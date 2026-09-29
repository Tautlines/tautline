"""Requested fleet observations are bounded and never turn missing evidence green."""
from __future__ import annotations

import copy
import importlib
import os
import sys
import threading
import time

import pytest

from tautline_methodology import work_remote as remote


HEAD = "a" * 40
URL = "https://github.com/example/app/pull/7"


def pr(head=HEAD):
    return {"number": 7, "html_url": URL, "state": "open", "draft": False,
            "merged": False, "head": {"sha": head},
            "base": {"repo": {"full_name": "example/app"}}}


def checks(head=HEAD, conclusion="success"):
    return {"total_count": 1, "check_runs": [
        {"id": 1, "head_sha": head, "status": "completed", "conclusion": conclusion}]}


def statuses(head=HEAD):
    return {"sha": head, "total_count": 0, "state": "pending", "statuses": []}


def test_observed_ci_does_not_change_declared_work(tmp_path, monkeypatch):
    remote = importlib.import_module("tautline_methodology.work_remote")
    responses = {"pulls": pr(), "check-runs": checks(), "status": statuses()}

    def request(target, endpoint, deadline):
        return copy.deepcopy(next(value for key, value in responses.items() if key in endpoint))

    monkeypatch.setattr(remote, "_gh_json", request)
    state = {"records": [{"lane": "builder", "state": "ACTIVE", "pr": URL}]}
    result = remote.attach_observations(tmp_path, state)
    record = result["records"][0]
    assert record["state"] == "ACTIVE"
    assert record["prObservation"]["state"] == "open"
    assert record["prObservation"]["ci"] == "passed"
    assert record["prObservation"]["headSha"] == HEAD
    assert record["prObservation"]["deployment"] == "unknown"

def observe(tmp_path, monkeypatch, response=None, *, records=None):
    calls = []

    def request(target, endpoint, deadline):
        calls.append(endpoint)
        if response is not None:
            return response(endpoint)
        if "/pulls/" in endpoint:
            return pr()
        return checks() if "check-runs" in endpoint else statuses()

    monkeypatch.setattr(remote, "_gh_json", request)
    state = {"records": records or [{"lane": "builder", "state": "ACTIVE", "pr": URL}]}
    return remote.attach_observations(tmp_path, state), calls


@pytest.mark.parametrize("url", [
    "http://github.com/example/app/pull/7", "https://gitlab.com/example/app/pull/7",
    "https://github.com.evil.test/example/app/pull/7", "https://user:secret@github.com/a/b/pull/7",
    "https://github.com/a/../pull/7", "https://github.com/a/b/pull/7?token=secret",
    "https://github.com/a/b/pull/7/files", "https://github.com/a/b/pull/07", "#7", [URL],
])
def test_unsupported_urls_never_invoke_github(tmp_path, monkeypatch, url):
    state, calls = observe(tmp_path, monkeypatch,
                           records=[{"state": "ACTIVE", "pr": url}])
    assert not calls
    result = state["records"][0]["prObservation"]
    assert result["state"] == "unknown" and result["url"] is None
    assert "secret" not in json_text(result)


def json_text(value):
    import json
    return json.dumps(value)


def test_duplicate_urls_share_one_observation_and_retired_are_omitted(tmp_path, monkeypatch):
    state, calls = observe(tmp_path, monkeypatch, records=[
        {"state": "ACTIVE", "pr": URL},
        {"state": "BLOCKED", "pr": URL.replace("example/app", "Example/App") + "/"},
        {"state": "COMPLETED", "pr": URL}, {"state": "ACTIVE", "pr": ""}])
    assert len(calls) == 4
    assert state["records"][0]["prObservation"] is state["records"][1]["prObservation"]
    assert "prObservation" not in state["records"][2]
    assert "prObservation" not in state["records"][3]


def test_all_includes_completed_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "_gh_json", lambda *args: pr())
    state = {"records": [{"state": "COMPLETED", "pr": URL}]}
    result = remote.attach_observations(tmp_path, state, all_records=True)
    assert result["records"][0]["prObservation"]["state"] == "open"
    assert result["records"][0]["state"] == "COMPLETED"


@pytest.mark.parametrize("fields,expected", [
    ({"draft": True}, "draft"), ({"state": "closed"}, "closed"),
    ({"state": "closed", "merged": True}, "merged"),
])
def test_pr_state_is_independent_of_declared_state(tmp_path, monkeypatch, fields, expected):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint:
                       {**pr(), **fields} if "/pulls/" in endpoint else
                       checks() if "check-runs" in endpoint else statuses())
    assert state["records"][0]["prObservation"]["state"] == expected
    assert state["records"][0]["state"] == "ACTIVE"


