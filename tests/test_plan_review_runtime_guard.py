"""RCA: run-plan-review invocations count toward the two-round plan-review cap."""

import json

import pytest


def _data():
    return {
        "project": "example",
        "laneState": {"runsDir": ".ai-runs"},
        "planningArtifacts": {"sourceOfTruth": "backlog/plans"},
    }


def _plan(tmp_path):
    path = tmp_path / "backlog" / "plans" / "admin.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Admin\n\n## Goal\n\nDo the work.\n", encoding="utf-8")
    return path


def _write_run_meta(cli, tmp_path, plan_rel, plan_hash, *, idx=1, round_name="R1", exit_code=0):
    runs = tmp_path / ".ai-runs" / "plan-review"
    runs.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": cli.PLAN_REVIEW_RUN_SCHEMA,
        "plan_path": plan_rel,
        "plan_content_sha256": plan_hash,
        "review_scope": "plan-only",
        "code_diff_review": False,
        "review_command": "codex-review --plan backlog/plans/admin.md",
        "log_path": f".ai-runs/plan-review/run-{idx}.log",
        "log_sha256": "x",
        "wrapper_exit_code": exit_code,
        "round": round_name,
    }
    path = runs / f"run-{idx}.meta.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def test_unfinalized_successful_round_blocks_duplicate_run(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    _write_run_meta(cli, tmp_path, plan_rel, plan_hash, round_name="R1")

    errors = cli.plan_review_runtime_cap_errors(_data(), tmp_path, plan, plan_rel, plan_hash, "R1", 1)

    assert any("existing successful Codex run for R1 is not finalized" in error for error in errors)


def test_two_successful_runs_without_clean_manifest_exhausts_runtime_cap(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    for idx in range(1, 3):
        _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=idx, round_name=f"R{idx}")

    errors = cli.plan_review_runtime_cap_errors(_data(), tmp_path, plan, plan_rel, plan_hash, "R2", 2)

    assert any("two-round runtime cap is exhausted" in error for error in errors)


def test_r3_structural_critical_exception_can_pass_runtime_cap(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    for idx in range(1, 3):
        _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=idx, round_name=f"R{idx}")

    errors = cli.plan_review_runtime_cap_errors(
        _data(),
        tmp_path,
        plan,
        plan_rel,
        plan_hash,
        "R3",
        3,
        allow_r3_structural_critical=True,
    )

    assert not any("two-round runtime cap is exhausted" in error for error in errors)


def test_finalized_manifest_allows_same_round_without_duplicate_error(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    meta_path = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, round_name="R1")
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "round": "R1",
                "verdict": "clean",
                "plan_content_sha256": plan_hash,
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "review_run_meta_path": meta_path.relative_to(tmp_path).as_posix(),
            }
        ),
        encoding="utf-8",
    )

    errors = cli.plan_review_runtime_cap_errors(_data(), tmp_path, plan, plan_rel, plan_hash, "R1", 1)

    assert not any("existing successful Codex run" in error for error in errors)


def test_plan_review_manifest_write_is_atomic_when_evidence_mutates_plan_hash(cli, tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    log_path = tmp_path / ".ai-runs" / "plan-review" / "review.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("review clean\n", encoding="utf-8")
    original_plan_text = plan.read_text(encoding="utf-8")
    original_upsert = cli.upsert_plan_review_evidence

    def mutating_upsert(text: str, replacement_body: str) -> str:
        return original_upsert(text, replacement_body) + "\n## Unexpected Mutation\n\nThis changes reviewed content.\n"

    monkeypatch.setitem(
        cli.write_plan_review_manifest.__globals__,
        "upsert_plan_review_evidence",
        mutating_upsert,
    )
    plan_hash = cli.plan_content_sha256(plan)

    with pytest.raises(SystemExit) as excinfo:
        cli.write_plan_review_manifest(
            data=_data(),
            target=tmp_path,
            plan_path=plan,
            plan_rel=plan_rel,
            plan_hash=plan_hash,
            log_path=log_path,
            review_command="./scripts/codex-review.sh --plan backlog/plans/admin.md",
            reviewer="codex",
            model="codex",
            review_round="R1",
            wrapper_exit_code=0,
            verdict="clean",
            unresolved_critical_count=0,
            unresolved_p1_count=0,
            findings=[],
            recorded_by="minervit-methodology run-plan-review",
        )

    message = str(excinfo.value)
    assert "Cross-Model Review Evidence update would change normalized plan content hash" in message
    assert "no manifest or plan evidence was written" in message
    assert not cli.plan_review_manifest_path(_data(), tmp_path, plan).exists()
    assert plan.read_text(encoding="utf-8") == original_plan_text
