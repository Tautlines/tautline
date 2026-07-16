import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_RULES = ROOT / "methodology" / "canonical-rules.md"
CODEX_PLUGIN_MANIFEST = (
    ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
)
PLUGIN_SKILL_ROOTS = (
    ROOT / "plugins" / "tautline-core" / "skills",
    ROOT / "plugins" / "tautline-ops" / "skills",
)
CORE_SKILL_ROOT = ROOT / "plugins" / "tautline-core" / "skills"
MAX_CORE_SKILL_MD_LINES = 45
MAX_CORE_SKILL_MD_TOTAL_LINES = 1200
CORE_OPS_PROVIDER_TERMS = (
    "Google Chat",
    "S3",
    "CloudFront",
    "Baretail",
    "Drizzle",
    "drizzle-kit",
)
RISK_TIER_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "risk-tier-autonomy"
    / "SKILL.md"
)
RISK_TIER_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "risk-tier-autonomy"
    / "references"
    / "risk-tier-policy.md"
)
GOAL_ORCHESTRATION_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "goal-orchestration"
    / "SKILL.md"
)
GOAL_ORCHESTRATION_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "goal-orchestration"
    / "references"
    / "goal-orchestration-policy.md"
)
EXECUTION_PACKET_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "execution-packet-work-loop"
    / "SKILL.md"
)
EXECUTION_PACKET_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "execution-packet-work-loop"
    / "references"
    / "execution-packet-policy.md"
)
HUMAN_INSTRUCTIONS_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "human-instructions"
    / "SKILL.md"
)
HUMAN_INSTRUCTIONS_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "human-instructions"
    / "references"
    / "human-instructions-policy.md"
)
BEHAVIOR_SPECS_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "behavior-specs"
    / "SKILL.md"
)
BEHAVIOR_SPECS_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "behavior-specs"
    / "references"
    / "behavior-specs-policy.md"
)
REVIEW_BEFORE_PUSH_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "review-before-push"
    / "SKILL.md"
)
REVIEW_BEFORE_PUSH_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "review-before-push"
    / "references"
    / "review-before-push-policy.md"
)
DOCUMENT_CONTEXT_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "SKILL.md"
)
DOCUMENT_CONTEXT_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "references"
    / "context-continuity-policy.md"
)
USAGE_ACCOUNTING_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "usage-accounting"
    / "SKILL.md"
)
USAGE_ACCOUNTING_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "usage-accounting"
    / "references"
    / "usage-accounting-policy.md"
)
STAKEHOLDER_QUESTIONS_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "stakeholder-questions"
    / "SKILL.md"
)
STAKEHOLDER_QUESTIONS_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "stakeholder-questions"
    / "references"
    / "stakeholder-questions-policy.md"
)
FRAMEWORK_INTAKE_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "framework-intake"
    / "SKILL.md"
)
FRAMEWORK_INTAKE_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "framework-intake"
    / "references"
    / "framework-intake-policy.md"
)
RULES_AUDIT_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "rules-audit"
    / "SKILL.md"
)
RULES_AUDIT_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "rules-audit"
    / "references"
    / "rules-audit-policy.md"
)
BOARD_ADOPTION_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "board-adoption"
    / "SKILL.md"
)
BOARD_ADOPTION_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "board-adoption"
    / "references"
    / "board-adoption-policy.md"
)
DELIVERY_SUMMARY_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "delivery-summary"
    / "SKILL.md"
)
DELIVERY_SUMMARY_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "delivery-summary"
    / "references"
    / "delivery-summary-policy.md"
)
MILESTONE_UPDATE_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "milestone-update"
    / "SKILL.md"
)
MILESTONE_UPDATE_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "milestone-update"
    / "references"
    / "milestone-update-policy.md"
)
GRAPHIFY_NAVIGATION_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "graphify-navigation"
    / "SKILL.md"
)
GRAPHIFY_NAVIGATION_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "graphify-navigation"
    / "references"
    / "graphify-navigation-policy.md"
)
LANE_LIFECYCLE_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "lane-lifecycle"
    / "SKILL.md"
)
LANE_LIFECYCLE_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "lane-lifecycle"
    / "references"
    / "lane-lifecycle-policy.md"
)
LANE_COORDINATION_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "lane-coordination"
    / "SKILL.md"
)
LANE_COORDINATION_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "lane-coordination"
    / "references"
    / "lane-coordination-policy.md"
)
EVENT_OBSERVABILITY_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "event-observability"
    / "SKILL.md"
)
EVENT_OBSERVABILITY_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "event-observability"
    / "references"
    / "event-observability-policy.md"
)
SESSION_JOURNAL_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "session-journal"
    / "SKILL.md"
)
SESSION_JOURNAL_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "session-journal"
    / "references"
    / "session-journal-policy.md"
)
BACKGROUND_MONITORING_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "background-task-monitoring"
    / "SKILL.md"
)
BACKGROUND_MONITORING_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "background-task-monitoring"
    / "references"
    / "background-monitoring-policy.md"
)
BACKLOG_EPIC_GROOMING_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "backlog-epic-grooming"
    / "SKILL.md"
)
BACKLOG_EPIC_GROOMING_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "backlog-epic-grooming"
    / "references"
    / "backlog-epic-grooming-policy.md"
)
DATABASE_MIGRATION_COLLISION_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "database-migration-collision"
    / "SKILL.md"
)
DATABASE_MIGRATION_COLLISION_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "database-migration-collision"
    / "references"
    / "database-migration-collision-policy.md"
)
MERGE_QUEUE_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "merge-queue-monitoring"
    / "SKILL.md"
)
MERGE_QUEUE_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "merge-queue-monitoring"
    / "references"
    / "merge-queue-policy.md"
)
CONTEXT_CONTINUITY_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "SKILL.md"
)
CONTEXT_CONTINUITY_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "references"
    / "context-continuity-policy.md"
)
ITERATION_REVIEW_SKILL = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "iteration-review"
    / "SKILL.md"
)
ITERATION_REVIEW_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "iteration-review"
    / "references"
    / "iteration-review-policy.md"
)
PROJECT_BOOTSTRAP_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "project-bootstrap"
    / "SKILL.md"
)
PROJECT_BOOTSTRAP_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "project-bootstrap"
    / "references"
    / "project-bootstrap-policy.md"
)
BOARD_ITEM_UPDATES_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "board-item-updates"
    / "SKILL.md"
)
BOARD_ITEM_UPDATES_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "board-item-updates"
    / "references"
    / "board-item-updates-policy.md"
)
BUG_INTAKE_TRIAGE_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "bug-intake-triage"
    / "SKILL.md"
)
EXAMPLE_SERVICE_PREFLIGHT_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "examples"
    / "example-service-preflight"
    / "SKILL.md"
)
EXAMPLE_SERVICE_PREFLIGHT_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "examples"
    / "example-service-preflight"
    / "references"
    / "example-service-preflight-policy.md"
)
MAKERKIT_IMPLEMENTATION_SKILL = (
    ROOT
    / "examples"
    / "community-skills"
    / "makerkit-implementation"
    / "SKILL.md"
)
MAKERKIT_IMPLEMENTATION_REFERENCE = (
    ROOT
    / "examples"
    / "community-skills"
    / "makerkit-implementation"
    / "references"
    / "makerkit-implementation-policy.md"
)


def _stripped_lines(text):
    return {line.strip() for line in text.splitlines()}


def _assert_thin_skill_entrypoint(path, name, reference, required=(), forbidden=()):
    text = path.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.splitlines()) <= MAX_CORE_SKILL_MD_LINES
    assert len(text.split()) <= 500
    assert f"name: {name}" in lines
    assert str(reference.relative_to(path.parent)) in text
    assert (
        "## Fast Path" in text
        or "## RCA Fast Path" in text
        or "## Feature Request Fast Path" in text
    )
    for phrase in required:
        assert phrase in text or phrase in normalized
    for phrase in forbidden:
        assert phrase not in text and phrase not in normalized
    return text, normalized


def test_core_skill_entrypoints_stay_thin():
    skill_files = sorted(
        path
        for path in CORE_SKILL_ROOT.glob("*/SKILL.md")
        if path.parent.name != "examples"
    )
    line_counts = {path.parent.name: len(path.read_text(encoding="utf-8").splitlines()) for path in skill_files}

    assert {name: count for name, count in line_counts.items() if count > MAX_CORE_SKILL_MD_LINES} == {}
    assert sum(line_counts.values()) <= MAX_CORE_SKILL_MD_TOTAL_LINES


def test_core_plugin_references_do_not_carry_ops_provider_detail():
    # No exclusion for the examples/ subtree: MakerKit/Drizzle content moved
    # to examples/community-skills/makerkit-implementation/,
    # so the core plugin (examples/ included) must carry zero
    # Drizzle/ops-provider content.
    scoped_files = list(CORE_SKILL_ROOT.rglob("*.md"))

    offenders = []
    for path in scoped_files:
        text = path.read_text(encoding="utf-8")
        for term in CORE_OPS_PROVIDER_TERMS:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {term}")

    assert offenders == []


def _plugin_skill_root(path):
    for root in PLUGIN_SKILL_ROOTS:
        if path.is_relative_to(root):
            return root
    raise AssertionError(f"{path} is not under a packaged skill root")


def _packaged_markdown_files():
    files = []
    for root in PLUGIN_SKILL_ROOTS:
        files.extend(sorted(root.rglob("*.md")))
    return files


def _relative_markdown_targets(text):
    targets = set()
    for match in re.finditer(r"\]\(([^)]+\.md)(?:#[^)]+)?\)", text):
        target = match.group(1)
        if _is_packaged_markdown_reference(target):
            targets.add(target)
    for match in re.finditer(r"`([^`]+\.md)`", text):
        target = match.group(1)
        if _is_packaged_markdown_reference(target):
            targets.add(target)
    return sorted(targets)


def _is_packaged_markdown_reference(target):
    normalized = target.replace("\\", "/")
    return (
        normalized.startswith("references/")
        or normalized.startswith("../")
        or "/references/" in normalized
        or normalized == "DATA-CONTRACT.md"
    )


def test_packaged_skill_markdown_references_resolve_after_ops_split():
    missing = []
    for path in _packaged_markdown_files():
        text = path.read_text(encoding="utf-8")
        for target in _relative_markdown_targets(text):
            if "://" in target or target.startswith("#") or target.startswith("/"):
                continue
            resolved = (path.parent / target).resolve(strict=False)
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                missing.append(f"{path.relative_to(ROOT)} escapes repo via {target}")
                continue
            if not resolved.exists():
                missing.append(f"{path.relative_to(ROOT)} -> {target}")

    assert missing == []


