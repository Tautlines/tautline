"""Item 73 WS1: AC-traceability is recorded evidence, and the push gate enforces it.

The defect (RCAs `g36-out-of-ac-review-findings-implemented-in-flight` and
`review-protocol-206-routing-scope-conflict`): the Done gate is AC-scoped and routing was
severity-scoped, so a Critical NOT open against the item's acceptance criteria was neither
blocking nor routable. Measured cost on G36: two review rounds and one reverted module for
building an out-of-scope fix in flight, plus two severity downgrades performed solely to make
routing legal. And the evidence could not record the distinction -- no `ac_ref`, `disposition`
or `routed_to` existed anywhere in the record.

These eight cases are the T1.1 contract from the plan, keyed on the ONE contract constant
`CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION` (packet W1.1, stitch decision S1 -- item 74's
deferral rules gate on the same constant, so a manifest is legacy under both rule families or
strict under both, never mixed).
"""
import json

from _classified_findings_fixtures import (
    BLOCKER_FREE_LOG,
    assert_legacy_version_is_below_contract,
    evidence_check,
    finalize,
    lane,
    legacy_plugin_version,
)


FIXED_CRITICAL = {
    "id": "F1",
    "severity": "critical",
    "status": "fixed",
    "summary": "unchecked write path",
}


def _fields_named(text: str) -> bool:
    return all(field in text for field in ("ac_ref", "disposition", "routed_to"))


# --- 1. the record must carry the traceability -------------------------------------------------


def test_blocker_finding_without_ac_fields_is_refused(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[{"id": "F1", "severity": "critical", "summary": "unchecked write path"}],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "implementation_review_finalize_error:" in err
    assert _fields_named(err), err
    # No dead ends: the refusal hands back a command that runs from where the lane stands.
    assert "finalize-implementation-review" in err
    # A refusal mutates nothing -- neither the manifest nor the tracked ledger.
    assert "classification_status" not in subject.manifest()
    assert not subject.ledger_path(cli).exists()


def test_ac_bearing_finding_is_never_routable(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[
            {
                "id": "F1",
                "severity": "critical",
                "summary": "AC2 acceptance path rejects valid input",
                "ac_ref": "AC2",
                "disposition": "routed",
                "routed_to": "ROW-1",
            }
        ],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "AC2" in err
    assert "may not be routed" in err
    assert "fixed or refuted" in err


def test_routed_without_routed_to_is_refused(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[
            {
                "id": "F1",
                "severity": "important",
                "summary": "adds a cache layer the milestone plan never named",
                "ac_ref": None,
                "disposition": "routed",
            }
        ],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "routed_to" in err


# --- 2. honest routing is the cheap path, and severity is never downgraded to reach it ---------


def test_out_of_ac_important_routes_at_honest_severity(cli, monkeypatch, capsys, tmp_path):
    """The whole point of the item: an out-of-AC blocker ships without a downgrade.

    The fixture log carries no blocker line -- WS2 wires a log cross-check into this same
    push-eligible path, and a blocker-mentioning fixture would start refusing under it.
    """
    subject = lane(cli, tmp_path, log_text=BLOCKER_FREE_LOG)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[
            {
                "id": "F1",
                "severity": "important",
                "summary": "adds a retry mechanism not named in the milestone plan",
                "ac_ref": None,
                "disposition": "routed",
                "routed_to": "ROW-1",
            }
        ],
    )
    assert rc == 0, capsys.readouterr().err
    recorded = subject.manifest()
    assert recorded["classification_status"] == "clean-with-deferrals"
    # Honest severity: the recorded string is what the reviewer said, not what routing needed.
    assert recorded["classified_findings"][0]["severity"] == "important"
    assert subject.ledger_path(cli).exists()


def test_a_routed_finding_forces_clean_with_deferrals(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[
            {
                "id": "F1",
                "severity": "important",
                "summary": "adds a retry mechanism not named in the milestone plan",
                "ac_ref": None,
                "disposition": "routed",
                "routed_to": "ROW-1",
            }
        ],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "clean-with-deferrals" in err
    assert "classification_status" not in subject.manifest()


def test_blocked_never_requires_the_new_fields(cli, monkeypatch, capsys, tmp_path):
    """Honest reporting stays the cheapest verdict to record -- the same direction of pressure
    the test-evidence gate above it already chose."""
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="blocked",
        findings=[{"id": "F1", "severity": "critical", "summary": "unchecked write path"}],
        critical=1,
    )
    captured = capsys.readouterr()
    # `blocked` exits 1 because the review IS blocked -- but it RECORDS, which is the point: the
    # contract never refuses the honest verdict, so it is never the reason a lane avoids it.
    assert rc == 1
    assert "implementation_review_finalize_error:" not in captured.err, captured.err
    assert "implementation_review_result: blocked" in captured.out
    recorded = subject.manifest()
    assert recorded["classification_status"] == "blocked"
    assert recorded["classified_findings"][0]["severity"] == "critical"


# --- 3. migration tolerance ---------------------------------------------------------------------


def test_legacy_plugin_version_manifest_refinalizes_without_the_fields(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[FIXED_CRITICAL],
    )
    assert rc == 0, capsys.readouterr().err
    assert subject.manifest()["classification_status"] == "clean"


def test_absent_plugin_version_stays_strict(cli, monkeypatch, capsys, tmp_path):
    """A forged or hand-built manifest cannot dodge the contract by omitting the field."""
    subject = lane(cli, tmp_path, plugin_version=None)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[FIXED_CRITICAL],
    )
    assert rc == 1
    assert _fields_named(capsys.readouterr().err)


def test_current_plugin_version_is_strict(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[FIXED_CRITICAL],
    )
    assert rc == 1
    assert _fields_named(capsys.readouterr().err)


# --- 4. the belt to finalize's suspenders -------------------------------------------------------


def _finalize_then_hand_edit(cli, monkeypatch, tmp_path, findings):
    """Finalize cleanly, then hand-edit the recorded findings.

    This is the exact threat `review-evidence-check` exists for: the manifest is a file, and a
    lane that edits it after finalize has bypassed every check the finalizer made.
    """
    subject = lane(cli, tmp_path, plugin_version=None)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[
            {
                "id": "F0",
                "severity": "important",
                "summary": "resolved in flight",
                "ac_ref": "AC1",
                "disposition": "fixed",
            }
        ],
    )
    assert rc == 0, "the fixture must finalize before it is tampered with"
    _rewrite_recorded_findings(cli, subject, findings)
    return subject


