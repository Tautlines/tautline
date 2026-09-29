"""question-guard-hook: deny an AskUserQuestion carrying a continue-vs-stop direction menu.

Item 82 / RCA 20260701T115759Z. The Stop guard is text-shaped and an AskUserQuestion menu is
payload-shaped, so the exact forbidden menu bypassed every guard. AskUserQuestion also BLOCKS the
turn waiting for the human, so the Stop hook may never fire at all -- this PreToolUse seam is the
only one that sees the shape before the operator does.
"""

import json
from pathlib import Path


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "generated-adapter-example-saas.json"


def _lane(tmp_path, cli, *, goal_status="in_progress", response_guard=None, adapter=True):
    root = tmp_path / "lane"
    root.mkdir()
    if adapter:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        if response_guard is not None:
            data["responseGuard"] = response_guard
        (root / ".minervit-ai-delivery.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    if goal_status is not None:
        goal = root / ".ai-work" / "GOAL_RUN.json"
        goal.parent.mkdir(parents=True, exist_ok=True)
        goal.write_text(
            json.dumps({"schema": cli.GOAL_RUN_SCHEMA, "goalId": "goal-82", "status": goal_status})
            + "\n",
            encoding="utf-8",
        )
    return root


def _transcript(root, last_assistant):
    path = root / "transcript.jsonl"
    path.write_text(
        json.dumps(
            {"type": "user", "message": {"role": "user", "content": "keep going on the goal"}}
        )
        + "\n"
        + json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": last_assistant}}
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# The literal payload from the RCA. Kept verbatim: a paraphrase would let the detector drift off
# the shape it was built for and nothing would notice.
RCA_MENU = {
    "questions": [
        {
            "question": "How do you want to proceed?",
            "header": "Next step",
            "options": [
                {"label": "Resume next session"},
                {"label": "Keep grinding on 537.1 now"},
                {"label": "Merge #552 first"},
            ],
        }
    ]
}

TRUE_BLOCKER = {
    "questions": [
        {
            "question": "Which production credential set should I use?",
            "header": "Credentials",
            "options": [
                {"label": "staging-writer", "description": "the read-write staging key"},
                {"label": "prod-writer", "description": "the read-write production key"},
            ],
        }
    ]
}


def _payload(root, tool_input, *, transcript=None, tool_name="AskUserQuestion", last_user=None):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "cwd": str(root),
        "tool_input": tool_input,
    }
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    if last_user is not None:
        payload["last_user_message"] = last_user
    return json.dumps(payload)


def _events(root):
    path = root / ".ai-runs" / "guard-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _fired(root, check_id):
    return [
        event for event in _events(root) if event.get("check_id") == check_id and event.get("fired")
    ]


def test_no_adapter_root_passes(run_cli, tmp_path, cli):
    # Guided onboarding routes adopt-or-skip through AskUserQuestion by design (queue item 6).
    root = _lane(tmp_path, cli, adapter=False, goal_status=None)
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_malformed_stdin_fails_open(run_cli, tmp_path):
    res = run_cli("question-guard-hook", stdin="{not json")
    assert res.returncode == 0
    assert "decision" not in res.stdout


# --- Install surface ---------------------------------------------------------------------------
# A guard nobody installs is not a guard. Both delivery paths must carry it: `install-hooks` for
# settings-managed users and `lane-start` for the migration of already-installed lanes.


def test_an_unknown_hook_subcommand_fails_open(run_cli):
    """Codex R1 P2, and the durable half of the rollback note.

    An unknown subcommand is an ARGPARSE error -- exit 2, before any handler runs -- and a
    PreToolUse hook exiting 2 is a DENY. A machine repinned below the release that introduced a
    hook would have that hook installed, invoked, and rejecting every matching tool call. Hooks are
    the one family where the HOST chooses the argv, so failing open is the only safe answer.
    """
    res = run_cli("a-hook-from-a-future-release-hook")
    assert res.returncode == 0
    assert "hook_fail_open:" in res.stderr


def test_an_unknown_ordinary_verb_still_fails_loudly(run_cli):
    """The tolerance above is scoped to hooks; a mistyped ordinary verb must stay an error."""
    res = run_cli("render-adapterz")
    assert res.returncode != 0


# --- The false-positive corpus for this seam ----------------------------------------------------
# Found by PROBING the seam with realistic true-blocker questions rather than by reasoning about it.
# The first draft blocked two of these, because it reused a detector built for free-text turns --
# where "should I <verb>" is evasion -- on a question payload, where it is the sanctioned form of
# the one question the canonical rules tell an agent to ask. A guard that denies that shape is
# worse than no guard: it teaches lanes to route around it.

TRUE_BLOCKER_QUESTIONS = [
    "Which production credential set should I use?",
    "Production credentials are missing. Should I deploy with the staging credential?",
    "The API contract is ambiguous. Should I implement pagination or reject large results?",
    "The approved scope excludes migrations, but this fix needs one. Should I update the schema?",
    "Should I force push? Break-glass conditions are not documented for this repo.",
    "This changes the public API. Should I ship the breaking change or add a compatibility shim?",
    "The staging and production regions disagree. Which region owns the canonical record?",
    "Do you want me to delete the orphaned bucket, or keep it until the audit closes?",
]
