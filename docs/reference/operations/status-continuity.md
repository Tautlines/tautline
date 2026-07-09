# Status And Continuity

This reference owns detailed status truth, operator-progress reporting, readiness
monitoring, and delivery-summary policy. Continuity handoff details live in
[Context Continuity](context-continuity.md). The operating manual keeps short
navigation entries for these workflows.

## Current Status Truth

When the human operator asks for current project status, whether something is complete, what is next, or work that may have happened in another lane, the latest-code baseline is the first evidence source. Run:

```bash
minervit-methodology latest-code-status --target . --write
```

The command fetches the adapter-configured remote base (`origin/main` by default), writes `.ai-work/LATEST_CODE_BASELINE.json`, reports local-vs-base divergence, lists remote branches ahead of base, and lists open PRs when GitHub CLI access is available. A branch that is ahead of `origin/main` may be the deployed or stakeholder-visible surface, so status answers must not stop at local HEAD or remote main.

For a narrow remote-main path check, the older helper remains available:

```bash
minervit-methodology remote-main-status --target . --path backlog/_index.md --path docs/product/backlog/status.md
```

Answer from fetched `origin/main`, GitHub PR/check evidence, ahead remote-branch evidence, deploy/build identity, and source-of-truth files on the relevant ref before trusting the local worktree. If the local lane is behind, dirty, detached, on a PR branch, or another remote branch is ahead and may be deployed/stakeholder-visible, state that plainly. Use `git show origin/main:<path>`, `git show <remote-branch>:<path>`, or `gh` for current artifacts. Pull/rebase local only when preparing to work; a read-only status answer should fetch and inspect remote without mutating unrelated lane state.

Deep codebase analysis, architecture review, multi-angle analysis, planning, implementation, review, and tactical subagent dispatch are work-prep unless the human explicitly asks for read-only historical/local-lane analysis. Do not spend an analysis budget on stale code. Establish the latest-code baseline first, then analyze.

The latest-code guard must never wedge its own recovery path. `latest-code-status
--write` records remote git state only, so it may fall back to the generated
lane adapter when canonical source-adapter checks fail because of
`sourceAdapterSha256` mismatch, a stale or transient `minervit-local-rescue/*`
rescue-ref hint, or a relocated source adapter. In that case it writes the
baseline, surfaces `latest_code_adapter_drift`, and leaves `render-adapters` as
the canonical drift recovery. Adapter-source drift is a warning to repair after
the baseline exists, not an unrecoverable lock-out.

When the latest-code baseline is stale, the hook refreshes it in-band using the
same fetch it would otherwise demand. If refresh succeeds, the tool proceeds
and surfaces relevant ahead-branch/open-PR or soft-offline heads-up output. It
blocks only when the refresh genuinely cannot self-heal, such as offline with
no cached base ref, and it must still allow the recovery command forms agents
actually use: `cd <lane>; minervit-methodology latest-code-status --target .
--write`, read-only pagers around that command, the installed
`$HOME/.config/minervit/methodology.env` shim, and the trusted
`$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology` launcher.

## Plain-Language Status

Status updates must be understandable without decoding agent, git, CI, or monitor jargon. The agent should explain the meaning first and include technical terms only when they add useful precision.

Rules:

- Say what is happening, why it matters, and what concrete action is underway or due next.
- Translate internal terms such as HEAD, trailer, BREAK-GLASS, R1/R2/R3, cap round, verdict, monitor event, full multi-port env, green/red, queue, and gate.
- Do not say `will report verdict on monitor event` or equivalent monitor-internal wording.
- For monitor status, say what artifact is being polled, when the next check is due, and what failure would interrupt the work.
- Raw command output may be included when useful, but summarize the meaning first.
- Operator visibility is required during work, not only at delivery. Emit a plain-language progress update after startup gates, before any review/preflight/deploy/test sequence expected to exceed 2 minutes, at every review round or monitor poll, at every PR/milestone/goal/context-rotation boundary, and at least every 5 minutes of wall-clock time during foreground or autonomous work whenever the host gives the agent a chance to speak.
- Operator updates lead with the plain-language outcome or current state, then state the next action. Add concise technical details only when they help the operator understand risk or progress. Headings and labels are optional readability tools, not a required schema.
- Autonomous yields and heartbeat handoffs must still name the real state, true blocker, and concrete retry/poll/next action; do not send empty or label-only heartbeats.
- Event logs, session journals, and continuity files support audit and restart, but they do not replace chat-visible operator updates.

