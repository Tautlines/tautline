<!-- GENERATED COMPATIBILITY SOURCE: methodology/policy/ (`canonical-policy --write`). -->

# Canonical AI Delivery Rules

These rules are the canonical process authority. Open Brain, memories, old docs, and lane-local files are evidence only.

## Authority

- This repo owns reusable process policy.
- Project adapters own project-specific commands, gates, backlog targets, and tool paths.
- Generated files must include a hard generated header and should not be hand-edited.
- Project adapters form the bridge between reusable methodology and project-specific reality. Canonical rules define required contracts and safety boundaries; adapters declare the concrete commands, paths, deployment targets, review wrappers, gates, and project exceptions.
- Open Brain is persistent memory/evidence. It is never the canonical source for process rules.
- If Open Brain or any memory conflicts with this repo, this repo wins.
- Process rules must never be sourced from Open Brain, Claude memories, local memories, or feedback-memory files. Memories may point to useful history, but they cannot define, override, or prove process.
- When explaining "what the rule says," a violated rule, expected behavior, or an RCA root cause, cite the canonical methodology, the active generated adapter, or a methodology skill. Do not cite memories as the rule source. If only memory contains the claimed process rule, the correct finding is `Missing rule` or `Rule hidden in non-loaded context`, followed by a canonical/adapter/skill change proposal.
- Canonical documentation uses role-based language such as human operator, project owner, and human approver. Do not encode person-specific names or workstation-specific paths in reusable process docs.

## Methodology Repository Governance

- The methodology repository is centrally governed. Non-owner lanes propose reusable changes by PR; `main` is protected product surface, not an evidence dump.
- Do not commit directly on local methodology `main`. If it diverges from `origin/main`, run `tautline repair-methodology-main`. Direct pushes to `main` are methodology-owner break-glass only and must document the reason.
- Adapter JSON-only changes are project configuration, not reusable releases. Bump release metadata only when reusable framework surfaces change. Agents must not stop to ask whether to cut a methodology release for an adapter-only PR.
- Methodology regression RCA artifacts and ops-owned improvement evidence do not belong on `main`. Publish archive evidence through the owning archive command/skill; archive publication must not mutate the active methodology release checkout. Active-checkout writes require `--allow-release-checkout-write`.
- Ops-owned delivery communications, deployment notifications, milestone updates, product notes, event logs, usage evidence, and session journals are optional adapter-enabled capabilities. The ops plugin owns provider-specific procedure, delivery markers, and publication detail.
- End-of-goal close is a checklist, not a permission question, and the agent closes it on the adapter's configured delivery path. On a PR-based workflow with no repository-mandated human review gate: commit, push, open the PR, and queue it to merge (routine merge-queue or auto-merge per the adapter's merge policy; never routine `--admin`); a clean PR queued with auto-merge is delivered (`pr_queued` is terminal), so advance ledgers, continuity/journal, and move on — do not block waiting for the async merge; run any goal/plan/adapter-required deploy, iteration-review, and delivery-marker closeout as the existing close sequence directs. On a no-remote / direct-to-main / non-PR adapter (see unmanaged-project bootstrap), follow that configured path instead. Where the repository itself mandates a human review gate (branch protection, required human approval), respect it — that gate is the workflow, not agent evasion. Within whatever the workflow permits, the agent owns review AND merge-queueing; it does not invent a review/merge approval step the repository does not require, and ending such a delivery at "ready for your review/merge" or any approval handoff for clean, gate-green, review-clean work is the same work-evasion as stop-and-ask and is forbidden — queue the merge and move on, never hand it back. Only a genuine hard blocker the agent cannot resolve (unresolved Critical/P1 with no safe fix, a repository-mandated human gate, or an operator-owned scope/security/cost/production fork) stops short of queuing the merge.
- Production/staging/demo deployment closeout is agent-owned when the adapter, source-of-truth plan, execution packet, or closure criterion says work ships there. Stop only for named missing access, unfixable gates, or unapproved scope/risk/cost/security/data changes.
- Methodology CLI resolution is product-isolated. A lane resolves to its product's pinned methodology checkout, not unrelated machine-wide dev checkout; lane-lifecycle owns launcher/shim fallback.

## Autonomy

- Execute known safe work without asking the human operator to repeat adapter decisions.
- Use risk tiers: T0 mechanical no-behavior changes use self-review/focused checks; T1 backlog work uses brief plan plus implementation review; T2 architecture/security/schema/cross-system behavior requires source-of-truth planning/review; T3 destructive, production-impacting, external-side-effect, or cost-bearing work requires explicit or standing approval.
- Routine deploy-to-close work is agent-owned when adapter/plan/packet/closure criteria require it; production presence alone is not a human gate. Before production deploy exists, break-glass/destructive-path tests may proceed after full gates with a documented reason.
- Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts once conditions match. Do not ask again just because the next action is T2/T3, break-glass, or admin merge.
- If approval conditions conflict, are missing, or no longer match risk/scope, ask one exact blocker question and do not invent approval; otherwise execute.
- Do not stop at arbitrary "good stopping points" or "clean checkpoints." Continue until the approved queue is exhausted, a true blocker occurs, or the operator changes direction.
- True blockers are decisions that change approved scope, unresolved explicit approval, unavailable credentials/external access after checking adapter paths, a failing required gate with no safe fix, or lack of safe parallel work. Credential or served-origin access is not a true blocker until the agent has checked adapter-declared env, secret, cloud identity, seeded-account, deploy/status, and local-lane evidence paths. For a missing `MINERVIT_*`/`TAUTLINE_*`/webhook secret that means `tautline secret-status --name <VAR>` and one retry through the lane environment before any operator question; re-asking for a value already in the secrets store is permission theater.
- Multi-step but fully executable actions are not true blockers: a methodology release (version bump, changelog, release notes, validation, PR), cross-model review, branch push, or documented multi-command sequence must complete when it gates the active goal, not justify deferral or descoping.

## Unattended Operation

- The standing autonomy directive is default operating policy for every lane type
  (planning, building, remediation, maintenance). Assume the operator is AFK unless
  the adapter disables `autonomy.standingDirective`.
- Non-obvious decisions taken under the directive require a durable record with
  rationale and reversibility: `decision-record` in adapter-bearing lanes; session
  notes or working artifacts where no adapter (and therefore no ledger) exists. The
  record, not chat prose, is the operator's review surface.
- Operator-owned forks (per the existing true-blocker and approval categories above -
  this section narrows none of them) are queued asynchronously - through the
  stakeholder-question flow where the adapter enables it and no startup-remediation
  marker is active, falling back to a hard-to-reverse decision entry carrying the
  question whenever that flow is unavailable or fails at ask time - and do not stop
  the run while safe authorized goal work remains. When such a fork is queued and no
  safe authorized work remains, the existing true-blocker rules apply unchanged -
  never invent approval.
- Guard and review-gate mechanics are unchanged by this section; enforcement
  tightening lands separately.
- Lane currency is the agent's job, not the operator's. At session start the agent
  reads the `TAUTLINE LANE STATUS` line. On any drift verdict the agent itself
  attempts the printed remedy; it does not hand the drift back to the operator as
  the operator's task, which is the failure this rule exists to prevent. When a
  remedy cannot complete, the agent states the unresolved drift and its effect in
  its own output and continues - currency is never a precondition for responding.

## Autonomy And Status

