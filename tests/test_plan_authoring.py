import copy
import re

from tautline_methodology import plan_authoring as pa


def test_plan_missing_goal_prompt_issue_none_reported_when_shipped(tmp_path):
    plan_path = tmp_path / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    (tmp_path / "goal-ws1-example.txt").write_text(
        "/goal do the thing from the finalized plan `plan-example.md`\n", encoding="utf-8"
    )
    assert pa.plan_missing_goal_prompt_issue(plan_path) is None


def test_plan_missing_goal_prompt_issue_reported_when_absent(tmp_path):
    plan_path = tmp_path / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a goal\n", encoding="utf-8")
    issue = pa.plan_missing_goal_prompt_issue(plan_path)
    assert issue is not None
    assert "no goal prompt artifact" in issue
    assert "goal-assignment" in issue


def test_plan_missing_goal_prompt_issue_only_looks_beside_the_plan(tmp_path):
    plan_dir = tmp_path / "plan-dir"
    plan_dir.mkdir()
    plan_path = plan_dir / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    # A goal file in the PARENT of the plan's directory must not satisfy the check.
    (tmp_path / "goal-elsewhere.txt").write_text(
        "/goal elsewhere for plan-example.md\n", encoding="utf-8"
    )
    assert pa.plan_missing_goal_prompt_issue(plan_path) is not None


def test_plan_missing_goal_prompt_issue_rejects_a_sibling_plans_goal(tmp_path):
    """Codex R1 P1: a flat plans directory (this repo's own docs/superpowers/plans/ shape) must
    not let plan B's goal satisfy plan A merely because a goal*.txt file exists nearby."""
    plan_a = tmp_path / "plan-a.md"
    plan_a.write_text("# Plan A\n", encoding="utf-8")
    plan_b = tmp_path / "plan-b.md"
    plan_b.write_text("# Plan B\n", encoding="utf-8")
    (tmp_path / "goal-b.txt").write_text(
        "/goal from the finalized plan `plan-b.md`\n", encoding="utf-8"
    )
    issue = pa.plan_missing_goal_prompt_issue(plan_a)
    assert issue is not None
    assert "does not appear in its text" in issue
    # Plan B's own check still passes.
    assert pa.plan_missing_goal_prompt_issue(plan_b) is None


def test_plan_missing_goal_prompt_issue_accepts_the_documented_fallback_path(tmp_path):
    """Codex R1 P2: the goal-assignment skill's own Fast Path writes --out .ai-work/goal.txt,
    a target-relative path, not one beside the plan; that sanctioned workflow must satisfy."""
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    assert pa.plan_missing_goal_prompt_issue(plan_path, target=tmp_path) is not None
    ai_work = tmp_path / ".ai-work"
    ai_work.mkdir()
    (ai_work / "goal.txt").write_text(
        "/goal from the finalized plan `plan-example.md`\n", encoding="utf-8"
    )
    assert pa.plan_missing_goal_prompt_issue(plan_path, target=tmp_path) is None


def test_fallback_path_goal_does_not_satisfy_a_different_plan_with_the_same_basename(tmp_path):
    """Codex R1 (second confirming round) P1: `.ai-work/goal.txt` is a SINGLE target-wide file
    shared by every plan in the lane, unlike the beside-the-plan glob (directory-scoped, so a
    same-basename collision there is impossible). Two DIFFERENT plans in DIFFERENT directories
    that happen to share a basename (e.g. `ready/item-a/plan.md` and `ready/item-b/plan.md`)
    must not collide on the fallback file just because their bare filenames match."""
    (tmp_path / "ready" / "item-a").mkdir(parents=True)
    (tmp_path / "ready" / "item-b").mkdir(parents=True)
    plan_a = tmp_path / "ready" / "item-a" / "plan.md"
    plan_a.write_text("# Plan A\n", encoding="utf-8")
    plan_b = tmp_path / "ready" / "item-b" / "plan.md"
    plan_b.write_text("# Plan B\n", encoding="utf-8")
    ai_work = tmp_path / ".ai-work"
    ai_work.mkdir()
    (ai_work / "goal.txt").write_text(
        "/goal from the finalized plan `ready/item-a/plan.md`\n", encoding="utf-8"
    )
    # Plan A's own fallback goal satisfies it when the caller supplies the fuller plan_ref.
    assert (
        pa.plan_missing_goal_prompt_issue(
            plan_a, target=tmp_path, plan_ref="ready/item-a/plan.md"
        )
        is None
    )
    # Plan B must NOT be satisfied by plan A's fallback goal merely because both are named
    # "plan.md" -- this is the exact collision the bare-basename check missed.
    issue = pa.plan_missing_goal_prompt_issue(
        plan_b, target=tmp_path, plan_ref="ready/item-b/plan.md"
    )
    assert issue is not None


