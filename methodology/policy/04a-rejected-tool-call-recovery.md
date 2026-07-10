## Rejected Tool Call Recovery

- If a tool call is rejected, denied, cancelled, or blocked, treat that as a narrow signal about that call. Do not retry the same call; choose a different concrete action, do non-conflicting work, or ask one exact blocker question.
- Status after rejection must acknowledge the exact state first. Do not answer with `yes`, `about to`, `queued`, `planned`, or `next I'll` when no tool, monitor, or parallel work is active.
- A rejected commit, push, merge, or other tool call is not a global stop signal. Continue with review, validation, documentation, ledger updates, monitoring, current context, or another parallel-safe task.
- A rejected read, search, or prep/discovery tool call is also not a stop signal. Use current context or another named source if possible.
- Non-conflicting work includes current-diff review, allowed validation, documentation/evidence updates, next independent queue item, and active monitor follow-up. Before claiming none remains, name which checks were unavailable.
- If targeted verification is rejected, continue with explicit uncertainty or ask one exact blocker question only when true-blocker criteria are met. Do not perform a second prep/discovery call after a rejected prep/discovery call.
