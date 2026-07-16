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

## [0.10.0] - 2026-07-15

### Added

- The PyPI package is real: `pipx install tautline` (or `pip install tautline`
  into a virtualenv) installs the full CLI — a thin wrapper package embedding
  the committed release tree under `tautline/_dist/`, stamped with a build-time
  `.snapshot-meta.json` (`installKind: "package"`), shipping both console
  scripts (`tautline` and the legacy `minervit-methodology`). The npm package
  remains a namespace pointer whose copy now points at pipx.
- A PR-blocking `fresh-install-smoke` CI job is the standing acceptance test:
  every pull request builds the wheel from its own tree, installs it into a
  clean Python 3.10 venv, and drives the full front door — both console
  scripts, the adopter flow to `adapter_drift: clean`, the lane-hook surface,
  and embedded-file canaries in site-packages.
- Package-mode UX and isolation: `version` reports `install_kind: package` with
  an `update_hint` naming both package channels (`pipx upgrade tautline` /
  `pip install -U tautline`); `sync-methodology` stands down with the same hint
  and never touches a leftover configured checkout; `update-repin` refuses
  before any fetch with a truthful remedy; package installs read adapter data
  from their own embedded tree. Snapshot-store and checkout machines keep their
  behavior byte-identically.

### Changed

- The adapter drift gate and every generated-file writer now treat
  provenance-stamp-only differences (`_generated.methodologyCommit`,
  `_generated.pluginVersion`) as equivalent content: two runtimes at identical
  rendered content never re-stamp each other's adapters, killing the
  mixed-mode ping-pong. Every content difference still gates, and true
  cross-build drift carries a version-alignment hint.
- Registry copy is per-registry: the PyPI README documents the real install
  (pipx/pip, the Python 3.10+ floor, the update channel) while npm keeps the
  truthful pointer copy; `publish-pypi.yml` ships the real wheel with an
  explicit `--channel stable` stamp.
- Plugin hooks invoke `tautline` (the name every supported install resolves)
  instead of the legacy `minervit-methodology`; rendered adapters carry the
  mode-independent `tautline render-adapters ...` regenerate line, so existing
  adapters re-render once on their next render.
- The README Quickstart states the Python 3.10+ prerequisite and the mandatory
  `tautline install-claude-launcher --force` cutover step, and gains an
  Install-from-PyPI subsection; the 3.10 floor rationale in `pyproject.toml`
  and CONTRIBUTING.md is corrected to the verified reason (`zip(strict=)` is
  3.10-only, and CI proves the floor on 3.10 every PR) — the retired
  `match`-statement claim was stale.

## [0.9.17] - 2026-07-15

### Added

- New `tautline maintainer-mode` verb (contract status: experimental) with
  `on`, `off`, and `status` actions, for framework-maintainer machines whose
  canonical methodology repo is a git checkout they develop in. `on` refuses
  unless there is a checkout to manage, then writes both key spellings
  (`TAUTLINE_METHODOLOGY_MAINTAINER_MODE` / `MINERVIT_METHODOLOGY_MAINTAINER_MODE`)
  into the user config env file; `off` strips both spellings from both the
  current and the legacy config surface and reports the re-read state, so it is
  authoritative rather than assertive. The key is file-only by design: a live
  environment variable of either spelling is inert, in Python and in the
  regenerated launcher's shell guard alike.
- With maintainer mode armed, the launcher-gate methodology update stands down
  at its single choke point — the checkout is never fetched, ff-merged,
  rescued, or repair-escalated underneath maintainer work, and the launch says
  so: `methodology_update: skipped - maintainer mode - update gates stand
  down; checkout left untouched`. Heal and the freshness stamp still flow, so
  committed maintainer work republishes the snapshot store's `current` at the
  very next launch. Snapshot execution, release guards, lane-start gates,
  drift and debt remediation, WIP holds, every Claude guard hook, and the
  skip-permissions interlock all stay on — there is no carve-out.
