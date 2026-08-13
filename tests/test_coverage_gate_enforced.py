"""The framework must not ship the FM1/FM3 anti-pattern it enforces on its products.

Quality recommendation #7 Part 1 (operator quality mandate, 2026-06-24): until now
.github/workflows/ci-python.yml ran the coverage step with `continue-on-error: true` and
.coveragerc declared no `fail_under` threshold -- so test coverage of the 1.2MB enforcement
engine could regress to zero and CI stayed green. That is exactly the "tests run but failure
does not gate" failure mode (FM3) the methodology blocks in customer products, dogfooded in
the canonical repo. These guards keep the coverage gate BLOCKING with a ratchet floor.

The floor is a RATCHET: raise MIN_FAIL_UNDER (and the .coveragerc fail_under) as coverage
improves; never lower it to make a regression pass. The whole-repo floor is a coarse
backstop -- per-change exercise of NEW lines is recommendation #7 Part 2 (diff-coverage).
"""

import configparser
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COVERAGERC = REPO_ROOT / ".coveragerc"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python.yml"
# The blocking ratchet lives in the DAILY full-matrix workflow. Coverage answers "has whole-repo
# coverage regressed" -- a question whose answer cannot meaningfully change between two pushes an
# hour apart, and measuring it cost ~40% more wall clock on every one of them. Moving WHERE it
# runs is allowed; letting it stop blocking is not, which is what these guards enforce.
COVERAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python-full.yml"

# Current measured baseline is ~25.13%. The ratchet floor sits just below it so a real
# regression fails the job while normal cross-version (3.10/3.12) variance does not.
MIN_FAIL_UNDER = 24


def test_coveragerc_declares_a_fail_under_floor():
    cfg = configparser.ConfigParser()
    cfg.read(COVERAGERC)
    assert cfg.has_option("report", "fail_under"), (
        ".coveragerc [report] must declare fail_under so the coverage gate can FAIL on a "
        "regression (without it, `pytest --cov` exits 0 no matter how low coverage drops)."
    )
    value = cfg.getfloat("report", "fail_under")
    assert value >= MIN_FAIL_UNDER, (
        f".coveragerc fail_under={value} is below the ratchet floor {MIN_FAIL_UNDER}. "
        "Raise the floor as coverage improves; never lower it to pass a regression."
    )


def test_ci_coverage_step_is_blocking():
    text = COVERAGE_WORKFLOW.read_text()
    assert "--cov" in text, (
        f"{COVERAGE_WORKFLOW.name} must still run a coverage step. The ratchet may move between "
        "workflows; it may not evaporate."
    )
    assert "--cov-config=.coveragerc" in text, (
        "the coverage step must read .coveragerc, or fail_under is never applied and the gate "
        "passes at any coverage level."
    )
    assert "continue-on-error: true" not in text, (
        f"{COVERAGE_WORKFLOW.name} must not run the coverage step with continue-on-error: true -- "
        "that defangs the coverage gate (the FM1/FM3 anti-pattern). Remove it so a coverage "
        "regression fails the job."
    )


def test_the_coverage_ratchet_actually_fires():
    """A ratchet moved off the per-push path has to run SOMEWHERE, automatically.

    Without this, "we moved coverage off the PR path" and "we deleted the coverage gate" look
    identical from the repo -- the FM3 anti-pattern with extra steps.

    A schedule alone does NOT satisfy this. GitHub runs `schedule` only from the repository's
    default branch, so a workflow declared on a non-default integration branch and triggered only
    by cron never runs at all -- a gate that is dark while reading as configured.
    """
    document = yaml.safe_load(COVERAGE_WORKFLOW.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), f"{COVERAGE_WORKFLOW.name} has no mapping `on:` block"
    pushes = (triggers.get("push") or {}).get("branches") or []
    assert pushes, (
        f"{COVERAGE_WORKFLOW.name} carries the blocking coverage ratchet, so it must fire on "
        "pushes to a real branch; a cron-only workflow on a non-default branch never runs."
    )
