import json
import os
import time

from minervit_methodology import guards


def _goal_run(cli, lane, goal_id="goal-1", status="in_progress"):
    work = lane / ".ai-work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "GOAL_RUN.json").write_text(
        json.dumps(
            {
                "schema": cli.GOAL_RUN_SCHEMA,
                "goalId": goal_id,
                "status": status,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _blocker(lane):
    return lane / ".ai-work" / "BLOCKER.json"


def test_blocker_declare_writes_valid_json_with_active_goal_id(cli, run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _goal_run(cli, lane, goal_id="goal-123")

    res = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for the deployment token after checking the adapter path.",
    )

    assert res.returncode == 0, res.stderr
    payload = json.loads(_blocker(lane).read_text(encoding="utf-8"))
    assert payload["schema"] == "minervit-blocker/v1"
    assert payload["kind"] == "credentials"
    assert payload["goal_id"] == "goal-123"
    assert payload["artifact"] is None
    assert payload["reason"] == "Waiting for the deployment token after checking the adapter path."
    assert "ts" in payload


def test_blocker_command_helpers_are_served_from_package(cli, tmp_path):
    checked = cli.parse_blocker_checked(
        "diff review, allowed validation, docs/evidence updates, next queue item, monitor follow-up"
    )
    assert checked == guards.parse_blocker_checked(
        "diff review, allowed validation, docs/evidence updates, next queue item, monitor follow-up"
    )
    assert cli.blocker_declare_error("credentials", "Waiting for credentials.", []) is None
    assert cli.blocker_declare_error(
        "no-safe-parallel-work",
        "No safe parallel work remains.",
        [],
    ) == guards.blocker_declare_error(
        "no-safe-parallel-work",
        "No safe parallel work remains.",
        [],
    )
    record = cli.blocker_declare_record(
        kind="credentials",
        reason="Waiting for credentials.",
        artifact=None,
        goal_id="goal-1",
        checked=[],
        timestamp="2026-07-07T00:00:00Z",
    )
    assert record == guards.blocker_declare_record(
        kind="credentials",
        reason="Waiting for credentials.",
        artifact=None,
        goal_id="goal-1",
        checked=[],
        timestamp="2026-07-07T00:00:00Z",
    )

    lane = tmp_path / "lane"
    lane.mkdir()
    assert cli.blocker_status_result(lane) == guards.blocker_status_result(lane, active_goal_id=None)
    assert cli.guard_check_blocker_state_result(lane) == guards.guard_check_blocker_state_result(
        lane,
        active_goal_id=None,
    )


# Note: the copied-bin-without-src execution mode is not supported for extracted guard
# helpers; guards_module() now hard-requires src/minervit_methodology (SystemExit otherwise),
# so the former "stale/partial guards module" fallback-parity tests were deleted.


def test_missing_blocker_does_not_read_corrupt_goal_state(run_cli, tmp_path):
    lane = tmp_path / "lane"
    work = lane / ".ai-work"
    work.mkdir(parents=True)
    (work / "GOAL_RUN.json").write_bytes(b"\xff")

    status = run_cli("blocker-status", "--target", str(lane))
    assert status.returncode == 1
    assert "blocker_status: missing" in status.stdout
    assert "Traceback" not in status.stderr

    guard = run_cli("guard-check", "--target", str(lane), "--boundary", "status")
    assert guard.returncode == 0, guard.stderr
    assert "guard_check_blocker: none" in guard.stdout
    assert "Traceback" not in guard.stderr


def test_missing_blocker_does_not_read_corrupt_lane_adapter(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / ".minervit-ai-delivery.json").write_bytes(b"\xff")

    status = run_cli("blocker-status", "--target", str(lane))
    assert status.returncode == 1
    assert "blocker_status: missing" in status.stdout
    assert "Traceback" not in status.stderr

    guard = run_cli("guard-check", "--target", str(lane), "--boundary", "status")
    assert guard.returncode == 0, guard.stderr
    assert "guard_check_blocker: none" in guard.stdout
    assert "Traceback" not in guard.stderr


def test_active_goal_lookup_ignores_non_object_goal_run(cli, tmp_path):
    lane = tmp_path / "lane"
    work = lane / ".ai-work"
    work.mkdir(parents=True)
    (work / "GOAL_RUN.json").write_text("[]\n", encoding="utf-8")

    assert cli.active_goal_id_for_target(lane) is None


def test_blocker_declare_rejects_unknown_kind(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()

    res = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "unclear",
        "--reason",
        "Unknown blocker class.",
    )

    assert res.returncode == 1
    assert "blocker_declare_error: unknown kind" in res.stderr
    assert not _blocker(lane).exists()


def test_no_safe_parallel_work_requires_checked_list(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()

    res = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "no-safe-parallel-work",
        "--reason",
        "No safe parallel work remains.",
    )

    assert res.returncode == 1
    assert "blocker_declare_error: no-safe-parallel-work requires --checked" in res.stderr
    assert not _blocker(lane).exists()


def test_no_safe_parallel_work_accepts_complete_checked_list(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()

    res = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "no-safe-parallel-work",
        "--reason",
        "No safe parallel work remains after checking all policy paths.",
        "--checked",
        "diff review, allowed validation, docs/evidence updates, next queue item, monitor follow-up",
    )

    assert res.returncode == 0, res.stderr
    payload = json.loads(_blocker(lane).read_text(encoding="utf-8"))
    assert payload["kind"] == "no-safe-parallel-work"
    assert payload["checked"] == [
        "diff review",
        "allowed validation",
        "docs/evidence updates",
        "next queue item",
        "monitor follow-up",
    ]


def test_blocker_status_marks_old_mtime_stale(cli, run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _goal_run(cli, lane, goal_id="goal-123")
    declared = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for credentials.",
    )
    assert declared.returncode == 0, declared.stderr
    old = time.time() - (31 * 60)
    os.utime(_blocker(lane), (old, old))

    res = run_cli("blocker-status", "--target", str(lane))

    assert res.returncode == 1
    assert "fresh: false" in res.stdout
    assert "stale_reason: older-than-30-minutes" in res.stdout


def test_blocker_status_marks_goal_mismatch_stale(cli, run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _goal_run(cli, lane, goal_id="goal-123")
    declared = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for credentials.",
    )
    assert declared.returncode == 0, declared.stderr
    _goal_run(cli, lane, goal_id="goal-456")

    res = run_cli("blocker-status", "--target", str(lane))

    assert res.returncode == 1
    assert "fresh: false" in res.stdout
    assert "stale_reason: goal-mismatch" in res.stdout


def test_blocker_status_marks_terminal_goal_stale(cli, run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _goal_run(cli, lane, goal_id="goal-123")
    declared = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for credentials.",
    )
    assert declared.returncode == 0, declared.stderr
    _goal_run(cli, lane, goal_id="goal-123", status="complete")

    res = run_cli("blocker-status", "--target", str(lane))

    assert res.returncode == 1
    assert "fresh: false" in res.stdout
    assert "stale_reason: goal-mismatch" in res.stdout


def test_blocker_status_marks_removed_goal_ledger_stale(cli, run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    _goal_run(cli, lane, goal_id="goal-123")
    declared = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for credentials.",
    )
    assert declared.returncode == 0, declared.stderr
    (lane / ".ai-work" / "GOAL_RUN.json").unlink()

    res = run_cli("blocker-status", "--target", str(lane))

    assert res.returncode == 1
    assert "fresh: false" in res.stdout
    assert "stale_reason: goal-mismatch" in res.stdout


def test_blocker_clear_removes_record(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    declared = run_cli(
        "blocker-declare",
        "--target",
        str(lane),
        "--kind",
        "credentials",
        "--reason",
        "Waiting for credentials.",
    )
    assert declared.returncode == 0, declared.stderr

    cleared = run_cli("blocker-clear", "--target", str(lane))

    assert cleared.returncode == 0, cleared.stderr
    assert not _blocker(lane).exists()
