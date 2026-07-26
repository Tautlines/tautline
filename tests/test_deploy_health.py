import argparse
import json
from datetime import datetime, timedelta, timezone

import pytest

from tautline_methodology import deploy


def _cfg(cli, **overrides):
    raw = {
        "enabled": True,
        "workflow": "deploy-makerkit-dev.yml",
        "branch": "main",
        "maxConsecutiveFailures": 3,
        "maxSuccessAgeHours": 72,
    }
    raw.update(overrides)
    return cli.normalize_deploy_health_config(raw, 0)


def _run(conclusion, hours_ago, *, status="completed", run_id=1):
    stamp = (datetime(2026, 6, 27, 21, 0, tzinfo=timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "databaseId": run_id,
        "status": status,
        "conclusion": conclusion,
        "createdAt": stamp,
        "updatedAt": stamp,
        "url": f"https://github.example/runs/{run_id}",
        "displayTitle": f"deploy {run_id}",
    }


def test_deploy_health_helpers_are_served_from_package_through_cli_wrapper(cli):
    cfg = _cfg(cli, failOnLatestFailure=False)
    runs = [_run("failure", 1, run_id=2), _run("success", 3, run_id=1)]
    now = datetime(2026, 6, 27, 21, 0, tzinfo=timezone.utc)
    data = {"deploymentTargets": [{"name": "dev", "deployHealth": cfg}, {"name": "disabled", "deployHealth": {"enabled": False}}]}

    assert cli.normalize_deploy_health_config({"workflow": "deploy.yml"}, 0) == deploy.normalize_deploy_health_config(
        {"workflow": "deploy.yml"},
        0,
        cli.DEFAULT_DEPLOY_HEALTH,
    )
    assert cli.deploy_health_configured_targets(data) == deploy.deploy_health_configured_targets(data)
    assert cli.deploy_health_parse_time("2026-06-27T21:00:00Z") == deploy.deploy_health_parse_time(
        "2026-06-27T21:00:00Z"
    )
    assert cli.deploy_health_sorted_runs(runs) == deploy.deploy_health_sorted_runs(runs)
    assert cli.deploy_health_completed_runs(runs) == deploy.deploy_health_completed_runs(runs)
    assert cli.deploy_health_run_label(runs[0]) == deploy.deploy_health_run_label(runs[0])
    assert cli.deploy_health_issues_for_runs("dev", cfg, runs, now=now) == deploy.deploy_health_issues_for_runs(
        "dev",
        cfg,
        runs,
        defaults=cli.DEFAULT_DEPLOY_HEALTH,
        failure_conclusions=cli.DEPLOY_HEALTH_FAILURE_CONCLUSIONS,
        now=now,
    )


def test_deploy_health_io_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path, monkeypatch):
    cfg = _cfg(cli)
    runs = [_run("success", 1)]
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps({"deploy-makerkit-dev.yml": runs}), encoding="utf-8")

    assert cli.deploy_health_runs_from_file(runs_file, cfg) == runs
    assert deploy.deploy_health_runs_from_file(runs_file, cfg) == runs

    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append((command, cwd, timeout))
        return 0, json.dumps(runs), ""

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.deploy_health_github_actions_runs(tmp_path, cfg) == deploy.deploy_health_github_actions_runs(
        tmp_path,
        cfg,
        command_runner=fake_run_command,
    )
    expected_command = [
        "gh",
        "run",
        "list",
        "--workflow",
        "deploy-makerkit-dev.yml",
        "--branch",
        "main",
        "--limit",
        "25",
        "--json",
        "databaseId,conclusion,status,createdAt,updatedAt,headSha,url,displayTitle,workflowName",
    ]
    assert calls[0] == (expected_command, tmp_path, 45)


