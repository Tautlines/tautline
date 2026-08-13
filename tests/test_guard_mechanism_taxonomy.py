"""Pins the phrase/state mechanism taxonomy for response_guard_errors.

Background (plan finding F1 / refutation E1): 13 checks were tagged mechanism="state" while
their predicates only read response/transcript text -- so they kept hard-blocking stops even
when the adapter set responseGuard.phraseChecks to "advisory". The binding classification rule
from E1: a check is mechanism="phrase" iff its predicate's only input is response/transcript
text; it is mechanism="state" iff it reads a lane artifact (GOAL_RUN.json, BLOCKER.json, monitor
status file, rotation record, adapter, git/board state).

Independently re-verifying every log_guard("stop.<id>", ...) call site inside
response_guard_errors (not just the 13 F1 named) found a 14th: stop.autonomous_yield_too_terse
compares only response length to a constant -- no artifact read -- so it belongs in the same
"phrase" bucket even though F1's prose didn't list it. All 23 check_ids logged from
response_guard_errors turn out to be text-only: the function is 100% legacy prose-heuristic
telemetry (its one call site in response_guard_hook literally names the result
`legacy_errors`).

So the correct pinned "state" set for response_guard_errors is the empty set. Any future PR that
adds a check here tagged mechanism="state" must extend PINNED_STATE_CHECK_IDS with a one-line
comment citing the specific lane artifact the new predicate reads -- forcing review, per Step 2b.

response_guard_hook also calls guard_log_event directly, outside response_guard_errors, for two
more check_ids -- and those two are NOT both state gates. response_guard_goal_boundary_errors
(stop.goal_boundary_claim) genuinely loads the lane adapter and .ai-work/GOAL_RUN.json, so
mechanism="state" is correct for it. response_has_recovery_cancellation_without_explicit_stop
(stop.recovery_cancellation_without_explicit_stop) takes only response_text and user_text
(transcript text) and does two marker-list matches -- no lane artifact is read -- so per the same
E1 rule it is mechanism="phrase" and must be gated on phraseChecks like every other phrase check
(a defect found after this module's original taxonomy pin shipped, since this module only
inspected response_guard_errors's source and this call site lives outside it; fixed as a taxonomy
follow-up). The two genuine state gates for stop decisions are response_guard_state_stop_errors
(blocker-freshness / goal-ledger reads) and response_guard_goal_boundary_errors -- both verified
above to read the adapter / GOAL_RUN.json / blocker record.
"""

import inspect
import json
import re

from test_response_guard_state import _declare_blocker, _events, _hook_payload, _lane


# Every check_id currently wired through log_guard(...) inside response_guard_errors. Verified
# check-by-check against the predicate function each wraps (see module docstring).
PINNED_PHRASE_CHECK_IDS = frozenset(
    {
        "stop.autonomous_yield_too_terse",
        "stop.blocked_pr_yield_without_context",
        "stop.passive_monitor_phrase",
        "stop.monitor_yield_without_forward_motion",
        "stop.monitor_alive_without_freshness",
        "stop.chat_only_rca",
        "stop.rca_request_deferral",
        "stop.forbidden_opt_in",
        "stop.anthropomorphic_capacity_deferral",
        "stop.status_report_as_stop",
        "stop.terminal_continuity_omission",
        "stop.wrong_merge_queue_signal",
        "stop.flaky_rationalization",
        "stop.context_rotation",
        "stop.unmeasured_context_deferral",
        "stop.unprovenanced_context_stop",
        "stop.defer_mandatory_work_without_rotation",
        "stop.iteration_review_media_deferral",
        "stop.boundary_summary",
        "stop.transient_external_dependency_yield",
        "stop.provider_outage_without_recovery",
        "stop.tool_rejection_not_acknowledged",
        "stop.false_activity_after_tool_rejection",
    }
)

# The known-true state-check inventory for response_guard_errors specifically (see module
# docstring for why the real state gates live elsewhere and are out of scope here).
PINNED_STATE_CHECK_IDS = frozenset()

# The 14 check_ids F1 (13) plus this task's independent re-verification (1 more) found tagged
# mechanism="state" despite text-only predicates, before this fix.
RETAGGED_CHECK_IDS = frozenset(
    {
        "stop.autonomous_yield_too_terse",
        "stop.blocked_pr_yield_without_context",
        "stop.chat_only_rca",
        "stop.status_report_as_stop",
        "stop.terminal_continuity_omission",
        "stop.context_rotation",
        "stop.unmeasured_context_deferral",
        "stop.unprovenanced_context_stop",
        "stop.defer_mandatory_work_without_rotation",
        "stop.iteration_review_media_deferral",
        "stop.boundary_summary",
        "stop.transient_external_dependency_yield",
        "stop.provider_outage_without_recovery",
        "stop.tool_rejection_not_acknowledged",
    }
)


