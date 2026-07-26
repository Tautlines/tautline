"""`decision-record`: the fail-closed, machine-local structured decision ledger writer the standing
autonomy directive instructs agents to use.

The verb composes the existing `build_event_payload` + `append_event_payload` event primitives
(same events.jsonl, locking, in-lock lane_id/seq stamping) with a keyword-only
`bypass_enabled_gate` on the append primitive so the ledger works on disabled-narration lanes
without weakening ordinary producers. Every non-empty stored field is sanitized + validated before
append; records carry a TOP-LEVEL `record_kind = "tautline-decision/v1"` discriminator (NOT a
reserved `--ref` key -- the final R4 design replaced the reserved-key approach with a top-level
discriminator, closing the forgery path with zero compatibility cost to the stable
`log-event`/`usage-record` ref namespace).

Black-box subprocess runs use a hermetic HOME (mirroring validate.sh isolation) so the telemetry
salt + per-lane seq/lane_id allocator state under $HOME/.local/state never touches the real machine.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
# Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a thin
# shim. Static source assertions scan the engine module; CLI_PATH stays the subprocess entrypoint.
CLI_ENGINE_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
STATE_DIR = "$HOME/.local/state/tautline-test/decision-events"
SECRET_LIKE = "ghp_1234567890abcdef1234567890abcdef123456"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _run_cli(tmp_path, *args, check=True, timeout=60):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _dr(tmp_path, target, *extra, summary="s", rationale="r", check=True):
    """Compact decision-record runner; summary/rationale default to valid non-blank values."""
    return _run_cli(
        tmp_path, "decision-record", "--target", str(target),
        "--summary", summary, "--rationale", rationale, *extra, check=check,
    )


def _write_event_adapter(target: Path, *, enabled: bool = True) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": STATE_DIR,
        "enabled": enabled,
    }
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for decision-record ledger behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path, *, enabled: bool = True, name: str = "decision-target"):
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
    adapter = _write_event_adapter(target, enabled=enabled)
    _run_cli(
        tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write"
    )
    return target, adapter


def _write_goal_run(target: Path, *, goal_id: str) -> None:
    """Minimal valid active goal-run ledger so build_event_payload derives a `goal` from context."""
    ledger = {
        "schema": "minervit-goal-run/v1",
        "createdAt": "2026-07-19T00:00:00+00:00",
        "updatedAt": "2026-07-19T00:00:00+00:00",
        "project": "example-saas",
        "repo": "example-org/example-saas",
        "goalId": goal_id,
        "sourceGoal": "docs/goal.md",
        "milestones": [],
    }
    path = target / ".ai-work" / "GOAL_RUN.json"
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_milestone_run(target: Path, *, milestone_id: str) -> None:
    ledger = {
        "schema": "minervit-milestone-run/v1",
        "createdAt": "2026-07-19T00:00:00+00:00",
        "updatedAt": "2026-07-19T00:00:00+00:00",
        "project": "example-saas",
        "repo": "example-org/example-saas",
        "milestoneId": milestone_id,
        "sourcePlan": "docs/plan.md",
        "tasks": [],
    }
    path = target / ".ai-work" / "MILESTONE_RUN.json"
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonl_path(tmp_path, target) -> Path:
    out = _run_cli(tmp_path, "event-log-path", "--target", str(target))
    for line in out.stdout.splitlines():
        if line.startswith("event_jsonl: "):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"event_jsonl missing from output:\n{out.stdout}")


def _records(tmp_path, target) -> list[dict]:
    path = _jsonl_path(tmp_path, target)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Happy path + record shape
# ---------------------------------------------------------------------------

RATIONALE = "Reserving a ref key broke a stable CLI input; a discriminator does not"


def test_decision_record_writes_decision_event(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target, summary="Chose top-level record_kind", rationale=RATIONALE)
    records = _records(tmp_path, target)
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "decision"
    assert rec["plain"] == "Chose top-level record_kind"
    assert rec["refs"]["rationale"] == RATIONALE
    assert rec["refs"]["reversibility"] == "reversible"
    assert rec["next"] == "proceed as decided"
    assert rec["methodology"]["plugin_version"]


def test_decision_record_writes_decision_schema_marker(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target)
    rec = _records(tmp_path, target)[0]
    assert rec["record_kind"] == "tautline-decision/v1"


def test_decision_record_severity_is_info(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target)
    assert _records(tmp_path, target)[0]["severity"] == "info"


def test_decision_record_stamps_lane_id_and_seq(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target)
    rec = _records(tmp_path, target)[0]
    assert isinstance(rec["lane_id"], str) and len(rec["lane_id"]) == 16
    assert isinstance(rec["seq"], int)


def test_decision_record_defaults_reversible_and_next(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target)
    rec = _records(tmp_path, target)[0]
    assert rec["refs"]["reversibility"] == "reversible"
    assert rec["next"] == "proceed as decided"


def test_decision_record_omits_blank_alternatives_and_surfaces(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(tmp_path, target)
    refs = _records(tmp_path, target)[0]["refs"]
    assert "alternatives" not in refs
    assert "surfaces" not in refs


def test_decision_record_records_alternatives_and_surfaces_when_given(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _dr(
        tmp_path, target,
        "--alternatives", "considered a reserved ref key",
        "--reversibility", "hard-to-reverse",
        "--surface", "bin/tautline", "--surface", "tests",
    )
    refs = _records(tmp_path, target)[0]["refs"]
    assert refs["alternatives"] == "considered a reserved ref key"
    assert refs["reversibility"] == "hard-to-reverse"
    assert refs["surfaces"] == "bin/tautline,tests"


def test_decision_record_succeeds_with_no_goal_context(tmp_path):
    # The DEFAULT invocation: no --goal/--milestone flags and no active goal/milestone ledgers.
    # build_event_payload legitimately stores empty strings for goal/milestone here; the empty
    # derived finals must NOT trip the non-empty validation.
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target)
    assert out.returncode == 0
    rec = _records(tmp_path, target)[0]
    assert rec["goal"] == ""
    assert rec["milestone"] == ""


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------

def test_decision_record_requires_summary(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _run_cli(
        tmp_path, "decision-record", "--target", str(target), "--rationale", "r", check=False
    )
    assert out.returncode != 0
    assert "--summary" in out.stderr  # intended required-arg error, not an unknown-command error
    assert not _records(tmp_path, target)


def test_decision_record_requires_rationale(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _run_cli(
        tmp_path, "decision-record", "--target", str(target), "--summary", "s", check=False
    )
    assert out.returncode != 0
    assert "--rationale" in out.stderr  # intended required-arg error, not an unknown-command error
    assert not _records(tmp_path, target)


def test_decision_record_blank_rationale_fails_closed(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, rationale="   ", check=False)
    assert out.returncode != 0
    assert "non-blank" in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_rejects_bad_reversibility(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, "--reversibility", "maybe", check=False)
    assert out.returncode != 0
    assert "--reversibility" in out.stderr and "invalid choice" in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_secretlike_rationale_fails_closed(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, rationale=f"api key {SECRET_LIKE}", check=False)
    assert out.returncode != 0
    assert "secret-looking value" in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_surfaces_joined_cap_enforced(tmp_path):
    target, _ = _prepare_target(tmp_path)
    # Each surface item is under the 1000-char cap, but the JOINED surfaces string is over it.
    surface_args = []
    for _ in range(4):
        surface_args += ["--surface", "x" * 300]
    out = _dr(tmp_path, target, *surface_args, check=False)
    assert out.returncode != 0
    assert "exceeds 1000 characters" in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_nonempty_goal_and_pr_validated(tmp_path):
    target, _ = _prepare_target(tmp_path)
    secret_goal = _dr(tmp_path, target, "--goal", f"g {SECRET_LIKE}", check=False)
    assert secret_goal.returncode != 0
    assert "secret-looking value" in secret_goal.stderr
    assert not _records(tmp_path, target)
    long_pr = _dr(tmp_path, target, "--pr", "p" * 1001, check=False)
    assert long_pr.returncode != 0
    assert "exceeds 1000 characters" in long_pr.stderr
    assert not _records(tmp_path, target)


@pytest.mark.parametrize("field", ["goal", "milestone", "pr"])
@pytest.mark.parametrize(
    "bad,needle",
    [(SECRET_LIKE, "secret-looking value"), ("z" * 1001, "exceeds 1000 characters")],
)
def test_decision_record_explicit_fields_validated_parameterized(tmp_path, field, bad, needle):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, f"--{field}", bad, check=False)
    assert out.returncode != 0, f"{field}={bad!r} should be rejected"
    assert needle in out.stderr
    assert not _records(tmp_path, target)


# over-cap --rationale is an author-ref path (rationale lives in refs, not plain).
def test_decision_record_overcap_rationale_rejected(tmp_path):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, rationale="r" * 1001, check=False)
    assert out.returncode != 0
    assert "exceeds 1000 characters" in out.stderr
    assert not _records(tmp_path, target)


@pytest.mark.parametrize("flag,value,needle", [
    ("--alternatives", SECRET_LIKE, "secret-looking value"),
    ("--alternatives", "a" * 1001, "exceeds 1000 characters"),
    ("--surface", SECRET_LIKE, "secret-looking value"),
    ("--next", SECRET_LIKE, "secret-looking value"),
    ("--next", "n" * 1001, "exceeds 1000 characters"),
])
def test_decision_record_author_refs_validated_parameterized(tmp_path, flag, value, needle):
    target, _ = _prepare_target(tmp_path)
    out = _dr(tmp_path, target, flag, value, check=False)
    assert out.returncode != 0, f"{flag}={value!r} should be rejected"
    assert needle in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_ref_values_sanitized(tmp_path):
    target, _ = _prepare_target(tmp_path)
    home = str(tmp_path / "home")
    _dr(tmp_path, target, rationale=f"path {home}/secret is\nflattened")
    rationale = _records(tmp_path, target)[0]["refs"]["rationale"]
    assert home not in rationale
    assert "$HOME" in rationale
    assert "\n" not in rationale


# ---------------------------------------------------------------------------
# Derived (state-sourced) goal/milestone are validated too
# ---------------------------------------------------------------------------

def test_decision_record_derived_goal_validated_when_nonempty(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _write_goal_run(target, goal_id=f"goal {SECRET_LIKE}")
    out = _dr(tmp_path, target, check=False)
    assert out.returncode != 0
    assert "secret-looking value" in out.stderr
    assert not _records(tmp_path, target)


def test_decision_record_derived_milestone_validated_when_nonempty(tmp_path):
    target, _ = _prepare_target(tmp_path)
    _write_milestone_run(target, milestone_id="m" * 1001)
    out = _dr(tmp_path, target, check=False)
    assert out.returncode != 0
    assert "exceeds 1000 characters" in out.stderr
    assert not _records(tmp_path, target)


# ---------------------------------------------------------------------------
# Escape hatch: works when narration disabled, without weakening ordinary producers
# ---------------------------------------------------------------------------

def test_decision_record_works_with_events_disabled(tmp_path):
    target, _ = _prepare_target(tmp_path, enabled=False)
    out = _dr(tmp_path, target)
    assert out.returncode == 0
    records = _records(tmp_path, target)
    assert len(records) == 1
    assert records[0]["record_kind"] == "tautline-decision/v1"


def test_log_event_still_refused_when_events_disabled(tmp_path):
    target, _ = _prepare_target(tmp_path, enabled=False)
    out = _run_cli(
        tmp_path, "log-event", "--target", str(target), "--event", "startup",
        "--severity", "info", "--plain", "p", "--next", "n",
    )
    assert "event_log_skipped: disabled" in out.stdout
    assert not _records(tmp_path, target)


def test_append_primitive_still_refuses_when_disabled_without_bypass(cli, tmp_path):
    # Direct primitive invocation: the verb-level tests short-circuit before the primitive and could
    # not catch an accidentally flipped default. The disabled-check fires before any file access.
    data = {"observabilityEvents": {"enabled": False}}
    lane = tmp_path / "lane"
    lane.mkdir()
    with pytest.raises(SystemExit):
        cli.append_event_payload(data, lane, {"ts": "2026-07-19T00:00:00+00:00"})
    assert not list(lane.rglob("events.jsonl"))


# ---------------------------------------------------------------------------
# Reader contract: top-level discriminator, no reserved --ref namespace break
# ---------------------------------------------------------------------------

def test_log_event_decision_schema_ref_still_accepted_and_not_counted_shape(tmp_path):
    # The final design reserves NOTHING in the --ref namespace: a log-event carrying a
    # decision_schema ref is still accepted as an ordinary ref, and is NOT a decision record
    # (no top-level record_kind), so a reader keying on record_kind never miscounts it.
    target, _ = _prepare_target(tmp_path)
    _run_cli(
        tmp_path, "log-event", "--target", str(target), "--event", "startup",
        "--severity", "info", "--plain", "p", "--next", "n",
        "--ref", "decision_schema=tautline-decision/v1",
    )
    rec = _records(tmp_path, target)[0]
    assert rec["refs"]["decision_schema"] == "tautline-decision/v1"
    assert "record_kind" not in rec


def test_freeform_log_event_cannot_set_record_kind(tmp_path):
    # log-event refs pass through event_refs_from_args into payload["refs"] ONLY; they can never set
    # a top-level payload key, so the forgery path is structurally closed with no reserved key.
    target, _ = _prepare_target(tmp_path)
    _run_cli(
        tmp_path, "log-event", "--target", str(target), "--event", "startup",
        "--severity", "info", "--plain", "p", "--next", "n",
        "--ref", "record_kind=tautline-decision/v1",
    )
    rec = _records(tmp_path, target)[0]
    assert rec.get("record_kind") != "tautline-decision/v1"
    assert rec["refs"]["record_kind"] == "tautline-decision/v1"


# ---------------------------------------------------------------------------
# Instrumentation classification + sole-callsite source invariant
# ---------------------------------------------------------------------------

def test_decision_event_classified_ignored_for_instrumentation(cli):
    assert "decision" in cli.INSTRUMENTATION_IGNORED_EVENTS
    assert cli.INSTRUMENTATION_IGNORED_EVENTS["decision"].strip()


def test_bypass_gate_sole_callsite():
    # Static source assertion: exactly ONE call site passes bypass_enabled_gate=True, and it is
    # inside decision_record. Another producer enabling the bypass fails this even if behavioral
    # tests stay green.
    source = CLI_ENGINE_PATH.read_text(encoding="utf-8")
    lines = source.splitlines()
    hits = [i for i, line in enumerate(lines) if "bypass_enabled_gate=True" in line]
    assert len(hits) == 1, f"expected exactly 1 bypass_enabled_gate=True call site, got {len(hits)}"
    enclosing = None
    for i in range(hits[0], -1, -1):
        if lines[i].startswith("def "):
            enclosing = lines[i]
            break
    assert enclosing is not None and enclosing.startswith("def decision_record("), (
        f"sole bypass_enabled_gate=True call site must be inside decision_record, got: {enclosing}"
    )
