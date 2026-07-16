"""RCA: the framework posts a Google Chat card per release via `publish-release-update`, but the
command kept no record of what was posted and nothing in the release flow called it, so the
stakeholder-update cadence silently lapsed (0.6.94->0.6.113 shipped without updates). This gate
mirrors milestone-update delivery accountability: a delivery ledger, a status command, and a
maintainer public-release check that fails closed when a release update was never delivered.
"""

import argparse
import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

from minervit_methodology import gitutil, paths, profiles, releases, telemetry, util


def test_version_key_orders_numerically(cli):
    assert cli.release_update_version_key("0.6.9") < cli.release_update_version_key("0.6.10")
    assert cli.release_update_version_key("0.6.113") > cli.release_update_version_key("0.6.99")
    assert cli.release_update_version_key("1.0.0") > cli.release_update_version_key("0.9.9")


def test_changelog_bullets_join_wrapped_lines(cli):
    body = """### Changed

- Moved the long narrative release log off the main branch and replaced it with
  a small current-version stub.
- Preserved runtime behavior.
"""

    assert cli.changelog_bullets(body) == [
        "Moved the long narrative release log off the main branch and replaced it with a small current-version stub.",
        "Preserved runtime behavior.",
    ]


def test_release_helpers_are_served_from_package_through_cli_wrapper(cli):
    current = cli.plugin_version()
    blocks = cli.changelog_release_blocks()

    for name in (
        "release_update_version_key",
        "release_update_delivery_file",
        "release_update_version_file",
        "release_update_delivery_load",
        "release_update_delivered_versions",
        "release_update_suspended_versions",
        "release_update_accounted_versions",
        "release_update_record_delivery",
        "release_update_overdue",
        "release_update_current_version",
        "release_update_overdue_versions",
        "release_update_public_release_issues",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(releases, name))

    assert cli.changelog_release_block(current) == releases.changelog_release_block(current)
    assert cli.changelog_bullets("- One\n  wrapped\n- Two\n") == releases.changelog_bullets("- One\n  wrapped\n- Two\n")
    assert cli.release_migration_report_path(current) == releases.release_migration_report_path(current)
    assert cli.release_update_content(current) == releases.release_update_content(current)
    assert cli.release_update_block(current) == releases.release_update_block(current)
    assert cli.release_update_lines(current) == releases.release_update_lines(current)
    assert cli.release_update_payload(current) == releases.release_update_payload(
        current,
        card_text=cli.milestone_update_card_text,
        slugify_func=cli.slugify,
    )
    assert cli.release_update_versions(argparse.Namespace(version=current, last=None)) == releases.release_update_versions(
        version=current,
        last=None,
        current_version=cli.plugin_version(),
        blocks=cli.changelog_release_blocks(),
    )
    assert cli.release_update_versions(argparse.Namespace(version=None, last=2)) == releases.release_update_versions(
        version=None,
        last=2,
        current_version=cli.plugin_version(),
        blocks=cli.changelog_release_blocks(),
    )
    # Multi-version `--last N` ordering is exercised against synthetic blocks: the real
    # changelog carries only the current single launch entry post-squash.
    synthetic_blocks = [
        {"version": "0.7.2", "date": "2026-08-01", "body": ""},
        {"version": "0.7.1", "date": "2026-07-20", "body": ""},
        {"version": "0.7.0", "date": "2026-07-08", "body": ""},
    ]
    assert releases.release_update_versions(
        version=None, last=2, current_version="0.7.2", blocks=synthetic_blocks
    ) == [synthetic_blocks[1]["version"], synthetic_blocks[0]["version"]]
    assert cli.release_update_versions(argparse.Namespace(version="0.6.1", last=1)) == [blocks[0]["version"]]
    with pytest.raises(SystemExit, match="--last must be positive"):
        cli.release_update_versions(argparse.Namespace(version=None, last=-1))
    assert cli.release_update_version_key("0.6.113") == releases.release_update_version_key("0.6.113")
    assert cli.release_update_overdue(["0.6.113", "0.6.112"], {"0.6.112"}, "0.6.114") == (
        releases.release_update_overdue(["0.6.113", "0.6.112"], {"0.6.112"}, "0.6.114")
    )
    status_summary = releases.release_update_status_summary(
        current="0.6.114",
        delivered={"0.6.113"},
        suspended={"0.6.112"},
        overdue=["0.6.111"],
        require_current=True,
    )
    assert status_summary["current_required_missing"] is True
    assert releases.release_update_status_lines(status_summary) == [
        "release_update_current_version: 0.6.114",
        "release_update_current_delivered: no (required for release check)",
        "release_update_delivered_count: 1",
        "release_update_suspended_count: 1",
        "release_update_overdue:",
        "  - 0.6.111 (no Google Chat delivery marker; run: minervit-methodology publish-release-update --version 0.6.111)",
        "release_update_current_required_missing:",
        "  - 0.6.114 (current release marker required by maintainer release check; run: minervit-methodology publish-release-update --version 0.6.114)",
    ]


