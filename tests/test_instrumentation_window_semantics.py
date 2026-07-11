"""T4 (0.9.0 sanitized instrumentation): remote-authoritative window-semantics tests at the
aggregation level.

There is NO local window marker, attempt file, or locally-persisted classified progress by design
-- the fetched, hygiene-verified archive branch's highest bound `end_seq` (`remote_max`) is the
only durable authority (see the plan's "Window semantics" section). Because publish-
instrumentation-record (the real fetch/commit/push pipeline) is T5's job, these tests model the
publish pipeline WITHOUT the real publisher: they simulate publish outcomes by re-invoking
`instrumentation_record_from_events` (T3) with the same or an advanced `remote_max`, and assert the
properties the design requires:

- publish-failure changes nothing durable, so a retry recomputes -- possibly a LARGER window
  (more events accumulated meanwhile), safely (still schema-valid, still exactly the surviving
  events);
- publish-success makes the published record's `end_seq` the new `remote_max`, so the next
  recomputation only covers events strictly after it (no duplication of already-published events);
- a crash after a successful push is absorbed by the next scan in both orderings: (A) nothing new
  happened before the next scan runs (a clean no-op, proving the recompute-after-crash path never
  re-publishes/duplicates), and (B) new events accumulated before the next scan runs (the next scan
  covers only the new window, not the already-published one).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _run_cli(tmp_path: Path, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
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


def _write_adapter(target: Path, state_dir: str) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {**data.get("observabilityEvents", {}), "stateDir": state_dir}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T4 window-semantics tests.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path, name: str = "window-semantics-target") -> Path:
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
    adapter = _write_adapter(target, "$HOME/.local/state/tautline-test/t4-window-events")
    _run_cli(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    return target


def _log_event(tmp_path: Path, target: Path, event: str) -> None:
    _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        event,
        "--severity",
        "info",
        "--plain",
        f"{event} happened",
        "--next",
        "n/a",
    )


def _jsonl_path(tmp_path: Path, target: Path) -> Path:
    result = _run_cli(tmp_path, "event-log-path", "--target", str(target))
    return next(Path(line.split(": ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("event_jsonl: "))


def _aggregate(cli, lane_id: str, remote_max: int, jsonl_path: Path) -> dict | None:
    return cli.instrumentation_record_from_events(
        lane_id=lane_id,
        remote_max=remote_max,
        jsonl_path=jsonl_path,
        retained_rotations=5,
        plugin_version="0.9.0",
    )


def test_publish_failure_changes_nothing_durable_and_retry_recomputes_a_safe_larger_window(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    lane_id = cli.instrumentation_lane_id(target)
    _log_event(tmp_path, target, "startup")
    jsonl = _jsonl_path(tmp_path, target)

    # Attempt 1: aggregate against remote_max=0 (nothing published yet). Simulate the push failing:
    # remote_max is NOT advanced (there is no local state to advance either -- see module docstring).
    attempt_1 = _aggregate(cli, lane_id, 0, jsonl)
    assert attempt_1 is not None
    assert cli.instrumentation_record_errors(attempt_1) == []
    assert {e["code"] for e in attempt_1["events"]} == {"startup"}

    # More local activity happens while the failed publish is retried.
    _log_event(tmp_path, target, "task_started")

    # Retry: same remote_max=0 (the failed push never moved it). The recomputed record is a safely
    # LARGER window -- still schema-valid, and it now also covers the event that arrived meanwhile.
    retry = _aggregate(cli, lane_id, 0, jsonl)
    assert retry is not None
    assert cli.instrumentation_record_errors(retry) == []
    retry_codes = {e["code"] for e in retry["events"]}
    assert retry_codes == {"startup", "task_started"}
    assert retry["end_seq"] > attempt_1["end_seq"]


def test_publish_success_makes_the_record_end_seq_the_new_remote_max(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    lane_id = cli.instrumentation_lane_id(target)
    _log_event(tmp_path, target, "startup")
    jsonl = _jsonl_path(tmp_path, target)

    published = _aggregate(cli, lane_id, 0, jsonl)
    assert published is not None
    assert cli.instrumentation_record_errors(published) == []

    # Simulate the archive-branch fetch after a successful publish: remote_max becomes end_seq.
    remote_max_after_success = published["end_seq"]

    _log_event(tmp_path, target, "task_started")
    _log_event(tmp_path, target, "task_completed")

    next_window = _aggregate(cli, lane_id, remote_max_after_success, jsonl)
    assert next_window is not None
    assert cli.instrumentation_record_errors(next_window) == []
    # Only the NEW events survive -- nothing already published is duplicated.
    next_codes = {e["code"] for e in next_window["events"]}
    assert next_codes == {"task_started", "task_completed"}
    assert "startup" not in next_codes
    assert next_window["end_seq"] > remote_max_after_success


def test_crash_after_push_ordering_a_nothing_new_before_next_scan_is_a_clean_no_op(cli, tmp_path, monkeypatch):
    """Crash ordering A: the push succeeded but the process died before it could act on success.
    The next publish attempt's fetch sees the pushed record as remote_max; with no new local
    activity in between, recomputation must be an explicit no-op (nothing to re-publish/duplicate)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    lane_id = cli.instrumentation_lane_id(target)
    _log_event(tmp_path, target, "startup")
    jsonl = _jsonl_path(tmp_path, target)

    published = _aggregate(cli, lane_id, 0, jsonl)
    assert published is not None
    remote_max_after_success = published["end_seq"]

    # Crash happens here -- no new events, no local state changed. The next scan uses the real
    # (fetched) remote_max, which already reflects the successful push.
    absorbed = _aggregate(cli, lane_id, remote_max_after_success, jsonl)
    assert absorbed is None


def test_crash_after_push_ordering_b_new_events_before_next_scan_cover_only_the_new_window(cli, tmp_path, monkeypatch):
    """Crash ordering B: the push succeeded, the process died, and MORE local activity happened
    before the next publish attempt runs. That next scan must cover only the new window -- it must
    never re-include (duplicate) the events the crashed process already got published."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    lane_id = cli.instrumentation_lane_id(target)
    _log_event(tmp_path, target, "startup")
    jsonl = _jsonl_path(tmp_path, target)

    published = _aggregate(cli, lane_id, 0, jsonl)
    assert published is not None
    remote_max_after_success = published["end_seq"]

    # Crash happens here. Before the next publish attempt runs, new local activity accumulates.
    _log_event(tmp_path, target, "gate_block")

    absorbed = _aggregate(cli, lane_id, remote_max_after_success, jsonl)
    assert absorbed is not None
    assert cli.instrumentation_record_errors(absorbed) == []
    absorbed_codes = {e["code"] for e in absorbed["events"]}
    assert absorbed_codes == {"gate_block"}
    assert "startup" not in absorbed_codes


def test_same_window_recompute_is_byte_identical_regardless_of_when_it_runs(cli, tmp_path, monkeypatch):
    """Determinism underpins every property above: recomputing the SAME window (same remote_max,
    same on-disk snapshot) must yield a byte-identical record whenever it runs, so retries are safe
    and idempotent rather than merely "close enough"."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    lane_id = cli.instrumentation_lane_id(target)
    _log_event(tmp_path, target, "startup")
    jsonl = _jsonl_path(tmp_path, target)

    first = _aggregate(cli, lane_id, 0, jsonl)
    second = _aggregate(cli, lane_id, 0, jsonl)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
