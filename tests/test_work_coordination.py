"""Coordination must inform peers across real worktrees without adding gates or network I/O."""
import json
import subprocess
import time
from pathlib import Path

import pytest

from tautline_methodology import work


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def lanes(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "init")
    a, b = tmp_path / "a", tmp_path / "b"
    git(main, "worktree", "add", "-b", "feature-a", str(a))
    git(main, "worktree", "add", "-b", "feature-b", str(b))
    return a, b


def run(cli, target, *args):
    return cli.main(["work", *args, "--target", str(target)])


def test_sibling_sees_intent_overlap_and_completion(cli, lanes, capsys):
    a, b = lanes
    assert run(cli, a, "declare", "Implement auth", "--path", "src/auth", "--interface", "auth-v2", "--item", "42") == 0
    capsys.readouterr()
    assert run(cli, b, "status") == 0
    text = capsys.readouterr().out
    assert "Implement auth" in text and "src/auth" in text and "auth-v2" in text
    assert "feature-a" in text and "42" in text
    assert run(cli, b, "declare", "Update login", "--path", "src/auth/login.py", "--interface", "auth-v2") == 0
    assert "OVERLAP" in capsys.readouterr().out
    assert run(cli, a, "finish", "--pr", "https://github.com/example/app/pull/1") == 0
    capsys.readouterr()
    assert run(cli, b, "status") == 0
    assert "OVERLAP" not in capsys.readouterr().out
    assert run(cli, b, "status", "--all", "--json") == 0
    records = json.loads(capsys.readouterr().out)["records"]
    completed = next(r for r in records if r["goal"] == "Implement auth")
    assert completed["status"] == "completed" and completed["pr"].endswith("/1")


def test_stale_crashed_removed_and_malformed_never_look_idle(cli, lanes, capsys):
    a, b = lanes
    run(cli, a, "declare", "Handle requests")
    state = work.snapshot(b)
    path = Path(state["store"]) / (state["records"][0]["lane"] + ".json")
    record = json.loads(path.read_text())
    record["updatedAt"] = time.time() - 25 * 3600
    path.write_text(json.dumps(record))
    assert work.snapshot(b)["records"][0]["state"] == "STALE"
    assert run(cli, a, "update", "--status", "blocked", "--blocker", "Needs schema answer") == 0
    assert work.snapshot(b)["records"][0]["state"] == "BLOCKED"
    git(a, "switch", "-c", "different-work")
    assert work.snapshot(b)["records"][0]["state"] == "STALE"
    run(cli, a, "update")
    git(b, "worktree", "remove", "--force", str(a))
    assert work.snapshot(b)["records"][0]["state"] == "STALE"
    path.write_text("{")
    assert work.snapshot(b)["records"][0]["state"] == "UNKNOWN"
    assert run(cli, b, "status") == 0
    assert "UNKNOWN" in capsys.readouterr().out


def test_no_false_prefix_overlap_and_abandoned_claims_retire(cli, lanes, capsys):
    a, b = lanes
    run(cli, a, "declare", "auth", "--path", "src/auth")
    run(cli, b, "declare", "author", "--path", "src/author.py")
    assert work.snapshot(b)["overlaps"] == []
    run(cli, b, "update", "--path", "src/auth")
    assert len(work.snapshot(b)["overlaps"]) == 1
    run(cli, a, "abandon")
    assert work.snapshot(b)["overlaps"] == []


@pytest.mark.parametrize("path", ["../other", "/etc/passwd", "src/../../other", "src/*.py"])
def test_invalid_scope_is_rejected_without_clobber(cli, lanes, path, capsys):
    a, b = lanes
    run(cli, a, "declare", "Valid", "--path", "src")
    assert run(cli, a, "update", "--path", path) == 1
    assert work.snapshot(b)["records"][0]["paths"] == ["src"]


def test_advisory_opt_in_no_store_and_unreadable_store(cli, lanes, capsys):
    a, b = lanes
    assert work.advisory_lines(b) == []
    assert "none declared" in work.advisory_lines(b, {"workCoordination": True})[0]
    run(cli, a, "declare", "Shared work", "--lane", "agent-a")
    run(cli, a, "declare", "Other work", "--lane", "agent-b")
    assert len(work.snapshot(b)["records"]) == 2
    store = Path(work.snapshot(b)["store"])
    (store / "broken.json").write_text("null")
    assert any("UNKNOWN" in line for line in work.advisory_lines(b))


