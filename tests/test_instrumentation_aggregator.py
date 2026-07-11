"""T3 (0.9.0 sanitized instrumentation): the sanitizing aggregator (rotation-aware, lane-strict).

`instrumentation_record_from_events(...)` is the pure aggregation core the window-semantics publish
pipeline (T5, not built yet) will call: it scans `events.jsonl` plus retained rotations (via the
existing `event_jsonl_read_paths()` rotation helper), filters strictly to `lane_id == this lane AND
seq > remote_max` (remote_max is a caller-supplied parameter -- T5's publisher is responsible for
fetching the real value off the archive branch; this function never touches git/network), maps known
local event names to the frozen v1 codes (`INSTRUMENTATION_EVENT_MAP` for plain counters,
`INSTRUMENTATION_PAIRED_LIFECYCLE_PRODUCERS` for started/finished/failed reducer triples,
`INSTRUMENTATION_FINALIZE_VERDICT_PRODUCERS` for verdict-bearing finalize events), and detects
`window_gap` per the remote-authoritative window semantics (no local marker state). Unmapped,
ignored, and custom/runtime `log-event` names are dropped, never guessed or passed through -- this is
the sanitization boundary between the freeform local event log and the closed instrumentation
vocabulary.
"""

import json
from pathlib import Path

LANE_A = "0123456789abcdef"
LANE_B = "fedcba9876543210"


def _event(event: str, ts: str, seq: int, *, lane_id: str = LANE_A, severity: str = "info", refs: dict | None = None, **extra: object) -> dict:
    payload = {
        "schema": "minervit-repo-event/v1",
        "ts": ts,
        "project": "Example",
        "repo": "example/example",
        "repo_slug": "example-example",
        "lane": "example",
        "branch": "main",
        "head": "abc1234",
        "goal": extra.pop("goal", ""),
        "milestone": extra.pop("milestone", ""),
        "pr": extra.pop("pr", ""),
        "event": event,
        "severity": severity,
        "plain": extra.pop("plain", f"{event} occurred"),
        "next": extra.pop("next", "n/a"),
        "refs": refs or {},
        "methodology": {"plugin_version": "0.9.0", "methodology_commit": "abc1234"},
        "lane_id": lane_id,
        "seq": seq,
    }
    payload.update(extra)
    return payload


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def _seed_seq_state(cli, monkeypatch, tmp_path: Path, lane_id: str, ts_values: list[str]) -> None:
    """Advance the real T2 seq counter for `lane_id` so its persisted seq/high-water-ts matches a
    scenario, reusing the already-tested allocate_instrumentation_seq() rather than hand-writing
    the state file."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for ts in ts_values:
        cli.allocate_instrumentation_seq(lane_id, ts)


def _aggregate(cli, jsonl_path: Path, *, lane_id: str = LANE_A, remote_max: int = 0, retained: int = 5, plugin_version: str = "0.9.0") -> dict | None:
    return cli.instrumentation_record_from_events(
        lane_id=lane_id,
        remote_max=remote_max,
        jsonl_path=jsonl_path,
        retained_rotations=retained,
        plugin_version=plugin_version,
    )


# ---------------------------------------------------------------------------
# Reducer: paired lifecycle producers (plan_review_started/finished/failed, etc.)
# ---------------------------------------------------------------------------


def test_reducer_started_finished_pairs_into_one_round_with_duration(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("plan_review_finished", "2026-07-10T12:30:00Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["plan_review_round"]["count"] == 1
    assert events["plan_review_round"]["total_seconds"] == 1800.0
    assert record["window_gap"] is False
    assert record["end_seq"] == 2


def test_reducer_started_failed_pairs_into_one_round_with_duration(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("implementation_review_started", "2026-07-10T12:00:00Z", 1),
            _event("implementation_review_failed", "2026-07-10T12:05:00Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["implementation_review_round"]["count"] == 1
    assert events["implementation_review_round"]["total_seconds"] == 300.0


def test_reducer_started_only_counts_once_with_no_duration(cli, tmp_path, monkeypatch):
    """Crash mid-round: an unpaired start counts once with no total_seconds contribution."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [_event("plan_review_started", "2026-07-10T12:00:00Z", 1)])
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["plan_review_round"]["count"] == 1
    assert "total_seconds" not in events["plan_review_round"]


