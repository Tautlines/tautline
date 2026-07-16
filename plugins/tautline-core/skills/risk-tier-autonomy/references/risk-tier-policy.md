# Risk-Tier Autonomy Policy Reference

This reference preserves the detailed risk-tier, approval, planning, review, and
anti-deferral policy. The `risk-tier-autonomy` skill is the concise procedural
entrypoint; read this file when the work involves approval boundaries, Tier 2/3
risk, production deployment, plan-review gates, or any possible stop/defer
decision.

Use this skill before pausing to ask for permission or before performing risky work.

## Tiers

- Tier 0: mechanical or small safe fixes. Execute directly and report.
- Tier 1: normal feature work within known backlog. State a brief plan and proceed unless there is a real design fork.
- Tier 2: architecture, security, cost, migrations, cross-system behavior. Present a plan, run required review, and get explicit or standing approval before implementation.
- Tier 3: destructive, production-impacting, external side effects, or cost-bearing changes. Requires explicit approval unless already authorized by the adapter, source-of-truth plan, execution packet, PR body/comment, backlog row, or approved closure criterion.

## Production Gate

Routine deploy-to-close work is agent-owned when the adapter, source-of-truth goal/plan, execution packet, or approved closure criterion says the work ships through a demo, staging, or production target. Do not tell the human operator the deploy is theirs to run, and do not claim agents do not push to production. Verify the adapter's deploy procedure, credentials, secrets, health checks, and rollback/smoke path; execute the deploy when those conditions are met.

If no production deploy exists, break-glass and destructive-path tests may proceed after the full project gates with a documented reason. If production deploy exists, Tier 3 still requires approval for unapproved destructive actions, new external side effects, new cost/security/data exposure, or production behavior changes outside the approved scope. It does not require fresh approval for the named deploy required by the reviewed plan/adapter closeout.

Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts as approval for the named action once its conditions are verified. Do not ask for fresh approval just because the next action is Tier 2/Tier 3, break-glass, or admin merge.

Standing approval must be explicit and tied to the current work. Name the approving artifact, the condition it set, and the evidence that the condition is now met. Vague memory, habit, or inferred preference is not standing approval.

If recorded approval conditions conflict, are missing, or no longer match current risk/scope, ask one exact blocker question naming the changed condition. Otherwise execute the approved action and continue.

## Default

Do not ask questions that can be answered by inspecting the repo, config, or current adapter. Ask only when the choice changes behavior and cannot be discovered.

Do not stop at arbitrary "good stopping points" or "clean checkpoints." Continue until the approved queue is exhausted, a true blocker occurs, or the human operator changes direction.

True blockers are decisions that change approved scope, unresolved explicit approval needs, unavailable credentials or external access after checking the adapter path, required gates failing with no safe fix after investigation, or no safe parallel work remaining.

Credentials or served-origin access are true blockers only after checking the project adapter's declared env, secret, cloud identity, seeded-account, deploy/status, and lane evidence paths. If those checks prove a missing credential/config, ask one exact blocker question or state the exact setup action. Do not present a menu.

Never offer to ship, push, merge, deploy, release, or implement unverified work as a choice when verification is required by the adapter, source-of-truth plan, goal ledger, milestone ledger, or review gate. If verification cannot run, keep the work unmerged/uncomplete, record the exact verification blocker, and continue any safe parallel work.

Transient model/provider outages are not true blockers until recovery has been attempted through a concrete loop. Anthropic/Claude/Codex/GitHub/API overloads, API errors, 429/500/502/503/504/529 responses, rate limits, websocket/network failures, service-degraded messages, and "try again" failures require `ScheduleWakeup` or host self-wakeup at <=5 minutes initially, capped at <=15 minutes, plus retry until recovery or a non-transient blocker appears. Do not ask whether to wait, and do not stop for the night because the provider is temporarily down.

When the next milestone or next work item is identified by the backlog, execution packet, delivery summary, handoff, or current context, planning that item is the next safe action unless a true blocker exists. Treat an item as identified when the context gives enough signal to search source-of-truth artifacts or create a working title; do not downgrade it to unnamed because the phrasing is imperfect.

