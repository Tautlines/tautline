from pathlib import Path

import pytest

PUBLIC_EXPORT_MARKER = Path(__file__).resolve().parents[1] / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; the export has no git remote to verify",
)

GOAL_KICKOFF_MARKERS = (
    "Work on the next active Minervit goal",
    "methodology-status --target /tmp/example-lane --fail-on-drift",
    "start Claude `/goal`",
    "goal-condition --target /tmp/example-lane",
    "backlog-provider-next --target /tmp/example-lane",
    "backlog-provider-sync --target /tmp/example-lane",
    "publish-pending-session-journals --target /tmp/example-lane",
    "adapter-declared exemption",
    "review-before-push gates",
    "goal-next --target /tmp/example-lane",
    "next_goal_name",
    "next_goal_short_description",
    "next_goal_claude_prompt",
)


def test_goal_kickoff_prompt_preserves_unmanaged_startup_contract(run_cli):
    result = run_cli("goal-kickoff-prompt", "--target", "/tmp/example-lane")

    assert result.returncode == 0, result.stderr
    missing = [marker for marker in GOAL_KICKOFF_MARKERS if marker not in result.stdout]
    assert missing == []


@private_repo_only
def test_goal_kickoff_prompt_uses_methodology_repo_self_adapter(run_cli):
    result = run_cli("goal-kickoff-prompt", "--target", ".")

    assert result.returncode == 0, result.stderr
    assert "goal_kickoff_mode: no-active-goal" in result.stdout
    assert "next_goal_source: repo-goal-plans" in result.stdout
    assert "next_goal_name:" in result.stdout
    assert "next_goal_claude_prompt:" in result.stdout
    assert "next_goal_next_action:" in result.stdout


def test_goal_kickoff_prompt_uses_requested_target(run_cli):
    result = run_cli("goal-kickoff-prompt", "--target", "/tmp/example-lane")

    assert result.returncode == 0, result.stderr
    assert "lane-start --target /tmp/example-lane" in result.stdout


def test_goal_kickoff_prompt_fails_cleanly_on_invalid_generated_adapter(run_cli, tmp_path):
    target = tmp_path / "invalid-generated-adapter"
    target.mkdir()
    (target / ".minervit-ai-delivery.json").write_text(
        "\n".join(
            [
                "{",
                '  "project": "Invalid Fixture",',
                "<<<<<<< HEAD",
                '  "repo": "local"',
                "=======",
                '  "repo": "remote"',
                ">>>>>>> origin/main",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli("goal-kickoff-prompt", "--target", str(target))

    assert result.returncode == 1
    assert ".minervit-ai-delivery.json: invalid JSON" in result.stderr
    assert "unresolved Git conflict markers are present" in result.stderr
    assert (
        "render-adapters --project <methodology_repo>/adapters/projects/<project>.json "
        "--target <lane> --write --json-only"
    ) in result.stderr
