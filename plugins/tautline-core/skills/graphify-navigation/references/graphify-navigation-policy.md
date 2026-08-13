# Graphify Navigation Policy Reference

This reference keeps detailed Graphify navigation policy behind the concise
`graphify-navigation` skill entrypoint.

## Purpose

Use this policy when a project adapter enables Graphify, when `graphify-out/`
exists, or when the human operator asks to install, build, update, repair, or
use Graphify.

Graphify support is adapter-backed and optional per project. For adapter-backed
lanes, the default is enabled unless the adapter says otherwise.

## Authority

- The project adapter controls whether Graphify is enabled.
- Graphify output is navigation evidence, not process authority.
- Canonical methodology and the generated adapter still decide planning,
  review, delivery, and RCA process.
- Stale Graphify output must not be used for decisions.

## Preferred Navigation

When Graphify is enabled and either `graphify-out/GRAPH_REPORT.md` or
`graphify-out/graph.json` exists:

1. Read `graphify-out/GRAPH_REPORT.md` first for broad architecture
   orientation.
2. Use `graphify query`, `graphify path`, or `graphify explain` for
   architecture, dependency, call-flow, feature-map, and "where does this live"
   questions before broad `rg`/grep scans.
3. Use `rg` for exact lexical searches, small known-file lookups, when Graphify
   is missing, or while rebuilding after a failed refresh.
4. Prefer Graphify when it can reduce token-heavy source dumping.
   Do not paste large graph output into chat; summarize the relevant
   edges/files and then inspect only the narrow files needed.

## Freshness

- After every code, docs, schema, route, test, architecture, or other system change, run `graphify update .` before relying on existing Graphify output, committing, or pushing. This is the no-LLM AST refresh: no API key, no backend, no external model.
- Semantic enrichment (community labels, `GRAPH_REPORT` prose) is a separate NON-blocking step: `GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli`, run only when enrichment is wanted. Its failure never blocks commit or push, and a Graphify invocation that auto-detects its backend is never a gate command.
- If Graphify output exists and any tracked or unignored project file is newer
  than the latest Graphify artifact, the graph is stale. Stale graph output is blocking drift and must not be used for decisions.
- If update fails, treat existing graph output as invalid stale evidence and
  fall back to narrow `rg`/file reads only until the graph is rebuilt.
- Do not block small exact text lookups on a Graphify refresh when `rg` is the
  right tool.

`graphify-status --target . --strict` and
`methodology-status --fail-on-drift` are the status surfaces that report stale
or tracked generated output. The next action for stale output is to run
the adapter's configured update command (default `graphify update .`) before
commit, push, or Graphify-backed decisions. Those surfaces print the CONFIGURED
command, so a project override and the gate can never disagree.

Freshness is a decision gate, not a ceremonial command. If a source, docs,
schema, route, test, config, generated adapter, or architecture file changed
after the latest Graphify artifact, do not cite the existing graph as current
architecture evidence. Refresh it first, or explicitly fall back to narrow file
reads and lexical searches until the refresh succeeds.

Small exact searches are different: looking up a literal symbol, filename, or
known string with `rg` does not require a graph refresh. The boundary is whether
the lane is relying on Graphify for dependency, ownership, call-flow,
architecture, or feature-map claims.

## Install And Build

- Install through the methodology CLI when asked:
  `tautline graphify-install --target .`.
- Build manually when needed: `graphify update .` (it cold-builds from nothing).
- Update after changes: `graphify update .`.
- Label communities when semantic enrichment is wanted (never a gate):
  `GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli`.
- Do not run `graphify claude install`, `graphify codex install`, or other
  assistant project installers unless the adapter explicitly allows Graphify to
  manage assistant files and the human asked for that exact installer.
  Minervit owns generated `CLAUDE.md` and `AGENTS.md`.

## Git Hygiene

- `graphify-out/` is generated local output.
- It must be ignored and must not be committed.
- If `methodology-status --fail-on-drift` reports tracked or stale Graphify
  output, remove tracked output or refresh stale output before continuing with
  project work.
- If generated output was accidentally tracked, remove it from Git while leaving
  local ignored files alone when useful for navigation.

## Boundaries

Graphify helps choose what to inspect; it does not replace reading source files,
running tests, updating derived artifacts, or following review gates. Use it to
reduce broad scans, then verify behavior in the relevant files and command
outputs.
