"""Item 48 / WS1: implementation review gets the ladder plan review already has.

The defect these pin (backlog item 43 diagnosed one symptom of it): `codex_run` carried TWO
independent round refusals, and the budget one returned before the other could be reached.

    cli.py ~37958   round_number > budget            -> return 1, flags never read
    cli.py ~37973   clean_rounds >= 2                -> the ONLY gate --allow-extra-rounds guarded

`--allow-extra-rounds` was built for the second gate -- its own --help says "Permit another Codex
round after two finalized clean rounds" -- but `methodology/policy/17-review-before-push.md` and the
0.17.5 migration text told lanes to use it for the owed confirming round on the FIRST. Policy
assigned the flag a meaning it never had, so the budget refusal was unconditional and its message
said "escalate": an agent stopped and asked the operator, at night, when taking the round was the
only valid option.

Nothing in the suite referenced the budget refusal before this file. That is why it survived
fourteen releases.
"""
import pytest


def _errors(cli, **kwargs):
    """Call the ladder with explicit defaults, so each test states only what it varies."""
    params = {
        "round_number": 1,
        "budget": 2,
        "risk_tier": "T2",
        "review_round_label": "R1",
        "allow_extra_rounds": False,
        "extra_round_reason": "",
        "is_confirming_round": False,
    }
    params.update(kwargs)
    return cli.implementation_review_round_cap_errors(**params)


# --- the reported defect ---------------------------------------------------------------------

def test_first_round_past_budget_proceeds_when_self_authorized(cli):
    """THE regression test. Before this, the flags were never read on the budget path."""
    assert _errors(
        cli,
        round_number=3,
        budget=2,
        allow_extra_rounds=True,
        extra_round_reason="P2 remediation voided R1/R2 evidence; confirming round owed",
    ) == []


def test_round_past_budget_without_authorization_refuses_with_a_continuation(cli):
    errors = _errors(cli, round_number=3, budget=2)
    assert errors, "a round past budget with no recorded reason must refuse"
    joined = " ".join(errors)
    # The refusal must hand the lane the exact invocation that works from where it stands.
    assert "--allow-extra-rounds" in joined
    assert "--extra-round-reason" in joined
    assert "codex-run" in joined


def test_no_refusal_on_this_surface_tells_an_agent_to_consult_a_human(cli):
    """The old message said "split/defer/escalate".

    "escalate" is the word that cost 30 hours of lane time.
    """
    surfaces = [
        _errors(cli, round_number=3, budget=2),
        _errors(cli, round_number=5, budget=2),
        _errors(cli, round_number=None, budget=2),
        _errors(cli, round_number=1, budget=None),
    ]
    # Phrases that hand the decision to a human. "operator" alone is NOT forbidden: the refusals
    # deliberately say "never require operator authorization", which is the opposite instruction.
    forbidden = ("escalate", "ask the operator", "consult the operator", "ask the human")
    for errors in surfaces:
        joined = " ".join(errors).lower()
        for phrase in forbidden:
            assert phrase not in joined, f"{phrase!r} in: {joined}"


# --- the ladder shape (mirrors plan_review_round_cap_errors) --------------------------------

def test_rounds_within_budget_need_no_authorization(cli):
    for round_number in (1, 2):
        assert _errors(cli, round_number=round_number, budget=2) == []


def test_hard_cap_is_budget_plus_two(cli):
    # budget 2 -> rounds 3 and 4 self-authorize, round 5 is past the absolute ceiling.
    reason = "genuinely new defect class found in the remediated diff"
    kwargs = {"budget": 2, "allow_extra_rounds": True, "extra_round_reason": reason}
    assert _errors(cli, round_number=4, **kwargs) == []
    assert _errors(cli, round_number=5, **kwargs)


