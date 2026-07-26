"""The plan-review log frame: which text is THIS round's reviewer output.

Item 25 (plan-review log verbatim replay). `run_plan_review` frames captured output with two
sentinel lines, and the reviewer routinely prints text containing them -- it greps the codebase
(the constants are source lines) and it reads previous round logs as evidence, which is
legitimate review behavior. The old parser split on the FIRST end marker, so on any such log the
captured block closed early and the finalize-time blocker scan graded the previous round's
findings. Reproduced against a stored log: 19 of 121 backlog logs closed early.
"""

REAL_BLOCKER = (
    "## Findings\n\n"
    "### Critical\n- None.\n\n"
    "### P1\n- The launcher deletes user data on startup.\n\n"
    "### P2\n- None.\n"
)

QUOTED_CLEAN = (
    "## Findings\n\n"
    "### Critical\n- None.\n\n"
    "### P1\n- None.\n\n"
    "### P2\n- None.\n"
)


def _frame(body, *, nonce=""):
    """A run log exactly as run_plan_review writes one."""
    suffix = f" run:{nonce}" if nonce else ""
    return (
        "MINERVIT_PLAN_REVIEW_RUN_V1\n"
        "plan_path: docs/plans/thing.md\n"
        f"--- review output ---{suffix}\n"
        f"{body}\n"
        f"--- review metadata ---{suffix}\n"
        "finished_at: 2026-07-26T00:00:00Z\n"
        "wrapper_exit_code: 0\n"
    )


def _echoed_footer(body, *, nonce=""):
    """A complete foreign frame, as it appears when the reviewer cats another round's log."""
    suffix = f" run:{nonce}" if nonce else ""
    return (
        f"--- review output ---{suffix}\n"
        f"{body}\n"
        f"--- review metadata ---{suffix}\n"
        "finished_at: 2026-07-25T00:00:00Z\n"
        "wrapper_exit_code: 0\n"
    )


def test_verdict_scan_sees_blockers_after_an_echoed_footer(cli):
    """The regression that matters. The reviewer quotes a prior round's clean log, then reports a
    real blocker. Before the frame fix the scan stopped at the echoed footer and never saw it, so
    `--unresolved-p1-count 0` sailed through the guard that exists to catch exactly that."""
    log = _frame(_echoed_footer(QUOTED_CLEAN) + "\ncodex\n" + REAL_BLOCKER)

    errors = cli.review_log_verdict_errors(
        log, "clean-with-deferrals", 0, 0, [], authoritative=True
    )

    assert errors, "a P1 reported after an echoed footer must still be flagged"


def test_echoed_end_marker_does_not_truncate_legacy_frame(cli):
    """Same log, scoping level: the span runs to the REAL footer, not the echoed one."""
    log = _frame(_echoed_footer(QUOTED_CLEAN) + "\ncodex\n" + REAL_BLOCKER)

    output = cli.review_output_text(log, authoritative=True)

    assert "deletes user data" in output
    # The QUOTED footer is reviewer output and stays; THIS run's own footer is not and must not.
    assert "2026-07-25T00:00:00Z" in output, "quoted material is content, not frame"
    assert "2026-07-26T00:00:00Z" not in output, "this run's own footer is not reviewer output"


def test_nonce_frame_ignores_a_foreign_nonce(cli):
    """A quoted frame carries ITS nonce, not ours; only the matching pair bounds this run."""
    log = _frame(
        _echoed_footer(QUOTED_CLEAN, nonce="feedfeed") + "\ncodex\n" + REAL_BLOCKER,
        nonce="abc123",
    )

    output = cli.review_output_text(log, expected_nonce="abc123", authoritative=True)

    assert "deletes user data" in output


def test_quoted_frame_after_own_findings_is_not_selected(cli):
    """The order the last-heading rule gets wrong on its own: the reviewer answers first, then
    quotes another round. Selection must still return the reviewer's own block."""
    log = _frame(
        REAL_BLOCKER + "\n" + _echoed_footer(QUOTED_CLEAN, nonce="feedfeed"),
        nonce="abc123",
    )

    section = cli.review_findings_section(log, expected_nonce="abc123", authoritative=True)

    assert "deletes user data" in section


def test_quoted_frame_before_own_findings_is_not_selected(cli):
    """The mirror order, which the old rule happened to get right; both must hold."""
    log = _frame(
        _echoed_footer(QUOTED_CLEAN, nonce="feedfeed") + "\n" + REAL_BLOCKER,
        nonce="abc123",
    )

    section = cli.review_findings_section(log, expected_nonce="abc123", authoritative=True)

    assert "deletes user data" in section


def test_import_path_parses_the_whole_log(cli):
    """No authority: a file this tool did not write carries no trustworthy boundary, so the
    verdict scan reads it whole. Real findings outside a quoted frame stay visible."""
    log = "imported transcript\n" + _echoed_footer(QUOTED_CLEAN) + "\n" + REAL_BLOCKER

    errors = cli.review_log_verdict_errors(log, "clean-with-deferrals", 0, 0, [])

    assert errors


def test_import_path_ignores_a_quoted_frame_after_the_real_findings(cli):
    """Same import with the order reversed."""
    log = "imported transcript\n" + REAL_BLOCKER + "\n" + _echoed_footer(QUOTED_CLEAN)

    errors = cli.review_log_verdict_errors(log, "clean-with-deferrals", 0, 0, [])

    assert errors


def test_import_of_a_single_framed_log_keeps_its_findings(cli):
    """The fallback arm. An import whose whole content is one ordinary framed log has every
    candidate heading inside a frame; excising them would leave nothing, and an empty scan reads
    as CLEAN -- the same failure inverted. The blockers must stay visible."""
    log = _frame(REAL_BLOCKER)

    errors = cli.review_log_verdict_errors(log, "clean-with-deferrals", 0, 0, [])

    assert errors


