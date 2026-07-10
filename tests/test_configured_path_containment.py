"""sec-config-path-1: configured_path is the runtime backstop that keeps adapter-configured paths
under the project root. Absolute, ~-expanded, and ..-escaping values are rejected unless a call site
opts out via allow_outside for a legitimately external field (scratchPaths, laneCoordination roots,
operator-supplied CLI paths).
"""

import pytest


def test_relative_path_resolves_under_target_unchanged(cli, tmp_path):
    result = cli.configured_path(tmp_path, "docs/planning/source.md")
    assert result == tmp_path / "docs" / "planning" / "source.md"


def test_target_itself_is_contained(cli, tmp_path):
    assert cli.configured_path(tmp_path, ".") == tmp_path / "."


def test_absolute_path_rejected(cli, tmp_path):
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_path(tmp_path, "/etc/passwd")


def test_home_path_rejected(cli, tmp_path):
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_path(tmp_path, "~/.ssh/id_rsa")


def test_dotdot_escape_rejected(cli, tmp_path):
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_path(tmp_path, "../../etc")


def test_interior_dotdot_that_escapes_rejected(cli, tmp_path):
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_path(tmp_path, "a/../../b")


def test_allow_outside_permits_external_scratch_dir(cli, tmp_path):
    # The framework default scratchPaths value (~/.claude/plans/) is intentionally external.
    result = cli.configured_path(tmp_path, "~/.claude/plans/", allow_outside=True)
    assert result == cli.Path("~/.claude/plans/").expanduser()


def test_configured_paths_plural_contains_by_default(cli, tmp_path):
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_paths(tmp_path, ["ok/here", "/etc/shadow"])


# --- Codex P2: operator CLI args / framework-internal paths are NOT contained ---------------
#
# A5's containment backstop targets adversarial ADAPTER-config values. Operator-typed CLI file
# arguments (e.g. monitor-status --log /tmp/run.log) and framework-written manifest/run-metadata
# paths are trusted external inputs and must resolve without ValueError. cli_path() is the
# non-contained sibling used at those sites; configured_path() stays contained for adapter values.


def test_cli_path_absolute_operator_arg_resolves(cli, tmp_path):
    # Regression: monitor-status --log /tmp/run.log is a legitimate external input, not adapter config.
    result = cli.cli_path(tmp_path, "/tmp/run.log")
    assert result == cli.Path("/tmp/run.log")


def test_cli_path_relative_arg_joins_target(cli, tmp_path):
    assert cli.cli_path(tmp_path, "runs/current.log") == tmp_path / "runs" / "current.log"


def test_cli_path_home_arg_expands_outside_root(cli, tmp_path):
    assert cli.cli_path(tmp_path, "~/notes.md") == cli.Path("~/notes.md").expanduser()


def test_configured_path_still_contains_absolute(cli, tmp_path):
    # The classification split must NOT loosen containment for adapter-sourced values.
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.configured_path(tmp_path, "/tmp/run.log")


# --- Codex R2 P2: harness command TEXT tolerates non-project tokens -------------------------


def test_harness_command_with_absolute_executable_tolerated(cli, tmp_path):
    # behaviorSpecs.acceptanceHarnesses[].command is command TEXT, not a path field. An absolute
    # executable first token (e.g. `/bin/sh scripts/acceptance.sh`) must not abort
    # methodology-status/lane-start via the containment ValueError; the token is simply not a
    # project script, and the in-project script token must still be found and read for proof.
    script = tmp_path / "scripts" / "acceptance.sh"
    script.parent.mkdir()
    script.write_text("echo acceptance-proof\n", encoding="utf-8")
    text = cli.behavior_harness_script_text(tmp_path, "/bin/sh scripts/acceptance.sh")
    assert "acceptance-proof" in text


def _minimal_document_context_data(**overrides: list[str]) -> dict:
    """Smallest data dict document_context_status_data needs, per derived_document_context()."""
    data = {
        "documentContext": {
            "enforcement": "warn",
            "contextIndexPaths": ["docs/_index.md"],
            "trackedDocRoots": ["docs"],
            "historicalPaths": ["docs/archive"],
            "ignoredDocPaths": [],
            "maxIndexBytes": 16000,
            "maxIndexLines": 250,
        },
        "planningArtifacts": {"sourceOfTruth": "docs/planning", "scratchPaths": []},
        "laneState": {"runsDir": ".ai-work/runs", "executionPacket": ".ai-work/packet"},
        "continuity": {"path": ".ai-work/continuity", "archiveDir": ".ai-work/continuity/archive"},
        "laneCoordination": {"enabled": False},
    }
    data["documentContext"].update(overrides)
    return data


@pytest.mark.parametrize("field", ["contextIndexPaths", "trackedDocRoots", "historicalPaths"])
def test_document_context_roots_are_contained_by_default(cli, tmp_path, field):
    # sec-a5-followup: contextIndexPaths/trackedDocRoots/historicalPaths default to in-project paths
    # and are not documented in adapter-schema.json as containment-exempt, so document_context_status_data
    # must apply the normal containment backstop to them (unlike scratchPaths/laneCoordination, which are
    # documented allowlist exceptions).
    data = _minimal_document_context_data(**{field: ["../outside"]})
    with pytest.raises(ValueError, match="escapes the project root"):
        cli.document_context_status_data(data, tmp_path)
