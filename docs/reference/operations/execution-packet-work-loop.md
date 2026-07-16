# Execution Packet Work Loop

This reference owns tactical execution packets, milestone continuation ledgers,
plan-finalization controls, review evidence, and PR-by-PR continuation behavior.
Goal hierarchy and `/goal` behavior stay in [Goal Execution](goal-execution.md).

After milestone planning is approved, Codex should write the tactical execution packet to the lane:

```text
.ai-work/EXECUTION_PACKET.md
```

The packet contract requires:

- milestone goal and non-goals;
- ordered tactical queue;
- dependencies and safe parallelism;
- tests/specs required per item;
- validation, review, and merge gates;
- drop/defer rules;
- true-blocker criteria;
- completion definition.

Claude consumes the packet until the queue is exhausted or a true blocker occurs. It should run required gates, record run evidence under `.ai-runs/`, push/open PRs when gates allow, enable merge queue, arm monitors, and continue with the next parallel-safe item.

Milestone continuation is tracked in lane-local state:

```text
.ai-work/MILESTONE_RUN.json
```

Start or refresh the milestone ledger after the milestone plan is approved:

```bash
tautline milestone-start --target . --plan <source-of-truth-plan>
```

After every queued-delivery summary, PR merge, PR abandonment, item completion, or item blocking, advance the ledger and start the returned `next_action`:

```bash
tautline milestone-advance --target . --event pr-queued --pr <PR>
tautline milestone-next --target .
```

The milestone ledger is the durable local controller across PR boundaries. A PR boundary is not a stop point: the agent marks the item state, reads the next action, and either starts the next packet item, creates/updates the next source-of-truth PR plan, runs Codex review and `plan-finalization-precheck`, or names a true blocker. A milestone is complete only when the ledger shows all items complete, merged, queued, or policy-deferred and the execution packet, backlog/readiness state, open PR state, continuity handoff, and session journal support that conclusion.

Optional watchdog orchestration is recovery visibility only. It may run on a schedule to surface stale or blocked milestone runs, pending session journals, or missing milestone state, but it does not decide what work means. The ledger and adapter/source-of-truth artifacts remain authoritative. Watchdog support is disabled by default unless the adapter opts in.

The framework backlog item `METH-FU-MILESTONE-CONTINUATION-CONTROLLER` tracks this structural fix. Its acceptance bar is that after a PR is queued, merged, abandoned, or blocked, the agent advances the ledger and starts the returned next action without asking the human operator.

True blockers are scope-changing decisions, unresolved Tier 2/Tier 3 approval needs, unavailable credentials or external access, a failing required gate with no safe fix after investigation, or no safe parallel work remaining. The agent should not stop at arbitrary "good stopping points" or "clean checkpoints."

Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts as approval for the named action once its conditions are verified. The agent should name the approving artifact, the condition it set, and the evidence that the condition is now met. It should not ask for fresh approval just because the next action is Tier 2/Tier 3, break-glass, or admin merge. Vague memory, habit, or inferred preference is not standing approval.

When the next milestone or next work item is identified by the backlog, execution packet, delivery summary, handoff, or current context, planning that item is the next safe action unless a true blocker exists. Treat an item as identified when the context gives enough signal to search source-of-truth artifacts or create a working title; do not downgrade it to unnamed because the phrasing is imperfect.

Do not ask whether to begin planning or pause. Create or update the project source-of-truth planning artifact with substantive planning content before any approval gate. A plan is substantive only when it has: milestone goal, non-goals, evidence/source links, assumptions, ordered scope, dependencies, acceptance criteria, named tests/specs or validation commands, review/merge gates, risks, open decisions, and completion definition. Any TODO-only section, generic one-line placeholder, vague/restatement-only entry, missing named test/gate, missing concrete testable acceptance criterion, or missing acceptance criterion for a deliverable is a stub and cannot be used to ask for approval.

Plan finalization includes asking the human operator to execute or approve implementation, calling a plan-mode exit action such as `ExitPlanMode`, leaving plan mode, writing an execution packet, marking a plan ready for development, pushing a plan-only PR, or starting implementation from the plan. Before plan finalization, classify the work by risk tier. T0/T1 uses brief inline/packet planning and implementation gates. T2/T3 or explicitly review-required plans use the adapter's source-of-truth path, cross-model plan review, and `plan-finalization-precheck`. Unclear classification does not default to plan review; inspect the adapter/source-of-truth, touched paths, issue scope, execution packet, and current diff, then choose the lowest defensible tier or ask one exact blocker question only when the tier changes approved risk. Tool-specific plan-mode checklists are not the complete framework; project adapter, source-of-truth, handoff, and execution-packet review gates overlay tool defaults.

Claude plan mode can supply `ExitPlanMode` with a random scratch path under an adapter-declared scratch root such as `~/.claude/plans/` while read-only plan mode prevents the repo writes needed for source-of-truth finalization. In that narrow case, the hook may allow `ExitPlanMode` as a scratch-to-source transition only. This is not plan approval and not approval to implement: after exiting, immediately create or migrate the source-of-truth plan, run review/finalize/precheck, and do not ask the human operator to choose a bypass. Non-configured outside paths and resolved source-of-truth plans that fail precheck still block.

