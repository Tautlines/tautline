---
name: example-service-preflight
description: "Apply stack-specific preflight gates for a Make/CI-driven API service: main status, open PR check, fast preflight, full preflight, Gherkin coverage, security invariants, and GitHub-only readiness automation."
---

> EXAMPLE / STACK-SPECIFIC SKILL. This is a worked example for one project stack
> (a Make/CI-driven API service) and is slated to move to a community examples
> plugin. It is not part of the portable methodology core;
> adopt its shape and adapt the commands/env vars to your own stack.

# Service Preflight

Use this skill inside an Example API service that uses a `make`-driven preflight
and CI. Replace the `make` targets and env-var names below with the equivalents
your project actually defines.
Read `references/example-service-preflight-policy.md` in full before applying
the stack-specific gates.

## Gate Summary

- Session start checks `make ci-status-main`, active-agent open PRs, branch
  liveness, and merge conflict risk against `origin/main`.
- Before commit, run `tautline lane-run --target . -- make pf-fast`.
- Before commit, review, push, or tactical subagent dispatch on an existing PR
  branch, run `tautline branch-liveness-check --target . --strict`.
- Before push, run the isolated test environment and full preflight through
  `lane-run`: `make test-env-up`, then `make preflight`.
- Use the project's wrapped Codex review script, not bare `codex review`.
- Clean queued PRs do not need active monitoring; queued/merged/closed branches
  are inactive for additional commits.

## Isolation

Use `.ai-work/lane-env.sh` through `lane-run` for per-lane port/env isolation.
If a bare command hits a port-in-use failure, rerun the same gate through
`lane-run` before escalating.

## Blocking Checks

- Customer-facing behavior requires Gherkin unless `GHERKIN-EXEMPT: <reason>`
  is in the commit message.
- Missing tests for new functions, endpoints, or pages are Critical.
- Secrets must never be returned, logged, or stored plaintext.
- Tenant endpoints must enforce tenant isolation.
- Do not combine FastAPI `@limiter.limit` with `response_model=`.
