"""The composed goal states THIS plan's bar.

Before this, `compose_done_clause` read only the adapter's definition of
done, so every goal composed from every plan carried the same generic process sentence and the
plan's own acceptance criteria appeared nowhere -- the operator asked for a goal focused on
acceptance criteria and got the definition of done.

The floor is RETAINED behind the criteria on purpose: it is what closes the measured stop at
90-95%, and a goal that states only a plan's criteria stops being a handoff.
"""
import pytest

from tautline_methodology import goal_assignment as ga


PLAN_WITH_CRITERIA = """
# Ship the widget pipeline

## Workstreams
### W1 — build the ingest adapter `model-tier: standard`
### W2 — wire the retry queue `model-tier: deep`

## Acceptance criteria

- **AC-1 (record integrity).** A run produces a record with an exit code,
  a commit and a tree digest. *Verified by:* `test_record_integrity`.
- **AC-2 (never a silent pass).** A missing report is an explicit non-zero error.
- [x] AC-0 (already satisfied). The spike landed last week.

## Risks
- something else entirely
"""

PLAN_WITHOUT_CRITERIA = """
# Ship the widget pipeline

## Workstreams
- Build the ingest adapter
- Wire the retry queue
"""


def _compose(**overrides):
    kwargs = {
        "command": "/goal",
        "title": "Ship the widget pipeline",
        "plan_ref": "docs/plans/widget.md",
        "milestones": (),
        "criteria": (),
    }
    kwargs.update(overrides)
    return ga.compose_goal_assignment(**kwargs)


def _minimum_limit(**kwargs):
    """The smallest limit that composes at all -- i.e. the irreducible core's own length.

    Derived, never hard-coded: a magic budget in a test is really an assertion about the size
    of the core, so it starts passing for the wrong reason the moment anything joins or leaves
    that core (a directive, a summary line), and it does so silently.
    """
    low, high = 1, ga.GOAL_ASSIGNMENT_CHAR_LIMIT
    while low < high:
        mid = (low + high) // 2
        try:
            _compose(limit=mid, **kwargs)
        except ValueError:
            low = mid + 1
        else:
            high = mid
    return low


# --- extraction: the plan's own named criteria ------------------------------------------------


def test_acceptance_criteria_come_from_the_acceptance_section():
    assert ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA) == [
        "AC-1 (record integrity). A run produces a record with an exit code, a commit and a "
        "tree digest. *Verified by:* `test_record_integrity`.",
        "AC-2 (never a silent pass). A missing report is an explicit non-zero error.",
    ]


def test_a_criterion_wrapped_across_lines_is_not_truncated_at_the_first_line():
    """A real criterion wraps; reading only the bullet line states half a bar and calls it
    the bar."""
    first = ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA)[0]
    assert "a commit and a tree digest" in first


def test_a_satisfied_checkbox_criterion_is_not_a_bar_to_restate():
    criteria = ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA)
    assert all("already satisfied" not in item for item in criteria)


def test_the_section_ends_at_the_next_heading_of_its_own_level():
    assert all(
        "something else entirely" not in item
        for item in ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA)
    )


def test_numbered_criteria_are_read_like_bulleted_ones():
    plan = """
# Plan
## Acceptance criteria
1. A composed goal states the plan's own criteria.
2. A plan with none still composes.
"""
    assert ga.plan_acceptance_criteria(plan) == [
        "A composed goal states the plan's own criteria.",
        "A plan with none still composes.",
    ]


def test_a_criterion_continues_after_a_fenced_example():
    """A fence does not end the criterion it sits inside. Flushing at the opening delimiter
    dropped everything after the example -- so "and exits with status 0" vanished and the
    composed clause silently stated a weaker bar than the plan does."""
    plan = (
        "# P\n## Acceptance criteria\n"
        "- the command prints the record:\n\n  ```\n  record: ok\n  ```\n\n"
        "  and exits with status 0.\n"
        "- the second criterion holds.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == [
        "the command prints the record: and exits with status 0.",
        "the second criterion holds.",
    ]


