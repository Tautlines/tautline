"""The two bases a plan path is measured against (item 59 W3).

`plan_relative_base` and `plan_review_root` deliberately answer DIFFERENT questions, and conflating
them is what silently rewrote every lane-local manifest on an earlier attempt at this item -- caught
only by seven tests. So they are pinned separately here, including the case where they disagree.

- **`plan_relative_base`** — what a plan path is relativized against when RECORDED. It varies by
  the plan's root: a lane plan is relative to the lane, an external one to its own repo. Getting
  this wrong writes an unusable reference into evidence.
- **`plan_review_root`** — where review evidence for that plan LIVES. It is always this lane, even
  for a plan owned by another repo, because the lane that ran the review is the lane that holds its
  receipts. Getting this wrong moves 61 existing manifests.
"""
from __future__ import annotations

import pytest

from tautline_methodology import cli, plan_reference

PLANS_ROOT = "docs/superpowers/plans"
LANE = plan_reference.LANE_ROOT


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


# --- plan_relative_base: varies by root -----------------------------------------------------------


def test_lane_plans_are_relative_to_the_lane(lane):
    assert cli.plan_relative_base(_data(), lane, LANE) == lane


def test_external_plans_are_relative_to_their_own_repo(lane):
    base = cli.plan_relative_base(_data("../tautline-backlog"), lane, "tautline-backlog")

    assert base == (lane.parent / "tautline-backlog").resolve()


def test_an_unconfigured_root_is_refused_rather_than_defaulted_to_the_lane(lane):
    """Silently falling back to the lane is how an external plan gets recorded as a lane path."""
    with pytest.raises(ValueError, match="not a configured plan root"):
        cli.plan_relative_base(_data(), lane, "tautline-backlog")


# --- plan_review_root: always the lane ------------------------------------------------------------


def test_review_evidence_for_a_lane_plan_lives_in_the_lane(lane):
    assert cli.plan_review_root(_data(), lane) == cli.planning_source_root(_data(), lane)


def test_review_evidence_for_an_external_plan_still_lives_in_the_lane(lane):
    """The lane that ran the review holds its receipts, even when it does not own the plan.

    This is the half that must NOT follow the plan's root. If it did, the 61 existing manifests
    would move the moment a planRepo was configured.
    """
    data = _data("../tautline-backlog")

    assert cli.plan_review_root(data, lane) == lane / PLANS_ROOT


def test_a_lane_plan_is_under_a_configured_root(lane):
    plan = lane / PLANS_ROOT / "2026-08-02-x.md"
    plan.write_text("# plan\n", encoding="utf-8")

    assert cli.plan_is_under_a_configured_root(_data(), lane, plan)


def test_an_external_plan_is_under_a_configured_root_once_planrepo_is_set(lane):
    """The 13 group-A refusals exist because this was false for every external plan."""
    external = lane.parent / "tautline-backlog" / "ready/item-a/plan.md"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("# plan\n", encoding="utf-8")

    assert not cli.plan_is_under_a_configured_root(_data(), lane, external)
    assert cli.plan_is_under_a_configured_root(_data("../tautline-backlog"), lane, external)


def test_an_unrelated_path_is_under_no_configured_root(lane):
    """The containment guarantee must survive the widening -- this is what it still refuses."""
    stray = lane.parent / "somewhere-else" / "plan.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# plan\n", encoding="utf-8")

    assert not cli.plan_is_under_a_configured_root(_data("../tautline-backlog"), lane, stray)


def test_the_lane_root_is_the_planning_source_root_not_the_whole_checkout(lane):
    """A file elsewhere in the lane is not a plan; group A gated on the plans dir, not the repo."""
    not_a_plan = lane / "src" / "whatever.md"
    not_a_plan.parent.mkdir(parents=True, exist_ok=True)
    not_a_plan.write_text("# nope\n", encoding="utf-8")

    assert not cli.plan_is_under_a_configured_root(_data(), lane, not_a_plan)


def test_rendering_a_lane_plan_reference_carries_the_lane_root(lane):
    plan = lane / PLANS_ROOT / "2026-08-02-x.md"
    plan.write_text("# plan\n", encoding="utf-8")

    rendered = cli.render_plan_reference_for(_data(), lane, plan)

    assert rendered == f"lane:{PLANS_ROOT}/2026-08-02-x.md"


def test_rendering_an_external_plan_reference_carries_its_repo_root(lane):
    """The point of the whole item: the reference says which repo it came from."""
    external = lane.parent / "tautline-backlog" / "ready/item-a/plan.md"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("# plan\n", encoding="utf-8")

    rendered = cli.render_plan_reference_for(_data("../tautline-backlog"), lane, external)

    assert rendered == "tautline-backlog:ready/item-a/plan.md"


def test_a_rendered_reference_round_trips_back_to_the_same_file(lane):
    external = lane.parent / "tautline-backlog" / "ready/item-a/plan.md"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("# plan\n", encoding="utf-8")
    data = _data("../tautline-backlog")

    rendered = cli.render_plan_reference_for(data, lane, external)
    resolved = cli.paths_module().resolve_plan_reference(data, lane, rendered)

    assert resolved.resolve() == external.resolve()


def test_rendering_refuses_a_plan_under_no_configured_root(lane):
    """Rendering a reference nothing can resolve would write a dead record."""
    stray = lane.parent / "somewhere-else" / "plan.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# plan\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no configured plan root"):
        cli.render_plan_reference_for(_data(), lane, stray)


# --- the surface that is deliberately NOT converted -----------------------------------------------


def test_reading_a_plans_tracker_fields_works_outside_the_lane(lane):
    """`goal_tracker_claim_plan_active` is exempt, and this verifies the exemption.

    The W0b inventory flagged it as fitting neither group and needing its own judgement. It does not
    contain and does not relativize -- it hands the path to a reader of the plan's own content. So
    there is nothing to widen, and it already works for an externally-owned plan once the caller can
    resolve one, which the group A and B conversions now make possible upstream. Asserted rather
    than assumed, because silence is how this surface stayed invisible for four review rounds.
    """
    external = lane.parent / "tautline-backlog" / "ready/item-a/plan.md"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text(
        "# plan\n\n## GitHub Project Source\n\n- project_item_id: PVTI_external\n",
        encoding="utf-8",
    )

    assert cli.goal_tracker_ref_from_plan(external) == "PVTI_external"


def test_the_two_bases_disagree_for_an_external_plan(lane):
    """The whole reason they are separate functions, stated as a test."""
    data = _data("../tautline-backlog")

    relative_base = cli.plan_relative_base(data, lane, "tautline-backlog")
    review_root = cli.plan_review_root(data, lane)

    assert relative_base != review_root
    assert review_root.is_relative_to(lane)
    assert not relative_base.is_relative_to(lane)
