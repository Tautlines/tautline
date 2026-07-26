# Framework Intake Policy Reference

This reference keeps detailed framework-intake policy behind the concise
`framework-intake` skill entrypoint: RCA first-pass analysis,
targeted evidence, taxonomy, artifact schema, validation, branch-published RCA
publication, branch-published methodology-repo copy rules, feature-request
intake, feature-request publication, and no-apology policy. It preserves
existing behavior while making routine methodology intake easier to load.

## Regression And Feature Intake

Use `framework-intake` when an agent violates, may have violated, or regresses on the methodology, or when the human operator asks why, RCA, root cause, or for a decision trace about agent behavior.

Use the same skill for Minervit framework or methodology enhancement requests:
new capabilities, new rules, new skills, new CLI support, new validation
coverage, new workflow integrations, or process improvements that do not yet
exist.

Use RCA only when there was a concrete methodology or process regression: an
existing canonical rule, adapter rule, skill, validation control, or expected
behavior was violated or failed to bind. Do not put feature requests on the RCA
rails just because the proposed change came from a gap. If both apply, write
the RCA for the regression first, then file a separate feature request for any
net-new capability.

Methodology skills are file-backed policy. If host skill tooling is unavailable, stale, or returns `Unknown skill`, resolve the methodology checkout in this order: existing `$MINERVIT_METHODOLOGY_REPO`; source `$HOME/.config/minervit/methodology.env`; run `tautline version --no-remote` and use its `methodology_repo`; then read `plugins/tautline-core/skills/framework-intake/SKILL.md` from that checkout and continue. `Unknown skill` is not a blocker unless those concrete resolution steps fail.

The output is an incident analysis plus a prevention proposal. Keep it direct,
evidence-backed, and free of raw transcripts, secrets, private absolute paths,
or customer-private details.

Do not write Open Brain, Claude memory, local memory, feedback-memory files, or any other memory note until after the RCA artifact is written, validated, and published. Memory capture is optional follow-up evidence only; it never replaces the RCA artifact. After publication, a memory note may only point to the published artifact and the canonical rule; it must not restate the process rule or procedure.

## Required Sequence

### RCA Sequence

1. First-pass analysis before tools:
   - State what happened from current context only.
   - Identify the violated methodology rule or expected behavior from canonical methodology, the active generated adapter, or a methodology skill. Do not cite Open Brain, Claude memories, local memories, or feedback-memory files as the rule source.
   - If only memory contains the claimed process rule, say the rule is missing or hidden in non-loaded methodology context and propose a canonical/adapter/skill change; do not write "what the rule says" from memory.
   - Name the likely failure class using the taxonomy below.
   - State what evidence is missing, if any.
2. Targeted evidence only:
   - Inspect only named artifacts needed to verify a stated uncertainty: relevant `CLAUDE.md` or `AGENTS.md`, canonical rules, skill files, logs, PR thread, continuity file, execution packet, or command output.
   - Memory/Open Brain artifacts may be inspected only as non-authoritative evidence/history. Label them as non-authoritative in `Evidence`; they cannot satisfy `Violated Rule`, `Expected Behavior`, or `Fix Proposal`.
   - Broad repo discovery is forbidden. Do not run recursive repo search, glob discovery, broad `find`, broad `rg`, tool-help discovery, or unrelated file reads during RCA.
   - If a needed artifact path is unknown, use only configured paths already present in current context, the lane adapter, or the canonical bootstrap. If the path is still unknown, state that uncertainty in the RCA and continue from current context.
   - Each inspected artifact must map to one stated uncertainty from the first-pass analysis.
   - In the artifact's `Evidence` section, list each inspected artifact as `<artifact>: resolved <stated uncertainty>`, or state `current conversation context only; no targeted tool verification needed`.
