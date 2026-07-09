## Stop And Deferral Red Flags

- Do not convert required process into a choice. If methodology, adapter guidance, a handoff, an execution packet, a source-of-truth plan, review evidence, validation, or a board/status update is required, run it unless a true blocker exists.
- A stop is valid only when the lane has no active work, the goal/milestone ledger is terminal, the human operator explicitly asked to stop, a fresh true blocker is declared, or context rotation has written continuity and the exact fresh-session startup action.
- Use `minervit-methodology blocker-declare --target . --kind <kind> --reason "<one sentence>"` for true blockers; clear stale records with `blocker-clear`.
- Phrase matches are advisory evidence for guard telemetry during the state-based transition. Do not add new forbidden phrases; retire them with `guard-report` evidence. Lines labeled `Forbidden example:` document wording to rewrite; the label is not a stop-message escape hatch.
- Forbidden example: "Committed <sha>. Pausing here at a clean checkpoint." Continue with the next authorized action instead.
- Forbidden example: "Next milestone is <name>. Want me to begin planning, or pause here?" Start the required planning artifact or name the exact blocker.
- Forbidden example: "Codex R3 running. Wakeup in 10 min." Actively supervise the review or do parallel-safe work until a terminal result.
- Forbidden example: "Review found C1/P1 blockers. Pick #1, #2, or #3 and I'll execute." Fix the blockers or ask one exact blocker question only when every safe path changes approved scope or approval.
- Forbidden example: "Say \"keep going\" to start the named next task." Start it now unless stopped by the operator, terminal state, context rotation, or a true blocker.
