# Board Item Updates Policy Reference

This reference keeps the detailed GitHub Project board-item write policy behind the concise `board-item-updates` entrypoint. Read it in full before editing board item status, comments, assignment, issue content, or any Project-related command whose tier is unclear.

## Board Item Updates — what an agent may write, and how

Methodology skills are file-backed policy. If host skill tooling returns `Unknown skill`, resolve the methodology checkout via `$MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, or `tautline version --no-remote` (`methodology_repo`), then read this skill and continue.

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
| Change Status / move a card between **existing** columns | `tautline backlog-provider-update --item <id-or-url> --status "<existing option>"` | Use the board's own option names. If the status you need does not exist on the board, that is a taxonomy mismatch — surface it and route to board-adopt; do **not** create a column. Native sub-issues/subtasks that are also board items have their own Status; parent issue status is not a substitute for board-backed subtask status, and a board-backed subtask in an active status means its parent issue must be active too. The normal active-claim path is `tautline backlog-provider-sync --item <id-or-url> --write`, which moves the selected board item and any board-backed native subtasks active together. Later sanctioned parent status moves reconcile board-backed subtasks too: open non-terminal subtasks follow active/blocked/ready parent transitions, closed/merged subtasks follow done transitions with the same verification evidence before the parent is marked done, and an open board-backed subtask blocks marking the parent done. Sanctioned subtask active-status moves reconcile the native parent active too. Subtask issue/PR closure is independent of board Status: close/finish the subtask through its own issue/PR path first, or update the subtask item directly when that is the selected work item. A native subtask missing from the board blocks parent Done because there is no subtask Status to reconcile. Moving to a done status requires `--verification-evidence`, `--verification-evidence-file`, or `--verification-evidence-url`; the command posts a `## Verification Evidence` issue/PR comment before changing Status. The compatibility `goal-tracker-update` command has the same evidence requirement for done moves, and `goal-advance` carries the same three flags plus an optional milestone `acVerification` key. **Oracle discipline (item 81):** when the linked issue carries a written acceptance-criteria section, that evidence must contain a line-by-line AC pass/fail table with one `| <criterion> | PASS |` or `| <criterion> | FAIL |` row matched to each criterion. Matching is injective, so duplicate or paraphrased rows cannot cover distinct criteria, and a `DEFERRED`/`PARTIAL`/`N/A` verdict is not a row at all. **An unmet criterion is a FAILED AC, never a deferral:** leave the item in an active or blocked status and post the honest table as a progress comment instead of moving it done. Verifying the implementation against itself -- "verified within the shipped model" -- is forbidden; the oracle is the written criteria, and a table built from the code cannot fail. `tautline ac-verify --item <id-or-url> --target .` prints the skeleton from the item's own criteria (and `--out` writes it straight to a file for `--verification-evidence-file`). The gate is governed by `backlogProvider.doneEvidence.acTable` (`off` | `warn` | `strict`, default `warn`): under `warn` the finding prints as `done_evidence_ac_warning:` and the move proceeds, under `strict` it refuses BEFORE any board mutation. An unreadable issue body prints `done_evidence_ac_state: unknown` rather than passing silently. The same check applies to any verification-CLAIMING comment posted through the CLI; a claim written into a PR body, chat or a summary composed outside the CLI is a named residual and is not covered. |
| Reflect milestone completion | the framework-owned `## Milestone Progress` checklist, auto-maintained by `goal-advance` (the goal issue's linked board item) | A marker-delimited block. The agent updates only inside the markers; hand edits inside it are overwritten on the next transition. |
| Claim work for a lane | `gh issue edit <n> --add-assignee @me` | Only to coordinate which lane owns the item. Never reassign away from a human. |
| Add a customer-facing item to the board | `tautline backlog-provider-export ...` | Only via the sanctioned export, which enforces the customer-facing justification. Never bulk-dump repo items. |

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

## PR Reference Contract

A separate agent may mirror build progress onto the board by reading pull
requests and issue states alone. PR text is that agent's only evidence, so the
reference has to be exact and has to distinguish finishing an item from
advancing it.

### Which forms GitHub honours

All three close on merge, and the gate accepts all three:

- `#123` — an issue in the same repository.
- `owner/repo#123` — the cross-repository form. Use it whenever the issue lives
  somewhere other than the PR's own repo; a bare `#123` always resolves against
  the PR's repository and will silently address the wrong issue.
- The full issue URL.

Keywords: `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`,
`resolve`/`resolves`/`resolved`.

### One keyword per issue, each on its own line

`Resolves #A, #B` auto-closes **only #A**. GitHub drops the rest, and nothing
warns, because from GitHub's side nothing went wrong. Write one line per
completed item:

    Resolves #A
    Resolves #B

The own-line convention is for the mirror agent's benefit; GitHub honours an
inline `This fixes #N` identically.

### Advancing versus completing — the decision

Ask one question: **does this PR finish the item, judged by the lane's own
completion gates** (`done-check`, and the acceptance-criteria table when
`backlogProvider.doneEvidence.acTable` requires one)?

- **Yes** — add the closing keyword on its own line. The merge-time auto-close
  is the completion claim, and `backlog-provider-closeout-check` verifies the
  close landed.
- **No** — add NO closing keyword, anywhere. Reference the item in the title
  only. A keyword on an advancing PR auto-closes unfinished work the moment the
  PR merges, and the item then reads Done on a board while the work continues.

### The default branch condition

GitHub honours a PR-BODY keyword only when that PR's base is the repository's
**default** branch. A lane integrating on another branch (`experimental`, a
release train) gets no auto-close when its PR merges, and nothing re-reads the
body later. What carries the claim there is the **squash commit message** —
which derives from the PR title and body — landing on the default branch at
promotion. Two consequences:

- Rule 3's "no keyword in commit messages" is structural on such repos, not
  stylistic: a stray keyword in an advancing PR's squash body sits on the
  integration branch and closes the item at the next promotion, long after
  anyone is watching.
- Verify the close actually happened rather than assuming it. A repository that
  builds its squash message from the PR title alone drops the body keyword, and
  then nothing ever closes.

### The enforcement gap, and the wrong way around it

The closing-reference gate is not yet aligned with this contract. It still
demands a closing keyword from every non-exempt PR body, so an **advancing** PR
that correctly carries none can be refused with `missing_closing_ref`.

The sanctioned resolutions are to bind the item, or to use an exemption that is
actually true of the lane: `allowRepoOnlyGoals` for work that legitimately has
no board item, or a non-development work profile.

**Do not satisfy the demand by adding a reference to an issue the PR does not
implement.** That trades a gate failure for a wrong auto-close on someone
else's item, which is worse in every way, and it is the specific failure rule 4
exists to prevent.
