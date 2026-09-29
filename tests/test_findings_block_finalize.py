# tests/test_findings_block_finalize.py
"""A reviewer's own structured findings must be able to refuse a finalization that
contradicts them. Before R2 the framework had no machine-readable findings to consult;
after R2.5 it has them and ignores them, which is a capability that reads as a control."""




def _manifest(verdict="findings", severity="P1", source="structured"):
    return {
        "review_result_source": source,
        "review_result_verdict": verdict,
        "review_result_findings": (
            [{"id": "R1-1", "severity": severity, "file": "src/x.py", "line": 42,
              "summary": "unbounded retry loop"}] if severity else []
        ),
    }


def test_the_recorded_wrapper_round_trips_a_quoted_argument():
    """The writer shlex-JOINS and the reader shlex-SPLITS, so a wrapper carrying an argument
    with whitespace has to survive the round trip. A plain space-join wrote it back unquoted and
    the manifest this codebase produced was then rejected by its own finalization check."""
    import shlex

    parts = ["./review.sh", "--label", "foo bar"]
    assert shlex.split(shlex.join(parts)) == parts
