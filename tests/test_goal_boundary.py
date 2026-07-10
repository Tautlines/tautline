"""RCA O12: a goal-completion claim is unsupported until goal-advance moves the ledger."""


def _cfg(enabled=True, granularities=("goal",)):
    return {"enabled": enabled, "granularities": list(granularities)}


def _run(cli, status):
    return {"schema": cli.GOAL_RUN_SCHEMA, "status": status}


def test_completion_claim_without_complete_ledger_is_flagged(cli):
    err = cli.goal_boundary_claim_error(_cfg(), _run(cli, "active"), "The goal is complete and delivered.")
    assert err and "goal-completion claim without goal-advance" in err


def test_completion_claim_with_complete_ledger_passes(cli):
    assert cli.goal_boundary_claim_error(_cfg(), _run(cli, "complete"), "Goal complete; shipped.") is None


def test_no_completion_claim_passes(cli):
    assert cli.goal_boundary_claim_error(_cfg(), _run(cli, "active"), "Finished milestone 2; continuing.") is None


def test_completion_claim_phrasing_variants_are_caught(cli):
    # Codex review P2: substring list missed "the goal is done" / "the goal has shipped".
    for claim in (
        "The goal is done.",
        "the goal has shipped",
        "We delivered the goal today.",
        "The goal is now complete and closed.",
    ):
        assert cli.goal_boundary_claim_error(_cfg(), _run(cli, "active"), claim), claim


def test_iteration_review_not_covering_goal_passes(cli):
    err = cli.goal_boundary_claim_error(
        _cfg(granularities=("milestone",)), _run(cli, "active"), "The goal is complete."
    )
    assert err is None


def test_disabled_iteration_review_passes(cli):
    assert cli.goal_boundary_claim_error(_cfg(enabled=False), _run(cli, "active"), "Goal delivered.") is None


def test_missing_or_invalid_ledger_does_not_flag(cli):
    assert cli.goal_boundary_claim_error(_cfg(), None, "Goal complete.") is None
    assert cli.goal_boundary_claim_error(_cfg(), {"schema": "other"}, "Goal complete.") is None
