---
name: project-bootstrap
description: Bootstrap a project onto the Minervit AI Delivery Methodology by creating a project adapter and rendering thin Claude/Codex rule files from canonical policy.
---

# Project Bootstrap

Use to initialize unmanaged repos, create or migrate project adapters, render
generated `CLAUDE.md`/`AGENTS.md`, ask adapter-bootstrap questions, or repair
missing adapter setup.

Read `references/project-bootstrap-policy.md` before writing adapters,
overwriting generated files, handling existing hand-written instructions,
declaring stack/cloud defaults, or adopting repo-local `.minervit/adapter.json`.

## Fast Path

1. Run `tautline init --target .` for unmanaged repos.
2. Capture unresolved setup questions with `adapter-bootstrap-questions --target .`.
3. Put reusable process in methodology files and project choices in the adapter.
4. Render generated adapters from the source adapter; do not hand-edit generated
   `CLAUDE.md`, `AGENTS.md`, or `.minervit-ai-delivery.json`.
5. Validate with lane startup, `methodology-status --fail-on-drift`, and the
   adapter/schema tests relevant to the repo.

## Non-Negotiables

- Do not overwrite hand-written project rule files without the explicit init
  flow proving it is safe.
- Do not invent cloud, auth, deploy, billing, or workflow defaults from tool
  memory.
- Repo-local `.minervit/adapter.json` is the adopter-owned default source.

## Required Follow-Through

Use the reference for adapter shape, generated-file ownership, bootstrap
interview handling, stack policy, and migration details.
