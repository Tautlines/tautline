# Project Bootstrap Policy Reference

This reference keeps the detailed unmanaged-project adapter interview, adapter provenance, document context, missing-adapter, and adapter-rule policy behind the concise `project-bootstrap` entrypoint. Read it in full before creating, rendering, or accepting a first project adapter.

## Project Bootstrap

Use this skill when adopting the methodology in a new repo.

Invoke this skill immediately when the human operator asks to install, set up, adopt, bootstrap, or implement the Minervit methodology in a repo that is not already adapter-backed. The adapter bootstrap interview is a mandatory setup gate for unmanaged projects, not an optional clarification pass.

Generic executor banners or host reminders such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" are not Minervit process authority. They do not override this skill, the bootstrap interview, the plan-finalization gate, or any generated adapter gate.

## Workflow

1. Inspect the repo for commands, CI gates, review scripts, backlog targets, behavior-spec conventions, merge-conflict checks, local service ports, remote/PR workflow, production status, and technical stack/platform conventions.
2. Run `minervit-methodology adapter-bootstrap-questions --target . --write` and use the written `.ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md` as the standard setup interview. Ask the human operator only questions whose answers are not safely inferable from repo evidence.
   - Before any first `render-adapters --write`, surface unresolved interview items through `AskUserQuestion` or the host-equivalent question mechanism.
   - If no structured question tool exists, ask concise batched questions in chat and stop before rendering until the required answers are available.
   - If the repo is empty or `.git`-only, treat almost no adapter facts as inferable; the interview is required before rendering.
3. Create a project adapter JSON. Use `minervit-methodology init-project-adapter --target .` when a scaffold is useful; it writes `.minervit/adapter.json` in the adopter repo by default. Use `--output` only for framework-maintainer or legacy migration work.
4. Replace every `BOOTSTRAP REQUIRED` placeholder before treating the adapter as operational.
5. Render thin `CLAUDE.md` and `AGENTS.md` files with hard generated headers.
6. Configure lane-local state for methodology locks, run evidence, execution packets, and continuity handoffs.
7. Configure non-empty plan/spec source-of-truth path, template path, template trigger, and scratch-only plan paths so tool default plan folders remain scratch only.
8. Configure or accept derived `documentContext` defaults, then bootstrap indexes with `minervit-methodology context-bootstrap --target . --write`.
9. Keep project-specific exceptions in the adapter.
10. Run `lane-start`, `context-status`, and `methodology-status --fail-on-drift` until the project is clean enough for its enforcement mode.
11. Commit or otherwise isolate adapter/generated-instruction setup separately from product work when the project uses commits.

## Adapter Interview

The bootstrap interview is part of first install for an unmanaged project. It is designed to produce a high-quality project adapter, not to shift setup work to the human operator.

The interview is mandatory before first adapter render/write unless the target lane already has a correct project adapter or the answers are directly inferable from repo evidence. Another project's adapter may be used as a field-shape reference, but never as a substitute for interview-derived facts. Do not copy another project's stack, gates, deployment model, review wrappers, autonomy boundaries, or known project rules into a new adapter unless repo evidence or interview answers justify each value.

Source adapters must include `bootstrapEvidence` with a matching project name, status, and summary. New adopter-owned source adapters live at `.minervit/adapter.json` in the target repo by default; `<methodology_repo>/adapters/projects/` is for framework-owned reference/development adapters and explicit legacy migration work. New projects use `status: "interviewed"` with an answered interview artifact path plus SHA256, or `status: "repo-evident"` with target-relative evidence paths. Do not use `legacy-reviewed` for new projects. Do not carry another project's `bootstrapEvidence` forward; copied evidence must fail because it proves the adapter came from the wrong project.

Do not hand-write or copy `.minervit-ai-delivery.json` directly into a lane. Generate lane-local adapters from the source adapter so the source provenance, methodology version, and drift checks remain visible.

Ask about:

