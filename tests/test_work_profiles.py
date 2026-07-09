import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _prepare_rendered_repo(run_cli, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    res = run_cli("render-adapters", "--project", str(EXAMPLE), "--target", str(root), "--write")
    assert res.returncode == 0, res.stderr
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "render adapter")
    _git(root, "checkout", "-qb", "feature/docs")
    return root


def _write_profile(root: Path, profile: str) -> None:
    path = root / ".ai-work" / "WORK_PROFILE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "minervit-work-profile/v1", "profile": profile}) + "\n",
        encoding="utf-8",
    )


def _commit_file(root: Path, rel: str, content: bytes | str = "content\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-qm", f"add {rel}")


def _generated_adapter_path(root: Path) -> Path:
    return root / ".tautline.json"


def _read_generated_adapter(root: Path) -> dict:
    return json.loads(_generated_adapter_path(root).read_text(encoding="utf-8"))


def _write_generated_adapter(root: Path, data: dict) -> None:
    _generated_adapter_path(root).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_missing_profile_defaults_to_development(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=development" in res.stdout
    assert "work_profile_gate_decision: development" in res.stdout


def test_default_rendered_adapter_omits_pre_push_base_for_rollback_compatibility(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)

    data = _read_generated_adapter(root)

    assert "prePushBase" not in data["workProfiles"]


def test_legacy_generated_adapter_without_work_profiles_defaults_safely(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    data = _read_generated_adapter(root)
    data.pop("workProfiles", None)
    _write_generated_adapter(root, data)
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=product-docs" in res.stdout
    assert "work_profile_gate_decision: non_dev_docs_only" in res.stdout


def test_invalid_profile_lock_falls_back_to_development(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    lock = root / ".ai-work" / "WORK_PROFILE.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("{not-json\n", encoding="utf-8")
    _commit_file(root, "src/app.ts", "export const value = 1;\n")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=development" in res.stdout
    assert "work_profile_gate_decision: development" in res.stdout
    assert "work profile lock is unreadable" in res.stderr


def test_product_docs_profile_allows_docs_assets_diff(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=product-docs" in res.stdout
    assert "work_profile_gate_decision: non_dev_docs_only" in res.stdout
    assert "Do not push code" in res.stdout


def test_support_docs_profile_allows_support_docs(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "support-docs")
    _commit_file(root, "support/incidents/checkout.md", "# Checkout note\n")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=support-docs" in res.stdout
    assert "work_profile_gate_decision: non_dev_docs_only" in res.stdout


def test_product_docs_profile_blocks_code_diff(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    _commit_file(root, "src/app.ts", "export const value = 1;\n")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert "src/app.ts: blocked path for product-docs" in res.stderr
    assert "switch to development" in res.stderr


def test_product_docs_profile_uses_adapter_pre_push_base(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _git(root, "checkout", "main")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "experimental")
    source = root / ".minervit" / "adapter.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["workProfiles"] = {"prePushBase": "origin/experimental"}
    source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = run_cli("render-adapters", "--project", str(source), "--target", str(root), "--write")
    assert rendered.returncode == 0, rendered.stderr
    assert _read_generated_adapter(root)["workProfiles"]["prePushBase"] == "origin/experimental"
    _git(root, "add", ".minervit/adapter.json", ".tautline.json", "AGENTS.md", "CLAUDE.md")
    _git(root, "commit", "-qm", "configure experimental work profile base")
    _commit_file(root, "src/experimental.ts", "export const experimental = true;\n")
    _git(root, "update-ref", "refs/remotes/origin/experimental", "HEAD")
    _git(root, "checkout", "-B", "feature/docs")
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 0, res.stderr
    assert "work_profile_changed_file: docs/wireframes/signup.png" in res.stdout
    assert "src/experimental.ts" not in res.stdout
    assert "work_profile_gate_decision: non_dev_docs_only" in res.stdout


def test_product_docs_profile_blocks_experimental_base_branch_for_methodology_repo(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _git(root, "checkout", "main")
    _git(root, "remote", "set-url", "origin", "git@github.com:minervit/minervit-ai-delivery-methodology.git")
    source = root / ".minervit" / "adapter.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["repo"] = "minervit/minervit-ai-delivery-methodology"
    data["workProfiles"] = {"prePushBase": "origin/experimental"}
    source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = run_cli("render-adapters", "--project", str(source), "--target", str(root), "--write")
    assert rendered.returncode == 0, rendered.stderr
    _git(root, "add", ".minervit/adapter.json", ".tautline.json", "AGENTS.md", "CLAUDE.md")
    _git(root, "commit", "-qm", "configure methodology work profile base")
    _git(root, "checkout", "-B", "experimental")
    _git(root, "update-ref", "refs/remotes/origin/experimental", "HEAD")
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert "cannot push directly from base branch experimental" in res.stderr
    assert "work_profile_changed_file:" not in res.stdout


@pytest.mark.parametrize("rel_path", ["docs/spec.mdx", "docs/wireframes/flow.svg"])
def test_product_docs_profile_blocks_executable_doc_formats_by_default(run_cli, tmp_path, rel_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    _commit_file(root, rel_path, "<script>alert(1)</script>\n")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert f"{rel_path}: extension" in res.stderr
    assert "is not allowed in product-docs" in res.stderr


def test_product_docs_profile_blocks_committed_symlink_even_if_worktree_regular(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    rel_path = "docs/wireframes/linked.png"
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to("../../src/secret.txt")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable in this test environment: {exc}")
    _git(root, "add", rel_path)
    _git(root, "commit", "-qm", "add symlink")
    path.unlink()
    path.write_bytes(b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert f"{rel_path}: symlinks are not allowed in product-docs" in res.stderr


def test_product_docs_profile_blocks_committed_oversize_even_if_worktree_small(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    rel_path = "docs/wireframes/large.png"
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.seek(25_000_000)
        fh.write(b"x")
    _git(root, "add", rel_path)
    _git(root, "commit", "-qm", "add large asset")
    (root / rel_path).write_bytes(b"x")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert f"{rel_path}: file is 25000001 bytes, over product-docs maxFileBytes=25000000" in res.stderr


def test_product_docs_profile_blocks_base_branch_push(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _git(root, "checkout", "main")
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push")

    assert res.returncode == 1
    assert "cannot push directly from base branch main" in res.stderr


def test_product_docs_profile_allows_base_branch_push_when_adapter_opts_into_direct_main(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _git(root, "checkout", "main")
    source = root / ".minervit" / "adapter.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["workProfiles"] = {"profiles": {"product-docs": {"pushPolicy": "direct-main"}}}
    source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = run_cli("render-adapters", "--project", str(source), "--target", str(root), "--write")
    assert rendered.returncode == 0, rendered.stderr
    _git(root, "add", ".minervit/adapter.json", ".tautline.json", "AGENTS.md", "CLAUDE.md")
    _git(root, "commit", "-qm", "set direct-main docs profile")
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push", "--base", "HEAD~1")

    assert res.returncode == 0, res.stderr
    assert "work_profile: profile=product-docs" in res.stdout
    assert "pushPolicy=direct-main" in res.stdout
    assert "work_profile_gate_decision: non_dev_docs_only" in res.stdout


def test_direct_main_profile_still_blocks_symlink_docs_asset(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _git(root, "checkout", "main")
    source = root / ".minervit" / "adapter.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["workProfiles"] = {"profiles": {"product-docs": {"pushPolicy": "direct-main"}}}
    source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = run_cli("render-adapters", "--project", str(source), "--target", str(root), "--write")
    assert rendered.returncode == 0, rendered.stderr
    _git(root, "add", ".minervit/adapter.json", ".tautline.json", "AGENTS.md", "CLAUDE.md")
    _git(root, "commit", "-qm", "set direct-main docs profile")
    _write_profile(root, "product-docs")
    rel_path = "docs/wireframes/linked.png"
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to("../../src/secret.txt")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable in this test environment: {exc}")
    _git(root, "add", rel_path)
    _git(root, "commit", "-qm", "add symlink")
    path.unlink()
    path.write_bytes(b"png")

    res = run_cli("work-profile-check", "--target", str(root), "--event", "pre-push", "--base", "HEAD~1")

    assert res.returncode == 1
    assert "pushPolicy=direct-main" in res.stdout
    assert f"{rel_path}: symlinks are not allowed in product-docs" in res.stderr


def test_non_dev_hook_skips_development_only_gates_for_docs_assets(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)
    _write_profile(root, "product-docs")
    _commit_file(root, "docs/wireframes/signup.png", b"png")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "pr list")
    printf '[{"number":12,"title":"Docs","url":"https://example.test/pr/12","state":"OPEN","mergedAt":null,"closedAt":null,"headRefName":"feature/docs","baseRefName":"main","mergeStateStatus":"CLEAN","autoMergeRequest":null}]\\n'
    ;;
  "repo view")
    printf '{"owner":{"login":"example-org"},"name":"example-saas"}\\n'
    ;;
  "api graphql")
    printf '{"data":{"repository":{"pullRequest":{"isInMergeQueue":false,"mergeQueueEntry":null}}}}\\n'
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
    res = run_cli(
        "install-hooks",
        "--settings",
        str(tmp_path / "settings.json"),
        "--target",
        str(root),
    )
    assert res.returncode == 0, res.stderr
    assert "work-profile-check --target . --event pre-commit" in (
        root / ".git" / "hooks" / "pre-commit"
    ).read_text(encoding="utf-8")
    assert "work-profile-check --target . --event pre-push" in (
        root / ".git" / "hooks" / "pre-push"
    ).read_text(encoding="utf-8")

    env = {"PATH": f"{fake_bin}:{os.environ['PATH']}", "HOME": str(tmp_path / "home")}
    hook = subprocess.run(
        [str(root / ".git" / "hooks" / "pre-push")],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert hook.returncode == 0, hook.stderr
    assert "branch_liveness: pass - current branch PR remains active" in hook.stdout
    assert "work_profile_hook: skipping development-only" in hook.stdout
    assert "review_evidence_check:" not in hook.stdout
