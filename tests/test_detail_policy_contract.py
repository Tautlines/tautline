from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_SKILLS = ROOT / "plugins" / "tautline-core" / "skills"
OPS_SKILLS = ROOT / "plugins" / "tautline-ops" / "skills"

DETAIL_POLICY_SOURCES = [
    ROOT / "methodology" / "canonical-rules.md",
    CORE_SKILLS / "risk-tier-autonomy" / "references" / "risk-tier-policy.md",
    CORE_SKILLS / "context-continuity" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "references"
    / "context-continuity-policy.md",
    CORE_SKILLS / "delivery-summary" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "delivery-summary"
    / "references"
    / "delivery-summary-policy.md",
    CORE_SKILLS / "background-task-monitoring" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "background-task-monitoring"
    / "references"
    / "background-monitoring-policy.md",
    CORE_SKILLS / "merge-queue-monitoring" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "merge-queue-monitoring"
    / "references"
    / "merge-queue-policy.md",
    CORE_SKILLS / "execution-packet-work-loop" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "execution-packet-work-loop"
    / "references"
    / "execution-packet-policy.md",
    CORE_SKILLS / "human-instructions" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "human-instructions"
    / "references"
    / "human-instructions-policy.md",
    CORE_SKILLS / "review-before-push" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "review-before-push"
    / "references"
    / "review-before-push-policy.md",
    CORE_SKILLS / "framework-intake" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "framework-intake"
    / "references"
    / "framework-intake-policy.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "context-continuity"
    / "references"
    / "context-continuity-policy.md",
    OPS_SKILLS / "usage-accounting" / "SKILL.md",
    OPS_SKILLS / "usage-accounting" / "references" / "usage-accounting-policy.md",
    CORE_SKILLS / "stakeholder-questions" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "stakeholder-questions"
    / "references"
    / "stakeholder-questions-policy.md",
    CORE_SKILLS / "graphify-navigation" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "graphify-navigation"
    / "references"
    / "graphify-navigation-policy.md",
    OPS_SKILLS / "session-journal" / "SKILL.md",
    OPS_SKILLS / "session-journal" / "references" / "session-journal-policy.md",
    CORE_SKILLS / "goal-orchestration" / "SKILL.md",
    ROOT / "docs" / "reference" / "operations" / "delivery-communications.md",
    OPS_SKILLS / "iteration-review" / "references" / "iteration-review-policy.md",
    OPS_SKILLS / "milestone-update" / "references" / "milestone-update-policy.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "goal-orchestration"
    / "references"
    / "goal-orchestration-policy.md",
    CORE_SKILLS / "behavior-specs" / "SKILL.md",
    CORE_SKILLS / "rules-audit" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "lane-lifecycle"
    / "references"
    / "lane-lifecycle-policy.md",
]


