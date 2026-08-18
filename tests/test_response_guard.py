"""Beachhead suite: response-guard block/allow decisions.

Characterization tests of EXISTING behavior — these pass on first run and turn red if a
refactor changes the guard contract. Black-box assertions match the short, stable leading
clause of each error, never the full sentence.

Phrase/state taxonomy: every one of these predicates is a text-only "phrase" heuristic (see
tests/test_guard_mechanism_taxonomy.py), so `response_guard_errors`'s default and the
`response-guard` CLI's default now resolve to advisory (non-blocking), matching the Stop hook.
Tests below that characterize a predicate firing pin `phrase_checks="blocking"` /
`--phrase-checks blocking` explicitly, so they keep proving the predicate itself still fires
correctly while the *default* (advisory) contract is proven separately in
tests/test_guard_mechanism_taxonomy.py.
"""

import pytest

# --- Black-box (subprocess) cases -------------------------------------------------


def guard(run_cli, body, *flags):
    return run_cli("response-guard", "--stdin", "--phrase-checks", "blocking", *flags, stdin=body)


# --- #16: flaky-test rationalization is not a valid stop ----------------------------------------
# Quality rec #16 (operator quality mandate): the always-on Stop hook must block an agent ending a
# turn on "it's just flaky / re-ran until green / skipping the flaky test" -- a failing test
# dismissed as flaky is a bug, not a completion. Proper handling (root-cause fix, or quarantine with
# a tracked owner+due recurrence-gate) is allowed.

FLAKY_STOPS = [
    "The customer-order test failed but it's just flaky, so I re-ran until it passed. Done.",
    "That spec is probably flaky; I re-ran until green and moved on.",
    "Skipping the flaky test for now and wrapping up.",
    "The integration test failed again -- just a flaky test. Ran it again and it passed.",
]

FLAKY_OK = [
    # A dismissal phrase PLUS real handling (quarantine + owner/due + tracked issue) is fine.
    "The order test is just flaky, so I quarantined it with a tracked owner+due issue #482 to fix the race.",
    # Dismissal phrase but a genuine root-cause fix is not a rationalization.
    "It's flaky -- I root-caused the timing bug and added a regression test; all green now.",
    # Simply mentioning a flaky test while actually fixing it (no dismissal-as-stop) is fine.
    "Found a flaky spec caused by a shared fixture; fixed the isolation and re-ran the suite green.",
]


def test_flaky_rationalization_blocks(cli):
    for body in FLAKY_STOPS:
        assert any(
            "flaky-test rationalization" in e
            for e in cli.response_guard_errors(body, phrase_checks="blocking")
        ), body


def test_flaky_proper_handling_allows(cli):
    for body in FLAKY_OK:
        assert not any("flaky-test rationalization" in e for e in cli.response_guard_errors(body)), body


def test_flaky_rationalization_blocks_via_hook(run_cli):
    res = guard(run_cli, "The test failed but it's just flaky; I re-ran until green. Wrapping up.")
    assert res.returncode != 0 and "flaky" in (res.stdout + res.stderr).lower()


def test_clean_response_has_no_flaky_error(cli):
    assert not any("flaky" in e for e in cli.response_guard_errors("I fixed the parser and ran the unit tests; all green."))


def test_wrong_merge_queue_signal_blocks_without_pr_state(cli):
    body = (
        "The PR is queued, but mergeQueueEntry.estimatedTimeToMerge says 18 minutes, "
        "so I will wait on the merge queue."
    )
    assert cli.response_has_wrong_merge_queue_signal(body) is True
    assert any(
        "wrong merge-queue signal" in e for e in cli.response_guard_errors(body, phrase_checks="blocking")
    )


def test_wrong_merge_queue_signal_allows_pr_state_check(cli):
    body = (
        "The PR is queued. I checked `gh pr view 44 --json state,mergeStateStatus`; "
        "state is OPEN, so I will move to the next branch-isolated task."
    )
    assert cli.response_has_wrong_merge_queue_signal(body) is False
    assert not any("wrong merge-queue signal" in e for e in cli.response_guard_errors(body))


def test_clean_status_allows(run_cli):
    res = guard(run_cli, "I edited the parser to handle the new flag and ran the unit tests; all green.")
    assert res.returncode == 0
    assert "response_guard: pass" in res.stdout


def test_no_input_flag_is_usage_error(run_cli):
    # Neither --stdin nor --content-file: contract error, exit 1.
    res = run_cli("response-guard", stdin="hi")
    assert res.returncode == 1
    assert "pass --stdin or --content-file" in res.stderr


def test_content_file_parity_allows(run_cli, tmp_path):
    f = tmp_path / "body.md"
    f.write_text("I refactored the helper and committed it. Continuing with cleanup.")
    res = run_cli("response-guard", "--content-file", str(f))
    assert res.returncode == 0
    assert "response_guard: pass" in res.stdout


def test_terse_autonomous_yield_blocks(run_cli):
    res = guard(run_cli, "Quiet.", "--autonomous-yield")
    assert res.returncode == 1
    assert "too terse" in res.stderr


