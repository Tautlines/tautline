"""T4 (0.8.9 startup remediation): lane-start's `--defer-debt-preflights` flag.

See .superpowers/sdd/task-089-T4-brief.md, the `--defer-debt-preflights` paragraph inside
"Launcher behavior (template change + truthful refusal)". Covers the DEBT-mapped lane-start
preflight writes this task's audit of `lane_start` found (three `return 1` sites plus eight
unguarded settings writes -- see task-089-T4-report.md for the full enumeration):

- the latest-code baseline write (`latest_code_baseline`, `latest_code` debt gate)
- the autocompact settings write (`write_claude_autocompact_settings`, `autocompact` debt gate)
- the ten Claude `*-hook` settings writes (`hook` debt gate; the SessionStart
  standing-directive hook joined the set in 0.13.0)

and the structural counter-case (adapter render failure via `write_generated_files`) that must
NOT degrade even with the flag.

Characterization pins (docstring says "baseline pin"): each was proven to PASS against the
pre-T4 `lane_start` (via `git stash`; see task-089-T4-report.md for the transcript) and is kept
green through the change -- exempt from red-first.
"""

import json
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"
REPO_LOCAL_ADAPTER_REL = ".tautline/adapter.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_adapter(target: Path, mutate=None) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for lane-start --defer-debt-preflights coverage (T4).",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
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
    if mutate:
        mutate(data)
    adapter = target / REPO_LOCAL_ADAPTER_REL
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("primary\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("secondary\n", encoding="utf-8")
    (target / SOURCE_REL).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")


def _start(run_cli, target: Path, adapter: Path, *flags: str) -> subprocess.CompletedProcess:
    return run_cli(
        "lane-start",
        "--project", str(adapter),
        "--target", str(target),
        "--skip-update",
        *flags,
    )


# --- latest-code baseline write ---------------------------------------------------------------


def _break_latest_code(tmp_path: Path, target: Path):
    """Returns a mutate() callback enabling latestCode against a local bare repo with no matching
    base branch, so latest_code_baseline's fetch-then-resolve raises SystemExit deterministically
    with zero network I/O (fast + sandbox-safe -- the fixture's real `origin` remote is an
    unreachable placeholder URL other tests rely on staying untouched)."""
    bare = tmp_path / "latest-code-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True, text=True)
    _git(target, "remote", "add", "latest-code-origin", str(bare))

    def mutate(data):
        data["latestCode"] = {
            "enabled": True,
            "remote": "latest-code-origin",
            "base": "main",
            "statusFile": ".ai-work/latest-code-status.json",
            "maxAgeMinutes": 30,
            "fetchAll": False,
            "includeOpenPrs": False,
            "includeRemoteBranches": False,
            "maxAheadBranches": 25,
            "rule": "test rule: latest-code preflight coverage fixture.",
        }

    return mutate


def test_unflagged_latest_code_failure_still_hard_fails_like_baseline(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    mutate = _break_latest_code(tmp_path, target)
    adapter = _write_adapter(target, mutate)
    result = _start(run_cli, target, adapter)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "latest_code: failed" in result.stdout
    assert "lane_start_warn:" not in result.stdout


def test_flagged_latest_code_failure_warns_and_exits_0(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    mutate = _break_latest_code(tmp_path, target)
    adapter = _write_adapter(target, mutate)
    result = _start(run_cli, target, adapter, "--defer-debt-preflights")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lane_start_warn: latest_code" in result.stdout
    assert "latest_code: failed" not in result.stdout


def _break_latest_code_status_write(tmp_path: Path, target: Path):
    """Codex T7 R1 P2 fixture: latestCode fetch/resolve SUCCEEDS against a local bare twin, but
    the statusFile write raises OSError -- the configured status path's parent is an existing
    FILE, so `path.parent.mkdir(parents=True, exist_ok=True)` raises FileExistsError. Exercises
    the non-SystemExit failure family (read-only .ai-work / path collision) deterministically
    with zero network I/O."""
    bare = tmp_path / "latest-code-origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(bare)],
        check=True, capture_output=True, text=True,
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "seed")
    _git(target, "remote", "add", "latest-code-origin", str(bare))
    _git(target, "push", "-q", "latest-code-origin", "main:main")

    def mutate(data):
        data["latestCode"] = {
            "enabled": True,
            "remote": "latest-code-origin",
            "base": "main",
            # parent is the existing bootstrap-evidence FILE -> mkdir raises FileExistsError
            "statusFile": ".ai-work/bootstrap-evidence.txt/latest-code-status.json",
            "maxAgeMinutes": 30,
            "fetchAll": False,
            "includeOpenPrs": False,
            "includeRemoteBranches": False,
            "maxAheadBranches": 25,
            "rule": "test rule: latest-code status-write failure coverage fixture.",
        }

    return mutate


def test_unflagged_latest_code_status_write_oserror_still_crashes_like_baseline(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    mutate = _break_latest_code_status_write(tmp_path, target)
    adapter = _write_adapter(target, mutate)
    result = _start(run_cli, target, adapter)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "lane_start_warn:" not in result.stdout
    assert "FileExistsError" in result.stderr, result.stdout + result.stderr


def test_flagged_latest_code_status_write_oserror_warns_and_exits_0(tmp_path, run_cli):
    """Codex T7 R1 P2: with --defer-debt-preflights, a statusFile create/write OSError must
    degrade to the latest_code lane_start_warn exactly like the SystemExit resolve family, so
    the launcher's deferred startup reaches methodology-status classification."""
    target = tmp_path / "target"
    _init_target(target)
    mutate = _break_latest_code_status_write(tmp_path, target)
    adapter = _write_adapter(target, mutate)
    result = _start(run_cli, target, adapter, "--defer-debt-preflights")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lane_start_warn: latest_code" in result.stdout
    assert "latest_code: failed" not in result.stdout


# --- Claude hook settings writes + autocompact settings write ---------------------------------


def _break_claude_settings_home(tmp_path: Path) -> None:
    """Collide ~/.claude with a plain file so write_claude_settings' `mkdir(parents=True,
    exist_ok=True)` on its parent raises FileExistsError -- a deterministic, root-safe way to
    force every durable-Claude-settings write to fail without relying on chmod semantics."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / ".claude").write_text("not a directory\n", encoding="utf-8")


def test_unflagged_hook_write_failure_still_crashes_like_baseline(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    _break_claude_settings_home(tmp_path)
    result = _start(run_cli, target, adapter)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "lane_start_warn:" not in result.stdout


def test_flagged_hook_writes_warn_and_exit_0(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    _break_claude_settings_home(tmp_path)
    result = _start(run_cli, target, adapter, "--defer-debt-preflights")
    assert result.returncode == 0, result.stdout + result.stderr
    # All eleven Claude *-hook settings writes must independently degrade, not just the
    # first (the plan-edit guard hook joined the set in 0.10.5; the SessionStart
    # standing-directive hook joined in 0.13.0; the SessionStart lane-status hook
    # joined in 0.21.0).
    assert result.stdout.count("lane_start_warn: hook") == 11, result.stdout


def test_flagged_autocompact_write_warns_and_exits_0(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    _break_claude_settings_home(tmp_path)
    result = _start(run_cli, target, adapter, "--defer-debt-preflights")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lane_start_warn: autocompact - " in result.stdout


def _corrupt_claude_settings_home(tmp_path: Path) -> None:
    """An existing-but-malformed ~/.claude/settings.json: load_claude_settings retries then
    raises json.JSONDecodeError (not OSError), the failure family Codex T7 R1 flagged as
    escaping the deferred-preflight degrade path."""
    claude_dir = tmp_path / "home" / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.json").write_text("{not valid json\n", encoding="utf-8")


def test_unflagged_malformed_claude_settings_still_crashes_like_baseline(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    _corrupt_claude_settings_home(tmp_path)
    result = _start(run_cli, target, adapter)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "lane_start_warn:" not in result.stdout


def test_flagged_malformed_claude_settings_warns_and_exits_0(tmp_path, run_cli):
    """Codex T7 R1 P2: json.JSONDecodeError from a malformed settings.json must degrade to the
    hook/autocompact lane_start_warn under --defer-debt-preflights, not abort the launcher's
    deferred startup before methodology-status can classify the debt."""
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    _corrupt_claude_settings_home(tmp_path)
    result = _start(run_cli, target, adapter, "--defer-debt-preflights")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("lane_start_warn: hook") == 11, result.stdout
    assert "lane_start_warn: autocompact - " in result.stdout


# --- structural: render failure keeps hard-refusing even with the flag ------------------------


def test_flagged_render_failure_still_hard_fails(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    first = _start(run_cli, target, adapter)
    assert first.returncode == 0, first.stdout + first.stderr
    claude_md = target / "CLAUDE.md"
    assert claude_md.exists()
    # 0.43.0 (item 69) stopped rewriting a generated Markdown file whose content is unchanged, so a
    # second lane-start no longer WRITES this file at all -- and a write that never happens cannot
    # fail. Change the content first, so the render genuinely has to write and the read-only mode
    # is what stops it. Without this the test would pass for the wrong reason: no write, no error,
    # and nothing proven about the structural path.
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + "\n<!-- forces a rewrite -->\n", encoding="utf-8"
    )
    original_mode = claude_md.stat().st_mode
    claude_md.chmod(stat.S_IRUSR)
    try:
        result = _start(run_cli, target, adapter, "--defer-debt-preflights")
        assert result.returncode != 0, result.stdout + result.stderr
        assert "lane_start_warn:" not in result.stdout
        # Must be the render write itself failing (an uncaught PermissionError propagating), not
        # merely any nonzero exit -- e.g. an argparse rejection of an unrecognized flag would also
        # be nonzero but would prove nothing about the structural-path characterization.
        assert "PermissionError" in result.stderr, result.stdout + result.stderr
    finally:
        claude_md.chmod(original_mode)


# --- flag registration -------------------------------------------------------------------------


def test_defer_debt_preflights_flag_is_registered(run_cli):
    result = run_cli("lane-start", "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--defer-debt-preflights" in result.stdout
