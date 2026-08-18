"""Item 73 WS2: the recorded counts can never silently diverge from the review log.

The incident: a round whose log carried **3 Critical and 22 Important** findings was finalized at
0 unresolved Critical / 0 unresolved P1, and nothing on the implementation path read the log to
notice. `review_log_verdict_errors` already detected exactly that -- in both real log formats, and
hardened over several rounds -- on the PLAN-review path. It was simply never wired into this
consumer. WS2 wires it and does not touch it.

The fixture logs below reproduce the two formats from the incident and are not invented: a
`## Findings` section with markdown-link findings and em-dash severities, and one with
backticked-path findings and bold severities. A detector tested only against the format its author
happened to imagine is a detector that passes its own suite and misses the incident.
"""

from _classified_findings_fixtures import finalize, lane, legacy_plugin_version


# --- the two real log formats -------------------------------------------------------------------

EM_DASH_LOG = """# Codex review run

## Findings

- [src/exporter/throttle.py:88](src/exporter/throttle.py#L88) — Critical — unbounded retry loop
  re-enters the queue without a ceiling.
- [src/exporter/throttle.py:140](src/exporter/throttle.py#L140) — Critical — the drain path
  swallows the cancellation signal.
- [src/exporter/queue.py:31](src/exporter/queue.py#L31) — Critical — depth counter is read after
  the mutation that invalidates it.
- [src/exporter/queue.py:64](src/exporter/queue.py#L64) — Important — the retry budget is not
  reset between batches.

Verdict: changes requested
"""

BOLD_LOG = """# Codex review run

## Findings

- `src/exporter/throttle.py:88` **Critical** unbounded retry loop re-enters the queue without a
  ceiling.
- `src/exporter/throttle.py:140` **Critical** the drain path swallows the cancellation signal.
- `src/exporter/queue.py:31` **Critical** depth counter is read after the mutation that
  invalidates it.
- `src/exporter/queue.py:64` **Important** the retry budget is not reset between batches.
"""

LOG_FORMATS = {"em-dash": EM_DASH_LOG, "bold": BOLD_LOG}


def _err(capsys):
    return capsys.readouterr().err


def _crosscheck_reported(err: str) -> bool:
    """The cross-check REPORTS; it does not refuse.

    `review_log_verdict_errors` was built for a structured `## Findings` section, where a line
    mentioning Critical IS a finding. This path feeds it free-form reviewer prose, where it is
    not -- "The critical retry path is covered by tests." reads as blocker evidence. Four rounds each
    found another ordinary English sentence that would refuse an honest review, so the divergence is
    printed and enforcement waits for a structured reviewer signal.
    """
    return "recorded unresolved counts are zero" in err


def _crosscheck_silent(err: str) -> bool:
    return not _crosscheck_reported(err)


# --- 1. the incident itself, in both formats -----------------------------------------------------


def test_zero_counts_over_a_blocker_carrying_log_are_refused_in_both_formats(
    cli, monkeypatch, capsys, tmp_path
):
    """The 0C/0I-for-3C/22I regression, once per real format."""
    for name, log_text in LOG_FORMATS.items():
        subject = lane(cli, tmp_path / name, log_text=log_text)
        rc = finalize(cli, monkeypatch, subject, verdict="clean")
        err = _err(capsys)
        assert rc == 0, f"{name}: report-only must not refuse -- {err}"
        assert _crosscheck_reported(err), f"{name}: {err}"
        assert "REPORT-ONLY" in err, name
        # No dead ends: both honest exits are still named and runnable.
        assert "--verdict blocked" in err, name
        assert "routed_to" in err, name


# --- 2. the escape, with the disposition vocabulary this contract created ------------------------


def test_every_blocker_disposed_of_finalizes(cli, monkeypatch, capsys, tmp_path):
    """Honest routing must not re-trigger the block, or the contract fights itself.

    `routed` + `routed_to` is the vocabulary item 73's WS1 shipped; if the escape did not accept
    it, every legitimately-routed out-of-AC finding would read as a divergence.
    """
    subject = lane(cli, tmp_path, log_text=EM_DASH_LOG)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[
            {
                "id": "F1",
                "severity": "critical",
                "summary": "retry loop",
                "ac_ref": "AC1",
                "disposition": "fixed",
            },
            {
                "id": "F2",
                "severity": "critical",
                "summary": "drain path",
                "ac_ref": "AC1",
                "disposition": "fixed",
            },
            {
                "id": "F3",
                "severity": "critical",
                "summary": "depth counter",
                "ac_ref": "AC2",
                "disposition": "refuted",
            },
            {
                "id": "F4",
                "severity": "important",
                "summary": "retry budget",
                "ac_ref": None,
                "disposition": "routed",
                "routed_to": "ROW-1",
            },
        ],
    )
    assert rc == 0, _err(capsys)
    assert subject.manifest()["classification_status"] == "clean-with-deferrals"


