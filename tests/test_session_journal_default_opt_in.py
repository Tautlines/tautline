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


def test_prepare_session_journal_pipeline_off_by_default(cli, tmp_path):
    """With the default flip, the merged config gates prepare (and therefore pending/
    publish) off: DEFAULT_SESSION_JOURNAL must carry enabled False."""
    assert cli.DEFAULT_SESSION_JOURNAL["enabled"] is False
