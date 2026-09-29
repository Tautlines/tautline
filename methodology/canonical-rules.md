# Tautline Canon (lean)

Adopted 2026-08-28 after the process-bankruptcy audit. This file replaces the prior 83KB rulebook; the old text is archived under docs/archive/.

1. The test suite is the gate. `scripts/test.sh` green is required to merge; CI runs it plus a fresh-checkout leg.
2. One adversarial review before merge. Fix Critical/P1 findings; merge. No review rounds, budgets, or ledgers. If findings cluster, the diff is too big or the design is wrong — decompose.
3. Failing test first; small diffs; one-page specs pulled from the top of the backlog queue.
4. Security is absolute: never commit secrets or customer data; sanitization checks stay in CI and at release.
5. Releases are batched scripts run when there is something to ship. A release must not break deployed users — the upgrade-path e2e proves the transition, every release.
6. Agents work in isolated worktrees; `tautline lane-status` is advisory and never blocks.
7. Every control pays rent: measure defects caught and time lost to false blocks. Coordination and continuity tools earn their place by reducing duplicate work, failed handoffs, and operator effort. Preserve delivery speed. Incidents are answered with a test, not a rule.
