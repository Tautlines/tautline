import json
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_ROOT = Path("docs/product/backlog/example-saas-v1/specs")


def _prepare_target(run_cli, tmp_path: Path, name: str = "target") -> Path:
    target = tmp_path / name
    target.mkdir()
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:example-org/example-saas.git"],
        check=True,
    )
    rendered = run_cli("render-adapters", "--project", str(EXAMPLE), "--target", str(target), "--write")
    assert rendered.returncode == 0, rendered.stderr
    (target / SOURCE_ROOT).mkdir(parents=True, exist_ok=True)
    wrapper = target / "scripts" / "codex-review.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'Codex review args: %s\\n' \"$*\"\n"
        "printf 'Verdict: clean\\n'\n"
        # Item 76 WS2: this fixture's log reaches the strict trusted path.
        "printf '## Findings\\nNo Critical or P1 findings.\\n'\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return target


def _write_reviewed_plan(run_cli, target: Path, rel: Path) -> Path:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Test Plan\n\n"
        "## Milestone Goal\n"
        "Deliver a safe test milestone with clear implementation boundaries and evidence.\n\n"
        "## Non-Goals\n"
        "Do not change production behavior outside the tested fixture.\n\n"
        "## Evidence And Sources\n"
        "Use the adapter, current backlog entry, and review logs as source evidence.\n\n"
        "## Assumptions\n"
        "The test lane has a configured source-of-truth path and review wrapper.\n\n"
        "## Ordered Scope\n"
        "1. Build the fixture.\n"
        "2. Validate the gate.\n"
        "3. Record the review evidence.\n\n"
        "## Dependencies\n"
        "The plan depends on the configured adapter review wrapper and local lane files.\n\n"
        "## Acceptance Criteria\n"
        "The plan finalization precheck fails before review evidence and passes after clean review evidence.\n\n"
        "## Tests And Validation\n"
        "Run run-plan-review and plan-finalization-precheck; then edit the plan and confirm stale evidence fails.\n\n"
        "## Review And Merge Gates\n"
        "Cross-model review must be recorded before finalization. Merge gates are not used in this fixture.\n\n"
        "## Risks\n"
        "The main risk is accepting stale review evidence.\n\n"
        "## Open Decisions\n"
        "None.\n\n"
        "## Behavior Source Materials\n"
        "- `docs/product/user-scenarios.md`: reviewed; product scenarios reviewed for this fixture plan.\n"
        "- `docs/product/acceptance-criteria.md`: reviewed; acceptance criteria reviewed for this fixture plan.\n\n"
        "## Completion Definition\n"
        "Done means the precheck accepts clean current evidence and rejects stale evidence.\n",
        encoding="utf-8",
    )
    reviewed = run_cli(
        "run-plan-review",
        "--target",
        str(target),
        "--plan",
        rel.as_posix(),
        "--round",
        "R1",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    assert (path.parent / ".plan-reviews" / f"{path.stem}.json").exists()
    return path


def _write_exempt_plan(target: Path, rel: Path, *, valid: bool = True) -> Path:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    no_behavior = (
        "- No product/runtime behavior change: no product code, schema, route, UI, infra, "
        "deployment, security, data, behavior-spec, or test-harness changes.\n"
        if valid
        else ""
    )
    path.write_text(
        "# Doc Only Plan\n\n"
        "## Plan Review Exemption\n\n"
        "- Exemption: doc-only\n"
        f"{no_behavior}"
        "- Implementation review/gates: run normal implementation diff review and required validation gates.\n",
        encoding="utf-8",
    )
    return path


def _transcript(path: Path, text: str) -> Path:
    record = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def _event(target: Path, *, plan_file: Path | str | None = None, transcript_path: Path | None = None, plan: str | None = None) -> str:
    tool_input: dict[str, str] = {}
    if plan_file is not None:
        tool_input["planFilePath"] = str(plan_file)
    if plan is not None:
        tool_input["plan"] = plan
    event: dict[str, object] = {"tool_name": "ExitPlanMode", "cwd": str(target), "tool_input": tool_input}
    if transcript_path is not None:
        event["transcript_path"] = str(transcript_path)
    return json.dumps(event) + "\n"


def _scratch_path(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "home" / ".claude" / "plans" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _unconfigured_scratch_path(tmp_path: Path, name: str) -> Path:
    """A scratch plan path that is NOT under the adapter's planningArtifacts.scratchPaths."""
    path = tmp_path / "drafts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _quoted_target(target: Path) -> str:
    return shlex.quote(str(target.resolve()))


def _stdout_json(stdout: str) -> dict:
    return json.loads(stdout)


def _hook_reason(stdout: str) -> str:
    payload = _stdout_json(stdout)
    assert payload["decision"] == "block"
    return payload["reason"]


def _hook_context(stdout: str) -> str:
    payload = _stdout_json(stdout)
    return payload["hookSpecificOutput"]["additionalContext"]


def _write_reviewed_compliant_plan(run_cli, target: Path, rel: Path) -> Path:
    """Like `_write_reviewed_plan`, but shape-compliant (Workstreams/model-tier/decision-record)
    so a `block`-enforcement test exercises ONLY the goal-prompt check, not the pre-existing
    plan-authoring shape check `plan_finalization_precheck_errors` already applies under `block`."""
    path = _write_reviewed_plan(run_cli, target, rel)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n## Workstreams\n"
        "WS1 is a hard predecessor for WS2; WS2 is parallel-safe (no shared files).\n\n"
        "### Task 1  model-tier: standard\n"
        "Use best judgment while executing; record non-obvious calls with "
        "`tautline decision-record`.\n",
        encoding="utf-8",
    )
    reviewed = run_cli(
        "run-plan-review", "--target", str(target), "--plan", rel.as_posix(),
        "--round", "R1", "--model", "codex-test", "--verdict", "clean",
        "--unresolved-critical-count", "0", "--unresolved-p1-count", "0",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    return path


def _set_planning_enforcement(target: Path, level: str) -> None:
    """Edit the RENDERED lane-local adapter (`.tautline.json`) directly. Safe here because the
    hook loads it with the plain `load_project` (no source-checksum verification) -- unlike
    `lane_project`, which strict CLI verbs use and which does check `sourceAdapterSha256`
    against a copied/edited lane adapter."""
    marker = target / ".tautline.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["planning"] = {"authoringStandard": {"enforcement": level}}
    marker.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_hook_never_blocks_exitplanmode_on_a_missing_goal_prompt(run_cli, tmp_path):
    """Codex R1 (final confirming round) P1: a goal-prompt-missing finding must NEVER refuse
    ExitPlanMode, even under `block` -- Claude is still in read-only plan mode here, and the only
    remedy (`goal-assignment --out`) WRITES a file. A hook that blocks the exit a write needs to
    run is an unconditional deadlock: the plan can never leave read-only mode to create the
    artifact that would let it pass. Advisory-only here; `plan-finalization-precheck` (which runs
    AFTER plan mode is left) still enforces `block` in full."""
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_compliant_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    _set_planning_enforcement(target, "block")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=str(source_plan)))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    context = _hook_context(result.stdout)
    assert "goal-prompt" in context.lower()
    assert "does not block exitplanmode" in context.lower() or "does not block" in context.lower()
    assert "goal-assignment" in context


