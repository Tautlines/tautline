# Delivery Summary Policy Reference

This reference keeps detailed operator progress, delivery-summary, ledger,
board, continuity, journal, context-rotation, and anti-stop policy behind the
concise `delivery-summary` skill entrypoint. It preserves the existing
behavior while making the skill easier to load during routine agent work.

Apply this policy whenever work is delivered for human review, including
completed implementation, PR creation, PR merge, monitor terminal success, batch
delivery progress, milestone completion, or an explicit request to summarize
what was built.

Any message that reports work landed or shipped is a delivery summary, even if
it is emitted as a monitor event, queue progress update, batch status update, or
brief status line.

Work-landed triggers include:

- a PR merged
- a PR queued for merge after clean local gates and review
- a batch item merged
- a deployment completed
- a direct-to-main change committed
- a release published
- a milestone or work packet completed

At a completed goal boundary, the summary must reflect the required closeout
sequence: reviewed work committed, pushed to the configured origin/base branch,
adapter-required deploy executed and verified, required iteration review
run/published when enabled, continuity refreshed, session journal handled, and
next goal/milestone transition started when authorized. Do not turn routine
push, deploy, or iteration-review delivery of reviewed work into a permission
question.

For a provider-backed lane, the board must be reconciled at every delivery / queued-delivery boundary, not only at `git push`. Run
`minervit-methodology backlog-provider-board-check --target .` at the boundary
and act on its findings: every customer-facing issue created this session must
be a board item with an Item Type and a current `Status` before the summary is
complete - `gh issue create` alone does not place it on the board. A
`backlog_provider_board_unplaced_warn` for a customer-facing issue means the
delivery boundary is not done; place the issue (`backlog-provider-export ...`
or `gh project item-add`) first. Tech-debt/internal issues stay off the board.

If a delivery-ops announcement happens before the dev/staging deploy is
actually live, say that plainly. When adapter deployment notifications are
enabled, the deploy/build pipeline must produce the separate ready-to-review
evidence after live-site health checks pass. Do not present an AI-session or
manual post as equivalent to pipeline-owned evidence. Do not imply a stakeholder
announcement means the deploy has finished rolling forward.

When a goal is complete or no active goal exists, include the next goal
candidate from `minervit-methodology goal-kickoff-prompt --target .` or the
`next_goal_*` lines from `lane-start`/`methodology-status`: `next_goal_name`,
`next_goal_short_description`, and the copy/pasteable `next_goal_claude_prompt`.
Do not make the human operator ask for the next `/goal` wording.

Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session.

## Operator Progress Updates

Use operator progress updates whenever the human operator could otherwise lose
the thread: long implementation, plan review, code review, preflight,
deployment, monitor supervision, Claude `/goal` work, recovery, or any boundary
between PR, milestone, and goal work. Do not wait until the final delivery
summary to explain plain-language progress.

Emit a plain-language operator update:

- after startup gates and before starting the first substantive work item
- before any review, preflight, deploy, or test sequence expected to take more than 2 minutes
- at every review round, preflight phase, monitor poll, PR boundary, milestone transition, goal transition, context-rotation checkpoint, blocker, and recovery action
- at least every 5 minutes of wall-clock time during foreground or autonomous work when the host gives the agent a chance to speak
- immediately before any autonomous yield, heartbeat, or wakeup handoff

If the host is inside a single non-interruptible tool call, emit the update at
the next safe return point and include elapsed time.

Lead with the plain-language outcome or current state, then state the next
action. Add technical details only when they help the operator understand risk
or progress. Use headings or labels when they improve readability; they are not
required for ordinary updates, boundary summaries, or autonomous yields.

Put user, business, or operator meaning before internal labels. Explain why the
work matters, not only what command is running. State where the work is in the
goal -> milestone -> PR hierarchy when that matters, and whether progress is
active, blocked, recovering, or waiting on a specific external event. If percent
complete is useful but unknowable, say `percent unknown` and name the artifact
that must be updated to make it knowable.

Event logs, session journals, and continuity files do not substitute for
chat-visible operator updates. Those artifacts support audit and restart; the
operator still needs the live plain-language update.

Forbidden examples include technical-only boundary status such as `PR #327 merged; 5 of 6 batch items landed`, review/preflight status that only says `review running`, `checks green`, `monitor event`, `harness notification`, or `preflight in progress`, autonomous-yield status that only says `quiet`, `standing by`, `heartbeat due`, or `approval hold`, and a summary that omits the next action when authorized work remains. When a response guard blocks one of these, rewrite the update in plain language with the next action and continue the next methodology-authorized action.

## Required Shape

Start with the plain-language outcome and next action before technical details.
Use headings or labels only when they improve readability; they are not a
required schema.