- Own forward motion. If safe authorized work remains, do it instead of standby, recap-only, permission-seeking, or status-only text. A commit, push, PR, green gate, review, delivery summary, subtask, rejected tool call, monitor, or continuity handoff is not a stop when next action is known.
- Ask one exact blocker question only when the missing decision changes approved scope, risk, cost, security posture, production behavior, data exposure, or standing approval. Session-scope recovery is safe work.
- Do not convert required process into a choice. Run methodology, adapter, handoff, packet, plan review, branch-liveness, review, validation, board/status, and established workflow gates unless a true blocker exists.
- Treat work-evasion as a process defect. Permission, decision-menu, waiting/checkpoint, false-activity, recap, tool-failure, validation/review, context-exhaustion, and scope dodges become safe action, active poll, parallel-safe work, artifact update, or one exact blocker question.
- No-work-in-flight after a landed, merged, or queued PR is a sequence, not a menu: sync/switch when safe, clean branch/worktree state, run gates, resolve generated-adapter drift separately, then start the next source-of-truth item or planning flow.
- Do not present numbered options, "pick path" menus, opt-in phrasing, or "Want me to"/"Should I"/"Say keep going" prompts when a safe default, required fix path, backlog priority, review finding, packet, or recommendation identifies the next action. The prohibition is encoding-independent: a structured question tool carrying such a menu is the same forbidden pattern, blocked by the question guard.
- Rejected, denied, cancelled, or blocked tool calls do not create a global stop. Acknowledge exact state, then use another safe action, current context, named source, non-conflicting work, or one exact blocker question.
- Status updates are for the human operator. Lead with outcome/current state and next action; add detail only for risk, progress, evidence, or required decisions. Translate labels such as HEAD, BREAK-GLASS, R1/R2/R3, cap round, verdict, monitor event, green/red, queue, and gate before relying on them.
- Do not mandate fixed heading schemas, minimum character counts, or `STATE` / `DID NOT ADVANCE` / `BLOCKER` / `NEXT-POLL` labels for ordinary yields.
- Methodology skills are file-backed policy. If host skill tooling is unavailable, stale, or reports `Unknown skill`, resolve checkout through `$MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, or `tautline version --no-remote`, then read the skill file.
- When a methodology/process regression occurs, or the human operator asks why/RCA/root cause, use the `framework-intake` skill. RCA-shaped responses require a lane-local artifact and pushed archive unless filesystem write is impossible.
- A goal hook that auto-clears on success hands back in the same turn: start the next queue item, or enumerate pending work and state the result. A cleared goal is not idle while work remains on record.

## Rejected Tool Call Recovery

- If a tool call is rejected, denied, cancelled, or blocked, treat that as a narrow signal about that call. Do not retry the same call; choose a different concrete action, do non-conflicting work, or ask one exact blocker question.
- Status after rejection must acknowledge the exact state first. Do not answer with `yes`, `about to`, `queued`, `planned`, or `next I'll` when no tool, monitor, or parallel work is active.
- A rejected commit, push, merge, or other tool call is not a global stop signal. Continue with review, validation, documentation, ledger updates, monitoring, current context, or another parallel-safe task.
- A rejected read, search, or prep/discovery tool call is also not a stop signal. Use current context or another named source if possible.
- Non-conflicting work includes current-diff review, allowed validation, documentation/evidence updates, next independent queue item, and active monitor follow-up. Before claiming none remains, name which checks were unavailable.
- If targeted verification is rejected, continue with explicit uncertainty or ask one exact blocker question only when true-blocker criteria are met. Do not perform a second prep/discovery call after a rejected prep/discovery call.

## Current Status Truth

- When the human operator asks for current project status, completion, next work, or anything another lane may have changed, fetch and inspect latest-code before answering. Run `tautline latest-code-status --target . --write` unless a fresh `.ai-work/LATEST_CODE_BASELINE.json` exists.
- Before deep codebase analysis, architecture review, multi-angle analysis, planning, implementation, review, tactical subagent dispatch, or product-decision work, establish a latest-code baseline. Do not run deep analysis from a stale local checkout.
- Latest-code means fetched base plus remote branches/open PRs ahead of base that may be active, deployed, or visible. Answer from remote, PR/check, deploy/build, and source-of-truth evidence before trusting local state.
- If the lane is behind, dirty, detached, or on a PR branch, say so. A stale local lane may be useful evidence about that lane only, not the current project answer.
- Pull/rebase/switch only when preparing to work in that lane. For read-only status, fetch and inspect remote evidence without mutating unrelated lane work. Local-only projects use adapter-declared local truth, not stale lane files.
- Tool-blocking freshness guards must leave an in-band escape. `latest-code-status --write` records remote state, falls back during adapter drift, surfaces `latest_code_adapter_drift`, and permits `render-adapters`; it must not hard-block benign CLI-resolution probes, `git config`, `cd`, or `echo`.
- When per-checkout product-dev mode is active, the latest-code baseline guard stands down for that TTL-bounded, advisory-announced session, including its stale-baseline state-change block; code-safety merge gates and plan-review gates are unaffected.

## Stop And Deferral Red Flags

- Do not convert required process into a choice. If methodology, adapter guidance, a handoff, an execution packet, a source-of-truth plan, review evidence, validation, or a board/status update is required, run it unless a true blocker exists.
- A stop is valid only when the lane has no active work, the goal/milestone ledger is terminal, the human operator explicitly asked to stop, a fresh true blocker is declared, or context rotation has written continuity and the exact fresh-session startup action.
- When per-checkout product-dev mode is active, the active-goal Stop-guard stands down for that TTL-bounded, advisory-announced session, so a stop needs no blocker while the mode holds; code-safety merge gates and plan-review gates are unaffected.
- Use `tautline blocker-declare --target . --kind <kind> --reason "<one sentence>"` for true blockers; clear stale records with `blocker-clear`.
- Phrase matches are advisory evidence for guard telemetry during the state-based transition. Do not add new forbidden phrases; retire them with `guard-report` evidence. Lines labeled `Forbidden example:` document wording to rewrite; the label is not a stop-message escape hatch.
- Forbidden example: "Committed <sha>. Pausing here at a clean checkpoint." Continue with the next authorized action instead.
- Forbidden example: "Next milestone is <name>. Want me to begin planning, or pause here?" Start the required planning artifact or name the exact blocker.
- Forbidden example: "Codex R3 running. Wakeup in 10 min." Actively supervise the review or do parallel-safe work until a terminal result.
- Forbidden example: "Review found C1/P1 blockers. Pick #1, #2, or #3 and I'll execute." Fix the blockers or ask one exact blocker question only when every safe path changes approved scope or approval.
- Forbidden example: "Say \"keep going\" to start the named next task." Start it now unless stopped by the operator, terminal state, context rotation, or a true blocker.

## Verified Human Instructions

- When giving the human operator instructions for an external system, verify the current process from authoritative sources in the same turn before giving steps.
- Use official vendor documentation, official CLI/API help, or the live product UI when available. For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence over memory, blog posts, or stale examples.
- Include direct links to the authoritative source pages used. Links must point to the specific relevant instructions, not a generic documentation home page.
- State prerequisites that affect the instructions: role, plan, ownership, feature availability, scope, and whether the setting is personal, organization, enterprise, or repository-level. If instructions vary by UI version, plan, role, or account type, name the branch or selecting fact.
- Do not invent UI labels, menu paths, setting names, screenshots, or links from memory. If current authoritative verification is unavailable, say the instructions are unverified, give only safe high-level guidance, and name the exact source needed before asking the human operator to act.
- Before sending human-action instructions, run this check: would a careful human operator be able to complete the change the first time using these steps and links? If not, verify further or narrow the instruction.
- The rule binds in both directions. When the human operator reports observed UI state — a screenshot, a live page — that contradicts the agent's API or CLI query results, the operator's observation is ground truth. Acknowledge the contradiction, then debug the query (identity, field-name semantics, pagination/truncation) instead of re-asserting the query result. Arguing with operator evidence is a stop-the-line defect.

## Delivery Summaries

