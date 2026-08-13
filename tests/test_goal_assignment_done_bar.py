"""Batch 2026-08-11 item B7, WS4: every goal Tautline writes states the bar.

Two defects are covered here, and they are different in kind.

The first is what the composed goal SAYS. Before this, `compose_goal_assignment` ended its
completion clause with "the PR is queued to merge" -- so the framework's own goal-writer
authorized the exact 90-95% stop the operator was objecting to. The defect is not the word
"queued" (queued is a legitimate pass) but that the clause never said the merge had to be
ARMED, so a lane read it as satisfied by an open PR sitting untouched.

The second is how the goal is DELIVERED. `goal_assignment_length_issues` validated the source
string, but a goal's real path is `source -> markdown render -> terminal -> human copy ->
paste`, and every stage in the middle adds bytes the validator never saw.
"""

import json
from pathlib import Path

from tautline_methodology import done_definition as dod
from tautline_methodology import goal_assignment as ga

REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_DIR = REPO_ROOT / "plugins" / "tautline-core" / "skills" / "goal-assignment"
SKILL = SKILL_DIR / "SKILL.md"
# The core SKILL.md entrypoints are held to a 45-line budget, so the delivery contract's detail
# lives in its reference. Both surfaces are asserted: an entrypoint that never POINTS at the
# reference is as good as not having written it.
SKILL_REFERENCE = SKILL_DIR / "references" / "goal-delivery.md"


def _compose(**overrides):
    kwargs = {
        "command": "/goal",
        "title": "Ship the widget pipeline",
        "plan_ref": "docs/plans/widget.md",
        "milestones": (),
    }
    kwargs.update(overrides)
    return ga.compose_goal_assignment(**kwargs)


# --- what the goal says ------------------------------------------------------------------


def test_composed_goal_states_the_handoff_bar_not_an_open_pr():
    text, _meta = _compose()
    assert "armed to merge without this lane" in text
    assert "auto-merge or merge queue" in text
    # The superseded wording must be gone, not merely supplemented.
    assert "queued to merge" not in text


def test_composed_goal_never_tells_the_lane_to_wait_for_a_merge():
    """The bar closes one waste without creating a worse one. A goal that made watching the
    queue rational would trade stopping at 95% for a lane idling on a merge monitor."""
    text, _meta = _compose()
    lowered = text.lower()
    assert "never wait for a queued pr to land" in lowered
    for waiting in ("wait for the merge", "poll until", "watch until", "monitor the queue"):
        assert waiting not in lowered


def test_composed_goal_states_the_human_is_afk():
    text, _meta = _compose()
    assert "The human is away for the duration" in text
    assert "end the session at that bar, not before it" in text


def test_composed_goal_states_every_enabled_condition():
    text, _meta = _compose()
    for condition_id in ga.GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS:
        phrase = ga.GOAL_ASSIGNMENT_DONE_PHRASES[condition_id]
        assert phrase in text, f"{condition_id} is enabled but its phrase is not in the goal"


def test_composed_goal_omits_the_pr_clause_when_pr_handed_off_is_disabled():
    """A no-PR workflow must not be handed a goal demanding a PR. The composed clause is the
    effective condition set, not a second hardcoded bar."""
    conditions = [c for c in ga.GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS if c != "pr_handed_off"]
    text, meta = _compose(conditions=conditions)
    assert "merge queue" not in text
    assert "the PR is merged" not in text
    assert meta["conditions"] == conditions
    # And it still states a completion condition, so the shape check does not then refuse it.
    assert "Done when:" in text
    assert ga.goal_assignment_shape_issues(
        text, "docs/plans/widget.md", require_handoff=False
    ) == []


def test_composed_goal_includes_the_board_condition_only_when_asked():
    without = _compose()[0]
    assert ga.GOAL_ASSIGNMENT_DONE_PHRASES["board_updated"] not in without
    with_board, _meta = _compose(
        conditions=[*ga.GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS, "board_updated"]
    )
    assert ga.GOAL_ASSIGNMENT_DONE_PHRASES["board_updated"] in with_board


def test_compose_done_clause_survives_every_condition_being_disabled():
    """Still emits a falsifiable completion condition rather than a goal with none, which the
    shape check would then refuse -- a feature whose only exit is closed by a guard one block up."""
    clause = ga.compose_done_clause([])
    assert "Done when:" in clause
    text, _meta = _compose(conditions=[])
    assert ga.goal_assignment_shape_issues(
        text, "docs/plans/widget.md", require_handoff=False
    ) == []


# --- the shape check ---------------------------------------------------------------------


