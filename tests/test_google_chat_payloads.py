"""Google Chat posts must be card-only.

Google Chat renders a top-level "text" field IN ADDITION TO a cardsV2 card, duplicating
the whole message (the nice card plus the raw markdown). Every payload that carries a card
must omit top-level "text", and the central poster strips it defensively.
"""

import argparse
import io
import json

from minervit_methodology import chat


def test_chat_helpers_are_served_from_package_through_cli_wrapper(cli):
    data = {"project": "Demo"}
    milestone_content = "## Shipped\nThing done.\n## Why It Matters\nValue."
    milestone_cfg = {"maxChars": 500}
    product_cfg = {"maxChars": 500}
    deploy_cfg = {"maxChars": 500}

    assert cli.milestone_update_sections(milestone_content) == chat.milestone_update_sections(milestone_content)
    assert cli.milestone_update_card_text("**Done**\nReady") == chat.milestone_update_card_text("**Done**\nReady")
    assert cli.milestone_update_payload(data, "M1", milestone_content) == chat.milestone_update_payload(
        data,
        "M1",
        milestone_content,
        cli.MILESTONE_UPDATE_REQUIRED_HEADINGS,
        slugify_func=cli.slugify,
    )
    assert cli.product_note_payload(data, "Note", "Body text.") == chat.product_note_payload(
        data,
        "Note",
        "Body text.",
        slugify_func=cli.slugify,
    )
    assert cli.deployment_notification_payload(
        data,
        environment="dev",
        url="https://example.test",
        summary="Live and ready.",
        iteration_review_url="",
        commit="abc123def456",
    ) == chat.deployment_notification_payload(
        data,
        environment="dev",
        url="https://example.test",
        summary="Live and ready.",
        iteration_review_url="",
        commit="abc123def456",
        slugify_func=cli.slugify,
    )
    assert cli.google_chat_card_only({"text": "raw twin", "cardsV2": [{"card": {}}]}) == chat.google_chat_card_only(
        {"text": "raw twin", "cardsV2": [{"card": {}}]}
    )
    milestone_args = argparse.Namespace(stdin=False, content_file=None, summary="Milestone body")
    product_args = argparse.Namespace(stdin=False, content_file=None, summary="Product note body")
    assert cli.milestone_update_content_from_args(milestone_args) == chat.google_chat_content_from_args(
        milestone_args,
        command="publish-milestone-update",
        label="milestone update",
    )
    assert cli.product_note_content_from_args(product_args) == chat.google_chat_content_from_args(
        product_args,
        command="publish-product-note",
        label="product note",
    )
    assert cli.validate_milestone_update_content(milestone_content, milestone_cfg) == chat.validate_milestone_update_content(
        milestone_content,
        milestone_cfg,
        cli.MILESTONE_UPDATE_REQUIRED_HEADINGS,
        cli.SESSION_JOURNAL_SECRET_PATTERNS,
    )
    assert cli.validate_product_note("Note", "Body text.", product_cfg) == chat.validate_product_note(
        "Note",
        "Body text.",
        product_cfg,
        cli.SESSION_JOURNAL_SECRET_PATTERNS,
    )
    assert cli.validate_deployment_notification_content(
        "dev",
        "https://example.test",
        "Live and ready.",
        deploy_cfg,
    ) == chat.validate_deployment_notification_content(
        "dev",
        "https://example.test",
        "Live and ready.",
        deploy_cfg,
        cli.SESSION_JOURNAL_SECRET_PATTERNS,
    )


def test_chat_content_input_helpers_preserve_errors(tmp_path):
    content_file = tmp_path / "note.md"
    content_file.write_text("File body", encoding="utf-8")

    assert (
        chat.google_chat_content_from_args(
            argparse.Namespace(stdin=False, content_file=content_file, summary=None),
            command="publish-product-note",
            label="product note",
        )
        == "File body"
    )
    try:
        chat.google_chat_content_from_args(
            argparse.Namespace(stdin=False, content_file=None, summary=None),
            command="publish-milestone-update",
            label="milestone update",
        )
    except SystemExit as exc:
        assert "publish-milestone-update requires exactly one of --stdin, --content-file, or --summary" in str(exc)
    else:
        raise AssertionError("missing milestone update content source should fail")
    try:
        chat.google_chat_content_from_args(
            argparse.Namespace(stdin=False, content_file=content_file, summary="also set"),
            command="publish-product-note",
            label="product note",
        )
    except SystemExit as exc:
        assert "publish-product-note requires exactly one of --stdin, --content-file, or --summary" in str(exc)
    else:
        raise AssertionError("conflicting product note content sources should fail")


