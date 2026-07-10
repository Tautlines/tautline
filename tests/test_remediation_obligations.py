"""Quality rec #3: open-remediation forcing function.

#325 PREDICTED the #448 recurrence seven days early and shipped anyway: the prediction had no forcing
function, and the "fix" PRs merged while the bug recurred. This generalizes the release-update ledger
into a remediation-obligation ledger: an obligation overdue-and-open is drift, and one marked closed
without a CUSTOMER-OUTCOME verify is drift -- a merged PR is not proof a recurrence is fixed. Blocks
under methodology-status --fail-on-drift, so a recurrence-gate cannot be silently deferred.
"""

import json

PAST = "2020-01-01"
FUTURE = "2099-01-01"
TODAY = "2026-06-24"


def test_overdue_open_obligation_flagged(cli):
    obs = [{"id": "RC-448", "status": "open", "due": PAST}]
    issues = cli.remediation_obligation_issues(obs, TODAY)
    assert len(issues) == 1 and "overdue" in issues[0]


def test_future_open_obligation_ok(cli):
    obs = [{"id": "RC-448", "status": "open", "due": FUTURE}]
    assert cli.remediation_obligation_issues(obs, TODAY) == []


def test_closed_without_customer_outcome_verify_flagged(cli):
    obs = [{"id": "RC-448", "status": "closed", "verifiedBy": "PR #512 merged"}]
    issues = cli.remediation_obligation_issues(obs, TODAY)
    assert len(issues) == 1 and "customer-outcome verify" in issues[0]


def test_closed_with_customer_outcome_verify_ok(cli):
    obs = [{"id": "RC-448", "status": "closed", "verifiedBy": "live-smoke round-trip passed post-merge on deploy run 991"}]
    assert cli.remediation_obligation_issues(obs, TODAY) == []


def test_malformed_due_is_not_overdue(cli):
    obs = [{"id": "x", "status": "open", "due": "soon"}]
    assert cli.remediation_obligation_issues(obs, TODAY) == []


def test_load_ledger_list_and_object_forms(cli, tmp_path):
    p1 = tmp_path / "a.json"
    p1.write_text(json.dumps([{"id": "1"}]))
    assert cli.load_remediation_ledger(p1) == [{"id": "1"}]
    p2 = tmp_path / "b.json"
    p2.write_text(json.dumps({"obligations": [{"id": "2"}]}))
    assert cli.load_remediation_ledger(p2) == [{"id": "2"}]
    assert cli.load_remediation_ledger(tmp_path / "missing.json") == []


def test_remediation_issues_no_ledger_is_silent(cli, tmp_path):
    assert cli.remediation_issues({"remediation": {"ledgerPath": "docs/none.json"}}, tmp_path) == []


def test_remediation_issues_reads_ledger(cli, tmp_path):
    led = tmp_path / "obligations.json"
    led.write_text(json.dumps([{"id": "RC-448", "status": "open", "due": PAST}]))
    issues = cli.remediation_issues({"remediation": {"ledgerPath": "obligations.json"}}, tmp_path)
    assert len(issues) == 1 and "RC-448" in issues[0]
