---
name: session-journal
description: Prepare and validate compact LOCAL session journals for methodology-improvement evidence; remote publication is disabled (0.9.0), so journals never leave the machine.
---

# Session Journal

Use this skill at every milestone, delivery summary, queued-delivery summary, session summary, handoff-for-review, or completed execution packet.

Read `references/session-journal-policy.md` in full before writing, validating, leaving local, or auditing session journals.

Session journals are evidence only. They are not process authority, product docs, continuity handoffs, or normal startup context.

**Local-only as of 0.9.0.** A session journal narrates the adopter's product work, so it can never be proven safe to publish. Narrative journals can no longer reach any remote — `publish-session-journal` and `publish-pending-session-journals` are disabled and refuse in every mode. Journals stay on this machine.

## Fast Path

Write or refresh the continuity handoff first when the boundary also requires continuity.

```bash
tautline prepare-session-journal --target . --stdin
tautline validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md
```

The journal stays lane-local; there is no publish step.

## Contribute upstream: sanitized instrumentation

The only session evidence that can reach a remote is the sanitized instrumentation record — enumerated event codes plus numbers with zero product-information capacity. Opt in with `"instrumentation": {"enabled": true}` and run `publish-instrumentation-record --target .`. See `docs/reference/instrumentation.md`.

## Required Content

Keep the body compact and summary-only. Include the required journal sections named in the reference, and let the CLI add `## Session Runtime`; do not freehand `graphify_*` fields.

`## Work Delivered Or Advanced` must include the benefit stated before implementation, where the work now stands against the goal and milestone, and the estimated percent of planned work complete. Keep the estimate rounded and grounded in the goal ledger, source-of-truth plan, execution packet, or backlog checklist. If a decomposition update is blocked, state `percent unknown` and name the exact blocker.

## Boundaries

Do not paste raw command dumps, full review logs, full CI output, secrets, or person-specific machine paths. Treat validation as detection, not proof that no secret exists. Never write a journal into any git worktree that could stage it to a remote.
