import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    command_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
        env=command_env,
    )
    return result.stdout.strip()


def _run_cli(
    binary: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    command_env = {
        **os.environ,
        "HOME": str(cwd / ".test-home"),
        "MINERVIT_METHODOLOGY_REPO": "",
        **(env or {}),
    }
    result = subprocess.run(
        [sys.executable, str(binary), *args],
        cwd=cwd,
        env=command_env,
        text=True,
        capture_output=True,
        timeout=90,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {binary} {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _write_sync_adapter(source: Path) -> None:
    adapter = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter["latestCode"] = {"enabled": False}
    adapter.setdefault("ciTestGate", {})["enforcement"] = "warn"
    adapter_path = source / "adapters" / "projects" / "example-saas.json"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(json.dumps(adapter, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_methodology_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "sync-remote.git"
    source = tmp_path / "sync-source"
    clone = tmp_path / "sync-clone"
    lane = tmp_path / "sync-lane"
    lane.mkdir()

    (source / "bin").mkdir(parents=True)
    shutil.copy2(CLI_PATH, source / "bin" / "tautline")
    (source / "bin" / "tautline").chmod(0o755)
    _write_sync_adapter(source)
    shutil.copy2(
        REPO_ROOT / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json",
        source / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json",
    )
    shutil.copy2(REPO_ROOT / "VERSION", source / "VERSION")
    manifest_dest = source / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
    manifest_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_MANIFEST, manifest_dest)
    src_dest = source / "src" / "minervit_methodology"
    src_dest.mkdir(parents=True)
    for path in (REPO_ROOT / "src" / "minervit_methodology").glob("*.py"):
        shutil.copy2(path, src_dest / path.name)
    (source / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.email", "validate@example.invalid")
    _git(source, "config", "user.name", "validate")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "initial methodology fixture")
    _git(tmp_path, "init", "--bare", "-q", "--initial-branch=main", str(remote))
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-q", "-u", "origin", "main")
    subprocess.run(["git", "clone", str(remote), str(clone)], text=True, capture_output=True, check=True)
    return source, clone, lane


def _advance_remote(source: Path, name: str, content: str) -> None:
    path = source / name
    path.write_text(content + "\n", encoding="utf-8")
    _git(source, "add", name)
    _git(source, "commit", "-q", "-m", f"advance methodology remote for {name}")
    _git(source, "push", "-q", "origin", "main")


def test_sync_methodology_rescues_clean_non_main_project_lane(tmp_path):
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _git(clone, "switch", "-q", "-c", "stale-feature")
    stale_head = _git(clone, "rev-parse", "HEAD")

    inside_methodology = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert inside_methodology.returncode == 1
    assert "methodology_update: failed - methodology checkout is on stale-feature, not main" in inside_methodology.stdout
    assert "MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1" in inside_methodology.stdout

    no_rescue = _run_cli(binary, "sync-methodology", "--no-auto-rescue-local-changes", "--no-remote", cwd=lane)
    assert no_rescue.returncode == 1
    assert "methodology_update: failed - methodology checkout is on stale-feature, not main" in no_rescue.stdout

    rescued = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - switched clean methodology checkout from non-release branch stale-feature" in rescued.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in rescued.stdout
    assert _git(clone, "branch", "--show-current") == "main"
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    assert _git(clone, "rev-parse", "stale-feature") == stale_head


def test_sync_methodology_repairs_divergent_main_and_preserves_local_commit(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    (clone / "LOCAL-MAIN-LANE-SYNC.md").write_text("local methodology main commit for project-lane sync\n")
    _git(clone, "add", "LOCAL-MAIN-LANE-SYNC.md")
    _git(
        clone,
        "-c",
        "user.email=validate@example.invalid",
        "-c",
        "user.name=validate",
        "commit",
        "-q",
        "-m",
        "local methodology main divergence before lane sync",
        env={"MINERVIT_METHODOLOGY_ALLOW_MAIN_COMMIT": "1"},
    )
    local_head = _git(clone, "rev-parse", "HEAD")
    _advance_remote(source, "REMOTE-DIVERGE-LANE.md", "remote methodology change for clean divergence lane sync")

    repaired = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)

    assert repaired.returncode == 0, repaired.stderr
    assert "methodology_update: updated - rescued divergent methodology main ahead=1 behind=1" in repaired.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in repaired.stdout
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    rescue_branches = _git(clone, "branch", "--format=%(refname:short)", "--list", "minervit-local-rescue/*-divergent-main-*")
    rescue_branch = rescue_branches.splitlines()[-1]
    assert _git(clone, "rev-parse", rescue_branch) == local_head
    assert "local methodology main commit for project-lane sync" in _git(
        clone, "show", f"{rescue_branch}:LOCAL-MAIN-LANE-SYNC.md"
    )


def test_sync_methodology_dirty_stale_fails_closed_then_auto_rescues_from_project_lane(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote(source, "REMOTE.md", "remote methodology change")
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local methodology edit\n")
    (clone / "LOCAL-NOTE.md").write_text("local untracked methodology note\n", encoding="utf-8")

    inside_methodology = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert inside_methodology.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in inside_methodology.stdout
    assert "refusing to start with stale methodology" in inside_methodology.stdout

    env_disabled = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE": "1"},
    )
    assert env_disabled.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in env_disabled.stdout

    no_rescue = _run_cli(binary, "sync-methodology", "--no-auto-rescue-local-changes", "--no-remote", cwd=lane)
    assert no_rescue.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in no_rescue.stdout

    # `--no-remote` only suppresses final remote-status reporting; the update guard still probes
    # origin so it can refuse auto-rescue when a newer release cannot be confirmed.
    original_origin = _git(clone, "remote", "get-url", "origin")
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing-sync-remote.git"))
    remote_unavailable = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)
    assert remote_unavailable.returncode == 1
    assert "refusing to auto-rescue without confirmed newer remote methodology" in remote_unavailable.stdout
    _git(clone, "remote", "set-url", "origin", original_origin)

    fake_token = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_REEXEC_TOKEN": str(tmp_path / "fake-reexec-token")},
    )
    assert fake_token.returncode == 1
    assert "methodology_update: failed - invalid or expired MINERVIT_METHODOLOGY_REEXEC_TOKEN" in fake_token.stdout

    rescued = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - rescued local changes to minervit-local-rescue/" in rescued.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in rescued.stdout
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    rescue_branch = _git(clone, "branch", "--format=%(refname:short)", "--list", "minervit-local-rescue/*").splitlines()[-1]
    assert "# local methodology edit" in _git(clone, "show", f"{rescue_branch}:bin/tautline")
    safe_branch = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in rescue_branch)
    assert (tmp_path / "methodology-rescue-state" / safe_branch / "untracked" / "LOCAL-NOTE.md").exists()


def test_lane_start_stable_manual_pin_skips_dirty_stale_update_and_renders(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote(source, "REMOTE-LANE.md", "remote methodology change for lane-start")
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local methodology edit before lane-start\n")
    (clone / "LOCAL-LANE-NOTE.md").write_text("local lane-start untracked methodology note\n", encoding="utf-8")

    started = _run_cli(
        binary,
        "lane-start",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )

    assert started.returncode == 0, started.stderr
    assert (
        "framework_pin: channel=stable version=unversioned-current updatePolicy=manual "
        "migrationPolicy=dry-run source=adapter"
    ) in started.stdout
    assert "framework_remote_status: remote differs" in started.stdout
    assert (
        "methodology_update: skipped - framework updatePolicy=manual; "
        "run sync-methodology intentionally at a safe boundary"
    ) in started.stdout
    assert (lane / "CLAUDE.md").exists()
    assert (lane / "AGENTS.md").exists()


def test_sync_methodology_dirty_current_skips_unless_explicit_auto_rescue(tmp_path):
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local current methodology edit\n")

    current = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert current.returncode == 0, current.stderr
    assert "methodology_update: skipped - methodology checkout has local changes but remote is up to date" in current.stdout

    rescued = _run_cli(
        binary,
        "sync-methodology",
        "--auto-rescue-local-changes",
        "--no-remote",
        cwd=clone,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - rescued local changes to minervit-local-rescue/" in rescued.stdout
    assert _git(clone, "status", "--porcelain") == ""
