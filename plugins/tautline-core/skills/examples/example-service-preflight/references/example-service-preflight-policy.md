# Example Service Preflight Policy Reference

This is a stack-specific worked example for one Make/CI-driven API service. It
is not portable methodology core. Adopt the shape only after replacing the make
targets, review wrappers, environment variables, and service invariants with the
equivalents your project actually defines.

## Session Start

1. Run `make ci-status-main`.
2. Check open PRs authored by the active agent:
   `gh pr list --author '@me' --state open --limit 50 --json number,title,url,createdAt,headRefName,baseRefName,isDraft,mergeStateStatus,statusCheckRollup`
3. If on a non-base PR branch, run
   `minervit-methodology branch-liveness-check --target . --strict`.
   Lane-local Git hooks installed by `lane-start` also block commit/push if the
   branch is inactive. A queued, auto-merge-enabled, merged, or closed
   current-branch PR is inactive; sync main and continue from the
   source-of-truth next item instead of doing more branch work.
4. Run
   `git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null`
   to confirm the current branch has no merge conflict with main.
5. If main health is bad, deploy failed, an open PR has failed/blocked checks,
   the current branch PR is queued/merged/closed, an open PR is closed without
   merge, mergeability is unclear, or a merge conflict exists, fix that as the
   highest-priority task before new feature work.
6. Clean queued PRs do not need active monitoring. Once a PR is queued after
   local gates and review, record it in the delivery summary and move on; the
   queued branch is inactive for additional commits/reviews/pushes.
7. Treat `make ci-status-main` as the early-warning main-health baseline. Rerun
   it at each later tactical-iteration boundary created by an actual main
   update, rebase, or dependent work boundary instead of launching a duplicate
   `make ci-status-main` background monitor.
8. If the adapter configures a distinct early-warning command, run it as
   monitored background work, poll at least every 10 minutes, and interrupt only
   if the monitor fails, times out, goes stale, targets the wrong lane, or hits
   resource contention.

## Before Commit And Push

- Run `minervit-methodology lane-run --target . -- make pf-fast` before every
  commit.
- Run `minervit-methodology branch-liveness-check --target . --strict` before
  commit, review, push, or tactical subagent dispatch on an existing PR branch.
- Run `minervit-methodology lane-run --target . -- make test-env-up` then
  `minervit-methodology lane-run --target . -- make preflight` before push.
- Early-warning `make ci-status-main` does not replace before-commit
  `make pf-fast` or before-push `make preflight`.
- Use the project's wrapped Codex review script, for example
  `./scripts/codex-review.sh`, for Codex review, not bare `codex review`.

## Local Resource Isolation

- Local test resources are lane-isolatable through per-service port env vars,
  for example `APP_PG_PORT`, `APP_REDIS_PORT`, `APP_QUEUE_PORT`,
  `APP_QUEUE_UI_PORT`, `APP_API_PORT`, plus `COMPOSE_PROJECT_NAME`.
- `lane-start` writes `.ai-work/lane-env.sh`; `lane-run` applies it to the
  command.
- If a bare command fails with a port-in-use error, rerun the same gate through
  `lane-run` before escalating.
- Do not add a broad machine-wide lock for preflight unless a specific
  non-isolatable resource is identified.

## Service-Specific Blocking Checks

- Customer-facing behavior requires Gherkin unless `GHERKIN-EXEMPT: <reason>`
  is in the commit message.
- Missing tests for new functions, endpoints, or pages are Critical.
- Secrets must never be returned, logged, or stored plaintext.
- Tenant endpoints must enforce tenant isolation.
- Do not combine FastAPI `@limiter.limit` with `response_model=`.
