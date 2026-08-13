"""Control-posture report engine (item 74 PR-A / WS1, plan T1.0-T1.2).

The gap both member RCAs name: every diagnosed safeguard ships as an adapter opt-in defaulting
to off/warn, and a control that is off, absent or self-disabled produces SILENCE from
`methodology-status` -- which is indistinguishable from healthy. A lane can therefore carry every
go-live gate in schema form while enforcing none of them, and no command says so.

So `control_posture_rows` reports one row per known control with a state in
{block, warn, off, empty, unreachable}, and anything but `block` is posture drift. Diagnostic
only in this release: no row enters any `*_failures` list under ANY flag combination
(test_posture_lines_never_change_exit_code). PR-C owns the opt-in profile that gates on them.

Fixture faithfulness (plan T1.1(1), packet A8): the economics-lane fixture is that adapter as it
actually was at `239fbcf2` -- uiEvidence disabled, criticalJourneys empty, floors at warn,
planAcceptance/sideEffectProof off, maxMarkers -1, and NO deploymentTargets. Nothing is invented
to make an assertion pass, because the point of the fixture is that it reproduces the lane the
incident happened on.
"""

import inspect
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"
REPO_LOCAL_ADAPTER_REL = ".tautline/adapter.json"


# --- fixtures ---------------------------------------------------------------------------------


def economics_lane_adapter() -> dict:
    """The economics lane as it was at `239fbcf2` (20260726 RCA, Validation item 3)."""
    return {
        "uiEvidence": {"enabled": False},
        "criticalJourneys": [],
        "coverageFloor": {"enforcement": "warn"},
        "ciTestGate": {"enabled": True, "enforcement": "warn"},
        "flakyQuarantine": {"enforcement": "warn", "maxMarkers": -1},
        "planAcceptance": {"enforcement": "off"},
        "sideEffectProof": {"enforcement": "off"},
        "commands": {"fastPreflight": "make pf-fast", "fullPreflight": "make preflight"},
    }


def all_block_adapter() -> dict:
    """The other end: every control on, bounded, and enforcing."""
    return {
        "ciTestGate": {"enabled": True, "enforcement": "block"},
        "uiEvidence": {
            "enabled": True, "enforcement": "block", "captureCommand": "playwright test",
        },
        "commands": {
            "fastPreflight": "make pf-fast",
            "fullPreflight": "make preflight && playwright test",
        },
        "criticalJourneys": [{"name": "checkout", "featurePath": "app/checkout"}],
        "runtimeConfig": {"enforcement": "block", "requiredSecrets": ["STRIPE_KEY"]},
        "flakyQuarantine": {"enforcement": "block", "maxMarkers": 0, "scanPath": "tests"},
        "readiness": {
            "enforcement": "block",
            "sources": ["docs/readiness.md"],
            "canaryWorkflow": "canary.yml",
            "alarmSources": ["docs/ops/alarms.md"],
            "requiredChecks": ["validate"],
        },
        "healthContract": {"enforcement": "block"},
        "sideEffectProof": {"enforcement": "block"},
        "remediation": {"enforcement": "block"},
        "planAcceptance": {"enforcement": "block"},
        "coverageFloor": {"enforcement": "block"},
        "migrationSafety": {"enforcement": "block", "migrationsPath": "db/migrations"},
    }


def rows_by_control(cli, data: dict) -> dict[str, dict]:
    return {row["control"]: row for row in cli.control_posture_rows(data)}


# --- T1.1(1) the regression fixture ------------------------------------------------------------


