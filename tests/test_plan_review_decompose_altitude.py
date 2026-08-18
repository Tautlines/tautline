"""Item 90 WS4 (plan-review round economy): decomposition altitude + lineage-round reporting.

D6: decomposition moves before R1. The round-3 stall and hard-cap FINALIZE remedies used to name
"decompose this plan into smaller source-of-truth plans" as the exit -- which is precisely the
budget-refill loop this program exists to close (a successor plan is a new file path, and a new
file path gets a fresh round budget). D2 (WS1, the release valve) has since landed: the hard cap
now finalizes automatically as `capped-with-open-findings` with the open Critical/P1 carried as
BINDING implementation-review focus items, so the hard-cap assertions here pin the valve's
behavior; the three round-3-stall branches still record `blocked` with the manual carry remedy.
This module pins two things:

1. (T4.1) No FINALIZE-time cap-state message (`finalize_trusted_plan_review`'s convergence_errors
   ladder, the seams named `cli.py:33039`/`cli.py:33062` in the plan) instructs the agent to spawn
   a successor plan or "split" as its exit -- checked both statically (a function-scoped guard
   that cannot regress) and behaviorally (the actual printed remedy at the hard cap and at the
   round-3 stall).

   NOTE: `plan_review_hard_cap_refusal`/`plan_review_round_cap_errors` (the ROUND-LAUNCH refusal,
   i.e. `run-plan-review --round R5` past the cap) is a DIFFERENT surface, out of this task's named
   seams, and is pinned by tests/test_plan_review_convergence.py to still say "the split is
   mandatory" -- deliberately untouched here.

2. (T4.2) Cumulative LINEAGE review rounds are reported per merged PR
   (`milestone-advance --event pr-merged`), reusing the existing `plan_review_round` /
   `plan_review_clean` / `plan_review_blocked` v1 vocabulary -- no enum change, so no T0
   vocabulary re-approval gate.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from test_plan_review_chain_accounting import _data as _chain_data
from test_plan_review_chain_accounting import _plan as _chain_plan
from test_plan_review_chain_accounting import _rel as _chain_rel
from test_plan_review_chain_accounting import _write_manifest as _chain_write_manifest
from test_plan_review_chain_accounting import _write_run_meta as _chain_write_run_meta
from test_plan_review_convergence import CLEAN, _blocked, _mutate_plan, _run_round
from test_plan_review_cli import PLAN_REL, _prepare_target, _run_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
CLI_SOURCE = CLI_SOURCE_PATH.read_text(encoding="utf-8")

# The exact instruction this program exists to remove: a cap-state message naming a successor
# plan / decomposition as the way to spend past the budget. Matched literally, not by keyword,
# so a message that merely uses the word "decompose" in its own right (pre-R1 authoring guidance,
# a docstring reasoning about why a split would be WRONG) does not false-positive.
FORBIDDEN_SPLIT_INSTRUCTIONS = (
    "decompose this plan into smaller",
    "split the work into smaller",
    "split the work unless",
    "the split is mandatory",
)


# --- 1a. Static guard: the FINALIZE convergence ladder never regresses to a split instruction ---


def _function_source(name: str) -> str:
    tree = ast.parse(CLI_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(CLI_SOURCE, node)
            assert segment is not None, name
            return segment
    raise AssertionError(f"function {name!r} not found in {CLI_SOURCE_PATH}")


FINALIZE_SOURCE = _function_source("finalize_trusted_plan_review")


@pytest.mark.parametrize("phrase", FORBIDDEN_SPLIT_INSTRUCTIONS)
def test_finalize_convergence_ladder_never_names_a_split_instruction(phrase):
    """Grep-based guard (T4.1 review gate): the retired instruction cannot regress into
    `finalize_trusted_plan_review`'s convergence-error ladder -- the hard-cap and round-3-stall
    messages named in the plan (`cli.py:~33037` region)."""
    assert phrase not in FINALIZE_SOURCE, (
        f"{phrase!r} regressed into finalize_trusted_plan_review's convergence-error ladder; "
        "the exit is the build (carried into the implementation-review focus list), never a "
        "successor plan"
    )


def test_finalize_convergence_ladder_points_at_the_build():
    """The replacement remedy text names an exit that is actually runnable TODAY: carry the
    finding into the implementation-review focus list by hand and proceed. (Codex R1 P1: naming
    the not-yet-implemented `capped-with-open-findings` verdict directly was a dead end on this
    branch alone -- WS1 ships that automatic finalize in a separate PR.)"""
    assert (
        "carry every unresolved Critical/P1 into the implementation-review focus list"
        in FINALIZE_SOURCE
    )
    assert "proceed to the build" in FINALIZE_SOURCE


def test_hard_cap_finalize_suppresses_the_chain_advisory_split_remedy(tmp_path):
    """Codex R1 P1: `plan_review_chain_advisory_line` (a DIFFERENT print in the same finalize
    call, fired when a succession chain crosses depth/round advisory thresholds) has its own
    remedy text -- "decompose the scope into smaller independent source-of-truth plans" -- which
    is the exact split instruction the convergence ladder above just replaced. A capped plan that
    also happens to belong to a big chain would get BOTH messages in the same finalize call,
    directly contradicting each other. The advisory must be suppressed whenever convergence_errors
    fired -- and on the valve's capped finalize, which just told the lane to build; the
    authoritative cap-state remedy already printed is what a capped lane should read."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    # Depth 2 ancestors recorded directly on disk, rooted at PLAN_REL's own source-of-truth
    # layout (mirrors test_milestone_advance_pr_merged_prints_lineage_rounds_for_a_known_chain,
    # since _chain_plan's root does not match this adapter's configured source root). Depth 3
    # (2 ancestors + this plan), cumulative rounds > 8 (ADVISORY_ROUNDS=8): ancestor carries 5,
    # predecessor carries 4, plus this plan's own 4 rounds below.
    ancestor_rel = PLAN_REL.parent / "test-plan-v1.md"
    (target / ancestor_rel).parent.mkdir(parents=True, exist_ok=True)
    (target / ancestor_rel).write_text("# Ancestor\n\n## Goal\n\nOldest scope.\n", encoding="utf-8")
    manifest_dir = target / ancestor_rel.parent / ".plan-reviews"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{ancestor_rel.stem}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-plan-review/v1",
                "verdict": "clean",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "observed_successful_runs": 5,
                "wrapper_exit_code": 0,
            }
        ),
        encoding="utf-8",
    )
    predecessor_rel = PLAN_REL.parent / "test-plan-v2.md"
    (target / predecessor_rel).write_text(
        "# Predecessor\n\n## Goal\n\nMiddle scope.\n", encoding="utf-8"
    )
    (manifest_dir / f"{predecessor_rel.stem}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-plan-review/v1",
                "verdict": "clean",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "observed_successful_runs": 4,
                "wrapper_exit_code": 0,
                "predecessor_plan_path": ancestor_rel.as_posix(),
            }
        ),
        encoding="utf-8",
    )

    assert _run_round(
        home, adapter_root, target, adapter, "R1", "--predecessor",
        predecessor_rel.as_posix(), *_blocked(3)
    ).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    NOTE = "R3 self-authorized; one blocker remains genuinely unresolved"
    r3 = _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    )
    assert r3.returncode == 0, r3.stdout + r3.stderr
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    combined = r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in combined
    assert "decompose the scope into smaller" not in combined, (
        "the chain advisory's own split remedy leaked into a capped finalize's output"
    )
    assert "plan_review_chain_advisory" not in combined


