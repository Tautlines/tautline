"""RCA cluster B: iteration-review delivery markers (skip/repeat audit) + after-merge workflow."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_posted_marker_appends_post_history(cli, tmp_path):
    marker = tmp_path / "review.json"
    cli.write_iteration_review_delivery_marker(
        marker,
        review_slug="g1",
        record_hash="r1",
        page_hash="p1",
        record_url="https://x/r",
        page_url="https://x/p",
        provider="google-chat",
        webhook_env="HOOK",
    )
    # O18: a forced repeat appends to postHistory and records the reason.
    cli.write_iteration_review_delivery_marker(
        marker,
        review_slug="g1",
        record_hash="r1",
        page_hash="p1",
        record_url="https://x/r",
        page_url="https://x/p",
        provider="google-chat",
        webhook_env="HOOK",
        repeat_reason="artifact correction",
    )
    data = _read(marker)
    assert data["skipped"] is False
    assert len(data["postHistory"]) == 2
    assert data["postHistory"][1]["repeatReason"] == "artifact correction"


def test_skipped_marker_records_reason_and_satisfies_when_approved(cli, tmp_path):
    marker = tmp_path / "review.json"
    # O11: an operator-approved skip with a reason is durable and satisfies the delivery gate.
    cli.write_iteration_review_delivery_marker(
        marker,
        review_slug="g1",
        record_hash="r1",
        page_hash="p1",
        record_url="https://x/r",
        page_url="https://x/p",
        provider="google-chat",
        webhook_env="HOOK",
        skipped=True,
        skip_reason="operator paused external comms",
        operator_approved=True,
    )
    data = _read(marker)
    assert data["skipped"] is True
    assert data["skipReason"] == "operator paused external comms"
    assert data["operatorApproved"] is True
    assert data["postedAt"] is None
    # accept_skipped honored only when operator-approved AND artifacts match
    assert cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r1", page_hash="p1", page_url="https://x/p", accept_skipped=True
    )
    assert not cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r1", page_hash="p1", page_url="https://x/p", accept_skipped=False
    )


def test_skipped_marker_without_approval_does_not_satisfy(cli, tmp_path):
    marker = tmp_path / "review.json"
    cli.write_iteration_review_delivery_marker(
        marker,
        review_slug="g1",
        record_hash="r1",
        page_hash="p1",
        record_url="https://x/r",
        page_url="https://x/p",
        provider="google-chat",
        webhook_env="HOOK",
        skipped=True,
        skip_reason="no approval",
        operator_approved=False,
    )
    assert not cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r1", page_hash="p1", page_url="https://x/p", accept_skipped=True
    )


def test_skipped_marker_requires_reason_and_page_url(cli, tmp_path):
    # Codex P2: a skipped marker must carry a non-blank skipReason AND match the current pageUrl.
    marker = tmp_path / "review.json"
    # hand-crafted/malformed marker missing skipReason -> not satisfied
    marker.write_text(json.dumps({
        "schema": "minervit-iteration-review-delivery/v1", "reviewSlug": "g",
        "recordSha256": "r", "pageSha256": "p", "pageUrl": "https://x/p",
        "skipped": True, "operatorApproved": True,
    }), encoding="utf-8")
    assert not cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r", page_hash="p", page_url="https://x/p", accept_skipped=True
    )
    # writer marker (reason defaulted) but pageUrl mismatch -> not satisfied
    cli.write_iteration_review_delivery_marker(
        marker, review_slug="g", record_hash="r", page_hash="p", record_url="u", page_url="https://x/p",
        provider="google-chat", webhook_env="H", skipped=True, skip_reason="paused", operator_approved=True,
    )
    assert not cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r", page_hash="p", page_url="https://x/OTHER", accept_skipped=True
    )
    # reason present and pageUrl matches -> satisfied
    assert cli.iteration_review_delivery_marker_matches(
        marker, record_hash="r", page_hash="p", page_url="https://x/p", accept_skipped=True
    )


def test_unreasoned_repeats_helper(cli, tmp_path):
    # Codex P2: shared helper used by delivery-check AND goal-complete.
    marker = tmp_path / "review.json"
    common = dict(review_slug="g", record_hash="r", page_hash="p", record_url="u", page_url="pu",
                  provider="google-chat", webhook_env="H")
    cli.write_iteration_review_delivery_marker(marker, **common)  # first post (no reason needed)
    assert cli.iteration_review_marker_unreasoned_repeats(marker) == 0
    cli.write_iteration_review_delivery_marker(marker, **common)  # repeat WITHOUT reason
    assert cli.iteration_review_marker_unreasoned_repeats(marker) == 1
    cli.write_iteration_review_delivery_marker(marker, repeat_reason="artifact fix", **common)  # reasoned repeat
    assert cli.iteration_review_marker_unreasoned_repeats(marker) == 1  # still just the one un-reasoned


def test_after_merge_workflow_yaml_uses_webhook_and_record_dir(cli):
    data = {
        "iterationReview": {
            "recordDir": "docs/iteration-reviews",
            "delivery": {"webhookEnv": "MY_HOOK", "trigger": "after-merge"},
        }
    }
    yaml = cli.iteration_review_after_merge_workflow_yaml(data)
    assert "publish-iteration-review" in yaml
    assert "MY_HOOK: ${{ secrets.MY_HOOK }}" in yaml
    assert "docs/iteration-reviews/**" in yaml


def test_iteration_review_delivery_cli_and_policy_contracts_remain_pinned():
    # Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a shim.
    cli_source = (ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")
    canonical = (ROOT / "methodology" / "canonical-rules.md").read_text(encoding="utf-8")

    assert "--skip-chat-reason" in cli_source
    assert "--repeat-chat-reason" in cli_source
    assert "emit-iteration-review-workflow" in cli_source
    assert "sourceAdapterSha256" in canonical


def test_skip_post_and_reasoned_repeat_accumulate_history(cli, tmp_path):
    marker = tmp_path / "review.json"
    common = {
        "review_slug": "g",
        "record_hash": "r",
        "page_hash": "p",
        "record_url": "u",
        "page_url": "pu",
        "provider": "google-chat",
        "webhook_env": "H",
    }

    cli.write_iteration_review_delivery_marker(
        marker,
        **common,
        skipped=True,
        skip_reason="paused",
        operator_approved=True,
    )
    assert cli.iteration_review_delivery_marker_matches(
        marker,
        record_hash="r",
        page_hash="p",
        page_url="pu",
        accept_skipped=True,
    )
    assert not cli.iteration_review_delivery_marker_matches(
        marker,
        record_hash="r",
        page_hash="p",
        page_url="pu",
        accept_skipped=False,
    )

    cli.write_iteration_review_delivery_marker(marker, **common)
    cli.write_iteration_review_delivery_marker(marker, **common, repeat_reason="fix")

    data = _read(marker)
    assert len(data["postHistory"]) == 3
    assert data["postHistory"][0]["skipped"] is True
    assert data["postHistory"][2]["repeatReason"] == "fix"
