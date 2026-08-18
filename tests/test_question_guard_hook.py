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


def test_rca_menu_is_logged_but_not_denied_by_default(run_cli, tmp_path, cli):
    """Item 82 decomposed: the classifier ships ADVISORY, so the shape is measured, not denied.

    Three consecutive review rounds each found a fresh false positive in this classifier, on a seam
    that denies by default -- most seriously a genuine operator-owned approval question, which can
    deadlock the very work whose only legal next step is requesting approval. Item 82-B owns the
    promotion, and this guard event is the evidence it will build on.
    """
    root = _lane(tmp_path, cli)
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    assert _fired(root, "pretool.question_direction_menu")


def test_the_menu_block_is_one_adapter_key_away(run_cli, tmp_path, cli):
    """Advisory by DEFAULT, not disabled: a lane that wants the block opts in, and gets it whole."""
    root = _lane(tmp_path, cli, response_guard={"questionGuard": "blocking"})
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "next buildable step" in res.stdout
    assert "true-blocker question" in res.stdout


def test_no_adapter_root_passes(run_cli, tmp_path, cli):
    # Guided onboarding routes adopt-or-skip through AskUserQuestion by design (queue item 6).
    root = _lane(tmp_path, cli, adapter=False, goal_status=None)
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_no_active_goal_passes(run_cli, tmp_path, cli):
    # A direction question BETWEEN goals is not this defect.
    root = _lane(tmp_path, cli, goal_status="complete")
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_true_blocker_question_passes(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    res = run_cli("question-guard-hook", stdin=_payload(root, TRUE_BLOCKER))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_other_tools_pass(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU, tool_name="Write"))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_self_contradiction_is_advisory_not_blocking(run_cli, tmp_path, cli):
    """The predicate fires and is logged; it never supplies the block.

    Its markers are loose by construction -- "i recommend" matches an ordinary technical
    recommendation -- which is exactly why it must not reach a hard-block seam.
    """
    root = _lane(tmp_path, cli)
    transcript = _transcript(
        root, "The safe default is to proceed under the trivial-fix exemption."
    )
    res = run_cli("question-guard-hook", stdin=_payload(root, TRUE_BLOCKER, transcript=transcript))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    assert _fired(root, "pretool.question_self_contradiction")


