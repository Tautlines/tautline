import json
import subprocess

import pytest

from tautline_methodology import health


@pytest.fixture
def repo(lane):
    return lane


def configure(root):
    (root / ".tautline.json").write_text(json.dumps({"integrationBranch": "main"}))
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                   cwd=root, check=True)
    subprocess.run(["git", "remote", "set-url", "origin", "git@github.com:example/repo.git"],
                   cwd=root, check=True)


def test_local_health_uses_cached_refs_and_never_queries_network(repo, monkeypatch):
    configure(repo)
    monkeypatch.setattr(health, "_gh_json", lambda *args: pytest.fail("local health used network"))
    result = health.health_snapshot(repo)
    assert result["integration"]["source"] == "cached_local_ref"
    assert result["integration"]["ahead"] == result["integration"]["behind"] == 0
    assert result["ci"]["state"] == "unknown"
    assert result["deployment"]["state"] == "unknown"


@pytest.mark.parametrize("conclusion,wanted", [("success", "passed"), ("failure", "failed"),
                          ("cancelled", "cancelled"), ("skipped", "unknown"), (None, "pending")])
def test_remote_ci_uses_exact_live_integration_sha(repo, monkeypatch, conclusion, wanted):
    configure(repo)
    tip = "a" * 40
    endpoints = []

    def fake(_root, endpoint, paginate=False):
        endpoints.append(endpoint)
        if endpoint.endswith("/commits/main"):
            return {"sha": tip}
        if "/check-runs" in endpoint:
            assert f"/commits/{tip}/" in endpoint
            return [{"check_runs": [{"head_sha": tip, "status": "completed" if conclusion else "in_progress",
                                      "conclusion": conclusion}]}]
        assert endpoint.endswith(f"/commits/{tip}/status")
        return {"sha": tip, "state": "pending", "total_count": 0, "statuses": []}

    monkeypatch.setattr(health, "_gh_json", fake)
    result = health.health_snapshot(repo, remote=True)
    assert result["integration"]["remoteHead"] == tip
    assert result["ci"]["state"] == wanted
    assert len(endpoints) == 3


@pytest.mark.parametrize("kind", ["empty", "wrong_sha", "unavailable", "missing_status"])
def test_missing_or_mismatched_ci_evidence_is_unknown(repo, monkeypatch, kind):
    configure(repo)
    tip = "b" * 40

    def fake(_root, endpoint, paginate=False):
        if endpoint.endswith("/commits/main"):
            return {"sha": tip}
        if "/check-runs" in endpoint:
            if kind == "unavailable":
                raise health.HealthUnavailable("GitHub observation unavailable")
            checks = [] if kind == "empty" else [{"head_sha": "c" * 40 if kind == "wrong_sha" else tip,
                                                   "status": "completed", "conclusion": "success"}]
            return [{"check_runs": checks}]
        if kind == "missing_status":
            raise health.HealthUnavailable("GitHub observation unavailable")
        return {"sha": tip, "state": "pending", "total_count": 0, "statuses": []}

    monkeypatch.setattr(health, "_gh_json", fake)
    assert health.health_snapshot(repo, remote=True)["ci"]["state"] == "unknown"


def test_local_health_reports_missing_integration_honestly_and_exits_zero(repo, run_cli):
    result = run_cli("health", "--target", str(repo), "--json")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["integration"]["state"] == "unknown"
    assert value["ci"]["state"] == "unknown"


def test_live_health_bounds_gh_queries_and_suppresses_error_output(repo, monkeypatch):
    configure(repo)
    original = subprocess.run
    seen = []

    def run(command, **kwargs):
        if command[0] != "gh":
            return original(command, **kwargs)
        seen.append((command, kwargs["timeout"]))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="synthetic-secret")

    monkeypatch.setattr(health.subprocess, "run", run)
    result = health.health_snapshot(repo, remote=True)
    assert result["ci"]["state"] == "unknown"
    assert seen[0][1] == 8
    assert "--hostname" in seen[0][0]
    assert "synthetic-secret" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["later_page", "commit_status"])
def test_a_failure_outside_the_first_check_page_prevents_green(repo, monkeypatch, failure):
    configure(repo)
    tip = "d" * 40

    def fake(_root, endpoint, paginate=False):
        if endpoint.endswith("/commits/main"):
            return {"sha": tip}
        if "/check-runs" in endpoint:
            assert paginate
            pages = [{"check_runs": [{"head_sha": tip, "status": "completed", "conclusion": "success"}]}]
            if failure == "later_page":
                pages.append({"check_runs": [{"head_sha": tip, "status": "completed", "conclusion": "failure"}]})
            return pages
        return {"sha": tip, "state": "failure", "total_count": 1 if failure == "commit_status" else 0}

    monkeypatch.setattr(health, "_gh_json", fake)
    assert health.health_snapshot(repo, remote=True)["ci"]["state"] == "failed"