def test_util_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    assert cli.slugify("Hello World!") == util.slugify("Hello World!")
    assert cli.slugify("") == util.slugify("") == "lane"
    assert cli.version_tuple("0.6.204") == util.version_tuple("0.6.204") == (0, 6, 204)
    assert cli.title_from_slug("my-cool-project") == util.title_from_slug("my-cool-project") == "My Cool Project"
    assert cli.normalize_repo_slug("git@github.com:Owner/Repo.git") == util.normalize_repo_slug("git@github.com:Owner/Repo.git") == "owner/repo"
    assert cli.command_string(["a b", "c"]) == util.command_string(["a b", "c"]) == "'a b' c"
    assert cli.parse_duration_seconds("2h") == util.parse_duration_seconds("2h") == 7200
    assert cli.path_is_under(tmp_path / "x", tmp_path) is True
    assert cli.path_display(tmp_path, tmp_path / "a" / "b.txt") == "a/b.txt"
    config_env = tmp_path / "methodology.env"
    secrets_env = tmp_path / "secrets.zsh"
    config_env.write_text('export X_TEST_WEBHOOK="https://example.invalid/configured"\n', encoding="utf-8")
    secrets_env.write_text('export X_TEST_SECRET="https://example.invalid/secret"\n', encoding="utf-8")
    assert cli.user_config_env_value("X_TEST_WEBHOOK", config_env) == util.user_config_env_value("X_TEST_WEBHOOK", config_env)
    assert cli.user_config_env_value("X_TEST_WEBHOOK", config_env) == "https://example.invalid/configured"
    assert (
        util.env_value_with_user_config_fallback("X_TEST_SECRET", config_env, secrets_env)
        == "https://example.invalid/secret"
    )
    target = tmp_path / "atomic.txt"
    cli.write_text_atomic(target, "content")
    assert target.read_text(encoding="utf-8") == "content"
    assert (
        cli.file_sha256(target)
        == util.file_sha256(target)
        == "ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73"
    )


def test_git_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "remote.origin.url", "git@github.com:Owner/Repo.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    for name in (
        "infer_repo_slug",
        "target_is_git_worktree",
        "run_git",
        "current_branch_name",
        "git_branch_upstream",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(gitutil, name))

    assert cli.infer_repo_slug(tmp_path) == gitutil.infer_repo_slug(tmp_path) == "Owner/Repo"
    assert cli.target_is_git_worktree(tmp_path) == gitutil.target_is_git_worktree(tmp_path) is True
    assert cli.run_git(tmp_path, ["rev-parse", "--is-inside-work-tree"]) == gitutil.run_git(
        tmp_path, ["rev-parse", "--is-inside-work-tree"]
    ) == "true"
    assert cli.current_branch_name(tmp_path) == gitutil.current_branch_name(tmp_path) == "main"
    assert cli.git_branch_upstream(tmp_path) == gitutil.git_branch_upstream(tmp_path) == ""


