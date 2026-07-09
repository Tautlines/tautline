# Project Administration

This reference keeps detailed project bootstrap, validation, publishing,
troubleshooting, and maintenance procedures out of the main operating manual.

## Adding A New Project

If `minervit-methodology lane-start --target .` fails with `No project adapter found`, the repo is not adapter-backed yet. Do not keep retrying `lane-start`, do not borrow another project's adapter, and do not ask whether to skip the framework when the human operator asked to use it. Bootstrap the adapter first.

For normal unmanaged repos, use the init front door:

```bash
minervit-methodology init --target .
```

Answer `.ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md`, then run:

```bash
minervit-methodology init --target . --continue
```

The lower-level sequence below is for maintainers who need to inspect or repair
one bootstrap step at a time.

Creating a project adapter from repo-evident facts is setup work, not automatically a Tier 2 approval stop. Ask one exact blocker question only for choices that cannot be inferred safely after inspection, such as unknown production status, missing required gate command, missing merge-conflict check for a PR-based project, or conflicting workflow evidence.

No generic operational adapter exists because planning paths, gates, review workflow, local resources, and production status are project-specific. A scaffold may be used, but every `BOOTSTRAP REQUIRED` placeholder must be replaced before the adapter is operational. Another project's adapter may be used only as a structural field reference; do not copy another project's stack, commands, deployment model, review wrappers, autonomy boundaries, known project rules, or `bootstrapEvidence` into a new adapter unless repo evidence or interview answers justify each value.

1. Inspect the target repo for commands, CI gates, review wrappers, backlog location, plan/spec conventions, behavior-spec conventions, merge-conflict checks, local service ports, remote/PR workflow, production status, and technical stack/platform evidence.
2. Generate the adapter bootstrap interview and ask the human operator only the unresolved questions after inspection. This interview is mandatory before first adapter render/write unless every required adapter fact is repo-evident. Do not ask for facts that package scripts, CI files, project docs, remotes, existing plans, or deployment files already answer.

```bash
bin/minervit-methodology adapter-bootstrap-questions \
  --target <lane_path> \
  --write
```

The interview covers product/deployment, technical stack policy, delivery workflow, backlog/source-of-truth, optional GitHub Projects goal tracking, bug intake, required gates, review flow, local resources, docs/readiness, behavior specs, and autonomy boundaries. Bundle unresolved questions into one concise setup interview so the resulting adapter reflects the actual project instead of a generic scaffold. In an empty or `.git`-only repo, almost no adapter facts are safely inferable, so the human operator interview is required. If the adapter uses `bootstrapEvidence.status: "interviewed"`, render verifies the answered interview artifact exists, has matching `Project:` and `Repository:` headers, answers every generated question, has no `BOOTSTRAP REQUIRED` markers, and matches `bootstrapEvidence.interviewArtifact.sha256`.

3. Create a scaffold adapter:

```bash
bin/minervit-methodology init-project-adapter \
  --target <lane_path>
```

4. Edit the adapter to match the project. Replace every `BOOTSTRAP REQUIRED` placeholder, including `bootstrapEvidence`, with project-matching interview or repo-evidence provenance. New projects must use `interviewed` with an interview artifact or `repo-evident` with non-boilerplate repo evidence paths; `legacy-reviewed` is only for explicitly grandfathered maintained adapters.
   For local-only/direct-to-main projects, configure explicit no-remote status commands and make the adapter `repo` value document the local-only workflow rather than a normal `<owner>/<repo>` identity. A local-only merge-conflict check can be `test -z "$(git diff --name-only --diff-filter=U)"`.
5. Render the adapter into the target project:

```bash
bin/minervit-methodology render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --write
```

6. Run startup gates:

```bash
bin/minervit-methodology lane-start \
  --target <lane_path>

bin/minervit-methodology methodology-status \
  --target <lane_path> \
  --fail-on-drift
```

7. Validate drift:

```bash
bin/minervit-methodology audit \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path>
```

8. Commit the adapter/generated-instruction setup separately from product work when the project uses commits.

If the project intentionally has no remote, PRs, or merge queue, configure explicit local/no-remote status commands and document the direct-to-main workflow in the adapter. Do not use GitHub commands for a local-only project.

Existing continuity handoffs and project docs may be used as evidence for adapter fields during bootstrap. Product execution from the handoff still waits until `lane-start` and `methodology-status --fail-on-drift` pass.

New project adapters should be thin. Do not paste all of `canonical-rules.md` into every project.

## Adding Or Updating Skills

Skills live under:

```text
plugins/tautline-core/skills/
```

Each skill directory must contain:

```text
SKILL.md
```

Each `SKILL.md` needs YAML frontmatter:

