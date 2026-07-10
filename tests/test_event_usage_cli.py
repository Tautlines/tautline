import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _run_cli(
    tmp_path: Path,
    *args: str,
    stdin: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        input=stdin,
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _write_event_adapter(target: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": "$HOME/.local/state/minervit/repo-events",
        "requiredBoundaryEvents": [
            "startup",
            "planning_review_gate",
            "preflight",
            "pr_queue_merge",
            "blocker",
            "rca",
            "continuity",
            "context_rotation",
            "goal_transition",
            "milestone_transition",
        ],
    }
    data["usageAccounting"] = {
        **data.get("usageAccounting", {}),
        "stateDir": "$HOME/.local/state/minervit/usage",
    }
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for event and usage isolation behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "event-usage-target"
    target.mkdir()
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
    adapter = _write_event_adapter(target)
    _run_cli(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    return target, adapter


def _path_from_output(stdout: str, label: str) -> Path:
    prefix = f"{label}: "
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"{label} missing from output:\n{stdout}")


def test_event_log_paths_audit_rotation_and_validation(tmp_path):
    target, adapter = _prepare_target(tmp_path)

    started = _run_cli(tmp_path, "lane-start", "--project", str(adapter), "--target", str(target), "--skip-update")
    assert "event_log_human:" in started.stdout
    assert "event_log_jsonl:" in started.stdout
    status = _run_cli(tmp_path, "methodology-status", "--target", str(target), "--no-remote")
    assert "event_log_human:" in status.stdout
    assert "event_log_jsonl:" in status.stdout

    paths = _run_cli(tmp_path, "event-log-path", "--target", str(target))
    event_log = _path_from_output(paths.stdout, "event_log")
    event_jsonl = _path_from_output(paths.stdout, "event_jsonl")
    assert "/.local/state/minervit/repo-events/" in str(event_log)
    assert event_jsonl.name == "events.jsonl"

    _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "preflight_started",
        "--severity",
        "info",
        "--plain",
        "Full preflight started",
        "--next",
        "Wait for the preflight terminal event",
        "--ref",
        "log=.ai-runs/preflight.log",
    )
    missing = _run_cli(tmp_path, "event-audit", "--target", str(target), "--since", "24h", "--strict", check=False)
    assert missing.returncode == 1
    assert "preflight_started: started event lacks a later terminal event" in missing.stdout

    _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "preflight_passed",
        "--severity",
        "ok",
        "--plain",
        "Full preflight is green",
        "--next",
        "Push the branch",
        "--ref",
        "log=.ai-runs/preflight.log",
    )
    assert event_log.is_file()
    assert event_jsonl.is_file()
    assert "OK    preflight_passed" in event_log.read_text(encoding="utf-8")
    tail = _run_cli(tmp_path, "event-tail", "--target", str(target), "--lines", "2")
    assert "Full preflight is green" in tail.stdout
    clean = _run_cli(tmp_path, "event-audit", "--target", str(target), "--since", "24h", "--strict")
    assert "event_audit: clean" in clean.stdout
    assert "event_audit_required_boundary_events:" in clean.stdout

    records = [json.loads(line) for line in event_jsonl.read_text(encoding="utf-8").splitlines()]
    last = records[-1]
    assert last["schema"] == "minervit-repo-event/v1"
    assert last["event"] == "preflight_passed"
    assert last["refs"]["log"] == ".ai-runs/preflight.log"
    assert last["methodology"]["plugin_version"]

    secret = _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "secret_test",
        "--severity",
        "fail",
        "--plain",
        "token ghp_1234567890abcdef1234567890abcdef123456",
        "--next",
        "Reject this event",
        check=False,
    )
    assert secret.returncode == 1
    assert "secret-looking value" in secret.stderr

    long_plain = "x" * 1001
    long_event = _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "long_test",
        "--severity",
        "info",
        "--plain",
        long_plain,
        "--next",
        "Reject this event",
        check=False,
    )
    assert long_event.returncode == 1
    assert "plain exceeds 1000 characters" in long_event.stderr

    _run_cli(tmp_path, "event-rotate", "--target", str(target), "--force")
    assert event_log.with_name("events.log.1").is_file()
    assert event_jsonl.with_name("events.jsonl.1").is_file()

    _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "plan_review_started",
        "--severity",
        "info",
        "--plain",
        "Plan review started",
        "--next",
        "Wait for the plan-review terminal event",
    )
    _run_cli(tmp_path, "event-rotate", "--target", str(target), "--force")
    rotated_missing = _run_cli(tmp_path, "event-audit", "--target", str(target), "--since", "24h", "--strict", check=False)
    assert rotated_missing.returncode == 1
    assert "plan_review_started: started event lacks a later terminal event" in rotated_missing.stdout
    _run_cli(
        tmp_path,
        "log-event",
        "--target",
        str(target),
        "--event",
        "plan_review_finished",
        "--severity",
        "ok",
        "--plain",
        "Plan review finished",
        "--next",
        "Continue after reviewed plan evidence",
    )
    rotated_clean = _run_cli(tmp_path, "event-audit", "--target", str(target), "--since", "24h", "--strict")
    assert "event_audit: clean" in rotated_clean.stdout


