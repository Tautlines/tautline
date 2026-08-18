"""Track D: the plan-review convergence ladder.

Operator convergence directive (2026-07-13): optimize for quality, then time. Rounds 1-2 are the
convergence TARGET. Rounds 3-4 are SELF-AUTHORIZED with a recorded exception note -- the tool never
stops to ask the operator to authorize a round. Past round 4 the hard cap is ABSOLUTE: refusal is
unconditional and only the refusal *message* varies with state (mandatory split when blockers
remain, finalize-the-existing-evidence otherwise).

A plan that converges within two rounds must behave exactly as it did before this policy landed.
"""

import json
from pathlib import Path

from test_plan_review_cli import (
    PLAN_REL,
    _manifest_path,
    _prepare_target,
    _run_cli,
    _stdout_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a shim.
CLI_SOURCE = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")

# >= 20 characters: a recorded exception must be a real reason, not a rubber stamp.
NOTE = "R2 blockers are fixed; one bound convergence round rebinds the evidence"


def _mutate_plan(target: Path, marker: str) -> None:
    """Land 'fixes' in the plan so its normalized content hash moves off the bound hash."""
    path = target / PLAN_REL
    text = path.read_text(encoding="utf-8")
    anchor = "3. Record the review evidence.\n"
    assert anchor in text
    path.write_text(text.replace(anchor, anchor + marker), encoding="utf-8")


def _run_round(home, adapter_root, target, adapter, review_round, *finalize_args):
    return _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        review_round,
        "--model",
        "codex-test",
        *finalize_args,
        home=home,
        adapter_root=adapter_root,
    )


def _blocked(critical: int) -> tuple[str, ...]:
    findings = [{"severity": "Critical", "summary": f"blocking issue {index}"} for index in range(critical)]
    return (
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        str(critical),
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        json.dumps(findings),
    )


CLEAN: tuple[str, ...] = (
    "--verdict",
    "clean",
    "--unresolved-critical-count",
    "0",
    "--unresolved-p1-count",
    "0",
    "--classified-findings-json",
    "[]",
)


def _precheck(home, adapter_root, target, adapter):
    return _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )


def test_convergence_round_allowed_after_blocked_round_with_changed_plan(tmp_path):
    """R1+R2 blocked, fixes land, R3 self-authorizes: no operator escalation, no carry-forward."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *_blocked(2))
    r2 = _run_round(home, adapter_root, target, adapter, "R2", *_blocked(1))
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert r2.returncode == 0, r2.stdout + r2.stderr

    _mutate_plan(target, "4. Land the fixes Codex demanded in R2.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3")

    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert "plan_review_exception: convergence round 3 of 4 - blockers addressed after final bound round" in r3.stdout
    assert "convergence target" not in r3.stderr


def test_rebinding_round_allowed_after_voided_run(tmp_path):
    """A successful-but-voided run (plan edited, never finalized) is rebindable, not a dead end."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1").returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2").returncode == 0

    _mutate_plan(target, "4. Edit the plan, voiding the bound run metadata.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3")

    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert "plan_review_exception: convergence round 3 of 4 - rebinding round after a voided run" in r3.stdout
    assert "finalize that run instead of launching another one" not in r3.stderr


