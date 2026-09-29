"""T6 (0.9.0 sanitized instrumentation): adapter status wiring.

The instrumentation state prints on lane-start / methodology-status, and the session-journal opt-in
hint now points adopters at sanitized instrumentation (zero product-information capacity) as the
safe way to contribute upstream -- narrative journals can no longer leave the machine.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def test_instrumentation_defaults_disabled_milestone(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw.pop("instrumentation", None)
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(path)
    assert data["instrumentation"] == {"enabled": False, "cadence": "milestone"}


def _render_adapter_for(cli, tmp_path, *, enabled: bool) -> str:
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": enabled, "cadence": "milestone"}
    if enabled:
        raw["observabilityEvents"] = {**raw.get("observabilityEvents", {}), "enabled": True}
    path = tmp_path / f"adapter-{enabled}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(path)
    return cli.render_adapter(data, "claude", str(path))


def test_instrumentation_enabled_requires_observability(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": True}
    raw["observabilityEvents"] = {**raw.get("observabilityEvents", {}), "enabled": False}
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        cli.load_project(path)
    except SystemExit as exc:
        assert "observabilityEvents.enabled" in str(exc)
    else:
        raise AssertionError("expected a configuration-coherence SystemExit")


def test_instrumentation_rejects_unknown_subkey(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": True, "branch": "custom-telemetry"}
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        cli.load_project(path)
    except SystemExit as exc:
        assert "branch" in str(exc)
    else:
        raise AssertionError("expected a hard validation error for unknown instrumentation subkey")