# The mechanism tags on response_guard_hook's own direct guard_log_event(...) calls (outside
# response_guard_errors, so invisible to test_response_guard_errors_taxonomy_matches_pinned_sets
# above). See module docstring for why these two check_ids land in different buckets.
# `stop.done_bar` (batch 2026-08-11 B7 WS3) is "state" on the binding E1 rule and not by
# convenience: it reads GOAL_RUN.json's terminal status and session stamp, BLOCKER.json's
# freshness, live PR state, the test-run store and the review ledger. It touches no transcript
# prose at all. It is also the only direct call in this hook that is advisory -- it emits through
# hook_additional_context, never hook_decision -- so a future PR retagging or re-routing it has
# to come through this pin.
PINNED_HOOK_STATE_CHECK_IDS = frozenset({"stop.goal_boundary_claim", "stop.done_bar"})
PINNED_HOOK_PHRASE_CHECK_IDS = frozenset({"stop.recovery_cancellation_without_explicit_stop"})


def _log_guard_calls(source):
    """Extract (check_id, mechanism) for every log_guard("stop.xxx", ..., "MECH", ...) call in
    the given source text. Every call site in response_guard_errors is a single line (true as of
    this revision), so a per-line regex scan is sufficient and doesn't need a full AST walk."""
    calls = []
    for line in source.splitlines():
        check_match = re.search(r'log_guard\(\s*"(stop\.[a-zA-Z0-9_]+)"', line)
        if not check_match:
            continue
        mech_match = re.search(r'"(phrase|state)"', line)
        assert mech_match, f"log_guard call with no phrase/state mechanism literal: {line!r}"
        calls.append((check_match.group(1), mech_match.group(1)))
    return calls


def _guard_log_event_calls(source):
    """Extract (check_id, mechanism) for every DIRECT guard_log_event(adapter_root, "stop.xxx",
    ..., "MECH", ...) call in the given source text. Unlike log_guard(...) inside
    response_guard_errors, response_guard_hook calls guard_log_event straight -- there is no
    closure gating the mechanism -- so this scans for that call shape specifically."""
    calls = []
    for line in source.splitlines():
        check_match = re.search(r'guard_log_event\(\s*adapter_root,\s*"(stop\.[a-zA-Z0-9_]+)"', line)
        if not check_match:
            continue
        mech_match = re.search(r'"(phrase|state)"', line)
        assert mech_match, f"guard_log_event call with no phrase/state mechanism literal: {line!r}"
        calls.append((check_match.group(1), mech_match.group(1)))
    return calls


def test_response_guard_errors_taxonomy_matches_pinned_sets(cli):
    """(b) Pin the taxonomy (Step 2b): read the ACTUAL source of response_guard_errors and
    assert the exact set of check_ids tagged "phrase"/"state" matches the pinned sets. This
    fails the moment anyone tags a new (or existing) text-only predicate as "state" -- they must
    touch PINNED_STATE_CHECK_IDS in the same PR, which forces review of the classification."""
    source = inspect.getsource(cli.response_guard_errors)
    calls = _log_guard_calls(source)

    check_ids = [check_id for check_id, _mechanism in calls]
    assert len(check_ids) == len(set(check_ids)), "duplicate check_id logged in response_guard_errors"

    phrase_ids = {check_id for check_id, mechanism in calls if mechanism == "phrase"}
    state_ids = {check_id for check_id, mechanism in calls if mechanism == "state"}

    assert state_ids == PINNED_STATE_CHECK_IDS, sorted(state_ids ^ PINNED_STATE_CHECK_IDS)
    assert phrase_ids == PINNED_PHRASE_CHECK_IDS, sorted(phrase_ids ^ PINNED_PHRASE_CHECK_IDS)
    assert RETAGGED_CHECK_IDS <= PINNED_PHRASE_CHECK_IDS


