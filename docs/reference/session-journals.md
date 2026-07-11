# Session Journals

Session journals are **opt-in** (since 0.8.7) evidence files an agent writes at milestone
boundaries to help improve Tautline itself. They are disabled unless your source adapter
explicitly enables them.

As of **0.9.0 they are local-only**. A journal narrates the session — so it inherently
describes **your product work** (features touched, decisions made, PR state) — and that
can never be proven safe to publish. As of 0.9.0 there is no publish step and no new archive
branch: journals stay under the lane's gitignored runs directory and never reach any remote.

> **Legacy archives are not auto-deleted.** Disabling publication stops *new* writes only; it
> does not remove anything already pushed. If a lane published before 0.9.0, a
> `methodology-session-archive` (or similarly named) remote branch may still hold historical
> narrative journals. Tautline will not touch it. Operators must audit each remote and delete
> any such branch by hand (for example `git push origin --delete methodology-session-archive`
> after confirming the contents) to retire the pre-0.9.0 exposure.

## What a journal contains

A journal is a single markdown file (capped by `sessionJournal.maxBytes`, default 12 KB)
with a machine-stamped runtime header (project name, repo slug, lane, branch/HEAD, plugin
version) followed by these sections:

- Starting Context
- Work Delivered Or Advanced
- Planning And Review Gates
- Human Interruptions Or Questions
- Delays, Waits, Or Autonomy Breakdowns
- Validation And PR State
- Continuity Outcome
- Methodology Improvement Signals

Because it narrates the session, it inherently describes your product work. Treat journals
as containing product-confidential context. `validate-session-journal` enforces the
structure, the size cap, and rejects person-specific tokens, but it cannot redact product
substance — which is why the file never leaves the lane.

## Where journals go

Journals are **local-only evidence**. Two commands operate on them, and both write only
under the lane's gitignored runs directory:

1. `prepare-session-journal` writes the file locally under the lane's runs directory
   (`.ai-runs/session-journals/`, gitignored by default via `gitIgnoreLocal`).
2. `validate-session-journal` checks structure, size, and person-specific tokens in place.

There is no publish step. `publish-session-journal` and `publish-pending-session-journals` are **disabled**
as of 0.9.0 and refuse in every mode, printing a migration message and
exiting non-zero; there is no session-archive branch.

## Contributing sanitized signal upstream

To contribute signal back to the framework, use an **instrumentation record** instead of a
journal. Enable it in your **source adapter** (`.tautline/adapter.json`):

```json
"instrumentation": { "enabled": true }
```

then publish a record:

```bash
tautline publish-instrumentation-record --target .
```

An instrumentation record is a closed-vocabulary record with zero product-information
capacity — it cannot carry the narrative a journal does. See
[Instrumentation](instrumentation.md) for the record schema and vocabulary.

## Opting in to journals

Add to your **source adapter** (`.tautline/adapter.json`):

```json
"sessionJournal": { "enabled": true }
```

then re-render the generated files:

```bash
tautline render-adapters --project .tautline/adapter.json --target . --write
```

Optional keys: `cadence` (`milestone` | `session` | `off`), `gitIgnoreLocal`, `maxBytes`.

## Opting out of the startup hint

Lane startup prints a one-line opt-in hint only while your source adapter says nothing
about session journals. Declaring `"sessionJournal": {"enabled": false}` records the
decision and silences the hint permanently.
