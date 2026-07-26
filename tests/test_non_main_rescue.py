"""RCA: a clean, intentionally-non-main methodology checkout must not generate phantom rescue refs.

`preserve_release_main_pointer` used to create a `tautline-local-rescue/*` ref whenever local main
differed from upstream -- including when main was merely *behind* (fast-forwardable). That ref had
nothing unique to preserve, polluted rescue-ref drift detection, and on a non-main checkout
contributed to a fully-wedged lane. The fix: preserve only when local main carries commits the
upstream does not (main is not an ancestor of upstream).
"""

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo_with_main_and_upstream(tmp_path: Path) -> Path:
    repo = tmp_path / "methodology"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "VERSION").write_text("0.0.1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    # an "upstream" ref two commits ahead of where main will sit
    _git(repo, "branch", "upstream-main")
    _git(repo, "checkout", "-q", "upstream-main")
    (repo / "VERSION").write_text("0.0.2\n")
    _git(repo, "commit", "-aqm", "upstream advance")
    _git(repo, "checkout", "-q", "main")
    return repo


def _rescue_refs(repo: Path) -> list[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/tautline-local-rescue")
    return [line for line in out.splitlines() if line.strip()]


def test_behind_main_creates_no_rescue_ref(cli, tmp_path, monkeypatch):
    # main is an ancestor of upstream (purely behind) -> nothing unique -> no rescue ref.
    repo = _repo_with_main_and_upstream(tmp_path)
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    ok, detail = cli.preserve_release_main_pointer("upstream-main", "non-main")
    assert ok and detail == ""
    assert _rescue_refs(repo) == []


def test_diverged_main_is_still_preserved(cli, tmp_path, monkeypatch):
    # main has a commit the upstream does not -> must be preserved before any reset.
    repo = _repo_with_main_and_upstream(tmp_path)
    (repo / "local-only.txt").write_text("local work\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "local-only commit on main")
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    ok, detail = cli.preserve_release_main_pointer("upstream-main", "non-main")
    assert ok and "preserved prior main at" in detail
    refs = _rescue_refs(repo)
    assert len(refs) == 1 and refs[0].startswith("tautline-local-rescue/")


def test_main_equals_upstream_creates_no_rescue_ref(cli, tmp_path, monkeypatch):
    # main already at upstream -> no-op (unchanged pre-existing fast path).
    repo = _repo_with_main_and_upstream(tmp_path)
    _git(repo, "reset", "--hard", "upstream-main")
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    ok, detail = cli.preserve_release_main_pointer("upstream-main", "non-main")
    assert ok and detail == ""
    assert _rescue_refs(repo) == []


def test_failed_preservation_aborts_reset_without_data_loss(cli, tmp_path, monkeypatch):
    # Codex P2: if a REQUIRED preservation cannot be created, switch_release_main must abort before
    # reset --hard so divergent local main commits are never dropped. Force branch creation to fail
    # by occupying the `tautline-local-rescue` ref namespace with a same-named branch (D/F conflict).
    repo = _repo_with_main_and_upstream(tmp_path)
    (repo / "local-only.txt").write_text("local work\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "local-only commit on main")
    main_sha = _git(repo, "rev-parse", "refs/heads/main")
    _git(repo, "branch", "tautline-local-rescue")  # blocks any tautline-local-rescue/* child ref
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    ok, detail = cli.preserve_release_main_pointer("upstream-main", "non-main")
    assert not ok and "could not preserve" in detail
    switched, switch_detail = cli.switch_release_main("upstream-main", "non-main")
    assert not switched and "aborted before reset" in switch_detail
    # main must be untouched -- no reset happened, unique commit intact.
    assert _git(repo, "rev-parse", "refs/heads/main") == main_sha
