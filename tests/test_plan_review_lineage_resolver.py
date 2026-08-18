"""Item 108 WS3: ONE lineage resolver -- declared, name-shape and work-item edges as a UNION.

The prior lineage machinery (read-only prior art `1e90a294`) carried three confirmed defects:

- P1 #3: the explicit ``--predecessor`` seed was consulted only when name-shape inference found
  nothing, so a ``-vN`` name silently discarded the declared edge -- one launch recorded two
  different lineages (advisory chain fields on the declared edge, budget on the inferred one).
- P1 #2: successor inference GENERATED candidate names downward from N, bounded at
  ``PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH`` -- ``admin-v34`` never found ``admin-v1`` and the miss
  returned "" silently, a standalone plan on a fresh budget; a date-like ``-v20260815`` suffix
  would have materialised twenty million candidate strings before finding anything.
- T3.3: a depth-capped walk stopped silently, so the cut lineage read as a smaller exact total.

This module pins the fresh resolver: edges bind as a union, inference ENUMERATES existing
entries, every truncation is a printed floor, and every advisory or authoritative consumer
reads the same resolver output.
"""

import json
import time
import tracemalloc


def _data():
    return {
        "project": "example",
        "laneState": {"runsDir": ".ai-runs"},
        "planningArtifacts": {"sourceOfTruth": "backlog/plans"},
    }


def _rel(name):
    return f"backlog/plans/{name}"


def _plan(tmp_path, name="admin.md", body="## Goal\n\nDo the work.\n"):
    path = tmp_path / "backlog" / "plans" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\n{body}", encoding="utf-8")
    return path


