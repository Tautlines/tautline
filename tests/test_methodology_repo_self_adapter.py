"""The framework repo's own adapter contract, lean era.

Until 2026-08-30 this file pinned the 1.x self-adapter chain (.tautline/adapter.json ->
render-adapters -> .tautline.json with _generated provenance). `tautline slim` migrated the
framework repo itself onto the lean profile (the reviewed migration PR #626): the source adapter
retired to docs/archive-prebankruptcy/, .tautline.json became a lean-1 config, and the render
chain no longer applies to this repo. What still pays rent:

* the committed lean config must stay valid against the authoritative lean validator and
  public-safe (this repo dogfoods the profile it ships);
* CLAUDE.md / AGENTS.md stay HAND-AUTHORED -- the migration deliberately kept them (they carry
  repo facts the generated lean adapter does not render), and a generated header appearing on
  either means someone re-rendered over that decision;
* render-adapters behaviors that once used the self-adapter as a convenient 1.x fixture
  (deprecation warnings, decode-error hints) are retargeted to the shipped example adapter --
  1.x adopters still render, so the behaviors still matter.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tautline_methodology import lean


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
PUBLIC_EXPORT_MARKER = REPO_ROOT / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; its subject files (self-adapter, bootstraps) are export-excluded",
)
LEAN_ADAPTER = REPO_ROOT / ".tautline.json"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        text=True,
        capture_output=True,
        timeout=60,
    )


@private_repo_only
def test_methodology_repo_lean_adapter_is_valid_and_public_safe():
    raw_text = LEAN_ADAPTER.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    assert lean.is_lean_config(data)
    assert lean.lean_config_errors(data) == []
    assert data["project"]["name"] == "Tautline"
    assert data["project"]["repo"] == "tautlines/tautline-dev"
    assert data["integrationBranch"] == "experimental"
    assert data["commands"]["test"] == "scripts/test.sh"
    assert "BOOTSTRAP REQUIRED" not in raw_text
    # The five 1.x knownProjectRules survived the migration verbatim; an empty list here means a
    # regeneration dropped them.
    assert len(data.get("projectRules") or []) >= 5


@private_repo_only
def test_methodology_repo_bootstraps_stay_handwritten():
    # The reviewed migration kept CLAUDE.md/AGENTS.md hand-authored (their own projectRule says
    # so): they carry repo facts the generated lean adapter does not render (the Python 3.12
    # gate constraint, the origin/HEAD-vs-experimental warning). slim marks its output with a
    # GENERATED header, so the header appearing here means someone rendered over that decision.
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "<!-- GENERATED -->" not in text, f"{name} must stay hand-authored"
    # And no un-adopted proposal files may linger at the repo root.
    assert not (REPO_ROOT / "CLAUDE.md.lean-proposed").exists()
    assert not (REPO_ROOT / "AGENTS.md.lean-proposed").exists()


def _example_render_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A renderable 1.x lane built from the shipped example adapter (the retired self-adapter
    used to play this fixture role)."""
    target = tmp_path / "repo"
    source = target / ".tautline" / "adapter.json"
    source.parent.mkdir(parents=True)
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    evidence_dir = target / ".ai-work"
    evidence_dir.mkdir()
    (evidence_dir / "evidence-1.txt").write_text("one\n", encoding="utf-8")
    (evidence_dir / "evidence-2.txt").write_text("two\n", encoding="utf-8")
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for render-adapters behaviors.",
        "repoEvidence": [
            {"path": ".ai-work/evidence-1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/evidence-2.txt", "fact": "evidence two exists"},
        ],
    }
    source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:example-org/example-saas.git"],
        check=True,
    )
    return target, source


def test_render_goaltracker_deprecation_warning_uses_raw_source_adapter(tmp_path):
    target, source = _example_render_fixture(tmp_path)

    clean = _run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "goalTracker' is DEPRECATED" not in clean.stderr

    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["goalTracker"] = {"enabled": False}
    source.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    deprecated = _run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert deprecated.returncode == 0, deprecated.stdout + deprecated.stderr
    assert "adapter key 'goalTracker' is DEPRECATED" in deprecated.stderr


def test_render_adapters_raw_source_decode_error_keeps_recovery_hints(tmp_path):
    target = tmp_path / "repo"
    source = target / ".tautline" / "adapter.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        '{\n'
        '  "project": "Broken"\n'
        "<<<<<<< HEAD\n"
        '  "repo": "example/repo"\n'
        "=======\n"
        '  "repo": "example/other"\n'
        ">>>>>>> branch\n"
        "}\n",
        encoding="utf-8",
    )

    result = _run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )

    assert result.returncode != 0
    assert "invalid JSON at line" in result.stderr
    assert "hint: unresolved Git conflict markers are present" in result.stderr
    assert "hint: Fix the project adapter JSON before running lane startup or status commands." in result.stderr