- Every armed launch prints a loud stderr banner whose load-bearing line is
  `maintainer_mode: update gates off - running <checkout> @ <commit>`, an
  armed launch reports `remote_status: skipped - maintainer mode` instead of
  probing the remote, and `methodology-status` gains a three-state
  `maintainer_mode:` line (off / on / configured but not armed).
- Regenerated Claude launchers carry a shell guard that parses the config file
  directly and stands the launcher's own auto-rescue down while the key is
  set. Launchers generated before this release keep their old behavior until
  regenerated with `tautline install-claude-launcher --force`; the verb prints
  a content-keyed advisory naming each one. Stock machines see zero behavior
  change: nothing ships, generates, or installs the key — the standdown is
  opt-in via the verb, and disarming it restores stock gate semantics.

## [0.9.16] - 2026-07-14

### Fixed

- Past the plan-review hard cap, the remedy Tautline prints is now chosen by
  asking whether the bound review evidence can actually be finalized — in every
  manifest writer, not just one. `finalize-plan-review` and
  `record-plan-review` previously chose the remedy from the blocker counts of
  the round being submitted, but a refused round is never written, so those
  counts say nothing about what the operator can finalize: submitting clean
  counts past the cap printed "finalize the existing review evidence" even when
  the bound evidence was clean but *stale*, which `plan-finalization-precheck`
  then rejects. The operator was sent to a dead end. The refusal past the cap
  stays unconditional at every door; only the wording changes.
- `run-plan-review`'s printed next-action remedy now renders the resolved
  absolute `--target` path instead of a literal `--target .`. On a machine
  running several lanes, a copy-pasted `--target .` binds to whichever checkout
  the shell is sitting in — possibly a worktree owned by another lane. The
  `--target .` written into a plan's committed Cross-Model Review Evidence block
  is deliberately left alone: an absolute path there would commit a machine
  token to a tracked file.

### Changed

- `methodology/canonical-rules.md` and every policy mirror now state the rule
  the CLI actually ships: past the plan-review cap the refusal is
  unconditional, and the remedy is chosen from the bound evidence. They
  previously said the split is unconditionally mandatory. Nothing reads these
  documents at runtime, which is precisely why the drift mattered — no gate
  caught it, and agents follow the text.
- The retired-domain ban in the public boundary scan is now derived from the
  CLI's own public-export rules rather than a hand-maintained file allowlist,
  widening the swept set from 104 files to 563. `GOVERNANCE.md`, `ROADMAP.md`,
  `LICENSE`, `docs/README.md` and the rest of the exported tree all ship to the
  public repo and none of them was being scanned. No shipped surface changed —
  none was carrying the retired domain — but the enforcement now covers what it
  ships instead of a subset of it.

## [0.9.15] - 2026-07-14

### Added

- Lanes now execute Tautline from an immutable snapshot store instead of from
  the methodology checkout itself. When an update is trusted, the new commit is
  copied into a read-only tree under
  `~/.local/share/minervit/tautline-releases/`, the store's `current` link is
  swapped atomically, and the CLI re-execs the new tree. A `git pull` in the
  checkout can no longer change the code that a running session is executing,
  which is what made concurrent lanes on one machine unsafe: one lane's update
  used to rewrite the files another lane was halfway through running.
- A session is pinned to the snapshot it started on, so every hook it spawns
  loads the same version of Tautline for the life of the conversation, even
  while other lanes advance the store. Sessions pick up the new snapshot on
  their next launch; a lane running an older snapshot after a release is the
  isolation working, not a fault.
- `tautline snapshot-status` reports the store, the current target, every
  published snapshot and every live lane pin. `tautline snapshot-prune --keep`
  removes superseded snapshots while refusing to delete the current target, a
  pinned snapshot, or a recently-current one. `tautline snapshot-pin --target`
  protects the snapshot a lane is executing from retention.
