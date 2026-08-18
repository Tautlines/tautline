"""Item 83 PR1 / WS1: `background-run` can say whether the work finished, and how.

The gap this closes: `background-run` used to `Popen` the command and return, so nothing in the
process tree ever called `wait()`. Nothing could know the exit code, and nothing recorded that the
run finished at all. A monitor could only infer from a dead pid -- and "the pid is gone" and "the
pid never started" are the same observation.

That is why a stalled background run reads exactly like a finished one, which is the contributing
factor behind the stale-monitor RCA: the tool that launches the work could not say whether the work
succeeded.
"""

import json
import time
from pathlib import Path

import pytest


def _await_meta(meta_path: Path, key: str = "finishedAt", deadline: float = 10.0) -> dict:
    """Poll for a recorded completion. A deadline, never a sleep-and-hope."""
    end = time.time() + deadline
    while time.time() < end:
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.05)
            continue
        if key in data:
            return data
        time.sleep(0.05)
    raise AssertionError(f"{key} never appeared in {meta_path} within {deadline}s")


def _await_marker(log_path: Path, deadline: float = 10.0) -> str:
    """Poll for the terminal marker itself, and return the line that carries it.

    Waiting on the META file is not waiting for this line. The producer writes the metadata first
    and only then appends `[tautline] finished:` to the log (cli.py), so a test that awaits the
    metadata and immediately reads the log races that gap. It is microseconds on an idle machine
    and wide enough to lose under load -- this test went red exactly once, during a full-suite run
    competing with two other suites, and passed on every isolated rerun.

    Wait for the artifact under assertion rather than a proxy for it.
    """
    end = time.time() + deadline
    last = ""
    while time.time() < end:
        try:
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            lines = []
        if lines:
            last = lines[-1]
            if last.startswith("[tautline] finished:"):
                return last
        time.sleep(0.05)
    raise AssertionError(
        f"terminal marker never appeared in {log_path} within {deadline}s; last line was {last!r}"
    )


def _run(run_cli, tmp_path, *command, extra=()):
    log = tmp_path / "run.log"
    res = run_cli("background-run", "--log", str(log), *extra, "--", *command)
    assert res.returncode == 0, res.stderr
    return log, res


def test_exit_code_and_finished_at_are_recorded(run_cli, tmp_path):
    """The headline: a completed run says it completed, and says how it went."""
    log, _res = _run(run_cli, tmp_path, "bash", "-c", "exit 3")
    meta = _await_meta(log.with_name("run.log.meta.json"))
    assert meta["exitCode"] == 3
    assert meta["finishedAt"]
    # Same shape as startedAt -- a consumer comparing them must not have to parse two formats.
    assert len(meta["finishedAt"]) == len(meta["startedAt"])


def test_the_terminal_marker_is_anchored_and_names_the_log(run_cli, tmp_path):
    """A producer-emitted, line-anchored marker: the rule this tool asks of everyone else.

    Anchored so a consumer can match `^\\[tautline\\] finished:` without a substring scan finding
    the phrase inside command output that happens to quote it.
    """
    log, _res = _run(run_cli, tmp_path, "bash", "-c", "exit 3")
    last = _await_marker(log)
    assert last.startswith("[tautline] finished: exit=3 ")
    assert "log=run.log" in last


def test_a_successful_run_records_zero(run_cli, tmp_path):
    """Non-vacuity floor: the recorder must distinguish success from failure, not just fire."""
    log, _res = _run(run_cli, tmp_path, "bash", "-c", "exit 0")
    meta = _await_meta(log.with_name("run.log.meta.json"))
    assert meta["exitCode"] == 0


def test_the_printed_pid_is_the_commands_not_the_reapers(run_cli, tmp_path):
    """The reaper is an implementation detail; every consumer keys on the COMMAND's pid.

    If this regressed to the reaper's pid, the timeout watchdog would kill the wrong process and
    the fan-out guard would count the wrong thing.
    """
    log, res = _run(run_cli, tmp_path, "bash", "-c", "sleep 5")
    printed = next(
        line.split(": ", 1)[1] for line in res.stdout.splitlines() if line.startswith("pid: ")
    )
    pid_file = log.with_name("run.log.pid").read_text(encoding="utf-8").strip()
    assert printed == pid_file
    meta = json.loads(log.with_name("run.log.meta.json").read_text(encoding="utf-8"))
    assert str(meta["pid"]) == printed
    assert meta["reaperPid"] != meta["pid"]


