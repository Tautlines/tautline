---
name: goal-assignment
description: Use immediately after a plan is finalized (plan-finalization-precheck passes) to hand the plan to a builder lane — emits the operator-assignable goal, hard-capped at the host's character limit. Also use when asked for "a goal I can assign", a goal prompt, or when an authored goal must be length-checked before it is handed over.
---

# Goal Assignment

The step between **planning finalized** and **a builder lane picking up the work**:
the operator needs one goal they can paste to assign. A goal over the host's limit
cannot be assigned at all — the harness refuses it at paste time, after the planning
session that wrote it is gone. Do not author it free-hand and estimate its length.
Emit it.
## Fast Path

1. Finalize planning first: `tautline plan-finalization-precheck --target . --plan <plan>`.
   Its pass output names this verb. An unfinalized plan is not assignable work.
2. Emit the goal **to a file** — the transport no renderer can corrupt:
   ```
   tautline goal-assignment --target . --plan <plan> --out .ai-work/goal.txt
   ```
3. Hand over the text **between** `goal_assignment_begin` and `goal_assignment_end`
   as the **sole content of the response** — never the markers, never a label, never a
   fence. `char_count` certifies that text alone, so any prefix pushes a certified goal
   back over the limit. `--raw` prints those bytes alone. Report the count and anything
   omitted in a separate message BEFORE the goal.

Read `references/goal-delivery.md` before handing a goal over: the enforced ceiling is
the 3,600-character authoring one, not the 4,000 delivered cap.

## Rules
- **Never hand over a goal you did not measure.** Check an authored one with
  `--check <file|->`; it exits 1 over the limit and names the overage.
- The goal is an **index into the plan, not a copy of it**: plan path, scope, completion
  condition, proof command. Detail lives in the plan.
- Omissions on `goal_assignment_milestones:`/`_acceptance_criteria:` are expected, not
  failures; a `0 of 0` naming a heading means that section could not be read.
- `--char-limit` belongs to a non-Claude host; never raise it to fit an over-long goal.
  `--allow-unfinalized` is a wording dry run only; do not assign that goal.
- The completion clause states the project's **effective** done conditions, including
  the handoff bar. Never hand over one that stops at "a PR is open".

## Required Follow-Through

Emit the goal and give it to the operator in the same turn planning finalized — do not
end the turn with "planning is complete" and no assignable goal.
