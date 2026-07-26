"""T3 (0.8.9 startup remediation): the remediation marker lifecycle + central dispatch guard.

See .superpowers/sdd/task-089-T3-brief.md ("Remediation marker (the enforcement teeth)" -- the
normative design section every clause here traces back to) and task-089-T3-report.md for the
TDD transcript. Builds on T1 (127c515: failure classification / three-way exit contract) and T2
(770ec52: lane-coordination staleness re-scope).
"""

import inspect
import json
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"
REPO_LOCAL_ADAPTER_REL = ".tautline/adapter.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_adapter(target: Path, mutate=None) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for startup-remediation coverage (T3).",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["backlogProvider"] = {"enabled": False}
    data["stakeholderQuestions"] = {"enabled": False}
    data["milestoneUpdate"] = {"enabled": False}
    data["productChat"] = {"enabled": False}
    data["deploymentNotification"] = {"enabled": False}
    behavior_specs = dict(data.get("behaviorSpecs") or {})
    behavior_specs["required"] = False
    behavior_specs["acceptanceHarnesses"] = []
    data["behaviorSpecs"] = behavior_specs
    document_context = dict(data.get("documentContext") or {})
    document_context["ignoredDocPaths"] = [
        *(document_context.get("ignoredDocPaths") or []),
        "docs/product/backlog",
    ]
    data["documentContext"] = document_context
    if mutate:
        mutate(data)
    adapter = target / REPO_LOCAL_ADAPTER_REL
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("primary\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("secondary\n", encoding="utf-8")
    (target / SOURCE_REL).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")


def _lane(tmp_path: Path, run_cli, mutate=None) -> Path:
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target, mutate)
    started = run_cli("lane-start", "--project", str(adapter), "--target", str(target), "--skip-update")
    assert started.returncode == 0, started.stdout + started.stderr
    bootstrapped = run_cli("context-bootstrap", "--project", str(adapter), "--target", str(target), "--write")
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    return target


