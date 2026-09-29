"""THE test that decides whether the agent-agnostic program worked.

A full plan -> build -> review -> finalize cycle driven by two fixture agents of DIFFERENT
declared vendors, run in both role assignments. Because the fixtures are vendor-agnostic by
construction -- `acme` and `globex` are invented, on invented runtimes -- this proves the
property for ANY pair of agents, not just the operator's.

The xfail marks were removed by R3.7 and by nothing else. They were `strict=True` on
purpose: a test that silently starts passing is a test nobody notices, and a skipped test is
indistinguishable from a test that does not exist.
"""
import json
import subprocess
from pathlib import Path

from _adapter_fixtures import EXAMPLE_ADAPTER, write_trusted_adapter as _write_trusted_adapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"

# R3.7 REMOVED THE `xfail(strict=True)` MARKS, and weakened no assertion doing it. Every test
# below now runs for real against the inverted gates. The marks were strict on purpose: an early
# pass would have failed the suite rather than sliding through unnoticed, so their removal here
# is evidence the gates actually inverted rather than that the tests stopped checking.

ACME = {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "ACME.md"}
GLOBEX = {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "GLOBEX.md"}


def _adapter(lane, *, builder, reviewer, planner=None, plan_reviewer=None):
    """Two invented agents, two role bindings, no vendor the framework has ever heard of.

    Overlaid on `example-saas`, never an ad-hoc dict: `plan-review-native` and `review-run` both
    resolve through `load_project()`, which requires the full adapter shape, so a six-key dict
    fails at adapter loading before these tests reach the role bindings they exist to prove.
    """
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data.update({
        "agents": {
            "acme-bot": {**ACME, "reviewWrapper": str(FIXTURES / "clean"),
                         "planReviewWrapper": str(FIXTURES / "clean")},
            "globex-bot": {**GLOBEX, "reviewWrapper": str(FIXTURES / "clean"),
                           "planReviewWrapper": str(FIXTURES / "clean")},
        },
        "roles": {
            "planner": planner or builder,
            "planReviewer": plan_reviewer or reviewer,
            "builder": builder,
            "implementationReviewer": reviewer,
        },
    })
    data["review"]["crossModel"] = {"enforcement": "block"}
    # A REAL preflight, deliberately trivial. `finalize-implementation-review` refuses without a
    # test-run record, and rightly: nothing else proves this tree's tests ever ran. Rather than
    # forge a record -- it carries a tree digest, so a forged one would be a lie the gate is
    # built to catch -- the lane gets a preflight that genuinely executes and genuinely passes.
    # The cycle below runs it, which is what makes this end-to-end rather than end-to-almost.
    # It must also emit a REPORT, not merely exit 0: the gate says "a green process is not a
    # count", which is the same principle as everything else in this program -- a control that
    # cannot say what it checked has not checked anything. So the lane's preflight writes a real
    # JUnit file and the record parses genuine counts out of it.
    # The board-currency gate reaches GitHub Projects and blocks when it cannot read the board.
    # That is right for a real lane and wrong for a hermetic one: the operator constraint behind
    # this whole release is that CI must not depend on anything external, and a test that needs
    # `gh auth login` violates it exactly as much as one needing a vendor CLI. The gate names its
    # own setting for deliberate offline work, so the lane uses it rather than skipping the gate.
    # `backlogAdapter` is a prose string in this adapter, not an object -- checked rather than
    # assumed after the first attempt assigned into it and got a TypeError.
    if isinstance(data.get("backlogProvider"), dict):
        data["backlogProvider"]["unavailablePolicy"] = "warn"
    report = ".ai-runs/test-runs/latest-junit.xml"
    data["testEvidence"] = {"report": {"format": "junit-xml", "path": report}}
    data["commands"]["fullPreflight"] = (
        "python3 -c \"import pathlib;"
        "p=pathlib.Path('" + report + "');"
        "p.parent.mkdir(parents=True,exist_ok=True);"

            "p.write_text('<testsuite name=\\'lane\\' tests=\\'1\\' "
            "failures=\\'0\\' errors=\\'0\\' skipped=\\'0\\'>"
        "<testcase classname=\\'lane\\' name=\\'acceptance_preflight\\'/></testsuite>')\""
    )
    # THE WORKFLOW RUNS THE COMMAND THE ADAPTER DECLARES. The ci-test-gate matches the workflow
    # against the adapter's own test-run command, so writing a workflow that runs something else
    # -- or that merely names a runner it does not invoke -- would satisfy the gate by pretending.
    # Deriving both from one string is what makes the gate's "tests run in CI" claim true here.
    workflow = lane / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "name: ci\n"
        "on: [pull_request, push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: test\n"
        "        run: " + data["commands"]["fullPreflight"] + "\n",
        encoding="utf-8",
    )
    return _write_trusted_adapter(lane, data)


