"""Session<->worktree occupancy (`tautline-occupancy-lease/v1`).

A fleet lease answers "which WORKTREE holds these paths"; an occupancy lease answers
"which SESSION holds this worktree". Two sessions in one checkout share index and HEAD, so the
second entrant must be refused or relocated BEFORE any work happens -- the mechanism behind two
recorded incidents, one of which swept a peer session's staged files into a foreign commit.

IDENTITY IS THE AGENT SESSION PROCESS, and it comes from a MEASURED runtime variable or nowhere.
Not `os.getpid()` (the CLI invocation), not `os.getppid()` (the per-invocation shell, measured to
be a corpse seconds after the command it ran returned), and not the POSIX session leader (shared by
every agent launched from one terminal). Getting this wrong does not make the control merely wrong,
it makes it INERT or, worse, REASSURING: leases read dead so nothing is refused, or two sessions
share one identity so the second entrant is greeted as a returning first.

This module owns file I/O for the lease -- unlike `lane_status`, whose collector owns I/O -- because
acquisition must be ATOMIC to mean anything. Everything else here is pure.

Posture, in one line: fail-OPEN on bad state, fail-CLOSED only on a live, well-formed, foreign
holder. A coordination aid must never be the thing that strands a lane.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

try:  # pragma: no cover - exercised by the 3.9 prepush-hook path, not by the 3.12 suite
    from typing import TypeGuard
except ImportError:  # Python < 3.10
    # This project has a 3.12 floor, but the pre-push schema-skew hook still runs under whatever
    # interpreter the checkout has -- 3.9 on macOS. A leaf that cannot be IMPORTED there takes the
    # whole hook down with an ImportError, which is a worse failure than a missing type narrowing:
    # the hook exists to tell a lane its adapter key is misspelled, and it cannot do that if it
    # will not load. TypeGuard is a typing-time construct with no runtime behaviour, so subscripting
    # a stand-in costs nothing at runtime and mypy still reads the real one on 3.12.
    class _TypeGuardFallback:
        def __getitem__(self, item):
            return bool

    TypeGuard = _TypeGuardFallback()  # type: ignore[assignment,misc]

from .util import resolve_env

OCCUPANCY_LEASE_SCHEMA = "tautline-occupancy-lease/v1"

# Per-worktree paths: `.ai-work/` is git-ignored lane state and never crosses worktrees, which is
# exactly the scope an occupancy lease needs.
OCCUPANCY_LEASE_PATH = ".ai-work/lane-lease.json"
OCCUPANCY_REVIEW_LEASE_PATH = ".ai-work/review-lease.json"
# Reserved here, written by the SessionStart seam in a later release: a session that finds a live
# foreign holder must not clobber it, so it leaves a presence record instead. Declared with its
# siblings so nothing else claims the path.
OCCUPANCY_PEERS_DIR = ".ai-work/occupancy-peers"

# Tuples, not lists: UPPER_CASE list-of-str constants are auto-collected into the policy-phrases
# SSOT (`dump-policy-phrases`), and these are configuration enums, not guard phrases.
OCCUPANCY_MODES = ("refuse", "auto-worktree", "observe")
OCCUPANCY_PRIMARY_CHECKOUT_MODES = ("report", "refuse")
OCCUPANCY_ACQUIRE_STATUSES = (
    "acquired",  # the worktree was free
    "refreshed",  # our own live lease, renewed
    "reclaimed",  # the previous holder is gone (dead session, elapsed TTL, or a corrupt record)
    "conflict",  # a LIVE peer session holds it; the caller decides whether to refuse or report
    "unresolved",  # we cannot name ourselves, so we must not claim (see below)
    "unavailable",  # the lease could not be written; degrade, never raise
)

OCCUPANCY_DEFAULT_TTL_MINUTES = 1440
DEFAULT_OCCUPANCY = {
    "enabled": True,
    "mode": "refuse",
    "primaryCheckout": "report",
    "ttlMinutes": OCCUPANCY_DEFAULT_TTL_MINUTES,
}

# Measured in the live harness 2026-08-09 by reading the exported environment, not by reading
# documentation. The name CLAUDE_SESSION_ID (with no CODE_) does NOT exist in any runtime measured
# here -- v1 of this plan specified it, which meant the env branch never fired and the fallback was
# always taken. Adding a runtime means MEASURING its exported names first and pinning them with a
# cross-invocation stability test.
OCCUPANCY_SESSION_ID_ENV = (
    "TAUTLINE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_COMPANION_SESSION_ID",
)
OCCUPANCY_SESSION_PID_ENV = ("TAUTLINE_SESSION_PID", "CLAUDE_PID")

# Shared with the fleet lease (`FLEET_MAX_TTL_MINUTES`), and pinned equal to it by a parity test.
# An unbounded TTL overflows `anchor + timedelta(minutes=ttl)`, and an OverflowError escaping a
# liveness predicate aborts the caller's whole scan -- so ONE absurd lease would disable every
# other one. A year is far beyond any real session.
OCCUPANCY_MAX_TTL_MINUTES = 60 * 24 * 365

# `os.kill()` raises OverflowError -- NOT an OSError -- for a pid outside the platform's pid_t, so
# a lease carrying 10**30 would abort the caller instead of reporting "stale". A pid is bounded by
# the C signed-int range everywhere this runs; anything larger is corruption, not a process.
OCCUPANCY_MAX_PID = 2**31 - 1

# How long a live-pid probe may keep a lease alive without a renewal. A live pid normally BEATS an
# elapsed TTL, so a working session is never evicted by a clock -- but pids are recycled, and an
# unbounded rule lets a recycled pid hold a worktree closed forever with no way back except a
# manual unlink. Past this horizon the lease falls back to TTL. Sessions renew at every session
# start, so nothing that is actually running gets anywhere near it.
OCCUPANCY_PID_TRUST_HORIZON_MINUTES = 60 * 24 * 7

# How long to wait for a peer's lease lock before giving up and running unlocked (which refuses to
# mutate, so the caller degrades to report-only). Generous for the work it guards -- one small read
# and one publish -- and bounded because the alternative is a startup hook that hangs behind a
# paused peer, which is worse than one that reports.
OCCUPANCY_LOCK_WAIT_SECONDS = 5.0

# Tolerance for a lease timestamp that sits in the future. Cross-host clocks drift and NTP steps
# happen, so a little slack is right; unbounded slack is not. On the TTL path the timestamp is the
# only evidence there is, so a far-future one would hold a worktree closed until that date plus its
# TTL, with no remedy but deleting the file by hand.
OCCUPANCY_MAX_FUTURE_SKEW_MINUTES = 60

# A lease is a small JSON object. Anything larger is not one, and reading it is how a lane gets
# stuck or exhausted before the parser ever sees the bytes.
OCCUPANCY_MAX_LEASE_BYTES = 64 * 1024


def _parse_utc(value: object) -> datetime | None:
    """Mirror of the fleet lease's timestamp discipline: total, and naive-means-UTC.

    Deliberately a local mirror rather than an import: leaf modules are what `cli.py` imports, not
    the reverse, and the carve that would relocate `fleet_parse_utc` into a shared home is parked.
    `tests/test_occupancy_lease.py` pins the two implementations equal over a shared input table so
    the mirror cannot drift into a second, subtly different truth model.
    """
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _valid_ttl(value: object) -> TypeGuard[int]:
    """A TypeGuard, not a bool: every caller converts the value it just validated, and a guard that
    does not narrow leaves each of those conversions defending itself again."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= OCCUPANCY_MAX_TTL_MINUTES
    )


