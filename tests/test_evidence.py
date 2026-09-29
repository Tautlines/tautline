"""Receipts describe what actually ran against this working tree, without becoming a gate."""
import json
import os
import select
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tautline_methodology import evidence


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (("init", "-qb", "main"), ("config", "user.email", "test@example.invalid"),
                 ("config", "user.name", "test")):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "source.py").write_text("original\n")
    (root / ".gitignore").write_text("ignored.log\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return root


def run(root, code="pass"):
    return evidence.record_run(root, [sys.executable, "-c", code])


def test_explicit_command_runs_once_and_receipt_omits_arguments_and_output(repo, capfd):
    assert run(repo, "from pathlib import Path; p=Path('ignored.log'); "
               "p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
               "print('synthetic-secret-not-for-a-receipt')") == 0
    assert (repo / "ignored.log").read_text() == "x"
    assert "synthetic-secret-not-for-a-receipt" in capfd.readouterr().out
    status = evidence.evidence_status(repo)
    assert status["state"] == "fresh_pass"
    assert status["receipt"]["exitCode"] == 0
    saved = "".join(path.read_text() for path in evidence.receipt_dir(repo).glob("*.json"))
    assert "synthetic-secret" not in saved
    assert "write_text" not in saved


@pytest.mark.parametrize("change", ["tracked", "untracked", "deleted", "mode", "index"])
def test_receipt_becomes_stale_when_working_tree_changes(repo, change):
    assert run(repo) == 0
    source = repo / "source.py"
    if change == "tracked":
        source.write_text("changed\n")
    elif change == "untracked":
        (repo / "new.py").write_text("new\n")
    elif change == "deleted":
        source.unlink()
    elif change == "mode":
        source.chmod(0o755)
    else:
        subprocess.run(["git", "rm", "--cached", "source.py"], cwd=repo, check=True,
                       capture_output=True)
    assert evidence.evidence_status(repo)["state"] == "stale"


def test_dirty_tree_can_pass_but_changes_during_execution_are_stale(repo):
    (repo / "source.py").write_text("already dirty\n")
    assert run(repo) == 0
    assert evidence.evidence_status(repo)["state"] == "fresh_pass"
    assert run(repo, "from pathlib import Path; Path('source.py').write_text('changed again')") == 0
    assert evidence.evidence_status(repo)["state"] == "stale"


def test_failure_supersedes_previous_pass_and_propagates_exit(repo):
    assert run(repo) == 0
    assert run(repo, "raise SystemExit(7)") == 7
    assert evidence.evidence_status(repo)["state"] == "failed"


def test_no_receipt_or_corrupt_latest_receipt_is_unknown(repo):
    assert evidence.evidence_status(repo)["state"] == "unknown"
    assert run(repo) == 0
    latest = sorted(evidence.receipt_dir(repo).glob("*.json"))[-1]
    latest.write_text("{broken")
    assert evidence.evidence_status(repo)["state"] == "unknown"


def test_running_command_hides_older_pass_and_concurrent_receipts_stay_valid(repo):
    assert run(repo) == 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(run, repo, "import time; time.sleep(.5)")
        deadline = time.monotonic() + 3
        while evidence.evidence_status(repo)["state"] != "running":
            assert time.monotonic() < deadline
            time.sleep(.01)
        other = pool.submit(run, repo)
        assert other.result() == pending.result() == 0
    receipts = list(evidence.receipt_dir(repo).glob("*.json"))
    assert len(receipts) == 3
    assert all(json.loads(path.read_text())["state"] == "finished" for path in receipts)


def test_sibling_worktrees_share_store_but_do_not_share_results(repo, tmp_path):
    sibling = tmp_path / "sibling"
    subprocess.run(["git", "worktree", "add", "-qb", "other", str(sibling)], cwd=repo,
                   check=True, capture_output=True)
    assert run(repo) == 0
    assert evidence.receipt_dir(repo).parent == evidence.receipt_dir(sibling).parent
    assert evidence.receipt_dir(repo) != evidence.receipt_dir(sibling)
    assert evidence.evidence_status(sibling)["state"] == "unknown"


def test_signal_termination_is_not_a_pass(repo):
    assert run(repo, "import os, signal; os.kill(os.getpid(), signal.SIGTERM)") == 143
    assert evidence.evidence_status(repo)["state"] == "interrupted"


def test_cli_status_is_advisory_and_run_returns_child_exit(repo, run_cli):
    result = run_cli("evidence", "run", "--target", str(repo), "--",
                     sys.executable, "-c", "raise SystemExit(9)")
    assert result.returncode == 9, result.stderr
    status = run_cli("evidence", "status", "--target", str(repo), "--json")
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["state"] == "failed"


def test_interrupting_recorder_cannot_preserve_an_older_pass(repo, tmp_path):
    assert run(repo) == 0
    cli = Path(__file__).resolve().parents[1] / "bin" / "tautline"
    proc = subprocess.Popen(
        [sys.executable, str(cli), "evidence", "run", "--target", str(repo), "--",
         sys.executable, "-c", "import time; time.sleep(20)"],
        env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while evidence.evidence_status(repo)["state"] != "running":
            assert proc.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.01)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=5)
        assert evidence.evidence_status(repo)["state"] in {"interrupted", "running"}
        assert proc.returncode != 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_interrupt_during_popen_assignment_reaps_the_started_child(repo, monkeypatch, signum):
    """A signal can arrive after fork/exec but before Popen returns the child handle."""
    real_popen = subprocess.Popen
    children = []

    def start_then_interrupt(*args, **kwargs):
        child = real_popen(*args, **kwargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        children.append(child)
        assert select.select([child.stdout], [], [], 5)[0], "descendant did not become ready"
        assert child.stdout.readline() == b"ready\n"
        signal.raise_signal(signum)
        return child

    monkeypatch.setattr(evidence.subprocess, "Popen", start_then_interrupt)
    descendant = (
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(20)"
    )
    command = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); time.sleep(20)"
    )
    try:
        result = evidence._execute(repo, [sys.executable, "-c", command])
        assert result == (128 + signum, True)
        assert len(children) == 1, "interruption must never launch the command again"
        assert children[0].poll() is not None, "the launched child must not outlive its recorder"
        # The ignoring descendant inherited these pipes. They reach EOF only after it exits too.
        children[0].communicate(timeout=2)
    finally:
        # The pre-fix implementation loses the handle and leaks this actual process. Reap it
        # even when the assertion fails so the regression itself cannot leave a sleeper behind.
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate(timeout=5)


