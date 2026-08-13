"""Item 81 WS1: closure verification is measured against the item's WRITTEN acceptance criteria.

RCA 2026-07-21 (issue #357 on a private product lane, two RCA copies; the product is named in the
source RCAs, not here -- this repo is a public cut). Nothing constrained the ORACLE used to verify
an item at closure. The canonical spec was frozen out of the run set, the executed specs were authored to
the divergent implementation, and the agent -- asked to verify -- adopted the only live oracle
left: the implementation itself ("verification within the shipped model"). It then reframed failed
acceptance-criteria lines as scope deferrals. A human caught it by quoting the AC lines back.

Done moves already required evidence to EXIST (`goal_tracker_post_done_evidence`, any non-empty
string passes) and still do. What is new here is that the evidence must be measured against
something the implementation cannot move: the criteria written on the linked issue.

Two properties carry the weight, and both have a test that fails if they are lost:

- **Matching is injective, not counted.** N identical or paraphrased rows can never cover N
  distinct criteria (case 5). A count-based check passes the exact evidence #357 produced.
- **The forbidden-phrase list is a tripwire, not the control.** A reworded evasion is still refused
  by the table check (case 7), so nobody can weaken the matcher and lean on the phrases.

The seam matters as much as the check: the gate runs as a PRE-FLIGHT, before the board-backed
subtask loop issues its first `gh project item-edit`. Case 11 is the test that catches a regression
to the v1 seam (inside `goal_tracker_post_done_evidence`), which fires only after subtasks have
already moved to done.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

AC_HEADINGS = ["acceptance criteria", "acceptance"]

# Four top-level criteria under a title-case level-2 heading.
AC_BODY = """# Digest scheduler

Some preamble prose that is not a criterion.

## Acceptance Criteria

- The scheduler runs three windows per day
- Users receive a digest email every morning
- The dashboard shows the last successful run time
- Failures are retried twice before alerting

## Notes

Unrelated trailing section.
"""

CRITERIA = [
    "The scheduler runs three windows per day",
    "Users receive a digest email every morning",
    "The dashboard shows the last successful run time",
    "Failures are retried twice before alerting",
]


def _table(rows: list[tuple[str, str]], heading: str = "## AC Verification") -> str:
    lines = [heading, "", "| Criterion | Verdict |", "| --- | --- |"]
    lines += [f"| {criterion} | {verdict} |" for criterion, verdict in rows]
    return "\n".join(lines) + "\n"


def _all_pass() -> str:
    return _table([(criterion, "PASS") for criterion in CRITERIA])


def _issues(
    cli,
    evidence: str,
    body: str = AC_BODY,
    headings: list[str] | None = None,
) -> list[str]:
    return cli.done_evidence_ac_table_issues(evidence, body, list(headings or AC_HEADINGS))


# --- The check lives where the closure walker looks for it ---------------------------------------


def test_the_check_is_defined_in_backlog_py(cli) -> None:
    """Placement is not the builder's choice: tests/test_closure_refusal_continuations.py walks a
    DECLARED file list, and a refusal builder that moves out of that list becomes invisible to it
    while every other test in this file stays green."""
    source_file = inspect.getsourcefile(cli.done_evidence_ac_table_issues) or ""
    assert Path(source_file).name == "backlog.py", (
        f"done_evidence_ac_table_issues is defined in {source_file!r}; the closure refusal walk "
        "declares backlog.py and cli.py as its only sources."
    )


# --- Case 0 (packet extra): the extractor is not silently empty ----------------------------------


def test_the_extraction_path_yields_criteria_on_the_fixtures(cli) -> None:
    """An extractor that silently matches nothing makes every refusal test below vacuous: no
    criteria means no unmatched criteria means no issues, and the gate ships green and dead. This is
    the same recurrence shape the RCA is about, so it gets its own floor rather than being implied.
    """
    section = cli._extract_ac_section(AC_BODY, AC_HEADINGS)
    assert section.strip(), "the AC section fixture extracted to nothing"
    assert len(cli._split_ac_items(section)) == 4


# --- Case 1: a complete honest table passes ------------------------------------------------------


def test_a_complete_pass_table_raises_no_issue(cli) -> None:
    assert _issues(cli, _all_pass()) == []


# --- Case 2: no table at all ---------------------------------------------------------------------


def test_evidence_with_no_table_names_the_unmatched_criteria_and_a_remedy(cli) -> None:
    issues = _issues(cli, "Verified the digest scheduler end to end. Everything works.")

    assert len(issues) == 1
    message = issues[0]
    assert message.startswith("done_evidence_ac_error:")
    assert "4 of 4" in message
    # Named verbatim, not counted: a count tells the lane nothing about which line to go verify.
    assert "the scheduler runs three windows per day" in message.lower()
    assert "tautline ac-verify" in message


# --- Case 3: a FAIL row refuses ------------------------------------------------------------------


def test_a_fail_row_is_a_failed_ac_and_never_a_deferral(cli) -> None:
    rows = [(criterion, "PASS") for criterion in CRITERIA[:3]]
    rows.append((CRITERIA[3], "FAIL"))

    issues = _issues(cli, _table(rows))

    assert len(issues) == 1
    message = issues[0]
    assert "FAILED AC" in message
    assert "never a deferral" in message
    assert "failures are retried twice before alerting" in message.lower()


# --- Case 4: DEFERRED / PARTIAL / N/A are not rows -----------------------------------------------


@pytest.mark.parametrize("verdict", ["DEFERRED", "PARTIAL", "N/A", "deferred to #350"])
def test_a_non_verdict_row_does_not_cover_the_criterion_it_pretends_to(cli, verdict: str) -> None:
    """The observed #357 mechanism: an unmet criterion re-labelled as scope. A row whose verdict is
    not PASS or FAIL is not a row, so the criterion reads as unmatched."""
    rows = [(criterion, "PASS") for criterion in CRITERIA[:3]]
    rows.append((CRITERIA[3], verdict))

    issues = _issues(cli, _table(rows))

    assert len(issues) == 1
    assert "1 of 4" in issues[0]
    assert "failures are retried twice before alerting" in issues[0].lower()


# --- Case 5: matching is injective, not counted --------------------------------------------------


IDENTICAL_ROW_BODY = """## Acceptance Criteria

