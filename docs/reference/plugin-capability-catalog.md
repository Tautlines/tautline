# Current capability reference

The CLI and plugins provide a small set of tools for agent teamwork. This page describes the
current source; see [releases](https://github.com/Tautlines/tautline/releases) for package
availability. `tautline --help` and each command's `--help` supply the exact arguments.

## Workflows

| Workflow | Current tools and boundary |
| --- | --- |
| Project setup | `init`, `slim`, adapter validation/rendering, and checkout/PyPI installation. Lean instructions are the default. |
| Shared work | `work` manifests and fleet status across local sibling worktrees. Startup and backlog pickup surface peer intent. Advisory overlap/staleness, no file locks or cross-machine sync. |
| Backlog | `backlog list/add/take/done` with one configured local, GitHub, or Jira provider. No board mirrors or atomic agent reservation guarantee. Jira has not been validated against a live site. |
| Evidence | `evidence run -- <command>` records an execution and code identity; `evidence status` reports its relevance to the current tree. Optional and local. |
| Health | `health` reports local facts. `health --remote` requests GitHub facts. No automatic deployment, no inference that an unknown check passed. |
| Decisions | `decision-record` and `inbox` retain questions and answers. `inbox --answer ID --text TEXT`, `--answers`, and `--ack ID` support answer delivery and acknowledgement; answer text is not automatically executed. |
| Continuity | Optional `.ai-continuity/HANDOFF.md`, startup guidance, and a handoff skill. No compulsory journal or durable goal runner. |
| Diagnostics | `lane-status`, `doctor`, decision/event readers, GitHub budget/identity reporting, and security diagnostics. |
| Builder operations | Purpose-built GitHub verbs, lane roles, App credentials, a Claude Bash hook, and a shell `gh` shim. Scope and limits are in [builder lanes](../builder-lanes.md). |
| Release | Public export/sanitization, package generation, `release-tail`, and registry drift checks. [Release procedure](releases.md). |

## Plugin packages

`tautline-core` contains goal-prompt, handoff, and verified-human-instructions skills. Its
Claude package installs an advisory SessionStart report and the specialized builder hook.
The Codex package exposes its skills; Claude hooks do not run in Codex.

`tautline-ops` contains the database migration collision skill. Iteration-review renderer
and page assets remain in the repository, but there is no current recap publishing workflow.

## Explicit limits

There is no Stop-time completion gate, review-evidence push gate, multi-round plan review,
automatic milestone advancement, usage accounting collector, event HTTP viewer, or automated
release/deployment/recap messaging in the current product. Old design documents, schema fields,
and release notes do not establish current support for those workflows.

New coordination and evidence tools do not bring those requirements back. Use the project's
existing tests, CI, and review practice; record useful facts at work boundaries.
