---
name: graphify-navigation
description: Use adapter-enabled Graphify graph/report/query/path/explain for token-efficient codebase navigation, keep graph output fresh, and prevent generated Graphify output from entering git.
---

# Graphify Navigation

Use when a repo adapter enables Graphify and codebase navigation, impact
analysis, or dependency tracing would otherwise require broad grep/read loops.

Read `references/graphify-navigation-policy.md` before building, updating,
using, committing around, or ignoring Graphify output.

## Fast Path

1. Check `methodology-status` or adapter output for Graphify enablement and
   output paths.
2. If current output exists, use Graphify report/query/path/explain before broad
   source scans.
3. If output is missing and graph context is needed, run `graphify update .` or
   the adapter-approved build command; it cold-builds with no LLM backend.
4. After code changes, run `graphify update .` -- the no-LLM refresh, and the
   only Graphify invocation the blocking freshness gate ever names.
5. Semantic labeling is a separate NON-blocking step with an explicit backend:
   `GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli`.
6. Keep `graphify-out/` generated and out of git.

## Non-Negotiables

- Do not run `graphify claude install` or `graphify codex install` inside
  product repos.
- Do not commit generated graph output.
- Stale graph output cannot justify current code claims.

## Required Follow-Through

Use the reference for freshness, generated-output handling, adapter enforcement,
and fallback navigation rules.
