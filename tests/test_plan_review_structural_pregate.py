"""Item 80 (N6): content problems surface at round zero, while fixing them is still free.

`plan-finalization-precheck` already refuses these -- but only AFTER the review budget is spent,
and fixing them then changes the plan, which unbinds the evidence. Item 57 lost one successor plan
to that and item 62 lost two. The point of this gate is WHEN, not whether.
"""

from __future__ import annotations

import pytest


def _adapter(enforcement: str | None = None) -> dict:
    if enforcement is None:
        return {}
    return {"planning": {"contentPregate": {"enforcement": enforcement}}}


# --- the knob ---------------------------------------------------------------------------------


def test_the_default_is_warn_not_block(cli) -> None:
    """A BINDING decision, not timidity. The framework's own item-34 lineage says a plan
    legitimately grows, so auto-refusing a section gap at round zero would refuse plans that were
    about to be fine. Every enforcement surface this program shipped landed warn-first with a
    deliberate, separately released flip."""
    from tautline_methodology.plan_authoring import normalize_planning_content_pregate

    assert normalize_planning_content_pregate({})["enforcement"] == "warn"


@pytest.mark.parametrize("value", ["off", "warn", "block"])
def test_every_declared_enforcement_is_accepted(cli, value) -> None:
    from tautline_methodology.plan_authoring import normalize_planning_content_pregate

    assert normalize_planning_content_pregate(_adapter(value))["enforcement"] == value


def test_an_unknown_enforcement_refuses_by_name(cli) -> None:
    from tautline_methodology.plan_authoring import normalize_planning_content_pregate

    with pytest.raises(SystemExit) as exc:
        normalize_planning_content_pregate(_adapter("nope"))

    assert "planning.contentPregate.enforcement" in str(exc.value)


def test_heuristics_stay_advisory_even_under_block(cli) -> None:
    """Length and marker checks are PROXIES for quality, and a proxy that refuses is a proxy that
    gets gamed. Section-shaped gaps are the ones a reviewer cannot work around."""
    from tautline_methodology.plan_authoring import partition_pregate_errors

    refusable, advisory = partition_pregate_errors([
        "plan missing substantive sections: assumptions, dependencies",
        "plan is shorter than the 200 line count guidance",
        "missing the embedded execution-autonomy contract",
    ])

    assert any("substantive sections" in r for r in refusable)
    assert any("line count" in a for a in advisory)


# --- the gate ---------------------------------------------------------------------------------


def _plan(tmp_path, text="# Plan\n\nnothing substantive here.\n"):
    p = tmp_path / "plan.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_off_computes_nothing_at_the_r1_seam(cli, tmp_path) -> None:
    refusals, warnings = cli.plan_review_content_pregate(_adapter("off"), _plan(tmp_path), 0)

    assert (refusals, warnings) == ([], [])


def test_warn_reports_everything_and_refuses_nothing(cli, tmp_path) -> None:
    refusals, warnings = cli.plan_review_content_pregate(_adapter(), _plan(tmp_path), 0)

    assert refusals == [], "the default never refuses"
    assert warnings, "but it does not go quiet either"


def test_block_refuses_only_section_gaps_at_round_zero(cli, tmp_path) -> None:
    refusals, warnings = cli.plan_review_content_pregate(_adapter("block"), _plan(tmp_path), 0)

    assert refusals, "a section-shaped gap is refusable under block"
    assert all("shorter than" not in r for r in refusals), "heuristics stay out of the refusal"


def test_mid_loop_is_always_advisory(cli, tmp_path) -> None:
    """Forcing an edit mid-loop is the ORIGINAL defect, not a stricter version of the fix: a plan
    edited after round one unbinds the evidence the rounds already produced."""
    refusals, warnings = cli.plan_review_content_pregate(_adapter("block"), _plan(tmp_path), 2)

    assert refusals == [], "observed_runs > 0 degrades to warnings in every mode"
    assert warnings


