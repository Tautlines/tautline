---
name: session-journal
description: Prepare, validate, and publish compact session journals for methodology improvement evidence without adding normal-session noise to main or startup context.
---

# Session Journal

Use this skill at every milestone, delivery summary, queued-delivery summary, session summary, handoff-for-review, or completed execution packet.

Read `references/session-journal-policy.md` in full before writing, validating, publishing, leaving pending, or auditing session journals.

Session journals are evidence only. They are not process authority, product docs, continuity handoffs, or normal startup context.

## Fast Path

Write or refresh the continuity handoff first when the boundary also requires continuity.

Prepare a compact journal:

```bash
minervit-methodology prepare-session-journal --target . --stdin
```

Validate and publish the written journal:

```bash
minervit-methodology validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
minervit-methodology publish-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md --commit --push
```

If `minervit-methodology` is initially missing from `PATH`, resolve it through the lane-lifecycle fallback instead of skipping the journal.

After startup gates pass, publish pending journals:

```bash
minervit-methodology publish-pending-session-journals --target .
```

## Required Content

Keep the body compact and summary-only. Include the required journal sections named in the reference, and let the CLI add `## Session Runtime`; do not freehand `graphify_*` fields.

`## Work Delivered Or Advanced` must include the benefit stated before implementation, where the work now stands against the goal and milestone, and the estimated percent of planned work complete. Keep the estimate rounded and grounded in the goal ledger, source-of-truth plan, execution packet, or backlog checklist. If a decomposition update is blocked, state `percent unknown` and name the exact blocker.

## Boundaries

Do not paste raw command dumps, full review logs, full CI output, secrets, or person-specific machine paths. Treat validation as detection, not proof that no secret exists. Raw `.ai-runs/` logs stay lane-local and ignored.

Publish to `methodology-session-archive`, not `main`. `publish-session-journal --commit --push` uses isolated archive-branch publication; do not write archive copies into the active release checkout.

If publish fails, leave the lane-local journal pending, record the exact publish blocker and machine-local loss risk in the continuity handoff, and continue authorized work unless current methodology analysis depends on the archive.

Do not fetch/read the archive branch during normal startup.