@pytest.mark.parametrize("bad", [
    [], None, {}, {**pr(), "number": True}, {**pr(), "html_url": URL.replace("/7", "/8")},
    {**pr(), "merged": True}, {**pr(), "draft": "false"},
    {**pr(), "head": {"sha": "not-a-sha"}}, {**pr(), "head": []},
    {**pr(), "base": {"repo": {"full_name": "other/repo"}}},
    {**pr(), "state": ["open"]},
])
def test_malformed_or_wrong_pr_identity_is_unknown(tmp_path, monkeypatch, bad):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: bad)
    result = state["records"][0]["prObservation"]
    assert result["state"] == "unknown" and result["ci"] == "unknown"
    assert result["headSha"] is None


@pytest.mark.parametrize("conclusion,expected", [
    ("success", "passed"), ("failure", "failed"), ("timed_out", "failed"),
    ("action_required", "failed"), ("cancelled", "cancelled"),
    ("skipped", "unknown"), ("neutral", "unknown"), (None, "unknown"), ([], "unknown"),
])
def test_ci_results_never_promote_inconclusive_checks(tmp_path, monkeypatch, conclusion, expected):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else checks(conclusion=conclusion) if "check-runs" in endpoint
                       else statuses())
    assert state["records"][0]["prObservation"]["ci"] == expected


def test_pending_check_is_pending(tmp_path, monkeypatch):
    running = checks(conclusion=None)
    running["check_runs"][0]["status"] = "in_progress"
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else running if "check-runs" in endpoint else statuses())
    assert state["records"][0]["prObservation"]["ci"] == "pending"


@pytest.mark.parametrize("bad", [
    None, [], {}, {"total_count": True, "check_runs": []},
    {"total_count": 1, "check_runs": []}, {"total_count": 0, "check_runs": [{}]},
    {"total_count": 1, "check_runs": [None]}, checks(head="b" * 40),
    {"total_count": 301, "check_runs": []},
])
def test_incomplete_check_pages_cannot_pass(tmp_path, monkeypatch, bad):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else bad if "check-runs" in endpoint else statuses())
    result = state["records"][0]["prObservation"]
    assert result["state"] == "open" and result["ci"] == "unknown"


@pytest.mark.parametrize("bad", [
    None, [], {}, statuses("b" * 40), {**statuses(), "total_count": True},
    {**statuses(), "state": "success"}, {**statuses(), "state": "failure"},
    {**statuses(), "total_count": 1},
    {**statuses(), "total_count": 1, "state": "failure",
     "statuses": [{"id": 1, "state": "success"}]},
    {**statuses(), "total_count": 1, "state": "success",
     "statuses": [{"id": 1, "state": []}]},
])
def test_incomplete_status_observations_cannot_pass(tmp_path, monkeypatch, bad):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else checks() if "check-runs" in endpoint else bad)
    assert state["records"][0]["prObservation"]["ci"] == "unknown"


@pytest.mark.parametrize("value,expected", [
    ("success", "passed"), ("failure", "failed"), ("error", "failed"), ("pending", "pending")])
def test_commit_statuses_are_observed_without_check_runs(tmp_path, monkeypatch, value, expected):
    status = {**statuses(), "total_count": 1,
              "state": "failure" if value == "error" else value,
              "statuses": [{"id": 1, "state": value}]}
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else {"total_count": 0, "check_runs": []} if "check-runs" in endpoint
                       else status)
    assert state["records"][0]["prObservation"]["ci"] == expected


def test_no_observations_is_unknown(tmp_path, monkeypatch):
    state, _ = observe(tmp_path, monkeypatch, lambda endpoint: pr() if "/pulls/" in endpoint
                       else {"total_count": 0, "check_runs": []} if "check-runs" in endpoint
                       else statuses())
    assert state["records"][0]["prObservation"]["ci"] == "unknown"


def test_push_during_observation_cannot_reuse_old_green(tmp_path, monkeypatch):
    reads = 0

    def response(endpoint):
        nonlocal reads
        if "/pulls/" in endpoint:
            reads += 1
            return pr(HEAD if reads == 1 else "b" * 40)
        assert HEAD in endpoint
        return checks() if "check-runs" in endpoint else statuses()

    state, _ = observe(tmp_path, monkeypatch, response)
    result = state["records"][0]["prObservation"]
    assert result["ci"] == "unknown" and result["headSha"] == "b" * 40
    assert "changed" in result["reason"]


def test_failure_to_recheck_head_cannot_leave_a_green(tmp_path, monkeypatch):
    reads = 0

    def response(endpoint):
        nonlocal reads
        if "/pulls/" in endpoint:
            reads += 1
            if reads == 2:
                raise remote.ObservationUnavailable("GitHub observation unavailable")
            return pr()
        return checks() if "check-runs" in endpoint else statuses()

    state, _ = observe(tmp_path, monkeypatch, response)
    assert state["records"][0]["prObservation"]["ci"] == "unknown"


def test_page_coverage_and_duplicate_detection(tmp_path, monkeypatch):
    def response(endpoint):
        if "/pulls/" in endpoint:
            return pr()
        if "check-runs" in endpoint:
            return {"total_count": 2, "check_runs": checks()["check_runs"]}
        return statuses()

    state, calls = observe(tmp_path, monkeypatch, response)
    assert state["records"][0]["prObservation"]["ci"] == "unknown"
    assert sum("check-runs" in call for call in calls) == 2


