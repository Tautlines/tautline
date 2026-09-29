---
name: handoff
description: Use when the operator runs /handoff, after a merge, before a long or risky operation, or before ending a session, to write or refresh .ai-continuity/HANDOFF.md so a fresh session can resume this work.
---

# Handoff

Write or refresh the one continuity file so a fresh session -- yours restarted, or someone
else's -- can resume without replaying this conversation. Full format and rationale:
`docs/reference/handoffs.md`. Single file, overwritten every time; one page max.

## Gather

- Goal: the current queue item or task, one line.
- Branch and short SHA: `git rev-parse --abbrev-ref HEAD` and `git rev-parse --short HEAD`.
- State: what is done AND VERIFIED (a test you actually re-ran, not one you assume still
  passes), what is still in flight, what is known broken.
- Next: the exact next action a fresh session should take -- a command or a file, not a vague
  direction like "continue the work."
- Gotchas: env quirks, decisions made but not yet obvious from the code, traps a fresh session
  would otherwise rediscover the hard way.

## Write

Create `.ai-continuity/` if it does not exist, then write `.ai-continuity/HANDOFF.md` in this
exact shape, overwriting whatever was there -- latest wins:

```
# Handoff — <ISO-8601 UTC> — <branch>@<short-sha>
## Doing: <goal / queue item>
## State: <what is done AND VERIFIED; what is in flight; what is broken>
## Next: <the exact next action a fresh session should take>
## Gotchas: <anything a fresh session must know: env quirks, decisions in flight, traps>
```

## Confirm

Run `tautline lane-status --target .` and report its `handoff:` line back to the operator as
proof the write landed and is fresh.