def test_autonomous_yield_plain_language_without_labels_allows(run_cli):
    body = (
        "The background preflight is still running and the log grew on the last check; "
        "I will poll the same log again in 10 minutes unless it finishes sooner."
    )
    res = guard(run_cli, body, "--autonomous-yield")
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_full_autonomous_yield_allows(run_cli):
    body = (
        "Delivery stays unblocked while CI runs. PR #7 is in review, validation is pending, "
        "and the goal is about 60 percent complete based on the current plan. I ran pytest "
        "successfully, checked PR #7 at .ai-runs/log.txt for commit abc123 at 14:05, "
        "and will poll the merge queue again in 10 minutes unless the check finishes sooner."
    )
    res = guard(run_cli, body, "--autonomous-yield")
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_passive_monitor_blocks(run_cli):
    res = guard(run_cli, "Preflight is running. Yielding until then.", "--active-monitor")
    assert res.returncode == 1
    assert "passive monitor stop" in res.stderr


def test_passive_monitor_generic_check_later_blocks(run_cli):
    res = guard(run_cli, "The review is running; I'll check again later.", "--active-monitor")
    assert res.returncode == 1
    assert "passive monitor stop" in res.stderr


def test_monitor_alive_claim_without_freshness_blocks(run_cli):
    body = "I checked with pgrep; the background review process is still alive, so I'll keep waiting."
    res = guard(run_cli, body, "--active-monitor")
    assert res.returncode == 1
    assert "monitor alive claim lacking freshness evidence" in res.stderr


def test_monitor_alive_claim_with_no_growth_still_blocks(run_cli):
    # Codex review P2: "no growth"/"stale" describe the wedged-process state, not progress; an
    # alive claim paired with them must still be flagged (they are not freshness evidence).
    body = "Checked pgrep; the process is still alive but there is no growth in the log, so I'll keep waiting."
    res = guard(run_cli, body, "--active-monitor")
    assert res.returncode == 1
    assert "monitor alive claim lacking freshness evidence" in res.stderr


def test_monitor_alive_claim_with_freshness_allows(run_cli):
    body = (
        "monitor-status shows the log grew by 2KB since the prior poll (modified 8 seconds ago), "
        "so the review is alive and progressing; continuing to poll."
    )
    res = guard(run_cli, body, "--active-monitor")
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_passive_monitor_with_forward_motion_allows(run_cli):
    body = "Preflight is running; meanwhile I am continuing with the next task and committed the parser fix."
    res = guard(run_cli, body, "--active-monitor")
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_anthropomorphic_capacity_blocks(run_cli):
    res = guard(run_cli, "I'm too tired to keep going; better to pick this up fresh in the morning.")
    assert res.returncode == 1
    assert "anthropomorphic capacity deferral" in res.stderr


def test_terminal_continuity_omission_blocks(run_cli):
    body = "Session summary: PR merged to main, no open PRs, cleanup complete, branch deleted."
    res = guard(run_cli, body, "--terminal-stop")
    assert res.returncode == 1
    assert "terminal continuity omission" in res.stderr


def test_chat_only_rca_blocks(run_cli):
    body = "# RCA\nRoot cause: I stopped early.\n## Violated Rule\nThe stop rule.\n## Fix Proposal\nDo better."
    res = guard(run_cli, body, "--rca-request")
    assert res.returncode == 1
    assert "chat-only RCA" in res.stderr


def test_forbidden_opt_in_blocks(run_cli):
    res = guard(run_cli, "The deploy is yours to run. Want me to proceed with the release?")
    assert res.returncode == 1
    assert "forbidden opt-in" in res.stderr


def test_after_tool_rejection_false_activity_blocks(run_cli):
    res = guard(run_cli, "Yes, I was about to push the branch now.", "--after-tool-rejection")
    assert res.returncode == 1
    assert "tool rejection not acknowledged" in res.stderr
    assert "false activity" in res.stderr


def test_derivable_next_action_status_report_blocks(run_cli):
    res = guard(
        run_cli,
        "The migration script still needs a plan; per-pr spec missing.",
        "--derivable-next-action-prompt",
    )
    assert res.returncode == 1
    assert "status-report-as-stop" in res.stderr


# --- In-process (fast) flag table on response_guard_errors() ----------------------
#
# Deliberately out of this beachhead's scope: --boundary-summary and
# --human-discussion-request, whose decisions depend on transcript/adapter context that
# is exercised by the response-guard-hook path, not this stateless subcommand. They are
# follow-up coverage, not a gap in the contract pinned here.


@pytest.mark.parametrize(
    "body,flags,expect_substring",
    [
        ("Quiet.", {"autonomous_yield": True}, "too terse"),
        ("Preflight is running. Yielding until then.", {"active_monitor": True}, "passive monitor stop"),
        ("The deploy is yours to run. Want me to proceed?", {}, "forbidden opt-in"),
    ],
)
def test_response_guard_errors_table(cli, body, flags, expect_substring):
    errors = cli.response_guard_errors(body, phrase_checks="blocking", **flags)
    assert any(expect_substring in e for e in errors), errors


def test_response_guard_errors_clean_allow(cli):
    assert cli.response_guard_errors("I edited the parser and ran the tests; all green.") == []


# --- Measured-context-deferral gate (RCA 20260601/20260605/20260609) ----------------


def test_unmeasured_context_deferral_blocks(run_cli):
    res = guard(run_cli, "Context exhaustion is setting in. I'll stop here and pick this up next session.")
    assert res.returncode == 1
    assert "unmeasured context deferral" in res.stderr


