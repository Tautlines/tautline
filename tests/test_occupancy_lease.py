"""Session<->worktree occupancy lease: identity, liveness, foreignness, acquire/release (WS0).

Backlog item 68, PR1. The module ships alone, with no caller, because this is where the review
findings cluster: an identity resolver that names the wrong process and a liveness predicate that
is not TOTAL over hostile file data make the whole control INERT -- every lease reads dead, so
nothing is ever refused.

Two claims in this file are the load-bearing ones, and both are proven by running the product code
in SEPARATE PROCESSES rather than by planting a synthetic pid:

* identity is the AGENT SESSION, not the CLI invocation (``os.getpid()``) and not its per-invocation
  shell (``os.getppid()``, measured to be a corpse seconds later);
* a lease is byte-stable across invocations, so a session recognises its OWN lease on re-entry.

A mock cannot fail either way, which is why neither is mocked.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tautline_methodology import occupancy
from tautline_methodology.occupancy import (
    DEFAULT_OCCUPANCY,
    OCCUPANCY_ACQUIRE_STATUSES,
    OCCUPANCY_LEASE_SCHEMA,
    OCCUPANCY_MAX_TTL_MINUTES,
    OCCUPANCY_MODES,
    OCCUPANCY_PRIMARY_CHECKOUT_MODES,
    OCCUPANCY_SESSION_ID_ENV,
    OCCUPANCY_SESSION_PID_ENV,
    occupancy_acquire,
    occupancy_lease_foreignness,
    occupancy_lease_is_live,
    occupancy_read_lease,
    occupancy_release,
    occupancy_session_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
MODULE_PATH = SRC_ROOT / "tautline_methodology" / "occupancy.py"

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
HOST = socket.gethostname()

# A driver run in a SEPARATE interpreter. The point of the whole file: two invocations of this must
# agree, because the CLI is invoked once per command and has to recognise the lease it wrote last
# time. `os.getppid()` -- what v1 of this plan specified -- differs on every invocation.
IDENTITY_DRIVER = """
import json, sys
sys.path.insert(0, sys.argv[1])
from tautline_methodology.occupancy import occupancy_session_identity
sys.stdout.write(json.dumps(occupancy_session_identity(), sort_keys=True))
"""


def _driver(tmp_path: Path) -> Path:
    path = tmp_path / "identity_driver.py"
    path.write_text(IDENTITY_DRIVER, encoding="utf-8")
    return path


def _run_driver(driver: Path, env: dict[str, str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(driver), str(SRC_ROOT)],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _bare_env(tmp_path: Path) -> dict[str, str]:
    """PATH/HOME only: no identity variable of any spelling, so the fallback path is exercised."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"PATH": os.environ["PATH"], "HOME": str(home)}


def _lease(**overrides) -> dict:
    base = {
        "schema": OCCUPANCY_LEASE_SCHEMA,
        "session_id": "session-a",
        "pid": os.getpid(),  # live by construction: it is this test process
        "identity_source": "env",
        "writer_pid": os.getpid(),
        "host": HOST,
        "branch": "feat/x",
        "started_at": NOW.isoformat(),
        "renewed_at": NOW.isoformat(),
        "ttl_minutes": DEFAULT_OCCUPANCY["ttlMinutes"],
    }
    base.update(overrides)
    return base


def _dead_pid() -> int:
    """A pid that is certainly not running: spawned, waited on, and reaped."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# --- 1. identity is the SESSION, not the invocation --------------------------------------------


def test_identity_reads_the_session_env_not_the_invocation(tmp_path):
    env = {"CLAUDE_CODE_SESSION_ID": "uuid-1234", "CLAUDE_PID": str(os.getpid())}
    assert occupancy_session_identity(env) == {
        "session_id": "uuid-1234",
        "pid": os.getpid(),
        "source": "env",
    }


def test_identity_is_byte_identical_across_two_separate_invocations(tmp_path):
    env = _bare_env(tmp_path)
    env["CLAUDE_CODE_SESSION_ID"] = "uuid-1234"
    env["CLAUDE_PID"] = str(os.getpid())
    driver = _driver(tmp_path)

    first = _run_driver(driver, env)
    second = _run_driver(driver, env)

    assert first == second
    assert first == {"session_id": "uuid-1234", "pid": os.getpid(), "source": "env"}


def test_identity_env_precedence_prefers_the_tautline_spelling(tmp_path):
    env = {
        "TAUTLINE_SESSION_ID": "tautline-id",
        "CLAUDE_CODE_SESSION_ID": "claude-id",
        "TAUTLINE_SESSION_PID": str(os.getpid()),
        "CLAUDE_PID": "2",
    }
    identity = occupancy_session_identity(env)
    assert identity["session_id"] == "tautline-id"
    assert identity["pid"] == os.getpid()


def test_identity_synthesises_an_id_when_only_a_pid_is_exported():
    identity = occupancy_session_identity({"CLAUDE_PID": str(os.getpid())})
    assert identity == {
        "session_id": f"pid-{os.getpid()}@{HOST}",
        "pid": os.getpid(),
        "source": "env",
    }


@pytest.mark.parametrize(
    "raw", ["", "   ", "not-a-number", "0", "1", "-5", "12.5", str(2**31), "9" * 40]
)
def test_identity_ignores_unusable_pid_values(raw):
    """A pid of 0/1, a non-integer, or one outside pid_t is not a session; do not make it one."""
    identity = occupancy_session_identity({"CLAUDE_CODE_SESSION_ID": "uuid", "CLAUDE_PID": raw})
    assert identity["session_id"] == "uuid"
    assert identity["pid"] is None


# --- 2. regression pin on the env name that does not exist -------------------------------------


def test_the_dead_env_name_is_not_read_by_this_module():
    """`CLAUDE_SESSION_ID` does not exist in any measured runtime. v1 specified it, so the fallback
    was ALWAYS taken and the control was inert. Pinned by AST, not substring: the comment warning
    future editors off the name is allowed to say it; a string LITERAL is not."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "CLAUDE_SESSION_ID" not in literals


def test_identity_env_names_are_exactly_the_measured_ones():
    assert OCCUPANCY_SESSION_ID_ENV == (
        "TAUTLINE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CODEX_COMPANION_SESSION_ID",
    )
    assert OCCUPANCY_SESSION_PID_ENV == ("TAUTLINE_SESSION_PID", "CLAUDE_PID")


