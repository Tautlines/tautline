# Writing a goal

A goal is the one message you hand to an agent -- another session, a fresh Claude Code instance,
a teammate's lane -- to do a piece of substantial work without you in the loop. Its job is narrower
than it looks: name what THIS piece of work is, how to tell it is done, and what it may and may
not touch. It does not need to grant autonomy or explain how to handle being blocked -- every
session already carries those as standing norms in its generated adapter. See "Ambient working
norms" below before you assume a goal has to spell that out.

The `/goal` skill composes one from a short description of what you want done. The anatomy below
is what that skill follows, and what to check by hand if you write one yourself.

## Ambient working norms

Every project's rendered `CLAUDE.md`/`AGENTS.md` carries a standing "Working style" block, present
in every session by construction -- see `docs/reference/lean-migration.md`. It covers working
autonomously and assuming the operator is away, how to handle being blocked (work everything else
in scope exhaustively; ask at most one exact question per true blocker, asynchronously, never a
menu of options), fanning out independent work to subagents, and requiring evidence before
claiming success.

That block is the source of truth for the exact wording. A goal does not restate it: two copies of
the same norm drift the moment one of them changes, and a goal that spends its character budget
re-explaining autonomy has that much less room for the scope that actually distinguishes this
piece of work from every other goal a project will ever compose.

A goal therefore adds only what is goal-specific: the outcome, the acceptance bar, what may and may
not be touched, and -- rarely -- a grant that goes beyond the standing norms. That last one is an
exception, not a default; most goals need none of it.

## The anatomy of a good goal

**A single outcome.** One sentence naming the one thing "done" builds -- `Complete "the CSV
export endpoint"`, not a list of loosely related asks. A goal that bundles several outcomes lets
an agent call the easiest one finished and stop there.

**A pointer, not a copy.** Name the plan, spec, issue, or file that holds the detail, and let the
goal point at it. Restating the detail inside the goal spends the budget below without buying
anything the agent could not read for itself.

**A scope boundary.** Say what may be touched, and -- when it matters -- what may not. Scope creep
is cheap to prevent before the work starts and expensive to argue about after.

**A measurable "Done when."** A falsifiable bar, not a feeling: "the new behavior has tests that
pass" beats "when it feels finished." Quote the source's own acceptance criteria when it has them;
state a plain floor (tests pass, reviewed, working) when it does not.

**The actual handoff line.** The single most commonly missed piece. "Done when: a PR is open"
authorizes exactly the stop this bar exists to prevent -- an agent that opens a PR and then waits
for someone to notice it. Name the real finish line instead: the PR is merged, or armed to merge
without further help (auto-merge or merge queue).

**One proof command.** Something the agent can run whose output shows the state, so "done" is a
command result both of you can read the same way, not a claim either of you has to take on trust.

**Flat and tight.** One paragraph, no headings, no bullets, no code fence -- a goal travels
through a render and a paste, and formatting rarely survives that trip intact. Keep it comfortably
under roughly 4000 characters: most hosts, Claude Code included, refuse to accept a much longer
pasted prompt outright, and the room you save by not restating the ambient norms or the plan is
what buys space for everything above.

## The checklist

- [ ] One outcome, stated as a single sentence
- [ ] Points at the plan/spec/issue instead of restating it
- [ ] States what may be touched, and what may not when that matters
- [ ] "Done when:" names a falsifiable bar, not a feeling
- [ ] The bar names the actual handoff line -- merged, or armed to merge (auto-merge or merge
      queue) -- not just "a PR is open"
- [ ] Names one proof command
- [ ] Adds only what's goal-specific -- does not restate the ambient working norms already in the
      adapter
- [ ] Reads as one flat paragraph, no fence, comfortably under ~4000 characters

## A worked example

> Complete "the CSV export endpoint" described in `docs/specs/csv-export.md`. Scope: add a
> `/export.csv` route and a streaming writer; do not touch the existing JSON export or
> authentication. Done when: the route returns a valid CSV for the sample dataset in the spec,
> large exports stream instead of buffering in memory, and the new behavior has tests that pass on
> the branch tip; and the PR is merged, or armed to merge without further help (auto-merge or
> merge queue). Proof: `pytest tests/test_csv_export.py -q` and the merged or auto-merge-armed PR
> link.

That reads as one flat paragraph in real use -- it is only broken into a blockquote here so it
displays as one block on this page -- and comes in under 600 characters. Notice what it does NOT
say: nothing about being autonomous, nothing about asking permission. That is already ambient.
Most of the budget goes unused even so; spend it on a real scope boundary and a real proof
command, not on padding.

## Handing it over

When a goal is composed and handed to a human to paste, the response IS the goal -- nothing else.
No preamble ("Here's your goal:"), no commentary after it, no code fence around it: a
whole-response copy has to yield exactly the goal text, because that is what gets pasted. Length
and shape checks happen in a tool call, not as printed commentary inside the goal. Anything the
human still needs to know -- a trim you made, something you could not verify -- goes in its own
message BEFORE the goal, never inside it or after it.

## See also

- The `/goal` skill: `plugins/tautline-core/skills/goal/SKILL.md`
- The standing working-style block, and enabling `/goal` in Claude Code from a framework checkout:
  `docs/reference/lean-migration.md#enable-the-claude-code-plugin`
- `docs/reference/handoffs.md` -- the sibling norm for resuming work a goal did not finish in one
  session
