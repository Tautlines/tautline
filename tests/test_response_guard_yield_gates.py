"""Item 83 PR2 -- the state-based yield gates on the Stop boundary.

Two RCA shapes converge here.

The STALLED-MONITOR shape: a detached background run never re-invokes anyone, so a turn that ends
while one is live hands the result to nobody, and a turn that ends after one finished without
reading its terminal summary reports on an outcome it never consumed.

The SUMMARY-AS-STOP-SIGNAL shape: the `/goal` hook auto-cleared on SUCCESS, the last user message
was an hours-old work directive, and pending work was still on record. Every guard on that boundary
was gated on a LIVE GOAL, so by the time the incident configuration existed, nothing was armed --
a control that reads healthy because something upstream never let it run.

The gates therefore evaluate with no dependence on a live goal, and their false-positive control is
the set of legal EXITS, not an advisory downgrade.
"""

import json
import subprocess
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "generated-adapter-example-saas.json"


def _lane(tmp_path, cli, *, goal_status=None, runs_dir=None, name="lane"):
    """A lane with NO goal ledger by default -- the incident configuration, not the easy one."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    adapter = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if runs_dir is not None:
        adapter.setdefault("laneState", {})["runsDir"] = runs_dir
    (root / ".minervit-ai-delivery.json").write_text(
        json.dumps(adapter, indent=2) + "\n", encoding="utf-8"
    )
    (root / ".ai-work").mkdir(exist_ok=True)
    if goal_status is not None:
        (root / ".ai-work" / "GOAL_RUN.json").write_text(
            json.dumps({"schema": cli.GOAL_RUN_SCHEMA, "goalId": "g1", "status": goal_status})
            + "\n",
            encoding="utf-8",
        )
    return root


def _payload(
    root,
    *,
    last_user="continue the migration work",
    assistant="Done for now.",
    stop_hook_active=False,
):
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "cwd": str(root),
            "last_user_message": last_user,
            "last_assistant_message": assistant,
            "stop_hook_active": stop_hook_active,
        }
    )


def _events(root, runs_dir=".ai-runs"):
    path = root / runs_dir / "guard-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _spawn_sleeper():
    proc = subprocess.Popen(["sleep", "30"])  # noqa: S603,S607
    return proc


def _write_run(
    root, name, *, runs_dir=".ai-runs", pid=None, finished_at=None, read_at=None, observed=None
):
    """A background-run triple the way `background-run` and `monitor-status` actually write it."""
    d = root / runs_dir
    d.mkdir(parents=True, exist_ok=True)
    log = d / name
    log.write_text("output\n", encoding="utf-8")
    if pid is not None:
        (d / f"{name}.pid").write_text(f"{pid}\n", encoding="utf-8")
    meta = {"pid": pid}
    if finished_at:
        meta["finishedAt"] = finished_at
        meta["exitCode"] = 0
    (d / f"{name}.meta.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    if read_at:
        (d / f"{name}.read.json").write_text(
            json.dumps({"readAt": read_at, "finishedAt": observed}) + "\n", encoding="utf-8"
        )
    return log


# --- the background-run gate -------------------------------------------------------------------


def test_a_live_detached_run_blocks_the_yield(cli, tmp_path):
    root = _lane(tmp_path, cli)
    proc = _spawn_sleeper()
    try:
        _write_run(root, "build.log", pid=proc.pid)
        errors = cli.response_guard_background_run_stop_errors(root)
    finally:
        proc.kill()
        proc.wait()
    assert len(errors) == 1
    assert "live detached background run" in errors[0]
    # The refusal must name a command that RUNS AS PRINTED -- the item-48 runnable-continuation
    # convention. A refusal whose remedy has to be reconstructed is a refusal with no exit. The
    # target and the log are both ABSOLUTE, because a session launched in a subdirectory would
    # otherwise resolve `--target .` to its own cwd and act on a different file than the one named.
    assert "tautline monitor-status --target " in errors[0]
    assert str(root) in errors[0]
    assert "build.log" in errors[0]


def test_a_finished_run_nobody_read_blocks_the_yield(cli, tmp_path):
    root = _lane(tmp_path, cli)
    _write_run(root, "build.log", pid=999_999, finished_at="2026-08-14T10:00:00Z")
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert "terminal summary is unread" in errors[0]


def test_reading_the_summary_clears_the_gate(cli, tmp_path):
    root = _lane(tmp_path, cli)
    _write_run(
        root,
        "build.log",
        pid=999_999,
        finished_at="2026-08-14T10:00:00Z",
        read_at="2026-08-14T10:00:05Z",
        observed="2026-08-14T10:00:00Z",
    )
    assert cli.response_guard_background_run_stop_errors(root) == []


def test_a_receipt_for_a_previous_run_of_the_same_log_does_not_clear_it(cli, tmp_path):
    """Relaunching writes a NEW finishedAt to the SAME log name.

    Comparing timestamps alone would let the receipt from the previous run -- written later than
    the older completion it observed -- clear a completion nobody has looked at. The receipt records
    which finish it saw, and only that one counts.
    """
    root = _lane(tmp_path, cli)
    _write_run(
        root,
        "build.log",
        pid=999_999,
        finished_at="2026-08-14T12:00:00Z",
        read_at="2026-08-14T11:00:00Z",
        observed="2026-08-14T10:00:00Z",
    )
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert "terminal summary is unread" in errors[0]


def test_a_stale_pre_upgrade_run_is_ignored(cli, tmp_path):
    """A dead pid with no recorded completion is UNKNOWABLE from here -- a pre-0.82.0 run or one
    whose reaper was lost. Blocking on it is the eternal-nag failure: nothing the lane can do
    clears it, because there is no summary to read."""
    root = _lane(tmp_path, cli)
    _write_run(root, "ancient.log", pid=999_999)
    assert cli.response_guard_background_run_stop_errors(root) == []


def test_the_watchdog_pid_file_is_not_treated_as_work(cli, tmp_path):
    """The watchdog is a timer for its run, not work anyone waits on. Counting it would make every
    timeout-bounded run un-yieldable for the whole of its timeout."""
    root = _lane(tmp_path, cli)
    proc = _spawn_sleeper()
    try:
        d = root / ".ai-runs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "build.log.watchdog.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
        assert cli.response_guard_background_run_stop_errors(root) == []
    finally:
        proc.kill()
        proc.wait()


def test_the_gate_reads_the_lanes_configured_runs_dir(cli, tmp_path):
    """A hardcoded `.ai-runs` scan would let a lane with a configured runsDir escape entirely --
    and report clean while doing so, because it looked in a directory that does not exist."""
    root = _lane(tmp_path, cli, runs_dir="custom-runs")
    proc = _spawn_sleeper()
    try:
        _write_run(root, "build.log", runs_dir="custom-runs", pid=proc.pid)
        errors = cli.response_guard_background_run_stop_errors(root)
    finally:
        proc.kill()
        proc.wait()
    assert len(errors) == 1
    assert "live detached background run" in errors[0]


def test_a_littered_runs_dir_says_what_it_withheld(cli, tmp_path):
    """Truncation that does not admit it is truncation reads as the whole story."""
    root = _lane(tmp_path, cli)
    for index in range(6):
        _write_run(root, f"run{index}.log", pid=999_000 + index, finished_at="2026-08-14T10:00:00Z")
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 4
    assert "3 more background-run finding(s) withheld" in errors[-1]


# --- the pending-work gate ---------------------------------------------------------------------


def test_next_session_next_action_arms_the_gate_with_no_goal_at_all(cli, tmp_path):
    """The incident configuration exactly: no goal ledger, a named next action on record."""
    root = _lane(tmp_path, cli)
    (root / ".ai-continuity").mkdir()
    (root / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "# Handoff\n\n## Next Action\n\nRebase onto experimental and push\n", encoding="utf-8"
    )
    pending = cli.response_guard_pending_work(root)
    assert pending == [("next_session", "Rebase onto experimental and push")]


def test_an_inline_next_action_heading_is_read(cli, tmp_path):
    root = _lane(tmp_path, cli)
    (root / ".ai-continuity").mkdir()
    (root / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "Next Action: finish the release boundary\n", encoding="utf-8"
    )
    assert cli.response_guard_pending_work(root) == [
        ("next_session", "finish the release boundary")
    ]


def test_the_execution_packet_first_unchecked_item_arms_the_gate(cli, tmp_path):
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text(
        "## Queue\n\n- [x] cut the branch\n- [ ] write the tests\n- [ ] ship it\n", encoding="utf-8"
    )
    assert cli.response_guard_pending_work(root) == [("packet", "write the tests")]


def test_the_milestone_ledger_is_the_machine_readable_queue(cli, tmp_path):
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "MILESTONE_RUN.json").write_text(
        json.dumps(
            {
                "schema": cli.MILESTONE_RUN_SCHEMA,
                # The REAL shape `initial_milestone_run` writes: `items`, with the milestone
                # vocabulary. The first version of this fixture invented `milestones` and goal
                # statuses, so it agreed with the reader and both were wrong together -- a fixture
                # written from the same misunderstanding as the code proves nothing.
                "items": [
                    {"index": 1, "title": "M1", "status": "merged"},
                    {"index": 2, "title": "wire the gate", "status": "in_progress"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert cli.response_guard_pending_work(root) == [("queue", "wire the gate")]


def test_an_empty_queue_arms_nothing(cli, tmp_path):
    root = _lane(tmp_path, cli)
    assert cli.response_guard_pending_work(root) == []


def test_the_refusal_enumerates_exactly_the_sources_the_gate_reads(cli, tmp_path, monkeypatch):
    """The claim can never outrun the gate.

    The refusal says the queue was "enumerated empty (...)" and lists the sources. If that list is
    prose, adding a fifth source silently makes the claim false -- the gate would be asserting an
    enumeration it does not perform, which is this program's signature defect. The clause is
    RENDERED from the same registry the reader iterates, so mutating the registry moves the text.
    """
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")

    baseline = cli.response_guard_yield_state_errors(
        root,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=False,
        payload={},
    )["stop.pending_work_unfinished"][0]
    for _key, label, _reader in cli.RESPONSE_GUARD_PENDING_SOURCES:
        assert label in baseline

    monkeypatch.setattr(
        cli,
        "RESPONSE_GUARD_PENDING_SOURCES",
        cli.RESPONSE_GUARD_PENDING_SOURCES + (("stub", "fifth stub source", lambda _root: ""),),
    )
    mutated = cli.response_guard_yield_state_errors(
        root,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=False,
        payload={},
    )["stop.pending_work_unfinished"][0]
    assert "fifth stub source" in mutated
    assert mutated != baseline


# --- the legal exits ---------------------------------------------------------------------------


def test_a_fresh_blocker_record_clears_the_gates(cli, tmp_path, run_cli):
    """The shipped boundary already accepts a fresh blocker record, and a lane holding one is
    ending its turn LEGALLY.

    This exit was missing from the first version of this gate, and the consequence was that every
    goal-active lane with a fresh blocker -- a lane that did exactly what the guard asks -- carried
    a pending-work advisory anyway. The false-refusal class this chain is rationed against,
    produced by the gate meant to ration it. The shipped suite caught it; these tests did not.
    """
    root = _lane(tmp_path, cli, goal_status="in_progress")
    res = run_cli(
        "blocker-declare",
        "--target",
        str(root),
        "--kind",
        "approval-needed",
        "--reason",
        "waiting for customer approval",
    )
    assert res.returncode == 0, res.stderr
    found = cli.response_guard_yield_state_errors(
        root,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=False,
        payload={},
    )
    assert not any(found.values())


def test_a_documented_rotation_exit_clears_the_gates(cli, tmp_path):
    root = _lane(tmp_path, cli, goal_status="in_progress")
    rotation_text = (
        "Context is at 92% and I am rotating now. NEXT_SESSION.md records the exact "
        "fresh-session startup action to resume from."
    )
    # Asserted, not assumed: a fixture the shipped detector does not actually recognise would make
    # this test pass for the wrong reason -- the exit would look honoured while never being taken.
    assert cli.response_guard_has_documented_rotation_exit(rotation_text)
    found = cli.response_guard_yield_state_errors(
        root,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=False,
        payload={},
        last_assistant=rotation_text,
    )
    assert not any(found.values())


def test_a_phrase_check_switched_off_is_not_switched_back_on_by_the_warn_only_clamp(cli):
    """A warn-only clamp is a limit on ENFORCEMENT, never a way to re-enable a disabled check.

    Hoisting the clamp above the phrase-mode lookup -- which is what made it reach state checks --
    turned a lane that had set `phraseChecks: off` into one emitting advisories.
    """
    check_id = next(iter(cli.WAVE3_STOP_CHAIN_WARN_ONLY_CHECKS))
    assert (
        cli.response_guard_effective_check_mode(
            check_id, "phrase", "off", "off", wave3_chain_blocking=False
        )
        == "off"
    )


@pytest.mark.parametrize(
    "exit_kwargs", [{"explicit_user_stop": True}, {"human_discussion_request": True}]
)
def test_the_legal_exits_clear_both_gates(cli, tmp_path, exit_kwargs):
    """The exits ARE the false-positive control, deliberately -- not an advisory downgrade.

    Downgrading instead would leave the incident configuration logging a line and stopping anyway,
    which is the outcome this gate exists to prevent.
    """
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    kwargs = {"explicit_user_stop": False, "human_discussion_request": False}
    kwargs.update(exit_kwargs)
    found = cli.response_guard_yield_state_errors(
        root, stop_hook_active=False, payload={}, **kwargs
    )
    assert not any(found.values())


# --- the stop_hook_active bound ----------------------------------------------------------------


def test_the_first_retry_still_blocks(cli, tmp_path):
    """The one-shot bypass, removed. The old handler returned 0 on the FIRST `stop_hook_active`
    evaluation, above adapter-root resolution -- so one block was the entire guard, and the very
    next evaluation let anything through regardless of lane state."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    found = cli.response_guard_yield_state_errors(
        root,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=True,
        payload={},
    )
    assert found["stop.pending_work_unfinished"]


