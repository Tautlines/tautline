"""Real bare remotes prove advisory work survives multiple independent clones."""
import json
import subprocess
import time

import pytest

from tautline_methodology import work_git


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clones(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    a, b = tmp_path / "a", tmp_path / "b"
    for clone in (a, b):
        git(tmp_path, "clone", str(remote), str(clone))
        git(clone, "config", "user.name", "Test")
        git(clone, "config", "user.email", "test@example.invalid")
        git(clone, "commit", "--allow-empty", "-m", "local code")
    return a, b, remote


def config(**overrides):
    return {"backend": "git", "remote": "origin", "branch": "tautline/work", "syncIntervalSeconds": 60, "timeoutSeconds": 2, **overrides}


def record(goal="Handle auth", status="active"):
    return {"schema": "tautline-work/v1", "lane": "agent", "goal": goal,
            "worktree": "/private/project", "gitDir": "/private/project/.git",
            "branch": "feature", "paths": ["src/auth"], "interfaces": [], "dependsOn": [],
            "item": "", "pr": "", "blocker": "", "status": status,
            "updatedAt": time.time(), "expiresHours": 24}


def test_cross_clone_identity_privacy_and_terminal_state(clones):
    a, b, remote = clones
    before = {p: (git(p, "rev-parse", "HEAD"), git(p, "status", "--porcelain")) for p in (a, b)}
    first = work_git.sync(a, config(), [record()], publish=True)
    assert first["sync"]["state"] == "fresh", first
    second = work_git.sync(b, config(), [record("Other owner")], publish=True)
    assert second["sync"]["state"] == "fresh", second
    assert first["namespace"] != second["namespace"]
    assert len(second["records"]) == 2
    raw = git(remote, "show", f"refs/heads/tautline/work:records/{first['namespace']}/agent.json")
    assert "/private/project" not in raw and "gitDir" not in raw and "worktree" not in raw
    work_git.sync(a, config(), [record(status="completed")], publish=True)
    done = work_git.sync(b, config(), [], force=True)
    assert {r["status"] for r in done["records"]} == {"active", "completed"}
    assert before == {p: (git(p, "rev-parse", "HEAD"), git(p, "status", "--porcelain")) for p in (a, b)}
    assert all(git(p, "rev-parse", "--is-shallow-repository") == "false" for p in (a, b))


def test_push_race_refetches_and_preserves_other_owner(clones, monkeypatch):
    a, b, _ = clones
    # This test inserts another complete sync inside the first one to force a race.
    # Exercise merge correctness without charging both operations to the default budget;
    # dedicated timeout tests cover the short production deadline.
    original = work_git._run
    raced = False
    def run(root, args, *pos, **kw):
        nonlocal raced
        if root == a and "push" in args and not raced:
            raced = True
            peer = work_git.sync(b, config(timeoutSeconds=10), [record("Racing owner")], publish=True)
            assert peer["sync"]["state"] == "fresh", peer
        return original(root, args, *pos, **kw)
    monkeypatch.setattr(work_git, "_run", run)
    state = work_git.sync(a, config(timeoutSeconds=10), [record()], publish=True)
    assert state["sync"]["state"] == "fresh", state
    assert {r["goal"] for r in state["records"]} == {"Handle auth", "Racing owner"}


def test_offline_is_cached_and_pending_retries(clones):
    a, b, remote = clones
    work_git.sync(a, config(), [record()], publish=True)
    old = work_git.sync(b, config(), [], force=True)
    assert len(old["records"]) == 1
    hidden = remote.with_name("offline.git")
    remote.rename(hidden)
    try:
        failed = work_git.sync(b, config(), [record("Pending local")], publish=True)
        assert failed["sync"]["state"] == "offline"
        assert failed["sync"]["pending"] and len(failed["records"]) == 1
        assert failed["sync"]["lastSuccess"] == old["sync"]["lastSuccess"]
        assert str(remote) not in failed["sync"]["error"]
    finally:
        hidden.rename(remote)
    recovered = work_git.sync(b, config(syncIntervalSeconds=0), [record("Pending local")])
    assert not recovered["sync"]["pending"] and len(recovered["records"]) == 2


def test_cache_and_no_sync_do_no_network(clones, monkeypatch):
    a, _, _ = clones
    work_git.sync(a, config(), [record()], publish=True)
    original = work_git._run
    def run(root, args, *pos, **kw):
        assert "fetch" not in args and "push" not in args and "ls-remote" not in args
        return original(root, args, *pos, **kw)
    monkeypatch.setattr(work_git, "_run", run)
    assert work_git.sync(a, config(), [])['sync']['state'] == "cached"
    assert work_git.sync(a, config(), [record("Unpublished")], publish=True, refresh=False)['sync']['pending']


def test_existing_code_branch_is_never_overwritten(clones):
    a, _, remote = clones
    git(a, "push", "origin", "HEAD:refs/heads/main")
    old = git(remote, "rev-parse", "refs/heads/main")
    state = work_git.sync(a, config(branch="main"), [record()], publish=True)
    assert state["sync"]["state"] == "unknown"
    assert "metadata branch" in state["sync"]["error"]
    assert git(remote, "rev-parse", "refs/heads/main") == old


def test_corrupt_remote_record_is_unknown_without_hiding_valid_peer(clones, tmp_path):
    a, b, remote = clones
    first = work_git.sync(a, config(), [record()], publish=True)
    edit = tmp_path / "metadata"
    git(tmp_path, "clone", "--branch", "tautline/work", str(remote), str(edit))
    git(edit, "config", "user.name", "Test")
    git(edit, "config", "user.email", "test@example.invalid")
    bad = edit / "records" / ("a" * 32)
    bad.mkdir(parents=True)
    (bad / "bad.json").write_text(json.dumps({"goal": "oops"}))
    git(edit, "add", ".")
    git(edit, "commit", "-m", "invalid peer")
    git(edit, "push", "origin", "HEAD")
    state = work_git.sync(b, config(), [], force=True)
    assert state["sync"]["state"] == "unknown"
    assert len(state["records"]) == 1 and state["records"][0]["namespace"] == first["namespace"]
    assert "invalid" in state["sync"]["error"]


def test_sibling_worktrees_share_namespace_and_disable_sync_keeps_pending(clones, tmp_path):
    a, b, _ = clones
    sibling = tmp_path / "sibling"
    git(a, "worktree", "add", "-b", "parallel", str(sibling))
    original = record()
    first = work_git.sync(a, config(), [original], publish=True)
    peer = work_git.sync(sibling, config(), [original], refresh=False)
    assert peer["namespace"] == first["namespace"]
    changed = record("Changed while offline")
    pending = work_git.sync(sibling, config(), [changed], publish=True, refresh=False)
    assert pending["sync"]["pending"]
    resumed = work_git.sync(a, config(syncIntervalSeconds=0), [changed])
    assert resumed["sync"]["state"] == "fresh" and not resumed["sync"]["pending"]
    assert work_git.sync(b, config(), [], force=True)["records"][0]["goal"] == "Changed while offline"


def test_busy_sync_does_not_overwrite_cache_or_block_local_work(clones, monkeypatch):
    a, _, _ = clones
    original_record = record()
    first = work_git.sync(a, config(), [original_record], publish=True)
    cache, _ = work_git._locations(a, config())
    previous = (cache / "state.json").read_bytes()
    original = work_git._run
    observed = []
    def run(root, args, *pos, **kw):
        if "fetch" in args and not observed:
            observed.append(True)
            busy = work_git.sync(a, config(), [record("New local scope")], publish=True)
            assert busy["sync"]["pending"]
            assert "in progress" in busy["sync"]["error"]
            assert (cache / "state.json").read_bytes() == previous
        return original(root, args, *pos, **kw)
    monkeypatch.setattr(work_git, "_run", run)
    assert work_git.sync(a, config(), [original_record], force=True)["namespace"] == first["namespace"]


def test_deadline_kills_git_and_descendant_with_open_pipes(tmp_path):
    import os
    import shlex
    import signal
    import sys
    helper = tmp_path / "stall.py"
    pidfile = tmp_path / "child.pid"
    heartbeat = tmp_path / "heartbeat"
    descendant = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]);\nwhile True: p.write_text(str(time.time())); time.sleep(0.03)"
    helper.write_text("import pathlib, subprocess, sys, time\np = subprocess.Popen([sys.executable, '-c', " + repr(descendant) + ", " + repr(str(heartbeat)) + "])\npathlib.Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(60)\n")
    git(tmp_path, "init")
    command = "!" + " ".join(shlex.quote(str(value)) for value in (sys.executable, helper, pidfile))
    started = time.monotonic()
    try:
        with pytest.raises(work_git.SyncError, match="time budget expired"):
            work_git._run(tmp_path, ["-c", "alias.stall=" + command, "stall"], started + 0.3)
        assert time.monotonic() - started < 1
        assert pidfile.exists(), "the descendant must start to exercise pipe cleanup"
        assert heartbeat.exists()
        stopped = heartbeat.read_text()
        time.sleep(0.1)
        assert heartbeat.read_text() == stopped, "descendant survived transport timeout"
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_metadata_publish_does_not_run_project_hooks(clones):
    a, _, _ = clones
    hook = a / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nexit 99\n")
    hook.chmod(0o755)
    assert work_git.sync(a, config(), [record()], publish=True)["sync"]["state"] == "fresh"
    assert "[skip ci]" in git(clones[2], "log", "-1", "--format=%s", "refs/heads/tautline/work")


