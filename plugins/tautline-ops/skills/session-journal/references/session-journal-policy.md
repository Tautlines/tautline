# Session Journal Policy Reference

This reference keeps the detailed compact session-journal workflow behind the
concise `session-journal` skill entrypoint.

## Core Rule

Use this policy at every milestone, delivery summary, queued-delivery summary,
session summary, handoff-for-review, or completed execution packet.

Session journals are evidence only. They are not process authority, product
docs, continuity handoffs, or normal startup context.

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
minervit-methodology prepare-session-journal --target . --stdin
```

4. Include only high-level summary evidence, not raw terminal transcripts.
5. Validate and publish the written journal:

```bash
minervit-methodology validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
minervit-methodology publish-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md --commit --push
```

6. If publish fails, do not ask whether to retry later. Leave the lane-local
   journal pending, record the exact publish blocker in the continuity handoff,
   and continue authorized work unless the current task is methodology analysis
   that depends on the archive. Pending journals are ignored lane-local state
   and may be lost if the machine, checkout, or ephemeral workspace is
   discarded; name that risk in the handoff when publication is still blocked.
7. At startup after `lane-start` and `methodology-status --fail-on-drift` pass,
   publish pending journals:

```bash
minervit-methodology publish-pending-session-journals --target .
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
- Publish to `methodology-session-archive`, not `main`.
- `publish-session-journal --commit --push` uses isolated archive-branch
  publication. Do not write journal archive copies into the active methodology
  release checkout; `--allow-release-checkout-write` is validation/preview-only
  and is not cross-machine durable publication.
- Do not fetch/read the archive branch during normal startup. Fetch/read it only
  for methodology audits, RCA pattern review, or explicit process-improvement
  work.
