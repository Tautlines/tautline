"""RCA: run-plan-review invocations count toward the plan-review convergence target.

The target is two rounds; rounds 3-4 need a self-authorizing exception (a recorded note or a
detected convergence/rebinding state) to get past the runtime cap.
"""

import io
import json
import shutil
from pathlib import Path

import pytest


FIXTURE_ADAPTER = Path(__file__).parent / "fixtures" / "generated-adapter-example-saas.json"


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


def _bind_clean_manifest(cli, tmp_path, plan, meta_path, plan_hash, *, round_name="R2"):
    """A clean, finalized manifest bound at plan_hash and meta_path -- the state that
    supersedes every run so no self-authorized round remains."""
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "round": round_name,
                "verdict": "clean",
                "plan_content_sha256": plan_hash,
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "review_run_meta_path": meta_path.relative_to(tmp_path).as_posix(),
                "timestamp": "2026-07-17T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_runtime_cap_with_stale_hash_prints_successor_instruction(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    r2_meta = None
    for idx in range(1, 3):
        r2_meta = _write_run_meta(
            cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name=f"R{idx}"
        )
    plan_hash = cli.plan_content_sha256(plan)
    # The GENUINE deadlock: a clean round was bound at the old hash, then the plan was edited
    # away from it. The clean manifest supersedes every run, so no self-authorized round
    # remains -- run-plan-review would refuse a rerun and the successor path is the only exit.
    # (A no-manifest state instead self-authorizes a rebinding round, so it is NOT stale-at-cap.)
    _bind_clean_manifest(cli, tmp_path, plan, r2_meta, stale_hash)

    errors = cli.plan_review_runtime_cap_errors(
        _data(), tmp_path, plan, plan_rel, plan_hash, "R2", 2
    )

    assert any("create a successor source-of-truth plan" in error for error in errors)
    assert not any(
        "carry unresolved findings into the implementation review focus list" in error
        for error in errors
    )


