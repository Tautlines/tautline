"""The rooted plan reference: `<root>:<relative-path>`, parsed for SHAPE only.

Item 59 W1 of the reviewed plan (`2026-08-02-plan-root-schema.md`). A recorded plan reference has
until now been a bare relative path whose root was implied by whoever read it -- which is why
`ready/item-a/plan.md` and `ready/item-b/plan.md` both slugged to the same manifest and overwrote
each other's review evidence.

Two constraints drive every test here.

**Legacy strings must not change meaning.** Every manifest written before this release holds a
bare relative path meaning "relative to this lane". If a colon anywhere in a string could promote
its prefix to a root token, then a legacy path that happens to contain a colon would be silently
reinterpreted the day this ships. Silent reinterpretation of already-recorded evidence is the
worst failure available here, so the token shape is deliberately narrow: no separator, non-empty.

**The parser holds no allowlist (R4 P1).** It decides shape; the configured resolver decides
validity. A fixed set of roots here could only be wrong -- hardcoding `backlog` rejects the real
`tautline-backlog:` reference, which is the single spelling this feature exists to support. So
these tests deliberately parse tokens the parser has never heard of, and assert it does NOT judge
them. Rejection of unknown tokens is W1b's resolver, tested there, where the configuration to
judge them exists.
"""
from __future__ import annotations

import pytest

from tautline_methodology import plan_reference

LANE = plan_reference.LANE_ROOT


# --- legacy compatibility: a bare string is lane-relative, unchanged ------------------------------


def test_bare_relative_path_reads_as_lane():
    assert plan_reference.parse_plan_reference("docs/superpowers/plans/2026-08-02-item.md") == (
        LANE,
        "docs/superpowers/plans/2026-08-02-item.md",
    )


def test_bare_path_containing_a_colon_stays_lane_relative():
    # The prefix `ready/weird` contains a separator, so it cannot be a root token. Were this to
    # split, a legacy path would silently change meaning -- the exact failure this shape prevents.
    assert plan_reference.parse_plan_reference("ready/weird:name/plan.md") == (
        LANE,
        "ready/weird:name/plan.md",
    )


def test_bare_absolute_path_stays_lane_relative_for_the_parser_to_report():
    # Absoluteness is a containment question, and containment is the resolver's job. The parser
    # reports shape without judging it.
    assert plan_reference.parse_plan_reference("/etc/passwd") == (LANE, "/etc/passwd")


# --- the rooted form ------------------------------------------------------------------------------


def test_rooted_reference_splits_into_token_and_relative_path():
    assert plan_reference.parse_plan_reference("backlog:ready/2026-08-02-item/plan.md") == (
        "backlog",
        "ready/2026-08-02-item/plan.md",
    )


def test_real_plan_repo_basename_is_not_special_cased():
    # The real repo is `tautline-backlog`, not `backlog`. A fixture that only ever proves `backlog`
    # passes by coincidence; the plan says so explicitly.
    assert plan_reference.parse_plan_reference("tautline-backlog:ready/item/plan.md") == (
        "tautline-backlog",
        "ready/item/plan.md",
    )


def test_parser_accepts_a_token_it_has_never_heard_of():
    # R4 P1: no allowlist in the leaf. Judging this token is the resolver's job.
    assert plan_reference.parse_plan_reference("wildly-unknown-repo:x/y.md") == (
        "wildly-unknown-repo",
        "x/y.md",
    )


def test_only_the_first_colon_separates():
    assert plan_reference.parse_plan_reference("backlog:ready/odd:name.md") == (
        "backlog",
        "ready/odd:name.md",
    )


def test_explicit_lane_token_is_accepted_and_means_the_lane():
    assert plan_reference.parse_plan_reference("lane:docs/plans/x.md") == (LANE, "docs/plans/x.md")


# --- shapes that are not references at all --------------------------------------------------------


def test_empty_token_is_not_a_root_and_stays_lane_relative():
    assert plan_reference.parse_plan_reference(":x/y.md") == (LANE, ":x/y.md")


def test_rooted_reference_with_an_empty_relative_half_is_refused():
    with pytest.raises(ValueError, match="relative path"):
        plan_reference.parse_plan_reference("backlog:")


def test_blank_text_is_refused():
    with pytest.raises(ValueError, match="empty"):
        plan_reference.parse_plan_reference("   ")


# --- render, and the round trip -------------------------------------------------------------------


def test_render_emits_the_rooted_form():
    assert (
        plan_reference.render_plan_reference("tautline-backlog", "ready/item/plan.md")
        == "tautline-backlog:ready/item/plan.md"
    )


def test_render_emits_the_rooted_form_for_the_lane_too():
    # v2 writes the root explicitly even for the lane; v1 bare strings still READ as lane above.
    assert plan_reference.render_plan_reference(LANE, "docs/x.md") == "lane:docs/x.md"


@pytest.mark.parametrize(
    "root,relative",
    [
        (LANE, "docs/superpowers/plans/x.md"),
        ("backlog", "ready/item/plan.md"),
        ("tautline-backlog", "ready/2026-08-02-item/plan.md"),
        ("some-other-repo", "nested/deep/path/plan.md"),
        ("backlog", "ready/odd:name.md"),
    ],
)
def test_round_trip(root, relative):
    assert plan_reference.parse_plan_reference(
        plan_reference.render_plan_reference(root, relative)
    ) == (root, relative)


def test_v1_string_read_then_rewritten_becomes_the_v2_form_and_means_the_same():
    """The upgrade path W2's migration depends on, pinned as a contract.

    Composition test over units already covered above: it adds no production code, it fixes the
    relationship between them so a later change cannot quietly break the v1 -> v2 conversion.
    """
    v1 = "docs/superpowers/plans/2026-08-02-item.md"

    parsed = plan_reference.parse_plan_reference(v1)
    v2 = plan_reference.render_plan_reference(*parsed)

    assert v2 == f"lane:{v1}"
    assert plan_reference.parse_plan_reference(v2) == parsed


def test_rewriting_a_v2_reference_is_idempotent():
    v2 = "tautline-backlog:ready/item/plan.md"

    once = plan_reference.render_plan_reference(*plan_reference.parse_plan_reference(v2))
    twice = plan_reference.render_plan_reference(*plan_reference.parse_plan_reference(once))

    assert once == v2
    assert twice == v2


def test_render_refuses_a_root_containing_a_separator():
    with pytest.raises(ValueError, match="separator"):
        plan_reference.render_plan_reference("a/b", "x.md")


def test_render_refuses_a_root_containing_a_colon():
    with pytest.raises(ValueError, match="colon"):
        plan_reference.render_plan_reference("a:b", "x.md")


def test_render_refuses_an_empty_root():
    with pytest.raises(ValueError, match="empty"):
        plan_reference.render_plan_reference("", "x.md")


def test_render_refuses_an_empty_relative_path():
    with pytest.raises(ValueError, match="relative path"):
        plan_reference.render_plan_reference("backlog", "")