# --- 3. the reopened-hole regression -------------------------------------------------------------


def test_one_routed_finding_cannot_suppress_unclassified_criticals(
    cli, monkeypatch, capsys, tmp_path
):
    """THE test this workstream exists for, in both formats -- and it needed a LEGACY manifest.

    The shipped any-one escape returns True as soon as a SINGLE blocker carries a resolving status,
    and that one True then suppresses EVERY suspicious line in the log. Reusing it on this path
    would reopen the incident's divergence class.

    Reaching that state through the verb takes care, and finding out why is worth recording: on a
    CURRENT manifest, WS1's contract refuses an unclassified blocker before the cross-check ever
    runs, so the mix is unreachable there. It is reachable on a LEGACY manifest, where the field
    requirement is tolerated by design -- which is precisely the population that predates the
    contract and most needs the log reconciled. A version of this test written against a current
    manifest would have failed for the right reason and been "fixed" by weakening it.
    """
    # One honestly-disposed-of blocker, three Criticals in the log with nothing recorded for them.
    mixed = [
        {
            "id": "F1",
            "severity": "critical",
            "summary": "retry loop",
            "status": "fixed",
            "ac_ref": "AC1",
            "disposition": "fixed",
        },
        {
            "id": "F4",
            "severity": "important",
            "summary": "retry budget",
            "ac_ref": None,
            "disposition": "routed",
            "routed_to": "ROW-1",
        },
        {
            "id": "F9",
            "severity": "critical",
            "summary": "drain path",
            "ac_ref": "AC1",
            "disposition": "fixed",
        },
        # The unaccounted-for blocker. No status, no disposition -- exactly what a pre-contract
        # record looks like, and exactly what the log's third Critical corresponds to.
        {"id": "F10", "severity": "critical", "summary": "depth counter"},
    ]
    # The premise, asserted rather than assumed. Under the SHIPPED any-one semantics this list IS
    # evidence -- one `status: fixed` blocker is enough, and it then suppresses EVERY suspicious
    # line including the unclassified F10. Without this assertion the test could pass because the
    # helper changed meaning rather than because the mode switch works.
    assert cli.classified_findings_have_resolved_blocker_evidence(mixed) is True
    assert cli.classified_findings_all_blockers_resolved(mixed) is False

    for name, log_text in LOG_FORMATS.items():
        subject = lane(
            cli,
            tmp_path / f"mixed-{name}",
            log_text=log_text,
            plugin_version=legacy_plugin_version(cli),
        )
        rc = finalize(
            cli,
            monkeypatch,
            subject,
            verdict="clean-with-deferrals",
            findings=mixed,
        )
        err = _err(capsys)
        assert rc == 0, f"{name}: report-only must not refuse"
        assert _crosscheck_reported(err), f"{name}: {err}"


def test_the_disposition_vocabulary_is_only_evidence_under_all_blockers(cli):
    """A boundary the plan predicted and the shipped code does not yet cross, pinned so it stays so.

    The any-one helper reads `status` ONLY -- a finding disposed of purely by the `disposition`
    vocabulary WS1 introduced is invisible to it. That is why extending that helper to read
    `disposition`, rather than adding a separate all-blockers helper, would have reopened the hole:
    routing is routine on this path, so every routed finding would instantly become a blanket
    suppressor. The two helpers must keep disagreeing here.
    """
    routed_only = [
        {
            "severity": "important",
            "summary": "retry budget",
            "disposition": "routed",
            "routed_to": "ROW-1",
        }
    ]
    assert cli.classified_findings_have_resolved_blocker_evidence(routed_only) is False
    assert cli.classified_findings_all_blockers_resolved(routed_only) is True


