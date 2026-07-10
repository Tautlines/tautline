"""RCA Jun-17 / Jun-16 #234: the board gate must reason about the lane's actual outgoing
work (current branch + its open PR's closing issues + active ledger), not an unrelated ledger."""


def test_branch_issue_number_parses_trailing_number(cli):
    assert cli.branch_issue_number("fix/example-saas-live-m2-334") == "334"
    assert cli.branch_issue_number("feature/no-number") == ""
    assert cli.branch_issue_number("main") == ""


def test_outgoing_issue_refs_from_open_pr_and_branch(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "run_git", lambda target, args: "fix/orders-334")
    monkeypatch.setattr(
        cli,
        "command_json",
        lambda args, target, timeout=15: (
            0,
            [{"number": 12, "closingIssuesReferences": [{"number": 334}, {"number": 301}]}],
            "",
        ),
    )
    refs = cli.lane_outgoing_issue_refs(tmp_path, "fix/orders-334")
    assert "334" in refs and "301" in refs  # PR-closed issues + branch number, deduped


def test_outgoing_issue_refs_no_pr_falls_back_to_branch_number(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "command_json", lambda args, target, timeout=15: (0, [], ""))
    refs = cli.lane_outgoing_issue_refs(tmp_path, "fix/orders-334")
    assert refs == ["334"]


def test_work_scope_collects_ledger_and_outgoing(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "run_git", lambda target, args: "fix/orders-334")
    monkeypatch.setattr(cli, "command_json", lambda args, target, timeout=15: (0, [], ""))
    monkeypatch.setattr(cli, "goal_run_path", lambda data, target: tmp_path / "GOAL_RUN.json")
    (tmp_path / "GOAL_RUN.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "load_goal_run", lambda data, target: {"goalId": "x"})
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda data, target, run: "")
    scope = cli.lane_work_scope({}, tmp_path)
    assert scope["outgoing_issue_numbers"] == ["334"]
    assert scope["unresolved_ledger"] is True  # ledger exists but has no project link


def test_board_item_matches_issue_numbers(cli):
    item = {"content": {"url": "https://github.com/o/r/issues/334"}}
    assert cli.board_item_matches_issue_numbers(item, ["334"]) is True
    assert cli.board_item_matches_issue_numbers(item, ["33"]) is False  # no partial-suffix match
    assert cli.board_item_matches_issue_numbers(item, ["999"]) is False
