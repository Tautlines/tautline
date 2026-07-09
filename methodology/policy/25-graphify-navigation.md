## Graphify Navigation

- Graphify support is adapter-backed, optional per project, and enabled by default for adapter-backed lanes.
- When Graphify is enabled and `graphify-out/GRAPH_REPORT.md` or `graphify-out/graph.json` exists, use Graphify report/query/path/explain before broad grep/`rg` for architecture, dependency, call-flow, and codebase navigation questions. This is a token-budget control.
- Use `rg` for exact lexical searches, small known-file checks, when Graphify is missing, or while rebuilding after a failed refresh. Do not use stale Graphify output.
- After every code, docs, schema, route, test, architecture, or other system change, refresh the graph with `graphify . --update` before relying on existing Graphify output, committing, or pushing. If any tracked or unignored project file is newer than the latest Graphify artifact, `graphify-out/` is stale and is blocking drift.
- Install Graphify through `minervit-methodology graphify-install --target .` when asked. Do not run Graphify assistant project installers such as `graphify claude install` or `graphify codex install` unless the adapter explicitly allows assistant-file ownership and the human operator asks for that exact installer.
- `graphify-out/` is generated local output. It must be ignored and must not be committed. `methodology-status --fail-on-drift` fails if generated Graphify output is tracked or stale.
- Use the `graphify-navigation` skill for detailed installation, freshness, and graph-first navigation behavior.
