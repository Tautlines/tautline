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


def test_estimate_source_high_percent_is_advisory_not_mandatory(cli):
    out = cli.context_rotation_decision(_rotation(), 88, True, "estimate")
    assert out["urgency"] == "recommended"
    assert out["action"] == "rotate-now"
    assert out["capped"] is True
    assert out["source"] == "estimate"


def test_host_source_high_percent_still_mandatory(cli):
    safe = cli.context_rotation_decision(_rotation(), 88, True, "host")
    assert safe["urgency"] == "mandatory"
    assert safe["action"] == "rotate-now"
    assert safe["capped"] is False
    unsafe = cli.context_rotation_decision(_rotation(), 88, False, "host")
    assert unsafe["urgency"] == "mandatory"
    assert unsafe["action"] == "rotate-mandatory-at-next-safe-boundary"
    assert unsafe["capped"] is False


def test_no_source_high_percent_capped_default_estimate(cli):
    out = cli.context_rotation_decision(_rotation(), 88, True, None)
    assert out["urgency"] == "recommended"
    assert out["capped"] is True
    assert out["source"] == "estimate"


def test_none_percent_unchanged_regardless_of_source(cli):
    for source in (None, "host", "estimate"):
        out = cli.context_rotation_decision(_rotation(), None, True, source)
        assert out["action"] == "check-visible-context"
        assert out["urgency"] == "unknown"
        assert out["capped"] is False
        assert out["source"] == "none"


def test_soft_band_unchanged_by_source(cli):
    for source in (None, "host", "estimate"):
        out = cli.context_rotation_decision(_rotation(), 63, True, source)
        assert out["urgency"] == "recommended"
        assert out["capped"] is False


def test_disabled_rotation_ignores_source(cli):
    out = cli.context_rotation_decision(_rotation(enabled=False), 88, True, "estimate")
    assert out["action"] == "continue"
    assert out["urgency"] == "disabled"
    assert out["capped"] is False


def test_below_soft_unchanged(cli):
    out = cli.context_rotation_decision(_rotation(), 40, True, "estimate")
    assert out["action"] == "continue"
    assert out["urgency"] == "none"
    assert out["capped"] is False


# --- D1 CLI black-box: --context-percent-source ------------------------------------------------


def _ctx_args(*args):
    return ("context-rotation-check", "--project", str(ADAPTER), "--boundary", "pr-queued", *args)


def test_cli_estimate_88_emits_capped_advisory(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "88", "--context-percent-source", "estimate"))
    assert res.returncode == 0, res.stderr
    assert "context_rotation_urgency: recommended" in res.stdout
    assert "context_rotation_capped: true" in res.stdout
    assert "context_rotation_percent_source: estimate" in res.stdout


def test_cli_host_88_still_mandatory(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "88", "--context-percent-source", "host"))
    assert res.returncode == 0, res.stderr
    assert "context_rotation_urgency: mandatory" in res.stdout
    assert "context_rotation_capped: false" in res.stdout
    assert "context_rotation_percent_source: host" in res.stdout


def test_cli_no_source_88_capped(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "88"))
    assert res.returncode == 0, res.stderr
    assert "context_rotation_urgency: recommended" in res.stdout
    assert "context_rotation_capped: true" in res.stdout
    assert "context_rotation_percent_source: estimate" in res.stdout


def test_cli_bad_source_value_exits_2(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "80", "--context-percent-source", "measured"))
    assert res.returncode == 2


def test_none_percent_reason_states_advisory_only(run_cli, tmp_path):
    res = run_cli("context-rotation-check", "--project", str(ADAPTER), "--target", str(tmp_path), "--boundary", "pr-queued")
    assert res.returncode == 0, res.stderr
    assert "context_rotation_percent_source: none" in res.stdout
    assert "context_rotation_capped: false" in res.stdout
    assert "advisory only and is never a mandatory-rotation trigger" in res.stdout


# --- D1 FIX-4: advisory vs mandatory host-fallback wording -------------------------------------

_MANDATORY_FALLBACK = "this is a mandatory \ncontext rotation boundary".replace("\n", "")
_ADVISORY_FALLBACK = "context_rotation_host_fallback: this is an advisory rotation, not a mandatory boundary"


def test_host_88_prints_mandatory_host_fallback(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "88", "--context-percent-source", "host"))
    assert res.returncode == 0, res.stderr
    assert "context_rotation_host_fallback: if this agent turn cannot invoke" in res.stdout
    assert "this is a mandatory" in res.stdout
    assert _ADVISORY_FALLBACK not in res.stdout


def test_soft_63_prints_advisory_host_fallback(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "63"))
    assert res.returncode == 0, res.stderr
    assert _ADVISORY_FALLBACK in res.stdout
    assert "if this agent turn cannot invoke" not in res.stdout


def test_estimate_88_safe_prints_advisory_not_mandatory(run_cli, tmp_path):
    res = run_cli(*_ctx_args("--target", str(tmp_path), "--context-percent", "88", "--context-percent-source", "estimate"))
    assert res.returncode == 0, res.stderr
    assert _ADVISORY_FALLBACK in res.stdout
    assert _MANDATORY_FALLBACK not in res.stdout


def test_estimate_88_unsafe_capped_branch_is_advisory(run_cli, tmp_path):
    # UNSAFE boundary + capped estimate: rotate-at-next-safe-boundary, recommended, capped, advisory
    # wording -- never the mandatory variant.
    res = run_cli(
        "context-rotation-check",
        "--project",
        str(ADAPTER),
        "--target",
        str(tmp_path),
        "--boundary",
        "implementation-edit",
        "--context-percent",
        "88",
        "--context-percent-source",
        "estimate",
    )
    assert res.returncode == 0, res.stderr
    assert "context_rotation_safe_boundary: false" in res.stdout
    assert "context_rotation_action: rotate-at-next-safe-boundary" in res.stdout
    assert "context_rotation_urgency: recommended" in res.stdout
    assert "context_rotation_capped: true" in res.stdout
    assert _ADVISORY_FALLBACK in res.stdout
    assert _MANDATORY_FALLBACK not in res.stdout