- ships correctly
- the digest email is sent nightly
- the dashboard shows the last successful run time
- failures are retried twice before alerting
"""


def test_four_identical_rows_cover_exactly_one_criterion(cli) -> None:
    """A count-based check passes this. Rows are consumed injectively, so one row satisfies at most
    one criterion and the other three criteria stay unmatched."""
    evidence = _table([("ships correctly", "PASS")] * 4)

    issues = _issues(cli, evidence, body=IDENTICAL_ROW_BODY)

    assert len(issues) == 1
    assert "3 of 4" in issues[0]


def test_nine_paraphrase_rows_that_match_nothing_cover_nothing(cli) -> None:
    evidence = _table([(f"observation number {index} was recorded", "PASS") for index in range(9)])

    issues = _issues(cli, evidence)

    assert len(issues) == 1
    assert "4 of 4" in issues[0]


# --- Codex R2: the strictest verdict wins, and a piped criterion round-trips ----------------------


def test_a_fail_row_wins_over_a_pass_row_for_the_same_criterion(cli) -> None:
    """Writing a passing row ABOVE a failing one must not silence the failure.

    Codex R2 P2. The matcher consumed the first eligible row, so `| A | PASS |` followed by
    `| A | FAIL |` reported no issue and allowed the done move -- an explicitly failed criterion
    silenced by adding a line above it. That is the reframe-a-failure mechanism this item exists to
    stop, rebuilt inside the gate meant to stop it, so the strictest recorded verdict now wins.
    """
    rows = [(criterion, "PASS") for criterion in CRITERIA]
    rows.append((CRITERIA[0], "FAIL"))

    issues = _issues(cli, _table(rows))

    assert len(issues) == 1
    assert "FAILED AC" in issues[0]
    assert CRITERIA[0].lower() in issues[0].lower()


def test_a_later_row_corrects_an_earlier_one_for_the_same_criterion(cli) -> None:
    """Ordering means "later corrects earlier", which is what the evidence channel is FOR.

    This replaces an order-independence assertion this lane wrote earlier. That assertion went
    beyond what the review finding behind it actually required -- the finding was that a PASS
    written ABOVE a FAIL silenced the failure, and that is still refused
    (test_a_fail_row_wins_over_a_pass_row_for_the_same_criterion). What it also forbade, wrongly,
    was the honest inverse: a corrected verdict appended after a stale one. Compose-time
    supersession existed only to work around that and could never be made correct, because the
    composer has no criteria. Judging the LAST verdict per criterion does both jobs at the site
    that does.
    """
    rows = [(CRITERIA[0], "FAIL")]
    rows += [(criterion, "PASS") for criterion in CRITERIA]

    assert _issues(cli, _table(rows)) == []


PIPED_BODY = """## Acceptance Criteria

- Support A | B imports
- The dashboard shows the last successful run time
"""


def test_a_criterion_containing_a_pipe_round_trips_through_the_skeleton(cli) -> None:
    """Codex R2 P2. A literal `|` in the criterion text opened a third table cell, so the row the
    verb emitted could not be parsed by the gate that demanded it: `ac-verify` refused its own
    output. The skeleton now escapes the pipe and the key unescapes it, so the continuation the
    refusal names actually works on this criterion."""
    criteria = cli.done_evidence_ac_criteria(PIPED_BODY, AC_HEADINGS)
    assert len(criteria) == 2

    skeleton = cli.done_evidence_ac_table_skeleton(criteria)
    assert "\\|" in skeleton, "the pipe must be escaped, not passed through"

    filled = skeleton.replace(cli.AC_TABLE_VERDICT_PLACEHOLDER, "PASS")

    assert _issues(cli, filled, body=PIPED_BODY) == []


def test_the_unfilled_piped_skeleton_is_still_refused(cli) -> None:
    """Escaping must not accidentally make the blank form parse as a pass."""
    criteria = cli.done_evidence_ac_criteria(PIPED_BODY, AC_HEADINGS)

    issues = _issues(cli, cli.done_evidence_ac_table_skeleton(criteria), body=PIPED_BODY)

    assert len(issues) == 1
    assert "2 of 2" in issues[0]


# --- Case 6: nested sub-bullets are ONE criterion ------------------------------------------------


NESTED_BODY = """## Acceptance Criteria

