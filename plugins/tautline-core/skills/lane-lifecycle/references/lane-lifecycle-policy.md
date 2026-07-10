# Lane Lifecycle Policy Reference

This reference keeps detailed lane startup, update, work-profile, latest-code,
goal/milestone ledger, cleanup, bootstrap, and lock policy behind the concise
`lane-lifecycle` skill entrypoint. It preserves existing behavior while making
routine startup guidance easier to load.

Use this policy at the start of work in an adapter-backed lane, or when asked to
lock, unlock, upgrade, or inspect methodology state.

## Session Start

Resolve the methodology CLI before running startup gates. Use
`minervit-methodology` from `PATH` when available. If it is missing from `PATH` or exits 127/command-not-found, source
`$HOME/.config/minervit/methodology.env` when present or use
`$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology`, then rerun the same gate
with that resolved CLI. A missing `PATH` entry is not a failed methodology gate,
not permission to substitute ad hoc checks, not a reason to ask the human
operator what to do, and not a reason to ask for a person-specific checkout path.

Each machine should install a portable user shim with
`bin/minervit-methodology install-cli`, which writes `minervit-methodology` into
a user bin directory and records `MINERVIT_METHODOLOGY_REPO` in
`$HOME/.config/minervit/methodology.env`.

If the methodology checkout path is not already known from `PATH`,
`MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, machine
bootstrap, current continuity handoff, or generated adapter context, inspect
only those configured sources to resolve it. If the CLI and checkout still
cannot be found, name the exact missing CLI/checkout true blocker.

Run from the lane root:

```bash
minervit-methodology lane-start --target .
minervit-methodology methodology-status --target . --fail-on-drift
```

This is a required startup gate. Do not ask whether to run it, whether to `kick it off`, or whether to proceed with the planned path after it runs. Run startup
gates immediately and continue with the authorized next action unless a true
blocker occurs.

This updates the methodology checkout, which contains plugin files, unless the
lane has a lock file, refreshes `.minervit-ai-delivery.json`, regenerates
`CLAUDE.md`/`AGENTS.md` only when those Markdown files are absent or already
methodology-generated, and ensures lane-local state paths are ignored through
`.git/info/exclude`.

Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`. If an optional
project setting only needs lane JSON/config, use
`minervit-methodology render-adapters --target . --project <project_adapter>
--write --json-only`; do not ask the human operator whether to overwrite
hand-written project instructions. Full Markdown migration is a separate
adapter-back migration after preserving/moving the hand-written rules.

Lane startup also reports document context budget state. Read configured
indexes first and do not broad-load Markdown trees. If
`document_context_unclassified`, missing indexes, or archive-header gaps are
reported, use `context-bootstrap` / `context-status` and the
`context-continuity` skill instead of scanning docs broadly.

Lane startup also reports local evidence publication state when the adapter
enables it. If pending evidence exists after `methodology-status --fail-on-drift`
passes, use the owning ops skill to publish it. Publishing failures must be
recorded in the next continuity handoff and are not a stop signal unless current
methodology analysis depends on the archive.

Lane startup also reports the active work profile. The default is `development`
and keeps all existing startup, git, review, test, board, and code gates. For
intentional Product/Support docs, requirements, wireframes, screenshots, or
support notes, use `minervit-methodology lane-start --target . --profile
product-docs` or `--profile support-docs`; the local lock lets Git hooks allow
only adapter-approved docs/assets paths while blocking code, config, generated
files, secrets, direct base-branch pushes, and oversized/unapproved assets.
Before implementation work, rerun startup with `--profile development`.

Lane startup also reports repo event-log paths when event logging is enabled.
Use adapter-approved event commands for boundary events not already logged by
CLI commands. Never write generated event files directly.

