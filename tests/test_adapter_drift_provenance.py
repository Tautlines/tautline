"""Task 2 (real-pypi-package plan): provenance-stamp equivalence — the mixed-mode identity fix.

The generated lane adapter (`.tautline.json`) embeds two identity stamps in `_generated`
(`methodologyCommit`, `pluginVersion`). Two runtimes at DIFFERENT identities that render
IDENTICAL content (a pip-installed wheel and a canonical checkout co-maintaining one project)
must not see each other's render as drift, and must not rewrite the file back and forth —
that is the wheel-vs-checkout ping-pong this suite kills. Equivalence is CONTENT-scoped:
every real difference (policy content, sourceAdapterSha256, hand reformatting, unparseable
or unstamped on-disk documents) still gates, fail closed.

Second decision under test: `_generated.regenerate` is rendered CONTENT and must be the
mode-independent `tautline ...` spelling, byte-identical from every renderer — a per-mode
string would reintroduce the exact ping-pong the equivalence helper removes (PP-R3-P2-2).
"""

import importlib.util
import json
import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
# Post the package-split flip (roadmap #11): bin/tautline is a thin shim; the engine lives here.
CLI_ENGINE_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
PLUGIN_MANIFEST_REL = "plugins/tautline-core/.codex-plugin/plugin.json"

# A fixed, obviously-foreign identity: what a wheel stamped by another build would carry.
FOREIGN_COMMIT = "feedfacecafe"
FOREIGN_PLUGIN_VERSION = "9.9.9"
SENTINEL_MTIME = 1_000_000_000  # any write after setup moves mtime far away from this


def _serialize(doc: dict) -> str:
    # The exact serializer render_project_config uses; equivalence is byte-strict through it.
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def _rendered_lane(cli, tmp_path):
    """A target whose generated files are freshly rendered — the zero-drift baseline."""
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


def _foreign_stamped(lane_json: Path) -> dict:
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    assert doc["_generated"]["methodologyCommit"] != FOREIGN_COMMIT
    assert doc["_generated"]["pluginVersion"] != FOREIGN_PLUGIN_VERSION
    doc["_generated"]["methodologyCommit"] = FOREIGN_COMMIT
    doc["_generated"]["pluginVersion"] = FOREIGN_PLUGIN_VERSION
    return doc


def _adapter_entries(cli, drift: list[str]) -> list[str]:
    return [entry for entry in drift if entry.startswith(cli.LANE_ADAPTER_FILE)]


# --- the equivalence gate (adapter_drift) ------------------------------------------------------


def test_stamp_only_difference_is_not_drift(cli, tmp_path):
    data, target, lane_json = _rendered_lane(cli, tmp_path)

    lane_json.write_text(_serialize(_foreign_stamped(lane_json)), encoding="utf-8")

    assert cli.adapter_drift(data, EXAMPLE_ADAPTER, target) == []


def test_content_difference_is_still_drift(cli, tmp_path):
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    fresh = lane_json.read_text(encoding="utf-8")

    # Policy content changed alongside the stamps: equivalence must NOT swallow it.
    doc = _foreign_stamped(lane_json)
    doc["commands"]["mainStatus"] = "stale command from a lagging build"
    lane_json.write_text(_serialize(doc), encoding="utf-8")
    assert _adapter_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target))

    # sourceAdapterSha256 is content (the source-adapter binding), never a stamp.
    lane_json.write_text(fresh, encoding="utf-8")
    doc = _foreign_stamped(lane_json)
    doc["_generated"]["sourceAdapterSha256"] = "0" * 64
    lane_json.write_text(_serialize(doc), encoding="utf-8")
    assert _adapter_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target))


def test_unparseable_on_disk_adapter_is_drift(cli, tmp_path):
    data, target, lane_json = _rendered_lane(cli, tmp_path)

    lane_json.write_text("{ this is not json\n", encoding="utf-8")

    assert _adapter_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target))


def test_missing_generated_block_is_drift(cli, tmp_path):
    data, target, lane_json = _rendered_lane(cli, tmp_path)

    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    del doc["_generated"]
    lane_json.write_text(_serialize(doc), encoding="utf-8")

    assert _adapter_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target))