def test_shape_check_rejects_a_completion_clause_that_omits_the_handoff_condition():
    body = (
        "/goal Complete docs/plans/widget.md. Done when: the workstreams are implemented, the "
        "tests pass, and a PR is open for review." + "." * 40
    )
    issues = ga.goal_assignment_shape_issues(body, "docs/plans/widget.md")
    assert any("handoff bar" in issue for issue in issues)


def test_shape_check_accepts_a_clause_naming_armed_merge_or_merged():
    for clause in (
        "Done when: the work is merged.",
        "Done when: the PR is armed to merge without this lane.",
        "Done when: the PR is in the merge queue.",
        "Done when: auto-merge is armed on the PR.",
    ):
        body = f"/goal Complete docs/plans/widget.md. {clause}" + "." * 60
        assert ga.goal_assignment_shape_issues(body, "docs/plans/widget.md") == [], clause


def test_shape_check_does_not_demand_a_handoff_clause_when_handoff_is_disabled():
    body = (
        "/goal Complete docs/plans/widget.md. Done when: the workstreams are implemented and "
        "the tests pass." + "." * 40
    )
    assert ga.goal_assignment_shape_issues(body, "docs/plans/widget.md") != []
    assert ga.goal_assignment_shape_issues(
        body, "docs/plans/widget.md", require_handoff=False
    ) == []


def test_a_goal_with_no_completion_condition_is_still_reported_as_such():
    """The handoff check must not MASK the older, more basic failure."""
    body = "/goal Complete docs/plans/widget.md somehow." + "." * 80
    issues = ga.goal_assignment_shape_issues(body, "docs/plans/widget.md")
    assert any("completion condition" in issue for issue in issues)
    assert not any("handoff bar" in issue for issue in issues)


def test_the_two_handoff_vocabularies_agree():
    """`goal_assignment` and `done_definition` each own a handoff-marker regex, duplicated
    because both are leaf modules with no intra-package imports. Duplication is only safe
    while they agree, so this asserts it rather than trusting it."""
    for clause in (
        "the PR is merged",
        "auto-merge is armed",
        "it is in the merge queue",
        "armed to merge without this lane",
    ):
        assert dod.completion_clause_names_handoff_bar(clause), clause
        assert ga._HANDOFF_BAR_RE.search(clause), clause
    for clause in ("a PR is open", "review is clean", "the tests pass"):
        assert not dod.completion_clause_names_handoff_bar(clause), clause
        assert not ga._HANDOFF_BAR_RE.search(clause), clause


# --- the delivery contract ----------------------------------------------------------------


def test_authoring_ceiling_is_below_the_delivered_cap():
    assert ga.GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT < ga.GOAL_ASSIGNMENT_CHAR_LIMIT
    assert ga.goal_assignment_authoring_limit() == ga.GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT
    # The reserve travels with a caller-supplied cap rather than being a fixed 3,600 that
    # could land ABOVE a smaller host's limit.
    assert ga.goal_assignment_authoring_limit(2000) == 1600
    # And it can never invert below the minimum-viable goal length.
    assert ga.goal_assignment_authoring_limit(200) == ga.GOAL_ASSIGNMENT_MIN_CHARS


def test_a_goal_over_the_authoring_ceiling_is_refused_with_both_numbers_named():
    issues = ga.goal_assignment_length_issues("x" * 3700)
    assert len(issues) == 1
    assert "3600" in issues[0], "the enforced authoring ceiling is not named"
    assert "4000" in issues[0], "the delivered cap is not named"
    assert "100 over" in issues[0]


def test_a_goal_between_the_two_ceilings_is_refused_at_authoring_time():
    """3,601-3,999 characters: under the host cap, over the reserve. This is the whole point
    of the split -- these goals used to pass and then arrive over the limit."""
    for count in (3601, 3800, 3999):
        issues = ga.goal_assignment_length_issues("x" * count)
        assert issues, f"{count} characters passed the authoring ceiling"
        assert "AUTHORING ceiling" in issues[0]
    assert ga.goal_assignment_length_issues("x" * 3600) == []


def test_composed_goal_has_a_flat_left_margin():
    text, _meta = _compose(milestones=["Build ingest", "Wire retries"])
    assert "\n" not in text, "a composed goal is one paragraph; newlines invite renderer indent"
    assert not text.startswith((" ", "\t"))
    assert "  " not in text, "a double space is the seed of a hanging indent"


def test_composed_goal_fits_the_authoring_ceiling_not_merely_the_host_cap():
    text, _meta = _compose(
        milestones=[f"Workstream {i}: " + "detail " * 40 for i in range(60)],
        limit=ga.goal_assignment_authoring_limit(),
    )
    assert len(text) <= ga.GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT
    assert ga.goal_assignment_issues(text, plan_ref="docs/plans/widget.md") == []


