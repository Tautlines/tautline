"""T7 (0.9.0): narrative session-journal publication is DISABLED for every adapter in every mode.

A session journal narrates the adopter's product work, so it can never be proven safe to publish.
0.9.0 makes that structural: publish-session-journal (--commit --push, bare --file, and
--allow-release-checkout-write) and publish-pending-session-journals refuse outright, naming
publish-instrumentation-record as the sanitized replacement. Journals remain local evidence
(prepare/validate). See the plan's narrative-journals section.
"""

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


def test_publish_session_journal_writes_nothing_to_the_release_checkout(tmp_path):
    # Even the no-commit/preview path must not write into any git worktree.
    journal = tmp_path / "journal.md"
    journal.write_text(JOURNAL_BODY, encoding="utf-8")
    before = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout
    _run(tmp_path, "publish-session-journal", "--file", str(journal), "--allow-release-checkout-write", "--no-stage")
    after = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert before == after, "publish-session-journal must not touch the framework checkout"
