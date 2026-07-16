"""Ratchet guard: the global E501 ignore is a frozen baseline, not a license to grow.

This guard freezes a ceiling: the measured E501 (line-too-long) hit count may
not exceed the baseline below. It does not by itself force the number down —
lowering `E501_BASELINE` after a cleanup fixes overlong lines is a manual step
this docstring is asking for. Please do that whenever you knock the count down.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E501_BASELINE = 6442
LINT_PATHS = ("bin/tautline", "src", "tests")

# A measured count of 0 across the whole repo would mean ruff silently linted
# nothing (e.g. every path in LINT_PATHS went missing) rather than that the
# codebase is genuinely clean. If a real cleanup ever drives the count to 0,
# retire this guard instead of trusting a silent zero.
MIN_PLAUSIBLE_COUNT = 1


def test_e501_count_does_not_grow() -> None:
    for rel_path in LINT_PATHS:
        assert (REPO_ROOT / rel_path).exists(), (
            f"Lint path {rel_path!r} does not exist under {REPO_ROOT}. "
            "This ratchet guard hardcodes LINT_PATHS in "
            "tests/test_lint_ratchet.py — update that list to match the "
            "repo layout (e.g. after a package split of bin/tautline) so "
            "the guard keeps measuring real files instead of passing "
            "vacuously."
        )

    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            *LINT_PATHS,
            "--select", "E501", "--output-format", "json", "--exit-zero",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )

    assert "Failed to lint" not in result.stderr, (
        "ruff reported a lint failure on stderr even though it exited 0 "
        "(ruff --exit-zero masks this in the exit code):\n"
        f"{result.stderr}"
    )

    count = len(json.loads(result.stdout))

    assert count >= MIN_PLAUSIBLE_COUNT, (
        f"Measured E501 count is {count}, below the plausibility floor of "
        f"{MIN_PLAUSIBLE_COUNT}. The real count is normally in the "
        "thousands, so this almost certainly means the guard measured "
        "nothing (e.g. a lint path silently failed) rather than that the "
        "codebase got clean. If overlong lines have genuinely been "
        "eliminated repo-wide, retire this guard instead of accepting a "
        "silent zero."
    )

    assert count <= E501_BASELINE, (
        f"E501 hits grew to {count} (baseline {E501_BASELINE}). "
        "Fix the new overlong lines instead of raising the baseline."
    )