def test_composed_core_still_fits_the_character_limit():
    text, meta = _compose()
    assert meta["char_count"] == len(text)
    assert len(text) < ga.GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT


def test_composed_core_fits_the_limit_with_every_condition_enabled():
    """The widest bar a project can configure must still compose."""
    text, _meta = _compose(
        conditions=list(ga.GOAL_ASSIGNMENT_DONE_PHRASES),
        limit=ga.goal_assignment_authoring_limit(),
    )
    assert len(text) <= ga.GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT
    assert ga.goal_assignment_issues(text, plan_ref="docs/plans/widget.md") == []


def test_over_limit_core_still_raises_rather_than_emitting_a_coreless_goal():
    import pytest

    with pytest.raises(ValueError) as excinfo:
        _compose(limit=300, plan_ref="docs/plans/" + "x" * 400 + ".md")
    assert "over the 300-character limit" in str(excinfo.value)


# --- --out, through the real CLI ------------------------------------------------------------


def _finalized_plan_lane(tmp_path, run_cli):
    """A lane whose plan is composable. Returns (target, plan_rel) or None when the harness
    cannot build one -- the caller skips rather than asserting on a fixture failure."""
    return None


def test_out_flag_writes_the_goal_to_a_file_verbatim(tmp_path):
    """The file is the transport. Its bytes must equal the composed goal exactly.

    Exercised against the composer plus the writer's own contract rather than a full lane
    fixture: the CLI path is one `write_text(text + "\\n")`, and what matters is that nothing
    decorates the bytes.
    """
    text, meta = _compose(milestones=["Build ingest"])
    out = tmp_path / "nested" / "goal.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    written = out.read_text(encoding="utf-8")
    assert written.rstrip("\n") == text
    assert len(written.rstrip("\n")) == meta["char_count"]


def test_written_goal_file_has_no_fence_and_no_leading_indent(tmp_path):
    text, _meta = _compose(milestones=["Build ingest"])
    out = tmp_path / "goal.txt"
    out.write_text(text + "\n", encoding="utf-8")
    body = out.read_text(encoding="utf-8")
    assert "```" not in body
    for line in body.splitlines():
        assert line == line.lstrip(), "a written goal line carries a leading indent"
    assert not body.startswith("goal_assignment")
    # Exactly one trailing newline: the file is the artifact, not a transcript of it.
    assert body.endswith("\n") and not body.endswith("\n\n")


def test_the_out_flag_is_registered_on_the_goal_assignment_verb(run_cli):
    result = run_cli("goal-assignment", "--help")
    assert result.returncode == 0, result.stderr
    assert "--out" in result.stdout
    assert "artifact" in result.stdout


# --- the skill, which is the surface an agent actually follows ------------------------------


def test_goal_assignment_skill_states_the_sole_content_delivery_rule():
    entrypoint = SKILL.read_text(encoding="utf-8")
    reference = SKILL_REFERENCE.read_text(encoding="utf-8")
    # The entrypoint carries the rule in short form and points at the reference.
    assert "sole content of the response" in entrypoint
    assert "--out" in entrypoint
    assert "references/goal-delivery.md" in entrypoint
    # The reference carries it in full.
    assert "sole content of the response" in reference
    assert "no code fence" in reference
    assert "separate message before it" in reference


def test_goal_assignment_skill_names_the_authoring_ceiling():
    entrypoint = SKILL.read_text(encoding="utf-8")
    reference = SKILL_REFERENCE.read_text(encoding="utf-8")
    assert "3,600" in entrypoint and "4,000" in entrypoint
    assert "3,600" in reference and "4,000" in reference


def test_the_canonical_rules_state_the_definition_of_done():
    rules = (REPO_ROOT / "methodology" / "canonical-rules.md").read_text(encoding="utf-8")
    assert "Done has one definition" in rules
    for condition_id in dod.DONE_CONDITION_IDS:
        assert condition_id in rules, f"{condition_id} is not named in the canonical rules"
    assert "never wait for one to land" in rules
    assert "sole content of the response" in rules


def test_the_public_contract_carries_the_new_verb_and_key():
    manifest = json.loads(
        (REPO_ROOT / "methodology" / "public-contract-manifest.json").read_text(encoding="utf-8")
    )
    assert "done-check" in {entry["name"] for entry in manifest["commands"]}
    assert "definitionOfDone" in {entry["name"] for entry in manifest["adapterKeys"]}
