---
name: github-projects-reads
description: Use when an agent reads a GitHub Project board — item lists, field values, counts — so a read cannot resolve the wrong board, mistake a renamed field for an absent one, or report a truncated page as the whole board.
---

# GitHub Projects Reads

Use when reading a GitHub Project board. The read-side complement to
`board-item-updates`: that skill governs what an agent writes to a board, this
one governs what it believes after reading one.

Read `references/github-projects-reads-policy.md` before resolving a board,
declaring a field absent, or acting on a bulk read.

## Fast Path

1. Confirm board identity from the adapter pin before any `gh project` command.
2. Read through sanctioned commands (`backlog-provider-status`,
   `backlog-provider-next`, `backlog-provider-board-check`), which count-verify.
3. Cross-check the returned count against the board's own total before acting.
4. If a field looks absent, scan for a semantically equivalent name first.

## Non-Negotiables

- Operator evidence is ground truth. When an observed UI state contradicts an API
  result, the observation wins; debug the query, never re-assert the result.
- Confirm owner and project number from the adapter pin. Never resolve a board by
  display-name resemblance or an owner carried forward unverified.
- No exact field-name match does not mean the field is absent. Scan for
  semantically equivalent names before declaring absence.
- Cross-check every bulk read's count against the board's total. A mismatch needs
  per-item verification before acting.

## Required Follow-Through

- A read that cannot be count-verified is unavailable, not empty: report it and let
  the gate block.
- Record the board identity a sync read from, so a later run can tell which board
  produced the artifact.