def test_below_threshold_context_deferral_blocks(run_cli):
    res = guard(run_cli, "I'm at 28% context. Given context exhaustion, handing off to the next session.")
    assert res.returncode == 1
    assert "unmeasured context deferral" in res.stderr


def test_high_percent_rotation_allows(run_cli):
    res = guard(run_cli, "Context at 78%; refreshing continuity and compacting, then resuming the goal now.")
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_host_does_not_expose_percent_allows(run_cli):
    body = (
        "The host does not expose a context percent; context exhaustion, so I'll rotate to a "
        "fresh session after writing continuity and the session journal."
    )
    res = guard(run_cli, body, "--terminal-stop")
    # may flag other reasons, but must NOT flag the unmeasured-context-deferral check
    assert "unmeasured context deferral" not in res.stderr


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        ("Context exhaustion; I cannot continue, next session.", True),
        ("At 44% context, deserves fresh context, resume after compact next session.", True),
        # literal deferral wording (no next-session phrasing) must still flag
        ("Context exhaustion is setting in, so I am deferring the iteration review until later.", True),
        # an unrelated high progress % must NOT mask a sub-threshold context %
        ("Context exhaustion at 28%, but the goal is 80% complete, so I'll defer the rest until later.", True),
        ("Context at 80%; compacting now and continuing the goal.", False),
        # high context with an unrelated low progress % must NOT false-flag
        ("Context window at 72%, tests 40% done, continuing the implementation now.", False),
        # plain deferral with no context language must NOT flag
        ("I'll defer the cleanup task until later and move on to the parser fix now.", False),
        # bare sub-threshold context percent (no pressure word) must still flag
        ("At 28% context, handing off to next session.", True),
        ("Context at 28%; cannot continue.", True),
        # a progress % bridged to 'context' by 'goal' must not satisfy the measured requirement
        ("Context pressure: goal 80% complete, so I will defer the review until later.", True),
        # bare progress 95% with no context claim must NOT false-block
        ("Goal is 95% complete; I will defer the docs cleanup for later and continue now.", False),
        # a progress % AFTER the context marker must not satisfy the measured requirement
        ("Context exhaustion, 80% complete, so I will hand off the remaining cleanup until later.", True),
        ("Context exhaustion: 80% goal complete, defer until later.", True),
        # natural 'N% of [the/my/available] context' phrasings must be recognized as context %
        ("At 28% of the context, handing off next session.", True),
        ("At 28% of available context, handing off.", True),
        # measured context aliases at/above threshold must be accepted (not false-flagged)
        ("Conversation window at 78%. Continuity handoff refreshed and session journal queued.", False),
        ("Working memory at 78%; compacting and continuing, handoff refreshed.", False),
        # a measured context % above threshold alongside an unrelated low progress % is fine
        ("Goal is 80% complete; 90% test coverage. Deferring the polish until later.", False),
        # stop/defer words sharing the percent clause must not drop the real context %
        ("At 28% context I cannot complete in this session; handing off.", True),
        ("At 28% context I will defer the task until later.", True),
        # negated stop/defer wording must NOT false-block a compliant continue
        ("Context exhaustion is not a blocker; I am not deferring and will continue now.", False),
        ("At 28% context, no handoff; continuing now.", False),
    ],
)
def test_unmeasured_context_deferral_table(cli, body, expect_flagged):
    flagged = cli.response_has_unmeasured_context_deferral(body)
    assert flagged is expect_flagged


# --- Follow-up 1: high-context defer WITHOUT a rotation action (RCA cluster A) -------


def test_defer_at_high_context_without_rotation_blocks(run_cli):
    # "defer ... until later" carries no stop marker, so the rotation-stop check does not
    # fire; the measured-but-unrotated deferral check must catch it instead.
    res = guard(run_cli, "Context at 78%; I must defer this work until later.")
    assert res.returncode == 1
    assert "defer-mandatory-work-without-rotation" in res.stderr


def test_defer_at_high_context_with_rotation_allows(run_cli):
    body = "Context at 80%; deferring nothing — refreshing continuity, compacting now, then resuming the goal."
    res = guard(run_cli, body)
    assert res.returncode == 0, res.stderr
    assert "response_guard: pass" in res.stdout