def test_codex_plugin_packages_split_skill_references():
    manifest = json.loads(CODEX_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    split_pairs = [
        (RISK_TIER_SKILL, RISK_TIER_REFERENCE),
        (GOAL_ORCHESTRATION_SKILL, GOAL_ORCHESTRATION_REFERENCE),
        (EXECUTION_PACKET_SKILL, EXECUTION_PACKET_REFERENCE),
        (HUMAN_INSTRUCTIONS_SKILL, HUMAN_INSTRUCTIONS_REFERENCE),
        (BEHAVIOR_SPECS_SKILL, BEHAVIOR_SPECS_REFERENCE),
        (REVIEW_BEFORE_PUSH_SKILL, REVIEW_BEFORE_PUSH_REFERENCE),
        (DOCUMENT_CONTEXT_SKILL, DOCUMENT_CONTEXT_REFERENCE),
        (USAGE_ACCOUNTING_SKILL, USAGE_ACCOUNTING_REFERENCE),
        (STAKEHOLDER_QUESTIONS_SKILL, STAKEHOLDER_QUESTIONS_REFERENCE),
        (RULES_AUDIT_SKILL, RULES_AUDIT_REFERENCE),
        (BOARD_ADOPTION_SKILL, BOARD_ADOPTION_REFERENCE),
        (DELIVERY_SUMMARY_SKILL, DELIVERY_SUMMARY_REFERENCE),
        (MILESTONE_UPDATE_SKILL, MILESTONE_UPDATE_REFERENCE),
        (GRAPHIFY_NAVIGATION_SKILL, GRAPHIFY_NAVIGATION_REFERENCE),
        (LANE_LIFECYCLE_SKILL, LANE_LIFECYCLE_REFERENCE),
        (LANE_COORDINATION_SKILL, LANE_COORDINATION_REFERENCE),
        (EVENT_OBSERVABILITY_SKILL, EVENT_OBSERVABILITY_REFERENCE),
        (SESSION_JOURNAL_SKILL, SESSION_JOURNAL_REFERENCE),
        (BACKGROUND_MONITORING_SKILL, BACKGROUND_MONITORING_REFERENCE),
        (BACKLOG_EPIC_GROOMING_SKILL, BACKLOG_EPIC_GROOMING_REFERENCE),
        (DATABASE_MIGRATION_COLLISION_SKILL, DATABASE_MIGRATION_COLLISION_REFERENCE),
        (MERGE_QUEUE_SKILL, MERGE_QUEUE_REFERENCE),
        (CONTEXT_CONTINUITY_SKILL, CONTEXT_CONTINUITY_REFERENCE),
        (ITERATION_REVIEW_SKILL, ITERATION_REVIEW_REFERENCE),
        (PROJECT_BOOTSTRAP_SKILL, PROJECT_BOOTSTRAP_REFERENCE),
        (BOARD_ITEM_UPDATES_SKILL, BOARD_ITEM_UPDATES_REFERENCE),
        (EXAMPLE_SERVICE_PREFLIGHT_SKILL, EXAMPLE_SERVICE_PREFLIGHT_REFERENCE),
    ]
    # makerkit-implementation is intentionally excluded: it moved to
    # examples/community-skills/ (structure: move stack-specific makerkit example out of
    # core plugin) and is no longer packaged with either plugin's manifest.

    assert manifest["skills"] == "./skills/"
    for skill, reference in split_pairs:
        assert skill.exists()
        assert reference.exists()
        skills_root = _plugin_skill_root(reference)
        reference.relative_to(skills_root)
        assert reference.parent.name == "references"
        assert str(reference.relative_to(skill.parent)) in skill.read_text(encoding="utf-8")


def test_risk_tier_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        RISK_TIER_SKILL,
        "risk-tier-autonomy",
        RISK_TIER_REFERENCE,
        required=(
            "## Non-Negotiables",
            "## Required Follow-Through",
            "Routine reviewed deploy/push closeout is agent-owned",
        ),
    )


def test_risk_tier_reference_retains_detailed_policy():
    text = RISK_TIER_REFERENCE.read_text(encoding="utf-8")

    assert len(text.split()) >= 2500
    assert text.startswith("# Risk-Tier Autonomy Policy Reference")
    assert (
        "T2/T3 cross-model implementation review must be preceded by Stage 1 native review"
        in text
    )
    assert "Routine deploy-to-close work is agent-owned" in text
    assert (
        "Do not cite Open Brain, Claude memories, local memories, or feedback-memory files as `the rule`"
        in text
    )


def test_risk_tier_plan_review_finalization_is_numbered_procedure():
    text = RISK_TIER_REFERENCE.read_text(encoding="utf-8")
    section = text.split("## Plan Review Finalization Procedure", 1)[1].split(
        "## Plan Review Convergence", 1
    )[0]

    assert "1. Confirm the risk tier." in section
    assert "2. Honor only valid exemptions." in section
    assert "3. For T2/T3 plan review" in section
    assert "4. Inspect and classify the printed log." in section
    assert "5. If Codex reports Critical/P1" in section
    assert "6. Then run `minervit-methodology plan-finalization-precheck --target . --plan <source-of-truth-plan>`" in section
    assert "7. Do not rerun Codex just to bind manifest evidence." in section
    assert (
        "Do not ask whether to execute, implement, approve, discuss with the human operator first"
        in section
    )
    assert max(len(paragraph.split()) for paragraph in section.split("\n\n")) <= 220


def test_risk_tier_requires_proof_of_done_before_implementation():
    skill_text = RISK_TIER_SKILL.read_text(encoding="utf-8")
    reference = RISK_TIER_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(reference.split())

    assert "proof-of-done evidence" in skill_text
    assert "`@pending`/pending/skipped/disabled/quarantined/wrong-target tests are gaps" in skill_text
    assert "proof-of-done standard" in reference
    assert "would make completion believable before implementation starts" in normalized
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof" in reference


def test_goal_orchestration_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        GOAL_ORCHESTRATION_SKILL,
        "goal-orchestration",
        GOAL_ORCHESTRATION_REFERENCE,
        required=(
            "Goal -> Milestone -> PR / tactical item",
            "minervit-methodology goal-next --target .",
            "Planning counts as starting",
            "Done = shipped",
        ),
    )


def test_goal_orchestration_reference_retains_detailed_policy():
    text = GOAL_ORCHESTRATION_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2500
    assert text.startswith("# Goal Orchestration Policy Reference")
    assert "Goal -> Milestone -> PR / tactical item" in text
    assert ".ai-work/GOAL_RUN.json" in text
    assert "backlogProvider.completionUnit" in text
    assert "Provider-backed board status is live operational state" in text
    assert "Free-text issue comments do not replace the structured board `Status` field" in normalized
    assert "The board-currency gate is scope-aware" in text
    assert "Planning counts as starting" in text
    assert "filing a customer-facing bug is not done until it is on the board" in normalized
    assert "minervit-methodology backlog-provider-status --target ." in text
    assert "minervit-methodology backlog-provider-next --target ." in text
    assert "minervit-methodology backlog-provider-sync --target . --item <id-or-url> --write" in text
    assert "backlog-provider-migration-interview --target . --write" in text
    assert "backlog-provider-export --target . --item-path <repo-plan.md> --type <goal|milestone|bug|task> --write" in text
    assert "Do not bulk export all repo plans by default" in text
    assert "Normal exports create real,\nnumbered repository issues in the adapter `repo`" in text
    assert "Board-only GitHub Project draft\nitems require explicit `--draft`" in text
    assert "Claude Code `/goal`" in text
    assert "Claude `/goal` is session-scoped and requires Claude Code `v2.1.139+`" in text
    assert "minervit-methodology goal-start --target . --goal <source-of-truth-goal-plan>" in text
    assert "minervit-methodology goal-next --target ." in text
    assert "minervit-methodology goal-advance --target . --event milestone-complete" in text
    assert "minervit-methodology goal-advance --target . --event milestone-deferred" in text
    assert "Do not mark a milestone complete without validation proof or a linked milestone ledger" in normalized
    assert "adapter enables delivery-ops closeout" in normalized
    assert "If the source-of-truth goal plan names operator-input dependencies" in text
    assert "context rotation can be required by the adapter" in text
    assert "context-rotation-check --target . --boundary goal-heartbeat --context-percent <visible-percent> --context-percent-source estimate" in normalized
    assert "Context exhaustion by itself does not satisfy `/goal`" in normalized
    assert "authorized per-session increment" in text
    assert ".ai-work/GOAL_RUN.json" in text
    assert "minervit-methodology goal-condition --target ." in text
    assert "Do not tell the human operator the deploy is theirs to run" in normalized
    assert "--customer-facing-justification" in text
    assert "## What this delivers" in text
    assert "## Why it matters" in text
    assert "sourceAdapterSha256" in text
    assert "## Verification Evidence" in normalized
    assert "delivery-summary" in text
    assert "adapter-declared credential/origin discovery" in text
    assert "Those epics are a hard scope boundary" in normalized
    assert "must never consider, recommend, surface, rank, or pull a board item from an epic it is not assigned" in normalized


def test_execution_packet_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        EXECUTION_PACKET_SKILL,
        "execution-packet-work-loop",
        EXECUTION_PACKET_REFERENCE,
        required=(
            "milestone-next",
            "milestone-advance --event <event>",
            "Do not ask whether to continue",
        ),
    )


def test_execution_packet_reference_retains_detailed_policy():
    text = EXECUTION_PACKET_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2500
    assert text.startswith("# Execution Packet Policy Reference")
    assert "codex-run --risk-tier T2 --native-review-note --stage1-sweep" in text
    assert "T0 uses self-review plus tests/preflight only" in text
    assert "Subagent, per-item, or milestone-local reviews do not replace assembled-diff review evidence" in text
    assert "A passive monitor stop is any response or turn whose only forward motion" in text
    assert "arm `ScheduleWakeup` or an equivalent host self-wakeup at the poll cadence" in text
    assert "A backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop is not a monitor" in text
    assert "Anthropic/Claude/Codex/GitHub/API overloads" in text
    assert "Standing approval recorded in the execution packet" in text
    assert "Any TODO-only section, generic one-line placeholder" in text
    assert "Next milestone is <name>. Want me to begin planning, or pause here?" in text
    assert "No log/artifact growth for two times the cadence is stale/hung" in text
    assert "Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff" in normalized


def test_human_instructions_skill_is_concise_entrypoint():
    text = HUMAN_INSTRUCTIONS_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 245
    assert "name: human-instructions" in lines
    assert "security/admin/GitHub/cloud/identity/billing/production/third-party" in text
    assert "references/human-instructions-policy.md" in text
    assert "Read `references/human-instructions-policy.md` in full" in text
    assert "Verify the current process in the same turn before giving steps" in text
    assert "official vendor docs, official CLI/API help, or live UI evidence" in text
    assert "For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence" in normalized
    assert "direct links to the specific authoritative source pages used" in text
    assert "exact scope of the setting: personal, organization, enterprise, repository, environment, project, or team" in text
    assert "Do not invent UI labels, menu paths, setting names, screenshots, or links from memory" in text
    assert "If current authoritative verification is unavailable, say the instructions are unverified" in normalized
    assert "check whether a careful human operator could complete the change the first time using the steps and links" in normalized


def test_human_instructions_reference_retains_detailed_policy():
    text = HUMAN_INSTRUCTIONS_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 250
    assert text.startswith("# Human Instructions Policy Reference")
    assert "External systems include GitHub, cloud consoles, identity providers, billing portals, production services" in normalized
    assert "security, admin, GitHub, cloud, identity, billing, production, or third-party setup changes" in normalized
    assert "Verify the current process in the same turn before giving steps" in text
    assert "official vendor documentation" in text
    assert "official CLI or API help/output" in text
    assert "live product UI evidence" in text
    assert "For GitHub, prefer `docs.github.com`, `gh` help/API output, or GitHub UI evidence" in normalized
    assert "over memory, blog posts, or old examples" in text
    assert "Do not invent UI labels, menu paths, setting names, screenshots, or links from memory" in normalized
    assert "name the exact source needed before asking the human operator to act" in normalized
    assert "direct links to the specific authoritative source pages used" in text
    assert "required role, plan, ownership, feature availability, repository scope, or account level" in normalized
    assert "personal, organization, enterprise, repository, environment, project, or team" in normalized
    assert "branch-specific instructions when the workflow differs by UI version, role, plan, or account type" in normalized
    assert "Do not link only to a generic documentation home page when a specific source exists" in normalized
    assert "could complete the change the first time using the steps and links" in normalized


def test_behavior_specs_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        BEHAVIOR_SPECS_SKILL,
        "behavior-specs",
        BEHAVIOR_SPECS_REFERENCE,
        required=(
            "one behavior per scenario",
            "Reviewed source materials are upstream source material",
            "inactive scenarios are not acceptable coverage",
        ),
    )


def test_behavior_specs_reference_retains_detailed_policy():
    text = BEHAVIOR_SPECS_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 750
    assert text.startswith("# Behavior Specs Policy Reference")
    assert "source-material, role-vocabulary, scenario quality, review, and executable-coverage policy" in normalized
    assert "every customer-facing system behavior change needs behavior specs before development starts" in normalized
    assert "Reviewed business/customer/user behavior specs are upstream source material, not inspiration" in normalized
    assert "Preserve business intent unless there is a documented conflict" in normalized
    assert "account for every declared source material path as reviewed/adapted or not applicable" in normalized
    assert "BEHAVIOR-SOURCE-EXEMPT: <real reason>" in text
    assert "Do not invent generic actors such as `stakeholder`, `user`, `admin`, or `operator`" in normalized
    assert "Use exactly one `Given`, one `When`, and one `Then` in each scenario" in normalized
    assert "Missing source-material traceability, wrong roles, multi-behavior scenarios" in normalized
    assert "Executable behavior specs must run against the application package that is actually being changed" in normalized
    assert "Inactive scenarios are not coverage" in text
    assert "Delivery summaries for customer-facing behavior must prominently state any inactive-scenario count" in normalized


