"""Item 74 WS3 (PR-B): a Critical/P1-origin deferral carries a rationale and a criterion.

The gap: `status: "deferred"` was the cheapest escape on the review record. Nothing asked WHY a
Critical was non-blocking or WHAT criterion it was judged non-blocking against, so relabelling a
blocker to `deferred` was indistinguishable from resolving it -- and the finding-3 hole meant
`clean-with-deferrals` with `classified_findings: []` bypassed the whole rule, one omitted
optional flag wide.

v1 of this plan made two fields mandatory with no producer, no schema and no documentation.
This ships the producer side in the same PR: the guard that refuses the verdict without the flag
(T3.0/T3.2 site 3), the doc section every refusal cites, and the help text on both parsers.

Every rule here gates on `CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION` -- the SAME constant item
73's AC-traceability rules use (packet W1.1, S1 / operator DECISION 2), never a second one.
"""

from _classified_findings_fixtures import (
    adapter,
    assert_legacy_version_is_below_contract,
    finalize,
    lane,
    legacy_plugin_version,
    plan_precheck_errors,
)

CRITICAL_NO_RATIONALE = {
    "id": "F1",
    "severity": "critical",
    "status": "deferred",
    "summary": "unbounded retry",
}
CRITICAL_RATIONALE_ONLY = {
    **CRITICAL_NO_RATIONALE,
    "deferral_rationale": "the retry path is unreachable until the flag ships",
}
CRITICAL_COMPLIANT = {
    **CRITICAL_RATIONALE_ONLY,
    "acceptance_criterion": "AC4: the export completes within the throttle ceiling",
}


ROUTED_NO_RATIONALE = {
    **CRITICAL_NO_RATIONALE,
    "ac_ref": None,
    "disposition": "routed",
    "routed_to": "ROW-2",
}
ROUTED_COMPLIANT = {
    **CRITICAL_COMPLIANT,
    "ac_ref": None,
    "disposition": "routed",
    "routed_to": "ROW-2",
}


def _deferral_errors(cli, findings):
    return cli.critical_origin_deferral_errors(findings)


# --- 1 + 2. both validators refuse a rationale-less deferred blocker ---------------------------


def test_plan_manifest_critical_deferral_without_rationale_refused(cli, tmp_path):
    errors = plan_precheck_errors(cli, tmp_path, [CRITICAL_NO_RATIONALE])
    assert any("deferral_rationale" in error for error in errors), errors


def test_impl_manifest_critical_deferral_without_rationale_refused(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[ROUTED_NO_RATIONALE],
    )
    assert rc == 1
    assert "deferral_rationale" in capsys.readouterr().err


# --- 3. the criterion is required too, and a rationale must say something ----------------------


def test_missing_acceptance_criterion_refused(cli, tmp_path):
    errors = _deferral_errors(cli, [CRITICAL_RATIONALE_ONLY])
    assert any("acceptance_criterion" in error for error in errors), errors
    assert not any("deferral_rationale" in error for error in errors), errors
    # The same rule reaches the plan-review path.
    plan_errors = plan_precheck_errors(cli, tmp_path, [CRITICAL_RATIONALE_ONLY])
    assert any("acceptance_criterion" in error for error in plan_errors), plan_errors


def test_a_token_rationale_does_not_satisfy_the_rule(cli):
    errors = _deferral_errors(cli, [{**CRITICAL_NO_RATIONALE, "deferral_rationale": "later"}])
    assert any("deferral_rationale" in error for error in errors), errors


def test_every_refusal_names_the_key_and_the_doc(cli):
    """No literal-phrase archaeology: each error names the exact JSON key and where it is
    documented, so the agent reading it can write the field without reading the source."""
    errors = _deferral_errors(cli, [CRITICAL_NO_RATIONALE])
    assert errors
    for error in errors:
        assert "docs/reference/operations/cli-operations.md" in error, error


# --- 4. the contract binds Critical/P1 origin only --------------------------------------------


def test_both_fields_present_accepted(cli):
    assert _deferral_errors(cli, [CRITICAL_COMPLIANT]) == []


