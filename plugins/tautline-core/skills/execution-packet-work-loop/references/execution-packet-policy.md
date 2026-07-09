# Execution Packet Policy Reference

This reference keeps the detailed execution-packet, monitor, review, planning,
and provider-recovery policy behind the concise `execution-packet-work-loop`
skill entrypoint. It preserves the existing behavior while making the skill
easier to load during routine agent work.

Apply this policy after a milestone plan is approved, when converting that plan into lane-local tactical work, or when consuming an existing execution packet.

## Packet Path

Use the project adapter's lane-state execution packet path. The default is:

```text
.ai-work/EXECUTION_PACKET.md
```

## Required Packet Sections

The packet must include:

- milestone goal and non-goals
- ordered tactical queue
- dependencies and safe parallelism: for three or more tasks, apply the
  parallelization pass in `parallel-execution.md` (declared file scopes,
  ambiguity classes, wave grouping, serial integration) and record the waves
  here
- tests/specs required per item
- validation, review, and merge gates
- drop/defer rules
- true-blocker criteria
- completion definition
- proof-of-done standard: the concrete checks, reviews, runtime/manual evidence,
  board/ledger transitions, deploy/health proof, or not-applicable reasons that
  will prove this packet item is complete

## Work Loop

1. Run lane startup first.
2. If `.ai-work/GOAL_RUN.json` exists, run `minervit-methodology goal-next --target .` before milestone work and start its `next_action` unless it names a true blocker. Goal-first startup prevents milestone-only thinking when the work belongs to a larger objective.
3. Read the execution packet and ensure the milestone run ledger exists. Start or refresh it with `minervit-methodology milestone-start --target . --plan <source-of-truth-plan>` once the milestone plan is approved. The default ledger path is `.ai-work/MILESTONE_RUN.json`.
4. Before the first code edit, implementation command, PR worktree creation, or tactical subagent dispatch, state the benefit of the current item in plain English, give a realistic wall-clock estimate or range for the current session, and name the proof-of-done evidence that will be required before claiming completion. Ground the estimate in visible scope, expected gate/review time, prior similar runs, or stated uncertainty. Refresh this only when switching to materially different work: a different goal, milestone, source-of-truth plan, execution-packet item, PR branch/worktree, deployment target, or user-visible capability.
5. Early-warning smoke is no longer a standing gate. Run it only when the adapter, source-of-truth plan, issue, human operator, or a concrete risk signal asks for it. If a smoke monitor is already running for the same target, inspect the latest early-warning `.meta.json` and `.pid` files, compare command plus `cwd`, verify the PID is live, and poll the existing monitor instead of launching a duplicate.
6. Execute the first incomplete queue item without waiting for ambient smoke bookkeeping.
7. Run the item-specific tests and required project gates. Use `minervit-methodology lane-run --target . -- <command>` for local-service gates configured by the adapter. Count only checks that actually execute the changed behavior as proof. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps or blockers, not proof.
8. Record run evidence under `.ai-runs/`.
9. Before commit, review, push, or tactical subagent dispatch on an existing PR branch, run `minervit-methodology branch-liveness-check --target . --strict`; lane-local Git hooks also block commit/push when this fails. Before push, apply risk-tiered implementation review: T0 uses self-review plus tests/preflight only, T1 runs one cross-model review round, and T2/T3 records the Stage 1 native/Superpowers class sweep with `record-stage1-sweep` before Codex review through `codex-run --risk-tier T2 --native-review-note --stage1-sweep` or the matching T3 tier. Inspect/classify the review with `finalize-implementation-review`, include the tracked `.impl-reviews/` ledger in the PR commit, then run `minervit-methodology review-evidence-check --target . --strict` when the adapter enables pre-push evidence. After fixing Codex Critical/P1 findings, rerun the tier-appropriate review gate; T2/T3 diffs rerun native review and record a fresh Stage 1 sweep before the next Codex round. Subagent, per-item, or milestone-local reviews do not replace assembled-diff review evidence for the exact diff being pushed. A queued, auto-merge-enabled, merged, or closed PR branch is inactive; stop branch work and sync main.
10. Push, open PRs, enable merge queue, record queued PR references, send queued-delivery summaries, then run `minervit-methodology milestone-advance --target . --event pr-queued --pr <PR>` and start the printed `next_action`. Clean queued PRs leave active attention; do not watch GitHub Actions or merge queue by default.
11. After PR merge, PR abandonment, item completion, or item blocking, run `milestone-advance` with the matching event and start the printed `next_action`. If it returns a planning action, create the planning artifact required for the risk tier. T0/T1 work uses brief inline/packet planning; T2/T3 work creates/updates the source-of-truth PR plan, runs Codex plan review, passes `plan-finalization-precheck`, verifies explicit or standing approval, then implements.
12. Continue with the next parallel-safe item until the ledger proves the milestone complete or a true blocker occurs. If a goal ledger exists, advance it with `minervit-methodology goal-advance --target . --event milestone-complete --detail <proof>` when the milestone is complete, then run `goal-next` and start the returned next action. At each new tactical-iteration boundary, return to step 4 only when the next item is materially different; otherwise return to step 5.

