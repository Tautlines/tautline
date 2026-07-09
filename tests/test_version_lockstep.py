"""All three version surfaces must move together.

`scripts/validate.sh` only compares `VERSION` against `.codex-plugin/plugin.json`, so the
`.claude-plugin/plugin.json` manifest — the version Claude Code actually reads — can silently
drift (it did, lagging a release behind at 0.6.115 while VERSION was 0.6.116). This guard,
in the non-frozen pytest tier, fails closed when the three disagree.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = (
    ROOT / "plugins" / "tautline-core",
    ROOT / "plugins" / "tautline-ops",
)
SEMVER = __import__("re").compile(r"^\d+\.\d+\.\d+$")


def test_version_surfaces_are_locked():
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert SEMVER.match(version_file), f"VERSION is not semver: {version_file!r}"
    for plugin in PLUGINS:
        codex = json.loads((plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
        claude = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
        assert version_file == codex == claude, (
            f"version drift in {plugin.name}: VERSION={version_file}, "
            f".codex-plugin={codex}, .claude-plugin={claude} "
            "(the .claude-plugin manifest must be bumped in lockstep — validate.sh does not catch it)"
        )


def test_lane_session_plugin_version_contracts_remain_pinned(cli):
    cli_source = (ROOT / "bin" / "tautline").read_text(encoding="utf-8")

    assert "lane_session_plugin_version_at_start" in cli_source
    assert "plugin_version_drift" in cli_source
    assert cli.version_tuple("0.6.73") < cli.version_tuple(
        cli.STAGE1_SWEEP_REQUIREMENT_PLUGIN_VERSION
    ), "pre-requirement manifest version must order below the requirement"
    assert cli.version_tuple(cli.plugin_version()) >= cli.version_tuple(
        cli.STAGE1_SWEEP_REQUIREMENT_PLUGIN_VERSION
    ), "current plugin must be at/after the stage1-sweep requirement"
