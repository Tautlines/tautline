"""WS5 integration: cross-component wiring of the plan-authoring standard.

The four-level finalize-plan-review enforcement matrix is covered end-to-end by
tests/test_plan_authoring_guard.py. This file covers the wiring those unit/guard
tests do not: the shipped verb's self-consistency and the skill/module contract.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tautline_methodology import plan_authoring as pa  # noqa: E402

CLI = REPO_ROOT / "bin" / "tautline"


def _run(*args: str) -> subprocess.CompletedProcess:
    env = {"PYTHONPATH": str(SRC_ROOT)}
    import os

    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_verb_hook_mode_exits_zero_and_prints_standard():
    result = _run("plan-authoring-standard", "--hook")
    assert result.returncode == 0
    assert "PLAN-AUTHORING STANDARD" in result.stdout


def test_shipped_standard_text_names_the_markers_it_enforces():
    """The verb's emitted guidance must describe the same three elements the
    checker enforces, or authors are told to produce a shape the guard rejects."""
    text = pa.STANDING_PLAN_AUTHORING_STANDARD_CORE.lower()
    assert "workstream" in text
    assert "model-tier" in text
    assert "best judgment" in text and "decision-record" in text


def test_skill_wraps_writing_plans_and_names_the_verb():
    skill = (
        REPO_ROOT
        / "plugins/tautline-core/skills/plan-authoring/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "superpowers:writing-plans" in skill
    assert "plan-authoring-standard" in skill


def test_canonical_rule_present_for_the_knob():
    rules = (REPO_ROOT / "methodology/canonical-rules.md").read_text(encoding="utf-8")
    assert "planning.authoringStandard.enforcement" in rules