DETAIL_POLICY_MARKERS = """
A commit, push, PR, green gate, review round, delivery summary, or completed subtask is not a stopping point
A rejected commit, push, merge, or other tool call is not a global stop signal
Do not present required methodology, adapter guidance, handoff instructions, execution-packet steps, source-of-truth plan review gates
Do not present a multiple-choice menu when the methodology, review findings, backlog priority, execution packet, or a stated recommendation identifies a safe next action
Even when every available path would change approved scope, risk, cost, security posture, production behavior, or standing approval, escalation must be one exact blocker question
When naming alternatives to explain a blocker, do not ask the human operator to pick among them
Decision-menu theater: presenting option numbers, path labels, or "pick one" choices
Recovery-cancel-on-frustration theater: canceling a provider recovery loop, scheduled retry, wakeup, or autonomous goal loop because the human operator expressed frustration
A Critical/C1/P1 review finding is a repair work item, not a stopping point
Codex review output must be retrieved
Do not infer "no findings" from a failed grep
A clean Codex review claim must cite the inspected review artifact
Do not present review-blocker options as a menu when a safe recommended path exists
Handoff theater: using a session summary, continuity handoff, or `NEXT_SESSION.md` write to defer an authorized next action
Context rotation is routine maintenance for autonomous goal work
CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85
At every PR queued/completed boundary, milestone completion, goal boundary, workflow summary, session summary, handoff-for-review, or long `/goal` heartbeat, check visible context pressure
next_goal_name
Milestone updates are internal, professional, text-only Google Chat cards
minervit-methodology publish-milestone-update --target . --milestone <milestone-id-or-title> --stdin
minervit-methodology publish-deploy-ready-update
deployment-notification-status --strict
minervit-methodology deploy-health --target .
minervit-methodology publish-product-note --target . --title "Short title" --stdin
A transient external dependency is not a terminal handoff
Anthropic/Claude/Codex/GitHub/API overloads
Memory-sourced process: treating Open Brain, Claude memories, local memories, or feedback-memory files as the authority
Never use memory as process authority
Do not cite Open Brain, Claude memories, local memories, or feedback-memory files as `the rule`
Handoff omission: ending a workflow, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet without refreshing the configured continuity handoff
Planning opt-out: treating the absence of planned work on deck as a reason to ask whether to plan
Writing a continuity handoff is not permission to stop
Writing a handoff is not permission to stop
Every workflow completion, delivery summary, session summary, milestone summary, queued-delivery summary, handoff-for-review, or completed execution packet must refresh the configured continuity handoff as final housekeeping
Handoff-for-review means any end-of-workflow summary meant to let the human operator review, drop, restart, or continue in a new session
Handoff refresh is workflow-end housekeeping, not a mid-iteration interruption or a stop signal
If no goal ledger next action, execution packet, handoff next action, or implementation-ready tactical PR plan is on deck after startup gates
No implementation-ready plan on deck is not a stop condition
Planning is automatic and routine
Goal -> Milestone -> PR
goal-next --target .
goal-condition --target .
Boundary summaries for delivery, PR, milestone, goal, session, and handoff-for-review events must lead with the plain-language outcome and next action
Use headings or labels only when they improve readability
context exhaustion alone is not goal completion
Context exhaustion means a system/tool compaction event, explicit low-context warning, user compaction request
Context exhaustion must match the signals in item 7
Context exhaustion must match the continuity skill's context-running-out signals
Do not turn a session summary, milestone summary, or continuity handoff into a stop menu
Do not ask the human operator to say `keep going`, `continue`, `stop here`, or `pick up next session`
Continuity is implied by wording such as compact, context, continuity, handoff, new session, pick up later
Do not emit a copy-paste continuity prompt as the primary response
Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts as approval
Do not ask whether to begin planning or pause
A stop is valid only when the lane has no active work, the goal/milestone ledger is terminal, the human operator explicitly asked to stop, a fresh true blocker is declared, or context rotation has written continuity and the exact fresh-session startup action
Starting or arming a monitor is not a stopping point
Platform or CI notifications do not replace active supervision
monitor-status --target . --log <log> --pid <pid-if-known> --strict
Strict monitor checks require verified PID/process identity
A live PID with no log/check progress past the stale threshold is stale/hung
Tool-level timeouts on a detached/background shell call are not enough
background-run --timeout-seconds <seconds>
Status updates are for the human operator, not for the agent
Lead with the plain-language outcome or current state
at least every 5 minutes of wall-clock time during foreground
Event logs, session journals, and continuity files do not substitute
verify the current process from authoritative sources in the same turn before giving steps
start the completion summary with an executive summary before technical detail
A queued-delivery summary is incomplete unless it ends with one of two concrete outcomes
Early-warning smoke is an ambient confidence signal, not the final branch gate
Control Markdown context loading by reading configured indexes first
Do not broad-load Markdown trees, scan all plans, or read every doc for routine context
upper bound of 20 Markdown files
Historical evidence only. Not current process, scope, or execution authority. Start from <index path>.
When creating, completing, moving, or archiving Markdown work artifacts, update the relevant context index before workflow completion
Session journals are evidence only
prepare-session-journal --target . --stdin
Local-only as of 0.9.0
refuse in every mode
publish-instrumentation-record
Do not fetch/read any remote archive branch during normal startup
Treat validation as detection, not proof that no secret exists
ignored lane-local state and may be lost
Milestone continuation state lives in the lane-local milestone run ledger
PR boundaries are ledger transitions, not stop points
At PR boundaries, `milestone-next` is the controller
queued-delivery or PR-completion summary is incomplete until the milestone ledger is advanced
The milestone ledger wins over a vague handoff summary at PR boundaries
proof-of-done standard
`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof
watchdog only surfaces stale runs; it is not process authority
""".strip().splitlines()


def test_detail_policy_sources_keep_required_markers():
    detail_policy = "\n".join(path.read_text(encoding="utf-8") for path in DETAIL_POLICY_SOURCES)
    normalized = " ".join(detail_policy.split())

    missing = [
        marker
        for marker in DETAIL_POLICY_MARKERS
        if marker not in detail_policy and marker not in normalized
    ]

    assert missing == []
