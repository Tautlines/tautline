# Backlog Provider Workflow

This reference owns detailed external backlog provider behavior: GitHub Project
selection, board status, stakeholder questions, migration/export, item ordering,
and board-backed subtask handling. Goal execution stays in
[Goal Execution](goal-execution.md).

## Provider Authority

When a project uses an external backlog provider for stakeholder-facing goals,
milestones, bugs, or tasks, enable adapter `backlogProvider`. GitHub Projects is
the first supported provider. The external provider can control adapter-declared
stakeholder-facing fields such as priority, order, item type, and board status,
but it does not replace repo source-of-truth planning or tactical PR planning.

Validate GitHub CLI auth and configured Project fields with:

```bash
minervit-methodology backlog-provider-status --target .
```

With no active goal ledger or provider item, select the next ready Project item,
sync it into the repo source of truth, and review the repo plan before
execution:

```bash
minervit-methodology backlog-provider-next --target .
minervit-methodology backlog-provider-sync --target . --item <id-or-url> --write
```

The synced plan links back to the GitHub Project item and preserves the board's
stakeholder/business guidance. It remains non-executable until normal
source-of-truth plan review or a valid adapter-declared exemption passes. Agents
must not implement directly from a GitHub Project item because project cards are
priority and guidance, not tactical execution authority.

Compatibility `goalTracker` remains supported for existing adapters, but new
adapters should use `backlogProvider`.

## Board Status

Provider-backed status is live operational state. `goal-start` moves the mapped
goal item to the adapter-approved active status, `goal-advance --event
goal-complete` moves it to done, and mapped milestone source plans move their
own Project items as milestones start, complete, block, or defer.
`methodology-status --fail-on-drift` reports stale board status or missing
milestone mappings. GitHub issue comments are useful evidence, but they do not replace the structured Project `Status` field.

The stakeholder board must stay current for every customer-facing item type:
goals, milestones, features, bugs, and tasks. Move an item to an active status
when work starts and to a done status when its issue or PR ships. Use only the
adapter-configured statuses and ship straight to done; do not stage shipped work
in a separate review/QA column just because the board has one.

Board currency is a blocking gate, not advisory:

```bash
minervit-methodology backlog-provider-board-check --target .
minervit-methodology methodology-status --target . --strict --fail-on-drift
```

The check reconciles in-scope board items against real issue/PR state. A
closed/merged item must be in a done status, an open item must not sit in a done
status, any item in a status outside the adapter's configured
ready/active/done/blocked status sets is drift, and verified current lane work
that is not active is drift. The pre-push hook runs the same check so
customer-facing work cannot ship while the board is stale.

The only non-blocking case is genuine provider unavailability (`gh`
missing/unauthenticated/offline). That is surfaced as a warning that re-blocks
once connectivity returns, so provider-backed lanes must maintain GitHub CLI
`project` scope.

## Current Work And Subtasks

The board-currency gate is scope-aware. The hard pre-push block judges verified
current lane work: the item the branch/PR closes, any changed source-of-truth
plan/spec mapped to a Project item, or the active ledger item when no branch or
plan points elsewhere. A stale active goal ledger that points to unrelated work
is an early warning, not a terminal push block when the branch's own board item
is current.

Planning counts as starting. When a lane drafts a milestone spec or plan for a
board item, that item must move to the first adapter-approved active status.
`backlog-provider-board-check` and `methodology-status` flag a current-work item
still sitting in `Backlog` or `Ready` as understating progress.

Native GitHub sub-issues/subtasks that are also board items inherit the same
status obligation. This applies to stakeholder-tracked, board-backed subtasks;
internal technical sub-issues stay in the repo backlog unless they are also
customer-facing board work. Parent issue status is not a substitute for board-backed subtask status, and a board-backed subtask in an active status means its parent issue must be active too. The normal active-claim path is:

```bash
minervit-methodology backlog-provider-sync --item <id-or-url> --write
```

That write refreshes the repo plan and moves the selected board item plus any board-backed native subtasks to the first adapter-approved active status before planning/review work proceeds. Later sanctioned parent status moves reconcile board-backed subtasks too; sanctioned subtask active-status moves reconcile the native parent active too.

