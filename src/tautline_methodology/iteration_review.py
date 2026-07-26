"""Iteration-review leaves: record validation, media/output-contract checks, poster/HTML render
helpers, delivery-marker matching, and the chat/workflow payload builders. The stateful verb
handlers (iteration_review_status, publish_iteration_review, ...) stay in bin/tautline; they reach
lane/adapter state and delegate the pure helpers here."""

from __future__ import annotations

import argparse
import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote


def iteration_review_config(data: dict) -> dict:
    return data["iterationReview"]


def iteration_review_renderer_ignored_names() -> tuple[str, ...]:
    return (
        "node_modules",
        "out",
        "dist",
        "build",
        ".next",
        ".turbo",
        ".cache",
        "coverage",
        "*.mp4",
        "*.mov",
        "*.webm",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.gif",
        "*.webp",
    )


def iteration_review_required_string(record: dict, path: str, errors: list[str]) -> str:
    value = record
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            errors.append(f"missing required field: {path}")
            return ""
    if not isinstance(value, str) or not value.strip():
        errors.append(f"field must be a non-blank string: {path}")
        return ""
    return value.strip()


def iteration_review_optional_string(record: dict, path: str, errors: list[str]) -> None:
    value = record
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return
    if value is not None and (not isinstance(value, str) or not value.strip()):
        errors.append(f"optional field must be a non-blank string when present: {path}")


def iteration_review_validate_string_list(value: object, path: str, errors: list[str], *, min_items: int = 0, max_items: int | None = None) -> None:
    if not isinstance(value, list):
        errors.append(f"field must be an array: {path}")
        return
    if len(value) < min_items:
        errors.append(f"field must contain at least {min_items} item(s): {path}")
    if max_items is not None and len(value) > max_items:
        errors.append(f"field must contain at most {max_items} item(s): {path}")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"field item must be a non-blank string: {path}[{index}]")


ITERATION_REVIEW_CUSTOMER_FIELD_LIMITS = {
    "product": 48,
    "goalTitle": 86,
    "kicker": 72,
    "why": 520,
    "milestones[].title": 120,
    "milestones[].pr": 80,
    "highlight.heading": 90,
    "highlight.items[]": 150,
    "quality.tests": 140,
    "quality.types": 140,
    "quality.review": 140,
    "quality.discipline": 140,
    "next[].title": 86,
    "next[].blurb": 220,
    "nextWhy": 360,
    "outro.headline": 90,
    "outro.subhead": 190,
    "usage[].caption": 150,
    "links[].label": 90,
}


ITERATION_REVIEW_CUSTOMER_JARGON_PATTERNS = [
    (
        re.compile(r"\b(?:Codex|Claude|Gherkin|pytest|vitest|typecheck|preflight|merge queue|review round|Stage[- ]?\d|R\d|L[0-3])\b", re.I),
        "internal review/test process",
    ),
    (
        re.compile(r"\b(?:test[- ]driven|automated tests?|unit tests?|integration tests?|e2e|playwright|type[- ]?checked|type checks?|green tests?|review evidence|no blocking issues|P[0-3])\b", re.I),
        "internal review/test process",
    ),
    (
        re.compile(r"\b(?:behavior contracts?|behavior specs?|business contracts?|acceptance criteria|source[- ]of[- ]truth|requirements? traceability|scenario coverage|BDD|spec(?:ification)?s?)\b", re.I),
        "internal planning/spec process",
    ),
    (
        re.compile(r"\b(?:wrote|authored|drafted|reviewed|validated)\b.{0,80}\b(?:before building|before implementation|contract|spec|scenario|test)\b", re.I),
        "internal planning/spec process",
    ),
    (
        re.compile(r"\b(?:PR\s*(?:#|-)?\d+|pull request|commit|SHA|branch|repo|mainline|squash|auto-merge|merge-group)\b", re.I),
        "repository workflow detail",
    ),
    (
        re.compile(r"\b(?:dataclass|Postgres|frontend|backend|schema|route|endpoint|API route|query|resolver|invariant|tenant isolation)\b", re.I),
        "implementation jargon",
    ),
    (
        re.compile(r"\b(?:persisted|atomic|idempotent|tokenized|server-only|off-by-default|feature flag|migration|liveness probe)\b", re.I),
        "implementation jargon",
    ),
    (
        re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/[A-Za-z0-9_./{}-]*"),
        "HTTP route detail",
    ),
    (
        re.compile(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_./{}-]+\b"),
        "file or route path",
    ),
    (
        re.compile(r"\b[a-z][a-z0-9]+_[a-z0-9_]+\b"),
        "code identifier",
    ),
    (
        re.compile(r"(?:__|::|<=>|==|⇔)"),
        "code/operator notation",
    ),
]