def test_finalize_convergence_ladder_names_the_precheck_bypass():
    """Codex R1 P1 (2nd re-run): "proceed to the build" was a dead end on its own -- a compliant
    agent that then runs plan-finalization-precheck (the adapter's own documented pre-implementation
    step) hits a refusal, because that gate only accepts clean/clean-with-deferrals and this
    verdict is recorded `blocked`. Every remedy branch must say so explicitly: precheck's refusal
    here is EXPECTED and is not itself a blocker, so the agent proceeds without waiting on it.
    Since the valve (WS1) landed, the hard-cap branch finalizes as `capped-with-open-findings`
    -- which precheck accepts directly -- so only the three round-3-stall variants still record
    `blocked` and still owe the note."""
    assert FINALIZE_SOURCE.count("proceed to the build") == 3, (
        "expected the three round-3-stall convergence branches to name the build exit (the "
        "hard-cap branch now finalizes capped instead of refusing)"
    )
    assert "plan-finalization-precheck correctly refuses" in FINALIZE_SOURCE
    assert "do not wait on" in FINALIZE_SOURCE


# --- 1b. Behavioral: the printed remedy at the hard cap and at the round-3 stall ------------------


def test_hard_cap_finalize_remedy_points_at_a_capped_finalize_not_a_split(tmp_path):
    """R1-R3 blocked (self-authorized with a note), R4 still blocked: R4 IS the hard cap
    (PLAN_REVIEW_HARD_CAP_ROUNDS=4). Since the valve (WS1) landed this is no longer a refusal:
    the finalize succeeds (exit 0) with verdict `capped-with-open-findings`, the open blocker is
    carried BINDING into the implementation-review focus list, and no split instruction is
    printed. The round-LAUNCH refusal (exit 1, a different surface) is checked by
    test_plan_review_convergence.py's R5 tests and deliberately untouched by this change."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    NOTE = "R3 self-authorized; one blocker remains genuinely unresolved"
    r3 = _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    )
    assert r3.returncode == 0, r3.stdout + r3.stderr
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    combined = r4.stdout + r4.stderr
    for phrase in FORBIDDEN_SPLIT_INSTRUCTIONS:
        assert phrase not in combined, f"hard-cap finalize remedy still names {phrase!r}"
    # The valve (WS1) is landed: the capped verdict is real, printed, and carried BINDING.
    assert "plan_review_capped: verdict=capped-with-open-findings" in combined
    assert "implementation-review focus items" in combined
    assert "Do not spawn a successor plan" in combined
    # Precheck accepts `capped-with-open-findings` directly, so the old "precheck correctly
    # refuses" bypass note must NOT appear on the capped path -- it would tell the lane to
    # ignore a gate that now passes.
    assert "plan-finalization-precheck correctly refuses" not in combined


def test_round_3_stall_finalize_remedy_points_at_a_capped_finalize_not_a_split(tmp_path):
    """R1/R2 blocked, R3 self-authorized but STILL blocked with the SAME (not reduced) blocker
    count: this is the "has not reduced unresolved Critical/P1 blockers by round 3" branch."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(2)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. An edit that does not fix the blocker.\n")
    NOTE = "R3 self-authorized; still investigating the blocker"
    r3 = _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(2)
    )

    assert r3.returncode == 2, r3.stdout + r3.stderr
    combined = r3.stdout + r3.stderr
    assert "has not reduced unresolved Critical/P1 blockers by round 3" in combined
    for phrase in FORBIDDEN_SPLIT_INSTRUCTIONS:
        assert phrase not in combined, f"round-3-stall finalize remedy still names {phrase!r}"
    assert "capped-with-open-findings" not in combined
    assert "implementation-review focus list" in combined