def test_mode_constants_are_tuples_not_lists():
    """UPPER_CASE list-of-str constants are auto-collected into the policy-phrases SSOT; these are
    config enums, not guard phrases, so they must stay tuples (see the SSOT collector)."""
    assert isinstance(OCCUPANCY_MODES, tuple)
    assert isinstance(OCCUPANCY_PRIMARY_CHECKOUT_MODES, tuple)
    assert isinstance(OCCUPANCY_SESSION_ID_ENV, tuple)
    assert isinstance(OCCUPANCY_SESSION_PID_ENV, tuple)
    assert isinstance(OCCUPANCY_ACQUIRE_STATUSES, tuple)
    assert DEFAULT_OCCUPANCY["mode"] in OCCUPANCY_MODES
    assert DEFAULT_OCCUPANCY["primaryCheckout"] in OCCUPANCY_PRIMARY_CHECKOUT_MODES


# --- 3/4. an identity that cannot be measured is ABSENT, never guessed --------------------------


def test_identity_is_unresolved_when_no_runtime_exports_one():
    assert occupancy_session_identity({}) == {
        "session_id": "",
        "pid": None,
        "source": "unresolved",
    }


def test_identity_never_falls_back_to_a_process_derived_value(tmp_path):
    """R1/P1. A process-derived fallback is worse than no identity, in both directions.

    The POSIX session leader is stable per TERMINAL, so two agents launched from one terminal would
    share a SID: the second entrant would be reported as a REFRESH of the first -- the module
    silently merging the exact collision it exists to detect. And a session leader can outlive the
    agent beneath it, keeping a dead agent's lease live with no way back but a manual unlink.

    Proven across two separate interpreters, because that is where a getppid-style fallback would
    also differ: both must be unresolved, and identical.
    """
    env = _bare_env(tmp_path)
    driver = _driver(tmp_path)

    first = _run_driver(driver, env)
    second = _run_driver(driver, env)

    assert first == second == {"session_id": "", "pid": None, "source": "unresolved"}