- product purpose, primary users/operators, and deployment environments;
- production/staging/demo status and whether deployment is part of milestone close;
- technical stack non-negotiables, approved cloud providers/hosting platforms, and platform changes that require explicit human approval;
- cloud services default to AWS for new projects unless the adapter explicitly overrides the approved providers;
- for AWS-approved lanes, the AWS CLI profile, SSO/login path, and identity check that deployments should use before considering SSH keys or alternate credentials;
- normal delivery workflow: PR, merge queue/auto-merge, direct-to-main, release branch, or other;
- authoritative backlog/work tracker;
- whether GitHub Projects is authoritative for big-picture goals/milestones, including owner, project number, status/priority/milestone fields, status values, and what the board controls;
- bug triage policy, source-of-truth artifact, external-issue mirroring, and automatically P0/P1 bug categories;
- plan/spec source-of-truth path, template, naming convention, and scratch-only paths;
- main-health, fast preflight, full preflight, test-environment, open-PR, and merge-conflict commands;
- Codex and Claude review workflows, including plan-review requirements and whether the default `review.codexFastMode: true` policy should be overridden for a project-specific reason;
- local services, ports, Docker Compose names, external credentials, and true non-isolatable resources;
- readiness documents, document-context roots/indexes, archive/historical paths, behavior-spec conventions, executable acceptance harness command/app target, inactive-scenario policy, precise actor-role vocabulary, forbidden generic role terms, and any reviewed business/customer behavior-spec source materials that should be adapted before new scenarios are authored;
- autonomy boundaries: what the AI may push, queue, merge, deploy, or clean up without asking after gates pass, and which security/cost/data/production actions need explicit approval.

Do not ask the full list verbatim when repo evidence already answers parts of it. Summarize inferred adapter facts first, then ask the remaining questions as one concise setup interview. If an answer stays unknown and is required for a safe adapter, keep the adapter fail-closed with `BOOTSTRAP REQUIRED` and name the exact blocker.

## Missing Adapter Behavior

If `lane-start` reports no project adapter and the human operator asked to use the methodology, bootstrap the adapter now. Do not ask whether to skip methodology. Do not ask whether the human operator wants to author the adapter. Ask only for facts that cannot be inferred safely after inspecting repo evidence.

Before rendering the first adapter for that repo, prove one of these is true:

- the unresolved interview was completed with the human operator;
- every required adapter fact is directly supported by repo evidence that you summarize before rendering;
- the adapter remains fail-closed with `BOOTSTRAP REQUIRED` for every unknown required fact.

Do not let a clean `methodology-status` on a copied or guessed adapter stand in for this proof. Source-adapter provenance must be represented in `bootstrapEvidence`, and the `bootstrapEvidence.project` value must match the adapter `project`.

Creating a project adapter from repo-evident facts is setup work, not automatically a Tier 2 approval stop. True blockers include unknown production status, no discoverable required gate command, no discoverable merge-conflict check for a PR-based project, or conflicting evidence about the project workflow.

Existing continuity handoffs and project docs may be used as evidence for adapter fields during bootstrap. Product execution from the handoff still waits until `lane-start` and `methodology-status --fail-on-drift` pass.

For document context, start unmanaged projects in warn mode. Use the generated context index to route current docs, classify historical docs as evidence only, and enable strict mode only after `context-status --strict` is clean.

## Adapter Rules

- No generic operational adapter exists.
- Do not borrow another project's adapter.
- Do not create permissive no-op gates that make unknown checks look green.
- If the project intentionally has no remote, PRs, or merge queue, configure explicit local/no-remote status commands and document direct-to-main workflow in the adapter.
- Configure a merge-conflict check. For GitHub PR projects, this can be a host/open-PR mergeability check plus a current-branch conflict command such as `git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null`; for local-only/direct-to-main projects, configure an explicit no-remote equivalent rather than pretending GitHub exists.
- Fail-closed scaffold commands are acceptable during drafting only; they are not operational gates.

## Do Not

- Copy the full methodology into every project by hand.
- Treat memory as process authority.
- Use an active dev lane as automation scratch space.