# --- 1c. The adapter-render mirror (byte-budget corridor) also drops the split instruction -------


def test_rendered_adapter_autonomy_and_planning_drops_the_split_instruction(cli, tmp_path):
    """The `## Autonomy And Planning` block rendered into every generated adapter must not carry
    the retired split instruction either -- it is agent-facing policy surface, same as the CLI
    messages. The lead-in clause stays byte-identical (pinned by
    tests/test_generated_adapter_contract.py's REQUIRED_RENDERED_ADAPTER_MARKERS)."""
    data = cli.load_project(REPO_ROOT / "adapters" / "projects" / "example-saas.json")
    files = cli.expected_files(data, str(REPO_ROOT / "adapters" / "projects" / "example-saas.json"))
    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files[filename]
        assert (
            "Review target is 2 rounds; rounds 3-4 self-authorize with `--exception-note`"
            in content
        ), filename
        for phrase in FORBIDDEN_SPLIT_INSTRUCTIONS:
            assert phrase not in content, f"{filename} still carries {phrase!r}"


# --- 2. Cumulative lineage rounds are reported per merged PR (T4.2) -------------------------------


def test_lineage_rounds_report_sums_a_known_three_plan_chain(cli, tmp_path):
    """Pure-function unit test: a three-plan chain with known per-member spend must sum exactly.

    Mirrors test_plan_review_chain_accounting.py's own chain-walk fixtures one level deeper: run
    metas on disk are the authoritative per-member spend (manifests are consulted only when no
    run metas survive), so this needs no manifest at all.
    """
    data = _chain_data()
    _chain_plan(tmp_path, "admin.md")
    _chain_plan(tmp_path, "admin-v2.md")
    _chain_plan(tmp_path, "admin-v3.md")
    _chain_write_run_meta(cli, tmp_path, _chain_rel("admin.md"), idx=1)
    _chain_write_run_meta(cli, tmp_path, _chain_rel("admin.md"), idx=2)
    _chain_write_run_meta(
        cli, tmp_path, _chain_rel("admin-v2.md"), idx=3,
        predecessor_plan_path=_chain_rel("admin.md")
    )
    _chain_write_run_meta(
        cli, tmp_path, _chain_rel("admin-v3.md"), idx=4,
        predecessor_plan_path=_chain_rel("admin-v2.md")
    )
    _chain_write_run_meta(
        cli, tmp_path, _chain_rel("admin-v3.md"), idx=5,
        predecessor_plan_path=_chain_rel("admin-v2.md")
    )

    report = cli.plan_review_lineage_rounds_for_merge(data, tmp_path, _chain_rel("admin-v3.md"))

    assert report["depth"] == 3
    assert report["cumulative_recorded_rounds"] == 5  # 2 + 1 + 2
    assert report["evidence"] == "exact"

    line = cli.plan_review_lineage_rounds_merge_line("77", report)
    assert line == (
        "plan_review_lineage_rounds_at_merge: pr=77 plan=backlog/plans/admin-v3.md depth=3 "
        "cumulative_recorded_rounds=5 evidence=exact "
        "(vocabulary: plan_review_round/plan_review_clean/plan_review_blocked)"
    )


