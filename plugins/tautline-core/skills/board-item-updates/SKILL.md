---
name: board-item-updates
description: Use when an agent needs to update a GitHub Project board item with sanctioned comments or Status moves while preserving board structure ownership.
---

# Board Item Updates

Use to update GitHub issue/Project item progress comments or board `Status`
through sanctioned methodology commands.

Read `references/board-item-updates-policy.md` before changing item Status,
posting progress comments, touching issue bodies/titles/labels/priority, or
handling parent/subtask status reconciliation.

## Fast Path

1. Identify the adapter-backed issue or provider item.
2. Use sanctioned backlog-provider commands, never raw board mutations.
3. Move started work to an adapter-approved active status and shipped work to an
   adapter-approved done status.
4. If a board-backed subtask is active, reconcile the parent issue active unless
   the parent is terminal.
5. Post progress comments only when policy or the adapter requires them.
6. Run board/status validation before delivery boundaries.

## Non-Negotiables

- Never change board fields, options, workflows, columns, or schema.
- Do not edit stakeholder-owned issue title/body/labels/priority unless the
  adapter explicitly allows it.
- Free-text comments do not replace structured board Status.

## Required Follow-Through

Use the reference for allowed writes, forbidden writes, subtask/parent
reconciliation, status validation, and delivery-boundary behavior.
