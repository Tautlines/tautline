"""Test-execution evidence ENFORCEMENT (item 37, Release 2).

Release 1 made a test run produce a tamper-evident receipt. Nothing read it: `classify_test_run_
evidence` computed `red` and its only consumer in the whole codebase was a `print`. A receipt
nobody reads is a receipt nobody needs.

This is the layer that makes the gates read it — and it ships **`block` by default**, per the
operator decision of 2026-07-31, overriding the R2 plan's original `warn` default. The reasoning:
a warn default makes the control opt-in, and the failure it exists to stop ("the tests passed" as a
sentence someone typed rather than a fact) is the operator's #1 recurring failure. An opt-in
control does not fix a recurring failure.

The cost of that choice is real and is why `test_every_block_refusal_prints_its_remedy` exists: a
downstream project advanced into `block` with no record lands in `missing`, not `red`. A project
blocked with no way out teaches its operator `--no-verify`, which is worse than no gate at all.
"""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import pytest


@pytest.fixture()
def te(cli):
    return cli.test_evidence_module()


# --- the mode contract -------------------------------------------------------------------------


def test_the_default_is_block(te):
    """The operator amendment, pinned. If someone re-reads the R2 plan and 'restores' warn, this
    fails and names the decision."""
    assert te.DEFAULT_ENFORCEMENT == "block"
    assert te.ENFORCEMENT_MODES == ("off", "warn", "block")


def test_absent_key_means_block(cli):
    assert cli.test_evidence_config({})["enforcement"] == "block"
    assert cli.test_evidence_config({"testEvidence": {}})["enforcement"] == "block"


def test_absent_key_still_leaves_the_rest_of_the_block_intact(cli):
    """Release 1's absent-stays-absent contract must survive the new key."""
    config = cli.test_evidence_config({})
    assert config["report"] is None
    assert config["freshCheckout"]["default"] is False


@pytest.mark.parametrize("mode", ["off", "warn", "block"])
def test_every_declared_mode_round_trips(cli, mode):
    data = {"testEvidence": {"enforcement": mode}}
    assert cli.test_evidence_config(data)["enforcement"] == mode


@pytest.mark.parametrize("bad", ["BLOCK", "on", "", "strict", True, 1, [], {}])
def test_a_mistyped_mode_refuses_rather_than_coercing(cli, bad):
    """Type-check, never coerce. A mistyped knob that silently resolved to a WEAKER mode is the
    worst failure available here: the lane believes it has enforcement it does not have, which is
    the same untrue-green this item exists to close."""
    with pytest.raises(SystemExit) as excinfo:
        cli.test_evidence_config({"testEvidence": {"enforcement": bad}})
    assert "testEvidence.enforcement" in str(excinfo.value)
    assert "off, warn, block" in str(excinfo.value)


def test_the_schema_declares_the_key(cli):
    """The adapter schema is closed to unknown keys, so an undeclared knob is unusable."""
    root = Path(cli.__file__).resolve().parents[2]
    schema = json.loads((root / "methodology" / "adapter-schema.json").read_text())

    def find(node):
        if isinstance(node, dict):
            if "testEvidence" in node.get("properties", {}):
                return node["properties"]["testEvidence"]
            for value in node.values():
                found = find(value)
                if found:
                    return found
        return None

    block = find(schema)
    assert block is not None
    assert block["properties"]["enforcement"]["enum"] == ["off", "warn", "block"]


# --- the per-state matrix ----------------------------------------------------------------------

BLOCKING_STATES = ["missing", "invalid", "stale", "red"]


@pytest.mark.parametrize("state", BLOCKING_STATES)
def test_block_refuses_every_untrustworthy_state(
    cli, te, tmp_path, monkeypatch, state
):
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: (state, {}))

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == state
    assert disposition == te.BLOCK
    assert lines


@pytest.mark.parametrize("state", BLOCKING_STATES)
def test_warn_reports_the_same_states_without_refusing(
    cli, te, tmp_path, monkeypatch, state
):
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: (state, {}))

    _condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "warn")

    assert disposition == te.WARN
    assert lines, "warn must still SAY something; a silent warn is `off` with extra steps"


@pytest.mark.parametrize("state", BLOCKING_STATES + ["unavailable"])
def test_off_is_silent_and_never_refuses(cli, te, tmp_path, monkeypatch, state):
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: (state, {}))

    _condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "off")

    assert disposition == te.PASS
    assert lines == []