def _spend(cli, tmp_path, plan_rel, rounds, *, start=0, predecessor=""):
    """`rounds` successful reviewer invocations recorded against one plan."""
    runs = tmp_path / ".ai-runs" / "plan-review"
    runs.mkdir(parents=True, exist_ok=True)
    for index in range(rounds):
        meta = {
            "schema": cli.PLAN_REVIEW_RUN_SCHEMA,
            "plan_path": plan_rel,
            "plan_content_sha256": "0" * 64,
            "review_scope": "plan-only",
            "code_diff_review": False,
            "review_command": f"codex-review --plan {plan_rel}",
            "log_path": f".ai-runs/plan-review/run-{start + index:03d}.log",
            "log_sha256": f"{start + index:x}" * 8,
            "wrapper_exit_code": 0,
            "round": f"R{index + 1}",
            "finished_at": f"2026-08-15T{10 + ((start + index) % 12):02d}:00:00+00:00",
        }
        if predecessor:
            meta["predecessor_plan_path"] = predecessor
        (runs / f"run-{plan_rel.replace('/', '_')}-{start + index:03d}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )


def _manifest(cli, tmp_path, plan_path, **fields):
    manifest_path = cli.plan_review_manifest_path(_data(), tmp_path, plan_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": cli.PLAN_REVIEW_SCHEMA,
        "plan_path": _rel(plan_path.name),
        "round": "R1",
        "verdict": "blocked",
        "wrapper_exit_code": 0,
        "timestamp": "2026-08-15T09:00:00+00:00",
    }
    payload.update(fields)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _member_paths(members):
    return [member["plan_path"] for member in members]


# --------------------------------------------------------------------------------------
# T3.1 -- declared and inferred edges bind as a UNION (closes P1 #3)
# --------------------------------------------------------------------------------------


def test_a_declared_predecessor_binds_even_when_name_shape_also_matches(cli, tmp_path):
    """P1 #3. On `1e90a294` the seed was consulted only when inference found NOTHING, so a
    `-vN` plan launched with `--predecessor other.md` bound the budget to the name-inferred
    component and the declared edge never entered. The union admits BOTH."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "other.md")
    _plan(tmp_path, "admin-v2.md")
    _spend(cli, tmp_path, _rel("admin-v1.md"), 2, start=0)
    _spend(cli, tmp_path, _rel("other.md"), 3, start=10)

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v2.md"),
        current_rounds=0, declared_predecessor=_rel("other.md"),
    )

    assert set(_member_paths(members)) == {
        _rel("admin-v1.md"), _rel("other.md"), _rel("admin-v2.md")
    }, "the declared edge AND the name-shape edge must both be admitted"
    assert members[-1]["plan_path"] == _rel("admin-v2.md")
    assert truncated is False
    assert "declared" in sources and "name-shape" in sources
    summary = cli.plan_review_chain_summary(members, truncated)
    assert summary["cumulative_recorded_rounds"] == 5
    assert summary["evidence"] == "exact"

    # And the ADVISORY launch surface admits the same union -- one launch, one lineage.
    launch_members, _launch_truncated = cli.plan_review_launch_chain(
        _data(), tmp_path, _rel("admin-v2.md"), _rel("other.md"), 0
    )
    assert set(_member_paths(launch_members)) == set(_member_paths(members))


def test_advisory_and_authoritative_lineage_are_the_same_resolver_output(
    cli, tmp_path, monkeypatch
):
    """Every consumer -- the launch chain, the finalize refresh walk, and the merge-time
    (authoritative-ready) report -- must read THE resolver's member set, so one launch can
    never record two different lineages."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v2.md")
    _spend(cli, tmp_path, _rel("admin-v1.md"), 2, start=0)
    _spend(cli, tmp_path, _rel("admin-v2.md"), 1, start=10, predecessor=_rel("admin-v1.md"))

    resolved, resolved_truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v2.md")
    )
    chain_members, chain_truncated = cli.plan_review_chain_members(
        _data(), tmp_path, _rel("admin-v2.md")
    )
    merge_report = cli.plan_review_lineage_rounds_for_merge(
        _data(), tmp_path, _rel("admin-v2.md")
    )
    assert chain_members == resolved and chain_truncated == resolved_truncated
    assert merge_report["members"] == resolved

    # The delegation is structural, not coincidental: patch the resolver and every surface
    # must reflect the patched output.
    sentinel_members = [
        {"plan_path": _rel("sentinel.md"), "recorded_rounds": 7, "rounds_source": "run_metas"}
    ]
    monkeypatch.setattr(
        cli, "plan_review_lineage_members",
        lambda *args, **kwargs: (list(sentinel_members), True, ["declared"]),
    )
    patched_chain, patched_truncated = cli.plan_review_chain_members(
        _data(), tmp_path, _rel("admin-v2.md")
    )
    assert patched_chain == sentinel_members and patched_truncated is True
    patched_launch, _ = cli.plan_review_launch_chain(
        _data(), tmp_path, _rel("admin-v2.md"), _rel("admin-v1.md"), 0
    )
    assert patched_launch == sentinel_members
    assert cli.plan_review_lineage_rounds_for_merge(
        _data(), tmp_path, _rel("admin-v2.md")
    )["members"] == sentinel_members


# --------------------------------------------------------------------------------------
# T3.2 -- inference ENUMERATES existing entries (closes P1 #2 via DD)
# --------------------------------------------------------------------------------------


