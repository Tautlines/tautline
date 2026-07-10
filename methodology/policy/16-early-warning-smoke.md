## Early-Warning Smoke

- Early-warning smoke is no longer a standing gate for every tactical iteration. Routine startup/main health is checked by lane startup; full preflight before push and CI remain the branch-quality gates.
- Run the adapter early-warning smoke only when the adapter, source-of-truth plan, issue, human operator, or a concrete risk signal asks for it. Do not launch background smoke monitors merely because a new plan/spec write, edit, PR, rebase, or iteration boundary began.
- If an early-warning smoke is running because it was explicitly required, supervise it with the normal background-work monitor rules and do not start duplicate local-service smoke commands for the same lane resources.
- A known smoke failure, stale required smoke, wrong target, or resource contention interrupts the relevant risky action until investigated or proven unrelated with named evidence. A missing ambient smoke poll does not block routine commit, push, queued-delivery summary, or next-work selection.
- Passing early-warning smoke is advisory confidence, not a new pause point. It does not replace full preflight, implementation review, merge checks, or CI.
- Do not delay clean queued-delivery summaries for routine post-merge smoke unless a failure/degraded signal is already known, the human operator explicitly asks for that check, or the next action truly depends on the merged main commit.
