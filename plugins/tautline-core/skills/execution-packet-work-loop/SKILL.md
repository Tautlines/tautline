---
name: execution-packet-work-loop
description: Create or consume lane-local execution packets so Claude can run tactical iterations after milestone approval with true-blocker-only human interruption.
---

# Execution Packet Work Loop

Use to create, validate, consume, or complete lane-local execution packets for
tactical work after source-of-truth planning and required review are complete.

Read `references/execution-packet-policy.md` before creating packets,
dispatching tactical work, deciding whether interruption is allowed, advancing
milestones at PR boundaries, or handling exhausted packets. For packets or
plans with three or more tasks, read `references/parallel-execution.md` and do
the parallelization pass (file scopes, ambiguity classes, waves, serial
integration, model routing) before starting the first task.

## Fast Path

1. Create packets only from reviewed/approved source-of-truth plans or
   adapter-authorized tactical work.
2. Include objective, scope, non-goals, ordered steps, validation, review gates,
   risks, exact next action, proof-of-done evidence, and true-blocker criteria.
3. During execution, continue through safe next steps without asking for
   permission.
4. Interrupt only for true blockers: missing approval, changed risk/scope/cost,
   unsafe production/security/data impact, or a required gate with no safe fix.
5. At PR or milestone boundaries, use `milestone-next` /
   `milestone-advance --event <event>` as the controller.
6. When a packet is exhausted, inspect goal/milestone/provider state and plan
   the next authorized item instead of stopping.

## Non-Negotiables

- A packet is execution guidance, not a substitute for adapter gates.
- Do not ask whether to continue when the next packet step is safe and in scope.
- Do not treat a completed subtask, PR, or validation command as a stop point by
  itself.
- `@pending`/pending/skipped/disabled/quarantined/wrong-target tests are gaps, not proof.

## Required Follow-Through

When packet detail is needed, load the reference and apply the relevant create,
consume, interruption, validation, boundary, or exhausted-packet rule.
