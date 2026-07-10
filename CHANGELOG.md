# Changelog

All notable changes to the Minervit AI Delivery Methodology are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is the concise, reader-facing changelog. It is intentionally short:
each entry summarizes user-visible behavior, not every commit. The full,
narrative per-release log (Executive Summary, Why It Matters, Operator/Developer
Impact, Validation, Residual Risk) is archived at
`methodology-release-notes-archive:docs/releases/minervit-ai-delivery-methodology.md`.
Pre-launch history through 0.6.265 is preserved privately (maintainer-only) at
`docs/productization/archive/changelog-prelaunch-root.md`.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.8.5] - 2026-07-09

Legacy plan-review evidence + generated-adapter guidance hotfixes; no runtime changes.

### Fixed

- `plan-finalization-precheck` accepts pre-0.8.0 Cross-Model Review Evidence
  blocks again: the template-generated Precheck line embeds the CLI name, so the
  byte-exact comparison rejected every legacy-reviewed plan after the rename.
  Exactly that command prefix is normalized; all other evidence drift still
  fails. Caught live by a Codex round in a product lane.
- Generated product `CLAUDE.md` adapters render the Codex T1 review command with
  the adapter's review wrapper after `--`; the previous line errored verbatim
  with "codex-run requires a command after --". Re-render adapters to pick it up.

## [0.8.4] - 2026-07-09

Upgrade re-exec hotfix; no runtime changes.

### Fixed

- The `bin/minervit-methodology` compat shim is a Python script again. Pre-0.8.0
  installs auto-update by re-executing that path with the Python interpreter, so
  the bash shim introduced in 0.8.0 crashed every 0.7.x upgrade mid-flight with a
  `SyntaxError` (the update itself applied; only the final re-exec failed, and
  rerunning the launcher recovered). Caught live on an operator machine.
- `plan-finalization-precheck` trusts plan-review manifests recorded under the
  legacy CLI name again (`minervit-methodology run-plan-review` /
  `finalize-plan-review`). The rename had left them untrusted, rejecting every
  pre-0.8.0 reviewed plan in downstream product repos; `record-plan-review`
  imports remain untrusted under both names. Caught live on the first product
  lane restart after the upgrade.

## [0.8.3] - 2026-07-09

Dependency refresh and public-mirror Dependabot hygiene; no runtime changes.

### Changed

- Dev toolchain pins: pytest 9.1.1, mypy 2.2.0, ruff 0.15.21.
- CI actions bumped to current majors (checkout v7.0.0, setup-python v6.3.0,
  setup-node v6.4.0, SHA-pinned); the previous pins targeted the deprecated
  Node 20 runtime.
- Iteration-review renderer-kit: remotion 4.0.487, react 19.2.7, zod 4.4.3,
  typescript 7.0.2, vitest 4.1.10.
- `public-release-export` no longer exports `.github/dependabot.yml`: the
  public repository is a force-pushed mirror, so Dependabot PRs opened there
  can never merge and always fail the release-change contract; dependency
  intake happens in the private repository.

### Fixed

- When the pinned/signed update policy blocks a methodology advance, the
  refusal now tells the operator how to proceed (review the incoming commits,
  then `tautline update-repin`) instead of only refusing.

## [0.8.2] - 2026-07-09

Public-export CI fix; no runtime changes.

### Fixed

- The framework self-adapter tests now skip in public-export trees (their
  subject files are deliberately excluded from the export), so CI on
  `tautlines/tautline` runs green.

## [0.8.1] - 2026-07-09

Public repository identity; no runtime changes.

### Changed

- README badges and clone URL, issue-template links, plugin manifest
  homepage/repository/policy URLs, and reference-doc clone instructions point
  at `github.com/tautlines/tautline`, Tautline's public home.
- Scaffolded adapters' `$schema` URL points at the `tautlines/tautline` raw
  path so it resolves for public users.

## [0.8.0] - 2026-07-09

The framework is renamed to **Tautline** — the governor for AI coding agents.
Backward compatibility is guaranteed for every renamed surface: nothing an
existing install or lane relies on stops working.

### Added

- `tautline` is the canonical CLI (`bin/tautline`); `install-cli` puts both
  `tautline` and the legacy `minervit-methodology` launcher on `PATH`.
- `TAUTLINE_*` environment variables are honored everywhere, with the
  `MINERVIT_*` names as fallback (one shared resolution helper).
- `.tautline.json` generated marker and `.tautline/adapter.json` repo-local
  source adapter are the canonical config locations; all reads fall back to
  the legacy `.minervit-ai-delivery.json` / `.minervit/adapter.json` names.
- Public `ROADMAP.md` tracking product direction in the open (package split
  targeted at 0.9.0, installable package, guided onboarding, update prompts).

### Changed

- Rendered adapters, help text, and generated lane wrappers emit
  `tautline <subcommand>`; wrappers and installed launchers resolve
  `tautline` first and fall back to `minervit-methodology`, including for
  pinned older checkouts.
- Plugins renamed: `minervit-ai-delivery-methodology` → `tautline-core`,
  `minervit-delivery-ops` → `tautline-ops` (directories and declared names).
  AI-runtime plugin registrations that reference the old names need
  re-registration (see the 0.8.0 migration report).
