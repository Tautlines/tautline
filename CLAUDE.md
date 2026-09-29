# Tautline

Reusable AI delivery framework. Integration branch: `experimental` (base branches and PRs on it); `main` is the stable channel, promoted from `experimental`.

## Build & test
- Gate: `scripts/test.sh` (Python 3.12 — CI is 3.12-only; 3.13 falsely reddens byte-compared goldens).
- CLI lives in `src/tautline_methodology/`; `bin/tautline` is a thin shim.

## Process — this is the whole process
- Take the top backlog item; specs are one page.
- Failing test first; small diffs.
- One adversarial review before merge; fix Critical/P1; merge.
- Never commit secrets or customer data.
- Releases are batched scripts, run when there is something to ship; a release must not break deployed users (`tests/test_upgrade_path_e2e.py` proves the transition).
- Every control pays rent: measure catches and false blocks; judge coordination by time saved. Preserve delivery speed. Incidents are answered with a test, not a rule.
- Backlog: `tautline backlog list`; file follow-ups there and include `Backlog: <id>` in PRs.
- At startup or before new work, read `tautline work status`. Declare scope before parallel work; update or finish the declaration as scope changes or work ends. Conflicts are advisory.
- Read `.ai-continuity/HANDOFF.md` if present. Refresh it at useful checkpoints. When notified of an operator answer, read `tautline inbox --answers` and acknowledge it after incorporation.

Process history (plans, review ledgers, RCAs) is archived read-only under `docs/archive/` and `docs/archive-prebankruptcy/` — reference, not authority.