def test_the_third_consecutive_retry_fails_open_loudly(cli, tmp_path, run_cli):
    """The harness's infinite-loop protection, preserved and BOUNDED rather than removed.

    Asserted through the HOOK, not through one arm's return value: the bound is a property of the
    handler. The first version of this test called `response_guard_yield_state_errors` directly and
    passed while the other three arms went on blocking every retry -- which is an unbounded Stop
    loop, and worse than the one-shot hole the change replaced.
    """
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    payload = _payload(root, stop_hook_active=True)
    for _ in range(2):
        run_cli("response-guard-hook", stdin=payload)
    res = run_cli("response-guard-hook", stdin=payload)
    assert '"decision": "block"' not in res.stdout
    assert "active pending work on record" not in res.stdout
    ids = [event["check_id"] for event in _events(root)]
    assert "stop.state_gate_exhausted_fail_open" in ids


def test_a_non_retry_evaluation_resets_the_counter(cli, tmp_path, run_cli):
    """Resetting only on a CLEAN stand-down would leave the counter at its limit after one blocked
    turn, so the next real block would fail open immediately."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    for _ in range(2):
        cli.response_guard_yield_state_errors(
            root,
            explicit_user_stop=False,
            human_discussion_request=False,
            stop_hook_active=True,
            payload={},
        )
    run_cli("response-guard-hook", stdin=_payload(root))
    assert not cli.response_guard_stop_retry_path(root).exists()


def test_an_unwritable_counter_fails_open_rather_than_looping(cli, tmp_path, monkeypatch):
    root = _lane(tmp_path, cli)
    monkeypatch.setattr(
        cli, "write_text_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    assert cli.response_guard_bump_stop_retries(root) == cli.RESPONSE_GUARD_STOP_RETRY_LIMIT


# --- sibling worktrees -------------------------------------------------------------------------


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)  # noqa: S603,S607


@pytest.fixture
def linked_worktree(tmp_path, cli):
    """A REAL `git worktree add`, not a simulated one -- the resolution being tested is git's."""
    main = _lane(tmp_path, cli, name="main")
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "t")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", "-b", "side", str(linked))
    return main, linked


