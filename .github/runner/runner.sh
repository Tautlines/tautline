#!/usr/bin/env bash
# Lifecycle for the local self-hosted CI runner. See README.md in this directory.
#
#   ./runner.sh up        build the image if needed, register on first run, start the runner
#   ./runner.sh status    is colima up, is the container up, is GitHub seeing the runner as online
#   ./runner.sh logs      follow the runner's log
#   ./runner.sh stop      stop the runner (registration is PRESERVED; `up` needs no new token)
#   ./runner.sh destroy   remove the container and deregister (a new token is needed after this)
set -euo pipefail

REPO_SLUG="${REPO_SLUG:-Tautlines/tautline-dev}"
REPO_URL="https://github.com/${REPO_SLUG}"
IMAGE="tautline-runner:latest"
# Overridable so a second runner can be started for parallel throughput; see README.md. Both must
# be changed together, since a distinct RUNNER_NAME with a colliding CONTAINER would just restart
# the existing one, and a distinct CONTAINER with a colliding RUNNER_NAME would take over the same
# GitHub registration via --replace instead of adding capacity.
CONTAINER="${CONTAINER:-tautline-runner}"
RUNNER_NAME="${RUNNER_NAME:-tautline-local}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,linux,tautline}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "error: $*" >&2; exit 1; }

ensure_colima() {
    command -v colima >/dev/null || die "colima not installed (brew install colima docker)"
    if ! colima status >/dev/null 2>&1; then
        echo "starting colima..."
        # The suite is process-parallel, so the VM is sized for it; without explicit --cpu the VM
        # takes a small default and the local run is SLOWER than the hosted runner it replaces.
        colima start --cpu 8 --memory 16 --disk 60
    fi
    docker info >/dev/null 2>&1 || die "docker daemon unreachable even though colima is up"
}

cmd_up() {
    ensure_colima

    if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
        # Derive the runner architecture from the DOCKER HOST, not from the Dockerfile's default.
        # `up` is the documented build path, so on an x86 host the arm64 default would quietly
        # download an arm64 runner into an amd64 image -- a build that succeeds and then dies the
        # first time config.sh executes, which reads as a broken runner rather than a wrong binary.
        local docker_arch runner_arch
        docker_arch="$(docker info --format '{{.Architecture}}' 2>/dev/null || echo unknown)"
        case "${docker_arch}" in
            aarch64|arm64)  runner_arch=arm64 ;;
            x86_64|amd64)   runner_arch=x64 ;;
            *) die "unsupported docker host architecture '${docker_arch}'; build manually with --build-arg RUNNER_ARCH=<arm64|x64>" ;;
        esac
        echo "building ${IMAGE} for ${docker_arch} (RUNNER_ARCH=${runner_arch})..."
        docker build --build-arg "RUNNER_ARCH=${runner_arch}" -t "${IMAGE}" "${HERE}"
    fi

    if docker container inspect "${CONTAINER}" >/dev/null 2>&1; then
        # The container already holds a valid credential, so this path never mints a token.
        echo "container exists; starting it (registration preserved, no token needed)"
        docker start "${CONTAINER}" >/dev/null
        echo "runner started."
        return
    fi

    # First run only: mint a registration token. It is passed as an env var on `docker create` and
    # is consumed once by config.sh; it expires within the hour regardless.
    command -v gh >/dev/null || die "gh CLI required to mint a registration token"
    echo "minting registration token for ${REPO_SLUG}..."
    local token
    token="$(gh api -X POST "/repos/${REPO_SLUG}/actions/runners/registration-token" --jq .token)" \
        || die "could not mint a registration token (needs repo admin)"

    # The token is deliberately NOT passed with -e. A container-level env var is baked into the
    # container's config for its whole life: `docker inspect` shows it, and every job the runner
    # executes inherits it -- so any job running inside the token's ~1h lifetime could read it and
    # register a runner of its own against this repo. Instead it is copied in as a file that
    # entrypoint.sh consumes once and shreds, so it never enters container config or job env.
    docker create \
        --name "${CONTAINER}" \
        --restart unless-stopped \
        -e REPO_URL="${REPO_URL}" \
        -e RUNNER_NAME="${RUNNER_NAME}" \
        -e RUNNER_LABELS="${RUNNER_LABELS}" \
        "${IMAGE}" >/dev/null

    # Copied to a path INSIDE the runner's own home, because with passwordless sudo removed the
    # runner user must be able to both read and delete this itself -- deleting needs write on the
    # containing directory, which it has for its home and does not have for /run.
    #
    # World-readable for the moment it exists, which is safe here in a way an env var never was:
    # entrypoint.sh consumes and shreds it BEFORE run.sh starts, so no job can ever coexist with
    # it. The env var, by contrast, persisted for the container's whole life and was inherited by
    # every job.
    local token_file
    token_file="$(mktemp)"
    # Armed BEFORE the token is written, and on EXIT rather than RETURN: `set -e` turns a failed
    # `docker cp` into a shell exit, which a RETURN trap does not reliably catch, and a Ctrl-C
    # during the copy catches neither. Without it that abort leaves a world-readable bearer token
    # in the host's shared /tmp for the rest of its ~1h life -- long enough for any other local
    # user to enrol a runner that reports checks for this repo.
    trap 'rm -f "${token_file}"' EXIT INT TERM
    printf '%s' "${token}" > "${token_file}"
    chmod 644 "${token_file}"
    unset token
    docker cp "${token_file}" "${CONTAINER}:/home/runner/.runner-token" >/dev/null
    rm -f "${token_file}"
    trap - EXIT INT TERM

    docker start "${CONTAINER}" >/dev/null
    echo "runner created and started as '${RUNNER_NAME}'."
}