def test_economics_lane_fixture_flags_every_advisory_control(cli):
    """Validation item 3 of the 20260726 RCA: the lane ran with everything advisory and no
    surface said so. Every control this adapter leaves advisory must report a non-block row."""
    rows = rows_by_control(cli, economics_lane_adapter())
    assert rows["uiEvidence"]["state"] == "off"
    # No deploymentTargets in this fixture, so the detail is the plain disabled variant.
    assert rows["uiEvidence"]["detail"] == "disabled"
    assert rows["criticalJourneys"]["state"] == "empty"
    assert rows["coverageFloor"]["state"] == "warn"
    assert rows["ciTestGate"]["state"] == "warn"
    assert rows["flakyQuarantine"]["state"] == "empty"
    assert rows["planAcceptance"]["state"] == "off"
    assert rows["sideEffectProof"]["state"] == "off"
    assert rows["healthContract"]["state"] == "off"
    assert rows["remediation"]["state"] == "off"
    # `warn` with no migrationsPath is a gate that scans nothing, so `empty` is the truer
    # reading -- and this fixture, faithfully, sets no path (Codex R1 P2).
    assert rows["migrationSafety"]["state"] == "empty"
    assert rows["runtimeConfig.requiredSecrets"]["state"] == "empty"
    assert rows["readiness"]["state"] == "off"
    # Not one of them is block: the whole lane is advisory.
    assert all(row["state"] != "block" for row in rows.values())
    summary = cli.control_posture_summary_line(cli.control_posture_rows(economics_lane_adapter()))
    assert summary.startswith("control_posture: ")
    assert "block=0" in summary
    assert "drift=none" not in summary


def test_economics_lane_fixture_flags_binding_preflight_shape(cli):
    """The cluster spec's named dangerous shape, and a row of its OWN: a binding preflight that
    cannot exercise the declared primary user surface. v1 of the plan wrongly collapsed this into
    the uiEvidence row, which loses the distinction the RCA is about."""
    row = cli.binding_preflight_row(economics_lane_adapter())
    assert row["control"] == "bindingPreflight"
    assert row["state"] == "unreachable"
    assert "fullPreflight" in row["detail"]
    # ... and it is a separate row from uiEvidence in the assembled table.
    rows = rows_by_control(cli, economics_lane_adapter())
    assert rows["bindingPreflight"]["state"] == "unreachable"
    assert rows["uiEvidence"]["control"] != rows["bindingPreflight"]["control"]


# --- T1.1(3)/(4) the enabled-flag and self-disable audit ---------------------------------------


def test_ci_test_gate_disabled_is_not_healthy(cli):
    """`ci_test_gate_issues` short-circuits to [] when enabled is false, so the gate never runs --
    an `enforcement: block` string on a disabled gate is the exact off-looks-healthy bug."""
    rows = rows_by_control(cli, {"ciTestGate": {"enabled": False, "enforcement": "block"}})
    assert rows["ciTestGate"]["state"] == "off"
    assert "enabled" in rows["ciTestGate"]["detail"]
    assert rows["ciTestGate"]["state"] != "block"


def test_ci_test_gate_expect_tests_self_disable_is_visible(cli):
    """The IMPLICIT self-disable: with no tests detected and expectTests false,
    `ci_test_gate_issues` returns [] and the gate is silent. The row must say so."""
    gate = {"ciTestGate": {"enabled": True, "enforcement": "block", "expectTests": False}}
    rows = rows_by_control(cli, gate)
    assert rows["ciTestGate"]["state"] != "block"
    assert "expectTests" in rows["ciTestGate"]["detail"]


def test_readiness_row_keys_on_enforcement_not_sources(cli):
    """The detection-baseline gate is readiness.ENFORCEMENT ('Default off' in the schema,
    consumed by readiness_review). Keying the row on readiness.sources -- a required file list --
    reports a false green for the control the go-live RCA cared most about."""
    data = {"readiness": {"sources": ["docs/readiness.md"]}}
    row = cli.readiness_posture_row(data)
    assert row["state"] == "off"
    for name in ("canaryWorkflow", "alarmSources", "requiredChecks"):
        assert name in row["detail"]
    # Opted in but with nothing to check is UNREACHABLE, not healthy.
    opted_in_empty = cli.readiness_posture_row({"readiness": {"enforcement": "block"}})
    assert opted_in_empty["state"] == "unreachable"


