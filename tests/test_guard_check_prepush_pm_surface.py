"""T1: pre-push guard-check scopes the review/CI gate to PM-surface-only branch diffs.

The decision is based on the FULL branch diff against the configured base
(`merge-base(base, local_sha)..local_sha`), NEVER the incremental `remote_sha..local_sha`
range. Every ambiguous/force/multi-ref/non-current-branch/undeterminable push fails closed to
today's full gate. The one failure that matters -- a code-touching push slipping past the review
gate -- must never happen.

Harness mirrors tests/test_review_evidence_prepush_coordination.py (the sibling records-file
gate) so the two pre-push mechanisms stay provably consistent.
"""

import argparse
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_ADAPTER = REPO_ROOT / ".tautline" / "adapter.json"
ZERO_SHA = "0" * 40


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, branch: str = "main") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", branch)
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


def _set_records_file(
    monkeypatch, tmp_path: Path, records: list[tuple[str, str, str, str]]
) -> Path:
    records_path = tmp_path / "prepush-records.txt"
    body = "\n".join(" ".join(r) for r in records)
    records_path.write_text(body + ("\n" if records else ""), encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PREPUSH_RECORDS_FILE", str(records_path))
    return records_path


def _push(monkeypatch, tmp_path, ref: str, local: str, remote: str) -> Path:
    """Set a single-ref pre-push record (`ref local ref remote`) -- the common case."""
    return _set_records_file(monkeypatch, tmp_path, [(ref, local, ref, remote)])


PM_ADAPTER = {"productDevelopment": {"surfaces": ["docs/product/**"]}, "review": {}}


def _run_guard(cli, repo: Path, monkeypatch, adapter=PM_ADAPTER, patch_adapter=True):
    """Invoke guard_check at the prepush boundary with the terminal gates stubbed so we can observe
    exactly which of review/board/ci ran. When patch_adapter is True the committed-tree adapter
    loader is stubbed to `adapter` (isolating the record/range/classifier logic); pass
    patch_adapter=False to exercise the real committed-adapter load + dirty check."""
    calls: list[str] = []

    def rec(label):
        def _f(args):
            calls.append(label)
            return 0

        return _f

    monkeypatch.setattr(cli, "review_evidence_check", rec("review"))
    monkeypatch.setattr(cli, "backlog_provider_board_check", rec("board"))
    monkeypatch.setattr(cli, "ci_health_check", rec("ci"))
    if patch_adapter:
        monkeypatch.setattr(
            cli, "guard_check_prepush_committed_adapter", lambda target, sha: adapter
        )
    rc = cli.guard_check(argparse.Namespace(project=None, target=repo, boundary="prepush"))
    return rc, calls


def _base_repo(repo: Path) -> str:
    """main with a README baseline, registered as origin/main so it is the configured base."""
    _init_repo(repo)
    _write(repo, "README.md", "base\n")
    base_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)
    return base_sha


# --- exemption granted: PM-surfaces-only whole-branch diff -------------------------------------