def test_recommendation_plus_true_blocker_not_blocked(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    transcript = _transcript(root, "I recommend Redis for the cache.")
    res = run_cli("question-guard-hook", stdin=_payload(root, TRUE_BLOCKER, transcript=transcript))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_full_rca_shape_is_blocked_and_carries_the_named_default_context(run_cli, tmp_path, cli):
    """RCA 20260616T132017Z: a named safe default AND a three-option menu.

    The menu supplies the block; the contradiction predicate only enriches the reason.
    """
    base = tmp_path / "blocking"
    base.mkdir()
    root_blocking = _lane(base, cli, response_guard={"questionGuard": "blocking"})
    transcript = _transcript(
        root_blocking, "The trivial-fix exemption is the defensible safe default here."
    )
    res = run_cli(
        "question-guard-hook", stdin=_payload(root_blocking, RCA_MENU, transcript=transcript)
    )
    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    assert "take the named default" in res.stdout


def test_quoted_guard_output_in_the_prior_turn_does_not_poison_a_clean_question(
    run_cli, tmp_path, cli
):
    """Blocking inputs are the question payload ONLY.

    Turns in this repo's own lanes routinely quote guard output verbatim. If `last_assistant` were a
    blocking input, a lane reporting on the guard would be denied its next legitimate question.
    """
    root = _lane(tmp_path, cli)
    transcript = _transcript(
        root,
        "The guard refused with: 'How do you want to proceed? Resume next session / Keep going "
        "now / "
        "Merge #552 first' -- that is the forbidden shape and I did not present it.",
    )
    res = run_cli("question-guard-hook", stdin=_payload(root, TRUE_BLOCKER, transcript=transcript))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_standing_authorization_reask_is_advisory(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    payload = {
        "questions": [
            {
                "question": "Authorize a scoped break-glass push for #276?",
                "header": "Authorization",
                "options": [{"label": "yes, authorize it"}, {"label": "no, wait for the queue"}],
            }
        ]
    }
    res = run_cli("question-guard-hook", stdin=_payload(root, payload))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    assert _fired(root, "pretool.question_standing_authorization_reask")


def test_first_time_break_glass_blocker_question_is_not_blocked(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    payload = {
        "questions": [
            {
                "question": (
                    "Break-glass conditions are not documented for this repo. Should I force "
                    "push, or "
                    "is there a recorded condition I have not found?"
                ),
                "header": "Break-glass",
                "options": [
                    {"label": "force push is authorized"},
                    {"label": "there is a recorded condition"},
                ],
            }
        ]
    }
    res = run_cli("question-guard-hook", stdin=_payload(root, payload))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_explicit_user_stop_passes(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli)
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU, last_user="stop"))
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_question_guard_advisory_is_explicit_as_well_as_default(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli, response_guard={"questionGuard": "advisory"})
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    # Demoted, never silenced: the event still lands so the shape stays measurable.
    assert _fired(root, "pretool.question_direction_menu")


def test_question_guard_off_logs_nothing_and_passes(run_cli, tmp_path, cli):
    root = _lane(tmp_path, cli, response_guard={"questionGuard": "off"})
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    assert not _fired(root, "pretool.question_direction_menu")


def test_malformed_stdin_fails_open(run_cli, tmp_path):
    res = run_cli("question-guard-hook", stdin="{not json")
    assert res.returncode == 0
    assert "decision" not in res.stdout


def test_the_block_is_emitted_exactly_once(run_cli, tmp_path, cli):
    # Inherited hook-contract finding (queue item 28, do not re-derive): a hook that reaches the
    # decision emitter twice prints two decision objects and the host reads the wrong one.
    root = _lane(tmp_path, cli, response_guard={"questionGuard": "blocking"})
    transcript = _transcript(root, "The safe default is to proceed, and I recommend it.")
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU, transcript=transcript))
    assert res.stdout.count('"decision"') == 1


# --- Install surface ---------------------------------------------------------------------------
# A guard nobody installs is not a guard. Both delivery paths must carry it: `install-hooks` for
# settings-managed users and `lane-start` for the migration of already-installed lanes.


