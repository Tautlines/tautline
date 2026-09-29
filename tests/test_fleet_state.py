"""Fleet Governor state core: common-dir resolution, lease lifecycle, fail-open reads."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _init_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    (target / "README.md").write_text("seed\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-q", "-m", "seed")


def _lease(cli, *, lease_id="abc123", worktree="/tmp/wt-a", globs=("src/**",), ttl=240):
    now = datetime.now(timezone.utc)
    return {
        "schema": cli.FLEET_LEASE_SCHEMA,
        "lease_id": lease_id,
        "worktree_path": worktree,
        "branch": "lane-a",
        "goal_ref": "goal-1",
        "globs": list(globs),
        "claimed_at": now.isoformat(),
        "renewed_at": now.isoformat(),
        "ttl_minutes": ttl,
        "session": {"pid": 1234, "host": "test", "started_at": now.isoformat()},
        "note": "",
    }


def test_fleet_config_defaults_and_validation(cli):
    import pytest

    assert cli.fleet_config({}) == cli.DEFAULT_FLEET
    cfg = cli.fleet_config({"fleet": {"enforcement": "observe"}})
    assert cfg["enforcement"] == "observe"
    assert cfg["enabled"] is True
    with pytest.raises(SystemExit):
        cli.fleet_config({"fleet": {"enforcement": "bogus"}})
    with pytest.raises(SystemExit):
        cli.fleet_config({"fleet": []})
