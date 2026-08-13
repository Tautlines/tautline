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
set -uo pipefail

HOME_DIR=/home/runner
PRISTINE=/opt/runner-pristine
KEEP_DIR="$(mktemp -d)"

# Preserve everything config.sh generates at registration. The pristine snapshot is taken at IMAGE
# BUILD, before any registration exists, so every one of these is absent from it -- wiping without
# preserving them does not merely lose credentials, it unregisters the runner and strips the
# runtime files run.sh sources. This list was derived by diffing a registered home against the
# snapshot, not guessed:
#
#   .runner .credentials .credentials_rsaparams .env .path _diag run-helper.sh svc.sh
#
# `.credentials*` stays a glob because the RSA parameter file's name has moved between runner
# versions, and an explicit name that missed it would break credential reload on the next start.
#
# Note this is an allowlist of what the RUNNER creates -- a known, enumerable set -- not of what a
# JOB might create, which is unbounded and is exactly why everything else is wiped rather than
# selectively cleaned.
for f in "${HOME_DIR}"/.runner "${HOME_DIR}"/.runner_migrated "${HOME_DIR}"/.credentials* \
         "${HOME_DIR}"/.env "${HOME_DIR}"/.path "${HOME_DIR}"/_diag \
         "${HOME_DIR}"/run-helper.sh "${HOME_DIR}"/svc.sh; do
    [ -e "${f}" ] && cp -a "${f}" "${KEEP_DIR}/" 2>/dev/null
done

# Wipe everything, dotfiles included, then restore the pristine tree. `find -mindepth 1` rather than
# `rm -rf ${HOME_DIR}` so the directory itself -- and its ownership -- survives.
find "${HOME_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
cp -a "${PRISTINE}/." "${HOME_DIR}/" 2>/dev/null || true

# Restore identity last, so it wins over anything the pristine copy might contain.
cp -a "${KEEP_DIR}/." "${HOME_DIR}/" 2>/dev/null || true
rm -rf "${KEEP_DIR}"

# No chown: without sudo this cannot change ownership, and it does not need to -- every file the
# restore creates is written BY the runner user, so it is already runner-owned.

# Never fail the job on cleanup trouble: this hook's exit code becomes the JOB's exit code, so a
# permission error here would turn a green suite red for a reason unrelated to the change.
exit 0