def test_deploy_health_issues_preserves_cli_monkeypatch_seams(cli, tmp_path, monkeypatch):
    cfg = _cfg(cli)
    data = {"deploymentTargets": []}
    runs_file = tmp_path / "runs.json"
    runs_file.write_text("[]", encoding="utf-8")
    calls = []

    def fake_configured_targets(adapter_data):
        calls.append(("targets", len(adapter_data["deploymentTargets"])))
        return [{"name": "dev", "deployHealth": cfg}]

    def fake_runs_from_file(path, health_cfg):
        calls.append(("file", path, health_cfg["workflow"]))
        return [_run("success", 1)]

    def fake_github_runs(target, health_cfg):
        calls.append(("github", target, health_cfg["workflow"]))
        return [_run("success", 1)], None

    def fake_issues_for_runs(name, health_cfg, runs):
        calls.append(("issues", name, health_cfg["workflow"], len(runs)))
        return [f"{name}: fake issue"]

    monkeypatch.setattr(cli, "deploy_health_configured_targets", fake_configured_targets)
    monkeypatch.setattr(cli, "deploy_health_runs_from_file", fake_runs_from_file)
    monkeypatch.setattr(cli, "deploy_health_github_actions_runs", fake_github_runs)
    monkeypatch.setattr(cli, "deploy_health_issues_for_runs", fake_issues_for_runs)

    assert cli.deploy_health_issues(data, tmp_path, runs_file=runs_file) == ["dev: fake issue"]
    assert calls == [
        ("targets", 0),
        ("file", runs_file, "deploy-makerkit-dev.yml"),
        ("issues", "dev", "deploy-makerkit-dev.yml", 1),
    ]
    calls.clear()

    assert cli.deploy_health_issues(data, tmp_path) == ["dev: fake issue"]
    assert calls == [
        ("targets", 0),
        ("github", tmp_path, "deploy-makerkit-dev.yml"),
        ("issues", "dev", "deploy-makerkit-dev.yml", 1),
    ]


def test_normalize_deploy_health_defaults_off_and_validates(cli):
    assert cli.normalize_deploy_health_config(None, 0)["enabled"] is False
    assert cli.normalize_deploy_health_config({"workflow": "deploy.yml"}, 0)["enabled"] is True
    with pytest.raises(SystemExit):
        cli.normalize_deploy_health_config({"enabled": True}, 0)
    with pytest.raises(SystemExit):
        cli.normalize_deploy_health_config({"enabled": True, "workflow": "deploy.yml", "maxConsecutiveFailures": 0}, 0)


def test_latest_failed_deploy_blocks(cli):
    issues = cli.deploy_health_issues_for_runs(
        "dev",
        _cfg(cli),
        [_run("failure", 1), _run("success", 4)],
        now=datetime(2026, 6, 27, 21, 0, tzinfo=timezone.utc),
    )
    assert any("latest deploy workflow concluded failure" in issue for issue in issues)


def test_consecutive_deploy_failures_block(cli):
    issues = cli.deploy_health_issues_for_runs(
        "dev",
        _cfg(cli, failOnLatestFailure=False),
        [_run("failure", 1, run_id=3), _run("timed_out", 2, run_id=2), _run("cancelled", 3, run_id=1), _run("success", 5, run_id=0)],
        now=datetime(2026, 6, 27, 21, 0, tzinfo=timezone.utc),
    )
    assert any("3 consecutive failing runs" in issue for issue in issues)


def test_stale_or_missing_success_blocks(cli):
    now = datetime(2026, 6, 27, 21, 0, tzinfo=timezone.utc)
    stale = cli.deploy_health_issues_for_runs("dev", _cfg(cli, failOnLatestFailure=False), [_run("success", 90)], now=now)
    assert any("last successful deploy is" in issue for issue in stale)
    missing = cli.deploy_health_issues_for_runs("dev", _cfg(cli, failOnLatestFailure=False), [_run("failure", 1)], now=now)
    assert any("no successful deploy workflow run found" in issue for issue in missing)


def test_deploy_health_accepts_naive_timestamps(cli):
    run = _run("success", 1)
    run["createdAt"] = "2026-06-27T20:00:00"
    run["updatedAt"] = "2026-06-27T20:00:00"
    issues = cli.deploy_health_issues_for_runs(
        "dev",
        _cfg(cli),
        [run],
        now=datetime(2026, 6, 27, 21, 0),
    )
    assert issues == []


def test_github_actions_run_query_uses_target_cwd(cli, tmp_path, monkeypatch):
    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append((command, cwd, timeout))
        return 0, "[]", ""

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    runs, error = cli.deploy_health_github_actions_runs(tmp_path, _cfg(cli))
    assert error is None
    assert runs == []
    assert calls and calls[0][1] == tmp_path


def test_deploy_health_command_exits_nonzero_for_latest_failure(cli, tmp_path, monkeypatch, capsys):
    cfg = _cfg(cli)
    data = {"deploymentTargets": [{"name": "apprunner-makerkit-dev", "deployHealth": cfg}]}
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps({"deploy-makerkit-dev.yml": [_run("failure", 1), _run("success", 3)]}), encoding="utf-8")

    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, tmp_path))
    rc = cli.deploy_health(
        argparse.Namespace(project=None, target=tmp_path, runs_file=runs_file, strict=True)
    )

    output = capsys.readouterr().out
    assert rc == 1
    assert "deploy_health_status: blocked" in output
    assert "latest deploy workflow concluded failure" in output