def test_a_json_null_is_an_absent_value_not_the_word_none(cli):
    """`str(None)` is "None" -- truthy, four characters, and indistinguishable from a real
    setting. Adapter JSON writes "unset" as `null` all over, so reading these fields with a bare
    `str()` would report a control as CONFIGURED because its value is null. That is a false green
    in the one surface that exists to make false greens visible, and it is the same trap the
    classified-findings contract paid a review round for."""
    nulled = {
        "readiness": {"enforcement": None, "canaryWorkflow": None},
        "commands": {"fastPreflight": None, "fullPreflight": None},
        "uiEvidence": {"enabled": True, "enforcement": None, "captureCommand": None},
        "flakyQuarantine": {"enforcement": None, "maxMarkers": None, "scanPath": None},
        "runtimeConfig": {"enforcement": None, "requiredSecrets": ["X"]},
        "healthContract": {"enforcement": None},
    }
    rows = rows_by_control(cli, nulled)
    assert rows["readiness"]["state"] == "off"
    assert "canaryWorkflow" in rows["readiness"]["detail"]
    # An empty binding preflight is unreachable; a null one must not read as configured.
    assert rows["bindingPreflight"]["state"] == "unreachable"
    assert "empty" in rows["bindingPreflight"]["detail"]
    for control in ("uiEvidence", "healthContract", "runtimeConfig.requiredSecrets"):
        assert rows[control]["state"] == "off", control
    assert rows["flakyQuarantine"]["state"] == "empty"
    assert "None" not in cli.control_posture_summary_line(cli.control_posture_rows(nulled))


def test_a_malformed_field_never_takes_the_status_surface_down(cli):
    """The row engine is DIAGNOSTIC and public (PR-C consumes it). normalize_flaky_quarantine
    rejects a non-integer maxMarkers at load, so a started lane never reaches this -- but a
    diagnostic that raises on a malformed field is worse than the silence it replaces."""
    rows = rows_by_control(cli, {"flakyQuarantine": {"maxMarkers": "lots", "scanPath": "tests"}})
    assert rows["flakyQuarantine"]["state"] == "empty"


def test_a_generic_runner_prefix_is_not_a_ui_surface_check(cli):
    """Codex R1 P2. Taking the FIRST word of a capture command routed through a generic runner
    stores only that runner, and then ANY preflight using the same runner satisfies the check:
    `captureCommand: "npm run e2e"` was reported as exercised by `fullPreflight: "npm ci &&
    pytest"`. Reporting bindingPreflight=block for a gate that never touches the UI surface is
    the exact false green this engine exists to kill."""
    routed = {
        "uiEvidence": {"enabled": True, "enforcement": "block", "captureCommand": "npm run e2e"},
        "commands": {"fastPreflight": "npm ci", "fullPreflight": "npm ci && pytest"},
    }
    assert cli.binding_preflight_row(routed)["state"] == "unreachable"
    # The same lane whose preflight actually runs the capture reports block.
    exercised = {**routed, "commands": {"fullPreflight": "npm ci && npm run e2e"}}
    assert cli.binding_preflight_row(exercised)["state"] == "block"
    # And a short token must match a WORD, never any substring: "ui" is inside "build".
    short = {
        "uiEvidence": {"enabled": True, "enforcement": "block", "captureCommand": "make ui"},
        "commands": {"fullPreflight": "npm run build"},
    }
    assert cli.binding_preflight_row(short)["state"] == "unreachable"


def test_a_gate_with_nothing_to_scan_is_not_enforcing(cli):
    """Codex R1 P2, and the same class in a second place found by applying its generalization.
    migration_safety_issues returns [] when migrationsPath is unset, and remediation_issues
    returns [] when the ledger file is absent -- so `enforcement: block` on either scans nothing
    while wearing the strongest word in the vocabulary."""
    unset_path = {"migrationSafety": {"enforcement": "block"}}
    row = rows_by_control(cli, unset_path)["migrationSafety"]
    assert row["state"] == "empty"
    assert "migrationsPath" in row["detail"]
    configured = {"migrationSafety": {"enforcement": "block", "migrationsPath": "db/migrations"}}
    assert rows_by_control(cli, configured)["migrationSafety"]["state"] == "block"


