import copy
import re

from tautline_methodology import plan_authoring as pa

COMPLIANT = """
# Feature Plan
## Workstreams
WS1 is a hard predecessor; WS2 and WS3 are parallel-safe (no shared files).
### Task 1  model-tier: deep
Use best judgment; record non-obvious calls with `tautline decision-record`.
"""

LINEAR = """
# Feature Plan
### Task 1
Do the thing. Then the next thing.
"""

# A Workstreams heading whose only "depend"-rooted word is "independently" — which the
# standard itself uses in "independently testable" — must NOT satisfy the dependency marker.
WORKSTREAMS_NO_GRAPH = """
# Feature Plan
## Workstreams
Each task ends with an independently testable deliverable.  model-tier: standard
Use best judgment; record decisions with `tautline decision-record`.
"""


def test_independently_does_not_satisfy_dependency_marker():
    issues = pa.plan_authoring_standard_issues(WORKSTREAMS_NO_GRAPH)
    assert any("Workstreams" in i or "dependency" in i.lower() for i in issues)


# An empty `## Workstreams` heading plus a dependency graph in a SEPARATE section must not
# satisfy the marker (Codex R1c P1: the dependency check is scoped to the Workstreams section).
EMPTY_WS_DEP_ELSEWHERE = """
# Feature Plan
## Workstreams
### Task 1  model-tier: deep
Use best judgment; record with `tautline decision-record`.
## Dependencies
WS2 depends on WS1; parallel-safe with a hard predecessor.
"""


def test_dependency_outside_workstreams_section_does_not_satisfy_marker():
    issues = pa.plan_authoring_standard_issues(EMPTY_WS_DEP_ELSEWHERE)
    assert any("Workstreams" in i or "dependency" in i.lower() for i in issues)


def test_dependency_inside_workstreams_section_passes():
    assert pa.plan_authoring_standard_issues(COMPLIANT) == []


def test_depends_and_dependency_still_match_dependency_marker():
    assert re.search(pa.PLAN_AUTHORING_MARKERS["dependency"], "WS2 depends on WS1")
    assert re.search(pa.PLAN_AUTHORING_MARKERS["dependency"], "an explicit dependency graph")
    assert not re.search(pa.PLAN_AUTHORING_MARKERS["dependency"], "runs independently")


def test_compliant_plan_has_no_issues():
    assert pa.plan_authoring_standard_issues(COMPLIANT) == []


def test_linear_plan_flags_all_three():
    issues = pa.plan_authoring_standard_issues(LINEAR)
    joined = " ".join(issues).lower()
    assert "workstream" in joined
    assert "model-tier" in joined
    assert "autonomy" in joined or "decision-record" in joined


def test_missing_only_model_tier():
    text = COMPLIANT.replace("model-tier: deep", "")
    issues = pa.plan_authoring_standard_issues(text)
    assert any("model-tier" in i.lower() for i in issues)
    assert not any("workstream" in i.lower() for i in issues)


def test_default_enforcement_is_advise():
    assert pa.DEFAULT_PLANNING_AUTHORING_STANDARD["enforcement"] == "advise"


def test_normalize_rejects_bad_enum():
    import pytest
    bad = {"planning": {"authoringStandard": {"enforcement": "nope"}}}
    with pytest.raises(SystemExit):
        pa.normalize_planning_authoring_standard(bad)


def test_normalize_absent_returns_default_advise():
    assert pa.normalize_planning_authoring_standard({})["enforcement"] == "advise"


def test_standard_block_is_str_not_list():
    # Guards the SSOT-exclusion constraint.
    assert isinstance(pa.STANDING_PLAN_AUTHORING_STANDARD_CORE, str)


def test_normal_dependency_phrasing_passes():
    # Regression: `depend` must match as a substring, not just the bare word.
    text = """
# Feature Plan
## Workstreams
WS2 depends on WS1.
### Task 1  model-tier: deep
Use best judgment; record non-obvious calls with `tautline decision-record`.
"""
    assert pa.plan_authoring_standard_issues(text) == []
    # The old \b-anchored regex would have missed these substring matches.
    assert re.search(pa.PLAN_AUTHORING_MARKERS["dependency"], "depends")
    assert re.search(pa.PLAN_AUTHORING_MARKERS["dependency"], "dependency")


def test_normalize_planning_authoring_standard_does_not_mutate_input():
    data = {"planning": {"authoringStandard": {"enforcement": "block"}}}
    before = copy.deepcopy(data)
    pa.normalize_planning_authoring_standard(data)
    assert data == before


def test_plan_authoring_standard_issues_none_and_empty_safe():
    for text in (None, ""):
        issues = pa.plan_authoring_standard_issues(text)
        assert len(issues) == 3