def test_fallback_ref_match_does_not_accept_an_archived_path_suffix(tmp_path):
    """Codex R1 (third confirming round) P1: the original delimiter set treated `/` as a valid
    boundary, so checking `docs/plans/plan.md` falsely matched inside a goal that actually names
    `archive/docs/plans/plan.md` -- a real, different plan whose reference happens to END with
    the same segments. `/` must not count as a delimiter for a full (multi-segment) plan_ref."""
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "plan.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    ai_work = tmp_path / ".ai-work"
    ai_work.mkdir()
    (ai_work / "goal.txt").write_text(
        "/goal from the finalized plan `archive/docs/plans/plan.md`\n", encoding="utf-8"
    )
    issue = pa.plan_missing_goal_prompt_issue(
        plan_path, target=tmp_path, plan_ref="docs/plans/plan.md"
    )
    assert issue is not None
    # A goal that properly delimits the SAME ref (not merely ending with it) still satisfies.
    (ai_work / "goal.txt").write_text(
        "/goal from the finalized plan `docs/plans/plan.md`\n", encoding="utf-8"
    )
    assert (
        pa.plan_missing_goal_prompt_issue(plan_path, target=tmp_path, plan_ref="docs/plans/plan.md")
        is None
    )


def test_plan_missing_goal_prompt_issue_remedy_uses_plan_ref_not_bare_name(tmp_path):
    """Codex R1 P2: for a nested plan the remedy command must name a resolvable reference, not
    the bare filename (which goal-assignment resolves relative to the target root and misses)."""
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    issue = pa.plan_missing_goal_prompt_issue(plan_path, plan_ref="docs/plans/plan-example.md")
    assert issue is not None
    assert "--plan docs/plans/plan-example.md" in issue
    assert "--plan plan-example.md" not in issue


