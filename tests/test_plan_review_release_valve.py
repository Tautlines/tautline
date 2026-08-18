"""WS1: the plan-review release valve (spec decision D2).

The cap counted reviewer invocations per plan FILE and prescribed a successor plan as the remedy.
A successor is a new file path and a new file path is a fresh budget, so the gate that looked like
a ceiling was in fact the instruction for refilling it: the measured chain in this lane ran v1 ->
v14, sixteen recorded rounds under fourteen fresh budgets, for five net plan lines.

So at the cap `finalize-plan-review` no longer refuses. It finalizes with the derived verdict
`capped-with-open-findings`, records every unresolved Critical/P1 at honest severity as
`status: carried`, and those become BINDING implementation-review focus items. Every test here
fails without that change.
"""

import json
import re
import shutil
from pathlib import Path

from test_plan_review_cli import (
    PLAN_REL,
    _manifest_path,
    _prepare_target,
    _run_cli,
    _stdout_path,
    _write_plan,
)
from test_plan_review_convergence import CLEAN, NOTE, _blocked, _mutate_plan, _run_round


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")


def _spend_the_budget(tmp_path):
    """Burn the four-round budget and finalize R4 still carrying one Critical.

    Returns the lane plus the R4 result, which is the moment the valve either opens or does not.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    r3 = _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    )
    assert r3.returncode == 0, r3.stdout + r3.stderr
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )
    return home, adapter_root, target, adapter, r4


def _spend_the_budget_leaving_a_round_unclassified(tmp_path):
    """The same four spent invocations, except R2 is launched and never bound.

    A charged reviewer-invocation record with no classification: the lane the disclosure must
    still refuse to certify, kept beside the lane it now certifies.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    # No verdict arguments: the run succeeds and is charged, and nothing binds it.
    assert _run_round(home, adapter_root, target, adapter, "R2").returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )
    return home, adapter_root, target, adapter, r4


def _disclosure_line(stdout: str) -> str:
    """The one `plan_review_capped_disclosure:` line.

    Asserted against the LINE rather than the whole finalize output: a plan path or a round label
    appears in half a dozen other printed lines, so `in stdout` can pass on text the disclosure
    never said.
    """
    lines = [
        line
        for line in stdout.splitlines()
        if line.startswith("plan_review_capped_disclosure:")
    ]
    assert len(lines) == 1, stdout
    return lines[0]


def _disclosed_basis(line: str) -> str:
    return line.split("carried_findings_basis=", 1)[1].split(" ", 1)[0]


def _disclosed_totals(line: str) -> tuple[int, int, int]:
    """`(unverified, counted, members)` as the line actually printed them.

    Parsed rather than substring-matched so a closing assertion cannot be satisfied by a
    disclosure that counted nothing: the pre-WS5 line named no totals at all, and every assertion
    that only pinned the `caller-asserted` token passed against it unchanged.
    """
    match = re.search(
        r"(\d+) of (\d+) counted round\(s\) across (\d+) lineage member\(s\)", line
    )
    assert match, f"the disclosure named no counted totals: {line}"
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


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


def test_finalize_at_the_cap_succeeds_with_capped_verdict(tmp_path):
    """T1.1. Exit 0, verdict `capped-with-open-findings`, blockers recorded as carried."""
    _home, _adapter_root, target, _adapter, r4 = _spend_the_budget(tmp_path)

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in r4.stdout
    assert "asserted_verdict=blocked" in r4.stdout
    assert "carried_binding_findings=1" in r4.stdout

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["verdict"] == "capped-with-open-findings"
    # The reviewer's own word survives beside the derived verdict, or the record could never be
    # reconciled against the log that produced it.
    assert manifest["asserted_verdict"] == "blocked"
    # Honest severity: carrying changes the medium a finding is settled in, never its severity.
    assert manifest["unresolved_critical_count"] == 1
    carried = [item for item in manifest["classified_findings"] if item.get("status") == "carried"]
    assert len(carried) == 1
    assert carried[0]["severity"] == "Critical"
    assert carried[0]["binding"] is True
    assert carried[0]["carried_to"] == "implementation-review-focus"
    assert carried[0]["carried_at_round"] == 4


def test_the_cap_refusal_no_longer_fires_and_names_no_successor_plan(tmp_path):
    """T1.1. The pre-change refusal is gone, and nothing on this path prescribes another plan."""
    _home, _adapter_root, _target, _adapter, r4 = _spend_the_budget(tmp_path)

    assert r4.returncode == 0, r4.stdout + r4.stderr
    combined = r4.stdout + r4.stderr
    assert "plan_review_convergence_error" not in combined
    assert "reached the hard cap" not in combined
    assert "the split is mandatory" not in combined
    assert "decompose this plan into smaller source-of-truth plans" not in combined
    # The exit points at code.
    assert "plan-finalization-precheck and start implementation" in r4.stdout


def test_no_state_of_the_cap_gate_refuses_every_exit(tmp_path):
    """T1.1, the safety property. Finalize succeeds AND the precheck downstream accepts it.

    Accepting at finalize and refusing at the precheck would move the 2026-07-14 deadlock one gate
    downstream rather than removing it, so both halves are asserted in one test.
    """
    home, adapter_root, target, adapter, r4 = _spend_the_budget(tmp_path)
    assert r4.returncode == 0, r4.stdout + r4.stderr

    precheck = _precheck(home, adapter_root, target, adapter)

    assert precheck.returncode == 0, precheck.stdout + precheck.stderr
    assert "plan_finalization_precheck: pass" in precheck.stdout
    # The bill is printed where the lane is already looking.
    assert "implementation_review_focus:" in precheck.stdout
    assert "(BINDING; re-test against the code)" in precheck.stdout