def test_no_manifest_stale_runs_is_not_stale_at_cap(cli, tmp_path):
    """0.10.5 Codex R2: two stale runs with NO bound manifest self-authorize a rebinding
    round in run-plan-review (reason: a voided run to rebind), so the recovery predicate must
    NOT call it stale-at-cap -- doing so would tell the operator to split the plan while the
    actual gate happily allows the rerun. The successor path requires a clean bound round."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    for idx in range(1, 3):
        _write_run_meta(cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name=f"R{idx}")
    plan_hash = cli.plan_content_sha256(plan)
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is False


def test_runtime_cap_with_matching_run_keeps_focus_transfer_instruction(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    for idx in range(1, 3):
        _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=idx, round_name=f"R{idx}")

    errors = cli.plan_review_runtime_cap_errors(
        _data(), tmp_path, plan, plan_rel, plan_hash, "R2", 2
    )

    assert any(
        "carry unresolved findings into the implementation review focus list" in error
        for error in errors
    )
    assert not any("create a successor source-of-truth plan" in error for error in errors)


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


def test_pending_unfinalized_run_blocks_plan_edit(cli, tmp_path):
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    _write_run_meta(cli, tmp_path, plan_rel, plan_hash, round_name="R1")

    reason = cli.plan_review_pending_block_reason(_data(), tmp_path, plan)

    assert reason is not None
    assert "awaiting finalize-plan-review" in reason
    assert "finalize" in reason


def test_manifest_bound_run_allows_plan_edit(cli, tmp_path):
    # Reuses the manifest-binding setup from
    # test_finalized_manifest_allows_same_round_without_duplicate_error.
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

    assert cli.plan_review_pending_block_reason(_data(), tmp_path, plan) is None


def test_no_runs_allow_plan_edit(cli, tmp_path):
    plan = _plan(tmp_path)
    assert cli.plan_review_pending_block_reason(_data(), tmp_path, plan) is None


def test_stale_pending_run_does_not_block_plan_edit(cli, tmp_path):
    # A run meta whose recorded hash differs from current content is already void:
    # editing the plan changes nothing, so the guard must stay out of the way. This is
    # the load-bearing scoping test -- it proves the guard fires only in the window
    # between a successful run and its finalize.
    plan = _plan(tmp_path)
    _write_run_meta(cli, tmp_path, "backlog/plans/admin.md", "0" * 64, round_name="R1")
    assert cli.plan_review_pending_block_reason(_data(), tmp_path, plan) is None


def test_pending_hook_blocks_edit_via_stdin_payload(cli, tmp_path, monkeypatch, capsys):
    # Wrapper-level integration following the wedge-test idiom: a full PreToolUse stdin
    # payload for an Edit of a reviewed plan with a pending (unfinalized) successful run
    # must emit the block JSON; a payload for an unrelated file must pass silently.
    lane = tmp_path / "lane"
    lane.mkdir()
    shutil.copy(FIXTURE_ADAPTER, lane / ".minervit-ai-delivery.json")
    plan = lane / "docs" / "product" / "backlog" / "example-saas-v1-readiness" / "specs" / "admin.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Admin\n\n## Goal\n\nDo the work.\n", encoding="utf-8")
    plan_rel = cli.path_relative_to_target(lane, plan)
    plan_hash = cli.plan_content_sha256(plan)
    _write_run_meta(cli, lane, plan_rel, plan_hash, round_name="R1")

    def run_hook(file_path):
        payload = {"tool_name": "Edit", "cwd": str(lane), "tool_input": {"file_path": file_path}}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        capsys.readouterr()
        assert cli.plan_review_pending_hook(None) == 0
        return capsys.readouterr().out

    out = run_hook(str(plan))
    assert '"decision": "block"' in out
    assert "awaiting finalize-plan-review" in out
    assert '"decision": "block"' not in run_hook(str(lane / "README.md"))


def test_write_claude_plan_review_pending_hook_installs_idempotently(cli, tmp_path):
    # Task 8 install wiring, mirroring the latest-code wedge install test: the writer
    # must add one Edit|Write|MultiEdit PreToolUse entry into a settings file that
    # already carries other hooks, preserve those hooks, and re-install idempotently.
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "tautline background-command-hook"}
                            ],
                        },
                        {
                            "matcher": "ExitPlanMode",
                            "hooks": [
                                {"type": "command", "command": "tautline plan-finalization-hook"}
                            ],
                        },
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert cli.settings_plan_review_pending_hook_installed(
        json.loads(settings.read_text(encoding="utf-8"))
    ) is False

    path, already_present = cli.write_claude_plan_review_pending_hook(
        settings, "tautline plan-review-pending-hook"
    )
    assert path == settings
    assert already_present is False
    data = json.loads(settings.read_text(encoding="utf-8"))
    pending_entries = [
        entry
        for entry in data["hooks"]["PreToolUse"]
        if "plan-review-pending-hook" in json.dumps(entry)
    ]
    assert len(pending_entries) == 1
    assert pending_entries[0]["matcher"] == "Edit|Write|MultiEdit"
    assert pending_entries[0]["hooks"] == [
        {"type": "command", "command": "tautline plan-review-pending-hook"}
    ]
    assert cli.settings_plan_review_pending_hook_installed(data) is True
    # Pre-existing hooks survive the install untouched.
    assert any(
        entry.get("matcher") == "Bash" and "background-command-hook" in json.dumps(entry)
        for entry in data["hooks"]["PreToolUse"]
    )
    assert any(
        entry.get("matcher") == "ExitPlanMode" and "plan-finalization-hook" in json.dumps(entry)
        for entry in data["hooks"]["PreToolUse"]
    )

    path, already_present = cli.write_claude_plan_review_pending_hook(
        settings, "tautline plan-review-pending-hook"
    )
    assert path == settings
    assert already_present is True
    rewritten = json.loads(settings.read_text(encoding="utf-8"))
    assert rewritten == data


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


def test_plan_review_pending_hook_state_reports_missing(cli, tmp_path, monkeypatch):
    """Codex R1 (0.10.5): the guard hook must be gated like every other required
    hook -- pre-0.10.5 settings without it must surface as a hook failure in
    methodology-status, not report OK with the advertised guard silently absent."""
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    installed, status = cli.claude_plan_review_pending_hook_state(tmp_path / "target")
    assert installed is False
    assert "missing required hook" in status and "install-hooks" in status


def test_plan_review_pending_hook_state_reports_installed(cli, tmp_path, monkeypatch):
    import json as _json

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: home))
    settings_path = home / ".claude" / "settings.json"
    _, _ = cli.write_claude_plan_review_pending_hook(settings_path, "tautline plan-review-pending-hook")
    settings = _json.loads(settings_path.read_text(encoding="utf-8"))
    assert cli.settings_plan_review_pending_hook_installed(settings)
    installed, status = cli.claude_plan_review_pending_hook_state(tmp_path / "target")
    assert installed is True and "installed" in status


def test_finalized_plan_edit_not_blocked_by_superseded_same_hash_run(cli, tmp_path):
    """0.10.5 Codex R1 (P1): R1 and R2 review the SAME content and the manifest binds
    R2 clean. Editing the finalized plan must NOT block on R1 looking 'unfinalized' --
    R1 is superseded by the bound manifest, not stranded. Blocking here would be a NEW
    false-block on a finalized plan, the exact class this release exists to remove."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=1, round_name="R1")
    r2_meta = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=2, round_name="R2")
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "round": "R2",
                "verdict": "clean",
                "plan_content_sha256": plan_hash,
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "review_run_meta_path": r2_meta.relative_to(tmp_path).as_posix(),
                "timestamp": "2026-07-17T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert cli.plan_review_pending_block_reason(_data(), tmp_path, plan) is None


