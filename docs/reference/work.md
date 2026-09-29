# Shared work declarations

`tautline work` shows what agents intend to change. Local sibling worktrees share declarations
by default; projects can opt into a Git branch shared across clones, computers, and people.
It helps agents avoid duplicated effort and coordinate overlapping files or interfaces.
It is advisory: no review, plan, permission gate, lock on edits, or daemon is added.

## The working loop

At wake/resume and before taking new work, read `tautline work status`. Before editing, declare
an outcome and the files, directories, or interfaces you expect to change:

```sh
tautline work declare "Add sign-in endpoint" --path src/auth --interface auth-api --item 42
tautline work status
tautline work update --path src/auth --path tests/auth --pr https://github.com/example/app/pull/7
tautline work finish
```

`work declare` saves the manifest immediately in the shared local Git directory. Peers see it
through `work status`, the advisory `lane-status` startup report, and on stderr before
`backlog take`. The latter still takes the item; declarations are information, not reservations.
An agent taking work without a backlog uses the same `work status` command. With the Git
backend enabled, mutations also attempt a bounded sync to the configured metadata branch.

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
manifest resumes it. Local retired files move into the work store's `retired/` directory and
remain available for inspection until manually removed or replaced. `--all` includes a bounded
sample of up to 32 retired records from the last seven days; it is not a permanent history browser.
Live claims have a separate 256-record limit, so routine task turnover does not consume it.
Local scans are bounded (4096 directory entries and a short read budget); an incomplete live
scan reports UNKNOWN and does not replace the shared namespace. Older flat local records are
still readable. Git history retains published versions even after cleanup of the branch tip.

## Local coordination

Records live in `<git-common-dir>/tautline/work/`, outside tracked source. Every worktree of the
same local Git checkout reads the same files immediately. The default lane ID is derived from
the worktree's Git directory and survives agent restarts. If multiple agents intentionally share
one worktree, give each a stable `--lane <name>` on every command, or set `TAUTLINE_WORK_LANE`.
Use separate worktrees when they edit independently. `--target <worktree>` works on every action.

This default needs no network. Separate clones, remote machines and hosted agent sandboxes
share declarations only when they use the Git backend below. Declarations contain intent,
not proof of current execution, exclusive ownership, completed tests, or a merged/deployed change.

## Coordination across computers and people

Set `workCoordination` in the project's `.tautline.json`:

```json
"workCoordination": {
  "backend": "git",
  "remote": "origin",
  "branch": "tautline/work",
  "syncIntervalSeconds": 60,
  "timeoutSeconds": 2
}
```

```sh
tautline work sync
```

The CLI reads this setting directly; no render step is required.
Only `backend` is required; the example shows every default. Commit the adapter so the team
uses the same setting. Each clone's named remote must point at the same repository. The
dedicated metadata branch carries manifests separately from source branches; it does not need
PRs or merges into the product's code. Use a dedicated branch, not `main`, the integration
branch, or an existing feature branch. Existing Git credentials and repository permissions
control who can read and publish declarations. The branch must allow direct writes; repository rules that deny them leave publication pending. Metadata commits include `[skip ci]`; exclude this branch explicitly in CI systems that do not honor that marker. Application hooks do not run during metadata synchronization. No separate service or account is required.
Each fresh Git clone gets a persistent random namespace, combined with the lane ID so two
people using the same worktree path or `--lane` name do not overwrite one another. A local-only
filesystem binding detects ordinary copies of a Git directory and assigns a new identity.
A same-filesystem rename keeps the identity. Device/inode remapping (for example some container
mounts or restored images) cannot always be distinguished from a copy; use independent Git
clones for those environments.
Existing unbound identities are adopted without changing them. Copies made before adoption,
or whole-machine snapshots that preserve the binding, cannot be distinguished reliably: use
`git clone` for independent machines rather than copying `.git`. No filesystem binding is published. Use separate worktrees
or explicit lane names for independent agents in a clone. A reader without push permission
can see peers; its own updates remain pending until it has write access. Repository writers
can modify the metadata branch; lane identity is coordination information, not authenticated
ownership or access isolation.

`remote` must be a configured remote name, not a URL or filesystem path. It needs one matching fetch/push URL so the shared view and publication have the same destination; use a dedicated remote if the project normally separates those URLs. `branch` must be a
valid Git branch name. `syncIntervalSeconds` accepts integers from 10 to 3600;
`timeoutSeconds` accepts numbers from 0.25 to 10. Unknown config keys are rejected.

Status, startup, and new-work checks refresh expired cached peer data within the configured
time budget. The default cache interval is 60 seconds; repeated reads within that interval
use local data. Mutations save locally first and attempt a bounded push. If offline or unable
to sync, pending updates stay local for a later retry and the view reports uncertainty.
`tautline work sync` forces a retry; `tautline work status --no-sync` reads only cached data.
There is no polling daemon, per-tool-call sync, or background test execution. Sync failure
never gates editing, taking a backlog item, or merging.

