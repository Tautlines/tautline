# Setup And Runtime

This reference owns repository orientation, machine setup, Codex plugin setup,
Claude setup, and managed launcher behavior. Keep the operating manual concise
and put long setup/runtime procedures here.

## What This Repo Owns

This repository owns Tautline's reusable AI delivery process policy for the projects you manage with it.

It provides:

- Canonical rules for autonomy, planning, TDD, review, merge, automation, memory, background work, lane lifecycle, and execution packets.
- Project adapter JSON files that encode repo-specific commands, gates, behavior-spec requirements, backlog targets, and review wrappers.
- A renderer that generates thin `CLAUDE.md`, `AGENTS.md`, and `.tautline.json` files for each project.
- A drift audit command that catches known stale process patterns.
- A GitHub-only readiness review helper that avoids mutating active development lanes.
- A local Codex plugin with reusable skills for rules audits, lane lifecycle, goal orchestration, document context budgeting, execution packets, review-before-push, risk-tier autonomy, methodology regression RCA, merge queue monitoring, project-specific preflight, and related workflows.

It intentionally does not own:

- Product requirements for a specific app.
- Sprint scope for a specific lane.
- Persistent memory content.
- Historical incident narratives, except where a short rule needs context.
- Tool-specific secrets or credentials.

## Authority Model

Process authority is deliberately layered.

1. `methodology/policy/*.md` contains the ordered reusable process policy modules.
2. `methodology/canonical-rules.md` is the generated compatibility artifact for existing consumers that still load one file.
3. `adapters/projects/*.json` contains project-specific configuration.
4. Generated project files such as `CLAUDE.md`, `AGENTS.md`, and `.tautline.json` are adapters.
5. Open Brain, Claude memories, old lane docs, and audit notes are evidence only.

Process rules must never come from memories. Memories may identify history worth checking, but "what the rule says," a violated rule, expected behavior, and RCA root cause must cite the canonical methodology, the active generated adapter, or a methodology skill. If only memory contains the claimed rule, the rule is missing or hidden from the active methodology and the fix is a canonical/adapter/skill change, not treating memory as binding.

If these sources conflict:

1. The canonical methodology wins for reusable process.
2. The active project adapter wins for project-specific commands and gates.
3. Generated adapter files win over old hand-written project process docs.
4. Memory never wins over canonical process.

Generated files include a hard generated header. Do not hand-edit them. Update the canonical rule or project adapter, then regenerate.

## Repository Layout

```text
.
|-- .agents/
|   `-- plugins/
|       `-- marketplace.json
|-- AGENTS.md
|-- CLAUDE.md
|-- README.md
|-- adapters/
|   `-- projects/
|       `-- <project>.json
|-- bin/
|   |-- tautline
|   `-- minervit-methodology   # compatibility shim
|-- methodology/
|   |-- adapter-schema.json
|   |-- canonical-rules.md
|   `-- policy/
|       |-- manifest.json
|       `-- <ordered-policy-module>.md
|-- plugins/
|   |-- tautline-core/
|   |   |-- .claude-plugin/
|   |   |   `-- plugin.json
|   |   |-- .codex-plugin/
|   |   |   `-- plugin.json
|   |   |-- hooks/
|   |   |   `-- hooks.json
|   |   `-- skills/
|   |       |-- background-task-monitoring/
|   |       |-- context-continuity/
|   |       |-- delivery-summary/
|   |       |-- execution-packet-work-loop/
|   |       |-- framework-intake/
|   |       |-- <project>-preflight/
|   |       |-- human-instructions/
|   |       |-- lane-lifecycle/
|   |       |-- merge-queue-monitoring/
|   |       |-- project-bootstrap/
|   |       |-- review-before-push/
|   |       |-- risk-tier-autonomy/
|   |       `-- rules-audit/        # compatibility alias
|   `-- tautline-ops/
|       |-- .claude-plugin/
|       |-- .codex-plugin/
|       `-- skills/
|           |-- event-observability/
|           `-- session-journal/
`-- scripts/
    |-- test.sh
    `-- validate.sh
