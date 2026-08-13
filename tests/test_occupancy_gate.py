"""Item 68 PR2: session<->worktree occupancy at lane start and session start.

Two sessions editing one worktree overwrite each other's files with no error and no way to tell
whose change survived. PR1 shipped the lease primitives with zero callers; this is where they get
their teeth.
"""

import pytest


def _adapter(**occupancy) -> dict:
    return {"fleet": {"enabled": True, "occupancy": {**occupancy}}}


# --- effective enablement -------------------------------------------------------------------


def test_the_master_fleet_switch_still_turns_occupancy_off(cli) -> None:
    """A lane that turned the fleet governor off did not agree to a new coordination gate
    appearing underneath it. One switch that means what it says."""
    assert cli.occupancy_enabled({"fleet": {"enabled": False}}) is False
    assert cli.occupancy_enabled(
        {"fleet": {"enabled": False, "occupancy": {"enabled": True}}}
    ) is False


def test_occupancy_can_be_turned_off_on_its_own(cli) -> None:
    assert cli.occupancy_enabled(_adapter(enabled=False)) is False
    assert cli.occupancy_enabled({}) is True, "on by default"


def test_a_partial_occupancy_object_keeps_its_siblings_defaults(cli) -> None:
    """A shallow {**DEFAULT_FLEET, **raw} replaces `occupancy` wholesale, so an adapter setting
    one key would silently lose the other three to ABSENCE rather than to their defaults -- and
    the validation would then be judging keys nobody wrote."""
    cfg = cli.fleet_config({"fleet": {"occupancy": {"mode": "observe"}}})["occupancy"]

    assert cfg["mode"] == "observe"
    assert cfg["primaryCheckout"] == "report", "sibling kept its default, not lost"
    assert cfg["ttlMinutes"] == cli.DEFAULT_OCCUPANCY["ttlMinutes"]
    assert cfg["enabled"] is True


@pytest.mark.parametrize(
    "bad, fragment",
    [
        ({"mode": "nope"}, "fleet.occupancy.mode"),
        ({"primaryCheckout": "nope"}, "fleet.occupancy.primaryCheckout"),
        ({"ttlMinutes": 0}, "fleet.occupancy.ttlMinutes"),
        ({"ttlMinutes": True}, "fleet.occupancy.ttlMinutes"),
        ({"enabled": "yes"}, "fleet.occupancy.enabled"),
    ],
)
def test_a_malformed_occupancy_key_refuses_by_name(cli, bad, fragment) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.fleet_config({"fleet": {"occupancy": bad}})

    assert fragment in str(exc.value), "the refusal names the key it is about"


# --- the lane-start gate --------------------------------------------------------------------


def _gate(cli, monkeypatch, tmp_path, *, status, data, mode_holder=None):
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1})
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(
        cli, "occupancy_acquire", lambda *a, **k: (status, mode_holder)
    )
    return cli.occupancy_gate(data, tmp_path)


@pytest.mark.parametrize(
    "status", ["acquired", "refreshed", "reclaimed", "unresolved", "unavailable"]
)
def test_every_status_but_conflict_proceeds(cli, monkeypatch, tmp_path, status) -> None:
    """FAIL-OPEN except on a proven conflict. A lease we could not read, could not arbitrate, or
    could not identify ourselves for is a coordination aid that did not work -- and a coordination
    aid must never strand a lane."""
    assert _gate(cli, monkeypatch, tmp_path, status=status, data={}) == 0


