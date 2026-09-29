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
    finalize,
    lane,
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


# --- 2. honest routing is the cheap path, and severity is never downgraded to reach it ---------


# --- 3. migration tolerance ---------------------------------------------------------------------


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


# --- 5. one contract constant, per DECISION 2 ---------------------------------------------------


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
