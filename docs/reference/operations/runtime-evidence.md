# Runtime Evidence

This reference keeps detailed runtime evidence procedures out of the main
operating manual. These surfaces support observability, accounting, and
framework improvement; they are not product documentation and not process
authority.

## Session Journals (Local-Only)

Adapter-backed lanes default to `sessionJournal.enabled: true`. Journals are
**local-only** as of 0.9.0: a journal narrates the adopter's product work, so it
can never be proven safe to publish. Drafts live under
`.ai-runs/session-journals/` and are ignored lane-local state. There is no
archive branch, and `publish-session-journal` / `publish-pending-session-journals` are disabled
and refuse in every mode.

At every milestone, delivery summary, queued-delivery summary, session summary,
handoff-for-review, or completed execution packet, the agent must refresh
continuity, then prepare and validate a compact session journal in place:

```bash
tautline prepare-session-journal --target . --stdin
tautline validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
```

Both commands write only under the lane's gitignored `.ai-runs/`; nothing leaves
the lane.

The journal is summary-only. It captures what advanced, where the work sits in
the lifecycle, gates/reviews, delays/autonomy breakdowns, continuity outcome,
and methodology improvement signals. It must not include raw logs unless a
methodology RCA explicitly needs a short quote, must not contain secrets, and
must not claim authority over process.

To contribute sanitized signal upstream, enable `"instrumentation": {"enabled":
true}` in the source adapter and publish an instrumentation record, a
closed-vocabulary record with zero product-information capacity:

```bash
tautline publish-instrumentation-record --target .
```

See [`instrumentation.md`](../instrumentation.md) for the record schema.

Default adapter config:

```json
{
  "sessionJournal": {
    "enabled": true,
    "cadence": "milestone",
    "gitIgnoreLocal": true,
    "maxBytes": 12000
  }
}
```

## Repo Event Logs

Adapter-backed lanes default to `observabilityEvents.enabled: true`. Event logs
are machine-local and repo-scoped, not product docs and not process authority.
They exist as repo-scoped event logs for live human tailing and AI/process audits:

```text
$HOME/.local/state/minervit/repo-events/<repo-slug>/events.log
$HOME/.local/state/minervit/repo-events/<repo-slug>/events.jsonl
```

`events.log` is the Baretail-friendly human stream. `events.jsonl` is the
canonical structured stream for audits. `lane-start` and `methodology-status`
print both paths.

Useful commands:

```bash
tautline event-log-path --target .
tautline log-event --target . --event preflight_passed --severity ok --plain "Full preflight is green" --next "Push the branch"
tautline event-tail --target . --lines 80
tautline event-viewer --target .
tautline event-audit --target . --since 24h --strict
tautline event-rotate --target . --force
```

`event-viewer` starts a simple local HTTP viewer, auto-refreshes the running
stream, and lets the operator click an event row to inspect the matching JSON
payload. The default URL starts at `127.0.0.1:18765`; if that port is occupied,
the CLI verifies whether it is the same Tautline viewer before reusing it,
otherwise it automatically chooses the next free port and prints the actual URL.

Agents must use `log-event` for boundary events that happen outside
CLI-controlled commands. They must never write `events.log` or `events.jsonl`
directly; the CLI performs validation, secret detection, path normalization,
rotation, and locked appends.

### Decision ledger read surface

`decision-record` writes structured decision entries to the event log;
`decisions-report` reads them back (machine-local; nothing is published):

```bash
tautline decisions-report --target .
tautline decisions-report --target . --since 24h --until-seq 120 --json
tautline decisions-report --target . --since-seq 40 --until-seq 55
```

- `--target` is repeatable; same-repo worktrees share one event log and are
  de-duplicated, and both `lane` and `lane_id` print so colliding basenames stay
  distinguishable.
- Bounds filter the view (they prove nothing about completeness). `--since` is
  exclusive and accepts a duration (`24h`) or an ISO-8601 timestamp;
  zone-less timestamps mean UTC. `--until` is an inclusive ISO-8601 bound.
  `--since-seq` (exclusive) and `--until-seq` (inclusive) take a non-negative
  integer — including `0` — and require exactly one `--target`.
- Every output is scoped to **retained rotations only** and says so
  unconditionally. `--json` emits one `tautline-decisions-report/v1` envelope
  object with a closed per-decision projection; the human header is
  `decisions: <n> total, <k> hard-to-reverse (retained rotations only)`.

`prepare-session-journal` records the same window in each journal's
`## Session Runtime` section (`decisions_recorded`, a `decisions_report`
convenience pointer that always runs from `.`, and a monotonic
`decisions_watermark_seq`) — see [Session Journals](../session-journals.md).

Default adapter config:

```json
{
  "observabilityEvents": {
    "enabled": true,
    "stateDir": "$HOME/.local/state/minervit/repo-events",
    "humanLog": "events.log",
    "jsonlLog": "events.jsonl",
    "rotateBytes": 5000000,
    "retainedRotations": 5,
    "requiredBoundaryEvents": [
      "startup",
      "planning_review_gate",
      "preflight",
      "pr_queue_merge",
      "blocker",
      "rca",
      "continuity",
      "context_rotation",
      "goal_transition",
      "milestone_transition"
    ]
  }
}
```

## Usage Accounting

Adapter-backed lanes default to `usageAccounting.enabled: true`. Usage
accounting is machine-local, repo-scoped operational evidence; it is not product
documentation and is not process authority:

```text
$HOME/.local/state/minervit/usage/<repo-slug>/usage.jsonl
$HOME/.local/state/minervit/usage/<repo-slug>/usage-rollup.json
```

`usage.jsonl` is the canonical record. `usage-rollup.json` is a convenience
cache generated from the JSONL stream. `lane-start` and `methodology-status`
print both paths plus the default report command.

Useful commands:

```bash
tautline usage-log-path --target .
tautline usage-record --target . --provider claude --model claude-opus --activity plan-review --source manual --confidence estimated --total-tokens 120000
tautline usage-import-claude --target . --path ~/.claude/projects/<project>/<session>.jsonl --since 7d --activity goal-execution
tautline usage-report --target . --since 7d --by product
tautline usage-report --target . --since 30d --by activity
tautline usage-rotate --target . --force
```

Usage records include provider, model, activity, source, confidence, token
fields, optional known cost, goal, milestone, PR, lane, branch, and methodology
version. Exact provider/host numbers should be recorded as `confidence=exact`.
Human estimates must be marked `estimated`. Missing cost data remains unknown;
do not invent exact dollar values from token counts unless the model pricing
source and calculation are explicit.

The first implementation stores local JSONL evidence and can import Claude Code
JSONL usage when the session file is available. Cross-machine S3 rollups remain
a separate backlog follow-up; until then, per-machine reports are authoritative
only for the machine-local records they can read.

Default adapter config:

```json
{
  "usageAccounting": {
    "enabled": true,
    "stateDir": "$HOME/.local/state/minervit/usage",
    "jsonlLog": "usage.jsonl",
    "rollupJson": "usage-rollup.json",
    "rotateBytes": 5000000,
    "retainedRotations": 5
  }
}
```