def test_git_branch_wrappers_keep_cli_run_git_monkeypatch_seam(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "run_git",
        lambda target, args: (
            "feature/docs-123"
            if args == ["branch", "--show-current"]
            else "origin/feature/docs-123"
            if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
            else "unavailable"
        ),
    )

    assert cli.current_branch_name(tmp_path) == "feature/docs-123"
    assert cli.git_branch_upstream(tmp_path) == "origin/feature/docs-123"


def test_path_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    data = {
        "laneState": {
            "goalRun": ".ai-work/GOAL_RUN.json",
            "milestoneRun": ".ai-work/MILESTONE_RUN.json",
        },
        "goalTracker": {"enabled": False},
        "backlogProvider": {"enabled": True, "provider": "github"},
    }
    markdown = """# Title

## First
Alpha

## Second
Beta
"""

    for name in (
        "configured_path",
        "goal_run_path",
        "milestone_run_path",
        "markdown_section",
        "goal_tracker_config",
        "backlog_provider_config",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(paths, name))

    assert cli.configured_path(tmp_path, "docs/spec.md") == paths.configured_path(tmp_path, "docs/spec.md")
    assert cli.configured_path(tmp_path, "docs/spec.md") == tmp_path / "docs" / "spec.md"
    assert cli.goal_run_path(data, tmp_path) == paths.goal_run_path(data, tmp_path)
    assert cli.goal_run_path(data, tmp_path) == tmp_path / ".ai-work" / "GOAL_RUN.json"
    assert cli.milestone_run_path(data, tmp_path) == paths.milestone_run_path(data, tmp_path)
    assert cli.milestone_run_path(data, tmp_path) == tmp_path / ".ai-work" / "MILESTONE_RUN.json"
    assert cli.markdown_section(markdown, "## First") == paths.markdown_section(markdown, "## First")
    assert cli.markdown_section(markdown, "## First") == "Alpha"
    assert cli.markdown_section(markdown, "## Missing") == ""
    assert cli.goal_tracker_config(data) == paths.goal_tracker_config(data) == {"enabled": False}
    assert cli.backlog_provider_config(data) == paths.backlog_provider_config(data) == {
        "enabled": True,
        "provider": "github",
    }


def test_work_profile_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    profile_cfg = {
        "allowedPaths": ["docs/**", "*.md"],
        "allowedExtensions": [".md", ".png"],
        "blockedPaths": ["src/**"],
        "maxFileBytes": 10,
    }
    metadata = {
        "docs/large.png": {"mode": "100644", "type": "blob", "size": 11},
        "docs/link.png": {"mode": "120000", "type": "blob", "size": 3},
    }

    for name in (
        "path_matches_work_profile_pattern",
        "git_blob_sizes",
        "work_profile_committed_file_metadata",
        "work_profile_file_issues",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(profiles, name))

    assert cli.path_matches_work_profile_pattern("docs/wireframes/signup.png", "docs/**") is True
    assert cli.path_matches_work_profile_pattern("docs/wireframes/signup.png", "*.png") is False
    assert cli.path_matches_work_profile_pattern("README.md", "*.md") is True
    assert cli.work_profile_file_issues(
        {},
        tmp_path,
        "product-docs",
        profile_cfg,
        ["src/app.ts", "docs/spec.mdx", "docs/large.png", "docs/link.png"],
        event="pre-push",
        file_metadata=metadata,
    ) == profiles.work_profile_file_issues(
        {},
        tmp_path,
        "product-docs",
        profile_cfg,
        ["src/app.ts", "docs/spec.mdx", "docs/large.png", "docs/link.png"],
        event="pre-push",
        file_metadata=metadata,
    )
    assert cli.work_profile_file_issues(
        {},
        tmp_path,
        "product-docs",
        profile_cfg,
        ["src/app.ts", "docs/spec.mdx", "docs/large.png", "docs/link.png"],
        event="pre-push",
        file_metadata=metadata,
    ) == [
        "src/app.ts: blocked path for product-docs; switch to development for code/config/generated artifacts",
        "docs/spec.mdx: extension .mdx is not allowed in product-docs",
        "docs/large.png: file is 11 bytes, over product-docs maxFileBytes=10; use adapter-approved LFS/asset policy or reduce the artifact",
        "docs/link.png: symlinks are not allowed in product-docs",
    ]


