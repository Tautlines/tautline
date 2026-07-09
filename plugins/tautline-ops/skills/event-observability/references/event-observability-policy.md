# Event Observability Policy Reference

This reference keeps detailed repo-event logging policy behind the concise
`event-observability` skill entrypoint.

## Core Rule

Use this policy when a boundary, blocker, handoff, review gate, preflight, PR
queue or merge, RCA, context rotation, goal transition, or milestone transition
happens outside a CLI command that already logs the event.

Event logs are local operational evidence. They are not process authority,
product docs, continuity handoffs, session journals, or normal startup context.
They help humans tail live state and help agents audit process gaps, but they do
not define the process.

Repo event logs also must not create product-repo noise. The configured streams
live in machine-local Minervit state, while the source repo keeps only the
methodology, adapter, and delivery artifacts that are meant to be committed.

## Workflow

Discover the log paths when useful:

```bash
minervit-methodology event-log-path --target .
```

Log one compact event through the CLI:

```bash
minervit-methodology log-event --target . \
  --event <event_name> \
  --severity <info|ok|warn|block|fail> \
  --plain "<plain-language event summary>" \
  --next "<concrete next action>"
```

Use `--ref key=value`, `--goal`, `--milestone`, or `--pr` only when those fields
add useful audit context. Never write `events.log` or `events.jsonl` directly:
the CLI performs validation, path normalization, rotation, and locked appends.
Keep `--plain` and `--next` short, plain, and operator-readable. Put technical
identifiers in refs or the technical section of the chat summary.

Event logs do not replace chat-visible operator updates. For long work,
autonomous yields, or PR/milestone/goal boundaries, use the `delivery-summary`
skill in chat and then log the compact event.

## Event Names

Use snake_case event names. Prefer these families:

- `startup`
- `planning_review_gate`
- `plan_review_started`, `plan_review_finished`, `plan_review_failed`,
  `plan_review_finalized`
- `preflight_started`, `preflight_passed`, `preflight_failed`
- `pr_queued`, `pr_merged`
- `blocker`
- `rca_requested`, `rca_written`, `rca_published`
- `continuity_written`
- `session_journal_written`, `session_journal_published`,
  `session_journal_pending`
- `context_rotation`
- `goal_advance_<event>`
- `milestone_advance_<event>`

Use `_started` for events that need a terminal event later. Use `_passed`,
`_finished`, `_failed`, `_blocked`, `_queued`, `_published`, or `_written` for
terminal events.

## Human Tail View

The human-readable file is intended for Baretail or any tailing viewer:

```bash
minervit-methodology event-tail --target . --lines 80
minervit-methodology event-viewer --target .
```

`event-viewer` starts a local HTTP viewer that auto-refreshes and lets the
operator click an event row to inspect the matching JSON payload. It defaults to
`127.0.0.1:18765`, verifies an existing Minervit viewer before reusing a port,
and otherwise moves to a free port. Use the printed URL, not an assumed port.

Each human-readable line should put plain meaning before process labels. Good:

```text
OK   preflight_passed Lane2 feature/x | Full preflight is green | next: push branch
```

Bad:

```text
Two-round cap clean-with-deferrals on tip SHA; awaiting harness
```

## Audit

Use JSONL audit for process-improvement work:

```bash
minervit-methodology event-audit --target . --since 24h --strict
```

Treat audit findings as evidence to inspect, not as process authority. If the
audit shows a gap, repair the missing event or produce the required RCA,
continuity, or journal artifact. Do not backfill events with invented history;
use the real event time and state what is being repaired.

When a boundary was already logged by a CLI command, do not duplicate it with a
second manual event unless the second event records a distinct human-visible
state change or repair.

## Boundaries

- Do not log secrets, raw terminal transcripts, complete review logs, or large
  command output.
- Do not log person-specific absolute paths. The CLI normalizes common paths,
  but agents should still phrase entries as repo-relative or local-state
  references.
- Do not let event logging become a stop signal. Log the boundary, then continue
  with the methodology-authorized next action.
