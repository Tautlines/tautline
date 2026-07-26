import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

OPEN_PR = '[{"number":367,"title":"Live","url":"https://example.test/pr/367","state":"OPEN","mergedAt":null,"closedAt":null,"headRefName":"feature/dead-branch","baseRefName":"main","mergeStateStatus":"CLEAN","autoMergeRequest":null}]'
MERGED_PR = '[{"number":367,"title":"Merged","url":"https://example.test/pr/367","state":"MERGED","mergedAt":"2026-05-15T20:06:51Z","closedAt":"2026-05-15T20:06:51Z","headRefName":"feature/dead-branch","baseRefName":"main","mergeStateStatus":"UNKNOWN","autoMergeRequest":null}]'
CLOSED_PR = '[{"number":367,"title":"Closed","url":"https://example.test/pr/367","state":"CLOSED","mergedAt":null,"closedAt":"2026-05-15T20:06:51Z","headRefName":"feature/dead-branch","baseRefName":"main","mergeStateStatus":"UNKNOWN","autoMergeRequest":null}]'
AUTO_PR = '[{"number":367,"title":"Auto","url":"https://example.test/pr/367","state":"OPEN","mergedAt":null,"closedAt":null,"headRefName":"feature/dead-branch","baseRefName":"main","mergeStateStatus":"CLEAN","autoMergeRequest":{"enabledAt":"2026-05-15T19:46:54Z"}}]'
QUEUE_TRUE = '{"data":{"repository":{"pullRequest":{"isInMergeQueue":true,"mergeQueueEntry":{"state":"QUEUED"}}}}}'
QUEUE_FALSE = '{"data":{"repository":{"pullRequest":{"isInMergeQueue":false,"mergeQueueEntry":null}}}}'
GRAPHQL_ERROR = '{"data":{"repository":{"pullRequest":null}},"errors":[{"message":"Resource not accessible by integration"}]}'


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _run_cli(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {"PATH": os.environ["PATH"], "HOME": str((cwd or REPO_ROOT) / ".test-home")}
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=cwd,
        env=full_env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _prepare_branch_liveness_repo(tmp_path: Path) -> Path:
    root = tmp_path / "branch-liveness"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    _git(root, "checkout", "-qb", "feature/dead-branch")
    res = _run_cli("render-adapters", "--project", str(EXAMPLE), "--target", str(root), "--write", cwd=root)
    assert res.returncode == 0, res.stderr
    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "on: [pull_request, push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: pytest\n",
        encoding="utf-8",
    )
    return root


def _fake_gh(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "fake-gh"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "pr list")
    printf '%s\\n' "${GH_PR_LIST_JSON:?missing GH_PR_LIST_JSON}"
    ;;
  "repo view")
    printf '{"owner":{"login":"example-org"},"name":"example-saas"}\\n'
    ;;
  "api graphql")
    printf '%s\\n' "${GH_GRAPHQL_JSON:?missing GH_GRAPHQL_JSON}"
    ;;
  "auth status")
    # 0.10.3: board gates fail closed on unavailability, so the fake must present a
    # properly-scoped token or every hook test blocks on the board gate instead of
    # exercising its own subject.
    printf 'Token scopes: gist, read:org, read:project, project, repo, workflow\\n'
    ;;
  "project item-list")
    case "$*" in
      *--help*) printf -- 'Usage: gh project item-list\\n  -q, --query string\\n  -L, --limit int\\n' ;;
      *) printf '{"items":[]}\\n' ;;
    esac
    ;;
  "project field-list")
    printf '{"fields":[{"name":"Status","type":"ProjectV2SingleSelectField","options":[{"name":"Ready"},{"name":"In Progress"},{"name":"Done"},{"name":"Blocked"}]}]}\\n'
    ;;
  *)
    printf 'unexpected gh call: %s\\n' "$*" >&2
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return fake_bin


def _gh_env(fake_bin: Path, pr_json: str, graphql_json: str = QUEUE_FALSE) -> dict[str, str]:
    return {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_PR_LIST_JSON": pr_json,
        "GH_GRAPHQL_JSON": graphql_json,
    }