def test_a_fifth_round_is_still_refused_and_is_sent_to_build_not_to_a_split(tmp_path):
    """The budget stays absolute. What changed is the remedy the refusal names."""
    home, adapter_root, target, adapter, r4 = _spend_the_budget(tmp_path)
    assert r4.returncode == 0, r4.stdout + r4.stderr

    r5 = _run_round(home, adapter_root, target, adapter, "R5", "--exception-note", NOTE)

    assert r5.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in r5.stderr
    assert "the exit is BUILD" in r5.stderr
    assert "the split is mandatory" not in r5.stderr
    assert "Do not split this plan" in r5.stderr
    # A refusal is a directive, never an operator question.
    assert "do not ask the operator to choose a path" in r5.stderr


def test_the_capped_event_is_recorded_as_warn_not_block(cli):
    """A `block` severity beside a successful exit would say the lane is stuck as it is released.

    Not `ok` either: the findings are real, open, and binding on implementation review.
    """
    capped = cli.plan_review_finalize_event_severity(
        capped=True, convergence_errors=False, blockers=1, wrapper_exit_code=0
    )
    blocked = cli.plan_review_finalize_event_severity(
        capped=False, convergence_errors=True, blockers=1, wrapper_exit_code=0
    )
    clean = cli.plan_review_finalize_event_severity(
        capped=False, convergence_errors=False, blockers=0, wrapper_exit_code=0
    )

    assert (capped, blocked, clean) == ("warn", "block", "ok")
    assert capped in cli.EVENT_SEVERITIES


def test_a_capped_finalize_whose_wrapper_failed_is_not_reported_as_released(cli):
    """Codex R1 P2. A nonzero wrapper exit means the command fails and the precheck rejects the
    manifest, so the lane is NOT released -- and `warn` would describe a release that never was."""
    assert (
        cli.plan_review_finalize_event_severity(
            capped=True, convergence_errors=False, blockers=1, wrapper_exit_code=1
        )
        == "block"
    )


def test_a_label_cannot_buy_the_release_valve(tmp_path):
    """Codex R1 P1. The valve opens on SPENT invocations, never on the `--round` label.

    `plan_review_effective_round` is max(declared, observed+1), so a plan whose FIRST round is
    labelled R4 reads as round 4. If the valve keyed on that, one Codex invocation would buy the
    capped release and R1-R3 would never happen -- the same label-trust defect the round cap
    itself was rebuilt to close, reintroduced through a new door.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)

    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    # The round is legal -- rounds 3-4 self-authorize with a note -- but it is the FIRST
    # invocation, so the budget is not spent and the valve stays shut.
    assert r4.returncode == 2, r4.stdout + r4.stderr
    assert "plan_review_capped:" not in r4.stdout
    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["verdict"] == "blocked"


def test_a_capped_verdict_cannot_be_hand_written_into_the_manifest(tmp_path):
    """Codex confirming-round P1. The precheck's capped branch re-derives the spend from disk.

    Every other check on that path reads a field the manifest itself owns -- verdict,
    recorded_by, wrapper_exit_code, the carried stamps -- so a lane holding a trusted `blocked`
    manifest could edit that one file into `capped-with-open-findings`, stamp its blockers
    carried/binding, and walk the gate having spent ONE reviewer invocation instead of four.
    Keeping the verdict out of every `--verdict` choice list stops the verb from asserting it and
    does nothing about the file. The valve's claim is "the budget is spent", so the budget is what
    must be proved, against evidence the manifest does not own.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1)).returncode == 0

    # Forge the capped record on top of a legitimately-recorded single round.
    manifest_path = _manifest_path(target)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verdict"] = "capped-with-open-findings"
    for finding in manifest["classified_findings"]:
        if str(finding.get("severity", "")).lower() in ("critical", "p1"):
            finding["status"] = "carried"
            finding["binding"] = True
            finding["carried_to"] = "implementation-review-focus"
            finding["carried_at_round"] = 4
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = _precheck(home, adapter_root, target, adapter)

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "only 1 successful reviewer invocation(s) are recorded on disk" in combined, combined
    assert "cannot be written into the manifest by hand" in combined, combined


def test_the_valve_opens_only_after_four_recorded_invocations(tmp_path):
    """The positive half of the same rule: four spent invocations, then the valve opens."""
    _home, _adapter_root, target, _adapter, r4 = _spend_the_budget(tmp_path)

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "spent_invocations=4" in r4.stdout
    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["observed_successful_runs"] == 3


def test_duplicate_finding_ids_get_distinct_focus_keys(cli):
    """Codex R1 P2. `id` is not unique in the contract, and the finalizer keys obligations in a
    SET -- so two Criticals sharing an id would collapse into one, and one disposition would
    discharge both."""
    carried = cli.plan_review_carry_blockers(
        [
            {"id": "R1", "severity": "Critical", "status": "open", "summary": "first"},
            {"id": "R1", "severity": "Critical", "status": "open", "summary": "second"},
        ],
        4,
    )

    focus_ids = [item["focus_id"] for item in carried]
    assert len(set(focus_ids)) == 2, focus_ids


def test_a_generated_focus_id_cannot_collide_with_a_supplied_one(cli):
    """The disambiguator must itself be checked.

    The suffixed form was trusted without re-testing it, so it could collide with an id a finding
    already SUPPLIED: `R1#3`, `R1`, `R1` produced `R1#3`, `R1`, and then `R1#3` again. Downstream
    keys obligations by focus key in a SET, so the pair collapses into one obligation and a single
    disposition discharges both -- the binding-ness of carried findings failing quietly, which is
    the one property the release valve rests on.
    """
    carried = cli.plan_review_carry_blockers(
        [
            {"id": "R1#3", "severity": "Critical", "status": "open", "summary": "first"},
            {"id": "R1", "severity": "Critical", "status": "open", "summary": "second"},
            {"id": "R1", "severity": "Critical", "status": "open", "summary": "third"},
        ],
        4,
    )

    focus_ids = [item["focus_id"] for item in carried]
    assert len(focus_ids) == 3, focus_ids
    assert len(set(focus_ids)) == 3, focus_ids


