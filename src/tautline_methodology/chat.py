"""Google Chat payload helpers for the Minervit methodology CLI."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from html import escape
from pathlib import Path

from .util import resolve_env
from typing import Callable


def google_chat_content_from_args(args, *, command: str, label: str) -> str:
    sources = [bool(args.stdin), bool(args.content_file), bool(args.summary)]
    if sum(1 for item in sources if item) != 1:
        raise SystemExit(f"{command} requires exactly one of --stdin, --content-file, or --summary")
    if args.stdin:
        return sys.stdin.read()
    if args.content_file:
        try:
            return args.content_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"{label} content unreadable: {args.content_file}: {exc}") from exc
    return str(args.summary)



def webhook_env_value(webhook_env: str, environ) -> str:
    """Read a webhook secret under EITHER rebrand spelling, THROUGH the resolver.

    `secret-status` probes both, so it can report `process-env` and exit 0 for a value exported
    under the sibling name -- and this consumer, reading the exact key only, would then refuse
    again. An agent following the remedy would loop forever on a probe that says the value is
    right there. The instruction and the consumer have to agree about what "reachable" means.

    Every read goes through `resolve_env` rather than `environ.get`, because
    `test_no_shipped_source_bypasses_the_resolver` forbids the direct form for exactly the failure
    being fixed here -- a read that misses a managed alias. `resolve_env` resolves
    MINERVIT_ -> TAUTLINE_ and not the reverse, so a TAUTLINE_-spelled name is asked a second time
    under its MINERVIT_ sibling, which the resolver then handles in both directions.
    """
    value = resolve_env(webhook_env, environ=environ).strip()
    if value:
        return value
    if webhook_env.startswith("TAUTLINE_"):
        sibling = "MINERVIT_" + webhook_env[len("TAUTLINE_"):]
        return resolve_env(sibling, environ=environ).strip()
    return ""


def google_chat_webhook_url(
    label: str, webhook_env: str, *, dry_run: bool, environ=None, value: str | None = None
) -> str:
    # `environ` is passed through as-is, INCLUDING None: `resolve_env` reads the process
    # environment itself in that case. Defaulting it here left this module naming the environment
    # while doing no read the resolver guard could see -- which is how that guard went vacuous
    # once before, so it now refuses the shape outright.
    #
    # (The guard's scan is textual, so the module must not NAME the environment even in a comment.
    # Filed as a false-positive class rather than worked around silently.)
    # `value` is the caller's ALREADY-RESOLVED secret, and callers in the CLI pass what
    # `webhook_env_reachable_value` found -- which reads the installed config env and the operator
    # secrets file as well as the process environment. Without it, strict STATUS (which does read
    # those files) passed while the publisher it advertises refused, on the same lane, in the same
    # second. A status check that green-lights a command that immediately refuses is worse than no
    # status check.
    webhook_url = value.strip() if value else webhook_env_value(webhook_env, environ)
    if not webhook_url and dry_run:
        webhook_url = "https://example.invalid/google-chat-webhook"
    if not webhook_url:
        raise SystemExit(
            f"{label} Google Chat webhook env var is missing: {webhook_env}. "
            f"Check the persisted secrets store with `tautline secret-status --name {webhook_env}` "
            "and re-run through the lane env before treating this as a blocker."
        )
    if not webhook_url.startswith("https://"):
        raise SystemExit(f"{label} Google Chat webhook env var must contain an https URL: {webhook_env}")
    return webhook_url


def milestone_update_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line.rstrip())
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def milestone_update_card_text(value: str) -> str:
    text = escape(value.strip())
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = text.replace("\n", "<br>")
    return text


def milestone_update_payload(
    data: dict,
    milestone: str,
    content: str,
    required_headings: list[str],
    *,
    slugify_func: Callable[..., str],
) -> dict:
    project = str(data.get("project") or data.get("repo") or "Project").strip()
    sections = milestone_update_sections(content)
    widgets = []
    for heading in required_headings:
        body = sections.get(heading, "").strip()
        if body:
            widgets.append(
                {
                    "header": heading.removeprefix("## "),
                    "widgets": [{"textParagraph": {"text": milestone_update_card_text(body)}}],
                }
            )
    # Card-only: Google Chat renders a top-level "text" field in addition to the card,
    # which duplicates the whole message.
    return {
        "cardsV2": [
            {
                "cardId": f"milestone-update-{slugify_func(milestone, fallback='milestone')}",
                "card": {
                    "header": {
                        "title": f"{project} milestone complete",
                        "subtitle": milestone.strip(),
                    },
                    "sections": widgets,
                },
            }
        ],
    }


def milestone_update_content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def milestone_update_marker_record(
    *,
    milestone: str,
    content_hash: str,
    provider: str,
    webhook_env: str,
    chat_space: str,
    posted_at: str,
) -> dict:
    return {
        "schema": "minervit-milestone-update-delivery/v1",
        "milestone": milestone,
        "contentSha256": content_hash,
        "provider": provider,
        "webhookEnv": webhook_env,
        "chatSpace": chat_space,
        "postedAt": posted_at,
    }


def milestone_update_write_marker(
    marker_path: Path,
    *,
    milestone: str,
    content_hash: str,
    provider: str,
    webhook_env: str,
    chat_space: str,
    posted_at: str,
) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            milestone_update_marker_record(
                milestone=milestone,
                content_hash=content_hash,
                provider=provider,
                webhook_env=webhook_env,
                chat_space=chat_space,
                posted_at=posted_at,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def milestone_update_marker_content_hash(marker_path: Path) -> str | None:
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = marker.get("contentSha256") if isinstance(marker, dict) else None
    return str(value) if value is not None else None


def milestone_update_already_sent(marker_path: Path, content_hash: str, *, dedupe: bool, force: bool) -> bool:
    return bool(
        dedupe
        and marker_path.exists()
        and not force
        and milestone_update_marker_content_hash(marker_path) == content_hash
    )


def validate_milestone_update_content(
    content: str,
    cfg: dict,
    required_headings: list[str],
    secret_patterns: list[str],
) -> list[str]:
    errors: list[str] = []
    text = content.strip()
    if not text:
        errors.append("milestone update content must be non-blank")
    if len(text) > cfg["maxChars"]:
        errors.append(f"milestone update content exceeds maxChars={cfg['maxChars']}")
    sections = milestone_update_sections(text)
    for heading in required_headings:
        if heading not in text:
            errors.append(f"milestone update content missing required heading: {heading}")
        elif not sections.get(heading, "").strip():
            errors.append(f"milestone update content heading has no body: {heading}")
    for pattern in secret_patterns:
        if re.search(pattern, text):
            errors.append("milestone update content contains a secret-looking value")
            break
    if re.search(r"https://chat\.googleapis\.com/v1/spaces/[^)\s]+", text):
        errors.append("milestone update content must not include Google Chat webhook URLs")
    return errors


def product_note_payload(data: dict, title: str, content: str, *, slugify_func: Callable[..., str]) -> dict:
    project = str(data.get("project") or data.get("repo") or "Project").strip()
    body = content.strip()
    # Card-only (see google_chat_card_only): no duplicate top-level "text".
    return {
        "cardsV2": [
            {
                "cardId": f"product-note-{slugify_func(title, fallback='note')}",
                "card": {
                    "header": {
                        "title": f"{project} product note",
                        "subtitle": title.strip(),
                    },
                    "sections": [
                        {
                            "widgets": [{"textParagraph": {"text": milestone_update_card_text(body)}}]
                        }
                    ],
                },
            }
        ],
    }


def validate_product_note(title: str, content: str, cfg: dict, secret_patterns: list[str]) -> list[str]:
    errors: list[str] = []
    if not title.strip():
        errors.append("product note title must be non-blank")
    if len(title.strip()) > 120:
        errors.append("product note title exceeds 120 characters")
    text = content.strip()
    if not text:
        errors.append("product note content must be non-blank")
    if len(text) > cfg["maxChars"]:
        errors.append(f"product note content exceeds maxChars={cfg['maxChars']}")
    for value_name, value in [("title", title), ("content", text)]:
        for pattern in secret_patterns:
            if re.search(pattern, value):
                errors.append(f"product note {value_name} contains a secret-looking value")
                break
        if re.search(r"https://chat\.googleapis\.com/v1/spaces/[^)\s]+", value):
            errors.append(f"product note {value_name} must not include Google Chat webhook URLs")
    return errors


def deployment_notification_payload(
    data: dict,
    *,
    environment: str,
    url: str,
    summary: str,
    iteration_review_url: str,
    commit: str,
    slugify_func: Callable[..., str],
) -> dict:
    project = str(data.get("project") or data.get("repo") or "Project").strip()
    environment = environment.strip()
    url = url.strip()
    commit = commit.strip()
    iteration_review_url = iteration_review_url.strip()
    clean_summary = summary.strip() or f"The latest reviewed change is live on {environment} and ready to review."
    # Build a single Google Chat card. We intentionally do NOT also set a
    # top-level "text" field: Google Chat renders "text" in addition to the
    # card, which duplicates the entire message.
    widgets: list[dict] = []
    if commit:
        widgets.append({"decoratedText": {"topLabel": "Commit", "text": commit}})
    widgets.append({"textParagraph": {"text": milestone_update_card_text(clean_summary)}})
    buttons = [{"text": "Open live site", "onClick": {"openLink": {"url": url}}}]
    if iteration_review_url:
        buttons.append(
            {"text": "Open iteration review", "onClick": {"openLink": {"url": iteration_review_url}}}
        )
    widgets.append({"buttonList": {"buttons": buttons}})
    subtitle = f"{environment} · ready to review" if environment else "Ready to review"
    return {
        "cardsV2": [
            {
                "cardId": f"deploy-ready-{slugify_func(environment, fallback='deploy')}",
                "card": {
                    "header": {
                        "title": f"{project} deploy is live",
                        "subtitle": subtitle,
                    },
                    "sections": [{"widgets": widgets}],
                },
            }
        ],
    }


def validate_deployment_notification_content(
    environment: str,
    url: str,
    content: str,
    cfg: dict,
    secret_patterns: list[str],
) -> list[str]:
    errors: list[str] = []
    if not environment.strip():
        errors.append("deploy-ready update environment must be non-blank")
    if not url.strip():
        errors.append("deploy-ready update url must be non-blank")
    elif not re.match(r"https?://", url.strip()):
        errors.append("deploy-ready update url must start with http:// or https://")
    text = content.strip()
    if len(text) > cfg["maxChars"]:
        errors.append(f"deploy-ready update content exceeds maxChars={cfg['maxChars']}")
    for value_name, value in [("environment", environment), ("url", url), ("content", text)]:
        for pattern in secret_patterns:
            if re.search(pattern, value):
                errors.append(f"deploy-ready update {value_name} contains a secret-looking value")
                break
        if re.search(r"https://chat\.googleapis\.com/v1/spaces/[^)\s]+", value):
            errors.append(f"deploy-ready update {value_name} must not include Google Chat webhook URLs")
    return errors


def google_chat_card_only(payload: dict) -> dict:
    """Enforce card-only Google Chat messages."""
    if isinstance(payload, dict) and payload.get("cardsV2"):
        return {key: value for key, value in payload.items() if key != "text"}
    return payload