def test_a_linked_worktree_inherits_the_main_lanes_pending_work(cli, linked_worktree):
    main, linked = linked_worktree
    (main / ".ai-continuity").mkdir(exist_ok=True)
    (main / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "## Next Action\n\nfinish the carve\n", encoding="utf-8"
    )
    pending = cli.response_guard_pending_work(linked)
    assert pending and pending[0][1] == "finish the carve"
    assert "main worktree" in pending[0][0]


def test_worktree_local_state_is_never_overridden_by_the_parents(cli, linked_worktree):
    main, linked = linked_worktree
    (main / ".ai-continuity").mkdir(exist_ok=True)
    (main / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "## Next Action\n\nparent work\n", encoding="utf-8"
    )
    (linked / ".ai-work").mkdir(parents=True, exist_ok=True)
    (linked / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] local work\n", encoding="utf-8")
    assert cli.response_guard_pending_work(linked) == [("packet", "local work")]


def test_a_declared_subagent_worktree_may_end_its_turn(cli, linked_worktree):
    """Stated up front rather than discovered during execution.

    The main-worktree fallback means every linked worktree of an armed lane inherits that arming --
    including the worktree-per-subagent default this framework itself prescribes. Without the
    marker, dispatching a subagent would make it unable to end its turn on work it does not own.
    """
    main, linked = linked_worktree
    (main / ".ai-continuity").mkdir(exist_ok=True)
    (main / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "## Next Action\n\nparent work\n", encoding="utf-8"
    )
    (linked / ".ai-work").mkdir(parents=True, exist_ok=True)
    (linked / ".ai-work" / "WORKTREE_ROLE.json").write_text(
        json.dumps({"role": "subagent", "parent": str(main)}) + "\n", encoding="utf-8"
    )
    found = cli.response_guard_yield_state_errors(
        linked,
        explicit_user_stop=False,
        human_discussion_request=False,
        stop_hook_active=False,
        payload={},
    )
    assert not any(found.values())


