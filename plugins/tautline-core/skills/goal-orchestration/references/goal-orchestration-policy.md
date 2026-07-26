# Goal Orchestration Policy Reference

This reference keeps the detailed goal, provider-board, `/goal`, and closeout
policy behind the concise `goal-orchestration` skill entrypoint. It preserves
the existing behavior while making the skill easier to load during routine
agent work.

## When A Goal Is Required

Use this skill when work is substantial enough to need the hierarchy
`Goal -> Milestone -> PR / tactical item`, when startup finds an active
`.ai-work/GOAL_RUN.json`, when a milestone boundary may advance a larger goal,
or when a Claude lane should use `/goal`.

Create or update a source-of-truth goal plan before milestone planning when the
work is expected to span multiple milestones, multiple PRs, overnight execution,
or ambiguous "build", "ship", "finish", or "make this happen" requests.

Small single-PR work does not require a goal unless the adapter or human
operator asks for one.

When no active `.ai-work/GOAL_RUN.json` exists, or the only ledger is complete,
`lane-start`, `methodology-status`, and `goal-kickoff-prompt` must emit
`next_goal_name`, `next_goal_short_description`, `next_goal_source`,
`next_goal_status`, `next_goal_claude_prompt`, and `next_goal_next_action`. Use
that candidate instead of asking the human operator "what is the next goal?" If
startup cannot determine a candidate because an external backlog provider is
blocked, resolve the printed provider blocker first.

## Goal Plan Contract

A source-of-truth goal plan must include:

- desired outcome
- user, business, operator, or delivery benefit
- measurable success condition
- non-goals
- ordered milestones
- dependencies and safe parallelism
- risks and true-blocker criteria
- review gates
- validation proof required for completion
- completion criteria

Goal plans require cross-model review before execution unless the adapter
declares a valid exemption. If the plan is not reviewed, it is not
execution-ready.

## External Backlog Provider

When adapter `backlogProvider.enabled` is true, the external provider can decide
stakeholder-facing priority/status for adapter-declared goals, milestones, bugs,
or tasks. GitHub Projects is the first supported provider. Compatibility
`goalTracker` remains supported for existing adapters, but new adapters should
use `backlogProvider`.

When adapter `backlogProvider.completionUnit` is `provider-item`, the GitHub
issue/Project item is the completion unit. Repo plans, milestones, and optional
goal ledgers decompose and prove the work; they do not replace, outrank, or
obscure the active issue. In that mode, start from `backlog-provider-next`, keep
the issue and board current at every planning/PR/milestone/blocked/closeout
boundary, and use `next_work_item_*` output rather than treating the work as a
separate next goal.

Use:

```bash
tautline backlog-provider-status --target .
tautline backlog-provider-next --target .
tautline backlog-provider-sync --target . --item <id-or-url> --write
```

The `--write` sync claims the selected board item and any board-backed native
subtasks by moving them to the first adapter-approved active status, then writes
or refreshes the source-of-truth repo plan. Review that synced plan before implementation. In goal-mode
products, start or refresh the goal ledger before substantial implementation.
In provider-item mode, the synced issue/work-item plan is the source-of-truth
completion artifact; use an internal goal ledger only when it helps decompose
large work or an adapter-required review needs it. Do not execute directly from
a raw GitHub Project item.

Provider-backed board status is live operational state, not optional
commentary. In goal-mode products, `goal-start` and `goal-advance` keep mapped
GitHub Project items current: active work moves to the first adapter-approved
active status, completed goals/milestones move to the first done status, and
blocked/deferred milestones move to the blocked status. In provider-item mode,
the issue/work item itself must be current even when no goal ledger exists. A
milestone source plan should carry its own `## GitHub Project Source` mapping
when stakeholders track milestones as Project items. Free-text issue comments
do not replace the structured board `Status` field.

