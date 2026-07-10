"""#2 required-runtime-secret registry: the literal #448 root cause.

`process.env.X ?? ''` turned a missing required secret into a silent per-request 500, invisible to
every gate. The registry makes required secrets a declared, validated adapter concept; the fallback
detector + bounded scan flag the degrade-to-empty idiom for any registered secret, surfaced (and
blocked under enforcement=block) by methodology-status.
"""


# --- pure detector --------------------------------------------------------------------------------
def test_fallback_findings_flags_nullish_and_or_empty(cli):
    text = "const k = process.env.HMAC_KEY ?? '';\nconst j = process.env.OTHER || \"\";\n"
    assert set(cli.required_secret_fallback_findings(text, ["HMAC_KEY", "OTHER"])) == {"HMAC_KEY", "OTHER"}


def test_fallback_findings_ignores_unregistered_and_real_defaults(cli):
    text = "const a = process.env.SOMETHING ?? '';\nconst b = process.env.HMAC_KEY ?? 'real-default';\n"
    assert cli.required_secret_fallback_findings(text, ["HMAC_KEY"]) == []


def test_fallback_findings_bracket_access(cli):
    text = "const k = process.env['HMAC_KEY'] ?? \"\";"
    assert cli.required_secret_fallback_findings(text, ["HMAC_KEY"]) == ["HMAC_KEY"]


def test_fallback_findings_template_literal_empty(cli):
    # P2 fix: a template-literal empty fallback degrades to empty just like '' / "".
    text = "const k = process.env.HMAC_KEY ?? ``;"
    assert cli.required_secret_fallback_findings(text, ["HMAC_KEY"]) == ["HMAC_KEY"]


def test_fallback_findings_destructuring_default_empty(cli):
    # P2 fix: const { HMAC_KEY = '' } = process.env is the same silent degrade-to-empty.
    text = "const { HMAC_KEY = '' } = process.env;"
    assert cli.required_secret_fallback_findings(text, ["HMAC_KEY"]) == ["HMAC_KEY"]
    assert cli.required_secret_fallback_findings("const { HMAC_KEY = 'real' } = process.env;", ["HMAC_KEY"]) == []


# --- bounded scan ---------------------------------------------------------------------------------
def _adapter(secrets, enforcement="block", deployment=True):
    rc = {"enforcement": enforcement, "requiredSecrets": [{"name": s} for s in secrets]}
    d = {"runtimeConfig": rc}
    if deployment:
        d["deploymentTargets"] = [{"target": "prod", "healthCheck": "x"}]
    return d


def test_scan_flags_idiom_in_source(cli, tmp_path):
    (tmp_path / "app.ts").write_text("export const k = process.env.HMAC_KEY ?? '';\n")
    issues = cli.runtime_secret_fallback_issues(_adapter(["HMAC_KEY"]), tmp_path)
    assert any("HMAC_KEY" in i and "app.ts" in i for i in issues)


def test_scan_clean_when_no_idiom(cli, tmp_path):
    (tmp_path / "app.ts").write_text("export const k = requireEnv('HMAC_KEY');\n")
    assert cli.runtime_secret_fallback_issues(_adapter(["HMAC_KEY"]), tmp_path) == []


def test_deployment_without_registry_is_advised(cli, tmp_path):
    # A customer-facing adapter with NO required-secret registry is advised (not wedged) to declare one.
    issues = cli.runtime_secret_fallback_issues({"deploymentTargets": [{"target": "p", "healthCheck": "x"}]}, tmp_path)
    assert any("requiredSecrets" in i for i in issues)


def test_no_targets_no_registry_is_silent(cli, tmp_path):
    # A non-product repo with no targets and no registry says nothing (backward compatible).
    assert cli.runtime_secret_fallback_issues({}, tmp_path) == []


# --- normalize ------------------------------------------------------------------------------------
def test_normalize_runtime_config_rejects_bad(cli):
    import pytest
    for bad in ["nope", {"requiredSecrets": "x"}, {"requiredSecrets": [{"name": 1}]}, {"enforcement": "loud"}]:
        with pytest.raises(SystemExit):
            cli.normalize_runtime_config({"runtimeConfig": bad})


def test_normalize_runtime_config_accepts_valid(cli):
    cfg = cli.normalize_runtime_config({"runtimeConfig": {"enforcement": "block", "requiredSecrets": [{"name": "K"}]}})
    assert cfg["enforcement"] == "block" and cfg["requiredSecrets"][0]["name"] == "K"
    assert cli.normalize_runtime_config({})["enforcement"] == "warn"  # default when absent
