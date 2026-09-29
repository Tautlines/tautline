import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EXPORT_MARKER = ROOT / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; its subject files are export-excluded",
)
METHODOLOGY_BACKLOG = ROOT / "docs" / "backlog" / "methodology-backlog.md"
PLUGIN_CHANGELOG = ROOT / "plugins" / "tautline-core" / "CHANGELOG.md"
PLUGIN_RELEASE_NOTES = ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md"
CORE_SKILLS = ROOT / "plugins" / "tautline-core" / "skills"
OPS_SKILLS = ROOT / "plugins" / "tautline-ops" / "skills"


def _assert_contains_all(path: Path, phrases: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [phrase for phrase in phrases if phrase not in text]
    assert missing == [], f"{path.relative_to(ROOT)} missing: {missing}"


def test_repository_templates_schema_and_governance_contracts():
    pull_request_template = ROOT / ".github" / "pull_request_template.md"
    validate_workflow = ROOT / ".github" / "workflows" / "validate.yml"

    assert pull_request_template.exists()
    assert validate_workflow.exists()
    _assert_contains_all(validate_workflow, ["scripts/validate.sh"])
    _assert_contains_all(ROOT / "methodology" / "adapter-schema.json", ["deploymentTargets", "reviewExemptions"])
    _assert_contains_all(
        ROOT / "docs" / "governance" / "methodology-change-governance.md",
        ["Methodology Repository Governance", "Session Journal Evidence"],
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