def test_a_hash_comment_inside_fenced_code_does_not_end_the_criteria_section():
    plan = """
# Plan
## Acceptance criteria
- The record is written.
```python
# not a heading, and not a criterion
```
- The record is verified.
"""
    assert ga.plan_acceptance_criteria(plan) == [
        "The record is written.",
        "The record is verified.",
    ]


def test_a_numbered_section_heading_is_still_the_acceptance_section():
    """Three plans in this repo head it `## 6. Acceptance (independently testable)`. Anchored
    straight at the word, the parser returned nothing and the CLI reported `0 of 0` -- a
    parser finding no section reading exactly like a plan that named none."""
    plan = """
# Plan
## 6. Acceptance (independently testable)
- The record is written.
"""
    assert ga.plan_acceptance_criteria(plan) == ["The record is written."]
    assert ga.plan_acceptance_criteria_heading(plan) == "6. Acceptance (independently testable)"


def test_an_empty_result_says_which_kind_of_empty_it_is():
    """`0 of 0` is two different facts wearing one string: a plan that names no criteria, and
    a plan whose section this parser could not read. Only the second wants someone to look."""
    assert ga.plan_acceptance_criteria_heading(PLAN_WITHOUT_CRITERIA) is None
    unreadable = "# Plan\n## Acceptance criteria\n\n| id | bar |\n|---|---|\n| AC-1 | it holds |\n"
    assert ga.plan_acceptance_criteria(unreadable) == []
    assert ga.plan_acceptance_criteria_heading(unreadable) == "Acceptance criteria"


def test_an_indented_only_list_is_still_the_criteria_list():
    plan = "# Plan\n## Acceptance criteria\n  - AC-1 alpha holds.\n  - AC-2 beta holds.\n"
    assert ga.plan_acceptance_criteria(plan) == ["AC-1 alpha holds.", "AC-2 beta holds."]


def test_the_continuation_of_a_satisfied_criterion_is_not_promoted_to_a_criterion():
    """A `- [x]` entry is skipped, and its wrapped remainder used to fall through as a prose
    item -- a fragment of already-satisfied work presented as this work's bar."""
    plan = """
# Plan
## Acceptance criteria
- [x] AC-1 done
  and its continuation line
  - and its sub-bullet
- [x] AC-2 done
"""
    assert ga.plan_acceptance_criteria(plan) == []


@pytest.mark.parametrize(
    "criterion",
    [
        "`docs/product/**` is excluded from the export",
        "`plugins/**/plugin.json` is bumped in lockstep",
        "2**32 is the ceiling",
        "2**32 and 3**4 both hold",
    ],
)
def test_a_literal_double_star_is_not_markdown_bold(criterion):
    """A blanket `**` strip rewrites a glob or an exponent into a different requirement, and
    criteria in this repo's own plans carry both."""
    assert ga._criterion_phrase(criterion) == criterion


def test_markdown_bold_is_still_removed():
    assert ga._criterion_phrase("**AC-1 (integrity).** A run produces a record") == (
        "AC-1 (integrity). A run produces a record"
    )


def test_a_blank_separated_continuation_stays_with_its_criterion():
    """A blank line does not end a criterion. Flushing there dropped the second paragraph of
    an active criterion and promoted a satisfied one's detail into a bar of its own."""
    plan = (
        "# P\n## Acceptance criteria\n"
        "- AC-1 first paragraph\n\n  second paragraph is also required\n- AC-2 other\n"
    )
    assert ga.plan_acceptance_criteria(plan) == [
        "AC-1 first paragraph second paragraph is also required",
        "AC-2 other",
    ]
    satisfied = (
        "# P\n## Acceptance criteria\n"
        "- [x] AC-1 done\n\n  detail belonging to the completed item\n- [x] AC-2 done\n"
    )
    assert ga.plan_acceptance_criteria(satisfied) == []


