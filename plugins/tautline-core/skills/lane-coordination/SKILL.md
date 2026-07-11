---
name: lane-coordination
description: Use when multiple AI lanes work simultaneously in one repo/product, when lanes depend on each other, or when shared contracts, ownership boundaries, routes, schemas, states, APIs, or deployment conventions may change.
---

# Lane Coordination

Use this skill when multiple AI lanes work in the same product or repo, when one lane depends on another, or when shared routes, actors, schemas, state machines, APIs, server actions, storage contracts, deployment conventions, or ownership boundaries may change.

Read `references/lane-coordination-policy.md` in full before resolving stale coordination state, changing cross-lane contracts, or making ownership assumptions in multi-lane work.

## Source Of Truth

Use the git repo as the coordination backbone. Chat is for alerts and discussion; tracked coordination artifacts are the durable source of truth. Lane coordination is mandatory by default for adapter-backed projects.

Adapter `laneCoordination` config defines the cross-lane contract path, lane board path, per-lane status directory, stale-status threshold, and enforcement mode. With default strict enforcement, missing, stale, untracked, uncommitted, or unpushed state in the current lane's own status file, or in the shared contract or lane board, fails `lane-coordination-status`, `methodology-status --strict`, and `methodology-status --fail-on-drift`. Other lanes' stale, untracked, or dirty status files are informational only and never block startup.

## Commands

```bash
minervit-methodology lane-coordination-status --target .
minervit-methodology lane-coordination-bootstrap --target . --write
minervit-methodology lane-coordination-note --target . --lane <lane> --goal "<goal>" --current "<current work>" --depends-on "<dependencies>" --provides "<provided interfaces>" --blockers "<blockers>" --pr "<PR or commit>" --write
```

Use bootstrap only when artifacts are missing outside startup; `lane-start` normally creates them.

## Lane Status

Each lane updates only its own status file, then commits and pushes it before multi-lane implementation or PR queue. Do not put routine progress in one shared status document. The status must name current changes, touched files/routes/contracts/data/API surfaces, dependencies, provided interfaces, blockers, and latest PR or commit.

Local-only status is not coordination. In strict mode, the status file must be tracked, clean in Git, current for the active branch, and pushed to the branch upstream unless it already exists on the shared base.

## Shared Contracts

Do not silently implement an incompatible version of a shared surface another lane owns or consumes. Update the cross-lane contract, open a small shared interface PR, or explicitly take ownership and mark dependent lanes. Shared routes, account semantics, order states, storage interfaces, event names, API/server-action shapes, and deployment conventions should land early before large implementation PRs.

## Required Follow-Through

At startup, milestone boundaries, PR boundaries, and before multi-lane plan finalization, run status, read the cross-lane contract plus relevant lane status files, and update this lane's status before queuing a PR, changing shared contracts, or declaring a blocker. If status files are stale, verify remote main and current PR state before trusting local lane claims. If the next coordination action is derivable from repo artifacts, do not ask the human operator to coordinate lanes manually.