def test_a_capped_verdict_reaches_instrumentation_instead_of_being_dropped(cli):
    """Codex R1 P2. The reducer drops unrecognised verdicts, so an unmapped capped outcome would
    vanish from telemetry entirely -- the reporting half of the defect this item exists to fix.

    Mapped to the BLOCKED code and NOT to clean: the finalize exits 0, but the record it leaves
    carries unresolved Critical/P1, and counting that as clean would say plan review converged
    when what happened is that it ran out of budget. No new enum value, so no vocabulary gate.
    """
    plan_only = cli.INSTRUMENTATION_FINALIZE_BLOCKED_VERDICTS_BY_PRODUCER["plan_review_finalized"]
    assert cli.PLAN_REVIEW_CAPPED_VERDICT in plan_only
    assert cli.PLAN_REVIEW_CAPPED_VERDICT not in cli.INSTRUMENTATION_FINALIZE_CLEAN_VERDICTS
    assert "blocked" in plan_only
    # ...and SCOPED to plan review (Codex round 5 P2). The reducer applies one verdict set to both
    # producers, so a shared set made a malformed `implementation_review_finalized` carrying this
    # plan-only verdict count as an implementation-review block instead of being dropped. The
    # contract is that an unrecognised verdict is dropped and never guessed; recognising it for
    # the wrong producer is a guess.
    assert cli.PLAN_REVIEW_CAPPED_VERDICT not in cli.INSTRUMENTATION_FINALIZE_BLOCKED_VERDICTS
    assert "implementation_review_finalized" not in (
        cli.INSTRUMENTATION_FINALIZE_BLOCKED_VERDICTS_BY_PRODUCER
    )


def test_capped_verdict_cannot_be_asserted_by_a_lane(cli):
    """Derived, never attested. A verdict a lane could type would be a bypass with a nice name."""
    assert cli.PLAN_REVIEW_CAPPED_VERDICT not in cli.PLAN_REVIEW_ALL_VERDICTS
    assert cli.PLAN_REVIEW_CAPPED_VERDICT not in cli.PLAN_REVIEW_ALLOWED_VERDICTS


def test_carried_is_not_a_resolved_status(cli):
    """`carried` must keep counting as unresolved, or the valve would be a silent downgrade."""
    assert cli.PLAN_REVIEW_CARRIED_STATUS not in cli.plan_review_resolved_statuses()
    critical, p1 = cli.finding_counts(
        [{"severity": "Critical", "status": "carried"}, {"severity": "P1", "status": "carried"}]
    )
    assert (critical, p1) == (1, 1)


def test_precheck_refuses_a_capped_manifest_whose_blockers_were_not_carried(tmp_path):
    """The valve is only safe because the record proves the findings became obligations."""
    home, adapter_root, target, adapter, r4 = _spend_the_budget(tmp_path)
    assert r4.returncode == 0, r4.stdout + r4.stderr
    manifest_path = _manifest_path(target)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for finding in manifest["classified_findings"]:
        if finding.get("status") == "carried":
            finding["binding"] = False
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    precheck = _precheck(home, adapter_root, target, adapter)

    assert precheck.returncode == 1
    assert 'must carry "binding": true' in precheck.stderr


def test_capped_manifest_errors_refuse_a_blocker_left_uncarried(cli):
    """Unit-level twin of the precheck refusal, keyed on the predicate rather than the plumbing."""
    errors = cli.plan_review_capped_manifest_errors(
        {"classified_findings": [{"id": "F1", "severity": "Critical", "status": "open"}]}
    )

    assert any('"status": "carried"' in error for error in errors)


def test_capped_verdict_with_no_open_blocker_is_refused(cli):
    """A capped finalize exists to carry open blockers; a record with none belongs at clean."""
    errors = cli.plan_review_capped_manifest_errors({"classified_findings": []})

    assert any("records no unresolved Critical/P1 finding" in error for error in errors)


def _carried(**overrides):
    """A minimally-valid carried blocker, so each test below perturbs exactly one field."""
    item = {
        "id": "F1",
        "focus_id": "F1",
        "severity": "Critical",
        "status": "carried",
        "binding": True,
    }
    item.update(overrides)
    return {"asserted_verdict": "blocked", "classified_findings": [item]}


def test_a_valid_capped_record_is_accepted(cli):
    """The floor for the three refusals below: without this, each could pass by refusing
    everything."""
    assert cli.plan_review_capped_manifest_errors(_carried()) == []


def test_a_carried_blocker_without_a_focus_identity_is_refused(cli):
    """Codex remediation-round P2. `plan_review_carried_focus_items` keys on `focus_id or id` and
    SKIPS an entry with neither, so an id-less carried blocker passed validation and then vanished
    from every downstream report -- recorded as binding and unreportable at once, which is worse
    than never carrying it, because the manifest testifies that it was carried."""
    errors = cli.plan_review_capped_manifest_errors(_carried(id=None, focus_id=""))

    assert any("non-empty" in error and "focus_id" in error for error in errors), errors


def test_a_capped_manifest_without_an_asserted_verdict_is_refused(cli):
    """Codex remediation-round P2. The pair of verdicts is the audit trail; half of it is not."""
    record = _carried()
    del record["asserted_verdict"]

    errors = cli.plan_review_capped_manifest_errors(record)

    assert any("requires" in error and "asserted_verdict" in error for error in errors), errors