def test_a_section_that_exists_but_reads_empty_does_not_borrow_another_section():
    """Answering from `Completion definition` would hide the section a human should look at
    behind an answer that looks fine -- the failure mode the heading signal exists to end."""
    plan = (
        "# P\n## Acceptance criteria\n| id | bar |\n|---|---|\n\n"
        "## Completion definition\nEverything merged.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == []
    assert ga.plan_acceptance_criteria_heading(plan) == "Acceptance criteria"


def test_the_adapters_configured_acceptance_heading_is_honored():
    """`planAcceptance.acHeadings` already tells plan finalization where a project's criteria
    live; a composer with its own hardcoded list reports 'no acceptance section' for the very
    section that gate just graded. Union, not replacement."""
    custom = "# P\n## Validation Requirements\n- the pipeline is green.\n"
    assert ga.plan_acceptance_criteria(custom) == []
    assert ga.plan_acceptance_criteria(custom, ["validation requirements"]) == [
        "the pipeline is green."
    ]
    standard = "# P\n## Acceptance criteria\n- standard still read.\n"
    assert ga.plan_acceptance_criteria(standard, ["validation requirements"]) == [
        "standard still read."
    ]


def test_completion_definition_is_the_fallback_and_only_the_fallback():
    """Plans that state their bar under `Completion definition` are not made to go without;
    plans carrying both are not made to state it twice."""
    fallback_only = """
# Plan
## Completion definition
Both PRs merged to `experimental` with the criteria proven by tests in CI.
"""
    assert ga.plan_acceptance_criteria(fallback_only) == [
        "Both PRs merged to `experimental` with the criteria proven by tests in CI."
    ]

    both = PLAN_WITH_CRITERIA + "\n## Completion definition\nEverything merged.\n"
    assert all("Everything merged" not in item for item in ga.plan_acceptance_criteria(both))


def test_a_lead_in_line_does_not_pose_as_a_criterion():
    plan = """
# Plan
## Acceptance criteria
All of the following must hold:
- The record is written.
"""
    assert ga.plan_acceptance_criteria(plan) == ["The record is written."]


def test_a_plan_with_no_criteria_section_yields_none():
    assert ga.plan_acceptance_criteria(PLAN_WITHOUT_CRITERIA) == []
    assert ga.plan_acceptance_criteria("# Plan\n\nJust prose.\n") == []


# --- binding: the goal states them ------------------------------------------------------------


def test_a_composed_goal_states_the_plans_own_acceptance_criteria():
    criteria = ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA)
    text, meta = _compose(criteria=criteria)
    assert "AC-1 (record integrity). A run produces a record with an exit code" in text
    assert "AC-2 (never a silent pass). A missing report is an explicit non-zero error" in text
    assert meta["criteria_total"] == 2
    assert meta["criteria_included"] == 2
    assert meta["criteria_omitted"] == 0


def test_the_definition_of_done_floor_is_retained_behind_the_criteria():
    """The floor is what closes the 90-95% stop; a goal stating only a plan's criteria stops
    being a handoff."""
    text, _meta = _compose(criteria=ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA))
    for phrase in (
        ga.GOAL_ASSIGNMENT_DONE_PHRASES["tests_green"],
        ga.GOAL_ASSIGNMENT_DONE_PHRASES["review_clean"],
        ga.GOAL_ASSIGNMENT_DONE_PHRASES["pr_handed_off"],
    ):
        assert phrase in text


def test_a_plan_with_no_criteria_composes_the_generic_bar_unchanged():
    text, meta = _compose(criteria=())
    assert ga.compose_done_clause() in text
    assert "Completion means those criteria" not in text
    assert "acceptance criteria" not in text
    assert meta["criteria_total"] == 0


