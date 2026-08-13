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
    "productDevelopment",
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
    "surfaces",
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


# --- productDevelopment adapter key + broad-glob-rejecting loader (PM-surface classifier PR 1) ---

# A safe, non-docs/product plan root so the symmetric source-of-truth guard does not reject a
# legitimate docs/product/** surface. The committed example's plan/goal source-of-truth lives UNDER
# docs/product/, which WOULD (correctly) overlap a docs/product surface, so accept-case tests
# override both to a framework plan root that mirrors the real self-adapter.
SAFE_PLAN_ROOT = "docs/superpowers/plans"


def _adapter_with_surfaces(surfaces, *, planning_sot=SAFE_PLAN_ROOT, goal_sot=SAFE_PLAN_ROOT):
    data = json.loads(EXAMPLE.read_text())
    data["productDevelopment"] = {"surfaces": list(surfaces)}
    if planning_sot is not None:
        data["planningArtifacts"]["sourceOfTruth"] = planning_sot
    if goal_sot is not None:
        data["goalArtifacts"]["sourceOfTruth"] = goal_sot
    return data


def _load_surfaces(cli, tmp_path, surfaces, **kwargs):
    data = _adapter_with_surfaces(surfaces, **kwargs)
    path = tmp_path / "pd-adapter.json"
    path.write_text(json.dumps(data))
    return cli.load_project(path)


def _expect_reject(cli, tmp_path, surface, **kwargs):
    try:
        _load_surfaces(cli, tmp_path, [surface], **kwargs)
    except SystemExit:
        return
    raise AssertionError(f"loader accepted a surface it must reject: {surface!r}")


# --- schema-level cases (validated directly against the schema) ---

def test_product_development_precise_surfaces_validate(cli):
    data = _example(cli)
    data["productDevelopment"] = {"surfaces": ["docs/product/**", "docs/product/plans/**"]}
    assert cli.schema_validation_errors(data, cli._adapter_schema()) == []


def test_product_development_unknown_subkey_rejected(cli):
    data = _example(cli)
    data["productDevelopment"] = {"surfaces": ["docs/product/**"], "bogus": True}
    errors = cli.schema_validation_errors(data, cli._adapter_schema())
    assert any("bogus" in e and "unknown property" in e for e in errors)


def test_load_project_rejects_typoed_product_development_key(cli, tmp_path):
    """Codex R1 P2 regression: normalize_product_development must not silently drop an unknown
    productDevelopment key (e.g. the `surface`/`surfaces` typo). It has to reach the
    additionalProperties:false schema validation so load_project REJECTS it -- otherwise a typo'd
    surface config loads as empty (PM exemption silently disabled) instead of erroring."""
    data = _example(cli)
    # `surface` (singular) is the classic typo for `surfaces`.
    data["productDevelopment"] = {"surface": ["docs/product/**"]}
    path = tmp_path / "typo-pd-adapter.json"
    path.write_text(json.dumps(data))
    try:
        cli.load_project(path)
    except SystemExit:
        return
    raise AssertionError(
        "load_project accepted a typo'd productDevelopment key instead of rejecting it via schema"
    )


def test_product_development_surface_rejects_dotdot_and_home(cli):
    for bad in ("../escape/**", "~/secrets/**"):
        data = _example(cli)
        data["productDevelopment"] = {"surfaces": [bad]}
        errors = cli.schema_validation_errors(data, cli._adapter_schema())
        assert any("surfaces" in e and "pattern" in e for e in errors), bad


# --- default + committed-artifact validity ---

def test_product_development_defaults_to_empty_surfaces(cli, tmp_path):
    data = json.loads(EXAMPLE.read_text())
    data.pop("productDevelopment", None)
    path = tmp_path / "no-pd.json"
    path.write_text(json.dumps(data))
    normalized = cli.load_project(path)
    assert normalized["productDevelopment"]["surfaces"] == []


def test_committed_example_and_self_adapter_stay_valid(cli):
    # The example adapter declares no PM surface (opt-in default empty).
    assert cli.load_project(EXAMPLE)["productDevelopment"]["surfaces"] == []
    # The self-adapter ships the repo's concrete PM surface (pm-surface-prepush plan T3): the
    # loader accepts docs/product/** (bounded, under the allowlist, disjoint from the hard-excluded
    # docs/superpowers/** plan root the self-adapter's sourceOfTruth points at).
    self_adapter = REPO_ROOT / ".tautline" / "adapter.json"
    assert cli.load_project(self_adapter)["productDevelopment"]["surfaces"] == ["docs/product/**"]


# --- loader ACCEPT (bounded, under the docs/product allowlist, plan root outside it) ---

def test_loader_accepts_bounded_surface(cli, tmp_path):
    for good in ("docs/product/**", "docs/product/plans/**"):
        normalized = _load_surfaces(cli, tmp_path, [good])
        assert normalized["productDevelopment"]["surfaces"] == [good], good


# --- loader REJECT: rule A (wildcard root, no bounded prefix) ---

def test_loader_rejects_rule_a_wildcard_root(cli, tmp_path):
    for surface in ("**", "*", "*/**", "**/plan-*.md", "?*", "[a-z]*"):
        _expect_reject(cli, tmp_path, surface)


