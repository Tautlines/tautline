import inspect
"""Item 76 WS2: a reviewer response with no `## Findings` section is a FORMAT error.

The incident (`rca-verdict-validator-prompt-echo`): when the heading was absent, the scanner
fell back to the captured review-output block. That block contains the codex CLI's echo of its
own prompt, and the prompt names the severity vocabulary. So the fallback read a genuinely
clean round as carrying findings, and — worse — gave a heading-less log a verdict at all, when
the truth is that an unstructured response is not classifiable in either direction.

Absence of reviewer structure is therefore never license to scan the raw block. It is a format
error with a named remedy.

The remedy ORDER is the part most easily got wrong, and it is asserted here: the wrapper-side
fix comes FIRST, the re-run second. The heading is emitted by the builtin wrapper's prompt, so a
lane pointing `review.codexPlanWrapper` at its own script may have a prompt that never asks for
it — and for that lane a bare re-run reproduces the same log forever. Naming the re-run first
would be a remedy that cannot work, which this codebase has now recorded eight separate times.

Strictness is keyed per-manifest, not globally, and the migration tests below are why: manifests
finalized before this release bound heading-less logs legitimately, because the fallback passed
at finalize time. Re-validating them strictly would retroactively void recorded evidence in
every deployed lane.
"""

HEADING_LESS = "some reviewer prose with no heading\nNo Critical or P1 findings.\n"
WITH_HEADING = "## Findings\n\nNo Critical or P1 findings.\n"


def _errors(cli, log_text, **kwargs):
    params = {"verdict": "clean", "unresolved_critical_count": 0, "unresolved_p1_count": 0}
    params.update(kwargs)
    return cli.review_log_verdict_errors(
        log_text,
        params["verdict"],
        params["unresolved_critical_count"],
        params["unresolved_p1_count"],
        params.get("classified_findings"),
        require_findings_section=params.get("require_findings_section", False),
        rerun_command=params.get("rerun_command", ""),
    )


# --- 1-2. the format error itself ---------------------------------------------------------------


def test_a_heading_less_log_is_a_format_error_when_strict(cli):
    errors = _errors(cli, HEADING_LESS, require_findings_section=True)
    assert errors
    assert "no `## Findings` section" in errors[0]
    assert "reviewer-format error, not a verdict" in errors[0]


def test_it_says_a_raw_scan_is_never_the_fallback(cli):
    """The sentence that names the defect, so the next reader does not re-introduce it."""
    errors = _errors(cli, HEADING_LESS, require_findings_section=True)
    assert "never a fallback" in errors[0]


# --- 3-4. the remedy, and its order -------------------------------------------------------------


def test_the_wrapper_side_remedy_is_named_before_the_rerun(cli):
    """A lane whose own wrapper never asks for the heading gets the same log on every re-run.
    Naming the re-run first would be a remedy that cannot work."""
    message = _errors(cli, HEADING_LESS, require_findings_section=True)[0]
    assert message.index("codexPlanWrapper") < message.index("re-run the round")


def test_the_rerun_command_is_the_callers(cli):
    rerun = "tautline run-plan-review --target . --plan docs/plans/p.md --round R2"
    message = _errors(cli, HEADING_LESS, require_findings_section=True, rerun_command=rerun)[0]
    assert rerun in message


def test_a_missing_rerun_command_still_names_something_runnable(cli):
    message = _errors(cli, HEADING_LESS, require_findings_section=True)[0]
    assert "tautline run-plan-review" in message


def test_the_refusal_hands_nothing_to_a_person(cli):
    message = _errors(cli, HEADING_LESS, require_findings_section=True).pop().lower()
    for phrase in ("escalate", "ask the operator", "ask a human", "wait for the operator"):
        assert phrase not in message, phrase


# --- 5-6. it replaces the verdict rather than adding to it ---------------------------------------


def test_the_format_error_is_the_only_error_returned(cli):
    """Not classifiable means not classifiable: the severity scan must not also run and report
    on a block that is, by definition, unstructured."""
    noisy = "prose naming Critical and P1 everywhere, with no heading at all\n"
    errors = _errors(cli, noisy, require_findings_section=True)
    assert len(errors) == 1
    assert "no `## Findings` section" in errors[0]


def test_a_log_with_the_heading_is_classified_normally(cli):
    """Non-vacuity floor: strictness must not reject the contracted shape."""
    assert _errors(cli, WITH_HEADING, require_findings_section=True) == []


def test_the_severity_scan_still_fires_under_strictness(cli):
    """And the detector it protects must still work: a heading-carrying log that reports a
    Critical while the counts say zero is still caught."""
    log = "## Findings\n\nCritical: a real blocker.\n"
    errors = _errors(cli, log, require_findings_section=True)
    assert errors
    assert "no `## Findings` section" not in errors[0]


