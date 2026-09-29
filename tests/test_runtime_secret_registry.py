"""#2 required-runtime-secret registry: the literal #448 root cause.

`process.env.X ?? ''` turned a missing required secret into a silent per-request 500, invisible to
every gate. The registry makes required secrets a declared, validated adapter concept; the fallback
detector + bounded scan flag the degrade-to-empty idiom for any registered secret, surfaced (and
blocked under enforcement=block) by methodology-status.
"""

import json
from pathlib import Path

import pytest


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


# --- the scan's ROOT, and the shapes it must survive --------------------------------------------
#
# Both classes below were live defects in the first cut of this relocation (the control moved from
# methodology-status to validate-adapter in the 2026-08-28 demolition). Neither was reachable from
# the tests above, which call the scanner directly with an explicit root and a well-formed dict --
# a shape the command itself never produces.


def _adapter_with_required_secret(cli, name="STRIPE_SECRET_KEY"):
    source = json.loads(
        (Path(cli.__file__).resolve().parents[2] / "adapters/projects/example-saas.json")
        .read_text(encoding="utf-8")
    )
    source["runtimeConfig"] = {"enforcement": "warn", "requiredSecrets": [{"name": name}]}
    return source


def test_the_scan_root_is_the_project_not_the_adapters_own_directory(cli, tmp_path):
    """A repo-local adapter lives in `<root>/.tautline/`, whose only file is the adapter itself.

    Scanning the adapter's PARENT walked that one directory and found nothing, so the #448-class
    control reported clean on every project laid out the way `init-project-adapter` scaffolds and
    the README Quickstart documents. The defect is invisible to a test that passes its own root.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "billing.ts").write_text(
        'const key = process.env.STRIPE_SECRET_KEY ?? "";\n', encoding="utf-8"
    )
    marker = tmp_path / ".tautline"
    marker.mkdir()
    adapter = marker / "adapter.json"
    adapter.write_text(json.dumps(_adapter_with_required_secret(cli)), encoding="utf-8")

    assert cli.adapter_project_root(adapter) == tmp_path.resolve()
    issues = cli.runtime_secret_fallback_issues(
        json.loads(adapter.read_text(encoding="utf-8")), cli.adapter_project_root(adapter)
    )
    assert any("STRIPE_SECRET_KEY" in issue for issue in issues), (
        "the scan must reach the project's own source, not just the adapter's directory"
    )


def test_an_adapter_at_the_root_still_scans_from_there(cli, tmp_path):
    """The other layout -- a source adapter sitting at the root -- must keep working unchanged."""
    (tmp_path / "app.ts").write_text(
        'const key = process.env.STRIPE_SECRET_KEY || "";\n', encoding="utf-8"
    )
    adapter = tmp_path / "adapter.json"
    adapter.write_text(json.dumps(_adapter_with_required_secret(cli)), encoding="utf-8")
    assert cli.adapter_project_root(adapter) == tmp_path.resolve()


@pytest.mark.parametrize(
    "runtime_config", ["nope", [1, 2], 5, True, {"requiredSecrets": 5}], ids=str
)
def test_a_malformed_runtime_config_reports_violations_instead_of_crashing(
    cli, tmp_path, runtime_config
):
    """`validate-adapter` reads the adapter RAW, so `runtimeConfig` can be any JSON value.

    Each shape here raised `TypeError` out of the `**` merge or the list comprehension, replacing
    the violation list the command exists to print with a traceback -- losing the schema errors it
    had already collected, which is the opposite of "every violation in one pass".
    """
    data = _adapter_with_required_secret(cli)
    data["runtimeConfig"] = runtime_config
    assert cli.runtime_config(data)["enforcement"] in {"warn", "block"}
    assert cli.required_secret_names(data) == [] or isinstance(
        cli.required_secret_names(data), list
    )
    assert cli.runtime_secret_fallback_issues(data, tmp_path) == []


def test_a_top_level_non_object_adapter_does_not_crash_the_scan(cli, tmp_path):
    for value in ([], "string", 7, None):
        assert cli.runtime_secret_fallback_issues(value, tmp_path) == []
