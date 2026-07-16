"""prod-distribution-1/3 (productization): cut-release builds the release boundary — a SHA256
checksums manifest of the distributed artifacts + the signed-tag command — without mutating git refs
by default, so an immutable, verifiable release artifact exists (composes with the auto-update trust
gate / pinned-tag policy).

Maintainer verbs (D-cat) additionally refuse to run from a runtime snapshot: a snapshot is an
immutable `git archive` export with no `.git`, so `git tag`, `git status` and the export's own
history scans have nothing to talk to. Left unguarded they do not fail loudly -- they degrade into
plausible nonsense (run_git's "unavailable" sentinel, an empty dirty check, a tag command that
cannot be run), which is how a release gets cut against code nobody can point a ref at.
"""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"


def _git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


@pytest.fixture(scope="module")
def snapshot_exec_root(tmp_path_factory):
    """A REAL snapshot exec root: HEAD's exported tree, no `.git`, plus a snapshot manifest.

    bin/tautline is overwritten from the working tree because `git archive` cannot see uncommitted
    work and the guard under test is the code being written. Module-scoped: the tree is read-only
    input to every test here, and exporting it once keeps four end-to-end runs cheap.
    """
    dest = tmp_path_factory.mktemp("snapshot") / "exec-root"
    dest.mkdir()
    tar_path = dest.parent / "snapshot.tar"
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(tar_path), "HEAD"],
        check=True,
        capture_output=True,
    )
    with tarfile.open(tar_path) as tar:
        tar.extractall(dest)  # noqa: S202 - our own git archive output
    tar_path.unlink()
    cli = dest / "bin" / "tautline"
    cli.write_text(CLI_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    cli.chmod(0o755)
    (dest / ".snapshot-meta.json").write_text(
        json.dumps(
            {"schema": "tautline-snapshot/v1", "commit": _git_head(REPO_ROOT), "channel": "stable"}
        ),
        encoding="utf-8",
    )
    assert not (dest / ".git").exists()  # the whole point: a snapshot cannot answer git
    return dest


@pytest.fixture(scope="module")
def canonical_checkout(tmp_path_factory):
    """The mutable dev checkout the guard must name in its message."""
    root = tmp_path_factory.mktemp("canonical") / "methodology"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def _run_from(exec_root: Path, canonical: Path, home: Path, *args: str):
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_CANONICAL_REPO": str(canonical),
    }
    return subprocess.run(
        [sys.executable, str(exec_root / "bin" / "tautline"), *args],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


MAINTAINER_VERBS = [
    ("cut-release", ["cut-release", "--dry-run"]),
    ("public-release-check", ["public-release-check"]),
    ("public-release-export", ["public-release-export", "--destination", "public-candidate"]),
]


@pytest.mark.parametrize("verb, argv", MAINTAINER_VERBS, ids=[v for v, _ in MAINTAINER_VERBS])
def test_maintainer_verb_refuses_to_run_from_a_snapshot(
    verb, argv, snapshot_exec_root, canonical_checkout, tmp_path
):
    res = _run_from(snapshot_exec_root, canonical_checkout, tmp_path / "home", *argv)

    assert res.returncode != 0, res.stdout
    assert f"{verb} must run from a methodology dev checkout, not a runtime snapshot" in res.stderr
    # The message has to be actionable: it names the checkout the operator should cd into.
    assert str(canonical_checkout) in res.stderr
    assert f"bin/tautline {verb}" in res.stderr


@pytest.mark.parametrize("verb, argv", MAINTAINER_VERBS, ids=[v for v, _ in MAINTAINER_VERBS])
def test_maintainer_verb_refuses_a_git_less_exec_root(
    verb, argv, snapshot_exec_root, canonical_checkout, tmp_path
):
    """A copied-out CLI has no manifest AND no `.git`. It is not a snapshot, but it is not a dev
    checkout either, and every git call these verbs make would silently return "unavailable"."""
    exec_root = tmp_path / "copied-cli"
    subprocess.run(["cp", "-R", str(snapshot_exec_root), str(exec_root)], check=True)
    (exec_root / ".snapshot-meta.json").unlink()

    res = _run_from(exec_root, canonical_checkout, tmp_path / "home", *argv)

    assert res.returncode != 0, res.stdout
    assert f"{verb} must run from a methodology dev checkout" in res.stderr


def test_cut_release_runs_from_a_dev_checkout(run_cli):
    """The guard must not fire on the repository it exists to protect."""
    res = run_cli("cut-release", "--dry-run")

    assert res.returncode == 0, res.stderr
    assert "must run from a methodology dev checkout" not in res.stderr


def test_cut_release_dry_run_lists_checksums_without_writing(run_cli, tmp_path):
    res = run_cli("cut-release", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "cut_release_version:" in res.stdout
    assert "cut_release_tag:" in res.stdout
    # five artifacts, each a 64-hex sha256
    import re

    shas = re.findall(r"^  ([0-9a-f]{64})  (\S+)$", res.stdout, re.MULTILINE)
    assert len(shas) >= 5
    assert any(p == "bin/tautline" for _, p in shas)
    # Extracted package modules are distributed implementation and must stay
    # inside the immutable release boundary alongside the bin entrypoint.
    assert any(p == "src/minervit_methodology/__init__.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/adapter.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/chat.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/deploy.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/gitutil.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/ghutil.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/guards.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/names.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/paths.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/profiles.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/releases.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/telemetry.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/util.py" for _, p in shas)
    assert any(p == "methodology/policy-phrases.json" for _, p in shas)
    assert "cut_release_dry_run: no files written" in res.stdout


def test_cut_release_dry_run_writes_nothing_and_creates_no_tag(run_cli):
    # --dry-run must not write the checksum manifest or create a git tag (no repo mutation).
    res = run_cli("cut-release", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "no files written, no tag created" in res.stdout
    assert "cut_release_written:" not in res.stdout
    assert "cut_release_tagged:" not in res.stdout