def test_unavailable_fails_open_even_under_block(
    cli, te, tmp_path, monkeypatch
):
    """The 2026-07-22 startup-gate lockout, applied forward: `unavailable` means the CHECKER
    broke, not that the tests are bad. A control that cannot tell must not stop the lane."""
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("unavailable", {}))

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "unavailable"
    assert disposition == te.FAIL_OPEN
    assert any("failing OPEN" in line for line in lines)


def test_an_exploding_classifier_fails_open_rather_than_propagating(
    cli, te, tmp_path, monkeypatch
):
    """This runs on the prepush path. A gate that can itself raise is worse than no gate."""

    def boom(_target):
        raise RuntimeError("disk went away")

    monkeypatch.setattr(te, "classify_test_run_evidence", boom)

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "unavailable"
    assert disposition == te.FAIL_OPEN
    assert any("disk went away" in line for line in lines), "name the error, do not shrug"


# --- what `current` actually proves ------------------------------------------------------------


def _record(**counts):
    base = {
        "source": "junit-xml",
        "collected": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
    }
    base.update(counts)
    # The `report` block is REQUIRED for a parsed source to be believed (Codex R2 P2): without it
    # nothing verifies the counts, so a record like this one is `invalid` by construction. The
    # fixture carries it because a parsed-source record without a report is a shape the writer
    # cannot produce -- modelling it here would have been testing an impossible record.
    return {
        "report": {
            "path": ".ai-runs/test-runs/x-junit.xml",
            "sha256": "abc",
            "format": "junit-xml",
        },
        "counts": base,
    }


def test_a_parsed_green_report_with_real_execution_is_admitted(
    cli, te, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        te, "classify_test_run_evidence", lambda _t: ("current", _record(collected=10, passed=10))
    )

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-parsed"
    assert disposition == te.PASS


def test_zero_collected_is_refused_under_block(
    cli, te, tmp_path, monkeypatch
):
    """A structurally valid report that collected nothing proves no execution. This is the same
    bypass class as a fabricated count, reached honestly -- point the suite at a glob that matches
    no files and every gate goes green."""
    monkeypatch.setattr(
        te, "classify_test_run_evidence", lambda _t: ("current", _record(collected=0))
    )

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-zero-tests"
    assert disposition == te.BLOCK


def test_an_all_skipped_report_is_refused_under_block(
    cli, te, tmp_path, monkeypatch
):
    """Skipped tests are not evidence -- the methodology's founding rule. An all-skipped report
    proves no execution just as surely as a zero-collected one."""
    monkeypatch.setattr(
        te, "classify_test_run_evidence", lambda _t: ("current", _record(collected=7, skipped=7))
    )

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-zero-tests"
    assert disposition == te.BLOCK


def test_failures_in_the_report_are_red_even_when_the_process_exited_zero(
    cli, te, tmp_path, monkeypatch
):
    """`pytest ... || true` swallows the process status while the report still records failures.
    The REPORT is the authority."""
    monkeypatch.setattr(
        te,
        "classify_test_run_evidence",
        lambda _t: ("current", _record(collected=10, passed=8, failed=2)),
    )

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "red"
    assert disposition == te.BLOCK
    # The `red` reason is shared by both paths into it, so it must not assert the exit code was
    # non-zero -- here it was zero. A refusal that explains itself with something false is the
    # small end of the untrue-green this release exists to stop.
    reason = te.ENFORCEMENT_REASONS["red"]
    assert "exited non-zero, or" in reason, "the reason must not claim a non-zero exit outright"
    assert "report" in reason, "it must name the report as the authority that found the failures"


def test_exit_code_only_evidence_is_refused_under_block_and_named_honestly(
    cli, te, tmp_path, monkeypatch
):
    """A green process with no declared report is honest evidence of a green PROCESS, and no
    evidence at all about how many tests ran."""
    monkeypatch.setattr(
        te,
        "classify_test_run_evidence",
        lambda _t: ("current", {"counts": {"source": "exit-code-only"}}),
    )

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-exit-code-only"
    assert disposition == te.BLOCK
    assert any("report" in line for line in lines), "must name the report declaration as the fix"


def test_a_count_sum_that_disagrees_is_not_admitted(
    cli, te, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        te,
        "classify_test_run_evidence",
        lambda _t: ("current", _record(collected=10, passed=3)),
    )

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition != "current-parsed"
    assert disposition == te.BLOCK


# --- the remedy contract -----------------------------------------------------------------------


