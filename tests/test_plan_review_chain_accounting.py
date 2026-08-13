"""Item 32: succession chains refill the round budget invisibly.

The hard cap counts successful reviewer invocations PER PLAN PATH, so a successor plan starts
with a brand-new four-round budget -- by design, because the successor is the sanctioned exit
the cap refusal itself names. Nothing counted how many budgets a CHAIN consumed: one live item
ran 22 legal rounds across six chained plans and every ledger read them as six fresh starts.

This module pins the accounting: lineage is recorded on the run meta and carried into the
manifest, the chain walk sums each member exactly once with honest unknowns, both ceremonies
print the running total, and a cumulative-spend advisory prints WITHOUT ever blocking anything.
Succession stays unconditionally reachable -- the 2026-07-14 deadlock was a gate that could
refuse every exit, and this release adds no refusal to any existing path.
"""

import json
from pathlib import Path

import pytest

from test_plan_review_cli import (
    PLAN_REL,
    SOURCE_ROOT,
    _manifest_path,
    _prepare_target,
    _run_cli,
    _stdout_path,
    _write_plan,
)


def _data():
    return {
        "project": "example",
        "laneState": {"runsDir": ".ai-runs"},
        "planningArtifacts": {"sourceOfTruth": "backlog/plans"},
    }


def _plan(tmp_path, name="admin.md"):
    path = tmp_path / "backlog" / "plans" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\n## Goal\n\nDo the work.\n", encoding="utf-8")
    return path


def _rel(name):
    return f"backlog/plans/{name}"


def _write_run_meta(cli, tmp_path, plan_rel, *, idx, exit_code=0, **extra):
    """A plan-review run meta on disk, keyed on plan_rel. `idx` orders the glob."""
    runs = tmp_path / ".ai-runs" / "plan-review"
    runs.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": cli.PLAN_REVIEW_RUN_SCHEMA,
        "plan_path": plan_rel,
        "plan_content_sha256": "0" * 64,
        "review_scope": "plan-only",
        "code_diff_review": False,
        "review_command": f"codex-review --plan {plan_rel}",
        "log_path": f".ai-runs/plan-review/run-{idx:03d}.log",
        "log_sha256": "x",
        "wrapper_exit_code": exit_code,
        "round": "R1",
    }
    meta.update(extra)
    path = runs / f"run-{idx:03d}.meta.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def _write_manifest(cli, tmp_path, plan_path, **fields):
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": cli.PLAN_REVIEW_SCHEMA,
        "plan_path": _rel(plan_path.name),
        "round": "R1",
        "verdict": "clean",
        "wrapper_exit_code": 0,
        "timestamp": "2026-07-27T00:00:00Z",
    }
    payload.update(fields)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


# --------------------------------------------------------------------------------------
# AC-1: lineage resolution and recording
# --------------------------------------------------------------------------------------


def test_run_plan_review_records_declared_predecessor_lineage_in_run_meta(cli, tmp_path):
    predecessor = _plan(tmp_path, "admin-v1.md")
    successor = _plan(tmp_path, "admin-v2.md")
    _write_run_meta(cli, tmp_path, _rel("admin-v1.md"), idx=1)

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v2.md"), Path(_rel("admin-v1.md"))
    )

    assert errors == []
    assert resolved == _rel("admin-v1.md")
    assert cli.plan_review_manifest_path(_data(), tmp_path, predecessor).name == "admin-v1.json"


def test_lineage_resolves_from_manifest_then_earliest_meta_when_flag_omitted(cli, tmp_path):
    successor = _plan(tmp_path, "admin-v2.md")
    successor_rel = _rel("admin-v2.md")
    _plan(tmp_path, "admin-v1.md")

    # No record anywhere: a plan with no declared lineage is standalone.
    assert cli.plan_review_recorded_predecessor(_data(), tmp_path, successor_rel) is None

    # A run meta carrying the field is enough, and the EARLIEST one wins.
    _write_run_meta(cli, tmp_path, successor_rel, idx=1, predecessor_plan_path=_rel("admin-v1.md"))
    _write_run_meta(cli, tmp_path, successor_rel, idx=2, predecessor_plan_path=_rel("other.md"))
    recorded = cli.plan_review_recorded_predecessor(_data(), tmp_path, successor_rel)
    assert recorded == _rel("admin-v1.md")

    # The manifest outranks the metas -- it is the finalized record.
    _write_manifest(cli, tmp_path, successor, predecessor_plan_path=_rel("admin-v0.md"))
    recorded = cli.plan_review_recorded_predecessor(_data(), tmp_path, successor_rel)
    assert recorded == _rel("admin-v0.md")

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, successor_rel, None
    )
    assert errors == []
    assert resolved == _rel("admin-v0.md")


