"""Goal-tracking leaves: pure goal-plan parsers, goal-run ledger record/percent/integrity
helpers, and GitHub-Projects goal-tracker field/value/item accessors. The stateful verb
handlers (goal_start, goal_status, goal_advance, goal_tracker_status, ...) stay in
bin/tautline; they reach lane/adapter/goal-run state and delegate the pure helpers here."""

from __future__ import annotations

import re
from pathlib import Path


GOAL_TERMINAL_STATUSES = {"complete", "deferred"}


def goal_plan_bullets(plan_text: str) -> list[str]:
    items: list[str] = []
    in_milestones = False
    for line in plan_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            in_milestones = heading in {"milestones", "ordered milestones", "milestone queue"}
            continue
        if not in_milestones:
            continue
        if line[:1].isspace():
            continue
        if re.match(r"^[-*]\s+\[[xX]\]\s+", stripped):
            continue
        match = re.match(r"^[-*]\s+(?:\[\s\]\s*)?(.+?)\s*$", stripped)
        if match:
            items.append(match.group(1))
    return items


def goal_operator_dependency_entries(goal_path: Path) -> list[str]:
    text = goal_path.read_text(encoding="utf-8")
    entries: list[str] = []
    in_relevant_section = False
    relevant_headings = {
        "dependencies",
        "risks",
        "risk",
        "true blockers",
        "true-blocker criteria",
        "blockers",
        "open decisions",
    }
    dependency_markers = re.compile(
        r"\b(?:operator(?:[-\s](?:provided|input|dependency|approval))?|human(?:[-\s](?:operator|input|approval))?|approval|credential|credentials|secret|secrets|manual|external access|true blocker|blocked by operator|operator-provided)\b",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            in_relevant_section = heading in relevant_headings or any(
                marker in heading for marker in ["risk", "dependenc", "blocker", "open decision"]
            )
            continue
        if not in_relevant_section or not stripped:
            continue
        if dependency_markers.search(stripped):
            cleaned = re.sub(r"^[-*]\s+(?:\[[ xX]\]\s*)?", "", stripped)
            entries.append(re.sub(r"\s+", " ", cleaned).strip("| "))
    return list(dict.fromkeys(entries))


def goal_dependency_matches_milestone(dependency: str, milestone: dict) -> bool:
    text = dependency.lower()
    index = milestone.get("index")
    if index is not None and re.search(rf"\b(?:m|milestone\s*){re.escape(str(index))}\b", text):
        return True
    title = str(milestone.get("title", "")).strip().lower()
    if title and title in text:
        return True
    title_tokens = [token for token in re.split(r"[^a-z0-9]+", title) if len(token) >= 4]
    if len(title_tokens) >= 2 and sum(1 for token in title_tokens if token in text) >= 2:
        return True
    return False


def goal_dependencies_for_milestone(run: dict, milestone: dict) -> list[str]:
    dependencies = run.get("knownOperatorDependencies") or []
    return [
        str(dependency)
        for dependency in dependencies
        if goal_dependency_matches_milestone(str(dependency), milestone)
    ]


def goal_instruction_with_dependencies(base: str, run: dict, milestone: dict) -> str:
    dependencies = goal_dependencies_for_milestone(run, milestone)
    if not dependencies:
        return base
    shown = dependencies[:3]
    omitted = len(dependencies) - len(shown)
    dependency_text = "; ".join(shown) + (f"; +{omitted} more" if omitted > 0 else "")
    return (
        f"{base}. Known operator-input dependency before plan finalization: {dependency_text}. "
        "If unsatisfied, defer with `goal-advance --event milestone-deferred`; block only when the dependency "
        "is confirmed unavailable or a hard true blocker before spending plan-review rounds."
    )


def goal_plan_is_multi_session(goal_path: Path) -> bool:
    text = goal_path.read_text(encoding="utf-8", errors="replace")
    return bool(
        re.search(
            r"\b(?:multi[-\s]?session|multiple sessions|multi[-\s]?day|overnight|more than one session)\b",
            text,
            re.IGNORECASE,
        )
    )


def goal_milestones_from_plan(goal_path: Path) -> list[str]:
    text = goal_path.read_text(encoding="utf-8")
    milestones = goal_plan_bullets(text)
    if not milestones:
        raise SystemExit(
            "goal plan has no ordered milestones; add a `## Milestones` section before starting the goal run"
        )
    return milestones


def goal_plan_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path.stem
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return path.stem.replace("-", " ").strip() or path.stem


def goal_percent_complete(run: dict) -> int:
    milestones = run.get("milestones", [])
    if not milestones:
        return 0
    done = sum(1 for item in milestones if item.get("status") in GOAL_TERMINAL_STATUSES)
    return int(round((done / len(milestones)) * 100))


def goal_next_action_record(run: dict) -> dict:
    if run.get("status") == "complete":
        return {
            "type": "goal_complete",
            "milestoneIndex": None,
            "milestoneTitle": None,
            "instruction": "Goal is complete; refresh continuity and session journal evidence, inspect the adapter backlog/readiness markers, then start the next source-of-truth goal or highest-priority item unless a true blocker exists.",
        }
    milestones = run.get("milestones", [])
    for milestone in milestones:
        if milestone.get("status") == "in_progress":
            return {
                "type": "continue_milestone",
                "milestoneIndex": milestone["index"],
                "milestoneTitle": milestone["title"],
                "instruction": goal_instruction_with_dependencies(
                    f"Continue milestone {milestone['index']}: {milestone['title']}",
                    run,
                    milestone,
                ),
            }
    for milestone in milestones:
        if milestone.get("status") == "pending":
            return {
                "type": "start_milestone",
                "milestoneIndex": milestone["index"],
                "milestoneTitle": milestone["title"],
                "instruction": goal_instruction_with_dependencies(
                    f"Start milestone {milestone['index']}: {milestone['title']}; create/update the source-of-truth milestone or PR plan, run Codex review/precheck, then implement.",
                    run,
                    milestone,
                ),
            }
    blocked = [milestone for milestone in milestones if milestone.get("status") == "blocked"]
    if blocked:
        milestone = blocked[0]
        blockers = "; ".join(milestone.get("blockers") or ["blocked with no reason recorded"])
        return {
            "type": "true_blocker",
            "milestoneIndex": milestone["index"],
            "milestoneTitle": milestone["title"],
            "instruction": f"True blocker on milestone {milestone['index']}: {blockers}",
        }
    return {
        "type": "ready_for_goal_completion",
        "milestoneIndex": None,
        "milestoneTitle": None,
        "instruction": "All goal milestones are terminal; run goal-advance --event goal-complete with validation proof and --iteration-review-record when iterationReview covers goal boundaries, refresh continuity, publish the session journal, and produce a boundary summary.",
    }


def goal_status_from_action(action: dict, run_status: str | None = None) -> str:
    if run_status == "complete" or action["type"] == "goal_complete":
        return "complete"
    if action["type"] == "true_blocker":
        return "blocked"
    if action["type"] == "ready_for_goal_completion":
        return "ready_for_completion"
    return "active"


def goal_run_integrity_issues(run: dict) -> list[str]:
    issues: list[str] = []
    for milestone in run.get("milestones", []):
        if milestone.get("status") == "blocked" and not milestone.get("blockers"):
            issues.append(f"milestone {milestone.get('index')} is blocked but has no blocker reason")
        if milestone.get("status") == "complete" and not (milestone.get("validationEvidence") or milestone.get("milestoneRun")):
            issues.append(f"milestone {milestone.get('index')} is complete but lacks validation evidence or linked milestone ledger")
        if milestone.get("status") == "deferred" and not (milestone.get("deferralReasons") or milestone.get("validationEvidence")):
            issues.append(f"milestone {milestone.get('index')} is deferred but lacks a deferral reason")
    if run.get("status") == "complete" and not run.get("validationProof"):
        issues.append("goal is complete but validationProof is empty")
    return issues


def goal_tracker_allowed_statuses(tracker: dict) -> list[str]:
    return (
        list(tracker["readyStatuses"])
        + list(tracker["activeStatuses"])
        + list(tracker["doneStatuses"])
        + list(tracker["blockedStatuses"])
    )


def goal_tracker_value_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ["name", "title", "text", "value", "number", "date", "id"]:
            if key in value:
                text = goal_tracker_value_text(value[key])
                if text:
                    return text
        if "option" in value:
            return goal_tracker_value_text(value["option"])
    if isinstance(value, list):
        parts = [goal_tracker_value_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    return str(value).strip()


def goal_tracker_item_title(item: dict) -> str:
    return (
        goal_tracker_value_text(item.get("title"))
        or goal_tracker_value_text((item.get("content") or {}).get("title") if isinstance(item.get("content"), dict) else "")
        or goal_tracker_value_text(item.get("id"))
        or "Untitled GitHub Project item"
    )


def goal_tracker_item_url(item: dict) -> str:
    return (
        goal_tracker_value_text(item.get("url"))
        or goal_tracker_value_text((item.get("content") or {}).get("url") if isinstance(item.get("content"), dict) else "")
    )


def goal_tracker_item_content_url(item: dict) -> str:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    return goal_tracker_value_text(content.get("url"))


def goal_tracker_item_body(item: dict) -> str:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    return (
        goal_tracker_value_text(item.get("body"))
        or goal_tracker_value_text(content.get("body"))
        or goal_tracker_value_text(content.get("bodyText"))
        or goal_tracker_value_text(item.get("description"))
    )


def goal_tracker_item_id(item: dict) -> str:
    return goal_tracker_value_text(item.get("id") or item.get("itemId") or item.get("databaseId"))


def goal_tracker_item_matches(item: dict, item_ref: str) -> bool:
    needle = item_ref.strip()
    if not needle:
        return False
    values = {
        goal_tracker_item_id(item),
        goal_tracker_item_url(item),
        goal_tracker_item_title(item),
        goal_tracker_value_text((item.get("content") or {}).get("url") if isinstance(item.get("content"), dict) else ""),
    }
    return needle in values or any(value and needle.endswith(value) for value in values)


def goal_tracker_priority_rank(value: str) -> int:
    text = value.strip().lower()
    if not text:
        return 999
    match = re.search(r"\bp\s*([0-9]+)\b", text)
    if match:
        return int(match.group(1))
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return int(float(text))
    ranks = {
        "critical": 0,
        "urgent": 0,
        "highest": 0,
        "high": 10,
        "medium": 50,
        "normal": 50,
        "low": 80,
        "lowest": 90,
    }
    return ranks.get(text, 500)


def goal_tracker_field_options(field: dict | None) -> list[dict]:
    if not field:
        return []
    options = field.get("options") or field.get("singleSelectOptions") or []
    return [option for option in options if isinstance(option, dict)]


def goal_tracker_option_by_name(field: dict, value: str) -> dict | None:
    wanted = value.strip().lower()
    for option in goal_tracker_field_options(field):
        if str(option.get("name", "")).strip().lower() == wanted:
            return option
    return None


def goal_tracker_next_sort_key(work_order: str, status_index: int, priority_rank: int, order_value: float, position: int) -> tuple:
    """Pure: 'board' work order selects by the operator's board order (an explicit numeric order
    field when configured, else the order GitHub returns the project's items), with list position
    as the stable tiebreak; 'priority' selects by ready-status group then priority tag then
    position."""
    if work_order == "board":
        return (order_value, position)
    return (status_index, priority_rank, position)


def goal_tracker_project_guidance_body(item: dict) -> str:
    body = goal_tracker_item_body(item)
    if body:
        return body.strip()
    return "No item body or guidance was returned by GitHub Projects. Add business/user guidance before treating this goal as execution-ready."


def goal_tracker_subtask_ref(item: dict) -> str:
    return (
        goal_tracker_item_id(item)
        or goal_tracker_item_content_url(item)
        or goal_tracker_item_url(item)
        or goal_tracker_item_title(item)
    )


def goal_tracker_primary_status(tracker: dict, key: str) -> str:
    values = tracker.get(key) or []
    if not values:
        raise SystemExit(f"goalTracker.{key} must contain at least one status when goalTracker is enabled")
    return str(values[0])


def goal_tracker_print_sync_result(item_ref: str, status: str, result: dict) -> None:
    print("goal_tracker_sync: ok")
    print(f"goal_tracker_sync_item_ref: {item_ref}")
    print(f"goal_tracker_sync_item_id: {result['item_id']}")
    print(f"goal_tracker_sync_status: {status}")


def goal_tracker_done_evidence_for_transition(event: str, detail: str, milestone: dict | None = None) -> str:
    if event == "goal-complete":
        return detail.strip()
    if event != "milestone-complete" or not milestone:
        return ""
    parts: list[str] = []
    detail = detail.strip()
    if detail:
        parts.append(detail)
    for value in milestone.get("validationEvidence", []) if isinstance(milestone.get("validationEvidence"), list) else []:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    milestone_run = str(milestone.get("milestoneRun") or "").strip()
    if milestone_run:
        parts.append(f"Milestone run: {milestone_run}")
    return "\n\n".join(parts).strip()


def goal_tracker_status_matches(actual: str, expected_values: list[str]) -> bool:
    return actual.strip().lower() in {value.strip().lower() for value in expected_values}


def ui_evidence_screenshot_entries(manifest: dict) -> list[dict]:
    raw = manifest.get("screenshots", manifest.get("images", []))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def ui_evidence_path_for_entry(target: Path, entry: dict) -> Path | None:
    value = str(entry.get("path") or entry.get("file") or "").strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = target / candidate
    return candidate.resolve(strict=False)
