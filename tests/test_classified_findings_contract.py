"""The stitch: items 73 and 74 PR-B extend ONE record, under ONE version constant.

Operator DECISION 2 exists because two independently-versioned extensions of the same evidence
record is a defect in waiting — a manifest could be legacy under one rule family and strict under
the other, and no single test would see it. These are the verification anchors for that decision.

The composed case is the six-field deferred Critical: an out-of-AC blocker, routed at honest
severity to a named row, deferred with its reason and the criterion it was judged against. It is
verbose and it is coherent — the two rule sets cannot contradict, because item 73 only FORBIDS
(AC-bearing + routed, routed under `clean`) and item 74 only REQUIRES (deferred blocker → reason
and criterion, `clean-with-deferrals` → non-empty findings plus the flag).
"""
import pytest

from _classified_findings_fixtures import (
    assert_legacy_version_is_below_contract,
    finalize,
    lane,
    legacy_plugin_version,
)

# The worked example from the doc section, verbatim in shape.
COMPOSED_DEFERRED_CRITICAL = {
    "id": "R1",
    "severity": "critical",
    "summary": "the export retry loop is unbounded",
    "status": "deferred",
    "ac_ref": None,
    "disposition": "routed",
    "routed_to": "BACKLOG-482",
    "deferral_rationale": "the retry path is unreachable until the throttle flag ships",
    "acceptance_criterion": "AC4: the export completes within the throttle ceiling",
}


def test_the_composed_six_field_deferred_critical_is_accepted(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[COMPOSED_DEFERRED_CRITICAL],
    )
    assert rc == 0, capsys.readouterr().err
    recorded = subject.manifest()["classified_findings"][0]
    # Honest severity survives the round trip: nothing downgraded it to make routing legal.
    assert recorded["severity"] == "critical"
    assert recorded["routed_to"] == "BACKLOG-482"


@pytest.mark.parametrize(
    ("dropped", "named"),
    [
        ("ac_ref", "ac_ref"),
        ("disposition", "disposition"),
        ("routed_to", "routed_to"),
        ("deferral_rationale", "deferral_rationale"),
        ("acceptance_criterion", "acceptance_criterion"),
    ],
)
def test_each_five_field_variant_is_refused_by_name(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
    dropped,
    named,
):
    """A refusal that does not name the field it wants is a dead end in contract's clothing."""
    finding = {key: value for key, value in COMPOSED_DEFERRED_CRITICAL.items() if key != dropped}
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=[finding])
    assert rc == 1, f"dropping {dropped} must refuse"
    assert named in capsys.readouterr().err


def test_dropping_the_deferred_status_leaves_a_valid_routed_finding(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    """The two axes really are orthogonal: without `status: deferred` item 74's rules do not
    apply at all, and what remains is item 73's ordinary routed out-of-AC finding."""
    finding = {
        key: value
        for key, value in COMPOSED_DEFERRED_CRITICAL.items()
        if key not in {"status", "deferral_rationale", "acceptance_criterion"}
    }
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=[finding])
    assert rc == 0, capsys.readouterr().err


# --- never mixed --------------------------------------------------------------------------------

AC_FIELDS_MISSING = {"id": "F1", "severity": "critical", "summary": "unchecked write path"}
DEFERRAL_FIELDS_MISSING = {
    "id": "F2",
    "severity": "critical",
    "status": "deferred",
    "summary": "unbounded retry",
    "ac_ref": None,
    "disposition": "routed",
    "routed_to": "ROW-3",
}


def test_a_legacy_manifest_is_legacy_under_both_rule_families(cli, monkeypatch, capsys, tmp_path):
    assert_legacy_version_is_below_contract(cli)
    for findings in ([AC_FIELDS_MISSING], [DEFERRAL_FIELDS_MISSING]):
        subject = lane(
            cli, tmp_path / str(id(findings)), plugin_version=legacy_plugin_version(cli)
        )
        rc = finalize(
            cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=findings
        )
        assert rc == 0, capsys.readouterr().err


def test_a_strict_manifest_is_strict_under_both_rule_families(cli, monkeypatch, capsys, tmp_path):
    for index, findings in enumerate(([AC_FIELDS_MISSING], [DEFERRAL_FIELDS_MISSING])):
        subject = lane(cli, tmp_path / f"strict-{index}", plugin_version=None)
        rc = finalize(
            cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=findings
        )
        assert rc == 1, f"{findings} must be refused under a strict manifest"
        capsys.readouterr()


