"""Fleet Governor state core: common-dir resolution, lease lifecycle, fail-open reads."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _init_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    (target / "README.md").write_text("seed\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-q", "-m", "seed")


def _lease(cli, *, lease_id="abc123", worktree="/tmp/wt-a", globs=("src/**",), ttl=240):
    now = datetime.now(timezone.utc)
    return {
        "schema": cli.FLEET_LEASE_SCHEMA,
        "lease_id": lease_id,
        "worktree_path": worktree,
        "branch": "lane-a",
        "goal_ref": "goal-1",
        "globs": list(globs),
        "claimed_at": now.isoformat(),
        "renewed_at": now.isoformat(),
        "ttl_minutes": ttl,
        "session": {"pid": 1234, "host": "test", "started_at": now.isoformat()},
        "note": "",
    }


def test_fleet_state_dir_is_shared_across_worktrees(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = tmp_path / "wt-b"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "lane-b")
    try:
        main_dir = cli.fleet_state_dir(repo)
        wt_dir = cli.fleet_state_dir(wt)
        assert main_dir is not None and wt_dir is not None
        assert main_dir.resolve() == wt_dir.resolve()
        assert main_dir.name == "tautline-fleet"
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
            check=False, capture_output=True,
        )


def test_fleet_state_dir_none_outside_git(cli, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cli.fleet_state_dir(plain) is None


def test_write_and_load_lease_roundtrip(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    lease = _lease(cli)
    path = cli.write_fleet_lease(repo, lease)
    assert path.name == "abc123.json"
    loaded = cli.load_fleet_leases(repo)
    assert len(loaded) == 1
    assert loaded[0]["lease_id"] == "abc123"
    assert loaded[0]["schema"] == "tautline-fleet-lease/v1"


def test_write_lease_refuses_id_collision(cli, tmp_path):
    import pytest

    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli))
    with pytest.raises(FileExistsError):
        cli.write_fleet_lease(repo, _lease(cli))


def test_write_lease_publishes_atomically_and_leaves_no_temp(cli, tmp_path):
    """The guard scans leases/ WITHOUT the claim lock, so a lease file must never be
    observable partially written. Publication is a single atomic link of an already
    complete file, and the dot-prefixed temp must not survive or be globbed."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli))
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    assert [p.name for p in sorted(leases_dir.glob("*.json"))] == ["abc123.json"]
    # No temp residue of any kind (the temp name is dot-prefixed, so glob misses it).
    assert [p.name for p in leases_dir.iterdir()] == ["abc123.json"]
    # The published file is complete, parseable JSON -- never a truncated prefix.
    payload = json.loads((leases_dir / "abc123.json").read_text(encoding="utf-8"))
    assert payload["lease_id"] == "abc123"
    assert payload["globs"] == ["src/**"]
    # "_path" is a load-time annotation only; it must never reach the file.
    assert "_path" not in payload


def test_lease_is_live_ttl_boundaries(cli):
    now = datetime.now(timezone.utc)
    lease = _lease(cli, ttl=60)
    assert cli.lease_is_live(lease, now) is True
    lease["renewed_at"] = (now - timedelta(minutes=61)).isoformat()
    assert cli.lease_is_live(lease, now) is False
    # Missing renewed_at falls back to claimed_at.
    del lease["renewed_at"]
    lease["claimed_at"] = (now - timedelta(minutes=1)).isoformat()
    assert cli.lease_is_live(lease, now) is True


def test_corrupt_lease_is_skipped_and_logged_never_raised(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli))
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    (leases_dir / "broken.json").write_text("{not json", encoding="utf-8")
    loaded = cli.load_fleet_leases(repo)  # must not raise
    assert [entry["lease_id"] for entry in loaded] == ["abc123"]
    log_path = cli.fleet_state_dir(repo) / "fleet.log"
    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["event"] == "lease_expired_observed" for e in events)


def test_invalid_utf8_lease_is_skipped_never_raised(cli, tmp_path):
    # read_text(encoding="utf-8") raises UnicodeDecodeError (a ValueError, NOT an
    # OSError or JSONDecodeError) on undecodable bytes: fail-open must cover it.
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli))
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    (leases_dir / "binary.json").write_bytes(b"\xff\xfe\x00 not utf-8")
    loaded = cli.load_fleet_leases(repo)  # must not raise
    assert [entry["lease_id"] for entry in loaded] == ["abc123"]