def test_a_routed_finding_without_a_destination_is_not_disposed_of(
    cli, monkeypatch, capsys, tmp_path
):
    """Routed with nowhere to route to is dropped, not routed."""
    subject = lane(cli, tmp_path, log_text=EM_DASH_LOG)
    rc = finalize(
        cli,
        monkeypatch,
        subject,
        verdict="clean-with-deferrals",
        findings=[
            {
                "id": "F1",
                "severity": "critical",
                "summary": "retry loop",
                "ac_ref": None,
                "disposition": "routed",
            }
        ],
    )
    assert rc == 1
    assert "routed_to" in _err(capsys)


def test_an_empty_findings_list_is_never_evidence(cli, monkeypatch, capsys, tmp_path):
    """Suspicious lines with NO recorded blocker findings are the divergence, not an excuse.

    Treating "nothing recorded" as "nothing to reconcile" makes the check vacuous exactly when it
    matters most -- the incident's own shape was a log full of blockers and a record with none.
    """
    subject = lane(cli, tmp_path, log_text=EM_DASH_LOG)
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    assert rc == 0
    assert _crosscheck_reported(_err(capsys))


# --- 4. the log must be the log the round recorded -----------------------------------------------


def test_a_log_that_no_longer_matches_its_sha_fails_closed(cli, monkeypatch, capsys, tmp_path):
    """A log whose bytes drifted from the manifest is not evidence of anything.

    The cross-check does not re-verify this itself, and that is deliberate: the base manifest
    validator ALREADY refuses a drifted log, for every verdict, before this block runs. Adding a
    second check here was dead code -- unreachable, therefore shipped untested while reading as
    guarded. This test pins the dependency so it is recorded rather than assumed, and so a future
    change that moves the base check cannot silently leave the cross-check reading a tampered log.
    """
    subject = lane(cli, tmp_path)
    subject.unpin_log(EM_DASH_LOG)
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    err = _err(capsys)
    assert rc == 1
    assert "log_sha256 does not match current log file" in err
    # It must fail on the DRIFT, before ever reconciling against the altered bytes.
    assert not _crosscheck_reported(err), err


def test_a_re_pinned_log_is_read_normally(cli, monkeypatch, capsys, tmp_path):
    """The sha guard must gate on DRIFT, not merely on the log having been written.

    Without this, a guard that always refused would pass the test above for the wrong reason.
    """
    subject = lane(cli, tmp_path)
    subject.rewrite_log(cli, EM_DASH_LOG)
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    err = _err(capsys)
    assert rc == 0
    assert "no longer matches" not in err
    assert _crosscheck_reported(err)


def test_a_manifest_naming_a_missing_log_refuses(cli, monkeypatch, capsys, tmp_path):
    """Same dependency, other half: the base validator owns log existence too."""
    subject = lane(cli, tmp_path)
    subject.log_path.unlink()
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    err = _err(capsys)
    assert rc == 1
    assert "log missing:" in err


# --- 5. blocked stays the cheapest honest verdict ------------------------------------------------


def test_blocked_never_runs_the_crosscheck(cli, monkeypatch, capsys, tmp_path):
    """Every gate on this path keeps `blocked` free to RECORD, and this one is no exception.

    `blocked` exits 1 by design -- that is the verb reporting that review found something, not a
    refusal -- so the property under test is that the manifest is WRITTEN and no cross-check error
    is printed. Making honest reporting expensive is how a lane learns to record a dishonest
    verdict instead.
    """
    for name, log_text in LOG_FORMATS.items():
        subject = lane(cli, tmp_path / f"blocked-{name}", log_text=log_text)
        finalize(cli, monkeypatch, subject, verdict="blocked", critical=3, p1=22)
        err = _err(capsys)
        assert not _crosscheck_reported(err), f"{name}: {err}"
        assert subject.manifest()["verdict"] == "blocked", name
        assert subject.manifest()["unresolved_critical_count"] == 3, name


def test_blocked_with_zero_counts_still_never_runs_the_crosscheck(
    cli, monkeypatch, capsys, tmp_path
):
    """Even the shape that looks most like the incident -- blocked at 0/0 over a blocker log."""
    subject = lane(cli, tmp_path, log_text=EM_DASH_LOG)
    finalize(cli, monkeypatch, subject, verdict="blocked")
    assert not _crosscheck_reported(_err(capsys))
    assert subject.manifest()["verdict"] == "blocked"


# --- 6. the clean baseline must stay clean -------------------------------------------------------


def test_a_blocker_free_log_finalizes_clean(cli, monkeypatch, capsys, tmp_path):
    """Non-vacuity floor: if the cross-check refused everything, every test above would pass."""
    subject = lane(cli, tmp_path)
    assert finalize(cli, monkeypatch, subject, verdict="clean") == 0, _err(capsys)
    assert subject.manifest()["classification_status"] == "clean"