def test_one_boolean_decides_both(cli):
    """Structural pin, and the reason it is worth having: the mixed state DECISION 2 forbids is
    reachable only by introducing a SECOND tolerance computation. There is one function, and both
    rule families are inside the branch it guards.
    """
    import inspect

    assert "CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION" in inspect.getsource(
        cli.classified_findings_contract_legacy
    )
    contract = inspect.getsource(cli.classified_findings_contract_errors)
    assert contract.count("classified_findings_contract_legacy(") == 1
    assert "critical_origin_deferral_errors" in contract
    assert "classified_finding_ac_errors" in contract


def test_the_contract_constant_is_the_only_gate_on_this_record(cli):
    """No second version constant may gate `classified_findings` content."""
    import inspect

    source = inspect.getsource(cli.implementation_review_manifest_errors)
    classification_block = source.split("if require_classification:", 1)[1]
    assert "classified_findings_contract_legacy" in classification_block
    assert "STAGE1_SWEEP_REQUIREMENT_PLUGIN_VERSION" not in classification_block


# --- the two rule sets cannot contradict ---------------------------------------------------------


def test_no_rule_requires_what_another_forbids(cli):
    """Item 73 forbids (AC-bearing + routed). Item 74 requires nothing of an AC-bearing finding
    beyond the deferral fields, and a fixed AC-bearing deferred Critical satisfies both."""
    finding = {
        "id": "F3",
        "severity": "critical",
        "summary": "AC2 write path",
        "ac_ref": "AC2",
        "disposition": "fixed",
        "status": "deferred",
        "deferral_rationale": "fixed in flight; the deferral records the follow-up hardening",
        "acceptance_criterion": "AC2: writes are bounded",
    }
    assert cli.classified_finding_ac_errors([finding], require_fields=True) == []
    assert cli.classified_finding_open_ac_errors([finding]) == []
    assert cli.critical_origin_deferral_errors([finding]) == []


def test_a_non_object_finding_is_refused_not_crashed(cli, monkeypatch, capsys, tmp_path):
    """Every validator in the contract reads findings as objects.

    Before the contract a non-object entry was simply stored; unguarded it would now reach
    `item.get` and raise, which turns a malformed file into a traceback instead of a refusal.
    """
    subject = lane(cli, tmp_path)
    path = subject.findings_file(["not an object"])
    rc = finalize(cli, monkeypatch, subject, verdict="clean", findings_path=path)
    assert rc == 1
    err = capsys.readouterr().err
    assert "must be an object" in err
    assert "classification_status" not in subject.manifest()


# --- Codex R1 P2 on the record-contract diff: `null` is absent, not the word "None" -------------


@pytest.mark.parametrize("field", ["routed_to", "acceptance_criterion", "deferral_rationale"])
def test_a_json_null_does_not_satisfy_a_required_field(cli, monkeypatch, capsys, tmp_path, field):
    """`str(None).strip()` is the truthy string "None", so a required field could be bypassed by
    writing `null` -- a contract with a hole the exact width of the word."""
    finding = {**COMPOSED_DEFERRED_CRITICAL, field: None}
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=[finding])
    assert rc == 1, f"{field}: null must not satisfy the contract"
    assert field in capsys.readouterr().err


def test_the_helper_treats_only_real_text_as_present(cli):
    assert cli.finding_text_field({"routed_to": None}, "routed_to") == ""
    assert cli.finding_text_field({"routed_to": "  "}, "routed_to") == ""
    assert cli.finding_text_field({"routed_to": 7}, "routed_to") == ""
    assert cli.finding_text_field({}, "routed_to") == ""
    assert cli.finding_text_field({"routed_to": " ROW-1 "}, "routed_to") == "ROW-1"


# --- Codex R3 P2 on the record-contract diff: a count is not evidence ---------------------------


PLACEHOLDERS = [{}, {"id": "F1"}, {"severity": "critical"}, {"summary": "x"}]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_a_placeholder_finding_does_not_satisfy_the_non_empty_rule(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
    placeholder,
):
    """`[{}]` counted as non-empty while every validator downstream skipped the object, so the
    gate that exists to demand evidence was satisfied by a list of placeholders."""
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=[placeholder])
    assert rc == 1, f"{placeholder} must not satisfy the contract"
    err = capsys.readouterr().err
    assert "severity is required" in err or "summary is required" in err


def test_the_floor_is_only_what_the_doc_already_asks_for(cli):
    """Non-vacuity floor in the other direction: an honest minimal record is NOT rejected."""
    minimal = [{"severity": "p3", "summary": "naming nit"}]
    aliases = [{"priority": "p3", "title": "naming nit"}]
    assert cli.classified_finding_substance_errors(minimal) == []
    assert cli.classified_finding_substance_errors(aliases) == []


def test_a_recorded_placeholder_is_refused_at_both_readers(cli, tmp_path):
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(classified_findings=[{"id": "F1"}])
    errors = subject.manifest_errors(cli)
    assert any("severity is required" in error for error in errors), errors
