# Tautline Plugin Capability Catalog

This reference preserves the detailed capability catalog for maintainers and validation. The public plugin manifest stays concise and marketplace-readable; add detailed behavior here or in focused skills instead of expanding `.codex-plugin/plugin.json`.

## Default Prompts

- Audit this repo's AI process rules.
- Install or sync the portable methodology CLI.
- Run and write the mandatory project adapter bootstrap interview artifact for a new unmanaged repo.
- Auto-rescue dirty stale or non-main methodology checkouts during project-lane startup instead of stranding on old rules.
- Install a portable Claude launcher executable without hand-editing shell startup files.
- Review and adapt declared behavior-spec source materials before writing new customer-facing Gherkin.
- Run behavior-spec integrity checks so inactive acceptance scenarios and harness/app mismatches are treated as skipped validation.
- Inspect adapter technologyStack policy before adding cloud or hosting platforms.
- Use AWS CLI identity checks before treating AWS deployment credentials as blocked.
- Resolve the methodology CLI and start a lane.
- Verify current project/cross-lane status and deep codebase analysis from the fetched latest-code baseline, including ahead remote branches and open PRs, before trusting the local worktree.
- Check whether the current branch still has an active PR before review, commit, or push, and install Git hooks to enforce it.
- Continue from no-work-in-flight or post-merge state without option menus.
- Create and advance a source-of-truth goal plan and lane-local GOAL_RUN ledger for substantial work.
- Emit the next goal name and next action at startup when no active goal ledger exists.
- Emit the next goal short description and copy/paste Claude /goal prompt when no active goal exists or a goal completes.
- Coordinate simultaneous AI lanes through mandatory tracked, committed, and pushed cross-lane contracts, lane boards, and per-lane status files.
- Sync external backlogProvider items such as GitHub Projects cards into reviewed repo plans before execution.
- Generate a backlog-provider migration interview and export only interview-approved existing repo backlog items to GitHub Projects.
- Classify and route product bugs through adapter `bugBacklog` policy so lanes do not ask whether specs, GitHub, Jira, Linear, or another tracker is authoritative when the adapter already resolves it.
- Ask stakeholder clarifying questions on active GitHub Issues, tag the configured stakeholder, and sync answered comments back into repo source-of-truth plans.
- Generate and publish the adapter-enabled customer-facing iteration review for a completed goal when iterationReview is enabled; low context means rotate and resume, not defer.
- Render adapter-required iteration-review recap video/media yourself through the configured renderer and S3/CloudFront path; do not claim agents do not do videos.
- Validate iteration-review and milestone-update canonical delivery keys before posting to Chat so recovery does not create duplicate cards.
- Treat reviewed adapter or plan deployment closeout as agent-owned work instead of handing production deploys to the human operator.
- Publish deploy-ready Google Chat notifications from the deploy/build pipeline after live-site health checks; agent posts are fallback only.
- Enforce full iteration-review delivery: required hosted video, Google Chat post, and iteration-review-delivery-check before goal close-out; do not publish partial customer reviews with a missing recap video.
- Keep iteration-review customer-facing copy short, non-technical, product-value focused, and free of PR/repository links outside the technical appendix.
- Publish an internal text-only Product Milestones Google Chat card when milestoneUpdate is enabled and a milestone completes.
- Refuse goal milestone completion when milestoneUpdate is enabled and the Product Milestones update has not been delivered.
- Publish a quick human-requested note to the adapter-configured product Google Chat space.
- Publish a concise framework release update to Google Chat after bumping VERSION.
- Surface known operator-input goal dependencies before spending plan-review rounds.
- Generate a Claude /goal completion condition from the active goal ledger when available.
- Use context-rotation heartbeats during long Claude /goal runs, invoke compact/restart when thresholds require it, and resume the active goal instead of stopping.
- Treat fatigue, sleep, fresh-eyes, and time-of-day explanations as invalid reasons to defer authorized agent work.
- Set Claude Code auto-compaction to 85 percent through the managed launcher when an override is needed.
- Install Claude auto-compaction env into Claude settings so raw Claude starts inherit the threshold.
- When /compact cannot be invoked from the current agent turn, write continuity and journal evidence, state the exact fresh-session startup action, and do not ask the human operator whether to compact.
- Print a copy/paste Claude goal kickoff prompt for a launcher.
- Advance the milestone run ledger across PR boundaries and start the returned next action.
- Run the review-before-push workflow.
- Run native or Superpowers review on the current assembled diff, including generated/derived artifact freshness, record the Stage 1 defect-class sweep, then run Codex implementation review.
- Finalize and check CLI-recorded Stage 1/Stage 2 implementation review evidence plus the tracked implementation review ledger before push.
- Enforce risk-tiered implementation review round budgets so low-risk work does not churn through repeated Codex rounds.
- Run one Codex plan-review round, then finalize the trusted log without launching Codex again.
- Native/Superpowers review before the first T2/T3 plan-review round.
- Retrieve Codex review findings from a CLI log.
- Check a background or review monitor for verified PID identity, fresh log progress, watchdog state, and stale/hung state.
- Use an independent heartbeat for long background/review work and block backgrounded sleep/until/wait loops before launch.
- Run response guards only during live active goal sessions for passive monitor
  stops, autonomous-loop yields, chat-only RCA-shaped responses, terminal
  continuity omissions, wrong merge-queue signal usage, forbidden opt-in
  language, and false-active status after rejected tools.
