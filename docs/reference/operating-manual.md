# Tautline Operating Manual

This is the detailed operating manual for maintainers and advanced adopters. The
top-level `README.md` is the public entrypoint; keep long procedures here or in
focused reference docs.

Tautline is the canonical process source for AI-assisted software delivery across Claude, Codex, project adapters, skills, and recurring automations.

This repo exists to keep AI development process rules out of scattered memories, stale lane files, and duplicated agent instructions. It provides one durable framework, thin generated project adapters, and a local Codex plugin that packages reusable workflows as skills.

For source-policy edits, start with the [Policy Module Index](policy-module-index.md).
`methodology/canonical-rules.md` is a generated compatibility artifact, not the
editing surface.

## Onboarding A New Project

Use `tautline init` as the front door for unmanaged repos.

```bash
cd <target-repo>
tautline init --target .
```

The command writes `.ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md` and prints only the
project facts that still need a human answer, including backlog location,
production status, gates, deploy ownership, review wrappers, and autonomy
boundaries.

After the interview artifact is answered, continue:

```bash
tautline init --target . --continue
```

The continuation writes `.tautline/adapter.json`, renders `CLAUDE.md`,
`AGENTS.md`, and `.tautline.json`, then runs `lane-start` without
changing existing managed repos. If a repo already has `.tautline.json` (or the
legacy `.minervit-ai-delivery.json`),
`init` exits with the normal `lane-start` command instead of overwriting it.