def _manifests(lane):
    return sorted((lane / ".ai-runs" / "review-evidence").glob("*.json"))


# ---------------------------------------------------------------- R2: the contract half


def test_the_two_fixture_agents_declare_different_vendors(lane):
    """The property the gate will assert in R3. Asserted on the fixture data here so a later
    edit that quietly makes both agents the same vendor cannot hollow out the swap test."""
    path = _adapter(lane, builder="acme-bot", reviewer="globex-bot")
    data = json.loads(path.read_text())
    assert data["agents"]["acme-bot"]["vendor"] != data["agents"]["globex-bot"]["vendor"]


# ---------------------------------------------------------------- R3: the binding half


# The overlaid adapter is `example-saas`, whose `planningArtifacts.sourceOfTruth` is this
# directory. `run-plan-review` validates the plan against that root, so a plan written at the
# lane root fails source-of-truth validation before any gate inversion is exercised.
PLAN_ROOT = "docs/product/backlog/example-saas-v1/specs"


def _write_plan(lane):
    """A compliant plan, under the adapter's configured source-of-truth root.

    Returns the TARGET-RELATIVE reference, which is what `--plan` takes.
    """
    plan_dir = lane / PLAN_ROOT
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_dir / "agent-agnostic-acceptance.md"
    plan.write_text(
        "# Plan\n\n## Workstreams\nWS1 is parallel-safe; WS2 depends on WS1.\n\n"
        "### Task 1\nmodel-tier: standard\nUse best judgment; record non-obvious calls with "
        "`tautline decision-record`.\n",
        encoding="utf-8",
    )
    return f"{PLAN_ROOT}/agent-agnostic-acceptance.md"