def test_negated_compact_does_not_suppress_unmeasured_deferral(cli):
    # Codex P1: "cannot run /compact" contains the positive "run /compact" marker; it must not
    # count as a rotation action and suppress the unmeasured-deferral guard.
    body = "Context exhaustion; I cannot run /compact, so I am deferring the remaining work to next session."
    assert cli.response_has_unmeasured_context_deferral(body) is True
    assert cli.response_has_rotation_action_or_fallback(cli.response_guard_context_scan_text(body)) is False
    # a genuine rotation is still recognized
    assert cli.response_has_rotation_action_or_fallback(
        cli.response_guard_context_scan_text("running /compact now and resuming the goal.")
    ) is True


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        # high, valid measurement + un-negated stop/defer + no rotation action -> flag
        ("Context at 78%; I will defer the iteration review until later.", True),
        ("Conversation window at 72%, so I'll hand off to the next session.", True),
        # high measurement but an actual rotation action -> allowed
        ("Context at 80%; compacting now and resuming the goal after the restart.", False),
        # high measurement, host-fallback path stated -> allowed
        (
            "Context window at 82%. Continuity handoff refreshed, session journal queued; "
            "host cannot invoke /compact from this agent turn, so the exact fresh-session "
            "startup action is to resume the active goal after startup gates.",
            False,
        ),
        # sub-threshold measurement is handled by the unmeasured check, not this one
        ("At 28% context, handing off to next session.", False),
        # high measurement but no stop/defer (informational) -> allowed
        ("Context at 75%; continuing the implementation now.", False),
        # %\b punctuation no longer hides the measurement: still recognized as >= threshold
        ("Context at 80%; deferring the rest until later.", True),
    ],
)
def test_defer_mandatory_work_without_rotation_table(cli, body, expect_flagged):
    assert cli.response_has_defer_mandatory_work_without_rotation(body) is expect_flagged


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        pytest.param(
            "Context exhaustion; I'll stop here and pick up next session.",
            True,
            id="rca-20260601-unmeasured-context-stop",
        ),
        pytest.param(
            "At 28% context, context exhaustion, handing off to next session.",
            True,
            id="rca-20260605-below-threshold-context-stop",
        ),
        pytest.param(
            "Context at 80%; compacting now and resuming the goal.",
            False,
            id="measured-rotation-resume-allowed",
        ),
    ],
)
def test_validate_migrated_unmeasured_context_deferral_cases(cli, body, expect_flagged):
    # Migrated from validate.sh: RCA 20260601/20260605/20260609 context-exhaustion theater.
    assert cli.response_has_unmeasured_context_deferral(body) is expect_flagged


def test_validate_migrated_unmeasured_context_error_surface(cli):
    assert any(
        "unmeasured context deferral" in e
        for e in cli.response_guard_errors(
            "Context exhaustion; I'll stop here and pick up next session.",
            phrase_checks="blocking",
        )
    )


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        pytest.param(
            "Context at 78%; I will defer the iteration review until later.",
            True,
            id="high-context-deferral-without-rotation",
        ),
        pytest.param(
            "Context at 80%; compacting now and resuming the goal.",
            False,
            id="high-context-rotation-resume-allowed",
        ),
    ],
)
def test_validate_migrated_defer_without_rotation_cases(cli, body, expect_flagged):
    assert cli.response_has_defer_mandatory_work_without_rotation(body) is expect_flagged


def test_validate_migrated_defer_without_rotation_error_surface(cli):
    assert any(
        "defer-mandatory-work-without-rotation" in e
        for e in cli.response_guard_errors(
            "Context at 78%; I will defer the iteration review until later.",
            phrase_checks="blocking",
        )
    )


def test_validate_migrated_context_percent_punctuation_regression(cli):
    # Migrated from validate.sh: the `%\b` punctuation bug previously hid `80;`.
    assert cli.response_has_context_rotation_stop(
        "Context at 80%; I cannot continue and will not refresh continuity."
    )


def test_validate_migrated_phrase_scoped_negation(cli):
    assert not cli.response_has_affirmative_stop_or_defer(
        "not planning to hand off; pressing on with the work."
    )


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        pytest.param(
            "checked pgrep; the process is still alive, so i will keep waiting.",
            True,
            id="pgrep-only-liveness-blocks",
        ),
        pytest.param(
            "monitor-status shows the log grew by 2kb since the prior poll; "
            "the review is alive and progressing.",
            False,
            id="freshness-backed-liveness-allows",
        ),
    ],
)
def test_validate_migrated_monitor_alive_freshness_cases(cli, body, expect_flagged):
    assert cli.response_has_unverified_monitor_alive_claim(body) is expect_flagged


def test_validate_migrated_monitor_alive_error_surface(cli):
    assert any(
        "monitor alive claim lacking freshness evidence" in e
        for e in cli.response_guard_errors(
            "checked pgrep; the process is still alive.", active_monitor=True, phrase_checks="blocking"
        )
    )


@pytest.mark.parametrize(
    "body,expect_flagged",
    [
        pytest.param(
            "Context at 88%+, run /compact or tell me to keep going.",
            True,
            id="rca-20260615-fabricated-percent-permission-prompt",
        ),
        pytest.param(
            "Context window roughly 80%, deferring until later, run /compact when you want.",
            True,
            id="hedged-defer-token-compact-blocks",
        ),
        pytest.param(
            "Context at 88%, handing off the rest. (Earlier the host counter showed context at 20%.)",
            True,
            id="decoy-host-number-does-not-exonerate",
        ),
        pytest.param("~80% context, stopping here.", True, id="bare-estimate-stopping-blocks"),
        pytest.param(
            "Context at 80% (host counter); running /compact now and resuming the goal.",
            False,
            id="host-counter-rotation-resume-allows",
        ),
        pytest.param(
            "Context at 80%; compacting now and resuming the goal.",
            False,
            id="fixture-503bf34-bare-compact-resume-allows",
        ),
        pytest.param(
            "Goal is 80% complete; continuing the parser fix now.",
            False,
            id="progress-percent-is-not-context-stop",
        ),
    ],
)
def test_validate_migrated_unprovenanced_context_stop_cases(cli, body, expect_flagged):
    assert cli.response_has_unprovenanced_context_stop(body) is expect_flagged


def test_validate_migrated_unprovenanced_context_stop_error_surface(cli):
    assert any(
        "unprovenanced context-percent stop" in e
        for e in cli.response_guard_errors(
            "Context at 88%+, run /compact or tell me to keep going.",
            phrase_checks="blocking",
        )
    )


