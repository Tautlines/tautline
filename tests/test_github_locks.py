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
