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


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


# over-cap --rationale is an author-ref path (rationale lives in refs, not plain).


# ---------------------------------------------------------------------------
# Derived (state-sourced) goal/milestone are validated too
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Escape hatch: works when narration disabled, without weakening ordinary producers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Instrumentation classification + sole-callsite source invariant
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lean lanes: the ledger writer the autonomy directive names must work on lean-1 adapters
# ---------------------------------------------------------------------------


def _prepare_lean_target(tmp_path, *, name="lean-target", remote="git@github.com:example-org/example-saas.git"):
    """A lean-1 lane shaped exactly like `tautline slim`/`tautline init` output: a git repo whose
    only adapter is a minimal lean `.tautline.json` -- no source adapter, no `_generated` chain."""
    target = tmp_path / name
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    if remote:
        _git(target, "remote", "add", "origin", remote)
    lean_config = {
        "schemaVersion": "lean-1",
        "project": {"name": "Example SaaS", "repo": "example-org/example-saas"},
        "integrationBranch": "main",
        "commands": {"test": "true"},
    }
    (target / ".tautline.json").write_text(
        json.dumps(lean_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "Initial fixture", "-q")
    return target


def _read_ledger_record(result) -> dict:
    jsonl_line = next(
        line for line in result.stdout.splitlines() if line.startswith("event_jsonl: ")
    )
    ledger = Path(jsonl_line.removeprefix("event_jsonl: "))
    assert ledger.exists(), f"ledger file missing: {ledger}"
    rows = [json.loads(row) for row in ledger.read_text(encoding="utf-8").splitlines() if row]
    assert rows, "ledger is empty"
    return rows[-1]


def test_lean_adapter_lane_records_a_decision(tmp_path):
    target = _prepare_lean_target(tmp_path)
    result = _dr(tmp_path, target, rationale=RATIONALE)
    record = _read_ledger_record(result)
    assert record["record_kind"] == "tautline-decision/v1"
    assert record["refs"]["rationale"] == RATIONALE
    assert record["project"] == "Example SaaS"
    assert record["repo"] == "example-org/example-saas"


def test_lean_adapter_without_remote_still_records(tmp_path):
    # `tautline init` legitimately produces a lean lane before any remote exists; refusing to
    # record a decision there would gut the autonomy directive exactly where it starts.
    target = _prepare_lean_target(tmp_path, remote=None)
    result = _dr(tmp_path, target, rationale=RATIONALE)
    record = _read_ledger_record(result)
    assert record["record_kind"] == "tautline-decision/v1"


def test_lean_adapter_wrong_repo_still_refuses(tmp_path):
    # The lean path keeps the one 1.x identity check that CAN still run: a lean adapter naming a
    # different repo than the target's remote is another project's adapter, and stays refused.
    target = _prepare_lean_target(tmp_path, remote="git@github.com:example-org/other-repo.git")
    result = _dr(tmp_path, target, rationale=RATIONALE, check=False)
    assert result.returncode != 0
    assert "does not match the target git remote" in result.stderr


def test_malformed_lean_adapter_refuses_cleanly(tmp_path):
    # `load_lean_config` only sniffs schemaVersion, so a marker that claims lean-1 but breaks the
    # schema (project as a bare string) must die as a clean one-line refusal from the
    # authoritative validator -- never an AttributeError traceback out of legacy_lane_view.
    target = _prepare_lean_target(tmp_path)
    (target / ".tautline.json").write_text(
        json.dumps({"schemaVersion": "lean-1", "project": "just-a-string", "commands": {"test": "true"}})
        + "\n",
        encoding="utf-8",
    )
    result = _dr(tmp_path, target, rationale=RATIONALE, check=False)
    assert result.returncode != 0
    assert "lean adapter invalid" in result.stderr
    assert "Traceback" not in result.stderr