```markdown
---
name: skill-name
description: Clear trigger description for when Codex should use this skill.
---
```

Guidelines:

- Keep `SKILL.md` concise.
- Put deterministic logic in scripts when possible.
- Use references only when the skill needs extra detail.
- Do not create extra docs inside skills unless they directly support skill execution.
- Validate after edits:

```bash
scripts/test.sh
scripts/validate.sh
```

## Validation

Run the behavior gate and repository validation script:

```bash
scripts/test.sh
scripts/validate.sh
```

The validation script checks:

- Python syntax for `bin/minervit-methodology`.
- Policy module assembly (`canonical-policy --check`) so `methodology/canonical-rules.md` stays generated from `methodology/policy/`.
- JSON validity for adapters and plugin manifests.
- Adapter render/check round trip against a temporary directory.
- Lane lifecycle startup, lock, unlock, status, and ignored state paths.
- Document context budget bootstrap/status behavior, derived adapter defaults, strict validation, and archive headers.
- Lane-local resource environment generation and `lane-run` command wrapping.
- Execution packet dry run evidence and continuity handoff refresh.
- Generated adapter coverage for drive/do-not-defer, rejected tool-call recovery, analysis-first requests, and continuity-file behavior.
- Skill frontmatter and body presence.
- Absence of person-specific names and workstation-specific path examples in repository text.
- Removal of generated `__pycache__` directories.

Run project-specific validation:

```bash
bin/minervit-methodology render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --check

bin/minervit-methodology audit \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path>
```

Run GitHub-only readiness smoke test:

```bash
bin/minervit-methodology readiness-review --project <lane_path>/.tautline/adapter.json
```

## Publishing To GitHub

Remote:

```text
https://github.com/tautlines/tautline.git
```

Normal publish flow:

```bash
git status --short
scripts/test.sh
scripts/validate.sh
git add .
git commit -m "Add Tautline delivery framework"
git push -u origin main
```

If the remote already has commits:

```bash
git fetch origin main
git status --short --branch
```

Do not force-push over remote history unless the human approver explicitly approves it.

## Troubleshooting

### `gh api` fails

Check authentication:

```bash
gh auth status
```

Confirm repo access:

```bash
gh api repos/<owner>/<repo> --jq .full_name
```

### Codex plugin does not appear

Check `~/.codex/config.toml` has the local marketplace:

```toml
[marketplaces.minervit-local]
source_type = "local"
source = "<methodology_repo>"
```

Restart Codex after changing plugin config.

### Claude does not use Superpowers

Verify installation:

```bash
claude plugin list
```

Install if missing:

```bash
claude plugin install -s user superpowers@claude-plugins-official
```

Restart Claude sessions that need the plugin.

### Generated adapter check fails

Regenerate the target project:

```bash
bin/minervit-methodology render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --write
```

Then run check again.

### Drift audit fails

Read the finding. Fix the stale process source by either:

- Regenerating the adapter.
- Updating the canonical rule.
- Updating the project adapter.
- Marking old docs as archival.
- Removing stale lane references.

Do not silence audit findings by editing the audit pattern unless the pattern itself is wrong.

## Maintenance Rules

Use these rules when changing this repo:

1. Reusable process belongs in ordered modules under `methodology/policy/`; regenerate the compatibility artifact with `minervit-methodology canonical-policy --write`.
2. Project-specific commands and gates belong in `adapters/projects/*.json`.
3. Generated files must be regenerated, not hand-edited.
4. Skills should stay concise and task-triggered.
5. Open Brain captures decisions and evidence, not canonical process.
6. Always run `scripts/test.sh` and `scripts/validate.sh` before committing.
7. For project adapter changes, also run render check and drift audit.
8. Do not use active development lanes as automation scratch space.
9. Do not restore routine admin merge.
10. Do not restore a review cap that allows known Critical/P1 findings to ship.
11. Do not restore plan-review loops that continue past two rounds without the narrow R3 structural-Critical exception.
12. Do not restore cross-model plan-review loops that rerun native/Superpowers review before every round instead of one self-check before R1.
13. Do not restore T2/T3 code-review loops that hand a changed assembled diff back to Codex/Stage 2 before native/Superpowers review has inspected that changed diff.
14. Do not restore review-blocker option menus that ask the human operator to pick a numbered path when a safe recommended repair sequence exists.

## Documentation Language Standard

Reusable framework documentation and generated adapter text must use role-based terms:

- `human operator` for the person directing the AI work;
- `project owner` for scope and priority ownership;
- `human approver` for explicit approval gates.

Do not use person-specific names in canonical process docs, generated adapters, or reusable skills. Do not use workstation-specific path examples. Prefer placeholders such as `<methodology_repo>`, `<lane_path>`, and `<project_adapter>`.
