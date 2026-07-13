"""Every published version surface must move together.

`scripts/validate.sh` only compares `VERSION` against `.codex-plugin/plugin.json`, so the
`.claude-plugin/plugin.json` manifest — the version Claude Code actually reads — can silently
drift (it did, lagging a release behind at 0.6.115 while VERSION was 0.6.116). This guard,
in the non-frozen pytest tier, fails closed when they disagree.

The root `.claude-plugin/marketplace.json` is the same hazard one level up: it is the
version a user sees when they add the marketplace, and it drifted the moment it was
introduced (advertising 0.9.5 against a 0.9.6 VERSION). It is pinned here too, so a
release bump cannot leave the public marketplace advertising a stale version.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = (
    ROOT / "plugins" / "tautline-core",
    ROOT / "plugins" / "tautline-ops",
)
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
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


def test_marketplace_manifest_version_is_locked():
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["metadata"]["version"]
    assert version_file == marketplace, (
        f"version drift in .claude-plugin/marketplace.json: VERSION={version_file}, "
        f"marketplace metadata.version={marketplace} — this is the version a user sees "
        "when they run `/plugin marketplace add tautlines/tautline`, so it must be "
        "bumped with the release"
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