def test_lineage_rounds_report_marks_a_floor_when_a_member_is_unknown(cli, tmp_path):
    """An unrecoverable member's spend must never be invented -- the total is a floor, marked."""
    data = _chain_data()
    ancestor = _chain_plan(tmp_path, "admin.md")
    _chain_plan(tmp_path, "admin-v2.md")
    # A pre-lineage manifest: no run metas survive and it carries no observed_successful_runs.
    _chain_write_manifest(cli, tmp_path, ancestor)
    _chain_write_run_meta(
        cli, tmp_path, _chain_rel("admin-v2.md"), idx=1,
        predecessor_plan_path=_chain_rel("admin.md")
    )

    report = cli.plan_review_lineage_rounds_for_merge(data, tmp_path, _chain_rel("admin-v2.md"))

    assert report["evidence"] == "floor"
    line = cli.plan_review_lineage_rounds_merge_line("12", report)
    assert "cumulative_recorded_rounds=>=" in line


def test_lineage_rounds_report_does_not_undercount_a_partially_pruned_member(cli, tmp_path):
    """Codex R1 P2: retained run metas being NONEMPTY does not mean COMPLETE. A member whose
    .ai-runs/plan-review history was partially pruned still has ONE surviving meta, but its
    finalized manifest remembers observed_successful_runs=3 plus a successful bind (round 4
    total) -- the true, larger number, not the surviving meta count."""
    data = _chain_data()
    plan_path = _chain_plan(tmp_path, "admin.md")
    _chain_write_manifest(cli, tmp_path, plan_path, observed_successful_runs=3, wrapper_exit_code=0)
    _chain_write_run_meta(cli, tmp_path, _chain_rel("admin.md"), idx=4)

    report = cli.plan_review_lineage_rounds_for_merge(data, tmp_path, _chain_rel("admin.md"))

    assert report["cumulative_recorded_rounds"] == 4, (
        "1 surviving run meta must not shadow the manifest's larger, more complete count"
    )
    assert report["evidence"] == "exact"


