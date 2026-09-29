"""Item 80 WS2: the shipped plan template, measured against the content contract.

If a lane can fill the template in completely and still fail `plan-substance-check`, the TEMPLATE
is the defect, not the lane. Report-only: the enum has no blocking value at all.
"""

from __future__ import annotations



def _template(tmp_path, text):
    p = tmp_path / "template.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_both_new_knobs_are_accepted_by_the_adapter_schema(cli) -> None:
    """Codex R1 P2. `planning.additionalProperties` is false, so a project following the release
    note would have had its adapter REJECTED before the normalizer ever ran -- the advertised
    modes were unusable from a real lane. A knob documented but unschema'd is worse than absent."""
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema.json").read_text()
    )
    planning = schema["properties"]["planning"]

    assert planning.get("additionalProperties") is False, "the constraint that made this a bug"
    assert {"contentPregate", "templateCoverage"} <= set(planning["properties"])
    assert planning["properties"]["contentPregate"]["properties"]["enforcement"]["enum"] == [
        "off", "warn", "block",
    ]
    assert planning["properties"]["templateCoverage"]["properties"]["enforcement"]["enum"] == [
        "off", "report",
    ], "no blocking value exists, and the schema says so too"