def test_stale_expected_nonce_falls_back_to_positional_scoping(cli):
    """A nonce that appears nowhere is stale metadata, not a reason to return nothing."""
    log = _frame(REAL_BLOCKER, nonce="abc123")

    output = cli.review_output_text(log, expected_nonce="nosuchnonce", authoritative=True)

    assert "deletes user data" in output


def test_unterminated_log_scopes_to_the_end(cli):
    """A watchdog-killed run never wrote a footer; its output is still its output."""
    log = "header\n--- review output --- run:abc123\n" + REAL_BLOCKER

    output = cli.review_output_text(log, expected_nonce="abc123", authoritative=True)

    assert "deletes user data" in output


def test_log_without_a_frame_falls_back_to_whole_text(cli):
    """No start marker at all behaves exactly as it did before this change."""
    log = "just a transcript\n" + REAL_BLOCKER

    assert cli.review_output_text(log, authoritative=True) == log
    assert "deletes user data" in cli.review_findings_section(log, authoritative=True)


def test_identity_check_rejects_a_plan_reference_only_outside_the_frame(cli):
    """The deliberate asymmetry: the verdict scan widens on an unauthoritative log, but the
    IDENTITY check must not. A header or an echoed review_command naming the plan cannot stand in
    for the reviewer's own output referencing it."""
    plan_rel = "docs/plans/thing.md"
    plan_hash = "a" * 64
    command = f"codex-review --plan {plan_rel}"
    log = (
        f"review_command: {command}\n"
        f"plan_path: {plan_rel}\n"
        "--- review output ---\n"
        "the reviewer never names the plan here\n"
        "--- review metadata ---\n"
        "finished_at: 2026-07-26T00:00:00Z\n"
    )

    errors = cli.review_log_errors(log, command, plan_rel, plan_hash)

    assert any("must reference the reviewed plan" in error for error in errors)


def test_identity_check_accepts_a_reference_inside_the_frame(cli):
    """The same log with the reviewer actually naming the plan passes."""
    plan_rel = "docs/plans/thing.md"
    plan_hash = "a" * 64
    command = f"codex-review --plan {plan_rel}"
    log = (
        f"review_command: {command}\n"
        "--- review output ---\n"
        f"Reviewing {plan_rel} as requested.\n"
        "--- review metadata ---\n"
        "finished_at: 2026-07-26T00:00:00Z\n"
    )

    assert cli.review_log_errors(log, command, plan_rel, plan_hash) == []


def test_imported_framed_log_does_not_fall_back_to_a_quoted_clean_block(cli):
    """0.23.0 implementation review R1 (P2): an import is scoped whole, so the file's OWN frame is
    in view alongside any quoted one. Greedy sentinel pairing matched the outer start to the inner
    footer, which made the whole file read as one quoted span, marked every heading nested, and
    sent selection to the fallback -- landing on the quoted CLEAN block while the reviewer's real
    P1 sat above it. Pairing is stack-based now, and on a whole-file scope only frames strictly
    inside the outermost one count as quotes."""
    log = "imported transcript\n" + _frame(
        REAL_BLOCKER + "\n" + _echoed_footer(QUOTED_CLEAN)
    )

    errors = cli.review_log_verdict_errors(log, "clean-with-deferrals", 0, 0, [])

    assert errors, "the reviewer's own P1 must still be graded, not the quoted clean block"


def test_clean_answer_followed_by_quoted_blockers_stays_clean(cli):
    """0.23.0 implementation review R2 (P2): the reviewer answers CLEAN and then pastes a prior
    log whose findings carry a blocker. The chosen heading sits outside every frame, so the span
    ran to end-of-scope and the scan read the quoted blocker -- refusing a genuinely clean round.
    A false refusal fails closed, but it is still a refusal nobody can act on."""
    quoted_blockers = _echoed_footer(REAL_BLOCKER, nonce="feedfeed")
    log = _frame(QUOTED_CLEAN + "\n" + quoted_blockers, nonce="abc123")

    errors = cli.review_log_verdict_errors(
        log, "clean-with-deferrals", 0, 0, [], expected_nonce="abc123", authoritative=True
    )

    assert errors == [], "quoted blockers after a clean answer must not refuse the clean round"


def test_a_blocker_after_a_quoted_frame_is_still_seen(cli):
    """0.24.0 implementation review R1 (P1). The first attempt at the case above TRUNCATED the
    section at the quoted frame, which hid anything the reviewer wrote afterwards -- turning a
    false refusal into a false PASS, the failure this whole line of work removes. Quoted spans are
    excised, not cut at, so text on BOTH sides of a quote is still graded."""
    quoted = _echoed_footer(QUOTED_CLEAN, nonce="feedfeed")
    log = _frame(
        "## Findings\n\n### P2\n- a note.\n" + quoted + REAL_BLOCKER, nonce="abc123"
    )

    errors = cli.review_log_verdict_errors(
        log, "clean-with-deferrals", 0, 0, [], expected_nonce="abc123", authoritative=True
    )

    assert errors, "a blocker written after a quoted frame must still be graded"


def test_real_blocker_before_a_quoted_clean_block_still_flags(cli):
    """The mirror, so the span cap cannot be used to hide a real finding: the reviewer reports a
    blocker and then quotes a clean log."""
    quoted_clean_only = _echoed_footer(QUOTED_CLEAN, nonce="feedfeed")
    log = _frame(REAL_BLOCKER + "\n" + quoted_clean_only, nonce="abc123")

    errors = cli.review_log_verdict_errors(
        log, "clean-with-deferrals", 0, 0, [], expected_nonce="abc123", authoritative=True
    )

    assert errors
