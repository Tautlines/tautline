"""Milestone-tracking leaves: the milestone-update config accessor and the milestone-run
ledger record/percent/integrity helpers. The stateful verb handlers (milestone_start,
milestone_status, milestone_advance, publish_milestone_update, ...) stay in bin/tautline;
they reach lane/adapter/milestone-run state and delegate the pure helpers here."""

from __future__ import annotations


def milestone_update_config(data: dict) -> dict:
    return data["milestoneUpdate"]


MILESTONE_TERMINAL_STATUSES = {"pr_queued", "merged", "complete", "deferred"}


def milestone_status_from_action(action: dict) -> str:
    if action["type"] == "milestone_complete":
        return "complete"
    if action["type"] == "true_blocker":
        return "blocked"
    return "active"


def milestone_run_integrity_issues(run: dict) -> list[str]:
    issues: list[str] = []
    for item in run.get("items", []):
        status = item.get("status")
        if status in {"pr_queued", "merged"} and not item.get("pr"):
            issues.append(f"item {item.get('index')} is {status} but has no PR recorded")
        if status == "blocked" and not item.get("blockers"):
            issues.append(f"item {item.get('index')} is blocked but has no blocker reason")
    return issues


def milestone_percent_complete(run: dict) -> int:
    items = run.get("items", [])
    if not items:
        return 0
    done = sum(1 for item in items if item.get("status") in MILESTONE_TERMINAL_STATUSES)
    return int(round((done / len(items)) * 100))


def milestone_next_action_record(run: dict) -> dict:
    items = run.get("items", [])
    for item in items:
        if item.get("status") == "in_progress":
            return {
                "type": "continue_item",
                "itemIndex": item["index"],
                "itemTitle": item["title"],
                "instruction": f"Continue item {item['index']}: {item['title']}",
            }
    for item in items:
        if item.get("status") == "pending":
            return {
                "type": "start_item",
                "itemIndex": item["index"],
                "itemTitle": item["title"],
                "instruction": f"Start item {item['index']}: {item['title']}",
            }
    blocked = [item for item in items if item.get("status") == "blocked"]
    if blocked:
        item = blocked[0]
        blockers = "; ".join(item.get("blockers") or ["blocked with no reason recorded"])
        return {
            "type": "true_blocker",
            "itemIndex": item["index"],
            "itemTitle": item["title"],
            "instruction": f"True blocker on item {item['index']}: {blockers}",
        }
    return {
        "type": "milestone_complete",
        "itemIndex": None,
        "itemTitle": None,
        "instruction": "Prove milestone completion from the ledger, execution packet/backlog readiness, open PR state, continuity handoff, and session journal, then start the next source-of-truth item or automatic planning flow unless a true blocker remains.",
    }