- Public docs rebranded to Tautline with the tagline "the governor for AI
  coding agents"; Minervit remains the legal maintainer (LICENSE, TERMS,
  PRIVACY, and changelog history unchanged).

### Deprecated

- `bin/minervit-methodology` (now an exec shim), the `MINERVIT_*` env-var
  names, and the legacy marker/adapter filenames remain supported through the
  0.8.x line; removal is a separate post-launch task gated on downstream
  products re-rendering against 0.8.0.

## [0.7.1] - 2026-07-09

Channel-reconciliation release: no new features.

### Fixed

- Ported the 0.7.0 launch boundary fixes from the stable channel back to
  experimental so both channels carry identical content: the private-codename
  scrub of export-included surfaces and the exclusion of the framework's own
  self-adapter files (`.minervit-ai-delivery.json`, `.minervit/`) from the
  public export.

## [0.7.0] - 2026-07-08

Initial public (open-core) release.

### Added

- **Enforced completion gates.** Blocking Claude Code hooks and pre-push/CI
  checks stop an agent from claiming a task is done while tests are red, a
  plan hasn't been reviewed, or a branch has drifted from its base — one
  canonical ruleset shared across every adopting project.
- **Per-project adapters.** A single JSON adapter (schema-validated, with
  `additionalProperties: false` on closed objects) captures each project's
  paths, board, and delivery conventions; `render-adapters` generates the
  project's `CLAUDE.md`/`AGENTS.md` from it, so the ruleset stays portable
  while project specifics stay local.
- **Release, board, and incident-review tooling.** Subcommands cover the
  full delivery loop: lane start/coordination, plan review, release cut and
  migration reporting, GitHub board sync, session-journal and root-cause
  incident-review publication, and release-update accountability.
- **Trust-gated auto-update.** Lane-start auto-update re-executes the
  methodology checkout only behind a verified-upstream check (a signed
  commit from an allowlisted key, a signed release tag, or a config-pinned
  hash), closing the fleet-wide re-exec exposure of an unverified `git pull`.
- **Zero telemetry by design.** The framework sends no outbound telemetry and
  phones home to nothing; the only ledger it keeps is a local, machine-only
  usage log. Any future telemetry will be opt-in, default off, with a
  published data-flow disclosure before it ships.
- **Governance and OSS scaffolding.** `SECURITY.md` (disclosure policy and
  hook-execution trust model), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and a
  fictional `example-saas` reference adapter that exercises every schema
  field as the onboarding example.
- **Contribution pack.** `.github/AI_CONTRIBUTION_POLICY.md` (the bar for
  AI-assisted pull requests), a general-purpose `.github/PULL_REQUEST_TEMPLATE.md`
  checklist, GitHub issue forms (`bug_report.yml`, `feature_request.yml`,
  `config.yml`), `GOVERNANCE.md` documenting the single-maintainer (BDFL)
  decision model, `CONTRIBUTING.md` "Before you build" / DCO sign-off /
  response-time sections, and a de-placeholdered `.github/CODEOWNERS` with the
  real maintainer handle on every active ownership line.
- **Launch documentation.** A rewritten README (pitch, quickstart with clone
  step, comparison table, FAQ), a `docs/README.md` landing page, a real
  terminal demo GIF and its `vhs` tape, and a social-preview generator
  (dev-only `pillow` dependency).

### Changed

- `validate.sh`, the legacy grep-pin gate, is frozen; `scripts/test.sh`
  (ruff + mypy + pytest) is the enforced gate going forward, and new
  behavior lands as pytest cases rather than new shell-script prose pins.
- This concise `CHANGELOG.md` is the reader-facing changelog going forward;
  the full pre-launch narrative log is retained privately for maintainers.

### Security

- **Pinned-by-default updates.** New installs default to a pinned auto-update
  policy: `install-cli` writes `MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned` plus
  a pin at the installed commit, so a fresh install fails closed on any
  unexpected upstream before the `git pull` + re-exec. `update-repin` advances
  the pin to current `origin/<branch>` HEAD after the operator reviews upstream
  (printing the trusted commit range); pre-existing installs with no policy env
  keep the backward-compatible `warn` fallback.
- **Skip-permissions interlock.** `--dangerously-skip-permissions` is gated on a
  verifiable upstream: `install-claude-launcher` refuses to bake it in unless
  the effective policy is `pinned` or `signed`, and the generated launcher
  re-checks the effective policy at every launch and refuses to start under
  `warn`/`unverified`.
- **Hardened re-exec token.** The auto-update re-exec handoff token is created
  with mode `0600` inside a private `0700` directory under `~/.config/minervit`,
  and the consumer rejects a token owned by another local user.
- **Adapter path containment.** Path-typed schema fields reject absolute, `~`,
  and `..`-escaping values, and `configured_path` enforces the same containment
  at runtime; intentionally external fields (`scratchPaths`, lane-coordination
  roots) are an explicit allowlist.
- **Verify-before-advance gating.** Lane-start auto-update and launcher rescue
  re-execute the methodology checkout only behind the verified-upstream check,
  closing the fleet-wide re-exec exposure of an unverified `git pull`.

### Removed

- No committed customer adapters or live-infrastructure references ship in
  the public tree; project-specific adapters live in each adopter's own
  repository.
- The stack-specific `makerkit-implementation` example skill is no longer
  packaged with either plugin; it moved to `examples/community-skills/` as a
  worked example outside the portable core.
