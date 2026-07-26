# Background Monitoring Policy Reference

This reference keeps the detailed monitor, polling, passive-stop,
provider-recovery, queue, and stale/hung rules behind the concise
`background-task-monitoring` skill entrypoint. It also owns early-warning smoke
command-selection, active-polling, stale/failure, queued-PR, and
final-preflight planning policy. It preserves existing behavior while making
routine skill loading smaller.

Use this skill for long-running commands, background commands, tailing monitors,
deploy watches, and queued work.

## Required Evidence

Every long/background command needs:

- exact command
- log path
- PID
- metadata file when available
- monitor id or task id when available
- interrupt conditions
- wrapper-enforced timeout when the command is detached or expected to finish within a bounded window
- heartbeat cadence or equivalent status watcher, concrete and no longer than 10 minutes unless the project adapter sets a stricter cadence
- next concrete action already underway, or active polling cadence when no parallel-safe work exists
- terminal summary when it completes or fails

## Rules

- A background command without a monitor is incomplete.
- A monitor without forward motion is also incomplete.
- Tool-level timeouts on a detached/background shell call are not enough because the tool may only time out launch. Use `tautline background-run --timeout-seconds <seconds>` or a project-equivalent watchdog for bounded background work.
- Triggered early-warning smoke/main-health checks run as monitored background work so planning and implementation can continue while known-risk failures interrupt quickly.
- Early-warning smoke monitors still require active polling at a concrete cadence no longer than 10 minutes; starting the monitor and assuming notifications will arrive is not enough.
- Final preflight may also run with monitor evidence once the current PR tip is frozen and review is clean. Use that wait for branch-isolated next-iteration planning or active polling instead of idle status, but do not edit the current PR diff while preflight is proving it.
- If final preflight fails, hangs, goes stale, times out, loses PID/log identity, or shows resource contention, interrupt next-iteration planning and repair or recover the current PR gate. If it passes, push/queue the current PR before continuing implementation on the next item.
- A sequence of foreground review, test, or gate commands whose cumulative wall-clock is expected to exceed 10 minutes is monitored-class work even if no single command is backgrounded. State the estimate, emit <=10 minute plain-language checkpoints, and arm a heartbeat if the sequence may outlast the current turn.
- Before starting a duplicate early-warning monitor, inspect the previous monitor metadata and PID files; compare command plus `cwd`, verify the PID is live, and poll the existing monitor if the same command is still live for the same target. If a PID exists without metadata, check PID liveness and the log once before deciding whether to start a replacement.
- Monitor/status updates must be plain language for the human operator. A monitor handoff/status message must include monitor id or task id when available, log path, PID/process identity when available, interrupt conditions, heartbeat/poll cadence, and the next concrete action already underway. Explain the meaning before internal terms.
- Use the `delivery-summary` skill's operator-progress cadence during long review/preflight/monitor work: after startup, before >2 minute monitored work, at every poll/round, and at least every 5 minutes when the host gives a chance to speak. Lead with the plain-language outcome or current state and the next action so the operator can tell what is happening without decoding process jargon. Labels are optional readability aids, not required schema.
- Do not say `will report verdict on monitor event` or equivalent monitor-internal wording. Say what artifact is being checked, when the next check is due, and what failure would interrupt the work.
- Translate labels such as HEAD, trailer, BREAK-GLASS, R1/R2, verdict, monitor event, full multi-port env, green/red, queue, and gate into what they mean for the current work.
- Starting or arming a monitor is not a stopping point. A monitor is an alerting mechanism, not the next action.
- If monitored work may outlast the current turn, arm `ScheduleWakeup` or an equivalent host self-wakeup at the same cadence, no longer than 10 minutes. The wakeup is a backup heartbeat, not a replacement for active work or active polling.
- A transient external dependency is not a terminal handoff. Transient provider/API failures are recovery-loop work, not terminal blockers. Anthropic/Claude/Codex/GitHub/API overloads, API errors, 429/500/502/503/504/529 responses, rate limits, websocket/network failures, service-degraded messages, and "try again" failures require `ScheduleWakeup` or host self-wakeup at an initial cadence no longer than 5 minutes, with backoff capped at 15 minutes, until the provider responds or the failure changes class. Do not stop for the night because a model provider is temporarily down.
- A backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop that waits for the same job is not a monitor. It inherits the same completion-notification failure mode and cannot prove forward motion after the turn ends.
- No log, artifact, check, or process-progress change for two times the poll cadence is stale/hung unless the adapter defines a stricter stale threshold. Kill/retry agent-launched routine review/preflight/monitor work without asking, record the recovery, and continue.
- Progress means terminal-relevant output: new findings, test/check status, phase movement, artifact growth that changes result interpretation, or process state change. Heartbeat timestamps, repeated identical status, debug noise, or byte-identical queue/check output do not reset the stale clock.
- Routine agent-launched review/preflight/monitor work includes plan review, cross-model review, local tests/preflight/smoke, and lane-local monitors. It is non-routine only when killing or retrying would alter external production state, shared infrastructure, customer data, security settings, or another operator-owned resource; then ask one exact blocker question.
- Routine clean queued PRs are not background work to supervise. After local gates and review are clean, queue the PR, record the PR reference in the queued-delivery summary, stop watching that PR, and continue with the next authorized task. Startup gates in the next session catch failed/blocked open PRs, main-health issues, and merge conflicts.
- A queued, auto-merge-enabled, merged, or closed PR branch is inactive. Do not keep background review, revert, push, or implementation work pointed at that branch; sync main and continue from the source-of-truth next item.
- After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps. Schedule no wakeup for routine clean queued PRs. Exceptional checks are allowed only when a specific failure/degraded signal is already known, the human operator explicitly asks for the check, or the next action truly depends on the merged main commit; the prompt must name that signal/dependency and the next authorized non-queue work item.
- Do not end a turn with only `monitor is running`, `monitor watches`, `waiting on merge`, `waiting on checks`, `R2 running`, or equivalent passive-monitor language.
- Do not end a turn with only `R3 running`, `review running`, `wakeup in 10 min`, or equivalent passive-monitor language.
- Claude Stop response guards should run `tautline response-guard-hook` so passive-monitor-stop messages are blocked before the turn is yielded during live active goal work. `lane-start` installs the guard automatically, and `methodology-status --fail-on-drift` fails if the required hook is missing. The hook no-ops when no live goal is active in the current chat window, even if stale goal ledger state exists, so ordinary conversation is not treated as a monitor boundary. If the guard blocks, start parallel-safe work or actively poll; do not resend the same status.
- When per-checkout product-dev mode is active (`tautline product-dev-mode on`), the active-goal Stop-guard stands down for that TTL-bounded, advisory-announced session, so a stop needs no blocker while the mode holds; code-safety merge gates and plan-review gates are unaffected.
- During live active goal work, the same Stop response guard blocks forbidden opt-in/standby language, chat-only RCA-shaped responses, status-report-as-stop on derivable-next-action prompts, terminal continuity omission, and false-active status after rejected tools. If a process the agent launched is live but stale or wedged, kill/retry it and report what happened; do not ask whether to kill or retry it.
- A passive monitor stop is any response or turn whose only forward motion is reporting monitor/background/queue/check state while the monitored work has not reached a terminal state. It is forbidden even if it avoids the listed phrases.
- Passive monitor stop examples include `CI is processing`, `the deploy is underway`, `the review is running`, `checks are in progress`, `I'll check back when it completes`, `Wakeup in 10 min`, or any equivalent status-only statement without a same-turn next action or valid active poll.
- Autonomous-loop yield messages must not be empty, one-word, or ultra-terse. `Quiet.` and equivalent no-information replies are forbidden.
- Before any autonomous-loop yield, delayed wakeup, `ScheduleWakeup`, or host-equivalent heartbeat, enumerate the current work set from open PR state, pending/unblocked task lists, and `.ai-continuity/NEXT_SESSION.md` scheduled/current work. If any item can advance without human operator input, advance it instead of yielding.
- A legitimate autonomous-loop yield must name the real state, true blocker,
  and concrete retry/poll/next action in plain language. Empty, one-word, or
  label-only heartbeats are invalid.