def test_finalized_then_superseded_run_is_not_a_voided_run(tmp_path):
    """Two CLEAN finalized rounds + a plan edit must NOT self-authorize R3.

    The manifest binds exactly ONE run-meta (the latest round), so R1's meta is orphaned by design
    the moment R2 finalizes. Treating that orphan as a "voided run" would let any plan edit after a
    clean convergence self-authorize rounds 3-4 with no note -- and the tool would pre-fill its own
    printed next-action with a *fabricated* reason, which an obedient agent then writes verbatim
    into the hash-bound manifest as a false attestation. No run was voided here: both finalized.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *CLEAN).returncode == 0

    _mutate_plan(target, "4. Fix a typo after a clean convergence.\n")

    for review_round in ("R3", "R4"):
        result = _run_round(home, adapter_root, target, adapter, review_round)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "--exception-note" in result.stderr
        # The tool must never invent the operator's reason for them.
        assert "rebinding round after a voided run" not in result.stdout
        assert "rebinding round after a voided run" not in result.stderr
        assert "no voided run to rebind" not in result.stdout

    # The explicit, honest path still works: a recorded reason buys the round.
    noted = _run_round(home, adapter_root, target, adapter, "R3", "--exception-note", NOTE)
    assert noted.returncode == 0, noted.stdout + noted.stderr
    assert f"plan_review_exception: convergence round 3 of 4 - {NOTE}" in noted.stdout


def test_rebinding_round_allowed_after_voided_run_past_a_bound_manifest(tmp_path):
    """A run voided AFTER the manifest was bound is still a real dead end, so it self-authorizes.

    Discriminating case for the predicate above: a manifest EXISTS (bound at R2), and the stranded
    R3 run sits past it. This is the genuine rebinding state -- refusing here would strand the
    operator with a successful run that can never be finalized.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *CLEAN).returncode == 0

    _mutate_plan(target, "4. Fix a typo after a clean convergence.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3", "--exception-note", NOTE)
    assert r3.returncode == 0, r3.stdout + r3.stderr

    # R3 succeeded but is voided by a further edit before it could be finalized.
    _mutate_plan(target, "5. Edit again, voiding the successful R3 run.\n")
    r4 = _run_round(home, adapter_root, target, adapter, "R4")

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_exception: convergence round 4 of 4 - rebinding round after a voided run" in r4.stdout


def test_round_at_hard_cap_releases_into_build(tmp_path):
    """At the cap the finalize RELEASES (D2); a fifth round is still refused, now toward build.

    This test used to assert the opposite -- R4 exiting 2 and R5 being told the split was
    mandatory -- and that assertion was the defect written down: a successor plan is a new file
    path and a new file path is a fresh four-round budget, so the refusal here was the refill
    instruction. The budget is unchanged; only its exit moved from prose to code.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1))
    assert r3.returncode == 0, r3.stdout + r3.stderr
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1))
    assert r4.returncode == 0, r4.stdout + r4.stderr

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["round"] == "R4"
    assert manifest["verdict"] == "capped-with-open-findings"
    assert manifest["asserted_verdict"] == "blocked"

    _mutate_plan(target, "6. Try to buy a fifth round.\n")
    r5 = _run_round(home, adapter_root, target, adapter, "R5", "--exception-note", NOTE)

    assert r5.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in r5.stderr
    # The plan moved after the capped manifest was bound, so this lane's bound evidence is stale
    # and the message is the generic past-cap one -- but it is still a refusal of the ROUND, never
    # of every exit, and the capped-evidence remedy is asserted on its own lane in
    # tests/test_plan_review_release_valve.py.
    # Refusal is a directive, never an operator question.
    assert "?" not in r5.stderr
    assert "do not ask the operator" in r5.stderr


def test_round_past_hard_cap_refused_even_when_clean(tmp_path):
    """The hard cap is absolute: clean, blocked, or evidence-free, round 5 never launches.

    Only the refusal MESSAGE is state-dependent -- blockers demand the split, clean evidence is
    directed to finalization.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)

    # State 1: no review evidence at all -> mandatory split (nothing clean to finalize).
    no_evidence = _run_round(home, adapter_root, target, adapter, "R5")
    assert no_evidence.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in no_evidence.stderr
    assert "the split is mandatory" in no_evidence.stderr

    # State 2: clean bound evidence -> still refused, but directed to finalize what exists.
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0
    clean = _run_round(home, adapter_root, target, adapter, "R5")
    assert clean.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in clean.stderr
    assert "finalize the existing review evidence" in clean.stderr
    assert "the split is mandatory" not in clean.stderr

    # State 3: blocked evidence -> mandatory split.
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(1)).returncode == 0
    blocked = _run_round(home, adapter_root, target, adapter, "R5")
    assert blocked.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in blocked.stderr
    assert "the split is mandatory" in blocked.stderr