def test_past_the_hard_cap_refusal_is_unconditional_and_says_so(cli):
    errors = _errors(
        cli,
        round_number=5,
        budget=2,
        allow_extra_rounds=True,
        extra_round_reason="a genuinely new defect class nobody has reviewed yet",
    )
    assert errors
    joined = " ".join(errors)
    assert "hard cap" in joined
    # Worded like plan_review_hard_cap_refusal: nothing raises it, so no lane hunts for a flag.
    assert "absolute" in joined
    assert "no exception note" in joined or "no flag" in joined


def test_a_rubber_stamp_reason_is_not_an_authorization(cli):
    errors = _errors(
        cli, round_number=3, budget=2, allow_extra_rounds=True, extra_round_reason="wip"
    )
    assert errors, "a placeholder reason must not buy a round"
    assert "at least" in " ".join(errors)


def test_the_flag_alone_without_a_reason_is_not_an_authorization(cli):
    errors = _errors(cli, round_number=3, budget=2, allow_extra_rounds=True, extra_round_reason="")
    assert errors
    assert "--extra-round-reason" in " ".join(errors)


def test_a_reason_without_the_flag_is_not_an_authorization(cli):
    """Symmetry with the existing clean-rounds gate: the flag is the deliberate act."""
    errors = _errors(
        cli,
        round_number=3,
        budget=2,
        allow_extra_rounds=False,
        extra_round_reason="P2 remediation voided the prior rounds' evidence",
    )
    assert errors
    assert "--allow-extra-rounds" in " ".join(errors)


# --- input validation, carried over from the old refusals ------------------------------------

def test_missing_round_number_is_named_not_tracebacked(cli):
    errors = _errors(cli, round_number=None)
    assert errors
    assert "R1" in " ".join(errors)


def test_missing_budget_for_the_tier_is_named(cli):
    errors = _errors(cli, round_number=1, budget=None, risk_tier="T2")
    assert errors
    assert "T2" in " ".join(errors)


@pytest.mark.parametrize("round_number", [0, -1])
def test_nonpositive_round_numbers_refuse(cli, round_number):
    assert _errors(cli, round_number=round_number)


# --- the tier shape ---------------------------------------------------------------------------

def test_t3_gets_more_rounds_than_t2(cli):
    """{T0:0, T1:1, T2:2, T3:2} gave the HIGHEST risk tier no more rounds than T2, and T1=1 made
    the confirming round policy mandates illegal on the first finding."""
    budgets = cli.DEFAULT_REVIEW["roundBudgets"]
    assert budgets["T0"] == 0, "T0 does not use cross-model implementation review"
    assert budgets["T1"] >= 2, "T1 must fit a finding plus its confirming round"
    assert budgets["T3"] > budgets["T2"], "the highest risk tier must not be capped at T2's ceiling"


# --- WS2: a confirming round on an already-remediated diff is free ---------------------------

def test_a_confirming_round_past_budget_is_not_charged(cli):
    """Re-binding a verdict to a changed hash is not a new round of inquiry.

    The remediation loop: R1 finds P2s -> fix -> hash changes -> R1 evidence void. R2 finds P2s ->
    fix -> hash changes -> R2 evidence void. R3 is owed, and charging it is what made "any PR where
    review is doing its job" unpushable.
    """
    assert _errors(cli, round_number=3, budget=2, is_confirming_round=True) == []


def test_a_confirming_round_cannot_carry_a_lane_past_the_hard_cap(cli):
    """Confirmations are free, not infinite."""
    assert _errors(cli, round_number=5, budget=2, is_confirming_round=True)


# --- Codex R1 P2: the ladder's self-authorization must actually be recorded -------------------
#
# The refusal tells the lane the round is "self-authorized only with a RECORDED reason". Nothing
# recorded it. `--extra-round-reason` reached the validator, the validator returned [], and the run
# proceeded silently -- the only `codex_run_extra_round_reason:` emission belonged to the
# clean-rounds gate, which a lane admitted by the ladder never reaches. A control that promises an
# audit trail and writes none is worse than no control, and the silence is the same class of defect
# as the one this whole item exists to remove.

