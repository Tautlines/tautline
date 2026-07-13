# Changelog

All notable changes to the Minervit AI Delivery Methodology are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is the concise, reader-facing changelog. It is intentionally short:
each entry summarizes user-visible behavior, not every commit. The full,
narrative per-release log (Executive Summary, Why It Matters, Operator/Developer
Impact, Validation, Residual Risk) is archived in the maintainer's release-notes
archive.
Pre-launch history through 0.6.265 is preserved in the maintainer's private
development repository.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.9.6] - 2026-07-13

### Added

- A regression test now freezes the project's line-length lint exclusion (E501)
  at its current hit count, so the previously-unbounded exclusion cannot grow
  further. Lowering the pinned count remains a manual follow-up as overlong
  lines are cleaned up over time.

## [0.9.5] - 2026-07-12

### Added

- Claude Code plugin marketplace manifest (`.claude-plugin/marketplace.json`), so
  `/plugin marketplace add tautlines/tautline` offers `tautline-core` and
  `tautline-ops` directly from the repository. The README documents the install
  flow.
- The quickstart names the shell activation and `PATH` step that the CLI install
  depends on, so a fresh clone reaches a working `tautline` command without
  guesswork.

### Changed

- `TERMS.md` now describes the auto-update trust model that actually ships rather
  than a pre-launch target: `install-cli` pins the update source to the commit it
  installed from by default, `--update-policy signed` verifies the upstream commit
  signature against a trusted key, and both policies fail closed. Baking
  `--dangerously-skip-permissions` into a launcher is refused unless one of them is
  in effect.
- `SECURITY.md` states the supply-chain posture that actually ships. It opens by
  noting the repository is public with published releases, and its trust-posture
  section separates what exists from what does not: the commit-level trust gate on
  every auto-update re-exec is real and fails closed, but the current releases carry
  **no checksum manifest** and the published release tags are **not signed**.
  `cut-release` can compute a SHA-256 manifest and can create a signed tag with the
  right flags, and that capability is now described as a capability rather than as
  something an adopter can go and verify against today.
- `SECURITY.md` and `TERMS.md` now note that `--update-policy signed` applies to an
  upstream you control and sign. The canonical upstream does not sign its commits
  yet, so a `signed` policy pointed at it refuses every update (fail-closed, with no
  upstream fix available to the adopter); `pinned`, the install default, is the
  working lever against it. Signing the canonical upstream is listed as a roadmap
  item.
- Public documentation no longer points at maintainer-only paths that a reader of
  this repository cannot open; those references now name the maintainer repository
  or its backlog in prose instead. The `render-adapters` deprecation warning for the
  legacy `goalTracker` adapter key drops its pointer to a maintainer-only design
  document and keeps the actionable instruction (migrate to `backlogProvider`).
- `ROADMAP.md` speaks of the public repository in the present tense — its work items
  are tracked as issues there and are now backlinked — and its "Recently shipped"
  section is current through the 0.9.x line.
- `ROADMAP.md` retitles the near-term section to 0.9.x instead of naming a fixed
  0.9.0 target, and states the compatibility sunset explicitly: the legacy
  `minervit-methodology` launcher name, `MINERVIT_*` environment fallbacks, and the
  `.minervit-ai-delivery.json` marker stay supported through 0.x and are removed in
  1.0.
- The renderer-ci workflow accepts `workflow_dispatch`, so its default-branch badge
  can render a status.

## [0.9.4] - 2026-07-12

### Changed

- Public-surface scrub: the changelog and the startup-remediation reference no
  longer carry private-tracker issue numbers, incident dates, or internal
  backlog/archive paths; the affected passages now describe the same behavior
  and follow-up tracking in maintainer-neutral terms. A stray internal
  codename was dropped from a `.gitignore` comment.
