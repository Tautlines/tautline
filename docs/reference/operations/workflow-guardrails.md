# Workflow Guardrails

This reference keeps detailed workflow-control rules out of the main operating
manual. These rules govern review, merge, background supervision, and memory
authority during active delivery work.

## Review And Merge Policy

High-level policy:

- Review before push for non-trivial code or process changes.
- Use native model review first.
- Use cross-model review before push/finalization.
- Before commit, review, push, or tactical subagent dispatch on an existing PR branch, verify current branch liveness with `minervit-methodology branch-liveness-check --target . --strict` or the adapter's equivalent PR-state check. Lane-local Git hooks installed by `lane-start` also block commit/push when the branch is inactive. A queued, auto-merge-enabled, merged, or closed PR branch is no longer active work; sync main and continue from the source-of-truth next item instead of spending review or implementation cycles on the inactive branch.
- Treat plan-mode exit, execution handoff, ready-for-development marking, plan-only PR pushes, implementation starts, and approval-to-implement prompts as plan finalization. Required cross-model plan review plus `plan-finalization-precheck` must pass before those actions.
- Use the active project adapter's `review.codexPlanWrapper` when running Codex plan review evidence; do not hard-code another project's commands in reusable framework docs or adapters.
- Codex CLI finding retrieval is part of the review gate: capture the complete log, read the final assistant review block, and classify every finding before declaring review clean. Do not infer no findings from a missing grep marker, missing blank line, speaker tag formatting, wrapper status text, or parser failure.
- Critical and P1/Important findings block merge.
- A Critical/C1/P1 review finding creates a repair work item, not a stopping point. If the finding can be fixed within approved scope, fix it and rerun the required gate/review. If it requires prerequisite PRs, dependency ordering, or a smaller safe sequence already supported by the source-of-truth plan, backlog, execution packet, or review recommendation, execute that sequence.
- Do not present review-blocker options as a menu when a safe recommended path exists. Ask one exact blocker question only when every viable repair path changes approved scope, risk, cost, security posture, production behavior, or standing approval.
- P2/P3/Nit findings may be fixed immediately or routed to the project backlog adapter.
- Review round budgets are escalation triggers, not permission to ship known blockers.

Project-specific review wrapper, merge, and gate commands belong in the project adapter. Do not substitute generic commands when the active adapter defines a wrapper or gate.

- After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps. Schedule no wakeup for routine clean queued PRs. Schedule an exceptional failure check only when a specific failure/degraded signal is already known, the human operator explicitly asks for the check, or the next action truly depends on the merged main commit; the prompt must name that signal/dependency and the next authorized non-queue work item.
- Exceptional queue checks use the PR `state` field from `gh pr view <PR> --json state` or GraphQL `pullRequest.state` as the terminal signal. Do not use `mergeQueueEntry.estimatedTimeToMerge` as progress; repeated identical queue output means switch signals instead of rescheduling the same query.
- Routine `--admin` is banned.
- Admin merge is break-glass only with a documented reason.
- If a source-of-truth artifact already authorized break-glass/admin merge under named conditions, that is standing approval once gates and conditions match. Do not stop for redundant approval; cite the artifact and condition in the merge note or delivery summary.
- If admin merge is required but no standing approval exists, or the recorded condition no longer matches current scope/risk, ask one exact blocker question. Do not invent approval from habit, memory, or urgency.

## Background Work Policy

Every long/background command needs:

- Exact command.
- Log path.
- PID.
- Wrapper-enforced timeout when detached or expected to finish in a bounded window.
- Monitor id or task id when available.
- Interrupt conditions.
- Heartbeat, monitor, or equivalent watcher with concrete cadence no longer than 10 minutes unless the project adapter sets a stricter cadence.
- Next concrete action already underway, or active polling cadence when no parallel-safe work exists.
- Terminal summary when it completes or fails.

A background command without a feedback path is incomplete work. A monitor without forward motion is also incomplete work. Routine clean queued PRs are not background work to supervise; after queueing, record the PR reference, stop watching that PR, and continue with the next authorized task.

Starting or arming a monitor is not a stopping point. Do not end a turn with only `monitor is running`, `monitor watches`, `waiting on merge`, `waiting on checks`, `R2 running`, `R3 running`, `review running`, `wakeup in 10 min`, or equivalent passive-monitor language. A passive monitor stop is any response or turn whose only forward motion is reporting monitor/background/queue/check state while the monitored work has not reached a terminal state. It is forbidden even if it avoids the listed phrases. Passive monitor stop examples include `CI is processing`, `the deploy is underway`, `the review is running`, `checks are in progress`, `I'll check back when it completes`, `Wakeup in 10 min`, or any equivalent status-only statement without a same-turn next action or valid active poll. After arming any monitor, immediately start the next parallel-safe task, do non-conflicting work such as ledger updates/review prep/backlog filing/evidence capture, or actively poll at the documented cadence until completion. Immediately means in the same turn before yielding, stopping, or sending a final status to the human operator. Vague cadence such as `as needed` is invalid.

`minervit-methodology response-guard --stdin --active-monitor`, and the installed Claude Stop hook `minervit-methodology response-guard-hook`, validate this response boundary. The installed Stop hook only evaluates when the lane has an active goal ledger and the current transcript or hook payload proves a live goal session; stale goal ledger files do not activate it. Without a live current-chat goal, it exits cleanly so discussion and clarification can pause for human input. During live active goal work, the same response guard blocks forbidden opt-in/standby text such as asking whether to kill/retry a proven-stale process the agent launched. If the guard blocks, continue with the printed recovery action instead of re-sending the same passive status.