def test_branch_liveness_blocks_dead_or_queued_current_branch_pr(tmp_path):
    root = _prepare_branch_liveness_repo(tmp_path)
    fake_bin = _fake_gh(tmp_path)

    cases = [
        (MERGED_PR, QUEUE_FALSE, "current branch is dead"),
        (CLOSED_PR, QUEUE_FALSE, "current branch is dead"),
        (OPEN_PR, QUEUE_TRUE, "queued/auto-merge enabled"),
        (AUTO_PR, QUEUE_FALSE, "queued/auto-merge enabled"),
        (OPEN_PR, GRAPHQL_ERROR, "queue state could not be verified"),
    ]
    for pr_json, graphql_json, message in cases:
        res = _run_cli(
            "branch-liveness-check",
            "--project",
            str(EXAMPLE),
            "--target",
            str(root),
            cwd=root,
            env=_gh_env(fake_bin, pr_json, graphql_json),
        )
        assert res.returncode == 1
        assert message in res.stderr

    res = _run_cli(
        "branch-liveness-check",
        "--project",
        str(EXAMPLE),
        "--target",
        str(root),
        cwd=root,
        env=_gh_env(fake_bin, OPEN_PR, QUEUE_FALSE),
    )
    assert res.returncode == 0, res.stderr
    assert "branch_liveness: pass - current branch PR remains active" in res.stdout


