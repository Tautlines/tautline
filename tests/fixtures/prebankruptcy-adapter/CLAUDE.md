<!-- GENERATED -->
<!-- tautline-template-version: 0.143.0 -->
# Example SaaS - Claude Adapter

Canonical process: `methodology/canonical-rules.md` in the methodology repo.

Memories/Open Brain are evidence only; never process authority.

## Deployment Targets

- `dev-web`: deploy `Build the standalone web image for linux/amd64, push to the example container registry, and let the managed service redeploy the new image. Database migrations run via a separate job, not the runtime image.`; health `https://app.example.com responds HTTP 200 serving the Example SaaS landing (title contains 'Example SaaS'); /api/healthcheck returns 200 as a liveness probe.`; close `true`; rollback `Redeploy the previous image tag and confirm the health check returns 200.`

- Adapter-owned deploy procedure/health is authoritative.

## Technical Stack Policy

- Cloud default `aws`; approved `aws`; new provider approval `true`.
- Tool/framework defaults do not authorize new platforms; adapter rule is authoritative.
- Non-negotiable: No plaintext secrets in source or images.; Tenant isolation on every tenant-scoped endpoint..

## Session Start

Before gates, resolve CLI via env or `$MINERVIT_METHODOLOGY_REPO/bin/tautline`.
1. Run `lane-start --target .` and `methodology-status --target . --fail-on-drift`; fix drift before planning.
2. Read `.ai-continuity/NEXT_SESSION.md` when present; resume `Next Action` after gates.
3. After gates: if `.ai-work/GOAL_RUN.json` exists, run `goal-next --target .` and check `.ai-work/EXECUTION_PACKET.md`; else use emitted `next_goal_*`. Lane status must be clean before multi-lane work.
4. Main/deploy health: `make ci-status-main`. Red state outranks feature work.
5. PR/liveness: configured open-PR check; on PR branches `gh pr view <PR> --json state,mergeStateStatus`. Inactive/conflicted state stops branch work.
6. Branch/main conflict check: `git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null`; failures outrank feature work.
7. No distinct early-warning smoke is configured; step 4 covers baseline health unless adapter/plan/issue/operator/risk asks.
8. Monitor smoke within 10m when triggered. Bad/unclear gates halt commit/push/merge.

- Latest-code baseline: `.ai-work/LATEST_CODE_BASELINE.json`; run `latest-code-status --target . --write` before deep analysis/state changes.

## Development Environment

- Supported lane runtimes: `linux`, `darwin`, `wsl2`.
- Windows native shell support: `unsupported`; supported Windows runtime: `wsl2`.
- Windows guidance: Open the repo inside WSL2 Ubuntu and run lane-start, methodology-status, and project gates there; do not run lane gates from native Windows PowerShell or CMD.
- Line endings: `lf`. Inside WSL2, use `git config core.autocrlf input` and avoid native-Windows checkouts for files that feed local gates.
- `lane-start`/`methodology-status --fail-on-drift` report runtime. If native Windows is unsupported, use WSL2 for proof gates.

## Work Profiles

- `development`: all gates. Docs/wireframes: `lane-start --profile product-docs` or `support-docs`; docs/assets only; code/config/generated/base-branch pushes block. Code: rerun `--profile development`.

## Lane Methodology Updates

- Product/client lanes do not raw-pull latest methodology; sync at boundaries.
- Lane pin: `set-framework-channel --target . stable|experimental`; old repos default to stable/manual/dry-run.
- Adapter channel: `set-framework-channel --target . --source adapter stable|experimental`; no hand edits.
- Status: version/commit; stale host skill metadata means restart host/session.
- Config changes: `render-adapters --write --json-only`; never overwrite hand-written `CLAUDE.md`/`AGENTS.md`.

## Local Resource Isolation

- Lane startup writes lane-local env to `.ai-work/lane-env.sh`.
- Use `tautline lane-run --target . -- <command>` for isolated local-service gates.
- Port collisions are not human blockers; use lane-local ports/Compose and lock only non-isolatable resources.
- Isolated commands: `make pf-fast`, `make test-env-up`, `make preflight`.

