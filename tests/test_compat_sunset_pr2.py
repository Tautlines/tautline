"""Compat-sunset warn stage (roadmap #16, part A) — PR 2.

The deferred-conveniences disposition (T3) plus the two P2 fixes deferred from PR 1:

- Managed-key TAUTLINE_ alias reads: every MINERVIT_ key in MANAGED_USER_CONFIG_ENV_KEYS
  resolves its TAUTLINE_ alias first from the installed config env FILE, and the residual
  MINERVIT_-only file read in effective_methodology_update_policy is closed.
- Drift-message copy: adapter_drift names the RESOLVED (possibly legacy) marker path.
- P2 #1: the durable-settings / launcher writer dual-writes the TAUTLINE_ autocompact twins,
  so claude_autocompact_env_status() self-warns zero times on a normally-provisioned startup.

The migration-report ceiling gap (P2 #2) is covered in test_release_tracks_and_migrations.py.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

util = importlib.import_module("tautline_methodology.util")

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = ROOT / "adapters" / "projects" / "example-saas.json"


@pytest.fixture(autouse=True)
def _reset_sunset():
    util._reset_sunset_state()
    yield
    util._reset_sunset_state()


def _warn_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("deprecation_warning:")]


def _serialize(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# --- T3: managed-key TAUTLINE_ alias reads (parameterized over MANAGED_USER_CONFIG_ENV_KEYS) ---


def _managed_minervit_keys(cli) -> list[str]:
    return sorted(k for k in cli.MANAGED_USER_CONFIG_ENV_KEYS if k.startswith("MINERVIT_"))


def test_managed_keys_inventory_is_nonempty(cli):
    # Guard the parameterization itself: an empty set would make every case below vacuously pass.
    assert _managed_minervit_keys(cli)


def test_managed_config_value_reads_tautline_alias_first_from_file(cli, tmp_path, monkeypatch):
    # For EVERY managed MINERVIT_ key, prove _managed_config_value reads the config FILE
    # TAUTLINE_-first (live env empty). A TAUTLINE_-only fixture is NOT enough: a MINERVIT_-first
    # regression (miss under MINERVIT_, then fall through to TAUTLINE_) would still resolve the
    # alias and pass. Writing BOTH spellings with DIFFERENT values is the load-bearing case:
    # install-cli dual-writes both, and a stale MINERVIT_ export must not win over the fresh alias.
    config = tmp_path / "tautline.env"
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", config)
    for key in _managed_minervit_keys(cli):
        alias = "TAUTLINE_" + key[len("MINERVIT_"):]
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(alias, raising=False)
        # TAUTLINE_-only: the alias resolves at all.
        config.write_text(f"export {alias}=sentinel-{key}\n", encoding="utf-8")
        assert cli._managed_config_value(key) == f"sentinel-{key}", key
        # Both spellings, different values: the fresh TAUTLINE_ alias must outrank the stale
        # MINERVIT_ export. Fails iff the file read is MINERVIT_-first.
        config.write_text(
            f"export {key}=stale-{key}\nexport {alias}=fresh-{key}\n", encoding="utf-8"
        )
        assert cli._managed_config_value(key) == f"fresh-{key}", key


def test_effective_update_policy_reads_tautline_alias_from_config_file(cli, tmp_path, monkeypatch):
    # Residual gap (PR2): the update-policy FILE read was MINERVIT_-only. A config carrying only
    # the TAUTLINE_ alias must now resolve to its policy, not fall through to the 'warn' default.
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", raising=False)
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    config = tmp_path / "tautline.env"
    config.write_text("export TAUTLINE_METHODOLOGY_UPDATE_POLICY=pinned\n", encoding="utf-8")
    assert cli.effective_methodology_update_policy(config_env=config) == "pinned"


def test_effective_update_policy_still_reads_legacy_config_file(cli, tmp_path, monkeypatch):
    # Regression guard: the legacy MINERVIT_ spelling in the file keeps resolving.
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", raising=False)
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    config = tmp_path / "methodology.env"
    config.write_text("export MINERVIT_METHODOLOGY_UPDATE_POLICY=signed\n", encoding="utf-8")
    assert cli.effective_methodology_update_policy(config_env=config) == "signed"


def test_effective_update_policy_live_tautline_alias_still_wins(cli, tmp_path, monkeypatch):
    # Live env (resolve_env, TAUTLINE_-first) outranks the file, unchanged by the file-read fix.
    monkeypatch.setenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", "unverified")
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    config = tmp_path / "tautline.env"
    config.write_text("export TAUTLINE_METHODOLOGY_UPDATE_POLICY=pinned\n", encoding="utf-8")
    assert cli.effective_methodology_update_policy(config_env=config) == "unverified"


def test_effective_update_policy_invalid_tautline_alias_does_not_fall_through(
    cli, tmp_path, monkeypatch
):
    # First-non-blank-decides contract: a NON-BLANK but INVALID TAUTLINE_ file value resolves to
    # "warn" and does NOT fall through to a valid legacy MINERVIT_ value below it. This is
    # intentional -- it mirrors the live-env path (resolve_env is set-nonblank-wins: a garbage live
    # TAUTLINE_ value also yields "warn", never a fall-through), and it is the conservative
    # direction for the --dangerously-skip-permissions interlock: an unreadable policy must fail
    # closed, never silently relax to a weaker legacy one.
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", raising=False)
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    config = tmp_path / "tautline.env"
    config.write_text(
        "export TAUTLINE_METHODOLOGY_UPDATE_POLICY=garbage\n"
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\n",
        encoding="utf-8",
    )
    assert cli.effective_methodology_update_policy(config_env=config) == "warn"


def test_effective_update_policy_valid_tautline_alias_outranks_legacy(cli, tmp_path, monkeypatch):
    # Positive twin of the first-non-blank contract: a VALID TAUTLINE_ file value outranks a
    # differing legacy MINERVIT_ value (TAUTLINE_-first among valid spellings), proving the
    # precedence is a real ordering, not an artifact of only ever writing one spelling.
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", raising=False)
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    config = tmp_path / "tautline.env"
    config.write_text(
        "export TAUTLINE_METHODOLOGY_UPDATE_POLICY=pinned\n"
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=warn\n",
        encoding="utf-8",
    )
    assert cli.effective_methodology_update_policy(config_env=config) == "pinned"


# --- T3: drift-message copy names the resolved (possibly legacy) marker path -------------------


def _rendered_lane(cli, tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    data = cli.load_project(EXAMPLE_ADAPTER)
    project_arg, override = cli.expected_files_render_context(data, EXAMPLE_ADAPTER, target)
    for rel, content in cli.expected_files(data, project_arg, override, target).items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    assert cli.adapter_drift(data, EXAMPLE_ADAPTER, target) == []
    return data, target, target / cli.LANE_ADAPTER_FILE


def _marker_entries(cli, drift):
    return [
        e
        for e in drift
        if e.startswith(cli.LANE_ADAPTER_FILE) or e.startswith(cli.LEGACY_LANE_ADAPTER_FILE)
    ]


def test_legacy_marker_in_sync_is_not_false_drift(cli, tmp_path):
    # A lane managed only via the legacy marker whose content matches the render must NOT report
    # the canonical .tautline.json as drifted (the pre-fix behavior read a non-existent canonical).
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    lane_json.rename(target / cli.LEGACY_LANE_ADAPTER_FILE)
    assert _marker_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target)) == []


def test_drift_entry_names_the_resolved_legacy_marker(cli, tmp_path):
    # When the resolved on-disk marker is the legacy file AND it has drifted, the drift entry names
    # the RESOLVED legacy path -- never the canonical constant the operator does not have on disk.
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    legacy = target / cli.LEGACY_LANE_ADAPTER_FILE
    lane_json.rename(legacy)
    doc = json.loads(legacy.read_text(encoding="utf-8"))
    doc["commands"]["mainStatus"] = "stale command from a hand edit"
    legacy.write_text(_serialize(doc), encoding="utf-8")
    drift = cli.adapter_drift(data, EXAMPLE_ADAPTER, target)
    assert any(e.startswith(cli.LEGACY_LANE_ADAPTER_FILE) for e in drift), drift
    assert not any(e.startswith(cli.LANE_ADAPTER_FILE) for e in drift), drift


def test_canonical_marker_drift_still_names_tautline(cli, tmp_path):
    # A canonical-marker repo keeps naming .tautline.json in its drift entry (no regression).
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    doc["commands"]["mainStatus"] = "stale command from a hand edit"
    lane_json.write_text(_serialize(doc), encoding="utf-8")
    drift = cli.adapter_drift(data, EXAMPLE_ADAPTER, target)
    assert any(e.startswith(cli.LANE_ADAPTER_FILE) for e in drift), drift
    assert not any(e.startswith(cli.LEGACY_LANE_ADAPTER_FILE) for e in drift), drift


# --- P2 #1: autocompact durable-settings / launcher dual-write the TAUTLINE_ twins -------------


def test_autocompact_env_keys_dual_write_tautline_twins(cli):
    keys = cli.CLAUDE_AUTOCOMPACT_ENV_KEYS
    assert keys["TAUTLINE_CLAUDE_AUTOCOMPACT_PCT"] == str(cli.DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT)
    assert keys["TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED"] == "1"
    # dual-write, not replace: the legacy spellings the older runtimes read stay present
    assert keys["MINERVIT_CLAUDE_AUTOCOMPACT_PCT"] == str(cli.DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT)
    assert keys["MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED"] == "1"


def test_autocompact_status_silent_when_writer_provisioned(cli, monkeypatch, capsys):
    # The durable-settings/launcher writer dual-writes the TAUTLINE_ autocompact twins, so a
    # normally-provisioned machine (its settings.json env loaded into the process) resolves via
    # the alias and claude_autocompact_env_status() self-warns zero times on startup. Values are
    # unchanged (85 / required).
    monkeypatch.setattr(sys, "argv", ["tautline", "methodology-status"])
    monkeypatch.delenv("CLAUDECODE", raising=False)
    for k, v in cli.CLAUDE_AUTOCOMPACT_ENV_KEYS.items():
        monkeypatch.setenv(k, v)
    desired, actual, status, required = cli.claude_autocompact_env_status()
    assert desired == str(cli.DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT)
    assert required is True
    assert not _warn_lines(capsys.readouterr().err)


def test_autocompact_status_warns_without_tautline_twins(cli, monkeypatch, capsys):
    # Control: the OLD writer behavior (only MINERVIT_ spellings present) is exactly the PR-1
    # self-warn this fix removes -- proving the silence above comes from the dual-write, not from
    # the value being unset.
    monkeypatch.setattr(sys, "argv", ["tautline", "methodology-status"])
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("TAUTLINE_CLAUDE_AUTOCOMPACT_PCT", raising=False)
    monkeypatch.delenv("TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED", raising=False)
    monkeypatch.setenv("MINERVIT_CLAUDE_AUTOCOMPACT_PCT", "85")
    monkeypatch.setenv("MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED", "1")
    cli.claude_autocompact_env_status()
    lines = _warn_lines(capsys.readouterr().err)
    assert any("MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED" in ln for ln in lines), lines


def test_launcher_dual_writes_autocompact_required_twin(cli):
    content = cli.claude_launcher_content(False)
    assert 'TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED="$MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED"' in content
    assert "export TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED" in content
    # PCT twin was already dual-written in PR1; it must stay.
    assert 'TAUTLINE_CLAUDE_AUTOCOMPACT_PCT="$MINERVIT_CLAUDE_AUTOCOMPACT_PCT"' in content
    # hook launcher variants never carry autocompact writes at all.
    assert "CLAUDE_AUTOCOMPACT_REQUIRED" not in cli.git_branch_liveness_hook_content(
        Path("/x"), "pre-commit"
    )


def test_autocompact_durable_settings_state_requires_twins(cli, tmp_path):
    # The drift detector iterates the same dict, so a settings.json the fixed writer produced is
    # 'ok' and one missing the twins is 'drift' -- keeping write + drift-check consistent.
    settings = tmp_path / "settings.json"
    cli.write_claude_autocompact_settings(settings)
    ok, _ = cli.claude_autocompact_settings_state(settings)
    assert ok
    data = json.loads(settings.read_text(encoding="utf-8"))
    del data["env"]["TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED"]
    settings.write_text(json.dumps(data), encoding="utf-8")
    ok2, detail = cli.claude_autocompact_settings_state(settings)
    assert not ok2 and "TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED" in detail
