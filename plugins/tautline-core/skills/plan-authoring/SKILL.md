---
name: plan-authoring
description: "Author Tautline plans in the standard shape: parallel autonomous workstreams + dependency graph, per-lane isolation, embedded execution-autonomy language, per-task model-tier tags. Wraps superpowers:writing-plans."
---

# Plan Authoring

Use when writing any T1+ implementation plan. This skill wraps `superpowers:writing-plans`.

Read `references/plan-authoring-policy.md` before authoring.

## Fast Path
1. Run `tautline plan-authoring-standard` to load the required shape.
2. If the `superpowers:writing-plans` skill is available, invoke it for the bite-sized TDD task mechanics. It is a recommended companion, not a bundled dependency — if it is not installed (e.g. Codex, or a Claude setup without the Superpowers plugin), skip this step and author the bite-sized tasks directly; the standard below is what matters.
3. Layer the standard on top: a `## Workstreams` section + dependency graph (parallel-safe vs. hard-predecessor), per-lane worktree assignment, per-task `model-tier:` tags, and the embedded autonomy contract (best judgment + `decision-record`) in each task.
4. Finalize via review-before-push; the `finalize-plan-review` guard checks the shape per the adapter's `planning.authoringStandard.enforcement`.
5. Once `plan-finalization-precheck` passes, hand the plan to a builder lane with the `goal-assignment` skill — do not end the turn with a finalized plan and no assignable goal.

## Non-Negotiables
- If `planning.authoringStandard.enforcement` is `off`, this skill imposes no shape — author with vanilla `superpowers:writing-plans` (or directly, if that skill is unavailable).
- Never hand-shape a linear plan when the knob is `advise`/`block`; the guard will warn or reject.

## Required Follow-Through
Load `references/plan-authoring-policy.md` and continue authoring in the standard shape.
