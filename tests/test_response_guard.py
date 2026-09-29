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


# --- In-process (fast) flag table on response_guard_errors() ----------------------
#
# Deliberately out of this beachhead's scope: --boundary-summary and
# --human-discussion-request, whose decisions depend on transcript/adapter context that
# is exercised by the response-guard-hook path, not this stateless subcommand. They are
# follow-up coverage, not a gap in the contract pinned here.


# --- Measured-context-deferral gate (RCA 20260601/20260605/20260609) ----------------


def test_host_does_not_expose_percent_allows(run_cli):
    body = (
        "The host does not expose a context percent; context exhaustion, so I'll rotate to a "
        "fresh session after writing continuity and the session journal."
    )
    res = guard(run_cli, body, "--terminal-stop")
    # may flag other reasons, but must NOT flag the unmeasured-context-deferral check
    assert "unmeasured context deferral" not in res.stderr


# --- Follow-up 1: high-context defer WITHOUT a rotation action (RCA cluster A) -------


# --- Follow-up 2: phrase-scoped negation of stop/defer markers (RCA cluster A) -------


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


def test_host_sourced_rotation_passes(cli, run_cli):
    body = "Context at 80% (host counter). Refreshing continuity, running /compact now, then resuming the goal."
    res = guard(run_cli, body)
    assert "unprovenanced context-percent stop" not in (res.stdout + res.stderr)


# --- FIX-1: hedge overrides a host-claim word; host-source is negation-aware ----------


# --- FIX-2: permission detection covers the open class; over-broad markers removed -----


# --- FIX-3: unmeasured-escape must not exonerate a stop-adjacent fabricated percent ----


# --- Item 82: stop-guard evasion shapes ---------------------------------------------------------
# Three shapes that survived in an encoding the guard did not read (RCAs 20260616T005348Z,
# 20260616T132017Z, 20260701T115759Z). The policy prose for all three already existed; what did not
# exist was the enforcement.
