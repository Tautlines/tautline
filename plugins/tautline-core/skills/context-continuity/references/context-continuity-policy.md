# Context Continuity Policy Reference

This reference keeps detailed handoff, resume, startup-gate, context-rotation,
goal/milestone, planning-on-resume, Markdown context-loading, bounded-audit,
archive, and index-hygiene policy behind the concise `context-continuity` skill
entrypoint. It preserves existing behavior while making routine continuity and
context-budget guidance easier to load.

Use this skill when the human operator asks to prepare for continuity, a
continuity prompt, compacting, context reset, handoff, or a new session. Also
use it as mandatory final housekeeping after every workflow completion, delivery
summary, session summary, milestone summary, queued-delivery summary,
handoff-for-review, or completed execution packet.

Use this skill when starting work in a lane, reading project docs, creating or
completing Markdown artifacts, classifying old docs, investigating context
bloat, bootstrapping document indexes, or validating strict document-context
state.

The goal is to keep normal startup and analysis context small without losing
source-of-truth work. Current action should come from configured indexes and
active lane artifacts, not from broad scans of every plan, archive, or Markdown
tree in a repository.

Control Markdown context loading by reading configured indexes first.

## Document Context Budget

Read only the startup set unless the task names a narrower artifact:

- generated `CLAUDE.md` / `AGENTS.md`
- `.minervit-ai-delivery.json`
- `.ai-continuity/NEXT_SESSION.md` when present
- `.ai-work/EXECUTION_PACKET.md` when present
- configured context indexes
- adapter readiness sources

Do not broad-load Markdown trees, scan all plans, or read every doc for routine
context. Do not load archive directories during startup. If the needed next
artifact is not obvious, read the configured index first and choose named files
from it.

`documentContext.enforcement` defaults to `warn`. Strict mode is enabled per
project only after indexes, classification, and archive headers are clean.
Warnings are still operational evidence: follow them before expanding context.

## Bounded Markdown Audits

A Markdown audit is bounded only when it states:

- the specific question being answered
- the target files or globs
- an upper bound of 20 Markdown files

If more than 20 Markdown files are needed, use a source-of-truth plan or
explicit human instruction that authorizes the larger read. Otherwise, read the
index first and select the specific named files needed to answer the audit
question.

Bounded audits should report what was read, why it was enough, and what remains
unknown. A search result alone is not authority; it is a routing signal to the
current index, adapter, execution packet, continuity handoff, or source plan.

## Archives

Archived or historical docs are evidence only. They are not current process,
scope, execution authority, or next-work authority.

Strict archive docs must include this sentence near the top:

```text
Historical evidence only. Not current process, scope, or execution authority. Start from <index path>.
```

Use archived docs only to verify history, reconstruct decisions, or support RCA
evidence. Current action must come from the active adapter, execution packet,
continuity handoff, source-of-truth plan, or current index.

Archive paths should be reachable from an index section named `Historical
Evidence Only`, not mixed with current plans. If an old doc lacks the historical
header, strict context status must flag it until the header is added or the doc
is moved/classified correctly.

## Index Hygiene

When creating, completing, moving, or archiving Markdown work artifacts, update
the relevant context index before workflow completion.

Indexes should keep current context small:

- `Read First` contains stable routing docs only.
- `Active Work` contains current in-flight artifacts.
- `Ready Next` contains approved ready work.
- `Historical Evidence Only` points to archive paths or specific historical
  docs.
- `Do Not Load Routinely` names ignored paths.
- `Needs Classification` must be empty before strict enforcement.

Run:

```bash
tautline context-status --target .
```

Use `--strict` during migration validation or when the adapter enables strict
enforcement.

Strict mode validates filesystem and index state. It does not observe every file
read, so the agent must still follow this skill and the generated adapter
loading rules.

`context-bootstrap` creates indexes, classifies tracked Markdown candidates, and
adds archive headers. It must not move docs automatically. `context-status
--strict` fails for missing indexes, oversized indexes, unclassified tracked
Markdown, missing archive headers, or generated adapter drift.

## Document Completion Boundary

A workflow that creates, completes, moves, or archives Markdown artifacts is not
finished until the relevant context index reflects the new state. Keep the
active index useful for the next lane: current work belongs in `Active Work`,
approved future work belongs in `Ready Next`, and old evidence belongs in
`Historical Evidence Only` or `Do Not Load Routinely`.

## Prepare A Handoff

1. Write the handoff to the project adapter's continuity path.
2. Prefer the CLI:

```bash
tautline prepare-continuity --project <adapter.json> --target <lane> --stdin
```

3. Include:
   - executive summary from the latest delivery or workflow summary when available
   - current state
   - process position
   - active branch and worktree status
   - decisions made
   - files changed
   - validation results
   - review state
   - active or queued PRs
   - goal run path, current milestone, percent complete, and `goal-next` output when `.ai-work/GOAL_RUN.json` exists
   - milestone run path, current item, percent complete, and `milestone-next` output when `.ai-work/MILESTONE_RUN.json` exists
   - open risks or blockers
   - exact next action
   - checks proving no authorized next work remains, if no next action exists
   - required startup gates, including `tautline lane-start --target .`
   - `tautline methodology-status --target . --fail-on-drift` as a required startup gate
   - a statement that ad hoc `git status`, `git log`, CI checks, or local tests do not replace the methodology status gate
   - a portable fallback using `$HOME/.config/minervit/methodology.env` or `$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology` when `minervit-methodology` is missing from `PATH` or exits 127/command-not-found
   - a statement that a missing `PATH` entry is not a failed methodology gate, not a reason to ask for a person-specific path, and the same gate must be rerun with the resolved portable CLI
4. If continuity is requested, implied by compaction/session handoff, or needed because context is running out, write the file before replying with continuity content or continuing, then briefly report the path.
5. If the request uses chat-prompt wording, honor the continuity intent and write the file anyway.
6. Continuity is implied by wording such as compact, context, continuity, handoff, new session, pick up later, or by a tool/system event indicating compaction, context exhaustion, or session transition.
7. Context exhaustion means a system/tool compaction event, explicit low-context warning, user compaction request, or the agent recognizing it can no longer preserve enough task state for a safe next session. When uncertain, write the handoff.
8. Chat-prompt wording includes requests like `give me a prompt`, `continuity prompt`, `copy/paste`, `new session to pick up`, or `summarize where we are`.
9. A silent handoff write is incomplete.
10. Never offer the filesystem handoff as an optional additional action.
11. If a chat continuity response was already produced, write the file in the same turn before doing anything else.
12. Do not ask whether to write the handoff. Only skip the file if the human operator explicitly says not to write it.
13. Do not ask the human operator to copy/paste a continuity prompt.
14. The lane-local handoff file is the primary artifact. A chat response is not an acceptable substitute when the configured filesystem path is writable.
15. Do not emit a copy-paste continuity prompt as the primary response. When the file exists, the default reply is the path plus a brief status; do not paste full handoff content unless the human operator explicitly asks for the contents of the existing file.
16. The continuity request is incomplete until the configured handoff file exists or an exact filesystem persistence blocker is named.
17. Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping before yielding or ending the turn, even when the human operator did not explicitly ask for continuity.
18. A delivery or workflow summary is incomplete until the handoff exists or an exact filesystem persistence blocker is named.
19. Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal. If continuing into the next authorized work after refreshing the handoff, refresh the handoff again at the next workflow summary or before any later yield/end-turn.
20. Keep the handoff lane-local and ignored by Git unless the adapter says otherwise.
21. Writing a handoff is not permission to stop. If the current session still has usable context and the next action is authorized, start that action after writing the handoff.
22. Do not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session`. If an explicit human stop request prevents continuing, report the handoff path and exact next action without opt-in language. Context exhaustion must match the signals in item 7, but it is not a terminal stop when compact/restart is available; it triggers context rotation and resumption of the same goal. If compact/restart is not invokable from the current agent turn, write the handoff/local evidence and state the exact fresh-session startup action without asking whether to compact or continue.
23. Context rotation is routine maintenance for autonomous goal work. Managed Claude startup sets `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in both the launcher env and Claude's durable settings file, and methodology status fails inside Claude when either live env or durable settings are missing/drifted. At PR queued/completed, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat boundaries, if visible host context is at or above the adapter soft threshold, refresh the handoff, update goal/milestone ledgers, handle adapter-required local evidence, compact or restart when available, and resume the active goal without asking.
24. Default context rotation thresholds are soft `60%`, hard `75%`, and heartbeat `15m` unless the project adapter overrides `contextRotation`. At or above the hard threshold, rotate at the next safe boundary unless a true blocker prevents the handoff.
25. For Claude Code, use `/compact` or the strongest host-supported compact/restart path at mandatory rotation points when the agent turn can invoke it directly; do not narrate context exhaustion as a final blocker.
26. If the host cannot literally clear or restart the session from the current turn, the fallback is the filesystem handoff plus the exact next startup action. Lack of a host reset command is not permission to skip handoff, ask the human operator to run `/compact`, say `/compact me`, claim the session reached its productive limit, or ask whether to continue.
27. Do not combine context rotation with a credential/access issue into an option menu. Run the adapter credential/origin checks first; if access is truly missing, name the one exact blocker and preserve/resume state through the handoff path. Never include an unverified shipping option in a continuity or context-rotation message.