Bad:

```text
Branch HEAD is the BREAK-GLASS trailer commit. Preflight running with full multi-port env. Will report verdict on monitor event.
```

Good:

```text
The branch is on the emergency-approval commit. The full local test suite is running with this lane's isolated ports, so it should not collide with another lane. I am checking the result and will interrupt if it fails.
```

## Verified Human Instructions

When giving the human operator instructions for an external system, verify the current process from authoritative sources in the same turn before giving steps.

This rule applies especially to security settings, repository or organization administration, cloud consoles, identity providers, billing, production services, third-party dashboards, and installation/setup flows controlled by an external vendor.

Rules:

- Use official vendor documentation, official CLI/API help, or the live product UI when available.
- For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence over memory, blog posts, or stale examples.
- Include direct links to the authoritative source pages used. Links must point to the specific relevant instructions, not a generic documentation home page.
- State prerequisites that affect the instructions, such as required role, plan, organization ownership, feature availability, repository scope, or whether the setting is personal, organization, enterprise, or repository-level.
- If the verified instructions vary by UI version, plan, role, or account type, name the variants and tell the human operator which branch applies or what fact would select the branch.
- Do not invent UI labels, menu paths, setting names, screenshots, or links from memory.
- If current authoritative verification is unavailable, say the instructions are unverified, give only safe high-level guidance, and name the exact source needed before asking the human operator to act.

Before sending human-action instructions, run this check: would a careful human operator be able to complete the change the first time using these steps and links? If not, verify further or narrow the instruction.

## Early-Warning Smoke

Run expensive smoke or main-health checks early only when a trigger justifies the extra work.

Rules:

- Early-warning smoke is no longer a standing gate for every tactical iteration. Routine startup/main health, pre-push preflight, and CI remain the default quality gates.
- Run the adapter's distinct `earlyWarningSmoke` command only when the adapter, source-of-truth plan, issue, human operator, or a concrete risk signal asks for it. If the adapter does not define one, or it matches `mainStatus`, use the main-status gate as the baseline check instead of launching a duplicate background monitor.
- Do not launch background smoke monitors merely because a new plan/spec write, edit, PR, rebase, or iteration boundary began.
- Before starting a new early-warning monitor, inspect the latest early-warning `.meta.json` and `.pid` files under the lane runs directory. Compare command plus `cwd` as the target, verify the PID is live, and poll the existing monitor if the same command is already running for the same target. If a `.pid` exists without metadata, check PID liveness and the log once before deciding whether to start a replacement.
- Continue planning and implementation while the early-warning smoke runs. Poll the log/process/check at least every 10 minutes unless the adapter is stricter, and record each poll as `timestamp | log path or command | observed state | next poll due`.
- Before commit, push, or merge, actively poll any running early-warning monitor in the same turn. Proceed only when the poll observes terminal success or a current healthy in-progress state; unknown, stale, failing, wrong-target, or resource-contention states halt the current item.
- Assume success unless the monitor reports failure, timeout, stale output, wrong target, or resource contention. Default stale threshold is one missed poll without a live process/check state or two consecutive polls without log/check progress.
- Early-warning smoke is not the final branch gate. Required item tests, fast preflight, full preflight, review gates, and merge gates still run at their configured points.
- Early-warning smoke failure interrupts as P0: halt the current item's commit, push, merge, and additional feature work until the failure is investigated or proven unrelated with named evidence such as unchanged-main reproduction, external service degradation, or logs showing the failure predates the branch. Passing early-warning smoke should reduce end-of-iteration waiting, not create a new pause point.
- Do not wait for a clean queued PR to land just to create a later tactical-iteration boundary. If the next authorized work does not depend on the merged main commit, continue.
- Post-merge smoke or deploy checks are not watched by default after a clean queued PR. Do not delay the queued-delivery summary waiting for post-merge success unless a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.
- In a normal successful iteration, the last human-facing action for that PR is the queued-delivery summary, then the agent continues the next authorized work.

## Final Preflight Planning Window