- Simultaneous launches no longer stampede the network: the first lane through
  the startup gate fetches, and the others reuse its result for a freshness
  window (`MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES`, default 10) instead of
  each running their own fetch and merge against the same checkout.
- Every mutation of the methodology checkout or the store is appended to a write
  journal at `~/.local/state/minervit/methodology-writes.jsonl` with the
  command, old and new head, outcome and the lane responsible — so an
  unexpected advance, a held update or a rescue can be attributed rather than
  guessed at.

### Changed

- `tautline install-cli` converts a machine to snapshot execution, and
  `tautline install-claude-launcher --force` is now a required step of the
  install rather than a convenience: until the launcher is regenerated, a
  session is not pinned to a snapshot and can change versions mid-conversation.
  The installer says so on every run, and `sync-methodology` keeps naming any
  launcher that still needs regenerating. Set
  `MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC=1` to hold a machine on the old
  behavior; deleting the store is also safe, as the CLI warns once and falls
  back to the checkout. See the Snapshot Store section of the release
  engineering reference.
- `tautline version` and `tautline methodology-status` now distinguish the
  checkout that updates are fetched into (`methodology_canonical_commit`) from
  the tree the running process was loaded from (`methodology_exec_root`), which
  are no longer the same thing.
- Release and public-export commands refuse to run from a snapshot and name the
  checkout to run them from. Executed from an immutable tree they had no git
  history to read, so they would previously report a tag as new without ever
  having looked one up, and skip the dirty-tree check entirely.

### Fixed

- One methodology commit reported two different short forms depending on where
  the CLI was executing, and generated adapters embed that value. Two lanes at
  the same commit therefore rendered different adapter bytes, each re-render
  putting the other back into drift — a permanent drift ping-pong through
  `methodology-status --fail-on-drift` with no methodology change behind it.

## [0.9.14] - 2026-07-14

### Changed

- The canonical public domain is now `minervit.ai` on every live shippable surface: contact
  addresses (README, `CODE_OF_CONDUCT.md`, `SECURITY.md`, the support SLA model, the plugin
  marketplace owner email, the demo tape) and the `$id` of both JSON Schemas
  (`methodology/adapter-schema.json`, `methodology/bootstrap-legacy-allowlist-schema.json`).
  `tests/test_public_boundary_scan.py` now enforces `minervit.ai` and bans the retired domains
  (it previously enforced the opposite, which silently reverted hand-fixes), and additionally
  asserts each swept surface positively carries its canonical-domain reference. The sweep now
  also covers `.claude-plugin/marketplace.json` and `docs/assets/demo.tape`, both of which ship
  and neither of which was scanned before. Historical records — release migration JSONs,
  archived changelogs, and the frozen 0.6.254 release-note strings in `bin/tautline` — keep the
  retired domain verbatim by design.
- **Schema `$id` compatibility: no adapter migration is required, and no adapter needs to
  change.** The schema `$id` is an identifier, not a resolution target: the CLI loads
  `methodology/adapter-schema.json` by filesystem path and validates with its stdlib-only
  subset validator, which implements no `$ref`/`$id` resolution and makes no network call.
  Adapter documents reference the schema through `$schema` — the raw.githubusercontent.com URL
  for generated scaffolds, or a repo-relative path in-tree — never through the `$id`, and the
  schema accepts any string there. Adapters that still pin the retired identifier therefore
  keep validating unchanged; `tests/test_adapter_schema_id_migration.py` pins that property so
  a future `$ref`-resolving validator cannot break them silently.

## [0.9.13] - 2026-07-14

### Changed

- Plan review now converges on a two-round target with a hard cap of four rounds, replacing
  the single fixed cap of two. Rounds 3 and 4 are self-authorizing: a run proceeds on a
  recorded `--exception-note` or on a detected convergence state -- blockers fixed after the
  bound round, or a successful run voided by a plan edit before it could be finalized. A round
  that was finalized and later superseded is *not* a voided run and never self-authorizes: the
  manifest binds one round at a time, so every earlier round is orphaned by design. The tool
  never stops to ask an operator to authorize a round, so a plan that genuinely needs a third
  pass is no longer dead-ended at the cap.