- The pipeline is observable end to end
    - metrics are emitted per stage
    - traces are sampled at one percent
    - logs carry the run id
"""

SHALLOW_NESTED_BODY = NESTED_BODY.replace("    - ", "  - ")


def test_nested_sub_bullets_are_one_criterion(cli) -> None:
    """`_split_ac_items` groups a bullet with its indented continuation lines. A naive bullet-count
    implementation demands four rows here and refuses honest evidence."""
    evidence = _table([("The pipeline is observable end to end", "PASS")])

    assert _issues(cli, evidence, body=NESTED_BODY) == []


def test_a_two_space_nested_list_over_splits_and_the_skeleton_still_agrees(cli) -> None:
    """KNOWN over-split, pinned rather than hidden.

    `_split_ac_items` is rec #13's shipped helper and treats up to three leading spaces as
    top-level, so a two-space-nested checklist reads as four criteria rather than one. This item
    reuses that helper deliberately -- forking a second splitter is how the two surfaces drift --
    so the over-split is real, and it is named in the migration report as a `strict`-ratchet
    criterion instead of being smoothed over here.

    What makes it survivable is the property this test actually pins: `ac-verify` derives its
    skeleton from the SAME splitter, so whatever the split does, the table the lane is told to
    produce is exactly the table the gate will accept. An over-split is noise under the default
    `warn`; it is never a dead end.
    """
    criteria = cli.done_evidence_ac_criteria(SHALLOW_NESTED_BODY, AC_HEADINGS)
    assert len(criteria) == 4, "the over-split is the documented behavior; if this changed, say so"

    skeleton = cli.done_evidence_ac_table_skeleton(criteria)
    filled = skeleton.replace(cli.AC_TABLE_VERDICT_PLACEHOLDER, "PASS")

    assert _issues(cli, filled, body=SHALLOW_NESTED_BODY) == []


# --- Codex R1 P1: the blank form must not verify itself ------------------------------------------


def test_the_unfilled_skeleton_is_refused_by_the_gate(cli) -> None:
    """The gate must refuse its OWN unfilled continuation.

    The first placeholder was `PASS|FAIL`, whose embedded pipe closes the verdict cell, so
    `_AC_ROW_RE` read it as a real `PASS`: handing `ac-verify`'s output straight back satisfied every
    criterion and closed the item with no pass/fail decision made anywhere. Found by Codex R1 as a
    P1, and this lane's own skeleton-agreement test had masked it by filling the placeholder before
    asserting.

    The assertion is on the REFUSAL, not on the regex: whatever the placeholder becomes, a table
    nobody has filled in cannot be accepted as verification.
    """
    criteria = cli.done_evidence_ac_criteria(AC_BODY, AC_HEADINGS)
    skeleton = cli.done_evidence_ac_table_skeleton(criteria)

    issues = _issues(cli, skeleton)

    assert len(issues) == 1
    assert "4 of 4" in issues[0], "an unfilled skeleton must cover NO criterion"


def test_the_same_skeleton_passes_once_every_verdict_is_filled_in(cli) -> None:
    """The other half of the property: refusing the blank form must not make the form unusable."""
    criteria = cli.done_evidence_ac_criteria(AC_BODY, AC_HEADINGS)
    filled = cli.done_evidence_ac_table_skeleton(criteria).replace(
        cli.AC_TABLE_VERDICT_PLACEHOLDER, "PASS"
    )

    assert _issues(cli, filled) == []


def test_a_partly_filled_skeleton_covers_only_what_was_decided(cli) -> None:
    criteria = cli.done_evidence_ac_criteria(AC_BODY, AC_HEADINGS)
    filled = cli.done_evidence_ac_table_skeleton(criteria).replace(
        cli.AC_TABLE_VERDICT_PLACEHOLDER, "PASS", 2
    )

    issues = _issues(cli, filled)

    assert len(issues) == 1
    assert "2 of 4" in issues[0]


# --- Case 7: the tripwire is not load-bearing ----------------------------------------------------


def test_a_forbidden_oracle_phrase_is_flagged_even_with_a_complete_table(cli) -> None:
    evidence = _all_pass() + "\nAll criteria were verified within the shipped model.\n"

    issues = _issues(cli, evidence)

    assert len(issues) == 1
    assert "forbidden verification oracle" in issues[0]
    assert "within the shipped model" in issues[0]


def test_a_reworded_evasion_is_still_refused_by_the_table_check(cli) -> None:
    """Three literals cannot survive rewording, which is why the structural matcher carries the
    enforcement weight. If someone ever deletes the matcher and leaves the phrase list, this fails.
    """
    evidence = (
        _table([(CRITERIA[0], "PASS")])
        + "\nThe rest was checked against what the service actually does today.\n"
    )

    issues = _issues(cli, evidence)

    assert not any("forbidden verification oracle" in message for message in issues), (
        "the reworded evasion is deliberately NOT caught by the phrase list -- that is the point"
    )
    assert len(issues) == 1
    assert "3 of 4" in issues[0]


# --- Case 8: anti-inert -- markdown_section() would ship this gate green and dead -----------------


@pytest.mark.parametrize(
    "heading",
    [
        "## Acceptance Criteria",
        "### Acceptance criteria:",
        "#### ACCEPTANCE CRITERIA",
        "## Acceptance",
    ],
    ids=["level2-title-case", "level3-trailing-colon", "level4-shouting", "short-form"],
)
def test_any_heading_level_case_and_trailing_colon_extract(cli, heading: str) -> None:
    """`markdown_section()` is case-sensitive and level-exact, so against the lowercased heading
    list it silently matches nothing: no section, no criteria, no issues, gate green and dead. This
    is the test that fails if anyone reintroduces it on this path."""
    body = heading + "\n\n" + "\n".join(f"- {criterion}" for criterion in CRITERIA) + "\n"

    assert _issues(cli, "no table here at all", body=body), f"{heading!r} extracted nothing"
    assert _issues(cli, _all_pass(), body=body) == []


# --- Case 9: no AC section on the issue ----------------------------------------------------------


def test_an_issue_with_no_ac_section_requires_no_table(cli) -> None:
    """Existing non-empty-evidence behavior is byte-unchanged for items that never wrote ACs."""
    assert _issues(cli, "Deployed and smoke-tested.", body="# Title\n\nJust a description.\n") == []
    assert _issues(cli, "Deployed and smoke-tested.", body="") == []


# --- The repo helper the fetch needs -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/other/repo/issues/5", "other/repo"),
        ("https://github.com/example-org/example-saas/pull/12", "example-org/example-saas"),
        ("  https://github.com/o/r/issues/1#issuecomment-9  ", "o/r"),
        ("https://example.com/o/r/issues/1", ""),
        ("", ""),
    ],
)
def test_github_repo_from_issue_url(cli, url: str, expected: str) -> None:
    assert cli.github_repo_from_issue_url(url) == expected


# --- Plumbing: the pre-flight seam, the knob, the fetch ------------------------------------------


def _item(*, number: int = 7, repo: str = "example-org/example-saas", body: str = "") -> dict:
    content: dict = {"url": f"https://github.com/{repo}/issues/{number}"}
    if body:
        content["body"] = body
    return {
        "id": "ITEM1",
        "content": content,
        "url": "https://github.com/orgs/example-org/projects/1?pane=item",
    }


def _project(cli, *, ac_table: str = "warn") -> dict:
    data = cli.load_project(EXAMPLE_ADAPTER)
    data["backlogProvider"]["doneEvidence"] = {"acTable": ac_table}
    return data


def _harness(
    cli,
    monkeypatch,
    *,
    item: dict,
    body: str,
    body_code: int = 0,
    body_err: str = "",
    subtasks: list[dict] | None = None,
):
    """Record every `gh` argv the done move actually issues.

    The board READS are stubbed at their own helper so the real mutation calls -- `gh project
    item-edit` from `goal_tracker_update_status`, and the comment POST from
    `stakeholder_issue_post_comment` -- still travel through `run_command` and land in this list.
    Stubbing the mutations themselves would make case 11 assert on the test double instead of on
    the code, and it would pass with the gate deleted.
    """
    calls: list[list[str]] = []

    def _run(command, cwd=None, timeout=None, **kwargs):
        calls.append(list(command))
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            if body_code != 0:
                return body_code, "", body_err
            return 0, body, ""
        if command[:2] == ["gh", "api"]:
            comment = {"html_url": "https://github.com/example-org/example-saas/issues/7#c1"}
            return 0, json.dumps(comment), ""
        return 0, "{}", ""

    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda *a, **k: [])
    monkeypatch.setattr(
        cli,
        "goal_tracker_project_fields",
        lambda *a, **k: [{"name": "Status", "id": "FIELD1", "options": [{"name": "Done", "id": "OPT1"}]}],
    )
    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda *a, **k: {"id": "PROJ1"})
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *a, **k: item)
    monkeypatch.setattr(cli, "goal_tracker_board_backed_subtasks", lambda *a, **k: list(subtasks or []))
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda *a, **k: "CLOSED")
    monkeypatch.setattr(cli, "github_cache_invalidate_project", lambda *a, **k: None)
    return calls


def _mutations(calls: list[list[str]]) -> list[list[str]]:
    return [
        call
        for call in calls
        if call[:3] == ["gh", "project", "item-edit"]
        or (call[:2] == ["gh", "api"] and "--method" in call and "POST" in call)
        or call[:3] == ["gh", "issue", "comment"]
    ]


def test_strict_refuses_the_done_move_on_an_unmatched_criterion(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli, ac_table="strict")
    _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_update_status_with_done_evidence(
            data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
        )

    assert "done_evidence_ac_error:" in str(raised.value)
    assert "tautline ac-verify" in str(raised.value)


def test_warn_proceeds_and_prints_the_warning(cli, monkeypatch, tmp_path, capsys) -> None:
    data = _project(cli, ac_table="warn")
    _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
    )

    out = capsys.readouterr().out
    assert "done_evidence_ac_warning:" in out
    assert "done_evidence_ac_state: fail" in out


def test_off_never_runs_the_check(cli, monkeypatch, tmp_path, capsys) -> None:
    data = _project(cli, ac_table="off")
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
    )

    assert "done_evidence_ac" not in capsys.readouterr().out
    assert not [call for call in calls if call[:3] == ["gh", "issue", "view"]], (
        "`off` must not even fetch the issue body"
    )


def test_a_complete_table_passes_the_preflight_and_the_done_move_proceeds(
    cli,
    monkeypatch,
    tmp_path,
) -> None:
    data = _project(cli, ac_table="strict")
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    assert _mutations(calls), "the done move must still mutate when the evidence is honest"


def test_the_knob_defaults_to_warn(cli) -> None:
    data = cli.load_project(EXAMPLE_ADAPTER)
    assert data["backlogProvider"]["doneEvidence"]["acTable"] == "warn"


# --- Case 11: a refused done move mutates nothing ------------------------------------------------


def test_a_strict_refusal_issues_no_item_edit_and_no_comment(cli, monkeypatch, tmp_path) -> None:
    """Only meaningful because the gate is a PRE-FLIGHT. The v1 seam (inside
    `goal_tracker_post_done_evidence`) fires AFTER `goal_tracker_update_board_backed_subtasks_status`
    has already moved both subtasks to done and posted their evidence comments. This test is what
    catches a regression back to it."""
    data = _project(cli, ac_table="strict")
    subtasks = [
        {"id": "SUB1", "content": {"url": "https://github.com/example-org/example-saas/issues/8"}},
        {"id": "SUB2", "content": {"url": "https://github.com/example-org/example-saas/issues/9"}},
    ]
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY, subtasks=subtasks)

    with pytest.raises(SystemExit):
        cli.goal_tracker_update_status_with_done_evidence(
            data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
        )

    assert _mutations(calls) == [], (
        "a refused done move mutated the board or posted a comment: "
        f"{_mutations(calls)}"
    )


# --- F9: the subtask call site is excluded -------------------------------------------------------


SUBTASK_AC_BODY = """## Acceptance Criteria

