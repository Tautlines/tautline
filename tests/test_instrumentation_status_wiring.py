"""T6 (0.9.0 sanitized instrumentation): adapter status wiring.

The instrumentation state prints on lane-start / methodology-status, and the session-journal opt-in
hint now points adopters at sanitized instrumentation (zero product-information capacity) as the
safe way to contribute upstream -- narrative journals can no longer leave the machine.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def test_instrumentation_defaults_disabled_milestone(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw.pop("instrumentation", None)
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(path)
    assert data["instrumentation"] == {"enabled": False, "cadence": "milestone"}


def test_instrumentation_status_line_prints_effective_combination(cli, capsys):
    data = {"instrumentation": {"enabled": True, "cadence": "session"}}
    cli.print_instrumentation_status(data)
    out = capsys.readouterr().out
    assert "instrumentation: enabled=true cadence=session" in out


def test_instrumentation_status_line_defaults_when_key_absent(cli, capsys):
    cli.print_instrumentation_status({})
    out = capsys.readouterr().out
    assert "instrumentation: enabled=false cadence=milestone" in out


def test_optin_hint_points_at_instrumentation_not_journal_remote(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw.pop("sessionJournal", None)
    silent = tmp_path / "adapter.json"
    silent.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(silent)
    hint = cli.session_journal_optin_hint(data, silent, tmp_path)
    assert "session_journal_optin:" in hint
    # The hint must NOT advertise publishing narrative journals to a remote branch anymore.
    assert "journal branch" not in hint
    # It steers adopters to the sanitized instrumentation record.
    assert "instrumentation" in hint
    assert "publish-instrumentation-record" in hint
    assert "docs/reference/instrumentation.md" in hint


def _render_adapter_for(cli, tmp_path, *, enabled: bool) -> str:
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": enabled, "cadence": "milestone"}
    if enabled:
        raw["observabilityEvents"] = {**raw.get("observabilityEvents", {}), "enabled": True}
    path = tmp_path / f"adapter-{enabled}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = cli.load_project(path)
    return cli.render_adapter(data, "claude", str(path))


def test_rendered_instrumentation_guidance_gates_publish_command_on_enabled(cli, tmp_path):
    # A default/disabled lane must NOT be instructed to run publish-instrumentation-record -- it
    # refuses while disabled, so unconditional "contribute upstream" guidance sends default lanes into
    # the refusal. Only an enabled lane gets the contribute-at-the-boundary imperative.
    disabled = _render_adapter_for(cli, tmp_path, enabled=False)
    assert "Instrumentation (`false`)" in disabled
    assert "disabled here" in disabled
    assert "contribute upstream" not in disabled

    enabled = _render_adapter_for(cli, tmp_path, enabled=True)
    assert "Instrumentation (`true`" in enabled
    assert "contribute upstream" in enabled
    assert "publish-instrumentation-record" in enabled


def test_rendered_instrumentation_guidance_cadence_off_is_manual_not_boundary(cli):
    # cadence "off" means manual publishing with no boundary prompt; generated guidance must not tell
    # agents to publish "at the off boundary".
    line = cli.instrumentation_guidance_line({"enabled": True, "cadence": "off"})
    assert "publish MANUALLY" in line and "no boundary prompting" in line
    assert "boundary with" not in line
    milestone = cli.instrumentation_guidance_line({"enabled": True, "cadence": "milestone"})
    assert "at the `milestone` boundary" in milestone


def test_instrumentation_enabled_requires_observability(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": True}
    raw["observabilityEvents"] = {**raw.get("observabilityEvents", {}), "enabled": False}
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        cli.load_project(path)
    except SystemExit as exc:
        assert "observabilityEvents.enabled" in str(exc)
    else:
        raise AssertionError("expected a configuration-coherence SystemExit")


def test_instrumentation_rejects_unknown_subkey(cli, tmp_path):
    raw = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    raw["instrumentation"] = {"enabled": True, "branch": "custom-telemetry"}
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        cli.load_project(path)
    except SystemExit as exc:
        assert "branch" in str(exc)
    else:
        raise AssertionError("expected a hard validation error for unknown instrumentation subkey")