def test_a_subagent_worktrees_own_live_run_still_blocks(cli, linked_worktree):
    """The marker suppresses INHERITED arming only. A run this worktree launched is its own."""
    main, linked = linked_worktree
    (linked / ".ai-work").mkdir(parents=True, exist_ok=True)
    (linked / ".ai-work" / "WORKTREE_ROLE.json").write_text(
        json.dumps({"role": "subagent", "parent": str(main)}) + "\n", encoding="utf-8"
    )
    proc = _spawn_sleeper()
    try:
        _write_run(linked, "build.log", pid=proc.pid)
        errors = cli.response_guard_background_run_stop_errors(linked)
    finally:
        proc.kill()
        proc.wait()
    assert len(errors) == 1


def test_the_main_worktree_lookup_is_bounded_and_fails_open(cli, tmp_path):
    """A Stop hook that hangs on git is worse than one that misses inherited state."""
    root = _lane(tmp_path, cli)
    assert cli.response_guard_main_worktree(root) is None


# --- posture and wiring ------------------------------------------------------------------------


def test_both_gates_ship_warn_only_while_the_chain_is_not_blocking(cli):
    """The chain's DECISION 4 posture: every Stop check ships warn-only until the fourth PR lands.

    The clamp used to sit BELOW `if mechanism != "phrase": return "blocking"`, which made it
    unreachable for state checks -- and these two, like the rest of the chain's remaining PRs, are
    state checks. The posture would have been announced and not implemented.
    """
    for check_id in cli.RESPONSE_GUARD_YIELD_CHECK_IDS:
        assert check_id in cli.WAVE3_STOP_CHAIN_WARN_ONLY_CHECKS
        assert (
            cli.response_guard_effective_check_mode(
                check_id, "state", "blocking", "blocking", wave3_chain_blocking=False
            )
            == "advisory"
        )
        # ...and blocking once the chain flips, or the clamp would be a permanent disablement.
        assert (
            cli.response_guard_effective_check_mode(
                check_id, "state", "blocking", "blocking", wave3_chain_blocking=True
            )
            == "blocking"
        )