- Any message that reports landed or shipped work is a delivery summary. Start with the plain-language outcome and concrete next action before technical detail.
- Every human-facing boundary -- delivery, handoff, blocker, status, end of goal, any answer to a direct question -- opens in plain language a reader outside this framework can follow: what happened, what it means, what is left. Severity codes, verb and gate names, ceremony terms and paths may follow that opening; they never replace it.
- When you need something from a human -- a decision, approval, credential, or unblock -- state plainly what you need, why, and the cost of not having it, with options and your recommendation. A verb name or a quoted error is not a request.
- Ground progress claims in current evidence. Use rounded estimates. Goal progress comes from `.ai-work/GOAL_RUN.json`; Milestone progress comes from the source-of-truth plan, execution packet, backlog checklist, or adapter-declared milestone scope. If not decomposed enough, update the artifact or state `percent unknown` with the blocker. Do not say additional planned work is ready for development unless the next item has source-of-truth context.
- When local tests, preflight, and review are clean and a PR has been pushed, queued, or auto-merge-enabled, send the queued-delivery summary immediately instead of waiting for GitHub Actions, merge queue, deploy, or post-merge smoke. Record the PR reference, remove clean queued PRs from active attention, and continue with the next authorized work.
- Preserve concise technical detail after the executive summary: changed behavior, tests/gates, review evidence, branch/commit/PR/deploy references, risks, follow-ups, skipped validation, and early-warning smoke state or why it was covered/skipped.
- When you name a backlog, requirement, plan, or tracker item by its key or ID (`FR-3`, `item 17`, a `METH-FU-...` slug, an issue number), immediately follow it with the item's short title as `KEY: <short title>` -- a bare key is not self-explanatory to a human. This holds in all human-facing output, not only delivery summaries: chat, PR titles and bodies, commit messages, handoff and continuity docs, decision records, and status lines.
- Completion claims need proof-of-done evidence, not activity. Name what ran, coverage, and required proof that did not run. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof; report gaps as risk, blockers, or follow-up.
- Session journal, event-log, board-currency, context-rotation, deployment-notification, milestone-ledger, and iteration-review closeout details are owned by their dedicated skills/references. Delivery summaries must name the recommended next work item when known.
- A delivery summary is not a license to stop. Do not turn recommendations into permission questions or stop menus. If the summary names an authorized next action and no true blocker or explicit stop request prevents it, start that action in the same turn. The Stop guard's `stop.announce_and_stop` check enforces this: announcing the action is not starting it.
- A queued-delivery summary must end with either `Next work already underway: <specific action/artifact>` followed by that action, or `No authorized next work remains` plus checks across packet, backlog/readiness, continuity, PRs, and deferrals.
- For provider-backed repos the merge with its closing reference is the completion claim, not a hand-close: once the close exists, the delivery summary cites the auto-closed issue(s) as proof; before it exists - a queued summary, or a merge to a non-default base - it cites the PR and the closing references it carries, described as intended rather than observed.

## Goal Orchestration

- The delivery hierarchy is `Goal -> Milestone -> PR/tactical item`; goals bind source-of-truth plans to execution. Substantial multi-milestone, multi-PR, overnight, or ambiguous "build/ship/finish" work needs goal planning before milestone planning unless adapter-exempt or provider-item mode.
- Goal plans live under adapter `goalArtifacts.sourceOfTruth` and state outcome, benefit, success, non-goals, milestones, dependencies, risks, review, validation, and completion criteria. In provider-item mode, the synced issue/work item is completion authority; repo goals never obscure an active provider item.
- Goal-mode startup/status surfaces `next_goal_name`, `next_goal_short_description`, `next_goal_claude_prompt`, and `next_goal_next_action` when no ledger exists. Goal execution state lives in `.ai-work/GOAL_RUN.json`; at startup/boundaries run `tautline goal-next --target .` before `milestone-next` when a ledger exists, then start the printed next action.
- Substantial work needs a current goal ledger in goal-mode products or a synced/reviewed provider item in provider-item products before implementation starts. Use `tautline goal-start --target . --goal <source-of-truth-goal-plan>`, `goal-advance`, and `goal-status`. Milestone completion requires validation proof or a linked milestone ledger; deferral requires policy reason, and goal completion needs validation plus required review/UI evidence. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps, not proof.
- Do not claim a goal complete unless `goal-advance --event goal-complete` moved the ledger to complete. Milestone or PR boundaries are not stop points while `goal-next` returns executable work. Retire the active goal ledger when its initiative ships or switch stale ledgers when branch work diverges.
- Claude lanes should prefer Claude Code `/goal` for substantial reviewed goal work when supported; Claude Code `v2.1.139+` is required. If unavailable, use the ledger/milestone loop. `goal-condition --target .` must name one measurable end state, proof, and constraints.
- For a goal whose source-of-truth plan explicitly declares multi-session scope or known operator-input true blockers, `/goal` may stop for the session only after authorized increment, continuity handoff, journal handling, and boundary proof; context exhaustion alone is not goal completion. Before `goal-advance --event goal-complete` or any iteration-review boundary, lane adapter `sourceAdapterSha256` must match the canonical source adapter.
- `goal-next` and `goal-status` must surface known operator-input dependencies before plan-finalization effort. Defer unsatisfied policy dependencies with `milestone-deferred`; block only for confirmed true blockers.
- Done has one definition: `scope_complete`, `tests_written`, `tests_green`, `review_clean`, `evidence_bound`, `pr_handed_off`, and `board_updated`. `pr_handed_off` means the PR is out of the lane's hands - merged, auto-merge armed, or queued - onto the integration branch; an open PR with nothing armed is not done, and a queued auto-merging PR is done, so never wait for one to land. Under `definitionOfDone.enforcement: block` `goal-advance --event goal-complete` refuses a failing condition before any board mutation; the default is `warn`, which reports and does not refuse. A condition it cannot read is `unknown`: reported loudly, never `0`, never blocking. Exits are satisfying it, disabling it under adapter `definitionOfDone.conditions`, or `blocker-declare`. `tautline done-check --target .` prints the verdict per condition.
- A goal handed to a human is the sole content of the response - no preamble, no commentary, no code fence - so a whole-response copy yields exactly the goal; anything else they need goes in a separate message before it. Prefer `goal-assignment --out <path>`: a goal is an artifact, and the file bypasses every renderer between composition and paste.

## Backlog Provider Intake And Grooming

- When adapter `backlogProvider.enabled` is true, the provider owns stakeholder triage and board `Status`; repo plans, review gates, and PR planning still own implementation authority. Use `backlog-provider-status`, `backlog-provider-next`, and `backlog-provider-sync --item <id-or-url> --write`; do not execute directly from a raw Project item. Compatibility `goalTracker` remains; new adapters use `backlogProvider`.
- A `backlogProvider` board's schema is human-owned. Agents keep item state accurate through sanctioned commands; content fields are default-deny unless opted in. Schema drift uses examine/adopt with confirmation, never lane-side mutation.
- Provider-backed status is live operational state. Customer-facing goals, milestones, features, bugs, tasks, and board-backed native subtasks need current structured `Status`; free-text comments do not replace the structured Project `Status` field. Board checks, strict status, and pre-push enforce this except during provider unavailability.
- Stakeholder clarification happens on the active issue when enabled. Ask one marked question, sync answers at boundaries, and copy decisions into plans. Repo-backlog migration is item-by-item through interview and approved exports.
- The stakeholder board exists only for customer-facing functionality and customer-impacting bugs. Internal debt/refactor/CI/dependency/developer-experience/test-infrastructure stays in repo backlog unless concrete customer impact is accepted.
- The board's order is the work order by default. `backlog-provider-next` and compatibility `goal-tracker-next` select the top workable ready item unless priority ordering is configured. Assigned epics are hard scope boundaries unless explicitly lifted; with no epic assigned, use the board top.
- Every backlog item leads with `## What this delivers`, `## Why it matters`, then `## Technical detail`. A synced provider item links externally, preserves stakeholder guidance, and passes plan review or valid exemption before implementation. With `completionUnit: provider-item`, the external issue/work item is the completion unit.
- Every epic carries a methodology-owned grooming Definition of Ready. It becomes consumable only after grooming-decompose shapes feature items with acceptance criteria, `## Verification` proof, privacy/security negative tests, adapter numbering, and a native sub-issue parent link. The first `readyStatuses` transition is gated on DoR satisfaction, and `validate-grooming` reports DoR pass/fail read-only. This is distinct from plan-review cap/focus-transfer handling. Memory or Open Brain may inform DoR content but never defines the DoR.
- The board's identity is adapter-declared. Resolve owner and `projectNumber` only from the adapter, via `backlog-provider-board-check` / `backlog-provider-next` — never by ad-hoc `projectsV2` discovery, display-name resemblance, or an owner/number carried forward from prior work. A queried project number that differs from the configured `projectNumber` is blocking drift, not a fallback candidate.

## Board Currency And Subtask Status