def test_a_live_peer_refuses_in_refuse_mode(cli, monkeypatch, tmp_path, capsys) -> None:
    rc = _gate(
        cli, monkeypatch, tmp_path, status="conflict", data={},
        mode_holder={"session_id": "other", "branch": "feat/theirs"},
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "occupancy_conflict:" in err
    assert "other" in err and "feat/theirs" in err, "name who holds it and where"
    # ONE message carrying its own continuation. Splitting the refusal from its way out left the
    # refusal line a dead end, which is exactly what the refusal walker checks for.
    assert "worktree add" in err, "the way out must be runnable, not advice"
    assert "tautline lane-start" in err


def test_observe_mode_reports_and_continues(cli, monkeypatch, tmp_path, capsys) -> None:
    rc = _gate(
        cli, monkeypatch, tmp_path, status="conflict", data=_adapter(mode="observe"),
        mode_holder={"session_id": "other", "branch": "feat/theirs"},
    )

    assert rc == 0
    assert "observe mode" in capsys.readouterr().err


def test_a_raising_lease_layer_never_strands_the_lane(cli, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1})
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")

    def _boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(cli, "occupancy_acquire", _boom)

    assert cli.occupancy_gate({}, tmp_path) == 0
    # A status line, not a refusal: this path CONTINUES, so it must not wear a gate prefix the
    # walker will hold to the continuation contract.
    assert "occupancy_status:" in capsys.readouterr().err


def test_a_checkout_with_no_git_dir_proceeds(cli, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: None)

    assert cli.occupancy_gate({}, tmp_path) == 0


def test_the_gate_runs_before_any_generated_write(cli) -> None:
    """A refusal that fires after this lane has written into a checkout another session is using
    has not PREVENTED the collision -- it has recorded that it happened. Pinned at the source
    because no output assertion can see an ordering."""
    import inspect

    source = inspect.getsource(cli.lane_start)
    gate = source.index("occupancy_gate(data, target)")

    assert "ensure_lane_state(data, target)" in source[:gate]
    assert source.index("write_work_profile_lock") > gate


# --- the SessionStart seam ------------------------------------------------------------------


def _record(cli, monkeypatch, tmp_path, *, data, status="acquired"):
    seen = []
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1})
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(
        cli, "occupancy_acquire", lambda *a, **k: seen.append(True) or (status, None)
    )
    cli.occupancy_record_session(data, tmp_path)
    return seen


def test_a_lane_with_the_startup_check_off_still_leaves_a_trace(cli, monkeypatch, tmp_path):
    """R1/P2: 'every session leaves a trace' has to hold for lanes that turned the startup CHECK
    off -- those are exactly the lanes most likely to have several sessions in one checkout, and a
    peer record that only exists where the check is on is a record with a hole in the shape of the
    problem. Pinned at the source, because the ordering is the whole point."""
    import inspect

    source = inspect.getsource(cli.lane_status)
    record = source.index("occupancy_record_session(data, root)")
    early_return = source.index('if cfg["startupCheck"] == "off" and hook_mode:')

    assert record < early_return, "acquisition must run before the startupCheck early return"


def test_turning_occupancy_off_does_stop_the_recording(cli, monkeypatch, tmp_path) -> None:
    """Turning off a status REPORT is not the same as opting out of coordination.
    `fleet.occupancy.enabled` is how a lane says the latter, and it must actually be honoured."""
    assert _record(cli, monkeypatch, tmp_path, data=_adapter(enabled=False)) == []
    assert _record(cli, monkeypatch, tmp_path, data={"fleet": {"enabled": False}}) == []
    assert _record(cli, monkeypatch, tmp_path, data={}) == [True], "on by default, it records"


def test_the_seam_reports_a_conflict_but_never_refuses(cli, monkeypatch, tmp_path, capsys) -> None:
    """`lane-status` runs as a hook on every session start and must stay exit 0 on every path.
    Refusing belongs to `lane-start`, which a human ran on purpose and can answer."""
    _record(cli, monkeypatch, tmp_path, data={}, status="conflict")

    assert "occupancy_status: conflict" in capsys.readouterr().err


def test_the_seam_swallows_everything(cli, monkeypatch, tmp_path) -> None:
    """A hook that raises is a hook that breaks session start."""
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1})
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")

    def _boom(*a, **k):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(cli, "occupancy_acquire", _boom)

    cli.occupancy_record_session({}, tmp_path)  # must not raise


# --- the two modes the schema advertises ----------------------------------------------------


