from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
# Raised 16000 -> 16043 (+43 bytes, the MEASURED delta) for item 69's template-version stamp:
# `<!-- tautline-template-version: X.Y.Z -->\n` on line 2 of every generated Markdown adapter.
#
# Raised by exactly the delta, on purpose. The RCA remediation program allocates the free bytes
# under this cap across six plans that each measured 320 free and each assumed sole ownership; the
# stamp is unconditional generated content, and the program's binding decision is that
# unconditional content raises this ceiling once with a measured number and a recorded decision
# rather than taking a slice. Measured on the PR tip: CLAUDE.md 15680 -> 15723, AGENTS.md
# 15621 -> 15664, so the headroom the six claimants budgeted against is still exactly 320.
# Raised 16_043 -> 16_318 (+275, the MEASURED delta) for item 101's PR-reference contract line,
# rendered inside the existing provider-pinned board block. Measured on this branch's tip by
# rendering example-saas to a scratch directory, never by reading a PR body: CLAUDE.md
# 15,841 -> 16,116 and AGENTS.md 15,782 -> 16,057, +275 on each.
#
# Raised in BOTH places that gate this artifact, in the same commit -- here and
# MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES in tests/test_generated_adapter_contract.py. That is
# item 71 PR2's rule, and it exists because item 69 raised only the constant whose test would
# have gone red and left the other 43 bytes tighter than every later claimant was quoting.
#
# A GRANT of new bytes, not a slice of anyone's: the corridor was 202 free before this raise
# (16,043 - 15,841) and is 202 free after it (16,318 - 16,116). The `per-lane-github-identity`
# lane's declared 200-byte claim on that corridor is therefore preserved untouched.
MAX_EXAMPLE_CLAUDE_BYTES = 16_318


def test_example_saas_rendered_claude_stays_within_phase4_budget(run_cli, tmp_path):
    target = tmp_path / "example-saas"
    target.mkdir()

    result = run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
    )

    assert result.returncode == 0, result.stderr
    rendered = target / "CLAUDE.md"
    assert rendered.exists()
    current = len(rendered.read_bytes())
    headroom = MAX_EXAMPLE_CLAUDE_BYTES - current
    assert current <= MAX_EXAMPLE_CLAUDE_BYTES, (
        f"rendered example-saas CLAUDE.md exceeds the byte budget "
        f"(current={current}, limit={MAX_EXAMPLE_CLAUDE_BYTES}, headroom={headroom}); "
        "trim/dedupe rendered sections in render_adapter (bin/minervit-methodology) "
        "-- do not raise this ceiling without a deliberate, reviewed decision"
    )
