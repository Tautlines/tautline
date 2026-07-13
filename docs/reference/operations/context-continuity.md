# Context Continuity

This reference owns lane-local continuity handoff behavior, fresh-session
startup requirements, and restart-safe next-action rules. Status reporting stays
in [Status And Continuity](status-continuity.md).

## Context Continuity

The framework removes the manual copy/paste continuity workflow. When the human operator asks to prepare continuity, compact, hand off, a continuity prompt, or start a new session, the agent should write a lane-local handoff file. The lane-local handoff file is the primary artifact; a chat response is not an acceptable substitute when the configured filesystem path is writable.

If the request uses chat-prompt wording, treat it as a request for the continuity artifact. Chat-prompt wording includes requests like `give me a prompt`, `continuity prompt`, `copy/paste`, `new session to pick up`, or `summarize where we are`. Continuity is implied by wording such as compact, context, continuity, handoff, new session, pick up later, or by a tool/system event indicating compaction, context exhaustion, or session transition. Context running out is signaled by a system/tool compaction event, explicit low-context warning, user compaction request, or the agent recognizing it can no longer preserve enough task state for a safe next session. When uncertain, write the handoff. Write the file before replying with continuity content or continuing, then briefly report the path. A silent handoff write is incomplete. Do not offer the filesystem handoff as an optional additional action. Writing a handoff is not permission to stop; if the current session still has usable context and the next action is authorized, start it after writing the handoff. Do not emit a copy-paste continuity prompt as the primary response. When the file exists, the default reply is the path plus a brief status; do not paste full handoff content unless the human operator explicitly asks for the contents of the existing file. If a chat continuity response was already produced, write the file in the same turn before doing anything else.

Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping before yielding or ending the turn, even when the human operator did not explicitly ask for continuity.

Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal. If the agent continues into the next authorized work after refreshing the handoff, it must refresh the handoff again at the next workflow summary or before any later yield/end-turn.

If the configured handoff write is rejected, try one alternate safe write method for the same configured path. An alternate safe method is a single different mechanism, such as direct file write if the methodology CLI failed or the CLI if direct write failed. Do not invent a tracked path, remote note, or second fallback location. If all filesystem writes are rejected, only one filesystem write method is available and rejected, or no alternate write method is obvious, provide the handoff in chat and name the exact persistence blocker.

Default configured path:

```text
.ai-continuity/NEXT_SESSION.md
```

Prepare a handoff:

```bash
bin/tautline prepare-continuity \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --stdin
```

The handoff content is read from stdin and wrapped with:

- Project metadata.
- Target lane path.
- Generated timestamp.
- Current branch.
- Current HEAD.
- Last commit.
- Current `git status --short --branch`.
- Required startup gates, including `tautline lane-start --target .`.
- `tautline methodology-status --target . --fail-on-drift` as a required startup gate.
- A statement that ad hoc `git status`, `git log`, CI checks, or local tests do not replace the methodology status gate.
- A portable fallback through `$HOME/.config/tautline/tautline.env` or `$TAUTLINE_METHODOLOGY_REPO/bin/tautline` when `tautline` is missing from `PATH` or exits 127/command-not-found, including the requirement to rerun the same gate with the resolved portable CLI.

The handoff body should include:

- Current state.
- Decisions made.
- Files changed.
- Validation results.
- Open risks or blockers.
- Exact next action.

When a new handoff is prepared and an older one exists, the old handoff is moved to the adapter's archive directory:

```text
.ai-continuity/archive/
```

For lane-local continuity, `.ai-continuity/` is added to `.git/info/exclude` instead of tracked `.gitignore`. That keeps handoff state local to the lane and avoids leaking session-specific context into normal commits.

New Claude/Codex sessions generated from this framework are instructed to check the continuity file at session start before starting new work. They should read it, resolve the methodology CLI, run `tautline lane-start --target .` or the resolved portable CLI equivalent, run `tautline methodology-status --target . --fail-on-drift` or the resolved portable CLI equivalent, then resume from the documented next action only after the status gate exits clean. Before those gates pass, they must not ask clarifying questions, report substantive status, or start analysis from the handoff content. If `tautline` is not on PATH, they should source `$HOME/.config/tautline/tautline.env` (or the legacy minervit env) when present or use `${TAUTLINE_METHODOLOGY_REPO:-$MINERVIT_METHODOLOGY_REPO}/bin/tautline`; missing CLI access is a true blocker only after the portable checkout fallback cannot be found, not permission to substitute ad hoc checks or ask for a person-specific path.

The agent must not ask whether to run the required startup gates, whether to "kick those off", or whether to proceed with a named path after the gates. It should run the gates immediately and continue with the handoff next action unless a true blocker occurs.

The agent must not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session` after writing a handoff. If an explicit stop request prevents continuing, it should report the handoff path and exact next action without opt-in language. Context exhaustion should have already triggered rotation; for Claude Code that means continuity, journal handling, `/compact` or host compaction when directly invokable, or a non-optional fresh-session startup instruction when not directly invokable, then resuming the active goal.

If no execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates, the agent should inspect the adapter, backlog/source-of-truth planning path, readiness markers, and latest delivery or continuity handoff. T0/T1 work uses brief inline/packet planning or the minimal adapter-required artifact before implementation gates. T2/T3 work creates or updates the source-of-truth plan, runs Codex plan review through `tautline run-plan-review`, passes `tautline plan-finalization-precheck`, and verifies explicit or standing approval before implementation. No implementation-ready plan on deck is not a stop condition. Planning is automatic and routine; the agent must not ask whether to plan.

If startup finds the previous PR is already on main and no work is in flight, the agent should perform safe cleanup, sync main, handle generated adapter drift as adapter hygiene only when the project tracks those files and the diff is solely methodology-generated, and continue into the next source-of-truth backlog/planning item without presenting cleanup/backlog/something-else options.