3. Root cause classification:
   - Choose one primary taxonomy entry.
   - Add contributing taxonomy entries only when evidence supports them.
   - Do not use "agent training default" as a generic escape hatch; tie it to a concrete missing, weak, hidden, conflicting, or unvalidated methodology control.
   - Do not use "tool/platform default" as a generic escape hatch; tie it to a concrete missing, weak, hidden, conflicting, stale, or unvalidated methodology control.
   - If the primary class is `Tool/platform default overrode methodology`, the root cause must also name the missing, weak, hidden, conflicting, stale, or unvalidated control that allowed it.
   - If the primary class is `Agent training default overrode methodology`, the root cause must also name the missing, weak, hidden, conflicting, stale, or unvalidated control that allowed it.
   - If the primary class is `Execution pressure/shortcut behavior`, the root cause must also name the missing, weak, hidden, conflicting, stale, or unvalidated control that allowed shortcut behavior.
   - If the primary class is `Tool/platform default overrode methodology`, `Agent training default overrode methodology`, or `Execution pressure/shortcut behavior`, the RCA cannot end with `No methodology change needed`; propose a control that makes recurrence harder.
4. Output artifact:
   - Create `.ai-runs/` if needed.
   - Write `.ai-runs/<utc>-methodology-regression-rca.md`, where `<utc>` uses `YYYYMMDDTHHMMSSZ`.
   - Gather methodology runtime facts when they are relevant to the failure: run `tautline version --no-remote` and `tautline methodology-status --target . --fail-on-drift` when a project adapter exists. If `methodology-status` cannot run, record the exact true blocker or failure output in `Evidence`.
   - The file must include every section in "Output Artifact" below.
   - Before replying in chat, verify the file exists and contains every required heading by running `tautline validate-rca-artifact --file <path>`.
   - For methodology/process regressions, publish the validated RCA into the methodology repository with `tautline publish-rca-artifact --file <path> --commit --push`. This creates a tracked copy on the maintainer repository's dedicated `methodology-rca-archive` branch, updates the archive index, commits the archive files, and pushes the branch so other machines and future agents can inspect it without loading RCA Markdown from `main`.
   - `publish-rca-artifact --commit --push` uses isolated archive-branch publication. Do not write RCA archive copies into the active methodology release checkout; `--allow-release-checkout-write` is validation/preview-only and is not cross-machine durable publication.
   - Do not add new RCA Markdown artifacts to methodology `main`. RCA evidence shapes the product; it is not itself the primary product methodology.
   - If the validator cannot run, the RCA is not complete. Name the exact true blocker and do not present the RCA as complete.
   - The RCA is not fully durable until the methodology-repo branch copy is committed and pushed. If publish/commit/push is blocked, execute the missing bootstrap or retryable recovery step and retry. Stop only for a true blocker where filesystem write, methodology checkout, Git commit, or Git push is impossible; name the exact blocker, include the lane-local path, and make the immediate next action the publish command or missing bootstrap/recovery step.
   - A chat-only RCA is non-compliant unless the filesystem write is impossible; if impossible, name the exact write blocker and still provide the RCA content in chat.
   - Any final response shaped as an RCA must point to both the lane-local `.ai-runs/<utc>-methodology-regression-rca.md` file and the pushed `methodology-rca-archive` copy. A Claude Stop response guard may block RCA-shaped final text that lacks those artifact references.
5. Chat summary:
   - Summarize the RCA concisely.
   - Point to both the lane-local RCA path and the pushed methodology RCA branch copy.
   - End with the concrete fix proposal or the evidence-backed reason no methodology change is needed.

### Feature Request Sequence

1. Classify the request:
   - Feature request: asks for a capability, rule, validation, artifact,
     workflow, or integration that does not yet exist.
   - RCA: analyzes why an existing rule/control failed or why an agent violated
     expected behavior.
   - If both apply, write the RCA first, then file a separate feature request
     for net-new capability.
2. Gather only enough context to make the request actionable:
   - Use current conversation context and targeted artifacts already named by
     the operator or obvious from the methodology checkout.
   - Do not run broad repo discovery just to make an intake artifact more
     elaborate.
   - Memory/Open Brain may be input evidence, but it is not process authority.