def test_review_before_push_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        REVIEW_BEFORE_PUSH_SKILL,
        "review-before-push",
        REVIEW_BEFORE_PUSH_REFERENCE,
        required=(
            "branch-liveness-check --target . --strict",
            "plan-finalization-precheck",
            "Critical/C1/P1 findings are repair work items",
        ),
        forbidden=("ask whether to run", "skip review", "subagent reviews satisfy"),
    )


def test_review_before_push_reference_retains_detailed_policy():
    text = REVIEW_BEFORE_PUSH_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1600
    assert text.startswith("# Review Before Push Policy Reference")
    assert "Run one authoring-model native/self-check before R1" in text
    assert "T0/T1 work uses brief planning and implementation gates instead of cross-model plan review" in text
    assert "Tool default plan locations" in text
    assert "migrate only T2/T3 or explicitly review-required plans into the source-of-truth path" in normalized
    assert "methodology-status --target . --fail-on-drift` fails when source/template paths are missing or relevant scratch plans remain" in normalized
    assert "TODO-only sections, generic placeholders, vague restatements, missing named tests/gates, missing concrete testable acceptance criteria" in normalized
    assert "Plan-review P1 must name the concrete user-visible failure or expensive rework" in text
    assert "Otherwise classify it as a non-blocking P2 note and carry it into implementation review or backlog routing" in text
    assert "bound to the active adapter `review.codexPlanWrapper`" in text
    assert "Ignored logs, mtime, or chat prose are not proof" in text
    assert "use `goal-orchestration` before milestone/PR plans" in normalized
    assert "Read the configured document context index before scanning source-of-truth plan directories" in text
    assert "For T2/T3 only, run the model-native review on the exact current assembled diff" in text
    assert "Do not hand a changed T2/T3 diff to Codex/Stage 2 after fixing review findings" in text
    assert "Stage 1 native review is the authoring model's exhaustive sweep" in text
    assert "`origin/main...HEAD`" in text
    assert "Stage 2 is a confirmation pass, not a discovery loop" in normalized
    assert "For Claude-authored code, use Superpowers review plus project review agents" in normalized
    assert "A class is \"swept\" only when you name the members you actually checked" in normalized
    assert "`--allow-extra-rounds`" in text
    assert "generated/derived artifact freshness" in text
    assert "Codex CLI Finding Retrieval" in text
    assert "Do not infer \"no findings\" from a failed grep" in text
    assert "Plan-review convergence is a ladder" in text
    assert "Adapter-declared review exemptions can skip plan review only through a valid `## Plan Review Exemption` section" in text
    assert "Starting a final, R3, `cap`, rerun, or any other named terminal/retry review round does not complete the review gate" in text
    assert "A live but idle review process with no log/check progress past the stale threshold is wedged" in text
    assert "Per-task, subagent, or milestone reviews do not satisfy this gate" in text
    assert "bind that existing trusted log with `minervit-methodology finalize-plan-review" in normalized


def test_framework_intake_reference_retains_detailed_policy():
    text = FRAMEWORK_INTAKE_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2900
    assert text.startswith("# Framework Intake Policy Reference")
    assert "First-pass analysis before tools" in text
    assert "Targeted evidence only" in text
    assert "Do not run recursive repo search, glob discovery, broad `find`, broad `rg`, tool-help discovery, or unrelated file reads during RCA" in text
    assert "Each inspected artifact must map to one stated uncertainty" in text
    assert "Tool/platform default overrode methodology." in text
    assert "Agent training default overrode methodology." in text
    assert "Memory/evidence treated as process authority." in text
    assert "## What happened" in text
    assert "## Root cause" in text
    assert "## Proposed control" in text
    assert "## Validation" in text
    assert "Evidence must cite concrete artifacts" in text
    assert "Open Brain, Claude memory, local memory, or feedback-memory files, label it non-authoritative" in text
    assert "`Proposed control` states the concrete framework, adapter, skill, validation, or documentation change" in text
    assert "`Validation` names the validation command, review, PR, test, archive branch publication, or true blocker" in text
    assert "branch-published methodology-repo copy" in text
    assert "publish-rca-artifact --commit --push` uses isolated archive-branch publication" in text
    assert "lane-local `.ai-runs/` file alone is incomplete for methodology work" in text
    assert "Routine `--admin` merge" in text
    assert "Plan-review loops that continue past the hard cap of four rounds" in text
    assert "Claude/Codex rule files that duplicate large policy blocks and drift" in normalized
    assert "Forbidden phrasing includes" not in text
    assert "must start with exactly one of the outcomes below on its first non-empty line" not in normalized


def test_context_continuity_skill_owns_document_context_budget_entrypoint():
    _assert_thin_skill_entrypoint(
        DOCUMENT_CONTEXT_SKILL,
        "context-continuity",
        DOCUMENT_CONTEXT_REFERENCE,
        required=(
            "configured indexes first",
            "avoid broad-loading",
            "minervit-methodology context-status --target .",
        ),
    )


def test_context_continuity_reference_retains_document_context_budget_policy():
    text = DOCUMENT_CONTEXT_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2400
    assert text.startswith("# Context Continuity Policy Reference")
    assert "Current action should come from configured indexes and active lane artifacts" in normalized
    assert "generated `CLAUDE.md` / `AGENTS.md`" in text
    assert "Do not load archive directories during startup" in text
    assert "`documentContext.enforcement` defaults to `warn`" in text
    assert "Strict mode is enabled per project only after indexes, classification, and archive headers are clean" in normalized
    assert "the specific question being answered" in text
    assert "the target files or globs" in text
    assert "an upper bound of 20 Markdown files" in text
    assert "A search result alone is not authority" in text
    assert "Strict archive docs must include this sentence near the top" in text
    assert "Historical evidence only. Not current process, scope, or execution authority. Start from <index path>." in text
    assert "Archive paths should be reachable from an index section named `Historical Evidence Only`" in normalized
    assert "`Read First` contains stable routing docs only" in text
    assert "`Active Work` contains current in-flight artifacts" in text
    assert "`Ready Next` contains approved ready work" in text
    assert "`Needs Classification` must be empty before strict enforcement" in text
    assert "minervit-methodology context-status --target ." in text
    assert "`context-bootstrap` creates indexes, classifies tracked Markdown candidates, and adds archive headers" in normalized
    assert "It must not move docs automatically" in text
    assert "`context-status --strict` fails for missing indexes, oversized indexes, unclassified tracked Markdown, missing archive headers, or generated adapter drift" in normalized
    assert "not finished until the relevant context index reflects the new state" in normalized


def test_usage_accounting_skill_is_concise_entrypoint():
    text = USAGE_ACCOUNTING_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 340
    assert "name: usage-accounting" in lines
    assert "Usage Accounting" in text
    assert "references/usage-accounting-policy.md" in text
    assert "Usage records are evidence only" in text
    assert "Do not write usage files directly" in text
    assert "Never present estimates as exact" in text
    assert "Human or inferred values must be `estimated`; missing cost remains `unknown`" in text
    assert "minervit-methodology usage-log-path --target ." in text
    assert "minervit-methodology usage-record --target ." in text
    assert "--confidence <exact|estimated|unknown>" in text
    assert "minervit-methodology usage-import-claude --target ." in text
    assert "minervit-methodology usage-report --target . --since 7d --by product" in text
    assert "Record usage at meaningful boundaries" in text
    assert "startup, plan-review round, implementation/code-review round, PR queue/merge, milestone completion, goal completion, context rotation, and session closeout" in normalized
    assert "Do not calculate price unless the pricing source and model mapping are explicit in the same work" in text
    assert "$HOME/.local/state/minervit/usage/<repo-slug>/" in text
    assert "Do not commit it to the product repo" in text
    assert "Use `usage-report` output as evidence" in text


def test_usage_accounting_reference_retains_detailed_policy():
    text = USAGE_ACCOUNTING_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 575
    assert text.startswith("# Usage Accounting Policy Reference")
    assert "local operational evidence for understanding AI spend by product, lane, goal, milestone, model, activity, and timeframe" in normalized
    assert "It is not process authority, product documentation, a continuity handoff, a session journal, or approval evidence" in normalized
    assert "Every usage record must carry a `source` and `confidence` value" in text
    assert "`exact`, `estimated`, or `unknown`" in normalized
    assert "minervit-methodology usage-record --target ." in text
    assert "usage-import-claude" in text
    assert "usage-report --target . --since 7d --by model" in text
    assert "Record usage at meaningful boundaries when data is available" in text
    assert "implementation or code-review round" in text
    assert "Do not calculate price unless the pricing source and model mapping are explicit in the same work" in normalized
    assert "$HOME/.local/state/minervit/usage/<repo-slug>/" in text
    assert "Do not put prompts, API keys, webhook URLs, raw customer data, private transcripts, or long terminal output in usage records" in normalized
    assert "If a source identifier itself is sensitive, replace it with a non-sensitive local reference" in normalized
    assert "Avoid vague activities that make later rollups useless" in normalized
    assert "Prefer provider or host usage metadata over manual estimates" in text
    assert "Imported records must still deduplicate by stable record identity" in normalized
    assert "Do not mine unrelated logs unless the user explicitly asks for reconstruction" in text
    assert "Reconstructed values are not exact unless the underlying provider/host metadata is exact" in normalized
    assert "whether the numbers are exact, estimated, incomplete, or machine-local only" in text
    assert "Do not present usage totals as organization-wide spend unless the evidence actually spans all relevant machines, products, providers, and timeframes" in normalized


def test_stakeholder_questions_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        STAKEHOLDER_QUESTIONS_SKILL,
        "stakeholder-questions",
        STAKEHOLDER_QUESTIONS_REFERENCE,
        required=(
            "stakeholder-question-status --target . --sync",
            "stakeholder-question-ask --target .",
            "Treat answered comments as product evidence after sync",
        ),
    )


def test_stakeholder_questions_reference_retains_detailed_policy():
    text = STAKEHOLDER_QUESTIONS_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 475
    assert text.startswith("# Stakeholder Questions Policy Reference")
    assert "when GitHub issue comments are used for product-owner answers" in normalized
    assert "Stakeholder clarifications happen on the active GitHub issue, not in private chat or memory" in normalized
    assert "durable for the lane, other agents, and stakeholders" in text
    assert "Ask one clear question at a time" in text
    assert "why the answer changes the build" in text
    assert "persist the answer in the project adapter so future questions do not ask again" in text
    assert "Do not hand-write marker comments" in text
    assert "moves the Project item to the adapter-approved blocked status" in text
    assert "At startup, PR boundaries, milestone boundaries, and blocked-work checks" in text
    assert "stakeholder-question-status --target . --sync" in text
    assert "records an answered marker, updates labels, and restores the Project item status" in normalized
    assert "An unanswered stakeholder question is a real blocker only for the work whose decision depends on that answer" in normalized
    assert "GitHub issue answers are stakeholder input evidence" in text
    assert "They are not execution authority by themselves" in normalized
    assert "source-of-truth goal, milestone, or PR plan with the decision before implementing the decision" in normalized
    assert "If the answer is ambiguous, post one follow-up question through `stakeholder-question-ask`; do not guess" in normalized
    assert "Do not treat private chat, memory notes, or local scratch files as a substitute" in text
    assert "Use stakeholder questions for product or stakeholder clarification, not for changing board schema" in normalized
    assert "Stakeholder-authored issue substance remains stakeholder-owned by default" in text
    assert "rather than editing those fields directly unless the adapter explicitly allows that write" in normalized


def test_methodology_regression_rca_skill_owns_feature_request_entrypoint():
    _assert_thin_skill_entrypoint(
        FRAMEWORK_INTAKE_SKILL,
        "framework-intake",
        FRAMEWORK_INTAKE_REFERENCE,
        required=(
            "Feature request: the operator asks for a new capability",
            "If both apply, write the RCA first",
            ".ai-runs/<utc>-methodology-feature-request.md",
        ),
    )


