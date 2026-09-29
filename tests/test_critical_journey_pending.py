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


def test_normalize_critical_journeys_rejects_bad(cli):
    import pytest
    for bad in ["x", [1], [{"featurePaths": []}], [{"name": "", "featurePaths": []}], [{"name": "x", "featurePaths": "y"}]]:
        with pytest.raises(SystemExit):
            cli.normalize_critical_journeys({"criticalJourneys": bad})


def test_normalize_critical_journeys_accepts_valid(cli):
    out = cli.normalize_critical_journeys({"criticalJourneys": [{"name": "checkout", "featurePaths": ["a.feature"]}]})
    assert out[0]["name"] == "checkout" and out[0]["featurePaths"] == ["a.feature"]
    assert cli.normalize_critical_journeys({}) == []
