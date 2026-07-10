import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(
    *args: str,
    home: Path,
    adapter_root: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
    }
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _write_planning_adapter(adapter_root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for lane-start planning, drift, and lane-env coverage.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
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
    adapter = adapter_root / "lane-start-planning-example.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(
    target: Path,
    *,
    create_source: bool = True,
    create_template: bool = True,
) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    if create_source:
        (target / SOURCE_REL).mkdir(parents=True)
    if create_template:
        template = target / TEMPLATE_REL
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("# Validation Template\n", encoding="utf-8")


def test_methodology_status_reports_planning_source_and_template_drift(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "missing-template"
    adapter = _write_planning_adapter(adapter_root)
    _init_target(target, create_source=True, create_template=False)

    status = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        home=home,
        adapter_root=adapter_root,
    )
    strict = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        home=home,
        adapter_root=adapter_root,
    )

    assert status.returncode == 0, status.stdout + status.stderr
    assert "planning_source_of_truth: present" in status.stdout
    assert "planning_template: missing" in status.stdout
    assert strict.returncode == 1
    assert "template path missing:" in strict.stdout


def test_lane_start_migrates_relevant_scratch_plan_and_clears_status_drift(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "scratch-migration"
    adapter = _write_planning_adapter(adapter_root)
    _init_target(target)
    scratch_dir = home / ".claude" / "plans"
    scratch_dir.mkdir(parents=True)
    scratch_plan = scratch_dir / "relevant-scratch-plan.md"
    scratch_plan.write_text(f"# Scratch plan\n\n{SOURCE_REL}/\n", encoding="utf-8")

    before = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        home=home,
        adapter_root=adapter_root,
    )
    lane_start = _run_cli(
        "lane-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--skip-update",
        home=home,
        adapter_root=adapter_root,
    )
    after = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        home=home,
        adapter_root=adapter_root,
    )

    assert before.returncode == 1
    assert "planning_relevant_scratch_plans: 1 candidate(s)" in before.stdout
    assert lane_start.returncode == 0, lane_start.stdout + lane_start.stderr
    assert f"plugin_version: {(REPO_ROOT / 'VERSION').read_text(encoding='utf-8').strip()}" in lane_start.stdout
    assert "methodology_commit:" in lane_start.stdout
    assert "claude_plan_finalization_hook:" in lane_start.stdout
    assert "document_context: enforcement=warn" in lane_start.stdout
    assert "context_rotation: enabled=true soft=60 hard=75" in lane_start.stdout
    assert "planning_migration: moved" in lane_start.stdout
    assert "planning_migration_error:" not in lane_start.stdout
    settings_text = (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    for hook_name in [
        "plan-finalization-hook",
        "branch-liveness-hook",
        "response-guard-hook",
        "tool-rejection-hook",
        "background-command-hook",
    ]:
        assert hook_name in settings_text
    assert not scratch_plan.exists()
    assert (target / SOURCE_REL / "relevant-scratch-plan.md").is_file()
    assert after.returncode == 0, after.stdout + after.stderr


def test_parallel_lane_start_migrates_shared_scratch_plan_once(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_planning_adapter(adapter_root)
    lane_a = tmp_path / "parallel-migration" / "lane-a"
    lane_b = tmp_path / "parallel-migration" / "lane-b"
    _init_target(lane_a)
    _init_target(lane_b)
    scratch_dir = home / ".claude" / "plans"
    scratch_dir.mkdir(parents=True)
    (scratch_dir / "parallel-scratch-plan.md").write_text(f"# Parallel scratch plan\n\n{SOURCE_REL}\n", encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
    }

    proc_a = subprocess.Popen(
        [sys.executable, str(CLI_PATH), "lane-start", "--project", str(adapter), "--target", str(lane_a), "--skip-update"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc_b = subprocess.Popen(
        [sys.executable, str(CLI_PATH), "lane-start", "--project", str(adapter), "--target", str(lane_b), "--skip-update"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out_a, err_a = proc_a.communicate(timeout=60)
    out_b, err_b = proc_b.communicate(timeout=60)

    assert proc_a.returncode == 0, out_a + err_a
    assert proc_b.returncode == 0, out_b + err_b
    assert "planning_migration_error:" not in out_a + out_b
    assert not (scratch_dir / "parallel-scratch-plan.md").exists()
    moved = sorted((tmp_path / "parallel-migration").glob("*/" + SOURCE_REL + "/parallel-scratch-plan.md"))
    assert len(moved) == 1


def test_lane_start_repairs_generated_adapter_drift_and_writes_lane_env(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "adapter-drift"
    adapter = _write_planning_adapter(adapter_root)
    _init_target(target)

    lane_start = _run_cli(
        "lane-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--skip-update",
        home=home,
        adapter_root=adapter_root,
    )
    lane_json = target / ".tautline.json"
    lane_data = json.loads(lane_json.read_text(encoding="utf-8"))
    lane_data["commands"]["mainStatus"] = "stale local generated adapter command"
    lane_json.write_text(json.dumps(lane_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    drift = _run_cli(
        "methodology-status",
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        home=home,
        adapter_root=adapter_root,
    )
    repaired = _run_cli(
        "lane-start",
        "--target",
        str(target),
        "--skip-update",
        home=home,
        adapter_root=adapter_root,
    )
    status = _run_cli(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        home=home,
        adapter_root=adapter_root,
    )

    assert lane_start.returncode == 0, lane_start.stdout + lane_start.stderr
    assert drift.returncode == 1
    assert "adapter_drift:" in drift.stdout
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert status.returncode == 0, status.stdout + status.stderr
    assert "adapter_drift: clean" in status.stdout
    assert (target / ".ai-runs").is_dir()
    assert (target / ".ai-work").is_dir()
    lane_env = target / ".ai-work" / "lane-env.sh"
    env_text = lane_env.read_text(encoding="utf-8")
    assert "export COMPOSE_PROJECT_NAME=" in env_text
    assert "export EXAMPLE_PG_PORT=" in env_text
    assert "export EXAMPLE_REDIS_PORT=" in env_text
    exclude_text = (target / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".ai-runs/" in exclude_text
    assert ".ai-work/" in exclude_text
    assert ".minervit-methodology-lock.json" in exclude_text
    assert "lane_env: present" in status.stdout
    assert "lane_env_compose_project:" in status.stdout
    assert "lane_env_ports:" in status.stdout


def test_lane_env_ports_are_lane_slot_specific_and_loaded_by_lane_run(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "ExampleSaas-Lane2"
    adapter = _write_planning_adapter(adapter_root)
    _init_target(target)

    lane_start = _run_cli(
        "lane-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--skip-update",
        home=home,
        adapter_root=adapter_root,
    )
    lane_run = _run_cli(
        "lane-run",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--",
        sys.executable,
        "-c",
        (
            "import os; "
            "assert os.environ['EXAMPLE_PG_PORT'] == '5442'; "
            "assert os.environ['EXAMPLE_REDIS_PORT'] == '6389'; "
            "assert os.environ['EXAMPLE_API_PORT'] == '8010'; "
            "assert os.environ['COMPOSE_PROJECT_NAME'].startswith('examplesaas-')"
        ),
        home=home,
        adapter_root=adapter_root,
    )

    assert lane_start.returncode == 0, lane_start.stdout + lane_start.stderr
    assert "lane_env_ports: EXAMPLE_PG_PORT=5442" in lane_start.stdout
    assert "EXAMPLE_REDIS_PORT=6389" in lane_start.stdout
    assert "EXAMPLE_API_PORT=8010" in lane_start.stdout
    assert lane_run.returncode == 0, lane_run.stdout + lane_run.stderr


def test_real_example_adapter_reports_lane_env_and_loads_lane_run_env(tmp_path):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    bootstrap_adapter = _write_planning_adapter(adapter_root)
    target = tmp_path / "ExampleSaas-Lane2"
    _init_target(target)
    lane_start = _run_cli(
        "lane-start",
        "--project",
        str(bootstrap_adapter),
        "--target",
        str(target),
        "--skip-update",
        home=home,
        adapter_root=adapter_root,
    )
    status = _run_cli(
        "methodology-status",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--no-remote",
        home=home,
        adapter_root=adapter_root,
    )
    lane_run = _run_cli(
        "lane-run",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--",
        sys.executable,
        "-c",
        (
            "import os; "
            "assert os.environ['EXAMPLE_PG_PORT'] == '5442'; "
            "assert os.environ['EXAMPLE_REDIS_PORT'] == '6389'; "
            "assert os.environ['EXAMPLE_API_PORT'] == '8010'; "
            "assert os.environ['COMPOSE_PROJECT_NAME'].startswith('examplesaas-')"
        ),
        home=home,
        adapter_root=adapter_root,
    )

    assert lane_start.returncode == 0, lane_start.stdout + lane_start.stderr
    assert status.returncode == 0, status.stdout + status.stderr
    assert "lane_env: present" in status.stdout
    assert "lane_env_ports: EXAMPLE_PG_PORT=5442" in status.stdout
    assert "EXAMPLE_REDIS_PORT=6389" in status.stdout
    assert "EXAMPLE_API_PORT=8010" in status.stdout
    assert lane_run.returncode == 0, lane_run.stdout + lane_run.stderr
