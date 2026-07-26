# Board Adoption Policy Reference

This reference keeps the detailed board-schema mismatch adoption policy behind
the concise `board-adoption` skill entrypoint. It preserves the examine,
present, ask, adopt, and never-mutate-the-board rules.

## Core Rule

A board schema mismatch means the adapter's recorded `backlogProvider` no longer
matches the board's live schema: columns, single-select options, fields, or
project metadata. The resolution is always to conform the **adapter** to the
**board**, never to alter the board. The board's schema is human-owned.

Invoke this flow when `tautline backlog-provider-board-check` or
`methodology-status` emits a `board schema mismatch` warning, when
`backlog-provider-update` / `backlog-provider-next` fails because the adapter
references a column or option the board no longer has, or when the operator asks
for board re-adoption.

## Examine

Run:

```bash
tautline backlog-board-examine --target .
```

This command is **read-only**. It reads the board's live schema via `gh`
(fields, single-select options, project metadata), prints the board profile
(project number, field names, option sets), derives plain-English assumptions
such as "Column 'In progress' maps to the active status", lists gaps it cannot
resolve automatically as `board_examine_unknown:` lines, and shows the proposed
`backlogProvider` diff that adoption would write if all unknowns were answered.
It changes nothing, and the proposed-vs-current diff is the operator's chance
to confirm that unrelated adapter keys remain preserved.

## Present And Ask

Show the operator the assumptions and ask **every unknown**. Do not guess or
infer answers to unknowns.

Typical answer keys:

| Unknown key | Meaning |
|-------------|---------|
| `role:<Column>=ready\|active\|done\|blocked\|icebox` | Which workflow role does this column play? |
| `priority_order=<...>` | How is the next item's priority or work order determined? |
| `custom:<Field>=<...>` | What does this ambiguous custom field represent? |

Present assumptions clearly so the operator can correct any wrong assumption
before adoption proceeds.

## Collect Answers

Gather each answer as an `--answer KEY=VALUE` pair for the adopt command. Wait
for the operator to confirm all unknowns are resolved before proceeding.

## Adopt

Run:

```bash
tautline backlog-board-adopt --target . --answer KEY=VALUE [--answer KEY=VALUE ...] --apply
```

The command is **operator-gated**. It refuses to apply while any unknown is
unanswered; surface remaining unknowns and ask again. On success it writes
**only** the adapter's `backlogProvider` block, including `schemaHash` and
`boardProfile`. No other adapter keys are touched. The board is never modified.

## Never Mutate Board Structure

Never run `gh project field-*`, `gh project edit/delete/copy/close/create`, or
any `updateProjectV2Field`, `createProjectV2*`, or `deleteProjectV2*` GraphQL
mutation. These change board schema/structure and are blocked at the PreToolUse
Bash hook. See the `board-item-updates` skill for the full board-structure
prohibition.

## Red Flags

- Reaching for `gh project field-*` or a structural GraphQL mutation to "fix"
  the mismatch means you are about to change the board's schema. Stop. Run
  examine + adopt instead.
- Skipping the examine step and hand-editing `backlogProvider` means the
  `schemaHash` will drift and the mismatch will recur. Always use the adopt
  command.
- Adopting while unknowns remain is invalid; the command refuses. Resolve every
  unknown with the operator first.
- Changing any adapter key outside `backlogProvider` during adoption is out of
  scope; those changes require their own operator-confirmed flow.