def test_a_stop_with_pending_work_advises_but_does_not_block_today(cli, tmp_path, run_cli):
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    res = run_cli("response-guard-hook", stdin=_payload(root))
    assert res.returncode == 0
    assert '"decision": "block"' not in res.stdout
    assert "active pending work on record" in res.stdout
    assert "warn-only" in res.stdout


def test_the_gate_events_are_attributed_per_check(cli, tmp_path, run_cli):
    """A shared boolean would credit every block to both gates and make the aggregate ceiling
    unattributable -- a measurement that cannot say which detector spent the budget."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    run_cli("response-guard-hook", stdin=_payload(root))
    fired = {event["check_id"]: event["fired"] for event in _events(root)}
    assert fired.get("stop.pending_work_unfinished") is True
    assert fired.get("stop.background_run_unyielded") is False


def test_product_dev_mode_stands_the_gates_down_and_says_so(cli, tmp_path, run_cli):
    """The whole-handler standdown keeps its contract. A per-gate carve-out would make it
    "whole handler except two gates", which no reader could verify."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    res = run_cli("product-dev-mode", "on", "--target", str(root))
    assert res.returncode == 0, res.stderr
    res = run_cli("response-guard-hook", stdin=_payload(root))
    assert '"decision": "block"' not in res.stdout
    assert "active pending work on record" not in res.stdout
    assert "yield state gates" in res.stdout


