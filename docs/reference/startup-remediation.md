# Startup Remediation

This reference documents the `methodology-status --fail-on-drift` exit contract, the
lane-local startup-remediation marker it can write, the generated launcher's
three-way dispatch on that exit code, and the pre-push coordination allowance that
lets a lane escape a strict-coordination deadlock. It is the detailed surface for
[Policy Module Index](policy-module-index.md)'s
[11-cross-lane-coordination](../../methodology/policy/11-cross-lane-coordination.md)
module and for the `methodology-status` entry in
[CLI Operations](operations/cli-operations.md).

## Exit Contract

`methodology-status --fail-on-drift` classifies every gate it evaluates into one of
two closed classes and returns one of three exit codes:

- **0 (clean):** nothing failed.
- **1 (integrity):** `drift` (a generated-adapter render failure `lane-start` could
  not self-heal) or `development_environment_failures` (an unsupported runtime that
  cannot run proof gates). Integrity failures mean the agent cannot prove anything,
  so the launcher never starts a project-work session. Since 0.9.1 (no-dead-ends),
  an interactive launch instead prints the exact remedy and offers a Claude repair
  session confined to fixing the named gate or declaring a blocker
  (`TAUTLINE_NO_REPAIR_SESSION=1` opts out and restores the bare exit-1 refusal);
  non-interactive launches still exit 1 with the remedy printed.
- **2 (debt-only):** every other failing gate — agent-fixable lane debt such as
  missing hooks, stale goal/milestone state, lane-coordination notes, review
  evidence, CI gaps, or Graphify staleness. Debt does not mean the agent cannot
  work; it means the agent's first job this session is to clear it.

Precedence: any integrity failure wins and the command exits 1 regardless of
concurrent debt. Debt-only exits 2. `--strict` semantics are unchanged by this
contract — the same gates that failed under `--strict` before still fail it, and
`--strict` never returns 2, including combined as `--strict --fail-on-drift` (any
failure under that combination exits 1). Classification only changes what a bare
`--fail-on-drift` debt-only outcome returns.

Whenever the exit code is nonzero, the command prints a truthful summary line last:

```
methodology_status_blocking: <integrity|debt> - <comma-separated gate names>
```

`<class>` is the winning class (`integrity` when any integrity gate failed), and the
gate list names every failing gate of both classes, integrity gates first, so
remaining debt is never hidden behind an integrity failure. The same names appear on
every surface that reports a gate — the summary line, the `methodology_status_failed`
event's `refs.gates`, and the remediation marker's `gates` array — so a name printed
in one place is always the right name to look up anywhere else.

## The Remediation Marker

Path: `<lane>/.ai-work/STARTUP_REMEDIATION.json` (lane-local; `.ai-work/` is already
gitignored). **Per-checkout, stated honestly:** the marker lives under one working
tree's `.ai-work/`, so it is not shared across multiple worktrees or clones of the
same lane/branch — each checkout tracks and clears its own remediation state
independently, and entering remediation in one checkout does not block, or get
cleared by, work in another. Schema:

```json
{
  "schema": "tautline-startup-remediation/v1",
  "entered_at": "<UTC RFC3339 timestamp>",
  "gates": ["<canonical gate names>"],
  "issues": ["<the printed issue strings>"],
  "status_exit": 2
}
```