def test_the_provenance_tail_is_dropped_but_the_criterion_is_not():
    phrase = ga._criterion_phrase(
        "**AC-3 (non-authorable).** A mismatched sha256 classifies `invalid`. "
        "*Verified by:* `test_mismatched_sha256`"
    )
    assert phrase == "AC-3 (non-authorable). A mismatched sha256 classifies `invalid`"


@pytest.mark.parametrize(
    "criterion",
    [
        "The record is verified by its embedded sha256 and attached.",
        "the run is verified by: the sha and the exit code",
        "`product_dev_mode_active` is NEVER read (scoping is mode-independent) — verified by grep",
    ],
)
def test_prose_that_merely_says_verified_by_keeps_its_whole_sentence(criterion):
    """Measured against the repo's own plans, a loose pattern amputated 5 real criteria. A
    goal stating a truncated, unfalsifiable bar is the failure this change exists to end."""
    assert ga._criterion_phrase(criterion) == criterion.rstrip(".")


def test_a_criterion_keeps_the_case_and_the_leading_dash_it_was_written_with():
    """The goal QUOTES the plan's bar. `-1`, `--workstream`, `Tautline` and `Python 3.12` all
    mean what their spelling says they mean, and a composer that rewrote them would state
    something the plan does not say."""
    for criterion in (
        "-1 exit code is preserved",
        "--workstream WS1 emits one goal",
        "Tautline refuses the release",
        "Python 3.12 is the floor",
        "AC-4 (report-only). Exit codes hold",
    ):
        assert ga._criterion_phrase(criterion) == criterion


# --- elasticity: criteria degrade, they never vanish -------------------------------------------


def test_over_budget_criteria_degrade_to_a_counted_summary_rather_than_vanishing():
    criteria = [f"criterion {i} states a long falsifiable thing " + "x" * 160 for i in range(24)]
    text, meta = _compose(criteria=criteria, limit=ga.goal_assignment_authoring_limit())
    assert len(text) <= ga.goal_assignment_authoring_limit()
    assert meta["criteria_total"] == 24
    assert meta["criteria_omitted"] > 0
    assert f"(+{meta['criteria_omitted']} more acceptance criteria in the plan)" in text


def test_no_budget_ever_hides_that_the_plan_named_acceptance_criteria():
    """The count is core, exactly as the milestone count is: a budget that admits no full
    criterion must still say the plan named them, or the goal silently reverts to the generic
    bar and reads as though there were none."""
    criteria = [f"criterion {i} " + "y" * 240 for i in range(6)]
    bare, _meta = _compose(criteria=criteria, limit=ga.GOAL_ASSIGNMENT_CHAR_LIMIT)
    floor = len(_compose(criteria=criteria, limit=len(bare))[0])
    for limit in range(floor, floor + 900, 13):
        text, meta = _compose(criteria=criteria, limit=limit)
        assert len(text) <= limit
        assert meta["criteria_included"] + meta["criteria_omitted"] == 6
        if meta["criteria_omitted"]:
            assert ("more acceptance criteria in the plan" in text) or (
                "all 6 acceptance criteria named in the plan are met" in text
            )


def test_when_no_criterion_fits_the_clause_still_names_the_count():
    criteria = ["criterion %d " % i + "z" * 200 for i in range(4)]
    floor = _minimum_limit(criteria=criteria, milestones=["W1", "W2"])
    text, meta = _compose(criteria=criteria, milestones=["W1", "W2"], limit=floor + 40)
    assert meta["criteria_included"] == 0
    assert "all 4 acceptance criteria named in the plan are met" in text


def test_criteria_outrank_the_milestone_list_for_the_leftover_budget():
    """The milestone list indexes the plan; the criteria state the bar. A goal that indexes a
    plan but cannot state its bar is the generic goal this binding replaces."""
    criteria = ["the ingest adapter refuses a malformed record with a named error"]
    milestones = [f"Workstream {i} " + "m" * 120 for i in range(8)]
    text, meta = _compose(criteria=criteria, milestones=milestones, limit=1500)
    assert meta["criteria_included"] == 1
    assert "refuses a malformed record" in text
    assert meta["milestones_included"] < 8
    assert "are in the plan" in text or "more in the plan" in text


