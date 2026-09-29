"""D4 (0.6.113): backlogProvider.featureSeries config plumbing.

featureSeries is a DICT {field, pattern} naming the board field that holds a feature number and an
optional regex/prefix constraining valid numbers. It must validate as a dict in its own type-check
block (mirroring ciTestGate), NOT be str-coerced by the optional-key loop, default to {}, and flow
through goal_tracker_from_backlog_provider for provider-enabled adapters.
"""

import pytest

LABEL = "backlogProvider"


def _normalize(cli, overrides):
    raw = {"enabled": False, "provider": "github-projects", **overrides}
    return cli.normalize_tracker_adapter_config(raw, cli.DEFAULT_BACKLOG_PROVIDER, LABEL)


def test_default_backlog_provider_featureSeries_empty(cli):
    assert cli.DEFAULT_BACKLOG_PROVIDER.get("featureSeries") == {}
    # An adapter that does not set featureSeries still validates and gets {}.
    config = _normalize(cli, {})
    assert config["featureSeries"] == {}


def test_normalize_featureSeries_typecheck(cli):
    # Valid dict round-trips with its string members intact (NOT str-coerced).
    config = _normalize(cli, {"featureSeries": {"field": "Feature", "pattern": "F-\\d+"}})
    assert config["featureSeries"] == {"field": "Feature", "pattern": "F-\\d+"}
    assert isinstance(config["featureSeries"], dict)
    # Non-dict featureSeries is rejected, not stringified.
    with pytest.raises(SystemExit):
        _normalize(cli, {"featureSeries": "Feature"})
    with pytest.raises(SystemExit):
        _normalize(cli, {"featureSeries": ["Feature"]})
    # Non-string members are rejected.
    with pytest.raises(SystemExit):
        _normalize(cli, {"featureSeries": {"field": 5}})
    with pytest.raises(SystemExit):
        _normalize(cli, {"featureSeries": {"pattern": ["x"]}})


def test_featureSeries_mirrored_into_goal_tracker(cli):
    provider = _normalize(
        cli,
        {
            "enabled": True,
            "owner": "acme",
            "projectNumber": 3,
            "featureSeries": {"field": "Feature", "pattern": "F-\\d+"},
        },
    )
    tracker = cli.goal_tracker_from_backlog_provider(provider)
    assert tracker["featureSeries"] == {"field": "Feature", "pattern": "F-\\d+"}


def test_backlog_provider_completion_unit_validates_and_mirrors(cli):
    provider = _normalize(cli, {"completionUnit": "provider-item"})
    assert provider["completionUnit"] == "provider-item"
    tracker = cli.goal_tracker_from_backlog_provider(provider)
    assert tracker["completionUnit"] == "provider-item"

    with pytest.raises(SystemExit):
        _normalize(cli, {"completionUnit": "issue"})
