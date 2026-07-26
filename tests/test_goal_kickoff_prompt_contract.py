from pathlib import Path

import pytest

PUBLIC_EXPORT_MARKER = Path(__file__).resolve().parents[1] / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; the export has no git remote to verify",
)

# Successor marker set (roadmap #14, PR 1): the un-adapted goal-kickoff no longer emits the generic
# goal template (which led into a failing lane-start). It emits the STANDING AUTONOMY DIRECTIVE
# first (exit 0 preserved), then the state-aware guided-onboarding offer with AskUserQuestion
# mediation. Same exhaustive style, deliberately updated -- never loosened.
ONBOARDING_KICKOFF_MARKERS = (
    "STANDING AUTONOMY DIRECTIVE",
    "This repository is not Tautline-managed.",
    "Guided onboarding is available and nothing runs automatically.",
    "onboarding_offer: this repository has no Tautline adapter.",
    "Guided onboarding writes one from a short interview: tautline init --target",
    "onboarding_offer: agents put the adopt/skip decision to the human operator through "
    "AskUserQuestion",
    "do not run init unprompted and do not re-ask on refusal.",
    "Put the adopt-or-skip decision to the human operator through AskUserQuestion",
    "Run the offered command only after the operator chooses to onboard.",
    "proceed as a normal non-Tautline session and do not re-ask.",
    "Never run init unprompted.",
)

# The retired generic-goal-template dead-end markers: their ABSENCE is part of the contract.
RETIRED_GOAL_TEMPLATE_MARKERS = (
    "Work on the next active Minervit goal",
    "start Claude `/goal`",
    "backlog-provider-next",
    "adapter-declared exemption",
    "next_goal_name",
)


def test_goal_kickoff_prompt_offers_guided_onboarding_when_unmanaged(run_cli):
    result = run_cli("goal-kickoff-prompt", "--target", "/tmp/example-lane")

    assert result.returncode == 0, result.stderr
    missing = [marker for marker in ONBOARDING_KICKOFF_MARKERS if marker not in result.stdout]
    assert missing == []
    present_retired = [m for m in RETIRED_GOAL_TEMPLATE_MARKERS if m in result.stdout]
    assert present_retired == []


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
    # The requested target is threaded into the onboarding offer (resolved; /tmp -> /private/tmp on
    # macOS), root-targeted so the paste-able command initializes the right repository.
    resolved = str(Path("/tmp/example-lane").resolve())
    assert f"tautline init --target {resolved}" in result.stdout


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


INTERVIEW_REL = ".ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md"


def _make_interview_pending(root):
    p = root / INTERVIEW_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("interview", encoding="utf-8")


def _make_source_unrendered(root):
    p = root / ".tautline" / "adapter.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


def test_goal_kickoff_prompt_interview_pending_offer(run_cli, tmp_path):
    target = (tmp_path / "ip").resolve()
    target.mkdir()
    _make_interview_pending(target)

    result = run_cli("goal-kickoff-prompt", "--target", str(target))

    assert result.returncode == 0, result.stderr
    assert "STANDING AUTONOMY DIRECTIVE" in result.stdout
    assert f"tautline init --target {target} --continue" in result.stdout
    # never the stale unmanaged recovery line
    assert "tautline init --target .\n" not in result.stdout
    assert "AskUserQuestion" in result.stdout


def test_goal_kickoff_prompt_source_unrendered_offer(run_cli, tmp_path):
    target = (tmp_path / "su").resolve()
    target.mkdir()
    _make_source_unrendered(target)

    result = run_cli("goal-kickoff-prompt", "--target", str(target))

    assert result.returncode == 0, result.stderr
    assert f"tautline render-adapters --project {target}/.tautline/adapter.json" in result.stdout
    assert f"tautline lane-start --target {target}" in result.stdout
    assert "AskUserQuestion" in result.stdout


@pytest.mark.parametrize("verb", ["lane-start", "methodology-status", "autonomy-directive"])
def test_gate_verbs_fail_closed_interview_pending_with_correct_recovery(run_cli, tmp_path, verb):
    target = (tmp_path / f"ip-{verb}").resolve()
    target.mkdir()
    _make_interview_pending(target)

    result = run_cli(verb, "--target", str(target))

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "No project adapter found for this lane." in combined  # sentinel head preserved
    assert f"tautline init --target {target} --continue" in combined
    assert "tautline init --target .\n" not in combined  # never the stale unmanaged line


@pytest.mark.parametrize("verb", ["lane-start", "methodology-status", "autonomy-directive"])
def test_gate_verbs_fail_closed_source_unrendered_with_correct_recovery(run_cli, tmp_path, verb):
    target = (tmp_path / f"su-{verb}").resolve()
    target.mkdir()
    _make_source_unrendered(target)

    result = run_cli(verb, "--target", str(target))

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "No project adapter found for this lane." in combined
    assert f"tautline render-adapters --project {target}/.tautline/adapter.json" in combined
    assert f"tautline lane-start --target {target}" in combined
    assert "tautline init --target .\n" not in combined
