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
RENDERER_CI = ROOT / ".github" / "workflows" / "renderer-ci.yml"
VALIDATE = ROOT / ".github" / "workflows" / "validate.yml"
NPM_AUDIT = ROOT / ".github" / "workflows" / "npm-audit.yml"

SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def _jobs(workflow: Path) -> dict:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]


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
    # The core anti-lie property: a 3.10-only failure must NOT publish all-green evidence.
    job = _jobs(CI_PYTHON)["evidence"]
    # `needs` must include python; the evidence job runs after the matrix legs.
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "python" in needs
    assert "cancelled()" in job["if"]
    compose = next(s for s in job["steps"] if s.get("name") == "Compose the run's evidence")
    assert "--suite ci-python:probe" in compose["run"]
    for leg in ("3.10", "3.12"):
        assert f"legs/py-{leg}/leg-status.txt" in compose["run"]
        assert f"ci-python.py-{leg}=" in compose["run"]


def test_ci_python_evidence_job_reports_the_fresh_install_gate():
    # A red fresh-install-smoke (a required check) must NOT publish all-green evidence.
    job = _jobs(CI_PYTHON)["evidence"]
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "fresh-install-smoke" in needs, "evidence must wait for the required fresh-install gate"
    compose = next(s for s in job["steps"] if s.get("name") == "Compose the run's evidence")
    assert "ci-python.fresh-install-smoke=${{ needs.fresh-install-smoke.result }}" in compose["run"]


def test_ci_python_emits_junit_on_failing_runs():
    steps = _steps(CI_PYTHON, "python")
    checks = next(s for s in steps if s.get("name") == "Run python checks")
    assert "--junitxml=evidence/pytest.junit.xml" in checks["env"]["PYTEST_ADDOPTS"]
    coverage = next(s for s in steps if str(s.get("run", "")).startswith("pytest --cov"))
    assert "--junitxml=evidence/pytest.junit.xml" in coverage["run"]


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
    for workflow in (CI_PYTHON, RENDERER_CI, VALIDATE, NPM_AUDIT):
        for job in _jobs(workflow):
            for step in _steps(workflow, job):
                ref = str(step.get("uses", ""))
                if not ref:
                    continue
                action, _, pin = ref.partition("@")
                assert SHA_PIN.match(pin), f"{action} must be pinned to a 40-char commit SHA"


def test_evidence_output_dirs_are_git_ignored():
    root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/evidence/" in root_ignore
    renderer_ignore = (
        ROOT
        / "plugins/tautline-ops/skills/iteration-review/renderer-kit/.gitignore"
    ).read_text(encoding="utf-8")
    assert "evidence/" in renderer_ignore
