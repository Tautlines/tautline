"""Item 80 WS2: the shipped plan template, measured against the content contract.

If a lane can fill the template in completely and still fail `plan-substance-check`, the TEMPLATE
is the defect, not the lane. Report-only: the enum has no blocking value at all.
"""

from __future__ import annotations

import pytest


def _template(tmp_path, text):
    p = tmp_path / "template.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_knob_cannot_be_configured_into_a_refusal(cli) -> None:
    """A template is a starting point, and a lane that deleted a section it does not need has not
    done anything wrong. There is deliberately no `block` value to reach for."""
    from tautline_methodology.plan_authoring import (
        PLAN_TEMPLATE_COVERAGE_ENFORCEMENT_CHOICES,
        normalize_planning_template_coverage,
    )

    assert set(PLAN_TEMPLATE_COVERAGE_ENFORCEMENT_CHOICES) == {"off", "report"}
    assert normalize_planning_template_coverage({})["enforcement"] == "report"

    with pytest.raises(SystemExit) as exc:
        normalize_planning_template_coverage(
            {"planning": {"templateCoverage": {"enforcement": "block"}}}
        )
    assert "off or report" in str(exc.value)


def test_off_computes_nothing(cli, tmp_path) -> None:
    data = {"planning": {"templateCoverage": {"enforcement": "off"}}}

    assert cli.plan_template_coverage_errors(data, _template(tmp_path, "# thin\n")) == []


def test_a_thin_template_reports_its_gaps(cli, tmp_path) -> None:
    issues = cli.plan_template_coverage_errors({}, _template(tmp_path, "# Plan\n\nnothing.\n"))

    assert issues, "a template that cannot satisfy the contract is the thing to fix"


def test_a_missing_template_is_reported_not_raised(cli, tmp_path) -> None:
    issues = cli.plan_template_coverage_errors({}, tmp_path / "absent.md")

    assert issues and "not found" in issues[0]


def test_f1_parity_the_report_consumes_the_gate_s_own_issue_list(cli, tmp_path) -> None:
    """THE REVIEW ANCHOR. A second implementation would drift from the gate, and the drift would be
    invisible precisely because the two are never compared. Same text, same issues, both sides."""
    text = "# Plan\n\nkeyword-poor on purpose.\n"
    path = _template(tmp_path, text)

    from_report = cli.plan_template_coverage_errors({}, path)
    refusals, warnings = cli.plan_review_content_pregate({}, path, 0)

    assert sorted(from_report) == sorted(refusals + warnings), (
        "the template report and the R1 gate must see exactly the same contract"
    )


def test_the_status_line_names_the_template_as_the_thing_to_fix(cli, tmp_path) -> None:
    line = cli.plan_template_coverage_status_line({}, _template(tmp_path, "# Plan\n\nthin.\n"))

    assert "report only" in line
    assert "TEMPLATE" in line, "point at the template, not at the lane reading it"


def test_the_status_line_is_quiet_when_the_template_is_whole(cli, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "plan_template_coverage_errors", lambda d, p: [])

    assert "ok" in cli.plan_template_coverage_status_line({}, tmp_path / "any.md")


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


def test_the_coverage_report_has_a_caller(cli) -> None:
    """Codex R1 P2: this helper was the only emitter for template coverage and nothing called it,
    so the knob had no observable effect. A control that changes nothing advertises a control that
    is not there."""
    import inspect

    source = inspect.getsource(cli)

    assert "plan_template_coverage_status_line(data, template_path)" in source
    assert source.count("plan_template_coverage_status_line(data, template_path)") >= 1