- the subtask has its very own acceptance criterion
"""


def test_a_subtasks_own_criteria_never_refuse_the_parents_own_preflight(cli, monkeypatch, tmp_path) -> None:
    """Packet fork F9's CORRECT half, kept: the PARENT's pre-flight measures the PARENT's criteria.

    `goal_tracker_post_done_evidence` gains no AC logic of its own, and the parent's gate is never
    polluted by a subtask's acceptance criteria -- evaluating one item's evidence against another
    item's criteria is meaningless, which is what F9 got right.
    """
    data = _project(cli, ac_table="strict")
    parent = _item()
    _harness(cli, monkeypatch, item=parent, body=AC_BODY)

    assert cli.goal_tracker_preflight_done_ac_evidence(
        data, tmp_path, parent, "ITEM1", _all_pass(), "backlog-provider-update"
    ) == []


def test_an_auto_closed_subtask_is_measured_against_its_own_criteria(cli, monkeypatch, tmp_path) -> None:
    """Codex R4 P2, and a correction to fork F9's OTHER half.

    F9 justified excluding the subtask call site with "each subtask's ACs are checked when IT moves
    to done through the same funnel". That premise is false for a board-backed subtask auto-closed
    by a parent closure: the subtask is moved to Done right there and never travels the funnel
    itself. So the parent's AC table could be posted as the subtask's verification and the subtask
    closed with its own written criteria never measured by anything, ever -- a bypass of the
    headline gate, inside the gate.

    The remedy is real and runnable, which is why refusing here is not a dead end: close the subtask
    through its own done move with its own evidence first, and the parent move then finds it already
    terminal and skips it.
    """
    data = _project(cli, ac_table="strict")
    subtasks = [{"id": "SUB1", "content": {"url": "https://github.com/example-org/example-saas/issues/8"}}]

    def _run(command, cwd=None, timeout=None, **kwargs):
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            return 0, (SUBTASK_AC_BODY if command[3] == "8" else AC_BODY), ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://example.com/c"}), ""
        return 0, "{}", ""

    _harness(cli, monkeypatch, item=_item(), body=AC_BODY, subtasks=subtasks)
    monkeypatch.setattr(cli, "run_command", _run)

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_update_status_with_done_evidence(
            data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
        )

    message = str(raised.value)
    assert "done_evidence_ac_error:" in message
    assert "the subtask has its very own acceptance criterion" in message.lower()
    assert "tautline ac-verify" in message


def test_an_auto_closed_subtask_without_its_own_criteria_still_closes(cli, monkeypatch, tmp_path) -> None:
    """The other direction, so the fix cannot become a blanket refusal of parent closures: a subtask
    with no written criteria of its own has nothing to measure and must not block the parent."""
    data = _project(cli, ac_table="strict")
    subtasks = [{"id": "SUB1", "content": {"url": "https://github.com/example-org/example-saas/issues/8"}}]

    def _run(command, cwd=None, timeout=None, **kwargs):
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            return 0, ("# Subtask\n\nNo criteria here.\n" if command[3] == "8" else AC_BODY), ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://example.com/c"}), ""
        return 0, "{}", ""

    _harness(cli, monkeypatch, item=_item(), body=AC_BODY, subtasks=subtasks)
    monkeypatch.setattr(cli, "run_command", _run)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )


# --- Case 12: the fetch can fail, and it must say so ---------------------------------------------


def test_a_body_fetch_failure_reports_unknown_under_warn(
    cli,
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """A degrade that is indistinguishable from a pass cannot be measured, and the strict ratchet
    is gated on measuring it."""
    data = _project(cli, ac_table="warn")
    _harness(cli, monkeypatch, item=_item(), body="", body_code=1, body_err="HTTP 403: Forbidden")

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
    )

    out = capsys.readouterr().out
    assert "done_evidence_ac_warning: issue body unavailable" in out
    assert "done_evidence_ac_state: unknown" in out


def test_a_body_fetch_failure_refuses_under_strict_and_names_the_retry(
    cli,
    monkeypatch,
    tmp_path,
) -> None:
    data = _project(cli, ac_table="strict")
    _harness(cli, monkeypatch, item=_item(), body="", body_code=1, body_err="HTTP 403: Forbidden")

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_update_status_with_done_evidence(
            data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
        )

    message = str(raised.value)
    assert "issue body unavailable" in message
    assert "tautline ac-verify" in message


def test_a_null_literal_body_is_treated_as_empty(cli, monkeypatch, tmp_path, capsys) -> None:
    """`gh ... --jq '.body // ""'` still emits the literal string `null` for some empty bodies. A
    body of `null` has no AC section, so the move proceeds -- it must not be parsed as prose."""
    data = _project(cli, ac_table="strict")
    _harness(cli, monkeypatch, item=_item(), body="null\n")

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence="Shipped it.", context="backlog-provider-update"
    )

    assert "done_evidence_ac_error" not in capsys.readouterr().out


# --- Case 13: the repo comes from the issue URL, never from the adapter --------------------------


def test_a_pr_backed_item_is_read_with_gh_pr_view(cli, monkeypatch, tmp_path) -> None:
    """Codex R1 P2. Board items are routinely backed by a PULL REQUEST, and both URL helpers accept
    `/pull/` by design -- so a fetch hardcoded to `gh issue view` resolves a real number, calls the
    wrong subcommand, and reports the body as permanently unavailable. Under `warn` that is an
    `unknown` on every PR-backed closure; under `strict` it refuses closures that are perfectly
    valid. The failure is invisible from the outside because it looks exactly like a fetch error.
    """
    data = _project(cli, ac_table="warn")
    item = {
        "id": "ITEM1",
        "content": {"url": "https://github.com/example-org/example-saas/pull/42"},
    }
    calls = _harness(cli, monkeypatch, item=item, body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    views = [call for call in calls if call[:2] == ["gh", "pr"]]
    assert views, f"a PR-backed item must be read with `gh pr view`, not: {calls}"
    assert views[0][:3] == ["gh", "pr", "view"]
    assert views[0][3] == "42"
    assert not [call for call in calls if call[:3] == ["gh", "issue", "view"]]


def test_an_issue_backed_item_still_uses_gh_issue_view(cli, monkeypatch, tmp_path) -> None:
    """The other half: fixing the PR path must not reroute the ordinary one."""
    data = _project(cli, ac_table="warn")
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    assert [call for call in calls if call[:3] == ["gh", "issue", "view"]]
    assert not [call for call in calls if call[:3] == ["gh", "pr", "view"]]


def test_a_contenturl_backed_item_is_read(cli, monkeypatch, tmp_path) -> None:
    """Codex R4 P2. A Project item payload that exposes its link only at top-level `contentUrl` is
    a shape `board_item_fetch_state` has handled all along, but this path walked two fields of its
    own and missed it -- so a valid item reported `unknown` under warn and was refused under strict.
    The URL candidates now come from `board_item_issue_pr_urls`, the one definition of where an
    item's issue/PR link lives."""
    data = _project(cli, ac_table="strict")
    item = {"id": "ITEM1", "contentUrl": "https://github.com/example-org/example-saas/issues/11"}
    calls = _harness(cli, monkeypatch, item=item, body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    views = [call for call in calls if call[:3] == ["gh", "issue", "view"]]
    assert views, "a contentUrl-backed item must still have its body read"
    assert views[0][3] == "11"
    assert views[0][views[0].index("--repo") + 1] == "example-org/example-saas"


def test_an_item_with_no_link_anywhere_still_reports_it_plainly(cli, monkeypatch, tmp_path, capsys) -> None:
    """Widening the candidate list must not swallow the genuinely-unlinked case.

    Asserted on the PRE-FLIGHT rather than the whole funnel: a done move on an unlinked item is
    refused further down by `goal_tracker_post_done_evidence`, which has required a linked issue
    since long before this item -- the evidence has nowhere to be posted. What is this item's to
    prove is that the closure gate degrades to an explicit `unknown` first, rather than reading an
    empty body as an item with no acceptance criteria and quietly passing.
    """
    data = _project(cli, ac_table="warn")
    item = {"id": "ITEM1", "content": {}}
    _harness(cli, monkeypatch, item=item, body=AC_BODY)

    issues = cli.goal_tracker_preflight_done_ac_evidence(
        data, tmp_path, item, "ITEM1", "Shipped it.", "backlog-provider-update"
    )

    out = capsys.readouterr().out
    assert issues == []
    assert "no linked GitHub issue/PR URL" in out
    assert "done_evidence_ac_state: unknown" in out


def test_a_cross_repo_item_is_fetched_from_its_own_repo(cli, monkeypatch, tmp_path) -> None:
    """`data["repo"]` is the LANE's repo. An item whose issue lives elsewhere would be checked
    against a body from the wrong repository -- or, worse, against issue #5 of the lane repo."""
    data = _project(cli, ac_table="warn")
    calls = _harness(cli, monkeypatch, item=_item(number=5, repo="other/repo"), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    views = [call for call in calls if call[:3] == ["gh", "issue", "view"]]
    assert views, "the pre-flight never fetched the issue body"
    assert "--repo" in views[0]
    assert views[0][views[0].index("--repo") + 1] == "other/repo"
    assert views[0][3] == "5"


# --- The comment surface, which had no behavioral test at all --------------------------------------


CLAIMING_COMMENT = """## Verification Evidence

Everything checked out end to end.
"""


def test_a_verification_claiming_comment_is_measured_under_strict(cli, monkeypatch, tmp_path) -> None:
    """The observed RCA defect was a verification COMMENT on an item that never moved to done, so
    gating the done funnel alone leaves the mechanism live. This surface contributes three of the
    closure walk's collected refusals and, until now, had no test that executed any of them."""
    data = _project(cli, ac_table="strict")
    _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    with pytest.raises(SystemExit) as raised:
        cli.stakeholder_issue_verification_claim_issues(
            data, tmp_path, "7", CLAIMING_COMMENT, repo=data["repo"]
        )

    assert "done_evidence_ac_error:" in str(raised.value)


def test_a_verification_claiming_comment_warns_under_warn(cli, monkeypatch, tmp_path, capsys) -> None:
    data = _project(cli, ac_table="warn")
    _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    issues = cli.stakeholder_issue_verification_claim_issues(
        data, tmp_path, "7", CLAIMING_COMMENT, repo=data["repo"]
    )

    assert issues
    assert "done_evidence_ac_warning:" in capsys.readouterr().out


def test_a_claiming_comment_carrying_an_honest_table_passes(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli, ac_table="strict")
    _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    assert cli.stakeholder_issue_verification_claim_issues(
        data, tmp_path, "7", "## Verification Evidence\n\n" + _all_pass(), repo=data["repo"]
    ) == []


def test_a_plain_progress_comment_is_never_fetched_or_checked(cli, monkeypatch, tmp_path) -> None:
    """Narrow by construction: a comment that claims nothing about verification pays no cost. The
    assertion is on the recorded argv -- no issue-body read happens at all."""
    data = _project(cli, ac_table="strict")
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    assert cli.stakeholder_issue_verification_claim_issues(
        data, tmp_path, "7", "Rebased onto main; CI is green.", repo=data["repo"]
    ) == []
    assert not [call for call in calls if call[:3] == ["gh", "issue", "view"]]


def test_the_done_path_does_not_double_check_its_own_comment(cli, monkeypatch, tmp_path) -> None:
    """`goal_tracker_post_done_evidence` wraps its evidence in a `## Verification Evidence` heading,
    which is verification-claiming by construction. Without the ac_checked suppression the done move
    would fetch the issue body twice and evaluate the same verdict twice."""
    data = _project(cli, ac_table="strict")
    calls = _harness(cli, monkeypatch, item=_item(), body=AC_BODY)

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )

    views = [call for call in calls if call[:3] == ["gh", "issue", "view"]]
    assert len(views) == 1, f"the issue body must be read exactly once, saw {len(views)}"


def test_an_already_done_subtask_does_not_block_the_parent(cli, monkeypatch, tmp_path) -> None:
    """Codex R1 on the gate-core cut. The status-update loop SKIPS a subtask already in a done
    status -- it neither comments nor moves it -- so judging it in the pre-flight could block the
    parent forever on criteria settled when that subtask was closed. It also punished the exact
    remedy this gate's refusal recommends: close the subtask through its own done move first, with
    its own evidence. The pre-flight now mirrors the mutation loop's skips."""
    data = _project(cli, ac_table="strict")
    subtasks = [{
        "id": "SUB1",
        "status": "Done",
        "fieldValues": {"nodes": [{"field": {"name": "Status"}, "name": "Done"}]},
        "content": {"url": "https://github.com/example-org/example-saas/issues/8"},
    }]

    def _run(command, cwd=None, timeout=None, **kwargs):
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            return 0, (SUBTASK_AC_BODY if command[3] == "8" else AC_BODY), ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://example.com/c"}), ""
        return 0, "{}", ""

    _harness(cli, monkeypatch, item=_item(), body=AC_BODY, subtasks=subtasks)
    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda item, field: "Done" if item.get("id") == "SUB1" else "")

    cli.goal_tracker_update_status_with_done_evidence(
        data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
    )


