# Stop-guard evasion shapes — the three checks, what they mean, and how to clear them

The canonical rules state the prohibitions. This reference states the *enforcement*: which check
fires, why, and what the legal exit is. It lives in a skill and not in the canonical rules or the
rendered adapter on purpose — the rendered adapter is loaded into every lane's context at every
session start, forever, while a skill loads on demand. Operational detail belongs here.

Source RCAs: `20260701T115759Z` (structured-payload bypass), `20260616T005348Z` (announce-and-stop;
break-glass re-ask), `20260616T132017Z` (self-named default, then an operator menu).

## The bypass these close

The guard input was text-shaped and the guard patterns were prose-shaped, so a forbidden pattern
survived in any other encoding. An `AskUserQuestion` menu stores its options under
`input → questions[] → options[] → label`, which the Stop-hook flattener never walked — so the exact
menu the free-text detector was built to catch was invisible to every guard. Worse, that tool blocks
the turn waiting for the human, so the Stop hook may never fire at all.

## The checks

| id | seam | mode | what fires it |
|---|---|---|---|
| `pretool.question_direction_menu` | PreToolUse on `AskUserQuestion` | **blocking** | The question payload forms a continue-vs-stop or pick-path menu: two or more distinct continue/stop/defer objects, or one plus explicit "how do you want to proceed" phrasing. |
| `pretool.question_self_contradiction` | PreToolUse on `AskUserQuestion` | advisory | The surrounding turn already names a safe/defensible default or a recommendation, and the same turn asks anyway. |
| `pretool.question_standing_authorization_reask` | PreToolUse on `AskUserQuestion` | advisory | The question re-asks break-glass / admin-merge / force-push authorization. |
| `stop.announce_and_stop` | Stop | high-precision tier | The final text asserts an in-progress or next action ("I'm proceeding now", "next I'll") with no evidence after the announcement. |
| `stop.standing_authorization_reask` | Stop | standard (advisory) tier | Same shape as above, in prose. |

### Why two of them are advisory and stay that way

Neither predicate can verify the thing it would be blocking on. The self-contradiction markers are
loose by construction — "I recommend Redis for the cache" satisfies them next to a perfectly genuine
credential question — and the standing-authorization detector cannot see whether a standing approval
actually exists, so blocking it would deny a legitimate *first-time* break-glass blocker question.
They supply telemetry and reason text; the menu shape supplies the block. Promote either one only
after guard-event telemetry shows its false-positive surface is structurally bounded.

## Clearing each one

**`pretool.question_direction_menu`.** Take the next buildable step in this turn. If a genuine fork
remains, ask **one** exact true-blocker question naming the scope, approval, credential, or gate
change — never a direction menu. A question with a single object (which credential, which scope,
which approval condition) does not match and never has.

**`stop.announce_and_stop`.** Do the announced action in the same turn, or replace the announcement
with a named true blocker via `tautline blocker-declare --kind <k> --reason <r>`. Appending evidence
*after* the announcement clears it — "I'm proceeding now — wrote `tests/test_x.py`, committed abc123"
passes, because the turn did the thing it announced.

The position gate is load-bearing and worth understanding before you try to satisfy it: evidence of
*prior* work does not clear the check. The incident shape is a delivery summary of completed work
followed by an unexecuted promise, and such summaries are full of `committed `/`pushed `/`wrote `.
A whole-response marker scan would go silent on exactly the class the check exists to catch, so only
text after the **last** announcement counts.

*Known residual, stated rather than hidden:* the check cannot verify that the trailing evidence
corresponds to the announced object, so a stale marker appended after the announcement still passes.
Correlating them needs tool-call provenance the Stop hook does not have. This is a deliberate
false-negative floor, chosen over false positives.

**`stop.standing_authorization_reask` / `pretool.question_standing_authorization_reask`.** Standing
approval recorded in a source-of-truth plan, packet, backlog row, PR body, or adapter counts once
conditions match. Read those artifacts and act under the recorded approval, or ask one exact blocker
question naming the condition that no longer matches. Reporting a *completed* break-glass push is
narrative and does not fire either check; only an ask-shaped sentence does.

## Modes and how to change them

Three adapter keys under `responseGuard`, each `blocking` | `advisory` | `off`:

- `questionGuard` — the AskUserQuestion seam. Default **blocking**.
- `highPrecisionPhraseChecks` — the high-precision Stop tier. Default **blocking**.
- `phraseChecks` — the standard Stop tier. Default `advisory`, unchanged.

The high-precision tier exists because plain phrase checks default to advisory and no shipped
adapter overrides them, so a new Stop-seam check registered in the standard tier is telemetry-only
in every real lane — a control that reads healthy because nothing ever lets it act. **Admission
rule:** only a check whose false-positive surface is structurally bounded, with multiple independent
carve-outs each pinned by a negative test, may enter the tier. Never reclassify a prose heuristic as
`state` to dodge the advisory default; it stays `phrase` and earns the tier on its carve-outs.

## The wave-3 aggregate budget

Four plans add blocking conditions to this one Stop boundary. Each measured its own false-positive
rate in isolation and nobody owned the aggregate; the risk is a lane that cannot end a turn at all.

`tautline stop-guard-aggregate` measures the **aggregate** stop-blocking rate over a frozen corpus
at maximum enforcement and compares it with the committed baseline in
`methodology/stop-guard/aggregate-baseline.json`. The ceiling is **+2 percentage points across all
four PRs combined**. Every PR in the chain re-measures on its own rebased tip and states the number
in its body; nobody carries a predecessor's number forward.

Until the fourth lands, every check in the chain ships **warn-only** — the events are logged, the
block is withheld — gated by the single constant `WAVE3_STOP_CHAIN_BLOCKING_ENABLED`. The last PR of
the chain flips it in the same commit that records the final measurement.

The corpus digest is pinned into the baseline. That is deliberate: without it a lane whose detector
started firing on legitimate turns could come back under the ceiling by deleting those entries, with
every gate still green.