def test_an_enforcing_remediation_gate_over_a_missing_ledger_is_not_enforcing(cli, tmp_path):
    cfg = {"remediation": {"enforcement": "block"}}
    rows = {r["control"]: r for r in cli.control_posture_rows(cfg, tmp_path)}
    assert rows["remediation"]["state"] == "empty"
    assert "ledger" in rows["remediation"]["detail"]
    ledger = tmp_path / "docs" / "quality" / "remediation-obligations.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("[]\n", encoding="utf-8")
    present = {r["control"]: r for r in cli.control_posture_rows(cfg, tmp_path)}
    assert present["remediation"]["state"] == "block"
    # enforcement off is the stronger, simpler truth and still wins.
    off = {r["control"]: r for r in cli.control_posture_rows({"remediation": {}}, tmp_path)}
    assert off["remediation"]["state"] == "off"


def test_a_generic_test_runner_is_not_a_ui_surface_check(cli):
    """Codex R2 P2. `pytest tests/e2e` and `pytest tests/unit` share their first word, so
    keeping `pytest` out of the generic list reintroduced the exact class R1 fixed for `npm`.
    The runners that genuinely NAME a surface stay out of the generic list."""
    routed = {
        "uiEvidence": {"enabled": True, "enforcement": "block", "captureCommand": "pytest tests/e2e"},
        "commands": {"fullPreflight": "pytest tests/unit"},
    }
    assert cli.binding_preflight_row(routed)["state"] == "unreachable"
    exercised = {**routed, "commands": {"fullPreflight": "pytest tests/unit && pytest tests/e2e"}}
    assert cli.binding_preflight_row(exercised)["state"] == "block"
    # playwright/cypress name a surface and must NOT be treated as generic.
    assert "playwright" not in cli.GENERIC_COMMAND_RUNNERS
    assert not set(cli.UI_SURFACE_RUNNER_MARKERS) & set(cli.GENERIC_COMMAND_RUNNERS)


def test_readiness_without_sources_cannot_run_its_gate(cli):
    """Codex R2 P2. `readiness-review` refuses outright without readiness.sources, so an opted-in
    lane with a full detection baseline and no sources cannot run the gate at all -- and would
    otherwise have reported `block`, and a whole-lane `drift=none`. sources joins the
    REACHABILITY list; it still never contributes to the state, which is test 5's whole point."""
    baseline = {
        "enforcement": "block",
        "canaryWorkflow": "canary.yml",
        "alarmSources": ["docs/ops/alarms.md"],
        "requiredChecks": ["validate"],
    }
    row = cli.readiness_posture_row({"readiness": baseline})
    assert row["state"] == "unreachable"
    assert "sources" in row["detail"]
    with_sources = cli.readiness_posture_row(
        {"readiness": {**baseline, "sources": ["docs/readiness.md"]}}
    )
    assert with_sources["state"] == "block"
    # ... and sources alone is still not evidence of enforcement.
    assert cli.readiness_posture_row({"readiness": {"sources": ["docs/x.md"]}})["state"] == "off"


def test_all_block_adapter_reports_no_drift(cli):
    """The other end of the range: a lane that actually enforces everything reports drift=none.
    Without this the engine could pass every negative test by always reporting drift."""
    rows = cli.control_posture_rows(all_block_adapter())
    assert [row for row in rows if row["state"] != "block"] == []
    summary = cli.control_posture_summary_line(rows)
    assert summary.endswith("drift=none")
    assert f"block={len(rows)}" in summary


