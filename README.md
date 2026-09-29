# Tautline — fast, coordinated AI development

[![ci-python](https://github.com/tautlines/tautline/actions/workflows/ci-python.yml/badge.svg)](https://github.com/tautlines/tautline/actions/workflows/ci-python.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Tautline helps Claude Code and Codex agents work together on real repositories. Give each
project a small set of instructions, see what other agents are changing, keep useful proof of
what ran, and carry decisions into the next session.

The aim is more useful work with less coordination effort. Agents keep moving: work manifests,
status, and evidence are advisory. There are no mandatory planning rounds, review ledgers, or
completion hooks. Your project's tests and CI remain the quality boundary.

## What you get

- **Shared work intent.** Local sibling worktrees share manifests of goals, scope,
  dependencies, blockers, and progress. Agents see peer work at startup and when taking a
  backlog item; the fleet view highlights stale declarations and possible overlaps.
- **Evidence you can inspect.** Wrap an existing test command with `tautline evidence run`
  to keep its exit status and code identity. `tautline health` shows current local facts;
  `--remote` adds on-demand GitHub facts. Unknown stays unknown.
- **Decisions that survive a session.** The operator inbox collects pending decisions,
  persists answers, and keeps answers available until the waiting agent acknowledges them.
  Optional handoffs preserve the next step across a restart.
- **One small project setup.** `tautline init` renders instructions for Claude Code and
  Codex. Choose a local queue, GitHub issues, or Jira for your backlog.
- **Local records, no analytics.** Coordination and evidence stay on your machine.
  Network access comes from the integrations you use; see [Privacy](PRIVACY.md).

## Quickstart

You need Python 3.12+ and git. Tautline supports Linux, macOS, and Windows through WSL2.
Clone the public release and install the checkout launcher:

```bash
git clone https://github.com/tautlines/tautline
cd tautline
bin/tautline install-cli --dry-run
bin/tautline install-cli
source ~/.config/tautline/tautline.env
```

The installer creates launchers, configuration, and a local runtime snapshot. It also ensures
Claude autocompact settings. Its preview lists the affected paths; see
[install and removal](docs/product/support-sla-model.md) for the exact boundary. New checkout
installs pin trusted updates to the installed commit.

Set up the repository where your agents will work:

```bash
cd <your-repo>
tautline init
tautline lane-status
```

`init` asks for the project, integration branch, test command, backlog, and handoff preference,
then writes `.tautline.json`, `CLAUDE.md`, and `AGENTS.md`. Every question has a flag;
`tautline init --yes` accepts the defaults. Existing configurations are preserved unless you
explicitly pass `--force`.

New projects enable work coordination. Existing projects can adopt it without rebuilding their
process; see [shared work](docs/reference/work.md). The older adapter workflow remains
available through `tautline init-project-adapter` and `tautline render-adapters`.
Use [`tautline slim`](docs/reference/lean-migration.md) to migrate a full legacy adapter to
small project instructions.

### Install from PyPI

```bash
pipx install tautline
```

The PyPI package includes the CLI, adapters, and plugin assets as a snapshot of one release.
Update it with `pipx upgrade tautline`; it does not update through the checkout launcher.
The npm package is a pointer to this Python installation, not another runtime.

## Everyday use

```bash
tautline work status                  # see peer agents and possible overlaps
tautline work declare "Improve checkout" --path src/checkout
tautline backlog list                 # use your configured backlog
tautline evidence run -- scripts/test.sh
tautline evidence status              # see the result and whether the code still matches
tautline health                       # local facts; no network
tautline health --remote              # request current GitHub facts
tautline inbox                        # pending operator decisions
```

Declare and refresh work at meaningful boundaries, not on a timer. Read peer work when starting
or resuming a session and before picking the next item. Mark the declaration complete or
abandoned when it ends. A stale or overlapping declaration is information to act on, not a lock.

Manifests coordinate worktrees sharing one local Git repository. They do not synchronize
independent clones or machines, reserve files, or guarantee that two agents cannot collide.
Evidence records what a command reported; it does not certify that a feature works or a
deployment is healthy. Inbox answers are delivered for an agent to interpret, not executed as
commands.

## Agent plugins

In Claude Code, after installing the CLI:

```text
/plugin marketplace add tautlines/tautline
/plugin install tautline-core@tautline
```

`tautline-core` supplies advisory startup context and skills for goal prompts, handoffs, and
clear operator instructions. Its builder hook restricts selected GitHub operations only in
explicitly configured builder lanes. [Builder lanes](docs/builder-lanes.md) explains the
boundary and GitHub App setup.

`tautline-ops` adds a database migration collision skill. The repository also includes
iteration-review rendering assets; automated recap publishing is not part of the current CLI.
Install it with `/plugin install tautline-ops@tautline` when needed.

Codex uses the generated `AGENTS.md` and available skills. Claude-specific hooks do not run in
Codex. Both runtimes can use the same CLI and local records.

## Upgrading from older Tautline

The lean release removes the old completion/review hooks, required planning rounds, and
publishing machinery. It restores coordination and visibility without restoring those gates.
Read the [migration guide](docs/reference/lean-migration.md), preview `tautline slim`, and keep
its backup until you have verified your project. Historical docs under `docs/archive/` and
`docs/archive-prebankruptcy/` describe older behavior, not current requirements.

A development branch can be ahead of public packages. Use [GitHub releases](https://github.com/Tautlines/tautline/releases)
and the installed `tautline version` to identify what you are running; the
[roadmap](ROADMAP.md) distinguishes current capability from future work.

## Learn more

- [Documentation](docs/README.md) and [capability reference](docs/reference/plugin-capability-catalog.md)
- [Product direction](docs/product/positioning.md) and [roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md), [governance](GOVERNANCE.md), and [AI contribution policy](.github/AI_CONTRIBUTION_POLICY.md)
- [Support and uninstall](docs/product/support-sla-model.md), [privacy](PRIVACY.md), and [security reporting](SECURITY.md)

Tautline is MIT-licensed and community-supported, with no support SLA. Maintained by
[Minervit](https://minervit.ai). General questions: `hello@minervit.ai`.