def test_a_v34_successor_finds_v1_without_materialising_candidate_names(cli, tmp_path):
    """P1 #2. The `1e90a294` descent generated candidate names v33..v2 plus the bare base and
    stopped at the 32-name bound, so `admin-v34` never found `admin-v1` -- the miss returned ""
    silently and the plan ran standalone on a fresh budget. Enumerating EXISTING entries has no
    such gap: only two files exist, so only two entries are ever examined."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v34.md")
    _spend(cli, tmp_path, _rel("admin-v1.md"), 3, start=0)

    inferred = cli.plan_review_name_shape_predecessor(_data(), tmp_path, _rel("admin-v34.md"))
    assert inferred == _rel("admin-v1.md")

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v34.md"), current_rounds=0
    )
    assert set(_member_paths(members)) == {_rel("admin-v1.md"), _rel("admin-v34.md")}
    assert truncated is False
    assert sources == ["name-shape"]
    summary = cli.plan_review_chain_summary(members, truncated)
    assert summary["cumulative_recorded_rounds"] == 3


def test_a_date_like_version_suffix_neither_hangs_nor_allocates(cli, tmp_path):
    """Salvaged from `1e90a294`, re-pointed at enumeration: `service-v20260815.md` must bind its
    ancestor in bounded time WITHOUT allocating twenty million candidate strings. Cost is
    bounded by directory size, so both the wall clock and the allocation peak stay tiny."""
    _plan(tmp_path, "service.md")
    _spend(cli, tmp_path, _rel("service.md"), 1, start=0)
    _plan(tmp_path, "service-v20260815.md")

    tracemalloc.start()
    started = time.monotonic()
    inferred = cli.plan_review_name_shape_predecessor(
        _data(), tmp_path, _rel("service-v20260815.md")
    )
    elapsed = time.monotonic() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert inferred == _rel("service.md"), "the existing ancestor must be found, not skipped"
    assert elapsed < 5, f"successor inference must stay bounded, took {elapsed:.1f}s"
    assert peak < 8 * 1024 * 1024, (
        f"enumeration of a two-file directory allocated {peak} bytes -- candidate-name "
        "materialisation is back"
    )


def test_name_shape_binding_walks_past_a_deleted_intermediate_version(cli, tmp_path):
    """Deleting the immediate predecessor must not hand the budget back: enumeration picks the
    highest EXISTING version below N, not `N-1` by construction."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v5.md")  # v2..v4 never existed
    _spend(cli, tmp_path, _rel("admin-v1.md"), 4, start=0)

    assert cli.plan_review_name_shape_predecessor(
        _data(), tmp_path, _rel("admin-v5.md")
    ) == _rel("admin-v1.md")
    members, truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v5.md"), current_rounds=0
    )
    assert cli.plan_review_chain_summary(members, truncated)[
        "cumulative_recorded_rounds"
    ] == 4


def test_a_deleted_predecessor_with_surviving_evidence_still_binds(cli, tmp_path):
    """The manifest outlives the plan file, so `rm` is not a way to buy rounds back: the
    enumeration lists reviewed ENTRIES (manifests, metas, records), not only files on disk."""
    ancestor = _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v3.md")
    _spend(cli, tmp_path, _rel("admin-v1.md"), 2, start=0)
    _manifest(cli, tmp_path, ancestor, observed_successful_runs=1, wrapper_exit_code=0)
    ancestor.unlink()

    assert cli.plan_review_name_shape_predecessor(
        _data(), tmp_path, _rel("admin-v3.md")
    ) == _rel("admin-v1.md")


# --------------------------------------------------------------------------------------
# T3.3 -- truncation is LOUD and the result is a FLOOR
# --------------------------------------------------------------------------------------


def _recorded_chain(cli, tmp_path, length):
    """`length` plans, each declaring the previous as predecessor, one round each."""
    previous = ""
    for index in range(length):
        name = f"deep-{index:03d}.md"
        _plan(tmp_path, name)
        _spend(cli, tmp_path, _rel(name), 1, start=index, predecessor=previous)
        previous = _rel(name)
    return previous  # the newest member


def test_a_truncated_lineage_walk_is_a_printed_floor_not_a_silent_fresh_budget(
    cli, tmp_path, capsys
):
    """A walk cut at `PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH` used to return a smaller lineage with no
    marker anywhere -- on the inference path it returned "" and the plan ran STANDALONE on a
    fresh budget. Now the cut is printed and the result is labelled a floor."""
    newest = _recorded_chain(cli, tmp_path, cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH + 8)

    members, truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, newest, current_rounds=1
    )

    assert truncated is True
    assert len(members) == cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH
    assert len(members) > 1, "a truncated walk must never read as a standalone plan"
    summary = cli.plan_review_chain_summary(members, truncated)
    assert summary["evidence"] == "floor", "a cut walk can only ever establish a floor"
    assert summary["cumulative_recorded_rounds"] >= cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH - 1
    err = capsys.readouterr().err
    assert "lineage_walk_truncated" in err
    assert "floor" in err.lower()
    assert "fresh budget" in err.lower()


def test_depth_capped_walks_emit_the_truncation_signal(cli, tmp_path, capsys):
    """Both cap kinds are loud (T3.3: 'component or chain depth'). The chain-depth cap is pinned
    above; this pins the COMPONENT cap -- and pins that the signal reaches the advisory wrapper
    every consumer calls, not only the resolver's own callers."""
    body = "Work item: item 108\n\n## Goal\n\nGo.\n"
    for index in range(cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH + 4):
        name = f"swarm-{index:03d}.md"
        _plan(tmp_path, name, body=body)
        _spend(cli, tmp_path, _rel(name), 1, start=index)

    members, truncated = cli.plan_review_chain_members(
        _data(), tmp_path, _rel("swarm-000.md")
    )

    assert truncated is True
    assert len(members) == cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH
    assert "lineage_walk_truncated" in capsys.readouterr().err
    assert cli.plan_review_chain_summary(members, truncated)["evidence"] == "floor"