def test_malformed_lease_record_treated_as_stale(cli, tmp_path):
    # Schema-correct but structurally malformed records must never reach the
    # conflict predicate: they can only ever produce a bogus block.
    repo = tmp_path / "repo"
    _init_repo(repo)
    for name, mutate in (
        ("aaaa01", lambda rec: rec.pop("worktree_path")),
        ("aaaa02", lambda rec: rec.__setitem__("globs", "src/**")),
        ("aaaa03", lambda rec: rec.__setitem__("ttl_minutes", 0)),
        ("aaaa04", lambda rec: rec.__setitem__("renewed_at", "not-a-timestamp")),
    ):
        bad = _lease(cli, lease_id=name)
        if name == "aaaa04":
            bad["claimed_at"] = "not-a-timestamp"
        mutate(bad)
        cli.write_fleet_lease(repo, bad)
    assert cli.load_fleet_leases(repo) == []
    log_path = cli.fleet_state_dir(repo) / "fleet.log"
    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(1 for e in events if "malformed" in str(e.get("detail", ""))) == 4


def test_hostile_lease_identity_is_malformed_not_live(cli, tmp_path):
    # lease_id reaches a printed shell command and worktree_path drives identity;
    # both are read from a file any process can write. Bad values must fail open.
    repo = tmp_path / "repo"
    _init_repo(repo)
    for name, key, value in (
        ("shelly", "lease_id", "abc; rm -rf /"),
        ("spacey", "lease_id", "not hex at all"),
        ("relative", "worktree_path", "relative/lane"),
    ):
        # Base id is valid hex so each case is rejected for its OWN field.
        bad = _lease(cli, lease_id="beef01")
        bad[key] = value
        # Write directly: write_fleet_lease names the file from lease_id, and
        # these ids are deliberately unfit to be filenames.
        leases_dir = cli.fleet_state_dir(repo) / "leases"
        leases_dir.mkdir(parents=True, exist_ok=True)
        (leases_dir / f"{name}.json").write_text(json.dumps(bad), encoding="utf-8")
    assert cli.load_fleet_leases(repo) == []


def test_fleet_config_defaults_and_validation(cli):
    import pytest

    assert cli.fleet_config({}) == cli.DEFAULT_FLEET
    cfg = cli.fleet_config({"fleet": {"enforcement": "observe"}})
    assert cfg["enforcement"] == "observe"
    assert cfg["enabled"] is True
    with pytest.raises(SystemExit):
        cli.fleet_config({"fleet": {"enforcement": "bogus"}})
    with pytest.raises(SystemExit):
        cli.fleet_config({"fleet": []})


def test_absurd_ttl_is_malformed_and_never_raises(cli, tmp_path):
    """An unbounded ttl_minutes overflows `anchor + timedelta(minutes=ttl)`. That
    OverflowError escapes lease_is_live and aborts the caller's WHOLE conflict scan,
    so ONE absurd lease stops every other live lease from being enforced. Bounded at
    write time and treated as malformed at read time; the predicate is total either way."""
    now = datetime.now(timezone.utc)
    for ttl in (cli.FLEET_MAX_TTL_MINUTES + 1, 5_000_000_000, 10**18):
        lease = _lease(cli, ttl=ttl)
        assert cli.fleet_lease_well_formed(lease) is False, ttl
        assert cli.lease_is_live(lease, now) is False, ttl  # must not raise
    ok = _lease(cli, ttl=cli.FLEET_MAX_TTL_MINUTES)
    assert cli.fleet_lease_well_formed(ok) is True
    assert cli.lease_is_live(ok, now) is True

    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli, lease_id="beef02", ttl=5_000_000_000))
    assert cli.load_fleet_leases(repo) == []


def test_deeply_nested_lease_json_never_raises(cli, tmp_path):
    """json.loads raises RecursionError -- a RuntimeError, NOT a ValueError -- on deeply
    nested input. An escaping raise abandons every lease sorting after the bad file."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli, lease_id="0zzzz1".replace("z", "a")))
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    (leases_dir / "0deep.json").write_text("[" * 20000 + "]" * 20000, encoding="utf-8")
    loaded = cli.load_fleet_leases(repo)  # must not raise
    assert [entry["lease_id"] for entry in loaded] == ["0aaaa1"]


def test_nul_byte_worktree_path_is_malformed_not_a_raise(cli, tmp_path):
    """Path.resolve()/is_absolute() raise ValueError on an embedded NUL, and identity
    comparison resolves worktree_path, so a NUL would escape as a raise from the scan."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    bad = _lease(cli, lease_id="beef03")
    bad["worktree_path"] = "/tmp/lane\x00evil"
    assert cli.fleet_lease_well_formed(bad) is False
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    leases_dir.mkdir(parents=True, exist_ok=True)
    (leases_dir / "nul.json").write_text(json.dumps(bad), encoding="utf-8")
    assert cli.load_fleet_leases(repo) == []


