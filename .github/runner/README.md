# Local self-hosted CI runner

Per-PR CI runs on this repo's own hardware instead of on GitHub-hosted runners. GitHub does not
bill Actions minutes for machines it does not own, so the per-PR path costs **$0**.

## Why

Measured over Jul 23–30 2026, the hosted bill projected to **~$137/mo**, of which **93%** was the
two per-PR workflows (`ci-python` $23.42/wk, `validate` $6.53/wk). Those two moved here first.

As of the 3.12 floor raise, **`ci-python-full` reads `CI_RUNNER_LABEL` too** and runs here as well.
It could not before: its matrix carried a 3.10 leg, Ubuntu 24.04 ships only 3.12, and
`setup-python`'s portable CPython dies the moment a test spawns it as a subprocess. Raising the
floor removed the only leg that needed a second interpreter, and with it the only reason this
workflow had to stay hosted.

Everything below is about the workflows that read `CI_RUNNER_LABEL` — as of 2026-08-02 that is
`ci-python`, `ci-python-full`, `validate`, `npm-audit`, and `renderer-ci`. The remainder hardcode
`ubuntu-latest`:

- `publish-pypi`, `publish-npm` — deliberately so: a release must never depend on whether a laptop
  is awake. Reaffirmed by the operator on 2026-08-02 when everything else moved.
- `release-drift-check` — gated `if: github.repository == 'tautlines/tautline'`. It runs on the
  PUBLIC MIRROR and is skipped here, so it costs this repo nothing either way.
- `npm-audit`, `renderer-ci` — **moved to this runner on 2026-08-02.** They used to be described
  here as "cheap and infrequent, so there was no bill to save." That reasoning was overtaken by an
  operator instruction — *"i do not want any more billed hosted runs"* — which is categorical rather
  than a cost threshold.

  **The trade that move accepts, stated so it is a decision and not a surprise:** both run `npm ci`,
  which executes dependency lifecycle scripts, and the dependabot PRs that trigger them are exactly
  the ones introducing newly published package versions. The container protects the HOST (see
  "What the container does and does not protect"), so this is not host-user execution. The residual
  exposure is that jobs are **not** isolated from each other and this machine sits on the operator's
  LAN rather than being a disposable VM off it.

The speed is the second win, and it is not marginal: the suite takes **101 seconds** locally
against **18m45s** on a hosted 2-core runner.

## The split

| Workflow | Runs on | Why |
| --- | --- | --- |
| `ci-python`, `validate` | this runner | the expensive 93%, now $0 |
| `ci-python-full` | this runner | moved here once the 3.12 floor raise removed the leg that needed a second interpreter |
| `publish-pypi`, `publish-npm` | GitHub-hosted | releases must never depend on a laptop |
| `npm-audit`, `renderer-ci` | this runner | moved 2026-08-02; the last two workflows that actually billed here |
| `release-drift-check` | GitHub-hosted | mirror-only (`if: github.repository == 'tautlines/tautline'`); skipped on this repo |