def iteration_review_customer_copy_check(path: str, value: str, errors: list[str], *, limit_key: str | None = None) -> None:
    text = re.sub(r"\s+", " ", value.strip())
    key = limit_key or path
    max_chars = ITERATION_REVIEW_CUSTOMER_FIELD_LIMITS.get(key)
    if max_chars is not None and len(text) > max_chars:
        errors.append(f"{path} exceeds {max_chars} characters; move detail to technical")
    for pattern, label in ITERATION_REVIEW_CUSTOMER_JARGON_PATTERNS:
        if pattern.search(text):
            errors.append(f"{path} contains {label}; keep customer-facing copy non-technical and move this to technical")
            break


def iteration_review_customer_link_check(index: int, link: dict, errors: list[str]) -> None:
    label = link.get("label")
    if isinstance(label, str) and label.strip():
        iteration_review_customer_copy_check(f"links[{index}].label", label, errors, limit_key="links[].label")
    url = str(link.get("url") or "").strip()
    if re.search(r"(?:github|gitlab|bitbucket)\.com/.+(?:/pull/|/commit/|/compare/|/tree/|/blob/)", url, re.I):
        errors.append(f"links[{index}].url points to repository workflow detail; move PR/repo links to technical")


def iteration_review_validate_customer_copy(record: dict, errors: list[str]) -> None:
    for field in ["product", "goalTitle", "kicker", "why", "nextWhy"]:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            iteration_review_customer_copy_check(field, value, errors)
    milestones = record.get("milestones")
    if isinstance(milestones, list):
        for index, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                continue
            value = milestone.get("title")
            if isinstance(value, str) and value.strip():
                iteration_review_customer_copy_check(f"milestones[{index}].title", value, errors, limit_key="milestones[].title")
            proof = milestone.get("pr")
            if isinstance(proof, str) and proof.strip():
                iteration_review_customer_copy_check(f"milestones[{index}].pr", proof, errors, limit_key="milestones[].pr")
    highlight = record.get("highlight")
    if isinstance(highlight, dict):
        value = highlight.get("heading")
        if isinstance(value, str) and value.strip():
            iteration_review_customer_copy_check("highlight.heading", value, errors)
        items = highlight.get("items")
        if isinstance(items, list):
            for index, item in enumerate(items):
                if isinstance(item, str) and item.strip():
                    iteration_review_customer_copy_check(f"highlight.items[{index}]", item, errors, limit_key="highlight.items[]")
    usage = record.get("usage")
    if isinstance(usage, list):
        for index, shot in enumerate(usage):
            if not isinstance(shot, dict):
                continue
            value = shot.get("caption")
            if isinstance(value, str) and value.strip():
                iteration_review_customer_copy_check(f"usage[{index}].caption", value, errors, limit_key="usage[].caption")
    quality = record.get("quality")
    if isinstance(quality, dict):
        for field in ["tests", "types", "review", "discipline"]:
            value = quality.get(field)
            if isinstance(value, str) and value.strip():
                iteration_review_customer_copy_check(f"quality.{field}", value, errors)
    next_items = record.get("next")
    if isinstance(next_items, list):
        for index, item in enumerate(next_items):
            if not isinstance(item, dict):
                continue
            for field in ["title", "blurb"]:
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    iteration_review_customer_copy_check(f"next[{index}].{field}", value, errors, limit_key=f"next[].{field}")
    outro = record.get("outro")
    if isinstance(outro, dict):
        for field in ["headline", "subhead"]:
            value = outro.get(field)
            if isinstance(value, str) and value.strip():
                iteration_review_customer_copy_check(f"outro.{field}", value, errors)
    links = record.get("links")
    if isinstance(links, list):
        for index, link in enumerate(links):
            if isinstance(link, dict):
                iteration_review_customer_link_check(index, link, errors)


