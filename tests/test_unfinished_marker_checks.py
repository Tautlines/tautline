"""Refusals that name what tripped them.

Item 29 (plan-precheck marker false positive) and item 19 (review-note placeholder check) are the
same defect: a fail-closed control whose refusal could not be acted on. The plan check matched four
words anywhere on a line and rejected a finished plan over `**Placeholder scan:** clean.` -- a
heading the superpowers writing-plans template tells the author to write -- while saying only
"plan contains stub/TODO markers". The note check rejected every angle bracket, so a note could not
quote the very token the change removed, and said only "must not be a placeholder token".
"""

FINISHED_PLAN_LINE = "**Placeholder scan:** clean."


def test_a_report_about_markers_is_not_a_marker(cli):
    """The live false positive. The word appears in a heading that RESOLVES it."""
    assert cli.plan_unfinished_marker_hits(FINISHED_PLAN_LINE) == []
    assert cli.plan_unfinished_marker_hits("No placeholders remain in this plan.") == []


def test_genuine_markers_are_still_caught(cli):
    """The check still has to earn its keep: these are unwritten work, not reports about it."""
    markers = ("- Owner: TBD", "TODO: write the migration step", "Set to <placeholder>")
    for text in markers:
        assert cli.plan_unfinished_marker_hits(text), f"missed a real marker in {text!r}"


def test_quoted_markers_are_exempt(cli):
    """A plan that DISCUSSES these markers -- this repo's own plans do -- is not unfinished."""
    assert cli.plan_unfinished_marker_hits("never write a bare `TODO` in a plan") == []
    assert cli.plan_unfinished_marker_hits("```\nTODO: sample\n```") == []


def test_the_refusal_names_the_line_and_the_word(cli, tmp_path):
    """The point of the item. On a long plan the old message left the remedy derivable only by
    reimplementing the regex by hand."""
    plan = tmp_path / "plan.md"
    body = ["# Plan", "", "## Goal", "Do the work." + " padding" * 200, ""]
    body += ["## Non-Goals", "None.", "## Assumptions", "None.", "## Dependencies", "None."]
    body += ["## Acceptance", "tests: test_thing", "## Risks", "None.", "## Decisions", "None."]
    body += ["## Done", "merged.", "", "- Owner: TBD"]
    plan.write_text("\n".join(body), encoding="utf-8")

    errors = [e for e in cli.validate_plan_substance(plan) if "unfinished-work" in e]

    assert errors, "a real marker must still be refused"
    assert "line " in errors[0], "the refusal must name the line"
    assert "TBD" in errors[0], "the refusal must quote what matched"


def test_review_note_may_quote_a_token_it_is_reporting(cli):
    """Item 19's live block: the note quoted the placeholder the change removed."""
    note = (
        "Native/Superpowers review of the current assembled diff; no blockers found. "
        "It removes the literal `<reason>` token from the remedy text."
    )
    assert not any("unfilled token" in error for error in cli.native_review_note_errors(note))


def test_review_note_still_rejects_an_unfilled_token_and_names_it(cli):
    note = (
        "Native/Superpowers review of the current assembled diff; no blockers found. "
        "Reason: <fill in later>"
    )
    errors = [e for e in cli.native_review_note_errors(note) if "unfilled token" in e]

    assert errors
    assert "fill in later" in errors[0], "the refusal must quote the offending token"


def test_placeholder_only_line_is_flagged_but_prose_is_not(cli):
    """The narrowed shape: only a line whose whole VALUE is the word counts."""
    assert cli.plan_unfinished_marker_hits("Owner: placeholder")
    assert cli.plan_unfinished_marker_hits("- stub")
    assert cli.plan_unfinished_marker_hits("`<workspace>` placeholder substitution") == []
    assert cli.plan_unfinished_marker_hits("rounds produced only test-stub bugs") == []


def test_the_scan_is_linear_on_a_large_plan(cli):
    """Regression guard. The obvious regex for "optional label, then only this word" nests
    quantifiers and backtracks catastrophically: on a 113k-character plan it ran for over three
    minutes before being killed. This check runs inside plan finalization, so a pathological
    pattern here hangs the gate rather than failing it."""
    import time

    body = "prose about placeholder substitution and stub helpers " * 40
    plan = ("## Section\n" + body + "\n") * 200
    started = time.monotonic()
    cli.plan_unfinished_marker_hits(plan)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"marker scan took {elapsed:.1f}s on a {len(plan)}-char plan"


def test_checklist_and_numbered_placeholders_are_caught(cli):
    """Plans use checkboxes and numbered lists for open items. Stripping only unordered bullets
    let those through, which the pre-change gate caught (0.27.0 implementation review R1 P2)."""
    for line in ("- [ ] placeholder", "1. stub", "2) placeholder", "- [x] stub"):
        assert cli.plan_unfinished_marker_hits(line), f"missed a list placeholder in {line!r}"


def test_a_bare_marker_is_flagged_even_when_the_line_reports_it_as_resolved(cli):
    """No negation heuristic. Earlier revisions tried to exempt lines that RESOLVE a marker -- "No
    TBD.", "No TODO or TBD markers remain" -- and review found a new hole in every attempt across
    four rounds: adjacent-word scoping flagged the second marker in a list, clause-wide scoping
    let "No TODO, but TBD owner missing" through, and so on. Each fix grew the heuristic and moved
    the hole. It was asking a regex to parse English.

    So it is gone, and the cost is small: the case that motivated all of this --
    `**Placeholder scan:** clean.` -- passes on the SHAPE rules alone, because bare
    placeholder/stub are no longer matched as words at all. What remains is that a plan writing a
    bare TODO/TBD in a resolution summary is asked to backtick it, by a refusal that names the
    line, quotes the word, and says backticks are exempt. Filed as its own item rather than
    refined a fifth time.
    """
    assert cli.plan_unfinished_marker_hits("No TBD.")
    assert cli.plan_unfinished_marker_hits("No TODO, but TBD owner missing")
    # Backticking is the documented escape, and it works.
    assert cli.plan_unfinished_marker_hits("`No TBD.`") == []
    # The case the whole item started from needs no negation handling at all.
    assert cli.plan_unfinished_marker_hits("**Placeholder scan:** clean.") == []


def test_markdown_labelled_placeholders_are_caught(cli):
    """0.27.0 implementation review R1 (P2). Plans label fields in the template's bold style, so
    `**Owner:** placeholder` left a trailing `**` on the value and the comparison missed a genuine
    unfinished entry the old word-anywhere scan caught. Markup normalization is bounded, unlike
    the negation heuristic this rule deliberately no longer carries (item 36)."""
    for line in ("**Owner:** placeholder", "- **Status:** stub", "_Owner_: placeholder"):
        assert cli.plan_unfinished_marker_hits(line), f"missed a labelled placeholder in {line!r}"
    assert cli.plan_unfinished_marker_hits("**Placeholder scan:** clean.") == []
