---
name: board-adoption
description: Use when a backlogProvider board schema has diverged from the adapter and the agent must re-align the adapter to the board without changing the board.
---

# Board Adoption

Use when GitHub Project fields/options/statuses differ from the adapter and the
adapter needs to be adopted to the board. The board is human-owned.

Read `references/board-adoption-policy.md` before examining project fields,
proposing adapter changes, applying adoption, or handling unknown board schema.

## Fast Path

1. Examine the board with the sanctioned backlog-provider/board commands.
2. Report assumptions, unknowns, and the exact adapter fields that would change.
3. Ask only the specific operator questions needed to adopt safely.
4. Apply changes to the adapter only after confirmation.
5. Rerender generated adapters and run adapter/schema/status validation.

## Non-Negotiables

- Never change board structure, fields, options, workflows, or project schema.
- Do not guess status mappings when the board is ambiguous.
- Do not continue feature work while adapter/board schema drift blocks the lane.

## Required Follow-Through

Use the reference for board examination, adoption prompts, adapter updates, and
post-adoption validation.