def test_a_recorded_cycle_is_reported_as_truncation_not_looped(cli, tmp_path, capsys):
    """Two plans declaring each other as predecessor: the walk terminates, keeps both members
    exactly once, flags the truncation, and says so out loud."""
    _plan(tmp_path, "loop-a.md")
    _plan(tmp_path, "loop-b.md")
    _spend(cli, tmp_path, _rel("loop-a.md"), 1, start=0, predecessor=_rel("loop-b.md"))
    _spend(cli, tmp_path, _rel("loop-b.md"), 1, start=10, predecessor=_rel("loop-a.md"))

    members, truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("loop-b.md")
    )

    assert truncated is True
    assert sorted(_member_paths(members)) == [_rel("loop-a.md"), _rel("loop-b.md")]
    assert "lineage_walk_truncated" in capsys.readouterr().err


# --------------------------------------------------------------------------------------
# Salvaged from `1e90a294` -- resolver behaviors that were wanted then and are wanted now
# --------------------------------------------------------------------------------------


def test_binding_path_a_declared_predecessor(cli, tmp_path):
    """(a) The flag binds on the FIRST round, before it is recorded anywhere."""
    _plan(tmp_path, "alpha.md")
    _plan(tmp_path, "beta.md")
    _spend(cli, tmp_path, _rel("alpha.md"), 3, start=0)

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("beta.md"),
        current_rounds=0, declared_predecessor=_rel("alpha.md"),
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert summary["depth"] == 2
    assert summary["cumulative_recorded_rounds"] == 3
    assert sources == ["declared"]


def test_binding_path_b_name_shape_with_no_flag_at_all(cli, tmp_path):
    """(b) No flag, no recorded lineage -- the successor still draws down its ancestor."""
    _plan(tmp_path, "admin.md")
    _plan(tmp_path, "admin-v2.md")
    _spend(cli, tmp_path, _rel("admin.md"), 4, start=0)
    assert cli.plan_review_recorded_predecessor(_data(), tmp_path, _rel("admin-v2.md")) is None

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v2.md"), current_rounds=0
    )

    assert sources == ["name-shape"]
    assert cli.plan_review_chain_summary(members, truncated)[
        "cumulative_recorded_rounds"
    ] == 4


def test_binding_path_c_shared_declared_work_item(cli, tmp_path):
    """(c) A rename escapes the name shape; a declared work item does not."""
    ancestor = _plan(
        tmp_path, "first-attempt.md", body="Work item: item 86\n\n## Goal\n\nGo.\n"
    )
    _plan(
        tmp_path, "totally-different-name.md", body="Work item: Item  86\n\n## Goal\n\nGo.\n"
    )
    _spend(cli, tmp_path, _rel("first-attempt.md"), 3, start=0)
    _manifest(cli, tmp_path, ancestor, work_item_reference="item 86")

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("totally-different-name.md"), current_rounds=0
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert sources == ["work-item"]
    assert summary["depth"] == 2
    assert summary["cumulative_recorded_rounds"] == 3


def test_a_work_item_sibling_brings_its_own_ancestors_with_it(cli, tmp_path):
    """Counting a sibling alone while reporting `exact` is an undercount as fact."""
    body = "Work item: item 86\n\n## Goal\n\nGo.\n"
    _plan(tmp_path, "other-track-v1.md", body=body)
    _plan(tmp_path, "other-track-v2.md", body=body)
    _plan(tmp_path, "mine.md", body=body)
    _spend(cli, tmp_path, _rel("other-track-v1.md"), 2, start=0)
    _spend(cli, tmp_path, _rel("other-track-v2.md"), 2, start=10)

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("mine.md"), current_rounds=0
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert "work-item" in sources
    # v2 is the work-item sibling; v1 is v2's own name-shape ancestor and its spend counts too.
    assert summary["depth"] == 3
    assert summary["cumulative_recorded_rounds"] == 4
    assert summary["evidence"] == "exact"


