"""Track G: goal-advice salvage.

The pre-demolition goal-tracker subsystem (`goal_assignment.py`, `10-goal-orchestration.md`,
`GOAL_RUN.json`, milestone/board binding) is gone and stays gone -- this covers only what
survived the salvage: the composition advice in `docs/reference/goals.md`, the `/goal` skill that
follows it, and the plugin-enablement hint `slim` (and `init`, once it exists) prints.

`docs/reference/goals.md` and the `/goal` skill are prose, covered here by content checks, the
same pattern `tests/test_continuity_handoffs.py` (Track H) uses for `/handoff`. The enablement
hint is a real code path in `lean.py`, covered end to end through `format_slim_summary` and once
through the real CLI, same as the rest of `tests/test_lean_profile.py`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tautline_methodology import lean

REPO_ROOT = Path(__file__).resolve().parents[1]
GOALS_DOC = REPO_ROOT / "docs" / "reference" / "goals.md"
GOAL_SKILL = REPO_ROOT / "plugins" / "tautline-core" / "skills" / "goal" / "SKILL.md"
LEAN_MIGRATION_DOC = REPO_ROOT / "docs" / "reference" / "lean-migration.md"
HANDOFFS_DOC = REPO_ROOT / "docs" / "reference" / "handoffs.md"

ENABLEMENT_ANCHOR = "docs/reference/lean-migration.md#enable-the-claude-code-plugin"

CHECKLIST_ITEMS = (
    "- [ ] One outcome, stated as a single sentence",
    "- [ ] Points at the plan/spec/issue instead of restating it",
    "- [ ] States what may be touched, and what may not when that matters",
    '- [ ] "Done when:" names a falsifiable bar, not a feeling',
    "- [ ] Names one proof command",
    "- [ ] Reads as one flat paragraph, no fence, comfortably under ~4000 characters",
)


# --- the doc: docs/reference/goals.md -----------------------------------------------------------


def test_goals_doc_carries_the_checklist():
    text = GOALS_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## The checklist" in text
    for item in CHECKLIST_ITEMS:
        assert item in text, item
    # The two-line checklist entries, reflowed so a wrap in the source file doesn't hide them.
    assert (
        "The bar names the actual handoff line -- merged, or armed to merge (auto-merge or merge "
        "queue) -- not just \"a PR is open\""
        in normalized
    )
    assert (
        "Adds only what's goal-specific -- does not restate the ambient working norms already in "
        "the adapter"
        in normalized
    )


def test_goals_doc_states_the_anatomy_and_the_handoff_bar():
    text = GOALS_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## The anatomy of a good goal" in text
    assert "A single outcome." in text
    assert "A pointer, not a copy." in text
    assert "A scope boundary." in text
    assert 'A measurable "Done when."' in text
    assert "The actual handoff line." in text
    assert "An explicit autonomy grant." not in text, "autonomy is ambient now, not a per-goal item"
    assert "One proof command." in text
    assert "Flat and tight." in text
    assert "merged, or armed to merge" in normalized
    assert "auto-merge or merge queue" in normalized
    assert "4000 characters" in normalized


def test_goals_doc_explains_the_ambient_working_norms():
    """Operator-directed addition: standing working norms now live in the rendered adapter
    (lean.WORKING_STYLE_LINES), so a goal adds only what is goal-specific. The doc explains the
    CONCEPT and points at the adapter as the source of truth -- it must not quote the adapter's
    exact bullet text verbatim, which would just be a second copy that could drift from the first.
    """
    text = GOALS_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## Ambient working norms" in text
    assert "autonom" in normalized.lower()
    assert "blocked" in normalized.lower()
    assert "subagent" in normalized.lower()
    assert "evidence" in normalized.lower()
    assert "does not restate it" in normalized or "do not restate" in normalized.lower()
    assert "drift" in normalized.lower()
    for line in lean.WORKING_STYLE_LINES:
        assert line not in text, "the doc must not carry a second, driftable copy of the adapter text"


def test_goals_doc_carries_a_worked_example_under_the_practical_budget():
    text = GOALS_DOC.read_text(encoding="utf-8")
    assert "## A worked example" in text
    assert "Done when:" in text
    assert "Proof: `pytest" in text
    # The example must NOT restate the ambient norms -- that is the whole point of them being
    # ambient, and the doc's own prose right after the example says so.
    assert "The human is away" not in text
    assert "Work autonomously --" not in text


def test_goals_doc_states_the_bare_output_contract():
    text = GOALS_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## Handing it over" in text
    assert "the response IS the goal" in normalized
    assert "no code fence" in normalized
    assert "goes in its own message BEFORE the goal" in normalized


def test_goals_doc_references_the_skill_and_the_enablement_section():
    text = GOALS_DOC.read_text(encoding="utf-8")
    assert "plugins/tautline-core/skills/goal/SKILL.md" in text
    assert ENABLEMENT_ANCHOR in text
    assert "docs/reference/handoffs.md" in text


# --- the skill: plugins/tautline-core/skills/goal/SKILL.md --------------------------------------


def test_goal_skill_is_a_concise_compose_and_handoff_entrypoint():
    text = GOAL_SKILL.read_text(encoding="utf-8")
    lines = text.splitlines()
    normalized = " ".join(text.split())

    assert len(lines) <= 45, f"{len(lines)} lines; the repo's skill lint caps core skills at 45"
    assert lines[0] == "---"
    assert "name: goal" in lines
    assert "docs/reference/goals.md" in text
    assert "Done when:" in text
    assert "auto-merge or merge queue" in normalized
    assert "One proof command" in normalized or "proof command" in normalized


def test_goal_skill_does_not_restate_the_ambient_norms():
    """Operator-directed addition: the standing working-style block is ambient (every generated
    adapter), so composing a goal must not spend budget restating it -- and must not carry a
    driftable second copy of the adapter's own bullet text."""
    text = GOAL_SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Do not restate autonomy" in text
    assert "standing" in normalized.lower()
    assert "That the human is away" not in text, "the old restated-autonomy bullet must be gone"
    for line in lean.WORKING_STYLE_LINES:
        assert line not in text


