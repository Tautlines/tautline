# Backlog Epic Grooming Policy Reference

This reference keeps the detailed epic shape, feature-item template,
feature-numbering, privacy-invariant, and read-only validation policy behind the
concise `backlog-epic-grooming` skill entrypoint.

## Core Rule

An epic is a container, not directly executable work. It is consumable only once
it has been **groomed** into feature items that each satisfy the Definition of
Ready. Grooming-decompose (shaping one epic into feature items) is distinct from plan-review cap/focus-transfer handling (carrying unresolved plan findings into implementation review focus when the two-round cap is reached); never conflate them. Memory and Open Brain may inform DoR content but never define it; the DoR is owned by canonical methodology, the generated adapter, and this skill.

## Epic Body Shape

Lead with `## What this delivers` and `## Why it matters` (plain-language
business framing), then `## Technical detail`. Then add a `## Grooming` section
listing the feature items the epic decomposes into, each as a native sub-issue
link. An epic with no DoR-satisfying sub-issues is not ready and must not enter a
ready status.

## Feature-Item Template

Each feature item (a native sub-issue of its epic) MUST contain:

- `## What this delivers` / `## Why it matters` — leading business framing.
- `## Acceptance criteria` — concrete, testable bullets; no TODO, placeholder,
  or one-line restatement.
- `## Verification` — exact commands/artifacts proving each acceptance criterion
  through named tests, validation commands, or check URLs.
- `## Privacy / negative tests` — for any project that declares
  privacy/security invariants, negative tests proving the invariant is NOT
  violated, for example an unauthorized actor cannot read/write the protected
  surface. Omit only when the project declares no privacy invariants and says so.
- A native sub-issue link to the parent epic (provider sub-issue relationship),
  not just a body mention.
- A feature number drawn from the project's configured numbering series.

## Field Conventions

- Epic field: `backlogProvider.epicField` (`<EPIC_FIELD>` in this lane's
  adapter).
- Feature-numbering series: `backlogProvider.featureSeries` — prefer `pattern` for collision detection: it is a regex matched over the feature item's
  title/body and is the RELIABLE mechanism, because native sub-issue nodes carry only number/title/url/body and expose no ProjectV2 field value, so a configured
  `field` reads empty against the real board. Set `pattern` to constrain valid
  numbers as `<PREFIX>-<n>` where `<PREFIX>` is operator-supplied per product
  (do NOT hardcode any prefix in policy; read it from the adapter). `field` may
  still be set for non-sub-issue item shapes that do carry a board field value,
  but if it reads empty for every sub-issue `validate-grooming` emits
  `grooming_feature_series_field_unreadable` and falls back to `pattern`. When
  neither is set, numbering is unenforced and `validate-grooming` says so.
- Statuses: use only the adapter's enumerated statuses; the ready gate is the
  first `readyStatuses` transition.

## Project Privacy Invariants

State this product's privacy/security invariants as adapter-sourced placeholders
(`<PRIVACY_INVARIANT_1>` ...). Every feature item touching the protected surface
needs a negative test proving the invariant holds. If the product has none,
record `no privacy invariants declared`.

## Done-When Checklist

A feature item is Ready when ALL hold:

1. It leads with business framing (`What this delivers` / `Why it matters`).
2. Acceptance criteria are concrete and testable, with no stubs.
3. `## Verification` names proof commands/artifacts for each criterion.
4. Privacy/negative tests are present for every declared privacy invariant it
   touches.
5. A native sub-issue link to the parent epic exists.
6. Feature number is unique within the configured series, with no collisions.
7. `minervit-methodology validate-grooming --target . --epic <EPIC>` exits 0.

Run `validate-grooming` read-only before moving any item into a ready status. It
never edits the board; fix the source item and re-run.
