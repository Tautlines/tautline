## Execution Packet Work Loop

- Human operator defines milestone goals and approves the milestone plan.
- Codex leads milestone-level planning and gets Claude review before tactical execution begins.
- The approved plan is converted into `.ai-work/EXECUTION_PACKET.md` in the lane.
- The execution packet must include milestone goal, non-goals, ordered tactical queue, dependencies, safe parallelism, tests/specs required per item, validation gates, review gates, merge gates, drop/defer rules, true-blocker criteria, and completion definition.
- Claude consumes the tactical queue until it is exhausted or a true blocker occurs.
- Claude may push, open PRs, enable merge queue, monitor gates, and continue after gates without asking for arbitrary permission.
- Tactical run evidence is recorded under `.ai-runs/`.
