import argparse
import json
import os
import time


def _args(target, boundary="prepush"):
    return argparse.Namespace(project=None, target=target, boundary=boundary)


def test_guard_check_prepush_composes_existing_state_gates(cli, monkeypatch, tmp_path, capsys):
    calls = []

    def ok(label):
        def _inner(args):
            calls.append((label, args.target, getattr(args, "strict", None)))
            print(f"{label}: ok")
            return 0

        return _inner

    monkeypatch.setattr(cli, "review_evidence_check", ok("review"))
    monkeypatch.setattr(cli, "backlog_provider_board_check", ok("board"))
    monkeypatch.setattr(cli, "ci_health_check", ok("ci"))

    rc = cli.guard_check(_args(tmp_path))

    assert rc == 0
    assert calls == [
        ("review", tmp_path.resolve(strict=False), True),
        ("board", tmp_path.resolve(strict=False), False),
        ("ci", tmp_path.resolve(strict=False), False),
    ]
    out = capsys.readouterr().out
    assert "guard_check_boundary: prepush" in out
    assert "guard_check: ok" in out


def test_guard_check_prepush_stops_on_review_evidence_failure(cli, monkeypatch, tmp_path, capsys):
    calls = []

    def fail_review(args):
        calls.append("review")
        return 7

    def unexpected(args):
        calls.append("unexpected")
        return 0

    monkeypatch.setattr(cli, "review_evidence_check", fail_review)
    monkeypatch.setattr(cli, "backlog_provider_board_check", unexpected)
    monkeypatch.setattr(cli, "ci_health_check", unexpected)

    rc = cli.guard_check(_args(tmp_path))

    assert rc == 7
    assert calls == ["review"]
    assert "guard_check_failed: review evidence" in capsys.readouterr().err


def test_guard_check_prepush_stops_on_board_currency_failure(cli, monkeypatch, tmp_path, capsys):
    calls = []

    def ok_review(args):
        calls.append("review")
        return 0

    def fail_board(args):
        calls.append("board")
        return 1

    def unexpected(args):
        calls.append("unexpected")
        return 0

    monkeypatch.setattr(cli, "review_evidence_check", ok_review)
    monkeypatch.setattr(cli, "backlog_provider_board_check", fail_board)
    monkeypatch.setattr(cli, "ci_health_check", unexpected)

    assert cli.guard_check(_args(tmp_path)) == 1
    assert calls == ["review", "board"]
    assert "guard_check_failed: board currency" in capsys.readouterr().err


def test_guard_check_blocks_stale_blocker_before_adapter_loading(run_cli, tmp_path):
    lane = tmp_path / "lane"
    path = lane / ".ai-work" / "BLOCKER.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "minervit-blocker/v1",
                "ts": "2026-07-03T00:00:00Z",
                "kind": "credentials",
                "reason": "Waiting for credentials.",
                "artifact": None,
                "goal_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    old = time.time() - (31 * 60)
    os.utime(path, (old, old))

    res = run_cli("guard-check", "--target", str(lane), "--boundary", "prepush")

    assert res.returncode == 1
    assert "guard_check_blocker_issue: stale BLOCKER.json (older-than-30-minutes)" in res.stderr
    assert "No project adapter found" not in res.stderr


def test_guard_check_status_boundary_reports_stale_blocker_without_prose_scan(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()

    res = run_cli("guard-check", "--target", str(lane), "--boundary", "status")

    assert res.returncode == 0, res.stderr
    assert "guard_check_blocker: none" in res.stdout
    assert "guard_check: ok" in res.stdout
