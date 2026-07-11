# Adapter And Lane Lifecycle

This reference owns project adapter structure, planning placement, technical
stack policy, lane startup/update behavior, release tracks, GitHub API budget,
and local resource isolation. Keep the operating manual concise and put detailed
adapter/lane procedures here.

## Project Adapters

A project adapter is a JSON file under:

```text
adapters/projects/
```

Adopter-owned projects should migrate toward a repo-local source adapter at:

```text
.tautline/adapter.json
```

The legacy `.minervit/adapter.json` location still resolves. `render-adapters --project .tautline/adapter.json --target . --write` records that repo-local source and its SHA in the generated lane adapter. Legacy `adapters/projects/*.json` remains supported for framework development and migration.

The adapter defines:

- Project name.
- GitHub repo slug.
- Whether a production deploy exists.
- Backlog routing policy for lower-severity findings.
- Technical stack policy, including approved cloud providers and non-negotiable platform defaults.
- Optional Graphify navigation settings, enabled by default, including output paths, install/build/update commands, freshness rules, and git-ignore policy.
- Project commands for main status, optional early-warning smoke, fast preflight, full preflight, test environment, merge queue, open PR checks, and merge-conflict checks.
- Review wrapper paths, Codex fast-mode policy, and cross-model review timing.
- Plan/spec source-of-truth paths, templates, and scratch-only tool defaults.
- Goal source-of-truth paths, template, trigger, Claude `/goal` preference, and lane-local goal ledger path.
- Behavior-spec requirements.
- Continuity handoff path and archive policy.
- Session journal policy, cadence, and local ignore behavior (local-only evidence as of 0.9.0; no archive branch).
- Lane-local state paths for methodology locks, run evidence, execution packets, goal/milestone run ledgers, and ignore policy.
- Lane-local resource isolation settings for local service gates.
- Readiness source paths for GitHub-only status reviews.
- Optional document context budget settings for indexes, tracked doc roots, historical paths, ignored paths, and warn/strict enforcement.
- Optional session journal settings for local-only summary evidence.
- Optional milestone continuation settings for watchdog recovery visibility.
- Optional iteration review settings for completed goal review records, pages, video output, and approved media hosting.
- Optional milestone update settings for internal Product Milestones Google Chat cards.
- Known project-specific invariants.
- Generated files.
- Optional framework release-track pinning through `_framework`; repo-local `.minervit/pin.json` can override it for a specific adopter checkout.

Example:

```json
{
  "project": "Example Product",
  "repo": "org/example-product",
  "productionDeployExists": true,
  "commands": {
    "mainStatus": "make ci-status-main",
    "earlyWarningSmoke": "make ci-status-main",
    "fastPreflight": "make pf-fast",
    "fullPreflight": "make preflight",
    "mergeConflictCheck": "git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null"
  },
  "review": {
    "codexWrapper": "./scripts/codex-review.sh",
    "codexPlanWrapper": "./scripts/codex-review.sh",
    "codexFastMode": true
  }
}
```

Do not put full reusable process text in an adapter. Put reusable policy in `methodology/canonical-rules.md`; put only project-specific values in the adapter.

### Planning Artifact Placement

Project adapters should define where non-trivial plans/specs live. Tool defaults are not automatically authoritative.

For example:

```text
source of truth: docs/product/backlog/<project>/specs/
template: docs/product/backlog/templates/pr-execution-spec.template.md
template trigger: non-trivial, protected-category, infrastructure, customer-facing, or adapter-required PR work
review exemptions: doc-only/operator-guide/index/release-note/backlog-status work with no runtime behavior change
scratch only: ~/.claude/plans/
```

Before drafting or finalizing a plan/spec, load the current lane adapter by running lane startup or reading the generated adapter already present in the lane. Do not draft canonical PR execution plans before the source-of-truth path and template are known.

Use the source-of-truth path for T2/T3 plans, adapter-required PR work, or any plan explicitly matching the project template trigger. Unclear classification does not default to the template/review path; inspect adapter, touched paths, issue scope, execution packet, and current diff, then choose the lowest defensible tier or ask one exact blocker question only when the tier changes approved risk. Preserve the template's required sections and local filename conventions when the source-of-truth path is used.

Use adapter `planningArtifacts.reviewExemptions` only for narrow plan-review bypasses that still keep implementation review and gates. A review-exempt source-of-truth plan must include `## Plan Review Exemption` and satisfy `plan-finalization-precheck`; it is not a chat-only exemption.

