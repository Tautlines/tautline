"""RCA: run-plan-review invocations count toward the plan-review convergence target.

The target is two rounds; rounds 3-4 need a self-authorizing exception (a recorded note or a
detected convergence/rebinding state) to get past the runtime cap.
"""

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

    assert any("2-round convergence target is exhausted" in error for error in errors)
    assert any("no convergence exception applies" in error for error in errors)


def test_recorded_exception_reason_can_pass_runtime_cap(cli, tmp_path):
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
        exception_reason="R2 surfaced a structural Critical that must be re-reviewed",
    )

    assert errors == []


def test_voided_run_does_not_block_a_rebinding_round(cli, tmp_path):
    """A run the plan has moved past can never be finalized; refusing here would be a dead end."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = cli.plan_content_sha256(plan)
    _write_run_meta(cli, tmp_path, plan_rel, stale_hash, round_name="R1")
    plan.write_text("# Admin\n\n## Goal\n\nDo the work, correctly.\n", encoding="utf-8")
    plan_hash = cli.plan_content_sha256(plan)
    assert plan_hash != stale_hash

    errors = cli.plan_review_runtime_cap_errors(
        _data(), tmp_path, plan, plan_rel, plan_hash, "R1", 1
    )

    assert not any(
        "finalize that run instead of launching another one" in error for error in errors
    )
    assert (
        cli.plan_review_self_authorized_reason(_data(), tmp_path, plan, plan_rel, plan_hash)
        == "rebinding round after a voided run"
    )


def test_superseded_run_meta_is_not_treated_as_voided(cli):
    """The manifest binds one round, so earlier rounds are orphaned by design -- not voided."""
    manifest = {"round": "R2", "timestamp": "2026-07-14T10:00:00+00:00"}

    # R1 finalized, then superseded by R2: reviewed, not stranded.
    assert cli.plan_review_run_meta_superseded_by_manifest(
        {"round": "R1", "finished_at": "2026-07-14T09:00:00+00:00"}, manifest
    )
    # A run past the bound round that was never finalized: a genuine dead end.
    assert not cli.plan_review_run_meta_superseded_by_manifest(
        {"round": "R3", "finished_at": "2026-07-14T11:00:00+00:00"}, manifest
    )
    # No manifest at all: nothing supersedes the run.
    assert not cli.plan_review_run_meta_superseded_by_manifest({"round": "R1"}, None)


def test_superseded_run_meta_same_round_rerun_uses_the_finalization_time(cli):
    """A re-run of the bound round: only a run recorded AFTER the manifest is stranded."""
    manifest = {"round": "R2", "timestamp": "2026-07-14T10:00:00+00:00"}

    # The voided first attempt at R2, superseded by the R2 run that was finalized.
    assert cli.plan_review_run_meta_superseded_by_manifest(
        {"round": "R2", "finished_at": "2026-07-14T09:30:00+00:00"}, manifest
    )
    # A fresh R2 run recorded after the finalization, then voided by an edit.
    assert not cli.plan_review_run_meta_superseded_by_manifest(
        {"round": "R2", "finished_at": "2026-07-14T10:30:00+00:00"}, manifest
    )
    # Offsets must be compared as instants, not as strings: 06:30-04:00 == 10:30Z is LATER than
    # the 10:00Z finalization, even though it sorts earlier lexicographically.
    assert not cli.plan_review_run_meta_superseded_by_manifest(
        {"round": "R2", "finished_at": "2026-07-14T06:30:00-04:00"}, manifest
    )


@pytest.mark.parametrize(
    "meta, manifest",
    [
        ({"round": "R2", "finished_at": "2026-07-14T11:00:00+00:00"}, {"round": "", "timestamp": "x"}),
        ({"round": "", "finished_at": "2026-07-14T11:00:00+00:00"}, {"round": "R2", "timestamp": "x"}),
        # Naive timestamps are not comparable instants, so strandedness cannot be proven.
        ({"round": "R2", "finished_at": "2026-07-14T11:00:00"}, {"round": "R2", "timestamp": "2026-07-14T10:00:00"}),
        ({"round": "R2", "finished_at": ""}, {"round": "R2", "timestamp": "2026-07-14T10:00:00+00:00"}),
    ],
)
def test_unprovable_strandedness_fails_closed(cli, meta, manifest):
    """Unparseable state must NOT self-authorize: a fabricated reason becomes a false attestation.

    Refusing is recoverable -- the operator records a real reason. Fabricating is not.
    """
    assert cli.plan_review_run_meta_superseded_by_manifest(meta, manifest)


def test_hard_cap_refusal_is_unconditional_and_state_appropriate(cli):
    blocked = cli.plan_review_hard_cap_refusal(5, unresolved_blockers=True)
    clean = cli.plan_review_hard_cap_refusal(5, unresolved_blockers=False)

    for message in (blocked, clean):
        assert "exceeds the hard cap of 4 rounds" in message
        assert "no exception note, structural Critical, or operator authorization" in message
    assert "the split is mandatory" in blocked
    assert "smaller source-of-truth plans" in blocked
    assert "finalize the existing review evidence" in clean
    assert "the split is mandatory" not in clean


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
