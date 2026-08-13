"""The board a lane reads must be the board its adapter pins.

RCA 2026-07-02: an ad-hoc `projectsV2` discovery query resolved the WRONG project, and every read
after it inherited that resolution and reported on it confidently. Nothing compared what was read
against what was configured, so the lane was not wrong about the board's contents -- it was right
about a different board.

Every synced goal source records the owner and project number it was read from. The adapter pins
the board the lane is supposed to read. This guard is the comparison nobody was making, and it
blocks on the same exit-1 path as drift because a board that is not the pinned board is not "out
of date" -- it is the wrong board.
"""
import argparse

import pytest

OWNER = "example-org"
NUMBER = 7


def _adapter(**overrides) -> dict:
    data = {
        "project": "Fixture",
        "goalTracker": {
            "enabled": True,
            "provider": "github-projects",
            "owner": OWNER,
            "projectNumber": NUMBER,
        },
        "backlogProvider": {"enabled": True, "owner": OWNER, "projectNumber": NUMBER},
        "goalArtifacts": {"sourceOfTruth": "docs/goals"},
        "laneState": {"goalRun": ".ai-work/GOAL_RUN.json"},
    }
    data.update(overrides)
    return data


def _source(cli, data, target, name: str, *, owner=OWNER, number=NUMBER, board=True) -> None:
    root = cli.goal_source_root(data, target)
    root.mkdir(parents=True, exist_ok=True)
    lines = ["# Synced item", "", "## GitHub Project Source", ""]
    if board:
        lines += [f"- owner: {owner}", f"- project_number: {number}"]
    lines += ["- status: In progress", ""]
    (root / name).write_text("\n".join(lines), encoding="utf-8")


def test_a_matching_identity_is_no_mismatch(cli, tmp_path, monkeypatch) -> None:
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    _source(cli, data, tmp_path, "matching.md")

    assert cli.board_identity_mismatches(data, tmp_path) == []


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [("owner", "someone-else", "someone-else"), ("number", 99, "99")],
)
def test_a_source_synced_from_another_board_is_named(
    cli, tmp_path, monkeypatch, field, value, named
) -> None:
    """The refusal names BOTH the recorded value and the pin, because "they disagree" is not
    actionable -- which one is wrong is the operator's call and they need to see both."""
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    kwargs = {"owner": value} if field == "owner" else {"number": value}
    _source(cli, data, tmp_path, "foreign.md", **kwargs)

    mismatches = cli.board_identity_mismatches(data, tmp_path)

    assert len(mismatches) == 1, mismatches
    assert "foreign.md" in mismatches[0]
    assert named in mismatches[0]
    assert (OWNER if field == "owner" else str(NUMBER)) in mismatches[0]
    assert "different board" in mismatches[0]


def test_a_source_with_no_board_lines_is_never_guessed_about(cli, tmp_path, monkeypatch) -> None:
    """Silence is the only honest answer for a source that records no identity: it predates this
    record or came from another path. Inventing a mismatch from an absent fact would make the
    guard the same confident-wrong it exists to catch."""
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    _source(cli, data, tmp_path, "legacy.md", board=False)

    assert cli.board_identity_mismatches(data, tmp_path) == []


def test_an_unpinned_adapter_makes_no_claim(cli, tmp_path, monkeypatch) -> None:
    """No pin, no comparison. A `projectNumber` of 0 is the schema default, not a board."""
    for tracker in ({"enabled": True, "owner": "", "projectNumber": NUMBER},
                    {"enabled": True, "owner": OWNER, "projectNumber": 0}):
        data = _adapter(goalTracker=tracker)
        monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
        _source(cli, data, tmp_path, "any.md", owner="someone-else")

        assert cli.board_identity_mismatches(data, tmp_path) == []


def test_the_gate_blocks_on_a_mismatch_and_names_it(cli, tmp_path, monkeypatch, capsys) -> None:
    data = _adapter()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "provider_board_currency_issues", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(cli, "print_provider_board_business_lead_warnings", lambda *a, **k: None)
    monkeypatch.setattr(cli, "print_unplaced_customer_facing_issue_warnings", lambda *a, **k: None)
    _source(cli, data, tmp_path, "foreign.md", number=99)

    code = cli.backlog_provider_board_check(argparse.Namespace(project=None, target=tmp_path))

    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "backlog_provider_board_identity:" in captured.err
    assert "99" in captured.err and str(NUMBER) in captured.err
    # The refusal has to say what to do, and BOTH directions are live: the sources may be stale, or
    # the pin itself may be the thing that is wrong.
    assert "re-sync" in captured.err
    assert "projectNumber" in captured.err


def test_the_ok_path_states_which_board_it_checked(cli, tmp_path, monkeypatch, capsys) -> None:
    """A gate that passes silently cannot be distinguished from a gate that did not run -- and for
    this particular gate, "which board" is the entire question."""
    data = _adapter()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "provider_board_currency_issues", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(cli, "print_provider_board_business_lead_warnings", lambda *a, **k: None)
    monkeypatch.setattr(cli, "print_unplaced_customer_facing_issue_warnings", lambda *a, **k: None)
    _source(cli, data, tmp_path, "matching.md")

    code = cli.backlog_provider_board_check(argparse.Namespace(project=None, target=tmp_path))

    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert f"board_identity: {OWNER}/projects/{NUMBER}" in captured.out


def test_an_unrelated_owner_bullet_elsewhere_in_the_plan_is_not_the_board_identity(
    cli, tmp_path, monkeypatch
) -> None:
    """Codex R1 P2. A whole-document regex reads any `- owner:` bullet a plan happens to contain --
    a requirements list, a stakeholder table -- and this gate BLOCKS, so a false positive stops a
    lane over prose. Identity is read only from the generated `## GitHub Project Source` section,
    which is exactly where the sync writes it."""
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    root = cli.goal_source_root(data, tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prose.md").write_text(
        "\n".join([
            "# A plan that talks about owners",
            "",
            "## Stakeholders",
            "",
            "- owner: someone-else",
            "- project_number: 999",
            "",
            "## GitHub Project Source",
            "",
            f"- owner: {OWNER}",
            f"- project_number: {NUMBER}",
            "",
        ]),
        encoding="utf-8",
    )

    assert cli.board_identity_mismatches(data, tmp_path) == []


def test_a_plan_with_no_source_section_at_all_is_never_guessed_about(
    cli, tmp_path, monkeypatch
) -> None:
    """The same rule from the other side: prose that mentions an owner but carries no generated
    source section records no board identity, so there is nothing to compare."""
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    root = cli.goal_source_root(data, tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prose-only.md").write_text(
        "# Notes\n\n## Stakeholders\n\n- owner: someone-else\n", encoding="utf-8"
    )

    assert cli.board_identity_mismatches(data, tmp_path) == []
