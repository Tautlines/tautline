"""`decisions-report` (D1) + `prepare-session-journal` decision window (D2): the machine-local READ
surface over the decision ledger written by `decision-record`.

The report is rotation-aware, lock-guarded, collision-safe, and totally validated -- every rendered
value passes a type-safe validator, same-repo worktrees that share one event log are de-duplicated,
and both `lane` and `lane_id` are printed so basename collisions stay distinguishable. The journal
records three preparation-time lines (count, convenience pointer, monotonic watermark) chained to
the nearest older validating journal.

Black-box subprocess runs use a hermetic HOME (mirroring validate.sh isolation) so the telemetry
salt + per-lane seq/lane_id allocator state under $HOME/.local/state never touches the real machine.
Synthetic decision lines are written directly to the shared events.jsonl (with the lane's real
lane_id, learned from one seeded record) so seq/ts/rotation/eviction cases are exactly controlled.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
STATE_DIR = "$HOME/.local/state/tautline-test/decisions-report"
CAP = 1000

JOURNAL_BODY = """## Starting Context
- Started from a generated adapter-backed lane with startup gates complete.

## Work Delivered Or Advanced
- Exercised the decisions-report read surface and journal window.

## Planning And Review Gates
- Plan review requirements remained active; no implementation bypass introduced.

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


def _run_cli(tmp_path, *args, stdin=None, check=True, timeout=90):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _write_event_adapter(target: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": STATE_DIR,
        "enabled": True,
    }
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for decisions-report behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path, name="report-target", subdir=None):
    parent = tmp_path / subdir if subdir else tmp_path
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name
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
    adapter = _write_event_adapter(target)
    _run_cli(tmp_path, "render-adapters", "--project", str(adapter),
             "--target", str(target), "--write")
    return target


def _header(total, hard):
    return f"decisions: {total} total, {hard} hard-to-reverse (retained rotations only)"


def _jsonl_path(tmp_path, target) -> Path:
    out = _run_cli(tmp_path, "event-log-path", "--target", str(target))
    for line in out.stdout.splitlines():
        if line.startswith("event_jsonl: "):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"event_jsonl missing:\n{out.stdout}")


def _seed(tmp_path, target):
    """One real decision-record so the lane_id + shared jsonl exist; returns (lane_id, jsonl).

    The event log is repo-scoped and SHARED across same-repo lanes, so this reads the just-appended
    LAST line (this target's record), not line [0] (which would be an earlier sibling's record)."""
    _run_cli(tmp_path, "decision-record", "--target", str(target), "--summary", "seed",
             "--rationale", "seed rationale")
    jsonl = _jsonl_path(tmp_path, target)
    rec = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()][-1]
    return rec["lane_id"], jsonl


def _decision(*, ts, seq, lane_id, lane="report-target", summary="chose a path",
              rationale="because it was safest", reversibility="reversible",
              alternatives=None, surfaces=None, goal="", milestone="", pr="",
              record_kind="tautline-decision/v1", event="decision"):
    refs = {"rationale": rationale, "reversibility": reversibility}
    if alternatives is not None:
        refs["alternatives"] = alternatives
    if surfaces is not None:
        refs["surfaces"] = surfaces
    payload = {
        "schema": "minervit-event-log/v1", "event": event, "ts": ts, "seq": seq,
        "lane_id": lane_id, "lane": lane, "plain": summary, "refs": refs,
        "goal": goal, "milestone": milestone, "pr": pr, "severity": "info",
    }
    if record_kind is not None:
        payload["record_kind"] = record_kind
    return payload


def _write_lines(jsonl: Path, payloads) -> None:
    jsonl.write_text("\n".join(json.dumps(p) for p in payloads) + "\n", encoding="utf-8")


def _report_json(tmp_path, *args, check=True):
    out = _run_cli(tmp_path, "decisions-report", *args, "--json", check=check)
    if out.returncode != 0:
        return out, None
    return out, json.loads(out.stdout)


TS_A = "2026-07-19T10:00:00Z"
TS_B = "2026-07-19T11:00:00Z"
TS_SAME = "2026-07-19T12:00:00Z"