def test_methodology_regression_rca_reference_retains_feature_request_policy():
    text = FRAMEWORK_INTAKE_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2900
    assert text.startswith("# Framework Intake Policy Reference")
    assert "new capabilities, new rules, new skills, new CLI support" in normalized
    assert "Do not put feature requests on the RCA rails just because the proposed change came from a gap" in normalized
    assert "If host skill tooling is unavailable, stale, or returns `Unknown skill`" in normalized
    assert "$MINERVIT_METHODOLOGY_REPO" in text
    assert "$HOME/.config/minervit/methodology.env" in text
    assert "minervit-methodology version --no-remote" in text
    assert "Classify the request" in text
    assert "Do not run broad repo discovery just to make an intake artifact more elaborate" in normalized
    assert "`YYYYMMDDTHHMMSSZ`" in text
    assert "```markdown\n# Methodology Feature Request" in text
    assert "## What this delivers" in text
    assert "## Why it matters" in text
    assert "## Current Gap / Evidence" in text
    assert "## Proposed Capability" in text
    assert "## Acceptance Criteria" in text
    assert "## Validation Proof" in text
    assert "## Risks / Compatibility" in text
    assert "## Suggested Triage" in text
    assert "## Immediate Next Action" in text
    assert "Acceptance Criteria` must contain concrete bullets or numbered criteria" in normalized
    assert "Immediate Next Action` must name a specific file path" in normalized
    assert "methodology-feature-request-archive" in text
    assert "Do not include person-specific machine paths" in text
    assert "entries in the maintainer backlog" in text
    assert "provider-backed backlog items through the existing sanctioned backlog flow" in normalized


def test_rules_audit_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        RULES_AUDIT_SKILL,
        "rules-audit",
        RULES_AUDIT_REFERENCE,
        required=(
            "memory is evidence only",
            "broad Markdown loading",
            "Do not broaden an audit into unrelated repo discovery",
        ),
    )


def test_rules_audit_reference_retains_detailed_policy():
    text = RULES_AUDIT_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) <= 100
    assert text.startswith("# Rules Audit Policy Reference")
    assert "compatibility reference preserves old `rules-audit`" in text
    assert "framework-intake-policy.md" in text
    assert "Rules Audit section" in normalized


def test_board_adoption_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        BOARD_ADOPTION_SKILL,
        "board-adoption",
        BOARD_ADOPTION_REFERENCE,
        required=(
            "The board is human-owned",
            "Never change board structure",
            "Apply changes to the adapter only",
        ),
    )


def test_board_adoption_reference_retains_detailed_policy():
    text = BOARD_ADOPTION_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 500
    assert text.startswith("# Board Adoption Policy Reference")
    assert "board schema mismatch means the adapter's recorded `backlogProvider` no longer matches the board's live schema" in normalized
    assert "The board's schema is human-owned" in text
    assert "`backlog-provider-update` / `backlog-provider-next` fails because the adapter references a column or option" in normalized
    assert "This command is **read-only**" in text
    assert "fields, single-select options, project metadata" in text
    assert "board_examine_unknown:" in text
    assert "| `role:<Column>=ready\\|active\\|done\\|blocked\\|icebox` |" in text
    assert "`priority_order=<...>`" in text
    assert "`custom:<Field>=<...>`" in text
    assert "Gather each answer as an `--answer KEY=VALUE` pair" in text
    assert "refuses to apply while any unknown is unanswered" in normalized
    assert "writes **only** the adapter's `backlogProvider` block" in normalized
    assert "Never run `gh project field-*`, `gh project edit/delete/copy/close/create`" in normalized
    assert "structural GraphQL mutation to \"fix\" the mismatch" in normalized
    assert "`schemaHash` will drift and the mismatch will recur" in text
    assert "Changing any adapter key outside `backlogProvider` during adoption is out of scope" in normalized


def test_delivery_summary_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        DELIVERY_SUMMARY_SKILL,
        "delivery-summary",
        DELIVERY_SUMMARY_REFERENCE,
        required=(
            "Start with the plain-language outcome and next action",
            "Refresh the configured continuity handoff",
            "Technical-only merge/check reports are incomplete",
        ),
    )


def test_delivery_summary_reference_retains_detailed_policy():
    text = DELIVERY_SUMMARY_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2200
    assert text.startswith("# Delivery Summary Policy Reference")
    assert "## Operator Progress Updates" in text
    assert "after startup gates and before starting the first substantive work item" in text
    assert "before any review, preflight, deploy, or test sequence expected to take more than 2 minutes" in normalized
    assert "at every review round, preflight phase, monitor poll, PR boundary, milestone transition, goal transition, context-rotation checkpoint, blocker, and recovery action" in normalized
    assert "at least every 5 minutes of wall-clock time" in normalized
    assert "immediately before any autonomous yield, heartbeat, or wakeup handoff" in normalized
    assert "Lead with the plain-language outcome or current state" in text
    assert "goal -> milestone -> PR hierarchy" in text
    assert "percent unknown" in text
    assert "Event logs, session journals, and continuity files do not substitute" in normalized
    assert "Start with the plain-language outcome and next action before technical details" in text
    assert "Any message that reports work landed or shipped is a delivery summary" in text
    assert "Work-landed triggers include" in text
    assert "Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session" in text
    assert "For batch delivery updates, the executive summary must include" in text
    assert "A technical-only merge report is incomplete" in text
    assert "Include a grounded progress narrative" in text
    assert "what capability was unlocked for users, admins, operators, or delivery velocity" in text
    assert "Use headings or labels only when they improve readability" in text
    assert "progress against the current goal and milestone, including an estimated percent of planned work complete" in text
    assert "Ground goal percent complete in `.ai-work/GOAL_RUN.json`" in text
    assert "Ground milestone percent complete in the source-of-truth plan, execution packet, backlog checklist, or adapter-declared milestone scope" in text
    assert "Do not turn the recommendation into a permission question" in text
    assert "If the summary proves no implementation-ready tactical PR plan is on deck, do not ask whether to plan" in text
    assert "Next milestone is <name>. Want me to begin planning, or pause here?" in text
    assert 'Do not use "no work-in-flight" as a stop menu' in text
    assert "Do not ask the human operator to choose cleanup, backlog, or something else" in text
    assert "whether early-warning smoke was started and its current state, or why it was covered/skipped" in text
    assert "## Proof Of Done" in text
    assert "compare the proof-of-done standard from the source-of-truth plan or execution packet against what actually ran" in normalized
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof" in text
    assert "They can explain why proof is missing" in text
    assert "still names executable proof for the behavior being claimed complete" in normalized
    assert "queued PR status, or post-merge/deploy monitor status only if an exceptional monitor was required" in text
    assert "At every PR queued/completed boundary, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat, check visible context pressure" in text
    assert "A queued-delivery or PR-completion summary is incomplete until the milestone ledger is advanced" in text
    assert 'do not use "what would you like" as a context-rotation fallback' in text
    assert "A queued-delivery summary is incomplete unless it ends with one of two concrete outcomes" in text
    assert "Statements such as `no more P1 followups`" in text
    assert "minervit-methodology milestone-next --target ." in text
    assert "minervit-methodology goal-next --target ." in text
    assert "Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff" in normalized

    assert "technical-only boundary status such as `PR #327 merged; 5 of 6 batch items landed`" in normalized
    assert "review/preflight status that only says `review running`, `checks green`, `monitor event`, `harness notification`, or `preflight in progress`" in normalized
    assert "rewrite the update in plain language" in normalized


def test_milestone_update_skill_is_concise_entrypoint():
    text = MILESTONE_UPDATE_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 375
    assert "# Milestone Update" in lines
    assert "name: milestone-update" in lines
    assert "references/milestone-update-policy.md" in text
    assert "internal operator visibility artifacts" in text
    assert "minervit-methodology milestone-update-status --target . --strict" in text
    assert "do not ask whether to enable it" in text
    assert "do not mark the milestone complete until the env is configured" in normalized
    assert "## Plain English" in text
    assert "## Progress" in text
    assert "## What Changed" in text
    assert "## Validation" in text
    assert "## Next" in text
    assert "## Technical Details" in text
    assert "minervit-methodology publish-milestone-update --target ." in text
    assert "short milestone keys such as `M3`" in text
    assert "canonicalized to the active milestone title" in text
    assert "goal-advance --event milestone-complete` is not allowed until the Product Milestones delivery marker exists" in normalized
    assert "Do not generate a video or S3 review page for the internal milestone update" in text
    assert "Customer-facing page/video reviews remain the `iteration-review` skill" in text
    assert "do not wait for Chat acknowledgement" in normalized


def test_milestone_update_reference_retains_detailed_policy():
    text = MILESTONE_UPDATE_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 550
    assert text.startswith("# Milestone Update Policy Reference")
    assert "internal, professional, text-only Google Chat cards" in text
    assert "adapter-configured Product Milestones space" in text
    assert "technical and meta detail" in normalized
    assert "minervit-methodology milestone-update-status --target . --strict" in text
    assert "If disabled, continue normal authorized work" in text
    assert "If enabled but the webhook env is missing, that is a setup blocker for milestone completion" in normalized
    assert "methodology-status --fail-on-drift` fails when the configured Product Milestones webhook env is missing" in normalized
    assert "`goal-advance --event milestone-complete` also refuses completion until the delivery marker exists" in normalized
    assert "## Plain English" in text
    assert "## Progress" in text
    assert "## What Changed" in text
    assert "## Validation" in text
    assert "## Next" in text
    assert "## Technical Details" in text
    assert "minervit-methodology publish-milestone-update --target ." in text
    assert "Do not re-post under a different milestone spelling" in text
    assert "goal-advance --event milestone-complete` is not allowed until the Product Milestones delivery marker exists" in normalized
    assert "Keep `Plain English` first and useful" in text
    assert "`Validation` should name real checks, reviews, deploy proof, or why validation is deferred" in normalized
    assert "Do not include secrets, webhook URLs, raw terminal dumps, or customer-private data" in normalized
    assert "Do not generate a video or S3 review page for the internal milestone update" in normalized
    assert "These updates may include implementation approach, risks, validation, PRs, review rounds, and next work" in normalized
    assert "not a substitute for a customer-facing goal-complete iteration review" in normalized
    assert "Do not treat a successful milestone-update post as permission to stop" in text


def test_graphify_navigation_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        GRAPHIFY_NAVIGATION_SKILL,
        "graphify-navigation",
        GRAPHIFY_NAVIGATION_REFERENCE,
        required=(
            "Graphify report/query/path/explain",
            "graphify . --update",
            "Do not commit generated graph output",
        ),
    )


def test_graphify_navigation_reference_retains_detailed_policy():
    text = GRAPHIFY_NAVIGATION_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 550
    assert text.startswith("# Graphify Navigation Policy Reference")
    assert "adapter-backed and optional per project" in text
    assert "default is enabled unless the adapter says otherwise" in text
    assert "Graphify output is navigation evidence, not process authority" in text
    assert "Stale Graphify output must not be used for decisions" in text
    assert "Read `graphify-out/GRAPH_REPORT.md` first" in text
    assert "Use `graphify query`, `graphify path`, or `graphify explain`" in text
    assert "before broad `rg`/grep scans" in text
    assert "Do not paste large graph output into chat" in text
    assert "After every code, docs, schema, route, test, architecture, or other system change" in text
    assert "run `graphify . --update` before relying on existing Graphify output, committing, or pushing" in normalized
    assert "tracked or unignored project file is newer than the latest Graphify artifact" in normalized
    assert "Stale graph output is blocking drift" in text
    assert "fall back to narrow `rg`/file reads" in text
    assert "`graphify-status --target . --strict`" in text
    assert "`methodology-status --fail-on-drift`" in text
    assert "minervit-methodology graphify-install --target ." in text
    assert "Do not run `graphify claude install`, `graphify codex install`" in text
    assert "Minervit owns generated `CLAUDE.md` and `AGENTS.md`" in text
    assert "`graphify-out/` is generated local output" in text
    assert "remove tracked output or refresh stale output" in text
    assert "does not replace reading source files, running tests, updating derived artifacts, or following review gates" in normalized


def test_lane_lifecycle_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        LANE_LIFECYCLE_SKILL,
        "lane-lifecycle",
        LANE_LIFECYCLE_REFERENCE,
        required=(
            "minervit-methodology lane-start --target .",
            "methodology-status --target . --fail-on-drift",
            "Product/client lanes do not raw-pull latest methodology by default",
            "branch-liveness-check --target . --strict",
        ),
    )