def test_goal_skill_states_the_bare_output_contract():
    text = GOAL_SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## Hand over" in text
    assert "no preamble" in normalized
    assert "no code fence" in normalized
    assert "in their own message BEFORE the goal" in normalized
    assert "A whole-response copy must yield exactly the goal text" in normalized


def test_goal_skill_frontmatter_description_has_no_unquoted_colon():
    """The same class of defect `test_skill_frontmatter_parses.py` guards repo-wide, re-asserted
    here because a broken frontmatter loads with EMPTY metadata rather than failing loudly."""
    text = GOAL_SKILL.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3
    frontmatter = parts[1]
    for line in frontmatter.strip().splitlines():
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            assert ": " not in value, value


# --- the enablement section: docs/reference/lean-migration.md -----------------------------------


def test_lean_migration_doc_documents_plugin_enablement():
    text = LEAN_MIGRATION_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## Enable the Claude Code plugin" in text
    assert "/plugin marketplace add ./" in text
    assert "/plugin install tautline-core@tautline" in text
    assert "/goal" in text
    assert "/handoff" in text
    assert "lane-status" in normalized
    assert "/plugin marketplace add tautlines/tautline" in text


def test_handoffs_doc_references_the_enablement_section():
    text = HANDOFFS_DOC.read_text(encoding="utf-8")
    assert ENABLEMENT_ANCHOR in text


# --- the hint: lean.PLUGIN_ENABLEMENT_HINT, printed by slim ------------------------------------


LEGACY_MINIMAL = {
    "schemaVersion": "1.0.0",
    "project": "Widget Co",
    "repo": "widget-org/widget",
    "latestCode": {"base": "develop", "remote": "origin"},
    "commands": {"fullPreflight": "make check", "fastPreflight": "make fast"},
    "review": {"roundBudgets": {"T1": 2}, "codexWrapper": "./scripts/codex-review.sh"},
    "knownProjectRules": ["Tenants are isolated at the query layer."],
    "technologyStack": {"nonNegotiable": ["No plaintext secrets."]},
    "planningArtifacts": {"sourceOfTruth": "docs/plans/"},
}


