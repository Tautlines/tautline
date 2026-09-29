"""Published plugin wiring must resolve to the capabilities included in the package."""

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = ROOT / "plugins" / "tautline-core" / ".claude-plugin" / "plugin.json"
OPS_MANIFEST = ROOT / "plugins" / "tautline-ops" / ".codex-plugin" / "plugin.json"
OPS_CLAUDE_MANIFEST = ROOT / "plugins" / "tautline-ops" / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CAPABILITY_REFERENCE = ROOT / "docs" / "reference" / "plugin-capability-catalog.md"


def test_codex_plugin_manifest_is_marketplace_sized():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    interface = manifest["interface"]

    assert 0 < len(interface["defaultPrompt"]) <= 12
    assert len(interface["longDescription"].split()) <= 120
    assert "docs/reference/plugin-capability-catalog.md" in interface["longDescription"]
    assert CAPABILITY_REFERENCE.is_file()


def test_claude_plugin_manifest_is_marketplace_sized():
    manifest = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))

    assert "_notes" not in manifest
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert manifest["skills"] == "./skills/"
    assert len(manifest["description"].split()) <= 20


def test_delivery_ops_plugin_manifests_are_marketplace_sized():
    manifest = json.loads(OPS_MANIFEST.read_text(encoding="utf-8"))
    interface = manifest["interface"]
    claude = json.loads(OPS_CLAUDE_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["name"] == "tautline-ops"
    assert manifest["skills"] == "./skills/"
    assert 0 < len(interface["defaultPrompt"]) <= 8
    assert len(interface["longDescription"].split()) <= 95
    assert claude["name"] == "tautline-ops"
    assert claude["skills"] == "./skills/"
    assert "hooks" not in claude


def test_local_marketplace_registers_core_and_delivery_ops_plugins():
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    plugins = {plugin["name"]: plugin for plugin in marketplace["plugins"]}

    assert plugins["tautline-core"]["source"]["path"] == "./plugins/tautline-core"
    assert plugins["tautline-ops"]["source"]["path"] == "./plugins/tautline-ops"
    assert plugins["tautline-ops"]["policy"]["installation"] == "AVAILABLE"


def test_both_hosts_resolve_the_same_available_skills():
    for name in ("tautline-core", "tautline-ops"):
        package = ROOT / "plugins" / name
        resolved = []
        for host in (".claude-plugin", ".codex-plugin"):
            manifest = json.loads((package / host / "plugin.json").read_text())
            skill_root = (package / manifest["skills"]).resolve()
            assert skill_root.is_relative_to(package.resolve())
            skills = {path.parent.name for path in skill_root.glob("*/SKILL.md")}
            assert skills, f"{host}/{name} has no invokable skills"
            resolved.append(skills)
        assert resolved[0] == resolved[1]


def test_claude_hook_commands_exist_in_the_shipped_cli():
    manifest = json.loads(CLAUDE_MANIFEST.read_text())
    package = CLAUDE_MANIFEST.parent.parent
    hook_path = (package / manifest["hooks"]).resolve()
    assert hook_path.is_relative_to(package.resolve())
    hooks = json.loads(hook_path.read_text())["hooks"]
    verbs = set()
    for entries in hooks.values():
        for entry in entries:
            for hook in entry["hooks"]:
                verbs.update(re.findall(r"\btautline ([a-z][a-z-]+)", hook["command"]))
    assert verbs
    for verb in sorted(verbs):
        result = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "tautline"), verb, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"plugin hook calls unavailable command {verb}"