Adapter-declared review exemptions can skip cross-model plan review only when the source-of-truth plan contains `## Plan Review Exemption`, names the matching adapter exemption, states why no product/runtime/infra/security/data/test-harness behavior changes are in scope, and states the implementation review/gates that still run. The default exemption covers doc-only/operator-guide/index/release-note/backlog-status work. Runtime/product files generally raise the tier, but the tier still comes from concrete evidence rather than a default-on review rule.

Before any T2/T3 or explicitly review-required plan-finalization action, run:

```bash
tautline plan-finalization-precheck --target . --plan <source-of-truth-plan>
```

If the precheck fails because review evidence is missing, run the configured cross-model review through the methodology CLI exactly once for the round, classify the printed log, finalize that existing log into a manifest, address blockers, and retry. Start with the recovery command the hook/precheck prints; the common sequence is:

```bash
tautline run-plan-review \
  --target . \
  --plan <source-of-truth-plan> \
  --round R1

tautline finalize-plan-review \
  --target . \
  --plan <source-of-truth-plan> \
  --log <printed-plan-review-log> \
  --round R1 \
  --verdict <clean|clean-with-deferrals|blocked> \
  --unresolved-critical-count <n> \
  --unresolved-p1-count <n>
```

If Codex reports Critical/P1, fix the plan and rerun the next review round. Rounds 1-2 are the convergence target; rounds 3-4 are self-authorized with a recorded `--exception-note` and never need operator authorization; past round 4 refusal is unconditional and the remedy follows the bound evidence: finalize it only when it is clean AND still bound to the current plan, otherwise the split into smaller source-of-truth plans is mandatory. Run one authoring-model native/self-check before R1 only; do not rerun native review before every plan-review round. Do not rerun Codex just to bind manifest evidence. Do not run `record-plan-review`, hand-edit `.plan-reviews`, disable hooks, skip required `ExitPlanMode` checks, or ask the human operator to choose a bypass. Those are review-evasion failures, not recovery paths.

Before a multi-round plan-review loop, state the expected round budget and wall-clock estimate. At each round boundary, report round N of the target (or of the hard cap once past it), cross-model verdict, unresolved Critical/P1 count, and next action in plain language. If the loop may exceed 10 minutes of cumulative wall-clock, it is monitored-class work and needs the same <=10 minute checkpoint/heartbeat discipline as background review work.

Plan-review convergence is a ladder with a hard cap. A single source-of-truth plan targets two review rounds and gets at most four. Rounds 3-4 are self-authorized when the plan legitimately needs another round: record the reason with `--exception-note "<reason>"` and take the round. A confirmed structural Critical from R2 that would otherwise cause a user-visible failure or expensive rework is one valid reason among others. Findings that do not justify another round transfer into the implementation review focus list. Past round 4 refusal is unconditional, and the remedy is chosen by whether the bound evidence can actually be finalized: finalize the existing evidence only when it is clean AND still bound to the current plan; in every other state — including evidence that is clean but STALE, which `plan-finalization-precheck` rejects as a stale manifest — the split into smaller source-of-truth plans is mandatory. Never ask the operator to authorize a review round, and do not ask whether to work through all findings, accept unverified state, switch tasks, scope down, park the task, or choose a path when this rule identifies the next action.

The captured review command must start with the adapter `review.codexPlanWrapper`, include the `--plan <source-of-truth-plan>` binding appended by `run-plan-review`, appear verbatim in the captured log, and match the CLI-written review-run metadata. The wrapper output itself must reference the reviewed plan path or plan hash.

Codex fast mode defaults to enabled for adapter-backed projects. `run-plan-review`, `codex-run`, `lane-run`, and adapter-backed `background-run` prepend a framework-managed `codex` shim that delegates to the real CLI with `--enable fast_mode`; set `review.codexFastMode` to `false` only for a project-specific opt-out. Generated adapters tell operators to invoke T1 implementation Codex review through `tautline codex-run --target . --risk-tier T1 --review-round R1 -- <review.codexWrapper>` and T2/T3 review with `--native-review-note` plus `--stage1-sweep`, so adapter policy is applied even when the project wrapper itself calls plain `codex review`.

Implementation review evidence is push-time enforced for adapter-backed lanes by default. T0 uses self-review plus tests/preflight and does not run cross-model implementation review. T1 keeps one cross-model implementation review round. T2/T3 review additionally requires Stage 1 native review on the exact current assembled diff, then an exhaustive class sweep recorded with `tautline record-stage1-sweep --target . --native-review-note "<native review result>" --class "<defect class>: <members checked>"`. For Claude-authored code, use Superpowers review plus configured project review agents where available; if unavailable, run a structured self-review checklist and state the fallback. The sweep should enumerate touched classes such as input bounding, output/render sinks, validation/error paths, array dimensions, deterministic fallbacks, rollout sequencing, public API leakage, atomicity/concurrency, breaking-change caller fan-out, idempotency/unique-index behavior, migration/seed ordering, generated/derived artifact freshness, and review-evidence/process integrity. When source files have committed generated mirrors, behavior catalogs, snapshots, indexes, compiled docs, or other derived artifacts, Stage 1 must regenerate or prove those artifacts are current before Codex/Stage 2 spends a round. Project `review.codexWrapper` scripts should review the committed outgoing diff from the adapter/base branch to `HEAD` and ignore untracked scratch files unless explicitly added to the PR scope. After fixing Codex Critical/P1 findings on a T2/T3 diff, rerun native review and record a fresh Stage 1 sweep on the updated assembled diff before the next Codex round. `cap`, `final`, and `retry` labels do not waive this for T2/T3.