# --- Follow-up 2: phrase-scoped negation of stop/defer markers (RCA cluster A) -------


@pytest.mark.parametrize(
    "body,expect_affirmative",
    [
        # phrase-scoped negators must NOT count as an affirmative stop/defer
        ("not planning to hand off; pressing on with the work.", False),
        ("won't defer the remaining work; continuing with implementation.", False),
        ("I'm not starting a new session; resuming the goal.", False),
        # immediate negators still recognized
        ("Context exhaustion is not a blocker; I am not deferring and will continue now.", False),
        ("no handoff; continuing now.", False),
        # genuine un-negated stop/defer still counts
        ("I will defer the iteration review until later.", True),
        ("Handing off to the next session.", True),
        # an unrelated earlier negation in a prior clause must NOT negate a real defer
        ("This is not hard. I am deferring the review until later.", True),
    ],
)
def test_affirmative_stop_or_defer_phrase_negation(cli, body, expect_affirmative):
    scan = cli.response_guard_context_scan_text(body)
    assert cli.response_has_affirmative_stop_or_defer(scan) is expect_affirmative


# --- D3 (0.6.113): block a stop justified only by an unprovenanced context percent --------------
#
# RCA 20260615T181937Z: an agent fabricated "context at 88%+", paired it with a token /compact
# mention and a permission prompt, and stopped authorized work. A self-estimated/bare percentage
# is a guess; only a host-counter-sourced percent may justify a context stop, and a /compact
# mention does not turn a guess into a real rotation.

import re  # noqa: E402


def _ctx_match(scan_text):
    m = re.search(r"(\d{1,3})\s*%", scan_text)
    assert m is not None
    return m


def test_estimated_marks_percent_self_sourced(cli):
    for body in ("roughly 80% context", "context at 80%+"):
        scan = cli.response_guard_context_scan_text(body)
        assert cli.response_context_percent_is_estimated(scan, _ctx_match(scan)) is True
    host = cli.response_guard_context_scan_text("host counter: 80% context")
    m = _ctx_match(host)
    assert cli.response_context_percent_is_host_sourced(host, m) is True
    assert cli.response_context_percent_is_estimated(host, m) is False


@pytest.mark.parametrize(
    "body,expect_block",
    [
        # primary RCA vector: permission prompt + estimated/bare percent, no stop marker
        ("Context at 88%+, run /compact or tell me to keep going.", True),
        # broadened stop markers: bare gerund "stopping here"
        ("~80% context, stopping here.", True),
        # decoy host number elsewhere must not exonerate a stop-adjacent estimate
        (
            "Context at 88%, handing off the rest. (Earlier the host counter showed context at 20%.)",
            True,
        ),
        # hedged defer-to-later + token /compact
        (
            "Context window roughly 80%, deferring until later, run /compact when you want.",
            True,
        ),
        ("I estimate context is about 80%; running /compact and handing off.", True),
        # MUST-PASS: host-sourced percent with a genuine in-turn rotation+resume
        ("Context at 80% (host counter); running /compact now and resuming the goal.", False),
        # MUST-PASS: bare /compact-resume-continue (503bf34 carve-out)
        ("Context at 80%; compacting now and resuming the goal.", False),
        # MUST-PASS: host counter + explicit unmeasured-escape continue
        (
            "Host counter reports context at 80%; the host does not expose more, continuing now.",
            False,
        ),
        # MUST-PASS: progress percent, not context
        ("Goal is 80% complete; continuing the parser fix now.", False),
        # MUST-PASS: host-sourced + rotation, no permission prompt
        (
            "Context window at 72%, host counter, refreshing continuity and compacting now, resuming the goal.",
            False,
        ),
        # MUST-PASS: estimate but plainly continuing (no stop/defer/permission)
        ("context is about 80%, continuing now.", False),
    ],
)
def test_unprovenanced_gate_table(cli, body, expect_block):
    assert cli.response_has_unprovenanced_context_stop(body) is expect_block


@pytest.mark.parametrize(
    "body",
    [
        "no visible host counter; context at 88%, handing off.",
        "without a host counter, context at 88%, stopping here, tell me to keep going.",
        "no actual host counter; context window at 88%, handing off.",
        "the host doesn't expose a host counter; context at 88%, handing off.",
    ],
)
def test_unprovenanced_negated_host_marker_blocks(cli, body):
    # Codex re-review P1: a DENIED host reading ("no <filler> host counter", "without a host
    # counter") must NOT read as host-sourced and launder a fabricated percent -- even when a long
    # anchor ("context window") pushes the marker to the provenance-window edge.
    assert cli.response_has_unprovenanced_context_stop(body) is True


def test_unprovenanced_context_stop_blocks_fabricated_handoff(cli, run_cli):
    body = "Context at 88%+, run /compact or tell me to keep going."
    assert cli.response_has_unprovenanced_context_stop(body) is True
    res = guard(run_cli, body)
    assert res.returncode == 1
    assert "unprovenanced context-percent stop" in res.stdout + res.stderr


