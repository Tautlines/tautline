# Positioning

**Tautline** — the governor for AI coding agents — is an **agent-enforcement engine** for the solo builder and the small AI team: it makes AI coding agents *finish*, *tell the truth about status*, and *ship only through your gates*.

## The three-layer authority model

Every decision the engine makes resolves through one deliberate hierarchy. This is the product's spine, not an implementation detail.

1. **Canonical policy** — `methodology/policy/*.md` is the reusable process source, assembled into `methodology/canonical-rules.md` as a generated compatibility artifact. It is a *replaceable default ruleset*, not vendor law.
2. **Adapter choices** — your `adapter.json` (e.g. the `example-saas` adapter) makes the project-specific calls: which gates, which providers, which budgets, which runtime targets.
3. **Tool behavior** — guards, hooks, and CLI subcommands enforce layers 1–2 at the point of action. Memory and audit notes are *evidence only* and never override the layers above.

Conflicts resolve top-down: canonical wins for reusable process, the adapter wins for project-specific gates, generated files win over stale hand-written docs. One source of truth, three surfaces, no drift.

## What the engine does

The differentiated core is a **test-backed self-correction loop** wrapped around a **guard-contract pattern**:

- **Guardrails** block an agent from yielding control, claiming false completion, or skipping a gate.
- **Self-correction loop** routes a blocked agent back through its own gates until the work is actually done — backed by the `scripts/test.sh` behavior-test suite (ruff + mypy + pytest) and a same-day RCA→fix cadence that hardens the rules from real failures.
- **Guard-contract pattern** keeps every tool-blocking guard fail-closed with an always-runnable in-band escape, so enforcement never strands the agent.

A **render and delivery pipeline** (iteration-review media + publish) is the second surface — the part that is hardest to self-host and the natural commercial edge.

## Honest enforcement tiers

Enforcement is not uniform across runtimes, and we say so:

- **Tier A — Claude:** blocking, in-session hooks. The agent is stopped at the moment of the violation.
- **Tier B — any runtime (incl. Codex):** advisory in-session, with the real teeth at **ship time** — pre-push and CI gates that bind regardless of runtime.

If you run outside Claude, you get ship-time gates, not live blocking. That is the honest line, and it is why the gates live at the boundary you actually control: your repo.

## Who it's for

The **solo-to-small-AI-team builder** running coding agents against a real codebase, who needs the agent to ship through their gates without babysitting. Enterprise multi-tenancy is a named future architecture, not a v1 claim.

> *See the product roadmap and public-release readiness plans for the full thesis and sequencing.*
