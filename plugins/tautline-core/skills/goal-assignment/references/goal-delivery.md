# Goal delivery: the transport is part of the goal

## The goal is the whole response

**A goal handed to a human for transport is the sole content of the response, unadorned — no
preamble, no trailing commentary, no code fence.** A whole-response copy must yield exactly the
goal and nothing else. Anything the human needs to know about it — the character count, what was
omitted, whether the plan was finalized — goes in a **separate message before it**, never wrapped
around it.

This is not a style preference. A goal's real path is `source → markdown render → terminal →
human copy → paste`, and every stage in the middle can add bytes the length check never saw. A
compliant 3,659-character goal was measured with only 5.17 spaces per line of headroom against the
4,000-character cap: a renderer indenting code blocks by six spaces delivers an over-limit goal
that had passed validation. A fence, a label, or a "here's your goal:" preamble spends the same
reserve.

## Two ceilings, and which one is enforced

| Ceiling | Value | What it is |
|---|---|---|
| Authoring | 3,600 | What `goal-assignment` enforces and composes to. |
| Delivered | 4,000 | The host's paste-time cap. |

The 400-character gap is the reserve that absorbs transport inflation. `goal_assignment_headroom`
is measured against the **authoring** ceiling, and a refusal names both numbers so the author can
see the margin they are spending. Do not raise `--char-limit` to make an over-long goal fit; that
flag exists for hosts whose real cap differs.

## Write the file

```
tautline goal-assignment --target . --plan <plan> --out .ai-work/goal.txt
```

A goal is an artifact, not chat prose. The file bypasses every renderer between composition and
paste, and the printed `goal_assignment_copy_command` (`pbcopy < file`, or `xclip` / `wl-copy`)
delivers it byte for byte.

## What the completion clause says

The composed clause states the project's **effective** done conditions — `goal_assignment_done_conditions:`
names them — rather than a fixed sentence, so it always matches what `done-check` and
`goal-advance` actually enforce for that adapter. It includes the handoff bar (the PR merged, or
armed to merge without the lane via auto-merge or the merge queue) unless the adapter disables
`pr_handed_off`.

Never hand over a goal whose completion clause stops at "a PR is open". That authorizes the exact
90–95% stop the done bar exists to close, and `goal_assignment_shape_issues` now refuses it.