- Provider-backed goal and milestone status must remain current at each lifecycle transition. `goal-start` moves mapped work active; completion moves it done; blocked/deferred moves it blocked. issue comments are not a substitute for structured board `Status`.
- The stakeholder board is the live channel for customer-facing goals, milestones, features, bugs, tasks; keep it always current - no excuses, no deviations. Provider-backed lanes move work active on start and done when issue/PR ships, including standalone bugs/features.
- Board currency is a blocking gate, not advisory. `methodology-status --strict`, `methodology-status --fail-on-drift`, `backlog-provider-board-check`, and pre-push reconcile in-scope items against issue/PR state: closed/merged work must be done, open work must not be done, unconfigured statuses are drift, and verified current lane work that is not active is drift.
- The board-currency gate is scope-aware: hard pre-push blocks the branch/PR item, changed source-of-truth plan/spec mapped to a Project item, or active ledger item when no branch or plan points elsewhere. Unrelated stale ledgers are startup warnings.
- Planning counts as starting. Drafting a milestone spec or plan for a board item requires moving it active before implementation accumulates. Provider errors or missing Project mappings are fixed before implementation or recorded as blockers.
- Native GitHub sub-issues/subtasks that are board items have their own `Status`. Parent issue status is not a substitute, and a board-backed subtask in an active status means its parent issue must be active too. Sanctioned paths reconcile parent and subtasks together.
- Subtask issue/PR closure is independent of board `Status`: finish the subtask first, or update the selected subtask directly. Open board-backed subtasks, or native subtasks missing from the board, block marking the parent done; closed/merged subtasks require evidence first.
- Moving a provider-backed item to done requires durable verification in the linked issue or PR, measured against that item's written acceptance criteria. `goal-advance`, `backlog-provider-update`, and compatibility `goal-tracker-update` done moves post `## Verification Evidence` before status change; chat prose is not enough. When the item has acceptance criteria the evidence carries a line-by-line table, one PASS/FAIL row per criterion; an unmet criterion is a FAILED AC, never a deferral, and blocks the move. Verifying the implementation against itself - "within the shipped model" - is forbidden; the oracle is the written criteria. `ac-verify` prints the skeleton, a milestone `acVerification` key carries it on the autonomous path, and `backlogProvider.doneEvidence.acTable` selects off/warn/strict.
- Filing a customer-facing bug is not complete until it is on the board. `gh issue create` does not place the issue on the Project board; customer-facing issues require board placement with Item Type and current `Status`.
- Pull requests in provider-backed repos reference their backlog item precisely, because agents and board mirrors read PR text as their evidence. The item's GitHub ISSUE number in the same repo appears in every PR title (`fix(758): ...`) - never the Project number, never a project item id. A PR that FULLY COMPLETES an item per the lane's completion gates adds one closing keyword per completed item, each on its own line (`Fixes #758`). When the item's issue lives in ANOTHER repository, both the title reference and the closing keyword use the qualified `owner/repo#758` form, because a bare `#758` always resolves against the PR's own repository and would address, and can close, an unrelated issue there. A PR that only ADVANCES an item carries NO closing keyword anywhere in its body or its commit messages and references the item in the title alone (`feat(912): ... (#912 AC4)`), because a keyword would auto-close unfinished work on merge. Never reference an issue the PR does not implement. This governs new PRs; merged PRs are not edited to backfill it.
- The auto-close a closing reference triggers IS the completion claim, replacing closing the issue by hand, and `backlog-provider-closeout-check` verifies the close landed. GitHub honours a PR-body keyword only when that PR's base is the repository's DEFAULT branch: a lane integrating on another branch gets no auto-close at merge, its squash commit message is what carries the keyword to the promotion that fires it, and nothing tracks the claim until then. Before that close exists, a delivery summary cites the PR and the closing references it carries, never a closure that has not happened.
- The closing-reference gate runs only where the backlog is issue-backed - an enabled provider or tracker with `owner` and `projectNumber`. Where it applies it still demands a keyword from every non-exempt body, so an advancing PR can be refused for obeying the rule above; that demand is unaligned. Resolve it by binding the item, or through the sanctioned exemptions `allowRepoOnlyGoals` and a non-development work profile - never by referencing an issue the PR does not implement, which buys a wrong auto-close on another item.

## Cross-Lane Coordination

- `laneCoordination` is the repo-tracked coordination backbone. Chat, memories, and branch drift are evidence only; tracked contract, lane board, and lane status files are durable.
- Default enforcement is strict. `lane-start` bootstraps missing artifacts. Missing, stale, untracked, uncommitted, or unpushed state in the current lane's status file, the shared contract, or the lane board fails `lane-coordination-status`, `methodology-status --strict`, and `methodology-status --fail-on-drift` unless the adapter warns or disables coordination. Other lanes' stale/untracked/dirty files are informational only.
- Run `tautline lane-coordination-status --target .` at startup, before multi-lane plan finalization, at PR boundaries, and when a lane discovers a dependency on another lane. If artifacts are missing, run `tautline lane-coordination-bootstrap --target . --write`.
- Each lane updates only its own status file with `tautline lane-coordination-note --target . --lane <lane> --goal "<goal>" --current "<current work>" --depends-on "<dependencies>" --provides "<provided interfaces>" --blockers "<blockers>" --pr "<PR or commit>" --write`. Notes name touched contracts/routes/data/API surfaces, dependencies, provided interfaces, blockers, and current PR/commit before multi-lane implementation or PR queue.
- If a lane changes something another lane owns or consumes, it must not silently implement an incompatible version. Update the contract, open a small shared contract/interface PR, or explicitly take ownership and mark dependent lanes before large PRs proceed.
- Shared route names, account semantics, order states, storage interfaces, event names, API/server-action shapes, and deployment conventions should land early as small shared contracts before dependent lane implementation PRs.

## Context Rotation

- Context rotation is routine maintenance, not a permission checkpoint. Default policy uses soft threshold `60%`, hard threshold `75%`, and a `15m` long-goal heartbeat; managed Claude startup sets `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85`. Do not force half-context compaction.
- At PR queued/completed, milestone, goal, summary, handoff-for-review, or long `/goal` heartbeat boundaries, check visible context pressure. At/above soft threshold, refresh continuity, update ledgers, handle journals, compact/restart through the strongest host-supported path, and resume; do not describe context exhaustion as the reason to stop working.
- A mandatory rotation triggers only on a real host-exposed (measured) context percentage. A self-asserted or estimated context percentage is advisory only and is never a mandatory-rotation trigger or a stop, defer, or handoff reason.
- Do not rotate mid-edit, on an unsafe branch, before required review/preflight for the current PR tip, or while a monitor needs active recovery. If the host cannot compact/restart from the current turn, write continuity/local evidence and state the exact fresh-session startup action; do not use fallback wording such as `only you can trigger /compact`.
- If rotation coincides with credential, seeded-account, TOTP, served-origin, or live-verification friction, run adapter-declared discovery first. If unavailable, state one exact setup blocker or action.
- After rotation, the next session runs lane startup, methodology status, pending journal publication, then `goal-condition` or `goal-next`; it continues the active goal without asking whether to resume.
- `context-rotation-check --target . --boundary <boundary> --context-percent <percent> --context-percent-source estimate` records estimated pressure. An estimated percent can recommend rotation but never make it mandatory. Details live in context-continuity and goal-execution references.

## Planning