def _status(run_cli, target: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return run_cli("methodology-status", "--target", str(target), "--no-remote", *flags)


def _break_hooks(run_cli, tmp_path: Path) -> None:
    """Wipe the installed Claude hook settings -- an unconditionally-populated DEBT gate
    (hook_failures) that only ever blocks under --fail-on-drift, never --strict alone. The
    simplest reliable single-gate debt trigger (reused from T1)."""
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")


def _write_goal_run(target: Path) -> None:
    """A goal ledger with exactly one integrity issue (goal_failures: DEBT, blocks under bare
    --fail-on-drift only) -- a milestone marked blocked with no recorded blocker reason."""
    goal_run = target / ".ai-work" / "GOAL_RUN.json"
    goal_run.write_text(
        json.dumps(
            {
                "schema": "minervit-goal-run/v1",
                "status": "active",
                "milestones": [{"index": 1, "title": "M1", "status": "blocked"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _marker_path(target: Path) -> Path:
    return target / ".ai-work" / "STARTUP_REMEDIATION.json"


def _read_marker(target: Path) -> dict:
    return json.loads(_marker_path(target).read_text(encoding="utf-8"))


# --- registry partition: the completeness authority -------------------------------------------


def test_startup_remediation_registry_partition(cli):
    """Every registered subcommand is classified into EXACTLY one of ALLOWED/BLOCKED -- walks the
    real argparse registry (registered_subcommand_names(), the same source the public-contract
    manifest uses), not a hand-typed copy."""
    names = set(cli.registered_subcommand_names())
    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    blocked = set(cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS)
    missing = names - (allowed | blocked)
    extra = (allowed | blocked) - names
    overlap = allowed & blocked
    assert not missing, f"unclassified registered commands: {sorted(missing)}"
    assert not extra, f"classified names that are not registered commands: {sorted(extra)}"
    assert not overlap, f"commands in both tuples: {sorted(overlap)}"


def test_startup_remediation_classification_constants_are_tuples(cli):
    assert isinstance(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS, tuple)
    assert isinstance(cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS, tuple)
    for value in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS.values():
        assert isinstance(value, tuple)
    assert isinstance(cli.STARTUP_REMEDIATION_WRITE_FLAG_GATED_COMMANDS, tuple)


def test_hook_invoked_commands_are_all_allowed(cli):
    """Mandatory rule 1: every command the generated git hooks or Claude hooks invoke must be
    ALLOWED, or a remediation session could not even commit/push its own fixes.

    The expected set is DERIVED from the real hook-template sources (plan-mandated), not
    hardcoded, so a future template change that starts invoking a currently-BLOCKED command
    fails this gate until the command is reclassified:
    - Git hook template: `git_branch_liveness_hook_content` builds the pre-commit/pre-push
      script; every CLI invocation goes through its `run_minervit_command '<label>' <subcommand>
      ...` wrapper (including the pre-push-only guard-check block), so the subcommand tokens are
      extracted from that call pattern.
    - Claude hooks: the generated settings entries are written from install-hooks' argparse
      `default="tautline <subcommand>"` wiring (--command, --branch-liveness-command, ...
      --plan-review-pending-command). The A1 package-split carve moved that wiring out of main()
      into a `_register_*` registrar segment, so the scan reads the whole CLI module source
      (inspect.getsource(cli)) rather than main() alone -- migration-proof, like the carve goldens.
    """
    registered = set(cli.registered_subcommand_names())

    git_template_source = inspect.getsource(cli.git_branch_liveness_hook_content)
    git_invoked = set(re.findall(r"run_minervit_command '[^']*' ([a-z][a-z0-9-]*)", git_template_source))

    cli_source = inspect.getsource(cli)
    claude_invoked = set(re.findall(r"default=\"tautline ([a-z][a-z0-9-]*)\"", cli_source))

    derived = git_invoked | claude_invoked
    # Sanity floor: a broken scanner must not silently pass an empty/gutted set.
    assert derived, "hook-template scanner extracted no invoked commands -- scanner is broken"
    assert {"guard-check", "work-profile-check"} <= derived, derived
    assert len(claude_invoked) >= 7, claude_invoked  # all seven Claude *-hook defaults today
    not_registered = derived - registered
    assert not not_registered, f"scanner extracted tokens that are not registered subcommands: {sorted(not_registered)}"

    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    assert derived <= allowed, f"hook-invoked commands not ALLOWED: {sorted(derived - allowed)}"


def test_recovery_action_coverage_global_or_recovery_map(cli):
    """Mandatory rule 2: every `tautline <command>` or bare registered-subcommand token named in
    a debt gate's printed remediation text is reachable -- globally ALLOWED, or listed in that
    gate's STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS entry. Scans the ACTUAL source of the
    functions that build/print each debt gate's issue text (inspect.getsource, not a hand-copied
    corpus), scoped to methodology_status's own debt-gate-relevant output so an unrelated
    "tautline goal-start" mention elsewhere in the file (e.g. an unrelated kickoff prompt) can't
    force over-broad global promotion of a project-work mutator.
    """
    source_funcs = {
        "hook": (
            cli.claude_hook_state,
            cli.claude_branch_liveness_hook_state,
            cli.claude_response_guard_hook_state,
            cli.claude_tool_rejection_hook_state,
            cli.claude_background_command_hook_state,
            cli.claude_latest_code_hook_state,
            cli.claude_context_rotation_heartbeat_hook_state,
            cli.claude_plan_review_pending_hook_state,
            cli.claude_session_start_directive_hook_state,
            cli.git_branch_liveness_hook_state,
        ),
        "latest_code": (cli.latest_code_instruction_line, cli.latest_code_baseline_state, cli.print_latest_code_baseline),
        "autocompact": (cli.claude_autocompact_failure_messages,),
        "graphify": (cli.print_graphify_status,),
        "product_chat": (cli.print_product_chat_status,),
        "goal_tracker": (cli.provider_board_currency_issues, cli.goal_tracker_drift_issues, cli.board_item_active_work_drift),
        "goal": (cli.goal_run_integrity_issues, cli.print_next_goal_candidate, cli.goal_candidate_claude_prompt),
        "milestone": (cli.milestone_run_integrity_issues,),
        "lane_coordination": (cli.print_lane_coordination_status,),
        "iteration_review": (cli.print_iteration_review_status,),
        "milestone_update": (cli.print_milestone_update_status,),
        "deployment_notification": (cli.print_deployment_notification_status,),
        "ui_evidence": (cli.print_ui_evidence_status,),
        "stakeholder_question": (cli.stakeholder_questions_auth_issues,),
        "behavior_spec": (cli.print_behavior_spec_status,),
        "ci_test_gate": (cli.print_ci_test_gate_status,),
        "runtime_secret": (cli.print_runtime_secret_status,),
        "critical_journey": (cli.print_critical_journey_status,),
        "migration_safety": (cli.print_migration_safety_status,),
        "health_contract": (cli.print_health_contract_status,),
        "side_effect_proof": (cli.print_side_effect_proof_status,),
        "remediation": (cli.print_remediation_status,),
        "planning": (cli.planning_path_issues,),
        "context": (cli.print_document_context_status,),
    }
    debt_gate_display_names = {
        cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES[name] for name in cli.METHODOLOGY_STATUS_DEBT_GATES
    }
    assert set(source_funcs) == debt_gate_display_names, set(source_funcs) ^ debt_gate_display_names

    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    registered = set(cli.registered_subcommand_names())
    token_re = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
    failures = []
    for gate, funcs in source_funcs.items():
        recovery = set(cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS.get(gate, ()))
        text = "\n".join(inspect.getsource(func) for func in funcs)
        for token in set(token_re.findall(text)):
            if token not in registered:
                continue  # not a command reference at all (e.g. an adapter key or flag name)
            if token in allowed or token in recovery:
                continue
            failures.append(f"gate={gate} command={token} (not globally ALLOWED and not in its recovery map)")
    assert not failures, "\n".join(failures)


def test_canonical_recovery_map_keys_are_canonical_gate_display_names(cli):
    """The recovery map's keys must be exactly the canonical gate identifiers the marker records
    and the summary/event surfaces use -- never a raw `..._failures` list-variable name."""
    display_names = set(cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES.values())
    assert set(cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS) <= display_names
    assert "goal" in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS
    assert "goal_tracker" in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS
    assert "milestone" in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS


def test_goal_advance_and_milestone_advance_have_no_recovery_map_entry(cli):
    """Graduation commands are deliberately never reachable via recovery -- fixing debt clears
    the marker; goal-advance/milestone-advance become reachable again once the guard has nothing
    to guard, not while the marker is present."""
    recovered = {cmd for commands in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS.values() for cmd in commands}
    assert "goal-advance" not in recovered
    assert "milestone-advance" not in recovered


# --- write-flag-gated commands (V14R1-P2-2) -----------------------------------------------------


def test_write_flag_gated_commands_are_allowed_and_gated(cli):
    gated = set(cli.STARTUP_REMEDIATION_WRITE_FLAG_GATED_COMMANDS)
    assert gated == {"canonical-policy", "dump-policy-phrases", "dump-instrumentation-schema"}
    assert gated <= set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)


# --- full lifecycle: fail -> marker -> refusal -> fix -> clean -> gone -> works -----------------


def test_full_remediation_lifecycle(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)

    entered = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert entered.returncode == 2, entered.stdout + entered.stderr
    marker_path = _marker_path(target)
    assert marker_path.exists()
    marker = _read_marker(target)
    assert marker["schema"] == "tautline-startup-remediation/v1"
    assert marker["gates"] == ["hook"]
    assert marker["status_exit"] == 2
    assert marker["issues"]

    blocked = run_cli("goal-start", "--target", str(target), "--goal", "docs/does-not-exist.md")
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    assert "startup remediation active" in blocked.stdout + blocked.stderr
    assert str(marker_path) in blocked.stdout + blocked.stderr

    # Fix the hook debt (reinstall hooks) and confirm the marker clears and the command works.
    fixed = run_cli("install-hooks", "--target", str(target))
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    clean = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert not marker_path.exists()

    unblocked = run_cli("methodology-status", "--target", str(target), "--no-remote")
    assert unblocked.returncode == 0, unblocked.stdout + unblocked.stderr


# --- representative refusals --------------------------------------------------------------------


def _enter_hook_debt_remediation(tmp_path, run_cli) -> Path:
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    entered = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert entered.returncode == 2, entered.stdout + entered.stderr
    return target


def test_representative_refusals_while_marker_present(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    for cmd, extra in (
        ("goal-start", ["--goal", "docs/x.md"]),
        ("goal-next", []),
        ("goal-advance", ["--event", "milestone-complete"]),
        ("milestone-start", ["--plan", "docs/x.md"]),
        ("milestone-next", []),
        ("milestone-advance", ["--event", "startup"]),
    ):
        result = run_cli(cmd, "--target", str(target), *extra)
        assert result.returncode == 1, f"{cmd}: {result.stdout}{result.stderr}"
        assert "startup remediation active" in result.stdout + result.stderr, cmd


# --- allowed-with-marker -------------------------------------------------------------------------


def test_allowed_commands_run_with_marker_present(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    status = _status(run_cli, target)
    assert status.returncode in (0, 2), status.stdout + status.stderr
    assert "startup remediation active" not in status.stdout + status.stderr

    lane_start = run_cli(
        "lane-start",
        "--project", str(target / REPO_LOCAL_ADAPTER_REL),
        "--target", str(target),
        "--skip-update",
    )
    assert "startup remediation active" not in lane_start.stdout + lane_start.stderr

    blocker = run_cli(
        "blocker-declare",
        "--target", str(target),
        "--kind", "operator",
        "--reason", "remediation coverage test",
    )
    assert "startup remediation active" not in blocker.stdout + blocker.stderr


def test_hook_invoked_commands_run_with_marker_present(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    for cmd, extra in (
        ("work-profile-check", ["--event", "status"]),
        ("branch-liveness-check", []),
        ("graphify-status", []),
        ("backlog-provider-active-check", []),
    ):
        result = run_cli(cmd, "--target", str(target), *extra)
        assert "startup remediation active" not in result.stdout + result.stderr, f"{cmd}: {result.stdout}{result.stderr}"


def test_review_evidence_pipeline_runs_with_marker_present(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    result = run_cli("review-evidence-check", "--target", str(target))
    assert "startup remediation active" not in result.stdout + result.stderr


# --- recovery map ---------------------------------------------------------------------------------


def test_goal_debt_marker_permits_goal_start_but_blocks_milestone_advance(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _write_goal_run(target)
    entered = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert entered.returncode == 2, entered.stdout + entered.stderr
    marker = _read_marker(target)
    assert marker["gates"] == ["goal"]

    goal_start = run_cli("goal-start", "--target", str(target), "--goal", "docs/does-not-exist.md")
    assert "startup remediation active" not in goal_start.stdout + goal_start.stderr

    milestone_advance = run_cli("milestone-advance", "--target", str(target), "--event", "startup")
    assert milestone_advance.returncode == 1
    assert "startup remediation active" in milestone_advance.stdout + milestone_advance.stderr


def test_context_debt_marker_permits_context_bootstrap_but_blocks_goal_advance(tmp_path, run_cli):
    """Codex T7 R2 P2: `context-bootstrap --write` is the sanctioned repair command for the
    `context` debt gate (missing index/archive dirs/classification/headers); a context-gate
    marker must permit it via the recovery map while other project-work mutators stay blocked,
    and a marker WITHOUT the context gate must keep it blocked."""
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    marker = _read_marker(target)
    marker["gates"] = ["context"]
    _marker_path(target).write_text(json.dumps(marker), encoding="utf-8")

    repaired = run_cli(
        "context-bootstrap",
        "--project", str(target / REPO_LOCAL_ADAPTER_REL),
        "--target", str(target),
        "--write",
    )
    assert "startup remediation active" not in repaired.stdout + repaired.stderr, (
        repaired.stdout + repaired.stderr
    )

    goal_advance = run_cli("goal-advance", "--target", str(target), "--event", "startup")
    assert goal_advance.returncode == 1
    assert "startup remediation active" in goal_advance.stdout + goal_advance.stderr

    marker["gates"] = ["hook"]
    _marker_path(target).write_text(json.dumps(marker), encoding="utf-8")
    blocked = run_cli(
        "context-bootstrap",
        "--project", str(target / REPO_LOCAL_ADAPTER_REL),
        "--target", str(target),
        "--write",
    )
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    assert "startup remediation active" in blocked.stdout + blocked.stderr


def test_hook_only_marker_blocks_all_goal_and_milestone_commands(tmp_path, run_cli):
    """A debt gate with NO recovery-map entry (hook_failures, standing in for the design's named
    "coordination-only marker" example -- both are single non-goal/milestone debt gates with no
    recovery-map coverage, so the guard property under test is identical) blocks every goal and
    milestone command, not just the ones without an explicit test above."""
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    for cmd, extra in (
        ("goal-start", ["--goal", "docs/x.md"]),
        ("goal-condition", []),
        ("milestone-start", ["--plan", "docs/x.md"]),
        ("milestone-next", []),
    ):
        result = run_cli(cmd, "--target", str(target), *extra)
        assert result.returncode == 1, f"{cmd}: {result.stdout}{result.stderr}"
        assert "startup remediation active" in result.stdout + result.stderr, cmd


def test_canonical_key_cross_surface_byte_equality(tmp_path, run_cli, cli):
    """The marker's recorded gate name and the recovery map's lookup key must be byte-identical
    -- otherwise the recovery-map lookup silently never matches."""
    target = _lane(tmp_path, run_cli)
    _write_goal_run(target)
    _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    marker = _read_marker(target)
    assert marker["gates"] == ["goal"]
    assert marker["gates"][0] in cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS
    assert marker["gates"][0] == cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES["goal_failures"]


# --- unwritable / corrupted / clear-failure matrix ------------------------------------------------


def test_flagged_unwritable_ai_work_exits_1_with_synthetic_gate(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    ai_work = target / ".ai-work"
    original_mode = ai_work.stat().st_mode
    ai_work.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "methodology_status_blocking: integrity - remediation_marker, hook" in result.stdout
    finally:
        ai_work.chmod(original_mode)
    assert not _marker_path(target).exists()


def test_plain_unwritable_ai_work_still_exits_2_and_writes_nothing(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    ai_work = target / ".ai-work"
    original_mode = ai_work.stat().st_mode
    ai_work.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _status(run_cli, target, "--fail-on-drift")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "remediation_marker_warn" not in result.stdout
    finally:
        ai_work.chmod(original_mode)
    assert not _marker_path(target).exists()


def test_flagged_absent_uncreatable_ai_work_parent_exits_1(tmp_path, cli):
    """Deferral 3 (V14R1-P3-1): creation-failure path, not just read-only-existing -- `.ai-work`
    itself is absent and its parent cannot be written to, so write_text_atomic's own
    mkdir(parents=True) fails. Exercised directly against the marker-write primitive rather than
    through the full methodology-status CLI subprocess: forcing a genuinely absent-and-
    uncreatable `.ai-work` end-to-end would require the *entire* target tree to be read-only,
    which also breaks ensure_lane_state's own unconditional directory bootstrap earlier in
    methodology_status (a pre-existing, unrelated crash -- not what this deferral is testing).
    The methodology_status wiring from "write failed" to the synthetic gate + exit 1 is proven
    end-to-end by test_flagged_unwritable_ai_work_exits_1_with_synthetic_gate (existing-but-
    readonly .ai-work); this test proves the ABSENT-parent write failure funnels through the
    identical `write_startup_remediation_marker` -> False contract that wiring depends on.
    """
    target = tmp_path / "readonly-parent"
    target.mkdir()
    assert not (target / ".ai-work").exists()
    original_mode = target.stat().st_mode
    target.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        ok = cli.write_startup_remediation_marker(target, gates=["hook"], issues=["x"], create=True)
    finally:
        target.chmod(original_mode)
    assert ok is False


def test_plain_run_refreshes_existing_marker_including_corrupted(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert _marker_path(target).exists()

    _marker_path(target).write_text("{not valid json", encoding="utf-8")
    result = _status(run_cli, target, "--fail-on-drift")
    assert result.returncode == 2, result.stdout + result.stderr
    refreshed = _read_marker(target)
    assert refreshed["gates"] == ["hook"]
    assert refreshed["schema"] == "tautline-startup-remediation/v1"


def test_plain_run_refresh_write_failure_warns_but_still_exits_2(tmp_path, run_cli):
    """CI-safe: a plain (unflagged) run whose refresh write fails must NOT escalate to exit 1 --
    that would make manual/CI callers depend on marker storage. It prints
    `remediation_marker_warn:` and leaves the (now-stale) marker in place so a later flagged
    relaunch or clean run keeps the guard's decisions current."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    entered = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert entered.returncode == 2, entered.stdout + entered.stderr
    original_marker = _read_marker(target)

    ai_work = target / ".ai-work"
    original_mode = ai_work.stat().st_mode
    ai_work.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _status(run_cli, target, "--fail-on-drift")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "remediation_marker_warn:" in result.stdout
    finally:
        ai_work.chmod(original_mode)
    # write_text_atomic never leaves a half-written file -- the stale marker survives untouched.
    assert _read_marker(target) == original_marker


def test_plain_run_with_no_marker_writes_nothing(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    result = _status(run_cli, target, "--fail-on-drift")
    assert result.returncode == 2, result.stdout + result.stderr
    assert not _marker_path(target).exists()


def test_corrupted_marker_still_refuses_blocked_commands(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    _marker_path(target).write_text("{not valid json at all", encoding="utf-8")
    result = run_cli("goal-start", "--target", str(target), "--goal", "docs/x.md")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "startup remediation active" in result.stdout + result.stderr


def test_invalid_utf8_marker_treated_as_corrupted_not_crash(tmp_path, run_cli):
    """Codex T7 R2 P2: a marker containing non-UTF-8 bytes must follow the documented
    corrupted-marker fail-closed path (blocked commands still refuse with the guard message;
    a plain --fail-on-drift run refreshes it in place), not crash with UnicodeDecodeError."""
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    _marker_path(target).write_bytes(b"\xff\xfe not utf-8 at all")

    result = run_cli("goal-start", "--target", str(target), "--goal", "docs/x.md")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "startup remediation active" in result.stdout + result.stderr
    assert "UnicodeDecodeError" not in result.stderr, result.stderr

    refreshed = _status(run_cli, target, "--fail-on-drift")
    assert refreshed.returncode == 2, refreshed.stdout + refreshed.stderr
    assert "UnicodeDecodeError" not in refreshed.stderr, refreshed.stderr
    marker = _read_marker(target)
    assert marker["gates"] == ["hook"]
    assert marker["schema"] == "tautline-startup-remediation/v1"


def test_unclearable_marker_exits_1_synthetic(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    fixed = run_cli("install-hooks", "--target", str(target))
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr

    ai_work = target / ".ai-work"
    original_mode = ai_work.stat().st_mode
    ai_work.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = _status(run_cli, target, "--fail-on-drift")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "methodology_status_blocking: integrity - remediation_marker" in result.stdout
    finally:
        ai_work.chmod(original_mode)
        _marker_path(target).unlink(missing_ok=True)


def test_clear_marker_race_already_deleted_counts_as_cleared(tmp_path, cli, monkeypatch):
    """Concurrency: exists()-then-unlink() raced with a concurrent clean run's delete would raise
    FileNotFoundError and spuriously report "unclearable" (synthetic integrity exit 1) for an
    already-clean lane. Already-gone must count as cleared. Simulated by forcing the (removed)
    exists() precheck answer to True while no marker is on disk -- with the missing_ok fix the
    patch is inert and the absent marker simply clears."""
    target = tmp_path / "lane"
    (target / ".ai-work").mkdir(parents=True)
    monkeypatch.setattr(type(target), "exists", lambda self, **kwargs: True)
    assert cli.clear_startup_remediation_marker(target) is True


# --- marker never touched outside bare --fail-on-drift ---------------------------------------------


def test_marker_never_written_under_strict_alone(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    _status(run_cli, target, "--strict")
    assert not _marker_path(target).exists()


def test_marker_never_written_under_plain_status(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    run_cli("methodology-status", "--target", str(target), "--no-remote")
    assert not _marker_path(target).exists()


def test_marker_never_created_under_combined_strict_and_fail_on_drift(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    result = _status(run_cli, target, "--strict", "--fail-on-drift", "--enter-remediation-on-debt")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not _marker_path(target).exists()


# --- resolved-path refusal message with non-cwd --target -------------------------------------------


def test_refusal_message_names_resolved_marker_path_and_target_for_non_cwd_target(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = subprocess.run(
        [__import__("sys").executable, str(REPO_ROOT / "bin" / "tautline"), "goal-start", "--target", str(target), "--goal", "docs/x.md"],
        cwd=elsewhere,
        env={"PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 1
    resolved_target = str(target.resolve())
    resolved_marker = str((target.resolve() / ".ai-work" / "STARTUP_REMEDIATION.json"))
    combined = result.stdout + result.stderr
    assert resolved_marker in combined
    assert f"--target {resolved_target}" in combined


# --- canonical-policy / dump-* flag-aware behavior (deferral 2) ------------------------------------


def _run_at(cwd: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """canonical-policy/dump-policy-phrases take no --target/--project (they operate on the
    methodology repo checkout relative to cwd), so exercising the guard for them means invoking
    with cwd=target rather than passing --target."""
    import os
    import sys

    home.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), *args],
        cwd=cwd,
        env={"PATH": os.environ["PATH"], "HOME": str(home)},
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_canonical_policy_write_blocked_read_allowed_with_marker(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    home = tmp_path / "home"
    read = _run_at(target, home, "canonical-policy", "--check")
    assert "startup remediation active" not in read.stdout + read.stderr

    write = _run_at(target, home, "canonical-policy", "--write")
    assert write.returncode == 1, write.stdout + write.stderr
    assert "startup remediation active" in write.stdout + write.stderr


def test_dump_policy_phrases_write_blocked_read_allowed_with_marker(tmp_path, run_cli):
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    home = tmp_path / "home"
    read = _run_at(target, home, "dump-policy-phrases", "--check")
    assert "startup remediation active" not in read.stdout + read.stderr

    write = _run_at(target, home, "dump-policy-phrases", "--write")
    assert write.returncode == 1, write.stdout + write.stderr
    assert "startup remediation active" in write.stdout + write.stderr


def test_dump_instrumentation_schema_write_blocked_read_allowed_with_marker(tmp_path, run_cli):
    """0.9.0's dump-instrumentation-schema follows the canonical-policy/dump-* flag-gated idiom:
    --check (read-only freshness) runs while the remediation marker is present; --write (mutates the
    tracked schema artifact) is refused by the dispatch guard."""
    target = _enter_hook_debt_remediation(tmp_path, run_cli)
    home = tmp_path / "home"
    read = _run_at(target, home, "dump-instrumentation-schema", "--check")
    assert "startup remediation active" not in read.stdout + read.stderr

    write = _run_at(target, home, "dump-instrumentation-schema", "--write")
    assert write.returncode == 1, write.stdout + write.stderr
    assert "startup remediation active" in write.stdout + write.stderr


# --- events ------------------------------------------------------------------------------------------


def test_startup_remediation_entered_and_cleared_events(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    entered = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert entered.returncode == 2, entered.stdout + entered.stderr

    events_dir = None
    for line in entered.stdout.splitlines():
        if line.startswith("event_log_jsonl:"):
            events_dir = Path(line.split(": ", 1)[1])
            break
    assert events_dir is not None
    entered_events = [json.loads(line)["event"] for line in events_dir.read_text(encoding="utf-8").strip().splitlines()]
    assert "startup_remediation_entered" in entered_events

    run_cli("install-hooks", "--target", str(target))
    clean = _status(run_cli, target, "--fail-on-drift", "--enter-remediation-on-debt")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    cleared_events = [json.loads(line)["event"] for line in events_dir.read_text(encoding="utf-8").strip().splitlines()]
    assert "startup_remediation_cleared" in cleared_events