Any plan/spec path outside the configured source-of-truth path is non-canonical scratch unless the project adapter explicitly says otherwise. At session start and before plan finalization, check whether current context or methodology status points to a relevant plan in a scratch-only path; migrate the relevant plan before continuing. Lane startup automatically moves detected relevant scratch plans into the source-of-truth path. `minervit-methodology methodology-status --target . --fail-on-drift` fails when the source/template paths are missing or relevant scratch plans remain. If a tool writes a plan to a scratch path, immediately move or rewrite it into the project source-of-truth path before treating planning as complete. After moving or rewriting a scratch plan, remove or ignore the scratch copy so there is only one canonical plan artifact. Backlog/source-of-truth paths beat tool defaults, memory defaults, and global agent defaults.

### Bug Backlog Management

Adapter-aware bug intake is active policy through the `bug-intake-triage`
skill, closing `METH-FU-BUG-BACKLOG-MANAGEMENT`. Before filing, planning, or
deferring a bug, read adapter `bugBacklog`, `backlogAdapter`, and
`backlogProvider`.

Classify severity first. Use the adapter severity taxonomy, and treat auth,
email, tenant data, security, deploy, billing, data-loss, and
customer-blocking failures as at least `P1` unless evidence proves lower
severity. Write the adapter-declared source-of-truth artifact or tracker entry,
create only adapter-required mirrors, and do not ask the operator whether to
use specs or GitHub when the adapter already resolves the tracker of record.

Customer-facing bugs in provider-backed projects must also be on the
stakeholder board with an Item Type and current `Status`; `gh issue create`
alone is not done. Internal/non-customer-facing bugs stay out of customer
boards unless adapter policy records concrete customer impact.

### Technical Stack Policy

Project adapters own technical stack policy. New projects default to AWS for cloud services, and the scaffold sets `technologyStack.approvedCloudProviders` to `["AWS"]` unless the project explicitly overrides it.

Do not introduce Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase, or another cloud/hosting platform from a starter-template or tool default when the adapter is AWS-only. A project can opt into another provider by making that approval explicit in `technologyStack`; otherwise, adding a new cloud/hosting platform is a Tier 2/Tier 3 decision because it adds billing, security, deployment, operations, and support surface.

For AWS-approved lanes, AWS CLI is the default deploy credential path. Agents should verify the CLI with `aws --version` and verify the active identity with `aws sts get-caller-identity` or the adapter-declared profile/identity command before treating credentials as blocked. If the CLI is missing, install or update AWS CLI v2 using the official AWS CLI installation guide. If login is missing or expired, configure or renew the adapter-declared AWS auth path such as IAM Identity Center/SSO, profile, or environment credentials. Do not ask for SSH keys, create SSH-key blockers, or invent alternate deploy credentials for AWS deployments until the AWS CLI path has been checked.

Useful official AWS references:

