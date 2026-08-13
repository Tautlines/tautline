"""A plan-review manifest's identity is its PATH, not its stem (item 59 W2).

`plan_review_manifest_path` slugged `plan_path.stem`, so every plan named `plan.md` -- which is
exactly what an external backlog lays out, `ready/<item>/plan.md` -- resolved to the same
`.plan-reviews/plan.json`. Two items silently overwrote each other's review evidence.

Two constraints, and they pull against each other, which is the whole difficulty.

**No existing manifest may move.** There are 61 of them. Identity is therefore the path relative to
the plan's ROOT, not to the target: a lane-local `docs/superpowers/plans/2026-08-02-x.md` is
`2026-08-02-x.md` relative to its root and slugs exactly as it does today.

**Adoption is keyed on the recorded reference, never on the manifest merely being there** -- a file
being present proves a manifest exists, not whose it is. A legacy stem-named manifest is adopted
unless its recorded reference names a *different plan that still exists*.

That last clause is not hypothetical: all three nested `archive/` plans in this repo have manifests
whose recorded `plan_path` is their PRE-ARCHIVE location. They were moved after finalization and
the records were never updated, so strict equality would orphan all three.
"""
from __future__ import annotations

import json

import pytest

from tautline_methodology import cli

PLANS_ROOT = "docs/superpowers/plans"


@pytest.fixture()
def lane(tmp_path):
    """A lane whose plans live in the conventional in-repo location."""
    (tmp_path / PLANS_ROOT / ".plan-reviews").mkdir(parents=True)
    return tmp_path


def _data() -> dict:
    return {"planningArtifacts": {"sourceOfTruth": PLANS_ROOT}}


def _write_plan(lane, rel: str) -> None:
    path = lane / PLANS_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# plan\n", encoding="utf-8")


def _write_manifest(lane, name: str, recorded_plan_rel: str) -> None:
    """Record the plan reference the way real manifests do: TARGET-relative, bare.

    A bare string is a v1 reference and must read as the lane root, which is precisely the
    backwards-compatibility guarantee W1's parser exists to provide.
    """
    (lane / PLANS_ROOT / ".plan-reviews" / f"{name}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-plan-review/v1",
                "plan_path": f"{PLANS_ROOT}/{recorded_plan_rel}",
            }
        ),
        encoding="utf-8",
    )


def _manifest_for(lane, rel: str):
    return cli.plan_review_manifest_path(_data(), lane, lane / PLANS_ROOT / rel)


# --- the hard constraint: 61 existing manifests keep their names ----------------------------------


def test_a_lane_local_top_level_plan_keeps_its_existing_name(lane):
    _write_plan(lane, "2026-08-02-plan-root-schema.md")

    assert _manifest_for(lane, "2026-08-02-plan-root-schema.md").name == (
        "2026-08-02-plan-root-schema.json"
    )


# --- the collision W2 exists to remove ------------------------------------------------------------


def test_two_plans_named_plan_md_do_not_share_a_manifest(lane):
    _write_plan(lane, "ready/item-a/plan.md")
    _write_plan(lane, "ready/item-b/plan.md")

    a = _manifest_for(lane, "ready/item-a/plan.md")
    b = _manifest_for(lane, "ready/item-b/plan.md")

    assert a != b


def test_neither_colliding_plan_slugs_to_the_bare_stem(lane):
    _write_plan(lane, "ready/item-a/plan.md")
    _write_plan(lane, "ready/item-b/plan.md")

    assert _manifest_for(lane, "ready/item-a/plan.md").name != "plan.json"
    assert _manifest_for(lane, "ready/item-b/plan.md").name != "plan.json"


# --- adoption, keyed on the recorded reference ----------------------------------------------------


def test_a_legacy_manifest_is_adopted_by_the_plan_it_records(lane):
    """The plan's own fixture: one legacy `plan.json`, two colliding `plan.md` paths."""
    _write_plan(lane, "ready/item-a/plan.md")
    _write_plan(lane, "ready/item-b/plan.md")
    _write_manifest(lane, "plan", "ready/item-a/plan.md")

    assert _manifest_for(lane, "ready/item-a/plan.md").name == "plan.json"


