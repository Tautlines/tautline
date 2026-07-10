"""#11 critical-journey @pending interdiction.

Private Product A ran 476/685 scenarios @pending -- including every customer-critical order scenario -- and the
count GREW while flagged. The static maxPendingScenarios ceiling does not forbid @pending on a
load-bearing journey. A scenario whose feature maps to a declared criticalJourneys entry must never be
@pending (it must have live coverage); methodology-status surfaces and (under --fail-on-drift) blocks it.
"""

PENDING_FEATURE = (
    "@pending\nFeature: Checkout\n\n  Scenario: submit order\n"
    "    Given a cart\n    When I submit\n    Then it works\n"
)
ACTIVE_FEATURE = (
    "Feature: Checkout\n\n  Scenario: submit order\n"
    "    Given a cart\n    When I submit\n    Then it works\n"
)


def _journey_adapter(feature_paths):
    return {
        "behaviorSpecs": {"pendingTags": ["@pending"]},
        "criticalJourneys": [{"name": "checkout", "featurePaths": feature_paths}],
    }


def test_pending_in_critical_journey_blocks(cli, tmp_path):
    (tmp_path / "checkout.feature").write_text(PENDING_FEATURE)
    issues = cli.critical_journey_pending_issues(_journey_adapter(["checkout.feature"]), tmp_path)
    assert any("checkout" in i.lower() and "pending" in i.lower() for i in issues)


def test_active_critical_journey_is_clean(cli, tmp_path):
    (tmp_path / "checkout.feature").write_text(ACTIVE_FEATURE)
    assert cli.critical_journey_pending_issues(_journey_adapter(["checkout.feature"]), tmp_path) == []


def test_no_critical_journeys_is_silent(cli, tmp_path):
    assert cli.critical_journey_pending_issues({}, tmp_path) == []


def test_journey_with_zero_resolvable_features_flagged(cli, tmp_path):
    # P2 fix: a declared journey whose featurePaths resolve to nothing has no live coverage -- the
    # @pending gate would otherwise be vacuously satisfied by zero scenarios.
    issues = cli.critical_journey_pending_issues(_journey_adapter(["features/missing.feature"]), tmp_path)
    assert any("zero feature files" in i for i in issues)
    assert cli.critical_journey_pending_issues(_journey_adapter([]), tmp_path)  # empty featurePaths too


def test_critical_journey_glob_resolution(cli, tmp_path):
    feats = tmp_path / "features"
    feats.mkdir()
    (feats / "a.feature").write_text(PENDING_FEATURE)
    assert cli.critical_journey_pending_issues(_journey_adapter(["features/**"]), tmp_path)


def test_normalize_critical_journeys_rejects_bad(cli):
    import pytest
    for bad in ["x", [1], [{"featurePaths": []}], [{"name": "", "featurePaths": []}], [{"name": "x", "featurePaths": "y"}]]:
        with pytest.raises(SystemExit):
            cli.normalize_critical_journeys({"criticalJourneys": bad})


def test_normalize_critical_journeys_accepts_valid(cli):
    out = cli.normalize_critical_journeys({"criticalJourneys": [{"name": "checkout", "featurePaths": ["a.feature"]}]})
    assert out[0]["name"] == "checkout" and out[0]["featurePaths"] == ["a.feature"]
    assert cli.normalize_critical_journeys({}) == []
