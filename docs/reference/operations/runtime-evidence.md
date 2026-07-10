# Runtime Evidence

This reference keeps detailed runtime evidence procedures out of the main
operating manual. These surfaces support observability, accounting, and
framework improvement; they are not product documentation and not process
authority.

## Session Journal Archive

Adapter-backed lanes default to `sessionJournal.enabled: true`. Local journal
drafts live under `.ai-runs/session-journals/` and are ignored lane-local state.
Published copies live on the `methodology-session-archive` branch under
`docs/backlog/session-journals/<project>/<year>/`.

At every milestone, delivery summary, queued-delivery summary, session summary,
handoff-for-review, or completed execution packet, the agent must refresh
continuity, prepare and validate a compact session journal, and publish it:

```bash
minervit-methodology prepare-session-journal --target . --stdin
minervit-methodology validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
minervit-methodology publish-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md --commit --push
```

The journal is summary-only. It captures what advanced, where the work sits in
the lifecycle, gates/reviews, delays/autonomy breakdowns, continuity outcome,
and methodology improvement signals. It must not include raw logs unless a
methodology RCA explicitly needs a short quote, must not contain secrets, and
must not claim authority over process.

Publishing failure is visible but not a stop signal. Leave the lane-local journal
pending, record the exact publish blocker in `.ai-continuity/NEXT_SESSION.md`,
and run:

```bash
minervit-methodology publish-pending-session-journals --target .
```

after the next session's startup gates pass. Agents should fetch/read
`methodology-session-archive` only for methodology audits, RCA pattern review, or
explicit process-improvement work.

Default adapter config:

```json
{
  "sessionJournal": {
    "enabled": true,
    "branch": "methodology-session-archive",
    "archiveDir": "docs/backlog/session-journals",
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
minervit-methodology event-log-path --target .
minervit-methodology log-event --target . --event preflight_passed --severity ok --plain "Full preflight is green" --next "Push the branch"
minervit-methodology event-tail --target . --lines 80
minervit-methodology event-viewer --target .
minervit-methodology event-audit --target . --since 24h --strict
minervit-methodology event-rotate --target . --force
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
minervit-methodology usage-log-path --target .
minervit-methodology usage-record --target . --provider claude --model claude-opus --activity plan-review --source manual --confidence estimated --total-tokens 120000
minervit-methodology usage-import-claude --target . --path ~/.claude/projects/<project>/<session>.jsonl --since 7d --activity goal-execution
minervit-methodology usage-report --target . --since 7d --by product
minervit-methodology usage-report --target . --since 30d --by activity
minervit-methodology usage-rotate --target . --force
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
