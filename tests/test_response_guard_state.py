import json
import os
import time
from pathlib import Path


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "generated-adapter-example-saas.json"


def _lane(tmp_path, cli, *, goal_status="in_progress", phrase_checks=None):
    root = tmp_path / "lane"
    root.mkdir()
    adapter = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if phrase_checks is not None:
        adapter["responseGuard"] = {"phraseChecks": phrase_checks}
    (root / ".minervit-ai-delivery.json").write_text(json.dumps(adapter, indent=2) + "\n", encoding="utf-8")
    goal_path = root / ".ai-work" / "GOAL_RUN.json"
    goal_path.parent.mkdir(parents=True)
    goal_path.write_text(
        json.dumps(
            {
                "schema": cli.GOAL_RUN_SCHEMA,
                "goalId": "goal-123",
                "status": goal_status,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _hook_payload(root, assistant):
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "cwd": str(root),
            "minervit_active_goal": True,
            "last_user_message": "continue the goal",
            "last_assistant_message": assistant,
        }
    )


def _events(root):
    path = root / ".ai-runs" / "guard-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _declare_blocker(run_cli, root):
    res = run_cli(
        "blocker-declare",
        "--target",
        str(root),
        "--kind",
        "approval-needed",
        "--reason",
        "waiting for customer approval",
    )
    assert res.returncode == 0, res.stderr


def test_stop_hook_blocks_active_goal_without_blocker(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)

    res = run_cli("response-guard-hook", stdin=_hook_payload(root, "I am stopping here."))

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "blocker-declare --kind <k> --reason <r>" in res.stdout
    assert "continue the next authorized action" in res.stdout


def test_response_guard_config_load_error_defaults_phrase_checks_blocking(cli, tmp_path):
    root = tmp_path / "lane"
    root.mkdir()
    (root / ".minervit-ai-delivery.json").write_text("{bad json", encoding="utf-8")

    assert cli.response_guard_config_for_root(root) == {"phraseChecks": "blocking"}


def test_stop_hook_allows_explicit_user_stop(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)
    payload = json.loads(_hook_payload(root, "Stopping because you explicitly said to stop the lane."))
    payload["last_user_message"] = "stop the lane"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert res.stdout == ""


def test_stop_hook_allows_user_requested_discussion(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)
    payload = json.loads(
        _hook_payload(root, "You want to think through the planning questions before deciding. I am listening.")
    )
    payload["last_user_message"] = "chat about this"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert res.stdout == ""


def test_stop_hook_blocks_self_attested_forward_motion_without_state_exit(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)

    res = run_cli(
        "response-guard-hook",
        stdin=_hook_payload(root, "Stage Z needed a spec, so I created docs/product/stage-z.md and I am running plan review now."),
    )

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "active-goal stop requires a legal exit" in res.stdout


def test_stop_hook_blocks_bare_startup_command_mention_without_exact_rotation_action(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)

    res = run_cli(
        "response-guard-hook",
        stdin=_hook_payload(
            root,
            "Context is at the hard threshold and I can't compact from inside this turn. "
            "I mentioned minervit-methodology lane-start, but I am not writing the restart steps.",
        ),
    )

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "active-goal stop requires a legal exit" in res.stdout


def test_stop_hook_allows_fresh_true_blocker(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)
    _declare_blocker(run_cli, root)

    res = run_cli("response-guard-hook", stdin=_hook_payload(root, "Blocked on customer approval."))

    assert res.returncode == 0
    assert res.stdout == ""


def test_stop_hook_allows_terminal_goal(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli, goal_status="complete")

    res = run_cli("response-guard-hook", stdin=_hook_payload(root, "Goal complete."))

    assert res.returncode == 0
    assert res.stdout == ""


def test_stop_hook_blocks_stale_blocker(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)
    _declare_blocker(run_cli, root)
    old = time.time() - cli.BLOCKER_FRESH_SECONDS - 60
    os.utime(root / ".ai-work" / "BLOCKER.json", (old, old))

    res = run_cli("response-guard-hook", stdin=_hook_payload(root, "Still blocked on approval."))

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "non-fresh blocker record" in res.stdout
    assert "older-than-30-minutes" in res.stdout


def test_stop_hook_blocks_context_rotation_artifacts_without_startup_action(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)

    res = run_cli(
        "response-guard-hook",
        stdin=_hook_payload(
            root,
            "I wrote .ai-continuity/NEXT_SESSION.md, but context is too full. "
            "I can't compact from inside this turn. Start a fresh session if you want me to continue.",
        ),
    )

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "context-rotation stop" in res.stdout


def test_stop_hook_allows_documented_context_rotation_exit(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli)

    res = run_cli(
        "response-guard-hook",
        stdin=_hook_payload(
            root,
            "Context is at the hard threshold and I can't compact from inside this turn. I refreshed "
            "continuity and the exact fresh-session startup action is: run "
            "minervit-methodology lane-start --target . and "
            "minervit-methodology methodology-status --target . --fail-on-drift, then resume.",
        ),
    )

    assert res.returncode == 0
    assert res.stdout == ""


def test_stop_hook_phrase_checks_are_advisory_by_default(run_cli, cli, tmp_path):
    """Phrase/state taxonomy: this must prove more than one benign phrase check passing through advisory
    mode -- it trips at least three of the 14 heuristics that F1 found mislabeled
    mechanism="state" (and were hard-blocking regardless of adapter config) and asserts the
    stop is still ALLOWED with the default adapter config."""
    root = _lane(tmp_path, cli)
    _declare_blocker(run_cli, root)
    assistant = (
        "# RCA\n"
        "Root cause: I stopped without publishing the RCA artifacts.\n\n"
        "The next milestone needs drafting and needs a plan before I continue.\n\n"
        "The PR merged. No open PRs remain in this session summary.\n\n"
        "Delivery summary: this response mentions Claude /goal but attaches no supporting artifact.\n\n"
        "The Anthropic API returned an API error and I am unable to continue right now.\n\n"
        "I don't do videos for the recap video in this iteration review.\n\n"
        "Plain English: hit a rate limit.\n"
        "Progress: paused after a 429 error.\n"
        "Next: will retry shortly.\n"
        "State: waiting.\n"
    )
    payload = json.loads(_hook_payload(root, assistant))
    payload["last_user_message"] = "what's next"

    res = run_cli("response-guard-hook", stdin=json.dumps(payload))

    assert res.returncode == 0
    assert res.stdout == ""
    events = {e["check_id"]: e for e in _events(root) if e["fired"]}
    retagged_fired = {
        "stop.chat_only_rca",
        "stop.status_report_as_stop",
        "stop.terminal_continuity_omission",
        "stop.iteration_review_media_deferral",
        "stop.boundary_summary",
        "stop.transient_external_dependency_yield",
        "stop.provider_outage_without_recovery",
    }
    assert retagged_fired <= events.keys(), sorted(retagged_fired - events.keys())
    for check_id in retagged_fired:
        assert events[check_id]["mechanism"] == "phrase", check_id


def test_stop_hook_legacy_phrase_blocking_is_adapter_opt_in(run_cli, cli, tmp_path):
    root = _lane(tmp_path, cli, phrase_checks="blocking")
    _declare_blocker(run_cli, root)

    res = run_cli(
        "response-guard-hook",
        stdin=_hook_payload(root, "Blocked on approval. Preflight is running. Yielding until then."),
    )

    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "passive monitor stop" in res.stdout
