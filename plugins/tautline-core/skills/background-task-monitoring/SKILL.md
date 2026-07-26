---
name: background-task-monitoring
description: Start and supervise long-running commands with logs, PID tracking, heartbeat/status output, and failure escalation instead of leaving silent background work.
---

# Background Task Monitoring

Use for long-running commands, early-warning smoke, final preflight waits,
provider recovery loops, queued exceptional monitors, and any work that may
outlast the current interaction.

Read `references/background-monitoring-policy.md` before starting monitors,
reusing/killing stale jobs, polling logs, handling shell completion notices,
supervising review rounds, or reporting terminal monitor state.

## Fast Path

1. Start work with `tautline background-run --log <log> -- <cmd>`
   or the adapter-approved monitor wrapper.
2. Capture log path, PID/meta path, command, cwd, start time, and next poll due.
3. Poll on the required cadence; record observed state and next poll.
4. Treat success, failure, cancelled, stale/hung, wrong-target, or contention as
   terminal monitor states needing action.
5. Continue parallel-safe work when available; otherwise actively poll until the
   result is consumed.

## Non-Negotiables

- A shell completion notification is not active supervision.
- Backgrounded `sleep`, `wait`, `tail -F | grep`, or equivalent loops are not
  monitors.
- Do not end a turn with an active monitor as the only remaining activity.
- Do not ask whether to wait, kill, or retry routine stale monitor work when the
  policy already authorizes recovery.

## Required Follow-Through

Use the reference for monitor reuse, stale/hung thresholds, review supervision,
early-warning smoke, provider recovery, and final preflight details.