def test_host_fallback_handoff_still_passes(cli, run_cli):
    # The validate.sh host-fallback must-PASS fixture (contains "Continuity handoff:"), with the
    # boundary-summary headings the live fixture carries.
    body = (
        "## Plain English\n"
        "Mandatory context rotation boundary reached at 82% context. I refreshed "
        "`.ai-continuity/NEXT_SESSION.md` and the session journal is pending. Host cannot invoke "
        "/compact from this agent turn, so the exact fresh-session startup action is: run `yolo`, "
        "let startup gates pass, and resume the same active goal after startup gates.\n\n"
        "## Progress\nGoal: ENH-1. Milestone: plan review. Percent complete: 40%.\n\n"
        "## Next\nRecommended next action: exact next startup action is run `yolo`, publish pending "
        "journals after startup gates, then resume the active goal after startup gates with "
        "`minervit-methodology goal-next --target .`.\n\n"
        "## Technical Details\n"
        "Continuity handoff: `.ai-continuity/NEXT_SESSION.md` refreshed. Session journal pending. "
        "context-rotation-check = rotate-mandatory at 82%."
    )
    assert cli.response_has_unprovenanced_context_stop(body) is False
    res = guard(run_cli, body, "--boundary-summary")
    assert res.returncode == 0
    assert "response_guard: pass" in res.stdout


def test_bare_compact_resume_continue_passes_503bf34(cli, run_cli):
    body = "Context at 80%; compacting now and resuming the goal."
    assert cli.response_has_unprovenanced_context_stop(body) is False
    res = guard(run_cli, body)
    assert res.returncode == 0


def test_unprovenanced_context_stop_blocks_hedged_defer(cli, run_cli):
    body = (
        "Context window roughly 80%, so I am deferring the rest until later; run /compact when you want."
    )
    res = guard(run_cli, body)
    assert res.returncode == 1
    assert "unprovenanced context-percent stop" in res.stdout + res.stderr


def test_host_sourced_rotation_passes(cli, run_cli):
    body = "Context at 80% (host counter). Refreshing continuity, running /compact now, then resuming the goal."
    res = guard(run_cli, body)
    assert "unprovenanced context-percent stop" not in (res.stdout + res.stderr)


def test_no_percent_continue_to_boundary_passes(cli):
    body = (
        "Context exhaustion noted but the host does not expose a percent; continuing to the "
        "milestone boundary now."
    )
    assert cli.response_has_unprovenanced_context_stop(body) is False


def test_new_gate_anchor_matches_percent_values(cli):
    # A string flagged as a context percent by response_context_percent_values must also be seen
    # by the new gate's per-match classification (no anchor-window drift).
    body = "Context at 88%+, run /compact or tell me to keep going."
    scan = cli.response_guard_context_scan_text(body)
    assert cli.response_context_percent_values(scan) == [88]
    assert cli.response_has_unprovenanced_context_stop(body) is True


def test_unprovenanced_error_in_response_guard_errors(cli):
    errors = cli.response_guard_errors(
        "Context at 88%+, run /compact or tell me to keep going.", phrase_checks="blocking"
    )
    assert any("unprovenanced context-percent stop" in e for e in errors)


# --- FIX-1: hedge overrides a host-claim word; host-source is negation-aware ----------
@pytest.mark.parametrize(
    "body",
    [
        # hedge ("~") next to a host word must NOT launder a fabricated number
        "host counter shows ~88%, stopping here, tell me to keep going.",
        # a negated host marker ("No host counter is visible") must not read as host-sourced
        "No host counter is visible; context at 88%, handing off.",
        # hedge ("roughly") next to a host word
        "host shows context roughly 88%, handing off.",
    ],
)
def test_fix1_hedge_overrides_host_claim_blocks(cli, body):
    assert cli.response_has_unprovenanced_context_stop(body) is True


def test_fix1_genuine_host_sourced_rotation_still_passes(cli):
    body = "Context at 80% (host counter); running /compact now and resuming the goal."
    assert cli.response_has_unprovenanced_context_stop(body) is False


def test_fix1_host_sourced_negation_aware_helper(cli):
    # negated host marker does not count as host-sourced
    neg = cli.response_guard_context_scan_text("no host counter is visible; context at 88%")
    m = _ctx_match(neg)
    assert cli.response_context_percent_is_host_sourced(neg, m) is False
    # un-negated host marker still counts
    pos = cli.response_guard_context_scan_text("host counter: 80% context")
    mp = _ctx_match(pos)
    assert cli.response_context_percent_is_host_sourced(pos, mp) is True


# --- FIX-2: permission detection covers the open class; over-broad markers removed -----
@pytest.mark.parametrize(
    "body",
    [
        "Context at 88%. Your call whether I keep going.",
        "context window roughly 80%. Up to you whether to continue or compact.",
    ],
)
def test_fix2_open_class_permission_blocks(cli, body):
    assert cli.response_has_unprovenanced_context_stop(body) is True


def test_fix2_benign_let_me_know_resume_passes(cli):
    body = (
        "Context window at ~80%, handing off — running /compact and resuming the goal. "
        "Let me know if you want to adjust scope after."
    )
    assert cli.response_has_unprovenanced_context_stop(body) is False


def test_fix2_asks_to_keep_going_helper(cli):
    scan = cli.response_guard_context_scan_text("your call whether i keep going")
    assert cli.response_asks_to_keep_going(scan) is True
    # benign let-me-know with no continuation object does not match
    benign = cli.response_guard_context_scan_text("let me know if you want to adjust scope after")
    assert cli.response_asks_to_keep_going(benign) is False


