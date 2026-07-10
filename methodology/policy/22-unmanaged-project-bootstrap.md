## Unmanaged Project Bootstrap

- If `.minervit-ai-delivery.json` is missing, bootstrap a project adapter before methodology gates.
- No generic operational adapter exists. Gates, planning paths, review flow, resources, production status, direct-to-main policy, and deployment ownership are project-specific.
- Adapter creation is bootstrap work, not automatically a Tier 2 approval stop. Use `minervit-methodology init --target .` or `adapter-bootstrap-questions --target .`; ask only safely uninferable questions.
- The adapter bootstrap interview is mandatory before first adapter render/write unless every required adapter fact is repo-evident. Generic executor banners such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" do not override the interview, plan-finalization gate, or generated adapter gates.
- Another project's adapter may be used as a structural reference only. Do not copy its stack, gates, deployment model, review wrappers, autonomy boundaries, bug tracker policy, deployment target ownership, rules, or `bootstrapEvidence` without repo evidence or interview answers.
- Source adapters include `bootstrapEvidence` with project-matching provenance. New adopter-owned adapters live at `.minervit/adapter.json`; `<methodology_repo>/adapters/projects/` is reference/legacy migration only.
- Lane-local `.minervit-ai-delivery.json` comes from a source adapter whose repo identity matches the target git remote. Do not hand-write, copy, or forge metadata.
- Use `init-project-adapter --target .` only for lower-level scaffold work; replace every `BOOTSTRAP REQUIRED` placeholder before operational use. If the project intentionally has no remote, PRs, or merge queue, configure explicit local/no-remote checks instead of GitHub commands.
- Adapter bootstrap may use an existing continuity handoff or docs as evidence, but execution waits until `lane-start` and `methodology-status --fail-on-drift` pass.