Every backlog item must LEAD with a plain-language business justification
before technical detail: `## What this delivers` (the capability/outcome in
plain language) and `## Why it matters` (the value to the customer/stakeholder
and why we care), then `## Technical detail`. Never write a board/backlog item
as a rote restatement of milestones or a pure-technical description with no
business context. `backlog-provider-export` refuses to create a board item
whose source repo item lacks both leading sections with real content, and leads
the exported body with them; `backlog-provider-board-check` and
`methodology-status` surface existing board items missing the lead as
non-blocking `backlog_provider_board_lead_warn` findings to rewrite over time.

The stakeholder board must be current at all times - no excuses, no deviations -
for every customer-facing item type (goals, milestones, features, bugs, tasks),
not just the active goal. Move an item to an active status when you start it and
to a done status when its issue/PR ships, even for standalone bug/feature work
between goals. Use only the adapter-configured statuses and ship straight to a
done status when the issue/PR lands: move active work to the configured active
status (for example `In progress`) and then directly to a done status - do NOT
stage work in a separate review/QA column even if the board has one. This is a
blocking gate, not advisory: `tautline backlog-provider-board-check
--target .` and `methodology-status --strict`/`--fail-on-drift` reconcile every
in-scope board item against its real issue/PR state. A closed/merged item must
be in a done status, an open item must not sit in a done status, any item in a
status the adapter does not enumerate is itself drift, and an open item that is
verified current lane work but is not in an active status is drift. The pre-push
hook runs the same check so customer-facing work cannot ship while the board is
stale. The only non-blocking case is genuine provider unavailability (`gh`
offline/unauthenticated), surfaced as a warning that re-blocks once connectivity
returns, so keep `gh` `project` scope authenticated.

The board-currency gate is scope-aware: the hard block is about verified current
lane work (the item the branch/PR closes, any changed source-of-truth plan/spec
mapped to a Project item, or the active ledger item when no branch/plan points
elsewhere), not an unrelated active goal ledger. If the active
`.ai-work/GOAL_RUN.json` has drifted from the initiative you are working (no
project link, or a different project link while the branch closes a tracked
item), `methodology-status` warns about it at session start and the push is NOT
blocked when the branch's own board item is current. Resolve the ledger early
with `goal-advance --event goal-complete` or `goal-start <plan>`, not as a
pre-push surprise. Planning counts as starting: when you draft an item's
milestone spec/plan, move that board item to the active status then.
Native GitHub sub-issues/subtasks that are also board items inherit the same
obligation: parent issue status is not a substitute for board-backed subtask
status. The normal claim path moves the selected board item plus those
board-backed native subtasks active in the same command. Later sanctioned parent
status moves reconcile board-backed subtasks too: open non-terminal subtasks
follow active/blocked/ready parent transitions, closed/merged subtasks follow
done transitions with the same verification evidence before the parent is marked
done, and an open board-backed subtask blocks marking the parent done. Subtask
issue/PR closure is independent of board Status: close or finish the subtask
through its own issue/PR path first, or update the subtask item directly when
that is the selected work item. A native subtask missing from the board blocks
parent Done because there is no subtask Status to reconcile.
`backlog-provider-active-check`, `backlog-provider-board-check`, and
`methodology-status` fail when a verified current-work item still sits in
`Backlog`/`Ready` and understates progress. `milestone-start` claims the mapped
plan's Project item active before saving the local milestone ledger; a
rate-limited/failed board mutation is a blocker for implementation, not a
reconciliation chore.

Moving a provider item to a done status requires verification evidence in the
linked issue/PR: `goal-advance --event milestone-complete|goal-complete` posts
the completion detail or milestone-run reference before changing Status, and
manual `backlog-provider-update` or compatibility `goal-tracker-update` done
moves require `--verification-evidence`, `--verification-evidence-file`, or
`--verification-evidence-url`; all of these paths post a `## Verification
Evidence` comment first. And filing a customer-facing bug is not done until it is
on the board: `gh issue create` alone does not place it there. Add it with an
Item Type and `Status`, or the board check warns
(`backlog_provider_board_unplaced_warn`).

