import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EXPORT_MARKER = ROOT / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; its subject files are export-excluded",
)
CANONICAL = ROOT / "methodology" / "canonical-rules.md"
METHODOLOGY_BACKLOG = ROOT / "docs" / "backlog" / "methodology-backlog.md"
PLUGIN_CHANGELOG = ROOT / "plugins" / "tautline-core" / "CHANGELOG.md"
PLUGIN_RELEASE_NOTES = ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md"
CORE_SKILLS = ROOT / "plugins" / "tautline-core" / "skills"
OPS_SKILLS = ROOT / "plugins" / "tautline-ops" / "skills"


def _assert_contains_all(path: Path, phrases: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [phrase for phrase in phrases if phrase not in text]
    assert missing == [], f"{path.relative_to(ROOT)} missing: {missing}"


def _assert_has_heading(path: Path, heading: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert heading in lines, f"{path.relative_to(ROOT)} missing heading: {heading}"


def test_repository_templates_schema_and_governance_contracts():
    pull_request_template = ROOT / ".github" / "pull_request_template.md"
    validate_workflow = ROOT / ".github" / "workflows" / "validate.yml"

    assert pull_request_template.exists()
    assert validate_workflow.exists()
    _assert_contains_all(pull_request_template, ["Problem Or Evidence"])
    _assert_contains_all(validate_workflow, ["scripts/validate.sh"])
    _assert_contains_all(ROOT / "methodology" / "adapter-schema.json", ["deploymentTargets", "reviewExemptions"])
    _assert_contains_all(
        ROOT / "docs" / "governance" / "methodology-change-governance.md",
        ["Methodology Repository Governance", "Session Journal Evidence"],
    )


def test_release_and_adapter_config_contracts():
    _assert_contains_all(
        ROOT / "docs" / "reference" / "operations" / "setup-runtime.md",
        [
            "Project adapter JSON changes under `adapters/projects/*.json` are project configuration changes",
            "release-note stub",
            "release migration report",
        ],
    )
    _assert_contains_all(
        ROOT / "docs" / "reference" / "operations" / "cli-operations.md",
        [
            "render-adapters --write` refuses to overwrite an existing `CLAUDE.md` or `AGENTS.md`",
        ],
    )
    _assert_contains_all(CANONICAL, ["render-adapters --write --json-only"])
    _assert_contains_all(ROOT / "docs" / "reference" / "operations" / "runtime-evidence.md", ["event-viewer"])
    _assert_contains_all(
        ROOT / "docs" / "reference" / "operations" / "workflow-guardrails.md",
        ["cumulative foreground loop expected to exceed 10 minutes is monitored-class work"],
    )
    _assert_contains_all(
        ROOT / "docs" / "reference" / "operations" / "runtime-evidence.md",
        ["repo-scoped event logs for live human tailing and AI/process audits"],
    )
    _assert_contains_all(
        ROOT / "docs" / "reference" / "operations" / "goal-execution.md",
        ["context-rotation heartbeat for long Claude `/goal` runs"],
    )
    _assert_contains_all(PLUGIN_RELEASE_NOTES, ["methodology-release-notes-archive", "CHANGELOG.md"])
    _assert_contains_all(ROOT / "tests" / "test_release_change_contract.py", ["_project_adapter_config_only"])


def test_generated_adapter_and_review_policy_contracts():
    _assert_contains_all(
        CANONICAL,
        [
            "Agents must not stop to ask whether to cut a methodology release for an adapter-only PR",
            "Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`",
            "render-adapters --write --json-only",
            "review.codexFastMode",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "lane-lifecycle"
        / "references"
        / "lane-lifecycle-policy.md",
        [
            "Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`",
            "`$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology`",
            "`$HOME/.config/minervit/methodology.env`",
            "not a reason to ask for a person-specific checkout path",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "review-before-push"
        / "references"
        / "review-before-push-policy.md",
        ["generated/derived artifact freshness"],
    )


def test_canonical_memory_review_handoff_and_planning_contracts():
    canonical_lines = CANONICAL.read_text(encoding="utf-8").splitlines()
    _assert_contains_all(
        CANONICAL,
        [
            "If the adapter declares reviewed behavior-spec source materials, treat them as upstream source material, not inspiration",
            "must include `## Behavior Source Materials`",
            "BEHAVIOR-SOURCE-EXEMPT: <real reason>",
            "Plan-review convergence is a ladder",
            "rounds 3-4 self-authorize with a recorded `--exception-note`, never an operator escalation",
            "transfer into the implementation review focus list",
            'When explaining "what the rule says," a violated rule, expected behavior, or an RCA root cause',
            "Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping",
            "Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal",
            "If no goal ledger next action, execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates",
            "For T0/T1 work, use a brief inline/packet plan or the minimal adapter-required artifact",
            "Goal -> Milestone -> PR/tactical item",
            "adapter `backlogProvider.enabled` is true",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "delivery-summary"
        / "references"
        / "delivery-summary-policy.md",
        [
            "grounded progress narrative",
            "what capability was unlocked for users, admins, operators, or delivery velocity",
            "Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session",
        ],
    )
    _assert_contains_all(
        OPS_SKILLS / "usage-accounting" / "references" / "usage-accounting-policy.md",
        ["Usage accounting is local operational evidence"],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "review-before-push"
        / "references"
        / "review-before-push-policy.md",
        [
            "Do not infer \"no findings\" from a failed grep",
            "A clean Codex review claim must cite the inspected review artifact",
        ],
    )
    assert "## Goal Orchestration" in canonical_lines


def test_board_goal_and_context_rotation_contracts_remain_pinned():
    _assert_contains_all(
        CANONICAL,
        [
            "The board-currency gate is scope-aware",
            "Filing a customer-facing bug is not complete until it is on the board",
            "Retire the active goal ledger when its initiative ships",
            "For a goal whose source-of-truth plan explicitly declares multi-session scope",
            "`goal-next` and `goal-status` must surface known operator-input dependencies",
            "tautline goal-start --target . --goal <source-of-truth-goal-plan>",
            "milestone-deferred",
            "Milestone completion requires validation proof or a linked milestone ledger",
            "goal-condition --target .",
            "Claude Code `v2.1.139+`",
            "soft threshold `60%`, hard threshold `75%`, and a `15m` long-goal heartbeat",
            "context-rotation-check --target . --boundary <boundary> --context-percent <percent> --context-percent-source estimate",
            "An estimated percent can recommend rotation but never make it mandatory",
            "context exhaustion alone is not goal completion",
            "A self-asserted or estimated context percentage is advisory only and is never a mandatory-rotation trigger or a stop, defer, or handoff reason",
            "A mandatory rotation triggers only on a real host-exposed (measured) context percentage",
        ],
    )
    _assert_has_heading(CANONICAL, "## Context Rotation")


def test_grooming_dor_and_backlog_epic_skill_contracts_remain_pinned():
    backlog_epic_grooming = (
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "backlog-epic-grooming"
        / "SKILL.md"
    )
    backlog_epic_grooming_reference = (
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "backlog-epic-grooming"
        / "references"
        / "backlog-epic-grooming-policy.md"
    )
    _assert_contains_all(
        CANONICAL,
        [
            "Every epic carries a methodology-owned grooming Definition of Ready",
            "distinct from plan-review cap/focus-transfer handling",
            "validate-grooming` reports DoR pass/fail read-only",
        ],
    )
    assert backlog_epic_grooming.exists()
    _assert_contains_all(
        backlog_epic_grooming,
        [
            "name: backlog-epic-grooming",
            "references/backlog-epic-grooming-policy.md",
        ],
    )
    _assert_contains_all(
        backlog_epic_grooming_reference,
        [
            "## Done-When Checklist",
            "<EPIC_FIELD>",
            "grooming_feature_series_field_unreadable",
        ],
    )


def test_boundary_milestone_and_context_budget_contracts_remain_pinned():
    _assert_contains_all(
        CANONICAL,
        [
            "do not describe context exhaustion as the reason to stop working",
            "only you can trigger /compact",
            "Do not broad-load Markdown trees, all plans, all docs, or archive directories for routine startup context",
            "A bounded Markdown audit must name the question, target files or globs, and an upper bound of 20 Markdown files",
            "Archived or historical docs are evidence only",
            "context-status --strict` fails for missing indexes",
            "methodology-status --strict --fail-on-drift` temporarily enforces document-context strictness",
            "Strict mode validates filesystem and index state. It is not a runtime read sandbox",
            "Explicit `documentContext` paths must be project-relative or home-relative",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "delivery-summary"
        / "references"
        / "delivery-summary-policy.md",
        [
            "Boundary summaries for delivery, PR, milestone, goal, session, and handoff-for-review events must lead with the plain-language outcome and next action",
            "tautline milestone-advance --target . --event pr-queued --pr <PR>",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "execution-packet-work-loop"
        / "references"
        / "execution-packet-policy.md",
        [
            "The default ledger path is `.ai-work/MILESTONE_RUN.json`",
            "At PR boundaries, `milestone-next` is the controller",
            "Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work",
        ],
    )
    _assert_contains_all(
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "lane-lifecycle"
        / "references"
        / "lane-lifecycle-policy.md",
        ["optional watchdog only surfaces stale runs; it is not process authority"],
    )
    _assert_has_heading(CANONICAL, "## Document Context Budget")


def test_graphify_database_migration_and_event_contracts_remain_pinned():
    database_migration_skill = (
        OPS_SKILLS / "database-migration-collision" / "SKILL.md"
    )
    _assert_contains_all(
        CANONICAL,
        [
            "This is a token-budget control",
            "refresh the graph with `graphify update .`",
            "`graphify-out/` is generated local output",
            "database-migration-collision",
            "long `/goal` heartbeat",
        ],
    )
    _assert_contains_all(
        OPS_SKILLS / "event-observability" / "SKILL.md",
        [
            "Event logs are local operational evidence",
            "tautline log-event --target .",
            "Never write `events.log` or `events.jsonl` directly",
        ],
    )
    _assert_has_heading(CANONICAL, "## Graphify Navigation")
    _assert_has_heading(CANONICAL, "## Database Migration Collisions")
    assert database_migration_skill.is_file(), (
        f"{database_migration_skill.relative_to(ROOT)} missing or not a file"
    )
    _assert_contains_all(
        database_migration_skill,
        [
            "name: database-migration-collision",
            "next free index",
            "snapshot metadata",
            "migration journal",
        ],
    )


def test_lane_lifecycle_update_and_cli_resolution_contracts_remain_pinned():
    lane_lifecycle_policy = (
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "lane-lifecycle"
        / "references"
        / "lane-lifecycle-policy.md"
    )
    _assert_contains_all(
        lane_lifecycle_policy,
        [
            "Unlocked adapter-backed product/client lanes do not raw-pull latest methodology by default",
            "Resolve the methodology CLI before running startup gates",
            "If it is missing from `PATH` or exits 127/command-not-found",
            "MINERVIT_METHODOLOGY_REPO",
        ],
    )


def test_product_isolated_cli_resolution_and_cost_prompt_contracts_remain_pinned():
    risk_tier_policy = (
        ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "risk-tier-autonomy"
        / "references"
        / "risk-tier-policy.md"
    )
    _assert_contains_all(
        CANONICAL,
        [
            "Methodology CLI resolution is product-isolated",
        ],
    )
    _assert_contains_all(
        risk_tier_policy,
        [
            "Cost-prompt provocation",
        ],
    )


@private_repo_only
def test_methodology_backlog_contract_markers_remain_present():
    _assert_contains_all(
        METHODOLOGY_BACKLOG,
        [
            "METH-FU-MID-SESSION-METHODOLOGY-CONTRACT-PINNING",
            "METH-FU-DERIVED-ARTIFACT-FRESHNESS-GATE",
            "METH-FU-MEASURED-CONTEXT-ROTATION-GUARD",
            "METH-FU-GOAL-CLOSEOUT-PENDING-REVIEW-GUARD",
        ],
    )


def test_usage_accounting_skill_title_remains_publicly_discoverable():
    _assert_contains_all(
        OPS_SKILLS / "usage-accounting" / "SKILL.md",
        ["Usage Accounting"],
    )


def test_every_default_graphify_key_is_published_in_the_adapter_schema(cli):
    """Defaults and the published contract must stay in lockstep, key for key.

    `properties.graphify` carries no `additionalProperties: false` (unlike the root object), so
    a new default key silently escapes `methodology/adapter-schema.json` -- the schema this repo
    serves as its public adapter contract. That is how two required keys could ship undocumented.
    Closing the class, not the instance: this asserts the whole key set, so the NEXT default added
    to DEFAULT_GRAPHIFY fails here until it is published too.
    """
    schema = json.loads((ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8"))
    published = set(schema["properties"]["graphify"]["properties"])
    missing = sorted(set(cli.DEFAULT_GRAPHIFY) - published)
    assert missing == [], (
        f"DEFAULT_GRAPHIFY keys absent from the published adapter schema: {missing}"
    )
