---
name: goal
description: Use when the operator runs /goal, or asks to write, draft, or compose a goal or agent handoff prompt from a short description, so the response comes back as one bare, assignable goal.
---

# Goal

Compose one assignable goal from the operator's short description, following the anatomy in
`docs/reference/goals.md`. The response you send back is the goal -- see Hand over below.

## Gather

- The one outcome the operator described, restated as a single sentence.
- Where the detail lives: a plan, spec, issue, or file the goal should point at rather than copy.
- What may be touched, and what may not, if the operator said so.

## Compose

Write one flat paragraph -- no headings, no bullets, no code fence -- that states:

- The outcome, as a single sentence naming what "done" builds.
- A pointer to the plan/spec/issue instead of restating its contents.
- The scope boundary, when one is worth stating.
- `Done when:` a falsifiable bar naming the actual handoff line -- merged, or armed to merge
  without further help (auto-merge or merge queue) -- not a way-station like "a PR is open."
- One proof command whose output shows the state.

Do not restate autonomy, blocked-handling, fan-out, or evidence-before-done -- every adapter
already carries them as a standing block (`docs/reference/goals.md` explains why). Add a grant
only when this goal needs MORE than that (rare), as one more clause, not a restatement.

## Verify

Count the composed text's characters in a tool call (for example `wc -c`), not by eye. Keep it
comfortably under ~4000 characters -- most hosts, Claude Code included, refuse a much longer
pasted prompt. Over budget, tighten prose and point at the plan/spec instead of restating it;
never trim the done-when bar or the proof command.

## Hand over

Send caveats -- a trim you made, something you could not verify -- in their own message BEFORE
the goal. Then send the goal as the entire content of the final message: no preamble, no "here's
your goal," no commentary, no code fence. A whole-response copy must yield exactly the goal text,
because that is what gets pasted.