Final preflight is required before push/queue, but its wall-clock time is not idle time.

Rules:

- Once the current PR tip is frozen, review is clean, and final preflight is running with monitor/log/PID evidence, use the wait for branch-isolated next-iteration planning or active polling.
- Safe planning includes reading the milestone ledger, execution packet, backlog/indexes, and source-of-truth plan candidates; drafting or updating the next plan only in a separate worktree/branch or ignored lane-local scratch under `.ai-work/` that cannot alter the current PR diff; and running plan review only when it does not contend for the same local test resources.
- Do not edit the current PR diff, amend the current commit, or start implementation for the next item while final preflight is proving that current tip.
- If final preflight fails, interrupt next-iteration planning and repair the current PR. If final preflight passes, push/queue the current PR before continuing implementation on the next item.
- If final preflight hangs, goes stale, times out, loses PID/log identity, or shows resource contention, recover it under Background Work rules before push. If no branch-isolated planning or other parallel-safe task exists during final preflight, actively poll the preflight artifact at the documented cadence. A status-only update that says preflight is running or that the agent will push when it finishes is a passive monitor stop.

Example for an adapter-backed lane:

```bash
minervit-methodology background-run \
  --log ".ai-runs/early-warning-smoke-$(date -u +%Y%m%dT%H%M%SZ).log" \
  -- bash -lc '<earlyWarningSmoke command>'
```

If the early-warning command touches local services and appears in `localResourceIsolation.isolatedCommands`, run the same command through `lane-run` inside `background-run` so it uses the lane's isolated ports and Compose project name.

## Milestone Progress Visibility

Before the first code edit, implementation command, PR worktree creation, or tactical subagent dispatch for a session or planned item, the agent must state the benefit of the work in plain English and give a realistic wall-clock estimate or range for the current session. Ground the estimate in visible scope, expected gate/review time, prior similar runs, or stated uncertainty. This is an operating forecast, not a promise.

Do not repeat the benefit and estimate before every small edit once the current session or item has been framed. Refresh it when switching to materially different work. Materially different means a different goal, milestone, source-of-truth plan, execution-packet item, PR branch/worktree, deployment target, or user-visible capability.

After work is delivered or advanced, the executive summary must state progress against the current goal and milestone in plain English and estimate the percent of planned work complete. Ground goal progress in `.ai-work/GOAL_RUN.json` and the source-of-truth goal plan when a goal exists; ground milestone progress in the source-of-truth plan, execution packet, backlog checklist, or adapter-declared milestone scope. Use rounded estimates such as `about 40%`; do not invent false precision. If the plan is not decomposed enough for a meaningful estimate, update the planning artifact or execution packet before treating the summary as complete. If that write is blocked, state `percent unknown`, name the exact blocker, and make the artifact update the next action.

## Delivery Summaries

When work is delivered for human review, the completion summary must begin with an executive summary before the technical detail. Any message that reports work landed or shipped is a delivery summary, even if it is emitted as a monitor event, queue progress update, batch status update, or brief status line.

Work-landed triggers include a PR queued after clean local gates and review, a PR merged, a batch item merged, a deployment completed, a direct-to-main change committed, a release published, or a milestone/work packet completed.

Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session.

Boundary summaries for delivery, PR, milestone, goal, session, and handoff-for-review events must lead with the plain-language outcome and next action. Use headings or labels only when they improve readability; they are not a required schema.

A complete boundary summary states what happened, why it matters, what capability was unlocked, current goal/milestone/PR/process position, grounded percent complete or `percent unknown` with blocker, whether planned work is ready, the recommended next action, and supporting technical detail needed to understand status or risk.

When local tests, preflight, and review are complete and a PR has been pushed or queued for merge, summarize immediately. State that the work is validated locally and queued or not yet merged, record the PR reference, and continue with the next authorized work. Do not wait for GitHub Actions, merge queue, deploy, or post-merge smoke to finish. A clean queued PR leaves active attention; the next session's startup gates catch main health, failed or blocked open PRs, and merge conflicts.

The executive summary must answer:

- What was delivered, in plain English.
- Why it matters.
- Where the work stands in the overall process, using understandable lifecycle language such as planning, implementation, local validation, review, PR open, merge queued, merged, or follow-up ready.
- Progress against the current goal and milestone, including the estimated percent of planned work complete.
- Whether additional planned work is ready for development.
- The recommended next work item.