# --- T1.1(7)/(8)/(9) the methodology-status wiring ---------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_adapter(target: Path, mutate=None) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for control-posture status wiring (item 74 PR-A).",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence."},
        ],
    }
    # Quiet every optional/networked gate: this file tests posture reporting, not those gates.
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["backlogProvider"] = {"enabled": False}
    data["stakeholderQuestions"] = {"enabled": False}
    data["milestoneUpdate"] = {"enabled": False}
    data["productChat"] = {"enabled": False}
    data["deploymentNotification"] = {"enabled": False}
    behavior_specs = dict(data.get("behaviorSpecs") or {})
    behavior_specs["required"] = False
    behavior_specs["acceptanceHarnesses"] = []
    data["behaviorSpecs"] = behavior_specs
    document_context = dict(data.get("documentContext") or {})
    document_context["ignoredDocPaths"] = [
        *(document_context.get("ignoredDocPaths") or []),
        "docs/product/backlog",
    ]
    data["documentContext"] = document_context
    if mutate:
        mutate(data)
    adapter = target / REPO_LOCAL_ADAPTER_REL
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    (target / SOURCE_REL).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")


def _lane(tmp_path: Path, run_cli, mutate=None) -> Path:
    """A clean, fully-started lane, mirroring test_methodology_status_classification's fixture."""
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target, mutate)
    started = run_cli(
        "lane-start", "--project", str(adapter), "--target", str(target), "--skip-update"
    )
    assert started.returncode == 0, started.stdout + started.stderr
    bootstrapped = run_cli(
        "context-bootstrap", "--project", str(adapter), "--target", str(target), "--write"
    )
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    return target


def _status(run_cli, target: Path, *flags: str):
    return run_cli("methodology-status", "--target", str(target), "--no-remote", *flags, cwd=target)


def test_status_prints_one_summary_line_and_no_per_row_detail_by_default(tmp_path, run_cli):
    """Noise budget: `methodology-status` is the surface an agent reads first, in a framework
    that maintains a document-context-budget policy. One line by default, and exactly one."""
    target = _lane(tmp_path, run_cli)
    result = _status(run_cli, target)
    lines = result.stdout.splitlines()
    summary = [line for line in lines if line.startswith("control_posture: ")]
    assert len(summary) == 1, result.stdout
    assert [line for line in lines if line.startswith("control_posture_warn:")] == []
    assert "drift=" in summary[0]