def test_a_capped_manifest_asserting_an_arbitrary_value_is_refused(cli):
    """Codex round 4 P2. The validator enumerates what it PERMITS, not what it forbids.

    Both clean verdicts are refused before the manifest is written, so `blocked` is the only value
    a legitimate capped finalize can have asserted. Rejecting only the clean values left every
    other string passing, so a hand-edited `"banana"` satisfied the guard while destroying exactly
    the reconcilability the field exists to provide.
    """
    errors = cli.plan_review_capped_manifest_errors(_carried() | {"asserted_verdict": "banana"})

    assert any("cannot be reconciled against the log" in error for error in errors), errors


def test_a_capped_manifest_asserting_clean_is_refused(cli):
    """Codex remediation-round P2. A capped finalize is derived only from a round that asserted
    unresolved Critical/P1, so `clean` beside carried blockers is provably false -- the record
    would claim the final review found nothing while carrying binding Criticals."""
    for clean in sorted(cli.INSTRUMENTATION_FINALIZE_CLEAN_VERDICTS):
        errors = cli.plan_review_capped_manifest_errors(_carried() | {"asserted_verdict": clean})

        # Same refusal as any other non-`blocked` value: the validator now permits exactly one
        # spelling rather than forbidding a list, so clean is caught by the allowlist.
        assert any("cannot be reconciled against the log" in error for error in errors), (
            clean,
            errors,
        )