Boundary summaries for delivery, PR, milestone, goal, session, and handoff-for-review events must lead with the plain-language outcome and next action.

When work is delivered for human review, start the completion summary with an executive summary before technical detail.

A complete delivery summary states what happened, why it matters, what
capability was unlocked, the current goal, milestone, PR/process position,
grounded percent complete or `percent unknown` with blocker, whether planned
work is ready, the recommended next action, and the supporting technical detail
needed to understand status or risk: branches, PRs, commits, tests, gates,
files, logs, deferred findings, risks, continuity, and local evidence.

The executive summary must cover:

- what was delivered, in plain English
- why it matters
- where the work stands in the overall process
- progress against the current goal and milestone, including an estimated percent of planned work complete
- whether additional planned work is ready for development
- the recommended next work item

Include a grounded progress narrative. Call out what capability was unlocked for users, admins, operators, or delivery velocity. Significant milestones should
sound consequential and worth noticing without obscuring current status,
validation state, or risk.

Ground goal percent complete in `.ai-work/GOAL_RUN.json` and the
source-of-truth goal plan when a goal exists. Ground milestone percent complete in the source-of-truth plan, execution packet, backlog checklist, or adapter-declared milestone scope. Use a defensible rounded estimate such as
`about 40%`, not false precision. If the plan is not decomposed enough for a
meaningful estimate, update the planning artifact or execution packet before
treating the summary as complete; if that write is blocked, state
`percent unknown`, name the exact blocker, and make the artifact update the next
action.

Use understandable lifecycle language for process position: planning,
implementation, local validation, review, PR open, merge queued, merged,
follow-up ready, or blocked on a named decision/gate.

When a PR has clean local tests, clean preflight, clean review, and is queued
for merge, summarize it immediately as queued for merge. Do not wait for GitHub
Actions, merge queue, deploy, or post-merge smoke to finish. Record the PR
reference and continue with the next authorized work. A clean queued PR leaves
active attention; startup gates in the next session catch main-health issues,
failed/blocked open PRs, and merge conflicts.

Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work. If `.ai-work/GOAL_RUN.json`
exists, run `minervit-methodology goal-next --target .` before `milestone-next`
and include goal progress in the summary. A queued-delivery or PR-completion summary is incomplete until the milestone ledger is advanced. Run
`minervit-methodology milestone-advance --target . --event pr-queued --pr <PR>`
after queueing, or the matching event for merge, abandonment, completion, or
blocking, then start the printed `next_action` in the same turn. If no
milestone ledger exists for approved milestone work, create it with
`milestone-start` instead of asking whether to continue.

Milestone continuation state lives in the lane-local milestone run ledger. PR boundaries are ledger transitions, not stop points.

For batch delivery updates, the executive summary must include:

- batch progress count
- what changed in plain English across landed items
- what remains in flight or blocked
- whether the remaining planned work is ready
- the recommended next action

A technical-only merge report is incomplete. Do not report only PR numbers,
branch names, invariant names, check names, or terse item labels when a
human-facing overview is required.

## Readiness For More Work

Do not say additional planned work is ready for development unless the next item
has:

- source-of-truth context
- clear dependencies
- acceptance criteria or execution-packet coverage
- no known true blocker

If it is not ready, name the missing decision, artifact, dependency, or gate.

## Technical Detail

After the executive summary, preserve technical delivery detail:

- files changed
- behavior changed
- tests and gates run
- proof-of-done evidence: what actually executed, what it covered, and which
  planned proof did not run
- whether early-warning smoke was started and its current state, or why it was covered/skipped
- queued PR status, or post-merge/deploy monitor status only if an exceptional monitor was required
- branch, commit, PR, merge, or deployment references
- risks and follow-ups
- skipped validation or residual uncertainty

## Proof Of Done

Completion claims require evidence that matches the work's real risk and blast
radius. Before calling work complete, compare the proof-of-done standard from
the source-of-truth plan or execution packet against what actually ran.

Valid proof can include executable tests that exercised the changed behavior,
behavior-spec status against the changed app, implementation review evidence,
manual/runtime checks with commands or artifacts, UI screenshots with manifests,
deploy health checks, board status transitions, goal/milestone ledger evidence,
or an adapter-approved not-applicable reason for a proof class that truly does
not apply.

