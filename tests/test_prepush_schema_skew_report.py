"""A provable adapter-schema skew reports and continues; everything else still refuses (item 1 B).

The half this suite has to get right is not the downgrade -- it is the REFUSAL. Release A made the
lane's own checkout the authority on its own schema; this release lets a *provable* stale installed
schema report-and-continue on a hook boundary instead of refusing a whole push. The obvious way to
get that wrong is to accept anything a lane asserts, so most of what follows pins the cases that
must still fail loudly, and `additionalProperties: false` is untouched throughout.

One case is worth naming because an earlier draft got it wrong and plan review caught it: a newer
`_generated.pluginVersion` proves the RENDERER was newer and proves nothing about the key. It is a
refusal-side signal here, never a downgrade proof -- otherwise a typo on any machine with a stale
install would have been excused.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from _hook_skew_fixtures import SKEW_KEY, build_real_skew_lane

REPO_ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = "(root): unknown property '{key}' (not allowed by the adapter schema)"


# --- unknown_top_level_property_keys: all-or-nothing, and that is the contract ------------------


def test_unknown_top_level_property_keys_extracts_root_keys_only(cli):
    adapter = cli.adapter_module()
    errors = [UNKNOWN.format(key="goLiveReadiness"), UNKNOWN.format(key="archetype")]
    assert adapter.unknown_top_level_property_keys(errors) == ("goLiveReadiness", "archetype")


def test_nested_unknown_property_disqualifies_the_list(cli):
    adapter = cli.adapter_module()
    nested = "(root).testEvidence: unknown property 'suites' (not allowed by the adapter schema)"
    assert adapter.unknown_top_level_property_keys([nested]) == ()


def test_mixed_error_classes_disqualify_the_list(cli):
    """One unknown key plus one type error is a broken adapter, not version skew.

    Reporting-and-continuing here would hide the type error behind the unknown key.
    """
    adapter = cli.adapter_module()
    errors = [
        UNKNOWN.format(key="goLiveReadiness"),
        "(root).project: expected type string, got int",
    ]
    assert adapter.unknown_top_level_property_keys(errors) == ()


def test_no_errors_is_not_a_skew(cli):
    assert cli.adapter_module().unknown_top_level_property_keys([]) == ()


# --- self_authoritative_schema_path: both halves, bounded, no subprocess -------------------------


def test_self_authoritative_probe_finds_the_framework_root(cli, tmp_path):
    adapter = cli.adapter_module()
    root = tmp_path / "framework"
    (root / "methodology").mkdir(parents=True)
    (root / "methodology" / "adapter-schema.json").write_text("{}", encoding="utf-8")
    (root / "src" / "tautline_methodology").mkdir(parents=True)
    (root / "src" / "tautline_methodology" / "cli.py").write_text("", encoding="utf-8")
    lane_adapter = root / ".tautline.json"
    lane_adapter.write_text("{}", encoding="utf-8")
    found = adapter.self_authoritative_schema_path(lane_adapter)
    assert found == (root / "methodology" / "adapter-schema.json").resolve()


@pytest.mark.parametrize("present", ["engine", "schema"])
def test_self_authoritative_probe_requires_engine_and_schema_together(cli, tmp_path, present):
    """A tree with the engine but no schema is not an authority on a schema it does not have."""
    adapter = cli.adapter_module()
    root = tmp_path / "half"
    root.mkdir()
    if present == "engine":
        (root / "src" / "tautline_methodology").mkdir(parents=True)
        (root / "src" / "tautline_methodology" / "cli.py").write_text("", encoding="utf-8")
    else:
        (root / "methodology").mkdir(parents=True)
        (root / "methodology" / "adapter-schema.json").write_text("{}", encoding="utf-8")
    lane_adapter = root / ".tautline.json"
    lane_adapter.write_text("{}", encoding="utf-8")
    assert adapter.self_authoritative_schema_path(lane_adapter) is None


def test_self_authoritative_probe_is_bounded(cli, tmp_path):
    """Depth-capped, so a deep tree cannot walk to the filesystem root looking for an authority."""
    adapter = cli.adapter_module()
    root = tmp_path / "framework"
    (root / "methodology").mkdir(parents=True)
    (root / "methodology" / "adapter-schema.json").write_text("{}", encoding="utf-8")
    (root / "src" / "tautline_methodology").mkdir(parents=True)
    (root / "src" / "tautline_methodology" / "cli.py").write_text("", encoding="utf-8")
    deep = root / "a" / "b" / "c" / "d" / "e" / "f" / "g"
    deep.mkdir(parents=True)
    buried = deep / ".tautline.json"
    buried.write_text("{}", encoding="utf-8")
    assert adapter.self_authoritative_schema_path(buried) is None


# --- the classifier: one downgrade proof, one refusal signal ------------------------------------


def _classify(cli, tmp_path, *, lane_declares: bool, stamped: str | None, installed: str):
    adapter = cli.adapter_module()
    installed_schema = tmp_path / "installed" / "methodology" / "adapter-schema.json"
    installed_schema.parent.mkdir(parents=True)
    installed_schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"project": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    lane_root = tmp_path / "lane"
    (lane_root / "methodology").mkdir(parents=True)
    (lane_root / "src" / "tautline_methodology").mkdir(parents=True)
    (lane_root / "src" / "tautline_methodology" / "cli.py").write_text("", encoding="utf-8")
    lane_props = {"project": {"type": "string"}}
    if lane_declares:
        lane_props["newKey"] = {"type": "object", "additionalProperties": True}
    (lane_root / "methodology" / "adapter-schema.json").write_text(
        json.dumps({"type": "object", "additionalProperties": False, "properties": lane_props}),
        encoding="utf-8",
    )
    data: dict = {"project": "x", "newKey": {"on": True}}
    if stamped is not None:
        data["_generated"] = {"pluginVersion": stamped}
    lane_adapter = lane_root / ".tautline.json"
    lane_adapter.write_text(json.dumps(data), encoding="utf-8")
    return adapter.adapter_schema_skew_classification(
        data, lane_adapter, installed_schema_path=installed_schema, installed_version=installed
    )


def test_tree_authoritative_proof_downgrades(cli, tmp_path):
    result = _classify(cli, tmp_path, lane_declares=True, stamped=None, installed="0.49.0")
    assert result is not None
    assert result["proof"] == "tree-authoritative"
    assert result["disposition"] == "downgrade"
    assert result["keys"] == ("newKey",)


def test_tree_authoritative_proof_requires_zero_tree_errors(cli, tmp_path):
    """A tree schema that ALSO rejects the adapter proves nothing; it is not an authority either."""
    result = _classify(cli, tmp_path, lane_declares=False, stamped=None, installed="0.49.0")
    assert result is None


def test_generator_newer_signal_classifies_as_refuse_not_downgrade(cli, tmp_path):
    result = _classify(cli, tmp_path, lane_declares=False, stamped="0.60.0", installed="0.49.0")
    assert result is not None
    assert result["proof"] == "generator-newer"
    assert result["disposition"] == "refuse"


def test_a_typo_under_a_newer_generator_never_downgrades(cli, tmp_path):
    """THE regression. A newer stamp is evidence about the renderer, never about the key.

    An earlier draft made this a downgrade proof: 'declared nowhere in the installed schema' is
    satisfied by a misspelling exactly as it is by a legitimate new key, so a typo on any machine
    with a stale install would have been reported-and-continued. It refuses.
    """
    result = _classify(cli, tmp_path, lane_declares=False, stamped="0.60.0", installed="0.49.0")
    assert result is not None
    assert result["disposition"] != "downgrade"


def test_lagging_generator_version_is_not_a_signal(cli, tmp_path):
    """The measured case: a framework lane stamps older than its own tree, routinely."""
    assert _classify(cli, tmp_path, lane_declares=False, stamped="0.35.3",
        installed="0.49.0") is None


def test_unprovable_unknown_key_is_not_classified(cli, tmp_path):
    assert _classify(cli, tmp_path, lane_declares=False, stamped=None, installed="0.49.0") is None


def test_classification_records_its_proof_and_its_disposition(cli, tmp_path):
    result = _classify(cli, tmp_path, lane_declares=True, stamped=None, installed="0.49.0")
    assert set(result) >= {"proof", "disposition", "keys", "installedVersion", "authority"}


def test_adapter_module_imports_stay_stdlib_only():
    """The layering invariant: adapter.py is a leaf and stays one."""
    source = (REPO_ROOT / "src" / "tautline_methodology" / "adapter.py").read_text(encoding="utf-8")
    imports = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith("import ") or (line.startswith("from ") and " import " in line)
    }
    assert imports <= {"json", "posixpath", "re", "pathlib", "__future__"}, imports


# --- the report: reachable, literal, parses, and the ORDER is the deliverable --------------------


def _report(cli, tmp_path):
    result = _classify(cli, tmp_path, lane_declares=True, stamped=None, installed="0.49.0")
    return cli.adapter_module().adapter_schema_skew_report_lines(result)


def test_skew_report_names_the_keys_and_the_proof(cli, tmp_path):
    lines = _report(cli, tmp_path)
    assert "newKey" in lines[0]
    assert "tree-authoritative" in lines[0]
    assert "downgrade" in lines[0]


def test_skew_report_has_no_metavariables(cli, tmp_path):
    for line in _report(cli, tmp_path):
        assert "<" not in line and ">" not in line, line


def test_skew_report_names_only_reachable_literal_remedies(cli, tmp_path):
    """Cross-checked here rather than in adapter.py: the leaf must not import the registry."""
    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    blocked = set(cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS)
    verbs = [line.split("tautline ")[1].split()[0] for line in _report(cli,
        tmp_path) if "tautline " in line]
    assert verbs, "the report named no remedy at all"
    for verb in verbs:
        assert verb in allowed, verb
        assert verb not in blocked, verb


def test_skew_report_flag_values_are_literal_and_parse(cli, tmp_path):
    """Every remedy actually parses. A remedy that reads fine in prose can still exit 2."""
    for line in _report(cli, tmp_path):
        if "tautline " not in line:
            continue
        argv = line.split("tautline ", 1)[1].split()
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "bin" / "tautline"), *argv, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{argv}: {result.stderr}"


def test_the_refuse_side_offers_a_hint_not_a_guaranteed_remedy(cli, tmp_path):
    """R2's P1: a typo under a newer generator must NOT be told a remedy that cannot clear it.

    `generator-newer` cannot tell a legitimate new key from a misspelled one. Printing the ordered
    sequence under a `remedy` label would promise that syncing and reinstalling fixes a
    misspelling, which it does not -- a refusal naming a remedy that does not work, which is the
    exact defect class this whole item exists to close.
    """
    result = _classify(cli, tmp_path, lane_declares=False, stamped="0.60.0", installed="0.49.0")
    assert result["disposition"] == "refuse"
    lines = cli.adapter_module().adapter_schema_skew_report_lines(result)
    body = "\n".join(lines)
    assert "adapter_schema_version_skew_remedy:" not in body, body
    assert "adapter_schema_version_skew_hint:" in body
    assert "cannot" in body and "misspelled" in body
    # Both branches named, neither promised.
    assert "fix the spelling" in body
    assert "not through this lane" in body
    # No command at all on this path: every verb re-validates the adapter and fails identically.
    assert "sync-methodology" not in body


def test_the_downgrade_remedy_never_names_a_command_that_needs_the_stale_cli(cli, tmp_path):
    """No sync in the downgrade remedy, and every command qualified to the authoritative checkout.

    Codex found the circularity this pins: `sync_methodology` calls `lane_project`, which validates
    the lane adapter -- so run from the stale install it dies with the IDENTICAL schema violation
    the remedy exists to clear. In the tree-authoritative case there is nothing to sync anyway: the
    lane's own checkout is what accepted the adapter, so it is already current. Naming a sync here
    was both useless and blocked.
    """
    lines = _report(cli, tmp_path)
    body = "\n".join(lines)
    assert "sync-methodology" not in body, body
    for line in lines[1:]:
        command = line.split("adapter_schema_version_skew_remedy: ", 1)[1]
        assert not command.startswith("tautline "), f"unqualified, PATH can reach the stale install: {command}"
        assert command.startswith("bin/tautline ") or "/bin/tautline " in command, command


def test_the_refuse_hint_names_no_command_that_runs_through_this_lane(cli, tmp_path):
    """The refuse case has no authoritative checkout, so it must not pretend one exists.

    Every verb this CLI offers re-validates the lane adapter first, so nothing run through this lane
    can clear the condition. The hint says that outright rather than naming a command that will fail
    the same way.
    """
    result = _classify(cli, tmp_path, lane_declares=False, stamped="0.60.0", installed="0.49.0")
    assert result["disposition"] == "refuse"
    body = "\n".join(cli.adapter_module().adapter_schema_skew_report_lines(result))
    assert "adapter_schema_version_skew_remedy:" not in body
    assert "sync-methodology" not in body, "a command that cannot run here must not be named"
    assert "fix the spelling" in body
    assert "not through this lane" in body


def test_skew_report_leaks_no_absolute_path(cli, tmp_path):
    """No absolute path at all, not merely no home-shaped one.

    The first version of this test checked only for `/Users/` and `/home/`, and passed while the
    report emitted an absolute path -- because pytest's tmp_path lives under `/private/var/...`,
    which matches neither. Codex caught the leak that the test was structurally unable to see. A
    hook report gets copied into CI logs and pasted into issues; the useful fact is WHICH tree
    answered, and a relative path says that without publishing the machine's layout.
    """
    for line in _report(cli, tmp_path):
        assert str(tmp_path) not in line, line
        for token in line.split():
            assert not token.startswith("/"), f"absolute path in report: {token}"


def test_fail_closed_control_entry_is_named_for_inheritance(cli):
    """FAIL_CLOSED_CONTROLS does not exist yet,
        so the entry is named where its owner will read it."""
    source = (REPO_ROOT / "src" / "tautline_methodology" / "adapter.py").read_text(encoding="utf-8")
    assert "prepush.adapter-schema-skew" in source
    assert "test_unprovable_unknown_key_still_refuses_under_the_hook_signal" in source
    assert "test_lane_adds_a_key_with_the_old_installed_cli_resolvable" in source


# --- the boundary signal and the seam ------------------------------------------------------------


def test_hook_boundary_signal_rejects_an_arbitrary_value(cli, monkeypatch):
    monkeypatch.setenv("TAUTLINE_HOOK_BOUNDARY", "anything-else")
    assert cli.hook_boundary_invocation() == ""


@pytest.mark.parametrize("hook_name", ["pre-commit", "pre-push"])
def test_hook_boundary_signal_accepts_the_two_real_hook_names(cli, monkeypatch, hook_name):
    monkeypatch.setenv("TAUTLINE_HOOK_BOUNDARY", hook_name)
    assert cli.hook_boundary_invocation() == hook_name


def test_hook_boundary_signal_is_empty_when_unset(cli, monkeypatch):
    monkeypatch.delenv("TAUTLINE_HOOK_BOUNDARY", raising=False)
    assert cli.hook_boundary_invocation() == ""


@pytest.mark.parametrize("hook_name", ["pre-commit", "pre-push"])
def test_hook_template_exports_the_boundary_for_both_hooks(cli, hook_name):
    """The literal `export` keyword, not a bare assignment.

    The neighbouring MINERVIT_WORK_PROFILE_SKIP_DEV_GATES=0 is a bare assignment read only inside
    the script; copying its form would produce a variable the child CLI never sees while a
    template-text assertion still passed.
    """
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), hook_name)
    assert f"export TAUTLINE_HOOK_BOUNDARY={hook_name}" in content


@pytest.mark.parametrize("hook_name", ["pre-commit", "pre-push"])
def test_boundary_is_unset_for_the_wrapped_backup_hook(cli, hook_name):
    """Both backup branches, because only one of them already had a subshell.

    Same hazard the template already handles for MINERVIT_PREPUSH_RECORDS_FILE, with a worse blast
    radius: a custom hook shelling out to this CLI would get downgrade semantics outside the gate
    chain that earns them.
    """
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), hook_name)
    assert content.count("unset TAUTLINE_HOOK_BOUNDARY") == 2


def test_boundary_env_name_is_not_a_managed_user_config_key(cli):
    assert "TAUTLINE_HOOK_BOUNDARY" not in set(cli.MANAGED_USER_CONFIG_ENV_KEYS)


def test_hook_invoked_command_derivation_is_unchanged(cli):
    """An env export is not a gate step, so the derived verb set gains nothing."""
    import inspect
    import re as _re

    source = inspect.getsource(cli.git_branch_liveness_hook_content)
    invoked = set(_re.findall(r"run_minervit_command '[^']*' ([a-z][a-z0-9-]*)", source))
    assert invoked <= set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    assert "sync-methodology" not in invoked


def test_hook_state_substrings_are_byte_unchanged(cli):
    """The boundary export adds no required hook STEP, so the drift gate is unmoved."""
    import inspect

    state_source = inspect.getsource(cli.git_branch_liveness_hook_state)
    for substring in (
        "work-profile-check --target . --event",
        "graphify-status --target . --strict",
        "backlog-provider-active-check",
        "guard-check --target . --boundary prepush",
    ):
        assert substring in state_source, substring
    assert "TAUTLINE_HOOK_BOUNDARY" not in state_source


# --- end to end through the real seam ------------------------------------------------------------


@pytest.fixture(scope="module")
def skew_lane(tmp_path_factory):
    return build_real_skew_lane(tmp_path_factory.mktemp("skew-report"))


def test_version_skew_report_replaces_the_bare_exit_on_the_hook_path(skew_lane):
    """With the boundary set, the OLDER install reports and continues instead of refusing."""
    result = skew_lane.run_cli(
        skew_lane.older_cli,
        "work-profile-check",
        "--target",
        ".",
        "--event",
        "pre-push",
        TAUTLINE_HOOK_BOUNDARY="pre-push",
    )
    assert "adapter_schema_version_skew:" in result.stderr, result.stderr
    assert SKEW_KEY in result.stderr
    assert "install-hooks" in result.stderr
    assert "sync-methodology" not in result.stderr


def test_version_skew_downgrade_requires_the_hook_boundary_signal(skew_lane):
    """Same fixture, signal unset: today's hard refusal, unchanged."""
    result = skew_lane.run_cli(
        skew_lane.older_cli, "work-profile-check", "--target", ".", "--event", "pre-push"
    )
    assert result.returncode != 0
    assert "not allowed by the adapter schema" in result.stderr
    assert "adapter_schema_version_skew:" not in result.stderr