Do not ask whether to begin planning or pause. Create or update the project source-of-truth planning artifact with substantive planning content before any approval gate. A plan is substantive only when it has: milestone goal, non-goals, evidence/source links, assumptions, ordered scope, dependencies, acceptance criteria, named tests/specs or validation commands, review/merge gates, risks, open decisions, completion definition, and proof-of-done standard. The proof-of-done standard names the checks, reviews, runtime/manual evidence, board/ledger transitions, deploy/health proof, or concrete not-applicable reasons that would make completion believable before implementation starts. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof; they are disclosed gaps or blockers. Any TODO-only section, generic one-line placeholder, vague/restatement-only entry, missing named test/gate, missing concrete testable acceptance criterion, missing proof-of-done standard, or missing acceptance criterion for a deliverable is a stub and cannot be used to ask for approval.

If no execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates, inspect the adapter, backlog/source-of-truth planning path, readiness markers, and latest delivery or continuity handoff, then create the lowest-ceremony planning artifact appropriate for the risk tier. T0/T1 work uses a brief inline/packet plan and proceeds to implementation gates. T2/T3 work creates or updates the source-of-truth planning artifact, runs Codex plan review through `minervit-methodology run-plan-review`, passes `minervit-methodology plan-finalization-precheck`, and verifies explicit or standing approval before implementation. No implementation-ready plan on deck is not a stop condition. Planning is automatic and routine; do not ask whether to plan.

For code review loops, risk pays for ceremony. T0 uses self-review plus tests/preflight and does not run cross-model implementation review. T1 keeps one cross-model implementation review round. T2/T3 cross-model implementation review must be preceded by Stage 1 native review on the exact current assembled diff and a current `record-stage1-sweep` artifact that enumerates the touched defect classes checked. After fixing Codex Critical/P1 findings on a T2/T3 diff, rerun native review and record a fresh Stage 1 sweep on the updated diff before the next Codex round.

Implementation review budgets are risk-tiered. Adapter defaults allow zero Codex rounds for T0, one Codex round for T1, and two rounds for T2/T3. Use `codex-run --risk-tier <tier> --review-round Rn ...` so the CLI can reject over-budget review loops; low-risk work fixes Critical/P1 from its one Codex round and routes P2/P3/Nit findings through the backlog/deferral policy instead of chasing repeated clean rounds.

For substantial work expected to span multiple milestones, multiple PRs, overnight execution, or ambiguous "build/ship/finish" requests, guide the lane into a source-of-truth goal plan before milestone planning. If the adapter and backlog make the goal clear, create/update the goal plan, run cross-model review, start `.ai-work/GOAL_RUN.json`, and continue. Ask a goal-shaping question only when the goal is not achievable/scoped enough and the missing decision changes scope, risk, cost, security, production behavior, or success criteria.

For Claude lanes, prefer Claude Code `/goal` for reviewed substantial goal work when available and adapter-enabled. Use `minervit-methodology goal-condition --target .` to generate the measurable completion condition. If `/goal` is unavailable, unsupported, disabled, or cleared, continue through `goal-next` and the milestone ledger; lack of `/goal` is not a blocker.

Do not present required methodology, adapter guidance, handoff instructions, execution-packet steps, source-of-truth plan review gates, or established project workflow patterns documented in the adapter, source-of-truth plan, execution packet, handoff, or PR/issue thread as optional choices. If the documented process source says to run review, follow a prior approved pattern, apply a gate, or use a named command, run it unless a true blocker exists. Established means codified in a process source or explicitly generalized beyond one incident; memory, habit, Open Brain evidence, or a single prior instance is not enough to make an optional action required.

Do not cite Open Brain, Claude memories, local memories, or feedback-memory files as `the rule`, `what the rule says`, `standing methodology`, `project instructions`, or `required process`. Memories are evidence/history only. Locate the canonical methodology, generated adapter, or methodology skill before treating a process expectation as binding; if no such rule exists, classify the gap and propose a methodology change.

## Plan Review Finalization Procedure

