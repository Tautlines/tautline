"""T4 (0.9.0 sanitized instrumentation): CLI commands for the prepare/validate surface.

`prepare-instrumentation-record --target .` writes the current-window preview under the lane's
`.ai-runs/instrumentation/` as a SINGLE overwritten file (there is no local window/attempt state by
design, so every prepare re-aggregates from remote_max=0 -- the real remote_max fetch off the
hygiene-verified archive branch is publish-instrumentation-record's job, T5; the preview is a
human-inspection artifact the publisher never reads). It validates the aggregated record with T1's
validator before writing and refuses to write anything invalid, and it refuses to write at all when
the preview path is not actually git-ignored in the product worktree (git check-ignore) -- the same
write-time gate the narrative-journals design section describes, applied to instrumentation state.

`validate-instrumentation-record --file <path>` is a standalone fail-closed validator: exit 1 with
reasons on stderr for any parse/schema error, exit 0 for a conforming record.
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


def _run_cli(tmp_path: Path, *args: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess[str]:
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


def _write_adapter(target: Path, *, lane_git_ignore: bool = True) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneState"] = {**data["laneState"], "gitIgnore": lane_git_ignore}
    # lane_ignore_patterns() also re-adds the runsDir pattern via sessionJournal.gitIgnoreLocal
    # independently of laneState.gitIgnore -- both must be off to actually reproduce "an adapter
    # disabled or lost the ignore" for .ai-runs/ (see the design's narrative-journals section).
    data["sessionJournal"] = {**data["sessionJournal"], "gitIgnoreLocal": lane_git_ignore}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T4 CLI tests.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path, name: str = "instrumentation-cli-target", *, lane_git_ignore: bool = True) -> Path:
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
    adapter = _write_adapter(target, lane_git_ignore=lane_git_ignore)
    _run_cli(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write", check=True)
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
    _run_cli(tmp_path, *args, check=True)


def _preview_path_from_stdout(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("instrumentation_prepare: wrote "):
            return Path(line.split(": wrote ", 1)[1])
    raise AssertionError(f"instrumentation_prepare: wrote line missing from stdout:\n{stdout}")


def test_prepare_nothing_to_prepare_is_a_clean_no_op(tmp_path):
    target = _prepare_target(tmp_path)
    result = _run_cli(tmp_path, "prepare-instrumentation-record", "--target", str(target))
    assert result.returncode == 0, result.stderr
    assert "instrumentation_prepare: nothing to prepare" in result.stdout
    assert not (target / ".ai-runs" / "instrumentation").exists()


def test_prepare_writes_single_overwritten_preview_no_accumulation(tmp_path):
    target = _prepare_target(tmp_path)
    _log_event(tmp_path, target, "startup")

    first = _run_cli(tmp_path, "prepare-instrumentation-record", "--target", str(target))
    assert first.returncode == 0, first.stderr
    preview_path = _preview_path_from_stdout(first.stdout)
    assert preview_path.is_file()
    assert preview_path.parent == target / ".ai-runs" / "instrumentation"

    record_v1 = json.loads(preview_path.read_text(encoding="utf-8"))
    events_v1 = {e["code"]: e for e in record_v1["events"]}
    assert events_v1["startup"]["count"] == 1

    instrumentation_dir = target / ".ai-runs" / "instrumentation"
    assert [p.name for p in instrumentation_dir.iterdir()] == [preview_path.name]

    # Log another event and prepare again: the design's remote-authoritative window semantics mean
    # there is no local marker to key a second preview file off of, so this MUST overwrite the same
    # path (never accumulate a second timestamped file).
    _log_event(tmp_path, target, "task_started")
    second = _run_cli(tmp_path, "prepare-instrumentation-record", "--target", str(target))
    assert second.returncode == 0, second.stderr
    preview_path_again = _preview_path_from_stdout(second.stdout)
    assert preview_path_again == preview_path

    assert [p.name for p in instrumentation_dir.iterdir()] == [preview_path.name]
    record_v2 = json.loads(preview_path.read_text(encoding="utf-8"))
    events_v2 = {e["code"]: e for e in record_v2["events"]}
    assert events_v2["startup"]["count"] == 1
    assert events_v2["task_started"]["count"] == 1


def test_prepare_refuses_when_preview_path_is_not_git_ignored(tmp_path):
    target = _prepare_target(tmp_path, lane_git_ignore=False)
    _log_event(tmp_path, target, "startup")

    result = _run_cli(tmp_path, "prepare-instrumentation-record", "--target", str(target))
    assert result.returncode == 1
    assert "not git-ignored" in result.stderr
    assert not (target / ".ai-runs" / "instrumentation").exists()


def test_prepare_broad_git_add_stages_no_telemetry_state_in_product_worktree(tmp_path):
    """Positive complement to the refuse-when-not-ignored gate: the design requires the
    product-worktree broad-`git add -A` test to cover instrumentation state alongside journals --
    after a SUCCESSFUL prepare (ignore intact), a broad `git add -A` in the product worktree must
    stage nothing under `.ai-runs/` (the preview is one `git add .` away from the product remote
    otherwise). Proves the write-time git check-ignore gate actually keeps the preview unstageable."""
    target = _prepare_target(tmp_path)
    _log_event(tmp_path, target, "startup")

    result = _run_cli(tmp_path, "prepare-instrumentation-record", "--target", str(target))
    assert result.returncode == 0, result.stderr
    preview_path = _preview_path_from_stdout(result.stdout)
    assert preview_path.is_file()

    _git(target, "add", "-A")
    staged = _git(target, "diff", "--cached", "--name-only").splitlines()
    telemetry_staged = [p for p in staged if p.startswith(".ai-runs/")]
    assert not telemetry_staged, f"broad `git add -A` staged telemetry state toward the product remote: {telemetry_staged}"


def test_prepare_refuses_invalid_record_and_writes_nothing(cli, tmp_path, monkeypatch):
    """The command must validate the aggregated record with T1's validator BEFORE writing and
    refuse anything invalid -- exercised by monkeypatching the aggregator to return a
    deliberately-broken record, since the real aggregator always builds schema-valid records."""
    target = _prepare_target(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def _broken_aggregator(**_kwargs):
        return {"schema": cli.INSTRUMENTATION_SCHEMA_VERSION, "not_a_real_field": "nope"}

    monkeypatch.setattr(cli, "instrumentation_record_from_events", _broken_aggregator)

    import argparse

    args = argparse.Namespace(project=None, target=target)
    stderr_lines: list[str] = []
    monkeypatch.setattr(
        sys,
        "stderr",
        type("W", (), {"write": lambda self, s: stderr_lines.append(s), "flush": lambda self: None})(),
    )
    rc = cli.prepare_instrumentation_record(args)
    assert rc == 1
    assert not (target / ".ai-runs" / "instrumentation").exists()
    joined = "".join(stderr_lines)
    assert "instrumentation_prepare_validation_error" in joined


def test_validate_instrumentation_record_accepts_a_conforming_record(tmp_path):
    record = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "0123456789abcdef",
        "plugin_version": "0.9.0",
        "window_seconds": 42,
        "window_gap": False,
        "end_seq": 3,
        "events": [{"code": "startup", "count": 1}],
    }
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    result = _run_cli(tmp_path, "validate-instrumentation-record", "--file", str(path))
    assert result.returncode == 0, result.stderr
    assert "instrumentation_record_valid" in result.stdout


def test_validate_instrumentation_record_rejects_unknown_top_level_key(tmp_path):
    record = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "0123456789abcdef",
        "plugin_version": "0.9.0",
        "window_seconds": 42,
        "window_gap": False,
        "end_seq": 3,
        "events": [{"code": "startup", "count": 1}],
        "notes": "freeform narrative should never be accepted",
    }
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    result = _run_cli(tmp_path, "validate-instrumentation-record", "--file", str(path))
    assert result.returncode == 1
    assert "instrumentation_record_validation_error" in result.stderr


def test_validate_instrumentation_record_rejects_malformed_json(tmp_path):
    path = tmp_path / "record.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(tmp_path, "validate-instrumentation-record", "--file", str(path))
    assert result.returncode == 1
    assert "instrumentation_record_invalid_json" in result.stderr


def test_validate_instrumentation_record_rejects_forged_empty_non_gap_record(tmp_path):
    """The design's forged-empty-record fixture: an empty `events` with `window_gap: false` and a
    high `end_seq` could otherwise suppress local events with no gap indication."""
    record = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "0123456789abcdef",
        "plugin_version": "0.9.0",
        "window_seconds": 0,
        "window_gap": False,
        "end_seq": 999999,
        "events": [],
    }
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    result = _run_cli(tmp_path, "validate-instrumentation-record", "--file", str(path))
    assert result.returncode == 1
    assert "instrumentation_record_validation_error" in result.stderr


def test_validate_instrumentation_record_missing_file(tmp_path):
    path = tmp_path / "does-not-exist.json"
    result = _run_cli(tmp_path, "validate-instrumentation-record", "--file", str(path))
    assert result.returncode == 1
    assert "instrumentation_record_unreadable" in result.stderr


def test_both_commands_are_classified_experimental_in_the_public_contract(cli):
    statuses = {c["name"]: c["status"] for c in cli.public_contract_manifest_data()["commands"]}
    assert statuses["prepare-instrumentation-record"] == "experimental"
    assert statuses["validate-instrumentation-record"] == "experimental"
