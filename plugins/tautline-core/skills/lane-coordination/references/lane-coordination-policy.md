# Lane Coordination Policy Reference

This reference keeps the detailed cross-lane coordination policy behind the
concise `lane-coordination` skill entrypoint.

## Core Rule

Use this policy when multiple AI lanes work in the same product or repo at the
same time, when a lane depends on another lane's work, or when a lane discovers
that it must change a shared route, actor, schema, state machine, API, server
action, storage contract, deployment convention, or ownership boundary.

Use the git repo as the coordination backbone. Chat is for alerts and
discussion, not durable coordination state. Tracked coordination artifacts are
the durable source of truth, and lane coordination is mandatory by default for
adapter-backed projects.

## Adapter-Owned Paths And Enforcement

The adapter config `laneCoordination` defines:

- the cross-lane contract path;
- the lane board path;
- the per-lane status directory;
- the stale-status threshold;
- the enforcement mode, which defaults to `strict`.

`lane-start` creates missing coordination artifacts. With default strict
enforcement, missing, stale, untracked, uncommitted, or unpushed state in the
current lane's own status file, or in the shared contract or lane board, fails
`lane-coordination-status`, `methodology-status --strict`, and
`methodology-status --fail-on-drift`. Other lanes' stale, untracked, or dirty
status files are informational only and never block startup.

Run:

```bash
minervit-methodology lane-coordination-status --target .
```

If coordination artifacts are missing outside startup, initialize them with:

```bash
minervit-methodology lane-coordination-bootstrap --target . --write
```

## Lane Status Files

Each lane updates only its own status file, then commits and pushes it before
multi-lane implementation or PR queue. Do not have every lane edit one large
status document for routine progress.

Use:

```bash
minervit-methodology lane-coordination-note --target . --lane <lane> --goal "<goal>" --current "<current work>" --depends-on "<dependencies>" --provides "<provided interfaces>" --blockers "<blockers>" --pr "<PR or commit>" --write
```

The lane status must make these plain:

- what this lane is currently changing;
- what files, routes, contracts, data records, or APIs it touches;
- what it depends on from other lanes;
- what it provides to other lanes;
- blockers;
- latest PR or commit.

In strict mode, a local-only status file is not coordination. The status file
must be tracked, clean in Git, current for the active branch, and pushed to the
branch upstream unless it already exists on the shared base.

## Shared Contract Changes

If a lane discovers it must touch something another lane owns or consumes, it
must not silently implement an incompatible version.

Do one of these:

- update the cross-lane contract with the required interface and mark the
  provider lane;
- open a small shared contract/interface PR that dependent lanes can rebase
  onto;
- explicitly take ownership of that slice and mark other lanes as depending on
  it.

Shared routes, account semantics, order states, storage interfaces, event names,
and API/server-action shapes should land early before large implementation PRs.
Deployment conventions are also shared contracts when multiple lanes depend on
the same release path.

## Startup And Boundaries

At startup, milestone boundaries, PR boundaries, and before plan finalization for
multi-lane work:

1. Run `lane-coordination-status`.
2. Read the cross-lane contract and relevant lane status files before making
   ownership assumptions.
3. Update this lane's status before queuing a PR, changing shared contracts, or
   declaring a blocker.
4. If status files are stale, verify remote main and current PR state before
   trusting local lane claims.

Do not ask the human operator to manually coordinate lanes when the next
coordination action is derivable from the repo artifacts.
