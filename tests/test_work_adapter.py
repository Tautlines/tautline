"""Shared coordination is an explicit, preserved project choice with bounded Git settings."""

import json
import re
from pathlib import Path

import pytest

from tautline_methodology import lean


def config(coordination):
    return {
        "schemaVersion": "lean-1",
        "project": {"name": "Shared project"},
        "integrationBranch": "main",
        "commands": {"test": "scripts/test.sh"},
        "workCoordination": coordination,
    }


@pytest.mark.parametrize("coordination", [True, False, {"backend": "git"}, {
    "backend": "git", "remote": "team-origin", "branch": "coordination/work",
    "syncIntervalSeconds": 10, "timeoutSeconds": 0.25,
}])
def test_supported_coordination_settings_validate_and_preserve(coordination):
    cfg = config(coordination)
    assert lean.lean_config_errors(cfg) == []
    assert lean.lean_config_from_legacy(cfg)["workCoordination"] == coordination
    assert lean.legacy_lane_view(cfg)["workCoordination"] == coordination
    assert (lean.WORK_COORDINATION_LINE in lean.render_lean_adapter(cfg)) is bool(coordination)


@pytest.mark.parametrize("settings,field", [
    ({}, "backend"),
    ({"backend": "local"}, "backend"),
    ({"backend": "git", "token": "never-in-config"}, "unknown property"),
    ({"backend": "git", "remote": "https://example.test/repo.git"}, "remote"),
    ({"backend": "git", "remote": "../repo"}, "remote"),
    ({"backend": "git", "remote": "--upload-pack=bad"}, "remote"),
    ({"backend": "git", "remote": 7}, "remote"),
    ({"backend": "git", "branch": "work/../main"}, "branch"),
    ({"backend": "git", "branch": "work/.hidden"}, "branch"),
    ({"backend": "git", "branch": "work/cache.lock"}, "branch"),
    ({"backend": "git", "branch": "work\nmain"}, "branch"),
    ({"backend": "git", "branch": "-main"}, "branch"),
    ({"backend": "git", "branch": "/main"}, "branch"),
    ({"backend": "git", "branch": "work@{1}"}, "branch"),
    ({"backend": "git", "branch": "work//main"}, "branch"),
    ({"backend": "git", "branch": "work."}, "branch"),
    ({"backend": "git", "branch": "@"}, "branch"),
    ({"backend": "git", "syncIntervalSeconds": 9}, "syncIntervalSeconds"),
    ({"backend": "git", "syncIntervalSeconds": 3601}, "syncIntervalSeconds"),
    ({"backend": "git", "syncIntervalSeconds": 60.5}, "syncIntervalSeconds"),
    ({"backend": "git", "syncIntervalSeconds": True}, "syncIntervalSeconds"),
    ({"backend": "git", "timeoutSeconds": 0.24}, "timeoutSeconds"),
    ({"backend": "git", "timeoutSeconds": 11}, "timeoutSeconds"),
    ({"backend": "git", "timeoutSeconds": float("nan")}, "timeoutSeconds"),
    ({"backend": "git", "timeoutSeconds": True}, "timeoutSeconds"),
])
def test_invalid_shared_config_fails_validation(settings, field):
    assert any(field in error for error in lean.lean_config_errors(config(settings)))


@pytest.mark.parametrize("field,value,valid", [
    ("remote", "origin", True),
    ("remote", "origin\n", False),
    ("remote", "https://example.test/repo.git", False),
    ("branch", "tautline/work", True),
    ("branch", "team/équipe", True),
    ("branch", "tautline/work\n", False),
    ("branch", "/tautline/work", False),
    ("branch", "tautline/cache.lock", False),
])
def test_published_schema_and_runtime_agree_on_git_names(field, value, valid):
    schema_path = Path(__file__).resolve().parents[1] / "methodology/adapter-schema-lean.json"
    schema = json.loads(schema_path.read_text())
    properties = schema["properties"]["workCoordination"]["oneOf"][1]["properties"]
    assert bool(re.search(properties[field]["pattern"], value)) is valid
    assert (not lean.work_coordination_errors({"backend": "git", field: value})) is valid


def test_init_and_slim_keep_shared_backend_and_render_guidance(cli, tmp_path):
    settings = {"backend": "git", "branch": "coordination/work", "timeoutSeconds": 1}
    marker = tmp_path / ".tautline.json"
    marker.write_text(json.dumps(config(settings)))
    assert cli.main(["init", "--target", str(tmp_path), "--yes", "--force"]) == 0
    assert json.loads(marker.read_text())["workCoordination"] == settings
    assert cli.main(["slim", "--target", str(tmp_path), "--keep-agent-hooks"]) == 0
    assert json.loads(marker.read_text())["workCoordination"] == settings
    for name in ("AGENTS.md", "CLAUDE.md"):
        assert lean.WORK_COORDINATION_LINE in (tmp_path / name).read_text()