def _rewrite_recorded_findings(cli, subject, findings):
    """Edit BOTH recorded copies -- the manifest and the tracked ledger it was written from.

    Editing only the manifest would trip the ledger-drift check instead of the rule each test
    names, and it is also the weaker threat: a lane that edits its evidence edits what it can see.
    """
    manifest = subject.manifest()
    manifest["classified_findings"] = findings
    subject.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    ledger_path = subject.ledger_path(cli)
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["classified_findings"] = findings
        ledger_path.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


OPEN_AC_FINDING = {
    "id": "F1",
    "severity": "important",
    "summary": "AC3 path still rejects valid input",
    "ac_ref": "AC3",
    "disposition": "routed",
    "routed_to": "ROW-9",
}


def test_strict_evidence_check_refuses_an_open_ac_finding(cli, monkeypatch, capsys, tmp_path):
    subject = _finalize_then_hand_edit(cli, monkeypatch, tmp_path, [OPEN_AC_FINDING])
    capsys.readouterr()
    rc = evidence_check(cli, monkeypatch, subject, strict=True)
    assert rc == 1
    err = capsys.readouterr().err
    assert "review_evidence_issue:" in err
    assert "AC3" in err
    assert "review_evidence_next_action:" in err
    assert "finalize-implementation-review" in err