def test_monitor_status_writes_the_read_receipt(cli, tmp_path, run_cli):
    """The receipt is what CLEARS the unread-run gate, so it must be written on every path that
    printed a status -- including a failed or stale one. A receipt written only on success would
    leave a lane that correctly diagnosed a failure unable to end its turn."""
    root = _lane(tmp_path, cli)
    log = _write_run(root, "build.log", pid=999_999, finished_at="2026-08-14T10:00:00Z")
    res = run_cli("monitor-status", "--target", str(root), "--log", str(log))
    assert res.returncode == 0, res.stderr
    receipt = json.loads((root / ".ai-runs" / "build.log.read.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == cli.MONITOR_READ_RECEIPT_SCHEMA
    assert receipt["finishedAt"] == "2026-08-14T10:00:00Z"
    assert cli.response_guard_background_run_stop_errors(root) == []


def test_the_terse_null_turn_markers_are_recognised(cli):
    for text in ("No response requested.", "Nothing to do.", "Done for now."):
        assert cli.response_is_terse_no_information(text), text


def test_the_aggregate_harness_actually_runs_the_yield_gates(cli, tmp_path, monkeypatch):
    """A +0.0 that means "never measured" is the defect this program is about.

    The harness evaluates the boundary's arms explicitly, so a new arm contributes zero until it is
    wired in -- and zero-by-construction is indistinguishable from a clean measurement. The same
    omission was caught one release earlier for the recovery-cancellation arm. Proven by MUTATION:
    forcing the yield gate to refuse must move the harness's number, which it can only do if the
    harness calls it.
    """
    repo_root = Path(cli.__file__).resolve().parents[2]
    baseline = cli.stop_guard_aggregate_measure(repo_root)
    assert baseline["blockedLegitimateTurns"] == 0

    monkeypatch.setattr(
        cli,
        "response_guard_yield_state_errors",
        lambda *a, **k: {"stop.pending_work_unfinished": ["injected yield refusal"], "stop.background_run_unyielded": []},
    )
    mutated = cli.stop_guard_aggregate_measure(repo_root)
    assert mutated["blockedLegitimateTurns"] > 0, (
        "forcing the yield gate to refuse did not move the aggregate: the harness is not running "
        "this arm, so the number it reports for this release covers everything except the thing "
        "this release adds."
    )


def test_a_declared_blocker_does_not_excuse_a_live_detached_run(cli, tmp_path):
    """The asymmetry between the two gates, pinned.

    Declaring a blocker is a legitimate way to stop having work in progress. It does not make a
    detached run observable, and yielding with one live leaves exactly the orphan the RCA is about.
    The remedy stays runnable either way -- poll it, or terminate it.
    """
    root = _lane(tmp_path, cli, goal_status="in_progress")
    proc = _spawn_sleeper()
    try:
        _write_run(root, "build.log", pid=proc.pid)
        (root / ".ai-work" / "BLOCKER.json").write_text(
            json.dumps(
                cli.guards_module().blocker_declare_record(
                    kind="approval-needed",
                    reason="fixture: a legally declared blocker, which is not a wake path",
                    artifact=None,
                    goal_id="g1",
                    checked=[],
                )
            ),
            encoding="utf-8",
        )
        found = cli.response_guard_yield_state_errors(
            root, explicit_user_stop=False, human_discussion_request=False,
            stop_hook_active=False, payload={},
        )
    finally:
        proc.kill()
        proc.wait()
    assert found["stop.background_run_unyielded"], "a blocker must not excuse an unwakeable run"
    assert not found["stop.pending_work_unfinished"], "a blocker IS the pending-work exit"


# --- Codex R1 findings, each pinned at the level the defect actually lived ------------------------


def test_retry_exhaustion_stands_down_every_arm_not_just_the_new_ones(cli, tmp_path, run_cli):
    """THE BOUND IS A PROPERTY OF THE HANDLER, NOT OF ONE ARM.

    Applying exhaustion only to the yield gates left the state, legacy and goal-boundary arms
    blocking on every retry -- so removing the old unconditional `stop_hook_active` bypass turned
    an active-goal lane without a fresh blocker into an INFINITE Stop loop, strictly worse than the
    one-shot hole it replaced.
    """
    root = _lane(tmp_path, cli, goal_status="in_progress")
    payload = _payload(root, assistant="I am stopping here.", stop_hook_active=True)
    for _ in range(2):
        run_cli("response-guard-hook", stdin=payload)
    res = run_cli("response-guard-hook", stdin=payload)
    assert '"decision": "block"' not in res.stdout, (
        "the third consecutive retry must fail open for EVERY arm; a blocking arm here is an "
        "unbounded Stop loop"
    )
    assert "stop.state_gate_exhausted_fail_open" in [e["check_id"] for e in _events(root)]


def test_a_real_milestone_ledger_is_read_through_the_hook(cli, tmp_path):
    """The reader used `milestones` and the GOAL terminal statuses; `initial_milestone_run` writes
    `items` with MILESTONE_TERMINAL_STATUSES. A lane whose only pending source was a real ledger
    reported EMPTY -- the machine-readable queue, consulted with the wrong key."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "MILESTONE_RUN.json").write_text(
        json.dumps(
            {
                "schema": cli.MILESTONE_RUN_SCHEMA,
                "items": [
                    {"index": 1, "title": "shipped already", "status": "merged"},
                    {"index": 2, "title": "carve the module", "status": "in_progress"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert cli.response_guard_pending_work(root) == [("queue", "carve the module")]


def test_a_queued_or_merged_item_is_not_pending_work(cli, tmp_path):
    """Fixing only the KEY would have been worse than leaving it: `pr_queued` and `merged` are
    terminal in the milestone vocabulary and absent from the goal one, so every queued or merged
    item would have read as pending."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "MILESTONE_RUN.json").write_text(
        json.dumps(
            {
                "schema": cli.MILESTONE_RUN_SCHEMA,
                "items": [
                    {"index": 1, "title": "a", "status": "merged"},
                    {"index": 2, "title": "b", "status": "pr_queued"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert cli.response_guard_pending_work(root) == []


def test_a_configured_continuity_path_is_read(cli, tmp_path):
    """An adopter with a non-default `continuity.path` writes there, and would otherwise lose the
    continuity source from this gate silently -- precisely when it is their only source."""
    root = _lane(tmp_path, cli)
    adapter = json.loads((root / ".minervit-ai-delivery.json").read_text(encoding="utf-8"))
    adapter.setdefault("continuity", {})["path"] = "handoff/NEXT.md"
    (root / ".minervit-ai-delivery.json").write_text(json.dumps(adapter, indent=2) + "\n", encoding="utf-8")
    (root / "handoff").mkdir()
    (root / "handoff" / "NEXT.md").write_text("## Next Action\n\nresume the carve\n", encoding="utf-8")
    assert cli.response_guard_pending_work(root) == [("next_session", "resume the carve")]


def test_a_subagent_worktree_is_not_exempt_from_its_own_work(cli, linked_worktree):
    """Asserted THROUGH the integrated path, which is where the defect lived.

    The marker returned early from the whole gate, exempting a subagent worktree from its own live
    background run and its own execution packet -- everything, not the inherited state the contract
    names. This gate's own test passed anyway, because it called the low-level background reader
    directly. A test one level below the defect proves the level it tests, not what ships.
    """
    main, linked = linked_worktree
    (linked / ".ai-work").mkdir(parents=True, exist_ok=True)
    (linked / ".ai-work" / "WORKTREE_ROLE.json").write_text(
        json.dumps({"role": "subagent", "parent": str(main)}) + "\n", encoding="utf-8"
    )
    (linked / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] its own work\n", encoding="utf-8")
    found = cli.response_guard_yield_state_errors(
        linked, explicit_user_stop=False, human_discussion_request=False,
        stop_hook_active=False, payload={},
    )
    assert found["stop.pending_work_unfinished"], "a subagent must still answer for its OWN work"


def test_a_reused_pid_does_not_pin_a_finished_run_as_live(cli, tmp_path):
    """No amount of polling clears a refusal keyed on a pid that now belongs to something else --
    a remedy that cannot work. `monitor-status` resolves this from `pidIdentity`; the gate must
    agree with it, or the two disagree about the same run."""
    root = _lane(tmp_path, cli)
    proc = _spawn_sleeper()
    try:
        d = root / ".ai-runs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "build.log").write_text("out\n", encoding="utf-8")
        (d / "build.log.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
        (d / "build.log.meta.json").write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "pidIdentity": "a-command-that-is-no-longer-running",
                    "finishedAt": "2026-08-14T10:00:00Z",
                    "exitCode": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        errors = cli.response_guard_background_run_stop_errors(root)
    finally:
        proc.kill()
        proc.wait()
    assert not any("live detached background run" in e for e in errors)


def test_the_receipt_is_written_when_the_log_is_gone(cli, tmp_path, run_cli):
    """The gate names `monitor-status` as the remedy for an unread completion. If the log was
    deleted while the sidecars remain, that command returned before writing anything, so running
    the prescribed remedy could never clear the finding."""
    root = _lane(tmp_path, cli)
    log = _write_run(root, "build.log", pid=999_999, finished_at="2026-08-14T10:00:00Z")
    log.unlink()
    res = run_cli("monitor-status", "--target", str(root), "--log", str(log))
    assert res.returncode == 0, res.stderr
    assert (root / ".ai-runs" / "build.log.read.json").exists()
    assert cli.response_guard_background_run_stop_errors(root) == []


def test_two_runs_finishing_in_the_same_second_are_told_apart(cli, tmp_path):
    """`finishedAt` is recorded to one-second precision, so two quick runs of the same log are
    indistinguishable by timestamp alone and the older receipt would clear the newer run."""
    root = _lane(tmp_path, cli)
    d = root / ".ai-runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "build.log").write_text("out\n", encoding="utf-8")
    (d / "build.log.pid").write_text("999999\n", encoding="utf-8")
    (d / "build.log.meta.json").write_text(
        json.dumps({"pid": 4242, "finishedAt": "2026-08-14T10:00:00Z", "exitCode": 0}) + "\n",
        encoding="utf-8",
    )
    (d / "build.log.read.json").write_text(
        json.dumps({"readAt": "2026-08-14T10:00:01Z", "finishedAt": "2026-08-14T10:00:00Z", "pid": 4141})
        + "\n",
        encoding="utf-8",
    )
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert "terminal summary is unread" in errors[0]


def test_a_run_in_a_subdirectory_of_the_runs_dir_is_seen(cli, tmp_path):
    """`background-run` treats any DESCENDANT of the configured runsDir as in-scope -- its
    outside-the-runsDir advisory fires only for a log outside it entirely. A top-level-only scan
    meant a run at `.ai-runs/reviews/build.log` was blessed by one half of this feature and
    invisible to the other, with the gate reporting clean because it looked one directory too
    shallow."""
    root = _lane(tmp_path, cli)
    (root / ".ai-runs" / "reviews").mkdir(parents=True, exist_ok=True)
    _write_run(root, "reviews/build.log", pid=999_999, finished_at="2026-08-14T10:00:00Z")
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert "terminal summary is unread" in errors[0]
    # ...and the remedy still names a path that runs as printed from the lane root.
    assert "reviews/build.log" in errors[0]


def test_a_run_that_could_not_spawn_is_still_seen(cli, tmp_path):
    """`background-run` records `finishedAt` and exit 127 for a command that could not start, and
    deliberately writes NO pid sidecar. A pid-only scan was therefore blind to precisely the
    terminal failure most worth catching -- and blind to it silently."""
    root = _lane(tmp_path, cli)
    d = root / ".ai-runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "build.log").write_text("command not found\n", encoding="utf-8")
    (d / "build.log.meta.json").write_text(
        json.dumps({"pid": None, "finishedAt": "2026-08-14T10:00:00Z", "exitCode": 127,
                    "launchError": "No such file or directory"})
        + "\n",
        encoding="utf-8",
    )
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert "terminal summary is unread" in errors[0]


def test_the_done_bar_advisory_is_not_replaced_by_the_generic_one(cli, tmp_path, monkeypatch, capsys):
    """A new control that suppresses an older, MORE SPECIFIC one is a net loss even when it is
    right.

    A terminal goal with unmet definition-of-done conditions makes `response_guard_has_active_goal`
    false while a pending source keeps the yield gate armed, so returning on the yield path
    replaced a diagnostic naming the unmet condition and its remediation with a generic
    "pending work" line.

    Driven through `response_guard_hook` IN-PROCESS rather than through the CLI subprocess: the
    done-bar arm needs a full definitionOfDone lane to speak for real, and a subprocess cannot see
    a stub. This is the integrated handler, which is where the defect was -- one level below it,
    in the combiner, the bug did not exist.
    """
    import argparse
    import io

    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text("## Queue\n\n- [ ] do the thing\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "done_bar_stop_advisory",
        lambda *a, **k: "done_bar_advisory: condition `deploy verified` is unmet; run X",
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(root)))
    assert cli.response_guard_hook(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    # Both must reach the turn: the specific condition AND the pending-work line.
    assert "condition `deploy verified` is unmet" in out
    assert "active pending work on record" in out
    # ...and still as an ADVISORY, never a block: this chain is warn-only until its fourth PR.
    assert '"decision": "block"' not in out


def test_the_done_bar_advisory_still_speaks_when_the_yield_gate_is_quiet(cli, tmp_path, monkeypatch, capsys):
    """Returning early because THIS gate found nothing is the other way a new control swallows an
    older one."""
    import argparse
    import io

    root = _lane(tmp_path, cli)
    monkeypatch.setattr(
        cli, "done_bar_stop_advisory", lambda *a, **k: "done_bar_advisory: condition unmet"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(root)))
    assert cli.response_guard_hook(argparse.Namespace()) == 0
    assert "done_bar_advisory: condition unmet" in capsys.readouterr().out


def test_an_ordinary_bullet_in_the_packet_queue_is_pending_work(cli, tmp_path):
    """`execution_queue_items` is the parser the packet WORK LOOP itself uses, and it accepts an
    ordinary bullet under a queue heading. Recognising only `- [ ]` meant a packet the executor
    happily runs read as empty here -- the gate and the executor disagreeing about the same file."""
    root = _lane(tmp_path, cli)
    (root / ".ai-work" / "EXECUTION_PACKET.md").write_text(
        "## Ordered Tactical Queue\n\n- [x] done already\n- carve the seam\n", encoding="utf-8"
    )
    assert cli.response_guard_pending_work(root) == [("packet", "carve the seam")]


def test_an_empty_next_action_section_does_not_borrow_the_next_one(cli, tmp_path):
    """Continuing past the next heading returned the first content line of an UNRELATED section as
    this lane's next action -- a false advisory today and a false block after the flip, produced by
    a handoff that correctly says it has no next action."""
    root = _lane(tmp_path, cli)
    (root / ".ai-continuity").mkdir()
    (root / ".ai-continuity" / "NEXT_SESSION.md").write_text(
        "## Next Action\n\n## Notes\n\nthis is not a next action\n", encoding="utf-8"
    )
    assert cli.response_guard_pending_work(root) == []


def test_the_remedy_runs_from_a_subdirectory_session(cli, tmp_path):
    """`find_adapter_root` walks UP, so a session launched in a subdirectory got a log path
    relative to the parent adapter while `--target .` resolved to its own cwd: the remedy as
    printed would monitor the wrong path and write a receipt beside it, and the finding would never
    clear. A remedy that silently acts on a different file than the one it names is worse than
    none."""
    root = _lane(tmp_path, cli)
    log = _write_run(root, "build.log", pid=999_999, finished_at="2026-08-14T10:00:00Z")
    errors = cli.response_guard_background_run_stop_errors(root)
    assert len(errors) == 1
    assert str(log) in errors[0]
    assert str(root) in errors[0]
    assert "--target ." not in errors[0]
