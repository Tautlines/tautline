## Automation

- Automations must not use active development lanes as scratch space.
- Readiness/status automations should prefer read-only GitHub API/`gh` calls.
- If a checkout is truly needed, use a dedicated clone, not a shared worktree or active lane.