def test_self_authorization_is_recognized_only_past_the_budget(cli):
    assert cli.implementation_review_round_self_authorized(3, 2) is True
    assert cli.implementation_review_round_self_authorized(2, 2) is False
    assert cli.implementation_review_round_self_authorized(1, 2) is False


def test_a_confirming_round_is_not_reported_as_self_authorized(cli):
    """A confirmation is admitted by the exemption, needs no reason, and prints its own line.
    Reporting it as self-authorized would demand an audit record for a round that owes none."""
    assert (
        cli.implementation_review_round_self_authorized(3, 2, is_confirming_round=True) is False
    )


@pytest.mark.parametrize(("round_number", "budget"), [(None, 2), (3, None)])
def test_unknown_round_or_budget_is_not_self_authorized(cli, round_number, budget):
    """Fails closed: an unknown state must not be reported as an authorized round. The ladder
    refuses these inputs anyway, so this can only ever be reached as a bug."""
    assert cli.implementation_review_round_self_authorized(round_number, budget) is False


def test_the_predicate_agrees_with_the_ladder_it_reports_on(cli):
    """The audit line and the admission decision must not drift apart -- the copy that drifts is
    the one deciding whether the reason gets recorded. For every round from 1 to the hard cap:
    if the ladder admits it with the flags and the predicate says self-authorized, then the ladder
    must ALSO refuse it without the flags. Otherwise a round would be logged as authorized while
    needing no authorization."""
    budget = 2
    for round_number in range(1, cli.implementation_review_hard_cap(budget) + 1):
        authorized = cli.implementation_review_round_self_authorized(round_number, budget)
        refused_without_flags = bool(_errors(cli, round_number=round_number, budget=budget))
        assert authorized == refused_without_flags, (
            f"round {round_number} of budget {budget}: predicate says "
            f"self_authorized={authorized} but the ladder "
            f"{'refuses' if refused_without_flags else 'admits'} it without the flags"
        )


# --- the T1-cannot-certify-its-own-fix scenario ----------------------------------------------
#
# Raised from a live lane on 2026-07-31, as a structural observation rather than a bug report:
#
#   "Fixing a review finding changes diff_sha256, which invalidates the round that found it. So
#    converging on n findings needs n+1 rounds -- but T1's budget is 1, meaning T1 can never
#    certify a fix to anything T1 finds. Every T1 change with a single finding forces a T2
#    escalation, which requires a Stage 1 sweep with its own content validation."
#
# That is exactly right, and it is the same defect as the operator-visible one: the budget was
# funding CONFIRMATIONS out of the inquiry budget. Two independent things fix it, and the tests
# below pin both so neither can regress alone:
#
#   1. WS2 -- the confirming round is not charged at all, so the arithmetic stops being n+1 rounds
#      against an n-round budget. This alone fixes the tier even at the OLD budget of 1.
#   2. WS1's reshape -- T1 goes 1 -> 2, which is headroom, not the fix.
#
# The forced-T2-escalation chain that observation describes is therefore closed at the root: a T1
# change with one finding never needs a tier change to certify its own fix.

def test_t1_can_certify_a_fix_to_its_own_finding_at_the_OLD_budget_of_one(cli):
    """The scenario as reported, run against budget=1 deliberately.

    Pinning it at 1 rather than at the new default proves the confirming-round exemption is what
    rescues the tier. If someone later reverts the budget reshape, this still passes; if someone
    reverts WS2, this fails and names the reason.
    """
    assert _errors(cli, round_number=2, budget=1, risk_tier="T1", is_confirming_round=True) == [], (
        "R1 found something, the fix changed the diff, and R2 re-binds the verdict -- a "
        "confirmation, not new inquiry. Charging it is what forced a T2 escalation to certify a "
        "one-finding T1 change."
    )


