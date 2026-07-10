"""D2 (0.6.113): the goal-heartbeat hook must forbid rotating/stopping on a self-estimated
percentage and still preserve the continuity/journal + /compact rotation tail (no doubled "then").
"""

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "generated-adapter-example-saas.json"


def _heartbeat_context(run_cli, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / ".minervit-ai-delivery.json").write_text(FIXTURE.read_text())
    (lane / ".ai-work").mkdir(parents=True, exist_ok=True)
    (lane / ".ai-work" / "GOAL_RUN.json").write_text(
        json.dumps({"goalId": "g1", "sourceGoal": "plan.md"})
    )
    payload = json.dumps({"hook_event_name": "PostToolUse", "cwd": str(lane)})
    res = run_cli("context-rotation-heartbeat-hook", stdin=payload)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"]


def test_heartbeat_forbids_self_estimate_and_preserves_tail(run_cli, tmp_path):
    ctx = _heartbeat_context(run_cli, tmp_path)
    assert "do not rotate or stop on a self-estimated or guessed percentage" in ctx
    # Nit: replace the tautological "then then" / ", then  refresh" checks (impossible against a
    # single string literal) with a REAL render check that the advisory-only clause AND the
    # /compact rotation tail are both present in the rendered hook context.
    assert "an unmeasured context guess is advisory only" in ctx
    assert "refresh continuity/session journal, invoke `/compact`" in ctx


def test_heartbeat_mandatory_clause_is_host_qualified(run_cli, tmp_path):
    # D2 FIX-5: the "this is mandatory at the next safe boundary" clause must qualify mandatory as
    # host-sourced, so an estimate at/above hard is not read as mandatory.
    ctx = _heartbeat_context(run_cli, tmp_path)
    assert "with a host-sourced percent this is mandatory at the next safe boundary" in ctx
    assert "an estimate stays advisory" in ctx
    # The bare unqualified mandatory clause must be gone.
    assert "% this is mandatory at the next safe boundary. If the host" not in ctx


def test_heartbeat_emits_source_flag_guidance(run_cli, tmp_path):
    ctx = _heartbeat_context(run_cli, tmp_path)
    assert "--context-percent-source estimate" in ctx
    assert "Pass --context-percent-source host only if the host literally exposes" in ctx
