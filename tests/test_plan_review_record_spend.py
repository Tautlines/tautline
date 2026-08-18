"""Item 108 WS2: the budget reader consumes the durable record.

Member spend is computed from the committed round records, additively across the cutover:
``spend = baseline pre-record floor (corrections applied raise-only) + |charged invocation
records, run and imported alike|``. The manifest's lane-local ``observed_successful_runs``
copy is demoted to display, the baseline input, and the no-baseline floor -- every BUDGET
decision reads through the record-backed reader, so a fresh worktree's finalize writing a
smaller lane-local ledger can no longer walk the durable count down (confirmed P1 #1).

Source labels stay honest: ``round_records`` (the durable record), ``baseline`` (a cutover
member with no invocations yet), ``run_metas`` / ``manifest-floor`` (a pre-record member at
today's floor), ``unknown`` (nothing anywhere, never invented).
"""

import json
import shutil

from tautline_methodology import plan_round_record

from test_plan_review_cli import (
    PLAN_REL,
    _manifest_path,
    _prepare_target,
    _run_cli,
    _stdout_path,
)
from test_plan_review_convergence import CLEAN, NOTE, _blocked, _mutate_plan, _run_round
from test_plan_review_round_record import _finalize, _load, _of_kind, _rounds_dir

MEMBER_REL = "backlog/plans/admin.md"


def _data():
    return {
        "project": "example",
        "laneState": {"runsDir": ".ai-runs"},
        "planningArtifacts": {"sourceOfTruth": "backlog/plans"},
    }


def _target_data():
    """The adapter shape of a _prepare_target lane, for in-process reads against it."""
    return {
        "project": "example",
        "laneState": {"runsDir": ".ai-runs"},
        "planningArtifacts": {"sourceOfTruth": PLAN_REL.parent.as_posix()},
    }


def _member_plan(tmp_path):
    path = tmp_path / "backlog" / "plans" / "admin.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Admin\n\n## Goal\n\nDo the work.\n", encoding="utf-8")
    return path


def _member_rounds(tmp_path):
    return tmp_path / "backlog" / "plans" / ".plan-reviews" / "rounds" / "admin"


def _write_baseline(rounds, count, digests=()):
    baseline = plan_round_record.render_baseline(
        plan_identity="admin",
        plan_path=MEMBER_REL,
        prerecord_count=count,
        prerecord_log_sha256s=list(digests),
    )
    _written, created = plan_round_record.write_baseline_once(rounds, baseline)
    assert created is True


def _append_invocation(rounds, digest, *, charged=True, source="run"):
    record = plan_round_record.render_reviewer_invocation(
        plan_identity="admin",
        plan_path=MEMBER_REL,
        plan_content_sha256="c" * 64,
        declared_round="R1",
        wrapper_exit_code=0 if charged else 3,
        reviewer="codex",
        reviewer_model="codex-test",
        started_at="2026-08-15T00:00:00Z",
        finished_at="2026-08-15T00:01:00Z",
        nonce=f"nonce-{digest[:8]}",
        log_sha256=digest,
        declared_predecessor="",
        work_items=[],
        source=source,
    )
    return plan_round_record.append_record(rounds, record)


def _write_meta(cli, tmp_path, *, idx, digest, exit_code=0):
    runs = tmp_path / ".ai-runs" / "plan-review"
    runs.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": cli.PLAN_REVIEW_RUN_SCHEMA,
        "plan_path": MEMBER_REL,
        "plan_content_sha256": "0" * 64,
        "review_scope": "plan-only",
        "code_diff_review": False,
        "review_command": f"codex-review --plan {MEMBER_REL}",
        "log_path": f".ai-runs/plan-review/run-{idx:03d}.log",
        "log_sha256": digest,
        "wrapper_exit_code": exit_code,
        "round": "R1",
    }
    (runs / f"run-{idx:03d}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_manifest(cli, tmp_path, plan_path, **fields):
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": cli.PLAN_REVIEW_SCHEMA,
        "plan_path": MEMBER_REL,
        "round": "R1",
        "verdict": "clean",
        "wrapper_exit_code": 0,
        "timestamp": "2026-08-15T00:00:00Z",
    }
    payload.update(fields)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --- T2.1: record-backed cumulative member spend ----------------------------------------------


