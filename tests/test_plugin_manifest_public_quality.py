import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = ROOT / "plugins" / "tautline-core" / ".claude-plugin" / "plugin.json"
OPS_MANIFEST = ROOT / "plugins" / "tautline-ops" / ".codex-plugin" / "plugin.json"
OPS_CLAUDE_MANIFEST = ROOT / "plugins" / "tautline-ops" / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CAPABILITY_REFERENCE = ROOT / "docs" / "reference" / "plugin-capability-catalog.md"
EXPECTED_PUBLIC_PROMPTS = {
    "Submit a Tautline feature request.",
    "Check public-release readiness and migration status.",
}
EXPECTED_OPS_PROMPTS = {
    "Prepare an iteration review from a delivered goal.",
    "Publish a milestone update through the configured delivery channel.",
    "Prepare or publish a session journal.",
    "Record or report local usage evidence.",
    "Resolve a database migration collision.",
}
REQUIRED_CAPABILITY_PHRASES = (
    "portable CLI bootstrap",
    "latest-code baseline verification",
    "Project bootstrap with mandatory adapter interview",
    "Goal orchestration with source-of-truth goal plans",
    "real repository issue exports by default",
    "Native/Superpowers review before the first T2/T3 plan-review round",
    "risk-tiered implementation review round budgets",
    "plan-review convergence ladder",
    "focus transfer for findings that do not justify another round",
    "unconditional refusal past the hard cap of four rounds",
    "adapter-enabled customer-facing iteration reviews",
    "quick product-space Google Chat notes through adapter-configured webhooks",
    "context rotation at PR/milestone/goal boundaries",
    "document context budgeting",
    "background monitoring with liveness/stale checks",
    "Claude Bash hook blocking",
    "Provider recovery loops",
    "memory-as-evidence-only enforcement",
    "branch-published framework feature-request intake",
    "adapter-backed behavior-spec source materials",
    "adapter-backed technical stack defaults with AWS-first cloud guidance",
)


def _heading_lines(text):
    return {line.strip() for line in text.splitlines() if line.startswith("#")}


def test_codex_plugin_manifest_is_marketplace_sized():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    interface = manifest["interface"]

    assert len(interface["defaultPrompt"]) <= 12
    assert len(interface["longDescription"].split()) <= 120
    assert "docs/reference/plugin-capability-catalog.md" in interface["longDescription"]
    assert EXPECTED_PUBLIC_PROMPTS <= set(interface["defaultPrompt"])


def test_claude_plugin_manifest_is_marketplace_sized():
    manifest = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))

    assert "_notes" not in manifest
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert manifest["skills"] == "./skills/"
    assert len(manifest["description"].split()) <= 20
    assert "Claude Code package" in manifest["description"]


def test_delivery_ops_plugin_manifests_are_marketplace_sized():
    manifest = json.loads(OPS_MANIFEST.read_text(encoding="utf-8"))
    interface = manifest["interface"]
    claude = json.loads(OPS_CLAUDE_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["name"] == "tautline-ops"
    assert manifest["skills"] == "./skills/"
    assert len(interface["defaultPrompt"]) <= 8
    assert len(interface["longDescription"].split()) <= 95
    assert EXPECTED_OPS_PROMPTS <= set(interface["defaultPrompt"])
    assert claude["name"] == "tautline-ops"
    assert claude["skills"] == "./skills/"
    assert "hooks" not in claude


def test_local_marketplace_registers_core_and_delivery_ops_plugins():
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    plugins = {plugin["name"]: plugin for plugin in marketplace["plugins"]}

    assert plugins["tautline-core"]["source"]["path"] == "./plugins/tautline-core"
    assert plugins["tautline-ops"]["source"]["path"] == "./plugins/tautline-ops"
    assert plugins["tautline-ops"]["policy"]["installation"] == "AVAILABLE"


def test_plugin_capability_reference_keeps_detailed_catalog():
    text = CAPABILITY_REFERENCE.read_text(encoding="utf-8")
    headings = _heading_lines(text)

    assert len(text.split()) >= 900
    assert text.startswith("# Tautline Plugin Capability Catalog")
    assert "# Tautline Plugin Capability Catalog" in headings
    assert "## Default Prompts" in headings
    assert "## Detailed Capability Narrative" in headings
    assert "### Startup And Adapter Lifecycle" in headings
    assert "### Planning, Goals, Backlog, And Coordination" in headings
    assert "### Review, Gates, And Quality Control" in headings
    assert "### Delivery, Visibility, And Stakeholder Updates" in headings
    assert "### Runtime Continuity And Operational Resilience" in headings
    assert "### Governance, Safety, And Specialized Skills" in headings


def test_plugin_capability_reference_preserves_required_catalog_phrases():
    text = CAPABILITY_REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    missing = [phrase for phrase in REQUIRED_CAPABILITY_PHRASES if phrase not in normalized]
    assert missing == []


def test_plugin_capability_reference_has_no_wall_of_text_regression():
    text = CAPABILITY_REFERENCE.read_text(encoding="utf-8")
    non_table_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.startswith("|")
    ]

    assert max(len(line.split()) for line in non_table_lines) <= 45
