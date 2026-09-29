# Changelog

All notable changes to the Minervit AI Delivery Methodology are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is the concise, reader-facing changelog. It is intentionally short:
each entry summarizes user-visible behavior, not every commit. The full,
narrative per-release log (Executive Summary, Why It Matters, Operator/Developer
Impact, Validation, Residual Risk) is archived in the maintainer's release-notes
archive.
Pre-launch history through 0.6.268 — every release before the 0.7.0 public
launch — is preserved in the maintainer's private development repository, and
summarized for maintainers in `docs/productization/archive/changelog-prelaunch-root.md`
(internal: `docs/productization/` is not part of the public release export, so
that file is not present in a published copy). This file starts at 0.7.0.

## [Unreleased]

## [0.149.0] - 2026-09-29

### Added
- Opt-in Git-branch work manifests coordinate independent clones, machines and repository collaborators. Configure `workCoordination` with `backend: git`; cached, bounded synchronization publishes portable declarations without touching application branches. Offline updates remain local and pending, and `work sync` retries them. The existing local default is unchanged.

## [0.148.1] - 2026-09-29

Fast agent teamwork, with an intentional compatibility break from public 0.111.0. This
pre-1.0 recovery is an explicit exception to the normal additive-only minor-release policy;
review the migration below before upgrading. Shared context and useful
evidence return without required plans, review rounds, extra test runs, or new merge gates.

### Added
- `tautline work`: declare what a lane is changing, see sibling worktrees and overlapping scope,
  update dependencies/blockers, and finish or abandon work. Startup and work pickup show advisory
  context. Stale, missing, and corrupt records are explicit; they never lock ordinary development.
  State is local to sibling worktrees sharing one Git repository, not a cross-machine service.
- `tautline evidence run -- <command>` records a verification command already being run;
  `evidence status` distinguishes a current receipt from stale, failed, or interrupted work.
  No raw output or command arguments are stored and no hook runs tests automatically.
- `tautline health`: an on-demand integration view. Remote CI facts require `--remote`;
  an unknown or cancelled check is never presented as a passing check.
- Operator answers: `inbox --answer <id> --text ...`, `inbox --answers`, and `inbox --ack <id>`.
  An answer persists through session restarts until the source lane incorporates and acknowledges it.

### Changed
- Public documentation and package descriptions now describe the lean product and its limits.
  Coordination is advisory; one adversarial review and the project's test gate remain the process.
- New project setup enables work coordination. Existing projects can opt in without a forced
  migration. Utilities are evaluated by time saved, not by how many actions they block.
- The public upgrade includes setup interviews, local/GitHub/Jira backlog providers, handoffs,
  decision readers, diagnostics, and the optional builder identity/tools added since 0.111.0.

### Fixed
- Public CI validates the sanitized repository without requiring private adapters, backlog files, or archives. Version 0.148.0 was tagged for validation but was not published to package registries.
- Runner cleanup preserves auto-updated executables and live logs, preventing online runners from silently losing their ability to start jobs.
- Builder tests no longer inherit operator roles/credentials or write the operator's token cache.
- Upgrade/rollback verification exercises the public 0.111.0 baseline at the integration tip.
- Repeated `slim` runs preserve handwritten adapters in projects that are already lean.

### Migration from 0.111.0
- Update the CLI and plugin, then run `tautline slim --target <project> --dry-run` and review its
  preview before applying `tautline slim --target <project>`. Existing artifacts are archived,
  not deleted; handwritten instructions are preserved. Update handwritten startup instructions
  to use `lane-status` and `work status` instead of removed lane/review commands.
- The old Stop/completion guards, review-round economy, board/goal synchronization, mandatory
  journals, and fleet lease enforcement were removed. New work declarations are advisory;
  do not rely on the old gates after upgrading. See `docs/reference/lean-migration.md`.
- PyPI installs are snapshots: use `pipx upgrade tautline`. Checkout installations follow their
  configured channel. Keep the migration archive if you need to restore an older adapter.

### Previously available only on the development channel

### Added
- **Builder-lane GitHub verbs.** `tautline board list|show|fields`, `tautline issue
  show|comments|find|comment` and `tautline debt file` are a build agent's entire
  GitHub surface. The board is READ-ONLY -- there is no move, no status write, no `item-add` --
  because a board's ordering is the product director's statement of what matters, an input to a
  lane and never an output. The only writes that exist are one stamped issue comment and one
  off-board debt issue, and both are read back before they are reported as done. Opt in per
  project with a `builderGithub` block in the lean adapter.
- **`tautline builder-guard`.** A Claude `PreToolUse` Bash hook, plus a `gh` PATH shim
  (`tautline builder-guard --shim-dir`) for lanes with no hook contract, that makes those verbs
  the only route: an allow-list over `gh` subcommands, with `gh api` restricted to read GETs,
  `gh search` to `prs`, `gh repo` to `view|clone|sync`, and `gh release`, `gh issue`, `gh project`
  and everything unknown denied. Direct HTTP to api.github.com is caught too, including inside
  `bash -c`, a loop body or a command substitution. **Humans are never bound**: the predicate
  stands down before any parsing when the lane is not a builder, and the hook exits 0 rather than
  denying when `tautline` is missing or predates the verb.
- **`tautline builder-token`, `tautline lane-role`, `tautline builder-env`.** A builder lane
  authenticates as a GitHub App installation (`<app-slug>[bot]`) whose Projects permission is
  Read-only, so a board write is refused by GitHub rather than by us, and every builder write is
  attributed to the bot. `tautline builder-token --status` prints the permissions GitHub itself
  reported for the minted token, which is what turns the scope claim into evidence. The GitHub
  verbs use it automatically: an exported `GH_TOKEN`/`GITHUB_TOKEN` still wins, then the App, then
  `gh auth token` -- so a human running the same verb by hand is unaffected.
- `docs/builder-lanes.md`: the whole model on one page, including the two residual gaps the
  operator has to decide about (the App's Contents write permission is fenced by branch protection,
  not by this framework; Workflows write is optional and should stay unset).

### Changed

## [0.148.0] - 2026-09-29

Tagged validation candidate for the recovery release. Public CI exposed private-fixture
assumptions in three tests, so package publication was held. The tag remains unchanged;
0.148.1 contains the corrected public release and its complete upgrade notes above.

## [0.147.0] - 2026-08-30

The Tier-1 salvage batch: seven tools reclaimed from the process-bankruptcy demolition,
re-seated as on-demand, advisory-only commands, plus the standing Working style block in
every rendered adapter and the goal-writing guidance.