def test_member_spend_is_the_union_of_round_records_metas_and_manifest_floor(cli, tmp_path, capsys):
    """Every source is covered exactly once: the baseline absorbs pre-record history, charged
    records spend, an unrecorded lane meta counts once and is surfaced as a write-path bug --
    and the manifest's smaller lane-local copy feeds NOTHING beyond the baseline."""
    plan = _member_plan(tmp_path)
    rounds = _member_rounds(tmp_path)
    _write_baseline(rounds, 2, ["a" * 64])
    _append_invocation(rounds, "b" * 64)
    _write_meta(cli, tmp_path, idx=1, digest="a" * 64)  # pre-record: in the baseline set
    _write_meta(cli, tmp_path, idx=2, digest="b" * 64)  # recorded: dedupes against the record
    _write_meta(cli, tmp_path, idx=3, digest="c" * 64)  # unrecorded: counted once, surfaced
    # The lane-local display copy remembers less than the durable truth; the budget ignores it.
    _write_manifest(cli, tmp_path, plan, observed_successful_runs=1, wrapper_exit_code=0)

    spend = cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL)

    assert spend == (4, "round_records")  # 2 baseline + 1 charged record + 1 unrecorded meta
    assert cli.plan_review_member_recorded_rounds(_data(), tmp_path, MEMBER_REL) == spend
    err = capsys.readouterr().err
    assert "plan_review_round_spend_warning" in err
    assert "write-path bug" in err
    assert "c" * 64 in err
    assert "a" * 64 not in err  # the absorbed and the recorded digests are not bugs
    assert "b" * 64 not in err


def test_manifest_counts_remain_a_floor_for_prerecord_history(cli, tmp_path):
    """A member with NO baseline has no records by construction; it reads at today's floor --
    max(manifest ladder, lane metas) -- labelled for what it is at the budget surface."""
    plan = _member_plan(tmp_path)
    _write_manifest(cli, tmp_path, plan, observed_successful_runs=3, wrapper_exit_code=0)

    # No metas at all: the manifest ladder (3 observed + the successful bound run) is the floor.
    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (4, "manifest-floor")

    # One surviving lane meta cannot pull the floor DOWN below the manifest's memory.
    _write_meta(cli, tmp_path, idx=1, digest="a" * 64)
    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (4, "manifest-floor")

    # More metas than the manifest remembers: the trusted rung of the ladder wins.
    for idx in range(2, 6):
        _write_meta(cli, tmp_path, idx=idx, digest=chr(ord("b") + idx) * 64)
    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (5, "run_metas")


def test_a_lane_meta_matching_a_record_log_digest_counts_once(cli, tmp_path, capsys):
    _member_plan(tmp_path)
    rounds = _member_rounds(tmp_path)
    _write_baseline(rounds, 0)
    _append_invocation(rounds, "b" * 64)
    _write_meta(cli, tmp_path, idx=1, digest="b" * 64)

    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (1, "round_records")
    assert "plan_review_round_spend_warning" not in capsys.readouterr().err


def test_prerecord_floor_plus_new_records_is_additive_not_max(cli, tmp_path):
    """The rejected max() shape (R1 P1): 2 pre-record rounds plus 1 new record must read 3 --
    max(2, 1) = 2 would let pre-record history refill the cap until records outgrow it."""
    _member_plan(tmp_path)
    rounds = _member_rounds(tmp_path)
    _write_baseline(rounds, 2, ["a" * 64, "d" * 64])
    _append_invocation(rounds, "b" * 64)

    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (3, "round_records")
    assert cli.plan_review_member_recorded_rounds(_data(), tmp_path, MEMBER_REL) == (
        3,
        "round_records",
    )


