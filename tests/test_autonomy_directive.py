"""Capability-aware standing autonomy directive (directive-core plan).

Covers the renderer (`standing_autonomy_directive_text`), the `autonomy.standingDirective` knob
(`normalize_autonomy`/`autonomy_directive_enabled`), the `autonomy-directive` verb (with `--hook`
total containment), first-output emission from `goal-kickoff-prompt`/`lane-start`/
`context-bootstrap`, and the canonical "Unattended Operation" policy subsection.

The directive resolves its two capability lines from CHEAP LOCAL SIGNALS ONLY -- adapter presence,
`stakeholderQuestions.enabled`, and the startup-remediation marker file -- and NEVER shells out on
any emission path (the auth-issues helper's 20-second `gh` call would stall every session start).
"""

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


def _install_no_subprocess(cli, monkeypatch):
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess invoked on a no-shell-out path")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(cli.subprocess, name, boom)
    return calls


# --------------------------------------------------------------------------------------------------
# D1: knob
# --------------------------------------------------------------------------------------------------


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


# --------------------------------------------------------------------------------------------------
# D3: entry-point emission
# --------------------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------------------
# D4: canonical "Unattended Operation" policy subsection (semantic presence, not byte-only)
# --------------------------------------------------------------------------------------------------


def _canonical_normalized() -> str:
    return " ".join(CANONICAL.read_text(encoding="utf-8").split())
