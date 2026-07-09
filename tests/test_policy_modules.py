import re


def test_canonical_policy_matches_ordered_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()

    assert assembled == cli.CANONICAL_RULES.read_text(encoding="utf-8")
    assert assembled.startswith("<!-- GENERATED COMPATIBILITY SOURCE:")


def test_policy_module_manifest_shape(cli):
    manifest = cli.load_policy_modules_manifest()
    modules = manifest["modules"]

    assert manifest["generatedArtifact"] == "methodology/canonical-rules.md"
    assert manifest["generator"] == "minervit-methodology canonical-policy --write"
    assert modules[0] == "00-introduction.md"
    assert modules[-1] == "31-automation.md"
    assert len(modules) == len(set(modules))
    assert all((cli.POLICY_MODULES_DIR / module).exists() for module in modules)
    assert {path.name for path in cli.POLICY_MODULES_DIR.glob("*.md")} == set(modules)


def test_canonical_policy_command_is_stable(cli):
    manifest = cli.public_contract_manifest_data()
    commands = {item["name"]: item for item in manifest["commands"]}

    assert commands["canonical-policy"]["status"] == "stable"


def test_canonical_policy_command_check(run_cli):
    result = run_cli("canonical-policy", "--check")

    assert result.returncode == 0
    assert "canonical_policy_check: ok" in result.stdout


def test_policy_module_index_lists_manifest_modules(cli):
    index = cli.REPO_ROOT / "docs" / "reference" / "policy-module-index.md"
    text = index.read_text(encoding="utf-8")
    modules = cli.load_policy_modules_manifest()["modules"]
    linked_modules = set(re.findall(r"\.\./\.\./methodology/policy/([^)\s]+\.md)\)", text))

    assert linked_modules == set(modules)
    for module in modules:
        assert module in text


def test_canonical_policy_requires_proof_of_done_without_pending_tests(cli):
    assembled = cli.canonical_policy_text_from_modules()
    normalized = " ".join(assembled.split())

    assert "proof-of-done standard" in assembled
    assert "would make completion believable" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps, not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof of completion" in normalized


def test_canonical_policy_size_ratchet(cli):
    assembled = cli.canonical_policy_text_from_modules()

    assert len(assembled.encode("utf-8")) <= 60000


def test_canonical_policy_keeps_ops_provider_detail_out_of_core_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()
    forbidden = ("Google Chat", "S3", "CloudFront", "Baretail", "Drizzle")
    offenders = [term for term in forbidden if term in assembled]

    assert offenders == []
