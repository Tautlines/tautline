"""RCA: the board's physical order is the work order (default), with per-lane epic assignment."""

import argparse


def test_sort_key_board_uses_order_then_position(cli):
    # Board order: (order_value, position) — ignores priority/status group.
    assert cli.goal_tracker_next_sort_key("board", 0, 5, 3.0, 2) == (3.0, 2)
    # explicit orderField value dominates over board list position
    rows = sorted([(0, 0, 5.0, 0), (0, 9, 1.0, 3)], key=lambda r: cli.goal_tracker_next_sort_key("board", *r))
    assert rows[0] == (0, 9, 1.0, 3)  # lower order value wins even at a later list position
    # with equal order values (e.g. no orderField → order==position), position decides
    rows = sorted([(0, 0, 3.0, 3), (0, 9, 1.0, 1)], key=lambda r: cli.goal_tracker_next_sort_key("board", *r))
    assert rows[0] == (0, 9, 1.0, 1)


def test_sort_key_priority_uses_priority_then_position(cli):
    rows = sorted([(0, 9, 0.0, 0), (0, 0, 0.0, 1)], key=lambda r: cli.goal_tracker_next_sort_key("priority", *r))
    assert rows[0] == (0, 0, 0.0, 1)  # better priority rank wins despite later position


def test_board_order_value_parsing(cli):
    assert cli.board_order_value("3") == 3.0
    assert cli.board_order_value("rank 12") == 12.0
    assert cli.board_order_value("") == float("inf")
    assert cli.board_order_value("none") == float("inf")


def test_board_work_order_default_is_board(cli):
    assert cli.board_work_order({"backlogProvider": {"enabled": True}, "goalTracker": {"enabled": False}}) == "board"
    assert cli.board_work_order(
        {"backlogProvider": {"enabled": True, "workOrder": "priority"}, "goalTracker": {"enabled": False}}
    ) == "priority"
    # unknown value degrades to board
    assert cli.board_work_order({"backlogProvider": {"enabled": True, "workOrder": "weird"}, "goalTracker": {}}) == "board"


def test_board_epic_field(cli):
    assert cli.board_epic_field({"backlogProvider": {"enabled": True, "epicField": "Epic"}, "goalTracker": {}}) == "Epic"
    assert cli.board_epic_field({"backlogProvider": {"enabled": False}, "goalTracker": {"enabled": True, "epicField": "Theme"}}) == "Theme"
    assert cli.board_epic_field({"backlogProvider": {"enabled": True}, "goalTracker": {}}) == ""


def _args(epic=None):
    return argparse.Namespace(epic=epic)


def test_lane_assigned_epics_from_flags_and_env(cli, monkeypatch):
    monkeypatch.delenv("MINERVIT_LANE_EPICS", raising=False)
    assert cli.lane_assigned_epics(_args(["Checkout", "Storefront"])) == ["Checkout", "Storefront"]
    # comma-splitting + de-dup (case-insensitive)
    assert cli.lane_assigned_epics(_args(["Checkout, checkout ,Storefront"])) == ["Checkout", "Storefront"]
    # no flags -> fall back to env
    assert cli.lane_assigned_epics(_args(None)) == []
    monkeypatch.setenv("MINERVIT_LANE_EPICS", "Billing, Storefront")
    assert cli.lane_assigned_epics(_args(None)) == ["Billing", "Storefront"]
    # explicit flags override env
    assert cli.lane_assigned_epics(_args(["Checkout"])) == ["Checkout"]


def test_selection_mode_marks_other_epics_out_of_scope(cli, capsys, monkeypatch):
    monkeypatch.delenv("MINERVIT_LANE_EPICS", raising=False)
    data = {"backlogProvider": {"enabled": True}, "goalTracker": {"enabled": False}}
    # Epics assigned: selection mode must state that other epics are out of scope without direction,
    # so a lane handed ordering discretion does not silently widen to the whole board.
    cli.print_board_selection_mode(data, _args(["Checkout"]), "goal_tracker_next")
    out = capsys.readouterr().out
    assert "goal_tracker_next_assigned_epics: Checkout" in out
    assert "goal_tracker_next_epic_scope:" in out
    assert "without explicit operator direction" in out
    # No epic assigned: the board top is in scope, so there is no out-of-scope restriction line.
    cli.print_board_selection_mode(data, _args(None), "goal_tracker_next")
    out2 = capsys.readouterr().out
    assert "no epic assigned" in out2
    assert "_epic_scope:" not in out2
