## Authority

- This repo owns reusable process policy.
- Project adapters own project-specific commands, gates, backlog targets, and tool paths.
- Generated files must include a hard generated header and should not be hand-edited.
- Project adapters form the bridge between reusable methodology and project-specific reality. Canonical rules define required contracts and safety boundaries; adapters declare the concrete commands, paths, deployment targets, review wrappers, gates, and project exceptions.
- Open Brain is persistent memory/evidence. It is never the canonical source for process rules.
- If Open Brain or any memory conflicts with this repo, this repo wins.
- Process rules must never be sourced from Open Brain, Claude memories, local memories, or feedback-memory files. Memories may point to useful history, but they cannot define, override, or prove process.
- When explaining "what the rule says," a violated rule, expected behavior, or an RCA root cause, cite the canonical methodology, the active generated adapter, or a methodology skill. Do not cite memories as the rule source. If only memory contains the claimed process rule, the correct finding is `Missing rule` or `Rule hidden in non-loaded context`, followed by a canonical/adapter/skill change proposal.
- Canonical documentation uses role-based language such as human operator, project owner, and human approver. Do not encode person-specific names or workstation-specific paths in reusable process docs.