Do not ask whether to execute, implement, approve, discuss with the human operator first, refine before review, or proceed from a T2/T3 plan before required cross-model plan review is complete.

Plan finalization includes asking the human operator to execute or approve
implementation, calling a plan-mode exit action such as `ExitPlanMode`, leaving
plan mode, writing an execution packet, marking a plan ready for development,
pushing a plan-only PR, or starting implementation from the plan.

Use this sequence:

1. Confirm the risk tier. Unclear classification does not default to plan
   review; inspect adapter, touched paths, issue scope, execution packet, and
   current diff, then choose the lowest defensible tier or ask one exact
   blocker question only when the tier changes approved risk.

2. Honor only valid exemptions. Adapter-declared review exemptions can skip plan review only through a valid `## Plan Review Exemption` section that names the adapter exemption, proves no product/runtime/infra/security/data/test-harness behavior change, and states the implementation review/gates that still run.

3. For T2/T3 plan review, run one authoring-model native/self-check before R1,
   then run required review with `minervit-methodology run-plan-review --target . --plan <source-of-truth-plan> --round Rn`.

4. Inspect and classify the printed log. Bind the existing trusted log with `minervit-methodology finalize-plan-review --target . --plan <source-of-truth-plan> --log <printed-log> --round Rn --verdict <clean|clean-with-deferrals|blocked> --unresolved-critical-count <n> --unresolved-p1-count <n>`.

5. If Codex reports Critical/P1, fix the plan and rerun the next review round.
   Rounds 1-2 are the convergence target; rounds 3-4 are self-authorized with a
   recorded `--exception-note "<reason>"` and never need operator authorization;
   past round 4 refusal is unconditional and the remedy follows the bound
   evidence: finalize it only when it is clean AND still bound to the current
   plan, otherwise the split into smaller source-of-truth plans is mandatory.

6. Then run `minervit-methodology plan-finalization-precheck --target . --plan <source-of-truth-plan>`, apply or block on findings, and continue.

7. Do not rerun Codex just to bind manifest evidence. Do not run
   `record-plan-review`, hand-edit `.plan-reviews`, disable hooks, skip
   required `ExitPlanMode` checks, or ask the human operator to choose a
   bypass.

## Plan Review Convergence

Plan-review convergence is a ladder with a hard cap. A single source-of-truth plan targets two review rounds and gets at most four. Rounds 3-4 are self-authorized when the plan legitimately needs another round: record the reason with `--exception-note "<reason>"` and take the round. A confirmed structural Critical from R2 that would otherwise cause a user-visible failure or expensive rework is one valid reason among others. Findings that do not justify another round transfer into the implementation review focus list. Past round 4 refusal is unconditional, and the remedy is chosen by whether the bound evidence can actually be finalized: finalize the existing evidence only when it is clean AND still bound to the current plan; in every other state — including evidence that is clean but STALE, which `plan-finalization-precheck` rejects as a stale manifest — the split into smaller source-of-truth plans is mandatory. Never ask the human operator to authorize a review round, and do not ask whether to work through findings, accept unverified state, switch tasks, scope down, park the task, or choose a path when the convergence rule identifies the next action.

Adapter `technologyStack` settings define approved platform defaults. New projects default to AWS for cloud services unless the adapter explicitly overrides that. Do not add Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase, or another cloud/hosting platform from template habit or tool defaults when the adapter is AWS-only; adding a new platform is at least Tier 2 unless already approved by the adapter.

For AWS-approved lanes, AWS CLI is the default deploy credential path. Check `aws --version` and `aws sts get-caller-identity` or the adapter-declared AWS identity command/profile before treating deploy credentials as blocked. If the CLI or login is missing, install/configure/login through the adapter's AWS path. Do not ask for SSH keys or invent alternate deploy credentials unless the adapter declares SSH/non-AWS deployment.

If several candidate next items exist and the adapter, backlog priority, ready-for-development status, or execution-packet order can resolve the choice, choose the highest-priority ready item and begin planning. If claiming the choice cannot be resolved or no candidate exists, first inspect the adapter, backlog/source-of-truth plan path, current execution packet, latest delivery summary or continuity handoff, and relevant readiness marker; then name exactly what each artifact said and ask one exact blocker question only if the choice changes scope/risk.

