"""#4 live-CI-conclusion merge gate: branch_liveness must fail closed on a not-green PR.

RCA (quality rec #4): branch_liveness_check fetched mergeStateStatus but only acted on QUEUED, so an
OPEN PR whose required test check concluded FAILURE passed as "active work" -- nothing consumed the CI
conclusion (FM3). pr_failed_required_check is the pure decision: given a PR's statusCheckRollup and the
adapter's ciTestGate.requiredCheckName, return a reason iff that check CONCLUDED a hard failure.

Opt-in (requiredCheckName unset => never blocks) so it cannot over-block existing lanes, and
provider-agnostic: a GitHub Actions CheckRun (conclusion) AND a Jenkins commit StatusContext (state)
both block, so a Jenkins pipeline that posts a required commit status is enforced too.
"""


def _pr(checks):
    return {"number": 1, "state": "OPEN", "statusCheckRollup": checks}


def test_required_check_name_validated(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_ci_test_gate({"ciTestGate": {"requiredCheckName": ["x"]}})
    assert cli.normalize_ci_test_gate({"ciTestGate": {"requiredCheckName": "ci"}})["requiredCheckName"] == "ci"