def test_usage_accounting_records_imports_dedupes_reports_and_rotates(tmp_path):
    target, _adapter = _prepare_target(tmp_path)
    started = _run_cli(tmp_path, "lane-start", "--target", str(target), "--skip-update")
    assert "usage_jsonl:" in started.stdout
    status = _run_cli(tmp_path, "methodology-status", "--target", str(target), "--no-remote")
    assert "usage_rollup:" in status.stdout

    paths = _run_cli(tmp_path, "usage-log-path", "--target", str(target))
    usage_jsonl = _path_from_output(paths.stdout, "usage_jsonl")
    usage_rollup = _path_from_output(paths.stdout, "usage_rollup")
    assert "/.local/state/minervit/usage/" in str(usage_jsonl)

    recorded = _run_cli(
        tmp_path,
        "usage-record",
        "--target",
        str(target),
        "--provider",
        "claude",
        "--model",
        "claude-opus-test",
        "--activity",
        "plan-review",
        "--source",
        "manual",
        "--confidence",
        "exact",
        "--input-tokens",
        "10",
        "--output-tokens",
        "5",
        "--cache-creation-input-tokens",
        "20",
        "--cache-read-input-tokens",
        "30",
        "--goal",
        "G1",
        "--milestone",
        "M1",
        "--request-id",
        "usage-record-1",
    )
    assert "usage_recorded: 1" in recorded.stdout
    assert usage_jsonl.is_file()
    assert usage_rollup.is_file()
    product_report = _run_cli(tmp_path, "usage-report", "--target", str(target), "--since", "7d", "--by", "product")
    assert "usage_report_total_tokens: 65" in product_report.stdout
    assert "usage_report_item:" in product_report.stdout

    claude_usage = tmp_path / "claude-usage.jsonl"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    claude_usage.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "sessionId": "session-a",
                        "requestId": "request-a",
                        "message": {
                            "model": "claude-sonnet-test",
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "cache_creation_input_tokens": 25,
                                "cache_read_input_tokens": 75,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "sessionId": "session-a",
                        "requestId": "request-a",
                        "message": {
                            "model": "claude-sonnet-test",
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "cache_creation_input_tokens": 25,
                                "cache_read_input_tokens": 75,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "sessionId": "session-a",
                        "requestId": "request-b",
                        "message": {
                            "model": "claude-sonnet-test",
                            "usage": {
                                "input_tokens": 7,
                                "output_tokens": 8,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0,
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    imported = _run_cli(
        tmp_path,
        "usage-import-claude",
        "--target",
        str(target),
        "--path",
        str(claude_usage),
        "--since",
        "7d",
        "--activity",
        "code-review",
    )
    assert "usage_imported: 2" in imported.stdout
    assert "usage_skipped_duplicate: 1" in imported.stdout
    activity_report = _run_cli(tmp_path, "usage-report", "--target", str(target), "--since", "7d", "--by", "activity")
    assert "usage_report_total_tokens: 330" in activity_report.stdout
    assert "usage_report_item: code-review records=2 total_tokens=265" in activity_report.stdout
    assert "usage_report_item: plan-review records=1 total_tokens=65" in activity_report.stdout

    records = [json.loads(line) for line in usage_jsonl.read_text(encoding="utf-8").splitlines()]
    assert all(record["schema"] == "minervit-usage-record/v1" for record in records)
    assert {record["confidence"] for record in records} == {"exact"}
    assert sum(record["tokens"]["total"] for record in records) == 330
    rollup = json.loads(usage_rollup.read_text(encoding="utf-8"))
    assert rollup["schema"] == "minervit-usage-rollup/v1"
    assert rollup["totals"]["total_tokens"] == 330

    secret = _run_cli(
        tmp_path,
        "usage-record",
        "--target",
        str(target),
        "--provider",
        "claude",
        "--model",
        "claude-opus-test",
        "--activity",
        "secret-test",
        "--source",
        "manual",
        "--confidence",
        "exact",
        "--total-tokens",
        "1",
        "--ref",
        "token=ghp_1234567890abcdef1234567890abcdef123456",
        check=False,
    )
    assert secret.returncode == 1
    assert "secret-looking value" in secret.stderr

    _run_cli(tmp_path, "usage-rotate", "--target", str(target), "--force")
    assert usage_jsonl.with_name("usage.jsonl.1").is_file()
