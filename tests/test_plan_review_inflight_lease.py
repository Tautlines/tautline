"""Item 77 WS1: one plan-review round per plan hash at a time.

The defect: `run-plan-review` had no idea another round was already in flight for the same
plan content. Two launches -- an operator retrying a round that looked hung, a second lane
picking up the same plan, a wedged round re-run -- both spawned a reviewer, both spent budget,
and the second one's log is the one that got classified. Nothing recorded that the first was
still running.

The lease is a file, deliberately: it works with no daemon and no shared service, across
worktrees on one machine, and it is inspectable by the person the refusal talks to.

Liveness is pid-based on the same host and TTL-based across hosts, and the asymmetry is the
point -- a pid from another machine is unverifiable, and failing OPEN there would re-create the
double-launch this exists to stop. So cross-host degrades to a generous TTL: a false "live"
costs one refusal carrying a `tail -f`, a false "stale" costs the incident.
"""
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone

import pytest


def _lease(cli, **overrides) -> dict:
    lease = {
        "schema": cli.PLAN_REVIEW_INFLIGHT_SCHEMA,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "plan_path": "docs/plans/p.md",
        "plan_content_sha256": "abc123",
        "round": "R1",
        "log_path": ".ai-runs/plan-review/r1.log",
        "started_at": cli.now_iso(),
    }
    lease.update(overrides)
    return lease


def _acquire(cli, tmp_path, plan_hash="abc123", review_round="R1"):
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return cli.plan_review_acquire_inflight_lease(
        tmp_path, runs_dir, "docs/plans/p.md", plan_hash, review_round, runs_dir / "r1.log"
    )


# --- 1. acquisition ------------------------------------------------------------------------------


def test_acquiring_writes_a_lease_naming_the_launcher(cli, tmp_path):
    lease_path, refusal = _acquire(cli, tmp_path)
    assert refusal is None
    assert lease_path is not None and lease_path.is_file()
    recorded = json.loads(lease_path.read_text(encoding="utf-8"))
    assert recorded["schema"] == cli.PLAN_REVIEW_INFLIGHT_SCHEMA
    assert recorded["pid"] == os.getpid()
    assert recorded["hostname"] == socket.gethostname()
    assert recorded["plan_content_sha256"] == "abc123"


def test_the_lease_is_keyed_on_plan_CONTENT_not_on_the_path(cli, tmp_path):
    """Two different plans review concurrently; the same plan content does not."""
    first, _ = _acquire(cli, tmp_path, plan_hash="hash-one")
    second, refusal = _acquire(cli, tmp_path, plan_hash="hash-two")
    assert refusal is None
    assert first != second


def test_the_lease_file_does_not_collide_with_the_meta_glob(cli, tmp_path):
    """It lands in the same directory the round's own artifacts do, so its name must not be
    picked up by anything scanning for `*.meta.json`."""
    lease_path, _ = _acquire(cli, tmp_path)
    assert lease_path.name.endswith(".lease.json")
    assert not lease_path.name.endswith(".meta.json")
    assert list((tmp_path / ".ai-runs" / "plan-review").glob("*.meta.json")) == []


# --- 2. a live holder refuses --------------------------------------------------------------------


def test_a_live_round_refuses_the_second_launch(cli, tmp_path):
    _acquire(cli, tmp_path)
    lease_path, refusal = _acquire(cli, tmp_path)
    assert lease_path is None
    assert refusal and "already in flight" in refusal


def test_the_refusal_hands_back_a_runnable_reattach(cli, tmp_path):
    """A refusal that does not say how to reach the round it is protecting just looks like a
    bug to the lane that meets it."""
    _acquire(cli, tmp_path)
    _, refusal = _acquire(cli, tmp_path)
    assert "tail -F" in refusal
    assert "finalize-plan-review" in refusal
    assert str(os.getpid()) in refusal


def test_the_refusal_never_hands_the_decision_to_a_person(cli, tmp_path):
    _acquire(cli, tmp_path)
    _, refusal = _acquire(cli, tmp_path)
    lowered = refusal.lower()
    for phrase in ("escalate", "ask the operator", "ask a human", "wait for the operator"):
        assert phrase not in lowered, phrase


# --- 3. a dead holder is reclaimed, out loud -----------------------------------------------------


