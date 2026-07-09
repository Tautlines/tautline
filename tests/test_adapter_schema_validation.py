"""arch-config-1/2/3 (productization): the adapter schema is now ENFORCED at load time by a
stdlib-only validator (no third-party runtime dependency), with root additionalProperties:false so
a misspelled top-level key fails loud instead of passing silently. `validate-adapter` exposes the
same check as a self-serve lint command.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

EXPECTED_EXAMPLE_COMMANDS = {
    "earlyWarningSmoke": "make ci-status-main",
    "mergeConflictCheck": "git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null",
}

EXPECTED_SCHEMA_PROPERTY_NAMES = {
    "acceptanceHarnesses",
    "approvedCloudProviders",
    "autoP1Categories",
    "autoRunAtBoundary",
    "awsCliConvention",
    "backlogProvider",
    "bootstrapEvidence",
    "branchLivenessCheck",
    "bugBacklog",
    "codexFastMode",
    "costPreferences",
    "contextIndexPaths",
    "contextRotation",
    "contractPath",
    "developmentEnvironment",
    "documentContext",
    "earlyWarningSmoke",
    "goalArtifacts",
    "goalExecution",
    "goalRun",
    "granularities",
    "hardPercent",
    "heartbeatBoundary",
    "heartbeatMinutes",
    "historicalPaths",
    "humanLog",
    "ignoredDocPaths",
    "inactiveAcceptanceEnforcement",
    "interviewArtifact",
    "iterationReview",
    "jsonlLog",
    "laneCoordination",
    "laneStatusDir",
    "mergeConflictCheck",
    "milestoneContinuation",
    "milestoneUpdate",
    "milestoneRun",
    "newCloudProviderRequiresApproval",
    "observabilityEvents",
    "pendingTags",
    "profileLockPath",
    "profiles",
    "productChat",
    "product-docs",
    "repoEvidence",
    "rendererVersion",
    "requiredBoundaryEvents",
    "roleVocabulary",
    "rollupJson",
    "sessionJournal",
    "softPercent",
    "sourceMaterialRule",
    "sourceMaterials",
    "stateDir",
    "stakeholderQuestions",
    "support-docs",
    "supportedRuntimes",
    "technologyStack",
    "trackedDocRoots",
    "usageAccounting",
    "workProfiles",
}

EXPECTED_SCHEMA_ENUM_LITERALS = {
    "github-issues",
    "github-projects",
    "darwin",
    "legacy-reviewed",
    "linux",
    "wsl1",
    "wsl2",
    "win32",
}


def _example(cli):
    data = json.loads(EXAMPLE.read_text())
    assert cli.schema_validation_errors(data, cli._adapter_schema()) == []
    return data


def _schema_property_names(node):
    names = set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in node.values():
            names.update(_schema_property_names(value))
    elif isinstance(node, list):
        for value in node:
            names.update(_schema_property_names(value))
    return names


def _schema_enum_literals(node):
    literals = set()
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list):
            literals.update(value for value in enum if isinstance(value, str))
        const = node.get("const")
        if isinstance(const, str):
            literals.add(const)
        for value in node.values():
            literals.update(_schema_enum_literals(value))
    elif isinstance(node, list):
        for value in node:
            literals.update(_schema_enum_literals(value))
    return literals


def test_example_adapter_is_schema_valid(cli):
    _example(cli)


def test_example_adapter_keeps_public_fixture_capabilities(cli):
    data = _example(cli)

    assert data["project"] == "Example SaaS"
    for command_name, expected_command in EXPECTED_EXAMPLE_COMMANDS.items():
        assert data["commands"][command_name] == expected_command
    assert data["bootstrapEvidence"]
    assert data["iterationReview"]["recordDir"] == "docs/iteration-reviews"
    assert data["iterationReview"]["boundary"]["autoRunAtBoundary"] is True
    assert data["milestoneUpdate"]["webhookEnv"] == "EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK"
    assert data["behaviorSpecs"]["sourceMaterials"] == [
        "docs/product/user-scenarios.md",
        "docs/product/acceptance-criteria.md",
    ]
    assert data["behaviorSpecs"]["sourceMaterialRule"] == (
        "Reviewed business/user scenario documents are upstream source material for behavior specs "
        "and must be reconciled before a feature is marked done."
    )
    assert set(data["behaviorSpecs"]["roleVocabulary"]) == {"allowed", "forbidden"}
    assert data["stakeholderQuestions"]["defaultMention"] == "@example-maintainer"
    assert data["stakeholderQuestions"]["openLabel"] == "stakeholder-question"
    assert data["developmentEnvironment"]["supportedRuntimes"] == ["linux", "darwin", "wsl2"]
    assert data["developmentEnvironment"]["windows"]["native"] == "unsupported"
    assert data["developmentEnvironment"]["windows"]["supportedRuntime"] == "wsl2"


def test_adapter_schema_exposes_required_public_contract_fields(cli):
    schema = cli._adapter_schema()

    assert sorted(EXPECTED_SCHEMA_PROPERTY_NAMES - _schema_property_names(schema)) == []
    assert sorted(EXPECTED_SCHEMA_ENUM_LITERALS - _schema_enum_literals(schema)) == []


def test_lane_coordination_enforcement_schema_contract(cli):
    schema = cli._adapter_schema()
    lane_coordination = schema["properties"]["laneCoordination"]["properties"]

    assert lane_coordination["enforcement"] == {
        "type": "string",
        "enum": ["warn", "strict"],
    }


def test_default_aws_cli_convention_names_identity_check(cli):
    assert "aws sts get-caller-identity" in cli.DEFAULT_AWS_CLI_CONVENTION


def test_unknown_top_level_key_is_rejected(cli):
    data = _example(cli)
    data["bogusKey"] = True
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("bogusKey" in e and "unknown property" in e for e in errors)


def test_wrong_scalar_type_is_rejected(cli):
    data = _example(cli)
    data["productionDeployExists"] = "yes"
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("productionDeployExists" in e and "boolean" in e for e in errors)


def test_bad_nested_enum_is_rejected(cli):
    data = _example(cli)
    data["laneCoordination"]["enforcement"] = "loose"
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("enforcement" in e for e in errors)


def test_legacy_t0_round_budget_is_schema_compatible(cli):
    data = _example(cli)
    data["review"]["roundBudgets"]["T0"] = 1
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert errors == []


def test_schema_version_pattern_enforced(cli):
    data = _example(cli)
    data["schemaVersion"] = "v1"  # not semver
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("schemaVersion" in e for e in errors)


def test_adapter_rejects_dotdot_escape_in_source_of_truth(cli):
    # A5: a path-typed field that escapes the project root via .. is a schema violation.
    data = _example(cli)
    data["planningArtifacts"]["sourceOfTruth"] = "../../etc"
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("sourceOfTruth" in e and "pattern" in e for e in errors)


def test_adapter_rejects_absolute_and_home_path_typed_fields(cli):
    # A5: absolute and ~-expanded values on a non-allowlisted path field are rejected. (scratchPaths
    # itself is an intentional allowlist exception - the framework default is ~/.claude/plans/.)
    for bad in ("/etc/passwd", "~/.ssh/id_rsa"):
        data = _example(cli)
        data["goalArtifacts"]["sourceOfTruth"] = bad
        errors = cli.schema_validation_errors(data, cli._adapter_schema())
        assert any("sourceOfTruth" in e and "pattern" in e for e in errors), bad


def test_adapter_accepts_normal_relative_path(cli):
    data = _example(cli)
    data["planningArtifacts"]["sourceOfTruth"] = "docs/planning/source-of-truth.md"
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert errors == []


def test_load_project_fails_loud_on_unknown_key(cli, tmp_path):
    data = json.loads(EXAMPLE.read_text())
    data["typodKey"] = 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    try:
        cli.load_project(bad)
        raise AssertionError("load_project accepted an adapter with an unknown top-level key")
    except SystemExit as exc:
        assert "typodKey" in str(exc)


def test_development_environment_status_accepts_wsl2(cli):
    data = _example(cli)
    normalized = cli.load_project(EXAMPLE)

    status = cli.development_environment_status(normalized, runtime="wsl2")

    assert status["runtime"] == "wsl2"
    assert status["issues"] == []
    assert data["developmentEnvironment"]["windows"]["supportedRuntime"] == "wsl2"


def test_detected_development_runtime_recognizes_wsl2(cli, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    original_read_text = cli.Path.read_text

    def fake_read_text(path, *args, **kwargs):
        if str(path) == "/proc/sys/kernel/osrelease":
            return "5.15.90.1-microsoft-standard-WSL2"
        if str(path) == "/proc/version":
            return "Linux version 5.15.90.1-microsoft-standard-WSL2"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(cli.Path, "read_text", fake_read_text)

    assert cli.detected_development_runtime() == "wsl2"


def test_detected_development_runtime_recognizes_wsl1_without_approving_wsl2(cli, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    original_read_text = cli.Path.read_text

    def fake_read_text(path, *args, **kwargs):
        if str(path) in {"/proc/sys/kernel/osrelease", "/proc/version"}:
            return "Linux version 4.4.0-microsoft"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(cli.Path, "read_text", fake_read_text)

    assert cli.detected_development_runtime() == "wsl1"
    data = cli.load_project(EXAMPLE)
    status = cli.development_environment_status(data, runtime="wsl1")
    assert status["issues"]
    assert "wsl1" in status["issues"][0]


def test_development_environment_status_blocks_native_windows_when_unsupported(cli):
    data = cli.load_project(EXAMPLE)

    status = cli.development_environment_status(data, runtime="win32")

    assert status["issues"]
    assert "native Windows is not a supported lane runtime" in status["issues"][0]
    assert "WSL2" in status["issues"][0]


def test_development_environment_is_optional_for_legacy_adapters(cli):
    data = json.loads(EXAMPLE.read_text())
    data.pop("developmentEnvironment")
    normalized = data.copy()
    normalized["developmentEnvironment"] = cli.normalize_development_environment(data)

    status = cli.development_environment_status(normalized, runtime="win32")

    assert status["issues"] == []
    assert status["warnings"] == ["adapter does not declare supported development runtimes; using compatibility mode"]


def test_development_environment_rejects_contradictory_native_windows_support(cli, tmp_path):
    data = json.loads(EXAMPLE.read_text())
    data["developmentEnvironment"]["supportedRuntimes"].append("win32")
    bad = tmp_path / "bad-windows-policy.json"
    bad.write_text(json.dumps(data), encoding="utf-8")

    try:
        cli.load_project(bad)
        raise AssertionError("load_project accepted contradictory Windows runtime policy")
    except SystemExit as exc:
        assert "cannot include win32" in str(exc)


def test_load_project_coerces_legacy_t0_round_budget(cli, tmp_path, capsys):
    data = json.loads(EXAMPLE.read_text())
    data["review"]["roundBudgets"]["T0"] = 1
    legacy = tmp_path / "legacy-t0-budget.json"
    legacy.write_text(json.dumps(data))

    loaded = cli.load_project(legacy)

    captured = capsys.readouterr()
    assert loaded["review"]["roundBudgets"]["T0"] == 0
    assert "review.roundBudgets.T0=1 is legacy" in captured.err


def test_validate_adapter_command_passes_on_example(run_cli):
    res = run_cli("validate-adapter", "--project", str(EXAMPLE))
    assert res.returncode == 0, res.stderr
    assert "matches the adapter schema" in res.stdout


def test_validate_adapter_command_reports_violations(run_cli, tmp_path):
    data = json.loads(EXAMPLE.read_text())
    data["productionDeployExists"] = "nope"  # wrong type
    data["alsoBogus"] = 1  # unknown key
    bad = tmp_path / "bad-adapter.json"
    bad.write_text(json.dumps(data))
    res = run_cli("validate-adapter", "--project", str(bad))
    assert res.returncode == 1
    assert "schema violation" in res.stderr


def test_validate_adapter_command_warns_on_legacy_t0_budget(run_cli, tmp_path):
    data = json.loads(EXAMPLE.read_text())
    data["review"]["roundBudgets"]["T0"] = 1
    legacy = tmp_path / "legacy-t0-adapter.json"
    legacy.write_text(json.dumps(data))

    res = run_cli("validate-adapter", "--project", str(legacy))

    assert res.returncode == 0, res.stderr
    assert "matches the adapter schema" in res.stdout
    assert "review.roundBudgets.T0=1 is legacy" in res.stderr
