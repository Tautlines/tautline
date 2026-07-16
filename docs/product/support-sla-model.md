# Support, SLA, and Uninstall Model

Tautline **edits your machine**. `install-cli` writes a launcher shim, mutates global
`~/.claude/settings.json`, installs a `pre-push` git hook, and can self-update and re-exec
new code on lane start. The recommended launcher mode can even pass
`--dangerously-skip-permissions`, disabling the agent's interactive prompts. A tool with that
much reach owes its adopters a clear answer to one question: **when it breaks my lane, who do
I call — and how do I cleanly back it out?**

This document defines that answer across four surfaces: community (OSS) support, commercial
SLA tiers, incident response (security/CVE), and a clean uninstall story — including a
previewable `--dry-run` / `uninstall` path that never silently mutates global settings.

The running example is the fictional `example-saas` adapter. The CLI is invoked as
`tautline`. The behavior-test gate is `scripts/test.sh` (ruff + mypy + pytest).
`scripts/validate.sh` is a legacy grep-pin gate being frozen and is **not** a
support or security boundary.

> Status note: the preview and uninstall surface is shipped. `install-cli --dry-run`
> prints every mutation before a real install, and `uninstall-cli` (which also supports
> `--dry-run`) removes the installed CLI shim and `methodology.env`. The
> `~/.claude/settings.json` autocompact settings and any installed git guards are
> intentionally left in place — remove them by hand (§4c) for a full rollback. The parts
> of §4b's design that `uninstall-cli` does not yet cover (settings.json restore with
> backup, hook removal, `--keep-settings`) remain target design.

---

## 1. OSS community support (best-effort)

The open core is an MIT-licensed project supported by a community, not a paid help desk.
Community support is **best-effort, with no response-time guarantee.**

**Channels**

| Channel | Use it for | Expectation |
|---|---|---|
| GitHub **Discussions** | "how do I…", adapter design, runtime/tier questions, sharing setups | Best-effort; community + maintainers as time allows |
| GitHub **Issues** | reproducible bugs, false-blocks, install/uninstall failures, doc gaps | Triaged on a best-effort cadence; label-routed |
| **Security reports** | suspected vulnerabilities | **Do not** use Issues/Discussions — see §3 and `SECURITY.md` |

**Before you file an issue**

- Include `tautline version`, your platform, and your agent runtime
  (Claude vs Codex — enforcement differs by tier, see `docs/product/positioning.md`).
- State whether you ran with `--dangerously-skip-permissions` and whether auto-update was
  enabled, since both change the blast radius of a failure.
- For a false-block, paste the guard's in-band escape message. Every tool-blocking guard
  follows the guard-contract pattern (a fail-closed, always-runnable in-band escape); the
  message it prints is the fastest path to a fix and to a good bug report.
- Run `scripts/test.sh` if you changed anything locally; a failing gate output is a strong
  signal. Do not rely on `validate.sh` — it is frozen and not the gate.

**Issue triage labels (best-effort, no SLA)**

- `severity:critical` — data loss, RCE-class, or a guard that strands a lane with no escape.
- `severity:high` — a gate false-blocks legitimate work, or install/uninstall corrupts
  `settings.json` or a git hook.
- `severity:normal` / `severity:low` — everything else.
- `area:` labels route to the owning surface (`area:install`, `area:guard`,
  `area:adapter`, `area:render`).

**What community support explicitly does not cover:** guaranteed response times, private
support, your specific agent-spend/cost outcomes, or adapter authoring for proprietary
stacks. Those are the commercial surface (§2).

---

## 2. Commercial SLA tiers

The commercial offering is the hosted render/delivery service plus support — the open core
remains free and self-hostable. SLA tiers below set **response** targets (time to a human
acknowledging and engaging), not **resolution** targets, except where stated. Times are in
the customer's business hours unless an Enterprise 24/7 add-on is purchased.

| | **Community** | **Standard** | **Business** | **Enterprise** |
|---|---|---|---|---|
| Price model | Free (OSS) | Per-seat / monthly | Per-seat + team | Contract |
| Channel | GitHub Issues/Discussions | Email / portal | Portal + shared chat | Dedicated channel + named contact |
| Hours | Best-effort | Business hours | Business hours | Up to 24/7 (add-on) |
| **Critical** (lane-down, data-loss, RCE-class) | Best-effort | 1 business day | **4 business hours** | **1 hour** |
| **High** (gate false-blocks real work; settings/hook corruption) | Best-effort | 2 business days | 1 business day | 4 business hours |
| **Normal** (bug, doc gap) | Best-effort | 5 business days | 3 business days | 1 business day |
| **Low** (question, enhancement) | Best-effort | Best-effort | 5 business days | 3 business days |
| Private vuln handling | Public coordinated disclosure (§3) | Coordinated + advance notice | Coordinated + advance notice | Coordinated + pre-disclosure embargo briefing |
| Uninstall / migration help | Self-serve docs | Self-serve + email | Guided | Hands-on + named engineer |
| Hosted render/delivery uptime | n/a (self-host) | 99.0% target | 99.5% target | 99.9% (contractual) + status page |

