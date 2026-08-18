"""The wave-3 aggregate stop-blocking budget, enforced as a measurement.

RCA remediation program conflict C3: four plans (items 82, 83, 84 and item 79's WS3) each add
blocking conditions to ONE Stop boundary, each measured its own false-positive rate in isolation,
and nobody owned the AGGREGATE. The named risk is a lane that cannot end a turn at all.

Close-out decision D2, 2026-08-13: the budget is a measured aggregate ceiling enforced by this
harness, not a number written in a document. Item 82 stamps the baseline; items 83, 84 and 79 WS3
each re-measure on their own rebased tip and state the number in the PR body. A lane may not carry
a predecessor's number forward -- the same rule the canonical ratchet and the adapter corridor
already carry, for the same reason.
"""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _baseline():
    return json.loads(
        (REPO_ROOT / "methodology" / "stop-guard" / "aggregate-baseline.json").read_text(
            encoding="utf-8"
        )
    )


def test_the_corpus_still_matches_the_digest_the_baseline_was_stamped_against(cli):
    """The anti-gaming control, and the reason the digest is in the artifact at all.

    Without it a successor whose detector started firing on legitimate turns could bring the
    aggregate back under the ceiling by DELETING those corpus entries, and every gate would stay
    green. Changing the corpus is a deliberate, reviewed act that re-stamps the baseline and says
    so in the PR body.
    """
    assert cli.stop_guard_corpus_sha256(REPO_ROOT) == _baseline()["corpusSha256"]


def test_the_corpus_is_large_enough_for_the_ceiling_to_mean_anything(cli):
    """A corpus small enough to make two percentage points a rounding error is not a budget."""
    entries = cli.stop_guard_corpus_entries(REPO_ROOT)
    legitimate = [entry for entry in entries if entry["expect"] == "allow"]
    evasion = [entry for entry in entries if entry["expect"] == "block"]
    assert len(legitimate) >= cli.STOP_GUARD_CORPUS_MIN_LEGITIMATE
    assert len(evasion) >= cli.STOP_GUARD_CORPUS_MIN_EVASION
    assert len({entry["id"] for entry in entries}) == len(entries), "corpus ids must be unique"


def test_the_aggregate_stop_blocking_rate_is_within_the_ceiling(cli):
    measured = cli.stop_guard_aggregate_measure(REPO_ROOT)
    baseline = _baseline()
    delta = measured["aggregateStopBlockingRatePct"] - baseline["aggregateStopBlockingRatePct"]
    assert delta <= cli.STOP_GUARD_AGGREGATE_CEILING_POINTS, (
        f"the aggregate stop-blocking rate moved {delta:+.2f} points against a ceiling of "
        f"+{cli.STOP_GUARD_AGGREGATE_CEILING_POINTS} across the WHOLE wave-3 chain; the turns now "
        f"blocked are {measured['blockedLegitimateIds']}. Decompose or narrow the detector rather "
        "than spending the budget and stranding the successor."
    )


def test_the_evasion_shapes_the_corpus_exists_to_catch_are_still_caught(cli):
    """Non-vacuity floor.

    A corpus that stopped firing reports a PERFECT false-positive rate, which is the same reading a
    genuinely clean chain produces. This is the assertion that tells the two apart -- and it is the
    dominant defect class in this repo: a control that reads healthy because something upstream
    never let it run.
    """
    measured = cli.stop_guard_aggregate_measure(REPO_ROOT)
    assert measured["missedEvasionIds"] == [], "evasion turns are no longer detected: " + ", ".join(
        measured["missedEvasionIds"]
    )
    assert measured["detectedEvasionTurns"] >= _baseline()["detectedEvasionTurns"]


def test_the_harness_measures_the_chain_at_maximum_enforcement_not_at_its_shipped_posture(cli):
    """The chain ships warn-only, so a harness reading the shipped posture would report zero.

    That would be a budget that cannot be exceeded because nothing it governs is ever counted. The
    measurement deliberately overrides the warn-only clamp and answers "what WOULD the aggregate be
    if the chain were blocking today", which is the number the ceiling is actually about.
    """
    entry = {
        "id": "probe",
        "expect": "block",
        "lastUser": "",
        "text": "Next, I'll draft the migration report.",
    }
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        adapter = cli.load_project(REPO_ROOT / "adapters" / "projects" / "example-saas.json")
        (root / ".tautline.json").write_text(json.dumps(adapter), encoding="utf-8")
        (root / ".ai-work").mkdir()
        (root / ".ai-work" / "GOAL_RUN.json").write_text(
            json.dumps({"schema": cli.GOAL_RUN_SCHEMA, "goalId": "probe", "status": "in_progress"}),
            encoding="utf-8",
        )
        (root / ".ai-work" / "BLOCKER.json").write_text(
            json.dumps(
                cli.guards_module().blocker_declare_record(
                    kind="approval-needed",
                    reason="probe fixture",
                    artifact=None,
                    goal_id="probe",
                    checked=[],
                )
            ),
            encoding="utf-8",
        )
        errors = cli.stop_guard_entry_blocks(entry, root)
    assert any("announce-and-stop" in error for error in errors), (
        "the harness must see a wave-3 check fire even though the chain ships warn-only; if this "
        "goes quiet the whole budget is measuring nothing"
    )