def test_the_lineage_is_the_connected_closure_not_a_backward_walk(cli, tmp_path):
    """A declares work item X; its `-vN` successor B drops the field; a new plan C declares X.
    B is reachable only FORWARD from A, and its spend still counts toward C's lineage."""
    with_item = "Work item: item 86\n\n## Goal\n\nGo.\n"
    without_item = "## Goal\n\nGo.\n"
    _plan(tmp_path, "admin-v1.md", body=with_item)
    _plan(tmp_path, "admin-v2.md", body=without_item)
    _plan(tmp_path, "rewritten.md", body=with_item)
    _spend(cli, tmp_path, _rel("admin-v1.md"), 2, start=0)
    _spend(cli, tmp_path, _rel("admin-v2.md"), 3, start=10)

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("rewritten.md"), current_rounds=0
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert "work-item" in sources
    assert summary["depth"] == 3, "B is reachable only forward from A, and it is in the lineage"
    assert summary["cumulative_recorded_rounds"] == 5
    assert summary["evidence"] == "exact"


def test_an_unresolvable_recorded_reference_never_raises(cli, tmp_path):
    """A manifest naming a plan root this lane no longer configures must be retained as inert,
    never raised through either ceremony."""
    _plan(tmp_path, "admin.md", body="Work item: item 86\n\n## Goal\n\nGo.\n")
    reviews = tmp_path / "backlog" / "plans" / ".plan-reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    (reviews / "old-plan.json").write_text(
        json.dumps(
            {
                "schema": cli.PLAN_REVIEW_SCHEMA,
                "plan_path": "backlog:plans/old-plan.md",  # root token this lane does not know
                "verdict": "blocked",
                "timestamp": "2026-08-15T09:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    members, truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin.md"), current_rounds=0
    )

    assert _member_paths(members) == [_rel("admin.md")]
    assert truncated is False


def test_omitting_the_predecessor_flag_no_longer_refills_the_budget(cli, tmp_path):
    """The same lineage is counted identically with and without the flag."""
    _plan(tmp_path, "admin.md")
    _plan(tmp_path, "admin-v2.md")
    _spend(cli, tmp_path, _rel("admin.md"), 4, start=0)

    with_flag, with_truncated, _s1 = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v2.md"),
        current_rounds=1, declared_predecessor=_rel("admin.md"),
    )
    without_flag, without_truncated, _s2 = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("admin-v2.md"), current_rounds=1
    )

    with_summary = cli.plan_review_chain_summary(with_flag, with_truncated)
    without_summary = cli.plan_review_chain_summary(without_flag, without_truncated)
    assert (
        with_summary["cumulative_recorded_rounds"]
        == without_summary["cumulative_recorded_rounds"]
        == 5
    )
    assert with_summary["depth"] == without_summary["depth"] == 2


def test_an_unrelated_plan_binds_to_nothing(cli, tmp_path):
    """No shape, no flag, no work item, no lineage: the budget must not sweep in strangers."""
    _plan(tmp_path, "admin.md")
    _plan(tmp_path, "unrelated.md")
    _spend(cli, tmp_path, _rel("admin.md"), 4, start=0)

    members, truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("unrelated.md"), current_rounds=0
    )
    summary = cli.plan_review_chain_summary(members, truncated)

    assert summary["depth"] == 1
    assert summary["cumulative_recorded_rounds"] == 0
    assert sources == []
    assert truncated is False


# --------------------------------------------------------------------------------------
# WS1 record fields are consumable edges (item 108 WS3 reads what WS1 writes)
# --------------------------------------------------------------------------------------


