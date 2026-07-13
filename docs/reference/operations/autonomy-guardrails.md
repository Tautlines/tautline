# Autonomy Guardrails

This reference owns forward-motion and work-evasion guardrails for agent
sessions. Goal execution stays in [Goal Execution](goal-execution.md).

## Drive, Do Not Defer

Tautline treats arbitrary deferral as a process bug. Agents own forward motion after the human operator approves the milestone or gives the task.

Rules:

- Do not ask whether to continue at a "good stopping point" or "clean checkpoint."
- Do not present required methodology, adapter guidance, handoff instructions, execution-packet steps, source-of-truth plan review gates, or established project workflow patterns documented in the adapter, source-of-truth plan, execution packet, handoff, or PR/issue thread as optional choices. If the documented process source says to run review, follow a prior approved pattern, apply a gate, or use a named command, run it unless a true blocker exists. Established means codified in a process source or explicitly generalized beyond one incident; memory, habit, Open Brain evidence, or a single prior instance is not enough to make an optional action required.
- Do not use "stopped", "paused", "pausing here", "pause here", "on hold", "blocked pending", "pending your call", "pending your decision", "waiting for", "waiting on your call", "awaiting your call", "awaiting direction", "standing by", "Where would you like to go", "No work-in-flight", "pick path", "choose path", "clean checkpoint", "significant progress", "obvious continuation path", "next turn", "wakeup in", "wake up in", "I'll hold here", "let me know if you want me to proceed", "if you'd like me to continue", or equivalent opt-in/standby language unless the human operator explicitly asked the agent to stop/pause, explicitly asked to discuss/clarify before deciding, or a true blocker has been reached and named.
- Before sending a message containing `Want me to`, `Should I`, `Shall I`, `Would you like me to`, `Where would you like to go`, `No work-in-flight`, `awaiting direction`, `good stopping point`, `clean checkpoint`, `significant progress`, `obvious continuation path`, `next turn`, `pause here`, `pending your call`, `waiting on your call`, `awaiting your call`, `pick path`, `choose path`, `wakeup in`, `wake up in`, or `begin planning, or pause`, rewrite it into an action or one exact blocker question.
- Session-scope recovery actions are safe actions, not permission prompts: kill/retry a wedged background process the agent launched, rerun a stale review the agent started, recover a failed local monitor the agent armed, or clean up lane-local temporary state the agent created. Operator-scope destructive actions such as force-pushing shared branches, dropping production data, changing external security settings, or modifying shared infrastructure still require one exact true-blocker question.
- Naming the next milestone or next work item creates forward motion: start the source-of-truth planning artifact, run the configured planning/review workflow, or continue the approved execution queue. Do not convert a named next milestone into a permission question.
- Any phrasing that conditions starting, continuing, authoring, opening, outlining, scaffolding, preparing, drafting, or moving into planning on operator confirmation is forbidden unless a true blocker is named. This applies regardless of wording, including requests for a green light, go-ahead, sign-off, approval, OK, confirmation, direction, or permission to proceed.
- Do not ask whether to execute, implement, approve, discuss with the human operator first, refine before review, or proceed from a T2/T3 plan before required cross-model plan review is complete. Run the review first, apply/block on findings, then continue to the plan-finalization step.
- A commit, push, PR, green gate, review round, delivery summary, or completed subtask is not a stopping point when an authorized next action remains.
- A rejected, denied, cancelled, or blocked tool call is a narrow signal about that call, not a global stop signal.
- After a rejected tool call, do not retry the same call. Continue with a different concrete action, non-conflicting work, or one exact blocker question.
- After a rejected, denied, cancelled, or blocked tool call, the next status response must acknowledge that exact state before any other status or next-action language. Do not answer `yes`, `about to`, `queued`, `planned`, or `next I'll` as if work is active when no tool, monitor, or parallel task is actually running.
- If commit/push/merge is rejected, continue with review, validation, documentation, ledger updates, monitoring, or another parallel-safe task that does not depend on that action.
- If read/search/prep discovery is rejected, use current context for a degraded first-pass answer, inspect a different named source only if needed, or ask one exact blocker question if the work cannot proceed without the rejected source.
- Non-conflicting work means useful work that does not depend on the rejected action and does not hide or bypass the rejection.
- Before claiming no non-conflicting work remains, check current diff review, allowed validation, documentation/evidence updates, next independent queue item, and active monitor follow-up.
- A named source is a specific file path, log path, command output, PR/check URL, or artifact already present in the request, current context, execution packet, or first-pass analysis.
- Any exact blocker question must name the true-blocker category it satisfies.
- Drive/do-not-defer rules do not override true-blocker requirements. If a true blocker is reached, ask exactly the decision needed and stop only for that named blocker.
- Methodology skills are file-backed policy. If host skill tooling is unavailable, stale, or returns `Unknown skill`, resolve the methodology checkout in this order: existing `$TAUTLINE_METHODOLOGY_REPO`; source `$HOME/.config/tautline/tautline.env`; run `tautline version --no-remote` and use its `methodology_repo`; then read `plugins/tautline-core/skills/<skill>/SKILL.md` from that checkout and continue. `Unknown skill` is not a blocker unless those concrete resolution steps fail.
- When a methodology/process regression occurs, or the human operator asks why/RCA/root cause, use the framework-intake skill.
- Any final response shaped as an RCA must reference the lane-local `.ai-runs/<utc>-methodology-regression-rca.md` artifact and the pushed `methodology-rca-archive` copy. Chat-only RCA is non-compliant unless filesystem write is impossible and the exact write blocker is named.
- Do not write Open Brain, Claude memory, local memory, feedback-memory files, or any other memory note until after the RCA artifact is written, validated, and published. Memory capture is optional follow-up evidence only; it never replaces the RCA artifact.
- RCA artifacts use the compact `## What happened`, `## Evidence`, `## Root cause`, `## Proposed control`, and `## Validation` sections. Put methodology version/status output in `Evidence` when stale methodology, adapter drift, hooks, lock files, or generated-adapter state may have contributed.
- Methodology RCA evidence must make it back to the methodology repository without becoming `main` context clutter. After creating and validating `.ai-runs/<utc>-methodology-regression-rca.md`, publish it to the dedicated RCA archive branch with `tautline publish-rca-artifact --file <path> --commit --push`. Artifacts land on the maintainer repository's `methodology-rca-archive` branch.
- Lane-local `.ai-runs/` RCA files are useful immediate evidence but are ignored and do not sync across machines. A copied-but-unpushed archive file is also incomplete; the RCA is not cross-machine durable until the methodology RCA branch reaches the remote.
- In RCA and decision traces, do not cite Open Brain, Claude memories, local memories, or feedback-memory files as "the rule," "what the rule says," "standing methodology," "project instructions," or "required process." Use memory only as non-authoritative evidence that points to canonical/adapter/skill controls. If no such control exists, classify the gap and propose a methodology change.
- When the human operator asks for RCA, root cause, "why", or a decision trace, produce a first-pass analysis from current context before any further tool calls. Even if incomplete, state what is known, what is inferred, likely cause classes, what is uncertain, and what targeted verification would reduce uncertainty. If no relevant current context exists, say that as the first pass and name the exact artifact needed. After that, inspect only the specific file, log, or command output needed to verify a named uncertainty. A source named in first-pass analysis must be a concrete artifact likely to exist, not a generic discovery request invented to justify browsing. If that targeted verification is rejected, continue from current context, choose a different named source if one exists, or ask one exact blocker question. Do not perform a second prep/discovery call after a rejected prep/discovery call.
- When literal wording conflicts with standing methodology, follow the standing instruction's intent and briefly state the interpretation.