The response guard also blocks status-report-as-stop on derivable-next-action prompts. If the human operator asks what the next milestone is, whether work is planned, or otherwise exposes a concrete planning/execution gap, the agent must start the source-of-truth planning artifact, review workflow, or next action in the same turn. A response that ends with "needs drafting", "missing spec", "requires planning", or equivalent without the action underway is non-compliant.

The response guard also blocks terminal continuity omission. A terminal workflow/session summary that reports merged/no-open-PR/no-work-in-flight/cleanup-complete state must refresh the configured continuity handoff and prepare/publish or pend the session journal before yielding.

When a monitor observes terminal success such as a merged PR, landed batch item, completed deploy, or published release, the next human-facing update must follow Delivery Summaries. A monitor event is not an excuse for a technical-only landed-work report.

If no parallel-safe task exists while a monitor is running, stay in active supervision mode and poll at the documented cadence until the monitor reaches a terminal state or a true blocker occurs. A valid active poll means running or reading a concrete monitor artifact: process status, log tail, PR/check/deploy status, queue state, or the monitor task itself. Record the poll as `timestamp | command/artifact | observed state | next poll due`. Merely restating that work is in progress is not a poll. Before saying a command or review is still active, verify process liveness and log freshness with `minervit-methodology monitor-status --target . --log <log> --pid <pid-if-known> --strict` or equivalent evidence. If no live process is verified and the log has not changed within the stale threshold, the command is stale/hung, not running. If monitored work may outlast the current turn, arm `ScheduleWakeup` or an equivalent host self-wakeup at the same cadence, no longer than 10 minutes. A sequence of foreground review, test, or gate commands whose cumulative wall-clock is expected to exceed 10 minutes is monitored-class work even if no single command is backgrounded; state the estimate, emit <=10 minute plain-language checkpoints, and arm a heartbeat if it may outlast the current turn. Put plainly, a cumulative foreground loop expected to exceed 10 minutes is monitored-class work. A backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop that waits for the same job is not a monitor. No log, artifact, check, or process-progress change for two times the poll cadence is stale/hung unless the adapter is stricter. Do not end the turn with an active monitor as the only remaining activity. Platform or CI notifications do not replace active supervision.

Provider/API outages use the same supervision mindset with a faster first retry. If Claude, Anthropic, Codex, GitHub, or another required provider returns overload, 5xx/529, websocket/network, rate-limit, service-degraded, or "try again" errors, arm a provider recovery loop at <=5 minutes, cap backoff at <=15 minutes, preserve continuity/session-journal evidence when safe, and retry until the provider recovers or the failure changes class. The lane should keep advancing provider-independent work where possible instead of ending the session. Frustration and profanity are not cancellation signals; keep the retry/wakeup/goal loop armed unless the human explicitly says stop, cancel, pause, abort, or `/goal clear`.

If a background/review process the agent launched is live but stale or wedged, kill/retry it and report the recovery action taken. Do not ask whether to kill/retry a process that is agent-launched, lane-local, and proven stale/hung.

Shell/background command completion notifications do not replace active supervision. A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision; it can only be a backup signal. Tool-level timeouts on detached/background shell calls are not sufficient because they may only cover launch; bounded detached work needs `minervit-methodology background-run --timeout-seconds <seconds>` or a project-equivalent watchdog. Do not write `waiting for notification`, `waiting for harness notification`, `will wait for completion`, `I'll resume when`, `I'll continue when`, `will be notified`, `completion notification`, `I'll wait for it to finish`, `waiting for the background command`, `waiting for shell`, `wakeup in 10 min`, or equivalent standby language while a command is still running. If a shell/background command is still running and no parallel-safe work is already underway, actively poll the process/log/check artifact instead of yielding a recap or standby message. If a command is still running and appears healthy, do not ask whether to wait, kill, or retry it. Health requires a live process plus fresh log/check progress. A live but idle process with no progress past the stale threshold is stale/hung; kill/retry or recover routine review/preflight work when safe and authorized. Kill, retry, or interrupt only when the command has failed, timed out, gone stale past the documented threshold, is consuming the wrong resource, or the human operator explicitly requested interruption.

Final/R3/`cap`/rerun review rounds, and any other named terminal or retry review round, are not complete when the review process starts. The agent must consume the review result, classify findings, and complete required fixes or documented deferrals before treating the review gate as done. If the review log is stale past the threshold, recover or rerun the configured wrapper instead of claiming the review is active.

Startup open-PR and main-health checks should interrupt on:

- Queue rejection.
- Closed-without-merge.
- Main red.
- Deploy failure.
- Test failure.
- Merge conflict.
- Failed or blocked open PR checks.
- Blocked or unclear mergeability.

## Open Brain Policy

Open Brain is useful persistent memory. It is not process authority.

Process never comes from Open Brain, Claude memories, local memories, or feedback-memory files. If a memory says a review, gate, handoff, planning step, or work-loop behavior is required, use it only to find the corresponding canonical rule, generated adapter, or methodology skill. If none exists, the correct outcome is a methodology gap to fix.

Use Open Brain for:

- Durable decisions.
- User preferences.
- Project facts.
- Important status changes.
- Evidence that may help future sessions.

Do not use Open Brain as:

- The canonical rule source.
- A source for violated rules, expected behavior, required review gates, or RCA root cause.
- A replacement for generated adapters.
- A blocking dependency for code review.
- A blocking dependency for preflight, merge, incident response, or automation.

If Open Brain conflicts with this repo, this repo wins.