@pytest.mark.parametrize("state", BLOCKING_STATES)
def test_every_block_refusal_prints_its_remedy(
    cli, te, tmp_path, monkeypatch, state
):
    """The half of this feature that keeps it from being hated.

    Downstream products mostly land in `missing`, not `red`. A project advanced into a blocked
    state with no way out teaches its operator `--no-verify` -- which removes every gate, not just
    this one. So each refusal names the command that produces evidence, the declaration that makes
    counts parse, AND the deliberate downgrade.
    """
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: (state, {}))

    _condition, _disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")
    joined = "\n".join(lines)

    assert "tautline test-run" in joined, "must name the command that produces evidence"
    assert "testEvidence.report" in joined, "must name the declaration that makes counts parse"
    assert "testEvidence.enforcement" in joined, "must name the deliberate downgrade"
    assert "render-adapters" in joined, "a source-adapter edit is inert until re-rendered"


@pytest.mark.parametrize(
    "state", BLOCKING_STATES + ["current-exit-code-only", "current-zero-tests"]
)
def test_every_refused_condition_states_a_reason(cli, te, state):
    """A refusal that names the state but not why it refuses makes the reader reverse-engineer the
    classifier."""
    assert state in te.ENFORCEMENT_REASONS or state == "red"
    if state in te.ENFORCEMENT_REASONS:
        assert len(te.ENFORCEMENT_REASONS[state]) > 30


def test_an_unknown_mode_falls_back_to_the_default_rather_than_passing(
    cli, te, tmp_path, monkeypatch
):
    """Fail closed on a mode the evaluator does not recognise. Normalization already refuses these,
    so reaching here is a bug -- and the safe behaviour for a bug is the strict default, not
    silence.
    """
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("missing", {}))

    _condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "nonsense")

    assert disposition == te.BLOCK


# --- the prepush consumer (W2) -----------------------------------------------------------------


def test_the_prepush_check_refuses_under_block(cli, te, tmp_path, monkeypatch):
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("missing", {}))
    monkeypatch.setattr(
        cli, "lane_project", lambda a: ({"testEvidence": {"enforcement": "block"}}, None, tmp_path)
    )

    rc = cli.test_evidence_enforcement_check(
        argparse.Namespace(project=None, target=tmp_path)
    )

    assert rc == 1


@pytest.mark.parametrize("mode", ["warn", "off"])
def test_the_prepush_check_never_refuses_below_block(cli, te, tmp_path, monkeypatch, mode):
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("missing", {}))
    monkeypatch.setattr(
        cli, "lane_project", lambda a: ({"testEvidence": {"enforcement": mode}}, None, tmp_path)
    )

    rc = cli.test_evidence_enforcement_check(
        argparse.Namespace(project=None, target=tmp_path)
    )

    assert rc == 0


def test_a_lane_with_no_adapter_is_never_refused(cli, tmp_path, monkeypatch):
    """This check must not be the thing that stops a lane it was never configured for."""

    def no_adapter(_args):
        raise SystemExit("No project adapter found for this lane.")

    monkeypatch.setattr(cli, "lane_project", no_adapter)

    rc = cli.test_evidence_enforcement_check(
        argparse.Namespace(project=None, target=tmp_path)
    )

    assert rc == 0


def test_unavailable_does_not_refuse_through_the_consumer(cli, te, tmp_path, monkeypatch):
    """Fail-open has to survive the wiring, not just the evaluator."""
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("unavailable", {}))
    monkeypatch.setattr(
        cli, "lane_project", lambda a: ({"testEvidence": {"enforcement": "block"}}, None, tmp_path)
    )

    rc = cli.test_evidence_enforcement_check(
        argparse.Namespace(project=None, target=tmp_path)
    )

    assert rc == 0


def test_a_malformed_knob_names_itself_rather_than_blaming_the_suite(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "lane_project", lambda a: ({"testEvidence": {"enforcement": "nope"}}, None, tmp_path)
    )

    rc = cli.test_evidence_enforcement_check(
        argparse.Namespace(project=None, target=tmp_path)
    )

    assert rc == 1


def test_the_prepush_boundary_wires_the_check_in(cli):
    """The evaluator existing is not the same as a gate reading it -- which is precisely the
    Release 1 gap this release closes. Pin the wiring, not just the logic."""
    source = inspect.getsource(cli.guard_check)
    assert "test_evidence_enforcement_check" in source
    assert '"test evidence"' in source


