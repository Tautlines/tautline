#!/usr/bin/env bash
# Runs after EVERY job (wired via ACTIONS_RUNNER_HOOK_JOB_COMPLETED).
#
# THIS IS HYGIENE, NOT A SECURITY BOUNDARY. Read that literally before relying on it.
#
# A non-ephemeral runner reuses one filesystem across every job, so state a job leaves behind can
# silently change how the NEXT job behaves: a stale $HOME/.gitconfig, a $HOME/.config/pip/pip.conf
# pointing at the wrong index, an interpreter left in the tool cache that a later job executes.
# Those cause confusing, hard-to-reproduce build failures, and wiping them is worth doing.
#
# What this CANNOT do is defend against a hostile job. Workflow steps run as the same `runner` user
# that owns $HOME, so a job can modify anything here -- including the very files this script
# preserves, before it ever runs. Restoring them faithfully restores the tampered copy. Four
# successive review rounds each found a new way around a cleanup-based boundary, all of them the
# same underlying fact: post-hoc cleanup by a user the job can impersonate is not isolation.
#
# That is acceptable HERE only because of the trust model, which is narrow and worth stating: this
# repository is private, and its only PR authors are the operator and dependabot. There is no
# untrusted code to isolate from. If that ever changes -- outside contributors, public forks with
# write access -- this script is NOT sufficient, and the runner must move to ephemeral mode
# (config.sh --ephemeral, one job per container) where no state survives a job at all. See
# README.md.
#
# The registration files are preserved because they are the runner's identity, created after the
# image-build snapshot; wiping them would deregister the runner on its first completed job.
#
# THE RUNNER DOES NOT EXECUTE THIS FILE THROUGH ITS SHEBANG. It runs it as
#
#     /usr/bin/bash --noprofile --norc -e -o pipefail {0}
#
# visible in every job log directly above this hook's output. So the `-e` is the INVOKER's, and it
# overrides what this script chooses for itself. Until that was understood, the first unguarded
# non-zero command aborted the script before the `exit 0` at the bottom, and the abort became the
# JOB's exit code -- defeating, in the most literal way, the contract stated at the end of this
# file. Measured: `Complete runner` was the failing step in half of the last 22 red
# `ci-python-full` runs on `experimental`, on jobs whose every real step had passed, and with
# `postMergeTier.enforcement` armed to `block` each one stopped every lane's merge.
#
# `set +e` drops the inherited errexit. The EXIT trap covers what `set +e` cannot -- a `-u`
# unbound-variable abort exits regardless of errexit. Both are needed; neither alone holds the
# contract, and tests/test_runner_job_cleanup_hook.py pins each one.
set -uo pipefail
set +e
trap 'exit 0' EXIT

# Report cleanup trouble instead of discarding it. Every failure-prone command here used to send
# stderr to /dev/null, so a failing hook logged `Process completed with exit code 1` and NOTHING
# about which command produced it -- which is why this defect was classified as a flake across 22
# runs instead of being read off the log. Not failing the job is correct; saying nothing is not.
warn() { printf 'job-cleanup: %s\n' "$*" >&2; }

# Run a cleanup step, capturing its output so a failure is reported rather than lost. Never
# propagates a non-zero status: that is the whole point of this file.
# Returns the command's status so a CALLER can distinguish fatal from best-effort. It never makes
# the SCRIPT exit -- `set +e` is off above and the exit code is decided at the bottom -- but
# swallowing the status outright is what let a failed identity copy fall through into the wipe.
try() {
    local what="$1"
    shift
    local output status
    output="$("$@" 2>&1)"
    status=$?
    if [ "${status}" -ne 0 ]; then
        warn "${what} failed: ${output}"
    fi
    return "${status}"
}

# Overridable ONLY so the test suite can exercise this script against throwaway directories. The
# runner sets neither, so the container behaviour is exactly the previous hardcoded pair. Without
# a seam the suite could assert nothing about a script whose real targets are $HOME and a
# root-owned snapshot -- which is why this file shipped untested and its contract went unheld.
#
# The names deliberately sit OUTSIDE the `RUNNER_` prefix, which is the runner's own namespace and
# is exported into this hook's environment (RUNNER_TEMP, RUNNER_TOOL_CACHE, RUNNER_WORKSPACE, ...).
# A `RUNNER_HOME_DIR` here would squat on it, and a future runner shipping that name would silently
# point this script's wipe-and-restore at a directory nobody chose.
# GATED BEHIND AN EXPLICIT SENTINEL, and Codex Stage 2 R2 is why. Reading the overrides
# unconditionally meant the PRODUCTION hook trusted them from whatever environment it was handed:
# anything that exported `JOB_CLEANUP_HOME_DIR` would silently redirect this script's wipe, and a
# `JOB_CLEANUP_PRISTINE_DIR` pointing nowhere would let the wipe run against the real home and then
# find nothing to restore. Moving off the `RUNNER_` prefix removed the likeliest collision but not
# the trust. With the sentinel, the production path is LITERALLY the pair that was hardcoded here
# before this release -- an override cannot be reached without deliberately asking for it.
if [ "${JOB_CLEANUP_TEST_MODE:-}" = "1" ]; then
    HOME_DIR="${JOB_CLEANUP_HOME_DIR:-/home/runner}"
    PRISTINE="${JOB_CLEANUP_PRISTINE_DIR:-/opt/runner-pristine}"
