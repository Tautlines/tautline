import hashlib
import json
import os
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from minervit_methodology import public_release

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"
SRC_ROOT = CLI_PATH.parents[1] / "src"


def _copy_cli_with_package(source: Path) -> Path:
    """Copy bin/minervit-methodology alongside its required src/minervit_methodology
    package into `source`. Note: the copied-bin-without-src execution mode is not
    supported for extracted helpers, so any fixture that runs a copied CLI end-to-end
    must bring the package with it."""
    cli_path = source / "bin" / "tautline"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text(CLI_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(SRC_ROOT, source / "src")
    return cli_path


def _symlink_or_skip(target: str, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable in this test environment: {exc}")


def _next_minor(version: str) -> str:
    major, minor, *_rest = [int(part) for part in version.split(".")]
    return f"{major}.{minor + 1}.0"


def _next_patch(version: str) -> str:
    major, minor, patch = [int(part) for part in version.split(".")]
    return f"{major}.{minor}.{patch + 1}"


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _init_example_saas_repo(path: Path) -> Path:
    remote = path / "example-org" / "example-saas.git"
    target = path / "adopter"
    remote.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", str(remote)], check=True)
    (target / "README.md").write_text("# Example\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(target), "push", "-q", "-u", "origin", "main"], check=True)
    return target


PUBLIC_EXPORT_MARKER = Path(__file__).resolve().parents[1] / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; the export tree has no private history to block",
)


def _known_public_release_private_terms() -> str:
    return "But" "cher,Fi" "nch,economics" "-engine,Economics " "Engine,AP" "D,apd" "-alpha"


def test_framework_pin_defaults_to_stable_manual(cli):
    pin = cli.normalize_framework_pin(None)

    assert pin == {
        "channel": "stable",
        "version": "",
        "updatePolicy": "manual",
        "migrationPolicy": "dry-run",
    }


def test_set_framework_channel_writes_repo_local_pin(run_cli, tmp_path):
    res = run_cli("set-framework-channel", "--target", str(tmp_path), "experimental")

    assert res.returncode == 0, res.stderr
    pin = json.loads((tmp_path / ".minervit" / "pin.json").read_text(encoding="utf-8"))
    assert pin["channel"] == "experimental"
    assert pin["updatePolicy"] == "manual"
    assert "framework_pin: channel=experimental" in res.stdout


def test_set_framework_channel_adapter_updates_source_and_generated_adapter(run_cli, cli, tmp_path):
    target = _init_example_saas_repo(tmp_path)
    source = target / ".tautline" / "adapter.json"

    migrated = run_cli(
        "migrate-adapter",
        str(cli.REPO_ROOT / "adapters/projects/example-saas.json"),
        "--adopter-target",
        str(target),
        "--write",
    )
    assert migrated.returncode == 0, migrated.stderr

    rendered = run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert rendered.returncode == 0, rendered.stderr

    res = run_cli("set-framework-channel", "--target", str(target), "--source", "adapter", "experimental")

    assert res.returncode == 0, res.stderr
    adapter = json.loads(source.read_text(encoding="utf-8"))
    generated = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert adapter["_framework"]["channel"] == "experimental"
    assert generated["_framework"]["channel"] == "experimental"
    assert generated["_generated"]["sourceAdapter"] == ".tautline/adapter.json"
    assert generated["_generated"]["sourceAdapterSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert not (target / ".minervit" / "pin.json").exists()
    assert f"framework_adapter_written: {source}" in res.stdout
    assert "framework_pin: channel=experimental" in res.stdout
    assert "framework_channel_safety: stable is the default" in res.stdout


def test_set_framework_channel_adapter_aligns_existing_lane_pin(run_cli, cli, tmp_path):
    target = _init_example_saas_repo(tmp_path)
    source = target / ".tautline" / "adapter.json"

    migrated = run_cli(
        "migrate-adapter",
        str(cli.REPO_ROOT / "adapters/projects/example-saas.json"),
        "--adopter-target",
        str(target),
        "--write",
    )
    assert migrated.returncode == 0, migrated.stderr
    rendered = run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert rendered.returncode == 0, rendered.stderr
    pinned = run_cli("set-framework-channel", "--target", str(target), "stable")
    assert pinned.returncode == 0, pinned.stderr

    res = run_cli("set-framework-channel", "--target", str(target), "--source", "adapter", "experimental")

    assert res.returncode == 0, res.stderr
    adapter = json.loads(source.read_text(encoding="utf-8"))
    generated = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    pin = json.loads((target / ".minervit" / "pin.json").read_text(encoding="utf-8"))
    assert adapter["_framework"]["channel"] == "experimental"
    assert generated["_framework"]["channel"] == "experimental"
    assert pin["channel"] == "experimental"
    assert "framework_pin_aligned:" in res.stdout
    assert "framework_pin: channel=experimental" in res.stdout


def test_set_framework_channel_adapter_invalid_pin_writes_nothing(run_cli, cli, tmp_path):
    target = _init_example_saas_repo(tmp_path)
    source = target / ".tautline" / "adapter.json"

    migrated = run_cli(
        "migrate-adapter",
        str(cli.REPO_ROOT / "adapters/projects/example-saas.json"),
        "--adopter-target",
        str(target),
        "--write",
    )
    assert migrated.returncode == 0, migrated.stderr
    rendered = run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert rendered.returncode == 0, rendered.stderr
    pin_path = target / ".minervit" / "pin.json"
    pin_path.parent.mkdir(exist_ok=True)
    pin_path.write_text("{bad", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    generated_path = target / ".tautline.json"
    before_generated = generated_path.read_text(encoding="utf-8")
    before_pin = pin_path.read_text(encoding="utf-8")

    res = run_cli("set-framework-channel", "--target", str(target), "--source", "adapter", "experimental")

    assert res.returncode != 0
    assert "framework pin file is not valid JSON" in res.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert generated_path.read_text(encoding="utf-8") == before_generated
    assert pin_path.read_text(encoding="utf-8") == before_pin


def test_set_framework_channel_adapter_mode_fails_without_repo_local_adapter(run_cli, tmp_path):
    res = run_cli("set-framework-channel", "--target", str(tmp_path), "--source", "adapter", "experimental")

    assert res.returncode != 0
    assert "framework adapter not found" in res.stderr
    assert "lane-local pin" in res.stderr


def test_set_framework_channel_adapter_path_must_stay_under_target(run_cli, cli, tmp_path):
    shared_adapter = cli.REPO_ROOT / "adapters/projects/example-saas.json"
    before = shared_adapter.read_text(encoding="utf-8")

    res = run_cli(
        "set-framework-channel",
        "--target",
        str(tmp_path),
        "--source",
        "adapter",
        "--adapter-path",
        str(shared_adapter),
        "experimental",
    )

    assert res.returncode != 0
    assert "framework adapter path must stay inside the target repo" in res.stderr
    assert shared_adapter.read_text(encoding="utf-8") == before


def test_set_framework_channel_adapter_rolls_back_source_when_render_fails(cli, tmp_path, monkeypatch):
    target = tmp_path / "repo"
    source = target / ".minervit" / "adapter.json"
    source.parent.mkdir(parents=True)
    before = json.dumps({"_framework": {"channel": "stable"}}, indent=2) + "\n"
    source.write_text(before, encoding="utf-8")
    monkeypatch.setattr(cli, "validate_migrated_adapter_payload", lambda _data, _label: None)
    monkeypatch.setattr(cli, "is_repo_local_source_adapter", lambda path, repo: path == source and repo == target)

    def fail_render(_args):
        raise SystemExit("render failed")

    monkeypatch.setattr(cli, "render_adapters", fail_render)

    with pytest.raises(SystemExit, match="render failed"):
        cli.write_framework_channel_to_adapter(target, "experimental")

    assert source.read_text(encoding="utf-8") == before


def test_experimental_channel_maps_to_experimental_release_branch(cli, monkeypatch):
    def fake_run_git(_target, args):
        if args == ["remote", "get-url", "origin"]:
            return "https://example.invalid/methodology.git"
        return "unavailable"

    monkeypatch.setattr(cli, "run_git", fake_run_git)

    assert cli.methodology_release_upstream("experimental") == ("origin", "experimental", "origin/experimental")
    assert cli.methodology_release_upstream("stable") == ("origin", "main", "origin/main")


def test_wip_blocks_minor_auto_update(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "invoked_from_methodology_repo", lambda: False)
    data = {"laneState": dict(cli.DEFAULT_LANE_STATE)}
    goal_path = tmp_path / data["laneState"]["goalRun"]
    goal_path.parent.mkdir(parents=True)
    goal_path.write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", _next_minor(cli.methodology_version()))
    pin = {
        "channel": "experimental",
        "version": "",
        "updatePolicy": "patch-auto",
        "migrationPolicy": "dry-run",
    }

    decision = cli.framework_update_decision(pin, data, tmp_path)

    assert decision["action"] == "skip"
    assert "active work blocks automatic minor" in decision["reason"]
    assert any("goal ledger active" in reason for reason in decision["wipReasons"])


def test_methodology_repo_invocation_skips_auto_update(cli, tmp_path):
    data = {"repo": "minervit/minervit-ai-delivery-methodology", "laneState": dict(cli.DEFAULT_LANE_STATE)}
    pin = {
        "channel": "stable",
        "version": "",
        "updatePolicy": "manual",
        "migrationPolicy": "dry-run",
    }

    decision = cli.framework_update_decision(pin, data, cli.REPO_ROOT)

    assert decision["action"] == "skip"
    assert "uses the current checkout without auto-update" in decision["reason"]


def test_explicit_external_target_updates_even_when_invoked_from_methodology_repo(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "invoked_from_methodology_repo", lambda: True)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", _next_patch(cli.methodology_version()))
    data = {"laneState": dict(cli.DEFAULT_LANE_STATE)}
    pin = {
        "channel": "experimental",
        "version": "",
        "updatePolicy": "patch-auto",
        "migrationPolicy": "dry-run",
    }

    decision = cli.framework_update_decision(pin, data, tmp_path, manual_request=True)

    assert decision["action"] == "update"
    assert "permits patch update" in decision["reason"]


def test_wip_patch_auto_requires_wip_safe_report(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "invoked_from_methodology_repo", lambda: False)
    data = {"laneState": dict(cli.DEFAULT_LANE_STATE)}
    goal_path = tmp_path / data["laneState"]["goalRun"]
    goal_path.parent.mkdir(parents=True)
    goal_path.write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
    patch_version = _next_patch(cli.methodology_version())
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", patch_version)
    pin = {
        "channel": "experimental",
        "version": "",
        "updatePolicy": "patch-auto",
        "migrationPolicy": "dry-run",
    }

    blocked = cli.framework_update_decision(pin, data, tmp_path)
    assert blocked["action"] == "skip"
    assert "wipSafe=true" in blocked["reason"]

    monkeypatch.setattr(cli, "load_release_migration_report", lambda version: {"version": version, "wipSafe": True})
    allowed = cli.framework_update_decision(pin, data, tmp_path)
    assert allowed["action"] == "update"


def test_checkout_hygiene_warning_flags_non_main_checkout(cli, monkeypatch):
    def fake_run_git(_target, args):
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return "true"
        if args == ["branch", "--show-current"]:
            return "feature/open-source-readiness"
        if args == ["status", "--porcelain"]:
            return ""
        return "unavailable"

    monkeypatch.setattr(cli, "run_git", fake_run_git)
    monkeypatch.delenv("MINERVIT_METHODOLOGY_ALLOW_NON_MAIN", raising=False)

    warning = cli.methodology_checkout_hygiene_warning()

    assert "feature/open-source-readiness" in warning
    assert "will not auto-rescue" in warning


def test_checkout_hygiene_warning_flags_dirty_checkout(cli, monkeypatch):
    def fake_run_git(_target, args):
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return "true"
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["status", "--porcelain"]:
            return " M bin/minervit-methodology"
        return "unavailable"

    monkeypatch.setattr(cli, "run_git", fake_run_git)

    warning = cli.methodology_checkout_hygiene_warning()

    assert "local changes" in warning
    assert "will not auto-rescue" in warning


def test_migrate_adapter_dry_run_write_and_idempotency(cli, run_cli, tmp_path):
    source = Path("adapters/projects/example-saas.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.pop("_framework", None)
    payload["goalTracker"] = cli.goal_tracker_from_backlog_provider(payload["backlogProvider"])
    adapter = tmp_path / "adapter.json"
    adapter.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = adapter.read_text(encoding="utf-8")

    dry = run_cli("migrate-adapter", str(adapter))

    assert dry.returncode == 0, dry.stderr
    assert "migrate_adapter_mode: dry-run" in dry.stdout
    assert "migrate_adapter_format: deterministic JSON normalization may reorder keys" in dry.stdout
    assert "migrate_adapter_written: no" in dry.stdout
    assert adapter.read_text(encoding="utf-8") == before

    written = run_cli("migrate-adapter", str(adapter), "--write")
    assert written.returncode == 0, written.stderr
    migrated = json.loads(adapter.read_text(encoding="utf-8"))
    assert "_framework" in migrated
    assert "backlogProvider" in migrated
    assert "goalTracker" not in migrated

    second = run_cli("migrate-adapter", str(adapter), "--write")
    assert second.returncode == 0, second.stderr
    assert "migrate_adapter_diff: clean" in second.stdout
    assert json.loads(adapter.read_text(encoding="utf-8")) == migrated


def test_public_contract_marks_hooks_internal_and_goal_tracker_deprecated(cli):
    manifest = cli.public_contract_manifest_data()
    commands = {item["name"]: item for item in manifest["commands"]}
    adapter_keys = {item["name"]: item for item in manifest["adapterKeys"]}
    skills = {item["name"]: item for item in manifest["skills"]}

    assert commands["plan-finalization-hook"]["status"] == "internal"
    assert commands["public-release-check"]["status"] == "experimental"
    assert commands["blocker-declare"]["status"] == "experimental"
    assert commands["blocker-status"]["status"] == "experimental"
    assert commands["blocker-clear"]["status"] == "experimental"
    assert commands["guard-check"]["status"] == "experimental"
    assert commands["goal-tracker-next"]["status"] == "deprecated"
    assert commands["goal-tracker-next"]["replacement"] == "backlog-provider-next"
    assert adapter_keys["_framework"]["status"] == "stable"
    assert adapter_keys["responseGuard"]["status"] == "internal"
    assert adapter_keys["goalTracker"]["status"] == "deprecated"
    assert skills["framework-intake"]["status"] == "stable"
    assert "methodology-regression-rca" not in skills
    assert skills["rules-audit"]["status"] == "deprecated"
    assert skills["rules-audit"]["replacement"] == "framework-intake"


def test_release_migration_report_is_release_specific(cli):
    current = cli.release_migration_report_data(version="0.6.127", products_tested=["methodology-framework"])
    assert current["version"] == "0.6.127"
    assert current["wipSafe"] is False
    assert any(item["id"] == "t0-review-budget-zero" for item in current["requiredMigrations"])
    assert not any("claude_transport_failure" in change for change in current["behaviorChanges"])

    previous = cli.release_migration_report_data(version="0.6.126", products_tested=["example-saas"])
    assert previous["wipSafe"] is True
    assert any("claude_transport_failure" in change for change in previous["behaviorChanges"])

    current_red_flags = cli.release_migration_report_data(version="0.6.149", products_tested=["example-saas"])
    assert current_red_flags["version"] == "0.6.149"
    assert current_red_flags["wipSafe"] is False
    assert any("Stop And Deferral Red Flags policy" in change for change in current_red_flags["behaviorChanges"])
    assert current_red_flags["requiredMigrations"] == []

    current_ops_split = cli.release_migration_report_data(version="0.6.150", products_tested=["example-saas"])
    assert current_ops_split["version"] == "0.6.150"
    assert current_ops_split["wipSafe"] is False
    assert current_ops_split["requiredMigrations"] == []
    assert any("minervit-delivery-ops" in change for change in current_ops_split["behaviorChanges"])
    assert any(item["id"] == "install-minervit-delivery-ops-plugin" for item in current_ops_split["optionalMigrations"])
    assert any("not WIP-safe" in note for note in current_ops_split["rollbackNotes"])

    current_renderer_cache = cli.release_migration_report_data(version="0.6.151", products_tested=["example-saas"])
    assert current_renderer_cache["version"] == "0.6.151"
    assert current_renderer_cache["wipSafe"] is False
    assert current_renderer_cache["requiredMigrations"] == []
    assert any("~/.local/state/minervit/renderer-kit" in change for change in current_renderer_cache["behaviorChanges"])
    assert any(item["id"] == "run-iteration-review-renderer-setup" for item in current_renderer_cache["optionalMigrations"])
    assert any("not WIP-safe" in note for note in current_renderer_cache["rollbackNotes"])

    current_release_check = cli.release_migration_report_data(version="0.6.152", products_tested=["example-saas"])
    assert current_release_check["version"] == "0.6.152"
    assert current_release_check["wipSafe"] is True
    assert current_release_check["requiredMigrations"] == []
    assert current_release_check["optionalMigrations"] == []
    assert any("public-release-check" in change for change in current_release_check["behaviorChanges"])
    assert any("WIP-safe" in note for note in current_release_check["rollbackNotes"])

    current_skill_merge = cli.release_migration_report_data(version="0.6.153", products_tested=["example-saas"])
    assert current_skill_merge["version"] == "0.6.153"
    assert current_skill_merge["wipSafe"] is False
    assert current_skill_merge["requiredMigrations"] == []
    assert any("early-warning-smoke" in change for change in current_skill_merge["behaviorChanges"])
    assert any(
        item["name"] == "early-warning-smoke" and item["status"] == "experimental-removal"
        for item in current_skill_merge["deprecatedSurfaces"]
    )
    assert any(item["id"] == "replace-early-warning-smoke-skill-reference" for item in current_skill_merge["optionalMigrations"])
    assert any("not WIP-safe" in note for note in current_skill_merge["rollbackNotes"])

    current_visibility_merge = cli.release_migration_report_data(version="0.6.154", products_tested=["example-saas"])
    assert current_visibility_merge["version"] == "0.6.154"
    assert current_visibility_merge["wipSafe"] is False
    assert current_visibility_merge["requiredMigrations"] == []
    assert any("operator-visibility" in change for change in current_visibility_merge["behaviorChanges"])
    assert any(
        item["name"] == "operator-visibility" and item["status"] == "experimental-removal"
        for item in current_visibility_merge["deprecatedSurfaces"]
    )
    assert any(item["id"] == "replace-operator-visibility-skill-reference" for item in current_visibility_merge["optionalMigrations"])
    assert any("not WIP-safe" in note for note in current_visibility_merge["rollbackNotes"])

    current_document_merge = cli.release_migration_report_data(version="0.6.155", products_tested=["example-saas"])
    assert current_document_merge["version"] == "0.6.155"
    assert current_document_merge["wipSafe"] is False
    assert current_document_merge["requiredMigrations"] == []
    assert any("document-context-budget" in change for change in current_document_merge["behaviorChanges"])
    assert any(
        item["name"] == "document-context-budget" and item["status"] == "experimental-removal"
        for item in current_document_merge["deprecatedSurfaces"]
    )
    assert any(item["id"] == "replace-document-context-budget-skill-reference" for item in current_document_merge["optionalMigrations"])
    assert any("not WIP-safe" in note for note in current_document_merge["rollbackNotes"])

    current_framework_intake_merge = cli.release_migration_report_data(version="0.6.156", products_tested=["example-saas"])
    assert current_framework_intake_merge["version"] == "0.6.156"
    assert current_framework_intake_merge["wipSafe"] is False
    assert current_framework_intake_merge["requiredMigrations"] == []
    assert any("methodology-feature-request" in change for change in current_framework_intake_merge["behaviorChanges"])
    assert any(
        item["name"] == "methodology-feature-request" and item["status"] == "experimental-removal"
        for item in current_framework_intake_merge["deprecatedSurfaces"]
    )
    assert any(
        item["id"] == "replace-methodology-feature-request-skill-reference"
        for item in current_framework_intake_merge["optionalMigrations"]
    )
    assert any("not WIP-safe" in note for note in current_framework_intake_merge["rollbackNotes"])

    current_review_merge = cli.release_migration_report_data(version="0.6.157", products_tested=["example-saas"])
    assert current_review_merge["version"] == "0.6.157"
    assert current_review_merge["wipSafe"] is False
    assert current_review_merge["requiredMigrations"] == []
    assert any("review-before-push now owns" in change for change in current_review_merge["behaviorChanges"])
    assert any(
        item["name"] == "native-review-checklist" and item["status"] == "experimental-removal"
        for item in current_review_merge["deprecatedSurfaces"]
    )
    assert any(
        item["name"] == "plan-review-loop" and item["status"] == "experimental-removal"
        for item in current_review_merge["deprecatedSurfaces"]
    )
    assert any(
        item["id"] == "replace-native-review-checklist-skill-reference"
        for item in current_review_merge["optionalMigrations"]
    )
    assert any(
        item["id"] == "replace-plan-review-loop-skill-reference"
        for item in current_review_merge["optionalMigrations"]
    )
    assert any("not WIP-safe" in note for note in current_review_merge["rollbackNotes"])

    current_bootstrap_thin = cli.release_migration_report_data(version="0.6.177", products_tested=["example-saas"])
    assert current_bootstrap_thin["version"] == "0.6.177"
    assert current_bootstrap_thin["wipSafe"] is False
    assert current_bootstrap_thin["requiredMigrations"] == []
    assert current_bootstrap_thin["optionalMigrations"] == []
    assert any("Unmanaged Project Bootstrap policy" in change for change in current_bootstrap_thin["behaviorChanges"])
    assert any("470-word" in change for change in current_bootstrap_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_bootstrap_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_bootstrap_thin["rollbackNotes"])

    current_lifecycle_background_thin = cli.release_migration_report_data(version="0.6.178", products_tested=["example-saas"])
    assert current_lifecycle_background_thin["version"] == "0.6.178"
    assert current_lifecycle_background_thin["wipSafe"] is False
    assert current_lifecycle_background_thin["requiredMigrations"] == []
    assert current_lifecycle_background_thin["optionalMigrations"] == []
    assert any("Lane Lifecycle policy" in change for change in current_lifecycle_background_thin["behaviorChanges"])
    assert any("Background Work policy" in change for change in current_lifecycle_background_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_lifecycle_background_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_lifecycle_background_thin["rollbackNotes"])

    current_board_backlog_thin = cli.release_migration_report_data(version="0.6.179", products_tested=["example-saas"])
    assert current_board_backlog_thin["version"] == "0.6.179"
    assert current_board_backlog_thin["wipSafe"] is False
    assert current_board_backlog_thin["requiredMigrations"] == []
    assert current_board_backlog_thin["optionalMigrations"] == []
    assert any("Backlog Provider Intake And Grooming policy" in change for change in current_board_backlog_thin["behaviorChanges"])
    assert any("Board Currency And Subtask Status policy" in change for change in current_board_backlog_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_board_backlog_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_board_backlog_thin["rollbackNotes"])

    current_background_continuity_thin = cli.release_migration_report_data(version="0.6.180", products_tested=["example-saas"])
    assert current_background_continuity_thin["version"] == "0.6.180"
    assert current_background_continuity_thin["wipSafe"] is False
    assert current_background_continuity_thin["requiredMigrations"] == []
    assert current_background_continuity_thin["optionalMigrations"] == []
    assert any("Background Work policy" in change for change in current_background_continuity_thin["behaviorChanges"])
    assert any("Context Continuity policy" in change for change in current_background_continuity_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_background_continuity_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_background_continuity_thin["rollbackNotes"])

    current_goal_orchestration_thin = cli.release_migration_report_data(version="0.6.181", products_tested=["example-saas"])
    assert current_goal_orchestration_thin["version"] == "0.6.181"
    assert current_goal_orchestration_thin["wipSafe"] is False
    assert current_goal_orchestration_thin["requiredMigrations"] == []
    assert current_goal_orchestration_thin["optionalMigrations"] == []
    assert any("Goal Orchestration policy" in change for change in current_goal_orchestration_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_goal_orchestration_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_goal_orchestration_thin["rollbackNotes"])

    current_backlog_provider_thin_2 = cli.release_migration_report_data(version="0.6.182", products_tested=["example-saas"])
    assert current_backlog_provider_thin_2["version"] == "0.6.182"
    assert current_backlog_provider_thin_2["wipSafe"] is False
    assert current_backlog_provider_thin_2["requiredMigrations"] == []
    assert current_backlog_provider_thin_2["optionalMigrations"] == []
    assert any("Backlog Provider Intake And Grooming policy" in change for change in current_backlog_provider_thin_2["behaviorChanges"])
    assert any("580-word" in change for change in current_backlog_provider_thin_2["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_backlog_provider_thin_2["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_backlog_provider_thin_2["rollbackNotes"])

    current_context_continuity_thin_2 = cli.release_migration_report_data(version="0.6.183", products_tested=["example-saas"])
    assert current_context_continuity_thin_2["version"] == "0.6.183"
    assert current_context_continuity_thin_2["wipSafe"] is False
    assert current_context_continuity_thin_2["requiredMigrations"] == []
    assert current_context_continuity_thin_2["optionalMigrations"] == []
    assert any("Context Continuity policy" in change for change in current_context_continuity_thin_2["behaviorChanges"])
    assert any("590-word" in change for change in current_context_continuity_thin_2["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_context_continuity_thin_2["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_context_continuity_thin_2["rollbackNotes"])

    current_validate_disposition = cli.release_migration_report_data(version="0.6.184", products_tested=["example-saas"])
    assert current_validate_disposition["version"] == "0.6.184"
    assert current_validate_disposition["wipSafe"] is True
    assert current_validate_disposition["requiredMigrations"] == []
    assert current_validate_disposition["optionalMigrations"] == []
    assert any("validate-sh-disposition.md" in change for change in current_validate_disposition["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_validate_disposition["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_validate_disposition["rollbackNotes"])

    current_goal_orchestration_port = cli.release_migration_report_data(version="0.6.185", products_tested=["example-saas"])
    assert current_goal_orchestration_port["version"] == "0.6.185"
    assert current_goal_orchestration_port["wipSafe"] is True
    assert current_goal_orchestration_port["requiredMigrations"] == []
    assert current_goal_orchestration_port["optionalMigrations"] == []
    assert any("test_goal_orchestration_cli.py" in change for change in current_goal_orchestration_port["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_goal_orchestration_port["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_goal_orchestration_port["rollbackNotes"])

    current_release_change_contract = cli.release_migration_report_data(version="0.6.186", products_tested=["example-saas"])
    assert current_release_change_contract["version"] == "0.6.186"
    assert current_release_change_contract["wipSafe"] is True
    assert current_release_change_contract["requiredMigrations"] == []
    assert current_release_change_contract["optionalMigrations"] == []
    assert any("test_release_change_contract.py" in change for change in current_release_change_contract["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_release_change_contract["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_release_change_contract["rollbackNotes"])

    current_plan_finalization_hook = cli.release_migration_report_data(version="0.6.187", products_tested=["example-saas"])
    assert current_plan_finalization_hook["version"] == "0.6.187"
    assert current_plan_finalization_hook["wipSafe"] is True
    assert current_plan_finalization_hook["requiredMigrations"] == []
    assert current_plan_finalization_hook["optionalMigrations"] == []
    assert any("test_plan_finalization_hook.py" in change for change in current_plan_finalization_hook["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_plan_finalization_hook["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_plan_finalization_hook["rollbackNotes"])

    current_proof_of_done = cli.release_migration_report_data(version="0.6.188", products_tested=["example-saas"])
    assert current_proof_of_done["version"] == "0.6.188"
    assert current_proof_of_done["wipSafe"] is True
    assert current_proof_of_done["requiredMigrations"] == []
    assert current_proof_of_done["optionalMigrations"] == []
    assert any("proof-of-done standard" in change for change in current_proof_of_done["behaviorChanges"])
    assert any("pending, skipped" in change for change in current_proof_of_done["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_proof_of_done["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_proof_of_done["rollbackNotes"])

    current_policy_ratchet = cli.release_migration_report_data(version="0.6.189", products_tested=["example-saas"])
    assert current_policy_ratchet["version"] == "0.6.189"
    assert current_policy_ratchet["wipSafe"] is True
    assert current_policy_ratchet["requiredMigrations"] == []
    assert current_policy_ratchet["optionalMigrations"] == []
    assert any("78000 bytes" in change for change in current_policy_ratchet["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet["rollbackNotes"])

    current_policy_ratchet_75kb = cli.release_migration_report_data(version="0.6.190", products_tested=["example-saas"])
    assert current_policy_ratchet_75kb["version"] == "0.6.190"
    assert current_policy_ratchet_75kb["wipSafe"] is True
    assert current_policy_ratchet_75kb["requiredMigrations"] == []
    assert current_policy_ratchet_75kb["optionalMigrations"] == []
    assert any("75000 bytes" in change for change in current_policy_ratchet_75kb["behaviorChanges"])
    assert any("@pending tests" in change for change in current_policy_ratchet_75kb["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_75kb["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_75kb["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_75kb["rollbackNotes"])

    current_policy_ratchet_73500 = cli.release_migration_report_data(version="0.6.191", products_tested=["example-saas"])
    assert current_policy_ratchet_73500["version"] == "0.6.191"
    assert current_policy_ratchet_73500["wipSafe"] is True
    assert current_policy_ratchet_73500["requiredMigrations"] == []
    assert current_policy_ratchet_73500["optionalMigrations"] == []
    assert any("73500 bytes" in change for change in current_policy_ratchet_73500["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_73500["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_73500["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_73500["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_73500["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_73500["rollbackNotes"])

    current_policy_ratchet_72350 = cli.release_migration_report_data(version="0.6.192", products_tested=["example-saas"])
    assert current_policy_ratchet_72350["version"] == "0.6.192"
    assert current_policy_ratchet_72350["wipSafe"] is True
    assert current_policy_ratchet_72350["requiredMigrations"] == []
    assert current_policy_ratchet_72350["optionalMigrations"] == []
    assert any("72350 bytes" in change for change in current_policy_ratchet_72350["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_72350["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_72350["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_72350["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_72350["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_72350["rollbackNotes"])

    current_policy_ratchet_71500 = cli.release_migration_report_data(version="0.6.193", products_tested=["example-saas"])
    assert current_policy_ratchet_71500["version"] == "0.6.193"
    assert current_policy_ratchet_71500["wipSafe"] is True
    assert current_policy_ratchet_71500["requiredMigrations"] == []
    assert current_policy_ratchet_71500["optionalMigrations"] == []
    assert any("71500 bytes" in change for change in current_policy_ratchet_71500["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_71500["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_71500["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_71500["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_71500["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_71500["rollbackNotes"])

    current_policy_ratchet_70000 = cli.release_migration_report_data(version="0.6.194", products_tested=["example-saas"])
    assert current_policy_ratchet_70000["version"] == "0.6.194"
    assert current_policy_ratchet_70000["wipSafe"] is True
    assert current_policy_ratchet_70000["requiredMigrations"] == []
    assert current_policy_ratchet_70000["optionalMigrations"] == []
    assert any("70000 bytes" in change for change in current_policy_ratchet_70000["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_70000["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_70000["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_70000["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_70000["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_70000["rollbackNotes"])

    current_policy_ratchet_69000 = cli.release_migration_report_data(version="0.6.195", products_tested=["example-saas"])
    assert current_policy_ratchet_69000["version"] == "0.6.195"
    assert current_policy_ratchet_69000["wipSafe"] is True
    assert current_policy_ratchet_69000["requiredMigrations"] == []
    assert current_policy_ratchet_69000["optionalMigrations"] == []
    assert any("69000 bytes" in change for change in current_policy_ratchet_69000["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_69000["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_69000["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_69000["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_69000["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_69000["rollbackNotes"])

    current_policy_ratchet_68500 = cli.release_migration_report_data(version="0.6.196", products_tested=["example-saas"])
    assert current_policy_ratchet_68500["version"] == "0.6.196"
    assert current_policy_ratchet_68500["wipSafe"] is True
    assert current_policy_ratchet_68500["requiredMigrations"] == []
    assert current_policy_ratchet_68500["optionalMigrations"] == []
    assert any("68500 bytes" in change for change in current_policy_ratchet_68500["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_68500["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_68500["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_68500["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_68500["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_68500["rollbackNotes"])

    current_release_update_suspension = cli.release_migration_report_data(version="0.6.212", products_tested=["example-saas"])
    assert current_release_update_suspension["version"] == "0.6.212"
    assert current_release_update_suspension["wipSafe"] is True
    assert current_release_update_suspension["requiredMigrations"] == []
    assert current_release_update_suspension["optionalMigrations"] == []
    assert any("documented suspension decisions" in change for change in current_release_update_suspension["behaviorChanges"])
    assert any("public-release-check" in change for change in current_release_update_suspension["behaviorChanges"])

    current_public_doc_scrub = cli.release_migration_report_data(version="0.6.211", products_tested=["example-saas"])
    assert current_public_doc_scrub["version"] == "0.6.211"
    assert current_public_doc_scrub["wipSafe"] is True
    assert current_public_doc_scrub["requiredMigrations"] == []
    assert current_public_doc_scrub["optionalMigrations"] == []
    assert any("internal productization finding IDs" in change for change in current_public_doc_scrub["behaviorChanges"])
    assert any("public-boundary regression coverage" in change for change in current_public_doc_scrub["behaviorChanges"])

    current_same_history = cli.release_migration_report_data(version="0.6.210", products_tested=["example-saas"])
    assert current_same_history["version"] == "0.6.210"
    assert current_same_history["wipSafe"] is True
    assert current_same_history["requiredMigrations"] == []
    assert current_same_history["optionalMigrations"] == []
    assert any("same-history" in change for change in current_same_history["behaviorChanges"])

    current_export_exclusions = cli.release_migration_report_data(version="0.6.209", products_tested=["example-saas"])
    assert current_export_exclusions["version"] == "0.6.209"
    assert current_export_exclusions["wipSafe"] is True
    assert current_export_exclusions["requiredMigrations"] == []
    assert current_export_exclusions["optionalMigrations"] == []
    assert any("public-release-export" in change for change in current_export_exclusions["behaviorChanges"])

    current_export_parity = cli.release_migration_report_data(version="0.6.208", products_tested=["example-saas"])
    assert current_export_parity["version"] == "0.6.208"
    assert current_export_parity["wipSafe"] is True
    assert current_export_parity["requiredMigrations"] == []
    assert current_export_parity["optionalMigrations"] == []
    assert any("public-release-export" in change for change in current_export_parity["behaviorChanges"])

    current_guard_shell = cli.release_migration_report_data(version="0.6.207", products_tested=["example-saas"])
    assert current_guard_shell["version"] == "0.6.207"
    assert current_guard_shell["wipSafe"] is True
    assert current_guard_shell["requiredMigrations"] == []
    assert current_guard_shell["optionalMigrations"] == []
    assert any("src/minervit_methodology/guards.py" in change for change in current_guard_shell["behaviorChanges"])
    assert any("text_contains_any" in change for change in current_guard_shell["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_guard_shell["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_guard_shell["rollbackNotes"])

    current_path_shell = cli.release_migration_report_data(version="0.6.206", products_tested=["example-saas"])
    assert current_path_shell["version"] == "0.6.206"
    assert current_path_shell["wipSafe"] is True
    assert current_path_shell["requiredMigrations"] == []
    assert current_path_shell["optionalMigrations"] == []
    assert any("src/minervit_methodology/paths.py" in change for change in current_path_shell["behaviorChanges"])
    assert any("configured_path" in change for change in current_path_shell["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_path_shell["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_path_shell["rollbackNotes"])

    current_git_shell = cli.release_migration_report_data(version="0.6.205", products_tested=["example-saas"])
    assert current_git_shell["version"] == "0.6.205"
    assert current_git_shell["wipSafe"] is True
    assert current_git_shell["requiredMigrations"] == []
    assert current_git_shell["optionalMigrations"] == []
    assert any("src/minervit_methodology/gitutil.py" in change for change in current_git_shell["behaviorChanges"])
    assert any("bin-level run_git seam" in change for change in current_git_shell["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_git_shell["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_git_shell["rollbackNotes"])

    current_util_shell = cli.release_migration_report_data(version="0.6.204", products_tested=["example-saas"])
    assert current_util_shell["version"] == "0.6.204"
    assert current_util_shell["wipSafe"] is True
    assert current_util_shell["requiredMigrations"] == []
    assert current_util_shell["optionalMigrations"] == []
    assert any("src/minervit_methodology/util.py" in change for change in current_util_shell["behaviorChanges"])
    assert any("lazy compatibility wrappers" in change for change in current_util_shell["behaviorChanges"])
    assert any("release-helpers-degraded" in change for change in current_util_shell["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_util_shell["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_util_shell["rollbackNotes"])

    current_package_shell = cli.release_migration_report_data(version="0.6.203", products_tested=["example-saas"])
    assert current_package_shell["version"] == "0.6.203"
    assert current_package_shell["wipSafe"] is True
    assert current_package_shell["requiredMigrations"] == []
    assert current_package_shell["optionalMigrations"] == []
    assert any("Phase 5.1 CLI package split" in change for change in current_package_shell["behaviorChanges"])
    assert any("src/minervit_methodology/releases.py" in change for change in current_package_shell["behaviorChanges"])
    assert any("lazy compatibility wrappers" in change for change in current_package_shell["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_package_shell["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_package_shell["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_package_shell["rollbackNotes"])

    current_release_log_archive = cli.release_migration_report_data(version="0.6.202", products_tested=["example-saas"])
    assert current_release_log_archive["version"] == "0.6.202"
    assert current_release_log_archive["wipSafe"] is True
    assert current_release_log_archive["requiredMigrations"] == []
    assert current_release_log_archive["optionalMigrations"] == []
    assert any("release-log hygiene" in change for change in current_release_log_archive["behaviorChanges"])
    assert any("current-version stub" in change for change in current_release_log_archive["behaviorChanges"])
    assert any("changelog entries" in change for change in current_release_log_archive["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_release_log_archive["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_release_log_archive["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_release_log_archive["rollbackNotes"])

    current_phase4_budget_tests = cli.release_migration_report_data(version="0.6.201", products_tested=["example-saas"])
    assert current_phase4_budget_tests["version"] == "0.6.201"
    assert current_phase4_budget_tests["wipSafe"] is True
    assert current_phase4_budget_tests["requiredMigrations"] == []
    assert current_phase4_budget_tests["optionalMigrations"] == []
    assert any("16000-byte" in change for change in current_phase4_budget_tests["behaviorChanges"])
    assert any("incident-style ISO dates" in change for change in current_phase4_budget_tests["behaviorChanges"])
    assert any("@pending tests" in change for change in current_phase4_budget_tests["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_phase4_budget_tests["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_phase4_budget_tests["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_phase4_budget_tests["rollbackNotes"])

    current_policy_ratchet_60000 = cli.release_migration_report_data(version="0.6.200", products_tested=["example-saas"])
    assert current_policy_ratchet_60000["version"] == "0.6.200"
    assert current_policy_ratchet_60000["wipSafe"] is True
    assert current_policy_ratchet_60000["requiredMigrations"] == []
    assert current_policy_ratchet_60000["optionalMigrations"] == []
    assert any("60000 bytes" in change for change in current_policy_ratchet_60000["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_60000["behaviorChanges"])
    assert any("@pending tests" in change for change in current_policy_ratchet_60000["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_60000["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_60000["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_60000["rollbackNotes"])

    current_open_core_boundary = cli.release_migration_report_data(version="0.6.199", products_tested=["example-saas"])
    assert current_open_core_boundary["version"] == "0.6.199"
    assert current_open_core_boundary["wipSafe"] is True
    assert current_open_core_boundary["requiredMigrations"] == []
    assert current_open_core_boundary["optionalMigrations"] == []
    assert any("Phase 3 open-core boundary" in change for change in current_open_core_boundary["behaviorChanges"])
    assert any("66000 bytes" in change for change in current_open_core_boundary["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_open_core_boundary["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_open_core_boundary["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_open_core_boundary["rollbackNotes"])

    current_proof_pending_literal = cli.release_migration_report_data(version="0.6.198", products_tested=["example-saas"])
    assert current_proof_pending_literal["version"] == "0.6.198"
    assert current_proof_pending_literal["wipSafe"] is True
    assert current_proof_pending_literal["requiredMigrations"] == []
    assert current_proof_pending_literal["optionalMigrations"] == []
    assert any("@pending tests" in change for change in current_proof_pending_literal["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_proof_pending_literal["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_proof_pending_literal["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_proof_pending_literal["rollbackNotes"])

    current_policy_ratchet_68000 = cli.release_migration_report_data(version="0.6.197", products_tested=["example-saas"])
    assert current_policy_ratchet_68000["version"] == "0.6.197"
    assert current_policy_ratchet_68000["wipSafe"] is True
    assert current_policy_ratchet_68000["requiredMigrations"] == []
    assert current_policy_ratchet_68000["optionalMigrations"] == []
    assert any("68000 bytes" in change for change in current_policy_ratchet_68000["behaviorChanges"])
    assert any("word-count ratchets" in change for change in current_policy_ratchet_68000["behaviorChanges"])
    assert any("pending tests" in change for change in current_policy_ratchet_68000["behaviorChanges"])
    assert any("runtime hooks" in change for change in current_policy_ratchet_68000["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_policy_ratchet_68000["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_policy_ratchet_68000["rollbackNotes"])

    current_platform_thin = cli.release_migration_report_data(version="0.6.176", products_tested=["example-saas"])
    assert current_platform_thin["version"] == "0.6.176"
    assert current_platform_thin["wipSafe"] is False
    assert current_platform_thin["requiredMigrations"] == []
    assert current_platform_thin["optionalMigrations"] == []
    assert any("Technical Stack And Platform Defaults policy" in change for change in current_platform_thin["behaviorChanges"])
    assert any("425-word" in change for change in current_platform_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_platform_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_platform_thin["rollbackNotes"])

    current_governance_thin_2 = cli.release_migration_report_data(version="0.6.175", products_tested=["example-saas"])
    assert current_governance_thin_2["version"] == "0.6.175"
    assert current_governance_thin_2["wipSafe"] is False
    assert current_governance_thin_2["requiredMigrations"] == []
    assert current_governance_thin_2["optionalMigrations"] == []
    assert any("575-word" in change for change in current_governance_thin_2["behaviorChanges"])
    assert any("delivery/release procedure" in change for change in current_governance_thin_2["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_governance_thin_2["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_governance_thin_2["rollbackNotes"])

    current_channel_adapter = cli.release_migration_report_data(version="0.6.174", products_tested=["example-saas"])
    assert current_channel_adapter["version"] == "0.6.174"
    assert current_channel_adapter["wipSafe"] is True
    assert current_channel_adapter["requiredMigrations"] == []
    assert current_channel_adapter["optionalMigrations"] == []
    assert any("--source adapter" in change for change in current_channel_adapter["behaviorChanges"])
    assert any(".minervit-ai-delivery.json" in change for change in current_channel_adapter["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_channel_adapter["rollbackNotes"])
    assert any("WIP-safe" in note for note in current_channel_adapter["rollbackNotes"])

    current_autonomy_status_thin = cli.release_migration_report_data(version="0.6.173", products_tested=["example-saas"])
    assert current_autonomy_status_thin["version"] == "0.6.173"
    assert current_autonomy_status_thin["wipSafe"] is False
    assert current_autonomy_status_thin["requiredMigrations"] == []
    assert current_autonomy_status_thin["optionalMigrations"] == []
    assert any("Autonomy And Status policy" in change for change in current_autonomy_status_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_autonomy_status_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_autonomy_status_thin["rollbackNotes"])

    current_context_rotation_thin = cli.release_migration_report_data(version="0.6.172", products_tested=["example-saas"])
    assert current_context_rotation_thin["version"] == "0.6.172"
    assert current_context_rotation_thin["wipSafe"] is False
    assert current_context_rotation_thin["requiredMigrations"] == []
    assert current_context_rotation_thin["optionalMigrations"] == []
    assert any("Context Rotation policy" in change for change in current_context_rotation_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_context_rotation_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_context_rotation_thin["rollbackNotes"])

    current_lane_lifecycle_thin = cli.release_migration_report_data(version="0.6.171", products_tested=["example-saas"])
    assert current_lane_lifecycle_thin["version"] == "0.6.171"
    assert current_lane_lifecycle_thin["wipSafe"] is False
    assert current_lane_lifecycle_thin["requiredMigrations"] == []
    assert current_lane_lifecycle_thin["optionalMigrations"] == []
    assert any("Lane Lifecycle policy" in change for change in current_lane_lifecycle_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_lane_lifecycle_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_lane_lifecycle_thin["rollbackNotes"])

    current_status_truth_thin = cli.release_migration_report_data(version="0.6.170", products_tested=["example-saas"])
    assert current_status_truth_thin["version"] == "0.6.170"
    assert current_status_truth_thin["wipSafe"] is False
    assert current_status_truth_thin["requiredMigrations"] == []
    assert current_status_truth_thin["optionalMigrations"] == []
    assert any("Current Status Truth policy" in change for change in current_status_truth_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_status_truth_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_status_truth_thin["rollbackNotes"])

    current_background_thin = cli.release_migration_report_data(version="0.6.169", products_tested=["example-saas"])
    assert current_background_thin["version"] == "0.6.169"
    assert current_background_thin["wipSafe"] is False
    assert current_background_thin["requiredMigrations"] == []
    assert current_background_thin["optionalMigrations"] == []
    assert any("Background Work policy" in change for change in current_background_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_background_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_background_thin["rollbackNotes"])

    current_context_continuity_thin = cli.release_migration_report_data(version="0.6.168", products_tested=["example-saas"])
    assert current_context_continuity_thin["version"] == "0.6.168"
    assert current_context_continuity_thin["wipSafe"] is False
    assert current_context_continuity_thin["requiredMigrations"] == []
    assert current_context_continuity_thin["optionalMigrations"] == []
    assert any("Context Continuity policy" in change for change in current_context_continuity_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_context_continuity_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_context_continuity_thin["rollbackNotes"])

    current_merge_ci_thin = cli.release_migration_report_data(version="0.6.167", products_tested=["example-saas"])
    assert current_merge_ci_thin["version"] == "0.6.167"
    assert current_merge_ci_thin["wipSafe"] is False
    assert current_merge_ci_thin["requiredMigrations"] == []
    assert current_merge_ci_thin["optionalMigrations"] == []
    assert any("Merge And CI policy" in change for change in current_merge_ci_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_merge_ci_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_merge_ci_thin["rollbackNotes"])

    current_backlog_provider_thin = cli.release_migration_report_data(version="0.6.166", products_tested=["example-saas"])
    assert current_backlog_provider_thin["version"] == "0.6.166"
    assert current_backlog_provider_thin["wipSafe"] is False
    assert current_backlog_provider_thin["requiredMigrations"] == []
    assert current_backlog_provider_thin["optionalMigrations"] == []
    assert any("Backlog Provider Intake And Grooming policy" in change for change in current_backlog_provider_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_backlog_provider_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_backlog_provider_thin["rollbackNotes"])

    current_risk_tier_reference_thin = cli.release_migration_report_data(version="0.6.165", products_tested=["example-saas"])
    assert current_risk_tier_reference_thin["version"] == "0.6.165"
    assert current_risk_tier_reference_thin["wipSafe"] is False
    assert current_risk_tier_reference_thin["requiredMigrations"] == []
    assert current_risk_tier_reference_thin["optionalMigrations"] == []
    assert any("risk-tier plan-review finalization guidance" in change for change in current_risk_tier_reference_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_risk_tier_reference_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_risk_tier_reference_thin["rollbackNotes"])

    current_lane_thin = cli.release_migration_report_data(version="0.6.164", products_tested=["example-saas"])
    assert current_lane_thin["version"] == "0.6.164"
    assert current_lane_thin["wipSafe"] is False
    assert current_lane_thin["requiredMigrations"] == []
    assert current_lane_thin["optionalMigrations"] == []
    assert any("Lane Lifecycle policy" in change for change in current_lane_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_lane_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_lane_thin["rollbackNotes"])

    current_board_thin = cli.release_migration_report_data(version="0.6.163", products_tested=["example-saas"])
    assert current_board_thin["version"] == "0.6.163"
    assert current_board_thin["wipSafe"] is False
    assert current_board_thin["requiredMigrations"] == []
    assert current_board_thin["optionalMigrations"] == []
    assert any("Board Currency And Subtask Status policy" in change for change in current_board_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_board_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_board_thin["rollbackNotes"])

    current_goal_thin = cli.release_migration_report_data(version="0.6.162", products_tested=["example-saas"])
    assert current_goal_thin["version"] == "0.6.162"
    assert current_goal_thin["wipSafe"] is False
    assert current_goal_thin["requiredMigrations"] == []
    assert current_goal_thin["optionalMigrations"] == []
    assert any("Goal Orchestration policy" in change for change in current_goal_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_goal_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_goal_thin["rollbackNotes"])

    current_governance_thin = cli.release_migration_report_data(version="0.6.161", products_tested=["example-saas"])
    assert current_governance_thin["version"] == "0.6.161"
    assert current_governance_thin["wipSafe"] is False
    assert current_governance_thin["requiredMigrations"] == []
    assert current_governance_thin["optionalMigrations"] == []
    assert any("Governance policy" in change for change in current_governance_thin["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_governance_thin["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_governance_thin["rollbackNotes"])

    current_rendered_adapter_budget = cli.release_migration_report_data(version="0.6.160", products_tested=["example-saas"])
    assert current_rendered_adapter_budget["version"] == "0.6.160"
    assert current_rendered_adapter_budget["wipSafe"] is False
    assert current_rendered_adapter_budget["requiredMigrations"] == []
    assert current_rendered_adapter_budget["optionalMigrations"] == []
    assert any("16000 bytes" in change for change in current_rendered_adapter_budget["behaviorChanges"])
    assert any("set-framework-channel" in change for change in current_rendered_adapter_budget["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_rendered_adapter_budget["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_rendered_adapter_budget["rollbackNotes"])

    current_rca_cleanup = cli.release_migration_report_data(version="0.6.159", products_tested=["example-saas"])
    assert current_rca_cleanup["version"] == "0.6.159"
    assert current_rca_cleanup["wipSafe"] is False
    assert current_rca_cleanup["requiredMigrations"] == []
    assert current_rca_cleanup["optionalMigrations"] == []
    assert any("RCA artifact validation" in change for change in current_rca_cleanup["behaviorChanges"])
    assert any("incident-date strings" in change for change in current_rca_cleanup["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_rca_cleanup["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_rca_cleanup["rollbackNotes"])

    current_thin_skills = cli.release_migration_report_data(version="0.6.158", products_tested=["example-saas"])
    assert current_thin_skills["version"] == "0.6.158"
    assert current_thin_skills["wipSafe"] is False
    assert current_thin_skills["requiredMigrations"] == []
    assert current_thin_skills["optionalMigrations"] == []
    assert any("45 lines" in change for change in current_thin_skills["behaviorChanges"])
    assert any("1200 lines" in change for change in current_thin_skills["behaviorChanges"])
    assert any("Stable clients remain on the stable channel" in note for note in current_thin_skills["rollbackNotes"])
    assert any("not WIP-safe" in note for note in current_thin_skills["rollbackNotes"])

    current_guard_check = cli.release_migration_report_data(version="0.6.148", products_tested=["example-saas"])
    assert current_guard_check["version"] == "0.6.148"
    assert current_guard_check["wipSafe"] is False
    assert any("guard-check --boundary prepush" in change for change in current_guard_check["behaviorChanges"])
    assert current_guard_check["requiredMigrations"] == []

    current_stop_guard = cli.release_migration_report_data(version="0.6.147", products_tested=["example-saas"])
    assert current_stop_guard["version"] == "0.6.147"
    assert current_stop_guard["wipSafe"] is False
    assert any("Stop-hook blocking" in change for change in current_stop_guard["behaviorChanges"])
    assert any(item["id"] == "responseGuard.phraseChecks" for item in current_stop_guard["optionalMigrations"])

    latest = cli.release_migration_report_data(version="0.6.146", products_tested=["example-saas"])
    assert latest["version"] == "0.6.146"
    assert latest["wipSafe"] is True
    assert any("blocker-declare" in change for change in latest["behaviorChanges"])
    assert any("no-safe-parallel-work" in change for change in latest["behaviorChanges"])
    assert latest["optionalMigrations"] == []

    previous_init_flow = cli.release_migration_report_data(version="0.6.145", products_tested=["example-saas"])
    assert previous_init_flow["version"] == "0.6.145"
    assert previous_init_flow["wipSafe"] is True
    assert any("minervit-methodology init" in change for change in previous_init_flow["behaviorChanges"])
    assert any("managed repos no-op" in change for change in previous_init_flow["behaviorChanges"])
    assert previous_init_flow["optionalMigrations"] == []

    previous_telemetry = cli.release_migration_report_data(version="0.6.144", products_tested=["example-saas"])
    assert previous_telemetry["version"] == "0.6.144"
    assert previous_telemetry["wipSafe"] is True
    assert any("guard-fire events" in change for change in previous_telemetry["behaviorChanges"])
    assert previous_telemetry["optionalMigrations"] == []

    previous_stability = cli.release_migration_report_data(version="0.6.143", products_tested=["example-saas"])
    assert previous_stability["version"] == "0.6.143"
    assert previous_stability["wipSafe"] is True
    assert any("set-framework-channel" in change for change in previous_stability["behaviorChanges"])
    assert any(item["id"] == "direct-main-non-dev-profile" for item in previous_stability["optionalMigrations"])

    previous_runtime = cli.release_migration_report_data(version="0.6.142", products_tested=["example-saas"])
    assert previous_runtime["version"] == "0.6.142"
    assert previous_runtime["wipSafe"] is True
    assert any("supported lane runtimes" in change for change in previous_runtime["behaviorChanges"])
    assert any(item["id"] == "declare-wsl2-windows-runtime" for item in previous_runtime["optionalMigrations"])

    previous_background = cli.release_migration_report_data(version="0.6.141", products_tested=["example-saas"])
    assert previous_background["version"] == "0.6.141"
    assert previous_background["wipSafe"] is True
    assert any("Background Work policy is now a concise stable contract" in change for change in previous_background["behaviorChanges"])
    assert previous_background["optionalMigrations"] == []

    previous_subtask_parent = cli.release_migration_report_data(version="0.6.140", products_tested=["example-saas"])
    assert previous_subtask_parent["version"] == "0.6.140"
    assert previous_subtask_parent["wipSafe"] is True
    assert any("board-backed native subtasks now also claim the native parent issue active" in change for change in previous_subtask_parent["behaviorChanges"])
    assert previous_subtask_parent["optionalMigrations"] == []

    previous_context = cli.release_migration_report_data(version="0.6.139", products_tested=["example-saas"])
    assert previous_context["version"] == "0.6.139"
    assert previous_context["wipSafe"] is True
    assert any("Context Continuity policy is now a shorter" in change for change in previous_context["behaviorChanges"])
    assert previous_context["optionalMigrations"] == []

    previous_delivery = cli.release_migration_report_data(version="0.6.138", products_tested=["example-saas"])
    assert previous_delivery["version"] == "0.6.138"
    assert previous_delivery["wipSafe"] is True
    assert any("Delivery Summaries policy is now a concise" in change for change in previous_delivery["behaviorChanges"])
    assert previous_delivery["optionalMigrations"] == []

    previous_autonomy = cli.release_migration_report_data(version="0.6.137", products_tested=["example-saas"])
    assert previous_autonomy["version"] == "0.6.137"
    assert previous_autonomy["wipSafe"] is True
    assert any("Autonomy And Status contract" in change for change in previous_autonomy["behaviorChanges"])
    assert previous_autonomy["optionalMigrations"] == []

    previous_review = cli.release_migration_report_data(version="0.6.136", products_tested=["example-saas"])
    assert previous_review["version"] == "0.6.136"
    assert previous_review["wipSafe"] is True
    assert any("Review Before Push policy is now a concise" in change for change in previous_review["behaviorChanges"])
    assert previous_review["optionalMigrations"] == []

    previous_latest_code = cli.release_migration_report_data(version="0.6.135", products_tested=["example-saas"])
    assert previous_latest_code["version"] == "0.6.135"
    assert previous_latest_code["wipSafe"] is True
    assert any("no longer blocks read-only Claude tool calls" in change for change in previous_latest_code["behaviorChanges"])
    assert previous_latest_code["optionalMigrations"] == []

    previous_init = cli.release_migration_report_data(version="0.6.134", products_tested=["example-saas"])
    assert previous_init["version"] == "0.6.134"
    assert previous_init["wipSafe"] is True
    assert any("init-project-adapter now writes <target>/.minervit/adapter.json" in change for change in previous_init["behaviorChanges"])
    assert previous_init["optionalMigrations"] == []

    previous_repo_local = cli.release_migration_report_data(version="0.6.133", products_tested=["example-saas"])
    assert previous_repo_local["wipSafe"] is True
    assert any("repo-local .minervit/adapter.json" in change for change in previous_repo_local["behaviorChanges"])
    assert any(item["id"] == "rerender-repo-local-generated-adapter" for item in previous_repo_local["optionalMigrations"])

    previous_freeze = cli.release_migration_report_data(version="0.6.132", products_tested=["example-saas"])
    assert previous_freeze["wipSafe"] is True
    assert any("static external-process budget" in change for change in previous_freeze["behaviorChanges"])
    assert previous_freeze["optionalMigrations"] == []

    previous_bug_intake = cli.release_migration_report_data(version="0.6.131", products_tested=["example-saas"])
    assert previous_bug_intake["wipSafe"] is True
    assert any("bug-intake-triage skill" in change for change in previous_bug_intake["behaviorChanges"])
    assert any("No generated-adapter change is expected" in item["description"] for item in previous_bug_intake["optionalMigrations"])

    previous_stable = cli.release_migration_report_data(version="0.6.130", products_tested=["example-saas"])
    assert previous_stable["wipSafe"] is False
    assert any("positive review.roundBudgets.T0 warn and coerce to 0" in change for change in previous_stable["behaviorChanges"])

    with pytest.raises(SystemExit, match="not declared for 0.6.128"):
        cli.release_migration_report_data(version="0.6.128")
    with pytest.raises(SystemExit, match="not declared for 0.6.129"):
        cli.release_migration_report_data(version="0.6.129")
    current_private_terms_file = cli.release_migration_report_data(version="0.6.213", products_tested=["example-saas"])
    assert current_private_terms_file["version"] == "0.6.213"
    assert current_private_terms_file["wipSafe"] is True
    assert any("--private-terms-file" in change for change in current_private_terms_file["behaviorChanges"])

    current_generated_adapter_pytest = cli.release_migration_report_data(version="0.6.214", products_tested=["example-saas"])
    assert current_generated_adapter_pytest["version"] == "0.6.214"
    assert current_generated_adapter_pytest["wipSafe"] is True
    assert any("generated-adapter overwrite protection" in change for change in current_generated_adapter_pytest["behaviorChanges"])

    current_document_context_pytest = cli.release_migration_report_data(version="0.6.215", products_tested=["example-saas"])
    assert current_document_context_pytest["version"] == "0.6.215"
    assert current_document_context_pytest["wipSafe"] is True
    assert any("document-context" in change for change in current_document_context_pytest["behaviorChanges"])

    current_work_loop_pytest = cli.release_migration_report_data(version="0.6.216", products_tested=["example-saas"])
    assert current_work_loop_pytest["version"] == "0.6.216"
    assert current_work_loop_pytest["wipSafe"] is True
    assert any("work-loop --dry-run" in change for change in current_work_loop_pytest["behaviorChanges"])

    current_lock_pytest = cli.release_migration_report_data(version="0.6.217", products_tested=["example-saas"])
    assert current_lock_pytest["version"] == "0.6.217"
    assert current_lock_pytest["wipSafe"] is True
    assert any("methodology lock" in change for change in current_lock_pytest["behaviorChanges"])

    current_lane_coordination_pytest = cli.release_migration_report_data(version="0.6.218", products_tested=["example-saas"])
    assert current_lane_coordination_pytest["version"] == "0.6.218"
    assert current_lane_coordination_pytest["wipSafe"] is True
    assert any("lane-coordination" in change for change in current_lane_coordination_pytest["behaviorChanges"])

    current_graphify_pytest = cli.release_migration_report_data(version="0.6.219", products_tested=["example-saas"])
    assert current_graphify_pytest["version"] == "0.6.219"
    assert current_graphify_pytest["wipSafe"] is True
    assert any("Graphify" in change for change in current_graphify_pytest["behaviorChanges"])

    current_sync_pytest = cli.release_migration_report_data(version="0.6.220", products_tested=["example-saas"])
    assert current_sync_pytest["version"] == "0.6.220"
    assert current_sync_pytest["wipSafe"] is True
    assert any("sync-methodology" in change for change in current_sync_pytest["behaviorChanges"])

    current_milestone_pytest = cli.release_migration_report_data(version="0.6.221", products_tested=["example-saas"])
    assert current_milestone_pytest["version"] == "0.6.221"
    assert current_milestone_pytest["wipSafe"] is True
    assert any("milestone ledger" in change for change in current_milestone_pytest["behaviorChanges"])

    current_session_journal_pytest = cli.release_migration_report_data(version="0.6.222", products_tested=["example-saas"])
    assert current_session_journal_pytest["version"] == "0.6.222"
    assert current_session_journal_pytest["wipSafe"] is True
    assert any("session journal" in change for change in current_session_journal_pytest["behaviorChanges"])

    current_event_usage_pytest = cli.release_migration_report_data(version="0.6.223", products_tested=["example-saas"])
    assert current_event_usage_pytest["version"] == "0.6.223"
    assert current_event_usage_pytest["wipSafe"] is True
    assert any("event and usage accounting" in change for change in current_event_usage_pytest["behaviorChanges"])
    assert any("deployment notification" in change for change in current_event_usage_pytest["behaviorChanges"])

    current_lane_start_planning_pytest = cli.release_migration_report_data(version="0.6.224", products_tested=["example-saas"])
    assert current_lane_start_planning_pytest["version"] == "0.6.224"
    assert current_lane_start_planning_pytest["wipSafe"] is True
    assert any("lane-start planning" in change for change in current_lane_start_planning_pytest["behaviorChanges"])
    assert any("lane-env" in change for change in current_lane_start_planning_pytest["behaviorChanges"])

    current_plan_review_pytest = cli.release_migration_report_data(version="0.6.225", products_tested=["example-saas"])
    assert current_plan_review_pytest["version"] == "0.6.225"
    assert current_plan_review_pytest["wipSafe"] is True
    assert any("plan-review and plan-finalization" in change for change in current_plan_review_pytest["behaviorChanges"])
    assert any("Codex fast-mode" in change for change in current_plan_review_pytest["behaviorChanges"])

    current_validate_wrapper = cli.release_migration_report_data(version="0.6.226", products_tested=["example-saas"])
    assert current_validate_wrapper["version"] == "0.6.226"
    assert current_validate_wrapper["wipSafe"] is True
    assert any("thin compatibility wrapper" in change for change in current_validate_wrapper["behaviorChanges"])
    assert any("legacy shell assertion body" in change for change in current_validate_wrapper["behaviorChanges"])

    current_profile_helpers = cli.release_migration_report_data(version="0.6.227", products_tested=["example-saas"])
    assert current_profile_helpers["version"] == "0.6.227"
    assert current_profile_helpers["wipSafe"] is True
    assert any("src/minervit_methodology/profiles.py" in change for change in current_profile_helpers["behaviorChanges"])
    assert any("lazy compatibility wrappers" in change for change in current_profile_helpers["behaviorChanges"])

    current_telemetry_helpers = cli.release_migration_report_data(version="0.6.228", products_tested=["example-saas"])
    assert current_telemetry_helpers["version"] == "0.6.228"
    assert current_telemetry_helpers["wipSafe"] is True
    assert any("src/minervit_methodology/telemetry.py" in change for change in current_telemetry_helpers["behaviorChanges"])
    assert any("guard-event helper primitives" in change for change in current_telemetry_helpers["behaviorChanges"])

    current_release_update_helpers = cli.release_migration_report_data(version="0.6.229", products_tested=["example-saas"])
    assert current_release_update_helpers["version"] == "0.6.229"
    assert current_release_update_helpers["wipSafe"] is True
    assert any("release-update accounting helpers" in change for change in current_release_update_helpers["behaviorChanges"])
    assert any("release-update delivery ledgers" in change for change in current_release_update_helpers["behaviorChanges"])

    current_env_helpers = cli.release_migration_report_data(version="0.6.230", products_tested=["example-saas"])
    assert current_env_helpers["version"] == "0.6.230"
    assert current_env_helpers["wipSafe"] is True
    assert any("installed environment-file helper primitives" in change for change in current_env_helpers["behaviorChanges"])
    assert any("publish-release-update webhook lookup" in change for change in current_env_helpers["behaviorChanges"])

    current_name_helpers = cli.release_migration_report_data(version="0.6.231", products_tested=["example-saas"])
    assert current_name_helpers["version"] == "0.6.231"
    assert current_name_helpers["wipSafe"] is True
    assert any("src/minervit_methodology/names.py" in change for change in current_name_helpers["behaviorChanges"])
    assert any("check-name-availability" in change for change in current_name_helpers["behaviorChanges"])

    current_release_render_helpers = cli.release_migration_report_data(version="0.6.232", products_tested=["example-saas"])
    assert current_release_render_helpers["version"] == "0.6.232"
    assert current_release_render_helpers["wipSafe"] is True
    assert any("release-update rendering helpers" in change for change in current_release_render_helpers["behaviorChanges"])
    assert any("publish-release-update" in change for change in current_release_render_helpers["behaviorChanges"])

    current_chat_payload_helpers = cli.release_migration_report_data(version="0.6.233", products_tested=["example-saas"])
    assert current_chat_payload_helpers["version"] == "0.6.233"
    assert current_chat_payload_helpers["wipSafe"] is True
    assert any("src/minervit_methodology/chat.py" in change for change in current_chat_payload_helpers["behaviorChanges"])
    assert any("publish-milestone-update" in change for change in current_chat_payload_helpers["behaviorChanges"])

    current_chat_validation_helpers = cli.release_migration_report_data(version="0.6.234", products_tested=["example-saas"])
    assert current_chat_validation_helpers["version"] == "0.6.234"
    assert current_chat_validation_helpers["wipSafe"] is True
    assert any("Google Chat content validation helpers" in change for change in current_chat_validation_helpers["behaviorChanges"])
    assert any("publish-product-note" in change for change in current_chat_validation_helpers["behaviorChanges"])

    current_deploy_health_helpers = cli.release_migration_report_data(version="0.6.235", products_tested=["example-saas"])
    assert current_deploy_health_helpers["version"] == "0.6.235"
    assert current_deploy_health_helpers["wipSafe"] is True
    assert any("src/minervit_methodology/deploy.py" in change for change in current_deploy_health_helpers["behaviorChanges"])
    assert any("deploy-health command output" in change for change in current_deploy_health_helpers["behaviorChanges"])

    current_deploy_health_io_helpers = cli.release_migration_report_data(version="0.6.236", products_tested=["example-saas"])
    assert current_deploy_health_io_helpers["version"] == "0.6.236"
    assert current_deploy_health_io_helpers["wipSafe"] is True
    assert any("deploy-health run-file loading" in change for change in current_deploy_health_io_helpers["behaviorChanges"])
    assert any("deploy_health_github_actions_runs" in change for change in current_deploy_health_io_helpers["behaviorChanges"])

    current_deployment_notification_helpers = cli.release_migration_report_data(version="0.6.237", products_tested=["example-saas"])
    assert current_deployment_notification_helpers["version"] == "0.6.237"
    assert current_deployment_notification_helpers["wipSafe"] is True
    assert any("deployment-notification config lookup" in change for change in current_deployment_notification_helpers["behaviorChanges"])
    assert any("deployment_notification_pipeline_issues" in change for change in current_deployment_notification_helpers["behaviorChanges"])

    current_deployment_marker_source_helpers = cli.release_migration_report_data(version="0.6.238", products_tested=["example-saas"])
    assert current_deployment_marker_source_helpers["version"] == "0.6.238"
    assert current_deployment_marker_source_helpers["wipSafe"] is True
    assert any("deployment-notification marker-path" in change for change in current_deployment_marker_source_helpers["behaviorChanges"])
    assert any("deployment_notification_content_from_args" in change for change in current_deployment_marker_source_helpers["behaviorChanges"])

    current_deploy_ready_validation_helpers = cli.release_migration_report_data(version="0.6.239", products_tested=["example-saas"])
    assert current_deploy_ready_validation_helpers["version"] == "0.6.239"
    assert current_deploy_ready_validation_helpers["wipSafe"] is True
    assert any("deploy-ready notification extra validation" in change for change in current_deploy_ready_validation_helpers["behaviorChanges"])
    assert any("dedupe identity basis" in change for change in current_deploy_ready_validation_helpers["behaviorChanges"])

    current_release_update_status_helpers = cli.release_migration_report_data(version="0.6.240", products_tested=["example-saas"])
    assert current_release_update_status_helpers["version"] == "0.6.240"
    assert current_release_update_status_helpers["wipSafe"] is True
    assert any("release-update version selection" in change for change in current_release_update_status_helpers["behaviorChanges"])
    assert any("release-update-status JSON/text output" in change for change in current_release_update_status_helpers["behaviorChanges"])

    current_chat_input_webhook_helpers = cli.release_migration_report_data(version="0.6.241", products_tested=["example-saas"])
    assert current_chat_input_webhook_helpers["version"] == "0.6.241"
    assert current_chat_input_webhook_helpers["wipSafe"] is True
    assert any("milestone-update and product-note content-input" in change for change in current_chat_input_webhook_helpers["behaviorChanges"])
    assert any("dry-run webhook fallback" in change for change in current_chat_input_webhook_helpers["behaviorChanges"])

    current_milestone_marker_helpers = cli.release_migration_report_data(version="0.6.242", products_tested=["example-saas"])
    assert current_milestone_marker_helpers["version"] == "0.6.242"
    assert current_milestone_marker_helpers["wipSafe"] is True
    assert any("milestone-update content hash" in change for change in current_milestone_marker_helpers["behaviorChanges"])
    assert any("delivery marker JSON fields" in change for change in current_milestone_marker_helpers["behaviorChanges"])
    assert any("Corrupt milestone-update delivery markers" in change for change in current_milestone_marker_helpers["behaviorChanges"])

    current_public_release_helpers = cli.release_migration_report_data(version="0.6.243", products_tested=["example-saas"])
    assert current_public_release_helpers["version"] == "0.6.243"
    assert current_public_release_helpers["wipSafe"] is True
    assert any("public-release export marker" in change for change in current_public_release_helpers["behaviorChanges"])
    assert any("standalone copied-bin fallback" in change for change in current_public_release_helpers["behaviorChanges"])
    assert any("clean export behavior are unchanged" in change for change in current_public_release_helpers["behaviorChanges"])
    assert not any(item["section"] == "skills" for item in current_public_release_helpers["deprecatedSurfaces"])

    current_self_adapter = cli.release_migration_report_data(version="0.6.244", products_tested=["example-saas"])
    assert current_self_adapter["version"] == "0.6.244"
    assert current_self_adapter["wipSafe"] is True
    assert any(".minervit/adapter.json" in change for change in current_self_adapter["behaviorChanges"])
    assert any("No project adapter found" in change for change in current_self_adapter["behaviorChanges"])
    assert any("goalTracker warning only when the raw source adapter declares goalTracker" in change for change in current_self_adapter["behaviorChanges"])
    assert any(
        item["section"] == "skills" and item["name"] == "methodology-regression-rca" and item["replacement"] == "framework-intake"
        for item in current_self_adapter["deprecatedSurfaces"]
    )
    assert any(
        item["section"] == "skills" and item["name"] == "rules-audit" and item["replacement"] == "framework-intake"
        for item in current_self_adapter["deprecatedSurfaces"]
    )

    current_blocker_helpers = cli.release_migration_report_data(version="0.6.245", products_tested=["example-saas"])
    assert current_blocker_helpers["version"] == "0.6.245"
    assert current_blocker_helpers["wipSafe"] is True
    assert any("blocker record path" in change for change in current_blocker_helpers["behaviorChanges"])
    assert any("compatibility wrappers" in change for change in current_blocker_helpers["behaviorChanges"])
    assert any("output, exit codes, and file formats are unchanged" in change for change in current_blocker_helpers["behaviorChanges"])

    current_github_helpers = cli.release_migration_report_data(version="0.6.246", products_tested=["example-saas"])
    assert current_github_helpers["version"] == "0.6.246"
    assert current_github_helpers["wipSafe"] is True
    assert any("GitHub provider cache, lock, telemetry, retry, and rate-budget primitives" in change for change in current_github_helpers["behaviorChanges"])
    assert any("compatibility wrappers" in change for change in current_github_helpers["behaviorChanges"])
    assert any("output, exit codes, and file formats are unchanged" in change for change in current_github_helpers["behaviorChanges"])

    current_adapter_helpers = cli.release_migration_report_data(version="0.6.247", products_tested=["example-saas"])
    assert current_adapter_helpers["version"] == "0.6.247"
    assert current_adapter_helpers["wipSafe"] is True
    assert any("adapter schema loading" in change for change in current_adapter_helpers["behaviorChanges"])
    assert any("compatibility wrappers" in change for change in current_adapter_helpers["behaviorChanges"])
    assert any("validate-adapter, render-adapters, lane startup" in change for change in current_adapter_helpers["behaviorChanges"])

    current_render_budget_helpers = cli.release_migration_report_data(version="0.6.248", products_tested=["example-saas"])
    assert current_render_budget_helpers["version"] == "0.6.248"
    assert current_render_budget_helpers["wipSafe"] is True
    assert any("adapter render-budget defaults" in change for change in current_render_budget_helpers["behaviorChanges"])
    assert any("compatibility wrappers" in change for change in current_render_budget_helpers["behaviorChanges"])
    assert any("render-adapters budget warnings/errors" in change for change in current_render_budget_helpers["behaviorChanges"])

    current_public_release_private_terms_helpers = cli.release_migration_report_data(
        version="0.6.249",
        products_tested=["example-saas"],
    )
    assert current_public_release_private_terms_helpers["version"] == "0.6.249"
    assert current_public_release_private_terms_helpers["wipSafe"] is True
    assert any(
        "public-release private adapter discovery" in change
        for change in current_public_release_private_terms_helpers["behaviorChanges"]
    )
    assert any("standalone fallback" in change for change in current_public_release_private_terms_helpers["behaviorChanges"])
    assert any("public-release-check and public-release-export" in change for change in current_public_release_private_terms_helpers["behaviorChanges"])

    current_blocker_command_helpers = cli.release_migration_report_data(
        version="0.6.250",
        products_tested=["example-saas"],
    )
    assert current_blocker_command_helpers["version"] == "0.6.250"
    assert current_blocker_command_helpers["wipSafe"] is True
    assert any("blocker declaration validation" in change for change in current_blocker_command_helpers["behaviorChanges"])
    assert any("blocker_status_result" in change for change in current_blocker_command_helpers["behaviorChanges"])
    assert any("stale helper package" in change for change in current_blocker_command_helpers["behaviorChanges"])
    assert any("blocker-declare, blocker-status, blocker-clear" in change for change in current_blocker_command_helpers["behaviorChanges"])

    current_plan_revision = cli.release_migration_report_data(
        version="0.6.251",
        products_tested=["example-saas"],
    )
    assert current_plan_revision["version"] == "0.6.251"
    assert current_plan_revision["wipSafe"] is True
    assert current_plan_revision["requiredMigrations"] == []
    assert any("productization refactor plan" in change for change in current_plan_revision["behaviorChanges"])
    assert any("Documentation only" in change for change in current_plan_revision["behaviorChanges"])

    current_policy_helpers = cli.release_migration_report_data(
        version="0.6.252",
        products_tested=["example-saas"],
    )
    assert current_policy_helpers["version"] == "0.6.252"
    assert current_policy_helpers["wipSafe"] is True
    assert any("guard phrase vocabulary collection" in change for change in current_policy_helpers["behaviorChanges"])
    assert any("render_policy_phrases_json" in change for change in current_policy_helpers["behaviorChanges"])
    assert any("dump-policy-phrases" in change for change in current_policy_helpers["behaviorChanges"])

    current_guard_taxonomy = cli.release_migration_report_data(
        version="0.6.253",
        products_tested=["example-saas"],
    )
    assert current_guard_taxonomy["version"] == "0.6.253"
    assert current_guard_taxonomy["wipSafe"] is True
    assert any("re-tagged from state to phrase mechanism" in change for change in current_guard_taxonomy["behaviorChanges"])
    assert any("phraseChecks default flips from blocking to advisory" in change for change in current_guard_taxonomy["behaviorChanges"])
    assert any("stop.boundary_summary" in change for change in current_guard_taxonomy["behaviorChanges"])
    assert any("stop.recovery_cancellation_without_explicit_stop" in change for change in current_guard_taxonomy["behaviorChanges"])

    current_domain_unification = cli.release_migration_report_data(
        version="0.6.254",
        products_tested=["example-saas"],
    )
    assert current_domain_unification["version"] == "0.6.254"
    assert current_domain_unification["wipSafe"] is True
    assert any("minervit.com" in change for change in current_domain_unification["behaviorChanges"])
    assert any("test_shippable_surfaces_unify_contact_domain_to_minervit_com" in change for change in current_domain_unification["behaviorChanges"])

    current_single_gate_docs = cli.release_migration_report_data(
        version="0.6.255",
        products_tested=["example-saas"],
    )
    assert current_single_gate_docs["version"] == "0.6.255"
    assert current_single_gate_docs["wipSafe"] is True
    assert any("no longer instruct contributors to run scripts/validate.sh" in change for change in current_single_gate_docs["behaviorChanges"])
    assert any("frozen 5-line alias" in change for change in current_single_gate_docs["behaviorChanges"])

    current_channel_neutral_policy = cli.release_migration_report_data(
        version="0.6.256",
        products_tested=["example-saas"],
    )
    assert current_channel_neutral_policy["version"] == "0.6.256"
    assert current_channel_neutral_policy["wipSafe"] is True
    assert any(
        "no longer names MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK" in change
        for change in current_channel_neutral_policy["behaviorChanges"]
    )
    assert any("Release Announcements section" in change for change in current_channel_neutral_policy["behaviorChanges"])

    current_validate_disposition_audit = cli.release_migration_report_data(
        version="0.6.257",
        products_tested=["example-saas"],
    )
    assert current_validate_disposition_audit["version"] == "0.6.257"
    assert current_validate_disposition_audit["wipSafe"] is True
    assert any(
        "Spot-Audit" in change
        for change in current_validate_disposition_audit["behaviorChanges"]
    )
    assert any(
        "tests/test_policy_phrases_ssot.py" in change
        for change in current_validate_disposition_audit["behaviorChanges"]
    )

    current_self_adapter_fix = cli.release_migration_report_data(
        version="0.6.258",
        products_tested=["example-saas"],
    )
    assert current_self_adapter_fix["version"] == "0.6.258"
    assert current_self_adapter_fix["wipSafe"] is True
    assert any(
        "load-bearing" in change
        for change in current_self_adapter_fix["behaviorChanges"]
    )
    assert any(
        "self-adapter verification" in change
        for change in current_self_adapter_fix["behaviorChanges"]
    )

    current_makerkit_move = cli.release_migration_report_data(
        version="0.6.259",
        products_tested=["example-saas"],
    )
    assert current_makerkit_move["version"] == "0.6.259"
    assert current_makerkit_move["wipSafe"] is False
    assert any(
        "makerkit-implementation skill moved" in change
        for change in current_makerkit_move["behaviorChanges"]
    )
    assert any(
        "makerkit skill-split recommendation" in change
        for change in current_makerkit_move["behaviorChanges"]
    )
    assert any(
        migration["id"] == "install-minervit-delivery-ops-plugin-for-makerkit"
        for migration in current_makerkit_move["optionalMigrations"]
    )

    current_render_adapter_budget = cli.release_migration_report_data(
        version="0.6.260",
        products_tested=["example-saas"],
    )
    assert current_render_adapter_budget["version"] == "0.6.260"
    assert current_render_adapter_budget["wipSafe"] is True
    assert any(
        "render_adapter()" in change
        for change in current_render_adapter_budget["behaviorChanges"]
    )
    assert any(
        "byte budget" in change
        for change in current_render_adapter_budget["behaviorChanges"]
    )

    current_dead_constant_removal = cli.release_migration_report_data(
        version="0.6.261",
        products_tested=["example-saas"],
    )
    assert current_dead_constant_removal["version"] == "0.6.261"
    assert current_dead_constant_removal["wipSafe"] is True
    assert any(
        "RELEASE_NOTES_ARCHIVE_BRANCH" in change
        for change in current_dead_constant_removal["behaviorChanges"]
    )
    assert any(
        "Release Notes Archive" in change
        for change in current_dead_constant_removal["behaviorChanges"]
    )

    current_parallel_execution_reference = cli.release_migration_report_data(
        version="0.6.262",
        products_tested=["example-saas"],
    )
    assert current_parallel_execution_reference["version"] == "0.6.262"
    assert current_parallel_execution_reference["wipSafe"] is True
    assert current_parallel_execution_reference["requiredMigrations"] == []
    assert any(
        "parallel-execution reference" in change
        for change in current_parallel_execution_reference["behaviorChanges"]
    )
    assert any(
        "advisory" in change
        for change in current_parallel_execution_reference["behaviorChanges"]
    )

    current_single_source_helpers = cli.release_migration_report_data(
        version="0.6.263",
        products_tested=["example-saas"],
    )
    assert current_single_source_helpers["version"] == "0.6.263"
    assert current_single_source_helpers["wipSafe"] is False
    assert current_single_source_helpers["requiredMigrations"] == []
    assert any(
        "src/minervit_methodology" in change
        for change in current_single_source_helpers["behaviorChanges"]
    )
    assert any(
        "fail" in change and "open" in change
        for change in current_single_source_helpers["behaviorChanges"]
    )

    current_alias_removal = cli.release_migration_report_data(
        version="0.6.264",
        products_tested=["example-saas"],
    )
    assert current_alias_removal["version"] == "0.6.264"
    assert current_alias_removal["wipSafe"] is False
    assert current_alias_removal["requiredMigrations"] == []
    assert any(
        item["id"] == "framework-intake-replaces-methodology-regression-rca"
        for item in current_alias_removal["optionalMigrations"]
    )
    assert any(
        "framework-intake owns" in change
        for change in current_alias_removal["behaviorChanges"]
    )
    assert not any(
        item["section"] == "skills" and item["name"] == "methodology-regression-rca"
        for item in current_alias_removal["deprecatedSurfaces"]
    )

    current_export_ci_context = cli.release_migration_report_data(
        version="0.6.265",
        products_tested=["example-saas"],
    )
    assert current_export_ci_context["version"] == "0.6.265"
    assert current_export_ci_context["wipSafe"] is True
    assert any(
        "public-release-export marker" in change
        for change in current_export_ci_context["behaviorChanges"]
    )

    current_governance_pack = cli.release_migration_report_data(
        version="0.6.266",
        products_tested=["methodology-framework"],
    )
    assert current_governance_pack["version"] == "0.6.266"
    assert current_governance_pack["wipSafe"] is True
    assert current_governance_pack["requiredMigrations"] == []
    assert current_governance_pack["optionalMigrations"] == []
    assert any(
        "Governance and OSS contribution scaffolding" in change
        for change in current_governance_pack["behaviorChanges"]
    )

    current_readme_launch = cli.release_migration_report_data(
        version="0.6.267",
        products_tested=["methodology-framework"],
    )
    assert current_readme_launch["version"] == "0.6.267"
    assert current_readme_launch["wipSafe"] is True
    assert current_readme_launch["requiredMigrations"] == []
    assert current_readme_launch["optionalMigrations"] == []
    assert any(
        "Launch README rewrite" in change
        for change in current_readme_launch["behaviorChanges"]
    )

    current_security_hardening = cli.release_migration_report_data(
        version="0.6.268",
        products_tested=["methodology-framework"],
    )
    assert current_security_hardening["version"] == "0.6.268"
    assert current_security_hardening["wipSafe"] is True
    assert current_security_hardening["requiredMigrations"] == []
    assert current_security_hardening["optionalMigrations"] == []
    assert any(
        "Auto-update trust hardening" in change
        for change in current_security_hardening["behaviorChanges"]
    )

    current_launch = cli.release_migration_report_data(
        version="0.7.0",
        products_tested=["methodology-framework"],
    )
    assert current_launch["version"] == "0.7.0"
    assert current_launch["wipSafe"] is False
    assert current_launch["requiredMigrations"] == []
    assert any(
        item["id"] == "copy-makerkit-implementation-community-skill"
        for item in current_launch["optionalMigrations"]
    )
    assert any(
        "Initial public (open-core) release" in change
        for change in current_launch["behaviorChanges"]
    )
    assert any(
        "fresh installs default to a pinned update policy" in change
        for change in current_launch["behaviorChanges"]
    )
    assert any("not WIP-safe" in note for note in current_launch["rollbackNotes"])

    with pytest.raises(SystemExit, match="not declared for 0.6.269"):
        cli.release_migration_report_data(version="0.6.269")

    with pytest.raises(SystemExit, match="not declared for 0.7.2"):
        cli.release_migration_report_data(version="0.7.2")


def test_release_migration_report_0_8_9_startup_remediation(cli):
    current = cli.release_migration_report_data(
        version="0.8.9",
        products_tested=["methodology-framework"],
    )
    assert current["version"] == "0.8.9"
    assert current["wipSafe"] is False
    assert any(
        item["id"] == "reinstall-claude-launcher" and item["command"] == "tautline install-claude-launcher --force"
        for item in current["requiredMigrations"]
    )
    assert any("type -a <launcher-name>" in item["description"] for item in current["requiredMigrations"])
    assert any(
        "three-way exit contract: 0 clean, 1 integrity" in change and "2 debt-only" in change
        for change in current["behaviorChanges"]
    )
    assert any("methodology_status_blocking:" in change for change in current["behaviorChanges"])
    assert any("!= 0" in change for change in current["behaviorChanges"])
    assert any("SUPPRESSES user-provided launcher arguments" in change for change in current["behaviorChanges"])
    assert any("MINERVIT_PREPUSH_RECORDS_FILE" in change for change in current["behaviorChanges"])
    assert any("lane_coordination_stale_other_lanes" in change for change in current["behaviorChanges"])
    assert any("treated exit code 1 as the only failure signal" in note for note in current["rollbackNotes"])

    with pytest.raises(SystemExit, match="not declared for 0.8.10"):
        cli.release_migration_report_data(version="0.8.10")

    # 0.8.7 and 0.8.8 shipped their own migration-report branches (session-journal
    # opt-in, pending-journal gate) between this branch's fork point and this
    # release; both resolve, not raise, once merged in.
    report_0_8_7 = cli.release_migration_report_data(version="0.8.7")
    assert report_0_8_7["version"] == "0.8.7"
    assert report_0_8_7["wipSafe"] is True

    report_0_8_8 = cli.release_migration_report_data(version="0.8.8")
    assert report_0_8_8["version"] == "0.8.8"
    assert report_0_8_8["wipSafe"] is True


def test_release_migration_report_0_9_0_sanitized_instrumentation(cli):
    # Pin the 0.9.0 content explicitly: test_current_release_migration_report_exists_and_is_fresh
    # only asserts committed==generated (both from the same generator), so it cannot catch a wrong
    # wipSafe or a missing behavior-change note. This release changes security-sensitive publishing
    # behavior, so its migration contract must be nailed down.
    current = cli.release_migration_report_data(
        version="0.9.0",
        products_tested=["methodology-framework"],
    )
    assert current["version"] == "0.9.0"
    assert current["wipSafe"] is False
    assert any(
        item["id"] == "migrate-off-narrative-journal-publication"
        and item["command"] == "tautline publish-instrumentation-record --target ."
        for item in current["requiredMigrations"]
    )
    assert any(
        "disabled in 0.9.0" in item["description"] and "publish-instrumentation-record" in item["description"]
        for item in current["requiredMigrations"]
    )
    assert any("security behavior change" in change and "refuse for every adapter" in change for change in current["behaviorChanges"])
    assert any("zero product-information" in change and "tautline-telemetry-archive" in change for change in current["behaviorChanges"])
    assert any("instrumentation.enabled requires observabilityEvents.enabled" in change for change in current["behaviorChanges"])
    assert any("security-exception clause" in change for change in current["behaviorChanges"])
    assert any("Pinning back to 0.8.9 restores narrative session-journal publication" in note for note in current["rollbackNotes"])

    # Upper boundary: the next patch is not declared until it ships its own report.
    with pytest.raises(SystemExit, match="not declared for 0.9.2"):
        cli.release_migration_report_data(version="0.9.2")


def test_release_migration_report_0_9_1_no_dead_ends_and_repo_slug(cli):
    # Pin the 0.9.1 contract: trust-pin holds stop blocking launch (held, exit 0, remedy printed),
    # generated launchers gain the gate-repair path, and the dev-repo slug moves to
    # tautlines/tautline-dev with the legacy slug still accepted.
    current = cli.release_migration_report_data(
        version="0.9.1",
        products_tested=["methodology-framework"],
    )
    assert current["version"] == "0.9.1"
    assert current["wipSafe"] is True
    assert current["requiredMigrations"] == []
    assert any(
        item["id"] == "reinstall-claude-launcher-gate-repair"
        and item["command"] == "tautline install-claude-launcher --force"
        for item in current["optionalMigrations"]
    )
    assert any(
        item["id"] == "repoint-origin-to-tautline-dev" for item in current["optionalMigrations"]
    )
    assert any("`held` (exit 0)" in change and "update-repin" in change for change in current["behaviorChanges"])
    assert any("never advances to unverified code" in change for change in current["behaviorChanges"])
    assert any("exact executable remedy" in change for change in current["behaviorChanges"])
    assert any("legacy" in change and "tautlines/tautline-dev" in change for change in current["behaviorChanges"])


def test_current_release_migration_report_exists_and_is_fresh(cli):
    version = cli.methodology_version()
    path = Path(__file__).resolve().parents[1] / "docs" / "releases" / "migrations" / f"{version}.json"

    assert path.exists(), f"missing release migration report for current VERSION: {path}"
    committed = json.loads(path.read_text(encoding="utf-8"))
    generated = cli.release_migration_report_data(version=version, products_tested=committed.get("productsTested", []))

    assert committed == generated


def test_release_migration_report_check_reuses_committed_products(run_cli):
    res = run_cli("release-migration-report", "--version", "0.6.243", "--check")

    assert res.returncode == 0, res.stderr
    assert "release_migration_report_check: ok" in res.stdout


def test_public_release_current_tree_ships_no_private_source_adapters(cli):
    issues = cli.public_release_issues()
    private_adapter_paths = {issue["path"] for issue in issues if issue["code"] == "private-source-adapter"}

    assert private_adapter_paths == set()
    assert not [issue for issue in issues if issue["code"] == "live-host-in-private-adapter"]
    assert not [issue for issue in issues if issue["code"] == "account-id"]
    assert not [issue for issue in issues if issue["code"] == "private-adapter-path"]


def test_public_release_helper_primitives_are_served_from_package(cli, tmp_path):
    # Note: the copied-bin-without-src execution mode is not supported for extracted
    # helpers; public_release_module() always resolves the real package or raises SystemExit
    # (adapter_module()-style), so this only asserts wrapper/module parity, not a fallback.
    cli._PUBLIC_RELEASE_MODULE = None
    assert cli.public_release_module() is public_release

    placeholder_account = "123456" + "789012"
    touch_timestamp = "202607" + "061230"
    invalid_touch_timestamp = "202613" + "061230"
    assert cli.public_release_allowed_account_like_token(placeholder_account, f"account {placeholder_account}") == (
        public_release.allowed_account_like_token(
            placeholder_account,
            f"account {placeholder_account}",
            placeholder_account_ids=cli.PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS,
        )
    )
    assert cli.public_release_allowed_account_like_token(touch_timestamp, f"touch -t {touch_timestamp} file") == (
        public_release.allowed_account_like_token(
            touch_timestamp,
            f"touch -t {touch_timestamp} file",
            placeholder_account_ids=cli.PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS,
        )
    )
    assert cli.public_release_allowed_account_like_token(
        invalid_touch_timestamp,
        f"touch -t {invalid_touch_timestamp} file",
    ) is False

    allowed_doc = Path("docs/product/positioning.md")
    excluded_doc = Path("docs/product/internal-roadmap.md")
    internal_plan = Path("docs/superpowers/plans/private.md")
    readme = Path("README.md")
    for rel in (allowed_doc, excluded_doc, internal_plan, readme):
        assert cli.public_release_export_path_included(rel) == public_release.export_path_included(
            rel,
            allowed_product_docs=cli.PUBLIC_RELEASE_EXPORT_ALLOWED_PRODUCT_DOCS,
            excluded_prefixes=cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES,
        )

    marker_text = public_release.export_marker_text(
        version=cli.plugin_version(),
        marker_schema=cli.PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
        private_terms_source="file",
        private_terms_count=2,
    )
    assert cli.public_release_export_marker_text(private_terms_source="file", private_terms_count=2) == marker_text

    destination = tmp_path / "public-export"
    destination.mkdir()
    assert cli.public_release_export_destination_is_prior_export(destination) is False
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(marker_text, encoding="utf-8")
    assert cli.public_release_export_destination_is_prior_export(destination) is True
    assert public_release.export_destination_is_prior_export(
        destination,
        marker_name=cli.PUBLIC_RELEASE_EXPORT_MARKER,
        marker_schema=cli.PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
    ) is True

    issues: list[dict] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    cli.public_release_add_issue(
        issues,
        seen,
        "private-product-reference",
        tmp_path / "docs" / "public.md",
        "public surface references a real product/client adapter name",
        tmp_path,
        line=3,
    )
    public_release.add_issue(
        issues,
        seen,
        "private-product-reference",
        tmp_path / "docs" / "public.md",
        "public surface references a real product/client adapter name",
        repo_root=tmp_path,
        max_issues_per_rule=cli.PUBLIC_RELEASE_MAX_ISSUES_PER_RULE,
        line=3,
    )
    assert issues == [
        {
            "code": "private-product-reference",
            "path": "docs/public.md",
            "message": "public surface references a real product/client adapter name",
            "line": 3,
        }
    ]


@private_repo_only
def test_public_release_check_current_tree_blocks_only_history_until_public_cut(cli, capsys, monkeypatch):
    monkeypatch.delenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, raising=False)

    code = cli.public_release_check(Namespace(as_json=False))

    captured = capsys.readouterr()
    assert code == 1
    assert "public_release_check: blocked" in captured.out
    assert (
        "private-adapter-history adapters/projects/" in captured.out
        or "git-history-shallow .:" in captured.out
    )
    assert "private-source-adapter" not in captured.out
    assert "live-host-in-private-adapter" not in captured.out
    assert "account-id" not in captured.out
    assert "private-adapter-path" not in captured.out


@private_repo_only
def test_public_release_check_cli_current_tree_json_blocks_only_history_until_public_cut(run_cli):
    result = run_cli("public-release-check", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "private-source-adapter" not in codes
    assert "live-host-in-private-adapter" not in codes
    assert "account-id" not in codes
    assert "private-adapter-path" not in codes
    assert codes <= {
        "private-adapter-history",
        "git-history-shallow",
        "same-history-remote",
        "release-update-overdue",
        "release-update-current-missing",
    }
    assert "private-adapter-history" in codes or "git-history-shallow" in codes


@private_repo_only
def test_public_release_check_current_tree_json_blocks_only_history_with_private_terms(
    cli, capsys, monkeypatch
):
    monkeypatch.setenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, _known_public_release_private_terms())

    code = cli.public_release_check(Namespace(as_json=True))

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "private-source-adapter" not in codes
    assert "live-host-in-private-adapter" not in codes
    assert "account-id" not in codes
    assert "private-adapter-path" not in codes
    assert "private-product-reference" not in codes
    assert codes <= {
        "private-adapter-history",
        "git-history-shallow",
        "same-history-remote",
        "release-update-overdue",
        "release-update-current-missing",
    }
    assert "private-adapter-history" in codes or "git-history-shallow" in codes


def test_public_release_check_blocks_private_adapter_fixture(cli, tmp_path):
    adapter_dir = tmp_path / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    (adapter_dir / "example-saas.json").write_text(
        '{"project":"Example SaaS","repo":"example/example-saas"}\n',
        encoding="utf-8",
    )
    (adapter_dir / private_name).write_text(
        '{"project":"Private Customer","repo":"example/private","healthCheck":"https://private.example.test"}\n',
        encoding="utf-8",
    )

    issues = cli.public_release_issues(tmp_path)
    private_adapter_paths = {issue["path"] for issue in issues if issue["code"] == "private-source-adapter"}

    assert private_adapter_paths == {private_rel}
    assert "adapters/projects/example-saas.json" not in private_adapter_paths


def test_public_release_check_allows_touch_timestamp_literals(cli, tmp_path):
    script = tmp_path / "validate.sh"
    script.write_text('touch -t 202001010000 "${STALE_MONITOR_LOG}"\n', encoding="utf-8")

    issues = cli.public_release_issues(tmp_path)

    assert not [issue for issue in issues if issue["code"] == "account-id"]


def test_public_release_check_scans_impl_review_ledgers_without_hash_noise(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "docs" / "superpowers" / "plans" / ".impl-reviews" / "review.json"
    ledger.parent.mkdir(parents=True)
    private_term = "Private Customer Alpha"
    leaked_account = "234567" + "890123"
    ledger.write_text(
        json.dumps(
            {
                "diff_sha256": "abc123456789012def",
                "branch": "feature/docs",
                "classified_findings": [
                    {
                        "evidence": f"Private note for {private_term}",
                    },
                    {"evidence": f"Found account {leaked_account} in free-form review text"},
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, private_term)

    issues = cli.public_release_issues(tmp_path)
    issue_codes = {issue["code"] for issue in issues}

    assert "private-product-reference" in issue_codes
    assert "account-id" in issue_codes
    assert not [
        issue
        for issue in issues
        if issue["code"] == "account-id" and issue["line"] == 2
    ]


def test_public_release_check_supports_private_term_denylist_after_adapter_removal(cli, tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    private_term = "Fi" + "nch"
    readme.write_text(f"Legacy customer codename: {private_term}\n", encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    issues = cli.public_release_issues(tmp_path)

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 1,
        "message": "public surface references a real product/client adapter name",
    } in issues


def test_public_release_check_supports_private_terms_file_after_adapter_removal(cli, tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    private_term = "Private Customer Alpha"
    readme.write_text(f"Legacy customer codename: {private_term}\n", encoding="utf-8")
    terms_file = tmp_path / "private-terms.txt"
    terms_file.write_text("# untracked local denylist\nPrivate Customer Alpha\n", encoding="utf-8")
    monkeypatch.delenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, raising=False)

    issues = cli.public_release_issues(tmp_path, private_terms_file=terms_file)

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 1,
        "message": "public surface references a real product/client adapter name",
    } in issues


def test_public_release_private_terms_file_accepts_json_string_array(cli, tmp_path):
    terms_file = tmp_path / "private-terms.json"
    terms_file.write_text('["Private Customer Alpha", "Private Customer Beta"]\n', encoding="utf-8")

    assert cli.public_release_private_terms([], terms_file) == [
        "Private Customer Alpha",
        "Private Customer Beta",
    ]


def test_public_release_check_blocks_private_adapter_paths_in_git_history(cli, tmp_path):
    repo = tmp_path / "repo"
    adapter_dir = repo / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(repo)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=repo, check=True)
    private_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove private adapter"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    assert {
        "code": "private-adapter-history",
        "path": private_rel,
        "message": "private adapter path remains in git history; rewrite history before flipping this repository public or publish from a clean public repo",
    } in issues


def test_public_release_history_scan_ignores_example_and_message_only_mentions(cli, tmp_path):
    repo = tmp_path / "repo"
    adapter_dir = repo / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(repo)
    example_adapter = adapter_dir / "example-saas.json"
    example_adapter.write_text('{"project":"Example SaaS","repo":"example/example-saas"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "adapters/projects/example-saas.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add example adapter"], cwd=repo, check=True)
    example_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=repo, check=True)
    private_ref = "adapters/projects/" + "private-customer.json"
    subprocess.run(["git", "commit", "-q", "-m", f"message mentions {private_ref} only"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    assert not [issue for issue in issues if issue["code"] == "private-adapter-history"]


def test_public_release_history_fails_closed_for_shallow_checkout(cli, tmp_path):
    source = tmp_path / "source"
    adapter_dir = source / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(source)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=source, check=True)
    private_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove private adapter"], cwd=source, check=True)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{source}", str(shallow)], check=True)

    issues = cli.public_release_issues(shallow)

    assert any(issue["code"] == "git-history-shallow" for issue in issues)


def test_public_release_check_blocks_same_history_remote(cli, tmp_path):
    repo = tmp_path / "repo"
    remote = tmp_path / "same-history.git"
    repo.mkdir()
    _init_git_repo(repo)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    (repo / "README.md").write_text("# Public Candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    same_history = [issue for issue in issues if issue["code"] == "same-history-remote"]
    assert same_history
    assert same_history[0]["path"] == "."
    assert "target remote 'origin' shares this repository's root commit" in same_history[0]["message"]
    assert "public-release-export" in same_history[0]["message"]


def test_public_release_root_commits_accepts_sha256_hashes(cli, tmp_path, monkeypatch):
    sha256_root = "a" * 64

    def fake_run_command(command, cwd=None, timeout=None):
        if command[:4] == ["git", "-C", str(tmp_path), "rev-list"]:
            return 0, sha256_root + "\n", ""
        return 1, "", "unexpected command"

    monkeypatch.setattr(cli, "run_command", fake_run_command)

    assert cli.public_release_root_commits(tmp_path) == {sha256_root}


def test_public_release_export_builds_clean_repo_without_private_history(cli, tmp_path):
    source = tmp_path / "source"
    adapter_dir = source / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(source)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=source, check=True)
    private_adapter.unlink()
    example_adapter = adapter_dir / "example-saas.json"
    example_adapter.write_text('{"project":"Example SaaS","repo":"example/example-saas"}\n', encoding="utf-8")
    (source / "README.md").write_text("# Public Candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "public tree"], cwd=source, check=True)

    source_issues = cli.public_release_issues(source)
    destination = tmp_path / "public"
    result = cli.public_release_export_repository(source, destination)
    export_issues = cli.public_release_issues(destination)

    assert any(issue["code"] == "private-adapter-history" for issue in source_issues)
    assert result["files"] == 2
    assert result["commit"] != "unavailable"
    assert (destination / ".git").exists()
    assert (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).exists()
    assert (destination / "README.md").read_text(encoding="utf-8") == "# Public Candidate\n"
    assert not (destination / private_rel).exists()
    assert export_issues == []


def test_public_release_export_excludes_dependabot_config(cli):
    # The public repository is a force-pushed mirror: Dependabot PRs opened there
    # can never merge and always fail the release-change contract, so dependency
    # intake stays private and the config must not be exported.
    assert cli.public_release_export_path_included(Path(".github/dependabot.yml")) is False
    assert cli.public_release_export_path_included(Path(".github/workflows/ci-python.yml")) is True


def test_public_release_export_refuses_ancestor_destination_even_with_force(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    try:
        cli.public_release_export_repository(source, tmp_path, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("ancestor destination should be refused")

    assert "destination must be outside" in message
    assert source.exists()


def test_public_release_export_force_only_replaces_prior_export(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / "unrelated.txt").write_text("do not delete\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("force should not replace an unmarked directory")

    assert "only replaces a prior public-release-export destination" in message
    assert (destination / "unrelated.txt").exists()

    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    result = cli.public_release_export_repository(source, destination, force=True)

    assert result["issues"] == []
    assert (destination / "README.md").exists()
    assert not (destination / "unrelated.txt").exists()


def test_public_release_export_refuses_dirty_source_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dirty tracked file should be refused before replacing a prior export")

    assert "dirty tracked files are not exported by default" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_preserves_safe_relative_symlink(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    _symlink_or_skip("README.md", source / "README-link.md")
    subprocess.run(["git", "add", "README.md", "README-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README-link.md").is_symlink()
    assert os.readlink(tmp_path / "public" / "README-link.md") == "README.md"


def test_public_release_export_refuses_escaping_symlink_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not export\n", encoding="utf-8")
    _symlink_or_skip(str(outside), source / "secret-link.txt")
    subprocess.run(["git", "add", "secret-link.txt"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("escaping symlink should be refused before replacing a prior export")

    assert "absolute symlink targets are not exported" in message or "symlink target escapes" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_relative_symlink_that_would_escape_export(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    _symlink_or_skip("../source/README.md", source / "source-loop-link.md")
    subprocess.run(["git", "add", "README.md", "source-loop-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("relative symlink that would escape export should be refused")

    assert "symlink target escapes or is missing: source-loop-link.md -> ../source/README.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_dangling_symlink_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    _symlink_or_skip("missing.md", source / "missing-link.md")
    subprocess.run(["git", "add", "missing-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dangling symlink should be refused before replacing a prior export")

    assert "symlink target escapes or is missing: missing-link.md -> missing.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_symlink_loop_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    _symlink_or_skip("loop-b.md", source / "loop-a.md")
    _symlink_or_skip("loop-a.md", source / "loop-b.md")
    subprocess.run(["git", "add", "loop-a.md", "loop-b.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("symlink loop should be refused before replacing a prior export")

    assert "symlink target escapes or is missing: loop-a.md -> loop-b.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_checks_private_terms_in_exported_tree(cli, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    private_term = "Fi" + "nch"
    (source / "README.md").write_text(f"# Public Candidate\n\nLegacy codename: {private_term}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 3,
        "message": "public surface references a real product/client adapter name",
    } in result["issues"]


def test_public_release_export_defaults_to_tracked_files_only(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "scratch.md").write_text("draft notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert not (tmp_path / "public" / "scratch.md").exists()


def test_public_release_export_excludes_internal_docs_but_keeps_public_product_docs(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    tracked_files = {
        "README.md": "# Source\n",
        "docs/backlog/methodology-backlog.md": "internal backlog\n",
        "docs/productization/audit-disposition-register.md": "internal audit\n",
        "docs/superpowers/plans/refactor.md": "internal plan\n",
        "docs/product/telemetry-consent.md": "internal telemetry\n",
        "docs/product/a11y-i18n.md": "internal a11y\n",
        "docs/product/positioning.md": "public positioning\n",
        "docs/product/support-sla-model.md": "public support\n",
        # The framework's own self-adapter files are maintainer-lane config that
        # references private planning conventions; they must not ship in the export
        # (the self-adapter gates skip in export trees since 0.6.265, so the export
        # does not need them).
        ".minervit/adapter.json": '{"project": "self"}\n',
        ".minervit-ai-delivery.json": '{"project": "self"}\n',
        ".tautline/adapter.json": '{"project": "self"}\n',
        ".tautline.json": '{"project": "self"}\n',
    }
    for rel, text in tracked_files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert not (tmp_path / "public" / "docs/backlog/methodology-backlog.md").exists()
    assert not (tmp_path / "public" / "docs/productization/audit-disposition-register.md").exists()
    assert not (tmp_path / "public" / "docs/superpowers/plans/refactor.md").exists()
    assert not (tmp_path / "public" / "docs/product/telemetry-consent.md").exists()
    assert not (tmp_path / "public" / "docs/product/a11y-i18n.md").exists()
    assert (tmp_path / "public" / "docs/product/positioning.md").exists()
    assert (tmp_path / "public" / "docs/product/support-sla-model.md").exists()
    assert not (tmp_path / "public" / ".minervit").exists()
    assert not (tmp_path / "public" / ".minervit/adapter.json").exists()
    assert not (tmp_path / "public" / ".minervit-ai-delivery.json").exists()
    assert not (tmp_path / "public" / ".tautline").exists()
    assert not (tmp_path / "public" / ".tautline/adapter.json").exists()
    assert not (tmp_path / "public" / ".tautline.json").exists()
    # The export marker (same .minervit- name stem, different string) must NOT be
    # swept up by the self-adapter exclusion.
    assert (tmp_path / "public" / cli.PUBLIC_RELEASE_EXPORT_MARKER).exists()


def test_public_release_export_ignores_dirty_and_untracked_excluded_internal_docs(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    internal = source / "docs" / "backlog" / "methodology-backlog.md"
    readme.write_text("# Source\n", encoding="utf-8")
    internal.parent.mkdir(parents=True)
    internal.write_text("internal backlog\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    internal.write_text("internal backlog dirty\n", encoding="utf-8")
    untracked = source / "docs" / "superpowers" / "plans" / "scratch.md"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("scratch\n", encoding="utf-8")

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert cli.public_release_dirty_tracked_paths(source) == []
    assert cli.public_release_untracked_export_paths(source) == []
    assert (tmp_path / "public" / "README.md").exists()
    assert not (tmp_path / "public" / "docs/backlog/methodology-backlog.md").exists()
    assert not (tmp_path / "public" / "docs/superpowers/plans/scratch.md").exists()


def test_public_release_export_can_include_untracked_when_explicit(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "new-doc.md").write_text("new public doc\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public", include_untracked=True)

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert (tmp_path / "public" / "new-doc.md").exists()


def test_public_release_export_refuses_dirty_tracked_by_default(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, tmp_path / "public")
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dirty tracked file should be refused by default")

    assert "dirty tracked files are not exported by default" in message
    assert not (tmp_path / "public").exists()


def test_public_release_export_can_include_dirty_tracked_when_explicit(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")

    result = cli.public_release_export_repository(source, tmp_path / "public", include_working_tree=True)

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").read_text(encoding="utf-8") == "# Source\n\nUncommitted edit\n"


def test_public_release_export_cli_refuses_dirty_tracked_checkout(tmp_path):
    source = tmp_path / "public-release-export-dirty-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    with cli_path.open("a", encoding="utf-8") as fh:
        fh.write("\n# validation dirty tracked fixture\n")

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(tmp_path / "public-release-export-default"),
            "--write",
        ],
        env={
            **os.environ,
            "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS": _known_public_release_private_terms(),
        },
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert f"public_release_export_source: {source.resolve()}" in result.stdout
    assert "public_release_export_error: dirty tracked files are not exported by default" in result.stderr
    assert not (tmp_path / "public-release-export-default").exists()


def test_public_release_export_cli_writes_current_tree_candidate(tmp_path):
    destination = tmp_path / "public-release-export"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env={
            **os.environ,
            "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS": _known_public_release_private_terms(),
        },
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert f"public_release_export_source: {CLI_PATH.parents[1].resolve()}" in result.stdout
    assert "public_release_export_check: ok" in result.stdout
    assert "release-update-current-missing" not in result.stdout
    assert "release-update-overdue" not in result.stdout
    assert "public_release_export_commit:" in result.stdout
    assert (destination / ".git").exists()
    assert (destination / ".minervit-public-release-export.json").exists()


def test_public_release_export_cli_accepts_private_terms_file_without_leaking_terms(tmp_path):
    destination = tmp_path / "public-release-export"
    terms_file = tmp_path / "private-terms.txt"
    private_term = "Acme" + " Confidential " + "Zulu"
    terms_file.write_text(private_term + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "public_release_export_private_terms_source: file" in result.stdout
    assert "public_release_export_private_terms_count: 1" in result.stdout
    assert private_term not in result.stdout
    assert private_term not in result.stderr
    marker = (destination / ".minervit-public-release-export.json").read_text(encoding="utf-8")
    marker_payload = json.loads(marker)
    assert marker_payload["privateTermsSource"] == "file"
    assert marker_payload["privateTermsCount"] == 1
    assert private_term not in marker


def test_public_release_export_copied_cli_accepts_json_private_terms_file(tmp_path):
    source = tmp_path / "copied-cli-json-terms-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-json-terms-export"
    first_term = "Acme" + " Confidential " + "Json"
    second_term = "Beta" + " Confidential " + "Json"
    terms_file = tmp_path / "private-terms.json"
    terms_file.write_text(json.dumps([first_term, second_term]), encoding="utf-8")
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "public_release_export_private_terms_source: file" in result.stdout
    assert "public_release_export_private_terms_count: 2" in result.stdout
    assert first_term not in result.stdout
    assert second_term not in result.stdout
    assert not destination.exists()


# Note: the copied-bin-without-src execution mode is not supported for extracted
# public-release helpers; public_release_module() now hard-requires src/minervit_methodology
# (SystemExit otherwise, adapter_module()-style), so the former
# test_public_release_export_copied_cli_uses_fallback_with_stale_public_release_package and
# test_public_release_export_copied_cli_uses_fallback_when_public_release_submodule_missing
# copied-bin-standalone-parity tests were deleted.


def test_public_release_export_copied_cli_refuses_private_terms_file_inside_source(tmp_path):
    source = tmp_path / "copied-cli-source-terms-source"
    cli_path = _copy_cli_with_package(source)
    terms_file = source / "private-terms.txt"
    terms_file.write_text("Private Customer Alpha\n", encoding="utf-8")
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src", "private-terms.txt"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-source-terms-export"

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--write",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "private terms file must be outside the methodology repository" in result.stderr
    assert not destination.exists()


def test_public_release_export_copied_cli_refuses_private_terms_file_inside_destination(tmp_path):
    source = tmp_path / "copied-cli-destination-terms-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-destination-terms-export"
    terms_file = destination / "private-terms.txt"

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--write",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "private terms file must be outside the public-release-export destination" in result.stderr
    assert not destination.exists()


def test_public_release_export_refuses_private_terms_file_inside_source(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    terms_file = source / "private-terms.txt"
    terms_file.write_text("Private Customer Alpha\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=True,
            include_working_tree=True,
            allow_empty_private_terms=False,
            private_terms_file=terms_file,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "private terms file must be outside the methodology repository" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_refuses_private_terms_file_inside_destination(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "public"
    terms_file = destination / "private-terms.txt"
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=destination,
            write=True,
            force=False,
            include_untracked=True,
            include_working_tree=True,
            allow_empty_private_terms=False,
            private_terms_file=terms_file,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "private terms file must be outside the public-release-export destination" in captured.err
    assert not destination.exists()


def test_public_release_export_cli_refuses_missing_private_terms(tmp_path):
    destination = tmp_path / "public-release-export"
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 2
    assert "no private product/client terms configured" in result.stderr
    assert "--private-terms-file" in result.stderr
    assert not destination.exists()


def test_public_release_export_command_reports_exported_tree_release_update_blockers(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (source / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] - 2026-07-05\n\n### Changed\n\n- Test release.\n",
        encoding="utf-8",
    )
    delivery = source / "docs" / "releases" / "release-update-delivery.json"
    delivery.parent.mkdir(parents=True)
    delivery.write_text(
        '{"schema":"minervit-release-update-delivery/v1","delivered":{}}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "public_release_export_check: blocked" in captured.out
    assert "release-update-current-missing" in captured.out
    assert "docs/releases/release-update-delivery.json" in captured.out


def test_public_release_export_command_refuses_untracked_by_default(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "scratch.md").write_text("draft notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "untracked files are not exported by default" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_command_refuses_dirty_tracked_by_default(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "dirty tracked files are not exported by default" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_command_warns_to_delete_blocked_candidate(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    private_term = "Fi" + "nch"
    (source / "README.md").write_text(f"# Source\n\nCodename: {private_term}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", source)
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=False,
        )
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "public_release_export_check: blocked" in captured.out
    assert "public_release_export_warning: delete the entire blocked candidate directory" in captured.out
    assert "including its .git history, before sharing it" in captured.out
    assert (tmp_path / "public" / ".git").exists()


def test_deprecated_command_warns_without_dispatch_wrapper_exit_change(run_cli, tmp_path):
    result = run_cli("goal-tracker-status", "--target", str(tmp_path))

    assert "deprecation_warning: command 'goal-tracker-status' is deprecated" in result.stderr
    assert result.returncode != 0
