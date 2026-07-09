from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STOP_RED_FLAGS_MODULE = ROOT / "methodology" / "policy" / "06a-stop-and-deferral-red-flags.md"
CORE_SKILLS = ROOT / "plugins" / "tautline-core" / "skills"
OPS_SKILLS = ROOT / "plugins" / "tautline-ops" / "skills"

ALLOWED_CONTEXTS = (
    "If the next message would contain",
    "Before sending a message containing",
    "Rewrite any response",
    "Do not end a turn with only",
    "Do not write",
    "red flags",
    "forbidden",
    "Forbidden example:",
    "Forbidden examples include",
    "passive-monitor",
    "Passive monitor stop examples",
    "Checkpoint theater",
    "Decision-menu theater",
    "Handoff theater",
    "stop-menu violation",
    "Do not ask",
    "Do not turn",
    "Do not use",
    "A delivery summary is not a license",
    "A commit, push, PR",
)

RED_FLAG_TERMS = (
    "`monitor is running`",
    "`monitor watches`",
    "`waiting on merge`",
    "`waiting on checks`",
    "`R2 running`",
    "`R3 running`",
    "`review running`",
    "`wakeup in 10 min`",
    "`wakeup in`",
    "`wake up in`",
    '"monitor is running"',
    '"monitor watches"',
    '"waiting on merge"',
    '"waiting on checks"',
    '"R2 running"',
    '"R3 running"',
    '"review running"',
    '"wakeup in 10 min"',
    '"wakeup in"',
    '"wake up in"',
    "Wakeup in 10 min",
    "`waiting for notification`",
    "`will wait for completion`",
    "`I'll wait for it to finish`",
    "`waiting for the background command`",
    "`waiting for shell`",
    "`Shall I`",
    "`shall I`",
    "`Where would you like to go`",
    "`No work-in-flight`",
    "`Pick #1`",
    "`pick #1`",
    "`pick one`",
    '`Say "keep going"`',
    "`stop here`",
    "`pick up next session`",
    "`clean checkpoint`",
    "`significant progress`",
    "`obvious continuation path`",
    "`next turn`",
    "`pausing here`",
    '"waiting for notification"',
    '"will wait for completion"',
    '"I\'ll wait for it to finish"',
    '"waiting for the background command"',
    '"waiting for shell"',
    '"Shall I"',
    '"shall I"',
    '"Where would you like to go"',
    '"No work-in-flight"',
    '"Pick #1"',
    '"pick #1"',
    '"pick one"',
    '"Say \\"keep going\\""',
    '"stop here"',
    '"pick up next session"',
    '"clean checkpoint"',
    '"significant progress"',
    '"obvious continuation path"',
    '"next turn"',
    '"pausing here"',
)

POLICY_SURFACES = (
    ROOT / "methodology" / "canonical-rules.md",
    CORE_SKILLS / "background-task-monitoring" / "SKILL.md",
    CORE_SKILLS / "context-continuity" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "execution-packet-work-loop"
    / "references"
    / "execution-packet-policy.md",
    CORE_SKILLS / "merge-queue-monitoring" / "SKILL.md",
    CORE_SKILLS / "risk-tier-autonomy" / "SKILL.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "risk-tier-autonomy"
    / "references"
    / "risk-tier-policy.md",
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "delivery-summary"
    / "references"
    / "delivery-summary-policy.md",
    OPS_SKILLS / "iteration-review" / "SKILL.md",
)


def test_stop_red_flags_policy_is_state_based_and_concise():
    text = STOP_RED_FLAGS_MODULE.read_text(encoding="utf-8")
    words = text.split()

    assert len(words) <= 350
    assert len(text.splitlines()) <= 15
    example_lines = [line for line in text.splitlines() if line.startswith("- Forbidden example:")]
    assert len(example_lines) <= 5
    assert "blocker-declare" in text
    assert "Phrase matches are advisory evidence" in text
    assert "Do not add new forbidden phrases" in text
    assert "quoting exception" not in text.lower()


def test_policy_surfaces_quote_stop_red_flags_only_in_allowed_contexts():
    violations = []
    for path in POLICY_SURFACES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(term in line for term in RED_FLAG_TERMS) and not any(
                marker in line for marker in ALLOWED_CONTEXTS
            ):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line}")

    assert violations == []