Unsetting `CI_RUNNER_LABEL` sends **all five** of the rows above that read it — `ci-python`,
`ci-python-full`, `validate`, `npm-audit`, `renderer-ci` — back to `ubuntu-latest` together, but
**on this repo that now FAILS those runs** unless you also set `CI_ALLOW_HOSTED_FALLBACK=1`.
Clearing the label alone is no longer a supported move; see
[Falling back to hosted, deliberately](#falling-back-to-hosted-deliberately).

Only `publish-pypi`, `publish-npm` and `release-drift-check` hardcode `ubuntu-latest` and are
unaffected by the variable in either direction.

## Operating it

```bash
.github/runner/runner.sh up       # start (builds + registers on first run)
.github/runner/runner.sh status   # colima + container + what GitHub thinks
.github/runner/runner.sh logs     # follow the runner log
.github/runner/runner.sh stop     # stop; registration preserved
.github/runner/runner.sh destroy  # remove + deregister
```

## About the registration token

`up` mints one automatically on **first run only**. It is short-lived by design (~1 hour), and that
is not a burden to work around: `config.sh` immediately trades it for a long-lived credential that
the runner auto-rotates, so it is never needed again.

The container is created with `--restart unless-stopped` and is never `docker rm`-ed, so that
credential survives restarts **and host reboots**. A new token is required only after
`runner.sh destroy`.

The token is short-lived because it is a *bearer* credential: anyone holding it can attach an
arbitrary machine as a runner for this repo, which would let them read the source, read any secret
exposed to a job, and — worst — **report a forged green check**. Registration tokens also leak
easily, since they pass through terminals, shell history, and pasted logs. A one-hour window means
a leaked token is almost always already dead.

## How a job reaches this runner

None of the CI workflows hardcode a `self-hosted` label. They read a repo variable:

```yaml
runs-on: ${{ vars.CI_RUNNER_LABEL || 'ubuntu-latest' }}
```

This file ships in the public release export, so a hardcoded label would leave every fork of the
public mirror queueing forever against a runner it does not have — with no signal that anything is
wrong. **In a fork, unset still behaves exactly as it always did:** hosted CI, no complaints. That
is correct — hosted is the only compute a fork has.

**On this repo the unset case is no longer silent.** Every locally-routed job runs
`.github/actions/assert-runner-identity` immediately after checkout, and an unset `CI_RUNNER_LABEL`
here means the local runner was lost and every gate quietly moved onto billed compute while still
reporting green. That is the regression this whole setup exists to prevent, so the job fails with
a `::error` naming the fix rather than passing and saying nothing.

This repo sets `CI_RUNNER_LABEL=tautline`, matching the `tautline` label the container registers
with.

### Falling back to hosted, deliberately

The local machine is away, or you want a hosted verification. **Clearing the label alone now fails
the run** — that is the point of the assertion, and it cannot distinguish "the operator chose this"
from "the runner silently disappeared" unless you say so. Say so:

```bash
# To hosted: BOTH commands, or CI goes red.
gh variable set CI_ALLOW_HOSTED_FALLBACK --repo Tautlines/tautline-dev --body "1"
gh variable set CI_RUNNER_LABEL --repo Tautlines/tautline-dev --body ""

# Back to local: restore the label, then withdraw the exemption.
gh variable set CI_RUNNER_LABEL --repo Tautlines/tautline-dev --body "tautline"
gh variable delete CI_ALLOW_HOSTED_FALLBACK --repo Tautlines/tautline-dev
```

While the exemption is set, every affected job still prints a `::warning` that it ran on billed
compute — deliberate, so a hatch left open is visible in every run rather than discovered on an
invoice. Delete `CI_ALLOW_HOSTED_FALLBACK` as soon as the runner is back.

## Throughput

One container runs **one job at a time**. A PR triggers `validate` plus `ci-python`'s two jobs — and
since 2026-08-02, a PR touching the renderer-kit also triggers `renderer-ci` and `npm-audit`, so
those PRs now queue **five** jobs here rather than three. Concurrent PRs serialize rather than run
in parallel. At a 101s suite that is usually invisible, but
it is the first thing to look at if PRs start feeling queued.

To scale, start additional containers with distinct names — they share the labels, and GitHub hands
each queued job to whichever is free:

```bash
CONTAINER=tautline-runner-2 RUNNER_NAME=tautline-local-2 .github/runner/runner.sh up
```

## What the container does and does not protect

**It protects the host.** Jobs run inside the container, not on your machine. Without it a job —
including a dependabot PR running `pip install` / `npm ci` — would execute as your host user with
reach into your home directory, SSH keys, and login keychain. Inside the container it sees a blank
Ubuntu and the checkout. This is the reason the container exists, and it holds.

**It does not protect one job from another.** See the section below; that boundary is not provided
here, and the docs no longer claim it is.

The repo is private, so there are no untrusted fork PRs — the usual reason to avoid self-hosted
runners entirely.

### State between jobs

This runner is **not** ephemeral: one container serves many jobs, so anything a job writes would
otherwise outlive it. The tool cache is the sharp edge — `actions/setup-python` installs
interpreters there and *later jobs execute them*, so a poisoned dependency install could plant a
binary that a subsequent check runs as its own toolchain.

`job-cleanup.sh` runs after every job (via `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`) and restores the
home tree from `/opt/runner-pristine`, a copy taken at image build. It exists so one job's leftovers
cannot silently change how the next job behaves — a stale `.gitconfig`, a `pip.conf` pointing at the
wrong index, an interpreter left in the tool cache. Those produce confusing, hard-to-reproduce
failures, and clearing them is worth the ~10s `setup-python` spends re-downloading per job.

### This is hygiene, not a security boundary

Stated plainly, because an earlier draft of this file claimed otherwise and was wrong:

**The cleanup hook cannot defend against a hostile job.** Workflow steps run as the same `runner`
user that owns `$HOME`, so a job can modify anything there — including the files the hook preserves,
*before* the hook runs. Restoring them faithfully restores the tampered copy. Four successive review
rounds each found a different way around a cleanup-based boundary, every one of them the same
underlying fact: post-hoc cleanup performed by a user the job can impersonate is not isolation.
Container-level protections (root-owned hook, no passwordless sudo) raise the effort but do not
change that conclusion.

**Why that is acceptable here, and exactly when it stops being so.** This repository is private and
its only PR authors are the operator and dependabot. There is no untrusted code for the runner to
isolate itself from, so the property simply is not needed. That is a statement about *this repo's
trust model*, not about the design being sound in general.

If any of the following becomes true, this setup is **no longer sufficient** and the runner must
move to **ephemeral** mode — `config.sh --ephemeral`, one job per container, driven by a host-side
supervisor that mints a token per job, so no state survives a job at all:

- outside contributors gain write access, or PRs are accepted from forks
- the repository goes public with CI running on untrusted PRs
- secrets meaningfully beyond this repo's own scope become reachable from a job

Until then the honest summary is: the container protects the **host** (jobs cannot reach your home
directory, SSH keys, or keychain), and the cleanup hook protects **build reproducibility**. Neither
protects one job from another.

## When the machine is off

Queued jobs simply wait; the PR shows *queued* and nothing merges, because the merge gate refuses
anything not green. A job that never ran cannot pass. Start the runner and the queue drains.

`ci-python-full` now runs here too, so it is **no longer a hosted backstop** — when the machine is
off, no Python CI runs anywhere. (`npm-audit` and `renderer-ci` still run hosted, but neither
exercises the suite, so neither substitutes for one.) If you need a gate to run while the runner is
down, take the deliberate hosted fallback — set `CI_ALLOW_HOSTED_FALLBACK=1` **and** clear
`CI_RUNNER_LABEL`, per [Falling back to hosted, deliberately](#falling-back-to-hosted-deliberately)
— and the three Python CI workflows fall back to `ubuntu-latest`. Clearing the label on its own
fails every one of those runs by design.

## Rebuilding after any Dockerfile change

`up` builds only when the image is **absent**, so it will happily reuse a stale image after you edit
the `Dockerfile` — the runner then keeps running the old build with no warning. Any Dockerfile edit,
including a `RUNNER_VERSION` bump, needs an explicit rebuild:

```bash
.github/runner/runner.sh destroy
docker image rm tautline-runner:latest
.github/runner/runner.sh up
```

GitHub force-upgrades runners more than ~30 days behind, which surfaces as jobs refusing to start
rather than as silent drift.