def test_auto_worktree_creates_the_way_out_instead_of_naming_it(cli, monkeypatch, tmp_path, capsys):
    """Codex R1 P2: `auto-worktree` was schema-valid but fell through to the plain refusal, so a
    lane that asked to be PLACED was merely blocked. It still returns non-zero -- this process is
    rooted in the old checkout and cannot move itself -- but the worktree exists by the time the
    message is read."""
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda cmd, **k: calls.append(cmd) or (0, "", ""))

    rc = _gate(
        cli, monkeypatch, tmp_path, status="conflict", data=_adapter(mode="auto-worktree"),
        mode_holder={"session_id": "other", "branch": "feat/theirs"},
    )

    assert rc == 1, "the lane must re-run in the new checkout"
    assert any("worktree" in " ".join(c) and "add" in c for c in calls), "it actually creates one"
    err = capsys.readouterr().err
    assert "occupancy_autoplaced:" in err
    assert "tautline lane-start --target" in err, "and says where to re-run"


def test_auto_worktree_falls_back_to_naming_it_when_creation_fails(
    cli, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "run_command", lambda cmd, **k: (1, "", "fatal: already exists"))

    rc = _gate(
        cli, monkeypatch, tmp_path, status="conflict", data=_adapter(mode="auto-worktree"),
        mode_holder={"session_id": "other", "branch": "feat/theirs"},
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "occupancy_conflict:" in err
    assert "worktree add" in err, "a failed placement still leaves a runnable way out"


def test_primary_checkout_refuse_keeps_lanes_out_of_a_free_shared_tree(
    cli, monkeypatch, tmp_path, capsys
):
    """Codex R1 P2: `primaryCheckout` was validated and never read. It is a DIFFERENT question
    from the conflict gate -- not 'is a peer here now' but 'is this tree reserved as a stable
    reference' -- so it applies even when the checkout is free."""
    monkeypatch.setattr(cli, "occupancy_is_primary_checkout", lambda t: True)

    rc = _gate(
        cli, monkeypatch, tmp_path, status="acquired", data=_adapter(primaryCheckout="refuse"),
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "occupancy_primary_checkout:" in err
    assert "worktree add" in err and "primaryCheckout: report" in err, "both ways out are named"


def test_primary_checkout_report_is_the_default_and_only_names_it(
    cli, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "occupancy_is_primary_checkout", lambda t: True)

    assert _gate(cli, monkeypatch, tmp_path, status="acquired", data={}) == 0
    assert "primary checkout" in capsys.readouterr().out


def test_a_linked_worktree_is_never_the_primary_checkout(cli, monkeypatch, tmp_path) -> None:
    """A linked worktree's --git-dir sits INSIDE the common dir; the primary checkout's IS the
    common dir. That is the question git itself answers, and it does not depend on naming."""
    monkeypatch.setattr(
        cli, "run_git",
        lambda t, a: "/repo/.git/worktrees/lane" if "--absolute-git-dir" in a else "/repo/.git",
    )

    assert cli.occupancy_is_primary_checkout(tmp_path) is False

    monkeypatch.setattr(cli, "run_git", lambda t, a: "/repo/.git")

    assert cli.occupancy_is_primary_checkout(tmp_path) is True


def test_observe_mode_still_honours_a_reserved_primary_checkout(
    cli, monkeypatch, tmp_path, capsys
):
    """Codex R2 P2. `observe` says 'do not refuse me for a PEER being here'; it does not say 'let
    me work in a tree the adapter reserved'. Returning 0 straight out of the observe branch
    skipped the primary-checkout question entirely, so the weaker setting silently disabled the
    stronger one."""
    monkeypatch.setattr(cli, "occupancy_is_primary_checkout", lambda t: True)

    rc = _gate(
        cli, monkeypatch, tmp_path, status="conflict",
        data=_adapter(mode="observe", primaryCheckout="refuse"),
        mode_holder={"session_id": "other", "branch": "feat/theirs"},
    )

    assert rc == 1, "the reserved tree still refuses"
    err = capsys.readouterr().err
    assert "observe mode, continuing" in err, "the peer conflict was still only observed"
    assert "occupancy_primary_checkout:" in err, "and the reservation still refused"
