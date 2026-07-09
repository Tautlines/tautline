"""arch-errors-8 (productization): the goal-boundary guard core fails toward its SAFE (blocking)
state when a goal-completion claim is present but the lane adapter is present-yet-unloadable, while
treating a *missing* adapter (no lane context) as a non-block.
"""

import json


def test_goal_boundary_fails_closed_on_unloadable_adapter(cli, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x")
    (tmp_path / ".minervit-ai-delivery.json").write_text("{ this is not valid json")
    errors = cli.response_guard_goal_boundary_errors(tmp_path, "The goal is complete and delivered.")
    assert errors, "a completion claim over an unloadable adapter must fail closed (block)"
    assert "could not be loaded" in errors[0]


def test_goal_boundary_no_block_when_no_adapter(cli, tmp_path):
    errors = cli.response_guard_goal_boundary_errors(tmp_path, "The goal is complete and delivered.")
    assert errors == []


def test_goal_boundary_no_block_without_completion_claim(cli, tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text(json.dumps({"project": "x"}))
    errors = cli.response_guard_goal_boundary_errors(tmp_path, "Still working on the implementation.")
    assert errors == []
