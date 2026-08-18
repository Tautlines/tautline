"""White-box coverage for the plan_finalization_precheck_errors guard core (LANE-R6). The full
finalize/precheck command is exercised black-box elsewhere; this pins the pure core directly so the
guard-coverage gate has a real reference and a missing plan fails closed.
"""

from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "adapters" / "projects" / "example-saas.json"


def test_precheck_reports_missing_plan(cli, tmp_path):
    data = cli.load_project(EXAMPLE)
    errors, plan_path, manifest = cli.plan_finalization_precheck_errors(
        data, tmp_path, Path("docs/product/backlog/example-saas-v1/specs/nonexistent-plan.md")
    )
    assert any("plan missing" in e for e in errors)
    assert manifest is None


def _plan(tmp_path: Path) -> Path:
    plan_path = tmp_path / "plan-example.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    return plan_path


def _data(cli) -> dict:
    return cli.load_project(EXAMPLE)


def test_goal_prompt_report_default_advise_never_blocks(cli, tmp_path):
    """AC5 / WS4 review gate: `advise` -- the default -- must never refuse. A newly required
    artifact becoming a new stop-and-ask is exactly the regression this pins against."""
    plan_path = _plan(tmp_path)
    std_cfg = {"enforcement": "advise"}
    block_errors, warnings = cli.plan_finalization_goal_prompt_report(
        _data(cli), tmp_path, plan_path, std_cfg
    )
    assert block_errors == []
    assert len(warnings) == 1
    assert "no goal prompt artifact" in warnings[0]


def test_goal_prompt_report_block_refuses(cli, tmp_path):
    plan_path = _plan(tmp_path)
    std_cfg = {"enforcement": "block"}
    block_errors, warnings = cli.plan_finalization_goal_prompt_report(
        _data(cli), tmp_path, plan_path, std_cfg
    )
    assert warnings == []
    assert len(block_errors) == 1
    assert "plan-authoring standard not met" in block_errors[0]


def test_goal_prompt_report_off_is_completely_silent(cli, tmp_path):
    plan_path = _plan(tmp_path)
    std_cfg = {"enforcement": "off"}
    block_errors, warnings = cli.plan_finalization_goal_prompt_report(
        _data(cli), tmp_path, plan_path, std_cfg
    )
    assert block_errors == [] and warnings == []


def test_goal_prompt_report_observe_neither_blocks_nor_warns(cli, tmp_path):
    plan_path = _plan(tmp_path)
    std_cfg = {"enforcement": "observe"}
    block_errors, warnings = cli.plan_finalization_goal_prompt_report(
        _data(cli), tmp_path, plan_path, std_cfg
    )
    assert block_errors == [] and warnings == []


def test_goal_prompt_report_none_reported_once_shipped(cli, tmp_path):
    plan_path = _plan(tmp_path)
    (tmp_path / "goal-ws1-example.txt").write_text(
        "/goal do it, from the finalized plan `plan-example.md`\n", encoding="utf-8"
    )
    data = _data(cli)
    for level in ("off", "observe", "advise", "block"):
        block_errors, warnings = cli.plan_finalization_goal_prompt_report(
            data, tmp_path, plan_path, {"enforcement": level}
        )
        assert block_errors == [] and warnings == [], level


def test_goal_plan_readiness_reflects_missing_goal_prompt_under_block(cli, tmp_path, monkeypatch):
    """Codex R1 P1: `goal_plan_readiness` (what `goal-status` reports) is a THIRD consumer of
    the shared precheck core, alongside the standalone verb and the ExitPlanMode hook. Without
    calling the goal-prompt check here too, a plan missing its goal prompt under `block` could
    be reported `execution-ready` while the standalone precheck verb refuses the same plan."""
    plan_path = _plan(tmp_path)
    data = _data(cli)
    data.setdefault("planning", {})["authoringStandard"] = {"enforcement": "block"}
    # goal_plan_readiness calls plan_finalization_precheck_errors first; stub it to a clean
    # result so only the goal-prompt layer under test can produce the readiness verdict.
    monkeypatch.setattr(
        cli, "plan_finalization_precheck_errors", lambda *a, **k: ([], plan_path, None)
    )
    status, errors = cli.goal_plan_readiness(data, tmp_path, plan_path)
    assert status != "execution-ready"
    assert any("no goal prompt artifact" in e for e in errors)

    (tmp_path / "goal-ws1-example.txt").write_text(
        "/goal from the finalized plan `plan-example.md`\n", encoding="utf-8"
    )
    status2, errors2 = cli.goal_plan_readiness(data, tmp_path, plan_path)
    assert status2 == "execution-ready"
    assert errors2 == []
