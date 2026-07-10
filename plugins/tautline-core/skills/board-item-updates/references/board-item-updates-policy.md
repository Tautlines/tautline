# Board Item Updates Policy Reference

This reference keeps the detailed GitHub Project board-item write policy behind the concise `board-item-updates` entrypoint. Read it in full before editing board item status, comments, assignment, issue content, or any Project-related command whose tier is unclear.

## Board Item Updates — what an agent may write, and how

Methodology skills are file-backed policy. If host skill tooling returns `Unknown skill`, resolve the methodology checkout via `$MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, or `minervit-methodology version --no-remote` (`methodology_repo`), then read this skill and continue.

A GitHub Project board has three layers, and an agent's permission differs at each. **Structure** (columns, fields, options, views, the project itself) is the human's and is blocked at the PreToolUse Bash hook. **Item content** is split in two: a small *collaboration/tracking surface* the agent keeps current as normal work, and the *stakeholder-authored substance* the agent does not touch by default. When the board's item status disagrees with reality, the agent's job is to make the **status** accurate — not to rewrite what the item says.

## The three tiers

| Tier | Examples | Default | Override |
|------|----------|---------|----------|
| 1. Collaboration / tracking surface | comments, Status/column, milestone checklist, self-assign | **Allowed** | — |
| 2. Stakeholder-authored substance | title/summary, body, acceptance criteria, labels, priority, milestone field | **Forbidden** | per-field adapter opt-in |
| 3. Board structure / schema | columns, options, fields, item order, project, views | **Forbidden, always** | none — no product may enable |

## Tier 1 — allowed by default (and exactly how)

Do these freely. Always through the sanctioned path, never raw `gh project ...` or GraphQL.

| Activity | How | Rules |
|----------|-----|-------|
| Post a progress update, status note, blocker, or handoff | `gh issue comment <n> --body "..."` on the item's linked issue | Additive only. Never edit or delete a comment you did not write. |
| Change Status / move a card between **existing** columns | `minervit-methodology backlog-provider-update --item <id-or-url> --status "<existing option>"` | Use the board's own option names. If the status you need does not exist on the board, that is a taxonomy mismatch — surface it and route to board-adopt; do **not** create a column. Native sub-issues/subtasks that are also board items have their own Status; parent issue status is not a substitute for board-backed subtask status, and a board-backed subtask in an active status means its parent issue must be active too. The normal active-claim path is `minervit-methodology backlog-provider-sync --item <id-or-url> --write`, which moves the selected board item and any board-backed native subtasks active together. Later sanctioned parent status moves reconcile board-backed subtasks too: open non-terminal subtasks follow active/blocked/ready parent transitions, closed/merged subtasks follow done transitions with the same verification evidence before the parent is marked done, and an open board-backed subtask blocks marking the parent done. Sanctioned subtask active-status moves reconcile the native parent active too. Subtask issue/PR closure is independent of board Status: close/finish the subtask through its own issue/PR path first, or update the subtask item directly when that is the selected work item. A native subtask missing from the board blocks parent Done because there is no subtask Status to reconcile. Moving to a done status requires `--verification-evidence`, `--verification-evidence-file`, or `--verification-evidence-url`; the command posts a `## Verification Evidence` issue/PR comment before changing Status. The compatibility `goal-tracker-update` command has the same evidence requirement for done moves. |
| Reflect milestone completion | the framework-owned `## Milestone Progress` checklist, auto-maintained by `goal-advance` (the goal issue's linked board item) | A marker-delimited block. The agent updates only inside the markers; hand edits inside it are overwritten on the next transition. |
| Claim work for a lane | `gh issue edit <n> --add-assignee @me` | Only to coordinate which lane owns the item. Never reassign away from a human. |
| Add a customer-facing item to the board | `minervit-methodology backlog-provider-export ...` | Only via the sanctioned export, which enforces the customer-facing justification. Never bulk-dump repo items. |

Everything not in this table is **not** Tier 1. If you are unsure which tier an action is in, treat it as Tier 2 (ask first).

## Tier 2 — forbidden by default, adapter-overridable

These are the stakeholder's authored content. By default an agent does **not** change them. If an agent believes one must change, it **comments and asks** (use the `stakeholder-questions` flow) — it does not edit:

- Issue **title / summary**
- Issue **body / description** (except inside the framework-owned `## Milestone Progress` markers)
- **Acceptance criteria** / behavior contract
- **Labels**, **priority**, and the **milestone field** assignment (the stakeholder's triage)

A product may opt into the **enforced** writes in its adapter. All keys default `false`; a product leaves them default unless it has a deliberate reason to opt in. This block is what the board-item guard reads at the Bash hook:

```jsonc
"backlogProvider": {
  "allowedItemWrites": {
    "title": false,     // gh issue edit --title  /  GraphQL updateIssue
    "body": false,      // gh issue edit --body  (the acceptance criteria live in the body)
    "labels": false,    // gh issue edit --add-label / --remove-label
    "milestone": false  // gh issue edit --milestone
  }
}
```

Setting one `true` permits that write **for that product only**; absence of the block = everything `false`. **Acceptance criteria** are protected by `body` (they live in the issue body). **Priority** is a board single-select field the stakeholder owns; the guard already blocks creating/removing its options, and value-level enforcement of a priority change is a tracked follow-up — until then it is skill-guidance only. An agent that wants any Tier-2 change it cannot make should **comment and ask**, never edit.

## Tier 3 — forbidden always (board structure)

Never add/remove/edit columns, single-select options, or fields; never reorder items; never create/delete/edit/copy/close the project or its views; never run a GraphQL mutation that changes structure or one loaded from a file. These are blocked at the PreToolUse Bash hook. A board-schema mismatch is resolved by re-adopting the adapter to the board, **never** by changing the board. See `canonical-rules.md` and the board-structure guard.

## Red flags — stop

- Reaching for raw `gh project field-*`, `gh project edit/delete`, or a `updateProjectV2Field`/`createProjectV2*` GraphQL call → you are about to change **structure**. Stop.
- Editing an issue **title, body, or acceptance criteria** to "make it match" reality → that is the stakeholder's; **comment and ask** instead.
- Building a hook, script, or commit step that writes the board automatically → an institutionalized bypass. Never.
- The sanctioned status write reports "blocked" → it is a **taxonomy mismatch**, not a reason to use raw `gh`. Surface it, route to adopt, keep status accurate on the columns that exist.

## Common mistakes

- Treating "the board is the source of truth for status" as license to rewrite item **content**. It is not — status, comments, and the milestone checklist only.
- Hand-editing inside the `## Milestone Progress` block expecting it to persist. It is framework-owned and regenerated.
- Using `gh project item-edit` to set a status the board lacks. The board's options are the human's; a missing option means adopt, not create.
