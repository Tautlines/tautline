"""Resolving a plan reference's root token against adapter configuration (item 59 W1b).

`plan_reference.py` decides shape and deliberately knows nothing about configuration. This is the
other half of that split (R4 P1): the resolver holds the configured roots and is therefore the
only place that can say a token is *wrong*.

Two of these tests are W1's deferred deliverables, landed here because they could not exist until
`backlogProvider.planRepo` did -- `test_unknown_token_is_refused_with_a_message_naming_the_roots`
and the non-`backlog` basename coverage throughout.

**Nothing here tests the literal `backlog:`.** That spelling exists only because one fixture repo
happened to be named `backlog`; the real plan repo is `tautline-backlog`, so a fixture that only
ever proves `backlog` passes by coincidence and would leave the dogfood lane unresolved (R3 P1).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tautline_methodology import paths, plan_reference

LANE = plan_reference.LANE_ROOT


def _adapter(plan_repo: str = "", *, enabled: bool = False) -> dict:
    return {"backlogProvider": {"enabled": enabled, "planRepo": plan_repo}}


# --- the configured roots -------------------------------------------------------------------------


def test_lane_resolves_to_the_target_with_no_plan_repo_configured(tmp_path):
    assert paths.resolve_plan_root(_adapter(), tmp_path, LANE) == tmp_path


def test_configured_plan_repo_basename_becomes_a_root_token(tmp_path):
    repo = tmp_path.parent / "tautline-backlog"

    roots = paths.configured_plan_roots(_adapter(str(repo)), tmp_path)

    assert roots == {LANE: tmp_path, "tautline-backlog": repo}


def test_plan_repo_root_resolves_by_its_own_basename(tmp_path):
    repo = tmp_path.parent / "tautline-backlog"

    resolved = paths.resolve_plan_root(_adapter(str(repo)), tmp_path, "tautline-backlog")

    assert resolved == repo


def test_a_relative_plan_repo_resolves_to_a_normalized_path(tmp_path):
    """The realistic adapter value is relative (`../tautline-backlog`), not absolute.

    Resolution must normalize it away: a root carrying a literal `..` compares unequal to the same
    directory spelled directly, and W2 keys manifest identity on these paths.
    """
    expected = (tmp_path / "lane-checkout")
    expected.mkdir()

    resolved = paths.resolve_plan_root(
        _adapter("../tautline-backlog"), expected, "tautline-backlog"
    )

    assert ".." not in resolved.parts
    assert resolved == tmp_path / "tautline-backlog"


def test_a_differently_named_plan_repo_uses_that_name(tmp_path):
    # The token is the basename dynamically -- nothing blesses any particular spelling.
    repo = tmp_path.parent / "some-other-plans"

    assert paths.resolve_plan_root(_adapter(str(repo)), tmp_path, "some-other-plans") == repo


def test_resolution_works_while_the_provider_is_disabled(tmp_path):
    """This repo's own adapter has `backlogProvider.enabled: false` and external plans.

    If resolution gated on `enabled`, the framework could not dogfood the feature it ships.
    """
    repo = tmp_path.parent / "tautline-backlog"

    adapter = _adapter(str(repo), enabled=False)

    resolved = paths.resolve_plan_root(adapter, tmp_path, "tautline-backlog")

    assert resolved == repo


# --- the loud error, which is the resolver's whole job --------------------------------------------


def test_unknown_token_is_refused_with_a_message_naming_the_roots(tmp_path):
    repo = tmp_path.parent / "tautline-backlog"

    with pytest.raises(ValueError) as excinfo:
        paths.resolve_plan_root(_adapter(str(repo)), tmp_path, "wildly-unknown-repo")

    message = str(excinfo.value)
    assert "wildly-unknown-repo" in message
    assert LANE in message
    assert "tautline-backlog" in message


def test_unknown_token_names_lane_even_with_no_plan_repo_configured(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        paths.resolve_plan_root(_adapter(), tmp_path, "tautline-backlog")

    message = str(excinfo.value)
    # The lane must learn that the root it named is not configured HERE, not merely "unknown".
    assert "tautline-backlog" in message
    assert LANE in message


def test_a_parsed_but_unconfigured_token_reaches_the_resolver_not_the_parser(tmp_path):
    """The seam, end to end: the parser accepts the shape, the resolver refuses the token."""
    root, relative = plan_reference.parse_plan_reference("wildly-unknown-repo:x/y.md")

    assert (root, relative) == ("wildly-unknown-repo", "x/y.md")
    with pytest.raises(ValueError, match="wildly-unknown-repo"):
        paths.resolve_plan_root(_adapter(), tmp_path, root)


# --- the outside-target allowance, narrow in one direction ----------------------------------------


def test_a_sibling_plan_repo_is_permitted_despite_the_containment_backstop(tmp_path):
    """R3 P2: adapter paths are contained by default, so a sibling checkout is refused first.

    Without an explicit allowance the root resolver never runs at all -- the normalizer rejects the
    value before resolution. The allowance exists for exactly this key.
    """
    repo = tmp_path.parent / "tautline-backlog"

    # The same value through the default containment path is refused, which is what makes the
    # allowance necessary rather than incidental.
    with pytest.raises(ValueError, match="escapes the project root"):
        paths.configured_path(tmp_path, str(repo))

    assert paths.resolve_plan_root(_adapter(str(repo)), tmp_path, "tautline-backlog") == repo


def test_the_allowance_does_not_leak_to_the_lane_root(tmp_path):
    """Narrow in one direction: `lane` is still contained, so this is not a general escape."""
    adapter = _adapter(str(tmp_path.parent / "tautline-backlog"))

    roots = paths.configured_plan_roots(adapter, tmp_path)

    assert roots[LANE] == tmp_path
    assert Path(roots[LANE]).resolve() == tmp_path.resolve()


# --- the adapter key itself -----------------------------------------------------------------------


def test_the_adapter_key_defaults_to_unset(tmp_path):
    from tautline_methodology import cli

    normalized = cli.normalize_tracker_adapter_config(
        {"enabled": False}, cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider"
    )

    assert normalized["planRepo"] == ""


def test_the_adapter_key_survives_normalization_and_is_stripped(tmp_path):
    from tautline_methodology import cli

    normalized = cli.normalize_tracker_adapter_config(
        {"enabled": False, "planRepo": "  ../tautline-backlog  "},
        cli.DEFAULT_BACKLOG_PROVIDER,
        "backlogProvider",
    )

    assert normalized["planRepo"] == "../tautline-backlog"


def test_the_key_does_not_leak_into_the_deprecated_goal_tracker_block(tmp_path):
    """`normalize_tracker_adapter_config` is shared between both tracker blocks.

    A bare addition to its strip-list defaults `planRepo` into `goalTracker` too, which has no plan
    root and never will -- rendering a meaningless key into every adapter still carrying the
    deprecated block.
    """
    from tautline_methodology import cli

    normalized = cli.normalize_tracker_adapter_config(
        {"enabled": False}, cli.DEFAULT_GOAL_TRACKER, "goalTracker"
    )

    assert "planRepo" not in normalized


def test_the_schema_permits_the_key():
    import json
    from pathlib import Path as _Path

    schema = json.loads(
        (_Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema.json").read_text(
            encoding="utf-8"
        )
    )
    provider = schema["properties"]["backlogProvider"]["properties"]

    assert provider["planRepo"]["type"] == "string"


def test_the_schema_states_the_outside_root_allowance():
    """R3 P2 wants the allowance stated in all three places, not just honoured in code.

    This is the one adapter key whose value is EXPECTED to resolve outside the project root, so a
    reader of the schema has to be told that here -- otherwise the containment rule reads as
    universal and this key looks like a bug.
    """
    import json
    from pathlib import Path as _Path

    schema = json.loads(
        (_Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema.json").read_text(
            encoding="utf-8"
        )
    )
    description = schema["properties"]["backlogProvider"]["properties"]["planRepo"]["description"]

    assert "outside" in description.lower()
    assert "basename" in description.lower()


# --- a planRepo may not shadow the reserved literal -----------------------------------------------


def test_a_plan_repo_named_lane_is_refused(tmp_path):
    """Decision 2026-08-03: `lane` outranks a colliding basename, and the collision is loud.

    Allowing it would silently reinterpret every existing bare and `lane:` reference as pointing
    at the external repo.
    """
    with pytest.raises(ValueError, match="reserved"):
        paths.configured_plan_roots(_adapter(str(tmp_path.parent / "lane")), tmp_path)


# --- item 59 W3: the thread from --plan to a recordable reference ------------------------------


def _adapter_with_root(root_dir) -> dict:
    from tautline_methodology.cli import DEFAULT_PLANNING_ARTIFACTS

    return {
        "backlogProvider": {"planRepo": str(root_dir)},
        "planningArtifacts": dict(DEFAULT_PLANNING_ARTIFACTS),
    }


def test_the_advertised_form_reaches_the_filesystem(cli, tmp_path) -> None:
    """Codex R1 P1. `resolve_plan_path` treats its argument as a LANE-relative path, so
    `tautline-backlog:ready/x/plan.md` reached the filesystem as a literal directory named
    `tautline-backlog:ready` -- the configured-root check never saw an external plan, and the
    feature could not be used the way its own release note describes."""
    lane = tmp_path / "lane"
    (lane / "docs").mkdir(parents=True)
    backlog = tmp_path / "tautline-backlog"
    plan = backlog / "ready" / "item-a" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    resolved = cli.plan_root_resolve(
        _adapter_with_root(backlog), lane, "tautline-backlog:ready/item-a/plan.md"
    )

    assert resolved == plan.resolve(), "the root token must name the configured checkout"


def test_a_lane_relative_plan_is_unchanged(cli, tmp_path) -> None:
    """No lane behaviour moves: a value with no root token resolves exactly as it always did."""
    lane = tmp_path / "lane"
    plan = lane / "docs" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    assert cli.plan_root_resolve({}, lane, "docs/plan.md") == plan.resolve()


def test_an_external_plan_is_recordable(cli, tmp_path) -> None:
    """`path_relative_to_target` RAISES for anything outside the target, and every downstream
    surface keys on this string -- so without a root-aware rendering an external plan could be
    resolved and then not written down."""
    lane = tmp_path / "lane"
    lane.mkdir()
    backlog = tmp_path / "tautline-backlog"
    plan = backlog / "ready" / "item-a" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    recorded = cli.plan_root_relative_reference(_adapter_with_root(backlog), lane, plan)

    assert recorded == "tautline-backlog:ready/item-a/plan.md"


def test_a_lane_local_plan_records_exactly_as_before(cli, tmp_path) -> None:
    """What keeps the existing manifests and ledgers byte-identical."""
    lane = tmp_path / "lane"
    plan = lane / "docs" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    expected = "docs/plan.md"
    assert cli.plan_root_relative_reference(
        _adapter_with_root(tmp_path / "nope"), lane, plan
    ) == expected


def test_two_external_plans_no_longer_share_a_manifest(cli, tmp_path, monkeypatch) -> None:
    """The collision this whole item exists to remove. Keyed on the slug logic directly rather
    than through a full adapter: `plan_root_containment_dirs` is the seam the fix changed, and
    reconstructing an entire adapter here would test the fixture, not the behaviour."""
    lane = tmp_path / "lane"
    lane.mkdir()
    backlog = tmp_path / "tautline-backlog"
    monkeypatch.setattr(
        cli, "plan_root_containment_dirs", lambda d, t: {"lane": lane, "tautline-backlog": backlog}
    )

    slugs = set()
    for item in ("item-a", "item-b"):
        plan = backlog / "ready" / item / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# plan\n", encoding="utf-8")
        slugs.add(cli.plan_review_manifest_identity({}, lane, plan))

    assert len(slugs) == 2, f"two plans must not map to one manifest: {slugs}"
    assert all("item" in s for s in slugs), "and each names the item it belongs to"


def test_an_external_plan_can_be_finalized_and_assigned(cli, tmp_path, monkeypatch) -> None:
    """Codex R2. The thread has to reach the END of the flow, not just its start. Two surfaces
    still derived a lane-relative string: `plan-finalization-precheck` compared it against a
    manifest holding a `<root>:<path>` reference, so a reviewed external plan could never pass the
    gate it exists to reach; and `goal-assignment` refused before its widened check ran, leaving
    the builder handoff unusable for the very workflow this item adds."""
    import inspect

    precheck = inspect.getsource(cli.plan_finalization_precheck_errors)
    assert "plan_root_relative_reference(data, target, plan_path)" in precheck, (
        "the reader must name a plan the way the writer did"
    )
    assert "expected_plan_rel = path_relative_to_target" not in precheck

    assignment = inspect.getsource(cli.goal_assignment)
    assert "plan_root_resolve(data, target, args.plan)" in assignment
    assert "plan_is_under_a_configured_root(data, target, plan_path)" in assignment
    assert "path_is_under(plan_path, target)" not in assignment, (
        "the narrow containment guard is what made the handoff unusable"
    )


def test_no_plan_path_is_resolved_lane_only_anywhere(cli) -> None:
    """THE CLASS, pinned. Four review rounds each found this defect one surface further along --
    and the sweep that fixed fourteen sites still missed `predecessor_path` and `candidate_path`,
    because it matched a VARIABLE NAME rather than a kind of value. A predecessor and a successor
    candidate are plans too.

    This asserts the property directly: no plan-shaped path is resolved or relativized lane-only,
    anywhere in the module. The two exemptions are inside `plan_root_relative_reference` itself,
    which is where the lane-only call legitimately lives as its own fallback.
    """
    import inspect
    import re

    source = inspect.getsource(cli)
    fallback = inspect.getsource(cli.plan_root_relative_reference)

    pattern = re.compile(
        r"(?:path_relative_to_target|resolve_plan_path)\(\s*target,\s*"
        r"([A-Za-z_][A-Za-z_0-9.]*)\s*\)"
    )
    plan_shaped = re.compile(r"plan|candidate|predecessor", re.IGNORECASE)

    offenders = sorted(
        {
            m.group(0)
            for m in pattern.finditer(source)
            if plan_shaped.search(m.group(1)) and m.group(0) not in fallback
        }
    )

    assert not offenders, (
        "every plan path must resolve through plan_root_resolve / "
        f"plan_root_relative_reference; still lane-only: {offenders}"
    )
