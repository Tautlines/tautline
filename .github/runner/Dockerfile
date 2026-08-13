# A disposable Linux box that runs this repo's per-PR CI on local hardware instead of on
# GitHub-hosted (billed) runners. See README.md in this directory for the why and the operations.
#
# The container exists to protect the HOST, not just for Linux parity: without it, a job --
# including a dependabot PR running `pip install` / `npm ci` -- would execute as the host user, with
# reach into the home directory, SSH keys, and login keychain. Inside here it sees a blank Ubuntu
# and the checkout, and nothing else.
#
# It does NOT isolate one job from another: jobs run as the user that owns the runner install, so
# they can tamper with anything in $HOME, the post-job cleanup hook's inputs included. See
# job-cleanup.sh and README.md, which state the trust model this setup actually relies on.
FROM ubuntu:24.04

# Bumping this is the whole upgrade procedure; GitHub force-upgrades runners more than ~30 days
# behind, so a stale pin here shows up as jobs that refuse to start rather than as a silent drift.
ARG RUNNER_VERSION=2.336.0
# The host is Apple silicon, so the default is arm64. Kept as an ARG so an x86 machine can build
# the same image with --build-arg RUNNER_ARCH=x64.
ARG RUNNER_ARCH=arm64

ENV DEBIAN_FRONTEND=noninteractive

# libicu is a hard runtime dependency of the runner's bundled .NET host -- without it the runner
# starts and then dies with a stack trace that does not name the missing library.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq sudo unzip zip tar gzip \
        python3 python3-pip python3-venv \
        build-essential \
        libicu74 \
    && rm -rf /var/lib/apt/lists/*

# The GitHub CLI. GitHub-HOSTED runners ship a large preinstalled toolset -- gh among it -- and a
# self-hosted image starts empty, so anything the suite shells out to has to be added explicitly.
# Several tests invoke `gh` and fail with FileNotFoundError without it; that gap is invisible on
# hosted runners and invisible locally on a developer machine that has gh installed, which is
# exactly the class of difference a self-hosted migration has to close deliberately.
RUN set -eux; \
    mkdir -p -m 755 /etc/apt/keyrings; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends gh; \
    rm -rf /var/lib/apt/lists/*; \
    gh --version

# System-wide git identity and ownership policy.
#
# Hosted runners get both implicitly -- actions/checkout writes a local identity and marks the
# workspace safe -- so tests that build throwaway git repos in tmpdirs inherit a usable environment
# there and find nothing here. Without an identity, `git commit` inside those fixtures aborts with
# "Please tell me who you are"; without safe.directory, git refuses to operate on trees whose owner
# does not match the invoking user, which is easy to hit when files arrive via docker cp or a
# restored snapshot.
#
# --system rather than --global so it survives the post-job home reset, which restores /home/runner
# from the pristine snapshot and would discard a ~/.gitconfig written at build time.
RUN set -eux; \
    git config --system user.name  "tautline-runner"; \
    git config --system user.email "runner@tautline.invalid"; \
    git config --system init.defaultBranch main; \
    git config --system --add safe.directory '*'; \
    git config --system --list

# The runner refuses to execute as root and exits immediately if you try.
#
# NO passwordless sudo. An earlier revision granted it so third-party actions could
# `sudo apt-get install`; it is withheld now simply because nothing in this repo's workflows needs
# it, and handing every job root on the machine that grades it buys nothing in return.
#
# This is least-privilege, not a claimed isolation boundary -- see job-cleanup.sh and README.md,
# which are explicit that a job running as the `runner` user can already tamper with anything in
# $HOME regardless. Withholding root just keeps the blast radius smaller.
#
# The consequence is real and accepted: an action that shells out to sudo will fail here, loudly
# and diagnosably. Fix the workflow, or move to an ephemeral runner.
RUN useradd -m -s /bin/bash runner
WORKDIR /home/runner

RUN curl -fsSL -o runner.tar.gz \
        "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" \
    && tar xzf runner.tar.gz \
    && rm runner.tar.gz \
    && chown -R runner:runner /home/runner

# actions/setup-python downloads an interpreter on first use and caches it here. Pointing this at a
# path the run script mounts as a named volume is what keeps that download a one-time cost instead
# of a per-job one.
ENV RUNNER_TOOL_CACHE=/home/runner/tool-cache
RUN mkdir -p /home/runner/tool-cache /home/runner/_work \
    && chown -R runner:runner /home/runner/tool-cache /home/runner/_work

# Pre-seed the tool cache with the DISTRO's Python so actions/setup-python resolves locally instead
# of downloading its portable build.
#
# This is not an optimisation, it is a correctness fix. setup-python's portable CPython is
# dynamically linked against libpython3.12.so.1.0, which lives inside its own tool-cache directory
# and is not on the loader path. The interpreter therefore works for the step that sets it up but
# dies with "error while loading shared libraries" the moment a test spawns it as a SUBPROCESS --
# which this suite does constantly. That produced 531 failures on the first real self-hosted run
# while the same commit was green on GitHub-hosted runners.
#
# Ubuntu 24.04 ships Python 3.12 as its system python, already linked against libraries on the
# default loader path, so a subprocess launch just works. setup-python finds this layout
# (Python/<version>/<arch> plus the sibling <arch>.complete marker) and skips the download entirely.
#
# Ordering matters: this runs BEFORE the pristine snapshot below, so the post-job cleanup restores
# the seed instead of wiping it.
# Seeded as a VENV, not as symlinks to /usr/bin. Two things break with symlinks, both fatal:
# Ubuntu marks its system Python PEP 668 externally-managed, so `pip install -r requirements-dev.txt`
# refuses outright; and even without that marker, site-packages is root-owned while jobs run as
# `runner` with no sudo, so the install could not write anywhere. A venv is writable by the job,
# accepts pip normally, and still uses the system interpreter underneath -- which is the whole point,
# since that interpreter's libpython is on the default loader path and therefore survives being
# spawned as a subprocess.
RUN set -eux; \
    PYVER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in arm64) TC_ARCH=arm64 ;; amd64) TC_ARCH=x64 ;; *) echo "unsupported ${ARCH}" >&2; exit 1 ;; esac; \
    TC_DIR="/home/runner/tool-cache/Python/${PYVER}/${TC_ARCH}"; \
    python3 -m venv "${TC_DIR}"; \
    "${TC_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel; \
    touch "/home/runner/tool-cache/Python/${PYVER}/${TC_ARCH}.complete"; \
    chown -R runner:runner /home/runner/tool-cache; \
    "${TC_DIR}/bin/python" -c 'import sys; print("seeded", sys.version)'; \
    "${TC_DIR}/bin/python" -m pip --version

# A pristine copy of the runner install, taken BEFORE any job can touch it and owned by root so no
# job can edit it. job-cleanup.sh restores from here after every job, which is what makes the reset
# cover the WHOLE home tree -- stray dotfiles like .gitconfig or .config/pip/pip.conf, and the
# runner's own writable `externals` tree -- rather than an allowlist of paths someone remembered.
# An allowlist is whack-a-mole; anything a job writes that nobody predicted survives it.
RUN cp -a /home/runner /opt/runner-pristine \
    && chown -R root:root /opt/runner-pristine \
    && chmod -R go-w /opt/runner-pristine

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY job-cleanup.sh /usr/local/bin/job-cleanup.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/job-cleanup.sh

# Run job-cleanup.sh after every job, so no job inherits the previous one's work tree or tool cache.
# Owned by root and NOT writable by the runner user -- a hook a job could rewrite would be a hook
# that disables its own cleanup.
ENV ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/usr/local/bin/job-cleanup.sh

USER runner
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