def test_identity_resolution_reads_no_process_attribute():
    """Pinned structurally: a future edit cannot reintroduce a process-derived identity quietly."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    resolver = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "occupancy_session_identity"
    )
    called = {
        node.func.attr
        for node in ast.walk(resolver)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"getsid", "getppid", "getpid", "getpgrp"}


# --- 5-8. liveness -------------------------------------------------------------------------------


def test_a_lease_whose_session_pid_is_live_is_live():
    assert occupancy_lease_is_live(_lease(), NOW) is True


def test_a_lease_whose_session_pid_is_dead_is_not_live():
    """Dead-session auto-reclaim: no manual unlock, ever."""
    assert occupancy_lease_is_live(_lease(pid=_dead_pid()), NOW) is False


def test_a_pid_owned_by_another_user_counts_as_live(monkeypatch):
    def _permission_denied(pid, sig):
        raise PermissionError("not ours")

    monkeypatch.setattr(occupancy.os, "kill", _permission_denied)
    assert occupancy_lease_is_live(_lease(), NOW) is True


def test_a_live_pid_beats_an_elapsed_ttl():
    """A long-running session must never have its worktree reopened because a clock elapsed."""
    stale = _lease(ttl_minutes=1, renewed_at=(NOW - timedelta(days=2)).isoformat())
    assert occupancy_lease_is_live(stale, NOW) is True


def test_another_hosts_lease_falls_back_to_ttl_liveness():
    fresh = _lease(host="somewhere-else", pid=_dead_pid())
    assert occupancy_lease_is_live(fresh, NOW) is True

    elapsed = _lease(
        host="somewhere-else",
        ttl_minutes=1,
        renewed_at=(NOW - timedelta(days=2)).isoformat(),
    )
    assert occupancy_lease_is_live(elapsed, NOW) is False


def test_a_lease_with_no_probeable_pid_falls_back_to_ttl_liveness():
    """Identity was unresolved at write time, or the record predates pid recording."""
    assert occupancy_lease_is_live(_lease(pid=None), NOW) is True
    assert (
        occupancy_lease_is_live(
            _lease(pid=None, ttl_minutes=1, renewed_at=(NOW - timedelta(days=2)).isoformat()),
            NOW,
        )
        is False
    )


MALFORMED_LEASES = [
    pytest.param(None, id="not-a-dict"),
    pytest.param("", id="empty-string"),
    pytest.param([], id="list"),
    pytest.param({}, id="empty-dict"),
    pytest.param({"schema": "tautline-fleet-lease/v1"}, id="wrong-schema"),
    pytest.param(_lease(pid="1234"), id="pid-is-a-string"),
    pytest.param(_lease(pid=True), id="pid-is-a-bool"),
    pytest.param(_lease(pid=0), id="pid-is-zero"),
    pytest.param(_lease(pid=-1), id="pid-is-negative"),
    # R1/P2: os.kill raises OverflowError -- NOT an OSError -- outside pid_t, so an unguarded
    # probe would abort the caller rather than report "stale".
    pytest.param(_lease(pid=2**31), id="pid-above-pid_t"),
    pytest.param(_lease(pid=10**30), id="pid-overflows-os-kill"),
    pytest.param(_lease(pid=None, ttl_minutes=None), id="ttl-is-none"),
    pytest.param(_lease(pid=None, ttl_minutes=True), id="ttl-is-a-bool"),
    pytest.param(_lease(pid=None, ttl_minutes=-1), id="ttl-negative"),
    pytest.param(
        _lease(pid=None, ttl_minutes=OCCUPANCY_MAX_TTL_MINUTES + 1), id="ttl-above-the-bound"
    ),
    pytest.param(_lease(pid=None, ttl_minutes=10**18), id="ttl-overflows-timedelta"),
    pytest.param(_lease(pid=None, renewed_at="not-a-timestamp"), id="unparseable-timestamp"),
    pytest.param(_lease(pid=None, renewed_at=None, started_at=None), id="no-timestamp"),
    pytest.param(_lease(host=None), id="host-is-none"),
]


@pytest.mark.parametrize("lease", MALFORMED_LEASES)
def test_the_liveness_predicate_is_total_over_hostile_data(lease):
    """A malformed lease must never block a lane and must never raise out of the predicate."""
    assert occupancy_lease_is_live(lease, NOW) is False


def test_a_live_pid_stops_being_evidence_past_the_trust_horizon():
    """R1/P2 (pid reuse). A live pid beats an elapsed TTL -- but not forever: pids recycle, and an
    unbounded rule would let a recycled pid hold a worktree closed with no way back but a manual
    unlink. Past the horizon the record falls back to TTL, which by then has long expired."""
    horizon = occupancy.OCCUPANCY_PID_TRUST_HORIZON_MINUTES
    inside = _lease(renewed_at=(NOW - timedelta(minutes=horizon - 1)).isoformat(), ttl_minutes=1)
    outside = _lease(renewed_at=(NOW - timedelta(minutes=horizon + 1)).isoformat(), ttl_minutes=1)

    assert occupancy_lease_is_live(inside, NOW) is True
    assert occupancy_lease_is_live(outside, NOW) is False


def test_the_trust_horizon_is_far_longer_than_any_renewal_interval():
    """The horizon must never evict a session that is actually running. Sessions renew at every
    session start, so a week of no renewal is not a working session."""
    assert occupancy.OCCUPANCY_PID_TRUST_HORIZON_MINUTES >= 60 * 24 * 7


def test_a_far_future_timestamp_does_not_hold_a_worktree_closed():
    """On the TTL path the timestamp is the ONLY evidence, so a skewed or corrupt one far in the
    future would hold the checkout until that date PLUS its TTL, with no remedy but deleting the
    file by hand. Malformed state must never outrank a live session."""
    skew = occupancy.OCCUPANCY_MAX_FUTURE_SKEW_MINUTES
    tolerated = _lease(pid=None, renewed_at=(NOW + timedelta(minutes=skew - 1)).isoformat())
    absurd = _lease(pid=None, renewed_at=(NOW + timedelta(days=3650)).isoformat())

    assert occupancy_lease_is_live(tolerated, NOW) is True  # ordinary clock drift is fine
    assert occupancy_lease_is_live(absurd, NOW) is False


def test_a_forged_future_date_cannot_buy_pid_trust():
    """Scoping the skew bound to the TTL path looked right -- 'a live pid beats a clock' -- and
    was wrong: the PID path reads the same timestamp through the trust horizon, so a decade-ahead
    `renewed_at` kept pid trust open for years. Combined with pid reuse, that is a stale or forged
    lease holding a worktree indefinitely on the strength of an unrelated live process."""
    forged = _lease(renewed_at=(NOW + timedelta(days=3650)).isoformat())  # live pid, absurd date

    assert occupancy_lease_is_live(forged, NOW) is False


def test_ordinary_clock_drift_still_keeps_a_live_session():
    """The bound is drift tolerance, not clock policing: a live session survives a fast clock."""
    skew = occupancy.OCCUPANCY_MAX_FUTURE_SKEW_MINUTES
    drifting = _lease(renewed_at=(NOW + timedelta(minutes=skew - 1)).isoformat(), ttl_minutes=1)

    assert occupancy_lease_is_live(drifting, NOW) is True  # elapsed TTL, live pid, tolerated drift


def test_a_fifo_at_the_lease_path_cannot_hang_a_lane(tmp_path):
    """A plain read of a FIFO blocks until someone writes -- a hang, inside a SessionStart hook
    contractually forbidden to block. It is not a lease, so it is not read."""
    fifo = tmp_path / "lane-lease.json"
    os.mkfifo(fifo)

    assert occupancy_read_lease(fifo) is None


def test_a_short_read_never_turns_a_live_holder_into_a_wreck(monkeypatch, lease_path):
    """`os.read` is permitted to return a SHORT read, and network/FUSE filesystems do. Truncated
    JSON fails to parse, and acquire reads unparseable-over-an-existing-file as a wreck to
    reclaim -- so a short read of a LIVE foreign holder would hand the worktree to a second
    session. The reader loops to EOF for exactly this reason."""
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    real_read = occupancy.os.read
    calls = {"n": 0}

    def _short_read(fd, size):
        calls["n"] += 1
        return real_read(fd, 8 if calls["n"] == 1 else size)  # first read returns a fragment

    monkeypatch.setattr(occupancy.os, "read", _short_read)

    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"
    assert calls["n"] > 1, "the reader did not loop; a single os.read cannot be short-read safe"
    assert occupancy_acquire(lease_path, IDENTITY_B, NOW)[0] == "conflict"


def test_a_lease_too_large_for_the_reader_is_never_published(lease_path):
    """A writer that publishes what the reader rejects hands the caller 'acquired' while every
    peer sees a wreck. Same class as the pid and session-id findings, so it is closed the same
    way: if we would not believe this lease, we do not write it."""
    huge = "x" * (occupancy.OCCUPANCY_MAX_LEASE_BYTES + 10)
    status, lease = occupancy_acquire(lease_path, {**IDENTITY_A, "session_id": huge}, NOW)

    assert (status, lease) == ("unavailable", None)
    assert not lease_path.exists()


def test_a_whitespace_only_session_id_never_claims(lease_path):
    """`" "` is truthy to a naive guard and blank to `_lease_well_formed`."""
    assert occupancy_acquire(lease_path, {**IDENTITY_A, "session_id": "   "}, NOW) == (
        "unresolved",
        None,
    )
    assert not lease_path.exists()


def test_an_unlocked_session_with_no_pid_declines_to_take_the_worktree(monkeypatch, lease_path):
    """Do not take what you could never give back. Unlocked, release is a no-op, and a pid-less
    lease is TTL-only so nothing reads it dead either -- publishing would hold the worktree for
    the whole TTL after the session ended, with no remedy but deleting the file."""
    monkeypatch.setitem(sys.modules, "fcntl", None)

    assert occupancy_acquire(lease_path, {**IDENTITY_A, "pid": None}, NOW) == ("unavailable", None)
    assert not lease_path.exists()
    # With a pid it is releasable-by-liveness, so the same unlocked publish is allowed.
    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "acquired"


def test_a_session_whose_id_has_whitespace_still_owns_its_own_lease(lease_path):
    """Acquire STORES the stripped id, so an unstripped ownership comparison makes a session read
    its own lease as foreign -- unable to refresh it and unable to release it."""
    padded = {**IDENTITY_A, "session_id": "  session-a  "}

    assert occupancy_acquire(lease_path, padded, NOW)[0] == "acquired"
    assert occupancy_acquire(lease_path, padded, NOW + timedelta(minutes=1))[0] == "refreshed"
    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "refreshed"  # same session
    assert occupancy_release(lease_path, padded) is True


def test_losing_a_publish_race_to_your_own_session_is_not_a_conflict(monkeypatch, lease_path):
    """Two invocations of one session racing for an empty path: the loser must not be told it
    conflicts with itself."""
    real_link = occupancy.os.link

    def _lose_once(src, dst):
        occupancy.os.link = real_link          # only the first publish loses
        real_link(src, dst)                    # simulate the winner landing first
        raise FileExistsError(17, "File exists")

    monkeypatch.setattr(occupancy.os, "link", _lose_once)

    status, lease = occupancy_acquire(lease_path, IDENTITY_A, NOW)

    assert status == "refreshed"
    assert lease["session_id"] == "session-a"


def test_a_non_regular_lock_node_does_not_leak_a_descriptor(tmp_path):
    """The early return on a non-regular lock skipped the cleanup below it, so a long-lived
    process would leak one descriptor per call until it ran out."""
    lease_path = tmp_path / ".ai-work" / "lane-lease.json"
    lease_path.parent.mkdir(parents=True)
    os.mkfifo(lease_path.parent / f".{lease_path.name}.lock")

    before = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
    for _ in range(40):
        occupancy_acquire(lease_path, IDENTITY_A, NOW)
        occupancy_release(lease_path, IDENTITY_A)
    after = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None

    if before is not None:
        assert after - before < 10, f"descriptors grew from {before} to {after} over 40 calls"


def test_declining_to_publish_still_reports_a_live_holder(monkeypatch, lease_path):
    """Refusing to publish and failing to notice a holder are different answers. The unlocked
    pid-less path declines to take the worktree -- but if a live foreign session holds it, that is
    a CONFLICT, not `unavailable`. The status contract documents `unavailable` as report-only, so
    conflating them would have a caller admit the second session into an occupied checkout."""
    occupancy_acquire(lease_path, IDENTITY_A, NOW)  # a live foreign holder, with a pid
    monkeypatch.setitem(sys.modules, "fcntl", None)

    status, holder = occupancy_acquire(lease_path, {**IDENTITY_B, "pid": None}, NOW)

    assert status == "conflict"
    assert holder["session_id"] == "session-a"


def test_a_padded_session_id_on_disk_is_malformed_not_a_self_lockout(lease_path):
    """Acquire stores the stripped form, so a record carrying a padded id -- damaged state, or a
    writer that is not this module -- would compare unequal to its own owner and lock that session
    out of its own worktree until the pid horizon or TTL elapsed."""
    padded = {**_lease(), "session_id": "  session-a  "}

    assert occupancy_lease_is_live(padded, NOW) is False
    assert occupancy_lease_foreignness(padded, NOW, IDENTITY_A) == (False, "")

    lease_path.write_text(json.dumps(padded), encoding="utf-8")
    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "reclaimed"


def test_a_fifo_lock_node_cannot_hang_lane_startup(tmp_path):
    """`open("a")` on a FIFO blocks waiting for a reader -- before the bounded LOCK_NB loop is
    ever reached -- so a malformed lock node would hang startup straight through the fail-open
    contract. A lock that is not a regular file is not a lock."""
    lease_path = tmp_path / ".ai-work" / "lane-lease.json"
    lease_path.parent.mkdir(parents=True)
    os.mkfifo(lease_path.parent / f".{lease_path.name}.lock")

    started = __import__("time").monotonic()
    status, _ = occupancy_acquire(lease_path, IDENTITY_A, NOW)
    elapsed = __import__("time").monotonic() - started

    assert elapsed < 10, f"acquire blocked {elapsed:.1f}s on a FIFO lock node"
    assert status == "acquired"  # unlocked, but an empty slot needs no lock


def test_an_oversized_file_at_the_lease_path_is_not_read(tmp_path):
    big = tmp_path / "lane-lease.json"
    big.write_bytes(b"x" * (occupancy.OCCUPANCY_MAX_LEASE_BYTES + 1))

    assert occupancy_read_lease(big) is None


def test_a_naive_timestamp_is_read_as_utc():
    """Naive vs aware comparison raises TypeError; a lease file is allowed to carry either."""
    naive = _lease(pid=None, renewed_at=NOW.replace(tzinfo=None).isoformat())
    assert occupancy_lease_is_live(naive, NOW) is True


# --- 10. foreignness -----------------------------------------------------------------------------


def test_our_own_live_lease_is_not_foreign():
    identity = {"session_id": "session-a", "pid": os.getpid(), "source": "env"}
    assert occupancy_lease_foreignness(_lease(), NOW, identity) == (False, "")


def test_another_live_session_is_foreign():
    identity = {"session_id": "session-b", "pid": os.getpid(), "source": "env"}
    assert occupancy_lease_foreignness(_lease(), NOW, identity) == (True, "different-session")


def test_a_dead_lease_is_never_foreign():
    identity = {"session_id": "session-b", "pid": os.getpid(), "source": "env"}
    assert occupancy_lease_foreignness(_lease(pid=_dead_pid()), NOW, identity) == (False, "")


def test_an_unresolved_identity_is_foreign_but_says_so():
    """We cannot prove the lease is ours, so we report -- and the caller must not refuse on it."""
    identity = {"session_id": "", "pid": None, "source": "unresolved"}
    assert occupancy_lease_foreignness(_lease(), NOW, identity) == (True, "unresolved-identity")


@pytest.mark.parametrize("lease", MALFORMED_LEASES)
def test_foreignness_is_total_over_hostile_data(lease):
    identity = {"session_id": "session-b", "pid": os.getpid(), "source": "env"}
    assert occupancy_lease_foreignness(lease, NOW, identity) == (False, "")


# --- 11. acquire / release round-trip, path-parameterized ---------------------------------------


@pytest.fixture
def lease_path(tmp_path):
    path = tmp_path / ".ai-work" / "lane-lease.json"
    path.parent.mkdir(parents=True)
    return path


IDENTITY_A = {"session_id": "session-a", "pid": os.getpid(), "source": "env"}
IDENTITY_B = {"session_id": "session-b", "pid": os.getpid(), "source": "env"}


def test_acquire_creates_a_lease_when_the_worktree_is_free(lease_path):
    status, lease = occupancy_acquire(lease_path, IDENTITY_A, NOW, branch="feat/x")

    assert status == "acquired"
    assert lease["schema"] == OCCUPANCY_LEASE_SCHEMA
    assert lease["session_id"] == "session-a"
    assert lease["pid"] == os.getpid()
    assert lease["identity_source"] == "env"
    assert lease["writer_pid"] == os.getpid()
    assert lease["host"] == HOST
    assert lease["branch"] == "feat/x"
    assert lease["started_at"] == NOW.isoformat()
    assert lease["renewed_at"] == NOW.isoformat()
    assert occupancy_read_lease(lease_path) == lease


def test_re_acquiring_from_the_same_session_refreshes_rather_than_conflicts(lease_path):
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    later = NOW + timedelta(minutes=30)

    status, lease = occupancy_acquire(lease_path, IDENTITY_A, later)

    assert status == "refreshed"
    assert lease["renewed_at"] == later.isoformat()
    assert lease["started_at"] == NOW.isoformat()  # the session's original entry, preserved


def test_acquiring_over_a_live_peers_lease_is_a_conflict(lease_path):
    _, held = occupancy_acquire(lease_path, IDENTITY_A, NOW)

    status, holder = occupancy_acquire(lease_path, IDENTITY_B, NOW)

    assert status == "conflict"
    assert holder == held
    assert occupancy_read_lease(lease_path) == held  # the holder's record is untouched


def test_acquiring_over_a_dead_sessions_lease_reclaims_it(lease_path):
    occupancy_acquire(lease_path, {**IDENTITY_A, "pid": _dead_pid()}, NOW)

    status, lease = occupancy_acquire(lease_path, IDENTITY_B, NOW)

    assert status == "reclaimed"
    assert lease["session_id"] == "session-b"
    assert lease["started_at"] == NOW.isoformat()


def test_acquiring_over_a_corrupt_lease_file_reclaims_it(lease_path):
    lease_path.write_text("{not json", encoding="utf-8")

    status, lease = occupancy_acquire(lease_path, IDENTITY_A, NOW)

    assert status == "reclaimed"
    assert occupancy_read_lease(lease_path) == lease


@pytest.mark.parametrize(
    "pid",
    [
        pytest.param(True, id="bool-is-an-int-in-python"),
        pytest.param(-1, id="negative"),
        pytest.param(0, id="zero"),
        pytest.param(1, id="init"),
        pytest.param(2**31, id="above-pid_t"),
        pytest.param("1234", id="string"),
    ],
)
def test_acquire_never_publishes_a_lease_its_own_predicate_calls_malformed(lease_path, pid):
    """A hand-built identity carrying an unusable pid must not be written through. Otherwise
    acquire returns 'acquired' while `_lease_well_formed` immediately reads the record as stale --
    so the holder believes it owns the worktree and a peer is free to reclaim it."""
    status, lease = occupancy_acquire(lease_path, {**IDENTITY_A, "pid": pid}, NOW)

    assert status == "acquired"
    assert lease["pid"] is None  # normalized, not written through
    assert occupancy_lease_is_live(lease, NOW) is True
    # And the record on disk is genuinely held: a peer conflicts rather than reclaiming.
    assert occupancy_acquire(lease_path, IDENTITY_B, NOW)[0] == "conflict"


def test_an_unresolved_identity_never_claims_a_lease(lease_path):
    """A lease written under an empty session id reads foreign to EVERY later session, including
    the one that wrote it -- a permanent phantom holder. Refuse to write it at all."""
    status, lease = occupancy_acquire(
        lease_path, {"session_id": "", "pid": None, "source": "unresolved"}, NOW
    )

    assert status == "unresolved"
    assert lease is None
    assert not lease_path.exists()


def test_acquire_degrades_instead_of_raising_when_the_lease_cannot_be_written(tmp_path):
    """A coordination aid must not be the thing that stops a lane: the startup hook that calls this
    is contractually non-blocking."""
    state = tmp_path / "readonly"
    state.mkdir()
    state.chmod(0o500)
    try:
        status, lease = occupancy_acquire(state / "lane-lease.json", IDENTITY_A, NOW)
    finally:
        state.chmod(0o700)

    assert status == "unavailable"
    assert lease is None


def test_acquire_publishes_the_lease_atomically_and_leaves_no_temp_file(lease_path):
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    occupancy_acquire(lease_path, IDENTITY_A, NOW + timedelta(minutes=1))

    # The lock file is expected and durable; a `.tmp` staging file is not.
    assert sorted(p.name for p in lease_path.parent.iterdir()) == [
        ".lane-lease.json.lock",
        "lane-lease.json",
    ]


def test_every_acquire_status_is_declared():
    assert set(OCCUPANCY_ACQUIRE_STATUSES) == {
        "acquired",
        "refreshed",
        "reclaimed",
        "conflict",
        "unresolved",
        "unavailable",
    }


def test_release_removes_only_our_own_lease(lease_path):
    occupancy_acquire(lease_path, IDENTITY_A, NOW)

    assert occupancy_release(lease_path, IDENTITY_B) is False
    assert lease_path.exists()

    assert occupancy_release(lease_path, IDENTITY_A) is True
    assert not lease_path.exists()


def test_release_is_a_no_op_when_there_is_no_lease(lease_path):
    assert occupancy_release(lease_path, IDENTITY_A) is False


def test_release_never_removes_a_lease_for_an_unresolved_identity(lease_path):
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    unresolved = {"session_id": "", "pid": None, "source": "unresolved"}

    assert occupancy_release(lease_path, unresolved) is False
    assert lease_path.exists()


def test_release_reclaims_our_own_dead_lease_written_by_an_earlier_invocation(lease_path):
    """WS3 releases in a `finally`; a crashed round must not wedge the next one."""
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    assert occupancy_release(lease_path, {**IDENTITY_A, "pid": _dead_pid()}) is True


def test_read_lease_is_total_over_unreadable_files(tmp_path):
    missing = tmp_path / "nope.json"
    assert occupancy_read_lease(missing) is None

    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00nonsense")
    assert occupancy_read_lease(binary) is None

    directory = tmp_path / "dir.json"
    directory.mkdir()
    assert occupancy_read_lease(directory) is None

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[1, 2, 3]", encoding="utf-8")
    assert occupancy_read_lease(not_an_object) is None


def test_the_review_lease_uses_the_same_primitives_at_a_different_path(tmp_path):
    """WS3 reuses this module with only a path and a TTL changed -- no second liveness model."""
    review = tmp_path / ".ai-work" / "review-lease.json"
    review.parent.mkdir(parents=True)

    status, lease = occupancy_acquire(review, IDENTITY_A, NOW, ttl_minutes=90)
    assert status == "acquired"
    assert lease["ttl_minutes"] == 90

    assert occupancy_acquire(review, IDENTITY_B, NOW)[0] == "conflict"
    assert occupancy_release(review, IDENTITY_A) is True


@pytest.mark.parametrize("ttl", [0, -1, OCCUPANCY_MAX_TTL_MINUTES + 1, "90", True, None])
def test_acquire_rejects_a_ttl_it_would_not_trust_on_read(lease_path, ttl):
    """A lease written with a TTL the liveness predicate treats as malformed is a lease that is
    dead the moment it lands -- write the default instead of an unusable value."""
    _, lease = occupancy_acquire(lease_path, IDENTITY_A, NOW, ttl_minutes=ttl)
    assert lease["ttl_minutes"] == DEFAULT_OCCUPANCY["ttlMinutes"]
    assert occupancy_lease_is_live(lease, NOW) is True


# --- mutual exclusion under real simultaneous acquisition ---------------------------------------

# One process per entrant, each with its OWN live session identity, all released by a wall-clock
# barrier. In-process threads would not exercise the thing under test: the critical section has to
# hold across PROCESSES, which is the only shape two agent sessions ever take.
CONTENTION_DRIVER = """
import json, sys, time
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
from tautline_methodology.occupancy import occupancy_acquire