def test_the_valve_stays_shut_when_the_spent_rounds_were_never_classified(tmp_path):
    """Codex remediation-round P1. The valve counted successful INVOCATIONS and said nothing about
    whether any of them was classified.

    Launch R1-R3 under distinct labels without finalizing any of them and all three metas count,
    so finalizing R4 derived the capped verdict ahead of the `not existing_manifest_present`
    convergence check -- the one that exists to refuse a late round which cannot prove what the
    earlier ones found. Every Critical those rounds raised would be gone: not carried, not
    deferred, absent, while the record claimed the budget was honestly spent.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    # Three launches, none finalized -- so three successful run metas and NO manifest.
    # No verdict arguments -- that is what makes the run succeed WITHOUT finalizing it.
    for label in ("R1", "R2", "R3"):
        _run_round(home, adapter_root, target, adapter, label, "--exception-note", NOTE)
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert "plan_review_capped:" not in r4.stdout, r4.stdout + r4.stderr
    assert r4.returncode != 0, r4.stdout + r4.stderr
    assert "no previous manifest to prove convergence" in (r4.stdout + r4.stderr)


def test_a_clean_assertion_at_the_cap_is_refused_before_the_manifest_is_written(tmp_path):
    """Codex round 3 P2, and a regression from this branch's own previous fix.

    `--verdict clean` with nonzero counts used to reach the derivation, be recorded as
    `asserted_verdict`, and return SUCCESS -- and then plan-finalization-precheck rejected the
    manifest, because the guard added the round before refuses a capped record asserting clean. A
    successful finalize whose evidence the very next required gate calls unusable is the deadlock
    this release exists to remove, reintroduced by the fix for it. Refused before the write, where
    the message can still name the contradiction the lane actually typed.
    """
    # The same ladder _spend_the_budget walks, except the FOURTH round -- the one that reaches the
    # valve -- asserts `clean` while still submitting an open Critical.
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")

    clean_at_cap = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE,
        "--verdict", "clean",
        "--unresolved-critical-count", "1",
        "--unresolved-p1-count", "0",
        "--classified-findings-json",
        json.dumps([{"severity": "Critical", "summary": "still open"}]),
    )

    combined = clean_at_cap.stdout + clean_at_cap.stderr
    assert clean_at_cap.returncode != 0, combined
    assert "the asserted verdict must be blocked" in combined, combined


def test_carry_preserves_severity_and_resolved_findings(cli):
    """No downgrade, and no obligation invented for a finding the round already resolved."""
    carried = cli.plan_review_carry_blockers(
        [
            {"id": "F1", "severity": "Critical", "status": "open"},
            {"id": "F2", "severity": "P1", "status": "fixed"},
            {"id": "F3", "severity": "P2", "status": "open"},
            {"severity": "Critical", "status": "open"},
        ],
        4,
    )

    assert carried[0]["severity"] == "Critical"
    assert carried[0]["status"] == "carried"
    assert carried[0]["focus_id"] == "F1"
    assert carried[1]["status"] == "fixed"
    assert carried[2]["status"] == "open"
    # An id-less finding still has to be dispositionable at a shell.
    assert carried[3]["focus_id"] == "carried-2"


def test_the_finalize_event_severity_call_site_uses_the_helper():
    """Grep guard pinning the CALL SITE, not just the helper.

    `test_the_capped_event_is_recorded_as_warn_not_block` and
    `test_a_capped_finalize_whose_wrapper_failed_is_not_reported_as_released` exercise
    `plan_review_finalize_event_severity` in isolation. Both stay green if the call site is
    reverted to the previous inline ternary -- and that revert makes the event record `block`
    beside a successful capped exit, which is exactly what the helper's docstring says must not
    happen. Behavioural coverage is not available here: the event sink resolves against a
    lane-relative state dir that these subprocess-driven tests never write to (verified -- no
    events.jsonl is produced under the test HOME or target), so there is nothing to assert on.
    A source pin is the honest second-best, and this file already uses one below.
    """
    marker = "severity = plan_review_finalize_event_severity("
    assert marker in CLI_SOURCE, "the finalize event severity no longer routes through the helper"
    # Split on the dedented closing paren, not the first `)`: the first one belongs to
    # `bool(convergence_errors)` inside the call, which would truncate the window before the
    # later kwargs and make every assertion below vacuous.
    call = CLI_SOURCE.split(marker, 1)[1].split("\n    )", 1)[0]
    for kwarg in ("capped=", "convergence_errors=", "blockers=", "wrapper_exit_code="):
        assert kwarg in call, f"call site dropped {kwarg!r}, so the helper cannot decide correctly"
    # The retired inline form must not come back alongside it.
    assert 'severity = "ok" if not convergence_errors' not in CLI_SOURCE


def test_the_cap_message_source_no_longer_prescribes_a_successor_plan():
    """Grep guard. The remedy that refilled the budget must not creep back into this branch."""
    marker = "capped_with_open_findings = ("
    assert marker in CLI_SOURCE
    branch = CLI_SOURCE.split(marker, 1)[1].split("elif current_blockers > 0:", 1)[0]
    assert "smaller source-of-truth plans" not in branch
    assert "split is mandatory" not in branch


def test_the_capped_record_discloses_its_carried_findings_basis(tmp_path):
    """The capped record says what its carried list RESTS ON -- CONTRACT CHANGED at item 108 WS5.

    Shipped (item 86 WS1) this test pinned `caller-asserted` for the `_spend_the_budget` lane,
    because nothing on that tip could prove the rounds the valve counted had ever been classified.
    WS1's durable per-round record, WS2's record-backed spend and WS3's authoritative resolver
    removed exactly that limit, and WS5 spends them: this lane finalizes all four of its counted
    rounds, so each leaves an observed, persisted `round-classification` record and the honest
    token is `round-record-verified`. Continuing to pin the old constant here would pin the
    ABSENCE of the proof the item shipped -- the assertion encodes pre-WS5 behavior this change
    deliberately inverts, so the assertion moves with it. This is the lane owner changing its own
    published contract, disclosed here and in the commit body, not a test relaxed to go green: the
    replacement is STRICTER (it pins a proof) and the old value stays pinned below.

    The honest DOWNGRADE is the other half of the same contract, and it is asserted in this same
    test rather than left to a sibling that could disappear without anyone noticing: a lane whose
    counted rounds are not all classified must still disclose `caller-asserted`, and must NAME
    what it could not prove. Only the assignment of the two tokens to lanes moved.
    """
    _home, _adapter_root, target, _adapter, r4 = _spend_the_budget(tmp_path)

    assert r4.returncode == 0, r4.stdout + r4.stderr
    verified = _disclosure_line(r4.stdout)
    assert _disclosed_basis(verified) == "round-record-verified", verified
    assert "all 4 counted round(s) across 1 lineage member(s)" in verified
    assert "carry a round-classification record" in verified
    assert "NOT verified" not in verified

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["carried_findings_basis"] == "round-record-verified"

    # ...and the caller-asserted path is still a live contract, on a lane that cannot prove one of
    # the four rounds it counts.
    _home2, _root2, target2, _adapter2, unproven_r4 = (
        _spend_the_budget_leaving_a_round_unclassified(tmp_path / "unproven")
    )
    assert unproven_r4.returncode == 0, unproven_r4.stdout + unproven_r4.stderr
    unproven = _disclosure_line(unproven_r4.stdout)
    assert (_disclosed_basis(unproven), _disclosed_totals(unproven)) == (
        "caller-asserted",
        (1, 4, 1),
    ), unproven
    assert " round R2 (" in unproven and "is counted and never classified" in unproven

    unproven_manifest = json.loads(_manifest_path(target2).read_text(encoding="utf-8"))
    assert unproven_manifest["carried_findings_basis"] == "caller-asserted"


def _rounds_root(target: Path) -> Path:
    return target / PLAN_REL.parent / ".plan-reviews" / "rounds"


def _declare_work_item(path: Path, reference: str) -> None:
    """Give a plan the declared work-item FIELD the lineage resolver binds siblings on."""
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("# Test Plan\n", f"# Test Plan\n\nWork item: {reference}\n", 1),
                    encoding="utf-8")


def test_carried_findings_basis_upgrades_when_every_counted_round_is_classified(tmp_path):
    """T5.1, decision DF. The valve shipped disclosing that it could not prove its carried list.

    With WS1's durable record, WS2's record-backed spend and WS3's authoritative resolver in
    place it can: every round the resolver counts here was finalized, so every one of them left a
    `round-classification` record and the basis is no longer the caller's word for it. The bound
    round counts through its own classification record, which is appended BEFORE the basis is
    derived -- the manifest reports what is on disk rather than what is about to be written.
    """
    _home, _adapter_root, target, _adapter, r4 = _spend_the_budget(tmp_path)

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert (
        "plan_review_capped_disclosure: carried_findings_basis=round-record-verified"
        in r4.stdout
    ), r4.stdout
    # The line says WHAT was verified, not merely that something was.
    assert "all 4 counted round(s) across 1 lineage member(s)" in r4.stdout
    assert "carry a round-classification record" in r4.stdout
    assert "NOT verified" not in r4.stdout

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["carried_findings_basis"] == "round-record-verified"


def test_an_unclassified_counted_round_keeps_the_basis_caller_asserted_and_names_the_round(
    tmp_path,
):
    """T5.1. The hole the valve's own comment describes: finalize R1, leave R2/R3 unclassified.

    R4 still reaches the valve -- `existing_manifest_present` proves SOME round was classified,
    never every one -- and its budget counts four invocations while two of them were never
    classified at all. The basis stays caller-asserted, and the disclosure NAMES the two rounds:
    a lane can bind `round R2`, and can do nothing whatever with "completeness is not verified".
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    # Two launches with NO verdict arguments: charged invocations that are never bound, so each
    # leaves a reviewer-invocation record and no classification.
    assert _run_round(home, adapter_root, target, adapter, "R2").returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in r4.stdout
    line = _disclosure_line(r4.stdout)
    assert "NOT verified" in line
    # Named, per round, so the gap is actionable.
    assert " round R2 (" in line and " round R3 (" in line
    assert line.count("is counted and never classified") == 2, line
    assert "tautline record-plan-review" in line
    # R1 and R4 were classified, so they are NOT named as gaps.
    assert " round R1 (" not in line

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    # DISCRIMINATING, not decorative (WS5 remediation). `manifest[...] == "caller-asserted"` on its
    # own passed identically against the pre-WS5 source, which wrote that constant into every
    # capped manifest unconditionally -- so this test's closing assertion could not tell the
    # derivation from its absence. It now pins the manifest's token to the token AND the counted
    # totals of the line the same derivation printed: two of this lane's four counted rounds, in
    # its one lineage member, unproven.
    assert (
        manifest["carried_findings_basis"],
        _disclosed_basis(line),
        _disclosed_totals(line),
    ) == ("caller-asserted", "caller-asserted", (2, 4, 1))


