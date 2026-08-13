"""Item 68 PR3: the CONCURRENT lane-status finding.

PR2 gave `lane-start` teeth. This is the report saying the same thing where nothing refuses --
because a session that never ran `lane-start` still has to be visible to the one that did.
"""

from __future__ import annotations

from tautline_methodology.lane_status import (
    LANE_STATUS_FINDING_ORDER,
    LANE_STATUS_RESOLVING_FINDINGS,
    compute_lane_status_findings,
)


def _facts(**overrides):
    base = {
        "branch": "feat/x",
        "integration": "main",
        "remote": "origin",
        "upstream_gone": False,
        "detached": False,
        "merged": False,
        "dirty": False,
        "squatted_by": "",
        "claim_state": "not-checked",
        "foreign_lease": None,
        "unverified": [],
    }
    base.update(overrides)
    return base


def _ids(facts):
    return [f["id"] for f in compute_lane_status_findings(facts)]


def test_a_foreign_holder_lease_is_reported(cli=None) -> None:
    facts = _facts(foreign_lease={"session_id": "other", "branch": "feat/theirs"})

    findings = compute_lane_status_findings(facts)
    concurrent = [f for f in findings if f["id"] == "CONCURRENT"]

    assert concurrent, "a live peer holding this worktree must be reported"
    assert concurrent[0]["severity"] == "drift"
    assert "other" in concurrent[0]["detail"]
    assert "feat/theirs" in concurrent[0]["detail"]
    assert "overwrite each other" in concurrent[0]["detail"], "say what actually goes wrong"


def test_a_peer_record_alone_is_enough(cli=None) -> None:
    """The lane-start-less intruder: a session that never ran `lane-start` holds no lease, but its
    peer record still says it is here. Reporting only on the holder lease would make the one kind
    of session that skipped the gate the one kind nothing notices."""
    facts = _facts(foreign_lease={"session_id": "drive-by"})

    assert "CONCURRENT" in _ids(facts)


def test_no_foreign_lease_is_silent(cli=None) -> None:
    assert _ids(_facts()) == []


def test_concurrent_leads_the_report(cli=None) -> None:
    facts = _facts(
        foreign_lease={"session_id": "other"}, dirty=True, detached=True
    )

    assert _ids(facts)[0] == "CONCURRENT", "it outranks every finding it can co-occur with"


def test_a_rerun_cannot_clear_it(cli=None) -> None:
    """The SQUATTED precedent. Ending the report with 'rerun lane-status' on a live peer promises
    a remediation that does not exist, and the lane loops."""
    assert "CONCURRENT" not in LANE_STATUS_RESOLVING_FINDINGS
    assert LANE_STATUS_FINDING_ORDER[0] == "CONCURRENT"


def test_dirty_is_reworded_only_under_a_foreign_lease(cli=None) -> None:
    """The no-lease DIRTY line is pinned byte-identical by adapter greps and the policy-phrase
    SSOT, so the rewording must be conditional -- a blanket change would break callers that never
    see a peer at all."""
    alone = compute_lane_status_findings(_facts(dirty=True))
    dirty_alone = [f for f in alone if f["id"] == "DIRTY"][0]

    assert dirty_alone["detail"] == "uncommitted changes inherited from a prior session"
    assert dirty_alone["severity"] == "info"

    shared = compute_lane_status_findings(
        _facts(dirty=True, foreign_lease={"session_id": "other"})
    )
    dirty_shared = [f for f in shared if f["id"] == "DIRTY"][0]

    assert dirty_shared["severity"] == "drift", "whose changes these are is now in doubt"
    assert "may not be yours" in dirty_shared["detail"]


# --- the records the collector reads must actually be written -------------------------------


def test_losing_the_lease_race_writes_a_peer_record(cli, tmp_path, monkeypatch) -> None:
    """Codex R1 P2. Losing the race is exactly when this session is the INVISIBLE one -- it holds
    nothing, so the holder's own `lane-status` would report a clean worktree while two sessions
    edit it. My first version of this suite asserted the 'peer record alone' case by feeding the
    fact in directly, which proved nothing about whether anything ever creates one."""
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "b", "pid": 2})
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/b")
    monkeypatch.setattr(cli, "occupancy_acquire", lambda *a, **k: ("conflict", {"session_id": "a"}))

    cli.occupancy_record_session({}, tmp_path)

    peers = list((tmp_path / ".ai-work" / "occupancy-peers").glob("*.json"))
    assert peers, "the losing session must leave a trace"
    import json as _json
    record = _json.loads(peers[0].read_text())
    assert record["session_id"] == "b"
    assert record["branch"] == "feat/b"