def test_hand_reformatted_adapter_is_drift(cli, tmp_path):
    """Same JSON data, different bytes: normalization re-serializes the FRESH render through the
    canonical serializer — it never launders the on-disk formatting, so byte strictness holds."""
    data, target, lane_json = _rendered_lane(cli, tmp_path)

    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    lane_json.write_text(json.dumps(doc, indent=4, sort_keys=True) + "\n", encoding="utf-8")

    drift = cli.adapter_drift(data, EXAMPLE_ADAPTER, target)
    # Stamps agree, so this is plain drift — no misleading "different build" hint.
    assert cli.LANE_ADAPTER_FILE in drift


def test_true_drift_message_hints_at_version_alignment(cli, tmp_path):
    """Content differs AND stamps differ: the honest residual case (a render-affecting change
    shipped in one runtime but not the other). The remediation is 'align versions', never
    're-render harder' — the drift entry must say so."""
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    fresh = lane_json.read_text(encoding="utf-8")

    doc = _foreign_stamped(lane_json)
    doc["commands"]["mainStatus"] = "stale command from a lagging build"
    lane_json.write_text(_serialize(doc), encoding="utf-8")

    entries = _adapter_entries(cli, cli.adapter_drift(data, EXAMPLE_ADAPTER, target))
    assert entries
    hint = entries[0]
    assert "different methodology build" in hint
    assert "pip install -U tautline" in hint
    assert "update-repin" in hint

    # Same content change with AGREEING stamps: a plain hand-edit must NOT claim a build skew.
    doc = json.loads(fresh)
    doc["commands"]["mainStatus"] = "stale command from a lagging build"
    lane_json.write_text(_serialize(doc), encoding="utf-8")
    drift = cli.adapter_drift(data, EXAMPLE_ADAPTER, target)
    assert cli.LANE_ADAPTER_FILE in drift
    assert not any("different methodology build" in entry for entry in drift)


# --- the writers must not churn a stamp-only difference ----------------------------------------


def test_lane_start_writer_preserves_a_stamp_only_difference(cli, tmp_path):
    data, target, lane_json = _rendered_lane(cli, tmp_path)
    lane_json.write_text(_serialize(_foreign_stamped(lane_json)), encoding="utf-8")
    os.utime(lane_json, (SENTINEL_MTIME, SENTINEL_MTIME))
    before = lane_json.read_bytes()

    written, _skipped = cli.write_generated_files(data, EXAMPLE_ADAPTER, target)

    assert lane_json.read_bytes() == before
    assert lane_json.stat().st_mtime == SENTINEL_MTIME
    assert all(path.name != cli.LANE_ADAPTER_FILE for path in written)


def test_first_render_stamps_current_identity(cli, tmp_path):
    """No on-disk adapter: nothing to be equivalent TO — the first render writes the current
    runtime's truthful identity."""
    target = tmp_path / "fresh-target"
    target.mkdir()
    data = cli.load_project(EXAMPLE_ADAPTER)

    written, _skipped = cli.write_generated_files(data, EXAMPLE_ADAPTER, target)

    lane_json = target / cli.LANE_ADAPTER_FILE
    assert lane_json in written
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    assert doc["_generated"]["methodologyCommit"] == cli.running_methodology_commit(short=True)
    assert doc["_generated"]["pluginVersion"] == (
        (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    )


# --- render-adapters --write / --check ----------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _render_target(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal repo-local-adapter target that passes render-adapters' provenance checks."""
    target = tmp_path / "render-target"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for provenance-stamp equivalence coverage (Task 2).",
        "repoEvidence": [
            {
                "path": ".ai-work/bootstrap-evidence.txt",
                "fact": "Primary bootstrap evidence exists.",
            },
            {
                "path": ".ai-work/bootstrap-evidence-2.txt",
                "fact": "Secondary bootstrap evidence exists.",
            },
        ],
    }
    adapter = target / ".tautline" / "adapter.json"
    adapter.parent.mkdir()
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target, adapter


def test_render_adapters_write_skips_a_stamp_only_rewrite(run_cli, tmp_path):
    target, adapter = _render_target(tmp_path)
    first = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--write"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    lane_json = target / ".tautline.json"
    lane_json.write_text(_serialize(_foreign_stamped(lane_json)), encoding="utf-8")
    os.utime(lane_json, (SENTINEL_MTIME, SENTINEL_MTIME))
    before = lane_json.read_bytes()

    second = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--write"
    )

    assert second.returncode == 0, second.stdout + second.stderr
    assert f"wrote {lane_json}" not in second.stdout
    assert lane_json.read_bytes() == before
    assert lane_json.stat().st_mtime == SENTINEL_MTIME