def test_hook_stays_silent_once_a_goal_prompt_is_shipped(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_compliant_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    _set_planning_enforcement(target, "block")
    source_plan.parent.joinpath("goal-ws1.txt").write_text(
        f"/goal from the finalized plan `{(SOURCE_ROOT / 'test-plan.md').as_posix()}`\n",
        encoding="utf-8",
    )

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=str(source_plan)))

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_resolves_configured_scratch_path_by_content_hash(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    scratch = _scratch_path(tmp_path, "test-plan.md")
    scratch.write_text(source_plan.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    assert "scratch path" not in result.stderr
    # Load-bearing ordering invariant: content-hash matching MUST stay ahead of the
    # configured-scratch escape, so a scratch COPY of a real repo plan still binds to its source
    # and keeps its precheck gate. Without this assertion the test also passes when the escape is
    # hoisted above the content-hash attempts -- the escape satisfies "not blocked" too.
    assert "Minervit plan-mode scratch escape" not in result.stdout


def test_hook_resolves_random_scratch_path_from_transcript_reference(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "doc-only-exempt-plan.md"
    _write_exempt_plan(target, source_rel)
    # Unconfigured scratch path: a CONFIGURED scratch path is classified as scratch before
    # reference matching and takes the plan-mode escape, which would leave this test asserting
    # nothing about find_source_plan_by_reference.
    scratch = _unconfigured_scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nClaude chose this generated path.\n", encoding="utf-8")
    transcript = _transcript(
        tmp_path / "reference.jsonl",
        f"Precheck passed with review-exempt status for {source_rel.as_posix()}.",
    )

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch, transcript_path=transcript))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    # The referenced source plan was adopted -- not waved through by the scratch escape.
    assert "Minervit plan-mode scratch escape" not in result.stdout


def test_hook_blocks_random_scratch_reference_to_invalid_source_plan(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "bad-exempt-plan.md"
    _write_exempt_plan(target, source_rel, valid=False)
    # Unconfigured scratch path: reference matching is still the live resolution path here, so an
    # invalid referenced source plan must still block. (A CONFIGURED scratch path is classified as
    # scratch before reference matching and reaches the plan-mode escape instead - see
    # test_configured_scratch_plan_wins_over_transcript_reference.)
    scratch = _unconfigured_scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n", encoding="utf-8")
    transcript = _transcript(tmp_path / "bad-reference.jsonl", f"Trying to exit plan mode for {source_rel.as_posix()}.")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch, transcript_path=transcript))

    assert result.returncode == 0
    reason = _hook_reason(result.stdout)
    assert "ExitPlanMode blocked" in reason
    assert "Plan Review Exemption must state no product/runtime behavior change" in reason