def test_load_retries_when_a_lease_vanishes_mid_read(cli, tmp_path, monkeypatch):
    """The directory listing is a snapshot. A concurrent takeover publishes then
    unlinks, so a reader that globbed before the publish and read after the unlink
    would see NEITHER lease and allow an edit a live foreign lease covers."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli, lease_id="0bbbb1"))
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    ghost = leases_dir / "0cccc2.json"
    ghost.write_text(json.dumps(_lease(cli, lease_id="0cccc2")), encoding="utf-8")

    real_read = type(ghost).read_text
    state = {"vanished": False}

    def racing_read(self, *args, **kwargs):
        # Simulate the unlink landing between glob and read, exactly once.
        if self.name == "0cccc2.json" and not state["vanished"]:
            state["vanished"] = True
            self.unlink(missing_ok=True)
            raise FileNotFoundError(str(self))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(ghost), "read_text", racing_read)
    loaded = cli.load_fleet_leases(repo)
    assert state["vanished"] is True, "the race was not exercised"
    # The retry re-globs, so the surviving lease is still reported.
    assert [entry["lease_id"] for entry in loaded] == ["0bbbb1"]


def test_one_unresolvable_lease_cannot_abort_the_whole_scan(cli, tmp_path):
    """Codex Stage 2 raised this as a symlink-loop case; on this platform
    Path.resolve() is non-strict and does NOT raise for loops, long components or
    deep nesting (all three checked), so that exact mechanism is a false positive
    here. The INVARIANT it describes is real and is what this pins: any
    worktree_path whose resolve() raises must be rejected as malformed at load
    time, because every conflict scan resolves it and an escape there reaches the
    hook's top-level fail-open and abandons the scan -- so ONE bad lease would stop
    every VALID lease being enforced. NUL is the input that genuinely raises here;
    fleet_lease_well_formed also resolves eagerly so a platform where loops DO
    raise is covered by the same gate."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    cli.write_fleet_lease(repo, _lease(cli, lease_id="0d00d1", globs=("src/**",)))

    bad = _lease(cli, lease_id="0bad001", globs=("docs/**",))
    bad["worktree_path"] = "/lane\x00evil"
    assert cli.fleet_lease_well_formed(bad) is False
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    (leases_dir / "0bad001.json").write_text(json.dumps(bad), encoding="utf-8")

    # The bad record is dropped and the good lease still ARBITRATES -- the scan
    # completed rather than fail-opening on the way past the bad file.
    loaded = cli.load_fleet_leases(repo)
    assert [entry["lease_id"] for entry in loaded] == ["0d00d1"]
    now = datetime.now(timezone.utc)
    hit = cli.fleet_conflicting_lease(repo, "src/a.py", tmp_path / "other-lane", now)
    assert hit is not None and hit["lease_id"] == "0d00d1"


def test_mixed_type_globs_list_is_malformed(cli, tmp_path):
    """Accepting ["src/**", 7] because ONE entry is usable lets the record load,
    and the claim/takeover conflict reporting then does `','.join(globs)` and
    raises TypeError -- a CRASH on corrupt local lease state, which the fail-open
    contract forbids. Lease files are local state any process can edit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    leases_dir = cli.fleet_state_dir(repo) / "leases"
    leases_dir.mkdir(parents=True, exist_ok=True)
    for name, globs in (
        ("0mix001", ["src/**", 7]),
        ("0mix002", ["src/**", None]),
        ("0mix003", ["src/**", ""]),
        ("0mix004", []),
    ):
        bad = _lease(cli, lease_id=name)
        bad["globs"] = globs
        (leases_dir / f"{name}.json").write_text(json.dumps(bad), encoding="utf-8")
        assert cli.fleet_lease_well_formed(bad) is False, globs
    assert cli.load_fleet_leases(repo) == []
    # An all-usable list still loads.
    cli.write_fleet_lease(repo, _lease(cli, lease_id="0dd0001", globs=("src/**", "docs/a.md")))
    assert [e["lease_id"] for e in cli.load_fleet_leases(repo)] == ["0dd0001"]