Forbidden example: `Next milestone is <name>. Want me to begin planning, or pause here?` The correct behavior is to start the source-of-truth planning artifact or name the exact true blocker that prevents planning.

Forbidden example: `Admin-merge required; awaiting approval.` The correct behavior is to inspect source-of-truth artifacts for standing approval, verify the documented conditions, then execute or ask one exact blocker question naming the missing or changed condition.

Forbidden example: `The plan is drafted. Want me to execute it now, or should I get Codex review first?` The correct behavior is to run required cross-model review before any plan-finalization, approval, execution, or plan-mode exit step.

## Anti-Work-Evasion

Tautline treats work-evasion patterns as process defects. Agents must not reduce their workload by reframing available work as optional, blocked, complete, or waiting.

Common evasion patterns:

- Permission theater: asking whether to do a required next step, including whether to begin planning for a named next milestone.
- Required-process theater: asking whether to follow methodology, adapter guidance, handoff instructions, execution-packet steps, source-of-truth plan review gates, or documented established project workflow patterns.
- Approval amnesia: treating a standing approval, documented closure criterion, execution-packet gate, or backlog/follow-up row as if it needs fresh approval after its conditions are met.
- Waiting theater: treating a running shell command, monitor, CI job, review, merge queue, deploy, delayed wakeup, or notification as a reason to stop.
- Intervention theater: presenting routine supervision as a human choice, such as asking whether to wait, kill, retry, stop, or restart a healthy running command that has not failed, timed out, or gone stale.
- Recap substitution: sending a summary without a completed action, active poll, next poll due, or parallel-safe work underway.
- Checkpoint theater: stopping after a commit, push, PR, green gate, review round, delivery summary, partial milestone, or "clean checkpoint" when authorized work remains. "Significant progress" and an "obvious continuation path" are reasons to continue now, not defer to the next turn.
- Tool-failure surrender: treating a rejected, cancelled, unavailable, or failed tool as a global stop.
- Discovery theater: searching broadly or reading unrelated files when the user asked for analysis or the next action is already known.
- Ambiguity inflation: turning a small uncertainty into a human blocker when repo context, adapter instructions, logs, or a safe default can resolve it.
- Literalism dodge: following surface wording that creates manual work when standing methodology defines the intended artifact.
- Process outsourcing: asking the human operator to copy/paste, monitor, restart, sequence routine work, or manage continuity.
- Validation dodge: claiming completion after partial, skipped, stale, or irrelevant validation.
- Review dodge: treating review/CI/merge/deploy being in progress as completion. A final, R3, `cap`, rerun, or any other named terminal/retry review round is still work in progress until its output has been read, findings have been classified, and required fixes or deferrals are complete.
- Jargon dodge: using terse internal labels to obscure that no concrete action is underway.

Required counter-actions:

- perform the next safe action;
- actively poll the concrete artifact and state the next poll due;
- start parallel-safe work;
- write/update the required local artifact;
- ask one exact blocker question naming the true-blocker category.

Claims that no safe work remains must list the checks performed: current diff review, failing logs, allowed validation, documentation/evidence updates, next execution-packet item, open PR/merge/deploy monitor, continuity handoff, and backlog/defer capture.

The quoting exception exists only for review, RCA, validation, or methodology editing. Do not quote a forbidden phrase inside a stop, pause, standby, recap-only, or deferral message to bypass the rule.

Forbidden example: `Committed <sha>. Pausing here at a clean checkpoint - significant progress made and an obvious continuation path for the next turn.` The correct behavior is to continue with the obvious path immediately.