- Treat Anthropic/Claude/Codex/GitHub/API provider outages, overloads, 5xx/529s, rate limits, and timeouts as provider-recovery-loop work, not human handoff points.
- Use delivery-summary operator-progress cadence so long work and autonomous yields lead with plain-language outcome/current state and the next action often enough for the human operator to understand status.
- Use final preflight latency for branch-isolated next-iteration planning instead of idle waiting.
- Use PR state, not mergeQueueEntry.estimatedTimeToMerge, for exceptional merge-queue terminal checks.
- Resolve database migration index, snapshot, and journal collisions with the database-migration-collision skill instead of choosing one side wholesale.
- Run plan review, record evidence, and run the plan-finalization precheck.
- Recover from Claude plan-mode scratch-path deadlocks by exiting only to complete source-of-truth plan finalization.
- Frame multi-round plan-review loops with round budget, wall-clock estimate, and plain-language round checkpoints.
- Self-authorize plan-review rounds 3-4 with a recorded `--exception-note` instead of asking the operator, and transfer findings that do not justify another round into implementation review focus.
- Treat refusal past round 4 as unconditional: split into smaller plans unless the bound evidence is clean and current, without option menus.
- Run early-warning smoke only when adapter policy, issue scope, human instruction, or a concrete risk signal asks for it.
- Prepare a lane continuity handoff.
- Refresh the final workflow continuity handoff.
- Check context rotation at PR, milestone, goal, heartbeat, and handoff boundaries and resume the active goal after compaction or restart.
- Prepare, validate, and publish a compact session journal with Graphify freshness evidence.
- Log repo-scoped process boundary events to the human-readable event stream and JSONL audit stream.
- Launch the local HTTP event viewer for repo event logs, verifying existing servers before reusing a port.
- Record and report local per-repo AI token usage with confidence-tagged usage accounting.
- Report implementation benefit, wall-clock estimate, goal/milestone progress, and percent complete in plain language with headings only when useful.
- Start planning when no work is on deck.
- Audit for memory-sourced process.
- Inspect the document context budget.
- Use Graphify report/query/path/explain before broad source scans only when graph output is current; refresh with graphify . --update after every system change before commit/push.
- Analyze a methodology regression RCA.
- Publish, commit, and push a methodology RCA artifact to the dedicated RCA archive branch.
- Submit a Tautline feature request through the framework-intake skill, dedicated feature-request intake artifact, and archive branch.
- Publish RCA and session-journal archives through isolated archive branches without dirtying the active methodology release checkout.
- Create an execution packet for an approved milestone.

## Detailed Capability Narrative

This catalog is grouped by operator workflow so maintainers can inspect coverage
without expanding the public plugin manifest. Individual skills remain the
procedural source for exact command order and failure handling.

### Startup And Adapter Lifecycle

- portable CLI bootstrap, installable Claude launchers, PATH-safe startup gates,
  adapter-backed lane startup, drift checks, dirty-checkout auto-rescue, and
  non-main checkout guards.
- Project bootstrap with mandatory adapter interview, bootstrap evidence,
  source-adapter hashing, and generated adapter validation.
- latest-code baseline verification across fetched remote base, ahead branches,
  and open PRs before cross-lane progress answers or deep codebase analysis.
- Stable/experimental release tracks, framework pins, deterministic migration
  reports, and public-release checks for private adapter removal.