def test_validate_adapter_verb_stays_strict_under_the_hook_signal(skew_lane):
    """The strict oracle does not reach the seam, so it is strict by construction."""
    result = skew_lane.run_cli(
        skew_lane.older_cli,
        "validate-adapter",
        "--project",
        str(skew_lane.lane_adapter),
        TAUTLINE_HOOK_BOUNDARY="pre-push",
    )
    assert result.returncode != 0
    assert "schema violation" in result.stderr


def test_the_refusal_carries_actionable_guidance(tmp_path):
    """The residual product-lane case, driven through the real CLI path.

    This is the test plan review R1 found missing, and the gap was real: everything else here
    checks classifier disposition or standalone report formatting, so the whole justification for
    keeping `generator-newer` -- that the refusal stops being silent about what to do -- had no
    executable proof on the path a user actually hits. R2 then corrected what it should assert, and
    R4 corrected its NAME: it pins a labelled HINT, never a remedy, because this signal cannot tell
    a new key from a misspelled one.

    The shape is a product lane: no framework engine of its own, so `tree-authoritative` cannot
    fire, and a `_generated.pluginVersion` newer than the installed CLI. The three assertions
    belong together. A report without the refusal would mean a typo got excused; a refusal without
    the report would mean the user is told no and not told what to do; and the remedy order is what
    makes the remedy work rather than merely run.
    """
    lane = build_real_skew_lane(tmp_path)
    # Strip the lane's own framework markers so the self-authority probe cannot fire -- this is a
    # product lane borrowing the fixture, not a framework checkout.
    (lane.root / "methodology" / "adapter-schema.json").unlink()
    data = json.loads(lane.lane_adapter.read_text(encoding="utf-8"))
    data["_generated"] = {**(data.get("_generated") or {}), "pluginVersion": "99.0.0"}
    lane.lane_adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    result = lane.run_cli(
        lane.older_cli,
        "work-profile-check",
        "--target",
        ".",
        "--event",
        "pre-push",
        TAUTLINE_HOOK_BOUNDARY="pre-push",
    )

    assert result.returncode != 0, f"a typo-shaped unknown key was excused:\n{result.stdout}"
    assert "not allowed by the adapter schema" in result.stderr, result.stderr
    guidance = result.stderr
    # A HINT, not a remedy. R2 of this plan's review corrected the first version of this test,
    # which asserted the ordered remedy here: `generator-newer` cannot tell a new key from a
    # misspelled one, so promising that syncing clears it would be false for exactly the typo case
    # the refusal exists to catch. What must be true is that the refusal stops being silent about
    # what to do -- and that it does not overstate what it knows.
    assert "adapter_schema_version_skew_hint:" in guidance
    assert "adapter_schema_version_skew_remedy:" not in guidance
    assert "fix the spelling" in guidance
    assert "not through this lane" in guidance
    assert "sync-methodology" not in guidance
    assert guidance.index("adapter_schema_version_skew:") < guidance.index(
        "adapter_schema_version_skew_hint:"
    )


