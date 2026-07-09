import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
PLAN_ROOT = Path("docs/product/backlog/example-saas-v1/specs")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run(
    tmp_path: Path,
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=cwd,
        env={**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""},
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _write_adapter(root: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data.setdefault("ciTestGate", {})["enforcement"] = "warn"
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for milestone CLI behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = root / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "milestone-target"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")
    adapter = _write_adapter(target)
    rendered = _run(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    assert rendered.returncode == 0
    return target, adapter


def _write_plan(target: Path, name: str, title: str, queue_heading: str, items: list[str]) -> str:
    rel = PLAN_ROOT / name
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    queue = "\n".join(f"- [ ] {item}" for item in items)
    path.write_text(
        f"""# {title}

## Milestone Goal
Validate milestone continuation behavior.

## {queue_heading}
{queue}

## Acceptance Criteria
- The milestone fixture proves the expected CLI transition.
""",
        encoding="utf-8",
    )
    return str(rel)


def _milestone_run(target: Path) -> dict:
    return json.loads((target / ".ai-work" / "MILESTONE_RUN.json").read_text(encoding="utf-8"))


def test_milestone_continuation_pr_transitions_watchdog_and_work_loop(tmp_path):
    target, _adapter = _prepare_target(tmp_path)
    plan = _write_plan(
        target,
        "test-milestone-continuation.md",
        "Test Milestone Continuation",
        "Ordered Tactical Queue",
        ["First continuation item", "Second continuation item"],
    )

    start = _run(tmp_path, "milestone-start", "--target", str(target), "--plan", plan)
    assert "next_action_type: continue_item" in start.stdout
    assert "next_action: Continue item 1: First continuation item" in start.stdout

    missing_pr = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-queued", check=False)
    assert missing_pr.returncode == 1
    assert "--pr is required for pr-queued" in missing_pr.stderr

    queued = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-queued", "--pr", "123")
    assert "percent_complete: 50" in queued.stdout
    assert "next_action: Continue item 2: Second continuation item" in queued.stdout

    mismatch = _run(
        tmp_path,
        "milestone-advance",
        "--target",
        str(target),
        "--event",
        "pr-merged",
        "--item-index",
        "2",
        "--pr",
        "123",
        check=False,
    )
    assert mismatch.returncode == 1
    assert "PR 123 is already recorded on milestone item 1" in mismatch.stderr

    merged = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-merged", "--pr", "123")
    assert merged.returncode == 0
    run = _milestone_run(target)
    items = {item["index"]: item for item in run["items"]}
    assert items[1]["status"] == "merged"
    assert items[1]["pr"] == "123"
    assert items[2]["status"] == "in_progress"
    assert items[2]["pr"] is None
    assert run["currentIndex"] == 2

    complete = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-queued", "--pr", "124")
    assert "status: complete" in complete.stdout
    assert "next_action_type: milestone_complete" in complete.stdout
    assert "Prove milestone completion from the ledger" in complete.stdout

    watchdog = _run(tmp_path, "milestone-watchdog", "--target", str(target))
    assert "watchdog_enabled: true" in watchdog.stdout
    assert "watchdog_role: recovery visibility only; milestone ledger remains the source of next-action truth" in watchdog.stdout

    forced = _run(tmp_path, "milestone-watchdog", "--target", str(target), "--force")
    assert "watchdog_next_pointer: run `tautline milestone-next --target .`" in forced.stdout
    assert "\nnext_action:" not in forced.stdout

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    work_loop = _run(tmp_path, "work-loop", "--target", str(target), "--plan", plan)
    assert "next_action_type: continue_item" in work_loop.stdout
    assert list((target / ".ai-runs").glob("*-work-loop-next.json"))


def test_milestone_blocked_abandoned_queue_heading_and_missing_pr_recovery(tmp_path):
    target, _adapter = _prepare_target(tmp_path)
    blocked_plan = _write_plan(
        target,
        "test-blocked-milestone.md",
        "Test Blocked Milestone",
        "Ordered Tactical Queue",
        ["Credential-bound item"],
    )
    _run(tmp_path, "milestone-start", "--target", str(target), "--plan", blocked_plan)
    blocked = _run(
        tmp_path,
        "milestone-advance",
        "--target",
        str(target),
        "--event",
        "item-blocked",
        "--reason",
        "credential unavailable",
    )
    assert "next_action_type: true_blocker" in blocked.stdout
    assert "True blocker on item 1: credential unavailable" in blocked.stdout

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    abandoned_plan = _write_plan(
        target,
        "test-abandoned-pr-reprioritizes.md",
        "Test Abandoned PR Reprioritizes",
        "Ordered Tactical Queue",
        ["Abandoned PR item", "Auto-promoted successor"],
    )
    _run(tmp_path, "milestone-start", "--target", str(target), "--plan", abandoned_plan)
    _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-queued", "--pr", "900")
    abandoned = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-abandoned", "--pr", "900")
    assert abandoned.returncode == 0
    run = _milestone_run(target)
    items = {item["index"]: item for item in run["items"]}
    assert items[1]["status"] == "in_progress"
    assert items[2]["status"] == "pending"
    assert run["currentIndex"] == 1

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    queue_plan = _write_plan(
        target,
        "test-plain-queue-heading.md",
        "Test Plain Queue Heading",
        "Queue",
        ["Queue heading item"],
    )
    queue_start = _run(tmp_path, "milestone-start", "--target", str(target), "--plan", queue_plan)
    assert "next_action: Continue item 1: Queue heading item" in queue_start.stdout

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    missing_pr_plan = _write_plan(
        target,
        "test-missing-queued-event-recovery.md",
        "Test Missing Queued Event Recovery",
        "Ordered Tactical Queue",
        ["Recoverable PR item"],
    )
    _run(tmp_path, "milestone-start", "--target", str(target), "--plan", missing_pr_plan)
    recovered = _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-merged", "--pr", "777")
    assert "next_action_type: milestone_complete" in recovered.stdout
    item = _milestone_run(target)["items"][0]
    assert item["status"] == "merged"
    assert item["pr"] == "777"


def test_milestone_refresh_rejects_state_loss_retargeting_and_generic_implementation_plan(tmp_path):
    target, _adapter = _prepare_target(tmp_path)
    drift_plan = _write_plan(
        target,
        "test-stateful-refresh-drift.md",
        "Test Stateful Refresh Drift",
        "Ordered Tactical Queue",
        ["Original title"],
    )
    _run(tmp_path, "milestone-start", "--target", str(target), "--plan", drift_plan)
    _run(tmp_path, "milestone-advance", "--target", str(target), "--event", "pr-queued", "--pr", "555")
    _write_plan(
        target,
        "test-stateful-refresh-drift.md",
        "Test Stateful Refresh Drift",
        "Ordered Tactical Queue",
        ["Renamed title"],
    )
    drift = _run(tmp_path, "milestone-start", "--target", str(target), "--plan", drift_plan, check=False)
    assert drift.returncode == 1
    assert "milestone refresh would drop existing item state" in drift.stderr

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    plan_a = _write_plan(
        target,
        "test-retarget-a.md",
        "Test Retarget A",
        "Ordered Tactical Queue",
        ["Shared item title"],
    )
    plan_b = _write_plan(
        target,
        "test-retarget-b.md",
        "Test Retarget B",
        "Ordered Tactical Queue",
        ["Shared item title"],
    )
    _run(tmp_path, "milestone-start", "--target", str(target), "--plan", plan_a)
    retarget = _run(tmp_path, "milestone-start", "--target", str(target), "--plan", plan_b, check=False)
    assert retarget.returncode == 1
    assert "milestone refresh would retarget an existing ledger" in retarget.stderr

    (target / ".ai-work" / "MILESTONE_RUN.json").unlink()
    bad_plan = target / PLAN_ROOT / "test-implementation-plan-not-queue.md"
    bad_plan.write_text(
        """# Test Implementation Plan Is Not A Queue

## Milestone Goal
Validate queue parsing stays explicit.

## Implementation Plan
- [ ] This bullet must not become a milestone ledger item.

## Acceptance Criteria
- Only explicit tactical queue headings are accepted.
""",
        encoding="utf-8",
    )
    bad_queue = _run(
        tmp_path,
        "milestone-start",
        "--target",
        str(target),
        "--plan",
        str(PLAN_ROOT / "test-implementation-plan-not-queue.md"),
        check=False,
    )
    assert bad_queue.returncode == 1
    assert "no ordered tactical queue items" in bad_queue.stderr