def test_prerecord_history_never_upgrades_the_basis(tmp_path):
    """T5.1. Rounds spent before the durable record existed can never be proven classified.

    The lane here is a cutover: three rounds ran and were finalized before any round record
    existed (simulated by removing the record tree, which is what a pre-WS1 lane looks like), so
    the fourth round's baseline absorbs them as a pre-record FLOOR. The floor carries no
    invocation record to classify, so it can never verify -- however many manifests it counted.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    # The cutover: this lane's history predates the record entirely.
    shutil.rmtree(_rounds_root(target))
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")

    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    line = _disclosure_line(r4.stdout)
    assert "round-record-verified" not in r4.stdout
    assert "3 further counted round(s) have no invocation record to classify" in line
    assert "pre-record baseline floor" in line

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    # DISCRIMINATING (WS5 remediation): the bare token assertion held against the pre-WS5 source
    # too, which wrote `caller-asserted` for every capped manifest without counting anything. The
    # manifest value is now pinned to the token AND the totals the same derivation printed -- three
    # of the four counted rounds unproven, in this lane's one lineage member -- so the pre-record
    # floor has to be counted and found unprovable before the token may read `caller-asserted`.
    assert (
        manifest["carried_findings_basis"],
        _disclosed_basis(line),
        _disclosed_totals(line),
    ) == ("caller-asserted", "caller-asserted", (3, 4, 1))


def test_basis_upgrade_counts_rounds_through_the_authoritative_resolver(tmp_path):
    """T5.1, and the plan's R1 P1: the rounds verified are the rounds the RESOLVER counts.

    The capped plan's own four rounds are all classified, so a backward-chain view of its lineage
    would certify it complete. WS3's resolver unions shared declared WORK ITEMS, and a sibling
    plan sharing this one's work item holds a charged round nobody ever classified. Verifying
    through the narrower view would write `round-record-verified` over a lineage the cap later
    counts differently -- so the upgrade is blocked and the sibling's round is named.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    _declare_work_item(target / PLAN_REL, "item-108-ws5-shared")
    sibling_rel = PLAN_REL.parent / "sibling-plan.md"
    _write_plan(target, sibling_rel)
    _declare_work_item(target / sibling_rel, "item-108-ws5-shared")
    # The sibling spends one charged reviewer invocation and never binds it.
    sibling = _run_cli(
        "run-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", sibling_rel.as_posix(),
        "--round", "S1",
        "--model", "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    assert sibling.returncode == 0, sibling.stdout + sibling.stderr

    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in r4.stdout
    line = _disclosure_line(r4.stdout)
    assert f"{sibling_rel.as_posix()} round S1 (" in line
    assert "is counted and never classified" in line

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    # DISCRIMINATING (WS5 remediation): pinning the token alone passed against the pre-WS5 source,
    # which never resolved a lineage at all before writing `caller-asserted`. The manifest value is
    # pinned to the token AND the totals of the line the same derivation printed, and those totals
    # are the RESOLVER's member set -- five counted rounds across two members, one of them unproven
    # -- which a backward-chain view would have reported as a complete four.
    assert (
        manifest["carried_findings_basis"],
        _disclosed_basis(line),
        _disclosed_totals(line),
    ) == ("caller-asserted", "caller-asserted", (1, 5, 2))


def _plan_rounds(target: Path) -> Path:
    """This plan's own round-record directory (the one the appends write into)."""
    return _rounds_root(target) / "test-plan"


def _round_records(rounds: Path, kind: str) -> list[dict]:
    records = []
    for path in sorted(rounds.glob("*.json")):
        if path.name == "000-baseline.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("kind") == kind:
            records.append(record)
    return records


def _finalize(home, adapter_root, target, adapter, log_path, review_round, *finalize_args):
    return _run_cli(
        "finalize-plan-review",
        "--project", str(adapter),
        "--target", str(target),
        "--plan", PLAN_REL.as_posix(),
        "--log", str(log_path),
        "--round", review_round,
        "--model", "codex-test",
        *finalize_args,
        home=home,
        adapter_root=adapter_root,
    )


def test_a_failed_classification_record_write_never_yields_a_verified_basis(tmp_path):
    """WS5 remediation P1. The token may only be written when the record that justifies it IS.

    The first cut wrote the manifest -- carrying `round-record-verified` -- and appended the bound
    round's classification record AFTERWARDS, inside a handler that turns an OSError into a stderr
    line and a return. It also SEEDED the bound log's digest into the proven set, so the round
    proved itself with a record that did not exist yet. Finalize a capped round with the record
    directory unwritable and the run exited 0 with a manifest certifying its carried list against
    a classification record that was never written: a control reporting success while the thing it
    counts is already lost, which is the defect class this whole item exists to remove.

    The exit stays 0 on purpose -- the lane-local ledger counted the round either way, and a
    finalize never refuses over record bookkeeping -- so the basis is what has to tell the truth.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    # R4 LAUNCHES normally -- its charged invocation record lands -- and only the classification
    # write is denied, which is what makes the seeded digest the sole basis for the old claim.
    r4 = _run_round(home, adapter_root, target, adapter, "R4", "--exception-note", NOTE)
    assert r4.returncode == 0, r4.stdout + r4.stderr

    rounds = _plan_rounds(target)
    before = {path.name for path in rounds.glob("*.json")}
    rounds.chmod(0o500)
    try:
        finalize = _finalize(
            home, adapter_root, target, adapter,
            _stdout_path(r4.stdout, "plan_review_run_log"),
            "R4", "--exception-note", NOTE, *_blocked(1),
        )
    finally:
        rounds.chmod(0o755)

    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in finalize.stdout
    # The record the token would have rested on genuinely does not exist.
    assert {path.name for path in rounds.glob("*.json")} == before
    assert "plan_review_round_record_error" in finalize.stderr
    assert not [
        record
        for record in _round_records(rounds, "round-classification")
        if record.get("declared_round") == "R4"
    ]

    line = _disclosure_line(finalize.stdout)
    assert _disclosed_basis(line) == "caller-asserted", line
    assert "round-record-verified" not in finalize.stdout
    # Named, not merely downgraded: the lane is told WHICH write failed and that the totals it is
    # reading are a floor because of it.
    assert "this finalize's own classification record could not be appended" in line
    assert "both totals are a FLOOR" in line

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["carried_findings_basis"] == _disclosed_basis(line) == "caller-asserted"


def test_an_imported_or_reimported_classification_cannot_prove_the_basis(tmp_path):
    """WS5 remediation P2. Proof needs an OBSERVED round, and no lane can mint one by re-running.

    `plan_review_append_import_records` MINTS a charged `source: imported` invocation for a digest
    it has never seen, and references it from an `origin: imported-unverified` classification --
    honest, and worth nothing as proof. But a SECOND identical `tautline record-plan-review` then
    matched the invocation the FIRST import had just minted, so it took the recorded branch and
    wrote an origin-free classification. An origin-free classification is exactly what the basis
    reads as proof, so running one import twice -- no privileged access, no hand-edited file --
    flipped the capped manifest to `round-record-verified` for a round the CLI never observed.

    Both halves are pinned here: the writer stops manufacturing the proof (every classification
    bound to an imported invocation keeps the imported origin), and the reader stops accepting it
    (a `source: imported` invocation can never be proven, whatever points at it).
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3)).returncode == 0
    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr

    # Rebuild the peer-lane state: R2's log survives as import evidence, its own invocation record
    # and lane meta never reached this checkout, so the digest is unknown to records and baseline.
    rounds = _plan_rounds(target)
    log_src = _stdout_path(r2.stdout, "plan_review_run_log")
    meta = json.loads(_stdout_path(r2.stdout, "plan_review_run_meta").read_text(encoding="utf-8"))
    import_rel = f"imported-evidence/{log_src.name}"
    import_log = target / import_rel
    import_log.parent.mkdir()
    shutil.copy2(log_src, import_log)
    meta["log_path"] = import_rel
    (target / f"{import_rel}.meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for path in sorted(rounds.glob("*.json")):
        if path.name == "000-baseline.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("kind") == "reviewer-invocation" and (
            record.get("log_sha256") == meta["log_sha256"]
        ):
            path.unlink()
    shutil.rmtree(target / ".ai-runs" / "plan-review")
    import_log.touch()

    def _import():
        return _run_cli(
            "record-plan-review",
            "--project", str(adapter),
            "--target", str(target),
            "--plan", PLAN_REL.as_posix(),
            "--log", import_rel,
            "--review-command", meta["review_command"],
            "--reviewer", "codex",
            "--model", "codex-test",
            "--round", "R2",
            "--wrapper-exit-code", "0",
            *CLEAN,
            home=home,
            adapter_root=adapter_root,
        )

    first = _import()
    assert first.returncode == 0, first.stdout + first.stderr
    reimport = _import()
    assert reimport.returncode == 0, reimport.stdout + reimport.stderr

    # The writer half: the re-import binds to the minted invocation and inherits its origin, so no
    # origin-free classification exists for a round nobody observed.
    imported_classifications = [
        record
        for record in _round_records(rounds, "round-classification")
        if record.get("log_sha256") == meta["log_sha256"]
    ]
    assert len(imported_classifications) == 2, imported_classifications
    assert [record.get("origin") for record in imported_classifications] == [
        "imported-unverified",
        "imported-unverified",
    ], imported_classifications

    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    # The reader half: four counted rounds, one of them imported, so the basis cannot upgrade.
    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in r4.stdout
    line = _disclosure_line(r4.stdout)
    assert "round-record-verified" not in r4.stdout
    assert " round R2 (" in line
    assert "was never observed by this CLI (imported evidence)" in line

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert (
        manifest["carried_findings_basis"],
        _disclosed_basis(line),
        _disclosed_totals(line),
    ) == ("caller-asserted", "caller-asserted", (1, 4, 1))


