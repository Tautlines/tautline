---
name: board-item-updates
description: Use when an agent needs to update a GitHub Project board item with sanctioned comments or Status moves while preserving board structure ownership.
---

# Board Item Updates

Use to update GitHub issue/Project item progress comments or board `Status`
through sanctioned methodology commands.

Read `references/board-item-updates-policy.md` before changing item Status,
posting comments, editing issue fields, reconciling subtasks, writing PR refs.

## Fast Path

1. Identify the adapter-backed issue or provider item.
2. Use sanctioned backlog-provider commands, never raw board mutations.
3. Move started work to an adapter-approved active status and shipped work to an
   adapter-approved done status. Before a done move verify against the item's own
   acceptance criteria: `tautline ac-verify --item <ref> --target .` prints the
   skeleton; fill each verdict and pass it with `--verification-evidence-file` (on
   `goal-advance`, `backlog-provider-update`, `goal-tracker-update`).
4. If a board-backed subtask is active, reconcile the parent issue active
   unless the parent is terminal.
5. Reference the item in every PR: issue number in the title; `Fixes #N` on its
   own line only when the PR COMPLETES it; none at all when it advances.
6. Post progress comments only when policy or the adapter requires them.
7. Run board/status validation before delivery boundaries.

## Non-Negotiables

- Never change board fields, options, workflows, columns, or schema.
- Do not edit stakeholder-owned issue title/body/labels/priority unless the
  adapter explicitly allows it.
- Free-text comments do not replace structured board Status.
- Closure verification is measured against the item's WRITTEN acceptance
  criteria, one PASS/FAIL row per criterion. An unmet criterion is a FAILED AC,
  never a deferral: leave the item active or blocked and post the honest table.
  Verifying the implementation against itself is forbidden; the oracle is the
  criteria.

## Required Follow-Through

Use the reference for allowed/forbidden writes, subtask/parent reconciliation,
status validation, delivery boundaries, and the full PR reference contract.