def test_a_failed_wrapper_record_does_not_consume_the_lineage_cap(cli, tmp_path):
    """An uncharged record is an audit fact: infrastructure failures never eat the budget."""
    _member_plan(tmp_path)
    rounds = _member_rounds(tmp_path)
    _write_baseline(rounds, 1, ["a" * 64])
    _append_invocation(rounds, "b" * 64, charged=False)

    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (1, "round_records")

    # A real round afterwards spends exactly one, from exactly one source.
    _append_invocation(rounds, "c" * 64)
    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (2, "round_records")

    # A cutover member with no invocations at all reads its baseline, labelled as such.
    records = plan_round_record.load_round_records(rounds)
    assert plan_round_record.charged_invocation_count(records) == 1


def test_a_baselineless_member_reads_at_the_manifest_floor(cli, tmp_path):
    plan = _member_plan(tmp_path)
    _write_manifest(cli, tmp_path, plan, observed_successful_runs=3, wrapper_exit_code=0)

    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (4, "manifest-floor")
    # The chain display keeps its recorded vocabulary for the same rung; only the budget surface
    # renames it so a floor never masquerades as the durable truth.
    assert cli.plan_review_member_recorded_rounds(_data(), tmp_path, MEMBER_REL) == (
        4,
        "manifest",
    )

    # A failed bound run never becomes a successful round, on any surface.
    _write_manifest(cli, tmp_path, plan, observed_successful_runs=3, wrapper_exit_code=1)
    assert cli.plan_review_member_spend(_data(), tmp_path, MEMBER_REL) == (3, "manifest-floor")