def test_pm_surfaces_only_single_record_skips_review_and_ci(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _push(monkeypatch, tmp_path, "refs/heads/feature/pm", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert rc == 0
    assert calls == ["board"]  # review + ci skipped, board kept


def test_new_branch_first_push_pm_only_is_exempt(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/new-pm")
    _write(repo, "docs/product/spec.md", "# Spec\n")
    head_sha = _commit(repo, "product spec")

    _push(monkeypatch, tmp_path, "refs/heads/feature/new-pm", head_sha, ZERO_SHA)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert rc == 0
    assert calls == ["board"]


# --- exemption denied: code / mixed / hard-excluded whole-branch diff --------------------------


def test_code_branch_diff_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/code")
    _write(repo, "src/app.py", "print('x')\n")
    head_sha = _commit(repo, "code change")

    _push(monkeypatch, tmp_path, "refs/heads/feature/code", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_mixed_branch_diff_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/mixed")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    _write(repo, "src/app.py", "print('x')\n")
    head_sha = _commit(repo, "mixed change")

    _push(monkeypatch, tmp_path, "refs/heads/feature/mixed", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_hard_excluded_plan_path_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/plan")
    _write(repo, "docs/superpowers/plans/some-plan.md", "# Plan\n")
    head_sha = _commit(repo, "plan change")

    _push(monkeypatch, tmp_path, "refs/heads/feature/plan", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_new_branch_first_push_with_code_not_exempt(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/new-code")
    _write(repo, "docs/product/spec.md", "# Spec\n")
    _write(repo, "src/app.py", "print('x')\n")
    head_sha = _commit(repo, "spec + code")

    _push(monkeypatch, tmp_path, "refs/heads/feature/new-code", head_sha, ZERO_SHA)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


# --- the laundering regression: docs-only increment on a branch that already carries code ------


def test_existing_branch_with_code_not_exempt_on_docs_increment(cli, monkeypatch, tmp_path):
    """A code commit already sits on the branch above the base; the newly pushed increment is
    docs-only. Classifying the FULL branch diff (not remote..local) keeps this NON-exempt so the
    unreviewed code cannot be laundered past the gate."""
    repo = tmp_path / "repo"
    _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/launder")
    _write(repo, "src/app.py", "print('x')\n")
    code_sha = _commit(repo, "code commit (already on branch)")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "docs-only increment")

    # remote already has the code commit; the pushed increment code_sha..head_sha is docs-only.
    _push(monkeypatch, tmp_path, "refs/heads/feature/launder", head_sha, code_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


# --- rename carrying a code path (--no-renames) -----------------------------------------------


def test_rename_code_to_pm_surface_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "src/app.py", "print('x')\n")
    base_sha = _commit(repo, "base with code")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-qb", "feature/rename")
    (repo / "docs" / "product").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "src/app.py", "docs/product/app.md")
    head_sha = _commit(repo, "rename code into pm surface")

    _push(monkeypatch, tmp_path, "refs/heads/feature/rename", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    # --no-renames keeps the deleted src/app.py path -> hard-excluded -> full gate.
    assert calls == ["review", "board", "ci"]


# --- fail-closed ambiguity: multi-ref / delete / tag / force / non-current / undeterminable ----


def test_multi_ref_push_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/multi")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _set_records_file(
        monkeypatch,
        tmp_path,
        [
            ("refs/heads/feature/multi", head_sha, "refs/heads/feature/multi", base_sha),
            ("refs/heads/other", head_sha, "refs/heads/other", ZERO_SHA),
        ],
    )

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_branch_delete_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    _commit(repo, "product docs")

    # a branch DELETE carries an all-zero local_sha (a refs/heads ref, so the zero-local guard --
    # not the non-branch guard -- is what fails it closed).
    _push(monkeypatch, tmp_path, "refs/heads/gone", ZERO_SHA, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_tag_ref_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _push(monkeypatch, tmp_path, "refs/tags/v1", head_sha, ZERO_SHA)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_branch_to_tag_push_runs_full_gate(cli, monkeypatch, tmp_path):
    # local_ref is a branch but remote_ref is a TAG (`git push origin feature/pm:refs/tags/v1`):
    # a PM-only diff must still fail closed to the full gate because the remote ref is not a branch.
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _set_records_file(
        monkeypatch,
        tmp_path,
        [("refs/heads/feature/pm", head_sha, "refs/tags/v1", base_sha)],
    )

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_same_sha_non_current_branch_push_runs_full_gate(cli, monkeypatch, tmp_path):
    # `git push origin other` while checked out on feature/pm, where `other` points at the SAME
    # commit as HEAD: local_sha == HEAD is true, but local_ref is not the current branch, so the
    # exemption must fail closed to the full gate (local_ref != the current symbolic branch ref).
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")
    _git(repo, "branch", "other", head_sha)  # a second branch at the same commit; stay on feature/pm

    _push(monkeypatch, tmp_path, "refs/heads/other", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_explicit_project_supplied_fails_closed(cli, monkeypatch, tmp_path):
    # When an explicit --project is supplied, the review/board/CI gates run against THAT adapter;
    # the PM-surface skip must fail closed rather than evaluate the exemption off a different
    # committed adapter. With no --project (the hook path) the SAME push is exempt -- the project
    # guard is the only difference.
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")
    _push(monkeypatch, tmp_path, "refs/heads/feature/pm", head_sha, base_sha)
    monkeypatch.setattr(cli, "guard_check_prepush_committed_adapter", lambda t, s: PM_ADAPTER)

    assert cli.guard_check_prepush_pm_surface_skip(repo, "some/other-adapter.json") is False
    assert cli.guard_check_prepush_pm_surface_skip(repo, None) is True


def test_force_push_non_fast_forward_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    # a divergent remote tip that is NOT an ancestor of head_sha -> non-fast-forward / force.
    _git(repo, "checkout", "-qb", "other", base_sha)
    _write(repo, "other.txt", "diverged\n")
    other_sha = _commit(repo, "diverged remote tip")
    _git(repo, "checkout", "-q", "feature/pm")

    _push(monkeypatch, tmp_path, "refs/heads/feature/pm", head_sha, other_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_non_current_branch_local_sha_not_head_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    # push a NON-checked-out ref: local_sha is base_sha, but HEAD is head_sha.
    _push(monkeypatch, tmp_path, "refs/heads/main", base_sha, ZERO_SHA)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]
    assert base_sha != head_sha


def test_undeterminable_base_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo, branch="work")  # no main/master/origin ref at all
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _push(monkeypatch, tmp_path, "refs/heads/work", head_sha, ZERO_SHA)

    # adapter has no configured review base -> no shared-base ref -> base undeterminable.
    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_absent_records_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    _commit(repo, "product docs")

    monkeypatch.delenv("MINERVIT_PREPUSH_RECORDS_FILE", raising=False)

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


def test_unparseable_records_runs_full_gate(cli, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _base_repo(repo)
    records_path = tmp_path / "prepush-records.txt"
    records_path.write_text("not-a-valid-record\n", encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PREPUSH_RECORDS_FILE", str(records_path))

    rc, calls = _run_guard(cli, repo, monkeypatch)

    assert calls == ["review", "board", "ci"]


# --- records-file contract preserved for the coordination allowance ---------------------------


def test_prepush_records_file_contract_preserved(cli, monkeypatch, tmp_path):
    """The new PM-surface skip and the existing coordination allowance read the SAME
    MINERVIT_PREPUSH_RECORDS_FILE env var. A coordination-only (non-PM) diff is NOT PM-exempt, and
    the records-file path is still resolvable for the coordination allowance."""
    repo = tmp_path / "repo"
    base_sha = _base_repo(repo)
    _git(repo, "checkout", "-qb", "feature/coord")
    _write(repo, "coordination/lanes/lane-1.md", "# Lane\n")
    head_sha = _commit(repo, "coordination note")

    records_path = _push(monkeypatch, tmp_path, "refs/heads/feature/coord", head_sha, base_sha)

    # lane coordination markdown is not under docs/product -> not PM-exempt (fails closed here).
    assert cli.guard_check_prepush_pm_surface_skip(repo, None) is False
    # the same records file the coordination allowance consumes is still resolvable.
    assert cli.review_evidence_prepush_records_file() == records_path


# --- real committed-tree adapter load + dirty-config fail-closed -------------------------------


def _valid_adapter_text(surfaces: list[str]) -> str:
    data = json.loads(SELF_ADAPTER.read_text(encoding="utf-8"))
    data["productDevelopment"] = {"surfaces": surfaces}
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _repo_with_committed_adapter(repo: Path, surfaces: list[str]) -> str:
    _init_repo(repo)
    _write(repo, ".tautline/adapter.json", _valid_adapter_text(surfaces))
    base_sha = _commit(repo, "base with adapter")
    # the self-adapter's configured review base is origin/experimental; register it so the
    # merge-base resolves (not origin/main) -- proves the configured-base resolver is honored.
    _git(repo, "update-ref", "refs/remotes/origin/experimental", base_sha)
    return base_sha


def test_committed_adapter_load_pm_only_skips(cli, monkeypatch, tmp_path):
    """Exercises the REAL committed-tree adapter load (not stubbed): a clean adapter at local_sha
    whose declared surfaces cover a docs/product-only branch diff grants the skip."""
    repo = tmp_path / "repo"
    base_sha = _repo_with_committed_adapter(repo, ["docs/product/**"])
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    _push(monkeypatch, tmp_path, "refs/heads/feature/pm", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch, patch_adapter=False)

    assert rc == 0
    assert calls == ["board"]


def test_dirty_adapter_config_fails_closed(cli, monkeypatch, tmp_path):
    """An UNCOMMITTED widening of the surface config in the worktree must NOT grant the exemption:
    the adapter is read from local_sha and a dirty surface config fails closed to the full gate."""
    repo = tmp_path / "repo"
    base_sha = _repo_with_committed_adapter(repo, ["docs/product/**"])
    _git(repo, "checkout", "-qb", "feature/pm")
    _write(repo, "docs/product/notes.md", "# Notes\n")
    head_sha = _commit(repo, "product docs")

    # dirty the tracked adapter in the worktree AFTER local_sha was committed.
    widened = _valid_adapter_text(["docs/product/**", "docs/product/extra/**"])
    _write(repo, ".tautline/adapter.json", widened)

    _push(monkeypatch, tmp_path, "refs/heads/feature/pm", head_sha, base_sha)

    rc, calls = _run_guard(cli, repo, monkeypatch, patch_adapter=False)

    assert calls == ["review", "board", "ci"]
