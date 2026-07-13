# Contributing

Thanks for your interest in contributing. This repository is the canonical source for
**Tautline**, the governor for AI coding agents: guardrails plus a test-backed
self-correction loop that make AI
coding agents finish work, report status honestly, and ship through your gates. This guide
covers how the repository is laid out, how to set up a dev environment, the single test gate
your change must pass, and how to open a pull request.

> Governance scaffolding (this file, `CODE_OF_CONDUCT.md`, `SECURITY.md`) ships with the
> MIT-licensed project (`LICENSE`).

## Repository layout

The project is deliberately small once you separate *policy*, *configuration*, and *code*.
Learn these five anchors and you can find anything:

| Path | Role |
| --- | --- |
| `methodology/canonical-rules.md` | **Policy SSOT.** The single source of truth for reusable process rules. Everything else defers to it. Treat this as a *replaceable default ruleset*, not person- or shop-specific law. |
| `bin/tautline` | **The CLI.** A single extension-less executable (Python) that implements every subcommand, gate, and guard. Invoked as `tautline`; `bin/minervit-methodology` remains as a compatibility shim. |
| `methodology/adapter-schema.json` | The JSON Schema for a project adapter — the contract an adopter fills in to describe their own repo, commands, gates, and tool paths. |
| `plugins/` | Tool-specific behavior (Claude/Codex plugin manifests, hooks, skills). This is where runtime-target behavior lives, not policy. |
| `adapters/projects/example-saas.json` | The **reference adapter**. Use it as the running example for any adapter-shaped change, docs, or test fixture. |

Other notable paths: `scripts/` (the test and validation gates), `tests/` (the behavior
suite), `pyproject.toml` (all lint/type/test configuration), and `docs/` (releases and
reference documentation).

### The three-layer authority model

This is the differentiated core of the product, so contributions must respect it. Authority
flows in exactly one direction:

1. **Canonical policy** (`methodology/canonical-rules.md`) defines the required contracts and
   safety boundaries — *what must be true* for any project.
2. **Adapter choices** (`adapters/projects/*.json`, validated against `methodology/adapter-schema.json`)
   declare the concrete commands, paths, deployment targets, review wrappers, gates, and
   project exceptions — *how this project satisfies the policy*.
3. **Tool behavior** (`bin/tautline` + `plugins/`) enforces and renders those
   choices for a specific runtime (Claude Code, Codex) — *the mechanism*.

Put each change at the right layer:

- Reusable process rules go in `methodology/`.
- Project-specific choices go in `adapters/projects/*.json`.
- Tool- or runtime-specific behavior goes in plugin skills or the CLI/renderer.

Do **not** copy full process policy into a project repo by hand, and do not hard-code one
project's commands into the CLI. If you find yourself doing either, you are working at the
wrong layer.

## Development setup

You need Python 3.10+ (the CLI uses `match` statements, which set the 3.10 floor) and the
pinned dev toolchain:

```bash
pip install -r requirements-dev.txt
```

This installs the exact pinned versions of `ruff`, `mypy`, and `pytest` that CI runs. The
versions are pinned for reproducibility — bump them intentionally in a dedicated change, not
as a side effect.

The CLI is a single executable, not an installable package, so there is intentionally no
`[project]` / `[build-system]` table in `pyproject.toml`. Run it directly during development:

```bash
bin/tautline --help
```

The CLI currently lives in that single file, `bin/tautline`. A split into an importable
package is planned — see [ROADMAP.md](ROADMAP.md) for the plan and status.

## Required local gates

**`scripts/test.sh` is the single behavior gate.** It must be green before you push or open a PR. It runs, in
order:

```
1. ruff check bin/tautline src tests                 # fast lint
2. mypy --config-file pyproject.toml bin/tautline src   # type-check (lenient baseline)
3. pytest                                            # the behavior suite
```

Run it from the repo root:

```bash
scripts/test.sh
```

If the dev toolchain is missing, the script tells you to `pip install -r requirements-dev.txt`
rather than failing with a cryptic "command not found".

Repository branch protection must require the Python behavior gate before merge. In GitHub terms, the `ci-python` workflow matrix is a blocking check; do not make it informational-only.

The pytest suite is the safety net for an otherwise large, legacy CLI. **New behavior must
arrive with a test.** If you change a guard, a gate, or a subcommand, add or update a
`tests/test_*.py` case that pins the new behavior.

### The ruff / mypy ratchet

`pyproject.toml` is the single source of lint and type configuration, and it encodes a
**ratchet discipline**. The suppression lists are a *day-one baseline for legacy code* and are
meant to **shrink over time, never grow**:

- `[tool.ruff.lint.per-file-ignores]` for `bin/tautline` suppresses only the
  specific rules the legacy file currently violates (e.g. `F541`, `F811`, `F841`, `B904`).
- `[tool.mypy] disable_error_code` lists the error codes traceable to known legacy root causes
  (duplicate defs, untyped JSON/subprocess `Any` narrowing).