### Added
- Every rendered adapter now carries a standing **Working style** block (work autonomously,
  log decisions, work exhaustively when blocked, fan out subagents, evidence before done) —
  ambient in every session; goals now add only goal-specific scope (#620).
- `/goal` skill + `docs/reference/goals.md`: composes a goal from a short description,
  bare-text output (#620).
- `inbox`, `decisions-report`, `event-tail`, `event-log-path`, `event-rotate`: readers for the
  decision ledger, plus a cross-repo pending-decisions queue; `decision-record --awaiting-operator`
  marks operator-owned questions explicitly (#622).
- `github-budget-status` restored; `stakeholder-question ask|list` posts tagged, secret-scanned
  questions to GitHub issues (#624).
- `doctor` (branch-liveness, framework-staleness, skip-lint, monitor-liveness — advisory,
  always exit 0) and `red-green-check` (mutation probe with a crash-safe backup protocol) (#623).
- The wisdom pack: `docs/reference/lessons.md`, `verify-before-trusting.md`,
  `giving-human-instructions.md`, and `docs/CONTROL-LEDGER.md` — the rent ledger (#621).

### Changed
- Lean config free-text fields now carry length caps, and the adapter renderer refuses
  (actionably) rather than ever writing an over-cap file (#620).
- Existing lean projects pick everything up with one `tautline slim --target .` after updating
  the framework checkout.

## [0.146.0] - 2026-08-28

Three lean features on top of the 0.145.0 process-bankruptcy baseline: a project's first adapter,
where its backlog lives, and how a session hands off to the next one.

### Added
- **`tautline init`.** The setup interview for a repo that has never carried a Tautline adapter:
  at most 8 questions (project name; repo; integration branch; test command; where the backlog
  lives -- local, GitHub, or Jira, plus that provider's fields; whether continuity handoffs are
  on; up to three project rules), and every one of them also a flag (`--name`, `--repo`,
  `--branch`, `--test-cmd`, `--backlog`, the per-provider `--backlog-*` flags, `--handoffs`) so an
  agent can run the whole thing non-interactively with `--yes`. Writes a lean `.tautline.json`,
  validates it on the same formatter `validate-adapter` uses (now lean-aware), and renders
  `CLAUDE.md`/`AGENTS.md`. Refuses to overwrite an existing config unless `--force` is passed, and
  a `--force` re-run prefills every question from the config already on disk, so it doubles as a
  reconfigure. A `--force` run over a project whose only existing adapter is the legacy
  `.minervit-ai-delivery.json` name archives it (never strands it) beside the new
  `.tautline.json`, with a note pointing at `tautline slim` if its content was worth migrating.
  Right after the backlog-provider question is answered, `init` echoes the same backlog-norm
  sentence the rendered adapter carries -- confirmation that reuses Track J's renderer rather
  than a hand-written paraphrase that could drift from it. `render-adapters` and `lane-status`
  each print one advisory line pointing an un-adopted repo at `tautline init` -- report-only,
  exit code unchanged; `backlog` has nothing else it can do without a config, so it already
  refused with the same pointer. A closed stdin or interrupt partway through the interview
  (`Ctrl-D`/`Ctrl-C`) aborts with a clean message instead of a traceback; nothing is written.
- **Continuity handoffs.** An optional `handoffs: true` lean config key. `docs/reference/
  handoffs.md` defines one file, `.ai-continuity/HANDOFF.md` (Doing / State / Next / Gotchas, one
  page, latest wins -- the whole point is that a fresh session can pick up from it after any
  session ends), a `/handoff` skill writes it on request, `tautline lane-status` reports its age
  as one advisory line, and the generated adapter gains two lines instructing an agent to read it
  at session start and refresh it at checkpoints.
- **Backlog providers.** One CLI verb, `tautline backlog`, with four subactions --
  `list`/`add`/`take`/`done` -- reading the target's lean config. Three providers behind the same
  seam: `local` (a `QUEUE.md` table plus ready/building/done directories), `github` (issues by
  label, via plain REST/`gh api`, never the Projects GraphQL endpoint), and `jira` (issues in a
  project, transitions resolved by name). No sync: nothing runs on a schedule or a hook, nothing
  writes except these four explicit commands. The generated adapter names the configured provider
  as the project's one backlog surface, so an agent does not file follow-ups into a repo TODO file
  instead. `docs/reference/backlog.md` documents the three providers, their config keys, and the
  credential environment variables -- credentials are never written to config.

### Changed
- **The lean-1 schema** (`methodology/adapter-schema-lean.json`) gains two optional keys:
  `handoffs` (boolean, default false) and `backlog` (`provider: local|github|jira` plus
  provider-specific fields). Both are additive -- every config that validated before still
  validates unchanged.

## [0.145.0] - 2026-08-28

### Removed
- **The process engine.** Operator-directed process-bankruptcy demolition: the CLI goes from **181
  subcommands to 19** and `cli.py` from 73,287 lines to ~13,100. Deleted outright: the review-round
  economy (round budgets, tiers, hard caps, ledgers, lineage keys, manifests and `diff_sha256`
  freeze/void semantics), plan-review gates and `finalize-plan-review`, board/milestone/goal sync,
  session journals and instrumentation, the RCA pipeline, the guard-check registry and stop-guard
  corpus, the per-machine pinned hooks and the `update-repin` treadmill, the policy-phrase SSOT,
  and the 14,000-line release-migration-report generator — with the 30 source modules and 29
  plugin skills that served only those features.
- **The per-PR release boundary.** `merge_gate.py` and the VERSION-bump-per-PR contract are gone.
  Releases are batched: this entry is one. **Tests-green enforcement now lives solely in the CI
  workflows** — `ci-python` runs `scripts/test.sh` on every pull request and `ci-python-full` adds
  the daily matrix, the coverage ratchet and the fresh-install packaging leg. There is no local
  gate that can be skipped, and no evidence file to forge.
- **`renderBudget`.** Its `minGeneratedBytes: 15000` floor demanded the generated adapter be
  *large* and fired on every render once the lean template landed. The lean renderer caps itself at
  2KB by construction instead.

### Changed
- **`render-adapters` emits the lean adapter.** It now calls the same renderer `tautline slim`
  uses, projecting a 1.x adapter through the lean config so a project keeps its own rules: the
  generated `CLAUDE.md` goes from 16,312 bytes naming 32 now-deleted verbs to 1,189 bytes naming
  none. A new guard reads the emitted text and refuses any `tautline <verb>` the CLI does not
  register.
- **`methodology-status` reports identity, pin, lock and adapter drift.** The ceremony index —
  goal and milestone ledgers, board currency, hook inventories, control posture, go-live readiness
  — went with the machinery behind it. Adapter drift is the one blocking condition; `--posture` and
  `--enter-remediation-on-debt` are removed rather than left inert.
- **Two security controls moved rather than dying with their host.** The runtime required-secret
  degrade-to-empty scan moved from `methodology-status` to `validate-adapter`, and
  `runtime_capabilities` now names missing *carriers* as well as gates.
- **The provider registry keeps its transports' absence honest.** Every shipped provider derives
  `unavailable_verbs` from its category contract, so adapter membership, per-provider identity and
  secret-env format validation keep working while no verb claims a capability it cannot serve.

### Kept
The surface that remains, and is tested: `version`, `install-cli`, `uninstall-cli`,
`sync-methodology`, `render-adapters`, `validate-adapter`, `init-project-adapter`,
`methodology-status`, `lane-status`, `decision-record`, `release-tail`, `release-drift-check`,
`cut-release`, `registry-package`, `public-contract`, `public-release-check`,
`public-release-export`, `secret-status`, and `slim`.

### Migration
See **`docs/reference/lean-migration.md`**. Existing projects run `tautline slim`, which archives
process artifacts with `git mv`, removes the framework's hooks, rewrites the config to `lean-1` and
renders the thin adapter — never deleting, with `--dry-run` to preview. `tests/test_upgrade_path_e2e.py`
proves a machine on the previous release survives the upgrade, the reinstall and a rollback.
Superseded documentation is read-only under `docs/archive/2026-08-process-bankruptcy/`.

## [0.144.0] - 2026-08-28

### Added
- **`tautline slim` — one command migrates an adapted project to the lean profile.** It archives the
  project's process artifacts (the plan directory its own config names, `.plan-reviews`,
  `.impl-reviews`, review ledgers, the 1.x adapter source) into `docs/archive-prebankruptcy/` with
  `git mv` so history follows them; removes the framework's Claude hooks from `~/.claude/settings.json`
  and its `pre-commit`/`pre-push` git hooks, leaving user-authored hooks alone; rewrites
  `.tautline.json` to the new `lean-1` contract, preserving project identity and dropping every
  ceremony key; and renders a thin (<2KB) `CLAUDE.md`/`AGENTS.md` in place of the ~16KB one.
  Nothing is deleted — every rewritten file is backed up first — and running it twice is a no-op.
  A hand-authored `CLAUDE.md` (one without the `<!-- GENERATED -->` header) is never overwritten:
  the lean adapter is written to `CLAUDE.md.lean-proposed` beside it. Review ledgers and plan
  directories are archived whether or not git tracks them; gitignored lane scratch is left in
  place. A `settings.json` that cannot be parsed is a hard failure with a nonzero exit and a
  `FAILED` section, never a success-shaped summary. `--dry-run` prints the plan;
  `--keep-agent-hooks` opts out of touching the agent settings.
- **`lean-1` project contract** (`methodology/adapter-schema-lean.json`): four required keys
  (`schemaVersion`, `project`, `integrationBranch`, `commands.test`) plus optional `review`,
  `security`, `release`, `laneStatus` and `projectRules`. Process is prose in the generated adapter,
  not configuration.

### Changed
- **`tautline lane-status` understands a lean adapter.** It previously degraded to "lane status
  could not be computed" against any config that failed the 1.x loader's eleven required keys.
- **`tests/test_upgrade_path_e2e.py` now proves both release transitions**: the process migration
  (a real rendered project with the real installed hooks, through `slim`, asserting nothing is
  destroyed and a second run is a byte-for-byte no-op) and the existing runtime transition
  (previous release → this code → rollback).

## [0.143.0] - 2026-08-27

### Changed
- **Jira identity values are validated for grammar, not just presence.** `projectKey` must match
  Jira's key grammar — an uppercase letter followed by at least one more uppercase alphanumeric —
  so a value carrying a path segment, whitespace or a newline can no longer be interpolated into
  the authoritative board pin. `boardId` must be a positive ASCII integer of bounded length. 0.142.0
  tested it with `str.isdigit()`, which is true for `"0"`, for Unicode digits like `"٣"`, and for a
  six-thousand-digit string — all three were accepted and rendered into an authoritative pin that
  identifies no board. The length bound is what lets the check *report* them: converting an
  unbounded digit string raises instead, because CPython refuses integer conversion beyond 4300
  digits. `siteUrl` is validated by DNS label rather than by character class, so
  `team-.atlassian.net` and `team..atlassian.net` are refused, and both DNS length limits apply —
  63 octets per label, 253 for the whole hostname.
- **One rule decides which adapter block configures the board.** Provider dispatch resolved the
  active block as "`backlogProvider` if enabled, otherwise `goalTracker` if that key is present at
  all"; configuration selection required the legacy block to be *enabled*. So an adapter with a
  disabled `backlogProvider` beside a **present but disabled** `goalTracker` dispatched to one
  block while reading its configuration from the other. Both now use one resolver. The pin's own
  suppression — a lane with nothing pinned gets no line rather than one taken from elsewhere — moved
  to the pin, where it is a rendering decision rather than a selection one; it fires only on an
  explicit `backlogProvider.enabled: false`, so a legacy adapter carrying only `goalTracker` still
  pins normally.

### Note
The Jira provider remains **declared, not yet validated against a live site**, and this release
adds no Jira call: every board verb still refuses by name. The HTTP client moved to its own release
after four of six review findings in two rounds were its credential or cache behaviour — including
a shared cache that crossed authentication boundaries and a containment claim about tracebacks that
was not true. That surface deserves its own review budget.

## [0.142.0] - 2026-08-27

### Added
- **Jira can now be configured in an adapter.** `backlogProvider` accepts a provider's own identity
  fields, so a Jira board is declared with `siteUrl`, `projectKey` and optionally `boardId` instead
  of GitHub's `owner` + `projectNumber`. Credentials are named, never carried: `emailEnv` and
  `apiTokenEnv` name environment variables, on the same rule the chat webhooks already follow.
- **`jira` is a registered backlog provider.** It declares every board verb **unavailable**, so each
  one refuses by name rather than failing obscurely.

### Changed
- **The adapter identity model is per-provider.** `owner` and `projectNumber` are required only by
  `github-projects`; each provider declares which fields it needs and is validated against its own
  set. A GitHub adapter is unaffected.
- **The rendered board pin follows the provider.** A lane on a Jira board no longer receives a
  GitHub `<owner>/projects/<n>` pin, and the status summaries print the provider's own coordinates.

### Note
This release makes a Jira adapter **configurable** — it loads, validates and renders. It does **not**
make it work: no Jira call is made anywhere in this release, and every board operation refuses by
name saying the verb is not implemented yet. Reads land in the next release, writes in the one after.
The provider is **declared, not yet validated against a live site**; nothing here has spoken to a
real Jira instance.
## [0.141.0] - 2026-08-27

### Fixed
- **The plan-review hard cap counts total executions, not charged spend.** An execution that funded
  no inquiry — an infrastructure failure, or a reviewer that returned no classifiable verdict — is
  still uncharged against the **budget**, but now advances the **ceiling**. Both previously read one
  number, so a reviewer that never emits a `## Findings` heading could take unlimited rounds.
- **The ceiling is lineage-wide.** Uncharged executions are summed across every resolved member.
  Counting only the current member left a declared successor of a predecessor with four
  unclassifiable runs at a ceiling of zero and a full fresh quota.
- **Topology and cost are different questions.** A wrapper-success format error supplies lineage
  edges, work items and predecessor evidence even though it spends no budget, because it really did
  review. A failed wrapper still supplies nothing. Readers are enumerated by test as TOPOLOGY or
  COST, and a new unclassified one fails the suite.
- **Round labels are compared by ordinal** in the runtime cap guard, so `R1` and `R01` no longer buy
  separate runs past the refusal to finalize an existing unfinalized run.

### Note
- A lineage carrying uncharged executions may see its **ceiling count rise**. That is the
  correction, not a regression — those runs really happened. Charged spend is unchanged, and so is
  the rounds 1–2 convergence ladder.

## [0.140.0] - 2026-08-27

### Added
- **A backlog board other than GitHub Projects can now be named in an adapter.**
  `backlogProvider.provider` and the deprecated `goalTracker.provider` moved from closed `enum`s to
  registry-validated strings. Adding a board system is a registration, not a schema edit and not a
  fork. `stakeholderQuestions.provider` is deliberately unchanged and still accepts only
  `github-issues` — the stakeholder issue operations are not dispatched yet, so opening it would
  let an adapter name another provider and then write to GitHub anyway.
- **A declared provider that cannot serve a board operation refuses BY NAME.** Every board read and
  write now resolves the provider the adapter declares before acting, and one that does not serve
  the verb says so — naming itself, the verb, and what to do instead. It never falls back to
  GitHub, because a fallback would drive the wrong board while looking like it worked.
- **The board and the work items are separate choices.** `backlogProvider` and
  `stakeholderQuestions` resolve independently in code, so one provider's board over another
  provider's issues becomes expressible as soon as the issues key opens — nothing assumes the two
  agree.

### Changed
- **`validate-adapter` runs the backlog/issues registry check too.** Membership left JSON Schema
  when the enums opened, so without this the self-service lint would report a clean adapter that
  `load_project` refuses on the next command. Absent and present-but-blank are distinct answers.
- **`github-projects` is no longer a schema `enum` literal.** It remains accepted and remains the
  default; the guarantee is now asserted directly by test rather than inferred from the schema's
  shape.

### Note
This release makes a non-GitHub board **nameable and honestly refused**. It does not make one
configurable, and it ships no second board provider. The adapter identity fields are still
GitHub-shaped (`owner` + `projectNumber`), so naming another registered provider and enabling it is
refused at load, by name, saying exactly that. Per-provider identity fields land with the release
that adds the first provider needing them.

## [0.139.0] - 2026-08-26

### Added
- **A provider registry, so an adopter's stack can be named without forking the CLI.** Every
  integration seam in the adapter contract was a single-value `enum` that did two jobs at once: it
  declared which system you intend to use *and* gated whether the framework can drive it. Those are
  now separate. Membership belongs to a registry, so adding a provider is a registration rather
  than a schema edit; availability belongs to a per-verb capability probe, so a provider can be
  legitimately named while one of its verbs is not available yet — and that verb refuses **by
  name** instead of quietly doing nothing.
- **A null notify provider, so "I have no chat tool" is an expressible answer.** The four chat
  seams (`iterationReview.delivery`, `milestoneUpdate`, `productChat`, `deploymentNotification`)
  accept `"none"`. It performs no I/O, never raises, and reports that nothing was delivered and
  why. Declaring `enabled: true` alongside it is refused at load, so a deliberate opt-out stays
  distinguishable from a broken webhook.

### Changed
- **The four notify `provider` fields are validated against the registry instead of a closed
  `enum`.** Existing adapters are unaffected: `google-chat-webhook` is registered and behaves
  identically, payloads and sent-state semantics are unchanged, and the reference adapter renders
  byte-for-byte as before. Because membership left JSON Schema, `validate-adapter` now runs the
  registry check too — without it the lint would have reported a clean adapter that the next
  command refuses.
- **One Google Chat transport instead of two.** `post_iteration_review_google_chat` was a verbatim
  copy of `post_google_chat_webhook` differing only in two string literals — a duplicate transport
  is somewhere for two copies to drift. Both operator-facing strings are preserved exactly.
## [0.138.0] - 2026-08-26

### Fixed
- **The hard-cap refusal no longer promises a reset that does not happen.** The message a lane reads
  at the moment it is most tempted to evade said *"The counter resets on a base change; the
  obligation does not, and nothing enforces that but you."* Both halves were false — 0.135.0 made
  the ceiling base-independent and 0.136.0 enforced the successor case. It now states the actual
  behaviour and names the acknowledgement flags.
- **The shipped `review-before-push` skill reference said the same two false things.** Adopters
  reading it were told the rule was advisory when the tooling had begun enforcing it.

### Added
- **A conformance test pins every surface describing reset semantics.** This was the fourth pass at
  one rule; each earlier pass corrected one surface while another kept contradicting it, and the
  third claimed to have checked every occurrence. The test asserts both the **absence** of the
  falsified wordings and the **presence** of the true claims, and discovers candidate surfaces
  across `methodology/`, `src/` and `plugins/` — a methodology-only scan would have missed both
  surfaces that were actually wrong.

## [0.137.0] - 2026-08-26

### Fixed
- **`review-evidence-check` honours `--strict` for the durable round history.** A missing or
  damaged history returned `1` unconditionally, while every other evidence failure in the same
  command returns `0` without `--strict` and the help says `--strict` is what blocks — so
  diagnostic callers failed unexpectedly on this one check. Strict behaviour is unchanged,
  including the ordering that refuses a history-only deletion despite a zero outgoing diff.
- **Predecessor round history is found under unusual planning roots.** Ref discovery ran
  `ls-tree --name-only` without `-z` and stripped each line, so a `planningArtifacts.sourceOfTruth`
  containing non-ASCII, a tab or leading whitespace — all permitted by the schema — made git
  C-quote its output, the `.rounds.json` suffix check miss, and a capped predecessor's history go
  **silently undiscovered**. A successor then started at zero with a full budget.
- **An out-of-target planning root no longer tracebacks out of the push gate.** Any adopter keeping
  plans in an external repository crashed on every push. It is now reported as a diagnostic error —
  deliberately not the empty result beside it, which would let `--strict` pass on a history the
  gate never inspected.

## [0.136.0] - 2026-08-26

### Added
- **A new branch over capped work is refused.** When a branch has no recorded rounds but changes
  paths belonging to another branch already at its round cap, `codex-run` refuses and names it.
  Two exits: **decompose** the work, or `--acknowledge-reset <branch>
  --acknowledge-reset-reason '<why>'`. It never advertises cutting a new branch — #600 removed
  that phrasing because advertising it is what got it taken. This is the third and last of the
  resets: parts 1 and 2 closed re-cut, rebase and fresh-worktree for the *same* branch.
- Detection reads **branch refs**, not the working tree — a predecessor's history is committed on
  its own branch, so a successor cut from the integration branch never sees it on disk, which is
  the exact shape of the incident this work exists for.

### Changed
- **The rule text catches up with the code.** Rule 258 and `methodology/policy/17-review-before-push.md`
  said *"a base change resets the counter"*; 0.135.0 stopped the ceiling resetting. They now state
  the ceiling's real scope, that the charged counter and confirming predicate stay lineage-scoped,
  and this release's refusal.
- The acknowledgement rides in the round's **manifest**, and `finalize` carries it into the tracked
  ledger — **no tracked file is written during a round**.

### Fixed
- `run_git_status` captures bytes and decodes with `surrogateescape`. `text=True` collapsed paths
  differing only as `\r` versus `\n` onto one identity, which would **fabricate** an overlap and
  refuse unrelated work.

## [0.135.0] - 2026-08-26

### Fixed
- **The round-budget counter reads the tracked round history, not only gitignored `.ai-runs`.**
  That store has **zero tracked files**, so a fresh worktree or clone of a branch reported *zero*
  spent rounds and got a full fresh budget — the cheapest and most frequent of the three resets,
  fired by ordinary hygiene on a fleet running 20+ linked worktrees. **Counts can go up, and that
  is the fix.**
- **The absolute ceiling is base-independent** — a rebase no longer refills it. Canonical rule 258:
  a base change resetting the counter is *"mechanical, not permission"*. The charged counter and
  confirming predicate keep their lineage semantics, so a round free going in is not charged
  coming out.
- `codex-run` prints `codex_run_lineage_source:`, so a count that is low because this checkout
  cannot see the history is distinguishable from a branch that genuinely has none.

### Changed
- **Read-only: no new writes.** Recording rounds to a tracked file *during* a round can retarget a
  dirt-sensitive review wrapper, so that work is filed separately rather than bundled here.

### Known gap
- The history records rounds at **finalize**, and blocker rounds are normally never finalized, so a
  fresh worktree counts finalized rounds rather than every execution — lower than true spend,
  though no longer zero. A low count only permits more rounds; it never refuses work.
- **The same gap bounds the rebase guarantee.** The ceiling survives a base change for rounds the
  history can *attribute* — finalized ones. An old-base **local** manifest with no durable row is
  ambiguous (a never-finalized pre-rebase round, or an earlier lane's spend under a reused branch
  name) and is excluded: excluding only permits more rounds, while counting would refuse a lane.

## [0.134.0] - 2026-08-26

### Added
- **Append-only round history in a new tracked file.** `finalize-implementation-review` now writes
  `.impl-reviews/<slug>.rounds.json` — one accounting row per finalized round, plus a `lineage{}`
  block. The durable half of making the round budget enforceable: the counter reads
  `.ai-runs/review-evidence/`, which is gitignored with **zero tracked files**, so the count zeroes
  on a re-cut, on an incidental rebase, and in any fresh worktree or clone of the same branch.
  **Nothing reads the history yet** — no lane's counted rounds change in this release. Commit the
  new file alongside the ledger; its absence is not an error.
- Rows carry **accounting fields only**, never `classified_findings`: this writer runs inside every
  generated adapter, so repeating finding prose per round would multiply review text in customer
  repositories. Each row carries its exact `branch` and an **immutable execution key** (the
  reviewer's `log_sha256`), because `feat/a-b` and `feat/a_b` share one file and because
  re-finalizing one review must not count as two rounds.

### Changed
- **The review ledger itself is unchanged** — no new keys, and the schema literal does not move.
  That is why the history is a separate file: a checkout pinned to an earlier release rebuilds
  `<slug>.json` from the current manifest and atomically replaces it, so a history stored inside it
  would be deleted by that writer. Lagging pinned CLIs are a supported environment.

## [0.133.0] - 2026-08-25

### Added
- **Changed-path overlap primitive for round-budget lineage.** `implementation_review_changed_paths`
  and `implementation_review_paths_overlap` — the signal that survives a branch rename, which the
  round counter's own store does not: `.ai-runs/review-evidence/` is gitignored with zero tracked
  files. **No callers in this release**; the reset refusal that consumes them lands later, so no
  round count, refusal or gate behaviour moves here. Both fail open narrowly — an unknown answer
  reads as "no overlap known", never as a guess, because a fabricated overlap is the one failure
  mode that could refuse legitimate work.

## [0.132.0] - 2026-08-25

### Changed
- **ruff 0.15.21 → 0.16.2** (dev dependency). Verified against the current tree before taking it: both versions report `All checks passed!` on `bin/tautline src tests tools`, and both count **6443** E501 hits over `LINT_PATHS`, measured with the ratchet's own invocation (`--select E501 --output-format json`) — that is exactly `E501_BASELINE`, so the pin change moves it by zero.

## [0.131.0] - 2026-08-25

### Fixed
- **The implementation-review round budget now says, in the rule itself, that it follows the WORK and not the branch name.** The plan-review rule already forbade successors, splits, renames, copies and new branches from refilling a spent budget. The implementation-review rule beside it said only *"a base change starts a new lineage"* — no anti-evasion clause at all — and the hard-cap refusal advertised *"a new branch is a new lineage and starts a fresh count"* as one of its two exits.

  **That asymmetry reads as a licence, and it was taken as one.** A capped branch was re-cut as a fresh lineage to obtain rounds; the rebuild then produced twelve P1 findings the cap had been holding back, several of which would have shipped a break-glass mechanism that could be fooled by a downgraded severity, an unrelated branch's manifest, or an omitted finding. The cap was right and the prose did not say so.

  The refusal message now distinguishes decomposing the **work** into genuinely smaller, independently reviewable PRs from re-cutting the same content, and states plainly that at the cap with an unresolved Critical or P1 the work does not ship.

## [0.130.0] - 2026-08-24

### Fixed
- **Asking permission to continue now BLOCKS when a standing autonomy directive is active.** The permission-seeking guard resolved its severity through `phraseChecks`, which defaults to advisory, so under a directive that forbids permission-seeking the guard logged the violation and the turn shipped anyway. Under an active directive the block is now forced rather than delegated, and a demoted tier cannot disarm it — only a whole-guard opt-out can.

  **What it will not block.** The promotion consumes the detector's reason codes rather than re-deriving them, so a turn that merely REPORTS state ("clean checkpoint", "no work-in-flight") stays advisory: under a directive that says work until no safe work remains, saying so when it is true is compliance. A negated handback ("I won't stop here; I'm continuing") is forward motion, not a handback. Recording an operator-owned fork with `decision-record` or `stakeholder-question-ask` licenses **asking** and continuing; it does not license **stopping**. Ending a turn by handing back requires a declared, fresh blocker (`tautline blocker-declare`) — the exit the guard's own error message has always named — and a missing, stale or unreadable blocker record fails closed to refusing.

  **An explicit human stop outranks the directive.** A directive governs autonomous continuation; it never overrides the operator ending the lane.

## [0.129.0] - 2026-08-24

### Changed
- **The opt-in/standby detector now reports WHY it fired, not just whether it did.** `response_forbidden_opt_in_reasons()` returns reason codes — a decision menu, a direct handback phrase, a state description, a `should I …` interrogative — and `response_has_forbidden_opt_in()` becomes a one-line view over it. Its verdict is unchanged: the refactor was verified against the previous implementation over 20 shapes and both `human_discussion_request` values with zero divergences, and that result is frozen as a golden test.

  **Why it matters.** A caller that has to treat a completion report differently from a permission handoff previously had no choice but to re-derive that judgement alongside the detector, and two implementations of one judgement drift. The detector's own phrase list is now a proven partition — handback versus state — with a test that fails the build if a phrase is added without being classified.

## [0.128.0] - 2026-08-23

### Fixed
- **`base-health` no longer reads a post-job teardown failure as evidence the base's code is broken.** A run that concluded `failure` whose *every* failing step is teardown — `Complete runner`, `Complete job`, `Stop containers`, or a generated `Post Run …` step — is now reported `unknown` rather than `red`. Unknown never blocks and says so.

  **Unknown, not green, and that distinction is the whole design.** Green would claim the base's code is good on evidence that only shows teardown ran and failed. The gate stops *refusing* on it; it does not start *vouching* for it.

  **Every ambiguity stays red.** An unreadable jobs payload, a failing job with no failing step recorded, a single unrecognised step name, or **any job or step whose conclusion is neither green nor `failure`** — a matrix fail-fast `cancelled`, a `timed_out` — all leave the refusal standing. That last one is not hypothetical: an exact `!= "failure"` filter *skipped* those conclusions rather than treating them as ambiguity, so a run carrying a cancelled job alongside a teardown-only failure would have been read as teardown-only and downgraded, with nothing having established that the cancelled job would have passed — the extra read is allowed to fail, never to excuse. Only `failure` is eligible: `cancelled`, `timed_out`, `startup_failure`, `action_required` and `stale` have no step-level meaning and are untouched. GitHub exposes no step *type*, so recognition is name-based — and **name alone is not enough**, because step names are workflow-authored. Two guards follow from that. The prefix is `Post Run ` and not the looser `Post `, so a real step called "Post results to Slack" is not mistaken for teardown. And **position is required as well**: a teardown-named step counts only when it sits in the *trailing run* of teardown-named steps, which is where GitHub appends the post-job phase — so an adopter's genuine step called `Complete runner` in the middle of a job cannot open the gate.

  **The residual limit is stated rather than papered over:** a job whose *last* step is user-authored and named exactly like a teardown step is indistinguishable through this API. Nothing in the payload separates those two cases.

  Measured on this repository: `Complete runner` was the failing step in 8 of the 12 failing steps across the ten `ci-python-full` runs on `experimental` still concluding `failure`, and 6 of 10 counted per attempt over the last seven merges. With `postMergeTier.enforcement` armed to `block`, each one refused every lane's merge. 0.127.0 removed *this* repository's cause; this removes the framework's, for every lane whose runner has its own job hooks.

### Added
- **`post_merge_tier_run_jobs`** reads one run's jobs and steps. It is called **only** when the tier is already refusing, so the common green path costs exactly what it did before — one extra `gh run view --json jobs` on a red, and nothing otherwise.

## [0.127.0] - 2026-08-23

### Fixed
- **The self-hosted runner's job-completed hook no longer fails the job it cleans up after.** `.github/runner/job-cleanup.sh` ends with `exit 0` and a comment stating the contract it exists to hold: *"Never fail the job on cleanup trouble: this hook's exit code becomes the JOB's exit code."* It was not holding it. The runner does not execute a job hook through its shebang — it runs it as `bash --noprofile --norc -e -o pipefail`, visible in every job log directly above the hook's output — so the invoker's `-e` overrode the script's own deliberately `-e`-free `set -uo pipefail`, and the first unguarded non-zero command aborted the script before it could reach `exit 0`. The abort then became the job's conclusion, after every real step had passed.

  **Measured, not estimated:** classifying the failing step of the last 22 red `ci-python-full` runs on `experimental` put `Complete runner` — post-job teardown — at half of them, with no long tail. Because `postMergeTier.enforcement` has been armed to `block` since 0.119.0, each of those refused every lane's merge. A gate that is wrong half the time is one lanes learn to `--override` without reading, so the cost was not the lost minutes; it was the credibility of the control 0.119.0 was built to establish.

  The reachable trigger is a race on `_diag`, the runner's **live** diagnostic directory: the runner rotates files there while the job completes, so a path can vanish between the hook's `[ -e ]` test and its `cp -a`. `set +e` drops the inherited errexit and an `EXIT` trap covers what `set +e` cannot — a `-u` unbound-variable abort exits regardless of errexit. Both are needed; neither alone holds the contract.

### Fixed, from the review of this release
- **A failed identity copy now skips the wipe instead of deregistering the runner.** Dropping the inherited `errexit` removed an abort that had been covering this *by accident*: if `.runner` or `.credentials` could not be copied to the scratch dir, the old script died before the wipe and left `$HOME` intact. Without that abort the wipe would proceed, the restore would have no identity to put back, and the runner would go offline — while the hook still reported success. Trading a red job for a deregistered runner is a worse bargain than the one this release exists to fix, so identity failures are now fatal to the cleanup and the home is deliberately left dirty. `_diag` stays best-effort, because its race *is* the case this release removes.
- **An unusable scratch directory skips cleanup instead of copying the filesystem root.** With `errexit` dropped, a failed `mktemp -d` left `KEEP_DIR` empty, and `${KEEP_DIR}/.` then expands to `/.` — so the identity restore would `cp -a "/." "$HOME/"`, filling the runner's disk and still exiting 0. `set -u` does not catch it, because the variable is set and merely empty. Reproduced: the test that pins this wrote 11GB in 60 seconds against the unguarded script.

- **The test-only path overrides are gated behind an explicit sentinel.** Read unconditionally, they meant the *production* hook trusted `JOB_CLEANUP_HOME_DIR` / `JOB_CLEANUP_PRISTINE_DIR` from whatever environment it was handed — anything exporting the first would silently redirect the wipe, and a second pointing nowhere would let the wipe run against the real home with nothing to restore from. Moving off the `RUNNER_` prefix cut the collision odds but not the trust. The overrides now require `JOB_CLEANUP_TEST_MODE=1`, so the production path is literally the pair that was hardcoded before this release.

- **The hook's own tests can no longer run cleanup against the live runner home.** Gating the overrides created a new hazard in the tests that exercise the ungated path: with the sentinel absent the hook falls back to its production target, and `/home/runner` — which does not exist on a developer machine — **is** the live home on this project's CI container, where it holds `_work` and therefore the checkout pytest is running from. Those tests would have wiped the running job's own workspace. They now run against a copy whose production literals are rewritten to throwaway paths, and a ratchet pins the number of direct invocations of the real hook so the next test cannot reintroduce it.

All four were found by the cross-model review rounds on this diff, and each is pinned by a test proven red against the unguarded script. Three of the four are the same shape: the original script's inherited `errexit` had been masking a fail-open path by accident, so each layer of the fix exposed the next.

### Changed
- **Cleanup trouble is reported instead of silently discarded.** Every failure-prone command in the hook sent stderr to `/dev/null`, so a failing hook logged `Process completed with exit code 1` and nothing about which command produced it. That suppression is why this defect survived 22 runs classified as a flake rather than being read off the log. Failures are now named on stderr and still never propagate.
- **`JOB_CLEANUP_HOME_DIR` / `JOB_CLEANUP_PRISTINE_DIR`** override the previously hardcoded `/home/runner` and `/opt/runner-pristine`. They exist so the suite can execute the real script against throwaway directories rather than assert on its text — a shape test would stay green against a script that re-acquires `errexit` later or grows a new unguarded command. The runner sets neither, so container behaviour is byte-for-byte what it was.

## [0.126.0] - 2026-08-23

### Changed
- **The methodology assigns roles, not vendors.** `methodology/canonical-rules.md` and the skill policy references now say "the planner", "the plan reviewer", "the builder" and "the implementation reviewer" where they said "Codex" and "Claude". The most explicit case was the Execution Packet Work Loop, which assigned all three seams by vendor name — "Codex leads milestone-level planning and gets Claude review", "Claude consumes the tactical queue" — so the methodology named one vendor as the only permissible planner and another as the only permissible builder.
- **The two cross-model review seams name roles.** "Claude asks Codex" / "Codex asks Claude" becomes the builder asking whatever `roles.implementationReviewer` binds, which the gate already requires to be a different vendor than the author. The finding-retrieval section is about the reviewer's wrapper generally, and the legacy transcript marker is the agent's own declared `agents.<id>.transcriptMarker` rather than a guessed `^codex$` literal.
- **The lane instruction-file rule covers every registered agent.** "Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`" enumerated two vendors' files, so a third agent's instruction file was protected by nothing. It now names each registered agent's `instructionFile`, keeping the two familiar names as examples rather than as the whole list.

### Unchanged, deliberately
Genuinely vendor-specific artifacts keep their names, because renaming a real thing is not de-coupling: `usage-import-claude` parses a Claude transcript format, `install-claude-launcher` installs the Claude Code launcher, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` is a Claude Code environment variable, the Graphify backend flags name real backends, and "Claude memories" is a real artifact.

Two adapter keys were **kept vendor-named against the plan's instruction**, because the plan was wrong about them: `review.codexFastMode` is what the launcher actually reads (`codex_fast_mode_status`), and `goalExecution.preferredClaudeCommand` is what the goal path reads. The registry keys the plan named — `agents.<id>.fastMode`, `agents.<id>.goalCommand` — are *written* by the compat shim from those legacy keys and are never read for enforcement. Documenting the registry key as the opt-out would have told lanes to set a key that changes nothing: the stale-claim defect this whole program exists to remove, introduced by the release meant to remove it.

### Measured cap raises
Role vocabulary is strictly longer than a vendor name — "the plan reviewer" is three words where "Codex" is one — so every substitution is a net add and four capped modules had no headroom to absorb it. Each raised by its own measured delta with the reason recorded above the constant: `10-goal-orchestration` 523 → 534, `13-planning` 656 → 658, `21-lane-lifecycle` 541 → 548, `17-review-before-push` 708 → 712, and the global canonical byte ratchet 82,407 → 82,661.

## [0.125.0] - 2026-08-22

### Fixed
- **Two plan-review runs in the same second no longer share a log path — and no longer destroy each other's evidence.** The run log is named with a second-resolution stamp plus the plan slug and round label, so two runs of the same plan and round inside one second produced the *same* filename and the second silently overwrote the first. A recorded manifest binds its log by `sha256`, so the overwrite made `plan-finalization-precheck` refuse the plan with `plan review log hash mismatch` and `plan review run metadata hash mismatch`: the lane could not finalize a review it genuinely ran, and the original log was already gone. Reachable by any lane taking two rounds quickly.

  Found while chasing what had been treated as a CI flake — it reddened `experimental` on three unrelated commits, one predating the investigation, always as `test_two_round_happy_path_unchanged` and always CI-only, because a slower machine puts the two runs in different seconds. A colliding path now gains a suffix, which preserves sort order and appears only on a real collision, so the stamp shape every other reader parses is unchanged.

## [0.124.0] - 2026-08-22

### Fixed
- **A malformed adapter `fleet` block no longer wedges every commit.** `fleet_config` raises on an invalid value, and `fleet_guard_hook` catches that deliberately so a broken adapter does not block edits. `portable-gate-check` let it propagate, so pre-commit refused **every** commit in the repository — including the commit that fixes the adapter, leaving `--no-verify` as the only way out. The commit-time mirror was stricter than the gate it mirrors, in the one direction that traps a lane. A lockout is not a safer failure than a miss.

### Known limitation, stated rather than implied
A checkout whose adapter marker lives in a **subdirectory** still does not get the portable gates at commit time. The installed hook passes `--target .`, which names the worktree root because git runs `pre-commit` from there. Fixing that turned out to be a cross-cutting change to the whole hook template rather than a target substitution — every gate the hook invokes assumes the target is the worktree root, and the hook exits at `work-profile-check` before it ever reaches the portable gates. Five review rounds each found the next layer of that same change, so it is routed as designed work rather than patched a sixth time. This release does not regress that layout; it is the same position as 0.123.0.

## [0.123.0] - 2026-08-22

### Added
- **`tautline portable-gate-check`.** The two in-session write gates that have a commit-time equivalent — `plan-review-pending` and `fleet-guard` — now run from `pre-commit` on **any** runtime, so a lane on a harness without Claude Code hooks is no longer silently ungated on those two. The verb reuses the hooks' own block-reason functions rather than reimplementing the rules: two controls with one name disagreeing about what they forbid is worse than having only one.
- **The limit is stated, never conflated.** Two of the **seven** blocking gates are portable. The other five gate in-session events with no commit-time artifact. The two SessionStart carriers are report-only and are counted **separately** — crediting a runtime with a gate that cannot block anything overstates enforcement exactly as badly as hiding one that is missing.

### Not included, deliberately
- **No CI counterpart**, though a `pre-commit` hook alone is skippable with `--no-verify`. Measured against this repository, a CI job for these two rules *is* the defect that requirement exists to prevent: `fleet-guard` reads leases under the repository's `git-common-dir`, and `plan-review-pending` reads `.ai-runs/`, which is gitignored with **zero tracked files**. A fresh `actions/checkout` holds neither, so the job would find nothing and pass on **every** diff — a permanently green job standing in for a floor that does not exist, which is worse than no job because it looks like coverage. A first cut shipped exactly that job; it was removed rather than kept green. `CI_ENFORCED_CAPABILITIES` is empty **as data**, so the coverage line reports *"2 of 7 gates run at commit-time, none in CI — both read state a CI checkout does not have"* and cannot drift from prose. Filed as `2026-08-22-ci-floor-for-the-portable-write-gates`.

### Changed
- The pre-commit refusal **names its own bypass** and says that nothing downstream re-checks these two rules. An agent that discovers `--no-verify` independently learns both that the gate is optional and that the framework hid it.
- Version skew **fails open and loudly**: a lane whose resolved CLI predates the verb is told the gates are not enforced there and that nothing catches them downstream, instead of every commit being refused by an unrecognised-verb error.
- A repository where no adapter resolves is not blocked — the gates have no rules to apply there — and the verb reports what it did **not** check rather than going silent.

### Fixed
- **Staged deletions and renames were invisible to the gate.** The staged path set came from `--name-only --diff-filter=ACMR`, which drops `D` outright and gives a rename's destination only, so `git rm` on a file covered by a fleet lease — or on a plan with a pending review — committed with `portable_gate_check: ok`. Deleting a guarded file is precisely what a lease exists to stop, so the destructive case was the one the gate could not see. Now `--name-status -M`, with both sides of a rename checked.
- **A subdirectory target no longer reports a silent pass.** `--target <subdir>` resolved the adapter from the caller's target rather than the discovered root, so the verb reported "nothing to enforce" for a repository whose adapter sits one directory up.

### Required migration
- **Run `tautline install-hooks --target .` (or `lane-start`) in every checkout.** The gates reach a machine only when its pre-commit hook is rewritten. Required rather than optional because the gap is silent from inside the lane.

## [0.122.0] - 2026-08-22

### Fixed
- **The plan-review edit guard can now be asked at commit time without lying.** The rule fires in the window between a successful plan-review run and its finalize, and it was written for `PreToolUse`, where the worktree still holds exactly the reviewed content. A commit-time caller stands somewhere else — the edit has already happened — so hashing the worktree read "already voided" and would allow the very commit that voids the run. `plan_review_pending_block_reason` now takes `content_hash`, naming **which version** to judge.
- **A review of never-committed content is no longer invisible.** Edit A→B, review B, then stage B→C: B is in neither `HEAD` nor the worktree, so **no** hash a commit-time caller can compute identifies the pending run. The new `any_unbound_run` mode asks the weaker, honest question instead — does this plan have a successful run that no manifest accounts for? A run the manifest already accounts for stays exempt, so a finalized plan does not block forever.
- **Deleting a reviewed plan is judged.** The guard returned no block reason for any path absent from the worktree, so `git rm` on a plan with a pending review passed — the most destructive case the guard exists to stop. Existence is now required only when the caller has not named a version.

Both parameters default to the in-session behaviour, so the `PreToolUse` hook is unchanged in what it forbids. Nothing in this release passes either one; it lands the rule the portable-gate migration will consume.

## [0.121.0] - 2026-08-22

### Added
- **Runtime capability reporting.** `methodology/runtime-capabilities.json` declares what in-session enforcement each harness supplies — 7 blocking gates and 2 report-only session carriers, one entry per hook registered in `hooks.json`. A lane whose builder runs in a harness with no hooks loses all seven gates; before this it lost them with no signal at all.
- **`runtimeCapabilities` adapter key.** Declare or override what a runtime supplies. WHOLE-ENTRY REPLACEMENT per runtime, adapter wins — never a union, because an adopter whose harness dropped a hook must be able to say so. Adding a harness is a data edit: no enum, no code change, no upstream PR.
- **`runtime_enforcement` in the implementation-review manifest.** A PR reviewed in an under-gated lane records that durably, where it outlives the session that produced it.

### Changed
- `methodology-status` reports enforcement as `N of 7 in-session gates and M of 2 session carriers`. It is the only surface that works on a runtime with no hooks at all — which is exactly the lane that most needs it.
- `lane-status` adds one ENFORCEMENT line at session start, only when a resolved runtime is missing something. A clean lane still prints exactly one line.

### Notes
- **Reports, never blocks.** A `degradationPolicy` knob was considered and cut: it is the rejected refuse-to-run option re-entering through a side door.
- **Unresolved is not zero.** A lane whose adapter declares no builder is reported as unresolved, never as zero-capable — saying otherwise would put a false claim in a durable artifact, and overstating degradation is still a false report.
- An undeclared or unknown runtime is reported as zero-capable: the safe default, not the intended path.

## [0.120.0] - 2026-08-21

### Added
- **Agent output contract.** An agent writes `review-result.json`; the seam reads it, rejects a wrapper that lies about its identity, and refuses malformed output. Replaces reverse-engineering one vendor's transcript format, which returned `unlocatable` for every other agent and made the caller SKIP the findings cross-check — a review that reported clean while checking nothing.
- **`tautline agent-conformance`.** Certifies any agent's wrapper against the contract, including one this repository has never run. Seven fixture agents exercise it as real subprocesses; no vendor CLI is installed anywhere in the test path.
- **`review.crossModel.enforcement`** (`off|observe|advise|block`, default `block`). `vendor` stays a free-form string — no enum, no allowlist.
- **Findings block finalization.** The reviewer's own structured findings can refuse a contradicting finalize; `--findings-addressed` records the operator's assertion that they were resolved, stamped into the tracked ledger.

### Changed
- **The four identity gates assert vendor DIFFERENCE, not `reviewer == "codex"`.** Evidence records the bound agent id resolved through `roles`, so a lane that binds a different reviewer produces evidence naming it.
- Neutral command names with the vendor-named spellings kept as deprecated aliases until 1.0.0: `review-run`, `plan-review-native`, `packet-review`, `packet-review-status`.
- `stage2-codex` → `stage2-cross-model`; both spellings still bind, because the stage constant is used in a glob and failing to match the old one would make every ledger already on disk invisible.
- Degraded reviews are printed AND stamped into the manifest rather than skipped silently.

### Removed
- `CODEX_TRANSCRIPT_SPEAKER_MARKER` and `command_matches_codex_wrapper`, deleted rather than shimmed.

## [0.119.0] - 2026-08-21

### Changed
- **A red post-merge tier outranks feature work — now canonical, and this repository arms the
  refusal.** `methodology/canonical-rules.md` carries the clause every adopter inherits: the tier
  is adapter-declared and read at session start, before push, and before merge; the first lane to
  read a red owns it (claim, stop, work to green); diagnosis does not discharge it; marker silence
  is never green; unreadable is `unknown`, never green; under `enforcement=block`, `merge` and
  pre-push refuse unless the pushing or merging worktree holds the live claim, and `merge` alone
  also accepts a recorded `--override` (pre-push has no override path). This
  repository's adapter flips `postMergeTier.enforcement` to `block` on `ci-python-full.yml` over
  `experimental`. Completes backlog item 124 (routed from an adopter lane's self-RCA: three PRs
  merged into a red main, the last one 47 minutes after the lane knew).

### Fixed
- The merge `--override` decision record names `base-health` only when the base-health gate was
  actually bypassed (red + `block` with no claim, or the cross-repo fail-closed path); under
  `advise` or after a claim release it no longer claims a bypass that did not happen.
- The continuity handoff no longer carries a base-health re-read obligation when the adapter no
  longer declares a tier.

## [0.118.0] - 2026-08-21

### Added
- **The post-merge tier is re-read at every boundary, and an in-flight run is an obligation.**
  The pre-push hook now runs `tautline base-health --boundary pre-push` on every push — including
  the docs/assets profile, because a red base is not a property of the diff — and an installed
  hook that lacks the step reads as missing, so `lane-start` / `methodology-status --fail-on-drift`
  drive a reinstall on every existing checkout. Session start names the read. Under
  `postMergeTier.enforcement=block` a push into a red base is refused unless this worktree holds
  the live claim on the red (`fleet-lease claim --note "base-red claim: <ref>"`); `advise`
  narrates; `unknown` never blocks. Every read is recorded in `.ai-work/BASE_HEALTH.json`, and a
  run still in flight at the read surfaces in the continuity handoff as a re-read owed.
- **`tautline merge` refuses to merge into a red base** when `postMergeTier.enforcement=block`
  (pulled forward from the planned 0.119.0 at review: a declared-enforcing `merge` boundary that
  nothing wired was misleading). The refusal is released by this worktree's live claim on the red
  or by `--override <reason>`, which now names the red run in the decision record. A cross-repo
  merge never reads this checkout's tier: it fails closed under `block` (override records
  `base-health` as bypassed) and narrates under `advise`. `gh pr merge` now runs only through the
  `merge_execute` seam. The canonical ranking clause and this repository's flip to `block` remain
  0.119.0.

### Fixed
- `base-health` pins `gh run list --repo` to the adapter's declared repository so it and the tip
  probe describe the same integration remote (carried from 0.117.0's review at the cap).

## [0.117.0] - 2026-08-21

### Added
- **`postMergeTier` adapter key and `tautline base-health`: read whether the branch you are
  merging into has a red post-merge acceptance suite.** Until now the framework could only ask
  whether a pull request's own checks were green; it had no way to ask whether the integration
  branch's post-merge suite was red, so a lane could add merge after merge to an already-broken
  branch with every gate reporting success. An adapter now names that suite (`workflow`, plus an
  optional `branch` that defaults to the integration branch) and `base-health` reads it. The
  verdict is a completed run on the base tip when one exists, else the newest completed run by
  commit order — not completion order, because long suites overlap and an older commit's red can
  finish after the tip's green. An untested known tip is reported `unknown`, never green; marker
  issues are never consulted; an unreadable tier is `unknown`, never green. Read-only in this
  release: the pre-push re-check (0.118.0) and the merge refusal (0.119.0) ride on it. Absent key
  means nothing changes.

## [0.116.1] - 2026-08-21

### Fixed
- **`experimental`'s post-merge suite is green again.** The 0.116.0 merge commit (#578) carried a
  stale `(0.115.0)` title because the merge bypassed `tautline merge`, whose release-subject guard
  exists to refuse exactly that; the detector test then failed on every post-merge run. The
  published subject cannot be corrected, so the frozen drift allowlist records it with a note
  naming the bypass as the real defect. No runtime change.

## [0.116.0] - 2026-08-20

### Changed
- **The plan-review round budget is charged per plan lineage, with a hard cap of five rounds.**
  A plan lineage — the original plan plus every successor or branch that declares it as a
  predecessor — now shares one round budget capped at five review rounds. Successors and branches
  inherit the lineage's spent rounds and never refill the budget. When the cap is reached, a
  capped finalize records the remaining findings into the plan document itself at honest severity,
  and the plan proceeds to the build as the final plan: the end of endless planning.

## [0.115.0] - 2026-08-20

### Added

- **Agent registry and per-seam role bindings (inert).** An adapter may declare an `agents`
  registry and `roles` bindings — `planner`, `planReviewer`, `builder`,
  `implementationReviewer`. `vendor` and `runtime` are free-form strings with no enum and no
  allowlist: an adopter running any model on any harness registers their own values and every
  gate works unchanged. `vendor` and `runtime` stay separate axes, so two harnesses from one
  provider are not mistaken for cross-model review, and one provider may have several harnesses.
- **`validate-adapter` reports registry errors alongside schema errors**, never instead of them,
  so an adopter sees every violation in one pass. `methodology-status` prints the bindings
  synthesised from legacy vendor-named keys, and warns that those keys are removed in 1.0.0 —
  the guess is visible and pinnable rather than silent.

### Changed

- Legacy vendor-named keys (`review.codexWrapper`, `review.claudeReview`,
  `goalExecution.preferredClaudeCommand` and their siblings) keep working through a compatibility
  shim confined to one module, which is deleted at 1.0.0. The shim fills per-FIELD gaps, so an
  adapter part-way through migration keeps a resolvable wrapper. It never infers who authored a
  plan: an adapter too sparse to identify a seam author gets a refusal with a remedy in a later
  release, never a fabricated author.

Nothing reads `roles` yet and the rendered adapters are byte-identical, so this release changes
no behavior for any existing adapter. The gate inversion lands later, after the agent output
contract — inverting first would let an adapter bind a reviewer whose findings the framework
cannot read, and report a bound, clean review that had checked nothing.

## [0.114.0] - 2026-08-19

### Changed
- **Warn-only stop-guard findings no longer print into the conversation.**
  While the wave-3 stop chain is warn-only, the response guard's yield-gate findings (pending
  work on record, unyielded background run) are recorded in the guard event log only. The
  transcript advisory they used to emit carried no enforcement and no information the log did not
  already hold — the 2026-08-19 stop-hook RCA measured it at ~302K tokens injected into a single
  lane as 1,362 near-verbatim repeats of 23 distinct states. `stop-guard-aggregate` and
  `guard-report` read the event log, so the false-positive measurement that gates the chain's
  future flip to blocking is unchanged, and blocking-mode refusals are emitted exactly as before.
  (item 120 WS2)

## [0.113.0] - 2026-08-18

### Added
- **A lane can name which GitHub identity it is holding.**
  `tautline github-budget-status --identity` prints the login, host, token source, and an
  eight-hex SHA-256 fingerprint that is never the token itself, and registers this lane in a
  machine-local identity record. When two lanes on one machine are active on the same upstream
  under one login, it warns and names both remedies (a per-lane `GH_TOKEN` bot PAT or a GitHub App
  installation token), with the runbook at
  `docs/reference/operations/per-lane-github-identity.md`. Closes Control 4 of RCA
  `20260630T202308Z`, the last of its five outstanding.
  **It must not cry wolf**, so the advisory fires only for two or more recently active lanes on
  the same upstream, on this machine, under one login. A lane is a **worktree root**: an
  invocation from a subdirectory resolves to the lane its root owns, while sibling linked
  worktrees stay distinct lanes, because in this framework's standard topology — one isolated
  worktree per lane — they are exactly the concurrent lanes the advisory exists to catch.
  Collapsing them onto their shared common dir, as the first version did, made `len(lanes)`
  permanently 1 and the warning unreachable. A checkout with no parseable remote never
  participates. **Cross-machine sharing is NOT detected**, and the canonical rule says so in a
  phrase pinned by a test, so a later edit cannot quietly widen the claim past what the control
  measures.
  The subsystem is advisory and cannot fail a lane: every failure path prints one
  `github_identity: unavailable - <reason>` line and leaves the exit code alone.
  `MINERVIT_GITHUB_IDENTITY=0` stands it down entirely.
  Registration happens only when `--identity` is passed — a passive status read must not
  manufacture the collision it reports.

### Changed
- **`gh auth token` no longer takes the machine-wide `gh` serialization lock.** It reads the local
  credential store and issues no API request, so serializing it bought zero rate-limit protection
  while costing up to the full 30 s acquire timeout. The exemption is keyed on the command, so a
  new caller of the same command cannot forget it.
- Measured, not hoped: warm identity snapshot **0.21 ms**, full printed surface **0.15 ms**,
  against the plan's 150 ms veto. The memo is keyed by resolved target path as well as lane key,
  so a warm read in a fresh process runs **zero** subprocesses — asserted by a test, because as
  originally written it ran two.
- Generated adapter unchanged: both rendered files are byte-identical. The reach Control 4 asks
  for lands in the `github-projects-reads` skill reference, which costs the corridor nothing; the
  adapter line measured **186 bytes against 202 free** and was deferred rather than stranding
  every later item in this program.

## [0.112.0] - 2026-08-18

### Changed
- **Board reads cost ~10x less GraphQL budget.** `gh project item-list`, `field-list`, and `view`
  are served by a hand-written GraphQL query instead of the `gh project` subcommands. Measured
  against a 227-item board: `item-list --limit 100` costs 102 GraphQL points and `field-list`
  costs 102, where the equivalent hand-written query costs 11 and 1. The budget is 5000
  points/hour, so `gh project` capped a machine at ~49 board reads an hour and the measured peak
  was 47 — lanes were sitting exactly on the ceiling. A full schema-plus-227-item read now costs
  34 points against ~331. The payload is a strict superset of gh's, verified against a live
  board; mutations, `--query` scopes, non-JSON output, unrecognized flags and field-list limits
  above GraphQL's page cap still run through `gh` untouched.
- **Board items carry issue/PR state and issue-field-backed values inline.** gh omits both, so
  an issue-field-backed `Priority` was invisible (53 of 100 items on the live board) — leaving
  `workOrder=priority` silently falling back to status/position. Inline state is a fallback rather
  than a replacement for the per-item REST `issue view`: that read is live where the board payload
  is cached, and a gate deciding whether work is finished keeps its live read.
- **The board field schema is cached for 24 hours** (was 300s) and served from cache whenever
  fresh — re-reading this static schema was 43% of all measured GraphQL spend. Staleness and
  cross-account exposure are bounded five ways: refresh on an unresolvable field/option, purge on
  a rejected write, item-only invalidation on a successful write, always-fresh reads for board
  adoption, and keying to the authenticated gh account — with no long-lived cache when that
  identity cannot be resolved. `TAUTLINE_GITHUB_FIELD_SCHEMA_TTL_SECONDS` overrides the TTL.
- **Incomplete board reads fail closed** rather than returning partial field values, including
  nested label/user/pull-request/reviewer connections, and a paginated read shares one deadline
  across pages instead of granting each page the caller's full timeout.

## [0.111.0] - 2026-08-18

### Changed
- **Preflight latency may now be spent on the next item, in a separate worktree.** The
  frozen-tip preflight rule previously confined a lane waiting on the gate to
  "planning/polling, not edits or next-item implementation". Paired with a pre-push gate that
  runs for the better part of an hour, that wording structurally produced an idle lane: the
  only two permitted activities were planning and polling, so a lane supervising a long
  preflight had nothing else it was allowed to do. Observed live on an adopter project, where
  a lane sat on a **~70 minute** gate with no authorized work available to it. The concern the
  old wording protected is isolation, not idleness — nothing about starting the next item
  endangers the proving diff when that work happens in a separate worktree. The rule now
  permits it and states the isolation requirement explicitly. Background-work supervision is
  untouched and still applies to the running gate: starting parallel work is not licence to
  stop supervising it. Expressed within the existing budgets rather than by raising them — the
  replacement occupies the bytes the old rule did, and the merge-and-ci module stays under its
  word cap.

  The rule itself landed on the integration branch in the previous release's span without a
  version of its own. This release is that missing boundary, cut so the change has a version,
  a changelog line, and a migration report like every other behaviour change. Nothing about
  the rule's text changes here; only its release record.

## [0.110.0] - 2026-08-17

### Fixed
- **The test suite filled the disk, because pytest's tmp reclaim only runs at a clean exit.**
  `$TMPDIR/pytest-of-<user>` reached **17 GB** across 13 sessions and took a 228 GB volume to
  642 MB free. pytest registers its numbered-dir cleanup as a program-exit callback, so an
  interrupted run reclaims nothing, and the next run will not touch the leftovers either: a stale
  lock still reads as alive for `LOCK_TIMEOUT`, three days. The suite now reclaims each tmp tree as
  soon as its test passes (`tmp_path_retention_policy = "failed"`), so an interrupted run costs
  almost nothing. A failing test keeps its tree, and keeps the permission **modes** it failed with
  — restoring write bits is itself destructive to evidence, so every unseal is gated on pytest
  actually reclaiming that tree. Measured on one heavy pair of test files: 325 MB left behind
  before, 0 B after.
- **A read-only tree defeated the reclaim silently.** The installer and snapshot store seal what
  they publish (0o555 dirs, 0o444 files) by design, and pytest reclaims with
  `shutil.rmtree(ignore_errors=True)`, which cannot unlink a child of a 0o555 directory and does
  not report that it could not — so a leak was indistinguishable from a clean reclaim. The sealing
  is unchanged; the harness now restores the owner write bits first, for both per-test trees and
  the `tmp_path_factory` trees no per-test sweep can see.
- **The adapter schema cache served stale schemas for the life of a process.**
  `_ADAPTER_SCHEMA_CACHE` was keyed by path with no invalidation, so a long-lived reader — a hook,
  a daemon, the test suite — that read a schema and then saw that path rewritten kept serving the
  first read forever. The fail-open empty result was cached the same way, so a briefly unreadable
  schema stayed "unavailable" permanently. Both failures were silent. The memo now compares the
  bytes it parsed: exact rather than a stat heuristic, one entry per path rather than one per
  revision, and no window between checking and reading for a rewrite to slip through.
- **Three `background-run` tests raced the marker they assert on.** The completion receipt is
  written before the `[tautline] finished:` line is appended, and those tests awaited the receipt
  then read the log immediately. Microseconds on an idle machine, lost once under concurrent
  suites. They now await the artifact under assertion.

## [0.109.0] - 2026-08-17

### Fixed
- **A round-record test raced the plan rewrite it depends on.** No adopter-visible behaviour
  changed; this is test-suite hygiene. `write_plan_review_manifest` upserts the Cross-Model
  Review Evidence section back **into the plan file** as its last act, so after a review round
  the plan's mtime is only milliseconds old. The round-record suite's digestless-floor import
  then made its imported log "current" with a bare `touch()` — a margin measured at **27ms** —
  and `record-plan-review` correctly refuses a log older than the plan. On CI that gap inverted
  and the suite went red for clock reasons rather than for anything the diff did. The setup now
  pins the ordering explicitly with `os.utime`, the idiom the rest of that file already uses, so
  the scenario under test is the digestless floor rather than the runner's timestamp behaviour.

## [0.108.0] - 2026-08-17

### Changed
- **The release valve proves its carried list (item 108 WS5).** The valve shipped at 0.100.0 with
  an honest limitation written into every capped record — `carried_findings_basis:
  "caller-asserted"` — because it counted reviewer invocations but could not prove those rounds
  were ever classified. With the durable round record (0.104.0), the record-backed budget reader
  (0.105.0) and one authoritative lineage resolver (0.107.0) in place, that disclosure now
  closes: when **every round the authoritative resolver counts** carries a `round-classification`
  record, the basis upgrades to a verified token and the finalize states what was verified. When
  it cannot, the basis stays `caller-asserted` and the disclosure **names the specific rounds
  that lack classification**, so a lane can act on the gap rather than merely be told one exists.
  Pre-record history, imported or unverified classifications, and members whose spend is unknown
  or whose lineage walk truncated are printed as floors and can never satisfy the upgrade.
  The verified token is written only when the justifying record is actually on disk: the
  classification is appended **before** the basis is derived, and a failed append forces
  `caller-asserted` and names the failed write rather than claiming a proof that does not exist.

## [0.107.0] - 2026-08-17

### Changed
- **One lineage resolver (item 108 WS3).** Plan-review lineage is resolved once, from the union
  of declared predecessor edges (an explicit `--predecessor` always binds and is never
  overridden by inference), `-vN` name-shape matches found by **enumerating existing** manifests,
  round records and metas rather than generating candidate names (so `admin-v34` finds
  `admin-v1`, and a date-like `-v20260815` suffix neither hangs nor allocates millions of
  strings), and shared work-item references. The advisory chain display and the authoritative
  budget now consume the same resolver output, so one launch can never record two different
  lineages; a depth-capped or cyclic walk prints `plan_review_lineage_walk_truncated` and labels
  its summary a floor, never a silent standalone plan on a fresh budget. Closes the two
  remaining confirmed defects from the retired lineage-cap branch.

## [0.106.0] - 2026-08-17

### Fixed
- **Deriving a release migration report no longer costs `2**depth`.** Every release block asked
  its predecessor for a report twice — once for `wipSafe`, once for `requiredMigrations` — so the
  ladder doubled in cost with every release ever added. Measured before the fix: 31.8s at 0.99.0,
  64.0s at 0.100.0, 127.4s at 0.101.0, extrapolating to roughly an hour for one derivation a few
  releases later. After: well under a second. This is why the repository test gate and CI appeared
  to hang with no failing test — the suite was spinning inside the ladder at 100% CPU. Reports are
  byte-identical; only the derivation cost changed, and the cache hands every caller its own copy
  so no caller's mutation can reach another's report.
- **Two occupancy-lease tests no longer rot with the calendar.** They compared a fixture pinned to
  the test module's clock against the real wall clock, so once elapsed time passed the lease TTL
  the fixture read expired, the liveness guard answered first, and the ownership assertions they
  exist to make failed for an unrelated reason. They now compare on the clock their fixture is
  built on. No product behaviour changes.

## [0.105.0] - 2026-08-16

### Changed
- **Every plan-review budget decision reads the durable record (item 108 WS2, PR2).** Round
  launch, the runtime cap, the release valve's spend derivation, and precheck's capped
  re-derivation now consume cumulative per-member counts from the committed round records:
  `spend = baseline floor (raise-only corrections included) + charged invocation records (run
  or imported)`, deduped against lane metas on the log digest, with an unrecorded post-cutover
  meta surfaced as a write-path-bug warning rather than silently counted. A fresh worktree's
  finalize can no longer shrink the durable lineage count (the confirmed refill defect this
  program exists to close), and out-of-order finalization never decrements cumulative member
  counts. A member with no baseline reads at the pre-record floor exactly as before —
  additivity begins at the first record write, so pre-record history is never double-counted
  and never treated as an alternative to new records. The manifest's lane-local
  `observed_successful_runs` is demoted to display plus the no-baseline floor.

## [0.104.0] - 2026-08-15

### Added
- **The durable per-round plan-review record — write path (item 108 WS1, PR1).** Every reviewer
  invocation appends one committed, append-only record under
  `<plans-root>/.plan-reviews/rounds/<identity>/`: a one-time `baseline` capturing pre-record
  history (its enumerated digest set is the durable cutover marker — set membership, never
  timestamps), a `reviewer-invocation` record for every run including failures (`charged` iff
  the wrapper exited 0; `source: run|imported`), a `round-classification` appended at bind time
  referencing the invocation by nonce + log digest, and raise-only `correction` records via
  `record-plan-review --correct`. The baseline is written before the current run's meta is
  absorbable, so the first post-cutover run counts exactly once; imports follow one
  deterministic rule (recorded digest → bind; in-baseline-set → pre-record, uncharged;
  otherwise → charged imported invocation). Dual-write only: no budget reader consumes the
  record in this release — that is PR2 — so no gate changes its verdict. A repository-wide grep
  guard pins that no recovery guidance prescribes overwriting a record or the manifest. This is
  the foundation under the valve's `carried_findings_basis: caller-asserted` disclosure
  (0.100.0), whose verified upgrade lands later in this program.

## [0.103.0] - 2026-08-15

### Added
- **A build-ready plan must ship its goal prompt (item 107 WS4 PR B).**
  `plan-finalization-precheck` now requires the goal-prompt artifact for a build-ready plan,
  enforced at all four knob levels (block refuses with a goal-assignment-specific remedy that
  persists via `--out`; advise warns on the pass path; observe/off stay silent) and wired into
  the standalone verb, the ExitPlanMode hook, and goal-status readiness. Binding uses 0.101.0's
  clause-parsing matching logic, so a sibling plan's goal can never satisfy this plan's
  requirement. Deliberately NOT wired into `goal-assignment`'s own gate — that would deadlock
  the tool that creates the artifact (the ExitPlanMode deadlock found and fixed in the
  decomposed 0.89.0 lineage's final confirming round rides along). Second half of the 0.89.0
  decomposition; hard predecessor 0.101.0 (PR A) is merged.

## [0.102.0] - 2026-08-15

### Added
- **Every composed goal says to parallelise (item 106 WS2-B).** `tautline goal-assignment` now
  writes the parallel directive into every composed goal's tail: dispatch independent tasks to
  concurrent subagents in a single batch, give each its own worktree when they would otherwise
  touch the same files, and route each by its `model-tier` tag. The directive lives in the tail,
  so every budget site that measures the tail — the 4000-char core-too-large refusal, the
  first-criterion floor, the criteria-fitting loop, and the milestone budget — counts it
  automatically. Also clarifies the goal-assignment skill's omission-reporting wording. This is
  the second half of superseded draft PR #553 (the extractor half landed as 0.95.0/#555); #553's
  round-cap decomposition is disclosed in its body and it closes with this release as its named
  successor.

## [0.101.0] - 2026-08-15

### Added
- **The matching logic for a build-ready plan's goal-prompt artifact (item 107 WS4 PR A).**
  `plan_authoring` can now decide whether a candidate goal file is bound to a given plan: binding
  happens only through the composer's own ``from the finalized plan `<ref>` `` clause, captured
  backtick-delimited and compared exactly — mentioning a plan elsewhere in a goal's text does not
  bind it, and punctuation in a filename cannot falsely collide. Includes the target-wide
  `.ai-work/goal.txt` fallback matched against the full plan reference. Matching only: no
  enforcement gate consumes this logic in this release — the `plan-finalization-precheck` wiring
  ships separately (PR B), so no gate changes its verdict here. Payload-only re-cut of the
  decomposed 0.89.0 lineage's matching half onto the merged 0.100.0 tip; the re-cut lineage
  carries its own fresh review ladder.

## [0.100.0] - 2026-08-15

### Changed
- **The plan-review round cap releases into the build: `finalize-plan-review` no longer refuses
  at the hard cap (item 86 WS1, spec decision D2 — the release valve).** A finalize at the
  4-round cap carrying unresolved Critical/P1 now exits 0 with the derived verdict
  `capped-with-open-findings`; every unresolved blocker is recorded at its honest severity as
  `status: carried` with a unique focus id, and becomes a BINDING implementation-review focus
  item reported by `plan-finalization-precheck`, `review-evidence-check` and
  `finalize-implementation-review`. `plan-finalization-precheck` accepts the capped manifest, so
  no state of that gate refuses every exit — the direct lesson of the 2026-07-14 plan-review
  deadlock. The spend is re-derived from on-disk run metadata, never from the `--round` label
  (a label cannot buy the valve); a capped record requires `asserted_verdict: blocked` (an
  allowlist of one), and a clean assertion at the cap is refused before the manifest is written.
  The capped verdict is scoped to plan-review telemetry only. The succession-chain advisory's
  split remedy is suppressed on the capped finalize, which just told the lane to build.
  **Disclosed limitation, by decision:** the valve counts successful reviewer invocations and
  carries the caller's classification of the bound round's log; it cannot prove earlier counted
  rounds were ever classified — that takes a durable per-round record, which is the
  round-accounting workstream's artifact. The capped manifest therefore records
  `carried_findings_basis: caller-asserted` and the finalize prints a matching
  `plan_review_capped_disclosure:` line, instead of implying a completeness it cannot verify.
  This is the code half of item 86 WS1; the canonical-rules/policy prose half lands in its own
  stacked PR. Fourth derivation of this boundary (0.84.0 → 0.87.0 → 0.97.0 → 0.100.0), chained
  from the merged 0.99.0.

## [0.99.0] - 2026-08-15

### Changed
- **Plan-review finalize no longer prescribes decomposition as the cap exit on the sequential
  path.** The finalize-time hard-cap and round-3-stall messages (`finalize_trusted_plan_review`)
  used to say "the split is mandatory: decompose this plan into smaller source-of-truth plans" --
  a new plan file is a new round budget, so this instruction was itself the budget-refill loop the
  item exists to close. The remedy now says to carry every unresolved Critical/P1 into the
  implementation-review focus list by hand and proceed to the build, never a successor plan; an
  automatic `capped-with-open-findings` finalize ships in a separate PR (item 106 WS1) and this
  text is deliberately still true once that lands. Mirrored in the generated adapter's
  `## Autonomy And Planning` guidance (net adapter bytes: -4). A grep-based guard pins the removal
  against regression. Verified end to end: driving one plan through R1-R4 naturally, this is the
  only cap-state message a lane reads, and it names the build.
  **Scoped, not closed:** `plan_review_hard_cap_refusal` (the round-LAUNCH refusal, a different
  function) still names the split. It is reachable only as a backstop, and only when three
  conditions hold at once -- a plan already at its per-file hard cap, with unresolved blockers,
  AND no bound `capped-with-open-findings`-eligible evidence to finalize instead -- which requires
  an agent to have already received and disregarded the build-carry remedy above. Its wording is
  pinned to `methodology/canonical-rules.md`'s Planning section by
  `test_the_process_authority_states_the_shipped_hard_cap_remedy`, and that paragraph is item 106
  WS1's wholesale-rewrite seam; closing this residual is deferred to avoid a collision with that
  in-flight release-valve PR.
  **Also scoped:** the message stops instructing decomposition, but "proceed to the build" is not
  yet mechanically enabled end to end for a Claude Code lane: `ExitPlanMode`'s
  `plan_finalization_hook` reruns `plan_finalization_precheck_errors`, which only accepts a
  `clean`/`clean-with-deferrals` verdict, so the hook still blocks on the `blocked` manifest this
  path writes. Making the capped exit actually pass that gate is exactly WS1's `capped-with-open-
  findings` verdict (D2); until it lands, this text names the correct direction and a lane
  bypassing ExitPlanMode (or working outside a Claude Code hook-enforced environment) can act on
  it today, but a hook-enforced lane will still be blocked and needs WS1.
- **`milestone-advance --event pr-merged` reports cumulative lineage review rounds.** When the
  milestone ledger's recorded source plan resolves, the merge prints
  `plan_review_lineage_rounds_at_merge:` with the chain's total recorded rounds (honesty-marked
  `exact`/floor `>=`), reusing the existing `plan_review_round`/`plan_review_clean`/`plan_review_blocked`
  v1 telemetry vocabulary -- no enum change, no T0 re-approval gate.
  **Known residual (P2, deferred):** `plan_review_member_recorded_rounds` takes the larger of
  run-metas-on-disk and the finalized manifest's own count, which fixes the common undercount
  (metas pruned, manifest remembers more) but not every mixed history: if the manifest's OWN
  bound meta was pruned AND a later successful meta survives, both sources can independently read
  the same smaller number and the true total (sum, not max) is silently undercounted while still
  labeled `exact`. Narrow and cosmetic to the advisory report only -- no gate or verdict reads
  this number -- documented rather than chased further this round.

## [0.95.0] - 2026-08-15

### Added
- **A composed goal now states the plan's own acceptance criteria.** `tautline goal-assignment
  --plan <plan>` reads the plan's `Acceptance criteria` section (falling back to
  `Completion definition`) and leads the `Done when:` clause with it. Before this, the clause was
  built solely from the adapter's definition of done, so every goal composed from every plan
  carried the same generic process bar and the plan's own criteria appeared nowhere. The
  definition-of-done floor is **retained** behind the criteria — it is what closes the measured
  stop at 90-95% — and criteria are elastic content that degrades the way the milestone list
  already does: shortened, then summarised with a count, never silently dropped. A plan with no
  named criteria still composes, with the generic bar alone.
- `goal-assignment` reports `goal_assignment_acceptance_criteria: <n> of <total> included`,
  naming the heading the criteria were read from, or saying no such section was found — so
  `0 of 0` never conflates a plan that names none with a section that could not be read.

## [0.86.0] - 2026-08-15

### Added
- **Two Stop-boundary state gates that do not need a live goal.** One refuses a turn ending on a
  live detached background run, or on a finished run whose terminal summary was never read; the
  other refuses a turn ending with pending work on record — read from *all four* queues (goal
  ledger, `NEXT_SESSION` next action, execution packet, milestone ledger). The
  summary-as-stop-signal incident had the goal ledger auto-cleared on SUCCESS, so every guard
  gated on a live goal was already unarmed by the time the incident configuration existed.
  **Both ship warn-only** until the fourth PR of the wave-3 stop chain flips the posture once, on
  evidence.
- **`monitor-status` writes a read receipt** (`<log>.read.json`) on every path that prints a
  status, including a failed or stale one — a receipt written only on success would leave a lane
  that correctly diagnosed a failure unable to end its turn. It records *which* completion it
  observed, so a relaunch under the same log name cannot be cleared by the previous run's receipt.
- A checkout may declare itself a subagent worktree (`.ai-work/WORKTREE_ROLE.json`), which exempts
  it from **inherited** arming only. A run it launched itself still counts.

### Changed
- **The `stop_hook_active` one-shot bypass is gone.** It returned 0 above adapter-root resolution,
  so a single block was the entire guard. The state gates now survive two consecutive retries and
  then fail open with a logged event; the counter resets on any non-retry evaluation, because
  resetting only on a clean stand-down would leave it at the limit after one blocked turn.
- The refusal **renders** its "queue enumerated empty (…)" clause from the same registry the reader
  iterates, so the claim cannot outrun the gate.
- Canonical policy 20's guard-activation sentence said the guard is active *only* with a live goal
  ledger — the behaviour that caused the incident. Replaced, not appended to.

### Fixed
- `stop-guard-aggregate` was reporting **+0.0 for an arm it never ran**: the harness enumerates the
  boundary's arms explicitly, so the new gates contributed zero because nothing called them. Wired
  in and proven by mutation.
- The wave-3 warn-only clamp sat below `if mechanism != "phrase"` and was **unreachable for state
  checks** — the mechanism every remaining PR in the chain uses. The posture the chain depends on
  was announced and not implemented.

## [0.83.0] - 2026-08-14

### Added
- **`tautline secret-status --name <VAR>`** reports *where* a named secret is reachable from —
  process environment, installed config env, or the operator secrets file — and **never what it
  is**. Exit 0 means reachable; exit 1 means absent from all three — the only answer that justifies
  an operator escalation — and exit 2 means a layer *exists but could not be read*, so absence was
  never established -- and it prints `secret_source: indeterminate`, never the `absent` marker the
  policy names as the escalation predicate. Those two are kept apart deliberately: `user_config_env_value` returns `""`
  on `OSError`, so an unreadable secrets file otherwise looks exactly like one that does not hold
  the value, and the answer it produces is the one that pages a human. Both rebrand spellings are probed in both directions, because a
  probe that checked only the name it was handed would report `absent` for a value sitting under its
  sibling.

### Changed
- **Every missing-webhook refusal now names that probe.** They previously said the secret was
  missing and sent the lane straight to a human, when the usual cause is a value that *is* persisted
  and merely unreachable from this process — a session started outside the lane env, or a value
  written under the `MINERVIT_` spelling while the resolver prefers its `TAUTLINE_` alias. Seven
  sites, swept as a class, with a test that fails on any eighth.
- Canonical policy 03 and 23 state the rule: a missing `MINERVIT_`/`TAUTLINE_`/webhook secret is not
  a true blocker until `secret-status` has been run and the command retried through the lane
  environment. Re-asking for a value already in the store is permission theater.

## [0.82.0] - 2026-08-14

### Changed
- **`background-run` now records whether the work finished, and how.** A detached reaper owns the
  command and waits on it, writing a real `exitCode` and `finishedAt` and appending an anchored
  `[tautline] finished: exit=<n>` line to the log. Nothing in the tree called `wait()` before, so a
  monitor could only infer from a dead pid — and *"the pid is gone"* and *"the pid never started"*
  are the same observation, which is why a stalled run read exactly like a finished one.
- **The printed `monitor:` line no longer recommends `tail -F`.** That form never exits, so it
  cannot report completion: a lane following it watches a stream that goes quiet whether the work
  finished or wedged. It now names `tautline monitor-status`, which reads the reaper's receipts.
- **A log written outside the lane's configured `runsDir` says so.** The turn-end yield gate scans
  that directory, and an advisory that is wrong in the reassuring direction is worse than none.

### Added
- Four monitor-lifecycle rules in canonical policy 20. The reasoning behind them lives in the
  background-monitoring skill reference, which costs neither the policy ratchet nor the rendered
  adapter corridor; only the rules themselves are canonical.

## [0.81.0] - 2026-08-14

### Added
- **An escape-hatch env var now names the functions allowed to read it.** `ESCAPE_HATCH_READERS`
  declares the reader set of every variable that stands a subsystem down — maintainer mode, snapshot
  exec, auto-rescue, the update policy and pins, trust signers, the main-branch requirement — and
  `tests/test_escape_hatch_reader_sets.py` re-derives that set from source on every run. A function
  that starts reading one of these without declaring it fails the suite, which is the obligation the
  2026-07-22 trust-pin RCA asked for: the problem was never that the hatches existed, it was that
  nothing could enumerate who obeyed them.
- The reader sets are **measured, not hand-listed**. The walk resolves two indirections a call-site
  scan cannot see — a key passed as a helper's own parameter, and a key computed by string surgery
  from a constant — because a scan for `resolve_env("<name>")` finds *zero* readers for two of these
  variables while both are read constantly. A declaration that no longer resolves is also a failure,
  so a relocation cannot leave the registry quietly naming a function that is gone.

## [0.80.0] - 2026-08-14

### Added
- New adapter key `goLiveReadiness` and canonical policy section **16a Go-Live Readiness Gate**. A
  lane that declares `profile: live-tenant` is held to six gates — customer-outcome health contract,
  detection baseline + branch protection, required-runtime-secret registry, CI test gate,
  critical-journey ratchet + flaky quarantine, and open-remediation obligation ledger — each of which
  must reach **its own satisfying state**, or carry a recorded decline naming the control and a
  reason. That state is not uniform: some controls take `enforcement: block`, others are satisfied by
  populating what they measure, and adding an `enforcement` key to a control that has none makes the
  adapter schema-invalid. `methodology-status` names the specific state each unsatisfied control
  needs.

### Changed
- **`runtimeConfig.requiredSecrets` no longer reports `block` for a registry nothing checks.** With
  secrets registered but neither `bootAssertionCommand` nor `secretParityCommand` set, the posture
  row now reports `empty`: naming the secrets is half the gate, and without an assertion command
  nothing on the lane ever verifies one of them. It reads as a missing input rather than as weak
  enforcement, because the enforcement string is not what is absent.
- **A `goLiveReadiness` block with an unknown key is refused by name**, not merged over the
  defaults. A misspelled key such as `profil` used to read as un-opted and enforce nothing while the
  lane that wrote it believed it was covered.
- **An opted-in lane sees why a gate is unmet without passing `--posture`.** Detail is limited to
  the six go-live controls, so the default surface's noise budget is unchanged elsewhere.
- **A lane that has not opted in gets one advisory line and no exit-code change**, at any flag
  combination including `--strict` and `--fail-on-drift`. That boundary is chosen against a measured
  constraint: `methodology-status --fail-on-drift` is the mandated lane-start command rendered into
  every generated adapter, and a shipped adapter already carries a milestone-close deployment target,
  so a drift failure here would have redded every live-surface lane at session start on upgrade —
  the adapter-removal 0.6.115 class.
- The forcing function is a shipped switch rather than silence: `goLiveReadiness.enforcement`
  (`warn` | `block`, **default `warn`**) makes the un-opted live-surface case drift when a lane sets
  it. Flipping the default is a separate release gated on adoption.
- A decline is a declaration, not a loophole: it names the control and states a reason of at least
  twelve characters. A control that is off with no decline is an undeclared gap, and the refusal
  names it **and carries the posture row's own detail** — `criticalJourneys` is an array with no
  enforcement field, so "set enforcement block" alone would be a dead end for exactly the controls an
  adopter most needs to fix.

### Upgrade safety
- **Not WIP-safe for a jump upgrade across 0.79.0.** This release's own change is advisory-only for
  a lane that has not opted in, but it *carries* 0.79.0's migrations forward — and 0.79.0's
  checkout-contradiction migration can newly make startup exit 2. A jump upgrade reads only the
  newest report, so the classification composes down from the predecessor rather than describing
  this diff alone.

### Rollback
- Adopters must remove `goLiveReadiness` from the source adapter and re-render **before** repinning
  below 0.80.0: the older schema sets root `additionalProperties: false` and rejects the unknown key,
  so lane startup wedges. A lane that never adopted it rolls back with no action.

## [0.79.0] - 2026-08-14

### Added
- `lane-start` and `methodology-status` now print `framework_checkout_reconciliation: <state>` and,
  when the state is **required**, `methodology-status --fail-on-drift` exits 2 as agent-fixable debt
  instead of printing a warning and exiting 0. RCA 2026-07-22 control 5: that incident persisted for
  weeks precisely because a channel/branch contradiction was reported as a bare warning and carried
  forward.

### Changed
- **The arming condition is narrow, and the narrowing is the design.** `required` fires only on a
  *contradiction* — the checkout sits on **another channel's** release branch — where all three
  enumerated resolutions are real. Every other non-release branch (feature branch, detached HEAD) is
  **advisory** and exits 0. An any-non-release-branch rule was written first and rejected against
  measurement: it would have made every framework session on a feature branch exit-2 debt whose only
  durable escape is a machine-wide maintainer-mode standdown, and a fail-closed control whose
  cheapest exit is a global gate standdown teaches the bypass this cluster exists to delete.
- The check is evaluated **outside** the "no pending update" branch the old warning lived in. The
  incident state *had* a pending update — that is what made the sync refuse — so a check evaluated
  only when no update is pending goes silent in exactly the situation it exists for.
- Two deliberate behaviour flips, both pinned by test, because the old warning hardcoded `main`
  instead of resolving the release branch from the channel: channel `experimental` with the checkout
  on `main` is a real contradiction and was silent — now `required`; channel `experimental` on
  `experimental` is correct and warned — now silent.
- `methodology_checkout_hygiene_warning` keeps only its dirty-checkout condition under its existing
  prefix. The two conditions have different owners and remedies.

## [0.78.0] - 2026-08-14

### Added
- `finalize-implementation-review` now reconciles the recorded unresolved counts against the review
  log the manifest pins and **prints** any divergence it finds. It is **report-only** — it does not
  refuse. The incident it addresses: a round whose log carried **3 Critical and 22 Important**
  findings was finalized at 0 unresolved Critical / 0 unresolved P1, and nothing on this path read
  the log to notice. The detector is not new; it has caught exactly this on the plan-review path for
  releases. It was simply never wired into this consumer.
- Two helpers for the successor that will enforce this: `classified_findings_all_blockers_resolved`
  (every recorded blocker disposed of, not merely one) and `classified_findings_cover_blocker_classes`
  (the classification must account for every blocker *class* the log shows, closing the case where
  blockers are omitted from the record entirely rather than left unresolved). The shipped any-one
  helper is untouched, so the three plan-review call sites are byte-for-byte unaffected.

### Changed
- The cross-check reads the **reviewer's answer**, not the raw log. An implementation review log is
  the whole `codex review` CLI transcript and carries no `## Findings` heading — that heading is a
  contract of the plan-review wrapper's prompt. Measured on a real 751,076-byte log, the findings
  section is 0 characters and the raw fallback is all 751,076.

### Known gaps
- **Enforcement is not claimed.** `review_log_verdict_errors` was built for a structured findings
  section, where a line mentioning Critical *is* a finding; this path feeds it free-form prose, where
  "The critical retry path is covered by tests." reads as blocker evidence. Enforcement waits on a
  reviewer-side structured findings contract.
- **`P0` and `High` are invisible to this scan.** A widened alias set was written and removed: under
  a bare-word match, "the tests provide high confidence" reads as a P1 finding.

## [0.77.0] - 2026-08-13

### Added
- A PreToolUse hook on `AskUserQuestion` now evaluates a question payload for the continue-vs-stop
  / pick-path menu shape and **logs** what it finds. It ships **advisory** and denies nothing by
  default; `responseGuard.questionGuard: "blocking"` opts a lane into the denial. The menu control
  is therefore **not closed** by this release and is not claimed to be: three consecutive review
  rounds each found a fresh false positive in the classifier, ending with a genuine operator-owned
  approval question being denied — which can deadlock exactly the work whose only legal next step is
  requesting approval. The shape is measured instead, and the promotion is its own item. The
  prohibition on pick-path menus already existed in canonical rule; what did not exist was any
  enforcement that could see it. The Stop guard reads text and such a menu is payload-shaped, so the
  exact pattern the free-text detector was built to catch was invisible to every guard — and because
  that tool blocks the turn waiting for a human, the Stop hook may never fire at all. Guided
  onboarding's sanctioned use, questions asked between goals, an explicit user stop, product-dev
  mode, and any single-object true-blocker question (which credential, which scope, which approval
  condition) all pass, each pinned by a test. Demote with `responseGuard.questionGuard: "advisory"`.
- `tautline stop-guard-aggregate` measures the **aggregate** stop-blocking rate across the whole
  Stop boundary over a frozen corpus, and compares it with a committed baseline. Four separate plans
  add blocking conditions to that one boundary; each measured its own false-positive rate in
  isolation and nobody owned the total, with the named risk being a lane that cannot end a turn at
  all. The ceiling is +2 percentage points across all four combined. The corpus digest is pinned
  into the baseline so the number cannot be brought back under the ceiling by deleting the entries
  that started failing.
- `responseGuard.highPrecisionPhraseChecks` (default `blocking`) introduces a high-precision phrase
  tier. Plain phrase checks default to advisory and no shipped adapter overrides them, so a new
  Stop-seam check in the standard tier is telemetry-only in every real lane. Admission is narrow by
  rule: only a check whose false-positive surface is structurally bounded, with independent
  carve-outs each pinned by a negative test.

### Changed
- Two new Stop-boundary checks — `stop.announce_and_stop` (a final turn asserting an in-progress or
  next action with no evidence after the announcement) and `stop.standing_authorization_reask`
  (re-asking break-glass or admin-merge authorization a source-of-truth artifact already grants) —
  ship **warn-only** and block nothing in this release. They log guard events so the shapes stay
  visible and measurable. Every check in this four-PR chain stays warn-only until the fourth lands
  and the aggregate is re-measured a final time.
- The Stop-hook flattener now walks an `AskUserQuestion` tool record's questions and options.
  Targeted, never generic: a plain `input` key would pour every `Write` tool's entire file body into
  every Stop-guard scan.

## [0.76.0] - 2026-08-13

### Changed
- The closing-reference checks now run only where the backlog is ISSUE-BACKED — an
  enabled `goalTracker` or `backlogProvider` that also carries `owner` and
  `projectNumber`, the same fields that decide whether the generated adapter states
  the PR-reference contract at all. The merge boundary previously had no provider
  guard, so it demanded a closing keyword from repositories with no issue backlog,
  and the compliant-looking way out of that refusal was to invent a reference —
  the exact harm the contract forbids. Both boundaries now read one predicate.
- The fence/inline-code blanker both closing-reference scanners share follows
  GitHub's actual rules: `~~~` fences are code, a fence closes on a run of at least
  its opening length, an inline span needs an exactly equal run, an unclosed fence
  is code through end of input, and a span may contain line endings. Previously
  `~~~` fences and double-backtick spans were invisible to it, which cut both ways —
  a PR body quoting a bad example was refused for quoting it, and a real closing
  reference hidden in one of those forms passed while GitHub closed nothing.
- Canonical policy and the `board-item-updates` skill reference now describe the
  gate that actually ships, including what remains unenforced.
- **Not WIP-safe.** Recognizing more code forms is itself a behavior change: a PR
  body whose ONLY closing reference sat inside a `~~~` fence or double-backtick
  span was accepted at 0.75.0 — the blanker could not see those forms, so the
  reference read as live text — and is now correctly treated as quoted example
  text, so that body binds nothing and `missing_closing_ref` refuses the next push
  or merge. Move the reference out of the code span before upgrading.

## [0.75.0] - 2026-08-13

### Changed
- Code ownership is an organization team (`@tautlines/maintainers`) rather than a
  personal GitHub handle. A personal handle in a public repository publishes a
  maintainer's identity on every review notification and in every fork; a team
  handle routes review requests identically and publishes no one's.
- The public-boundary scan no longer exempts `CODEOWNERS` from its person-reference
  check. That exemption existed on the reasoning that routing required a personal
  handle; it does not, so `CODEOWNERS` is now scanned like every other surface.
- The boundary scanner no longer embeds the tokens it scans for as plain literals,
  so the file guarding against publishing an identity stops publishing one itself.
- The session-journal shell-transcript heuristic no longer carries one maintainer's
  username in its prompt-prefix list. The entry is removed, not replaced: detection
  narrows slightly and broadens nothing, so no journal that validated before is refused
  now. Generalizing the heuristic to recognize any user's prompt is a real improvement
  and a real behavior change; it is filed separately rather than carried by a
  sanitization release.
- `tests/test_public_boundary_scan.py` is excluded from the public release export. It is
  a private-repo guard whose content IS the denylist of identifiers that must not reach
  the export, so it cannot ship without publishing exactly what it exists to withhold.
  The scan itself is unchanged and still runs where the export is produced.
- `tools/carve/HANDOFF.md` is excluded from the public release export: it is
  internal cross-machine campaign state naming workstations, worktrees, and local
  run counts. The carve tooling beside it still ships, because `cli.py` and shipped
  release migrations reference it.

## [0.74.0] - 2026-08-12

QUEUE item 101: pull requests say which backlog item they advance, and whether they finish it.

### Added

- **The PR↔backlog reference contract**, in canonical policy and in the generated adapter of every
  repo whose backlog is GitHub issues. A separate agent now mirrors build progress onto the
  stakeholder board by reading pull requests and issue states alone, so PR text is its only
  evidence: the item's **issue** number goes in every PR title (never the Project number or a
  project item id); a PR that **completes** an item carries one closing keyword per item on its own
  line; a PR that only **advances** one carries no closing keyword anywhere, and references the
  item in the title alone. Never reference an issue the PR does not implement.
- **The `board-item-updates` skill carries the operational detail** — the reference forms GitHub
  honours, the one-keyword-per-issue rewrite for `Resolves #A, #B`, and the advancing-versus-
  completing decision.

### Changed

- **The auto-close is stated with its condition, not as a promise.** GitHub honours a PR-body
  closing keyword only when that PR's base is the repository's **default** branch. A lane
  integrating on another branch gets no auto-close at merge; its squash commit message is what
  carries the keyword to the promotion that fires it. The rule says so, because a rule that
  promises a mechanism which silently does not fire is worse than no rule.
- **The rule states its own enforcement gap.** The closing-reference gate still demands a keyword
  from every non-exempt PR body, so an advancing PR can be refused for obeying the new rule. The
  published rule names that gap and names the wrong way around it: never satisfy the demand with a
  reference to an issue the PR does not implement.
- **This repository stops doing exactly that.** Its own lanes had been satisfying the gate with the
  backlog QUEUE number, and every one of those numbers addressed an unrelated already-merged PR in
  this repo. `backlogProvider.allowRepoOnlyGoals` is now set, which is simply true here: no
  GitHub-issue backlog, no board, work items in an external Markdown queue.
- **`backlogProvider.planRepo` is set for this repo**, turning on the plan-in-place review that
  0.73.0 shipped the capability for but left unconfigured.

### Fixed

- **Repos with no issue-backed backlog render none of this.** The contract text is gated on the
  same three conditions as the board pin — provider enabled, owner, project number — and an
  issue-less adapter renders byte-identically, proven by mutation rather than by absence.

## [0.73.0] - 2026-08-12

QUEUE item 59: a plan may live outside the lane that reviews it.

### Added

- **`run-plan-review` accepts an external plan**, addressed as `<root>:<path>` where the root token
  is the plan checkout's directory basename. Every batch packet this framework has shipped carried
  a workaround for the absence of this — copy the plan into the lane first — and that copy is what
  made a reviewed plan and its published original two different files.
- **`backlogProvider.planRepo`** names that checkout. Empty by default, which means lane-only —
  exactly what every existing lane already does.

### Changed

- **Manifest identity is the recorded reference resolved to a path, not its spelling**, so two ways
  of naming one plan adopt the same evidence instead of forking it. All existing review manifests
  stay byte-identical.
- **WIP-safe and additive.** A recorded reference with no root token keeps its current meaning.

## [0.72.0] - 2026-08-12

Item 80 (N6): plan content problems surface while fixing them is still free.

### Changed

- **`run-plan-review` now warns at round one** about content problems that
  `plan-finalization-precheck` would refuse later — missing assumptions, dependencies, acceptance
  criteria, completion definition. The point is *when*: plan edits before R1 cost no review budget
  and void no evidence, while the same fix after a round unbinds the evidence that round produced.
- **WIP-safe.** `planning.contentPregate.enforcement` defaults to `warn`, so nothing new refuses.
  Set it to `block` to refuse section-shaped gaps at zero observed runs; length and marker
  heuristics stay advisory even then, and everything is advisory once a round has been observed —
  forcing an edit mid-loop is the defect this closes, not a stricter version of it.

### Added

- **`tautline plan-substance-check`** answers the same question explicitly, and is *not* softened
  by that knob. `--list` needs no adapter.
- **`planning.templateCoverage`** (default `report`; no blocking value exists) measures the shipped
  template against the same contract: if a lane can fill it in completely and still fail, the
  template is the defect.
- A **sizing advisory** at the same seam — hint-grade, permanently non-blocking, and silent on
  every plan this repo ships.

## [0.71.0] - 2026-08-12

Item 68 PR4 (occupancy, wave 2.6). Closes the occupancy chain.

### Changed

- **A recorded `codex-run` now takes a review lease and refuses when another round is already
  running against the same checkout.** Two rounds on one diff spend two reviewer invocations
  against one budget and race to write the same evidence log. **Not WIP-safe.** The refusal names
  the holder and both ways out: wait for that round, or review from your own worktree.
  Non-recorded invocations take no lease.
- The lease is released in a `finally`, so a killed or crashed round frees it. A round whose
  wrapper is gone is reclaimed on the next attempt; a 90-minute TTL is the backstop.
- **Occupancy records gain an optional `owner` field, defaulting to `session_id`.** A record
  written without it keeps its exact previous meaning, so lane leases already on disk stay valid
  and every 0.68.0/0.70.0 behaviour is unchanged. The field exists because a *session* and a
  review *run* are different holders of the same mechanism.

## [0.70.0] - 2026-08-12

Item 68 PR3 (occupancy, wave 2.5).

### Changed

- **`tautline lane-status` reports a new finding, `CONCURRENT`**, when another live session is
  working in this worktree. It leads the report: every other finding describes a state the lane
  can reason about, this one says the lane's own edits may not be its own.
- Rendered at `drift` severity. The report never blocks — 0.68.0's `lane-start` refusal is where
  occupancy has teeth. A rerun cannot clear a live peer, so the report does not offer one.
- **WIP-safe.** Nothing new refuses, and a lane with no peer sees exactly what it saw before: the
  uncommitted-changes line is reworded *only* when a foreign session is present.

## [0.69.0] - 2026-08-12

Batch 2026-08-11 item B7. Tautline now has one definition of done, and it is enforced.

Released as `0.69.0`. `0.64.0` (#532), `0.65.0` (#533), `0.66.0` (#535), `0.67.0` (#536) and
`0.68.0` (#537) were each claimed by another lane while this change was in review -- five times. Versions are expectations, never reservations.

### Added

- **One definition of done, named and adapter-overridable.** Seven conditions — `scope_complete`,
  `tests_written`, `tests_green`, `review_clean`, `evidence_bound`, `pr_handed_off`,
  `board_updated` — each with a real checker over real lane state, in the new leaf module
  `done_definition.py`. Before this there was no `definition_of_done` symbol anywhere, no
  statement of one in the canonical rules, and three unrelated fragments standing in for it.
- **`done-check`**, which prints the verdict condition by condition (`pass` / `fail` / `unknown` /
  `skipped`) with a summary line and a machine-readable `--json`. It exits 1 only on a `fail`.
- **`goal-assignment --out <path>`**, which writes the goal's exact bytes to a file and prints the
  copy command. A goal is an artifact, not chat prose: the file bypasses every renderer between
  composition and paste.
- **`definitionOfDone` adapter key** (`enforcement`, `conditions`, `integrationBranch`), read-side
  only on the `autonomy` precedent, so an absent key stays absent and no existing adapter
  regenerates. Rendered-adapter cost: **zero bytes, asserted as a delta against the merge base.**

### Changed

- **`goal-advance --event goal-complete` refuses a failing condition under `enforcement: block`**, at the same pre-flight seam
  as the closure gate and **before it**, so a refused done move mutates nothing on any board. A
  condition the checker could not read is `unknown`: reported loudly, never `0`, and never
  blocking — a bar that blocked on what it could not read would wedge an offline lane.
- **The done bar is HANDOFF, not merge.** `pr_handed_off` passes when the PR is out of the lane's
  hands — merged, auto-merge armed, or in the merge queue, targeting the integration branch. An
  open PR with nothing armed fails. **It never requires a lane to wait for a queued PR to land**,
  which would trade one waste for the worse one the `watch-until-merged` detector already forbids.
  The integration branch is adapter-resolved, never hardcoded to `main`.
- **Every composed goal states the bar it will be judged by.** `compose_goal_assignment`'s
  completion clause is built from the project's *effective* enabled condition set instead of a
  hardcoded sentence, so a project that disables `pr_handed_off` is not handed a goal demanding a
  PR. The old clause ended "the PR is queued to merge" — the framework's own goal-writer
  authorizing the exact stop being complained about. Composed goals also state that the human is
  away for the duration.
- **`goal-condition` states the same bar, from the same source.** The documented Claude `/goal`
  path composes goals too, from what used to be its own hardcoded completion sentence — so fixing
  only `compose_goal_assignment` left the framework stating two different bars depending on which
  verb you ran, and the one an operator actually runs was still the pre-B7 text. Both surfaces now
  read `goal_assignment_effective_conditions`; disabling a condition drops its clause from both.
- **`goal_assignment_shape_issues` now has teeth on content**: a completion clause that names no
  handoff condition is refused.
- **A `goal-complete` rerun with no resolvable session id clears the previous stamp** instead of
  inheriting it. A stale `completedBySession` made the Stop arm correlate a completion to a session
  that had already ended, suppressing the advisory for the session actually at the boundary.
- **A goal is length-checked against a new authoring ceiling of 3,600**, below the delivered cap of
  4,000. The check was measuring the source string while the goal's real path is
  `source → render → terminal → copy → paste`; a measured 3,659-character goal had 5.17 spaces per
  line of headroom, so a six-space renderer indent delivered an over-limit goal that had passed.
  Refusals name both numbers.
- **The Stop boundary no longer goes silent when a session declares its own goal done.** It warns —
  through the advisory channel, never a block decision, per RCA DECISION 4 — naming the failing
  conditions and the next action, and a fresh `blocker-declare` record releases it. The warning
  fires only for a goal *this* session completed, correlated by a new `completedBySession` stamp;
  an un-correlatable completion reports one honest `unknown` line rather than guessing.

## [0.68.0] - 2026-08-12

Item 68 PR2 (occupancy, wave 2.4).

### Changed

- **`tautline lane-start` now refuses when another live session already holds this checkout.**
  Two sessions editing one worktree overwrite each other's files with no error and no way to tell
  whose change survived. **Not WIP-safe.** The refusal carries its own way out: a runnable
  `git worktree add`, and the command to clear a lease whose session is gone.
- **`fleet.occupancy` is new, on by default**, with `mode: refuse`. Set `mode: observe` to report
  without refusing, or `fleet.occupancy.enabled: false` to opt out; the master `fleet.enabled:
  false` still turns it off along with everything else.
- **`lane-status` records the session on every session start**, before its own `startupCheck`
  early return, so lanes that turned the startup check off still leave a trace. That path never
  refuses and never raises — it runs as a hook.

## [0.67.0] - 2026-08-12

Items 76 + 77 (batch-1 slot W1.3), one PR per INDEX section 3.

### Changed

- **`codex-plan-review` refuses a direct invocation** and names `run-plan-review` as the way in.
  The launcher is what holds the in-flight lease, so a direct call was a round nothing was
  serialising — two reviewers could launch against one plan and neither would know. **A previously
  working invocation now refuses**; the message carries the fix.
- **A reviewer log with no recognisable verdict heading no longer finalizes.** The parser's
  prompt-echo defect was fixed at the mechanism level, but a log that never contained a real
  verdict could still bind evidence — which is the failure the fix was for. Applies to logs
  recorded from this release onward.
- **`run-plan-review` takes a 2-hour in-flight lease.** A malformed or stale lease cannot crash
  the launcher or lock a lane out; clock skew is not evidence a round ended; and the handshake is
  dual-written so the evidence log stays clean.

## [0.66.0] - 2026-08-12

Item 79 WS1.

### Changed

- **A merge now records the board closeout it owes.** Closing the board card is work the merge
  *causes* but cannot finish inside the merge itself — the PR is not merged until it is merged, so
  at that instant the closeout can only be owed. Writing the debt down is what makes it survivable:
  a lane that dies between merge and closeout now leaves a record naming exactly what is owed,
  instead of a silently unclosed card nobody knows about.
- **`tautline backlog-provider-closeout-check` settles that debt**, and the prepush boundary
  refuses while one is outstanding. **Not WIP-safe**: a lane that merges and then pushes again
  without closing out will be stopped, with the owed closeout named.
- The merge itself is never blocked by this. Blocking a merge on post-merge work would be a
  deadlock, which is why the debt is recorded rather than enforced there.

## [0.65.0] - 2026-08-12

Item 79 WS2. Closes RCA `2026-06-15` (#307/#260) and RCA `2026-07-18` control 3.

### Changed

- **A PR body now has to bind the issues it closes.** Two checks run at the prepush board gate and
  at `tautline merge`:
  - `Resolves #A, #B` is refused. GitHub honors a closing keyword for the **first** ref only and
    drops the rest silently — #260 stayed open and nothing warned, because from GitHub's side
    nothing went wrong.
  - A body with **no** closing reference is refused: merging it auto-closes nothing, and 18 of 60
    merged PRs were measured in exactly that state. The comma-list check cannot catch this — zero
    refs yields zero list errors — which is why both checks exist.

  **Not WIP-safe: a previously green PR body can now refuse.** Each message carries its own fix.

- The missing-reference check is **exempt** where the lane has already said the obligation does not
  apply — a non-development work profile, a recorded `board-binding` decision, or
  `allowRepoOnlyGoals`. All three resolve through **one** function both boundaries call, so prepush
  and merge cannot disagree about the same lane. None of them excuses a *malformed* comma list.
  At merge both checks ride the existing `mergeGate.enforcement` switch and run **before** the
  `--override` decision record, so a refusal cannot leave the ledger claiming a break-glass for a
  merge nothing attempted. The `board-binding` exemption is scoped to a decision recorded
  **newer than the branch's merge-base** — an unscoped scan would mean that using the
  documented escape hatch once exempted every later PR in the repository forever, a control
  that disables itself the first time someone legitimately uses it.
- GitHub's cross-repository closing form `owner/repo#123` is accepted; it auto-closes exactly
  like `#123`, and refusing it meant the gate rejecting correct work.
- A `body` field **absent** from the provider response is an unanswered question, not an empty
  body: both boundaries warn and proceed rather than refuse a PR whose body was never read.

## [0.64.0] - 2026-08-12

Item 71 PR3 (WS4). Closes RCA `2026-07-31` control 4 and completes item 71.

### Added

- **`allowRepoOnlyGoals`** — a new optional adapter key, **off by default**, on both `goalTracker`
  and `backlogProvider`. A goal with no GitHub Project Source item can proceed repo-only instead of
  refusing.

  The sync used to raise **unconditionally** and name no way out, so a lane whose work genuinely
  has no board item had exactly two exits, both bad: disable the tracker wholesale, or hand-edit
  the ledger. A refusal that names no sanctioned alternative is where bypasses get invented, and an
  invented bypass is worse than the allowance it replaces.

  The refusal now names the knob, still offers the sync remedy first, and says the change belongs
  in the **source** adapter and must be re-rendered. With the knob set, the run prints
  `goal_tracker_repo_only_goal:` and states that board status is not updated for that goal —
  proceeding silently would be its own defect. The **drift gate honors the same knob**, because a
  gate reporting drift for the exact state its own sync sanctions makes the sanctioned path
  unusable. A goal that *does* have an item takes the normal path either way.

  **The allowance covers the goal item and nothing else.** A board-backed **milestone** under
  a repo-only parent still syncs, and milestone drift is still checked — an early return
  would have turned a parent-goal allowance into a milestone-sync opt-out, silently, because
  the run would report success while writing nothing to the board. The pre-existing fallback
  that rolls an unmapped milestone up to the parent item does not fire when there is no
  parent item to roll up to.

### Note on the record

QUEUE row 71 recorded this workstream as shipped in 0.46.0 (#513). `git grep allowRepoOnlyGoals`
returned **zero hits** on the merged tree and the sync still raised unconditionally — it never
landed. The row stated claim-time intent, not merged code. Corrected in the backlog; it ships here.

## [0.63.0] - 2026-08-12

Item 71 PR2. Closes RCA `20260702T202523Z` and the read-side half of `20260627T193516Z`.

### Added

- **The board's identity is adapter-declared, and now verifiable.** The generated adapter renders
  `- Board pin: <owner>/projects/<n>` when the enabled provider carries one — and renders nothing
  when it does not, because a lane with no pin should get no line rather than a line that guesses.
  `backlog-provider-board-check` compares the identity recorded in every synced goal source against
  that pin and **blocks on a mismatch**, on the same exit-1 path as drift: a board that is not the
  pinned board is not out of date, it is the wrong board. Its ok path prints `board_identity:`, so a
  passing gate is distinguishable from a gate that never ran.
- **A `github-projects-reads` skill**, the read-side complement to `board-item-updates`, carrying
  the four controls with the surface traps that produced them — including that
  `gh project item-list --format json` omits `fieldValues` on some `gh` versions, where a null is
  not an empty field but an unanswered question.

### Fixed

- **The board position map read one page and believed it was the board.** A single un-cursored
  `items(first:100)` meant that on any board past a hundred items, every later item was missing from
  the authoritative order — and the selection site then ranked it by a synthetic
  `len(position_map) + position`, putting real board order and fallback order in the same sort key.
  It now paginates to the same ceiling the verified read uses, and returns an **empty** map rather
  than a partial one on a mid-pagination failure: a half-filled map looks authoritative while
  silently ranking the items it contains above every item it does not.
- **Two warning-only board reads degraded silently.** `provider_board_business_lead_gaps` and
  `lane_unplaced_customer_facing_issues` still return `[]` on an unreadable board — they are
  non-blocking by design — but now say `board read incomplete` first. Both report what is *missing*,
  so an unreadable board produced the most reassuring possible answer from the least evidence.
- The currency gate's truncation-drift branch shipped in 0.46.0 with no regression test and has been
  unpinned for six releases. It is pinned now, with its positive twin.

### Changed

- Policy states both rules: a queried project number differing from the configured `projectNumber`
  is **blocking drift, not a fallback candidate**; and operator-observed UI state is **ground
  truth** against an agent's API result — arguing with operator evidence is a stop-the-line defect.

## [0.62.0] - 2026-08-11

Closes RCA `20260707T181643Z-methodology-regression-rca`. With 0.61.0, this completes item 75.

### Changed

- **Implementation-review rounds are counted by execution, not by label.** Six executions against
  one lineage, every one invoked as `R1`, each passed a label-derived cap as round 1 while the
  aggregate was round 6. Rounds are now counted per outgoing lineage (branch plus review base).

  **Two currencies**, because one number cannot serve both comparisons: the absolute ceiling counts
  **total** executions — all six of the incident's runs were confirming-by-predicate, so only
  quantity separates a pathology from a healthy remediation loop — while the tier budget and the
  self-authorization rung count **charged** executions, the confirming predicate replayed over the
  recorded sequence. Every free round stays free and the budget stays reachable.

  **The recorded `branch` is verified, not inferred from the filename slug.** `feat/a-b` and
  `feat/a_b` slugify to the same filename component and share a glob, so a fresh branch could
  warn, spend budget, or hit the hard cap on another branch's reviews.

  **The confirming predicate reads the same ledger as the counters.** Given a lineage base it
  scopes to that lineage, so a branch carrying an old-base or void manifest no longer has its
  first new-lineage round admitted free and then replayed as charged — free going in and
  charged coming out is a budget bug in either direction.

  A void manifest is not counted as a spent execution, and a `--review-round` label the ladder
  would reject — no digits at all, or a non-positive marker like `R0` — reaches that refusal
  unchanged. Only a positive parsed marker is effective-counted; promoting the others would
  hand the ladder a positive number and silently retire a validation it already had.

- **Not WIP-safe.** A branch that has already recorded rounds is now at the round its *executions*
  say, so a lane mid-remediation — especially one that has been relabelling — can meet the hard cap
  sooner than it expects on its next run. Both exits are unchanged and neither needs another Codex
  execution.

### Added

- **A visible per-lineage counter.** `codex-run` prints `codex_run_execution_count:` on every run,
  label or not, and warns when this attempt would be the third. It reports an **attempt** alongside
  the recorded and charged counts, not an execution: the line prints before the run is known to
  record anything, and claiming a spend that did not happen would be the same dishonest accounting
  this release removes.
- Stage 2 manifest filenames carry microseconds — separated by a `.`, so the time-of-day and the
  microseconds never run together into twelve consecutive digits, which the public-release scan
  correctly reads as an account-like identifier. These filenames are recorded *into* the tracked
  `.impl-reviews/` ledger, so without the separator every future review would ship a false
  positive into a public repo. The manifest and the log it pins share **one** stamp definition. Two executions inside one second used to collide; fixing only the manifest
  would make the first execution's evidence permanently unfinalizable.

## [0.61.0] - 2026-08-11

Closes RCA `2026-07-28-empty-diff-review-recorded-clean`.

### Added

- **A review with no subject is refused before it can be recorded, ledgered, or charged.**
  `head_sha == base_sha`, zero diff bytes, or `diff_sha256` equal to the empty-string digest now
  refuses at manifest validation — closing `finalize-implementation-review` and the prepush
  evidence scan together — in `codex-run` before the wrapper is invoked, in the evidence writer
  itself (which recomputes state *after* the wrapper, so a wrapper that moves `HEAD` cannot slip a
  void manifest past the pre-flight), and in `record-stage1-sweep`, whose narrower
  zero-bytes-only check let a sweep over nothing unlock a review of nothing. Each marker refuses
  independently, so a forged manifest that omits `diff_bytes` cannot slip past; absence of all
  three is **not** voidness, so an underived subject falls through rather than minting a refusal.
  `review-evidence-check` is the one deliberate exemption: an empty *outgoing* diff at push time
  legitimately owes no evidence.

  The original incident is exactly this shape — a void manifest matched a void state, because the
  equality check that binds evidence to a subject passed on the **absence** of one.

### Changed

- **A recorded `codex-run` that writes no manifest now exits non-zero.** A zero wrapper exit with
  no evidence is not a successful review: nothing was recorded, nothing can be finalized, nothing
  binds the diff.
- Prose-completeness and coverage-breadth findings on non-authoritative documentation now have a
  written default of P2 in `17-review-before-push` — a rule both source RCAs asked for and which
  `grep` confirmed existed nowhere.

## [0.60.0] - 2026-08-11

### Fixed

- **A done-evidence comment now goes to the item's repository, not the lane's.** For a board item
  backed by an issue in another repository, the verification claim was posted to the **same-numbered
  issue of the lane's own repo** — a real, unrelated issue belonging to someone else. The closure
  gate had already learned to *read* the acceptance criteria from the item's own repo, so one
  command read from one repository and wrote to another. Both sides now share a single resolver, so
  they cannot diverge again. `stakeholder_issue_post_comment` takes a **required** repo argument:
  the default that produced this defect is gone rather than corrected.

### Changed

- **An unresolvable evidence target is refused, not guessed.** An item whose linked URL yields an
  issue number but no parseable `owner/name` (an enterprise host, an API-shaped URL) no longer falls
  back to the lane's repository. That fallback was unreachable for an item with no link at all —
  which has no issue number either and is refused a line earlier — and in the one case that did
  reach it, the lane's repo was a guess that published a third party's claim onto an unrelated
  issue.
- **The refusal lands before anything is mutated.** The evidence target for the parent *and every
  board-backed subtask* is resolved in a pre-flight that runs ahead of the first status edit, and is
  reachable from `goal-advance`'s closure pre-flight — which is the only seam earlier than the
  required UI-evidence comment. The pre-flight is pure URL parsing and adds no network call, so a
  single-repo lane pays nothing for it.
- **`stakeholder-question-ask --issue <url>` refuses a URL naming another repository.** It
  previously kept only the issue number and commented on the lane's same-numbered issue. A URL whose
  repository cannot be parsed is refused too — that is the case a "does the repo differ?" check
  would wave through. Pass a bare issue number to act on the lane repository.

Known residual, tracked as this item's Release B: a repository that is now addressed **correctly**
may still refuse the write, and that failure can surface partway through a multi-subtask sweep. No
read-only check can predict it, so it is not claimed closed here.

## [0.59.0] - 2026-08-11

### Changed

- **The canonical rules now state the oracle-discipline rule the gate has been enforcing** since
  0.56.0. `methodology/policy/10b-board-currency.md` — and the `board-item-updates` skill and its
  reference — say it in three parts, none inferable from the others: closure evidence for a
  provider-backed item is measured against that item's **written acceptance criteria** and carries
  one PASS/FAIL row per criterion; **an unmet criterion is a FAILED AC, never a deferral**; and
  verifying the implementation against itself — "within the shipped model" — is forbidden, because
  a table built from the code cannot fail. Prose only; no code path changes. A lane already passing
  the gate sees no difference, and a lane that meets the `strict` refusal can now read why.

## [0.58.0] - 2026-08-11

### Added

- **`goal-advance` reads an optional milestone `acVerification` key** — inline AC table text, or a
  repo-relative path to one — so a lane that authors the table into the milestone before advancing
  needs no command-line flag. That is what keeps the primary autonomous closure path usable
  unattended once the gate is `strict`. The key is optional and absent-stays-absent: unset, the
  composed evidence is byte-identical to 0.57.0. The path must resolve **inside the checkout**,
  symlinks included, because its contents are posted to the linked issue. There is no precedence
  rule between the key and the `--verification-evidence*` flags, deliberately: both are appended,
  milestone first, and the gate decides per criterion by the last verdict recorded — so a
  command-line correction lands after the milestone's table and decides.
- **The `milestone-complete` evidence guard accepts that table as completion evidence** — alongside
  `--detail`, `--milestone-run`, a recorded `milestoneRun`, and `validationEvidence`. Widening only:
  nothing that satisfied the guard before stops satisfying it. Without it the no-flag channel is
  unreachable, because a lane that authored the table into the milestone and supplied nothing else
  was refused before composition ever ran. The guard weighs the **resolved text**, not the key's
  truthiness, so an empty or whitespace-only file does not open it — otherwise the command could
  publish its required UI-proof comment and only then refuse, mutating on a refused move. The value
  is resolved for `milestone-complete` only: `milestone-started`, `-blocked`, and `-deferred` never
  use AC verification, and a stale or out-of-tree path must not be able to block the transitions a
  lane uses to report that something is wrong.

## [0.57.0] - 2026-08-11

### Fixed

- **A false refusal shipped in 0.56.0, and the mechanism that caused it.** 0.56.0 decided at
  *compose* time whether fresh evidence displaced a recorded AC table, and dropped the recorded
  table whenever the supplied evidence merely contained PASS/FAIL rows — a CI matrix, a test grid —
  after which the gate refused the closure for criteria it had just discarded. That decision cannot
  be made correctly where it was being made: two rows can each name the same acceptance criterion
  without naming each other, and the composer does not have the criteria. It is gone. The gate,
  which does have them, now judges each criterion by the **last verdict recorded against it**, so a
  correction appended after a stale entry decides and nothing is dropped from the posted evidence at
  all. A `PASS` row written *above* a `FAIL` row for the same criterion still fails it.

## [0.56.0] - 2026-08-11

### Added

- Closure verification is now measured against the item's own written acceptance criteria. When a
  provider-backed item's linked issue carries an acceptance-criteria section, the done evidence must
  contain a line-by-line pass/fail table with one PASS/FAIL row matched to each criterion. Rows are
  matched injectively, so duplicate or paraphrased rows cannot cover distinct criteria, and a
  `DEFERRED`/`PARTIAL`/`N/A` verdict is not a row at all. A `FAIL` row refuses the done move: an
  unmet criterion is a FAILED AC, never a deferral, and no ordering of rows or of matching stages
  can hide one. The check runs as a pre-flight, before any board write or comment, so a refused
  done move mutates nothing.
- `tautline ac-verify --item <ref>` prints the fill-in table skeleton from the item's own criteria,
  optionally writing it with `--out`. It is the runnable continuation every refusal on this surface
  names, and it derives the skeleton from the same splitter the gate uses, so the table a lane is
  told to produce is exactly the table the gate accepts. The **unfilled** skeleton is refused: a
  form that verifies itself is not verification.
- `goal-advance` gains `--verification-evidence`, `--verification-evidence-file` and
  `--verification-evidence-url`, composed through the same helper the other two done verbs already
  use, so file reading and URL validation keep one definition. A supplied AC table supersedes a
  stale one already recorded in the milestone's `validationEvidence` — a FAIL row anywhere in the
  evidence fails its criterion, so an appended correction would leave the stale FAIL refusing the
  closure it was meant to unblock. Before this release the primary autonomous closure path had no
  operator evidence channel at all, and with none supplied the composed evidence is byte-identical
  to before.
- Verification-claiming comments posted through the CLI are measured against the same criteria under
  the same knob. Comments that claim nothing about verification are never fetched and never checked.
  Named residual, not closed: a claim written into a PR body, chat, or a summary composed outside
  the CLI is not covered.

### Changed

- New adapter knob `backlogProvider.doneEvidence.acTable` (`off` | `warn` | `strict`), default
  **`warn`**: the finding is printed and the move proceeds. An unreadable issue body reports an
  explicit `done_evidence_ac_state: unknown` rather than degrading into a silent pass, so the
  fail-open rate is measurable before anyone considers `strict`. The migration report publishes the
  criteria for that promotion. The canonical rule that states this discipline in prose ships in a
  following release (WS3); this one ships the mechanism.

### Known gaps

- A done move on a **cross-repo** board item still posts its evidence comment to the lane's repo
  rather than the item's. That predates this release and is filed as backlog item 95; this release
  makes it visible because the gate reads the criteria from the item's own repo. Same-repo items
  are unaffected.

## [0.55.0] - 2026-08-10

### Added
- **`behavior-spec-status --base <ref>` reports the inactive scenarios your branch added.** The
  repo-wide counts answered "how much debt is there", which a repo carrying long-standing debt
  answers identically whether a change added to it or not — so growth per change was invisible at
  the one surface policy 15 requires before every finalization, merge and delivery. `--base` prints
  `behavior_specs_added_inactive: <N> (vs <ref>)` — every scenario newly inactive since the merge
  base, annotated or not, because a fully annotated `@pending` is still growth — alongside
  `behavior_specs_added_issues: <N> (vs <ref>)` and one `behavior_specs_added_issue:` line per
  scenario the branch left without the owner and un-pend-trigger annotations, each citing the
  canonical form. **The two counts are different sets, not nested:** stripping metadata from a
  scenario that already existed reports `0` added and `1` issue, because that is debt the branch
  introduced without introducing a scenario.
- It compares two committed trees, so an uncommitted edit never moves the answer, and **both**
  counts print `unknown` rather than `0` whenever it cannot see — an unresolvable or blank ref, no
  common ancestor, an unreadable feature file, a path scope that selects nothing, or an unexpected
  failure. A check that cannot look must not print what a clean branch prints. Where
  `behaviorSpecs.pendingRequiresOwnerAndTrigger` is `false`, the issue half reports
  `disabled by adapter` and the growth count still reports.
- `--base` is **reporting only and never changes the exit code.** The exit code stays exactly what
  it was: repo-wide issues under `--strict` or strict enforcement. Enforcement of the same rule at
  the boundary that creates the debt is `behavior-spec-delta-check`, which refuses the
  metadata-less scenarios a staged change introduces and lets pre-existing debt through.

### Known gaps
- **A Gherkin scenario has no stable identity, and this report inherits that.** Same-named
  scenarios in one feature file are paired in line order, so inserting a new bare `@pending`
  *above* an existing same-named one and annotating the original makes the new instance take the
  old one's slot: growth is still counted, but the issue half attributes it to the pre-existing
  scenario and reports `behavior_specs_added_issues: 0`. Deferred deliberately, not overlooked —
  the pairing helper is shared with `behavior-spec-delta-check`, and three of four review rounds
  in 0.50.0 showed every patch to it minted a fresh false refusal on that gate. Scenario identity
  is the successor plan's subject; a narrow under-report on a report is the cheaper side of that
  trade. Pinned by a test that is documented to fail when the successor closes it.

### Changed
- `behavior_specs_instruction:` now cites the machine-checkable annotation form
  (`@pending @owner:<goal-or-lane> @reason:<why> @unpend:<trigger>`), interpolated from the same
  constant the refusals use. Authors were discovering the shape by trial. The
  `behavior_specs_issue:` lines are unchanged byte-for-byte — consumers parse those.
- `behavior-spec-status` and `methodology-status` each scan the behavior-spec surface **once** per
  invocation instead of twice. Both computed the repo-wide record for their report and again for
  their strictness decision, and `methodology-status` runs before every plan finalization, merge
  and delivery. It gains no delta line and no new git work: no base ref is resolved anywhere in its
  scope, so producing one would mean adding a merge-base and a unified diff to that hot path.

## [0.54.0] - 2026-08-11

### Changed
- **The blocking Graphify freshness gate no longer depends on an LLM backend.** `DEFAULT_GRAPHIFY`
  prescribed a bare `graphify .` invocation with an update flag as the command that satisfied a
  BLOCKING pre-commit/pre-push gate. That form makes Graphify auto-detect a backend from ambient
  credentials, and when the provider retired the model auto-detect landed on, the documented gate
  command failed permanently — while the flag the gate actually checks (an mtime comparison) only
  ever needed the dependency-free no-LLM AST refresh. `updateCommand` and `buildCommand` now
  default to `graphify update .`, which was measured cold-building a repo from nothing with no API
  key and no `AWS_PROFILE`, so the auto-detect form survives in no default at all. A lane on
  defaults gets this automatically; a lane that pinned the old command keeps its pin and should
  adopt the split.
- **Semantic enrichment is a separate, non-blocking, backend-explicit step.** Two new adapter keys
  carry it: `graphify.semanticCommand` (default
  `GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli`) and
  `graphify.semanticRule`. Both are required non-blank and are published in
  `methodology/adapter-schema.json`; adapters that omit them inherit the defaults and keep
  validating. A new contract test asserts every `DEFAULT_GRAPHIFY` key appears in the published
  schema, so the next default key cannot escape the public contract the way these two would have —
  `properties.graphify` carries no `additionalProperties: false`, so the omission would have been
  silent.
- **The gate prints the command the adapter configured, not a hardcoded one.** `graphify-status`,
  the generated git hooks, and the rendered adapter's Graphify Navigation bullet now interpolate
  `graphify.updateCommand`/`graphify.buildCommand`. A project that had already moved off the broken
  invocation was still being told to run it — the divergence between the documented command and the
  printed one is what let the break survive. The rendered `(no-LLM)` qualifier is attached only
  when the configured command *is* the no-LLM default, so an adapter that pins an LLM-backed
  invocation is never handed a generated file claiming its gate needs no backend.
- Policy 25, the canonical rules, the `graphify-navigation` skill and the reference docs state the
  split, plus the general rule that a Graphify invocation which auto-detects its backend is never a
  gate command in any adapter, and the prevention-gap rule that **a review finding that a documented
  blocking gate command does not run is a source defect, never "doc staleness"**, and may not be
  downgraded without evidence that the command executes.

## [0.53.0] - 2026-08-10

### Added
- **`methodology-status` and `audit` now report which quality controls are actually on.** Every
  diagnosed safeguard ships as an adapter opt-in defaulting to off or warn, and a control that is
  off, absent or self-disabled printed *nothing* — silence that is indistinguishable from healthy.
  A lane could therefore carry every go-live gate in schema form while enforcing none of them.
  `methodology-status` now prints one `control_posture:` line summarising every control by state
  (`block`/`warn`/`off`/`empty`/`unreachable`) with a `drift=` list, and `tautline audit` prints
  the full table in both its findings and its clean branch. Three states are computed rather than
  read off an `enforcement` string, because that string lies: a `ciTestGate` with `enabled: false`
  or a taken `expectTests` self-disable never runs whatever it claims to enforce; the
  detection-baseline gate keys on `readiness.enforcement`, not on the `readiness.sources` file
  list; and a binding preflight that cannot exercise the declared primary user surface is its own
  row rather than a footnote on `uiEvidence`.

### Changed
- **`methodology-status --posture`** prints one `control_posture_warn:` line per drifting control
  with the reason. It is behind a flag because `methodology-status` is the surface an agent reads
  first, and the summary line is the whole default cost. Posture is diagnostic in this release: no
  posture row enters any failure list at any flag combination, including `--strict` and
  `--fail-on-drift`, and no exit code changes.

## [0.52.0] - 2026-08-10

### Added
- **Review findings are routed by acceptance-criteria traceability, not by severity alone.** The
  Done gate is AC-scoped and routing was severity-scoped, so a Critical *not* open against the
  item's acceptance criteria was neither blocking nor routable. Classified findings now carry
  `ac_ref` (the criterion violated, or `null` when out of scope), `disposition`
  (`fixed`/`routed`/`refuted`) and `routed_to`, and `finalize-implementation-review` enforces them
  on a push-eligible verdict. A finding open against a criterion is fixed or refuted regardless of
  severity -- never routed, never downgraded to make routing legal.
- **A deferred Critical/P1 carries its reason and its criterion.** `status: "deferred"` was the
  cheapest escape on the record; a Critical/P1-origin deferral now requires `deferral_rationale`
  (>=12 characters) and `acceptance_criterion` on both the plan-review and implementation-review
  paths. `--verdict clean-with-deferrals` requires `--classified-findings-json` with at least one
  finding, so the rule cannot be bypassed by omitting an optional flag. A deferred P2 owes nothing.
- `review-evidence-check --strict` runs the whole contract over **both** recorded copies — the
  manifest and the tracked `.impl-reviews/` ledger, compared field-for-field — so evidence edited
  after finalize cannot pass. Non-strict warns. `methodology-status` prints one `critical_deferral:` line
  per recorded Critical/P1-origin deferral -- a ledger surface, never a gate.
- One documentation surface for the whole contract at
  `docs/reference/operations/cli-operations.md`, cited by every refusal, with the flag's
  path-vs-inline difference between the two verbs stated explicitly.

### Changed
- Canonical rules, policy 17 and the `review-before-push` skill now state routing in terms of
  acceptance-criteria traceability at honest severity. "No unresolved Critical/Important ships"
  reads "unresolved **against the acceptance criteria**".
- `--verdict blocked` requires none of the above and never runs the log cross-check. Recording what
  review actually found stays the cheapest verdict there is.

## [0.51.0] - 2026-08-10

### Added
- On a hook boundary only, an adapter-schema refusal that is **provably** version skew now reports
  and continues instead of refusing the push. Provable means one thing: the adapter sits inside a
  framework checkout whose own schema is a different file and accepts the adapter. That is the only
  signal that consults a schema which actually declares the key.
- The refusal that previously named no remedy at all now says something. Where the skew is provable
  the remedy's reinstall is **qualified to the authoritative checkout** rather than routed through
  `PATH` -- which may still resolve the stale install that produced the report. Where the only
  signal is a newer generator stamp, which cannot distinguish a new key from a misspelling, it
  emits a labelled **hint** naming both branches and promising neither.

### Changed
- The generated hooks export `TAUTLINE_HOOK_BOUNDARY`, and unset it before invoking a wrapped
  backup hook on both branches so a custom hook cannot inherit downgrade semantics outside the gate
  chain that earns them.

### Fixed
- Nothing about `additionalProperties: false`, which is unchanged. A misspelled key still refuses,
  and so does a lane whose only signal is a newer generator stamp. `validate-adapter` stays the
  strict oracle everywhere.

## [0.50.0] - 2026-08-09

### Added

- **`behavior-spec-delta-check`: the owner/un-pend rule now sits at the boundary where the debt is
  created.** 0.47.0 gave the rule one definition and published its form, but left it reachable only
  from `codex-run`'s evidence path and the repo-wide status report — a commit crossing neither
  landed metadata-less `@pending` scenarios silently, which is how one adopter's debt reached 268
  scenarios before a repo-wide gate detonated on an unrelated PR. The new verb reads the staged
  tree and exits 1 when a scenario the change *introduces* lacks owner or un-pend metadata.
- Pre-existing debt never blocks. "Introduced" is decided by **comparing the inactive scenarios in
  the staged tree against those at `HEAD`**, not by intersecting line ranges — a proxy that was
  wrong in both directions: a deletion above an untouched scenario made it look introduced, and a
  feature-level `@pending` made a file's worth of newly inactive scenarios look untouched. A file
  renamed between two in-scope paths keeps its history; one renamed in from outside scope brings
  its debt to the gate for the first time.
- The check is **fail-open**: any git failure warns and reports `unknown`, never `0`, so a check
  that could not look never reads as a clean one. An unreadable `HEAD` reports `unknown` too,
  rather than treating "no prior debt" as proven and refusing the commit. No boundary is wired to
  the verb in this release — it ships callable by hand, so nothing changes for adopters on upgrade.

- If the adapter differs between the worktree and the index, the check **refuses to answer** and
  reports `unknown`. Policy and scenarios have to come from the same revision: an adapter edited
  but not staged would otherwise set the rules for a tree it is not part of, and flipping
  `pendingRequiresOwnerAndTrigger` to false in the worktree alone would silence an enforcing staged
  adapter without that change ever being committed.

### Fixed

- **`codex-run`'s diff scoping did not decode git-quoted paths.** Its hunk parser was a second copy
  of the same logic and had drifted: under the default `core.quotePath` a non-ASCII path was stored
  under its escaped name, which never matched the real filename, so an unannotated scenario added
  in a file like `é.feature` was invisible while the gate reported success. Both parsers are now
  one, and rename detection is pinned on at the invocation rather than left to `diff.renames`.

### Known gaps

- **`codex-run` still does not see debt introduced by *deletion*.** Removing an `@owner:` line adds
  no lines, so the `+N,0` hunk carries no range and the push-boundary gate reads the
  now-noncompliant scenario as pre-existing debt. A base-vs-tip scenario comparison sees it; that
  comparison was wired into `codex-run` during this release and then taken back out, because four
  review rounds each found a fresh **false refusal** in it — and this is a blocking push gate,
  where refusing correct work is the expensive failure. It returns once scenario identity across
  revisions is settled. `behavior-spec-delta-check` catches the case today, wired to no boundary.
- The verb's own identity handling has known rough edges deferred with it: duplicate scenarios of
  the same name are paired by line order, which mis-pairs when their cardinality changes; a move
  that also rewrites a file below git's rename-similarity threshold loses its history; and a
  literal-Unicode path inside C quotes (possible with `core.quotePath=false`) is not decoded
  faithfully. Each can produce a false refusal from the verb — which is why it is wired to no
  boundary in this release.

## [0.49.0] - 2026-08-09

### Fixed
- The generated `pre-commit`/`pre-push` hooks now probe the lane's own checkout for a CLI first,
  then `TAUTLINE_METHODOLOGY_REPO` and `MINERVIT_METHODOLOGY_REPO`, and only then the baked
  install path. Probing the baked path first made the environment branches unreachable whenever
  that path existed and was executable, so a release that ADDS an adapter-schema key could not be
  pushed from such a machine: the hook validated the new adapter against the old install's schema,
  the closed schema refused it, and the only way out was `--no-verify` on a release boundary. A
  repository shipping both the framework engine and the adapter schema is the authority on its own
  schema. `additionalProperties: false` is unchanged, and a misspelled key still refuses.
- The resolver is now evaluated once per hook run rather than once per gate.

### Changed
- The resolution order is pinned by a new `HOOK_CLI_RESOLUTION_ORDER` constant and asserted
  label-for-label against the emitted template for both hook names.

**Reach:** this fix arrives on a machine only when `lane-start` or `install-hooks` rewrites the hook
there. The drift substrings are unchanged, so no gate reports an existing hook as stale; until the
rewrite that machine keeps its pre-upgrade behaviour, which is a hard refusal and never a silent
pass. Update the install BEFORE reinstalling — see the migration report.

## [0.47.1] - 2026-08-09

### Fixed
- Behavior-spec path scoping: a pattern whose last segment is `**` names the directories to
  descend into, not files. `features/*/**` therefore no longer selects `features/a.feature`
  directly -- measured against `Path.glob`, which returns only directories for such a pattern and
  lets `behavior_feature_files` rglob beneath them. The predicate had widened scope for these
  patterns, which is the worse drift direction for a gate.

## [0.47.0] - 2026-08-09

### Changed
- The owner + un-pend rule for inactive (`@pending`) behavior scenarios now has ONE definition,
  `behavior_pending_missing_metadata`, in `core.runtime`. It previously existed only as inline
  string checks duplicated between `behavior-spec-status` and the `codex-run` review block --
  two copies of a rule that was never written down anywhere an author could read it.
- Policy 15 now SHOWS the machine-checkable form,
  `@pending @owner:<goal-or-lane> @reason:<why> @unpend:<trigger>`, instead of only naming the
  three things it requires. The form is a strict
  subset of the legacy prose tokens, so adopting it breaks no existing annotation and no existing
  annotation breaks under it.
- Behavior-spec path scoping is now segment-aware and shared between globbing and predicate
  matching, so the two cannot drift. The previous `fnmatch`-based approach would have treated `/`
  as an ordinary character, matching `x/a.feature` against `*.feature` and failing to match a
  root-level `a.feature` against `**/*.feature`.

## [0.46.0] - 2026-08-09

### Changed

- **A GitHub Project board read is now verifiably complete, or it refuses.** One page was fetched
  and the payload's `totalCount` discarded, so "not in the first page" and "not on the board" were
  indistinguishable — `goal-start` refused an item that was present. A short read escalates; a
  still-short read fails closed with `truncated at N of M` rather than anything an agent could read
  as absence. A miss over a complete read names how many items were actually searched.
- Scoped reads (`backlogProvider.scopeQuery`) distrust `totalCount` in both directions — never to
  clear a read, never to accuse one, and never as a retry bound — because gh may report the
  project-wide total while `--query` filters the items it returns.

## [0.45.1] - 2026-08-09

### Added

- **Session↔worktree occupancy primitives** (`tautline_methodology.occupancy`): lease identity,
  liveness, foreignness, and atomic acquire/release for the record that answers "which SESSION
  holds this worktree" — the sibling of the fleet lease, which answers "which WORKTREE holds these
  paths". Two sessions inside one checkout resolve to the same fleet holder and pass unchallenged;
  that is the mechanism behind two recorded incidents, one of which swept a peer session's staged
  files into a foreign commit. Identity resolves to the **agent session process** from a measured
  runtime variable or not at all — never the CLI invocation, its shell, or the POSIX session
  leader that two agents in one terminal share. Exclusivity rests on one rule: without a real
  kernel lock, only a publish into an empty slot is permitted, and mutating an existing record
  requires the lock. Every predicate is total over hostile file data: a malformed lease is stale,
  never a blocker and never an exception. Internal only at this release — no CLI verb, no adapter
  key, no hook content, no refusal.

## [0.45.0] - 2026-08-09

### Changed

- **The refusal-continuation machinery moved to a shared test module.** The runnable-command check
  and the allowlist-with-reason discipline now live in `tests/refusal_continuations_common.py`, so
  a second refusal surface can apply the SAME check instead of a drifting copy. Refactor only: the
  review-surface suite's checks, prefixes and allowlist entries are unchanged, and its run output
  is byte-identical before and after.

## [0.44.0] - 2026-08-09

### Added

- **`codex-run` refuses a review round whose only dirty files are the generated adapters.** The
  review wrapper flips to `--uncommitted` on any dirty tree, so a tool-injected re-render would
  become the round's subject and spend its whole budget. Mixed dirt warns instead of refusing;
  `--allow-adapter-dirt` reviews the adapters deliberately. A hand-written `CLAUDE.md`/`AGENTS.md`
  is the lane's own work and never counts as adapter dirt. The refusal's discard commands are
  derived from what git distinguishes — in HEAD, staged-add, untracked — so following them
  actually clears the dirt.

## [0.43.1] - 2026-08-09

### Fixed

- **Four package modules were missing from the release artifact registry** and are now
  registered: `core/runtime.py` — which the W1 carve moved 391 symbols into at 0.41.0 —
  `goal_assignment.py`, `merge_gate.py`, and `test_evidence.py`. That list is what `cut-release`
  checksums, so a missing module was omitted from the integrity record a verifier checks:
  manifests from releases before this one are **incomplete**, not merely different — they attest
  to a subset of what shipped. A new guard asserts the registry against the tree in both
  directions — every shipped module registered, every registered path present — so it cannot
  drift again; the list stays explicit rather than globbed, because a manifest built by walking
  the filesystem would checksum whatever happened to be lying in the tree.

## [0.43.0] - 2026-08-09

### Added

- **Generated adapters record the template that rendered them.** `CLAUDE.md` and `AGENTS.md` now
  carry a `tautline-template-version` comment on line 2 (line 1 is unchanged, so every existing
  runtime still recognizes them). A render whose on-disk files were produced by a **newer**
  template no longer silently rolls them back: `lane-start` narrates and skips the file, and
  `render-adapters --write` exits 1 with the repin remedy plus a `--allow-template-downgrade`
  override for a deliberate one. The stamp is identity, not content — a stamp-only difference is
  never drift and never a rewrite, so a release bump does not re-dirty every lane.
- **Renders name themselves.** Both render paths print `adapter_render_trigger:` and record an
  `adapter_render` event carrying the trigger, pid, argv0, cwd and runtime version — enough to
  tell two concurrent sibling-worktree sessions apart. Refused downgrades record
  `adapter_render_refused` with the on-disk stamp.

### Changed

- `lane-start` and `render-adapters --write` no longer rewrite a generated Markdown file whose
  content is unchanged. Previously every lane-start rewrote both files unconditionally.

### Notes

- This closes render skew only **between runtimes at or after 0.43.0**. A machine still pinned
  below it can perform the same silent downgrade; the fleet repin is the control for that
  population. See the 0.43.0 migration report.

## [0.42.0] - 2026-08-03

### Added

- **W2 enablement for the monolith split** (`tools/carve/`): `plan_core.plan()` gains a
  `restrict` parameter that derives the largest provably-safe SUBSET of a verb family under the
  full gate ladder, and `apply.py` gains alias-aware importability — an eager re-export left by
  an earlier carve (`X = _core_runtime_mod.X`) now counts as importable directly from its carved
  module, so later waves can move symbols that call already-carved helpers (proven end-to-end by
  a two-stage carve test). Maintainer tooling only; no shipped surface changes. Measurement at
  this base, recorded in `tools/carve/HANDOFF.md`: zero W2 family lanes pass clean today — every
  release/public family member reaches unmovable monolith state — so the next carve waves start
  from a regenerated plan rather than a family assumption.

## [0.41.0] - 2026-08-03

### Changed

- **W1 core extraction (cli.py monolith split, wave 1)**: 391 shared-core symbols (4,858 LOC)
  relocated byte-identically from `cli.py` into `tautline_methodology.core.runtime` by the 0.40.0
  carve tooling, driven by the first committed batch (`carve/batches/core.json`, a derived
  artifact reproducible from the base commit). Eager guarded aliases at the deletion site keep
  `cli.<name>` attribute reach, every in-repo call site, the suite's monkeypatch seams, and the
  hook fail-open contract working unchanged — zero behaviour change by construction, proven by
  the full gate on the carved tree. Internal refactor only: no adapter key, no CLI surface, no
  policy change reaches an adopter.

## [0.40.0] - 2026-08-03

### Added

- **Carve tooling for the `cli.py` monolith split** (`tools/carve/`): a tested, manifest-driven
  tool that relocates top-level symbols out of the CLI monolith by byte-slice, so a batch's diff
  is a pure function of (base commit, batch) and parallel lanes recompute instead of merging.
  Maintainer/dev-repo tooling only — no shipped CLI surface changes. The tool refuses, rather
  than miscompiles, every analysed hazard class: origin back-edges, module-scope consumers on the
  fail-open path, per-load mutable or environment-derived state (including function defaults),
  test-suite monkeypatch seams, relative imports, module-introspecting bodies, multi-name binding
  statements, the `_MissingFrameworkPackage` binding floor, import-order displacement past
  effectful survivors, and broken-versus-absent destination packages. `tools/carve/analyze.py`
  derives the split plan from the reference graph; `tools/carve/plan_core.py` emits the largest
  provably safe shared-core batch.

### Fixed

- **`scripts/test.sh` xdist probe on Python 3.13+**: the gate's pytest-xdist detection matched on
  `-n numprocesses` help text that 3.13-era pytest no longer prints; it now matches on
  `--numprocesses`, so the fail-closed test gate works on every supported interpreter again.
- **`cli.py` F541 hygiene**: the seven placeholder-free f-strings were de-prefixed (byte-identical
  string values) and `F541` was deleted from the per-file lint baseline — required so the first
  carved batch, which relocates one of those strings, lands in a destination file the frozen lint
  gate accepts.

## [0.39.2] - 2026-08-02

### Changed

- **`renderer-ci` and `npm-audit` now run on local hardware.** Both select their runner through
  `CI_RUNNER_LABEL` and assert, immediately after checkout, that the job actually landed there —
  reusing the `assert-runner-identity` action from 0.38.1. Eight locally-routed jobs across five
  workflows now carry the assertion. These were the last two workflows that actually billed on this
  repository.

  This supersedes 0.38.1's recommendation to leave them hosted, which rested on there being no bill
  worth saving. The operator instruction of 2026-08-02 is categorical, not a cost threshold.

  Unchanged deliberately: `publish-pypi` and `publish-npm` stay hosted, because a release must never
  depend on whether a laptop is awake; `release-drift-check` is gated to the public mirror and never
  runs here.

  **The trade this accepts:** both run `npm ci`, which executes dependency lifecycle scripts. The
  container protects the host, so this is not host-user execution — but jobs are not isolated from
  each other, and the machine is on the operator's LAN.

- **This does not achieve zero billed hosted runs, and does not claim to.** Scheduled and `push`
  triggers resolve from the **default branch**, and `main` predates `CI_RUNNER_LABEL` routing
  entirely, so its copies stay hardcoded `ubuntu-latest` until a release promotion:

  | Resolves from `main` until promotion | Detail |
  | --- | --- |
  | `ci-python` (3 jobs), `validate` | hardcoded hosted, **no path filter** on `pull_request` |
  | `npm-audit` `push` → `main` | **no path filter** — every push to `main` |
  | `npm-audit` weekly cron | `0 6 * * 1`, ~1–2 min |
  | `renderer-ci` main-path push, manual dispatch | path-filtered / manual |

  0.39.1 disabling Dependabot removed the largest *automatic* driver of that residual: security
  updates ignored `target-branch` and opened against `main`, where one PR could trigger six hosted
  jobs including the full Python suite. With Dependabot off, what remains is human PRs to `main`,
  pushes to `main`, and the weekly cron. **Promoting `main` closes the rest.**

- The `assert-runner-identity` header, both moved workflows' comments, and the runner README now
  state one consistent model: the canonical-repo check is a **routing guard, not fork containment**.
  On `pull_request`, `github.repository` is the base repository, so a fork PR passes it and routes
  to the self-hosted runner. Containment rests on the repository being private — a precondition,
  not a property — and making it public requires a fork guard on every `pull_request`-triggered
  self-hosted job first.

## [0.39.1] - 2026-08-02

### Changed

- Dependabot is disabled in this repository by operator decision: an automated vector that pushes
  dependency changes into the product without the operator's approval is not wanted for now. The
  config is renamed to `.github/dependabot.yml.disabled` rather than deleted, so it and its caveats
  survive; renaming it back is the whole re-enable.
- The trade is written into the disabled file rather than left implicit: no automatic notice when a
  dependency ships a security fix, and pins drift silently. `npm-audit.yml` still reports known npm
  advisories, so the JS side keeps a watcher; pip and github-actions have none while this is off.
- No adopter-visible change: `.github/dependabot.yml` is excluded from the public release export, so
  no adopter tree ever contained it.

## [0.39.0] - 2026-08-02

### Added

- `tautline merge` refuses a merge whose resulting commit subject names a version the PR head does
  not ship. A squash takes its subject from the PR title, which goes stale whenever a branch is
  renumbered — and the resulting commit cannot be corrected once published, so this is checked at
  the last point where the subject is both knowable and still editable. Fix the title (or the
  `--subject`) and re-run.
- A test asserting that every commit touching `VERSION` whose subject carries a version token names
  the version it actually ships. Two published commits that violate it are pinned in a frozen
  allowlist that may only shrink; they are on every clone and cannot be corrected.

### Changed

- The subject check reads `--subject` when supplied and the PR title otherwise, because
  `gh pr merge --subject/-t` overrides the title outright. It is skipped for an explicit
  `--merge`/`--rebase`, whose subject does not come from the title, but **not** for a bare merge:
  with no strategy flag the effective strategy is the repository's default, which the command
  cannot read, so the ambiguous case is checked.
- `VERSION` is read from the repository owning the PR **head**, so the guard still runs on a fork
  PR. When it cannot be read the merge proceeds with an explicit notice that the subject was *not*
  verified — an unreadable check must never become a lockout.

## [0.38.3] - 2026-08-02

### Added

- **Three shipped releases were in no changelog at all, and nothing could tell.** 0.6.266, 0.6.267
  and 0.6.268 each shipped a migration report and appeared in neither this file (which starts at
  0.7.0) nor the pre-launch archive (which stopped at 0.6.265) — three releases with no
  reader-facing record anywhere. It hid behind this file's own boundary sentence, "Pre-launch
  history through 0.6.265": true of the *archive's* coverage, and so it read as intentional rather
  than as a description of a hole. The three entries are reconstructed from their own migration
  reports, every file they name verified to exist, and their dates are bracketed rather than
  guessed — 0.6.265 and 0.7.0 are both 2026-07-08.

- **The durable part is the test, and it immediately found the gap is 24 versions, not 3.** Every
  migration report must now have an entry in one of the two changelogs. The archive also skips
  0.6.123–0.6.126, 0.6.128 and 0.6.160–0.6.175. Those 21 are **not** fixed here and are not
  deferred by preference: their content is recoverable from the migration reports, but the archive
  is dated per entry and those dates exist only in the private pre-launch repository. Inventing 21
  dates to turn a check green would put fabricated history into the release record. They are
  enumerated in `KNOWN_PRELAUNCH_CHANGELOG_GAP`, and the test asserts that list may only **shrink**
  — so a newly cut release that forgets its changelog section fails immediately, and every
  backfilled entry must delete its own line.

## [0.38.2] - 2026-08-02

### Changed

- **A diff that ships nothing no longer owes a release.** Two of this repository's own gates
  contradicted each other, and a docs-only planning PR sat on the contradiction for eleven days:
  `review-evidence-check` refuses a push until the tracked
  `docs/superpowers/plans/.impl-reviews/` ledger is **committed**, and the version-bump contract
  then counted that same commit as a framework change owing a full release — version bump,
  changelog section, migration report, nine version surfaces. One gate demanded the file; the
  other charged a release for it. The only exits were burning a version number on a planning
  document or bypassing a gate with `--no-verify`.

  The release-change contract now exempts paths under `docs/superpowers/` — plans, specs, and
  review ledgers. The exemption is provable rather than a judgement call: that prefix is already
  in `PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES`, so nothing under it has ever reached an adopter.
  The test keys on that constant instead of copying the string, so if the export ever starts
  shipping plans, the exemption's justification fails loudly rather than silently widening over
  consumer-visible surface.

  It stays **per-path**, like every other rule in that contract: a diff mixing a plan with real
  code still owes its release. Only a docs-only push is exempt. The test-only half of the same
  backlog item (`tests/**`) is deliberately not taken here — tests *do* ship in the public export,
  so that case needs its own argument rather than riding this one.

## [0.38.1] - 2026-08-01

### Added

- **The hosted-runner fallback can no longer be taken silently.** `runs-on: ${{ vars.CI_RUNNER_LABEL
  || 'ubuntu-latest' }}` failed *open*: clear the repo variable and all six locally-routed jobs move
  back to billed GitHub compute while still reporting green — the exact regression the self-hosted
  move existed to end, with no signal that anything changed. A new
  `.github/actions/assert-runner-identity` composite action runs immediately after checkout in
  `validate`, both `ci-python` jobs, and all three `ci-python-full` jobs, and fails the run when an
  unset `CI_RUNNER_LABEL` means the local runner was silently lost.

  Both behaviours that legitimately depend on the fallback survive. **Forks** still fall back
  quietly — hosted is the only compute they have — via a case-insensitive canonical-repo check.
  The **runner-down escape hatch** still works, now taken deliberately with
  `CI_ALLOW_HOSTED_FALLBACK=1` instead of by silence; affected jobs then pass with a `::warning` on
  every run, so an open hatch stays visible rather than turning up on an invoice.

  It deliberately does **not** claim to detect an offline, deregistered, or typoed runner label:
  GitHub queues those jobs rather than falling back, so no step runs and no runtime check can see
  it. That case has its own signal — nothing merges.

  Maintainer-repo only. No adapter key, no CLI surface, no policy change; adopter lanes are
  untouched in either direction.

### Changed

- The workflow SHA-pin guard exempts same-repo `./` action references — keyed on the `./` prefix
  rather than on the absence of an `@pin`, which would have re-admitted an unpinned
  `actions/checkout` — and now also covers `ci-python-full.yml`, which had been declared and then
  left out of the only supply-chain check in the suite.

## [0.38.0] - 2026-08-01

### Added

- **"The tests passed" stops being a sentence anyone can type.** 0.28.0 made a test run produce a
  tamper-evident receipt (`tautline-test-run/v1`). Nothing read it — `classify_test_run_evidence`
  computed `red` and its only consumer in the whole codebase was a `print`. Two boundaries now read
  it: `guard-check --boundary prepush` gains a fourth check, and `finalize-implementation-review`
  refuses a push-eligible verdict without it.

  New adapter key `testEvidence.enforcement` (`off|warn|block`). **Absent means `block`** — an
  operator decision, overriding this item's own plan, whose default was `warn`. A warn default
  makes the control opt-in, and an opt-in control does not fix a recurring failure.

  Refused under `block`: a record that is missing, invalid, stale, red, **exit-code-only**, or that
  proves no test executed — **zero collected, or every test skipped**. That last pair is the real
  bypass: point a suite at a glob matching no files and it produces a structurally valid report
  that turns every gate green. Skipped tests are not evidence.

  The **report outranks the exit code**: a `pytest … || true` command swallows the process status
  while the report still records the failures.

  `unavailable` — a classifier internal error — **fails open in every mode, including `block`**,
  per the 2026-07-22 startup-gate lockout precedent. A control that cannot tell must not stop the
  lane. Recording a `blocked` verdict likewise never requires evidence: that verdict is how a lane
  honestly reports that review found something, and gating it would make the truthful verdict the
  hardest one to record.

  Every refusal prints its remedy — the command that produces evidence, the report declaration that
  makes counts parse, and the deliberate downgrade *including the re-render*, since a source-adapter
  edit is inert until rendered. Downstream projects mostly land in `missing`, not `red`, and a
  project blocked with no way out teaches its operator `--no-verify`, which removes every gate
  rather than just this one.

  **Five defects in this release's own classifier, found by consecutive review rounds and fixed
  here rather than shipped.** The record declares the digest exclusions it was measured under and
  the classifier re-applies them — deliberately, so widening the defaults never reclassifies an old
  record. The cost is that the record names its own comparison basis: an entry of `.`, or git
  pathspec magic like `:(top)`, excluded the whole worktree, making the recorded digest the
  empty-tree hash that the classifier then recomputed to the same value for *any* tree. An
  option-shaped entry such as `--bad-option` was parsed by git as a **flag**, exiting non-zero into
  `unavailable`, which fails open by design. Exclusions are now an allowlist over what the writer
  emits, passed after `--` and as `:(literal)` pathspecs so neither flags nor globs are
  interpreted — while a legal filename like `report[1].xml` is still accepted.

  A record whose `git` block was a string rather than an object raised into that same fail-open
  catch; it now classifies `invalid`. In the other direction, a record **store** that cannot be
  listed is a checker outage (`unavailable`, fails open) rather than absent evidence, and pytest's
  `xfailed`/`xpassed`/`deselected` outcomes are mapped into the count buckets — a green suite using
  expected-failure markers could not push. `finalize-implementation-review` also refuses a record
  whose exclusions predate the ledger path instead of accepting it and leaving the push blocked one
  line later, gated on `enforcement=block` so `warn`/`off` keep their non-blocking contract.

## [0.37.0] - 2026-08-01

### Changed

- **Implementation review got the round ladder plan review already had, and no round decision on
  that surface is an operator escalation any more.** `codex-run` carried two independent round
  refusals, and the budget one returned before the other could be reached — so
  `--allow-extra-rounds`, which is wired to the *other* gate (two finalized clean rounds, per its
  own `--help`), was unreachable on the budget path. The review-before-push policy nevertheless
  told lanes to use that flag for the confirming round it mandates on a remediated diff. Policy had
  assigned the flag a meaning it never had since 0.17.5, so the refusal was unconditional, its
  message said "escalate", and agents stopped to ask the operator a question with exactly one valid
  answer. On 2026-07-30 that stopped four development lanes overnight.

  Now: rounds up to the adapter budget are free, rounds up to **budget + 2** self-authorize with a
  recorded `--extra-round-reason`, and past that refusal is absolute and says so. Every refusal on
  the path carries a runnable continuation, and none of them can tell an agent to consult a human —
  pinned by `tests/test_codex_run_round_ladder.py`, which is also the first test in the suite to
  cover this refusal at all. That absence is why the defect survived fourteen releases.

- **A confirming round on an already-remediated diff is no longer charged.** Re-binding an owed
  verdict to a changed diff hash is not new inquiry, and charging it as a fresh round is what made
  any PR whose review found something twice unpushable without break-glass. `codex-run` now prints
  `codex_run_confirming_round:` when the exemption applies; the exemption is bounded by the hard cap
  and fails closed whenever it cannot prove the prior rounds were voided.

- **`review.roundBudgets` defaults re-shaped: `{T0:0, T1:1, T2:2, T3:2}` → `{T0:0, T1:2, T2:3,
  T3:4}`.** The old shape gave T3 — the highest risk tier — no more rounds than T2, and T1=1 made
  the mandated confirming round illegal on the first finding. With the ladder's +2 margin, T3's
  absolute ceiling is 6. Adapters that pin `review.roundBudgets` explicitly are unaffected; those
  relying on the default get the new values on update.

- **The review-before-push policy now describes the ladder that actually ships.** Policy had told
  lanes since 0.17.5 to take the owed confirming round with `--allow-extra-rounds` — a meaning that
  flag never had. The policy module and the `review-before-push` skill reference are reconciled
  against shipped behavior, and 0.17.5's migration record is left byte-identical on purpose (it is
  the record of what that release *claimed*); the correction is published here instead.

### Added

- **"No dead ends" is an enforced invariant on the review surface, not a principle.**
  `tests/test_refusal_continuations.py` walks `cli.py` for every refusal on the review/gate
  boundary and asserts three things: none may instruct an agent to escalate, ask, or wait for a
  person; a refusal that denies an action on *policy* grounds must name a runnable continuation;
  and any command a refusal names must actually exist with the flags it shows. Allowlists are keyed
  by message fragment (not line number) and every entry carries its reason in the test file — the
  goal is that each dead end is a deliberate, named decision, not that the count is zero. All three
  checks are mutation-verified against the defect they exist to catch.

### Fixed

- **Every dependabot PR touching a workflow file was red on arrival, permanently, with no compliant
  path.** `.github/workflows/*.yml` ships inside the public release export, so a pinned-action
  change there is consumer-visible and genuinely needs a VERSION bump — but a bot cannot bump
  `VERSION`, and the gate's failure message listed the changed files and named no way to satisfy
  it (PR #413, `actions/checkout` 4→7). The exemption is deliberately *not* widened; the message
  now names the maintainer commit that clears it, including the `gh pr checkout` path for a bot's
  branch. A gate with no compliant path is how a team learns to ignore red.

- **`record-plan-review` refused a Critical/P1 count mismatch without saying which side was
  wrong.** It now prints both the counts derived from the findings file and the counts passed, plus
  the exact corrected re-invocation.

## [0.36.1] - 2026-08-01

### Fixed

- **The runner operations docs said `ci-python-full` stays hosted; 0.36.0 had just moved it.** That
  file is what an operator reads when deciding where CI runs, so the split table, the "deliberately
  stays hosted" claim, and the paragraph naming the hosted run as *the backstop for when the machine
  is off* were all actively misleading. There is no hosted backstop any more — with the runner down,
  nothing CI-related runs anywhere, and the recovery is to unset `CI_RUNNER_LABEL`, which now returns
  all three CI workflows to `ubuntu-latest` together. `ci-python.yml`'s "deliberately NOT applied to
  ci-python-full" comment and its stale `3.10 + 3.12 matrix` phrasing are corrected too.

  Documentation and comments only — no workflow expression or code path changed.

## [0.36.0] - 2026-07-31

### Changed

- **The Python support floor moves 3.10 → 3.12, and the last GitHub-hosted workflow moves onto the
  self-hosted runner.** These are one change: keeping the 3.10 floor was the *only* thing forcing
  `ci-python-full` to stay hosted, because Ubuntu 24.04 ships only 3.12 and `setup-python`'s
  portable CPython cannot be used here — its `libpython` is not on the loader path and dies the
  moment a test spawns it as a subprocess (531 failures on the first self-hosted run).

  **Nothing in the tree ever required 3.10.** It parses clean under the 3.9 grammar, and the floor
  rested entirely on `zip(strict=)` (PEP 618), which exists in every version from 3.10 up. The
  floor was a support *promise*, not a dependency — and honouring it meant hand-building a second
  interpreter into the runner image to prove a version no adopter had been asked to stay on.
  Operator decision: adopters still on 3.10/3.11 upgrade.

  `ci-python-full`'s three jobs now use the same `CI_RUNNER_LABEL` selection as the per-PR
  workflows. **Unset still resolves to `ubuntu-latest`**, so a fork of the public release export is
  untouched and never queues against a runner it does not have.

  **Three things the floor raise would otherwise have broken, caught in review:** `ci-python-full`'s
  evidence job still downloaded `evidence-py-3.10` and read `legs/py-3.10/leg-status.txt` — an
  artifact no job uploads once the leg is gone — which would have failed that job on *every* run
  while both real jobs passed. The generated PyPI package still emitted `requires-python = ">=3.10"`
  and a `Requires Python 3.10+` README, so `pip`/`pipx` would have gone on installing the wheel onto
  the two interpreters this release drops; both now derive from `cli.PYTHON_FLOOR`, pinned to
  pyproject by test. And the 0.36.0 migration report had lost the `grant-gh-project-scopes`
  carry-forward that every report since 0.10.3 carries — the update engine reads only the latest
  report, so a lane jumping from pre-0.10.3 would have hit fail-closed board gates with no
  instruction explaining them.

  Two stale claims corrected while doing it: the workflow said match statements forced the floor
  (there is not one in the tree), and the matrix guard hardcoded `"3.10"` — it now **derives** the
  floor from `pyproject.toml`, so a future raise cannot leave it asserting a version nothing runs.

## [0.35.3] - 2026-07-30

### Changed

- **Per-PR CI moved onto a self-hosted runner, and superseded runs stopped being paid for.**
  Hosted Actions spend was projecting **~$137/mo** against a $70 ceiling, and a measurement over
  Jul 23–30 (283 billed jobs, per-job round-up, all Linux at $0.008/min) put **93% of it in two
  workflows**: `ci-python` ($23.42/wk) and `validate` ($6.53/wk). Both now select their runner via
  the `CI_RUNNER_LABEL` repo variable — **unset resolves to `ubuntu-latest`, so forks of the public
  release export are untouched**; set to a runner label, the job routes to that runner and costs
  nothing, because GitHub does not meter minutes for hardware it does not own. The same suite runs
  in **101s locally against 18m45s hosted**. Both workflows also cancel superseded PR runs, scoped
  to `pull_request` only so a push run composing the `evidence` artifact a gate consumes is never
  cancelled. `ci-python-full` and the publish workflows are deliberately unchanged and stay hosted,
  so the authoritative interpreter matrix and anything that ships a release never depend on a local
  machine being awake. New `.github/runner/` holds the containerized runner and its operations.

### Fixed

- **A GitHub runner registration token could be left behind in the host's shared `/tmp`.**
  `.github/runner/runner.sh` removed the temp token file only after a successful `docker cp`, so
  an interrupted or failed copy left a world-readable bearer token for the rest of its ~1h life,
  enough for another local user to enrol a runner reporting checks for this repo. Cleanup is now
  a trap armed before the token is written, covering the failure and Ctrl-C paths.

## [0.35.2] - 2026-07-30

### Changed

- **Two test suites were re-doing identical work once per parametrized case.** Measured by file,
  `test_package_split_wave.py` was **431.8s — 20.7% of the whole suite**, because a pin
  parametrized over ~300 moved names re-read and re-parsed the 2.6MB CLI engine *per parameter*.
  Reads and parses are now cached per worker: **431.8s → 12.4s**. Together with the cubic
  registrar-carve pin, a same-machine A/B at CI's parallelism (`-n 2`) measures the suite at
  **488.6s → 312.7s (36% faster)**, with user CPU time halving from 681s to 336s — confirming work
  removed rather than merely rebalanced. Both rewrites keep their assertions and were proven
  non-vacuous by mutation.

- **The suite's slowest test was accidentally cubic: 35.56s → 0.85s.** Measured before touching
  anything: `ruff` is 0.05s and *cold* `mypy` 2.0s, so essentially all 994 of the CI Python leg's
  1019 seconds is pytest — and `--durations` showed one test at 35.56s against 10.73s for the next.
  For each of ~190 `add_parser` calls it walked the entire 52k-line module AST, then re-walked each
  candidate function's subtree. Rewritten as one pass. The assertion is unchanged, and was proven
  non-vacuous by planting a stray `add_parser` in `main()` and confirming it still fails. On an
  xdist worker a single 35s test is a floor no other worker can lower, so the gain is largest where
  the worker count is smallest — CI.

## [0.35.1] - 2026-07-30

### Fixed

- **`tautline merge <pr> -- <gh flags>` now applies those flags.** The `--` separator was stripped
  only when it came *first*, so after an explicit PR reference it reached `gh` — which stops option
  parsing at `--` and read `--squash` as a positional, merging with the default strategy instead of
  the requested one. That shape is the one the verb's own refusal text suggests.
- **A caller-supplied `--match-head-commit` is refused rather than honoured.** It suppressed the
  pin the gate had just verified and forwarded the caller's SHA instead — an override of the
  race protection recording no reason, while every other override in this verb (`--override`,
  `--admin`) records a decision. It now joins `--repo` / `-R` / `--admin` as a refused passthrough
  flag, and the verified head is passed unconditionally.
- **A green suite could be recorded as "the command did not write its report", and the faster the
  machine the more often.** `tautline test-run` proved a declared report belonged to the run by
  requiring its mtime to be at or after the run's start reading — but those two timestamps come
  from different clocks. File timestamps come from the kernel's coarse-grained clock, refreshed
  once per timer tick, so a report written immediately after the run started could carry an mtime
  *earlier* than the start reading: **188 of 200 trials** on a local runner. Every one produced
  `predates this run`, dropped the counts, and **synthesised exit code 1 out of a passing suite**.
  The floor now carries a documented tolerance for that skew.
- **A run whose command wrote no report at all could inherit the previous run's counts.** The
  stable report path is reused between runs, so a command that exited 0 without writing its
  declared report left the last run's file sitting there — and any mtime slack wide enough to
  survive clock skew is also wide enough for back-to-back runs to land inside. `test-run` now
  clears the declared report *before* the command runs, in place exactly as it already did for
  fresh-checkout mode, so absence afterwards is the proof; the record store's own copy of every
  accepted report is untouched. A clear that *fails* is recorded as its own error rather than
  falling through to the mtime floor, which is wider than the gap between two consecutive runs.
- **The "most recent goal plan" could be whichever plan sorted last by filename.** Plans written
  within one timer tick share an mtime (98 of 100 consecutive writes), and a fresh clone stamps
  *every* plan with the single checkout time — so ties were the normal case, not the exotic one.
  Sorting `(mtime, name)` in reverse resolved those ties reverse-alphabetically, silently making
  the last name in the directory "the newest plan". Ordering is now newest-first with ties broken
  ascending by name.

## [0.35.0] - 2026-07-30

### Added

- **`tautline merge` — the gate starts refusing.** The verb consuming 0.34.0's kernel. It reads
  the PR's live `statusCheckRollup`, refuses on a failing check (or, by default, one that has not
  reported yet), then merges via `gh`. **Tautline's own adapter is armed to `block`**: on a repo
  where `ci-health-check` reports `platform_required_checks: unavailable`, this is the only thing
  standing between a red commit and `experimental`.
  - The PR is an explicit **argument**, or the current branch's PR — never parsed out of a command
    string. With no PR reference, separate gh flags with `--`; the separator is consumed rather
    than forwarded, since gh would otherwise stop option parsing and read `--squash` as a
    positional.
  - **Target-changing flags are refused, not forwarded** (`--repo`, `-R`, `--admin`, in every
    spelling `gh` accepts). Forwarded, they let the gate verify one PR and merge another.
  - **A PR URL reveals its own repo**, so the cross-repo fail-closed rule fires for URL targets
    even without `--repo`.
  - **The verified head commit is pinned** with `--match-head-commit`, so a push landing between
    verification and merge cannot be merged on the old commit's checks.
  - Same-repo unverifiable **fails open with an explicit notice**; cross-repo **fails closed**.
    Routine `--admin` stays forbidden; `--override <reason>` records a hard-to-reverse decision
    **before** the merge.
- **`mergeGate` adapter knob** (`enforcement: off | advise | block`, `blockOnPending`), absent-safe
  and defaulting to `advise`.

### Fixed

- **Both kernel defects deferred from 0.34.0**, fixed here where the code first becomes reachable:
  pending now outranks unknown in *both* modes (matching the module's documented precedence), and
  wrapper flags taking non-numeric operands (`sudo -u build gh …`, `env -C /tmp gh …`,
  `timeout --signal TERM 30 gh …`) no longer hide a wrapped raw merge.

## [0.34.0] - 2026-07-30

### Added

- **The merge gate's verdict kernel** (`tautline_methodology.merge_gate`). Backlog item 21 option 3,
  selected by the operator on 2026-07-24. Branch protection is a paid feature for private
  repositories, so this repo cannot carry a required status check on *any* branch — PR #482 proved
  a deliberately failing commit stays `MERGEABLE` here. When the platform cannot enforce the gate,
  the methodology will. This release lands the pure decision logic on its own; the `tautline merge`
  verb that consumes it is the successor PR, so **nothing calls this yet and no behavior changes**.
  - `classify_merge_gate()` returns `block` / `allow` / `unverifiable` over a PR's
    `statusCheckRollup`. `STALE` blocks unconditionally — a stale run no longer corresponds to the
    head commit. Precedence is failure > pending > unknown, pinned in both directions. An
    unreadable rollup is `unverifiable`, never a block: a gate that blocks when it cannot see is a
    lockout.
  - `is_raw_pr_merge()` coarsely detects the `gh pr merge` command class — yes/no only, never a
    target or flag resolution. It steps over a wrapper *with its own flags and operands*
    (`sudo -E gh …`, `env -i X=1 gh …`, `timeout 30 gh …`) and recognises every spelling of gh's
    repo selector including attached values (`--repo=o/r`, `-Ro/r`), since a detector that misses
    a valid invocation is a bypass, not a nuisance.

## [0.33.1] - 2026-07-30

### Fixed

- **The recommended packaging-smoke dispatch names the branch it means.** `gh workflow run
  ci-python-full.yml` with no `--ref` dispatches on the *default* branch, so the pre-release smoke
  the 0.33.0 migration recommended would have covered `main` — the stable channel — instead of
  `experimental`. The CHANGELOG and the workflow comment already carried the correct form; the
  migration report did not, which is the worst place for the wrong one to live, because the other
  two make it look verified. A test now fails any recommended `gh workflow run` that omits `--ref`.
- **The 3.10 floor rationale no longer overstates its cadence.** `CONTRIBUTING.md`,
  `pyproject.toml` and the front-door doc contract test all pinned "CI proves the floor on 3.10
  every PR". As of 0.33.0 the 3.10 leg runs on every merge and on the daily schedule, not per PR.
  The floor is still genuinely proven — the pairing test fails closed if the full matrix stops
  covering what per-PR CI dropped — but a repo must not contract-test a false statement about its
  own gate.
- **Frozen migration reports are now guarded against retroactive edits.** Correcting the dispatch
  command inside the *0.33.0* branch would have made `release-migration-report --version 0.33.0
  --check` call its own archived report stale — an operator auditing an old release must get the
  bytes that release actually shipped. The fix lives in 0.33.1 only, and a new test re-generates
  every archived report and requires it to match, with the six pre-launch reports that had already
  drifted named individually rather than excluded by a version cutoff, so any *new* drift fails
  closed.

## [0.33.0] - 2026-07-30

### Changed

- **The heavyweight gates moved off the per-push path.** The blocking coverage ratchet and the
  fresh-install packaging smoke now run in `ci-python-full` — on every merge into `experimental`,
  plus the daily schedule and on demand — and the `validate`
  workflow no longer re-runs the whole suite — `scripts/validate.sh` is a frozen 5-line alias of
  `scripts/test.sh`, so that was a duplicate execution of the same tests against the same tree
  (~18 minutes of it, on every push). Together with 0.31.1 and 0.32.0, a push went from **four
  full-suite runs plus a fifth in `validate`** to **one**.
- **The validate-freeze whole-suite guarantee is intact.** `validate.sh` still invokes the entire
  suite, `tests/test_validate_freeze.py` still enforces that inside every `ci-python` run, and
  `ci-python-full` now invokes the suite *through the alias* daily, so the alias stays exercised
  end to end. `validate` also gained a fail-closed check that it still delegates to the real gate.
- **Coverage keeps its teeth, in a new place.** Same 24% floor, same blocking behavior, now on the
  full matrix. A new guard fails closed if the workflow carrying the ratchet ever stops firing —
  otherwise "we moved coverage off the PR path" and "we deleted the coverage gate" look identical
  from the repo. The gate runs on every merge, so it cannot go dark waiting for a schedule that a
  non-default branch never receives.
- **A scheduled packaging smoke tests the integration branch.** A scheduled run starts on the
  default branch, so the moved job's checkout is redirected at `experimental` the same way the
  matrix job's is — otherwise the daily smoke would build and install `main` and report green about
  a tree nobody develops on.
- **Honest cost of moving the packaging smoke:** a `pipx install` break is now caught within a day
  rather than at the PR that caused it, so the blast radius is every PR merged in between. It was
  only ~1 minute of compute, so this move is about keeping a release-shaped gate off the
  per-change path rather than about wall clock. It still runs on every merge into `experimental`,
  so the exposure is "merged but not yet integrated", not "a whole day". Dispatch `ci-python-full`
  (`gh workflow run ci-python-full.yml --ref experimental`) before a release, and before merging
  anything touching `pyproject.toml`, the registry-package tree, or hook payloads.

## [0.32.1] - 2026-07-30

### Fixed

- **An unverifiable platform probe no longer announces that nothing is protecting the branch.**
  `ci-health-check` appended its "no platform gate is blocking merges into `<branch>`; CI is
  advisory there" note for *every* non-armed state — including `unverifiable`, which means the
  probe could not run at all (`gh` missing, unauthenticated, offline, or a slug it cannot see).
  That contradicted the state line printed directly above it, and told an operator whose gate *is*
  armed that they were unprotected: the same overclaim the probe exists to prevent, pointed the
  other way. The note is now emitted only for `absent` and `unavailable`, where absence was
  positively established; `unverifiable` gets its own note stating the state is **unknown**, saying
  explicitly that this is not a report that no gate exists, and naming what would make it knowable.

## [0.32.0] - 2026-07-30

### Added

- **`ci-python-full`: the whole 3.10 + 3.12 matrix, off the per-PR path.** A new workflow that runs
  the full interpreter matrix with the blocking coverage ratchet. It exists so the per-PR trim
  below is not a coverage loss, and a test fails closed if it ever stops covering every interpreter
  per-PR CI dropped.
  - It fires on **every merge into `experimental`**, plus a daily 09:00 UTC schedule and
    `workflow_dispatch`. The push trigger is the load-bearing one: GitHub runs `schedule` **only
    from the repository's default branch**, which here is `main` — the stable channel, many minors
    behind. A schedule-only workflow declared on `experimental` would not have run at all until a
    release promotion carried the file to `main`, so the trim would have left the 3.10 floor
    covered by nothing while looking, from the repo, exactly like coverage. Verified against this
    repo's own `npm-audit` history, whose scheduled runs all report `headBranch=main`.
  - A scheduled run is dispatched from `main`, so its checkout is redirected at `experimental` —
    otherwise it would test the stable channel and report green about a tree nobody develops on.
- **`ci-health-check` now reports whether a platform gate is actually armed.** Wiring tests into CI
  and CI being *able to block a merge* are different properties, and this repo proves they come
  apart: branch protection is a paid feature for private repositories, so every branch here —
  including `main` — returns 403 and a green CI run gates nothing. The check prints
  `platform_required_checks: armed | absent | unavailable | unverifiable` and, when nothing is
  armed, says plainly that CI is advisory on that branch and that the local gates cannot stop a
  merge someone else performs. `unavailable` (the platform refuses) is deliberately distinct from
  `absent` (nobody configured it), and a probe that could not run reports `unverifiable` rather
  than claiming there is no gate — a bare `404` counts as *could not run*, because a token without
  access, a wrong slug and a deleted branch all read the same. **Both** ways of arming the gate are
  consulted: legacy branch protection *and* repository rulesets, since a ruleset-protected branch
  404s on the protection endpoint and would otherwise be reported as unguarded. **Report-only, permanently** — whether GitHub can gate a merge is
  not something a lane can fix, so failing on it would be a lockout with no remedy.

### Changed

- **Per-PR CI runs one Python leg (3.12) instead of two.** A second interpreter re-running the
  identical suite answers "is this change broken?" twice. The 3.10 floor is not abandoned — it
  moves to the daily `ci-python-full` matrix. Combined with 0.31.1's single covered pass, a push
  now runs the suite **once** where it used to run it four times.

## [0.31.1] - 2026-07-30

### Changed

- **CI runs the suite once per Python leg instead of twice.** `ci-python` ran the whole suite bare
  via `scripts/test.sh` and then a *second* full pass under `--cov`, for a coverage number that is
  measurably the same either way. The ratchet now rides on the single run through `PYTEST_ADDOPTS`
  (so the `pytest` line in `scripts/test.sh` stays bare and the validate-freeze whole-suite
  guarantee is intact) and the second pass is gone. Re-proved like-for-like *before* deleting
  anything: both shapes report **29845 statements, 12907 missed, TOTAL 56.75%** against the
  unchanged 24% floor, with the same 4301 tests passing. The gate is exactly as blocking folded in
  — `pytest` exits non-zero on `fail_under` and `scripts/test.sh` runs under `set -e`.

### Fixed

- **The per-leg JUnit evidence was being produced by the pass that was about to be deleted.**
  `scripts/test.sh` appends its own `--junitxml` last and pytest takes the last value, so the first
  pass's `PYTEST_ADDOPTS: --junitxml=evidence/pytest.junit.xml` had never written anything — only
  the coverage pass did. The report is now copied from the stable path `scripts/test.sh` actually
  writes, under `if: always()` so a red run still publishes its per-test detail. The workflow-shape
  test asserts that property instead of pinning the flag that silently did nothing.

## [0.31.0] - 2026-07-29

### Added

- **`tautline test-run --fresh-checkout` reproduces CI's checkout state locally.** The gate runs in
  a throwaway `git worktree` holding exactly what git can see — `HEAD`, plus your working-tree diff,
  plus untracked-but-not-ignored files — and nothing `.gitignore` covers. A test that reads
  gitignored runtime state (`.ai-runs/`, `.ai-work/`) passes on the authoring machine and fails on
  every fresh clone; one did, after **eight** local suite runs that were each structurally incapable
  of catching it, and it reddened all three CI jobs. Your real tree is never touched: the worktree
  is created outside the repo and removed afterwards, and the record, the output log and the tree
  digest still belong to the real project.
- **`testEvidence.freshCheckout` adapter knob.** `default` picks the lane's mode (`--fresh-checkout`
  / `--no-fresh-checkout` override it per run) and `carryPaths` names the gitignored dependency
  directories CI installs out-of-tree — `.venv`, `node_modules` — which are symlinked into the fresh
  tree so the configured gate can actually start. Absent stays absent: a lane that never declares it
  keeps running in place, so no existing adapter needs regenerating and no adopter has the mode
  turned on under them. Tautline's own adapter opts in.
- **The record says which mode ran.** A fresh run carries a `freshCheckout` block
  (`method`, `appliedWorkingTreeDiff`, `copiedUntracked`, `carriedPaths`), and the `lane-start` /
  pre-push evidence line reports `freshCheckout=yes|no`. In a lane that defaults to fresh, an
  in-place record is called out and the remedy names `--fresh-checkout` — `current` alone does not
  say which mode produced it.

### Changed

- **A fresh-checkout run that cannot be set up refuses; it never falls back to an in-place run.**
  The whole value of the mode is that its green means something an in-place green cannot, so a
  silent downgrade would hand back the weaker signal under the stronger label. `--no-fresh-checkout`
  is the deliberate, visible opt-out. Carrying a *tracked* path is likewise refused rather than
  quietly symlinked over.

## [0.30.2] - 2026-07-29

### Changed

- **The behavior gate runs in parallel: 955s → ~110s.** `pytest-xdist` is pinned into the dev
  toolchain and `scripts/test.sh` passes `-n auto` (via `PYTEST_ADDOPTS`, so the `pytest` line stays
  bare and the validate-freeze whole-suite guarantee is intact). Measured on a 28-core machine: the
  same 4277 tests, a junit report with identical `tests`/`failures`/`errors`/`skipped`, so
  `tautline test-run` records the same counts. Debug a single failure with
  `PYTEST_ADDOPTS='-n 0' scripts/test.sh`. CI parallelizes its coverage pass the same way —
  total coverage is unchanged at 56.58% against the 24% floor, so the blocking ratchet is unmoved.
- **The gate fails closed when `pytest-xdist` is absent**, naming the pinned-toolchain install. It
  never falls back to serial silently: a silent fallback would hide a ~16-minute regression that
  nobody would notice.

### Fixed

- **A latent flaky test that parallel execution exposed.** The tree-digest isolation test compared
  *every* file under `.git/objects`, including git's transient `maintenance.lock`, which background
  auto-maintenance writes and removes on its own schedule — so the comparison depended on git's
  timing rather than on what the digest wrote. It could flake at any concurrency. It now ignores
  `*.lock` and asserts on *added* objects rather than set equality, since git may legitimately
  repack its own files mid-test.

## [0.30.1] - 2026-07-29

### Fixed

- **A goal-assignment test depended on gitignored evidence, reddening CI.** The block-versus-`--raw`
  byte-equality test composed from a *finalized* repo plan, but finalization requires the plan-review
  log and run metadata under `.ai-runs/plan-review/`, which is gitignored — that evidence exists only
  on the machine that ran the review. The test therefore passed locally and failed on every fresh
  checkout, including all three CI jobs. The assertion is about the emitted block matching `--raw`,
  not about finalization, so it now passes `--allow-unfinalized` and depends on no untracked state.
  No runtime behavior changed.

## [0.30.0] - 2026-07-29

### Added

- **`goal-assignment`: the goal a finalized plan hands to a builder lane.** Between "planning is
  finalized" and "a builder lane picks up the work" sits a step nothing owned: the operator needs
  one goal they can paste to assign. The Claude Code harness refuses a goal prompt over 4000
  characters, so an over-long goal fails at *paste* time — after the planning session that wrote
  it has ended. Telling the author to keep it short repeatedly failed to hold, so the goal is now
  composed under a budget instead of estimated. `tautline goal-assignment --target . --plan <plan>`
  emits an assignable goal carrying the plan reference, the scope, the completion condition, the
  autonomy contract, and the proof command, and prints its exact character count and headroom. The
  goal is emitted between `goal_assignment_begin` / `goal_assignment_end` markers rather than
  behind a label, because `char_count` certifies the goal text alone and any prefix pasted along
  with it eats into the same budget; `--raw` prints those bytes and nothing else, for piping.
- **A fail-closed check for goals you already wrote.** `goal-assignment --check <file|->` validates
  an authored goal and exits 1 when it is over the limit, naming the exact count and the overage so
  the remedy is derivable from the refusal. It also flags a goal that states no completion
  condition or omits the plan reference. Run without `--plan`, the plan-reference check cannot
  run, and the output says so on `goal_assignment_plan_reference_check:` rather than passing
  silently — a skipped check must never read as a clean one.

### Changed

- **The irreducible core of a goal is never trimmed.** The plan reference, completion condition and
  proof command always survive; if they alone cannot fit the limit, composition *refuses* rather
  than emit a goal that cannot tell a builder when to stop. Only the milestone list flexes, and
  every dropped or shortened entry is reported on `goal_assignment_milestones:` and marked in the
  goal itself as `(+N more in the plan)` — nothing is silently truncated. That the plan *has*
  milestones is core, not flexible: when the budget admits no full entry, the goal still says
  `Milestones: all N are in the plan`, so omitted work is never invisible at any limit.
- **A goal cannot be emitted for an unfinalized plan.** Composition is gated on the plan's
  finalization precheck and refuses with the plan-review recovery path, so unreviewed work is not
  handed to a builder lane. `--allow-unfinalized` dry-runs the wording and labels its own output as
  not-yet-assignable.
- **`plan-finalization-precheck` now names the next step on success.** Its pass output carries one
  additional `plan_finalization_next_action:` line pointing at `goal-assignment` with the plan
  already bound, so the goal is emitted in the same turn planning finalized. Advisory and
  print-only; the precheck's exit codes are unchanged.

## [0.29.0] - 2026-07-27

### Added

- **Succession-chain accounting for plan review (item 32).** The plan-review hard cap counts
  reviewer invocations *per plan path*, so starting a successor plan — the sanctioned exit the cap
  refusal itself names — hands out a brand-new four-round budget. Nothing counted what a *chain*
  spent: one live item ran 22 legal rounds across six chained plans, and every ledger read it as
  six fresh starts; a second chain's only record of its 6 cumulative rounds was a sentence someone
  typed into a free-text note. `run-plan-review` now accepts `--predecessor <plan>`, which records
  the succession link on the run meta and carries it into the finalized manifest along with the
  chain's depth and cumulative recorded rounds. Both ceremonies print the running total —
  `plan_review_chain_ledger:` at run time, `plan_review_chain_status:` at finalize — and the
  finalize event carries the chain refs.
- **A cumulative-spend advisory that never blocks.** Past 8 cumulative recorded rounds or a chain
  depth of 3, one `plan_review_chain_advisory:` line prints at both surfaces, states plainly that
  nothing is blocked, and names only the two remedies that work from there: decompose the scope,
  or carry non-blocking findings into the implementation review focus list. Exit codes do not move
  and succession is never refused by chain accounting — the escape hatch the round cap depends on
  stays unconditionally reachable, which is the 2026-07-14 deadlock's standing constraint.
- **Honest totals, marked as such.** A chain member whose spend cannot be established from
  evidence is reported as `unknown` and the total is printed *and persisted* as a floor (`>=`,
  `chain_evidence: floor`), so a stored number can never masquerade as an exact count. Each member
  is counted exactly once from its own records — never from another member's chain total, which
  would double-count every shared ancestor.
- **Adoption pressure, not inference.** The successor instruction the cap refusal prints now names
  the flag, and a plan whose name has the strict `-vN` shape with a reviewed predecessor and no
  recorded lineage gets one `plan_review_lineage_hint:` line. It records nothing: auto-recording a
  guessed predecessor would put an invented fact into an evidence record.

### Changed

- Lineage is append-once. A repeated `--predecessor` matching the recorded value is a no-op; a
  conflicting one is refused quoting both values, because review evidence is never edited or
  retired. The only new errors in this release fire on an explicitly-passed `--predecessor`;
  omitting the flag behaves exactly as 0.28.1 did, and manifests and run metas written before this
  release parse and finalize unchanged.

## [0.28.1] - 2026-07-27

### Fixed

- **`tautline-test-run/v1` counts were authorable by assertion.** Hashing the report copy proved
  the *report* had not been edited, but nothing checked that the record's own `counts` block
  agreed with it — so editing `counts` in the record JSON left the hash valid and the record still
  classified `current`, surfacing fabricated pass/collected numbers. Reproduced, then fixed:
  `classify_test_run_evidence` now re-parses the hashed copy and requires every count field to
  match, returning `invalid` on any disagreement. Records written by `test-run` are unaffected;
  only hand-edited ones change state. This is the exact substitution the feature exists to
  eliminate, found inside the feature's own first release.
- `tautline test-run --report <path>` no longer refuses when the adapter declares
  `testEvidence.report.format` — the flag's help promised that fallback, but the code read the
  adapter value only when the *path* also came from the adapter.

## [0.28.0] - 2026-07-27

### Added

- **`tautline test-run` and the `tautline-test-run/v1` record (item 37, Release 1).** Every other
  Tautline control that appears to cover tests validates a *declaration* about tests, never an
  *execution*: `ci_test_gate` reports `has_tests=true (adapter declares a preflight/test command)`
  — the parenthetical is the whole check — and `finalize-implementation-review` takes its verdict
  and finding counts as self-reported CLI arguments. `test-run` runs the configured command and
  writes a record that is a by-product of executing it: the command's real exit code, counts parsed
  from the runner's own machine-readable report, and a digest of the non-ignored tree that was
  tested. A record stops reading as `current` the moment the tree moves, which retires "I ran the
  tests" as a defence. The wrapper exits with the underlying command's exit code, so a red suite
  stays red.
- **Optional `testEvidence.report` adapter key** `{path, format}` (`junit-xml` | `pytest-json`).
  Absent-safe: a lane that declares nothing gets `counts.source: exit-code-only` with an explicit
  warning rather than a claim of zeros.
- **Report-only surfacing** at `lane-start` and `guard-check --boundary prepush`. Release 1 changes
  no exit code in any evidence state — a fail-closed gate on upgrade would recreate the 2026-07-22
  startup-gate lockout. Enforcement and test-reachability are versioned separately.

### Changed

- The "Green tests must mean working software" rule now names its machine-checkable form.
- `AGENTS.md`, `CLAUDE.md` and the self-adapter's `commands.fullPreflight` agree that
  `scripts/test.sh` **is** the full preflight. `validate.sh` execs it, so the previous
  run-both instruction executed the identical suite twice for no additional coverage — a
  contradiction that produced four wrong review rejections across two backlog items.

## [0.27.1] - 2026-07-27

### Fixed

- RCA 2026-07-22 control 1 (a refusal must name its own supported control) was already
  implemented but neither correctly pinned nor correctly labelled. The non-release-branch
  refusal does name `maintainer-mode on` ahead of the narrower
  `MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1` escape, but its regression test grepped `cli.py`'s
  source text and asserted only that the phrase appeared *somewhere* -- so reordering the two
  remedies, which is exactly the regression that taught two consecutive sessions to build a
  launcher bypass, passed the suite. The pin now runs `sync-methodology` on a non-release branch
  and asserts the **emitted** message: the supported control appears before the bypass, and the
  env var keeps its "single intentional deviation" qualifier. Verified by swapping the order and
  observing the new test go red while the old one stayed green.
- The same control was credited to "control 2" in both `cli.py` and the test section header,
  which is why it kept reading as outstanding in the backlog. Both surfaces now say control 1,
  with a label assertion kept separate from the behavioural one.

## [0.27.0] - 2026-07-26

### Fixed

- The plan-substance check matched four unfinished-work words anywhere on any line, so it rejected
  a FINISHED plan over `**Placeholder scan:** clean.` -- a heading the plan-authoring self-review
  template tells the author to write -- while reporting only "plan contains stub/TODO markers", so
  on a long plan the remedy was derivable only by reimplementing the regex by hand. It now matches
  marker SHAPES, exempts backticked and fenced text, and quotes the offending line and substring
  (item 29: plan-precheck marker false positive).
- The native-review-note check rejected every angle bracket, so a note could not quote a real
  string containing one -- it blocked a review round whose note quoted the very placeholder that
  change removed. It now matches unfilled-token shape, exempts quoted spans, and names the
  offending token (item 19: review-note placeholder check).

## [0.26.0] - 2026-07-26

### Added

- Canonical policy now requires plain language at every human-facing boundary -- delivery,
  handoff, blocker, status, any answer to a direct question -- and a real request when the agent
  needs something from a human: what is needed, why, the cost of not having it, the options, and a
  recommendation. Internal vocabulary may follow the plain-language opening; it never replaces it
  (item 33: plain-language operator boundaries, operator-raised).

### Fixed

- Four remaining plan-review call sites still decided on the caller-supplied `--round` label
  rather than recorded evidence: the plan-edit guard, the finalize-time convergence remedy, frame
  span ordering, and a same-second timestamp tie. This completes 0.22.0, which stopped the round
  BUDGET trusting labels but left these behind (item 31).
- The goal-kickoff contract test read the developer's live goal state, so the suite went red for
  anyone who had run `goal-start` -- which the plan-authoring standard tells every builder to do
  before touching code. CI never saw it, so only the person following the process paid
  (item 30: goal state couples the test suite).

## [0.25.0] - 2026-07-26

### Added

- `tautline lane-status` reports lane currency -- upstream gone, behind the
  integration branch, VERSION drift, already merged, integration branch held by
  another worktree, dirty tree, detached HEAD -- and a second `SessionStart` hook
  runs it before the first reasoning turn. Report-only by construction: the
  adapter knob accepts only `off` or `report`, and every exit path returns 0.
- `laneStatus` adapter domain (`startupCheck`, `fetchTimeoutSeconds`,
  `maxAgeMinutes`, `integrationBranch`, `statusFile`, `claimSource`).
- `render-adapters --omit-domain laneStatus`, the supported compatibility render
  for downgrading a lane below 0.21.0.

### Changed

- The canonical Autonomy rules make lane currency the agent's job: attempt the
  printed remedy, and when it cannot complete, state the unresolved drift in your
  own output rather than reporting it to the operator as their task.


### Deprecated

### Removed

### Fixed

### Security

## [0.24.0] - 2026-07-26

### Fixed

- A plan-review round that answered **clean** and then quoted a prior log carrying blockers was
  refused: the selected findings span ran to the end of the scope, so the verdict scan read the
  quoted blockers as if they were this round's. The span now stops at the next quoted frame that
  begins after the reviewer's own heading. It failed closed — a false refusal, never a false clean
  — but a refusal nobody can act on is the class this ladder exists to remove.
- Two overlong lines added by 0.22.0's follow-up pushed the repo-wide E501 ratchet over its
  baseline; both are wrapped, and the count is back under it.

## [0.23.0] - 2026-07-26

### Fixed

- The finalize-time blocker scan could grade the **wrong round's findings**. Plan-review logs are
  framed by two sentinel lines, and the reviewer routinely prints text containing them — it greps
  the codebase, where the constants are source lines, and it reads previous round logs as evidence.
  The parser split on the FIRST closing sentinel, so on any such log the captured block ended early
  and `review_log_verdict_errors` scanned a truncated span: on a stored log it saw the previous
  round's clean findings and never saw the current round's P1. 19 of 121 stored logs closed early
  (item 25: plan-review log verbatim replay).
- Each run's log is now framed with a per-run nonce (`--- review output --- run:<nonce>`, recorded
  in the run meta), and one resolver decides the span — by nonce when the caller supplies one from
  the bound run meta, otherwise by position, ending at the footer that is actually followed by
  `finished_at:`. Findings selection skips headings inside a quoted complete frame, in either
  order, with a fallback so it can never narrow to nothing.
- Authority is a parameter, not a convention: `run-plan-review`, `finalize-plan-review`, and
  `plan-finalization-precheck` pass it (the precheck keying off the existing
  `PLAN_REVIEW_TRUSTED_RECORDERS` boundary), while `record-plan-review` imports scope whole-log,
  which is the fail-closed direction. The plan-identity check deliberately keeps framed scoping so
  a log header or an echoed review command cannot stand in for the reviewer's own output.

## [0.22.0] - 2026-07-25

### Changed

- The plan-review round budget now counts **successful reviewer invocations** against one source
  plan instead of the `--round` label the caller passes. A lane that relabelled every round `R1`
  and never finalized could launch unlimited Codex rounds, because both cap gates read the label:
  one live lane spent ten invocations on a single plan, six of them under one label, while the
  four-round hard cap never engaged (item 24: plan-review round advance gap). Failed and
  watchdog-killed runs still cost nothing. The two-round convergence target, the rounds 3-4
  exception-note ladder, and the cap numbers are unchanged.
- Every `run-plan-review` prints a `plan_review_round_ledger:` line, and the run meta and manifest
  record `observed_successful_runs` and `effective_round`, so a divergence between what a round was
  called and what was actually spent is visible in the evidence rather than only in the logs.
- Past the cap, when an unfinalized successful run already matches the current plan content, the
  refusal now names the runnable `finalize-plan-review` command for that run instead of demanding a
  split — the exit that actually works from that state.

## [0.20.0] - 2026-07-24

### Added

- Canonical Delivery Summaries policy now requires that any reference to a backlog, requirement, plan, or tracker item by its key or ID (for example `FR-3`, `item 17`, a `METH-FU-...` slug, or an issue number) be immediately followed by the item's short title as `KEY: <short title>` in human-facing output — a bare key is not self-explanatory to a human reader.

## [0.19.0] - 2026-07-23

### Changed

- End-of-goal close now states the agent owns review **and** merge-queueing: a clean, gate-green,
  review-clean PR is opened and queued to merge by the agent (routine merge-queue or auto-merge per
  the adapter's merge policy), then the agent advances and moves on. Ending a delivery at "ready for
  your review", "ready to merge", or any approval handoff is forbidden work-evasion, the same class
  as stop-and-ask. Aligns with the existing `pr_queued`-terminal / queue-and-move-on subsystem — no
  engine or guard change.
## [0.18.2] - 2026-07-24

### Changed

- The trust gate's `held` notice now names the actual update instead of a generic remedy. When a
  `pinned` machine holds an upstream advance, `lane-start` and `sync-methodology` print the
  resolved take-it offer — the held candidate's version and channel — in place of `update-repin
  --channel <stable|experimental>`, so the operator can copy one runnable command rather than guess
  a channel. Exactly one take-it line is shown; a `signed`-policy hold keeps its own
  signature/signer remedy untouched. Display-only: the update decision, probe, and policy paths are
  unchanged, and the offer never feeds the decision.

## [0.18.1] - 2026-07-23

### Fixed

- The test suite no longer depends on how the session was launched. The operator fleet launcher
  exports a session profile (`unverified` update policy plus pins, `DISABLE_AUTO_RESCUE`,
  `DISABLE_SNAPSHOT_EXEC`) that switched off the trust gate, the snapshot store, and the sync
  rescue paths — the exact subsystems three groups of tests assert against — silently failing 23
  tests on any operator-launched machine while passing in CI. The pytest fixture layer now
  neutralizes that profile, and drops the `TAUTLINE_` alias of every legacy env name the suite
  sets so an alias cannot shadow it. Tests only; no shipped behavior changes.

## [0.18.0] - 2026-07-23

### Added

- Plan-Authoring Standard: Tautline now authors T1+ plans in a parallel, model-tiered,
  autonomous shape by default. A new read-only `tautline plan-authoring-standard` verb prints the
  standard (parallel workstreams with a dependency graph, per-lane worktree isolation, per-task
  `model-tier:` tags, and the embedded execution-autonomy contract), and a new `plan-authoring`
  skill wraps `superpowers:writing-plans` to layer the standard on top. `policy/13-planning.md`
  carries the rule as default for T1+ plans (T0 exempt).
- A `finalize-plan-review` shape guard, gated on the new read-side adapter knob
  `planning.authoringStandard.enforcement` (`off | observe | advise | block`, default `advise`).
  `off` is a full passthrough to vanilla `superpowers:writing-plans` or any other methodology;
  `advise` warns; `block` rejects a linear/untagged plan before the review manifest is written;
  `observe` logs a would-block. The knob is absent-by-default, so no existing adapter is
  regenerated.

## [0.17.5] - 2026-07-23

### Changed

- Implementation-review convergence now mirrors the plan-review ladder in the review-before-push
  policy: reaching the round budget is never an operator escalation for a reversible in-workflow
  fork. When remediating findings within budget changes the assembled diff, the owed clean
  confirming round on the current diff is self-authorized repair work — re-record a fresh Stage 1
  sweep on the remediated diff and take the round with `codex-run --allow-extra-rounds` — not a
  question to stop and ask. Docs-only planning artifacts continue to take the plan-review contract,
  not the implementation-review confirming-round budget.
- Scoped the review break-glass. If the round-budget tooling itself blocks a legitimate confirming
  round after all Critical/C1/P1 are resolved, that is a tooling defect to repair, not a license to
  skip evidence. A `--no-verify` push is a narrow, non-routine break-glass permitted only when a
  fresh Stage 1 sweep on the current diff records zero Critical/C1/P1, a `decision-record` states
  the specific tooling defect being worked around, and the same defect is filed for repair. It
  never ships a diff with an open blocker and never substitutes for a runnable confirming round.

## [0.17.4] - 2026-07-22

### Added

- Unauthorized-disarm detection for maintainer mode (RCA 2026-07-22 control 2). `maintainer-mode
  on` records an arm marker in the state dir -- deliberately outside the config env, since the
  failure being detected is that file being rewritten; `maintainer-mode off` removes it. A marker
  with the mode key absent from every config surface means the config env was edited behind the
  mode's back and every update gate is live again, so `maintainer-mode status`,
  `methodology-status`, and every `sync-methodology` launch report it and name both remedies
  (re-arm, or accept the disarm through the verb). A machine armed before this release is
  backfilled a marker on its next launch, flagged `observed` so the notice never claims a
  first-arm time it cannot know.
- Diverged-launcher detection (RCA 2026-07-22 control 4). The installed-launcher record gains a
  per-launcher sha256 taken at install (schema v2; v1 records are still read). A recorded launcher
  that no longer carries the generated marker reports as `hand-replaced` -- this needs no digest,
  so it catches hand-written replacements from pre-existing v1 records; one whose bytes no longer
  match the recorded digest reports as `edited`. Each reports with the `install-claude-launcher`
  line that regenerates *that* launcher: the install records the options it was installed with
  (`--bin-dir`, `--operator-channel`/`--runtime`, `--dangerously-skip-permissions`) and the notice
  replays them, so the remediation can never talk an operator into replacing a non-blocking
  operator launcher with a gated default one. Records written before this release carry no
  options, and their line says so rather than printing a command that might be wrong. Surfaced at
  launch and in
  `methodology-status`. Advisory only: a gate here would be a second way to be blocked at startup,
  which is the failure this RCA exists to end. A recorded launcher the operator deleted is not
  reported.

### Changed

- The non-release-branch sync refusal names `maintainer-mode on` first -- the supported control
  for an operator who intentionally tracks a non-release branch -- before the
  `MINERVIT_METHODOLOGY_ALLOW_NON_MAIN` escape. The previous wording named only the escape, and
  two consecutive sessions read it and built launcher bypasses instead.

### Fixed

- In-process tests no longer read the operator's own maintainer-mode state. The session CLI module
  bakes the real `HOME` into its config-env constants, so on a machine where the maintainer had
  legitimately run `maintainer-mode on`, six upstream-trust tests failed with `'skipped' ==
  'failed'` — a suite that only passed on machines whose operator had not used the product. An
  autouse fixture now points both config surfaces at a per-test path.

## [0.17.3] - 2026-07-22

### Added

- Operator fleet launcher (FR-1): `install-claude-launcher --operator-channel <channel>
  [--runtime <path>]` installs a distinct NON-BLOCKING operator launcher that fetch-advances
  the operator's OWN channel, session-scopes an `unverified` policy via its own launcher-body
  exports (no shared `methodology.env` write, so the default managed launcher and other
  commands on the machine keep their pinned trust gate), and execs
  `--dangerously-skip-permissions`. Every git step is failure-guarded so a start never blocks
  (offline, stale pin, or a missing runtime just log and continue). The default managed
  launcher, its `_SKIP_PERMISSIONS_LAUNCH_GUARD`, the install guard, and the pinned trust
  model are all byte-unchanged (golden test). Distinct from `maintainer-mode`, which edits
  the framework in place and does not fetch. NOT WIP-safe: carries forward 0.17.0's
  `install-fleet-guard-hook` and 0.10.3's `grant-gh-project-scopes` required migrations.

## [0.17.2] - 2026-07-22

### Changed

- Package split part B, THE FLIP (roadmap #11): internal refactor only. The entire
  CLI engine body — every command handler, the `_register_<family>_<n>` segment
  functions, the lazy `*_module()` accessors, `dispatch_command`, `main()`,
  `_MissingFrameworkPackage`, and the eager wave aliases — moves from `bin/tautline`
  into `src/tautline_methodology/cli.py`, and `bin/tautline` becomes a thin
  executable shim that resolves the framework package (a dev checkout OR the wheel's
  embedded `_dist` tree, both carrying `src/tautline_methodology` beside `bin/`) and
  delegates to `cli.main()`. The shim keeps a standalone fail-open fallback so a
  copied `bin/tautline` with no `src/` sibling still honors the hook fail-open
  contract. Root and subcommand `--help`, the dispatch map, and every runtime
  behavior stay byte-identical; no verb, help line, exit code, or output changed.
  Every invocation path is unchanged: the launcher ladder, the snapshot store, the
  legacy `minervit-methodology` execv target, CI `py_compile`/`registry-package`,
  and the wheel runpy of `_dist/bin/tautline` all keep resolving. Further
  distribution of `cli.py` into family modules is a documented follow-up. NOT
  WIP-safe: it carries forward 0.17.0's `install-fleet-guard-hook` required
  migration (framework_update_decision reads only the latest report), plus
  `grant-gh-project-scopes` from 0.10.3.

## [0.17.1] - 2026-07-22

### Changed

- Package split part B, wave W4 (roadmap #11): internal refactor only. The
  lane/context ROOT families — the most shared-state-heavy in the CLI — have their
  closure-clean leaves extracted from `bin/tautline` into the
  `tautline_methodology` package — `lane.py` (the deterministic lane slot/index
  derivation, the lane env-file path, the lane session-state path, the
  lane-coordination config accessor with the coordination contract/board markdown
  templates, and the lane-start debt-preflight write wrapper, plus the
  `LANE_SESSION_FILE` constant) and `context.py` (the pure context-rotation
  decision core that caps a non-host-sourced percent to advisory). Each module
  imports only stdlib, so lane and context cannot form an import cycle. Every
  stateful lane/context verb handler (lane-start/lane-run, the lane-coordination
  verbs, work-loop, context-bootstrap/status, context-rotation-check and its
  heartbeat hook) stays in `bin/tautline` — its closure reaches monolith state
  (REPO_ROOT/run_git/load_project/lane_project/goal_run_path) — and wires the moved
  leaves through eager aliases, so the root parser and every subcommand `--help`,
  the dispatch map, and all runtime behavior stay byte-identical. No verb moved; no
  behavior, help-text, exit-code, or output change. NOT WIP-safe: it carries forward
  0.17.0's `install-fleet-guard-hook` required migration (framework_update_decision
  reads only the latest report), plus `grant-gh-project-scopes` from 0.10.3.

## [0.17.0] - 2026-07-21

### Added

- Fleet Governor (v1, PR 1 of 2): cross-worktree lease coordination for N
  concurrent agent lanes on one repo. New `tautline fleet-lease` verb
  (`claim --globs g1,g2 [--ttl-minutes N] [--goal REF] [--note TEXT]`,
  `renew`/`release [--lease ID] [--operator-note TEXT]`,
  `takeover --lease ID --note WHY [--operator-note TEXT]`) storing
  `tautline-fleet-lease/v1` records in `<git-common-dir>/tautline-fleet/`, and a
  new `tautline fleet-guard-hook` PreToolUse guard that blocks (or advises, or
  observes, per the new adapter `fleet.enforcement` domain) edits to paths
  leased by another lane — always with runnable escapes, always fail-open on
  corrupt state. Single-lane repos short-circuit before any lease parsing.
  Scope: the guard covers the structured file-edit tools (`Edit`, `Write`,
  `MultiEdit`, `NotebookEdit`). Writes issued through `Bash` (`sed -i`, shell
  redirection) are NOT guarded in v1. Glob syntax is `*`, `?`, and `**`;
  bracket classes are not supported and match literally. Minor bump: new public
  CLI verbs, new hook, new adapter surface.

### Changed

- `methodology-status --fail-on-drift` now counts `fleet-guard-hook` among the
  required Claude hooks. Settings-managed installs report drift until their
  settings are rewritten; recovery is `tautline install-hooks`, or any
  `tautline lane-start`, which repairs settings on the way through.

## [0.16.5] - 2026-07-21

### Changed

- Package split part B, wave W3 (roadmap #11): internal refactor only. The
  delivery/publication families' closure-clean leaves are extracted from
  `bin/tautline` into the `tautline_methodology` package — `adapters.py` (the
  bootstrap-interview questionnaire builder and its question bank, bootstrap
  answer-slot parsing, rendered-adapter provenance-stamp extraction and
  stamp-equivalence normalization, the fail-closed init command string, canonical
  adapter-JSON serialization, and adapter test-command detection) and `release.py`
  (the registry-package MIT license text, the registry-JSON HTTP fetch, the
  release-notes leak-term scan, the public-mirror export overlay, and annotated-tag
  commit peeling). The `publish` and `install` families have no closure-clean defs
  — every handler reaches monolith state (run_git/run_command/lane_project/chat/
  deploy/canonical helpers) — so they are fully deferred with no module this wave.
  The stateful render/init/bootstrap and release verb handlers (render-adapter,
  init-methodology-project, adapter-drift, cut-release, registry-package,
  release-tail, release-migration-report) stay in `bin/tautline` and wire the moved
  leaves through eager aliases, so the root parser and every subcommand `--help`,
  the dispatch map, and all runtime behavior stay byte-identical. No verb moved; no
  behavior, help-text, exit-code, or output change. WIP-safe.

## [0.16.4] - 2026-07-21

### Changed

- Package split part B, wave W2 (roadmap #11): internal refactor only. The
  work-tracking families' closure-clean leaves are extracted from `bin/tautline`
  into the `tautline_methodology` package — `goal.py` (the pure goal-plan parsers,
  goal-run ledger record/percent/integrity helpers, and GitHub-Projects
  goal-tracker field/value/item accessors), `milestone.py` (the milestone-update
  config accessor plus the milestone-run ledger record/percent/integrity helpers),
  and `backlog.py` (the backlog-item business-lead justification scanners with
  their heading constants, and the stakeholder-question config/marker/parse
  helpers). Each module imports only stdlib, so the three cannot form an import
  cycle. The stateful verb handlers (goal-start/advance/tracker, milestone
  start/advance, publish-milestone-update, backlog-provider/board, and
  stakeholder-question ask/status) stay in `bin/tautline` (they reach
  lane/adapter/goal-run/board state) and wire the moved helpers through eager
  aliases, so the root parser and every subcommand `--help`, the dispatch map, and
  all runtime behavior stay byte-identical. No verb moved; no behavior, help-text,
  exit-code, or output change. WIP-safe.

## [0.16.3] - 2026-07-21

### Changed

- Package split part B, wave W1 (roadmap #11): internal refactor only. The guards
  & review machinery's closure-clean leaves are extracted from `bin/tautline` into
  the `tautline_methodology` package — `response_guard.py` (the pure response-guard
  detection scanners plus their marker constants, importing the scan primitives
  from `guards.py`) and `iteration_review.py` (the iteration-review record
  validation, media/output-contract checks, poster/HTML render helpers,
  delivery-marker matching, and chat/workflow payload builders, plus the three
  customer-copy/approval constants). The stateful verb handlers stay in
  `bin/tautline` (they reach lane/adapter/goal state) and wire the moved helpers
  through eager aliases, so the root parser and every subcommand `--help`, the
  dispatch map, and all runtime behavior stay byte-identical. No verb moved; no
  behavior, help-text, exit-code, or output change. WIP-safe.

## [0.16.2] - 2026-07-21

### Changed

- Package split part A, PR A2 (roadmap #11): internal refactor only. The
  mechanism-spike def plus the events/usage family's closure-clean leaves are
  extracted from `bin/tautline` into the `tautline_methodology` package —
  `core/paths.py` (`event_jsonl_read_paths`), `core/policy.py` (the shared
  repo-event guard/marker constants + the `event_boundary_family` decision core),
  `events.py` (record-id and boundary-audit helpers), and `usage.py` (usage
  dedupe/token/report helpers). `bin/tautline` re-exports every moved name as an
  eager alias, so the root parser and every subcommand `--help`, the dispatch map,
  and all runtime behavior stay byte-identical. No verb moved; no behavior,
  help-text, exit-code, or output change. WIP-safe.

## [0.16.1] - 2026-07-21

### Changed

- Package split part A, PR A1 (roadmap #11): internal refactor only. `main()`'s
  inline argparse registration body is carved into order-preserving per-family
  `_register_<family>_<n>` segment functions (still in `bin/tautline`), called in
  the exact original interleaved order, so the root parser and every subcommand
  `--help` stay byte-identical. No import moves; no behavior, help-text, exit-code,
  or output change. Adds two behavior-neutrality goldens as test data — the
  `--help` corpus (`tests/data/help_corpus/`) and the AST-derived dispatch map
  (`tests/data/dispatch_map.json`) — guarded by a shared, migration-proof walker
  so every later package-split move can be proven neutral.

## [0.16.0] - 2026-07-21

### Changed

- Compatibility sunset **warn stage** (roadmap #16, PR 2): the deferred-
  conveniences disposition plus the two P2 fixes deferred from PR 1. Managed-
  config `TAUTLINE_` aliases are now complete — the residual `MINERVIT_`-only
  update-policy config-file read is closed, so a config carrying only
  `TAUTLINE_METHODOLOGY_UPDATE_POLICY` resolves. Adapter drift/status messages
  now name the **resolved** marker file (a repo managed only via the legacy
  `.minervit-ai-delivery.json` marker names that file, not the canonical
  `.tautline.json` it does not have on disk). The autocompact durable-settings
  (`~/.claude/settings.json`) and managed-launcher writers now dual-write the
  `TAUTLINE_CLAUDE_AUTOCOMPACT_PCT` / `TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED`
  twins, so a normally-provisioned session resolves them through the alias and
  emits **zero** autocompact deprecation warnings on startup. No functional
  change: values, gates, guards, and every legacy surface are unchanged. The
  full disposition of all five deferred conveniences is recorded in the
  `METH-FU-TAUTLINE-FALLBACK-REMOVAL` backlog item.

### Fixed

- `release-migration-report` now refuses undeclared skipped versions in the
  `0.14.7 < v < 0.15.0` and `0.15.0 < v < 0.16.0` patch ranges instead of
  fabricating a stale report: the 0.15.0 minor bump had left the `0.14.8+`
  range with no gap guard, so `release_migration_report_data("0.14.8")`
  produced a bogus pre-`0.6.125` report. Both gap guards now raise, mirroring
  the existing `0.13.x` / `0.12.x` guards; the declared `0.15.0` and `0.16.0`
  minors still succeed.

## [0.15.0] - 2026-07-21

### Deprecated

- Compatibility sunset **warn stage** (roadmap #16, PR 1): every legacy
  `minervit`-era surface now emits a once-only, stderr-only deprecation warning
  naming the tautline replacement and the 1.0 removal — the `MINERVIT_*` env
  fallbacks (through `resolve_env` and the interactive session launcher), the
  `minervit-methodology` launcher name, and the legacy marker/config fallbacks
  (`.minervit-ai-delivery.json`, `.minervit/adapter.json`,
  `~/.config/minervit/methodology.env`) plus the pre-rebrand repo slug. Every
  legacy surface keeps working exactly as before — this stage removes nothing.
  Silence the window for automation with `TAUTLINE_SUPPRESS_SUNSET_WARNINGS=1`
  (or the equally-honored `MINERVIT_SUPPRESS_SUNSET_WARNINGS`); `*-hook` verbs
  and `--hook` invocations stay byte-silent (total containment). Exit codes and
  stdout are byte-identical. Per-surface `deprecatedSurfaces`
  (`removeAfter: 1.0.0`) are enumerated in the 0.15.0 migration report so the
  removal plan can attest each surface individually.

## [0.14.7] - 2026-07-21

### Added

- Guided onboarding (roadmap #14, PR 2): the SessionStart directive hook
  (`autonomy-directive --hook`) now offers onboarding **resumption** on positive
  evidence — an interview-pending or source-unrendered un-adapted repo emits one
  root-resolved `onboarding_offer:` line (exit 0, never blocking). Zero-trace /
  unmanaged repos stay byte-silent (total containment); the hook never shells out.

### Fixed

- The unmanaged no-adapter recovery now names the requested target
  (`tautline init --target <target>`) instead of a hard-coded `.`, so a gate verb
  run with `--target` elsewhere recovers the failed repo, not the cwd (renders `.`
  only when target == cwd; unmanaged-at-target output stays byte-identical).

## [0.14.6] - 2026-07-20

### Added

- Guided onboarding (roadmap #14, PR 1): an un-adapted session start now offers
  the onboarding interview — state-aware (fresh repo / interview in progress /
  source adapter unrendered), root-resolved from any cwd, and AskUserQuestion-
  mediated — at `goal-kickoff-prompt`, the generated launcher, and the
  no-adapter recovery text, instead of a stale `init` recovery line. Nothing
  auto-runs; gate verbs still fail closed.

### Changed

- The no-adapter message is split into a stable `NO_ADAPTER_SENTINEL` prefix +
  a swappable recovery block + a preserved footer; unmanaged-at-target output is
  byte-identical to before and every consumer matches the sentinel. No exit-code
  changes. Not WIP-safe solely for the carried-forward engine-gap migration.

## [0.14.5] - 2026-07-20

### Added

- Installed-package (pip/pipx) runtimes now probe PyPI for the available release
  and print a `framework_update_offer:` line with the pipx/pip update command
  when a newer version exists (roadmap #15, completing PR 1's git-checkout
  support). Read-only, fail-open, 24h cache, 3s timeout; opt out with
  `TAUTLINE_METHODOLOGY_UPDATE_PROBE=off`.

### Changed

- Display-only: no policy/trust/exit-code change; the package-mode remote-status
  line is byte-identical. Not WIP-safe solely for the carried-forward
  `grant-gh-project-scopes` engine-gap migration.

## [0.14.4] - 2026-07-20

### Added

- Session-start surfaces (`lane-start`, `sync-methodology`, `methodology-status`)
  now report the genuinely available framework version and a non-blocking,
  trust-aware `framework_update_offer:` line naming the first real unblock
  (roadmap #15), instead of the silent `methodology_update: skipped`. Backed by
  a read-only, fail-open, cached update probe (single `ls-remote` per launch;
  launches never fetch; opt out with `TAUTLINE_METHODOLOGY_UPDATE_PROBE=off`).

### Changed

- Display-only: `framework_update_decision`, `framework_available_version`, trust
  gates, and the `held` path are byte-identical; any probe failure yields
  byte-identical session-start output. `methodology-status` performs one bounded
  fetch into a disposable `refs/tautline-update-probe/*` ref only. Not WIP-safe
  solely for the carried-forward `grant-gh-project-scopes` engine-gap migration.

## [0.14.3] - 2026-07-20

### Changed

- De-minervit refactor part 2A, PR 3 (write-new/read-both). GitHub-comment
  markers (milestone-progress, stakeholder-question), git rescue refs
  (`tautline-local-rescue/`), and non-schema state paths
  (`~/.local/state/tautline/{renderer-kit,methodology-rescue}`) now emit the
  tautline form and still read/parse the legacy minervit form. Lock-bearing
  paths and schema ids are unchanged.
- **BREAKING (default):** `composeProjectPrefix` default is now `tautline`
  (was `minervit`). Adopters relying on the default `COMPOSE_PROJECT_NAME` will
  see docker containers/volumes created under the old prefix orphaned; set
  `composeProjectPrefix` explicitly to retain them. Not WIP-safe; the 0.10.3
  `grant-gh-project-scopes` migration is carried forward.

## [0.14.2] - 2026-07-20

### Changed

- De-minervit refactor part 2A, PR 2. Shipped policy prose, plugin skill/
  reference prose, and product display names (plugin `displayName`s, the local
  marketplace displayName, and the auto-maintained GitHub-comment footers) now
  say Tautline, and `author.url` points at `github.com/tautlines`. Company name,
  copyright, and marketplace owner stay Minervit; the `tautline` shim keeps the
  legacy command working, so there is no runtime behavior change.
- The framework channel pin migrates from `.minervit/pin.json` to
  `.tautline/pin.json` (mirroring the adapter-dir move): new pins write the
  tautline path, and a legacy `.minervit/pin.json` is still read and is copied
  onto the tautline path on read.

### Deprecated

- `MINERVIT_*` env vars now emit a once-only stderr deprecation warning when
  read from the process environment without their `TAUTLINE_*` alias set. The
  value still resolves; this starts the deprecation clock for the `MINERVIT_*`
  family (removed at a future major release).

## [0.14.1] - 2026-07-20

### Changed

- Internal-only rename: the repo-local Python package `minervit_methodology`
  is renamed to `tautline_methodology` (de-minervit refactor part 2A, PR 1).
  The package is unpublished, so there is no public API and no user-visible
  change; the `bin/minervit-methodology` shim and `MINERVIT_*` env fallbacks
  keep working.

## [0.14.0] - 2026-07-19

### Added

- Decision ledger read surface. A new `tautline decisions-report` verb reads the
  machine-local decision ledger written by `decision-record` and lists decisions
  for one or more lanes, newest first. It is rotation-aware (current log plus
  retained rotations), lock-guarded, and collision-safe: every rendered value
  passes a total type-safe validator, same-repo worktrees that share one event
  log are de-duplicated, and both `lane` and `lane_id` are printed so
  basename-colliding sibling worktrees stay distinguishable. Bounds filter the
  view — `--since`/`--until` (ISO-8601 or a duration such as `24h`; zone-less
  values are UTC) and `--since-seq`/`--until-seq` (single-target, non-negative,
  inclusive upper / exclusive lower) — and `--json` emits one
  `tautline-decisions-report/v1` envelope object with a closed per-decision
  projection. Every output carries an unconditional `retained rotations only`
  scope note; the report makes no completeness or reproducibility claim.
- Session-journal decision window. `prepare-session-journal` now records three
  preparation-time lines in the `## Session Runtime` section —
  `decisions_recorded`, a `decisions_report` convenience pointer (always
  `--target .`), and a monotonic `decisions_watermark_seq` — chaining each
  journal to the watermark of the nearest older validating journal so a session
  can see how many decisions were recorded since the last one. Counts are scoped
  to retained rotations and stated as such. Suffix-aware journal discovery is
  centralized so collision-suffixed journals are visible to the pending-status
  and leak-detection scans too. The new runtime fields are optional, so existing
  v1 journals stay valid.

### Changed

- Like 0.10.4–0.13.0 this release stays NOT WIP-safe and carries 0.10.3's auth
  migration forward until the intermediate-migrations update engine ships. It
  reads only; no guard, gate, or review behavior changes.

## [0.13.0] - 2026-07-19

### Added

- SessionStart standing-directive hook. A `SessionStart` hook is now registered
  (plugin manifest + `install-hooks` settings writer + self-enforcing
  `lane-start` migration) for directive-core's already-shipped
  `tautline autonomy-directive --hook`, so a bare session — one where no
  entry-point verb has run yet — still receives the STANDING AUTONOMY DIRECTIVE.
  The hook command is fail-open at the shell boundary
  (`/bin/sh -c 'command -v tautline … || true'`) with a 5-second per-hook
  timeout, so a missing/older CLI or a hanging shim never breaks session start.
  The hook ALWAYS emits — there is deliberately no dedup/suppression machinery —
  so compaction and resume re-inject the directive by construction; the accepted
  cost is at-most-double emission (a cosmetic ~7 lines) on machines registered
  from both the plugin manifest and settings.

### Changed

- The hook-state gate (`methodology-status --fail-on-drift`) extends to a NINTH
  required hook: a settings-managed install missing the SessionStart entry now
  surfaces as blocking startup debt, recoverable with `tautline install-hooks`.
  This is additive BLOCKING behavior — a previously-passing install can now
  block — hence the minor bump; release policy reserves patches for bug fixes.
  No other guard, gate, or review semantics change. Like 0.10.4–0.12.0 this
  release stays NOT WIP-safe and carries 0.10.3's auth migration forward until
  the intermediate-migrations update engine ships.

## [0.12.0] - 2026-07-19

### Added

- Capability-aware standing autonomy directive. `goal-kickoff-prompt`,
  `lane-start`, and `context-bootstrap` now emit a short STANDING AUTONOMY
  DIRECTIVE block as their first output, and a new `tautline autonomy-directive`
  verb (`[--target .] [--hook]`) renders it on demand. The block tells an agent
  to work autonomously toward the active goal, record non-obvious decisions with
  `tautline decision-record`, and queue only genuinely operator-owned forks.
  The two capability-resolved lines (record mechanism, question queue) are
  derived from CHEAP LOCAL SIGNALS ONLY — adapter presence,
  `stakeholderQuestions.enabled`, and the startup-remediation marker file — so
  the directive never shells out or touches the network on a session-start path.
  Where no adapter exists it names no `tautline` commands (session notes only);
  where the stakeholder-question flow is disabled, remediation-gated, or fails at
  ask time it falls back to a hard-to-reverse `decision-record` entry.
- New `autonomy.standingDirective` adapter knob (boolean). Absent (the default)
  is treated as ON; set `false` to fully opt a lane out. The key is read-side
  only — never materialized into a rendered lane adapter, so upgrades drift
  nothing.
- Canonical rules gain an "Unattended Operation" subsection documenting the
  standing directive as default operating policy, the durable-record obligation,
  and the async operator-fork queue with its hard-to-reverse fallback.

### Changed

- No guard, gate, or review mechanics changed. Minor bump: new public CLI verb
  and adapter surface. Like 0.10.4–0.11.0 this release stays NOT WIP-safe and
  carries 0.10.3's auth migration forward until the intermediate-migrations
  update engine ships.

## [0.11.0] - 2026-07-19

### Added

- New `tautline decision-record` verb: a fail-closed, machine-local structured
  decision-ledger writer. It records a decision (`--summary`, required
  `--rationale`, optional `--alternatives`, `--reversibility`, repeatable
  `--surface`, and the usual `--goal`/`--milestone`/`--pr` linkage) as a
  `decision` event on the lane's existing per-lane event log, carrying a
  top-level `record_kind` = `tautline-decision/v1` discriminator so a reader
  never mistakes a decision-named event for a ledger entry. Unlike ordinary
  narration it is written even when `observabilityEvents.enabled` is false — the
  toggle governs observability, not the operator's review ledger — via a
  keyword-only `bypass_enabled_gate` on the append primitive whose sole caller is
  the verb itself. Every non-empty stored field is sanitized and validated before
  any write; nothing is ever silently dropped. Decision records are never
  remote-published. No gate, guard, or review behavior changes. Minor bump: this
  is the first verb of a new public CLI family. Like 0.10.4–0.10.14 it stays NOT
  WIP-safe and carries 0.10.3's auth migration forward until the
  intermediate-migrations update engine ships.

## [0.10.14] - 2026-07-18

### Added

- The `npm-audit` workflow now publishes a run artifact named `evidence`
  containing a `tautline-evidence/v1` `probe` suite with one result per audit
  level (critical, high). Each result is read from the step's `outcome` (not
  `conclusion`), so a failing informational high+ audit — which carries
  `continue-on-error: true` — reports an honest `fail` even while the job stays
  green. The audit failure policy is unchanged: critical still blocks the build,
  high+ still does not. Like 0.10.4–0.10.13 it stays NOT WIP-safe and carries
  0.10.3's auth migration forward until the intermediate-migrations update engine
  ships (the engine reads only the latest report).

## [0.10.13] - 2026-07-18

### Added

- The `validate` workflow now publishes a run artifact named `evidence`
  containing a `tautline-evidence/v1` document composed from the four gates the
  job owns (methodology suite, CLI compile, `validate.sh` freeze-check,
  whitespace), one `eval` result each. The gates gain step ids and `if: always()`
  so a later gate still reports its outcome after an earlier one fails — the job
  still fails, so blocking behavior is unchanged. `scripts/validate.sh` and
  `scripts/test.sh` are untouched. Like 0.10.4–0.10.12 it stays NOT WIP-safe and
  carries 0.10.3's auth migration forward until the intermediate-migrations update
  engine ships (the engine reads only the latest report).

## [0.10.12] - 2026-07-18

### Added

- CI now publishes a run artifact named `evidence` from `ci-python` and
  `renderer-ci`: pytest and vitest emit JUnit XML, and a small stdlib-only
  composer (`.github/scripts/emit_evidence.py`) turns GitHub step outcomes into a
  `tautline-evidence/v1` document. Because `ci-python` runs a two-leg matrix and
  v4 artifact names are immutable per run, each leg uploads a leg-scoped artifact
  and an aggregation job composes the run's single `evidence` artifact — the
  canonical leg's JUnit plus a probe suite carrying both matrix legs' outcomes
  and the `fresh-install-smoke` gate's result, so a matrix-leg or fresh-install
  failure can never render as green. Purely additive CI reporting:
  the coverage ratchet, ruff, mypy, and pytest gates still block exactly as
  before. Like 0.10.4–0.10.11 it stays NOT WIP-safe and carries 0.10.3's auth
  migration forward until the intermediate-migrations update engine ships (the
  engine reads only the latest report).

## [0.10.11] - 2026-07-18

### Changed

- The pre-push gate now scopes to PM surfaces: a push whose FULL branch diff
  against the configured base is entirely within the adapter-declared PM surfaces
  (`docs/product/**`) skips the review-evidence + CI gates. Every other push —
  code, mixed, force/multi-ref/delete/tag, a docs-only increment on a branch that
  already carries code, or a non-current-branch push — runs the full gate (fail
  closed). Authorized in canonical policy. The repo now ships a concrete
  `docs/product/` surface. Operators must reinstall pre-push hooks (`install-hooks`)
  to enable the relief. Like 0.10.4–0.10.10 it stays NOT WIP-safe and carries
  0.10.3's auth migration forward until the intermediate-migrations update engine
  ships (the engine reads only the latest report).

## [0.10.10] - 2026-07-18

### Added

- A `productDevelopment.surfaces` adapter key (opt-in) plus a fail-closed
  PM-surface classifier: the loader constrains every declared surface to sit
  under the `docs/product/` allowlist (framework docs, code, config, and root
  files are excluded by construction), and a change whose ENTIRE diff is within
  the declared surfaces is now exempt from the VERSION-bump contract — authorized
  in canonical policy. Code, methodology, plan, release, adapter-config, and
  mixed diffs are unaffected (the exemption is additive and fails closed). Like
  0.10.4–0.10.9 it stays NOT WIP-safe and carries 0.10.3's auth migration forward
  until the intermediate-migrations update engine ships (the engine reads only
  the latest report).

## [0.10.9] - 2026-07-18

### Changed

- Product-dev mode now stands down three shepherding agent nags while active —
  the latest-code baseline nag (and its stale-baseline state-change block), the
  active-goal Stop-guard, and the fake-monitor background-command guard — each
  emitting a non-blocking advisory. Every code-safety merge gate and the
  plan-finalization / plan-review-pending gates stay ON, so enabling the mode
  still cannot ship unreviewed code. Authorized in canonical policy,
  methodology-status, and the delivered skill references. Like 0.10.4–0.10.8 it
  stays NOT WIP-safe and carries 0.10.3's auth migration forward until the
  intermediate-migrations update engine ships (the engine reads only the latest
  report).

## [0.10.8] - 2026-07-18

### Added

- `tautline product-dev-mode on|off|status`: a per-checkout, auto-expiring
  (240-min TTL) product-dev mode declaration written to a gitignored
  `.ai-work/PRODUCT_DEV_MODE.json`. INERT in this release — no hook or gate
  reads it yet (the sibling shepherding standdown wires it in); enabling it
  cannot ship unreviewed code (no code-safety path reads the mode). The
  release's own change is inert, but like 0.10.4–0.10.7 it stays NOT WIP-safe
  and carries 0.10.3's auth migration forward until the intermediate-migrations
  update engine ships (the engine reads only the latest report).

## [0.10.7] - 2026-07-17

### Fixed

- Plan-review recovery decides the hard cap from the next round number
  (one past the highest round reached) rather than the raw successful-run
  count, so same-round reruns that reach the hard-cap count no longer
  mis-route a still-available convergence round to a successor plan — the
  predicate now mirrors the round-cap gate across every state. Like
  0.10.4–0.10.6, stays NOT WIP-safe and carries 0.10.3's auth migration
  forward until METH-FU-UPDATE-DECISION-INTERMEDIATE-MIGRATIONS ships.

## [0.10.6] - 2026-07-17

### Fixed

- Plan-review recovery and guard predicates are now exactly consistent with
  `run-plan-review`'s own self-authorization gate, closing two false-block
  edge cases in 0.10.5's new deadlock logic: a finalized plan is no longer
  edit-blocked by a superseded run recording the same hash, and the routine
  fix-after-blockers flow is no longer routed to a plan split when the gate
  would allow the next convergence round. The genuine-deadlock successor
  path (a clean bound round the plan then edited, or past the hard cap) is
  unchanged.
- Like 0.10.4/0.10.5, this release stays NOT WIP-safe and carries 0.10.3's
  required auth migration forward for lanes updating across 0.10.3 in one
  jump, until METH-FU-UPDATE-DECISION-INTERMEDIATE-MIGRATIONS ships.

## [0.10.5] - 2026-07-17

### Fixed

- **The plan-review deadlock is closed at both ends.** A PreToolUse guard
  now blocks the edit that wedges a lane (editing a source-of-truth plan
  after a capped review round reviewed it, before finalize binds it), and
  the cap/recovery messages tell the truth: they name the sanctioned
  successor-plan path instead of prescribing the `run-plan-review` the cap
  will refuse. The successor-plan practice is documented policy.

### Changed

- Process authority is write-protected against memory: the canonical memory
  policy adds the never-write-process-to-memory rule and routes process
  lessons through framework-intake (RCA when a control failed, feature
  request when it's missing); the intake reference gains the
  post-publication point-only rule, a memory-write drift pattern, and the
  "decision capture artifact / DCA" vocabulary alias.
- Like 0.10.4, this release stays NOT WIP-safe and carries 0.10.3's required
  auth migration forward for lanes updating across 0.10.3 in one jump, until
  METH-FU-UPDATE-DECISION-INTERMEDIATE-MIGRATIONS teaches the update engine
  to walk intermediate reports.

## [0.10.4] - 2026-07-17

### Fixed

- The CLI imports on native Windows again: the snapshot-store fault-phrase
  map accessed POSIX-only errno names (`EDQUOT`/`ESTALE`) at module level;
  it is now getattr-guarded and present-only.
- A legacy `goalTracker.unavailablePolicy: "warn"` survives the
  provider/tracker normalization round trip — a deliberate offline opt-down
  is no longer silently dropped (and re-blocked) on load.
- The 0.10.3 required auth migration is carried forward (and this release
  stays NOT WIP-safe) for lanes updating across 0.10.3 in one jump: the
  update engine consults only the latest report until
  METH-FU-UPDATE-DECISION-INTERMEDIATE-MIGRATIONS ships.

## [0.10.3] - 2026-07-17

### Fixed

- **Board gates fail closed.** With a backlog provider enabled, "cannot read
  the board" (gh missing, unauthenticated, or a token without the project
  read scope — which is `gh auth login`'s default) now BLOCKS the
  pre-commit/pre-push board hook, `guard-check`'s board-currency check, and
  `methodology-status --strict/--fail-on-drift`, printing the exact remedy
  (`gh auth refresh --hostname github.com -s read:project -s project`).
  Previously all three surfaces warned and passed, silently disabling board
  enforcement on normally-authenticated machines — the root cause behind
  recurring "work shipped but the board never moved" incidents. Required
  migration: grant the gh project scopes on every machine running
  provider-backed lanes. `backlogProvider.unavailablePolicy: "warn"` is the
  explicit adapter opt-down for deliberate offline work.

## [0.10.2] - 2026-07-16

### Fixed

- Snapshot-store integrity: the generated launcher refuses to pin a `current`
  left behind the canonical HEAD by a failed publish (announced on stderr,
  executes the checkout, never blocks a launch — and stays armed in git
  worktree checkouts), and a freshness stamp that recorded a stale store no
  longer starves the heal retry. Regenerate launchers with
  `tautline install-claude-launcher --force` to pick these up.
- Package-mode isolation: installed packages stand the snapshot store fully
  down (no heal, no pin refresh, no freshness stamp) and read-only reporters
  no longer remote-probe a leftover configured checkout.
- Snapshot-store diagnostics: a concurrently-pruned entry no longer empties
  the store report; fault warnings name full-disk, quota, read-only/stale
  mount, and I/O faults (permissions keep the honest "unreadable" default);
  degrade warnings route to stderr; a failed pin refresh reports instead of
  degrading silently.
- The launcher's shell maintainer-mode guard parses hand-edited config shapes
  (quoted values, trailing comments, exportless assignments) the same way the
  Python reference does on every supported shape; the deliberate divergences
  stay documented in the launcher comment.
- Registry package: generated pyproject pins the hatchling major; wheels are
  byte-reproducible (commit-date stamp); a symlinked `_dist` is refused
  loudly.

### Changed

- Release contract: renderer-kit dependency pins (package.json + lockfile)
  are exempt from the VERSION-bump gate, so Dependabot npm bumps merge as
  raised; touching a lockfile AND framework code still requires the bump.
- `.claude/` local agent-session state is gitignored.

## [0.10.1] - 2026-07-16

### Changed

- The npm registry copy leads with the product and the one-command install
  ("Tautline is a Python CLI. Install it with pipx") instead of self-describing
  as a namespace pointer. The name-reservation fact stays as plain copy — the
  package still installs nothing and says so — and the no-npm-wrapper decision
  is unchanged. The published npm page updates at the next release-tail.
- Dev toolchain: mypy 2.3.0 (Dependabot #384 adopted through the version-bump
  contract). Dependabot now raises PRs against `experimental`, where a PR can
  actually merge, instead of the promotion-only `main`.
- Review-ledger hygiene: four pre-0.9.16 implementation-review ledgers carry
  backfilled finding titles, derived from their own recorded summaries; no
  finding was reclassified.
- The public boundary scan and the release export's dirty-state gate ignore
  `.claude/` local agent-session state: untracked worktree checkouts of
  historical branches under it made scan verdicts and export refusals depend
  on which sessions had run on the machine, not on what ships.

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