def _round_record(cli, tmp_path, plan_name, *, declared_predecessor="", work_items=()):
    """One charged reviewer-invocation record under the committed reviews root."""
    module = cli.plan_round_record_module()
    plan_path = tmp_path / "backlog" / "plans" / plan_name
    rounds = cli.plan_review_rounds_dir(_data(), tmp_path, plan_path)
    record = module.render_reviewer_invocation(
        plan_identity=cli.plan_review_manifest_identity(_data(), tmp_path, plan_path),
        plan_path=_rel(plan_name),
        plan_content_sha256="0" * 64,
        declared_round="R1",
        wrapper_exit_code=0,
        reviewer="codex",
        reviewer_model="codex-test",
        started_at="2026-08-15T10:00:00+00:00",
        finished_at="2026-08-15T10:05:00+00:00",
        nonce="a" * 16,
        log_sha256="b" * 64,
        declared_predecessor=declared_predecessor,
        work_items=list(work_items),
        source="run",
    )
    return module.append_record(rounds, record)


def test_a_round_record_declared_predecessor_is_a_lineage_edge(cli, tmp_path):
    """WS1's durable record carries `declared_predecessor`; the resolver consumes it as an edge
    alongside manifests and run metas -- a lane whose metas were pruned keeps its lineage."""
    _plan(tmp_path, "root.md")
    _plan(tmp_path, "regrown.md")
    _spend(cli, tmp_path, _rel("root.md"), 2, start=0)
    _round_record(cli, tmp_path, "regrown.md", declared_predecessor=_rel("root.md"))

    members, _truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("regrown.md"), current_rounds=0
    )

    assert set(_member_paths(members)) == {_rel("root.md"), _rel("regrown.md")}
    assert "declared" in sources


def test_a_round_record_work_item_is_a_lineage_edge(cli, tmp_path):
    """WS1's `work_items` field binds siblings even when the plan text and manifests are gone."""
    _plan(tmp_path, "one-track.md")
    _plan(tmp_path, "other-track.md", body="Work item: item 99\n\n## Goal\n\nGo.\n")
    _spend(cli, tmp_path, _rel("other-track.md"), 3, start=0)
    _round_record(cli, tmp_path, "one-track.md", work_items=["item 99"])

    members, _truncated, sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("one-track.md"), current_rounds=0
    )

    assert set(_member_paths(members)) == {_rel("one-track.md"), _rel("other-track.md")}
    assert sources == ["work-item"]


def test_an_exact_cap_depth_chain_is_complete_not_a_floor(cli, tmp_path, capsys):
    """Codex R1 P2 (this lineage): a component of EXACTLY cap depth whose walk consumed every
    edge is a complete, honest answer -- labeling it a truncated floor said 'there was more'
    when there was not. Capped means only that unvisited edges remained beyond the cap."""
    body = "Work item: item 108\n\n## Goal\n\nGo.\n"
    for index in range(cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH):
        name = f"exact-{index:03d}.md"
        _plan(tmp_path, name, body=body)
        _spend(cli, tmp_path, _rel(name), 1, start=index)

    members, truncated = cli.plan_review_chain_members(
        _data(), tmp_path, _rel("exact-000.md")
    )

    assert len(members) == cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH
    assert truncated is False
    assert "lineage_walk_truncated" not in capsys.readouterr().err
    assert cli.plan_review_chain_summary(members, truncated)["evidence"] == "exact"


def test_the_hint_names_the_enumerated_predecessor(cli, tmp_path):
    """Codex R1 P3 (this lineage): the --predecessor adoption hint must name the SAME ancestor
    the resolver's enumerated inference binds advisorily -- the old v(N-1)/bare-base probe went
    silent on exactly the admin-v34 -> admin-v1 lineages the enumeration now finds."""
    _plan(tmp_path, "admin-v1.md")
    _plan(tmp_path, "admin-v34.md")
    _spend(cli, tmp_path, _rel("admin-v1.md"), 2, start=0)

    hint = cli.plan_review_lineage_shape_hint(
        _data(), tmp_path, tmp_path / "backlog" / "plans" / "admin-v34.md"
    )

    assert "plan_review_lineage_hint" in hint
    assert _rel("admin-v1.md") in hint
    assert "--predecessor" in hint


