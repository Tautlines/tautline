"""Capability-aware standing autonomy directive (directive-core plan).

Covers the renderer (`standing_autonomy_directive_text`), the `autonomy.standingDirective` knob
(`normalize_autonomy`/`autonomy_directive_enabled`), the `autonomy-directive` verb (with `--hook`
total containment), first-output emission from `goal-kickoff-prompt`/`lane-start`/
`context-bootstrap`, and the canonical "Unattended Operation" policy subsection.

The directive resolves its two capability lines from CHEAP LOCAL SIGNALS ONLY -- adapter presence,
`stakeholderQuestions.enabled`, and the startup-remediation marker file -- and NEVER shells out on
any emission path (the auth-issues helper's 20-second `gh` call would stall every session start).
"""

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
CANONICAL = REPO_ROOT / "methodology" / "canonical-rules.md"

REPO_LOCAL_ADAPTER_REL = ".tautline/adapter.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"

DIRECTIVE_HEAD = "STANDING AUTONOMY DIRECTIVE"


# --------------------------------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run(tmp_path, *args, check=False, timeout=90, merge=False):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""}
    kwargs = dict(env=env, text=True, timeout=timeout)
    if merge:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    else:
        kwargs.update(capture_output=True)
    result = subprocess.run([sys.executable, str(CLI_PATH), *args], **kwargs)
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _init_repo(target: Path) -> None:
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


def _write_source_adapter(target: Path, mutate=None) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for standing autonomy directive coverage.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence."},
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


def _prepare_repo(tmp_path, mutate=None, name="lane"):
    """Repo with a repo-local SOURCE adapter (usable via --project). No generated adapter."""
    target = tmp_path / name
    _init_repo(target)
    adapter = _write_source_adapter(target, mutate)
    return target, adapter


def _prepare_rendered(tmp_path, mutate=None, name="lane"):
    """Repo with the generated .tautline.json rendered (usable via --target and the verb)."""
    target, adapter = _prepare_repo(tmp_path, mutate, name)
    _run(
        tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target),
        "--write", check=True,
    )
    return target, adapter


def _knob_off(data: dict) -> None:
    data["autonomy"] = {"standingDirective": False}


def _legacy_t0(data: dict) -> None:
    review = dict(data.get("review") or {})
    budgets = dict(review.get("roundBudgets") or {})
    budgets["T0"] = 3
    review["roundBudgets"] = budgets
    data["review"] = review


# --------------------------------------------------------------------------------------------------
# D1: renderer
# --------------------------------------------------------------------------------------------------


def test_directive_full_capability_names_both_verbs(cli):
    text = cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": True}}, None)
    assert "stakeholder-question-ask" in text
    assert "decision-record" in text
    assert "if that fails" in text  # in-prose ask-time fallback clause


def test_directive_fallbacks_name_summary_rationale_and_next(cli):
    enabled = cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": True}})
    disabled = cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": False}})
    for text in (enabled, disabled):
        assert "--reversibility hard-to-reverse" in text
        assert "--summary" in text
        assert "--rationale" in text
        assert "--next" in text


def test_directive_no_adapter_names_no_tautline_commands(cli):
    text = cli.standing_autonomy_directive_text(None, None)
    assert "`tautline" not in text
    assert "decision-record" not in text
    assert "stakeholder-question-ask" not in text
    assert "session notes or working artifacts" in text


def test_directive_disabled_questions_falls_back_to_ledger(cli):
    text = cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": False}}, None)
    assert "stakeholder-question-ask" not in text
    assert "decision-record --reversibility hard-to-reverse" in text


def test_directive_remediation_marker_falls_back_to_ledger(cli, tmp_path):
    target = tmp_path / "rem"
    marker = cli.startup_remediation_marker_path(target)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}\n", encoding="utf-8")
    text = cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": True}}, target)
    assert "stakeholder-question-ask" not in text
    assert "decision-record --reversibility hard-to-reverse" in text


def _install_no_subprocess(cli, monkeypatch):
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess invoked on a no-shell-out path")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(cli.subprocess, name, boom)
    return calls


def test_render_path_never_shells_out(cli, tmp_path, monkeypatch):
    calls = _install_no_subprocess(cli, monkeypatch)
    marker_target = tmp_path / "rem"
    marker = cli.startup_remediation_marker_path(marker_target)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}\n", encoding="utf-8")
    # Every rendering branch, plus the print wrapper.
    cli.standing_autonomy_directive_text(None, None)
    cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": True}}, tmp_path)
    cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": False}}, tmp_path)
    cli.standing_autonomy_directive_text({"stakeholderQuestions": {"enabled": True}}, marker_target)
    cli.print_autonomy_directive({"autonomy": {"standingDirective": True}}, tmp_path)
    cli.print_autonomy_directive(None, None)
    assert calls == []