def test_milestone_update_marker_helpers_preserve_format(tmp_path):
    marker_path = tmp_path / "markers" / "m1.json"

    assert chat.milestone_update_content_hash("  Done.  ") == (
        "ed251864987c367e9641fbdc89c1d83e9bf0fa2e3eecef8f301c79f619bfac81"
    )
    expected = {
        "schema": "minervit-milestone-update-delivery/v1",
        "milestone": "M1",
        "contentSha256": "abc",
        "provider": "google-chat-webhook",
        "webhookEnv": "MILESTONE_WEBHOOK",
        "chatSpace": "Product Milestones",
        "postedAt": "2026-07-06T00:00:00Z",
    }
    assert chat.milestone_update_marker_record(
        milestone="M1",
        content_hash="abc",
        provider="google-chat-webhook",
        webhook_env="MILESTONE_WEBHOOK",
        chat_space="Product Milestones",
        posted_at="2026-07-06T00:00:00Z",
    ) == expected

    chat.milestone_update_write_marker(
        marker_path,
        milestone="M1",
        content_hash="abc",
        provider="google-chat-webhook",
        webhook_env="MILESTONE_WEBHOOK",
        chat_space="Product Milestones",
        posted_at="2026-07-06T00:00:00Z",
    )

    marker_text = marker_path.read_text(encoding="utf-8")
    assert marker_text == json.dumps(expected, indent=2, sort_keys=True) + "\n"
    assert json.loads(marker_text) == expected
    assert chat.milestone_update_marker_content_hash(marker_path) == "abc"
    assert chat.milestone_update_already_sent(marker_path, "abc", dedupe=True, force=False) is True
    assert chat.milestone_update_already_sent(marker_path, "abc", dedupe=True, force=True) is False
    assert chat.milestone_update_already_sent(marker_path, "abc", dedupe=False, force=False) is False
    assert chat.milestone_update_already_sent(marker_path, "different", dedupe=True, force=False) is False
    assert chat.milestone_update_marker_content_hash(tmp_path / "missing.json") is None
    corrupt_marker_path = tmp_path / "corrupt.json"
    corrupt_marker_path.write_text("[]\n", encoding="utf-8")
    assert chat.milestone_update_marker_content_hash(corrupt_marker_path) is None


def test_chat_content_input_wrapper_errors_and_stdin(cli, monkeypatch):
    try:
        cli.milestone_update_content_from_args(argparse.Namespace(stdin=False, content_file=None, summary=None))
    except SystemExit as exc:
        assert "publish-milestone-update requires exactly one of --stdin, --content-file, or --summary" in str(exc)
    else:
        raise AssertionError("missing milestone update wrapper content source should fail")
    try:
        cli.product_note_content_from_args(argparse.Namespace(stdin=False, content_file=None, summary=None))
    except SystemExit as exc:
        assert "publish-product-note requires exactly one of --stdin, --content-file, or --summary" in str(exc)
    else:
        raise AssertionError("missing product note wrapper content source should fail")

    monkeypatch.setattr(chat.sys, "stdin", io.StringIO("stdin body"))
    assert chat.google_chat_content_from_args(
        argparse.Namespace(stdin=True, content_file=None, summary=None),
        command="publish-product-note",
        label="product note",
    ) == "stdin body"


def test_chat_webhook_url_helper_preserves_errors():
    assert chat.google_chat_webhook_url(
        "milestone update",
        "WEBHOOK",
        dry_run=False,
        environ={"WEBHOOK": "https://example.invalid/google-chat-webhook"},
    ) == "https://example.invalid/google-chat-webhook"
    assert chat.google_chat_webhook_url("product note", "WEBHOOK", dry_run=True, environ={}) == (
        "https://example.invalid/google-chat-webhook"
    )
    try:
        chat.google_chat_webhook_url("milestone update", "WEBHOOK", dry_run=False, environ={})
    except SystemExit as exc:
        assert "milestone update Google Chat webhook env var is missing: WEBHOOK" in str(exc)
    else:
        raise AssertionError("missing milestone update webhook should fail outside dry-run")
    try:
        chat.google_chat_webhook_url("product note", "WEBHOOK", dry_run=False, environ={"WEBHOOK": "http://example.invalid"})
    except SystemExit as exc:
        assert "product note Google Chat webhook env var must contain an https URL: WEBHOOK" in str(exc)
    else:
        raise AssertionError("non-https product note webhook should fail")