def test_hard_cap_remedy_never_names_an_impossible_finalization(tmp_path):
    """Stale-clean evidence past the hard cap must be sent to the split, not to finalization.

    The manifest's blocker counts are clean, but the plan moved after it was bound, so
    plan-finalization-precheck refuses that evidence as stale. Choosing the remedy on blocker
    counts ALONE would print "finalize the existing review evidence" for a state where finalization
    provably cannot succeed -- and the hard cap forbids another round. That is a dead end, which is
    exactly what this ladder exists to remove. The remedy must be chosen on the same predicate
    finalization is judged by: clean AND bound to the CURRENT plan.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *CLEAN).returncode == 0

    # The fixes land, so the clean manifest is now bound to a plan that no longer exists.
    _mutate_plan(target, "4. Land a change the clean evidence never saw.\n")

    stale = _run_round(home, adapter_root, target, adapter, "R5")
    assert stale.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in stale.stderr
    # The remedy it USED to name is provably impossible for this state.
    precheck = _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )
    assert precheck.returncode != 0
    assert "stale" in precheck.stderr
    # So the only real way forward is the split.
    assert "the split is mandatory" in stale.stderr
    assert "finalize the existing review evidence" not in stale.stderr
    assert "do not ask the operator" in stale.stderr


def _stale_clean_bound_evidence(tmp_path):
    """R1 finalizes CLEAN evidence, then the plan moves: the bound manifest is clean but STALE.

    plan-finalization-precheck rejects a stale manifest, so this evidence CANNOT be finalized --
    and past the hard cap no further round may be launched. Any writer that picks the past-cap
    remedy from the SUBMITTED round's blocker counts (0/0 here) instead of from the BOUND manifest
    prints "finalize the existing review evidence" and sends the operator into a dead end.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *CLEAN)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    _mutate_plan(target, "4. Land a change the clean evidence never saw.\n")
    return home, adapter_root, target, adapter, _stdout_path(r1.stdout, "plan_review_run_log")


def _assert_split_remedy(result) -> None:
    assert result.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in result.stderr
    assert "the split is mandatory" in result.stderr
    assert "smaller source-of-truth plans" in result.stderr
    assert "finalize the existing review evidence" not in result.stderr
    assert "do not ask the operator" in result.stderr


def test_finalize_past_cap_remedy_is_chosen_by_the_bound_evidence(tmp_path):
    """finalize-plan-review is a manifest writer, so it must pick the remedy the same way.

    run-plan-review already chooses the past-cap remedy with
    plan_review_bound_evidence_is_unfinalizable. Choosing it here from the round being SUBMITTED
    (clean counts) instead reopens the same dead end through a second door.
    """
    home, adapter_root, target, adapter, log_path = _stale_clean_bound_evidence(tmp_path)

    finalize = _run_cli(
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
        "R5",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--exception-note",
        NOTE,
        home=home,
        adapter_root=adapter_root,
    )

    _assert_split_remedy(finalize)


def test_record_past_cap_remedy_is_chosen_by_the_bound_evidence(tmp_path):
    """record-plan-review writes the same manifest schema, so it is the third door on the ladder."""
    home, adapter_root, target, adapter, _r1_log = _stale_clean_bound_evidence(tmp_path)

    # A fresh run bound to the CURRENT plan, so record-plan-review's own log/mtime gates pass and
    # the past-cap refusal is the only thing under test. The trusted manifest stays the stale-clean
    # R1 one: this run is never finalized.
    fresh = _run_round(home, adapter_root, target, adapter, "R2")
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    log_path = _stdout_path(fresh.stdout, "plan_review_run_log")
    review_command = next(
        line.split(": ", 1)[1]
        for line in fresh.stdout.splitlines()
        if line.startswith("plan_review_run_command: ")
    )

    record = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--review-command",
        review_command,
        "--reviewer",
        "codex",
        "--model",
        "codex-test",
        "--round",
        "R5",
        "--wrapper-exit-code",
        "0",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--exception-note",
        NOTE,
        home=home,
        adapter_root=adapter_root,
    )

    _assert_split_remedy(record)


