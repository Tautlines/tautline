"""The hosted-runner fallback must not be takeable silently (item 57).

`runs-on: ${{ vars.CI_RUNNER_LABEL || 'ubuntu-latest' }}` fails OPEN: clear the repo variable and
every job routes back to billed GitHub compute while still reporting green. The saving the
self-hosted move exists to capture disappears with no signal at all. `.github/actions/
assert-runner-identity` closes that, and this module is what keeps it closed.

Two of these tests are shape tests over the workflow YAML; the third EXECUTES the action's shell
body. That split is deliberate. A presence-only suite stays green against an action whose branches
are inverted, whose escape hatch is unreachable, or whose body has been defanged into a pure
warning -- so the truth table below runs the real script under real environments and asserts the
real exit codes. Parsed as YAML rather than regexed, same posture as
tests/test_evidence_artifacts.py, so a restructure cannot quietly drop an invariant.

The canonical-repo comparison is case-INSENSITIVE, and `test_lowercase_canonical_repo_still_fails`
is not a stylistic nicety: GitHub emits `Tautlines/tautline-dev` while this repo's own git remote
is `tautlines/tautline-dev`. An exact compare would classify the canonical repo as a fork, exit 0,
and leave the silent fallback fully intact -- the guard bypassing itself, which is precisely the
failure class the action exists to catch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION = REPO_ROOT / ".github" / "actions" / "assert-runner-identity" / "action.yml"

# The local action reference. It has no `@sha` because it is not a supply-chain surface: it
# resolves inside the commit under test and moves with it. tests/test_evidence_artifacts.py
# exempts exactly this shape and nothing else.
ACTION_REF = "./.github/actions/assert-runner-identity"

CANONICAL = "Tautlines/tautline-dev"

# The two inputs every call site must pass. Reading these from `vars` inside the composite action
# is what this design deliberately avoids: if `vars` resolves empty there, EXPECTED_LABEL is empty
# on every run, every canonical job takes the "unset" branch, and all six gates go red claiming a
# silent fallback while the variable is set correctly.
REQUIRED_INPUTS = ("runner-label", "allow-hosted-fallback")

# The env contract the shell body actually reads. The `${{ }}` expressions mean nothing to bash,
# so the truth-table test drives THESE names -- and CANONICAL must always be set, because the
# script runs under `set -u` and an unbound one aborts it, failing the test for the wrong reason.
EXPECTED_ENV_MAPPING = {
    "EXPECTED_LABEL": "inputs.runner-label",
    "ALLOW_HOSTED": "inputs.allow-hosted-fallback",
    "CANONICAL": "inputs.canonical-repo",
    "THIS_REPO": "github.repository",
}


def _workflow_docs() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    }


def _locally_routed_jobs() -> list[tuple[str, str, list[dict]]]:
    """Every (workflow, job, steps) whose `runs-on` selects the runner via CI_RUNNER_LABEL.

    Derived from the workflows themselves rather than hardcoded, so a NEW job that opts into local
    routing is covered the moment it is added -- the failure mode being guarded is a job that
    silently routes to billed compute, and a hardcoded list would not see it.
    """
    found = []
    for name, document in _workflow_docs().items():
        for job_id, job in (document.get("jobs") or {}).items():
            if "CI_RUNNER_LABEL" in str(job.get("runs-on", "")):
                found.append((name, job_id, job.get("steps") or []))
    return found


def _action_step() -> dict:
    document = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    steps = document["runs"]["steps"]
    assert len(steps) == 1, "the action is one shell step; update this test if that changes"
    return steps[0]


def _run_action(env: dict[str, str]) -> subprocess.CompletedProcess:
    """Execute the action's real shell body under a controlled environment."""
    script = _action_step()["run"]
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _env(this_repo: str, label: str, allow: str, runner_env: str | None) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "THIS_REPO": this_repo,
        "EXPECTED_LABEL": label,
        "ALLOW_HOSTED": allow,
        "CANONICAL": CANONICAL,
    }
    if runner_env is not None:
        env["RUNNER_ENVIRONMENT"] = runner_env
    return env


# --- shape: every locally-routed job asserts its own identity ----------------------------------