def test_sha_stale_at_cap_false_when_blockers_addressed_after_final_round(cli, tmp_path):
    """0.10.5 Codex R1 (P2): after a BLOCKED final round, editing the plan to fix the
    blockers is the valid self-authorized convergence round -- not a dead end. The
    successor-plan instruction must not fire and push an unnecessary plan split for the
    standard fix-after-blockers flow."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    old_hash = "0" * 64
    for idx in range(1, 3):
        _write_run_meta(cli, tmp_path, plan_rel, old_hash, idx=idx, round_name=f"R{idx}")
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "round": "R2",
                "verdict": "blocked",
                "plan_content_sha256": old_hash,
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 1,
                "review_run_meta_path": ".ai-runs/plan-review/run-2.meta.json",
                "timestamp": "2026-07-17T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    plan_hash = cli.plan_content_sha256(plan)
    assert plan_hash != old_hash
    assert (
        cli.plan_review_self_authorized_reason(_data(), tmp_path, plan, plan_rel, plan_hash)
        == "blockers addressed after final bound round"
    )
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is False


def test_sha_stale_at_cap_true_at_hard_cap_even_with_voided_run(cli, tmp_path):
    """0.10.6 Codex R1 (P2): at the hard cap, run-plan-review refuses another round
    UNCONDITIONALLY, so even a 'rebinding round after a voided run' self-authorization
    cannot produce a round -- the successor path is the only exit and sha_stale_at_cap must
    say so, or precheck/ExitPlanMode recovery would tell the operator to rerun a review the
    hard cap will refuse (the mirror of the deadlock this whole line of work removes)."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    for idx in range(1, cli.PLAN_REVIEW_HARD_CAP_ROUNDS + 1):
        _write_run_meta(cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name=f"R{idx}")
    plan_hash = cli.plan_content_sha256(plan)
    # A self-authorized reason exists (no manifest, voided runs) but no round is available.
    assert cli.plan_review_self_authorized_reason(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is True


def test_same_round_reruns_spend_the_budget_and_route_to_the_successor(cli, tmp_path):
    """SUPERSEDES the 0.10.7 (0.10.6 Codex R2) rule that same-round RERUNS were free.

    That rule keyed the budget on the highest round LABEL reached, so four metas reaching only
    `R2` left `R3`/`R4` notionally available. The budget is now counted in reviewer INVOCATIONS
    (item 24: plan-review round advance gap): four successful runs are the whole budget however
    they were labelled, because each one consumed a reviewer. A lane in this state has no round
    left, so the successor plan is the correct routing -- and `sha_stale_at_cap` must say so, or
    it would advertise a round `run-plan-review` will refuse.

    The concern the old rule protected against -- being told to split while a round remained --
    is preserved by `test_next_round_inside_the_hard_cap_is_available_despite_rerun_count`, which
    still passes with a budget that is genuinely unspent.
    """
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    # four successful invocations, whatever they were labelled -> budget spent
    for idx, rnd in enumerate([1, 1, 2, 2], start=1):
        _write_run_meta(cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name=f"R{rnd}")
    plan_hash = cli.plan_content_sha256(plan)
    assert cli.plan_review_self_authorized_reason(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is True
    # And the gate agrees: a fifth launch under any label is refused.
    assert cli.plan_review_round_cap_errors(round_number=1, observed_runs=4, declared_label="R1")


def test_next_round_inside_the_hard_cap_is_available_despite_rerun_count(cli, tmp_path):
    """Two `R1` reruns over a STALE hash self-authorize a rebinding round (reason: a voided run
    to rebind). Two invocations are spent, so the next one is round 3 -- past the two-round
    TARGET but inside the four-round hard cap -- and a round is therefore available, so this is
    not stale-at-cap. (The old name said "within target"; under the invocation-counted budget the
    next round here is 3, not 2, and what the assertion shows is headroom against the hard cap.)
    Contrast the clean-manifest case below, which has no self-authorized reason left and IS the
    successor deadlock."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    for idx in (1, 2):
        _write_run_meta(cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name="R1")
    plan_hash = cli.plan_content_sha256(plan)
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is False


def test_stale_clean_manifest_after_same_round_reruns_is_successor(cli, tmp_path):
    """0.10.7 Codex R1: two R1 reruns, then a CLEAN manifest binds the old hash and the plan
    is edited. No self-authorized reason remains (a clean manifest supersedes the runs), and
    the runtime cap's COUNT-based target refuses another run since len(records) >= target --
    so neither rerun nor finalize can succeed and the successor path is the only exit, even
    though the next round (3 under the invocation-counted budget: two spent plus one) is still
    inside the hard cap. sha_stale_at_cap must agree with the runtime cap here, not with the
    round number alone."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    stale_hash = "0" * 64
    r_meta = None
    for idx in (1, 2):
        r_meta = _write_run_meta(cli, tmp_path, plan_rel, stale_hash, idx=idx, round_name="R1")
    _bind_clean_manifest(cli, tmp_path, plan, r_meta, stale_hash, round_name="R1")
    plan_hash = cli.plan_content_sha256(plan)
    assert plan_hash != stale_hash
    assert not cli.plan_review_self_authorized_reason(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert cli.plan_review_sha_stale_at_cap(_data(), tmp_path, plan, plan_rel, plan_hash) is True


# --- item 24 (plan-review round advance gap): the budget counts invocations, not labels -------


def test_repeated_label_cannot_exceed_the_hard_cap(cli, tmp_path):
    """The live shape from the lane that spent ten invocations on one plan: every round declared
    `R1`, so `plan_review_round_number` read 1 every time and the hard cap never engaged. Four
    successful runs are the whole budget however they are labelled; the fifth launch is refused."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    for idx in range(1, cli.PLAN_REVIEW_HARD_CAP_ROUNDS + 1):
        # distinct hashes: each round reviewed different content, as a fix-then-rerun loop does
        _write_run_meta(cli, tmp_path, plan_rel, f"{idx}" * 64, idx=idx, round_name="R1")
    plan_hash = cli.plan_content_sha256(plan)
    observed = cli.plan_review_observed_run_count(_data(), tmp_path, plan_rel)
    assert observed == cli.PLAN_REVIEW_HARD_CAP_ROUNDS
    errors = cli.plan_review_round_cap_errors(
        round_number=1, observed_runs=observed, declared_label="R1"
    )
    assert errors, "a fifth invocation under a repeated label must be refused"
    assert "exceeds the hard cap of 4 rounds" in errors[0]
    # And the runtime gate refuses it too, so neither path alone is load-bearing.
    runtime = cli.plan_review_runtime_cap_errors(
        _data(), tmp_path, plan, plan_rel, plan_hash, "R1", 1
    )
    assert any("exceeds the hard cap" in error for error in runtime)


def test_effective_round_leaves_a_lane_inside_budget_untouched(cli):
    """Inside budget nothing changes -- and "unchanged" is not "silent". Rounds 1-2 return no
    errors; rounds 3-4 WITHOUT a recorded note keep the convergence-target refusal they give
    today; rounds 3-4 WITH one return no errors. Asserting emptiness across 1..4 would force the
    exception-note ladder to be weakened, which this work does not touch."""
    note = "R3 needed because the previous round's blockers were fixed and need confirming."
    for observed in range(0, cli.PLAN_REVIEW_HARD_CAP_ROUNDS):
        for declared in (1, 2):
            assert (
                cli.plan_review_round_cap_errors(round_number=declared, observed_runs=observed)
                == []
            ), f"declared R{declared} with {observed} records must stay clean"
        for declared in (3, 4):
            effective = cli.plan_review_effective_round(declared, observed)
            if effective > cli.PLAN_REVIEW_HARD_CAP_ROUNDS:
                continue
            refused = cli.plan_review_round_cap_errors(
                round_number=declared, observed_runs=observed
            )
            assert refused and "past the 2-round convergence target" in refused[0]
            assert (
                cli.plan_review_round_cap_errors(
                    round_number=declared, observed_runs=observed, exception_reason=note
                )
                == []
            )


def test_failed_and_stale_runs_do_not_spend_the_budget(cli, tmp_path):
    """Only invocations that produced a review count. A wrapper failure and a watchdog kill
    (exit 124) produced nothing, so charging the budget for them would cap a lane that never
    got a round."""
    _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    _write_run_meta(cli, tmp_path, plan_rel, "a" * 64, idx=1, round_name="R1")
    _write_run_meta(cli, tmp_path, plan_rel, "b" * 64, idx=2, round_name="R2", exit_code=1)
    _write_run_meta(cli, tmp_path, plan_rel, "c" * 64, idx=3, round_name="R2", exit_code=124)
    assert cli.plan_review_observed_run_count(_data(), tmp_path, plan_rel) == 1


def test_hard_cap_refusal_names_the_declared_label_and_the_count(cli):
    """K3: a refusal that does not say what it counted cannot be acted on. The label is quoted
    verbatim -- `R01` parses to 1 but is not what the caller typed."""
    errors = cli.plan_review_round_cap_errors(
        round_number=1, observed_runs=5, declared_label="R01"
    )
    assert errors
    assert "5 successful review run(s)" in errors[0]
    assert "R01" in errors[0]
    assert "the split is mandatory" in errors[0]


def test_cap_refusal_points_at_a_finalizable_run_instead_of_the_split(cli, tmp_path):
    """The budget is spent, but an unbound successful run matches the CURRENT plan content --
    so `finalize-plan-review` is the exit that works from here. Telling this lane to decompose
    would send it away from a working remedy, which is the failure class the whole ladder
    exists to remove."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    for idx in range(1, cli.PLAN_REVIEW_HARD_CAP_ROUNDS):
        _write_run_meta(cli, tmp_path, plan_rel, f"{idx}" * 64, idx=idx, round_name="R1")
    # the newest run reviewed the plan as it stands now, and nothing has bound it
    _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=9, round_name="R1")
    pending = cli.plan_review_finalizable_run_meta(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert pending is not None
    command = cli.plan_review_finalize_command(tmp_path, plan_rel, pending)
    errors = cli.plan_review_round_cap_errors(
        round_number=1,
        observed_runs=cli.plan_review_observed_run_count(_data(), tmp_path, plan_rel),
        declared_label="R1",
        finalizable_command=command,
    )
    assert errors
    assert "bind it instead of splitting" in errors[0]
    assert "finalize-plan-review" in errors[0]
    assert "--log" in errors[0], "a path alone is not an action; the command must be runnable"
    assert "the split is mandatory" not in errors[0]


def test_finalize_and_record_are_not_capped_by_observed_runs(cli):
    """A round is spent by LAUNCHING a reviewer, not by binding evidence. Both writers call this
    gate without an observed count, so a lane past the budget can still finalize what it holds --
    without this default, the cap would strand evidence and recreate the deadlock."""
    assert cli.plan_review_round_cap_errors(round_number=1) == []
    assert cli.plan_review_round_cap_errors(round_number=2) == []


def test_successor_plan_path_is_reachable_at_the_spent_budget(cli, tmp_path):
    """The exit the refusal names has to work: a successor source-of-truth plan is a different
    plan_path, so it starts with an unspent budget."""
    _plan(tmp_path)
    spent_rel = "backlog/plans/admin.md"
    for idx in range(1, cli.PLAN_REVIEW_HARD_CAP_ROUNDS + 1):
        _write_run_meta(cli, tmp_path, spent_rel, f"{idx}" * 64, idx=idx, round_name="R1")
    successor_rel = "backlog/plans/admin-v2.md"
    assert cli.plan_review_observed_run_count(_data(), tmp_path, successor_rel) == 0
    assert (
        cli.plan_review_round_cap_errors(
            round_number=1,
            observed_runs=cli.plan_review_observed_run_count(_data(), tmp_path, successor_rel),
        )
        == []
    )


def test_legacy_run_meta_carries_no_ledger_fields(cli, tmp_path):
    """Every run meta on disk predates the ledger. Reading one must yield "absent", never a
    guessed number, so finalizing pre-release evidence keeps working and its manifest simply
    omits the keys."""
    _plan(tmp_path)
    meta_path = _write_run_meta(cli, tmp_path, "backlog/plans/admin.md", "a" * 64, idx=1)
    assert cli.plan_review_run_meta_ledger_value(meta_path, "observed_successful_runs") is None
    assert cli.plan_review_run_meta_ledger_value(meta_path, "effective_round") is None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["observed_successful_runs"] = 3
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert cli.plan_review_run_meta_ledger_value(meta_path, "observed_successful_runs") == 3


def test_finalize_command_for_a_past_target_run_carries_the_exception_flag(cli, tmp_path):
    """0.22.0 implementation review R1 P2: past the two-round target, finalize itself demands a
    recorded exception, so a printed command without `--exception-note` fails before binding
    anything. A remedy that is not runnable is the failure class this ladder removes."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    meta_path = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=3, round_name="R3")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["exception_reason"] = "R2 blockers were fixed and this round confirms convergence."
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    command = cli.plan_review_finalize_command(tmp_path, plan_rel, meta_path)

    assert "--exception-note" in command
    assert "confirms convergence" in command, "the recorded reason is reused, not invented"


def test_finalize_command_within_target_has_no_exception_flag(cli, tmp_path):
    """Inside the target the flag is not required, and offering it would invite a needless
    recorded exception on a round that does not need one."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    meta_path = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=1, round_name="R1")

    assert "--exception-note" not in cli.plan_review_finalize_command(tmp_path, plan_rel, meta_path)


def test_finalizable_run_is_chosen_by_time_not_by_label(cli, tmp_path):
    """0.22.0 implementation review R2 P2: in a relabelled lane a current-hash run recorded AFTER
    an R3 manifest can still be labelled `R1`. Ordering candidates by the declared label would
    discard it as superseded and print "split", while finalize-plan-review would bind it happily.
    This release exists because labels do not track reality; this predicate must not trust them."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    bound = _write_run_meta(cli, tmp_path, plan_rel, "0" * 64, idx=1, round_name="R3")
    _bind_clean_manifest(cli, tmp_path, plan, bound, "0" * 64, round_name="R3")
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["timestamp"] = "2026-07-25T10:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    later = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=2, round_name="R1")
    meta = json.loads(later.read_text(encoding="utf-8"))
    meta["finished_at"] = "2026-07-25T12:00:00+00:00"   # after the manifest, despite the label
    later.write_text(json.dumps(meta), encoding="utf-8")

    found = cli.plan_review_finalizable_run_meta(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert found == later


def test_finalizable_run_excludes_a_run_the_manifest_already_passed(cli, tmp_path):
    """The other direction: a current-hash run that finished BEFORE the manifest was recorded is
    superseded, and offering it would send the lane backwards."""
    plan = _plan(tmp_path)
    plan_rel = "backlog/plans/admin.md"
    plan_hash = cli.plan_content_sha256(plan)
    earlier = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=1, round_name="R1")
    meta = json.loads(earlier.read_text(encoding="utf-8"))
    meta["finished_at"] = "2026-07-25T08:00:00+00:00"
    earlier.write_text(json.dumps(meta), encoding="utf-8")
    bound = _write_run_meta(cli, tmp_path, plan_rel, plan_hash, idx=2, round_name="R2")
    _bind_clean_manifest(cli, tmp_path, plan, bound, plan_hash, round_name="R2")
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["timestamp"] = "2026-07-25T10:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    found = cli.plan_review_finalizable_run_meta(_data(), tmp_path, plan, plan_rel, plan_hash)
    assert found is None