def test_finalize_carries_lineage_and_chain_depth_into_manifest(cli, tmp_path):
    meta_path = _write_run_meta(
        cli,
        tmp_path,
        _rel("admin-v2.md"),
        idx=1,
        predecessor_plan_path=_rel("admin-v1.md"),
        predecessor_manifest_path="backlog/plans/.plan-reviews/admin-v1.json",
        chain_depth=2,
        chain_prior_recorded_rounds=5,
        chain_evidence="exact",
        chain_unknown_members=0,
    )

    fields = cli.plan_review_manifest_chain_fields(meta_path, 0)

    assert fields["predecessor_plan_path"] == _rel("admin-v1.md")
    assert fields["predecessor_manifest_path"] == "backlog/plans/.plan-reviews/admin-v1.json"
    assert fields["chain_depth"] == 2
    assert fields["chain_evidence"] == "exact"
    assert fields["chain_unknown_members"] == 0


def test_manifest_chain_recorded_rounds_derives_from_bound_meta_not_recount(cli, tmp_path):
    """The bound run itself is the +1, and only when it actually succeeded.

    A finalize-time filesystem recount would read one high (the run being bound is already on
    disk as a successful record) and would drift whenever another run lands between the launch
    and the finalize.
    """
    clean = _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=1,
        predecessor_plan_path=_rel("admin-v1.md"), chain_prior_recorded_rounds=5,
    )
    assert cli.plan_review_manifest_chain_fields(clean, 0)["chain_recorded_rounds"] == 6

    # A failed bind never invents a successful round.
    failed = _write_run_meta(
        cli, tmp_path, _rel("admin-v3.md"), idx=2, exit_code=1,
        predecessor_plan_path=_rel("admin-v2.md"), chain_prior_recorded_rounds=5,
    )
    assert cli.plan_review_manifest_chain_fields(failed, 1)["chain_recorded_rounds"] == 5


# --------------------------------------------------------------------------------------
# AC-2: honest chain accounting
# --------------------------------------------------------------------------------------


def test_chain_walk_sums_recorded_rounds_across_two_plan_chain(cli, tmp_path):
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    for idx in range(1, 5):
        _write_run_meta(cli, tmp_path, _rel("admin-v1.md"), idx=idx)
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=5, predecessor_plan_path=_rel("admin-v1.md")
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))
    summary = cli.plan_review_chain_summary(members, truncated)

    assert [member["plan_path"] for member in members] == [_rel("admin-v1.md"), _rel("admin-v2.md")]
    assert summary["depth"] == 2
    assert summary["cumulative_recorded_rounds"] == 5
    assert summary["unknown_members"] == 0
    assert summary["evidence"] == "exact"