Lane startup also reports context rotation policy and the Claude auto-compact
env/settings check. Managed Claude startup sets
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` before Claude starts, writes the same
durable env into Claude settings, and marks it required for startup health. At
PR/milestone/goal boundaries and long `/goal` heartbeats, if visible context
usage is at or above the adapter soft threshold, refresh continuity, handle the
session journal, compact or restart when available, and resume the active goal
after startup gates. For Claude Code, `/compact` or the strongest host
compact/restart path is the expected rotation action. If the current agent turn
cannot invoke `/compact` or host restart directly, the filesystem handoff plus
exact next startup action is the fallback. Do not ask the human operator to run `/compact`, ask "what would you like", or turn rotation into an opt-in.

Lane startup also reports goal run state. If `.ai-work/GOAL_RUN.json` exists
and is active after startup/status gates, run `minervit-methodology goal-next --target .` before milestone work and start the printed `next_action` unless it
names a true blocker. If no active goal exists or the prior goal ledger is complete, use the printed `next_goal_name`, `next_goal_short_description`, `next_goal_claude_prompt`, and `next_goal_next_action` from
`lane-start`/`methodology-status`/`goal-kickoff-prompt`; if no candidate exists
and the next work is substantial or multi-milestone, create/update the
source-of-truth goal plan, run cross-model review, start the goal ledger, then
proceed to milestone/PR planning. Use the `goal-orchestration` skill for full
policy and Claude `/goal` guidance.

Lane startup also reports milestone run state. If
`.ai-work/MILESTONE_RUN.json` exists after startup/status gates, run
`minervit-methodology milestone-next --target .` and start the printed
`next_action`. At PR boundaries, run `minervit-methodology milestone-advance --target . --event <event>` before treating a delivery summary as complete. The
optional watchdog only surfaces stale runs; it is not process authority.

Lane startup also reports cross-lane coordination state and bootstraps missing coordination artifacts by default. With default strict enforcement, missing, stale, untracked, uncommitted, or unpushed coordination state fails
`lane-coordination-status`, `methodology-status --strict`, and
`methodology-status --fail-on-drift`. Before PR queue, cross-lane contract
changes, blocker summaries, or any work touching shared routes, actors,
schemas, state machines, APIs, storage contracts, deployment conventions, or
another lane's ownership boundary, update this lane's own status file with
`minervit-methodology lane-coordination-note --target . --lane <lane> --goal
"<goal>" --current "<current work>" --depends-on "<dependencies>" --provides
"<provided interfaces>" --blockers "<blockers>" --pr "<PR or commit>" --write`,
then commit and push it.

Lane startup also reports behavior-spec integrity. For customer-facing behavior
in behavior-spec-required projects, run `minervit-methodology
behavior-spec-status --target .` before plan finalization, merge, or delivery.
Inactive acceptance scenarios and harness/app target mismatches are skipped
validation, not coverage.

Lane startup installs the Claude `ExitPlanMode` hook, Claude `Task`
branch-liveness hook, Claude context-rotation heartbeat hook, and Git
`pre-commit`/`pre-push` branch-liveness hooks when possible. Methodology status
reports the plan-finalization gate and hook status. Non-trivial source-of-truth
plans require `minervit-methodology plan-finalization-precheck --target . --plan
<source-of-truth-plan>` before approval, execution packet creation,
ready-for-development marking, plan-only PR push, `ExitPlanMode`, or
implementation start. Claude `ExitPlanMode` hooks are mandatory for Claude plan-mode lanes, Claude `Task` branch-liveness hooks are mandatory for tactical
subagent dispatch, Claude context heartbeats are mandatory for long `/goal`
lanes, and Git branch-liveness hooks are mandatory for Git worktrees;
`methodology-status --fail-on-drift` fails when required hooks are missing.

Unlocked adapter-backed product/client lanes do not raw-pull latest methodology by default; existing adapters default to stable/manual/dry-run framework pins.
`lane-start` reports the effective framework pin, available update, WIP
reasons, and pending migration-report state. Deliberate updates use
`minervit-methodology sync-methodology --target .`, which still applies
release-track and WIP checks. From project lanes, dirty stale methodology
checkouts and non-`main` methodology branches are startup hygiene to auto-rescue
only when an update is allowed. When invoked from inside the methodology repo,
sync remains fail-closed so framework development work is not moved
unexpectedly. Use `minervit-methodology version` and `minervit-methodology
methodology-status --target .` to report `plugin_version`, methodology commit,
lock state, remote status, and adapter drift. If uncertain which process
surface is active, run those commands; do not ask the human operator to decide whether to inspect version/status. Cached host plugin metadata is not a lane update failure. If the CLI reports the expected plugin version but Codex/Claude
still shows stale plugin skills or metadata, restart that host/session.

After methodology status passes, run the project adapter's main-health/smoke
gate, open-PR health check, current-branch liveness check, and merge-conflict
check before new feature work. If any issue appears, handle it as the
highest-priority task before continuing: main-health failure, failed deploy,
open PR with failed/blocked checks, queued/auto-merge-enabled current branch,
merged/closed current-branch PR, closed-without-merge PR, merge conflict, or
unclear mergeability.

When the human operator asks for current project status, whether work is
complete, what is next, anything that may have changed in another lane, or deep codebase/architecture/multi-angle analysis, run `minervit-methodology latest-code-status --target . --write` before answering or analyzing unless
startup just wrote a fresh baseline. Answer from the fetched base (`origin/main`
by default), GitHub PR/check evidence, remote branches ahead of base,
deploy/build identity, and source-of-truth files on the relevant ref before trusting local lane files. If local is behind, dirty, detached, on a PR branch,
or another remote branch is ahead and may be deployed/stakeholder-visible, say
so plainly and do not use the local lane as current product-surface evidence.
For read-only status checks, fetch/inspect remote; pull/rebase only when
preparing to work. Deep analysis, planning, implementation, review, and
tactical subagent dispatch are work-prep unless explicitly scoped as
historical/local-lane analysis, so establish the latest-code baseline before spending analysis budget. The latest-code hook protects state-changing work such as edits, plan finalization, commits, and pushes; it must not block ordinary read-only inspection needed to diagnose or refresh lane state.

If on a non-base PR branch, run `minervit-methodology branch-liveness-check --target . --strict` or the adapter's equivalent. The Git hooks installed by
`lane-start` block commit/push if this check fails, but hooks do not replace
explicit review/subagent liveness checks. A queued, auto-merge-enabled, merged,
or closed current-branch PR is no longer active work; sync main and continue
from the source-of-truth next item instead of committing, reviewing, pushing,
reverting, or dispatching subagents on that branch.

If startup proves the previous PR already landed and no work is in flight, do
not ask where to go next. Perform safe cleanup first: switch/sync to the base
branch, delete the merged local branch or worktree when safe, run `lane-start`,
`methodology-status --fail-on-drift`, and adapter startup/status gates, and
handle generated adapter drift as adapter hygiene only when the project tracks generated adapter files and the diff is solely methodology-generated. Keep adapter cleanup separate from feature work and never commit lane-local state or unrelated product changes. Then continue from the highest-priority ready
source-of-truth backlog item, or create/update its PR-level plan and run
required review. Cleanup versus next backlog item is a sequence, not a menu.

Any direction-asking question after the previous PR landed and no work is in flight is a stop-menu violation, even if it avoids the exact words `Where would you like to go` or `No work-in-flight`.

If no goal ledger next action, execution packet, handoff next action, or
implementation-ready tactical PR plan is on deck after startup gates, inspect
the adapter, backlog/source-of-truth planning path, readiness markers, and
latest delivery or continuity handoff. For substantial or multi-milestone
T2/T3 work, create/update the source-of-truth goal plan first, run Codex plan
review, and pass `minervit-methodology plan-finalization-precheck` before
implementation. For T0/T1 work, use brief inline/packet planning or the
minimal adapter-required artifact, then continue to implementation gates. Do
not ask whether to plan.

If `lane-start` fails because `.minervit-ai-delivery.json` does not exist, the
repo is unmanaged. Use the `project-bootstrap` skill immediately. Do not ask
whether to skip methodology, do not borrow another project's adapter, and do
not wait for the human operator to author the adapter unless a true blocker
remains after repo inspection.

When the human operator asked to use the methodology in an existing repo,
authoring a project adapter from repo-evident facts is bootstrap work, not automatically a Tier 2 approval stop. Ask one exact blocker question only for
choices that cannot be inferred safely.

If the update fails because the methodology checkout is dirty, diverged, or
temporarily unreachable, report it briefly and continue with the current local
methodology. Adapter render failure is blocking.

`lane-start` also writes the lane-local resource environment file configured by
the adapter. Run local-service commands through:

```bash
minervit-methodology lane-run --target . -- <command>
```

This applies lane-specific ports and Docker Compose project names so active
lanes do not collide on local test services.

## Lock And Unlock

Use a lock when the project owner wants a stable methodology version for a
period of work:

```bash
minervit-methodology lock-methodology --target . --reason "<reason>"
```

Resume automatic updates:

```bash
minervit-methodology unlock-methodology --target .
```

Inspect state:

```bash
minervit-methodology methodology-status --target .
```

## Rules

- Do not use old unmanaged lanes as methodology sources.
- Do not hand-edit generated adapters.
- Do not ask the human operator whether to continue after startup gates unless a true blocker exists.
- A rejected or cancelled startup, commit, push, or merge tool call is not a stop signal. Continue with a different safe action or non-conflicting work.
- Prefer lane-local resource isolation over broad machine locks. A port-in-use failure is not a true blocker until the command has been retried through `lane-run` or a specific non-isolatable resource has been identified.