## If Handoff Tools Are Rejected

- If a read/search/prep tool call is rejected while preparing a handoff, continue from current context or use a different named source.
- If the filesystem write is rejected, do not ask whether to write it. Try one alternate safe filesystem write method if available.
- The alternate write must target the same configured handoff path. An alternate safe method is a single different mechanism, such as direct file write if the methodology CLI failed or the CLI if direct write failed. Do not invent a tracked path, remote note, or second fallback location.
- If no filesystem write is allowed, provide the handoff content in chat and state the exact blocker preventing lane-local persistence.
- If only one filesystem write method is available, or no alternate write method is obvious, do not loop. Provide the handoff in chat and name the exact persistence blocker.

## Resume From A Handoff

At session start, check the configured continuity path before starting new work. If present:

1. Read it.
2. Resolve the methodology CLI: use `minervit-methodology` from `PATH`, or source `$HOME/.config/minervit/methodology.env` and use `$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology` if `PATH` is missing it or the command exits 127/command-not-found.
3. A missing `PATH` entry is not a failed methodology gate, not permission to substitute ad hoc checks, and not a reason to ask for a person-specific checkout path; rerun the same gate with the resolved portable CLI.
4. If neither the CLI nor portable checkout fallback can be found, name that true blocker instead of substituting ad hoc checks.
5. Run `tautline lane-start --target .`, or the resolved portable CLI equivalent.
6. Run `tautline methodology-status --target . --fail-on-drift`, or the resolved portable CLI equivalent.
7. If the status gate fails, fix the reported adapter drift, planning path issue, or relevant scratch-plan issue before continuing from the handoff.
8. If either methodology gate is skipped or fails, stop before using Handoff Content, resolve the gate failure, rerun the gate, and proceed only after it exits clean. If it cannot be resolved safely, name the exact true blocker.
9. Do not ask clarifying questions, report substantive status, or start analysis from Handoff Content before the methodology gates pass. The only exception is naming a true blocker that prevents running the methodology CLI.
10. Do not ask whether to run required startup gates, whether to `kick those off`, or whether to proceed with a named path after the gates. Run the gates immediately and continue with the handoff `Next Action` unless a true blocker occurs.
11. Do not treat the handoff content as execution authority until the methodology status gate exits clean.
12. Continuity holds are condition-scoped evidence only. Once the named condition is resolved, the hold expires and never overrides canonical rules or adapter invariants such as reviewed-work push, required iteration review, continuity refresh, or journal handling.
13. Run project-specific startup gates such as main status and open PR checks after both methodology gates are clean.
14. Resume from its `Next Action`.
15. If `.ai-work/GOAL_RUN.json` exists, run `tautline goal-next --target .` after startup gates and start the printed `next_action` before milestone work unless a true blocker occurs. The goal ledger wins over a milestone-only or vague handoff summary at goal/milestone boundaries.
16. If `.ai-work/MILESTONE_RUN.json` exists, run `tautline milestone-next --target .` after goal state and startup gates, then start the printed `next_action` unless a true blocker occurs. The milestone ledger wins over a vague handoff summary at PR boundaries.
17. If there is pending adapter-required local evidence after startup gates, publish it through the owning ops skill. If publishing fails, record the exact blocker in the next continuity handoff instead of silently ignoring it.
18. If no goal ledger next action, execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates, inspect the adapter, backlog/source-of-truth planning path, readiness markers, and latest delivery or continuity handoff. Also check milestone ledger state when present. For substantial/multi-milestone T2/T3 work, create or update the source-of-truth goal plan first, run Codex plan review, pass plan-finalization precheck, and verify explicit or standing approval before implementation. For T0/T1 work, use brief inline/packet planning or the minimal adapter-required artifact, then continue to implementation gates. Do not ask whether to plan.
19. Archive or replace the handoff only when a newer handoff is prepared.
20. After a context rotation, resume through startup gates, pending journal publication, `goal-condition` or `goal-next`, then `milestone-next`. Do not ask whether to resume the active goal.

## Handoff Quality Bar

The next session should be able to continue without asking the human operator what happened. If the next action is ambiguous, the handoff is incomplete.
