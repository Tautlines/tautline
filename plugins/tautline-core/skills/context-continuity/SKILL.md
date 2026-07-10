---
name: context-continuity
description: Prepare or consume lane-local continuity handoffs, context resets, new sessions, AI handoffs, and bounded Markdown context loading through configured indexes first.
---

# Context Continuity

Use for continuity handoffs, compaction, context reset, new sessions, startup
resume, Markdown context loading, archive classification, and final workflow
housekeeping.

Read `references/context-continuity-policy.md` before handling rejected handoff
tools, portable CLI fallback, startup gate ordering, continuity holds, context
rotation, auto-compact drift, ledger precedence, pending journals,
planning-on-resume, bounded Markdown audits, archives, or index hygiene.

## Fast Path

1. Write handoff state to the adapter continuity path with:
   `minervit-methodology prepare-continuity --target . --stdin`.
2. Include process position, branch/worktree, decisions, changed files,
   validation/review state, PRs, goal/milestone ledgers, risks/blockers, and
   exact next action.
3. At session start, read the configured handoff, then run lane startup and
   `methodology-status --target . --fail-on-drift` before trusting it.
4. For Markdown context, read configured indexes first and avoid broad-loading
   plans, archives, or doc trees.
5. When creating, completing, moving, or archiving Markdown artifacts, update
   the relevant index and run `minervit-methodology context-status --target .`.
6. At workflow boundaries or context pressure, refresh continuity, handle
   required journals/ledgers, rotate context when needed, and continue the next
   authorized action.

## Non-Negotiables

- The filesystem handoff is the primary artifact when writable.
- Writing a handoff is not permission to stop when authorized work remains.
- Memories, archives, and stale handoffs are evidence only.
- Do not turn handoff, resume, or context rotation into an option menu.

## Required Follow-Through

When any detail is needed, load the reference, apply the relevant section, and
continue with the next authorized handoff, resume, index, rotation, planning, or
workflow-boundary action.