# --- loader REJECT: rule A2 (top-level file, no slash in fixed prefix) ---

def test_loader_rejects_rule_a2_top_level(cli, tmp_path):
    for surface in ("pyproject.toml", "CHANGELOG.md", "README.md", "*.md"):
        _expect_reject(cli, tmp_path, surface)


# --- loader REJECT: rule A3 (not under the docs/product allowlist) ---

def test_loader_rejects_rule_a3_non_product_roots(cli, tmp_path):
    for surface in (
        "docs/reference/**",
        "docs/backlog/**",
        "docs/productization/**",
        "docs/governance/**",
    ):
        _expect_reject(cli, tmp_path, surface)


# --- loader REJECT: rule A4 (wildcard mid-segment; would match docs/productization/) ---

def test_loader_rejects_rule_a4_partial_segment(cli, tmp_path):
    for surface in ("docs/product*/**", "docs/prod*/**"):
        _expect_reject(cli, tmp_path, surface)


# --- loader REJECT: rule B (fixed prefix overlaps a hard-excluded root, symmetric) ---

def test_loader_rejects_rule_b_hard_root_overlap(cli, tmp_path):
    for surface in (
        "docs/**",
        "docs/*/**",
        "docs/superpowers/**",
        "docs/releases/**",
        "docs/superpowers/plans/2026-*.md",
        "adapters/projects/prod-*.json",
        "plugins/**/plugin.json",
        ".claude-plugin/*",
    ):
        _expect_reject(cli, tmp_path, surface)


def test_loader_rejects_fnmatch_metachar_variants(cli, tmp_path):
    for surface in ("docs/superpowers/plans/2026-??-??.md", "docs/releases/[0-9]*.md"):
        _expect_reject(cli, tmp_path, surface)


def test_loader_rejects_legacy_adapter_overlaps(cli, tmp_path):
    for surface in (".minervit/**", ".minervit-ai-delivery.json"):
        _expect_reject(cli, tmp_path, surface)


# --- symmetric bounded source-of-truth guard (Design 3) ---

def test_loader_rejects_surface_overlapping_broad_plan_root(cli, tmp_path):
    # A broad structured plan root "docs" contains the docs/product/** surface -> reject.
    _expect_reject(cli, tmp_path, "docs/product/**", planning_sot="docs", goal_sot=SAFE_PLAN_ROOT)


def test_loader_rejects_surface_overlapped_by_nested_plan_root(cli, tmp_path):
    # A nested structured plan root under the surface -> reject (symmetric direction).
    _expect_reject(
        cli, tmp_path, "docs/product/**",
        planning_sot=SAFE_PLAN_ROOT, goal_sot="docs/product/plans",
    )


def test_loader_skips_prose_source_of_truth(cli, tmp_path):
    # A free-form/tracker sourceOfTruth (whitespace, not a repo-relative path) is skipped, not
    # parsed as a path -> a legitimate docs/product surface still loads.
    normalized = _load_surfaces(
        cli, tmp_path, ["docs/product/**"],
        planning_sot="GitHub issues and product docs", goal_sot=SAFE_PLAN_ROOT,
    )
    assert normalized["productDevelopment"]["surfaces"] == ["docs/product/**"]


# --- item 37: the testEvidence key (test-execution evidence) ----------------------------------


def test_validate_adapter_accepts_well_formed_test_evidence_block(cli):
    """The key is optional, but a lane that declares a report must validate on first try -- the
    schema is closed to unknown top-level keys, so the key ships with the feature, not after it."""
    data = _example(cli)
    data["testEvidence"] = {"report": {"path": ".ai-runs/junit.xml", "format": "junit-xml"}}
    assert cli.schema_validation_errors(data, cli._adapter_schema()) == []


def test_validate_adapter_rejects_malformed_test_evidence_block(cli):
    """Every malformation must fail loudly. Failing quietly here means silently degrading to
    exit-code-only evidence, which is the exact substitution this feature exists to prevent."""
    schema = cli._adapter_schema()

    unknown_format = _example(cli)
    unknown_format["testEvidence"] = {"report": {"path": "j.xml", "format": "tap"}}
    assert any("format" in e for e in cli.schema_validation_errors(unknown_format, schema))

    missing_path = _example(cli)
    missing_path["testEvidence"] = {"report": {"format": "junit-xml"}}
    assert cli.schema_validation_errors(missing_path, schema)

    # Release 2 (item 37) SHIPS testEvidence.enforcement, so this assertion is inverted from what
    # Release 1 left here. Release 1 deliberately pinned the key as unknown -- a forward guard so
    # an adapter could not declare enforcement that nothing read, which would have been a lane
    # believing it had a control it did not have. That guard did its job and is now the contract.
    for mode in ("off", "warn", "block"):
        declared = _example(cli)
        declared["testEvidence"] = {"enforcement": mode}
        assert not cli.schema_validation_errors(declared, schema), (
            f"testEvidence.enforcement={mode!r} ships in Release 2 and must validate"
        )

    bad_mode = _example(cli)
    bad_mode["testEvidence"] = {"enforcement": "strict"}
    assert cli.schema_validation_errors(bad_mode, schema), (
        "an enum the enforcement layer does not implement must be refused at the schema, not "
        "silently normalized to a weaker mode"
    )
