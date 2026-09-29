"""RCA: a repo can define tests yet run them nowhere in CI, so regressions ship silently behind
green local/agent-invoked gates. The CI-test-gate health check fails closed when the repo has
tests but no CI workflow runs them on PR/push.
"""

DEPLOY_ONLY = """
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/deploy.sh
"""

TEST_WORKFLOW = """
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""


def _data(*, full_preflight="scripts/preflight.sh", enforcement="warn"):
    return {"commands": {"fullPreflight": full_preflight}, "ciTestGate": {"enforcement": enforcement}}


def _workflows(tmp_path, name=None, content=None):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    if name:
        (wf / name).write_text(content)
    return tmp_path


PUSH_ONLY_TEST = "name: ci\non:\n  push:\njobs:\n  test:\n    steps:\n      - run: pytest -q\n"
INSTALL_ONLY = "name: ci\non: [push, pull_request]\njobs:\n  setup:\n    steps:\n      - run: cd saas && pnpm install\n"


def test_invalid_ci_test_gate_config_rejected(cli):
    # Codex P3: malformed ciTestGate must be rejected, not coerced into bogus values.
    import pytest
    for bad_gate in ["bad", {"enforcement": "nope"}, {"events": [1]}, {"events": []}, {"requiredWorkflow": ["x"]}, {"testCommandMarkers": [2]}, {"enabled": "yes"}]:
        with pytest.raises(SystemExit):
            cli.normalize_ci_test_gate({"ciTestGate": bad_gate})


def test_valid_ci_test_gate_config_accepted(cli):
    cfg = cli.normalize_ci_test_gate({"ciTestGate": {"enforcement": "block", "events": ["pull_request"]}})
    assert cfg["enforcement"] == "block" and cfg["events"] == ["pull_request"]
    assert cli.normalize_ci_test_gate({})["enforcement"] == "warn"  # default


# --- #6: close the has-tests fail-open ----------------------------------------------------------
# RCA (quality rec #6): repo_has_tests returned False both when it CONCLUSIVELY found no tests and
# when the scan was INCONCLUSIVE (hit its cap), and ci_test_gate_issues treated "no tests detected"
# as a legitimately test-less repo -> the FM2 fail-open that let Private Product A's never-executed suite ship.
# A customer-facing adapter (deploymentTargets) can no longer silently self-disable the gate; it must
# either have tests or assert ciTestGate.expectTests=false explicitly.


def _product(*, enforcement="warn", expect=None):
    gate = {"enforcement": enforcement}
    if expect is not None:
        gate["expectTests"] = expect
    return {
        "deploymentTargets": [{"target": "prod", "healthCheck": "x"}],
        "commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"},
        "ciTestGate": gate,
    }


def test_expectTests_must_be_boolean(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_ci_test_gate({"ciTestGate": {"expectTests": "yes"}})
    assert cli.normalize_ci_test_gate({"ciTestGate": {"expectTests": False}})["expectTests"] is False
