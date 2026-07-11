"""Session journals must be opt-in, not opt-out.

A session journal narrates what the agent did in the ADOPTER'S product repo (work
delivered, decisions, PR state) and `publish-session-journal --commit --push` pushes it
to a branch of the framework checkout's origin. Defaulting that to enabled silently
exports product-work narratives from every adopter that never heard of the feature.

0.8.7 flips the default to disabled. Adopters who want to contribute improvement
signals opt in by declaring `"sessionJournal": {"enabled": true}` in their SOURCE
adapter; lane-start/methodology-status print a one-line opt-in hint only while the
source adapter is silent about the feature (an explicit false must NOT nag).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _adapter_without_session_journal(tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw.pop("sessionJournal", None)
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_session_journal_defaults_to_disabled(cli, tmp_path):
    data = cli.load_project(_adapter_without_session_journal(tmp_path))
    assert data["sessionJournal"]["enabled"] is False


def test_session_journal_explicit_enable_is_respected(cli):
    data = cli.load_project(EXAMPLE_ADAPTER)
    assert data["sessionJournal"]["enabled"] is True


def test_optin_hint_shown_only_when_adapter_is_silent(cli, tmp_path):
    silent = _adapter_without_session_journal(tmp_path)
    data = cli.load_project(silent)
    hint = cli.session_journal_optin_hint(data, silent, tmp_path)
    assert "session_journal_optin:" in hint
    # 0.9.0: narrative journals can no longer be published; the hint steers adopters to the
    # sanitized instrumentation record as the safe way to contribute upstream.
    assert "docs/reference/instrumentation.md" in hint


def test_no_hint_when_explicitly_declared(cli, tmp_path):
    # Explicit true: enabled, no nag.
    data = cli.load_project(EXAMPLE_ADAPTER)
    assert cli.session_journal_optin_hint(data, EXAMPLE_ADAPTER, REPO_ROOT) == ""

    # Explicit false: the adopter decided; no nag either.
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["sessionJournal"] = {"enabled": False}
    declined = tmp_path / "declined.json"
    declined.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(declined)
    assert cli.session_journal_optin_hint(data, declined, tmp_path) == ""


def test_hint_consults_source_adapter_for_generated_markers(cli, tmp_path):
    """Generated .tautline.json markers embed the MERGED sessionJournal block, so the
    declared-check must consult _generated.sourceAdapter, not the marker itself."""
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw.pop("sessionJournal", None)
    source_dir = tmp_path / ".tautline"
    source_dir.mkdir()
    (source_dir / "adapter.json").write_text(json.dumps(raw), encoding="utf-8")

    marker = tmp_path / ".tautline.json"
    merged = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    merged["sessionJournal"] = dict(cli.DEFAULT_SESSION_JOURNAL)
    merged["_generated"] = {"sourceAdapter": ".tautline/adapter.json"}
    marker.write_text(json.dumps(merged), encoding="utf-8")

    data = cli.load_project(marker)
    hint = cli.session_journal_optin_hint(data, marker, tmp_path)
    assert "session_journal_optin:" in hint


def test_prepare_session_journal_pipeline_off_by_default(cli, tmp_path):
    """With the default flip, the merged config gates prepare (and therefore pending/
    publish) off: DEFAULT_SESSION_JOURNAL must carry enabled False."""
    assert cli.DEFAULT_SESSION_JOURNAL["enabled"] is False


def test_publish_pending_refuses_and_never_publishes(tmp_path):
    """0.9.0: narrative journals can no longer be published to any remote, for ANY adapter
    (enabled or not). publish-pending-session-journals refuses outright and never marks a pending
    journal as published; the journal stays local. (See test_session_journal_publish_disabled.py
    for the full refusal matrix.)"""
    target = tmp_path / "lane"
    target.mkdir()
    for args in (["init", "-q", "-b", "main"],
                 ["config", "user.email", "test@example.invalid"],
                 ["config", "user.name", "Test User"],
                 ["remote", "add", "origin", "git@github.com:example-org/example-saas.git"]):
        subprocess.run(["git", "-C", str(target), *args], check=True, capture_output=True)

    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["sessionJournal"] = {**raw.get("sessionJournal", {}), "enabled": True}
    source_dir = target / ".tautline"
    source_dir.mkdir()
    adapter = source_dir / "adapter.json"
    adapter.write_text(json.dumps(raw), encoding="utf-8")

    runs_dir = str((raw.get("laneState") or {}).get("runsDir") or ".ai-runs")
    journal_dir = target / runs_dir / "session-journals"
    journal_dir.mkdir(parents=True)
    pending = journal_dir / "20260101T000000Z-session-journal.md"
    pending.write_text("## Session Runtime\n- stub\n", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "publish-pending-session-journals",
         "--project", str(adapter), "--target", str(target)],
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 1, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "disabled as of 0.9.0" in result.stderr
    assert "publish-instrumentation-record" in result.stderr
    assert not pending.with_name(f"{pending.name}.published.json").exists()