3. Write `.ai-runs/<utc>-methodology-feature-request.md`, where `<utc>` uses
   `YYYYMMDDTHHMMSSZ`.
4. Validate it before replying:

```bash
tautline validate-feature-request-artifact --file .ai-runs/<utc>-methodology-feature-request.md
```

5. Publish it to the dedicated archive branch:

```bash
tautline publish-feature-request-artifact --file .ai-runs/<utc>-methodology-feature-request.md --commit --push
```

6. Summarize the request concisely and point to both the lane-local artifact and
   the pushed `methodology-feature-request-archive` copy.

## Root Cause Taxonomy

- Missing rule.
- Weak/ambiguous rule.
- Rule hidden in non-loaded context.
- Conflicting rule.
- Tool/platform default overrode methodology.
- Agent training default overrode methodology.
- Stale adapter or drift.
- Missing validation/test coverage.
- Human instruction conflicted with standing methodology.
- Execution pressure/shortcut behavior.
- Memory/evidence treated as process authority.

## Output Artifact

Write `.ai-runs/<utc>-methodology-regression-rca.md` with this structure:

```markdown
# Methodology Regression RCA

## What happened

## Evidence

## Root cause

## Proposed control

## Validation
```

Then publish the validated RCA to the methodology repo:

```bash
tautline publish-rca-artifact --file .ai-runs/<utc>-methodology-regression-rca.md --commit --push
```

The pushed methodology RCA branch copy is the cross-machine evidence. The lane-local `.ai-runs/` file alone is incomplete for methodology work because it is ignored and will not reach other machines through Git. A copied-but-unpushed archive file is also incomplete.

Evidence must cite concrete artifacts or say "current conversation context only" when no tools were needed or available. When evidence comes from Open Brain, Claude memory, local memory, or feedback-memory files, label it non-authoritative; it cannot be the process authority for the control.

`Root cause` must name the failed or missing control, not only an agent habit or platform default. If the cause is `Tool/platform default overrode methodology`, `Agent training default overrode methodology`, or `Execution pressure/shortcut behavior`, also name the missing, weak, hidden, conflicting, stale, or unvalidated canonical/adapter/skill/validation control.

`Proposed control` states the concrete framework, adapter, skill, validation, or documentation change that would make recurrence harder. If no change is needed, cite the existing canonical/adapter/skill/validation controls that already cover the failure and explain why they failed to bind in this run.

`Validation` names the validation command, review, PR, test, archive branch publication, or true blocker proving the RCA and proposed control are complete enough for the next agent to act without redoing the analysis.

## Feature Request Artifact

Write `.ai-runs/<utc>-methodology-feature-request.md` with this structure:

```markdown
# Methodology Feature Request

## What this delivers

## Why it matters

## Current Gap / Evidence

## Proposed Capability

## Acceptance Criteria

## Validation Proof

## Risks / Compatibility

## Suggested Triage

## Immediate Next Action
```

`What this delivers` and `Why it matters` must be plain-language business
framing before technical detail. `Acceptance Criteria` must contain concrete
bullets or numbered criteria. `Immediate Next Action` must name a specific file
path, validation target, command, PR/check URL, or true-blocker decision.

Do not include person-specific machine paths such as `/Users/<name>/...`; use
repo-relative paths or canonical branch/path references.

Submission is intake evidence, not automatic backlog promotion. Accepted
requests can later become entries in the maintainer backlog or
provider-backed backlog items through the existing sanctioned backlog flow. Do
not mutate GitHub Project board structure or rewrite stakeholder-authored
backlog content as part of filing the request.

## Rules Audit

Use this skill when asked to inspect or reconcile AI development process rules.

## Workflow

1. Inventory process surfaces:
   - Machine: `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.codex/config.toml`, `~/.codex/rules/*.rules`, automation TOML files.
   - Project: `CLAUDE.md`, `AGENTS.md`, `.clauderules`, `.cursorrules`, `.claude/**`, review scripts/prompts, docs under `docs/ops/`.
   - Memory: Open Brain and local memory are evidence only.
