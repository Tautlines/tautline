"""Repo-event record helpers and the boundary-audit projection for the events family."""

from __future__ import annotations

import hashlib
import json

from .core.policy import (
    EVENT_LOG_SCHEMA,
    EVENT_REQUIRED_BOUNDARY_FAMILIES,
    EVENT_START_SUFFIX,
    EVENT_TERMINAL_SUFFIXES,
    event_boundary_family,
)


def event_record_id(record: dict) -> str:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:16]


def event_base_name(event: str) -> str:
    for suffix in (EVENT_START_SUFFIX, "_start"):
        if event.endswith(suffix):
            return event[: -len(suffix)]
    return event


def event_family_enabled(required_events: set[str] | None, family: str | None) -> bool:
    effective_required = set(EVENT_REQUIRED_BOUNDARY_FAMILIES) if required_events is None else required_events
    if family is None:
        return required_events is None
    return family in effective_required


def event_is_terminal_for(base: str, event: str) -> bool:
    if not event.startswith(base):
        return False
    return any(event.endswith(suffix) for suffix in EVENT_TERMINAL_SUFFIXES)


def audit_event_records(records: list[dict], required_events: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    effective_required = set(EVENT_REQUIRED_BOUNDARY_FAMILIES) if required_events is None else required_events
    unknown_required = sorted(effective_required - EVENT_REQUIRED_BOUNDARY_FAMILIES)
    for family in unknown_required:
        issues.append(f"unknown required boundary event family: {family}")
    for index, record in enumerate(records):
        event = str(record.get("event", ""))
        family = event_boundary_family(event, str(record.get("severity", "")))
        next_action = str(record.get("next", "")).strip().lower()
        if record.get("schema") != EVENT_LOG_SCHEMA:
            issues.append(f"invalid schema at event {index}: {event or 'unknown'}")
        if event_family_enabled(effective_required, "blocker") and str(record.get("severity")) in {"block", "fail"} and next_action in {"", "none", "n/a", "unknown"}:
            issues.append(f"{event}: blocker/failure event lacks concrete next action")
        if event.endswith(EVENT_START_SUFFIX) and event_family_enabled(effective_required, family):
            base = event_base_name(event)
            if not any(event_is_terminal_for(base, str(later.get("event", ""))) for later in records[index + 1 :]):
                issues.append(f"{event}: started event lacks a later terminal event")
        if (
            event_family_enabled(effective_required, "pr_queue_merge")
            and event in {"pr_queued", "pr_queue"}
            and not any(str(later.get("event", "")).startswith("milestone_advance") for later in records[index + 1 :])
        ):
            issues.append(f"{event}: PR queued without later milestone-advance event")
        if (
            event_family_enabled(effective_required, "rca")
            and event in {"rca_requested", "methodology_regression_rca_requested"}
            and not any("rca" in str(later.get("event", "")) and str(later.get("event", "")).endswith(("written", "published")) for later in records[index + 1 :])
        ):
            issues.append(f"{event}: RCA requested without later RCA artifact write/publish event")
        if event_family_enabled(effective_required, "continuity") and event in {"session_summary", "terminal_summary", "handoff_for_review", "workflow_complete"}:
            later_events = [str(later.get("event", "")) for later in records[index + 1 :]]
            if not any("continuity" in item and item.endswith(("written", "prepared", "refreshed")) for item in later_events):
                issues.append(f"{event}: terminal summary without later continuity event")
            if not any("session_journal" in item and item.endswith(("written", "published", "pending")) for item in later_events):
                issues.append(f"{event}: terminal summary without later session journal event")
        if event_family_enabled(effective_required, "startup") and event == "startup" and "stale" in f"{record.get('plain', '')} {record.get('next', '')}".lower():
            issues.append("startup: stale methodology evidence recorded")
    return issues
