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


def test_triggers_on_events_inline_and_nested(cli):
    assert cli.workflow_triggers_on_events("on: [push, pull_request]", ["pull_request", "push"]) == {"pull_request", "push"}
    nested = "on:\n  push:\n    branches: [main]\njobs:\n  x:\n"
    assert cli.workflow_triggers_on_events(nested, ["push", "pull_request"]) == {"push"}
    # a workflow_dispatch-only workflow does not trigger on PR/push
    assert cli.workflow_triggers_on_events("on:\n  workflow_dispatch:\n", ["push", "pull_request"]) == set()


def test_triggers_ignores_nested_and_indented_on(cli):
    # Codex P2: only a TOP-LEVEL `on:` counts -- a jobs.<id>.on or an indented `on:` inside a block
    # scalar must not be read as the workflow trigger.
    nested_job = "name: x\njobs:\n  build:\n    on: [pull_request]\n    steps: []\n"
    assert cli.workflow_triggers_on_events(nested_job, ["pull_request"]) == set()


def test_triggers_ignores_nested_config_event_names(cli):
    # Codex P1 (pass 2): an event name appearing as NESTED config (e.g. a workflow_dispatch input
    # default of pull_request) is not a trigger and must not match.
    manual = (
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      event:\n"
        "        default: pull_request\n"
    )
    assert cli.workflow_triggers_on_events(manual, ["push", "pull_request"]) == set()
    # but real first-level keys do count
    nested_real = "on:\n  push:\n  pull_request:\n    branches: [main]\n"
    assert cli.workflow_triggers_on_events(nested_real, ["push", "pull_request"]) == {"push", "pull_request"}
    # inline scalar + trailing comment
    assert cli.workflow_triggers_on_events("on: push  # only push\n", ["push", "pull_request"]) == {"push"}


def test_triggers_all_yaml_forms(cli):
    # Codex pass 3: flow mapping (top keys only), anchor, and block-list forms.
    ev = ["push", "pull_request"]
    # flow mapping: top-level keys match; nested config does NOT
    assert cli.workflow_triggers_on_events("on: {push: null, pull_request: {branches: [main]}}\n", ev) == {"push", "pull_request"}
    assert cli.workflow_triggers_on_events("on: {workflow_dispatch: {inputs: {event: {default: pull_request}}}}\n", ev) == set()
    # anchored block mapping
    assert cli.workflow_triggers_on_events("on: &events\n  push:\n  pull_request:\n", ev) == {"push", "pull_request"}
    # block list form
    assert cli.workflow_triggers_on_events("on:\n  - push\n  - pull_request\n", ev) == {"push", "pull_request"}


def test_triggers_pass4_hardening(cli):
    ev = ["push", "pull_request"]
    # Codex P1: `true:` / case-variant keys are NOT the trigger key
    assert cli.workflow_triggers_on_events("true:\n  pull_request:\n", ev) == set()
    assert cli.workflow_triggers_on_events("ON: [pull_request]\n", ev) == set()
    # Codex P1: quoted value inside a flow mapping must not leak an event name
    assert cli.workflow_triggers_on_events('on: {workflow_dispatch: "pull_request: not a trigger"}\n', ev) == set()
    # quoted scalar / quoted block key ARE recognized (real, just quoted)
    assert cli.workflow_triggers_on_events('on: "push"\n', ev) == {"push"}
    assert cli.workflow_triggers_on_events('"on":\n  "pull_request":\n', ev) == {"pull_request"}
    # Codex P1 (pass 5): a quoted scalar mis-written as a compact list is ONE event name, not two
    assert cli.workflow_triggers_on_events('on: ["push, pull_request"]\n', ev) == set()
    # genuine flow list still splits
    assert cli.workflow_triggers_on_events('on: [push, pull_request]\n', ev) == {"push", "pull_request"}


def test_runs_tests_marker_detection(cli):
    markers = cli.CI_TEST_RUNNER_MARKERS
    assert cli.workflow_runs_tests(TEST_WORKFLOW, markers)
    assert not cli.workflow_runs_tests(DEPLOY_ONLY, markers)
    # adapter's own preflight command counts as a marker
    assert cli.workflow_runs_tests("steps:\n  - run: scripts/my-preflight.sh\n", ["scripts/my-preflight.sh"])


def test_runs_tests_monorepo_commands(cli):
    # RCA follow-up: real monorepo/turbo test commands must be recognized (false-negatived before).
    markers = cli.CI_TEST_RUNNER_MARKERS
    for step in [
        "- run: pnpm exec turbo test:unit --concurrency=1",
        "- run: pnpm exec turbo test:e2e",
        "- run: nx test my-app",
        "- run: pnpm run test:ci",
    ]:
        assert cli.workflow_runs_tests(step, markers), step
    # an install/build step still does not count
    assert not cli.workflow_runs_tests("- run: pnpm install --frozen-lockfile\n", markers)
    assert not cli.workflow_runs_tests("- run: pnpm build\n", markers)
    # Codex: broad nx run/affected non-test targets must NOT count as running tests
    for non_test in ["- run: nx run web:build\n", "- run: nx affected -t build\n", "- run: nx run api:lint\n"]:
        assert not cli.workflow_runs_tests(non_test, markers), non_test
    # Codex: `npx playwright install` (setup) must NOT count; a real run is `playwright test`
    assert not cli.workflow_runs_tests("- run: npx playwright install --with-deps\n", markers)
    assert cli.workflow_runs_tests("- run: npx playwright test\n", markers)


def _data(*, full_preflight="scripts/preflight.sh", enforcement="warn"):
    return {"commands": {"fullPreflight": full_preflight}, "ciTestGate": {"enforcement": enforcement}}


