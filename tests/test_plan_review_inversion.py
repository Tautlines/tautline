import json
import re
from pathlib import Path
from _adapter_fixtures import EXAMPLE_ADAPTER, write_trusted_adapter as _write_trusted_adapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"


# `example-saas`'s planningArtifacts.sourceOfTruth. `run-plan-review` validates the plan against
# this root, so a plan at the lane root is refused before the reviewer binding is ever reached.
PLAN_ROOT = "docs/product/backlog/example-saas-v1/specs"


def _write_plan(lane):
    """A plan under the adapter's configured source-of-truth root; returns the `--plan` ref."""
    plan_dir = lane / PLAN_ROOT
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "seam.md").write_text(
        "# Plan\n\n## Workstreams\nparallel-safe\n\nmodel-tier: standard\n"
        "Use best judgment; record with `tautline decision-record`.\n", encoding="utf-8")
    return f"{PLAN_ROOT}/seam.md"


def _adapter(lane, planner, plan_reviewer, builder=None, impl_reviewer=None,
             plan_wrapper=None):
    """Overlay on `example-saas`. `plan-review-native` resolves through `load_project()` and
    schema validation, so a partial dict fails before reaching the plan-review inversion."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data.update({
        "agents": {
            "acme-bot": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md",
                         "planReviewWrapper": str(FIXTURES / "clean"),
                         "reviewWrapper": str(FIXTURES / "clean")},
            "globex-bot": {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "G.md",
                           "planReviewWrapper": str(FIXTURES / (plan_wrapper or "clean")),
                           "reviewWrapper": str(FIXTURES / "clean")},
        },
        "roles": {
            "planner": planner, "planReviewer": plan_reviewer,
            "builder": builder or planner, "implementationReviewer": impl_reviewer or plan_reviewer,
        },
    })
    return _write_trusted_adapter(lane, data)


def test_no_hardcoded_codex_binary_invocation_remains():
    from _ast_inventory import source_files

    offenders = []
    for p in source_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        # The ONE sanctioned exception, and it is named rather than inline: the builtin native
        # wrapper's own default, which an adapter overrides by setting `planReviewWrapper`. The
        # guard's point was never "the string `codex` may not appear" -- it was that no SEAM may
        # invoke a vendor binary it was not configured to invoke. A named constant with one
        # reader is reviewable; an inline literal at a call site is the coupling.
        if "BUILTIN_NATIVE_PLAN_REVIEW_COMMAND" in text:
            continue
        if '["codex", "review"]' in text or "['codex', 'review']" in text:
            offenders.append(str(p))
    assert offenders == [], (
        "a hardcoded vendor binary invocation survived; the plan reviewer's command comes from "
        "its agent record's planReviewWrapper: " + ", ".join(offenders)
    )


def _log_ref(stdout, lane):
    """The `--log` path `run-plan-review` printed for its own round.

    Read from the printed next-action rather than globbed off disk: the point of the printed
    remedy is that following it verbatim works, so a test that reconstructs the path by other
    means would stay green while the instruction the operator actually follows is broken.
    """
    match = re.search(r"--log (\S+)", stdout)
    assert match, stdout
    return match.group(1)


def test_binding_the_builtin_itself_still_runs_the_builtin(run_cli, lane):
    """The documented configuration must be untouched by the refusal above.

    `planReviewWrapper: "tautline plan-review-native"` is how an adapter says "use the builtin",
    so the role naming this command is not a custom wrapper to proxy -- there is nothing to
    delegate to, and the builtin runs. A refusal here would break the configuration the framework
    recommends.
    """
    plan_ref = _write_plan(lane)
    path = _adapter(lane, planner="acme-bot", plan_reviewer="globex-bot")
    data = json.loads(path.read_text())
    data["agents"]["globex-bot"]["planReviewWrapper"] = "tautline plan-review-native"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_cli("plan-review-native", "--project", str(path), "--target", str(lane),
                     "--plan", plan_ref, "--standalone", cwd=lane)
    combined = result.stdout + result.stderr
    # It reaches the builtin launch rather than the proxy refusal. Whether the builtin binary
    # exists on this machine is not this test's subject -- the refusal it must NOT hit is.
    assert "this lane binds `roles.planReviewer` to a custom" not in combined, combined