def test_every_locally_routed_job_asserts_runner_identity():
    offenders = [
        f"{workflow}:{job}"
        for workflow, job, steps in _locally_routed_jobs()
        if not any(str(step.get("uses", "")) == ACTION_REF for step in steps)
    ]
    assert not offenders, (
        "these jobs select their runner via CI_RUNNER_LABEL but never assert where they "
        f"landed, so a cleared variable routes them to billed compute silently: {offenders}"
    )


def test_locally_routed_jobs_cover_every_expected_workflow():
    """A guard that silently stopped covering a workflow would look identical to a passing one.

    `renderer-ci` and `npm-audit` joined on operator instruction 2026-08-02 ("no more billed hosted
    runs"), superseding the earlier recommendation to leave them hosted because there was no bill
    worth saving. They are the last two workflows that actually billed on this repo.

    Still deliberately ABSENT, and each for its own reason:
      - `publish-pypi` / `publish-npm` — release-gated, and a release must never depend on whether
        a laptop is awake (operator answer, same date).
      - `release-drift-check` — gated `if: github.repository == 'tautlines/tautline'`; it runs on
        the public mirror and is skipped here, so routing it would change no bill.
    """
    workflows = {workflow for workflow, _, _ in _locally_routed_jobs()}
    assert workflows == {
        "ci-python.yml",
        "ci-python-full.yml",
        "npm-audit.yml",
        "renderer-ci.yml",
        "validate.yml",
    }
    assert len(_locally_routed_jobs()) == 8


def test_assertion_runs_immediately_after_checkout():
    """Position is the point: the failure must precede the spend.

    Presence alone is satisfied by an action placed after setup, install, and the test run -- at
    which point the job has done all of its expensive billed work on hosted compute and only then
    reports that it should not have been there.
    """
    for workflow, job, steps in _locally_routed_jobs():
        uses = [str(step.get("uses", "")) for step in steps]
        checkout = next(
            (i for i, ref in enumerate(uses) if ref.startswith("actions/checkout@")), None
        )
        assert checkout is not None, f"{workflow}:{job} has no checkout step"
        assert uses[checkout + 1] == ACTION_REF, (
            f"{workflow}:{job} must assert runner identity directly after checkout, "
            f"before any billed work; found {uses[checkout + 1]!r}"
        )


def test_every_call_site_passes_both_repo_variables():
    for workflow, job, steps in _locally_routed_jobs():
        step = next(step for step in steps if str(step.get("uses", "")) == ACTION_REF)
        passed = step.get("with") or {}
        for required in REQUIRED_INPUTS:
            assert required in passed, (
                f"{workflow}:{job} must pass {required} explicitly -- the action cannot read "
                "vars.* from inside composite context"
            )
        assert "vars.CI_RUNNER_LABEL" in str(passed["runner-label"])
        assert "vars.CI_ALLOW_HOSTED_FALLBACK" in str(passed["allow-hosted-fallback"])


def test_runs_on_expressions_are_unchanged():
    """This change removes the silence, not the fallback. Forks still need it."""
    for name, document in _workflow_docs().items():
        for job_id, job in (document.get("jobs") or {}).items():
            runs_on = str(job.get("runs-on", ""))
            if "CI_RUNNER_LABEL" in runs_on:
                assert runs_on == "${{ vars.CI_RUNNER_LABEL || 'ubuntu-latest' }}", (
                    f"{name}:{job_id} changed its routing expression; this item asserts identity "
                    "at run time and deliberately leaves runs-on alone"
                )


# --- shape: the action's own wiring -------------------------------------------------------------


def test_action_declares_the_inputs_it_consumes():
    document = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    declared = document.get("inputs") or {}
    for required in (*REQUIRED_INPUTS, "canonical-repo"):
        assert required in declared, f"action.yml must declare the {required} input"
    assert declared["canonical-repo"]["default"] == CANONICAL


def test_action_env_maps_each_input_exactly():
    """Assert the MAPPINGS, not just the key names.

    A key-name-only check stays green if EXPECTED_LABEL is wired to inputs.allow-hosted-fallback by
    mistake, or if runner-label is left unwired entirely -- both green in the suite and broken in
    CI, which is the worst place to find out.
    """
    env = _action_step()["env"]
    assert set(env) == set(EXPECTED_ENV_MAPPING), (
        "the truth-table test drives these exact names; renaming one here without renaming it "
        "there would leave the suite green against an action nothing exercises"
    )
    for name, expression in EXPECTED_ENV_MAPPING.items():
        assert expression in str(env[name]), f"{name} must come from {expression}"