- The MakerKit community example (`examples/community-skills/makerkit-implementation`)
  is fully de-identified: the internal example codename is gone from its
  filename and headings, and exact kit/dependency version pins are replaced
  with relative phrasing (the kit's previous and current minor versions). The
  Stripe and Better Auth teaching patterns are unchanged.
- The internal release-update delivery ledger is excluded from the public
  release export, alongside the repo's other maintainer-only records. The
  release-update accountability gate now evaluates against the maintainer's
  source repository instead of the exported tree, so `public-release-export`
  stays gated on release-update delivery rather than tripping on the ledger's
  absence from the export.

## [0.9.3] - 2026-07-12

### Changed

- Brand copy sweep: live reader-facing docs teach the `tautline` CLI, the
  `tautlines/tautline-dev` repository, and the `~/.config/tautline/tautline.env`
  config surface; a guard test bans the retired "minervit methodology" brand on
  those surfaces. Documentation and test expectations only — no runtime changes.

## [0.9.2] - 2026-07-12

### Changed

- Config surface rebrand: the CLI, emitted shims, launchers, and git hooks read
  `~/.config/tautline/tautline.env` first (legacy `~/.config/minervit/methodology.env`
  kept as a byte-identical mirror and fallback); `TAUTLINE_METHODOLOGY_REPO` and
  `TAUTLINE_CLAUDE_AUTOCOMPACT_PCT` aliases are emitted, and lane/codex child
  environments dual-write both families. Re-exec tokens move to
  `~/.config/tautline/reexec-tokens`. Trust configuration (update policy and pins)
  keeps its 0.9.1 names and semantics: `install-cli` pins at the installing HEAD and
  `update-repin` afterward widens trust; `update-repin` keeps both config surfaces'
  pins in step. TAUTLINE trust aliases and pin-set preservation ship separately as a
  focused security change.
- Held-update banners defer to the active trust policy's remedy in the hold detail
  (lands the deferred 0.9.1 R2 finding).

## [0.9.1] - 2026-07-11

### Changed

- No dead ends at launch: a trust-policy hold on an available update now reports
  `held` (exit 0) and launch continues on the trusted retained checkout with the
  repair command printed alongside — provided the retained head itself passes the
  active trust policy (otherwise still fail-closed). Generated Claude launchers
  print an exact executable remedy with every gate failure and, when interactive,
  start a Claude repair session instead of a bare refusal
  (`TAUTLINE_NO_REPAIR_SESSION=1` opts out). The checkout still never advances to
  unverified code.
- Rebrand identity: the framework's dev repository moved to `tautlines/tautline-dev`
  (renamed + transferred from `minervit/minervit-ai-delivery-methodology`; GitHub serves
  redirects). The self-adapter and `METHODOLOGY_REPO_SLUG` now record the new slug; the
  legacy slug stays accepted everywhere the framework identifies its own repo, so
  unconverted checkouts keep starting during the transition.

## [0.9.0] - 2026-07-11

Sanitized instrumentation replaces narrative session-journal publication. A
session journal narrates the adopter's product work, so it can never be proven
safe to publish; 0.9.0 disables narrative publication entirely and introduces a
closed-vocabulary instrumentation record with zero product-information capacity
as the only session evidence that can reach a remote.

### Added

- Sanitized instrumentation record and CLI (experimental):
  `publish-instrumentation-record` recomputes a closed-vocabulary record
  (enumerated event codes plus numbers, no repo/branch/project/path/freeform
  fields) from the local observability event log and publishes it to the
  constant `tautline-telemetry-archive` branch via a hardened push path — pinned
  adopter-neutral commit identity/date, whole-branch fail-closed hygiene,
  closed-set commit-object parse, byte-compare readback, branch-tip ancestry
  guard, and recompute-at-publish so a tampered preview cannot influence what
  publishes. `prepare-instrumentation-record` and
  `validate-instrumentation-record` round out the surface.
- Additive `instrumentation` adapter key (experimental):
  `{enabled (default false), cadence (default milestone)}`. `enabled` alone
  permits publishing; `cadence` gates only boundary prompting.
  `instrumentation.enabled` requires `observabilityEvents.enabled`, and unknown
  `instrumentation.*` subkeys are rejected (remote metadata is a fixed constant).
- `docs/reference/instrumentation.md` documenting the record shape, guarantees,
  and the explicit threat model; the generated
  `methodology/instrumentation-schema.json` is registered as public-contract
  surface.

### Changed

- The session-journal opt-in hint, generated-adapter guidance, goal kickoff
  prompt, and lane-start/status lines now describe the local-only reality and
  point at instrumentation for upstream contribution.

### Deprecated

- `publish-session-journal` and `publish-pending-session-journals` are deprecated
  (removal >= 1.0.0), replaced by `publish-instrumentation-record`.

### Security

- Narrative session-journal publication is disabled: both publish commands refuse
  for every adapter in every mode (`--commit --push`, bare `--file`,
  `--allow-release-checkout-write`). No new narrative content can reach any remote
  from any adapter; journals remain local-only evidence. This invokes a new
  deprecation security-exception clause allowing a stable surface confirmed to
  expose adopter data to a remote to be hard-disabled ahead of its deprecation
  window with a required migration note and named replacement.

## [0.8.9] - 2026-07-11

Startup remediation mode: a debt-only lane-startup failure now opens a guided
remediation session instead of refusing to start; lane-coordination staleness
checks are re-scoped so a dead or unrelated lane's status file can no longer
block another lane's startup.

### Added

- Startup remediation mode: a debt-only `methodology-status --fail-on-drift`
  failure (agent-fixable lane debt such as missing hooks, stale goal/milestone
  state, lane-coordination notes, review evidence, or CI gaps) now starts the
  generated Claude launcher in a remediation session instead of refusing to
  start Claude, prompted to fix every printed issue and rerun until it exits 0,
  or declare a blocker if a fix is genuinely operator-only. Integrity failures
  (adapter drift the render pipeline could not self-heal, or an unsupported
  runtime) still refuse to start. See
  `docs/reference/startup-remediation.md`, which also documents the marker
  schema, the remediation contract, and the CLI's exit contract. Motivated by
  a startup-deadlock failure mode in which strict lane-coordination and
  pre-push review-evidence enforcement could each independently strand a
  lane's own startup or its ability to push a coordination-only fix; the
  remaining enforcement compositions are tracked in the maintainer backlog.
- `methodology-status --fail-on-drift` returns a three-way exit contract (0
  clean, 1 integrity, 2 debt-only) and prints a truthful
  `methodology_status_blocking: <integrity|debt> - <gate names>` summary line
  whenever it exits nonzero.
- The pre-push review-evidence gate gains a tightly-scoped allowance for a
  single-ref, coordination-artifacts-only push (a lane status note or an
  update to the shared cross-lane contract/board), so a strict-coordination
  lane can push that fix without full review evidence for the rest of the
  branch. Multi-ref pushes and any push that also touches a non-coordination
  path keep today's ordinary gating.

### Changed

- Lane-coordination staleness and strict-mode untracked/uncommitted checks
  are re-scoped to the current lane's own status file. Other lanes' stale,
  untracked, or dirty status files are now informational only
  (`lane_coordination_stale_other_lanes` / `lane_coordination_foreign_status_git`)
  and never block startup; the shared cross-lane contract and lane board
  checks are unchanged.
- The generated Claude launcher's exit-2 (debt-only) path suppresses
  user-provided launcher arguments so the remediation prompt is not competing
  with a stale prompt; a clean (exit 0) launch keeps full argument
  pass-through unchanged. The launcher's catch-all refusal message no longer
  blames every non-zero, non-debt failure on "adapter drift" and instead
  points at the actual `methodology_status_blocking` line.
- Third-party callers of `methodology-status --fail-on-drift` that compared
  the exit code to `== 1` to detect any failure must compare `!= 0` instead;
  nonzero-means-stop is unchanged, but exit 2 (debt-only) is a new nonzero
  outcome that `== 1` alone will miss.
- Reinstall the generated Claude launcher after upgrading
  (`tautline install-claude-launcher --force`) to pick up the three-way exit
  dispatch, then run `type -a <launcher-name>` to confirm no shell function or
  alias shadows the regenerated launcher script. Git pre-push hooks pick up
  the coordination-push allowance automatically at the next `lane-start`.

### Deprecated

### Removed

### Fixed

### Security

## [0.8.8] - 2026-07-10

Session-journal privacy hardening follow-up to 0.8.7.

### Fixed

- `publish-pending-session-journals` now respects `sessionJournal.enabled: false`:
  previously it committed and pushed pending LOCAL journals even after the
  adapter disabled the feature, defeating the 0.8.7 opt-in guarantee. Pending
  journals now stay local when disabled; `publish-session-journal --file`
  remains as an explicit operator override.
- Generated shims, Claude launchers, and git hooks suspend `set -eu` while
  sourcing `methodology.env` (which sources the user's private secrets file):
  a secrets line referencing a variable unset in the invoking environment —
  cron, git hooks, CI — previously killed every CLI invocation with
  `unbound variable`. Re-run `tautline install-cli` (and re-render hooks) to
  regenerate existing installs with the hardened wrappers.

## [0.8.7] - 2026-07-10

Session journals become opt-in; no other adapter or command-surface changes.

### Changed

- Session journals are now **disabled by default**. A journal narrates the
  session's product work and publishes to the framework checkout's journal
  branch, so it is never collected without an explicit
  `"sessionJournal": {"enabled": true}` declaration in the source adapter.
  Lane startup and `methodology-status` print a one-line opt-in hint while the
  source adapter is silent about the feature (an explicit `false` silences it);
  `docs/reference/session-journals.md` documents contents, destination, and
  how to opt in. Adopters who relied on the old default-on behavior must add
  the explicit declaration and re-render.

## [0.8.6] - 2026-07-10

Windows subprocess-encoding hotfix; no adapter or command-surface changes.

### Fixed

- Pre-push hook no longer crashes on Windows with `UnicodeDecodeError` +
  `NoneType.strip` when `gh` output contains non-ASCII bytes.
  Every text-mode subprocess capture (`gh`, `git`, `ps`, `tasklist`, review
  wrappers) now decodes as UTF-8 with replacement instead of the locale codec
  (`charmap` on Windows), and `run_command` tolerates a missing stdout stream.
  A repo-wide AST policy test keeps locale-dependent captures from returning.

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