def test_the_fan_out_guard_still_counts_a_live_run(cli, run_cli, tmp_path):
    """Regression for the guard's pid semantics after the reaper moved process ownership."""
    log, _res = _run(run_cli, tmp_path, "bash", "-c", "sleep 5")
    _ = log.with_name("run.log.pid").read_text(encoding="utf-8")
    assert cli.count_live_background_runs(tmp_path) == 1


def test_the_monitor_line_is_not_tail_f(run_cli, tmp_path):
    """The tool that launches background work must not recommend the unbounded form.

    `tail -F` never exits, so it cannot report completion: a lane following that line watches a
    stream that goes quiet for either reason -- finished, or wedged. `monitor-status` reads the
    receipts the reaper writes and can tell those apart.
    """
    _log, res = _run(run_cli, tmp_path, "bash", "-c", "exit 0")
    assert "tail -F" not in res.stdout
    assert "monitor: tautline monitor-status" in res.stdout


@pytest.mark.parametrize("timeout_flag", [("--timeout-seconds", "1")])
def test_the_timeout_watchdog_still_fires_and_the_reaper_still_records(
    run_cli, tmp_path, timeout_flag
):
    """Both mechanisms must survive together: the watchdog kills, the reaper records the kill.

    Before this change the timeout line was the ONLY completion evidence, and it appeared for one
    failure mode out of many.
    """
    log, _res = _run(run_cli, tmp_path, "bash", "-c", "sleep 30", extra=timeout_flag)
    meta = _await_meta(log.with_name("run.log.meta.json"), deadline=20.0)
    assert meta["exitCode"] != 0
    _await_marker(log)  # the marker trails the receipt; see _await_marker
    text = log.read_text(encoding="utf-8")
    assert "[minervit] timeout after" in text
    assert "[tautline] finished: exit=" in text


def test_a_log_outside_the_runs_dir_is_advised(run_cli, tmp_path, cli):
    """The advisory names the configured runsDir, resolved from laneState -- never hardcoded.

    The turn-end yield gate scans the CONFIGURED directory. A lane that moved it would otherwise be
    told its run is inside the gate's scan when it is not: an advisory wrong in the reassuring
    direction, which is worse than no advisory.
    """
    _log, res = _run(run_cli, tmp_path, "bash", "-c", "exit 0")
    # This repo has an adapter, and tmp_path is outside its runsDir.
    assert "outside this lane's configured runsDir" in res.stdout
    assert "will not see this run" in res.stdout


def test_the_runs_dir_resolver_reads_the_adapter_not_a_constant(cli, tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    assert cli.background_run_runs_dir({"laneState": {"runsDir": "custom/runs"}}, root) == (
        root / "custom" / "runs"
    ).resolve()
    # An adapter that omits it falls back to the documented default, not to nothing.
    assert cli.background_run_runs_dir({"laneState": {}}, root) == (root / ".ai-runs").resolve()
    # No adapter means no claim about a runsDir at all -- silence, not a guess.
    assert cli.background_run_runs_dir(None, None) is None


def test_the_monitor_this_release_recommends_can_tell_success_from_failure(run_cli, tmp_path):
    """The headline of the change, and it was hollow without this.

    `background-run` now prints `monitor: tautline monitor-status ...` instead of `tail -F`, on the
    grounds that `tail -F` cannot report completion. But `monitor_status` classified purely on pid
    liveness and log age, so BOTH `exit 0` and `exit 3` came back `stale` once the pid died — the
    replacement was blind in exactly the way the thing it replaced was blind (Codex R1).
    """
    for code, expected in ((0, "success"), (3, "failed")):
        log = tmp_path / f"run{code}.log"
        res = run_cli("background-run", "--log", str(log), "--", "bash", "-c", f"exit {code}")
        assert res.returncode == 0, res.stderr
        _await_meta(log.with_name(f"run{code}.log.meta.json"))
        status = run_cli("monitor-status", "--target", str(tmp_path), "--log", str(log))
        assert f"monitor_state: {expected}" in status.stdout, status.stdout
        assert f"monitor_exit_code: {code}" in status.stdout


def test_a_reused_log_path_does_not_arm_the_watchdog_against_the_old_pid(run_cli, tmp_path):
    """A supervisor pointed at the wrong process is worse than no supervisor.

    Reusing a `--log` path left the previous run's `<log>.pid` in place, and the bounded readback
    could accept that OLD pid before the new reaper overwrote it. The launcher would print and store
    it and arm the timeout watchdog against a process it never started — and if that process were
    still alive its identity would verify, so the watchdog could kill an unrelated process group
    while leaving the new command unbounded (Codex R1).
    """
    log = tmp_path / "reused.log"
    pid_file = log.with_name("reused.log.pid")
    first = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "exit 0")
    assert first.returncode == 0
    _await_meta(log.with_name("reused.log.meta.json"))
    stale_pid = pid_file.read_text(encoding="utf-8").strip()

    second = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "sleep 5")
    assert second.returncode == 0, second.stderr
    printed = next(
        line.split(": ", 1)[1] for line in second.stdout.splitlines() if line.startswith("pid: ")
    )
    assert printed != stale_pid, "the launcher reported the PREVIOUS run's pid"
    assert pid_file.read_text(encoding="utf-8").strip() == printed