def test_action_never_reads_vars_context():
    """`vars` inside a composite action is at best ambiguously supported.

    If it resolves empty, EXPECTED_LABEL is empty on every run and all six gates go red claiming a
    silent fallback while the variable was set correctly the whole time -- a self-inflicted outage
    of the entire CI surface, caused by the guard meant to protect it.

    The invariant is that no `vars` EXPRESSION is ever EVALUATED here. Checked against the PARSED
    document rather than the raw text, because the file's own header comment quotes the
    `${{ vars.CI_RUNNER_LABEL || 'ubuntu-latest' }}` expression to explain what it is guarding --
    and YAML comments are dropped by the parser, which is exactly the distinction that matters:
    the runner substitutes expressions in values, never in comments.
    """

    def _strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for key, value in node.items():
                yield from _strings(key)
                yield from _strings(value)
        elif isinstance(node, list):
            for item in node:
                yield from _strings(item)

    document = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    offenders = [value for value in _strings(document) if "${{ vars." in value]
    assert not offenders, (
        "the action must receive repo variables from its caller, never evaluate vars.* itself: "
        f"{offenders}"
    )


# --- behaviour: the truth table, executed -------------------------------------------------------


@pytest.mark.parametrize(
    "case,this_repo,label,runner_env,allow,expect_exit,expect_marker",
    [
        # A fork has no repo variables and hosted is CORRECT for it. This row is why a bare
        # "fail if unset" assert was never an option.
        ("fork", "someone/fork", "", "github-hosted", "", 0, None),
        # The R1 P1 regression guard. Lowercase canonical must NOT be read as a fork.
        ("lowercase-canonical", CANONICAL.lower(), "", "github-hosted", "", 1, "::error"),
        ("intended-local", CANONICAL, "tautline", "self-hosted", "", 0, None),
        ("label-resolved-hosted", CANONICAL, "tautline", "github-hosted", "", 1, "::error"),
        # The hatch must be honoured on BOTH failing paths, or the error above advertises a
        # recovery its own branch never reads.
        ("hatch-with-label", CANONICAL, "tautline", "github-hosted", "1", 0, "::warning"),
        ("hatch-without-label", CANONICAL, "", "github-hosted", "1", 0, "::warning"),
        # The unset row must NOT depend on RUNNER_ENVIRONMENT: with no label, runs-on resolved to
        # ubuntu-latest by construction. Depending on a runner-supplied variable would fail OPEN
        # for the one case this whole change exists to catch.
        ("silent-fallback-no-runner-env", CANONICAL, "", None, "", 1, "::error"),
    ],
)
def test_truth_table(case, this_repo, label, runner_env, allow, expect_exit, expect_marker):
    result = _run_action(_env(this_repo, label, allow, runner_env))
    assert result.returncode == expect_exit, (
        f"{case}: expected exit {expect_exit}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    if expect_marker:
        assert expect_marker in result.stdout, (
            f"{case}: expected a {expect_marker} annotation, got: {result.stdout}"
        )


@pytest.mark.parametrize(
    "case,label,allow",
    [("silent-fallback", "", ""), ("landed-hosted", "tautline", "")],
)
def test_every_refusal_names_a_recovery(case, label, allow):
    """An error that does not say how to fix it is a dead end.

    Both refusals must name CI_ALLOW_HOSTED_FALLBACK, and the hatch must actually work from that
    state -- an earlier draft's "landed hosted" branch advertised a variable it never read.
    """
    result = _run_action(_env(CANONICAL, label, allow, "github-hosted"))
    assert result.returncode == 1
    assert "CI_ALLOW_HOSTED_FALLBACK" in result.stdout, (
        f"{case}: the refusal must name the deliberate-override path"
    )
    accepted = _run_action(_env(CANONICAL, label, "1", "github-hosted"))
    assert accepted.returncode == 0, (
        f"{case}: the recovery the error advertises must actually clear it"
    )


def test_deliberate_hosted_runs_are_never_silent():
    """The accepted fallback must still announce itself.

    An implementation that exits 0 and prints nothing satisfies an exit-code-only check while
    making the deliberate hosted path silent -- this item's original defect, one level in.
    """
    for label in ("", "tautline"):
        result = _run_action(_env(CANONICAL, label, "1", "github-hosted"))
        assert result.returncode == 0
        assert "::warning" in result.stdout