def test_three_plan_chain_counts_each_member_exactly_once(cli, tmp_path):
    """A member's OWN chain total covers its ancestors; summing those double-counts them."""
    _plan(tmp_path, "admin-v1.md")
    middle = _plan(tmp_path, "admin-v2.md")
    _plan(tmp_path, "admin-v3.md")
    for idx in range(1, 5):
        _write_run_meta(cli, tmp_path, _rel("admin-v1.md"), idx=idx)
    for idx in range(5, 8):
        _write_run_meta(
            cli, tmp_path, _rel("admin-v2.md"), idx=idx, predecessor_plan_path=_rel("admin-v1.md")
        )
    _write_run_meta(
        cli, tmp_path, _rel("admin-v3.md"), idx=8, predecessor_plan_path=_rel("admin-v2.md")
    )
    # The middle member's finalized manifest carries a chain total spanning v1 AND v2.
    _write_manifest(
        cli, tmp_path, middle,
        predecessor_plan_path=_rel("admin-v1.md"),
        chain_depth=2,
        chain_recorded_rounds=7,
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v3.md"))
    summary = cli.plan_review_chain_summary(members, truncated)

    assert summary["depth"] == 3
    assert summary["cumulative_recorded_rounds"] == 8  # 4 + 3 + 1, never 7 + anything
    assert [member["recorded_rounds"] for member in members] == [4, 3, 1]


def test_chain_walk_reports_unknown_member_without_inventing_numbers(cli, tmp_path):
    ancestor = _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    # A pre-lineage manifest: no run metas survive and it carries no observed_successful_runs.
    _write_manifest(cli, tmp_path, ancestor)
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=1, predecessor_plan_path=_rel("admin-v1.md")
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))
    summary = cli.plan_review_chain_summary(members, truncated)

    assert members[0]["recorded_rounds"] is None
    assert members[0]["rounds_source"] == "unknown"
    assert summary["unknown_members"] == 1
    assert summary["cumulative_recorded_rounds"] == 1
    assert summary["evidence"] == "floor"
    assert ">=1" in cli.plan_review_chain_ledger_line(summary, members)


def test_chain_walk_falls_back_to_manifest_observed_runs_when_metas_absent(cli, tmp_path):
    """Fresh clone: `runsDir` is lane-local, so an ancestor's run metas are simply gone."""
    ancestor = _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    _write_manifest(cli, tmp_path, ancestor, observed_successful_runs=3, wrapper_exit_code=0)
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=1, predecessor_plan_path=_rel("admin-v1.md")
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))
    summary = cli.plan_review_chain_summary(members, truncated)

    assert members[0]["recorded_rounds"] == 4  # 3 observed before the bound run, plus the bind
    assert members[0]["rounds_source"] == "manifest"
    assert summary["cumulative_recorded_rounds"] == 5
    assert summary["unknown_members"] == 0


def test_manifest_fallback_never_counts_a_failed_bound_run(cli, tmp_path):
    ancestor = _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    _write_manifest(cli, tmp_path, ancestor, observed_successful_runs=3, wrapper_exit_code=1)
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=1, predecessor_plan_path=_rel("admin-v1.md")
    )

    members, _truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))

    assert members[0]["recorded_rounds"] == 3


def test_chain_walk_terminates_on_cycle_and_flags_truncation(cli, tmp_path):
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    _write_run_meta(
        cli, tmp_path, _rel("admin-v1.md"), idx=1, predecessor_plan_path=_rel("admin-v2.md")
    )
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=2, predecessor_plan_path=_rel("admin-v1.md")
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))
    summary = cli.plan_review_chain_summary(members, truncated)

    assert truncated is True
    assert summary["evidence"] == "floor"
    assert [member["plan_path"] for member in members] == [_rel("admin-v1.md"), _rel("admin-v2.md")]


def test_self_referencing_lineage_terminates_the_walk(cli, tmp_path):
    _plan(tmp_path, "admin-v2.md")
    _write_run_meta(
        cli, tmp_path, _rel("admin-v2.md"), idx=1, predecessor_plan_path=_rel("admin-v2.md")
    )

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin-v2.md"))

    assert [member["plan_path"] for member in members] == [_rel("admin-v2.md")]
    assert truncated is True


