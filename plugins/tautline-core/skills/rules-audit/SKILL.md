---
name: rules-audit
description: Compatibility alias for framework-intake. Audit Claude, Codex, Cursor, automation, memory, and project rule surfaces for drift.
---

# Rules Audit

This is a compatibility alias. Use `framework-intake` for new work.

Read `references/rules-audit-policy.md`, which forwards to the single-source
`framework-intake` policy, before classifying process authority, auditing stale
memories, validating review prompts, checking plan/review loops, or deciding
whether a rule surface is current.

## Fast Path

1. Start from canonical methodology, active generated adapters, and skill
   references; memory is evidence only.
2. Compare only the named surfaces or adapter-declared rule files in scope.
3. Flag hidden process, stale lane references, conflicting instructions,
   optionalized required gates, broad Markdown loading, and incident-era prose.
4. Separate findings into blocking process drift, cleanup tasks, and historical
   evidence that should not load routinely.
5. For generated files, update the source adapter or methodology and rerender;
   do not hand-edit generated output.

## Non-Negotiables

- Do not treat Open Brain, Claude memories, local memories, or old docs as
  process authority.
- Do not broaden an audit into unrelated repo discovery.
- Do not add new phrase/tone rules; new enforcement belongs in state checks and
  telemetry.

## Required Follow-Through

Load the forwarded reference for the full drift taxonomy, shippable-surface
checks, process-authority rules, and remediation sequence before changing rules.