def test_a_still_open_subtask_is_still_judged(cli, monkeypatch, tmp_path) -> None:
    """The other direction: skipping terminal subtasks must not skip the ones being auto-closed."""
    data = _project(cli, ac_table="strict")
    subtasks = [{"id": "SUB1", "content": {"url": "https://github.com/example-org/example-saas/issues/8"}}]

    def _run(command, cwd=None, timeout=None, **kwargs):
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            return 0, (SUBTASK_AC_BODY if command[3] == "8" else AC_BODY), ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://example.com/c"}), ""
        return 0, "{}", ""

    _harness(cli, monkeypatch, item=_item(), body=AC_BODY, subtasks=subtasks)
    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda item, field: "In Progress")

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_update_status_with_done_evidence(
            data, tmp_path, "ITEM1", "Done", evidence=_all_pass(), context="backlog-provider-update"
        )

    assert "the subtask has its very own acceptance criterion" in str(raised.value).lower()


OVERLAPPING_BODY = """## Acceptance Criteria

- support csv import
- support csv import preview
"""


def test_an_overlapping_criterion_cannot_hide_an_exact_fail(cli) -> None:
    """Codex R3, and the one direction this gate must never fail in: FALSE ACCEPTANCE.

    When one criterion is a substring of another, a flat scan of every eligible row let the longer
    criterion's later PASS count as the last verdict for the shorter one -- so an explicit
    `| support csv import | FAIL |` was accepted. The most SPECIFIC match now decides: an exact row
    naming a criterion outright is never overruled by one that merely contains it.
    """
    evidence = "| support csv import | FAIL |\n| support csv import preview | PASS |\n"

    issues = _issues(cli, evidence, body=OVERLAPPING_BODY)

    assert any("FAILED AC" in issue for issue in issues)
    assert "support csv import" in " ".join(issues).lower()