def test_an_unknown_spend_member_is_counted_in_the_disclosure_and_blocks_the_upgrade(tmp_path):
    """WS5 remediation P3. The denominator must not shrink exactly where the lineage is least known.

    A lineage member whose spend reads `unknown` was skipped before it reached the counted total,
    so the line could report `0 of 4 counted round(s) across 2 lineage member(s) are NOT verified`
    -- a numerator of zero, printed for a lineage holding a member whose rounds nobody can count.
    A lane reading that sees a clean bill beside the honest token. The member is now visible where
    the totals are printed: both are declared a FLOOR, and the member is named with the reason its
    rounds are in neither of them.

    Blocking the upgrade is the other half and is asserted with it: rounds nobody can count can
    never be shown classified.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *_blocked(3))
    assert r1.returncode == 0, r1.stdout + r1.stderr

    # A predecessor this checkout holds no review evidence for -- the ordinary shape of a lineage
    # whose earlier plan was reviewed in another worktree. It is a real declared edge (the
    # resolver admits it from the run meta), and its spend cannot be read at all.
    ghost_rel = (PLAN_REL.parent / "ghost-plan.md").as_posix()
    meta_path = _stdout_path(r1.stdout, "plan_review_run_meta")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["predecessor_plan_path"] = ghost_rel
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert _run_round(home, adapter_root, target, adapter, "R2", *_blocked(2)).returncode == 0
    _mutate_plan(target, "4. Fix one blocker.\n")
    assert _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    ).returncode == 0
    _mutate_plan(target, "5. Fail to fix the last blocker.\n")
    r4 = _run_round(
        home, adapter_root, target, adapter, "R4", "--exception-note", NOTE, *_blocked(1)
    )

    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert "plan_review_capped: verdict=capped-with-open-findings" in r4.stdout
    line = _disclosure_line(r4.stdout)
    # The unknown member is IN the printed accounting: two members, and the totals are declared
    # floors because one of them cannot be counted.
    assert "across 2 lineage member(s) are NOT verified" in line
    assert "both totals are a FLOOR" in line
    assert f"{ghost_rel}: spend reads unknown" in line
    assert "in neither total" in line
    # ...and it blocks the upgrade, since its rounds can never be shown classified.
    assert _disclosed_basis(line) == "caller-asserted", line
    assert "round-record-verified" not in r4.stdout

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert manifest["carried_findings_basis"] == _disclosed_basis(line) == "caller-asserted"


def test_a_non_capped_manifest_carries_no_findings_basis_field(tmp_path):
    """The disclosure is capped-only: every other manifest stays byte-identical.

    A clean R1 finalize must not grow the new key -- the same rule `asserted_verdict` follows.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *CLEAN)
    assert r1.returncode == 0, r1.stdout + r1.stderr

    manifest = json.loads(_manifest_path(target).read_text(encoding="utf-8"))
    assert "carried_findings_basis" not in manifest
    assert "plan_review_capped_disclosure" not in r1.stdout


