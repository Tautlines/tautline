"""Live PR observations are explicit and never replace the agent's declared intent."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from tautline_methodology import work


@pytest.fixture
def view(monkeypatch, tmp_path):
    state = {
        "schema": work.SCHEMA, "lane": "builder", "backend": "local", "overlaps": [],
        "worktree": str(tmp_path), "store": str(tmp_path / "store"),
        "records": [{
            "lane": "builder", "state": "ACTIVE", "status": "active", "goal": "Ship search",
            "branch": "feature", "paths": ["src/search"], "interfaces": [], "dependsOn": [],
            "item": "42", "pr": "https://github.com/example/app/pull/7", "blocker": "",
            "ageHours": 0.1,
        }],
    }
    monkeypatch.setattr(work, "_local_snapshot", lambda *a, **kw: copy.deepcopy(state))
    monkeypatch.setattr(work, "snapshot", lambda *a, **kw: copy.deepcopy(state))
    return state


def observer(monkeypatch, callback):
    monkeypatch.setitem(sys.modules, "tautline_methodology.work_remote",
                        SimpleNamespace(attach_observations=callback))


def test_explicit_remote_status_preserves_intent_and_exposes_exact_observation(cli, view, monkeypatch, capsys):
    calls = []
    def attach(target, state, **kwargs):
        calls.append(kwargs)
        state["records"][0]["prObservation"] = {
            "state": "merged", "headSha": "a" * 40, "ci": "passed",
            "observedAt": 1790653000, "url": view["records"][0]["pr"],
            "reason": "", "deployment": "unknown",
        }
        return state
    observer(monkeypatch, attach)
    assert cli.main(["work", "status", "--remote", "--json", "--no-sync"]) == 0
    result = json.loads(capsys.readouterr().out)
    record = result["records"][0]
    assert record["state"] == "ACTIVE" and record["status"] == "active"
    assert record["prObservation"]["state"] == "merged"
    assert record["prObservation"]["headSha"] == "a" * 40
    assert record["prObservation"]["deployment"] == "unknown"
    assert calls == [{"all_records": False}]
    assert "prObservation" not in view["records"][0]
    assert cli.main(["work", "status", "--remote", "--all"]) == 0
    output = capsys.readouterr().out
    assert "ACTIVE" in output and "PR MERGED" in output and "CI PASSED" in output
    assert "a" * 12 in output and "2026-09-29" in output
    assert "Deployment UNKNOWN" in output
    assert calls[-1] == {"all_records": True}


def test_default_status_and_startup_never_collect_pr_observations(cli, view, monkeypatch, capsys):
    observer(monkeypatch, lambda *a, **kw: pytest.fail("implicit GitHub observation"))
    assert cli.main(["work", "status", "--no-sync", "--json"]) == 0
    assert "prObservation" not in capsys.readouterr().out
    assert work.advisory_lines(view["worktree"])


@pytest.mark.parametrize("action", ["declare", "update", "finish", "abandon", "sync"])
def test_remote_flag_cannot_mutate_work(cli, view, monkeypatch, capsys, action):
    observer(monkeypatch, lambda *a, **kw: pytest.fail("unexpected observation"))
    monkeypatch.setattr(work, "_write", lambda *a, **kw: pytest.fail("unexpected mutation"))
    assert cli.main(["work", action, "--remote", "--goal", "change"]) == 1
    assert "only valid for work status" in capsys.readouterr().err


def test_unavailable_observer_keeps_declared_work_visible(cli, view, monkeypatch, capsys):
    def unavailable(*a, **kw):
        raise OSError("credential-bearing diagnostic must not be copied")
    observer(monkeypatch, unavailable)
    assert cli.main(["work", "status", "--remote", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["records"][0]["goal"] == "Ship search"
    assert result["records"][0]["state"] == "ACTIVE"
    assert result["records"][0]["prObservation"]["ci"] == "unknown"
    assert "credential-bearing" not in json.dumps(result)
