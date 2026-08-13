from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_REFERENCE = ROOT / "docs" / "reference" / "operating-manual.md"
OPERATING_MANUAL = README_REFERENCE
POLICY_MODULE_INDEX = ROOT / "docs" / "reference" / "policy-module-index.md"
RUNTIME_EVIDENCE_REFERENCE = ROOT / "docs" / "reference" / "operations" / "runtime-evidence.md"
WORKFLOW_GUARDRAILS_REFERENCE = ROOT / "docs" / "reference" / "operations" / "workflow-guardrails.md"
PROJECT_ADMINISTRATION_REFERENCE = ROOT / "docs" / "reference" / "operations" / "project-administration.md"
CLI_OPERATIONS_REFERENCE = ROOT / "docs" / "reference" / "operations" / "cli-operations.md"
DELIVERY_COMMUNICATIONS_REFERENCE = ROOT / "docs" / "reference" / "operations" / "delivery-communications.md"
GOAL_EXECUTION_REFERENCE = ROOT / "docs" / "reference" / "operations" / "goal-execution.md"
EXECUTION_PACKET_REFERENCE = ROOT / "docs" / "reference" / "operations" / "execution-packet-work-loop.md"
BACKLOG_PROVIDER_REFERENCE = ROOT / "docs" / "reference" / "operations" / "backlog-provider-workflow.md"
AUTONOMY_GUARDRAILS_REFERENCE = ROOT / "docs" / "reference" / "operations" / "autonomy-guardrails.md"
STATUS_CONTINUITY_REFERENCE = ROOT / "docs" / "reference" / "operations" / "status-continuity.md"
CONTEXT_CONTINUITY_REFERENCE = ROOT / "docs" / "reference" / "operations" / "context-continuity.md"
SETUP_RUNTIME_REFERENCE = ROOT / "docs" / "reference" / "operations" / "setup-runtime.md"
ADAPTER_LANE_REFERENCE = ROOT / "docs" / "reference" / "operations" / "adapter-lane-lifecycle.md"
RELEASE_ENGINEERING_REFERENCE = ROOT / "docs" / "reference" / "operations" / "release-engineering.md"


def _heading_lines(text):
    return {line.strip() for line in text.splitlines() if line.startswith("#")}


def _validate_sh_word_count(text):
    # Keep parity with the removed validate.sh Python heredoc.
    return len(text.split())


def _assert_contains_all(text, required_phrases):
    missing = [phrase for phrase in required_phrases if phrase not in text]
    assert missing == []


def _assert_contains_none(text, forbidden_phrases):
    present = [phrase for phrase in forbidden_phrases if phrase in text]
    assert present == []


def _operating_reference_corpus():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            OPERATING_MANUAL,
            RUNTIME_EVIDENCE_REFERENCE,
            WORKFLOW_GUARDRAILS_REFERENCE,
            PROJECT_ADMINISTRATION_REFERENCE,
            CLI_OPERATIONS_REFERENCE,
            DELIVERY_COMMUNICATIONS_REFERENCE,
            GOAL_EXECUTION_REFERENCE,
            EXECUTION_PACKET_REFERENCE,
            BACKLOG_PROVIDER_REFERENCE,
            AUTONOMY_GUARDRAILS_REFERENCE,
            STATUS_CONTINUITY_REFERENCE,
            CONTEXT_CONTINUITY_REFERENCE,
            SETUP_RUNTIME_REFERENCE,
            ADAPTER_LANE_REFERENCE,
            RELEASE_ENGINEERING_REFERENCE,
        ]
    )


def test_readme_is_concise_public_entrypoint():
    assert README.exists(), README
    text = README.read_text(encoding="utf-8")
    headings = _heading_lines(text)

    assert _validate_sh_word_count(text) <= 2500
    assert len(text.splitlines()) <= 200
    assert "# Tautline — the governor for AI coding agents" in headings
    # The pitch names the core promise near the top of the public entrypoint.
    assert "claiming false completion" in text
    assert "## Why Tautline" in headings
    assert "## Quickstart" in headings
    assert "## How it compares" in headings
    assert "## Common questions" in headings
    assert "## Docs" in headings
    assert "## Community" in headings
    assert "bin/tautline install-cli" in text
    assert "tautline init --target ." in text
    assert "init --target . --continue" in text
    assert "tautline lane-start --target ." in text
    assert "docs/README.md" in text
    assert "docs/reference/operating-manual.md" in text
    assert "docs/product/positioning.md" in text
    assert "docs/product/support-sla-model.md" in text
    assert "CONTRIBUTING.md" in text
    assert ".github/AI_CONTRIBUTION_POLICY.md" in text
    assert "GOVERNANCE.md" in text
    assert "SECURITY.md" in text
    _assert_contains_none(
        text,
        [
            "public-release-export",
            "public-release-check",
            "public-contract --check",
        ],
    )