**Rules of the ratchet:**

- **Never add a new code** to either suppression list to make your change pass. A new
  violation means your code (or your fix) should be corrected, not exempted.
- **Deleting codes is the goal.** When you fix the underlying issue, remove its code from the
  list. That is how the baseline burns down.
- New violations of any *other* rule, and these rules in any *other* file, already fail the
  gate — keep it that way.

If your change genuinely needs a different lint or type posture, raise it in the PR
description as an explicit, reviewed decision — do not silently widen the exemption list.

### `validate.sh` is frozen — write pytest, not grep pins

`scripts/validate.sh` is the **legacy grep-pin gate**. It is a large shell script that asserts
behavior by grepping expected strings, and it is being **frozen**: it should not grow, and new
gates should not be added to it. Grep pins are slow (hundreds of cold-start subprocess
spawns) and brittle compared to real tests. It still owns unique release, public-doc,
generated-artifact, and compatibility checks while that migration is in progress.

**When you need to pin new behavior, write a pytest in `tests/`, not a grep pin in
`validate.sh`.** The pytest suite is the supported gate; `validate.sh` is a frozen 5-line alias of `test.sh` kept for legacy automation. Do not extend it.

## Before you build

Save yourself and the maintainer time by matching the size of the change to the size of the
conversation it needs:

- **First-time contributor, or any non-trivial change** (new behavior, a new subcommand, a
  schema change, anything touching the three-layer authority model): open an issue first and
  wait for a maintainer nod before you write code. This is the discussion step, not a
  formality — it's where scope, layering, and approach get agreed on before either of you
  spends review time on it.
- **Typo fixes, doc fixes, or an obvious bug with a failing test attached**: skip the issue,
  go straight to a PR. Small, self-evidently-correct changes don't need a discussion round
  trip.
- **Unsolicited refactors and style-only PRs are closed.** This project follows the htmx
  model here: reformatting code, renaming things, or restructuring modules without a
  discussed problem behind it costs review time and offers no corresponding benefit. If you
  think something needs a refactor, open an issue and make the case first.

See [`.github/AI_CONTRIBUTION_POLICY.md`](.github/AI_CONTRIBUTION_POLICY.md) for the
additional bar AI-assisted contributions are held to, and [`GOVERNANCE.md`](GOVERNANCE.md)
for how decisions get made.

## Developer Certificate of Origin (DCO)

Every commit must be signed off: `git commit -s`. This appends a `Signed-off-by:` trailer
certifying that you wrote the change (or otherwise have the right to submit it under the
project's license) — it's a lightweight, standard way of taking ownership of a contribution
without a separate contributor license agreement. It is enforced automatically: PRs with an
unsigned commit fail the DCO check and cannot merge until every commit in the PR is signed
off (`git commit --amend -s` or an interactive rebase with `-s` fixes history after the
fact).

## Response expectations

This is a community-run project with no support SLA on issues or pull requests. Triage
happens in batches, not continuously — expect a delay before your issue or PR gets a response,
not silence forever. If you haven't heard back and it's been a while, a polite bump is fine.

The one deliberate exception is security: time-sensitive vulnerability reports go through
[`SECURITY.md`](SECURITY.md), which *does* carry response-time targets. That contrast is
intentional — security reports get a guaranteed clock; everything else gets best-effort
attention in the order it arrives.

## Pull request flow

1. **Branch.** `main` is protected product infrastructure — never commit directly to it. Create
   a feature branch and open a PR. (Direct pushes to `main` are break-glass only, and must
   document the reason.)
2. **Make the change at the right layer** (see the authority model above) and add tests for any
   new behavior.
3. **Run the gate locally:** `scripts/test.sh` must be green.
4. **Review before push.** Get a review for any non-trivial code or process change before it
   merges. State the problem and evidence, the proposed change, migration impact, and the
   validation you ran in the PR description.
5. **Fix Critical/P1 findings before merge.** Lower-severity findings (P2/P3/Nit) may be
   backlogged only when explicitly allowed and documented with evidence.
6. **Merge** via the merge queue or auto-merge. Routine merges do not use admin override.

### Changing canonical rules or generated adapters

Process-policy and adapter-behavior changes have extra discipline:

- A process-policy change PR must state the problem/evidence, the proposed
  canonical/adapter/skill/CLI change, migration impact, the validation run, and review status.
- Adapter-only changes under `adapters/projects/*.json` are project configuration, not a
  framework release — they do not require a `VERSION`/changelog bump unless the same PR also
  touches reusable surfaces (CLI, schema, canonical rules, skills, validation,
  generated-adapter behavior, README, or release docs).
- When you change generated adapter behavior, update `bin/tautline`, regenerate the
  affected project files, and make sure `scripts/test.sh` stays green.

Use `adapters/projects/example-saas.json` as the example in any new docs, fixtures, or tests —
do not reference real adopter projects.

## Reporting security issues

Do not file security issues as public PRs or issues. See `SECURITY.md` for the private
disclosure process.
