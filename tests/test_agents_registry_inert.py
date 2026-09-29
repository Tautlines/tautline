"""R1 is inert by construction, and that is a test, not a claim.

R1's whole value is that it can land against the operator's real adapters before any behavior
changes. Three properties make that true: nothing new is rendered, the inference never reaches
the adapter mapping, and no gate reads `roles` yet.
"""
import json
from pathlib import Path

from tautline_methodology import agent_compat


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = ROOT / "adapters" / "projects" / "example-saas.json"

# Measured by rendering to a scratch directory before this program changed anything, and
# re-measured at the R1 tip. NOT inherited from a comment: the figure this replaces was seven
# bytes stale on each file, which is how the corridor came to be oversubscribed.
# Re-measured 2026-08-20 (+189/+189 bytes): the 0.116.0 five-round lineage-budget release
# deliberately rewrote the rendered "Autonomy And Planning" review line; the registry itself
# still emits nothing -- these constants pin the render WITHOUT the registry, whatever other
# features legitimately move it.
R1_RENDERED_CLAUDE_BYTES = 16_312
R1_RENDERED_AGENTS_BYTES = 16_253


def test_registering_agents_does_not_change_the_rendered_output(run_cli, tmp_path):
    """An adapter that declares the registry renders identically to one that does not.
    Nothing reads it yet."""
    base = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    withreg = json.loads(json.dumps(base))
    withreg["agents"] = {
        "claude-code": {"vendor": "anthropic", "runtime": "claude-code",
                        "instructionFile": "CLAUDE.md"},
        "codex": {"vendor": "openai", "runtime": "codex", "instructionFile": "AGENTS.md"},
    }
    withreg["roles"] = {
        "planner": "claude-code", "planReviewer": "codex",
        "builder": "claude-code", "implementationReviewer": "codex",
    }

    rendered = {}
    for name, data in (("plain", base), ("withreg", withreg)):
        # The TRUSTED repo-local path. `require_source_adapter_for_target` refuses an ad-hoc
        # lane-local adapter by name, so a tmp_path/*.json fixture never reaches the renderer.
        target = tmp_path / name
        (target / ".tautline").mkdir(parents=True)
        adapter = target / ".tautline" / "adapter.json"
        adapter.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = run_cli("render-adapters", "--project", str(adapter),
                         "--target", str(target), "--write")
        assert result.returncode == 0, result.stdout + result.stderr
        # BOTH instruction files. Comparing only CLAUDE.md lets a registry-carrying adapter
        # change AGENTS.md and still pass, and R1's goal is zero delta for both.
        rendered[name] = {f.name: f.read_bytes() for f in sorted(target.glob("*.md"))}

    assert rendered["plain"] == rendered["withreg"]
    assert set(rendered["plain"]) == {"CLAUDE.md", "AGENTS.md"}


def test_a_legacy_adapter_renders_no_synthesised_registry(run_cli, tmp_path):
    """THE REGRESSION THIS FILE EXISTS FOR, found by executing R1 rather than by reviewing it.

    An earlier version merged the shim's inference into the adapter mapping, and
    `render-adapters` promptly wrote a whole synthesised `agents` block into the generated
    adapter -- a file stamped `doNotEdit`. That is worse than a byte delta: it is adapter
    content the adopter never wrote. Anything a serialiser can reach eventually gets serialised,
    so the inference must never enter the mapping at all.
    """
    target = tmp_path / "lane"
    (target / ".tautline").mkdir(parents=True)
    adapter = target / ".tautline" / "adapter.json"
    adapter.write_text(EXAMPLE_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8")
    result = run_cli("render-adapters", "--project", str(adapter),
                     "--target", str(target), "--write")
    assert result.returncode == 0, result.stdout + result.stderr
    generated = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert "agents" not in generated, (
        "a synthesised agents block reached the generated adapter; the legacy inference must be "
        "merged on read, never written into the mapping"
    )
    assert "roles" not in generated


def test_the_projection_leaves_the_mapping_untouched():
    legacy = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    projected = agent_compat.effective_agents(legacy)
    assert agent_compat.merged_registry(projected), "precondition: the shim inferred something"
    assert "agents" not in projected
    assert "roles" not in projected
    assert json.loads(json.dumps(projected)) == legacy


# `test_no_gate_reads_roles_in_r1` lived here until R2.2. It asserted that NOTHING read
# `roles`, which is what made R1 provably inert. R2.2 adds the first legitimate consumer --
# the per-agent `transcriptMarker` lookup in the implementation-review scan -- so the guard
# was deleted in that same commit rather than weakened. The byte-delta assertions below
# stay: R1 rendering no extra bytes is still true and still worth pinning.