def test_the_plan_review_call_sites_keep_any_one_semantics(cli):
    """The three plan-review callers must be behavior-identical: they pass no `blocker_evidence`.

    Their escape is the shipped any-one helper, and this workstream deliberately left that helper
    and `plan_review_resolved_statuses` byte-for-byte alone. A default that silently changed under
    them would be this change breaking a surface it never reviewed.
    """
    # BOLD_LOG, not EM_DASH_LOG: the latter also carries an explicit `Verdict: changes requested`
    # line, which trips a DIFFERENT (and correct) error and would mask the one under test.
    log = BOLD_LOG
    one_resolved = [{"severity": "critical", "status": "fixed", "summary": "retry loop"}]
    # The plan-review default: ONE resolved blocker is evidence, and that stays true.
    assert cli.review_log_verdict_errors(log, "clean", 0, 0, one_resolved) == []
    # The implementation path refuses the same input, and for a reason the plan-review path does not
    # ask about: the log also shows an Important, and the classification accounts for no Important.
    assert (
        cli.review_log_verdict_errors(log, "clean", 0, 0, one_resolved, blocker_evidence="all")
        != []
    )
    # Account for every class the log shows, and it finalizes.
    covered = one_resolved + [
        {"severity": "important", "disposition": "routed", "routed_to": "ROW-1"}
    ]
    assert (
        cli.review_log_verdict_errors(log, "clean", 0, 0, covered, blocker_evidence="all") == []
    )
    mixed = one_resolved + [{"severity": "critical", "summary": "unclassified"}]
    assert cli.review_log_verdict_errors(log, "clean", 0, 0, mixed) == []
    assert cli.review_log_verdict_errors(log, "clean", 0, 0, mixed, blocker_evidence="all") != []


def test_the_wired_path_reports_both_incident_formats_identically(
    cli, monkeypatch, capsys, tmp_path
):
    """The review gate for T2.2: run both incident fixtures through the WIRED path, not the helper.

    A helper-level test proves the detector works; this proves it is reachable from the verb.
    """
    messages = {}
    for name, log_text in LOG_FORMATS.items():
        subject = lane(cli, tmp_path / f"wired-{name}", log_text=log_text)
        assert finalize(cli, monkeypatch, subject, verdict="clean") == 0
        messages[name] = [line for line in _err(capsys).splitlines() if _crosscheck_reported(line)]
    assert messages["em-dash"] == messages["bold"] != []


# --- 7. the implementation log is a TRANSCRIPT, not a plan-review log ---------------------------
# Codex R1 P1, and the most expensive defect this workstream could have shipped. An implementation
# review log is the whole `codex review` CLI transcript -- prompt echo, every tool invocation, the
# full source diff -- and it carries no `## Findings` heading, because that heading is a contract of
# the builtin PLAN-review wrapper's prompt, not of `codex review`.
#
# Measured on a real 751,076-byte log from this branch: the findings section is 0 characters and the
# fallback scope is all 751,076. The transcript quotes source containing the word "Critical" and
# fixtures containing "Verdict: changes requested", so the scan fired and a genuinely CLEAN review
# could not be finalized. Wiring the plan-review call shape unchanged would have made EVERY
# implementation review in the fleet unfinalizable -- a false refusal on the push boundary.

CODEX_TRANSCRIPT_CLEAN = """OpenAI Codex v0.144.5
--------
workdir: /repo
--------
user
changes against 'origin/experimental'

exec
/bin/zsh -lc 'git diff' in /repo
 succeeded in 0ms:
+    if severity == "critical" or severity == "p1":
+        errors.append("Critical finding recorded")
+# Verdict: changes requested   <- quoted from a test fixture, not this reviewer's verdict

exec
/bin/zsh -lc 'sed -n 1,40p tests/test_x.py' in /repo
 succeeded in 0ms:
- [src/a.py:1] — Critical — an example from another round's log

codex
No issues found. The change is well covered by tests.
"""

CODEX_TRANSCRIPT_WITH_FINDINGS = """OpenAI Codex v0.144.5
--------
user
changes against 'origin/experimental'

exec
/bin/zsh -lc 'git diff' in /repo
 succeeded in 0ms:
+    harmless = True

codex
The change drops a bounds check.

Full review comments:

- [Critical] Unbounded retry loop — src/exporter/throttle.py:88
  The drain path re-enters the queue without a ceiling.
"""


