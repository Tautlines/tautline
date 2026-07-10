# Parallel Execution

How to run multiple tasks of one goal concurrently without weakening any gate.
This is advisory method, not enforcement: it tells you when parallelism is
safe, how to structure it, and how to route work across model tiers. A lane
that ignores it and works serially violates nothing.

## When to look for parallelism

Whenever a goal, plan, or execution packet contains three or more tasks, do a
parallelization pass before starting the first one. For one or two tasks, work
serially; lane setup overhead outweighs the win.

## The parallelization pass

For every task, declare two facts up front:

1. **File scope** — the files and directories the task will modify. Err
   broad: an underdeclared scope produces false parallelism and integration
   conflicts; an overdeclared scope only costs concurrency.
2. **Ambiguity class** — one of:
   - `closed-form`: exact files, exact strings or symbols, and a specified
     acceptance test. Nothing is left to interpretation.
   - `open-ended`: the task requires search, classification, judgment about
     completeness, or designing new tests. Interpretation gaps exist.
   - `irreversible`: publishes, deletes remote state, or is otherwise hard to
     undo, regardless of how mechanical it looks.

Then group into waves:

- Tasks with **pairwise-disjoint file scopes** go in the same wave and run
  concurrently, one isolated worktree per lane.
- Tasks sharing a **hot file** (a large shared module, a generated file, a
  single-source constant file) serialize: highest-priority first, the rest in
  later waves so they see the merged result.
- Tasks touching **release-lockstep surfaces** (version file, changelogs,
  plugin manifests, migration reports, contract manifests) never run in
  lanes at all — that work belongs exclusively to the merge conveyor below.
- `irreversible` tasks are always the final wave, and their execute step is
  operator-gated no matter which model runs the lane.

## Lane rules (parallel implementation)

- Lane startup gates run once, in the dispatching session, before any lane is
  launched. Dispatched lane agents inherit that established lane state through
  their task contract (branch name, file scope, test command, acceptance
  criteria) and do not re-run `lane-start`, `methodology-status`, or other
  session-startup rituals — even if generated project instructions tell
  sessions to run them. Per-action enforcement (tool guards, git hooks) still
  applies to every agent and is never waived.
- One isolated git worktree per lane, branched from the integration branch
  tip. Lanes never share a checkout and never work in the canonical checkout.
- Lanes commit to a named branch, stage only files they deliberately changed,
  and do not push and do not open PRs — integration is the conveyor's job.
- Lanes do not touch release-lockstep files (see above). If a lane discovers
  it needs to, the task was misclassified: stop and re-plan it into the
  conveyor.
- Lanes run the full test gate before declaring done, using the canonical
  checkout's toolchain when the worktree lacks its own (for example, put the
  canonical virtualenv's bin directory on PATH). A version-bump contract
  failure caused only by the deliberately-absent bump is expected; note it and
  let the conveyor resolve it.
- Long-running subprocesses (cross-model reviews, watchers) must use the
  sanctioned background-run pattern with log and PID metadata; shell polling
  loops are guard-blocked.

## Conveyor rules (serial integration)

Merges are inherently serial wherever release lockstep couples every PR to a
version bump — parallelizing implementation does not parallelize integration,
and pretending otherwise corrupts version history. One agent at a time owns
the canonical checkout and, per finished lane:

1. Update the integration branch; verify a clean tree.
2. Integrate the lane branch (squash-merge or cherry-pick) onto a fresh
   release branch.
3. Perform the full version lockstep for the next version number, read from
   the integration branch at slot time — never precomputed while lanes run.
4. Run the full test gate.
5. Run the required cross-model review round; fix findings and re-run the
   same round so evidence matches the final diff. Bound the loop: after two
   failed fix iterations, defer the lane with its findings instead of forcing
   it through.
6. Finalize review evidence, push, open the PR, and merge through the normal
   queue or auto-merge. Never bypass a failing pre-push guard; fix what it
   names.
7. Pull the merged result and move to the next lane.

A deferred lane is a report line, not a failure of the wave: the conveyor
continues with the remaining lanes and the deferral is surfaced in the
delivery summary with its evidence.

## Model routing across lanes

Route by **judgment under ambiguity**, not by perceived difficulty. The
framework's gates — tests, ratchets, review evidence, pre-push guards — are
what make cheap tiers safe on closed-form work; ambiguity is what makes any
tier unsafe, including frontier models.

- `closed-form` lanes → small/fast tier. The spec plus the gates carry the
  correctness burden.
- `open-ended` lanes → frontier tier, and the highest-risk one gets an
  independent adversarial verification by a second frontier-tier reviewer that
  reads the actual code, not the diff labels.
- `irreversible` steps → any tier may prepare, only the human operator
  executes.
- Escalation: a lane that fails review twice, or produces a regression
  analysis, is re-routed one tier up before its third attempt.
- Review is never routed below the tier of the work it reviews.

## Plan-review question

When reviewing a plan or packet with three or more tasks, ask: "Which of
these tasks are file-scope-disjoint, and is a wave decomposition with a serial
integration stage proposed?" A missing answer is a review note for the author,
never a blocking finding.