def test_backlog_take_advisory_never_blocks(cli, lanes, capsys):
    a, b = lanes
    cfg = {"schemaVersion": "lean-1", "project": {"name": "test"}, "integrationBranch": "main", "commands": {"test": "true"}, "backlog": {"provider": "local"}}
    (b / ".tautline.json").write_text(json.dumps(cfg))
    run(cli, a, "declare", "Peer task", "--path", "src")
    assert cli.main(["backlog", "add", "Next task", "--target", str(b)]) == 0
    capsys.readouterr()
    assert cli.main(["backlog", "take", "--target", str(b)]) == 0
    captured = capsys.readouterr()
    assert "Peer task" in captured.err
    assert "take:" in captured.out


def test_session_start_sees_peer_scope(cli, lanes, capsys):
    a, b = lanes
    (b / ".tautline.json").write_text(json.dumps({
        "schemaVersion": "lean-1", "project": {"name": "test"},
        "integrationBranch": "main", "commands": {"test": "true"},
    }))
    run(cli, a, "declare", "Peer feature", "--path", "src/widget")
    capsys.readouterr()
    assert cli.main(["lane-status", "--hook", "--target", str(b)]) == 0
    assert "Peer feature" in capsys.readouterr().out


def test_future_and_missing_fields_are_unknown(cli, lanes):
    a, b = lanes
    run(cli, a, "declare", "Present")
    state = work.snapshot(b)
    path = Path(state["store"]) / (state["records"][0]["lane"] + ".json")
    record = json.loads(path.read_text())
    record["updatedAt"] = time.time() + 60
    path.write_text(json.dumps(record))
    assert work.snapshot(b)["records"][0]["state"] == "UNKNOWN"
    record.pop("goal")
    path.write_text(json.dumps(record))
    assert work.snapshot(b)["records"][0]["state"] == "UNKNOWN"


def test_removed_lane_can_be_explicitly_retired_from_a_peer(cli, lanes):
    a, b = lanes
    run(cli, a, "declare", "Old work", "--lane", "old-agent")
    git(b, "worktree", "remove", "--force", str(a))
    assert run(cli, b, "abandon", "--lane", "old-agent") == 0
    record = work.snapshot(b)["records"][0]
    assert record["state"] == "ABANDONED"
    assert record["worktree"] == str(a)


def test_init_guidance_defaults_and_disable_flag(cli, tmp_path):
    from tautline_methodology import lean
    for name, flags, enabled in (("on", [], True), ("off", ["--no-work-coordination"], False)):
        target = tmp_path / name
        target.mkdir()
        assert cli.main(["init", "--target", str(target), "--yes", *flags]) == 0
        cfg = json.loads((target / ".tautline.json").read_text())
        assert cfg["workCoordination"] is enabled
        assert (lean.WORK_COORDINATION_LINE in (target / "AGENTS.md").read_text()) is enabled
    cfg["workCoordination"] = "strict"
    assert "workCoordination: expected boolean" in lean.lean_config_errors(cfg)


def test_bad_store_is_unknown_and_does_not_follow_a_symlink(cli, lanes, tmp_path, capsys):
    a, b = lanes
    store = Path(work.identity(b)["store"])
    outside = tmp_path / "outside"
    outside.mkdir()
    store.parent.symlink_to(outside, target_is_directory=True)
    assert "UNKNOWN" in work.advisory_lines(b)[0]
    assert run(cli, b, "declare", "Should fail clearly") == 1
    assert list(outside.iterdir()) == []


def test_corrupt_record_cannot_block_taking_work(cli, lanes, capsys):
    a, b = lanes
    cfg = {"schemaVersion": "lean-1", "project": {"name": "test"}, "integrationBranch": "main", "commands": {"test": "true"}, "backlog": {"provider": "local"}}
    (b / ".tautline.json").write_text(json.dumps(cfg))
    run(cli, a, "declare", "Peer task")
    store = Path(work.snapshot(b)["store"])
    (store / "broken.json").write_text("{")
    assert cli.main(["backlog", "add", "Next task", "--target", str(b)]) == 0
    capsys.readouterr()
    assert cli.main(["backlog", "take", "--target", str(b)]) == 0
    assert "UNKNOWN" in capsys.readouterr().err


@pytest.mark.parametrize("key,value", [("updatedAt", 10 ** 400), ("worktree", "relative/path")])
def test_invalid_numeric_or_path_identity_is_unknown_per_record(cli, lanes, key, value):
    a, b = lanes
    run(cli, a, "declare", "Corrupt me", "--lane", "agent-a")
    run(cli, b, "declare", "Still readable", "--lane", "agent-b")
    path = Path(work.snapshot(b)["store"]) / "agent-a.json"
    record = json.loads(path.read_text())
    record[key] = value
    path.write_text(json.dumps(record))
    records = work.snapshot(b)["records"]
    assert records[0]["state"] == "UNKNOWN"
    assert records[1]["state"] == "ACTIVE"
