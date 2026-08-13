import pytest

from tautline_methodology import goal_assignment as ga


PLAN = """
# Ship the widget pipeline

## Workstreams
WS1 is a hard predecessor; WS2 and WS3 are parallel-safe.
- [ ] Build the ingest adapter
- [x] Spike the schema
- Wire the retry queue
  - nested detail that is not its own unit
- Backfill the historical rows

## Notes
- not a workstream
"""


def _compose(**overrides):
    kwargs = {
        "command": "/goal",
        "title": "Ship the widget pipeline",
        "plan_ref": "docs/plans/widget.md",
        "milestones": (),
    }
    kwargs.update(overrides)
    return ga.compose_goal_assignment(**kwargs)


def _core_size(**overrides):
    """The composed length with no milestones -- the floor every budget test must sit above.

    Batch 2026-08-11 B7 widened the irreducible core (the done clause now states the whole
    enabled condition set, and the goal states that the human is AFK), which broke three
    budget tests that had hardcoded limits chosen against the old core. Deriving the range
    from a measurement instead of re-hardcoding it means these tests stop rotting every time
    the core's wording changes -- they test BUDGETING, not a particular sentence length.
    """
    text, _meta = _compose(milestones=(), **overrides)
    return len(text)


def _min_limit(units, **overrides):
    """The smallest limit at which composition still succeeds for `units`.

    Found by asking the composer, not by adding a guessed constant to `_core_size`: the
    irreducible core with milestones also carries the ` Milestones: all N are in the plan.`
    fallback, whose length depends on N.
    """
    low = _core_size(**overrides)
    for limit in range(low, low + 200):
        try:
            _compose(milestones=units, limit=limit, **overrides)
        except ValueError:
            continue
        return limit
    raise AssertionError("composition never succeeded within 200 characters of the bare core")


# -- the reason this module exists: the cap is structural, not advisory --


def test_composed_goal_never_exceeds_the_limit_even_for_an_enormous_plan():
    milestones = [f"Workstream {i}: " + "detail " * 60 for i in range(200)]
    text, meta = _compose(milestones=milestones)
    assert len(text) <= ga.GOAL_ASSIGNMENT_CHAR_LIMIT
    assert meta["char_count"] == len(text)
    assert meta["milestones_total"] == 200
    assert meta["milestones_omitted"] > 0


def test_omitted_milestones_are_reported_not_dropped_silently():
    milestones = [f"Workstream {i}: " + "detail " * 60 for i in range(200)]
    text, meta = _compose(milestones=milestones)
    assert f"(+{meta['milestones_omitted']} more in the plan)" in text
    assert meta["milestones_included"] + meta["milestones_omitted"] == 200


def test_a_small_plan_keeps_every_milestone_and_adds_no_omission_marker():
    text, meta = _compose(milestones=["Build ingest", "Wire retries", "Backfill rows"])
    assert meta["milestones_included"] == 3
    assert meta["milestones_omitted"] == 0
    assert "more in the plan" not in text
    for milestone in ("Build ingest", "Wire retries", "Backfill rows"):
        assert milestone in text


def test_composition_fails_closed_when_the_core_alone_cannot_fit():
    with pytest.raises(ValueError) as excinfo:
        _compose(limit=200, plan_ref="docs/plans/" + "x" * 300 + ".md")
    assert "over the 200-character limit" in str(excinfo.value)


def test_omitted_work_is_named_even_when_no_milestone_fits():
    """Codex T2 R2 P2: when the budget admits the marker but not a full entry, `entries` was
    empty and the whole milestone clause was suppressed — so a goal omitting 7 workstreams
    said nothing about them. The count is part of the irreducible core, not the flexible list."""
    units = ["Workstream %d does a long thing " % i + "x" * 120 for i in range(7)]
    floor = _min_limit(units)
    for limit in range(floor, floor + 70, 5):
        text, meta = _compose(milestones=units, limit=limit)
        assert len(text) <= limit
        if meta["milestones_included"] == 0:
            assert "all 7 are in the plan" in text
        assert meta["milestones_omitted"] == 7 - meta["milestones_included"]


def test_no_budget_ever_hides_that_the_plan_has_milestones():
    units = [f"Workstream {i} " + "y" * 200 for i in range(12)]
    floor = _min_limit(units)
    for limit in range(floor, floor + 1360, 11):
        text, meta = _compose(milestones=units, limit=limit)
        assert len(text) <= limit
        if meta["milestones_omitted"]:
            assert ("more in the plan" in text) or ("are in the plan" in text)


