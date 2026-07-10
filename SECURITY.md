# Security Policy

This project ships software that **executes code on your machine** and can **modify your
local environment** (it installs a launcher, writes git hooks, and can self-update from an
upstream git remote). Because of that, the security model below is not boilerplate — it
defines the trust boundary you accept when you adopt Tautline. Read the
[Hook-Execution Trust Model](#hook-execution-trust-model) before installing.

The running example throughout is the fictional `example-saas` adapter. The CLI is invoked
as `tautline`; the legacy `minervit-methodology` name keeps working as a compatibility shim.

---

## Reporting a Vulnerability

We practice **coordinated disclosure**. Please do **not** open a public GitHub issue, pull
request, or discussion for a suspected vulnerability — that exposes other adopters before a
fix exists.

**How to report**

- Preferred: use **GitHub Private Vulnerability Reporting** on this repository
  (`Security` tab → `Report a vulnerability`).
- Alternative: email the maintainers at **security@minervit.com** with a clear subject line
  and, if possible, a minimal reproduction.

**What to include**

- The affected version (`tautline version`) and platform.
- A description of the impact and the trust boundary it crosses (e.g. auto-update,
  hook execution, secret handling, tenancy/isolation).
- A reproduction or proof-of-concept where feasible.

**Response targets (SLAs).** These are good-faith targets for a community-run open-source
project, measured in business days:

| Stage | Target |
|---|---|
| Acknowledge receipt | within **3 business days** |
| Initial severity triage | within **7 business days** |
| Fix or documented mitigation for Critical/High | within **30 days** of triage |
| Coordinated public disclosure | by mutual agreement, typically **≤ 90 days** |

We credit reporters in the release notes unless you ask us not to. We support a coordinated
embargo window and will keep you updated through the fix.

**Supported versions.** Security fixes target the latest released version (currently the
`0.6.x` line). Because installs run the live release artifact, the most reliable mitigation
is to update to the latest signed release once one is available (see
[Supply-Chain Posture](#supply-chain-posture-signing--provenance)).

---

## Hook-Execution Trust Model

> **You must trust the origin of your framework checkout.** Adopting this tool means
> granting the upstream you point it at the ability to run code as your user.

This is the most important section of this document. The framework's enforcement works by
executing a resolved CLI from hooks and a launcher. Those execution paths are intentional
and load-bearing — but they mean **the code that runs is whatever your configured checkout
resolves to**, so the integrity of that checkout is your responsibility.

### Where code gets executed

1. **The generated launcher** (`install-claude-launcher`). The launcher is a `/bin/sh`
   script that resolves the framework repository, runs `sync-methodology`, runs
   `lane-start` / `methodology-status`, and finally `exec`s your agent
   (`bin/minervit-methodology`, `claude_launcher_content`). Resolution order is:
   an operator-set `MINERVIT_METHODOLOGY_REPO` preset, then a **cwd-ancestor walk for any
   directory named `minervit-ai-delivery-methodology`**, then the `methodology.env`
   fallback. The cwd-walk step is convenient but means that **a
   directory of that name planted under your working tree can be adopted as the privileged
   checkout**. Prefer an operator-controlled `MINERVIT_METHODOLOGY_REPO` /
   `methodology.env` and do not run lanes from directories you do not control.

2. **The pre-push git hook.** `install-cli` writes a `pre-push` hook that invokes the
   resolved CLI to run blocking gates (review-evidence, board-currency, CI-health) before a
   push is allowed. The hook executes the same resolved CLI as the launcher. A compromised checkout therefore
   compromises every `git push` from that repository.

3. **`methodology.env`.** The launcher currently **`source`s** `~/.config/minervit/methodology.env`
   as a shell script rather than parsing it as strict `KEY=VALUE`
   pairs. Any code in that file runs at launch. Treat `methodology.env` as
   trusted, write it `0600`, and never accept one from an untrusted source. The target
   hardening is a strict non-executing parser plus a CLI fingerprint check.

### What this means for adopters

- **Pin your upstream to an origin you trust.** Today, consumption is the live git working
  tree of a checkout you control. If you point that checkout at a third-party fork or a
  shared upstream, you are trusting that party with code execution as your user on every
  lane start and every push.
- **Control the resolution path.** Set `MINERVIT_METHODOLOGY_REPO` explicitly. Do not rely
  on the cwd-ancestor walk in shared or multi-user directories.
- **Protect `methodology.env`.** Keep it `0600` and owned by you.

These behaviors are documented, not hidden, and the planned hardening is described below.

---

## Auto-Update Safety

The CLI can update itself. On lane start, `update_methodology_repo` runs `git pull --ff-only`
and, when the HEAD advances, **re-executes the new code in place via `os.execve`** so the
just-pulled version handles the rest of the command. The launcher's auto-rescue path uses the
same re-exec. Every one of those re-exec points is gated by `verify_upstream_trust`, which
decides whether the freshly-fetched HEAD may run **before** `os.execve`.

**The trust gate.** `verify_upstream_trust` reads
`MINERVIT_METHODOLOGY_UPDATE_POLICY`, which selects one of four levers:

- **`signed`** — the new HEAD must carry a valid signature (`git verify-commit`), optionally
  from a key on the `MINERVIT_METHODOLOGY_UPDATE_SIGNERS` allowlist. An unsigned or
  wrongly-signed HEAD **fails closed** (the re-exec is refused).
- **`pinned`** — the new HEAD must match a commit in the pin allowlist
  (`MINERVIT_METHODOLOGY_UPDATE_PINS`, or `~/.config/minervit/methodology.update-pins`). Any
  other HEAD **fails closed**. A `pinned` policy with no configured pins also fails closed.
- **`unverified`** — an explicit opt-out for a single trusted operator on a trusted machine:
  the re-exec proceeds silently with no verification.
- **`warn`** — allows the update but prints a loud stderr warning recommending a strict
  policy. This is the backward-compatible default for installs that never set a policy.

**New installs default to `pinned`.** `install-cli` writes
`MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned` plus a pin equal to the commit it installed from
into `methodology.env`, so a fresh install fails closed on any unexpected upstream. After you
review incoming upstream commits, `update-repin` advances the pin to the current
`origin/<branch>` HEAD and prints the commit range you are now trusting. Use
`install-cli --update-policy {signed,pinned,warn,unverified}` to choose a different lever at
install time.

**Legacy residual risk.** A pre-existing install that has **no** policy env — created before
pinned-by-default — falls back to `warn` at runtime. `warn` **allows** the update and
re-executes the new code after only a stderr warning; it does not fail closed. Such installs
keep working, but they carry the original unverified-upstream exposure until the operator sets
a strict policy (re-run `install-cli`, or export `MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned`
or `=signed`). If the upstream you track is compromised, a `warn`/`unverified` install will
pull and execute the attacker's code as your user; because many adopters can point at a shared
upstream, that remains a fleet-wide remote code execution surface for those installs.

You can also skip the update path operationally (e.g. `--skip-update`, or running from inside
the framework repo, which short-circuits the pull).

### `--dangerously-skip-permissions` is opt-in, expert-only

The generated launcher can be installed to pass `--dangerously-skip-permissions` to the agent
(`claude_launcher_content`). This **disables the agent's interactive permission prompts** and,
combined with the auto-update chain above, widens the blast radius of any upstream compromise.

- It is **not** the default and **must not** be presented as the recommended mode.
- It is an **expert opt-in** (`install-claude-launcher --dangerously-skip-permissions`) and
  carries an explicit risk warning.
- It is **gated on a verifiable upstream**: `install-claude-launcher` refuses to bake in
  `--dangerously-skip-permissions` unless the effective policy is `pinned` or `signed`, and
  the generated launcher **re-checks the effective policy at every launch** (it can change
  after install) and refuses to start under `warn` or `unverified`.

Only enable it on a machine and against a checkout you fully trust.

---

## Supply-Chain Posture (Signing & Provenance)

**Current state.** The CLI and plugin are
distributed and executed today with **no signing, checksum, or provenance**, and hooks exec
the launcher/CLI from an env-resolved path. There is no immutable release artifact — adopters
run the live git tree.

**Target state (the public-distribution gate).**

- **Signed, checksummed releases.** Releases will be cut as immutable tags / GitHub Releases
  with **SHA-256 checksums** and **signing/provenance via Sigstore/cosign or
  `gh attestation`**.
- **Verify-before-exec.** The launcher and auto-update path will **verify the shipped
  checksum/signature before `exec`**. Verification failure fails closed.
- **No public release until the trust layer lands.** Signing + verify-before-exec +
  signed/pinned auto-update are prerequisites for flipping this repository public.

When SBOMs ship, they will cover the optional renderer toolchain (which uses npm); the core
CLI needs none (see below).

---

## Zero Third-Party Runtime Dependencies

The core CLI has **zero third-party runtime dependencies** — it runs on the **Python
standard library only**. Its entire import surface is stdlib:
`argparse`, `json`, `os`, `re`, `pathlib`, `subprocess`, `hashlib`, `urllib`,
`http.server`, `tempfile`, `shutil`, `shlex`, and similar modules.

This is a deliberate, verifiable security property, not an aspiration:

- **No transitive dependency tree** to audit, pin, or watch for advisories for the engine
  itself — there is no npm/PyPI runtime install path that could pull a compromised package
  into the core.
- **Minimal attack surface.** The bytes that run are the bytes in this repository plus the
  Python interpreter you already trust.
- **Auditable.** You can read the full runtime in a single file and confirm there is no
  third-party code in the execution path.

The **optional renderer/delivery toolchain** is the only component that uses third-party
packages (via npm). It is not required to run the core enforcement engine, and its
supply-chain controls (`npm ci`, CI, SBOM) are tracked separately from the core runtime.
If you do not use the renderer, you carry zero third-party runtime
dependencies.

---

## Secrets, Privacy, and Data Flow

- **Adapters reference secrets by env-var name, not value.** An adapter such as
  `example-saas.json` stores `"webhookEnv": "EXAMPLE_SAAS_WEBHOOK"`, and the live secret is
  resolved from your environment at runtime — keep that pattern; never commit secret URLs
  or tokens into an adapter.
- **`methodology.env` holds live secrets in plaintext.** Keep it `0600`, parent directory
  `0700`. Avoid passing secrets as CLI flags (e.g. `--webhook-url`) where they land in the
  process table, shell history, or logs; prefer env-var indirection.
- **Outbound data flow.** Depending on your adapter, the framework may contact: your
  configured **git remotes** (push, archive branches), **GitHub** (board/PR APIs), a
  **chat/notify webhook** (e.g. Google Chat), and the **auto-update fetch** from your
  framework upstream. It emits **no anonymous telemetry**. See `PRIVACY.md` for the full
  data-flow statement.
- **Tenancy.** Published session journals and RCAs use redaction as defense-in-depth, not as
  the isolation boundary. Multi-tenant isolation and a retention/erasure path are tracked
  work; do not co-mingle multiple tenants' data in a shared archive until isolation lands.

---

## Scope

In scope: the `tautline` CLI (including the `minervit-methodology` compatibility shim), the
generated launcher and git hooks, the
auto-update / re-exec path, adapter and `methodology.env` handling, and the publishing /
redaction surfaces.

Out of scope: vulnerabilities in third-party software you choose to run alongside this tool
(your agent runtime, git, Python, the optional npm renderer toolchain), and risks that
require an already-compromised upstream you explicitly chose to trust (documented above as
inherent to the trust model rather than as a defect).

---

## Verifying Changes

The behavior-test gate is `scripts/test.sh` (ruff + mypy + pytest, 269 tests). Security-
relevant changes must pass it. `scripts/validate.sh` is a legacy grep-pin gate being frozen
and is **not** the security gate.
