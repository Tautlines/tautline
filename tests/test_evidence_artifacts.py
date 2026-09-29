"""Pins for the CommandCenter evidence convention (artifact name `evidence`)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EMITTER = ROOT / ".github" / "scripts" / "emit_evidence.py"


def _emit(tmp_path, *args):
    out = tmp_path / "evidence" / "evidence.json"
    result = subprocess.run(
        [sys.executable, str(EMITTER), "--out", str(out), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result, out


def test_emit_evidence_writes_a_schema_v1_document(tmp_path):
    result, out = _emit(
        tmp_path,
        "--suite", "validate:eval",
        "--result", "validate.methodology-suite=success",
        "--result", "validate.compile-cli=failure",
        "--result", "validate.whitespace=skipped",
    )
    assert result.returncode == 0, result.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "tautline-evidence/v1"
    assert len(doc["suites"]) == 1
    suite = doc["suites"][0]
    assert suite["name"] == "validate"
    assert suite["kind"] == "eval"
    assert [r["status"] for r in suite["results"]] == ["pass", "fail", "skip"]
    assert all(set(r) == {"id", "status"} for r in suite["results"])


def test_emit_evidence_creates_the_output_directory(tmp_path):
    _, out = _emit(tmp_path, "--suite", "validate:eval",
                   "--result", "validate.compile-cli=success")
    assert out.exists()


def test_emit_evidence_rejects_an_unknown_step_outcome(tmp_path):
    result, _ = _emit(tmp_path, "--suite", "validate:eval",
                      "--result", "validate.compile-cli=exploded")
    assert result.returncode != 0
    assert "unknown step outcome" in result.stderr


def test_emit_evidence_rejects_an_unknown_suite_kind(tmp_path):
    result, _ = _emit(tmp_path, "--suite", "validate:vibes",
                      "--result", "validate.compile-cli=success")
    assert result.returncode != 0


def test_emit_evidence_rejects_a_result_whose_prefix_names_no_suite(tmp_path):
    # A typoed prefix must fail loudly, not land schema-shaped but wrong evidence
    # in whichever suite happened to be declared last.
    result, _ = _emit(
        tmp_path,
        "--suite", "validate:eval",
        "--suite", "smoke:smoke",
        "--result", "validte.compile-cli=success",
    )
    assert result.returncode != 0
    assert "no matching --suite prefix" in result.stderr


def test_emit_evidence_routes_results_to_their_named_suite(tmp_path):
    _, out = _emit(
        tmp_path,
        "--suite", "validate:eval",
        "--suite", "smoke:smoke",
        "--result", "validate.compile-cli=success",
        "--result", "smoke.cli-validate-adapter=success",
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in doc["suites"]}
    assert [r["id"] for r in by_name["validate"]["results"]] == ["validate.compile-cli"]
    assert [r["id"] for r in by_name["smoke"]["results"]] == ["smoke.cli-validate-adapter"]
    assert by_name["smoke"]["kind"] == "smoke"


def test_emit_evidence_maps_a_cancelled_leg_to_skip(tmp_path):
    _, out = _emit(tmp_path, "--suite", "python-matrix:probe",
                   "--result", "python-matrix.py-3.10=cancelled")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["suites"][0]["results"][0]["status"] == "skip"


def test_emit_evidence_routes_a_dotted_suite_name(tmp_path):
    # Splitting the id at the first dot would look up `api`, not the declared `api.contract`.
    _, out = _emit(
        tmp_path,
        "--suite", "api.contract:test",
        "--result", "api.contract.case=success",
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["suites"][0]["name"] == "api.contract"
    assert doc["suites"][0]["results"][0]["id"] == "api.contract.case"


def test_emit_evidence_prefers_the_longest_matching_suite_prefix(tmp_path):
    _, out = _emit(
        tmp_path,
        "--suite", "a:test",
        "--suite", "a.b:test",
        "--result", "a.b.case=success",
    )
    doc = json.loads(out.read_text(encoding="utf-8"))
    by_name = {s["name"]: [r["id"] for r in s["results"]] for s in doc["suites"]}
    assert by_name["a.b"] == ["a.b.case"]
    assert by_name["a"] == []


def test_emit_evidence_rejects_a_result_id_with_no_suffix(tmp_path):
    # A bare id equal to a suite name (no `.<result>` suffix) is malformed, not suite-level.
    result, _ = _emit(tmp_path, "--suite", "validate:eval",
                      "--result", "validate=success")
    assert result.returncode != 0
    assert "no matching --suite prefix" in result.stderr


CI_PYTHON = ROOT / ".github" / "workflows" / "ci-python.yml"
CI_PYTHON_FULL = ROOT / ".github" / "workflows" / "ci-python-full.yml"
RENDERER_CI = ROOT / ".github" / "workflows" / "renderer-ci.yml"
VALIDATE = ROOT / ".github" / "workflows" / "validate.yml"
NPM_AUDIT = ROOT / ".github" / "workflows" / "npm-audit.yml"

SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def _jobs(workflow: Path) -> dict:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]


def _triggers(workflow: Path) -> dict:
    """The workflow's `on:` block. YAML 1.1 parses a bare `on` key as the boolean True, so read
    both spellings rather than depending on which loader quirk is in play."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    block = document.get("on", document.get(True))
    assert isinstance(block, dict), f"{workflow.name} has no mapping `on:` block"
    return block