def test_task_branch_liveness_hook_blocks_dead_branch_and_allows_live_branch(tmp_path):
    root = _prepare_branch_liveness_repo(tmp_path)
    fake_bin = _fake_gh(tmp_path)
    payload = f'{{"tool_name":"Task","cwd":"{root}","tool_input":{{"description":"worker"}}}}\n'

    blocked = subprocess.run(
        [sys.executable, str(CLI_PATH), "branch-liveness-hook"],
        cwd=root,
        env={"HOME": str(tmp_path / "home"), **_gh_env(fake_bin, MERGED_PR, QUEUE_FALSE)},
        input=payload,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert blocked.returncode == 0
    assert "Task blocked by Minervit branch-liveness guard" in blocked.stdout

    live = subprocess.run(
        [sys.executable, str(CLI_PATH), "branch-liveness-hook"],
        cwd=root,
        env={"HOME": str(tmp_path / "home"), **_gh_env(fake_bin, OPEN_PR, QUEUE_FALSE)},
        input=payload,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert live.returncode == 0
    assert "Task blocked" not in live.stdout


def test_branch_liveness_strict_allows_non_github_remote(tmp_path):
    root = tmp_path / "branch-liveness-non-github"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    _git(root, "checkout", "-qb", "feature/non-github")
    _git(root, "remote", "add", "origin", "https://gitlab.com/minervit/example.git")

    res = _run_cli("branch-liveness-check", "--target", str(root), "--strict", cwd=root)

    assert res.returncode == 0, res.stderr
    assert "branch_liveness: pass - no GitHub remote detected" in res.stdout


def test_branch_liveness_treats_experimental_as_base_branch_only_for_methodology_repo(tmp_path):
    root = tmp_path / "branch-liveness-experimental"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "experimental")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/minervit/minervit-ai-delivery-methodology.git")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    (root / ".minervit-ai-delivery.json").write_text(
        '{"repo":"minervit/minervit-ai-delivery-methodology"}\n',
        encoding="utf-8",
    )

    res = _run_cli("branch-liveness-check", "--target", str(root), "--strict", cwd=root)

    assert res.returncode == 0, res.stderr
    assert "branch_liveness: pass - base branch" in res.stdout

    copied_adapter_root = tmp_path / "branch-liveness-copied-methodology-adapter"
    copied_adapter_root.mkdir()
    _git(copied_adapter_root, "init", "-q")
    _git(copied_adapter_root, "checkout", "-B", "experimental")
    _git(copied_adapter_root, "config", "user.email", "test@example.com")
    _git(copied_adapter_root, "config", "user.name", "Test User")
    _git(copied_adapter_root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (copied_adapter_root / "README.md").write_text("base\n", encoding="utf-8")
    _git(copied_adapter_root, "add", "README.md")
    _git(copied_adapter_root, "commit", "-qm", "init")
    (copied_adapter_root / ".minervit-ai-delivery.json").write_text(
        '{"repo":"minervit/minervit-ai-delivery-methodology"}\n',
        encoding="utf-8",
    )
    fake_bin = _fake_gh(tmp_path)

    copied_adapter_blocked = _run_cli(
        "branch-liveness-check",
        "--target",
        str(copied_adapter_root),
        "--strict",
        cwd=copied_adapter_root,
        env=_gh_env(fake_bin, MERGED_PR, QUEUE_FALSE),
    )

    assert copied_adapter_blocked.returncode == 1
    assert "branch_liveness: pass - base branch" not in copied_adapter_blocked.stdout
    assert "current branch is dead" in copied_adapter_blocked.stderr

    product_root = tmp_path / "branch-liveness-product-experimental"
    product_root.mkdir()
    _git(product_root, "init", "-q")
    _git(product_root, "checkout", "-B", "experimental")
    _git(product_root, "config", "user.email", "test@example.com")
    _git(product_root, "config", "user.name", "Test User")
    _git(product_root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (product_root / "README.md").write_text("base\n", encoding="utf-8")
    _git(product_root, "add", "README.md")
    _git(product_root, "commit", "-qm", "init")
    res = _run_cli("render-adapters", "--project", str(EXAMPLE), "--target", str(product_root), "--write", cwd=product_root)
    assert res.returncode == 0, res.stderr
    blocked = _run_cli(
        "branch-liveness-check",
        "--target",
        str(product_root),
        "--strict",
        cwd=product_root,
        env=_gh_env(fake_bin, MERGED_PR, QUEUE_FALSE),
    )

    assert blocked.returncode == 1
    assert "branch_liveness: pass - base branch" not in blocked.stdout
    assert "current branch is dead" in blocked.stderr


def test_installed_git_hooks_enforce_branch_liveness_and_fail_closed_without_adapter(tmp_path):
    root = _prepare_branch_liveness_repo(tmp_path)
    fake_bin = _fake_gh(tmp_path)
    res = _run_cli("install-hooks", "--settings", str(tmp_path / "settings.json"), "--target", str(root), cwd=root)
    assert res.returncode == 0, res.stderr
    assert "git_branch_liveness_hook:" in res.stdout

    pre_commit = root / ".git" / "hooks" / "pre-commit"
    pre_push = root / ".git" / "hooks" / "pre-push"
    assert "MINERVIT-BRANCH-LIVENESS-HOOK" in pre_commit.read_text(encoding="utf-8")
    assert "MINERVIT-BRANCH-LIVENESS-HOOK" in pre_push.read_text(encoding="utf-8")
    pre_push_text = pre_push.read_text(encoding="utf-8")
    assert "guard-check --target . --boundary prepush" in pre_push_text
    assert pre_push_text.index(str(CLI_PATH)) < pre_push_text.index("MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology")

    hook_env = _gh_env(fake_bin, MERGED_PR, QUEUE_FALSE)
    blocked = subprocess.run(
        [str(pre_commit)],
        cwd=root,
        env={"HOME": str(tmp_path / "home"), **hook_env},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert blocked.returncode == 1
    assert "current branch is dead" in blocked.stderr

    live = subprocess.run(
        [str(pre_push)],
        cwd=root,
        env={"HOME": str(tmp_path / "home"), **_gh_env(fake_bin, OPEN_PR, QUEUE_FALSE)},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert live.returncode == 0, live.stderr
    assert "branch_liveness: pass - current branch PR remains active" in live.stdout

    adapter = root / ".tautline.json"
    backup = root / ".tautline.json.bak"
    adapter.rename(backup)
    missing_adapter = subprocess.run(
        [str(pre_push)],
        cwd=root,
        env={"HOME": str(tmp_path / "home"), **_gh_env(fake_bin, OPEN_PR, QUEUE_FALSE)},
        text=True,
        capture_output=True,
        timeout=60,
    )
    backup.rename(adapter)
    assert missing_adapter.returncode == 1
    assert "No project adapter found for this lane" in missing_adapter.stderr
    assert "tautline init --target ." in missing_adapter.stderr
