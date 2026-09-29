"""T2 (0.9.0 sanitized instrumentation): telemetry salt + lane_id + per-lane monotonic seq.

`telemetry_salt()` is a 32-byte machine secret at `$HOME/.local/state/tautline/telemetry-salt`
(0600, create-on-first-use) that must never be published or logged.
`instrumentation_lane_id(target) = sha256(salt + resolved lane path).hexdigest()[:16]` is the
salted, stable-per-machine-and-lane discriminator that local event writes now carry (`lane_id`),
replacing the previous basename-only `lane` field that collides across parallel worktrees sharing
a directory name. Each local event write also gets a per-lane monotonically increasing `seq`,
allocated INSIDE the same advisory flock append_event_payload() already takes around the event
log's rotate+append, so two simultaneous try_write_event calls for the same lane can never
duplicate or skip a seq. The seq counter's persisted state also carries the high-water timestamp
of the last allocated event (the deterministic source a later gap-record aggregator will use when
no mapped event survives to derive emitted_at/filename from).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
LANE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _run_cli(
    tmp_path: Path,
    *args: str,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _write_event_adapter(target: Path, state_dir: str) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": state_dir,
    }
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T2 lane_id/seq isolation.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path, name: str = "event-lane-target", state_dir: str = "$HOME/.local/state/tautline-test/events") -> tuple[Path, Path]:
    target = tmp_path / name
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")
    (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "Initial fixture", "-q")
    adapter = _write_event_adapter(target, state_dir)
    _run_cli(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    return target, adapter


# ---------------------------------------------------------------------------
# telemetry_salt()
# ---------------------------------------------------------------------------


def test_telemetry_salt_stable_across_repeated_calls(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    first = cli.telemetry_salt()
    second = cli.telemetry_salt()
    assert first == second


def test_telemetry_salt_differs_across_machines_home_dirs(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home-a"))
    salt_a = cli.telemetry_salt()
    monkeypatch.setenv("HOME", str(tmp_path / "home-b"))
    salt_b = cli.telemetry_salt()
    assert salt_a != salt_b


# ---------------------------------------------------------------------------
# instrumentation_lane_id()
# ---------------------------------------------------------------------------


def test_instrumentation_lane_id_is_16_lowercase_hex(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_id = cli.instrumentation_lane_id(tmp_path / "lane")
    assert LANE_ID_PATTERN.fullmatch(lane_id), lane_id


def test_instrumentation_lane_id_is_stable_for_the_same_resolved_target(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = tmp_path / "lane"
    target.mkdir()
    first = cli.instrumentation_lane_id(target)
    second = cli.instrumentation_lane_id(target)
    assert first == second
    # A relative path that resolves to the same directory must hash identically.
    monkeypatch.chdir(target.parent)
    relative = cli.instrumentation_lane_id(Path(target.name))
    assert relative == first


def test_instrumentation_lane_id_distinct_across_different_lanes(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_a = tmp_path / "lane-a"
    lane_b = tmp_path / "lane-b"
    lane_a.mkdir()
    lane_b.mkdir()
    assert cli.instrumentation_lane_id(lane_a) != cli.instrumentation_lane_id(lane_b)


def test_instrumentation_lane_id_distinct_across_same_basename_worktrees(cli, tmp_path, monkeypatch):
    """The design's exact collision scenario: two parallel worktree clones with the SAME
    directory basename must still get distinct lane_id values, because the salted hash is over the
    resolved absolute path, not the basename (unlike the pre-existing `lane` event field)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    worktree_1 = tmp_path / "parent-1" / "myproject"
    worktree_2 = tmp_path / "parent-2" / "myproject"
    worktree_1.mkdir(parents=True)
    worktree_2.mkdir(parents=True)
    assert worktree_1.name == worktree_2.name == "myproject"

    lane_id_1 = cli.instrumentation_lane_id(worktree_1)
    lane_id_2 = cli.instrumentation_lane_id(worktree_2)

    assert lane_id_1 != lane_id_2
    assert LANE_ID_PATTERN.fullmatch(lane_id_1)
    assert LANE_ID_PATTERN.fullmatch(lane_id_2)


def test_instrumentation_lane_id_changes_with_different_machine_salt(cli, tmp_path, monkeypatch):
    target = tmp_path / "lane"
    target.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home-a"))
    lane_id_a = cli.instrumentation_lane_id(target)
    monkeypatch.setenv("HOME", str(tmp_path / "home-b"))
    lane_id_b = cli.instrumentation_lane_id(target)
    assert lane_id_a != lane_id_b


# ---------------------------------------------------------------------------
# seq counter + high-water timestamp
# ---------------------------------------------------------------------------


