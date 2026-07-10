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