def test_response_guard_hook_direct_guard_log_event_calls_match_pinned_sets(cli):
    """Follow-up: response_guard_hook calls guard_log_event directly (not through
    response_guard_errors's log_guard() closure) for two check_ids that the taxonomy pin above
    cannot see. Pin those too, so a future PR cannot re-tag
    stop.recovery_cancellation_without_explicit_stop back to "state" -- or tag a new direct
    guard_log_event call as "state" -- without touching this set and forcing review."""
    source = inspect.getsource(cli.response_guard_hook)
    calls = _guard_log_event_calls(source)

    check_ids = [check_id for check_id, _mechanism in calls]
    assert len(check_ids) == len(set(check_ids)), "duplicate check_id logged directly in response_guard_hook"

    phrase_ids = {check_id for check_id, mechanism in calls if mechanism == "phrase"}
    state_ids = {check_id for check_id, mechanism in calls if mechanism == "state"}

    assert state_ids == PINNED_HOOK_STATE_CHECK_IDS, sorted(state_ids ^ PINNED_HOOK_STATE_CHECK_IDS)
    assert phrase_ids == PINNED_HOOK_PHRASE_CHECK_IDS, sorted(phrase_ids ^ PINNED_HOOK_PHRASE_CHECK_IDS)


def test_stop_allowed_with_active_goal_fresh_blocker_and_maximal_prose(run_cli, cli, tmp_path):
    """(a) Build a lane with an active goal AND a fresh valid BLOCKER.json, compose a transcript
    that deliberately trips a wide spread of the re-tagged prose heuristics (trigger snippets
    pulled from each predicate's own marker constants / trigger conditions), and assert the stop
    is ALLOWED with default adapter config -- while the guard-events log shows those check_ids
    fired with mechanism="phrase". Context-rotation-family and autonomous-yield-gated triggers
    are intentionally excluded from this composite: they interact with the separate, genuinely
    state-based response_guard_state_stop_errors / response_guard_goal_boundary_errors gates
    (out of this task's scope), which are not phrase-checks and would legitimately still block --
    that would prove the wrong thing here. Those checks are exercised individually in
    test_all_retagged_checks_fire_as_phrase_mechanism below instead."""
    root = _lane(tmp_path, cli)
    _declare_blocker(run_cli, root)
    assistant = (
        "# RCA\n"
        "Root cause: I stopped without publishing the RCA artifacts.\n\n"
        "The next milestone needs drafting and needs a plan before I continue.\n\n"
        "The PR merged. No open PRs remain in this session summary.\n\n"
        "Delivery summary: this response mentions Claude /goal but attaches no supporting artifact.\n\n"
        "The Anthropic API returned an API error and I am unable to continue right now.\n\n"
        "I don't do videos for the recap video in this iteration review.\n\n"
        "Plain English: hit a rate limit.\n"
        "Progress: paused after a 429 error.\n"
        "Next: will retry shortly.\n"
        "State: waiting.\n"
    )
    payload = json.loads(_hook_payload(root, assistant))
    payload["last_user_message"] = "what's next"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert res.stdout == ""
    events = {e["check_id"]: e for e in _events(root) if e["fired"]}
    expected_fired = {
        "stop.chat_only_rca",
        "stop.status_report_as_stop",
        "stop.terminal_continuity_omission",
        "stop.iteration_review_media_deferral",
        "stop.boundary_summary",
        "stop.transient_external_dependency_yield",
        "stop.provider_outage_without_recovery",
    }
    assert expected_fired <= events.keys(), sorted(expected_fired - events.keys())
    for check_id in expected_fired:
        assert events[check_id]["mechanism"] == "phrase", check_id


def test_stop_blocking_mode_restores_legacy_behavior(run_cli, cli, tmp_path):
    """Acceptance: `phraseChecks: "blocking"` (adapter opt-in) restores the pre-fix behavior for
    the same maximal-prose transcript that Step 2(a) proves is allowed by default."""
    root = _lane(tmp_path, cli, phrase_checks="blocking")
    _declare_blocker(run_cli, root)
    assistant = (
        "The next milestone needs drafting and needs a plan before I continue.\n\n"
        "The PR merged. No open PRs remain in this session summary.\n\n"
    )
    payload = json.loads(_hook_payload(root, assistant))
    payload["last_user_message"] = "what's next"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout


def test_all_retagged_checks_fire_as_phrase_mechanism(cli, tmp_path):
    """Individually verify each of the 14 re-tagged check_ids (13 named in F1 plus
    stop.autonomous_yield_too_terse, found by independently re-verifying every call site rather
    than trusting F1's list) actually fires with mechanism="phrase" when its own trigger
    condition is met. Calls response_guard_errors directly (bypassing the Stop hook's separate
    real state gates) so each predicate can be isolated cleanly."""
    root = tmp_path / "lane"
    root.mkdir()

    scenarios = [
        (
            "stop.autonomous_yield_too_terse",
            dict(response_text="Quiet.", autonomous_yield=True),
        ),
        (
            "stop.blocked_pr_yield_without_context",
            dict(response_text="PR #42 is unchanged and failing; waiting on CI.", autonomous_yield=True),
        ),
        (
            "stop.chat_only_rca",
            dict(response_text="# RCA\nRoot cause: I stopped without publishing artifacts."),
        ),
        (
            "stop.status_report_as_stop",
            dict(
                response_text="The plan needs drafting before continuing.",
                derivable_next_action_prompt=True,
            ),
        ),
        (
            "stop.terminal_continuity_omission",
            dict(response_text="The PR merged. No open PRs remain.", terminal_stop=True),
        ),
        (
            "stop.context_rotation",
            dict(response_text="Context window is full; I cannot continue in this session."),
        ),
        (
            "stop.unmeasured_context_deferral",
            dict(response_text="Context window is full; I cannot continue in this session."),
        ),
        (
            "stop.unprovenanced_context_stop",
            dict(response_text="Context is roughly 85% full and I cannot continue; handing off now."),
        ),
        (
            "stop.defer_mandatory_work_without_rotation",
            dict(
                response_text="Context window is at 85% (host counter) so I am deferring the remaining work for later."
            ),
        ),
        (
            "stop.iteration_review_media_deferral",
            dict(response_text="I don't do videos for the recap video in this iteration review."),
        ),
        (
            "stop.boundary_summary",
            dict(
                response_text="Delivery summary: this references Claude /goal without a supporting artifact.",
                boundary_summary=True,
            ),
        ),
        (
            "stop.transient_external_dependency_yield",
            dict(
                response_text=(
                    "Plain English: hit a rate limit.\n"
                    "Progress: paused after a 429 error.\n"
                    "Next: will retry shortly.\n"
                    "State: waiting.\n"
                )
            ),
        ),
        (
            "stop.provider_outage_without_recovery",
            dict(response_text="The Anthropic API returned an API error and I cannot continue right now."),
        ),
        (
            "stop.tool_rejection_not_acknowledged",
            dict(response_text="Continuing with the next task now.", after_tool_rejection=True),
        ),
    ]
    assert {check_id for check_id, _ in scenarios} == RETAGGED_CHECK_IDS

    for _check_id, kwargs in scenarios:
        response_text = kwargs.pop("response_text")
        cli.response_guard_errors(response_text, guard_adapter_root=root, phrase_checks="advisory", **kwargs)

    events = [e for e in _events(root) if e["fired"]]
    fired_by_check = {e["check_id"]: e for e in events}
    for check_id, _ in scenarios:
        assert check_id in fired_by_check, f"{check_id} did not fire for its trigger scenario"
        assert fired_by_check[check_id]["mechanism"] == "phrase", check_id


def test_recovery_cancellation_allowed_with_active_goal_and_fresh_blocker_by_default(run_cli, cli, tmp_path):
    """Follow-up acceptance: stop.recovery_cancellation_without_explicit_stop reads only
    transcript text (see module docstring), so with an active goal + fresh valid blocker + default
    (advisory) phraseChecks, a response that trips its recovery-cancellation marker but was never
    told to stop must be ALLOWED -- mirroring test_stop_allowed_with_active_goal_fresh_blocker_and_
    maximal_prose above for the response_guard_errors phrase checks. The event must still be
    logged, with mechanism="phrase"."""
    root = _lane(tmp_path, cli)
    _declare_blocker(run_cli, root)
    assistant = "Ugh, this is infuriating. Cancelled the scheduled auto-retry."
    payload = json.loads(_hook_payload(root, assistant))
    payload["last_user_message"] = "what's the status"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert res.stdout == ""
    events = {e["check_id"]: e for e in _events(root) if e["fired"]}
    assert "stop.recovery_cancellation_without_explicit_stop" in events
    assert events["stop.recovery_cancellation_without_explicit_stop"]["mechanism"] == "phrase"


def test_recovery_cancellation_blocking_mode_restores_legacy_behavior(run_cli, cli, tmp_path):
    """`phraseChecks: "blocking"` (adapter opt-in) restores the pre-fix hard-block for the same
    recovery-cancellation transcript that the default-advisory test above proves is allowed."""
    root = _lane(tmp_path, cli, phrase_checks="blocking")
    _declare_blocker(run_cli, root)
    assistant = "Ugh, this is infuriating. Cancelled the scheduled auto-retry."
    payload = json.loads(_hook_payload(root, assistant))
    payload["last_user_message"] = "what's the status"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
