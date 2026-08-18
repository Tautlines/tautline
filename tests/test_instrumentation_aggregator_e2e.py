"""T3 (0.9.0 sanitized instrumentation): end-to-end aggregator tests against the REAL local event
log write path (the public `log-event` CLI command), not just synthetic dicts. These prove the
pure aggregation core in test_instrumentation_aggregator.py actually integrates with T2's real
lane_id/seq tagging and the real events.jsonl format, and are the literal fixtures the design calls
for: a runtime `log-event --event custom_name` never appears in telemetry, and two worktrees
sharing a directory basename (T2's exact collision scenario) still discriminate correctly.
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


def _write_event_adapter(target: Path, state_dir: str) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {**data.get("observabilityEvents", {}), "stateDir": state_dir}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T3 aggregator e2e.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path, name: str = "event-lane-target", state_dir: str = "$HOME/.local/state/tautline-test/t3-events") -> Path:
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
    return target


def _log_event(tmp_path: Path, target: Path, event: str, *, refs: list[str] | None = None) -> None:
    args = [
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
    ]
    for ref in refs or []:
        args.extend(["--ref", ref])
    _run_cli(tmp_path, *args)


def _jsonl_path(tmp_path: Path, target: Path) -> Path:
    paths = _run_cli(tmp_path, "event-log-path", "--target", str(target))
    return next(Path(line.split(": ", 1)[1]) for line in paths.stdout.splitlines() if line.startswith("event_jsonl: "))


def test_e2e_real_log_event_custom_name_never_appears_in_telemetry(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    _log_event(tmp_path, target, "custom_name")
    jsonl = _jsonl_path(tmp_path, target)

    record = cli.instrumentation_record_from_events(
        lane_id=cli.instrumentation_lane_id(target),
        remote_max=0,
        jsonl_path=jsonl,
        retained_rotations=5,
        plugin_version="0.9.0",
    )
    assert record is None


def test_e2e_real_plan_review_started_finished_pair_reduces_via_log_event(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    _log_event(tmp_path, target, "plan_review_started")
    _log_event(tmp_path, target, "plan_review_finished")
    jsonl = _jsonl_path(tmp_path, target)
    lane_id = cli.instrumentation_lane_id(target)

    record = cli.instrumentation_record_from_events(
        lane_id=lane_id,
        remote_max=0,
        jsonl_path=jsonl,
        retained_rotations=5,
        plugin_version="0.9.0",
    )
    assert record is not None
    assert cli.instrumentation_record_errors(record) == []
    events = {e["code"]: e for e in record["events"]}
    assert events["plan_review_round"]["count"] == 1
    assert "total_seconds" in events["plan_review_round"]


def test_e2e_real_finalize_verdict_via_log_event_ref(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    _log_event(tmp_path, target, "plan_review_finalized", refs=["verdict=clean"])
    jsonl = _jsonl_path(tmp_path, target)
    lane_id = cli.instrumentation_lane_id(target)

    record = cli.instrumentation_record_from_events(
        lane_id=lane_id,
        remote_max=0,
        jsonl_path=jsonl,
        retained_rotations=5,
        plugin_version="0.9.0",
    )
    assert record is not None
    assert cli.instrumentation_record_errors(record) == []
    codes = {e["code"] for e in record["events"]}
    assert codes == {"plan_review_clean"}


def test_e2e_a_capped_plan_review_verdict_reduces_to_blocked_not_dropped(
    cli, tmp_path, monkeypatch
):
    """The release valve's telemetry wiring, exercised through the REDUCER rather than asserted on
    the constant.

    `test_a_capped_verdict_reaches_instrumentation_instead_of_being_dropped` asserts only that
    `capped-with-open-findings` is a member of `INSTRUMENTATION_FINALIZE_BLOCKED_VERDICTS`. That
    membership survives reverting the call site from `verdict in
    INSTRUMENTATION_FINALIZE_BLOCKED_VERDICTS` back to `verdict == "blocked"`, which is the edit
    that would actually make every capped outcome vanish from telemetry -- the reducer drops
    verdicts it does not recognise. This feeds a real capped finalize event through the real
    aggregator, so the wiring itself is what is measured.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = _prepare_target(tmp_path)
    _log_event(
        tmp_path,
        target,
        "plan_review_finalized",
        refs=[f"verdict={cli.PLAN_REVIEW_CAPPED_VERDICT}"],
    )
    jsonl = _jsonl_path(tmp_path, target)

    record = cli.instrumentation_record_from_events(
        lane_id=cli.instrumentation_lane_id(target),
        remote_max=0,
        jsonl_path=jsonl,
        retained_rotations=5,
        plugin_version="0.9.0",
    )
    assert record is not None
    assert cli.instrumentation_record_errors(record) == []
    codes = {e["code"] for e in record["events"]}
    # BLOCKED, and specifically not clean: the finalize exits 0, but counting a capped outcome as
    # clean would make the aggregate say plan review converged when it ran out of budget.
    assert codes == {"plan_review_blocked"}


def test_e2e_two_worktrees_same_basename_lane_discrimination(cli, tmp_path, monkeypatch):
    """T2's exact collision scenario: two worktrees sharing a directory basename write into the SAME
    physical jsonl file (same repo_slug), but the aggregator must only ever count the requested
    lane's own events."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    parent_a = tmp_path / "parent-a"
    parent_b = tmp_path / "parent-b"
    parent_a.mkdir()
    parent_b.mkdir()
    target_a = _prepare_target(tmp_path, name="parent-a/myproject", state_dir="$HOME/.local/state/tautline-test/t3-worktree-events")
    target_b = _prepare_target(tmp_path, name="parent-b/myproject", state_dir="$HOME/.local/state/tautline-test/t3-worktree-events")
    assert target_a.name == target_b.name == "myproject"

    _log_event(tmp_path, target_a, "startup")
    _log_event(tmp_path, target_b, "startup")
    _log_event(tmp_path, target_b, "task_started")

    jsonl_a = _jsonl_path(tmp_path, target_a)
    jsonl_b = _jsonl_path(tmp_path, target_b)
    assert jsonl_a == jsonl_b  # same physical file -- the pre-existing collision

    lane_id_a = cli.instrumentation_lane_id(target_a)
    lane_id_b = cli.instrumentation_lane_id(target_b)
    assert lane_id_a != lane_id_b

    record_a = cli.instrumentation_record_from_events(
        lane_id=lane_id_a, remote_max=0, jsonl_path=jsonl_a, retained_rotations=5, plugin_version="0.9.0"
    )
    record_b = cli.instrumentation_record_from_events(
        lane_id=lane_id_b, remote_max=0, jsonl_path=jsonl_b, retained_rotations=5, plugin_version="0.9.0"
    )

    assert record_a is not None and record_b is not None
    events_a = {e["code"]: e for e in record_a["events"]}
    events_b = {e["code"]: e for e in record_b["events"]}
    assert events_a["startup"]["count"] == 1
    assert "task_started" not in events_a
    assert events_b["startup"]["count"] == 1
    assert events_b["task_started"]["count"] == 1