def _ttl_live(lease: Mapping, now: datetime) -> bool:
    """TTL-only liveness: the fallback for a lease this host cannot probe by pid."""
    anchor = _parse_utc(lease.get("renewed_at") or lease.get("started_at") or "")
    ttl = lease.get("ttl_minutes")
    if anchor is None or not _valid_ttl(ttl):
        return False
    try:
        if anchor > now + timedelta(minutes=OCCUPANCY_MAX_FUTURE_SKEW_MINUTES):
            # A timestamp far in the future is corruption or a badly skewed clock, and on this
            # path -- no probeable pid -- it is the ONLY evidence there is. Honouring it would hold
            # the worktree closed until that future date plus the TTL, with no remedy but deleting
            # the file by hand. Malformed state must never outrank a live session.
            return False
    except (OverflowError, TypeError):
        return False
    try:
        return now <= anchor + timedelta(minutes=int(ttl))
    except (OverflowError, TypeError):
        # Belt and braces with the bound above: this predicate reads file-supplied data, so it has
        # to be TOTAL. A raise escaping here would abort the caller instead of reporting "stale".
        return False


def _usable_pid(value: object) -> int | None:
    """The pid if it is one this module will probe, else None. ONE definition, deliberately.

    `_lease_well_formed` and `occupancy_acquire` must agree about what a pid is, or acquire can
    publish a record its own liveness predicate immediately calls malformed -- returning "acquired"
    to a session while a peer is free to reclaim the worktree out from under it. `pid=True` is the
    sharp edge: `bool` is an `int`, so a hand-built identity carrying it sails through a naive
    isinstance check.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if 1 < value <= OCCUPANCY_MAX_PID else None


def _env_pid(raw: str) -> int | None:
    """A usable session pid from an environment value, or None. Never raises.

    `str.isdigit()` is NOT a safe guard for `int()`: it is true for characters `int()` REJECTS
    (`"²"` and other Unicode digit forms), and CPython caps integer parsing at 4300 digits, so a
    long-enough run of ASCII digits raises ValueError too. A malformed environment must make the
    identity unresolvable, not crash the gate that reads it.

    ASCII only, and bounded. `int("١٢٣")` succeeds and returns 123 -- no crash, but no runtime
    exports a pid in Arabic-Indic digits either, so accepting one means silently adopting a
    session number nobody wrote. Unresolvable is the honest reading of an identity we cannot
    recognise, and unresolvable degrades to report-only.
    """
    value = raw.strip()
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        return None
    try:
        pid = int(value)
    except ValueError:  # pragma: no cover - ascii-digit + length already exclude every known case
        return None
    return _usable_pid(pid)


def _anchor_trustworthy(lease: Mapping, now: datetime) -> bool:
    """Is this record's timestamp usable as evidence at all?

    Applied to EVERY path, not just the TTL one. Scoping it to TTL looked right -- "a live pid
    beats a clock" -- but the pid path reads the same timestamp through the trust horizon, so a
    decade-ahead `renewed_at` kept pid trust open for years. Combined with pid reuse, that is a
    stale or forged lease holding a worktree indefinitely on the strength of an unrelated live
    process. A timestamp beyond tolerated drift is corruption, and corruption is evidence of
    nothing.
    """
    anchor = _parse_utc(lease.get("renewed_at") or lease.get("started_at") or "")
    if anchor is None:
        return False
    try:
        return anchor <= now + timedelta(minutes=OCCUPANCY_MAX_FUTURE_SKEW_MINUTES)
    except (OverflowError, TypeError):
        return False


def _within_pid_trust_horizon(lease: Mapping, now: datetime) -> bool:
    anchor = _parse_utc(lease.get("renewed_at") or lease.get("started_at") or "")
    if anchor is None:
        return False
    try:
        return now <= anchor + timedelta(minutes=OCCUPANCY_PID_TRUST_HORIZON_MINUTES)
    except (OverflowError, TypeError):
        return False


def _lease_well_formed(lease: object) -> TypeGuard[dict]:
    """Does this record carry every field the liveness rules read, in a shape they can trust?

    The distinction that matters is `pid: null` versus `pid: "1234"`. Null is a LEGAL value written
    by a session whose identity was unresolved, and TTL governs it. A string, a bool, or a pid of
    0/1 is CORRUPTION, and a corrupt record must not be able to hold a worktree closed by falling
    through to whatever TTL happens to be next to it -- a malformed lease is treated as stale, the
    same fail-open posture as the fleet lease.

    `session_id` is required and must be a non-blank string, for the same reason. Foreignness
    compares session ids, so a record missing one compares unequal to EVERY resolved acquirer:
    without this check a single mangled field would hold the checkout closed against everyone
    until the pid died -- malformed state acting as a blocker, which is the posture inverted.
    """
    if not isinstance(lease, dict) or lease.get("schema") != OCCUPANCY_LEASE_SCHEMA:
        return False
    session_id = lease.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return False
    if session_id != session_id.strip():
        # A PADDED id is malformed, not merely ugly. Acquire stores the stripped form, so a record
        # carrying `" session-a "` -- from damaged state or a writer that is not this module --
        # would compare unequal to its own owner and lock that session out of its own worktree
        # until the pid horizon or TTL elapsed. One canonical form on disk; anything else is stale.
        return False
    host = lease.get("host")
    if not isinstance(host, str) or not host.strip():
        return False
    pid = lease.get("pid")
    if pid is not None and _usable_pid(pid) is None:
        return False
    if not _valid_ttl(lease.get("ttl_minutes")):
        return False
    return _parse_utc(lease.get("renewed_at") or lease.get("started_at") or "") is not None


def occupancy_session_identity(env: Mapping[str, str] | None = None) -> dict:
    """`{"session_id", "pid", "source"}` for the AGENT SESSION, never for this invocation.

    `source` is "env" when a runtime exported its session identity, and "unresolved" otherwise --
    which callers must treat as REPORT-ONLY: never claim, never refuse.

    There is deliberately NO process-derived fallback. `os.getppid()` is the per-invocation shell
    (a corpse seconds later), and the POSIX session leader (`os.getsid`) is worse in the way that
    matters: two agents launched from ONE terminal share a SID, so the fallback would hand them a
    single identity and report the second entrant as a "refresh" of the first -- silently merging
    exactly the collision this module exists to detect. A session leader can also outlive the agent
    under it, which would keep a dead agent's lease live indefinitely. An identity that is wrong is
    worse than an identity that is absent, because absent degrades to reporting while wrong
    reassures. Supporting a new runtime means MEASURING its exported names and adding them above,
    or exporting `TAUTLINE_SESSION_ID` / `TAUTLINE_SESSION_PID` from its launcher.
    """
    session_id = ""
    for name in OCCUPANCY_SESSION_ID_ENV:
        value = resolve_env(name, environ=env).strip()
        if value:
            session_id = value
            break
    pid = None
    for name in OCCUPANCY_SESSION_PID_ENV:
        parsed = _env_pid(resolve_env(name, environ=env))
        if parsed is not None:
            pid = parsed
            break
    if session_id or pid is not None:
        return {
            "session_id": session_id or f"pid-{pid}@{socket.gethostname()}",
            "pid": pid,
            "source": "env",
        }
    return {"session_id": "", "pid": None, "source": "unresolved"}


def occupancy_lease_is_live(lease: object, now: datetime) -> bool:
    """TOTAL over file-supplied data: a malformed lease must never block or crash a lane."""
    if not _lease_well_formed(lease):
        return False
    if not _anchor_trustworthy(lease, now):
        return False  # a timestamp beyond tolerated drift is corruption, on every path
    if str(lease.get("host") or "") != socket.gethostname():
        return _ttl_live(lease, now)  # another host's pids are not probeable from here
    pid = lease.get("pid")
    if pid is None:
        return _ttl_live(lease, now)  # identity was unresolved at write time
    if not _within_pid_trust_horizon(lease, now):
        # Long past any renewal, the pid is more likely recycled than the original session, so the
        # probe stops being evidence and TTL decides. Bounds the blast radius of pid reuse.
        return _ttl_live(lease, now)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # dead session -> auto-reclaim, no manual unlock
    except PermissionError:
        return True  # alive, owned by another uid
    except (OSError, OverflowError, ValueError):
        return _ttl_live(lease, now)
    # A LIVE PID BEATS AN ELAPSED TTL. A long-running session must never have its worktree reopened
    # to a second entrant because a clock ran out; TTL governs only the cases a pid cannot answer.
    return True


def occupancy_owner_of(record: Mapping | None, fallback: object = None) -> str:
    """The identity a lease is compared BY -- `owner` when present, `session_id` otherwise.

    The owner is a RECORD FIELD, not a relabelling of the session. Two things can hold a lease:
    a SESSION holds a worktree for as long as it is working there, and a review RUN holds its own
    lease for exactly the length of one invocation. Keying both on `session_id` would make a
    lane's second review round read as its own first one -- the same session, a different holder.

    Defaults to `session_id` so every lease written before this field existed, and every lane
    lease written after it, keeps its exact previous meaning. A record on disk that predates the
    field is legal, not malformed: rejecting those would strand live sessions mid-round.
    """
    source = record if isinstance(record, Mapping) else {}
    owner = str(source.get("owner") or "").strip()
    if owner:
        return owner
    if fallback is not None:
        return str(fallback).strip()
    return str(source.get("session_id") or "").strip()


def occupancy_lease_foreignness(
    lease: object, now: datetime, identity: Mapping
) -> tuple[bool, str]:
    """`(is_foreign, reason)`; reason in ("", "different-session", "unresolved-identity")."""
    if not occupancy_lease_is_live(lease, now):
        return False, ""
    # Both sides stripped, belt to the well-formedness braces: ownership is the one comparison
    # where a whitespace difference costs a session its own worktree, and this predicate is the
    # last place to catch a record that reached disk by some other route.
    mine = occupancy_owner_of(identity)
    if not mine:
        return True, "unresolved-identity"  # cannot prove it is ours -> report, never refuse
    theirs = occupancy_owner_of(lease)  # type: ignore[arg-type]
    return (theirs != mine), ("different-session" if theirs != mine else "")


@contextmanager
def _occupancy_lock(path: Path):
    """Serialize the read-decide-publish sequence for one lease path across processes.

    `os.link` already makes the FIRST publish mutually exclusive, but reclaim and release are
    read-then-write: without a critical section two entrants can both observe one dead holder and
    both believe they took the worktree, which is the failure this module exists to prevent.

    Yields True when a real kernel lock is held and False when the body runs best-effort (no
    `fcntl`, `flock` refused, or a peer held it past the bounded wait). It NEVER raises on lock
    failure and it never blocks a lane indefinitely on lock state -- same posture as
    `fleet_claims_lock`, and for the same reason: a coordination aid that can strand a lane is
    worse than the collision it prevents.

    The False path is not a weaker version of the True path. `occupancy_write_lease` refuses to
    MUTATE without a lock and `occupancy_release` refuses to unlink, so an unlocked caller can only
    publish into an empty slot -- which `os.link` arbitrates on its own.
    """
    lock_path = Path(path).parent / f".{Path(path).name}.lock"
    locked = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # O_NONBLOCK, and then verify what we actually opened. `open("a")` on a FIFO blocks waiting
        # for a reader -- before the bounded loop below is ever reached -- so a malformed lock node
        # could hang lane startup indefinitely, straight through the fail-open contract. A lock
        # that is not a regular file is not a lock, and we run unlocked instead.
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NONBLOCK", 0), 0o644)
    except OSError:
        yield False
        return
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        # Close before yielding: an early return here skips the cleanup below, and a long-lived
        # process calling acquire/release in a loop would leak one descriptor per call until it
        # ran out of them -- a slow strangling of the very lane the fail-open path protects.
        try:
            os.close(fd)
        except OSError:
            pass
        yield False
        return
    try:
        try:
            import fcntl  # type: ignore[import-not-found]

            # NON-BLOCKING, with a bounded wait. A plain LOCK_EX waits forever, so one paused peer
            # holding this lock would hang every later lane-start and review round -- and they
            # would never reach the fail-open path this whole contextmanager exists to provide. A
            # startup hook that hangs is worse than one that reports. Past the deadline we run
            # unlocked, which means mutation is refused and the caller degrades to report-only.
            deadline = time.monotonic() + OCCUPANCY_LOCK_WAIT_SECONDS
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
        except (ImportError, OSError, AttributeError):
            locked = False
        yield locked
    finally:
        try:
            if locked:
                import fcntl  # type: ignore[import-not-found]

                fcntl.flock(fd, fcntl.LOCK_UN)
        except (ImportError, OSError, AttributeError):
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def occupancy_read_lease(path: Path) -> dict | None:
    """The lease at `path`, or None for anything that is not a readable JSON object.

    Opened `O_NONBLOCK` and checked with `fstat` on the descriptor we hold, not with a `stat` on
    the name -- otherwise the check and the open describe two different files. Two shapes at a
    lease path would otherwise defeat totality before the parser is ever reached: a FIFO, where a
    plain read blocks until someone writes (a hang, in a SessionStart hook contractually forbidden
    to block), and a very large regular file, where it exhausts memory. Neither is a lease, so
    neither is read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > OCCUPANCY_MAX_LEASE_BYTES:
            return None
        # Read to EOF, not once. `os.read` is permitted to return a SHORT read, and network and
        # FUSE filesystems do. A truncated read parses as invalid JSON, which this returns as None
        # -- and `occupancy_acquire` reads None-over-an-existing-file as a wreck to reclaim, so a
        # short read of a LIVE foreign holder would hand the worktree to a second session.
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > OCCUPANCY_MAX_LEASE_BYTES:
                return None
            chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)
    try:
        lease = json.loads(raw)
    except (ValueError, TypeError):
        return None
    except RecursionError:
        # Deeply nested JSON blows the parser's stack, and RecursionError is not a ValueError. An
        # unreadable lease must read as stale, never abort the startup hook that read it -- the
        # same reason the fleet loader treats a malformed record as expired rather than raising.
        return None
    return lease if isinstance(lease, dict) else None


