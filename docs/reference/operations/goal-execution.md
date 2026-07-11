# Goal Execution

This reference owns detailed goal, milestone, and context-rotation policy. Backlog-provider board workflows live in [Backlog Provider Workflow](backlog-provider-workflow.md). Tactical execution packets and plan-finalization controls live in [Execution Packet Work Loop](execution-packet-work-loop.md). Forward-motion and work-evasion guardrails live in [Autonomy Guardrails](autonomy-guardrails.md). The operating manual keeps short navigation entries for these workflows.

## Goal Orchestration

The delivery hierarchy is:

```text
Goal -> Milestone -> PR / tactical item
```

Goals are source-of-truth plans plus lane-local execution state. They are for substantial work expected to span multiple milestones, multiple PRs, overnight autonomous execution, or ambiguous "build/ship/finish X" requests. Small single-PR tasks can stay at the PR-plan layer unless the adapter or human operator asks for a goal.

Adapter-backed defaults:

```json
{
  "goalArtifacts": {
    "sourceOfTruth": "<planningArtifacts.sourceOfTruth>/goals",
    "template": "<planningArtifacts.sourceOfTruth>/goals/goal.template.md",
    "templateTrigger": "Substantial work expected to span multiple milestones, multiple PRs, overnight execution, or ambiguous build/ship/finish requests.",
    "reviewRequired": true
  },
  "goalExecution": {
    "preferredClaudeCommand": "/goal",
    "claudeGoalGuidance": true,
    "fallback": "goal-ledger"
  },
  "laneState": {
    "goalRun": ".ai-work/GOAL_RUN.json"
  }
}
```

A goal plan should define desired outcome, user/business benefit, success condition, non-goals, milestones, dependencies, risks, review gates, validation proof, and completion criteria. Goal plans require cross-model review before being treated as execution-ready unless the adapter explicitly exempts them.
Validation proof must come from checks that actually executed the changed behavior. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof of completion; disclose them as gaps, blockers, or follow-up risk.

When adapter `backlogProvider.enabled` is true, the external board selects and
tracks stakeholder-facing goals, milestones, bugs, and tasks. The lane still
syncs selected items into repo source-of-truth plans and reviews those plans
before execution; agents must not implement directly from a raw GitHub Project
item. Keep provider commands, board status rules, stakeholder-question flow,
migration/export behavior, board order, epic scope, and board-backed subtask
status in [Backlog Provider Workflow](backlog-provider-workflow.md).

Start or refresh a lane-local goal ledger:

```bash
minervit-methodology goal-start --target . --goal <source-of-truth-goal-plan>
minervit-methodology goal-status --target .
minervit-methodology goal-next --target .
```

Advance the ledger at milestone boundaries:

```bash
minervit-methodology goal-advance --target . --event milestone-complete --detail "<validation proof>"
minervit-methodology goal-advance --target . --event milestone-deferred --reason "<policy deferral reason>"
minervit-methodology goal-advance --target . --event milestone-blocked --reason "<true blocker>"
minervit-methodology goal-advance --target . --event goal-complete --detail "<completion proof>" --iteration-review-record docs/iteration-reviews/<goal-id>/goal-review.json
```

