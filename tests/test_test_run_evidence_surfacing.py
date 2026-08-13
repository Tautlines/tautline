"""item 37 W2: report-only surfacing of test-execution evidence at prepush and lane-start.

Release 1 is report-only by design. A fail-closed test-evidence gate on upgrade would recreate the
2026-07-22 startup-gate lockout, so the release's central obligation is a NEGATIVE one: no exit
code moves in any evidence state. The two parametrized exit-code tests below are that proof, and
they lean on W1's never-raise `classify_test_run_evidence` contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tautline_methodology import cli, test_evidence

EVIDENCE_STATES = ["missing", "invalid", "stale", "red", "current", "unavailable"]


def _seed_state(target: Path, state: str) -> None:
    """Put `target` into the requested evidence state with a real record where one is needed."""
    records = test_evidence.test_run_dir(target)
    records.mkdir(parents=True, exist_ok=True)
    if state == "missing":
        return
    if state == "unavailable":
        (records / "20260101T000000.000000Z-test-run.json").write_text("{broken", encoding="utf-8")
        return

    record = {
        "schema": test_evidence.TEST_RUN_SCHEMA,
        "label": "full-preflight",
        "command": "true",
        "commandSource": "--command",
        "exitCode": 1 if state == "red" else 0,
        "startedAt": "2026-01-01T00:00:00.000000Z",
        "finishedAt": "2026-01-01T00:00:01.000000Z",
        "durationSeconds": 1.0,
        "git": {
            "commit": "0" * 40,
            "branch": "main",
            "treeDigest": "deadbeef" if state == "stale" else "PLACEHOLDER",
            "digestMethod": test_evidence.TREE_DIGEST_METHOD,
        },
        "counts": {"source": "exit-code-only"},
        "outputLog": ".ai-runs/test-runs/x.log",
    }
    if state == "invalid":
        record["reportError"] = "declared report missing"
    if state == "current":
        record["git"]["treeDigest"] = test_evidence.non_ignored_tree_digest(target)
    (records / "20260101T000000.000000Z-test-run.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


@pytest.fixture()
def lane(tmp_path):
    import subprocess

    repo = tmp_path / "lane"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"],
                 ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / ".gitignore").write_text(".ai-runs/\n", encoding="utf-8")
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


@pytest.mark.parametrize("state", EVIDENCE_STATES)
def test_evidence_line_is_emitted_for_every_state(lane, state):
    _seed_state(lane, state)
    lines = cli.test_run_evidence_lines(lane)
    assert lines and lines[0].startswith("test_run_evidence: ")


def test_evidence_line_reports_current_only_when_the_tree_matches(lane):
    _seed_state(lane, "current")
    assert "test_run_evidence: current" in cli.test_run_evidence_lines(lane)[0]
    (lane / "src.py").write_text("x = 2\n", encoding="utf-8")
    assert "test_run_evidence: stale" in cli.test_run_evidence_lines(lane)[0]


@pytest.mark.parametrize("state", EVIDENCE_STATES)
def test_remedy_line_present_unless_current(lane, state):
    _seed_state(lane, state)
    lines = cli.test_run_evidence_lines(lane)
    if lines[0].startswith("test_run_evidence: current"):
        assert len(lines) == 1
    else:
        assert any(line.startswith("test_run_evidence_next: ") for line in lines)


def test_remedy_line_is_remediation_aware(lane):
    """`test-run` is dispatch-blocked while remediation is active, so advertising it there would
    print a command the dispatcher refuses -- the RCA control-6 defect in our own output."""
    _seed_state(lane, "missing")
    plain = cli.test_run_evidence_lines(lane)[-1]
    assert "run `tautline test-run --target .`" in plain

    marker = cli.startup_remediation_marker_path(lane)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    remediating = cli.test_run_evidence_lines(lane)[-1]
    assert "complete startup remediation first" in remediating


@pytest.mark.parametrize("state", EVIDENCE_STATES)
def test_evidence_lines_never_raise(lane, state):
    """lane-start is a startup boundary: a reporter that can explode there changes startup
    behaviour despite the release being report-only."""
    _seed_state(lane, state)
    assert cli.test_run_evidence_lines(lane)


def test_evidence_lines_survive_a_non_git_target(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert cli.test_run_evidence_lines(plain)[0].startswith("test_run_evidence: ")


@pytest.mark.parametrize("state", EVIDENCE_STATES)
def test_guard_check_prepush_exit_code_unchanged_for_every_evidence_state(
    lane, state, monkeypatch, capsys
):
    """The release's no-lockout proof: the evidence line is pure output in every state."""
    _seed_state(lane, state)
    monkeypatch.setattr(cli, "guard_check_blocker_state", lambda target: 7)

    rc = cli.guard_check(
        argparse.Namespace(target=lane, boundary="prepush", project=None)
    )
    out = capsys.readouterr().out
    assert rc == 7, "the evidence line must not alter the blocker gate's exit code"
    assert "test_run_evidence: " in out


@pytest.mark.parametrize("state", EVIDENCE_STATES)
def test_guard_check_prepush_prints_evidence_line_even_when_a_check_blocks(
    lane, state, monkeypatch, capsys
):
    """Printed after the blocker gate, this line would vanish on exactly the blocked runs where
    the operator most needs to know the suite was never run."""
    _seed_state(lane, state)
    monkeypatch.setattr(cli, "guard_check_blocker_state", lambda target: 3)

    cli.guard_check(argparse.Namespace(target=lane, boundary="prepush", project=None))
    out = capsys.readouterr().out
    assert out.index("test_run_evidence: ") < len(out)
    assert "test_run_evidence: " in out


def test_guard_check_non_prepush_boundary_does_not_print_the_line(lane, monkeypatch, capsys):
    _seed_state(lane, "missing")
    monkeypatch.setattr(cli, "guard_check_blocker_state", lambda target: 0)
    cli.guard_check(argparse.Namespace(target=lane, boundary="premerge", project=None))
    assert "test_run_evidence: " not in capsys.readouterr().out