lease_path, start_at, session_id = sys.argv[2], float(sys.argv[3]), sys.argv[4]
while time.time() < start_at:
    pass
identity = {"session_id": session_id, "pid": None, "source": "env"}
status, _ = occupancy_acquire(lease_path, identity, datetime.now(timezone.utc))
sys.stdout.write(json.dumps({"status": status}))
"""


def test_simultaneous_acquisition_awards_the_worktree_to_exactly_one_session(tmp_path):
    """The whole module is worthless if two entrants can both be told they hold the worktree."""
    driver = tmp_path / "contention_driver.py"
    driver.write_text(CONTENTION_DRIVER, encoding="utf-8")
    lease_path = tmp_path / ".ai-work" / "lane-lease.json"
    lease_path.parent.mkdir(parents=True)

    entrants = 8
    start_at = __import__("time").time() + 2.0
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(driver),
                str(SRC_ROOT),
                str(lease_path),
                str(start_at),
                f"session-{index}",
            ],
            env=_bare_env(tmp_path),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(entrants)
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=90)
        assert proc.returncode == 0, err
        results.append(json.loads(out)["status"])

    winners = [status for status in results if status in {"acquired", "reclaimed", "refreshed"}]
    assert len(winners) == 1, f"{len(winners)} entrants believed they took the worktree: {results}"
    assert results.count("conflict") == entrants - 1

    # And the record on disk belongs to the winner: no half-written or last-writer-wins record.
    held = occupancy_read_lease(lease_path)
    assert held is not None
    assert held["session_id"].startswith("session-")
    assert not [p.name for p in lease_path.parent.iterdir() if p.name.endswith(".tmp")]


def test_the_lock_never_stops_a_lane_when_the_filesystem_cannot_lock(monkeypatch, lease_path):
    """Fail-open, like fleet_claims_lock: no fcntl (or a refusing flock) degrades to best-effort,
    and the no-replace publish still prevents two entrants from both taking a free worktree."""
    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` now raises ImportError

    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "acquired"
    assert occupancy_acquire(lease_path, IDENTITY_B, NOW)[0] == "conflict"


RECLAIM_RACE_DRIVER = """
import json, sys, time
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
if sys.argv[5] == "no-lock":
    sys.modules["fcntl"] = None        # the documented lock-unavailable path