For projects with existing repo backlog items, run:

```bash
tautline backlog-provider-migration-interview --target . --write
```

Walk the generated interview item by item. Present each candidate in plain
language and ask whether that specific goal/milestone/bug/task should be
exported to the external provider for stakeholder prioritization. Export only
interview-approved items:

```bash
tautline backlog-provider-export --target . --item-path <repo-plan.md> --type <goal|milestone|bug|task> --write
```

Do not bulk export all repo plans by default. Normal exports create real,
numbered repository issues in the adapter `repo`, add them to the configured
project, and link back to the repo source item. Board-only GitHub Project draft
items require explicit `--draft` and are not repo-visible tracker issues. Do
not overwrite stakeholder-authored external descriptions unless explicitly
instructed.

The board exists only and exclusively for customer-facing functionality and
customer-impacting bugs. It must never be cluttered with technical debt,
refactors, cleanup, internal/non-customer-facing bugs, CI/dependency chores, or
developer-experience/test-infrastructure work, which stay in the repo backlog.
`backlog-provider-export` enforces this: it refuses without an explicit
`--customer-facing` affirmation, and refuses a tech-debt/non-customer-facing
item even then unless `--customer-facing-justification "<concrete customer
impact>"` records why. Never relabel tech debt as customer-facing to slip it
onto the board; if it has no customer-facing impact, it does not belong there.

The board's order is the work order. `backlog-provider-next` and
`goal-tracker-next` pick the topmost workable ready item in the board's order.
The operator's ordering, not the priority tag, decides sequence
(`backlogProvider.workOrder: board`, the default; `priority` is an explicit
per-product opt-out that needs a `priorityField`). Board order comes from an
explicit numeric `orderField` when configured, else from the order GitHub
returns the project's items, so without an `orderField`, arrange the project's
item order to match intended sequence.

A lane may be assigned epics with `--epic <name>` (repeatable) or
`MINERVIT_LANE_EPICS`, plus an adapter `epicField`; the lane then works the top
board item within its assigned epics. Those epics are a hard scope boundary on
everything the lane considers: selection, what-next recommendations, planning,
and analysis. Without specific operator direction the lane must never consider,
recommend, surface, rank, or pull a board item from an epic it is not assigned,
even when the operator sets the ordering aside. Considering or proposing another
epic's work needs explicit operator direction that names that epic or lifts the
scope. If the assigned epics have no ready item, say so and stop for direction
rather than substituting another epic's item. With no epic assigned, the command
says `no epic assigned; defaulting to the top of the board stack` and takes the
board top.

## Lane Ledger

The lane-local goal ledger defaults to:

```text
.ai-work/GOAL_RUN.json
```

Start or refresh it with:

```bash
tautline goal-start --target . --goal <source-of-truth-goal-plan>
```

Read it before milestone state:

```bash
tautline goal-next --target .
```

Advance it at milestone boundaries:

```bash
tautline goal-advance --target . --event milestone-complete --detail "<validation proof>"
tautline goal-advance --target . --event milestone-deferred --reason "<policy deferral reason>"
tautline goal-advance --target . --event milestone-blocked --reason "<true blocker>"
tautline goal-advance --target . --event goal-complete --detail "<completion proof>" [--iteration-review-record <record>]
```