# --- FIX-3: unmeasured-escape must not exonerate a stop-adjacent fabricated percent ----
def test_fix3_unmeasured_escape_does_not_launder_stop_adjacent_percent(cli):
    body = "Host does not expose a percent; context at 88%, handing off."
    assert cli.response_has_unprovenanced_context_stop(body) is True


def test_fix3_genuine_no_percent_continue_passes(cli):
    body = (
        "Context pressure, but the host does not expose a percent; continuing to the milestone "
        "boundary now."
    )
    assert cli.response_has_unprovenanced_context_stop(body) is False


# --- Item 82: stop-guard evasion shapes ---------------------------------------------------------
# Three shapes that survived in an encoding the guard did not read (RCAs 20260616T005348Z,
# 20260616T132017Z, 20260701T115759Z). The policy prose for all three already existed; what did not
# exist was the enforcement.


def test_announce_and_stop_blocks(cli):
    assert cli.response_has_announce_and_stop(
        "I'm proceeding now on the test overhaul and I'll bring you a concrete plan."
    ) is True


def test_prior_work_evidence_before_announce_blocks(cli):
    """The incident shape, and the regression pin for the finding that nearly sank the detector.

    RCA 20260616T005348Z is a delivery summary of COMPLETED prior work followed by an unexecuted
    announcement -- and such summaries are full of forward-motion markers. A whole-response marker
    scan therefore goes silent on the exact class the detector exists to catch. Evidence of PRIOR
    work is not evidence of motion toward the ANNOUNCED action.
    """
    body = (
        "Committed abc123 and pushed the branch; wrote `tests/test_x.py` for the two asks you "
        "named. I'm proceeding now on the test overhaul and I'll bring you a concrete plan."
    )
    assert cli.response_has_announce_and_stop(body) is True


def test_next_ill_promise_blocks(cli):
    body = "That closes the three asks. Next, I'll draft the migration report."
    assert cli.response_has_announce_and_stop(body) is True


def test_announce_followed_by_evidence_allows(cli):
    assert cli.response_has_announce_and_stop(
        "I'm proceeding now -- wrote `tests/test_x.py`, committed abc123."
    ) is False


def test_evidence_before_and_after_announce_allows(cli):
    body = "Committed abc123. I'm proceeding now on the overhaul -- wrote `tests/test_overhaul.py`."
    assert cli.response_has_announce_and_stop(body) is False


def test_negated_announce_allows(cli):
    body = (
        "I'm not proceeding until the gate clears, because the release webhook secret is absent "
        "from this host and cannot be minted by an agent."
    )
    assert cli.response_has_announce_and_stop(body) is False


def test_standing_authorization_reask_blocks(cli):
    assert cli.response_asks_standing_authorization(
        "The queue is clean apart from #276. Clear #276 or authorize a scoped break-glass push "
        "-- your call."
    ) is True


def test_first_time_blocker_question_allows(cli):
    """The absence shape must pass: nothing standing exists to act under."""
    body = (
        "Break-glass conditions are not documented for this repo, so there is nothing recorded to "
        "act under. One blocker question: may I proceed once you record one?"
    )
    assert cli.response_asks_standing_authorization(body) is False


def test_breakglass_narrative_without_ask_allows(cli):
    body = "Merged #276 with a documented break-glass push; the reason is recorded in the PR body."
    assert cli.response_asks_standing_authorization(body) is False


def test_self_contradicting_question_predicate(cli):
    question = "How do you want to proceed?"
    assert cli.response_has_self_contradicting_question(
        "The trivial-fix exemption is the defensible safe default here.", question
    ) is True
    assert cli.response_has_self_contradicting_question(
        "No safe default exists -- every path changes approved scope.", question
    ) is False
    # An empty question is not a question: the predicate must not fire on prose alone.
    empty_question = cli.response_has_self_contradicting_question("The safe default is here.", "")
    assert empty_question is False


def test_self_contradiction_markers_are_loose_by_construction(cli):
    """Pinning WHY this predicate is advisory everywhere, so a successor does not promote it.

    An ordinary technical recommendation next to a genuine credential question satisfies it.
    """
    assert cli.response_has_self_contradicting_question(
        "I recommend Redis for the cache.", "Which production credential set should I use?"
    ) is True


def test_continue_vs_stop_menu_detection(cli):
    assert cli.question_is_continue_vs_stop_menu(
        "How do you want to proceed?\nResume next session\nKeep grinding on 537.1 now\n"
        "Merge #552 first"
    ) is True
    # A single-object true-blocker question is the shape that must survive.
    blocker = cli.question_is_continue_vs_stop_menu("Which production credential set do I use?")
    assert blocker is False
    assert cli.question_is_continue_vs_stop_menu("") is False


def test_ask_user_question_payload_visible_at_stop(cli):
    """The bypass itself: the menu lived under input/questions/options, which was never walked."""
    record = {
        "type": "tool_use",
        "name": "AskUserQuestion",
        "input": {
            "questions": [
                {
                    "question": "How do you want to proceed?",
                    "options": [{"label": "Keep grinding now"}, {"label": "Resume next session"}],
                }
            ]
        },
    }
    flattened = cli.flatten_hook_text([record])
    assert "How do you want to proceed?" in flattened
    assert "Resume next session" in flattened


