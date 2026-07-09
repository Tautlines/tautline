"""RCA: GitHub access should avoid unnecessary GraphQL pressure."""


def _data():
    tracker = {
        "enabled": True,
        "provider": "github-projects",
        "owner": "minervit",
        "projectNumber": 5,
        "scopeQuery": "",
        "statusField": "Status",
        "readyStatuses": ["Ready"],
        "activeStatuses": ["In progress"],
        "doneStatuses": ["Done"],
        "blockedStatuses": ["Blocked"],
    }
    return {"goalTracker": tracker, "backlogProvider": {"enabled": False}}


def test_issue_state_prefers_rest(cli, tmp_path, monkeypatch):
    def _command_json(command, cwd=None, timeout=None):
        assert command[:2] == ["gh", "api"]
        return 0, {"state": "open"}, ""

    monkeypatch.setattr(cli, "command_json", _command_json)

    assert cli.github_issue_or_pr_state_rest(tmp_path, "https://github.com/o/r/issues/234") == "OPEN"