class OccupancyUnserialized(Exception):
    """A mutation was requested that cannot be made safe without a real kernel lock."""


def occupancy_write_lease(
    path: Path, lease: Mapping, *, replacing: bool = False, serialized: bool = False
) -> Path:
    """Publish `lease` at `path` atomically. Raises FileExistsError if another entrant won.

    ONE rule makes this safe, and two earlier versions each got it wrong by trying to be cleverer:

        **Without a real kernel lock, only a publish into an EMPTY slot is permitted.
        Mutating an existing record requires the lock.**

    Publishing into an empty slot needs no lock because `os.link` arbitrates it: exactly one
    contender can create the destination and the rest get FileExistsError. Mutation has no such
    primitive. `os.replace` obviously double-awards. So does unlink-then-link, which looks atomic
    and is not: contender A unlinks the stale record and links its own, then contender B -- still
    holding its stale read -- unlinks *A's live record* and links its own, and both are told they
    reclaimed the worktree. There is no POSIX "unlink only if the content is still what I read",
    so an unserialized mutation is refused (`OccupancyUnserialized`) and the caller degrades to
    report-only rather than issuing a false award.

    This costs nothing in practice: `flock` is available on every filesystem this runs on, so the
    unserialized path is reached only where the kernel refuses locks entirely -- and there,
    reporting beats lying. `os.replace` appears exactly once below, guarded by `serialized`, for
    the filesystems that refuse hard links.

    `O_CREAT|O_EXCL` on the TEMP name excludes nothing on its own -- the temp name is per-process.
    """
    if replacing and not serialized:
        raise OccupancyUnserialized("cannot safely replace an existing lease without a lock")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(lease), indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > OCCUPANCY_MAX_LEASE_BYTES:
        # The reader refuses anything this large, so publishing it would announce a holder that
        # every subsequent read discards -- the caller told "acquired" while peers reclaim freely.
        raise OccupancyUnserialized("lease payload exceeds the size the reader will accept")
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if replacing:
            os.replace(tmp, path)  # safe ONLY because `serialized` is proven above
            return path
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise  # a real holder landed first; the caller re-reads and reports the conflict
        except OSError:
            # Hard links are unsupported here (some network and virtualised filesystems refuse
            # them), so nothing arbitrates this publish but the lock. With it, replace is safe;
            # without it there is no way to tell a winner from a loser, and inventing one is how
            # both entrants "win".
            if not serialized:
                raise OccupancyUnserialized("no hard links and no lock; cannot arbitrate") from None
            os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return path