def test_an_unreadable_plan_is_not_a_content_verdict(cli, tmp_path) -> None:
    """The gates above already decided the plan is readable; inventing a refusal from a transient
    read failure would refuse a plan nobody can see is wrong."""
    missing = tmp_path / "gone.md"

    assert cli.plan_review_content_pregate(_adapter("block"), missing, 0) == ([], [])


def test_the_next_action_says_the_fix_is_still_free(cli, tmp_path) -> None:
    line = cli.plan_review_content_pregate_next_action("docs/plans/p.md", tmp_path)

    assert "BEFORE R1" in line
    assert "void no evidence" in line
    assert "plan-substance-check" in line, "and names a runnable re-check"


# --- the C2 interlock: this is the debt W1.3's PR body assigns to item 80 ----------------------


def test_content_refusal_never_holds_a_lease(cli) -> None:
    """W1.3 acquires a 2-hour in-flight lease. A content refusal placed BELOW that acquisition
    would return while the lease is held, stranding it for the whole TTL on a plan nobody is
    reviewing -- and the next attempt, even a corrected one, would be lease-refused. Pinned at the
    source because the ordering is the whole invariant and no output assertion can see it."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    pregate = source.index("plan_review_content_pregate(")
    lease = source.index("plan_review_acquire_inflight_lease(")

    assert pregate < lease, "the content gate goes ABOVE the lease acquisition"
    refusal = source.index("return 1", pregate)
    assert refusal < lease, "and its refusal returns before any lease is taken"


def test_warn_path_does_not_touch_the_lease_lifecycle(cli) -> None:
    """Under the default, a warned run acquires and releases exactly as a clean run does -- the
    warnings are printed on the way past, not a branch around the lease."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    pregate = source.index("plan_review_content_pregate(")
    lease = source.index("plan_review_acquire_inflight_lease(")
    between = source[pregate:lease]

    assert between.count("return 1") == 1, "exactly one exit, and it is the block-mode refusal"
    assert "pregate_refusals" in between, "guarded by refusals, never by warnings"


def test_a_reviewed_plan_cannot_pass_on_its_reviewer_s_words(cli, tmp_path) -> None:
    """Codex R2 P2. A previously-reviewed plan carries its own log under
    `## Cross-Model Review Evidence`, and that log routinely contains `model-tier:`,
    `best judgment` and `decision-record`. An unstripped read let a plan satisfy authoring markers
    it never authored -- out of words a REVIEWER wrote ABOUT it -- which made the gate weakest on
    exactly the plans most likely to reach it."""
    plan = tmp_path / "plan.md"
    plan.write_text(
        "# Plan\n\nThin body with no markers of its own.\n\n"
        "## Cross-Model Review Evidence\n\n"
        "Reviewer notes: tasks tagged model-tier: deep, use best judgment, "
        "record with decision-record.\n",
        encoding="utf-8",
    )

    _refusals, warnings = cli.plan_review_content_pregate(_adapter(), plan, 0)
    joined = " ".join(warnings)

    assert "execution-autonomy contract" in joined or "model-tier" in joined, (
        "the authoring gap must still be reported; the evidence block is not the plan"
    )


def test_a_length_heuristic_never_refuses_under_block(cli, tmp_path) -> None:
    """Codex R2 P2, and the rule this classifier exists to implement. Blacklisting advisory
    phrases meant every heuristic string nobody thought to list defaulted to BLOCKING -- and
    `validate_plan_substance` emits 'plan is too short to be decision-complete', which matched none
    of them. A plan with every required section present was refused for being short."""
    from tautline_methodology.plan_authoring import partition_pregate_errors

    refusable, advisory = partition_pregate_errors([
        "plan is too short to be decision-complete",
        "plan missing substantive sections: assumptions",
        "some future heuristic nobody has written yet",
    ])

    assert any("too short" in a for a in advisory), "the string the code actually emits"
    assert any("future heuristic" in a for a in advisory), (
        "and anything unrecognised defaults to advisory, not to blocking"
    )
    assert refusable == ["plan missing substantive sections: assumptions"]
