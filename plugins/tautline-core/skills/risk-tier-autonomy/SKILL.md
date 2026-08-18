---
name: risk-tier-autonomy
description: Apply Minervit's risk-tiered autonomy model to decide when an agent should proceed, plan briefly, request approval, or stop for human approval.
---

# Risk-Tier Autonomy

Use whenever choosing whether to proceed, plan, review, ask one blocker
question, or stop for approval.

Read `references/risk-tier-policy.md` before classifying risk, handling
operator approval, estimating work, applying tech-stack defaults, interpreting
permission theater, or deciding whether deployment/closeout is agent-owned.
Read `references/stop-guard-evasion-shapes.md` when a stop-guard or
question-guard check refuses: what fires it, the legal exit, and the knob.

## Fast Path

1. Classify the work from evidence: T0 docs/config nits, T1 ordinary backlog
   work, T2/T3 architecture/security/data/infra/broad behavior work.
2. T0/T1 uses lightweight planning and the relevant gates.
3. T2/T3 requires source-of-truth planning, required review/precheck, and
   explicit or standing approval before implementation.
4. Before implementation, name the proof-of-done evidence that will make
   completion believable.
5. Proceed without asking when the next action is authorized and safe.
6. Ask one exact blocker question only when every viable path changes approved
   scope, risk, cost, security posture, production behavior, or standing
   approval.

## Non-Negotiables

- Do not convert required process into a choice.
- Rejected tools, failed pushes, or missing optional context do not create a
  global stop.
- No implementation-ready plan on deck means plan next, not ask whether to
  plan.
- `@pending`/pending/skipped/disabled/quarantined/wrong-target tests are gaps, not proof.
- Routine reviewed deploy/push closeout is agent-owned when the adapter/plan
  requires it.

## Required Follow-Through

Use the reference for risk tiers, approval boundaries, estimates, stop/deferral
rules, tech-stack policy, deploy ownership, and anti-work-evasion details.