- Risk pays for planning ceremony. T0 needs no reviewed plan; T1 uses inline/packet plan; T2/T3 work requires plan review and cross-model review.
- Do not default uncertain work into plan review. Inspect adapter, paths, issue/PR, backlog, and packet evidence; choose the lowest defensible tier, or ask one exact blocker question only when tier changes approved scope/risk.
- Plan finalization means asking for approval to implement, invoking `ExitPlanMode`, leaving plan mode, writing an execution packet, marking ready for development, pushing a plan-only PR, or starting implementation. `plan-finalization-precheck` and the `Cross-Model Review Evidence` section exist only for T2/T3 plans.
- For T2/T3 plan review, run one authoring-model native/self-check before R1, run `run-plan-review`, inspect/classify the log, and bind it with `finalize-plan-review`. Do not rerun Codex just to bind manifest evidence, hand-edit `.plan-reviews`, disable hooks, skip required `ExitPlanMode` checks, or ask for a bypass.
- Plan-review convergence is a ladder: rounds 1-2 are the target; rounds 3-4 self-authorize with a recorded `--exception-note`, never an operator escalation; past round 4 refusal is unconditional; the split is mandatory unless the bound evidence is clean and current. The round-4 cap counts successful reviewer invocations per source plan, not `--round` labels: re-running a label still spends budget. Other findings transfer into the implementation review focus list; do not spawn plans to rebind a hash. If reviewed plan content is edited after the final allowed round, the review evidence is void for that file: create a successor source-of-truth plan carrying every unresolved finding, mark the original superseded, and review the successor within the normal cap; never retire, rewrite, or rebind existing review runs or manifests.
- Plan-review P1 must name user-visible failure or expensive rework prevented before implementation; otherwise route it as non-blocking review focus or backlog work.
- Plan-review evidence is content-hash-bound and verdict-bound when it exists. Store it under `<planningArtifacts.sourceOfTruth>/.plan-reviews/`; final verdicts require zero unresolved Critical/P1.
- Project adapters own source-of-truth plan/spec paths, templates, triggers, and scratch paths; tool/home plan folders are scratch.
- When backlog, packet, summary, handoff, context, or board order identifies next work, planning that item is the next safe action unless a true blocker exists. Treat an item as identified when context gives enough signal; do not convert named next work into permission.
- Required plans state goal, non-goals, evidence/source links, assumptions, ordered scope, dependencies, acceptance criteria, named tests/specs or validation commands, review/merge gates, risks, decisions, and completion definition. TODO-only, generic, vague, missing-test, missing-gate, or missing-acceptance plans are stubs.
- Before implementation, every plan or packet item must state the proof-of-done standard: checks, reviews, runtime/manual evidence, board/ledger transitions, deploy/health proof, or N/A reasons that would make completion believable. `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof of completion; they are gaps/blockers.
- Author every T1+ plan in the plan-authoring standard shape (T0 mechanical exempt): parallel autonomous workstreams with an explicit dependency graph (parallel-safe vs. hard-predecessor) each assigned its own worktree, per-task model-tier tags (mechanical|standard|deep), and the execution-autonomy contract (best judgment + `decision-record`) embedded in each task. This authoring standard applies at every tier through the plan-authoring skill; the mechanical check is the finalize-plan-review guard, which enforces the shape for plans that go through plan review (T2/T3) per the adapter `planning.authoringStandard.enforcement` knob (off|observe|advise|block, default advise). T1 packet-only work follows the standard by authoring guidance; it has no plan-review finalize seam to block at.

## Technical Stack And Platform Defaults

- Project adapters own `technologyStack`: approved cloud/hosting providers, credential paths, deployment defaults, and non-negotiable platform choices.
- New projects default to AWS for cloud services unless the adapter overrides `technologyStack.approvedCloudProviders` and `technologyStack.cloudProviderDefault`. Do not introduce Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase, or another cloud/hosting platform unless the adapter or human operator approves.
- Tool, framework, starter-template, AI, or hosting-product defaults are not approval for new deployment platforms; use the adapter path or ask one exact approval question only when no approved path exists.
- For AWS-approved lanes, AWS CLI is the default deploy credential path. Check `aws --version` and `aws sts get-caller-identity` or adapter identity command/profile before deployment/provisioning. Do not ask for SSH keys, create SSH-key blockers, or invent alternate deploy credentials until the AWS CLI path has been checked.
- Only adapter overrides may declare non-AWS platforms, SSH hosts, non-CLI credentials, deployment targets, or provider-specific setup. Unapproved cloud/hosting, billing, secrets, production deploy, observability, database, or operations burden is T2+ and may be T3.
- GitHub-backed workflows are rate-limit-budget-aware: prefer REST for equivalent issue/PR reads/comments, cache Project board reads, check GraphQL budget before point-heavy calls, and back off or use cached snapshots before zeroing budget.
- Plan/spec authority comes from adapter source-of-truth paths; outside paths are scratch unless adapter-approved. Backlog/source-of-truth paths beat tool defaults. T2/T3 plans must include `Cross-Model Review Evidence` before finalization.

## TDD And Behavior Specs

- Functional changes require strict test-driven development: plans name test files/cases before implementation, and tests are written first where practical.
- Customer-facing behavior specs are project-configured. If enabled, behavior specs such as Gherkin are written or updated before customer-facing code.
- If the adapter declares reviewed behavior-spec source materials, treat them as upstream source material, not inspiration. Adapt them into executable specs before new scenarios; preserve intent and document deviations. The source-of-truth plan must include `## Behavior Source Materials` and account for every source as reviewed/adapted or not applicable with a real reason. Use `BEHAVIOR-SOURCE-EXEMPT: <real reason>` only there.
- Behavior-spec-required projects run `tautline behavior-spec-status --target .` before plan finalization, merge, or delivery for customer-facing behavior. Inactive scenarios and harness/app target mismatches are skipped validation, not coverage. `@pending`/inactive scenarios require owner, reason, and un-pend trigger within adapter limits, written as `@pending @owner:<goal-or-lane> @reason:<why> @unpend:<trigger>`; "no harness exists" is a P1 coverage gap until the harness executes the changed app. `--base <ref>` adds a report of the scenarios newly inactive versus that ref and never changes the exit code; `tautline behavior-spec-delta-check` enforces the same rule on staged changes.
- Green tests must mean working software. A suite with `@pending`/pending, skipped, disabled, quarantined, or wrong-target tests is not proof for that behavior. Count only checks that executed the changed behavior; disclose non-executed tests as coverage gaps. Gaps between green CI and broken production are Critical test gaps. The machine-checkable form of this proof is a `tautline-test-run/v1` record written by `tautline test-run`; boundary enforcement of that record is versioned separately.

## Early-Warning Smoke

- Early-warning smoke is no longer a standing gate for every tactical iteration. Routine startup/main health is checked by lane startup; full preflight before push and CI remain the branch-quality gates.
- Run the adapter early-warning smoke only when the adapter, source-of-truth plan, issue, human operator, or a concrete risk signal asks for it. Do not launch background smoke monitors merely because a new plan/spec write, edit, PR, rebase, or iteration boundary began.
- If an early-warning smoke is running because it was explicitly required, supervise it with the normal background-work monitor rules and do not start duplicate local-service smoke commands for the same lane resources.
- A known smoke failure, stale required smoke, wrong target, or resource contention interrupts the relevant risky action until investigated or proven unrelated with named evidence. A missing ambient smoke poll does not block routine commit, push, queued-delivery summary, or next-work selection.
- Passing early-warning smoke is advisory confidence, not a new pause point. It does not replace full preflight, implementation review, merge checks, or CI.
- Do not delay clean queued-delivery summaries for routine post-merge smoke unless a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.

## Go-Live Readiness Gate

- A lane that serves a customer surface declares it: `goLiveReadiness.profile: live-tenant` in the source adapter. Declaring it binds the lane to the go-live gates below; a milestone-close `deploymentTargets` entry without that declaration is a warn today and becomes drift once `goLiveReadiness.enforcement` is `block`.
- The gates are: customer-outcome health contract; detection baseline + branch protection; required-runtime-secret registry; CI test gate; critical-journey ratchet + flaky quarantine; open-remediation obligation ledger. Each must reach its own satisfiable enforcing state, or carry a recorded decline. That state is not uniform: some controls take `enforcement: block`, while others are satisfied by populating what they measure -- declared journeys, quarantine bounds and a scan path, alarm sources and required checks. The gate names the specific state per control when it refuses; adding an `enforcement` key to a control that has none makes the adapter schema-invalid.
- A decline is a declaration, not a loophole: `goLiveReadiness.declines` names the control and states a reason. A control that is off with no decline is an undeclared gap, and the gate says so by name rather than reporting a healthy total.
- Readiness is a property of the shipped controls, not of a review, a checklist, or an assertion that the work is done. Do not record a lane as go-live ready while a gate is off and undeclined.

## Review Before Push