def test_the_check_is_skipped_on_a_pm_surfaces_only_push(cli):
    """A docs-only push has no suite to have run. The skip must cover this check the same way it
    covers review-evidence and the CI gate, or a PM-surface push becomes unpushable."""
    source = inspect.getsource(cli.guard_check)
    body = source.split("pm_surface_skip = ")[1]
    appended = body.split("test_evidence_enforcement_check")[0]
    assert appended.count("if not pm_surface_skip:") >= 2


# --- the finalize consumer (W3) ----------------------------------------------------------------


def test_finalize_is_gated_on_test_evidence_for_push_eligible_verdicts(cli):
    source = inspect.getsource(cli.finalize_implementation_review)
    assert "test_evidence_enforcement_check" in source
    assert "IMPLEMENTATION_REVIEW_ALLOWED_VERDICTS" in source


def test_a_blocked_verdict_never_requires_test_evidence(cli):
    """Recording `blocked` is how a lane HONESTLY reports that review found something. Demanding
    green test evidence before it could say so would make the truthful verdict the hardest one to
    record -- pressure in exactly the wrong direction."""
    source = inspect.getsource(cli.finalize_implementation_review)
    guard = source.split("test_evidence_enforcement_check")[0]
    assert "if args.verdict in IMPLEMENTATION_REVIEW_ALLOWED_VERDICTS:" in guard


def test_a_refused_finalize_mutates_nothing(cli):
    """The check sits AFTER verdict validation and BEFORE the manifest is touched. A finalize that
    half-wrote a ledger and then refused would leave the lane worse off than before it ran."""
    source = inspect.getsource(cli.finalize_implementation_review)
    gate = source.index("test_evidence_enforcement_check")
    mutation = source.index("manifest.update(")
    assert gate < mutation, "the evidence gate must precede every manifest mutation"


def test_the_finalize_refusal_names_the_blocked_verdict_as_the_way_out(cli):
    # Asserts the two EXITS are runnable, not that a particular sentence appears. The first draft
    # of this refusal said "record `blocked` instead" and named no command -- and the 0.36.0
    # no-dead-ends invariant (tests/test_refusal_continuations.py) failed it for exactly that,
    # which is that control policing a new refusal on a different surface a release later.
    source = " ".join(inspect.getsource(cli.finalize_implementation_review).split())
    assert "tautline test-run --target" in source, (
        "must name the runnable command that PRODUCES evidence"
    )
    assert "--verdict blocked" in source, (
        "must name the verdict that needs no evidence, as a runnable invocation -- a lane with a "
        "genuine blocker has to be able to record it"
    )
    assert "finalize-implementation-review --target" in source, (
        "the blocked exit must be a full invocation, not a verdict name in prose"
    )


# --- the two gates must not deadlock each other (Codex R1 P2 on Release 2) ---------------------
#
# finalize accepted the record, then wrote the TRACKED implementation-review ledger, which is part
# of the non-ignored tree digest -- so the record it had just accepted went `stale` one line later,
# and the prepush gate shipping in the same release then refused the push. Two new gates
# deadlocking each other, at the cost of a second full suite run per PR for every lane.


def test_the_tracked_review_ledger_is_excluded_from_the_tree_digest(cli, tmp_path):
    data = {"planningArtifacts": {"sourceOfTruth": "docs/plans"}}

    excludes = cli.test_run_digest_excludes(data, tmp_path)

    assert excludes == ["docs/plans/.impl-reviews"], (
        "finalize writes this ledger AFTER the suite ran; leaving it in the digest makes every "
        "accepted record stale the moment the verdict is bound"
    )


def test_the_exclusion_reaches_the_digest_helper(cli, te, tmp_path):
    excluded = te.digest_excluded_paths(None, tmp_path, ["docs/plans/.impl-reviews"])

    assert te.TEST_RUN_DIR in excluded
    assert "docs/plans/.impl-reviews" in excluded


def test_digest_excludes_never_break_test_run_when_unresolvable(cli, tmp_path):
    """An adapter without planningArtifacts must not take `test-run` down with it: the exclusion
    is an optimisation of correctness, not a precondition for recording anything."""
    assert cli.test_run_digest_excludes({}, tmp_path) == []


def test_the_report_exclusion_still_applies_alongside_the_new_one(cli, te, tmp_path):
    """The unresolvable-report early return used to skip the rest of the list. Both kinds of
    evidence-about-a-run have to be excluded, not whichever one is resolved first."""
    outside = tmp_path.parent / "elsewhere" / "junit.xml"

    excluded = te.digest_excluded_paths(outside, tmp_path, ["docs/plans/.impl-reviews"])

    assert "docs/plans/.impl-reviews" in excluded, (
        "a report path that cannot be made relative must not swallow the ledger exclusion"
    )