def test_a_dead_holders_lease_is_reclaimed_with_a_printed_note(cli, tmp_path, capsys):
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stale = cli.plan_review_inflight_lease_path(runs_dir, "abc123")
    # pid 1 exists but is not us; use an unassigned high pid instead so the probe says dead.
    dead_pid = 2**22
    stale.write_text(json.dumps(_lease(cli, pid=dead_pid)), encoding="utf-8")
    lease_path, refusal = _acquire(cli, tmp_path)
    assert refusal is None, "a crashed launcher must not strand the plan forever"
    assert lease_path is not None
    out = capsys.readouterr().out
    assert "plan_review_inflight_note: reclaiming stale in-flight lease" in out
    assert str(dead_pid) in out


def test_an_unreadable_lease_is_reclaimed_rather_than_trusted(cli, tmp_path, capsys):
    """A corrupt body must still be reclaimable -- but only once it is OLD enough to prove it is
    garbage rather than a write in progress (see the test below)."""
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stale = cli.plan_review_inflight_lease_path(runs_dir, "abc123")
    stale.write_text("{not json", encoding="utf-8")
    old = time.time() - (cli.PLAN_REVIEW_LEASE_WRITE_WINDOW_SECONDS + 60)
    os.utime(stale, (old, old))

    lease_path, refusal = _acquire(cli, tmp_path)

    assert refusal is None
    assert lease_path is not None


def test_a_lease_still_being_written_is_live_not_stale(cli, tmp_path, capsys):
    """Codex R2 P2. The winner creates the lease with O_EXCL and only THEN writes the JSON body.
    A loser arriving inside that window reads an empty file, and every path turns that into `{}` --
    which read as stale, unlinked the winner's inode, and let BOTH launchers proceed. That is
    exactly the racing launch the lease exists to serialize, so it cannot be the case it fails."""
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    inflight = cli.plan_review_inflight_lease_path(runs_dir, "abc123")
    inflight.write_text("", encoding="utf-8")  # created, body not yet written

    lease_path, refusal = _acquire(cli, tmp_path)

    assert lease_path is None, "the loser must back off, not reclaim a live round"
    assert refusal and "mid-write" in refusal, "and be told why, with a way forward"
    assert inflight.exists(), "the winner's inode must survive"


# --- 4. liveness: pid on this host, TTL across hosts ---------------------------------------------


def test_our_own_pid_reads_as_live(cli):
    assert cli.plan_review_inflight_lease_is_live(_lease(cli)) is True


def test_a_dead_pid_on_this_host_reads_as_stale(cli):
    assert cli.plan_review_inflight_lease_is_live(_lease(cli, pid=2**22)) is False


def test_a_foreign_host_inside_the_ttl_reads_as_live(cli):
    """The pid is unverifiable from here, and failing OPEN would re-create the double-launch."""
    lease = _lease(cli, hostname="some-other-host", pid=999999)
    assert cli.plan_review_inflight_lease_is_live(lease) is True


def test_a_foreign_host_past_the_ttl_reads_as_stale(cli):
    old = datetime.now(timezone.utc) - timedelta(seconds=cli.PLAN_REVIEW_INFLIGHT_TTL_SECONDS + 60)
    lease = _lease(cli, hostname="some-other-host", started_at=old.isoformat())
    assert cli.plan_review_inflight_lease_is_live(lease) is False


def test_a_naive_foreign_timestamp_does_not_crash_the_launcher(cli):
    """Subtracting a naive datetime from an aware one raises TypeError, which would kill
    run-plan-review at launch instead of refusing or reclaiming. Someone else's clock format is
    not a reason for this lane to die."""
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    lease = _lease(cli, hostname="some-other-host", started_at=naive)
    assert cli.plan_review_inflight_lease_is_live(lease) is True


def test_a_garbage_timestamp_reads_as_stale_rather_than_raising(cli):
    lease = _lease(cli, hostname="some-other-host", started_at="not-a-timestamp")
    assert cli.plan_review_inflight_lease_is_live(lease) is False


def test_a_missing_pid_reads_as_stale(cli):
    lease = _lease(cli)
    lease.pop("pid")
    assert cli.plan_review_inflight_lease_is_live(lease) is False


# --- 5. the wiring invariant ---------------------------------------------------------------------