def test_reducer_multiple_rounds_sum_counts_and_durations(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("plan_review_finished", "2026-07-10T12:10:00Z", 2),
            _event("plan_review_started", "2026-07-10T12:20:00Z", 3),
            _event("plan_review_finished", "2026-07-10T12:35:00Z", 4),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["plan_review_round"]["count"] == 2
    assert events["plan_review_round"]["total_seconds"] == 600.0 + 900.0


def test_reducer_new_start_closes_previous_unclosed_start_as_unpaired(cli, tmp_path, monkeypatch):
    """A second start before any terminal event closes the first as an unpaired unit (no double
    counting the eventually-finished second round as two rounds)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("plan_review_started", "2026-07-10T12:05:00Z", 2),
            _event("plan_review_finished", "2026-07-10T12:20:00Z", 3),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    # first start unpaired (no duration), second start closed by the finish (one duration entry)
    assert events["plan_review_round"]["count"] == 2
    assert events["plan_review_round"]["total_seconds"] == 900.0


def test_reducer_finalized_clean_verdict(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [_event("plan_review_finalized", "2026-07-10T12:00:00Z", 1, refs={"verdict": "clean", "unresolved_critical_count": "0", "unresolved_p1_count": "0"})],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"plan_review_clean"}


def test_reducer_finalized_clean_with_deferrals_reduces_to_clean(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [_event("implementation_review_finalized", "2026-07-10T12:00:00Z", 1, refs={"verdict": "clean-with-deferrals"})],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"implementation_review_clean"}


def test_reducer_finalized_blocked_verdict(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [_event("implementation_review_finalized", "2026-07-10T12:00:00Z", 1, refs={"verdict": "blocked"})],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"implementation_review_blocked"}


def test_reducer_finalized_with_missing_or_unknown_verdict_is_dropped_not_guessed(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_finalized", "2026-07-10T12:00:00Z", 1, refs={}),
            _event("plan_review_finalized", "2026-07-10T12:01:00Z", 2, refs={"verdict": "yolo-hostile-value"}),
        ],
    )
    record = _aggregate(cli, jsonl)
    # no mapped events, no gap -> harmless no-op
    assert record is None


def test_reducer_finalized_with_non_string_verdict_values_never_crashes_and_is_dropped(cli, tmp_path, monkeypatch):
    """Attack the verdict field itself: a hostile/corrupt line can carry ANY JSON type as
    `refs.verdict` (list, dict, int, null). Membership checks against a frozenset hash the
    operand, so an unhashable list/dict would raise TypeError without an isinstance guard -- the
    aggregator must instead treat every non-string verdict as unclassifiable (dropped, never
    guessed), exactly consistent with the unknown-verdict-string handling above."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_finalized", "2026-07-10T12:00:00Z", 1, refs={"verdict": ["clean"]}),
            _event("plan_review_finalized", "2026-07-10T12:00:01Z", 2, refs={"verdict": {"value": "clean"}}),
            _event("plan_review_finalized", "2026-07-10T12:00:02Z", 3, refs={"verdict": 7}),
            _event("plan_review_finalized", "2026-07-10T12:00:03Z", 4, refs={"verdict": None}),
            _event("startup", "2026-07-10T12:00:04Z", 5),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    # every hostile finalize is dropped without crashing; only the mapped startup survives
    assert codes == {"startup"}
    assert cli.instrumentation_record_errors(record) == []