def _steps(workflow: Path, job: str) -> list[dict]:
    return _jobs(workflow)[job]["steps"]


def _upload_steps(workflow: Path, job: str) -> list[dict]:
    return [s for s in _steps(workflow, job) if "upload-artifact" in str(s.get("uses", ""))]


def _named_upload(workflow: Path, job: str, name: str) -> dict:
    return next(
        s for s in _upload_steps(workflow, job) if s["with"]["name"] == name
    )


def test_ci_python_publishes_exactly_one_artifact_named_evidence():
    # Leg artifacts are intermediates with distinct names; CommandCenter reads `evidence`.
    names = [
        s["with"]["name"]
        for job in _jobs(CI_PYTHON)
        for s in _upload_steps(CI_PYTHON, job)
    ]
    assert names.count("evidence") == 1, "a second `evidence` upload collides (v4 names immutable)"
    upload = _named_upload(CI_PYTHON, "evidence", "evidence")
    assert upload["with"]["path"] == "evidence/"


def test_ci_python_legs_always_upload_their_own_outcome():
    steps = _steps(CI_PYTHON, "python")
    record = next(s for s in steps if s.get("name") == "Record this leg's outcome")
    assert record["if"] == "always()"
    assert "job.status" in record["run"]
    assert "leg-status.txt" in record["run"]

    leg_upload = next(
        s for s in _upload_steps(CI_PYTHON, "python")
        if "${{ matrix.python-version }}" in s["with"]["name"]
    )
    assert leg_upload["if"] == "always()", "a red leg's evidence is the evidence that matters"


def test_ci_python_evidence_job_reports_every_matrix_leg():
    """The core anti-lie property: a failing leg must NOT publish all-green evidence.

    Derived from the matrix rather than hardcoded. It used to list ("3.10", "3.12") literally, so
    trimming per-PR CI to one leg would have failed a workflow that still satisfies the contract,
    while ADDING a leg nobody composed would have passed. Reading the matrix catches both.
    """
    job = _jobs(CI_PYTHON)["evidence"]
    # `needs` must include python; the evidence job runs after the matrix legs.
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "python" in needs
    assert "cancelled()" in job["if"]
    compose = next(s for s in job["steps"] if s.get("name") == "Compose the run's evidence")
    assert "--suite ci-python:probe" in compose["run"]
    legs = _jobs(CI_PYTHON)["python"]["strategy"]["matrix"]["python-version"]
    assert legs, "the python job must declare at least one interpreter"
    for leg in legs:
        assert f"legs/py-{leg}/leg-status.txt" in compose["run"]
        assert f"ci-python.py-{leg}=" in compose["run"]


