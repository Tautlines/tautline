"""Shared fixtures for the lane-status suites (item 27: session-start currency gate).

Every fixture builds a REAL git repository. Nothing here mocks git itself: the whole point of this
control is how it behaves against real refs, real prunes, and real worktrees, and three separate
plan-review rounds found defects that only real git exposes (a pruned upstream, a narrow fetchspec,
`rev-parse` exit codes).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
    return proc.stdout.strip()


def _identify(repo: Path) -> None:
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")


def git_repo(tmp_path: Path, name: str = "lane", version: str | None = "0.21.0") -> Path:
    """An initialised repo on `experimental`. `version=None` builds a repo with NO VERSION file --
    adopter repositories are not required to have one."""
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "experimental")
    _identify(repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    if version is not None:
        (repo / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def repo_with_remote(
    tmp_path: Path, version: str | None = "0.21.0", name: str = "lane"
) -> tuple[Path, Path]:
    """(clone, bare_origin) with upstream tracking configured."""
    origin_source = git_repo(tmp_path, name=f"{name}-source", version=version)
    bare = tmp_path / f"{name}-origin.git"
    git(origin_source, "clone", "--bare", "-q", str(origin_source), str(bare))
    clone = tmp_path / name
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(clone)], capture_output=True, check=True
    )
    _identify(clone)
    return clone, bare


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_adapter(lane: Path, **lane_status: object) -> None:
    """A generated adapter marker so `find_adapter_root` and `load_project` both resolve this lane.

    Built from THIS repository's own generated adapter rather than hand-rolled: `load_project`
    requires a dozen domains, and a hand-built stub drifts the moment the contract grows. Only the
    fields this control reads are overridden.
    """
    payload: dict = json.loads((REPO_ROOT / ".tautline.json").read_text(encoding="utf-8"))
    # `project` is left as the source adapter's: load_project cross-validates it against
    # bootstrapEvidence.project, so renaming one without the other is rejected.
    payload["latestCode"] = dict(
        payload.get("latestCode") or {},
        enabled=True,
        remote="origin",
        base="experimental",
        statusFile=".ai-work/LATEST_CODE_BASELINE.json",
        maxAgeMinutes=60,
        fetchAll=False,
        includeOpenPrs=False,
        includeRemoteBranches=False,
        maxAheadBranches=0,
    )
    payload.pop("laneStatus", None)
    if lane_status:
        payload["laneStatus"] = dict(lane_status)
    (lane / ".tautline.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # The ignore file ignores itself, so adding an adapter marker never makes a fixture lane DIRTY.
    gitignore = lane / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".ai-work/" not in existing:
        gitignore.write_text(
            existing + ".ai-work/\n.tautline.json\n.gitignore\n", encoding="utf-8"
        )


def clean_lane(tmp_path: Path, version: str | None = "0.21.0", name: str = "lane") -> Path:
    lane, _bare = repo_with_remote(tmp_path, version=version, name=name)
    write_adapter(lane)
    return lane


def stale_orphaned_lane(
    tmp_path: Path, local_version: str = "0.17.5", base_version: str = "0.20.0"
) -> Path:
    """The literal 2026-07-24 incident: a lane several minors behind whose upstream was deleted.

    The upstream ref must be genuinely pruned, not merely absent from config -- a surviving stale
    remote-tracking ref is exactly what made `ORPHANED` unreachable in three separate revisions.
    """
    lane, bare = repo_with_remote(tmp_path, version=base_version, name="lane")
    # A feature branch pushed then deleted on the remote.
    git(lane, "switch", "-qc", "work/feature")
    (lane / "VERSION").write_text(f"{local_version}\n", encoding="utf-8")
    git(lane, "add", "-A")
    git(lane, "commit", "-qm", "old work")
    git(lane, "push", "-q", "-u", "origin", "work/feature")
    git(bare, "branch", "-D", "work/feature")
    # Base advances beyond the lane.
    helper = tmp_path / "advance"
    subprocess.run(["git", "clone", "-q", str(bare), str(helper)], capture_output=True, check=True)
    _identify(helper)
    (helper / "VERSION").write_text(f"{base_version}\n", encoding="utf-8")
    (helper / "moved.txt").write_text("advanced\n", encoding="utf-8")
    git(helper, "add", "-A")
    git(helper, "commit", "-qm", "advance base")
    git(helper, "push", "-q", "origin", "experimental")
    write_adapter(lane)
    return lane


def lane_with_squatted_integration_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A second real worktree pinning `experimental` BEHIND the remote."""
    lane, bare = repo_with_remote(tmp_path, name="lane")
    # The lane must leave `experimental` before a peer worktree can hold it: git forbids the same
    # branch in two worktrees, which is exactly why SQUATTED is about the INTEGRATION branch.
    git(lane, "switch", "-qc", "work/side")
    held = tmp_path / "held"
    git(lane, "worktree", "add", "-q", str(held), "experimental")
    helper = tmp_path / "advance-squat"
    subprocess.run(["git", "clone", "-q", str(bare), str(helper)], capture_output=True, check=True)
    _identify(helper)
    (helper / "moved.txt").write_text("advanced\n", encoding="utf-8")
    git(helper, "add", "-A")
    git(helper, "commit", "-qm", "advance base")
    git(helper, "push", "-q", "origin", "experimental")
    git(lane, "fetch", "-q", "origin", "--prune")
    write_adapter(lane)
    return lane, held


def lane_with_integration_worktree_ahead(tmp_path: Path) -> tuple[Path, Path]:
    """A peer worktree holding `experimental` legitimately AHEAD with an unpushed commit.
    Must NOT report SQUATTED -- it is not behind anything."""
    lane, _bare = repo_with_remote(tmp_path, name="lane")
    git(lane, "switch", "-qc", "work/side")
    held = tmp_path / "held-ahead"
    git(lane, "worktree", "add", "-q", str(held), "experimental")
    _identify(held)
    (held / "local.txt").write_text("unpushed\n", encoding="utf-8")
    git(held, "add", "-A")
    git(held, "commit", "-qm", "unpushed work")
    write_adapter(lane)
    return lane, held