def test_chat_validation_wrappers_preserve_error_messages(cli):
    milestone_cfg = {"maxChars": 5}
    product_cfg = {"maxChars": 5}
    deploy_cfg = {"maxChars": 5}

    assert cli.validate_milestone_update_content("", milestone_cfg) == [
        "milestone update content must be non-blank",
        "milestone update content missing required heading: ## Plain English",
        "milestone update content missing required heading: ## Progress",
        "milestone update content missing required heading: ## What Changed",
        "milestone update content missing required heading: ## Validation",
        "milestone update content missing required heading: ## Next",
        "milestone update content missing required heading: ## Technical Details",
    ]
    assert cli.validate_product_note("", "", product_cfg) == [
        "product note title must be non-blank",
        "product note content must be non-blank",
    ]
    assert cli.validate_deployment_notification_content("", "ftp://example.test", "too long", deploy_cfg) == [
        "deploy-ready update environment must be non-blank",
        "deploy-ready update url must start with http:// or https://",
        "deploy-ready update content exceeds maxChars=5",
    ]


def test_deployment_notification_payload_is_card_only_and_structured(cli):
    # RCA 20260612: Google Chat duplicates payloads that include both text and cardsV2.
    payload = cli.deployment_notification_payload(
        {"project": "Demo"},
        environment="dev",
        url="https://example.test",
        summary="Live and ready.",
        iteration_review_url="",
        commit="abc123def456",
    )

    assert "text" not in payload
    assert payload.get("cardsV2")

    widgets = payload["cardsV2"][0]["card"]["sections"][0]["widgets"]
    assert any(widget.get("decoratedText", {}).get("text") == "abc123def456" for widget in widgets)
    assert any("textParagraph" in widget for widget in widgets)
    assert any("buttonList" in widget for widget in widgets)


def test_deployment_notification_payload_preserves_default_summary_and_stripping(cli):
    payload = cli.deployment_notification_payload(
        {"project": "Demo"},
        environment="prod",
        url="https://example.test",
        summary="  ",
        iteration_review_url="",
        commit="  abc123def456  ",
    )

    widgets = payload["cardsV2"][0]["card"]["sections"][0]["widgets"]
    assert payload["cardsV2"][0]["card"]["header"]["subtitle"] == "prod · ready to review"
    assert any(widget.get("decoratedText", {}).get("text") == "abc123def456" for widget in widgets)
    assert any(
        widget.get("textParagraph", {}).get("text")
        == "The latest reviewed change is live on prod and ready to review."
        for widget in widgets
    )


def test_milestone_update_payload_is_card_only(cli):
    payload = cli.milestone_update_payload(
        {"project": "Demo"}, "M1", "## Shipped\nThing done.\n## Why It Matters\nValue."
    )
    assert "text" not in payload
    assert payload.get("cardsV2")


def test_product_note_payload_is_card_only(cli):
    payload = cli.product_note_payload({"project": "Demo"}, "Note", "Body text.")
    assert "text" not in payload
    assert payload.get("cardsV2")


def test_release_update_payload_is_card_only(cli):
    # Release-update summaries are backed by the concise changelog on main.
    version = cli.changelog_release_blocks()[0]["version"]
    payload = cli.release_update_payload(version)
    assert "text" not in payload
    assert payload.get("cardsV2")
    assert payload["cardsV2"][0]["card"]["header"]["subtitle"] == version


def test_card_only_strips_text_when_card_present(cli):
    stripped = cli.google_chat_card_only({"text": "raw twin", "cardsV2": [{"card": {}}]})
    assert "text" not in stripped
    assert stripped.get("cardsV2")


def test_card_only_keeps_text_only_payload_untouched(cli):
    payload = {"text": "links only, no card"}
    assert cli.google_chat_card_only(payload) == payload
