"""Backlog / stakeholder-question leaves: the backlog-item business-lead justification
scanners and their heading constants, plus stakeholder-question config/marker/parse/
substantive-answer helpers. The stateful verb handlers (backlog_provider_status,
backlog_board_examine, stakeholder_question_ask, ...) stay in bin/tautline; they reach
lane/adapter/board state and delegate the pure helpers here."""

from __future__ import annotations

import re


def backlog_provider_completion_unit(data: dict) -> str:
    provider = data.get("backlogProvider") if isinstance(data, dict) else {}
    if not isinstance(provider, dict) or not provider.get("enabled"):
        return "goal"
    value = str(provider.get("completionUnit") or "goal").strip().lower()
    return value if value in {"goal", "provider-item"} else "goal"


def backlog_provider_done_evidence_comment(evidence: str) -> str:
    return "## Verification Evidence\n\n" + evidence.strip() + "\n"


BACKLOG_LEAD_WHAT_HEADINGS = ["what this delivers", "what it delivers", "what is it", "what is this", "what"]


BACKLOG_LEAD_WHY_HEADINGS = ["why it matters", "why we care", "why this matters", "value", "what value", "business value"]


BACKLOG_LEAD_MIN_CHARS = 24


def _backlog_lead_section(text: str, headings: list[str]) -> tuple[int, str] | None:
    """Earliest-by-position heading matching any of `headings` (exact, case-insensitive, levels
    `#`-`######`), with its section content (to the next heading of any level). Using the EARLIEST
    occurrence keeps the content check and the ordering check on the SAME section, so a placeholder
    `## What` near the top cannot borrow content from a real `## What this delivers` lower down
    (Codex). Returns (position, content) or None."""
    names = {h.lower() for h in headings}
    best: tuple[int, str] | None = None
    for match in re.finditer(r"(?im)^#{1,6}\s*(.+?)\s*$", text):
        if match.group(1).strip().lower() in names and (best is None or match.start() < best[0]):
            rest = text[match.end():]
            next_heading = re.search(r"(?m)^#{1,6}\s+\S", rest)
            content = (rest[: next_heading.start()] if next_heading else rest).strip()
            best = (match.start(), content)
    return best


def _backlog_lead_section_content(text: str, headings: list[str]) -> str | None:
    section = _backlog_lead_section(text, headings)
    return section[1] if section is not None else None


def _backlog_lead_content_ok(content: str | None) -> bool:
    """Real plain-language content: enough characters AND several distinct words, so a placeholder
    like `xxxxxxxxxxxxxxxxxxxxxxxx` does not pass (mirrors the customer-facing justification guard)."""
    if content is None:
        return False
    if len(re.sub(r"\s+", "", content)) < BACKLOG_LEAD_MIN_CHARS:
        return False
    distinct_words = len({word for word in re.findall(r"[a-z0-9]+", content.lower()) if len(word) > 1})
    return distinct_words >= 4