- Past the hard cap, refusal is unconditional. Clean, blocked, ambiguous, and stale states are
  all refused and no exception note overrides it; only the remedy varies, and it is chosen by
  whether the bound evidence can actually be finalized. Finalization of the existing evidence is
  named only when that evidence is clean AND still bound to the current plan; every other state,
  including clean-but-STALE evidence, takes the mandatory split. Naming finalization for stale
  evidence would be a dead end, since `plan-finalization-precheck` rejects a stale manifest.
- A run voided by a plan edit no longer triggers the "finalize that run instead" refusal. Such
  a run can never be finalized, so refusing there was a dead end.
- Plans that converge within two rounds are unchanged: no exception line, no `exception_note`
  field, no `- Exception:` evidence line, and round status still renders against the target
  (`round 1 of 2`). The hard cap governs refusal, not display.

### Added

- A recorded exception is now rendered into the plan's committed `## Cross-Model Review Evidence`
  block as an `- Exception:` line, so the reason a past-target round was taken is visible where
  reviewers actually read it instead of only inside the JSON manifest.
- `--exception-note` on `finalize-plan-review`, `run-plan-review`, and `record-plan-review`. It
  is required to write a plan-review manifest past the two-round target, on every writer -- the
  secondary/diagnostic writer included, so it cannot be used as a bypass. `run-plan-review`'s
  printed next-action carries the flag, so an agent that follows the tool's own instructions
  never hits the validation error.

## [0.9.12] - 2026-07-14

### Fixed

- The ExitPlanMode plan guard hijacked a plan stored under the adapter's
  `planningArtifacts.scratchPaths` to an unrelated source-of-truth plan. Transcript
  reference matching ran before the configured-scratch check, so whenever the recent
  transcript happened to name exactly one plan path, a configured scratch plan bound to
  that plan instead of reaching the plan-mode escape it was entitled to. Configured
  scratch is now classified first. Content-hash matching still runs ahead of it, so a
  scratch copy of a real repo plan continues to bind to its source.

### Changed

- Configured scratch plans no longer adopt a source-of-truth plan that merely shares
  their filename. The configured-scratch check also precedes filename matching, so such a
  plan now reaches the non-blocking plan-mode escape rather than being gated by the
  same-named plan's finalization precheck (which could block `ExitPlanMode`). This is
  deliberate -- a filename collision is weak evidence of identity, while the content-hash
  match that still runs first is strong evidence. Plans that actually live under the
  source-of-truth root are unaffected and keep their full precheck gate.

### Fixed

- The plan guards printed literal `--target .` in their command examples. On a
  multi-agent machine `.` names whatever checkout the agent happens to be sitting in --
  possibly a worktree owned by another lane -- so a copy-pasted remedy could act on the
  wrong repository. The `run-plan-review`, `finalize-plan-review`,
  `plan-finalization-precheck`, and `goal-start` remedies now render the resolved
  absolute target, shell-quoted so paths containing spaces stay copy-paste safe.

## [0.9.11] - 2026-07-14

### Fixed

- `public-release-check` reported a false `account-id` blocker for any 12-digit run
  that happened to sit inside a hex digest. A sha-256 digest contains a run of
  exactly twelve digits whenever the hex characters flanking that run are letters,
  so review ledgers, plan evidence headers, changelogs and checksum manifests all
  tripped the scan. Because the scan is tree-wide, one such digest anywhere in the
  tree could block a release export. A 12-digit run is now treated as a digest
  fragment when every occurrence of it on the line is interior to a digest-length
  hex run, which covers all of those surfaces at once.
- The narrow exemption that skipped every 12-digit token on an `.impl-reviews/`
  `"...sha...":` line is removed: the digest rule subsumes it, and the exemption
  also suppressed genuinely leaked account identifiers on those lines. Such an
  identifier is now correctly reported.