def test_status_posture_flag_prints_per_row_detail(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    result = _status(run_cli, target, "--posture")
    lines = result.stdout.splitlines()
    summary = [line for line in lines if line.startswith("control_posture: ")]
    detail = [line for line in lines if line.startswith("control_posture_warn: ")]
    assert len(summary) == 1, result.stdout
    assert detail, result.stdout
    drift = summary[0].split("drift=", 1)[1].strip()
    assert drift != "none"
    # One detail line per drifting row, and every drifting control is named.
    assert len(detail) == len(drift.split(","))
    for entry in drift.split(","):
        control = entry.split("=", 1)[0]
        assert any(line.startswith(f"control_posture_warn: {control} ") for line in detail), entry


def test_posture_lines_never_change_exit_code(tmp_path, run_cli):
    """Posture is DIAGNOSTIC in this release. The lane below has real posture drift (uiEvidence
    null, criticalJourneys null, readiness.enforcement unset); no flag combination may let that
    drift reach an exit code, and no gate list may carry it."""
    target = _lane(tmp_path, run_cli)
    baseline = _status(run_cli, target)
    assert "drift=none" not in baseline.stdout
    for flags in ((), ("--posture",), ("--strict",), ("--fail-on-drift",),
                  ("--strict", "--fail-on-drift"), ("--posture", "--strict", "--fail-on-drift")):
        result = _status(run_cli, target, *flags)
        assert result.returncode == baseline.returncode, (flags, result.stdout, result.stderr)
        blocking = [line for line in result.stdout.splitlines()
                    if line.startswith("methodology_status_blocking:")]
        assert not any("posture" in line for line in blocking), (flags, blocking)


def test_no_posture_gate_enters_the_status_failure_classification(cli):
    """Structural half of the pin above: the gate-condition surface is where a failure list would
    have to be registered to affect an exit code. No posture list may appear in it -- and the
    classification suite's partition test makes an unclassified addition impossible to miss."""
    params = set(inspect.signature(cli.methodology_status_gate_conditions).parameters)
    assert not [name for name in params if "posture" in name]
    classified = (set(cli.METHODOLOGY_STATUS_INTEGRITY_GATES)
                  | set(cli.METHODOLOGY_STATUS_DEBT_GATES))
    assert not [name for name in classified if "posture" in name]


def test_posture_summary_precedes_critical_deferral_lines(tmp_path, run_cli):
    """Ordering seam W1.1 (item 74 PR-B) left open: it printed `critical_deferral:` lines with no
    posture summary to order against. The plan's T3.3 places them AFTER the posture summary line,
    so pin it now that both surfaces exist. Both stay report-only."""
    target = _lane(tmp_path, run_cli)
    evidence = target / ".ai-runs" / "review-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "20260810T000000Z-posture-fixture.json").write_text(
        json.dumps(
            {
                "classification_status": "clean-with-deferrals",
                "classified_findings": [
                    {
                        "id": "F1",
                        "severity": "critical",
                        "status": "deferred",
                        "summary": "posture ordering fixture",
                        "deferral_rationale": "fixture rationale for the ordering pin",
                        "acceptance_criterion": "AC-1",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = _status(run_cli, target)
    lines = result.stdout.splitlines()
    summary_at = [i for i, line in enumerate(lines) if line.startswith("control_posture: ")]
    deferral_at = [i for i, line in enumerate(lines) if line.startswith("critical_deferral: ")]
    assert len(summary_at) == 1, result.stdout
    assert deferral_at, result.stdout
    assert summary_at[0] < deferral_at[0], result.stdout
    # Neither surface gates: the lane with both lines still exits as it did without them.
    assert result.returncode == _status(run_cli, _lane(tmp_path / "clean", run_cli)).returncode


# --- T1.1(10) the audit verb -------------------------------------------------------------------


DRIFTING_CLAUDE_MD = "# Rules\n\nRoutine merge: `gh pr merge 123 --squash --admin`.\n"


def _audit_target(tmp_path: Path, name: str, claude_md: str | None) -> tuple[Path, Path]:
    target = tmp_path / name
    target.mkdir(parents=True)
    if claude_md is not None:
        (target / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    adapter = target / "adapter.json"
    adapter.write_text(EXAMPLE_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8")
    return target, adapter


def test_audit_prints_posture_after_findings_and_keeps_exit_1(tmp_path, run_cli):
    target, adapter = _audit_target(tmp_path, "drifting", DRIFTING_CLAUDE_MD)
    result = run_cli("audit", "--project", str(adapter), "--target", str(target))
    assert result.returncode == 1, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    # The legacy findings block is byte-identical and still first.
    assert lines[0] == "Process drift findings:"
    assert any(line.startswith("- routine-admin-merge: ") for line in lines)
    posture_at = [i for i, line in enumerate(lines) if line.startswith("control_posture: ")]
    assert len(posture_at) == 1, result.stdout
    assert posture_at[0] > lines.index("Process drift findings:")
    assert [line for line in lines if line.startswith("control_posture_row: ")], result.stdout


def test_audit_prints_posture_on_clean_repo_and_keeps_legacy_line(tmp_path, run_cli):
    target, adapter = _audit_target(tmp_path, "clean", None)
    result = run_cli("audit", "--project", str(adapter), "--target", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "No known process drift found."
    assert len([line for line in lines if line.startswith("control_posture: ")]) == 1
    assert [line for line in lines if line.startswith("control_posture_row: ")], result.stdout
    # Posture never sets exit 1 -- a clean repo with a fully advisory adapter still exits 0.
    assert "drift=none" not in result.stdout
