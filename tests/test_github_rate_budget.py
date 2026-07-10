import subprocess

import pytest


def _rate_payload(graphql_remaining=5000, core_remaining=4999, search_remaining=30):
    return {
        "resources": {
            "graphql": {"limit": 5000, "used": 5000 - graphql_remaining, "remaining": graphql_remaining, "reset": 1893456000},
            "core": {"limit": 5000, "used": 5000 - core_remaining, "remaining": core_remaining, "reset": 1893456000},
            "search": {"limit": 30, "used": 30 - search_remaining, "remaining": search_remaining, "reset": 1893456000},
        }
    }


def test_goal_tracker_gh_json_caches_project_reads(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_READ_MODE", "always")
    calls = []
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]

    def fake_command_json(command, cwd=None, timeout=None):
        calls.append(command)
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(), ""
        if command == ["gh", *args]:
            return 0, {"items": [{"id": "PVTI_1"}]}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_1"}]}
    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_1"}]}
    assert calls.count(["gh", *args]) == 1


def test_goal_tracker_gh_json_default_cache_mode_refreshes_when_budget_is_healthy(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_SHARED_SNAPSHOT_SECONDS", "0")
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]
    live_payloads = iter([{"items": [{"id": "PVTI_first"}]}, {"items": [{"id": "PVTI_second"}]}])

    def fake_command_json(command, cwd=None, timeout=None):
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(), ""
        if command == ["gh", *args]:
            return 0, next(live_payloads), ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_first"}]}
    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_second"}]}


def test_goal_tracker_gh_json_reuses_default_shared_snapshot(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]
    calls = []

    def fake_command_json(command, cwd=None, timeout=None):
        calls.append(command)
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(), ""
        if command == ["gh", *args]:
            return 0, {"items": [{"id": "PVTI_snapshot"}]}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_snapshot"}]}
    assert cli.goal_tracker_gh_json(args, tmp_path) == {"items": [{"id": "PVTI_snapshot"}]}
    assert calls.count(["gh", *args]) == 1


def test_goal_tracker_gh_json_blocks_live_project_read_when_graphql_budget_low(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", "100")
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]
    live_project_calls = []

    def fake_command_json(command, cwd=None, timeout=None):
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(graphql_remaining=0), ""
        if command == ["gh", *args]:
            live_project_calls.append(command)
            return 0, {"items": []}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    with pytest.raises(SystemExit, match="GitHub GraphQL budget low"):
        cli.goal_tracker_gh_json(args, tmp_path)
    assert live_project_calls == []


def test_goal_tracker_gh_json_uses_fresh_cache_even_when_graphql_budget_low(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", "100")
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]
    payload = {"items": [{"id": "PVTI_cached"}]}
    cli.github_cache_write(args, payload)
    project_calls = []

    def fake_command_json(command, cwd=None, timeout=None):
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(graphql_remaining=0), ""
        if command == ["gh", *args]:
            project_calls.append(command)
            return 0, {"items": []}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    assert cli.goal_tracker_gh_json(args, tmp_path) == payload
    assert project_calls == []


def test_pending_retry_prevents_busy_rate_limit_loop_when_graphql_exhausted(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", "100")
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]
    calls = []

    def fake_command_json(command, cwd=None, timeout=None):
        calls.append(command)
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(graphql_remaining=0), ""
        if command == ["gh", *args]:
            return 0, {"items": []}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    with pytest.raises(SystemExit, match="safe_next_poll="):
        cli.goal_tracker_gh_json(args, tmp_path)
    with pytest.raises(SystemExit, match="pending_retry"):
        cli.goal_tracker_gh_json(args, tmp_path)

    assert calls.count(["gh", "api", "rate_limit"]) == 1
    assert calls.count(["gh", *args]) == 0


def test_project_cache_invalidation_removes_cached_project_and_graphql_reads(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    project_args = ["project", "view", "7", "--owner", "minervit", "--format", "json"]
    graphql_args = ["api", "graphql", "-f", "query=query($id:ID!){node(id:$id){id}}", "-f", "id=PVT_kw"]
    issue_args = ["issue", "list", "--repo", "o/r", "--json", "number"]
    cli.github_cache_write(project_args, {"id": "PVT_kw"})
    cli.github_cache_write(graphql_args, {"data": {"node": {"id": "PVT_kw"}}})
    cli.github_cache_write(issue_args, [{"number": 1}])

    assert cli.github_cache_invalidate_project() == 2
    assert cli.github_cache_read(project_args)[0] is None
    assert cli.github_cache_read(graphql_args)[0] is None
    assert cli.github_cache_read(issue_args)[0] == [{"number": 1}]


def test_github_issue_list_rest_paginates_and_filters_pull_requests(cli, tmp_path, monkeypatch):
    calls = []

    def fake_rest_json(endpoint, target, extra_args=None, timeout=30):
        calls.append(endpoint)
        if endpoint.endswith("page=1"):
            return [{"number": n, "html_url": f"https://github.com/o/r/issues/{n}"} for n in range(1, 101)]
        if endpoint.endswith("page=2"):
            return [{"number": n, "html_url": f"https://github.com/o/r/issues/{n}"} for n in range(101, 131)] + [
                {"number": 900, "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/900"}}
            ]
        return []

    monkeypatch.setattr(cli, "github_rest_json", fake_rest_json)

    issues = cli.github_issue_list_rest("o/r", tmp_path, label="stakeholder question", limit=120)
    assert [issue["number"] for issue in issues[:2]] == [1, 2]
    assert issues[-1]["number"] == 120
    assert len(issues) == 120
    assert "labels=stakeholder%20question" in calls[0]
    assert "per_page=100&page=2" in calls[1]


def test_github_budget_status_command_reports_budget_and_cache(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))

    def fake_command_json(command, cwd=None, timeout=None):
        assert command == ["gh", "api", "rate_limit"]
        return 0, _rate_payload(graphql_remaining=75), ""

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    result = cli.main(["github-budget-status", "--target", str(tmp_path), "--refresh"])
    out = capsys.readouterr().out

    assert result == 0
    assert "github_budget_status: ok low_watermark=100" in out
    assert "github_budget_graphql: remaining=75" in out
    assert "state=low" in out
    assert "github_budget_core:" in out
    assert "github_cache:" in out
    assert "github_provider_health:" in out
    assert "github_provider_recent_call:" in out


def test_github_budget_status_reports_pending_retry_and_recent_callers(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))
    monkeypatch.setenv("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", "100")
    args = ["project", "item-list", "7", "--owner", "minervit", "--format", "json", "--limit", "100"]

    def fake_command_json(command, cwd=None, timeout=None):
        if command == ["gh", "api", "rate_limit"]:
            return 0, _rate_payload(graphql_remaining=0), ""
        if command == ["gh", *args]:
            return 0, {"items": []}, ""
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli, "command_json", fake_command_json)

    with pytest.raises(SystemExit):
        cli.goal_tracker_gh_json(args, tmp_path)

    result = cli.main(["github-budget-status", "--target", str(tmp_path)])
    out = capsys.readouterr().out

    assert result == 0
    assert "github_provider_health:" in out
    assert "pending_migrations=0" in out
    assert "pending_retries=1" in out
    assert "github_provider_pending_retry: operation=project.item-list" in out
    assert "github_provider_recent_call:" in out


def test_gh_api_preserves_called_process_error_contract(cli, monkeypatch):
    def fail_rest(_path, _target):
        raise SystemExit("gh api failed")

    monkeypatch.setattr(cli, "github_rest_json", fail_rest)

    with pytest.raises(subprocess.CalledProcessError):
        cli.gh_api("repos/minervit/example")
