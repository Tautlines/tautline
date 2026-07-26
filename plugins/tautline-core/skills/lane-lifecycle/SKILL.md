---
name: lane-lifecycle
description: Start adapter-backed lanes, auto-update methodology unless locked, manage lane-local methodology locks, inspect adapter drift, and prepare lane-local state.
---

# Lane Lifecycle

Use for lane startup, methodology sync/locks, generated adapter drift, local
resource isolation, current-branch liveness, Graphify readiness, event-log
paths, context rotation policy, work profiles, and lane-local runtime state.

Read `references/lane-lifecycle-policy.md` before interpreting lane-start
output, methodology update behavior, local rescue refs, stale host plugin
metadata, branch liveness, adapter drift, Graphify freshness, Windows/WSL2
runtime checks, or generated-adapter cleanup.

## Fast Path

1. Resolve the methodology CLI from `PATH`, `$MINERVIT_METHODOLOGY_REPO`, or
   `$HOME/.config/minervit/methodology.env`.
2. Run `tautline lane-start --target .` before new work.
3. Run `tautline methodology-status --target . --fail-on-drift`.
4. Read continuity and active goal/milestone/provider output after startup
   gates pass.
5. On PR branches, run `branch-liveness-check --target . --strict`; queued,
   merged, closed, or auto-merge-enabled branches are inactive.
6. Use `lane-run --target . -- <command>` for adapter-isolated local-service
   commands.

## Guardrails

- Product/client lanes do not raw-pull latest methodology by default.
- A missing CLI path is setup recovery, not a failed methodology gate.
- Cached host plugin metadata means restart the host/session; do not mutate
  product files to compensate.
- Adapter cleanup must stay separate from feature work and must not commit
  lane-local state or unrelated product changes.

## Required Follow-Through

When details are needed, load the reference and apply the relevant startup,
sync, lock, runtime, branch, profile, Graphify, adapter-drift, or cleanup rule
before continuing feature work.
