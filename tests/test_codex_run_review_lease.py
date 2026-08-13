"""Item 68 PR4: one recorded review round per checkout at a time.

A second `codex-run` against the same checkout spends two reviewer invocations against one budget
and races to write the same evidence log. This is the lease that stops it.
"""

from __future__ import annotations

import os

import pytest


def _holder(**overrides) -> dict:
    base = {"session_id": "other-session", "pid": 4242, "started_at": "2026-08-12T07:00:00Z"}
    base.update(overrides)
    return base


# --- containment ------------------------------------------------------------------------------


def test_the_lease_lives_under_the_reviewed_target(cli, tmp_path) -> None:
    """`codex-run --target /other/worktree` reviews over there and must lease over there -- not in
    the caller's cwd. Resolved through the shared containment resolver rather than a hand-rolled
    join, so escapes refuse the same way they do everywhere else."""
    path = cli.codex_run_review_lease_path(tmp_path)

    assert path is not None
    assert str(path).startswith(str(tmp_path)), "the lease belongs to the reviewed checkout"
    assert path.name.endswith(".json")


# --- acquisition ------------------------------------------------------------------------------


def _acquire(cli, monkeypatch, tmp_path, *, status, holder=None):
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(
        cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1}
    )
    monkeypatch.setattr(cli, "occupancy_acquire", lambda *a, **k: (status, holder))
    return cli.codex_run_acquire_review_lease(tmp_path, "review-abc")


@pytest.mark.parametrize("status", ["acquired", "refreshed", "reclaimed", "unresolved", "unavailable"])
def test_every_status_but_conflict_proceeds(cli, monkeypatch, tmp_path, status) -> None:
    """A lease helper outage must not block review -- the round is the valuable thing here, and a
    coordination aid that cannot coordinate should get out of the way."""
    _path, refusal = _acquire(cli, monkeypatch, tmp_path, status=status)

    assert refusal is None


def test_a_running_round_refuses_with_both_ways_out(cli, monkeypatch, tmp_path) -> None:
    _path, refusal = _acquire(cli, monkeypatch, tmp_path, status="conflict", holder=_holder())

    assert refusal is not None
    assert refusal.startswith("codex_run_error:"), "the existing walker prefix, no new one"
    assert "other-session" in refusal and "4242" in refusal, "name who holds it"
    assert "wait for" in refusal.lower() or "worktree add" in refusal
    assert "worktree add" in refusal, "the second continuation must be runnable"
    assert "rm " in refusal, "and say how to clear a lease whose round is gone"


def test_a_raising_lease_layer_never_blocks_review(cli, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 1})

    def _boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(cli, "occupancy_acquire", _boom)

    path, refusal = cli.codex_run_acquire_review_lease(tmp_path, "review-abc")

    assert (path, refusal) == (None, None)


# --- the owner distinction --------------------------------------------------------------------


def test_the_wrapper_pid_is_probed_on_purpose(cli, monkeypatch, tmp_path) -> None:
    """The one place probing the invocation is CORRECT: the wrapper IS the invocation and the
    lease's lifetime is exactly the wrapper's. The lane lease is the opposite case, where probing
    the invocation was the v1 bug -- same mechanism, different holder, which is why `owner` had to
    become a record field."""
    seen = {}

    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    monkeypatch.setattr(
        cli, "occupancy_session_identity", lambda: {"session_id": "me", "pid": 999999}
    )

    def capture(path, identity, now, **kwargs):
        seen.update({"identity": identity, "kwargs": kwargs})
        return "acquired", None

    monkeypatch.setattr(cli, "occupancy_acquire", capture)

    cli.codex_run_acquire_review_lease(tmp_path, "review-abc")

    assert seen["identity"]["pid"] == os.getpid(), "the wrapper's pid, not the session's"
    assert seen["kwargs"]["owner"] == "review-abc"
    assert seen["kwargs"]["ttl_minutes"] == 90


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


def test_the_release_is_in_a_finally(cli) -> None:
    """A killed or crashed round must free its lease -- those are the failure modes that most need
    a clean re-run. Pinned at the source because no output assertion can see an ordering."""
    import inspect

    source = inspect.getsource(cli.codex_run)
    acquire = source.index("codex_run_acquire_review_lease")

    assert "finally:" in source[acquire:]
    assert "occupancy_release(review_lease_path, review_lease_identity)" in source[acquire:]


def test_a_non_recorded_invocation_takes_no_lease(cli) -> None:
    """Plan test 5. Nothing is being spent that a second run could waste."""
    import inspect

    source = inspect.getsource(cli.codex_run)
    acquire = source.index("codex_run_acquire_review_lease")
    guard = source.index("if should_record:")

    # The acquisition lives INSIDE the recorded branch, so an unrecorded invocation never reaches
    # it -- a stronger guarantee than ordering against the `log_path is None` early return, which
    # is where this test used to look. Codex R1 P3 moved the acquisition above the start evidence,
    # and that move is what made the old positional assertion wrong while the behaviour stayed
    # right: the lease is taken only where a round is actually spent.
    assert guard < acquire, "the lease is taken only on the recorded path"
    recorded_block = source[guard:]
    indent = "        "  # inside `if should_record:`
    acquire_line = next(
        line for line in recorded_block.splitlines()
        if "codex_run_acquire_review_lease" in line and "def " not in line
    )
    assert acquire_line.startswith(indent), "and at that branch's indentation, not above it"


def test_the_lease_is_taken_before_the_start_evidence(cli) -> None:
    """Codex R1 P3. A conflicting round used to reach the refusal only AFTER printing
    `review_evidence_log` and writing an `implementation_review_started` event -- so the
    observability trail carried a started review pointing at a log that was never written."""
    import inspect

    source = inspect.getsource(cli.codex_run)
    acquire = source.index("codex_run_acquire_review_lease")

    assert acquire < source.index('print(f"review_evidence_log:')
    assert acquire < source.index('event="implementation_review_started"')


def test_the_inactive_spec_warning_still_concatenates(cli) -> None:
    """Not a review finding about the feature -- a bug my own E501 wrap introduced. Splitting the
    string with a comma turned `+ "; ".join(...)` into unary plus on a str, so a repo with
    pre-existing inactive-scenario debt got a TypeError instead of a non-blocking warning. A lint
    fix that changes runtime behaviour is a code change wearing a formatting hat."""
    import inspect

    source = inspect.getsource(cli.codex_run)

    assert '"(not blocking) "\n' in source or "(not blocking) " in source
    assert '"(not blocking)",\n' not in source, "the comma that broke the concatenation"