def test_allocate_instrumentation_seq_is_monotonic_for_one_lane(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_id = "0123456789abcdef"
    assert cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:00+00:00") == 1
    assert cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:01+00:00") == 2
    assert cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:02+00:00") == 3


def test_allocate_instrumentation_seq_is_independent_per_lane(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_a = "aaaaaaaaaaaaaaaa"
    lane_b = "bbbbbbbbbbbbbbbb"
    assert cli.allocate_instrumentation_seq(lane_a, "2026-07-10T12:00:00+00:00") == 1
    assert cli.allocate_instrumentation_seq(lane_b, "2026-07-10T12:00:00+00:00") == 1
    assert cli.allocate_instrumentation_seq(lane_a, "2026-07-10T12:00:01+00:00") == 2


def test_read_instrumentation_seq_state_defaults_when_absent(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    state = cli.read_instrumentation_seq_state("0000000000000000")
    assert state == {"seq": 0, "high_water_ts": None}


def test_high_water_timestamp_persists_the_last_allocated_ts(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_id = "fedcba9876543210"
    cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:00+00:00")
    cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:05+00:00")
    cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:09+00:00")

    state = cli.read_instrumentation_seq_state(lane_id)

    assert state["seq"] == 3
    assert state["high_water_ts"] == "2026-07-10T12:00:09+00:00"


def test_high_water_timestamp_is_deterministic_across_a_fresh_read(cli, tmp_path, monkeypatch):
    """Simulates a process restart: the high-water timestamp read back from disk must be exactly
    the persisted value, not recomputed from wall-clock `now` or anything else non-deterministic --
    it is later used verbatim as a gap record's emitted_at/filename stamp."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_id = "1111222233334444"
    cli.allocate_instrumentation_seq(lane_id, "2026-01-01T00:00:00+00:00")

    first_read = cli.read_instrumentation_seq_state(lane_id)
    second_read = cli.read_instrumentation_seq_state(lane_id)

    assert first_read == second_read == {"seq": 1, "high_water_ts": "2026-01-01T00:00:00+00:00"}


# ---------------------------------------------------------------------------
# local event writes: lane_id + seq fields, salt never leaked
# ---------------------------------------------------------------------------


def test_allocate_seq_recovers_above_event_log_after_state_loss(cli, tmp_path, monkeypatch):
    # If the persisted per-lane counter is deleted/rolled back while events remain in the log, a naive
    # allocator restarts at 1 and reissues seqs a published window's remote_max already covers, so
    # those events are silently filtered out forever. Recovery seeds above the log high-water instead.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lane_id = "9f2c4a1b0e7d5c3a"
    jsonl = tmp_path / "events.jsonl"
    jsonl.write_text(
        "".join(
            json.dumps({"lane_id": lane_id, "seq": n, "ts": "2026-07-10T12:00:00+00:00"}) + "\n"
            for n in range(1, 6)
        ),
        encoding="utf-8",
    )
    assert not cli.instrumentation_seq_state_path(lane_id).exists()  # state lost

    seq = cli.allocate_instrumentation_seq(lane_id, "2026-07-10T12:00:01+00:00", jsonl_path=jsonl, retained_rotations=0)
    assert seq == 6  # recovered above the log high-water (5), not reissued as 1


def test_allocate_seq_fresh_lane_with_empty_log_starts_at_one(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    jsonl.write_text("", encoding="utf-8")
    seq = cli.allocate_instrumentation_seq("00000000deadbeef", "2026-07-10T12:00:00+00:00", jsonl_path=jsonl, retained_rotations=0)
    assert seq == 1


# ---------------------------------------------------------------------------
# owner-only event-log permissions (lane_id correlation vector protection)
# ---------------------------------------------------------------------------


def test_secure_event_log_paths_forces_owner_only_dir_and_files(cli, tmp_path):
    # The event log carries the salted lane_id that ALSO appears in published telemetry; a
    # world-readable log on a multi-user host lets a co-located account correlate a remote record
    # back to local project data, defeating the salt. secure_event_log_paths must clamp the dir to
    # 0700 and every event file (incl. rotations) to 0600 regardless of the world-open modes here.
    directory = tmp_path / "events"
    directory.mkdir()
    directory.chmod(0o755)
    human = directory / "events.log"
    jsonl = directory / "events.jsonl"
    lock = directory / "events.lock"
    rotation = directory / "events.jsonl.1"
    for path in (human, jsonl, lock, rotation):
        path.write_text("x\n", encoding="utf-8")
        path.chmod(0o644)

    cli.secure_event_log_paths(human, jsonl, lock)

    assert directory.stat().st_mode & 0o777 == 0o700
    for path in (human, jsonl, lock, rotation):
        assert path.stat().st_mode & 0o777 == 0o600, path