2. Classify each rule as:
   - canonical
   - project adapter
   - evidence/history
   - stale/tombstone
   - conflicting
3. Resolve conflicts against the canonical methodology first, then the project adapter.
4. Report findings with exact file paths, the conflict, the chosen authority, and the proposed adapter/rule change.

## Drift Patterns To Flag

- Routine `--admin` merge.
- Queue rules that require blocking until `MERGED` or starting routine monitors for clean queued PRs instead of queue-and-move-on.
- Queue rules or examples that treat `mergeQueueEntry.estimatedTimeToMerge`, repeated `AWAITING_CHECKS`, or byte-identical merge-queue GraphQL output as live progress instead of switching to authoritative PR `state` and merge-group check evidence for exceptional checks.
- Rules or workflows that allow commits, review rounds, pushes, reverts, or tactical subagents to continue on a branch after its PR is queued, auto-merge-enabled, merged, or closed.
- Rules that delay delivery summaries until post-merge smoke/deploy success when no failure/degraded signal is known and the next action does not depend on merged main.
- Rules that require early-warning smoke at every iteration without an adapter/plan/issue/operator/risk trigger, or skip triggered early-warning smoke until the end.
- Rules that start duplicate local-service smoke/preflight commands against the same lane resources instead of polling an existing monitor or using a remote/main-health baseline.
- Rules or examples that let an agent identify a next milestone and ask whether to begin planning or pause.
- Rules or examples that let an agent launch a final/R3/cap/rerun review, say it will wake up later, and yield before consuming the review result or doing parallel-safe work.
- Rules, hooks, or generated adapters missing the `response-guard-hook` Stop guard for passive-monitor stops, chat-only RCA-shaped responses, status-report-as-stop on derivable-next-action prompts, terminal continuity omission, forbidden opt-in/standby language, and false-active status after rejected tools during live active goal work, or rules that let stale goal ledger files activate Stop guards in ordinary planning chat.
- Rules, hooks, or generated adapters that allow long work, review loops, monitors, or autonomous yields to omit the plain-language outcome/current state and next action.
- Rules or examples that let an agent ask permission to kill/retry a background process, review run, or local monitor it launched after concrete evidence proves the process is stale/hung.
- Rules or examples that let a status response claim work is active with `yes`, `about to`, `queued`, `planned`, or `next I'll` when the last state was idle, blocked, rejected, cancelled, denied, or no tool/monitor/parallel task is actually active.
- Rules or examples that let an agent call a review/background command active without verifying process liveness and log freshness through `monitor-status` or equivalent evidence.
- Rules or examples that rely on a tool launch timeout for detached background work instead of a wrapper-level timeout/watchdog.
- Rules or examples that ask the human operator whether to kill and retry routine review/preflight work after the monitor has already proven it is stale/hung.
- Rules or examples that treat delayed wakeups, monitor events, shell completion notifications, or reminders as replacements for active supervision.
- Rules or examples that use backgrounded shell `until`/`sleep`/`wait` loops as monitors, or that omit a `ScheduleWakeup`/host-equivalent self-wakeup when monitored work may outlast the current turn.
- Rules or examples that let agent-launched review/preflight work sit with no log/artifact growth for more than two times the poll cadence instead of killing/retrying without asking.
- Review rules that omit generated/derived artifact freshness from Stage 1 when source files have committed mirrors, behavior catalogs, snapshots, indexes, compiled docs, or other generated outputs.
- Rules or examples that schedule wakeups, reminders, or monitor prompts after queueing that restate completed push, PR creation, labeling, auto-merge, queue, or requeue steps, or that schedule exceptional queue checks without an already-known failure/degraded signal, explicit human request, or true dependency on merged main.
- Rules or examples that treat documented standing approval, closure criteria, execution-packet gates, or backlog/follow-up rows as requiring fresh approval after their conditions are met.
- Rules or examples that let an agent invent approval for break-glass/admin merge from habit, memory, urgency, or a vague preference instead of a named source-of-truth artifact.
- Rules or examples that condition starting, continuing, authoring, opening, outlining, scaffolding, preparing, drafting, or moving into planning on operator confirmation.
- Rules or examples that allow a one-line plan stub to satisfy a planning gate before asking for approval.
- Rules or examples that let an agent claim source-of-truth context cannot resolve next work without naming the exact artifacts inspected and what each said.
- Review caps that allow shipping known Critical/P1 defects.
- Plan-review loops that continue past the hard cap of four rounds against one source-of-truth plan instead of splitting it (or finalizing bound evidence that is clean and current), or that stop to ask the operator to authorize a round 3-4 instead of self-authorizing it with a recorded `--exception-note`.
- Plan-review blocker responses that ask the human operator whether to work through findings, accept unverified state, switch tasks, scope the plan down, park the task, choose a path, or answer `Which?` when the convergence rule or reviewer findings already identify focus-transfer as the safe next action.
- New-project or default-stack rules that allow Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase, or another cloud/hosting platform when the adapter is AWS-only or lacks explicit `technologyStack` approval.
- AWS-approved deployment rules or examples that ask for SSH keys, stop on missing SSH credentials, or invent alternate deploy credentials before checking `aws --version` and `aws sts get-caller-identity` or the adapter-declared AWS identity command/profile.
- Process authority stored only in memory.
- RCA or decision-trace patterns that cite Open Brain, Claude memories, local memories, or feedback-memory files as "what the rule says" instead of citing canonical methodology, a generated adapter, or a methodology skill.
- RCA response patterns that write memory notes before writing, validating, and publishing the RCA artifact.
- RCA-shaped chat responses that do not reference both the lane-local `.ai-runs/<utc>-methodology-regression-rca.md` artifact and the pushed `methodology-rca-archive` copy.
- Host skill registry failures such as `Unknown skill` treated as blockers when the file-backed methodology skill exists in the methodology checkout.
- Plan-finalization paths that bypass `tautline plan-finalization-precheck`, including `ExitPlanMode`, execution packet creation, ready-for-development marking, plan-only PR push, approval-to-implement prompts, or implementation start.
- Plan-review claims backed only by ignored lane-local logs, mtime, chat prose, or a freehand `Cross-Model Review Evidence` section instead of a tracked `.plan-reviews/` manifest written by `run-plan-review` or `finalize-plan-review`.
- Memory notes that describe process but have no matching canonical/adapter/skill rule; these must be converted into methodology changes or tombstoned as non-authoritative history.
- Memory writes that store process rules, gates, caps, review procedures, or escape hatches, instead of filing framework intake and pointing at the resulting artifact.
- Rules or examples that broad-load Markdown trees, all plans, archive folders, or `.ai-*` state instead of using configured context indexes.
- Archive or historical docs treated as current process, scope, execution authority, or next-work authority.
- Workflows that create, complete, move, or archive Markdown artifacts without updating the relevant context index.
- Projects with many Markdown artifacts but no context index, unclassified tracked Markdown, oversized index, or missing historical header.
- Session journal artifacts committed to `main`, treated as product docs/process authority, loaded during normal startup, or left lane-local without publish-blocker evidence.
- Session summaries, milestone summaries, queued-delivery summaries, handoff-for-review, or completed execution packets that omit the continuity refresh and session journal publish/pend step.
- Status reports that identify a concrete next milestone, missing spec, or planning gap without starting the source-of-truth planning/review workflow in the same turn.
- Boundary summaries for delivery, PR, milestone, goal, session, or handoff-for-review events that omit the plain-language outcome/current state or next action, or put technical labels before plain meaning.
- Rules or examples that think only in milestones/PRs when a substantial multi-milestone or overnight request should create a source-of-truth goal plan and `.ai-work/GOAL_RUN.json`.
- Claude `/goal` guidance treated as the source of truth instead of a session-scoped accelerator backed by the generic goal ledger and source-of-truth goal plan.
- Active automations that use an active development lane as scratch space.
- Claude/Codex rule files that duplicate large policy blocks and drift.