# ---------------------------------------------------------------------------
# T1: ordering
# ---------------------------------------------------------------------------

def test_report_lists_decisions_most_recent_first(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="older"),
        _decision(ts=TS_B, seq=2, lane_id=lane_id, summary="newer"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert [d["summary"] for d in env["decisions"]] == ["newer", "older"]


def test_report_same_second_rows_ordered_by_seq_desc(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_SAME, seq=5, lane_id=lane_id, summary="s5"),
        _decision(ts=TS_SAME, seq=9, lane_id=lane_id, summary="s9"),
        _decision(ts=TS_SAME, seq=7, lane_id=lane_id, summary="s7"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert [d["seq"] for d in env["decisions"]] == [9, 7, 5]


def test_report_cross_lane_deterministic_order(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    # Same repo slug -> one shared jsonl; two lanes, identical ts, so lane_id breaks the tie.
    _write_lines(jsonl, [
        _decision(ts=TS_SAME, seq=1, lane_id=lid_a, lane="lane-a", summary="from-a"),
        _decision(ts=TS_SAME, seq=1, lane_id=lid_b, lane="lane-b", summary="from-b"),
    ])
    _, env = _report_json(tmp_path, "--target", str(a), "--target", str(b))
    order = [d["lane_id"] for d in env["decisions"]]
    assert order == sorted([lid_a, lid_b], reverse=True)


# ---------------------------------------------------------------------------
# T1: time + seq bounds
# ---------------------------------------------------------------------------

def test_report_since_duration_filters(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_lines(jsonl, [
        _decision(ts=old, seq=1, lane_id=lane_id, summary="old"),
        _decision(ts=fresh, seq=2, lane_id=lane_id, summary="fresh"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--since", "1h")
    assert [d["summary"] for d in env["decisions"]] == ["fresh"]


def test_report_since_iso_filters(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="ten"),
        _decision(ts=TS_B, seq=2, lane_id=lane_id, summary="eleven"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--since", "2026-07-19T10:30:00Z")
    assert [d["summary"] for d in env["decisions"]] == ["eleven"]


def test_report_until_bound_inclusive(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="ten"),
        _decision(ts=TS_B, seq=2, lane_id=lane_id, summary="eleven"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--until", TS_A)
    assert [d["summary"] for d in env["decisions"]] == ["ten"]  # exactly-at-bound is included


def test_report_since_exclusive(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id, summary="ten")])
    _, env = _report_json(tmp_path, "--target", str(target), "--since", TS_A)
    assert env["decisions"] == []  # exactly-at-bound is excluded on the lower bound


def test_report_iso_zoneless_treated_utc(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    # Zone-less bound must not raise on the aware (Z) record ts and must mean UTC.
    _write_lines(jsonl, [
        _decision(ts="2026-07-19T09:00:00Z", seq=1, lane_id=lane_id, summary="nine"),
        _decision(ts="2026-07-19T11:00:00Z", seq=2, lane_id=lane_id, summary="eleven"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--since", "2026-07-19T10:00:00")
    assert [d["summary"] for d in env["decisions"]] == ["eleven"]


def test_report_seq_bounds_total_order(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=s, lane_id=lane_id, summary=f"s{s}") for s in (1, 2, 3, 4, 5)
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--since-seq", "2", "--until-seq", "4")
    assert sorted(d["seq"] for d in env["decisions"]) == [3, 4]  # exclusive lower, inclusive upper


def test_report_seq_bounds_require_single_target(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    _seed(tmp_path, a)
    _seed(tmp_path, b)
    out = _run_cli(tmp_path, "decisions-report", "--target", str(a), "--target", str(b),
                   "--since-seq", "1", check=False)
    assert out.returncode != 0
    assert "require exactly one --target" in out.stderr


def test_report_negative_seq_bounds_rejected(tmp_path):
    target = _prepare_target(tmp_path)
    _seed(tmp_path, target)
    for flag in ("--since-seq", "--until-seq"):
        out = _run_cli(tmp_path, "decisions-report", "--target", str(target),
                       flag, "-1", check=False)
        assert out.returncode != 0, f"{flag} -1 should be rejected"
        assert "non-negative integer" in out.stderr
    # zero is a legitimate bound (a first journal with no retained decisions -> --until-seq 0)
    ok = _run_cli(tmp_path, "decisions-report", "--target", str(target), "--until-seq", "0")
    assert ok.returncode == 0


def test_report_goal_filter(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="g1", goal="alpha"),
        _decision(ts=TS_B, seq=2, lane_id=lane_id, summary="g2", goal="beta"),
    ])
    _, env = _report_json(tmp_path, "--target", str(target), "--goal", "alpha")
    assert [d["summary"] for d in env["decisions"]] == ["g1"]
    assert env["scope"]["goal"] == "alpha"


# ---------------------------------------------------------------------------
# T1: multi-target / collision / attribution
# ---------------------------------------------------------------------------

def test_report_multiple_targets_merge(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lid_a, lane="lane-a", summary="from-a"),
        _decision(ts=TS_B, seq=1, lane_id=lid_b, lane="lane-b", summary="from-b"),
    ])
    _, env = _report_json(tmp_path, "--target", str(a), "--target", str(b))
    assert {d["summary"] for d in env["decisions"]} == {"from-a", "from-b"}


def test_report_same_repo_two_lanes_no_duplication(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    # both targets resolve to the SAME shared jsonl; reading both must not double-count.
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lid_a, lane="lane-a", summary="only-a")])
    _, env = _report_json(tmp_path, "--target", str(a), "--target", str(b))
    assert [d["summary"] for d in env["decisions"]] == ["only-a"]


def test_report_filters_sibling_lane_decisions(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lid_a, lane="lane-a", summary="mine"),
        _decision(ts=TS_B, seq=1, lane_id=lid_b, lane="lane-b", summary="sibling"),
    ])
    _, env = _report_json(tmp_path, "--target", str(a))  # only lane-a requested
    assert [d["summary"] for d in env["decisions"]] == ["mine"]
    assert env["scope"]["skipped_lines"] == 0  # a valid other-lane record is ignored, not skipped


def test_report_basename_collision_not_confused(tmp_path):
    a = _prepare_target(tmp_path, name="collide", subdir="a")
    b = _prepare_target(tmp_path, name="collide", subdir="b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    assert lid_a != lid_b  # same basename, different resolved paths -> different lane_ids
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lid_a, lane="collide", summary="from-a"),
        _decision(ts=TS_B, seq=1, lane_id=lid_b, lane="collide", summary="from-b"),
    ])
    out = _run_cli(tmp_path, "decisions-report", "--target", str(a), "--target", str(b))
    # human blocks are distinguishable ONLY via lane_id (basename is identical)
    assert lid_a in out.stdout and lid_b in out.stdout


# ---------------------------------------------------------------------------
# T1: rotation-aware, retained scope
# ---------------------------------------------------------------------------

def test_report_includes_retained_rotation(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    rotated = jsonl.with_name(jsonl.name + ".1")
    _write_lines(rotated, [_decision(ts=TS_A, seq=1, lane_id=lane_id, summary="in-rotation")])
    _write_lines(jsonl, [_decision(ts=TS_B, seq=2, lane_id=lane_id, summary="current")])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert {d["summary"] for d in env["decisions"]} == {"in-rotation", "current"}


def test_report_header_always_notes_retained_scope(tmp_path):
    target = _prepare_target(tmp_path)
    _seed(tmp_path, target)
    _jsonl_path(tmp_path, target).write_text("", encoding="utf-8")
    out = _run_cli(tmp_path, "decisions-report", "--target", str(target))
    assert out.stdout.splitlines()[0] == _header(0, 0)
    # and the machine envelope carries the same scope honesty
    _, env = _report_json(tmp_path, "--target", str(target))
    assert env["scope"]["retained_rotations_only"] is True


def test_report_tolerates_rotation_during_read(tmp_path, monkeypatch):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id, summary="present")])
    # A path enumerated but removed before read must be tolerated, not crash.
    out = _run_cli(tmp_path, "decisions-report", "--target", str(target))
    assert out.returncode == 0


