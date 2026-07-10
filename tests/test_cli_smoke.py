"""Smoke tests: the CLI loads in-process and dispatches as a subprocess."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_loads(cli):
    # The `cli` fixture imports the extension-less executable in-process.
    assert hasattr(cli, "response_guard_errors")
    assert hasattr(cli, "main")


def test_version_subcommand_dispatches(run_cli, cli):
    result = run_cli("version", "--no-remote")
    manifest = json.loads(
        (ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.returncode == 0
    assert f"plugin: {manifest['name']}" in result.stdout
    assert f"plugin_version: {cli.plugin_version()}" in result.stdout
    assert "version_source: VERSION" in result.stdout
    assert "methodology_commit:" in result.stdout
