"""Lane lifecycle leaves: the deterministic lane slot/index derivation, the lane env-file
path, the lane session-state path, the lane-coordination config accessor and the coordination
contract/board markdown templates, and the lane-start debt-preflight write wrapper. The
stateful lane verb handlers (lane_start, lane_run, lane_project, ensure_lane_state,
lane_coordination_*, work_loop, ...) stay in bin/tautline; they reach REPO_ROOT/run_git/
load_project lane state and delegate these pure leaves here."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


LANE_SESSION_FILE = "lane-session.json"


def lane_slot(target: Path) -> int:
    name = target.name.lower()
    match = re.search(r"(?:lane|lane[-_ ])(\d+)", name)
    if match:
        return max(int(match.group(1)) - 1, 0)
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()
    return 50 + (int(digest[:8], 16) % 400)


def lane_env_path(data: dict, target: Path) -> Path:
    return target / data["localResourceIsolation"]["envFile"]


def lane_session_path(data: dict, target: Path) -> Path:
    return target / data["laneState"]["runsDir"] / LANE_SESSION_FILE


def lane_coordination_config(data: dict) -> dict:
    return data["laneCoordination"]


def lane_coordination_contract_template(data: dict, target: Path) -> str:
    return (
        "# Cross-Lane Coordination Contract\n\n"
        "This tracked document is the source of truth for shared decisions across simultaneous AI development lanes. "
        "Use it to prevent lanes from inventing incompatible routes, actors, schemas, APIs, state machines, or ownership boundaries.\n\n"
        "## Shared Decisions\n\n"
        "- TBD\n\n"
        "## Ownership Boundaries\n\n"
        "- TBD\n\n"
        "## Interfaces Other Lanes Consume\n\n"
        "- TBD\n\n"
        "## Contract Change Rule\n\n"
        "If a lane discovers it needs to change something another lane owns or consumes, it must update this contract, "
        "open a small shared contract/interface PR, or explicitly take ownership and mark dependent lanes here before implementation drifts.\n\n"
        "## Open Cross-Lane Questions\n\n"
        "- TBD\n"
    )


def lane_coordination_board_template(data: dict, target: Path) -> str:
    return (
        "# Cross-Lane Lane Board\n\n"
        "This tracked board points to per-lane status files. Each lane owns its own status file under the lane status directory. "
        "Keep shared decisions in the coordination contract, not in chat or local memory.\n\n"
        "## Lane Status Files\n\n"
        "<!-- lane-status:start -->\n"
        "<!-- lane-status:end -->\n\n"
        "## Merge And Contract Notes\n\n"
        "- Land small shared contract/interface PRs before large dependent implementation PRs.\n"
        "- When a lane depends on another lane, link the provider lane status file and PR/commit here.\n"
    )


def _lane_start_hook_write(defer_debt_preflights: bool, gate: str, label: str, phrase: str, writer, *writer_args) -> None:
    """One lane-start preflight that writes durable Claude settings state and maps to a DEBT-
    classified methodology-status gate (`hook` for the Claude *-hook settings writes, `autocompact`
    for the autocompact settings write -- see METHODOLOGY_STATUS_GATE_DISPLAY_NAMES). `writer(*writer_args)`
    performs the write and returns `(path, unchanged)`; the success line ("already <phrase>" vs
    "installed") prints identically whether or not --defer-debt-preflights is set.

    Without the flag this calls the write with no try/except, so an uncaught write failure
    propagates exactly as it did on the pre-0.8.9 baseline (characterization pin: unflagged
    lane-start is byte-for-byte unchanged). With the flag, a write failure degrades to one
    `lane_start_warn:` line instead of crashing lane-start, deferring the pass/fail decision to
    methodology-status --fail-on-drift's own classification of the gate.
    """

    def _write_and_print() -> None:
        path, unchanged = writer(*writer_args)
        print(f"{label}: {'already ' + phrase if unchanged else 'installed'} {path}")

    if not defer_debt_preflights:
        _write_and_print()
        return
    try:
        _write_and_print()
    except (OSError, json.JSONDecodeError) as exc:
        # json.JSONDecodeError: load_claude_settings raises it for an existing-but-malformed
        # settings.json -- same debt family as an OSError write failure (Codex T7 R1 P2).
        print(f"lane_start_warn: {gate} - {exc}")