Subtask issue/PR closure is independent of board `Status`: finish or close the
subtask first, or update the subtask item directly when that is the selected
work item. An open board-backed subtask blocks marking the parent done. A native subtask missing from the board blocks parent Done when the parent is board-backed customer-facing work that declares native subtasks as stakeholder-tracked deliverables. Closed/merged subtasks are evidenced and marked done ahead of the parent.

## Stakeholder Questions

When stakeholders should answer clarifying questions in GitHub, enable adapter
`stakeholderQuestions`. The agent asks on the active issue and tags the
configured stakeholder:

```bash
minervit-methodology stakeholder-question-ask --target . \
  --issue <issue-number-or-url> \
  --question "<one clear question>" \
  --why "<why the answer changes the build>" \
  --needed-for "<goal/milestone/PR scope>"
```

The command writes a hidden `minervit-question` marker, applies the configured
waiting label, and moves the linked Project item to the configured blocked
status when the issue is on the board. At startup and PR/milestone/blocked
boundaries, run:

```bash
minervit-methodology stakeholder-question-status --target . --sync
```

The sync command detects later comments from the tagged stakeholder, records an
answered marker, updates labels, and restores Project status when configured.
GitHub answers are stakeholder input evidence; the lane still syncs the decision
into the repo source-of-truth plan before implementation.

## Migration And Export

For projects with an existing repo backlog, migrate deliberately rather than
replacing the backlog wholesale:

```bash
minervit-methodology backlog-provider-migration-interview --target . --write
minervit-methodology backlog-provider-export --target . --item-path <repo-plan.md> --type <goal|milestone|bug|task> --write
```

The migration interview lists candidate repo goals, milestones, bugs, and tasks
with a plain-language summary. A development lane asks item by item whether each
candidate should be exported for stakeholder prioritization. Only
interview-approved items are sent to GitHub Projects.

Backlog-provider exports create real, numbered repository issues in the adapter
`repo`, add them to the configured project, and link back to the repo source
item. Export creates a real, numbered repository issue in the adapter `repo`.
Board-only GitHub Project draft items are not the default and require explicit `--draft`. Board-only GitHub Project draft items are not a valid fulfillment of an ordinary export; drafts are not repo-visible tracker issues. Do not overwrite
stakeholder-authored external descriptions unless explicitly instructed.

Every backlog item must lead with plain-language business context before
technical detail. Use `## What this delivers`, `## Why it matters`, then
`## Technical detail`. `backlog-provider-export` refuses to create a board item
whose source lacks the two leading business sections with real content, and
existing board items missing the lead are surfaced as non-blocking
`backlog_provider_board_lead_warn` findings.

The board exists only and exclusively for customer-facing functionality and
customer-impacting bugs. Technical debt, refactors, cleanup, internal bugs,
CI/dependency chores, developer-experience work, and test-infrastructure work
stay in the repo backlog. `backlog-provider-export` refuses without
`--customer-facing` and also refuses technical-debt/non-customer-facing items
unless a concrete `--customer-facing-justification` records the customer impact.

Filing a customer-facing bug is not complete until it is on the board. Creating
a GitHub issue with `gh issue create` does not place it on the Project board; a
customer-facing issue must be added to the board with an Item Type and a current
`Status`. `backlog-provider-board-check` warns with
`backlog_provider_board_unplaced_warn` when an open customer-facing issue is not
a board item.

## Board Order And Epic Scope

The board's physical top-to-bottom ordering is the exact order work is taken.
`backlog-provider-next` and compatibility `goal-tracker-next` pick the topmost
workable ready item in the board's order.
The operator's ordering, not a priority tag, decides sequence when
`backlogProvider.workOrder` is `board` (the default). Priority-field selection is
an explicit per-product opt-out and requires `priorityField`.

Board order comes from an explicit numeric `orderField` when configured;
otherwise it comes from the order GitHub returns for the Project's items. For
products without an `orderField`, arrange the Project's item order to match the
intended work sequence.

A lane may be assigned epics with repeated `--epic <name>` flags,
`MINERVIT_LANE_EPICS`, and adapter `backlogProvider.epicField`. Assigned epics
are a hard scope boundary for selection, next-work recommendations, planning,
and analysis. Operator discretion over ordering within the stack does not widen
scope to other epics. If assigned epics contain no ready item, say so and stop
for direction instead of substituting another epic's work.