# --- 7-8. migration: legacy evidence keeps its own semantics -------------------------------------


def test_lenient_by_default_so_legacy_paths_are_untouched(cli):
    """`require_findings_section` defaults False. Every caller that does not opt in -- including
    record-plan-review's diagnostic import -- behaves exactly as before."""
    assert _errors(cli, HEADING_LESS) == []


def test_the_capability_marker_is_not_a_classifier_bump(cli):
    """The migration hazard, pinned. Bumping PLAN_REVIEW_CLASSIFIER_VERSION would retroactively
    invalidate every manifest in every deployed lane, including the majority whose logs always
    carried the heading. A per-manifest marker opts new evidence in without voiding old.
    """
    assert cli.PLAN_REVIEW_VERDICT_SCAN_CONTRACT == "findings-section/v1"
    assert cli.PLAN_REVIEW_CLASSIFIER_VERSION == "plan-review-classifier/v2", (
        "bumping the classifier version is the obvious-looking move and is exactly what this "
        "item must not do -- see the decision record"
    )


def test_the_precheck_keys_strictness_on_the_manifest_not_the_clock(cli):
    """Structural pin: a legacy manifest carries no `verdict_scan`, so it must keep the
    semantics it was recorded under."""
    import inspect

    source = inspect.getsource(cli.plan_finalization_precheck_errors)
    assert 'manifest.get("verdict_scan") == PLAN_REVIEW_VERDICT_SCAN_CONTRACT' in source


def test_finalize_is_strict_unconditionally_on_the_trusted_path(cli):
    """And the other half of the split: what a lane records NOW must meet the contract, through
    either caller of the shared helper -- finalize-plan-review or run-plan-review --verdict.
    """
    import inspect

    source = inspect.getsource(cli.finalize_trusted_plan_review)
    assert "require_findings_section=True" in source


# --- T2.4: the advisory, so a lane hears it BEFORE it pays for the round -------------------------


def test_a_lane_owned_wrapper_is_warned_at_launch_not_at_finalize(cli):
    """The heading comes from the builtin wrapper's prompt. A lane using its own script owns
    that requirement, and the first it would otherwise hear of it is a finalize-time format
    error on a round it has already paid for."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    assert "plan_review_reviewer_contract:" in source
    advisory = source.index("plan_review_reviewer_contract:")
    acquire = source.index("plan_review_acquire_inflight_lease(")
    assert advisory < acquire, "the advisory is free; it must precede the lease acquisition"


def test_the_advisory_is_not_refusal_shaped(cli):
    """It prints and continues. An advisory that looked like a refusal would be read as one."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    start = source.index("plan_review_reviewer_contract:")
    window = source[start:start + 900]
    assert "_error:" not in window.split("command_errors")[0]
    assert "return 1" not in window.split("command_errors")[0]


def test_the_format_error_recovery_is_not_a_closed_loop(cli, tmp_path, monkeypatch) -> None:
    """Codex R1 P1. `run-plan-review` writes the round's run meta BEFORE the log reaches the
    findings-section check, so a bare re-run of the same round is refused by the duplicate-run
    guard ("finalize that run instead") -- and finalizing is exactly what just failed. Following
    the recovery looped. The log carries no recognisable verdict, so its meta attests nothing and
    removing it loses no evidence; the recovery now names that step and the exact path."""
    meta = tmp_path / ".ai-runs" / "plan-review" / "r1.meta.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text("{}")

    errors = cli.review_log_verdict_errors(
        "no findings heading here",
        "clean",
        0,
        0,
        require_findings_section=True,
        rerun_command=f"rm {meta} && tautline run-plan-review --round 1",
    )

    assert errors, "a heading-less log must still refuse"
    joined = " ".join(errors)
    assert "rm " in joined and str(meta) in joined, "the recovery must name the void step"
    assert "run-plan-review" in joined, "and the command that follows it"


def test_the_finalize_call_site_builds_the_void_step_into_the_recovery(cli, monkeypatch) -> None:
    """The test above proves `review_log_verdict_errors` PROPAGATES whatever recovery it is given.
    This one proves the caller BUILDS the right one -- a distinction mutation testing caught: a
    mutant that dropped the `rm` from the call site left that test green, because it never touched
    the call site at all."""
    captured = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return ["plan_review_run_error: no findings section"]

    monkeypatch.setattr(cli, "review_log_verdict_errors", _capture)

    source = inspect.getsource(cli.finalize_trusted_plan_review)

    assert "rm {shlex.quote(str(run_meta_path))} " in source, (
        "the finalize call site must build the void step into the recovery it hands over; "
        "without it the recovery points at a round the duplicate-run guard refuses"
    )
    assert "run_meta_path" in source
