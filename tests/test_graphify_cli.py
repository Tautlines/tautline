import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _run(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command_env = {
        **os.environ,
        "HOME": str((cwd or REPO_ROOT) / ".test-home"),
    }
    if env:
        command_env.update(env)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=cwd,
        env=command_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")


def _write_graphify_adapter(adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["latestCode"] = {"enabled": False}
    data.setdefault("graphify", {})["freshnessEnforcement"] = "strict-if-present"
    data.setdefault("ciTestGate", {})["enforcement"] = "warn"
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for Graphify behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = adapter_root / "graphify-example.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _adapter_env(adapter_root: Path) -> dict[str, str]:
    return {
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
        "MINERVIT_METHODOLOGY_REPO": "",
    }


def _prepare_graphify_target(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    target = tmp_path / "graphify-target"
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_graphify_adapter(adapter_root)
    _init_repo(target)
    env = _adapter_env(adapter_root)
    started = _run("lane-start", "--project", str(adapter), "--target", str(target), "--skip-update", cwd=target, env=env)
    assert "graphify: enabled=true" in started.stdout
    assert "graphify_instruction: If output exists, it must be current before use/commit/push" in started.stdout
    assert "graphify-out/" in (target / ".gitignore").read_text(encoding="utf-8")
    return target, adapter, env


def test_graphify_status_detects_missing_stale_fresh_and_tracked_output(tmp_path):
    target, adapter, env = _prepare_graphify_target(tmp_path)

    missing = _run("graphify-status", "--project", str(adapter), "--target", str(target), cwd=target, env=env)
    assert "graphify: enabled=true" in missing.stdout
    assert "graphify_gitignore: ok graphify-out/" in missing.stdout
    assert "graphify_freshness: missing-output enforcement=strict-if-present" in missing.stdout

    output = target / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text('{"nodes":[]}\n', encoding="utf-8")
    (output / "GRAPH_REPORT.md").write_text("# Graph report\n", encoding="utf-8")
    time.sleep(1)
    (target / "app.py").write_text("new project behavior\n", encoding="utf-8")
    _git(target, "add", "app.py")

    stale = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=env,
        check=False,
    )
    assert stale.returncode == 1
    assert "graphify_freshness: stale enforcement=strict-if-present" in stale.stdout
    assert "graphify_issue: stale Graphify output: run `graphify . --update`" in stale.stdout
    assert "graphify_next: run `graphify . --update` before commit, push, or Graphify-backed decisions" in stale.stdout

    time.sleep(1)
    (output / "graph.json").write_text('{"nodes":["fresh"]}\n', encoding="utf-8")
    fresh = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=env,
    )
    assert "graphify_freshness: current enforcement=strict-if-present" in fresh.stdout

    _git(target, "add", "-f", "graphify-out/graph.json")
    tracked = _run(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        cwd=target,
        env=env,
        check=False,
    )
    assert tracked.returncode == 1
    assert "graphify_issue: tracked Graphify output must be removed from git" in tracked.stdout


def test_installed_hooks_enforce_graphify_freshness_and_keep_prepush_guard(tmp_path):
    target, _adapter, env = _prepare_graphify_target(tmp_path)

    _run(
        "install-hooks",
        "--settings",
        str(tmp_path / "graphify-claude-settings.json"),
        "--target",
        str(target),
        cwd=target,
        env=env,
    )
    pre_commit = target / ".git" / "hooks" / "pre-commit"
    pre_push = target / ".git" / "hooks" / "pre-push"
    assert "graphify-status --target . --strict" in pre_commit.read_text(encoding="utf-8")
    assert "graphify-status --target . --strict" in pre_push.read_text(encoding="utf-8")
    assert "guard-check --target . --boundary prepush" in pre_push.read_text(encoding="utf-8")

    output = target / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text('{"nodes":[]}\n', encoding="utf-8")
    time.sleep(1)
    (target / "hook-change.py").write_text("hook-visible project change\n", encoding="utf-8")
    stale = subprocess.run(
        [str(pre_commit)],
        cwd=target,
        env={**os.environ, **env, "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert stale.returncode == 1
    assert "graphify_issue: stale Graphify output: run `graphify . --update`" in stale.stdout

    time.sleep(1)
    (output / "graph.json").write_text('{"nodes":["hook-fresh"]}\n', encoding="utf-8")
    fresh = subprocess.run(
        [str(pre_commit)],
        cwd=target,
        env={**os.environ, **env, "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert fresh.returncode == 0, fresh.stderr
    assert "branch_liveness: pass" in fresh.stdout
