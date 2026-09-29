"""Non-blocking invariants and end-to-end acceptance (item 27: session-start currency gate).

Fixtures build real git repositories and a real second worktree -- nothing here mocks git.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from lane_status_fixtures import (
    clean_lane,
    git,
    lane_with_integration_worktree_ahead,
    lane_with_squatted_integration_worktree,
    stale_orphaned_lane,
    write_adapter,
)
from tautline_methodology import cli

SCHEMA = Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema.json"


def _args(lane, *, hook=True, json_mode=False):
    return argparse.Namespace(target=Path(lane), hook=hook, json=json_mode, project=None)


def _artifact(lane: Path) -> dict:
    return json.loads((lane / ".ai-work" / "LANE_STATUS.json").read_text(encoding="utf-8"))


# --- C1: no representable blocking value -------------------------------------------------------


def _lane_status_schema():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["laneStatus"]


def test_startup_check_offers_no_blocking_value():
    """C1: the never-blocks guarantee is structural. Adding teeth must require a schema change that
    shows up in review -- not a config edit on someone's laptop."""
    enum = _lane_status_schema()["properties"]["startupCheck"]["enum"]
    assert enum == ["off", "report"]
    assert "block" not in enum


def test_schema_fetch_timeout_maximum_matches_the_clamp():
    assert (
        _lane_status_schema()["properties"]["fetchTimeoutSeconds"]["maximum"]
        == cli.LANE_STATUS_MAX_FETCH_TIMEOUT_SECONDS
    )


def test_blocking_shaped_nested_keys_are_rejected():
    """Top-level additionalProperties:false does not recurse. Without the nested guard,
    `laneStatus: {block: true}` validates and C1's structural claim is false."""
    assert _lane_status_schema()["additionalProperties"] is False


# --- C2: every exit path is `return 0` ---------------------------------------------------------


def test_lane_status_can_only_ever_return_zero():
    """C2 is 'every return is `return 0`', not 'one syntactic return' -- the handler has several
    early exits. Structural, asserted over the full list."""
    source = inspect.getsource(cli.lane_status)
    # A CALL, not the word: the docstring names the invariant it is asserting.
    assert "hook_decision(" not in source
    returns = [line.strip() for line in source.splitlines() if line.strip().startswith("return")]
    assert returns, "handler has no return statement"
    assert all(line == "return 0" for line in returns), f"non-zero exit path present: {returns}"


# --- C4 / C5: every failure mode exits 0 and still reports --------------------------------------


def test_missing_adapter_is_byte_silent_in_hook_mode(tmp_path, capsys):
    """This hook is registered globally, so it runs in every repository the operator opens.
    Warning in unrelated repos would be the loudest instance of the habituation failure this item
    exists to end."""
    bare = tmp_path / "unmanaged"
    bare.mkdir()
    assert cli.lane_status(_args(bare)) == 0
    assert capsys.readouterr().out.strip() == ""


def test_missing_adapter_explains_itself_in_manual_mode(tmp_path, capsys):
    bare = tmp_path / "unmanaged"
    bare.mkdir()
    assert cli.lane_status(_args(bare, hook=False)) == 0
    assert "UNVERIFIED" in capsys.readouterr().out


