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

        blocked = _run_cli(
            tmp_path,
            "publish-session-journal",
            "--file",
            str(journal_path),
            "--archive-dir",
            str(archive_dir),
        )
        assert blocked.returncode == 1
        assert (
            "local session journal archive writes to the methodology release checkout are disabled by default"
            in blocked.stderr
        )
        assert not (archive_dir / "_index.md").exists()

        published = _run_cli(
            tmp_path,
            "publish-session-journal",
            "--file",
            str(journal_path),
            "--archive-dir",
            str(archive_dir),
            "--allow-release-checkout-write",
            "--no-stage",
        )
        _assert_cli_ok(published)
        assert "session_journal_published:" in published.stdout
        assert "session_journal_staged: skipped --no-stage" in published.stdout
        assert "Session Journal Archive" in (archive_dir / "_index.md").read_text(encoding="utf-8")

        republished = _run_cli(
            tmp_path,
            "publish-session-journal",
            "--file",
            str(journal_path),
            "--archive-dir",
            str(archive_dir),
            "--allow-release-checkout-write",
            "--no-stage",
        )
        _assert_cli_ok(republished)
        archived = sorted(archive_dir.glob("*/*/*-session-journal.md"))
        assert len(archived) == 1
    finally:
        shutil.rmtree(archive_dir, ignore_errors=True)


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