def test_lane_lifecycle_reference_retains_detailed_policy():
    text = LANE_LIFECYCLE_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1900
    assert text.startswith("# Lane Lifecycle Policy Reference")
    assert "Resolve the methodology CLI before running startup gates" in text
    assert "If it is missing from `PATH` or exits 127/command-not-found" in text
    assert "MINERVIT_METHODOLOGY_REPO" in text
    assert "bin/minervit-methodology install-cli" in text
    assert "A missing `PATH` entry is not a failed methodology gate" in text
    assert "not a reason to ask for a person-specific checkout path" in text
    assert "Never overwrite hand-written lane `CLAUDE.md` or `AGENTS.md`" in text
    assert "Unlocked adapter-backed product/client lanes do not raw-pull latest methodology by default" in text
    assert "Cached host plugin metadata is not a lane update failure" in text
    assert "do not ask the human operator to decide whether to inspect version/status" in text
    assert "restart that host/session" in text
    assert "latest-code-status --target . --write" in text
    assert "deep codebase/architecture/multi-angle analysis" in text
    assert "establish the latest-code baseline before spending analysis budget" in text
    assert "before trusting local lane files" in text
    assert "current-branch liveness check" in text
    assert "branch-liveness-check --target . --strict" in text
    assert "If no active goal exists or the prior goal ledger is complete, use the printed `next_goal_name`, `next_goal_short_description`, `next_goal_claude_prompt`, and `next_goal_next_action`" in normalized
    assert "Lane startup also reports milestone run state" in text
    assert "Lane startup also reports cross-lane coordination state and bootstraps missing coordination artifacts by default" in text
    assert (
        "missing, stale, untracked, uncommitted, or unpushed state in the current lane's own status file, "
        "or in the shared contract or lane board, fails"
    ) in text
    assert "other lanes' stale, untracked, or dirty" in normalized.lower()
    assert "lane-coordination-note --target ." in text
    assert "Lane startup also reports repo event-log paths" in text
    assert "adapter-approved event commands" in text
    assert "Lane startup also reports context rotation policy" in text
    assert "Do not ask the human operator to run `/compact`" in text
    assert "Claude context-rotation heartbeat hook" in text
    assert "minervit-methodology milestone-advance --target . --event <event>" in text
    assert "document context budget state" in text
    assert "context-continuity" in text
    assert "Prefer lane-local resource isolation over broad machine locks" in text
    assert "A rejected or cancelled startup, commit, push, or merge tool call is not a stop signal" in text
    assert "Keep adapter cleanup separate from feature work and never commit lane-local state or unrelated product changes" in text
    assert "Any direction-asking question after the previous PR landed and no work is in flight is a stop-menu violation" in text
    assert "Claude `ExitPlanMode` hooks are mandatory for Claude plan-mode lanes" in text
    assert "not automatically a Tier 2 approval stop" in text


def test_lane_coordination_skill_is_concise_entrypoint():
    text = LANE_COORDINATION_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 475
    assert "name: lane-coordination" in lines
    assert "references/lane-coordination-policy.md" in text
    assert "Read `references/lane-coordination-policy.md` in full" in text
    assert "Use the git repo as the coordination backbone" in text
    assert "Lane coordination is mandatory by default" in text
    assert "Each lane updates only its own status file" in text
    assert "lane-coordination-status --target ." in text
    assert "methodology-status --strict" in text
    assert "methodology-status --fail-on-drift" in text
    assert "lane-coordination-bootstrap --target . --write" in text
    assert "lane-coordination-note --target ." in text
    assert "Use bootstrap only when artifacts are missing outside startup" in text
    assert "Local-only status is not coordination" in text
    assert "tracked, clean in Git, current for the active branch, and pushed" in normalized
    assert "Do not put routine progress in one shared status document" in text
    assert "Do not silently implement an incompatible version" in text
    assert "Shared routes, account semantics, order states" in text
    assert "before large implementation PRs" in text
    assert "verify remote main and current PR state before trusting local lane claims" in text
    assert "If the next coordination action is derivable from repo artifacts" in normalized


def test_lane_coordination_reference_retains_detailed_policy():
    text = LANE_COORDINATION_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 525
    assert text.startswith("# Lane Coordination Policy Reference")
    assert "shared route, actor, schema, state machine, API, server action" in normalized
    assert "Chat is for alerts and discussion, not durable coordination state" in normalized
    assert "The adapter config `laneCoordination` defines" in text
    assert "the cross-lane contract path" in text
    assert "the lane board path" in text
    assert "the stale-status threshold" in text
    assert "enforcement mode, which defaults to `strict`" in text
    assert "lane-start` creates missing coordination artifacts" in text
    assert (
        "missing, stale, untracked, uncommitted, or unpushed state in the current lane's own status file, "
        "or in the shared contract or lane board, fails"
    ) in normalized
    assert "other lanes' stale, untracked, or dirty" in normalized.lower()
    assert "Do not have every lane edit one large status document" in normalized
    assert "tracked, clean in Git, current for the active branch, and pushed" in normalized
    assert "what files, routes, contracts, data records, or APIs it touches" in text
    assert "must not silently implement an incompatible version" in text
    assert "open a small shared contract/interface PR" in text
    assert "verify remote main and current PR state before trusting local lane claims" in normalized
    assert "Do not ask the human operator to manually coordinate lanes" in text


def test_event_observability_skill_is_concise_entrypoint():
    text = EVENT_OBSERVABILITY_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 375
    assert "name: event-observability" in lines
    assert "references/event-observability-policy.md" in text
    assert "Read `references/event-observability-policy.md` in full" in text
    assert "Event logs are local operational evidence" in text
    assert "minervit-methodology event-log-path --target ." in text
    assert "minervit-methodology log-event --target ." in text
    assert "Never write `events.log` or `events.jsonl` directly" in text
    assert "Baretail" in text
    assert "minervit-methodology event-tail --target . --lines 80" in text
    assert "minervit-methodology event-viewer --target ." in text
    assert "The command is safe as a fast path" in text
    assert "Use snake_case names" in text
    assert "Event logs do not replace chat-visible operator updates" in text
    assert "event-audit --target . --since 24h --strict" in text
    assert "Do not let event logging become a stop signal" in normalized


def test_event_observability_reference_retains_detailed_policy():
    text = EVENT_OBSERVABILITY_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 550
    assert text.startswith("# Event Observability Policy Reference")
    assert "boundary, blocker, handoff, review gate, preflight, PR queue or merge" in normalized
    assert "not process authority, product docs, continuity handoffs, session journals" in normalized
    assert "must not create product-repo noise" in text
    assert "machine-local Minervit state" in text
    assert "the CLI performs validation, path normalization, rotation, and locked appends" in normalized
    assert "delivery-summary" in text
    assert "`plan_review_started`, `plan_review_finished`, `plan_review_failed`" in normalized
    assert "`preflight_started`, `preflight_passed`, `preflight_failed`" in normalized
    assert "`pr_queued`, `pr_merged`" in text
    assert "`session_journal_written`, `session_journal_published`" in normalized
    assert "`goal_advance_<event>`" in text
    assert "`milestone_advance_<event>`" in text
    assert "The human-readable file is intended for Baretail" in text
    assert "minervit-methodology event-tail --target . --lines 80" in text
    assert "`event-viewer` starts a local HTTP viewer" in text
    assert "`127.0.0.1:18765`" in text
    assert "verifies an existing Minervit viewer before reusing a port" in text
    assert "Use the printed URL, not an assumed port" in text
    assert "OK   preflight_passed Lane2 feature/x" in text
    assert "Two-round cap clean-with-deferrals on tip SHA; awaiting harness" in text
    assert "event-audit --target . --since 24h --strict" in text
    assert "Do not backfill events with invented history" in text
    assert "do not duplicate it with a second manual event" in normalized
    assert "Do not log secrets, raw terminal transcripts, complete review logs" in normalized
    assert "The CLI normalizes common paths" in text
    assert "phrase entries as repo-relative or local-state references" in normalized
    assert "Log the boundary, then continue with the methodology-authorized next action" in normalized


def test_session_journal_skill_is_concise_entrypoint():
    text = SESSION_JOURNAL_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)

    assert len(text.split()) <= 350
    assert "name: session-journal" in lines
    assert "references/session-journal-policy.md" in text
    assert "Read `references/session-journal-policy.md` in full" in text
    assert "Session journals are evidence only" in text
    assert "minervit-methodology prepare-session-journal --target . --stdin" in text
    assert "validate-session-journal --file .ai-runs/session-journals/<utc>-session-journal.md" in text
    # 0.9.0: publication is disabled; the skill must document the refusal + name the replacement.
    assert "Local-only as of 0.9.0" in text
    assert "publish-session-journal` and `publish-pending-session-journals` are disabled" in text
    assert "publish-instrumentation-record --target ." in text
    assert "do not freehand `graphify_*` fields" in text
    assert "estimated percent of planned work complete" in text
    assert "Keep the estimate rounded and grounded" in text
    assert "state `percent unknown` and name the exact blocker" in text
    assert "there is no publish step" in text
    assert "Treat validation as detection, not proof that no secret exists" in text
    assert "Never write a journal into any git worktree that could stage it to a remote" in text


def test_session_journal_reference_retains_detailed_policy():
    text = SESSION_JOURNAL_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 475
    assert text.startswith("# Session Journal Policy Reference")
    assert "milestone, delivery summary, queued-delivery summary" in normalized
    assert "not process authority, product docs, continuity handoffs, or normal startup context" in normalized
    assert "$HOME/.config/minervit/methodology.env" in text
    assert "$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology" in text
    assert "Do not skip journal writing just because the command is not initially on `PATH`" in normalized
    assert "Include only high-level summary evidence, not raw terminal transcripts" in text
    assert "Local-only as of 0.9.0" in normalized
    assert "publish-instrumentation-record" in text
    assert "refuse in every mode" in normalized
    assert "machine, checkout, or ephemeral workspace is discarded" in normalized
    assert "`## Starting Context`" in text
    assert "`## Work Delivered Or Advanced`" in text
    assert "`## Planning And Review Gates`" in text
    assert "`## Human Interruptions Or Questions`" in text
    assert "`## Delays, Waits, Or Autonomy Breakdowns`" in text
    assert "`## Validation And PR State`" in text
    assert "`## Continuity Outcome`" in text
    assert "`## Methodology Improvement Signals`" in text
    assert "The CLI adds `## Session Runtime`, including Graphify freshness evidence" in normalized
    assert "Treat validation as detection, not proof that no secret exists" in text
    assert "there is no archive branch and no publish step" in normalized
    assert "Do not fetch/read any remote archive branch during normal startup" in text


def test_background_monitoring_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        BACKGROUND_MONITORING_SKILL,
        "background-task-monitoring",
        BACKGROUND_MONITORING_REFERENCE,
        required=(
            "background-run --log <log>",
            "Do not end a turn with an active monitor",
            "Do not ask whether to wait, kill, or retry",
        ),
    )


def test_background_monitoring_reference_retains_detailed_policy():
    text = BACKGROUND_MONITORING_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1800
    assert text.startswith("# Background Monitoring Policy Reference")
    assert "Tool-level timeouts on a detached/background shell call are not enough" in text
    assert "Triggered early-warning smoke/main-health checks run as monitored background work" in text
    assert "Final preflight may also run with monitor evidence once the current PR tip is frozen" in text
    assert "Preflight idle examples include `Preflight still running; will push as soon as it lands`" in text
    assert "A backgrounded shell `until`, `sleep`, `wait`, `tail -F | grep`, or equivalent loop that waits for the same job is not a monitor" in text
    assert "Progress means terminal-relevant output" in text
    assert "Heartbeat timestamps, repeated identical status, debug noise, or byte-identical queue/check output do not reset the stale clock" in text
    assert "No log, artifact, check, or process-progress change for two times the poll cadence is stale/hung" in text
    assert "A valid active poll means running or reading a concrete monitor artifact" in text
    assert "Strict monitor checks require verified PID/process identity" in text
    assert "A delayed wakeup, reminder, monitor event, or shell completion notification is not active supervision" in text
    assert "A final, R3, `cap`, rerun, or any other named terminal/retry review round is not done when the review process starts" in text
    assert "specific failure/degraded signal is already known, the human operator explicitly asks for the check, or the next action truly depends on the merged main commit" in normalized