Keep advanced bootstrap details in
[Project Administration](operations/project-administration.md#adding-a-new-project).

## Table Of Contents

- [Onboarding A New Project](#onboarding-a-new-project)
- [What This Repo Owns](#what-this-repo-owns)
- [Authority Model](#authority-model)
- [Repository Layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Codex Plugin Setup](#codex-plugin-setup)
- [Claude Setup](#claude-setup)
- [Claude Launcher Helper](#claude-launcher-helper)
- [Release Engineering](#release-engineering)
- [Core CLI Usage](#core-cli-usage)
- [Project Adapters](#project-adapters)
- [Lane Lifecycle And Methodology Updates](#lane-lifecycle-and-methodology-updates)
- [Release Tracks And Adapter Migrations](#release-tracks-and-adapter-migrations)
- [Document Context Budget](#document-context-budget)
- [Graphify Navigation](#graphify-navigation)
- [Goal Orchestration](#goal-orchestration)
- [Backlog Provider Workflow](#backlog-provider-workflow)
- [Cross-Lane Coordination](#cross-lane-coordination)
- [Iteration Reviews](#iteration-reviews)
- [Milestone Updates](#milestone-updates)
- [Product Chat Notes](#product-chat-notes)
- [Execution Packet Work Loop](#execution-packet-work-loop)
- [Drive, Do Not Defer](#drive-do-not-defer)
- [Anti-Work-Evasion](#anti-work-evasion)
- [Current Status Truth](#current-status-truth)
- [Plain-Language Status](#plain-language-status)
- [Verified Human Instructions](#verified-human-instructions)
- [Early-Warning Smoke](#early-warning-smoke)
- [Milestone Progress Visibility](#milestone-progress-visibility)
- [Delivery Summaries](#delivery-summaries)
- [Readiness Automation](#readiness-automation)
- [Context Continuity](#context-continuity)
- [Session Journals (Local-Only)](#session-journals-local-only)
- [Repo Event Logs](#repo-event-logs)
- [Usage Accounting](#usage-accounting)
- [Review And Merge Policy](#review-and-merge-policy)
- [Background Work Policy](#background-work-policy)
- [Open Brain Policy](#open-brain-policy)
- [Adding A New Project](#adding-a-new-project)
- [Adding Or Updating Skills](#adding-or-updating-skills)
- [Validation](#validation)
- [Publishing To GitHub](#publishing-to-github)
- [Troubleshooting](#troubleshooting)
- [Maintenance Rules](#maintenance-rules)
- [Documentation Language Standard](#documentation-language-standard)

## What This Repo Owns

This repo owns reusable framework policy, project adapter rendering, drift
audits, readiness helpers, and the local Codex plugin. Product requirements,
lane scope, persistent memory, and secrets stay outside this repo. Keep the
full ownership boundary in [Setup And Runtime](operations/setup-runtime.md#what-this-repo-owns).

## Authority Model

Process authority is layered: canonical policy first, project adapters
second, generated project files third, and memories only as evidence. Generated
files are not hand-edited; change canonical policy or adapter source, then
regenerate. Keep the detailed precedence and memory boundary in
[Setup And Runtime](operations/setup-runtime.md#authority-model).

## Repository Layout

Key directories are `methodology/` for reusable policy, `adapters/projects/`
for project adapters, `bin/` for the CLI, `plugins/` for the local Codex
plugin, and `scripts/` for repository gates. Keep the full tree and
important-file map in [Setup And Runtime](operations/setup-runtime.md#repository-layout).

## Prerequisites

The framework expects a shell environment, Git, Python 3, GitHub CLI for GitHub
operations, Codex for the Codex plugin, and Claude Code for Claude integration.
Keep install checks and GitHub auth notes in
[Setup And Runtime](operations/setup-runtime.md#prerequisites).

## Initial Setup

Validate fresh checkouts with `scripts/test.sh` and `scripts/validate.sh`, then
install the portable shim with `bin/tautline install-cli`.
Generated adapters and handoffs must not hard-code person-specific checkout
paths; they resolve `tautline` from `PATH`, then fall back through
`MINERVIT_METHODOLOGY_REPO`. Keep clone, validation, and shim details in
[Setup And Runtime](operations/setup-runtime.md#initial-setup).

## Codex Plugin Setup

The plugin lives at `plugins/tautline-core`; the release
version has one source of truth in `VERSION`, mirrored into plugin manifests
only because Codex and Claude hosts need manifest-local versions. Bump
`VERSION` for every methodology build that changes reusable framework behavior.
Project adapter JSON changes under `adapters/projects/*.json` are project
configuration changes and do not require a global methodology version bump
unless the same PR also changes reusable framework surface. Main keeps a small
release-note stub; the full narrative release log lives on
`methodology-release-notes-archive`. Validation requires `VERSION` to match the
plugin manifest, first changelog heading, and release-note stub heading, and
fails reusable framework changes without a version bump. After bumping
`VERSION`, publish with
`publish-release-update --version "$(cat VERSION)"`; the command uses
`CHANGELOG.md`, the release migration report, and
`MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK`. Keep marketplace setup,
generated-adapter size limits, archive details, and release-update behavior in
[Setup And Runtime](operations/setup-runtime.md#codex-plugin-setup).

### Available Codex Skills

The plugin packages reusable workflow skills for audits, lane lifecycle, goal
orchestration, execution packets, review-before-push, risk-tier autonomy,
operator-progress reporting, RCA, document context, Graphify, migration collisions,
session journals, event logs, iteration reviews, milestone updates, plan
review, continuity, and project bootstrap. Keep the current skill list in
[Setup And Runtime](operations/setup-runtime.md#available-codex-skills).

## Claude Setup

Claude should load this repo through the machine-level `~/.claude/CLAUDE.md`
bootstrap, pointing at `methodology/canonical-rules.md`. Claude Superpowers is
recommended for Claude-side review and planning workflows. Keep the bootstrap
template and install commands in [Setup And Runtime](operations/setup-runtime.md#claude-setup).

## Claude Launcher Helper

The managed launcher keeps Claude startup portable: update the framework, install
the shim, then run `tautline install-claude-launcher --name minervit-claude`.
The installed launcher lives in
`~/.local/bin/minervit-claude` by default, runs sync/startup/status gates, and
starts Claude only after lane checks. The high-autonomy command remains
`install-claude-launcher --name yolo --dangerously-skip-permissions`; existing
shell aliases named `yolo` can shadow it. Keep the full launcher behavior,
`MINERVIT_SHOW_GOAL_PROMPT=0`, plugin-list expectations, and non-`main`
framework checkout rules in
[Setup And Runtime](operations/setup-runtime.md#claude-launcher-helper).

## Release Engineering

Maintainer releases use `scripts/test.sh`, `scripts/validate.sh`, public
contract checks, and public-release gates. Stable releases must protect existing
client lanes from raw-main upgrades and surprise migrations; experimental is
opt-in. Keep exact commands and client-safety promotion rules in
[Release Engineering](operations/release-engineering.md#release-gate-commands),
[Public Release Export](operations/release-engineering.md#public-release-export),
and
[Release Tracks And Client Safety](operations/release-engineering.md#release-tracks-and-client-safety).

## Core CLI Usage

The CLI entrypoint is `bin/tautline`. Keep detailed command usage in
[CLI Operations](operations/cli-operations.md#core-cli-usage).

### Render Project Adapters

Adapter rendering covers bootstrap questions, source adapter setup, generated
file checks, `--write`, and `--json-only`. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#render-project-adapters).

### Audit Drift

Drift audit catches known stale process patterns. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#audit-drift).

### GitHub-Only Readiness Review Data

GitHub-only readiness review fetches readiness evidence without touching a local
checkout. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#github-only-readiness-review-data).

### Background Run Helper

Background helpers provide log-backed execution, monitor status, and provider
recovery-loop evidence. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#background-run-helper).

### RCA Archive Publishing

RCA publishing validates methodology regression evidence and publishes it to the
dedicated archive branch. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#rca-archive-publishing).

### Session Journals (Local-Only)

Session journals are prepared and validated as normal-session evidence that stays
local — remote publication is disabled as of 0.9.0. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#session-journals-local-only).

### Methodology Repository Governance

Methodology repository governance separates reusable policy, archive branches,
PR changes, migration impact, and validation evidence. Keep detailed guidance in
[CLI Operations](operations/cli-operations.md#methodology-repository-governance).

### Plan-Finalization Gate

Plan finalization requires native review, trusted cross-model review evidence,
manifest binding, precheck, and hook installation. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#plan-finalization-gate).

### Document Context Commands

Document context commands bootstrap indexes, classify Markdown, add archive
headers, and inspect strict budget state. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#document-context-commands).

### Graphify Commands

Graphify commands inspect, install, build, refresh, and enforce generated graph
freshness. Keep detailed commands in
[CLI Operations](operations/cli-operations.md#graphify-commands).

## Database Migration Collisions

Parallel lanes that generate database migrations must check for monotonic migration-index collisions before commit, push, merge queue, and after rebasing onto main. If migration SQL, snapshot metadata, or journal files collide, keep the already-landed migration, move the current lane to the next free index, rebuild metadata/journal ordering, and verify with the adapter database tests plus merge-conflict check.

Use the `database-migration-collision` skill for Drizzle-style SQL/snapshot/journal repair details. Do not ask the human operator to choose a migration number when the next free index is derivable from the migration chain.

## Project Adapters

A project adapter records repo-specific commands, gates, planning paths,
review wrappers, release-track pins, generated files, and local resource
settings. Legacy `adapters/projects/*.json` remains supported while
adopter-owned repos migrate toward `.tautline/adapter.json`. Keep the full
adapter shape and example in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#project-adapters).

### Planning Artifact Placement

Project adapters define the source-of-truth path, template, trigger, review
exemptions, and scratch-only plan paths. Tool defaults are not authoritative.
Keep detailed rules for source-of-truth plan placement and scratch-plan
migration in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#planning-artifact-placement).

### Bug Backlog Management

Adapter-aware bug intake is active through the `bug-intake-triage` skill.
Agents classify severity, write the adapter-declared source of truth, create
only required mirrors, and keep customer-facing bugs on the stakeholder board
when `backlogProvider` is enabled. Keep the detailed policy in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#bug-backlog-management).

### Technical Stack Policy

Project adapters own technical stack policy. New projects default to AWS unless
they explicitly approve another provider, and AWS-approved lanes use AWS CLI as
the default deploy credential path. Keep provider defaults, forbidden
tool-default clouds, credential checks, and official AWS links in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#technical-stack-policy).

## Lane Lifecycle And Methodology Updates

Adapter-backed lanes start with `lane-start` and `methodology-status
--fail-on-drift`, resolve the methodology CLI through portable fallbacks, honor
release-track pins, protect hand-written generated-adapter targets, and fetch
latest-code evidence before analysis. Keep startup commands, update rescue,
lock/unlock, latest-code, and lane-local state details in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#lane-lifecycle-and-methodology-updates).

## Release Tracks And Adapter Migrations

Framework changes are controlled by client-facing pins. Stable is the default
for products and clients, experimental is opt-in, and WIP blocks unsafe
minor/major updates. Keep pin shape, migration commands, adapter migration, and
`public-release-check` publication boundaries in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#release-tracks-and-adapter-migrations).

## GitHub API Budget

Provider-backed lanes treat GitHub GraphQL points as a shared budget, prefer
REST where equivalent, and fail closed on required board mutations when the
budget is too low. Keep detailed budget and retry guidance in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#github-api-budget).

## Local Resource Isolation

Adapter-backed lanes isolate local test resources with lane-local environment,
Docker Compose project names, port blocks, and `lane-run` before falling back to
locks. Keep detailed commands and port-contention rules in
[Adapter And Lane Lifecycle](operations/adapter-lane-lifecycle.md#local-resource-isolation).

## Behavior Specs And Source Materials

Customer-facing behavior specs are adapter-configured. When enabled, behavior specs such as Gherkin must be written or updated before customer-facing implementation starts and reviewed with the source-of-truth plan.

Adapters may declare `behaviorSpecs.sourceMaterials` for reviewed business/customer/user behavior documents. Those materials are upstream source material, not inspiration. Agents must inspect, review, normalize, split, and adapt them into executable behavior specs before authoring new scenarios from scratch. The source-of-truth plan must include `## Behavior Source Materials`, account for every declared source material as reviewed/adapted or not applicable with a real reason, and document any material deviation from the reviewed business intent. Use `BEHAVIOR-SOURCE-EXEMPT: <real reason>` only inside that section when reviewed source materials do not apply to the plan.

`behaviorSpecs.roleVocabulary` lets projects declare allowed and forbidden actor terms. Agents should use the project’s precise roles and treat forbidden/generic role terms as required fixes unless the adapter is explicitly changed.

Behavior-spec-required projects also have acceptance integrity checks:

```bash
tautline behavior-spec-status --target .
```

This status checks adapter-declared `.feature` files, inactive tags such as `@pending`, and adapter-declared acceptance harnesses. Customer-facing behavior is not covered when scenarios are inactive or the harness drives the wrong application package. Inactive scenarios require owner, reason, and un-pend trigger within the adapter policy; "pending because no harness exists" is a P1 coverage gap until the harness executes the changed app.

## Proving Tests Ran

Every other test-related control validates a *declaration* about tests: `ciTestGate` checks that the adapter **declares** a preflight command, and `finalize-implementation-review` takes its verdict as a self-reported argument. `tautline test-run` closes that gap by producing evidence that is a by-product of executing something rather than a claim about having executed it.

```bash
tautline test-run --target .
```

It runs the adapter's `commands.fullPreflight` (or `--command`), streams output live, and writes a `tautline-test-run/v1` record under `.ai-runs/test-runs/` carrying the command's real exit code, machine-parsed counts from the runner's own report (declare it with the optional `testEvidence.report` adapter key; without one the record honestly says `counts.source: exit-code-only` rather than claiming zeros), and a digest of the non-ignored tree that was tested. The wrapper exits with the underlying command's exit code, so a red suite stays red. Readers classify the newest record as `current`, `stale`, `red`, `invalid`, `missing`, or `unavailable` — a record stops being `current` the moment the tree moves, which is what retires "I ran the tests" as a defence.

**Release 1 is report-only.** The state is printed at `lane-start` and at `guard-check --boundary prepush` and changes no exit code anywhere; boundary enforcement of the record, and test-reachability checking, are versioned separately.

## Document Context Budget

Projects can keep durable Markdown artifacts without loading all of them into every AI session. The budget rule is: read configured indexes first, load only named current artifacts, and treat archived/historical docs as evidence only.

Routine startup context is limited to:

- generated `CLAUDE.md` / `AGENTS.md`;
- `.tautline.json`;
- `.ai-continuity/NEXT_SESSION.md` when present;
- `.ai-work/EXECUTION_PACKET.md` when present;
- configured context indexes;
- adapter-declared readiness sources.

Agents must not broad-load Markdown trees or scan every plan/doc for routine context. A bounded Markdown audit must state the specific question, target files or globs, and an upper bound of 20 Markdown files unless a source-of-truth plan explicitly authorizes more.

Adapter-backed projects may configure `documentContext`. When absent, the CLI derives safe defaults:

- `enforcement`: `warn`;
- `contextIndexPaths`: `<planningArtifacts.sourceOfTruth>/_index.md`;
- `trackedDocRoots`: `planningArtifacts.sourceOfTruth`;
- `historicalPaths`: `<planningArtifacts.sourceOfTruth>/archive`;
- `ignoredDocPaths`: lane-local `.ai-*` state, planning scratch paths, common build/cache directories, and any explicit adapter paths;
- `maxIndexBytes`: `16000`;
- `maxIndexLines`: `250`.

Explicit `documentContext` paths must be project-relative or home-relative (`~`), not absolute workstation paths.

`lane-start` and `methodology-status` print a `document_context:` block showing enforcement mode, index paths, unclassified count, archive-header gaps, oversized indexes, and the instruction to read indexes first. Warn mode is the default for migration. Strict mode is enabled per project only after indexes and archive headers are clean.

Strict mode validates filesystem and index state. It does not sandbox or observe every file an AI agent reads, so generated adapters and the `context-continuity` skill remain part of the enforcement layer.

Standard index sections are:

- `Read First`
- `Active Work`
- `Ready Next`
- `Historical Evidence Only`
- `Do Not Load Routinely`
- `Needs Classification`

Archived Markdown must contain this sentence near the top:

```text
Historical evidence only. Not current process, scope, or execution authority. Start from <index path>.
```

### Machine Migration

For an existing framework checkout:

```bash
cd <methodology_repo>
git pull --ff-only origin main
bin/tautline install-cli
source "$HOME/.config/tautline/tautline.env"
tautline sync-methodology
tautline version
```

For first-time setup on a machine:

```bash
cd <projects_parent>
git clone https://github.com/tautlines/tautline.git
cd tautline
bin/tautline install-cli
source "$HOME/.config/tautline/tautline.env"
tautline version
```

All projects on the machine can use the same shared framework clone unless a lane is intentionally locked.

### Project Migration

Start in warn mode:

```bash
cd <lane_path>
tautline lane-start --target .
tautline context-bootstrap --target . --write
tautline context-bootstrap --target . --classify --write
tautline context-status --target .
tautline methodology-status --target . --fail-on-drift
```

Then review the generated index, move every `Needs Classification` entry into the right section, and add archive headers:

```bash
tautline context-bootstrap --target . --add-archive-headers --write
```

After the index is clean, set `documentContext.enforcement` to `strict` in the project adapter and validate:

```bash
tautline lane-start --target .
tautline context-status --target . --strict
tautline methodology-status --target . --strict --fail-on-drift
```

Existing unmanaged projects must bootstrap the project adapter first, then run the same context migration sequence. Do not use another project's paths or assumptions.

## Graphify Navigation

Graphify is optional per adapter and enabled by default for adapter-backed lanes. It is a codebase navigation and token-budget tool: when a graph exists, agents should query the graph before doing broad source scans.

Default behavior:

- `graphify-out/` is the generated output directory.
- `lane-start` ensures `graphify-out/` is ignored.
- `methodology-status --fail-on-drift` fails if anything under `graphify-out/` is tracked in git or stale.
- Existing `graphify-out/GRAPH_REPORT.md` or `graphify-out/graph.json` should be used before broad grep/`rg` for architecture, dependency, call-flow, and navigation questions.
- `rg` remains correct for exact lexical search, known-file checks, missing graph output, or temporary fallback after a failed refresh. Stale graph output must not be used.

Install when asked:

```bash
tautline graphify-install --target .
```

Build or refresh from the project root:

```bash
graphify update .
```

After every code, docs, schema, route, test, architecture, or other system change, refresh with `graphify update .` before relying on the graph, committing, or pushing. That command is the no-LLM AST rebuild: it needs no API key, no backend, and no external model, it cold-builds when no graph output exists yet, and it is the only Graphify invocation the blocking freshness gate names. If the refresh fails, treat existing graph output as invalid stale evidence and fall back to narrow `rg`/file reads only until the graph is rebuilt.

Semantic enrichment — community labels and `GRAPH_REPORT` prose — is a separate NON-blocking step with an explicitly named backend:

```bash
GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli
```

Run it only when enrichment is wanted; its failure never blocks commit or push. A Graphify invocation that auto-detects its backend is never a gate command.

Do not run Graphify assistant installers such as `graphify claude install` or `graphify codex install` unless the adapter explicitly allows assistant-file ownership and the human asks for that exact installer. Tautline owns generated `CLAUDE.md` and `AGENTS.md`.

## Goal Orchestration

Goal orchestration defines when work needs a goal, how the lane-local goal
ledger drives milestone execution, and how Claude `/goal` fits into the
workflow. Keep detailed command contracts, ledger behavior, and completion rules
in [Goal Execution](operations/goal-execution.md#goal-orchestration).

## Backlog Provider Workflow

Backlog provider workflow defines how GitHub Project items are selected, synced
into repo source-of-truth plans, kept current on the board, migrated/exported,
and reconciled with board-backed native subtasks. Keep detailed provider
commands, stakeholder-question flow, board order, epic scope, and subtask status
rules in [Backlog Provider Workflow](operations/backlog-provider-workflow.md#backlog-provider-workflow).

## Cross-Lane Coordination

Cross-lane coordination keeps ownership, shared contracts, dependencies, and
status visible through git-tracked artifacts. Keep detailed adapter defaults,
bootstrap/status commands, lane note format, and strict enforcement rules in
[Goal Execution](operations/goal-execution.md#cross-lane-coordination). Only the
current lane's own status file (plus the shared contract/board) blocks startup;
other lanes' stale, untracked, or dirty status is informational. Debt-class startup
failures, the remediation marker and contract, and the pre-push coordination
allowance are documented in [Startup Remediation](startup-remediation.md).

## Iteration Reviews

Iteration reviews are customer-facing communication artifacts for completed
goals. Keep detailed adapter config, validation, hosting, video, and delivery
rules in [Delivery Communications](operations/delivery-communications.md#iteration-reviews).

## Deployment Ready Notifications

Deployment ready notifications tell stakeholders when a deployed environment is
actually ready for review. Keep detailed adapter config, pipeline snippets, and
strict evidence rules in
[Delivery Communications](operations/delivery-communications.md#deployment-ready-notifications).

## Milestone Updates

Milestone updates are internal operator visibility artifacts for completed
milestones. Keep detailed adapter config, required headings, delivery markers,
and webhook rules in
[Delivery Communications](operations/delivery-communications.md#milestone-updates).

## Product Chat Notes

Product Chat notes are quick, human-requested messages to a project's product
Google Chat space. Keep detailed adapter config and publish commands in
[Delivery Communications](operations/delivery-communications.md#product-chat-notes).

## Context Rotation

Context rotation keeps long-running goal work recoverable before context pressure
causes poor decisions. Keep detailed thresholds, Claude auto-compact behavior,
safe-boundary rules, and `context-rotation-check` usage in
[Goal Execution](operations/goal-execution.md#context-rotation).

## Execution Packet Work Loop

The execution packet work loop turns an approved milestone plan into a tactical
queue, milestone ledger, review gates, and PR-by-PR continuation behavior. Keep
detailed packet requirements, milestone commands, plan-finalization controls,
review evidence rules, and hook requirements in
[Execution Packet Work Loop](operations/execution-packet-work-loop.md#execution-packet-work-loop).

## Drive, Do Not Defer

Drive/do-not-defer rules prevent required next actions from becoming permission
questions or passive checkpoints. Keep the detailed anti-deferral rules, true
blocker boundaries, RCA publication obligations, and forbidden examples in
[Autonomy Guardrails](operations/autonomy-guardrails.md#drive-do-not-defer).

## Anti-Work-Evasion

Anti-work-evasion policy names patterns such as permission theater, waiting
theater, recap substitution, validation dodge, and review dodge so agents keep
working when authorized work remains. Keep the detailed pattern list and
required counter-actions in
[Autonomy Guardrails](operations/autonomy-guardrails.md#anti-work-evasion).

## Current Status Truth

Current status answers start from fetched latest-code and external evidence, not
only the local worktree. Keep detailed `latest-code-status`, remote-main,
remote-branch, and stale-analysis rules in
[Status And Continuity](operations/status-continuity.md#current-status-truth).

## Plain-Language Status

Status updates should explain meaning before technical labels and keep the
operator informed during long work. Keep detailed phrasing rules, required
labels, monitor wording, and examples in
[Status And Continuity](operations/status-continuity.md#plain-language-status).

## Verified Human Instructions

Human-action instructions for external systems need same-turn verification from
authoritative sources. Keep detailed source, prerequisite, variant, and
unverified-instruction rules in
[Status And Continuity](operations/status-continuity.md#verified-human-instructions).

## Early-Warning Smoke

Early-warning smoke is risk-triggered, not a standing gate. When a trigger
requires it, the check runs early and stays supervised while planning or
implementation continues. Keep detailed trigger, monitor reuse, poll cadence,
failure, and post-merge rules in
[Status And Continuity](operations/status-continuity.md#early-warning-smoke).

## Final Preflight Planning Window

Final preflight time can be used for branch-isolated next-iteration planning or
active polling without mutating the current PR diff. Keep detailed safe-planning,
failure, stale-preflight, and `background-run` examples in
[Status And Continuity](operations/status-continuity.md#final-preflight-planning-window).

## Milestone Progress Visibility

Milestone progress visibility frames planned work with a plain-English benefit,
wall-clock estimate, and grounded percent complete. Keep detailed estimate,
refresh, percent, and blocker rules in
[Status And Continuity](operations/status-continuity.md#milestone-progress-visibility).

## Delivery Summaries

Delivery summaries begin with a plain-English executive summary and cannot become
a stop menu while authorized work remains. Keep detailed trigger, shape,
percent-complete, continuity-refresh, queued-delivery, and no-work-in-flight
rules in [Status And Continuity](operations/status-continuity.md#delivery-summaries).

## Readiness Automation

Readiness automation should run from the framework repo and avoid active
development lanes as scratch space. Keep detailed command and dedicated-clone
rules in [Status And Continuity](operations/status-continuity.md#readiness-automation).

## Context Continuity

Continuity handoffs are lane-local filesystem artifacts, not copy/paste chat
prompts, and are required at workflow boundaries. Keep detailed trigger,
handoff body, startup-gate, portable CLI, archive, and no-stop-menu rules in
[Context Continuity](operations/context-continuity.md#context-continuity).

## Session Journals (Local-Only)

Session journals are compact framework-improvement evidence for normal
delivery sessions. They are local-only as of 0.9.0 (no remote publication). Keep
detailed command usage, the local-only rationale, and default adapter config in
[Runtime Evidence](operations/runtime-evidence.md#session-journals-local-only).

## Repo Event Logs

Repo event logs are machine-local, repo-scoped observability evidence. Keep the
command list, viewer behavior, direct-write prohibition, and adapter config in
[Runtime Evidence](operations/runtime-evidence.md#repo-event-logs).

## Usage Accounting

Usage accounting is local operational evidence for AI spend and activity. Keep
the commands, confidence rules, local-only boundaries, and adapter config in
[Runtime Evidence](operations/runtime-evidence.md#usage-accounting).

## Review And Merge Policy

Review and merge rules define the pre-push review sequence, branch liveness
checks, queue behavior, admin-merge boundary, and blocker handling. Keep detailed
policy in [Workflow Guardrails](operations/workflow-guardrails.md#review-and-merge-policy).

## Background Work Policy

Background work rules define required feedback paths, active polling, monitor
boundaries, response-guard enforcement, provider retry loops, and stale-process
recovery. Keep detailed policy in
[Workflow Guardrails](operations/workflow-guardrails.md#background-work-policy).

## Open Brain Policy

Open Brain is persistent memory, not process authority. Keep allowed uses,
forbidden authority roles, and conflict handling in
[Workflow Guardrails](operations/workflow-guardrails.md#open-brain-policy).

## Adding A New Project

For normal unmanaged repos, use
[`tautline init`](#onboarding-a-new-project). Keep the lower-level
repo inspection, interview binding, scaffold, render, startup, and drift details
in [Project Administration](operations/project-administration.md#adding-a-new-project).

## Adding Or Updating Skills

Skills live under the plugin's `skills/` tree, each with concise frontmatter and
task-triggered content. Keep layout and validation details in
[Project Administration](operations/project-administration.md#adding-or-updating-skills).

## Validation

Repository validation runs `scripts/test.sh` and `scripts/validate.sh`, plus
project-specific render checks, audits, and readiness smoke tests when relevant.
Keep the detailed checklist in
[Project Administration](operations/project-administration.md#validation).

## Publishing To GitHub

Publishing requires a clean status, test/validation gates, normal Git flow, and
explicit approval before overwriting remote history. Keep detailed commands in
[Project Administration](operations/project-administration.md#publishing-to-github).

## Troubleshooting

Troubleshooting covers `gh` access, plugin visibility, Superpowers setup,
generated adapter checks, and drift-audit failures. Keep detailed commands in
[Project Administration](operations/project-administration.md#troubleshooting).

## Maintenance Rules

Maintenance rules define where reusable policy, adapter config, generated files,
skills, validation, and anti-regression boundaries belong. Keep the detailed
numbered list in
[Project Administration](operations/project-administration.md#maintenance-rules).

## Documentation Language Standard

Reusable framework documentation and generated adapter text use role-based
terms and placeholder paths, never person-specific names or workstation-specific
examples. Keep the detailed terminology rule in
[Project Administration](operations/project-administration.md#documentation-language-standard).
