"""T5 (0.8.9 startup remediation): backward-compatible stdin handshake for the regenerated
pre-push hook template + the true production path through the installed hook.

See .superpowers/sdd/task-089-T5-brief.md ("Secondary deadlock -- review-evidence pre-push
coordination allowance (brief option b), with an explicit scope boundary").
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


# --- template content assertions (fast, no subprocess) ------------------------------------------


def test_pre_push_template_captures_stdin_and_exports_records_file(cli):
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-push")
    assert "MINERVIT_PREPUSH_RECORDS_FILE=" in content
    assert 'cat > "$MINERVIT_PREPUSH_RECORDS_FILE"' in content
    assert "export MINERVIT_PREPUSH_RECORDS_FILE" in content
    # the capture must happen before any other command that could consume stdin
    capture_index = content.index('cat > "$MINERVIT_PREPUSH_RECORDS_FILE"')
    first_gate_index = content.index("run_minervit_work_profile_check")
    assert capture_index < first_gate_index


def test_pre_commit_template_has_no_stdin_capture(cli):
    """pre-commit never receives ref-update records on stdin, so the capture-and-export block
    (top of the pre-push-only template) must be absent. The shared guarded backup-replay branch
    at the bottom still mentions the variable name textually -- it is dead code for pre-commit
    since the variable is never set, which is exactly the backward-compatible property being
    pinned, not a contradiction."""
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-commit")
    assert 'cat > "$MINERVIT_PREPUSH_RECORDS_FILE"' not in content
    assert "export MINERVIT_PREPUSH_RECORDS_FILE" not in content
    assert 'mktemp "${TMPDIR:-/tmp}/minervit-prepush-records' not in content


def test_backup_invocation_unsets_var_and_replays_records_when_set(cli):
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-push")
    assert 'if [ -n "${MINERVIT_PREPUSH_RECORDS_FILE:-}" ]; then' in content
    assert "unset MINERVIT_PREPUSH_RECORDS_FILE" in content
    # the replay must feed the backup's stdin from the captured file
    assert "< \"$minervit_prepush_records_replay\"" in content


def test_backup_invocation_falls_through_untouched_when_var_absent(cli):
    """pre-commit's template text still contains the guarded replay branch (it is shared code),
    but since pre-commit never sets the variable, the plain unconditional backup call below it is
    what actually runs -- this pins that the plain fallback line is still present and unconditioned
    on hook_name."""
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-commit")
    tail = content[content.index("if [ -x /nonexistent/backup ]"):]
    # plain passthrough call outside the guarded var-is-set branch
    assert tail.count('/nonexistent/backup "$@"') >= 1


# --- old-template simulation: a hand-replicated pre-T5 bottom section --------------------------


def test_old_style_hook_passes_stdin_through_untouched_no_var_set(tmp_path):
    """Characterizes the backward-compatible handshake from the OTHER side: an installed hook
    that predates this release never captures stdin or sets MINERVIT_PREPUSH_RECORDS_FILE, so the
    backup process inherits the original stdin byte-for-byte and never observes the variable --
    exactly today's (pre-T5) behavior."""
    backup = tmp_path / "backup.sh"
    backup.write_text(
        "#!/bin/sh\n"
        'cat > "' + str(tmp_path / "backup-received.txt") + '"\n'
        'printf \'%s\\n\' "${MINERVIT_PREPUSH_RECORDS_FILE+set}" > "' + str(tmp_path / "backup-var-state.txt") + '"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    backup.chmod(0o755)

    old_hook = tmp_path / "old-style-pre-push.sh"
    old_hook.write_text(
        "#!/bin/sh\n"
        "set -u\n"
        f'if [ -x {backup} ]; then\n'
        f'  {backup} "$@"\n'
        "  exit $?\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    old_hook.chmod(0o755)

    records_text = "refs/heads/main abc123 refs/heads/main def456\n"
    result = subprocess.run(
        [str(old_hook), "origin", "git@example.invalid:x.git"],
        input=records_text,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert (tmp_path / "backup-received.txt").read_text(encoding="utf-8") == records_text
    assert (tmp_path / "backup-var-state.txt").read_text(encoding="utf-8").strip() == ""


# --- production path: real render + install + direct hook execution ----------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", "https://example.invalid/example-org/example-saas.git")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")


def _write_evidence(target: Path) -> None:
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")


def _write_adapter(adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    # item 37 R2: this fixture exercises the pre-push STDIN handoff through the production hook
    # path, and the lane has never run a suite. Test-evidence enforcement defaults to block, so
    # leaving it on would refuse this push for a reason unrelated to what is under test -- exactly
    # as ciTestGate above is disabled for the same reason.
    data["testEvidence"] = {**(data.get("testEvidence") or {}), "enforcement": "off"}
    data["backlogProvider"] = {"enabled": False}
    data["stakeholderQuestions"] = {"enabled": False}
    data["milestoneUpdate"] = {"enabled": False}
    data["productChat"] = {"enabled": False}
    data["deploymentNotification"] = {"enabled": False}
    behavior_specs = dict(data.get("behaviorSpecs") or {})
    behavior_specs["required"] = False
    behavior_specs["acceptanceHarnesses"] = []
    data["behaviorSpecs"] = behavior_specs
    document_context = dict(data.get("documentContext") or {})
    document_context["ignoredDocPaths"] = [
        *(document_context.get("ignoredDocPaths") or []),
        "docs/product/backlog",
    ]
    data["documentContext"] = document_context
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for T5 pre-push coordination allowance production-path coverage.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = adapter_root / "t5-hook-coordination.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=90,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _lane(tmp_path: Path, monkeypatch) -> Path:
    """MINERVIT_METHODOLOGY_ADAPTER_ROOT is set via monkeypatch (not a one-off env dict) so it is
    inherited by EVERY subprocess this test spawns, including plain `git commit`/`git push`
    invocations that trigger the newly installed hooks -- exactly how an operator's real shell
    session works."""
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_adapter(adapter_root)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_ADAPTER_ROOT", str(adapter_root))
    target = tmp_path / "target"
    _init_repo(target)
    _write_evidence(target)
    _run("render-adapters", "--project", str(adapter), "--target", str(target), "--write", cwd=target)
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "baseline")
    return target


def _install_hooks_with_recording_backup(cli, target: Path) -> tuple[Path, Path, Path]:
    """Pre-seed a backup pre-push hook BEFORE installing so write_git_branch_liveness_hooks wraps
    it, exactly like an operator's pre-existing custom hook would be wrapped."""
    hooks_dir, error = cli.git_hooks_dir(target)
    assert error is None, error
    hooks_dir.mkdir(parents=True, exist_ok=True)
    pre_push = hooks_dir / "pre-push"
    received = target.parent / "backup-received.txt"
    var_state = target.parent / "backup-var-state.txt"
    pre_push.write_text(
        "#!/bin/sh\n"
        f'cat > "{received}"\n'
        f'printf \'%s\\n\' "${{MINERVIT_PREPUSH_RECORDS_FILE+set}}" > "{var_state}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    pre_push.chmod(0o755)

    installed, errors = cli.write_git_branch_liveness_hooks(target)
    assert not errors, errors
    assert any("wrapped existing pre-push" in item for item in installed), installed
    return hooks_dir / "pre-push", received, var_state


def test_production_hook_path_coordination_only_first_push_passes_and_replays_stdin(cli, tmp_path, monkeypatch):
    target = _lane(tmp_path, monkeypatch)
    pre_push_hook, received_path, var_state_path = _install_hooks_with_recording_backup(cli, target)

    base_sha = _git(target, "rev-parse", "HEAD")
    _git(target, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(target, "checkout", "-qb", "feature/coord-only")
    lane_status_dir = target / ".ai-work" / "lane-status"
    lane_status_dir.mkdir(parents=True, exist_ok=True)
    (lane_status_dir / "lane-1.md").write_text("# Lane Status\n\nBranch: feature/coord-only\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "lane status update")
    head_sha = _git(target, "rev-parse", "HEAD")

    zero_sha = "0" * 40
    records_text = f"refs/heads/feature/coord-only {head_sha} refs/heads/feature/coord-only {zero_sha}\n"

    result = subprocess.run(
        [str(pre_push_hook), "origin", "https://example.invalid/example-org/example-saas.git"],
        cwd=target,
        input=records_text,
        text=True,
        capture_output=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "review_evidence_check: pass - coordination-only outgoing range" in result.stdout
    assert received_path.read_text(encoding="utf-8") == records_text
    assert var_state_path.read_text(encoding="utf-8").strip() == ""


def test_production_hook_path_smuggle_is_gated_and_backup_never_runs(cli, tmp_path, monkeypatch):
    target = _lane(tmp_path, monkeypatch)
    pre_push_hook, received_path, var_state_path = _install_hooks_with_recording_backup(cli, target)

    base_sha = _git(target, "rev-parse", "HEAD")
    _git(target, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(target, "checkout", "-qb", "feature/smuggle")
    lane_status_dir = target / ".ai-work" / "lane-status"
    lane_status_dir.mkdir(parents=True, exist_ok=True)
    (lane_status_dir / "lane-1.md").write_text("# Lane Status\n\nBranch: feature/smuggle\n", encoding="utf-8")
    (target / "src").mkdir(parents=True, exist_ok=True)
    (target / "src" / "app.py").write_text("print('smuggled')\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "smuggle attempt")
    head_sha = _git(target, "rev-parse", "HEAD")

    zero_sha = "0" * 40
    records_text = f"refs/heads/feature/smuggle {head_sha} refs/heads/feature/smuggle {zero_sha}\n"

    result = subprocess.run(
        [str(pre_push_hook), "origin", "https://example.invalid/example-org/example-saas.git"],
        cwd=target,
        input=records_text,
        text=True,
        capture_output=True,
        timeout=90,
    )

    assert result.returncode != 0
    assert "review_evidence_check: pass - coordination-only" not in result.stdout
    # the guard-check gate failed before reaching the wrapped backup hook
    assert not received_path.exists()
    assert not var_state_path.exists()
