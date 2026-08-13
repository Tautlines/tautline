"""Milestone `sourcePlan` is a rooted plan reference too (item 59 W3).

The W0b inventory found this and said not to let it be decided by omission: `initial_milestone_run`
and `refresh_milestone_run` write `sourcePlan` into PERSISTED milestone state, making milestones a
second store of plan references with the same under-specification as `.plan-reviews/`.

They adopt the rooted form. The hazard the inventory named is real and lives in the retarget guard,
which compared the stored and recomputed values as STRINGS -- so changing the rendering alone would
have retarget-refused every ledger written before this release. The guard now compares what the
references RESOLVE to, which is backwards-compatible and the correct comparison anyway: a guard
against retargeting should care about the target, not the spelling.
"""
from __future__ import annotations

import pytest

from tautline_methodology import cli

PLANS_ROOT = "docs/superpowers/plans"


@pytest.fixture()
def lane(tmp_path):
    (tmp_path / "lane-checkout" / PLANS_ROOT).mkdir(parents=True)
    (tmp_path / "tautline-backlog").mkdir()
    return tmp_path / "lane-checkout"


def _data(plan_repo: str = "") -> dict:
    return {
        "planningArtifacts": {"sourceOfTruth": PLANS_ROOT},
        "backlogProvider": {"enabled": False, "planRepo": plan_repo},
    }


def _plan(lane, rel: str):
    path = lane / PLANS_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# plan\n", encoding="utf-8")
    return path


def test_two_spellings_of_the_same_plan_match(lane):
    """Category D: recorded run-meta holds v1, the recomputed value is v2, same plan.

    Matching them as strings is what made `plan_review_pending_block_reason` return None -- the
    plan-edit guard silently stopped blocking. Every consumer that compares a RECORDED reference
    against a recomputed one has to compare resolutions.
    """
    _plan(lane, "2026-08-02-x.md")

    assert cli.plan_references_match(
        _data(), lane, f"{PLANS_ROOT}/2026-08-02-x.md", f"lane:{PLANS_ROOT}/2026-08-02-x.md"
    )


def test_two_different_plans_do_not_match(lane):
    _plan(lane, "2026-08-02-x.md")
    _plan(lane, "2026-08-02-y.md")

    assert not cli.plan_references_match(
        _data(), lane, f"{PLANS_ROOT}/2026-08-02-x.md", f"lane:{PLANS_ROOT}/2026-08-02-y.md"
    )


def test_an_empty_recorded_reference_matches_nothing(lane):
    _plan(lane, "2026-08-02-x.md")

    assert not cli.plan_references_match(_data(), lane, "", f"lane:{PLANS_ROOT}/2026-08-02-x.md")


def test_a_ledger_holding_the_bare_legacy_spelling_is_not_a_retarget(lane):
    """The whole compatibility question, in one assertion.

    Every milestone ledger written before this release stores a bare target-relative path. The
    recomputed value is now rooted. Same plan, different spelling -- and a string comparison would
    call that a retarget and refuse.
    """
    plan = _plan(lane, "2026-08-02-x.md")

    assert cli.milestone_source_plan_matches(
        _data(), lane, f"{PLANS_ROOT}/2026-08-02-x.md", plan
    )


def test_the_rooted_spelling_matches_itself(lane):
    plan = _plan(lane, "2026-08-02-x.md")

    assert cli.milestone_source_plan_matches(
        _data(), lane, f"lane:{PLANS_ROOT}/2026-08-02-x.md", plan
    )


def test_a_genuinely_different_plan_is_still_a_retarget(lane):
    """The guard must keep doing its job -- this is what it exists to refuse."""
    _plan(lane, "2026-08-02-x.md")
    other = _plan(lane, "2026-08-02-y.md")

    assert not cli.milestone_source_plan_matches(
        _data(), lane, f"{PLANS_ROOT}/2026-08-02-x.md", other
    )


def test_an_externally_rooted_reference_resolves_through_its_repo(lane):
    data = _data("../tautline-backlog")
    external = lane.parent / "tautline-backlog" / "ready/item-a/plan.md"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("# plan\n", encoding="utf-8")

    assert cli.milestone_source_plan_matches(
        data, lane, "tautline-backlog:ready/item-a/plan.md", external
    )


def test_an_unresolvable_stored_reference_is_treated_as_a_mismatch(lane):
    """Unresolvable means the guard cannot prove they match, so it must not say they do."""
    plan = _plan(lane, "2026-08-02-x.md")

    assert not cli.milestone_source_plan_matches(
        _data(), lane, "no-such-root:ready/item-a/plan.md", plan
    )