def _classify_in_subdir(cli, tmp_path, adapter_name=".tautline.json"):
    """A lane living in a SUBDIRECTORY of the framework checkout -- the common shape."""
    adapter = cli.adapter_module()
    installed_schema = tmp_path / "installed" / "methodology" / "adapter-schema.json"
    installed_schema.parent.mkdir(parents=True)
    installed_schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"project": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "checkout"
    (root / "methodology").mkdir(parents=True)
    (root / "src" / "tautline_methodology").mkdir(parents=True)
    (root / "src" / "tautline_methodology" / "cli.py").write_text("", encoding="utf-8")
    (root / "methodology" / "adapter-schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "project": {"type": "string"},
                    "newKey": {"type": "object", "additionalProperties": True},
                },
            }
        ),
        encoding="utf-8",
    )
    lane = root / "lanes" / "one"
    lane.mkdir(parents=True)
    data = {"project": "x", "newKey": {"on": True}}
    lane_adapter = lane / adapter_name
    lane_adapter.write_text(json.dumps(data), encoding="utf-8")
    return adapter.adapter_schema_skew_classification(
        data, lane_adapter, installed_schema_path=installed_schema, installed_version="0.49.0"
    )


def test_the_remedy_resolves_from_a_lane_inside_the_checkout(cli, tmp_path):
    """The adapter is usually BELOW the checkout root, so the CLI is above the lane.

    Path.relative_to raises there, and the empty fallback printed a bare `bin/tautline` that
    resolves against the lane subdirectory -- a remedy pointing at a path that does not exist.
    posixpath.relpath emits the `../` form, which is still relative and actually resolves.
    """
    result = _classify_in_subdir(cli, tmp_path)
    assert result is not None and result["disposition"] == "downgrade"
    lines = cli.adapter_module().adapter_schema_skew_report_lines(result)
    for line in lines[1:]:
        command = line.split("adapter_schema_version_skew_remedy: ", 1)[1]
        assert command.startswith("../"), command
        assert not command.startswith("/"), command
    # And it actually points at the checkout's CLI, not at somewhere under the lane.
    lane_dir = tmp_path / "checkout" / "lanes" / "one"
    resolved = (lane_dir / lines[1].split()[1]).resolve()
    assert resolved == (tmp_path / "checkout" / "bin" / "tautline").resolve()


def test_the_remedy_names_the_lanes_own_adapter_file(cli, tmp_path):
    """Legacy lanes are still supported and still use the legacy marker.

    Hardcoding `.tautline.json` sends one of those to validate a file that is not there.
    """
    result = _classify_in_subdir(cli, tmp_path, adapter_name=".minervit-ai-delivery.json")
    assert result is not None
    body = "\n".join(cli.adapter_module().adapter_schema_skew_report_lines(result))
    assert ".minervit-ai-delivery.json" in body
    assert ".tautline.json" not in body
