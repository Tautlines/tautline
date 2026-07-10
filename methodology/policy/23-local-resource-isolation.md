## Local Resource Isolation

- Prefer lane-local resource isolation over machine-wide serialization. Use unique Docker Compose project names, host ports, local databases, cache endpoints, and service URLs per active lane.
- Commands that touch local services must run through the lane resource environment, either by sourcing the configured lane env file or by using `minervit-methodology lane-run --target . -- <command>`.
- A port-in-use failure is not a true blocker until the agent has retried the command through the lane resource environment or identified a project resource that cannot be isolated.
- Use resource locks only for project-declared machine-global resources that cannot be isolated by lane-specific env, names, ports, paths, or remote API calls.
- Do not add a broad lock that serializes all local gates when the actual contention is fixed default ports or an inherited global environment variable.