- Preflight idle examples include `Preflight still running; will push as soon as it lands` and `Preflight just started; 11 min ETA` when no branch-isolated planning or active poll is already underway.
- After arming any monitor, immediately start the next parallel-safe task, do non-conflicting work, or actively poll at the documented cadence until completion.
- Heartbeat/poll cadence must be concrete. Vague cadence such as `as needed` is invalid.
- Immediately means in the same turn before yielding, stopping, or sending a final status to the human operator.
- If no parallel-safe task exists while a monitor is running, stay in active supervision mode and poll at the documented cadence until the monitor reaches a terminal state or a true blocker occurs. Do not end the turn with an active monitor as the only remaining activity.
- A valid active poll means running or reading a concrete monitor artifact: process status, log tail, PR/check/deploy status, queue state, or the monitor task itself. Record the poll as `timestamp | command/artifact | observed state | next poll due`. Merely restating that work is in progress is not a poll.
- Before saying a command or review is still active, verify process liveness and log freshness with `tautline monitor-status --target . --log <log> --pid <pid-if-known> --strict` or equivalent evidence. Strict monitor checks require verified PID/process identity, not only a fresh log.
- If no live process is verified and the log has not changed within the stale threshold, the command is stale/hung, not running. Inspect the log tail, recover or rerun the command, and do not ask whether to keep waiting.
- Terminal monitor states are success, failure, cancelled, timed out, queue rejection, deploy failure, main red, or another project-defined terminal condition. Nonterminal states require continued work or another poll.
- Platform or CI notifications do not replace active supervision. Treat them only as additional signals.
- Shell/background command completion notifications do not replace active supervision. They are additional signals only.
- A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision. It may exist as a backup signal, but the agent still must keep working or poll concrete artifacts in the same turn.
- When per-checkout product-dev mode is active (`tautline product-dev-mode on`), the fake-monitor background-command guard (the shell `until`/`while`/`sleep`/`tail -F | grep` polling-loop block) stands down for that TTL-bounded, advisory-announced session; the board-structure and item-content safety blocks and every code-safety and plan-review gate are unaffected.
- Do not write `waiting for notification`, `waiting for harness notification`, `will wait for completion`, `I'll resume when`, `I'll continue when`, `will be notified`, `completion notification`, `I'll wait for it to finish`, `waiting for the background command`, `waiting for shell`, `wakeup in 10 min`, or equivalent standby language while a command is still running.
- If a shell/background command is still running and no parallel-safe work is already underway, actively poll the process/log/check artifact instead of yielding a recap or standby message.
- If a shell/background command is still running and appears healthy, do not ask whether to wait, kill, or retry it. Keep supervising at the documented cadence or continue parallel-safe work. Kill, retry, or interrupt only when the command has failed, timed out, gone stale past the documented threshold, is consuming the wrong resource, or the human operator explicitly requested interruption.
- A live PID with no log/check progress past the stale threshold is stale/hung, not healthy. Kill/retry or recover routine review/preflight work when safe and authorized; do not ask whether to kill and retry.
- A recap while a shell/background command is still running is valid only if it names the active poll just performed, the next poll due, and any parallel-safe work already underway.
- A final, R3, `cap`, rerun, or any other named terminal/retry review round is not done when the review process starts. Keep supervising until the review output has been read, findings have been classified, and required fixes or deferrals are complete.
- If a monitor sees failure, queue rejection, deploy failure, or test failure, interrupt as P0.
- If an early-warning smoke monitor passes, do not pause or summarize only that event; keep working or include it as validation detail in the next delivery summary.
- If work is intentionally fire-and-forget, record where the monitor will surface failures.