def occupancy_acquire(
    path: Path,
    identity: Mapping,
    now: datetime,
    *,
    branch: str = "",
    ttl_minutes: object = None,
    owner: str | None = None,
) -> tuple[str, dict | None]:
    """Take, refresh, or reclaim the lease at `path`. Returns `(status, lease-or-holder)`.

    Path-parameterized on purpose: the review-round lease (WS3) is this same mechanism at a
    different path with a shorter TTL, so there is exactly one liveness model in the framework.

    `status` is one of `OCCUPANCY_ACQUIRE_STATUSES`. Only "conflict" carries the OTHER session's
    record; "unresolved" and "unavailable" carry None and mean *report, do not refuse*.
    """
    # Stripped, because `_lease_well_formed` strips: a session id of " " is truthy here and
    # malformed there, so an unstripped guard writes a record the reader immediately discards.
    session_id = str((identity or {}).get("session_id") or "").strip()
    if not session_id:
        # A lease written under an empty session id reads foreign to every later session INCLUDING
        # the one that wrote it: a phantom holder nothing can ever release. Refuse to write it.
        return "unresolved", None
    # Normalize ONCE, at entry, and use the normalized identity for every downstream comparison.
    # Normalizing at the point of use is what produced the "writer accepted, reader rejected" class
    # three times over; the same shape reappeared in ownership checks, where an unstripped
    # comparison made a session's own lease read as foreign.
    identity_pid = _usable_pid((identity or {}).get("pid"))
    identity = {**(identity or {}), "session_id": session_id, "pid": identity_pid}
    # Normalized once, beside the session id, for the same reason: comparing an unstripped owner
    # against a stripped one is how a holder reads its own lease as foreign.
    owner_key = str(owner or "").strip()
    if owner_key:
        identity = {**identity, "owner": owner_key}

    # A TTL the liveness predicate would reject is a lease that is dead the moment it lands, so an
    # unusable value falls back to the default rather than being written through.
    ttl = ttl_minutes if _valid_ttl(ttl_minutes) else OCCUPANCY_DEFAULT_TTL_MINUTES

    # Read, decide, and publish inside ONE critical section. Reclaiming is a read-then-write, so
    # without this two entrants can both observe the same dead holder and both believe they won --
    # and `locked` is threaded into the publish, which refuses to MUTATE when it is False.
    with _occupancy_lock(path) as locked:
        existing = occupancy_read_lease(path)

        if not locked and identity_pid is None:
            # Do not take what we could never give back. Unlocked, release is a no-op; a pid-less
            # lease is TTL-only, so nothing would read it dead either. Publishing here would hold
            # the worktree for the whole TTL after this session ended, with no remedy but deleting
            # the file. Same reasoning as unresolved-never-claims: decline instead.
            #
            # But LOOK FIRST. Declining before reading turns the one case this module exists to
            # catch -- a live foreign holder -- into "unavailable", which the status contract
            # documents as report-only, so a caller following that contract would admit the second
            # session. Refusing to publish and failing to notice a holder are different answers
            # and must not share a code path.
            if existing is not None and occupancy_lease_foreignness(existing, now, identity)[0]:
                return "conflict", existing
            return "unavailable", None

        started_at = now.isoformat()
        # A file that exists but does not parse still had a holder; saying "acquired" over it would
        # report a free worktree where there was a wreck. Report the reclaim so the caller can say
        # so.
        status = "acquired" if existing is None and not os.path.lexists(path) else "reclaimed"

        if existing is not None:
            foreign, _reason = occupancy_lease_foreignness(existing, now, identity)
            if foreign:
                return "conflict", existing
            if occupancy_lease_is_live(existing, now):
                status = "refreshed"
                started_at = str(existing.get("started_at") or started_at)

        lease = {
            "schema": OCCUPANCY_LEASE_SCHEMA,
            "session_id": session_id,
            # Normalized through the SAME predicate the reader uses: a hand-built identity
            # carrying `pid=True` or an out-of-range value must not be published as a record our
            # own liveness check then calls malformed -- that hands the caller "acquired" while a
            # peer is free to reclaim the worktree.
            "pid": identity_pid,
            "identity_source": str(identity.get("source") or ""),
            # Forensics only: which CLI invocation last wrote this record. Never probed for
            # liveness -- probing it is the v1 bug this module exists to not repeat.
            "writer_pid": os.getpid(),
            "host": socket.gethostname(),
            "branch": str(branch or ""),
            "started_at": started_at,
            "renewed_at": now.isoformat(),
            "ttl_minutes": ttl,
        }
        # Written only when the caller NAMES one. A lane lease carries no owner, so its record is
        # byte-identical to every one written before this field existed -- which is what keeps the
        # existing suite passing unmodified and old records readable.
        if owner_key:
            lease["owner"] = owner_key
        if not _lease_well_formed(lease):
            # THE CLASS FIX. Three separate findings were one defect wearing different fields -- a
            # pid, a session id, a payload size -- that the writer accepted and the reader
            # rejected. Each time acquire returned "acquired" while every peer read the record as
            # malformed and reclaimed the worktree underneath it. Rather than guard field by field
            # and wait for the fourth, the record is checked HERE with the reader's own
            # well-formedness predicate before publication: if we would not believe this lease, we
            # do not write it. (SHAPE only, deliberately -- not liveness. A caller whose session
            # pid is genuinely dead should still record that truthfully; the record then reads
            # dead, which is correct rather than contradictory.)
            return "unavailable", None

        try:
            occupancy_write_lease(
                path, lease, replacing=status != "acquired", serialized=locked
            )
        except FileExistsError:
            # We lost the publish. This is the lock-unavailable path's real arbiter: whoever won
            # the link owns the worktree, and we report what actually landed rather than
            # overwriting it. Never retry the write -- retrying is how both entrants "win".
            raced = occupancy_read_lease(path)
            if raced is not None and occupancy_lease_is_live(raced, now):
                foreign, _reason = occupancy_lease_foreignness(raced, now, identity)
                if foreign:
                    return "conflict", raced
                # We lost the publish to OURSELVES -- two invocations of one session racing for an
                # empty path. Reporting a conflict there would have a session refuse its own lease.
                return "refreshed", raced
            return "unavailable", None
        except (OccupancyUnserialized, OSError):
            # Either a mutation with no lock to make it safe, or the write genuinely failed.
            # Both degrade to report-only: the caller neither claims nor refuses.
            return "unavailable", None
        return status, lease