def test_reducer_interleaved_families_no_cross_contamination(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("implementation_review_started", "2026-07-10T12:01:00Z", 2),
            _event("plan_review_finished", "2026-07-10T12:10:00Z", 3),
            _event("implementation_review_finished", "2026-07-10T12:21:00Z", 4),
            _event("plan_review_finalized", "2026-07-10T12:22:00Z", 5, refs={"verdict": "clean"}),
            _event("implementation_review_finalized", "2026-07-10T12:23:00Z", 6, refs={"verdict": "blocked"}),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["plan_review_round"]["count"] == 1
    assert events["plan_review_round"]["total_seconds"] == 600.0
    assert events["implementation_review_round"]["count"] == 1
    assert events["implementation_review_round"]["total_seconds"] == 1200.0
    assert events["plan_review_clean"]["count"] == 1
    assert events["implementation_review_blocked"]["count"] == 1


# ---------------------------------------------------------------------------
# Simple / identity mapping producers
# ---------------------------------------------------------------------------


def test_goal_advance_and_milestone_advance_variants_map_to_transition_codes(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    records = []
    seq = 1
    for choice in sorted(cli.GOAL_ADVANCE_EVENTS):
        records.append(_event(f"goal_advance_{choice.replace('-', '_')}", "2026-07-10T12:00:00Z", seq))
        seq += 1
    for choice in sorted(cli.MILESTONE_ADVANCE_EVENTS):
        records.append(_event(f"milestone_advance_{choice.replace('-', '_')}", "2026-07-10T12:00:00Z", seq))
        seq += 1
    _write_jsonl(jsonl, records)
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["goal_transition"]["count"] == len(cli.GOAL_ADVANCE_EVENTS)
    assert events["milestone_transition"]["count"] == len(cli.MILESTONE_ADVANCE_EVENTS)


def test_methodology_status_failed_maps_to_gate_block_and_passed_is_ignored(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("methodology_status_passed", "2026-07-10T12:00:00Z", 1),
            _event("methodology_status_failed", "2026-07-10T12:01:00Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["gate_block"]["count"] == 1


# ---------------------------------------------------------------------------
# Drop-unknown / custom log-event names / hostile payloads
# ---------------------------------------------------------------------------


def test_drop_unknown_event_names_never_appear(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("totally_unknown_producer_name", "2026-07-10T12:00:00Z", 1),
            _event("startup", "2026-07-10T12:00:01Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"startup"}
    dumped = json.dumps(record)
    assert "totally_unknown_producer_name" not in dumped


def test_custom_only_window_is_a_harmless_noop(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [_event("custom_name", "2026-07-10T12:00:00Z", 1)])
    record = _aggregate(cli, jsonl)
    assert record is None


def test_custom_before_mapped_window_still_produces_correct_record(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("custom_name", "2026-07-10T12:00:00Z", 1),
            _event("startup", "2026-07-10T12:05:00Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"startup"}
    assert "custom_name" not in json.dumps(record)


def test_hostile_freeform_payloads_never_appear_in_record(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    secret = "CONFIDENTIAL-PRODUCT-CODENAME-ZEBRA"
    _write_jsonl(
        jsonl,
        [
            _event(
                "startup",
                "2026-07-10T12:00:00Z",
                1,
                plain=f"Lane started for {secret}",
                next="Continue with the secret roadmap",
                goal=secret,
                refs={"leak": secret, "path": "/Users/someone/secret-repo"},
            ),
            _event("product_note_published", "2026-07-10T12:01:00Z", 2, plain=secret, refs={"note": secret}),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    dumped = json.dumps(record)
    assert secret not in dumped
    assert "/Users/someone/secret-repo" not in dumped
    assert cli.instrumentation_record_errors(record) == []


def test_hostile_non_string_event_field_is_safely_ignored(cli, tmp_path, monkeypatch):
    """Attack every field: a non-string `event` value (e.g. a list, from a hostile/malformed line)
    must never be treated as classifiable -- it is silently dropped rather than raising or being
    miscounted (a naive `name in some_dict` lookup would raise TypeError on an unhashable list)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    hostile_event_type = _event("startup", "2026-07-10T12:00:01Z", 1)
    hostile_event_type["event"] = ["startup"]
    _write_jsonl(jsonl, [hostile_event_type])
    record = _aggregate(cli, jsonl)
    assert record is None


def test_hostile_boolean_seq_value_is_never_treated_as_a_real_match(cli, tmp_path, monkeypatch):
    """`seq: true` is valid JSON and Python's bool is an int subclass (True <= 0 is False), so
    without an explicit bool guard a hostile/malformed line could smuggle a match past the
    remote_max filter. It must be excluded from the surviving set entirely, exactly like an
    untagged pre-0.9.0 event (this then genuinely looks like seq 1 went missing to the scanner --
    the same as the ignored-events-age-out over-report case -- so a real high-water-ts-anchored gap
    record with empty events is the correct, non-crashing outcome, not a raised exception)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    hostile_bool_seq = _event("startup", "2026-07-10T12:00:00Z", 1)
    hostile_bool_seq["seq"] = True
    real_event = _event("startup", "2026-07-10T12:00:01Z", 2)
    _write_jsonl(jsonl, [hostile_bool_seq, real_event])
    _seed_seq_state(cli, monkeypatch, tmp_path, LANE_A, ["2026-07-10T12:00:00+00:00", "2026-07-10T12:00:01+00:00"])
    record = _aggregate(cli, jsonl, remote_max=1)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["startup"]["count"] == 1
    assert record["end_seq"] == 2


# ---------------------------------------------------------------------------
# Lane discrimination
# ---------------------------------------------------------------------------


def test_lane_filter_two_lanes_in_one_file_only_this_lane_counted(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("startup", "2026-07-10T12:00:00Z", 1, lane_id=LANE_A),
            _event("startup", "2026-07-10T12:00:00Z", 1, lane_id=LANE_B),
            _event("task_started", "2026-07-10T12:00:01Z", 2, lane_id=LANE_B),
        ],
    )
    record = _aggregate(cli, jsonl, lane_id=LANE_A)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["startup"]["count"] == 1
    assert "task_started" not in events


def test_untagged_pre_0_9_0_events_without_lane_id_are_dropped(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    legacy = _event("startup", "2026-07-10T12:00:00Z", 1)
    del legacy["lane_id"]
    del legacy["seq"]
    _write_jsonl(jsonl, [legacy, _event("startup", "2026-07-10T12:00:01Z", 1)])
    record = _aggregate(cli, jsonl)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["startup"]["count"] == 1


# ---------------------------------------------------------------------------
# remote_max filtering + rotation-awareness
# ---------------------------------------------------------------------------


def test_remote_max_filters_already_published_events(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("startup", "2026-07-10T12:00:00Z", 1),
            _event("task_started", "2026-07-10T12:00:01Z", 2),
            _event("task_completed", "2026-07-10T12:00:02Z", 3),
        ],
    )
    record = _aggregate(cli, jsonl, remote_max=2)
    assert record is not None
    codes = {e["code"] for e in record["events"]}
    assert codes == {"task_completed"}
    assert record["end_seq"] == 3


def test_remote_anchor_already_published_events_surviving_in_retained_rotation_never_reaggregated(cli, tmp_path, monkeypatch):
    """Already-published events (seq <= remote_max) that still physically survive in a retained
    rotation file must never be re-aggregated -- the remote's own recorded max is the only bound
    that matters, not which physical file the bytes happen to live in."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    rotation_1 = tmp_path / "events.jsonl.1"
    _write_jsonl(
        rotation_1,
        [
            _event("startup", "2026-07-10T11:00:00Z", 1),
            _event("task_started", "2026-07-10T11:00:01Z", 2),
            _event("task_completed", "2026-07-10T11:00:02Z", 3),
        ],
    )
    _write_jsonl(
        jsonl,
        [
            _event("task_started", "2026-07-10T12:00:00Z", 4),
            _event("task_completed", "2026-07-10T12:00:01Z", 5),
        ],
    )
    record = _aggregate(cli, jsonl, remote_max=3)
    assert record is not None
    events = {e["code"]: e for e in record["events"]}
    assert events["task_started"]["count"] == 1
    assert events["task_completed"]["count"] == 1
    assert record["end_seq"] == 5
    # only the new seq-4/5 window contributed -- the already-published seq 1-3 window did not
    # double up counts (each code above shows exactly 1, not 2)


def test_rotation_between_publishes_scans_across_rotation_boundary(cli, tmp_path, monkeypatch):
    """Simulates two sequential publishes with a rotation happening between them: first publish
    sees seq 1-3 in the (then-current) base file; a rotation moves that file to .1 and a fresh base
    file starts with seq 4-5; the second publish (remote_max=3, the first publish's end_seq) must
    still find the new events even though the physical file identity changed."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("startup", "2026-07-10T11:00:00Z", 1),
            _event("task_started", "2026-07-10T11:00:01Z", 2),
            _event("task_completed", "2026-07-10T11:00:02Z", 3),
        ],
    )
    first = _aggregate(cli, jsonl, remote_max=0)
    assert first is not None
    assert first["end_seq"] == 3

    # simulate rotation: current file becomes .1, fresh events.jsonl holds the new window
    jsonl.rename(tmp_path / "events.jsonl.1")
    _write_jsonl(
        jsonl,
        [
            _event("task_started", "2026-07-10T12:00:00Z", 4),
            _event("task_completed", "2026-07-10T12:05:00Z", 5),
        ],
    )
    second = _aggregate(cli, jsonl, remote_max=first["end_seq"])
    assert second is not None
    events = {e["code"]: e for e in second["events"]}
    assert events["task_started"]["count"] == 1
    assert events["task_completed"]["count"] == 1
    assert second["end_seq"] == 5


# ---------------------------------------------------------------------------
# Gap semantics
# ---------------------------------------------------------------------------


def test_gap_detected_when_smallest_surviving_seq_skips_ahead_of_remote_max_plus_one(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [_event("task_completed", "2026-07-10T12:00:05Z", 5)])
    record = _aggregate(cli, jsonl, remote_max=2)
    assert record is not None
    assert record["window_gap"] is True


def test_gap_detected_on_discontinuity_inside_surviving_range(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("task_started", "2026-07-10T12:00:00Z", 1),
            # seq 2 is missing entirely (ignored event aged out of retention, or genuine loss)
            _event("task_completed", "2026-07-10T12:00:05Z", 3),
        ],
    )
    record = _aggregate(cli, jsonl, remote_max=0)
    assert record is not None
    assert record["window_gap"] is True


def test_gap_over_reports_when_ignored_events_age_out_indistinguishable_from_loss(cli, tmp_path, monkeypatch):
    """window_gap deliberately over-reports: an aged-out IGNORED event (never even scanned/mapped)
    leaves a seq hole indistinguishable from genuine loss, and the design says this must never
    under-report -- so this discontinuity flags a gap exactly like a real loss would."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("task_started", "2026-07-10T12:00:00Z", 1),
            # seq 2 would have been e.g. "methodology_status_passed" (ignored) had it survived
            _event("task_completed", "2026-07-10T12:00:05Z", 3),
        ],
    )
    record = _aggregate(cli, jsonl, remote_max=0)
    assert record is not None
    assert record["window_gap"] is True


def test_gap_with_no_surviving_events_but_high_water_exceeds_remote_max_is_complete_loss(cli, tmp_path, monkeypatch):
    """A complete-loss window (zero mapped events survive) must still publish its empty window_gap
    record -- gap emission is never skipped by the no-op path."""
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [])
    _seed_seq_state(cli, monkeypatch, tmp_path, LANE_A, ["2026-07-10T09:00:00+00:00", "2026-07-10T09:05:00+00:00"])
    record = _aggregate(cli, jsonl, remote_max=0)
    assert record is not None
    assert record["window_gap"] is True
    assert record["events"] == []
    assert record["window_seconds"] == 0
    assert record["end_seq"] == 2
    assert record["emitted_at"] == "2026-07-10T09:05:00+00:00"


def test_idle_window_with_nothing_new_is_a_noop(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [_event("startup", "2026-07-10T12:00:00Z", 1)])
    record = _aggregate(cli, jsonl, remote_max=1)
    assert record is None


def test_ignored_only_window_with_no_gap_is_a_noop(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(jsonl, [_event("methodology_status_passed", "2026-07-10T12:00:00Z", 1)])
    record = _aggregate(cli, jsonl, remote_max=0)
    assert record is None


def test_window_seconds_is_zero_for_gap_records_even_with_mapped_events(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("startup", "2026-07-10T12:00:00Z", 5),
            _event("task_started", "2026-07-10T13:00:00Z", 6),
        ],
    )
    record = _aggregate(cli, jsonl, remote_max=2)
    assert record is not None
    assert record["window_gap"] is True
    assert record["window_seconds"] == 0


# ---------------------------------------------------------------------------
# emitted_at / determinism / schema validity
# ---------------------------------------------------------------------------


def test_emitted_at_derives_from_last_mapped_event_ts(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("startup", "2026-07-10T12:00:00Z", 1),
            _event("task_started", "2026-07-10T12:30:00Z", 2),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    assert record["emitted_at"] == "2026-07-10T12:30:00+00:00"


def test_every_reducer_scenario_produces_a_schema_valid_record(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("plan_review_finished", "2026-07-10T12:10:00Z", 2),
            _event("plan_review_finalized", "2026-07-10T12:11:00Z", 3, refs={"verdict": "clean"}),
            _event("context_rotation", "2026-07-10T12:12:00Z", 4),
            _event("goal_advance_startup", "2026-07-10T12:13:00Z", 5),
        ],
    )
    record = _aggregate(cli, jsonl)
    assert record is not None
    assert cli.instrumentation_record_errors(record) == []


def test_determinism_same_window_produces_byte_identical_record(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    jsonl = tmp_path / "events.jsonl"
    _write_jsonl(
        jsonl,
        [
            _event("plan_review_started", "2026-07-10T12:00:00Z", 1),
            _event("plan_review_finished", "2026-07-10T12:10:00Z", 2),
        ],
    )
    first = _aggregate(cli, jsonl)
    second = _aggregate(cli, jsonl)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
