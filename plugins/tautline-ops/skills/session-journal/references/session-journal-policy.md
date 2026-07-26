# Session Journal Policy Reference

This reference keeps the detailed compact session-journal workflow behind the
concise `session-journal` skill entrypoint.

## Core Rule

Use this policy at every milestone, delivery summary, queued-delivery summary,
session summary, handoff-for-review, or completed execution packet.

Session journals are evidence only. They are not process authority, product
docs, continuity handoffs, or normal startup context.

**Local-only as of 0.9.0.** A session journal narrates the adopter's product
work, so it can never be proven safe to publish. Remote publication is disabled:
`publish-session-journal` and `publish-pending-session-journals` refuse in every
mode. Journals stay on this machine as local evidence. The only session evidence
that can reach a remote is the sanitized instrumentation record (zero
product-information capacity) — `publish-instrumentation-record`; see
`docs/reference/instrumentation.md`.

## Workflow

1. Write or refresh the continuity handoff first when the event also requires
   continuity.
2. Resolve the methodology CLI through the standard lane-lifecycle fallback if
   `minervit-methodology` is missing from `PATH`: source
   `$HOME/.config/minervit/methodology.env` or use
   `$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology`. Do not skip journal
   writing just because the command is not initially on `PATH`.
3. Prepare a compact journal:

```bash
tautline prepare-session-journal --target . --stdin
```

4. Include only high-level summary evidence, not raw terminal transcripts.
5. Validate the written journal (read-only; there is no publish step):

```bash
tautline validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
```

6. The journal stays lane-local. It is ignored lane-local state and may be lost
   if the machine, checkout, or ephemeral workspace is discarded — that is
   expected, because narrative journals never leave the machine. Do not attempt
   to publish or archive it to any remote.
7. To contribute sanitized signal upstream, opt in with
   `"instrumentation": {"enabled": true}` and run:

```bash
tautline publish-instrumentation-record --target .
```

## Required Sections

The journal body must include:

- `## Starting Context`
- `## Work Delivered Or Advanced`
- `## Planning And Review Gates`
- `## Human Interruptions Or Questions`
- `## Delays, Waits, Or Autonomy Breakdowns`
- `## Validation And PR State`
- `## Continuity Outcome`
- `## Methodology Improvement Signals`

The CLI adds `## Session Runtime`, including Graphify freshness evidence from
the same status record used by `graphify-status`. Do not freehand `graphify_*`
fields.

`## Work Delivered Or Advanced` must include the benefit stated before
implementation, where the work now stands against the goal and milestone, and
the estimated percent of planned work complete. Keep the estimate rounded and
grounded in the goal ledger, source-of-truth plan, execution packet, or backlog
checklist. If a decomposition update is blocked, state `percent unknown` and
name the exact blocker.

## Boundaries

- Keep the journal compact and summary-only.
- Do not paste raw command dumps, full review logs, full CI output, secrets, or
  person-specific machine paths.
- Treat validation as detection, not proof that no secret exists. The primary
  control is summary-only content with no raw logs.
- Raw `.ai-runs/` logs stay lane-local and ignored.
- Journals are local evidence only; there is no archive branch and no publish
  step. `publish-session-journal`/`publish-pending-session-journals` are disabled
  and refuse in every mode (removal at >=1.0.0).
- Never write a journal (or a copy of one) into any git worktree.
  `prepare-session-journal` refuses to write a preview that is not git-ignored,
  so a broad `git add` can never stage narrative toward a remote.
- Do not fetch/read any remote archive branch during normal startup.