def test_a_declared_cycle_closing_at_the_depth_boundary_is_a_floor(cli, tmp_path, capsys):
    """Codex R2 P2 (this lineage): a recorded predecessor cycle that closes on the member
    reached exactly at cap depth escaped the cycle check the early return skipped -- a 32-plan
    ring read truncated=False/evidence=exact. The boundary member's edges get the same cycle
    reading as everywhere else."""
    body = "## Goal\n\nGo.\n"
    depth = cli.PLAN_REVIEW_CHAIN_WALK_MAX_DEPTH
    for index in range(depth):
        name = f"ring-{index:03d}.md"
        _plan(tmp_path, name, body=body)
    for index in range(depth):
        predecessor = _rel(f"ring-{(index + 1) % depth:03d}.md")
        _spend(cli, tmp_path, _rel(f"ring-{index:03d}.md"), 1, start=index,
               predecessor=predecessor)

    members, truncated = cli.plan_review_chain_members(_data(), tmp_path, _rel("ring-000.md"))

    assert len(members) == depth
    assert truncated is True
    assert cli.plan_review_chain_summary(members, truncated)["evidence"] == "floor"


def test_an_explicit_predecessor_with_only_a_round_record_is_accepted(cli, tmp_path):
    """Codex R3 P2 (this lineage): the --predecessor validator must accept the SAME evidence
    set the resolver counts. A lane whose .ai-runs was pruned before finalization still holds
    the durable round record; refusing its flag while the resolver counts that spend is two
    readers disagreeing about one truth."""
    _plan(tmp_path, "pruned-v1.md")
    _plan(tmp_path, "pruned-v2.md")
    # The predecessor's ONLY surviving evidence is its durable round record: no lane metas
    # were ever written here and no manifest was finalized.
    _round_record(cli, tmp_path, "pruned-v1.md")

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, tmp_path / "backlog" / "plans" / "pruned-v2.md",
        _rel("pruned-v2.md"), tmp_path / "backlog" / "plans" / "pruned-v1.md",
    )

    assert errors == [], errors
    assert resolved == _rel("pruned-v1.md")


def test_an_unresolvable_recorded_predecessor_is_an_unknown_member_not_a_crash(cli, tmp_path):
    """Codex R3 P2 (this lineage): a recorded predecessor whose plan-root token is no longer
    configured is admitted by identity but was crashing materialization with ValueError. It
    must surface as an unknown member on a floor walk instead."""
    _plan(tmp_path, "renamed-v2.md")
    _spend(cli, tmp_path, _rel("renamed-v2.md"), 1, start=0,
           predecessor="gone-root:old/plans/renamed-v1.md")

    members, _truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("renamed-v2.md")
    )

    by_path = {m["plan_path"]: m for m in members}
    assert "gone-root:old/plans/renamed-v1.md" in by_path
    unknown = by_path["gone-root:old/plans/renamed-v1.md"]
    assert unknown["recorded_rounds"] is None
    assert unknown["rounds_source"] == "unresolved"


def test_a_contradictory_flag_is_refused_when_lineage_survives_only_in_records(cli, tmp_path):
    """Codex R4 P2 (this lineage): after .ai-runs pruning, the declared predecessor survives
    only in the durable round record -- the conflict branch must read it there, or one plan can
    append contradictory --predecessor declarations while the resolver counts the original."""
    _plan(tmp_path, "orig.md")
    _plan(tmp_path, "other.md")
    _plan(tmp_path, "succ-v2.md")
    _round_record(cli, tmp_path, "succ-v2.md", declared_predecessor=_rel("orig.md"))
    _round_record(cli, tmp_path, "orig.md")
    _round_record(cli, tmp_path, "other.md")

    errors, resolved = cli.plan_review_lineage_errors(
        _data(), tmp_path, tmp_path / "backlog" / "plans" / "succ-v2.md",
        _rel("succ-v2.md"), tmp_path / "backlog" / "plans" / "other.md",
    )

    assert errors, "a flag contradicting the record-surviving declaration must be refused"
    assert _rel("orig.md") in errors[0]
    assert resolved == ""