def _declared_floor() -> str:
    """The floor as pyproject declares it, e.g. `py312` -> `3.12`.

    Read rather than hardcoded: a guard that pins a literal version keeps asserting the OLD floor
    after a raise, which is how a matrix ends up proving an interpreter nobody supports.
    """
    import re

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'target-version\s*=\s*"py(\d)(\d+)"', text)
    assert match, "pyproject must declare a ruff target-version; the floor is derived from it"
    return f"{match.group(1)}.{match.group(2)}"


def test_ci_python_runs_one_leg_per_pr_and_the_daily_workflow_covers_the_rest():
    """Per-PR CI is trimmed to one interpreter; the declared floor is not abandoned, it moves.

    The pairing is the contract. Dropping a leg from per-PR CI without the daily workflow picking
    it up is exactly the silent coverage loss this trim is not allowed to be.
    """
    per_pr = _jobs(CI_PYTHON)["python"]["strategy"]["matrix"]["python-version"]
    assert per_pr == ["3.12"], "per-PR CI runs exactly one modern interpreter"

    daily = _jobs(CI_PYTHON_FULL)["python"]["strategy"]["matrix"]["python-version"]
    assert set(daily) >= set(per_pr), (
        "the daily matrix must cover every interpreter per-PR CI dropped"
    )

    # Derived from the declared floor rather than hardcoded, so raising the floor cannot leave this
    # guard asserting a version nothing runs. The floor moved 3.10 -> 3.12 on 2026-07-31: nothing
    # in the tree ever required 3.10 (it rested on zip(strict=), present in 3.10+), so keeping the
    # leg meant hand-building a second interpreter into the runner image to prove a version no
    # adopter was asked to stay on.
    floor = _declared_floor()
    assert floor in set(daily), (
        f"the daily matrix must prove the declared floor ({floor}); if the floor moves, this "
        "follows it automatically rather than pinning a stale version"
    )


def test_daily_evidence_job_reports_the_fresh_install_gate():
    """A red fresh-install-smoke must NOT publish all-green evidence.

    Asserted against the DAILY workflow, which is where the packaging gate lives now. The property
    is unchanged; only its home moved.
    """
    job = _jobs(CI_PYTHON_FULL)["evidence"]
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "fresh-install-smoke" in needs, "evidence must wait for the fresh-install gate"
    compose = next(s for s in job["steps"] if s.get("name") == "Compose the run's evidence")
    assert (
        "ci-python-full.fresh-install-smoke=${{ needs.fresh-install-smoke.result }}"
        in compose["run"]
    )


def test_per_pr_ci_carries_no_coverage_instrumentation():
    """The ratchet moved to the daily matrix; per-PR CI must not quietly grow it back.

    Coverage answers "has whole-repo coverage regressed", which cannot meaningfully change between
    two pushes an hour apart, and instrumenting it cost ~40% more wall clock on every one.
    """
    steps = _steps(CI_PYTHON, "python")
    for step in steps:
        assert "--cov" not in str(step.get("run", ""))
        assert "--cov" not in str((step.get("env") or {}).get("PYTEST_ADDOPTS", ""))