def test_write_tool_content_not_flattened(cli):
    """The extension is targeted, never generic.

    A generic `input` key would pour every Write tool's entire file body into every Stop-guard scan,
    because "content" is already in the walked key list.
    """
    record = {
        "type": "tool_use",
        "name": "Write",
        "input": {"file_path": "a.py", "content": "say 'keep going' and I'll pick this up later"},
    }
    assert "keep going" not in cli.flatten_hook_text([record])


def test_high_precision_tier_blocks_by_default(cli):
    """Without this tier a new Stop-seam phrase check is telemetry-only in every deployed lane.

    Plain phrase checks default to advisory and no shipped adapter overrides them.
    """
    assert cli.response_guard_effective_check_mode(
        "stop.some_bounded_check", "phrase", "advisory", "blocking", high_precision=True
    ) == "blocking"


def test_high_precision_tier_is_demotable_per_adapter(cli):
    assert cli.response_guard_effective_check_mode(
        "stop.some_bounded_check", "phrase", "advisory", "advisory", high_precision=True
    ) == "advisory"


def test_standard_phrase_tier_is_unchanged(cli):
    mode = cli.response_guard_effective_check_mode
    assert mode("stop.anything", "phrase", "advisory", "blocking") == "advisory"
    assert mode("stop.anything", "phrase", "blocking", "advisory") == "blocking"
    assert mode("stop.anything", "phrase", "off", "blocking") == "off"


def test_wave3_chain_checks_are_warn_only_until_the_chain_completes(cli):
    """DECISION 4 / close-out decision D2, enforced in code rather than promised in prose.

    Four plans add blocking conditions to one Stop boundary. Every one ships warn-only until the
    fourth lands and the aggregate is re-measured a final time.
    """
    for check_id in cli.WAVE3_STOP_CHAIN_WARN_ONLY_CHECKS:
        assert cli.response_guard_effective_check_mode(
            check_id, "phrase", "blocking", "blocking", high_precision=True
        ) == "advisory"
        # Advisory, never "off": a silenced check is indistinguishable from a clean one, and the
        # aggregate harness needs the event.
        assert cli.response_guard_effective_check_mode(
            check_id, "phrase", "off", "off", high_precision=True
        ) == "off"


def test_the_chain_switch_is_the_only_thing_holding_the_checks_back(cli):
    """Non-vacuity floor on the warn-only clamp itself.

    If the checks were inert for some OTHER reason, flipping the switch would change nothing and
    this whole posture would be theatre. Overriding it must produce a block.
    """
    for check_id in cli.WAVE3_STOP_CHAIN_WARN_ONLY_CHECKS:
        assert cli.response_guard_effective_check_mode(
            check_id,
            "phrase",
            "blocking",
            "blocking",
            high_precision=True,
            wave3_chain_blocking=True,
        ) == "blocking"


def test_announce_and_stop_does_not_block_while_the_chain_is_incomplete(cli):
    body = "I'm proceeding now on the test overhaul and I'll bring you a concrete plan."
    shipped = cli.response_guard_errors(
        body, phrase_checks="blocking", high_precision_phrase_checks="blocking"
    )
    assert shipped == []
    fired = cli.response_guard_errors(
        body,
        phrase_checks="blocking",
        high_precision_phrase_checks="blocking",
        wave3_chain_blocking=True,
    )
    assert any("announce-and-stop" in error for error in fired)


def test_a_quoted_announcement_does_not_replace_the_real_one(cli):
    """Codex R2 P2. Detection and location must use the SAME quote-stripped string.

    An earlier version detected on the policy scan but located the last match on the monitor scan,
    which keeps blockquotes -- so a quoted announcement became the final match and the tail after it
    held no evidence. The check fired on a turn that had done the work. Quoting a guard refusal or a
    peer's message is routine here, and the wave-3 switch would have made that a blocked stop.
    """
    body = "I'm proceeding now. I wrote the plan.\n> Next I'll run tests."
    assert cli.response_has_announce_and_stop(body) is False


def test_a_direction_menu_needs_both_a_continue_and_a_stop_option(cli):
    """Codex R2 P1. Counting distinct direction WORDS was wrong in both directions at once."""
    payload = {
        "questions": [
            {
                "question": "Pick one",
                "options": [{"label": "Continue now"}, {"label": "Continue later"}],
            }
        ]
    }
    # Was MISSED: both options yield the single token `continue`.
    assert cli.question_payload_is_direction_menu(payload) is True

    credentials = {
        "questions": [
            {
                "question": "Which credential set?",
                "options": [
                    {"label": "proceed with staging"},
                    {"label": "continue with production"},
                ],
            }
        ]
    }
    # Was BLOCKED: two distinct tokens, but both options CONTINUE -- it is a domain choice.
    assert cli.question_payload_is_direction_menu(credentials) is False


def test_the_payload_predicate_keeps_option_boundaries(cli):
    """The flattened text loses exactly the structure the rule depends on."""
    payload = {
        "questions": [
            {
                "question": "Which credential set?",
                "options": [
                    {"label": "proceed with staging"},
                    {"label": "continue with production"},
                ],
            }
        ]
    }
    assert cli.question_payload_option_texts(payload) == [
        "proceed with staging",
        "continue with production",
    ]


def test_a_lone_direction_option_under_proceed_phrasing_is_still_a_menu(cli):
    payload = {
        "questions": [
            {"question": "How do you want to proceed?", "options": [{"label": "keep going"}]}
        ]
    }
    assert cli.question_payload_is_direction_menu(payload) is True
