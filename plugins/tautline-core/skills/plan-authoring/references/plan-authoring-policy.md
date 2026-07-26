# Plan-Authoring Policy Reference

This reference keeps the detailed plan-authoring standard behind the concise
`plan-authoring` skill entrypoint. It explains what the standard shape looks
like, how it is checked, and how enforcement can be dialed up or down per
adapter. It expands on the canonical policy rather than repeating it
verbatim — read `methodology/policy/13-planning.md` for the authoritative
one-line rule.

## Why this exists

Tautline plans read best — and parallelize best — when they are authored as
several independent lanes of work with an explicit map of what can run
alongside what, rather than as one long linear sequence of steps. The
plan-authoring standard is how that proven shape gets applied by default to
every T1+ plan, instead of depending on each author remembering to structure
it that way. It sits on top of `superpowers:writing-plans`: that skill still
owns the mechanics of bite-sized, TDD-shaped tasks; this standard adds the
workstream/dependency/tiering/autonomy scaffolding around those tasks.

## The three-part shape a compliant plan has

A plan is checked against three independent elements. All three must be
present; the mechanical checker (`plan_authoring_standard_issues` in
`plan_authoring.py`, invoked through the `finalize-plan-review` guard) treats
a plan missing any one of them as non-compliant and names exactly which
element is missing so the fix is unambiguous.

1. **A workstream section that actually maps the dependency graph.**
   Somewhere in the plan there must be a heading that reads as "Workstream"
   or "Workstreams" (levels 1-3 both count), and that section must say, in
   plain language, which pieces of work are safe to run at the same time and
   which ones have to wait on something else first. Words like "parallel-safe,"
   "predecessor," "depends on," or an explicit "dependency graph" label are
   what the checker looks for — a bare list of steps with no stated ordering
   relationship does not qualify, even if the work described happens to be
   parallelizable in practice. The point is that the plan states its own
   shape, not that a reader has to infer it.

2. **Model-tier tagging.** The plan needs at least one `model-tier:` tag
   naming `mechanical`, `standard`, or `deep`. This is how the plan tells
   whichever model picks up a given piece of work how much reasoning budget
   it is worth — mechanical steps (regenerating a file, bumping a version)
   shouldn't be routed to the same tier as a from-scratch algorithm design,
   and vice versa. The authoring goal is to tag every individual task block
   (each `### Task` or `### Workstream` heading), not just one somewhere in
   the document — that's what makes tier-based routing actually useful. The
   v1 mechanical checker, though, only verifies that at least one tag is
   present anywhere in the plan; it deliberately does not try to parse and
   verify every task block, because that finer-grained per-task check is
   more prone to false positives (headings that look like tasks but aren't,
   nested/irregular structure, etc.) than the payoff is worth for a first
   version. So a plan can pass the mechanical check today with only one
   tagged task even though it hasn't met the authoring goal — full
   per-task-block coverage checking is documented as a future (v2)
   refinement to the checker, not something `block` mode currently
   guarantees.

3. **An execution-autonomy contract embedded in the task text itself,**
   not just referenced from an external policy doc. Concretely: the plan
   text needs a line that tells the implementer to use their own best
   judgment on execution details, and it needs to point at
   `tautline decision-record` as where non-obvious calls get written down.
   Together these two phrases are what let an agent execute a task without
   stopping to ask permission for every small decision, while still leaving
   an audit trail for the decisions that matter. Embedding this in the plan
   (rather than trusting the implementer to already know the house rule)
   is what makes autonomous, unattended execution of the plan defensible.

These three checks are shared verbatim (same regexes, same wording
requirements) across the checker module, the standard text the checker
prints, this skill, and the canonical policy rule, so there is exactly one
definition of "compliant" anywhere in Tautline.

## Enforcement levels

Whether — and how loudly — the standard is enforced is controlled by the
adapter knob `planning.authoringStandard.enforcement`, checked at the
`finalize-plan-review` seam (the same moment a plan is about to leave
plan mode, get marked ready, or be pushed). There are four levels:

- **`off`** — the guard does not run at all. See "The `off` guarantee"
  below.
- **`observe`** — the guard runs and records what it found, but never
  interrupts the author. A non-compliant plan produces one
  `plan.authoring_standard` line in the guard-event log and finalization
  proceeds exactly as it would have without the guard. Use this level to see
  how much of the existing plan population would fail the standard before
  turning on visible warnings.
- **`advise`** — the default level. A non-compliant plan still finalizes
  successfully, but each missing element is printed as a
  `plan_authoring_standard_warning` so the author sees, in the same terminal
  output as the rest of finalization, exactly what the plan is missing and
  can choose to fix it before moving on.
- **`block`** — a non-compliant plan cannot finalize. The guard exits
  non-zero with a named, specific error (which element(s) are missing,
  not just "invalid plan"), so the failure is always actionable rather than
  a dead end.

Every non-`off` level also writes a `plan.authoring_standard` event to the
guard log, whether or not the plan was compliant, so there is always a
record of what was checked and what was found — `observe` and `advise` just
differ in whether that finding also becomes visible to the author in the
moment.

## The `off` guarantee

Setting `planning.authoringStandard.enforcement` to `off` is a full
passthrough, not a softer version of the standard. With the knob off, this
skill defers entirely to vanilla `superpowers:writing-plans` — no workstream
section, no tiering, no autonomy-contract line is expected, requested, or
checked, and the `finalize-plan-review` guard takes no action at all (no log
line, no warning, no block). This exists so that adopters who want plain
`superpowers` behavior, or who are running a different plan-authoring
convention of their own, are never forced into Tautline's shape. Turning the
standard on is always an explicit adapter choice, and `off` is always
available as an escape hatch back to unmodified upstream behavior.