from tautline_methodology.occupancy import occupancy_acquire

lease_path, start_at, session_id = sys.argv[2], float(sys.argv[3]), sys.argv[4]
while time.time() < start_at:
    pass
identity = {"session_id": session_id, "pid": None, "source": "env"}
status, _ = occupancy_acquire(lease_path, identity, datetime.now(timezone.utc))
sys.stdout.write(json.dumps({"status": status}))
"""


def _race_for_a_stale_lease(tmp_path, lock_mode, entrants=6):
    driver = tmp_path / "reclaim_race_driver.py"
    driver.write_text(RECLAIM_RACE_DRIVER, encoding="utf-8")
    lease_path = tmp_path / ".ai-work" / "lane-lease.json"
    lease_path.parent.mkdir(parents=True)
    # A stale record every entrant observes simultaneously: well-formed, dead pid.
    lease_path.write_text(json.dumps(_lease(pid=_dead_pid())), encoding="utf-8")

    start_at = __import__("time").time() + 2.0
    procs = [
        subprocess.Popen(
            [sys.executable, str(driver), str(SRC_ROOT), str(lease_path), str(start_at),
             f"reclaimer-{index}", lock_mode],
            env=_bare_env(tmp_path), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for index in range(entrants)
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=90)
        assert proc.returncode == 0, err
        results.append(json.loads(out)["status"])
    return results, lease_path


def test_exactly_one_session_reclaims_a_stale_lease(tmp_path):
    """Six processes, one planted stale record, released by a wall-clock barrier."""
    results, lease_path = _race_for_a_stale_lease(tmp_path, "lock")

    winners = [s for s in results if s in {"acquired", "reclaimed", "refreshed"}]
    assert len(winners) == 1, f"{len(winners)} entrants reclaimed the same stale lease: {results}"
    assert occupancy_read_lease(lease_path)["session_id"].startswith("reclaimer-")


def test_a_stale_lease_is_never_reclaimed_twice_when_the_lock_is_unavailable(tmp_path):
    """R2/P1 + two impl-review P1s. The lock is documented FAIL-OPEN, so exclusivity may not
    depend on it -- and reclaim has no lock-free primitive that can arbitrate it: unlink-then-link
    lets a second contender delete the first's LIVE record and both be told they won. So an
    unserialized mutation is refused. ZERO winners is the correct answer here, not one: the
    entrants report, the stale record stands, and a session that can lock reclaims it later."""
    results, lease_path = _race_for_a_stale_lease(tmp_path, "no-lock")

    winners = [s for s in results if s in {"acquired", "reclaimed", "refreshed"}]
    assert not winners, f"an unserialized reclaim awarded the worktree: {results}"
    assert set(results) == {"unavailable"}
    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"  # never clobbered


def test_an_unlocked_reclaim_reports_rather_than_deleting_the_winner(monkeypatch, lease_path):
    """The exact interleaving the review named: A unlinks the stale record and links its own, then
    B -- still holding its stale read -- unlinks A's LIVE record and links its own, and both are
    told they reclaimed. unlink-then-link only looks atomic. With no POSIX "unlink only if the
    content is still what I read", an unserialized mutation is refused instead."""
    lease_path.write_text(json.dumps(_lease(pid=_dead_pid())), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "fcntl", None)

    status, lease = occupancy_acquire(lease_path, IDENTITY_B, NOW)

    assert (status, lease) == ("unavailable", None)
    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"  # untouched


