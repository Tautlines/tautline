"""Keep scripts/validate.sh as a thin wrapper (arch-validate-tests-1/2).

The productization audit (arch-validate-tests-1
"Freeze validate.sh (byte budget)" and arch-validate-tests-2 "Retire validate.sh as a
product liability") found that validate.sh is the single largest single-source-of-truth
liability: ~711KB of grep-based prose pins that grew rather than shrank since the prior
audit, with multiple RCAs each appending one more `grep -q` line by hand. Every new pin
is duplication that an enumerated denylist can never make complete, and the file is an
OSS-contributor and onboarding killer.

The shell assertions have been ported or retired. `scripts/validate.sh` is now only a
compatibility wrapper around `scripts/test.sh` so existing branch protection and muscle
memory keep working while pytest owns behavior coverage.

Any future validation behavior belongs in pytest, not in this wrapper.
"""

import re
import subprocess
import sys
from pathlib import Path

# Recorded at the wrapper line count with NO slack: any growth fails the gate.
BUDGET_LINES = 5
EXTERNAL_PROCESS_BUDGET = {
    "awk": 0,
    "cat": 0,
    "cp": 0,
    "find": 0,
    "git": 0,
    "grep": 0,
    "mkdir": 0,
    "mktemp": 0,
    "mv": 0,
    "python3": 0,
    "rm": 0,
    "sed": 0,
    "tail": 0,
    "wc": 0,
}

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_SH = REPO_ROOT / "scripts" / "validate.sh"
TEST_SH = REPO_ROOT / "scripts" / "test.sh"
CI_PYTHON_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python.yml"
VALIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
PULL_REQUEST_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"


def _line_count(path: Path) -> int:
    # Count newline-terminated lines the way `wc -l` does (the audit's measurement).
    with path.open("rb") as fh:
        return fh.read().count(b"\n")


def _external_process_counts(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    return {
        tool: len(re.findall(rf"(?<![\w./-]){re.escape(tool)}(?=\s|$)", text))
        for tool in EXTERNAL_PROCESS_BUDGET
    }


def test_validate_sh_stays_a_thin_wrapper():
    actual = _line_count(VALIDATE_SH)
    assert actual <= BUDGET_LINES, (
        f"scripts/validate.sh grew to {actual} lines (budget {BUDGET_LINES}). "
        "validate.sh has been retired to a compatibility wrapper; put validation "
        "behavior in pytest instead of shell."
    )
    text = VALIDATE_SH.read_text(encoding="utf-8")
    assert 'PATH="${ROOT}/.venv/bin:${PATH}" "${ROOT}/scripts/test.sh"' in text


def test_validate_sh_external_process_sites_are_frozen():
    actual = _external_process_counts(VALIDATE_SH)
    assert actual == EXTERNAL_PROCESS_BUDGET, (
        "scripts/validate.sh external process sites changed. validate.sh is retired: "
        "new validation behavior belongs in pytest, not shell subprocesses. "
        f"expected={EXTERNAL_PROCESS_BUDGET!r} actual={actual!r}"
    )


def test_validate_freeze_budget_has_no_slack():
    # The budget must equal the current size (no headroom): if validate.sh SHRINKS,
    # ratchet BUDGET_LINES down to match so the freeze keeps holding the new ceiling.
    actual = _line_count(VALIDATE_SH)
    assert actual == BUDGET_LINES, (
        f"scripts/validate.sh is now {actual} lines but BUDGET_LINES={BUDGET_LINES}. "
        "Keep the wrapper budget exact with no slack."
    )


def test_validate_and_pytest_gates_stay_paired():
    test_sh = TEST_SH.read_text(encoding="utf-8")
    ci_python = CI_PYTHON_WORKFLOW.read_text(encoding="utf-8")
    validate = VALIDATE_WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in ci_python
    assert "pull_request:" in validate
    assert "push:" in ci_python
    assert "push:" in validate
    assert "\npytest\n" in test_sh
    assert "pytest tests/" not in test_sh
    assert "scripts/test.sh" in ci_python
    assert "scripts/validate.sh" in validate


def test_xdist_preflight_probe_matches_the_pytest_actually_in_use():
    """The gate's own preflight must not fail closed on a healthy toolchain.

    The probe reads `pytest --help` and refuses to run if xdist looks absent. Python
    3.13 changed argparse to print a short/long option pair once rather than per-alias,
    so the pinned xdist renders `-n numprocesses, --numprocesses numprocesses` on 3.12
    but `-n, --numprocesses numprocesses` on 3.13+. A probe keyed to the short-option
    spelling passed CI's 3.12 leg while telling every 3.13+ developer to install a
    toolchain they already had. Assert against the interpreter running the suite.
    """
    probe = re.search(r'^\s*\*"([^"]+)"\*\)\s*;;', TEST_SH.read_text(encoding="utf-8"), re.M)
    assert probe, "could not find the xdist preflight probe pattern in scripts/test.sh"

    help_text = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "numprocesses" in help_text, "pytest-xdist is genuinely missing; cannot judge the probe"
    assert probe.group(1) in help_text, (
        f"scripts/test.sh probes for {probe.group(1)!r}, which does not appear in "
        f"`pytest --help` on Python {sys.version_info.major}.{sys.version_info.minor}. "
        "The gate would refuse to run despite a healthy toolchain."
    )