def test_a_transcript_body_full_of_severity_words_does_not_refuse_a_clean_review(
    cli, monkeypatch, capsys, tmp_path
):
    """THE false-refusal regression. The body mentions Critical; the reviewer's answer is clean."""
    subject = lane(cli, tmp_path, log_text=CODEX_TRANSCRIPT_CLEAN)
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    err = _err(capsys)
    assert rc == 0, err
    assert not _crosscheck_reported(err), err
    assert subject.manifest()["classification_status"] == "clean"


def test_a_transcript_whose_answer_reports_blockers_still_refuses(
    cli, monkeypatch, capsys, tmp_path
):
    """Non-vacuity floor for the test above: scoping must not disarm the check.

    Without this, narrowing the scope to nothing would satisfy the regression and silently delete
    the control -- which is the defect class this whole cluster is about.
    """
    subject = lane(cli, tmp_path, log_text=CODEX_TRANSCRIPT_WITH_FINDINGS)
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    assert rc == 0
    assert _crosscheck_reported(_err(capsys))


def test_the_scope_prefers_a_findings_section_when_one_exists(cli):
    """Plan-review-shaped logs keep their existing scope; only the fallback changed."""
    scan, source = cli.implementation_review_scan_text(EM_DASH_LOG)
    assert source == "findings-section"
    assert "unbounded retry loop" in scan.lower()


def test_the_scope_falls_back_to_the_codex_final_response(cli):
    scan, source = cli.implementation_review_scan_text(CODEX_TRANSCRIPT_WITH_FINDINGS)
    assert source == "codex-final-response"
    assert "drops a bounds check" in scan
    # The transcript body must be gone, or the fallback bought nothing.
    assert "git diff" not in scan


def test_an_unlocatable_answer_skips_LOUDLY_rather_than_refusing_everything(
    cli, monkeypatch, capsys, tmp_path
):
    """A deliberate fail-open, and the direction is argued rather than assumed.

    Scanning the raw transcript refuses 100% of genuine logs (measured), so "fail closed" here means
    closed to everyone -- not a gate but a fleet-wide wedge, on a boundary whose input format this
    repo does not control. The skip is PRINTED: a quiet skip is indistinguishable from a clean
    reconciliation, which is the exact defect class this cluster exists to close.
    """
    subject = lane(cli, tmp_path, log_text="a log with no findings section and no speaker marker\n")
    rc = finalize(cli, monkeypatch, subject, verdict="clean")
    err = _err(capsys)
    assert rc == 0, err
    assert "implementation_review_log_crosscheck: skipped" in err
    assert "were NOT reconciled" in err


def test_the_real_shaped_transcript_is_measurably_smaller_after_scoping(cli):
    """The scope must actually shrink the input, not merely rename it."""
    scan, _source = cli.implementation_review_scan_text(CODEX_TRANSCRIPT_CLEAN)
    assert len(scan) < len(CODEX_TRANSCRIPT_CLEAN) / 4
    assert "Verdict: changes requested" not in scan
    assert "Critical" not in scan


# --- 8. Codex R2: three ways the reconciliation was still wrong ----------------------------------

TRANSCRIPT_WITH_ECHOED_FINDINGS_HEADING = """user
changes against 'origin/experimental'

exec
/bin/zsh -lc 'sed -n 1,20p tests/test_plan_review.py' in /repo
 succeeded in 0ms:
## Findings
- [src/a.py:1] Critical - an example quoted from ANOTHER round's log
Verdict: changes requested

codex
No issues found. The change is well covered by tests.
"""


def test_an_echoed_findings_heading_does_not_beat_the_reviewers_answer(
    cli, monkeypatch, capsys, tmp_path
):
    """Codex R2 P1. Order matters, and getting it backwards reproduced the bug being fixed.

    This repo's own plan-review code and fixtures contain `## Findings`, so a transcript that
    inspected one had that ECHOED heading chosen over the reviewer's actual answer. The final
    speaker marker wins whenever it exists; the findings section is the fallback for logs that are
    not codex transcripts at all.
    """
    scan, source = cli.implementation_review_scan_text(TRANSCRIPT_WITH_ECHOED_FINDINGS_HEADING)
    assert source == "codex-final-response"
    assert "Critical" not in scan
    assert "Verdict: changes requested" not in scan

    subject = lane(cli, tmp_path, log_text=TRANSCRIPT_WITH_ECHOED_FINDINGS_HEADING)
    assert finalize(cli, monkeypatch, subject, verdict="clean") == 0, _err(capsys)