### Planning, Goals, Backlog, And Coordination

- Goal orchestration with source-of-truth goal plans, lane-local goal ledgers,
  milestone continuation ledgers, Claude /goal guidance, multi-session Claude
  /goal boundaries, operator-dependency surfacing, and copy/paste launcher
  kickoff prompts.
- Execution packets, startup planning, next-goal summaries, and continuation
  after post-merge or no-work-in-flight boundaries.
- Cross-lane coordination through tracked contracts, lane boards, and per-lane
  status files for simultaneous AI lanes.
- Provider-backed backlog workflows with GitHub Projects sync/export/migration
  interviews, real repository issue exports by default, stakeholder question
  intake, adapter-aware bug triage, board-order work selection, and board item
  status maintenance.

### Review, Gates, And Quality Control

- Review-before-push orchestration, Codex review finding retrieval, risk-tiered
  implementation review round budgets, and adapter-backed Codex fast-mode
  enforcement with project opt-out.
- One native/Superpowers self-check before T2/T3 plan-review R1, and
  Stage 1 native review before T2/T3 Stage 2 implementation/code-review rounds.
- CLI-recorded and classified Stage 1/Stage 2 implementation review evidence,
  Stage 1 defect-class sweep manifests before Codex implementation review,
  tracked implementation review ledgers, and pre-push review-evidence checks.
- Plan-finalization precheck, adapter-declared review exemptions, plan-only
  Codex review wrappers, finalize-plan-review evidence binding without duplicate
  Codex runs, monitored plan-review convergence loops, and the plan-review
  convergence ladder: a two-round target, self-authorized rounds 3-4 with a
  recorded exception note, focus transfer for findings that do not justify
  another round, and an unconditional refusal past the hard cap of four rounds
  whose remedy follows the bound evidence (finalize it only when it is clean and
  current; otherwise the split into smaller plans is mandatory).
- Risk-triggered early-warning smoke, preflight latency planning, merge queue handling with
  PR-state terminal checks, and explicit protection against
  `mergeQueueEntry.estimatedTimeToMerge` as a progress signal.

### Delivery, Visibility, And Stakeholder Updates

- adapter-enabled customer-facing iteration reviews with hosted pages/media,
  adapter-approved recap music, Google Chat delivery after merge, full
  iteration-review delivery checks, and customer-facing copy-quality guards.
- Internal text-only milestone updates, quick product-space Google Chat notes
  through adapter-configured webhooks, and concise framework release updates
  to Google Chat after VERSION bumps.
- Pipeline-backed deploy-ready Google Chat notifications after live-site health
  checks, with agent-session posts treated as manual fallback only.
- Delivery summaries with fixed plain-language boundary headings and progress
  narrative, milestone progress visibility, and operator-progress cadence for
  long work and autonomous yields.

### Runtime Continuity And Operational Resilience

- context rotation at PR/milestone/goal boundaries, goal heartbeat checks for
  long /goal runs, non-optional compact/restart handling, and automatic
  continuity handoffs.
- Session journals with Graphify freshness evidence, document context budgeting,
  adapter-backed Graphify navigation, generated Graphify output excluded from
  git, and local token/cost usage accounting.
- background monitoring with liveness/stale checks, independent heartbeats,
  fake-monitor loop bans, and Claude Bash hook blocking for unsafe background
  commands.
- Provider recovery loops for Anthropic, Claude, Codex, GitHub, API outages,
  5xx/529s, rate limits, and timeouts instead of human handoff points.
- Repo-scoped human/JSONL event logs and an HTTP event viewer for live operator
  tailing and audit drill-down.

### Governance, Safety, And Specialized Skills

- Rules audits, memory-as-evidence-only enforcement, verified human
  instructions, methodology regression RCA analysis, branch-published RCA
  artifacts, and branch-published framework feature-request intake.
- Public-release readiness, private adapter migration, repo-local adapter
  support, stale public-doc detection, release migration reports, and public
  contract status classification.
- Database migration collision repair for parallel-lane migration indexes,
  snapshots, and journals.
- adapter-backed behavior-spec source materials and behavior-spec integrity
  checks so reviewed business Gherkin is imported, adapted, executable against
  the changed app, and not silently parked behind inactive tags.
- adapter-backed technical stack defaults with AWS-first cloud guidance, AWS
  CLI deploy credential conventions, and agent-owned reviewed deploy closeout.
