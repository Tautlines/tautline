"""D1 (0.6.113): context-percent provenance cap on context-rotation-check.

RCA 20260615T181937Z: an agent fabricated an 88% context-percent (the host exposes no
counter), passed it to context-rotation-check, got rotate-mandatory, and used it to stop
authorized work. Root cause: no provenance distinction -- a self-estimated number was treated
exactly like a host-measured one. Fix: a pure helper context_rotation_decision(...) that caps a
non-host-sourced percent at advisory (recommended) and can never emit 'mandatory'. The no-source
default is ESTIMATE (advisory cap); a real host opts back into measured behavior with
--context-percent-source host.
"""

from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "projects" / "example-saas.json"
ROTATION = {
    "enabled": True,
    "softPercent": 60,
    "hardPercent": 75,
    "heartbeatMinutes": 15,
    "heartbeatBoundary": "goal-heartbeat",
    "safeBoundaries": ["pr-queued", "milestone-complete"],
}


def _rotation(**overrides):
    rot = dict(ROTATION)
    rot.update(overrides)
    return rot


# --- D1 pure helper: context_rotation_decision -------------------------------------------------


# --- D1 CLI black-box: --context-percent-source ------------------------------------------------


def _ctx_args(*args):
    return ("context-rotation-check", "--project", str(ADAPTER), "--boundary", "pr-queued", *args)


def test_cli_bad_source_value_exits_2(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "80", "--context-percent-source", "measured"))
    assert res.returncode == 2


# --- D1 FIX-4: advisory vs mandatory host-fallback wording -------------------------------------

_MANDATORY_FALLBACK = "this is a mandatory \ncontext rotation boundary".replace("\n", "")
_ADVISORY_FALLBACK = "context_rotation_host_fallback: this is an advisory rotation, not a mandatory boundary"