def test_render_adapters_check_accepts_a_stamp_only_difference(run_cli, tmp_path):
    target, adapter = _render_target(tmp_path)
    first = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--write"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    lane_json = target / ".tautline.json"
    lane_json.write_text(_serialize(_foreign_stamped(lane_json)), encoding="utf-8")

    check = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--check"
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "drift:" not in check.stdout

    # Equivalence is stamp-scoped: a content difference under the same stamps still fails --check.
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    doc["_generated"]["sourceAdapterSha256"] = "0" * 64
    lane_json.write_text(_serialize(doc), encoding="utf-8")
    recheck = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--check"
    )
    assert recheck.returncode == 1
    assert f"drift: {lane_json}" in recheck.stdout


# --- the regenerate line is mode-independent CONTENT --------------------------------------------


def _package_mode_cli(tmp_path: Path):
    """A second CLI instance executing from a package-shaped tree: a snapshot manifest with
    installKind "package" at its root and no .git — the identity a pip-installed wheel runs
    under (running_methodology_commit reads the manifest, not git)."""
    fixture = tmp_path / "package-fixture"
    (fixture / "bin").mkdir(parents=True)
    (fixture / "bin" / "tautline").write_bytes(CLI_PATH.read_bytes())
    (fixture / "VERSION").write_bytes((REPO_ROOT / "VERSION").read_bytes())
    manifest_dest = fixture / PLUGIN_MANIFEST_REL
    manifest_dest.parent.mkdir(parents=True)
    manifest_dest.write_bytes((REPO_ROOT / PLUGIN_MANIFEST_REL).read_bytes())
    (fixture / ".snapshot-meta.json").write_text(
        json.dumps(
            {
                "schema": "tautline-snapshot/v1",
                "commit": "f" * 40,
                "shortCommit": "f" * 12,
                "version": (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                "channel": "stable",
                "installKind": "package",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Post the package-split flip (roadmap #11): the engine lives in the package. Copy cli.py into
    # the fixture's package tree and load it FROM there so its REPO_ROOT (parents[2]) bakes to the
    # fixture -- the package-shaped exec-root identity under test. Family submodules resolve via the
    # real package already on sys.path (conftest), so only cli.py needs to sit in the fixture.
    engine_dest = fixture / "src" / "tautline_methodology" / "cli.py"
    engine_dest.parent.mkdir(parents=True)
    engine_dest.write_bytes(CLI_ENGINE_PATH.read_bytes())
    loader = SourceFileLoader("tautline_package_mode_fixture", str(engine_dest))
    spec = importlib.util.spec_from_loader("tautline_package_mode_fixture", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_regenerate_line_is_mode_independent_and_runnable_from_a_wheel(cli, tmp_path):
    data = cli.load_project(EXAMPLE_ADAPTER)
    target = tmp_path / "render-root"
    target.mkdir()

    checkout_doc = json.loads(
        cli.render_project_config(
            data,
            "adapters/projects/example-saas.json",
            source_path_override=EXAMPLE_ADAPTER,
            target_root=target,
        )
    )
    checkout_regen = checkout_doc["_generated"]["regenerate"]
    # `bin/tautline` does not exist in a pipx/pip user's project; `tautline` resolves on EVERY
    # supported install (wheel console script, install-cli shim on checkout/snapshot machines).
    assert checkout_regen.startswith("tautline ")
    assert "bin/tautline" not in checkout_regen

    pkg_cli = _package_mode_cli(tmp_path)
    assert pkg_cli.running_from_snapshot(), "package fixture must execute under a manifest identity"
    pkg_doc = json.loads(
        pkg_cli.render_project_config(
            data,
            "adapters/projects/example-saas.json",
            source_path_override=EXAMPLE_ADAPTER,
            target_root=target,
        )
    )
    pkg_regen = pkg_doc["_generated"]["regenerate"]
    # The two runtimes genuinely disagree on identity (stamps differ)...
    assert (
        pkg_doc["_generated"]["methodologyCommit"]
        != checkout_doc["_generated"]["methodologyCommit"]
    )
    # ...yet the regenerate line — rendered CONTENT — is byte-identical: no per-mode string.
    assert pkg_regen == checkout_regen
    assert pkg_regen.startswith("tautline ")
