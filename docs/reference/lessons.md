# Lessons

The process the 2026-08-28 demolition replaced ran for a long time and generated real
incidents. Most of that process left with it; the failure patterns it existed to catch did
not. What follows are those patterns without the ceremony — stated as facts about how a
system like this fails, for a reader to apply or test, not commands to obey.

## Fleet/version-skew

A pinned CLI that renders generated files can silently downgrade content a newer version
wrote. On 2026-08-03 a pinned snapshot runtime (`tautline-snap/998f1910…`) did exactly this: an
implicit render at lane-start overwrote `CLAUDE.md`/`AGENTS.md` with an older template,
clobbering content a newer channel had already rendered and committed, with no version
comparison anywhere in the render path to catch it. The fix that followed only closes the gap
between runtimes at or after that release — the plan that shipped it is explicit about the
residual: "any pin cut before it keeps overwriting newer committed adapters exactly as in the
incident." A release that fixes this class of bug is not enough by itself: the fleet still
needs an explicit roll-forward step, or a checkout pinned before the fix keeps reproducing what
the fix was supposed to close, one machine at a time, with no single event that announces it.

## Remedy text

A refusal that names one hardcoded remedy fails every reader whose runtime cannot use that
remedy. A remedy that derives from the detected runtime instead degrades gracefully: the same
refusal, a different fix, depending on what is actually true when it fires.

`src/tautline_methodology/cli.py`'s upstream-trust gate carries both halves as a live example.
`_generic_pinned_advance_remedy()` is the fallback text — add the reviewed commit to the
pinned allowlist — correct whenever nothing more specific is knowable, and its docstring notes
that it deliberately names a file and an environment variable rather than a verb, because verbs
get removed across releases and files do not. `_resolve_held_refusal()` sits in front of it:
under a pinned policy it always swaps the generic line for a resolved offer, naming the held
candidate's actual version when that can be read and falling back to naming the commit sha
alone when it can't. The same docstring records what happens when this discipline
lapses — an earlier version of the remedy pointed at a convenience verb that rewrote the pins
file, the 2026-08-28 demolition removed that verb, and an operator following the old remedy
text got "invalid choice" while still blocked.

## Relaxed-trust scope

A debug or operator launcher writes relaxed policy session-scoped, never to shared machine
config. The current launcher marks exactly this scope on the write itself —
`OPERATOR_LAUNCHER_MARKER` in `src/tautline_methodology/core/runtime.py` reads in full
`# tautline-operator-launcher: session-scoped, non-blocking` — so the scope is a property of the
code path, not a convention someone has to remember to preserve. The same relaxation written to
shared config instead would turn a one-session convenience into a standing hole in every other
session that machine runs.

## GitHub API economics

Concurrent actors sharing one token share one budget and one blast radius — a runaway consumer
in one lane can starve every other lane authenticating the same way. REST beats point-priced
GraphQL for simple reads: the same question, asked the two ways, has been measured at 1 point
against 102 points. Backing off when the shared budget is low costs the one actor that backs
off a delay; failing hard on the same signal costs every other actor still holding budget,
because a hard failure does not distinguish "this token is actually exhausted" from "this one
call alone would have been expensive."

## Release/registry

An idempotent release re-derives its progress from observable world state — is there a tag, a
release, a registry version that already matches? — rather than from an internal journal that
can say one thing while the world says another. The current release-drift check
(`.github/workflows/release-drift-check.yml`) exists because of exactly this failure: the
repository said 0.9.1 while npm and PyPI both sat at 0.8.2, and nothing looked until someone
happened to compare them by hand. It now runs on a fixed daily schedule and asks the same three
surfaces what version they are on, which turns a silent registry mismatch into a same-day
finding instead of a six-month one.

## Parallel-lane isolation

Namespacing Compose projects, container names, ports, and database names per lane avoids
exactly the collision that machine-wide locks were built to prevent — two lanes racing for the
same port or the same database name is the failure a lock serializes around, and a lane that
never contends for the resource in the first place does not need to wait for one. The locks
stay for whatever genuinely cannot be namespaced this way.

## Automation blast radius

A worktree shares Git refs and fetch state with every other worktree of the same repository,
so scheduled automation running inside one can collide with whatever an interactive session in
a sibling worktree is doing with those same refs at that moment — a `git fetch`, a branch
switch, anything that touches shared state. This repo's own daily readiness automation was
written specifically to avoid that: it runs from the framework checkout itself, calls only the
GitHub API, never runs `git fetch`, and records the reviewed SHA in its own report so a stale
read is visible rather than assumed away. A dedicated clone earns the same guarantee for
whatever genuinely needs a checkout of its own — a credential or a working tree shared between
scheduled automation and interactive development is one either can corrupt while the other is
not watching.

## Working habits

From the retired skills — of the twenty-five Tautline-specific skills the plugin shipped before
2026-08-28, one, `human-instructions`, survived — the working habits that outlasted the
ceremony around them:

- Evidence precedes a success claim. A claim made before the command that would prove it has
  run is a guess wearing the shape of a fact, and reads identically to one until someone checks.
- Three failed fixes mean the design is in question, not the fourth fix. A fourth attempt at
  the same kind of change spends effort exactly where the previous three attempts already
  showed it does not land.
- A reviewer gets a crafted brief and a diff, never a session history. A transcript records
  what happened; a brief records what a reviewer needs in order to judge whether it was right —
  handing over the transcript instead makes the reviewer perform that compression themselves,
  worse, and on the clock.