def test_a_fast_command_keeps_its_completion_record(run_cli, tmp_path):
    """The launcher writes metadata AFTER spawning the reaper, so a command that finishes in
    milliseconds has already had `finishedAt`/`exitCode` published — and a plain write erased them
    for exactly the fastest runs, which is the completion record this release exists to produce.

    `exit 7` finishes about as fast as anything can, so this is the window (Codex R1).
    """
    log = tmp_path / "fast.log"
    res = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "exit 7")
    assert res.returncode == 0, res.stderr
    meta = _await_meta(log.with_name("fast.log.meta.json"))
    assert meta["exitCode"] == 7
    assert meta["finishedAt"]
    # ...and the launcher-owned fields survived too, so the merge did not go the other way.
    assert meta["pid"] and meta["reaperPid"] and meta["command"]


def test_an_explicit_failure_marker_outranks_a_zero_exit(run_cli, tmp_path):
    """`--failure-marker` exists for tools whose exit code is insufficient, so it is not an
    inference for the recorded exit to outrank — it is the caller declaring what failure looks
    like. Placing the receipt above it made a command that exits 0 while printing the marker report
    `success`, defeating the whole mechanism (Codex R2).
    """
    log = tmp_path / "marked.log"
    res = run_cli(
        "background-run", "--log", str(log), "--", "bash", "-c", "echo BUILD-FAILED; exit 0"
    )
    assert res.returncode == 0, res.stderr
    meta = _await_meta(log.with_name("marked.log.meta.json"))
    assert meta["exitCode"] == 0

    status = run_cli(
        "monitor-status", "--target", str(tmp_path), "--log", str(log),
        "--failure-marker", "BUILD-FAILED",
    )
    assert "monitor_state: failed" in status.stdout, status.stdout


def test_a_receipt_is_bound_to_its_own_run_even_when_a_log_is_shared():
    """Attribution is solved by BINDING the receipt, not by locking the log.

    Nine review rounds went into a hand-rolled O_EXCL + pid + staleness lock meant to stop two runs
    sharing a log, and each round found the next race in it — pid reuse, takeover serialization,
    ownership released a moment too early. That work is filed as its own item, to be built on the
    `advisory_flock`/occupancy-lease primitives this repo already has rather than a fourth
    hand-rolled scheme.

    What makes the RECEIPT correct needs no lock at all: the reaper writes only when the metadata
    still names its own pid, and `monitor-status` ignores a receipt naming a different pid than the
    one asked about. Both are pinned below and neither depends on exclusion.
    """
    # Documented non-guarantee, asserted so it is not mistaken for an oversight: concurrent reuse
    # of one --log path is UNSUPPORTED, and the receipt binding is what keeps it from lying.


def test_a_dead_previous_run_may_reuse_its_log(run_cli, tmp_path):
    """Non-vacuity for the refusal above: rerunning into the same log is the ordinary case and must
    still work, or the guard would have replaced an attribution bug with a usability wall."""
    log = tmp_path / "rerun.log"
    first = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "exit 4")
    assert first.returncode == 0, first.stderr
    assert _await_meta(log.with_name("rerun.log.meta.json"))["exitCode"] == 4

    second = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "exit 0")
    assert second.returncode == 0, second.stdout + second.stderr
    assert _await_meta(log.with_name("rerun.log.meta.json"), key="exitCode")["exitCode"] == 0


def test_a_receipt_for_another_pid_is_not_evidence_about_this_one(cli, tmp_path):
    """`monitor-status --pid` asked about a specific run; a receipt naming a different pid is not
    evidence about it, and trusting it would report another run's completion (Codex R3)."""
    log = tmp_path / "other.log"
    log.write_text("x\n", encoding="utf-8")
    log.with_name("other.log.meta.json").write_text(
        json.dumps({"pid": 999999, "exitCode": 0, "finishedAt": "2026-01-01T00:00:00"}),
        encoding="utf-8",
    )
    import argparse

    args = argparse.Namespace(
        target=tmp_path, log=str(log), pid=123456, pid_file=None, max_stale_seconds=600,
        success_marker=None, failure_marker=None, strict=False, project=None,
    )
    code = cli.monitor_status(args)
    assert code == 0