def test_blockers_omitted_from_the_json_entirely_cannot_be_masked(
    cli, monkeypatch, capsys, tmp_path
):
    """Codex R2 P1 -- the same hole one level up, and the sharpest one in this workstream.

    `classified_findings_all_blockers_resolved` only ever inspects findings the classification file
    SUPPLIED. A log carrying Criticals alongside a JSON carrying one routed Important returned "all
    resolved": one routed finding masking blockers that were simply left out. The escape now also
    requires the classification to ACCOUNT FOR every blocker class the log shows.
    """
    one_routed = [
        {
            "id": "F4",
            "severity": "important",
            "summary": "retry budget",
            "ac_ref": None,
            "disposition": "routed",
            "routed_to": "ROW-1",
        }
    ]
    # The premise: the supplied list IS internally all-resolved. The gap is what it omits.
    assert cli.classified_findings_all_blockers_resolved(one_routed) is True

    subject = lane(cli, tmp_path, log_text=EM_DASH_LOG, plugin_version=legacy_plugin_version(cli))
    rc = finalize(cli, monkeypatch, subject, verdict="clean-with-deferrals", findings=one_routed)
    assert rc == 0, "report-only must not refuse"
    assert _crosscheck_reported(_err(capsys))


def test_class_coverage_is_satisfied_when_every_observed_class_is_recorded(cli):
    """Non-vacuity floor: coverage must be satisfiable, or the escape is simply deleted."""
    findings = [
        {"severity": "critical", "disposition": "fixed"},
        {"severity": "important", "disposition": "routed", "routed_to": "ROW-1"},
    ]
    covered = cli.classified_findings_cover_blocker_classes(findings, {"critical", "important"})
    assert covered is True
    # `important` collapses into the P1 class, so ask for one genuinely absent.
    absent = cli.classified_findings_cover_blocker_classes([{"severity": "important"}], {"critical"})
    assert absent is False
    # No observed classes is not a gap -- there is nothing to account for.
    assert cli.classified_findings_cover_blocker_classes([], set()) is True


def test_ordinary_reviewer_prose_never_refuses_a_clean_round(cli):
    """Codex R3 P1, and the reason the P0/High alias widening was REMOVED rather than patched.

    A widened alias set was written to close a real gap and then taken back out: under a bare-word
    match, "the tests provide high confidence" reads as a P1 finding and refuses a clean round on
    the push boundary. That is worse than the gap it closes, and matching `High` safely needs
    severity POSITIONS rather than word presence -- design this item's round budget cannot confirm.
    """
    for clean_answer in (
        "No issues found. The tests provide high confidence in the change.",
        "Looks good. Coverage is high and the risk is low.",
        "No P0 findings.",
        "High: none.",
    ):
        errors = cli.review_log_verdict_errors(
            clean_answer, "clean", 0, 0, [], blocker_evidence="all"
        )
        assert errors == [], clean_answer


def test_the_p0_and_high_gap_is_a_known_residual(cli):
    """Asserting the GAP, so closing it is a deliberate change and not an accident.

    `finding_counts` and `BLOCKER_SEVERITIES` classify p0 as Critical and high as P1; this scan
    recognizes neither. The successor that closes it will turn these assertions around, which is the
    point of pinning them.
    """
    assert cli.blocker_class_of("p0") == "critical"
    assert cli.blocker_class_of("high") == "p1"
    assert (
        cli.review_log_verdict_errors(
            "## Findings\n- [P0] unbounded retry loop", "clean", 0, 0, [], blocker_evidence="all"
        )
        == []
    )


def test_the_two_modes_stay_aligned_on_the_severities_they_do_scan(cli):
    """The plan-review call sites pass no blocker_evidence and must be byte-identical."""
    log = "## Findings\n- [Critical] unbounded retry loop"
    assert cli.review_log_verdict_errors(log, "clean", 0, 0, []) != []
    assert cli.review_log_verdict_errors(log, "clean", 0, 0, [], blocker_evidence="all") != []


def test_the_alias_map_agrees_with_the_shared_blocker_severities(cli):
    """The two lists must not drift: a severity that blocks elsewhere must map to a class here."""
    for severity in cli.BLOCKER_SEVERITIES:
        assert cli.blocker_class_of(severity) is not None, severity