# ---------------------------------------------------------------------------
# T1: validator / skip diagnostics
# ---------------------------------------------------------------------------

def test_report_freeform_log_event_decision_not_counted(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    # event == "decision" but NO top-level record_kind (free-form log-event) -> skipped, uncounted
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id, record_kind=None)])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert env["decisions"] == []
    assert env["scope"]["skipped_lines"] == 1


MALFORMED_CASES = {
    "plain_missing": lambda d: d.pop("plain"),
    "plain_blank": lambda d: d.update(plain="   "),
    "plain_nonstr": lambda d: d.update(plain=5),
    "plain_overcap": lambda d: d.update(plain="x" * (CAP + 1)),
    "ts_unparseable": lambda d: d.update(ts="not-a-timestamp"),
    "ts_nonstr": lambda d: d.update(ts=123),
    "seq_bool": lambda d: d.update(seq=True),
    "seq_zero": lambda d: d.update(seq=0),
    "seq_negative": lambda d: d.update(seq=-1),
    "seq_string": lambda d: d.update(seq="3"),
    "seq_missing": lambda d: d.pop("seq"),
    "lane_id_blank": lambda d: d.update(lane_id="   "),
    "lane_id_nonstr": lambda d: d.update(lane_id=7),
    "lane_blank": lambda d: d.update(lane="   "),
    "lane_overcap": lambda d: d.update(lane="x" * (CAP + 1)),
    "lane_nonstr": lambda d: d.update(lane=9),
    "refs_not_dict": lambda d: d.update(refs="nope"),
    "rationale_missing": lambda d: d["refs"].pop("rationale"),
    "rationale_blank": lambda d: d["refs"].update(rationale="   "),
    "rationale_overcap": lambda d: d["refs"].update(rationale="x" * (CAP + 1)),
    "rationale_nonstr": lambda d: d["refs"].update(rationale=3),
    "reversibility_bad": lambda d: d["refs"].update(reversibility="maybe"),
    "reversibility_missing": lambda d: d["refs"].pop("reversibility"),
    "record_kind_wrong": lambda d: d.update(record_kind="tautline-decision/v2"),
    "alternatives_nonstr": lambda d: d["refs"].update(alternatives=123),
    "alternatives_overcap": lambda d: d["refs"].update(alternatives="x" * (CAP + 1)),
    "alternatives_blank": lambda d: d["refs"].update(alternatives="   "),
    "surfaces_overcap": lambda d: d["refs"].update(surfaces="x" * (CAP + 1)),
    "surfaces_nonstr": lambda d: d["refs"].update(surfaces=5),
    "goal_nonstr": lambda d: d.update(goal=5),
    "goal_overcap": lambda d: d.update(goal="x" * (CAP + 1)),
    "milestone_overcap": lambda d: d.update(milestone="x" * (CAP + 1)),
    "pr_nonstr": lambda d: d.update(pr=[1]),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_CASES))
