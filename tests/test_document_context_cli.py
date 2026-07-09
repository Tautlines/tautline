import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
INDEX_REL = "docs/product/backlog/example-saas-v1/specs/_index.md"
ACTIVE_PLAN_REL = "docs/product/backlog/example-saas-v1/specs/active-plan.md"
ARCHIVE_PLAN_REL = "docs/product/backlog/example-saas-v1/specs/archive/old-plan.md"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(*args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=60,
    )


def _init_target(target: Path) -> None:
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    (target / "docs/product/backlog/example-saas-v1/specs").mkdir(parents=True)
    templates = target / "docs/product/backlog/templates"
    templates.mkdir(parents=True)
    (templates / "pr-execution-spec.template.md").write_text("# PR Template\n", encoding="utf-8")
    (templates / "goal.template.md").write_text("# Goal Template\n", encoding="utf-8")


def _write_document_context_adapter(target: Path, adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for document-context command coverage.",
        "repoEvidence": [
            {
                "path": "docs/product/backlog/templates/pr-execution-spec.template.md",
                "fact": "PR execution template fixture exists.",
            },
            {
                "path": "docs/product/backlog/templates/goal.template.md",
                "fact": "Goal template fixture exists.",
            },
        ],
    }
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
    data.setdefault("behaviorSpecs", {})["required"] = False
    data["behaviorSpecs"]["acceptanceHarnesses"] = []
    for key in (
        "backlogProvider",
        "goalTracker",
        "stakeholderQuestions",
        "deploymentNotification",
        "productChat",
        "milestoneUpdate",
        "iterationReview",
    ):
        data.pop(key, None)
    data["documentContext"] = {
        "enforcement": "warn",
        "contextIndexPaths": [INDEX_REL],
        "trackedDocRoots": ["docs/product/backlog/example-saas-v1/specs"],
        "historicalPaths": ["docs/product/backlog/example-saas-v1/specs/archive"],
        "ignoredDocPaths": [".ai-work/"],
        "maxIndexBytes": 16000,
        "maxIndexLines": 250,
    }
    adapter = adapter_root / "document-context-example.json"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _write_strict_document_context_adapter(target: Path, adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["repo"] = "owner/strict-context"
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for strict document-context adapter enforcement.",
        "repoEvidence": [
            {
                "path": "docs/product/backlog/templates/pr-execution-spec.template.md",
                "fact": "PR execution template fixture exists.",
            },
            {
                "path": "docs/product/backlog/templates/goal.template.md",
                "fact": "Goal template fixture exists.",
            },
        ],
    }
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
    data.setdefault("behaviorSpecs", {})["required"] = False
    data["behaviorSpecs"]["acceptanceHarnesses"] = []
    for key in (
        "backlogProvider",
        "goalTracker",
        "stakeholderQuestions",
        "deploymentNotification",
        "productChat",
        "milestoneUpdate",
        "iterationReview",
    ):
        data.pop(key, None)
    data["documentContext"] = {
        "enforcement": "strict",
        "contextIndexPaths": ["docs/context/_index.md"],
        "trackedDocRoots": ["docs/context"],
        "historicalPaths": ["docs/context/archive"],
        "ignoredDocPaths": [".ai-work/"],
        "maxIndexBytes": 16000,
        "maxIndexLines": 250,
    }
    adapter = adapter_root / "strict-document-context.json"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    target = tmp_path / "document-context-fixture"
    adapter_root = tmp_path / "trusted-adapters"
    _init_target(target)
    adapter = _write_document_context_adapter(target, adapter_root)
    env = {"MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root)}
    result = _run_cli("render-adapters", "--project", str(adapter), "--target", str(target), "--write", env=env)
    assert result.returncode == 0, result.stderr
    hook_settings = target / ".claude" / "settings.json"
    hooks = _run_cli("install-hooks", "--settings", str(hook_settings), "--target", str(target), env=env)
    assert hooks.returncode == 0, hooks.stderr
    return target, adapter, env


def test_context_status_strict_fails_until_indexes_are_bootstrapped(tmp_path):
    target, adapter, env = _prepare_target(tmp_path)

    warn = _run_cli("context-status", "--project", str(adapter), "--target", str(target), env=env)
    strict = _run_cli("context-status", "--project", str(adapter), "--target", str(target), "--strict", env=env)
    method_status = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--strict",
        "--fail-on-drift",
        env=env,
    )

    assert warn.returncode == 0, warn.stderr
    assert "document_context: enforcement=warn" in warn.stdout
    assert f"document_context_missing_indexes: 1 - {INDEX_REL}" in warn.stdout
    assert strict.returncode == 1
    assert "missing context index:" in strict.stdout
    assert method_status.returncode == 1
    assert f"document_context_missing_indexes: 1 - {INDEX_REL}" in method_status.stdout
    assert "lane_coordination_issue:" not in method_status.stdout