def test_multiple_pages_are_combined(tmp_path, monkeypatch):
    def response(endpoint):
        if "/pulls/" in endpoint:
            return pr()
        if "check-runs" in endpoint:
            check = checks()["check_runs"][0]
            return {"total_count": 2, "check_runs": [
                {**check, "id": 2 if "page=2&" in endpoint else 1}]}
        return statuses()

    state, calls = observe(tmp_path, monkeypatch, response)
    assert state["records"][0]["prObservation"]["ci"] == "passed"
    assert sum("check-runs" in call for call in calls) == 2


def test_parallelism_and_unique_pr_cap(tmp_path, monkeypatch):
    entered = threading.Barrier(4)
    calls = []

    def observation(target, identity, deadline):
        calls.append(identity)
        entered.wait(timeout=2)
        return remote._unknown("Test observation", identity[0])

    monkeypatch.setattr(remote, "_observe", observation)
    state = {"records": [{"state": "ACTIVE", "pr": URL.removesuffix("7") + str(i)}
                         for i in range(1, 11)]}
    result = remote.attach_observations(tmp_path, state)
    assert len(calls) == 8
    assert "limit" in result["records"][-1]["prObservation"]["reason"]


def executable(tmp_path, monkeypatch, source):
    script = tmp_path / "gh"
    script.write_text(f"#!{sys.executable}\n" + source)
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    return script


def test_real_failed_command_never_echoes_credentials(tmp_path, monkeypatch):
    secret = "DO-NOT-PRINT-INHERITED-CREDENTIAL"
    monkeypatch.setenv("GH_TOKEN", secret)
    executable(tmp_path, monkeypatch,
               "import os, sys\nprint(os.environ['GH_TOKEN'])\n"
               "print(os.environ['GH_TOKEN'], file=sys.stderr)\nsys.exit(1)\n")
    state = {"records": [{"state": "ACTIVE", "pr": URL}]}
    result = remote.attach_observations(tmp_path, state)
    assert result["records"][0]["prObservation"]["state"] == "unknown"
    assert secret not in json_text(result)


def test_real_timeout_stops_pipe_holding_descendant_for_whole_fleet(tmp_path, monkeypatch):
    script = executable(tmp_path, monkeypatch, "")
    script.write_text("#!/bin/sh\n(sleep 1.25; : > escaped-$$) &\n"
                      "printf '%s' \"$!\" > child-$$\nwait\n")
    state = {"records": [{"state": "ACTIVE", "pr": URL.removesuffix("7") + str(i)}
                         for i in range(1, 9)]}
    started = time.monotonic()
    result = remote.attach_observations(tmp_path, state, timeout=0.75)
    assert time.monotonic() - started < 1.5
    assert all(r["prObservation"]["state"] == "unknown" for r in result["records"])
    children = [int(path.read_text()) for path in tmp_path.glob("child-*")]
    assert children
    time.sleep(1.3)
    assert not list(tmp_path.glob("escaped-*"))


def test_response_size_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "MAX_RESPONSE_BYTES", 100)
    executable(tmp_path, monkeypatch, "print('x' * 1000)\n")
    with pytest.raises(remote.ObservationUnavailable, match="size limit"):
        remote._gh_json(tmp_path, "repos/example/app/pulls/7", time.monotonic() + 1)


def test_one_broken_response_does_not_discard_a_healthy_peer(tmp_path, monkeypatch):
    def request(target, endpoint, deadline):
        if "/pulls/8" in endpoint:
            raise RecursionError("untrusted response detail must not be printed")
        if "/pulls/" in endpoint:
            return pr()
        return checks() if "check-runs" in endpoint else statuses()

    monkeypatch.setattr(remote, "_gh_json", request)
    state = {"records": [{"state": "ACTIVE", "pr": URL},
                         {"state": "BLOCKED", "pr": URL.removesuffix("7") + "8"}]}
    result = remote.attach_observations(tmp_path, state)
    assert result["records"][0]["prObservation"]["ci"] == "passed"
    assert result["records"][1]["prObservation"]["state"] == "unknown"
    assert "untrusted" not in json_text(result)


def test_exhausted_deadline_never_starts_a_subprocess(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("No subprocess is allowed after the deadline")

    monkeypatch.setattr(remote.subprocess, "Popen", unexpected)
    state = {"records": [{"state": "ACTIVE", "pr": URL}]}
    result = remote.attach_observations(tmp_path, state, timeout=0)
    assert "time budget" in result["records"][0]["prObservation"]["reason"]


def test_recursive_json_decoder_failure_is_unknown(tmp_path, monkeypatch):
    executable(tmp_path, monkeypatch, "print('{}')\n")

    def recursive_payload(raw):
        raise RecursionError("Untrusted nested response detail")

    monkeypatch.setattr(remote.json, "loads", recursive_payload)
    with pytest.raises(remote.ObservationUnavailable, match="unreadable"):
        remote._gh_json(tmp_path, "repos/example/app/pulls/7", time.monotonic() + 1)