def test_report_malformed_marked_record_skipped(tmp_path, case):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    payload = _decision(ts=TS_A, seq=1, lane_id=lane_id)
    MALFORMED_CASES[case](payload)
    _write_lines(jsonl, [payload])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert env["decisions"] == [], f"{case} must not be counted"
    assert env["scope"]["skipped_lines"] == 1, f"{case} must land in the skipped diagnostic"


def test_report_sibling_lane_malformed_row_not_counted(tmp_path):
    # A sibling lane's MALFORMED decision row (readable non-target lane_id) is ignored exactly like
    # a valid sibling row -- it must not inflate the current lane's scoped skipped diagnostic.
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    bad_sibling = _decision(ts=TS_B, seq=1, lane_id=lid_b, lane="lane-b")
    bad_sibling["refs"].update(reversibility="maybe")  # malformed, but a clear non-target lane_id
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lid_a, lane="lane-a"), bad_sibling])
    _, env = _report_json(tmp_path, "--target", str(a))  # only lane-a requested
    assert len(env["decisions"]) == 1
    assert env["scope"]["skipped_lines"] == 0  # the sibling's malformed row is attributed away
    # a malformed row with an UNREADABLE lane_id stays counted (unattributable)
    unattributable = _decision(ts=TS_B, seq=2, lane_id=lid_a, lane="lane-a")
    unattributable["lane_id"] = 999  # non-str -> cannot attribute
    _write_lines(jsonl, [unattributable])
    _, env2 = _report_json(tmp_path, "--target", str(a))
    assert env2["scope"]["skipped_lines"] == 1