def test_background_monitoring_reference_retains_early_warning_policy():
    text = BACKGROUND_MONITORING_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 2200
    assert text.startswith("# Background Monitoring Policy Reference")
    assert "## Early-Warning Smoke" in text
    assert "command-selection, active-polling, stale/failure, queued-PR, and final-preflight planning policy" in normalized
    assert "Early-warning smoke is no longer a standing gate" in text
    assert "use the main-status gate as the baseline check" in text
    assert "Run adapter-backed local-service commands through lane isolation" in text
    assert "Continue with the authorized tactical queue while actively monitoring the smoke command" in normalized
    assert "Default stale threshold is one missed poll without a live process/check state" in normalized
    assert "A passing early-warning smoke is not a new stopping point" in text
    assert "Required item tests, fast preflight, full preflight, review gates, and merge gates still run" in normalized
    assert "Safe planning includes reading the milestone ledger, execution packet, backlog/indexes" in normalized
    assert "Draft or update the next plan only in a separate worktree/branch or ignored lane-local scratch" in normalized
    assert "A status-only update that says preflight is running or that the agent will push when it finishes is a passive monitor stop" in normalized


def test_backlog_epic_grooming_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        BACKLOG_EPIC_GROOMING_SKILL,
        "backlog-epic-grooming",
        BACKLOG_EPIC_GROOMING_REFERENCE,
        required=(
            "Definition of Ready",
            "Run the read-only grooming validation gate",
            "Do not change board structure during grooming",
        ),
    )


def test_backlog_epic_grooming_reference_retains_detailed_policy():
    text = BACKLOG_EPIC_GROOMING_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 550
    assert text.startswith("# Backlog Epic Grooming Policy Reference")
    assert "epic shape, feature-item template, feature-numbering, privacy-invariant, and read-only validation policy" in normalized
    assert "An epic is a container, not directly executable work" in text
    assert "Grooming-decompose (shaping one epic into feature items) is distinct from plan-review cap/focus-transfer handling" in text
    assert "the DoR is owned by canonical methodology, the generated adapter, and this skill" in text
    assert "Lead with `## What this delivers` and `## Why it matters`" in text
    assert "A native sub-issue link to the parent epic" in text
    assert "Feature-numbering series: `backlogProvider.featureSeries`" in text
    assert "prefer `pattern` for collision detection" in text
    assert "native sub-issue nodes carry only number/title/url/body" in text
    assert "`field` may still be set for non-sub-issue item shapes that do carry a board field value" in normalized
    assert "grooming_feature_series_field_unreadable" in text
    assert "When neither is set, numbering is unenforced and `validate-grooming` says so" in normalized
    assert "State this product's privacy/security invariants as adapter-sourced placeholders" in text
    assert "If the product has none, record `no privacy invariants declared`" in normalized
    assert "Run `validate-grooming` read-only before moving any item into a ready status" in normalized


def test_database_migration_collision_skill_is_concise_entrypoint():
    text = DATABASE_MIGRATION_COLLISION_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 400
    assert "name: database-migration-collision" in lines
    assert "references/database-migration-collision-policy.md" in text
    assert "Read `references/database-migration-collision-policy.md` in full" in text
    assert "migration numbering, snapshot metadata, migration journal entries" in text
    assert "The project adapter owns exact database, test, and migration generation commands" in text
    assert "Do not leave SQL files, snapshot metadata, or migration journal entries guessed" in normalized
    assert "## Fast Path" in text
    assert "## Collision Signals" in text
    assert "## Cure Rule" in text
    assert "duplicate SQL numeric prefixes" in text
    assert "meta/<index>_snapshot.json" in text
    assert "adapter merge-conflict output names migration SQL" in text
    assert "renumber and rebuild before pushing" in text
    assert "Use the reference playbook to identify the winner" in text
    assert "rebuild snapshot metadata and the migration journal" in text
    assert "Do not ask the human operator to choose a migration number" in text


def test_database_migration_collision_reference_retains_detailed_policy():
    text = DATABASE_MIGRATION_COLLISION_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 575
    assert text.startswith("# Database Migration Collision Policy Reference")
    assert "Drizzle repair, snapshot metadata, migration journal" in normalized
    assert "monotonic indexes such as `0004_*.sql`, `meta/0004_snapshot.json`, and `_journal.json`" in normalized
    assert "The project adapter owns exact database commands" in text
    assert "A migration chain is code and data-shape authority" in text
    assert "Before generating a migration:" in text
    assert "During long push deferrals or multi-PR goals, repeat the migration collision check" in normalized
    assert "Do not treat \"I generated this earlier\" as freshness proof" in text
    assert "a snapshot `prevId` points to a migration that is no longer the immediately previous journal entry" in normalized
    assert "repair the chain rather than taking either side wholesale" in normalized
    assert "Identify the migration index already consumed by `main` or the merge base winner" in normalized
    assert "Rebuild the local snapshot as winner cumulative schema plus the local schema additions" in normalized
    assert "Append the local journal entry at the new index and preserve the winner's journal entry" in normalized
    assert "future lane can replay the journal in order" in normalized
    assert "prefer that command over hand-editing" in text
    assert "Before declaring the collision resolved, the summary must name" in text
    assert "the contested index" in text
    assert "the winner migration kept from base/main" in text
    assert "the new index assigned to this lane's migration" in text
    assert "Do not ask the human operator to choose a migration number" in text


def test_merge_queue_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        MERGE_QUEUE_SKILL,
        "merge-queue-monitoring",
        MERGE_QUEUE_REFERENCE,
        required=(
            "admin merge is break-glass only",
            "clean PR is queued",
            "queued, auto-merge-enabled, merged, or closed PR branches as inactive",
        ),
    )


def test_merge_queue_reference_retains_detailed_policy():
    text = MERGE_QUEUE_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1000
    assert text.startswith("# Merge Queue Monitoring Policy Reference")
    assert "detailed merge queue, auto-merge, exceptional monitor, inactive-branch, and break-glass policy" in text
    assert "failed, stalled, conflicted, or otherwise exceptional merge/queue/deploy monitor" in text
    assert "If final preflight takes meaningful wall-clock time" in text
    assert "use the wait for branch-isolated next-iteration planning or active polling" in text
    assert "Remove the clean queued PR from active attention" in text
    assert "Continue with the next authorized task in the same turn" in text
    assert "prove no authorized next work remains by checking the execution packet" in text
    assert "Routine queued PRs are queue-and-move-on, not foreground work" in text
    assert "Do not wait for GitHub Actions, merge queue, deploy, or post-merge smoke" in text
    assert "After enabling auto-merge or confirming queue placement, do not schedule a future wakeup" in text
    assert "the prompt must name that signal/dependency and the next authorized non-queue work item" in text
    assert "For exceptional in-session queue checks, the PR `state` field" in text
    assert "Do not use `mergeQueueEntry.estimatedTimeToMerge` as a progress indicator" in text
    assert "If two queue polls return byte-identical output" in text
    assert "Do not say `will report verdict on monitor event`" in text
    assert "A monitor event is not an excuse for a technical-only landed-work report" in text
    assert "For batch merge updates, include the batch progress count" in text
    assert "Post-merge smoke or deploy checks are not watched by default after a clean queued PR" in text
    assert "Do not write `waiting for notification`, `will wait for completion`, or equivalent standby language" in text
    assert "Continue parallel-safe work or actively poll only for the exceptional reason" in text
    assert "At the next session start, run the adapter's main-health/smoke gate" in text
    assert "If a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment" in text
    assert "If this proves the prior PR has already landed and no work is in flight, do not ask where to go next" in text
    assert "ask one exact blocker question naming the missing or changed condition" in text
    assert "Queue rejection, queued/auto-merge-enabled current branch" in normalized


def test_merge_queue_split_preserves_original_policy_phrases():
    combined = (
        MERGE_QUEUE_SKILL.read_text(encoding="utf-8")
        + "\n"
        + MERGE_QUEUE_REFERENCE.read_text(encoding="utf-8")
    )

    original_policy_phrases = [
        "Confirm required item tests and review gates are clean for Critical/P1",
        "Run the configured local pre-merge gates as foreground work",
        "If final preflight takes meaningful wall-clock time",
        "Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work",
        "Send a queued-delivery summary immediately",
        "Remove the clean queued PR from active attention",
        "Routine queued PRs are queue-and-move-on, not foreground work",
        "Do not start a routine merge monitor just to watch a clean queued PR",
        "Check queued merge state in-session only when a failure/degraded signal is already known",
        "A queued, auto-merge-enabled, merged, or closed PR branch is inactive",
        "If this proves the prior PR has already landed and no work is in flight, do not ask where to go next",
        "After enabling auto-merge or confirming queue placement, do not schedule a future wakeup",
        "For exceptional in-session queue checks, the PR `state` field",
        "Do not use `mergeQueueEntry.estimatedTimeToMerge` as a progress indicator",
        "If two queue polls return byte-identical output",
        "When an exceptional in-session merge/deploy check is required, status must be plain language",
        "When a merge/queue/deploy monitor observes terminal success",
        "For batch merge updates, include the batch progress count",
        "Post-merge smoke or deploy checks are not watched by default after a clean queued PR",
        "Do not treat \"merge/check/deploy in progress\" as a reason to stand by",
        "Do not write `waiting for notification`, `will wait for completion`, or equivalent standby language",
        "do not ask whether to wait, cancel, retry, or restart it",
        "At the next session start, run the adapter's main-health/smoke gate",
        "Routine `--admin` merge is banned",
        "standing approval once gates and conditions match",
        "Do not invent approval from habit, memory, or urgency",
        "Queue rejection, queued/auto-merge-enabled current branch, merged/closed current-branch PR",
    ]

    for phrase in original_policy_phrases:
        assert phrase in combined


def test_merge_queue_validate_pin_targets_reference_for_moved_detail():
    text = MERGE_QUEUE_REFERENCE.read_text(encoding="utf-8")

    assert (
        "After enabling auto-merge or confirming queue placement, do not schedule a future wakeup"
        in text
    )
    assert "Do not use `mergeQueueEntry.estimatedTimeToMerge` as a progress indicator" in text


def test_context_continuity_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        CONTEXT_CONTINUITY_SKILL,
        "context-continuity",
        CONTEXT_CONTINUITY_REFERENCE,
        required=(
            "prepare-continuity --target . --stdin",
            "methodology-status --target . --fail-on-drift",
            "Do not turn handoff, resume, or context rotation into an option menu",
        ),
    )


def test_context_continuity_reference_retains_detailed_policy():
    text = CONTEXT_CONTINUITY_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1800
    assert text.startswith("# Context Continuity Policy Reference")
    assert "write the file in the same turn before doing anything else" in text
    assert "An alternate safe method is a single different mechanism" in text
    assert "If neither the CLI nor portable checkout fallback can be found" in text
    assert "Do not ask clarifying questions, report substantive status, or start analysis from Handoff Content before the methodology gates pass" in text
    assert "Run project-specific startup gates such as main status and open PR checks" in text
    assert "resolved portable CLI" in text
    assert "not a reason to ask for a person-specific path" in text
    assert "goal run path, current milestone, percent complete, and `goal-next` output" in text
    assert "milestone run path, current item, percent complete, and `milestone-next` output" in text
    assert "Continuity holds are condition-scoped evidence only" in text
    assert "The milestone ledger wins over a vague handoff summary at PR boundaries" in text
    assert "The goal ledger wins over a milestone-only or vague handoff summary at goal/milestone boundaries" in text
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85" in text
    assert "Default context rotation thresholds are soft `60%`, hard `75%`, and heartbeat `15m`" in text
    assert "Context exhaustion must match the signals in item 7, but it is not a terminal stop when compact/restart is available" in text
    assert "Do not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session`" in text
    assert "say `/compact me`" in text
    assert "After a context rotation, resume through startup gates" in text
    assert "The next session should be able to continue without asking the human operator what happened" in text
    assert "Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff" in normalized


