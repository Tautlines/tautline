# Merge Queue Monitoring Policy Reference

This reference keeps the detailed merge queue, auto-merge, exceptional monitor, inactive-branch, and break-glass policy behind the concise `merge-queue-monitoring` entrypoint. Read it in full before any failed, stalled, conflicted, or otherwise exceptional merge/queue/deploy monitor; inactive-branch recovery; delayed wakeup/reminder; batch merge update; post-merge smoke/deploy check; or break-glass/admin merge.

## Routine Path

1. Confirm required item tests and review gates are clean for Critical/P1.
2. Run the configured local pre-merge gates as foreground work: fast preflight first, then test-environment and full preflight after fast preflight succeeds.
3. If final preflight takes meaningful wall-clock time, run it with monitor evidence on the frozen PR tip and use the wait for branch-isolated next-iteration planning or active polling. Do not edit the current PR diff while preflight is proving that tip; if preflight fails, hangs, goes stale, or shows resource contention, repair or recover the current PR gate before next work.
4. Enable merge queue or auto-merge using the project adapter command.
5. Record the PR reference in the delivery summary or lane evidence.
6. Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work. Advance the lane ledger with `minervit-methodology milestone-advance --target . --event pr-queued --pr <PR>` and start the printed `next_action`.
7. Send a queued-delivery summary immediately: validated locally, PR queued or auto-merge enabled, not yet merged.
8. Remove the clean queued PR from active attention.
9. Continue with the next authorized task in the same turn, or prove no authorized next work remains by checking the execution packet, backlog/source-of-truth readiness, continuity handoff, open PR list, and defer/follow-up capture.

Routine queued PRs are queue-and-move-on, not foreground work. Do not wait for GitHub Actions, merge queue, deploy, or post-merge smoke after local gates and review are clean. Do not start a routine merge monitor just to watch a clean queued PR. Check queued merge state in-session only when a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.

A queued, auto-merge-enabled, merged, or closed PR branch is inactive. If this state is discovered at startup or before commit/review/push/subagent dispatch, stop work on that branch, sync main, and continue only from the source-of-truth next work item. If this proves the prior PR has already landed and no work is in flight, do not ask where to go next; sync main, clean the merged local branch/worktree when safe, run gates, and continue from the next source-of-truth item or planning artifact. Do not run additional review rounds, commits, pushes, reverts, or tactical subagents against the inactive branch.

After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps. Schedule no wakeup for routine clean queued PRs. Schedule an exceptional failure check only when a specific failure/degraded signal is already known, the human operator explicitly asks for the check, or the next action truly depends on the merged main commit; the prompt must name that signal/dependency and the next authorized non-queue work item.

For exceptional in-session queue checks, the PR `state` field from `gh pr view <PR> --json state` or GraphQL `pullRequest.state` is the authoritative terminal signal. Do not use `mergeQueueEntry.estimatedTimeToMerge` as a progress indicator. If two queue polls return byte-identical output, switch to PR state and merge-group check-run evidence instead of rescheduling the same query.

When an exceptional in-session merge/deploy check is required, status must be plain language. Explain what is happening and what it means before using labels such as HEAD, queue, gate, verdict, monitor event, green/red, or deploy run. Do not say `will report verdict on monitor event`; say what PR/check/deploy artifact is being checked, why this check is required, and what failure would interrupt the work.

When a merge/queue/deploy monitor observes terminal success such as a merged PR, landed batch item, completed deploy, or published release, the next human-facing update must follow the delivery-summary skill. A monitor event is not an excuse for a technical-only landed-work report.

For batch merge updates, include the batch progress count, what changed in plain English across landed items, what remains in flight or blocked, whether the remaining planned work is ready, and the recommended next action before listing PR numbers, invariant names, branch names, or checks.

Post-merge smoke or deploy checks are not watched by default after a clean queued PR. Do not delay the queued-delivery summary waiting for post-merge success unless a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.

Do not treat "merge/check/deploy in progress" as a reason to stand by. After queueing, continue the next authorized task. If an exceptional check is required and no parallel-safe task exists, actively poll the PR/check/deploy artifact in the same turn and record the next poll due. Do not write `waiting for notification`, `will wait for completion`, or equivalent standby language.

If an exceptional in-session merge/deploy check is required and the operation is still running but appears healthy, do not ask whether to wait, cancel, retry, or restart it. Continue parallel-safe work or actively poll only for the exceptional reason. Cancel, retry, or interrupt only when the operation has failed, timed out, gone stale past the documented threshold, is using the wrong target, or the human operator explicitly requested interruption.

At the next session start, run the adapter's main-health/smoke gate, open-PR health check, current-branch liveness check, and merge-conflict check. Any main-health failure, failed deploy, open PR with failed/blocked checks, queued/auto-merge-enabled current branch, merged/closed current-branch PR, closed-without-merge PR, merge conflict, or unclear mergeability is highest priority before new feature work.

## Break-Glass

Routine `--admin` merge is banned. Use admin merge only for a real emergency with the reason documented in the PR body or thread.

If a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion already authorized break-glass/admin merge under named conditions, that is standing approval once gates and conditions match. Do not stop for redundant approval; cite the approving artifact and condition in the merge note or delivery summary.

If admin merge is required but no standing approval exists, or the recorded condition no longer matches current scope/risk, ask one exact blocker question naming the missing or changed condition. Do not invent approval from habit, memory, or urgency.

## Interrupts

Queue rejection, queued/auto-merge-enabled current branch, merged/closed current-branch PR, closed-without-merge, main red, deploy failure, failed/blocked open PR checks, merge conflict, or unclear mergeability is P0.
