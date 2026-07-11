"""T5 end-to-end publisher tests against a LOCAL bare remote (no network).

`publish-instrumentation-record` recomputes the record from the local event log at publish time,
publishes ONLY the recomputed record to the CONSTANT `tautline-telemetry-archive` branch of the
framework checkout's origin via the full hardened push path (pinned-env commit, closed-set commit
parse, whole-branch hygiene, byte-compare readback, branch-tip ancestry guard, fetch/rebase/retry),
and advances no local state (idempotency is remote-derived). These tests exercise the real git
pipeline end to end.

The telemetry remote is the framework checkout's origin. For hermetic testing we point the
framework checkout at a local bare repo via TAUTLINE_TELEMETRY_REPO (the same kind of internal
resolution seam MINERVIT_METHODOLOGY_REPO already provides) -- this only changes WHERE sanitized
telemetry goes, never what it contains (the record has zero freeform capacity by construction)."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
ARCHIVE_BRANCH = "tautline-telemetry-archive"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _bare_origin(tmp_path: Path) -> Path:
    bare = tmp_path / "telemetry-origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    return bare


def _framework_checkout(tmp_path: Path, bare: Path) -> Path:
    fw = tmp_path / "framework"
    fw.mkdir()
    _git(fw, "init", "-q", "-b", "main")
    _git(fw, "config", "user.email", "fw@example.invalid")
    _git(fw, "config", "user.name", "Framework Checkout")
    _git(fw, "remote", "add", "origin", str(bare))
    return fw


def _env(tmp_path: Path, framework: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_REPO": "",
        "TAUTLINE_TELEMETRY_REPO": str(framework),
    }


def _run(env: dict, *args: str, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args], env=env, text=True, capture_output=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _write_adapter(target: Path, state_dir: str, *, instrumentation_enabled: bool) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {**data.get("observabilityEvents", {}), "stateDir": state_dir}
    data["instrumentation"] = {"enabled": instrumentation_enabled, "cadence": "session"}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T5 publisher e2e tests.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_lane(tmp_path: Path, env: dict, *, name: str = "lane", instrumentation_enabled: bool = True) -> Path:
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
    adapter = _write_adapter(target, f"$HOME/.local/state/tautline-test/{name}-events", instrumentation_enabled=instrumentation_enabled)
    _run(env, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    return target


def _log_event(env: dict, target: Path, event: str) -> None:
    _run(env, "log-event", "--target", str(target), "--event", event, "--severity", "info", "--plain", f"{event} happened", "--next", "n/a")


def _archive_blobs(bare: Path) -> list[str]:
    listing = _git(bare, "ls-tree", "-r", "--name-only", ARCHIVE_BRANCH)
    return [line for line in listing.splitlines() if line.strip()]


def _blob_text(bare: Path, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(bare), "cat-file", "blob", f"{ARCHIVE_BRANCH}:{path}"],
        check=True, capture_output=True, text=True,
    ).stdout


def test_first_publish_bootstraps_orphan_branch_with_pinned_path_bound_blob(cli, tmp_path):
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")
    _log_event(env, target, "task_started")

    result = _run(env, "publish-instrumentation-record", "--target", str(target))
    assert "instrumentation_published:" in result.stdout

    blobs = _archive_blobs(bare)
    assert len(blobs) == 1
    path = blobs[0]
    assert path.startswith("telemetry/") and path.endswith(".json")

    record = json.loads(_blob_text(bare, path))
    assert cli.instrumentation_record_errors(record) == []
    assert cli.instrumentation_archive_path_matches_record(path, record)
    assert {e["code"] for e in record["events"]} == {"startup", "task_started"}

    # Pinned commit metadata: no adopter identity/date/timezone/message reaches the remote.
    raw_commit = _git(bare, "cat-file", "commit", ARCHIVE_BRANCH)
    assert cli.instrumentation_commit_object_errors(raw_commit, emitted_at=record["emitted_at"]) == []

    # The whole log --stat carries no freeform string outside the closed set (constant paths/message).
    log_stat = _git(bare, "log", "--stat", ARCHIVE_BRANCH)
    assert "example-org" not in log_stat and "example-saas" not in log_stat
    assert "Test User" not in log_stat and "test@example.invalid" not in log_stat


def test_disabled_adapter_refuses_to_publish(tmp_path):
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env, instrumentation_enabled=False)
    _log_event(env, target, "startup")

    result = _run(env, "publish-instrumentation-record", "--target", str(target), check=False)
    assert result.returncode == 1
    assert "disabled" in (result.stdout + result.stderr).lower()
    # Nothing pushed.
    assert not _git(bare, "branch", "--list", ARCHIVE_BRANCH)


def test_idempotent_second_publish_with_nothing_new_is_a_noop(tmp_path):
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")

    _run(env, "publish-instrumentation-record", "--target", str(target))
    first_blobs = _archive_blobs(bare)
    assert len(first_blobs) == 1

    second = _run(env, "publish-instrumentation-record", "--target", str(target))
    assert "nothing to publish" in second.stdout.lower()
    assert _archive_blobs(bare) == first_blobs  # no new commit, no duplicate blob


def test_preview_tampered_into_conforming_but_different_record_does_not_influence_publish(cli, tmp_path):
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")

    # Prepare a preview, then TAMPER it into a schema-valid-but-different record (freeform is
    # impossible; instead alter counts). The publisher must never read the preview -- it recomputes.
    _run(env, "prepare-instrumentation-record", "--target", str(target))
    result = _run(env, "event-log-path", "--target", str(target))
    runs_dir = next(Path(line.split(": ", 1)[1]).parent for line in result.stdout.splitlines() if line.startswith("event_jsonl: "))
    preview = runs_dir.parent / "instrumentation" / "preview.json"
    # locate the preview robustly
    if not preview.exists():
        candidates = list((target).rglob("instrumentation/preview.json"))
        assert candidates, "preview not found"
        preview = candidates[0]
    tampered = json.loads(preview.read_text(encoding="utf-8"))
    for entry in tampered["events"]:
        entry["count"] = 999
    tampered["end_seq"] = 424242
    preview.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _run(env, "publish-instrumentation-record", "--target", str(target))
    published = json.loads(_blob_text(bare, _archive_blobs(bare)[0]))
    assert cli.instrumentation_record_errors(published) == []
    assert published["end_seq"] != 424242
    assert all(e["count"] != 999 for e in published["events"])


def test_second_window_after_new_events_advances_remote_max(tmp_path):
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")
    _run(env, "publish-instrumentation-record", "--target", str(target))

    _log_event(env, target, "gate_block")
    _run(env, "publish-instrumentation-record", "--target", str(target))

    blobs = _archive_blobs(bare)
    assert len(blobs) == 2
    codes_by_blob = [{e["code"] for e in json.loads(_blob_text(bare, b))["events"]} for b in blobs]
    # The two windows are disjoint: the second must NOT re-include the already-published startup.
    all_second = [c for c in codes_by_blob if "gate_block" in c][0]
    assert "startup" not in all_second


def _seed_archive_branch(bare: Path, tmp_path: Path, files: dict, *, name: str = "tautline-telemetry", email: str = "telemetry@tautline.invalid") -> str:
    """Push an orphan `tautline-telemetry-archive` branch to the bare origin carrying `files`
    (relpath -> text), committed under a chosen identity. Used to plant a poisoned pre-existing
    branch and prove the publisher refuses to trust it (whole-branch fail-closed hygiene)."""
    seed = tmp_path / f"seed-{abs(hash(tuple(sorted(files)))) % 100000}"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", ARCHIVE_BRANCH)
    _git(seed, "config", "user.name", name)
    _git(seed, "config", "user.email", email)
    for rel, text in files.items():
        blob = seed / rel
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_text(text, encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-q", "origin", ARCHIVE_BRANCH)
    return _git(bare, "rev-parse", ARCHIVE_BRANCH)


def test_publish_refuses_and_pushes_nothing_when_existing_branch_has_a_freeform_blob(tmp_path):
    # Gap #1: the whole-branch hygiene walk is the sole gate against an already-poisoned archive
    # branch. A conforming-looking blob carrying a freeform field must make publish fail closed --
    # refuse, push nothing, leave the poisoned tip untouched (operator recreates as sanitized orphan).
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")

    poisoned = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "9f2c4a1b0e7d5c3a",
        "plugin_version": "0.9.0",
        "window_seconds": 5400,
        "window_gap": False,
        "end_seq": 3,
        "events": [{"code": "startup", "count": 1}],
        "note": "customer ACME migration blocked on prod outage",  # freeform injection
    }
    seed_tip = _seed_archive_branch(
        bare, tmp_path, {"telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-3.json": json.dumps(poisoned, sort_keys=True) + "\n"}
    )

    result = _run(env, "publish-instrumentation-record", "--target", str(target), check=False)
    assert result.returncode == 1
    assert "hygiene" in (result.stdout + result.stderr).lower()
    assert "Traceback" not in result.stderr
    # Nothing pushed: the poisoned tip is untouched, still exactly one commit, one blob.
    assert _git(bare, "rev-parse", ARCHIVE_BRANCH) == seed_tip
    assert _git(bare, "rev-list", "--count", ARCHIVE_BRANCH) == "1"


def test_publish_fails_closed_without_crashing_on_newline_tainted_blob(tmp_path):
    # Gap #1 + P2 at e2e level: a poisoned blob whose emitted_at ends in a newline previously slipped
    # past record validation and crashed the path-binding datetime.fromisoformat with an uncaught
    # ValueError inside the whole-branch walk -- a telemetry DoS. Publish must refuse cleanly (rc 1,
    # no Python traceback) and push nothing.
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")

    tainted = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00\n",  # trailing newline
        "lane_id": "9f2c4a1b0e7d5c3a",
        "plugin_version": "0.9.0",
        "window_seconds": 5400,
        "window_gap": False,
        "end_seq": 3,
        "events": [{"code": "startup", "count": 1}],
    }
    seed_tip = _seed_archive_branch(
        bare, tmp_path, {"telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-3.json": json.dumps(tainted, sort_keys=True) + "\n"}
    )

    result = _run(env, "publish-instrumentation-record", "--target", str(target), check=False)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "hygiene" in (result.stdout + result.stderr).lower()
    assert _git(bare, "rev-parse", ARCHIVE_BRANCH) == seed_tip


def test_publish_survives_hostile_global_gitattributes_filter_and_prepush_hook(cli, tmp_path):
    # The publisher's isolation flags must neutralize user Git config on EVERY write, not only commit.
    # A global gitattributes clean filter on *.json runs at `git add` (staging) and would rewrite the
    # staged blob (caught only by the byte-compare readback -> every publish aborts); a global
    # core.hooksPath pre-push hook runs at `git push` and would reject every publish. Both are supported
    # user configs, so publication must still succeed and land the exact validated record.
    bare = _bare_origin(tmp_path)
    framework = _framework_checkout(tmp_path, bare)
    env = _env(tmp_path, framework)
    home = Path(env["HOME"])

    hooks_dir = tmp_path / "global-hooks"
    hooks_dir.mkdir()
    prepush = hooks_dir / "pre-push"
    prepush.write_text("#!/usr/bin/env bash\necho 'global pre-push rejects' >&2\nexit 1\n", encoding="utf-8")
    prepush.chmod(0o755)
    global_attrs = home / "global.gitattributes"
    global_attrs.write_text("*.json filter=mangle\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        '[filter "mangle"]\n'
        "\tclean = sed 's/.*/CORRUPTED/'\n"
        "[core]\n"
        f"\tattributesFile = {global_attrs}\n"
        f"\thooksPath = {hooks_dir}\n",
        encoding="utf-8",
    )

    target = _prepare_lane(tmp_path, env)
    _log_event(env, target, "startup")
    _log_event(env, target, "task_started")

    result = _run(env, "publish-instrumentation-record", "--target", str(target))
    assert "instrumentation_published:" in result.stdout, result.stdout + result.stderr

    blobs = _archive_blobs(bare)
    assert len(blobs) == 1
    blob = _blob_text(bare, blobs[0])
    assert "CORRUPTED" not in blob  # the clean filter did NOT touch the staged telemetry blob
    record = json.loads(blob)
    assert cli.instrumentation_record_errors(record) == []
    assert {e["code"] for e in record["events"]} == {"startup", "task_started"}
