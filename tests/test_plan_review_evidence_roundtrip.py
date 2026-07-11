"""Evidence upsert/strip must round-trip for any plan shape.

Regression for a 2026-07-10 defect: strip_plan_review_evidence removed
content from the evidence heading to the NEXT `## ` heading, so a plan whose
post-title preamble is not `## `-headed (blockquote, bold paragraphs) lost
that preamble on strip, and the finalize writer's normalized-hash guard
could never pass for such plans.
"""

PREAMBLE_PLAN = (
    "# Some Plan Title\n"
    "\n"
    "> **For agentic workers:** follow the sub-skill.\n"
    "\n"
    "**Goal:** One sentence.\n"
    "\n"
    "## Global Constraints\n"
    "\n"
    "- A constraint.\n"
)

HEADED_PLAN = (
    "# Some Plan Title\n"
    "\n"
    "## Overview\n"
    "\n"
    "Body text.\n"
)


def test_upsert_then_strip_preserves_preamble_plan(cli):
    updated = cli.upsert_plan_review_evidence(PREAMBLE_PLAN, "Evidence body.")
    assert "## Cross-Model Review Evidence" in updated
    assert cli.strip_plan_review_evidence(updated) == PREAMBLE_PLAN
    assert "**Goal:** One sentence." in cli.strip_plan_review_evidence(updated)


def test_normalized_hash_stable_across_upsert_for_preamble_plan(cli):
    before = cli.plan_content_sha256_from_text(PREAMBLE_PLAN)
    updated = cli.upsert_plan_review_evidence(PREAMBLE_PLAN, "Evidence body.")
    assert cli.plan_content_sha256_from_text(updated) == before


def test_upsert_is_idempotent_replacement_for_preamble_plan(cli):
    once = cli.upsert_plan_review_evidence(PREAMBLE_PLAN, "First body.")
    twice = cli.upsert_plan_review_evidence(once, "Second body.")
    assert "First body." not in twice
    assert "Second body." in twice
    assert cli.strip_plan_review_evidence(twice) == PREAMBLE_PLAN


def test_legacy_headed_plan_round_trip_unchanged(cli):
    updated = cli.upsert_plan_review_evidence(HEADED_PLAN, "Evidence body.")
    assert cli.strip_plan_review_evidence(updated) == HEADED_PLAN
    assert cli.plan_content_sha256_from_text(updated) == cli.plan_content_sha256_from_text(HEADED_PLAN)


def test_legacy_plan_without_end_marker_still_strips_to_next_heading(cli):
    legacy = (
        "# Title\n"
        "\n"
        "## Cross-Model Review Evidence\n"
        "\n"
        "- Old-style body without end marker\n"
        "\n"
        "## Overview\n"
        "\n"
        "Body.\n"
    )
    stripped = cli.strip_plan_review_evidence(legacy)
    assert "Cross-Model Review Evidence" not in stripped
    assert "## Overview" in stripped


def test_evidence_matcher_truncates_at_end_marker(cli):
    marker = cli.PLAN_REVIEW_EVIDENCE_END_MARKER
    section = (
        "Evidence body.\n\n" + marker
        + "\n\n> Preamble blockquote pulled in by heading-bounded extraction.\n\n**Goal:** text."
    )
    assert cli.plan_review_evidence_section_matches(section, "Evidence body.")
    assert not cli.plan_review_evidence_section_matches(section, "Different body.")