def test_operating_manual_retains_detailed_reference_content():
    assert OPERATING_MANUAL.exists(), OPERATING_MANUAL
    assert POLICY_MODULE_INDEX.exists(), POLICY_MODULE_INDEX
    assert RUNTIME_EVIDENCE_REFERENCE.exists(), RUNTIME_EVIDENCE_REFERENCE
    assert WORKFLOW_GUARDRAILS_REFERENCE.exists(), WORKFLOW_GUARDRAILS_REFERENCE
    assert PROJECT_ADMINISTRATION_REFERENCE.exists(), PROJECT_ADMINISTRATION_REFERENCE
    assert CLI_OPERATIONS_REFERENCE.exists(), CLI_OPERATIONS_REFERENCE
    assert DELIVERY_COMMUNICATIONS_REFERENCE.exists(), DELIVERY_COMMUNICATIONS_REFERENCE
    assert GOAL_EXECUTION_REFERENCE.exists(), GOAL_EXECUTION_REFERENCE
    assert EXECUTION_PACKET_REFERENCE.exists(), EXECUTION_PACKET_REFERENCE
    assert BACKLOG_PROVIDER_REFERENCE.exists(), BACKLOG_PROVIDER_REFERENCE
    assert AUTONOMY_GUARDRAILS_REFERENCE.exists(), AUTONOMY_GUARDRAILS_REFERENCE
    assert STATUS_CONTINUITY_REFERENCE.exists(), STATUS_CONTINUITY_REFERENCE
    assert CONTEXT_CONTINUITY_REFERENCE.exists(), CONTEXT_CONTINUITY_REFERENCE
    assert SETUP_RUNTIME_REFERENCE.exists(), SETUP_RUNTIME_REFERENCE
    assert ADAPTER_LANE_REFERENCE.exists(), ADAPTER_LANE_REFERENCE
    assert RELEASE_ENGINEERING_REFERENCE.exists(), RELEASE_ENGINEERING_REFERENCE
    text = OPERATING_MANUAL.read_text(encoding="utf-8")
    headings = _heading_lines(text)

    assert _validate_sh_word_count(text) >= 3300
    assert "# Tautline Operating Manual" in headings
    assert "Policy Module Index](policy-module-index.md)" in text
    assert "operations/setup-runtime.md#what-this-repo-owns" in text
    assert "operations/setup-runtime.md#authority-model" in text
    assert "operations/setup-runtime.md#repository-layout" in text
    assert "operations/setup-runtime.md#prerequisites" in text
    assert "operations/setup-runtime.md#initial-setup" in text
    assert "operations/setup-runtime.md#codex-plugin-setup" in text
    assert "operations/setup-runtime.md#available-codex-skills" in text
    assert "operations/setup-runtime.md#claude-setup" in text
    assert "operations/setup-runtime.md#claude-launcher-helper" in text
    assert "operations/release-engineering.md#release-gate-commands" in text
    assert "operations/release-engineering.md#public-release-export" in text
    assert "operations/release-engineering.md#release-tracks-and-client-safety" in text
    assert "operations/adapter-lane-lifecycle.md#project-adapters" in text
    assert "operations/adapter-lane-lifecycle.md#planning-artifact-placement" in text
    assert "operations/adapter-lane-lifecycle.md#bug-backlog-management" in text
    assert "operations/adapter-lane-lifecycle.md#technical-stack-policy" in text
    assert "operations/adapter-lane-lifecycle.md#lane-lifecycle-and-methodology-updates" in text
    assert "operations/adapter-lane-lifecycle.md#release-tracks-and-adapter-migrations" in text
    assert "operations/adapter-lane-lifecycle.md#github-api-budget" in text
    assert "operations/adapter-lane-lifecycle.md#local-resource-isolation" in text
    assert "operations/runtime-evidence.md#session-journals-local-only" in text
    assert "operations/runtime-evidence.md#repo-event-logs" in text
    assert "operations/runtime-evidence.md#usage-accounting" in text
    assert "operations/workflow-guardrails.md#review-and-merge-policy" in text
    assert "operations/workflow-guardrails.md#background-work-policy" in text
    assert "operations/workflow-guardrails.md#open-brain-policy" in text
    assert "operations/project-administration.md#adding-a-new-project" in text
    assert "operations/project-administration.md#validation" in text
    assert "operations/project-administration.md#documentation-language-standard" in text
    assert "operations/cli-operations.md#core-cli-usage" in text
    assert "operations/cli-operations.md#render-project-adapters" in text
    assert "operations/cli-operations.md#graphify-commands" in text
    assert "operations/delivery-communications.md#iteration-reviews" in text
    assert "operations/delivery-communications.md#deployment-ready-notifications" in text
    assert "operations/delivery-communications.md#product-chat-notes" in text
    assert "operations/goal-execution.md#goal-orchestration" in text
    assert "operations/backlog-provider-workflow.md#backlog-provider-workflow" in text
    assert "operations/goal-execution.md#cross-lane-coordination" in text
    assert "operations/goal-execution.md#context-rotation" in text
    assert "operations/execution-packet-work-loop.md#execution-packet-work-loop" in text
    assert "operations/autonomy-guardrails.md#drive-do-not-defer" in text
    assert "operations/autonomy-guardrails.md#anti-work-evasion" in text
    assert "operations/status-continuity.md#current-status-truth" in text
    assert "operations/status-continuity.md#plain-language-status" in text
    assert "operations/status-continuity.md#verified-human-instructions" in text
    assert "operations/status-continuity.md#early-warning-smoke" in text
    assert "operations/status-continuity.md#final-preflight-planning-window" in text
    assert "operations/status-continuity.md#milestone-progress-visibility" in text
    assert "operations/status-continuity.md#delivery-summaries" in text
    assert "operations/status-continuity.md#readiness-automation" in text
    assert "operations/context-continuity.md#context-continuity" in text
    assert "# Runtime Evidence" in _heading_lines(RUNTIME_EVIDENCE_REFERENCE.read_text(encoding="utf-8"))
    assert "# Workflow Guardrails" in _heading_lines(WORKFLOW_GUARDRAILS_REFERENCE.read_text(encoding="utf-8"))
    assert "# Project Administration" in _heading_lines(PROJECT_ADMINISTRATION_REFERENCE.read_text(encoding="utf-8"))
    assert "# CLI Operations" in _heading_lines(CLI_OPERATIONS_REFERENCE.read_text(encoding="utf-8"))
    assert "# Delivery Communications" in _heading_lines(DELIVERY_COMMUNICATIONS_REFERENCE.read_text(encoding="utf-8"))
    policy_index_text = POLICY_MODULE_INDEX.read_text(encoding="utf-8")
    policy_index_headings = _heading_lines(policy_index_text)
    assert "# Policy Module Index" in policy_index_headings
    assert "## Module Ownership" in policy_index_headings
    assert "## Editing Rules" in policy_index_headings
    assert "06a-stop-and-deferral-red-flags.md" in policy_index_text
    assert "10-goal-orchestration.md" in policy_index_text
    assert "10a-backlog-provider.md" in policy_index_text
    assert "10b-board-currency.md" in policy_index_text
    assert "21-lane-lifecycle.md" in policy_index_text
    assert "31-automation.md" in policy_index_text
    adapter_lane_headings = _heading_lines(ADAPTER_LANE_REFERENCE.read_text(encoding="utf-8"))
    assert "# Adapter And Lane Lifecycle" in adapter_lane_headings
    assert "## Project Adapters" in adapter_lane_headings
    assert "### Planning Artifact Placement" in adapter_lane_headings
    assert "### Bug Backlog Management" in adapter_lane_headings
    assert "### Technical Stack Policy" in adapter_lane_headings
    assert "## Lane Lifecycle And Methodology Updates" in adapter_lane_headings
    assert "## Release Tracks And Adapter Migrations" in adapter_lane_headings
    assert "## GitHub API Budget" in adapter_lane_headings
    assert "## Local Resource Isolation" in adapter_lane_headings
    adapter_lane_text = ADAPTER_LANE_REFERENCE.read_text(encoding="utf-8")
    _assert_contains_all(
        adapter_lane_text,
        [
            "Do not introduce Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase",
            "set -euo pipefail",
            "tautline latest-code-status --target . --write",
            "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS",
            "public-release-check` is the open-source publication gate",
            "one user's 5,000-points/hour GraphQL budget",
            "tautline lane-run --target . -- make pf-fast",
            "Project Administration](project-administration.md#adding-a-new-project)",
        ],
    )
    setup_runtime_headings = _heading_lines(SETUP_RUNTIME_REFERENCE.read_text(encoding="utf-8"))
    assert "# Setup And Runtime" in setup_runtime_headings
    assert "## What This Repo Owns" in setup_runtime_headings
    assert "## Authority Model" in setup_runtime_headings
    assert "## Repository Layout" in setup_runtime_headings
    assert "## Prerequisites" in setup_runtime_headings
    assert "## Initial Setup" in setup_runtime_headings
    assert "## Codex Plugin Setup" in setup_runtime_headings
    assert "### Available Codex Skills" in setup_runtime_headings
    assert "## Claude Setup" in setup_runtime_headings
    assert "## Claude Launcher Helper" in setup_runtime_headings
    setup_runtime = SETUP_RUNTIME_REFERENCE.read_text(encoding="utf-8")
    assert "`methodology/policy/*.md` contains the ordered reusable process policy modules" in setup_runtime
    assert "`methodology/canonical-rules.md` is the generated compatibility artifact" in setup_runtime
    assert "plugins/tautline-core/.claude-plugin/plugin.json" in setup_runtime
    assert "plugins/tautline-core/hooks/hooks.json" in setup_runtime
    goal_execution_headings = _heading_lines(GOAL_EXECUTION_REFERENCE.read_text(encoding="utf-8"))
    assert "# Goal Execution" in goal_execution_headings
    assert "## Goal Orchestration" in goal_execution_headings
    assert "## Cross-Lane Coordination" in goal_execution_headings
    assert "## Context Rotation" in goal_execution_headings
    assert "## Execution Packet Work Loop" not in goal_execution_headings
    execution_packet_headings = _heading_lines(EXECUTION_PACKET_REFERENCE.read_text(encoding="utf-8"))
    assert "# Execution Packet Work Loop" in execution_packet_headings
    autonomy_guardrails_headings = _heading_lines(AUTONOMY_GUARDRAILS_REFERENCE.read_text(encoding="utf-8"))
    assert "# Autonomy Guardrails" in autonomy_guardrails_headings
    assert "## Drive, Do Not Defer" in autonomy_guardrails_headings
    assert "## Anti-Work-Evasion" in autonomy_guardrails_headings
    backlog_provider_headings = _heading_lines(BACKLOG_PROVIDER_REFERENCE.read_text(encoding="utf-8"))
    assert "# Backlog Provider Workflow" in backlog_provider_headings
    assert "## Provider Authority" in backlog_provider_headings
    assert "## Board Status" in backlog_provider_headings
    assert "## Current Work And Subtasks" in backlog_provider_headings
    assert "## Stakeholder Questions" in backlog_provider_headings
    assert "## Migration And Export" in backlog_provider_headings
    assert "## Board Order And Epic Scope" in backlog_provider_headings
    status_continuity_headings = _heading_lines(STATUS_CONTINUITY_REFERENCE.read_text(encoding="utf-8"))
    assert "# Status And Continuity" in status_continuity_headings
    assert "## Current Status Truth" in status_continuity_headings
    assert "## Plain-Language Status" in status_continuity_headings
    assert "## Verified Human Instructions" in status_continuity_headings
    assert "## Early-Warning Smoke" in status_continuity_headings
    assert "## Final Preflight Planning Window" in status_continuity_headings
    assert "## Milestone Progress Visibility" in status_continuity_headings
    assert "## Delivery Summaries" in status_continuity_headings
    assert "## Readiness Automation" in status_continuity_headings
    context_continuity_headings = _heading_lines(CONTEXT_CONTINUITY_REFERENCE.read_text(encoding="utf-8"))
    assert "# Context Continuity" in context_continuity_headings
    assert "## Context Continuity" in context_continuity_headings


