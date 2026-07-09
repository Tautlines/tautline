import json


def _events(root):
    path = root / ".ai-runs" / "guard-events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_guard_log_event_appends_jsonl_and_truncates_detail(cli, tmp_path):
    cli.guard_log_event(tmp_path, "stop.example", True, "phrase", "x" * 250)
    cli.guard_log_event(tmp_path, "stop.example", False, "state", "ok")

    events = _events(tmp_path)
    assert [event["check_id"] for event in events] == ["stop.example", "stop.example"]
    assert events[0]["fired"] is True
    assert events[0]["mechanism"] == "phrase"
    assert len(events[0]["detail"]) == 200
    assert events[1]["fired"] is False


def test_guard_log_event_never_raises(cli, tmp_path):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("already here", encoding="utf-8")

    cli.guard_log_event(not_a_directory, "stop.example", True, "phrase", "ignored")


def test_guard_report_aggregates_counts(cli, run_cli, tmp_path):
    cli.guard_log_event(tmp_path, "stop.a", True, "phrase", "hit")
    cli.guard_log_event(tmp_path, "stop.a", False, "phrase", "miss")
    cli.guard_log_event(tmp_path, "bash.fake_monitor", False, "regex-command", "git status")

    res = run_cli("guard-report", "--target", str(tmp_path), "--json")

    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    rows = {(row["check_id"], row["mechanism"]): row for row in report["checks"]}
    assert rows[("stop.a", "phrase")] == {
        "check_id": "stop.a",
        "mechanism": "phrase",
        "evaluated": 2,
        "fired": 1,
        "fire_rate": 0.5,
    }
    assert rows[("bash.fake_monitor", "regex-command")]["evaluated"] == 1
    assert rows[("bash.fake_monitor", "regex-command")]["fire_rate"] == 0.0


def test_guard_report_rejects_invalid_since_without_traceback(run_cli, tmp_path):
    res = run_cli("guard-report", "--target", str(tmp_path), "--since", "not-a-date")

    assert res.returncode == 2
    assert "guard_report_error: invalid --since timestamp" in res.stderr
    assert "Traceback" not in res.stderr


def test_response_guard_writes_events_without_changing_decision(run_cli, tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}\n", encoding="utf-8")

    res = run_cli(
        "response-guard",
        "--stdin",
        "--target",
        str(tmp_path),
        "--active-monitor",
        stdin="Preflight is running. Yielding until then.",
    )

    assert res.returncode == 1
    events = _events(tmp_path)
    assert any(event["check_id"] == "stop.passive_monitor_phrase" and event["fired"] for event in events)
    assert any(event["check_id"] == "stop.flaky_rationalization" and not event["fired"] for event in events)


def test_bash_hook_writes_events_without_changing_decision(run_cli, tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}\n", encoding="utf-8")
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": "gh api graphql -f query='mutation{updateProjectV2Field(input:{})}'"},
        }
    )

    res = run_cli("background-command-hook", stdin=payload)

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    events = _events(tmp_path)
    assert any(event["check_id"] == "bash.board_structure" and event["fired"] for event in events)