def test_ci_python_emits_junit_on_failing_runs():
    """The contract is that a RED run still publishes its per-test JUnit detail to `evidence/`.

    Asserted as the property, not as one mechanism. It used to be pinned to a `--junitxml` flag on
    a second full-suite coverage pass; when that pass was folded into the single run, the pin
    would have failed on a workflow that still satisfies the contract -- and worse, the FIRST
    pass's `PYTEST_ADDOPTS: --junitxml=evidence/...` had never worked at all, because
    scripts/test.sh appends its own `--junitxml` last and pytest takes the last value. Pin the
    publish step and its `always()` instead.
    """
    steps = _steps(CI_PYTHON, "python")
    publish = next(
        s for s in steps if "evidence/pytest.junit.xml" in str(s.get("run", ""))
    )
    assert publish["if"] == "always()", "a red run's JUnit report is the one that matters"
    assert "latest-junit.xml" in str(publish["run"]), (
        "the report must be copied from the stable path scripts/test.sh actually writes"
    )


def test_ci_python_runs_the_suite_exactly_once():
    """One full-suite pass per leg.

    The suite used to run TWICE per Python leg for a coverage number that is measurably identical
    either way (29845 statements / 12907 missed / 56.75% both ways, re-proved before the second
    pass was deleted). A reintroduced second pass is a ~2x compute regression nobody would notice
    from a green check.
    """
    steps = _steps(CI_PYTHON, "python")
    suite_runs = [s for s in steps if "scripts/test.sh" in str(s.get("run", ""))]
    assert len(suite_runs) == 1, "the suite must run exactly once per Python leg"
    assert not any(
        str(s.get("run", "")).lstrip().startswith("pytest ") for s in steps
    ), "a bare second `pytest` pass is the duplicate full-suite run this job removed"


def test_ci_python_keeps_the_coverage_gate_blocking():
    text = CI_PYTHON.read_text(encoding="utf-8")
    assert "continue-on-error: true" not in text
    assert "scripts/test.sh" in text
    assert "fetch-depth: 0" in text


def test_renderer_ci_emits_junit_and_uploads_evidence():
    steps = _steps(RENDERER_CI, "renderer")
    test_step = next(s for s in steps if s.get("name") == "Test")
    assert "--reporter=junit" in test_step["run"]
    assert "--reporter=default" in test_step["run"]
    assert "--outputFile.junit=evidence/renderer.junit.xml" in test_step["run"]

    uploads = _upload_steps(RENDERER_CI, "renderer")
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "evidence"
    # `uses:` steps ignore defaults.run.working-directory, so the path is repo-root-relative.
    assert upload["with"]["path"] == (
        "plugins/tautline-ops/skills/iteration-review/renderer-kit/evidence/"
    )


VALIDATE_GATE_IDS = (
    "methodology-suite",
    "compile-cli",
    "validate-sh-freeze",
    "whitespace",
    "pr-backlog-ref",
)


def test_validate_workflow_gives_every_gate_an_id_and_still_reports_after_failure():
    steps = {s["id"]: s for s in _steps(VALIDATE, "validate") if "id" in s}
    for gate in VALIDATE_GATE_IDS:
        assert gate in steps, f"gate {gate} needs an id so its outcome can be composed"
    for gate in VALIDATE_GATE_IDS[1:]:
        assert steps[gate]["if"] == "always()", "later gates must report after an earlier failure"


def test_validate_workflow_composes_one_result_per_gate():
    compose = next(
        s for s in _steps(VALIDATE, "validate") if s.get("name") == "Compose evidence document"
    )
    assert compose["if"] == "always()"
    assert ".github/scripts/emit_evidence.py" in compose["run"]
    assert "--suite validate:eval" in compose["run"]
    for gate in VALIDATE_GATE_IDS:
        assert f"--result validate.{gate}=${{{{ steps.{gate}.outcome }}}}" in compose["run"]


def test_validate_workflow_uploads_one_evidence_artifact():
    uploads = _upload_steps(VALIDATE, "validate")
    assert len(uploads) == 1
    assert uploads[0]["if"] == "always()"
    assert uploads[0]["with"]["name"] == "evidence"
    assert uploads[0]["with"]["path"] == "evidence/"


def test_validate_workflow_keeps_its_frozen_gates():
    text = VALIDATE.read_text(encoding="utf-8")
    assert "scripts/validate.sh" in text
    assert "py_compile bin/tautline" in text
    assert "git diff --check" in text