def test_malformed_huge_timestamp_is_rejected_without_overflow():
    value = record()
    value.pop("gitDir")
    value.pop("worktree")
    value["namespace"] = "a" * 32
    value["updatedAt"] = 10 ** 400
    with pytest.raises(work_git.MetadataError, match="timestamp"):
        work_git.validate_record(value)


def test_split_fetch_and_push_destinations_are_not_reported_synced(clones, tmp_path):
    a, _, remote = clones
    other = tmp_path / "different.git"
    git(tmp_path, "init", "--bare", str(other))
    git(a, "remote", "set-url", "--push", "origin", str(other))
    state = work_git.sync(a, config(), [record()], publish=True)
    assert state["sync"]["state"] == "unknown" and state["sync"]["pending"]
    assert "matching fetch and push" in state["sync"]["error"]
    assert git(remote, "for-each-ref", "refs/heads/tautline/work") == ""
    assert git(other, "for-each-ref", "refs/heads/tautline/work") == ""


@pytest.mark.parametrize("field,value", [("lastSuccess", "yesterday"), ("lastAttempt", True), ("lastAttempt", 10 ** 400), ("lastSuccess", float("nan")), ("lastSuccess", 1e12), ("state", []), ("pending", "yes")])
def test_malformed_sync_cache_is_unknown_and_can_recover(clones, field, value):
    a, _, _ = clones
    own = record()
    work_git.sync(a, config(), [own], publish=True)
    cache, _ = work_git._locations(a, config())
    stored = json.loads((cache / "state.json").read_text())
    stored[field] = value
    (cache / "state.json").write_text(json.dumps(stored))
    offline = work_git.sync(a, config(), [own], refresh=False)
    assert offline["sync"]["state"] == "unknown"
    assert offline["sync"]["lastSuccess"] is None
    assert len(offline["records"]) == 1
    recovered = work_git.sync(a, config(), [own])
    assert recovered["sync"]["state"] == "fresh"


