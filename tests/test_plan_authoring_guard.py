"""Shape guard at the `finalize-plan-review` seam (WS2 of the plan-authoring-standard feature).

Drives the real `finalize-plan-review` CLI command (via `run-plan-review` first, to produce a
trusted review log/run-meta) on a temp lane, at each `planning.authoringStandard.enforcement`
level, against both a linear (non-compliant) plan and a plan that meets the plan-authoring
standard's three-part marker contract (workstreams+dependency graph, model-tier tag, embedded
best-judgment/decision-record autonomy contract -- see `tautline_methodology.plan_authoring`).

Reuses the fixture helpers from `test_plan_review_cli.py` (adapter/plan/target scaffolding, the
`_run_cli` subprocess runner) rather than reinventing them, per the plan-authoring-standard WS2
task brief.
"""

import json
from pathlib import Path

import pytest

import test_plan_review_cli as base

PLAN_REL = base.PLAN_REL

# The base `_write_plan` fixture text (Milestone Goal / Non-Goals / ... / Completion Definition)
# contains none of the three plan-authoring-standard markers, so it is already a valid "linear"
# (non-compliant) plan for these tests. The compliant variant appends all three markers.
COMPLIANT_EXTRA = (
    "\n## Workstreams\n"
    "WS1 is a hard predecessor for WS2; WS2 and WS3 are parallel-safe (no shared files); "
    "see the dependency graph above.\n\n"
    "### Task 1  model-tier: standard\n"
    "Use best judgment while executing; record non-obvious calls with `tautline decision-record`.\n"
)


def _write_plan(target: Path, *, compliant: bool) -> Path:
    path = base._write_plan(target, PLAN_REL)
    if compliant:
        path.write_text(path.read_text(encoding="utf-8") + COMPLIANT_EXTRA, encoding="utf-8")
    return path


def _set_planning_enforcement(adapter_path: Path, level: str | None) -> None:
    data = json.loads(adapter_path.read_text(encoding="utf-8"))
    if level is None:
        data.pop("planning", None)
    else:
        data["planning"] = {"authoringStandard": {"enforcement": level}}
    adapter_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _guard_events(target: Path) -> list[dict]:
    path = target / ".ai-runs" / "guard-events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _authoring_events(target: Path) -> list[dict]:
    return [e for e in _guard_events(target) if e.get("check_id") == "plan.authoring_standard"]


def _run_review_and_finalize(
    tmp_path, *, level: str | None, compliant: bool, round_name: str = "R1Single"
):
    home, adapter_root, target, adapter = base._prepare_target(tmp_path)
    _write_plan(target, compliant=compliant)
    _set_planning_enforcement(adapter, level)
    run = base._run_cli(
        "run-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", PLAN_REL.as_posix(),
        "--round", round_name,
        "--model", "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    log_path = base._stdout_path(run.stdout, "plan_review_run_log")
    finalize = base._run_cli(
        "finalize-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", PLAN_REL.as_posix(),
        "--log", str(log_path),
        "--round", round_name,
        "--model", "codex-test",
        "--verdict", "clean",
        "--unresolved-critical-count", "0",
        "--unresolved-p1-count", "0",
        home=home,
        adapter_root=adapter_root,
    )
    return target, finalize


def test_block_level_rejects_linear_plan_and_names_missing_workstream(tmp_path):
    target, finalize = _run_review_and_finalize(tmp_path, level="block", compliant=False)
    assert finalize.returncode == 1
    assert "plan-authoring standard not met" in finalize.stderr
    assert "Workstreams" in finalize.stderr
    assert not base._manifest_path(target).exists()
    events = _authoring_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_advise_level_warns_and_still_writes_manifest(tmp_path):
    target, finalize = _run_review_and_finalize(tmp_path, level="advise", compliant=False)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_authoring_standard_warning:" in finalize.stderr
    assert base._manifest_path(target).exists()
    events = _authoring_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_default_absent_knob_behaves_as_advise(tmp_path):
    target, finalize = _run_review_and_finalize(tmp_path, level=None, compliant=False)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_authoring_standard_warning:" in finalize.stderr
    assert base._manifest_path(target).exists()


def test_observe_level_logs_only_with_no_stderr_warning(tmp_path):
    target, finalize = _run_review_and_finalize(tmp_path, level="observe", compliant=False)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_authoring_standard_warning:" not in finalize.stderr
    assert "plan-authoring standard not met" not in finalize.stderr
    assert base._manifest_path(target).exists()
    events = _authoring_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_off_level_is_silent_with_no_guard_event(tmp_path):
    target, finalize = _run_review_and_finalize(tmp_path, level="off", compliant=False)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_authoring_standard_warning:" not in finalize.stderr
    assert "plan-authoring standard not met" not in finalize.stderr
    assert base._manifest_path(target).exists()
    assert _authoring_events(target) == []


@pytest.mark.parametrize("level", ["off", "observe", "advise", "block"])
def test_compliant_plan_passes_at_every_level(tmp_path, level):
    target, finalize = _run_review_and_finalize(tmp_path, level=level, compliant=True)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_authoring_standard_warning:" not in finalize.stderr
    assert "plan-authoring standard not met" not in finalize.stderr
    assert base._manifest_path(target).exists()
    events = _authoring_events(target)
    if level == "off":
        assert events == []
    else:
        assert len(events) == 1
        assert events[0]["fired"] is False


def test_precheck_enforces_authoring_standard_even_when_manifest_was_finalized_laxly(tmp_path):
    """Codex R1 P1: a noncompliant plan finalized under `off` must not slip through a later
    `block` via plan-finalization-precheck reusing the existing manifest. The precheck seam
    (ExitPlanMode hook / plan-finalization-precheck) must re-evaluate the shape authoritatively."""
    home, adapter_root, target, adapter = base._prepare_target(tmp_path)
    _write_plan(target, compliant=False)
    _set_planning_enforcement(adapter, "off")
    run = base._run_cli(
        "run-plan-review", "--project", str(adapter), "--target", str(target),
        "--plan", PLAN_REL.as_posix(), "--round", "R1Single", "--model", "codex-test",
        home=home, adapter_root=adapter_root,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    log_path = base._stdout_path(run.stdout, "plan_review_run_log")
    finalize = base._run_cli(
        "finalize-plan-review", "--project", str(adapter), "--target", str(target),
        "--plan", PLAN_REL.as_posix(), "--log", str(log_path), "--round", "R1Single",
        "--model", "codex-test", "--verdict", "clean",
        "--unresolved-critical-count", "0", "--unresolved-p1-count", "0",
        home=home, adapter_root=adapter_root,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr  # off finalized it
    assert base._manifest_path(target).exists()

    # Now the adapter tightens to block; the precheck must catch the noncompliant plan.
    _set_planning_enforcement(adapter, "block")
    precheck = base._run_cli(
        "plan-finalization-precheck", "--project", str(adapter), "--target", str(target),
        "--plan", PLAN_REL.as_posix(), home=home, adapter_root=adapter_root,
    )
    assert precheck.returncode == 1
    assert "plan-authoring standard not met" in precheck.stderr