def test_npm_audit_gives_both_audit_steps_an_id():
    steps = {s["id"]: s for s in _steps(NPM_AUDIT, "audit") if "id" in s}
    assert "audit-critical" in steps
    assert "audit-high" in steps
    # The critical audit stays blocking: no continue-on-error, no always().
    assert "continue-on-error" not in steps["audit-critical"]
    assert "if" not in steps["audit-critical"]
    # The informational audit keeps its existing non-blocking behavior.
    assert steps["audit-high"]["continue-on-error"] is True


def test_npm_audit_composes_a_probe_suite_from_step_outcomes():
    compose = next(
        s for s in _steps(NPM_AUDIT, "audit") if s.get("name") == "Compose evidence document"
    )
    assert compose["if"] == "always()"
    # The job's defaults.run.working-directory is the renderer-kit; the composer lives at the root.
    assert compose["working-directory"] == "${{ github.workspace }}"
    assert "--suite npm-audit:probe" in compose["run"]
    # `outcome` survives continue-on-error; `conclusion` would lie about a failing audit.
    assert "--result npm-audit.critical=${{ steps.audit-critical.outcome }}" in compose["run"]
    assert "--result npm-audit.high=${{ steps.audit-high.outcome }}" in compose["run"]
    assert "conclusion" not in compose["run"]


def test_npm_audit_uploads_one_evidence_artifact():
    uploads = _upload_steps(NPM_AUDIT, "audit")
    assert len(uploads) == 1
    assert uploads[0]["if"] == "always()"
    assert uploads[0]["with"]["name"] == "evidence"
    assert uploads[0]["with"]["path"] == "evidence/"


def test_npm_audit_keeps_the_critical_gate_blocking():
    text = NPM_AUDIT.read_text(encoding="utf-8")
    assert "npm audit --audit-level=critical" in text
    assert "npm ci" in text


def test_evidence_workflow_actions_are_sha_pinned():
    # Supply-chain convention: a mutable tag like `@v4` must not slip in.
    #
    # CI_PYTHON_FULL joined this tuple with the runner-identity assertion (item 57). It had been
    # declared above and then left out of the only SHA-pin check in the suite -- all eight of its
    # refs were already pinned, so the gap cost nothing yet and would have been invisible until it
    # did.
    for workflow in (CI_PYTHON, CI_PYTHON_FULL, RENDERER_CI, VALIDATE, NPM_AUDIT):
        for job in _jobs(workflow):
            for step in _steps(workflow, job):
                ref = str(step.get("uses", ""))
                if not ref:
                    continue
                # Same-repo local actions (`./path`) carry no `@sha` and need none: they resolve
                # inside the commit under test and move with it, so there is no mutable
                # third-party tag to pin. The exemption is deliberately keyed on the `./` prefix
                # and NOT on "the ref has no @" -- the latter would silently re-admit a bare
                # `actions/checkout`, trading a supply-chain guard for a routing one.
                if ref.startswith("./"):
                    continue
                action, _, pin = ref.partition("@")
                assert SHA_PIN.match(pin), f"{action} must be pinned to a 40-char commit SHA"


def test_sha_pin_exemption_does_not_admit_unpinned_third_party_actions():
    """The `./` exemption must stay narrow.

    Guards the exact loophole the item-57 review flagged: an exemption written as "skip refs with
    no `@`" reads as equivalent and is not -- it would let `actions/checkout` in unpinned. This
    asserts the discriminator is the `./` prefix by exercising both shapes directly.
    """
    exempt = "./.github/actions/assert-runner-identity"
    assert exempt.startswith("./")

    for unpinned in ("actions/checkout", "actions/checkout@v4", "third/party@main"):
        assert not unpinned.startswith("./"), f"{unpinned} must not qualify for the local exemption"
        _, _, pin = unpinned.partition("@")
        assert not SHA_PIN.match(pin), f"{unpinned} must still fail the SHA pin"


