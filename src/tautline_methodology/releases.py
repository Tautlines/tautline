"""Release metadata helpers for the Minervit methodology CLI."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPO_ROOT / "VERSION"
RELEASE_MIGRATION_REPORTS_DIR = REPO_ROOT / "docs" / "releases" / "migrations"
RELEASE_NOTES_FILE = REPO_ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
RELEASE_UPDATE_DELIVERY_FILE = REPO_ROOT / "docs" / "releases" / "release-update-delivery.json"
RELEASE_UPDATE_DELIVERY_SCHEMA = "minervit-release-update-delivery/v1"


def release_migration_report_path(version: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._+-]+", "-", version.strip() or "current")
    return RELEASE_MIGRATION_REPORTS_DIR / f"{safe}.json"


def load_release_migration_report(version: str) -> dict | None:
    path = release_migration_report_path(version)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def changelog_release_blocks(path: Path | None = None) -> list[dict[str, str]]:
    text = (path or CHANGELOG_FILE).read_text(encoding="utf-8")
    pattern = re.compile(
        r"^## \[?(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\]? - (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\n(?P<body>.*?)(?=^## \[?[0-9]+\.[0-9]+\.[0-9]+\]? - |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    return [match.groupdict() for match in pattern.finditer(text)]


def changelog_release_block(version: str) -> dict[str, str] | None:
    return next((item for item in changelog_release_blocks() if item["version"] == version), None)


def changelog_bullets(body: str, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            if current:
                bullets.append(" ".join(current).strip())
                current = []
                if len(bullets) >= limit:
                    break
            current = [stripped[2:].strip()]
            continue
        if current and stripped and not stripped.startswith("#"):
            current.append(stripped)
            continue
        if current:
            bullets.append(" ".join(current).strip())
            current = []
            if len(bullets) >= limit:
                break
    if current and len(bullets) < limit:
        bullets.append(" ".join(current).strip())
    return bullets


def release_note_blocks() -> list[dict[str, str]]:
    text = RELEASE_NOTES_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^## (?P<version>[0-9]+\.[0-9]+\.[0-9]+) - (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\n(?P<body>.*?)(?=^## [0-9]+\.[0-9]+\.[0-9]+ - |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    return [match.groupdict() for match in pattern.finditer(text)]


def release_note_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^### {re.escape(heading)}\s*$", flags=re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    next_heading = re.search(r"^###\s+", body[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(body)
    return body[match.end() : end].strip()


def release_note_first_paragraph(section: str, max_chars: int = 520) -> str:
    section_without_code = re.sub(r"```.*?```", "", section.strip(), flags=re.DOTALL)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section_without_code) if part.strip()]
    paragraph = ""
    for candidate in paragraphs:
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not candidate or candidate.endswith(":"):
            continue
        paragraph = candidate
        break
    if not paragraph:
        return ""
    if len(paragraph) <= max_chars:
        return paragraph
    return paragraph[: max_chars - 1].rstrip() + "..."


def release_note_bullets(section: str, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        if len(bullets) >= limit:
            break
    return bullets


def release_update_content(version: str) -> dict[str, object]:
    block = next((item for item in release_note_blocks() if item["version"] == version), None)
    if block:
        index = release_note_bullets(release_note_section(block["body"], "Release Index"), limit=4)
        summary = release_note_first_paragraph(release_note_section(block["body"], "Executive Summary"))
        operator = release_note_first_paragraph(release_note_section(block["body"], "Operator Impact"), max_chars=360)
        if index or summary or operator:
            return {"summary": summary or "Release notes were updated.", "index": index, "operator": operator}

    changelog_block = changelog_release_block(version)
    if not changelog_block:
        raise SystemExit(f"release metadata missing version: {version}")
    bullets = changelog_bullets(changelog_block["body"], limit=4)
    summary = bullets[0] if bullets else "Release metadata was updated."
    operator = ""
    report = load_release_migration_report(version)
    rollback_notes = report.get("rollbackNotes") if isinstance(report, dict) else None
    if isinstance(rollback_notes, list):
        operator = " ".join(str(note).strip() for note in rollback_notes[:2] if str(note).strip())
    return {"summary": summary, "index": bullets, "operator": operator}


def release_update_block(version: str) -> dict:
    block = next((item for item in release_note_blocks() if item["version"] == version), None)
    if not block:
        changelog_block = changelog_release_block(version)
        if changelog_block:
            return changelog_block
        raise SystemExit(f"release metadata missing version: {version}")
    return block


def release_update_lines(version: str) -> list[str]:
    """Plain-text rendering of a release update (used for --dry-run output and logs)."""
    content = release_update_content(version)
    index = [str(item) for item in content["index"]]
    summary = str(content["summary"])
    operator = str(content["operator"])
    lines = [
        f"Minervit methodology {version}",
        "",
        summary or "Release notes were updated.",
    ]
    if index:
        lines.extend(["", "Highlights:"])
        lines.extend(f"- {bullet}" for bullet in index)
    if operator:
        lines.extend(["", f"Operator impact: {operator}"])
    return lines


def release_update_payload(
    version: str,
    *,
    card_text: Callable[[str], str],
    slugify_func: Callable[..., str],
) -> dict:
    # Card-only Google Chat message (see google_chat_card_only): a single cardsV2 card,
    # never a duplicate top-level "text".
    content = release_update_content(version)
    index = [str(item) for item in content["index"]]
    summary = str(content["summary"])
    operator = str(content["operator"])
    sections: list[dict] = [
        {"widgets": [{"textParagraph": {"text": card_text(summary or "Release notes were updated.")}}]}
    ]
    if index:
        bullets = "<br>".join(f"• {card_text(bullet)}" for bullet in index)
        sections.append({"header": "Highlights", "widgets": [{"textParagraph": {"text": bullets}}]})
    if operator:
        sections.append({"header": "Operator impact", "widgets": [{"textParagraph": {"text": card_text(operator)}}]})
    return {
        "cardsV2": [
            {
                "cardId": f"release-update-{slugify_func(version, fallback='release')}",
                "card": {
                    "header": {"title": "Minervit methodology", "subtitle": version},
                    "sections": sections,
                },
            }
        ]
    }


def release_update_versions(
    *,
    version: str | None,
    last: int | None,
    current_version: str,
    blocks: list[dict[str, str]] | None = None,
) -> list[str]:
    if last:
        if last < 1:
            raise SystemExit("--last must be positive")
        release_blocks = blocks if blocks is not None else changelog_release_blocks()
        return [block["version"] for block in reversed(release_blocks[:last])]
    return [version or current_version]


def release_update_version_key(version: str) -> tuple:
    parts: list[int] = []
    for chunk in str(version).split("."):
        match = re.match(r"\d+", chunk)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts)


def release_update_delivery_file(repo_root: Path = REPO_ROOT) -> Path:
    if repo_root.resolve(strict=False) == REPO_ROOT.resolve(strict=False):
        return RELEASE_UPDATE_DELIVERY_FILE
    return repo_root / "docs" / "releases" / "release-update-delivery.json"


def release_update_version_file(repo_root: Path = REPO_ROOT) -> Path:
    if repo_root.resolve(strict=False) == REPO_ROOT.resolve(strict=False):
        return VERSION_FILE
    return repo_root / "VERSION"


def release_update_delivery_load(repo_root: Path = REPO_ROOT) -> dict:
    """Load the committed release-update delivery ledger, tolerating a missing/corrupt file."""
    delivery_file = release_update_delivery_file(repo_root)
    try:
        data = json.loads(delivery_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": RELEASE_UPDATE_DELIVERY_SCHEMA, "delivered": {}}
    if (
        not isinstance(data, dict)
        or data.get("schema") != RELEASE_UPDATE_DELIVERY_SCHEMA
        or not isinstance(data.get("delivered"), dict)
    ):
        return {"schema": RELEASE_UPDATE_DELIVERY_SCHEMA, "delivered": {}}
    if "suspended" in data and not isinstance(data.get("suspended"), dict):
        data["suspended"] = {}
    return data


def release_update_delivered_versions(repo_root: Path = REPO_ROOT) -> set[str]:
    return set(release_update_delivery_load(repo_root).get("delivered", {}).keys())


def release_update_current_version(repo_root: Path = REPO_ROOT) -> str:
    try:
        version = release_update_version_file(repo_root).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        return ""
    return version


def release_update_suspended_versions(repo_root: Path = REPO_ROOT) -> set[str]:
    """Versions with documented release-update suspension evidence.

    Suspension is not a silent bypass: each entry needs an operator/source, a
    scope, a reason, and a timestamp before it can satisfy release accountability.
    """
    suspended = release_update_delivery_load(repo_root).get("suspended", {})
    valid: set[str] = set()
    if not isinstance(suspended, dict):
        return valid
    current = release_update_current_version(repo_root)
    current_key = release_update_version_key(current) if current else None
    known_versions = {block["version"] for block in changelog_release_blocks(repo_root / "CHANGELOG.md")}
    allowed_via = {"operator-instruction", "maintainer-backfill"}
    for version, record in suspended.items():
        version = str(version)
        if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
            continue
        if version not in known_versions:
            continue
        if current_key is not None and release_update_version_key(version) > current_key:
            continue
        if not isinstance(record, dict):
            continue
        required = ("at", "via", "scope", "reason")
        if not all(isinstance(record.get(key), str) and record.get(key, "").strip() for key in required):
            continue
        try:
            datetime.fromisoformat(record["at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if record["via"].strip() not in allowed_via:
            continue
        valid.add(version)
    return valid


def release_update_accounted_versions(repo_root: Path = REPO_ROOT) -> set[str]:
    return release_update_delivered_versions(repo_root) | release_update_suspended_versions(repo_root)


def release_update_record_delivery(version: str, *, via: str = "publish-release-update") -> None:
    """Record that a release-update card for `version` was delivered to Google Chat."""
    version = str(version).strip()
    if not version:
        return
    data = release_update_delivery_load()
    delivered = data.setdefault("delivered", {})
    delivered[version] = {"at": datetime.now(timezone.utc).isoformat(), "via": via}
    data["schema"] = RELEASE_UPDATE_DELIVERY_SCHEMA
    data["delivered"] = dict(sorted(delivered.items(), key=lambda kv: release_update_version_key(kv[0])))
    suspended = data.get("suspended")
    if isinstance(suspended, dict):
        data["suspended"] = dict(sorted(suspended.items(), key=lambda kv: release_update_version_key(kv[0])))
    RELEASE_UPDATE_DELIVERY_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def release_update_overdue(versions: list[str], delivered: set[str], current: str) -> list[str]:
    """Released versions already on the base branch (older than `current`) with no delivery marker.

    The current VERSION is excluded because its card is posted after merge; future versions are
    excluded. Pure function so validate.sh and the CLI status command share one definition.
    """
    current_key = release_update_version_key(current)
    overdue: list[str] = []
    for version in versions:
        if version == current:
            continue
        if release_update_version_key(version) > current_key:
            continue
        if version not in delivered:
            overdue.append(version)
    return overdue


def release_update_overdue_versions(repo_root: Path = REPO_ROOT) -> list[str]:
    current = release_update_current_version(repo_root)
    if not current:
        return []
    versions = [block["version"] for block in changelog_release_blocks(repo_root / "CHANGELOG.md")]
    return release_update_overdue(versions, release_update_accounted_versions(repo_root), current)


def release_update_public_release_issues(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    """No issues: the Google Chat delivery marker this used to demand can no longer be produced.

    The 2026-08-28 process-bankruptcy demolition removed `publish-release-update`, the chat
    transport behind it, and every other notify publisher. This function used to refuse a public
    release whose versions carried no delivery marker, and its remedy named that verb. Left as it
    was it would have become the worst kind of gate -- one that cannot be satisfied by any action
    available to the operator, whose only escape is to bypass it.

    Kept as a function rather than deleted because `public_release_issues` calls it and the delivery
    ACCOUNTING below it (`release_update_status_summary`, the marker readers) is still meaningful
    for the historical record. If a delivery seam returns, this is where its gate goes back.
    """
    return []


def release_update_status_summary(
    *,
    current: str,
    delivered: set[str],
    suspended: set[str],
    overdue: list[str],
    require_current: bool,
) -> dict[str, object]:
    accounted = delivered | suspended
    current_required_missing = require_current and current not in accounted
    return {
        "current_version": current,
        "current_delivered": current in delivered,
        "current_suspended": current in suspended,
        "current_accounted": current in accounted,
        "current_required": require_current,
        "current_required_missing": current_required_missing,
        "delivered_count": len(delivered),
        "suspended_count": len(suspended),
        "accounted_count": len(accounted),
        "overdue": overdue,
    }


def release_update_status_lines(summary: dict[str, object]) -> list[str]:
    current = str(summary["current_version"])
    current_delivered = bool(summary["current_delivered"])
    current_suspended = bool(summary["current_suspended"])
    current_required = bool(summary["current_required"])
    current_required_missing = bool(summary["current_required_missing"])
    overdue = [str(version) for version in summary["overdue"]]
    if current_delivered:
        current_status = "yes"
    elif current_suspended:
        current_status = "suspended (documented operator decision)"
    elif current_required:
        current_status = "no (required for release check)"
    else:
        current_status = "no (posted after merge)"
    lines = [
        f"release_update_current_version: {current}",
        f"release_update_current_delivered: {current_status}",
        f"release_update_delivered_count: {summary['delivered_count']}",
        f"release_update_suspended_count: {summary['suspended_count']}",
    ]
    if overdue:
        lines.append("release_update_overdue:")
        lines.extend(
            f"  - {version} (no Google Chat delivery marker; run: minervit-methodology publish-release-update --version {version})"
            for version in overdue
        )
    else:
        lines.append("release_update_overdue: none")
    if current_required_missing:
        lines.append("release_update_current_required_missing:")
        lines.append(
            f"  - {current} (current release marker required by maintainer release check; run: "
            f"minervit-methodology publish-release-update --version {current})"
        )
    return lines
