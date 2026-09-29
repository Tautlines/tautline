# Shared work declarations

`tautline work` shows what agents intend to change across local Git worktrees. It helps agents
avoid duplicated effort and coordinate overlapping files or interfaces. It is advisory: no
review, plan, permission gate, lock on edits, daemon, or network request is added.

## The working loop

At wake/resume and before taking new work, read `tautline work status`. Before editing, declare
an outcome and the files, directories, or interfaces you expect to change:

```sh
tautline work declare "Add sign-in endpoint" --path src/auth --interface auth-api --item 42
tautline work status
tautline work update --path src/auth --path tests/auth --pr https://github.com/example/app/pull/7
tautline work finish
```

`work declare` publishes the manifest immediately in the shared Git directory. Peers see it
through `work status`, the advisory `lane-status` startup report, and on stderr before
`backlog take`. The latter still takes the item; declarations are information, not reservations.
An agent taking work without a backlog uses the same `work status` command.

Use `work update` with no extra flags to refresh your declaration after resuming. Refresh when
scope or state changes, not before every tool call. Repeated `--path`, `--interface`, and
`--depends-on` flags replace that whole list on update; use `--clear-paths`,
`--clear-interfaces`, or `--clear-dependencies` to clear it. Paths are repository-relative files
or directories, including ones that do not exist yet. Globs and paths outside the repo are
rejected. Declare `--path .` when the intended scope is the whole repository.

`work update --status blocked --blocker "Needs API decision"` surfaces a blocker. Dependencies
are lane IDs or short descriptions, and interface names describe shared contracts; they are
visible information, with no dependency scheduler. Clear the blocker with
`work update --status active --blocker ""`. All mutations also accept `--pr`.

Finish with `work finish`; stop without completing with `work abandon`. `work status --all`
includes retired declarations, and `--json` returns their structured records, effective states,
and overlap findings. `work declare` replaces your previous manifest; `work update` on a retired
manifest resumes it. Retired records are retained locally until manually removed or replaced.

## What is shared

Records live in `<git-common-dir>/tautline/work/`, outside tracked source. Every worktree of the
same local Git checkout reads the same files immediately. The default lane ID is derived from
the worktree's Git directory and survives agent restarts. If multiple agents intentionally share
one worktree, give each a stable `--lane <name>` on every command, or set `TAUTLINE_WORK_LANE`.
Use separate worktrees when they edit independently. `--target <worktree>` works on every action.

This is **same-machine coordination**. Separate clones, remote machines and hosted agent
sandboxes do not share the store. Declarations contain intent, not proof of current execution,
exclusive ownership, completed tests, or a merged/deployed change.

## Reading the view

- `ACTIVE` and `BLOCKED` are fresh declarations. The view includes owner, branch, worktree,
  goal, item, paths, interfaces, dependencies, blockers, PR, and age.
- `OVERLAP` means two fresh declarations name intersecting file/directory scopes, the same
  interface, or the same item. `src/auth` intersects `src/auth/login.py`, not `src/author.py`.
  Coordinate directly, split scope, or choose another task. Nothing is blocked automatically.
- `STALE` means the record expired, its worktree disappeared, or that worktree changed branch.
  The default expiry is 24 hours; `--expires-hours 1..168` changes it. A crashed agent leaves a
  declaration that eventually becomes stale; there is no claim that a live process was detected.
- `UNKNOWN` means a record or store cannot be read reliably, has invalid fields/a future
  timestamp, or a bounded scan could not finish. It does **not** mean nobody is working there.
- `COMPLETED` and `ABANDONED` retire scope from overlap checks. A surviving peer can retire a
  removed lane explicitly with `work abandon --lane <its-id>`.

Stale and unknown records remain visible but do not count as fresh overlap claims. Inspect them
before deciding work is free. A lane with unreadable JSON must be repaired or its record removed
before rewriting it; the command does not silently discard an unreadable manifest. Startup
reports show up to six declarations; the full view is one command away. Reads are bounded and
local, with atomic per-lane writes; two processes updating the *same* lane are last-writer-wins.

## Adoption

New `tautline init` projects enable a short lifecycle instruction in generated adapters. Use
`tautline init --no-work-coordination` to omit it. Existing lean projects opt in by adding
`"workCoordination": true` to `.tautline.json` and running `tautline render-adapters --target .`.

The flag controls adapter guidance. An explicit declaration remains visible at startup and
before backlog take even when the flag is absent or false. Projects with no declarations and
no opt-in gain no report noise. These commands also work in ordinary Git repositories without
a Tautline adapter; automatic startup notices require a managed Tautline project.

The feature earns its place through less duplicated work, fewer conflicting changes and faster
resumes. It adds no mandatory plan, recurring review, edit gate or polling loop.
