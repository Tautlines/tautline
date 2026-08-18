"""Black-box coverage for the goal-prompt-required check (WS4, item 107: "a build-ready plan
ships its goal prompt").

This is the trigger half of the goal-assignment feature: `tautline goal-assignment` already
composes a valid goal prompt (WS1-WS3), but nothing required a build-ready plan to actually
ship one until this check. It is wired at `plan-finalization-precheck` -- the seam that decides
a plan is build-ready -- under the same `planning.authoringStandard.enforcement` knob the rest
of the plan-authoring standard already uses (off|observe|advise|block, default advise).

Deliberately NOT wired into `finalize-plan-review` or into the shared
`plan_finalization_precheck_errors` core: `goal-assignment` itself calls that shared function to
gate its own composition, and a goal cannot be required to exist before the tool that creates it
is allowed to run. See `plan_finalization_goal_prompt_report` in cli.py.

Reuses `test_plan_authoring_guard`'s COMPLIANT plan writer so these tests isolate the goal-prompt
artifact question from the (separately covered) plan-authoring shape question -- every plan here
already satisfies workstreams/model-tier/decision-record, so `block` enforcement never refuses
for the shape reason, only ever for the goal-prompt reason under test.
"""

import json
from pathlib import Path

import test_plan_authoring_guard as shape
import test_plan_review_cli as base

PLAN_REL = base.PLAN_REL


def _guard_events(target: Path) -> list[dict]:
    path = target / ".ai-runs" / "guard-events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _goal_prompt_events(target: Path) -> list[dict]:
    return [e for e in _guard_events(target) if e.get("check_id") == "plan.goal_prompt"]


def _finalize_compliant_plan(tmp_path, *, level: str | None):
    home, adapter_root, target, adapter = base._prepare_target(tmp_path)
    shape._write_plan(target, compliant=True)
    shape._set_planning_enforcement(adapter, level)
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
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    return home, adapter_root, target, adapter


def _precheck(home, adapter_root, target, adapter):
    return base._run_cli(
        "plan-finalization-precheck", "--project", str(adapter), "--target", str(target),
        "--plan", PLAN_REL.as_posix(), home=home, adapter_root=adapter_root,
    )


def _ship_goal_prompt(target: Path) -> None:
    # Must name the plan's FULL reference (target-relative path), not just its bare filename --
    # the real production caller always supplies a resolved plan_ref, and the binding check
    # matches against it, not the basename alone (Codex R1 P1, third + final confirming rounds).
    (target / PLAN_REL).parent.joinpath("goal-ws1-example.txt").write_text(
        f"/goal do the build-ready thing from the finalized plan `{PLAN_REL.as_posix()}`\n",
        encoding="utf-8",
    )


def test_block_level_refuses_a_build_ready_plan_with_no_goal_prompt(tmp_path):
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="block")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 1
    assert "no goal prompt artifact" in precheck.stderr
    events = _goal_prompt_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_advise_level_warns_and_still_passes(tmp_path):
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="advise")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    assert "plan_authoring_standard_warning:" in precheck.stderr
    assert "no goal prompt artifact" in precheck.stderr
    events = _goal_prompt_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_advise_level_pass_action_persists_the_goal_when_one_is_missing(tmp_path):
    """Codex R1 (second confirming round) P2: the pass-path hint used to always print
    `goal-assignment ... --target ... --plan ...` with no `--out`, so following the ADVERTISED
    action only printed the goal to stdout and created no file -- the warning would fire again
    on every future precheck no matter how many times the advice was followed. When a goal
    prompt is missing, the pass action must include a concrete `--out` path."""
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="advise")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    pass_action = precheck.stdout.strip().splitlines()[-1]
    assert pass_action.startswith("plan_finalization_next_action: emit the builder-lane goal")
    assert "--out" in pass_action


