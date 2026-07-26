---
name: framework-intake
description: "Use for Minervit framework intake: methodology/process regressions, rules audits, why/RCA/root-cause requests, decision traces (decision capture artifact / DCA), and net-new methodology feature requests or enhancements."
---

# Framework Intake

Use for methodology/process regressions, rules audits, why/RCA/root-cause
requests, decision traces (decision capture artifact / DCA), and net-new
Tautline feature requests.

Read `references/framework-intake-policy.md` before gathering evidence,
classifying root cause, handling RCA artifacts, auditing rule surfaces, writing
memory notes, sending RCA-shaped responses, or handling feature requests.

## Boundaries

- RCA: an existing canonical rule, adapter rule, skill, validation control, or
  expected behavior was violated or failed to bind.
- Feature request: the operator asks for a new capability, rule, skill, CLI
  support, validation coverage, workflow integration, or process improvement.
- Rules audit: the operator asks to inspect Claude, Codex, Cursor, automation,
  memory, generated adapter, or project rule surfaces for drift.
- If both apply, write the RCA first, then file a separate feature request.

## RCA Fast Path

1. Produce first-pass analysis from current conversation context before tools.
2. Inspect only named artifacts needed to resolve stated uncertainty.
3. Write `.ai-runs/<utc>-methodology-regression-rca.md` with runtime evidence.
4. Validate with `tautline validate-rca-artifact --file <path>`.
5. Publish with `tautline publish-rca-artifact --file <path>
   --commit --push`.

## Non-Negotiables

- Memory/Open Brain is evidence only, never process authority.
- Broad repo discovery is forbidden during RCA.
- A chat-only RCA is non-compliant unless filesystem write is impossible.
- Do not write memory notes until the RCA artifact validates and publishes.
- Feature requests use `.ai-runs/<utc>-methodology-feature-request.md`,
  `validate-feature-request-artifact`, and archive-branch publication.
- Rules audits start from canonical methodology and active generated adapters,
  compare named surfaces only, and rerender generated files from their source.