def test_repo_has_tests_signals(cli, tmp_path):
    assert cli.repo_has_tests(_data(), tmp_path)[0]  # adapter declares a test command
    no_cmd = {"commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"}}
    assert not cli.repo_has_tests(no_cmd, tmp_path)[0]
    (tmp_path / "tests").mkdir()
    assert cli.repo_has_tests(no_cmd, tmp_path)[0]  # test dir present


def _workflows(tmp_path, name=None, content=None):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    if name:
        (wf / name).write_text(content)
    return tmp_path


def test_no_workflows_with_tests_is_drift(cli, tmp_path):
    issues = cli.ci_test_gate_issues(_data(), tmp_path)
    assert issues and "no CI test gate" in issues[0]


def test_deploy_only_workflow_is_drift(cli, tmp_path):
    _workflows(tmp_path, "deploy.yml", DEPLOY_ONLY)
    issues = cli.ci_test_gate_issues(_data(), tmp_path)
    assert issues and "not executed in CI" in issues[0]


def test_test_workflow_is_clean(cli, tmp_path):
    _workflows(tmp_path, "ci.yml", TEST_WORKFLOW)
    assert cli.ci_test_gate_issues(_data(), tmp_path) == []


def test_no_tests_is_noop(cli, tmp_path):
    # A genuinely test-less repo is not blocked.
    no_cmd = {"commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"}, "ciTestGate": {}}
    _workflows(tmp_path, "deploy.yml", DEPLOY_ONLY)
    assert cli.ci_test_gate_issues(no_cmd, tmp_path) == []


def test_disabled_gate_is_noop(cli, tmp_path):
    data = {"commands": {"fullPreflight": "scripts/preflight.sh"}, "ciTestGate": {"enabled": False}}
    assert cli.ci_test_gate_issues(data, tmp_path) == []


def test_required_workflow_missing_is_drift(cli, tmp_path):
    data = {"commands": {"fullPreflight": "pytest"}, "ciTestGate": {"requiredWorkflow": "test.yml"}}
    _workflows(tmp_path, "ci.yml", TEST_WORKFLOW)  # a test gate exists, but not the required name
    issues = cli.ci_test_gate_issues(data, tmp_path)
    assert issues and "required CI workflow" in issues[0]


PUSH_ONLY_TEST = "name: ci\non:\n  push:\njobs:\n  test:\n    steps:\n      - run: pytest -q\n"
INSTALL_ONLY = "name: ci\non: [push, pull_request]\njobs:\n  setup:\n    steps:\n      - run: cd saas && pnpm install\n"


def test_push_only_leaves_pull_request_uncovered(cli, tmp_path):
    # Codex P1: tests on push only must NOT satisfy the default events (PRs would ship ungated).
    _workflows(tmp_path, "ci.yml", PUSH_ONLY_TEST)
    issues = cli.ci_test_gate_issues(_data(), tmp_path)
    assert issues and "pull_request" in issues[0]


def test_setup_only_workflow_is_drift(cli, tmp_path):
    # Codex P1: testEnvironment-style install/setup must not count as running the test suite.
    data = {"commands": {"fullPreflight": "pytest", "testEnvironment": "cd saas && pnpm install"}, "ciTestGate": {}}
    _workflows(tmp_path, "ci.yml", INSTALL_ONLY)
    issues = cli.ci_test_gate_issues(data, tmp_path)
    assert issues, "an install-only workflow must not satisfy the test gate"


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


def test_repo_has_tests_reports_conclusiveness(cli, tmp_path):
    # repo_has_tests now returns (has_tests, conclusive, reason).
    has, conclusive, _why = cli.repo_has_tests(_data(), tmp_path)
    assert has and conclusive  # adapter declares a test command -> conclusive
    no_cmd = {"commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"}}
    has, conclusive, _why = cli.repo_has_tests(no_cmd, tmp_path)
    assert not has and conclusive  # empty tree fully scanned -> conclusively test-less


def _product(*, enforcement="warn", expect=None):
    gate = {"enforcement": enforcement}
    if expect is not None:
        gate["expectTests"] = expect
    return {
        "deploymentTargets": [{"target": "prod", "healthCheck": "x"}],
        "commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"},
        "ciTestGate": gate,
    }


def test_product_without_tests_blocks_instead_of_selfdisabling(cli, tmp_path):
    # A customer-facing adapter with no detectable tests must NOT be treated as legitimately test-less.
    _workflows(tmp_path, "deploy.yml", DEPLOY_ONLY)
    issues = cli.ci_test_gate_issues(_product(), tmp_path)
    assert issues and "expectTests" in issues[0]


def test_product_expectTests_false_asserts_testless(cli, tmp_path):
    # An explicit, audited assertion that the product is deliberately test-less suppresses the block.
    _workflows(tmp_path, "deploy.yml", DEPLOY_ONLY)
    assert cli.ci_test_gate_issues(_product(expect=False), tmp_path) == []


def test_non_product_without_tests_stays_noop(cli, tmp_path):
    # Backward-compat: a repo with no deployment surface and no tests is still not blocked.
    no_cmd = {"commands": {"fullPreflight": "BOOTSTRAP REQUIRED: set me"}, "ciTestGate": {}}
    assert cli.ci_test_gate_issues(no_cmd, tmp_path) == []


def test_expectTests_must_be_boolean(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_ci_test_gate({"ciTestGate": {"expectTests": "yes"}})
    assert cli.normalize_ci_test_gate({"ciTestGate": {"expectTests": False}})["expectTests"] is False