# --- the fabricated-counts bypass (Codex R2 P2 on Release 2) -----------------------------------
#
# classify_test_run_evidence verifies counts against the hashed report copy ONLY when the record
# carries a `report` block. Without one there is nothing to verify against -- so a record in
# gitignored .ai-runs/ could be hand-edited to claim a parsed source with plausible green counts,
# and `block` would admit it. An ASSERTION substituted for an EXECUTION, reintroduced by the layer
# built to stop exactly that.


def test_parsed_counts_without_a_hashed_report_are_refused(cli, te, tmp_path, monkeypatch):
    """THE bypass. A green-looking `junit-xml` count block with no report to verify it against."""
    forged = {
        "counts": {
            "source": "junit-xml",
            "collected": 4000,
            "passed": 4000,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }
    }
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("current", forged))

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "invalid", (
        "a record claiming a parse that left no artifact is corrupt or edited, not merely weaker "
        "evidence -- downgrading it to exit-code-only would still let it through a warn lane "
        "looking honest"
    )
    assert disposition == te.BLOCK


def test_a_parsed_source_with_a_report_block_is_still_admitted(cli, te, tmp_path, monkeypatch):
    """The fix must not refuse the legitimate shape it was written to protect."""
    genuine = {
        "report": {
            "path": ".ai-runs/test-runs/x-junit.xml",
            "sha256": "abc",
            "format": "junit-xml",
        },
        "counts": {
            "source": "junit-xml",
            "collected": 10,
            "passed": 10,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
    }
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("current", genuine))

    condition, disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-parsed"
    assert disposition == te.PASS


def test_an_honest_exit_code_only_record_is_unaffected(cli, te, tmp_path, monkeypatch):
    """`exit-code-only` with no report is the writer's OWN honest output when no report is
    declared. It must stay exit-code-only -- refused under block, but named for what it is."""
    honest = {"counts": {"source": "exit-code-only"}}
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("current", honest))

    condition, _disposition, _lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "current-exit-code-only"


def test_the_writer_never_produces_a_parsed_source_without_a_report(cli, te):
    """The reason `invalid` is the right verdict rather than a downgrade: this combination cannot
    come from run_and_record at all, so seeing it means the record was edited."""
    source = inspect.getsource(te.run_and_record)
    assert "COUNTS_SOURCE_EXIT_CODE_ONLY" in source, (
        "the writer must record exit-code-only when it has no report to parse; if that changes, "
        "the invalid verdict above needs revisiting"
    )


# --- the unreadable-record bypass (Codex R4 P1) ------------------------------------------------
#
# `unavailable` was covering two different things, and only one is an outage:
#   * the checker could not run at all            -> a genuine outage, fail open
#   * the newest record EXISTS and is malformed   -> present-and-untrustworthy, i.e. `invalid`
#
# Treating the second as an outage meant dropping ANY corrupt file into gitignored
# .ai-runs/test-runs/ with a newer timestamp bypassed both gates completely -- no crafting needed,
# which makes it easier to exploit than a forged record.


def test_a_malformed_record_on_disk_classifies_invalid_not_unavailable(cli, te, tmp_path):
    """THE bypass, driven through the REAL classifier rather than a mock.

    The first fix for this keyed on the `__unreadable__` tag from outside the classifier, which
    covered one of the two ways evidence can be present-and-unreadable and left the other open
    (R5 found it). Testing against a mocked classifier state is what let that happen -- the mock
    could express a state the classifier no longer produces. Real garbage on disk cannot lie.
    """
    records = tmp_path / te.TEST_RUN_DIR
    records.mkdir(parents=True)
    (records / "20260101T000000Z-test-run.json").write_text("{ not json at all", encoding="utf-8")

    state, _record = te.classify_test_run_evidence(tmp_path)

    assert state == "invalid", (
        "a record that EXISTS and cannot be parsed is untrustworthy evidence, not a checker "
        "outage -- reported as an outage it fails open and every gate is bypassed by garbage"
    )


def test_a_malformed_record_is_refused_under_block(cli, te, tmp_path):
    records = tmp_path / te.TEST_RUN_DIR
    records.mkdir(parents=True)
    (records / "20260101T000000Z-test-run.json").write_text("{{{", encoding="utf-8")

    _condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert disposition == te.BLOCK
    assert any("tautline test-run" in line for line in lines), "and it still names its remedy"