def test_deferred_p2_unchanged(cli, tmp_path):
    """Relabel-to-escape is the target, not ceremony: a deferred P2 owes nothing new."""
    p2 = {"id": "F2", "severity": "p2", "status": "deferred", "summary": "naming nit"}
    assert _deferral_errors(cli, [p2]) == []
    assert not any(
        "deferral_rationale" in error for error in plan_precheck_errors(cli, tmp_path, [p2])
    )
    # Non-vacuity floor: an absence assertion over a fixture that never reaches the rule is green
    # for the wrong reason. Prove the same fixture DOES refuse when the finding is blocker-origin.
    assert any(
        "deferral_rationale" in error
        for error in plan_precheck_errors(cli, tmp_path, [CRITICAL_NO_RATIONALE])
    )


# --- 5. the finding-3 hole ---------------------------------------------------------------------


def test_impl_clean_with_deferrals_requires_nonempty_classified_findings(cli, tmp_path):
    """Without this the Critical-origin check iterates an empty list and refuses nothing."""
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(classified_findings=[])
    errors = subject.manifest_errors(cli)
    assert any(
        "clean-with-deferrals requires" in error and "classified_findings" in error
        for error in errors
    ), errors


def test_a_recorded_deferred_critical_is_validated_on_the_manifest_too(cli, tmp_path):
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(classified_findings=[CRITICAL_NO_RATIONALE])
    assert any("deferral_rationale" in error for error in subject.manifest_errors(cli))


def test_require_classification_false_is_unaffected(cli, tmp_path):
    """The finalize path calls this validator with require_classification=False before it has a
    classification at all. The new rule must not fire there, or finalize refuses itself."""
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(classified_findings=[])
    errors = subject.manifest_errors(cli, require_classification=False)
    assert not any("clean-with-deferrals requires" in error for error in errors), errors


# --- 6. the producer guard ---------------------------------------------------------------------


def test_finalize_impl_review_refuses_deferrals_verdict_without_findings_json(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals")
    assert rc == 1
    err = capsys.readouterr().err
    assert "--classified-findings-json" in err
    assert "deferral_rationale" in err and "acceptance_criterion" in err
    assert "docs/reference/operations/cli-operations.md" in err
    # Refuses BEFORE the manifest is written.
    assert "classification_status" not in subject.manifest()


def test_the_producer_guard_also_refuses_an_empty_array(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path)
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=[])
    assert rc == 1
    assert "--classified-findings-json" in capsys.readouterr().err


def test_the_producer_guard_is_not_version_gated(cli, monkeypatch, capsys, tmp_path):
    """It runs in the CURRENT CLI by definition -- there is no legacy producer to be tolerant of."""
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals")
    assert rc == 1
    assert "--classified-findings-json" in capsys.readouterr().err


def test_clean_without_findings_is_untouched(cli, monkeypatch, capsys, tmp_path):
    """The guard binds `clean-with-deferrals` only: a clean review with nothing to report is
    still the cheapest thing to record."""
    subject = lane(cli, tmp_path)
    assert finalize(cli, monkeypatch, subject, verdict="clean") == 0, capsys.readouterr().err


# --- 7. migration tolerance, on the ONE constant -----------------------------------------------


def test_legacy_plugin_version_manifest_exempt(cli, monkeypatch, capsys, tmp_path):
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[CRITICAL_NO_RATIONALE],
    )
    assert rc == 0, capsys.readouterr().err


def test_absent_plugin_version_stays_strict(cli, monkeypatch, capsys, tmp_path):
    subject = lane(cli, tmp_path, plugin_version=None)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[ROUTED_NO_RATIONALE],
    )
    assert rc == 1
    assert "deferral_rationale" in capsys.readouterr().err


def test_the_empty_findings_rule_shares_that_tolerance(cli, tmp_path):
    assert_legacy_version_is_below_contract(cli)
    subject = lane(cli, tmp_path, plugin_version=legacy_plugin_version(cli))
    subject.classify(classified_findings=[])
    errors = subject.manifest_errors(cli)
    assert not any("clean-with-deferrals requires" in error for error in errors), errors


# --- 8. the ledger surface (T3.3) --------------------------------------------------------------