def test_launch_chain_counts_the_current_plan_at_its_exact_observed_runs(cli, tmp_path):
    """At launch the current plan's spend is KNOWN, so it is never an unknown member."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    for idx in range(1, 5):
        _write_run_meta(cli, tmp_path, _rel("admin-v1.md"), idx=idx)

    members, truncated = cli.plan_review_launch_chain(
        _data(), tmp_path, _rel("admin-v2.md"), _rel("admin-v1.md"), 0
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert summary["depth"] == 2
    assert summary["cumulative_recorded_rounds"] == 4
    assert summary["unknown_members"] == 0
    assert summary["evidence"] == "exact"


# --------------------------------------------------------------------------------------
# AC-3 / AC-4: surfacing and the advisory
# --------------------------------------------------------------------------------------


def _summary(cli, **fields):
    base = {
        "depth": 2,
        "cumulative_recorded_rounds": 5,
        "unknown_members": 0,
        "truncated": False,
        "evidence": "exact",
    }
    base.update(fields)
    return base


def test_chain_ledger_line_renders_depth_total_and_members(cli, tmp_path):
    members = [
        {"plan_path": _rel("admin-v1.md"), "recorded_rounds": 4, "rounds_source": "run_metas"},
        {"plan_path": _rel("admin-v2.md"), "recorded_rounds": 1, "rounds_source": "run_metas"},
    ]

    line = cli.plan_review_chain_ledger_line(_summary(cli), members)

    assert line.startswith("plan_review_chain_ledger: ")
    assert "depth=2" in line
    assert "cumulative_recorded_rounds=5" in line
    assert "unknown_members=0" in line
    assert "evidence=exact" in line
    assert f"members={_rel('admin-v1.md')}:4->{_rel('admin-v2.md')}:1" in line


def test_chain_advisory_absent_below_both_lines(cli):
    """The item-37-shaped chain -- one sanctioned succession, 6 cumulative rounds -- is silent."""
    for rounds in (6, 8):
        summary = _summary(cli, depth=2, cumulative_recorded_rounds=rounds)
        assert cli.plan_review_chain_advisory_line(summary) == ""


@pytest.mark.parametrize(
    ("fields", "expected_lines"),
    [
        ({"depth": 2, "cumulative_recorded_rounds": 9}, ["cumulative rounds"]),
        ({"depth": 3, "cumulative_recorded_rounds": 3}, ["chain depth"]),
        ({"depth": 6, "cumulative_recorded_rounds": 22}, ["cumulative rounds", "chain depth"]),
    ],
)
def test_chain_advisory_prints_past_rounds_or_depth_line(cli, fields, expected_lines):
    line = cli.plan_review_chain_advisory_line(_summary(cli, **fields))

    assert line.startswith("plan_review_chain_advisory: ")
    assert "Nothing is blocked" in line
    # Only remedies that genuinely work: the split, or the implementation-review focus list.
    assert "smaller independent source-of-truth plans" in line
    assert "implementation review focus list" in line
    # The advisory names the line that actually fired, and never one that did not.
    for phrase in ("cumulative rounds", "chain depth"):
        assert (phrase in line) is (phrase in expected_lines), line


def test_chain_advisory_marks_a_floor_total_as_a_floor(cli):
    line = cli.plan_review_chain_advisory_line(
        _summary(cli, depth=4, cumulative_recorded_rounds=12, unknown_members=2, evidence="floor")
    )

    assert ">=12" in line


def test_chain_status_line_reads_the_manifest_never_a_fresh_walk(cli):
    manifest = {
        "predecessor_plan_path": _rel("admin-v1.md"),
        "chain_depth": 2,
        "chain_recorded_rounds": 6,
        "chain_unknown_members": 0,
        "chain_evidence": "exact",
    }

    refs = cli.plan_review_chain_event_refs(manifest)
    # The honesty markers travel with the numbers, so event evidence can never look exact when
    # the walk was a floor.
    assert refs == {
        "predecessor_plan_path": _rel("admin-v1.md"),
        "chain_depth": "2",
        "chain_recorded_rounds": "6",
        "chain_evidence": "exact",
        "chain_unknown_members": "0",
    }
    assert cli.plan_review_chain_event_refs({}) == {}
    assert cli.plan_review_chain_event_refs({"chain_depth": 4}) == {}

    line = cli.plan_review_chain_status_line(manifest)
    assert line.startswith("plan_review_chain_status: ")
    assert "depth=2" in line
    assert "chain_recorded_rounds=6" in line
    assert "evidence=exact" in line
    assert f"predecessor={_rel('admin-v1.md')}" in line
    assert cli.plan_review_chain_status_line({}) == ""


# --------------------------------------------------------------------------------------
# AC-5: absent-safe back-compat
# --------------------------------------------------------------------------------------


def test_standalone_plan_carries_no_chain_fields_anywhere(cli, tmp_path):
    plan = _plan(tmp_path, "admin.md")
    meta_path = _write_run_meta(cli, tmp_path, _rel("admin.md"), idx=1)

    assert cli.plan_review_manifest_chain_fields(meta_path, 0) == {}
    assert cli.plan_review_recorded_predecessor(_data(), tmp_path, _rel("admin.md")) is None
    assert cli.plan_review_lineage_shape_hint(_data(), tmp_path, plan) == ""

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin.md"))
    summary = cli.plan_review_chain_summary(members, truncated)
    assert summary["depth"] == 1
    assert cli.plan_review_chain_advisory_line(summary) == ""


def test_old_manifest_and_meta_without_lineage_fields_parse_and_finalize(cli, tmp_path):
    plan = _plan(tmp_path, "admin.md")
    legacy_manifest = cli.plan_review_manifest_path(_data(), tmp_path, plan)
    legacy_manifest.parent.mkdir(parents=True, exist_ok=True)
    legacy_manifest.write_text(
        json.dumps({"round": "R1", "verdict": "clean", "plan_path": _rel("admin.md")}),
        encoding="utf-8",
    )
    meta_path = _write_run_meta(cli, tmp_path, _rel("admin.md"), idx=1)

    assert cli.plan_review_manifest_chain_fields(meta_path, 0) == {}
    assert cli.plan_review_chain_status_line(json.loads(legacy_manifest.read_text())) == ""
    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("admin.md"))
    assert cli.plan_review_chain_summary(members, truncated)["depth"] == 1


# --------------------------------------------------------------------------------------
# AC-6: refusals name only remedies that work
# --------------------------------------------------------------------------------------


def test_predecessor_flag_conflicting_with_recorded_lineage_is_refused_quoting_both(cli, tmp_path):
    successor = _plan(tmp_path, "admin-v3.md")
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    _write_run_meta(cli, tmp_path, _rel("admin-v1.md"), idx=1)
    _write_run_meta(cli, tmp_path, _rel("admin-v2.md"), idx=2)
    _write_run_meta(
        cli, tmp_path, _rel("admin-v3.md"), idx=3, predecessor_plan_path=_rel("admin-v2.md")
    )

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v3.md"), Path(_rel("admin-v1.md"))
    )

    assert len(errors) == 1
    assert _rel("admin-v1.md") in errors[0]
    assert _rel("admin-v2.md") in errors[0]
    assert "rerun without --predecessor" in errors[0]
    assert resolved == ""

    # The matching value is a no-op, never a refusal: lineage is append-once, not write-once.
    repeat_errors, repeat_resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v3.md"), Path(_rel("admin-v2.md"))
    )
    assert repeat_errors == []
    assert repeat_resolved == _rel("admin-v2.md")


def test_predecessor_flag_rejects_self_and_predecessor_without_recorded_evidence(cli, tmp_path):
    successor = _plan(tmp_path, "admin-v2.md")
    _plan(tmp_path, "admin-v1.md")

    self_errors, _ = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v2.md"), Path(_rel("admin-v2.md"))
    )
    assert len(self_errors) == 1
    assert "different plan" in self_errors[0]

    bare_errors, _ = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v2.md"), Path(_rel("admin-v1.md"))
    )
    assert len(bare_errors) == 1
    # Names BOTH checked locations and BOTH working remedies.
    assert "backlog/plans/.plan-reviews/admin-v1.json" in bare_errors[0]
    assert ".ai-runs/plan-review" in bare_errors[0]
    assert "correct the path" in bare_errors[0]
    assert "omit --predecessor" in bare_errors[0]


def test_predecessor_outside_the_source_of_truth_root_is_refused(cli, tmp_path):
    successor = _plan(tmp_path, "admin-v2.md")
    outside = tmp_path / "elsewhere" / "admin-v1.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("# elsewhere\n", encoding="utf-8")

    errors, _ = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v2.md"), Path("elsewhere/admin-v1.md")
    )

    assert len(errors) == 1
    assert "outside source-of-truth path" in errors[0]


# --------------------------------------------------------------------------------------
# AC-7: adoption text
# --------------------------------------------------------------------------------------


def test_successor_instruction_names_the_predecessor_flag(cli):
    instruction = cli.plan_review_successor_instruction(_rel("admin-v1.md"))

    assert "--predecessor" in instruction
    assert _rel("admin-v1.md") in instruction


def test_v_suffix_shape_hint_prints_only_when_base_manifest_exists_and_no_lineage_recorded(
    cli, tmp_path
):
    base = _plan(tmp_path, "admin.md")
    v2 = _plan(tmp_path, "admin-v2.md")

    # No predecessor manifest yet: nothing to point at, so nothing is printed.
    assert cli.plan_review_lineage_shape_hint(_data(), tmp_path, v2) == ""

    _write_manifest(cli, tmp_path, base)
    hint = cli.plan_review_lineage_shape_hint(_data(), tmp_path, v2)
    assert hint.startswith("plan_review_lineage_hint: ")
    assert "--predecessor" in hint
    assert _rel("admin.md") in hint

    # `-v(N-1)` wins over the bare base when both are reviewed.
    v1 = _plan(tmp_path, "admin-v1.md")
    _write_manifest(cli, tmp_path, v1)
    assert _rel("admin-v1.md") in cli.plan_review_lineage_shape_hint(_data(), tmp_path, v2)

    # STRICT shape only -- no English parsing (item 36).
    for name in ("admin-final.md", "admin-v.md", "admin-v2b.md", "adminv2.md"):
        assert cli.plan_review_lineage_shape_hint(_data(), tmp_path, _plan(tmp_path, name)) == ""


# --------------------------------------------------------------------------------------
# Constraint pins: succession is never blocked, exit codes never move
# --------------------------------------------------------------------------------------


def test_chained_successor_launch_is_never_refused_by_chain_accounting(cli, tmp_path):
    """A 22-round chain still launches R1 on its successor. The chain never gates."""
    successor = _plan(tmp_path, "admin-v7.md")
    idx = 0
    previous = None
    for generation in range(1, 7):
        name = f"admin-v{generation}.md"
        _plan(tmp_path, name)
        for _ in range(4):
            idx += 1
            _write_run_meta(
                cli, tmp_path, _rel(name), idx=idx,
                **({"predecessor_plan_path": previous} if previous else {}),
            )
        previous = _rel(name)

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, successor, _rel("admin-v7.md"), Path(_rel("admin-v6.md"))
    )
    assert errors == []

    members, truncated = cli.plan_review_launch_chain(
        _data(), tmp_path, _rel("admin-v7.md"), resolved, 0
    )
    summary = cli.plan_review_chain_summary(members, truncated)
    assert summary["cumulative_recorded_rounds"] == 24
    assert cli.plan_review_chain_advisory_line(summary) != ""

    # The round-budget gate is keyed on THIS plan only -- the chain contributes nothing to it.
    assert cli.plan_review_round_cap_errors(round_number=1, observed_runs=0) == []
    successor_hash = cli.plan_content_sha256(successor)
    assert cli.plan_review_runtime_cap_errors(
        _data(), tmp_path, successor, _rel("admin-v7.md"), successor_hash, "R1", 1
    ) == []


# --------------------------------------------------------------------------------------
# End-to-end: both ceremonies, real CLI
# --------------------------------------------------------------------------------------


SUCCESSOR_REL = SOURCE_ROOT / "test-plan-v2.md"


def _round(home, adapter_root, target, adapter, plan_rel, review_round, *extra):
    return _run_cli(
        "run-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", plan_rel.as_posix(),
        "--round", review_round,
        "--model", "codex-test",
        *extra,
        home=home,
        adapter_root=adapter_root,
    )


def test_run_and_finalize_print_the_chain_ledger_for_a_chained_plan(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    _write_plan(target, SUCCESSOR_REL, summary="Deliver the successor plan safely.")

    base = _round(home, adapter_root, target, adapter, PLAN_REL, "R1")
    assert base.returncode == 0, base.stdout + base.stderr
    assert "plan_review_chain_ledger:" not in base.stdout, "standalone output must not change"
    assert "plan_review_chain_advisory:" not in base.stdout

    base_finalize = _run_cli(
        "finalize-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", PLAN_REL.as_posix(),
        "--log", str(_stdout_path(base.stdout, "plan_review_run_log")),
        "--round", "R1",
        "--model", "codex-test",
        "--verdict", "clean",
        "--unresolved-critical-count", "0",
        "--unresolved-p1-count", "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert base_finalize.returncode == 0, base_finalize.stdout + base_finalize.stderr
    assert "plan_review_chain_status:" not in base_finalize.stdout

    successor = _round(
        home, adapter_root, target, adapter, SUCCESSOR_REL, "R1",
        "--predecessor", PLAN_REL.as_posix(),
    )
    assert successor.returncode == 0, successor.stdout + successor.stderr
    assert "plan_review_chain_ledger: depth=2" in successor.stdout
    assert "cumulative_recorded_rounds=1" in successor.stdout
    assert "plan_review_chain_advisory:" not in successor.stdout

    meta_path = _stdout_path(successor.stdout, "plan_review_run_meta")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["predecessor_plan_path"] == PLAN_REL.as_posix()
    assert meta["chain_depth"] == 2
    assert meta["chain_prior_recorded_rounds"] == 1
    assert meta["chain_evidence"] == "exact"

    finalize = _run_cli(
        "finalize-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", SUCCESSOR_REL.as_posix(),
        "--log", str(_stdout_path(successor.stdout, "plan_review_run_log")),
        "--round", "R1",
        "--model", "codex-test",
        "--verdict", "clean",
        "--unresolved-critical-count", "0",
        "--unresolved-p1-count", "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_review_chain_status: depth=2" in finalize.stdout
    assert "chain_recorded_rounds=2" in finalize.stdout

    manifest = json.loads(_manifest_path(target, SUCCESSOR_REL).read_text(encoding="utf-8"))
    assert manifest["predecessor_plan_path"] == PLAN_REL.as_posix()
    assert manifest["chain_depth"] == 2
    assert manifest["chain_recorded_rounds"] == 2
    assert manifest["chain_evidence"] == "exact"

    standalone = json.loads(_manifest_path(target, PLAN_REL).read_text(encoding="utf-8"))
    assert not [key for key in standalone if key.startswith(("chain_", "predecessor_"))]


def test_finalize_chain_status_matches_manifest_when_an_extra_run_lands_between_run_and_finalize(
    tmp_path,
):
    """The status line and the manifest it sits beside can never contradict each other."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    _write_plan(target, SUCCESSOR_REL, summary="Deliver the successor plan safely.")

    assert _round(home, adapter_root, target, adapter, PLAN_REL, "R1").returncode == 0
    successor = _round(
        home, adapter_root, target, adapter, SUCCESSOR_REL, "R1",
        "--predecessor", PLAN_REL.as_posix(),
    )
    log_path = _stdout_path(successor.stdout, "plan_review_run_log")

    # Another round lands on the PREDECESSOR before the successor's run is bound.
    assert _round(home, adapter_root, target, adapter, PLAN_REL, "R2").returncode == 0

    finalize = _run_cli(
        "finalize-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", SUCCESSOR_REL.as_posix(),
        "--log", str(log_path),
        "--round", "R1",
        "--model", "codex-test",
        "--verdict", "clean",
        "--unresolved-critical-count", "0",
        "--unresolved-p1-count", "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr

    manifest = json.loads(_manifest_path(target, SUCCESSOR_REL).read_text(encoding="utf-8"))
    assert manifest["chain_recorded_rounds"] == 2
    assert f"chain_recorded_rounds={manifest['chain_recorded_rounds']}" in finalize.stdout
    # The refreshed members list is separate and clearly labelled, so it may legitimately
    # differ from the bound total.
    assert "plan_review_chain_members:" in finalize.stdout


def test_predecessor_flag_refusal_costs_no_review_round(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    _write_plan(target, SUCCESSOR_REL, summary="Deliver the successor plan safely.")

    refused = _round(
        home, adapter_root, target, adapter, SUCCESSOR_REL, "R1",
        "--predecessor", PLAN_REL.as_posix(),
    )

    assert refused.returncode == 1
    assert "no recorded plan-review evidence" in refused.stderr
    assert not list((target / ".ai-runs" / "plan-review").glob("*.meta.json"))