**Severity definitions (shared with §1 triage so a community issue maps cleanly to a paid
ticket):**

- **Critical** — the engine prevents all forward progress on a lane with no working in-band
  escape, destroys/corrupts user files (`settings.json`, a git hook, an adapter), or exposes
  a remote-code-execution surface (see the auto-update trust class in `SECURITY.md`).
- **High** — a gate false-blocks legitimate work repeatedly, or install/uninstall leaves
  `settings.json` or a git hook in a broken-but-recoverable state.
- **Normal** — a defect with a viable workaround.
- **Low** — questions, docs, enhancements.

**Out-of-scope for all tiers:** vulnerabilities in software you choose to run alongside the
tool (your agent runtime, git, Python, the optional npm renderer toolchain), and any failure
that requires an already-compromised upstream you explicitly chose to trust — that is an
inherent property of the trust model documented in `SECURITY.md`, not a defect.

---

## 3. Incident response, CVE, and security advisories

Security is handled separately from normal support and is governed by **`SECURITY.md`**,
which is the authoritative source. This section summarizes how it ties into the support
model; the response targets and disclosure policy live in `SECURITY.md` and are not
duplicated here to avoid drift.

**Report a vulnerability — never via public Issues/Discussions.** Use GitHub **Private
Vulnerability Reporting** on the repository (`Security` tab → `Report a vulnerability`), or
email **security@minervit.ai**. Public disclosure before a fix exposes every adopter,
because installs run a live release artifact.

**Why this tool warrants a real process.** The highest-severity classes are in the trust
boundary documented in `SECURITY.md`:

- **Auto-update supply chain (Critical class):** lane start can pull and re-execute
  updated framework code, so a compromised upstream is the highest-severity exposure.
  The re-exec is gated by `verify_upstream_trust`: new installs default to the `pinned`
  update policy (`install-cli` writes the pin at the installed commit; advance it with
  `update-repin` after reviewing the incoming upstream commits), and a `signed` policy
  is available for commit/tag-signature trust. The residual risk is legacy installs
  without a policy env, which fall back to `warn` (updates proceed with a stderr
  warning) — set an explicit `pinned` or `signed` policy on any install tracking an
  upstream you do not fully control.
- **`--dangerously-skip-permissions` (High):** widens the blast radius of
  any upstream compromise; expert opt-in only, never the default.
  `install-claude-launcher` refuses to bake it into a launcher unless the effective
  update policy is `pinned` or `signed`, and the generated launcher re-checks the
  effective policy at every launch, refusing to start under `warn` or unverified
  policies.
- **Hook / launcher execution and `methodology.env` sourcing:** the resolved CLI is exec'd
  from a `pre-push` hook and a launcher, and `methodology.env` is currently `source`d as a
  shell script.

**Incident lifecycle (CVE-class).** Mapped to `SECURITY.md`'s stages: acknowledge receipt →
severity triage → fix or documented mitigation for Critical/High → coordinated public
disclosure. For CVE-eligible issues we request a CVE ID, publish a **GitHub Security
Advisory (GHSA)**, and ship the fix in a release adopters can verify through the `pinned`
or `signed` update policy before advancing their pin. Reporters are credited in release
notes unless they ask otherwise.

**How adopters consume advisories.** Watch the repository's Security Advisories, and treat
advisory notes in the release notes / `CHANGELOG` as actionable. Because installs run the
live release artifact, **updating to the latest fixed (and, once available, signed) release**
is the primary mitigation. Commercial tiers receive advance notice and, at Enterprise, a
pre-disclosure embargo briefing (§2).

---

## 4. Clean uninstall story

A tool that mutates global settings and installs a git hook **must** be cleanly removable —
and removal must be **previewable first** and **non-destructive to user-owned content.**
This is a hard requirement, not a nice-to-have.

### 4a. What `install-cli` changes (the exact surface to reverse)

`install-cli` (`bin/tautline`, `install_cli` at ~`:11904`) creates or mutates:

1. **The launcher shim** — `minervit-methodology` written into the chosen `--bin-dir`
   (a `/bin/sh` script that resolves the framework repo and `exec`s the real CLI).