def test_a_composed_goal_with_criteria_passes_its_own_checker():
    """Including a criterion naming a dotted file, which real criteria always do."""
    criteria = [
        "`scripts/test.sh` passes on the branch tip with the pass count stated as a number",
        "the renderer emits `cli.py` unchanged",
    ]
    text, _meta = _compose(criteria=criteria, milestones=["Build ingest"])
    assert ga.goal_assignment_issues(text, plan_ref="docs/plans/widget.md") == []


def test_the_core_too_large_refusal_counts_the_criteria_summary():
    criteria = [f"criterion {i}" for i in range(5)]
    bare, _meta = _compose()
    with pytest.raises(ValueError):
        _compose(criteria=criteria, limit=len(bare))


# --- the parallel directive is core, not tail ---------------------------------------------------


def test_every_composed_goal_carries_the_parallel_directive():
    for kwargs in (
        {},
        {"milestones": ["Build ingest", "Wire retries"]},
        {"criteria": ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA)},
        {"conditions": []},
    ):
        text, _meta = _compose(**kwargs)
        assert ga.GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE.strip() in text, kwargs


def test_the_directive_names_the_batch_the_worktree_and_the_model_tier():
    directive = ga.GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE
    assert "concurrent subagents in a single batch" in directive
    assert "rather than working them in sequence" in directive
    assert "its own worktree" in directive
    assert "`model-tier`" in directive


def test_the_directive_survives_a_budget_that_drops_every_milestone():
    units = ["Workstream %d " % i + "w" * 200 for i in range(9)]
    floor = _minimum_limit(milestones=units)
    for limit in range(floor, floor + 400, 9):
        text, _meta = _compose(milestones=units, limit=limit)
        assert ga.GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE.strip() in text
        assert len(text) <= limit


def test_the_core_too_large_refusal_counts_the_directive():
    """A limit that would fit the core WITHOUT the directive must refuse, not emit a goal
    missing it -- the fail-closed edge has to move with the core it measures."""
    text, _meta = _compose()
    with pytest.raises(ValueError):
        _compose(limit=len(text) - 1)
    with pytest.raises(ValueError) as excinfo:
        _compose(limit=len(text) - len(ga.GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE))
    assert "goal assignment core is" in str(excinfo.value)


# --- the composed shape is otherwise unchanged --------------------------------------------------


def test_the_composed_shape_is_otherwise_unchanged():
    text, meta = _compose(
        criteria=ga.plan_acceptance_criteria(PLAN_WITH_CRITERIA),
        milestones=["Build ingest", "Wire retries"],
    )
    assert "\n" not in text
    assert "  " not in text
    assert not text.startswith((" ", "\t"))
    assert "The human is away for the duration" in text
    assert "Work autonomously: use best judgment" in text
    assert "Proof: `tautline goal-status --target .`." in text
    assert len(text) <= ga.GOAL_ASSIGNMENT_CHAR_LIMIT
    assert meta["char_count"] == len(text)


def test_the_done_clause_signature_stays_usable_by_its_other_caller():
    """`goal-condition` composes the same bar from the condition set alone; adding criteria
    must not change what that surface prints."""
    assert ga.compose_done_clause(["tests_green"]) == (
        f" Done when: {ga.GOAL_ASSIGNMENT_DONE_PHRASES['tests_green']}."
    )


# --- end to end, through the CLI ----------------------------------------------------------------


def test_a_goal_composed_from_a_real_plan_states_that_plans_criteria(run_cli):
    """AC-2 end to end: the composer reads the plan, not just the adapter."""
    plan = "docs/superpowers/plans/2026-07-27-test-execution-evidence-v2.md"
    result = run_cli("goal-assignment", "--target", ".", "--plan", plan, "--allow-unfinalized")
    assert result.returncode == 0, result.stderr
    assert "goal_assignment_acceptance_criteria: 7 of 7 included" in result.stdout
    assert "record integrity" in result.stdout


