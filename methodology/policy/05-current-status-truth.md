## Current Status Truth

- When the human operator asks for current project status, completion, next work, or anything another lane may have changed, fetch and inspect latest-code before answering. Run `minervit-methodology latest-code-status --target . --write` unless a fresh `.ai-work/LATEST_CODE_BASELINE.json` exists.
- Before deep codebase analysis, architecture review, multi-angle analysis, planning, implementation, review, tactical subagent dispatch, or product-decision work, establish a latest-code baseline. Do not run deep analysis from a stale local checkout.
- Latest-code means fetched base plus remote branches/open PRs ahead of base that may be active, deployed, or visible. Answer from remote, PR/check, deploy/build, and source-of-truth evidence before trusting local state.
- If the lane is behind, dirty, detached, or on a PR branch, say so. A stale local lane may be useful evidence about that lane only, not the current project answer.
- Pull/rebase/switch only when preparing to work in that lane. For read-only status, fetch and inspect remote evidence without mutating unrelated lane work. Local-only projects use adapter-declared local truth, not stale lane files.
- Tool-blocking freshness guards must leave an in-band escape. `latest-code-status --write` records remote state, falls back during adapter drift, surfaces `latest_code_adapter_drift`, and permits `render-adapters`; it must not hard-block benign CLI-resolution probes, `git config`, `cd`, or `echo`.