def test_hook_allows_unresolved_configured_scratch_path_as_plan_mode_escape(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    _write_exempt_plan(target, SOURCE_ROOT / "plan.md")
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nNo source-of-truth reference.\n", encoding="utf-8")
    transcript = _transcript(tmp_path / "scratch-only.jsonl", "The temporary scratch artifact is /tmp/draft-plan.md.")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch, transcript_path=transcript))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    context = _hook_context(result.stdout)
    assert "Minervit plan-mode scratch escape" in context
    assert "not source-of-truth" in context


def test_hook_blocks_non_configured_scratch_path(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    scratch = tmp_path / "non-configured-scratch-plan.md"
    scratch.write_text("# Non Configured Scratch\n", encoding="utf-8")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch))

    assert result.returncode == 0
    reason = _hook_reason(result.stdout)
    assert "ExitPlanMode blocked" in reason
    assert "plan outside source-of-truth path" in reason


def test_configured_scratch_plan_wins_over_transcript_reference(run_cli, tmp_path):
    # Defect: a plan under the adapter's configured scratchPaths was hijacked to an unrelated repo
    # plan whenever the recent transcript happened to name exactly one source-of-truth plan.
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "doc-only-exempt-plan.md"
    _write_exempt_plan(target, source_rel)
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nUnrelated scratch draft.\n", encoding="utf-8")
    transcript = _transcript(
        tmp_path / "reference.jsonl",
        f"Earlier we discussed {source_rel.as_posix()} in passing.",
    )

    result = run_cli(
        "plan-finalization-hook",
        stdin=_event(target, plan_file=scratch, transcript_path=transcript),
    )

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    context = _hook_context(result.stdout)
    assert "Minervit plan-mode scratch escape" in context
    assert str(scratch.resolve()) in context
    assert str(source_rel.as_posix()) not in context


def test_configured_scratch_plan_wins_over_same_filename_source_plan(run_cli, tmp_path):
    # The configured-scratch check also precedes find_source_plan_by_name, so a scratch plan that
    # merely SHARES A FILENAME with a repo plan no longer adopts it. A filename collision is weak
    # evidence; only a content-hash match (checked earlier) is strong enough to bind. Pre-fix the
    # invalid repo plan below was adopted by name and BLOCKED ExitPlanMode; now the scratch plan
    # reaches the escape instead.
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "bad-exempt-plan.md"
    _write_exempt_plan(target, source_rel, valid=False)
    scratch = _scratch_path(tmp_path, "bad-exempt-plan.md")
    scratch.write_text("# Scratch Plan\n\nSame filename, unrelated content.\n", encoding="utf-8")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    context = _hook_context(result.stdout)
    assert "Minervit plan-mode scratch escape" in context
    assert str(scratch.resolve()) in context
    # the same-named repo plan was not adopted
    assert source_rel.as_posix() not in context


