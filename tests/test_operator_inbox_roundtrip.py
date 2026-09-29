"""An answer reaches its source lane and remains visible until incorporated."""
import argparse
import json
from test_ledger_readers import _write_decision_line, _write_marker


def args(target, **kw):
    return argparse.Namespace(target=[target], json=True, answer=None, text=None,
                              answers=False, ack=None, **kw)


def test_answer_resume_ack_roundtrip(cli, tmp_path, capsys):
    target = tmp_path / "lane"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-09-29T10:00:00Z",
                         summary="Choose compatible API", next_step="awaiting operator")
    assert cli.inbox(args(target)) == 0
    question = json.loads(capsys.readouterr().out)["pending"][0]
    ident = question["id"]
    answer = args(target)
    answer.answer, answer.text = ident, "Keep v1 for this release"
    assert cli.inbox(answer) == 0
    capsys.readouterr()
    assert cli.inbox(args(target)) == 0
    assert json.loads(capsys.readouterr().out)["pending"] == []
    resumed = args(target)
    resumed.answers = True
    for _ in range(2):
        assert cli.inbox(resumed) == 0
        assert json.loads(capsys.readouterr().out)["answers"][0]["answer"] == answer.text
    from tautline_methodology import operator_inbox
    assert "Keep v1" in " ".join(operator_inbox.startup_lines(target, cli))
    ack = args(target)
    ack.ack = ident
    assert cli.inbox(ack) == 0
    capsys.readouterr()
    assert cli.inbox(resumed) == 0
    assert json.loads(capsys.readouterr().out)["answers"] == []
    assert operator_inbox.startup_lines(target, cli) == []


def test_answer_rejects_unknown_id_and_secret_and_does_not_overwrite(cli, tmp_path, capsys):
    target = tmp_path / "lane"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-09-29T10:00:00Z",
                         summary="Choose", next_step="awaiting operator")
    request = args(target)
    request.answer, request.text = "not-an-id", "Yes"
    assert cli.inbox(request) == 1
    capsys.readouterr()
    cli.inbox(args(target))
    request.answer = json.loads(capsys.readouterr().out)["pending"][0]["id"]
    request.text = "ghp_" + "x" * 36
    assert cli.inbox(request) == 1
    capsys.readouterr()
    request.text = "Yes"
    assert cli.inbox(request) == 0
    capsys.readouterr()
    request.text = "No"
    assert cli.inbox(request) == 1
    capsys.readouterr()
    request.text = "Yes"
    assert cli.inbox(request) == 0  # retries are idempotent


def test_corrupt_answer_does_not_hide_question(cli, tmp_path, capsys):
    from tautline_methodology import operator_inbox
    target = tmp_path / "lane"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-09-29T10:00:00Z",
                         summary="Choose", next_step="awaiting operator")
    cli.inbox(args(target))
    ident = json.loads(capsys.readouterr().out)["pending"][0]["id"]
    directory = operator_inbox.response_dir(data, target, cli)
    directory.mkdir(parents=True)
    (directory / f"{ident}.json").write_text("{broken")
    cli.inbox(args(target))
    output = capsys.readouterr()
    assert len(json.loads(output.out)["pending"]) == 1
    assert "UNKNOWN" in output.err


def test_startup_never_scans_decision_history(cli, tmp_path, monkeypatch):
    from tautline_methodology import operator_inbox
    target = tmp_path / "lane"
    _write_marker(target, state_dir=tmp_path / "state")
    def forbidden(*a, **kw):
        raise AssertionError("startup must not scan event history")
    monkeypatch.setattr(cli, "read_countable_decisions", forbidden)
    assert operator_inbox.startup_lines(target, cli) == []


def test_answer_visibility_is_scoped_to_source_lane(cli, tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    data = _write_marker(a, state_dir=tmp_path / "state")
    _write_marker(b, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, a, seq=1, ts="2026-09-29T10:00:00Z",
                         summary="For a", next_step="awaiting operator")
    cli.inbox(args(a))
    ident = json.loads(capsys.readouterr().out)["pending"][0]["id"]
    request = args(a)
    request.answer, request.text = ident, "Proceed"
    cli.inbox(request)
    capsys.readouterr()
    request = args(b)
    request.answers = True
    cli.inbox(request)
    assert json.loads(capsys.readouterr().out)["answers"] == []


def test_nonregular_answer_is_ignored_without_waiting(cli, tmp_path, capsys):
    import os
    from tautline_methodology import operator_inbox
    target = tmp_path / "lane"
    data = _write_marker(target, state_dir=tmp_path / "state")
    directory = operator_inbox.response_dir(data, target, cli)
    directory.mkdir(parents=True)
    os.mkfifo(directory / ("a" * 20 + ".json"))
    records, warnings = operator_inbox.load([(data, target)], cli)
    assert not records
    assert "UNKNOWN" in warnings[0]


def test_session_start_surfaces_reply_and_stays_advisory(cli, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lane_status_fixtures import clean_lane
    from tautline_methodology import operator_inbox
    lane = clean_lane(tmp_path)
    marker = lane / ".tautline.json"
    marker.write_text(json.dumps({"schemaVersion": "lean-1", "project": {"name": "demo", "repo": "demo/demo"}, "integrationBranch": "main", "laneStatus": "advisory", "commands": {"test": "true"}, "workCoordination": True}))
    data = cli.ledger_target_data(lane)
    directory = operator_inbox.response_dir(data, lane, cli)
    directory.mkdir(parents=True, exist_ok=True)
    ident = "a" * 20
    row = {"schema": operator_inbox.SCHEMA, "id": ident,
           "lane_id": cli.instrumentation_lane_id(lane), "summary": "Choose",
           "answer": "Use the compatible API", "answered_at": "2026-09-29T01:00:00Z"}
    (directory / (ident + ".json")).write_text(json.dumps(row))
    assert cli.lane_status(argparse.Namespace(target=lane, hook=True, json=False, project=None)) == 0
    output = capsys.readouterr().out
    assert "WORK (local, advisory): none declared" in output
    assert "Use the compatible API" in output
    assert "inbox --answers" in output
    request = args(lane)
    request.ack = ident
    assert cli.inbox(request) == 0
    assert operator_inbox.startup_lines(lane, cli) == []
