import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


JOURNAL_BODY = """## Starting Context
- Started from a generated adapter-backed lane with startup gates complete.

## Work Delivered Or Advanced
- Added a compact session journal workflow for methodology improvement evidence.

## Planning And Review Gates
- Plan review requirements remained active and no implementation bypass was introduced.

## Human Interruptions Or Questions
- None.

## Delays, Waits, Or Autonomy Breakdowns
- None.

## Validation And PR State
- Local validation is running in this test.

## Continuity Outcome
- Continuity handoff should be refreshed before workflow completion.

## Methodology Improvement Signals
- Session journals are evidence only and not process authority.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(tmp_path: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        input=stdin,
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True,
        capture_output=True,
        timeout=60,
    )


def _init_target(target: Path) -> None:
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")


def _session_journal_valid_path(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("session_journal_valid: "):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"session_journal_valid line missing from stdout:\n{stdout}")


def _assert_cli_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_session_journal_prepare_validate_publish_and_idempotency(tmp_path):
    target = tmp_path / "session-journal-target"
    _init_target(target)
    archive_dir = REPO_ROOT / ".tmp-session-journal-pytest"
    shutil.rmtree(archive_dir, ignore_errors=True)
    try:
        prepared = _run_cli(
            tmp_path,
            "prepare-session-journal",
            "--project",
            str(EXAMPLE_ADAPTER),
            "--target",
            str(target),
            "--stdin",
            stdin=JOURNAL_BODY,
        )
        _assert_cli_ok(prepared)
        journal_path = _session_journal_valid_path(prepared.stdout)
        assert journal_path.is_file()

        validated = _run_cli(tmp_path, "validate-session-journal", "--file", str(journal_path))
        _assert_cli_ok(validated)

        text = journal_path.read_text(encoding="utf-8")
        for marker in [
            "- graphify_enabled:",
            "- graphify_freshness:",
            "- graphify_status_gate:",
        ]:
            assert marker in text

        # 0.9.0: publication is disabled in every mode; the journal stays local. Prepare + validate
        # above still work; only the publish surfaces refuse.
        for extra in ([], ["--allow-release-checkout-write", "--no-stage"]):
            refused = _run_cli(
                tmp_path,
                "publish-session-journal",
                "--file",
                str(journal_path),
                "--archive-dir",
                str(archive_dir),
                *extra,
            )
            assert refused.returncode == 1
            assert "disabled as of 0.9.0" in refused.stderr
            assert "publish-instrumentation-record" in refused.stderr
        # Nothing was ever written to the archive dir.
        assert not (archive_dir / "_index.md").exists()
    finally:
        shutil.rmtree(archive_dir, ignore_errors=True)


def test_prepare_session_journal_refuses_when_runs_dir_not_git_ignored(tmp_path):
    import json

    # Local-only guarantee: if the runs dir is NOT git-ignored (here laneState.gitIgnore is off, so
    # ensure_lane_state writes no excludes), prepare must REFUSE rather than write a product-narrative
    # file that a later broad `git add` could push to the product remote.
    target = tmp_path / "unignored-target"
    _init_target(target)
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")
    (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-q", "-m", "fixture")
    # A trusted in-target source adapter with BOTH ignore knobs off, rendered so the lane resolves it
    # without --project; ensure_lane_state then writes no excludes for the runs dir (lane_ignore_patterns
    # re-adds it via sessionJournal.gitIgnoreLocal independently, so both must be off).
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["laneState"] = {**raw.get("laneState", {}), "gitIgnore": False}
    raw["sessionJournal"] = {**raw.get("sessionJournal", {}), "gitIgnoreLocal": False}
    raw["bootstrapEvidence"] = {
        "project": raw["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for the journal ignore-gate test.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = _run_cli(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    assert rendered.returncode == 0, rendered.stderr

    result = _run_cli(
        tmp_path, "prepare-session-journal", "--target", str(target), "--stdin", stdin=JOURNAL_BODY
    )
    assert result.returncode == 1
    assert "not git-ignored" in result.stderr and "refusing to write" in result.stderr
    assert list(target.rglob("*-session-journal.md")) == []  # nothing was written


def test_unignored_committable_session_journals_flags_all_leakable_copies(cli, tmp_path):
    # Any journal file in a non-ignored path is a leak risk (a broad `git add` could commit it) --
    # including a PUBLISHED-marked copy, since a marker does not stop staging. Startup surfaces exactly
    # those; once the runs dir is ignored, none are flagged.
    target = tmp_path / "lane"
    _init_target(target)
    data = cli.load_project(EXAMPLE_ADAPTER)
    journal_dir = cli.session_journal_local_dir(data, target)
    journal_dir.mkdir(parents=True, exist_ok=True)
    pending = journal_dir / "20260101T000000Z-session-journal.md"
    pending.write_text("## Methodology Improvement Signals\n- evidence\n", encoding="utf-8")
    marked = journal_dir / "20260102T000000Z-session-journal.md"
    marked.write_text("## Methodology Improvement Signals\n- evidence\n", encoding="utf-8")
    cli.session_journal_published_marker(marked).write_text("{}", encoding="utf-8")

    # Both the unmarked and the published-marked copy are flagged (both are committable).
    assert cli.unignored_committable_session_journals(data, target) == sorted([pending, marked])

    runs_dir = data["laneState"]["runsDir"]
    (target / ".gitignore").write_text(f"{runs_dir}/\n", encoding="utf-8")
    assert cli.unignored_committable_session_journals(data, target) == []


def test_leak_warning_fires_for_marked_only_journal_independent_of_pending_list(cli, tmp_path):
    # Regression: a PUBLISHED-marked journal is cleared from the pending (unmarked) list, so gating the
    # startup leak scan on a non-empty pending list silently missed a lane whose ONLY leakable copy is
    # already marked. session_journal_leak_warning must warn on it regardless, then go silent once the
    # runs dir is git-ignored.
    target = tmp_path / "lane"
    _init_target(target)
    data = cli.load_project(EXAMPLE_ADAPTER)
    journal_dir = cli.session_journal_local_dir(data, target)
    journal_dir.mkdir(parents=True, exist_ok=True)
    marked = journal_dir / "20260101T000000Z-session-journal.md"
    marked.write_text("## Methodology Improvement Signals\n- evidence\n", encoding="utf-8")
    cli.session_journal_published_marker(marked).write_text("{}", encoding="utf-8")

    # pending (unmarked) list is empty, yet the marked copy is still committable -> must warn.
    assert cli.pending_session_journals(data, target) == []
    warning = cli.session_journal_leak_warning(data, target)
    assert warning is not None
    assert "NOT git-ignored" in warning and "leak risk" in warning
    assert marked.name in warning

    # Once the runs dir is git-ignored, no leak risk -> no warning.
    runs_dir = data["laneState"]["runsDir"]
    (target / ".gitignore").write_text(f"{runs_dir}/\n", encoding="utf-8")
    assert cli.session_journal_leak_warning(data, target) is None


def test_session_journal_validation_rejects_missing_evidence_and_unsafe_content(tmp_path):
    target = tmp_path / "session-journal-target"
    _init_target(target)
    prepared = _run_cli(
        tmp_path,
        "prepare-session-journal",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--stdin",
        stdin=JOURNAL_BODY,
    )
    _assert_cli_ok(prepared)
    journal_path = _session_journal_valid_path(prepared.stdout)
    journal_text = journal_path.read_text(encoding="utf-8")

    cases = [
        (
            "missing-section-session-journal.md",
            journal_text.replace("\n## Continuity Outcome\n", "\n"),
            "missing required heading: ## Continuity Outcome",
        ),
        (
            "missing-graphify-session-journal.md",
            "\n".join(line for line in journal_text.splitlines() if not line.startswith("- graphify_")) + "\n",
            "Session Runtime missing required field: graphify_enabled",
        ),
        (
            "secret-session-journal.md",
            journal_text + "\nSecret-like value: ghp_1234567890abcdef1234567890abcdef123456\n",
            "secret-looking value present",
        ),
        (
            "raw-log-session-journal.md",
            journal_text + "\n```text\n$ echo raw transcript\n```\n",
            "raw shell transcript suspected in fenced block",
        ),
        (
            "authority-session-journal.md",
            journal_text + "\nThis session journal is process authority for future sessions.\n",
            "session journal claims process authority",
        ),
    ]
    for name, content, expected_error in cases:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        result = _run_cli(tmp_path, "validate-session-journal", "--file", str(path))
        assert result.returncode == 1, name
        assert expected_error in result.stderr