def test_the_verb_reports_the_numbers_a_successor_pr_body_must_quote(run_cli):
    res = run_cli("stop-guard-aggregate", "--repo-root", str(REPO_ROOT))
    assert res.returncode == 0, res.stderr
    for key in (
        "stop_guard_corpus_sha256",
        "stop_guard_aggregate_rate_pct",
        "stop_guard_baseline_rate_pct",
        "stop_guard_delta_points",
        "stop_guard_sensitivity_pct",
    ):
        assert key in res.stdout


def test_the_verb_refuses_when_the_corpus_drifts_from_the_baseline(run_cli, tmp_path, cli):
    """The digest pin has teeth, proven by breaking it rather than by reading the code."""
    import shutil

    scratch = tmp_path / "repo"
    (scratch / "methodology" / "stop-guard").mkdir(parents=True)
    (scratch / "adapters" / "projects").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "adapters" / "projects" / "example-saas.json",
        scratch / "adapters" / "projects" / "example-saas.json",
    )
    corpus = (REPO_ROOT / "methodology" / "stop-guard" / "corpus.jsonl").read_text(encoding="utf-8")
    # Drop the last evasion turn: the exact move the pin exists to refuse.
    trimmed = "\n".join(corpus.splitlines()[:-1]) + "\n"
    (scratch / "methodology" / "stop-guard" / "corpus.jsonl").write_text(trimmed, encoding="utf-8")
    shutil.copy(
        REPO_ROOT / "methodology" / "stop-guard" / "aggregate-baseline.json",
        scratch / "methodology" / "stop-guard" / "aggregate-baseline.json",
    )
    res = run_cli("stop-guard-aggregate", "--repo-root", str(scratch))
    assert res.returncode == 1
    assert "no longer matches the digest" in res.stderr


def test_an_absent_baseline_is_a_failure_not_a_pass(run_cli, tmp_path):
    """Codex R2 P1. The gate reported success in the one state where it enforces nothing.

    A missing or empty baseline made every comparison fall through, so the command returned 0 with
    ok:true. The baseline IS the contract; only the command that creates one may proceed without it.
    """
    import shutil

    scratch = tmp_path / "repo"
    (scratch / "methodology" / "stop-guard").mkdir(parents=True)
    (scratch / "adapters" / "projects").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "adapters" / "projects" / "example-saas.json",
        scratch / "adapters" / "projects" / "example-saas.json",
    )
    shutil.copy(
        REPO_ROOT / "methodology" / "stop-guard" / "corpus.jsonl",
        scratch / "methodology" / "stop-guard" / "corpus.jsonl",
    )
    res = run_cli("stop-guard-aggregate", "--repo-root", str(scratch))
    assert res.returncode == 1, "an absent baseline must fail, not pass"
    assert "no committed aggregate baseline" in res.stderr

    res_json = run_cli("stop-guard-aggregate", "--repo-root", str(scratch), "--json")
    assert res_json.returncode == 1
    assert json.loads(res_json.stdout)["ok"] is False

    # ...but the command that CREATES the baseline must still be able to run.
    (scratch / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    res_write = run_cli(
        "stop-guard-aggregate", "--repo-root", str(scratch), "--write-baseline"
    )
    assert res_write.returncode == 0, res_write.stderr


def test_write_baseline_is_flag_gated_during_startup_remediation(cli):
    """Codex R2 P2. Allowlisting the verb also allowlisted its mutating mode.

    The gate keyed on a hardcoded `write` attribute, and this command spells its mutating flag
    `--write-baseline`, so the rewrite of a committed source artifact slipped through a remediation
    that exists to hold exactly those artifacts still.
    """
    assert "stop-guard-aggregate" in cli.STARTUP_REMEDIATION_WRITE_FLAG_GATED_COMMANDS
    assert cli.STARTUP_REMEDIATION_WRITE_FLAG_ATTRIBUTES["stop-guard-aggregate"] == "write_baseline"