def test_overlapping_criteria_both_pass_when_both_pass(cli) -> None:
    """The other direction, so specificity does not become its own false refusal."""
    evidence = "| support csv import | PASS |\n| support csv import preview | PASS |\n"

    assert _issues(cli, evidence, body=OVERLAPPING_BODY) == []


def test_a_correction_still_decides_within_the_same_specificity(cli) -> None:
    """Ranking by stage must not break the correction path: two rows naming one criterion the same
    way are still resolved by order, later wins."""
    evidence = "| support csv import | FAIL |\n| support csv import | PASS |\n| support csv import preview | PASS |\n"

    assert _issues(cli, evidence, body=OVERLAPPING_BODY) == []


def test_a_later_index_keyed_fail_overrides_an_exact_pass(cli) -> None:
    """Codex R4, a P1 false acceptance introduced by R3's own fix.

    `| AC 1 | FAIL |` names criterion 1 outright -- it is UNAMBIGUOUS, not merely less specific --
    so ranking it below an exact row discarded a later explicit failure. Ambiguity, not specificity,
    is the thing worth ranking on.
    """
    evidence = "| support csv import | PASS |\n| AC 1 | FAIL |\n"

    issues = _issues(cli, evidence, body=OVERLAPPING_BODY)

    assert any("FAILED AC" in issue for issue in issues)