def test_migrated_prose_policy_validate_pins_are_preserved():
    migrated_pins = [
        (
            BEHAVIOR_SPECS_REFERENCE,
            [
                "Reviewed business/customer/user behavior specs are upstream source material, not inspiration",
                "add `## Behavior Source Materials`",
                "BEHAVIOR-SOURCE-EXEMPT: <real reason>",
                "document every material deviation from the source material in the plan/spec",
                "behaviorSpecs.roleVocabulary.allowed",
                "quote obsolete source wording in backticks or blockquotes",
                "behavior-spec-status --target .",
                "Inactive scenarios are not coverage",
            ],
        ),
        (
            FRAMEWORK_INTAKE_REFERENCE,
            [
                "broad-load Markdown trees",
                "Archive or historical docs treated as current process",
            ],
        ),
        (
            REVIEW_BEFORE_PUSH_REFERENCE,
            [
                "Run one authoring-model native/self-check before R1",
                "For T2/T3 only, run the model-native review on the exact current assembled diff",
                "Do not hand a changed T2/T3 diff to Codex/Stage 2 after fixing review findings",
                "Plan-review convergence is a ladder",
                "Rounds 3-4 are self-authorized",
                "confirmed structural Critical",
                "Plan-review P1 must name the concrete user-visible failure or expensive rework",
                "codex-run --target . --risk-tier T1 --review-round R1",
            ],
        ),
        (
            RISK_TIER_REFERENCE,
            [
                "For T2/T3 plan review, run one authoring-model native/self-check before R1",
                "T1 keeps one cross-model implementation review round",
            ],
        ),
        (
            EXECUTION_PACKET_REFERENCE,
            [
                "risk-tier",
                "milestone-start --target . --plan <source-of-truth-plan>",
                "minervit-methodology goal-next --target .",
                "milestone-advance --target . --event pr-queued --pr <PR>",
                "At PR boundaries, `milestone-next` is the controller",
                "At goal boundaries, `goal-next` is the controller",
                "Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work",
            ],
        ),
        (
            DELIVERY_SUMMARY_REFERENCE,
            [
                "grounded progress narrative",
                "what capability was unlocked for users, admins, operators, or delivery velocity",
                "Use headings or labels only when they improve readability",
                "minervit-methodology goal-next --target .",
                "queued-delivery or PR-completion summary is incomplete until the milestone ledger is advanced",
                "Execution-packet work, source-of-truth-plan-backed work, and any PR implementing approved planned work are milestone work",
                "minervit-methodology milestone-advance --target . --event pr-queued --pr <PR>",
                "At every PR queued/completed boundary, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat, check visible context pressure",
                'do not use "what would you like" as a context-rotation fallback',
                "Every human-facing boundary summary must also log a compact event",
                "the board must be reconciled at every delivery / queued-delivery boundary",
                "backlog_provider_board_unplaced_warn",
                "minervit-methodology milestone-next --target .",
            ],
        ),
        (
            CONTEXT_CONTINUITY_REFERENCE,
            [
                "resolved portable CLI",
                "not a reason to ask for a person-specific path",
                "goal run path, current milestone, percent complete, and `goal-next` output",
                "milestone run path, current item, percent complete, and `milestone-next` output",
                "The milestone ledger wins over a vague handoff summary at PR boundaries",
                "The goal ledger wins over a milestone-only or vague handoff summary at goal/milestone boundaries",
                "Context rotation is routine maintenance for autonomous goal work",
                "Default context rotation thresholds are soft `60%`, hard `75%`, and heartbeat `15m`",
                "Context exhaustion must match the signals in item 7, but it is not a terminal stop when compact/restart is available",
                "say `/compact me`",
            ],
        ),
        (
            MERGE_QUEUE_REFERENCE,
            [
                "Advance the lane ledger with `minervit-methodology milestone-advance --target . --event pr-queued --pr <PR>`",
            ],
        ),
        (
            STAKEHOLDER_QUESTIONS_REFERENCE,
            [
                "stakeholder-question-ask --target .",
                "stakeholder-question-status --target . --sync",
            ],
        ),
        (
            EVENT_OBSERVABILITY_SKILL,
            [
                "name: event-observability",
                "minervit-methodology log-event --target .",
                "minervit-methodology event-viewer --target .",
                "Never write `events.log` or `events.jsonl` directly",
                "minervit-methodology event-audit --target . --since 24h --strict",
                "Baretail",
            ],
        ),
        (
            GRAPHIFY_NAVIGATION_REFERENCE,
            [
                "Use `graphify query`, `graphify path`, or `graphify explain`",
                "graphify . --update",
                "Do not run `graphify claude install`, `graphify codex install`",
                "graphify-out/` is generated local output",
            ],
        ),
        (
            MILESTONE_UPDATE_SKILL,
            [
                "# Milestone Update",
                "Publish internal, professional, text-only milestone-complete updates",
                "Do not generate a video or S3 review page for the internal milestone update",
                "goal-advance --event milestone-complete` is not allowed until the Product Milestones delivery marker exists",
                "short milestone keys such as `M3` are",
            ],
        ),
        (
            LANE_LIFECYCLE_REFERENCE,
            [
                "bin/minervit-methodology install-cli",
                "A missing `PATH` entry is not a failed methodology gate",
                "not a reason to ask for a person-specific checkout path",
                "Cached host plugin metadata is not a lane update failure",
                "do not ask the human operator to decide whether to inspect version/status",
                "restart that host/session",
                "latest-code-status --target . --write",
                "deep codebase/architecture/multi-angle analysis",
                "establish the latest-code baseline before spending analysis budget",
                "before trusting local lane files",
                "current-branch liveness check",
                "branch-liveness-check --target .",
                "branch-liveness-check --target . --strict",
                "If no active goal exists or the prior goal ledger is complete, use the printed `next_goal_name`, `next_goal_short_description`, `next_goal_claude_prompt`, and `next_goal_next_action`",
                "minervit-methodology goal-next --target .",
                "Lane startup also reports milestone run state",
                "Lane startup also reports cross-lane coordination state and bootstraps missing coordination artifacts by default",
                "missing, stale, untracked, uncommitted, or unpushed state in the current lane's own status file, "
                "or in the shared contract or lane board, fails",
                "lane-coordination-note --target .",
                "Lane startup also reports repo event-log paths",
                "adapter-approved event commands",
                "Lane startup also reports context rotation policy",
                "Do not ask the human operator to run `/compact`",
                "Claude context-rotation heartbeat hook",
                "minervit-methodology milestone-next --target .",
                "minervit-methodology milestone-advance --target . --event <event>",
                "document context budget state",
                "context-continuity",
            ],
        ),
        (
            LANE_COORDINATION_SKILL,
            [
                "Use the git repo as the coordination backbone",
                "Lane coordination is mandatory by default",
                "Each lane updates only its own status file",
            ],
        ),
        (
            CANONICAL_RULES,
            [
                "Cross-Lane Coordination",
                "Default enforcement is strict",
                "shared contract/interface PR",
            ],
        ),
        (
            PROJECT_BOOTSTRAP_REFERENCE,
            [
                "documentContext",
                "context-bootstrap --target . --write",
                "reviewed business/customer behavior-spec source materials",
                "precise actor-role vocabulary",
            ],
        ),
    ]

    for path, phrases in migrated_pins:
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        for phrase in phrases:
            assert phrase in text or phrase in normalized


def test_context_continuity_reference_orders_resume_gates_before_handoff_use():
    text = CONTEXT_CONTINUITY_REFERENCE.read_text(encoding="utf-8")
    resolve = text.index("Resolve the methodology CLI")
    missing = text.index("If neither the CLI nor portable checkout fallback can be found")
    lane = text.index("Run `minervit-methodology lane-start --target .`")
    status = text.index("Run `minervit-methodology methodology-status --target . --fail-on-drift`")
    failure = text.index("If the status gate fails")
    skipped = text.index("If either methodology gate is skipped or fails")
    no_questions = text.index("Do not ask clarifying questions")
    authority = text.index("Do not treat the handoff content as execution authority")
    project = text.index("Run project-specific startup gates")
    resume = text.index("Resume from its `Next Action`")

    assert resolve < missing < lane < status < failure < skipped < no_questions < authority < project < resume


def test_iteration_review_skill_is_concise_entrypoint():
    text = ITERATION_REVIEW_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 650
    assert "name: iteration-review" in lines
    assert "references/iteration-review-policy.md" in text
    assert "Read `references/iteration-review-policy.md` in full" in text
    assert "Do not proceed from this entrypoint alone" in text
    assert "## Fast Path" in text
    assert "## Content And Media" in text
    assert "## Boundary Rules" in text
    assert "iterationReview.enabled" in text
    assert "minervit-methodology iteration-review-status --target . --strict" in normalized
    assert "minervit-methodology validate-iteration-review --target . --file <record.json>" in normalized
    assert "minervit-methodology generate-iteration-review-page --target . --record <record.json> --write" in normalized
    assert "minervit-methodology publish-iteration-review --target . --record <record.json>" in normalized
    assert "minervit-methodology iteration-review-delivery-check --target . --record <record.json>" in normalized
    assert "publish-deploy-ready-update" in text
    assert "deployment-notification-status --target . --strict" in text
    assert "The review folder slug must match the active `goal_id`" in text
    assert "Do not post a GitHub URL as the primary stakeholder link" in text
    assert "docs/iteration-reviews/<goal-or-milestone-id>/goal-review.json" in text
    assert "Never commit generated videos, screenshots, thumbnails, clips, posters, or other media binaries" in text
    assert "Video, poster, screenshot, and page-media production is agent-owned delivery work" in text
    assert "Do not say agents do not do videos or media production" in text
    assert "missing recap video is not a publishable partial stakeholder update" in text
    assert "Boundary announcement is non-blocking" in text
    assert "Do not ask `Want me to generate the review?`" in text


def test_iteration_review_reference_retains_detailed_policy():
    text = ITERATION_REVIEW_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1300
    assert text.startswith("# Iteration Review Policy Reference")
    assert "iterationReview.enabled" in text
    assert "Internal milestone-complete visibility belongs to the `milestone-update` skill" in text
    assert "DATA-CONTRACT.md" in text
    assert "docs/iteration-reviews/<goal-or-milestone-id>/goal-review.json" in text
    assert "musicUrl" in text
    assert "musicVolume" in text
    assert "built-in SVG poster thumbnail" in text
    assert "S3/CloudFront" in text
    assert "missing recap video is not a publishable partial stakeholder update" in text
    assert "OPERATOR_APPROVED_PARTIAL_ITERATION_REVIEW" in text
    assert "--operator-approval-token" in text
    assert "--skip-chat" in text
    assert "Google Chat webhook" in text
    assert "Do not post a GitHub URL as the primary stakeholder link" in normalized
    assert "the review folder slug must match the active `goal_id`" in normalized
    assert "publish-deploy-ready-update" in text
    assert "deployment-notification-status --target . --strict" in normalized
    assert "iteration-review-delivery-check --target . --record <record.json>" in normalized
    assert "Do not say agents do not do videos or media production" in text
    assert "do not replace the required review with a note that it is \"teed up\" for later" in text
    assert "PR numbers, repository links, file paths, routes, schemas, database details, test tiers, review rounds, commits, CI mechanics, and implementation jargon must not appear" in text
    assert "each milestone completion gets its own customer-facing review" in text
    assert "otherwise use the internal `milestone-update` workflow for milestone completion" in text
    assert "`iterationReview.outputs.video: false` disables recap-video rendering only" in text
    assert "Low context, fatigue, marathon-session length, or the desire for a \"fresh context\" is context-rotation work" in text
    assert "page output may proceed only for a strictly text-only `GoalReview` record" in text
    assert "Video, poster, screenshot, and page-media production is agent-owned delivery work" in text


def test_project_bootstrap_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        PROJECT_BOOTSTRAP_SKILL,
        "project-bootstrap",
        PROJECT_BOOTSTRAP_REFERENCE,
        required=(
            "adapter-bootstrap-questions --target .",
            "Repo-local `.minervit/adapter.json`",
            "do not hand-edit generated",
        ),
    )