## Human Interruption Policy

Do not stop at arbitrary "good stopping points" or "clean checkpoints." Interrupt the human operator only for true blockers: scope-changing decisions, unresolved explicit approval needs, unavailable credentials or external access after checking the adapter path, required gates failing with no safe fix after investigation, or no safe parallel work remaining.

Standing approval recorded in the execution packet, source-of-truth plan, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts as approval for the named action once its conditions are verified. Do not treat an authorized packet gate or closure criterion as needing fresh approval. Name the approving artifact, the condition it set, and the evidence that the condition is now met.

If the execution packet, source-of-truth plan, adapter, or approved closure criterion says the work ships by deploying to demo/staging/production, that deploy is part of the agent's closeout work. Do not hand it to the human operator. Check the adapter deploy command, credential path, required secrets, health checks, and smoke/rollback path; deploy when those conditions pass. Ask only one exact blocker question if a named credential/external access remains unavailable after following the adapter path or if the deploy would change unapproved scope, risk, cost, security, data, or production behavior.

When the adapter enables deployment notifications, the deploy is not fully
communicated until the live URL is verified and adapter-required delivery
notification evidence exists. Delivery-ops references own provider-specific
publisher, delivery marker, and pipeline evidence requirements; agent-session
fallbacks are not proof that the build process owns the notification.

When the next milestone or next work item is identified by the backlog, execution packet, delivery summary, handoff, or current context, planning that item is the next safe action unless a true blocker exists. Treat an item as identified when the context gives enough signal to search source-of-truth artifacts or create a working title; do not downgrade it to unnamed because the phrasing is imperfect.

Do not ask whether to begin planning or pause. Create or update the project source-of-truth planning artifact with substantive planning content before any approval gate. A plan is substantive only when it has: milestone goal, non-goals, evidence/source links, assumptions, ordered scope, dependencies, acceptance criteria, named tests/specs or validation commands, review/merge gates, risks, open decisions, and completion definition. Any TODO-only section, generic one-line placeholder, vague/restatement-only entry, missing named test/gate, missing concrete testable acceptance criterion, or missing acceptance criterion for a deliverable is a stub and cannot be used to ask for approval.

If the packet is exhausted and no goal ledger next action, handoff next action, or implementation-ready tactical PR plan is on deck, inspect the adapter, backlog/source-of-truth planning path, readiness markers, and latest delivery or continuity handoff. For substantial/multi-milestone work, create or update the source-of-truth goal plan first; for small work, create or update the PR-level planning artifact for the highest-priority ready item. Run Codex plan review and pass plan-finalization precheck before implementation. No implementation-ready plan on deck is not a stop condition. Planning is automatic and routine; do not ask whether to plan.