def occupancy_release(path: Path, identity: Mapping) -> bool:
    """Remove the lease at `path` only if it is OURS. Releasing a peer's lease is a no-op.

    Liveness is deliberately NOT consulted: a session releasing in a `finally` after its own round
    crashed still owns the record it wrote, and must be able to clear it.
    """
    # Stripped, to match what acquire STORED. An unstripped comparison makes a session whose id
    # carries surrounding whitespace read its own lease as foreign and refuse to release it.
    mine = occupancy_owner_of(identity)
    if not mine:
        return False
    # Same critical section as acquire. A delete has no no-replace analogue -- there is no POSIX
    # "unlink only if the content is still mine" -- so unlike publication, release cannot arbitrate
    # a lost race after the fact. Without a real lock it therefore does NOTHING rather than risk
    # deleting a lease a peer reclaimed between our read and our unlink.
    #
    # What that degradation costs, stated exactly rather than waved away: a lease carrying a
    # session PID reads dead on the very next probe, so an unreleased one is reclaimed
    # immediately. A lease whose identity supplied a session id but NO pid is TTL-only, so an
    # unreleased one stays live until its TTL elapses -- up to a day at the default. Every runtime
    # measured here exports both, so the pid-less case is the exception; where it matters (the
    # review lease, PR4) the caller passes a short TTL for exactly this reason.
    with _occupancy_lock(path) as locked:
        if not locked:
            return False
        lease = occupancy_read_lease(path)
        # BOTH SIDES THROUGH THE SAME RESOLVER. `mine` is the owner -- the run id for a review
        # lease -- and comparing it against the record's raw `session_id` meant a review lease was
        # never its holder's to release, so a finished round stayed held until reclamation. The
        # one-fact-two-readers shape, in the release path this time. Codex R1 P2.
        if not isinstance(lease, dict) or occupancy_owner_of(lease) != mine:
            return False
        try:
            Path(path).unlink()
        except OSError:
            return False
        return True