## Early-Warning Smoke

Early-warning smoke is no longer a standing gate. Run it only when the adapter,
source-of-truth plan, issue, human operator, or a concrete risk signal asks for
it. Routine startup/main health, pre-push preflight, and CI remain the default
quality gates.

Use the project adapter's `commands.earlyWarningSmoke` when present and distinct from `commands.mainStatus`. If it is not configured, or it matches `mainStatus`, use the main-status gate as the baseline check instead of launching a duplicate background monitor.

Run adapter-backed local-service commands through lane isolation when the
adapter lists the command under `localResourceIsolation.isolatedCommands`.
Remote/main-health commands can run directly.

```bash
tautline background-run \
  --log ".ai-runs/early-warning-smoke-$(date -u +%Y%m%dT%H%M%SZ).log" \
  -- bash -lc '<early-warning-smoke-command>'
```

For a local-service smoke command listed in `isolatedCommands`, use:

```bash
tautline background-run \
  --log ".ai-runs/early-warning-smoke-$(date -u +%Y%m%dT%H%M%SZ).log" \
  -- tautline lane-run --target . -- bash -lc '<early-warning-smoke-command>'
```

### Smoke Work Policy

- Confirm the trigger. If no trigger exists, do not launch an ambient smoke
  monitor; continue authorized work under normal startup/preflight gates.