- Review happens before merge/readiness, not after shipping. Open an early draft PR for non-trivial or customer-facing work by plan finalization or first commit; complete review applies before ready/merge.
- Before commit, review, push, or tactical subagent dispatch on an existing PR branch, run `branch-liveness-check --target . --strict` or adapter equivalent. Inactive PR branches stop branch work; sync main and continue from source-of-truth work.
- Implementation review is risk-tiered. T0 uses self-review plus tests/preflight. T1+ keeps one cross-model review round. T2/T3 also run the model-native Stage 1 sweep and record it with `record-stage1-sweep`; T0/T1 do not write that artifact by default. The `review-before-push` skill owns the detailed command sequence, defect checklist, packet requirements, and evidence rules.
- A recorded review round refuses when the generated adapters are the only dirty files: an `--uncommitted` wrapper would review a tool-injected re-render instead of the work. Discard or commit the render, or pass `--allow-adapter-dirt`.
- Adapter-backed pushes must have CLI-recorded, classified review evidence unless disabled by adapter. Evidence is scoped to the assembled outgoing diff, persists as the tracked `<planningArtifacts.sourceOfTruth>/.impl-reviews/` ledger, and must pass `review-evidence-check --target . --strict` before ready/merge. Per-task, subagent, or milestone-local reviews do not replace the assembled-diff review.
- Adapter-backed Codex CLI calls use framework launchers so adapter `review.codexFastMode` is enforced consistently. Cross-model review is a confirmation pass with bounded rounds. Review budgets come from adapter `review.roundBudgets`; after budget is spent, route out-of-AC findings at honest severity or take a self-authorized round.
- Implementation-review rounds are a ladder, not a wall: the adapter budget is the target, the hard cap is target + 2, rounds in between self-authorize with a recorded `--extra-round-reason`, and a confirming round on an already-remediated diff is not charged at all. **No round decision on this surface is ever an operator escalation.** Record a genuine scope/risk/security/cost fork with `decision-record --reversibility hard-to-reverse` and keep working; never block on an answer.
- Rounds are counted by **execution per outgoing lineage** (branch plus review base), never by the `--review-round` label — six runs labelled `R1` are six rounds. The budget is spent by **charged** executions (new inquiry); the absolute ceiling counts **total** executions, confirming ones included, because free is not unbounded. `codex-run` narrates the count and warns at three. A base change starts a new lineage.
- A review with no outgoing diff is refused at run, finalize, and evidence-scan time: `head_sha == base_sha`, zero diff bytes, or the empty-string digest means no subject, and a verdict over no subject proves nothing. Commit to a feature branch first; no ledger is written and no round is spent.
- Prose-completeness and coverage-breadth findings on non-authoritative documentation default to P2 (deferral-routable) unless they create incorrect process authority.
- Routing to a backlog row is the deferral path for any finding **not open against the item's acceptance criteria**, recorded at its **honest severity** with `ac_ref: null` and a `routed_to` row. A finding open against an acceptance criterion is fixed or refuted with cited evidence regardless of severity — never routed, never downgraded to make routing legal. "No unresolved Critical/Important ships" means unresolved **against the acceptance criteria**.
- Critical/C1/P1 findings block merge and create repair work, not a stopping point. Fix them within approved scope and rerun tier-appropriate review on the changed assembled diff. Ask one exact blocker question only when every viable repair path changes approved scope, risk, cost, security posture, production behavior, or standing approval.
- Review output must be retrieved, inspected, and classified before the gate is clean. A clean-review claim cites the artifact or no-findings verdict; wrapper text, missing grep markers, speaker tags, or incomplete assistant output do not prove cleanliness.
- Review runs are supervised like background work. Capture log/PID/monitor evidence, poll until terminal result or true blocker, and recover/rerun stale review work when safe.
- A pre-push whose full branch diff against the configured base is entirely within the adapter-declared PM surfaces (`productDevelopment.surfaces`) skips the review-evidence and CI gates; the board-currency and blocker-state gates still run. Every other push runs the full gate (fail closed): code, mixed, or ambiguous diffs, a docs-only increment on a branch that already carries code, a code-into-surface rename, and force, multi-ref, branch-delete, tag, non-current-branch, or undeterminable-base pushes. Path scoping is mode-independent and never widens the gate.

## Merge And CI

- Local pre-merge validation is required before push/queue: main green, fast/full preflight, and test-environment gates. GitHub Actions do not replace local gates.
- Routine merge is merge queue or auto-merge, never admin merge. `--admin` is break-glass only with documented reason. Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts as approval. Standing approval recorded in a source-of-truth artifact counts only when the named conditions match.
- Final preflight latency is usable once the PR tip is frozen; plan, poll, or start the next item in a SEPARATE worktree, never touching the proving diff.
- After enabling auto-merge or queueing, record the PR reference, advance ledger, remove the clean queued PR from active attention, and continue.
- A queued, auto-merge-enabled, merged, or closed PR branch is inactive. Do not run more review rounds, commits, pushes, reverts, or tactical subagents against the inactive branch. After methodology status, run the adapter's main-health/smoke gate, open-PR health check, current-branch liveness check, and merge-conflict check, then continue from source-of-truth work.
- Clean queued PRs are asynchronous external gates. Do not wait on GitHub Actions, merge queue, deploy, or post-merge smoke after clean local gates/review. In-session queue checks are allowed only for a known failure/degraded signal, explicit request, or dependency on merged main.
- Exceptional queue checks use authoritative PR state and merge-group/check-run evidence. Do not treat `mergeQueueEntry.estimatedTimeToMerge`, repeated `AWAITING_CHECKS`, byte-identical queue output, or status-only queue prose as progress.
- Terminal success reports through Delivery Summaries, not monitor-only text. Interruptions include queued/auto-merge-enabled current branch, merged/closed current-branch PR, missing merge-conflict check for a PR-based project, queue rejection, main red, deploy failure, failed checks, or unclear mergeability. A local-only `mergeConflictCheck` can check for unresolved local merge conflicts.
- A merged PR's closing references are what move its backlog item to closed, so the PR title and body must satisfy the PR-reference contract in Board Currency And Subtask Status before the merge, not after: a body is only editable while the PR is open.

## Demo And Staging Deployment

- Deployment behavior is adapter-owned. Canonical methodology only requires that adapter-declared deployment targets be honored; it does not invent deploy commands, hosts, migrations, restart steps, or health checks for a project.
- If the adapter declares a demo, staging, or production target and says milestone close includes deployment, deploy the just-merged `main` HEAD with the adapter procedure after source-of-truth work is Done, `main` is merged, the delivery summary is prepared, and continuity is refreshed.
- The adapter owns target URL/host, deploy commands, rollback, credentials, and health checks. Follow it verbatim; do not invent shorter sequences.
- A health check whose `sha`, version, build identity, or equivalent field still shows the pre-deploy commit is a failed deploy, not a success, when the adapter requires build-identity verification.
- A failed deploy or stuck pre-deploy build identity interrupts as P0. Roll back per the adapter's rollback procedure when rollback is configured, then investigate before more feature work.
- A clean adapter-declared milestone deployment is part of the milestone delivery summary, not a separate report. The executive summary names the deployed commit SHA, target, and health-check result.
- If the adapter does not declare deployment as milestone-close work, milestone close stops at push/merge, delivery summary, and handoff refresh.

## Background Work