Do not mark a milestone complete without validation proof or a linked milestone
ledger. Proof must come from executed checks for the changed behavior;
`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps, not completion
proof. Do not defer a milestone without a policy deferral reason. When an
adapter enables delivery-ops closeout, the owning ops skill/reference defines
the required delivery marker before milestone or goal completion.

Before goal-complete, the lane adapter `sourceAdapterSha256` must match the
canonical source adapter. `lane-project()` enforces this on every lane command
(including `goal-advance`), so a drifted adapter - for example one whose
delivery settings diverged after render - blocks goal completion. If you see a
`sourceAdapterSha256` mismatch, diff canonical vs the lane's committed adapter
and any `minervit-local-rescue/*` ref, then re-render with
`render-adapters --json-only --write` before closing the goal. When delivery
ops are enabled, follow the owning ops skill/reference for any approved skip,
repeat-send, or delivery-marker requirements.

After `goal-advance --event goal-complete`, goal-mode lanes surface the printed
`next_goal_short_description` and copy/pasteable `next_goal_claude_prompt`.
Provider-item lanes surface the next provider item from `backlog-provider-next`
or `next_work_item_*` instead.

Do not stop at a PR or milestone boundary while `goal-next` returns executable
work.

If the source-of-truth goal plan names operator-input dependencies or true
blockers for a milestone, `goal-next`/`goal-status` should surface them before
plan-finalization begins. Dependency detection is intentionally narrow:
ordinary implementation words such as `input`, `fixture`, or `blocked` are not
enough by themselves. If the dependency is not already satisfied by lane
evidence, defer with `goal-advance --event milestone-deferred`; block only when
the dependency is confirmed unavailable or a hard true blocker before spending
Codex review rounds.

At PR queued/completed, milestone completion, goal boundary, workflow summary,
session summary, handoff-for-review, or long `/goal` heartbeat boundaries,
context rotation can be required by the adapter. Managed Claude startup sets
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in both the launcher env and Claude's
durable settings file so Claude Code keeps a safety margin while avoiding
half-context compaction churn. If visible context is at or above the soft threshold,
refresh continuity, handle the session journal, compact or restart if
available, then resume the same goal through `goal-condition` or `goal-next`. If
`/compact` or host restart is not invokable from the current agent turn, write
the evidence and state the exact fresh-session startup action instead. Context
rotation is not goal completion, not a terminal blocker, not a "productive
limit", and not a reason to ask whether to continue.

## Claude /goal Guidance

For Claude lanes, prefer Claude Code `/goal` for substantial reviewed goal work
when available and not disabled by the adapter.

Claude `/goal` is session-scoped and requires Claude Code `v2.1.139+`. Its
evaluator judges evidence surfaced in the conversation, not files/tools
independently. Therefore the agent must surface the proof commands, relevant
artifacts, and completion evidence in chat.

Generate the completion condition from the ledger:

```bash
tautline goal-condition --target .
```

The condition must include one measurable end state, proof commands/artifacts,
and relevant constraints.

During long Claude `/goal` runs, do not wait for final goal completion before
checking context pressure. Use the adapter heartbeat cadence and
`tautline context-rotation-check --target . --boundary
goal-heartbeat --context-percent <visible-percent> --context-percent-source
estimate` whenever the host exposes a percent and the lane reaches a safe
checkpoint. Pass `--context-percent-source host` only if the host literally
exposes a context-window counter; an estimate can recommend rotation but never
make it mandatory. When the check returns recommended or mandatory rotation,
refresh continuity, handle the journal, invoke `/compact` or the strongest host
compact/restart path when directly possible, and resume; if direct invocation
is unavailable, state the exact fresh-session startup action without opt-in
language. Do not explain that context exhaustion requires stopping.

Use the `delivery-summary` skill during long `/goal` runs. At each safe
heartbeat, PR boundary, milestone transition, review round, or at least every 5
minutes when the host gives the agent a chance to speak, lead with the
plain-language outcome or current state and the next action so the operator can
see goal/milestone/PR position without waiting for final goal completion.

If `/goal` is unavailable, unsupported, disabled, or cleared, continue through
`goal-next`, `milestone-next`, and the execution-packet work loop. Lack of
`/goal` is not a blocker.

For a goal plan that explicitly declares multi-session scope, or carries known
operator-input true blockers, the Claude `/goal` condition can be satisfied for
the current session by delivering an authorized per-session increment,
refreshing continuity, handling or queueing the session journal, and reaching
one of: goal complete, true blocker, or genuine scope boundary. Use explicit
words such as `multi-session`, `multiple sessions`, `overnight`, or `more than
one session` in the source goal plan when this clause should apply. This is not
permission to stop at an arbitrary clean PR or milestone boundary. Context
exhaustion by itself does not satisfy `/goal`; rotate context and resume the
same goal.

Goal-close owns the merge, not just the push. On a PR-based workflow without a
repository-mandated human review gate, the agent commits, pushes, opens the PR,
and queues it to merge (routine merge-queue or auto-merge per the adapter's merge
policy; never routine `--admin`). A clean PR queued with auto-merge is delivered
(`pr_queued` is terminal), so advance and move on without blocking on the async
merge; run any goal/plan/adapter-required deploy, iteration-review, and
delivery-marker closeout as the existing close sequence directs. No-remote/direct-to-main
adapters follow their configured delivery path, and a repository-mandated human
review gate (branch protection) is respected as the workflow. Ending goal-close at
`ready for your review/merge` for clean, gate-green, review-clean work the agent
CAN merge is forbidden work-evasion, the same class as stop-and-ask.

If a live goal hits credential or served-origin friction, run the
adapter-declared credential/origin discovery first. A missing credential/config
after those checks is one exact true blocker or setup action, not a
multiple-choice menu. Do not offer unverified shipping, deployment, or merge as
a way around required goal validation.

## Startup Order

After lane startup gates and pending session-journal publication:

1. If `.ai-work/GOAL_RUN.json` exists, run
   `tautline goal-next --target .`.
2. Start the returned `next_action` unless it names a true blocker.
3. Then run milestone status or `milestone-next` for the active milestone.
4. Then continue PR/tactical item work.

If no active goal exists and the next work is substantial, create or update the
source-of-truth goal plan before milestone planning. Do not ask whether to plan
when the adapter, backlog, handoff, or current context identifies a substantial
next goal.

After a context rotation restart, run startup gates first, then
`goal-condition` or `goal-next`, and continue the active goal. Do not ask
whether to resume.

## Completion Proof

A goal is complete only when all of the following support that conclusion:

- goal ledger
- milestone ledgers
- source-of-truth goal and milestone plans
- validation evidence
- open PR/branch state
- continuity handoff
- session journal

If any proof is missing, the next action is to produce that proof or continue
the next milestone. A milestone summary is not a goal completion summary unless
it includes goal progress and completion evidence.

## End-Of-Goal Boundary

When the planned/reviewed goal work is clean, close the goal through the
required sequence without asking for permission: commit the reviewed work; on a
PR-based workflow without a repository-mandated human review gate, push the head
branch, open the PR (head into the configured base branch), and queue it to merge
(routine merge-queue or auto-merge per the adapter's merge policy; never routine
`--admin`); no-remote/direct-to-main adapters push to the configured base branch
per their configured path and a
mandated human review gate is respected. Then deploy to the adapter-declared
demo/staging/production target when the goal/plan/adapter closeout requires it,
run adapter-required delivery-ops closeout when enabled, record the required
delivery marker, run `goal-advance --event goal-complete` with the required
proof artifacts, refresh continuity, handle local evidence, log the boundary
event, then continue through the next authorized goal or milestone transition. A
clean PR queued with auto-merge (or a routine push/deploy on a non-PR path) is
`Done = shipped`, not an operator-confirmation action, and ending at "ready for
your review/merge" is forbidden. Where a provider board is active, respect the
board-currency reconciliation: an item's board Status reaches `Done` when its PR
merges/closes (which the queued auto-merge does), so do not write `Done` against
an item whose PR is still `OPEN` -- let the merge close it. (A queued-terminal
board state that avoids this reconciliation lag is the deferred
METH-FU-POST-MERGE-CLOSEOUT-GATE engine work.) Do not tell the human operator the deploy or
merge is theirs to run; stop only for a named missing credential/config after
checking the adapter path, a failing required gate with no safe fix, or an
unapproved scope/risk/cost/security/data change.

A clean PR queued with auto-merge, or a routine push/deploy of reviewed work on a
non-PR path, is `Done = shipped`.
