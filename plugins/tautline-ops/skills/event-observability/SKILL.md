---
name: event-observability
description: Write compact repo-scoped event-log entries for human Baretail visibility and JSONL audit evidence without direct file writes or product-repo noise.
---

# Event Observability

Use this skill when a boundary, blocker, handoff, review gate, preflight, PR queue/merge, RCA, context rotation, goal transition, or milestone transition happens outside a CLI command that already logs the event.

Read `references/event-observability-policy.md` in full before defining new event names, repairing audit gaps, relying on viewer behavior details, or deciding whether to backfill an event.

Event logs are local operational evidence. They are not process authority, product docs, continuity handoffs, or normal startup context.

## Fast Path

Discover paths when useful:

```bash
tautline event-log-path --target .
```

Log one compact event through the CLI:

```bash
tautline log-event --target . \
  --event <event_name> \
  --severity <info|ok|warn|block|fail> \
  --plain "<plain-language event summary>" \
  --next "<concrete next action>"
```

Use `--ref key=value`, `--goal`, `--milestone`, or `--pr` only when those fields add useful audit context. Never write `events.log` or `events.jsonl` directly; the CLI handles validation, path normalization, rotation, and locked appends.

## Human Tail View

Use the human-readable stream for Baretail or a local viewer:

```bash
tautline event-tail --target . --lines 80
tautline event-viewer --target .
```

Use the printed viewer URL, not an assumed port. The command is safe as a fast path; read the reference for port reuse, auto-refresh, and JSON payload details.

## Event Shape

Use snake_case names. Use `_started` for events that need a terminal event later; use `_passed`, `_finished`, `_failed`, `_blocked`, `_queued`, `_published`, or `_written` for terminal events. Keep `--plain` and `--next` short, plain, and operator-readable; put technical IDs in refs or the chat summary.

## Required Follow-Through

Event logs do not replace chat-visible operator updates. For long work, autonomous yields, or PR/milestone/goal boundaries, use `delivery-summary` in chat, then log the compact event. Do not log secrets, raw terminal transcripts, complete review logs, large command output, or person-specific absolute paths. Do not let event logging become a stop signal.

For audit gaps, use `tautline event-audit --target . --since 24h --strict` as evidence to inspect, not process authority.
