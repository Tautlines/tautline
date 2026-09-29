# Control ledger

Canonical rule 7 (`methodology/canonical-rules.md`): every control pays rent. Measure catches
against false blocks and time lost. Coordination and continuity tools earn their place through
less duplicate work, successful handoffs, and less operator effort. Preserve delivery speed.

Rows record observed value, not additional approval requirements. Pending means evidence has
not yet been collected; it is not a reason to block a session, PR, or release.

## Rules

- Keep safety controls when real catches justify their cost and false blocks.
- Keep utilities when they save time. They do not need to block an action to be useful.
- Answer incidents with focused tests; do not add review rounds or required plans.

## Ledger

| Control or utility | Since | Evidence of value | Verdict |
|---|---|---|---|
| Test gate — `scripts/test.sh` green required to merge (canonical rule 1) | pre-2026-08-28 | — | pending first review |
| Fresh-checkout leg — `fresh-install-smoke` installs the built wheel where no Tautline checkout has ever run (`.github/workflows/ci-python-full.yml`; canonical rule 1) | pre-2026-08-28 | — | pending first review |
| Upgrade-path e2e — every release proves the deployed-checkout transition (`tests/test_upgrade_path_e2e.py`; canonical rule 5) | pre-2026-08-28 | — | pending first review |
| One-review norm — one adversarial review, Critical/P1 fixed, before merge; no rounds, budgets, or ledgers (canonical rule 2) | pre-2026-08-28 | 2026-08-29/30 Tier-1 batch, one pass per PR: silent 2KB-cap overflow (#620), terminal injection via the ts field (#622), backup protocol destroying originals after a crash (#623), unscanned `--stakeholder` field posting secret-shaped text (#624), interview EOF traceback (#619) — all reproduced, fixed pre-merge | earning |
| Secret scan — redacts webhook URLs, key/token/secret query params, and secret-suffixed env values at every sink (`redact_secrets` in `src/tautline_methodology/util.py`; gated by `tests/test_secret_redaction.py`; canonical rule 4) | pre-2026-08-28 | — | pending first review |
| Verb guards — the generated adapter and the refusal continuations stay in sync with the registered verb set (`tests/test_generated_adapter_contract.py`, `tests/test_refusal_continuations.py`) | pre-2026-08-28 | — | pending first review |
| Contract-manifest freshness — the committed manifest must match a live regeneration per command (`tests/test_public_contract_freshness.py`) | 0.147.0 (#622) | caught its target class twice in its first day: #624's hand-edited labels reverting on regen, then #623's identical hand-edit | earning |
| `decisions-report` — queries the decision-record ledger by date range, reversibility, and free text (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| `event-tail` / `event-log-path` — tails or locates the same ledger (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| `inbox` — pending decisions with explicit answer delivery until acknowledgement | 0.147.0; answers in 0.148.0 | Roundtrip, repeated delivery after resume, and source-lane isolation verified; operator time saved still to measure | observe real use |
| `github-budget-status` — read-only GitHub rate/GraphQL budget and identity report (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| `stakeholder-question ask` / `list` — tagged GitHub-issue questions, secret-scanned before posting (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| `doctor` — branch-liveness, framework-staleness, skip-lint, and monitor-liveness advisory checks (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| `red-green-check` — mutates a named symbol, confirms the given test command kills it, restores the original (Tier-1 reclaim) | 0.147.0 (2026-08-30) | — | pending first review |
| PR<->backlog reference check — `scripts/check_pr_backlog_ref.py`, active only when a backlog provider is configured | 0.148.0 | Framework config now enables the existing check; no additional review step | observe real use |
| Shared work declarations — advisory, local by default, optional Git sharing, no edit or merge lock | 0.148.0 | Sibling-worktree and independent-clone discovery, concurrent pushes, offline recovery, overlap, stale/crash handling verified; duplicated effort avoided still to measure | observe real use |
| Optional execution receipts and health reports | 0.148.0 | Fresh/stale/interrupted results and unknown health are distinguished; never an extra merge gate | observe real use |

0.147.0 landed on the development channel in August. The next public release carries the lean
workflow and recovery features to adopters. Evaluate their value during ordinary use, without a
separate review ceremony.