def test_a_peer_record_is_named_by_hash_not_by_session_id(cli, tmp_path, monkeypatch) -> None:
    """A session id can contain path separators; using it as a filename writes outside the dir."""
    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/x")
    path = cli.occupancy_write_peer_record(tmp_path, {"session_id": "../../escape", "pid": 1}, {})

    assert path is not None
    assert path.parent == tmp_path / ".ai-work" / "occupancy-peers"
    assert ".." not in path.name


def test_the_reader_refuses_a_fifo_and_an_oversized_file(cli, tmp_path) -> None:
    """Codex R1 P2: this runs inside lane-status's deadline against whatever is on disk. A FIFO
    blocks forever; an oversized file eats a budget the hook does not have."""
    import os

    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo)
    assert cli.occupancy_read_record(fifo) is None, "a FIFO is not a record"

    big = tmp_path / "big.json"
    big.write_text("{}" + " " * (cli.OCCUPANCY_RECORD_MAX_BYTES + 10))
    assert cli.occupancy_read_record(big) is None, "oversized is not a record"

    good = tmp_path / "good.json"
    good.write_text('{"session_id": "x"}')
    assert cli.occupancy_read_record(good) == {"session_id": "x"}


def test_a_present_but_unreadable_record_is_reported_not_ignored(cli, tmp_path, monkeypatch):
    """'I could not look' must not render as 'nobody is here'."""
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "lease.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "me"})
    (tmp_path / "lease.json").write_text("{not json")
    unverified = []

    assert cli.lane_status_foreign_lease(tmp_path, unverified) is None
    assert any("unreadable" in u for u in unverified)


def test_a_written_peer_record_survives_the_liveness_predicate(cli, tmp_path, monkeypatch) -> None:
    """Codex R2 P2, and the sharpest finding of this PR. The record I wrote omitted `schema` and
    used `hostname` where `_lease_well_formed` requires `host`, so EVERY peer record was discarded
    as malformed and the peer-record-only case never fired -- while the tests above still passed,
    because they fed the fact in rather than round-tripping it. Writer and reader must share one
    vocabulary."""
    from datetime import datetime, timezone

    import os

    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/b")
    # A LIVE pid, because liveness is what is under test: a record for a dead process is correctly
    # not live, and asserting on one would prove the opposite of what this test is for.
    path = cli.occupancy_write_peer_record(tmp_path, {"session_id": "b", "pid": os.getpid()}, {})

    import json as _json
    record = _json.loads(path.read_text())

    assert cli.occupancy_lease_is_live(record, datetime.now(timezone.utc)) is True, (
        "a record the reader rejects is a record that was never written"
    )


def test_the_holder_sees_a_peer_that_never_ran_lane_start(cli, tmp_path, monkeypatch) -> None:
    """End to end through the real files: B loses the race and writes a peer record; A's later
    lane-status must find it. This is the case the earlier fixture-fed tests could not prove."""
    import os

    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/b")
    cli.occupancy_write_peer_record(tmp_path, {"session_id": "b", "pid": os.getpid()}, {})

    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "absent.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "a", "pid": 1})
    unverified = []

    found = cli.lane_status_foreign_lease(tmp_path, unverified)

    assert found is not None, "the holder must see the drive-by session"
    assert found["session_id"] == "b"


def test_non_utf8_bytes_do_not_escape_the_reader(cli, tmp_path) -> None:
    """UnicodeDecodeError is not an OSError, so it escaped the never-raises contract and collapsed
    the whole lane-status run to a generic UNVERIFIED."""
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"session_id": "\xff\xfe"}')

    assert cli.occupancy_read_record(bad) is None


def test_a_disabled_lane_reports_nothing_even_with_a_live_lease(cli, tmp_path, monkeypatch):
    """Codex R3 P2. `lane-start` and the SessionStart seam both honour the opt-out; the collector
    did not -- so a lane that had explicitly disabled occupancy still got CONCURRENT from an old
    live lease, most sharply right after flipping the adapter while a peer's lease is running.
    One switch, every reader."""
    import os

    monkeypatch.setattr(cli, "run_git", lambda t, a: "feat/b")
    cli.occupancy_write_peer_record(tmp_path, {"session_id": "b", "pid": os.getpid()}, {})
    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "absent.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "a", "pid": 1})

    # The collector still finds it when occupancy is ON ...
    assert cli.lane_status_foreign_lease(tmp_path, []) is not None
    # ... and the fact is gated on the same switch the other two readers use.
    assert cli.occupancy_enabled({"fleet": {"occupancy": {"enabled": False}}}) is False
    assert cli.occupancy_enabled({"fleet": {"enabled": False}}) is False


