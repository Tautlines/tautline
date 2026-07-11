"""T7 (0.9.0): narrative session-journal publication is DISABLED for every adapter in every mode.

A session journal narrates the adopter's product work, so it can never be proven safe to publish.
0.9.0 makes that structural: publish-session-journal (--commit --push, bare --file, and
--allow-release-checkout-write) and publish-pending-session-journals refuse outright, naming
publish-instrumentation-record as the sanitized replacement. Journals remain local evidence
(prepare/validate). See the plan's narrative-journals section.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
JOURNAL_BODY = """## Session Runtime
- graphify_enabled: false

## What happened
- stub session journal body for the disabled-publish test
"""


def _run(tmp_path, *args, stdin=None, check=False):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        input=stdin, env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True, capture_output=True, timeout=60,
    )


def _lane(tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.invalid"],
              ["config", "user.name", "T"], ["remote", "add", "origin", "git@github.com:example-org/example-saas.git"]):
        subprocess.run(["git", "-C", str(target), *a], check=True, capture_output=True)
    return target


def test_publish_session_journal_refuses_in_every_mode(tmp_path):
    journal = tmp_path / "journal.md"
    journal.write_text(JOURNAL_BODY, encoding="utf-8")
    for extra in (["--commit", "--push"], [], ["--allow-release-checkout-write", "--no-stage"]):
        result = _run(tmp_path, "publish-session-journal", "--file", str(journal), *extra)
        assert result.returncode == 1, f"mode {extra} should refuse"
        assert "disabled as of 0.9.0" in result.stderr
        assert "publish-instrumentation-record" in result.stderr


def test_publish_session_journal_writes_nothing_to_the_release_checkout(tmp_path):
    # Even the no-commit/preview path must not write into any git worktree.
    journal = tmp_path / "journal.md"
    journal.write_text(JOURNAL_BODY, encoding="utf-8")
    before = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout
    _run(tmp_path, "publish-session-journal", "--file", str(journal), "--allow-release-checkout-write", "--no-stage")
    after = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert before == after, "publish-session-journal must not touch the framework checkout"


def test_publish_pending_refuses_for_every_adapter(tmp_path):
    target = _lane(tmp_path)
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["sessionJournal"] = {**raw.get("sessionJournal", {}), "enabled": True}  # even ENABLED refuses now
    source_dir = target / ".tautline"
    source_dir.mkdir()
    adapter = source_dir / "adapter.json"
    adapter.write_text(json.dumps(raw), encoding="utf-8")
    result = _run(tmp_path, "publish-pending-session-journals", "--project", str(adapter), "--target", str(target))
    assert result.returncode == 1
    assert "disabled as of 0.9.0" in result.stderr
    assert "publish-instrumentation-record" in result.stderr


def test_help_text_describes_refusal_and_names_replacement(tmp_path):
    for cmd in ("publish-session-journal", "publish-pending-session-journals"):
        result = _run(tmp_path, cmd, "--help")
        assert result.returncode == 0
        # argparse hard-wraps the description, so collapse whitespace before substring-matching.
        collapsed = "".join(result.stdout.split())
        assert "publish-instrumentation-record" in collapsed
        low = result.stdout.lower()
        assert "disabled" in low or "deprecated" in low
