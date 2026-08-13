"""The fleet adapter domain validates through the real schema validator."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (REPO_ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8")
)


def test_fleet_domain_declared_and_optional():
    assert "fleet" in SCHEMA["properties"]
    assert "fleet" not in SCHEMA.get("required", [])
    props = SCHEMA["properties"]["fleet"]["properties"]
    assert set(props) == {"enabled", "enforcement", "defaultTtlMinutes", "occupancy"}
    assert props["enforcement"]["enum"] == ["block", "advise", "observe"]
    assert SCHEMA["properties"]["fleet"]["additionalProperties"] is False

    # Pinned ONE LEVEL DEEPER than the parent set, because an occupancy sub-object that accepted
    # unknown keys would take a typo silently -- and a coordination gate reading a key nobody
    # spelled correctly is the failure this schema exists to prevent.
    occupancy = props["occupancy"]
    assert occupancy["additionalProperties"] is False
    assert set(occupancy["properties"]) == {
        "enabled",
        "mode",
        "primaryCheckout",
        "ttlMinutes",
    }
    assert occupancy["properties"]["mode"]["enum"] == ["refuse", "auto-worktree", "observe"]
    assert occupancy["properties"]["primaryCheckout"]["enum"] == ["report", "refuse"]


def test_fleet_domain_accepted_by_validator(cli, tmp_path):
    adapter = json.loads(
        (REPO_ROOT / "adapters" / "projects" / "example-saas.json").read_text(
            encoding="utf-8"
        )
    )
    adapter["fleet"] = {"enforcement": "observe"}
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(adapter), encoding="utf-8")
    cli.validate_adapter_schema(adapter, path)  # must not raise