def test_an_uncharged_failed_record_is_not_review_evidence(cli, tmp_path):
    """Codex R5 P2 (this lineage): a failed wrapper's uncharged invocation record is not
    evidence -- the predicate must match the meta path's success filter, or a predecessor with
    zero successful reviews binds lineage it never earned."""
    _plan(tmp_path, "failed-v1.md")
    module = cli.plan_round_record_module()
    plan_path = tmp_path / "backlog" / "plans" / "failed-v1.md"
    rounds = cli.plan_review_rounds_dir(_data(), tmp_path, plan_path)
    record = module.render_reviewer_invocation(
        plan_identity=cli.plan_review_manifest_identity(_data(), tmp_path, plan_path),
        plan_path=_rel("failed-v1.md"),
        plan_content_sha256="0" * 64,
        declared_round="R1",
        wrapper_exit_code=1,
        reviewer="codex",
        reviewer_model="codex-test",
        started_at="2026-08-16T10:00:00+00:00",
        finished_at="2026-08-16T10:05:00+00:00",
        nonce="f" * 16,
        log_sha256="e" * 64,
        declared_predecessor="",
        work_items=[],
        source="run",
    )
    module.append_record(rounds, record)

    assert not cli.plan_review_reference_has_review_evidence(
        _data(), tmp_path, _rel("failed-v1.md")
    )


def test_an_uncharged_record_declaration_is_not_the_recorded_lineage(cli, tmp_path):
    """Codex R1 P2 (post-rebase lineage): a failed wrapper still writes its invocation record,
    and reading `declared_predecessor` from an UNCHARGED one let a run that produced no review
    become the recorded lineage -- conflicting with a later correct --predecessor and pulling an
    ancestor's spend into the budget. The record reader is charged-only, like the meta reader."""
    _plan(tmp_path, "ghost.md")
    _plan(tmp_path, "succ-v2.md")
    module = cli.plan_round_record_module()
    plan_path = tmp_path / "backlog" / "plans" / "succ-v2.md"
    rounds = cli.plan_review_rounds_dir(_data(), tmp_path, plan_path)
    module.append_record(
        rounds,
        module.render_reviewer_invocation(
            plan_identity=cli.plan_review_manifest_identity(_data(), tmp_path, plan_path),
            plan_path=_rel("succ-v2.md"),
            plan_content_sha256="0" * 64,
            declared_round="R1",
            wrapper_exit_code=1,
            reviewer="codex",
            reviewer_model="codex-test",
            started_at="2026-08-17T10:00:00+00:00",
            finished_at="2026-08-17T10:05:00+00:00",
            nonce="d" * 16,
            log_sha256="c" * 64,
            declared_predecessor=_rel("ghost.md"),
            work_items=[],
            source="run",
        ),
    )

    assert cli.plan_review_recorded_predecessor(_data(), tmp_path, _rel("succ-v2.md")) is None


def test_an_uncharged_record_contributes_no_work_item_edge(cli, tmp_path):
    """Codex R2 P2 (post-rebase lineage): a failed wrapper records its work_items too, and
    harvesting them let an attempt that produced no review bind this plan to same-item siblings
    and their ancestors once the plan text changed. Every lineage edge -- predecessor OR work
    item -- must rest on a review that actually happened; one predicate now enforces both."""
    _plan(tmp_path, "sibling.md", body="Work item: item 999\n\n## Goal\n\nGo.\n")
    _spend(cli, tmp_path, _rel("sibling.md"), 2, start=0)
    # This plan's LIVE text declares no work item; only a FAILED attempt recorded one.
    _plan(tmp_path, "quiet.md", body="## Goal\n\nGo.\n")
    module = cli.plan_round_record_module()
    plan_path = tmp_path / "backlog" / "plans" / "quiet.md"
    rounds = cli.plan_review_rounds_dir(_data(), tmp_path, plan_path)
    module.append_record(
        rounds,
        module.render_reviewer_invocation(
            plan_identity=cli.plan_review_manifest_identity(_data(), tmp_path, plan_path),
            plan_path=_rel("quiet.md"),
            plan_content_sha256="0" * 64,
            declared_round="R1",
            wrapper_exit_code=1,
            reviewer="codex",
            reviewer_model="codex-test",
            started_at="2026-08-17T10:00:00+00:00",
            finished_at="2026-08-17T10:05:00+00:00",
            nonce="e" * 16,
            log_sha256="a" * 64,
            declared_predecessor="",
            work_items=["item 999"],
            source="run",
        ),
    )

    assert cli.plan_review_work_items_for_rel(_data(), tmp_path, _rel("quiet.md")) == set()
    members, _truncated, _sources = cli.plan_review_lineage_members(
        _data(), tmp_path, _rel("quiet.md")
    )
    assert _rel("sibling.md") not in _member_paths(members)
