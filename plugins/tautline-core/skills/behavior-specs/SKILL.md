---
name: behavior-specs
description: Write, review, import, or repair customer-facing behavior specs such as Gherkin using adapter source materials, role vocabulary, and business language.
---

# Behavior Specs

Use for customer-facing behavior specs, Gherkin scenarios, role vocabulary,
source-material traceability, executable coverage, or behavior-spec repair.

Read `references/behavior-specs-policy.md` before drafting scenarios,
adapting source materials, naming actors, exempting behavior specs, or checking
executable coverage.

## Fast Path

1. Load adapter behavior-spec config, source materials, and allowed role
   vocabulary.
2. Preserve business intent and document material deviations.
3. Write one behavior per scenario with exactly one `Given`, one `When`, and
   one `Then`.
4. Use adapter-approved role names; do not invent generic actors.
5. Run behavior-spec status/coverage gates before delivery.

## Non-Negotiables

- Reviewed source materials are upstream source material, not inspiration.
- Missing traceability, wrong roles, multi-behavior scenarios, or inactive
  scenarios are not acceptable coverage.
- Exemptions require a concrete adapter-approved reason.

## Required Follow-Through

Use the reference for source traceability, role vocabulary, scenario quality,
exemptions, executable coverage, and delivery summary requirements.