def test_a_correction_record_raises_spend_and_never_lowers_it(cli, tmp_path):
    """The reader half WS1 deferred: corrections apply RAISE-ONLY. The writer refuses to append
    a lowering correction, and even one merged in from another lane is inert."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    data = _target_data()
    plan_rel = PLAN_REL.as_posix()
    assert cli.plan_review_member_spend(data, target, plan_rel) == (1, "round_records")

    correction = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        plan_rel,
        "--correct",
        "baseline",
        "--correction-note",
        "three pre-record rounds were burned in a parked worktree before the cutover",
        "--raise-prerecord-count-to",
        "3",
        home=home,
        adapter_root=adapter_root,
    )
    assert correction.returncode == 0, correction.stdout + correction.stderr
    assert cli.plan_review_member_spend(data, target, plan_rel) == (4, "round_records")

    # A hand-written lowering correction (the writer refuses to produce one) changes nothing.
    lowering = plan_round_record.render_correction(
        plan_identity="test-plan",
        plan_path=plan_rel,
        corrects="baseline",
        note="a lowering correction merged from elsewhere must be inert",
        raise_prerecord_count_to=0,
        recorded_by="test-fixture",
        recorded_at="2026-08-15T00:00:00Z",
    )
    plan_round_record.append_record(_rounds_dir(target), lowering)
    assert cli.plan_review_member_spend(data, target, plan_rel) == (4, "round_records")


def test_a_post_cutover_import_spends_budget_or_is_refused(cli, tmp_path):
    """The reader half of 108-R4-P1-2: a post-cutover import rides a CHARGED imported
    invocation record, and that record spends budget exactly once -- a re-import binds to it
    without charging twice."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    data = _target_data()
    plan_rel = PLAN_REL.as_posix()
    rounds = _rounds_dir(target)

    # Rebuild the peer-lane state: R2's log survives as import evidence, but its record and its
    # lane meta never reached this checkout -- the digest is unknown to records and baseline.
    log_src = _stdout_path(r2.stdout, "plan_review_run_log")
    meta = _load(_stdout_path(r2.stdout, "plan_review_run_meta"))
    import_rel = f"imported-evidence/{log_src.name}"
    import_log = target / import_rel
    import_log.parent.mkdir()
    shutil.copy2(log_src, import_log)
    meta["log_path"] = import_rel
    (target / f"{import_rel}.meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for path, record in _of_kind(rounds, "reviewer-invocation"):
        if record["log_sha256"] == meta["log_sha256"]:
            path.unlink()
    shutil.rmtree(target / ".ai-runs" / "plan-review")
    assert cli.plan_review_member_spend(data, target, plan_rel) == (1, "round_records")

    def _import():
        return _run_cli(
            "record-plan-review",
            "--project",
            str(adapter),
            "--target",
            str(target),
            "--plan",
            plan_rel,
            "--log",
            import_rel,
            "--review-command",
            meta["review_command"],
            "--reviewer",
            "codex",
            "--model",
            "codex-test",
            "--round",
            "R2",
            "--wrapper-exit-code",
            "0",
            *CLEAN,
            home=home,
            adapter_root=adapter_root,
        )

    imported = _import()
    assert imported.returncode == 0, imported.stdout + imported.stderr

    assert cli.plan_review_member_spend(data, target, plan_rel) == (2, "round_records")
    assert cli.plan_review_member_recorded_rounds(data, target, plan_rel) == (
        2,
        "round_records",
    )
    charged_imports = [
        record
        for _path, record in _of_kind(rounds, "reviewer-invocation")
        if record["source"] == "imported"
    ]
    assert len(charged_imports) == 1
    assert charged_imports[0]["charged"] is True
    assert charged_imports[0]["log_sha256"] == meta["log_sha256"]

    # The SAME evidence imported again binds to the existing record: budget spent exactly once.
    reimported = _import()
    assert reimported.returncode == 0, reimported.stdout + reimported.stderr
    assert cli.plan_review_member_spend(data, target, plan_rel) == (2, "round_records")
    assert (
        len(
            [
                record
                for _path, record in _of_kind(rounds, "reviewer-invocation")
                if record["source"] == "imported"
            ]
        )
        == 1
    )


# --- T2.2: the finalize can no longer shrink durable spend -------------------------------------


def test_a_fresh_worktree_finalize_cannot_shrink_recorded_lineage_spend(cli, tmp_path):
    """The P1 #1 regression: prior spend 2, fresh worktree, one round, finalize -- the budget
    reads 3, never 1, and the launch itself starts from the durable count."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *CLEAN).returncode == 0

    # The fresh worktree: lane-local run metas are gone; the COMMITTED evidence -- manifest and
    # round records -- is exactly what a checkout carries.
    shutil.rmtree(target / ".ai-runs" / "plan-review")

    r3 = _run_round(home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *CLEAN)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    # The launch ledger reads the durable record, not the empty lane: 2 spent, not 0.
    assert "observed_successful_runs=2" in r3.stdout

    data = _target_data()
    plan_rel = PLAN_REL.as_posix()
    assert cli.plan_review_member_spend(data, target, plan_rel) == (3, "round_records")
    assert cli.plan_review_member_recorded_rounds(data, target, plan_rel) == (
        3,
        "round_records",
    )
    # The manifest carry-through stays display -- and whatever it says, the budget is indifferent.
    manifest = _load(_manifest_path(target))
    assert manifest["observed_successful_runs"] == 2


def test_out_of_order_finalization_never_decrements_cumulative_member_counts(cli, tmp_path):
    """Cardinality of an append-only set is order-free: binding R1 after R2 leaves the manifest
    displaying the OLDER launch's smaller ledger, and the budget still reads every spent round."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr

    f2 = _finalize(
        home,
        adapter_root,
        target,
        adapter,
        _stdout_path(r2.stdout, "plan_review_run_log"),
        "R2",
        *CLEAN,
    )
    assert f2.returncode == 0, f2.stdout + f2.stderr
    f1 = _finalize(
        home,
        adapter_root,
        target,
        adapter,
        _stdout_path(r1.stdout, "plan_review_run_log"),
        "R1",
        *CLEAN,
    )
    assert f1.returncode == 0, f1.stdout + f1.stderr

    data = _target_data()
    plan_rel = PLAN_REL.as_posix()
    # The display shrank -- the late bind carries R1's launch-time ledger of 0 runs before it...
    manifest = _load(_manifest_path(target))
    assert manifest["observed_successful_runs"] == 0
    # ...and the budget did not: two charged records exist, whatever order they were bound in.
    assert cli.plan_review_member_spend(data, target, plan_rel) == (2, "round_records")

    # Even a fresh clone that never held the lane metas reads the full spend.
    shutil.rmtree(target / ".ai-runs" / "plan-review")
    assert cli.plan_review_member_spend(data, target, plan_rel) == (2, "round_records")
    assert cli.plan_review_member_recorded_rounds(data, target, plan_rel) == (
        2,
        "round_records",
    )


def test_stale_at_cap_routing_follows_the_record_in_a_fresh_worktree(cli, tmp_path):
    """Codex R1 P2 (this lineage): `plan_review_sha_stale_at_cap` derived its count from lane
    metas alone, so a fresh worktree at a record-spent cap with every recorded review stale was
    told to carry findings into implementation while the record-backed cap refused the next
    run. The routing must follow the same count the cap enforces."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    for label in ("R1", "R2"):
        assert _run_round(home, adapter_root, target, adapter, label, *_blocked(1)).returncode == 0
    for label in ("R3", "R4"):
        _mutate_plan(target, f"4. A fix before {label} that leaves one blocker standing.\n")
        r = _run_round(
            home, adapter_root, target, adapter, label, "--exception-note", NOTE, *_blocked(1)
        )
        assert r.returncode in (0, 2), r.stdout + r.stderr
    _mutate_plan(target, "5. An edit after the hard cap, voiding every recorded hash.\n")
    # The fresh worktree: lane metas gone; committed records carry the hard-cap spend.
    shutil.rmtree(target / ".ai-runs" / "plan-review")

    data = _target_data()
    plan_path = target / PLAN_REL
    plan_hash = cli.plan_content_sha256_from_text(plan_path.read_text(encoding="utf-8"))
    assert cli.plan_review_sha_stale_at_cap(
        data, target, plan_path, PLAN_REL.as_posix(), plan_hash
    ), "record-spent cap with every recorded review stale must route to the successor path"


def test_current_hash_evidence_in_the_record_is_not_called_stale(cli, tmp_path):
    """Codex R2 P2 (this lineage): with record-backed spend and an empty lane, a metas-only
    staleness scan called evidence FOR THE CURRENT HASH stale and routed to a successor plan
    the cap does not require. The durable invocation hashes join the scan."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(1)).returncode == 0
    for label in ("R3", "R4"):
        r = _run_round(
            home, adapter_root, target, adapter, label, "--exception-note", NOTE, *_blocked(1)
        )
        assert r.returncode in (0, 2), r.stdout + r.stderr
    # NO edit after the runs: the committed records bind the CURRENT hash. Fresh worktree.
    shutil.rmtree(target / ".ai-runs" / "plan-review")

    data = _target_data()
    plan_path = target / PLAN_REL
    plan_hash = cli.plan_content_sha256_from_text(plan_path.read_text(encoding="utf-8"))
    assert not cli.plan_review_sha_stale_at_cap(
        data, target, plan_path, PLAN_REL.as_posix(), plan_hash
    ), "evidence bound to the current hash must never be routed to a successor plan"


def test_a_current_hash_blocked_manifest_is_not_routed_to_a_successor(cli, tmp_path):
    """Codex R3 P2 (this lineage): a baselineless member at the manifest-floor cap in a fresh
    checkout has neither metas nor records -- but a BLOCKED manifest bound to the current hash
    can finalize capped through the valve. Routing it to a successor is the refill exit this
    program retires. The manifest is the third and final evidence surface in the scan."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    for label, args in (("R1", _blocked(1)), ("R2", _blocked(1))):
        assert _run_round(home, adapter_root, target, adapter, label, *args).returncode == 0
    for label in ("R3", "R4"):
        r = _run_round(
            home, adapter_root, target, adapter, label, "--exception-note", NOTE, *_blocked(1)
        )
        assert r.returncode in (0, 2), r.stdout + r.stderr
    # Simulate the PRE-RECORD member: strip lane metas AND the durable records, keeping only
    # the committed manifest (blocked, bound to the current hash).
    shutil.rmtree(target / ".ai-runs" / "plan-review")
    rounds_root = target / PLAN_REL.parent / ".plan-reviews" / "rounds"
    if rounds_root.exists():
        shutil.rmtree(rounds_root)

    data = _target_data()
    plan_path = target / PLAN_REL
    plan_hash = cli.plan_content_sha256_from_text(plan_path.read_text(encoding="utf-8"))
    assert not cli.plan_review_sha_stale_at_cap(
        data, target, plan_path, PLAN_REL.as_posix(), plan_hash
    ), "a blocked manifest bound to the current hash is finalizable capped, never successor-routed"
