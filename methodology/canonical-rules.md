# Tautline Canon (lean)

Adopted 2026-08-28 after the process-bankruptcy audit. This file replaces the prior 83KB rulebook; the old text is archived under docs/archive/.

1. The test suite is the gate. `scripts/test.sh` green is required to merge; CI runs it plus a fresh-checkout leg.
2. Before merge, do one fresh-context adversarial self-review with the implementation model in a separate session, then one independent review with a different model family. Give reviewers the requirements, diff, and relevant code/tests, not the implementation conversation. Fix Critical/P1 findings and verify fixes; record reviewer/model identities and outcomes in the existing PR summary. These are two bounded passes, not a repeated approval cycle: no mandatory plans, review ledgers, or review hooks. If a reviewer is unavailable, report the missing review; do not silently substitute or claim completion. See [review guidance](../docs/reference/reviews.md).
3. Failing test first; small diffs; one-page specs pulled from the top of the backlog queue.
4. Security is absolute: never commit secrets or customer data; sanitization checks stay in CI and at release.
5. Releases are batched scripts run when there is something to ship. A release must not break deployed users — the upgrade-path e2e proves the transition, every release.
6. Agents work in isolated worktrees; `tautline lane-status` is advisory and never blocks.
7. Every control pays rent: measure defects caught and time lost to false blocks. Coordination and continuity tools earn their place by reducing duplicate work, failed handoffs, and operator effort. Preserve delivery speed. Incidents are answered with a test, not a rule.