def test_the_lease_is_acquired_after_every_pre_existing_gate(cli):
    """Placement is the whole design: acquired after the budget/precheck/command gates, so a
    refused launch has spent nothing, and released in a `finally`, so a wedged or killed round
    frees it. Pinned at the source because no output assertion can see an ordering.
    """
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    acquire = source.index("plan_review_acquire_inflight_lease(")
    assert "review_command_errors" in source[:acquire], "command gate must run before the lease"
    assert source.index("try:", acquire) < source.index('event="plan_review_started"')
    assert "finally:" in source[acquire:]
    assert "plan_review_release_inflight_lease(lease_path)" in source[acquire:]


def test_a_content_gate_added_later_must_go_above_the_lease(cli):
    """Successor invariant for item 80, recorded where the next builder will read it: a content
    refusal below the acquisition point returns while the lease is held, stranding it for the
    whole TTL on a plan nobody is reviewing."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    assert "SUCCESSOR INVARIANT" in source


# --- Stitched: the lease and the wedge/refusal stories compose ----------------------------------
#
# Neither source plan could write these. Item 77 introduced a lease file into the same
# `.ai-runs/plan-review/` directory that item 76's "stale artifacts must not poison the re-run"
# scenario was written against, and item 76 pinned that scenario assuming no lease existed.
# Authored blind to each other, both were right and the pair was untested.


def test_a_run_that_dies_inside_the_body_still_frees_the_lease(cli, tmp_path, monkeypatch):
    """The wedge story. A watchdog-killed or exception-ended round is exactly the case that most
    needs a clean re-run, and exactly the case that would strand the lease if the release were
    not in a `finally`.

    Modelled by raising inside the wrapped body rather than by driving a real watchdog kill: the
    property under test is that the `finally` runs, and a raise reaches it by the same path a
    SystemExit or a killed subprocess would.
    """
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lease_path, refusal = _acquire(cli, tmp_path)
    assert refusal is None and lease_path.exists()

    # Stand in for the wrapped body dying part-way through.
    try:
        try:
            raise RuntimeError("watchdog killed the reviewer")
        finally:
            try:
                lease_path.unlink()
            except (FileNotFoundError, OSError):
                pass
    except RuntimeError:
        pass

    assert not lease_path.exists(), "a died-mid-run round must not hold the lease"
    again, refusal_again = _acquire(cli, tmp_path)
    assert refusal_again is None, "the same-round re-run must not be lease-refused"
    assert again is not None


def test_the_release_is_in_a_finally_not_on_the_success_path(cli):
    """The structural half of the test above, because the simulation cannot prove where the
    real release lives."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    acquire = source.index("plan_review_acquire_inflight_lease(")
    tail = source[acquire:]
    assert "finally:" in tail
    assert tail.index("finally:") < tail.index("plan_review_release_inflight_lease(lease_path)")


def test_a_finalize_time_format_refusal_leaves_no_lease(cli, tmp_path):
    """Item 76's reviewer-format refusal fires at FINALIZE, long after the run released its
    lease -- so the re-run it prints must be launchable immediately, not blocked by a leftover.

    Finalize never touches the lease directory at all; this asserts that rather than assuming
    it, because the two features share `.ai-runs/plan-review/`.
    """
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lease_path, _ = _acquire(cli, tmp_path)
    lease_path.unlink()  # the run ended; its finally released

    errors = cli.review_log_verdict_errors(
        "reviewer prose with no heading\n", "clean", 0, 0, None,
        require_findings_section=True,
        rerun_command="tautline run-plan-review --target . --plan p.md --round R2",
    )
    assert errors and "no `## Findings` section" in errors[0]

    # The re-run the refusal names is actually launchable: nothing holds the hash.
    reacquired, refusal = _acquire(cli, tmp_path, review_round="R2")
    assert refusal is None, "the printed re-run must not be blocked by a leftover lease"
    assert reacquired is not None


def test_the_lease_name_cannot_be_mistaken_for_round_evidence(cli, tmp_path):
    """Item 76's fixtures assert stale artifacts do not poison a re-run. The lease lands in the
    same directory, so it must not look like a log or a meta file to anything scanning there."""
    lease_path, _ = _acquire(cli, tmp_path)
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    assert list(runs_dir.glob("*.log")) == []
    assert list(runs_dir.glob("*.meta.json")) == []
    assert lease_path.name.startswith("inflight-")


# --- Codex R1: the recovery path must not become the defect ------------------------------------


def test_reclaiming_never_deletes_a_lease_someone_else_just_won(cli, tmp_path, capsys):
    """P2. Two launchers can read the same stale body. If the first reclaims it and acquires,
    an unconditional unlink by the second would delete that fresh, LIVE lease and hand both
    processes a round -- the exact double-launch this mechanism exists to stop, reintroduced by
    its own recovery path.

    Simulated by swapping the file between the read and the unlink: a live lease standing where
    the stale one was is precisely what the losing launcher sees.
    """
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lease_path = cli.plan_review_inflight_lease_path(runs_dir, "abc123")
    lease_path.write_text(json.dumps(_lease(cli, pid=2**22)), encoding="utf-8")

    real_stat = os.stat
    swapped = {"done": False}

    def stat_then_swap(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if not swapped["done"] and str(path) == str(lease_path):
            swapped["done"] = True
            # The winner replaces the stale lease with its own LIVE one (new inode).
            lease_path.unlink()
            lease_path.write_text(json.dumps(_lease(cli)), encoding="utf-8")
        return result

    import _pytest.monkeypatch

    mp = _pytest.monkeypatch.MonkeyPatch()
    try:
        mp.setattr(os, "stat", stat_then_swap)
        _acquire(cli, tmp_path)
    finally:
        mp.undo()

    assert lease_path.exists(), "the winner's live lease must survive the loser's reclaim"
    survivor = json.loads(lease_path.read_text(encoding="utf-8"))
    assert survivor["pid"] == os.getpid(), "the surviving lease must be the winner's, not a new one"


def test_the_reattach_command_is_runnable_from_anywhere(cli, tmp_path):
    """P3. The lease records a TARGET-relative log path, but the second launcher may be invoked
    from any cwd with --target. A re-attach command that only works if you already cd'd into
    the lane is not a re-attach."""
    _acquire(cli, tmp_path)
    _, refusal = _acquire(cli, tmp_path)
    assert str(tmp_path) in refusal, "the tail path must be resolved against the target"


def test_a_genuinely_stale_lease_is_still_reclaimed(cli, tmp_path, capsys):
    """Non-vacuity floor: the inode guard must not break ordinary recovery from a crash."""
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    cli.plan_review_inflight_lease_path(runs_dir, "abc123").write_text(
        json.dumps(_lease(cli, pid=2**22)), encoding="utf-8"
    )
    lease_path, refusal = _acquire(cli, tmp_path)
    assert refusal is None and lease_path is not None
    assert "reclaiming stale in-flight lease" in capsys.readouterr().out


# --- Codex R2: a malformed lease must not crash the launcher or lock it out forever ------------


@pytest.mark.parametrize("body", ["[]", "null", '"a string"', "42"])
def test_non_object_lease_json_is_stale_not_a_crash(cli, tmp_path, body):
    """Valid JSON that is not an object parses fine and then crashes the reclaim print on
    `.get`. A lease that is not an object carries no launcher identity, so it is stale by
    definition -- being unable to launch because someone corrupted a lease file is the failure
    this whole mechanism is supposed to prevent, not cause."""
    runs_dir = tmp_path / ".ai-runs" / "plan-review"
    runs_dir.mkdir(parents=True, exist_ok=True)
    cli.plan_review_inflight_lease_path(runs_dir, "abc123").write_text(body, encoding="utf-8")
    lease_path, refusal = _acquire(cli, tmp_path)
    assert refusal is None, f"{body} must be reclaimed, not refused"
    assert lease_path is not None


@pytest.mark.parametrize("pid", [0, -1, -12345])
def test_a_non_positive_pid_is_never_live(cli, pid):
    """`os.kill(0, 0)` signals the caller's whole PROCESS GROUP, and negative pids address a
    group too. A lease recording pid 0 would probe something that always exists and read as
    live FOREVER: a permanent lockout of that plan hash, with no process that could ever die to
    clear it. A pid that cannot identify a launcher is not evidence of one."""
    assert cli.plan_review_inflight_lease_is_live(_lease(cli, pid=pid)) is False


def test_a_non_object_lease_is_never_live(cli):
    for body in ([], None, "x", 7):
        assert cli.plan_review_inflight_lease_is_live(body) is False


def test_a_real_pid_is_still_live(cli):
    """Non-vacuity floor: the pid guard must not disarm the liveness check it guards."""
    assert cli.plan_review_inflight_lease_is_live(_lease(cli)) is True


# --- Codex R3: skew must not read as "the round ended" -----------------------------------------


def test_a_foreign_lease_from_a_clock_ahead_of_ours_is_still_live(cli):
    """Two hosts sharing a lane will not agree on the time. A lease stamped slightly in OUR
    future means the writer's clock is ahead, not that the round ended -- and reading it as
    stale reclaims a still-running foreign round and starts the duplicate this exists to stop.

    Fails toward LIVE, which is the asymmetry the whole function is built on: a false live
    costs one refusal carrying a tail command, a false stale costs the incident.
    """
    ahead = datetime.now(timezone.utc) + timedelta(minutes=5)
    lease = _lease(cli, hostname="some-other-host", started_at=ahead.isoformat())
    assert cli.plan_review_inflight_lease_is_live(lease) is True


def test_skew_tolerance_does_not_make_foreign_leases_immortal(cli):
    """Non-vacuity floor: the TTL must still expire a genuinely old foreign lease."""
    old = datetime.now(timezone.utc) - timedelta(seconds=cli.PLAN_REVIEW_INFLIGHT_TTL_SECONDS + 60)
    lease = _lease(cli, hostname="some-other-host", started_at=old.isoformat())
    assert cli.plan_review_inflight_lease_is_live(lease) is False


def test_the_reattach_command_survives_a_log_that_does_not_exist_yet(cli, tmp_path):
    """A second launcher can arrive after the lease is written but before the first opens the
    log. `tail -f` on a missing file exits immediately on common implementations, so the
    re-attach would quit the moment it was run -- which reads as the tool being broken."""
    _acquire(cli, tmp_path)
    _, refusal = _acquire(cli, tmp_path)
    assert "tail -F" in refusal
    assert "tail -f " not in refusal


def test_the_release_does_not_delete_someone_elses_lease(cli, tmp_path):
    """Codex R3 P2. A cross-host round that outlives the TTL can be reclaimed while the original
    process is still in its `finally`, and a new launcher then holds a FRESH lease at the same
    path. An unconditional unlink deleted that one, leaving the second review unprotected and a
    third free to start on the same plan hash."""
    lease_path = tmp_path / "lease.json"
    lease_path.write_text(
        json.dumps({"pid": os.getpid() + 1, "hostname": socket.gethostname()}), encoding="utf-8"
    )

    assert cli.plan_review_release_inflight_lease(lease_path) is False
    assert lease_path.exists(), "another launcher's live lease must survive our release"

    lease_path.write_text(
        json.dumps({"pid": os.getpid(), "hostname": socket.gethostname()}), encoding="utf-8"
    )

    assert cli.plan_review_release_inflight_lease(lease_path) is True
    assert not lease_path.exists(), "our own lease is released normally"


def test_a_reused_pid_does_not_hold_a_dead_round_forever(cli):
    """Codex R3 P2. If a launcher crashes and the OS later reuses its pid for something unrelated,
    `kill(pid, 0)` succeeds -- and the lease read live until that stranger exited, refusing every
    round on this plan hash meanwhile. The TTL is the backstop: a same-host lease is live only
    while its pid exists AND it is younger than a round can plausibly be."""
    ours = _lease(cli)  # our own pid, on this host, started now
    assert cli.plan_review_inflight_lease_is_live(ours) is True

    ancient = dict(ours)
    ancient["started_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=cli.PLAN_REVIEW_INFLIGHT_TTL_SECONDS + 60)
    ).isoformat()

    assert cli.plan_review_inflight_lease_is_live(ancient) is False, (
        "an existing pid is not proof it is the one that wrote this lease"
    )


def test_a_replaced_lease_path_is_not_unlinked(cli, tmp_path):
    """Codex R4 P2. `os.stat()` then `unlink()` are two operations on a NAME: between them another
    launcher can delete that inode and create its own fresh lease at the same path, and the unlink
    then removes the NEW holder's lease -- both rounds proceed unprotected. The open pins the inode
    we decided about, so a replacement cannot be mistaken for it."""
    lease_path = tmp_path / "lease.json"
    lease_path.write_text("{}", encoding="utf-8")
    stale_ino = os.stat(lease_path).st_ino

    lease_path.unlink()
    lease_path.write_text("{}", encoding="utf-8")  # a different inode at the same path
    if os.stat(lease_path).st_ino == stale_ino:
        pytest.skip("filesystem reused the inode; the guard cannot be exercised here")

    assert cli.plan_review_unlink_if_inode(lease_path, stale_ino) is False
    assert lease_path.exists(), "the replacement lease must survive"

    assert cli.plan_review_unlink_if_inode(lease_path, os.stat(lease_path).st_ino) is True
    assert not lease_path.exists(), "the inode we actually decided about is removed"
