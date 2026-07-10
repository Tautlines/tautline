"""Quality rec #10: day-one self-proving test-harness scaffold + ci-test-gate block-by-default.

project_scaffold emitted an adapter but zero test infra, so a greenfield app's first commit had no
runner, no CI, and no proof any gate bites -- exactly the Private Product A window. Now a NEW project ships a
runner + a real CI workflow (no continue-on-error) + a passing smoke + a written "prove the gate can go
red" procedure, and the scaffolded adapter blocks on the ci-test-gate from commit one. The runtime
DEFAULT stays warn (warn-then-block migration) so no existing rendered adapter is silently wedged -- the
0.6.115 lesson -- which the all-adapters-load guard below enforces.
"""

from pathlib import Path


# --- the scaffolded harness files ----------------------------------------------------------------

def test_harness_emits_runner_ci_smoke_and_proof(cli):
    files = cli.scaffold_test_harness_files("acme")
    assert set(files) == {
        ".github/workflows/ci.yml",
        "scripts/test.sh",
        "tests/smoke_test.sh",
        "docs/quality/gate-self-proof.md",
    }


def test_ci_workflow_is_blocking_and_runs_tests(cli):
    ci = cli.scaffold_test_harness_files("acme")[".github/workflows/ci.yml"]
    assert "continue-on-error: true" not in ci  # the FM1/FM3 anti-pattern must not be scaffolded
    assert "pull_request" in ci and "push" in ci
    assert "scripts/test.sh" in ci  # a recognized CI test-runner marker


def test_self_proof_doc_requires_a_red_run(cli):
    proof = cli.scaffold_test_harness_files("acme")["docs/quality/gate-self-proof.md"]
    assert "failure" in proof.lower() and "conclusion" in proof.lower()


def test_runner_fails_closed(cli):
    runner = cli.scaffold_test_harness_files("acme")["scripts/test.sh"]
    assert "set -euo pipefail" in runner


# --- ci-test-gate block-by-default for NEW projects ----------------------------------------------

def test_scaffold_adapter_blocks_on_ci_test_gate(cli):
    adapter = cli.project_scaffold("Acme App", "acme/app", "../methodology/adapter-schema.json")
    assert adapter["ciTestGate"]["enforcement"] == "block"
    assert cli.normalize_ci_test_gate(adapter)["enforcement"] == "block"


def test_scaffold_adapter_omits_unset_work_profile_pre_push_base(cli):
    adapter = cli.project_scaffold("Acme App", "acme/app", "../methodology/adapter-schema.json")
    assert "prePushBase" not in adapter["workProfiles"]


# --- warn-then-block migration: existing adapters are NOT wedged ---------------------------------

def test_all_bundled_adapters_still_load(cli):
    root = Path(cli.REPO_ROOT) / "adapters" / "projects"
    adapters = sorted(p for p in root.glob("*.json") if not p.name.startswith("."))
    assert adapters, "expected bundled adapters to exist"
    for path in adapters:
        data = cli.load_project(path)  # must not SystemExit (the 0.6.115 guard)
        assert data["ciTestGate"]["enforcement"] in {"warn", "block"}


def test_runtime_default_stays_warn(cli):
    # The global default is intentionally NOT flipped (flipping would wedge already-rendered external
    # adapters that omit ciTestGate). New projects opt into block via project_scaffold instead.
    assert cli.DEFAULT_CI_TEST_GATE["enforcement"] == "warn"
