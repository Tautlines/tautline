import json
from pathlib import Path

from tautline_methodology import agents

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "methodology" / "adapter-schema.json"
MANIFEST = ROOT / "methodology" / "public-contract-manifest.json"


def _schema():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_schema_declares_agents_and_roles():
    props = _schema()["properties"]
    assert "agents" in props
    assert "roles" in props


def test_agents_and_roles_are_registered_adapter_keys():
    names = {e["name"] for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["adapterKeys"]}
    assert "agents" in names
    assert "roles" in names


def test_vendor_is_a_free_form_string_with_no_enum():
    """THE load-bearing schema constraint. An enum here rejects every adopter the framework
    has never heard of, which is the exact defect this program removes."""
    agent = _schema()["properties"]["agents"]["additionalProperties"]
    vendor = agent["properties"]["vendor"]
    assert vendor["type"] == "string"
    assert "enum" not in vendor
    assert "const" not in vendor
    assert "pattern" not in vendor


def test_runtime_is_a_free_form_string_with_no_enum():
    agent = _schema()["properties"]["agents"]["additionalProperties"]
    runtime = agent["properties"]["runtime"]
    assert runtime["type"] == "string"
    assert "enum" not in runtime
    assert "const" not in runtime


def test_schema_required_agent_fields_match_the_module():
    agent = _schema()["properties"]["agents"]["additionalProperties"]
    assert sorted(agent["required"]) == sorted(agents.REQUIRED_AGENT_FIELDS)


def test_roles_property_names_match_the_module():
    roles = _schema()["properties"]["roles"]
    assert sorted(roles["properties"]) == sorted(agents.ROLE_NAMES)
    assert roles["additionalProperties"] is False
