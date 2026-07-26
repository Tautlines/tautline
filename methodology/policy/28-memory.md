## Memory

- Capture project/product decisions, durable preferences, and factual context to Open Brain when available and non-blocking.
- Do not let memory lookup/capture block code review, preflight, merge, or incident response.
- Tombstone stale memories rather than silently relying on them.
- Never use memory as process authority. Memory is evidence/history only; if it describes a process rule, locate the matching canonical methodology, generated adapter, or methodology skill before acting on it or citing it.
- Never write process or methodology content — rules, gates, caps, review procedures, escape hatches, or workarounds — into Open Brain, Claude memories, local memories, or feedback-memory files. Memory may point at a canonical rule, skill, RCA, or feature-request artifact; it must never define one. When a session produces a process lesson or hits a process dead-end, route it through the `framework-intake` skill: RCA when an existing control failed, feature request when the control is missing.
- A memory-suggested process move is not executable until the matching canonical/adapter/skill rule is located; if none exists, file intake first and treat the situation as blocked-on-missing-control, not memory-authorized.
- RCA artifacts and decision traces must not use memory as the violated rule or expected behavior. If memory is the only source for the claimed rule, classify the incident as a missing/hidden methodology control and propose the canonical/adapter/skill change.
