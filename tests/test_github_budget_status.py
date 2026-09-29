"""`github-budget-status` -- Tier 1 salvage, track S2.

Reconnects the pre-demolition handler to the cache/lock/identity primitives ghutil.py kept alive
throughout the 2026-08-28 process-bankruptcy demolition. Plain REST (`gh api rate_limit`), never
Projects GraphQL. Two behaviors are deliberately DIFFERENT from the pre-demolition handler, and
each gets its own test:

* ALWAYS EXITS 0 (the salvage spec's rail: a diagnostic verb prints findings, never enforces them
  via exit code) -- the old handler returned 1 on a rate-limit fetch error.
* `allow_cold` is threaded from `--identity`, so a BARE invocation never pays a cold `gh api user`
  subprocess (memo-or-nothing) -- the old handler let `print_github_identity_status`'s default
  override that split, contradicting ghutil.py's own docstring for the primitive it calls.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sandboxed_github_state(monkeypatch, tmp_path):
    """Every ghutil-owned file (cache, telemetry, identity records) lives under tmp_path."""
    root = tmp_path / "github-state"
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(root))
    return root


def _ns(**overrides) -> argparse.Namespace:
    base = {"target": Path("."), "refresh": False, "identity": False}
    base.update(overrides)
    return argparse.Namespace(**base)


def _fake_run(rate_limit_payload=None, rate_limit_code=0, gh_missing=False):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if gh_missing:
            raise FileNotFoundError("gh not found")
        if command[:2] == ["gh", "api"] and command[2:3] == ["rate_limit"]:
            out = json.dumps(rate_limit_payload or {}) if rate_limit_code == 0 else ""
            return subprocess.CompletedProcess(command, rate_limit_code, out, "" if rate_limit_code == 0 else "boom")
        return subprocess.CompletedProcess(command, 0, "", "")

    return fake_run, calls


RATE_LIMIT_PAYLOAD = {
    "resources": {
        "graphql": {"remaining": 4900, "used": 100, "limit": 5000, "reset": 1893456000},
        "core": {"remaining": 4990, "used": 10, "limit": 5000, "reset": 1893456000},
        "search": {"remaining": 30, "used": 0, "limit": 30, "reset": 1893456000},
    }
}


# --- command_json ---------------------------------------------------------------------------


def test_command_json_parses_stdout(cli, monkeypatch):
    fake_run, _calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code, payload, err = cli.command_json(["gh", "api", "rate_limit"])
    assert (code, err) == (0, "")
    assert payload == RATE_LIMIT_PAYLOAD


def test_command_json_reports_nonzero_exit_as_error(cli, monkeypatch):
    fake_run, _calls = _fake_run(rate_limit_code=1)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code, payload, err = cli.command_json(["gh", "api", "rate_limit"])
    assert code == 1
    assert payload is None
    assert "boom" in err


def test_command_json_reports_invalid_json_as_error(cli, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "not json", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code, payload, err = cli.command_json(["gh", "api", "rate_limit"])
    assert code == 1
    assert payload is None
    assert "invalid JSON" in err


# --- github_rate_limit_snapshot -----------------------------------------------------------------


def test_rate_limit_snapshot_fetches_live_and_writes_cache(cli, monkeypatch, sandboxed_github_state, tmp_path):
    fake_run, calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    snapshot = cli.github_rate_limit_snapshot(tmp_path)
    assert snapshot == RATE_LIMIT_PAYLOAD
    assert any(c[:3] == ["gh", "api", "rate_limit"] for c in calls)
    # A second read within the TTL must be served from cache -- no second subprocess call.
    calls.clear()
    snapshot2 = cli.github_rate_limit_snapshot(tmp_path)
    assert snapshot2 == RATE_LIMIT_PAYLOAD
    assert calls == []


def test_rate_limit_snapshot_max_age_zero_bypasses_cache(cli, monkeypatch, sandboxed_github_state, tmp_path):
    fake_run, calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli.github_rate_limit_snapshot(tmp_path)
    calls.clear()
    cli.github_rate_limit_snapshot(tmp_path, max_age=0)
    assert any(c[:3] == ["gh", "api", "rate_limit"] for c in calls)


def test_rate_limit_snapshot_reports_error_on_gh_failure(cli, monkeypatch, sandboxed_github_state, tmp_path):
    fake_run, _calls = _fake_run(rate_limit_code=1)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    snapshot = cli.github_rate_limit_snapshot(tmp_path)
    assert "error" in snapshot


# --- github_cache_summary -------------------------------------------------------------------


def test_cache_summary_counts_fresh_and_stale(cli, monkeypatch, sandboxed_github_state):
    root = sandboxed_github_state
    root.mkdir(parents=True)
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_TTL_SECONDS", "300")
    import time

    fresh = {"stored_at": time.time(), "args": ["api", "rate_limit"], "payload": {}}
    stale = {"stored_at": time.time() - 10_000, "args": ["api", "rate_limit"], "payload": {}}
    (root / "fresh.json").write_text(json.dumps(fresh), encoding="utf-8")
    (root / "stale.json").write_text(json.dumps(stale), encoding="utf-8")
    (root / "garbage.json").write_text("not json", encoding="utf-8")
    summary = cli.github_cache_summary()
    assert summary["entries"] == 3
    assert summary["fresh"] == 1
    assert summary["stale"] == 2  # the aged entry, plus the unreadable one


def test_cache_summary_on_missing_dir_is_empty(cli, sandboxed_github_state):
    summary = cli.github_cache_summary()
    assert summary == {"dir": str(sandboxed_github_state), "entries": 0, "fresh": 0, "stale": 0}


# --- print_github_identity_status: allow_cold threading, the deliberate behavior change ----------


def test_identity_status_disabled_by_master_knob_prints_nothing(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    cli.print_github_identity_status(tmp_path, allow_cold=True)
    assert capsys.readouterr().out == ""


def test_bare_status_read_never_pays_a_cold_subprocess(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    """allow_cold=False (what a bare `github-budget-status` passes): no memo exists, so this must
    return the "not resolved yet" finding WITHOUT ever shelling out to `gh` -- `gh` is patched to
    explode if called, which would fail the test rather than silently pass. Resolving the memo's
    OWN cache key still costs a local `git rev-parse` (pre-existing, unrelated plumbing this salvage
    does not touch); only `gh` -- the subprocess that can reach the network -- is asserted on.
    """
    real_run = cli.subprocess.run

    def guarded(command, *a, **k):
        if command and command[0] == "gh":
            raise AssertionError(f"cold `gh` resolution must not run when allow_cold=False: {command}")
        return real_run(command, *a, **k)

    monkeypatch.setattr(cli.subprocess, "run", guarded)
    cli.print_github_identity_status(tmp_path, allow_cold=False)
    out = capsys.readouterr().out
    assert "github_identity: unavailable" in out
    assert "identity not resolved yet" in out
    assert "github-budget-status --identity" in out  # no stale removed-verb claim


def test_identity_flag_allows_cold_resolution(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    def fake_run(command, **kwargs):
        if command[:2] == ["gh", "auth"]:
            return subprocess.CompletedProcess(command, 0, "fake-token-value-123456\n", "")
        if command[:2] == ["gh", "api"] and "user" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"login": "octocat", "id": 1}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    # No real git remote in tmp_path; empty upstream/lane-key is fine for this assertion.
    cli.print_github_identity_status(tmp_path, allow_cold=True, create_record=True)
    out = capsys.readouterr().out
    assert "github_identity: login=octocat" in out


# --- github_budget_status: the always-exit-0 rail -------------------------------------------


def test_budget_status_exits_0_even_when_gh_is_missing(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    fake_run, _calls = _fake_run(gh_missing=True)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")  # keep this test scoped to the budget path
    code = cli.github_budget_status(_ns(target=tmp_path))
    assert code == 0
    out = capsys.readouterr().out
    assert "github_budget_status: unavailable" in out


def test_budget_status_reports_resources_and_low_watermark_state(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    fake_run, _calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    monkeypatch.setenv("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", "5000")  # above "remaining" -> low
    code = cli.github_budget_status(_ns(target=tmp_path))
    assert code == 0
    out = capsys.readouterr().out
    assert "github_budget_status: ok low_watermark=5000" in out
    assert "github_budget_graphql: remaining=4900 used=100 limit=5000" in out
    assert "state=low" in out
    assert "github_budget_core:" in out
    assert "github_budget_search:" in out
    assert "github_cache:" in out
    assert "github_provider_health:" in out


def test_budget_status_sanitizes_a_control_character_in_pending_retry_reason(
    cli, monkeypatch, capsys, sandboxed_github_state, tmp_path
):
    """`reason` can carry a remote error body; a control character in it must not reach the
    terminal raw. Plants one and asserts the fix (routed through `util.flatten_printable`, not a
    hand-rolled newline-strip-and-cap) actually strips it rather than merely trusting that it does.
    """
    import time

    fake_run, _calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    retries_dir = sandboxed_github_state / "pending-retries"
    retries_dir.mkdir(parents=True)
    record = {
        "operation": "graphql.read",
        "attempts": 1,
        "reason": "budget exhausted\x1b[2Kinjected-line",
        "safe_next_poll_epoch": time.time() + 3600,
        "safeNextPoll": "2099-01-01T00:00:00+00:00",
        "reset": "unknown",
    }
    (retries_dir / "one.json").write_text(json.dumps(record), encoding="utf-8")
    code = cli.github_budget_status(_ns(target=tmp_path))
    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "github_provider_pending_retry:" in out
    assert "budget exhausted" in out


def test_budget_status_refresh_bypasses_cache(cli, monkeypatch, sandboxed_github_state, tmp_path):
    fake_run, calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    cli.github_budget_status(_ns(target=tmp_path))
    calls.clear()
    cli.github_budget_status(_ns(target=tmp_path, refresh=True))
    assert any(c[:3] == ["gh", "api", "rate_limit"] for c in calls)


def test_bare_budget_status_does_not_mint_an_identity_record(cli, monkeypatch, sandboxed_github_state, tmp_path):
    """The deliberate behavior fix: without --identity, no identity record file is created even
    when the identity subsystem is enabled and gh is reachable."""
    fake_run, _calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli.github_budget_status(_ns(target=tmp_path))
    records_root = sandboxed_github_state / "identities"
    assert not records_root.is_dir() or list(records_root.glob("*.json")) == []


def test_identity_flag_disabled_by_master_knob_still_exits_0(cli, monkeypatch, capsys, sandboxed_github_state, tmp_path):
    fake_run, _calls = _fake_run(RATE_LIMIT_PAYLOAD)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    code = cli.github_budget_status(_ns(target=tmp_path, identity=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "MINERVIT_GITHUB_IDENTITY=0 stands the subsystem down" in out


# --- end-to-end through the registered verb -------------------------------------------------


def test_registered_verb_runs_and_exits_0(run_cli, monkeypatch, tmp_path):
    env_home = tmp_path / "home"
    env_home.mkdir()
    result = run_cli("github-budget-status", "--target", str(tmp_path), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "github_budget_status" in result.stdout or "github_identity" in result.stdout