def test_a_configured_heading_ending_in_punctuation_still_binds():
    """`planAcceptance.acHeadings` is matched by the finalization gate exactly, but the
    composer escaped it and appended `\\b` -- and a word boundary after `)` needs a word
    character that a heading's end does not have. A project whose graded section is
    `Definition of Ready (AC)` was told its plan names no criteria."""
    plan = "# P\n## Definition of Ready (AC)\n- the gate exits 0.\n- the record is committed.\n"
    assert ga._criteria_scan(plan, ["Definition of Ready (AC)"]) == (
        "Definition of Ready (AC)",
        ["the gate exits 0.", "the record is committed."],
    )


def test_an_exact_criteria_heading_beats_a_generic_one_above_it():
    """The scanner took the FIRST heading starting with "acceptance", so `## Acceptance
    mapping` above `## Acceptance criteria` won and the goal stated a mapping row as the
    plan's bar. A goal that confidently states criteria that are not the plan's is worse than
    one that states none, so an exact heading anywhere beats a generic prefix match earlier."""
    plan = (
        "# P\n"
        "## Acceptance mapping\n"
        "- this row maps a control to a test, it is NOT the bar.\n"
        "## Acceptance criteria\n"
        "- the gate exits 0 and the record is committed.\n"
    )
    assert ga._criteria_scan(plan) == (
        "Acceptance criteria",
        ["the gate exits 0 and the record is committed."],
    )


def test_a_generic_acceptance_heading_still_binds_when_it_is_the_only_one():
    """Preferring the exact heading must not make the composer blind to the plans that only
    have a generic one -- three in-repo plans use `Acceptance (independently testable)`."""
    assert ga._criteria_scan("# P\n## Acceptance (independently testable)\n- alpha holds.\n") == (
        "Acceptance (independently testable)",
        ["alpha holds."],
    )


def test_an_indented_code_block_does_not_end_the_criteria_section():
    """Heading detection matched the STRIPPED line, so `    # rebuild the index` inside an
    indented example read as a heading and ended the section there. Every criterion below it
    was dropped while the report still said "N of N included" -- a claim of completeness for
    a bar the plan never finished stating. CommonMark: <=3 spaces is a heading, 4+ is code."""
    plan = (
        "# P\n## Acceptance criteria\n- the gate exits 0.\n\n"
        "      # rebuild the index\n      tautline reindex\n\n"
        "- the record is committed.\n- the ledger is green.\n"
    )
    got = ga.plan_acceptance_criteria(plan)
    assert len(got) == 3
    assert got[1:] == ["the record is committed.", "the ledger is green."]