def test_install_hooks_installs_the_askuserquestion_matcher(run_cli, tmp_path, cli):
    settings = tmp_path / "settings.json"
    res = run_cli("install-hooks", "--settings", str(settings))
    assert res.returncode == 0, res.stderr
    assert "claude_question_guard_hook: installed" in res.stdout
    data = json.loads(settings.read_text(encoding="utf-8"))
    entries = [
        entry
        for entry in data["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
    ]
    assert len(entries) == 1
    assert entries[0]["hooks"][0]["command"] == "tautline question-guard-hook"


def test_install_hooks_is_idempotent(run_cli, tmp_path, cli):
    settings = tmp_path / "settings.json"
    run_cli("install-hooks", "--settings", str(settings))
    res = run_cli("install-hooks", "--settings", str(settings))
    assert "claude_question_guard_hook: already present" in res.stdout
    data = json.loads(settings.read_text(encoding="utf-8"))
    matching = [
        entry
        for entry in data["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
    ]
    assert len(matching) == 1


def test_settings_predicate_round_trips(cli, tmp_path):
    settings = tmp_path / "settings.json"
    assert cli.settings_question_guard_hook_installed({}) is False
    cli.write_claude_question_guard_hook(settings, "tautline question-guard-hook")
    assert (
        cli.settings_question_guard_hook_installed(json.loads(settings.read_text(encoding="utf-8")))
        is True
    )


def test_install_hooks_is_idempotent_for_a_custom_command(run_cli, tmp_path, cli):
    """Codex R1 P2. A substring-only predicate never recognizes a custom command's own install.

    Every subsequent run appended another AskUserQuestion entry and the host ran the guard N times
    on one tool call. The matcher is the durable identity of the entry; the command is what the
    caller asked for, and both are checked.
    """
    settings = tmp_path / "settings.json"
    custom = "/opt/lane/bin/my-question-guard"
    for _ in range(3):
        run_cli("install-hooks", "--settings", str(settings), "--question-guard-command", custom)
    data = json.loads(settings.read_text(encoding="utf-8"))
    entries = [
        entry
        for entry in data["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
    ]
    assert len(entries) == 1
    assert entries[0]["hooks"][0]["command"] == custom


def test_the_json_aggregate_gate_cannot_report_success_while_failing(run_cli, tmp_path):
    """Codex R1 P1, pinned by breaking the corpus rather than by reading the code.

    The --json branch returned 0 before any check ran, so a drifted corpus produced valid JSON and
    exit 0 -- a machine-readable consumer would have read a FAILED aggregate gate as passing. That
    is the harness reproducing, in itself, the exact defect class it exists to detect.
    """
    import shutil
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    scratch = tmp_path / "repo"
    (scratch / "methodology" / "stop-guard").mkdir(parents=True)
    (scratch / "adapters" / "projects").mkdir(parents=True)
    shutil.copy(
        repo / "adapters" / "projects" / "example-saas.json",
        scratch / "adapters" / "projects" / "example-saas.json",
    )
    corpus = (repo / "methodology" / "stop-guard" / "corpus.jsonl").read_text(encoding="utf-8")
    (scratch / "methodology" / "stop-guard" / "corpus.jsonl").write_text(
        "\n".join(corpus.splitlines()[:-1]) + "\n", encoding="utf-8"
    )
    shutil.copy(
        repo / "methodology" / "stop-guard" / "aggregate-baseline.json",
        scratch / "methodology" / "stop-guard" / "aggregate-baseline.json",
    )
    res = run_cli("stop-guard-aggregate", "--repo-root", str(scratch), "--json")
    assert res.returncode == 1, "the JSON mode must carry the same exit status as the text mode"
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["failures"], payload


def test_a_broken_adapter_does_not_stand_the_guard_down(run_cli, tmp_path, cli):
    """Codex R1 P2. A broken adapter is a broken LANE, not an absent goal.

    `load_project` raises SystemExit on an invalid adapter, and SystemExit derives from
    BaseException, so it escaped the handler ordering entirely: the guard exited without a decision
    in precisely the degraded state the config's fail-safe blocking default exists to protect.
    """
    root = tmp_path / "lane"
    root.mkdir()
    (root / ".minervit-ai-delivery.json").write_text("{not valid json", encoding="utf-8")
    goal = root / ".ai-work" / "GOAL_RUN.json"
    goal.parent.mkdir(parents=True)
    goal.write_text(
        json.dumps({"schema": cli.GOAL_RUN_SCHEMA, "goalId": "g", "status": "in_progress"}),
        encoding="utf-8",
    )
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert res.returncode == 0
    # The guard must still EVALUATE -- the failure mode this pins is the hook dying on SystemExit
    # and standing down entirely. It does not deny, because the classifier ships advisory: failing a
    # degraded lane into a classifier three review rounds found false positives in would be the
    # opposite of a fail-safe.
    assert _fired(root, "pretool.question_direction_menu"), res.stdout + res.stderr


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


def test_no_real_true_blocker_question_is_denied(run_cli, tmp_path, cli):
    """The false-positive floor for a BLOCKING seam. Every one of these must pass."""
    for index, question in enumerate(TRUE_BLOCKER_QUESTIONS):
        base = tmp_path / f"tb{index}"
        base.mkdir()
        root = _lane(base, cli)
        payload = {
            "questions": [
                {
                    "question": question,
                    "header": "Blocker",
                    "options": [{"label": "option A"}, {"label": "option B"}],
                }
            ]
        }
        res = run_cli("question-guard-hook", stdin=_payload(root, payload))
        assert res.returncode == 0, question
        assert "decision" not in res.stdout, f"DENIED a true-blocker question: {question}"


def test_the_menu_shape_is_still_denied(run_cli, tmp_path, cli):
    """Non-vacuity floor for the test above: narrowing the input must not disarm the guard."""
    root = _lane(tmp_path, cli, response_guard={"questionGuard": "blocking"})
    res = run_cli("question-guard-hook", stdin=_payload(root, RCA_MENU))
    assert '"decision": "block"' in res.stdout


def test_prose_opt_in_still_logs_without_deciding(run_cli, tmp_path, cli):
    """It is demoted, not deleted: the shape stays measurable so a promotion can be evidence-led."""
    root = _lane(tmp_path, cli)
    payload = {
        "questions": [
            {
                "question": (
                    "Production credentials are missing. Should I deploy with the staging "
                    "credential?"
                ),
                "header": "Credentials",
                "options": [{"label": "staging"}, {"label": "wait"}],
            }
        ]
    }
    res = run_cli("question-guard-hook", stdin=_payload(root, payload))
    assert res.returncode == 0
    assert "decision" not in res.stdout
    assert _fired(root, "pretool.question_prose_opt_in")


def test_changing_the_command_replaces_the_registration_rather_than_adding_one(
    run_cli, tmp_path, cli
):
    """Codex R3 P2. lane-start installs the default; an operator asks for a custom one.

    The command-aware check correctly said "not installed", but appending left BOTH registered, so
    Claude ran two guards on every question and the command that was explicitly replaced kept
    logging and deciding.
    """
    settings = tmp_path / "settings.json"
    run_cli("install-hooks", "--settings", str(settings))
    run_cli(
        "install-hooks",
        "--settings",
        str(settings),
        "--question-guard-command",
        "/opt/lane/bin/my-question-guard",
    )
    entries = [
        entry
        for entry in json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
    ]
    assert len(entries) == 1
    assert entries[0]["hooks"][0]["command"] == "/opt/lane/bin/my-question-guard"


def test_moving_between_custom_commands_replaces_rather_than_accumulates(cli, tmp_path):
    """Codex R3 P2. "Ours" is not recognizable by verb name -- a custom command need not carry it.

    A lane that moved /opt/custom-a -> /opt/custom-b kept both registered, and so did one that went
    from a custom command back to the default. Claude then ran every one of them on each question.
    """
    settings = tmp_path / "settings.json"
    sequence = ("/opt/custom-a", "/opt/custom-b", "tautline question-guard-hook", "/opt/custom-c")
    for command in sequence:
        cli.write_claude_question_guard_hook(settings, command)
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in data["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
        for hook in entry["hooks"]
    ]
    assert commands == ["/opt/custom-c"]


def test_replacing_the_guard_preserves_a_sibling_hook_in_the_same_entry(cli, tmp_path):
    """Codex R3 P2. Dropping the whole matcher entry silently uninstalled someone else's hook."""
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": cli.QUESTION_GUARD_HOOK_MATCHER,
                            "hooks": [
                                {"type": "command", "command": "tautline question-guard-hook"},
                                {"type": "command", "command": "other-tool guard"},
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.write_claude_question_guard_hook(settings, "/opt/new-guard")
    commands = [
        hook["command"]
        for entry in json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        for hook in entry["hooks"]
    ]
    assert "other-tool guard" in commands
    assert "/opt/new-guard" in commands
    assert "tautline question-guard-hook" not in commands


def test_the_schema_default_matches_the_runtime_default(cli):
    """Codex R3 P2. A published contract that disagrees with shipped behaviour is a defect.

    The schema said `blocking` while the runtime resolved `advisory`, so schema-driven tooling and
    every adopter reading the contract got the opposite of what ships.
    """
    schema = json.loads(
        (cli.REPO_ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8")
    )
    declared = schema["properties"]["responseGuard"]["properties"]["questionGuard"]["default"]
    assert declared == cli.response_guard_config_for_root(None)["questionGuard"] == "advisory"


def test_a_foreign_askuserquestion_hook_is_left_alone(cli, tmp_path):
    """Replacement is scoped to Tautline's own entries; another tool's hook is not ours."""
    import json as _json

    settings = tmp_path / "settings.json"
    settings.write_text(
        _json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": cli.QUESTION_GUARD_HOOK_MATCHER,
                            "hooks": [{"type": "command", "command": "some-other-tool guard"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.write_claude_question_guard_hook(settings, "tautline question-guard-hook")
    entries = [
        entry
        for entry in _json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        if entry.get("matcher") == cli.QUESTION_GUARD_HOOK_MATCHER
    ]
    commands = {entry["hooks"][0]["command"] for entry in entries}
    assert commands == {"some-other-tool guard", "tautline question-guard-hook"}