- [Installing or updating to the latest version of the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Configuring IAM Identity Center authentication with the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
- [`aws sts get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)

## Lane Lifecycle And Methodology Updates

Adapter-backed lanes should start with the lane lifecycle command from the lane root:

```bash
minervit-methodology lane-start --target .
minervit-methodology methodology-status --target . --fail-on-drift
```

Resolve the methodology CLI before running those gates. Use `minervit-methodology` from `PATH` when available. If it is missing from `PATH` or exits 127/command-not-found, source `$HOME/.config/minervit/methodology.env` when present or use `$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology`, then rerun the same gate with that resolved CLI. A missing `PATH` entry is not a failed methodology gate, not permission to substitute ad hoc checks, not a reason to ask the human operator what to do, and not a reason to ask for a person-specific checkout path. If the methodology checkout path is not already known from `PATH`, `MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, machine bootstrap, current continuity handoff, or generated adapter context, inspect only those configured sources to resolve it. If the CLI and checkout still cannot be found, name the exact missing CLI/checkout true blocker.

These startup gates are mandatory actions, not choices for the human operator. Do not ask whether to run them, whether to "kick those off", or whether to proceed with a named path after they pass. Run the gates and continue with the authorized next action unless a true blocker occurs.

The command:

- reads `.tautline.json` by default (falling back to the legacy `.minervit-ai-delivery.json`), or an explicit `--project <adapter.json>`;
- honors the effective framework pin before any framework update; existing adapters default to `stable` / `manual` / `dry-run`;
- installs the release-main git guard so the shared framework checkout cannot be accidentally committed on local `main`;
- fails closed when the framework update fails for an unlocked lane, because stale process rules must be resolved before adapter regeneration;
- refreshes `.tautline.json` and regenerates `CLAUDE.md`/`AGENTS.md` only when those Markdown files are absent or already framework-generated;
- migrates detected relevant scratch plans into the configured source-of-truth path;
- writes lane-local resource exports such as ports and Docker Compose project name;
- creates lane-local state directories;
- adds lane-local state to `.git/info/exclude`;
- reports continuity, execution-packet presence, document context budget state, and session journal state.

Unlocked adapter-backed lanes do not raw-pull the latest methodology by default. Existing products and clients default to the stable channel with `updatePolicy=manual`, so `lane-start` reports the effective pin, available update, WIP reasons, and pending migration-report state without surprise minor/major movement. A deliberate update uses `minervit-methodology sync-methodology --target .`, which still applies release-track and WIP checks. Stable updates require signed or pinned update-trust policy before re-exec; experimental updates are opt-in through `_framework.channel=experimental` or `.minervit/pin.json`.

When `sync-methodology` or `lane-start` is allowed to update from a project lane, the existing auto-rescue behavior still applies: preserve dirty tracked methodology checkout changes on a local `minervit-local-rescue/<utc>-...` branch, move untracked files under `$HOME/.local/state/minervit/methodology-rescue/.../untracked/`, preserve clean non-`main` branches by switching back to release `main`, preserve accidental local `main` commits on a rescue branch before resetting release `main` to `origin/main`, re-run itself, and continue startup. Managed Claude launchers also run a shell-level preflight rescue before calling the CLI, because an outdated CLI may not yet contain the newest rescue behavior. If the newer remote cannot be confirmed for dirty stale changes, project-lane startup fails closed instead of moving edits based on stale cached state. When invoked from inside the methodology repo, plain `sync-methodology` still fails closed so framework development work is not moved unexpectedly; use `--auto-rescue-local-changes` explicitly to rescue it, or `--no-auto-rescue-local-changes` to force fail-closed behavior from a project lane. `install-cli`, `sync-methodology`, `install-claude-launcher`, and `lane-start` install a repo-local pre-commit hook that blocks local commits directly on methodology `main`; methodology work belongs on feature branches and PRs. `lane-start`, `methodology-status`, and `version` report `plugin_version` and methodology commit so the session can prove which process surface it is using. If uncertain which process surface is active, run `minervit-methodology version` and `minervit-methodology methodology-status --target .`; do not ask the human operator to decide whether to inspect version/status. Cached host plugin metadata is not a lane update failure. If `minervit-methodology version` reports the expected plugin version but Codex/Claude still shows stale plugin skills or metadata, restart that host/session.

If the methodology repo already shows Git's divergent-branch prompt on `git pull`, run `bin/minervit-methodology repair-methodology-main` from the methodology checkout. The command preserves accidental local `main` commits on a `minervit-local-rescue/...` branch, resets release `main` to `origin/main`, installs the release-main guard, and reports the current version/commit.

If startup still shows `methodology_update: failed - methodology checkout has local changes and remote differs ...` or `methodology checkout is on <branch>, not main`, the installed launcher itself predates launcher-level rescue or is not the managed launcher. Do not continue the session on stale framework rules. Run the printed methodology checkout's `bin/minervit-methodology sync-methodology --auto-rescue-local-changes` from the project lane, then reinstall the CLI and managed launcher with `install-cli` and `install-claude-launcher --force`. If auto-rescue is not available because the installed CLI is older, resolve the printed methodology checkout once: commit the local changes on a proposal branch, stash them, or discard them only when they are known generated/scratch edits. Then rerun `minervit-methodology sync-methodology`, `minervit-methodology version`, `minervit-methodology lane-start --target .`, and `minervit-methodology methodology-status --target . --fail-on-drift`.

Lane startup never overwrites hand-written `CLAUDE.md` or `AGENTS.md`. If those files do not carry the framework's generated header, startup reports `generated_markdown_protected` and leaves them untouched while still refreshing `.tautline.json`. Methodology status reports the protected Markdown under `adapter_markdown_protected` instead of treating it as generated-adapter drift. Agents must not ask whether to overwrite such files; for a small config enablement, use `render-adapters --write --json-only`, and for full adapter-backed Markdown, run a separate migration that preserves the old rules before rendering.

The status command is the startup health gate before planning work. With `--fail-on-drift`, it fails on adapter drift, missing planning source/template paths, relevant scratch plans that still require migration, and strict document-context issues. Use `methodology-status --strict --fail-on-drift` during project context migration to temporarily enforce document-context strictness without changing the adapter. Session journals are local-only as of 0.9.0: they stay under the lane's gitignored `.ai-runs/` and are never published, so there is no pending-publish step (`publish-session-journal`/`publish-pending-session-journals` are disabled). To contribute sanitized signal upstream, enable `"instrumentation": {"enabled": true}` in the source adapter and run `publish-instrumentation-record --target .`.

If `lane-start` reports `No project adapter found`, the lane is unmanaged. Use the new-project bootstrap flow in [Project Administration](project-administration.md#adding-a-new-project) instead of asking whether to skip the framework. The missing adapter is the prerequisite setup task.

When checking current project status, whether work is complete, what is next, or work that may have happened in another lane, fetch and inspect the latest-code baseline before answering. Use:

```bash
minervit-methodology latest-code-status --target . --write
```

This command fetches the adapter-configured remote base (`origin/main` by default), records `.ai-work/LATEST_CODE_BASELINE.json`, reports local-vs-base divergence, lists remote branches ahead of base, and lists open PRs when GitHub CLI access is available. If the local lane is behind, dirty, detached, on a PR branch, or another remote branch may be deployed or stakeholder-visible, do not answer from local files as if they are current. Use `git show origin/main:<path>`, `git show <remote-branch>:<path>`, GitHub/`gh` evidence, and deploy/build identity for the current answer.

Latest-code baseline is mandatory before deep codebase analysis, architecture review, multi-angle analysis, planning, implementation, review, tactical subagent dispatch, or any work that will influence product decisions. Fetch remote/base and ahead lane branches first. If the work is read-only status or diagnosis, inspect fetched remote refs/GitHub/deploy evidence without mutating unrelated lane work. The latest-code hook protects state-changing work such as edits, plan finalization, commits, and pushes; it must not block ordinary read-only inspection needed to diagnose or refresh lane state. If preparing to work in the lane, bring the branch onto the fetched base by the adapter-approved path before using local files as current; if that cannot be done cleanly, name the exact blocker before analysis.

Use `--skip-update` for a one-off startup that should not pull the latest framework:

```bash
minervit-methodology lane-start --target . --skip-update
```

Lock the framework version for a lane when the project owner wants process stability:

```bash
minervit-methodology lock-methodology --target . --reason "<reason>"
```

Unlock it when the lane should resume automatic updates:

```bash
minervit-methodology unlock-methodology --target .
```

Inspect current state:

```bash
minervit-methodology methodology-status --target .
```

Force-refresh a lane manually when another machine may not be updating. This path intentionally unpins a lane if a lock file exists, because the project owner is explicitly requesting the latest framework. If the lane should stay pinned, do not run this block; run `minervit-methodology methodology-status --target .` and report the locked commit and reason instead.

```bash
set -euo pipefail
cd <lane_path>
if test -f "$HOME/.config/minervit/methodology.env"; then
  . "$HOME/.config/minervit/methodology.env"
fi
if ! command -v minervit-methodology >/dev/null 2>&1; then
  : "${MINERVIT_METHODOLOGY_REPO:?missing methodology env; run <methodology_repo>/bin/minervit-methodology install-cli}"
  export PATH="$MINERVIT_METHODOLOGY_REPO/bin:$PATH"
fi
: "${MINERVIT_METHODOLOGY_REPO:?missing methodology env; run <methodology_repo>/bin/minervit-methodology install-cli}"
test -d "$MINERVIT_METHODOLOGY_REPO/.git"
if ! git -C "$MINERVIT_METHODOLOGY_REPO" diff --quiet || ! git -C "$MINERVIT_METHODOLOGY_REPO" diff --cached --quiet; then
  echo "Methodology checkout has local changes; resolve them before force-refreshing." >&2
  exit 1
fi
minervit-methodology sync-methodology
minervit-methodology version
if test -f .minervit-methodology-lock.json; then
  minervit-methodology unlock-methodology --target .
fi
minervit-methodology lane-start --target .
minervit-methodology methodology-status --target . --fail-on-drift
```

Lane-local state paths are:

```text
.minervit-methodology-lock.json
.ai-runs/
.ai-runs/session-journals/
.ai-work/EXECUTION_PACKET.md
.ai-work/lane-env.sh
.ai-continuity/NEXT_SESSION.md
```

These paths are ignored through `.git/info/exclude` by default. They are lane-local operational state, not project source.

## Release Tracks And Adapter Migrations

Framework changes are controlled by a client-facing pin. Put it in the source adapter as `_framework` or in the adopter repo as `.minervit/pin.json`:

```json
{
  "channel": "stable",
  "version": "0.6.123",
  "updatePolicy": "manual",
  "migrationPolicy": "dry-run"
}
```

Defaults are stable, current local version, manual updates, and dry-run migrations. Stable is for products and clients; experimental is opt-in for policy splitting, behavior pruning, provider-registry work, and other canary changes. Active goal ledgers, milestone ledgers, execution packets, running review evidence, or active branches block automatic minor/major updates. Patch auto-updates during WIP require the target release migration report to declare `wipSafe=true`.

Set a lane's track with the channel command so users do not need to hand-edit JSON.
The default writes `.minervit/pin.json` as a lane-local override:

```bash
minervit-methodology set-framework-channel --target . stable
minervit-methodology set-framework-channel --target . experimental
```

To change the repo-local source adapter's `_framework.channel`, use adapter
source mode. This validates `.tautline/adapter.json` and re-renders
`.tautline.json` with `--json-only`:

```bash
minervit-methodology set-framework-channel --target . --source adapter stable
minervit-methodology set-framework-channel --target . --source adapter experimental
```

Use the migration tools before moving products across framework boundaries:

```bash
minervit-methodology public-contract --check
minervit-methodology release-migration-report --version 0.6.123 --print
minervit-methodology migrate-adapter .tautline/adapter.json
minervit-methodology migrate-adapter .tautline/adapter.json --write
minervit-methodology public-release-check
```

To move a legacy framework-owned adapter into an adopter repo:

```bash
minervit-methodology migrate-adapter adapters/projects/<project>.json --adopter-target <repo> --write
minervit-methodology render-adapters --project <repo>/.tautline/adapter.json --target <repo> --write
```

Do not delete the legacy adapter source until affected lanes are pinned, migrated, re-rendered, and passing startup/status gates.

`public-release-check` is the open-source publication gate. During the private migration window it is expected to fail if real product adapters, private adapter paths, private adapter paths in git history, account IDs, live adapter hosts, or product/client names remain in the release candidate. Internal validation asserts that failure until the real adapters move to adopter-owned `.tautline/adapter.json` files. After those adapters leave the repo, private release CI should pass `--private-terms-file` or set `MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS` with a denylist of customer/product terms so leftover name references remain blocked without committing the denylist. Run the gate from a full git checkout; shallow checkouts fail closed because they cannot prove history is clean. Deleting private adapters from the current tree is not enough for a same-repo public flip; either rewrite history or publish from a clean public repository.

## GitHub API Budget

Provider-backed lanes must treat GitHub GraphQL points as a shared operational budget. Phase-1 controls cache short-lived Project item reads, prefer REST for issue/PR state and issue comments where equivalent, and refuse point-heavy ProjectV2 calls when the remaining GraphQL budget is low. When several lanes are active, give each lane its own `GH_TOKEN` or GitHub App/bot identity instead of sharing one user's 5,000-points/hour GraphQL budget.

If a board command reports low GraphQL budget, do not bypass the board update with raw `gh project` or schema changes. Use cached status for read-only planning where safe, prefer REST-backed issue/PR operations, or retry after the reported reset. A failed active-status or done-status mutation remains a blocker for milestone/implementation or closeout until the board is current.

## Local Resource Isolation

Adapter-backed lanes should isolate local test resources before falling back to locks. Project adapters can declare lane-local environment variables, Docker Compose project names, and port blocks. For additional numbered lanes, the framework uses a non-overlapping stride so local services do not collide.

Run local-service gates through `lane-run`:

```bash
minervit-methodology lane-run --target . -- make pf-fast
minervit-methodology lane-run --target . -- make test-env-up
minervit-methodology lane-run --target . -- make preflight
```

If a lane fails with a port-in-use error after running a bare project command, rerun the command through `lane-run` before treating it as a blocker. A broad machine lock is the wrong default when the contention is fixed host ports or an inherited `COMPOSE_PROJECT_NAME`. Use a resource lock only for a project-declared machine-global resource that cannot be isolated by lane-specific env, names, ports, paths, or remote API calls.
