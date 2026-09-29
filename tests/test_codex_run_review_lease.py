"""Item 68 PR4: one recorded review round per checkout at a time.

A second `codex-run` against the same checkout spends two reviewer invocations against one budget
and races to write the same evidence log. This is the lease that stops it.
"""

from __future__ import annotations

import os



def _holder(**overrides) -> dict:
    base = {"session_id": "other-session", "pid": 4242, "started_at": "2026-08-12T07:00:00Z"}
    base.update(overrides)
    return base


# --- containment ------------------------------------------------------------------------------


# --- acquisition ------------------------------------------------------------------------------


def _acquire(cli, monkeypatch, tmp_path, *, status, holder=None):
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(
        cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1}
    )
    monkeypatch.setattr(cli, "occupancy_acquire", lambda *a, **k: (status, holder))
    return cli.codex_run_acquire_review_lease(tmp_path, "review-abc")


# --- the owner distinction --------------------------------------------------------------------


def test_two_runs_of_one_session_do_not_share_a_lease(cli, tmp_path) -> None:
    """Plan test 3, first direction: a second concurrent run from the SAME session has a different
    run id, so it must not inherit the first round's lease."""
    from datetime import datetime, timezone

    from tautline_methodology.occupancy import occupancy_acquire

    path = tmp_path / "review-lease.json"
    now = datetime.now(timezone.utc)
    identity = {"session_id": "s1", "pid": os.getpid()}

    first, _ = occupancy_acquire(path, identity, now, ttl_minutes=90, owner="review-1")
    assert first == "acquired"

    second, holder = occupancy_acquire(path, identity, now, ttl_minutes=90, owner="review-2")

    assert second == "conflict", "one session, two rounds, one checkout"
    assert holder is not None and holder.get("owner") == "review-1"


def test_the_same_run_refreshes_rather_than_conflicting(cli, tmp_path) -> None:
    """Plan test 3, second direction: a round that re-enters its own lease is not its own peer."""
    from datetime import datetime, timezone

    from tautline_methodology.occupancy import occupancy_acquire

    path = tmp_path / "review-lease.json"
    now = datetime.now(timezone.utc)
    identity = {"session_id": "s1", "pid": os.getpid()}

    occupancy_acquire(path, identity, now, ttl_minutes=90, owner="review-1")
    again, _ = occupancy_acquire(path, identity, now, ttl_minutes=90, owner="review-1")

    assert again == "refreshed"


def test_a_dead_round_is_reclaimed(cli, tmp_path) -> None:
    """A wrapper that died holds nothing: its pid is gone, so the next round takes the lease."""
    from datetime import datetime, timezone

    from tautline_methodology.occupancy import occupancy_acquire

    path = tmp_path / "review-lease.json"
    now = datetime.now(timezone.utc)

    occupancy_acquire(
        path, {"session_id": "s1", "pid": 2**22}, now, ttl_minutes=90, owner="review-dead"
    )
    status, _ = occupancy_acquire(
        path, {"session_id": "s2", "pid": os.getpid()}, now, ttl_minutes=90, owner="review-new"
    )

    assert status == "reclaimed"