The view reports sync state (`fresh`, `cached`, `offline`, `pending`, or `unknown`), last
successful sync/attempt times, and pending updates. The age of a cached declaration matters:
an offline reader cannot know whether a peer has changed or completed its work since that sync.

**Sharing boundary:** repository readers can read the declared goals, repository-relative
paths, interfaces, dependencies, blockers, item references, and PR links on the metadata
branch. A public repository makes this information public. Automatic absolute local paths
and machine hostnames are excluded from the published manifest, but text you declare is
shared as written. Do not put secrets, customer information, or private machine details in
that text. Git history retains prior versions; finishing a declaration does not erase it. Enabling Git
mode shares active local intent, but does not retroactively publish retired local goals that
were never shared. A finish or abandon performed with Git coordination enabled records the
intent to share that final update, even if its push must wait. A local-only or legacy completion
can retire the last public manifest but cannot export new private text from reuse of the same lane.
Published retired records remain briefly visible (up to 32, for seven days,
within the 256-record shared-view limit). Records expired for more than seven days leave the
branch tip. An owner publication includes bounded cleanup of retired/expired records; read-only observations
do not attempt a push just for peer-history cleanup, and
fresh peer claims remain untouched. Removed local records and scopes invalidated by a removed
worktree or branch change stop asserting active work on the next successful sync. Local stale
records remain inspectable; temporary offline clones may still show the last fetched state.
Unchanged blobs are reused rather than re-hashed through one Git process per record.

## Observe PR outcomes

```sh
tautline work status --remote
tautline work status --remote --json
tautline work status --remote --all
```

`--remote` explicitly asks GitHub for the PRs named in visible declarations. It shows each PR's
open, draft, merged, or closed state, observed head commit, and CI result for that exact commit.
It requires the `gh` CLI with access to the linked GitHub.com repositories. Unsupported links,
missing access, incomplete responses and absent checks report unknown. Skipped or neutral checks
cannot produce a passing CI result.

The whole PR refresh has a five-second budget, with up to four concurrent requests and eight
unique PRs. Repeated links reuse one observation. Work beyond the time or size limit remains
unknown. Each observation has a timestamp; a PR may change immediately afterward. A head change
during collection invalidates the CI observation. Results are not written into declarations or
published to the shared metadata branch.

Declared progress and observed outcomes stay separate: an active declaration can reference a
merged PR, and completing a declaration does not say its PR merged. CI success establishes only
the observed checks, not sufficient coverage, review approval, acceptance or deployment.
Deployment remains explicitly unknown.

This option is only valid with `work status`. Ordinary status, startup, work pickup and edits
collect no PR observations. Git-mode manifest refresh is still controlled by its adapter settings;
`--no-sync --remote` uses cached manifests while explicitly querying their PRs. There is no
background polling, automatic retirement, required check or additional development gate.

## Reading the view

- `ACTIVE` and `BLOCKED` are fresh declarations. The view includes owner, branch, worktree,
  goal, item, paths, interfaces, dependencies, blockers, PR, and age.
- `OVERLAP` means two fresh declarations name intersecting file/directory scopes, the same
  interface, or the same item. `src/auth` intersects `src/auth/login.py`, not `src/author.py`.
  Coordinate directly, split scope, or choose another task. Nothing is blocked automatically.
- `STALE` means the record expired, its local worktree disappeared, or that local worktree
  changed branch. Remote peers are not checked against this machine's filesystem.
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
with atomic per-lane local writes; two processes updating the *same* local lane are
last-writer-wins. In Git mode, also inspect sync status and cached timestamps before treating
the peer view as current. An unavailable remote is not evidence that nobody else is working.

## Adoption

New `tautline init` projects enable a short lifecycle instruction in generated adapters. Use
`tautline init --no-work-coordination` to omit it. Existing lean projects opt in by adding
`"workCoordination": true` to `.tautline.json`. To refresh generated agent instructions, run
`tautline slim --target .`. Handwritten instructions are preserved; incorporate the work lifecycle
line manually: "Use `tautline work`: `status` on wake/resume and before new work; `declare`
before edits; `update` on scope changes; `finish` or `abandon` to retire scope." Already-lean
projects do not receive new proposals for handwritten files. Changing local mode to the Git object takes effect
immediately and does not require regenerating instructions.

The boolean controls adapter guidance and keeps storage local. The Git object both enables
guidance and selects shared storage. An explicit declaration remains visible at startup and
before backlog take even when the flag is absent or false. Projects with no declarations and
no opt-in gain no report noise. These commands also work in ordinary Git repositories without
a Tautline adapter; automatic startup notices require a managed Tautline project.

The feature earns its place through less duplicated work, fewer conflicting changes and faster
resumes. It adds no mandatory plan, recurring review, edit gate or polling loop.

The metadata schema is versioned. Unsupported fields or malformed records keep the aggregate
view UNKNOWN, because an incomplete inventory must not look complete. Future incompatible
field changes require a schema version change and explicit reader compatibility; they are
not silently accepted as valid v1 records.