def test_the_finalize_retracts_its_classification_by_record_identity(cli):
    """Codex R4 P3: the first version of this scenario fabricated a correction keyed on the
    invocation NONCE and filtered classifications by nonce, so it would still have passed for the
    round-target behaviour that poisons retries — a test that no longer guarded what it claimed.

    This pins the production wiring instead: the append helper hands back the record's identity,
    and the finalize retracts THAT identity. The semantics (retract, retry, same-second ordering)
    are covered by the test below, which operates on real appended records.
    """
    import inspect

    assert hasattr(cli, "plan_review_retract_classification_record")
    retract_src = inspect.getsource(cli.plan_review_retract_classification_record)
    assert "classification_record_id" in retract_src, (
        "the retraction must name the RECORD it retracts, not the round"
    )
    assert "corrects=target_ref" in retract_src.replace(" ", "").replace("\n", "") or (
        "corrects=" in retract_src
    )

    append_src = inspect.getsource(cli.plan_review_append_classification_record)
    assert "Path(record_path).stem" in append_src, (
        "the append helper must return the record identity a correction can name"
    )

    finalize_src = inspect.getsource(cli.finalize_trusted_plan_review)
    assert "classification_record_id=classification_recorded" in finalize_src.replace(
        "\n", ""
    ).replace("  ", ""), "the finalize must retract the record it just appended"


def test_retraction_names_a_record_so_order_and_retries_do_not_matter(cli, tmp_path):
    """Codex R2 P2 and R3 P2 together: a retraction must not poison the round, and it must not
    depend on record order.

    Retracting the round's TARGET meant a legitimate retry could never re-prove it. Folding by
    `recorded_at` instead has second precision and the filename suffix is random, so in the very
    failure path this exists for -- classification and correction written back-to-back inside one
    second -- the correction could sort FIRST and be overwritten, silently reinstating the orphan.
    A correction therefore names the RECORD it retracts, by that record's unique file identity:
    order is irrelevant, and a retry is a different record that nothing retracts.
    """
    module = cli.plan_round_record_module()
    rounds = tmp_path / "rounds"
    rounds.mkdir()

    def _classification(at):
        return module.render_round_classification(
            plan_identity="p", plan_path="p.md", plan_content_sha256="0" * 64,
            declared_round="R1", verdict="blocked", unresolved_critical_count=1,
            unresolved_p1_count=0, classified_findings_count=1, nonce="n" * 16,
            log_sha256="l" * 64, origin="", recorded_by="t", recorded_at=at,
        )

    def _proven():
        records = module.load_round_records(rounds)
        retracted = {
            str(r.get("corrects") or "")
            for _p, r in records
            if r.get("kind") == "correction"
            and str(r.get("corrects") or "") != module.CORRECTION_BASELINE_TARGET
        }
        return {
            Path(path).stem
            for path, record in records
            if record.get("kind") == "round-classification"
            and not record.get("origin")
            and Path(path).stem not in retracted
        }

    # Same second for both writes -- the exact case a timestamp fold cannot order.
    orphan = module.append_record(rounds, _classification("2026-08-17T00:01:00+00:00"))
    assert _proven() == {Path(orphan).stem}

    module.append_record(
        rounds,
        module.render_correction(
            plan_identity="p", plan_path="p.md", corrects=Path(orphan).stem,
            note="round R1: the finalize that appended this classification did not complete",
            raise_prerecord_count_to=None, recorded_by="t",
            recorded_at="2026-08-17T00:01:00+00:00",
        ),
    )
    assert _proven() == set(), (
        "a retracted classification must be skipped regardless of the order records are read in"
    )

    retry = module.append_record(rounds, _classification("2026-08-17T00:01:00+00:00"))
    assert _proven() == {Path(retry).stem}, (
        "a retry is a DIFFERENT record that nothing retracts, so it proves its round even when "
        "it shares a timestamp with the retraction that preceded it"
    )
    assert Path(retry).stem != Path(orphan).stem