def test_the_n_plus_one_shape_converges_without_a_tier_change(cli):
    """n findings need n+1 rounds. Walk a T1 remediation loop and assert every confirming round up
    to the hard cap is admitted -- so convergence never requires a tier change.

    The loop stops AT the cap, because that is where the design says it stops: confirmations are
    free, not infinite (`test_a_confirming_round_cannot_carry_a_lane_past_the_hard_cap`). At the
    old T1 budget of 1 the cap is 3, so a T1 change converges on up to two findings without ever
    leaving the tier. Past that the refusal is deliberate and names its two exits.
    """
    budget = 1
    cap = cli.implementation_review_hard_cap(budget)
    for findings in range(1, cap):
        assert (
            _errors(
                cli,
                round_number=findings + 1,
                budget=budget,
                risk_tier="T1",
                is_confirming_round=True,
            )
            == []
        ), f"the confirming round after {findings} finding(s) was refused"


# --- Codex R3 P2: the recorded reason must reach the DURABLE artifact -------------------------
#
# Printing to stdout is not recording. stdout dies with the terminal; the manifest and the tracked
# ledger are what finalization and any later audit actually read. The ladder's refusal promises a
# recorded reason, so the reason has to survive the process or the promise is decoration.

def test_the_evidence_writer_accepts_and_persists_an_extra_round_reason(cli):
    import inspect

    params = inspect.signature(cli.write_implementation_review_evidence).parameters
    assert "extra_round_reason" in params
    assert "extra_round_authorization" in params
    assert params["extra_round_reason"].default == "", "must stay optional for in-budget rounds"


def test_the_tracked_ledger_carries_the_authorization_fields(cli):
    """The manifest lives under gitignored .ai-runs/; the LEDGER is the tracked artifact. A reason
    that stopped at the manifest would leave nothing reviewable in the repo."""
    source = inspect_ledger_fields(cli)
    assert "extra_round_reason" in source
    assert "extra_round_authorization" in source


def inspect_ledger_fields(cli):
    import inspect

    return inspect.getsource(cli.implementation_review_ledger_payload)


# --- Codex R3 P2 on Release 2 / backlog item 51 ------------------------------------------------
#
# The over-budget retry command was runnable for T1 and DIED for T2/T3: `codex_run` additionally
# requires --native-review-note and --stage1-sweep for those tiers, so a lane pasting the printed
# remedy hit the Stage 1 refusal instead of taking the round. A remedy that fails one gate later is
# still a dead end. Deferred at 0.36.0's hard cap as item 51; closed here.

def _retry(cli, tier):
    import pathlib

    return cli.implementation_review_retry_command(
        {"review": {"codexWrapper": "codex review --base origin/experimental"}},
        pathlib.Path("."),
        tier,
        "R4",
    )


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_the_retry_command_carries_the_stage1_arguments_those_tiers_require(cli, tier):
    command = _retry(cli, tier)

    assert "--native-review-note" in command
    assert "--stage1-sweep" in command
    assert command.index("--stage1-sweep") < command.index(" -- "), (
        "codex-run requires both BEFORE the `--` separator"
    )


def test_t1_is_not_burdened_with_stage1_arguments_it_does_not_need(cli):
    """implementation_stage1_required_for_risk_tier exempts an explicit T1, so demanding a sweep
    there would invent a requirement the verb does not have."""
    command = _retry(cli, "T1")

    assert "--stage1-sweep" not in command
    assert "--allow-extra-rounds" in command


def test_the_retry_command_uses_placeholders_not_the_callers_stale_artifacts(cli):
    """Both Stage 1 artifacts must be re-made against the REMEDIATED diff. Echoing the caller's
    own paths back would invite pasting evidence that describes a tree which no longer exists."""
    command = _retry(cli, "T2")

    assert "<fresh-sweep.json>" in command
    assert ".ai-runs/review-evidence/stage1-sweeps/" not in command