If no active goal exists and the next work is substantial or multi-milestone, create/update the source-of-truth goal plan first, run cross-model review, start the goal ledger, then create milestone/PR plans beneath it. Do not ask whether to use goal planning when the trigger is met.

If a milestone/status question reveals that the next milestone lacks a PR-level plan or execution spec, start that source-of-truth plan in the same turn. Do not end with a status report saying the plan or spec is missing.

If several candidate next items exist and the adapter, backlog priority, ready-for-development status, or execution-packet order can resolve the choice, choose the highest-priority ready item and begin planning. If claiming the choice cannot be resolved or no candidate exists, first inspect the adapter, backlog/source-of-truth plan path, current execution packet, latest delivery summary or continuity handoff, and relevant readiness marker; then name exactly what each artifact said and ask one exact blocker question only if the choice changes scope/risk.

At PR boundaries, `milestone-next` is the controller. Do not replace it with a summary, stop menu, or permission question. Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work. If no milestone ledger exists for approved milestone work, create it with `milestone-start`; a missing ledger is repairable lane state, not a reason to ask what to do next.

At goal boundaries, `goal-next` is the controller. Do not replace it with a milestone-only summary, stop menu, or permission question. A completed milestone is a transition inside the goal, not a reason to stop while the goal ledger returns executable work.

A rejected or cancelled commit, push, merge, or monitor command is not a stop signal. Continue with review, validation, documentation, ledger updates, monitoring, or another parallel-safe task that does not depend on the rejected action.

Early-warning smoke is an ambient confidence signal, not the final branch gate. Do not wait for it to pass before planning or implementation. Poll it at least every 10 minutes unless the adapter is stricter and record `timestamp | log path or command | observed state | next poll due`. Before commit, push, or merge, actively poll any running early-warning monitor in the same turn and proceed only if it is terminal-success or current healthy in-progress. Interrupt as P0 if it fails, times out, goes stale, uses the wrong target, or hits resource contention; halt the current item's commit, push, merge, and additional feature work until investigated or proven unrelated with named evidence. Do not wait for a clean queued PR to land just to create a later tactical-iteration boundary; if the next work does not depend on the merged main commit, continue.

A commit, push, PR, green gate, review round, delivery summary, or completed subtask is not a stopping point when an authorized next action remains. "Significant progress" and an "obvious continuation path" mean continue with that path now, not in the next turn.

Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff and publish a compact session journal as final housekeeping before yielding or ending the turn. The handoff must capture the exact next action or the checks proving no authorized next work remains.

Delivery summaries must lead with the plain-language outcome and next action, state progress against the current goal and milestone, and estimate percent of planned work complete. Use headings or labels only when they improve readability. If the plan or packet is not decomposed enough for a meaningful estimate, update it before treating the summary as complete; if that write is blocked, state `percent unknown`, name the exact blocker, and make the artifact update the next action.

The quoting exception exists only for review, RCA, validation, or methodology editing. Do not quote a forbidden phrase inside a stop, pause, standby, recap-only, or deferral message to bypass the rule.

Forbidden example: `Committed <sha>. Pausing here at a clean checkpoint - significant progress made and an obvious continuation path for the next turn.` Continue with the obvious path immediately.

Forbidden example: `Next milestone is <name>. Want me to begin planning, or pause here?` Start the source-of-truth planning artifact or name the exact true blocker that prevents planning.

Forbidden example: `Codex R3 running. Wakeup in 10 min.` Continue parallel-safe work immediately or actively poll the review log/process in the same turn and keep supervising until a terminal result or true blocker.

Treat work-evasion patterns as process defects: permission theater, waiting theater, intervention theater, recap substitution, checkpoint theater, tool-failure surrender, discovery theater, ambiguity inflation, literalism dodge, process outsourcing, validation dodge, review dodge, and jargon dodge. Before yielding, either perform the next safe action, actively poll the concrete artifact and state the next poll due, start parallel-safe work, write/update the required local artifact, or ask one exact blocker question naming the true-blocker category.