def test_an_unreadable_report_copy_classifies_invalid(cli, te, tmp_path):
    """The SECOND way evidence can be present-and-unreadable, and the one the tag-keyed fix
    missed. The report copy is what verifies the counts; unreadable, it verifies nothing."""
    import json
    import os

    records = tmp_path / te.TEST_RUN_DIR
    records.mkdir(parents=True)
    report = records / "20260101T000000Z-report.xml"
    report.write_text("<testsuite/>", encoding="utf-8")
    (records / "20260101T000000Z-test-run.json").write_text(
        json.dumps(
            {
                "schema": te.TEST_RUN_SCHEMA,
                "exitCode": 0,
                "report": {
                    "path": f"{te.TEST_RUN_DIR}/20260101T000000Z-report.xml",
                    "sha256": "whatever",
                    "format": "junit-xml",
                },
                "counts": {"source": "junit-xml", "collected": 1, "passed": 1},
                "git": {"treeDigest": "abc"},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(report, 0o000)
    try:
        state, _record = te.classify_test_run_evidence(tmp_path)
    finally:
        os.chmod(report, 0o644)

    assert state == "invalid", (
        "an unreadable report copy must not fail open; it is present evidence that cannot be "
        "verified, which is exactly what invalid means"
    )


def test_a_genuine_classifier_outage_still_fails_open(cli, te, tmp_path, monkeypatch):
    """The distinction has to cut both ways: narrowing fail-open must not remove it. A checker
    that cannot run still must not stop the lane -- the 2026-07-22 startup-gate precedent."""
    monkeypatch.setattr(te, "classify_test_run_evidence", lambda _t: ("unavailable", None))

    condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "block")

    assert condition == "unavailable"
    assert disposition == te.FAIL_OPEN
    assert any("failing OPEN" in line for line in lines)


def test_an_unreadable_record_is_still_silent_under_off(cli, te, tmp_path, monkeypatch):
    monkeypatch.setattr(
        te, "classify_test_run_evidence", lambda _t: ("unavailable", {"__unreadable__": "x"})
    )

    _condition, disposition, lines = te.evaluate_test_evidence_enforcement(tmp_path, "off")

    assert disposition == te.PASS
    assert lines == []


def test_finalize_refuses_a_record_whose_exclusions_predate_the_ledger(cli):
    """The deadlock this release fixed once has a second door, open only to upgrading lanes.

    `test_run_digest_excludes` writes the tracked ledger dir into the record at WRITE time, and the
    prepush gate re-uses whatever exclusions that record stored. A record produced BEFORE this
    release does not carry the ledger path -- so finalize accepts it, writes the ledger, and the
    prepush gate then recomputes the digest without excluding the file finalize just created and
    calls the same record stale.

    The lane is blocked immediately after a SUCCESSFUL finalize, with the tracked artifact already
    mutated. That is the worst moment to be blocked, so the refusal has to come first.
    """
    source = inspect.getsource(cli.finalize_implementation_review)
    assert "excludedPaths" in source, "finalize must inspect the record's stored exclusions"
    guard = source.index("excludedPaths")
    mutation = source.index("manifest.update(")
    assert guard < mutation, (
        "the exclusion check must precede every manifest mutation -- refusing after the ledger is "
        "written is the deadlock it exists to prevent"
    )


def test_the_stale_exclusion_refusal_is_runnable(cli):
    """Same no-dead-ends contract every other refusal on this surface answers to."""
    source = " ".join(inspect.getsource(cli.finalize_implementation_review).split())
    marker = source.index("predates")
    assert "tautline test-run --target" in source[marker:], (
        "the refusal must name the runnable command that produces a fresh record"
    )


def test_a_whole_tree_exclusion_makes_a_record_invalid(te, tmp_path):
    """The forgery the record's own exclusions would otherwise permit.

    Re-applying the exclusions a record DECLARES is what keeps old records valid across config
    changes -- but it also lets the record choose its own comparison basis. An entry of "."
    excludes the whole worktree, so the recorded digest is the empty-tree hash, which the
    classifier then recomputes to that identical value for ANY tree. A hand-written record with a
    copied green report would be admitted as `current` on a tree nothing ever ran against, and
    this classifier is what the push and finalize gates ask.
    """
    for entry in (".", "./", "", "/"):
        assert te._is_untrustworthy_exclusion(entry), f"{entry!r} excludes the entire tree"

    # "*" and "**" are NOT in that list any more, and that is the point of the :(literal) fix:
    # passed as literal pathspecs they name a file called "*", which does not exist, so
    # --ignore-unmatch makes them a no-op rather than a whole-tree wipe. Rejecting them as data
    # would also have rejected legal filenames containing the same characters.
    for entry in ("*", "**"):
        assert not te._is_untrustworthy_exclusion(entry), (
            f"{entry!r} is inert once passed as a literal pathspec"
        )


def test_real_exclusions_are_not_mistaken_for_whole_tree(te):
    """The guard must not reject what the writer actually produces."""
    for entry in (
        ".ai-runs/test-runs",
        ".ai-runs/test-runs/latest-junit.xml",
        "docs/superpowers/plans/.impl-reviews",
        "junit.xml",
    ):
        assert not te._is_untrustworthy_exclusion(entry), f"{entry!r} is a legitimate exclusion"


def test_the_ledger_exclusion_guard_respects_a_downgrade(cli):
    """warn/off is a documented downgrade whose contract is that this surface stops changing exit
    codes. A guard that refused regardless of mode would make the downgrade non-nonblocking for
    exactly the mid-migration lanes it exists to unblock."""
    source = inspect.getsource(cli.finalize_implementation_review)
    marker = source.index("excludedPaths")
    guard = source.rindex('mode == "block"', 0, marker)
    assert guard < marker, "the mode check must gate the ledger-exclusion refusal"


def test_git_pathspec_magic_is_rejected_in_exclusions(te):
    """The first draft of the forgery guard enumerated the bad spellings and missed git's own.

    `:(top)`, `:/*`, `:(glob)**` and friends all reach the whole tree through `git rm --cached`,
    and none of them look like ".", "*", or "**". Enumerating what git accepts is a losing game,
    so the guard is an allowlist over what this module actually EMITS.
    """
    for entry in (":(top)", ":/*", ":(glob)**", ":!keep", ":^keep", ":(exclude)x", "/abs/path",
                  "../escape", "~/home"):
        assert te._is_untrustworthy_exclusion(entry), f"{entry!r} must not be trusted"


def test_literal_glob_characters_in_a_filename_are_allowed(te):
    """`report[1].xml` is a legal filename, not an attack.

    Rejecting glob metacharacters made the writer emit evidence the classifier then refused: a
    lane configuring such a report path could never satisfy the gate with its own green run.
    They are safe because `non_ignored_tree_digest` passes exclusions as `:(literal)` pathspecs,
    so git matches the name rather than the pattern.
    """
    for entry in ("report[1].xml", "a/b*c.json", "weird?name.xml"):
        assert not te._is_untrustworthy_exclusion(entry), f"{entry!r} is a legal filename"


def test_exclusions_are_passed_as_literal_pathspecs(te):
    """The boundary that would otherwise interpret a glob is where glob handling belongs."""
    source = inspect.getsource(te.non_ignored_tree_digest)
    assert '":(literal)' in source, (
        "exclusions must be passed as literal pathspecs so a filename is matched as itself"
    )


def test_an_unreadable_record_store_fails_open(te, tmp_path, monkeypatch):
    """A store that cannot be LISTED is a checker outage, not an absence of evidence.

    Swallowing the OSError into None made an unreadable store indistinguishable from an empty one,
    so a permissions or filesystem error classified `missing` and BLOCKED under the default mode.
    That inverts the standing rule this module states everywhere else: a control that cannot tell
    must not stop the lane.
    """
    def boom(_target):
        raise OSError("permission denied")

    monkeypatch.setattr(te, "test_run_dir", boom)
    record = te.load_latest_test_run(tmp_path)
    assert record is not None and "__store_unreadable__" in record, (
        "an unlistable store must be distinguishable from an empty one"
    )


def test_option_shaped_exclusions_are_rejected(te):
    """An entry like `--bad-option` was accepted by the allowlist and then parsed by git as a FLAG.

    git exits non-zero, the classifier reports `unavailable`, and `unavailable` fails open by
    design -- so a malformed record in gitignored `.ai-runs/test-runs/` walked straight through
    the gate it was supposed to be stopped by, in `block` mode.
    """
    for entry in ("--bad-option", "-r", "--cached", "-"):
        assert te._is_untrustworthy_exclusion(entry), f"{entry!r} is option-shaped"


def test_the_digest_passes_exclusions_after_a_separator(te):
    """The parser-boundary half of that fix, kept alongside the data-contract half.

    Recorded exclusions are attacker-influenceable: the record declares them and the classifier
    re-applies them. `--` makes the flag-injection class impossible here rather than only where it
    happened to be noticed, and it holds even if the allowlist is later loosened.
    """
    source = inspect.getsource(te.non_ignored_tree_digest)
    assert '"--ignore-unmatch", "--", f":(literal){path}"' in source, (
        "exclusions must be passed after `--` so a path can never be read as an option"
    )


def test_a_malformed_git_block_is_invalid_not_an_outage(te, tmp_path, monkeypatch):
    """`(record.get("git") or {})` handles a null but not a STRING.

    `"oops".get` raises AttributeError, the broad catch in the evaluator converts that to
    `unavailable`, and `unavailable` fails open by design -- so a hand-edited record with a
    malformed shape bypassed the gate in `block` mode. A record whose shape is wrong is
    present-and-untrustworthy, which is what `invalid` means.
    """
    source = inspect.getsource(te.classify_test_run_evidence)
    assert 'isinstance(git_block, dict)' in source, (
        "the git block's shape must be validated inside the classifier, not left to the "
        "fail-open catch outside it"
    )


def test_expected_failure_outcomes_do_not_invalidate_a_green_report(te, tmp_path):
    """A green suite using xfail markers had nothing wrong with it and could not push.

    pytest counts xfailed/xpassed/deselected in `collected` but not in the four buckets, so the
    sum check marked an ordinary report `invalid` and `block` refused it. The invariant is worth
    keeping -- it is what catches a doctored report -- so the outcomes are mapped instead.
    """
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"summary": {
        "collected": 5, "passed": 2, "failed": 0, "skipped": 1, "xfailed": 1, "xpassed": 1,
    }}), encoding="utf-8")
    counts = te.parse_pytest_json_counts(report)
    partition = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"]
    assert partition == counts["collected"], (
        "the mapped outcomes must satisfy the same partition the classifier checks"
    )
    assert counts["passed"] == 3, "xpassed ran and passed"
    assert counts["skipped"] == 2, (
        "xfailed ran and did not pass -- it is not evidence of working code"
    )