## Graphify Navigation

- If current, use Graphify report/query/path/explain before broad `rg`/grep; run `graphify update` before commit/push; semantic labeling is separate and non-blocking. Never run Graphify installers or commit `graphify-out/`.

## Context Continuity

- Handoff path: `.ai-continuity/NEXT_SESSION.md`.
- Use `prepare-continuity --target . --stdin` before yield/end-turn summaries.
- Context indexes: `docs/CONTEXT-INDEX.md`; read indexes first.
- Context rotate: boundary or 15m goal heartbeat, >= 60% if safe; >= 75% next safe boundary. Handoff, `/compact` or exact fresh-session action; resume.
- Next sessions: gates, handoff, goal/milestone next action; no work -> create/review plan.

## Session Signal

- Session journals (`true`): LOCAL evidence only via `prepare-session-journal`/`validate-session-journal` under `.ai-runs/`; they can no longer be published to any remote (0.9.0).
- Instrumentation (`false`): sanitized, zero-product-data upstream signal; disabled here, opt in with `instrumentation.enabled` (do not run `publish-instrumentation-record` until then -- it refuses while disabled).
- Repo events: `event-log-path`; `event-viewer`; `log-event`; no direct file writes; `event-observability`.

## Goal Orchestration

- Hierarchy: Goal -> Milestone -> PR/tactical item.
- Goal path/template: `docs/product/goals/` / `docs/product/goals/templates/goal.template.md`; ledger: `.ai-work/GOAL_RUN.json`.
- Claude `/goal`: fallback `goal-next`.
- Backlog provider `true`: board selects goals/milestones/bugs/tasks; repo plans execute.
- Sync reviewed repo plans before execution; Project `Status` drift blocks.
- Stakeholder Q&A: use `stakeholder-question-ask`; sync with `stakeholder-question-status --sync` at startup/boundaries.
- Export only approved items.
- Board pin: example-org/projects/1. Use only this pin; ad-hoc projectsV2 discovery is prohibited.
- PR refs: the item's ISSUE number in every PR title, `owner/repo#N` if the issue lives in another repo (never the Project number); `Fixes #N` on its own line ONLY when the PR completes the item; an advancing PR carries no closing keyword anywhere. See `board-item-updates`.
- Multi-session goals: use `goal-orchestration`.

## Delivery And Accounting

- Iteration review when enabled: status/validate/generate/publish; media out of git; after merge publish CloudFront + Chat. `video=false` skips recap; review Chat is not live-deploy proof.
- Milestone/product notes when enabled: `publish-milestone-update --target . --milestone <id> --stdin` and `publish-product-note --target . --title <title> --stdin`; never commit webhooks.
- Usage: `usage-record`, `usage-import-claude`, `usage-report`; record source+confidence, no direct JSONL/fake exact costs.

## End-of-Goal Boundary