The executive summary must include a grounded progress narrative. Call out what capability was unlocked for users, admins, operators, or delivery velocity. Significant milestones should sound consequential and worth noticing without obscuring current status, validation state, or risk. For example, an environment milestone should not be buried as "Terraform smoke passed"; it should explain that the team can now create, test, and tear down an isolated validation environment repeatably.

The milestone percent complete must be grounded in the source-of-truth plan, execution packet, backlog checklist, or adapter-declared milestone scope. If the plan is not decomposed enough for a meaningful estimate, update the planning artifact or execution packet before treating the summary as complete, or state the exact blocker that prevents the update.

For batch delivery updates, the executive summary must include the batch progress count, what changed in plain English across landed items, what remains in flight or blocked, whether the remaining planned work is ready, and the recommended next action.

A technical-only merge report is incomplete. Do not report only PR numbers, branch names, invariant names, check names, or terse item labels when a human-facing overview is required.

Do not say follow-up work is ready for development unless the next item has enough source-of-truth context, clear dependencies, acceptance criteria or execution-packet coverage, and no known true blocker. If it is not ready, name the missing decision, artifact, dependency, or gate.

Keep the existing technical delivery detail after the executive summary: files changed, behavior changed, tests and gates run, whether early-warning smoke was started and its current state or why it was covered/skipped, queued PR status or exceptional post-merge/deploy monitor status, PR/branch/commit references, risks, follow-ups, and skipped validation. The recommendation is not a permission question; state the recommended next step and continue if the framework already authorizes continuing.

Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping before yielding or ending the turn. The summary is incomplete until the handoff exists or an exact filesystem persistence blocker is named.

The refreshed handoff must include the executive summary, process position, validation/review state, active or queued PRs, open risks, and either the exact next action or the checks proving no authorized next work remains.

Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal. If the agent continues into the next authorized work after refreshing the handoff, it must refresh the handoff again at the next workflow summary or before any later yield/end-turn.

Do not turn a session summary, milestone summary, or continuity handoff into a stop menu. If the summary names an authorized next action and no true blocker exists, start that action in the same turn. Do not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session`. If an explicit human stop request prevents continuing, write the handoff and state the next action without opt-in language. Context exhaustion is a rotation trigger, not a stop reason, when compact/restart is available.

A delivery summary is not a license to stop when authorized work remains. Do not use "clean checkpoint", "significant progress", "obvious continuation path", or "next turn" to defer work that is already authorized by the adapter, execution packet, or approved milestone.

A queued-delivery summary is incomplete unless it ends with either `Next work already underway: <specific action/artifact>` followed by starting that action in the same turn, or `No authorized next work remains` with the checks performed across the execution packet, backlog/source-of-truth readiness, continuity handoff, open PR list, and defer/follow-up capture. Claims such as "no more P1 followups" or "nothing else open" are not enough to stop.

`No work-in-flight` after a prior PR landed is not a human-routing prompt. The agent should complete safe branch/worktree cleanup, sync main, run `lane-start`, `methodology-status --fail-on-drift`, and adapter startup/status gates, handle generated adapter drift as adapter hygiene, then start the highest-priority source-of-truth backlog item or its required PR-level planning flow. Commit adapter drift only when the project tracks generated adapter files and the diff is solely methodology-generated; keep it separate from feature work and never commit lane-local state or unrelated product changes. It must not ask the human operator to choose cleanup, next backlog item, or something else.

Any direction-asking question after the previous PR landed and no work is in flight is a stop-menu violation, even if it avoids the exact words `Where would you like to go` or `No work-in-flight`.

## Readiness Automation

A daily readiness automation should not use an active development lane as scratch space.

Correct design:

- Run from this framework repo.
- Use GitHub API/`gh` only.
- Include the reviewed SHA in its report.
- Inspect readiness files at that SHA.
- Avoid `git fetch`.
- Avoid active development lane cwd.

Current starting command:

```bash
bin/minervit-methodology readiness-review --project <lane_path>/.tautline/adapter.json
```

If a future automation truly needs a checkout, use a dedicated clone. Do not use a shared worktree, because worktrees share Git refs and fetch state.