def test_an_unlocked_acquire_into_a_free_slot_still_works(monkeypatch, lease_path):
    """Publishing into an EMPTY slot needs no lock: os.link arbitrates it. Only MUTATION is
    refused, so the common unlocked case is not degraded into uselessness."""
    monkeypatch.setitem(sys.modules, "fcntl", None)

    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "acquired"
    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"


def test_no_hard_links_and_no_lock_reports_rather_than_awarding(monkeypatch, lease_path):
    """With neither os.link nor flock there is nothing left to tell a winner from a loser, and
    inventing one is exactly how both entrants 'win'."""

    def _no_links(src, dst):
        raise OSError(45, "Operation not supported")

    monkeypatch.setattr(occupancy.os, "link", _no_links)
    monkeypatch.setitem(sys.modules, "fcntl", None)

    assert occupancy_acquire(lease_path, IDENTITY_A, NOW) == ("unavailable", None)
    assert not lease_path.exists()


def test_a_deeply_nested_lease_reads_as_stale_rather_than_aborting_the_caller(lease_path):
    """json.loads raises RecursionError -- not a ValueError -- on deeply nested input, so an
    uncaught one would abort the startup hook that read the lease instead of reclaiming it."""
    lease_path.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")

    assert occupancy_read_lease(lease_path) is None
    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "reclaimed"


