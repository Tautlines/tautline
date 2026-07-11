# Tautline — the governor for AI coding agents

[![ci-python](https://github.com/tautlines/tautline/actions/workflows/ci-python.yml/badge.svg)](https://github.com/tautlines/tautline/actions/workflows/ci-python.yml)
[![validate](https://github.com/tautlines/tautline/actions/workflows/validate.yml/badge.svg)](https://github.com/tautlines/tautline/actions/workflows/validate.yml)
[![renderer-ci](https://github.com/tautlines/tautline/actions/workflows/renderer-ci.yml/badge.svg)](https://github.com/tautlines/tautline/actions/workflows/renderer-ci.yml)
[![npm-audit](https://github.com/tautlines/tautline/actions/workflows/npm-audit.yml/badge.svg)](https://github.com/tautlines/tautline/actions/workflows/npm-audit.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Tautline stops AI coding agents — Claude Code, Codex — from claiming false completion,
skipping your review gates, or stopping early with the work half-done. You keep one canonical
ruleset, generate a small per-project adapter, and machine-checked enforcement hooks hold the
agent to it. The rules live where you actually control the boundary: your repository, your
pre-push hook, your CI.

![An agent tries to declare done without a green gate — and gets blocked.](docs/assets/demo.gif)

*An agent tries to declare done without a green gate — and gets blocked.*

## Why Tautline

- **Agents can't fake "done."** A completion claim without a green gate is blocked at the
  point of action, not caught later in review.
- **One ruleset, every project.** Canonical policy plus a per-project adapter renders the
  agent instructions and hooks — no copy-pasted prompt drift across repos.
- **Zero telemetry by design.** Nothing phones home. Evidence stays as local logs in your
  own repo; there is no analytics endpoint to opt out of.
- **140+ subcommands for the whole delivery loop.** One CLI covers init, session start, review
  gates, release cutting, backlog sync, and continuity handoffs.
- **Honest enforcement tiers.** Blocking, in-session hooks on Claude; advisory in-session
  elsewhere, with hard gates at pre-push and CI that bind on any runtime, including Codex.
- **SHA-pinned supply chain.** Dependencies and update sources are pinned, so an upstream
  change can't silently alter what runs on your machine.

## Quickstart

Clone the repository, then install the CLI from the checkout:

```bash
git clone https://github.com/tautlines/tautline
cd tautline
bin/tautline install-cli
```

`install-cli` writes a portable launcher to `~/.local/bin/minervit-methodology` (the
compatibility-named launcher for the `tautline` CLI), an
environment file at `~/.config/minervit/methodology.env`, a pre-commit guard in the
framework checkout, and autocompact settings in `~/.claude/settings.json`. Pass `--dry-run`
to see every mutation before it happens; `uninstall-cli` removes the launcher and
environment file (the `~/.claude/settings.json` autocompact settings and any installed
git guards stay in place — remove those by hand if you want a full rollback).

Then initialize a project you want the agent to work in:

```bash
cd <your-repo>
tautline init --target .
```

Answer the printed interview questions, then re-run `init --target . --continue` to render
`CLAUDE.md`, `AGENTS.md`, and the per-repo runtime contract. Existing managed repos skip
onboarding and start a session directly:

```bash
tautline lane-start --target .
```

The legacy `minervit-methodology` command name keeps working as a compatibility shim for
existing installs and generated adapters.

## How it compares

|                                        | Hand-written `CLAUDE.md` rules | Advisory guardrail repos | Tautline |
| -------------------------------------- | :---------------------------: | :----------------------: | :------: |
| Enforced, not advisory                 |               No              |          Partial         |    Yes   |
| False-completion detection             |               No              |            No            |    Yes   |
| Works across Claude Code + Codex        |            Claude only        |          Varies          |    Yes   |
| Review-gate + release tooling built in |               No              |          Rarely          |    Yes   |

Prose instructions ask an agent to behave; Tautline makes the machine refuse the action when
it doesn't. The comparison is about enforcement mechanics, not the quality of anyone else's
prompts.

## Common questions

### How do I stop Claude Code from claiming it's done?

Tautline installs a Stop-time hook that inspects the agent's response and the session's state
before the agent can hand back control, and blocks completion claims that aren't backed by
the required evidence — routing the agent back through the work instead. Independently, the
pre-push guard refuses to ship anything without a green test gate and review evidence, so a
false "done" can't reach your remote even if it slips past the session.

### Can I enforce code review on an AI coding agent?

Yes. Review is a gate, not a suggestion: the agent must produce review evidence for the
assembled diff before a change can be finalized, and the pre-push and CI gates fail the push
if that evidence is missing. This binds regardless of which runtime wrote the code.

### Does it work with Codex as well as Claude Code?

Both. On Claude you get live, blocking in-session hooks. On other runtimes, including Codex,
in-session guidance is advisory, but the real teeth are the pre-push and CI gates that bind
on any runtime. That split is deliberate and stated plainly — you get ship-time enforcement
everywhere and live blocking where the host supports it.

### How do I keep AI agents from skipping steps across many repos?

You maintain one canonical ruleset and a small per-project adapter. The CLI renders the
agent instructions and hooks into each repo from that shared source, so every project follows
the same operating model without hand-copying prompts that drift out of sync.

### Does Tautline send my code or telemetry anywhere?

No. There is no analytics endpoint and nothing phones home. Enforcement evidence stays on
your machine as plain local files: review records and continuity handoffs live inside your
repository checkout, while event logs and usage records default to
`~/.local/state/minervit/`. Everything is yours to inspect or delete.

## A note on the codebase

The CLI is deliberately a single stdlib-only executable (~35k lines, no third-party runtime
dependencies) so it stays trivial to audit and vendor. Extraction into a package under `src/`
is underway; the monolith and the package coexist during that migration. If you open the big
file first, that is by design, not neglect — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
rationale and the layout that makes it navigable.

## Docs

- [Documentation index](docs/README.md) — where to start and where to go next.
- [Operating Manual](docs/reference/operating-manual.md) — the full reference for maintainers
  and advanced adopters.
- [Positioning](docs/product/positioning.md) — the authority model and what the engine does.
- [Support & SLA model](docs/product/support-sla-model.md) — support surfaces and clean
  uninstall.
- [Release engineering](docs/reference/operations/release-engineering.md) — how releases are
  cut, and how adopters pin the stable or experimental framework channel.

## Community

- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, the single test gate, and how to open a PR.
- [AI contribution policy](.github/AI_CONTRIBUTION_POLICY.md) — how AI-assisted contributions
  are expected to be disclosed and gated.
- [GOVERNANCE.md](GOVERNANCE.md) — how decisions are made and who owns what.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.

This is a community-supported open-source project; it ships with no support SLA. Commercial
support tiers are described in the [support model](docs/product/support-sla-model.md), and
general questions can go to `hello@minervit.com`.

## License

Released under the [MIT License](LICENSE).

Maintained by [Minervit](https://minervit.com).
