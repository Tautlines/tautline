"""T5 (0.8.9 startup remediation): the review-evidence pre-push coordination allowance.

See .superpowers/sdd/task-089-T5-brief.md ("Secondary deadlock -- review-evidence pre-push
coordination allowance (brief option b), with an explicit scope boundary" -- the normative design
section every clause here traces back to) and task-089-T5-report.md for the TDD transcript.
"""

import subprocess
from pathlib import Path

ZERO_SHA = "0" * 40


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")


def _write(repo: Path, rel: str, content: str = "content\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _data(*, review_base: str | None = None, contract="lane-contract.json", board="lane-board.json", status_dir="lane-status", root="coordination-root") -> dict:
    review: dict = {}
    if review_base:
        review["codexWrapper"] = f"codex review --base {review_base}"
    return {
        "laneState": {"runsDir": ".ai-runs"},
        "review": review,
        "laneCoordination": {
            "root": root,
            "contractPath": contract,
            "boardPath": board,
            "laneStatusDir": status_dir,
        },
    }


def _set_records_file(monkeypatch, tmp_path: Path, records: list[tuple[str, str, str, str]]) -> Path:
    records_path = tmp_path / "prepush-records.txt"
    records_path.write_text("\n".join(" ".join(r) for r in records) + ("\n" if records else ""), encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PREPUSH_RECORDS_FILE", str(records_path))
    return records_path


# --- coordination-only single-ref range -------------------------------------------------------


def test_coordination_only_single_ref_range_passes(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is True


def test_json_contract_and_board_at_exact_resolved_path_passes(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "lane-contract.json", '{"contract": true}\n')
    _write(repo, "lane-board.json", '{"board": true}\n')
    head_sha = _commit(repo, "contract + board update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is True


# --- first-push (zero remote sha) cases --------------------------------------------------------


def test_first_push_zero_sha_default_base_evaluates_only_coordination_commit(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-qb", "feature/coord-only")
    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/feature/coord-only", head_sha, "refs/heads/feature/coord-only", ZERO_SHA)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is True


def test_first_push_zero_sha_non_main_configured_base_evaluates_only_coordination_commit(cli, monkeypatch, tmp_path):
    """this repo's own flow: review base is origin/experimental, not origin/main. A branch built
    on top of experimental must be diffed against experimental, not main -- otherwise the
    experimental-only commit would leak into the range and incorrectly gate the push."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-qb", "experimental")
    _write(repo, "experimental.txt", "experimental-only change\n")
    experimental_sha = _commit(repo, "experimental baseline")
    _git(repo, "update-ref", "refs/remotes/origin/experimental", experimental_sha)

    _git(repo, "checkout", "-qb", "feature/coord-only")
    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/feature/coord-only", head_sha, "refs/heads/feature/coord-only", ZERO_SHA)])

    data = _data(review_base="origin/experimental")
    assert cli.review_evidence_coordination_allowance(data, repo) is True

    # sanity: had the (wrong) default base origin/main been used, the range would also include
    # experimental.txt and must NOT pass -- prove the distinction is real, not incidental.
    wrong_base_changed = cli.review_evidence_coordination_changed_paths(repo, base_sha, head_sha)
    assert "experimental.txt" in wrong_base_changed


# --- smuggle / scope-boundary tests ------------------------------------------------------------


def test_smuggle_coordination_note_plus_source_file_is_gated(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    _write(repo, "src/app.py", "print('smuggled')\n")
    head_sha = _commit(repo, "smuggle attempt")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_non_coordination_markdown_under_root_but_outside_artifact_paths_is_gated(cli, monkeypatch, tmp_path):
    """laneCoordination.root may be a broad org/project directory holding ordinary docs/plans; a
    root-scoped allowance would let unreviewed content bypass evidence."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "coordination-root/plans/some-plan.md", "# Plan\n")
    head_sha = _commit(repo, "plan update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_rename_smuggle_source_file_into_coordination_md_path_is_gated(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "src/app.py", "print('hi')\n")
    base_sha = _commit(repo, "base")

    (repo / "lane-status").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "src/app.py", "lane-status/app.md")
    head_sha = _commit(repo, "rename into coordination path")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_symlink_at_non_coordination_path_pointing_into_status_dir_is_gated(cli, monkeypatch, tmp_path):
    """Codex T7 R1 P2: classification must apply to the Git path itself (lexically), not its
    symlink-resolved target -- a src/ symlink pointing at a lane-status artifact must not ride
    the coordination allowance past Stage 2 review."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    (repo / "src").mkdir()
    (repo / "src" / "smuggle.md").symlink_to(Path("..") / "lane-status" / "lane-1.md")
    head_sha = _commit(repo, "symlink smuggle")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


# --- multi-ref pushes: fail closed for the allowance regardless of content ---------------------


def test_multi_ref_coordination_plus_source_receives_no_allowance(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    coord_sha = _commit(repo, "coordination-only")

    _write(repo, "src/app.py", "print('x')\n")
    source_sha = _commit(repo, "source change")

    _set_records_file(
        monkeypatch,
        tmp_path,
        [
            ("refs/heads/coord", coord_sha, "refs/heads/coord", base_sha),
            ("refs/heads/source", source_sha, "refs/heads/source", coord_sha),
        ],
    )

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_multi_ref_two_coordination_only_refs_receives_no_allowance(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "lane-status/lane-1.md", "# Lane Status 1\n")
    coord1_sha = _commit(repo, "coordination-only 1")

    _write(repo, "lane-status/lane-2.md", "# Lane Status 2\n")
    coord2_sha = _commit(repo, "coordination-only 2")

    _set_records_file(
        monkeypatch,
        tmp_path,
        [
            ("refs/heads/coord1", coord1_sha, "refs/heads/coord1", base_sha),
            ("refs/heads/coord2", coord2_sha, "refs/heads/coord2", coord1_sha),
        ],
    )

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


# --- no-merge-base fallback: allowance does not apply, gate evaluates as today ------------------


def test_no_merge_base_no_shared_ref_and_no_configured_base_falls_back_to_todays_gating(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "coord-only-branch")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")
    # no main/master/origin refs of any kind exist and no configured review base ->
    # git_shared_base_refs() is empty -> no candidate base to merge-base against.

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/coord-only-branch", head_sha, "refs/heads/coord-only-branch", ZERO_SHA)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_no_merge_base_unrelated_history_falls_back_to_todays_gating(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "rm", "-rq", "--cached", ".")
    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "unrelated coordination-only commit")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/unrelated", head_sha, "refs/heads/unrelated", ZERO_SHA)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


# --- root-resolution failure: fail closed -------------------------------------------------------


def test_root_resolution_failure_fails_closed(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    # No "laneCoordination" key at all -> lane_coordination_paths() raises -> fail closed.
    data = {"laneState": {"runsDir": ".ai-runs"}, "review": {}}
    assert cli.review_evidence_coordination_allowance(data, repo) is False


# --- backward-compatible handshake: old-template simulation -------------------------------------


def test_no_records_file_env_var_reads_nothing_from_stdin_old_template_simulation(cli, monkeypatch, tmp_path):
    """A NOT-YET-REGENERATED installed hook never sets MINERVIT_PREPUSH_RECORDS_FILE. Even when
    the repo state WOULD be coordination-only if evaluated, the allowance must not activate --
    today's HEAD-based gating is preserved exactly."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    _commit(repo, "lane status update")

    monkeypatch.delenv("MINERVIT_PREPUSH_RECORDS_FILE", raising=False)

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_missing_records_file_fails_closed(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    _commit(repo, "base")
    monkeypatch.setenv("MINERVIT_PREPUSH_RECORDS_FILE", str(tmp_path / "does-not-exist.txt"))

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_malformed_record_line_fails_closed(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    _commit(repo, "base")
    records_path = tmp_path / "prepush-records.txt"
    records_path.write_text("not-a-valid-record-line\n", encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PREPUSH_RECORDS_FILE", str(records_path))

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


def test_deletion_push_local_sha_zero_receives_no_allowance(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")

    _set_records_file(monkeypatch, tmp_path, [("(delete)", ZERO_SHA, "refs/heads/gone", base_sha)])

    data = _data()
    assert cli.review_evidence_coordination_allowance(data, repo) is False


# --- wiring: review_evidence_check itself ------------------------------------------------------


def _args(cli, target: Path, *, strict=True, base=None):
    import argparse

    return argparse.Namespace(project=None, target=target, strict=strict, scope_strict=False, base=base)


def test_review_evidence_check_passes_via_coordination_allowance_without_manifests(cli, monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))

    rc = cli.review_evidence_check(_args(cli, repo))

    assert rc == 0
    out = capsys.readouterr().out
    assert "review_evidence_check: pass - coordination-only outgoing range" in out


def test_review_evidence_check_smuggle_still_gated_through_full_check(cli, monkeypatch, tmp_path, capsys):
    """The allowance must not fire for a mixed range; the ORDINARY evidence-manifest gate then
    runs and fails exactly as it does today (no .impl-reviews evidence dir exists)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    _write(repo, "src/app.py", "print('smuggled')\n")
    head_sha = _commit(repo, "smuggle attempt")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))

    rc = cli.review_evidence_check(_args(cli, repo))

    assert rc == 1
    err = capsys.readouterr().err
    assert "review_evidence_check: pass - coordination-only" not in err
    assert "review evidence" in err.lower() or "review_evidence" in err


def test_review_evidence_check_characterization_unchanged_when_no_records_file(cli, monkeypatch, tmp_path, capsys):
    """Per-ref evidence semantics beyond the allowance are pinned UNCHANGED: with no
    MINERVIT_PREPUSH_RECORDS_FILE set (baseline/pre-T5 behavior), the ordinary HEAD-based gate
    runs exactly as it did before this release, even for a coordination-only diff."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    _commit(repo, "lane status update")

    monkeypatch.delenv("MINERVIT_PREPUSH_RECORDS_FILE", raising=False)

    data = _data()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))

    rc = cli.review_evidence_check(_args(cli, repo))

    assert rc == 1
    err = capsys.readouterr().err
    assert "review_evidence_check: pass - coordination-only" not in err
    assert "current outgoing diff has no matching Stage 2 Codex review evidence" in err


# --- wiring: guard-check at the prepush boundary (guard-check wraps review_evidence_check) ------


def test_guard_check_prepush_passes_via_coordination_allowance(cli, monkeypatch, tmp_path, capsys):
    """A direct-only test of review_evidence_coordination_allowance could miss a broken stdin
    handoff through guard-check's dispatch; this proves the allowance through the SAME entry
    point the installed pre-push hook invokes (`guard-check --boundary prepush`)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    head_sha = _commit(repo, "lane status update")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))
    monkeypatch.setattr(cli, "backlog_provider_board_check", lambda args: 0)
    monkeypatch.setattr(cli, "ci_health_check", lambda args: 0)
    # item 37 R2: this file tests the COORDINATION allowance, not test evidence. The lane
    # has no test-run record, so the block-by-default evidence gate would refuse it for a
    # reason unrelated to what is under test -- stubbed exactly like the two checks above.
    monkeypatch.setattr(cli, "test_evidence_enforcement_check", lambda args: 0)

    import argparse

    rc = cli.guard_check(argparse.Namespace(project=None, target=repo, boundary="prepush"))

    assert rc == 0
    out = capsys.readouterr().out
    assert "review_evidence_check: pass - coordination-only outgoing range" in out
    assert "guard_check: ok" in out


def test_guard_check_prepush_still_gates_smuggle(cli, monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _write(repo, "lane-status/lane-1.md", "# Lane Status\n")
    _write(repo, "src/app.py", "print('smuggled')\n")
    head_sha = _commit(repo, "smuggle attempt")

    _set_records_file(monkeypatch, tmp_path, [("refs/heads/main", head_sha, "refs/heads/main", base_sha)])

    data = _data()
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))
    monkeypatch.setattr(cli, "backlog_provider_board_check", lambda args: 0)
    monkeypatch.setattr(cli, "ci_health_check", lambda args: 0)
    # item 37 R2: this file tests the COORDINATION allowance, not test evidence. The lane
    # has no test-run record, so the block-by-default evidence gate would refuse it for a
    # reason unrelated to what is under test -- stubbed exactly like the two checks above.
    monkeypatch.setattr(cli, "test_evidence_enforcement_check", lambda args: 0)

    import argparse

    rc = cli.guard_check(argparse.Namespace(project=None, target=repo, boundary="prepush"))

    assert rc == 1
    err = capsys.readouterr().err
    assert "guard_check_failed: review evidence" in err