def test_hook_full_path_never_shells_out(cli, tmp_path, monkeypatch, capsys):
    target, _ = _prepare_rendered(tmp_path)  # render first (allowed to shell out)
    calls = _install_no_subprocess(cli, monkeypatch)
    rc = cli.autonomy_directive(argparse.Namespace(target=target, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    assert out.startswith(DIRECTIVE_HEAD)


# --------------------------------------------------------------------------------------------------
# D1: knob
# --------------------------------------------------------------------------------------------------


def test_normalize_autonomy_defaults_on(cli):
    assert cli.normalize_autonomy({"autonomy": {}})["standingDirective"] is True


def test_normalize_autonomy_absent_key_is_on(cli):
    assert cli.autonomy_directive_enabled({}) is True
    assert cli.autonomy_directive_enabled(None) is True


def test_normalize_autonomy_rejects_non_bool(cli):
    import pytest

    with pytest.raises(SystemExit):
        cli.normalize_autonomy({"autonomy": {"standingDirective": "yes"}})


def test_normalize_autonomy_rejects_non_object(cli):
    import pytest

    with pytest.raises(SystemExit):
        cli.normalize_autonomy({"autonomy": True})


def test_normalize_autonomy_never_mutates_data(cli):
    data = {"foo": 1}
    cli.normalize_autonomy(data)
    assert data == {"foo": 1}
    data2 = {"autonomy": {"standingDirective": False}}
    snapshot = copy.deepcopy(data2)
    cli.normalize_autonomy(data2)
    assert data2 == snapshot


def test_adapter_schema_accepts_autonomy_knob(cli):
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["autonomy"] = {"standingDirective": False}
    assert cli.schema_validation_errors(data, cli._adapter_schema()) == []


def test_adapter_schema_rejects_unknown_autonomy_key(cli):
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["autonomy"] = {"standingDirective": True, "bogus": 1}
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("bogus" in e for e in errors)


def test_render_omits_absent_autonomy_key(tmp_path):
    target, _ = _prepare_rendered(tmp_path)
    generated = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert "autonomy" not in generated


# --------------------------------------------------------------------------------------------------
# D2: verb
# --------------------------------------------------------------------------------------------------


def test_verb_prints_directive_in_adapter_repo(tmp_path):
    target, _ = _prepare_rendered(tmp_path)
    result = _run(tmp_path, "autonomy-directive", "--target", str(target), check=True)
    assert result.stdout.startswith(DIRECTIVE_HEAD)


def test_verb_knob_off_prints_nothing_exit_zero(tmp_path):
    target, _ = _prepare_rendered(tmp_path, mutate=_knob_off)
    result = _run(tmp_path, "autonomy-directive", "--target", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""


def test_verb_nonhook_surfaces_malformed_adapter_error(tmp_path):
    target = tmp_path / "bad"
    target.mkdir(parents=True)
    (target / ".tautline.json").write_text('{"project": "x"}\n', encoding="utf-8")
    result = _run(tmp_path, "autonomy-directive", "--target", str(target))
    assert result.returncode != 0
    assert "missing required keys" in result.stderr


def test_verb_hook_mode_prints_in_adapter_repo(tmp_path):
    target, _ = _prepare_rendered(tmp_path)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(target), check=True)
    assert result.stdout.startswith(DIRECTIVE_HEAD)


def test_verb_hook_mode_respects_knob_off(tmp_path):
    target, _ = _prepare_rendered(tmp_path, mutate=_knob_off)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""


def test_verb_hook_mode_silent_outside_adapter_repo_exit_zero(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(outside))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""


# --------------------------------------------------------------------------------------------------
# roadmap #14 PR 2: intent-gated SessionStart resumption offer on the un-adapted hook path.
# Zero-trace repos stay byte-silent (total containment); positive onboarding evidence emits exactly
# one root-resolved `onboarding_offer:` line. The hook NEVER shells out on any un-adapted case.
# --------------------------------------------------------------------------------------------------

INTERVIEW_REL = ".ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md"
SOURCE_ADAPTER_REL = ".tautline/adapter.json"


def _write_interview(root: Path) -> None:
    p = root / INTERVIEW_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("interview", encoding="utf-8")


def _write_bare_source_adapter(root: Path) -> None:
    p = root / SOURCE_ADAPTER_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


def test_hook_unmanaged_repo_byte_silent_exit_zero(tmp_path):
    # Zero-trace repo: no marker, no source adapter, no interview -> total containment preserved.
    bare = tmp_path / "bare"
    bare.mkdir(parents=True)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(bare))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""  # byte-empty, not merely stripped-empty


def test_hook_unmanaged_never_shells_out(cli, tmp_path, monkeypatch, capsys):
    bare = tmp_path / "bare"
    bare.mkdir(parents=True)
    calls = _install_no_subprocess(cli, monkeypatch)
    rc = cli.autonomy_directive(argparse.Namespace(target=bare, hook=True))
    assert rc == 0
    assert calls == []
    assert capsys.readouterr().out == ""


def test_hook_interview_pending_emits_single_offer_line(tmp_path):
    repo = tmp_path / "ip"
    repo.mkdir(parents=True)
    _write_interview(repo)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("onboarding_offer:")
    assert "tautline init --target" in lines[0]
    assert "--continue" in lines[0]
    # root-resolved: invocation_cwd == target == repo, so the command targets `.`.
    assert f"--target {repo} --continue" in lines[0] or "--target . --continue" in lines[0]


def test_hook_interview_pending_never_shells_out(cli, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "ip"
    repo.mkdir(parents=True)
    _write_interview(repo)
    calls = _install_no_subprocess(cli, monkeypatch)
    rc = cli.autonomy_directive(argparse.Namespace(target=repo, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("onboarding_offer:")


def test_hook_source_unrendered_emits_render_and_lane_start(tmp_path):
    repo = tmp_path / "su"
    repo.mkdir(parents=True)
    _write_bare_source_adapter(repo)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("onboarding_offer:")
    assert "tautline render-adapters" in lines[0]
    assert "tautline lane-start" in lines[0]


def test_hook_source_unrendered_never_shells_out(cli, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "su"
    repo.mkdir(parents=True)
    _write_bare_source_adapter(repo)
    calls = _install_no_subprocess(cli, monkeypatch)
    rc = cli.autonomy_directive(argparse.Namespace(target=repo, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("onboarding_offer:")


def test_hook_interview_pending_from_subdirectory(cli, tmp_path, monkeypatch, capsys):
    # A start from <repo>/sub/dir must classify like the root (parent-walk) and resolve the offer
    # to the repository root, not the subdirectory -- still shell-free.
    repo = tmp_path / "ip-root"
    repo.mkdir(parents=True)
    _write_interview(repo)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    calls = _install_no_subprocess(cli, monkeypatch)
    rc = cli.autonomy_directive(argparse.Namespace(target=sub, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1
    # root is an ANCESTOR of the invocation cwd -> rendered ABSOLUTE, targeting the repo root.
    assert f"tautline init --target {repo} --continue" in lines[0]


def test_hook_offer_renders_target_relative_to_true_cwd(cli, tmp_path, monkeypatch, capsys):
    # The offer command must render relative to the TRUE process cwd, not --target. From an
    # unrelated cwd, an explicit `--target <repo>` resumes <repo> (absolute), never `.`.
    repo = tmp_path / "ip"
    repo.mkdir(parents=True)
    _write_interview(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(parents=True)
    calls = _install_no_subprocess(cli, monkeypatch)
    monkeypatch.chdir(elsewhere)
    rc = cli.autonomy_directive(argparse.Namespace(target=repo, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert f"tautline init --target {repo} --continue" in lines[0]
    assert "--target . --continue" not in lines[0]


def test_hook_offer_renders_dot_when_target_is_process_cwd(cli, tmp_path, monkeypatch, capsys):
    # Same-cwd case: when the operator sits in the repo, the offer command stays `--target .`.
    repo = tmp_path / "ip"
    repo.mkdir(parents=True)
    _write_interview(repo)
    calls = _install_no_subprocess(cli, monkeypatch)
    monkeypatch.chdir(repo)
    rc = cli.autonomy_directive(argparse.Namespace(target=repo, hook=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "tautline init --target . --continue" in lines[0]


def test_hook_managed_repo_prints_directive_unchanged(tmp_path):
    target, _ = _prepare_rendered(tmp_path)
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(target), check=True)
    assert result.stdout.startswith(DIRECTIVE_HEAD)
    assert "onboarding_offer:" not in result.stdout


def test_verb_hook_mode_silent_on_invalid_adapter_systemexit(tmp_path):
    target = tmp_path / "bad"
    target.mkdir(parents=True)
    (target / ".tautline.json").write_text('{"project": "x"}\n', encoding="utf-8")
    result = _run(tmp_path, "autonomy-directive", "--hook", "--target", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""


def test_verb_hook_mode_never_nonzero_on_internal_error(cli, tmp_path, monkeypatch, capsys):
    target, _ = _prepare_rendered(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(cli, "load_project", boom)
    rc = cli.autonomy_directive(argparse.Namespace(target=target, hook=True))
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


# --------------------------------------------------------------------------------------------------
# D3: entry-point emission
# --------------------------------------------------------------------------------------------------


def test_kickoff_prints_directive_first(tmp_path):
    target, _ = _prepare_rendered(tmp_path)
    result = _run(tmp_path, "goal-kickoff-prompt", "--target", str(target), check=True)
    assert result.stdout.startswith(DIRECTIVE_HEAD)


def test_kickoff_no_adapter_prints_directive_first(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    result = _run(tmp_path, "goal-kickoff-prompt", "--target", str(outside), check=True)
    assert result.stdout.startswith(DIRECTIVE_HEAD)
    assert "session notes or working artifacts" in result.stdout
    # roadmap #14 PR 1: the adapterless kickoff now follows the directive with the guided-onboarding
    # offer (state-aware) instead of the generic goal template that led into a failing lane-start.
    assert "onboarding_offer: this repository has no Tautline adapter." in result.stdout
    assert "AskUserQuestion" in result.stdout


def test_lane_start_prints_directive_first(tmp_path):
    target, adapter = _prepare_repo(tmp_path)
    result = _run(
        tmp_path, "lane-start", "--project", str(adapter), "--target", str(target), "--skip-update",
        check=True,
    )
    assert result.stdout.startswith(DIRECTIVE_HEAD)


def test_context_bootstrap_prints_directive_first(tmp_path):
    target, adapter = _prepare_repo(tmp_path)
    result = _run(
        tmp_path, "context-bootstrap", "--project", str(adapter),
        "--target", str(target), check=True,
    )
    assert result.stdout.startswith(DIRECTIVE_HEAD)


def test_entry_points_suppressed_when_knob_off(tmp_path):
    target, adapter = _prepare_repo(tmp_path, mutate=_knob_off)
    result = _run(
        tmp_path, "context-bootstrap", "--project", str(adapter),
        "--target", str(target), check=True,
    )
    assert DIRECTIVE_HEAD not in result.stdout


def test_legacy_coercion_warning_prints_after_directive(tmp_path):
    target, adapter = _prepare_repo(tmp_path, mutate=_legacy_t0)
    result = _run(
        tmp_path, "context-bootstrap", "--project", str(adapter),
        "--target", str(target), check=True,
    )
    assert result.stdout.startswith(DIRECTIVE_HEAD)
    # The coercion warning is a STDERR diagnostic replayed AFTER the directive, byte-intact.
    assert "is legacy; coercing to 0" in result.stderr


def test_legacy_warning_merged_stream_byte_order(tmp_path):
    target, adapter = _prepare_repo(tmp_path, mutate=_legacy_t0)
    result = _run(
        tmp_path, "context-bootstrap", "--project", str(adapter), "--target", str(target),
        merge=True,
    )
    assert result.returncode == 0, result.stdout
    merged = result.stdout
    directive_at = merged.index(DIRECTIVE_HEAD)
    warning_at = merged.index("is legacy; coercing to 0")
    assert directive_at < warning_at, merged


# --------------------------------------------------------------------------------------------------
# D4: canonical "Unattended Operation" policy subsection (semantic presence, not byte-only)
# --------------------------------------------------------------------------------------------------


def _canonical_normalized() -> str:
    return " ".join(CANONICAL.read_text(encoding="utf-8").split())


def test_canonical_rules_unattended_operation_present():
    assert "## Unattended Operation" in CANONICAL.read_text(encoding="utf-8")


def test_canonical_rules_unattended_opt_out_named():
    assert "the adapter disables `autonomy.standingDirective`" in _canonical_normalized()


def test_canonical_rules_unattended_durable_record_required():
    norm = _canonical_normalized()
    assert "require a durable record with rationale and reversibility" in norm
    assert "The record, not chat prose, is the operator's review surface." in norm


def test_canonical_rules_unattended_async_question_fallback_stated():
    norm = _canonical_normalized()
    assert "are queued asynchronously" in norm
    assert "falling back to a hard-to-reverse decision entry carrying the question" in norm


def test_canonical_rules_unattended_guards_unchanged_stated():
    marker = "Guard and review-gate mechanics are unchanged by this section"
    assert marker in _canonical_normalized()
