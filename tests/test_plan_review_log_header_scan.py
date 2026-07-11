"""Severity section HEADERS with empty ('- None.') bodies must not be flagged
as unresolved-finding mentions by the finalize log scan (2026-07-10 regression:
a clean-with-deferrals log using '### Critical\n- None.' sections could not be
finalized at zero Critical/P1)."""

CLEAN_SECTIONED_FINDINGS = (
    "## Findings\n\n"
    "### Critical\n- None.\n\n"
    "### P1\n- None.\n\n"
    "### P2\n- **A real minor finding about tests.**\n\n"
    "### P3\n- None.\n"
)

REAL_P1_FINDINGS = (
    "## Findings\n\n"
    "### Critical\n- None.\n\n"
    "### P1\n- [P1] A real blocker exists here.\n\n"
    "### P2\n- None.\n"
)

# Codex T7 R4 P1: a NON-EMPTY severity section whose bullets do not repeat the
# severity word. The bare-header skip must not treat this header as structure.
IMPLICIT_P1_FINDINGS = (
    "## Findings\n\n"
    "### Critical\n- None.\n\n"
    "### P1\n- The launcher deletes user data on startup.\n\n"
    "### P2\n- None.\n"
)

# Header at end of findings with no body at all: still an empty section.
TRAILING_EMPTY_HEADER_FINDINGS = (
    "## Findings\n\n"
    "### P2\n- A real minor finding about tests.\n\n"
    "### P1\n"
)


def _wrap(findings: str) -> str:
    return "prompt noise\n--- review output ---\n" + findings + "\n--- review metadata ---\n"


def test_header_only_sections_do_not_flag_zero_counts(cli):
    errors = cli.review_log_verdict_errors(
        _wrap(CLEAN_SECTIONED_FINDINGS), verdict="clean-with-deferrals",
        unresolved_critical_count=0, unresolved_p1_count=0, classified_findings=[],
    )
    assert errors == []


def test_real_p1_bullet_still_flags_zero_counts(cli):
    errors = cli.review_log_verdict_errors(
        _wrap(REAL_P1_FINDINGS), verdict="clean-with-deferrals",
        unresolved_critical_count=0, unresolved_p1_count=0, classified_findings=[],
    )
    assert errors, "a real P1 bullet must still be flagged"


def test_p1_section_with_unlabeled_bullet_still_flags_zero_counts(cli):
    errors = cli.review_log_verdict_errors(
        _wrap(IMPLICIT_P1_FINDINGS), verdict="clean-with-deferrals",
        unresolved_critical_count=0, unresolved_p1_count=0, classified_findings=[],
    )
    assert errors, "a non-empty P1 section must be flagged even when its bullets do not repeat the severity"


def test_trailing_empty_severity_header_does_not_flag_zero_counts(cli):
    errors = cli.review_log_verdict_errors(
        _wrap(TRAILING_EMPTY_HEADER_FINDINGS), verdict="clean-with-deferrals",
        unresolved_critical_count=0, unresolved_p1_count=0, classified_findings=[],
    )
    assert errors == []