LOCK_HOLDER_DRIVER = """
import fcntl, sys, time
handle = open(sys.argv[1], "a")
fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
sys.stdout.write("held\\n")
sys.stdout.flush()
time.sleep(600)                        # a peer that is paused, not one that is working
"""


def test_a_paused_peer_holding_the_lock_cannot_hang_a_lane(tmp_path, monkeypatch):
    """A plain LOCK_EX waits forever, so one stuck peer would hang every later lane-start and
    review round -- and they would never reach the fail-open path the lock exists to provide. A
    startup hook that hangs is worse than one that reports."""
    lease_path = tmp_path / ".ai-work" / "lane-lease.json"
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(json.dumps(_lease(pid=_dead_pid())), encoding="utf-8")
    lock_path = lease_path.parent / f".{lease_path.name}.lock"

    driver = tmp_path / "lock_holder.py"
    driver.write_text(LOCK_HOLDER_DRIVER, encoding="utf-8")
    holder = subprocess.Popen(
        [sys.executable, str(driver), str(lock_path)],
        text=True, stdout=subprocess.PIPE, env=_bare_env(tmp_path),
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(occupancy, "OCCUPANCY_LOCK_WAIT_SECONDS", 0.5)

        started = __import__("time").monotonic()
        status, lease = occupancy_acquire(lease_path, IDENTITY_B, NOW)
        elapsed = __import__("time").monotonic() - started
    finally:
        holder.kill()
        holder.wait()

    assert elapsed < 30, f"acquire waited {elapsed:.1f}s behind a paused peer"
    # Unlocked, so the reclaim is refused rather than risked: report-only, record untouched.
    assert (status, lease) == ("unavailable", None)
    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"


def test_release_does_not_mutate_without_a_real_lock(monkeypatch, lease_path):
    """A delete has no no-replace analogue, so release cannot arbitrate a lost race after the
    fact. Unlocked, it does nothing rather than delete a lease a peer just reclaimed -- safe,
    because a lease whose session is gone reads dead on the next probe anyway."""
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    monkeypatch.setitem(sys.modules, "fcntl", None)

    assert occupancy_release(lease_path, IDENTITY_A) is False
    assert lease_path.exists()


def test_a_lease_with_no_session_id_is_malformed_not_a_permanent_blocker(lease_path):
    """impl-review P2. Foreignness compares session ids, so a record missing one compares unequal
    to EVERY acquirer: without this it would hold the checkout closed against everyone until its
    pid died -- malformed state acting as a blocker, which is the module's posture inverted."""
    for broken in ({**_lease(), "session_id": ""}, {**_lease(), "session_id": None},
                   {k: v for k, v in _lease().items() if k != "session_id"}):
        assert occupancy_lease_is_live(broken, NOW) is False
        assert occupancy_lease_foreignness(broken, NOW, IDENTITY_A) == (False, "")

    lease_path.write_text(json.dumps({**_lease(), "session_id": ""}), encoding="utf-8")
    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "reclaimed"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("²", id="superscript-two-isdigit-but-int-rejects-it"),
        pytest.param("⁵", id="superscript-five"),
        pytest.param("9" * 5000, id="beyond-cpython-int-str-digit-cap"),
        pytest.param("١٢٣", id="arabic-indic-digits"),
    ],
)
def test_a_hostile_pid_variable_makes_identity_unresolvable_rather_than_raising(raw):
    """impl-review P2. `str.isdigit()` is true for characters `int()` rejects, and CPython caps
    integer parsing at 4300 digits -- so the obvious guard raises where it must degrade."""
    identity = occupancy_session_identity({"CLAUDE_CODE_SESSION_ID": "uuid", "CLAUDE_PID": raw})
    assert identity == {"session_id": "uuid", "pid": None, "source": "env"}