def test_non_strict_evidence_check_warns_and_passes(cli, monkeypatch, capsys, tmp_path):
    subject = _finalize_then_hand_edit(cli, monkeypatch, tmp_path, [OPEN_AC_FINDING])
    capsys.readouterr()
    rc = evidence_check(cli, monkeypatch, subject, strict=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert "review_evidence_warn:" in captured.err
    assert "AC3" in captured.err


def test_evidence_check_passes_a_resolved_ac_finding(cli, monkeypatch, capsys, tmp_path):
    subject = _finalize_then_hand_edit(
        cli,
        monkeypatch,
        tmp_path,
        [
            {
                "id": "F1",
                "severity": "important",
                "summary": "fixed",
                "ac_ref": "AC3",
                "disposition": "fixed",
            }
        ],
    )
    capsys.readouterr()
    rc = evidence_check(cli, monkeypatch, subject, strict=True)
    assert rc == 0, capsys.readouterr().err


def test_evidence_check_tolerates_a_legacy_manifest(cli, monkeypatch, capsys, tmp_path):
    """Tolerance is keyed on the manifest's OWN recorded plugin_version, same as finalize."""
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    assert finalize(cli, monkeypatch, subject, verdict="clean", findings=[]) == 0
    _rewrite_recorded_findings(cli, subject, [OPEN_AC_FINDING])
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 0


# --- 5. one contract constant, per DECISION 2 ---------------------------------------------------


def test_exactly_one_classified_findings_contract_constant(cli):
    """DECISION 2: two independently-versioned extensions of one record is a defect in waiting.

    The two per-plan names (item 73's and item 74's) must not exist anywhere in the tree.
    """
    assert isinstance(cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION, str)
    assert not hasattr(cli, "AC_TRACEABILITY_REQUIREMENT_PLUGIN_VERSION")
    assert not hasattr(cli, "CRITICAL_DEFERRAL_REQUIREMENT_PLUGIN_VERSION")


def test_the_two_per_plan_constant_names_appear_nowhere_in_the_tree():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    forbidden = (
        "AC_TRACEABILITY_REQUIREMENT_PLUGIN_VERSION",
        "CRITICAL_DEFERRAL_REQUIREMENT_PLUGIN_VERSION",
    )
    offenders = []
    for path in (*repo_root.glob("src/**/*.py"), *repo_root.glob("tests/**/*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in forbidden:
            if name in text:
                offenders.append(f"{path}: {name}")
    assert not offenders, offenders


# --- Codex R1 P2: the strict gate makes the same demand the producer made -----------------------


def test_strict_gate_refuses_a_manifest_stripped_of_its_ac_fields(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    """A blocker finding edited after finalize to drop `ac_ref`/`disposition` used to pass, because
    only the producer demanded them."""
    subject = _finalize_then_hand_edit(
        cli,
        monkeypatch,
        tmp_path,
        [{"id": "F1", "severity": "critical", "summary": "unchecked write path"}],
    )
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 1
    err = capsys.readouterr().err
    assert "ac_ref" in err
    assert "review_evidence_next_action:" in err


def test_strict_gate_refuses_a_routed_finding_relabelled_to_clean(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    subject = _finalize_then_hand_edit(
        cli,
        monkeypatch,
        tmp_path,
        [
            {
                "id": "F1",
                "severity": "important",
                "summary": "out of scope for this item",
                "ac_ref": None,
                "disposition": "routed",
                "routed_to": "ROW-4",
            }
        ],
    )
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 1
    assert "may not be recorded as clean" in capsys.readouterr().err


def test_the_strict_gate_shares_the_one_tolerance(cli, monkeypatch, capsys, tmp_path):
    """A legacy manifest is legacy at the gate too -- a mid-flight lane is never stranded."""
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    assert finalize(cli, monkeypatch, subject, verdict="clean", findings=[]) == 0
    _rewrite_recorded_findings(
        cli, subject, [{"id": "F1", "severity": "critical", "summary": "unchecked"}]
    )
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 0


def test_strict_gate_refuses_a_tampered_tracked_ledger(cli, monkeypatch, capsys, tmp_path):
    """Codex R2 P2. The manifest lives under gitignored `.ai-runs/`; the LEDGER is the tracked
    artifact committed to the PR. Pinning the manifest and never comparing what the ledger copied
    let the record under review and the record that shipped say different things.
    """
    subject = lane(cli, tmp_path, plugin_version=None)
    assert finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[
            {
                "id": "F0",
                "severity": "important",
                "summary": "resolved in flight",
                "ac_ref": "AC1",
                "disposition": "fixed",
            }
        ],
    ) == 0
    ledger_path = subject.ledger_path(cli)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["classified_findings"] = [{"id": "F0", "severity": "important", "summary": "resolved"}]
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 1
    err = capsys.readouterr().err
    assert "tracked ledger classified_findings does not match" in err


def test_an_untampered_ledger_passes(cli, monkeypatch, capsys, tmp_path):
    """Non-vacuity floor for the check above: the same fixture, unedited, must pass."""
    subject = lane(cli, tmp_path, plugin_version=None)
    assert finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean",
        findings=[
            {
                "id": "F0",
                "severity": "important",
                "summary": "resolved in flight",
                "ac_ref": "AC1",
                "disposition": "fixed",
            }
        ],
    ) == 0
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 0, capsys.readouterr().err


def test_strict_gate_refuses_a_non_object_recorded_finding(cli, monkeypatch, capsys, tmp_path):
    """Codex R4 P2. Filtering non-objects away made `[1]` a NON-EMPTY findings list that every
    rule then read as empty -- the non-empty gate satisfied by evidence carrying no findings.
    """
    subject = _finalize_then_hand_edit(cli, monkeypatch, tmp_path, [1])
    capsys.readouterr()
    assert evidence_check(cli, monkeypatch, subject, strict=True) == 1
    assert "must be objects" in capsys.readouterr().err