def test_exception_note_required_and_recorded_past_target(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    _mutate_plan(target, "4. Land the R1 fix.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3")
    assert r3.returncode == 0, r3.stdout + r3.stderr
    log_path = _stdout_path(r3.stdout, "plan_review_run_log")

    finalize_args = [
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
        "R3",
        "--model",
        "codex-test",
        *CLEAN,
    ]
    without_note = _run_cli(*finalize_args, home=home, adapter_root=adapter_root)
    assert without_note.returncode == 1
    assert "--exception-note" in without_note.stderr

    with_note = _run_cli(*finalize_args, "--exception-note", NOTE, home=home, adapter_root=adapter_root)
    assert with_note.returncode == 0, with_note.stdout + with_note.stderr

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["exception_note"] == NOTE
    assert manifest["round"] == "R3"

    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr


def test_two_round_happy_path_unchanged(tmp_path):
    """A plan converging within the target rounds behaves exactly as it did before the ladder."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)

    r1 = _run_round(home, adapter_root, target, adapter, "R1", *CLEAN)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert (
        "plan_review_round_status: round 1 of 2; verdict=clean; unresolved_critical=0; "
        "unresolved_p1=0; next_action=run plan-finalization-precheck and finalize only if it passes"
    ) in r1.stdout
    assert "plan_review_exception" not in r1.stdout
    assert "exception_note" not in r1.stdout

    r2 = _run_round(home, adapter_root, target, adapter, "R2", *CLEAN)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "plan_review_round_status: round 2 of 2; verdict=clean;" in r2.stdout
    assert "plan_review_exception" not in r2.stdout

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert "exception_note" not in manifest

    # And the printed finalize guidance for a within-target round never mentions the flag.
    plain = _run_round(home, adapter_root, target, adapter, "R2")
    assert "--exception-note" not in plain.stdout

    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr


def test_printed_next_action_includes_exception_note_past_target(tmp_path):
    """Agents that follow the tool's own printed guidance must not hit the missing-note error."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    _mutate_plan(target, "4. Land the R1 fix.\n")

    r3 = _run_round(home, adapter_root, target, adapter, "R3")

    assert r3.returncode == 0, r3.stdout + r3.stderr
    next_action = next(line for line in r3.stdout.splitlines() if line.startswith("plan_review_next_action: "))
    assert "finalize-plan-review" in next_action
    assert "--exception-note" in next_action


def test_all_manifest_writers_require_exception_past_target(tmp_path):
    """The ladder must not be bypassable through a secondary manifest writer."""
    # Guard: exactly two code paths write the plan-review manifest schema. A new writer must
    # come with its own past-target enforcement, so this count is deliberately pinned.
    assert CLI_SOURCE.count('"schema": PLAN_REVIEW_SCHEMA,') == 2

    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    _mutate_plan(target, "4. Land the R1 fix.\n")
    r3 = _run_round(home, adapter_root, target, adapter, "R3")
    assert r3.returncode == 0, r3.stdout + r3.stderr
    log_path = _stdout_path(r3.stdout, "plan_review_run_log")
    review_command = next(
        line.split(": ", 1)[1] for line in r3.stdout.splitlines() if line.startswith("plan_review_run_command: ")
    )

    # Writer 1: run-plan-review's inline finalization interface.
    inline = _run_round(home, adapter_root, target, adapter, "R3", *CLEAN)
    assert inline.returncode == 1
    assert "--exception-note" in inline.stderr

    # Writer 2: finalize-plan-review.
    finalize = _run_cli(
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
        "R3",
        "--model",
        "codex-test",
        *CLEAN,
        home=home,
        adapter_root=adapter_root,
    )
    assert finalize.returncode == 1
    assert "--exception-note" in finalize.stderr

    # Writer 3: record-plan-review (diagnostic import, but still a schema writer).
    record_args = [
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--review-command",
        review_command,
        "--reviewer",
        "codex",
        "--model",
        "codex-test",
        "--round",
        "R3",
        "--wrapper-exit-code",
        "0",
        *CLEAN,
    ]
    record_without_note = _run_cli(*record_args, home=home, adapter_root=adapter_root)
    assert record_without_note.returncode == 1
    assert "--exception-note" in record_without_note.stderr

    record_with_note = _run_cli(*record_args, "--exception-note", NOTE, home=home, adapter_root=adapter_root)
    assert record_with_note.returncode == 0, record_with_note.stdout + record_with_note.stderr
    imported = json.loads(_stdout_path(record_with_note.stdout, "plan_review_manifest").read_text(encoding="utf-8"))
    assert imported["exception_note"] == NOTE


# Retired plan-review policy. These strings shipped inside agent-facing guidance and went stale when
# the ladder landed: no test pinned them, so the policy sweep missed two live mirrors and agents
# would have read the retired cap as current. The sweep is only durable if a test enforces it.
RETIRED_POLICY_PATTERNS = (
    "two-round cap is reached",
    "when the two-round cap",
    "R3 only for confirmed structural",
    "only for confirmed structural Critical",
    "cap is 2 rounds",
    "PLAN_REVIEW_MAX_ROUNDS",
    # The hard-cap remedy is chosen by whether the bound evidence can actually be FINALIZED, not by
    # blocker counts alone: clean-but-stale evidence takes the split, because the precheck rejects a
    # stale manifest. A mirror that says "otherwise/without them, finalize" reasserts the retired
    # over-broad rule and sends the operator to a finalization that provably fails.
    "otherwise finalize the existing evidence",
    "without them, finalize the existing evidence",
    # The same over-broad rule in its OTHER shipped phrasings. The first sweep pinned only the two
    # wordings it happened to fix, so the process authority (methodology/canonical-rules.md), the
    # risk-tier and capability mirrors, and the CLI's own adapter guidance kept asserting that the
    # split is mandatory UNCONDITIONALLY past the cap -- which the shipped CLI contradicts: when
    # the bound evidence is clean AND current the remedy is to finalize it, not to split. A
    # process authority that contradicts the tool it governs is worse than no authority: nothing
    # reads it at runtime, so nothing catches the drift, and agents follow the text.
    "refusal is unconditional and the split is mandatory",
    "the hard cap is absolute and the split is mandatory",
    "the existing evidence is finalized as-is",
    "past round 4 the split",
    "the split past round 4 as mandatory",
    "a mandatory split past the hard cap",
)

# .md mirrors plus the CLI itself: bin/tautline renders plan-review policy into every generated
# adapter, so its guidance strings are an agent-facing policy surface too. Leaving them unpinned is
# how a "policy sweep" ships a contradiction.
POLICY_SURFACES = (
    REPO_ROOT / "plugins",
    REPO_ROOT / "docs" / "reference",
    REPO_ROOT / "methodology",
)
POLICY_SURFACE_FILES = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py",)


def _policy_surface_files() -> list[Path]:
    files = [path for root in POLICY_SURFACES for path in sorted(root.rglob("*.md"))]
    files.extend(POLICY_SURFACE_FILES)
    return files


def test_no_shipped_policy_surface_asserts_the_retired_plan_review_cap():
    """Every agent-facing mirror of the plan-review cap must describe the ladder, not the old cap."""
    offenders = []
    for path in _policy_surface_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in RETIRED_POLICY_PATTERNS:
                if pattern in line:
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {pattern}")

    assert offenders == [], "retired plan-review policy still shipped in:\n" + "\n".join(offenders)


def test_the_process_authority_states_the_shipped_hard_cap_remedy():
    """methodology/canonical-rules.md is the repo's process authority: it must match the CLI.

    Nothing reads this text at runtime, which is exactly why the drift is dangerous -- no gate
    catches it, and agents follow it. Past the cap the refusal is unconditional and the remedy is
    chosen by the bound evidence, so the authority has to say both.
    """
    for path in (
        REPO_ROOT / "methodology" / "canonical-rules.md",
        REPO_ROOT / "methodology" / "policy" / "13-planning.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "past round 4 refusal is unconditional" in text, path
        assert "the split is mandatory unless the bound evidence is clean and current" in text, path


def test_exception_reason_surfaces_in_the_committed_evidence_block(tmp_path):
    """A RECORDED exception must be visible where reviewers read: the plan's evidence block.

    The reason is what makes a past-target round legitimate. If it lives only in the JSON manifest,
    a reviewer sees round R3 with no justification on the PR-visible surface.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    _mutate_plan(target, "4. Land the R1 fix.\n")

    r3 = _run_round(home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *CLEAN)
    assert r3.returncode == 0, r3.stdout + r3.stderr

    plan_text = (target / PLAN_REL).read_text(encoding="utf-8")
    assert f"- Exception: `{NOTE}`" in plan_text
    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["exception_note"] == NOTE

    # The regenerated block must still match the committed one, or finalization would be unbindable.
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr


def test_two_round_evidence_block_has_no_exception_line(tmp_path):
    """AC3: a plan that converges within the target renders exactly what it rendered before."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *CLEAN).returncode == 0

    plan_text = (target / PLAN_REL).read_text(encoding="utf-8")
    assert "- Exception:" not in plan_text
    precheck = _precheck(home, adapter_root, target, adapter)
    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
