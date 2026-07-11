import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
COORD_ROOT = "docs/product/backlog/example-saas-v1/specs/coordination"


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


def _init_repo(target: Path, *, remote: str = "git@github.com:example-org/example-saas.git") -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", remote)
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")


def _write_evidence(target: Path) -> None:
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")


def _write_lane_coordination_adapter(adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    lane_coordination = data.setdefault("laneCoordination", {})
    for key in ("contractPath", "boardPath", "laneStatusDir"):
        lane_coordination.pop(key, None)
    lane_coordination["root"] = COORD_ROOT
    data["latestCode"] = {"enabled": False}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for markdown lane-coordination behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = adapter_root / "lane-coordination.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _adapter_env(adapter_root: Path) -> dict[str, str]:
    return {"MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root)}


def _render(target: Path, adapter: Path, adapter_root: Path) -> None:
    _write_evidence(target)
    _run(
        "render-adapters",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )


def _commit(repo: Path, message: str, *paths: str) -> None:
    _git(repo, "add", *(paths or ["."]))
    _git(repo, "commit", "-qm", message)


def _age_file(path: Path, hours: float) -> None:
    """Backdate a file's mtime so staleness checks (mtime-based) see it as old."""
    stamp = time.time() - (hours * 3600)
    os.utime(path, (stamp, stamp))


def _write_foreign_status(target: Path, name: str, *, branch: str = "dead-lane-branch-xyz") -> Path:
    """Write another (dead/other) lane's status file directly, bypassing lane-coordination-note
    so it is never mistaken for the current lane's own file (no Branch: match, no name match)."""
    path = target / COORD_ROOT / "lanes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Lane Status: {name}\n\nBranch: {branch}\n\nSome other lane's stale coordination note.\n",
        encoding="utf-8",
    )
    return path


def test_lane_coordination_bootstrap_note_and_strict_status(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-base-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")

    before = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert before.returncode == 1
    assert "lane_coordination: enabled=true" in before.stdout
    assert "lane_coordination_enforcement: warn" in before.stdout
    assert "lane_coordination_contract: missing" in before.stdout

    bootstrap = _run(
        "lane-coordination-bootstrap",
        "--target",
        str(target),
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert "cross-lane-contract.md" in bootstrap.stdout
    assert "lane-board.md" in bootstrap.stdout

    note = _run(
        "lane-coordination-note",
        "--target",
        str(target),
        "--lane",
        "lane-1-owner-access",
        "--goal",
        "First shop launch",
        "--current",
        "Owner access routes and role checks",
        "--depends-on",
        "Lane 2: account persistence contract",
        "--provides",
        "Owner session contract for customer intake",
        "--blockers",
        "none",
        "--pr",
        "#123",
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert "wrote " in note.stdout
    assert "lane-1-owner-access.md" in note.stdout
    assert "updated " in note.stdout
    lane_status = target / COORD_ROOT / "lanes" / "lane-1-owner-access.md"
    assert "Lane Status: lane-1-owner-access" in lane_status.read_text(encoding="utf-8")
    assert "Owner session contract for customer intake" in lane_status.read_text(encoding="utf-8")
    assert "lane-1-owner-access" in (target / COORD_ROOT / "lane-board.md").read_text(encoding="utf-8")

    untracked = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert untracked.returncode == 1
    assert "coordination contract is untracked" in untracked.stdout
    assert "lane status is untracked" in untracked.stdout

    _commit(target, "track lane coordination artifacts", COORD_ROOT)
    after = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert "lane_coordination_enforcement: warn" in after.stdout
    assert "lane_coordination_status: ok" in after.stdout
    assert (
        "lane_coordination_status_files: 1 - "
        "docs/product/backlog/example-saas-v1/specs/coordination/lanes/lane-1-owner-access.md"
    ) in after.stdout


def test_lane_start_bootstraps_untracked_coordination_artifacts(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-start-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline")

    started = _run("lane-start", "--target", str(target), "--skip-update", cwd=target, env=_adapter_env(adapter_root))
    assert "lane_coordination_bootstrap: created " in started.stdout
    assert "cross-lane-contract.md" in started.stdout
    assert "lane-board.md" in started.stdout
    assert "coordination/lanes" in started.stdout

    status = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert status.returncode == 1
    assert "lane_coordination_status: issues" in status.stdout
    assert "coordination contract is untracked" in status.stdout


def test_current_lane_status_must_be_pushed_to_branch_upstream(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-feature-target"
    remote = tmp_path / "coordination-feature-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    _init_repo(target, remote="git@github.com:example-org/example-saas.git")
    _git(target, "remote", "set-url", "--push", "origin", str(remote))
    _render(target, adapter, adapter_root)
    _run(
        "lane-coordination-bootstrap",
        "--target",
        str(target),
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    _commit(target, "baseline")
    _git(target, "push", "-u", "origin", "main")
    _git(target, "switch", "-c", "feature/customer-ordering")
    _run(
        "lane-coordination-note",
        "--target",
        str(target),
        "--lane",
        "customer-ordering",
        "--goal",
        "Customer ordering",
        "--current",
        "Checkout and order-line routes",
        "--depends-on",
        "none",
        "--provides",
        "Customer order contract",
        "--blockers",
        "none",
        "--pr",
        "branch feature/customer-ordering",
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )

    uncommitted = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert uncommitted.returncode == 1
    assert "lane status is untracked" in uncommitted.stdout

    _commit(target, "update feature lane status", COORD_ROOT)
    unpushed = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert unpushed.returncode == 1
    assert "current lane status is not pushed to the branch upstream" in unpushed.stdout

    _git(target, "push", "-u", "origin", "feature/customer-ordering")
    pushed = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert "lane_coordination_status: ok" in pushed.stdout
    assert (
        "lane_coordination_current_status_files: 1 - "
        "docs/product/backlog/example-saas-v1/specs/coordination/lanes/customer-ordering.md"
    ) in pushed.stdout


def _issue_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("lane_coordination_issue:")]


def _bootstrap_and_commit(target: Path, adapter_root: Path) -> None:
    _run(
        "lane-coordination-bootstrap",
        "--target",
        str(target),
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    _commit(target, "bootstrap coordination artifacts", COORD_ROOT)


def _write_own_note(target: Path, adapter_root: Path, lane: str) -> None:
    _run(
        "lane-coordination-note",
        "--target",
        str(target),
        "--lane",
        lane,
        "--goal",
        "Staleness re-scope coverage",
        "--current",
        "Exercising lane-coordination staleness re-scope",
        "--depends-on",
        "none",
        "--provides",
        "none",
        "--blockers",
        "none",
        "--pr",
        "none",
        "--write",
        cwd=target,
        env=_adapter_env(adapter_root),
    )


def test_foreign_stale_status_is_informational_not_issue(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-stale-foreign-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")
    _git(target, "switch", "-c", "feature/staleness-check")
    _bootstrap_and_commit(target, adapter_root)

    _write_own_note(target, adapter_root, "staleness-check")
    own_status = target / COORD_ROOT / "lanes" / "staleness-check.md"
    foreign_status = _write_foreign_status(target, "dead-lane.md")
    _commit(target, "add lane status files", COORD_ROOT)
    _age_file(own_status, 100)
    _age_file(foreign_status, 100)

    status = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    issues = _issue_lines(status.stdout)
    assert any("stale lane status:" in line and "staleness-check.md" in line for line in issues)
    assert not any("dead-lane.md" in line for line in issues)
    assert "lane_coordination_stale_other_lanes: 1 - " in status.stdout
    assert "dead-lane.md" in status.stdout


def test_shared_base_branch_starts_clean_with_stale_foreign_files(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-stale-main-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")
    _bootstrap_and_commit(target, adapter_root)

    foreign_status = _write_foreign_status(target, "dead-lane.md")
    _commit(target, "add foreign lane status file", COORD_ROOT)
    _age_file(foreign_status, 100)

    status = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert "lane_coordination_status: ok" in status.stdout
    assert _issue_lines(status.stdout) == []
    assert "lane_coordination_stale_other_lanes: 1 - " in status.stdout
    assert "dead-lane.md" in status.stdout


def test_foreign_untracked_status_is_informational_not_issue(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-untracked-foreign-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")
    _bootstrap_and_commit(target, adapter_root)

    _write_own_note(target, adapter_root, "main")
    _write_foreign_status(target, "dead-lane-untracked.md")

    status = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert status.returncode == 1
    issues = _issue_lines(status.stdout)
    assert any("lane status is untracked" in line and "main.md" in line for line in issues)
    assert not any("dead-lane-untracked.md" in line for line in issues)
    assert "lane_coordination_foreign_status_git: 1 - " in status.stdout
    assert "dead-lane-untracked.md" in status.stdout


def test_foreign_dirty_status_is_informational_not_issue(tmp_path):
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    target = tmp_path / "coordination-dirty-foreign-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")
    _bootstrap_and_commit(target, adapter_root)

    _write_own_note(target, adapter_root, "main")
    foreign_status = _write_foreign_status(target, "dead-lane-dirty.md")
    _commit(target, "add lane status files", COORD_ROOT)

    own_status = target / COORD_ROOT / "lanes" / "main.md"
    with own_status.open("a", encoding="utf-8") as handle:
        handle.write("\nDirtied for own-file regression coverage.\n")
    with foreign_status.open("a", encoding="utf-8") as handle:
        handle.write("\nDirtied for foreign-file re-scope coverage.\n")

    status = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=_adapter_env(adapter_root),
        check=False,
    )
    assert status.returncode == 1
    issues = _issue_lines(status.stdout)
    assert any("lane status has uncommitted changes" in line and "main.md" in line for line in issues)
    assert not any("dead-lane-dirty.md" in line for line in issues)
    assert "lane_coordination_foreign_status_git: 1 - " in status.stdout
    assert "dead-lane-dirty.md" in status.stdout


def test_max_status_age_hours_still_honored_for_own_file(tmp_path):
    # The example-saas source adapter's laneCoordination.maxStatusAgeHours is 12; lane_project()
    # re-derives data from the trusted source adapter every run (sha256-pinned to it), so the
    # threshold can't be overridden by hand-editing the rendered .tautline.json marker.
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_lane_coordination_adapter(adapter_root)
    adapter_data = json.loads(adapter.read_text(encoding="utf-8"))
    assert adapter_data["laneCoordination"]["maxStatusAgeHours"] == 12
    target = tmp_path / "coordination-max-age-target"
    _init_repo(target)
    _render(target, adapter, adapter_root)
    _commit(target, "baseline", "AGENTS.md", "CLAUDE.md", ".tautline.json")
    _bootstrap_and_commit(target, adapter_root)

    _write_own_note(target, adapter_root, "main")
    own_status = target / COORD_ROOT / "lanes" / "main.md"
    _commit(target, "add own lane status file", COORD_ROOT)

    _age_file(own_status, 6)
    fresh = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert not any("stale lane status:" in line for line in _issue_lines(fresh.stdout))

    _age_file(own_status, 20)
    stale = _run(
        "lane-coordination-status",
        "--target",
        str(target),
        cwd=target,
        env=_adapter_env(adapter_root),
    )
    assert any("stale lane status:" in line and "main.md" in line for line in _issue_lines(stale.stdout))
