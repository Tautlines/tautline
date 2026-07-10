---
name: backlog-epic-grooming
description: Use when grooming an epic into consumable feature items or checking whether an epic/feature item meets Definition of Ready before ready status.
---

# Backlog Epic Grooming

Use for decomposing epics into feature items, checking feature-item Definition
of Ready, and validating customer-facing backlog item shape before ready status.

Read `references/backlog-epic-grooming-policy.md` before editing epic bodies,
creating feature items, validating acceptance criteria, or handling privacy
negative tests.

## Fast Path

1. Load the adapter backlog/grooming configuration and source epic.
2. Verify the epic has business framing, scope, non-goals, dependencies, and
   acceptance criteria.
3. Decompose into consumable feature items with `## What this delivers`,
   `## Why it matters`, technical detail, acceptance criteria, verification,
   and privacy-negative tests.
4. Keep customer-facing items on the stakeholder board only when they have real
   customer impact.
5. Run the read-only grooming validation gate before marking ready.

## Non-Negotiables

- Do not bulk export or mark items ready without Definition of Ready evidence.
- Do not relabel internal tech debt as customer-facing.
- Do not change board structure during grooming.

## Required Follow-Through

Use the reference for item templates, numbering, Definition of Ready checks,
privacy invariants, and export boundaries.
