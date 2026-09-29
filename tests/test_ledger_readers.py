"""Tier 1 salvage, Track S1: decisions-report / event-tail / event-log-path / event-rotate /
inbox -- the read surface over the SAME machine-local decision ledger that `decision-record`
(tests/test_decision_record.py) writes. See the "Tier 1 salvage, Track S1" banner comment above
`decision_record` in src/tautline_methodology/cli.py for the salvage/rebuild boundary.

Two fixture styles are used, matching the two loaders the read surface itself uses:

* decisions-report / inbox read the GENERATED adapter directly via `ledger_target_data`
  (cheap, no git validation -- exactly what `autonomy-directive --hook` loads), so their tests
  hand-write a bare `.tautline.json` marker with no git repo at all (`_write_marker` /
  `_write_decision_line` below), and drive the handlers in-process through the `cli` fixture.
  This is fast enough to cover many filter/edge-case scenarios.

* event-tail / event-log-path / event-rotate read through `lane_project` (the SAME heavyweight,
  git-validated loader `decision-record` itself uses), so their tests go through the full
  git-init + render-adapters black-box pipeline (`_prepare_git_target`, mirroring
  test_decision_record.py's `_prepare_target`) and run the real CLI via the `run_cli` fixture.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
STATE_DIR = "$HOME/.local/state/tautline-test/ledger-reader-events"


# ---------------------------------------------------------------------------------------------
# Cheap fixtures (no git, no render): a hand-written GENERATED marker plus hand-written JSONL
# rows. Precise and fast -- exactly what the report/inbox loader reads, nothing more.
# ---------------------------------------------------------------------------------------------


def _write_marker(target: Path, *, state_dir: Path, repo: str = "example-org/example-saas") -> dict:
    target.mkdir(parents=True, exist_ok=True)
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["repo"] = repo
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": str(state_dir),
        "enabled": True,
    }
    (target / ".tautline.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return data


def _write_decision_line(
    cli,
    data: dict,
    target: Path,
    *,
    seq: int,
    ts: str,
    summary: str = "a decision",
    rationale: str = "a rationale",
    reversibility: str = "reversible",
    next_step: str = "proceed as decided",
    repo: str | None = None,
    awaiting_operator: bool | None = None,
    extra: dict | None = None,
) -> None:
    """Hand-write one valid tautline-decision/v1 JSONL row, matching decision_record's own
    payload shape exactly (build_event_payload + the decision-only fields decision_record adds).
    Bypasses the heavyweight git-validated write path so tests can plant many precise rows fast;
    the write side's own contract is covered by test_decision_record.py.

    `awaiting_operator=None` (the default) OMITS the key entirely -- simulating a row written
    before `--awaiting-operator` existed. Pass True/False to plant the key explicitly."""
    _human, jsonl, _lock = cli.observability_event_paths(data, target)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    lane_id = cli.instrumentation_lane_id(target)
    record = {
        "schema": "minervit-repo-event/v1",
        "ts": ts,
        "project": data.get("project"),
        "repo": repo if repo is not None else data.get("repo"),
        "repo_slug": cli.event_repo_slug(data),
        "lane": target.name,
        "branch": "main",
        "head": "abc1234",
        "goal": "",
        "milestone": "",
        "pr": "",
        "event": "decision",
        "severity": "info",
        "plain": summary,
        "next": next_step,
        "refs": {"reversibility": reversibility, "rationale": rationale},
        "methodology": {"plugin_version": "0.0.0-test", "methodology_commit": "0" * 12},
        "lane_id": lane_id,
        "seq": seq,
        "record_kind": "tautline-decision/v1",
    }
    if awaiting_operator is not None:
        record["awaiting_operator"] = awaiting_operator
    if extra:
        record.update(extra)
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _report_ns(target=None, **overrides) -> argparse.Namespace:
    base = dict(target=target, since=None, until=None, reversibility=None, grep=None, goal=None, json=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def _inbox_ns(target=None, **overrides) -> argparse.Namespace:
    base = dict(target=target, json=False)
    base.update(overrides)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------------------------
# decisions-report
# ---------------------------------------------------------------------------------------------


def test_decisions_report_table_happy_path_newest_first(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T10:00:00Z", summary="Picked postgres")
    _write_decision_line(
        cli, data, target, seq=2, ts="2026-08-29T11:00:00Z", summary="Dropped v1 API",
        reversibility="hard-to-reverse", next_step="awaiting sign-off",
    )
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "decisions: 2 total, 1 hard-to-reverse" in out
    lines = [line for line in out.splitlines() if line.startswith("2026-")]
    assert lines[0].startswith("2026-08-29T11:00:00Z") and "Dropped v1 API" in lines[0]
    assert lines[1].startswith("2026-08-29T10:00:00Z") and "Picked postgres" in lines[1]


def test_decisions_report_reads_a_lean_lane(cli, tmp_path, capsys, monkeypatch):
    # A lean-1 marker carries no observabilityEvents block, so the loader must supply the SAME
    # machine-local defaults every 1.x lane gets -- a lane migrated by `tautline slim` keeps
    # aggregating into the same ledger instead of becoming a per-target error line forever.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = tmp_path / "repo"
    target.mkdir(parents=True)
    lean_marker = {
        "schemaVersion": "lean-1",
        "project": {"name": "Example SaaS", "repo": "example-org/example-saas"},
        "integrationBranch": "main",
        "commands": {"test": "true"},
    }
    (target / ".tautline.json").write_text(
        json.dumps(lean_marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    data = cli.ledger_target_data(target)
    assert data["repo"] == "example-org/example-saas"
    assert data["observabilityEvents"]["stateDir"] == cli.DEFAULT_OBSERVABILITY_EVENTS["stateDir"]
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T10:00:00Z", summary="Lean lane decision")
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "decisions: 1 total" in out
    assert "Lean lane decision" in out


def test_decisions_report_survives_a_malformed_lean_target(cli, tmp_path, capsys, monkeypatch):
    # _ledger_targets_data's contract: one bad target becomes one error line and every OTHER
    # target still aggregates. A lean marker that fails the lean validator must therefore raise
    # SystemExit (the one exception type that loader catches), not an AttributeError that aborts
    # the whole report.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    good = tmp_path / "good"
    good.mkdir(parents=True)
    (good / ".tautline.json").write_text(
        json.dumps(
            {
                "schemaVersion": "lean-1",
                "project": {"name": "Example SaaS", "repo": "example-org/example-saas"},
                "integrationBranch": "main",
                "commands": {"test": "true"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    broken = tmp_path / "broken"
    broken.mkdir(parents=True)
    (broken / ".tautline.json").write_text(
        json.dumps({"schemaVersion": "lean-1", "project": "just-a-string"}) + "\n", encoding="utf-8"
    )
    data = cli.ledger_target_data(good)
    _write_decision_line(cli, data, good, seq=1, ts="2026-08-29T10:00:00Z", summary="Still aggregates")
    rc = cli.decisions_report(_report_ns(target=[good, broken]))
    assert rc == 0
    captured = capsys.readouterr()
    assert "Still aggregates" in captured.out
    # Table mode folds target errors into the report body (stderr is the --json convention).
    assert "lean adapter invalid" in captured.out


def test_decisions_report_json_envelope_shape(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T10:00:00Z", summary="s")
    rc = cli.decisions_report(_report_ns(target=[target], json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "tautline-decisions-report/v1"
    assert payload["scope"]["skipped_lines"] == 0
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["summary"] == "s"
    assert payload["decisions"][0]["repo"] == "example-org/example-saas"


def test_decisions_report_filters_by_reversibility(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="soft", reversibility="reversible")
    _write_decision_line(cli, data, target, seq=2, ts="2026-08-29T09:00:00Z", summary="hard", reversibility="hard-to-reverse")
    rc = cli.decisions_report(_report_ns(target=[target], reversibility="hard-to-reverse"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "hard" in out and "soft" not in out


def test_decisions_report_filters_by_grep_across_rationale(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, target, seq=1, ts="2026-08-29T08:00:00Z",
        summary="Picked postgres", rationale="team already knows SQL well",
    )
    _write_decision_line(
        cli, data, target, seq=2, ts="2026-08-29T09:00:00Z",
        summary="Picked mongo", rationale="flexible schema",
    )
    rc = cli.decisions_report(_report_ns(target=[target], grep="sql"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "postgres" in out and "mongo" not in out


def test_decisions_report_filters_by_since_until(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="early")
    _write_decision_line(cli, data, target, seq=2, ts="2026-08-29T10:00:00Z", summary="middle")
    _write_decision_line(cli, data, target, seq=3, ts="2026-08-29T12:00:00Z", summary="late")
    rc = cli.decisions_report(
        _report_ns(target=[target], since="2026-08-29T09:00:00Z", until="2026-08-29T11:00:00Z")
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "middle" in out
    assert "early" not in out and "late" not in out


def test_decisions_report_filters_by_goal(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="goal a work", extra={"goal": "GOAL-A"})
    _write_decision_line(cli, data, target, seq=2, ts="2026-08-29T09:00:00Z", summary="goal b work", extra={"goal": "GOAL-B"})
    rc = cli.decisions_report(_report_ns(target=[target], goal="GOAL-A"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "goal a work" in out and "goal b work" not in out


def test_decisions_report_skips_malformed_lines_with_count_never_crashes(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _human, jsonl, _lock = cli.observability_event_paths(data, target)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    lane_id = cli.instrumentation_lane_id(target)
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write("{ this is not valid json\n")
        handle.write(
            json.dumps(
                {
                    "event": "decision",
                    "record_kind": "tautline-decision/v1",
                    "refs": {"rationale": "x", "reversibility": "not-a-real-value"},
                    "plain": "y",
                    "next": "z",
                    "ts": "2026-08-29T00:00:00Z",
                    "seq": 1,
                    "lane_id": lane_id,
                    "lane": "repo",
                }
            )
            + "\n"
        )
    _write_decision_line(cli, data, target, seq=2, ts="2026-08-29T01:00:00Z", summary="valid one")
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "decisions: 1 total" in out
    assert "skipped: 2 decision-shaped line(s) failed validation (not counted)" in out


def test_decisions_report_sanitizes_control_characters_in_table(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, target, seq=1, ts="2026-08-29T00:00:00Z",
        summary="control\x1b[31mchar\x07here",
    )
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\x07" not in out
    assert "control" in out and "char" in out and "here" in out


def test_decisions_report_ts_field_cannot_inject_control_characters(cli, tmp_path, capsys):
    """The fromisoformat-ESC trick: Python's datetime.fromisoformat (3.11+) accepts almost any
    single byte as the date/time separator, so a `ts` carrying an ESC in place of "T" still
    parses and validates. The table must never print the raw ts string -- only the re-derived,
    airtight display built from the PARSED datetime (_safe_ts_display)."""
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, target, seq=1, ts="2026-08-29\x1b10:00:00Z", summary="esc separator row",
    )
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    # A sanitization proof, not a rejection proof: the row still validates and appears, with a
    # clean re-derived timestamp -- a validator that just discarded malformed-ts rows would hide
    # this exact bug behind "0 results, looks fine".
    assert "esc separator row" in out
    assert "2026-08-29T10:00:00Z" in out


def test_decisions_report_unreadable_ledger_source_counts_as_skipped_with_a_note(cli, tmp_path, capsys):
    """The OUTER `except OSError` in read_countable_decisions (a whole source failing to even
    open its lock -- not one corrupt line) must be as honest as the inner per-line handler: one
    skipped unit, one printed reason, never a silent zero-results report."""
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _human, jsonl, lock = cli.observability_event_paths(data, target)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text('{"irrelevant": "just needs to exist"}\n', encoding="utf-8")
    lock.mkdir(parents=True)  # a directory sitting where the lock FILE must be -> open("a") raises
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    captured = capsys.readouterr()
    assert "skipped: 1 decision-shaped line(s) failed validation (not counted)" in captured.out
    assert f"ledger: could not read {jsonl}" in captured.err


def test_decisions_report_mixed_valid_and_invalid_targets_isolates_the_bad_one(cli, tmp_path, capsys):
    good = tmp_path / "good-repo"
    bad = tmp_path / "no-such-repo"  # never created -- no adapter marker at all
    data = _write_marker(good, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, good, seq=1, ts="2026-08-29T09:00:00Z", summary="still reported")

    rc = cli.decisions_report(_report_ns(target=[good, bad]))
    assert rc == 0  # one bad target must not abort the aggregation
    out = capsys.readouterr().out
    assert "still reported" in out
    assert f"target_error: {bad}" in out


def test_decisions_report_missing_adapter_degrades_to_a_visible_error_not_a_crash(cli, tmp_path, capsys):
    target = tmp_path / "no-adapter"
    target.mkdir()
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "(no decisions recorded in scope)" in out
    assert f"target_error: {target}" in out


def test_decisions_report_falls_back_to_lane_when_repo_blank(cli, tmp_path, capsys):
    target = tmp_path / "repo-x"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T00:00:00Z", summary="no repo field", repo="")
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "repo-x" in out


def test_decisions_report_empty_scope_prints_placeholder(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    _write_marker(target, state_dir=tmp_path / "state")
    rc = cli.decisions_report(_report_ns(target=[target]))
    assert rc == 0
    assert "(no decisions recorded in scope)" in capsys.readouterr().out


def test_decisions_report_defaults_target_to_cwd(cli, tmp_path, capsys, monkeypatch):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T00:00:00Z", summary="cwd default")
    monkeypatch.chdir(target)
    rc = cli.decisions_report(_report_ns(target=None))
    assert rc == 0
    assert "cwd default" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# inbox
# ---------------------------------------------------------------------------------------------


def test_is_pending_decision_authoritative_flag_wins_regardless_of_next_wording(cli):
    assert cli.is_pending_decision({"next": "proceed as decided", "awaiting_operator": True}) is True
    assert cli.is_pending_decision(
        {"next": "totally done, no action needed", "awaiting_operator": True}
    ) is True


def test_is_pending_decision_legacy_substring_fallback_when_flag_is_false_or_absent(cli):
    assert cli.is_pending_decision(
        {"next": "Awaiting operator review", "awaiting_operator": False}
    ) is True
    assert cli.is_pending_decision({"next": "AWAITING SIGN-OFF", "awaiting_operator": False}) is True
    # Documents the fallback's known shape: literal substring, not semantic parsing. A phrase that
    # merely CONTAINS "awaiting" still flags pending -- deliberate. The authoritative flag is the
    # precise signal; this fallback exists ONLY so legacy rows (written before --awaiting-operator
    # existed) don't silently drop out of the inbox, not to be a smarter classifier.
    assert cli.is_pending_decision(
        {"next": "not awaiting anything, fully resolved", "awaiting_operator": False}
    ) is True


def test_is_pending_decision_neither_signal_is_not_pending(cli):
    assert cli.is_pending_decision({"next": "proceed as decided", "awaiting_operator": False}) is False
    assert cli.is_pending_decision(
        {"next": "resolved, no action needed", "awaiting_operator": False}
    ) is False


def test_inbox_table_and_json_include_only_pending_newest_first(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="resolved item", next_step="proceed as decided")
    _write_decision_line(cli, data, target, seq=2, ts="2026-08-29T09:00:00Z", summary="older pending", next_step="awaiting review")
    _write_decision_line(cli, data, target, seq=3, ts="2026-08-29T10:00:00Z", summary="newer pending", next_step="awaiting sign-off")
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "inbox: 2 pending decision(s) awaiting an answer" in out
    assert "resolved item" not in out
    newer_idx = out.index("newer pending")
    older_idx = out.index("older pending")
    assert newer_idx < older_idx  # newest first

    rc = cli.inbox(_inbox_ns(target=[target], json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "tautline-inbox/v1"
    assert [item["summary"] for item in payload["pending"]] == ["newer pending", "older pending"]


def test_inbox_multi_repo_aggregation_newest_first_across_repos(cli, tmp_path, capsys):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    data_a = _write_marker(repo_a, state_dir=tmp_path / "state-a", repo="example-org/repo-a")
    data_b = _write_marker(repo_b, state_dir=tmp_path / "state-b", repo="example-org/repo-b")
    _write_decision_line(cli, data_a, repo_a, seq=1, ts="2026-08-29T09:00:00Z", summary="A pending", next_step="awaiting review")
    _write_decision_line(cli, data_b, repo_b, seq=1, ts="2026-08-29T10:00:00Z", summary="B pending", next_step="awaiting sign-off")
    _write_decision_line(cli, data_a, repo_a, seq=2, ts="2026-08-29T11:00:00Z", summary="A resolved", next_step="done")

    rc = cli.inbox(_inbox_ns(target=[repo_a, repo_b], json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["summary"] for item in payload["pending"]] == ["B pending", "A pending"]
    assert {item["repo"] for item in payload["pending"]} == {"example-org/repo-a", "example-org/repo-b"}
    assert len(payload["scope"]["targets"]) == 2


def test_inbox_skips_malformed_lines_with_count(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _human, jsonl, _lock = cli.observability_event_paths(data, target)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write("garbage not json\n")
    _write_decision_line(cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="valid pending", next_step="awaiting review")
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "inbox: 1 pending decision(s)" in out
    assert "skipped: 1 decision-shaped line(s) failed validation (not counted)" in out


def test_inbox_sanitizes_control_characters(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, target, seq=1, ts="2026-08-29T08:00:00Z", summary="s",
        next_step="awaiting\x1b[31m review\x07 now",
    )
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "review" in out and "now" in out


def test_inbox_ts_field_cannot_inject_control_characters(cli, tmp_path, capsys):
    """The fromisoformat-ESC trick (see the decisions-report sibling test for the mechanism):
    a `ts` with a control byte in place of "T" still validates, so _inbox_table must render the
    re-derived, airtight display built from the PARSED datetime, never the raw ts string."""
    target = tmp_path / "repo"
    data = _write_marker(target, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, target, seq=1, ts="2026-08-29\x1b10:00:00Z", summary="esc separator row",
        next_step="awaiting review",
    )
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "esc separator row" in out
    assert "2026-08-29T10:00:00Z" in out


def test_inbox_mixed_valid_and_invalid_targets_isolates_the_bad_one(cli, tmp_path, capsys):
    good = tmp_path / "good-repo"
    bad = tmp_path / "no-such-repo"  # never created -- no adapter marker at all
    data = _write_marker(good, state_dir=tmp_path / "state")
    _write_decision_line(
        cli, data, good, seq=1, ts="2026-08-29T09:00:00Z", summary="good pending",
        next_step="awaiting review",
    )

    rc = cli.inbox(_inbox_ns(target=[good, bad], json=True))
    assert rc == 0  # one bad target must not abort the aggregation
    payload = json.loads(capsys.readouterr().out)
    assert [item["summary"] for item in payload["pending"]] == ["good pending"]
    assert len(payload["scope"]["target_errors"]) == 1
    assert str(bad) in payload["scope"]["target_errors"][0]

    # Table mode: the failure is a VISIBLE row, not silent.
    rc2 = cli.inbox(_inbox_ns(target=[good, bad]))
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "good pending" in out
    assert f"target_error: {bad}" in out


def test_inbox_empty_scope_prints_placeholder(cli, tmp_path, capsys):
    target = tmp_path / "repo"
    _write_marker(target, state_dir=tmp_path / "state")
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    assert "inbox is empty" in capsys.readouterr().out


def test_inbox_missing_adapter_degrades_to_a_visible_error_not_a_crash(cli, tmp_path, capsys):
    target = tmp_path / "no-adapter"
    target.mkdir()
    rc = cli.inbox(_inbox_ns(target=[target]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "inbox is empty" in out
    assert f"target_error: {target}" in out


# ---------------------------------------------------------------------------------------------
# event-log-path / event-tail / event-rotate -- these three go through lane_project, the SAME
# git-validated loader decision-record itself uses, so their tests go through the full
# git-init + render-adapters black-box pipeline (mirroring test_decision_record.py).
# ---------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _prepare_git_target(tmp_path, run_cli, *, name: str = "event-target") -> Path:
    target = tmp_path / name
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("two\n", encoding="utf-8")
    (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "Initial fixture", "-q")
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}), "stateDir": STATE_DIR, "enabled": True,
    }
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for ledger-reader tests.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = run_cli("render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    assert result.returncode == 0, result.stderr
    return target


def test_event_log_path_event_tail_and_event_rotate_black_box(tmp_path, run_cli):
    target = _prepare_git_target(tmp_path, run_cli)
    written = run_cli(
        "decision-record", "--target", str(target), "--summary", "s1", "--rationale", "r1",
    )
    assert written.returncode == 0, written.stderr

    path_result = run_cli("event-log-path", "--target", str(target))
    assert path_result.returncode == 0, path_result.stderr
    assert "event_log: " in path_result.stdout
    assert "event_jsonl: " in path_result.stdout
    assert f"event-tail --target {target} --lines 80" in path_result.stdout

    tail_result = run_cli("event-tail", "--target", str(target), "--lines", "5")
    assert tail_result.returncode == 0, tail_result.stderr
    assert "s1" in tail_result.stdout

    rotate_result = run_cli("event-rotate", "--target", str(target), "--force")
    assert rotate_result.returncode == 0, rotate_result.stderr
    assert "event_rotate_log: " in rotate_result.stdout
    assert "event_rotate_jsonl: " in rotate_result.stdout
    # A force-rotate with no writes afterward leaves the CURRENT (post-rotation) human log empty
    # -- proving rotation actually renamed the file rather than silently no-op'ing.
    tail_after = run_cli("event-tail", "--target", str(target), "--lines", "5")
    assert tail_after.returncode == 0, tail_after.stderr
    assert tail_after.stdout == ""


def test_event_tail_rejects_non_positive_lines(tmp_path, run_cli):
    target = _prepare_git_target(tmp_path, run_cli)
    result = run_cli("event-tail", "--target", str(target), "--lines", "0")
    assert result.returncode != 0
    assert "--lines must be positive" in result.stderr


def test_inbox_and_decisions_report_read_the_real_decision_record_output(tmp_path, run_cli):
    """Closes the loop end-to-end: decision-record (the real, git-validated write path) writes;
    decisions-report/inbox (the cheap, multi-target read path) read the SAME on-disk ledger."""
    target = _prepare_git_target(tmp_path, run_cli, name="real-write-target")
    first = run_cli(
        "decision-record", "--target", str(target), "--summary", "Picked postgres",
        "--rationale", "known", "--reversibility", "reversible",
    )
    assert first.returncode == 0, first.stderr
    second = run_cli(
        "decision-record", "--target", str(target), "--summary", "Drop the v1 API",
        "--rationale", "unused", "--reversibility", "hard-to-reverse",
        "--next", "awaiting operator sign-off",
    )
    assert second.returncode == 0, second.stderr
    # The authoritative --awaiting-operator flag, through the REAL write path, with --next
    # wording that does NOT itself contain "awaiting" -- proves the flag alone is sufficient.
    third = run_cli(
        "decision-record", "--target", str(target), "--summary", "Rotate the signing key",
        "--rationale", "operator-only credential", "--awaiting-operator",
        "--next", "proceed once approved",
    )
    assert third.returncode == 0, third.stderr

    report = run_cli("decisions-report", "--target", str(target), "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["schema"] == "tautline-decisions-report/v1"
    assert [d["summary"] for d in report_payload["decisions"]] == [
        "Rotate the signing key", "Drop the v1 API", "Picked postgres",
    ]
    assert report_payload["decisions"][0]["awaiting_operator"] is True
    assert report_payload["decisions"][1]["awaiting_operator"] is False

    inbox_result = run_cli("inbox", "--target", str(target), "--json")
    assert inbox_result.returncode == 0, inbox_result.stderr
    inbox_payload = json.loads(inbox_result.stdout)
    assert [item["summary"] for item in inbox_payload["pending"]] == [
        "Rotate the signing key", "Drop the v1 API",
    ]
