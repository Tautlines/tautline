"""RCA O17: detect canonical adapter changes stranded on local rescue refs."""

import json
import subprocess
from pathlib import Path


ADAPTER_REL = "adapters/projects/" + "demo.json"
ROOT = Path(__file__).resolve().parents[1]
# Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a shim.
CLI = ROOT / "src" / "tautline_methodology" / "cli.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "methodology"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    adapters = repo / "adapters" / "projects"
    adapters.mkdir(parents=True)
    (adapters / "demo.json").write_text('{"project": "demo"}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_clean_repo_has_no_rescue_findings(cli, tmp_path):
    repo = _make_repo(tmp_path)
    assert hasattr(cli, "methodology_rescue_ref_adapter_changes")
    assert cli.methodology_rescue_ref_adapter_changes(repo) == []


def test_rescue_ref_status_surface_remains_pinned():
    assert "methodology_rescue_ref_adapter_drift" in CLI.read_text(encoding="utf-8")


def test_rescue_ref_with_adapter_change_is_detected(cli, tmp_path):
    repo = _make_repo(tmp_path)
    # A canonical adapter fix lands on a rescue ref, not on main.
    _git(repo, "checkout", "-q", "-b", "minervit-local-rescue/20260610-1-fix")
    (repo / "adapters" / "projects" / "demo.json").write_text('{"project": "demo", "fixed": true}\n')
    _git(repo, "commit", "-aq", "-m", "rescue fix")
    _git(repo, "checkout", "-q", "main")
    findings = cli.methodology_rescue_ref_adapter_changes(repo)
    assert len(findings) == 1
    ref, paths = findings[0]
    assert ref == "minervit-local-rescue/20260610-1-fix"
    assert paths == [ADAPTER_REL]


def test_rescue_ref_tautline_prefix_is_detected(cli, tmp_path):
    # write-new/read-both: rescue refs created under the new tautline prefix are enumerated too.
    repo = _make_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "tautline-local-rescue/20260720-1-fix")
    (repo / "adapters" / "projects" / "demo.json").write_text('{"project": "demo", "fixed": true}\n')
    _git(repo, "commit", "-aq", "-m", "rescue fix")
    _git(repo, "checkout", "-q", "main")
    findings = cli.methodology_rescue_ref_adapter_changes(repo)
    assert len(findings) == 1
    ref, paths = findings[0]
    assert ref == "tautline-local-rescue/20260720-1-fix"
    assert paths == [ADAPTER_REL]


def test_rescue_ref_already_relanded_is_not_flagged(cli, tmp_path):
    # Codex P3: a rescue adapter change already re-landed on the base branch (matching content)
    # must NOT be reported as stranded; two-dot tree compare handles this.
    repo = _make_repo(tmp_path)
    fixed = '{"project": "demo", "fixed": true}\n'
    _git(repo, "checkout", "-q", "-b", "minervit-local-rescue/20260610-3-fix")
    (repo / "adapters" / "projects" / "demo.json").write_text(fixed)
    _git(repo, "commit", "-aq", "-m", "rescue fix")
    # re-land the identical change on main
    _git(repo, "checkout", "-q", "main")
    (repo / "adapters" / "projects" / "demo.json").write_text(fixed)
    _git(repo, "commit", "-aq", "-m", "re-land fix on main")
    assert cli.methodology_rescue_ref_adapter_changes(repo) == []


def test_rescue_ref_that_is_ancestor_of_base_is_not_flagged(cli, tmp_path):
    # RCA: a rescue ref that is OLD main (an ancestor of base) carries nothing un-landed -- base
    # advanced past it. It must not be flagged, even though base later changed the same adapter file
    # (which a two-dot tree diff alone would report). This was the phantom `...-non-main-<sha>` hint.
    repo = _make_repo(tmp_path)
    # snapshot current main as a rescue ref (old main), then advance main's adapter
    _git(repo, "branch", "minervit-local-rescue/20260615-9-non-main-abc1234")
    (repo / "adapters" / "projects" / "demo.json").write_text('{"project": "demo", "advanced": true}\n')
    _git(repo, "commit", "-aq", "-m", "advance demo.json on main after rescue snapshot")
    assert cli.methodology_rescue_ref_adapter_changes(repo) == []


def test_rescue_ref_without_adapter_change_is_ignored(cli, tmp_path):
    repo = _make_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "minervit-local-rescue/20260610-2-docs")
    (repo / "README.md").write_text("docs only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")
    _git(repo, "checkout", "-q", "main")
    assert cli.methodology_rescue_ref_adapter_changes(repo) == []


def test_release_reset_restores_tracked_private_source_adapters(cli, tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / ".gitignore").write_text(
        "adapters/projects/*.json\n"
        "!adapters/projects/example-saas.json\n"
        "!adapters/projects/.bootstrap-legacy-allowlist.json\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore private source adapters")
    _git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    _git(tmp_path, "init", "--bare", "-q", "remote.git")
    _git(repo, "push", "-q", "-u", "origin", "main")

    # New public main removes the private source adapter from the framework tree.
    (repo / ADAPTER_REL).unlink()
    _git(repo, "commit", "-aq", "-m", "remove private adapter from public tree")
    _git(repo, "push", "-q", "origin", "main")

    # Simulate an old installed checkout behind origin/main that still has the tracked adapter.
    _git(repo, "reset", "--hard", "-q", "HEAD~1")
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_RESCUE_STATE_DIR", str(tmp_path / "rescue-state"))

    ok, detail = cli.switch_release_branch("origin/main", "main", "test-reset", preserve_existing_main=False)

    assert ok, detail
    assert (repo / ADAPTER_REL).exists()
    assert json.loads((repo / ADAPTER_REL).read_text(encoding="utf-8"))["project"] == "demo"
    assert "restored private source adapters" in detail
    assert _git(repo, "status", "--short") == ""