# `corrupt-baseline` was a fifth mode here until the 2026-08-28 demolition removed the latest-code
# baseline: nothing writes or reads LATEST_CODE_BASELINE.json any more, so corrupting it exercises
# no code path and asserting UNVERIFIED on it would be a test that passes by measuring nothing.
@pytest.mark.parametrize(
    "mode", ["no-remote", "no-upstream", "detached", "hostile-remote"]
)
def test_every_failure_mode_exits_zero_and_still_reports(mode, tmp_path, capsys):
    """C4 + C5. Nonempty output is not enough -- the one-line `clean OK` report is also nonempty --
    so each mode asserts the verdict it must actually produce."""
    lane = clean_lane(tmp_path)
    if mode == "no-remote":
        git(lane, "remote", "remove", "origin")
    elif mode == "no-upstream":
        git(lane, "switch", "-qc", "work/no-upstream")
    elif mode == "detached":
        head = git(lane, "rev-parse", "HEAD")
        git(lane, "checkout", "-q", head)
    elif mode == "hostile-remote":
        write_adapter(lane)
        data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
        data["latestCode"]["remote"] = "--upload-pack=/tmp/pwned"
        (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")

    assert cli.lane_status(_args(lane, json_mode=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    ids = {finding["id"] for finding in payload["findings"]}
    expected = {"detached": "DETACHED"}.get(mode, "UNVERIFIED")
    assert expected in ids, f"{mode} rendered {ids}, expected {expected}"


def test_a_symlink_loop_target_still_reports(tmp_path, capsys):
    """Resolution happens INSIDE the containment block: a symlink loop raises from .resolve(), and
    outside the try the shell swallows stderr and the session gets no line at all."""
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    assert cli.lane_status(_args(loop, hook=False)) == 0
    assert capsys.readouterr().out.strip()


def test_an_invalid_adapter_reports_rather_than_going_silent(tmp_path, capsys):
    """load_project raises SystemExit, which `except Exception` does not catch -- that would be the
    forbidden silent startup on a located lane."""
    lane = clean_lane(tmp_path)
    (lane / ".tautline.json").write_text("{ not valid json", encoding="utf-8")
    assert cli.lane_status(_args(lane)) == 0
    assert "UNVERIFIED" in capsys.readouterr().out


def test_a_hostile_remote_never_reaches_the_report_or_the_artifact(tmp_path, capsys):
    """git parses a leading `--` value as an OPTION, so `--upload-pack=...` in a
    repository-controlled adapter would execute an attacker-named binary at session start."""
    lane = clean_lane(tmp_path)
    data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
    data["latestCode"]["remote"] = "--upload-pack=/tmp/pwned"
    (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.lane_status(_args(lane, hook=False)) == 0
    out = capsys.readouterr().out
    assert "upload-pack" not in out
    assert "<unusable>" in json.dumps(_artifact(lane))
    assert "upload-pack" not in json.dumps(_artifact(lane))


def test_an_unwritable_status_path_is_reported_and_publishes_no_clean_verdict(tmp_path, capsys):
    """A swallowed write error would print a clean report while leaving consumers reading a stale
    artifact -- two consumers disagreeing about the same lane."""
    lane = clean_lane(tmp_path)
    (lane / ".ai-work").mkdir(exist_ok=True)
    (lane / ".ai-work" / "LANE_STATUS.json").mkdir()  # a directory cannot be written as a file
    assert cli.lane_status(_args(lane)) == 0
    assert "UNVERIFIED" in capsys.readouterr().out


def test_a_tracked_status_path_is_refused(tmp_path, capsys):
    """statusFile may name any in-repo path; a repository-controlled adapter must not be able to
    turn a SessionStart hook into an overwrite of tracked content."""
    lane = clean_lane(tmp_path)
    data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
    data["laneStatus"] = {"statusFile": "VERSION"}
    (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")
    before = (lane / "VERSION").read_text(encoding="utf-8")
    assert cli.lane_status(_args(lane, hook=False)) == 0
    assert "UNVERIFIED" in capsys.readouterr().out
    assert (lane / "VERSION").read_text(encoding="utf-8") == before, "tracked file was overwritten"


def test_startup_check_off_silences_the_hook_but_not_the_manual_diagnostic(tmp_path, capsys):
    lane = clean_lane(tmp_path)
    data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
    data["laneStatus"] = {"startupCheck": "off"}
    (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.lane_status(_args(lane)) == 0
    assert capsys.readouterr().out.strip() == ""
    assert cli.lane_status(_args(lane, hook=False)) == 0
    assert capsys.readouterr().out.strip()


# --- acceptance ---------------------------------------------------------------------------------


def test_stale_orphaned_lane_reports_at_start_without_any_tool_call(tmp_path, capsys):
    """Acceptance: reproduces the 2026-07-24 incident -- a lane three minors behind with a deleted
    upstream -- and proves it surfaces with no tool call and no subagent."""
    lane = stale_orphaned_lane(tmp_path, local_version="0.17.5", base_version="0.20.0")
    assert cli.lane_status(_args(lane)) == 0
    out = capsys.readouterr().out
    assert "ORPHANED" in out and "STALE" in out
    assert "0.17.5" in out and "0.20.0" in out
    assert "THE AGENT RUNS THIS, NOT THE OPERATOR" in out


def test_clean_lane_prints_exactly_one_line(tmp_path, capsys):
    lane = clean_lane(tmp_path)
    cli.lane_status(_args(lane))
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_a_lane_without_a_version_file_is_still_clean(tmp_path, capsys):
    """Adopter repositories are not required to carry a VERSION; a mandatory comparison would make
    every otherwise clean session in such a project report a false failure."""
    lane = clean_lane(tmp_path, version=None)
    cli.lane_status(_args(lane))
    out = capsys.readouterr().out
    assert "clean OK" in out
    assert "UNVERIFIED" not in out


def test_squatted_integration_branch_is_detected_with_a_real_worktree(tmp_path, capsys):
    lane, _held = lane_with_squatted_integration_worktree(tmp_path)
    cli.lane_status(_args(lane))
    assert "SQUATTED" in capsys.readouterr().out


def test_a_peer_worktree_legitimately_ahead_is_not_squatted(tmp_path, capsys):
    """SQUATTED means held BEHIND the remote. A worktree with unpublished commits is not squatting,
    and branding it so produces a false verdict plus an untrue 'behind remote' detail."""
    lane, _held = lane_with_integration_worktree_ahead(tmp_path)
    cli.lane_status(_args(lane))
    assert "SQUATTED" not in capsys.readouterr().out


def test_the_artifact_matches_the_frozen_v1_contract(tmp_path):
    lane = stale_orphaned_lane(tmp_path, local_version="0.17.5", base_version="0.20.0")
    cli.lane_status(_args(lane))
    payload = _artifact(lane)
    assert set(payload) == {
        "schema", "recordedAt", "lastFetchAt", "branch", "integrationBranch", "remote",
        "ahead", "behind", "localVersion", "baseVersion", "findings", "resolved",
    }
    assert payload["schema"] == "tautline-lane-status/v1"
    assert payload["resolved"] is False
    assert {finding["id"] for finding in payload["findings"]} >= {"ORPHANED", "STALE"}


def test_json_output_is_byte_equal_to_the_artifact(tmp_path, capsys):
    """--json and the artifact are one contract; they must not drift apart."""
    lane = clean_lane(tmp_path)
    cli.lane_status(_args(lane, json_mode=True))
    emitted = json.loads(capsys.readouterr().out)
    assert emitted == _artifact(lane)


def test_rerunning_after_remediation_marks_the_artifact_resolved(tmp_path):
    """The remediate-then-consume flow: without it, a resolved condition keeps being reported."""
    lane = stale_orphaned_lane(tmp_path, local_version="0.17.5", base_version="0.20.0")
    cli.lane_status(_args(lane))
    assert _artifact(lane)["resolved"] is False
    subprocess.run(
        ["git", "-C", str(lane), "switch", "-q", "-c", "work/fresh", "origin/experimental"],
        capture_output=True,
        check=True,
    )
    cli.lane_status(_args(lane))
    payload = _artifact(lane)
    assert payload["resolved"] is True
    assert payload["findings"] == []


def test_status_file_may_not_name_another_framework_state_file(tmp_path, capsys):
    """`.ai-work/GOAL_RUN.json` is ignored, untracked and inside the worktree -- exactly what the
    safety gate accepts -- so without an ownership reservation a misconfigured statusFile would
    erase an active goal on every session start."""
    lane = clean_lane(tmp_path)
    (lane / ".ai-work").mkdir(exist_ok=True)
    goal = lane / ".ai-work" / "GOAL_RUN.json"
    goal.write_text('{"goal": "do not clobber me"}', encoding="utf-8")
    data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
    data["laneStatus"] = {"statusFile": ".ai-work/GOAL_RUN.json"}
    (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.lane_status(_args(lane, hook=False)) == 0
    assert "UNVERIFIED" in capsys.readouterr().out
    assert json.loads(goal.read_text(encoding="utf-8"))["goal"] == "do not clobber me"


def test_the_latest_code_baseline_is_also_reserved(tmp_path, capsys):
    lane = clean_lane(tmp_path)
    (lane / ".ai-work").mkdir(exist_ok=True)
    baseline = lane / ".ai-work" / "LATEST_CODE_BASELINE.json"
    baseline.write_text('{"baseCommit": "keepme"}', encoding="utf-8")
    data = json.loads((lane / ".tautline.json").read_text(encoding="utf-8"))
    data["laneStatus"] = {"statusFile": ".ai-work/LATEST_CODE_BASELINE.json"}
    (lane / ".tautline.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.lane_status(_args(lane, hook=False)) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["baseCommit"] == "keepme"


def test_startup_fetches_are_noninteractive():
    """A SessionStart fetch must never stall behind a credential prompt; a timeout does not make an
    operation noninteractive, it only kills it after the stall."""
    env = cli.lane_status_fetch_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert env["GCM_INTERACTIVE"] == "never"
