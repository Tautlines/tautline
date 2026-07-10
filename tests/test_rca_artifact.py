def _valid_rca_text(*, proposed_control: str | None = None) -> str:
    control = proposed_control or (
        "Add focused RCA artifact tests under tests/test_rca_artifact.py and update the methodology skill reference."
    )
    return f"""# Methodology Regression RCA

## What happened
The lane skipped a required durable RCA artifact during a methodology regression.

## Evidence
- methodology/canonical-rules.md: resolved active process authority.

## Root cause
The validation coverage was incomplete around RCA artifact shape and authority handling.

## Proposed control
{control}

## Validation
Run `minervit-methodology validate-rca-artifact --file docs/backlog/methodology-regressions/example.md`.
"""


def test_valid_rca_artifact_passes(cli, tmp_path):
    artifact = tmp_path / "rca.md"
    artifact.write_text(_valid_rca_text(), encoding="utf-8")

    assert cli.validate_rca_artifact_file(artifact) == []


def test_rca_artifact_rejects_memory_as_proposed_control_authority(cli, tmp_path):
    artifact = tmp_path / "memory-authority.md"
    artifact.write_text(
        _valid_rca_text(
            proposed_control="Open Brain memory says the lane should validate the RCA artifact."
        ),
        encoding="utf-8",
    )

    errors = cli.validate_rca_artifact_file(artifact)

    assert "Proposed control cannot cite memory/Open Brain as process authority" in errors


def test_rca_artifact_no_longer_polices_tone_phrases(cli, tmp_path):
    artifact = tmp_path / "tone.md"
    artifact.write_text(
        _valid_rca_text(
            proposed_control="I apologize for the miss. Add focused RCA artifact tests under tests/test_rca_artifact.py."
        ),
        encoding="utf-8",
    )

    assert cli.validate_rca_artifact_file(artifact) == []


def test_rca_artifact_requires_reduced_substance_headings(cli, tmp_path):
    artifact = tmp_path / "missing.md"
    artifact.write_text(
        "# Methodology Regression RCA\n\n## What happened\nThe lane skipped the durable RCA artifact.\n",
        encoding="utf-8",
    )

    errors = cli.validate_rca_artifact_file(artifact)

    assert "missing required heading: ## Evidence" in errors
    assert "missing required heading: ## Root cause" in errors
    assert "missing required heading: ## Proposed control" in errors
    assert "missing required heading: ## Validation" in errors


def test_rca_artifact_commands_are_discoverable(run_cli):
    validate_help = run_cli("validate-rca-artifact", "--help")
    publish_help = run_cli("publish-rca-artifact", "--help")

    assert validate_help.returncode == 0
    assert "validate-rca-artifact" in validate_help.stdout
    assert publish_help.returncode == 0
    assert "publish-rca-artifact" in publish_help.stdout