def test_backward_clock_cannot_hide_a_newer_failure(repo, monkeypatch):
    ticks = iter((2_000_000_000, 1_000_000_000))
    monkeypatch.setattr(evidence.time, "time_ns", lambda: next(ticks))
    assert run(repo) == 0
    assert run(repo, "raise SystemExit(11)") == 11
    status = evidence.evidence_status(repo)
    assert status["state"] == "failed"
    assert status["receipt"]["exitCode"] == 11


def test_older_concurrent_completion_never_replaces_latest_start(repo, monkeypatch):
    import threading

    older_executing, release_older = threading.Event(), threading.Event()
    ticks = iter((2_000_000_000, 1_000_000_000))
    monkeypatch.setattr(evidence.time, "time_ns", lambda: next(ticks))
    real_execute = evidence._execute

    def execute(root, command):
        if command[-1] == "pass":
            older_executing.set()
            assert release_older.wait(3)
        return real_execute(root, command)

    monkeypatch.setattr(evidence, "_execute", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(run, repo)
        assert older_executing.wait(3)
        try:
            newer = pool.submit(run, repo, "raise SystemExit(13)")
            assert newer.result(timeout=3) == 13
            assert evidence.evidence_status(repo)["state"] == "failed"
        finally:
            release_older.set()
        assert older.result(timeout=3) == 0
    assert evidence.evidence_status(repo)["receipt"]["exitCode"] == 13


def test_new_start_during_status_cannot_leave_a_stale_green(repo, monkeypatch):
    import threading

    assert run(repo) == 0
    reader_started, release_reader = threading.Event(), threading.Event()
    real_snapshot = evidence._snapshot

    def snapshot(root):
        if threading.current_thread().name.startswith("old-status"):
            reader_started.set()
            assert release_reader.wait(3)
        return real_snapshot(root)

    monkeypatch.setattr(evidence, "_snapshot", snapshot)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="old-status") as pool:
        status = pool.submit(evidence.evidence_status, repo)
        assert reader_started.wait(3)
        try:
            assert run(repo, "raise SystemExit(17)") == 17
        finally:
            release_reader.set()
        assert status.result(timeout=3)["state"] != "fresh_pass"
    assert evidence.evidence_status(repo)["state"] == "failed"


def test_cli_preserves_child_flags_after_boundary(repo, run_cli):
    result = run_cli("evidence", "run", "--target", str(repo), "--",
                     sys.executable, "-c", "import sys; assert sys.argv[1:] == ['--target', 'child', '--json']",
                     "--target", "child", "--json")
    assert result.returncode == 0, result.stderr