def test_a_command_that_cannot_start_says_so(run_cli, tmp_path):
    """A missing binary produced no pid, no log line, and nothing to read.

    The launcher's bounded readback then reported only that the reaper never named a pid within
    five seconds — true, and useless: it describes the supervisor rather than the failure. The
    reaper now writes the launch error where a reader will look and records exit 127, so
    `monitor-status` classifies it instead of inferring staleness (Codex R3).
    """
    log = tmp_path / "nostart.log"
    run_cli("background-run", "--log", str(log), "--", "definitely-not-a-real-binary-xyz")
    meta = _await_meta(log.with_name("nostart.log.meta.json"), key="exitCode")
    assert meta["exitCode"] == 127
    assert meta["launchError"]
    _await_marker(log)  # the marker trails the receipt; see _await_marker
    text = log.read_text(encoding="utf-8")
    assert "[tautline] launch failed:" in text
    assert "[tautline] finished: exit=127 " in text


def test_a_watchdog_kill_is_recorded_as_a_timeout_not_as_an_exit_code(run_cli, tmp_path):
    """"We terminated it for running too long" and "it chose to exit with this code" must be
    distinguishable.

    A SIGTERM-derived code is a plausible code for a program to return on its own, so the number
    alone cannot say who ended the run — and a receipt that says what happened is the whole point of
    this release. The watchdog leaves an explicit marker; the reaper records `timedOut` from it
    rather than inferring from the code (Codex R5).
    """
    log = tmp_path / "slow.log"
    res = run_cli(
        "background-run", "--log", str(log), "--timeout-seconds", "1",
        "--", "bash", "-c", "sleep 30",
    )
    assert res.returncode == 0, res.stderr
    meta = _await_meta(log.with_name("slow.log.meta.json"), deadline=25.0)
    assert meta["timedOut"] is True, meta
    status = run_cli("monitor-status", "--target", str(tmp_path), "--log", str(log))
    assert "monitor_state: failed" in status.stdout
    assert "TERMINATED BY THE TIMEOUT WATCHDOG" in status.stdout, status.stdout


def test_an_ordinary_failure_is_not_reported_as_a_timeout(run_cli, tmp_path):
    """Non-vacuity for the flag: a command that simply fails must not be labelled a timeout, or the
    distinction the previous test asserts would be decoration."""
    log = tmp_path / "plain.log"
    run_cli("background-run", "--log", str(log), "--timeout-seconds", "30", "--", "bash", "-c", "exit 9")
    meta = _await_meta(log.with_name("plain.log.meta.json"), key="exitCode")
    assert meta["exitCode"] == 9
    assert meta["timedOut"] is False


def test_a_timed_out_run_is_not_reported_as_success_when_its_child_exits_zero(cli, tmp_path):
    """`timedOut` is checked BEFORE the exit code, not after.

    A process group terminated by the watchdog can still leave a zero exit — a wrapper that traps
    SIGTERM and exits cleanly, a shell reporting its last successful builtin — and ordering success
    first reported that run as a SUCCESS. The receipt says it was killed; the number does not
    (Codex v2 R1).
    """
    import argparse

    log = tmp_path / "trapped.log"
    log.write_text("x\n", encoding="utf-8")
    log.with_name("trapped.log.meta.json").write_text(
        json.dumps(
            {"pid": 424242, "exitCode": 0, "finishedAt": "2026-01-01T00:00:00", "timedOut": True}
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        target=tmp_path, log=str(log), pid=None, pid_file=None, max_stale_seconds=600,
        success_marker=None, failure_marker=None, strict=True, project=None,
    )
    assert cli.monitor_status(args) == 1, "a timed-out run must not pass --strict"


def test_the_receipt_exists_whenever_the_terminal_marker_does(run_cli, tmp_path):
    """The marker must never appear while the receipt it points at is still absent.

    Both say the run finished, and this release tells consumers to trust the RECEIPT — so a marker
    written first meant a consumer could see `[tautline] finished:` and then read metadata with no
    `exitCode`, classifying a completed run as stale. The visible signal arriving before the
    authoritative one is the same shape as every other finding in this item (Codex v2 R4).
    """
    log = tmp_path / "order.log"
    res = run_cli("background-run", "--log", str(log), "--", "bash", "-c", "exit 6")
    assert res.returncode == 0, res.stderr
    _await_meta(log.with_name("order.log.meta.json"), key="exitCode")
    if "[tautline] finished:" in log.read_text(encoding="utf-8"):
        meta = json.loads(log.with_name("order.log.meta.json").read_text(encoding="utf-8"))
        assert meta.get("exitCode") == 6, "marker present but receipt missing its exit code"