def backlog_item_missing_business_lead(body: str) -> str:
    """Pure: every backlog item must LEAD with plain-language business framing -- what it delivers
    and why it matters -- before technical detail (RCA: items were rote technical readings with no
    business context). Returns a drift/refusal message naming what is missing, or '' when compliant.
    Empty/whitespace body is itself missing the lead."""
    text = body or ""
    what = _backlog_lead_section(text, BACKLOG_LEAD_WHAT_HEADINGS)
    why = _backlog_lead_section(text, BACKLOG_LEAD_WHY_HEADINGS)
    missing = []
    if what is None or not _backlog_lead_content_ok(what[1]):
        missing.append("a plain-language `## What this delivers` section")
    if why is None or not _backlog_lead_content_ok(why[1]):
        missing.append("a plain-language `## Why it matters` section")
    if missing:
        return (
            "backlog item does not lead with a business justification: it is missing "
            + " and ".join(missing)
            + ". Every item must explain in plain language what it delivers and why it matters before technical detail."
        )
    # Lead off: What and Why must be the FIRST section headings. Any other `##`+ section before
    # both of them (e.g. `## Technical detail`, `## Implementation notes`, `## Technical approach`)
    # means the item does not lead with the business justification. This catches every technical
    # heading variant without enumerating them; a leading `#` (level-1) title is ignored (Codex).
    business_names = {h.lower() for h in BACKLOG_LEAD_WHAT_HEADINGS + BACKLOG_LEAD_WHY_HEADINGS}
    lead_end = max(what[0], why[0])
    headings = list(re.finditer(r"(?im)^(#{1,6})\s*(.+?)\s*$", text))
    for idx, match in enumerate(headings):
        if match.start() >= lead_end:
            break
        if match.group(2).strip().lower() in business_names:
            continue
        # Allow a single leading level-1 document TITLE (first heading, `#`, with no substantial
        # body). A level-1 heading that carries real content before What/Why is a section, not a
        # title, and must NOT be skipped (Codex: `# Technical approach` with a paragraph).
        if idx == 0 and len(match.group(1)) == 1:
            section_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
            title_body = text[match.end():section_end]
            if len(re.sub(r"\s+", "", title_body)) < BACKLOG_LEAD_MIN_CHARS:
                continue
        return (
            f"backlog item does not lead with the business justification: the section `{match.group(2).strip()}` "
            "appears before `## What this delivers` / `## Why it matters`. Lead with the business framing, then technical detail."
        )
    return ""


STAKEHOLDER_QUESTION_MARKER = "tautline-question"


STAKEHOLDER_QUESTION_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=\"([^\"]*)\"")


def stakeholder_questions_config(data: dict) -> dict:
    return data["stakeholderQuestions"]


def stakeholder_questions_status_summary(data: dict) -> str:
    config = stakeholder_questions_config(data)
    if not config["enabled"]:
        return "stakeholder_questions: enabled=false"
    default = f" default={config['defaultMention']}" if config.get("defaultMention") else " default=unknown"
    sync = ",".join(config.get("syncAt", [])) or "none"
    return (
        "stakeholder_questions: enabled=true provider=github-issues"
        f"{default} open_label={config['openLabel']} answered_label={config['answeredLabel']} sync_at={sync}"
    )


def stakeholder_login_from_mention(mention: str) -> str:
    return mention.strip().lstrip("@").lower()


def stakeholder_question_marker(attrs: dict[str, str]) -> str:
    parts = []
    for key in ["id", "status", "asked_at", "answered_at", "stakeholder", "issue"]:
        value = str(attrs.get(key, "")).strip()
        if value:
            safe = value.replace('"', "'")
            parts.append(f'{key}="{safe}"')
    return f"<!-- {STAKEHOLDER_QUESTION_MARKER} {' '.join(parts)} -->"


def stakeholder_question_parse_markers(body: str) -> list[dict[str, str]]:
    markers = []
    for match in re.finditer(r"<!--\s*(?:tautline|minervit)-question\s+([^>]*)-->", body or ""):
        attrs = {key: value for key, value in STAKEHOLDER_QUESTION_ATTR_RE.findall(match.group(1))}
        if attrs.get("id"):
            markers.append(attrs)
    return markers


def stakeholder_question_answer_is_substantive(body: str) -> bool:
    text = re.sub(r"\s+", " ", body or "").strip()
    if len(text) < 24 or len(re.findall(r"[A-Za-z0-9]+", text)) < 4:
        return False
    non_answer_patterns = [
        r"(?i)^\+1$",
        r"(?i)^ok(?:ay)?[.!]?$",
        r"(?i)^thanks?[.!]?$",
        r"(?i)\b(looking into it|checking|i'?ll check|will check|get back to you|not sure yet|need to think|following up)\b",
    ]
    return not any(re.search(pattern, text) for pattern in non_answer_patterns)
