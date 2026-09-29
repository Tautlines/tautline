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
