## Document Context Budget

- Markdown context is routed through configured indexes. Read the adapter, continuity handoff, execution packet, context indexes, and adapter readiness sources first.
- Do not broad-load Markdown trees, all plans, all docs, or archive directories for routine startup context. A bounded Markdown audit must name the question, target files or globs, and an upper bound of 20 Markdown files unless source-of-truth scope or explicit human instruction authorizes more.
- Archived or historical docs are evidence only. They are not current process, scope, execution authority, or next-work authority. Historical paths need the canonical historical header before strict enforcement.
- When creating, completing, moving, or archiving Markdown work artifacts, update the context index before workflow completion. Explicit `documentContext` paths must be project-relative or home-relative (`~`), not absolute workstation paths.
- `context-bootstrap` creates indexes, classifies tracked Markdown candidates, and adds archive headers; it must not move docs automatically. `documentContext.enforcement` defaults to `warn`.
- `context-status --strict` fails for missing indexes, oversized indexes, unclassified tracked Markdown, missing archive headers, or generated adapter drift. `methodology-status --strict --fail-on-drift` temporarily enforces document-context strictness during migration without changing the adapter.
- Strict mode validates filesystem and index state. It is not a runtime read sandbox. Agents still follow generated adapter and `context-continuity` skill loading rules.
- Use the `context-continuity` skill for detailed loading, audit, archive, index-hygiene, handoff, and context-rotation behavior.