def _write_legacy(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / ".tautline.json").write_text(
        json.dumps(LEGACY_MINIMAL, indent=2) + "\n", encoding="utf-8"
    )


def test_hint_names_the_enablement_section_and_the_activated_surfaces():
    normalized = " ".join(lean.PLUGIN_ENABLEMENT_HINT.split())
    assert "/goal" in normalized
    assert "/handoff" in normalized
    assert "lane-status" in normalized
    assert ENABLEMENT_ANCHOR in normalized


def test_slim_summary_prints_the_hint_on_a_real_migration(tmp_path):
    target = tmp_path / "project"
    _write_legacy(target)

    result = lean.slim_project(target)
    assert result.changed

    summary = "\n".join(lean.format_slim_summary(target, result, dry_run=False))
    assert f"  next      {lean.PLUGIN_ENABLEMENT_HINT}" in summary
    # after the rollback note, before any FAILED section -- never buried above the change list
    assert summary.index("rollback:") < summary.index(lean.PLUGIN_ENABLEMENT_HINT)


def test_slim_summary_prints_the_hint_on_a_dry_run(tmp_path):
    target = tmp_path / "project"
    _write_legacy(target)

    result = lean.slim_project(target, dry_run=True)
    summary = "\n".join(lean.format_slim_summary(target, result, dry_run=True))
    assert lean.PLUGIN_ENABLEMENT_HINT in summary


def test_slim_summary_prints_the_hint_when_already_lean(tmp_path):
    target = tmp_path / "project"
    _write_legacy(target)
    lean.slim_project(target)  # first run: migrates
    second = lean.slim_project(target)  # second run: no-op
    assert second.changed is False

    summary = "\n".join(lean.format_slim_summary(target, second, dry_run=False))
    assert "already lean - no changes" in summary
    assert lean.PLUGIN_ENABLEMENT_HINT in summary


def test_slim_command_prints_the_hint_end_to_end(tmp_path, capsys):
    target = tmp_path / "project"
    _write_legacy(target)
    args = argparse.Namespace(target=str(target), dry_run=False, keep_agent_hooks=True)

    assert lean.slim_command(args) == 0
    out = capsys.readouterr().out
    assert lean.PLUGIN_ENABLEMENT_HINT in out


# --- the hint, also wired into `tautline init` (#619) --------------------------------------------
#
# Same constant as slim's -- deliberately reused rather than a second hand-written line, per the
# coordinator's item 1: `init` and `slim` are the two commands that leave a project without the
# Claude Code plugin enabled, and both now point at the exact same next step.

_INIT_FLAG_DEFAULTS = dict(
    name=None,
    repo=None,
    branch=None,
    test_cmd=None,
    backlog=None,
    backlog_path=None,
    backlog_repo=None,
    backlog_label=None,
    backlog_site=None,
    backlog_project=None,
    backlog_board=None,
    handoffs=None,
    rules=None,
    yes=False,
    force=False,
)


def _init_ns(target: Path, **overrides) -> argparse.Namespace:
    values = dict(_INIT_FLAG_DEFAULTS, target=target, **overrides)
    return argparse.Namespace(**values)


def test_what_next_lines_carries_the_hint_as_a_sixth_line():
    cfg = {"schemaVersion": "lean-1", "project": {"name": "Widget"}, "backlog": {"provider": "local"}}
    lines = lean._what_next_lines(cfg)
    assert len(lines) == 7  # the "what next:" header plus 6 numbered lines
    assert lines[-1] == f"  6. {lean.PLUGIN_ENABLEMENT_HINT}"


def test_init_command_prints_the_hint_end_to_end(tmp_path, capsys):
    target = tmp_path / "widget"
    target.mkdir()

    assert lean.init_command(_init_ns(target, yes=True)) == 0
    out = capsys.readouterr().out
    assert "what next:" in out
    assert lean.PLUGIN_ENABLEMENT_HINT in out