def test_context_bootstrap_classification_and_archive_header_repair(tmp_path):
    target, adapter, env = _prepare_target(tmp_path)

    bootstrap = _run_cli("context-bootstrap", "--project", str(adapter), "--target", str(target), "--write", env=env)
    index = target / INDEX_REL
    archive_dir = target / "docs/product/backlog/example-saas-v1/specs/archive"
    assert bootstrap.returncode == 0, bootstrap.stderr
    assert index.exists()
    assert archive_dir.is_dir()
    index_text = index.read_text(encoding="utf-8")
    for heading in [
        "## Read First",
        "## Active Work",
        "## Ready Next",
        "## Historical Evidence Only",
        "## Do Not Load Routinely",
        "## Needs Classification",
    ]:
        assert heading in index_text

    (target / ACTIVE_PLAN_REL).write_text("# Active Plan\n", encoding="utf-8")
    (target / ARCHIVE_PLAN_REL).write_text("---\ntitle: Old Plan\n---\n# Old Plan\n", encoding="utf-8")
    classify = _run_cli(
        "context-bootstrap",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--classify",
        "--write",
        env=env,
    )
    assert classify.returncode == 0, classify.stderr
    index_text = index.read_text(encoding="utf-8")
    classification_entry = (
        f"- [ ] `{ACTIVE_PLAN_REL}` - classify as Active Work, Ready Next, or Historical Evidence Only."
    )
    assert classification_entry in index_text

    strict_gap = _run_cli("context-status", "--project", str(adapter), "--target", str(target), "--strict", env=env)
    assert strict_gap.returncode == 1
    assert "needs classification index entry" in strict_gap.stdout
    assert "archive header missing" in strict_gap.stdout

    index.write_text(
        index_text.replace(
            "## Active Work\n\n<!-- Add current execution plans/specs here. -->",
            f"## Active Work\n\n<!-- Add current execution plans/specs here. -->\n- `{ACTIVE_PLAN_REL}` - current validation fixture.",
        ).replace(classification_entry + "\n", ""),
        encoding="utf-8",
    )
    header_repair = _run_cli(
        "context-bootstrap",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--add-archive-headers",
        "--write",
        env=env,
    )
    old_plan = target / ARCHIVE_PLAN_REL
    old_plan_lines = old_plan.read_text(encoding="utf-8").splitlines()
    final_status = _run_cli("context-status", "--project", str(adapter), "--target", str(target), "--strict", env=env)

    assert header_repair.returncode == 0, header_repair.stderr
    assert "context_archive_headers_missing: 1" in header_repair.stdout
    assert "context_archive_headers_written: 1" in header_repair.stdout
    assert old_plan_lines[0] == "---"
    assert old_plan_lines[2] == "---"
    assert old_plan_lines[4].startswith("Historical evidence only.")
    assert final_status.returncode == 0, final_status.stdout + final_status.stderr


def test_adapter_strict_document_context_fails_until_bootstrapped(tmp_path):
    target = tmp_path / "strict-context-fixture"
    adapter_root = tmp_path / "trusted-adapters"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:owner/strict-context.git")
    templates = target / "docs/product/backlog/templates"
    templates.mkdir(parents=True)
    (templates / "pr-execution-spec.template.md").write_text("# Validation Template\n", encoding="utf-8")
    (templates / "goal.template.md").write_text("# Goal Template\n", encoding="utf-8")
    adapter = _write_strict_document_context_adapter(target, adapter_root)
    env = {"MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root)}
    render = _run_cli("render-adapters", "--project", str(adapter), "--target", str(target), "--write", env=env)
    before = _run_cli("context-status", "--project", str(adapter), "--target", str(target), env=env)

    assert render.returncode == 0, render.stderr
    assert before.returncode == 1
    assert "document_context: enforcement=strict" in before.stdout
    assert "document_context_missing_indexes: 1 - docs/context/_index.md" in before.stdout
    assert "missing context index:" in before.stdout

    bootstrap = _run_cli("context-bootstrap", "--project", str(adapter), "--target", str(target), "--write", env=env)
    after = _run_cli("context-status", "--project", str(adapter), "--target", str(target), env=env)

    assert bootstrap.returncode == 0, bootstrap.stderr
    assert (target / "docs/context/_index.md").is_file()
    assert (target / "docs/context/archive").is_dir()
    assert after.returncode == 0, after.stdout + after.stderr
    assert "document_context: enforcement=strict" in after.stdout
    assert "document_context_missing_indexes: none" in after.stdout