Status updates must be plain language for the human operator. Explain the meaning before internal terms such as HEAD, trailer, BREAK-GLASS, R1/R2/R3, cap round, verdict, monitor event, full multi-port env, green/red, queue, and gate. A valid status says what is happening, why it matters, and what concrete action is underway or due next.

Starting or arming a monitor is not a stopping point. A monitor is an alerting mechanism, not the next action. Do not end a turn with only `monitor is running`, `monitor watches`, `waiting on merge`, `waiting on checks`, `R2 running`, `R3 running`, `review running`, `wakeup in 10 min`, `waiting for harness notification`, `I'll resume when it completes`, or equivalent passive-monitor language. A passive monitor stop is any response or turn whose only forward motion is reporting monitor/background/queue/check state while the monitored work has not reached a terminal state. It is forbidden even if it avoids the listed phrases. Passive monitor stop examples include `CI is processing`, `the deploy is underway`, `the review is running`, `checks are in progress`, `I'll check back when it completes`, `Wakeup in 10 min`, or any equivalent status-only statement without a same-turn next action or valid active poll. Routine clean queued PRs are not active monitors; after queueing, record the PR and continue. After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps. Schedule no wakeup for routine clean queued PRs; exceptional checks require a known failure/degraded signal, explicit human request, or true dependency on merged main. For real monitors that may outlast the current turn, arm `ScheduleWakeup` or an equivalent host self-wakeup at the poll cadence. A backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop is not a monitor. Immediately start the next parallel-safe task, do non-conflicting work, or actively poll at a concrete cadence no longer than 10 minutes until completion. Immediately means in the same turn before yielding, stopping, or sending a final status to the human operator. A valid active poll must run or read a concrete monitor artifact and record `timestamp | command/artifact | observed state | next poll due`. No log/artifact growth for two times the cadence is stale/hung and requires kill/retry for agent-launched review/preflight work. Platform or CI notifications do not replace active supervision.

Transient provider/API failures are not packet completion and not permission to stop. Anthropic/Claude/Codex/GitHub/API overloads, API errors, 429/500/502/503/504/529 responses, rate limits, websocket/network failures, service-degraded messages, and "try again" failures require a provider recovery loop: arm `ScheduleWakeup` or host self-wakeup at an initial cadence no longer than 5 minutes, cap backoff at 15 minutes, preserve continuity and local evidence when safe, and retry until service recovers or the failure becomes a true blocker. If another packet item can advance without the failed provider, do that work while the retry loop runs.

For autonomous-loop yields, `Quiet.` and equivalent no-information replies are forbidden. Before any delayed wakeup, `ScheduleWakeup`, or host-equivalent heartbeat, enumerate open PR state, pending/unblocked tasks, and `.ai-continuity/NEXT_SESSION.md` scheduled/current work. If another lane item can advance without human operator input, advance it instead of yielding. A legitimate yield names the real state, true blocker, and concrete retry/poll/next action in plain language; fixed field labels are optional.

A final, R3, `cap`, rerun, or any other named terminal/retry review round is not done when the review process starts. Keep supervising until the review output has been read, findings have been classified, and required fixes or deferrals are complete. A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision.

If a shell/background command is still running and appears healthy, do not ask whether to wait, kill, or retry it. Keep supervising at the documented cadence or continue parallel-safe work. Kill, retry, or interrupt only when the command has failed, timed out, gone stale past the documented threshold, is consuming the wrong resource, or the human operator explicitly requested interruption.

Before claiming no non-conflicting work remains, check current diff review, allowed validation, documentation/evidence updates, next independent queue item, and active monitor follow-up. Ask a blocker question only when the missing fact satisfies true-blocker criteria, and name the true-blocker category.