def test_the_other_colliding_plan_is_refused_the_legacy_manifest(lane):
    """`item-b` must not inherit `item-a`'s evidence just because the file is sitting there."""
    _write_plan(lane, "ready/item-a/plan.md")
    _write_plan(lane, "ready/item-b/plan.md")
    _write_manifest(lane, "plan", "ready/item-a/plan.md")

    assert _manifest_for(lane, "ready/item-b/plan.md").name != "plan.json"


def test_a_manifest_recording_a_vanished_plan_is_adopted_by_the_matching_stem(lane):
    """The archive case, live in this repo three times over.

    The plan was moved under `archive/` after finalization and its manifest still records the old
    location. Nothing else claims that manifest, so the moved plan keeps it.
    """
    _write_plan(lane, "archive/2026-07-14-maintainer-mode.md")
    _write_manifest(lane, "2026-07-14-maintainer-mode", "2026-07-14-maintainer-mode.md")

    resolved = _manifest_for(lane, "archive/2026-07-14-maintainer-mode.md")

    assert resolved.name == "2026-07-14-maintainer-mode.json"


def test_a_manifest_whose_recorded_plan_still_exists_is_not_stolen(lane):
    """Existence of the manifest proves one is there, not whose it is -- so check the reference."""
    _write_plan(lane, "2026-07-14-maintainer-mode.md")
    _write_plan(lane, "archive/2026-07-14-maintainer-mode.md")
    _write_manifest(lane, "2026-07-14-maintainer-mode", "2026-07-14-maintainer-mode.md")

    # The top-level plan still exists and is the recorded owner, so the archived one must not
    # take it.
    assert _manifest_for(lane, "archive/2026-07-14-maintainer-mode.md").name != (
        "2026-07-14-maintainer-mode.json"
    )
    assert _manifest_for(lane, "2026-07-14-maintainer-mode.md").name == (
        "2026-07-14-maintainer-mode.json"
    )


def test_imported_manifests_carry_the_same_identity(lane):
    """`.imported.json` had the identical stem collision, and zero of them exist yet.

    Nothing to migrate, so it takes the path-based identity outright -- no adoption path, because
    an adoption rule with no legacy to adopt is untestable machinery that would rot.
    """
    _write_plan(lane, "ready/item-a/plan.md")
    _write_plan(lane, "ready/item-b/plan.md")
    data = _data()

    a = cli.plan_review_import_manifest_path(data, lane, lane / PLANS_ROOT / "ready/item-a/plan.md")
    b = cli.plan_review_import_manifest_path(data, lane, lane / PLANS_ROOT / "ready/item-b/plan.md")

    assert a != b
    assert a.name.endswith(".imported.json")
    assert a.name != "plan.imported.json"


def test_an_imported_manifest_keeps_the_lane_local_name(lane):
    _write_plan(lane, "2026-08-02-x.md")

    resolved = cli.plan_review_import_manifest_path(
        _data(), lane, lane / PLANS_ROOT / "2026-08-02-x.md"
    )

    assert resolved.name == "2026-08-02-x.imported.json"


def test_a_recorded_relative_path_resolves_through_its_root(lane):
    """`plan_review_manifest_path_for_rel` rebuilt `target / plan_rel`, reinstating the lane.

    The walk carries members as recorded references, and those records outlive their plan files, so
    a rooted reference has to survive the round trip that a bare legacy one always did.
    """
    _write_plan(lane, "ready/item-a/plan.md")

    bare = cli.plan_review_manifest_path_for_rel(
        _data(), lane, f"{PLANS_ROOT}/ready/item-a/plan.md"
    )
    rooted = cli.plan_review_manifest_path_for_rel(
        _data(), lane, f"lane:{PLANS_ROOT}/ready/item-a/plan.md"
    )

    assert bare == rooted
    assert bare.name == "ready-item-a-plan.json"


def test_a_manifest_at_the_path_based_name_wins_outright(lane):
    """Once a plan has a path-based manifest, no legacy lookup should second-guess it."""
    _write_plan(lane, "ready/item-a/plan.md")
    path_based = _manifest_for(lane, "ready/item-a/plan.md").name
    _write_manifest(lane, path_based[: -len(".json")], "ready/item-a/plan.md")
    _write_manifest(lane, "plan", "ready/item-a/plan.md")

    assert _manifest_for(lane, "ready/item-a/plan.md").name == path_based
