---
name: delivery-summary
description: Use when reporting delivered work, landed or merged work, PR completion, milestone completion, monitor terminal success, batch delivery progress, or handoff-for-review summaries.
---

# Delivery Summary

Use for delivered/landed work, PR completion, milestone completion, monitor
terminal success, batch delivery progress, handoff-for-review summaries, and
operator progress updates during long work.

Read `references/delivery-summary-policy.md` before reporting delivery,
progress, merge/queue state, next-work recommendation, milestone/goal percent,
early-warning smoke status, handoff refresh, or batch completion.

## Fast Path

1. Start with the plain-language outcome and next action before technical
   detail.
2. State what changed, who benefits, validation/review evidence, PR/branch
   status, and remaining risk.
3. Include progress against the current goal/milestone when applicable.
4. State proof of done: what actually ran, what it covered, and any planned
   proof that did not run.
5. Name the recommended next work item from the ledger, source plan, execution
   packet, backlog, or adapter.
6. Refresh the configured continuity handoff before yielding at workflow
   boundaries.
7. Log required boundary events when event observability is enabled.

## Non-Negotiables

- A delivery summary is not permission to stop while authorized work remains.
- Do not convert the next recommended work into a permission question.
- Technical-only merge/check reports are incomplete for human-facing delivery.
- Queued-delivery summaries must name the concrete outcome or next controller
  action.
- `@pending`/pending/skipped/disabled/quarantined/wrong-target tests are gaps, not proof.

## Required Follow-Through

When detail is needed, load the reference and apply the relevant delivery,
progress, batch, boundary, continuity, event-log, or next-work rule before
replying.