cmd_status() {
    if colima status >/dev/null 2>&1; then echo "colima:    running"; else echo "colima:    STOPPED"; fi

    if docker container inspect "${CONTAINER}" >/dev/null 2>&1; then
        echo "container: $(docker inspect -f '{{.State.Status}}' "${CONTAINER}")"
    else
        echo "container: ABSENT (run './runner.sh up')"
    fi

    # The authoritative view: what GitHub itself believes. A container that is "running" while
    # GitHub reports the runner offline is the failure this line exists to catch.
    if command -v gh >/dev/null; then
        gh api "/repos/${REPO_SLUG}/actions/runners" \
            --jq '.runners[] | "github:    \(.name) is \(.status) busy=\(.busy) labels=[\([.labels[].name] | join(","))]"' \
            2>/dev/null || echo "github:    (could not query)"
    fi
}

cmd_logs()    { docker logs -f "${CONTAINER}"; }
cmd_stop()    { docker stop "${CONTAINER}" >/dev/null && echo "stopped (registration preserved)"; }

cmd_destroy() {
    # Deregisters AND removes, so the repo's runner list does not keep a permanently-offline entry.
    #
    # Ordering matters here. `config.sh remove` only runs inside a LIVE container, so a destroy that
    # follows `stop` cannot exec into it; swallowing that failure and removing the container anyway
    # would delete the only stored credential while still registered, which is precisely the stale
    # entry this command promises not to leave. So: restart it if stopped, remove from inside, and
    # then verify against the API rather than trusting the exec.
    command -v gh >/dev/null || die "gh CLI required to deregister"

    if docker container inspect "${CONTAINER}" >/dev/null 2>&1; then
        if [ "$(docker inspect -f '{{.State.Status}}' "${CONTAINER}")" != "running" ]; then
            docker start "${CONTAINER}" >/dev/null 2>&1 || true
        fi
        local token
        if token="$(gh api -X POST "/repos/${REPO_SLUG}/actions/runners/remove-token" --jq .token 2>/dev/null)"; then
            docker exec "${CONTAINER}" ./config.sh remove --token "${token}" >/dev/null 2>&1 || true
        fi
        docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    fi

    # Belt and braces: if the in-container removal never happened -- container already gone, the
    # credential unreadable, a job in flight -- delete the registration through the API so this
    # command's promise holds even when the container cannot speak for itself.
    local id
    id="$(gh api "/repos/${REPO_SLUG}/actions/runners" \
            --jq ".runners[] | select(.name==\"${RUNNER_NAME}\") | .id" 2>/dev/null | head -1)"
    if [ -n "${id}" ]; then
        gh api -X DELETE "/repos/${REPO_SLUG}/actions/runners/${id}" >/dev/null 2>&1 \
            && echo "deregistered '${RUNNER_NAME}' via API (in-container removal did not take)"
    fi

    echo "destroyed. './runner.sh up' will mint a fresh token and re-register."
}

case "${1:-}" in
    up)      cmd_up ;;
    status)  cmd_status ;;
    logs)    cmd_logs ;;
    stop)    cmd_stop ;;
    destroy) cmd_destroy ;;
    *)       sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
