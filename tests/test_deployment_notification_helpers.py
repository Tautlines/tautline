import argparse
import io
import json
import os

from minervit_methodology import deploy


def _notification_data(**overrides):
    cfg = {
        "enabled": True,
        "webhookEnv": "DEPLOY_WEBHOOK",
        "reuseIterationReviewWebhook": False,
        "sentStateDir": ".ai-work/deployment-notification-delivery",
        "pipeline": {
            "required": True,
            "mode": "ci-post-deploy",
            "evidencePaths": [".github/workflows/deploy.yml"],
            "requiredCommand": "minervit-methodology publish-deploy-ready-update",
            "healthCheckBeforeNotify": True,
        },
    }
    cfg.update(overrides)
    return {
        "deploymentNotification": cfg,
        "iterationReview": {"delivery": {"webhookEnv": "ITERATION_WEBHOOK"}},
    }


def test_deployment_notification_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    data = _notification_data()
    workflow = tmp_path / ".github" / "workflows" / "deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "steps:\n  - run: minervit-methodology publish-deploy-ready-update --source pipeline\n",
        encoding="utf-8",
    )

    assert cli.deployment_notification_config(data) == deploy.deployment_notification_config(data)
    assert cli.deployment_notification_effective_webhook_env(data) == deploy.deployment_notification_effective_webhook_env(
        data,
        config_func=cli.deployment_notification_config,
    )
    assert cli.deployment_notification_pipeline_issues(data, tmp_path) == deploy.deployment_notification_pipeline_issues(
        data,
        tmp_path,
        config_func=cli.deployment_notification_config,
        configured_path_func=cli.configured_path,
    )
    assert cli.deployment_notification_pipeline_issues(data, tmp_path) == []


def test_deployment_notification_effective_webhook_reuses_iteration_delivery(cli):
    data = _notification_data(webhookEnv="", reuseIterationReviewWebhook=True)

    assert cli.deployment_notification_effective_webhook_env(data) == "ITERATION_WEBHOOK"


def test_deployment_notification_pipeline_issues_preserves_errors(cli, tmp_path):
    data = _notification_data(pipeline={"required": True, "mode": "manual", "evidencePaths": []})

    assert cli.deployment_notification_pipeline_issues(data, tmp_path) == [
        "deploymentNotification.pipeline.required is true but mode is not ci-post-deploy",
        "deploymentNotification.pipeline.healthCheckBeforeNotify must be true for reliable deploy-ready notifications",
        "deploymentNotification.pipeline.requiredCommand is missing",
        "deploymentNotification.pipeline.required is true but no evidencePaths are configured",
    ]