def test_unconfigured_scratch_still_resolves_by_reference(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "doc-only-exempt-plan.md"
    _write_exempt_plan(target, source_rel)
    scratch = _unconfigured_scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nUnrelated scratch draft.\n", encoding="utf-8")
    transcript = _transcript(
        tmp_path / "reference.jsonl",
        f"Earlier we discussed {source_rel.as_posix()} in passing.",
    )

    result = run_cli(
        "plan-finalization-hook",
        stdin=_event(target, plan_file=scratch, transcript_path=transcript),
    )

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    assert "Minervit plan-mode scratch escape" not in result.stdout


def test_recovery_instruction_names_resolved_target(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path, name="lane with space")
    plan_rel = SOURCE_ROOT / "unreviewed-plan.md"
    plan_path = target / plan_rel
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        "# Unreviewed Plan\n\nNo review evidence recorded yet.\n", encoding="utf-8"
    )

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=plan_path))

    assert result.returncode == 0
    reason = _hook_reason(result.stdout)
    assert "ExitPlanMode blocked" in reason
    assert f"--target {_quoted_target(target)}" in reason
    assert "--target ." not in reason


def test_scratch_escape_context_names_resolved_target(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path, name="lane with space")
    _write_exempt_plan(target, SOURCE_ROOT / "plan.md")
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nNo source-of-truth reference.\n", encoding="utf-8")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch))

    assert result.returncode == 0
    context = _hook_context(result.stdout)
    assert "Minervit plan-mode scratch escape" in context
    quoted = _quoted_target(target)
    for command in ("run-plan-review", "finalize-plan-review", "plan-finalization-precheck"):
        assert f"{command} --target {quoted}" in context
    # every --target rendering in the escape message resolves; none fall back to the ambiguous "."
    assert "--target ." not in context


def test_goal_ledger_nudge_names_resolved_target(run_cli, tmp_path):
    # The goal-ledger nudge is the guard's other command example, and it carried the same
    # ambiguous `--target .` as the plan-review remedies.
    target = _prepare_target(run_cli, tmp_path, name="lane with space")
    plan_rel = SOURCE_ROOT / "plan.md"
    _write_exempt_plan(target, plan_rel)

    result = run_cli(
        "plan-finalization-hook",
        stdin=_event(
            target,
            plan_file=target / plan_rel,
            plan="This is a multi-milestone effort spanning multiple PRs.",
        ),
    )

    assert result.returncode == 0
    context = _hook_context(result.stdout)
    assert "Minervit goal-ledger check" in context
    assert f"goal-start --target {_quoted_target(target)}" in context
    assert "--target ." not in context


def test_hook_ignores_archive_reference_when_resolving_random_scratch_path(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    archived_rel = SOURCE_ROOT / "archive" / "old-exempt-plan.md"
    _write_exempt_plan(target, archived_rel)
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n", encoding="utf-8")
    transcript = _transcript(tmp_path / "archive-reference.jsonl", f"Archived evidence only: {archived_rel.as_posix()}.")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch, transcript_path=transcript))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    assert "Minervit plan-mode scratch escape" in _hook_context(result.stdout)


def test_both_advisories_emit_one_parsable_hook_response(run_cli, tmp_path):
    """Codex R1 P2 (this lineage): when the goal-prompt advisory AND the goal-ledger nudge both
    fire in one hook evaluation, they must arrive as ONE JSON response — hook consumers parse a
    single object, and two concatenated objects make both advisories unreadable."""
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_compliant_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    _set_planning_enforcement(target, "block")
    # No goal-prompt artifact exists (fires the goal-prompt advisory), and the EVENT's inline
    # plan text reads substantial (fires the goal-ledger nudge via extra_reference_text; no
    # goal ledger exists in a fresh target). The reviewed file itself stays untouched, so the
    # hook reaches the advisory path rather than the stale-evidence refusal.
    result = run_cli(
        "plan-finalization-hook",
        stdin=_event(
            target,
            plan_file=str(source_plan),
            plan="This is a multi-PR effort delivered across milestones.",
        ),
    )

    assert result.returncode == 0
    # _stdout_json raises if stdout is not exactly one JSON document.
    context = _hook_context(result.stdout)
    assert "Minervit goal-prompt check:" in context
    assert "Minervit goal-ledger check:" in context


def test_advise_level_missing_goal_prompt_still_reaches_the_hook_advisory(run_cli, tmp_path):
    """Codex R2 P2 (this lineage): at `advise` — the DEFAULT — the goal-prompt report returns
    warnings, not errors, and the hook used to discard them entirely: default lanes got no hook
    advisory for a missing goal prompt. The warning path must reach the same single advisory."""
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_compliant_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    _set_planning_enforcement(target, "advise")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=str(source_plan)))

    assert result.returncode == 0
    context = _hook_context(result.stdout)
    assert "Minervit goal-prompt check:" in context
    assert "does NOT block ExitPlanMode" in context
