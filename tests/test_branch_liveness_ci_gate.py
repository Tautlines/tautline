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


def test_opt_in_without_required_check_never_blocks(cli):
    checks = [{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}]
    assert cli.pr_failed_required_check(_pr(checks), "") is None


def test_blocks_on_failed_checkrun(cli):
    checks = [{"__typename": "CheckRun", "name": "ci-tests", "status": "COMPLETED", "conclusion": "FAILURE"}]
    assert cli.pr_failed_required_check(_pr(checks), "ci-tests")


def test_blocks_on_failed_jenkins_status_context(cli):
    # Jenkins posts a commit StatusContext with state=FAILURE -- provider-agnostic, must block too.
    checks = [{"__typename": "StatusContext", "context": "jenkins/pr", "state": "FAILURE"}]
    assert cli.pr_failed_required_check(_pr(checks), "jenkins/pr")


def test_allows_success_pending_neutral_skipped(cli):
    cases = [
        ({"__typename": "CheckRun", "name": "ci-tests", "status": "COMPLETED", "conclusion": "SUCCESS"}, "ci-tests"),
        ({"__typename": "CheckRun", "name": "ci-tests", "status": "IN_PROGRESS", "conclusion": None}, "ci-tests"),
        ({"__typename": "CheckRun", "name": "ci-tests", "status": "COMPLETED", "conclusion": "NEUTRAL"}, "ci-tests"),
        ({"__typename": "CheckRun", "name": "ci-tests", "status": "COMPLETED", "conclusion": "SKIPPED"}, "ci-tests"),
        ({"__typename": "StatusContext", "context": "jenkins/pr", "state": "PENDING"}, "jenkins/pr"),
    ]
    for check, want in cases:
        assert cli.pr_failed_required_check(_pr([check]), want) is None, check


def test_only_the_named_check_counts(cli):
    checks = [
        {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"},
        {"__typename": "CheckRun", "name": "ci-tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
    ]
    assert cli.pr_failed_required_check(_pr(checks), "ci-tests") is None


def test_missing_rollup_is_not_a_failure(cli):
    assert cli.pr_failed_required_check({"number": 1}, "ci-tests") is None


def test_required_check_name_validated(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_ci_test_gate({"ciTestGate": {"requiredCheckName": ["x"]}})
    assert cli.normalize_ci_test_gate({"ciTestGate": {"requiredCheckName": "ci"}})["requiredCheckName"] == "ci"