def test_an_index_keyed_pass_cannot_clear_a_fail(cli) -> None:
    """`_AC_INDEX_RE` accepts any cell beginning with a number, so `| 1 smoke test | PASS |` in a
    retained CI matrix would read as a correction to criterion 1 and turn an explicit FAIL green.
    Clearing therefore requires an EXACT restatement of the criterion. Index rows still FAIL a
    criterion -- nothing that says FAIL is discarded -- they simply cannot clear one."""
    # ONE criterion, so nothing else can fail and mask the result. An earlier version of this test
    # used the two-criterion body and could not tell the fix from its absence -- the second
    # criterion failed either way, and the mutation went undetected.
    single = "## Acceptance Criteria\n\n- support csv import\n"

    evidence = "| support csv import | FAIL |\n| 1 smoke test | PASS |\n"
    assert any("FAILED AC" in issue for issue in _issues(cli, evidence, body=single))

    exact = "| support csv import | FAIL |\n| support csv import | PASS |\n"
    assert _issues(cli, exact, body=single) == []


def test_a_substring_row_never_overrides_an_unambiguous_one(cli) -> None:
    """And the R3 case stays closed: a longer criterion's row only substring-matches the shorter
    one, so it never displaces a row that names it outright."""
    evidence = "| support csv import | FAIL |\n| support csv import preview | PASS |\n"

    issues = _issues(cli, evidence, body=OVERLAPPING_BODY)

    assert any("FAILED AC" in issue for issue in issues)


def test_a_later_paraphrased_fail_is_never_ignored(cli) -> None:
    """Codex R5, a P1 false acceptance introduced by R4's own fix. No row that says FAIL is
    discarded, whatever form it takes -- the gate fails closed."""
    evidence = "| support csv import preview | PASS |\n| csv import preview | FAIL |\n"
    body = "## Acceptance Criteria\n\n- support csv import preview\n"

    issues = _issues(cli, evidence, body=body)

    assert any("FAILED AC" in issue for issue in issues)


def test_only_an_unambiguous_later_pass_clears_a_fail(cli) -> None:
    """The escape is deliberately narrow: an ambiguous row cannot clear a failure it might not even
    be about, so clearing requires naming the criterion outright."""
    body = "## Acceptance Criteria\n\n- support csv import\n- support csv import preview\n"

    ambiguous_after = "| support csv import | FAIL |\n| support csv import preview | PASS |\n"
    assert any("FAILED AC" in i for i in _issues(cli, ambiguous_after, body=body))

    exact_after = (
        "| support csv import | FAIL |\n| support csv import | PASS |\n"
        "| support csv import preview | PASS |\n"
    )
    assert _issues(cli, exact_after, body=body) == []
