"""Quality rec #9: detection-baseline readiness gate.

readiness_review was the P5 anti-pattern in code: it printed the CI conclusion and returned 0, so
"ready" never required that detection actually works on what shipped. The #448 default branch had no
protection at all -> required checks were advisory. This gate makes detection a machine go-live
prerequisite: branch protection (required checks + strict), a synthetic canary whose last conclusion on
the DEPLOYED sha is success, and an errorId/alarm content check -- pure functions over the GitHub API
shapes so they are unit-testable.
"""


# --- branch protection ---------------------------------------------------------------------------

def test_absent_protection_flagged(cli):
    issues = cli.branch_protection_issues(None, [])
    assert len(issues) == 1 and "absent" in issues[0]


def test_no_required_status_checks_flagged(cli):
    issues = cli.branch_protection_issues({"required_status_checks": None}, [])
    assert any("no required_status_checks" in i for i in issues)


def test_non_strict_protection_flagged(cli):
    prot = {"required_status_checks": {"strict": False, "contexts": ["ci"]}}
    assert any("strict is false" in i for i in cli.branch_protection_issues(prot, []))


def test_missing_required_check_flagged(cli):
    prot = {"required_status_checks": {"strict": True, "contexts": ["ci"]}}
    issues = cli.branch_protection_issues(prot, ["ci", "live-smoke"])
    assert any("missing required checks: live-smoke" in i for i in issues)


def test_protection_with_checks_array_passes(cli):
    prot = {"required_status_checks": {"strict": True, "checks": [{"context": "ci"}, {"context": "live-smoke"}]}}
    assert cli.branch_protection_issues(prot, ["ci", "live-smoke"]) == []


# --- synthetic canary on the deployed SHA --------------------------------------------------------

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def test_canary_missing_on_sha_flagged(cli):
    runs = [{"name": "canary", "head_sha": "0000000000000000", "conclusion": "success"}]
    assert "no run on the deployed SHA" in cli.canary_conclusion_issue(runs, "canary", SHA)


def test_canary_red_on_sha_flagged(cli):
    runs = [{"name": "canary", "head_sha": SHA, "conclusion": "failure"}]
    assert "not success" in cli.canary_conclusion_issue(runs, "canary", SHA)


def test_canary_green_on_sha_passes(cli):
    runs = [{"name": "canary", "head_sha": SHA, "conclusion": "success"}]
    assert cli.canary_conclusion_issue(runs, "canary", SHA) is None


def test_canary_disabled_when_unnamed(cli):
    assert cli.canary_conclusion_issue([], "", SHA) is None


# --- errorId / alarm content ---------------------------------------------------------------------

def test_alarm_source_missing_flagged(cli):
    assert any("missing" in i for i in cli.readiness_alarm_content_issues({"infra/alarms.tf": None}))


def test_alarm_source_without_wiring_flagged(cli):
    issues = cli.readiness_alarm_content_issues({"infra/alarms.tf": "resource aws_s3_bucket {}"})
    assert any("no errorId/alarm wiring" in i for i in issues)


def test_alarm_source_with_wiring_passes(cli):
    content = "resource aws_cloudwatch_alarm error_rate { metric = errorId }"
    assert cli.readiness_alarm_content_issues({"infra/alarms.tf": content}) == []
