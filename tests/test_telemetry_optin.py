"""MISSING-telemetry (productization): opt-in, local-first, anonymized gate telemetry. Default OFF
(zero outbound, zero recording). When opted in, records ONLY gate id + outcome + coarse numeric
fields + timestamp -- never code, prompts, paths, or secrets -- to a local JSONL the user controls.
"""

import json


def test_default_off_records_nothing(cli, tmp_path, monkeypatch):
    monkeypatch.delenv("MINERVIT_METHODOLOGY_TELEMETRY", raising=False)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY_PATH", str(tmp_path / "t.jsonl"))
    assert cli.telemetry_enabled() is False
    cli.record_gate_telemetry("response-guard-stop", "block", error_count=3)
    assert not (tmp_path / "t.jsonl").exists()


def test_opt_in_records_anonymized_event(cli, tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY", "1")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY_PATH", str(log))
    assert cli.telemetry_enabled() is True
    cli.record_gate_telemetry("response-guard-stop", "block", error_count=2)
    rec = json.loads(log.read_text().splitlines()[-1])
    assert rec["gate"] == "response-guard-stop"
    assert rec["outcome"] == "block"
    assert rec["error_count"] == 2
    # anonymized: only the known coarse keys, nothing else
    assert set(rec) <= {"ts", "gate", "outcome", "error_count"}


def test_non_numeric_fields_are_dropped(cli, tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY", "1")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY_PATH", str(log))
    # a caller must never be able to smuggle content (paths/prompts) into telemetry
    cli.record_gate_telemetry("g", "block", secret_path="/home/u/secret.py", error_count=1)
    rec = json.loads(log.read_text().splitlines()[-1])
    assert "secret_path" not in rec
    assert rec["error_count"] == 1


def test_telemetry_show_runs_and_reports_disabled(run_cli):
    # Hermetic HOME, no opt-in env -> default path, disabled, zero records.
    res = run_cli("telemetry", "--show")
    assert res.returncode == 0, res.stderr
    assert "telemetry_enabled: False" in res.stdout
    assert "telemetry_records: 0" in res.stdout


def test_telemetry_clear_is_safe_when_empty(run_cli):
    res = run_cli("telemetry", "--clear")
    assert res.returncode == 0, res.stderr
    assert "telemetry_cleared" in res.stdout
