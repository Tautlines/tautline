import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_dirs_renamed():
    assert (ROOT / "plugins/tautline-core").is_dir()
    assert (ROOT / "plugins/tautline-ops").is_dir()
    assert not (ROOT / "plugins/minervit-ai-delivery-methodology").exists()
    assert not (ROOT / "plugins/minervit-delivery-ops").exists()


def test_plugin_declared_names():
    for sub in (".claude-plugin", ".codex-plugin"):
        assert json.loads((ROOT / f"plugins/tautline-core/{sub}/plugin.json").read_text())["name"] == "tautline-core"
        assert json.loads((ROOT / f"plugins/tautline-ops/{sub}/plugin.json").read_text())["name"] == "tautline-ops"