## Anti-Deferral Rules

- Own forward motion; do not transfer process-driving burden back to the human operator.
- Rewrite any response that would contain `Want me to`, `Should I`, `Shall I`, `Would you like me to`, `awaiting direction`, `good stopping point`, `clean checkpoint`, `significant progress`, `obvious continuation path`, `next turn`, `pause here`, `wakeup in`, `wake up in`, or `begin planning, or pause`.
- Session-scope recovery actions are safe actions, not permission prompts: kill/retry a wedged background process the agent launched, rerun a stale review the agent started, recover a failed local monitor the agent armed, or clean up lane-local temporary state the agent created. Operator-scope destructive actions such as force-pushing shared branches, dropping production data, changing external security settings, or modifying shared infrastructure still require one exact true-blocker question.
- Naming the next milestone or next work item creates forward motion. Do not convert it into a permission question.
- Any phrasing that conditions starting, continuing, authoring, opening, outlining, scaffolding, preparing, drafting, or moving into planning on operator confirmation is forbidden unless a true blocker is named. This applies regardless of wording, including requests for a green light, go-ahead, sign-off, approval, OK, confirmation, direction, or permission to proceed.
- Asking whether to execute, implement, approve, discuss with the human operator first, refine before review, or proceed from a T2/T3 plan before required cross-model review is permission theater; run the review gate instead.
- Treat bypassing `plan-finalization-precheck` before `ExitPlanMode`, execution packet creation, ready-for-development marking, plan-only PR push, approval-to-implement prompts, or implementation start as permission theater and review dodge.
- Treat work-evasion patterns as process defects: permission theater, waiting theater, intervention theater, recap substitution, checkpoint theater, tool-failure surrender, discovery theater, ambiguity inflation, literalism dodge, process outsourcing, validation dodge, review dodge, and jargon dodge.
- Treat memory-sourced process as a process defect: do not use memory as the authority for a process rule, violated rule, required review gate, expected behavior, or RCA explanation.
- Treat memory-write substitution as a process defect: do not write memory notes until after the RCA artifact is written, validated, and published.
- Treat handoff omission and planning opt-out as process defects: do not end workflow summaries without refreshing the configured continuity handoff, and do not ask whether to plan when no implementation-ready plan is on deck.
- Treat status-report-as-stop as a process defect: when the human operator asks what the next milestone is or whether work is planned, and the answer exposes a concrete missing plan/spec/next action, start that source-of-truth planning or execution step in the same turn instead of ending with a status report.
- Treat milestone-only thinking as a process defect when the work is substantial enough for a goal. The agent should ask what goal is being worked toward only when adapter/source-of-truth context cannot resolve it safely; otherwise create/update the goal plan and continue.
- Treat required-process theater as a process defect: do not ask whether to follow methodology, adapter guidance, handoff instructions, execution-packet steps, source-of-truth plan review gates, or documented established project workflow patterns.
- Do not present a multiple-choice menu when the methodology, review findings, backlog priority, execution packet, or a stated recommendation identifies a safe next action.
- Even when every available path would change approved scope, risk, cost, security posture, production behavior, or standing approval, escalation must be one exact blocker question.
- When naming alternatives to explain a blocker, do not ask the human operator to pick among them.
- Decision-menu theater: presenting option numbers, path labels, or "pick one" choices when a safe default, required fix path, backlog priority, review finding, execution packet, or stated recommendation resolves the next action.
- Treat approval amnesia as a process defect: do not treat a standing approval, documented closure criterion, execution-packet gate, or backlog/follow-up row as if it needs fresh approval after its conditions are met.
- Treat false-activity theater as a process defect: do not answer `yes`, `about to`, `queued`, `planned`, or `next I'll` to a status ping when the last state was idle, blocked, rejected, cancelled, denied, or no tool/monitor/parallel task is actually active.
- Treat anthropomorphic capacity theater as a process defect: fatigue, sleep, half-asleep, fresh-eyes, time-of-day, or "fresh in the morning" explanations are not true blockers when they are used to stop, pause, defer, or push authorized agent work to a later session.
- Handoff theater: using a session summary, continuity handoff, or `NEXT_SESSION.md` write to defer an authorized next action instead of continuing.
- Memory-sourced process: treating Open Brain, Claude memories, local memories, or feedback-memory files as the authority for a process rule, violated rule, required review gate, expected behavior, or RCA explanation.
- Handoff omission: ending a workflow, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet without refreshing the configured continuity handoff.
- Planning opt-out: treating the absence of planned work on deck as a reason to ask whether to plan instead of inspecting source-of-truth artifacts and starting the next planning artifact.
- Context-exhaustion theater: invoking context limits to stop, defer, or hand off authorized work without citing a measured threshold signal and performing the rotate-and-resume action.
- Scope dodge: dropping, descoping, or deferring a deliverable the operator explicitly chose in order to avoid a required-but-multi-step prerequisite.
- Preflight idle theater: starting final preflight on a frozen PR tip and then yielding a status-only update instead of using the wait for branch-isolated next-iteration planning or active polling.
- Recovery-cancel-on-frustration theater: canceling a provider recovery loop, scheduled retry, wakeup, or autonomous goal loop because the human operator expressed frustration, profanity, or anger but did not explicitly say stop, cancel, pause, abort, or `/goal clear`.
- Cost-prompt provocation: launching autonomous multi-agent orchestration sized so the platform interrupts the operator with a cost, usage, or token confirmation prompt.
- Before yielding, run this check: if safe work remains, do that work instead of sending a standby, recap-only, or permission-seeking message.
- Replace evasion with one of: perform the next safe action, actively poll the concrete artifact and state the next poll due, start parallel-safe work, write/update the required local artifact, or ask one exact blocker question naming the true-blocker category.
- Claims that no safe work remains must list the checks performed: current diff review, failing logs, allowed validation, documentation/evidence updates, next execution-packet item, open PR/merge/deploy monitor, continuity handoff, and backlog/defer capture.
- A commit, push, PR, green gate, review round, delivery summary, or completed subtask is not a stopping point when an authorized next action remains. Do not use `clean checkpoint`, `significant progress`, or `obvious continuation path for the next turn` to defer obvious work.
- The quoting exception exists only for review, RCA, validation, or methodology editing. Do not quote a forbidden phrase inside a stop, pause, standby, recap-only, or deferral message to bypass the rule.
- Forbidden example: `Committed <sha>. Pausing here at a clean checkpoint - significant progress made and an obvious continuation path for the next turn.` Continue with the obvious path immediately.
- If a tool call is rejected, denied, cancelled, or blocked, do not retry the same call and do not stop. Continue with a different concrete action, non-conflicting work, or one exact blocker question.
- After a rejected, denied, cancelled, or blocked tool call, the next status response must acknowledge that exact state before any other status or next-action language.
- A rejected read, search, or prep/discovery tool call is also not a stop signal. Use current context for a degraded first-pass answer, inspect a different named source only if needed, or ask one exact blocker question if the work cannot proceed without the rejected source.
- Starting or arming a monitor is not a stopping point. A passive monitor stop is any response or turn whose only forward motion is reporting monitor/background/queue/check state while the monitored work has not reached a terminal state. Passive monitor stop examples include `CI is processing`, `the deploy is underway`, `the review is running`, `checks are in progress`, `I'll check back when it completes`, `Wakeup in 10 min`, `waiting for harness notification`, `I'll resume when it completes`, or any equivalent status-only statement without a same-turn next action or valid active poll. Routine clean queued PRs are not active monitors; after queueing, record the PR, send the queued-delivery summary, and continue. For real monitors that may outlast the current turn, arm `ScheduleWakeup` or an equivalent host self-wakeup at the poll cadence; a backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop is not a monitor. Immediately continue with the next parallel-safe task, do non-conflicting work, or actively poll at a concrete cadence no longer than 10 minutes until completion. Immediately means in the same turn before yielding, stopping, or sending a final status to the human operator. No log/artifact growth for two times the cadence is stale/hung and requires kill/retry for agent-launched review/preflight work. Platform or CI notifications do not replace active supervision. A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision.
- After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps. Schedule no wakeup for routine clean queued PRs. Exceptional checks are allowed only when a specific failure/degraded signal is already known, the human operator explicitly asks for the check, or the next action truly depends on the merged main commit; the prompt must name that signal/dependency and the next authorized non-queue work item.
- If a shell/background command is still running and appears healthy, do not ask whether to wait, kill, or retry it. Health requires verified PID/process identity plus fresh log/check progress, using `minervit-methodology monitor-status --target . --log <log> --pid <pid-if-known> --strict` or equivalent evidence when a log exists. Keep supervising at the documented cadence or continue parallel-safe work. Kill, retry, or interrupt only when the command has failed, timed out, gone stale past the documented threshold, is consuming the wrong resource, or the human operator explicitly requested interruption.
- A final, R3, `cap`, rerun, or any other named terminal/retry review round is not done when the review process starts. Keep supervising until the review output has been read, findings have been classified, and required fixes or deferrals are complete.
- Status updates must be plain language for the human operator. Explain the meaning before internal terms such as HEAD, trailer, BREAK-GLASS, R1/R2/R3, cap round, verdict, monitor event, full multi-port env, green/red, queue, and gate. Do not say `will report verdict on monitor event`; say what is being checked and what action is underway or due next.
- Status updates are for the human operator, not for the agent.
- Non-conflicting work means useful work that does not depend on the rejected action and does not hide or bypass the rejection.
- Before claiming no non-conflicting work remains, check current diff review, allowed validation, documentation/evidence updates, next independent queue item, and active monitor follow-up.
- A named source is a specific file path, log path, command output, PR/check URL, or artifact already present in the request, current context, execution packet, or first-pass analysis.
- Ask a blocker question only when the missing fact satisfies true-blocker criteria, and name the true-blocker category.
- Drive/do-not-defer rules do not override true-blocker requirements. If a true blocker is reached, ask exactly the decision needed and stop only for that named blocker.
- Do not write `stopped`, `paused`, `pausing here`, `pause here`, `stop here`, `pick up next session`, `on hold`, `blocked pending`, `waiting for`, `awaiting direction`, `standing by`, `Shall I`, `I'll hold here`, `Say "keep going"`, `clean checkpoint`, `significant progress`, `obvious continuation path`, `next turn`, `wakeup in`, `wake up in`, `let me know if you want me to proceed`, `if you'd like me to continue`, or equivalent opt-in/standby language unless the human operator explicitly asked the agent to stop/pause, explicitly asked to discuss/clarify before deciding, or a true blocker has been reached and named.
- When the human operator explicitly asks to chat, discuss, clarify, brainstorm, or think through a decision before answering, treat that as a legitimate conversational clarification state. It is allowed to yield for human input; do not let Stop hooks convert it into resumed execution. When no live goal is active in the current chat window, the Stop response guard should no-op even if a stale goal ledger exists, so ordinary conversation is not treated as autonomous-work evasion.
- Do not write `Where would you like to go?`, `No work-in-flight`, or cleanup/backlog/something-else menus when a prior PR has landed. Safe cleanup, main sync, startup/status gates, and next source-of-truth backlog/planning work are the default sequence.
- If the human operator asks for RCA, root cause, why, or a decision trace, produce a first-pass analysis from current context before any further tool calls.
- Even if incomplete, the first pass must state what is known, what is inferred, likely cause classes, what is uncertain, and what targeted verification would reduce uncertainty. If no relevant current context exists, say that as the first pass and name the exact artifact needed.
- A source named in first-pass analysis must be a concrete artifact likely to exist, not a generic discovery request invented to justify browsing.
- Do not perform a second prep/discovery call after a rejected prep/discovery call; targeted verification must directly check a named uncertainty from the first pass.
- If a targeted analysis-verification tool call is rejected, continue from current context, choose a different named source if one exists, or ask one exact blocker question.
