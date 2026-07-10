## Methodology Repository Governance

- The methodology repository is centrally governed. Non-owner lanes propose reusable changes by PR; `main` is protected product surface, not an evidence dump.
- Do not commit directly on local methodology `main`. If it diverges from `origin/main`, run `minervit-methodology repair-methodology-main`. Direct pushes to `main` are methodology-owner break-glass only and must document the reason.
- Adapter JSON-only changes are project configuration, not reusable releases. Bump release metadata only when reusable framework surfaces change. Agents must not stop to ask whether to cut a methodology release for an adapter-only PR.
- Methodology regression RCA artifacts and ops-owned improvement evidence do not belong on `main`. Publish archive evidence through the owning archive command/skill; archive publication must not mutate the active methodology release checkout. Active-checkout writes require `--allow-release-checkout-write`.
- Ops-owned delivery communications, deployment notifications, milestone updates, product notes, event logs, usage evidence, and session journals are optional adapter-enabled capabilities. The ops plugin owns provider-specific procedure, delivery markers, and publication detail.
- End-of-goal close is a checklist, not a permission question. Reviewed clean work is committed, pushed, deployed/reviewed when required, advanced in ledgers, continuity/journaled, and continued. Routine push of reviewed work to the configured remote is `Done = shipped`.
- Production/staging/demo deployment closeout is agent-owned when the adapter, source-of-truth plan, execution packet, or closure criterion says work ships there. Stop only for named missing access, unfixable gates, or unapproved scope/risk/cost/security/data changes.
- Methodology CLI resolution is product-isolated. A lane resolves to its product's pinned methodology checkout, not unrelated machine-wide dev checkout; lane-lifecycle owns launcher/shim fallback.