def test_operating_manual_documents_review_and_chat_workflows():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Iteration Reviews" in headings
    assert "## Deployment Ready Notifications" in headings
    assert "## Product Chat Notes" in headings

    required_phrases = [
        "framework-intake",
        "delivery-summary",
        "session-journal",
        "iteration-review",
        "iteration-review-status --target .",
        "deployment-notification-status --target .",
        "deployment-notification-pipeline-snippet --target .",
        "publish-deploy-ready-update",
        "Agent-session posting is a manual fallback only",
        "milestone-update-status --target .",
        "publish-milestone-update --target .",
        "review folders whose slug does not match the active `goal_id` before any Chat post",
        "short milestone keys such as `M3` are canonicalized to the active milestone title",
        "publish-product-note --target .",
        "validate-iteration-review --target . --file docs/iteration-reviews/<id>/goal-review.json",
        "generate-iteration-review-page --target .",
        "validate-iteration-review` enforces length limits and rejects technical/process jargon in customer-facing fields",
        "publish-iteration-review --target .",
        "Google Chat webhook",
        "The primary stakeholder link is the S3/CloudFront page, not GitHub",
        "musicUrl",
        "built-in SVG poster",
        "Do not commit them",
        "outputs.video: false` disables rendering a recap video",
        "Page output can proceed without media hosting only when the review is strictly text-only",
        "Any screenshot, poster, clip, embedded video, or other generated media used by the page belongs in adapter-approved S3/CloudFront hosting",
        "Boundary notices are non-blocking",
        "Milestone updates are internal operator visibility artifacts",
        "MINERVIT_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK",
        "Session Journals (Local-Only)",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_goal_context_and_archive_workflows():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Goal Orchestration" in headings
    assert "## Context Rotation" in headings
    assert "## Graphify Navigation" in headings

    required_phrases = [
        "METH-FU-BUG-BACKLOG-MANAGEMENT",
        "METH-FU-MILESTONE-CONTINUATION-CONTROLLER",
        "Use semantic versions without leading zeroes",
        "Patch bumps are for narrow fixes and small affordances",
        "minor-line bumps are required for substantial new workflow layers",
        "Adapter-aware bug intake is active through the `bug-intake-triage` skill",
        "milestone-start --target . --plan <source-of-truth-plan>",
        "milestone-advance --target . --event pr-queued --pr <PR>",
        "The milestone ledger is the durable local controller across PR boundaries",
        "Watchdog support is disabled by default unless the adapter opts in",
        "Goal -> Milestone -> PR / tactical item",
        "authorized per-session increment",
        "known operator-input dependencies",
        "soft threshold of `60%` visible context usage, a hard threshold of `75%`, and a `15m` heartbeat",
        "context-rotation-check --target . --boundary pr-queued --context-percent 63 --context-percent-source estimate",
        "Pass `--context-percent-source host` only if the host literally exposes a context-window counter",
        "tautline goal-start --target . --goal <source-of-truth-goal-plan>",
        "backlogProvider",
        "backlog-provider-status --target .",
        "backlog-provider-sync --target . --item <id-or-url> --write",
        "backlog-provider-migration-interview --target . --write",
        "stakeholder-question-ask --target .",
        "stakeholder-question-status --target . --sync",
        "must not implement directly from a GitHub Project item",
        'tautline goal-advance --target . --event milestone-deferred --reason "<policy deferral reason>"',
        "tautline goal-condition --target .",
        "tautline goal-kickoff-prompt --target .",
        "tautline install-claude-launcher --name minervit-claude",
        "tautline install-claude-launcher --name yolo --dangerously-skip-permissions",
        "If an existing shell alias or function named `yolo` exists",
        "MINERVIT_SHOW_GOAL_PROMPT=0",
        "Claude Code `v2.1.139+`",
        ".ai-work/GOAL_RUN.json",
        "## Plain English",
        "there is no session-archive branch",
        "tautline prepare-session-journal --target <lane_path> --stdin",
        "are disabled and refuse in every mode",
        "tautline publish-instrumentation-record --target .",
        "Journal validation rejects raw terminal dumps",
        "sanitized upstream signal comes from instrumentation records",
        "Methodology skills are file-backed policy",
        "run `tautline version --no-remote` and use its `methodology_repo`",
        "Unknown skill` is not a blocker unless those concrete resolution steps fail",
        "Do not write Open Brain, Claude memory, local memory, feedback-memory files, or any other memory note until after the RCA artifact is written, validated, and published",
        "RCA artifacts use the compact `## What happened`, `## Evidence`, `## Root cause`, `## Proposed control`, and `## Validation` sections",
        "Put methodology version/status output in `Evidence`",
        "tautline publish-rca-artifact --file <path> --commit --push",
        "methodology-rca-archive",
        "publishes through an isolated temporary clone to `methodology-rca-archive`",
        "`--allow-release-checkout-write`; that mode is validation/preview-only",
        "copied-but-unpushed archive file is also incomplete",
        "Artifacts land on the maintainer repository's `methodology-rca-archive` branch",
        "context-continuity",
        "Document Context Budget",
        "context-bootstrap --target <lane_path> --write",
        "context-status --target <lane_path> --strict",
        "Historical evidence only. Not current process, scope, or execution authority. Start from <index path>.",
        "tautline graphify-status --target <lane_path>",
        "tautline graphify-install --target <lane_path>",
        "graphify update .",
        "`graphify-out/` is generated local output",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_stack_defaults_and_release_controls():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "### Technical Stack Policy" in headings

    required_phrases = [
        "New projects default to AWS for cloud services",
        "install-claude-launcher --name yolo --dangerously-skip-permissions",
        "The installed launcher lives in `~/.local/bin/minervit-claude` by default",
        "tool default when the adapter is AWS-only",
        "AWS CLI is the default deploy credential path",
        "aws sts get-caller-identity",
        "official AWS CLI installation guide",
        "The release version has one source of truth",
        "Bump `VERSION` for every methodology build that changes reusable framework behavior",
        "Project adapter JSON changes under `adapters/projects/*.json` are project configuration changes and do not require a global methodology version bump",
        "small release-note stub",
        "the full narrative release log lives on",
        "`methodology-release-notes-archive`",
        'publish-release-update --version "$(cat VERSION)"',
        "`CHANGELOG.md`, the release migration report",
        "MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK",
        "Validation requires `VERSION` to match the plugin manifest, first changelog heading, and release-note stub heading",
        "Validation also fails PRs that change reusable methodology/framework files without changing `VERSION`; adapter-only project configuration changes are exempt",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_plan_review_and_hooks():
    text = _operating_reference_corpus()

    required_phrases = [
        "After enabling auto-merge or confirming queue placement, do not schedule a future wakeup, reminder, or monitor prompt that restates completed push, PR creation, labeling, auto-merge, queue, or requeue steps",
        "Exceptional queue checks use the PR `state` field from `gh pr view <PR> --json state` or GraphQL `pullRequest.state` as the terminal signal",
        "Do not use `mergeQueueEntry.estimatedTimeToMerge` as progress",
        "Plan finalization includes asking the human operator to execute or approve implementation",
        "plan-finalization-precheck --target . --plan <source-of-truth-plan>",
        "bin/tautline run-plan-review",
        "bin/tautline finalize-plan-review",
        "Do not run Codex manually and then run `run-plan-review` again just to bind manifest evidence",
        "Do not run `record-plan-review`, hand-edit `.plan-reviews`, disable hooks, skip required `ExitPlanMode` checks, or ask the human operator to choose a bypass",
        "Plan-review convergence is a ladder with a hard cap",
        "targets two review rounds and gets at most four",
        "Rounds 3-4 are self-authorized",
        "transfer into the implementation review focus list",
        "Adapter-declared review exemptions can skip cross-model plan review only when the source-of-truth plan contains `## Plan Review Exemption`",
        "Do not restore plan-review loops that continue past the hard cap of four rounds",
        "accept unverified state, switch tasks, scope down, park the task, or choose a path",
        "record-plan-review` remains available for diagnostics/imports only; it writes `.imported.json` evidence",
        "Cross-Model Review Evidence",
        "Before a multi-round plan-review loop, state the expected round budget and wall-clock estimate",
        "Claude Code `PreToolUse: ExitPlanMode` hooks are mandatory for Claude plan-mode lanes",
        "Claude `PreToolUse: Bash` background-command hooks are mandatory",
        "Claude `Stop` response guards are mandatory",
        "status-report-as-stop on derivable-next-action prompts",
        "terminal continuity omission",
        "Claude `PostToolUseFailure` tool-rejection hooks are mandatory",
        "`lane-start` installs the hook automatically",
        "`methodology-status --fail-on-drift` fails if any required hook is missing",
        "Treat plan-mode exit, execution handoff, ready-for-development marking, plan-only PR pushes, implementation starts, and approval-to-implement prompts as plan finalization",
        "Unclear classification does not default to plan review",
        "Codex CLI finding retrieval is part of the review gate",
        "Do not infer no findings from a missing grep marker",
        "Lane startup never overwrites hand-written `CLAUDE.md` or `AGENTS.md`",
        "adapter_markdown_protected",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_implementation_review_evidence():
    text = _operating_reference_corpus()

    required_phrases = [
        "run one authoring-model native/self-check before R1",
        "round N of the target (or of the hard cap once past it)",
        "Do not restore cross-model plan-review loops that rerun native/Superpowers review before every round instead of one self-check before R1",
        "T2/T3 review additionally requires Stage 1 native review on the exact current assembled diff",
        "Finalization also writes a tracked implementation-review ledger under `<planningArtifacts.sourceOfTruth>/.impl-reviews/`",
        "Project `review.codexWrapper` scripts should review the committed outgoing diff from the adapter/base branch to `HEAD`",
        # Item 48 / Codex R2 P2: this pinned the PRE-0.36.0 budgets, so it was actively holding
        # the operations reference at values the CLI no longer ships. The marker now pins the
        # shipped shape AND the property that made the old numbers dangerous to document -- that
        # the budget is a target, not a ceiling.
        "defaulting to zero Codex rounds for T0, two for T1, three for T2, and four for T3",
        "The budget is a **target, not a ceiling**",
        "generated/derived artifact freshness",
        "Do not restore T2/T3 code-review loops that hand a changed assembled diff back to Codex/Stage 2 before native/Superpowers review",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_event_logs_and_usage_accounting():
    text = _operating_reference_corpus()
    normalized = " ".join(text.split())
    headings = _heading_lines(text)

    assert "## Repo Event Logs" in headings
    assert "## Usage Accounting" in headings

    required_phrases = [
        "tautline event-log-path --target .",
        "tautline event-viewer --target .",
        "tautline event-audit --target . --since 24h --strict",
        "tautline usage-report --target . --since 7d --by product",
        "The first implementation stores local JSONL evidence",
    ]
    _assert_contains_all(text, required_phrases)
    assert "They must never write `events.log` or `events.jsonl` directly" in normalized


def test_operating_manual_documents_behavior_specs_and_portable_cli_bootstrap():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Behavior Specs And Source Materials" in headings

    required_phrases = [
        "Those materials are upstream source material, not inspiration",
        "Adapters may declare `behaviorSpecs.sourceMaterials`",
        "must include `## Behavior Source Materials`",
        "BEHAVIOR-SOURCE-EXEMPT: <real reason>",
        "set -euo pipefail",
        "bin/tautline install-cli",
        "tautline sync-methodology",
        "TAUTLINE_METHODOLOGY_REPO",
        'if test -f "$HOME/.config/tautline/tautline.env"; then',
        ': "${TAUTLINE_METHODOLOGY_REPO:?missing methodology env; run <methodology_repo>/bin/tautline install-cli}"',
        "Generated adapters and handoffs must not hard-code person-specific checkout paths",
        "tautline version",
        "Resolve the methodology CLI before running those gates",
        "If it is missing from `PATH` or exits 127/command-not-found",
        "A missing `PATH` entry is not a failed methodology gate",
        "missing CLI access is a true blocker only after the portable checkout fallback cannot be found",
        "not a reason to ask for a person-specific checkout path",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_status_monitor_and_review_evidence():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Current Status Truth" in headings

    required_phrases = [
        "monitor-status --target <lane_path>",
        "response-guard --stdin --active-monitor",
        "background-run --timeout-seconds <seconds>",
        "watchdog state when configured",
        "fresh log without verified PID liveness is not proof",
        "A live but idle process with no progress past the stale threshold is stale/hung",
        "Unlocked adapter-backed lanes do not raw-pull the latest methodology by default",
        "tautline latest-code-status --target . --write",
        "remote branches ahead of base, and lists open PRs",
        "Answer from fetched `origin/main`, GitHub PR/check evidence, ahead remote-branch evidence",
        "Latest-code baseline is mandatory before deep codebase analysis",
        "Do not spend an analysis budget on stale code",
        "sourceAdapterSha256` mismatch, a stale or transient `minervit-local-rescue/*`",
        "surfaces `latest_code_adapter_drift`",
        "ahead-branch/open-PR or soft-offline heads-up",
        "$TAUTLINE_METHODOLOGY_REPO/bin/tautline",
        "branch-liveness-check --target .",
        "branch-liveness-check --target . --strict",
        "review-evidence-check --target . --strict",
        "finalize-implementation-review --target . --manifest <manifest>",
        "Subagent or per-item reviews do not replace the assembled-diff review",
        "A queued, auto-merge-enabled, merged, or closed PR branch is no longer active work",
        "`No work-in-flight` after a prior PR landed is not a human-routing prompt",
        "It must not ask the human operator to choose cleanup, next backlog item, or something else",
        "Commit adapter drift only when the project tracks generated adapter files and the diff is solely methodology-generated",
        "never commit lane-local state or unrelated product changes",
        "Any direction-asking question after the previous PR landed and no work is in flight is a stop-menu violation",
        "without presenting cleanup/backlog/something-else options",
        "Git `pre-commit` and `pre-push` hooks are mandatory",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_milestone_visibility_memory_and_continuity():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Milestone Progress Visibility" in headings
    assert "## Context Continuity" in headings

    required_phrases = [
        "Before the first code edit, implementation command, PR worktree creation, or tactical subagent dispatch",
        "realistic wall-clock estimate or range for the current session",
        "Materially different means a different goal, milestone, source-of-truth plan, execution-packet item, PR branch/worktree, deployment target, or user-visible capability",
        "estimate the percent of planned work complete",
        "state `percent unknown`, name the exact blocker",
        "create, test, and tear down an isolated validation environment repeatably",
        "Cached host plugin metadata is not a lane update failure",
        "do not ask the human operator to decide whether to inspect version/status",
        "Process rules must never come from memories",
        "violated rule, expected behavior, and RCA root cause must cite the canonical methodology",
        "In RCA and decision traces, do not cite Open Brain, Claude memories, local memories, or feedback-memory files",
        "Process never comes from Open Brain, Claude memories, local memories, or feedback-memory files",
        "Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping",
        "Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session",
        "Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal",
        "A portable fallback through `$HOME/.config/tautline/tautline.env` or `$TAUTLINE_METHODOLOGY_REPO/bin/tautline` when `tautline` is missing from `PATH` or exits 127/command-not-found",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_planning_and_document_context_strictness():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Document Context Budget" in headings

    required_phrases = [
        "No implementation-ready plan on deck is not a stop condition",
        "Claude plan mode can supply `ExitPlanMode` with a random scratch path",
        "This is not plan approval and not approval to implement",
        "Planning is automatic and routine",
        "Strict mode exits non-zero for missing indexes, oversized indexes, unclassified tracked Markdown, missing archive headers, or generated adapter drift",
        "methodology-status --strict --fail-on-drift",
        "Strict mode validates filesystem and index state. It does not sandbox or observe every file an AI agent reads",
        "Explicit `documentContext` paths must be project-relative or home-relative",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_backlog_export_and_provider_status():
    text = _operating_reference_corpus()

    required_phrases = [
        "Export creates a real, numbered repository issue in the adapter `repo`",
        "Board-only GitHub Project draft items are not the default and require explicit `--draft`",
        "Provider-backed status is live operational state",
        "GitHub issue comments are useful evidence, but they do not replace the structured Project `Status` field",
        "This applies to stakeholder-tracked, board-backed subtasks",
        "Parent issue status is not a substitute for board-backed subtask status",
        "a board-backed subtask in an active status means its parent issue must be active too",
        "That write refreshes the repo plan and moves the selected board item plus any board-backed native subtasks",
        "sanctioned subtask active-status moves reconcile the native parent active too",
        "A native subtask missing from the board blocks parent Done",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_database_migration_and_plan_review_timeout():
    text = _operating_reference_corpus()
    headings = _heading_lines(text)

    assert "## Database Migration Collisions" in headings
    required_phrases = [
        "database-migration-collision",
        "run-plan-review --no-output-timeout-seconds",
    ]
    _assert_contains_all(text, required_phrases)


def test_operating_manual_documents_adapter_bootstrap_boundaries():
    text = _operating_reference_corpus()

    required_phrases = [
        "The adapter bootstrap interview is mandatory before first adapter render/write",
        'Generic executor banners such as "greenfield execution mode"',
        "Another project's adapter may be used only as a structural field reference",
    ]
    _assert_contains_all(text, required_phrases)


def test_public_readme_does_not_duplicate_operating_manual_detail():
    text = README.read_text(encoding="utf-8")

    detailed_phrases = [
        "Export creates a real, numbered repository issue in the adapter `repo`",
        "Board-only GitHub Project draft items are not the default and require explicit `--draft`",
        "Provider-backed status is live operational state",
        "GitHub issue comments are useful evidence, but they do not replace the structured Project `Status` field",
        "## Database Migration Collisions",
        "database-migration-collision",
        "run-plan-review --no-output-timeout-seconds",
        "The adapter bootstrap interview is mandatory before first adapter render/write",
        'Generic executor banners such as "greenfield execution mode"',
        "Another project's adapter may be used only as a structural field reference",
    ]
    _assert_contains_none(text, detailed_phrases)
