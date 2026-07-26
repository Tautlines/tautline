"""Pure response-guard scan helpers for the Minervit methodology CLI."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


BLOCKER_SCHEMA = "minervit-blocker/v1"
BLOCKER_PATH = ".ai-work/BLOCKER.json"
BLOCKER_FRESH_SECONDS = 30 * 60
BLOCKER_KINDS = {
    "credentials",
    "external-access",
    "approval-needed",
    "failing-gate-no-safe-fix",
    "scope-change",
    "operator-stop-request",
    "no-safe-parallel-work",
}
NO_SAFE_PARALLEL_WORK_CHECKS = {
    "diff review",
    "allowed validation",
    "docs/evidence updates",
    "next queue item",
    "monitor follow-up",
}


def blocker_record_path(target: Path) -> Path:
    return target / BLOCKER_PATH


def parse_blocker_checked(value: str) -> list[str]:
    return [item.strip().lower() for item in str(value or "").split(",") if item.strip()]


def blocker_declare_error(kind: str, reason: str, checked: list[str]) -> str | None:
    if kind not in BLOCKER_KINDS:
        return f"blocker_declare_error: unknown kind {kind!r}; allowed={','.join(sorted(BLOCKER_KINDS))}"
    if not reason:
        return "blocker_declare_error: --reason is required"
    if kind == "no-safe-parallel-work":
        missing = sorted(NO_SAFE_PARALLEL_WORK_CHECKS - set(checked))
        if missing:
            return (
                "blocker_declare_error: no-safe-parallel-work requires --checked with "
                + ", ".join(sorted(NO_SAFE_PARALLEL_WORK_CHECKS))
                + f"; missing={','.join(missing)}"
            )
    return None


def utc_event_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def blocker_declare_record(
    *,
    kind: str,
    reason: str,
    artifact: str | None,
    goal_id: str | None,
    checked: list[str],
    timestamp: str | None = None,
) -> dict:
    record = {
        "schema": BLOCKER_SCHEMA,
        "ts": timestamp or utc_event_timestamp(),
        "kind": kind,
        "reason": reason,
        "artifact": artifact,
        "goal_id": goal_id,
    }
    if checked:
        record["checked"] = checked
    return record


def read_blocker_record(target: Path) -> tuple[dict | None, str | None]:
    path = blocker_record_path(target)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable: {exc}"


def blocker_status_result(target: Path, *, active_goal_id: str | None = None) -> tuple[int, list[str]]:
    record, error = read_blocker_record(target)
    if record is None:
        lines = ["blocker_status: missing"]
        if error:
            lines.append(f"stale_reason: {error}")
        return 1, lines
    fresh, reason = blocker_freshness(target, record, active_goal_id=active_goal_id)
    lines = [
        "blocker_status: present",
        f"fresh: {str(fresh).lower()}",
        f"kind: {record.get('kind') or 'unknown'}",
        f"goal_id: {record.get('goal_id') or 'none'}",
    ]
    if not fresh:
        lines.append(f"stale_reason: {reason}")
    return (0 if fresh else 1), lines


def guard_check_blocker_state_result(
    target: Path,
    *,
    active_goal_id: str | None = None,
) -> tuple[int, list[str], list[str]]:
    record, error = read_blocker_record(target)
    if record is None:
        if error == "missing":
            return 0, ["guard_check_blocker: none"], []
        return (
            1,
            [],
            [
                f"guard_check_blocker_issue: {error}",
                "guard_check: blocked - blocker record is unreadable; clear or redeclare it before push",
            ],
        )
    fresh, reason = blocker_freshness(target, record, active_goal_id=active_goal_id)
    stdout = [f"guard_check_blocker: present fresh={str(fresh).lower()} kind={record.get('kind') or 'unknown'}"]
    if fresh:
        return 0, stdout, []
    return (
        1,
        stdout,
        [
            f"guard_check_blocker_issue: stale BLOCKER.json ({reason})",
            "guard_check: blocked - stale blocker record claims the lane is blocked while this boundary proceeds; run blocker-clear or blocker-declare with current evidence",
        ],
    )


def blocker_freshness(
    target: Path,
    record: dict,
    *,
    active_goal_id: str | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    path = blocker_record_path(target)
    now = time.time() if now is None else now
    try:
        age_seconds = now - path.stat().st_mtime
    except OSError:
        return False, "missing"
    if age_seconds > BLOCKER_FRESH_SECONDS:
        return False, "older-than-30-minutes"
    if record.get("schema") != BLOCKER_SCHEMA:
        return False, "unsupported-schema"
    kind = str(record.get("kind") or "")
    if kind not in BLOCKER_KINDS:
        return False, "unknown-kind"
    record_goal_id = record.get("goal_id")
    if record_goal_id and not active_goal_id:
        return False, "goal-mismatch"
    if record_goal_id and active_goal_id and record_goal_id != active_goal_id:
        return False, "goal-mismatch"
    return True, "fresh"


def text_contains_any(text: str, phrases: list[str]) -> bool:
    lower = text.lower()
    for phrase in phrases:
        escaped = re.escape(phrase.lower())
        escaped = escaped.replace(r"\ ", r"\s+")
        prefix = r"(?<![A-Za-z0-9_])" if phrase[:1].isalnum() else ""
        suffix = r"(?![A-Za-z0-9_])" if phrase[-1:].isalnum() else ""
        if re.search(prefix + escaped + suffix, lower):
            return True
    return False


def response_guard_policy_scan_text(text: str) -> str:
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", " ", text)
    kept_lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    text = "\n".join(kept_lines)
    text = re.sub(r'"[^"\n]{1,240}"', " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])'[^'\n]{1,240}'(?![A-Za-z0-9])", " ", text)
    return text.lower()


def response_guard_monitor_scan_text(text: str) -> str:
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", " ", text)
    return text.lower()


def response_guard_context_scan_text(text: str) -> str:
    return (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .lower()
    )