def test_never_fetched_busy_cache_does_not_imply_empty_remote(clones):
    import fcntl
    a, _, _ = clones
    cache, _ = work_git._locations(a, config())
    with (cache / "sync.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = work_git.sync(a, config(), [])
        assert state["sync"]["state"] == "unknown"
        assert state["sync"]["lastSuccess"] is None
        assert not (cache / "state.json").exists()


def test_fifo_lock_cannot_hang_startup(clones):
    import os
    a, _, _ = clones
    cache, _ = work_git._locations(a, config())
    os.mkfifo(cache / "sync.lock")
    started = time.monotonic()
    state = work_git.sync(a, config(), [])
    assert time.monotonic() - started < 0.5
    assert state["sync"]["state"] == "offline"
    assert "not a regular file" in state["sync"]["error"]


def test_delayed_snapshot_cannot_overwrite_a_newer_same_clone_publication(clones):
    a, b, _ = clones
    old = record("Old scope")
    current = [old]
    work_git.sync(a, config(), current, publish=True)
    newer = record("Completed scope", status="completed")
    # File replacement order is authoritative even if the owner's wall clock went backwards.
    newer["updatedAt"] = old["updatedAt"] - 60
    current[:] = [newer]
    work_git.sync(a, config(), current, publish=True)
    late = work_git.sync(a, config(), [old], publish=True, load_local=lambda: list(current))
    assert late["sync"]["state"] == "fresh" and not late["sync"]["pending"]
    observed = work_git.sync(b, config(), [], force=True)
    assert observed["records"][0]["goal"] == "Completed scope"
    assert observed["records"][0]["status"] == "completed"


def test_local_change_during_push_stays_pending_then_publishes_current_file(clones, monkeypatch):
    a, b, _ = clones
    old = record("Scope before push")
    current = [old]
    original = work_git._publish
    changed = False
    def publish(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if result and not changed:
            changed = True
            current[:] = [record("Scope changed during push")]
        return result
    monkeypatch.setattr(work_git, "_publish", publish)
    state = work_git.sync(a, config(), [old], publish=True, load_local=lambda: list(current))
    assert state["sync"]["state"] == "pending" and state["sync"]["pending"]
    assert state["records"][0]["goal"] == "Scope before push"
    retried = work_git.sync(a, config(syncIntervalSeconds=0), [old], load_local=lambda: list(current))
    assert retried["sync"]["state"] == "fresh" and not retried["sync"]["pending"]
    observed = work_git.sync(b, config(), [], force=True)
    assert observed["records"][0]["goal"] == "Scope changed during push"
