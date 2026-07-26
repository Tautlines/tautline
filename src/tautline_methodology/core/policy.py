"""Shared repo-event guard/marker constants and the pure boundary-classification decision core."""

from __future__ import annotations

EVENT_LOG_SCHEMA = "minervit-repo-event/v1"
EVENT_START_SUFFIX = "_started"
EVENT_REQUIRED_BOUNDARY_FAMILIES = {
    "startup",
    "planning_review_gate",
    "preflight",
    "pr_queue_merge",
    "blocker",
    "rca",
    "continuity",
    "context_rotation",
    "goal_transition",
    "milestone_transition",
}
EVENT_TERMINAL_SUFFIXES = (
    "_passed",
    "_pass",
    "_completed",
    "_complete",
    "_finished",
    "_green",
    "_failed",
    "_fail",
    "_blocked",
    "_stale",
    "_timeout",
    "_timed_out",
    "_cancelled",
    "_canceled",
    "_queued",
    "_published",
    "_written",
)


def event_boundary_family(event: str, severity: str = "") -> str | None:
    if event == "startup" or event.startswith("startup_"):
        return "startup"
    if event.startswith(("plan_review", "planning_review")):
        return "planning_review_gate"
    if event.startswith("preflight_"):
        return "preflight"
    if event in {"pr_queued", "pr_queue", "pr_merged"} or event.startswith(("pr_queue_", "merge_queue_")):
        return "pr_queue_merge"
    if event.startswith("context_rotation"):
        return "context_rotation"
    if event.startswith("goal_advance") or event.startswith("goal_transition"):
        return "goal_transition"
    if event.startswith("milestone_advance") or event.startswith("milestone_transition"):
        return "milestone_transition"
    if "rca" in event:
        return "rca"
    if "continuity" in event:
        return "continuity"
    if severity in {"block", "fail"} or "blocker" in event or event.endswith("_blocked"):
        return "blocker"
    return None
