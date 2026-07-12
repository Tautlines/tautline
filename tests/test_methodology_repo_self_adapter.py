import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
PUBLIC_EXPORT_MARKER = REPO_ROOT / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; its subject files (self-adapter) are export-excluded",
)
SOURCE_ADAPTER = REPO_ROOT / ".tautline" / "adapter.json"
GENERATED_ADAPTER = REPO_ROOT / ".tautline.json"


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        text=True,
        capture_output=True,
        timeout=60,
    )


@private_repo_only
def test_methodology_repo_source_adapter_is_public_safe_and_json_only():
    raw_text = SOURCE_ADAPTER.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    assert "BOOTSTRAP REQUIRED" not in raw_text
    assert "goalTracker" not in data
    assert data["project"] == "Minervit AI Delivery Methodology"
    assert data["repo"] == "tautlines/tautline-dev"
    assert data["productionDeployExists"] is False
    assert data["_framework"]["channel"] == "stable"
    assert data["_framework"]["updatePolicy"] == "manual"
    assert data["generatedFiles"] == [".tautline.json"]
    assert data["technologyStack"]["cloudProviderDefault"] == "none"
    assert data["developmentEnvironment"]["windows"]["supportedRuntime"] == "wsl2"
    assert data["review"]["codexWrapper"] == "codex review --base origin/experimental"
    assert "--full-context" not in data["review"]["codexWrapper"]

    evidence = data["bootstrapEvidence"]
    assert evidence["status"] == "repo-evident"
    for item in evidence["repoEvidence"]:
        assert (REPO_ROOT / item["path"]).is_file(), item["path"]


@private_repo_only
def test_methodology_repo_generated_adapter_is_fresh_and_preserves_handwritten_bootstraps():
    generated = json.loads(GENERATED_ADAPTER.read_text(encoding="utf-8"))

    assert generated["_generated"]["sourceAdapter"] == ".tautline/adapter.json"
    assert generated["_generated"]["sourceAdapterSha256"] == hashlib.sha256(SOURCE_ADAPTER.read_bytes()).hexdigest()
    assert generated["_generated"]["methodologyCommit"] == "self-referential-methodology-repo"
    assert generated["_generated"]["regenerate"].endswith("--write --json-only")
    assert generated["generatedFiles"] == [".tautline.json"]

    json_check = _run_cli(
        "render-adapters",
        "--project",
        str(SOURCE_ADAPTER),
        "--target",
        str(REPO_ROOT),
        "--check",
        "--json-only",
    )
    assert json_check.returncode == 0, json_check.stdout + json_check.stderr
    assert "goalTracker' is DEPRECATED" not in json_check.stderr

    full_check = _run_cli(
        "render-adapters",
        "--project",
        str(SOURCE_ADAPTER),
        "--target",
        str(REPO_ROOT),
        "--check",
    )
    assert full_check.returncode == 1
    assert "protected:" in full_check.stdout
    assert str(REPO_ROOT / "AGENTS.md") in full_check.stdout
    assert str(REPO_ROOT / "CLAUDE.md") in full_check.stdout


@private_repo_only
def test_methodology_repo_self_adapter_marker_uses_target_checkout(cli, tmp_path):
    target = tmp_path / "methodology-copy"
    source = target / ".tautline" / "adapter.json"
    source.parent.mkdir(parents=True)
    shutil.copy2(SOURCE_ADAPTER, source)
    shutil.copy2(GENERATED_ADAPTER, target / ".tautline.json")
    shutil.copy2(REPO_ROOT / "AGENTS.md", target / "AGENTS.md")
    shutil.copy2(REPO_ROOT / "CLAUDE.md", target / "CLAUDE.md")
    scripts = target / "scripts"
    scripts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "test.sh", scripts / "test.sh")
    shutil.copy2(REPO_ROOT / "scripts" / "validate.sh", scripts / "validate.sh")
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:minervit/minervit-ai-delivery-methodology.git"],
        check=True,
    )

    result = _run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--check",
        "--json-only",
    )

    assert result.returncode == 0, result.stdout + result.stderr

    source_data = cli.load_project(source)
    generated_data = cli.load_project(target / ".tautline.json")
    assert cli.adapter_drift(source_data, source, target) == []
    assert cli.adapter_drift(generated_data, target / ".tautline.json", target) == []


@private_repo_only
def test_render_goaltracker_deprecation_warning_uses_raw_source_adapter(tmp_path):
    target = tmp_path / "repo"
    source = target / ".tautline" / "adapter.json"
    source.parent.mkdir(parents=True)
    for rel in ("AGENTS.md", "CLAUDE.md"):
        shutil.copy2(REPO_ROOT / rel, target / rel)
    scripts = target / "scripts"
    scripts.mkdir()
    for rel in ("scripts/test.sh", "scripts/validate.sh"):
        shutil.copy2(REPO_ROOT / rel, target / rel)
    shutil.copy2(SOURCE_ADAPTER, source)

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
