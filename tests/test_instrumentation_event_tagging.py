"""T2 (0.9.0 sanitized instrumentation) scope note: current `plan_review_finalized` /
`implementation_review_finalized` `try_write_event(...)` call sites in bin/tautline do not carry a
structured verdict, so T2 adds `verdict` and unresolved-count fields to both -- tested here at the
emitters. The T3 reducer (not built yet) will later read these structured refs to choose
`plan_review_clean`/`plan_review_blocked` and `implementation_review_clean`/
`implementation_review_blocked` without ever parsing freeform text.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_ROOT = Path("docs/product/backlog/example-saas-v1/specs")
PLAN_REL = SOURCE_ROOT / "test-plan.md"
TEMPLATE_REL = Path("docs/product/backlog/templates/pr-execution-spec.template.md")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _run_cli(
    *args: str,
    home: Path,
    adapter_root: Path,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    env = {
        **{key: value for key, value in os.environ.items() if not key.startswith("MINERVIT_CODEX")},
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
    }
    result = subprocess.run([sys.executable, str(CLI_PATH), *args], env=env, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _events_jsonl_path(home: Path, adapter_data: dict, cli_module) -> Path:
    state_dir_template = adapter_data["observabilityEvents"]["stateDir"]
    state_dir = Path(state_dir_template.replace("$HOME", str(home)))
    return state_dir / cli_module.event_repo_slug(adapter_data) / adapter_data["observabilityEvents"]["jsonlLog"]


def _load_events(jsonl_path: Path) -> list[dict]:
    return [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# plan_review_finalized
# ---------------------------------------------------------------------------


def _write_plan_review_adapter(adapter_root: Path) -> tuple[Path, dict]:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for T2 plan-review event tagging.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": "$HOME/.local/state/tautline-test/plan-review-events",
    }
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
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
    adapter_root.mkdir(parents=True, exist_ok=True)
    adapter = adapter_root / "plan-review-tagging.json"
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter, data


def _write_review_script(target: Path, body: str) -> Path:
    path = target / "scripts" / "codex-review.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_plan(target: Path) -> Path:
    path = target / PLAN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Test Plan\n\n"
        "## Milestone Goal\nDeliver reviewed behavior safely.\n\n"
        "## Non-Goals\nDo not change production behavior outside the tested fixture.\n\n"
        "## Evidence And Sources\nUse the adapter, current backlog entry, and review logs as source evidence.\n\n"
        "## Assumptions\nThe test lane has a configured source-of-truth path and review wrapper.\n\n"
        "## Ordered Scope\n1. Build the fixture.\n2. Validate the gate.\n3. Record the review evidence.\n\n"
        "## Dependencies\nThe plan depends on the configured adapter review wrapper and local lane files.\n\n"
        "## Acceptance Criteria\nThe plan finalization precheck passes after clean review evidence.\n\n"
        "## Tests And Validation\nRun behavior and implementation gates.\n\n"
        "## Review And Merge Gates\nCross-model review must be recorded before finalization.\n\n"
        "## Risks\nThe main risk is accepting stale review evidence.\n\n"
        "## Open Decisions\nNone.\n\n"
        "## Behavior Source Materials\n"
        "- `docs/product/user-scenarios.md`: reviewed and split into shop-owner/platform-admin role scenarios where needed.\n"
        "- `docs/product/acceptance-criteria.md`: reviewed and preserved for customer role expectations.\n\n"
        "## Completion Definition\nDone means the precheck accepts clean current evidence.\n",
        encoding="utf-8",
    )
    return path


def _prepare_plan_review_target(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "target"
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    (target / SOURCE_ROOT).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")
    _write_review_script(target, "printf 'Codex review args: %s\\n' \"$*\"\nprintf '## Findings\\n'\nprintf 'Verdict: clean\\n'\nprintf 'No Critical or P1 findings.\\n'\n")
    _write_plan(target)
    adapter, adapter_data = _write_plan_review_adapter(adapter_root)
    return home, adapter_root, target, adapter_data, adapter


def _stdout_path(stdout: str, prefix: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"missing output line {prefix!r} in:\n{stdout}")


def test_plan_review_finalized_event_carries_clean_verdict_and_zero_counts(tmp_path, cli):
    home, adapter_root, target, adapter_data, adapter = _prepare_plan_review_target(tmp_path)
    run = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    log_path = _stdout_path(run.stdout, "plan_review_run_log")
    _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )

    jsonl_path = _events_jsonl_path(home, adapter_data, cli)
    records = _load_events(jsonl_path)
    finalized = [record for record in records if record["event"] == "plan_review_finalized"]
    assert finalized, records
    last = finalized[-1]
    assert last["refs"]["verdict"] == "clean"
    assert last["refs"]["unresolved_critical_count"] == "0"
    assert last["refs"]["unresolved_p1_count"] == "0"
    assert last["severity"] == "ok"


def test_plan_review_finalized_event_carries_blocked_verdict_and_nonzero_counts(tmp_path, cli):
    home, adapter_root, target, adapter_data, adapter = _prepare_plan_review_target(tmp_path)
    run = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    log_path = _stdout_path(run.stdout, "plan_review_run_log")
    findings_json = json.dumps([{"severity": "critical", "status": "open", "summary": "a structural blocker"}])
    _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        "1",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        findings_json,
        home=home,
        adapter_root=adapter_root,
    )

    jsonl_path = _events_jsonl_path(home, adapter_data, cli)
    records = _load_events(jsonl_path)
    finalized = [record for record in records if record["event"] == "plan_review_finalized"]
    assert finalized, records
    last = finalized[-1]
    assert last["refs"]["verdict"] == "blocked"
    assert last["refs"]["unresolved_critical_count"] == "1"
    assert last["refs"]["unresolved_p1_count"] == "0"
    assert last["severity"] == "block"


# ---------------------------------------------------------------------------
# implementation_review_finalized
# ---------------------------------------------------------------------------


def _write_implementation_review_adapter(adapter_root: Path) -> tuple[Path, dict]:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for T2 implementation-review event tagging.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    data["observabilityEvents"] = {
        **data.get("observabilityEvents", {}),
        "stateDir": "$HOME/.local/state/tautline-test/implementation-review-events",
    }
    # item 37 R2: this fixture exercises implementation-review EVENT TAGGING, and its lane has
    # never run a suite. Test-evidence enforcement defaults to block and now gates a push-eligible
    # finalize, so leaving it on would refuse these finalizes for a reason unrelated to the events
    # under test.
    data["testEvidence"] = {**(data.get("testEvidence") or {}), "enforcement": "off"}
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
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
    adapter_root.mkdir(parents=True, exist_ok=True)
    adapter = adapter_root / "implementation-review-tagging.json"
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter, data


def _prepare_implementation_review_target(tmp_path: Path, cli) -> tuple[Path, Path, Path, dict, Path, dict, Path]:
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "target"
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    (target / "README.md").write_text("base\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-qm", "base")
    _git(target, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(target, "checkout", "-qb", "feature/t2-tagging")
    (target / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(target, "add", "feature.txt")
    _git(target, "commit", "-qm", "feature")

    adapter, adapter_data = _write_implementation_review_adapter(adapter_root)

    state, errors = cli.implementation_review_state(target, "origin/main")
    assert errors == [], errors
    assert state is not None

    note = (
        "Stage 1 native review inspected the current assembled diff and found no blockers "
        "before the Codex implementation review."
    )
    log_path = target / "review.log"
    log_path.write_text("review log\n", encoding="utf-8")
    sweep_path = target / "stage1-sweep.json"
    sweep_path.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_STAGE1_SWEEP_SCHEMA,
                "stage": cli.IMPLEMENTATION_STAGE1_SWEEP_STAGE,
                "recorded_by": "tautline record-stage1-sweep",
                "branch": state["branch"],
                "base_sha": state["base_sha"],
                "head_sha": state["head_sha"],
                "diff_sha256": state["diff_sha256"],
                "native_review_note": note,
                "classes": [
                    {
                        "class": "process integrity",
                        "members_checked": "review manifest compatibility fields for T2 event-tagging fixture",
                        "status": "clean",
                    }
                ],
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "recorded_at": "2026-07-10T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    evidence_dir = target / cli.IMPLEMENTATION_REVIEW_DIR
    evidence_dir.mkdir(parents=True)
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
                "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
                "reviewer": "codex",
                "recorded_by": "tautline codex-run",
                "branch": state["branch"],
                "base_sha": state["base_sha"],
                "head_sha": state["head_sha"],
                "diff_sha256": state["diff_sha256"],
                "review_command": "./scripts/codex-review.sh",
                "review_wrapper": "./scripts/codex-review.sh",
                "risk_tier": "T1",
                "review_round": "R1",
                "native_review_required": True,
                "native_review_requirement": "Stage 1 native/Superpowers review on current assembled diff before this Stage 2 Codex round",
                "native_review_note": note,
                "stage1_sweep_required": True,
                "stage1_sweep_path": sweep_path.name,
                "stage1_sweep_sha256": cli.file_sha256(sweep_path),
                "log_path": log_path.name,
                "log_sha256": cli.file_sha256(log_path),
                "wrapper_exit_code": 0,
                "finished_at": "2026-07-10T00:00:01+00:00",
                "plugin_version": cli.plugin_version(),
            }
        ),
        encoding="utf-8",
    )
    return home, adapter_root, target, adapter_data, adapter, state, manifest_path


def test_implementation_review_finalized_event_carries_clean_verdict_and_zero_counts(tmp_path, cli):
    home, adapter_root, target, adapter_data, adapter, state, manifest_path = _prepare_implementation_review_target(tmp_path, cli)

    # 0.52.0: `clean-with-deferrals` records deferrals, so it now requires the findings file with
    # at least one finding. This fixture deferred nothing and passed no flag, which is exactly the
    # producer hole that release closed -- so it records what it means: one out-of-AC P2, routed at
    # honest severity. The event assertions below are unchanged.
    findings_path = target / "classified-findings.json"
    findings_path.write_text(
        json.dumps(
            [
                {
                    "id": "F1",
                    "severity": "p2",
                    "summary": "naming nit outside this item's acceptance criteria",
                    "ac_ref": None,
                    "disposition": "routed",
                    "routed_to": "ROW-1",
                }
            ]
        ),
        encoding="utf-8",
    )
    _run_cli(
        "finalize-implementation-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--manifest",
        str(manifest_path),
        "--base",
        "origin/main",
        "--verdict",
        "clean-with-deferrals",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        str(findings_path),
        home=home,
        adapter_root=adapter_root,
    )

    jsonl_path = _events_jsonl_path(home, adapter_data, cli)
    records = _load_events(jsonl_path)
    finalized = [record for record in records if record["event"] == "implementation_review_finalized"]
    assert finalized, records
    last = finalized[-1]
    assert last["refs"]["verdict"] == "clean-with-deferrals"
    assert last["refs"]["unresolved_critical_count"] == "0"
    assert last["refs"]["unresolved_p1_count"] == "0"
    assert last["severity"] == "ok"


def test_implementation_review_finalized_event_carries_blocked_verdict_and_nonzero_counts(tmp_path, cli):
    home, adapter_root, target, adapter_data, adapter, state, manifest_path = _prepare_implementation_review_target(tmp_path, cli)

    result = _run_cli(
        "finalize-implementation-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--manifest",
        str(manifest_path),
        "--base",
        "origin/main",
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        "2",
        "--unresolved-p1-count",
        "1",
        home=home,
        adapter_root=adapter_root,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr

    jsonl_path = _events_jsonl_path(home, adapter_data, cli)
    records = _load_events(jsonl_path)
    finalized = [record for record in records if record["event"] == "implementation_review_finalized"]
    assert finalized, records
    last = finalized[-1]
    assert last["refs"]["verdict"] == "blocked"
    assert last["refs"]["unresolved_critical_count"] == "2"
    assert last["refs"]["unresolved_p1_count"] == "1"
    assert last["severity"] == "block"