def test_status_prints_critical_deferral_lines_without_changing_exit(
    cli,
    monkeypatch,
    capsys,
    tmp_path,
):
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[ROUTED_COMPLIANT],
    )
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()
    lines = cli.critical_deferral_status_lines(adapter(), subject.target)
    assert lines and any("critical_deferral:" in line for line in lines), lines
    assert any("the retry path is unreachable" in line for line in lines), lines


def test_the_ledger_surface_is_report_only(cli, tmp_path):
    """A ledger surface, not a gate. Per finding 3 it is explicitly NOT the thing standing
    between an empty findings array and a green push -- the producer guard and the manifest
    validator are. An exception or a nonzero exit from here would be a second, weaker gate."""
    empty = tmp_path / "no-lane"
    empty.mkdir()
    assert cli.critical_deferral_status_lines(adapter(), empty) == []


def test_status_scan_survives_unreadable_evidence(cli, tmp_path):
    subject = lane(cli, tmp_path)
    evidence_dir = cli.implementation_review_evidence_dir(subject.target)
    (evidence_dir / "broken.json").write_text("{not json", encoding="utf-8")
    assert cli.critical_deferral_status_lines(adapter(), subject.target) == []


def test_methodology_status_exit_is_unchanged_by_the_lines(cli):
    """The lines are printed by `methodology-status`; they never participate in its exit code.

    Pinned at the source, because the failure this guards against is a future edit that folds the
    scan into a return path -- which no output assertion would catch.
    """
    import inspect

    source = inspect.getsource(cli.print_critical_deferral_status)
    assert "return 1" not in source
    assert "return 2" not in source


# --- the composed contract: two rule families, one record ---------------------------------------


def test_a_deferred_blocker_is_told_how_to_dispose_of_itself(cli, monkeypatch, capsys, tmp_path):
    """The bridge rule (packet W1.1, S3). `status` and `disposition` are separate axes, and a
    deferred blocker with no disposition would otherwise read as caught between two gates."""
    subject = lane(cli, tmp_path)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[{**CRITICAL_COMPLIANT, "ac_ref": None}],
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "disposition" in err
    assert "routed_to" in err
    assert "fixed/refuted" in err


# --- Codex R1 P2: the producer refuses before it writes -----------------------------------------


def test_every_plan_review_writer_refuses_an_invalid_deferral_before_writing(cli):
    """The precheck READS the manifest, so enforcement there alone arrives one command too late:
    the lane has already written the file it will be told is invalid. Both writers -- the shared
    run/finalize path and the import path -- refuse at the producer.
    """
    import inspect

    for writer in (cli.finalize_trusted_plan_review, cli.record_plan_review):
        source = inspect.getsource(writer)
        assert "critical_origin_deferral_errors" in source, writer.__name__


def test_a_recorded_non_object_finding_is_refused_not_filtered(cli, tmp_path):
    """Codex R4 P2, at the manifest validator: `[1]` must not satisfy the non-empty rule."""
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(classified_findings=[1])
    errors = subject.manifest_errors(cli)
    assert any("must be objects" in error for error in errors), errors


def test_a_desynced_verdict_and_status_cannot_skip_the_non_empty_rule(cli, tmp_path):
    """Codex R2 P2 on the record-contract diff. The manifest carries two fields the finalizer
    always writes identically; keying the rule off one of them made the other the bypass."""
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(
        classification_status="clean", verdict="clean-with-deferrals", classified_findings=[]
    )
    errors = subject.manifest_errors(cli)
    assert any("clean-with-deferrals requires" in error for error in errors), errors
    assert any("disagree" in error for error in errors), errors


def test_the_matched_pair_is_still_accepted(cli, tmp_path):
    """Non-vacuity floor: the agreement rule must not reject what the finalizer actually writes."""
    subject = lane(cli, tmp_path, plugin_version=cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION)
    subject.classify(
        classification_status="clean-with-deferrals",
        verdict="clean-with-deferrals",
        classified_findings=[CRITICAL_COMPLIANT],
    )
    assert not any("disagree" in error for error in subject.manifest_errors(cli))