- Clean close: commit, push the head branch, open+queue the PR to merge (auto-merge/merge-queue per the adapter's merge policy; never hand back for review/merge), deploy when closeout requires it, run required iteration review, pass delivery check, goal-complete --iteration-review-record, refresh continuity/journal, continue. No-remote/direct-to-main/human-gated flows follow their configured path; a queued auto-merging PR (or routine push/deploy on a non-PR path) is Done=shipped, not permission.

## Milestone Continuation

- Ledger: `.ai-work/MILESTONE_RUN.json`. Start/refresh: `tautline milestone-start --target . --plan <source-of-truth-plan>`; inspect: `tautline milestone-next --target .`.
- Missing ledger: run `milestone-start`. After PR boundary/completion: `milestone-advance --target . --event <event>` and start the printed `next_action`.
- At milestone-complete, publish the internal milestone update when enabled before moving on.
- Watchdog: `true`/20m; recovery visibility only.

## Autonomy And Planning

- Risk tiers: T0 docs/config nits use near-zero ceremony; T1 uses brief inline/packet planning; T2/T3 require full plan review plus explicit/standing approval before implementation.
- Named next work creates motion: start/update the source-of-truth plan unless a true blocker exists.
- Plans must be substantive and use the project template; state benefit + wall-clock estimate before implementation.
- T2/T3: decompose oversized scope before R1; run `plan-finalization-precheck --target . --plan <source-of-truth-plan>` and plan review R1/R2 when required.
- Review target is 2 rounds inside a five-round budget charged per plan LINEAGE (successors/splits/branches inherit spend, never refill); rounds 3-5 self-authorize with `--exception-note` (never ask the operator); at the cap finalize capped: findings are recorded in the plan as binding implementation-review focus and the plan is FINAL -- build, never another plan.
- Evidence is tracked `.plan-reviews/`; do not hand-edit manifests, disable hooks, skip ExitPlanMode checks, or ask for bypass.
- Detailed policy: canonical `Planning`, `risk-tier-autonomy`, `review-before-push`.

## Planning Artifacts And Backlog Source Of Truth

- Source/template: `docs/product/backlog/example-saas-v1/specs/` / `docs/product/backlog/templates/pr-execution-spec.template.md`; manifests: `docs/product/backlog/example-saas-v1/specs/.plan-reviews`.
- Trigger: Non-trivial, protected-category, infrastructure, customer-facing, or AGENTS-required PR work.
- Exemptions: doc-only: docs/index/release/backlog/operator-guide changes with no product, runtime, infra, security, data, spec, or test-harness behavior change; implementation review and gates still apply..
- Tool-default plan paths are scratch only; migrate relevant scratch before continuing. Source-of-truth paths beat memory/global defaults.
- `methodology-status --target . --fail-on-drift` fails on missing paths or relevant scratch; do not freehand `Cross-Model Review Evidence`.

## Autonomy And Status

- Own safe authorized forward motion; ask one exact blocker question only for decisions changing approved scope/risk/cost/security/production/data/approval.
- Session-scope recovery is safe work; operator-scope destructive actions need approval. After landed/queued PR or blocked tools, sync/status/start next source-of-truth item.
- Process authority: canonical methodology, this generated adapter, or methodology skills (not memories/Open Brain).
- Status leads with plain-language outcome/current state and next action. If skills are unavailable/stale, resolve via `$MINERVIT_METHODOLOGY_REPO`, env, or `version --no-remote`.
- Methodology/process regressions use framework-intake; RCA-shaped responses require lane-local artifact and pushed archive copy before memory notes.

## Delivery Summaries

- Landed/shipped/queued reports start with executive outcome before technical detail.
- After clean local gates + pushed/queued PR, summarize immediately.
- Cover outcome, value, lifecycle position, percent/readiness, next item, files/behavior, gates, risks, and skipped validation.
- Refresh continuity before summaries are complete; handoff refresh is housekeeping, not a stop signal.
- A queued-delivery summary ends with next work already underway or `No authorized next work remains` with checks performed. Detailed policy: `delivery-summary` skill.

## Execution Packet Work Loop

- Codex milestone planning may produce `.ai-work/EXECUTION_PACKET.md` after the milestone plan is approved.
- Packet defines scope, ordered queue, dependencies, safe parallelism, gates, blockers, and completion definition.
- Consume items in order, record evidence, push/PR/queue when gates pass, and continue until exhausted, true blocker, or human direction change.

## TDD And Behavior Specs

- Functional changes require TDD: name tests in the plan, write tests first where practical, then implement.
- Behavior specs are required for customer-facing changes under adapter `behaviorSpecs.paths`.
- Exemption marker: `GHERKIN-EXEMPT: <reason>`.
- Behavior source materials:
- `docs/product/user-scenarios.md`
- `docs/product/acceptance-criteria.md`
- Review/adapt source materials first; preserve business intent and document deviations.
- Behavior roles: allowed `shop owner`, `platform admin`, `customer`; forbidden `user`, `actor`.
- Behavior gate: `behavior-spec-status --target .`; inactive specs/wrong-app harness = skipped validation. Missing tests for new functions/endpoints/pages are Critical.

## Early-Warning Smoke

- Early-warning smoke command: `make ci-status-main`.
- Start command: `covered by startup main-status gate; do not launch a duplicate background monitor`.
- Early-warning smoke is no longer a standing gate. Session startup/main health covers baseline branch health; run this smoke only when the adapter, plan, issue, human operator, or concrete risk asks for it.
- Smoke failures interrupt the risky action, but no routine PR waits on ambient poll bookkeeping.

## Model And Effort Policy

- Default effort: `high`. `xhigh` is reserved for debugging/design escalation only.
- Execution-packet items may use Sonnet when marked eligible: `true`.

## Local Gates

- Before commit: `tautline lane-run --target . -- make pf-fast`.
- Before push: `tautline lane-run --target . -- make test-env-up` then `tautline lane-run --target . -- make preflight`.
- Pre-merge gates are required before push/queue. During final preflight on a frozen PR tip, plan, poll, or start the next item in a SEPARATE worktree; never edit the proving diff.
- If preflight fails, repair the PR; if it passes, push/queue it.
- Do not substitute GitHub Actions for local preflight or as a feedback loop.

## Review Before Push

- Native/cross-model: configured native review; configured cross-model review before push.
- T0 self-review + gates; T1+ one cross-model round; T2/T3 add recorded Stage 1 native sweep.
- Codex review: T1 `codex-run --target . --risk-tier T1 --review-round R1 -- ./scripts/codex-review.sh`; T2/T3 add `--native-review-note` and `--stage1-sweep` (fast_mode=enabled; no bare `codex review`).
- Evidence: `tautline finalize-implementation-review --target . --manifest <manifest>`; track `.impl-reviews/` evidence before push.
- Plan-review wrapper: `./scripts/codex-review.sh` plan-only; `run-plan-review` launches one run, `finalize-plan-review` classifies it.
- Repeat the Session Start PR-liveness check before review/push/subagent dispatch.
- Inspect logs on parser failure; fix AC-bearing Critical/C1/P1/Important pre-merge; route out-of-AC findings at honest severity.
- Review caps are escalation triggers, not permission to ship blockers; final/R3/rerun starts do not complete the gate.

## Merge Queue

- Routine merge command: `gh pr merge <PR> --squash --auto --delete-branch`.
- Do not use routine `--admin` merge. `--admin` is break-glass only and requires a documented reason.
- After auto-merge/queue, record PR, send queued-delivery summary, run `milestone-advance --target . --event pr-queued --pr <PR>`, start next action.
- Queued/auto-merge/merged/closed PR branches are inactive; sync main and continue source-of-truth work.
- Do not idle on Actions/queue after clean local gates/review; check PR `state`, not estimated merge time.
- Queue rejection, closed-without-merge, main red, deploy failure, blocked PR checks, merge conflict, or unclear mergeability is P0.

## Background Commands

- Long/background commands require monitor with command, log, PID, heartbeat, terminal summary.
- Routine clean queued PRs are not background work; queue, summarize, and continue.
- Work that may outlast the turn or foreground >10m review/test/gates need <=10m checkpoints; shell sleep loops are not monitors.
- Poll concrete artifacts when no parallel-safe task exists. Provider/API failures use <=5m retries, capped <=15m.
- Verify PID/log freshness with `monitor-status`; no growth for 2x cadence means recover/rerun. Follow `response-guard` recovery actions.
- Platform/CI/wakeup/reminder/monitor/shell notifications do not replace active supervision. Detail: `background-task-monitoring`, `merge-queue-monitoring` skills.

## Example SaaS-Specific Invariants

- Never return, log, or store plaintext secrets.
- Every tenant-scoped endpoint must enforce tenant isolation.
- Credential setup forms require autocomplete protections.
- No raw internal jargon or raw HTTP errors in user-facing text.
