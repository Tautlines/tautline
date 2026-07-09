---
name: review-before-push
description: "Run risk-tiered review workflows: T2/T3 plan review, native Stage 1 sweep, T1+ cross-model implementation review, Critical/P1 blocking, and lower-severity routing."
---

# Review Before Push

Use before finalizing non-trivial plans or pushing code/process changes. Risk
tier decides review ceremony.

Read `references/review-before-push-policy.md` before plan finalization,
exemptions, native Stage 1 sweeps, Stage 2 evidence, Codex CLI finding
retrieval, review ledgers, round budgets, final preflight, stale/wedged review
recovery, or Critical/C1/P1/P2/P3/Nit routing.

## Fast Path

1. Confirm main is green using the adapter command.
2. Run `branch-liveness-check --target . --strict` before commit/review/push or
   tactical subagent dispatch on a PR branch.
3. Run adapter-required fast/full local gates.
4. For T2/T3 plan/spec finalization, run one native/self-check, one bounded
   cross-model plan-review round, finalize the trusted log, then run
   `plan-finalization-precheck --target . --plan <source-of-truth-plan>`.
5. For implementation review: T0 uses self-review and gates; T1 uses one
   cross-model round; T2/T3 adds native Stage 1 sweep evidence before Stage 2.
6. Retrieve, inspect, classify, and finalize review output before push.

## Non-Negotiables

- Required review is not optional.
- Do not merge known Critical/C1/P1 defects.
- Critical/C1/P1 findings are repair work items, not stopping points.
- Per-task, subagent, or milestone reviews do not satisfy the assembled-diff
  pre-push gate.
- Review round limits are escalation controls, not permission to ship blockers.
- Active review runs require monitor/log/liveness evidence until consumed.

## Required Follow-Through

When any review detail is needed, load the reference, apply the relevant plan,
native Stage 1, Stage 2, evidence, blocker-routing, or supervision rule, and
continue the review gate.
