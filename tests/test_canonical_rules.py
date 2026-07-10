"""D4 (0.6.113): the canonical Goal Orchestration grooming-DoR bullet + disambiguation lint guard.

The grooming bullet must name the Definition of Ready and explicitly distinguish grooming-decompose
from plan-review cap/focus-transfer handling, and must never use the bare word "decompose"/"split" without the
distinguishing parenthetical (so a future edit cannot silently re-collide the two controls).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "methodology" / "canonical-rules.md"
VALIDATE_SH = ROOT / "scripts" / "validate.sh"
REVIEW_BEFORE_PUSH_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "review-before-push"
    / "references"
    / "review-before-push-policy.md"
)
REVIEW_BEFORE_PUSH_POLICY_MODULE = ROOT / "methodology" / "policy" / "17-review-before-push.md"
REJECTED_TOOL_CALL_POLICY_MODULE = ROOT / "methodology" / "policy" / "04a-rejected-tool-call-recovery.md"
VERIFIED_HUMAN_INSTRUCTIONS_POLICY_MODULE = ROOT / "methodology" / "policy" / "08-verified-human-instructions.md"
GOVERNANCE_POLICY_MODULE = ROOT / "methodology" / "policy" / "02-methodology-repository-governance.md"
GOAL_ORCHESTRATION_POLICY_MODULE = ROOT / "methodology" / "policy" / "10-goal-orchestration.md"
BACKLOG_PROVIDER_POLICY_MODULE = ROOT / "methodology" / "policy" / "10a-backlog-provider.md"
BOARD_CURRENCY_POLICY_MODULE = ROOT / "methodology" / "policy" / "10b-board-currency.md"
LANE_COORDINATION_POLICY_MODULE = ROOT / "methodology" / "policy" / "11-cross-lane-coordination.md"
CONTEXT_ROTATION_POLICY_MODULE = ROOT / "methodology" / "policy" / "12-context-rotation.md"
PLANNING_POLICY_MODULE = ROOT / "methodology" / "policy" / "13-planning.md"
TDD_AND_BEHAVIOR_SPECS_POLICY_MODULE = ROOT / "methodology" / "policy" / "15-tdd-and-behavior-specs.md"
MERGE_AND_CI_POLICY_MODULE = ROOT / "methodology" / "policy" / "18-merge-and-ci.md"
DEMO_AND_STAGING_POLICY_MODULE = ROOT / "methodology" / "policy" / "19-demo-and-staging-deployment.md"
LANE_LIFECYCLE_POLICY_MODULE = ROOT / "methodology" / "policy" / "21-lane-lifecycle.md"
AUTONOMY_AND_STATUS_POLICY_MODULE = ROOT / "methodology" / "policy" / "04-autonomy-and-status.md"
DELIVERY_SUMMARIES_POLICY_MODULE = ROOT / "methodology" / "policy" / "09-delivery-summaries.md"
DOCUMENT_CONTEXT_POLICY_MODULE = ROOT / "methodology" / "policy" / "24-document-context-budget.md"
CONTEXT_CONTINUITY_POLICY_MODULE = ROOT / "methodology" / "policy" / "29-context-continuity.md"
SESSION_JOURNALS_POLICY_MODULE = ROOT / "methodology" / "policy" / "30-session-journals.md"
TECHNICAL_STACK_POLICY_MODULE = ROOT / "methodology" / "policy" / "14-technical-stack-and-platform-defaults.md"
UNMANAGED_PROJECT_BOOTSTRAP_POLICY_MODULE = ROOT / "methodology" / "policy" / "22-unmanaged-project-bootstrap.md"
BACKGROUND_MONITORING_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "background-task-monitoring"
    / "references"
    / "background-monitoring-policy.md"
)
DELIVERY_COMMUNICATIONS_REFERENCE = ROOT / "docs" / "reference" / "operations" / "delivery-communications.md"
ITERATION_REVIEW_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-ops"
    / "skills"
    / "iteration-review"
    / "references"
    / "iteration-review-policy.md"
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
RISK_TIER_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "risk-tier-autonomy"
    / "references"
    / "risk-tier-policy.md"
)
STARTUP_RELEASE_AND_AUTHORITY_MARKERS = (
    "Unlocked adapter-backed product/client lanes do not raw-pull latest methodology by default",
    "When the human operator asks for current project status",
    "minervit-methodology latest-code-status --target . --write",
    "Before deep codebase analysis, architecture review, multi-angle analysis",
    "Do not run deep analysis from a stale local checkout",
    "A stale local lane may be useful evidence about that lane only",
    "Before running startup gates, resolve the methodology CLI",
    "if it is missing from `PATH` or exits 127/command-not-found",
    "MINERVIT_METHODOLOGY_REPO",
    "bin/minervit-methodology install-cli",
    "A missing `PATH` entry is not a failed methodology gate",
    "not a reason to ask for a person-specific checkout path",
    "Cached host plugin metadata is not a lane update failure",
    "do not ask the human operator to decide whether to inspect version/status",
    "`VERSION` is reusable release truth",
    "release-note stub",
    "release-notes archive branch",
    'publish-release-update --version "$(cat VERSION)"',
    "Process rules must never be sourced from Open Brain, Claude memories, local memories, or feedback-memory files",
    "review.codexFastMode",
)
REVIEW_EVIDENCE_MARKERS = (
    "`plan-finalization-precheck` and the `Cross-Model Review Evidence` section exist only for T2/T3 plans",
    "bind it with `finalize-plan-review`",
    "Do not rerun Codex just to bind manifest evidence",
    "Plan-review cap is two rounds",
    "R3 is allowed only for a confirmed structural Critical from R2",
    "hand-edit `.plan-reviews`, disable hooks, skip required `ExitPlanMode` checks, or ask for a bypass",
    "Plan-review evidence is content-hash-bound and verdict-bound when it exists",
    "For T2/T3 plan review, run one authoring-model native/self-check before R1",
    "do not spawn new source-of-truth plans solely because the plan-review cap fired",
    "Implementation review is risk-tiered",
    "T1+ keeps one cross-model review round",
    "The `review-before-push` skill owns the detailed command sequence",
    "Evidence is scoped to the assembled outgoing diff",
    "tracked `<planningArtifacts.sourceOfTruth>/.impl-reviews/` ledger",
    "Review budgets come from adapter `review.roundBudgets`",
    "Cross-Model Review Evidence",
)
REVIEW_DETAIL_MARKERS = (
    "When Codex review is run through a CLI wrapper, the review gate includes retrieving and classifying the final assistant output.",
    "If Codex/Stage 2 reports Critical or P1/Important findings, fix them and rerun the tier-appropriate review",
    "public API leakage, atomicity/concurrency, breaking-change caller fan-out, idempotency/unique-index behavior, migration/seed ordering, generated/derived artifact freshness, and review-evidence/process integrity",
    "Project `review.codexWrapper` scripts should review the committed outgoing diff from the configured base branch to `HEAD`",
    "Implementation review budgets are risk-tiered",
    'codex-run --target . --risk-tier T1 --review-round R1',
    "Starting a final, R3, `cap`, rerun, or any other named terminal/retry review round does not complete the review gate",
    "A stale review log is stale/hung review work, not progress",
)
COMMUNICATION_AND_DELIVERY_MARKERS = (
    "Ops-owned delivery communications, deployment notifications, milestone updates, product notes, event logs, usage evidence, and session journals",
    "The ops plugin owns provider-specific procedure, delivery markers, and publication detail",
    "Product Chat notes are quick, human-requested messages",
    "The reliable path is the build/deploy pipeline itself",
    "Iteration reviews are customer-facing communication artifacts",
    "Milestone updates are internal operator visibility artifacts",
    "A latest failed deploy, repeated deploy failures, no recent successful deploy",
    "A transient external dependency is not a terminal handoff",
    "docs/iteration-reviews/<goal-or-milestone-id>/goal-review.json",
    "Generated videos, thumbnails, screenshots, posters, clips, and render scratch output must stay out of git",
    "review folder slug must match the active `goal_id`",
    "short milestone keys such as `M3` are canonicalized to the active milestone title",
    "outputs.video: false` disables recap-video rendering only",
    "posts that CloudFront page URL to the configured Google Chat webhook",
    'Low context, fatigue, marathon-session length, or the desire for a "fresh context" is context-rotation work',
    "Production/staging/demo deployment closeout is agent-owned",
    "Routine deploy-to-close work is agent-owned",
)
DRIVE_AND_PLAN_REVIEW_AUTONOMY_MARKERS = (
    "planning that item is the next safe action unless a true blocker exists",
    "Treat an item as identified when context gives enough signal",
    "T2/T3 work",
    "Plan finalization means asking for approval to implement",
    "Plan-review cap is two rounds",
    "R3 is allowed only for a confirmed structural Critical from R2",
    "unresolved findings transfer into the implementation review focus list",
    "do not spawn new source-of-truth plans solely because the plan-review cap fired",
)
AUTONOMY_AND_STATUS_MARKERS = (
    "## Autonomy And Status",
    "Own forward motion",
    "Ask one exact blocker question only when the missing decision changes approved scope",
    "Do not convert required process into a choice",
    "Treat work-evasion as a process defect",
    "No-work-in-flight after a landed, merged, or queued PR is a sequence, not a menu",
    "Rejected, denied, cancelled, or blocked tool calls do not create a global stop",
    "Status updates are for the human operator",
    "Do not mandate fixed heading schemas",
    "Methodology skills are file-backed policy",
    "When a methodology/process regression occurs",
)
STABLE_MONITOR_RESPONSE_GUARD_AND_RCA_MARKERS = (
    "Methodology regression RCA artifacts and ops-owned improvement evidence do not belong on `main`",
    "Publish archive evidence through the owning archive command/skill",
    "archive publication must not mutate the active methodology release checkout",
    "--allow-release-checkout-write",
    "Do not end a turn with only \"monitor is running\", \"monitor watches\", \"waiting on merge\", \"waiting on checks\", \"R2 running\"",
    "Passive monitor stop examples include \"CI is processing\", \"the deploy is underway\", \"the review is running\", \"checks are in progress\"",
    "Before any autonomous-loop yield, delayed wakeup, `ScheduleWakeup`, or host-equivalent heartbeat",
    "Frustration, profanity, or an angry interjection is not an explicit stop",
    "A monitor without forward motion is also incomplete work",
    "Heartbeat/poll cadence must be concrete and no longer than 10 minutes",
    "arm `ScheduleWakeup` or an equivalent host self-wakeup at the same cadence",
    "Claude Stop response guards and tool-rejection hooks are mandatory",
    "response guard is active only when the lane has an active goal ledger and the current Claude transcript or hook payload proves a live goal session",
    "terminal continuity omission",
    "Strict monitor checks require a verified PID/process identity",
    "Terminal monitor states are success, failure, cancelled",
)
TECH_STACK_AND_NEXT_ACTION_MARKERS = (
    # Compatibility-first coverage for current adapter-overridable defaults. Provider-registry
    # and null-provider work should intentionally update or remove these AWS/default pins.
    "New projects default to AWS for cloud services",
    "Do not introduce Vercel, GCP, Azure, Netlify, Fly.io, Render, Supabase, Firebase",
    "Tool, framework, starter-template, AI, or hosting-product defaults are not approval",
    "AWS CLI is the default deploy credential path",
    "Do not ask for SSH keys, create SSH-key blockers, or invent alternate deploy credentials until the AWS CLI path has been checked",
    "Do not default uncertain work into plan review",
    "TODO-only, generic, vague, missing-test, missing-gate, or missing-acceptance plans are stubs",
    "If no goal ledger next action, execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates",
    "begin planning, or pause",
    "Next milestone is <name>. Want me to begin planning, or pause here?",
)


def _grooming_bullet():
    text = CANONICAL.read_text()
    for line in text.splitlines():
        if "grooming Definition of Ready" in line:
            return line
    return ""


def test_canonical_grooming_rule_present():
    bullet = _grooming_bullet()
    assert bullet, "canonical grooming-DoR bullet missing"
    assert "Definition of Ready" in bullet
    assert "validate-grooming" in bullet
    assert "native sub-issue" in bullet
    assert "## Verification" in bullet


def test_canonical_grooming_disambiguation_present():
    bullet = _grooming_bullet()
    assert "distinct from plan-review cap/focus-transfer handling" in bullet
    # Lint guard: the grooming bullet must never use bare "decompose"/"split" without the
    # distinguishing parenthetical phrase being present in the same bullet.
    if re.search(r"\bdecompose\b|\bsplit\b|\bsplitting\b", bullet):
        assert "distinct from plan-review cap/focus-transfer handling" in bullet


def test_canonical_grooming_evidence_only_memory():
    bullet = _grooming_bullet()
    assert "Memory or Open Brain may inform DoR content but never defines the DoR" in bullet
    # No lane-specific leakage in the canonical rule.
    assert "Private Product A" not in bullet


def test_canonical_rules_are_vendor_neutral():
    """The canonical ruleset is a REPLACEABLE DEFAULT, not Minervit's private playbook.

    cross-counterproductive-7 (productization): canonical-rules.md must name no specific
    customer/product. The smoking gun was a 'must stay on for the Private Product A app' clause at the
    board-order bullet. This guard fails closed if any customer/product name re-enters canonical,
    so the open-core default ruleset stays decoupled from Minervit's own products.
    """
    text = CANONICAL.read_text()
    for token in ("Private Product A", "private-product-a", "Private Product B", "private-product-b", "private-product-c", "Private Product C"):
        assert token not in text, f"canonical-rules.md leaks a customer/product name: {token!r}"


def test_canonical_rules_keep_startup_release_and_authority_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in STARTUP_RELEASE_AND_AUTHORITY_MARKERS if marker not in text]

    assert missing == []


def test_canonical_rules_order_continuity_handoff_gates_before_project_gates():
    text = CANONICAL.read_text(encoding="utf-8")
    gate = text.index("A continuity handoff is not execution authority until both methodology gates run in order")
    no_questions = text.index("Before both methodology gates pass")
    failure = text.index("If the methodology status gate fails")
    skipped = text.index("If either methodology gate is skipped or fails")
    missing = text.index("If the methodology status gate cannot run")
    project = text.index("Project-specific gates such as main status")

    assert gate < no_questions < failure < skipped < missing < project


def test_canonical_rules_keep_review_evidence_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in REVIEW_EVIDENCE_MARKERS if marker not in text]

    assert missing == []


def test_review_detail_markers_live_in_review_skills():
    detail_text = REVIEW_BEFORE_PUSH_REFERENCE.read_text()
    missing = [marker for marker in REVIEW_DETAIL_MARKERS if marker not in detail_text]

    assert missing == []


def test_review_before_push_policy_module_stays_concise():
    words = REVIEW_BEFORE_PUSH_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 321


def test_rejected_tool_call_policy_module_stays_concise():
    words = REJECTED_TOOL_CALL_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 206


def test_verified_human_instructions_policy_module_stays_concise():
    words = VERIFIED_HUMAN_INSTRUCTIONS_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 205


def test_methodology_governance_policy_module_stays_concise():
    words = GOVERNANCE_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 270


def test_goal_orchestration_policy_module_stays_concise():
    words = GOAL_ORCHESTRATION_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 390


def test_board_currency_policy_module_stays_concise():
    words = BOARD_CURRENCY_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 355


def test_lane_coordination_policy_module_stays_concise():
    words = LANE_COORDINATION_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 220


def test_backlog_provider_policy_module_stays_concise():
    words = BACKLOG_PROVIDER_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 345


def test_merge_and_ci_policy_module_stays_concise():
    words = MERGE_AND_CI_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 357


def test_tdd_and_behavior_specs_policy_module_stays_concise():
    words = TDD_AND_BEHAVIOR_SPECS_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 210


def test_planning_policy_module_stays_concise():
    words = PLANNING_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 385


def test_demo_and_staging_policy_module_stays_concise():
    words = DEMO_AND_STAGING_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 210


def test_lane_lifecycle_policy_module_stays_concise():
    words = LANE_LIFECYCLE_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 365


def test_autonomy_and_status_policy_module_stays_concise():
    words = AUTONOMY_AND_STATUS_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 377


def test_delivery_summaries_policy_module_stays_concise():
    words = DELIVERY_SUMMARIES_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 330


def test_current_status_truth_policy_module_stays_concise():
    words = (ROOT / "methodology" / "policy" / "05-current-status-truth.md").read_text(encoding="utf-8").split()

    assert len(words) <= 225


def test_context_rotation_policy_module_stays_concise():
    words = CONTEXT_ROTATION_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 256


def test_context_continuity_policy_module_stays_concise():
    words = CONTEXT_CONTINUITY_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 382


def test_document_context_policy_module_stays_concise():
    words = DOCUMENT_CONTEXT_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 225


def test_technical_stack_policy_module_stays_concise():
    words = TECHNICAL_STACK_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 235


def test_unmanaged_project_bootstrap_policy_module_stays_concise():
    words = UNMANAGED_PROJECT_BOOTSTRAP_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 287


def test_background_work_policy_module_stays_concise():
    words = (ROOT / "methodology" / "policy" / "20-background-work.md").read_text(encoding="utf-8").split()

    assert len(words) <= 375


def test_session_journals_policy_module_stays_concise():
    words = SESSION_JOURNALS_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 240


def test_communication_and_delivery_markers_live_in_policy_or_references():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            CANONICAL,
            BACKGROUND_MONITORING_REFERENCE,
            DELIVERY_COMMUNICATIONS_REFERENCE,
            ITERATION_REVIEW_REFERENCE,
            MILESTONE_UPDATE_REFERENCE,
            RISK_TIER_REFERENCE,
        )
    )
    missing = [marker for marker in COMMUNICATION_AND_DELIVERY_MARKERS if marker not in text]

    assert missing == []


def test_canonical_rules_keep_drive_and_plan_review_autonomy_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in DRIVE_AND_PLAN_REVIEW_AUTONOMY_MARKERS if marker not in text]

    assert missing == []


def test_canonical_rules_keep_autonomy_and_status_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in AUTONOMY_AND_STATUS_MARKERS if marker not in text]

    assert missing == []


def test_canonical_rules_keep_monitor_response_guard_and_rca_archive_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in STABLE_MONITOR_RESPONSE_GUARD_AND_RCA_MARKERS if marker not in text]

    assert missing == []


def test_canonical_rules_keep_tech_stack_and_next_action_markers():
    text = CANONICAL.read_text()
    missing = [marker for marker in TECH_STACK_AND_NEXT_ACTION_MARKERS if marker not in text]

    assert missing == []


def test_migrated_canonical_markers_stay_out_of_validate_sh():
    validate_lines = VALIDATE_SH.read_text(encoding="utf-8").splitlines()
    migrated_markers = (
        STARTUP_RELEASE_AND_AUTHORITY_MARKERS
        + REVIEW_EVIDENCE_MARKERS
        + COMMUNICATION_AND_DELIVERY_MARKERS
        + DRIVE_AND_PLAN_REVIEW_AUTONOMY_MARKERS
        + TECH_STACK_AND_NEXT_ACTION_MARKERS
    )

    offenders = [
        f"{line_number}: {line}"
        for line_number, line in enumerate(validate_lines, start=1)
        if re.search(r"\b(?:[ef]?grep|rg)\b", line)
        and "methodology/canonical-rules.md" in line
        and any(marker in line for marker in migrated_markers)
    ]
    assert offenders == []
