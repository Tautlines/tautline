# Usage Accounting Policy Reference

This reference keeps detailed local AI usage accounting policy behind the
concise `usage-accounting` skill entrypoint.

## Purpose

Use this policy when the human operator asks about token or AI spend, when a
lane reaches a startup, review, PR, milestone, goal, context-rotation, or
session boundary, or when provider/host usage metadata is available.

Usage accounting is local operational evidence for understanding AI spend by
product, lane, goal, milestone, model, activity, and timeframe. It is not
process authority, product documentation, a continuity handoff, a session
journal, or approval evidence.

## Authority

- Usage records are evidence only.
- Do not write usage files directly. Use the methodology CLI so records are
  validated, deduplicated, rotated, and tagged with confidence.
- Never present estimates as exact.
- Exact values require provider or host usage data.
- Human-entered, inferred, or reconstructed values must be marked
  `estimated`.
- Missing cost remains `unknown`.
- Every usage record must carry a `source` and `confidence` value: `exact`,
  `estimated`, or `unknown`.

## Commands

Locate usage files:

```bash
minervit-methodology usage-log-path --target .
```

Record a known or estimated usage snapshot:

```bash
minervit-methodology usage-record --target . --provider <provider> --model <model> --activity <activity> --source <source> --confidence <exact|estimated|unknown> --total-tokens <n>
```

Import Claude Code JSONL usage when the session file is available:

```bash
minervit-methodology usage-import-claude --target . --path <claude-session.jsonl> --since 7d --activity <activity>
```

Report usage:

```bash
minervit-methodology usage-report --target . --since 7d --by product
minervit-methodology usage-report --target . --since 7d --by activity
minervit-methodology usage-report --target . --since 7d --by model
```

## Recording Rules

Record usage at meaningful boundaries when data is available:

- startup
- plan-review round
- implementation or code-review round
- PR queue or merge
- milestone completion
- goal completion
- context rotation
- session closeout

Include `goal`, `milestone`, `pr`, `session-id`, or `request-id` when known.
If cost is unavailable, omit cost fields and report the missing cost as
`unknown`. Do not calculate price unless the pricing source and model mapping
are explicit in the same work.

Local usage JSONL stays in
`$HOME/.local/state/minervit/usage/<repo-slug>/`. Do not commit it to the
product repo.

Usage records should identify the work without exposing secrets or customer
private data. Use stable issue, PR, goal, milestone, session, or request
identifiers when they are safe to store locally. Do not put prompts, API keys,
webhook URLs, raw customer data, private transcripts, or long terminal output in
usage records. If a source identifier itself is sensitive, replace it with a
non-sensitive local reference and state the limitation in reporting.

Use the most specific `activity` that reflects the work being measured, such as
startup, plan-review, implementation, code-review, PR, milestone, goal,
context-rotation, session-closeout, or support investigation. Avoid vague
activities that make later rollups useless.

## Import And Reconstruction

Prefer provider or host usage metadata over manual estimates. Use
`usage-import-claude` for Claude Code session JSONL files when available rather
than hand-entering records. Imported records must still deduplicate by stable
record identity and must retain their source and confidence fields.

Do not mine unrelated logs unless the user explicitly asks for reconstruction.
If reconstruction is requested, state the source logs inspected, the confidence
level, and what could not be recovered. Reconstructed values are not exact
unless the underlying provider/host metadata is exact.

## Reporting Rules

Start with plain English:

- what product spent the most
- which activity drove usage
- which model drove usage
- whether the numbers are exact, estimated, incomplete, or machine-local only

State the coverage gap when records are missing, machine-local only, cost is
unknown, or the timeframe excludes known work. Use `usage-report` output as
evidence and cite the grouping used, such as `--by product`, `--by activity`, or
`--by model`.

Do not present usage totals as organization-wide spend unless the evidence
actually spans all relevant machines, products, providers, and timeframes.
