import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def valid_feature_request_text() -> str:
    return """# Methodology Feature Request

## What this delivers
Operators can submit methodology enhancement requests through a dedicated durable intake path.

## Why it matters
Separating enhancements from RCA artifacts keeps regression evidence clean and triage reliable.

## Current Gap / Evidence
Current conversation context: operators need feature requests to stop riding the regression RCA archive.

## Proposed Capability
Add a methodology feature-request skill with validation and archive-branch publication.

## Acceptance Criteria
- A valid request artifact can be validated by the CLI.
- The request can be published to a dedicated feature-request archive branch.

## Validation Proof
Run `minervit-methodology validate-feature-request-artifact --file <artifact>` and targeted pytest coverage.

## Risks / Compatibility
The flow is additive and does not mutate existing backlog or GitHub Project board content.

## Suggested Triage
Priority P1; promote accepted requests into `docs/backlog/methodology-backlog.md` after product review.

## Immediate Next Action
Add or update `docs/backlog/methodology-backlog.md` when the request is accepted for implementation.
"""


def write_valid_artifact(path: Path) -> Path:
    path.write_text(valid_feature_request_text(), encoding="utf-8")
    return path


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def test_valid_feature_request_artifact_passes(cli, tmp_path):
    artifact = write_valid_artifact(tmp_path / "20260627T120000Z-methodology-feature-request.md")
    assert cli.validate_feature_request_artifact_file(artifact) == []


def test_feature_request_surface_is_discoverable(run_cli):
    help_result = run_cli("--help")
    assert help_result.returncode == 0
    assert "validate-feature-request-artifact" in help_result.stdout
    assert "publish-feature-request-artifact" in help_result.stdout

    manifest = json.loads(
        (ROOT / "plugins/tautline-core/.codex-plugin/plugin.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_text = json.dumps(manifest)
    assert "Submit a Tautline feature request" in manifest_text
    capability_reference = (ROOT / "docs/reference/plugin-capability-catalog.md").read_text(encoding="utf-8")
    assert "branch-published framework feature-request intake" in capability_reference


def test_feature_request_requires_business_lead(cli, tmp_path):
    artifact = tmp_path / "bad.md"
    artifact.write_text(
        valid_feature_request_text().replace("## What this delivers", "## Technical detail"),
        encoding="utf-8",
    )
    errors = cli.validate_feature_request_artifact_file(artifact)
    assert any("What this delivers" in error for error in errors)


def test_feature_request_rejects_rca_shape(cli, tmp_path):
    artifact = tmp_path / "rca-shaped.md"
    artifact.write_text(
        valid_feature_request_text() + "\n## What happened\n\nA process regression.\n\n## Root cause\n\nMissing rule.\n",
        encoding="utf-8",
    )
    errors = cli.validate_feature_request_artifact_file(artifact)
    assert any("RCA incident heading" in error for error in errors)


def test_feature_request_rejects_person_specific_paths(cli, tmp_path):
    artifact = tmp_path / "path-leak.md"
    artifact.write_text(
        valid_feature_request_text().replace(
            "Current conversation context:",
            "Current conversation context: /Users/alice/project",
        ),
        encoding="utf-8",
    )
    errors = cli.validate_feature_request_artifact_file(artifact)
    assert any("person/machine-specific path" in error for error in errors)


def test_feature_request_requires_concrete_next_action(cli, tmp_path):
    artifact = tmp_path / "generic-next.md"
    artifact.write_text(
        valid_feature_request_text().replace(
            "Add or update `docs/backlog/methodology-backlog.md` when the request is accepted for implementation.",
            "Continue.",
        ),
        encoding="utf-8",
    )
    errors = cli.validate_feature_request_artifact_file(artifact)
    assert any("Immediate Next Action" in error for error in errors)


def test_publish_feature_request_uses_isolated_branch(cli, tmp_path, monkeypatch):
    release = tmp_path / "release"
    remote = tmp_path / "remote.git"
    release.mkdir()
    git(release, "init")
    git(release, "checkout", "-b", "main")
    git(release, "config", "user.name", "Minervit Test")
    git(release, "config", "user.email", "test@example.invalid")
    (release / "README.md").write_text("release checkout\n", encoding="utf-8")
    git(release, "add", "README.md")
    git(release, "commit", "-m", "initial")
    subprocess.check_call(["git", "init", "--bare", str(remote)])
    git(release, "remote", "add", "origin", str(remote))
    git(release, "push", "-u", "origin", "main")

    artifact = write_valid_artifact(tmp_path / "20260627T120000Z-methodology-feature-request.md")
    monkeypatch.setattr(cli, "REPO_ROOT", release)
    monkeypatch.setattr(cli, "DEFAULT_FEATURE_REQUEST_ARCHIVE_DIR", release / "docs" / "backlog" / "feature-requests")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Minervit Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Minervit Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")

    rc = cli.publish_feature_request_artifact(
        argparse.Namespace(
            file=artifact,
            archive_dir=None,
            no_stage=False,
            allow_release_checkout_write=False,
            commit=True,
            push=True,
            branch="methodology-feature-request-archive",
            message=None,
        )
    )

    assert rc == 0
    assert git(release, "branch", "--show-current") == "main"
    assert git(release, "status", "--short") == ""
    tree = subprocess.check_output(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "methodology-feature-request-archive"],
        text=True,
    )
    assert "docs/backlog/feature-requests/20260627T120000Z-methodology-feature-request.md" in tree
    assert "docs/backlog/feature-requests/_index.md" in tree
