"""MISSING-efficacy (productization): pilot-report gives an external-validity pilot real
instrumentation -- it aggregates the opt-in gate telemetry into per-gate fire counts (a false-block
proxy) that a non-author can interpret alongside did-it-ship/time-to-lane.
"""

import json


def test_pilot_report_aggregates_gate_counts(cli, tmp_path, monkeypatch, capsys):
    log = tmp_path / "telemetry.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"gate": "response-guard-stop", "outcome": "block"},
                {"gate": "response-guard-stop", "outcome": "block"},
                {"gate": "latest-code", "outcome": "block"},
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(cli, "telemetry_path", lambda: log)
    import argparse

    rc = cli.pilot_report(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "pilot_report_total_events: 3" in out
    assert "response-guard-stop:block = 2" in out
    assert "latest-code:block = 1" in out


def test_pilot_report_handles_missing_log(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "telemetry_path", lambda: tmp_path / "none.jsonl")
    import argparse

    rc = cli.pilot_report(argparse.Namespace())
    assert rc == 0
    assert "pilot_report_total_events: 0" in capsys.readouterr().out
