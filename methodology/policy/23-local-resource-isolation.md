## Local Resource Isolation

- Prefer lane-local resource isolation over machine-wide serialization. Use unique Docker Compose project names, host ports, local databases, cache endpoints, and service URLs per active lane.
- Commands that touch local services must run through the lane resource environment, either by sourcing the configured lane env file or by using `tautline lane-run --target . -- <command>`.
- A port-in-use failure is not a true blocker until the agent has retried the command through the lane resource environment or identified a project resource that cannot be isolated.
- Use resource locks only for project-declared machine-global resources that cannot be isolated by lane-specific env, names, ports, paths, or remote API calls.
- Do not add a broad lock that serializes all local gates when the actual contention is fixed default ports or an inherited global environment variable.
- Operator secrets persist in `~/.config/tautline/secrets.zsh` (legacy `~/.config/minervit/secrets.zsh`); the installed config env sources that store, and webhook-bearing commands fall back to it. A `MINERVIT_*`/`TAUTLINE_*`/`*_WEBHOOK` secret reported missing by a `tautline` command is not a true blocker until the agent has run `tautline secret-status --name <VAR>` and retried through the lane environment; only `secret_source: absent` after that retry is an operator escalation -- `secret_source: indeterminate` means a layer exists and could not be read, so absence was never established and escalating on it is acting on a measurement nothing took.