def test_a_lead_in_line_does_not_swallow_an_indented_list():
    """A lead-in ("All of the following must hold:") followed by an INDENTED list is the
    list, not one paragraph. Comparing indents folded every bullet into the lead-in and
    returned ONE combined criterion where the plan states several, under-reporting the count
    and letting the 200-character cap truncate what survived."""
    plan = (
        "# P\n## Acceptance criteria\n"
        "All of the following must hold:\n"
        "  - alpha holds.\n"
        "  - beta holds.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == ["alpha holds.", "beta holds."]


def test_a_nested_sub_bullet_still_folds_into_its_parent_criterion():
    """The lead-in fix must not promote genuine detail: a sub-bullet under a list item is
    that item's detail and still folds in, or one criterion becomes two."""
    plan = "# P\n## Acceptance criteria\n- alpha holds.\n  - with this detail.\n- beta holds.\n"
    assert ga.plan_acceptance_criteria(plan) == ["alpha holds. with this detail.", "beta holds."]


def test_an_amendment_numbered_criterion_is_its_own_item():
    """Plans amend a numbered list in place rather than renumber it. `2b.` is a criterion of
    its own, but a digits-only marker folded it into criterion 2, where the 200-character
    shortening then cut it -- while the report still said every parsed criterion was
    included. An in-repo plan (2026-08-08-plan-review-verdict-parsing.md) does exactly this."""
    plan = (
        "# P\n## Acceptance criteria\n"
        "1. the gate exits 0.\n"
        "2. the record is committed.\n"
        "2b. the amendment is pinned and bounded.\n"
        "3. the ledger is green.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == [
        "the gate exits 0.",
        "the record is committed.",
        "the amendment is pinned and bounded.",
        "the ledger is green.",
    ]


def test_a_generic_acceptance_heading_must_end_or_be_punctuated():
    """`acceptance` as a bare prefix bound `## Acceptance testing strategy` as the plan's
    criteria instead of falling through to `## Completion definition` -- the same wrong-section
    binding as a generic heading beating an exact one, one word later. The headings real plans
    use (`Acceptance`, `Acceptance criteria (independently testable)`, `6. Acceptance (...)`)
    all still bind."""
    for heading in (
        "Acceptance",
        "Acceptance criteria",
        "Acceptance criteria:",
        "Acceptance criteria (independently testable)",
        "6. Acceptance (independently testable)",
        "Success criteria",
    ):
        assert ga._ACCEPTANCE_HEADINGS.match(heading), heading
    for heading in ("Acceptance testing strategy", "Acceptance mapping", "Acceptance evidence"):
        assert not ga._ACCEPTANCE_HEADINGS.match(heading), heading

    plan = (
        "# P\n## Acceptance testing strategy\n- we will test it thoroughly.\n"
        "## Completion definition\n- the gate is green and the record committed.\n"
    )
    assert ga._criteria_scan(plan) == (
        "Completion definition",
        ["the gate is green and the record committed."],
    )


def test_the_core_refusal_measures_the_output_not_the_fallback_sentence():
    """The fail-closed check measured the summary sentence ("all N acceptance criteria ... are
    met") even when the criterion it stands in for is shorter, so a goal whose real output
    fitted was refused as over-budget -- a control rejecting on a length the result would never
    have had."""
    kwargs = dict(command="/goal", title="T", plan_ref="p.md", milestones=())
    stated, _meta = _compose(criteria=["ok."], limit=ga.GOAL_ASSIGNMENT_CHAR_LIMIT, **kwargs)
    text, meta = _compose(criteria=["ok."], limit=len(stated), **kwargs)
    assert meta["criteria_included"] == 1
    assert len(text) <= len(stated)
    with pytest.raises(ValueError):
        _compose(criteria=["ok."], limit=len(stated) - 1, **kwargs)


def test_a_descriptive_completion_heading_does_not_shadow_the_real_one():
    """`\\b` let `## Completion definition mapping` bind before the real
    `## Completion definition` and return a mapping row as the plan's bar -- the same two-headed
    bug as the acceptance prefix, and fixing one half while leaving the other is how a defect
    class survives being fixed."""
    plan = (
        "# P\n## Completion definition mapping\n- a mapping row, NOT the bar.\n"
        "## Completion definition\n- the gate is green.\n"
    )
    assert ga._criteria_scan(plan) == ("Completion definition", ["the gate is green."])


def test_an_inner_fence_does_not_close_an_outer_one():
    """A plan showing Markdown inside Markdown closed on the INNER fence, so an example
    `## Acceptance criteria` was read as the real section while the real one was skipped as
    fenced. Per CommonMark a fence closes only on the same character, at least as long as the
    opener."""
    plan = (
        "# P\n## Notes\n~~~\nExample plan:\n```\n"
        "## Acceptance criteria\n- fake criterion.\n```\n~~~\n"
        "## Acceptance criteria\n- the real criterion holds.\n"
    )
    assert ga._criteria_scan(plan) == ("Acceptance criteria", ["the real criterion holds."])


def test_a_heading_inside_a_criterion_is_that_criterion_s_content():
    """Plans quote Markdown output inside a criterion. Treating that indented heading as a
    section boundary truncated the criterion AND could end the section, dropping every
    criterion below it."""
    plan = (
        "# P\n## Acceptance criteria\n- the command prints:\n\n"
        "  ## Verification\n\n  and exits 0.\n- the second criterion holds.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == [
        "the command prints: ## Verification and exits 0.",
        "the second criterion holds.",
    ]


def test_a_four_backtick_fence_is_not_closed_by_an_inner_three_backtick_one():
    """The exact variant a review round named: a four-backtick outer fence embedding a
    three-backtick example. Closing on the inner delimiter reads the example's
    `## Acceptance criteria` as the real section and skips the real one as fenced."""
    plan = (
        "# P\n## Notes\n````\n```\n## Acceptance criteria\n- fake criterion.\n```\n````\n"
        "## Acceptance criteria\n- the real criterion holds.\n"
    )
    assert ga._criteria_scan(plan) == ("Acceptance criteria", ["the real criterion holds."])


def test_a_nested_heading_at_the_sections_own_level_still_belongs_to_its_criterion():
    """Indentation decides, not heading level: an indented `## Acceptance criteria` quoted
    inside a criterion must not end the section it sits in, which is the case where level
    equality would otherwise break the whole section."""
    plan = (
        "# P\n## Acceptance criteria\n- the command prints:\n"
        "  ## Acceptance criteria\n  and exits 0.\n- the second criterion holds.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == [
        "the command prints: ## Acceptance criteria and exits 0.",
        "the second criterion holds.",
    ]


def test_a_section_whose_criteria_are_all_satisfied_yields_nothing_not_its_lead_in():
    """Skipping every `- [x]` entry left the listed set empty, so the prose fallback promoted
    the lead-in line and handed back "All of the following must hold:" as the plan's sole
    acceptance criterion. A section that was a list stays a list even when every entry is done."""
    plan = (
        "# P\n## Acceptance criteria\nAll of the following must hold:\n"
        "- [x] one is done.\n- [x] two is done.\n"
    )
    assert ga.plan_acceptance_criteria(plan) == []


def test_a_prose_only_section_still_yields_its_paragraph():
    """The all-satisfied guard must not disable the prose path for sections that never had a
    list -- plans are allowed to state their bar in sentences."""
    assert ga.plan_acceptance_criteria("# P\n## Completion definition\nJust prose here.\n") == [
        "Just prose here."
    ]


def test_a_closing_fence_carries_no_info_string():
    """CommonMark: ```` ```python ```` inside a ``` block is content, not a close. Closing on
    the marker alone made a fake `## Acceptance criteria` in that block visible to the scanner,
    where it could shadow the real section."""
    plan = (
        "# P\n## Notes\n```\n```python\n## Acceptance criteria\n- fake criterion.\n```\n"
        "## Acceptance criteria\n- the real criterion.\n"
    )
    assert ga._criteria_scan(plan) == ("Acceptance criteria", ["the real criterion."])


def test_a_configured_heading_outranks_a_standard_one_earlier_in_the_plan():
    """Plan finalization grades only the configured `planAcceptance.acHeadings` section. Folding
    configured and standard headings into one alternation left DOCUMENT ORDER to decide, so an
    earlier standard section won and the goal stated a bar the gate never graded."""
    plan = (
        "# P\n## Acceptance criteria\n- the standard bar.\n"
        "## Validation Requirements\n- the configured bar.\n"
    )
    assert ga._criteria_scan(plan) == ("Acceptance criteria", ["the standard bar."])
    assert ga._criteria_scan(plan, ["Validation Requirements"]) == (
        "Validation Requirements",
        ["the configured bar."],
    )