`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof.
They can explain why proof is missing, why work is blocked, or what follow-up is
required, but they must not be counted as validation. If the intended proof did
not run, say that plainly. A source-of-truth plan may define a narrower
completion standard only when that narrower standard still names executable
proof for the behavior being claimed complete.

## Final Housekeeping

Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping before yielding
or ending the turn. The delivery summary is incomplete until the handoff exists
or an exact filesystem persistence blocker is named.

Every workflow completion, delivery summary, session summary, milestone summary,
queued-delivery summary, handoff-for-review, or completed execution packet must
also handle adapter-required local evidence through the owning ops skill when
that capability is enabled.

Every human-facing boundary summary must also log a compact event through
`minervit-methodology log-event --target .` unless the CLI command that caused
the boundary already logged it. Use adapter-approved event logging when enabled;
do not write generated event files directly.

The refreshed handoff must include the executive summary, process position, validation/review state, active or queued PRs, open risks, and either the exact
next action or the checks proving no authorized next work remains.

Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal. If continuing into the next authorized work after refreshing
the handoff, refresh the handoff again at the next workflow summary or before
any later yield/end-turn.

At every PR queued/completed boundary, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat, check visible context pressure when the host exposes it. If visible
context is at or above the adapter soft threshold, run context rotation after
the boundary summary, handoff, ledger update, and session journal: compact or
restart when available, then resume the active goal through startup gates. For
Claude Code, invoke `/compact` or the strongest host compact/restart path when
the agent turn can do that directly. If the host command is not invokable from
the current turn, leave the filesystem handoff and exact next startup action.
Do not ask whether to rotate or continue, do not ask the human operator to run
`/compact`, and do not use "what would you like" as a context-rotation fallback.

Do not turn the recommendation into a permission question. State the recommended
next step and continue if the methodology already authorizes continuing.

Do not turn a session summary, milestone summary, or continuity handoff into a
stop menu. If the summary names an authorized next action and no true blocker
exists, start that action in the same turn. Do not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session`. If an explicit
human stop request prevents continuing, write the handoff and state the next
action without opt-in language. Context exhaustion must match the continuity skill's context-running-out signals; when compact/restart is available, context
exhaustion requires rotation and resumption rather than a final stop.

Do not turn a session summary, milestone summary, or continuity handoff into a stop menu.

When the boundary also involves missing credentials, seeded accounts, TOTP,
served-origin access, or live verification access, report the adapter/source-of-truth
checks that were performed before naming a blocker. A summary must not offer
unverified shipping, unverified deployment, or human-selected bypass options.
Verification-required work remains uncomplete until verified or formally
deferred by policy.

Do not use "no work-in-flight" as a stop menu. If the prior PR is already landed
or queued and there is no active branch work, state that plainly, complete safe
local cleanup, sync main, run startup/status gates, and start the next
source-of-truth backlog item or required planning artifact. Do not ask the human operator to choose cleanup, backlog, or something else.

If the summary identifies the next milestone or next work item and no true
blocker exists, begin the source-of-truth planning artifact or next authorized
work. Do not ask whether to begin planning or pause. A planning artifact must be
substantive before any approval question: milestone goal, non-goals,
evidence/source links, assumptions, ordered scope, dependencies, acceptance
criteria, named tests/specs or validation commands, review/merge gates, risks,
open decisions, and completion definition. Any TODO-only section, generic
one-line placeholder, vague/restatement-only entry, missing named test/gate,
missing concrete testable acceptance criterion, or missing acceptance criterion
for a deliverable is a stub and cannot be used to ask for approval.

If the summary proves no implementation-ready tactical PR plan is on deck, do not ask whether to plan. After refreshing the continuity handoff and session
journal, inspect the adapter, backlog/source-of-truth planning path, readiness
markers, and latest delivery or continuity handoff, then create or update the
source-of-truth PR-level planning artifact for the highest-priority ready item,
run Codex plan review, and pass plan-finalization precheck before implementation
unless a true blocker prevents planning.

Forbidden example: `Next milestone is <name>. Want me to begin planning, or pause here?`
Start the source-of-truth planning artifact or name the exact true blocker that
prevents planning.

A delivery summary is not a license to stop when authorized work remains. Do not use `clean checkpoint`, `significant progress`, `obvious continuation path`, or `next turn` to defer work that is already authorized by the adapter, execution packet, or approved milestone.

A queued-delivery summary is incomplete unless it ends with one of two concrete outcomes:

- `Next work already underway: <specific action/artifact>` followed by starting that action in the same turn.
- `No authorized next work remains` followed by the exact checks performed across the execution packet, backlog/source-of-truth readiness, continuity handoff, open PR list, and defer/follow-up capture.

Statements such as `no more P1 followups`, `nothing else open`, `all planned
work complete`, or `no more open items` are not enough to stop. They are claims
that must be proven against the execution packet and source-of-truth backlog
before ending the turn.

When `.ai-work/MILESTONE_RUN.json` exists, the proof must also include
`minervit-methodology milestone-next --target .` showing milestone completion.
If it returns any executable `next_action`, start that action instead of ending
the workflow.

When `.ai-work/GOAL_RUN.json` exists, the proof must include
`minervit-methodology goal-next --target .` before milestone proof. If it
returns any executable `next_action`, start that action instead of ending the
workflow.
