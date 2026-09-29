"""A review of nothing is refused before it can be recorded, ledgered, or charged.

RCA `2026-07-28-empty-diff-review-recorded-clean`: a Stage 2 manifest whose subject was zero bytes
-- `head_sha == base_sha`, `diff_bytes: 0`, `diff_sha256` the empty-string digest -- was finalized
clean, written to the ledger, and counted against the round budget. Every downstream gate then
read a green review that had reviewed nothing. The manifest matched the current state for the same
reason it was void: both sides were empty, so the equality check that is supposed to bind evidence
to a subject passed on the absence of one.

The refusal is spelled once, in `implementation_review_subject_errors`, and wired at the doors that
can record or spend. Each void marker refuses INDEPENDENTLY: a forged manifest that simply omits
`diff_bytes` must not slip past, and `head_sha == base_sha` catches the case before any diff is
hashed.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _classified_findings_fixtures import lane

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


def void_lane(cli, tmp_path, **overrides):
    """A lane whose manifest AND state carry the void triple -- the incident replay.

    Both sides are voided together on purpose. That is what made the original incident invisible:
    a void manifest matched a void state, so `diff_sha256 does not match` never fired.
    """
    subject = lane(cli, tmp_path)
    void = {
        "head_sha": "same" * 10,
        "base_sha": "same" * 10,
        "diff_sha256": EMPTY_DIGEST,
        "diff_bytes": 0,
    }
    void.update(overrides)
    subject.state.update(void)
    manifest = subject.manifest()
    manifest.update(void)
    subject.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return subject


# --- 1. the predicate: each void marker refuses on its own ---------------------------------------


# --- 2. door 1: manifest validation ---------------------------------------------------------------


# --- 3. door 2: finalization refuses and mutates NOTHING ------------------------------------------


# --- 4. door 3: codex-run refuses BEFORE the wrapper runs -----------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def void_review_repo(tmp_path):
    """A real repo whose review subject is empty: HEAD is the base.

    The wrapper touches a marker, so "the wrapper never ran" is an assertion about the filesystem
    rather than about stdout -- a refusal that still executed the wrapper has already spent the
    round it claims to have saved.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    rendered = subprocess.run(
        [sys.executable, str(CLI_PATH), "render-adapters",
         "--project", str(EXAMPLE_ADAPTER), "--target", str(repo), "--write"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "lane@example.test")
    _git(repo, "config", "user.name", "Lane")
    _git(repo, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")

    marker = repo / "wrapper-ran.marker"
    wrapper = repo / "scripts" / "codex-review.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    wrapper.chmod(0o755)
    (repo / ".gitignore").write_text(".ai-work/\n.ai-runs/\n.impl-reviews/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    # HEAD is now `main`, and `main` is the review base -- so the resolved scope is zero bytes.
    return repo, marker, env


def test_a_void_run_records_no_manifest_and_therefore_spends_no_round(void_review_repo) -> None:
    """Refusals are round-free because the counter derives from RECORDED manifests. This asserts
    the mechanism, not the intent: nothing landed in the evidence directory."""
    repo, _marker, env = void_review_repo

    subprocess.run(
        [sys.executable, str(CLI_PATH), "codex-run", "--target", str(repo),
         "--risk-tier", "T1", "--review-round", "R1", "--", "./scripts/codex-review.sh"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120,
    )

    evidence = repo / ".ai-runs" / "review-evidence"
    manifests = sorted(evidence.glob("*.json")) if evidence.is_dir() else []
    assert manifests == [], f"a refused run left evidence behind: {manifests}"


# --- 5. door 4: the WRITER, the only site that actually records ----------------------------------


# --- 6. no refusal on this surface hands the decision to a human ----------------------------------