def test_report_interleaved_nondecision_events_no_side_effects(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    ordinary = {"schema": "minervit-event-log/v1", "event": "startup", "ts": TS_A, "seq": 2,
                "lane_id": lane_id, "lane": "report-target", "plain": "boot", "refs": {}}
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="d1"),
        ordinary,
        _decision(ts=TS_B, seq=3, lane_id=lane_id, summary="d3"),  # seqs non-contiguous, normal
    ])
    _, env = _report_json(tmp_path, "--target", str(target))
    assert [d["seq"] for d in env["decisions"]] == [3, 1]
    assert env["scope"]["skipped_lines"] == 0  # an ordinary event is ignored, not skipped


# ---------------------------------------------------------------------------
# T1: JSON envelope
# ---------------------------------------------------------------------------

def test_report_json_envelope_shape(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, env = _report_json(tmp_path, "--target", str(target), "--since-seq", "0", "--until-seq", "5")
    assert env["schema"] == "tautline-decisions-report/v1"
    scope = env["scope"]
    assert scope["retained_rotations_only"] is True
    assert scope["targets"] == [lane_id]
    assert scope["since_seq"] == 0 and scope["until_seq"] == 5
    assert scope["since"] is None and scope["until"] is None
    assert scope["skipped_lines"] == 0
    assert isinstance(env["decisions"], list) and len(env["decisions"]) == 1
    # empty case: still a single envelope object with an empty decisions array
    jsonl.write_text("", encoding="utf-8")
    _, empty = _report_json(tmp_path, "--target", str(target))
    assert empty["schema"] == "tautline-decisions-report/v1"
    assert empty["decisions"] == []


def test_report_json_closed_projection(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    payload = _decision(ts=TS_A, seq=1, lane_id=lane_id, summary="s", rationale="r",
                        reversibility="hard-to-reverse", alternatives="alt", surfaces="bin,tests",
                        goal="g", milestone="m", pr="p")
    payload["injected_secret"] = "should never surface"  # extra raw payload field
    payload["refs"]["extra_ref"] = "also hidden"
    _write_lines(jsonl, [payload])
    _, env = _report_json(tmp_path, "--target", str(target))
    d = env["decisions"][0]
    assert set(d) == {"ts", "lane", "lane_id", "seq", "summary", "rationale",
                      "alternatives", "reversibility", "surfaces", "goal", "milestone", "pr"}
    assert d["goal"] == "g" and d["surfaces"] == "bin,tests"
    # a validated row with empty optionals projects nulls, never the raw empty strings
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, env2 = _report_json(tmp_path, "--target", str(target))
    d2 = env2["decisions"][0]
    assert d2["goal"] is None and d2["milestone"] is None and d2["pr"] is None
    assert d2["alternatives"] is None and d2["surfaces"] is None


def test_report_json_with_corrupt_line_stderr_diag(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    good = json.dumps(_decision(ts=TS_A, seq=1, lane_id=lane_id))
    jsonl.write_text(good + "\n{ this is not json\n", encoding="utf-8")
    out = _run_cli(tmp_path, "decisions-report", "--target", str(target), "--json")
    env = json.loads(out.stdout)
    assert env["scope"]["skipped_lines"] == 1  # authoritative count
    assert out.stderr.strip()  # free-text warning on stderr, envelope stays clean on stdout
    assert len(env["decisions"]) == 1


def test_report_empty_log_zero_exit(tmp_path):
    target = _prepare_target(tmp_path)
    # never seeded: the events dir/log may not exist at all
    out = _run_cli(tmp_path, "decisions-report", "--target", str(target))
    assert out.returncode == 0
    assert out.stdout.splitlines()[0] == _header(0, 0)


def test_report_counts_hard_to_reverse(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lane_id, reversibility="reversible"),
        _decision(ts=TS_B, seq=2, lane_id=lane_id, reversibility="hard-to-reverse"),
        _decision(ts=TS_SAME, seq=3, lane_id=lane_id, reversibility="hard-to-reverse"),
    ])
    out = _run_cli(tmp_path, "decisions-report", "--target", str(target))
    assert out.stdout.splitlines()[0] == _header(3, 2)


# ===========================================================================
# T2: journal integration
# ===========================================================================

def _prepare_journal(tmp_path, target, body=JOURNAL_BODY):
    out = _run_cli(tmp_path, "prepare-session-journal", "--target", str(target),
                   "--stdin", stdin=body)
    for line in out.stdout.splitlines():
        if line.startswith("session_journal_valid: "):
            return out, Path(line.split(": ", 1)[1])
    return out, None


def _journal_dir(target) -> Path:
    return target / ".ai-runs" / "session-journals"


def _runtime_field(path: Path, field: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().lstrip("- ").strip()
        if stripped.startswith(f"{field}:"):
            return stripped.split(":", 1)[1].strip()
    raise AssertionError(f"field {field} not found in {path.name}")


def test_journal_includes_decision_count(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=s, lane_id=lane_id) for s in (1, 2, 3)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == "3 (all retained through seq 3)"
    assert _runtime_field(journal, "decisions_watermark_seq") == "3"


def test_journal_zero_new_decisions_rendering(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=40, lane_id=lane_id)])
    _prepare_journal(tmp_path, target)  # first journal -> watermark 40
    # nothing newer than seq 40 remains
    _write_lines(jsonl, [_decision(ts=TS_A, seq=40, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == \
        "0 (no retained decisions newer than seq 40)"


def test_journal_zero_form_after_eviction(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=40, lane_id=lane_id)])
    _prepare_journal(tmp_path, target)  # watermark 40
    # a post-watermark decision (seq 41) recorded then EVICTED before this preparation
    jsonl.write_text("", encoding="utf-8")
    _, journal = _prepare_journal(tmp_path, target)
    # the qualified zero form, never a false absolute "none newer" claim
    assert _runtime_field(journal, "decisions_recorded") == \
        "0 (no retained decisions newer than seq 40)"
    assert _runtime_field(journal, "decisions_watermark_seq") == "40"


def test_journal_generated_zero_pointer_executes(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    jsonl.write_text("", encoding="utf-8")  # no retained decisions at all
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == "0 (all retained through seq 0)"
    pointer = _runtime_field(journal, "decisions_report")
    assert pointer == "tautline decisions-report --target . --until-seq 0"
    # the generated pointer must actually run and exit 0
    run = _run_cli(tmp_path, "decisions-report", "--target", str(target), "--until-seq", "0")
    assert run.returncode == 0


def test_journal_concurrent_preparations_serialized(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    procs = []
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for _ in range(3):
        procs.append(subprocess.Popen(
            [sys.executable, str(CLI_PATH), "prepare-session-journal",
             "--target", str(target), "--stdin"],
            env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))
    for proc in procs:
        proc.communicate(input=JOURNAL_BODY, timeout=120)
        assert proc.returncode == 0
    journals = sorted(_journal_dir(target).glob("*-session-journal*.md"))
    assert len(journals) == 3  # distinct destinations, no overwrite
    watermarks = {_runtime_field(j, "decisions_watermark_seq") for j in journals}
    assert watermarks == {"1"}  # each saw the one retained decision; no duplicated window


def test_journal_includes_report_pointer_dot_target(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    pointer = _runtime_field(journal, "decisions_report")
    assert pointer == "tautline decisions-report --target . --until-seq 1"
    assert str(target) not in pointer  # never a person-specific absolute path


def test_journal_count_excludes_sibling_lane(tmp_path):
    a = _prepare_target(tmp_path, name="lane-a")
    b = _prepare_target(tmp_path, name="lane-b")
    lid_a, jsonl = _seed(tmp_path, a)
    lid_b, _ = _seed(tmp_path, b)
    _write_lines(jsonl, [
        _decision(ts=TS_A, seq=1, lane_id=lid_a, lane="lane-a"),
        _decision(ts=TS_B, seq=2, lane_id=lid_b, lane="lane-b"),
        _decision(ts=TS_SAME, seq=3, lane_id=lid_a, lane="lane-a"),
    ])
    _, journal = _prepare_journal(tmp_path, a)
    assert _runtime_field(journal, "decisions_recorded") == "2 (all retained through seq 3)"


def test_journal_count_includes_retained_rotation(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    rotated = jsonl.with_name(jsonl.name + ".1")
    _write_lines(rotated, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _write_lines(jsonl, [_decision(ts=TS_B, seq=2, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == "2 (all retained through seq 2)"


def test_journal_watermark_seq_persisted_machine_readable(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=7, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_watermark_seq") == "7"
    # and it survives re-validation
    validated = _run_cli(tmp_path, "validate-session-journal", "--file", str(journal))
    assert validated.returncode == 0


def test_journal_watermark_monotonic_after_full_eviction(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=40, lane_id=lane_id)])
    _prepare_journal(tmp_path, target)  # watermark 40
    jsonl.write_text("", encoding="utf-8")  # every row evicted, nothing new
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_watermark_seq") == "40"  # carried forward, not reset


def test_journal_first_journal_labeled_all_retained(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=s, lane_id=lane_id) for s in (1, 2)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == "2 (all retained through seq 2)"
    assert _runtime_field(journal, "decisions_report") == \
        "tautline decisions-report --target . --until-seq 2"


def test_journal_subsequent_journal_counts_between_watermarks(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=s, lane_id=lane_id) for s in (1, 2, 3)])
    _prepare_journal(tmp_path, target)  # watermark 3
    _write_lines(jsonl, [_decision(ts=TS_B, seq=s, lane_id=lane_id) for s in (1, 2, 3, 4, 5)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_recorded") == \
        "2 (after seq 3, through seq 5, retained rotations only)"
    assert _runtime_field(journal, "decisions_report") == \
        "tautline decisions-report --target . --since-seq 3 --until-seq 5"


def _mutate_journal(path, *, watermark=None, drop_watermark=False, break_heading=False):
    lines = path.read_text(encoding="utf-8").split("\n")
    out = []
    for line in lines:
        if drop_watermark and line.strip().lstrip("- ").startswith("decisions_watermark_seq:"):
            continue
        wm_line = line.strip().lstrip("- ").startswith("decisions_watermark_seq:")
        if watermark is not None and wm_line:
            out.append(f"- decisions_watermark_seq: {watermark}")
            continue
        if break_heading and line.strip() == "## Work Delivered Or Advanced":
            out.append("## Broken Heading")
            continue
        out.append(line)
    path.write_text("\n".join(out), encoding="utf-8")


def test_journal_failed_prior_preparation_not_trusted(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=15, lane_id=lane_id)])
    _, good = _prepare_journal(tmp_path, target)  # valid predecessor, watermark 15
    # a newer-but-INVALID journal must be ignored during predecessor discovery
    broken = _journal_dir(target) / "29991231T235959Z-session-journal.md"
    broken.write_text(good.read_text(encoding="utf-8"), encoding="utf-8")
    _mutate_journal(broken, watermark=999, break_heading=True)
    _write_lines(jsonl, [_decision(ts=TS_B, seq=16, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_report") == \
        "tautline decisions-report --target . --since-seq 15 --until-seq 16"


def test_journal_same_second_collision_predecessor_order(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=10, lane_id=lane_id)])
    _, base = _prepare_journal(tmp_path, target)
    template = base.read_text(encoding="utf-8")
    # two same-stamp (future) predecessors; the numeric -1 suffix must sort AFTER the base
    p_base = _journal_dir(target) / "29991231T235959Z-session-journal.md"
    p_one = _journal_dir(target) / "29991231T235959Z-session-journal-1.md"
    p_base.write_text(template, encoding="utf-8")
    _mutate_journal(p_base, watermark=10)
    p_one.write_text(template, encoding="utf-8")
    _mutate_journal(p_one, watermark=20)
    _write_lines(jsonl, [_decision(ts=TS_B, seq=25, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    # chained to the -1 suffix (watermark 20), NOT the base (watermark 10)
    assert _runtime_field(journal, "decisions_report") == \
        "tautline decisions-report --target . --since-seq 20 --until-seq 25"


def test_journal_validator_accepts_v1_without_watermark(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    _mutate_journal(journal, drop_watermark=True)  # a retained v1 journal with no watermark line
    validated = _run_cli(tmp_path, "validate-session-journal", "--file", str(journal))
    assert validated.returncode == 0


def test_journal_validator_rejects_malformed_watermark(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    _mutate_journal(journal, watermark="not-an-int")
    validated = _run_cli(tmp_path, "validate-session-journal", "--file", str(journal), check=False)
    assert validated.returncode != 0
    assert "decisions_watermark_seq" in validated.stderr


def test_journal_upserts_into_supplied_runtime_section(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=1, lane_id=lane_id)])
    _, first = _prepare_journal(tmp_path, target)
    reused = first.read_text(encoding="utf-8")  # already carries generated runtime + decision lines
    _write_lines(jsonl, [_decision(ts=TS_B, seq=s, lane_id=lane_id) for s in (1, 2)])
    out = _run_cli(tmp_path, "prepare-session-journal", "--target", str(target),
                   "--stdin", stdin=reused)
    journal = None
    for line in out.stdout.splitlines():
        if line.startswith("session_journal_valid: "):
            journal = Path(line.split(": ", 1)[1])
    assert journal is not None, out.stdout + out.stderr
    text = journal.read_text(encoding="utf-8")
    # exactly one of each field even though the supplied content already had them
    assert text.count("- decisions_recorded:") == 1
    assert text.count("- decisions_report:") == 1
    assert text.count("- decisions_watermark_seq:") == 1
    assert _runtime_field(journal, "decisions_watermark_seq") == "2"


def test_journal_skips_legacy_watermarkless_predecessors(tmp_path):
    target = _prepare_target(tmp_path)
    lane_id, jsonl = _seed(tmp_path, target)
    _write_lines(jsonl, [_decision(ts=TS_A, seq=15, lane_id=lane_id)])
    _, good = _prepare_journal(tmp_path, target)  # valid, watermark 15
    template = good.read_text(encoding="utf-8")
    # a NEWER valid v1 journal with NO watermark must be scanned PAST, not reset the chain
    legacy = _journal_dir(target) / "29991231T235959Z-session-journal.md"
    legacy.write_text(template, encoding="utf-8")
    _mutate_journal(legacy, drop_watermark=True)
    _write_lines(jsonl, [_decision(ts=TS_B, seq=16, lane_id=lane_id)])
    _, journal = _prepare_journal(tmp_path, target)
    assert _runtime_field(journal, "decisions_report") == \
        "tautline decisions-report --target . --since-seq 15 --until-seq 16"


# ---------------------------------------------------------------------------
# Centralized suffix-aware journal discovery (compatibility for existing consumers)
# ---------------------------------------------------------------------------

def test_pending_journals_sees_suffixed_files(cli, tmp_path):
    journal_dir = tmp_path / "runs" / "session-journals"
    journal_dir.mkdir(parents=True)
    base = journal_dir / "20260719T120000Z-session-journal.md"
    suffixed = journal_dir / "20260719T120000Z-session-journal-1.md"
    base.write_text("x", encoding="utf-8")
    suffixed.write_text("x", encoding="utf-8")
    data = {"laneState": {"runsDir": "runs"}}
    pending = cli.pending_session_journals(data, tmp_path)
    assert suffixed in pending and base in pending


def test_leak_scan_sees_suffixed_files(cli, tmp_path, monkeypatch):
    journal_dir = tmp_path / "runs" / "session-journals"
    journal_dir.mkdir(parents=True)
    suffixed = journal_dir / "20260719T120000Z-session-journal-2.md"
    suffixed.write_text("x", encoding="utf-8")
    data = {"laneState": {"runsDir": "runs"}}
    monkeypatch.setattr(cli, "path_is_git_ignored", lambda target, path: False)
    leaked = cli.unignored_committable_session_journals(data, tmp_path)
    assert suffixed in leaked