2. **`methodology.env`** — `~/.config/tautline/tautline.env` (default), holding
   `TAUTLINE_METHODOLOGY_REPO`, autocompact percentages, and a `PATH` export. It also
   **preserves** any local user/project exports it found, so it is not always safe to delete
   wholesale.
3. **Global `~/.claude/settings.json`** — `write_claude_autocompact_settings` (~`:10720`)
   adds keys under `env`; the guard installers add **hooks** entries
   (`Stop` response-guard, `PreToolUse` plan-finalization and branch-liveness) via
   `write_claude_*_hook` (~`:10755`–`:10799`). These are **appended into a file the user
   also owns** — the central reason uninstall must be surgical, not a file delete.
4. **A `pre-push` git hook** — in the target repo's hooks dir. An existing hook is **moved to
   `<hook>.before-minervit`** and wrapped (`git_branch_liveness_hook_content` ~`:10879`,
   install logic ~`:11015`–`:11022`), so the original is recoverable.
5. **A framework release guard** — `install_methodology_release_guards` (~`:6427`).

### 4b. Target `uninstall-cli` design

Ship a first-class inverse command:

```
tautline uninstall-cli [--dry-run] [--keep-settings] [--target <repo>]
```

- **`--dry-run` (must also be added to `install-cli`).** Prints every change that *would* be
  made or reversed — file paths, the specific `settings.json` keys/hooks to be removed, and
  the git hook to be restored — and **makes no change**. This mirrors the existing
  `--dry-run` discipline already used across publish/iteration-review paths, so it is a
  consistent flag, not a new concept. **No machine-mutating command should run without a
  `--dry-run` preview available first.**
- **Surgical `settings.json` restore.** Remove **only** the keys and hook entries this tool
  added (matched by the same `settings_*_installed` predicates used at install, e.g.
  `settings_response_guard_hook_installed`), preserving all user-authored keys, env, and
  hooks. Write a timestamped backup (`settings.json.before-minervit-uninstall`) before
  editing. `--keep-settings` skips this step for operators who manage settings by hand.
- **Restore the git hook.** If a `<hook>.before-minervit` backup exists, move it back into
  place; otherwise remove the minervit-installed `pre-push` hook. Never delete a hook the
  tool did not write.
- **Remove the shim, `methodology.env`, and release guard.** Delete the launcher shim and the
  release guard. For `methodology.env`, strip only the minervit-generated block and **keep
  the preserved user/project exports** (or move the file to `.bak` and report it) rather than
  deleting secrets the operator still needs.
- **Leave the framework checkout alone.** Uninstall removes the *integration*, not your
  cloned repo or your adapter; the operator deletes those explicitly if they choose.
- **Idempotent and fail-closed.** Re-running uninstall is safe; if any step cannot be
  reversed safely it reports the manual step rather than guessing.

### 4c. Manual cleanup of what `uninstall-cli` leaves in place

`uninstall-cli` removes the CLI shim and `methodology.env`; the remaining integration
points are removed manually, and the steps are fully deterministic:

1. **Remove the hook entries from `~/.claude/settings.json`.** Back up the file first, then
   delete the `Stop` / `PreToolUse` hook entries whose `command` invokes
   `tautline` or the legacy `minervit-methodology` (response-guard, plan-finalization, branch-liveness), plus the
   autocompact keys this tool added under `env`. Leave everything else intact.
2. **Restore or remove the `pre-push` hook.** In the affected repo's hooks dir: if
   `pre-push.before-minervit` exists, move it back to `pre-push`; otherwise delete the
   minervit `pre-push` hook.
3. **Remove the launcher shim** from your `--bin-dir` (and the `PATH` export it added in
   `methodology.env`).
4. **Clean `~/.config/tautline/tautline.env`** — delete the minervit-generated lines but
   keep any "Preserved local user/project environment" block you still rely on.
5. **Disable auto-update** by removing the launcher and not running lanes from inside the
   methodology checkout's resolution path. Re-confirm with `tautline version` no
   longer resolving (or removing the checkout if you are fully done).

After manual removal, your agent runtime returns to its prior state: interactive permission
prompts are back, no lane gates run on push, and no code self-updates on launch.

---

## 5. Cross-references

- **`SECURITY.md`** — authoritative reporting process, response-time targets, the
  hook-execution trust model, auto-update safety, and supply-chain posture.
- **`docs/product/positioning.md`** — the enforcement tiers (Claude blocking vs ship-time
  gates) that determine how a failure manifests per runtime.
- This model's incident process is built around the same trust boundary and supply-chain
  posture documented in `SECURITY.md`.
