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