def test_pass_action_omits_out_when_a_goal_prompt_already_shipped(tmp_path):
    """The --out addition is conditional on an actual gap -- a plan that already shipped its
    goal prompt gets the plain (pre-existing) hint, not a redundant --out suggestion."""
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="advise")
    _ship_goal_prompt(target)
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    pass_action = precheck.stdout.strip().splitlines()[-1]
    assert pass_action.startswith("plan_finalization_next_action: emit the builder-lane goal")
    assert "--out" not in pass_action


def test_default_absent_knob_behaves_as_advise_and_never_blocks(tmp_path):
    """The knob's default is `advise`; a plan finalized with no `planning` key at all must warn,
    never refuse -- a newly required artifact must not become a new stop-and-ask."""
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level=None)
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    assert "no goal prompt artifact" in precheck.stderr


def test_observe_level_logs_only_with_no_stderr_warning(tmp_path):
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="observe")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    assert "plan_authoring_standard_warning:" not in precheck.stderr
    assert "no goal prompt artifact" not in precheck.stderr
    events = _goal_prompt_events(target)
    assert len(events) == 1
    assert events[0]["fired"] is True


def test_off_level_is_silent_with_no_guard_event(tmp_path):
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="off")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    assert "no goal prompt artifact" not in precheck.stderr
    assert _goal_prompt_events(target) == []


def test_shipped_goal_prompt_passes_at_every_level(tmp_path):
    for level in ("off", "observe", "advise", "block"):
        home, adapter_root, target, adapter = _finalize_compliant_plan(
            tmp_path / level, level=level
        )
        _ship_goal_prompt(target)
        precheck = _precheck(home, adapter_root, target, adapter)
        assert precheck.returncode == 0, f"{level}: " + precheck.stdout + precheck.stderr
        assert "no goal prompt artifact" not in precheck.stderr, level


def test_block_level_next_action_points_at_goal_assignment_not_review(tmp_path):
    """Codex R1 P2: when the goal prompt is the ONLY thing missing, the printed next-action must
    not be the generic review-round recovery instruction (which cannot create the missing file
    and can consume the capped review budget for nothing)."""
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="block")
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 1
    next_action = precheck.stderr.split("plan_finalization_next_action:", 1)[1]
    assert next_action.strip().startswith("compose the missing goal prompt with")
    assert "goal-assignment" in next_action
    # The message explicitly tells the reader NOT to spend a review round -- that sentence
    # legitimately contains the phrase "run-plan-review" as prose, so the real assertion is
    # that it never appears as a RUNNABLE command (the `tautline run-plan-review --target`
    # form the generic recovery instruction prints).
    assert "tautline run-plan-review" not in next_action
    assert "do not run run-plan-review" in next_action


def test_goal_for_a_sibling_plan_does_not_satisfy_this_one(tmp_path):
    """Codex R1 P1: a flat plans directory (this repo's own docs/superpowers/plans/ shape) must
    not let a sibling plan's goal prompt silently satisfy this plan under `block`."""
    home, adapter_root, target, adapter = _finalize_compliant_plan(tmp_path, level="block")
    sibling_goal = (target / PLAN_REL).parent / "goal-for-a-different-plan.txt"
    sibling_goal.write_text(
        "/goal from the finalized plan `some-other-plan.md`\n", encoding="utf-8"
    )
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 1
    assert "does not appear in its text" in precheck.stderr
    # Shipping one that actually names THIS plan clears it.
    _ship_goal_prompt(target)
    precheck2 = _precheck(home, adapter_root, target, adapter)
    assert precheck2.returncode == 0, precheck2.stdout + precheck2.stderr


def test_standing_standard_command_surfaces_goal_prompt_requirement(tmp_path):
    """AC1's second half: the requirement is surfaced at AUTHORING time, not only at the gate."""
    home, adapter_root, target, adapter = base._prepare_target(tmp_path)
    result = base._run_cli(
        "plan-authoring-standard", "--target", str(target),
        home=home, adapter_root=adapter_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "goal prompt" in result.stdout
    assert "goal-assignment" in result.stdout