def test_project_bootstrap_reference_retains_detailed_policy():
    text = PROJECT_BOOTSTRAP_REFERENCE.read_text(encoding="utf-8")

    assert len(text.split()) >= 1100
    assert text.startswith("# Project Bootstrap Policy Reference")
    assert "adapter bootstrap interview is a mandatory setup gate for unmanaged projects" in text
    assert "adapter-bootstrap-questions --target . --write" in text
    assert ".ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md" in text
    assert "AskUserQuestion` or the host-equivalent question mechanism" in text
    assert "bootstrapEvidence" in text
    assert "status: \"interviewed\"" in text
    assert "status: \"repo-evident\"" in text
    assert "Do not use `legacy-reviewed` for new projects" in text
    assert "Do not hand-write or copy `.minervit-ai-delivery.json` directly into a lane" in text
    assert "technical stack non-negotiables, approved cloud providers/hosting platforms" in text
    assert "cloud services default to AWS for new projects" in text
    assert "the AWS CLI profile, SSO/login path, and identity check" in text
    assert "GitHub Projects is authoritative" in text
    assert "automatically P0/P1 bug categories" in text
    assert "precise actor-role vocabulary" in text
    assert "reviewed business/customer behavior-spec source materials" in text
    assert "autonomy boundaries" in text
    assert "the unresolved interview was completed with the human operator" in text
    assert "every required adapter fact is directly supported by repo evidence" in text
    assert "the adapter remains fail-closed with `BOOTSTRAP REQUIRED`" in text
    assert "No generic operational adapter exists" in text
    assert "Configure a merge-conflict check" in text
    assert "Fail-closed scaffold commands are acceptable during drafting only" in text


def test_board_item_updates_skill_is_concise_entrypoint():
    _assert_thin_skill_entrypoint(
        BOARD_ITEM_UPDATES_SKILL,
        "board-item-updates",
        BOARD_ITEM_UPDATES_REFERENCE,
        required=(
            "sanctioned backlog-provider commands",
            "board-backed subtask is active",
            "Never change board fields",
        ),
    )


def test_board_item_updates_reference_retains_detailed_policy():
    text = BOARD_ITEM_UPDATES_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 1000
    assert text.startswith("# Board Item Updates Policy Reference")
    assert "Methodology skills are file-backed policy" in text
    assert "stakeholder-authored substance" in text
    assert "Stakeholder-authored substance | title/summary, body, acceptance criteria, labels, priority, milestone field | **Forbidden**" in text
    assert "The three tiers" in text
    assert "Do these freely. Always through the sanctioned path, never raw `gh project ...` or GraphQL" in text
    assert "Post a progress update, status note, blocker, or handoff" in text
    assert "minervit-methodology backlog-provider-update --item <id-or-url> --status" in text
    assert "Native sub-issues/subtasks that are also board items have their own Status" in text
    assert "The normal active-claim path is `minervit-methodology backlog-provider-sync --item <id-or-url> --write`" in text
    assert "Later sanctioned parent status moves reconcile board-backed subtasks too" in text
    assert "Sanctioned subtask active-status moves reconcile the native parent active too" in text
    assert "an open board-backed subtask blocks marking the parent done" in text
    assert "Subtask issue/PR closure is independent of board Status" in text
    assert "A native subtask missing from the board blocks parent Done" in text
    assert "Moving to a done status requires `--verification-evidence`, `--verification-evidence-file`, or `--verification-evidence-url`" in text
    assert "## Verification Evidence" in text
    assert "Never reassign away from a human" in text
    assert "Acceptance criteria" in text and "protected by `body`" in text
    assert "All keys default `false`" in text
    assert '"allowedItemWrites"' in text
    assert "absence of the block = everything `false`" in text
    assert '"title": false' in text
    assert '"body": false' in text
    assert '"labels": false' in text
    assert '"milestone": false' in text
    assert "**Priority** is a board single-select field the stakeholder owns" in text
    assert "Never add/remove/edit columns, single-select options, or fields" in text
    assert "**Forbidden, always**" in text
    assert "A board-schema mismatch is resolved by re-adopting the adapter to the board" in text
    assert "Editing an issue **title, body, or acceptance criteria**" in text
    assert "The sanctioned status write reports \"blocked\"" in text
    assert "Treating \"the board is the source of truth for status\" as license to rewrite item **content**" in normalized


def test_bug_intake_triage_skill_is_concise_entrypoint():
    text = BUG_INTAKE_TRIAGE_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 600
    assert "name: bug-intake-triage" in lines
    assert "bugBacklog" in text
    assert "backlogAdapter" in text
    assert "backlogProvider" in text
    assert "## Triage Order" in text
    assert "## Required Bug Fields" in text
    assert "## Routing Rules" in text
    assert "Default auth, email, tenant data, security, deploy, billing, data-loss, and customer-blocking failures to at least `P1`" in text
    assert "Do not ask \"specs or GitHub?\"" in text
    assert "Customer-facing bugs are not complete until" in text
    assert "BOOTSTRAP REQUIRED" in text
    assert "ask one exact setup question instead of inventing policy" in text
    assert "backlog-provider-export --target . --item-path <bug-artifact.md> --type bug [--customer-facing] --write" in text
    assert "backlog-provider-board-check --target ." in text
    assert "Use the sanctioned board/status commands" in text
    assert "Do not mutate board structure" in text
    assert "tracker of record" in normalized


def test_example_service_preflight_skill_is_concise_entrypoint():
    text = EXAMPLE_SERVICE_PREFLIGHT_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 330
    assert "name: example-service-preflight" in lines
    assert "EXAMPLE / STACK-SPECIFIC SKILL" in text
    assert "not part of the portable methodology core" in text
    assert "references/example-service-preflight-policy.md" in text
    assert "Read `references/example-service-preflight-policy.md` in full" in text
    assert "make ci-status-main" in text
    assert "branch-liveness-check --target . --strict" in text
    assert "Before commit, review, push, or tactical subagent dispatch" in text
    assert "minervit-methodology lane-run --target . -- make pf-fast" in text
    assert "make test-env-up" in text
    assert "make preflight" in text
    assert "Use the project's wrapped Codex review script, not bare `codex review`" in text
    assert ".ai-work/lane-env.sh" in text
    assert "Customer-facing behavior requires Gherkin unless `GHERKIN-EXEMPT: <reason>`" in normalized
    assert "Missing tests for new functions, endpoints, or pages are Critical" in text
    assert "Do not combine FastAPI `@limiter.limit` with `response_model=`" in text


def test_example_service_preflight_reference_retains_detailed_policy():
    text = EXAMPLE_SERVICE_PREFLIGHT_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert len(text.split()) >= 500
    assert text.startswith("# Example Service Preflight Policy Reference")
    assert "stack-specific worked example for one Make/CI-driven API service" in text
    assert "not portable methodology core" in text
    assert "Run `make ci-status-main`" in text
    assert "gh pr list --author '@me' --state open --limit 50" in text
    assert "number,title,url,createdAt,headRefName,baseRefName,isDraft,mergeStateStatus,statusCheckRollup" in text
    assert "minervit-methodology branch-liveness-check --target . --strict" in text
    assert "queued, auto-merge-enabled, merged, or closed current-branch PR is inactive" in normalized
    assert "git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null" in text
    assert "main health is bad, deploy failed, an open PR has failed/blocked checks" in normalized
    assert "Clean queued PRs do not need active monitoring" in text
    assert "Treat `make ci-status-main` as the early-warning main-health baseline" in text
    assert "poll at least every 10 minutes" in text
    assert "make pf-fast" in text
    assert "make test-env-up" in text
    assert "make preflight" in text
    assert "not bare `codex review`" in text
    assert "APP_PG_PORT" in text
    assert "APP_REDIS_PORT" in text
    assert "COMPOSE_PROJECT_NAME" in text
    assert "Do not add a broad machine-wide lock for preflight" in text
    assert "Customer-facing behavior requires Gherkin unless `GHERKIN-EXEMPT: <reason>`" in normalized
    assert "Secrets must never be returned, logged, or stored plaintext" in text
    assert "Tenant endpoints must enforce tenant isolation" in text
    assert "Do not combine FastAPI `@limiter.limit` with `response_model=`" in text


def test_makerkit_implementation_skill_is_concise_entrypoint():
    text = MAKERKIT_IMPLEMENTATION_SKILL.read_text(encoding="utf-8")
    lines = _stripped_lines(text)
    normalized = " ".join(text.split())

    assert len(text.split()) <= 700
    assert "name: makerkit-implementation" in lines
    assert "EXAMPLE / STACK-SPECIFIC SKILL" in text
    assert "references/makerkit-implementation-policy.md" in text
    assert "Read `references/makerkit-implementation-policy.md` in full" in text
    assert "before any MakerKit implementation, port, package/import/export decision" in text
    assert "auth/session/ownership/tenant/billing/data/migration/deployment/verification/healthcheck/smoke" in text
    assert "Do not proceed from this entrypoint alone" in text
    assert "customer names, account IDs, live hosts, private adapter paths" in text
    assert "## First Moves" in text
    assert "## Core Posture" in text
    assert "## Non-Negotiables" in text
    assert "## Common Wrong Turns" in text
    assert "references/current-lessons.md" in text
    assert "references/example-engine-makerkit.md" in text
    assert "Treat MakerKit as the owned SaaS platform, not a blank Next.js app" in text
    assert "Use the installed kit's monorepo shape unless local source proves otherwise" in text
    assert "Use the correct auth surface for the file type" in text
    assert "Better Auth anonymous users are real `user` rows with `isAnonymous: true`" in text
    assert "never use `drizzle-kit push` or ad hoc schema mutation" in text
    assert "Cross-tenant and cross-owner tests are mandatory for tenant/owner behavior" in text
    assert "Use MakerKit billing abstractions for subscriptions" in text
    assert "Use the active adapter's cloud policy" in text
    assert "Never assume `pnpm healthcheck` covers unit tests" in normalized
    assert "tie smoke evidence to build identity" in text
    assert "Do not edit Better Auth core generated tables for app-specific fields" in text


def test_makerkit_implementation_reference_retains_detailed_policy():
    text = MAKERKIT_IMPLEMENTATION_REFERENCE.read_text(encoding="utf-8")

    assert len(text.split()) >= 1700
    assert text.startswith("# MakerKit Implementation Policy Reference")
    assert "before any MakerKit implementation, port, package/import/export decision" in text
    assert "auth/session/ownership/tenant/billing/data/migration/deployment/verification/healthcheck/smoke" in text
    assert "generalized public-stack guidance for an example/community stack pack" in text
    assert "customer names, account IDs, live hosts, private adapter paths" in text
    assert "Treat MakerKit as the owned SaaS platform, not a blank Next.js app" in text
    assert "Use the installed kit's monorepo shape unless local source proves otherwise" in text
    assert "`apps/web`: main Next.js app" in text
    assert "`packages/database`: Drizzle schema, migrations, DB utilities" in text
    assert "Schema usually belongs in `packages/database/src/schema/schema.ts`" in text
    assert "Drizzle config usually lives at `packages/database/drizzle.config.mjs`" in text
    assert "Use the correct auth surface for the file type" in text
    assert "auth.api.getSession({ headers: requestHeaders })" in text
    assert "authenticatedActionClient" in text
    assert "Better Auth anonymous users are real `user` rows with `isAnonymous: true`" in text
    assert "A kit super-admin grant can hide an incorrect domain-role gate" in text
    assert "Public/signup/account/org/billing/payment lockdown must cover unauthenticated users" in text
    assert "Do not use `drizzle-kit push` or ad hoc schema mutation" in text
    assert "Cross-tenant and cross-owner tests need positive fixture reads first" in text
    assert "Reject unset, malformed, fallback, or production-equivalent test URLs" in text
    assert "Port by phase, not by enthusiasm" in text
    assert "import-graph completeness check" in text
    assert "Use direct Stripe SDK only when a required one-off payment flow is not covered" in text
    assert "Grant durable entitlement idempotently by stable payment key" in text
    assert "Use the active adapter's cloud policy" in text
    assert "Do not assume a managed SSR host can reach a private managed database" in text
    assert "Never bake real DB credentials or auth secrets into a public image" in text
    assert "Do not assume `pnpm healthcheck` covers tests" in text
    assert "Capture build identity in smoke evidence" in text
    assert "Do not let a clean review manifest hide superseded convention text" in text