Claude lanes should prefer Claude Code `/goal` for substantial reviewed goal work when available, but `/goal` is not the source of truth. Per [Claude Code Goals](https://code.claude.com/docs/en/goal), it is session-scoped, requires Claude Code `v2.1.139+`, and its evaluator judges evidence surfaced in the conversation rather than independently inspecting files/tools. Generate a measurable condition from the ledger:

```bash
minervit-methodology goal-condition --target .
```

To show a copy/paste Claude startup prompt before launching Claude, use:

```bash
minervit-methodology goal-kickoff-prompt --target .
```

In an adapter-backed lane, this command is context-aware. If a goal is active, it prints the active goal condition. If no goal is active or the previous goal ledger is complete, it prints `next_goal_name`, `next_goal_short_description`, and `next_goal_claude_prompt` so the next Claude `/goal` can be started without asking the lane to invent the wording.

Launcher functions can print that prompt after framework sync and lane startup, then pause before `claude` starts so the prompt stays visible:

```zsh
minervit-methodology sync-methodology || return 1
minervit-methodology lane-start --target . || return 1
minervit-methodology methodology-status --target . --fail-on-drift || return 1
minervit-methodology goal-kickoff-prompt --target .
printf '\nCopy the prompt above if you want goal-led startup, then press Return to start Claude...'
read -r _
claude --dangerously-skip-permissions "$@"
```

If `/goal` is unavailable, unsupported, disabled, or cleared, continue through `goal-next`, `milestone-next`, and the existing work loop. Lack of `/goal` is not a blocker.

For source-of-truth goals declared as multi-session, or goals with known operator-input true blockers, the Claude `/goal` condition can be satisfied for the current session by delivering an authorized per-session increment, refreshing continuity, handling or queueing the session journal, and reaching goal complete, true blocker, or a genuine scope boundary. This is not permission to stop at a routine clean PR or milestone boundary; the boundary must be evidenced by the goal ledger and summary. Context exhaustion by itself does not satisfy the goal when compact/restart is available. Use explicit phrases such as `multi-session`, `multiple sessions`, `overnight`, or `more than one session` in the source goal plan when that escape clause should exist.

`goal-start` extracts known operator-input dependencies from goal plan risk/dependency/blocker sections. Dependency detection is intentionally narrow: ordinary implementation words such as `input`, `fixture`, or `blocked` are not enough by themselves. `goal-status` and `goal-next` surface matching dependencies before milestone plan-finalization, so agents defer with `goal-advance --event milestone-deferred` or block only when the dependency is confirmed unavailable or a hard true blocker before spending Codex review rounds.

When `iterationReview.enabled` is true and `iterationReview.granularities` includes `goal`, `goal-advance --event goal-complete` requires `--iteration-review-record`. The command verifies the same required outputs and Google Chat delivery marker as `iteration-review-delivery-check`; a free-text `--detail` alone cannot close the goal.

At startup, the order is: lane gates, pending journal publication, `goal-next` when an active `.ai-work/GOAL_RUN.json` exists, `milestone-next`, then PR/item work. If no active goal exists, or the prior goal ledger is complete, `lane-start`, `methodology-status`, and `goal-kickoff-prompt` print `next_goal_name`, `next_goal_short_description`, `next_goal_source`, `next_goal_status`, `next_goal_claude_prompt`, and `next_goal_next_action` from the configured external backlog provider or repo goal-plan folder when available. Use that candidate before tactical work. If no candidate exists and the next work is substantial, goal planning starts before milestone planning. The agent should ask what goal is being worked toward only when the source-of-truth artifacts cannot resolve it without changing scope/risk.

## Cross-Lane Coordination

Lane coordination is mandatory by default for adapter-backed projects. Use git-tracked coordination artifacts as the shared source of truth so lane ownership, shared contracts, and dependencies are visible to every lane. Chat is useful for alerts, but the repo artifacts are the durable coordination record. What a `--fail-on-drift` debt-only outcome does at startup, the remediation marker/contract, and the pre-push coordination-only push allowance are documented in [Startup Remediation](../startup-remediation.md).

Adapters default `laneCoordination` to enabled and derive paths from `planningArtifacts.sourceOfTruth`:

```json
{
  "laneCoordination": {
    "enabled": true,
    "enforcement": "strict",
    "root": "<planningArtifacts.sourceOfTruth>/coordination",
    "contractPath": "<planningArtifacts.sourceOfTruth>/coordination/cross-lane-contract.md",
    "boardPath": "<planningArtifacts.sourceOfTruth>/coordination/lane-board.md",
    "laneStatusDir": "<planningArtifacts.sourceOfTruth>/coordination/lanes",
    "maxStatusAgeHours": 24
  }
}
```

`lane-start` bootstraps the coordination docs when they are missing:

```bash
minervit-methodology lane-coordination-bootstrap --target . --write
```

Check status at startup, PR boundaries, and before multi-lane plan finalization. With default strict enforcement, missing, stale, untracked, uncommitted, or unpushed state in the current lane's own status file, or in the shared cross-lane contract or lane board, fails `lane-coordination-status`, `methodology-status --strict`, and `methodology-status --fail-on-drift`. Other lanes' stale, untracked, or dirty status files are informational only and never block startup. Feature branches must have a current lane status file for the active branch, and that status must be committed and pushed unless the state already exists on the shared base:

```bash
minervit-methodology lane-coordination-status --target .
```

Each lane updates only its own status file, then commits and pushes it before multi-lane implementation or PR queue:

```bash
minervit-methodology lane-coordination-note --target . \
  --lane lane-1 \
  --goal "First shop launch" \
  --current "Owner access routes and role checks" \
  --depends-on "Lane 2: account persistence contract" \
  --provides "Owner session contract for customer intake" \
  --blockers "none" \
  --pr "#123" \
  --write
```

If a lane discovers it must change something another lane owns or consumes, it must update the cross-lane contract, open a small shared contract/interface PR, or explicitly take ownership and mark dependent lanes before large implementation PRs continue.

## Context Rotation

Long-running goal work should rotate context routinely instead of waiting for the human operator to ask for a continuity prompt. The default adapter policy enables rotation with a soft threshold of `60%` visible context usage, a hard threshold of `75%`, and a `15m` heartbeat for long Claude `/goal` work. This context-rotation heartbeat for long Claude `/goal` runs must fire before final goal completion when thresholds require rotation. Managed startup sets `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` both in the launcher env and in Claude's durable settings file, so Claude Code keeps a safety margin while avoiding the throughput churn of half-context compaction even when a session is launched through raw `claude`. Reinstall the launcher or rerun `lane-start` after upgrading the framework to repair this setting:

```bash
minervit-methodology install-claude-launcher --name yolo --dangerously-skip-permissions --force
```

`methodology-status` reports both `claude_autocompact_pct_override` and `claude_autocompact_settings`. If a fresh Claude session still reaches 80-90% context with both lines reporting `ok`, collect that status output and the visible context percentage; that is evidence that the host is not honoring its documented auto-compact setting, not evidence that the framework setting is absent.

At every PR queued/completed boundary, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat, the agent should inspect the visible host context percentage when the host exposes it. If context is at or above the soft threshold, the agent refreshes the continuity handoff, updates goal/milestone ledgers, handles the session journal, compacts or restarts through the strongest host-supported path, and resumes the active goal. If context is at or above the hard threshold, rotation is mandatory at the next safe boundary. For Claude Code, invoke `/compact` or the strongest host-supported compaction path when the agent can do that directly; if the agent turn cannot invoke slash commands directly, write the handoff/journal evidence and state the exact fresh-session startup action. Do not describe context exhaustion as a terminal blocker or "productive limit", and do not ask the human operator whether to compact or continue.

Use the helper when a visible percent is available:

```bash
minervit-methodology context-rotation-check --target . --boundary pr-queued --context-percent 63 --context-percent-source estimate
minervit-methodology context-rotation-check --target . --boundary goal-heartbeat --context-percent 63 --context-percent-source estimate
```

Pass `--context-percent-source host` only if the host literally exposes a context-window counter; a host counter is the only source that can make rotation mandatory, so `estimate` is the safe default.

Safe boundaries are adapter-configured and default to `pr-queued`, `pr-complete`, `milestone-complete`, `goal-boundary`, `goal-heartbeat`, `session-summary`, and `handoff-for-review`. Do not rotate mid-edit, while a branch is unsafe, while required review/preflight is incomplete for the current PR tip, or while an active monitor needs recovery. If the host cannot literally clear or restart the session, the required fallback is to prepare the filesystem handoff and state the exact startup action for the next session. Forbidden fallback wording includes `only you can trigger /compact`, `/compact me`, `if you want`, `what would you like`, `how do you want to proceed`, `productive limit`, or any variant that turns mandatory rotation into a human opt-in.

If context rotation coincides with missing credentials, seeded accounts, TOTP, served-origin access, or live verification access, the agent must first run the adapter-declared credential/origin discovery path. If access is still missing, it names one exact setup blocker or setup action. It must not present a menu, and it must not offer to ship, push, merge, deploy, release, or implement unverified work when verification is required.
