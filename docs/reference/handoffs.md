# Continuity handoffs

One file: `.ai-continuity/HANDOFF.md`. It exists so an operator can kill any session -- on
purpose, mid-task, or because it died -- and a fresh session (yours, or someone else's) picks up
exactly where the last one left off, without replaying the whole conversation.

## The file

Single file, overwritten every time. Latest wins -- there is no history to preserve inside it,
and no numbering, because a chain of past handoffs is not a chain a fresh session has time to
read. One page max: if it does not fit on a screen, a fresh session will not read all of it.

```
# Handoff — <ISO-8601 UTC> — <branch>@<short-sha>
## Doing: <goal / queue item>
## State: <what is done AND VERIFIED; what is in flight; what is broken>
## Next: <the exact next action a fresh session should take>
## Gotchas: <anything a fresh session must know: env quirks, decisions in flight, traps>
```

Each field is one line, inline after its heading -- this is not a document with sections that
grow paragraphs under them. `State` distinguishes what you actually re-ran and watched pass from
what you believe is still true; `Next` is a concrete action (a command, a file, a decision),
never "continue the work."

`.ai-continuity/` is scratch, the same as `.ai-work/` and `.ai-runs/`: expected to be
gitignored, never archived by `tautline slim`, and not read by anything except a session start
and the operator.

## Turning it on

Set `"handoffs": true` in the lean `.tautline.json`. This buys two lines in the generated
adapter (`CLAUDE.md` / `AGENTS.md`), which is the norm that actually gets a fresh session to
read the file: on session start, read it if present and continue from it; refresh it at
checkpoints -- after a merge, before long or risky operations, and when the operator asks.

The freshness line below and the `/handoff` skill work whether or not the flag is set, the
moment a handoff file exists -- the flag only controls whether the generated adapter tells the
agent to read and refresh one on its own.

## Writing one

Run `/handoff`. The skill gathers the current goal, branch, short SHA, and state, writes the
file in the shape above, then confirms with the freshness line (below) so you can see the write
landed. You can also write the file by hand; nothing about the format requires the skill.

`/handoff` ships in the `tautline-core` Claude Code plugin. If the slash command is not
available, see `docs/reference/lean-migration.md#enable-the-claude-code-plugin` for how to turn
it on from a framework checkout.

## Freshness in `lane-status`

`tautline lane-status` reports one advisory line:

- `handoff: <age> old — <first Doing line>` when the file exists.
- `handoff: none` when `handoffs` is on but no file has been written yet.
- No line at all on a project that has neither.

Never blocking -- same as the rest of `lane-status`. It is the cheapest way to notice a handoff
has gone stale (a session ran for hours without refreshing it) or was never written before a
prior session ended.