def _full_cycle(run_cli, lane, path, *, expect_plan_reviewer, expect_impl_reviewer):
    """plan -> build -> review -> finalize, all four seams.

    Codex R2 P2: running only `review-run` + `guard-check` would leave `roles.planner` and
    `roles.planReviewer` unexercised, so a regression in which the plan-review path still
    invoked or validated one hardcoded vendor would pass the program's own acceptance test.
    The spec asks for a full cycle; this runs one.
    """
    plan_ref = _write_plan(lane)

    # --- plan seam
    # ARGUMENT CONTRACTS DIFFER BETWEEN THE TWO SEAMS, and it is not guessable. `codex-run`
    # refuses with "codex-run requires a command after --" when nothing follows `--`, so the
    # R2.5 tests must pass the wrapper explicitly. `run-plan-review` does NOT: it builds
    # `full_command = [*command_tokens, *review_args]`, deriving the command from the adapter's
    # recorded launcher and treating trailing args as extras. So no command is passed here, and
    # that asymmetry is deliberate rather than an omission. Verified against cli.py on the
    # merged tip, not assumed -- checking each seam's real signature is what the routed backlog
    # row `ready/2026-08-21-r26-xpass-guard` asks the executor of this task to do.
    # THE RECORDED LAUNCHER, not the native wrapper. `plan-review-native` (the rename of
    # `codex-plan-review`) is the thing `run-plan-review` invokes; it writes no evidence and
    # refuses a direct launch outside the launcher for exactly that reason. Driving it here
    # would assert a manifest that nothing wrote. `run-plan-review` is what records.
    plan_review = run_cli("run-plan-review", "--project", str(path), "--target", str(lane),
                          "--plan", plan_ref, cwd=lane)
    assert plan_review.returncode == 0, plan_review.stdout + plan_review.stderr
    # RECURSIVE, and rooted at the adapter's source-of-truth. Plan-review records land under
    # `<planningArtifacts.sourceOfTruth>/.plan-reviews/rounds/<slug>/`, not at the lane root --
    # the same derived-vs-hardcoded trap as the implementation ledger. A non-recursive glob at
    # the lane root finds nothing and reports "the seam recorded nothing" when the seam in fact
    # recorded correctly.
    plan_manifests = sorted(lane.glob("**/.plan-reviews/**/*.json"))
    assert plan_manifests, "the plan-review seam recorded nothing"
    assert json.loads(plan_manifests[-1].read_text())["reviewer"] == expect_plan_reviewer

    # `finalize-plan-review` requires --log, --verdict and both unresolved counts. Check
    # `tautline finalize-plan-review --help` before adapting: this is the current surface, and
    # omitting any of them fails in argparse rather than finalizing anything.
    plan_logs = sorted(lane.glob("**/plan-review/*.log"))
    assert plan_logs, "the recorded launcher wrote no reviewer log to bind"
    finalize_plan = run_cli(
        "finalize-plan-review", "--project", str(path), "--target", str(lane),
        "--plan", plan_ref, "--log", str(plan_logs[-1]),
        "--verdict", "clean", "--unresolved-critical-count", "0",
        "--unresolved-p1-count", "0", cwd=lane,
    )
    assert finalize_plan.returncode == 0, finalize_plan.stdout + finalize_plan.stderr

    # --- build/review seam
    result = run_cli("review-run", "--project", str(path), "--target", str(lane),
                     "--risk-tier", "T1", "--", str(FIXTURES / "clean"), cwd=lane)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest_path = _manifests(lane)[-1]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["reviewer"] == expect_impl_reviewer
    assert manifest["review_result_source"] == "structured"

    # --- preflight, because finalize requires evidence the tests ran
    preflight = run_cli("test-run", "--project", str(path), "--target", str(lane), cwd=lane)
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr

    # --- finalize seam
    finalize = run_cli("finalize-implementation-review", "--project", str(path),
                       "--target", str(lane), "--manifest", str(manifest_path),
                       "--verdict", "clean", "--unresolved-critical-count", "0",
                       "--unresolved-p1-count", "0", cwd=lane)
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr

    # `finalize-implementation-review` WRITES the ledger; it does not commit it. The prepush
    # evidence gate requires that ledger to be tracked AND clean (see
    # `implementation_review_ledger_errors`), so in a fresh lane the guard below fails at
    # evidence binding -- before the role swap it exists to prove is ever exercised. Commit it.
    #
    # This cannot move the diff the evidence is bound to: `review_scope_changed_files` scopes
    # the reviewed diff with `:(exclude)**/.impl-reviews/*.json`, so a ledger-only commit is
    # invisible to it. That exclusion is what makes committing here legal rather than a
    # gate-vs-gate deadlock -- the same deadlock migration 0.38.2 records.
    #
    # Globbed, not hardcoded: the ledger lives under `planning_source_root(data, target)`,
    # which this adapter overlay moves to the example-saas source-of-truth root, not
    # `docs/superpowers/plans/`. A hardcoded path would silently stage nothing and the guard
    # would fail with the ledger untracked anyway.
    ledgers = sorted(lane.glob("**/.impl-reviews/*.json"))
    assert ledgers, "finalize-implementation-review wrote no ledger to commit"
    subprocess.run(["git", "add", *[str(x) for x in ledgers]], cwd=lane,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "review: bind implementation review evidence"],
                   cwd=lane, check=True, capture_output=True)

    # PREFLIGHT AGAIN, after the ledger commit. The test-run record pins a tree digest, and
    # committing the ledger changed the tree -- so the earlier record is genuinely stale by the
    # time the push gate reads it. Re-running is the honest fix: the gate wants evidence that
    # THIS tree's tests passed, and after the commit that is a different tree.
    repreflight = run_cli("test-run", "--project", str(path), "--target", str(lane), cwd=lane)
    assert repreflight.returncode == 0, repreflight.stdout + repreflight.stderr

    guard = run_cli("guard-check", "--project", str(path), "--target", str(lane),
                    "--boundary", "prepush", cwd=lane)
    assert guard.returncode == 0, guard.stdout + guard.stderr