Successful implementation Codex review through `codex-run --risk-tier <tier> --review-round Rn` writes `.ai-runs/review-evidence/` manifests bound to the current outgoing diff, HEAD, adapter `review.codexWrapper`, review log hash, wrapper exit code, and the tier-required native-review/Stage 1 sweep fields. After reading and classifying the log, run `tautline finalize-implementation-review --target . --manifest <manifest> --verdict <clean|clean-with-deferrals|blocked> --unresolved-critical-count <n> --unresolved-p1-count <n>`. Finalization also writes a tracked implementation-review ledger under `<planningArtifacts.sourceOfTruth>/.impl-reviews/`; ignored `.ai-runs` evidence alone is not push-eligible. `tautline review-evidence-check --target . --strict` verifies that the tier-required evidence and tracked ledger are matching, classified, committed clean, and have zero unresolved Critical/P1 findings; the lane-local Git `pre-push` hook blocks pushes that lack it. Subagent or per-item reviews do not replace the assembled-diff review for the exact diff being pushed.

Implementation review round budgets are risk-tiered by adapter `review.roundBudgets`, defaulting to zero Codex rounds for T0, one round for T1, and two rounds for T2/T3. When running implementation review, pass `--risk-tier <T1|T2|T3> --review-round Rn` to `codex-run`; the CLI rejects T0 review and rounds beyond the adapter budget. For low-risk PRs, fix Critical/P1 from the single Codex round, route P2/P3/Nit findings by policy, and do not keep buying extra Codex rounds unless the work is reclassified or split.

Plan-review evidence is tracked under `<planningArtifacts.sourceOfTruth>/.plan-reviews/` and bound to a Codex cross-model reviewer manifest, the active adapter `review.codexPlanWrapper`, the exact review command, the plan content hash, review log hash, review-run metadata hash, `review_scope: plan-only`, `code_diff_review: false`, wrapper exit code, verdict, unresolved Critical/P1 counts, classifier version, and timestamp. `clean` and `clean-with-deferrals` are the only finalization-eligible verdicts. Ignored lane-local logs without a tracked manifest are not enough. Source-of-truth plans must include a `Cross-Model Review Evidence` section populated from the manifest unless a valid `## Plan Review Exemption` applies; deleting or editing the required evidence section after manifest recording fails precheck.

Claude Code `PreToolUse: ExitPlanMode` hooks are mandatory for Claude plan-mode lanes. Claude `PreToolUse: Task` branch-liveness hooks are mandatory for Claude tactical subagent dispatch. Claude `PreToolUse: Bash` background-command hooks are mandatory so fake monitor shell loops are blocked before launch. Claude `Stop` response guards are mandatory but runtime-scoped to live active goal sessions: a stale `.ai-work/GOAL_RUN.json` alone is not enough. When no live goal is active in the current chat window, the hook no-ops so normal conversation and clarification can yield; during live active goals it bounces passive-monitor stops, chat-only RCA-shaped responses, status-report-as-stop on derivable-next-action prompts, terminal continuity omission, and false-active status after rejected tools before the turn is yielded. Claude `PostToolUseFailure` tool-rejection hooks are mandatory so rejected/cancelled/denied tool calls inject the correct recovery instruction before the next response. Lane-local Git `pre-commit` and `pre-push` hooks are mandatory for Git worktrees so queued, auto-merge-enabled, merged, or closed PR branches block before more local branch work; `pre-push` also runs `review-evidence-check --strict` when adapter `review.prePushReviewEvidence` is enabled. The portable CLI precheck remains the primary plan control, and the Git hooks bind commit/push to branch liveness and implementation review evidence. `lane-start` installs the hook automatically for Claude plan mode and installs the Claude Task, Bash background-command, Stop response guard, tool-rejection, and Git branch-liveness/review-evidence hooks for Git worktrees; `methodology-status --fail-on-drift` fails if any required hook is missing. Manual install:

```bash
tautline install-hooks --target .
```

If several candidate next items exist and the adapter, backlog priority, ready-for-development status, or execution-packet order can resolve the choice, choose the highest-priority ready item and begin planning. If claiming the choice cannot be resolved or no candidate exists, first inspect the adapter, backlog/source-of-truth plan path, current execution packet, latest delivery summary or continuity handoff, and relevant readiness marker; then name exactly what each artifact said and ask one exact blocker question only if the choice changes scope/risk.

For parser/fixture validation of a packet:

```bash
tautline work-loop --target . --dry-run
```
