#!/usr/bin/env bash
# Configure this runner against the repo on FIRST start only, then hand off to the runner's own
# long-poll loop.
#
# The registration token is needed exactly once in the container's lifetime. `config.sh` trades it
# for a long-lived credential in ./.credentials, which the runner then auto-rotates on its own; the
# short-lived token is never referenced again. Because the container is created with
# `--restart unless-stopped` and never `docker rm`-ed, that credential survives restarts and host
# reboots -- so a reboot does NOT require minting a new token.
#
# Correspondingly, this script deliberately does NOT deregister on exit. A trap that ran
# `config.sh remove` would throw away the credential on every stop and make a fresh token mandatory
# for every start, which is the failure mode this design is avoiding.
set -euo pipefail

REPO_URL="${REPO_URL:?REPO_URL is required (e.g. https://github.com/Tautlines/tautline-dev)}"
RUNNER_NAME="${RUNNER_NAME:-tautline-local}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,linux,tautline}"

cd /home/runner

TOKEN_FILE=/home/runner/.runner-token

if [ ! -f .runner ]; then
    # The token arrives as a FILE, never as an env var: an env var would live in container config
    # for the container's whole life and be inherited by every job, so any job running inside the
    # token's ~1h lifetime could read it and register a runner of its own. Read it, then shred it
    # before the runner ever accepts work.
    [ -f "${TOKEN_FILE}" ] || {
        echo "no registration token at ${TOKEN_FILE}; run runner.sh up" >&2
        exit 1
    }
    # No sudo anywhere in this container by design (see Dockerfile), so the token lands somewhere
    # the runner user can read and delete unaided. Shredded immediately, before run.sh accepts any
    # work, so no job ever coexists with it.
    RUNNER_TOKEN="$(cat "${TOKEN_FILE}")"
    rm -f "${TOKEN_FILE}"

    # --replace so re-registering after a deliberate `docker rm` takes over the existing runner
    # entry instead of accumulating dead duplicates in the repo's runner list.
    ./config.sh --unattended --replace \
        --url "${REPO_URL}" \
        --token "${RUNNER_TOKEN}" \
        --name "${RUNNER_NAME}" \
        --labels "${RUNNER_LABELS}" \
        --work /home/runner/_work

    # Belt and braces: RUNNER_TOKEN is a plain shell variable, never exported, so `exec ./run.sh`
    # would not pass it on regardless -- but clear it so no later edit can make it leak by adding
    # an export somewhere above.
    unset RUNNER_TOKEN

    echo "runner registered as '${RUNNER_NAME}' with labels: ${RUNNER_LABELS}"
else
    echo "runner already registered; reusing stored credential"
fi

# Clear any checkout left by a PREVIOUS CONTAINER LIFETIME. This runs once at start, not between
# jobs -- per-job cleanliness is actions/checkout's job (it resets the work tree on every run), and
# this only guards against a container that was stopped mid-job leaving a half-written tree behind.
rm -rf /home/runner/_work/* 2>/dev/null || true

# exec so the runner is PID 1 and receives SIGTERM directly from `docker stop`, letting it finish
# or cleanly abandon an in-flight job instead of being killed after the timeout.
exec ./run.sh