### Added

- The four implementation plans for the multi-lane runtime isolation, runtime
  snapshot store, plan-guard scratch escape, and plan-review convergence tracks
  land as planning documents. They add no runtime behavior.

## [0.9.10] - 2026-07-14

### Changed

- No user-visible change. This release adds internal backlog notes only; those
  notes live in a file that is excluded from every public export and never
  ships to users.

## [0.9.9] - 2026-07-13

### Fixed

- Publishing to npm failed again right after the 0.9.8 fix landed, this time with
  `ENEEDAUTH`. npm's OIDC trusted-publishing exchange mints a short-lived credential
  only when the published package's `repository.url` matches the workflow's identity
  claim, and npm compares that field case-sensitively. The generated package manifest's
  `homepage`, `repository.url` and `bugs` fields all read the lowercase `tautlines`,
  but GitHub's canonical owner is `Tautlines` (capital T), so the comparison never
  matched, no token was minted, and npm fell back to demanding an interactive login.
  These fields are now generated from GitHub's exact canonical casing, and a guard
  test pins it going forward. Publishing to PyPI, which does not compare this field
  case-sensitively, was never affected.

## [0.9.8] - 2026-07-13

### Fixed

- Publishing to npm never authenticated, so no release could reach npm. The
  publish workflow held no secrets by design, yet still told npm to read an
  authentication token from the environment. No such token existed, so npm sent
  an empty credential rather than exchanging its OIDC identity, and the registry
  rejected every attempt with a 404. The workflow no longer configures a registry
  token in any form, and npm authenticates over OIDC Trusted Publishing as it was
  always meant to. Publishing to PyPI was never affected.
- `release-tail` could not resume once it had tagged a release. It compared the
  tag's object identifier against the commit it had just pushed, but an annotated
  tag's reference names a tag object rather than a commit, so the two never
  matched and the command refused to continue, reporting a correctly placed tag
  as pointing somewhere else. Tags are now resolved to their commit before the
  comparison. A tag that genuinely points at a different commit is still refused:
  a published tag is never moved.

## [0.9.7] - 2026-07-13

### Added

- `release-tail` runs the whole release tail as one command: export, public-mirror
  commit, tag, GitHub Release, registry publish, and drift verification, printing
  evidence for each step. `--dry-run` prints the complete plan and changes nothing,
  and `--skip-registry` stops at a draft Release so no publish fires. Resuming needs
  no flag: rerunning the command continues a partially-completed tail without
  repeating finished steps or publishing twice.
- `release-drift-check` compares the version held by the repository, npm, and PyPI
  and exits non-zero when they disagree. It runs after a publish and on a daily
  schedule, so a stale registry is caught within a day rather than months later.
- `registry-package` generates the npm and PyPI pointer-package metadata from a
  single source, so what the registries say can no longer drift from what the
  project ships.
- Publish workflows for npm and PyPI that authenticate with OIDC Trusted
  Publishing and contain **no secrets**: the registry mints a short-lived
  credential from the workflow's identity token, so there is no API token to
  create, paste, rotate, or leak.

### Changed

- The public mirror is only ever fast-forwarded. The release tail never
  force-pushes it and never rewrites its history, so existing clones stay valid.
- Because a registry publish cannot be undone, each publish workflow first asks
  the registry whether the target version already exists, does nothing when it
  does, and fails closed rather than publishing blind if the registry cannot be
  read.

### Security

- Registry publishing no longer involves a stored credential of any kind. Note
  that this requires the maintainer to configure Trusted Publishing once on npm
  and on PyPI, binding each to this repository and to the publish workflow
  filenames. Until that one-time configuration is done, the publish workflows
  fail closed; they never fall back to a token. The workflow filenames are part
  of the trust relationship, so renaming one breaks it. The bootstrap order and
  the registry configuration steps are documented in the release-engineering
  reference.

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