def test_telemetry_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY", "1")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_TELEMETRY_PATH", str(log))

    for name in (
        "telemetry_enabled",
        "telemetry_path",
        "record_gate_telemetry",
        "guard_log_event",
        "parse_guard_report_since",
        "guard_event_after_since",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(telemetry, name))

    assert cli.telemetry_enabled() == telemetry.telemetry_enabled() is True
    assert cli.telemetry_path() == telemetry.telemetry_path() == log
    cli.record_gate_telemetry("response-guard-stop", "block", error_count=2, secret_path="/tmp/secret")
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["gate"] == "response-guard-stop"
    assert record["error_count"] == 2
    assert "secret_path" not in record
    cli.guard_log_event(tmp_path, "stop.example", True, "phrase", "x" * 250)
    event = json.loads((tmp_path / ".ai-runs" / "guard-events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert event["check_id"] == "stop.example"
    assert event["mechanism"] == "phrase"
    assert len(event["detail"]) == 200
    since = cli.parse_guard_report_since("2026-07-06T00:00:00Z")
    assert since == telemetry.parse_guard_report_since("2026-07-06T00:00:00Z")
    assert cli.guard_event_after_since({"ts": "2026-07-06T00:00:01Z"}, since) is True


def test_overdue_excludes_current_and_future(cli):
    # versions are newest-first, mirroring changelog_release_blocks()
    versions = ["0.6.114", "0.6.113", "0.6.112"]
    # current 0.6.113 not yet delivered (its card posts after merge) -> not overdue;
    # 0.6.114 is future relative to current -> not overdue; 0.6.112 prior and delivered -> clean.
    assert cli.release_update_overdue(versions, {"0.6.112"}, "0.6.113") == []


def test_overdue_flags_unmarked_prior_release(cli):
    versions = ["0.6.114", "0.6.113", "0.6.112"]
    # current is 0.6.114; prior shipped 0.6.113 has no marker -> overdue.
    assert cli.release_update_overdue(versions, {"0.6.112"}, "0.6.114") == ["0.6.113"]


def test_overdue_clean_when_all_prior_delivered(cli):
    versions = ["0.6.114", "0.6.113", "0.6.112"]
    assert cli.release_update_overdue(versions, {"0.6.113", "0.6.112"}, "0.6.114") == []


def test_record_and_load_roundtrip_is_idempotent(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "release-update-delivery.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    cli.release_update_record_delivery("0.6.114")
    cli.release_update_record_delivery("0.6.114")  # re-record must not duplicate
    data = json.loads(ledger.read_text())
    assert data["schema"] == cli.RELEASE_UPDATE_DELIVERY_SCHEMA
    assert list(data["delivered"].keys()) == ["0.6.114"]
    assert data["delivered"]["0.6.114"]["via"] == "publish-release-update"
    assert cli.release_update_delivered_versions() == {"0.6.114"}


def test_release_update_wrapper_sync_does_not_leak_package_constants(cli, tmp_path, monkeypatch):
    original = releases.RELEASE_UPDATE_DELIVERY_FILE
    ledger = tmp_path / "release-update-delivery.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)

    cli.release_update_record_delivery("0.6.114")

    assert json.loads(ledger.read_text(encoding="utf-8"))["delivered"]["0.6.114"]["via"] == "publish-release-update"
    assert releases.RELEASE_UPDATE_DELIVERY_FILE == original


def test_release_update_suspended_versions_require_documented_scope(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "release-update-delivery.json"
    current = cli.plugin_version()
    ledger.write_text(
        json.dumps(
            {
                "schema": cli.RELEASE_UPDATE_DELIVERY_SCHEMA,
                "delivered": {},
                "suspended": {
                    current: {
                        "at": "2026-07-05T00:00:00+00:00",
                        "via": "operator-instruction",
                        "scope": "refactor-release-card-suspension",
                        "reason": "Release cards are suspended for productization refactor releases.",
                    },
                    "0.6.211": {
                        "at": "2026-07-05T00:00:00+00:00",
                        "via": "operator-instruction",
                        "scope": "",
                        "reason": "missing scope",
                    },
                    "0.6.210": {
                        "at": "2026-07-05T00:00:00+00:00",
                        "via": "operator-instruction",
                        "scope": "refactor-release-card-suspension",
                        "reason": "",
                    },
                    "9.9.9": {
                        "at": "2026-07-05T00:00:00+00:00",
                        "via": "operator-instruction",
                        "scope": "future-release-card-suspension",
                        "reason": "future versions cannot be pre-accounted.",
                    },
                    "not-a-version": {
                        "at": "2026-07-05T00:00:00+00:00",
                        "via": "operator-instruction",
                        "scope": "bad-key",
                        "reason": "invalid version key",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)

    assert cli.release_update_suspended_versions() == {current}
    assert cli.release_update_accounted_versions() == {current}


def test_release_update_overdue_versions_accepts_valid_prior_suspension_only(cli, tmp_path):
    (tmp_path / "VERSION").write_text("0.6.114\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [0.6.114] - 2026-07-05\n\n### Changed\n\n- Current.\n\n"
        "## [0.6.113] - 2026-07-04\n\n### Changed\n\n- Suspended.\n\n"
        "## [0.6.112] - 2026-07-03\n\n### Changed\n\n- Delivered.\n",
        encoding="utf-8",
    )
    delivery = tmp_path / "docs" / "releases" / "release-update-delivery.json"
    delivery.parent.mkdir(parents=True)
    valid = {
        "schema": cli.RELEASE_UPDATE_DELIVERY_SCHEMA,
        "delivered": {"0.6.112": {"at": "2026-07-03T00:00:00+00:00", "via": "bootstrap"}},
        "suspended": {
            "0.6.113": {
                "at": "2026-07-05T00:00:00+00:00",
                "via": "operator-instruction",
                "scope": "refactor-release-card-suspension",
                "reason": "Release cards are suspended for productization refactor releases.",
            },
            "0.6.230": {
                "at": "2026-07-05T00:00:00+00:00",
                "via": "operator-instruction",
                "scope": "future-release-card-suspension",
                "reason": "Future release entries must not pre-satisfy later gates.",
            },
        },
    }
    delivery.write_text(json.dumps(valid), encoding="utf-8")

    assert cli.release_update_overdue_versions(tmp_path) == []
    assert cli.release_update_suspended_versions(tmp_path) == {"0.6.113"}

    valid["suspended"]["0.6.113"]["reason"] = ""
    delivery.write_text(json.dumps(valid), encoding="utf-8")
    assert cli.release_update_overdue_versions(tmp_path) == ["0.6.113"]


def test_record_sorts_versions_numerically(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", tmp_path / "led.json")
    for v in ("0.6.10", "0.6.9", "0.6.113"):
        cli.release_update_record_delivery(v, via="bootstrap")
    keys = list(cli.release_update_delivery_load()["delivered"].keys())
    assert keys == ["0.6.9", "0.6.10", "0.6.113"]


def test_missing_or_corrupt_ledger_loads_empty(cli, tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", missing)
    assert cli.release_update_delivered_versions() == set()
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json")
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", corrupt)
    assert cli.release_update_delivered_versions() == set()
    wrong_schema = tmp_path / "wrong-schema.json"
    wrong_schema.write_text('{"schema":"wrong","delivered":{"0.6.1":{}}}\n', encoding="utf-8")
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", wrong_schema)
    assert cli.release_update_delivered_versions() == set()
    assert cli.release_update_suspended_versions() == set()


def _publish_args(cli, version, *, dry_run=False, webhook_url=None, webhook_env="X_TEST_WEBHOOK"):
    return argparse.Namespace(
        version=version, last=None, webhook_env=webhook_env, webhook_url=webhook_url, dry_run=dry_run
    )


def test_publish_records_only_for_real_configured_post(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "led.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    monkeypatch.setattr(cli, "post_google_chat_webhook", lambda *a, **k: None)  # no network
    current = cli.plugin_version()

    # dry-run: reached no channel -> no record
    cli.publish_release_update(_publish_args(cli, current, dry_run=True))
    assert cli.release_update_delivered_versions() == set()

    # one-off --webhook-url (manual/test override) -> no record
    cli.publish_release_update(_publish_args(cli, current, webhook_url="https://example.invalid/one-off"))
    assert cli.release_update_delivered_versions() == set()

    # real post through the configured env webhook -> recorded
    monkeypatch.setenv("X_TEST_WEBHOOK", "https://example.invalid/configured")
    cli.publish_release_update(_publish_args(cli, current))
    assert current in cli.release_update_delivered_versions()


def test_publish_release_update_current_dry_run_cli_contract(cli, run_cli):
    current = cli.plugin_version()

    result = run_cli("publish-release-update", "--version", current, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert f"release_update_version: {current}" in result.stdout
    assert "release_update_chat_post_dry_run: google-chat-webhook" in result.stdout
    assert "release_update_chat_posted: dry_run" in result.stdout


def test_publish_release_update_last_two_dry_run_cli_contract(cli, run_cli):
    # `--last 2` caps to however many release entries the changelog actually has (post-launch
    # squash leaves a single entry until future releases accumulate more).
    expected_count = min(2, len(cli.changelog_release_blocks()))

    result = run_cli("publish-release-update", "--last", "2", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "release_update_chat_posted: dry_run" in result.stdout
    assert not re.search(r"^Operator impact: .+:$", result.stdout, re.MULTILINE)
    versions = re.findall(r"release_update_version: ([0-9]+\.[0-9]+\.[0-9]+)", result.stdout)
    assert len(versions) == expected_count
    assert versions == sorted(versions, key=lambda value: tuple(int(part) for part in value.split(".")))


def test_publish_uses_methodology_env_fallback_for_configured_webhook(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "led.json"
    config_env = tmp_path / "methodology.env"
    config_env.write_text('export X_TEST_WEBHOOK="https://example.invalid/configured"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", config_env)
    monkeypatch.delenv("X_TEST_WEBHOOK", raising=False)
    posts = []
    monkeypatch.setattr(cli, "post_google_chat_webhook", lambda _kind, url, _payload, dry_run=False: posts.append((url, dry_run)))

    current = cli.plugin_version()
    cli.publish_release_update(_publish_args(cli, current))

    assert posts == [("https://example.invalid/configured", False)]
    assert current in cli.release_update_delivered_versions()


def test_env_fallback_reads_user_secrets_file(cli, tmp_path, monkeypatch):
    config_env = tmp_path / "methodology.env"
    secrets_env = tmp_path / "secrets.zsh"
    secrets_env.write_text('export X_TEST_WEBHOOK="https://example.invalid/from-secrets"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", config_env)
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", secrets_env)
    monkeypatch.delenv("X_TEST_WEBHOOK", raising=False)

    assert cli.env_value_with_user_config_fallback("X_TEST_WEBHOOK") == "https://example.invalid/from-secrets"


def test_failed_post_does_not_record(cli, tmp_path, monkeypatch):
    # A post that raises (HTTP/URL/timeout -> SystemExit) must not leave a delivery marker,
    # because the gate would then believe a never-delivered release was announced.
    ledger = tmp_path / "led.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)

    def boom(*args, **kwargs):
        raise SystemExit("release_update Google Chat post failed: boom")

    monkeypatch.setattr(cli, "post_google_chat_webhook", boom)
    monkeypatch.setenv("X_TEST_WEBHOOK", "https://example.invalid/configured")
    with pytest.raises(SystemExit):
        cli.publish_release_update(_publish_args(cli, cli.plugin_version()))
    assert cli.release_update_delivered_versions() == set()


def _snapshot_exec_root(root: Path, *, commit: str = "b" * 40) -> Path:
    """An exec root with a snapshot manifest and no `.git` -- what a lane runs post-cutover."""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".snapshot-meta.json").write_text(
        json.dumps({"schema": "tautline-snapshot/v1", "commit": commit}), encoding="utf-8"
    )
    return root


def _canonical_checkout(root: Path) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def test_publish_release_update_refuses_to_run_from_a_snapshot(cli, tmp_path, monkeypatch):
    """The delivery ledger is a COMMITTED maintainer record: `docs/releases/release-update-delivery.json`
    is written into the exec root and then committed by the release flow. A snapshot exec root is an
    immutable export with no `.git`, so the write either dies on EACCES or -- if the store were ever
    writable -- lands an accountability record in a tree nobody can commit, and the gate that reads
    the ledger from the canonical checkout would keep reporting the release as never delivered.
    """
    canonical = _canonical_checkout(tmp_path / "canonical")
    exec_root = _snapshot_exec_root(tmp_path / "snapshot")
    ledger = exec_root / "docs" / "releases" / "release-update-delivery.json"
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    monkeypatch.setattr(cli, "_CANONICAL_METHODOLOGY_REPO", None)
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_CANONICAL_REPO", raising=False)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    monkeypatch.setattr(cli, "post_google_chat_webhook", lambda *a, **k: None)  # no network
    monkeypatch.setenv("X_TEST_WEBHOOK", "https://example.invalid/configured")

    with pytest.raises(SystemExit) as excinfo:
        cli.publish_release_update(_publish_args(cli, cli.plugin_version()))

    message = str(excinfo.value)
    assert "publish-release-update must run from a methodology dev checkout" in message
    assert str(canonical) in message
    assert not ledger.exists()  # refused BEFORE any delivery record was written


def test_publish_release_update_refuses_a_git_less_exec_root(cli, tmp_path, monkeypatch):
    """No manifest either: a copied-out CLI. `git add`/`git commit` of the ledger have no repo."""
    canonical = _canonical_checkout(tmp_path / "canonical")
    exec_root = _snapshot_exec_root(tmp_path / "copied")
    (exec_root / ".snapshot-meta.json").unlink()
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setattr(cli, "_CANONICAL_METHODOLOGY_REPO", None)
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_CANONICAL_REPO", raising=False)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))

    with pytest.raises(SystemExit) as excinfo:
        cli.publish_release_update(_publish_args(cli, cli.plugin_version(), dry_run=True))

    assert "publish-release-update must run from a methodology dev checkout" in str(excinfo.value)


def test_publish_release_update_runs_from_a_dev_checkout(cli, tmp_path, monkeypatch):
    """The guard must not fire on the maintainer's own checkout: REPO_ROOT here has a `.git`."""
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", tmp_path / "led.json")
    monkeypatch.setattr(cli, "post_google_chat_webhook", lambda *a, **k: None)  # no network

    assert cli.publish_release_update(_publish_args(cli, cli.plugin_version(), dry_run=True)) == 0


def test_status_command_exit_code(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", tmp_path / "led.json")
    # Fixture: a synthetic prior release, independent of how many entries the real (post-launch
    # squash) changelog happens to carry, so this stays deterministic as history accumulates.
    monkeypatch.setattr(
        cli,
        "release_update_overdue_versions",
        lambda repo_root=None: [
            v for v in ("0.6.9",) if v not in cli.release_update_delivered_versions()
        ],
    )
    # nothing delivered: the previous shipped release is overdue -> exit 1
    rc = cli.release_update_status(argparse.Namespace(as_json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert sorted(out) == [
        "accounted_count",
        "current_accounted",
        "current_delivered",
        "current_required",
        "current_required_missing",
        "current_suspended",
        "current_version",
        "delivered_count",
        "overdue",
        "suspended_count",
    ]
    assert out["overdue"], "expected the unmarked previous release to be flagged overdue"
    # mark every prior release delivered -> clean exit 0
    for v in out["overdue"]:
        cli.release_update_record_delivery(v, via="bootstrap")
    assert cli.release_update_status(argparse.Namespace(as_json=True)) == 0


def test_status_require_current_blocks_when_current_marker_missing(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", tmp_path / "led.json")
    current = cli.plugin_version()
    current_key = cli.release_update_version_key(current)
    for block in cli.changelog_release_blocks():
        version = block["version"]
        if version != current and cli.release_update_version_key(version) <= current_key:
            cli.release_update_record_delivery(version, via="bootstrap")

    rc = cli.release_update_status(argparse.Namespace(as_json=True, require_current=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["overdue"] == []
    assert out["current_required_missing"] is True

    cli.release_update_record_delivery(current)
    assert cli.release_update_status(argparse.Namespace(as_json=True, require_current=True)) == 0


def test_status_require_current_accepts_documented_suspension(cli, tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "led.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    current = cli.plugin_version()
    current_key = cli.release_update_version_key(current)
    for block in cli.changelog_release_blocks():
        version = block["version"]
        if version != current and cli.release_update_version_key(version) <= current_key:
            cli.release_update_record_delivery(version, via="bootstrap")
    data = cli.release_update_delivery_load()
    data["suspended"] = {
        current: {
            "at": "2026-07-05T00:00:00+00:00",
            "via": "operator-instruction",
            "scope": "refactor-release-card-suspension",
            "reason": "Release cards are suspended for productization refactor releases.",
        }
    }
    ledger.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    rc = cli.release_update_status(argparse.Namespace(as_json=True, require_current=True))
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["current_delivered"] is False
    assert out["current_suspended"] is True
    assert out["current_required_missing"] is False
    assert out["suspended_count"] == 1


def test_public_release_check_owns_current_release_update_marker(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "release-update-delivery.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    current = cli.plugin_version()
    current_key = cli.release_update_version_key(current)
    for block in cli.changelog_release_blocks():
        version = block["version"]
        if version != current and cli.release_update_version_key(version) <= current_key:
            cli.release_update_record_delivery(version, via="bootstrap")

    issues = cli.release_update_public_release_issues()

    assert [issue[0] for issue in issues] == ["release-update-current-missing"]
    assert current in issues[0][2]

    cli.release_update_record_delivery(current)
    assert cli.release_update_public_release_issues() == []


def test_public_release_check_accepts_documented_current_suspension(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "release-update-delivery.json"
    monkeypatch.setattr(cli, "RELEASE_UPDATE_DELIVERY_FILE", ledger)
    current = cli.plugin_version()
    current_key = cli.release_update_version_key(current)
    for block in cli.changelog_release_blocks():
        version = block["version"]
        if version != current and cli.release_update_version_key(version) <= current_key:
            cli.release_update_record_delivery(version, via="bootstrap")
    data = cli.release_update_delivery_load()
    data["suspended"] = {
        current: {
            "at": "2026-07-05T00:00:00+00:00",
            "via": "operator-instruction",
            "scope": "refactor-release-card-suspension",
            "reason": "Release cards are suspended for productization refactor releases.",
        }
    }
    ledger.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cli.release_update_public_release_issues() == []


def test_core_validation_no_longer_requires_current_release_update_marker():
    validate = (Path(__file__).resolve().parents[1] / "scripts" / "validate.sh").read_text(encoding="utf-8")

    assert "release-update-status --require-current" not in validate