def test_milestone_advance_pr_merged_prints_lineage_rounds_for_a_known_chain(tmp_path):
    """End-to-end (T4.2 review gate: "the number is emitted and correct for a known chain"): a
    milestone started from a plan with two prior chained ancestors reports the FULL lineage total
    at `milestone-advance --event pr-merged`, not just the current plan's own spend."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    # milestone-start requires an ordered tactical queue section (bullet items under one of a
    # fixed set of headings) that the plan-review fixture plan does not carry by default.
    plan_path = target / PLAN_REL
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8")
        + "\n## Tactical Queue\n- Ship the reviewed change.\n",
        encoding="utf-8",
    )
    # PLAN_REL already has one clean round recorded via a predecessor chain built directly on
    # disk, mirroring test_plan_review_chain_accounting's fixtures but rooted at PLAN_REL's own
    # source-of-truth layout (docs/product/backlog/example-saas-v1/specs).
    predecessor_rel = PLAN_REL.parent / "test-plan-v1.md"
    (target / predecessor_rel).parent.mkdir(parents=True, exist_ok=True)
    (target / predecessor_rel).write_text(
        "# Predecessor\n\n## Goal\n\nEarlier scope.\n", encoding="utf-8"
    )
    predecessor_manifest_dir = target / predecessor_rel.parent / ".plan-reviews"
    predecessor_manifest_dir.mkdir(parents=True, exist_ok=True)
    (predecessor_manifest_dir / f"{predecessor_rel.stem}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-plan-review/v1",
                "verdict": "clean",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "observed_successful_runs": 0,
                "wrapper_exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    assert _run_round(
        home, adapter_root, target, adapter, "R1", "--predecessor",
        predecessor_rel.as_posix(), *CLEAN
    ).returncode == 0

    start = _run_cli(
        "milestone-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )
    assert start.returncode == 0, start.stdout + start.stderr

    merged = _run_cli(
        "milestone-advance",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--event",
        "pr-merged",
        "--pr",
        "555",
        home=home,
        adapter_root=adapter_root,
    )
    assert merged.returncode == 0, merged.stdout + merged.stderr
    lineage_lines = [
        line
        for line in merged.stdout.splitlines()
        if line.startswith("plan_review_lineage_rounds_at_merge:")
    ]
    assert len(lineage_lines) == 1, merged.stdout
    line = lineage_lines[0]
    assert "pr=555" in line
    assert "depth=2" in line
    assert "cumulative_recorded_rounds=2" in line  # 1 (predecessor manifest) + 1 (this R1)
    assert "evidence=exact" in line


def test_milestone_advance_pr_merged_omits_the_lineage_line_when_no_pr_is_known(tmp_path):
    """Codex R1 P2 (re-run): `pr-merged --item-index N` is a supported call with no `--pr`, and
    when the selected item never passed through `pr-queued` (so it carries no stored `pr` either),
    the old fallback `item.get("pr") or args.pr or ""` produced an empty string that still printed
    `plan_review_lineage_rounds_at_merge: pr=...` -- an unattributable line advertised as a per-PR
    report. The fix omits the line entirely rather than print `pr=` empty."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    plan_path = target / PLAN_REL
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8")
        + "\n## Tactical Queue\n- Ship the reviewed change.\n",
        encoding="utf-8",
    )
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0

    start = _run_cli(
        "milestone-start",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )
    assert start.returncode == 0, start.stdout + start.stderr

    # No --pr, and this item never passed through pr-queued: both attribution sources are empty.
    merged = _run_cli(
        "milestone-advance",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--event",
        "pr-merged",
        "--item-index",
        "1",
        home=home,
        adapter_root=adapter_root,
    )
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert "plan_review_lineage_rounds_at_merge:" not in merged.stdout
    assert "pr=" not in merged.stdout


def test_no_new_instrumentation_enum_values_were_introduced(cli):
    """T4.2 review gate: "confirm no new enum values were introduced" -- the lineage report reuses
    the EXISTING v1 vocabulary (plan_review_round/plan_review_clean/plan_review_blocked); the
    approved v1 enum itself must be byte-identical to what shipped before this change."""
    assert cli.INSTRUMENTATION_EVENT_CODES == (
        "startup",
        "preflight",
        "planning_review_gate",
        "plan_review_round",
        "plan_review_clean",
        "plan_review_blocked",
        "implementation_review_round",
        "implementation_review_clean",
        "implementation_review_blocked",
        "gate_block",
        "autonomy_stop",
        "human_question",
        "blocker_declared",
        "blocker_cleared",
        "rca",
        "continuity_written",
        "context_rotation",
        "goal_transition",
        "milestone_transition",
        "pr_opened",
        "pr_queue_merge",
        "pr_merged",
        "ci_wait",
        "merge_queue_wait",
        "task_started",
        "task_completed",
        "session_end",
    )
    assert {"plan_review_round", "plan_review_clean", "plan_review_blocked"} <= set(
        cli.INSTRUMENTATION_EVENT_CODES
    )
