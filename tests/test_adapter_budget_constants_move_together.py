"""The two adapter byte ceilings gate the SAME artifact and must move together.

WHY THIS TEST EXISTS
--------------------
`MAX_EXAMPLE_CLAUDE_BYTES` (tests/test_rendered_adapter_budget.py) and
`MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES` (tests/test_generated_adapter_contract.py)
both bound the rendered `example-saas` adapter. Item 69 raised only the first --
the one whose test would have gone red -- and left the second 43 bytes tighter
than the number every later claimant was quoting. A passing suite hid the tighter
gate, and the corridor people budgeted against was not the corridor they had.

The existing fix was a COMMENT in both files stating the rule: "a cap raise must
enumerate EVERY constant gating the artifact, not just the one whose test would
have gone red." That comment is why the next raise was done correctly. But a
comment asking people to remember is not a control, and asking harder is not a
stronger control. This test makes the two constants unable to diverge, so the
rule is enforced by the suite rather than by recall.

If you are here because this test failed: you raised one ceiling and not the
other. Raise both, in the SAME commit, by the SAME measured delta, and record the
measurement in both files' comments as the existing convention requires.

WHAT IS AND IS NOT BILLED
-------------------------
Measured 2026-08-15, two independent ways: content added to
`methodology/canonical-rules.md` does NOT change the rendered adapter. Appending
500 bytes of filler left CLAUDE.md at 16,116 and AGENTS.md at 16,057, unchanged;
and separately, three items that grew canonical-rules.md by +907, +498 and +352
all rendered byte-identical. The renderer emits a PATH reference to that file and
never inlines it.

So the corridor under these ceilings is spent ONLY by editing the renderer's own
authored strings in `src/tautline_methodology/cli.py`. Rules, policy modules and
skill references are free. The question to ask of new prose is not "can this route
to a skill" but "does this touch cli.py's emitted text" -- and if it does not, no
measurement is needed.
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERED_BUDGET = REPO_ROOT / "tests" / "test_rendered_adapter_budget.py"
GENERATED_CONTRACT = REPO_ROOT / "tests" / "test_generated_adapter_contract.py"


def _read_int_constant(path: Path, name: str) -> int:
    """Parse `NAME = 1_234` out of a test module without importing it.

    Read rather than import: these modules define pytest fixtures and collect-time
    behavior, and this test is about the literal a human edits, not a runtime value.
    """
    source = path.read_text()
    match = re.search(rf"^{re.escape(name)}\s*=\s*([0-9_]+)\s*$", source, re.MULTILINE)
    assert match is not None, f"{name} not found as a module-level int literal in {path.name}"
    return int(match.group(1).replace("_", ""))


def test_both_adapter_byte_ceilings_are_equal():
    claude_cap = _read_int_constant(RENDERED_BUDGET, "MAX_EXAMPLE_CLAUDE_BYTES")
    markdown_cap = _read_int_constant(
        GENERATED_CONTRACT, "MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES"
    )

    assert claude_cap == markdown_cap, (
        "the two adapter byte ceilings gate the same artifact and have diverged: "
        f"MAX_EXAMPLE_CLAUDE_BYTES={claude_cap} in {RENDERED_BUDGET.name}, "
        f"MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES={markdown_cap} in {GENERATED_CONTRACT.name}. "
        "A cap raise must enumerate EVERY constant gating the artifact, not just the one whose "
        "test would have gone red -- raise both in the same commit by the same measured delta. "
        "Item 69 raised only one and left the corridor 43 bytes tighter than everyone was quoting."
    )