else
    HOME_DIR=/home/runner
    PRISTINE=/opt/runner-pristine
fi
# GUARDED, and the empty case is not hypothetical: with the inherited errexit dropped, a failed
# `mktemp -d` (missing or unwritable TMPDIR, full temp filesystem) would leave KEEP_DIR empty, and
# `${KEEP_DIR}/.` then expands to `/.` -- so the identity restore would copy the FILESYSTEM ROOT
# into $HOME, filling the runner's disk while still reporting success. `set -u` does not catch it
# because the variable is set, just empty. Codex Stage 2 R1.
KEEP_DIR="$(mktemp -d)" || KEEP_DIR=""
if [ -z "${KEEP_DIR}" ] || [ ! -d "${KEEP_DIR}" ]; then
    warn "could not create a scratch directory; skipping cleanup entirely rather than wipe \
$HOME with no way to restore the runner's identity"
    exit 0
fi

# Preserve everything config.sh generates at registration. The pristine snapshot is taken at IMAGE
# BUILD, before any registration exists, so every one of these is absent from it -- wiping without
# preserving them does not merely lose credentials, it unregisters the runner and strips the
# runtime files run.sh sources. This list was derived by diffing a registered home against the
# snapshot, not guessed:
#
#   .runner .credentials .credentials_rsaparams .env .path run-helper.sh svc.sh
#
# `.credentials*` stays a glob because the RSA parameter file's name has moved between runner
# versions, and an explicit name that missed it would break credential reload on the next start.
#
# Note this is an allowlist of what the RUNNER creates -- a known, enumerable set -- not of what a
# JOB might create, which is unbounded and is exactly why everything else is wiped rather than
# selectively cleaned.
# IDENTITY. The runner deregisters without these, so a failure to preserve one is FATAL to the
# cleanup: the wipe is skipped rather than run with no way to put the identity back. Dropping the
# inherited errexit removed the abort that used to cover this by accident -- it turned a red job
# into a DEREGISTERED RUNNER, which is worse. Codex Stage 2 R1.
identity_lost=0
for f in "${HOME_DIR}"/.runner "${HOME_DIR}"/.runner_migrated "${HOME_DIR}"/.credentials* \
         "${HOME_DIR}"/.env "${HOME_DIR}"/.path \
         "${HOME_DIR}"/run-helper.sh "${HOME_DIR}"/svc.sh; do
    if [ -e "${f}" ]; then
        try "preserving ${f}" cp -a "${f}" "${KEEP_DIR}/" || identity_lost=1
    fi
done

if [ "${identity_lost}" -ne 0 ]; then
    warn "could not preserve the runner's identity; skipping the wipe so the runner stays \
registered. The home is left dirty on purpose: stale state is recoverable, a deregistered \
runner is not."
    exit 0
fi

# The updater switches bin/externals symlinks to versioned directories while the listener is
# live. Never unlink/copy those directories or _diag: replacing an active executable leaves the
# listener running from a deleted inode, unable to launch its matching worker; replacing a log
# disconnects open file descriptors. The image snapshot may contain an OLDER runner version.
# Preserve these paths IN PLACE on BOTH sides of cleanup, while job leftovers/toolcache reset.
# `find -mindepth 1` keeps the home directory itself and its ownership intact.
try "wiping job leftovers in ${HOME_DIR}" find "${HOME_DIR}" -mindepth 1 -maxdepth 1 \
    ! -name bin ! -name 'bin.*' ! -name externals ! -name 'externals.*' ! -name _diag \
    -exec rm -rf {} +

if [ -d "${PRISTINE}" ]; then
    shopt -s dotglob nullglob
    for f in "${PRISTINE}"/*; do
        case "${f##*/}" in
            bin|bin.*|externals|externals.*|_diag) continue ;;
        esac
        try "restoring pristine ${f}" cp -a "${f}" "${HOME_DIR}/"
    done
else
    warn "pristine snapshot unavailable; could not restore job defaults"
fi

# Restore identity last, so it wins over anything the pristine copy might contain.
try "restoring runner identity" cp -a "${KEEP_DIR}/." "${HOME_DIR}/"
try "removing the scratch dir" rm -rf "${KEEP_DIR}"

# No chown: without sudo this cannot change ownership, and it does not need to -- every file the
# restore creates is written BY the runner user, so it is already runner-owned.

# Never fail the job on cleanup trouble: this hook's exit code becomes the JOB's exit code, so a
# permission error here would turn a green suite red for a reason unrelated to the change.
#
# This `exit 0` is no longer the only thing holding that promise, and it was never sufficient on
# its own -- reaching it at all depends on the `set +e` and the EXIT trap at the top of this file.
exit 0