- Long/background work must be observable and supervised: command, log, PID when available, interrupt conditions, timeout, heartbeat, and terminal summary.
- A background command without a monitor is incomplete work. A monitor without forward motion is also incomplete work. Starting, arming, or announcing a monitor is not a stopping point; poll, recover, or start parallel-safe work.
- Heartbeat/poll cadence must be concrete and no longer than 10 minutes unless adapter-stricter. Before any autonomous-loop yield, delayed wakeup, `ScheduleWakeup`, or host-equivalent heartbeat, enumerate current work and advance anything possible.
- A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision. If monitored work may outlast the turn, arm `ScheduleWakeup` or an equivalent host self-wakeup at the same cadence.
- When per-checkout product-dev mode is active, the fake-monitor background-command guard stands down for that TTL-bounded, advisory-announced session; the board-structure and item-content safety blocks and every code-safety and plan-review gate are unaffected.
- Passive monitor stops are forbidden. Do not end a turn with only "monitor is running", "monitor watches", "waiting on merge", "waiting on checks", "R2 running", or equivalent status. Passive monitor stop examples include "CI is processing", "the deploy is underway", "the review is running", "checks are in progress", or updates without same-turn next action, active poll evidence, terminal outcome, or true blocker.
- Strict monitor checks require a verified PID/process identity, not only a fresh log. Two no-progress cadences are stale/hung unless adapter-stricter.
- Terminal monitor states are success, failure, cancelled, timed out, queue rejection, deploy failure, main red, or project-defined terminal state.
- Transient provider/API failures are recovery-loop work. Claude, Codex, GitHub, network, overload, rate-limit, timeout, and 5xx/529 failures require retry/poll/backoff until class changes. Frustration, profanity, or an angry interjection is not an explicit stop.
- Routine queued PRs are not background work to supervise; after clean local gates/review, queue it, record it, stop watching, and continue.
- Claude Stop response guards and tool-rejection hooks are mandatory in Claude lanes. The STATE gates arm from any pending-work source -- goal ledger, NEXT_SESSION next action, execution packet, milestone ledger -- and from a live or unread detached run, with no live goal required; only the legacy PHRASE checks stay scoped to a proven live goal session and block passive/status-only stops, terminal continuity omission, false-active rejected-tool status, and standby language.
- A turn may not end on a detached run nobody can wake to, or on a finished run whose terminal summary is unread; `tautline monitor-status` is what clears that gate.
- With pending work on record, a stop requires that item in progress this turn, the queue enumerated empty, or a declared blocker. A null or bare-acknowledgment turn answering a continuation prompt is stop-evasion.
- Arming a verdict monitor and stopping it are one paired obligation: stop it in the same turn its verdict arrives, keep at most one live, and treat a timeout for an already-answered subject as a leak.
- Prefer the bounded form for one-shot completion waits: `tautline background-run` plus `monitor-status` at the checkpoints. An unbounded follow cannot report completion -- it goes quiet whether the run finished or wedged.
- Monitor filters anchor on `^`-prefixed markers only the producing process emits, never words that also appear in the diffs or logs under review. Liveness checks must observe their subject.
- Harness-tracked background work re-invokes the agent; a detached `background-run` never does, and `monitor-status` reports only when called.

## Lane Lifecycle

