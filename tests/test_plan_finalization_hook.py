import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_ROOT = Path("docs/product/backlog/example-saas-v1/specs")


def _prepare_target(run_cli, tmp_path: Path) -> Path:
    target = tmp_path / "target"
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
        "printf 'No Critical or P1 findings.\\n'\n",
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


def _stdout_json(stdout: str) -> dict:
    return json.loads(stdout)


def _hook_reason(stdout: str) -> str:
    payload = _stdout_json(stdout)
    assert payload["decision"] == "block"
    return payload["reason"]


def _hook_context(stdout: str) -> str:
    payload = _stdout_json(stdout)
    return payload["hookSpecificOutput"]["additionalContext"]


def test_hook_resolves_configured_scratch_path_by_content_hash(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_plan = _write_reviewed_plan(run_cli, target, SOURCE_ROOT / "test-plan.md")
    scratch = _scratch_path(tmp_path, "test-plan.md")
    scratch.write_text(source_plan.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout
    assert "scratch path" not in result.stderr


def test_hook_resolves_random_scratch_path_from_transcript_reference(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "doc-only-exempt-plan.md"
    _write_exempt_plan(target, source_rel)
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
    scratch.write_text("# Scratch Plan\n\nClaude chose this generated path.\n", encoding="utf-8")
    transcript = _transcript(
        tmp_path / "reference.jsonl",
        f"Precheck passed with review-exempt status for {source_rel.as_posix()}.",
    )

    result = run_cli("plan-finalization-hook", stdin=_event(target, plan_file=scratch, transcript_path=transcript))

    assert result.returncode == 0
    assert "ExitPlanMode blocked" not in result.stdout


def test_hook_blocks_random_scratch_reference_to_invalid_source_plan(run_cli, tmp_path):
    target = _prepare_target(run_cli, tmp_path)
    source_rel = SOURCE_ROOT / "bad-exempt-plan.md"
    _write_exempt_plan(target, source_rel, valid=False)
    scratch = _scratch_path(tmp_path, "lexical-toasting-pond.md")
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