def test_evidence_output_dirs_are_git_ignored():
    root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/evidence/" in root_ignore
    renderer_ignore = (
        ROOT
        / "plugins/tautline-ops/skills/iteration-review/renderer-kit/.gitignore"
    ).read_text(encoding="utf-8")
    assert "evidence/" in renderer_ignore


# --- the daily full-matrix workflow ------------------------------------------------------------
#
# Per-PR `ci-python` runs one interpreter. That is only safe because this workflow runs the rest,
# so the properties below are the ones that keep the trim from being a silent coverage loss.


def test_full_matrix_fires_without_depending_on_the_default_branch():
    """The load-bearing trigger is `push` to the integration branch, NOT the schedule.

    GitHub runs `schedule` only from the repository's DEFAULT branch. This repo's default is
    `main`, the stable channel, many minors behind `experimental` -- verified against this repo's
    own npm-audit history, whose scheduled runs all report headBranch=main. A workflow declared on
    `experimental` with only a schedule does not run AT ALL until a release promotion carries it to
    `main`, so trimming the per-PR matrix against it would leave the 3.10 floor covered by nothing
    while looking, from the repo, exactly like coverage.
    """
    triggers = _triggers(CI_PYTHON_FULL)
    branches = (triggers.get("push") or {}).get("branches") or []
    assert "experimental" in branches, (
        "the full matrix must fire on merges into the integration branch; a schedule alone cannot "
        "run from a non-default branch"
    )
    assert triggers.get("schedule"), (
        "the daily schedule is still declared, for the branch-sat-untouched case"
    )
    assert "workflow_dispatch" in triggers, (
        "the gate must be runnable deliberately, or it cannot be verified at all"
    )
    # Still off the per-PR path -- that is the whole compute win.
    assert "pull_request" not in triggers


def test_scheduled_full_matrix_tests_the_integration_branch_not_the_default_branch():
    """A scheduled run is dispatched from `main`. Without an explicit ref it would test the stable
    channel and report green about a tree nobody is developing on."""
    checkout = next(
        step for step in _steps(CI_PYTHON_FULL, "python")
        if "actions/checkout" in str(step.get("uses", ""))
    )
    ref = str(checkout["with"]["ref"])
    assert "schedule" in ref and "experimental" in ref, (
        "the checkout must redirect a scheduled run at the integration branch"
    )


def test_daily_full_matrix_keeps_the_coverage_ratchet_blocking():
    steps = _steps(CI_PYTHON_FULL, "python")
    suite_runs = [
        s for s in steps
        if "scripts/validate.sh" in str(s.get("run", ""))
        or "scripts/test.sh" in str(s.get("run", ""))
    ]
    assert len(suite_runs) == 1, "the daily job runs the suite once per leg too"
    addopts = suite_runs[0]["env"]["PYTEST_ADDOPTS"]
    assert "--cov=tautline_methodology" in addopts
    assert "--cov-config=.coveragerc" in addopts
    assert "continue-on-error: true" not in CI_PYTHON_FULL.read_text(encoding="utf-8"), (
        "a daily gate that cannot fail the run is the FM1/FM3 anti-pattern"
    )


def test_daily_full_matrix_evidence_reports_every_leg():
    """A 3.10-only failure in the daily run must not publish green evidence either."""
    job = _jobs(CI_PYTHON_FULL)["evidence"]
    assert "cancelled()" in job["if"]
    compose = next(s for s in job["steps"] if s.get("name") == "Compose the run's evidence")
    for leg in _jobs(CI_PYTHON_FULL)["python"]["strategy"]["matrix"]["python-version"]:
        assert f"legs/py-{leg}/leg-status.txt" in compose["run"]
        assert f"ci-python-full.py-{leg}=" in compose["run"]
