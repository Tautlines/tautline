import json
import os
import subprocess
import time


def test_github_command_lock_removes_stale_legacy_lock(cli, tmp_path, monkeypatch, capsys):
    cache = tmp_path / "github-cache"
    lock = cache / ".request.lock"
    lock.mkdir(parents=True)
    old_epoch = time.time() - 30
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(cache))
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_STALE_SECONDS", "1")
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_TIMEOUT_SECONDS", "1")
    os.utime(lock, (old_epoch, old_epoch))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert lock.is_dir()
        assert (lock / "owner.json").is_file()
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    code, out, err = cli.run_command(["gh", "api", "rate_limit"], cwd=tmp_path, timeout=5)

    assert (code, out, err) == (0, "ok", "")
    assert calls == [["gh", "api", "rate_limit"]]
    assert not lock.exists()
    assert "github_lock_stale_removed" in capsys.readouterr().err


def test_github_command_lock_degrades_on_fresh_lock_timeout(cli, tmp_path, monkeypatch, capsys):
    cache = tmp_path / "github-cache"
    lock = cache / ".request.lock"
    lock.mkdir(parents=True)
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(cache))
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_STALE_SECONDS", "60")
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_TIMEOUT_SECONDS", "0")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert lock.is_dir()
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    code, out, err = cli.run_command(["gh", "api", "rate_limit"], cwd=tmp_path, timeout=5)

    assert (code, out, err) == (0, "ok", "")
    assert calls == [["gh", "api", "rate_limit"]]
    stderr = capsys.readouterr().err
    assert "github_request_lock_timeout_warn:" in stderr
    assert "schema=legacy-empty-directory" in stderr


def test_github_command_lock_degrades_when_cache_root_unwritable(cli, tmp_path, monkeypatch, capsys):
    cache = tmp_path / "github-cache"
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(cache))
    calls = []

    def fail_mkdir(*_args, **_kwargs):
        raise PermissionError("cache denied")

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(cli.Path, "mkdir", fail_mkdir)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    code, out, err = cli.run_command(["gh", "api", "rate_limit"], cwd=tmp_path, timeout=5)

    assert (code, out, err) == (0, "ok", "")
    assert calls == [["gh", "api", "rate_limit"]]
    assert "github_request_lock_unavailable_warn:" in capsys.readouterr().err


def test_github_operation_lock_degrades_on_timeout(cli, tmp_path, monkeypatch, capsys):
    cache = tmp_path / "github-cache"
    args = ["project", "item-list", "7", "--owner", "minervit"]
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(cache))
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_STALE_SECONDS", "60")
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_TIMEOUT_SECONDS", "0")
    cli.github_operation_lock_path(args).mkdir(parents=True)
    ran = False

    with cli.github_operation_lock(args):
        ran = True

    assert ran is True
    stderr = capsys.readouterr().err
    assert "github_operation_lock_timeout_warn:" in stderr
    assert "schema=legacy-empty-directory" in stderr


def test_github_operation_lock_degrades_when_cache_root_unwritable(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))

    def fail_mkdir(*_args, **_kwargs):
        raise PermissionError("cache denied")

    monkeypatch.setattr(cli.Path, "mkdir", fail_mkdir)
    ran = False

    with cli.github_operation_lock(["project", "item-list", "7"]):
        ran = True

    assert ran is True
    assert "github_operation_lock_unavailable_warn:" in capsys.readouterr().err


def test_github_cache_write_degrades_when_cache_root_unusable(cli, tmp_path, monkeypatch, capsys):
    blocked = tmp_path / "notdir"
    blocked.write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(blocked / "cache"))

    cli.github_cache_write(["api", "rate_limit"], {"ok": True})

    assert "github_cache_write_unavailable_warn:" in capsys.readouterr().err


def test_windows_process_liveness_does_not_call_os_kill(cli, monkeypatch):
    monkeypatch.setattr(cli.os, "name", "nt", raising=False)

    def fail_kill(*_args):
        raise AssertionError("os.kill must not be used as a Windows liveness probe")

    monkeypatch.setattr(cli.os, "kill", fail_kill)

    def fake_tasklist(command, **kwargs):
        assert command[:2] == ["tasklist", "/FI"]
        return subprocess.CompletedProcess(command, 0, '"python.exe","1234","Console","1","10,000 K"\n', "")

    monkeypatch.setattr(cli.subprocess, "run", fake_tasklist)

    assert cli.github_process_exists(1234) is True


def test_live_pid_lock_is_not_removed_only_because_it_is_old(cli, tmp_path, monkeypatch):
    cache = tmp_path / "github-cache"
    lock = cache / ".request.lock"
    lock.mkdir(parents=True)
    owner = {
        "schema": "minervit-github-lock/v1",
        "pid": 1234,
        "token": "token",
        "created_at_epoch": time.time() - 999,
        "command": "gh api rate_limit",
    }
    (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(cache))
    monkeypatch.setenv("MINERVIT_GITHUB_LOCK_STALE_SECONDS", "1")
    monkeypatch.setattr(cli, "github_process_exists", lambda pid: True)

    assert cli.github_lock_stale_reason(lock) == ""
