---
name: goal-orchestration
description: Use for substantial work that spans multiple milestones or PRs, Claude Code /goal setup, source-of-truth goal planning, goal ledger transitions, and goal completion proof.
---

# Goal Orchestration

Use for substantial `Goal -> Milestone -> PR / tactical item` work, active
`.ai-work/GOAL_RUN.json` ledgers, provider-backed work items, goal boundaries,
and Claude `/goal` setup or completion proof.

Read `references/goal-orchestration-policy.md` before interpreting provider
board state, goal plan readiness, ledger transitions, deferral/blocking,
`/goal`, context rotation, closeout, or completion proof.

## Fast Path

1. If a goal ledger exists, run `tautline goal-next --target .`.
2. Start the returned `next_action` unless it names a true blocker, then inspect
   milestone state.
3. If no active ledger exists and work is substantial, create or update the
   source-of-truth goal plan before milestone planning.
4. For provider-item mode, start from `backlog-provider-next`, sync/review the
   issue, and keep the issue plus board current.
5. At PR, milestone, or goal boundaries, advance the ledger/provider item with
   validation proof and continue while executable work remains.
6. For Claude lanes, prefer `/goal` when supported; otherwise continue through
   `goal-next`, `milestone-next`, and execution packets.

## Completion Rules

- A goal plan needs outcome, benefit, success condition, non-goals, milestones,
  dependencies, risks, review gates, validation proof, and completion criteria.
- Planning counts as starting for board status.
- Goal completion requires ledgers, source plans, validation evidence,
  PR/branch state, continuity, and journal evidence.
- `@pending`/pending/skipped/disabled/quarantined/wrong-target tests are gaps, not proof.
- On a PR workflow, closeout opens+queues the PR (auto-merge; never hand back; non-PR/human-gated
  follow their path); a queued auto-merging PR is `Done = shipped`, not permission.

## Required Follow-Through

When detailed policy is needed, load the reference, apply the relevant ledger,
provider, `/goal`, boundary, or closeout section, and continue the next safe
action instead of yielding a recap or permission prompt.
