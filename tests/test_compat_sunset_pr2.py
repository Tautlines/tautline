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
