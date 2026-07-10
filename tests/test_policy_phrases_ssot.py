"""dup-policy-1 (productization): the guard phrase/marker vocabulary now has a single machine-
readable projection (methodology/policy-phrases.json) generated from the CLI constants. ONE
generated-equals-source assertion replaces hand-maintained restatements: if a phrase constant
changes without regenerating the JSON, this fails (run `dump-policy-phrases --write`).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_JSON = REPO_ROOT / "methodology" / "policy-phrases.json"


def test_policy_phrases_json_exists_and_is_nonempty(cli):
    assert POLICY_JSON.exists(), "run: minervit-methodology dump-policy-phrases --write"
    data = json.loads(POLICY_JSON.read_text())
    assert len(data) >= 50
    assert sum(len(v) for v in data.values()) >= 500


def test_policy_phrases_json_matches_constants(cli):
    """generated-equals-source: the committed JSON must equal what the CLI constants project."""
    committed = POLICY_JSON.read_text(encoding="utf-8")
    rendered = cli.render_policy_phrases_json()
    assert committed == rendered, (
        "methodology/policy-phrases.json is stale vs the CLI phrase constants; "
        "run `minervit-methodology dump-policy-phrases --write`"
    )


def test_policy_phrases_reference_matches_source(cli):
    """dup-policy-2: the human-readable reference is GENERATED from the same source, not hand-kept."""
    ref = REPO_ROOT / "methodology" / "policy-phrases-reference.md"
    assert ref.exists(), "run: minervit-methodology dump-policy-phrases --write"
    assert ref.read_text(encoding="utf-8") == cli.render_policy_phrases_reference(), (
        "methodology/policy-phrases-reference.md is stale; run `dump-policy-phrases --write`"
    )


def test_dump_policy_phrases_check_passes(run_cli):
    res = run_cli("dump-policy-phrases", "--check")
    assert res.returncode == 0, res.stderr
    assert "up to date" in res.stdout


def test_policy_phrase_exports_include_rca_and_merge_queue_guard_keys(cli):
    data = json.loads(cli.render_policy_phrases_json())
    assert "RCA_STRONG_PROCESS_AUTHORITY_MARKERS" in data
    assert "canonical methodology" in data["RCA_STRONG_PROCESS_AUTHORITY_MARKERS"]
    assert "RESPONSE_GUARD_WRONG_MERGE_QUEUE_SIGNAL_MARKERS" in data
    assert "mergequeueentry" in data["RESPONSE_GUARD_WRONG_MERGE_QUEUE_SIGNAL_MARKERS"]
    assert "wrong merge-queue signal" in data["RESPONSE_GUARD_WRONG_MERGE_QUEUE_POLICY_MARKERS"]