The marker is written **only** by `methodology-status --fail-on-drift
--enter-remediation-on-debt` — a flag the generated launcher passes and that is
classified internal (see [CLI contract](#cli-contract)) — and only on a debt-only
outcome. If a marker already exists, any plain `--fail-on-drift` debt-only run
refreshes it in place (updated `gates`/`issues`) so a running remediation session's
rerun loop stays current as remaining debt changes; it still never *creates* one. The
marker is deleted whenever `--fail-on-drift` would exit 0, with or without the flag.

Both the write (under the flag) and the clear are fail-closed: if `.ai-work` cannot
be created or the marker write fails, or if a marker exists and cannot be deleted,
the command exits 1 with a synthetic integrity gate named `remediation_marker`
instead of silently reporting success — the guard must never keep refusing project
work while status claims clean, and a marker must never fail to persist and then
report a false "started, remediating" state. Integrity failures (exit 1) never write
or clear the marker; non-`--fail-on-drift` invocations never touch it.

## The Remediation Contract

While a marker is present, a single central guard — checked once dispatch has
resolved the subcommand and the lane target — refuses most `tautline` subcommands
with:

```
startup remediation active: fix the issues in <marker path> (rerun 'tautline
methodology-status --target <target> --fail-on-drift' until it exits 0) before
project work
```

Every registered subcommand is classified into exactly one of an ALLOWED or BLOCKED
list; the default posture for anything project-mutating is BLOCKED. ALLOWED covers
what diagnosing and clearing gate debt, committing/pushing the fixes, or declaring a
blocker requires: `methodology-status`, `lane-start`, the review-evidence pipeline,
every command the generated git/Claude hooks invoke, read-only status/diagnostic
commands, and blocker declare/clear/status. A small per-gate recovery map
(`goal`/`goal_tracker`/`milestone`) additionally permits the specific repair commands
those gates need (for example `goal-start` while a `goal` gate is recorded) without
promoting them globally — a coordination-only marker still blocks every
goal/milestone command. `canonical-policy` and `dump-policy-phrases` are flag-aware:
their read/check modes stay ALLOWED, but `--write` is treated as BLOCKED.

**The session's only permitted work is clearing the printed issues or declaring a
blocker.** If a debt gate is genuinely operator-only (a required break-glass
decision, a credential the agent cannot obtain, or similar), the exit is
`blocker-declare` with a report — remediation mode is designed to convert what used
to be an operator lockout into a started session that reaches that exit, not to
force the agent through work it cannot legitimately do. Break-glass mechanisms
themselves (`--no-verify` pushes, gate relaxation, trust re-pinning) remain
operator-only regardless of remediation state; remediation mode does not grant an
agent new authority to bypass gates, only room to work inside them.

## Non-Interactive Scope

**Enforcement scope, stated honestly:** the marker and its guard gate `tautline` CLI
entry points — the framework's project-work choke points. They do not intercept an
agent's direct file edits or arbitrary shell commands; that layer is governed by the
injected remediation prompt and the canonical-policy contract. Marker-aware
Claude-hook enforcement (extending blocking to direct tool/file edits) is deferred
follow-up work — see [Deferred Follow-Ups](#deferred-follow-ups).

Only the interactive Claude launcher special-cases exit 2. Plain `--fail-on-drift`
runs from CI, git hooks, `lane-run`, or a manual shell exit 2 on debt exactly like
any other nonzero exit — stop, non-interactive-caller semantics are unchanged — and
they never pass `--enter-remediation-on-debt`, so they never create a marker.
Non-interactive callers therefore cannot strand lane-local blocking state; only the
launcher's explicit, flagged invocation can.

Any caller that previously compared the exit code to `== 1` to detect a failure must
compare `!= 0` instead: exit 2 is a new nonzero outcome and nonzero-means-stop is
unchanged, but code that special-cased `1` specifically will now miss debt-only
failures.

## Launcher Mechanics

The generated Claude launcher's status invocation gains
`--enter-remediation-on-debt` and three-way-dispatches on the exit code:

- **0:** unchanged — falls through to the goal-kickoff prompt, then execs Claude with
  the user's own arguments.
- **2:** skips the goal-kickoff prompt (one instruction at a time) and execs Claude
  with a remediation prompt naming the lane target and the exact rerun command,
  telling the agent to fix every printed issue and rerun until it exits 0, and that
  break-glass bypasses require an explicit operator decision and a `blocker-declare`
  report if genuinely needed. **User-provided launcher arguments are suppressed on
  this path** — a POSIX launcher cannot reliably separate flags from positional
  prompts, and a surviving user prompt would compete with the remediation
  instruction — so only the configured `claude` args plus the remediation prompt (as
  the sole positional argument) reach Claude. This supersedes an earlier v1-cycle
  decision to preserve user arguments on every path; preserving flags cannot be done
  safely in POSIX `sh` without parsing every `claude` flag's arity.
- **any other nonzero:** refuses with `methodology status failed (integrity); see the
  methodology_status_blocking line above; refusing to start Claude` — the retired
  catch-all that blamed every integrity failure on "adapter drift" no longer appears
  anywhere; the message now points at the actual failing class instead of guessing.

`lane-start` gains an internal `--defer-debt-preflights` flag, passed only by the
generated launcher. With it, `lane-start` preflight failures that correspond to
DEBT-classified gates (for example the latest-code baseline write) degrade to a
printed `lane_start_warn:` line and exit 0 instead of hard-refusing, so the launcher
reaches the status gate and lets *its* classification decide whether the lane enters
remediation mode. Genuinely structural failures (adapter render failure, lock
acquisition, bootstrap-evidence) still hard-refuse even with the flag. Without the
flag, `lane-start` is byte-for-byte unchanged: manual and CI callers using
`lane-start` as a gate keep nonzero-means-stop.

## CLI Contract

`methodology-status --fail-on-drift` and `--strict` document the exit contract and
the summary line directly in `--help`. `--enter-remediation-on-debt` (on
`methodology-status`) and `--defer-debt-preflights` (on `lane-start`) are marked
`(internal)` in their help text and are passed only by the generated launcher; they
are not part of the stable public CLI contract and may change without a migration
notice. No public command or adapter key was added by this release.

## Pre-Push Coordination Allowance

The ordinary pre-push review-evidence gate evaluates a branch's whole outgoing diff,
so a coordination-only commit (a lane status note, or an update to the shared
cross-lane contract/board) could not be pushed from a branch that also carries
unreviewed work-in-progress — a second way a strict-coordination lane could deadlock
against its own gates. The allowance: a push whose outgoing range touches **only**
coordination artifacts — `.md` files under the lane-status directory, or the
resolved cross-lane contract/board file paths (matched by full resolved path, any
extension) — passes the evidence check without full review evidence.

Scope, stated honestly:

- The allowance activates **only** when the pre-push hook's stdin contains exactly
  one ref-update record and that ref's range is coordination-only. Any multi-ref
  push (for example a coordination branch pushed alongside a source branch) gets
  today's ordinary gating, with no allowance, even if every individual ref looks
  coordination-only.
- For a brand-new remote ref, the range is bounded at `merge-base(local head,
  effective review base)` — never full history — where the effective review base is
  the adapter's configured review/pre-push base ref when set, falling back to the
  first existing shared-base ref otherwise.
- Path collection runs with rename detection disabled, so a source file renamed into
  a coordination path still surfaces its old (deleted) path and is gated rather than
  laundered through the allowance.
- A branch that already carries committed, unreviewed source commits and then adds a
  coordination commit still pushes a mixed range and is still gated — correctly: the
  allowance solves the fresh coordination-only push, not a way to launder existing
  WIP. See [Deferred Follow-Ups](#deferred-follow-ups).
- **Residual channel, stated honestly:** content copied into a new coordination
  `.md` file (leaving the original file untouched) is path-invisible, and no
  path-based rule can catch it — the same is true of hand-typed content. This is
  accepted: coordination artifacts are process metadata under human board review,
  cannot execute as code, and the allowance grants passage only to `.md` files under
  the resolved artifact paths.
- **Pre-existing limitation, unchanged by this release:** the review-evidence check
  evaluates the current `HEAD`, not every ref in a multi-ref push. This plan makes no
  multi-ref evidence guarantee; see [Deferred Follow-Ups](#deferred-follow-ups).

### Stdin Handshake

The pre-push hook template captures its stdin ref-update records to a temp file,
exports the path as `MINERVIT_PREPUSH_RECORDS_FILE`, feeds the coordination checks
from that file, and replays the original records on stdin to any wrapped backup hook
— with `MINERVIT_PREPUSH_RECORDS_FILE` explicitly unset for that replay, so a wrapped
hook that itself calls the upgraded CLI cannot unexpectedly activate the new range
logic. The coordination checks read ref-update records only when that variable is
set: a not-yet-regenerated installed hook (CLI upgraded first, hook not yet
reinstalled) sets nothing, so the checks read nothing from stdin and behave exactly
as before — the allowance is simply unavailable until the hook regenerates.
`lane-start` reinstalls git hooks at every startup, so regeneration is effectively
automatic at the next lane start.

## Deferred Follow-Ups

Three follow-ups from this release are tracked in the maintainer backlog
rather than shipped here: a dedicated coordination-branch or git-notes design for
mixed-WIP status pushes, per-ref review-evidence evaluation for multi-ref pushes,
and marker-aware Claude-hook enforcement extending remediation blocking to direct
tool/file edits.