def test_a_plan_with_no_milestones_adds_no_milestone_clause():
    text, meta = _compose(milestones=[])
    assert meta["milestones_total"] == 0
    assert "in the plan" not in text


def test_the_irreducible_core_survives_a_tight_budget():
    """Milestones flex; the plan reference, completion condition and proof never do."""
    tight = _core_size() + 340
    text, meta = _compose(milestones=["a" * 500 for _ in range(50)], limit=tight)
    assert len(text) <= tight
    assert "docs/plans/widget.md" in text
    assert "Done when:" in text
    assert "tautline goal-status" in text
    # Whatever the leftover budget admits, the rest is accounted rather than dropped.
    assert meta["milestones_included"] < 50
    assert meta["milestones_included"] + meta["milestones_omitted"] == 50
    assert f"(+{meta['milestones_omitted']} more in the plan)" in text


def test_composed_goal_passes_its_own_checker():
    text, _meta = _compose(milestones=["Build ingest", "Wire retries"])
    assert ga.goal_assignment_issues(text, plan_ref="docs/plans/widget.md") == []


# -- the checker --


def test_over_limit_goal_is_rejected_and_the_message_names_the_overage():
    """Batch 2026-08-11 B7 T4.5: the enforced ceiling is now the AUTHORING one, and the
    message names both numbers so the author can see the reserve they are spending."""
    issues = ga.goal_assignment_length_issues("x" * 4200, limit=4000)
    assert len(issues) == 1
    assert "4200 characters" in issues[0]
    assert "600 over" in issues[0]
    assert "3600" in issues[0] and "4000" in issues[0]


def test_a_goal_exactly_at_the_authoring_ceiling_is_accepted():
    assert ga.goal_assignment_length_issues("x" * 3600, limit=4000) == []


def test_empty_and_stub_goals_are_rejected():
    assert ga.goal_assignment_length_issues("") == [
        "goal assignment is empty; there is nothing to assign"
    ]
    assert ga.goal_assignment_length_issues("do the plan") != []


def test_shape_check_requires_the_plan_reference_and_a_completion_condition():
    body = "/goal Do the work. Done when: it is merged." + "." * 100
    assert ga.goal_assignment_shape_issues(body, "docs/plans/widget.md") != []
    with_ref = body + " docs/plans/widget.md"
    assert ga.goal_assignment_shape_issues(with_ref, "docs/plans/widget.md") == []

    no_condition = "/goal Complete docs/plans/widget.md somehow." + "." * 100
    issues = ga.goal_assignment_shape_issues(no_condition, "docs/plans/widget.md")
    assert any("completion condition" in issue for issue in issues)


def test_plan_reference_matches_on_the_file_stem_too():
    body = "/goal Complete `widget.md`. Done when: merged." + "." * 100
    assert ga.goal_assignment_shape_issues(body, "docs/plans/widget.md") == []


# -- milestone extraction --


def test_milestones_come_from_the_workstreams_section_only():
    assert ga.plan_assignment_milestones(PLAN) == [
        "Build the ingest adapter",
        "Wire the retry queue",
        "Backfill the historical rows",
    ]


def test_completed_bullets_are_not_assignable_work():
    assert "Spike the schema" not in ga.plan_assignment_milestones(PLAN)


def test_subheadings_win_over_the_bullets_nested_under_them():
    """The plan-authoring standard names each unit as its own `### Task N` heading; the
    bullets underneath are that unit's file list. Preferring bullets would produce a goal
    listing file paths instead of workstreams."""
    plan = """
# Plan
## Workstreams
### W1 — build the ingest adapter `model-tier: standard`
**Files:**
- Create: `src/ingest.py`
- Modify: `src/cli.py`
### W2 — wire the retry queue `model-tier: deep`
- Modify: `src/retry.py`
"""
    assert ga.plan_assignment_milestones(plan) == [
        "W1 — build the ingest adapter",
        "W2 — wire the retry queue",
    ]


def test_bullets_are_used_when_the_section_has_no_subheadings():
    plan = """
# Plan
## Milestones
- Build the ingest adapter
- Wire the retry queue
"""
    assert ga.plan_assignment_milestones(plan) == [
        "Build the ingest adapter",
        "Wire the retry queue",
    ]


def test_a_hash_comment_inside_fenced_code_does_not_end_the_section():
    """Regression: a `# comment` in an embedded snippet parsed as an H1 and silently
    truncated the workstream list to whatever preceded the first code block."""
    plan = """
# Plan
## Workstreams
### W1 — core module
```python
# test_evidence.py — pure functions, no module-level state
def f(): ...
```
### W2 — surfacing
### W3 — dogfood
"""
    assert ga.plan_assignment_milestones(plan) == [
        "W1 — core module",
        "W2 — surfacing",
        "W3 — dogfood",
    ]