def test_publication_degrades_to_replace_where_hard_links_are_unsupported(monkeypatch, lease_path):
    """Some network and virtualised filesystems refuse os.link. A control that stands down there
    protects nobody -- publish atomically anyway and let the lock serialize the decision."""

    def _no_links(src, dst):
        raise OSError(45, "Operation not supported")

    monkeypatch.setattr(occupancy.os, "link", _no_links)

    assert occupancy_acquire(lease_path, IDENTITY_A, NOW)[0] == "acquired"
    assert occupancy_read_lease(lease_path)["session_id"] == "session-a"
    assert occupancy_acquire(lease_path, IDENTITY_B, NOW)[0] == "conflict"


def test_the_lock_file_is_not_mistaken_for_a_lease(lease_path):
    occupancy_acquire(lease_path, IDENTITY_A, NOW)
    assert occupancy_read_lease(lease_path.parent / f".{lease_path.name}.lock") is None


# --- parity with the fleet-lease primitives this module deliberately mirrors ---------------------


PARITY_TIMESTAMPS = [
    "2026-08-09T12:00:00+00:00",
    "2026-08-09T12:00:00Z",
    "2026-08-09T12:00:00",  # naive -> UTC
    "  2026-08-09T12:00:00Z  ",
    "not-a-timestamp",
    "",
    "2026-13-45T99:00:00Z",
]


def test_the_ttl_bound_matches_the_fleet_bound(cli):
    assert OCCUPANCY_MAX_TTL_MINUTES == cli.FLEET_MAX_TTL_MINUTES


def test_the_module_never_reaches_the_process_environment_directly():
    """Managed TAUTLINE_ settings must be read through util.resolve_env (tests/
    test_env_reads_use_resolver.py polices this for the whole package). Pinned here too, at the
    module that introduces two new managed names, so the reason is visible where the names live."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    }
    assert "environ" not in attributes
    assert "getenv" not in attributes


# --- item 68 PR4: the owner key ---------------------------------------------------------------


def test_a_record_without_an_owner_is_owned_by_its_session(cli) -> None:
    """The default-equivalence proof. Every lease written before this field existed, and every
    lane lease written after it, keeps its exact previous meaning -- which is why the 179 tests
    above this one pass UNMODIFIED. A record that predates the field is legal, not malformed:
    rejecting those would strand live sessions mid-round."""
    from tautline_methodology.occupancy import occupancy_owner_of

    assert occupancy_owner_of({"session_id": "s1"}) == "s1"
    assert occupancy_owner_of({"session_id": "s1", "owner": ""}) == "s1", "blank is absent"
    assert occupancy_owner_of({"session_id": " s1 "}) == "s1", "one canonical form"


def test_an_explicit_owner_wins_over_the_session(cli) -> None:
    """Two things can hold a lease: a SESSION holds a worktree for as long as it works there, and
    a review RUN holds its own for exactly one invocation. Keying both on session_id would make a
    lane's second review round read as its own first one -- same session, different holder."""
    from tautline_methodology.occupancy import occupancy_owner_of

    assert occupancy_owner_of({"session_id": "s1", "owner": "review-abc"}) == "review-abc"


def test_two_runs_of_one_session_are_different_owners(cli) -> None:
    """The distinctness that motivates the field at all.

    The comparison clock is this module's pinned NOW, not the wall clock: `_lease()` stamps
    `renewed_at` at NOW, so judging it against `datetime.now()` made the fixture read EXPIRED
    once real time drifted past its TTL, `occupancy_lease_foreignness` short-circuited on the
    liveness guard, and this owner assertion failed for a reason that has nothing to do with
    owners. It passed when written and rotted with the calendar -- the same hardcoded-constant
    class as a test that pins a future version as its "newer release".
    """
    from tautline_methodology.occupancy import occupancy_lease_foreignness

    now = NOW
    held = _lease(session_id="s1")
    held["owner"] = "review-run-1"

    same_session_new_run = {"session_id": "s1", "owner": "review-run-2"}
    foreign, reason = occupancy_lease_foreignness(held, now, same_session_new_run)

    assert foreign is True, "a second run must not inherit the first run's lease"
    assert reason == "different-session"

    same_run = {"session_id": "s1", "owner": "review-run-1"}
    assert occupancy_lease_foreignness(held, now, same_run)[0] is False, "its own run is not foreign"


def test_a_lane_lease_still_compares_by_session(cli) -> None:
    """No lane behaviour moves: with no owner on either side, this is the pre-PR4 comparison.

    Pinned to this module's NOW for the same reason as the test above: the fixture lease is
    stamped at NOW, so a wall-clock comparison expires it and the liveness guard answers before
    the ownership comparison this test exists to make.
    """
    from tautline_methodology.occupancy import occupancy_lease_foreignness

    now = NOW
    held = _lease(session_id="s1")

    assert occupancy_lease_foreignness(held, now, {"session_id": "s1"})[0] is False
    assert occupancy_lease_foreignness(held, now, {"session_id": "s2"})[0] is True


def test_a_review_lease_is_released_by_its_own_run(cli, tmp_path) -> None:
    """Codex R1 P2. `mine` is the OWNER -- the run id for a review lease -- and comparing it
    against the record's raw session_id meant a review lease was never its holder's to release,
    so a finished round stayed held until reclamation. Both sides go through one resolver."""
    import os
    from datetime import datetime, timezone

    from tautline_methodology.occupancy import occupancy_acquire, occupancy_release

    path = tmp_path / "review-lease.json"
    identity = {"session_id": "s1", "pid": os.getpid(), "owner": "review-1"}

    occupancy_acquire(path, identity, datetime.now(timezone.utc), ttl_minutes=90, owner="review-1")
    assert path.exists()

    assert occupancy_release(path, identity) is True
    assert not path.exists(), "the run that took it must be able to give it back"


def test_a_review_lease_is_not_released_by_another_run(cli, tmp_path) -> None:
    """Releasing a peer's lease stays a no-op -- the same rule, now keyed on the owner."""
    import os
    from datetime import datetime, timezone

    from tautline_methodology.occupancy import occupancy_acquire, occupancy_release

    path = tmp_path / "review-lease.json"
    occupancy_acquire(
        path, {"session_id": "s1", "pid": os.getpid(), "owner": "review-1"},
        datetime.now(timezone.utc), ttl_minutes=90, owner="review-1",
    )

    other = {"session_id": "s1", "pid": os.getpid(), "owner": "review-2"}

    assert occupancy_release(path, other) is False
    assert path.exists(), "a second run of the same session must not free the first"