def validate_iteration_review_record(record: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["GoalReview must be a JSON object"]
    for field in ["product", "goalTitle", "kicker", "why", "nextWhy"]:
        iteration_review_required_string(record, field, errors)
    for field in ["date", "status", "videoUrl", "posterUrl", "musicUrl", "musicCredit"]:
        iteration_review_optional_string(record, field, errors)
    if "musicVolume" in record:
        try:
            music_volume = float(record["musicVolume"])
        except (TypeError, ValueError):
            errors.append("musicVolume must be a number between 0 and 1 when present")
        else:
            if music_volume < 0 or music_volume > 1:
                errors.append("musicVolume must be between 0 and 1")

    milestones = record.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        errors.append("milestones must be a non-empty array")
    else:
        for index, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                errors.append(f"milestones[{index}] must be an object")
                continue
            for field in ["id", "title", "pr"]:
                iteration_review_required_string(milestone, field, errors)
            if milestone.get("status") != "complete":
                errors.append(f"milestones[{index}].status must be complete")

    highlight = record.get("highlight")
    if not isinstance(highlight, dict):
        errors.append("highlight must be an object")
    else:
        iteration_review_required_string(highlight, "heading", errors)
        iteration_review_validate_string_list(highlight.get("items"), "highlight.items", errors, min_items=1, max_items=8)
        iteration_review_optional_string(highlight, "image", errors)

    usage = record.get("usage")
    if usage is not None:
        if not isinstance(usage, list):
            errors.append("usage must be an array when present")
        elif len(usage) > 4:
            errors.append("usage must contain at most 4 item(s)")
        else:
            for index, shot in enumerate(usage):
                if not isinstance(shot, dict):
                    errors.append(f"usage[{index}] must be an object")
                    continue
                iteration_review_required_string(shot, "src", errors)
                iteration_review_optional_string(shot, "caption", errors)

    quality = record.get("quality")
    if not isinstance(quality, dict):
        errors.append("quality must be an object")
    else:
        for field in ["tests", "types", "review", "discipline"]:
            iteration_review_required_string(quality, field, errors)

    next_items = record.get("next")
    if not isinstance(next_items, list) or not next_items:
        errors.append("next must be a non-empty array")
    else:
        for index, item in enumerate(next_items):
            if not isinstance(item, dict):
                errors.append(f"next[{index}] must be an object")
                continue
            for field in ["title", "blurb"]:
                iteration_review_required_string(item, field, errors)

    outro = record.get("outro")
    if not isinstance(outro, dict):
        errors.append("outro must be an object")
    else:
        for field in ["headline", "subhead"]:
            iteration_review_required_string(outro, field, errors)

    links = record.get("links")
    if links is not None:
        if not isinstance(links, list):
            errors.append("links must be an array when present")
        else:
            for index, link in enumerate(links):
                if not isinstance(link, dict):
                    errors.append(f"links[{index}] must be an object")
                    continue
                for field in ["label", "url"]:
                    iteration_review_required_string(link, field, errors)

    technical = record.get("technical")
    if technical is not None:
        if not isinstance(technical, dict):
            errors.append("technical must be an object when present")
        else:
            iteration_review_required_string(technical, "summary", errors)
            iteration_review_validate_string_list(technical.get("changes"), "technical.changes", errors)
            iteration_review_validate_string_list(technical.get("evidence"), "technical.evidence", errors)
            prs = technical.get("prs")
            if not isinstance(prs, list):
                errors.append("technical.prs must be an array")
            else:
                for index, pr in enumerate(prs):
                    if not isinstance(pr, dict):
                        errors.append(f"technical.prs[{index}] must be an object")
                        continue
                    for field in ["id", "title"]:
                        iteration_review_required_string(pr, field, errors)
    iteration_review_validate_customer_copy(record, errors)
    return errors


def iteration_review_hosting_base_url(cfg: dict) -> str:
    return str(cfg["hosting"].get("baseUrl") or "").strip().rstrip("/")


def iteration_review_url_is_hosted(cfg: dict, url: str) -> bool:
    value = str(url or "").strip()
    base_url = iteration_review_hosting_base_url(cfg)
    if not value or not base_url:
        return False
    return value == base_url or value.startswith(f"{base_url}/")


def iteration_review_media_references(record: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for key in ["videoUrl", "posterUrl"]:
        value = str(record.get(key) or "").strip()
        if value:
            refs.append((key, value))
    highlight = record.get("highlight")
    if isinstance(highlight, dict):
        value = str(highlight.get("image") or "").strip()
        if value:
            refs.append(("highlight.image", value))
    usage = record.get("usage")
    if isinstance(usage, list):
        for index, item in enumerate(usage):
            if not isinstance(item, dict):
                continue
            value = str(item.get("src") or "").strip()
            if value:
                refs.append((f"usage[{index}].src", value))
    return refs


def iteration_review_output_contract_issues(record: dict, cfg: dict, page_path: Path | None = None) -> list[str]:
    issues: list[str] = []
    if cfg["outputs"].get("page") and page_path is not None and not page_path.exists():
        issues.append(f"iterationReview.outputs.page requires generated index.html before publish: {page_path}")
    video_url = str(record.get("videoUrl") or "").strip()
    if cfg["outputs"].get("video"):
        if not video_url:
            issues.append("iterationReview.outputs.video requires a hosted videoUrl before validate/publish; render and upload the recap video before publishing the stakeholder review")
        elif not iteration_review_url_is_hosted(cfg, video_url):
            issues.append("iterationReview.outputs.video requires videoUrl to use adapter iterationReview.hosting.baseUrl")
        if page_path is not None and page_path.exists():
            try:
                page_text = page_path.read_text(encoding="utf-8")
            except OSError:
                page_text = ""
            if "Video appears here when this review includes a hosted recap" in page_text or 'class="empty-video"' in page_text:
                issues.append("iterationReview.outputs.video requires generated index.html to embed the hosted videoUrl; regenerate the page after adding videoUrl")
            elif video_url and video_url not in page_text:
                issues.append("iterationReview.outputs.video requires generated index.html to reference the hosted videoUrl; regenerate the page after adding videoUrl")
    for path, url in iteration_review_media_references(record):
        if not iteration_review_url_is_hosted(cfg, url):
            issues.append(f"{path} must use adapter-approved S3/CloudFront base URL: {url}")
    return issues


def iteration_review_required_outputs_satisfied(record: dict, cfg: dict, page_path: Path | None = None) -> str:
    page_ok = (not cfg["outputs"].get("page")) or page_path is None or page_path.exists()
    video_url = str(record.get("videoUrl") or "").strip()
    video_ok = (not cfg["outputs"].get("video")) or (bool(video_url) and iteration_review_url_is_hosted(cfg, video_url))
    return f"page={str(page_ok).lower()} video={str(video_ok).lower()}"


ITERATION_REVIEW_OPERATOR_APPROVAL_TOKEN = "OPERATOR_APPROVED_PARTIAL_ITERATION_REVIEW"


def iteration_review_operator_approval_ok(args: argparse.Namespace) -> bool:
    return str(getattr(args, "operator_approval_token", "") or "").strip() == ITERATION_REVIEW_OPERATOR_APPROVAL_TOKEN


def iteration_review_builtin_music_credit(url: str) -> str:
    if url.strip().lower() == "builtin:minervit-midnight-pulse":
        return "Minervit Midnight Pulse"
    return ""


def iteration_review_apply_media_defaults(record: dict, cfg: dict) -> tuple[dict, list[str]]:
    updated = dict(record)
    applied: list[str] = []
    music = cfg["video"]["music"]
    default_url = str(music.get("defaultUrl") or "").strip()
    if (
        cfg["outputs"].get("video")
        and music.get("enabled")
        and default_url
        and not str(updated.get("musicUrl") or "").strip()
    ):
        updated["musicUrl"] = default_url
        applied.append("musicUrl")
        if "musicVolume" not in updated:
            updated["musicVolume"] = music["volume"]
            applied.append("musicVolume")
        if not str(updated.get("musicCredit") or "").strip():
            credit = iteration_review_builtin_music_credit(default_url)
            if credit:
                updated["musicCredit"] = credit
                applied.append("musicCredit")
    return updated, applied


def iteration_review_poster_lines(value: str, *, max_chars: int, max_lines: int) -> list[str]:
    words = re.sub(r"\s+", " ", value.strip()).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(" .") + "..."
    return lines or ["Iteration review"]


def iteration_review_generated_poster_data_uri(record: dict) -> str:
    title_lines = iteration_review_poster_lines(str(record.get("goalTitle") or "Iteration Review"), max_chars=28, max_lines=3)
    heading = str((record.get("highlight") or {}).get("heading") or record.get("why") or "See what shipped.").strip()
    heading_lines = iteration_review_poster_lines(heading, max_chars=52, max_lines=2)
    status = str(record.get("status") or "Complete").strip()
    date = str(record.get("date") or "").strip()
    meta = f"{status} - {date}" if date else status
    kicker = str(record.get("kicker") or f"{record.get('product', 'Minervit')} iteration review").strip()
    title_tspans = "\n".join(
        f'<tspan x="96" dy="{0 if index == 0 else 74}">{escape(line)}</tspan>'
        for index, line in enumerate(title_lines)
    )
    heading_tspans = "\n".join(
        f'<tspan x="96" dy="{0 if index == 0 else 34}">{escape(line)}</tspan>'
        for index, line in enumerate(heading_lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#f7f9fc"/>
      <stop offset="0.58" stop-color="#f6f4ef"/>
      <stop offset="1" stop-color="#e8f7f1"/>
    </linearGradient>
    <linearGradient id="stripe" x1="0" x2="1">
      <stop offset="0" stop-color="#2f6fed"/>
      <stop offset="0.52" stop-color="#10a37f"/>
      <stop offset="1" stop-color="#f59e0b"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#162233" flood-opacity=".16"/>
    </filter>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <path d="M0 104H1280M0 272H1280M0 440H1280M0 608H1280" stroke="#2f6fed" stroke-opacity=".07"/>
  <rect x="54" y="54" width="1172" height="612" rx="34" fill="#ffffff" stroke="#d8e2ef" filter="url(#shadow)"/>
  <rect x="54" y="54" width="1172" height="10" rx="5" fill="url(#stripe)"/>
  <text x="96" y="126" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="25" font-weight="800" fill="#2f6fed">{escape(kicker.upper())}</text>
  <text x="96" y="228" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="68" font-weight="850" fill="#172033">{title_tspans}</text>
  <text x="96" y="470" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="30" font-weight="500" fill="#5d6b7c">{heading_tspans}</text>
  <g transform="translate(96 556)">
    <rect width="286" height="64" rx="16" fill="#172033"/>
    <circle cx="33" cy="32" r="19" fill="#ffffff"/>
    <polygon points="29,22 29,42 45,32" fill="#2f6fed"/>
    <text x="67" y="41" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="26" font-weight="800" fill="#ffffff">Watch recap</text>
  </g>
  <text x="1004" y="604" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="23" font-weight="800" fill="#10a37f">{escape(meta)}</text>
  <text x="1004" y="634" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" font-size="18" fill="#8a96a8">Iteration Review</text>
  <circle cx="1095" cy="590" r="54" fill="#eef5ff" stroke="#d8e2ef"/>
  <polygon points="1081,562 1081,618 1126,590" fill="#2f6fed"/>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe=":/,;=-_.!~*'()")


def iteration_review_default_page_path(record_path: Path) -> Path:
    if record_path.name == "goal-review.json":
        return record_path.parent / "index.html"
    return record_path.with_suffix(".html")


def iteration_review_public_url(cfg: dict, prefix: str, filename: str) -> str:
    base_url = str(cfg["hosting"].get("baseUrl", "")).strip().rstrip("/")
    if not base_url:
        raise SystemExit("iterationReview.hosting.baseUrl must be configured before publishing iteration reviews")
    return f"{base_url}/{prefix.strip('/')}/{filename}"


def iteration_review_marker_unreasoned_repeats(marker_path: Path) -> int:
    """Count repeat Chat posts after the first that lack a repeatReason (RCA O18). A marker with
    such repeats is a duplicate-card defect, not a valid delivery; both the delivery check and the
    goal-complete gate use this so neither can be bypassed (Codex P2)."""
    if not marker_path.exists():
        return 0
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    history = marker.get("postHistory") if isinstance(marker.get("postHistory"), list) else []
    return sum(
        1
        for entry in history[1:]
        if isinstance(entry, dict) and not entry.get("skipped") and not str(entry.get("repeatReason") or "").strip()
    )


def iteration_review_delivery_marker_matches(
    marker_path: Path,
    *,
    record_hash: str,
    page_hash: str,
    page_url: str,
    accept_skipped: bool = False,
) -> bool:
    if not marker_path.exists():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if marker.get("skipped"):
        # An operator-approved skip with a non-blank recorded reason, matching the current
        # artifacts (record/page hashes AND page URL), satisfies the delivery gate (RCA O11: a
        # skipped delivery must be durably recorded with a reason, not asserted — Codex P2).
        return bool(
            accept_skipped
            and marker.get("operatorApproved")
            and str(marker.get("skipReason") or "").strip()
            and marker.get("recordSha256") == record_hash
            and marker.get("pageSha256") == page_hash
            and marker.get("pageUrl") == page_url
        )
    return (
        marker.get("recordSha256") == record_hash
        and marker.get("pageSha256") == page_hash
        and marker.get("pageUrl") == page_url
    )


def iteration_review_chat_payload(record: dict, page_url: str) -> dict:
    video_url = str(record.get("videoUrl") or "").strip()
    lines = [
        f"{record['product']} iteration review: {record['goalTitle']}",
        "",
        str(record["why"]).strip(),
        "",
        f"Review page: {page_url}",
    ]
    if video_url:
        lines.append(f"Video: {video_url}")
    return {"text": "\n".join(lines)}


def iteration_review_after_merge_workflow_yaml(data: dict) -> str:
    """A ready-to-wire GitHub Actions workflow that publishes the iteration review after the
    review record lands on the base branch (RCA O8: after-merge delivery had no automation, so
    it silently never posted). The operator wires the webhook env var as a repo secret."""
    cfg = iteration_review_config(data)
    webhook_env = str(cfg["delivery"].get("webhookEnv") or "GOOGLE_CHAT_WEBHOOK").strip()
    record_dir = str(data["iterationReview"].get("recordDir") or "docs/iteration-reviews").strip().rstrip("/")
    return "\n".join(
        [
            "name: Publish Iteration Review (after merge)",
            "# Generated by `tautline emit-iteration-review-workflow`.",
            f"# Wire {webhook_env} as a repository secret and set the goal-review record path below.",
            "on:",
            "  push:",
            "    branches: [main]",
            "    paths:",
            f'      - "{record_dir}/**"',
            "permissions:",
            "  contents: read",
            "  id-token: write",
            "jobs:",
            "  publish-iteration-review:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - name: Publish iteration review",
            "        env:",
            f"          {webhook_env}: ${{{{ secrets.{webhook_env} }}}}",
            "        run: |",
            "          tautline publish-iteration-review \\",
            "            --target . \\",
            f"            --record {record_dir}/<goal-id>/goal-review.json",
            "",
        ]
    )