def test_plan_missing_goal_prompt_issue_does_not_match_an_overlapping_basename(tmp_path):
    """Codex R1 (confirming round) P2: raw substring containment let a goal for `long-plan.md`
    also satisfy `plan.md`, since "plan.md" is literally a substring of "long-plan.md". Two
    plans with overlapping basenames in the same (or a configured) root must not collide."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    (tmp_path / "goal-for-long-plan.txt").write_text(
        "/goal from the finalized plan `long-plan.md`\n", encoding="utf-8"
    )
    issue = pa.plan_missing_goal_prompt_issue(plan_path)
    assert issue is not None
    # A goal that properly delimits the SAME basename (e.g. quoted, or as a full path) still
    # satisfies it -- this is a precision fix, not a stricter format requirement.
    (tmp_path / "goal-for-long-plan.txt").write_text(
        "/goal from the finalized plan `plan.md`\n", encoding="utf-8"
    )
    assert pa.plan_missing_goal_prompt_issue(plan_path) is None


def test_mentioning_the_plan_outside_the_source_plan_clause_does_not_bind(tmp_path):
    """Codex R1 (this round) P2: a sibling's goal may legitimately MENTION this plan's path
    somewhere other than its own source-plan clause (e.g. a milestone note telling the builder
    to also touch it). Only the "from the finalized plan `<ref>`" clause -- the one thing
    `compose_goal_assignment` actually writes to bind a goal to ITS plan -- may satisfy the
    check; an incidental mention elsewhere must not."""
    plan_a = tmp_path / "plan-a.md"
    plan_a.write_text("# Plan A\n", encoding="utf-8")
    plan_b = tmp_path / "plan-b.md"
    plan_b.write_text("# Plan B\n", encoding="utf-8")
    (tmp_path / "goal-b.txt").write_text(
        "/goal from the finalized plan `plan-b.md`. Also update `plan-a.md` per the milestone.\n",
        encoding="utf-8",
    )
    issue = pa.plan_missing_goal_prompt_issue(plan_a)
    assert issue is not None
    assert pa.plan_missing_goal_prompt_issue(plan_b) is None


def test_a_filename_containing_punctuation_does_not_falsely_collide(tmp_path):
    """Codex R1 (this round) P2: the old delimiter set only excluded ASCII letters/digits/`_-.`,
    so a goal bound to a DIFFERENT plan whose reference contains a space or other legal filename
    punctuation right before/after the shorter plan's name could falsely satisfy it (e.g. `my
    plan.md` or `archive plans/plan.md` both "contain" `plan.md` at a false boundary). Parsing
    the exact source-plan clause and comparing the FULL captured reference removes the
    approximation entirely."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    (tmp_path / "goal-other.txt").write_text(
        "/goal from the finalized plan `my plan.md`\n", encoding="utf-8"
    )
    assert pa.plan_missing_goal_prompt_issue(plan_path) is not None

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    nested_plan = plan_dir / "plan.md"
    nested_plan.write_text("# Plan\n", encoding="utf-8")
    (plan_dir / "goal-archive.txt").write_text(
        "/goal from the finalized plan `archive plans/plan.md`\n", encoding="utf-8"
    )
    issue = pa.plan_missing_goal_prompt_issue(
        nested_plan, target=tmp_path, plan_ref="plans/plan.md"
    )
    assert issue is not None


def test_plan_missing_goal_prompt_issue_remedy_shell_quotes_the_plan_ref(tmp_path):
    """Codex R1 (confirming round) P3: an unquoted plan reference containing a space breaks the
    printed remedy command into the wrong number of shell arguments when copy-pasted."""
    plan_path = tmp_path / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    issue = pa.plan_missing_goal_prompt_issue(plan_path, plan_ref="docs/plans/My Plan.md")
    assert issue is not None
    assert "--plan 'docs/plans/My Plan.md'" in issue


def test_standing_standard_surfaces_the_goal_prompt_requirement():
    # Codex R1 (this round) P2: this PR ships the matching logic only -- enforcement wiring
    # (and the claim that `plan-finalization-precheck` checks this under the enforcement knob)
    # is a follow-up PR's job, so the standing block documents the requirement without yet
    # claiming it is checked anywhere.
    core = pa.STANDING_PLAN_AUTHORING_STANDARD_CORE
    assert "goal prompt" in core
    assert "goal-assignment" in core

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


def test_the_target_wide_fallback_never_binds_without_a_full_plan_ref(tmp_path):
    """Codex R1 P2 (this lineage): the fallback is ONE file for the whole target, so letting it
    bind through the bare-basename degradation would satisfy every `ready/*/plan.md` at once.
    Without a caller-supplied full reference the fallback simply cannot bind; sibling artifacts
    beside the plan keep the basename path (collision-scoped to their own directory)."""
    plan = tmp_path / "ready" / "item-a" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan A\n", encoding="utf-8")
    work = tmp_path / ".ai-work"
    work.mkdir()
    (work / "goal.txt").write_text(
        "/goal from the finalized plan `ready/item-a/plan.md`\n", encoding="utf-8"
    )
    # Full ref supplied and matching: the fallback binds.
    assert (
        pa.plan_missing_goal_prompt_issue(
            plan, target=tmp_path, plan_ref="ready/item-a/plan.md"
        )
        is None
    )
    # No plan_ref, directory-carrying bound ref: binds only on PATH PROOF -- it resolves to this
    # very plan, so item-a still binds...
    assert pa.plan_missing_goal_prompt_issue(plan, target=tmp_path) is None
    # ...but the SAME fallback text must never satisfy item-b through the basename degradation,
    # which is the reviewer's exact collision example.
    plan_b = tmp_path / "ready" / "item-b" / "plan.md"
    plan_b.parent.mkdir(parents=True)
    plan_b.write_text("# Plan B\n", encoding="utf-8")
    assert pa.plan_missing_goal_prompt_issue(plan_b, target=tmp_path) is not None
