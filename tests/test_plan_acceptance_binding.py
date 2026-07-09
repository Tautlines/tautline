"""Quality rec #13: AC-to-test-id binding at plan finalization.

canonical-rules.md already declares that a plan with a "missing named test/gate" or "missing concrete
testable acceptance criterion" is a stub -- but nothing enforced the per-AC binding. This gate gives
Definition-of-Ready teeth: under planAcceptance.enforcement=block, plan-finalization-precheck fails any
acceptance criterion that names no executable test/scenario id, or that is parked behind @pending
(FM1: untestable AC; FM2: AC excluded from live coverage), so the gap cannot be baked in at story entry.
"""

import pytest

BOUND = """## Acceptance Criteria
- Guest can submit an order -> `test_guest_submit_order` (orders.feature: Scenario: guest checkout)
- Admin sees the new order -> covered by: test_admin_order_visible
"""

UNBOUND = """## Acceptance Criteria
- Guest can submit an order
- Admin sees the new order and gets a confirmation email
"""

PENDING = """## Acceptance Criteria
- Guest can submit an order -> test_guest_submit_order @pending (harness not wired)
"""

CFG_BLOCK = {"enforcement": "block", "acHeadings": ["acceptance criteria"]}


def test_bound_criteria_pass(cli):
    assert cli.plan_acceptance_binding_issues(BOUND, CFG_BLOCK, ["@pending"]) == []


def test_unbound_criterion_flagged(cli):
    issues = cli.plan_acceptance_binding_issues(UNBOUND, CFG_BLOCK, ["@pending"])
    assert len(issues) == 2
    assert all("no executable test/scenario id" in i for i in issues)


def test_pending_bound_criterion_flagged(cli):
    issues = cli.plan_acceptance_binding_issues(PENDING, CFG_BLOCK, ["@pending"])
    assert len(issues) == 1
    assert "inactive" in issues[0]


def test_no_ac_section_is_silent(cli):
    # The presence of an AC section is the substance gate's job; this gate only binds existing ACs.
    assert cli.plan_acceptance_binding_issues("## Goal\nSome plan.\n", CFG_BLOCK, ["@pending"]) == []


def test_prose_ac_section_does_not_bypass(cli):
    # P2 fix: ACs written as prose paragraphs (no list bullets) must not silently pass the gate.
    prose = "## Acceptance Criteria\nThe user must be able to log in successfully.\nPayments clear in 2s.\n"
    issues = cli.plan_acceptance_binding_issues(prose, CFG_BLOCK, ["@pending"])
    assert len(issues) == 1 and "no parseable list criteria" in issues[0]


def test_heading_level_and_casing(cli):
    text = "### acceptance criteria:\n- does a thing\n"
    issues = cli.plan_acceptance_binding_issues(text, CFG_BLOCK, ["@pending"])
    assert len(issues) == 1


def test_feature_file_and_it_block_count_as_binding(cli):
    text = '## Acceptance Criteria\n- login works (login.spec.ts)\n- signup works -> it("creates a user")\n'
    assert cli.plan_acceptance_binding_issues(text, CFG_BLOCK, ["@pending"]) == []


def test_normalize_plan_acceptance(cli):
    with pytest.raises(SystemExit):
        cli.normalize_plan_acceptance({"planAcceptance": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_plan_acceptance({"planAcceptance": {"acHeadings": "ac"}})
    cfg = cli.normalize_plan_acceptance({})
    assert cfg["enforcement"] == "off" and cfg["acHeadings"] == ["acceptance criteria"]
    cfg2 = cli.normalize_plan_acceptance({"planAcceptance": {"enforcement": "block", "acHeadings": ["AC", "Acceptance"]}})
    assert cfg2["acHeadings"] == ["ac", "acceptance"]


def test_off_default_does_not_block_precheck(cli, tmp_path):
    # With the default (off), the binding gate contributes no errors even on an unbound AC plan.
    data = {"planningArtifacts": {"sourceOfTruth": "."}, "behaviorSpecs": {}, "planAcceptance": {"enforcement": "off"}}
    plan = tmp_path / "plan.md"
    plan.write_text(UNBOUND)
    errors, _, _ = cli.plan_finalization_precheck_errors(data, tmp_path, plan)
    assert not any("executable test/scenario id" in e for e in errors)


def test_block_mode_wires_into_precheck(cli, tmp_path):
    data = {"planningArtifacts": {"sourceOfTruth": "."}, "behaviorSpecs": {}, "planAcceptance": CFG_BLOCK}
    plan = tmp_path / "plan.md"
    plan.write_text(UNBOUND)
    errors, _, _ = cli.plan_finalization_precheck_errors(data, tmp_path, plan)
    assert any("executable test/scenario id" in e for e in errors)
