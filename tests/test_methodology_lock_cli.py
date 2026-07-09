import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(*args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=60,
    )


def _write_lock_adapter(adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for methodology lock lifecycle coverage.",
        "repoEvidence": [
            {
                "path": ".ai-work/bootstrap-evidence.txt",
                "fact": "Bootstrap evidence fixture exists.",
            },
            {
                "path": ".ai-work/bootstrap-evidence-2.txt",
                "fact": "Second bootstrap evidence fixture exists.",
            },
        ],
    }
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
    data.setdefault("behaviorSpecs", {})["required"] = False
    data["behaviorSpecs"]["acceptanceHarnesses"] = []
    for key in (
        "backlogProvider",
        "goalTracker",
        "stakeholderQuestions",
        "deploymentNotification",
        "productChat",
        "milestoneUpdate",
        "iterationReview",
    ):
        data.pop(key, None)
    adapter = adapter_root / "methodology-lock-example.json"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    target = tmp_path / "methodology-lock-fixture"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lock_adapter(adapter_root)
    home = tmp_path / "home"
    env = {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
    }
    return target, adapter, env


def test_methodology_lock_relock_lane_start_invalid_and_unlock(tmp_path):
    target, adapter, env = _prepare_target(tmp_path)
    lock_path = target / ".minervit-methodology-lock.json"

    first = _run_cli("lock-methodology", "--project", str(adapter), "--target", str(target), "--reason", "validation lock", env=env)
    assert first.returncode == 0, first.stderr
    assert lock_path.is_file()
    first_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert first_lock["schema"] == "minervit-methodology-lock/v1"
    assert first_lock["pluginVersion"] == (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert first_lock["reason"] == "validation lock"

    second = _run_cli(
        "lock-methodology",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--reason",
        "validation relock",
        env=env,
    )
    assert second.returncode == 0, second.stderr
    assert "archived previous methodology lock" in second.stdout
    superseded = sorted((target / ".ai-runs/methodology-locks").glob("*superseded-lock*.json"))
    assert len(superseded) == 1
    assert json.loads(superseded[0].read_text(encoding="utf-8"))["reason"] == "validation lock"

    lane_start = _run_cli("lane-start", "--project", str(adapter), "--target", str(target), env=env)
    assert lane_start.returncode == 0, lane_start.stdout + lane_start.stderr
    assert "methodology_update: locked at" in lane_start.stdout
    assert "(validation relock)" in lane_start.stdout
    assert f"plugin_version: {first_lock['pluginVersion']}" in lane_start.stdout
    assert "methodology_commit:" in lane_start.stdout

    unlock = _run_cli("unlock-methodology", "--project", str(adapter), "--target", str(target), env=env)
    assert unlock.returncode == 0, unlock.stderr
    assert not lock_path.exists()
    assert (target / ".ai-runs/methodology-locks").is_dir()

    lock_path.write_text("{not-json\n", encoding="utf-8")
    status = _run_cli("methodology-status", "--project", str(adapter), "--target", str(target), "--no-remote", env=env)
    assert status.returncode == 0, status.stderr
    assert "lock: invalid" in status.stdout

    invalid_start = _run_cli(
        "lane-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--skip-update",
        env=env,
    )
    assert invalid_start.returncode == 0, invalid_start.stdout + invalid_start.stderr
    assert "locked by invalid lock file" in invalid_start.stdout
    assert lock_path.is_file()

    invalid_unlock = _run_cli("unlock-methodology", "--project", str(adapter), "--target", str(target), env=env)
    assert invalid_unlock.returncode == 0, invalid_unlock.stderr
    assert not lock_path.exists()
    archived_locks = sorted((target / ".ai-runs/methodology-locks").glob("*.json"))
    assert len(archived_locks) >= 3
