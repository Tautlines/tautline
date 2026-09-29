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