- Do not wait for early-warning smoke to pass before starting planning or implementation.
- Continue with the authorized tactical queue while actively monitoring the
  smoke command.
- Poll the smoke log/process/check at least every 10 minutes unless the adapter is stricter. Record each poll as `timestamp | log path or command | observed state | next poll due`.
- Before starting a new early-warning monitor, inspect the latest early-warning `.meta.json` and `.pid` files under the lane runs directory. Compare command plus `cwd` as the target, verify the PID is live, and poll the existing monitor if the same early-warning command is already running for the same target. If a `.pid` exists without metadata, check PID liveness and the log once before deciding whether to start a replacement.
- Do not launch background smoke monitors merely because a new plan/spec write,
  edit, PR, rebase, or iteration boundary began.
- Before commit, push, or merge, actively poll any running early-warning monitor
  in the same turn. Proceed only when the poll observes terminal success or a
  current healthy in-progress state; unknown, stale, failing, wrong-target, or
  resource-contention states halt the current item.
- Default stale threshold is one missed poll without a live process/check state
  or two consecutive polls without log/check progress.
- Interrupt as P0 if the smoke fails, times out, goes stale, runs against the wrong target, or hits resource contention. Halt the current item's commit, push, merge, and additional feature work until investigated or proven unrelated with named evidence such as unchanged-main reproduction, external service degradation, or logs showing the failure predates the branch.
- A passing early-warning smoke is not a new stopping point and does not replace
  final branch gates.
- Required item tests, fast preflight, full preflight, review gates, and merge
  gates still run at their configured points.
- Do not wait for a clean queued PR to land just to create a later
  tactical-iteration boundary. If the next authorized work does not depend on
  the merged main commit, continue.
- Post-merge smoke or deploy checks are not watched by default after a clean queued PR. Do not delay the queued-delivery summary waiting for post-merge success unless a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.
- In a normal successful iteration, the final human-facing action is the
  queued-delivery summary, then the next authorized work begins.

### Final Preflight Planning Window

When the current PR tip is frozen, review is clean, and final preflight is running with monitor/log/PID evidence, use that wait for branch-isolated next-iteration planning or active polling. This is not early-warning smoke, but the same anti-idle rule applies.

- Safe planning includes reading the milestone ledger, execution packet,
  backlog/indexes, and source-of-truth plan candidates.
- Draft or update the next plan only in a separate worktree/branch or ignored
  lane-local scratch under `.ai-work/` that cannot alter the current PR diff.
- Run next-plan review during the wait only when it does not contend for the
  same local test resources.
- Do not edit the current PR diff, amend the current commit, or start
  implementation for the next item while final preflight is proving the current
  tip.
- If final preflight fails, hangs, goes stale, times out, loses PID/log
  identity, or shows resource contention, interrupt next-iteration planning and
  repair or recover the current PR gate. If it passes, push/queue the current PR
  before continuing implementation on the next item.
- A status-only update that says preflight is running or that the agent will
  push when it finishes is a passive monitor stop.