def test_deeply_nested_json_does_not_escape_the_reader(cli, tmp_path) -> None:
    """RecursionError is not JSONDecodeError, so it escaped and dropped the whole hook to
    'lane status could not be computed' instead of naming one bad record."""
    bomb = tmp_path / "deep.json"
    # 4,000 levels parses fine on CPython; 20,000 is past the recursion limit and is what the
    # reader must survive. Measured, not guessed -- an under-deep fixture makes this test pass
    # against the very mutant it exists to catch.
    bomb.write_text("[" * 20000 + "]" * 20000)

    assert cli.occupancy_read_record(bomb) is None


def test_an_oversized_integer_is_a_parse_failure_like_any_other(cli, tmp_path) -> None:
    """Codex R4 P2. A JSON integer past Python's digit limit raises a PLAIN ValueError, not a
    JSONDecodeError -- so catching the parent covers every parse failure at once rather than
    growing an exception tuple per exotic input."""
    huge = tmp_path / "huge.json"
    huge.write_text('{"session_id": ' + "9" * 5000 + "}")

    assert cli.occupancy_read_record(huge) is None


def test_the_peer_scan_is_bounded_and_says_so(cli, tmp_path, monkeypatch) -> None:
    """Codex R4 P2. Nothing prunes peer records, so a long-lived busy checkout accumulates them
    and scanning every one can spend the whole SessionStart budget -- a hook that misses its
    deadline is a hook that did not run."""
    peers = tmp_path / ".ai-work" / "occupancy-peers"
    peers.mkdir(parents=True)
    for i in range(cli.OCCUPANCY_PEER_SCAN_LIMIT + 10):
        (peers / f"{i:04d}.json").write_text("{}")

    monkeypatch.setattr(cli, "occupancy_lease_path", lambda t: tmp_path / "absent.json")
    monkeypatch.setattr(cli, "occupancy_session_identity", lambda: {"session_id": "a"})
    unverified = []

    cli.lane_status_foreign_lease(tmp_path, unverified)

    assert any("stopped after" in u and "examined" in u for u in unverified), (
        "a bounded scan must SAY it was bounded -- silent truncation reads as 'nobody is here'"
    )


def test_the_peer_scan_does_not_stat_the_whole_directory(cli, tmp_path, monkeypatch) -> None:
    """Codex R2 P2, raised twice. Sorting by mtime and then slicing limited how many records were
    PARSED but not how many were STATTED -- and 'newest 64' could drop an older long-lived LIVE
    peer behind newer stale ones. Liveness is the criterion that matters, so the scan stops at the
    cap without ranking candidates it does not need to rank."""
    import inspect

    source = inspect.getsource(cli.lane_status_foreign_lease)

    assert "os.scandir" in source, "the directory must be walked lazily"
    assert "sorted(" not in source, "no full-directory sort before the cap"


def test_the_reader_checks_the_object_it_reads(cli) -> None:
    """Codex R3 P2. A stat-then-open pair can be defeated by swapping a FIFO in between, and
    `.ai-work/occupancy-peers` is written by other local processes -- an ordinary race, not an
    exotic one. The open must come first, non-blocking, with the fstat asked of the descriptor."""
    import inspect

    source = inspect.getsource(cli.occupancy_read_record)

    assert "O_NONBLOCK" in source, "even a FIFO that slips through must not block the open"
    assert "os.fstat(fd)" in source, "the check must be on the descriptor, not the name"
    assert "path.stat()" not in source, "no stat-then-open pair remains"


def test_a_short_read_does_not_truncate_a_valid_record(cli, tmp_path, monkeypatch) -> None:
    """Codex R4 P2. A single os.read may return fewer bytes than asked -- ordinary on network and
    FUSE filesystems -- and a PREFIX of a valid record parses as unreadable, so a live peer would
    go unreported and a spurious UNVERIFIED line would appear in its place."""
    import os as _os

    record = tmp_path / "peer.json"
    body = '{"session_id": "b", "branch": "' + "x" * 500 + '"}'
    record.write_text(body)

    real_read = _os.read
    calls = {"n": 0}

    def short_read(fd, n):
        # One byte at a time: the pathological end of what a short read can be.
        calls["n"] += 1
        return real_read(fd, 1)

    monkeypatch.setattr(cli.os, "read", short_read)

    got = cli.occupancy_read_record(record)

    assert got is not None, "a valid record must survive a short read"
    assert got["session_id"] == "b"
    assert calls["n"] > 1, "the loop was actually exercised"
