---
name: usage-accounting
description: Record, import, and report confidence-tagged local AI token and cost evidence by product, lane, goal, milestone, model, activity, and timeframe.
---

# Usage Accounting

Use for token or AI spend questions, startup/review/PR/milestone/goal/session
boundaries, or available provider/host usage metadata.

Read `references/usage-accounting-policy.md` in full before recording,
importing, reconstructing, or reporting usage evidence.

## Authority

- Usage records are evidence only. They are not process authority, product docs, continuity handoffs, or session journals.
- Do not write usage files directly. Use the methodology CLI so records are validated, deduplicated, rotated, and tagged with confidence.
- Never present estimates as exact. Exact values require provider/host usage data. Human or inferred values must be `estimated`; missing cost remains `unknown`.

## Required Commands

- Locate files:
  ```bash
  tautline usage-log-path --target .
  ```
- Record usage:
  ```bash
  tautline usage-record --target . --provider <provider> --model <model> --activity <activity> --source <source> --confidence <exact|estimated|unknown> --total-tokens <n>
  ```
- Import Claude Code JSONL usage:
  ```bash
  tautline usage-import-claude --target . --path <claude-session.jsonl> --since 7d --activity <activity>
  ```
- Report usage:
  ```bash
  tautline usage-report --target . --since 7d --by product
  tautline usage-report --target . --since 7d --by activity
  tautline usage-report --target . --since 7d --by model
  ```

## Recording Rules

- Record usage at meaningful boundaries when data is available: startup, plan-review round, implementation/code-review round, PR queue/merge, milestone completion, goal completion, context rotation, and session closeout.
- Include `goal`, `milestone`, `pr`, `session-id`, or `request-id` when known.
- Do not calculate price unless the pricing source and model mapping are explicit in the same work.
- Local usage JSONL stays in `$HOME/.local/state/minervit/usage/<repo-slug>/`. Do not commit it to the product repo.

## Reporting Rules

- Start with plain English: what product spent the most, which activity/model drove usage, and whether the numbers are exact or incomplete.
- State the coverage gap when records are missing, machine-local only, or cost is unknown.
- Use `usage-report` output as evidence; do not mine unrelated logs unless the user explicitly asks for reconstruction.
