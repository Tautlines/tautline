---
name: merge-queue-monitoring
description: Use merge queue or auto-merge safely: no routine admin merge, queue after local gates, stop watching clean queued PRs, and let startup gates catch later failures/conflicts.
---

# Merge Queue Monitoring

Use when queueing PRs, enabling auto-merge, checking exceptional queue state, or
handling merged/closed/queued branch liveness.

Read `references/merge-queue-policy.md` before admin merge, exceptional queue
monitoring, interpreting merge queue fields, or deciding whether a PR branch is
still active.

## Fast Path

1. Run local gates and required review before queueing.
2. Use merge queue or auto-merge for routine delivery; admin merge is
   break-glass only with documented reason.
3. Once a clean PR is queued, advance lane ledgers and move to the next
   authorized work instead of foreground-watching it.
4. For exceptional in-session checks, inspect authoritative PR state/checks.
5. Treat queued, auto-merge-enabled, merged, or closed PR branches as inactive.

## Non-Negotiables

- Do not use routine `--admin`.
- Do not treat repeated byte-identical queue output or estimated merge time as
  progress.
- Do not keep editing an inactive PR branch.

## Required Follow-Through

Use the reference for queue state, exceptional monitoring, branch liveness,
ledger advancement, and recovery behavior.