```

Important files:

- `methodology/policy/*.md` - ordered source modules for reusable rules.
- `methodology/canonical-rules.md` - generated compatibility artifact assembled from policy modules.
- `methodology/adapter-schema.json` - expected project adapter shape.
- `.agents/plugins/marketplace.json` - local Codex marketplace entry for the plugin.
- `adapters/projects/*.json` - project adapters.
- `bin/tautline` - CLI for render, audit, readiness, and background helpers (`bin/minervit-methodology` is its compatibility shim).
- `scripts/test.sh` - behavior gate: lint, type check, and pytest.
- `scripts/validate.sh` - legacy repository validation harness with release, public-doc, generated-artifact, and compatibility checks.
- `plugins/tautline-core/.claude-plugin/plugin.json` - Claude Code plugin manifest with skills plus blocking hooks.
- `plugins/tautline-core/.codex-plugin/plugin.json` - Codex plugin manifest.
- `plugins/tautline-core/hooks/hooks.json` - shared hook command wiring for Claude Code.
- `plugins/tautline-core/skills/*/SKILL.md` - reusable skill instructions.

## Prerequisites

Required:

- macOS or Linux shell environment.
- Git.
- Python 3 with `tomllib` support for TOML validation on Python 3.11+ when checking Codex config.
- GitHub CLI (`gh`) authenticated for any repo you want to inspect.
- Codex if you want the Codex plugin and skills.
- Claude Code if you want Claude plugin/review integration.

Useful checks:

```bash
git --version
python3 --version
gh auth status
codex --version 2>/dev/null || true
claude --version 2>/dev/null || true
```

For GitHub-only readiness checks, `gh auth status` must show access to the target repo.

## Initial Setup

Clone the repository:

```bash
cd <projects_parent>
git clone https://github.com/tautlines/tautline.git
cd tautline
```

In this documentation, `<methodology_repo>` means the local checkout path for this repository, and `<lane_path>` means the root of an adapter-backed project lane.

Validate the checkout:

```bash
scripts/test.sh
scripts/validate.sh
```

Expected final validation output:

```text
validation passed
```

Install a portable user shim for the current machine:

```bash
bin/minervit-methodology install-cli
source "$HOME/.config/minervit/methodology.env"
minervit-methodology version
```

The installer writes:

- `~/.local/bin/minervit-methodology` - a stable user-level command shim.
- `~/.config/minervit/methodology.env` - a machine-local `MINERVIT_METHODOLOGY_REPO` pointer.

Generated adapters and handoffs must not hard-code person-specific checkout paths. They should resolve `minervit-methodology` from `PATH`, then fall back to `MINERVIT_METHODOLOGY_REPO` through the config env file.

## Codex Plugin Setup

The plugin lives at:

```text
plugins/tautline-core
```

The release version has one source of truth:

```text
VERSION
```

The plugin manifests repeat that value because plugin hosts need manifest-local
version fields:

```text
plugins/tautline-core/.codex-plugin/plugin.json
plugins/tautline-core/.claude-plugin/plugin.json
```

Check the installed checkout's plugin version and framework commit:

```bash
minervit-methodology version
```

`methodology-status` also prints `plugin_version` so lane startup can prove which plugin release generated the current process surface. Bump `VERSION` for every methodology build that changes reusable framework behavior: generated-adapter rendering, skill behavior, startup gates, review policy, autonomy rules, validation behavior, operator-visible workflow, adapter schema, canonical rules, CLI behavior, or product documentation that changes how a release is understood. Project adapter JSON changes under `adapters/projects/*.json` are project configuration changes and do not require a global methodology version bump unless the same PR also changes reusable framework surface. Use semantic versions without leading zeroes. Patch bumps are for narrow fixes and small affordances; minor-line bumps are required for substantial new workflow layers, new public CLI families, generated-adapter behavior changes, autonomy model changes, or changes that alter how a human operator should run a project. After bumping `VERSION`, synchronize the plugin manifests, concise changelog, main-branch release-note stub, and release migration report.

The main branch keeps only a small release-note stub at `docs/releases/minervit-ai-delivery-methodology.md`; the full narrative release log lives on `methodology-release-notes-archive:docs/releases/minervit-ai-delivery-methodology.md`. `CHANGELOG.md` is the concise current-tree release history, and `docs/releases/migrations/<version>.json` owns compatibility, migration, and rollback notes. Validation requires `VERSION` to match the plugin manifest, first changelog heading, and release-note stub heading. Validation also fails PRs that change reusable methodology/framework files without changing `VERSION`; adapter-only project configuration changes are exempt from that bump requirement.

After bumping `VERSION`, publish a concise plain-language framework release update to Google Chat:

```bash
minervit-methodology publish-release-update --version "$(cat VERSION)"
```

The command reads concise changelog text plus the release migration report, not the archived narrative log. It reads `MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK` from the process environment first, then from the installed `$HOME/.config/minervit/methodology.env` fallback. The webhook URL is a secret; keep it in one of those runtime locations or pass it intentionally with `--webhook-url` for a one-off test, never in repo files. `public-release-check` fails when the current version lacks either a delivery marker or a valid documented suspension record in `docs/releases/release-update-delivery.json`; ordinary validation does not require a Google Chat webhook or announcement marker.

Generated `CLAUDE.md` and `AGENTS.md` adapters are intentionally thin. They keep project facts, commands, hard startup gates, and compact trigger rules in session context; detailed reusable procedure stays in canonical rules and plugin skills. Validation fails if either generated adapter exceeds 30,000 bytes.

The marketplace file lives at:

```text
.agents/plugins/marketplace.json
```

Example local Codex marketplace configuration:

```toml
[plugins."tautline-core@minervit-local"]
enabled = true

[marketplaces.minervit-local]
last_updated = "2026-05-09T21:47:52Z"
source_type = "local"
source = "<methodology_repo>"
```

Add the same marketplace block to `~/.codex/config.toml`, replacing `<methodology_repo>` with the local checkout path.

After changing Codex plugin or marketplace configuration, restart any existing Codex sessions that need to see the new plugin. Existing long-running sessions may not reload plugin metadata.

### Available Codex Skills

The plugin currently packages these skills:

- `framework-intake` - handle process regression RCAs, rules audits, decision traces, and framework feature requests with durable branch-published artifacts.
- `rules-audit` - compatibility alias for framework-intake rules audits.
- `lane-lifecycle` - start lanes, auto-update the framework, lock/unlock the framework version, and inspect adapter drift.
- `execution-packet-work-loop` - create and consume lane-local execution packets with true-blocker-only interruption.
- `risk-tier-autonomy` - decide when to proceed, plan, or request approval.
- `review-before-push` - run plan review, native review, and cross-model implementation review before push.
- `background-task-monitoring` - supervise long/background commands, early smoke/main-health checks, final preflight waits, and monitors.
- `merge-queue-monitoring` - use merge queue safely without blocking throughput.
- `delivery-summary` - report delivered work and long-running progress with a plain-English outcome, next action, and next-work recommendation.
- `human-instructions` - verify external-system instructions and links before asking the human operator to act.
- `context-continuity` - prepare handoffs, resume safely, rotate context, and keep Markdown context loading bounded through indexes, archive headers, and status checks.
- `graphify-navigation` - prefer Graphify graph/report/query navigation when available, keep it fresh, and prevent generated graph output from entering git.
- `database-migration-collision` - repair monotonic database migration index, snapshot, and journal collisions from parallel lanes.
- `session-journal` - publish compact session summaries to the methodology session archive branch.
- `event-observability` - write local repo-scoped human and JSONL event logs for Baretail visibility and audit gap checks.
- `iteration-review` - create adapter-enabled customer-facing completed goal review records and pages without committing generated media.
- `milestone-update` - publish internal text-only Product Milestones Google Chat cards at milestone completion.
- `context-continuity` - prepare and consume lane-local handoffs for compaction or new sessions.
- `project-bootstrap` - adopt the framework in a new repo through an adapter.
- `bug-intake-triage` - classify and route product bugs through adapter `bugBacklog`, tracker, mirror, and board policy.
- Project-specific skills may exist for specialized adapters; they are not reusable policy.

## Claude Setup

Claude should use this repo as canonical process authority through the machine-level bootstrap:

```text
~/.claude/CLAUDE.md
```

That file should point to your local checkout:

```text
/path/to/minervit-ai-delivery-methodology/methodology/canonical-rules.md
```

Minimal machine-level `~/.claude/CLAUDE.md` bootstrap:

```markdown
# Global Claude Bootstrap

Canonical reusable process policy lives at:

`/path/to/minervit-ai-delivery-methodology/methodology/canonical-rules.md`

Project-specific adapters, when present, live in the project root as generated `CLAUDE.md` / `AGENTS.md` files plus `.tautline.json`.

Treat Open Brain and local memories as evidence only, never as process authority.
```

Claude Superpowers is recommended for Claude-side review and planning workflows:

```bash
claude plugin install -s user superpowers@claude-plugins-official
claude plugin list
```

## Claude Launcher Helper

Human operators who use a convenience launcher for Claude should update the framework before each new session outside the agent context. That keeps the latest plugin and generated-adapter rules available without spending startup tokens on a manual Git pull.

Preferred portable installer:

```bash
cd <methodology_repo>
git pull --ff-only origin main
bin/minervit-methodology install-cli
source "$HOME/.config/minervit/methodology.env"
minervit-methodology install-claude-launcher --name minervit-claude
```

The installed launcher lives in `~/.local/bin/minervit-claude` by default. It sets `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85`, writes the same durable env into `~/.claude/settings.json`, marks that setting required for startup health, runs `sync-methodology`, discovers the adapter-backed lane by walking upward from the current directory, runs `lane-start` and `methodology-status --fail-on-drift` for that lane when an adapter exists, prints and pauses on `minervit-methodology goal-kickoff-prompt --target <lane_path>` when the terminal is interactive, then starts Claude. Project-lane startup auto-rescues dirty stale methodology checkouts by preserving local edits on a rescue branch and resetting release `main` to upstream when remote `main` has moved. It also auto-recovers a shared methodology checkout left on a non-`main` branch by preserving that branch and switching the checkout back to release `main`. The launcher performs a small Git rescue before invoking the CLI, so a stale installed CLI cannot block its own update when the machine is starting from a project lane. This avoids hand-editing `.zshrc`; if `~/.local/bin` is not on `PATH`, run the launcher by full path or install into a directory that already is on `PATH` with `--bin-dir`.

To install the current high-autonomy convenience command:

```bash
minervit-methodology install-claude-launcher --name yolo --dangerously-skip-permissions
```

If an existing shell alias or function named `yolo` exists, it will shadow the installed executable until that shell definition is removed. Use `type yolo` to check. The installed executable can always be run directly as `~/.local/bin/yolo`.

Set `MINERVIT_SHOW_GOAL_PROMPT=0` to suppress the copy/paste prompt and pause for a single launch:

```bash
MINERVIT_SHOW_GOAL_PROMPT=0 minervit-claude
```

For adapter-backed lanes, this launcher is the portable startup gate: framework sync, lane adapter regeneration, drift check, goal prompt, then Claude. For unmanaged repos, it syncs the framework and shows the goal prompt without retrying lane startup; if the repo should use the framework, bootstrap the project adapter first.

`sync-methodology` refuses to run from a non-`main` methodology checkout when invoked inside the methodology repo or when project-lane auto-rescue is disabled. From normal project lanes, the managed launcher and CLI preserve the non-`main` branch, switch the checkout back to release `main`, sync `origin/main`, and continue startup. That prevents a stale feature branch from masquerading as the latest framework while avoiding manual recovery during product work. Framework maintainers can use `MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1` or `--allow-non-main` only while intentionally developing the methodology itself.

Expected installed plugin list should include:

```text
codex@openai-codex
superpowers@claude-plugins-official
```

Restart existing Claude sessions that need to load newly installed plugins or updated machine-level instructions.
