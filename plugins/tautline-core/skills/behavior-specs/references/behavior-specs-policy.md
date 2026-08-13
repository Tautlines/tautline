# Behavior Specs Policy Reference

This reference keeps the detailed source-material, role-vocabulary, scenario
quality, review, and executable-coverage policy behind the concise
`behavior-specs` skill entrypoint. Read it before adapting reviewed behavior
materials, interpreting adapter vocabulary, granting exemptions, accepting
inactive scenarios, declaring executable coverage, or finalizing a
customer-facing plan.

## Required Timing

For behavior-spec-enabled projects, every customer-facing system behavior change
needs behavior specs before development starts. The scenarios belong in the
source-of-truth plan/spec and must be reviewed with that plan before
implementation, execution-packet creation, ready-for-development marking,
plan-mode exit, or approval-to-implement prompts.

For non-trivial work, the cross-model plan review must inspect the behavior
specs. Missing, vague, unreviewed, or post-hoc behavior specs are plan blockers.

## Source Materials

Load the active project adapter before writing scenarios. If
`behaviorSpecs.sourceMaterials` is non-empty, inspect those source materials
before authoring new scenarios.

Reviewed business/customer/user behavior specs are upstream source material, not
inspiration. Import, review, normalize, split, and adapt them into executable
behavior specs before creating new scenarios from scratch. Preserve business
intent unless there is a documented conflict, ambiguity, obsolete assumption,
role-vocabulary issue, or execution constraint.

When adapting source materials:

- add `## Behavior Source Materials` to the source-of-truth plan;
- account for every declared source material path as reviewed/adapted or not
  applicable with a real reason;
- cite the source material path and relevant section, heading, scenario, or page
  in the source-of-truth plan;
- keep the reviewed business outcome intact when rewriting syntax;
- split multi-behavior source scenarios into smaller executable scenarios
  without changing intent;
- document every material deviation from the source material in the plan/spec;
- do not replace reviewed business phrasing with implementation mechanics unless
  the source behavior cannot execute as written and the reason is documented.

If source materials conflict with each other or with current product constraints,
record the conflict and the proposed interpretation in the source-of-truth plan.
Ask the human operator only when the conflict changes business scope, product
behavior, risk, or approval boundaries.

Use `BEHAVIOR-SOURCE-EXEMPT: <real reason>` only inside `## Behavior Source
Materials` when reviewed source materials do not apply to the plan. Do not use
the behavior-spec/Gherkin exemption marker to bypass source-material
traceability.

## Role Vocabulary

Use `behaviorSpecs.roleVocabulary.allowed` when present, and otherwise use only
roles proven by current product docs or the system model.

Do not invent generic actors such as `stakeholder`, `user`, `admin`, or
`operator` when the project has more precise roles. If the adapter lists
forbidden behavior-spec actor terms, treat their appearance in new or edited
scenarios as a required fix unless the human operator explicitly changes the
adapter. When documenting a source-material deviation, quote obsolete source
wording in backticks or blockquotes and state the replacement role.

## Scenario Quality

- Write in business language that a real customer, owner, staff member, or
  operator can understand without implementation context.
- One scenario tests one behavior of the system.
- Use exactly one `Given`, one `When`, and one `Then` in each scenario.
- If no setup is needed, write one business-meaningful no-op `Given` rather than
  omitting setup entirely.
- Avoid `And`/`But` chains that smuggle in extra setup, actions, or assertions.
  Split the behavior into separate scenarios instead.
- Do not mention selectors, components, tables, database records, API status
  codes, mocks, fixtures, or test harness mechanics unless the product language
  itself exposes them.
- Scenario names should describe the capability or outcome, not the
  implementation path.

## Review Checklist

Before plan finalization or merge, verify:

- every customer-facing behavior change has an upfront scenario or a valid
  adapter exemption marker;
- declared source materials were inspected and adapted before new scenarios were
  invented;
- every material deviation from reviewed source behavior is documented in the
  source-of-truth plan;
- every scenario uses allowed project roles and avoids forbidden/generic role
  terms;
- every scenario has one behavior and one `Given`/`When`/`Then` structure;
- the suite reads as living documentation for the business owner;
- automated acceptance tests and any living documentation portal use the same
  behavior files when the project expects that.

Missing source-material traceability, wrong roles, multi-behavior scenarios,
duplicate `Given`/`When`/`Then` chains, implementation language, or missing
required scenarios are required fixes, not polish.

## Executable Coverage Integrity

Run `tautline behavior-spec-status --target .` before plan
finalization, merge, delivery summaries, or claiming customer-facing behavior is
covered.

Add `--base <ref>` to that run to see what the branch itself changed. It prints
two counts:

- `behavior_specs_added_inactive: <N> (vs <ref>)` — every scenario newly
  inactive since the merge base with `<ref>`, annotated or not, because a fully
  annotated `@pending` is still growth.
- `behavior_specs_added_issues: <N> (vs <ref>)`, plus one
  `behavior_specs_added_issue:` line citing the canonical form, for each
  scenario the branch left without the owner and un-pend-trigger annotations.

Those are **different sets, not nested.** Stripping the metadata off a scenario
that already existed reports `0` added and `1` issue: the branch introduced debt
without introducing a scenario. Note the check verifies owner and un-pend
trigger; the `@reason:` field is required by policy and carried in the canonical
form, but no automated check reads it.

`--base` compares two committed trees, so an uncommitted edit never moves the
answer. When it cannot see — a blank or unresolvable ref, no common ancestor, an
unreadable feature file, a `behaviorSpecs.paths` scope that selects nothing, or
an unexpected failure — **both counts report `unknown`, never `0`,** with a
`behavior_specs_added_warning:` line naming the reason. A check that could not
look must never print what a clean branch prints. Where the adapter sets
`pendingRequiresOwnerAndTrigger: false`, the issue half reports `disabled by
adapter` and the growth count still reports.

`--base` is **reporting only: it never changes the exit code**, including when
it fails. The enforcement counterpart at the boundary that creates the debt is
`tautline behavior-spec-delta-check`, which refuses the metadata-less scenarios
a staged change introduces and lets pre-existing debt through.

Executable behavior specs must run against the application package that is
actually being changed. If a harness launches a demo app, preview shell, mock
page, or different package while the implementation changes another app package,
name that as skipped validation and fix or declare the correct adapter harness
before delivery.

Inactive scenarios are not coverage and cannot be proof of done. Tags such as
`@pending` are allowed only within the adapter policy and must have a real
owner, reason, and un-pend trigger. A scenario parked because no harness exists
is a P1 coverage gap, not a normal deferral.

Delivery summaries for customer-facing behavior must prominently state any
inactive-scenario count and blocking reason. Do not bury this under technical
details or claim unit tests prove the behavior when the acceptance harness cannot
execute it.
