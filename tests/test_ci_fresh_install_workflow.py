"""Shape tests for the CI fresh-install smoke job (real-PyPI-package plan, Task 5).

The smoke job is the standing acceptance test for `pipx install tautline`: on every
PR it builds the real wheel FROM the tree under review, installs it into a clean
venv on Python 3.10 (the declared floor, proven here rather than asserted in a
comment), and runs the front door an adopter actually runs -- both console-script
names, the adopter flow, and the lane-hook surface -- in a scratch project under a
scratch HOME. These tests pin the job's SHAPE so a future edit cannot quietly hollow
out the gate; the behavioral proof is the job's own green run on each PR.

Parsed as YAML rather than regexed as a whole file (same posture as
tests/test_release_tail_workflows.py) so a restructure cannot quietly drop an
invariant.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python.yml"

# The job id doubles as the required-status-check name on the PR base branch
# (Task 5.4 binds the gating configuration to this exact string), so it is pinned
# here as a constant: renaming the job silently unbinds the required check.
#
# Task 5.4 verification record (2026-07-15): every read-only gating surface on the
# private dev repo -- branches/experimental/protection, .../protection/
# required_status_checks, /rulesets, and /rules/branches/experimental -- returned
# HTTP 403 "Upgrade to GitHub Pro or make this repository public to enable this
# feature", so required-check membership CANNOT be configured or verified on this
# repo tier. Until the repo is public (or Pro), the honest gating state is:
# ci-python.yml runs on every PR and this suite pins the job as unskippable, but
# GitHub does not enforce the check as required. The operator must add
# "fresh-install-smoke" to the base branch's required checks (Settings > Branches
# or a ruleset) the moment the tier allows it, and re-run the gh api verification.
SMOKE_JOB_ID = "fresh-install-smoke"

# The seven Claude hooks lane-start installs; the smoke job must assert every one
# of them lands in the scratch HOME's settings (PP-R1-P2-1: a wheel that omits or
# breaks the hook payload must turn the job red).
CLAUDE_HOOK_NAMES = (
    "plan-finalization-hook",
    "branch-liveness-hook",
    "response-guard-hook",
    "tool-rejection-hook",
    "background-command-hook",
    "latest-code-hook",
    "context-rotation-heartbeat-hook",
)

# The embedded-tree canaries: the sdist->wheel data-fidelity trap silently drops
# non-Python files (dotfiles first), so the job must look for the exact payload
# the front door depends on inside the INSTALLED site-packages tree.
EMBEDDED_FILE_CANARIES = (
    ".snapshot-meta.json",
    "VERSION",
    "methodology/canonical-rules.md",
    "plugins/tautline-core/hooks/hooks.json",
)
EMBEDDED_DIR_CANARY = "docs/releases/migrations"


def load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    """Return the `on:` block (PyYAML resolves the bare key `on` to boolean True)."""
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def smoke_job() -> dict:
    workflow = load_workflow(CI_WORKFLOW)
    assert SMOKE_JOB_ID in workflow["jobs"], (
        f"ci-python.yml must carry the {SMOKE_JOB_ID} job: it is the standing "
        "acceptance test for the real PyPI package"
    )
    return workflow["jobs"][SMOKE_JOB_ID]


def smoke_steps() -> list[dict]:
    return smoke_job().get("steps", []) or []


def smoke_run_text() -> str:
    return "\n".join(str(step.get("run", "")) for step in smoke_steps())


def test_smoke_job_exists_and_runs_on_python_310() -> None:
    """The 3.10 floor is PROVEN on every PR, not narrated in a comment.

    The job must pin exactly '3.10' (a quoted string: unquoted YAML 3.10 parses as
    the float 3.1) and must not ride the test matrix -- a floor proven only on
    whichever matrix leg happens to run is not a proven floor.
    """
    job = smoke_job()
    assert "name" not in job, (
        "the job id IS the required-check name the base branch binds (Task 5.4); "
        "a display-name override would silently unbind the gate"
    )
    assert "strategy" not in job, "the smoke pins one Python; the floor is not a matrix leg"
    setup_steps = [
        step for step in job.get("steps", []) if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]
    assert len(setup_steps) == 1, "exactly one setup-python step must pin the floor"
    assert setup_steps[0]["with"]["python-version"] == "3.10", (
        "the smoke must run on the declared 3.10 floor (quoted, so YAML cannot "
        "collapse it to the float 3.1)"
    )


def test_smoke_job_installs_the_built_wheel_into_a_clean_venv() -> None:
    """The tested artifact is the wheel `python -m build` produced from the sdist.

    Installing the source directory (or an editable install) would bypass the
    sdist->wheel data-fidelity trap -- the single most likely silent failure for a
    package embedding 700+ non-Python files.
    """
    text = smoke_run_text()
    assert "registry-package" in text
    assert "--registry pypi" in text
    assert "--write" in text, "a dry-run plan exports nothing; the build must --write"
    assert "--channel experimental" in text, (
        "dev-tree smoke wheels must never be stamped stable; the channel rides "
        "into .snapshot-meta.json"
    )
    build_invocation = text.find("-m build")
    assert build_invocation != -1, "the wheel must come from python -m build"
    assert text.find("registry-package") < build_invocation, (
        "the package tree must be materialized before python -m build consumes it"
    )
    assert "--sdist" not in text and "--wheel" not in text, (
        "python -m build must keep its default sdist+wheel output so the wheel is "
        "built FROM the sdist (the data-fidelity path under test)"
    )
    assert "-m venv" in text, "the wheel must be installed into a freshly created venv"
    install_lines = [
        line for line in text.splitlines() if "pip" in line and " install " in f" {line} "
    ]
    assert any(".whl" in line for line in install_lines), (
        "the produced .whl must be what pip installs"
    )
    for line in install_lines:
        assert " -e" not in line, f"editable install bypasses the wheel entirely: {line!r}"
        assert ".whl" in line or line.strip().endswith("pip install build"), (
            "every pip install must be either the build tool or the built wheel, "
            f"never the source directory: {line!r}"
        )


def test_smoke_job_exercises_version_and_the_adopter_flow() -> None:
    """Both console-script names and the adopter flow run from the installed wheel.

    `minervit-methodology` is the legacy name today's plugin hooks and older
    rendered adapters still invoke; the adopter flow is the front door the README
    sells. `adapter_drift: clean` is methodology_status's own summary line -- the
    flow must END in a coherent, drift-free lane, not merely exit 0.
    """
    text = smoke_run_text()
    assert "tautline version" in text
    assert "minervit-methodology version" in text
    assert "git init" in text, "the adopter flow must run in a scratch git project"
    for verb in ("init-project-adapter", "render-adapters", "methodology-status"):
        assert verb in text, f"the adopter flow must run {verb}"
    assert "adapter_drift: clean" in text, (
        "the job must assert methodology-status's own 'adapter_drift: clean' line"
    )


def test_smoke_job_verifies_embedded_runtime_files() -> None:
    """File canaries inside the INSTALLED tree, not the build directory.

    hatchling only ships what its config includes and `pip` only installs what the
    wheel carries; each canary is a distinct way the payload has silently vanished
    before (dotfile, data dir, plugin hook payload -- PP-R1-P2-1).
    """
    text = smoke_run_text()
    assert "_dist" in text, "the canaries live in the wheel's embedded _dist tree"
    for canary in EMBEDDED_FILE_CANARIES:
        assert canary in text, f"missing embedded-file canary: {canary}"
    assert EMBEDDED_DIR_CANARY in text, (
        "docs/releases/migrations/ is the data-directory canary (migration reports "
        "are runtime data the CLI reads)"
    )


def test_smoke_job_exercises_the_lane_hook_surface() -> None:
    """The README-quickstart lane verb runs, and its hooks land AND execute.

    PP-R1-P2-1: a wheel that omits or breaks the hook payload must turn this job
    red. Landing is asserted in the scratch HOME's Claude settings plus the scratch
    repo's git hooks; execution is proven by running an installed hook command
    through the wheel's console script.
    """
    text = smoke_run_text()
    assert "lane-start --target ." in text, (
        "the lane-hook surface is the README quickstart's own verb: lane-start --target ."
    )
    assert ".claude/settings.json" in text, (
        "the job must look for the installed Claude hooks in the scratch HOME"
    )
    for hook in CLAUDE_HOOK_NAMES:
        assert hook in text, f"missing installed-hook assertion for {hook}"
    assert "tautline tool-rejection-hook" in text, (
        "at least one installed hook command must be EXECUTED from the wheel, "
        "not merely found in settings"
    )
    for git_hook in ("pre-commit", "pre-push"):
        assert git_hook in text, f"the git branch-liveness {git_hook} hook must be asserted"


def test_smoke_job_is_not_soft_gated() -> None:
    """A green-but-skippable job is not a gate (half of PP-R1-P1-2).

    No continue-on-error anywhere in the job, and no `if:` on the job or any step:
    any conditional evaluated on pull requests is a way for the gate to silently
    not run. The workflow itself must fire on pull_request, because required-check
    membership is meaningless for a workflow that never runs on PRs.
    """
    workflow = load_workflow(CI_WORKFLOW)
    triggers = workflow_triggers(workflow)
    assert "pull_request" in triggers, "ci-python.yml is the blocking PR gate"
    job = smoke_job()
    assert not job.get("continue-on-error"), "continue-on-error would defang the gate"
    assert "if" not in job, "a job-level if: could skip the gate on pull requests"
    for step in smoke_steps():
        assert not step.get("continue-on-error"), (
            f"continue-on-error on a step defangs the gate: {step.get('name', step)}"
        )
        assert "if" not in step, (
            f"a step-level if: could skip part of the gate: {step.get('name', step)}"
        )
