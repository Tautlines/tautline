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
    "tautline latest-code-status --target . --write",
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
    "Never write process or methodology content",
    "file intake first and treat the situation as blocked-on-missing-control",
)
REVIEW_EVIDENCE_MARKERS = (
    "`plan-finalization-precheck` and the `Cross-Model Review Evidence` section exist only for T2/T3 plans",
    "bind it with `finalize-plan-review`",
    "Do not rerun Codex just to bind manifest evidence",
    "Plan-review convergence is a ladder",
    "rounds 3-4 self-authorize with a recorded `--exception-note`, never an operator escalation",
    "past round 4 refusal is unconditional; the split is mandatory unless the bound "
    "evidence is clean and current",
    "hand-edit `.plan-reviews`, disable hooks, skip required `ExitPlanMode` checks, or ask for a bypass",
    "Plan-review evidence is content-hash-bound and verdict-bound when it exists",
    "For T2/T3 plan review, run one authoring-model native/self-check before R1",
    "do not spawn plans to rebind a hash",
    "Implementation review is risk-tiered",
    "T1+ keeps one cross-model review round",
    "The `review-before-push` skill owns the detailed command sequence",
    "Evidence is scoped to the assembled outgoing diff",
    "tracked `<planningArtifacts.sourceOfTruth>/.impl-reviews/` ledger",
    "Review budgets come from adapter `review.roundBudgets`",
    "Cross-Model Review Evidence",
    "never retire, rewrite, or rebind existing review runs or manifests",
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
    "Plan-review convergence is a ladder",
    "rounds 1-2 are the target",
    "rounds 3-4 self-authorize with a recorded `--exception-note`, never an operator escalation",
    "past round 4 refusal is unconditional; the split is mandatory unless the bound "
    "evidence is clean and current",
    "transfer into the implementation review focus list",
    "do not spawn plans to rebind a hash",
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

    # Cap raised 321 -> 400 to authorize the PM-surface pre-push review/CI exemption (one bullet
    # enumerating every fail-closed branch) without dropping existing review-before-push guidance.
    # Raised 400 -> 475 (2026-07-31, item 48, 0.36.0) for the implementation-review round ladder:
    # target / hard cap at target+2 / self-authorizing in between / confirming rounds free, and the
    # statement that no round decision on this surface is ever an operator escalation. Measured
    # delta only (+75 words, module at 472). This module was at 397 of 400 -- three words of
    # headroom -- so the addition could not be absorbed. The DETAIL deliberately lives in
    # plugins/tautline-core/skills/review-before-push/references/, which this policy already names
    # as the owner of the command sequence; what stays here is the rule, not the procedure.
    # Raised 475 -> 507 (+32 words, the measured delta) for item 69 PR-B's review-entry
    # adapter-dirt refusal (0.44.0): a recorded round whose ONLY dirty files are the generated adapters would
    # review a tool-injected re-render instead of the work. It is one bullet because the whole rule
    # is one sentence plus its two continuations; the detail lives in the guard's own tests.
    # Raised 507 -> 575 (+68 words, this lane's own measured delta, re-measured at the 0.51.0 tip
    # and carried from no predecessor) for item 73's AC-keyed routing rule. The module was at 507
    # of 507 -- zero headroom -- so the bullet could not be absorbed. It is worth the words because
    # the rule it replaces made routing severity-scoped while the Done gate is AC-scoped, which
    # left an out-of-AC Critical neither blocking nor routable; the measured cost was two review
    # rounds, one reverted module built in flight, and two severity downgrades performed solely to
    # make routing legal. The field-level procedure stays out: it lives in the classified-findings
    # contract doc and in the review-before-push reference, which this module already names.
    # Raised 575 -> 644 (+69 words, this PR's own measured delta at the f9cbb69c tip) for
    # item 75 WS1's two bullets. The module was at 575 of 575 -- zero headroom -- so they
    # could not be absorbed.
    # Raised 644 -> 708 (+64 words, this PR's own measured delta at the e09ff7fa tip) for
    # item 75 WS2's execution-counting bullet.
    assert len(words) <= 708


AC_ROUTING_MARKERS = (
    "not open against the item's acceptance criteria",
    "honest severity",
    "`ac_ref: null`",
    "`routed_to` row",
    "never routed, never downgraded to make routing legal",
    "means unresolved **against the acceptance criteria**",
)

# The three severity-only routing phrases item 73 removes. Each was verified PRESENT before the
# change (canonical-rules + policy 17, skill reference :59, and skill reference :103). Deliberately
# NOT gating on "P2/P3/Nit findings only": that sentence lives only in the downstream product
# REVIEW_PROTOCOL.md, never in this repo, so asserting its absence here would be trivially green
# and would prove nothing.
SEVERITY_ONLY_ROUTING_PHRASES = (
    "route non-blocking findings to the backlog",
    "Route P2/P3/Nit findings to the configured backlog adapter",
    "routing P2/P3/Nit to the backlog",
)


def test_canonical_rules_key_routing_to_ac_traceability():
    """The regenerated canonical rules carry the AC-keyed rule, not just the policy module.

    Regeneration is where this can silently revert: an edit to the module that is never
    regenerated leaves the canonical text saying the old thing.
    """
    text = CANONICAL.read_text(encoding="utf-8")
    missing = [marker for marker in AC_ROUTING_MARKERS if marker not in text]

    assert missing == []


def test_severity_only_routing_phrases_are_gone():
    roots = [ROOT / "methodology", ROOT / "plugins"]
    offenders = []
    for root in roots:
        for path in root.rglob("*.md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for phrase in SEVERITY_ONLY_ROUTING_PHRASES:
                if phrase in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {phrase}")

    assert offenders == []


def test_the_removed_phrases_check_is_not_vacuous():
    """A phrase list that no longer matches anything anywhere would pass the test above forever.

    Each phrase must still be a plausible thing to write, so pin that the SHAPE it replaces --
    severity-list routing without an acceptance-criteria qualifier -- is what the wording is
    steering away from, and that the replacement wording is actually present.
    """
    reference = REVIEW_BEFORE_PUSH_REFERENCE.read_text(encoding="utf-8")
    assert "honest severity" in reference
    assert "open against an acceptance criterion" in reference
    assert "presumptively out-of-AC" in reference


def test_rejected_tool_call_policy_module_stays_concise():
    words = REJECTED_TOOL_CALL_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 206


def test_verified_human_instructions_policy_module_stays_concise():
    words = VERIFIED_HUMAN_INSTRUCTIONS_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 205 -> 267 (+62 words, this lane's own measured delta) for item 71 WS3's
    # both-directions ground-truth rule. Exact RCA wording; not trimmable to fit.
    assert len(words) <= 267


def test_methodology_governance_policy_module_stays_concise():
    words = GOVERNANCE_POLICY_MODULE.read_text(encoding="utf-8").split()

    # 270 -> 340 (2026-07-23): the agent owns review AND merge -- deliver MERGED, never hand a
    # clean gate-green PR back for operator review/merge (Done = merged, not Done = pushed).
    assert len(words) <= 444


def test_goal_orchestration_policy_module_stays_concise():
    words = GOAL_ORCHESTRATION_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 390 -> 509 (+119 words over the previous cap; the module went 347 -> 509, this
    # lane's own measured delta on the 112b4705 tip) for batch 2026-08-11 item B7's two
    # statements. Raised once naming both, on the 10b-board-currency precedent.
    #
    #   1. The definition of done. Most of its length is irreducible: it must NAME the seven
    #      condition ids, because a lane cannot look up a set the rules do not list, and it must
    #      state the handoff bar in BOTH directions -- an unarmed open PR is not done, AND a
    #      queued auto-merging one IS -- or the rule reads as a licence to sit on a merge
    #      monitor, which is the worse of the two wastes available here.
    #   2. The goal-delivery rule: a goal handed to a human is the sole content of the response.
    #
    # Both are rules a lane cannot infer from a refusal string, which is this file's standing
    # test for whether policy words are worth their budget: the first names its legal exits, and
    # the second describes a response SHAPE that no gate can enforce after the fact.
    # Raised 509 -> 523 (+14 words, measured) to qualify the refusal sentence with the
    # enforcement mode it actually depends on. The shipped default is `warn`; a canonical rule
    # stating a flat "refuses" would be the authority document describing behavior the code
    # does not have by default, which is exactly the mismatch review caught on the schema.
    assert len(words) <= 523


def test_board_currency_policy_module_stays_concise():
    words = BOARD_CURRENCY_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 355 -> 430 (+75 words, this lane's own measured delta at the 40b1b39a tip) for item
    # 81's oracle-discipline clause. The module was at its cap exactly, so the clause could not be
    # absorbed. It is worth the words because the gate it describes now REFUSES a done move under
    # `strict`, and the three things it states -- AC-measured evidence, FAILED AC is never a
    # deferral, and no self-verification -- are each a distinct rule a lane cannot infer from a
    # refusal string.
    #
    # Raised 430 -> 748 (+318 words, measured on this branch's tip) for item 101's PR-reference
    # contract, the stakeholder request of 2026-08-12. The module was at its cap exactly again,
    # so none of it could be absorbed.
    #
    # Three statements, and the word count is where it is because each carries the thing that
    # makes it actionable rather than merely true:
    #
    #   1. The four rules must distinguish a PR that COMPLETES an item from one that only
    #      ADVANCES it, and give the title-only form for the advancing case. "Reference the item
    #      precisely" without both shapes is a rule every lane resolves differently, and one of
    #      those resolutions auto-closes live unfinished work on a stakeholder board.
    #   2. The auto-close statement must name the DEFAULT-BRANCH condition. GitHub honours a PR
    #      body keyword only when the PR's base is the default branch, so on an
    #      integration-branch repo -- which is what this framework and its adopters run -- the
    #      unconditional promise is false. A rule that promises a mechanism which silently does
    #      not fire is worse than no rule, because the lane stops checking.
    #   3. The enforcement-gap statement exists because the gate contradicts rule 3 TODAY: an
    #      adopter can be refused for obeying the published rule. Naming the gap AND its
    #      forbidden workaround is what stops the rule teaching lanes to satisfy the gate with a
    #      reference to an issue the PR does not implement -- which is what this repo's own lanes
    #      had been doing, and is the harm rule 4 names.
    #
    # Operational detail deliberately did NOT come here. The GitHub-honoured reference forms, the
    # one-keyword-per-issue rewrite, the advancing-vs-completing decision procedure and the
    # commit-message consequence all live in the `board-item-updates` skill reference, which
    # costs neither canonical ratchet nor rendered-adapter corridor.
    #
    # 748 -> 790 (+42) at implementation review R1: the rule said "the item's ISSUE number in
    # the same repo" and then gave a bare `Fixes #758` for the closing keyword, which is wrong
    # whenever a provider-backed Project item is an issue in ANOTHER repository -- GitHub
    # resolves a bare ref against the PR's own repo, so the contract as written could close an
    # unrelated issue there. The qualified `owner/repo#N` form is required for that case.
    assert len(words) <= 790


def test_lane_coordination_policy_module_stays_concise():
    words = LANE_COORDINATION_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Ceiling raised (0.8.9 T6) to cover the T2 foreign-file re-scope qualifier:
    # only the current lane's own status file (plus the shared contract/board)
    # blocks; other lanes' stale/untracked/dirty status is informational only.
    assert len(words) <= 250


def test_backlog_provider_policy_module_stays_concise():
    words = BACKLOG_PROVIDER_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 345 -> 396 (+51 words, this lane's own measured delta) for item 71 WS2's
    # adapter-declared board-identity rule. Exact RCA wording; not trimmable to fit.
    assert len(words) <= 396


def test_merge_and_ci_policy_module_stays_concise():
    words = MERGE_AND_CI_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 357


def test_tdd_and_behavior_specs_policy_module_stays_concise():
    words = TDD_AND_BEHAVIOR_SPECS_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 210 -> 228 for the machine-checkable-proof sentence appended to the "Green tests must
    # mean working software" bullet (item 37, test-execution proof, Release 1 / W4): that rule was
    # already correct and already loaded, and bound nothing because no control could observe
    # compliance. The sentence names `tautline-test-run/v1` as its checkable form and says
    # enforcement is versioned separately. Per the shared-surface discipline, this lane raises the
    # cap by its own measured delta only.
    # Raised 228 -> 234 (+6 words, this lane's own measured delta) for item 72 Release A: the
    # inactive-scenario bullet now shows the machine-checkable form rather than only naming the
    # three things it requires. Same shape as the raise above -- a rule that was already correct
    # and already loaded, given the checkable form that lets a control observe compliance.
    # Raised 234 -> 262 (+28 words, this lane's own measured delta, re-measured at MY tip on
    # 2026-08-10) for item 72 Release B: `behavior-spec-status --base`. Deliberately the shortest
    # form that carries what a lane cannot infer from the flag name -- that it REPORTS and never
    # changes an exit code, and that `behavior-spec-delta-check` is the enforcing counterpart. A
    # reporting line mistaken for a gate is how a real gate ends up treated as already covered.
    # The full explanation lives in the behavior-specs skill reference, not here.
    assert len(words) <= 262


def test_planning_policy_module_stays_concise():
    words = PLANNING_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 385 -> 435 for the 50-word successor-plan sentence appended to the cap bullet
    # (2026-07-14 process-authority plan, Task 9); per the rough-edges umbrella, only that
    # lane raises the module-13 cap. Raised 435 -> 496 for the plan-authoring standard bullet
    # (2026-07-23 plan-authoring-standard plan, WS4): parallel-workstream shape, per-task
    # model-tier tags, embedded execution-autonomy contract, and the enforcement knob.
    # Raised 496 -> 535 (Codex R1 P1): scope the mechanical guard honestly to the plan-review
    # seam and note T1 packet-only work is authoring-guidance-only, not falsely "T1+ enforced".
    # Raised 535 -> 554 (2026-07-25, item 24 plan-review round advance gap): one sentence stating
    # that the round-4 cap counts successful reviewer invocations per source plan rather than
    # `--round` labels. The gate now enforces exactly that, and a lane that reads only the policy
    # would otherwise believe relabelling still buys rounds.
    assert len(words) <= 554


def test_demo_and_staging_policy_module_stays_concise():
    words = DEMO_AND_STAGING_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 210


def test_lane_lifecycle_policy_module_stays_concise():
    words = LANE_LIFECYCLE_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Ceiling raised (0.8.9 T6) for the startup-remediation-mode contract bullet: debt-class
    # startup failures start a remediation session instead of refusing to start; break-glass
    # stays operator-only; integrity failures never start a session.
    # Raised 450 -> 460 for the PM-surface VERSION-bump-exemption sentence (a PM-surfaces-only diff
    # is not a framework change and needs no bump).
    # Raised 460 -> 541 (+81 words, the measured delta) for item 69's generated-adapter template
    # stamp (0.43.0). Four things a lane meets at STARTUP and cannot infer: which surface renders
    # implicitly (lane-start/init, not the hooks), that a newer on-disk template no-ops here but
    # refuses on the explicit verb, that a stamp-only difference is neither drift nor a rewrite,
    # and that detection is version-only -- without that last clause an agent hitting a
    # same-version content difference concludes no downgrade happened, which is the misreading the
    # incident itself began with.
    assert len(words) <= 541


def test_autonomy_and_status_policy_module_stays_concise():
    words = AUTONOMY_AND_STATUS_POLICY_MODULE.read_text(encoding="utf-8").split()

    assert len(words) <= 377


def test_delivery_summaries_policy_module_stays_concise():
    words = DELIVERY_SUMMARIES_POLICY_MODULE.read_text(encoding="utf-8").split()

    # Raised 330 -> 400 for the key-with-title reference rule (item 26: bare item
    # keys like `FR-3` must be followed by their short title in human-facing output).
    # Raised 400 -> 490 (2026-07-26, item 33 plain-language operator boundaries,
    # operator-raised): two obligations that could not be folded into the existing
    # first bullet, because that one is scoped to messages reporting SHIPPED work.
    # The new ones cover every human-facing boundary, and cover ASKING a human for
    # something -- the case with no rule at all until now.
    #
    # Raised 490 -> 549 (+59 words, measured) for item 101: for provider-backed repos the merge
    # with its closing reference IS the completion claim, replacing a hand-close. The sentence
    # costs what it does because it has to carry TENSE, not just the rule: a queued summary is
    # sent before the merge, and a merge to a non-default base does not close anything either, so
    # an unqualified "cites the auto-closed issue" would have this module licensing a completion
    # claim for a closure that has not happened -- against the module's own proof-of-done rule.
    assert len(words) <= 549


def test_canonical_rules_require_key_with_title_reference():
    """Item 26: a bare backlog/requirement key is not self-explanatory to a human, so
    the canonical rules must require expanding it with the item's short title.

    Pinned in BOTH the source module and the generated artifact so a future edit or
    a stale regeneration cannot silently drop the rule.
    """
    marker = "immediately follow it with the item's short title"
    source = DELIVERY_SUMMARIES_POLICY_MODULE.read_text(encoding="utf-8")
    generated = CANONICAL.read_text(encoding="utf-8")
    assert marker in source, "key-with-title rule missing from the source policy module"
    assert marker in generated, (
        "canonical-rules.md is stale; regenerate with `canonical-policy --write`"
    )
    assert "`KEY: <short title>`" in generated


def test_canonical_rules_require_plain_language_at_human_boundaries():
    """Item 33 (plain-language operator boundaries), operator-raised 2026-07-26.

    The existing first bullet already asked for a plain-language OUTCOME, but only for
    messages reporting shipped work -- so a status answer, a handoff, or a blocker could
    be, and was, delivered as a wall of severity codes and verb names. And nothing at all
    governed ASKING a human for something. Both are pinned in the source module and the
    generated artifact so an edit or a stale regeneration cannot quietly drop them.
    """
    source = DELIVERY_SUMMARIES_POLICY_MODULE.read_text(encoding="utf-8")
    generated = CANONICAL.read_text(encoding="utf-8")
    for marker in (
        "Every human-facing boundary",
        "they never replace it",
        "state plainly what you need, why, and the cost of not having it",
    ):
        assert marker in source, f"plain-language rule missing from the source module: {marker}"
        assert marker in generated, (
            f"canonical-rules.md is stale for: {marker}; "
            "regenerate with `canonical-policy --write`"
        )


def test_current_status_truth_policy_module_stays_concise():
    words = (ROOT / "methodology" / "policy" / "05-current-status-truth.md").read_text(encoding="utf-8").split()

    # Raised 225 -> 240 for the product-dev-mode latest-code standdown exception
    # bullet (deliberate ratchet).
    assert len(words) <= 240


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
