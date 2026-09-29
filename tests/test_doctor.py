"""Unit cover for `doctor` (four advisory checks) and `red-green-check` (the mutation-
discrimination proof), both salvaged/built in `tautline_methodology.doctor`.

Per-check OK/FINDING/UNKNOWN states are exercised directly against the pure/near-pure check
functions (fast, deterministic, no real `gh`/network). Git-shaped checks (branch-liveness,
framework-staleness) use REAL local git repos -- git has no useful fake-transport seam, and a local
repo is cheap and fully hermetic (no socket ever opens; `git ls-remote` against a local filesystem
path is local I/O, not network). `gh` itself is always mocked via the `doctor._run` seam: no test
here may shell out to the real `gh` binary.

`doctor_command` is never exercised through a real network call: the framework-staleness check's
`framework_repo` is always an injected local fixture, never the resolved real checkout, so no test
in this file (including the `run_cli` subprocess ones) does a live `git ls-remote` to GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tautline_methodology import doctor  # noqa: E402


# --- git fixture helpers -------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, remote: str | None = "https://example.invalid/owner/repo.git", branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")
    if remote:
        _git(path, "remote", "add", "origin", remote)
    return path


def _commit(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


# --- CheckResult / summary line -------------------------------------------------------------


def test_check_result_render_with_and_without_detail():
    assert doctor.CheckResult("x", doctor.OK).render() == "x: OK"
    assert doctor.CheckResult("x", doctor.FINDING, "why").render() == "x: FINDING -- why"


def test_summary_line_counts_each_status():
    results = [
        doctor.CheckResult("a", doctor.OK),
        doctor.CheckResult("b", doctor.OK),
        doctor.CheckResult("c", doctor.FINDING, "x"),
        doctor.CheckResult("d", doctor.UNKNOWN, "y"),
    ]
    assert doctor._summary_line(results) == "doctor: 4 checks -- 1 finding, 1 unknown, 2 ok"


def test_summary_line_empty():
    assert doctor._summary_line([]) == "doctor: 0 checks"


def test_safe_check_converts_exception_to_unknown():
    def boom(*_a, **_k):
        raise ValueError("bad")

    result = doctor._safe_check("thing", boom)
    assert result.status == doctor.UNKNOWN
    assert "bad" in result.detail


# --- a. branch-liveness ----------------------------------------------------------------------


def test_branch_liveness_unknown_when_not_a_git_repo(tmp_path):
    not_repo = tmp_path / "plain_dir"
    not_repo.mkdir()
    result = doctor.check_branch_liveness(not_repo)
    assert result.status == doctor.UNKNOWN
    assert "not a git repository" in result.detail


def test_branch_liveness_unknown_when_gh_not_installed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    result = doctor.check_branch_liveness(repo, gh_binary="definitely-not-a-real-binary-doctor-test")
    assert result.status == doctor.UNKNOWN
    assert "gh CLI not installed" in result.detail


def test_branch_liveness_unknown_when_no_remote(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo", remote=None)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.UNKNOWN
    assert "no git remote configured" in result.detail


def test_branch_liveness_unknown_on_detached_head(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    _git(repo, "checkout", "--detach", "HEAD")
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.UNKNOWN
    assert "current branch" in result.detail


def test_branch_liveness_unknown_when_gh_call_fails(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(doctor, "_run", lambda *_a, **_k: (1, "", "authentication required"))
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.UNKNOWN
    assert "gh pr list failed" in result.detail
    assert "authentication required" in result.detail


def test_branch_liveness_unknown_on_unparsable_json(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(doctor, "_run", lambda *_a, **_k: (0, "not json{{", ""))
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.UNKNOWN
    assert "unparsable" in result.detail


def test_branch_liveness_unknown_on_unexpected_state(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        doctor, "_run", lambda *_a, **_k: (0, json.dumps([{"number": 1, "state": "DRAFT"}]), "")
    )
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.UNKNOWN
    assert "unexpected PR state" in result.detail


def test_branch_liveness_ok_when_no_pr_found(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(doctor, "_run", lambda *_a, **_k: (0, "[]", ""))
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.OK
    assert "no PR found" in result.detail


def test_branch_liveness_ok_when_pr_open(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        doctor, "_run", lambda *_a, **_k: (0, json.dumps([{"number": 7, "state": "OPEN", "url": "https://x"}]), "")
    )
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.OK
    assert "PR #7" in result.detail and "OPEN" in result.detail


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_branch_liveness_finding_on_dead_pr(tmp_path, monkeypatch, state):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        doctor, "_run", lambda *_a, **_k: (0, json.dumps([{"number": 3, "state": state, "url": "https://x"}]), "")
    )
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.FINDING
    assert "you are working on a dead branch" in result.detail
    assert f"PR #3 is {state}" in result.detail


@pytest.mark.parametrize(
    "adapter",
    [
        {"schemaVersion": "lean-1", "integrationBranch": "experimental"},
        {"latestCode": {"base": "experimental", "remote": "origin"}},
        {"laneStatus": {"integrationBranch": "experimental"}},
    ],
    ids=["lean-1", "1.x-latestCode", "1.x-laneStatus"],
)
def test_branch_liveness_ok_on_the_integration_branch_itself(tmp_path, monkeypatch, adapter):
    # An integration branch is routinely the HEAD of merged release/promotion PRs (this repo's
    # own #572: experimental -> main), so "its PR is merged" is business as usual there -- not a
    # dead lane. Without the exemption every session on the integration branch reports a FINDING
    # forever, and a control that cries wolf on every session reports nothing.
    repo = _init_repo(tmp_path / "repo", branch="experimental")
    (repo / ".tautline.json").write_text(json.dumps(adapter), encoding="utf-8")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")

    def _no_gh_call(*_a, **_k):
        raise AssertionError("the integration-branch exemption must not spend a gh call")

    monkeypatch.setattr(doctor, "_run", _no_gh_call)
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.OK
    assert "integration branch" in result.detail


def test_branch_liveness_same_name_without_adapter_still_checks(tmp_path, monkeypatch):
    # No adapter -> no exemption: a branch merely NAMED like an integration branch in a repo
    # with no .tautline.json keeps the real liveness check.
    repo = _init_repo(tmp_path / "repo", branch="experimental")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        doctor, "_run", lambda *_a, **_k: (0, json.dumps([{"number": 9, "state": "MERGED", "url": "https://x"}]), "")
    )
    result = doctor.check_branch_liveness(repo)
    assert result.status == doctor.FINDING


# --- b. framework-staleness -------------------------------------------------------------------


def test_framework_staleness_unknown_when_repo_is_none():
    result = doctor.check_framework_staleness(None)
    assert result.status == doctor.UNKNOWN
    assert "not resolved" in result.detail


def test_framework_staleness_unknown_when_not_a_git_checkout(tmp_path):
    not_repo = tmp_path / "snapshot"
    not_repo.mkdir()
    result = doctor.check_framework_staleness(not_repo)
    assert result.status == doctor.UNKNOWN
    assert "not a git checkout" in result.detail


def test_framework_staleness_unknown_when_no_upstream(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote=None)
    result = doctor.check_framework_staleness(repo)
    assert result.status == doctor.UNKNOWN
    assert "no upstream" in result.detail


def test_framework_staleness_unknown_when_remote_unreachable(tmp_path):
    origin = _init_repo(tmp_path / "origin", remote=None)
    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", str(origin), str(checkout))
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "nowhere-doctor-test"))
    result = doctor.check_framework_staleness(checkout)
    assert result.status == doctor.UNKNOWN
    assert "could not reach" in result.detail


def test_framework_staleness_ok_when_up_to_date(tmp_path):
    origin = _init_repo(tmp_path / "origin", remote=None)
    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", str(origin), str(checkout))
    result = doctor.check_framework_staleness(checkout)
    assert result.status == doctor.OK
    assert "up to date" in result.detail


def test_framework_staleness_unknown_when_origin_moved_but_not_fetched(tmp_path):
    origin = _init_repo(tmp_path / "origin", remote=None)
    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", str(origin), str(checkout))
    _commit(origin, "two.txt", "two\n", "second commit")
    result = doctor.check_framework_staleness(checkout)
    assert result.status == doctor.UNKNOWN
    assert "not fetched locally" in result.detail


def test_framework_staleness_finding_when_behind_and_fetched(tmp_path):
    origin = _init_repo(tmp_path / "origin", remote=None)
    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", str(origin), str(checkout))
    _commit(origin, "two.txt", "two\n", "second commit")
    _commit(origin, "three.txt", "three\n", "third commit")
    _git(checkout, "fetch", "origin")  # populate objects only -- HEAD/branch untouched, matching a
    # real "someone fetched but hasn't merged" state; check_framework_staleness itself never fetches.
    result = doctor.check_framework_staleness(checkout)
    assert result.status == doctor.FINDING
    assert "behind" in result.detail
    assert "by 2 commit(s)" in result.detail


# --- c. skip-lint ------------------------------------------------------------------------------


def test_skip_lint_ok_with_no_markers():
    diff_text = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-old = 1\n+new = 2\n"
    result = doctor.check_skip_lint(Path("."), "origin/main", diff_text=diff_text)
    assert result.status == doctor.OK
    assert "origin/main" in result.detail


def test_skip_lint_ignores_removed_and_context_lines():
    diff_text = (
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,3 +1,2 @@\n"
        " context_line_mentions_pytest.mark.skip_but_unchanged = 1\n"
        "-@pytest.mark.skip\n"
        "+plain_line_no_marker = 2\n"
    )
    result = doctor.check_skip_lint(Path("."), "origin/main", diff_text=diff_text)
    assert result.status == doctor.OK


def test_skip_lint_finding_lists_new_markers():
    diff_text = "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,0 +2,2 @@\n+@pytest.mark.skip\n+def test_thing(): pass\n"
    result = doctor.check_skip_lint(Path("."), "origin/main", diff_text=diff_text)
    assert result.status == doctor.FINDING
    assert "silently disabled coverage" in result.detail
    assert "tests/test_x.py" in result.detail
    assert "@pytest.mark.skip" in result.detail


def test_skip_lint_finding_truncates_long_lists():
    markers = doctor.SKIP_LINT_MARKERS[:10]
    lines = ["+++ b/many.py"] + [f"+{marker} marker_{i}" for i, marker in enumerate(markers)]
    diff_text = "\n".join(lines) + "\n"
    result = doctor.check_skip_lint(Path("."), "origin/main", diff_text=diff_text)
    assert result.status == doctor.FINDING
    assert "+2 more" in result.detail


def test_skip_lint_unknown_when_diff_file_missing(tmp_path):
    result = doctor.check_skip_lint(tmp_path, "origin/main", diff_file=tmp_path / "nope.diff")
    assert result.status == doctor.UNKNOWN
    assert "not found" in result.detail


def test_skip_lint_reads_diff_file(tmp_path):
    diff_file = tmp_path / "the.diff"
    diff_file.write_text("+++ b/x.py\n+@pytest.mark.xfail\n", encoding="utf-8")
    result = doctor.check_skip_lint(tmp_path, "origin/main", diff_file=diff_file)
    assert result.status == doctor.FINDING
    assert "@pytest.mark.xfail" in result.detail


def test_skip_lint_unknown_when_git_diff_fails(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote=None)
    result = doctor.check_skip_lint(repo, base="origin/does-not-exist")
    assert result.status == doctor.UNKNOWN
    assert "could not diff" in result.detail


def test_skip_lint_unknown_on_disjoint_history_never_falls_back_to_two_dot(tmp_path):
    """P1 regression: three-dot (`base...HEAD`) fails with "no merge base" on a disjoint/shallow
    history, and an earlier version silently fell back to a plain two-dot `git diff base` -- a
    DIFFERENT comparison (tip vs tip) that reports nearly the whole unrelated history as "added by
    this branch". `base` here resolves to a real, unrelated commit fetched from a second,
    independent repo (reproducing the reviewer's shallow-clone finding without needing an actual
    shallow clone): the fix must report UNKNOWN, never a diff at all."""
    a = _init_repo(tmp_path / "a", remote=None)
    # NOT _init_repo for `b`: two _init_repo calls commit byte-identical content (same file,
    # message, and author/committer identity+second-resolution timestamp) -- verified to collide on
    # the SAME commit sha, which would make `a`'s HEAD and `unrelated-base` the same commit (or, if
    # `b` grew a second commit on top of it, a genuine ANCESTOR of it) and this fixture would no
    # longer be disjoint at all. A root commit with different content is a different sha with no
    # parent relationship to `a`'s history, guaranteeing a real merge-base failure.
    b = tmp_path / "b"
    b.mkdir()
    _git(b, "init", "-b", "main")
    _git(b, "config", "user.email", "t@example.com")
    _git(b, "config", "user.name", "t")
    (b / "UNRELATED.md").write_text("this history shares nothing with a\n", encoding="utf-8")
    _git(b, "add", "-A")
    _git(b, "commit", "-m", "unrelated root commit")
    _git(a, "fetch", str(b), "main:refs/heads/unrelated-base")

    result = doctor.check_skip_lint(a, base="unrelated-base")

    assert result.status == doctor.UNKNOWN
    assert "no merge base" in result.detail
    assert "unrelated-base" in result.detail


def test_skip_lint_no_false_positive_on_dot_skip_methods():
    """P1 regression: the salvaged "t.skip(" marker substring-matched any `<word ending in
    t>.skip(` -- dropped entirely (see the comment on SKIP_LINT_MARKERS). These are real,
    non-test-framework `.skip(` calls (a pagination/cursor idiom, e.g. MongoDB/RxJS) and must never
    be reported."""
    diff_text = "+++ b/x.py\n+element.skip()\n+count.skip(5)\n+pagination.skip(10)\n"
    result = doctor.check_skip_lint(Path("."), "origin/main", diff_text=diff_text)
    assert result.status == doctor.OK


def test_skip_lint_ok_against_a_real_repo_diff(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote=None)
    _git(repo, "branch", "base-marker", "HEAD")
    _commit(repo, "new.py", "value = 1\n", "add a plain file")
    result = doctor.check_skip_lint(repo, base="base-marker")
    assert result.status == doctor.OK


def test_default_skip_lint_base_reads_adapter(tmp_path):
    (tmp_path / ".tautline.json").write_text(
        json.dumps({"latestCode": {"base": "develop", "remote": "upstream"}}), encoding="utf-8"
    )
    assert doctor._default_skip_lint_base(tmp_path) == "upstream/develop"


def test_default_skip_lint_base_reads_lean_adapter(tmp_path):
    # A lean-1 marker names its base as `integrationBranch` (no latestCode block); falling back
    # to origin/main on a lean lane would diff against a nearly-unrelated history.
    (tmp_path / ".tautline.json").write_text(
        json.dumps({"schemaVersion": "lean-1", "integrationBranch": "experimental"}), encoding="utf-8"
    )
    assert doctor._default_skip_lint_base(tmp_path) == "origin/experimental"


def test_default_skip_lint_base_falls_back_without_adapter(tmp_path):
    assert doctor._default_skip_lint_base(tmp_path) == "origin/main"


def test_default_skip_lint_base_falls_back_on_malformed_adapter(tmp_path):
    (tmp_path / ".tautline.json").write_text("{not json", encoding="utf-8")
    assert doctor._default_skip_lint_base(tmp_path) == "origin/main"


def test_adapter_readers_survive_a_byte_corrupt_adapter(tmp_path):
    # Invalid UTF-8 raises UnicodeDecodeError, not JSONDecodeError; _default_skip_lint_base runs
    # OUTSIDE _safe_check, so anything escaping it kills the whole doctor run.
    (tmp_path / ".tautline.json").write_bytes(b"\xff\xfe{broken")
    assert doctor._default_skip_lint_base(tmp_path) == "origin/main"
    assert doctor._target_integration_branch(tmp_path) is None


# --- d. monitor-liveness ---------------------------------------------------------------------


@pytest.mark.parametrize("spec", ["no-colon-here", "123:", "abc:/tmp/x.log", ":/tmp/x.log"])
def test_monitor_liveness_unknown_on_malformed_spec(spec):
    assert doctor.check_monitor_liveness(spec).status == doctor.UNKNOWN


def test_monitor_liveness_finding_when_pid_dead():
    result = doctor.check_monitor_liveness("123:/tmp/x.log", pid_alive=lambda _pid: False)
    assert result.status == doctor.FINDING
    assert "not running" in result.detail


def test_monitor_liveness_finding_when_log_missing(tmp_path):
    missing = tmp_path / "nope.log"
    result = doctor.check_monitor_liveness(f"123:{missing}", pid_alive=lambda _pid: True)
    assert result.status == doctor.FINDING
    assert "does not exist" in result.detail


def test_monitor_liveness_finding_when_log_stale(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("x", encoding="utf-8")
    mtime = log.stat().st_mtime
    result = doctor.check_monitor_liveness(
        f"123:{log}", pid_alive=lambda _pid: True, stale_after_seconds=10, now=mtime + 100
    )
    assert result.status == doctor.FINDING
    assert "stale" in result.detail


def test_monitor_liveness_ok_when_alive_and_fresh(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("x", encoding="utf-8")
    mtime = log.stat().st_mtime
    result = doctor.check_monitor_liveness(
        f"123:{log}", pid_alive=lambda _pid: True, stale_after_seconds=600, now=mtime + 5
    )
    assert result.status == doctor.OK
    assert "fresh" in result.detail


def test_pid_is_alive_default_implementation():
    assert doctor._pid_is_alive(os.getpid()) is True
    assert doctor._pid_is_alive(-1) is False


# --- doctor_command orchestration --------------------------------------------------------------


def _stub_always_ok(monkeypatch):
    for name in ("check_branch_liveness", "check_framework_staleness", "check_skip_lint"):
        monkeypatch.setattr(doctor, name, lambda *_a, **_k: doctor.CheckResult("x", doctor.OK))


def test_doctor_command_prints_summary_and_each_check_and_always_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "check_branch_liveness", lambda *_a, **_k: doctor.CheckResult("branch-liveness", doctor.OK, "stub"))
    monkeypatch.setattr(
        doctor, "check_framework_staleness", lambda *_a, **_k: doctor.CheckResult("framework-staleness", doctor.FINDING, "stub")
    )
    monkeypatch.setattr(doctor, "check_skip_lint", lambda *_a, **_k: doctor.CheckResult("skip-lint", doctor.UNKNOWN, "stub"))
    args = argparse.Namespace(target=tmp_path, base=None, diff_file=None, watch=[], stale_after="10m")

    code = doctor.doctor_command(args, framework_repo=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert "doctor: 3 checks -- 1 finding, 1 unknown, 1 ok" in out
    assert "branch-liveness: OK -- stub" in out
    assert "framework-staleness: FINDING -- stub" in out
    assert "skip-lint: UNKNOWN -- stub" in out


def test_doctor_command_survives_a_check_raising(tmp_path, monkeypatch, capsys):
    def _boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(doctor, "check_branch_liveness", _boom)
    monkeypatch.setattr(doctor, "check_framework_staleness", lambda *_a, **_k: doctor.CheckResult("framework-staleness", doctor.OK))
    monkeypatch.setattr(doctor, "check_skip_lint", lambda *_a, **_k: doctor.CheckResult("skip-lint", doctor.OK))
    args = argparse.Namespace(target=tmp_path, base=None, diff_file=None, watch=[], stale_after="10m")

    code = doctor.doctor_command(args, framework_repo=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert "branch-liveness: UNKNOWN -- internal error: kaboom" in out


def test_doctor_command_watch_rows_only_when_requested(tmp_path, monkeypatch, capsys):
    _stub_always_ok(monkeypatch)
    args_no_watch = argparse.Namespace(target=tmp_path, base=None, diff_file=None, watch=[], stale_after="10m")
    doctor.doctor_command(args_no_watch, framework_repo=tmp_path)
    assert "monitor-liveness" not in capsys.readouterr().out

    (tmp_path / "a.log").write_text("x", encoding="utf-8")
    args_watch = argparse.Namespace(
        target=tmp_path,
        base=None,
        diff_file=None,
        watch=[f"{os.getpid()}:{tmp_path / 'a.log'}", "999999:/nonexistent-doctor-test.log"],
        stale_after="10m",
    )
    code = doctor.doctor_command(args_watch, framework_repo=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("monitor-liveness") == 2
    assert "999999" in out


def test_doctor_command_bad_stale_after_reports_unknown_not_crash(tmp_path, monkeypatch, capsys):
    _stub_always_ok(monkeypatch)
    args = argparse.Namespace(
        target=tmp_path, base=None, diff_file=None, watch=["123:/tmp/x.log"], stale_after="not-a-duration"
    )

    code = doctor.doctor_command(args, framework_repo=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert "UNKNOWN -- --stale-after:" in out


def test_doctor_command_defaults_framework_repo_when_not_injected(tmp_path, monkeypatch, capsys):
    """No `framework_repo=` given -> falls back to `_default_framework_repo()` rather than crashing."""
    _stub_always_ok(monkeypatch)
    monkeypatch.setattr(doctor, "_default_framework_repo", lambda: tmp_path)
    args = argparse.Namespace(target=tmp_path, base=None, diff_file=None, watch=[], stale_after="10m")

    code = doctor.doctor_command(args)

    assert code == 0


# --- cli.py wrapper delegation (in-process; no network) ----------------------------------------


def test_cli_doctor_wrapper_injects_canonical_methodology_repo(tmp_path, monkeypatch, cli):
    monkeypatch.setattr(cli, "canonical_methodology_repo", lambda: tmp_path)
    captured = {}

    def fake_doctor_command(args, *, framework_repo=None):
        captured["framework_repo"] = framework_repo
        captured["target"] = args.target
        return 0

    monkeypatch.setattr(doctor, "doctor_command", fake_doctor_command)
    args = argparse.Namespace(target=Path("."), base=None, diff_file=None, watch=[], stale_after="10m")

    assert cli.doctor(args) == 0
    assert captured["framework_repo"] == tmp_path


def test_cli_red_green_check_wrapper_delegates(tmp_path, monkeypatch, cli):
    captured = {}

    def fake_red_green_command(args):
        captured["file"] = args.file
        return 0

    monkeypatch.setattr(doctor, "red_green_check_command", fake_red_green_command)
    args = argparse.Namespace(target=tmp_path, file=tmp_path / "f.py", test_command="true")

    assert cli.red_green_check(args) == 0
    assert captured["file"] == tmp_path / "f.py"


# --- CLI wiring smoke tests (subprocess, --help only for `doctor` -- see module docstring for why
#     `doctor` is never executed via subprocess in this file) ----------------------------------


def test_doctor_and_red_green_check_help_via_cli(run_cli):
    result = run_cli("doctor", "--help")
    assert result.returncode == 0, result.stderr
    assert "--watch" in result.stdout
    assert "--stale-after" in result.stdout
    assert "--base" in result.stdout

    result2 = run_cli("red-green-check", "--help")
    assert result2.returncode == 0, result2.stderr
    assert "--test-command" in result2.stdout
    assert "--file" in result2.stdout
    assert "--timeout" in result2.stdout


# --- generate_mutations / mutation_outcome (pure) -----------------------------------------------


def test_generate_mutations_skips_comments_and_takes_first_occurrence_per_rule():
    source = "# return True\nif a == b:\n    return True\nelse:\n    return False\n"
    mutants = doctor.generate_mutations(source)
    by_label = dict(mutants)
    assert "return True -> return False" in by_label
    mutated = by_label["return True -> return False"]
    assert mutated.startswith("# return True\n")  # the comment line is untouched
    assert "    return False\nelse:\n    return False\n" in mutated  # the real occurrence flipped


def test_generate_mutations_empty_when_nothing_applies():
    assert doctor.generate_mutations("x = 1\ny = 2\n") == []


@pytest.mark.parametrize(
    "exit_code, output, expected",
    [
        (0, "", "survived"),
        (1, "1 failed, 1 passed\nAssertionError: boom", "killed"),
        (1, "ModuleNotFoundError: no module named x", "error"),
        (124, "command timed out after 600s", "timeout"),
        (124, "", "timeout"),
    ],
)
def test_mutation_outcome_classification(exit_code, output, expected):
    assert doctor.mutation_outcome(exit_code, output) == expected


# --- red_green_check_command --------------------------------------------------------------------


def test_red_green_file_not_found(tmp_path, capsys):
    args = argparse.Namespace(target=tmp_path, file=tmp_path / "nope.py", test_command="true")
    code = doctor.red_green_check_command(args)
    assert code == 0
    assert "file not found" in capsys.readouterr().out


def test_red_green_refuses_when_a_backup_already_exists(tmp_path, capsys):
    """CRITICAL regression: a run killed mid-mutation leaves file=mutated, backup=true-original. A
    naive second run used to read the (mutated) file as "original", overwrite the true-original
    backup with it, then delete that corrupted backup on its own clean exit -- the true original
    became unrecoverable. The fix refuses outright: neither file is read or touched, and both stay
    exactly as a crashed first run left them, so the true original in the backup is still there for
    a human to restore by hand."""
    f = tmp_path / "toy.py"
    mutated_looking_content = "def g(a, b):\n    return a != b\n"  # what a crashed run left behind
    f.write_text(mutated_looking_content, encoding="utf-8")
    backup = doctor._backup_path(f)
    true_original = "def g(a, b):\n    return a == b\n"
    backup.write_text(true_original, encoding="utf-8")

    args = argparse.Namespace(target=tmp_path, file=f, test_command="true")
    code = doctor.red_green_check_command(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "a previous run left" in out
    assert str(backup) in out
    assert "restore from the backup" in out
    assert f.read_text(encoding="utf-8") == mutated_looking_content  # untouched
    assert backup.read_text(encoding="utf-8") == true_original  # untouched -- still recoverable


def test_red_green_no_applicable_mutation(tmp_path, capsys):
    f = tmp_path / "flat.py"
    f.write_text("x = 1\n", encoding="utf-8")
    args = argparse.Namespace(target=tmp_path, file=f, test_command="true")

    code = doctor.red_green_check_command(args)

    assert code == 0
    assert "no applicable single-symbol mutation" in capsys.readouterr().out
    assert f.read_text(encoding="utf-8") == "x = 1\n"


def test_red_green_baseline_not_green(tmp_path, monkeypatch, capsys):
    f = tmp_path / "toy.py"
    original = "def g():\n    return True\n"
    f.write_text(original, encoding="utf-8")
    monkeypatch.setattr(doctor, "_run", lambda *_a, **_k: (1, "", "boom"))
    args = argparse.Namespace(target=tmp_path, file=f, test_command="anything")

    code = doctor.red_green_check_command(args)

    assert code == 0
    assert "baseline test command is not green" in capsys.readouterr().out
    assert f.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(f).exists()


def test_red_green_inconclusive_timeout_when_a_mutation_times_out(tmp_path, monkeypatch, capsys):
    """P1 regression (message-composition, mocked for speed -- see the real-subprocess variants
    below for proof that --timeout is actually threaded to the subprocess calls). A timed-out
    mutation must be scored neither killed nor survived, and the final report must say why."""
    f = tmp_path / "toy.py"
    original = "def g(a, b):\n    return a == b\n"
    f.write_text(original, encoding="utf-8")
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return (0, "", "")  # baseline green
        return (124, "", "command timed out after 1s")  # the one mutation times out

    monkeypatch.setattr(doctor, "_run", fake_run)
    args = argparse.Namespace(target=tmp_path, file=f, test_command="anything", timeout=1)

    code = doctor.red_green_check_command(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "red_green_mutation:" in out and "-> timeout" in out
    assert "inconclusive" in out and "timeout" in out
    assert f.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(f).exists()


def test_red_green_inconclusive_when_every_mutation_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "toy.py"
    original = "def g(a, b):\n    return a == b\n"
    f.write_text(original, encoding="utf-8")
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return (0, "", "")  # baseline green
        return (1, "", "SyntaxError: invalid syntax")  # tooling failure, no assertion evidence

    monkeypatch.setattr(doctor, "_run", fake_run)
    args = argparse.Namespace(target=tmp_path, file=f, test_command="anything")

    code = doctor.red_green_check_command(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "inconclusive" in out
    assert f.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(f).exists()


def test_red_green_backup_holds_original_while_file_is_mutated(tmp_path, monkeypatch):
    """Proves the COPY-guard concretely: while a mutation is in flight, the working file holds the
    MUTATED text and the on-disk backup holds the ORIGINAL -- the recovery path a crash that skips
    the `finally` restore would need."""
    f = tmp_path / "toy.py"
    original = "def g(a, b):\n    return a == b\n"
    f.write_text(original, encoding="utf-8")
    observed = {}
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return (0, "", "")  # baseline green
        observed["file_during_mutation"] = f.read_text(encoding="utf-8")
        observed["backup_during_mutation"] = doctor._backup_path(f).read_text(encoding="utf-8")
        return (0, "", "")  # 'survived' -- ends the loop right after we capture state

    monkeypatch.setattr(doctor, "_run", fake_run)
    args = argparse.Namespace(target=tmp_path, file=f, test_command="anything")

    doctor.red_green_check_command(args)

    assert observed["file_during_mutation"] != original
    assert observed["backup_during_mutation"] == original


def test_red_green_restores_on_crash_mid_mutation(tmp_path, monkeypatch, capsys):
    """The finally-restore path, proved under a crash mid-flight: `_run` raises on the FIRST
    mutation attempt (after a green baseline), simulating the test run dying mid-mutation. The
    `finally` block must still restore the original and clean up the backup before the outer
    always-exit-0 handler reports the internal error."""
    f = tmp_path / "toy.py"
    original = "def g(a, b):\n    return a == b\n"
    f.write_text(original, encoding="utf-8")
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return (0, "", "")  # baseline green
        raise RuntimeError("simulated crash mid-mutation")

    monkeypatch.setattr(doctor, "_run", fake_run)
    args = argparse.Namespace(target=tmp_path, file=f, test_command="anything")

    code = doctor.red_green_check_command(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "internal error" in out
    assert f.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(f).exists()


def test_red_green_kills_a_real_mutation_end_to_end(tmp_path):
    """A genuine toy module + a genuine (Python subprocess) test command: proves the whole
    discrimination proof, not just the classification helper."""
    toy = tmp_path / "toy_killed.py"
    original = "def check(n):\n    if n == 5:\n        return True\n    return False\n"
    toy.write_text(original, encoding="utf-8")
    test_command = (
        f"{sys.executable} -c \"import sys; sys.path.insert(0, '.'); import toy_killed as m; "
        "assert m.check(5) == True\""
    )
    args = argparse.Namespace(target=tmp_path, file=toy, test_command=test_command)

    code = doctor.red_green_check_command(args)

    assert code == 0
    assert toy.read_text(encoding="utf-8") == original


def test_red_green_survives_a_useless_test_command_end_to_end(tmp_path):
    toy = tmp_path / "toy_survive.py"
    original = "def flag(a, b):\n    x = a == b\n    return x\n"
    toy.write_text(original, encoding="utf-8")
    args = argparse.Namespace(target=tmp_path, file=toy, test_command="true")

    code = doctor.red_green_check_command(args)

    assert code == 0
    assert toy.read_text(encoding="utf-8") == original


def test_red_green_baseline_timeout_end_to_end(tmp_path, capsys):
    """P1 regression, real subprocess: proves --timeout is actually threaded to the baseline `_run`
    call (a mocked `_run` would silently accept a missing `timeout=` kwarg and prove nothing). A
    hanging baseline must be killed within --timeout, not left to run forever."""
    f = tmp_path / "toy.py"
    original = "def g():\n    return True\n"
    f.write_text(original, encoding="utf-8")
    args = argparse.Namespace(target=tmp_path, file=f, test_command="sleep 30", timeout=1)

    code = doctor.red_green_check_command(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "baseline test command timed out" in out
    assert f.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(f).exists()


def test_red_green_mutation_timeout_end_to_end(tmp_path, capsys):
    """P1 regression, real subprocess + a real infinite loop: the ORIGINAL never enters the loop
    (`i == -1` is false from i=0), so the baseline is instant; the one applicable mutation
    (`== -> !=`) makes the loop condition always true, hanging forever. Proves --timeout is threaded
    to the per-mutation `_run` call too, and that a killed mutation run still restores the file.

    `-B` (no .pyc writing) is load-bearing, not decoration: "==" -> "!=" is a same-length edit, so
    the mutated file keeps the original's exact size and can land within the same mtime-resolution
    window. Without `-B`, the baseline run's cached bytecode can satisfy Python's (mtime, size)
    staleness check for the MUTATED source too, and the "hanging" run silently executes the
    original's fast bytecode instead -- reproduced while writing this test: the mutation was
    scored 'survived' in under a second, not 'timeout'.
    """
    toy = tmp_path / "toy_spin.py"
    original = "def spin(n):\n    i = 0\n    while i == -1:\n        i += 1\n    return n\n"
    toy.write_text(original, encoding="utf-8")
    test_command = (
        f"{sys.executable} -B -c \"import sys; sys.path.insert(0, '.'); import toy_spin as m; "
        "assert m.spin(5) == 5\""
    )
    args = argparse.Namespace(target=tmp_path, file=toy, test_command=test_command, timeout=1)

    code = doctor.red_green_check_command(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "red_green_mutation:" in out and "-> timeout" in out
    assert "inconclusive" in out and "timeout" in out
    assert toy.read_text(encoding="utf-8") == original
    assert not doctor._backup_path(toy).exists()


def test_red_green_check_cli_end_to_end(run_cli, tmp_path):
    toy = tmp_path / "toy.py"
    original = "def check(n):\n    if n == 5:\n        return True\n    return False\n"
    toy.write_text(original, encoding="utf-8")
    test_command = (
        f"{sys.executable} -c \"import sys; sys.path.insert(0,'.'); import toy; assert toy.check(5) == True\""
    )

    result = run_cli(
        "red-green-check",
        "--target",
        str(tmp_path),
        "--file",
        str(toy),
        "--test-command",
        test_command,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "red_green: pass" in result.stdout
    assert toy.read_text(encoding="utf-8") == original