def test_deselected_tests_leave_the_denominator(te, tmp_path):
    """A -k filtered run must not look short."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"summary": {
        "collected": 10, "passed": 3, "failed": 0, "skipped": 0, "deselected": 7,
    }}), encoding="utf-8")
    counts = te.parse_pytest_json_counts(report)
    assert counts["collected"] == 3, "deselected tests never ran and are not part of the partition"


def test_the_ledger_guard_does_not_undo_a_fail_open(cli):
    """Mode alone was not enough to keep this guard honest.

    Under `block` the evaluator still fails OPEN on `unavailable` -- a checker outage, such as git
    being unable to resolve the tree. The guard then reloaded the same record and refused it for
    lacking the ledger exclusion, converting an outage into a refusal one line after the gate had
    deliberately let it through. That is the 2026-07-22 startup-gate lockout precedent again: if
    the checker could not tell, neither can this.
    """
    source = inspect.getsource(cli.finalize_implementation_review)
    marker = source.index("excludedPaths")
    guard = source.rindex('condition != "unavailable"', 0, marker)
    assert guard < marker, "the classifier condition must gate the ledger-exclusion refusal"


def test_a_non_utf8_record_is_unreadable_not_an_outage(te, tmp_path):
    """`UnicodeDecodeError` is a `ValueError`, NOT an `OSError`.

    The module already documents this exact trap in `parse_pytest_json_counts` and missed it here.
    A non-UTF-8 newest record escaped the handler, the classifier's broad catch mapped it to
    `unavailable`, and `unavailable` fails open -- so dropping a binary file into gitignored
    `.ai-runs/test-runs/` walked through both gates in `block` mode.
    """
    run_dir = tmp_path / te.TEST_RUN_DIR
    run_dir.mkdir(parents=True)
    (run_dir / "20260101T000000Z-test-run.json").write_bytes(b"\xff\xfe\x00 not utf-8")
    record = te.load_latest_test_run(tmp_path)
    assert record is not None and "__unreadable__" in record, (
        "a present-but-undecodable record is untrustworthy evidence, not a checker outage"
    )


def test_block_remedies_name_the_target_that_was_checked(te):
    """`guard-check --target /some/repo` run from elsewhere printed remedies saying `--target .`,
    which would act on the caller's cwd rather than the lane that was checked."""
    lines = te._remedy_lines("/some/repo")
    assert any("--target /some/repo" in line for line in lines), (
        "the remedy must name the checked target, not the default"
    )