def test_deployment_notification_pipeline_issues_default_path_resolver_uses_shared_semantics(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workflow = home / "deploy.yml"
    workflow.write_text("steps:\n  - run: minervit-methodology publish-deploy-ready-update\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    data = _notification_data(
        pipeline={
            "required": True,
            "mode": "ci-post-deploy",
            "evidencePaths": ["~/deploy.yml"],
            "requiredCommand": "minervit-methodology publish-deploy-ready-update",
            "healthCheckBeforeNotify": True,
        }
    )

    assert deploy.deployment_notification_pipeline_issues(data, tmp_path) == []


def test_deployment_notification_pipeline_issues_preserves_cli_monkeypatch_seams(cli, tmp_path, monkeypatch):
    data = _notification_data()
    calls = []

    def fake_config(adapter_data):
        calls.append(("config", adapter_data["deploymentNotification"]["webhookEnv"]))
        return {
            "enabled": True,
            "pipeline": {
                "required": True,
                "mode": "ci-post-deploy",
                "evidencePaths": ["deploy.yml"],
                "requiredCommand": "ship-it",
                "healthCheckBeforeNotify": True,
            },
        }

    def fake_configured_path(target, path_text):
        calls.append(("path", target, path_text))
        return target / "real.yml"

    (tmp_path / "real.yml").write_text("steps:\n  - run: ship-it\n", encoding="utf-8")
    monkeypatch.setattr(cli, "deployment_notification_config", fake_config)
    monkeypatch.setattr(cli, "configured_path", fake_configured_path)

    assert cli.deployment_notification_pipeline_issues(data, tmp_path) == []
    assert calls == [
        ("config", "DEPLOY_WEBHOOK"),
        ("path", tmp_path, "deploy.yml"),
    ]


def test_deployment_notification_marker_helpers_are_served_from_package_through_cli_wrapper(cli, tmp_path):
    data = _notification_data()
    marker_dir = tmp_path / ".ai-work" / "deployment-notification-delivery"
    marker_dir.mkdir(parents=True)
    old_marker = marker_dir / "old.json"
    new_marker = marker_dir / "new.json"
    old_marker.write_text('{"source": "pipeline", "postedAt": "2026-07-01T00:00:00Z"}', encoding="utf-8")
    new_marker.write_text('{"source": "agent", "postedAt": "2026-07-02T00:00:00Z"}', encoding="utf-8")
    os.utime(old_marker, (1, 1))
    os.utime(new_marker, (2, 2))

    expected_marker_path = tmp_path / ".ai-work" / "deployment-notification-delivery" / "dev-abc123.json"
    assert cli.deployment_notification_marker_path(data, tmp_path, "dev-abc123") == expected_marker_path
    assert deploy.deployment_notification_marker_path(
        data,
        tmp_path,
        "dev-abc123",
        config_func=cli.deployment_notification_config,
        configured_path_func=cli.configured_path,
    ) == expected_marker_path
    latest = cli.deployment_notification_latest_marker(data, tmp_path)
    assert latest == deploy.deployment_notification_latest_marker(
        data,
        tmp_path,
        config_func=cli.deployment_notification_config,
        configured_path_func=cli.configured_path,
    )
    assert latest["source"] == "agent"
    assert latest["_path"] == new_marker


def test_deployment_notification_package_defaults_are_exercised(tmp_path, monkeypatch):
    data = _notification_data()
    marker_dir = tmp_path / ".ai-work" / "deployment-notification-delivery"
    marker_dir.mkdir(parents=True)
    marker = marker_dir / "latest.json"
    marker.write_text('{"source": "agent", "postedAt": "2026-07-03T00:00:00Z"}', encoding="utf-8")

    assert deploy.deployment_notification_marker_path(data, tmp_path, "dev") == marker_dir / "dev.json"
    assert deploy.deployment_notification_latest_marker(data, tmp_path)["_path"] == marker
    assert deploy.deployment_notification_ci_detected(environ={"GITHUB_ACTIONS": "true"}) is True
    monkeypatch.setenv("CI", "true")
    assert deploy.deployment_notification_source("auto", dry_run=False) == "pipeline"


def test_deployment_notification_marker_helpers_preserve_cli_monkeypatch_seams(cli, tmp_path, monkeypatch):
    data = _notification_data()
    calls = []

    def fake_config(adapter_data):
        calls.append(("config", adapter_data["deploymentNotification"]["webhookEnv"]))
        return {"sentStateDir": "markers"}

    def fake_configured_path(target, path_text):
        calls.append(("path", target, path_text))
        return target / "real-markers"

    marker_dir = tmp_path / "real-markers"
    marker_dir.mkdir()
    marker = marker_dir / "latest.json"
    marker.write_text('{"source": "pipeline", "postedAt": "2026-07-02T00:00:00Z"}', encoding="utf-8")
    monkeypatch.setattr(cli, "deployment_notification_config", fake_config)
    monkeypatch.setattr(cli, "configured_path", fake_configured_path)

    assert cli.deployment_notification_marker_path(data, tmp_path, "dev") == tmp_path / "real-markers" / "dev.json"
    latest = cli.deployment_notification_latest_marker(data, tmp_path)
    assert latest["source"] == "pipeline"
    assert latest["_path"] == marker
    assert calls == [
        ("config", "DEPLOY_WEBHOOK"),
        ("path", tmp_path, "markers"),
        ("config", "DEPLOY_WEBHOOK"),
        ("path", tmp_path, "markers"),
    ]


def test_deployment_notification_source_helpers_preserve_behavior_and_cli_seams(cli, monkeypatch):
    assert deploy.deployment_notification_ci_detected(environ={"CI": "1"}) is True
    assert deploy.deployment_notification_ci_detected(environ={"CI": ""}) is False
    assert cli.deployment_notification_source("agent", dry_run=False) == "agent"
    assert cli.deployment_notification_source("pipeline", dry_run=True) == "pipeline"

    monkeypatch.setattr(cli, "deployment_notification_ci_detected", lambda: True)
    assert cli.deployment_notification_source("auto", dry_run=False) == "pipeline"
    assert cli.deployment_notification_source("pipeline", dry_run=False) == "pipeline"

    monkeypatch.setattr(cli, "deployment_notification_ci_detected", lambda: False)
    assert cli.deployment_notification_source("auto", dry_run=False) == "agent"
    try:
        cli.deployment_notification_source("pipeline", dry_run=False)
    except SystemExit as exc:
        assert "requires a CI/deploy environment marker" in str(exc)
    else:
        raise AssertionError("pipeline source without CI marker should fail")


def test_deployment_notification_content_from_args_is_served_from_package_through_cli_wrapper(cli, tmp_path, monkeypatch):
    content_file = tmp_path / "deploy-ready.md"
    content_file.write_text("Ready from file.\n", encoding="utf-8")

    file_args = argparse.Namespace(stdin=False, content_file=content_file, summary=None)
    assert cli.deployment_notification_content_from_args(file_args) == deploy.deployment_notification_content_from_args(file_args)
    assert cli.deployment_notification_content_from_args(file_args) == "Ready from file.\n"

    summary_args = argparse.Namespace(stdin=False, content_file=None, summary="Ready from summary.")
    assert cli.deployment_notification_content_from_args(summary_args) == "Ready from summary."

    monkeypatch.setattr(deploy.sys, "stdin", io.StringIO("Ready from stdin."))
    stdin_args = argparse.Namespace(stdin=True, content_file=None, summary=None)
    assert cli.deployment_notification_content_from_args(stdin_args) == "Ready from stdin."

    conflict_args = argparse.Namespace(stdin=False, content_file=content_file, summary="also set")
    try:
        cli.deployment_notification_content_from_args(conflict_args)
    except SystemExit as exc:
        assert "accepts at most one" in str(exc)
    else:
        raise AssertionError("content input conflict should fail")


def test_deployment_notification_extra_validation_helpers_preserve_errors(cli):
    secret_url = "https://chat.googleapis.com/v1/spaces/AAA/messages?key=SECRET&token=TOKEN"

    assert deploy.deployment_notification_extra_validation_errors(
        iteration_review_url="not-a-url",
        commit="bad ref!",
        secret_patterns=cli.SESSION_JOURNAL_SECRET_PATTERNS,
    ) == [
        "deploy-ready update iteration review URL must start with http:// or https://",
        "deploy-ready update commit/ref contains unsupported characters",
    ]
    assert deploy.deployment_notification_extra_validation_errors(
        iteration_review_url=secret_url,
        commit="abc123def456",
        secret_patterns=cli.SESSION_JOURNAL_SECRET_PATTERNS,
    ) == [
        "deploy-ready update iteration_review_url must not include Google Chat webhook URLs",
    ]
    assert deploy.deployment_notification_extra_validation_errors(
        iteration_review_url="https://reviews.example.test/iteration",
        commit="feature/deploy-ready_123",
        secret_patterns=cli.SESSION_JOURNAL_SECRET_PATTERNS,
    ) == []


def test_deployment_notification_identity_hash_helper_matches_existing_basis(cli):
    kwargs = {
        "source": "agent",
        "environment": "dev",
        "url": "https://dev.example.test",
        "iteration_review_url": "https://reviews.example.test/iteration",
        "commit": "abc123def456",
        "content": "  Ready to review.  ",
    }

    assert deploy.deployment_notification_identity_hash(**kwargs) == "92e684acb206c8975d327588cbd2c0fe52e56b5e2861f7711d3d3340d4c0f498"


def test_deployment_notification_webhook_url_and_marker_record_helpers():
    assert deploy.deployment_notification_webhook_url(
        "DEPLOY_WEBHOOK",
        dry_run=False,
        environ={"DEPLOY_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    ) == "https://example.invalid/google-chat-webhook"
    assert deploy.deployment_notification_webhook_url("DEPLOY_WEBHOOK", dry_run=True, environ={}) == (
        "https://example.invalid/google-chat-webhook"
    )
    try:
        deploy.deployment_notification_webhook_url("DEPLOY_WEBHOOK", dry_run=False, environ={})
    except SystemExit as exc:
        assert "deployment notification Google Chat webhook env var is missing: DEPLOY_WEBHOOK" in str(exc)
    else:
        raise AssertionError("missing webhook URL should fail outside dry-run")

    assert deploy.deployment_notification_marker_record(
        environment="dev",
        url="https://dev.example.test",
        iteration_review_url="https://reviews.example.test/iteration",
        commit="abc123def456",
        source="agent",
        identity_hash="abc",
        provider="google-chat-webhook",
        webhook_env="DEPLOY_WEBHOOK",
        chat_space="Deploys",
        posted_at="2026-07-06T00:00:00Z",
    ) == {
        "schema": "minervit-deployment-notification/v1",
        "environment": "dev",
        "url": "https://dev.example.test",
        "iterationReviewUrl": "https://reviews.example.test/iteration",
        "commit": "abc123def456",
        "source": "agent",
        "identitySha256": "abc",
        "provider": "google-chat-webhook",
        "webhookEnv": "DEPLOY_WEBHOOK",
        "chatSpace": "Deploys",
        "postedAt": "2026-07-06T00:00:00Z",
    }


def test_deployment_notification_write_marker_helper(tmp_path):
    marker_path = tmp_path / "markers" / "dev.json"

    deploy.deployment_notification_write_marker(
        marker_path,
        environment="dev",
        url="https://dev.example.test",
        iteration_review_url="",
        commit="abc123def456",
        source="pipeline",
        identity_hash="abc",
        provider="google-chat-webhook",
        webhook_env="DEPLOY_WEBHOOK",
        chat_space="Deploys",
        posted_at="2026-07-06T00:00:00Z",
    )

    marker_text = marker_path.read_text(encoding="utf-8")
    expected = {
        "schema": "minervit-deployment-notification/v1",
        "environment": "dev",
        "url": "https://dev.example.test",
        "iterationReviewUrl": "",
        "commit": "abc123def456",
        "source": "pipeline",
        "identitySha256": "abc",
        "provider": "google-chat-webhook",
        "webhookEnv": "DEPLOY_WEBHOOK",
        "chatSpace": "Deploys",
        "postedAt": "2026-07-06T00:00:00Z",
    }
    assert marker_text == json.dumps(expected, indent=2, sort_keys=True) + "\n"
    assert json.loads(marker_text) == expected