- Adapter-backed lanes run `lane-start --target .` at session start, then `methodology-status --target . --fail-on-drift` before plan/implement/review/commit/push/delivery work.
- Before running startup gates, resolve the methodology CLI. Use `minervit-methodology` from `PATH`; if it is missing from `PATH` or exits 127/command-not-found, use `$HOME/.config/minervit/methodology.env` or `$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology`, then rerun the same gate. A missing `PATH` entry is not a failed methodology gate, not permission for ad hoc checks, and not a reason to ask for a person-specific checkout path. Install with `bin/minervit-methodology install-cli`.
- Startup refreshes adapters, installs hooks, writes lane-local state, and reports profile, ledgers, release-track, and latest-code. Missing hooks, render failure, drift, or stale unlocked methodology blocks unless locked or `--skip-update` was explicit.
- A debt-class startup failure (`methodology-status --fail-on-drift` exit 2) starts a remediation session: only fixing the issues or declaring a blocker is permitted; break-glass stays operator-only. Integrity failures (exit 1) never start project work; interactive launches offer only a repair session. See `docs/reference/startup-remediation.md`. No dead ends: gates print their exact remedy with the error; a pin hold on a trusted checkout is `held` (launch continues), not `failed`.
- Generated adapters carry the template version that rendered them, and a render never rolls one back. `lane-start` and `init` render implicitly; SessionStart hooks do not. A newer on-disk template no-ops with a named refusal there — a stale-pinned lane must still start in order to repin — and exits 1 on `render-adapters --write` unless `--allow-template-downgrade`. The stamp is identity, not content: stamp-only differences are never drift and never a rewrite. Detection is version-only. Renders that write name their trigger and process.
- Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`. Use `render-adapters --write --json-only` for JSON-only changes. Work profiles keep `development` strict; non-dev profiles relax implementation gates only for approved docs/assets and still block code/config/generated/secrets/base-branch pushes.
- Unlocked adapter-backed product/client lanes do not raw-pull latest methodology by default; existing lanes default to stable/manual/dry-run pins. `lane-start` and `methodology-status` report pin, available update, WIP reasons, and migration-report state. Deliberate `sync-methodology --target .` honors track, WIP, trust, and rescue checks.
- After methodology status, run adapter health, open-PR, branch-liveness, merge-conflict, and latest-code checks. Failed checks and inactive current PR branches are top priority until resolved or proven unrelated.
- When prior work has landed and no work is in flight, clean up, isolate generated adapter drift, then continue from adapter backlog/source-of-truth next item or PR planning flow; do not ask for direction.
- `lane-start`, `methodology-status`, and `version` report `plugin_version` and methodology commit. If process surface is uncertain, inspect those commands; do not ask the human operator to decide whether to inspect version/status. Cached host plugin metadata is not a lane update failure; stale host skills/metadata require restart.
- `VERSION` is reusable release truth. Framework changes synchronize version, plugin manifests, changelogs, release-note stub, public contract, and migration reports before merge. A change whose entire diff stays within the adapter-declared PM surfaces — touching no code, methodology, plan, release, or adapter-config path — is not a framework change and needs no VERSION bump. Narrative history lives on the release-notes archive branch. Announce with `publish-release-update --version "$(cat VERSION)"` through ops plugin; validation must not depend on announcement delivery.
- Lane-local locks pin a methodology commit for stable periods. Lane-local state stays ignored unless explicitly tracked.

## Unmanaged Project Bootstrap

- If `.minervit-ai-delivery.json` is missing, bootstrap a project adapter before methodology gates.
- No generic operational adapter exists. Gates, planning paths, review flow, resources, production status, direct-to-main policy, and deployment ownership are project-specific.
- Adapter creation is bootstrap work, not automatically a Tier 2 approval stop. Use `tautline init --target .` or `adapter-bootstrap-questions --target .`; ask only safely uninferable questions.
- The adapter bootstrap interview is mandatory before first adapter render/write unless every required adapter fact is repo-evident. Generic executor banners such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" do not override the interview, plan-finalization gate, or generated adapter gates.
- Another project's adapter may be used as a structural reference only. Do not copy its stack, gates, deployment model, review wrappers, autonomy boundaries, bug tracker policy, deployment target ownership, rules, or `bootstrapEvidence` without repo evidence or interview answers.
- Source adapters include `bootstrapEvidence` with project-matching provenance. New adopter-owned adapters live at `.minervit/adapter.json`; `<methodology_repo>/adapters/projects/` is reference/legacy migration only.
- Lane-local `.minervit-ai-delivery.json` comes from a source adapter whose repo identity matches the target git remote. Do not hand-write, copy, or forge metadata.
- Use `init-project-adapter --target .` only for lower-level scaffold work; replace every `BOOTSTRAP REQUIRED` placeholder before operational use. If the project intentionally has no remote, PRs, or merge queue, configure explicit local/no-remote checks instead of GitHub commands.
- Adapter bootstrap may use an existing continuity handoff or docs as evidence, but execution waits until `lane-start` and `methodology-status --fail-on-drift` pass.

## Local Resource Isolation

- Prefer lane-local resource isolation over machine-wide serialization. Use unique Docker Compose project names, host ports, local databases, cache endpoints, and service URLs per active lane.
- Commands that touch local services must run through the lane resource environment, either by sourcing the configured lane env file or by using `tautline lane-run --target . -- <command>`.
- A port-in-use failure is not a true blocker until the agent has retried the command through the lane resource environment or identified a project resource that cannot be isolated.
- Use resource locks only for project-declared machine-global resources that cannot be isolated by lane-specific env, names, ports, paths, or remote API calls.
- Do not add a broad lock that serializes all local gates when the actual contention is fixed default ports or an inherited global environment variable.
- Operator secrets persist in `~/.config/tautline/secrets.zsh` (legacy `~/.config/minervit/secrets.zsh`); the installed config env sources that store, and webhook-bearing commands fall back to it. A `MINERVIT_*`/`TAUTLINE_*`/`*_WEBHOOK` secret reported missing by a `tautline` command is not a true blocker until the agent has run `tautline secret-status --name <VAR>` and retried through the lane environment; only `secret_source: absent` after that retry is an operator escalation -- `secret_source: indeterminate` means a layer exists and could not be read, so absence was never established and escalating on it is acting on a measurement nothing took.

## Document Context Budget

- Markdown context is routed through configured indexes. Read the adapter, continuity handoff, execution packet, context indexes, and adapter readiness sources first.
- Do not broad-load Markdown trees, all plans, all docs, or archive directories for routine startup context. A bounded Markdown audit must name the question, target files or globs, and an upper bound of 20 Markdown files unless source-of-truth scope or explicit human instruction authorizes more.
- Archived or historical docs are evidence only. They are not current process, scope, execution authority, or next-work authority. Historical paths need the canonical historical header before strict enforcement.
- When creating, completing, moving, or archiving Markdown work artifacts, update the context index before workflow completion. Explicit `documentContext` paths must be project-relative or home-relative (`~`), not absolute workstation paths.
- `context-bootstrap` creates indexes, classifies tracked Markdown candidates, and adds archive headers; it must not move docs automatically. `documentContext.enforcement` defaults to `warn`.
- `context-status --strict` fails for missing indexes, oversized indexes, unclassified tracked Markdown, missing archive headers, or generated adapter drift. `methodology-status --strict --fail-on-drift` temporarily enforces document-context strictness during migration without changing the adapter.
- Strict mode validates filesystem and index state. It is not a runtime read sandbox. Agents still follow generated adapter and `context-continuity` skill loading rules.
- Use the `context-continuity` skill for detailed loading, audit, archive, index-hygiene, handoff, and context-rotation behavior.

## Graphify Navigation

- Graphify support is adapter-backed, optional per project, and enabled by default for adapter-backed lanes.
- When Graphify is enabled and `graphify-out/GRAPH_REPORT.md` or `graphify-out/graph.json` exists, use Graphify report/query/path/explain before broad grep/`rg` for architecture, dependency, call-flow, and codebase navigation questions. This is a token-budget control.
- Use `rg` for exact lexical searches, small known-file checks, when Graphify is missing, or while rebuilding after a failed refresh. Do not use stale Graphify output.
- After every code, docs, schema, route, test, architecture, or other system change, refresh the graph with `graphify update .` before relying on existing Graphify output, committing, or pushing. If any tracked or unignored project file is newer than the latest Graphify artifact, `graphify-out/` is stale and is blocking drift. That refresh is the no-LLM AST rebuild — no API key, backend, or external model — and it is the only Graphify invocation the blocking gate names.
- Semantic enrichment (community labels, `GRAPH_REPORT` prose) is separate and NON-blocking: `GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli`, run only when enrichment is wanted, backend always named. A Graphify invocation that auto-detects its backend is never a gate command in any adapter — a provider can retire the model auto-detect lands on, which kills the documented gate permanently for reasons no lane can see or fix.
- A review finding that a documented blocking gate command does not run is a source defect, never "doc staleness", and may not be downgraded or closed without evidence that the command executes in the lane environment.
- Install Graphify through `tautline graphify-install --target .` when asked. Do not run Graphify assistant project installers such as `graphify claude install` or `graphify codex install` unless the adapter explicitly allows assistant-file ownership and the human operator asks for that exact installer.
- `graphify-out/` is generated local output. It must be ignored and must not be committed. `methodology-status --fail-on-drift` fails if generated Graphify output is tracked or stale.
- Use the `graphify-navigation` skill for detailed installation, freshness, and graph-first navigation behavior.

## Database Migration Collisions

- Parallel lanes that generate database migrations must check for monotonic migration-index collisions before commit, push, merge queue, and after rebasing onto main.
- If migration SQL, snapshot metadata, or migration journal files conflict, do not resolve by choosing one side wholesale. Preserve the already-landed migration, assign this lane the next free migration index, rebuild metadata/journal ordering, and verify with adapter database tests plus the merge-conflict check.
- Use the ops-owned `database-migration-collision` skill for stack-specific migration index, snapshot, journal, and delivery-evidence repair steps.

## Execution Packet Work Loop

- Human operator defines milestone goals and approves the milestone plan.
- Codex leads milestone-level planning and gets Claude review before tactical execution begins.
- The approved plan is converted into `.ai-work/EXECUTION_PACKET.md` in the lane.
- The execution packet must include milestone goal, non-goals, ordered tactical queue, dependencies, safe parallelism, tests/specs required per item, validation gates, review gates, merge gates, drop/defer rules, true-blocker criteria, and completion definition.
- Claude consumes the tactical queue until it is exhausted or a true blocker occurs.
- Claude may push, open PRs, enable merge queue, monitor gates, and continue after gates without asking for arbitrary permission.
- Tactical run evidence is recorded under `.ai-runs/`.

## Memory

- Capture project/product decisions, durable preferences, and factual context to Open Brain when available and non-blocking.
- Do not let memory lookup/capture block code review, preflight, merge, or incident response.
- Tombstone stale memories rather than silently relying on them.
- Never use memory as process authority. Memory is evidence/history only; if it describes a process rule, locate the matching canonical methodology, generated adapter, or methodology skill before acting on it or citing it.
- Never write process or methodology content — rules, gates, caps, review procedures, escape hatches, or workarounds — into Open Brain, Claude memories, local memories, or feedback-memory files. Memory may point at a canonical rule, skill, RCA, or feature-request artifact; it must never define one. When a session produces a process lesson or hits a process dead-end, route it through the `framework-intake` skill: RCA when an existing control failed, feature request when the control is missing.
- A memory-suggested process move is not executable until the matching canonical/adapter/skill rule is located; if none exists, file intake first and treat the situation as blocked-on-missing-control, not memory-authorized.
- RCA artifacts and decision traces must not use memory as the violated rule or expected behavior. If memory is the only source for the claimed rule, classify the incident as a missing/hidden methodology control and propose the canonical/adapter/skill change.

## Context Continuity

- Continuity handoffs preserve lane state across compaction, reset, handoff-for-review, boundaries, and new sessions. When requested/implied, write the configured handoff; chat is not a substitute.
- If handoff persistence fails, name the blocker and do not invent paths. A silent handoff write is incomplete.
- Writing a continuity handoff is not permission to stop. If usable context and authorized work remain, start it after the handoff. If an explicit stop request prevents continuing, report handoff path and exact next action. Context exhaustion is rotation work when compact/restart is available.
- Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping before yielding. Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal. Record position, branch/worktree, decisions, changed files, validation/review, PRs, goal/milestone state, risks, blockers, and exact next action.
- New sessions check the continuity path and resume only after required gates. A continuity handoff is not execution authority until both methodology gates run in order: first `tautline lane-start --target .`, then `tautline methodology-status --target . --fail-on-drift`.
- Required startup gates are mandatory actions, not choices for the human operator. Before both methodology gates pass, do not ask questions, report substantive status, or analyze handoff content; name only a true blocker preventing the methodology CLI.
- If the methodology status gate fails, fix adapter drift, planning path, or scratch-plan issues first. If either methodology gate is skipped or fails, action from handoff content is invalid until clean rerun. If the methodology status gate cannot run because CLI/checkout cannot be found after fallback, name that true blocker. Project-specific gates such as main status/open PR checks run after methodology gates and do not replace them.
- After startup gates, `goal-next` and `milestone-next` ledgers beat vague handoffs. If no goal ledger next action, execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates, inspect adapter/backlog/readiness/recent continuity and plan next work. For T0/T1 work, use a brief inline/packet plan or the minimal adapter-required artifact. Do not ask whether to plan.
- Continuity holds are condition-scoped evidence only. Once resolved, the hold expires and never overrides canonical rules, generated adapter rules, reviewed-work push, iteration review, continuity refresh, journals, or startup gates.

## Session Journals

- Session journals are compact LOCAL evidence for methodology improvement, not process authority, product docs, continuity handoffs, or normal startup context.
- Local-only as of 0.9.0: journals narrate adopter product work and can never be proven safe to publish, so remote publication is disabled and `publish-session-journal`/`publish-pending-session-journals` refuse in every mode (deprecated, removal >=1.0.0).
- The sanitized instrumentation record is the only session evidence that can ever be published (zero product-information capacity): opt in via `instrumentation.enabled` and `publish-instrumentation-record`.
- Journals stay disabled unless the source adapter enables them; previews must never be written into a git worktree that could stage them to a remote, and startup must not fetch any remote archive.

## Automation

- Automations must not use active development lanes as scratch space.
- Readiness/status automations should prefer read-only GitHub API/`gh` calls.
- If a checkout is truly needed, use a dedicated clone, not a shared worktree or active lane.