def test_deeper_subheadings_are_workstream_detail_not_units():
    plan = """
# Plan
## Workstreams
### W1 — core module
#### Files
#### Tests
### W2 — surfacing
"""
    assert ga.plan_assignment_milestones(plan) == ["W1 — core module", "W2 — surfacing"]


def test_milestone_list_is_terminated_before_the_completion_clause():
    text, _meta = _compose(milestones=["Build ingest"])
    assert "Build ingest. Done when:" in text


def test_the_terminating_period_is_budgeted():
    """The period is appended after budgeting, so it must be reserved or it can push a
    goal one character past a limit the composer just certified."""
    units = [f"Workstream {i} does a thing" for i in range(40)]
    floor = _min_limit(units)
    for limit in range(floor, floor + 700, 7):
        text, meta = _compose(milestones=units, limit=limit)
        assert len(text) <= limit
        assert meta["char_count"] == len(text)


def test_a_plan_with_no_scope_section_yields_no_milestones():
    assert ga.plan_assignment_milestones("# Plan\n\nJust prose.\n") == []


# -- the cli mirror of the limit --


def test_cli_default_char_limit_mirrors_the_module_constant(cli):
    assert cli._GOAL_ASSIGNMENT_DEFAULT_CHAR_LIMIT == ga.GOAL_ASSIGNMENT_CHAR_LIMIT


def test_plan_outside_the_target_refuses_instead_of_tracebacking(run_cli, tmp_path):
    """Codex T2 R1 P2: path_relative_to_target raises on an outside path, so containment must
    be checked first. A fail-closed surface that exits with a traceback is not fail-closed."""
    outside = tmp_path / "nope.md"
    outside.write_text("# Plan\n", encoding="utf-8")
    result = run_cli("goal-assignment", "--target", ".", "--plan", str(outside))

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # The question WIDENED with item 59: "under this lane" became "under any configured plan
    # root", because a plan the lane just reviewed externally must be assignable to the builder
    # who will execute it. Still fail-closed, still an actionable message, still no traceback --
    # which is what this test was actually protecting.
    assert "goal_assignment_error: plan is outside every configured plan root" in result.stderr


def test_check_without_a_plan_says_the_reference_check_was_skipped(run_cli, tmp_path):
    """Codex T2 R1 P2: a silent skip reads as a clean bill of health on a check never run."""
    goal = tmp_path / "goal.txt"
    goal.write_text("/goal Do it. Done when: merged." + "." * 120, encoding="utf-8")
    result = run_cli("goal-assignment", "--target", ".", "--check", str(goal))

    assert result.returncode == 0
    assert "goal_assignment_plan_reference_check: skipped" in result.stdout


def test_emitted_goal_is_delimited_and_raw_matches_it_byte_for_byte(run_cli):
    """Codex T2 R2 P2: char_count certifies the goal text alone, so a `goal_assignment: `
    label invited pasting an 18-character prefix that could push a certified goal back over
    the limit. The block carries exactly the certified bytes, and --raw must equal them."""
    # --allow-unfinalized on purpose: this asserts block/raw byte-equality, not finalization.
    # Requiring a FINALIZED plan tied the test to `.ai-runs/plan-review/` evidence, which is
    # gitignored — so it passed locally and failed on every fresh checkout, including CI.
    plan = "docs/superpowers/plans/2026-07-27-test-execution-evidence-v2.md"
    result = run_cli("goal-assignment", "--target", ".", "--plan", plan, "--allow-unfinalized")
    assert result.returncode == 0, result.stderr

    lines = result.stdout.splitlines()
    start, end = lines.index("goal_assignment_begin"), lines.index("goal_assignment_end")
    body = "\n".join(lines[start + 1 : end])
    prefix = "goal_assignment_char_count:"
    count = next(int(line.split(":", 1)[1]) for line in lines if line.startswith(prefix))
    assert len(body) == count, "the emitted block must be exactly what char_count certifies"

    args = ("--target", ".", "--plan", plan, "--allow-unfinalized")
    raw = run_cli("goal-assignment", *args, "--raw")
    assert raw.returncode == 0, raw.stderr
    assert raw.stdout.strip("\n") == body
    assert "goal_assignment" not in raw.stdout


def test_goal_assignment_is_classified_in_the_remediation_partition(cli):
    assert "goal-assignment" in cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS
    assert "goal-assignment" not in cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS
