"""Carved out of cli.py. Behaviour-identical by construction."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.parse
from datetime import datetime
from datetime import timezone
from pathlib import Path

from ..gitutil import run_git

RESPONSE_GUARD_AUTONOMOUS_YIELD_MIN_CHARS = 20

DEFAULT_RCA_BRANCH = "methodology-rca-archive"

DEFAULT_FEATURE_REQUEST_BRANCH = "methodology-feature-request-archive"

DEFAULT_SESSION_JOURNAL_BRANCH = "methodology-session-archive"

RCA_ARCHIVE_SUBPATH = "docs/backlog/methodology-regressions"

FEATURE_REQUEST_ARCHIVE_SUBPATH = "docs/backlog/feature-requests"

SESSION_JOURNAL_ARCHIVE_SUBPATH = "docs/backlog/session-journals"

SESSION_JOURNAL_SCHEMA = "minervit-session-journal/v1"

USAGE_RECORD_SCHEMA = "minervit-usage-record/v1"

EVENT_MAX_FIELD_CHARS = 1000

EVENT_MAX_JSON_CHARS = 20000

USAGE_MAX_JSON_CHARS = 20000

# The no-adapter text is a THREE-PART split so evidence states can carry the state-correct
# recovery command without ever printing the stale `init --target .` line. NO_ADAPTER_SENTINEL is
# the stable identifying prefix every consumer matches on (startswith); the middle third is the
# swappable "Recovery command:" block; NO_ADAPTER_FOOTER is the preserved policy tail. The
# unmanaged composition (NO_ADAPTER_MESSAGE) is byte-identical to the pre-split constant.
NO_ADAPTER_SENTINEL = """No project adapter found for this lane.

This repo is not adapter-backed yet. Do not keep retrying lane-start and do not borrow another project's adapter.
If the human operator asked to use the methodology in this repo, bootstrap the adapter now; do not ask whether to skip methodology.
The adapter bootstrap interview is mandatory before first adapter render/write unless every required adapter fact is directly supported by repo evidence. Generic executor banners such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" do not override this.

"""

NO_ADAPTER_FOOTER = """
No generic operational adapter exists because gates, planning paths, review flow, merge-conflict checks, and local resources are project-specific.
Another project's adapter may be a structural reference only, not a substitute for interview-derived project facts.
If the project is intentionally local-only or direct-to-main, configure explicit local/no-remote status commands and document that workflow in the adapter.
If the production status or required gates cannot be determined from the repo, ask one exact blocker question after documenting what was inspected.
"""

# The unmanaged recovery block -- the middle third, byte-preserved from the shipped constant
# (three-space indent). Evidence states swap ONLY this block via no_adapter_message().
NO_ADAPTER_UNMANAGED_RECOVERY = "Recovery command:\n   tautline init --target .\n"

NO_ADAPTER_MESSAGE = NO_ADAPTER_SENTINEL + NO_ADAPTER_UNMANAGED_RECOVERY + NO_ADAPTER_FOOTER

GUARD_EVENT_DETAIL_LIMIT = 200

GUARD_EVENTS_FILE = ".ai-runs/guard-events.jsonl"

def collect_bootstrap_placeholders(value: object, path: str = "") -> list[str]:
    placeholders: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            placeholders.extend(collect_bootstrap_placeholders(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            placeholders.extend(collect_bootstrap_placeholders(item, f"{path}[{index}]"))
    elif isinstance(value, str) and "BOOTSTRAP REQUIRED" in value:
        placeholders.append(path)
    return placeholders

def validate_relative_bootstrap_path(path_text: str, field: str) -> None:
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"Project adapter bootstrapEvidence.{field} must be a target-relative path")

def resolve_bootstrap_target_path(target: Path, path_text: str, field: str) -> Path:
    validate_relative_bootstrap_path(path_text, field)
    target_root = target.resolve()
    candidate = target / path_text
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise
    try:
        resolved.relative_to(target_root)
    except ValueError as exc:
        raise SystemExit(
            f"Project adapter bootstrapEvidence.{field} must resolve inside the target repo: {path_text}"
        ) from exc
    return resolved

def extract_bootstrap_header(text: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None

def validate_render_adapter_provenance(data: dict, project_path: Path) -> None:
    if data.get("_generated"):
        return
    if data.get("bootstrapEvidence") is None:
        raise SystemExit(
            "render-adapters requires project adapter bootstrapEvidence. Do not render from ad hoc, copied, "
            "or lane-local adapter JSON without interview or repo-evidence provenance."
        )

def normalize_profile_path(path_text: str, source: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        raise SystemExit(f"{source} must be non-blank")
    path = Path(value)
    if path.is_absolute() or value == ".." or value.startswith("../") or "/../" in value:
        raise SystemExit(f"{source} must be project-relative, not absolute or parent-relative")
    return value

def normalize_profile_string_list(raw: object, source: str, *, extensions: bool = False) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SystemExit(f"{source} must be an array")
    values: list[str] = []
    for index, item in enumerate(raw):
        value = str(item or "").strip()
        if not value:
            raise SystemExit(f"{source}[{index}] must be non-blank")
        if extensions:
            value = value.lower()
            if not value.startswith("."):
                raise SystemExit(f"{source}[{index}] must start with a dot")
        elif value.startswith("/") or value == ".." or value.startswith("../") or "/../" in value:
            raise SystemExit(f"{source}[{index}] must be project-relative, not absolute or parent-relative")
        values.append(value)
    return [value for value in dict.fromkeys(values) if value]

def framework_pin_status_line(pin: dict, source: str) -> str:
    version = pin["version"] or "unversioned-current"
    return (
        "framework_pin: "
        f"channel={pin['channel']} version={version} updatePolicy={pin['updatePolicy']} "
        f"migrationPolicy={pin['migrationPolicy']} source={source}"
    )

def active_json_status(path: Path, complete_statuses: set[str]) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, "present"
    if not isinstance(payload, dict):
        return True, "present"
    status = str(payload.get("status") or "").strip().lower()
    if status and status in complete_statuses:
        return False, status
    return True, status or "present"

def _update_probe_result(
    available_version: str | None,
    available_sha: str | None,
    change_kind: str,
    is_newer: bool,
    source: str,
    failure_detail: str | None,
    probed_at: str,
) -> dict:
    return {
        "availableVersion": available_version,
        "availableSha": available_sha,
        "changeKind": change_kind,
        "isNewer": is_newer,
        "source": source,
        "failureDetail": failure_detail,
        "probedAt": probed_at,
    }

def _update_probe_parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _framework_update_reason_is_wip_hold(reason: str) -> bool:
    """True for the decision's OWN active-work skip reasons -- the untouched decision emits these
    only when a pin/env-supplied version is a genuine minor/major/patch upgrade held by live work.
    A manual-policy hold is NOT a WIP hold even with wipReasons present (manual sync proceeds)."""
    return (
        reason.startswith("active work blocks automatic")
        or reason == (
            "active work allows patch auto-update only when the release migration report "
            "declares wipSafe=true"
        )
        or reason == (
            "minor-at-boundary update waits until no goal, milestone, packet, review, or "
            "branch work is active"
        )
    )

def scope_query_filters_status(scope_query: str, status_field: str) -> bool:
    """Pure: does a GitHub Projects scopeQuery filter on the status field? A status predicate would
    hide an item parked in an unconfigured/review status from board-currency reconciliation, so it
    is forbidden. Catches `status:`, `-status:`, and the existence qualifiers `has:status`/`no:status`
    (GitHub Projects filter syntax), matching the exact configured field name as a whole top-level
    qualifier -- not a substring, so `mystatus:`/`custom-status:`/`label:"status:x"` are NOT flagged.
    Values inside quotes are ignored so a status-like string in another qualifier's value is safe."""
    field = (status_field or "").strip().lower()
    if not field or not (scope_query or "").strip():
        return False
    unquoted = re.sub(r"\"[^\"]*\"", " ", scope_query)
    unquoted = re.sub(r"'[^']*'", " ", unquoted)
    for raw_token in unquoted.split():
        token = raw_token.lower().lstrip("-")
        if token.startswith(field + ":") or token in (f"has:{field}", f"no:{field}"):
            return True
    return False

def normalize_tracker_adapter_config(raw: object, defaults: dict, label: str) -> dict:
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit(f"Project adapter {label} must be an object")
    config = {**defaults, **(raw or {})}
    if not isinstance(config.get("enabled"), bool):
        raise SystemExit(f"Project adapter {label}.enabled must be boolean")
    if config.get("provider") != "github-projects":
        raise SystemExit(f"Project adapter {label}.provider must be github-projects")
    try:
        config["projectNumber"] = int(config.get("projectNumber", 0))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Project adapter {label}.projectNumber must be an integer") from exc
    for key in ["owner", "scopeQuery", "statusField", "priorityField", "milestoneField", "linkPolicy"]:
        config[key] = str(config.get(key, "")).strip()
    # planRepo is a backlogProvider-only key, and this normalizer is shared with the deprecated
    # goalTracker block. Keying on the defaults rather than adding it to the list above keeps it
    # out of goalTracker, which has no plan root and would otherwise render a meaningless key
    # into every adapter still carrying that block.
    if "planRepo" in defaults:
        config["planRepo"] = str(config.get("planRepo") or "").strip()
    # A status predicate in scopeQuery would hide an item parked in an unconfigured/review status
    # from board-currency reconciliation (the gate only scans the scoped set), letting a lane evade
    # the no-review-column enforcement by scoping. Forbid it (Codex P2).
    if scope_query_filters_status(config["scopeQuery"], config["statusField"]):
        raise SystemExit(
            f"Project adapter {label}.scopeQuery must not filter on the status field "
            f"({config['statusField']!r}); board currency must see every in-scope item regardless of status"
        )
    for optional_key in [
        "typeField",
        "tacticalPlanningAuthority",
        "syncMode",
        "migrationInterviewPath",
        "exportMode",
        "completionUnit",
        "epicField",
        "orderField",
    ]:
        if optional_key in config:
            config[optional_key] = str(config.get(optional_key, "")).strip()
    # Board physical ordering defines the exact work order by default; 'priority' opts out.
    work_order = str(config.get("workOrder", "board") or "board").strip().lower()
    if work_order not in {"board", "priority"}:
        raise SystemExit(f"Project adapter {label}.workOrder must be 'board' or 'priority'")
    config["workOrder"] = work_order
    for key in ["readyStatuses", "activeStatuses", "doneStatuses", "blockedStatuses", "authoritativeFor"]:
        values = config.get(key, [])
        if not isinstance(values, list) or any(not str(item).strip() for item in values):
            raise SystemExit(f"Project adapter {label}.{key} must be an array of non-blank strings")
        config[key] = [str(item).strip() for item in values]
    if "itemTypes" in config:
        values = config.get("itemTypes", [])
        if not isinstance(values, list) or any(str(item).strip() not in {"goal", "milestone", "bug", "task"} for item in values):
            raise SystemExit(f"Project adapter {label}.itemTypes must contain only goal, milestone, bug, and/or task")
        config["itemTypes"] = [str(item).strip() for item in values]
    if not isinstance(config.get("repoPlanRequired"), bool):
        raise SystemExit(f"Project adapter {label}.repoPlanRequired must be boolean")
    if "tacticalPlanningAuthority" in config and config["tacticalPlanningAuthority"] != "repo":
        raise SystemExit(f"Project adapter {label}.tacticalPlanningAuthority must be repo")
    if "syncMode" in config and config["syncMode"] != "read-select-write-status-links-notes":
        raise SystemExit(f"Project adapter {label}.syncMode must be read-select-write-status-links-notes")
    if "exportMode" in config and config["exportMode"] != "interview-approved":
        raise SystemExit(f"Project adapter {label}.exportMode must be interview-approved")
    if "completionUnit" in config:
        completion_unit = str(config.get("completionUnit") or "goal").strip().lower()
        if completion_unit not in {"goal", "provider-item"}:
            raise SystemExit(f"Project adapter {label}.completionUnit must be goal or provider-item")
        config["completionUnit"] = completion_unit
    if "migrationInterviewPath" in config:
        if not config["migrationInterviewPath"]:
            raise SystemExit(f"Project adapter {label}.migrationInterviewPath must be non-blank")
        if Path(config["migrationInterviewPath"]).is_absolute():
            raise SystemExit(f"Project adapter {label}.migrationInterviewPath must be project-relative, not an absolute machine path")
    # featureSeries is a DICT {field, pattern}; type-check it in its own block (mirroring ciTestGate)
    # so the str()-coercion optional-key loop above never stringifies and corrupts the dict.
    if "featureSeries" in config:
        feature_series = config["featureSeries"]
        if not isinstance(feature_series, dict):
            raise SystemExit(f"Project adapter {label}.featureSeries must be an object")
        for member_key in ["field", "pattern"]:
            if member_key in feature_series and not isinstance(feature_series[member_key], str):
                raise SystemExit(f"Project adapter {label}.featureSeries.{member_key} must be a string")
        config["featureSeries"] = feature_series
    if config["enabled"]:
        if not config["owner"]:
            raise SystemExit(f"Project adapter {label}.owner must be non-blank when enabled")
        if config["projectNumber"] < 1:
            raise SystemExit(f"Project adapter {label}.projectNumber must be positive when enabled")
        if not config["statusField"]:
            raise SystemExit(f"Project adapter {label}.statusField must be non-blank when enabled")
        # blockedStatuses is intentionally NOT required-non-empty: a board may legitimately have no
        # "Blocked" column (the canonical Funnel/Todo/In progress/Done shape), so adopting it yields
        # an empty blockedStatuses. Requiring it here would make board-adopt write a self-
        # invalidating adapter that bricks every later load_project.
        for key in ["readyStatuses", "activeStatuses", "doneStatuses"]:
            if not config[key]:
                raise SystemExit(f"Project adapter {label}.{key} must be non-empty when enabled")
        if not config["authoritativeFor"]:
            raise SystemExit(f"Project adapter {label}.authoritativeFor must be non-empty when enabled")
        if not config["repoPlanRequired"]:
            raise SystemExit(f"Project adapter {label}.repoPlanRequired must be true when enabled")
        if not config["linkPolicy"]:
            raise SystemExit(f"Project adapter {label}.linkPolicy must be non-blank when enabled")
        if "itemTypes" in config and not config["itemTypes"]:
            raise SystemExit(f"Project adapter {label}.itemTypes must be non-empty when enabled")
        if config.get("workOrder") == "priority" and not config["priorityField"]:
            raise SystemExit(f"Project adapter {label}.priorityField must be set when workOrder is 'priority'")
    return config

def command_needs_lane_run(command: str, isolated_commands: list[str]) -> bool:
    try:
        command_parts = set(shlex.split(command))
    except ValueError:
        command_parts = set(command.split())
    for isolated in isolated_commands:
        if command == isolated:
            return True
        try:
            isolated_parts = shlex.split(isolated)
        except ValueError:
            isolated_parts = isolated.split()
        if isolated_parts and all(part in command_parts for part in isolated_parts):
            return True
    return False

def instrumentation_guidance_line(instrumentation: dict) -> str:
    """The rendered `## Session Signal` instrumentation line. Boundary-publish guidance is gated on
    the effective config: a disabled/default lane is never told to run publish-instrumentation-record
    (which refuses while disabled), and an enabled `cadence: off` lane is told to publish MANUALLY
    with no boundary prompt (its defined behavior) rather than "at the off boundary"."""
    if not instrumentation["enabled"]:
        return (
            "- Instrumentation (`false`): sanitized, zero-product-data upstream signal; disabled here, "
            "opt in with `instrumentation.enabled` (do not run `publish-instrumentation-record` until "
            "then -- it refuses while disabled).\n"
        )
    cadence = instrumentation["cadence"]
    if cadence == "off":
        return (
            "- Instrumentation (`true`, cadence `off`): sanitized, zero-product-data record; publish "
            "MANUALLY with `publish-instrumentation-record` (no boundary prompting).\n"
        )
    return (
        f"- Instrumentation (`true`, cadence `{cadence}`): sanitized, zero-product-data record; "
        f"contribute upstream at the `{cadence}` boundary with `publish-instrumentation-record`.\n"
    )

ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT = (
    "adapter was rendered by a different methodology build; align versions "
    "(pip install -U tautline / update-repin) before re-rendering"
)

def scaffold_test_harness_files(project_slug: str) -> dict[str, str]:
    """Day-one self-proving test harness (rec #10): a NEW repo's first commit ships a runner, a real CI
    workflow (no continue-on-error) that runs tests on push/PR, a passing smoke, and a written procedure
    to prove the gate can actually go RED on a CI run. project_scaffold sets ciTestGate.enforcement=block
    so this harness is required from commit one (exactly the private-product greenfield window)."""
    ci = (
        "# Generated by tautline (rec #10 day-one harness). The coverage/test step must NOT\n"
        "# use continue-on-error -- a failing test has to fail the job (no FM1/FM3 anti-pattern).\n"
        "name: ci\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: run tests\n"
        "        run: bash scripts/test.sh\n"
    )
    runner = (
        "#!/usr/bin/env bash\n"
        "# Generated by tautline (rec #10). Replace the smoke with the real suite, but keep\n"
        "# set -euo pipefail so a failing test exits non-zero and fails CI.\n"
        "set -euo pipefail\n"
        "\n"
        "echo '==> day-one smoke (replace with the real test command, e.g. pytest / npm test)'\n"
        "bash tests/smoke_test.sh\n"
        "\n"
        "# BOOTSTRAP REQUIRED: add the project test command below, e.g.:\n"
        "#   pytest -q --cov --cov-config=.coveragerc\n"
        "#   npm test\n"
    )
    smoke = (
        "#!/usr/bin/env bash\n"
        "# A trivially-true smoke so CI is green from commit one. Prove the gate BITES via\n"
        "# docs/quality/gate-self-proof.md before trusting it.\n"
        "set -euo pipefail\n"
        "test \"1\" = \"1\"\n"
        "echo 'smoke ok'\n"
    )
    self_proof = (
        "# Gate self-proof (rec #10): prove the test gate can go RED\n\n"
        f"Project: {project_slug}\n\n"
        "A green pipeline only proves the gate works if you have seen it go red on a real CI run.\n"
        "Do this once at setup, and any time the CI changes:\n\n"
        "1. On a throwaway branch, add a deliberately failing test (e.g. `test \"1\" = \"2\"` in\n"
        "   `tests/smoke_test.sh`).\n"
        "2. Push and open a PR. Poll the run on that exact SHA:\n"
        "   `gh run list --branch <branch> --json headSha,conclusion,status`.\n"
        "3. Confirm the required check **concluded `failure`** on that SHA -- not `cancelled`, not\n"
        "   skipped. That is the proof the gate bites.\n"
        "4. Revert the failing test. The gate is now trusted.\n\n"
        "Until step 3 has been observed, treat the gate as unproven (P1 provability theater).\n"
    )
    return {
        ".github/workflows/ci.yml": ci,
        "scripts/test.sh": runner,
        "tests/smoke_test.sh": smoke,
        "docs/quality/gate-self-proof.md": self_proof,
    }

def protected_markdown_message(paths: list[Path]) -> str:
    protected = ", ".join(str(path) for path in paths)
    return (
        "refusing to overwrite non-generated adapter markdown: "
        f"{protected}. Use `render-adapters --write --json-only` for lane JSON/config-only updates. "
        "For a full migration, first move hand-written instructions into the canonical project adapter "
        "or other source-of-truth docs, then remove/rename the hand-written Markdown and render generated files."
    )

# Domains a compatibility render may omit. Deliberately a closed set: this exists to produce a
# generated adapter an OLDER CLI can load during a downgrade, not as a general escape hatch for
# dropping configuration.
RENDER_OMITTABLE_DOMAINS: tuple[str, ...] = ("laneStatus",)

def load_adapter_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"adapter not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"adapter is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"adapter must be a JSON object: {path}")
    return payload

# Compat-sunset (roadmap #16): the concrete legacy MINERVIT_ env NAMES the warn stage lights up,
# across the Python resolve_env chokepoint AND the shell session launcher. Enumerated (never a
# family-level entry) so each becomes its own removeAfter:1.0.0 deprecatedSurfaces line the removal
# plan attests per surface. Sorted for a deterministic migration report. The four
# EXEMPT_DIRECT_READS process-private handoff envs and MINERVIT_METHODOLOGY_MAINTAINER_MODE (a
# config-file read, TAUTLINE_-first, not a resolve_env chokepoint) are deliberately absent.
SUNSET_WARNED_ENV_NAMES = (
    "MINERVIT_CLAUDE_AUTOCOMPACT_PCT",
    "MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED",
    "MINERVIT_GITHUB_CACHE_DIR",
    "MINERVIT_GITHUB_CACHE_READ_MODE",
    "MINERVIT_GITHUB_CACHE_TTL_SECONDS",
    "MINERVIT_GITHUB_COALESCE",
    "MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK",
    "MINERVIT_GITHUB_LOCK_STALE_SECONDS",
    "MINERVIT_GITHUB_LOCK_TIMEOUT_SECONDS",
    "MINERVIT_GITHUB_RATE_GUARD",
    "MINERVIT_GITHUB_RETRY_MAX_SECONDS",
    "MINERVIT_GITHUB_RETRY_MIN_SECONDS",
    "MINERVIT_GITHUB_SERIALIZE",
    "MINERVIT_GITHUB_SHARED_SNAPSHOT_SECONDS",
    "MINERVIT_GITHUB_TELEMETRY_DIR",
    "MINERVIT_LANE_EPICS",
    "MINERVIT_METHODOLOGY_ADAPTER_ROOT",
    "MINERVIT_METHODOLOGY_ALLOW_FANOUT",
    "MINERVIT_METHODOLOGY_ALLOW_NON_MAIN",
    "MINERVIT_METHODOLOGY_AVAILABLE_VERSION",
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_CLI",
    "MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE",
    "MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    "MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK",
    "MINERVIT_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_RESCUE_STATE_DIR",
    "MINERVIT_METHODOLOGY_SNAPSHOT_KEEP",
    "MINERVIT_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "MINERVIT_METHODOLOGY_TELEMETRY",
    "MINERVIT_METHODOLOGY_TELEMETRY_PATH",
    "MINERVIT_METHODOLOGY_UPDATE_PINS",
    "MINERVIT_METHODOLOGY_UPDATE_POLICY",
    "MINERVIT_METHODOLOGY_UPDATE_PROBE",
    "MINERVIT_METHODOLOGY_UPDATE_SIGNERS",
    "MINERVIT_NO_REPAIR_SESSION",
    "MINERVIT_PREPUSH_RECORDS_FILE",
    "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS",
    "MINERVIT_REAL_CODEX",
    "MINERVIT_RENDERER_KIT_STATE_DIR",
    "MINERVIT_SHOW_GOAL_PROMPT",
)

def gh_api(path: str) -> dict:
    proc = subprocess.run(
        ["gh", "api", path],
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(proc.stdout)

def gh_api_opt(path: str) -> dict | None:
    """gh_api that returns None instead of raising -- for endpoints that legitimately 404/403 (e.g.
    branch protection on an unprotected branch, or without admin scope)."""
    try:
        return gh_api(path)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None

def branch_protection_issues(protection: dict | None, required_checks: list[str]) -> list[str]:
    """Detection baseline (rec #9, P5): a customer-facing main must enforce green required checks and
    re-run them on stale branches (strict). No protection => CI checks are advisory, exactly the #448
    'no branch protection on main' gap."""
    if not protection:
        return ["branch protection is absent on the default branch: required CI checks are advisory, not enforced (P5)"]
    issues: list[str] = []
    rsc = protection.get("required_status_checks")
    if not rsc:
        issues.append("branch protection declares no required_status_checks: a red check cannot block merge")
        return issues
    if not rsc.get("strict", False):
        issues.append("branch protection required_status_checks.strict is false: a stale branch can merge without re-running checks")
    contexts: set[str] = {str(c) for c in (rsc.get("contexts") or [])}
    for check in rsc.get("checks") or []:
        if isinstance(check, dict) and check.get("context"):
            contexts.add(str(check["context"]))
    missing = [c for c in required_checks if c not in contexts]
    if missing:
        issues.append(f"branch protection is missing required checks: {', '.join(missing)}")
    return issues

def canary_conclusion_issue(runs: list[dict], canary_name: str, sha: str) -> str | None:
    """The synthetic canary's LAST conclusion must be success ON THE DEPLOYED SHA -- an outcome signal,
    not just that a canary workflow exists. actions/runs returns newest first."""
    if not canary_name:
        return None
    target = canary_name.strip().lower()
    short = sha[:12]
    candidates = [
        run for run in runs
        if str(run.get("name", "")).strip().lower() == target
        and (str(run.get("head_sha", "")) == sha or str(run.get("head_sha", "")).startswith(short))
    ]
    if not candidates:
        return f"synthetic canary '{canary_name}' has no run on the deployed SHA {short}: detection is unproven on what shipped"
    conclusion = str(candidates[0].get("conclusion"))
    if conclusion != "success":
        return f"synthetic canary '{canary_name}' last conclusion on {short} is {conclusion}, not success"
    return None

def process_identity(pid: int) -> str | None:
    if pid < 1:
        return None
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return " ".join(proc.stdout.split())

def count_live_background_runs(log_dir: Path) -> int:
    """Count minervit background runs still alive in a log dir (by their .pid files).

    Used by the fan-out runaway guard. A stale .pid (dead process) is not counted.
    """
    if not log_dir.is_dir():
        return 0
    live = 0
    for pid_file in log_dir.glob("*.pid"):
        if pid_file.name.endswith(".watchdog.pid"):
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        try:
            os.kill(pid, 0)  # signal 0: liveness probe, sends nothing
        except OSError:
            continue
        live += 1
    return live

def pid_is_live(pid: int) -> bool:
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False

def read_pid_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        pid = int(text.splitlines()[0].strip())
    except ValueError:
        return None
    return pid if pid > 0 else None

# --- PM-surface classifier: STATIC hard-exclusion set (Design 3) --------------------------------
# Authoritative even against a broad adapter glob. Directory ROOTS (a path is excluded when it is
# at or under any of these). Everything under docs/ EXCEPT the allowlisted docs/product/ is a
# framework doc root and is excluded. `plugins/` covers every plugin manifest; the adapter/config
# roots (`.tautline/`, `.minervit/`, `adapters/projects/`) cover current + legacy surface config.
HARD_EXCLUDED_ROOTS = (
    "bin",
    "src",
    "tests",
    "scripts",
    "methodology",
    "plugins",
    ".github",
    "docs/superpowers",
    "docs/releases",
    "docs/backlog",
    "docs/governance",
    "docs/productization",
    "docs/reference",
    "docs/assets",
    "adapters/projects",
    ".tautline",
    ".minervit",
    ".agents",
    ".claude-plugin",
)

# One representative path per hard-excluded root, used by the loader (Design 1 rule B) as a
# defense-in-depth backstop behind the symbolic overlap check. Derived from the STATIC roots/files
# above so the loader's rejection surface cannot drift from the classifier's exclusion surface.
HARD_EXCLUSION_SENTINELS = (
    "bin/tautline",
    "src/tautline_methodology/adapter.py",
    "tests/test_pm_surface_classifier.py",
    "scripts/test.sh",
    "methodology/adapter-schema.json",
    "plugins/tautline-core/.claude-plugin/plugin.json",
    ".github/workflows/ci.yml",
    "docs/superpowers/plans/plan.md",
    "docs/releases/release.md",
    "docs/backlog/item.md",
    "docs/governance/policy.md",
    "docs/productization/plan.md",
    "docs/reference/guide.md",
    "docs/assets/logo.png",
    # Product-neutral representative under the adapters/projects/ hard-excluded root: a
    # real, sanctioned path (see PUBLIC_RELEASE_PRIVATE_ADAPTER_PATH_RE) that carries no
    # example-product name, so this generic surface stays free of project-specific refs.
    "adapters/projects/.bootstrap-legacy-allowlist.json",
    ".tautline/adapter.json",
    ".minervit/adapter.json",
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
)

def public_contract_status_for_adapter_key(name: str, schema: dict) -> dict:
    if name == "goalTracker":
        return {"status": "deprecated", "replacement": "backlogProvider", "removeAfter": "1.0.0"}
    if name == "_generated":
        return {"status": "internal"}
    if name == "responseGuard":
        return {"status": "internal"}
    if name == "_framework":
        return {"status": "stable"}
    if name == "instrumentation":
        # 0.9.0: sanitized-instrumentation adapter key introduced as experimental alongside its
        # experimental CLI commands; the record schema/vocabulary is a reviewed public surface.
        return {"status": "experimental"}
    prop = (schema.get("properties") or {}).get(name) or {}
    if isinstance(prop, dict) and prop.get("deprecated") is True:
        return {"status": "deprecated"}
    return {"status": "stable"}

def public_contract_status_for_skill(name: str, rel: str) -> dict:
    if rel.startswith("examples/") or rel == "examples":
        return {"status": "experimental"}
    # makerkit-implementation moved to examples/community-skills/ (structure: move
    # stack-specific makerkit example out of core plugin) and is no longer scanned
    # under either plugin's skills/ root, so its status special-case is retired.
    if name in {"rules-audit"}:
        return {
            "status": "deprecated",
            "replacement": "framework-intake",
            "removeAfter": "1.0.0",
        }
    return {"status": "stable"}

# T1 (0.9.0 sanitized instrumentation): the operator-approved v1 event vocabulary (T0, sha256
# fe966b2a...). A TUPLE, not a list -- an UPPER_CASE list-of-str constant would auto-enter the
# policy-phrases SSOT (policy_phrase_constants() above) and break test_policy_phrases_ssot.py. This
# is the single source of truth: the generated schema's `events[].code` enum and the validator both
# derive from it, so an enum edit here is the ONLY place a new event code can be introduced.
INSTRUMENTATION_EVENT_CODES: tuple[str, ...] = (
    "startup",
    "preflight",
    "planning_review_gate",
    "plan_review_round",
    "plan_review_clean",
    "plan_review_blocked",
    "implementation_review_round",
    "implementation_review_clean",
    "implementation_review_blocked",
    "gate_block",
    "autonomy_stop",
    "human_question",
    "blocker_declared",
    "blocker_cleared",
    "rca",
    "continuity_written",
    "context_rotation",
    "goal_transition",
    "milestone_transition",
    "pr_opened",
    "pr_queue_merge",
    "pr_merged",
    "ci_wait",
    "merge_queue_wait",
    "task_started",
    "task_completed",
    "session_end",
)

INSTRUMENTATION_SCHEMA_VERSION = "tautline-instrumentation/v1"

# UTC-only RFC3339, e.g. "2026-07-10T12:00:00+00:00" or with fractional seconds. Pattern-
# constrained in the schema itself (not JSON-Schema "format", which consumers may not assert) and
# deliberately rejects any non-"+00:00" offset -- the record is always emitted in UTC.
INSTRUMENTATION_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$"

INSTRUMENTATION_LANE_ID_PATTERN = r"^[0-9a-f]{16}$"

INSTRUMENTATION_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"

def instrumentation_schema_dict() -> dict:
    """The in-code field rules (single source of truth) for `tautline-instrumentation/v1`.

    `methodology/instrumentation-schema.json` (dump-instrumentation-schema) and
    instrumentation_record_errors() both derive from this ONE dict via the stdlib-only
    schema_validation_errors() engine (the same engine the adapter schema already uses), so the
    committed schema artifact and the validator's behavior cannot drift by construction. The
    additionalProperties:false at every object level plus const/enum/pattern on every string
    property is what gives the schema its no-freeform-capacity property; the cross-field rule
    (window_gap:false requires at least one event) is expressed here as if/then so it's enforced by
    the same single definition rather than as separate hand-written logic.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "emitted_at",
            "lane_id",
            "plugin_version",
            "window_seconds",
            "window_gap",
            "end_seq",
            "events",
        ],
        "properties": {
            "schema": {"type": "string", "const": INSTRUMENTATION_SCHEMA_VERSION},
            "emitted_at": {"type": "string", "pattern": INSTRUMENTATION_TIMESTAMP_PATTERN},
            "lane_id": {"type": "string", "pattern": INSTRUMENTATION_LANE_ID_PATTERN},
            "plugin_version": {"type": "string", "pattern": INSTRUMENTATION_VERSION_PATTERN},
            "window_seconds": {"type": "number", "minimum": 0},
            "window_gap": {"type": "boolean"},
            "end_seq": {"type": "integer", "minimum": 0},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "count"],
                    "properties": {
                        "code": {"type": "string", "enum": list(INSTRUMENTATION_EVENT_CODES)},
                        "count": {"type": "integer", "minimum": 1},
                        "total_seconds": {"type": "number", "minimum": 0},
                        "ordinal": {"type": "integer", "minimum": 0},
                        "round": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        # Cross-field rule: a non-gap record (window_gap: false) must contain at least one event.
        # An empty `events` is reserved for gap records -- otherwise a forged empty non-gap blob
        # with a high bound end_seq could pass hygiene and suppress local events with no gap
        # indication (see the plan's Record schema section).
        "if": {"properties": {"window_gap": {"const": False}}},
        "then": {"properties": {"events": {"minItems": 1}}},
    }

def render_instrumentation_schema() -> str:
    return json.dumps(instrumentation_schema_dict(), indent=2, sort_keys=True) + "\n"

def _json_pairs_reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """`json.loads(object_pairs_hook=...)` callback that raises ValueError on a repeated object key
    instead of silently keeping the last value (the duplicate-key smuggling representation)."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result

# T2 (0.9.0 sanitized instrumentation): telemetry salt + lane_id + per-lane monotonic seq. The
# salt is a machine secret ($HOME/.local/state/tautline/telemetry-salt, 0600, create-on-first-use)
# that must NEVER be published or logged; lane_id = sha256(salt + resolved lane path).hexdigest()
# [:16] is the only lane discriminator added to the local event log, replacing the previous
# basename-only `lane` field that collides across parallel worktrees sharing a directory name. The
# per-lane seq counter is persisted BESIDE THE SALT (not beside the event log, which two
# same-repo worktrees can share) and is allocated INSIDE the same advisory flock
# append_event_payload() already takes around the event log's rotate+append, so two simultaneous
# try_write_event calls for the same lane can never duplicate or skip a seq. The counter's
# persisted state also carries the high-water timestamp of the last allocated event -- the
# deterministic source T3's aggregator will use for a complete-loss gap record's emitted_at/
# filename stamp when no mapped event survives to derive it from.
def telemetry_state_dir() -> Path:
    return Path.home() / ".local" / "state" / "tautline"

def telemetry_salt_path() -> Path:
    return telemetry_state_dir() / "telemetry-salt"

def telemetry_salt() -> bytes:
    """32 random bytes, created on first use at telemetry_salt_path() (0600) and never rotated.

    Creation uses O_CREAT|O_EXCL (never replace): if two processes hit first-use simultaneously,
    exactly one creates the file and the loser reads the winner's salt, so every caller on the
    machine converges on ONE salt (a replace-based write would let the loser keep a salt that no
    longer exists on disk, silently forking that lane's lane_id). The fd is opened 0600 at
    creation, so the secret is never even briefly readable by group/other."""
    path = telemetry_salt_path()
    for _attempt in range(2):
        try:
            existing = path.read_bytes()
        except FileNotFoundError:
            existing = b""
        if len(existing) == 32:
            return existing
        if existing:
            # Corrupt/truncated salt (crash mid-first-write): discard and recreate. lane_ids
            # derived from a corrupt salt were never valid, so regeneration is safe recovery.
            try:
                path.unlink()
            except OSError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue  # another process won the create race; loop back and read its salt
        with os.fdopen(fd, "wb") as handle:
            handle.write(os.urandom(32))
        return path.read_bytes()
    raise SystemExit(f"could not create or read telemetry salt: {path}")

def instrumentation_seq_state_path(lane_id: str) -> Path:
    return telemetry_state_dir() / "lane-seq" / f"{lane_id}.json"

def read_instrumentation_seq_state(lane_id: str) -> dict:
    """{"seq": <highest allocated seq for this lane, 0 if none>, "high_water_ts": <str|None>}."""
    path = instrumentation_seq_state_path(lane_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = None
    if not isinstance(raw, dict):
        return {"seq": 0, "high_water_ts": None}
    try:
        seq = max(int(raw.get("seq", 0)), 0)
    except (TypeError, ValueError):
        seq = 0
    high_water_ts = raw.get("high_water_ts")
    if not isinstance(high_water_ts, str) or not high_water_ts:
        high_water_ts = None
    return {"seq": seq, "high_water_ts": high_water_ts}

# (start_name, finished_name, failed_name, code): the reducer opens a unit on `start_name` and
# closes it on either terminal name, contributing total_seconds = terminal_ts - start_ts. An
# unpaired start (crash mid-round, or a second start before any terminal event) counts once with no
# duration.
INSTRUMENTATION_PAIRED_LIFECYCLE_PRODUCERS: tuple[tuple[str, str, str, str], ...] = (
    ("plan_review_started", "plan_review_finished", "plan_review_failed", "plan_review_round"),
    ("implementation_review_started", "implementation_review_finished", "implementation_review_failed", "implementation_review_round"),
)

# (finalize_name, clean_code, blocked_code): verdict "clean" or "clean-with-deferrals" (deferrals are
# backlogged findings, not blockage) contributes clean_code; "blocked" contributes blocked_code. A
# missing/unrecognized verdict value (corrupt or hostile payload) contributes nothing -- dropped,
# never guessed.
INSTRUMENTATION_FINALIZE_VERDICT_PRODUCERS: tuple[tuple[str, str, str], ...] = (
    ("plan_review_finalized", "plan_review_clean", "plan_review_blocked"),
    ("implementation_review_finalized", "implementation_review_clean", "implementation_review_blocked"),
)

INSTRUMENTATION_FINALIZE_CLEAN_VERDICTS = frozenset({"clean", "clean-with-deferrals"})

def instrumentation_render_timestamp(moment: datetime) -> str:
    """Render an aware datetime in the exact `+00:00`-suffixed UTC form
    INSTRUMENTATION_TIMESTAMP_PATTERN requires (events.jsonl's own `ts` field uses a `Z` suffix,
    which the schema deliberately does not accept -- see INSTRUMENTATION_TIMESTAMP_PATTERN)."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")

# Constant remote-metadata surface (T5): the archive branch, path grammar, and commit-message
# template are FIXED -- never adapter/flag-configurable -- so no freeform adopter string can reach
# the remote through git metadata (see the plan's "Remote metadata is constant" section).
INSTRUMENTATION_ARCHIVE_BRANCH = "tautline-telemetry-archive"

# telemetry/<16hex lane_id>/<colon-free seconds-precision UTC stamp>-<end_seq>.json. Colon-free so
# the branch checks out on Windows/NTFS; the -<end_seq> suffix (not sub-second time) disambiguates
# same-second publishes. Bound to the record's own fields by hygiene -- a blob cannot be moved under
# another lane/stamp/seq to forge a remote_max.
INSTRUMENTATION_ARCHIVE_PATH_PATTERN = r"^telemetry/[0-9a-f]{16}/\d{8}T\d{6}Z-\d+\.json$"

def instrumentation_archive_stamp(emitted_at: str) -> str:
    """The colon-free seconds-precision UTC filename stamp (YYYYMMDDTHHMMSSZ) derived from a
    validated record's `emitted_at`. Fractional seconds (which the schema permits) are truncated --
    the `-<end_seq>` suffix, not sub-second time, keeps same-second publishes distinct."""
    moment = datetime.fromisoformat(emitted_at).astimezone(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")

def instrumentation_archive_relpath(record: dict) -> str:
    """Derive the archive path from a VALIDATED record's own fields ONLY (lane_id, emitted_at,
    end_seq). Callers pass records that already passed instrumentation_record_errors(); this never
    interpolates any adopter-supplied or freeform string."""
    return f"telemetry/{record['lane_id']}/{instrumentation_archive_stamp(record['emitted_at'])}-{record['end_seq']}.json"

def instrumentation_archive_path_matches_record(relpath: str, record: dict) -> bool:
    """Hygiene path-binding keystone: a blob's FULL repo-relative path (directory lane_id, filename
    stamp derived from emitted_at, and -<end_seq> suffix) must equal what the blob's own validated
    fields derive. Because the path is fully a function of the record, binding reduces to recomputing
    the expected path and comparing -- a conforming blob moved under another lane, or renamed to a
    different stamp/seq, no longer matches and cannot forge that lane's remote_max."""
    return relpath == instrumentation_archive_relpath(record)

# Pinned remote commit metadata (T5): every telemetry commit is authored/committed by a FIXED
# identity with a FIXED message and a date derived only from the validated record -- the adopter's
# own git config would otherwise embed company/project strings in the identity, and default commit
# dates embed the local timezone. Constants, never adapter/flag-configurable.
INSTRUMENTATION_COMMIT_AUTHOR_NAME = "tautline-telemetry"

INSTRUMENTATION_COMMIT_AUTHOR_EMAIL = "telemetry@tautline.invalid"

INSTRUMENTATION_COMMIT_MESSAGE = "telemetry: instrumentation record"

# Schema versions THIS publisher understands. A blob labeled with any other version is rejected
# fail-closed (upgrade-your-framework) -- a future v2 could carry freeform data past a grammar-only
# check, so an older publisher must never trust it on syntax alone.
INSTRUMENTATION_KNOWN_SCHEMA_VERSIONS = frozenset({INSTRUMENTATION_SCHEMA_VERSION})

# Verifier version: bump when a hygiene RULE changes so the content-addressed hygiene cache re-walks
# already-seen commits under the new rules rather than trusting a stale pass.
INSTRUMENTATION_HYGIENE_VERIFIER_VERSION = "1"

def instrumentation_commit_epoch(emitted_at: str) -> int:
    """The integer UNIX epoch for a validated record's `emitted_at` -- the pinned author/committer
    date. emitted_at is always UTC (`+00:00`), so this is timezone-unambiguous."""
    return int(datetime.fromisoformat(emitted_at).timestamp())

def instrumentation_expected_commit_identity_line(emitted_at: str) -> str:
    """The exact author/committer identity+date line a pinned telemetry commit must carry:
    `<name> <<email>> <epoch> +0000`. Both author and committer lines must equal this."""
    return (
        f"{INSTRUMENTATION_COMMIT_AUTHOR_NAME} <{INSTRUMENTATION_COMMIT_AUTHOR_EMAIL}> "
        f"{instrumentation_commit_epoch(emitted_at)} +0000"
    )

# T4 (0.9.0 sanitized instrumentation): prepare/validate CLI commands.
#
# `prepare-instrumentation-record` writes a SINGLE overwritten preview file under the lane's own
# `.ai-runs/instrumentation/` -- never a timestamped/accumulating one like session journals,
# because the window-semantics design deliberately keeps NO local window/attempt state to key a
# second preview off of. The preview always aggregates from remote_max=0 (the full retained local
# history): fetching the REAL remote_max off the hygiene-verified archive branch is
# publish-instrumentation-record's job (T5, not built yet), and the preview is a human-inspection
# artifact the publisher never reads at publish time (see the design's "Publish-time
# recomputation" section) -- it exists to let an operator see what the next publish would contain,
# not to influence it.
def instrumentation_preview_dir(data: dict, target: Path) -> Path:
    return target / data["laneState"]["runsDir"] / "instrumentation"

def instrumentation_preview_path(data: dict, target: Path) -> Path:
    return instrumentation_preview_dir(data, target) / "preview.json"

def instrumentation_record_blob_text(record: dict) -> str:
    """The single canonical on-disk form of a record blob (pretty, key-sorted, trailing newline).
    Used identically to write the blob, to byte-compare the committed blob on readback, and by the
    hygiene walk -- one representation so a readback can byte-match what was written. allow_nan=False
    so a non-finite number raises here rather than serializing the non-standard NaN/Infinity tokens
    (validation already rejects them; this is belt-and-suspenders on the write path)."""
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"

def git_object_bytes(repo: Path, spec: str) -> bytes | None:
    """Raw bytes of a git object (`git cat-file blob <spec>`), NOT whitespace-stripped -- run_git/
    run_command strip trailing newlines, which would break an exact byte comparison. Returns None on
    any error."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", spec],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    return proc.stdout if proc.returncode == 0 else None

def instrumentation_hygiene_cache_path() -> Path:
    return telemetry_state_dir() / "archive-hygiene-cache.json"

def read_instrumentation_hygiene_cache() -> set[str]:
    """Content-addressed set of commit SHAs already verified clean under the CURRENT verifier
    version. A verifier-version bump invalidates the whole cache so a rule change re-walks history
    rather than trusting a stale pass."""
    try:
        raw = json.loads(instrumentation_hygiene_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, dict) or raw.get("verifier") != INSTRUMENTATION_HYGIENE_VERIFIER_VERSION:
        return set()
    verified = raw.get("verified")
    return set(verified) if isinstance(verified, list) else set()

def instrumentation_ancestry_state_path(remote_url: str) -> Path:
    key = hashlib.sha256(f"{remote_url}\n{INSTRUMENTATION_ARCHIVE_BRANCH}".encode("utf-8")).hexdigest()[:16]
    return telemetry_state_dir() / "archive-tip" / f"{key}.json"

def read_instrumentation_ancestry_tip(remote_url: str) -> str | None:
    try:
        raw = json.loads(instrumentation_ancestry_state_path(remote_url).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tip = raw.get("tip") if isinstance(raw, dict) else None
    return tip if isinstance(tip, str) and tip else None

# The declared Python floor, as shipped to adopters in the generated PyPI package. pyproject's
# ruff `target-version` is the source of truth; this constant must track it, and
# test_registry_package_floor_tracks_pyproject pins the two together so a future raise cannot
# leave the published wheel advertising a version the release no longer supports. That is exactly
# what happened at the 3.10 -> 3.12 raise: every in-repo gate moved and the wheel kept saying
# >=3.10, so pip/pipx would still install it onto an interpreter the release had just dropped.
PYTHON_FLOOR = "3.12"

# GitHub's canonical owner/repo, in GitHub's own casing. The OIDC claim used by npm's
# trusted publishing carries this exact string, and npm compares case-sensitively.
REGISTRY_PACKAGE_REPO_SLUG = "Tautlines/tautline"

REGISTRY_PACKAGE_REGISTRIES = ("npm", "pypi")

# Where the pypi payload embeds the committed tree, relative to the package root.
REGISTRY_PACKAGE_DIST_DIR = "src/tautline/_dist"

# ---------------------------------------------------------------------------
# The release tail: export -> mirror commit -> tag -> Release -> registries.
#
# Two facts shape every line below.
#
# 1. The export is a FRESH repository with a root commit
#    (public_release_export_repository), so it shares no ancestor with the public
#    mirror and CANNOT be fast-forwarded onto it. Pushing it would demand a
#    force-push and would orphan every existing clone. The mirror commit is
#    therefore built by cloning the mirror, overlaying the export tree while
#    preserving `.git/`, and committing on top of the mirror's current HEAD.
#    The mirror's history is never rewritten and is never force-pushed.
#
# 2. Run from this checkout, bare `gh` resolves to the DEV repository. A `gh`
#    call without `--repo` would create the Release in the wrong repo, where no
#    publish workflow exists -- a silent no-op. Every `gh` call in the tail goes
#    through release_tail_gh(), which pins --repo and refuses a caller-supplied
#    one, so the pinning cannot be forgotten at a new call site.
# ---------------------------------------------------------------------------
PUBLIC_MIRROR_REPO = "tautlines/tautline"

PUBLIC_MIRROR_REMOTE = "https://github.com/tautlines/tautline.git"

PUBLIC_MIRROR_BRANCH = "main"

RELEASE_TAIL_RUN_FIELDS = "conclusion,databaseId,event,headBranch,headSha,status,url"

class ReleaseTailError(Exception):
    """A fail-closed refusal. release_tail() turns it into a message + non-zero exit."""

def graphify_latest_output_mtime(status_paths: list[Path]) -> tuple[float | None, Path | None]:
    latest_mtime: float | None = None
    latest_path: Path | None = None
    seen: set[Path] = set()
    for path in status_paths:
        if not path.exists():
            continue
        candidates = [path]
        if path.is_dir():
            candidates = [candidate for candidate in path.rglob("*") if candidate.is_file()]
        for candidate in candidates:
            if candidate in seen or not candidate.exists() or not candidate.is_file():
                continue
            seen.add(candidate)
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = candidate
    return latest_mtime, latest_path

_PM_SURFACE_METACHARACTERS = "*?["

def pm_surface_fixed_prefix(pattern: str) -> str:
    """The literal substring up to (not including) the first fnmatch metacharacter (`*`, `?`, `[`).

    The classifier's matcher ultimately uses fnmatch, so `?` and `[]` are wildcards too. A pattern
    with no metacharacter is entirely fixed (its own prefix).
    """
    for index, char in enumerate(pattern):
        if char in _PM_SURFACE_METACHARACTERS:
            return pattern[:index]
    return pattern

def pm_roots_overlap(a: str, b: str) -> bool:
    """Symmetric path-segment containment: True if a == b, or either is at/under the other."""
    a = a.strip("/")
    b = b.strip("/")
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")

def _looks_like_repo_relative_path(value: object) -> bool:
    """True only for a repo-relative path value (no whitespace/prose, no ~, /, or .. escape).

    Free-form / tracker source-of-truth values (`backlogAdapter`, `GitHub issues`, prose) are NOT
    paths and are skipped by the bounded loader guard.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or any(char.isspace() for char in text):
        return False
    if text.startswith("~") or text.startswith("/"):
        return False
    return not any(segment == ".." for segment in text.strip("/").split("/"))

def lock_path(data: dict, target: Path) -> Path:
    return target / data["laneState"]["lockPath"]

def read_lock(data: dict, target: Path) -> dict | None:
    path = lock_path(data, target)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema": "minervit-methodology-lock/v1", "invalid": True, "path": str(path)}

def lock_archive_path(data: dict, target: Path, suffix: str = "lock") -> Path:
    archive_dir = target / data["laneState"]["runsDir"] / "methodology-locks"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archived = archive_dir / f"{stamp}-{suffix}.json"
    counter = 1
    while archived.exists():
        archived = archive_dir / f"{stamp}-{suffix}-{counter}.json"
        counter += 1
    return archived

def archive_lock_file(data: dict, target: Path, suffix: str = "lock") -> Path | None:
    path = lock_path(data, target)
    if not path.exists():
        return None
    archived = lock_archive_path(data, target, suffix)
    path.replace(archived)
    return archived

def relevant_scratch_plan_candidates(data: dict, candidates: list[Path]) -> list[Path]:
    planning = data["planningArtifacts"]
    source = str(planning.get("sourceOfTruth", "")).strip().rstrip("/")
    source_parent = str(Path(source).parent) if source else ""
    if source_parent == ".":
        source_parent = ""
    markers = [
        source.lower(),
        source_parent.lower(),
        str(planning.get("template", "")).lower(),
        str(data.get("repo", "")).lower(),
    ]
    markers = [marker for marker in markers if marker]
    relevant: list[Path] = []
    for path in candidates:
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:32768].lower()
        except OSError:
            sample = ""
        haystack = f"{path.name.lower()}\n{sample}"
        if any(marker in haystack for marker in markers):
            relevant.append(path)
    return relevant

def scratch_status_line(label: str, candidates: list[Path]) -> str:
    if not candidates:
        return f"{label}: none"
    preview = ", ".join(str(path) for path in candidates[:5])
    suffix = "" if len(candidates) <= 5 else f", ... +{len(candidates) - 5} more"
    return f"{label}: {len(candidates)} candidate(s) - {preview}{suffix}"

def replace_markdown_section(text: str, heading: str, replacement_body: str) -> str:
    section = f"{heading}\n\n{replacement_body.strip()}\n"
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return text.rstrip() + "\n\n" + section
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[: match.start()] + section.rstrip() + "\n\n" + text[end:].lstrip()

def markdown_fence_for_embedded_text(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)

def resolve_plan_path(target: Path, plan: Path) -> Path:
    plan = plan.expanduser()
    return plan if plan.is_absolute() else target / plan

# Unfinished-work markers, matched by SHAPE rather than by bare word (item 29: plan-precheck
# marker false positive). The old rule flagged four words anywhere on any line, so it rejected a
# finished plan over `**Placeholder scan:** clean.` -- a heading the superpowers writing-plans
# self-review template tells the author to write. Two framework surfaces contradicting each other
# is worse than a missed marker, especially since the refusal named neither the line nor the word.
# Tuples, not lists, so they stay out of the policy-phrase SSOT export.
PLAN_UNFINISHED_MARKER_PATTERNS = (
    (r"\bTODO\b", "TODO marker"),
    (r"\bTBD\b", "TBD marker"),
    (r"\bFIXME\b", "FIXME marker"),
    (r"<[^>\n]{0,60}?(?:placeholder|todo|tbd|fill this in)[^>\n]{0,60}?>", "angle-bracket fill-in"),
    (r"\bfill (?:this|these|it|them) in\b", "fill-this-in instruction"),
)

# `placeholder`/`stub` count only as a standalone value -- "Owner: placeholder", a bare bullet.
# As bare words they are ordinary technical English ("test-stub bugs", "`<workspace>` placeholder
# substitution") and produced most of this check's false refusals while adding almost no signal the
# shapes above do not already carry. Checked in Python, not by regex: the obvious pattern for
# "optional label, then only this word" nests quantifiers and backtracks catastrophically on a long
# line, which would hang the gate it guards rather than fail it.
PLAN_PLACEHOLDER_ONLY_VALUES = frozenset({"placeholder", "placeholders", "stub", "stubs"})

def text_without_code_spans(text: str) -> str:
    """Public name for the fence/inline-code blanker below, for any scanner that must not read
    EXAMPLE text as real content.

    Item 79 WS2 needs exactly this for PR bodies: a body that shows `Resolves #1, #2` inside a
    fenced block as an example of what NOT to write must not be refused for containing it. Rather
    than write a second four-line stripper -- two implementations of one rule is how they drift --
    the closing-reference scanners share this one. Blanking (not deleting) keeps every offset
    aligned, which is why it can be shared safely.
    """
    return _plan_text_without_quoted_spans(text)


def _plan_text_without_quoted_spans(text: str) -> str:
    """`text` with fenced blocks and inline-code spans blanked to spaces.

    Blanked, not deleted, so every offset and line number still lines up with the original -- the
    refusal has to quote the real line number back to the author.
    """
    out = list(text)

    def blank(match: re.Match) -> None:
        for index in range(match.start(), match.end()):
            if out[index] != "\n":
                out[index] = " "

    for match in re.finditer(r"```.*?```", text, re.DOTALL):
        blank(match)
    for match in re.finditer(r"`[^`\n]*`", text):
        blank(match)
    return "".join(out)

def _plan_line_is_placeholder_only(line: str) -> bool:
    """True when a line's whole VALUE is the word placeholder/stub, list marker and label aside.

    Strips the Markdown list forms plans actually use for open items -- bullets, numbered entries,
    and task checkboxes. Handling only unordered bullets let `- [ ] placeholder` and `1. stub`
    through, which the pre-change gate caught (0.27.0 implementation review R1 P2).
    """
    body = re.sub(r"^[\s>]*(?:[-*+]|\d+[.)])?\s*(?:\[[ xX]?\])?\s*", "", line)
    if ":" in body:
        body = body.split(":", 1)[1]
    # Strip Markdown emphasis from the value. Plans label fields in the template's bold style, so
    # `**Owner:** placeholder` leaves a trailing `**` on the value and the comparison missed a
    # genuine unfinished entry (0.27.0 implementation review R1 P2). Markup normalization is
    # bounded, unlike the negation heuristic this rule deliberately no longer carries.
    return body.strip(" *_`\t").rstrip(".").strip(" *_`\t").lower() in PLAN_PLACEHOLDER_ONLY_VALUES

def plan_unfinished_marker_hits(text: str) -> list[tuple[int, str, str]]:
    """`(line_number, what_matched, the_line)` for each unfinished-work marker in `text`.

    Quoted spans are exempt: a plan that discusses these markers -- this repository's own plans do
    -- is not itself unfinished.
    """
    scannable = _plan_text_without_quoted_spans(text)
    lines = text.splitlines()
    hits: list[tuple[int, str, str]] = []
    seen: set[int] = set()
    for pattern, label in PLAN_UNFINISHED_MARKER_PATTERNS:
        for match in re.finditer(pattern, scannable, re.IGNORECASE):
            line_number = scannable.count("\n", 0, match.start()) + 1
            if line_number in seen:
                continue
            body = lines[line_number - 1].strip() if line_number <= len(lines) else ""
            # Only a negation in the same clause resolves the marker; a word-only scan backwards
            # crosses sentence breaks and hides real work.
            seen.add(line_number)
            hits.append((line_number, f"{label} ({match.group(0).strip()!r})", body))
    for index, line in enumerate(_plan_text_without_quoted_spans(text).splitlines(), start=1):
        if index in seen or not _plan_line_is_placeholder_only(line):
            continue
        seen.add(index)
        hits.append((index, "placeholder-only line", lines[index - 1].strip()))
    return sorted(hits)

# What counts as an acceptance criterion NAMING an executable test/scenario id. canonical-rules.md
# already declares "missing named test ... is a stub"; rec #13 gives it teeth at plan finalization.
# A tuple (not a list) so it is excluded from the policy-phrase SSOT export -- these are regex
# patterns, not human phrase vocabulary.
PLAN_AC_TEST_ID_PATTERNS = (
    r"\btest_[A-Za-z0-9_]+",                       # pytest / go / rust test_*
    r"\b[A-Za-z0-9_]+_test\b",                     # *_test
    r"[\w./-]+\.(?:spec|test)\.[A-Za-z0-9]+\b",    # foo.spec.ts / bar.test.js
    r"[\w./-]+\.feature\b",                        # gherkin .feature file
    r"\bScenario\s*:",                             # Scenario: <name>
    r"\bscenario\s+[\"'][^\"']+[\"']",             # scenario "name"
    r"\bit\(\s*[\"']",                             # it("...")
    r"\b(?:tests?|specs?|scenarios?|verified by|covered by)\s*:\s*\S+",  # explicit annotation w/ content
)

STANDING_AUTONOMY_DIRECTIVE_CORE = (
    "STANDING AUTONOMY DIRECTIVE\n"
    "Work autonomously toward the active goal. Assume the operator is AFK.\n"
    "Make decisions with best judgment. {record_line}\n"
    "While safe authorized work remains, do not stop, defer to the operator, or wait for "
    "permission mid-run.\n"
    "If blocked on one part, work exhaustively on all other parts of the goal you can advance.\n"
    "Only a fork the canonical rules class as operator-owned (the existing true-blocker and "
    "approval categories - not a shorter list) earns a question - {question_line} and keep "
    "working elsewhere. Never invent approval; when such a fork is queued and no safe "
    "authorized work remains anywhere in the goal, that is a true blocker and yielding on "
    "it is correct."
)

def _replay_loader_streams(out_text: str, err_text: str) -> None:
    """Replay loader diagnostics captured during lane resolution onto their ORIGINAL channels,
    AFTER the standing directive is printed and stdout is flushed -- so a 2>&1 consumer sees the
    directive bytes before any replayed stderr coercion warning."""
    if out_text:
        sys.stdout.write(out_text)
        sys.stdout.flush()
    if err_text:
        sys.stderr.write(err_text)
        sys.stderr.flush()

def _extract_ac_section(plan_text: str, ac_headings: list[str]) -> str:
    """Return the text under the first matching acceptance-criteria heading, up to the next heading."""
    lines = plan_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and m.group(2).strip().lower().rstrip(":") in ac_headings:
            start = i + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        body.append(line)
    return "\n".join(body)

def _split_ac_items(section_text: str) -> list[str]:
    """Group each top-level list bullet (and its nested/continuation lines) into one AC block."""
    items: list[str] = []
    current: list[str] | None = None
    for line in section_text.splitlines():
        if re.match(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", line):
            if current is not None:
                items.append("\n".join(current))
            current = [line]
        elif current is not None and (line.strip() == "" or line.startswith((" ", "\t"))):
            current.append(line)
        elif current is not None:
            items.append("\n".join(current))
            current = None
    if current is not None:
        items.append("\n".join(current))
    return [item for item in items if item.strip()]

def finding_counts(findings: list[dict]) -> tuple[int, int]:
    critical = 0
    p1 = 0
    for item in findings:
        severity = str(item.get("severity", item.get("priority", ""))).lower()
        status = str(item.get("status", "")).lower()
        if status in plan_review_resolved_statuses():
            continue
        if severity in {"critical", "c1", "p0"}:
            critical += 1
        elif severity in {"p1", "important", "high"}:
            p1 += 1
    return critical, p1

# Every refusal in the classified-findings contract cites ONE doc section, so an agent reading a
# refusal can write the field without literal-phrase archaeology through the source.
CLASSIFIED_FINDINGS_CONTRACT_DOC = "docs/reference/operations/cli-operations.md"


def finding_text_field(item: dict, key: str) -> str:
    """A finding's string field, with JSON `null` treated as ABSENT rather than as text.

    Codex R1 P2 on the record-contract diff, twice over: `str(item.get(key, "")).strip()` turns a
    JSON `null` into the truthy string "None", so `"routed_to": null` satisfied a check that exists
    to demand a backlog row and `"acceptance_criterion": null` satisfied one that exists to demand
    a criterion. A required field bypassed by writing `null` is a contract with a hole the exact
    width of the word.
    """
    value = item.get(key)
    return value.strip() if isinstance(value, str) else ""


def classified_finding_substance_errors(findings: list[dict]) -> list[str]:
    """A finding has to BE one. Codex R3 P2 on the record-contract diff.

    The non-empty rule counted objects, and every validator downstream skips an object with no
    severity (not a blocker) and no opt-in AC field -- so `[{}]` satisfied a gate that exists to
    demand evidence, and `clean-with-deferrals` could be recorded with a list of placeholders.
    A count is not evidence.

    The floor is exactly what the contract doc already told authors to write: a severity and a
    summary. Nothing more, so an honest reviewer's record is never rejected for shape.
    """
    errors: list[str] = []
    for index, item in enumerate(findings):
        if not (finding_text_field(item, "severity") or finding_text_field(item, "priority")):
            errors.append(
                f"finding {index}: severity is required "
                f"(see {CLASSIFIED_FINDINGS_CONTRACT_DOC}, classified-findings contract)"
            )
        if not (finding_text_field(item, "summary") or finding_text_field(item, "title")):
            errors.append(
                f"finding {index}: summary is required -- a recorded finding states what was found "
                f"(see {CLASSIFIED_FINDINGS_CONTRACT_DOC}, classified-findings contract)"
            )
    return errors


def critical_origin_deferrals(findings: list[dict]) -> list[dict]:
    """Deferred findings whose ORIGIN severity is Critical/P1 -- the relabel-to-escape target.

    Severity set written inline, matching `finding_counts` above: an UPPER_CASE list-of-str
    constant would auto-enter the policy-phrase SSOT, and a severity vocabulary is not prose.
    """
    out = []
    for item in findings:
        severity = str(item.get("severity", item.get("priority", ""))).lower()
        status = str(item.get("status", "")).lower()
        if status == "deferred" and severity in {"critical", "c1", "p0", "p1", "important", "high"}:
            out.append(item)
    return out


def critical_origin_deferral_errors(findings: list[dict]) -> list[str]:
    """A deferred Critical/P1 owes a reason and the criterion it was judged non-blocking against.

    A deferred P2 owes nothing new: the target is relabelling a blocker to `deferred`, not
    ceremony on findings that were never blocking.
    """
    errors: list[str] = []
    for item in critical_origin_deferrals(findings):
        severity = str(item.get("severity", item.get("priority", ""))).lower()
        label = str(item.get("id") or item.get("title") or item.get("summary") or "finding")[:80]
        if len(finding_text_field(item, "deferral_rationale")) < 12:
            errors.append(
                f'deferred {severity} finding {label!r} needs a "deferral_rationale" string '
                f"(>=12 chars) stating why it is non-blocking "
                f"(see {CLASSIFIED_FINDINGS_CONTRACT_DOC}, classified-findings contract)"
            )
        if not finding_text_field(item, "acceptance_criterion"):
            errors.append(
                f'deferred {severity} finding {label!r} needs an "acceptance_criterion" string '
                f"naming the criterion it was judged non-blocking against "
                f"(see {CLASSIFIED_FINDINGS_CONTRACT_DOC}, classified-findings contract)"
            )
    return errors


def plan_review_resolved_statuses() -> set[str]:
    return {"fixed", "resolved", "addressed", "deferred", "closed", "false-positive", "false positive", "not-applicable", "not applicable"}

def classified_findings_have_resolved_blocker_evidence(findings: list[dict]) -> bool:
    for item in findings:
        severity = str(item.get("severity", item.get("priority", ""))).lower()
        status = str(item.get("status", "")).lower()
        if severity in {"critical", "c1", "p0", "p1", "important", "high"} and status in plan_review_resolved_statuses():
            return True
    return False

FINDING_DISPOSITIONS = ("fixed", "routed", "refuted")
# Tuple/frozenset on purpose: an UPPER_CASE list-of-str auto-enters the policy-phrase SSOT
# (tests/test_policy_phrases_ssot.py), and a field vocabulary is not policy prose.
BLOCKER_SEVERITIES = frozenset({"critical", "c1", "p0", "p1", "important", "high"})


def classified_finding_ac_errors(findings: list[dict], *, require_fields: bool) -> list[str]:
    """AC-traceability schema errors.

    `require_fields=False` is the migration tolerance: findings recorded before the record
    carried these fields are validated only when they opt in by carrying any of them.

    `disposition` is a SEPARATE axis from `status` (packet W1.1, S3). `status` keeps the
    plan-review vocabulary, including `deferred`; `disposition` never gains a `deferred` value.
    A deferred blocker records `disposition: routed` + `routed_to`, or `fixed`/`refuted`.
    """
    errors: list[str] = []
    for index, item in enumerate(findings):
        severity = str(item.get("severity", item.get("priority", ""))).lower()
        blocker = severity in BLOCKER_SEVERITIES
        opted_in = any(key in item for key in ("ac_ref", "disposition", "routed_to"))
        if not opted_in and not (require_fields and blocker):
            continue
        if "ac_ref" not in item:
            errors.append(
                f"finding {index}: ac_ref is required (the acceptance criterion violated, or null "
                f"for out-of-scope)"
            )
        ac_ref = item.get("ac_ref")
        if ac_ref is not None and (not isinstance(ac_ref, str) or not ac_ref.strip()):
            errors.append(f"finding {index}: ac_ref must be a non-empty string or null")
            ac_ref = None
        disposition = str(item.get("disposition", "")).lower()
        if disposition not in FINDING_DISPOSITIONS:
            deferred_hint = ""
            if str(item.get("status", "")).lower() == "deferred":
                # The bridge rule (packet W1.1, S3). Two vocabularies must read as one contract,
                # or a deferred blocker looks like it is caught between two gates.
                deferred_hint = (
                    " -- a deferred blocker records disposition routed plus routed_to, or is "
                    "fixed/refuted"
                )
            errors.append(
                f"finding {index}: disposition must be one of "
                f"{'/'.join(FINDING_DISPOSITIONS)}{deferred_hint}"
            )
            continue
        if disposition == "routed":
            if not finding_text_field(item, "routed_to"):
                errors.append(
                    f"finding {index}: routed_to (backlog row id) is required when disposition is "
                    f"routed"
                )
            if isinstance(ac_ref, str) and ac_ref.strip():
                errors.append(
                    f"finding {index}: violates {ac_ref} and may not be routed -- an AC-bearing "
                    f"finding is "
                    "fixed or refuted regardless of severity"
                )
    return errors


def classified_finding_open_ac_errors(findings: list[dict]) -> list[str]:
    """Findings that keep the item out of Done: non-null ac_ref, not fixed/refuted."""
    errors: list[str] = []
    for index, item in enumerate(findings):
        ac_ref = item.get("ac_ref")
        if isinstance(ac_ref, str) and ac_ref.strip():
            disposition = str(item.get("disposition", "")).lower()
            if disposition not in {"fixed", "refuted"}:
                errors.append(
                    f"finding {index} is open against {ac_ref.strip()} "
                    f"(disposition {disposition or 'missing'!r}); fix it or refute it with cited "
                    f"evidence"
                )
    return errors


def classified_findings_routed(findings: list[dict]) -> bool:
    """True when any finding is routed -- which forces `clean-with-deferrals`, never `clean`."""
    return any(str(item.get("disposition", "")).lower() == "routed" for item in findings)


def plan_review_round_number(review_round: str) -> int | None:
    match = re.search(r"\d+", str(review_round))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None

def plan_review_effective_round(declared_round: int | None, observed_runs: int) -> int:
    """The round this launch really is: the higher of what the caller called it and one past
    what the evidence shows was already spent.

    The budget is spent by INVOCATIONS, not by labels. A lane that relabels every round `R1`
    still consumed the reviewer, so `--round` alone cannot bound the ceremony (item 24:
    plan-review round advance gap -- a live lane spent ten runs on one plan, six under one
    label, and the hard cap never engaged).
    """
    return max(int(declared_round or 0), int(observed_runs) + 1)

def plan_review_blocker_total(critical_count: int, p1_count: int) -> int:
    return max(0, int(critical_count)) + max(0, int(p1_count))

def previous_plan_review_blocker_total(manifest_path: Path) -> int | None:
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return plan_review_blocker_total(
            int(manifest.get("unresolved_critical_count", 0)),
            int(manifest.get("unresolved_p1_count", 0)),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

def resolve_unmanaged_root(target: Path) -> Path:
    """Resolve the fresh-offer root for an UNMANAGED target: the VCS toplevel (so an offer from
    `<repo>/sub/dir` initializes the repository, not the subdirectory), falling back to the target
    itself for non-git trees. SEPARATE from the classifier and NEVER called on the hook path -- it
    shells out to git, which the total-containment invariant forbids."""
    target = Path(target)
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return target
    if result.returncode == 0:
        top = result.stdout.strip()
        if top:
            return Path(top)
    return target

def _render_onboarding_path(path: Path, invocation_cwd: Path) -> str:
    """Render a path relative to invocation_cwd ONLY when it is under it (or equal, -> '.'),
    otherwise ABSOLUTE -- never a wrong-relative path for a non-default --target invocation."""
    path = Path(path)
    try:
        rel = path.relative_to(invocation_cwd)
    except ValueError:
        return str(path)
    return "." if rel == Path(".") else str(rel)

def _render_onboarding_command_path(path: Path, invocation_cwd: Path) -> str:
    """Render a path for interpolation into an EMITTED COMMAND: the cwd-relative display form
    (per _render_onboarding_path), then shell-quoted so a copy-run command survives spaces and
    shell metacharacters (e.g. `/Users/x/My Project`). shlex.quote('.') == '.', so the
    unmanaged-at-target case stays `--target .` unquoted and byte-identical to today."""
    return shlex.quote(_render_onboarding_path(path, invocation_cwd))

def onboarding_offer_lines(info: dict) -> list[str]:
    """PURE, declarative offer copy: one exact command per state, root/paths substituted from
    `info` and rendered cwd-relative per _render_onboarding_path. `managed` -> []. For `unmanaged`
    the caller must have populated `info['root']` with the VCS toplevel (see
    onboarding_info_for_offer); this function never shells out."""
    state = info["state"]
    cwd = info["invocation_cwd"]
    if state == "unmanaged":
        root = _render_onboarding_command_path(info["root"], cwd)
        return [
            "onboarding_offer: this repository has no Tautline adapter. Guided onboarding writes "
            f"one from a short interview: tautline init --target {root}",
            "onboarding_offer: agents put the adopt/skip decision to the human operator through "
            "AskUserQuestion (or the host equivalent) before running init; do not run init "
            "unprompted and do not re-ask on refusal.",
        ]
    if state == "interview-pending":
        root = _render_onboarding_command_path(info["root"], cwd)
        interview = _render_onboarding_path(info["interview_path"], cwd)  # display only, not a cmd
        return [
            "onboarding_offer: an onboarding interview is already in progress "
            f"({interview}). Finish it: answer the remaining questions, then run: "
            f"tautline init --target {root} --continue",
        ]
    if state == "source-unrendered":
        root = _render_onboarding_command_path(info["root"], cwd)
        source = _render_onboarding_command_path(info["source_path"], cwd)
        return [
            "onboarding_offer: a source adapter exists but this repo is not rendered. Next: "
            f"tautline render-adapters --project {source} --target {root} --write, then: "
            f"tautline lane-start --target {root}",
        ]
    return []

def _no_adapter_recovery_commands(info: dict) -> list[str]:
    """The state-correct recovery command(s) for the `Recovery command:` block. Unmanaged keeps
    today's exact `tautline init --target .` (byte-preserved); evidence states carry the correct
    command instead of the stale init line. Never emits `onboarding_offer:` copy."""
    state = info["state"]
    cwd = info["invocation_cwd"]
    if state == "unmanaged":
        return [f"tautline init --target {_render_onboarding_command_path(info['target'], cwd)}"]
    if state == "interview-pending":
        root = _render_onboarding_command_path(info["root"], cwd)
        return [f"tautline init --target {root} --continue"]
    if state == "source-unrendered":
        root = _render_onboarding_command_path(info["root"], cwd)
        source = _render_onboarding_command_path(info["source_path"], cwd)
        return [
            f"tautline render-adapters --project {source} --target {root} --write",
            f"tautline lane-start --target {root}",
        ]
    return []

def _no_adapter_recovery_block(commands: list[str]) -> str:
    lines = ["Recovery command:"]
    lines.extend(f"   {cmd}" for cmd in commands)
    return "\n".join(lines) + "\n"

def no_adapter_message(info: dict) -> str:
    """Compose the state-aware no-adapter error: stable sentinel + state-correct recovery block +
    preserved footer. For `unmanaged` this is byte-identical to NO_ADAPTER_MESSAGE. `managed`
    never produces one (it is not a no-adapter state)."""
    recovery = _no_adapter_recovery_block(_no_adapter_recovery_commands(info))
    return NO_ADAPTER_SENTINEL + recovery + NO_ADAPTER_FOOTER

def path_without_minervit_codex_shims(path_value: str) -> str:
    parts = [
        part
        for part in path_value.split(os.pathsep)
        if part and Path(part).name != "codex-fast-mode-bin"
    ]
    return os.pathsep.join(parts)

def codex_fast_mode_shim_content(real_codex: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by minervit-methodology. Forces Codex CLI fast mode for adapter-launched commands.\n"
        "set -euo pipefail\n"
        f"REAL_CODEX={shlex.quote(real_codex)}\n"
        "case \"${MINERVIT_CODEX_FAST_MODE:-1}\" in\n"
        "  0|false|False|FALSE|off|OFF|no|NO)\n"
        "    exec \"$REAL_CODEX\" \"$@\"\n"
        "    ;;\n"
        "esac\n"
        "exec \"$REAL_CODEX\" --enable fast_mode \"$@\"\n"
    )

def source_plan_is_active_candidate(target: Path, path: Path) -> bool:
    try:
        rel = path.resolve(strict=False).relative_to(target.resolve(strict=False))
    except ValueError:
        return False
    inactive_parts = {"archive", "archives", "archived", "superseded", "obsolete", "old"}
    return not any(part.lower() in inactive_parts for part in rel.parts)

def text_references_path(text: str, reference: str) -> bool:
    reference = reference.strip().lower()
    if not reference or "/" not in reference:
        return False
    escaped = re.escape(reference)
    return bool(re.search(rf"(?<![A-Za-z0-9_./-]){escaped}(?![A-Za-z0-9_/-])", text.lower()))

def upsert_section_entries(text: str, section: str, entries: list[str]) -> str:
    entries = [entry for entry in entries if entry and entry not in text]
    if not entries:
        return text if text.endswith("\n") else text + "\n"
    heading = f"## {section}"
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return text.rstrip() + f"\n\n{heading}\n" + "\n".join(entries) + "\n"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    updated = lines[:end] + entries + lines[end:]
    return "\n".join(updated).rstrip() + "\n"

def unique_destination(directory: Path, name: str) -> Path:
    dest = directory / name
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

def methodology_reexec_token_dir() -> Path:
    # Cross-version note: the consumer receives the token's ABSOLUTE path via
    # METHODOLOGY_REEXEC_TOKEN_ENV, so relocating the create dir is handoff-safe in both
    # directions during the rebrand transition.
    return Path.home() / ".config" / "tautline" / "reexec-tokens"

SNAPSHOT_PIN_SCHEMA = "tautline-snapshot-pin/v1"

SNAPSHOT_DEFAULT_KEEP = 3

SNAPSHOT_DEFAULT_PIN_TTL_HOURS = 72

def _make_snapshot_read_only(root: Path) -> None:
    """Files 0444 (0555 when executable), directories 0555, applied bottom-up.

    Bottom-up matters: locking a directory before its contents would leave the file pass unable to
    walk into it.

    The ROOT directory's own mode is deliberately LEFT ALONE, and that is not an oversight. A
    directory that moves to a new parent has its `..` entry rewritten by rename(2), which requires
    write permission ON THE DIRECTORY BEING MOVED -- so a 0555 staging root cannot be published
    into the store at all (EACCES; verified on darwin, documented on linux). Callers lock the root
    themselves once the tree is in its final place: materialize after the publish rename, prune
    (transitively) never, because it is tearing the tree down.
    """
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            path = Path(dirpath) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        if Path(dirpath) != root:
            Path(dirpath).chmod(0o555)

def _rmtree_force(path: Path) -> None:
    """Delete a tree that may be read-only: restore the write bits top-down, then remove.

    The ONLY sanctioned way to remove a snapshot or a staging tree. `shutil.rmtree` alone cannot
    unlink a child of a 0555 directory, and with ignore_errors=True it does not even complain --
    it just leaves the tree behind, so a leak looks exactly like a clean exit.
    """
    for dirpath, _dirnames, filenames in os.walk(path):
        try:
            Path(dirpath).chmod(0o755)
        except OSError:
            continue
        for name in filenames:
            try:
                (Path(dirpath) / name).chmod(0o644)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)

def _reject_unsafe_tar_members(archive: tarfile.TarFile) -> None:
    """Refuse anything that could write outside the staging tree, or point out of it afterwards.

    Links are rejected outright. The 3.12 `data` filter CONTAINS link targets; this check has to
    hold on 3.10/3.11 too, where nothing contains them, and a link whose target escapes the tree
    would let the read-only chmod pass -- or a later exec -- follow it out of the store. The
    release tree ships no links at all (`git ls-files -s` has no 120000 entries), so rejecting them
    costs nothing and closes the class.
    """
    for member in archive.getmembers():
        if member.islnk() or member.issym():
            raise tarfile.TarError(f"refusing link archive member: {member.name}")
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise tarfile.TarError(f"refusing unsafe archive member: {member.name}")

def _safe_extract_methodology_tar(tar_path: Path, staging: Path) -> None:
    """Containment-checked extraction of a `git archive` export.

    extractall(filter="data") needs Python 3.12+ and this repo supports 3.10, so the member check
    above runs on EVERY interpreter and the filter is layered on top where it exists.
    """
    with tarfile.open(tar_path) as archive:
        _reject_unsafe_tar_members(archive)
        if sys.version_info >= (3, 12):
            archive.extractall(staging, filter="data")
        else:
            archive.extractall(staging)  # members validated above

def _retire_store_snapshot_dir(snap: Path) -> bool:
    """Take a published snapshot out of the store and destroy it. True when it is gone.

    Retiring is the ATOMIC step (a rename out of the store, under the caller's store lock); the
    tree removal that follows is bookkeeping. A published root is 0555 and rename(2) needs write
    permission on a directory it re-parents, so the root must be unsealed first or every retirement
    silently no-ops with EACCES -- and _rmtree_force, never rmtree, is the only thing that can
    remove the 0555 tree once it has been moved aside.
    """
    store = snap.parent
    doomed = store / ".tmp" / f"deleting-{snap.name}-{os.getpid()}"
    try:
        (store / ".tmp").mkdir(parents=True, exist_ok=True)
        snap.chmod(0o755)
        os.rename(snap, doomed)
    except OSError:
        return False
    _rmtree_force(doomed)
    return True

METHODOLOGY_SYNC_STAMP_SCHEMA = "tautline-methodology-sync-stamp/v1"

METHODOLOGY_SYNC_DEFAULT_FRESHNESS_MINUTES = 10

def print_context_rotation_status(data: dict) -> None:
    rotation = data["contextRotation"]
    print(
        "context_rotation: "
        f"enabled={str(rotation['enabled']).lower()} "
        f"soft={rotation['softPercent']} hard={rotation['hardPercent']} "
        f"heartbeat={rotation['heartbeatMinutes']}m boundary={rotation['heartbeatBoundary']} "
        f"safe_boundaries={','.join(rotation['safeBoundaries'])}"
    )
    print(
        "context_rotation_instruction: At PR/milestone/goal boundaries and long `/goal` heartbeats, visible context "
        "at or above soft threshold means refresh continuity/session journal, compact/restart, then resume the active "
        "goal; hard threshold requires rotation at the next safe boundary without further deferral. If the agent cannot "
        "invoke the host compaction command directly, write the continuity/session-journal evidence and state the exact "
        "fresh-session startup action without asking the human operator whether to compact or continue."
    )

def plan_review_evidence_body(manifest: dict, manifest_rel: str) -> str:
    findings = manifest.get("classified_findings", [])
    finding_count = len(findings) if isinstance(findings, list) else 0
    # A past-target round is only legitimate because a reason was RECORDED, so the reason belongs on
    # the surface humans actually read -- the plan's committed evidence block, which is what shows
    # up in review. Without it a reader sees round R3/R4 with no justification and has to open the
    # JSON. Rendered only when present, so a plan that converged within the target stays byte-
    # identical.
    exception_note = " ".join(str(manifest.get("exception_note") or "").split())
    exception_line = f"- Exception: `{exception_note}`\n" if exception_note else ""
    return (
        f"- Manifest: `{manifest_rel}`\n"
        f"- Recorded By: `{manifest['recorded_by']}`\n"
        f"- Plan SHA256: `{manifest['plan_content_sha256']}`\n"
        f"- Reviewer: `{manifest['reviewer']}` / `{manifest.get('reviewer_model', 'unknown')}` / round `{manifest['round']}`\n"
        f"{exception_line}"
        f"- Review command: `{manifest['review_command']}`\n"
        f"- Log: `{manifest['log_path']}`\n"
        f"- Log SHA256: `{manifest['log_sha256']}`\n"
        f"- Run Metadata: `{manifest.get('review_run_meta_path', 'missing')}`\n"
        f"- Run Metadata SHA256: `{manifest.get('review_run_meta_sha256', 'missing')}`\n"
        f"- Verdict: `{manifest['verdict']}`\n"
        f"- Unresolved Critical/P1: `{manifest['unresolved_critical_count']}` / `{manifest['unresolved_p1_count']}`\n"
        f"- Classified findings: `{finding_count}`\n"
        f"- Precheck: `tautline plan-finalization-precheck --target . --plan {manifest['plan_path']}`\n"
    )

def parse_classified_findings(value: str | None) -> list[dict]:
    """Parse the inline `--classified-findings-json` value into finding objects.

    Deliberately permissive: this is the parse boundary, and the validators own the rules. It is
    no longer an undocumented free-form dict, though. The recorded shape is

        {id, severity, status, summary, ac_ref, disposition, routed_to?,
         deferral_rationale?, acceptance_criterion?}

    where `status` is the round vocabulary (including `deferred`) and `disposition` is how the
    finding LEAVES the item (`fixed`/`routed`/`refuted`, never `deferred`). Requiredness differs
    by path and is enforced elsewhere -- `classified_finding_ac_errors` and
    `classified_finding_open_ac_errors` on the implementation path,
    `critical_origin_deferral_errors` on both. The full contract, including which verbs take a
    PATH and which take inline JSON, is documented at
    `docs/reference/operations/cli-operations.md`, Classified-Findings Contract.
    """
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--classified-findings-json must be JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise SystemExit("--classified-findings-json must be a JSON array")
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise SystemExit(f"--classified-findings-json item {index} must be an object")
    return parsed

def codex_plan_wrapper(data: dict) -> str:
    return str(data["review"].get("codexPlanWrapper") or data["review"]["codexWrapper"]).strip()

def review_tokens_bind_plan(tokens: list[str], plan_rel: str, plan_hash: str) -> bool:
    allowed = {plan_rel, plan_hash}
    for index, token in enumerate(tokens):
        if token == "--plan" and index + 1 < len(tokens) and tokens[index + 1] in allowed:
            return True
        if token.startswith("--plan=") and token.split("=", 1)[1] in allowed:
            return True
    return False

def plan_review_run_meta_frame_nonce(meta_path: Path | None) -> str | None:
    """This run's frame nonce from its run meta, or None when the record predates the frame."""
    if meta_path is None:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    nonce = str(meta.get("log_frame_nonce") or "").strip()
    return nonce or None

BEHAVIOR_PENDING_CANONICAL_FORM = "@pending @owner:<goal-or-lane> @reason:<why> @unpend:<trigger>"
"""The machine-checkable annotation for an inactive scenario.

Published so authors stop discovering the format by trial. It is a strict SUBSET of the legacy
prose tokens accepted below -- "@owner:" contains "owner:", "@unpend:" contains "unpend" -- so
adopting it never breaks an existing gate and no existing annotation breaks under it.
"""

BEHAVIOR_PENDING_OWNER_TOKENS = ("owner:",)
BEHAVIOR_PENDING_TRIGGER_TOKENS = ("un-pend", "unpend", "trigger:", "remove @pending when")

def behavior_pending_missing_metadata(context: str) -> list[str]:
    """Which of owner / un-pend trigger a `@pending` scenario's context is missing.

    THE single definition of the owner+un-pend rule. It previously existed only as inline string
    checks duplicated between `behavior_spec_status_record` and the codex-run review block -- two
    copies of an unpublished rule, which is the mechanism behind the RCA's "no documented tag
    spec" clause: authors could not read the rule anywhere, and the two copies were free to drift
    apart. Both call sites now route through here, so there is one rule and it has a name.
    """
    lowered = str(context).lower()
    missing: list[str] = []
    if not any(token in lowered for token in BEHAVIOR_PENDING_OWNER_TOKENS):
        missing.append("owner")
    if not any(token in lowered for token in BEHAVIOR_PENDING_TRIGGER_TOKENS):
        missing.append("un-pend trigger")
    return missing

def _behavior_glob_segments_match(rel_parts: tuple[str, ...], pat_parts: tuple[str, ...]) -> bool:
    """`Path.glob` semantics: `**` spans zero or more segments, `*`/`?`/`[]` never cross `/`.

    `fnmatch.fnmatch(rel, pattern)` is NOT equivalent and fails in both directions -- it treats
    `/` as an ordinary character, so `*.feature` wrongly matches `x/a.feature` while
    `**/*.feature` wrongly fails to match a root-level `a.feature` that `Path.glob` does match.
    Either direction silently rescopes the adapter. `PurePath.full_match` would do this in one
    line but is 3.13+; this package still supports 3.12.
    """
    if not pat_parts:
        return not rel_parts
    head, rest = pat_parts[0], pat_parts[1:]
    if head == "**":
        return any(
            _behavior_glob_segments_match(rel_parts[i:], rest)
            for i in range(len(rel_parts) + 1)
        )
    if not rel_parts:
        return False
    return fnmatch.fnmatchcase(rel_parts[0], head) and _behavior_glob_segments_match(
        rel_parts[1:], rest
    )

def behavior_feature_pattern_participates(pattern: str) -> bool:
    """Whether a `behaviorSpecs.paths` entry addresses feature files at all."""
    return ".feature" in pattern or "/features" in f"/{pattern}" or pattern.endswith("features/**")

def behavior_feature_path_selected(data: dict, rel: str) -> bool:
    """Whether `rel` (target-relative, `/`-separated) is in behaviorSpecs scope.

    Invariant I4: revision-scoped discovery cannot glob a tree it does not have checked out, so it
    needs a path predicate -- and that predicate must select exactly what `behavior_feature_files`
    globs, or scope drifts between the two. They share this one function so they cannot.
    """
    rel = str(rel).strip().replace("\\", "/")
    # Strip an exact "./" prefix only. `lstrip("./")` is character-wise, so it eats the leading
    # dot of a hidden directory: ".features/a.feature" would become "features/a.feature", and the
    # predicate would then select it for the pattern "features/**" while missing ".features/**".
    # That is scope drift against behavior_feature_files, which is what invariant I4 forbids.
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel.endswith(".feature"):
        return False
    rel_parts = tuple(part for part in rel.split("/") if part)
    for raw_pattern in data.get("behaviorSpecs", {}).get("paths", []):
        pattern = str(raw_pattern).strip().replace("\\", "/")
        # The pattern gets the SAME "./"-prefix normalization as the path. `Path.glob("./x/**")`
        # resolves the "./" away and matches x/a.feature, so a predicate that kept "." as a
        # literal segment would return False for a file the glob selects -- the same drift, just
        # entering from the pattern side instead of the path side.
        while pattern.startswith("./"):
            pattern = pattern[2:]
        if not pattern or not behavior_feature_pattern_participates(pattern):
            continue
        pat_parts = tuple(part for part in pattern.rstrip("/").split("/") if part)
        # Some patterns are DIRECTORY-ONLY: `Path.glob` returns only directories for them, and
        # `behavior_feature_files` then rglobs beneath. Such a pattern can never select a file
        # directly -- it reaches files only through an ancestor -- so matching the file path
        # against it would widen scope, the worse drift direction for a gate. Measured on 3.12,
        # against a tree holding features/a.feature and features/group/b.feature:
        #     "features/*/"   -> ['features/group']                (directories only)
        #     "features/*/**" -> ['features/group']                (directories only)
        #     "features/**"   -> ['features', 'features/group']    (directories only)
        #     "features/**/*.feature" -> both .feature files       (files -- not directory-only)
        # The rule behind all four: a pattern is directory-only when it ends in "/" or when its
        # last segment is "**". A trailing "**" is not a wildcard for files; it names the
        # directories to descend into.
        directory_only = pattern.endswith("/") or (bool(pat_parts) and pat_parts[-1] == "**")
        # `behavior_feature_files` has TWO ways to select a file, and the predicate must mirror
        # both or it under-scopes: the glob matches the FILE, or the glob matches a DIRECTORY and
        # every `.feature` beneath it is rglob'd in. So a path is in scope when the pattern matches
        # it, or when the pattern matches any of its ancestor directories. Stating it that way
        # subsumes the special cases this used to enumerate (a magic-free directory prefix,
        # `dir/**`, `dir/*`) -- each was one instance of "the pattern matched an ancestor".
        if not directory_only and _behavior_glob_segments_match(rel_parts, pat_parts):
            return True
        if any(
            _behavior_glob_segments_match(rel_parts[:depth], pat_parts)
            for depth in range(1, len(rel_parts))
        ):
            return True
    return False

def behavior_feature_files(data: dict, target: Path) -> list[Path]:
    behavior = data.get("behaviorSpecs", {})
    files: set[Path] = set()
    for raw_pattern in behavior.get("paths", []):
        pattern = str(raw_pattern).strip()
        if not pattern:
            continue
        normalized = pattern.replace("\\", "/")
        if behavior_feature_pattern_participates(normalized):
            for candidate in target.glob(normalized):
                if candidate.is_file() and candidate.suffix == ".feature":
                    files.add(candidate)
                elif candidate.is_dir():
                    files.update(path for path in candidate.rglob("*.feature") if path.is_file())
    return sorted(files)

def critical_journey_feature_files(journey: dict, target: Path) -> list[Path]:
    """Resolve a critical journey's featurePaths (file / dir / glob) to .feature files under target."""
    files: set[Path] = set()
    for raw in journey.get("featurePaths", []):
        pattern = str(raw).strip().replace("\\", "/")
        if not pattern:
            continue
        for candidate in target.glob(pattern):
            if candidate.is_file() and candidate.suffix == ".feature":
                files.add(candidate)
            elif candidate.is_dir():
                files.update(path for path in candidate.rglob("*.feature") if path.is_file())
    return sorted(files)

def normalize_critical_journeys(data: dict) -> list[dict]:
    """Validate the optional criticalJourneys block: each is {name, featurePaths[]}. Type-checks; an
    absent block is simply []."""
    raw = data.get("criticalJourneys")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SystemExit("Project adapter criticalJourneys must be an array")
    norm: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise SystemExit("Project adapter criticalJourneys[] entries must be objects")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SystemExit("Project adapter criticalJourneys[].name must be a non-blank string")
        paths = entry.get("featurePaths", [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or not p.strip() for p in paths):
            raise SystemExit("Project adapter criticalJourneys[].featurePaths must be an array of non-blank strings")
        norm.append({**entry, "name": name.strip(), "featurePaths": [p.strip() for p in paths]})
    return norm

#: Revision sentinel for "the staged tree" -- what a pre-commit gate must read. Not a git
#: revision, so every helper that accepts a revision maps it to `--cached` / `:<path>` explicitly.
BEHAVIOR_REVISION_INDEX = ":index:"

class BehaviorRevisionUnavailable(Exception):
    """git could not list or diff a revision. Distinct from "the revision has no feature files"."""

def behavior_feature_paths_at_revision(data: dict, target: Path, revision: str) -> list[str]:
    """Target-relative `.feature` paths in scope at `revision` (or the index).

    Cannot glob: a git tree object has no filesystem to walk. Discovery therefore lists the tree
    and filters through `behavior_feature_path_selected` -- the SAME predicate `behavior_feature_files`
    is pinned equal to -- so revision-scoped discovery cannot select a wider set than the adapter
    configured (invariant I4).

    Raises rather than returning [] on a git failure, because those two are not the same answer and
    the caller has to be able to tell them apart in order to warn. The CALLER fails open (invariant
    I5); swallowing it here would make the gate print the same thing when it is working and when it
    is blind.
    """
    if revision == BEHAVIOR_REVISION_INDEX:
        out = run_git(target, ["ls-files", "--cached", "-z", "--", "*.feature"])
    else:
        out = run_git(target, ["ls-tree", "-r", "--name-only", "-z", revision])
    if out == "unavailable":
        raise BehaviorRevisionUnavailable(revision)
    if out == "":
        return []
    names = [name for name in out.split("\0") if name]
    return sorted(
        name for name in (n.replace("\\", "/") for n in names)
        if behavior_feature_path_selected(data, name)
    )

def behavior_feature_text_at_revision(target: Path, revision: str, rel: str) -> str | None:
    """The text of `rel` at `revision` (or staged), or None when git cannot produce it.

    None is a REPORTED degradation, never a silent skip: a gate that cannot read the tree it is
    supposed to police must say so rather than pass quietly, which is how a control becomes
    decorative.

    Reads through `git_object_bytes` (`git cat-file blob`) rather than `run_git`, because `run_git`
    STRIPS its output. Stripping a feature file's leading blank lines shifts every line number
    below them, so the spans parsed here would no longer line up with the diff ranges they are
    about to be intersected against -- invariant I1 broken by the very helper written to enforce
    it, and silently, since nothing about the result would look wrong.
    """
    # `git ls-files --relative` and `git diff --relative` key by TARGET-relative path, but a blob
    # spec is resolved from the REPOSITORY root. Below a subdirectory target the two disagree, so
    # every staged feature would read as unreadable and the check would fail open on exactly the
    # repos that configured a sub-path. `:./x` / `<rev>:./x` are cwd-relative forms, and
    # git_object_bytes runs with `-C target`.
    spec = f":./{rel}" if revision == BEHAVIOR_REVISION_INDEX else f"{revision}:./{rel}"
    raw = git_object_bytes(target, spec)
    return None if raw is None else raw.decode("utf-8", errors="replace")

def _scenario_rel(scenario: dict, target: Path) -> str:
    raw = Path(scenario["path"])
    if raw.is_absolute():
        try:
            return str(raw.relative_to(target)).replace("\\", "/")
        except ValueError:
            return str(raw).replace("\\", "/")
    return str(scenario["path"]).replace("\\", "/")

def behavior_delta_findings(
    tip_scenarios: list[dict],
    base_scenarios: list[dict],
    target: Path,
    rename_sources: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """`(added_inactive, offending)` by comparing the tip's inactive scenarios against the base's.

    This USED to intersect each scenario's span with the diff's added line ranges, and that proxy
    was wrong in both directions -- the R1 review found one instance of each:

    * a pure deletion immediately above a pre-existing noncompliant scenario anchored a touched
      point on the scenario's new first line, so untouched debt read as introduced and the gate
      refused. Pre-existing debt blocking is invariant I3, the one thing this must never do; and
    * a `@pending` staged above an existing `Feature:` makes every scenario in the file inactive,
      but the only added range is the tag line at the top, which intersects no scenario span -- so
      a file's worth of newly inactive scenarios passed silently.

    Line ranges answer "did the diff touch these lines". The question is "did this change introduce
    this debt", and comparing the two revisions' scenario sets answers it directly. A scenario
    counts as introduced when the base has no matching one -- matched as a MULTISET on
    `(path, name)`, so adding a second noncompliant scenario with a name already present is still
    caught.

    `rename_sources` maps a tip path to the base path it moved from, so a file renamed BETWEEN two
    in-scope paths finds its own history and introduces nothing, while one renamed IN from outside
    scope has no base entry and introduces everything (invariant I3, both directions).

    `added_inactive` is EVERY newly inactive scenario, compliant or not -- that is the growth signal
    the RCA says is missing, and deriving it from the offending list alone would report zero for a
    change that added a perfectly annotated `@pending`. `offending` is the subset lacking required
    metadata: the only ones any gate may block on.

    A scenario RENAMED in place counts as introduced, because its old name is gone and its new one
    is new. That is deliberate: editing a scenario's title is touching it, and the author is in the
    best position to annotate it.
    """
    rename_sources = rename_sources or {}

    def noncompliant(scenario: dict) -> bool:
        return bool(behavior_pending_missing_metadata(scenario.get("context", "")))

    # Instances sharing a (path, name) are paired IN LINE ORDER, and compliance is read off the
    # resulting pairs. Two earlier shapes both failed, in opposite directions:
    #
    #   * two INDEPENDENT multiset comparisons -- one over all pending scenarios, one pre-filtered
    #     to the noncompliant ones -- let pre-existing debt absorb a new scenario sharing its name:
    #     annotate the old one, add an unannotated duplicate, and the filtered comparison pairs the
    #     new debt with the old and reports nothing (R2); and
    #   * one comparison that always consumed a COMPLIANT base instance first falsely refused an
    #     UNCHANGED tree whose file happens to hold an unannotated and an annotated scenario of the
    #     same name, because the unannotated tip instance took the annotated base one and read as a
    #     metadata removal (R3).
    #
    # Line order resolves both without a heuristic: an unchanged tree pairs each instance with
    # itself, a metadata deletion pairs a scenario with its own former self, and a genuinely new
    # duplicate is the one left over. Names are the only stable identity a Gherkin scenario has --
    # line numbers move and text is what changed -- so ordering by line is the tie-break, not the
    # key.
    base_buckets: dict[tuple[str, str], list[dict]] = {}
    for scenario in base_scenarios:
        key = (_scenario_rel(scenario, target), str(scenario.get("name", "")))
        base_buckets.setdefault(key, []).append(scenario)
    for bucket in base_buckets.values():
        bucket.sort(key=lambda s: int(s.get("line", 0) or 0))

    tip_buckets: dict[tuple[str, str], list[dict]] = {}
    for scenario in tip_scenarios:
        rel = _scenario_rel(scenario, target)
        key = (rename_sources.get(rel, rel), str(scenario.get("name", "")))
        tip_buckets.setdefault(key, []).append(scenario)

    added_inactive: list[dict] = []
    offending: list[dict] = []
    for key, tips in tip_buckets.items():
        bases = base_buckets.get(key, [])
        for index, scenario in enumerate(sorted(tips, key=lambda s: int(s.get("line", 0) or 0))):
            if index >= len(bases):
                # No counterpart at base: new. Compliant ones are still growth, which is the number
                # delta reporting exists to publish.
                added_inactive.append(scenario)
                if noncompliant(scenario):
                    offending.append(scenario)
                continue
            if not noncompliant(bases[index]) and noncompliant(scenario):
                # The scenario existed and was annotated; this change removed its metadata. Debt
                # introduced WITHOUT a scenario being introduced -- which is why `offending` is
                # deliberately not a subset of `added_inactive`. This is the case R1's zero-count
                # deletion anchor existed to catch, now measured rather than inferred from an
                # adjacent line number.
                offending.append(scenario)
    return added_inactive, offending

def _unquote_git_path(name: str) -> str:
    """Decode one C-quoted path as git emits it under the default `core.quotePath`.

    Applied to `+++` headers AND to `rename from`/`rename to` headers. It was applied to only the
    first, so a non-ASCII rename kept its quotes and escapes, the scope predicate did not recognise
    the destination, and -- since a 100% rename carries no hunk -- moving an unannotated feature
    file into scope produced nothing at all and passed.
    """
    name = name.strip()
    if not (name.startswith('"') and name.endswith('"') and len(name) >= 2):
        return name
    try:
        decoded = name[1:-1].encode("ascii", "backslashreplace").decode("unicode_escape")
        return decoded.encode("latin-1", "ignore").decode("utf-8", errors="replace")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name[1:-1]

def parse_diff_rename_pairs(diff_text: str) -> list[tuple[str, str]]:
    """`(source, destination)` for every rename in a diff, both paths unquoted.

    A rename emits headers and no `@@` hunk, so the destination carries no ranges of its own.
    Whether it is "new content" depends on where it came from: moving a file INTO
    `behaviorSpecs.paths` brings its debt to the gate for the first time, while moving it BETWEEN
    two in-scope paths brings nothing -- and `--no-renames`, which fixes the first, breaks the
    second by expanding every rename into a full-file addition and blocking on pre-existing debt
    (invariant I3). The caller needs the pair to tell them apart.
    """
    pairs: list[tuple[str, str]] = []
    source: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("rename from "):
            source = _unquote_git_path(line[len("rename from "):])
        elif line.startswith("rename to ") and source is not None:
            pairs.append((source, _unquote_git_path(line[len("rename to "):])))
            source = None
    return pairs

def parse_added_line_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """HEAD-side added/modified line ranges per file, parsed from a `--unified=0` diff.

    Factored out so the revision-scoped gates and the existing `git_added_line_ranges` share ONE
    hunk parser; two parsers over the same format is a divergence waiting for a `--relative` or
    rename-header edge case to land on only one of them.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            # Under the default core.quotePath, a non-ASCII path arrives C-escaped and quoted.
            # Storing the escaped text as the range key means it never matches the Unicode filename
            # discovery returns, so a newly added unannotated scenario in such a file is invisible.
            name = _unquote_git_path(line[4:])
            if name.startswith("b/"):
                current = name[2:]
            elif name == "/dev/null":
                current = None
            else:
                current = name
        elif line.startswith("@@") and current:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) is not None else 1
                # A pure DELETION renders as `+N,0`: nothing was added on the tip side, so there is
                # no added range to record. An earlier version anchored a touched point at `start`
                # to catch metadata deleted from a compliant scenario -- but `start` is simply the
                # line the removal sits against, so a deletion of unrelated content immediately
                # above a PRE-EXISTING noncompliant scenario marked that scenario touched and the
                # gate refused. That is invariant I3 broken, in a gate shared with `codex-run`.
                # Debt introduced by deletion is now caught by comparing the base and tip scenario
                # sets (`behavior_delta_findings`), which measures it directly instead of guessing
                # from adjacency.
                if count > 0:
                    ranges.setdefault(current, []).append((start, start + count - 1))
    return ranges

def git_diff_text_at(target: Path, base: str, tip: str) -> str:
    """The `--unified=0` diff between `base` and `tip`, where `tip` may be the index sentinel.

    The tip is a PARAMETER, not `HEAD`. Invariant I2 requires the pushed tip to be whatever the ref
    records say -- `git push origin other:other`, a multi-ref push, or a push from a different
    checkout all make `HEAD` the wrong answer.

    `diff.mnemonicPrefix` is pinned off so the parser sees one prefix shape; with it on, a staged
    diff uses `i/` and `w/` rather than `a/` and `b/` and every path key is wrong.

    Rename detection is pinned ON for the same reason. An adopter with `diff.renames=false` gets
    delete/add records instead of rename headers, `behavior_rename_sources` finds no mapping, and
    a file moved between two configured feature paths makes every pre-existing unannotated
    scenario in it look new -- a false refusal produced by the adopter's git config rather than by
    their change. Neither of these may depend on how the consumer has configured git.
    """
    if tip == BEHAVIOR_REVISION_INDEX:
        out = run_git(
            target,
            ["-c", "diff.mnemonicPrefix=false", "-c", "diff.renames=true", "diff", "--cached",
             "--find-renames", "--relative", "--unified=0"],
        )
    else:
        out = run_git(
            target,
            ["-c", "diff.mnemonicPrefix=false", "-c", "diff.renames=true", "diff",
             "--find-renames", "--relative", "--unified=0", f"{base}...{tip}"],
        )
    if out == "unavailable":
        raise BehaviorRevisionUnavailable(f"diff {base}...{tip}")
    return out

def behavior_rename_sources(data: dict, diff_text: str) -> dict[str, str]:
    """Tip path -> the base path it was renamed from, for in-scope destinations only.

    Lets the base lookup follow a file that moved. A rename BETWEEN two in-scope paths finds its
    own history and introduces nothing; a rename IN from outside scope has no base entry under the
    destination and introduces everything it carries (invariant I3, both directions).
    """
    sources: dict[str, str] = {}
    for source, destination in parse_diff_rename_pairs(diff_text):
        destination = destination.replace("\\", "/")
        if behavior_feature_path_selected(data, destination):
            sources[destination] = source.replace("\\", "/")
    return sources

def behavior_pending_scenarios_at_revision(
    data: dict, target: Path, revision: str
) -> tuple[list[dict], list[str]]:
    """`(scenarios, unreadable_rels)` for every in-scope feature file at one revision.

    Both halves matter. The scenarios are parsed from the same tree object the caller will compute
    its added-line ranges against (invariant I1), and `unreadable_rels` is what lets the caller
    report a degraded read instead of treating "git could not answer" as "no pending debt here".
    """
    scenarios: list[dict] = []
    unreadable: list[str] = []
    # Normalized exactly as behavior_spec_status_record does. A valid `[" @pending "]` that the
    # status check honours but this gate ignored would mean two enforcement answers for one
    # adapter.
    pending_tags = [
        str(tag).strip()
        for tag in data.get("behaviorSpecs", {}).get("pendingTags", ["@pending"])
        if str(tag).strip()
    ]
    try:
        rels = behavior_feature_paths_at_revision(data, target, revision)
    except BehaviorRevisionUnavailable:
        # Reported, not swallowed: the caller prints a warning and exits 0 (invariant I5).
        return [], [f"<listing at {revision}>"]
    for rel in rels:
        text = behavior_feature_text_at_revision(target, revision, rel)
        if text is None:
            unreadable.append(rel)
            continue
        scenarios.extend(
            behavior_pending_scenarios_from_text(text, pending_tags, target / rel)
        )
    return scenarios, unreadable

def behavior_pending_scenarios(path: Path, pending_tags: list[str]) -> list[dict]:
    """Inactive scenarios in the WORKTREE copy of `path`. Unchanged behaviour; the parsing now
    lives in `behavior_pending_scenarios_from_text` so a caller can supply text from a git tree
    object instead (invariant I1: spans and diff ranges must come from the SAME revision)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return behavior_pending_scenarios_from_text(text, pending_tags, path)

def behavior_pending_scenarios_from_text(
    text: str, pending_tags: list[str], path: Path
) -> list[dict]:
    """Parse inactive scenarios out of feature-file TEXT, labelling them with `path`.

    Split out from `behavior_pending_scenarios` so revision-scoped gates can parse a blob read
    from a git tree object. Reading text from the worktree while computing added-line ranges from
    a commit range is invariant I1's failure: an uncommitted edit above a scenario shifts its span
    relative to the diff, so on a repo carrying pre-existing metadata-less debt a scenario the
    diff never touched can slide into an added range and hard-refuse the push.
    """
    pending = {tag.lower() for tag in pending_tags}
    lines = text.splitlines()
    feature_pending = False
    tag_block: list[tuple[int, str]] = []
    scenarios: list[dict] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            tag_block.append((index + 1, stripped))
            continue
        lower = stripped.lower()
        if lower.startswith("feature:"):
            feature_pending = any(tag.lower() in pending for _line_no, tag_line in tag_block for tag in tag_line.split())
            tag_block = []
            continue
        if lower.startswith("scenario:") or lower.startswith("scenario outline:"):
            scenario_pending = feature_pending or any(
                tag.lower() in pending
                for _line_no, tag_line in tag_block
                for tag in tag_line.split()
            )
            if scenario_pending:
                name = stripped.split(":", 1)[1].strip() if ":" in stripped else stripped
                tag_line_numbers = [line_no for line_no, _tag_line in tag_block] or [index + 1]
                context_start = max(0, min(tag_line_numbers) - 3)
                context_end = min(len(lines), index + 6)
                context = "\n".join(lines[context_start:context_end])
                scenarios.append(
                    {
                        "path": path,
                        "line": index + 1,
                        "name": name,
                        "context": context,
                        # 1-based, inclusive span from the first @pending tag through the body
                        # window the metadata check inspects. Diff-scoping (RCA 20260615T071304Z)
                        # tests membership against this span, not just the Scenario: line, so a diff
                        # that pends an existing scenario (adds only the tag above it) or edits the
                        # inactive scenario's body still counts as introduced-by-this-diff.
                        "spanStart": min(tag_line_numbers),
                        "spanEnd": context_end,
                    }
                )
            tag_block = []
            continue
        tag_block = []
    return scenarios

def behavior_not_applicable_line_has_reason(line: str, source: str, terms: list[str]) -> bool:
    normalized_line = line.replace("\\", "/")
    normalized_source = source.replace("\\", "/")
    source_index = normalized_line.lower().find(normalized_source.lower())
    after_source = normalized_line[source_index + len(normalized_source) :] if source_index >= 0 else normalized_line
    term_pattern = re.compile(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b", re.IGNORECASE)
    match = term_pattern.search(after_source)
    if not match:
        return False
    reason = after_source[match.end() :].strip(" :-.")
    if not reason or "<reason>" in reason.lower() or reason.lower() in {"n/a", "na", "todo", "tbd"}:
        return False
    return len(reason) >= 8

def behavior_source_material_exemption_state(plan_text: str, marker: str) -> tuple[bool, str | None]:
    if not marker:
        return False, None
    for line in plan_text.splitlines():
        if marker not in line:
            continue
        reason = line.split(marker, 1)[1].strip()
        if not reason or "<reason>" in reason.lower() or reason.lower() in {"n/a", "na", "todo", "tbd"}:
            return False, f"behavior source material exemption `{marker}` must include a real reason, not the placeholder"
        if len(reason) < 8:
            return False, f"behavior source material exemption `{marker}` reason is too short"
        return True, None
    return False, None

def behavior_role_vocabulary_errors(data: dict, plan_text: str) -> list[str]:
    behavior = data.get("behaviorSpecs", {})
    role_vocabulary = behavior.get("roleVocabulary", {})
    forbidden = [
        str(value).strip()
        for value in role_vocabulary.get("forbidden", [])
        if str(value).strip()
    ]
    if not forbidden:
        return []
    scan_text = markdown_without_quoted_blocks(plan_text)
    errors: list[str] = []
    for term in forbidden:
        if re.search(rf"(?<![\w`/-]){re.escape(term)}(?![\w`/-])", scan_text, re.IGNORECASE):
            errors.append(f"forbidden behavior role term present in plan: {term}")
    return errors

def markdown_without_quoted_blocks(text: str) -> str:
    kept_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        kept_lines.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(kept_lines)

def plan_review_run_meta_path(log_path: Path) -> Path:
    return log_path.with_name(f"{log_path.name}.meta.json")

def load_plan_review_run_meta(log_path: Path) -> tuple[dict | None, Path, list[str]]:
    meta_path = plan_review_run_meta_path(log_path)
    if not meta_path.exists():
        return None, meta_path, [f"plan review run metadata missing: {meta_path}; run tautline run-plan-review"]
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")), meta_path, []
    except json.JSONDecodeError as exc:
        return None, meta_path, [f"plan review run metadata invalid JSON: {exc}"]

def load_plan_review_manifest(manifest_path: Path) -> dict | None:
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None

def plan_review_chain_summary(members: list[dict], truncated: bool) -> dict:
    """Chain totals with an explicit honesty marker.

    `evidence` is `floor` whenever any member's spend was unrecoverable or the walk was cut short,
    so a persisted or printed total can never masquerade as exact.
    """
    known = [
        member["recorded_rounds"] for member in members if member["recorded_rounds"] is not None
    ]
    unknown_members = len(members) - len(known)
    return {
        "depth": len(members),
        "cumulative_recorded_rounds": sum(known),
        "unknown_members": unknown_members,
        "truncated": bool(truncated),
        "evidence": "floor" if unknown_members or truncated else "exact",
    }

def plan_review_chain_total_display(summary: dict) -> str:
    """The cumulative total, prefixed `>=` when the walk could only establish a floor."""
    total = summary["cumulative_recorded_rounds"]
    return f">={total}" if summary.get("evidence") == "floor" else str(total)

def plan_review_chain_members_display(members: list[dict]) -> str:
    return "->".join(
        f"{member['plan_path']}:"
        f"{'?' if member['recorded_rounds'] is None else member['recorded_rounds']}"
        for member in members
    )

def plan_review_chain_ledger_line(summary: dict, members: list[dict]) -> str:
    """The chain's running total at launch, on the round ledger's before-this-run semantics."""
    line = (
        "plan_review_chain_ledger: "
        f"depth={summary['depth']} "
        f"cumulative_recorded_rounds={plan_review_chain_total_display(summary)} "
        f"unknown_members={summary['unknown_members']} "
        f"evidence={summary['evidence']}"
    )
    if summary.get("truncated"):
        line += " truncated=true"
    return f"{line} members={plan_review_chain_members_display(members)}"

def plan_review_chain_status_line(manifest: dict) -> str:
    """The finalized chain record, read from the manifest -- never from a fresh filesystem walk.

    A run meta landing between the launch and the finalize would make a recomputed status
    contradict the manifest it is printed beside. The counts here and the counts on disk are the
    same numbers by construction; the refreshed members list is printed separately and labelled.
    """
    predecessor = str((manifest or {}).get("predecessor_plan_path") or "").strip()
    if not predecessor:
        return ""
    parts = [f"depth={manifest.get('chain_depth', '?')}"]
    parts.append(f"chain_recorded_rounds={manifest.get('chain_recorded_rounds', '?')}")
    parts.append(f"unknown_members={manifest.get('chain_unknown_members', '?')}")
    parts.append(f"evidence={manifest.get('chain_evidence', 'unknown')}")
    parts.append(f"predecessor={predecessor}")
    return "plan_review_chain_status: " + " ".join(parts)

def plan_review_chain_event_refs(manifest: dict) -> dict:
    """Chain facts for the `plan_review_finalized` event, as strings like the refs beside them.

    The honesty markers travel WITH the numbers: an event that carried `chain_recorded_rounds`
    alone would let a consumer read a floor total as an exact one, which is the exact substitution
    the persisted `chain_evidence` marker exists to prevent. Empty for a standalone plan.
    """
    if not str((manifest or {}).get("predecessor_plan_path") or "").strip():
        return {}
    return {
        key: str(manifest[key])
        for key in (
            "predecessor_plan_path",
            "chain_depth",
            "chain_recorded_rounds",
            "chain_evidence",
            "chain_unknown_members",
        )
        if key in manifest
    }

def plan_review_manifest_chain_fields(run_meta_path: Path, wrapper_exit_code: int) -> dict:
    """Lineage and chain fields for the manifest, carried from the BOUND run meta.

    Same carry-through discipline as the round ledger: never recount at finalize. The one derived
    value, `chain_recorded_rounds`, is the bound meta's prior total plus this bound run -- and only
    when this run actually succeeded, so a failed bind can never invent a successful round. A run
    meta without lineage yields {}, which keeps a standalone plan's manifest byte-identical.
    """
    try:
        meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    predecessor = str(meta.get("predecessor_plan_path") or "").strip()
    if not predecessor:
        return {}
    fields: dict = {"predecessor_plan_path": predecessor}
    for key in ("predecessor_manifest_path", "chain_evidence"):
        value = str(meta.get(key) or "").strip()
        if value:
            fields[key] = value
    for key in ("chain_depth", "chain_unknown_members"):
        try:
            fields[key] = int(meta[key])
        except (KeyError, TypeError, ValueError):
            continue
    try:
        prior = int(meta["chain_prior_recorded_rounds"])
    except (KeyError, TypeError, ValueError):
        prior = None
    if prior is not None:
        fields["chain_recorded_rounds"] = prior + (1 if int(wrapper_exit_code) == 0 else 0)
    return fields

def plan_review_run_meta_ledger_value(meta_path: Path, key: str) -> int | None:
    """An integer ledger field from a run meta, or None when the record does not carry it.

    Absent is the normal case for every run meta written before the ledger existed, so this
    never guesses a value.
    """
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or key not in meta:
        return None
    try:
        return int(meta[key])
    except (TypeError, ValueError):
        return None

def plan_review_run_meta_superseded_by_manifest(meta: dict, manifest: dict | None) -> bool:
    """True when the bound manifest already accounts for this run, so the run is NOT stranded.

    The manifest is a single-round file: it binds exactly ONE run-meta, so every earlier round's
    meta is orphaned the moment a later round finalizes. An orphan is not a voided run -- it was
    reviewed, finalized, and superseded. Only a run at or past the bound round can be a genuinely
    unfinalizable dead end.

    Fails CLOSED: when strandedness cannot be proven (unparseable round or timestamp), this returns
    True, so the round falls back to requiring an explicit --exception-note. Refusing to
    self-authorize is always recoverable -- the operator records a real reason and takes the round.
    Self-authorizing on a fabricated reason is not: it is written verbatim into the hash-bound
    manifest as a false attestation.
    """
    if not manifest:
        return False
    bound_round = plan_review_round_number(str(manifest.get("round") or ""))
    meta_round = plan_review_round_number(str(meta.get("round") or ""))
    if bound_round is None or meta_round is None:
        return True
    if meta_round != bound_round:
        return meta_round < bound_round
    # Same round as the bound run but a different run-meta (the round was re-run): the finalization
    # supersedes any run that finished before the manifest was recorded.
    finished_at = plan_review_parse_timestamp(meta.get("finished_at"))
    recorded_at = plan_review_parse_timestamp(manifest.get("timestamp"))
    if finished_at is None or recorded_at is None:
        return True
    return finished_at <= recorded_at

def plan_review_parse_timestamp(value: object) -> datetime | None:
    """Offset-aware timestamp, else None. Naive values are rejected: they are not comparable."""
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed

def plan_review_successor_instruction(plan_rel: str) -> str:
    return (
        f"this plan's content changed after its final allowed review round ({plan_rel}); its "
        "review evidence cannot be rebound: create a successor source-of-truth plan (new file), "
        "carry all prior unresolved findings into it, mark this plan superseded, and run the "
        "capped review ceremony against the successor. Declare lineage on the successor's first "
        f"review run with `--predecessor {shlex.quote(plan_rel)}` so the chain's cumulative review "
        "spend is accounted -- it records the link and never blocks the succession. Do not edit "
        "`.plan-reviews` or retire run records."
    )

def guard_target_argument(target: Path) -> str:
    """Shell-quoted absolute target for command examples printed by the guards.

    `--target .` is ambiguous on a multi-agent machine: it names whatever checkout the agent
    happens to be sitting in, which may be a worktree owned by another lane. Every guard remedy
    renders the resolved target instead.
    """
    return shlex.quote(str(target.resolve(strict=False)))

# Board-as-source-of-truth safety rule #1 (2026-06-24 incident): a board is human-owned and
# read-authoritative; no agent or code path may mutate its STRUCTURE. These patterns match the
# board-structure mutations -- single-select option / field create-delete-edit (the exact
# `updateProjectV2Field` option-set rebuild that orphaned every card's Status), and item reorder.
# Per-item VALUE edits (`gh project item-edit`) and reads (`item-list`/`field-list`) are NOT here:
# value writes are the opt-in write path governed separately. A tuple (not a list) so this regex
# config stays out of the auto-collected policy-phrases SSOT.
# The line is CONTENT vs SCHEMA (operator clarification 2026-06-25): agents do normal developer work
# on board ITEMS -- move cards, change Status/field values, edit/comment issues, track milestones
# (`gh project item-*`, `gh issue *`, and the `updateProjectV2ItemFieldValue`/`addProjectV2ItemById`
# value mutations stay ALLOWED). Only board SCHEMA/structure is forbidden: fields, single-select
# options, item reorder, board-level create/delete/edit/copy/close, and views/workflow. The negative
# lookaheads on the board-level mutations are deliberate so the allowed item-value variants
# (updateProjectV2ItemFieldValue, deleteProjectV2Item, ...) are NOT caught.
BOARD_STRUCTURE_MUTATION_PATTERNS = (
    r"\bgh\s+project\s+field-(?:create|delete|edit)\b",
    r"\bgh\s+project\s+(?:delete|edit|copy|close|create)\b",
    r"updateprojectv2field",
    r"createprojectv2field",
    r"deleteprojectv2field",
    r"updateprojectv2itemposition",
    r"updateprojectv2(?![a-z])",
    r"createprojectv2(?![a-z])",
    r"deleteprojectv2(?![a-z])",
    r"copyprojectv2(?![a-z])",
    r"(?:create|update|delete)projectv2view",
    # A GraphQL query loaded from a file/stdin (`query=@file`, `query=@-`) can hide a schema mutation
    # from this guard, so it cannot be inspected -- block it; agents inline board queries.
    r"\bgh\s+api\s+graphql\b[^\n]*query=@",
)

def command_mutates_board_structure(command: str) -> bool:
    if not command:
        return False
    scan = (
        command.replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .lower()
    )
    return any(re.search(pattern, scan) for pattern in BOARD_STRUCTURE_MUTATION_PATTERNS)

# Tier-2 item-content protection (board-item-updates skill): an issue's title/summary, body (which
# holds the acceptance criteria), labels, and milestone are stakeholder-authored. An agent edits them
# only when the product's backlogProvider.allowedItemWrites opts in (default-deny; the first adopter leaves it
# default). Comments, Status writes, the ## Milestone Progress checklist, and self-assign are the
# allowed collaboration surface and are NOT here. The `[^|&;\n]*` scoping binds a forbidden flag to
# its own `gh issue edit` segment, so a chained `gh issue comment --body ... && gh issue edit
# --add-assignee` is not false-flagged.
ITEM_CONTENT_WRITE_FLAG_PATTERNS = (
    (r"\bgh\s+issue\s+edit\b[^|&;\n]*--title\b", "title"),
    (r"\bgh\s+issue\s+edit\b[^|&;\n]*--body(?:-file)?\b", "body"),
    (r"\bgh\s+issue\s+edit\b[^|&;\n]*--(?:add|remove)-label\b", "labels"),
    (r"\bgh\s+issue\s+edit\b[^|&;\n]*--milestone\b", "milestone"),
)

def item_content_write_kinds(command: str) -> set:
    """The stakeholder-authored item fields a command would change (title/body/labels/milestone), or
    an empty set for allowed collaboration work. A GraphQL updateIssue can set title and body, so it
    reports both."""
    if not command:
        return set()
    scan = (
        command.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"').lower()
    )
    kinds = set()
    for pattern, kind in ITEM_CONTENT_WRITE_FLAG_PATTERNS:
        if re.search(pattern, scan):
            kinds.add(kind)
    if re.search(r"\bgh\s+api\s+graphql\b[^|&;\n]*updateissue\b", scan):
        kinds.update({"title", "body"})
    return kinds

LATEST_CODE_STATE_CHANGING_TOOL_MATCHERS = (
    "Bash",
    "Edit",
    "MultiEdit",
    "Write",
    "NotebookEdit",
    "ExitPlanMode",
    "Task",
)

LATEST_CODE_STATE_CHANGING_BASH_PATTERNS = (
    r"\bmake\s+(?:.*\b)?(?:deploy|release|publish|migrate|migration|seed|write|apply)\b",
    r"\b(?:terraform|pulumi|cdk)\s+(?:apply|destroy|deploy|up)\b",
)

def latest_code_redirection_writes_real_file(command: str) -> bool:
    for match in re.finditer(r"(?<![<])(?:[0-9]+)?(?:>>?|&>)[ \t]*([^ \t;&|]+)", command):
        target = match.group(1)
        if target.startswith("&") or target == "/dev/null":
            continue
        return True
    return False

def latest_code_shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=False, posix=True)
    except ValueError:
        return []

def shell_token_basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]

def skip_cli_global_options(tokens: list[str], index: int, value_options: set[str]) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token in {"&&", "||", ";", "|"}:
            index += 1
            continue
        if not token.startswith("-") or token == "-":
            return index
        option = token.split("=", 1)[0]
        index += 1
        if "=" not in token and option in value_options and index < len(tokens):
            index += 1
    return index

def latest_code_tokens_include_state_change(tokens: list[str]) -> bool:
    git_mutating = {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
        "tag",
    }
    gh_mutating = {"close", "comment", "create", "delete", "edit", "merge", "ready", "reopen", "transfer", "update"}
    file_mutating = {"rm", "mv", "cp", "mkdir", "touch", "chmod", "chown", "ln", "tee"}
    package_mutating = {"add", "install", "i", "remove", "uninstall", "update", "ci"}
    for index, token in enumerate(tokens):
        name = shell_token_basename(token)
        if name == "git":
            subcommand_index = skip_cli_global_options(
                tokens,
                index + 1,
                {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"},
            )
            subcommand = tokens[subcommand_index] if subcommand_index < len(tokens) else ""
            if subcommand in git_mutating:
                return True
            if subcommand == "branch" and any(arg in {"-d", "-D", "-m", "-M"} for arg in tokens[subcommand_index + 1 :]):
                return True
        if name == "gh":
            subcommand_index = skip_cli_global_options(
                tokens,
                index + 1,
                {"-r", "--repo", "--hostname", "--jq", "--template"},
            )
            subcommand = tokens[subcommand_index] if subcommand_index < len(tokens) else ""
            remaining = tokens[subcommand_index + 1 :]
            if subcommand in {"issue", "pr", "project", "release"} and any(
                arg in gh_mutating or arg.startswith(("field-", "item-")) for arg in remaining
            ):
                return True
            if subcommand == "api":
                upper_remaining = [arg.upper() for arg in remaining]
                if "MUTATION" in " ".join(upper_remaining):
                    return True
                for arg_index, arg in enumerate(upper_remaining):
                    if arg in {"-X", "--METHOD"} and arg_index + 1 < len(upper_remaining):
                        if upper_remaining[arg_index + 1] in {"POST", "PUT", "PATCH", "DELETE"}:
                            return True
                    if arg.startswith(("-X", "--METHOD=")) and any(
                        method in arg for method in ("POST", "PUT", "PATCH", "DELETE")
                    ):
                        return True
        if name in file_mutating:
            return True
        if name == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in tokens[index + 1 :]):
            return True
        if name in {"npm", "pnpm", "yarn", "bun"} and index + 1 < len(tokens) and tokens[index + 1] in package_mutating:
            return True
        if name in {"pip", "pip3"} and index + 1 < len(tokens) and tokens[index + 1] == "install":
            return True
        if name in {"python", "python3"} and tokens[index + 1 : index + 4] == ["-m", "pip", "install"]:
            return True
        if name in {"uv", "poetry"} and index + 1 < len(tokens) and tokens[index + 1] in {
            "add",
            "install",
            "remove",
            "sync",
            "update",
        }:
            return True
    return False

LATEST_CODE_AUTOREFRESH_BACKOFF_SECONDS = 90

def latest_code_autorefresh_note(baseline: dict, warnings: object = None) -> str | None:
    """A concise heads-up when the auto-refresh surfaced work ahead of base or the fetch did not
    complete, so the agent keeps the awareness the guard was built to create -- without the block.
    Silent when the baseline refreshed cleanly with nothing ahead. Emits only integer counts (never
    branch names, URLs, or warning text, which can carry remote tokens)."""
    ahead = baseline.get("remoteBranchesAheadOfBase") or []
    prs = baseline.get("openPrs") or []
    fetch_incomplete = bool(warnings)
    if not ahead and not prs and not fetch_incomplete:
        return None
    parts: list[str] = []
    if ahead:
        parts.append(f"{len(ahead)} remote branch(es) ahead of base")
    if prs:
        parts.append(f"{len(prs)} open PR(s)")
    note = "Minervit latest-code: the freshness window had lapsed and the baseline was auto-refreshed."
    if parts:
        note += (
            " " + " and ".join(parts)
            + " exist -- do not assume local HEAD or origin/main is current; review them before deep work."
        )
    if fetch_incomplete:
        note += (
            " (git fetch did not fully complete; the baseline reflects the last-known remote state --"
            " verify connectivity before relying on it.)"
        )
    return note

# The SessionStart standing-directive hook command. Fail-open at the shell boundary: a missing
# executable (rollback) or an older CLI without the subcommand exits 0 silently before Python
# runs. Byte-identical in plugins/tautline-core/hooks/hooks.json and the settings writer below.
SESSION_START_DIRECTIVE_HOOK_COMMAND = (
    "/bin/sh -c 'command -v tautline >/dev/null 2>&1 "
    "&& tautline autonomy-directive --hook 2>/dev/null || true'"
)

# Host per-hook timeout (seconds): a hanging shim/adapter read never reaches `|| true`, and
# without it every session would wait out the host's long default, defeating fail-open.
SESSION_START_DIRECTIVE_HOOK_TIMEOUT = 5

# A SEPARATE SessionStart entry, not an extension of the directive command: the directive's 5s
# bound is enforced by _is_session_start_directive_hook_current and its command is byte-pinned
# across hooks.json and the settings writer, so folding a fetch into it would break both (C7).
SESSION_START_LANE_STATUS_HOOK_COMMAND = (
    "/bin/sh -c 'command -v tautline >/dev/null 2>&1 "
    "&& tautline lane-status --hook 2>/dev/null || true'"
)

# Must exceed LANE_STATUS_MAX_FETCH_TIMEOUT_SECONDS (15) plus collection overhead, or the host
# kills the hook before it can report UNVERIFIED and fail-open reporting is defeated.
SESSION_START_LANE_STATUS_HOOK_TIMEOUT = 25

def settings_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    return any("plan-finalization-hook" in json.dumps(item) for item in hooks)

def settings_branch_liveness_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    return any("branch-liveness-hook" in json.dumps(item) for item in hooks)

def settings_response_guard_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("Stop", [])
    return any("response-guard-hook" in json.dumps(item) for item in hooks)

def settings_tool_rejection_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PostToolUseFailure", [])
    return any("tool-rejection-hook" in json.dumps(item) for item in hooks)

def settings_background_command_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    return any("background-command-hook" in json.dumps(item) for item in hooks)

def settings_latest_code_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    return any("latest-code-hook" in json.dumps(item) for item in hooks)

def latest_code_hook_entry_is_current(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("matcher") not in LATEST_CODE_STATE_CHANGING_TOOL_MATCHERS:
        return False
    return "latest-code-hook" in json.dumps(entry)

def settings_latest_code_hook_current(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    matchers = {
        str(entry.get("matcher"))
        for entry in hooks
        if latest_code_hook_entry_is_current(entry)
    }
    stale_latest_code_entries = [
        entry
        for entry in hooks
        if "latest-code-hook" in json.dumps(entry) and not latest_code_hook_entry_is_current(entry)
    ]
    return set(LATEST_CODE_STATE_CHANGING_TOOL_MATCHERS).issubset(matchers) and not stale_latest_code_entries

def settings_context_rotation_heartbeat_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PostToolUse", [])
    return any("context-rotation-heartbeat-hook" in json.dumps(item) for item in hooks)

def settings_plan_review_pending_hook_installed(settings: dict) -> bool:
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    return any("plan-review-pending-hook" in json.dumps(item) for item in hooks)

FLEET_GUARD_HOOK_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"

def settings_fleet_guard_hook_installed(settings: dict) -> bool:
    # Matcher-aware ON PURPOSE, unlike the plan-review predicate above. A settings
    # file written by an older build carries "Edit|Write|MultiEdit", which leaves
    # NotebookEdit silently unguarded -- the exact bypass the plugin hooks.json
    # closes. A command-string-only check would report that stale entry as
    # installed and let the hole persist forever.
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher") != FLEET_GUARD_HOOK_MATCHER:
            continue
        for hook in entry.get("hooks", []) or []:
            if isinstance(hook, dict) and "fleet-guard-hook" in str(hook.get("command", "")):
                return True
    return False

def _is_session_start_directive_command(hook: object, command: str) -> bool:
    # Identifies OURS by command string (any/missing timeout) -- used by the writer to strip/replace
    # any stale registration of this command. NOT the health check; see _current below.
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and hook.get("command") == command
    )

def _is_session_start_directive_hook_current(
    hook: object, command: str, timeout: int = SESSION_START_DIRECTIVE_HOOK_TIMEOUT
) -> bool:
    # A HEALTHY registration is our command AND the exact fail-open timeout. An entry carrying the
    # command but a missing/larger timeout is NOT current: a hanging shim would stall session start
    # for the host default, defeating the fail-open guarantee -- so it must be rewritten, not
    # accepted, and reported as drift by the hook-state gate.
    #
    # `timeout` is parameterised (defaulted to the directive value, so existing callers are
    # byte-unchanged) because the lane-status entry carries 25s: hardcoding the directive constant
    # would judge a correct lane-status entry stale forever and the writer would never be
    # idempotent.
    return (
        _is_session_start_directive_command(hook, command)
        and hook.get("timeout") == timeout
    )

def settings_session_start_directive_hook_installed(
    settings: dict,
    command: str = SESSION_START_DIRECTIVE_HOOK_COMMAND,
    timeout: int = SESSION_START_DIRECTIVE_HOOK_TIMEOUT,
) -> bool:
    # Matcher-aware AND timeout-aware: an active registration is the exact command as a
    # `type: command` hook WITH the fail-open timeout under the all-source "*" matcher. A
    # right-command entry with a NARROWED matcher, or a wildcard entry missing/oversizing the
    # timeout, does not count -- the writer migrates/rewrites it so a bare session never misses the
    # directive and never loses the fail-open bound.
    for entry in settings.get("hooks", {}).get("SessionStart", []):
        if not isinstance(entry, dict) or str(entry.get("matcher")) != "*":
            continue
        for hook in entry.get("hooks", []):
            if _is_session_start_directive_hook_current(hook, command, timeout):
                return True
    return False

def claude_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks` for Claude ExitPlanMode hook"

def claude_branch_liveness_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_branch_liveness_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude Task branch-liveness hook"

def claude_response_guard_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_response_guard_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude Stop response guard hook"

def claude_tool_rejection_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_tool_rejection_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude tool-rejection context hook"

def claude_background_command_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_background_command_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude Bash background-command guard"

def claude_latest_code_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_latest_code_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude latest-code guard"

def claude_fleet_guard_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [
        Path.home() / ".claude" / "settings.json",
        target / ".claude" / "settings.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_fleet_guard_hook_installed(settings):
            return True, f"installed {path}"
    return False, (
        "missing required hook - run `tautline install-hooks --target .` for the "
        "fleet lease guard (cross-worktree edit coordination)"
    )

def claude_plan_review_pending_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_plan_review_pending_hook_installed(settings):
            return True, f"installed {path}"
    return False, (
        "missing required hook - run `tautline install-hooks --target .` for the "
        "plan-edit guard (plan-review deadlock prevention)"
    )

def claude_context_rotation_heartbeat_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_context_rotation_heartbeat_hook_installed(settings):
            return True, f"installed {path}"
    return False, "missing required hook - run `tautline install-hooks --target .` for Claude context-rotation heartbeat hook"

def claude_session_start_directive_hook_state(target: Path) -> tuple[bool, str]:
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_session_start_directive_hook_installed(settings):
            return True, f"installed {path}"
    return False, (
        "missing required hook - run `tautline install-hooks --target .` for the "
        "Claude SessionStart standing-directive hook"
    )

def claude_session_start_lane_status_hook_state(target: Path) -> tuple[bool, str]:
    """Reported by methodology-status, but NEVER added to hook_failures (C6): gating drift on it
    would fail startup on every machine that has not re-run install-hooks, which is the exact
    2026-07-22 lockout class this item exists to close."""
    candidates = [Path.home() / ".claude" / "settings.json", target / ".claude" / "settings.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if settings_session_start_directive_hook_installed(
            settings,
            SESSION_START_LANE_STATUS_HOOK_COMMAND,
            SESSION_START_LANE_STATUS_HOOK_TIMEOUT,
        ):
            return True, f"installed {path}"
    return False, (
        "optional hook not installed - run `tautline install-hooks --target .` for the "
        "Claude SessionStart lane-status hook (report-only; its absence never blocks)"
    )

def write_claude_session_start_lane_status_hook(
    settings_path: Path,
    command: str = SESSION_START_LANE_STATUS_HOOK_COMMAND,
    timeout: int = SESSION_START_LANE_STATUS_HOOK_TIMEOUT,
) -> tuple[Path, bool]:
    return write_claude_session_start_directive_hook(settings_path, command, timeout)

def claude_hook_status(target: Path) -> str:
    return claude_hook_state(target)[1]

def load_claude_settings(settings_path: Path) -> dict:
    settings_path = settings_path.expanduser()
    for attempt in range(5):
        if not settings_path.exists():
            return {}
        try:
            raw = settings_path.read_text(encoding="utf-8")
            if not raw.strip():
                raise json.JSONDecodeError("empty settings file", raw, 0)
            return json.loads(raw)
        except (OSError, json.JSONDecodeError):
            if attempt == 4:
                raise
            time.sleep(0.05)
    return {}

def write_claude_settings(settings_path: Path, settings: dict) -> None:
    settings_path = settings_path.expanduser()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    tmp_path = settings_path.with_name(f".{settings_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, settings_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

def write_claude_plan_finalization_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_present = settings_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PreToolUse"].append(
            {
                "matcher": "ExitPlanMode",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_branch_liveness_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_present = settings_branch_liveness_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PreToolUse"].append(
            {
                "matcher": "Task",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_response_guard_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("Stop", [])
    already_present = settings_response_guard_hook_installed(settings)
    if not already_present:
        settings["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": command}]})
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_tool_rejection_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PostToolUseFailure", [])
    already_present = settings_tool_rejection_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PostToolUseFailure"].append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_background_command_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_present = settings_background_command_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PreToolUse"].append(
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_latest_code_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_current = settings_latest_code_hook_current(settings)
    if not already_current:
        rewritten_hooks: list[dict] = []
        for entry in settings["hooks"]["PreToolUse"]:
            if "latest-code-hook" not in json.dumps(entry):
                rewritten_hooks.append(entry)
                continue
            hooks = [
                hook
                for hook in entry.get("hooks", [])
                if "latest-code-hook" not in json.dumps(hook)
            ]
            if hooks:
                kept = dict(entry)
                kept["hooks"] = hooks
                rewritten_hooks.append(kept)
        existing = {
            (str(entry.get("matcher")), json.dumps(entry.get("hooks", []), sort_keys=True))
            for entry in rewritten_hooks
        }
        for matcher in LATEST_CODE_STATE_CHANGING_TOOL_MATCHERS:
            hook_entry = {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
            key = (matcher, json.dumps(hook_entry["hooks"], sort_keys=True))
            if key not in existing:
                rewritten_hooks.append(hook_entry)
        settings["hooks"]["PreToolUse"] = rewritten_hooks
        write_claude_settings(settings_path, settings)
    return settings_path, already_current

def write_claude_context_rotation_heartbeat_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PostToolUse", [])
    already_present = settings_context_rotation_heartbeat_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PostToolUse"].append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_plan_review_pending_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_present = settings_plan_review_pending_hook_installed(settings)
    if not already_present:
        settings["hooks"]["PreToolUse"].append(
            {
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_fleet_guard_hook(settings_path: Path, command: str) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("PreToolUse", [])
    already_present = settings_fleet_guard_hook_installed(settings)
    if not already_present:
        # REPLACE, never append: an older build's entry carries the narrower
        # "Edit|Write|MultiEdit" matcher, and appending beside it would register
        # the command twice while leaving the stale entry in place. Strip every
        # fleet-guard registration first, preserving foreign sibling hooks and
        # dropping entries that become empty, then write the single correct one.
        rewritten: list[dict] = []
        for entry in settings["hooks"]["PreToolUse"]:
            if not isinstance(entry, dict) or "fleet-guard-hook" not in json.dumps(entry):
                rewritten.append(entry)
                continue
            kept_hooks = [
                hook for hook in entry.get("hooks", []) or []
                if "fleet-guard-hook" not in json.dumps(hook)
            ]
            if kept_hooks:
                kept = dict(entry)
                kept["hooks"] = kept_hooks
                rewritten.append(kept)
        rewritten.append(
            {
                "matcher": FLEET_GUARD_HOOK_MATCHER,
                "hooks": [{"type": "command", "command": command}],
            }
        )
        settings["hooks"]["PreToolUse"] = rewritten
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def write_claude_session_start_directive_hook(
    settings_path: Path,
    command: str = SESSION_START_DIRECTIVE_HOOK_COMMAND,
    timeout: int = SESSION_START_DIRECTIVE_HOOK_TIMEOUT,
) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("SessionStart", [])
    already_present = settings_session_start_directive_hook_installed(
        settings, command, timeout
    )
    if not already_present:
        # Migration REPLACES: strip this command from EVERY existing entry -- a narrowed-matcher
        # entry (append-alongside would double/triple-emit) AND a wildcard entry carrying a stale or
        # missing timeout (keeping it would leave two wildcard registrations, re-introducing the
        # double-emit and the unbounded-timeout hole). Foreign sibling hooks are preserved and an
        # entry that becomes empty is dropped; then the single fail-open wildcard entry is written.
        rewritten: list = []
        for entry in settings["hooks"]["SessionStart"]:
            if not isinstance(entry, dict):
                rewritten.append(entry)
                continue
            nested = entry.get("hooks", [])
            kept = [h for h in nested if not _is_session_start_directive_command(h, command)]
            if len(kept) == len(nested):
                rewritten.append(entry)
            elif kept:
                pruned = dict(entry)
                pruned["hooks"] = kept
                rewritten.append(pruned)
            # else: the entry held only our (stale) directive hook -> drop it entirely
        rewritten.append(
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": timeout,
                    }
                ],
            }
        )
        settings["hooks"]["SessionStart"] = rewritten
    write_claude_settings(settings_path, settings)
    return settings_path, already_present

def normalize_repo_path_arg(path_arg: str) -> str:
    path = path_arg.strip()
    if not path:
        raise SystemExit("--path values must be non-blank")
    path = path[2:] if path.startswith("./") else path
    if path.startswith("/") or path == ".." or path.startswith("../") or "/../" in path:
        raise SystemExit(f"--path must be relative to the target repo: {path_arg}")
    return path

def latest_code_config(data: dict) -> dict:
    return data["latestCode"]

def resolve_test_run_command(data: dict, explicit: str | None) -> tuple[str, str]:
    """The command to run and where it came from.

    Split out of `test_run` so the refusal is reachable in a unit test without standing up a whole
    adapter-backed lane -- the refusal text is a rule surface (it must name every supported path
    forward, per RCA 2026-07-22 control 6), and a rule surface no test can reach is exactly the
    unobservable-control problem this feature exists to fix.
    """
    if explicit:
        return explicit, "--command"
    commands = data.get("commands") if isinstance(data, dict) else None
    configured = (commands or {}).get("fullPreflight")
    if configured:
        return configured, "commands.fullPreflight"
    raise SystemExit(
        "test-run: no test command configured. Either pass `--command '<cmd>'` for a one-off run, "
        "or set `commands.fullPreflight` in the project adapter and re-render it with "
        "`tautline render-adapters`."
    )

def lane_status_declared_claim_branch(entry: Path) -> str | None:
    """The branch a claimed backlog item declares, or None. Runs on the session-start path, so an
    unreadable file is the same as undeclared -- it must never raise."""
    try:
        for line in (entry / "CLAIM").read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.strip()
    except OSError:
        return None
    return None

def latest_code_instruction_line() -> str:
    """The latest_code_failures debt-gate remediation hint methodology_status prints when no
    cached baseline exists yet. Its own pure function (rather than an inline literal) so the
    startup-remediation recovery-action coverage test can scan exactly this string instead of
    methodology_status's entire body."""
    return (
        "latest_code_instruction: run `tautline latest-code-status --target . --write` before "
        "current-status answers, deep analysis, planning, implementation, review, or subagent "
        "work; read-only diagnosis remains allowed."
    )

def print_latest_code_baseline(data: dict, target: Path, baseline: dict, state: str | None = None) -> None:
    print(f"latest_code: enabled={str(bool(baseline.get('enabled'))).lower()}")
    if state:
        print(f"latest_code_baseline_state: {state}")
    print(f"latest_code_recorded_at: {baseline.get('recordedAt', 'unknown')}")
    print(f"latest_code_base_ref: {baseline.get('baseRef', 'unknown')}")
    print(f"latest_code_base_commit: {baseline.get('baseCommit', 'unknown')}")
    print(f"latest_code_local_branch: {baseline.get('localBranch', 'unknown')}")
    print(f"latest_code_local_commit: {baseline.get('localCommit', 'unknown')}")
    print(
        "latest_code_local_vs_base: "
        f"ahead={baseline.get('localAheadBase', 'unknown')} behind={baseline.get('localBehindBase', 'unknown')}"
    )
    print(f"latest_code_local_dirty: {baseline.get('localDirty', 'unknown')}")
    ahead = baseline.get("remoteBranchesAheadOfBase") or []
    print(f"latest_code_remote_branches_ahead: {len(ahead)}")
    for branch in ahead[:5]:
        print(
            "latest_code_remote_branch_ahead: "
            f"{branch.get('ref')} ahead={branch.get('aheadOfBase')} behind={branch.get('behindBase')} commit={branch.get('commit')}"
        )
    if len(ahead) > 5:
        print(f"latest_code_remote_branch_ahead_more: {len(ahead) - 5}")
    open_prs = baseline.get("openPrs") or []
    print(f"latest_code_open_prs: {len(open_prs)}")
    for pr in open_prs[:5]:
        print(
            "latest_code_open_pr: "
            f"#{pr.get('number')} {pr.get('headRefName')} -> {pr.get('baseRefName')} "
            f"{pr.get('mergeStateStatus', 'unknown')} {pr.get('url', '')}"
        )
    if len(open_prs) > 5:
        print(f"latest_code_open_pr_more: {len(open_prs) - 5}")
    for warning in baseline.get("warnings") or []:
        print(f"latest_code_warning: {warning}")
    if ahead:
        print(
            "latest_code_instruction: remote branches are ahead of base; before deep analysis or state-changing work, decide whether the live/stakeholder surface is base or one of those branch refs."
        )
    else:
        print("latest_code_instruction: latest baseline is fetched; use base/GitHub/deploy evidence before trusting local lane files.")

STARTUP_REMEDIATION_MARKER_SCHEMA = "tautline-startup-remediation/v1"

# 0.8.9 startup remediation (docs/reference/startup-remediation.md): the central dispatch guard's
# ALLOWED/BLOCKED partition of the real argparse command registry (see
# registered_subcommand_names()). Every registered subcommand must be classified into EXACTLY one
# of these two tuples -- tuples, not UPPER_CASE lists of str, so they stay out of the
# policy-phrases SSOT collector -- enforced by the registry partition test. Default posture for
# anything project-mutating is BLOCKED; ALLOWED is what diagnosing/clearing gate debt,
# committing/pushing the fixes, or declaring a blocker requires. Two mandatory membership rules
# (enforced by dedicated tests, not just this comment): (1) every command invoked by the
# generated git hooks and Claude hooks is ALLOWED; (2) every command referenced in a debt gate's
# printed issue/recovery text is reachable -- globally ALLOWED here, or listed in that gate's
# STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS entry (project-work mutators like goal/milestone
# repair commands take the recovery-map route, never global promotion).
STARTUP_REMEDIATION_ALLOWED_COMMANDS: tuple[str, ...] = (
    # -- explicitly named by design: the remediation rerun loop and its exits --
    # Fleet Governor. fleet-lease is ALLOWED because the fleet guard's own escape
    # commands are `fleet-lease takeover` / `release`: blocking them would strand a
    # remediating lane behind a lease it is being told to take over. Classified in
    # the same commit that registers the verb -- the registry partition test fails
    # the moment a registered subcommand sits in neither tuple.
    "fleet-lease",
    # fleet-guard-hook is hook-invoked, and test_hook_invoked_commands_are_all_allowed
    # DERIVES its expectation from the real hook templates: once hooks.json calls it,
    # ALLOWED is mandatory, not a judgment call.
    "fleet-guard-hook",
    "methodology-status",
    "lane-start",
    "sync-methodology",
    # product-dev-mode is a per-checkout operator-convenience relief verb that writes only its
    # own gitignored .ai-work/ state file (no code-safety impact): it must never be blocked by
    # an active startup-remediation marker -- otherwise a degraded checkout could refuse the very
    # verb meant to relieve the friction (the sibling standdown also allowlists it past the
    # stale-baseline latest-code guard for the same chicken-and-egg reason).
    "product-dev-mode",
    # snapshot-pin is invoked by the generated launcher on every startup (it is what stops
    # retention from deleting the snapshot this session is executing); snapshot-status is a
    # read-only diagnostic. snapshot-prune deletes trees, has no startup role, and is BLOCKED.
    "snapshot-pin",
    "snapshot-status",
    "install-claude-launcher",
    "log-event",
    # decision-record: recording a decision DURING startup remediation is desirable, never blocked;
    # it writes only the machine-local event JSONL (same family as log-event) with no code-safety
    # impact.
    "decision-record",
    # decisions-report: a read-only view over the machine-local decision ledger (no writes, no
    # code-safety impact); reading decisions during startup remediation is desirable, never blocked.
    "decisions-report",
    "blocker-declare",
    "blocker-clear",
    "blocker-status",
    # -- the review-evidence pipeline (commit/push the fixes with evidence) --
    "record-stage1-sweep",
    "codex-run",
    "finalize-implementation-review",
    "review-evidence-check",
    "claude-review",
    "claude-review-status",
    # -- graphify install/status --
    "graphify-install",
    "graphify-status",
    # -- session journal validate/prepare (local-only; publish is a separate, blocked surface) --
    "prepare-session-journal",
    "validate-session-journal",
    # -- instrumentation prepare/validate (0.9.0): local-only preview + read-only validator;
    # publish-instrumentation-record is a separate, blocked surface (added in T5) --
    "prepare-instrumentation-record",
    "validate-instrumentation-record",
    # -- canonical-policy/dump-* (flag-aware: --write is blocked; see
    # STARTUP_REMEDIATION_WRITE_FLAG_GATED_COMMANDS) and validate-style read-only commands --
    "canonical-policy",
    "dump-policy-phrases",
    "dump-instrumentation-schema",
    "validate-adapter",
    "validate-feature-request-artifact",
    "validate-grooming",
    "validate-iteration-review",
    "validate-rca-artifact",
    # -- help/version --
    "version",
    # -- hook-invoked (mandatory rule 1): every command the generated git hooks or Claude hooks
    # call, enumerated from the hook templates (git_branch_liveness_hook_content, guard_check,
    # and the install_claude_*_hook writers) --
    "work-profile-check",
    "branch-liveness-check",
    "guard-check",
    "backlog-provider-active-check",
    "plan-finalization-hook",
    "plan-review-pending-hook",
    "branch-liveness-hook",
    "response-guard-hook",
    "tool-rejection-hook",
    "background-command-hook",
    "latest-code-hook",
    "context-rotation-heartbeat-hook",
    # -- debt-gate remediation text (mandatory rule 2): commands methodology-status's own printed
    # debt-gate output names, that are not themselves goal/milestone/board mutators --
    "install-hooks",  # hook_failures: "missing required hook - run `tautline install-hooks`"
    "latest-code-status",  # latest_code_failures: "run `tautline latest-code-status --write`"
    "publish-product-note",  # product_chat: "post quick human-requested notes with `tautline publish-product-note`"
    "ui-evidence-submit",  # the fix action for ui_evidence_failures debt (verification evidence, not goal/milestone content)
    "publish-deploy-ready-update",  # deployment_notification's own printed rule names this as the required caller
    # -- coordination process metadata (not project source/goal content); repairs
    # lane_coordination_failures the way T2 intends ("your own note is fresh enough") --
    "lane-coordination-note",
    "lane-coordination-status",
    # -- read-only diagnostics: inspection/reporting only, no project-state mutation, needed to
    # diagnose which gate is failing and why --
    "audit",
    "behavior-spec-status",
    # behavior-spec-delta-check: read-only (it inspects the staged tree and reports), and it is
    # built to run from a pre-commit hook. Blocking it during remediation would make that hook
    # fail on a lane that is already unhealthy -- turning a degraded lane into one that cannot
    # commit the fix. It is fail-open by construction, so allowing it costs nothing.
    "behavior-spec-delta-check",
    "backlog-provider-status",
    "backlog-provider-board-check",
    # backlog-provider-closeout-check: read-only in the same sense as its board-check sibling --
    # it ASSERTS and PRINTS and performs no board write by construction (item 79 D1). It is also
    # the named remedy in its own refusal and in the pending-closeout boundary warning, so
    # blocking it during startup remediation would make a lane unable to run the one command that
    # clears the condition holding it -- the dead-end shape this program keeps closing.
    "backlog-provider-closeout-check",
    # autonomy-directive: read-only render of the standing directive; the SessionStart hook and
    # entry-point emission fire during startup remediation, so the verb must never be blocked.
    "autonomy-directive",
    # plan-authoring-standard: read-only render of the plan-authoring standard (same shape as
    # autonomy-directive); prints guidance only, no writes, so it is never blocked.
    "plan-authoring-standard",
    # plan-substance-check: read-only content check on a plan the lane already has. Allowed at a
    # blocked startup for the same reason as its sibling above -- it writes nothing, and a lane
    # told to fix its plan before R1 has to be able to SEE what is missing while it is blocked.
    "plan-substance-check",
    # lane-status: read-only currency report writing only its own gitignored artifact. It is the
    # SessionStart control, so blocking it under a startup-remediation marker would remove the
    # report from precisely the degraded lanes that most need it.
    "lane-status",
    "goal-status",
    # done-check: read-only report, writes nothing at all. A lane under a startup-remediation
    # marker is exactly a lane whose operator needs to know which done conditions are failing.
    "done-check",
    "goal-kickoff-prompt",
    "goal-tracker-status",
    "milestone-status",
    "milestone-watchdog",
    "iteration-review-status",
    "iteration-review-delivery-check",
    "deployment-notification-status",
    "deployment-notification-pipeline-snippet",
    "stakeholder-question-status",
    "milestone-update-status",
    "release-update-status",
    "github-budget-status",
    "remote-main-status",
    "context-status",
    "context-rotation-check",
    "diff-coverage-check",
    "flaky-quarantine-check",
    "ci-health-check",
    "red-green-check",
    "deploy-health",
    "guard-report",
    "readiness-review",
    "response-guard",
    "telemetry",
    "pilot-report",
    "check-name-availability",
    # read-only: reports the repo/npm/PyPI versions and the drift verdict, mutating
    # nothing. Its mutating counterpart, release-tail, is BLOCKED.
    "release-drift-check",
    "event-log-path",
    "event-tail",
    "event-audit",
    "event-viewer",
    "event-rotate",
    "usage-report",
    "usage-log-path",
    "usage-import-claude",
    "usage-record",
    "usage-rotate",
    "monitor-status",
    # -- execution utilities the Claude background-command-hook's own block message points agents
    # at ("Use the adapter command or `tautline background-run` ... `monitor-status` active
    # polling"); blocking these would make the hook's own guidance unfollowable mid-remediation --
    "background-run",
)

STARTUP_REMEDIATION_BLOCKED_COMMANDS: tuple[str, ...] = (
    # -- goal/milestone project-work mutators: the core of what remediation gates. Some are
    # reachable only via STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS while the marker's recorded
    # gates cover them; goal-advance/milestone-advance have no recovery-map entry at all --
    "goal-start",
    "goal-next",
    "goal-condition",
    # goal-assignment hands a finalized plan to a builder lane. Handing out NEW work while this
    # checkout owes remediation debt is exactly what the gate exists to stop, so it sits with the
    # rest of the goal family here rather than in ALLOWED, print-only though it is.
    "goal-assignment",
    "goal-advance",
    "milestone-start",
    "milestone-next",
    "milestone-advance",
    "work-loop",
    "lane-run",
    # Running a full product test suite is project work, not a startup-remediation action: it can
    # take a quarter of an hour and proves nothing about the blocked gate. The registry-partition
    # test fails any subcommand listed in neither tuple, so this placement is deliberate.
    "test-run",
    # Landing code is the LAST thing a checkout owing remediation debt should be doing, and the
    # verb performs a real merge. Deliberate placement, same as test-run above.
    "merge",
    "backlog-provider-next",
    "backlog-provider-sync",
    "backlog-provider-update",
    # ac-verify (item 81) reads a board item's acceptance criteria and prints the closure table
    # skeleton. It is the continuation of the done-move gate, and every verb that can reach a done
    # move -- goal-advance, goal-tracker-update, backlog-provider-update -- is BLOCKED here, so
    # promoting its helper would only let a remediating lane prepare closure evidence it cannot
    # post. Classified in the same commit that registers the verb.
    "ac-verify",
    "backlog-board-examine",
    "backlog-board-adopt",
    "goal-tracker-next",
    "goal-tracker-sync",
    "goal-tracker-update",
    "backlog-provider-export",
    "backlog-provider-migration-interview",
    "stakeholder-question-ask",
    # -- publish-*: external announcements of project-work progress; a remediation session should
    # not be declaring milestones/features done while debt is outstanding (publish-deploy-ready-
    # update and publish-product-note are ALLOWED above -- required by their own debt gates'
    # printed remediation text, and process/status metadata rather than project-work content) --
    "publish-feature-request-artifact",
    "publish-instrumentation-record",
    "publish-iteration-review",
    "publish-milestone-update",
    "publish-pending-session-journals",
    "publish-rca-artifact",
    "publish-release-update",
    "publish-session-journal",
    # -- project/adapter/repo setup and mutation, not remediation --
    "adapter-bootstrap-questions",
    "context-bootstrap",
    "cut-release",
    "emit-iteration-review-workflow",
    "finalize-plan-review",
    "generate-iteration-review-page",
    "init",
    "init-project-adapter",
    "install-cli",
    "uninstall-cli",
    "iteration-review-renderer-setup",
    "lane-coordination-bootstrap",
    "lock-methodology",
    "unlock-methodology",
    # maintainer-mode mutates the machine-wide update-gate state (arming stands every
    # methodology update gate down; disarming restores them) -- the same machine-mutator
    # posture as set-framework-channel / update-repin / install-cli. Diagnosis during
    # remediation stays available through the ALLOWED methodology-status, whose report
    # block prints the three-state maintainer_mode line.
    "maintainer-mode",
    "plan-finalization-precheck",
    "prepare-continuity",
    "purge-archive",
    "record-plan-review",
    "release-migration-report",
    "render-adapters",
    "repair-methodology-main",
    "run-plan-review",
    "scaffold-test-harness",
    "set-framework-channel",
    # deletes snapshot trees from the shared store; nothing a remediation session needs, and the
    # read-only half (snapshot-status) stays ALLOWED
    "snapshot-prune",
    "update-repin",
    "codex-plan-review",
    "migrate-adapter",
    "public-contract",
    "public-release-check",
    "public-release-export",
    # -- the release tail: publishes the mirror and two registries. A registry publish
    # is irreversible, so shipping a release is the last thing a repo in startup
    # remediation should be able to do. release-drift-check is the read-only half and
    # stays ALLOWED, like release-update-status --
    "registry-package",
    "release-tail",
)

# canonical-policy/dump-* are flag-aware (V14R1-P2-2): read/check modes stay ALLOWED, --write is
# treated as BLOCKED (recovery-map rules still apply if a future gate ever needs one).
STARTUP_REMEDIATION_WRITE_FLAG_GATED_COMMANDS: tuple[str, ...] = ("canonical-policy", "dump-policy-phrases", "dump-instrumentation-schema")

def _startup_remediation_marker_data(marker_path: Path) -> dict:
    """Best-effort parse; a missing/corrupted marker (truncated JSON, non-UTF-8 bytes, non-dict)
    reads as `{}` so callers fail closed (no recovery-map gates recognized) instead of crashing
    (UnicodeDecodeError coverage: Codex T7 R2 P2)."""
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def _startup_remediation_marker_gates(marker_path: Path) -> list[str]:
    gates = _startup_remediation_marker_data(marker_path).get("gates")
    return [gate for gate in gates if isinstance(gate, str)] if isinstance(gates, list) else []

LAUNCHER_GENERATED_MARKER = "Generated by tautline install-claude-launcher."

# v2 adds the per-launcher sha256 the divergence check needs (RCA 2026-07-22 control 4). v1
# records -- bare path strings -- are still read; see read_installed_launcher_entries.
INSTALLED_LAUNCHERS_SCHEMA = "tautline-installed-launchers/v2"

# A generated launcher is a few KB of shell. The cap is what separates "read a candidate" from
# "decode whatever the operator happens to have installed": stale_claude_launchers() scans a real
# bin dir -- compiled binaries, multi-megabyte single-file tools -- on EVERY lane start.
LAUNCHER_SCAN_MAX_BYTES = 256 * 1024

def _launcher_text(path: Path) -> str | None:
    """The text of a file that could plausibly BE a launcher, or None.

    Reads bytes, not text, and reads at most the cap: a launcher is a small regular text file, so
    anything that is not one is rejected without decoding it. Binary is detected the way every
    other tool does it -- a NUL byte in the content -- because read_text(errors="replace") happily
    turns a 40MB executable into a 40MB string and only then fails to find the marker in it.
    """
    try:
        if not path.is_file():  # a directory, a socket, a dangling symlink: not a launcher
            return None
        with path.open("rb") as handle:
            head = handle.read(LAUNCHER_SCAN_MAX_BYTES + 1)
    except OSError:  # missing, unreadable: not a launcher we can judge
        return None
    if len(head) > LAUNCHER_SCAN_MAX_BYTES or b"\0" in head:
        return None
    return head.decode("utf-8", errors="replace")

def _launcher_digest(path: Path) -> str | None:
    """sha256 of a launcher's bytes, or None when it cannot be read or is not launcher-shaped.

    Bytes, not text: the digest must change for ANY edit, including one that only touches
    encoding or line endings.

    SIZE-CAPPED like _launcher_text, and for the same reason one level up: this runs on every
    launch over whatever now sits at a recorded path. Without the cap, a recorded path that has
    become a 250MB binary would be read end to end on every single sync. Callers reach the digest
    only AFTER _launcher_looks_generated has confirmed launcher-shaped content, so the cap can
    never be the thing that decides whether a replacement is reported.
    """
    try:
        if path.stat().st_size > LAUNCHER_SCAN_MAX_BYTES:
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

LAUNCHER_DIVERGENCE_HAND_REPLACED = "hand-replaced"

LAUNCHER_DIVERGENCE_EDITED = "edited"

def _launcher_looks_generated(path: Path) -> bool | None:
    """Is the file at `path` our generated launcher? None when we could not judge.

    THE THREE-WAY ANSWER IS THE POINT. _launcher_text collapses "unreadable" and "not a launcher"
    into one None, which is fine for a scan that only ever adds candidates -- but here the two
    must diverge: an unreadable file is one we cannot accuse of anything (a permissions blip must
    not print a replacement notice), while a readable file that is oversized, binary, or simply
    missing the generated marker IS the replacement we are hunting.
    """
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            head = handle.read(LAUNCHER_SCAN_MAX_BYTES + 1)
    except OSError:
        return None
    if len(head) > LAUNCHER_SCAN_MAX_BYTES or b"\0" in head:
        return False  # oversized or binary: whatever this is, it is not our shell script
    return LAUNCHER_GENERATED_MARKER in head.decode("utf-8", errors="replace")

# sec-trust-exec-1: a skip-permissions launcher re-checks the effective update policy at launch,
# because it can change after install (methodology.env edit / removed pin). It refuses to start
# unless the upstream is verifiable (pinned or signed). Tuple, not list, to stay out of the
# policy-phrases SSOT.
_SKIP_PERMISSIONS_LAUNCH_GUARD = (
    'MINERVIT_METHODOLOGY_UPDATE_POLICY_EFFECTIVE="${TL_UPDATE_POLICY:-warn}"',
    'case "$MINERVIT_METHODOLOGY_UPDATE_POLICY_EFFECTIVE" in',
    "  pinned|signed) ;;",
    "  *)",
    '    printf "%s\\n" "minervit-claude: refusing --dangerously-skip-permissions while methodology update policy is $MINERVIT_METHODOLOGY_UPDATE_POLICY_EFFECTIVE (need pinned or signed; see SECURITY.md)" >&2',
    "    exit 1",
    "    ;;",
    "esac",
)

OPERATOR_LAUNCHER_MARKER = "# tautline-operator-launcher: session-scoped, non-blocking"

def _reject_reserved_launcher_name(name: str) -> None:
    """Reserved-name/`/` rejection for the operator branch (FR1V-R3 P1).

    DUPLICATES install_claude_launcher's inline default check so the operator branch validates
    WITHOUT editing or calling into the byte-protected default handler body.
    """
    forbidden_names = {"", ".", "..", "claude", "tautline", "minervit-methodology"}
    if "/" in name or name in forbidden_names:
        raise SystemExit(
            "launcher name must be a command name such as tautline-claude or yolo, "
            "not a path or reserved command"
        )

# SHA-256 of b"": the digest a review manifest carries when the resolved scope was zero bytes.
# Named so the 2026-07-28 incident's signature is greppable; before this constant existed the
# empty-string digest appeared nowhere in the repo, which is HOW a void review finalized clean.
EMPTY_DIFF_SHA256 = hashlib.sha256(b"").hexdigest()


def implementation_review_subject_errors(record: dict) -> list[str]:
    """Refuse a review with no subject (RCA 2026-07-28: empty-diff review finalized clean).

    ``record`` is either an ``implementation_review_state()`` dict or a Stage 2 manifest -- both
    carry the same keys. Each void marker refuses INDEPENDENTLY: a manifest that omits
    ``diff_bytes`` must not dodge the check, and ``head == base`` catches the case before any diff
    is hashed.

    Absence is NOT voidness. A record carrying none of the three markers is a subject the caller
    could not derive, and an underived subject must fall through to today's behavior -- an unknown
    state has no more business minting a refusal than it has minting a free round.
    """
    errors: list[str] = []
    head = str(record.get("head_sha") or "").strip()
    base = str(record.get("base_sha") or "").strip()
    diff_sha = str(record.get("diff_sha256") or "").strip()
    diff_bytes = record.get("diff_bytes")
    if (head and base and head == base) or diff_sha == EMPTY_DIFF_SHA256 or diff_bytes == 0:
        errors.append(
            "the reviewed diff is empty (head_sha == base_sha, zero diff bytes, or diff_sha256 "
            "is the empty-string digest): this review has no subject and proves nothing. Likely "
            "cause: uncommitted work, or a review run from the base branch. Commit the outgoing "
            "work to a feature branch (`git switch -c <branch> && git add -A && git commit`), "
            "then re-run the review. No ledger is written and no round is spent."
        )
    return errors


def implementation_review_effective_round(
    declared_round: int | None, observed_executions: int
) -> int:
    """The round this execution really is: the higher of the label and one past the recorded spend.

    The budget is spent by EXECUTIONS, not labels. Six runs invoked as R1 against one lineage
    (RCA 20260707T181643Z) each passed a label-derived cap as round 1 while the aggregate was
    round 6; plan review closed the identical hole in 0.22.0 (``plan_review_effective_round``) and
    this is the implementation-review analogue.
    """
    return max(int(declared_round or 0), int(observed_executions) + 1)


def implementation_review_round_number(round_marker: str | None) -> int | None:
    if not round_marker:
        return None
    match = re.search(r"(\d+)", str(round_marker))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None

IMPLEMENTATION_REVIEW_EXTRA_ROUND_REASON_MIN_CHARS = 12

# How far past the adapter budget a lane may self-authorize before refusal turns absolute. Named
# rather than inlined so the cap moves with the budget instead of being a second magic number:
# plan review learned this the hard way (PLAN_REVIEW_TARGET_ROUNDS vs PLAN_REVIEW_HARD_CAP_ROUNDS).
IMPLEMENTATION_REVIEW_HARD_CAP_MARGIN = 2

# Codex R4 P2. Every refusal that offers "bind the evidence instead" showed
# `finalize-implementation-review --verdict clean-with-deferrals` and stopped there -- but the verb
# REQUIRES --manifest, --unresolved-critical-count, and --unresolved-p1-count, so following the
# remedy landed on an argparse error. A no-dead-ends refusal that ends in a usage error is still a
# dead end; it just moves where the lane gets stuck. One constant, not three copies, because three
# copies of an invocation drift and the drifted one is the one nobody runs until it matters.
IMPLEMENTATION_REVIEW_FINALIZE_EXAMPLE = (
    "tautline finalize-implementation-review --target . --manifest <manifest.json> "
    "--verdict clean-with-deferrals --unresolved-critical-count 0 --unresolved-p1-count 0"
)

def implementation_review_hard_cap(budget: int) -> int:
    return int(budget) + IMPLEMENTATION_REVIEW_HARD_CAP_MARGIN

def implementation_review_retry_command(
    data: dict, target: Path, risk_tier: str, review_round: str
) -> str:
    """The literal invocation that takes the self-authorized round, wrapper and all.

    Codex R2 P2. A remedy is only a remedy if pasting it works. `codex-run` is a SUBCOMMAND of
    `tautline`, and the verb refuses without the review wrapper after `--`, so the old bare
    `codex-run --allow-extra-rounds ...` died before the round could start. Built here, from the
    lane's own adapter, rather than hardcoded in the message: the wrapper is per-project, and a
    message naming some other project's wrapper is a dead end for everyone but its author.

    Mirrors `plan_review_finalize_command`. Returns "" when the adapter carries no wrapper, and the
    refusal falls back to its generic-but-runnable shape.
    """
    review = data.get("review", {}) if isinstance(data.get("review"), dict) else {}
    wrapper = str(review.get("codexWrapper") or "").strip()
    if not wrapper:
        return ""
    # Codex R4 P2: guard_target_argument ALREADY shell-quotes (see its docstring). Wrapping it in
    # shlex.quote again survives every path without a metacharacter -- which is every path in the
    # test suite -- and then, on a checkout whose path contains a space, emits literal quote
    # characters INSIDE --target, pointing the remedy at a directory that does not exist. A remedy
    # that only works on tidy paths is a dead end for exactly the machines least able to debug it.
    # Codex R3 P2 / backlog item 51, deferred at 0.36.0's hard cap and closed here. `codex_run`
    # additionally REQUIRES --native-review-note and --stage1-sweep for T2/T3, so the earlier
    # invocation died at the Stage 1 refusal instead of taking the round -- a remedy that fails one
    # gate later is still a dead end. Placeholders rather than the caller's own values on purpose:
    # both artifacts must be re-made against the REMEDIATED diff, and echoing the stale ones back
    # would invite pasting evidence that describes a tree that no longer exists.
    stage1 = ""
    if implementation_stage1_required_for_risk_tier(risk_tier):
        stage1 = (
            ' --native-review-note "<what Stage 1 found on the current assembled diff>"'
            " --stage1-sweep <fresh-sweep.json>"
        )
    return (
        f"tautline codex-run --target {guard_target_argument(target)} "
        f"--risk-tier {shlex.quote(risk_tier)} --review-round {shlex.quote(review_round)} "
        '--allow-extra-rounds --extra-round-reason "<reason>"'
        f"{stage1} "
        f"-- {wrapper}"
    )

def implementation_review_round_self_authorized(
    round_number: int | None, budget: int | None, *, is_confirming_round: bool = False
) -> bool:
    """True when this round was admitted by the LADDER's self-authorization rung, not by the budget.

    Exists so the call site does not re-derive "past budget" from the same inputs the ladder
    already judged (Codex R1 P2). Two copies of that comparison would drift, and the copy that
    drifts is the one deciding whether the reason gets recorded -- an audit gap that reads as a
    clean run.

    A confirming round is admitted by the exemption, not by self-authorization, so it is False
    here: it needs no reason and prints its own `codex_run_confirming_round:` line instead.
    """
    if round_number is None or budget is None or is_confirming_round:
        return False
    return int(round_number) > int(budget)

def implementation_review_round_cap_errors(
    *,
    round_number: int | None,
    budget: int | None,
    charged_round_number: int | None = None,
    risk_tier: str = "",
    review_round_label: str = "",
    allow_extra_rounds: bool = False,
    extra_round_reason: str = "",
    is_confirming_round: bool = False,
    retry_command: str = "",
) -> list[str]:
    """Round-budget ladder for implementation review. Item 48 / backlog item 43.

    Before this existed, `codex_run` refused on `round_number > budget` alone and returned before
    reaching the `clean_rounds >= 2` gate that `--allow-extra-rounds` was actually wired to. The
    confirming round `methodology/policy/17-review-before-push.md` MANDATES on a remediated diff was
    therefore unreachable, the refusal said "escalate", and lanes stopped to ask the operator a
    question with exactly one valid answer. Nothing in the suite covered that refusal, which is how
    it survived from 0.17.5 to 0.35.3.

    The shape deliberately mirrors `plan_review_round_cap_errors`: rounds up to `budget` are free,
    rounds up to `budget + margin` self-authorize with a RECORDED reason, and past that refusal is
    unconditional. Two idioms for one concept is how the policy and the code drifted apart in the
    first place.

    Order matters, and each position is load-bearing:

    1. Input validation, so a bad `--review-round` is named rather than silently treated as round 0.
    2. The HARD CAP, before the confirming-round exemption -- a free confirmation must not be a way
       past the absolute ceiling.
    3. The CONFIRMING-ROUND exemption, before the budget comparison. Re-binding an existing verdict
       to a changed diff hash is not a new round of inquiry and is not charged as one; that is the
       whole remediation loop, and charging it is what made every PR whose review found something
       unpushable.
    4. The budget comparison and the self-authorization ladder.

    TWO CURRENCIES (item 75). ``round_number`` is the TOTAL executions recorded for this lineage
    and is what the hard cap binds; ``charged_round_number`` is the subset that funded new inquiry
    -- the confirming predicate replayed over the recorded sequence -- and is what the budget and
    the self-authorization rung compare. It defaults to ``round_number``, so every pre-existing
    caller and every existing test in this ladder's contract behaves exactly as before.

    Feeding one number to both comparisons breaks the ladder in two directions, and the plan's
    T2.0 decision exists because both were observed. Compare TOTAL against the budget and a
    within-budget round run after a free confirming round starts demanding ``--allow-extra-rounds``
    -- a silent budget cut. Compare CHARGED against the cap and the six-R1 pathology walks
    straight through, because all six of those executions were confirming-by-predicate: each
    followed a fix and bound a changed hash. Confirming-ness cannot tell a pathological loop from
    a healthy one. Only quantity can, which is why the ceiling counts everything.


    Returns refusal strings; empty means proceed. No string returned from here may instruct an agent
    to consult a human -- see `tests/test_codex_run_round_ladder.py`.
    """
    label = str(review_round_label or "").strip()
    tier = str(risk_tier or "").strip() or "this risk tier"

    if round_number is None or int(round_number) < 1:
        quoted = f", got {label!r}" if label else ""
        return [
            "--review-round must include a numeric round marker such as R1"
            f"{quoted}"
        ]
    if budget is None:
        return [
            f"no implementation review round budget is configured for risk tier {tier}; "
            "add review.roundBudgets to the project adapter and re-run: "
            "tautline validate-adapter --project .tautline/adapter.json"
        ]

    round_number = int(round_number)
    budget = int(budget)
    charged = int(charged_round_number) if charged_round_number is not None else round_number
    cap = implementation_review_hard_cap(budget)

    if round_number > cap:
        quoted = f" (label {label!r})" if label else ""
        # Name BOTH currencies whenever they diverge. An unexplained jump from a label of R1 to
        # "round 5" reads as a budget bug, and a lane that cannot see why it was refused cannot
        # tell a working control from a broken one -- the same narration discipline
        # `codex_run_confirming_round:` already follows.
        spend = ""
        if charged != round_number:
            spend = (
                f" ({round_number - 1} prior executions recorded against this lineage, "
                f"{charged - 1} of them charged)"
            )
        return [
            f"implementation review round {round_number}{quoted} exceeds the hard cap of {cap} "
            f"rounds for {tier} (adapter budget {budget} plus "
            f"{IMPLEMENTATION_REVIEW_HARD_CAP_MARGIN}){spend}; the cap is absolute and no "
            "exception "
            "note, no flag, and no authorization can raise it. Two exits, neither of which needs "
            "another Codex execution: decompose this change into smaller PRs and review each of "
            "those (a new branch is a new lineage and starts a fresh count); or, IF a recorded "
            "manifest still binds the diff you are pushing, resolve every Critical/P1, park any "
            "discretionary post-review changes (`git stash`, or carry them on a follow-up branch) "
            f"and bind that manifest with `{IMPLEMENTATION_REVIEW_FINALIZE_EXAMPLE}`, routing "
            "out-of-AC findings at honest severity to named backlog rows. If the diff has moved "
            "past every recorded manifest, only the first exit is open -- finalize cannot bind "
            "evidence to a tree that no longer exists"
        ]

    # A confirmation is owed work, not new inquiry. Free, and bounded by the cap checked above.
    if is_confirming_round:
        return []

    if charged <= budget:
        return []

    reason = str(extra_round_reason or "").strip()
    if not allow_extra_rounds:
        # Codex R2 P2: this used to show a bare `codex-run ...`, and following it literally FAILS.
        # `codex-run` is a subcommand of `tautline`, not an executable, and the verb also requires
        # the review wrapper after `--`. A remedy that dies before the round starts is the same
        # dead end this item exists to remove, wearing a remedy's clothes. The caller builds the
        # real invocation -- including the adapter's own wrapper -- exactly as plan review's
        # `finalizable_command` does; the fallback below is generic but still runnable in shape.
        take_the_round = retry_command or (
            "tautline codex-run --target . --risk-tier <tier> --review-round <Rn> "
            '--allow-extra-rounds --extra-round-reason "<reason>" -- <review.codexWrapper>'
        )
        return [
            f"implementation review round {charged} is past the adapter budget of {budget} "
            f"for {tier} (charged rounds only; {round_number - 1} total executions are "
            "recorded against this lineage), so it is self-authorized only with a recorded "
            f"reason. Rounds {budget + 1}-{cap} never require operator authorization: take the "
            "round with "
            f"`{take_the_round}` naming the genuine new defect class, or resolve the remaining "
            f"findings and bind the evidence with `{IMPLEMENTATION_REVIEW_FINALIZE_EXAMPLE}`"
        ]
    if len(reason) < IMPLEMENTATION_REVIEW_EXTRA_ROUND_REASON_MIN_CHARS:
        return [
            "--allow-extra-rounds requires --extra-round-reason \"<reason>\" naming the genuine "
            f"new defect class (at least {IMPLEMENTATION_REVIEW_EXTRA_ROUND_REASON_MIN_CHARS} "
            "characters); a placeholder is not accepted"
        ]
    return []

def implementation_stage1_required_for_risk_tier(risk_tier: str | None) -> bool:
    """Fail closed for old wrappers: only an explicit T1 review skips Stage 1 sweep evidence."""
    return str(risk_tier or "").strip() not in {"T1"}

CLAUDE_REVIEW_PACKET_WARN_BYTES = 30000

def claude_review_added_diff_content_lines(blob_text: str) -> list[str]:
    lines: list[str] = []
    for line in blob_text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if not line.strip():
            continue
        lines.append(line)
    return lines

def claude_review_packet_diff_block(packet_text: str, path: str) -> str:
    normalized = packet_text.replace("\r\n", "\n").replace("\r", "\n")
    diff_header = f"diff --git a/{path} b/{path}"
    start = normalized.find(diff_header)
    if start < 0:
        return ""
    next_start = normalized.find("\ndiff --git ", start + len(diff_header))
    if next_start < 0:
        return normalized[start:]
    return normalized[start:next_start]

def claude_review_packet_has_diff_header(packet_text: str, path: str) -> bool:
    normalized = packet_text.replace("\r\n", "\n").replace("\r", "\n")
    escaped = re.escape(path)
    return bool(
        re.search(rf"^diff --git a/{escaped} b/.+$", normalized, re.MULTILINE)
        or re.search(rf"^diff --git a/.+ b/{escaped}$", normalized, re.MULTILINE)
    )

def claude_review_is_reference_policy_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(".md") and ("/references/" in normalized or normalized.startswith("references/"))

def claude_review_packet_mentions_stage1_native(packet_text: str) -> bool:
    return bool(re.search(r"stage\s*1[^\n]{0,80}native\s+review", packet_text, re.IGNORECASE))

def claude_review_packet_mentions_stage1_sweep(packet_text: str) -> bool:
    return bool(re.search(r"stage\s*1[^\n]{0,80}sweep", packet_text, re.IGNORECASE))

def claude_review_packet_mentions_verification(packet_text: str) -> bool:
    return bool(re.search(r"^##\s+.*(?:verification|tests?|validation)", packet_text, re.IGNORECASE | re.MULTILINE))

def claude_review_packet_has_live_probe(packet_text: str) -> bool:
    return "claude_review_output:" in packet_text and "claude_review_verdict: no_blockers" in packet_text

def claude_review_prompt(packet_text: str, extra_instruction: str = "") -> str:
    boundary = "MINERVIT_REVIEW_PACKET_" + hashlib.sha256(packet_text.encode("utf-8")).hexdigest()[:16]
    result_shape = {
        "verdict": "no_blockers",
        "blockers": [],
        "non_blocking": [],
        "reviewed_evidence": "one sentence naming the packet evidence reviewed",
    }
    extra = f"\nAdditional review instruction:\n{extra_instruction.strip()}\n" if extra_instruction.strip() else ""
    return (
        "You are the Stage 2 Claude reviewer for a Minervit implementation/process change.\n"
        "Do not use tools. Do not ask to run tools. Do not propose shell commands.\n"
        "Review only the evidence packet below. If the packet is missing evidence needed to decide "
        "whether a Critical or P1 blocker exists, return exactly one blocker naming that missing evidence.\n"
        "Report only Critical or P1 blockers in blockers. Put lower-severity observations in non_blocking.\n"
        "Return valid JSON only, with this shape:\n"
        f"{json.dumps(result_shape, sort_keys=True)}\n"
        f"{extra}"
        f"\n--- BEGIN {boundary} ---\n"
        f"{packet_text}\n"
        f"--- END {boundary} ---\n"
    )

def claude_review_record_kind(record: dict) -> str:
    preflight = record.get("packet_preflight")
    if isinstance(preflight, dict) and preflight.get("errors"):
        return "packet_preflight_error"
    if record.get("claude_transport_failure"):
        return "transport_failure"
    if record.get("wrapper_exit_code") == 124:
        return "timeout"
    if record.get("parse_error"):
        return "parse_error"
    review_result = record.get("review_result")
    if isinstance(review_result, dict):
        verdict = review_result.get("verdict")
        if verdict == "blocked":
            return "completed_blocked_review"
        if verdict == "no_blockers":
            return "completed_clean_review"
        return "completed_unknown_review"
    claude_exit = record.get("claude_cli_exit_code")
    if isinstance(claude_exit, int) and claude_exit != 0:
        return "legacy_transport_failure"
    wrapper_exit = record.get("wrapper_exit_code")
    if isinstance(wrapper_exit, int) and wrapper_exit != 0:
        return "wrapper_error"
    return "unknown"

def git_diff_bytes(target: Path, base_sha: str, head_ref: str = "HEAD") -> bytes:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "diff",
            "--binary",
            f"{base_sha}...{head_ref}",
            "--",
            ".",
            ":(exclude)**/.impl-reviews/*.json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip() or "git diff failed"
        raise RuntimeError(detail)
    return proc.stdout

def normalize_repo_path(path: str) -> str:
    """Repo-root-relative, forward-slash form matching what `git diff --name-only` emits: drop a
    leading './' and collapse '.'/'//' so a declared artifact/source path lines up with the diff."""
    return os.path.normpath(path).replace(os.sep, "/")

def normalize_derived_artifacts(raw: object) -> list[dict]:
    """Validate + normalize the adapter `derivedArtifacts` declaration (fail-closed). Each entry
    binds a committed derived artifact to the source globs it is generated from."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SystemExit("Project adapter derivedArtifacts must be a list")
    normalized: list[dict] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SystemExit(f"Project adapter derivedArtifacts[{index}] must be an object")
        artifact = str(entry.get("artifact", "")).strip()
        if not artifact:
            raise SystemExit(f"Project adapter derivedArtifacts[{index}] missing artifact")
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources or not all(
            isinstance(s, str) and s.strip() for s in sources
        ):
            raise SystemExit(
                f"Project adapter derivedArtifacts[{index}].sources must be a non-empty list of glob strings"
            )
        clean_sources = []
        for source in sources:
            source = source.strip()
            if "**" in source:
                raise SystemExit(
                    f"Project adapter derivedArtifacts[{index}].sources entry {source!r} uses '**', which "
                    "fnmatch does not match recursively; use '*' (it already spans '/')"
                )
            clean_sources.append(normalize_repo_path(source))
        normalized.append(
            {
                "artifact": normalize_repo_path(artifact),
                "sources": clean_sources,
                "regenerate": str(entry.get("regenerate", "")).strip(),
            }
        )
    return normalized

def stage1_sweep_class_errors(classes: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(classes, list) or not classes:
        return ["stage1 sweep must include at least one checked defect class"]
    clean_or_fixed = 0
    allowed_status = {"clean", "fixed", "not-applicable"}
    for index, item in enumerate(classes, start=1):
        if not isinstance(item, dict):
            errors.append(f"class {index} must be an object")
            continue
        class_name = str(item.get("class", "")).strip()
        members = str(item.get("members_checked", "")).strip()
        status = str(item.get("status", "")).strip()
        if len(class_name) < 3:
            errors.append(f"class {index} missing class name")
        if len(members) < 20:
            errors.append(f"class {index} must describe the members/files/sinks checked")
        if status not in allowed_status:
            errors.append(f"class {index} status must be one of {sorted(allowed_status)}")
        if status in {"clean", "fixed"}:
            clean_or_fixed += 1
    if clean_or_fixed == 0:
        errors.append("stage1 sweep must include at least one clean or fixed defect class")
    return errors

def parse_prepush_ref_records(text: str) -> list[tuple[str, str, str, str]] | None:
    """Parse `<local ref> <local sha1> <remote ref> <remote sha1>` lines (the documented
    pre-push hook stdin format). Any malformed line invalidates the whole batch (fail closed)."""
    records: list[tuple[str, str, str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4:
            return None
        records.append((parts[0], parts[1], parts[2], parts[3]))
    return records

def review_evidence_coordination_path_is_artifact(target: Path, rel_path: str, roots: dict[str, Path]) -> bool:
    """Classify the Git path itself, lexically (Codex T7 R1 P2): resolve() on the candidate
    would follow a symlink placed at rel_path and let a non-allowlisted source path masquerade
    as a coordination artifact. Only the target root is canonicalized (host /tmp indirection);
    the candidate's own components are joined lexically and never resolved. A coordination
    artifact reached through a symlinked CONFIGURED path therefore no longer matches -- that
    direction fails closed into today's ordinary gating."""
    try:
        candidate = Path(os.path.normpath(target.resolve(strict=False) / rel_path))
    except OSError:
        return False
    if candidate in (roots["contract"], roots["board"]):
        return True
    if candidate.suffix != ".md":
        return False
    try:
        # Purely lexical containment (Path.relative_to), NOT path_is_under: that helper
        # resolves the candidate, which follows an on-disk symlink and reopens the bypass.
        candidate.relative_to(roots["laneStatusDir"])
        return True
    except ValueError:
        return False

def scenario_in_added_ranges(scenario: dict, added_ranges: list[tuple[int, int]]) -> bool:
    """True when this outgoing diff's HEAD-side added ranges intersect the inactive scenario's
    span (its first @pending tag through its body window), so the diff-scoped behavior-spec gate
    treats a scenario as introduced/modified by this diff when the diff touched the tag, the
    Scenario: line, or the body — not only the single Scenario: line (which a tag-only pend or an
    in-body edit would miss, falling through to the non-blocking pre-existing-debt bucket)."""
    start = int(scenario.get("spanStart", scenario["line"]))
    end = int(scenario.get("spanEnd", scenario["line"]))
    if end < start:
        start, end = end, start
    return any(lo <= end and start <= hi for lo, hi in added_ranges)

def default_continuity_content() -> str:
    return """## Current State
- TODO

## Decisions Made
- TODO

## Files Changed
- TODO

## Validation
- TODO

## Open Risks Or Blockers
- TODO

## Next Action
- TODO
"""

def session_journal_local_dir(data: dict, target: Path) -> Path:
    return target / data["laneState"]["runsDir"] / "session-journals"

def session_journal_declared(data: dict, project_path: Path, target: Path) -> bool:
    """True when the SOURCE adapter takes a position on sessionJournal.enabled.

    Generated .tautline.json markers embed the merged sessionJournal block, so the
    marker itself always "declares" it; the adopter's actual choice lives in the
    _generated.sourceAdapter file. Unreadable/missing sources count as declared so a
    broken lane never nags."""
    source_rel = str((data.get("_generated") or {}).get("sourceAdapter") or "")
    source_path = (target / source_rel) if source_rel else project_path
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    block = raw.get("sessionJournal")
    return isinstance(block, dict) and "enabled" in block

def session_journal_optin_hint(data: dict, project_path: Path, target: Path) -> str:
    if data["sessionJournal"].get("enabled") or session_journal_declared(data, project_path, target):
        return ""
    return (
        "session_journal_optin: want to help make Tautline better? Session journals capture "
        "framework-improvement signals at milestone boundaries (off by default; kept local only — "
        "narrative journals can no longer be published to any remote as of 0.9.0). The safe way to "
        'contribute upstream is sanitized instrumentation: add "instrumentation": {"enabled": true} '
        "(a closed-vocabulary record with zero product-information capacity) and use "
        "`publish-instrumentation-record`. Learn more: docs/reference/instrumentation.md"
    )

def session_journal_published_marker(path: Path) -> Path:
    return path.with_name(f"{path.name}.published.json")

def session_journal_sort_key(path: Path) -> tuple[str, int]:
    """Collision-aware ordering key: (base name, numeric `-N` suffix). `unique_destination`
    appends `-1`/`-2` on same-second filename collisions, so lexical order alone would sort a
    third same-second journal (`...-session-journal-2.md`) BEFORE the first -- chaining a
    predecessor incorrectly. Base sorts chronologically (stamps are lexically ordered); the
    integer suffix breaks same-base ties in creation order (0 == no suffix)."""
    match = re.match(r"^(.*-session-journal)(?:-(\d+))?\.md$", path.name)
    if not match:
        return (path.name, 0)
    return (match.group(1), int(match.group(2)) if match.group(2) else 0)

def discover_session_journal_files(journal_dir: Path) -> list[Path]:
    """CENTRALIZED suffix-aware discovery of every session-journal file in a lane's journal dir,
    sorted collision-aware (ascending). The per-caller `*-session-journal.md` globs missed a
    collision-suffixed `...-session-journal-1.md`; every consumer (pending status, leak scan,
    predecessor-watermark chaining) shares this helper so a suffixed journal is never invisible."""
    if not journal_dir.exists():
        return []
    files = [path for path in journal_dir.glob("*-session-journal*.md") if path.is_file()]
    return sorted(files, key=session_journal_sort_key)

def pending_session_journals(data: dict, target: Path) -> list[Path]:
    journal_dir = session_journal_local_dir(data, target)
    return [
        path
        for path in discover_session_journal_files(journal_dir)
        if not session_journal_published_marker(path).exists()
    ]

def observability_state_dir(data: dict) -> Path:
    configured = str(data["observabilityEvents"]["stateDir"])
    expanded = os.path.expandvars(configured.replace("$HOME", str(Path.home())))
    return Path(expanded).expanduser()

def write_iteration_review_delivery_marker(
    marker_path: Path,
    *,
    review_slug: str,
    record_hash: str,
    page_hash: str,
    record_url: str,
    page_url: str,
    provider: str,
    webhook_env: str,
    skipped: bool = False,
    skip_reason: str | None = None,
    operator_approved: bool = False,
    repeat_reason: str | None = None,
) -> None:
    """Write/update the delivery marker, appending to a postHistory audit array so repeated
    posts (RCA O18) and operator-approved skips (RCA O11) are durably recorded rather than
    silently overwritten."""
    existing: dict = {}
    if marker_path.exists():
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    stamp = utc_event_timestamp()
    entry: dict = {"at": stamp, "recordSha256": record_hash, "pageSha256": page_hash, "pageUrl": page_url, "skipped": skipped}
    if repeat_reason:
        entry["repeatReason"] = repeat_reason
    if skip_reason:
        entry["skipReason"] = skip_reason
    post_history = list(existing.get("postHistory", []))
    post_history.append(entry)
    marker: dict = {
        "schema": "minervit-iteration-review-delivery/v1",
        "reviewSlug": review_slug,
        "recordSha256": record_hash,
        "pageSha256": page_hash,
        "recordUrl": record_url,
        "pageUrl": page_url,
        "provider": provider,
        "webhookEnv": webhook_env,
        "skipped": skipped,
        "postedAt": None if skipped else stamp,
        "postHistory": post_history,
    }
    if skipped:
        marker["skipReason"] = skip_reason or "operator-requested"
        marker["waivedAt"] = stamp
        marker["operatorApproved"] = operator_approved
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def product_chat_config(data: dict) -> dict:
    return data["productChat"]

def print_product_chat_status(data: dict) -> list[str]:
    cfg = product_chat_config(data)
    issues: list[str] = []
    if cfg["enabled"] and not cfg.get("webhookEnv"):
        issues.append("productChat.enabled is true but webhookEnv is blank")
    print(f"product_chat: enabled={str(cfg['enabled']).lower()}")
    print(f"product_chat_provider: {cfg['provider']}")
    print(f"product_chat_space: {cfg.get('chatSpace') or 'not-configured'}")
    print(f"product_chat_webhook_env: {cfg.get('webhookEnv') or 'not-configured'}")
    print(f"product_chat_max_chars: {cfg['maxChars']}")
    if cfg["enabled"]:
        print("product_chat_rule: agents may post quick human-requested notes with `tautline publish-product-note --target . --title <title> --stdin`")
    for issue in issues:
        print(f"product_chat_issue: {issue}")
    return issues

def utc_event_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def event_human_line(payload: dict) -> str:
    stamp = str(payload["ts"]).split("T", 1)[-1].replace("+00:00", "Z")
    severity = str(payload["severity"]).upper()
    event = str(payload["event"])
    lane = str(payload.get("lane") or "-")
    branch = str(payload.get("branch") or "-")
    plain = str(payload["plain"])
    next_action = str(payload["next"])
    return f"{stamp:<9} {severity:<5} {event:<28} {lane} {branch} | {plain} | next: {next_action}"

def rotate_event_file(path: Path, rotate_bytes: int, retained: int) -> None:
    if not path.exists() or path.stat().st_size <= rotate_bytes:
        return
    for index in range(retained - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        dest = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            if dest.exists():
                dest.unlink()
            source.rename(dest)
    first = path.with_name(f"{path.name}.1")
    if first.exists():
        first.unlink()
    path.rename(first)

def secure_event_log_paths(human: Path, jsonl: Path, lock: Path) -> None:
    """Restrict the observability dir (0700) and its event files (0600) to the owner. The event log
    now carries the salted lane_id that ALSO appears in published telemetry, so a world-readable
    (umask 0022 -> 0644) log on a multi-user host would let a co-located OS account correlate a
    remote sanitized record back to this product's local project/repo/branch data -- defeating the
    salt. The 0700 dir alone blocks traversal by others; the 0600 files are defense in depth, applied
    to existing logs and rotations too. Best-effort: permission errors are non-fatal."""
    directory = human.parent
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    for base in (human, jsonl, lock):
        for path in [base, *directory.glob(f"{base.name}.*")]:
            try:
                if path.exists():
                    path.chmod(0o600)
            except OSError:
                pass

DECISIONS_REPORT_SCHEMA = "tautline-decisions-report/v1"

DECISION_REVERSIBILITY_ENUM = ("reversible", "hard-to-reverse")

def _aware_utc(dt: datetime) -> datetime:
    """Normalize a datetime to aware UTC so no aware/naive comparison can throw. Zone-less
    (naive) values are interpreted as UTC (the documented decisions-report bound contract)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _valid_capped_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= EVENT_MAX_FIELD_CHARS

def decision_shaped_record(record: object) -> bool:
    """Anything that looks like it MEANT to be a decision -- an `event == "decision"` row (incl. a
    free-form `log-event --event decision`) or a row carrying the top-level discriminator. Used to
    decide what belongs in the skipped diagnostic vs. an ordinary event that is simply ignored."""
    if not isinstance(record, dict):
        return False
    return record.get("event") == "decision" or record.get("record_kind") == "tautline-decision/v1"

def _lane_status_discard_artifact(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass

def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]

EVENT_VIEWER_APP = "minervit-event-viewer"

EVENT_VIEWER_DEFAULT_PORT = 18765

def event_viewer_client_host(host: str) -> str:
    normalized = str(host or "").strip()
    if normalized in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    if ":" in normalized and not normalized.startswith("["):
        return f"[{normalized}]"
    return normalized

def event_viewer_url(host: str, port: int) -> str:
    return f"http://{event_viewer_client_host(host)}:{port}/"

EVENT_VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minervit Event Viewer</title>
<style>
:root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
body { margin: 0; background: Canvas; color: CanvasText; }
header { padding: 12px 16px; border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent); display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
h1 { font-size: 16px; margin: 0; }
#meta { font-size: 12px; opacity: .72; }
main { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, .9fr); height: calc(100vh - 54px); }
#events { overflow: auto; border-right: 1px solid color-mix(in srgb, CanvasText 18%, transparent); }
.row { padding: 8px 12px; border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; white-space: pre-wrap; cursor: pointer; }
.row:hover, .row.selected { background: color-mix(in srgb, Highlight 20%, transparent); }
.ok { border-left: 4px solid #1f9d55; }
.info { border-left: 4px solid #3b82f6; }
.warn { border-left: 4px solid #d97706; }
.block, .fail { border-left: 4px solid #dc2626; }
#detail { overflow: auto; padding: 12px; }
#detail h2 { font-size: 14px; margin: 0 0 8px; }
pre { margin: 0; font-size: 12px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 900px) { main { grid-template-columns: 1fr; grid-template-rows: 55vh 45vh; } #events { border-right: 0; border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent); } }
</style>
</head>
<body>
<header><h1>Minervit Event Viewer</h1><div id="meta">loading...</div></header>
<main>
  <section id="events" aria-label="Event stream"></section>
  <section id="detail"><h2>Event Detail</h2><pre>Click an event row to inspect its JSON payload.</pre></section>
</main>
<script>
let selectedId = null;
const eventsEl = document.getElementById('events');
const detailEl = document.getElementById('detail');
const metaEl = document.getElementById('meta');
function renderDetail(item) {
  selectedId = item.id;
  const title = document.createElement('h2');
  title.textContent = item.record.event || 'Event Detail';
  const detail = document.createElement('pre');
  detail.textContent = JSON.stringify(item.record, null, 2);
  detailEl.replaceChildren(title, detail);
  document.querySelectorAll('.row').forEach(row => row.classList.toggle('selected', row.dataset.id === selectedId));
}
async function refresh() {
  const response = await fetch('/api/events?limit=250&since=7d', {cache: 'no-store'});
  const payload = await response.json();
  metaEl.textContent = payload.project + ' | ' + payload.repo + ' | ' + payload.event_log + ' | refreshed ' + new Date().toLocaleTimeString();
  const scrollNearBottom = eventsEl.scrollTop + eventsEl.clientHeight >= eventsEl.scrollHeight - 48;
  eventsEl.innerHTML = '';
  payload.events.forEach(item => {
    const row = document.createElement('div');
    row.className = 'row ' + (item.record.severity || 'info');
    row.dataset.id = item.id;
    row.textContent = item.line;
    row.onclick = () => renderDetail(item);
    eventsEl.appendChild(row);
  });
  if (selectedId) {
    const selected = payload.events.find(item => item.id === selectedId);
    if (selected) renderDetail(selected);
  }
  if (scrollNearBottom) eventsEl.scrollTop = eventsEl.scrollHeight;
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""

def usage_state_dir(data: dict) -> Path:
    configured = str(data["usageAccounting"]["stateDir"])
    expanded = os.path.expandvars(configured.replace("$HOME", str(Path.home())))
    return Path(expanded).expanduser()

def session_journal_default_content() -> str:
    return """## Starting Context
- TODO

## Work Delivered Or Advanced
- TODO

## Planning And Review Gates
- TODO

## Human Interruptions Or Questions
- None.

## Delays, Waits, Or Autonomy Breakdowns
- None.

## Validation And PR State
- TODO

## Continuity Outcome
- TODO

## Methodology Improvement Signals
- None.
"""

def upsert_session_runtime_fields(text: str, fields: dict[str, str]) -> str:
    """Replace-if-present, insert-if-absent each field in the `## Session Runtime` section, leaving
    EXACTLY ONE of each afterward. Caller-supplied reused runtime content must not accumulate a
    second count/pointer/watermark (which would also let predecessor parsing read a stale value)."""
    lines = text.split("\n")
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^##\s+Session Runtime\s*$", line)),
        None,
    )
    if start is None:
        return text
    end = next(
        (j for j in range(start + 1, len(lines)) if re.match(r"^##\s+", lines[j])),
        len(lines),
    )
    body = lines[start + 1 : end]
    for field, value in fields.items():
        new_line = f"- {field}: {value}"
        pattern = re.compile(rf"^\s*-?\s*`?{re.escape(field)}`?\s*:", re.IGNORECASE)
        replaced = False
        for k, line in enumerate(body):
            if pattern.match(line):
                body[k] = new_line
                replaced = True
                break
        if not replaced:
            insert_at = len(body)
            while insert_at > 0 and body[insert_at - 1].strip() == "":
                insert_at -= 1
            body.insert(insert_at, new_line)
    return "\n".join(lines[: start + 1] + body + lines[end:])

def execution_queue_items(packet_text: str) -> list[str]:
    items: list[str] = []
    in_queue = False
    queue_headings = {
        "queue",
        "ordered tactical queue",
        "tactical queue",
        "execution queue",
    }
    for line in packet_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            in_queue = heading in queue_headings
            continue
        if not in_queue:
            continue
        if line[:1].isspace():
            continue
        if re.match(r"^[-*]\s+\[[xX]\]\s+", stripped):
            continue
        match = re.match(r"^[-*]\s+(?:\[\s\]\s*)?(.+?)\s*$", stripped)
        if match:
            items.append(match.group(1))
    return items

GOAL_RUN_SCHEMA = "minervit-goal-run/v1"

BLOCKER_SCHEMA = "minervit-blocker/v1"

BLOCKER_PATH = ".ai-work/BLOCKER.json"

BLOCKER_FRESH_SECONDS = 30 * 60

def blocker_path_display(target: Path, path: Path) -> str:
    try:
        return str(path.relative_to(target))
    except ValueError:
        return str(path)

def write_blocker_record_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)

def compact_one_line(text: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" -*\t|")
    cleaned = re.sub(r"^\[[ xX]\]\s*", "", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip(" .,;:-") + "..."

def selected_goal_milestone(run: dict, milestone_index: int | None) -> dict:
    milestones = run.get("milestones", [])
    if milestone_index is not None:
        for milestone in milestones:
            if milestone.get("index") == milestone_index:
                return milestone
        raise SystemExit(f"goal milestone not found: {milestone_index}")
    current_index = run.get("currentMilestoneIndex")
    for milestone in milestones:
        if milestone.get("index") == current_index:
            return milestone
    for milestone in milestones:
        if milestone.get("status") == "in_progress":
            return milestone
    for milestone in milestones:
        if milestone.get("status") == "pending":
            return milestone
    raise SystemExit("goal run has no selectable milestone")

def promote_next_goal_milestone(run: dict, now: str) -> None:
    for milestone in run.get("milestones", []):
        if milestone.get("status") == "pending":
            milestone["status"] = "in_progress"
            milestone["updatedAt"] = now
            run["currentMilestoneIndex"] = milestone["index"]
            return

def board_schema_fingerprint(fields: list) -> list:
    """Canonical, display-order-independent fingerprint of a board's schema (Slice B mismatch
    detection). Field display order is cosmetic and is sorted away; single-select OPTION order is the
    workflow column order and is preserved, so reordering columns is a meaningful schema change."""
    canon = []
    for field in fields or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        ftype = str(field.get("type") or "")
        options = [str(opt.get("name") or "") for opt in (field.get("options") or []) if isinstance(opt, dict)]
        canon.append([name, ftype, options])
    canon.sort(key=lambda entry: (entry[0], entry[1]))
    return canon

def board_schema_hash(fields: list) -> str:
    payload = json.dumps(board_schema_fingerprint(fields), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def board_schema_changed(stored_hash, fields: list) -> bool:
    """A never-adopted board (no stored hash) or a board whose live schema diverges from the stored
    hash is a mismatch -> the agent re-proposes an aligned adapter for operator confirmation."""
    if not stored_hash:
        return True
    return str(stored_hash) != board_schema_hash(fields)

def normalized_field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())

def goal_tracker_field_by_name(fields: list[dict], name: str) -> dict | None:
    wanted = normalized_field_key(name)
    for field in fields:
        if normalized_field_key(str(field.get("name", ""))) == wanted:
            return field
    return None

# Column-role keyword map: tuples of (match-keywords, role-label).  Tuple (not list) to avoid
# the policy-phrases SSOT auto-collection that fires on UPPER_CASE list-of-str constants.
_COLUMN_ROLE_KEYWORDS: tuple = (
    (("ready", "next"), "ready"),
    (("in progress", "active", "doing"), "active"),
    (("done", "closed", "shipped"), "done"),
    (("blocked",), "blocked"),
)

def _classify_column_role(name: str) -> str | None:
    """Return the role (ready/active/done/blocked) for a column name, or None if unrecognised."""
    low = name.strip().lower()
    for keywords, label in _COLUMN_ROLE_KEYWORDS:
        if low in keywords:
            return label
    return None

def board_assumptions(profile: dict) -> dict:
    """Pure renderer: given a board_profile dict, return plain-English assumptions (auto-classified
    parts) and the unknowns the operator must answer before an adopt can proceed."""
    statements: list[str] = []
    unknowns: list[str] = []

    status_field: str | None = profile.get("statusField")
    columns: list[str] = profile.get("columns") or []
    priority_c: list[str] = profile.get("priorityCandidates") or []
    order_c: list[str] = profile.get("orderCandidates") or []
    single_selects: dict[str, list[str]] = profile.get("singleSelects") or {}
    custom_fields: list[str] = profile.get("customFields") or []

    # 1. Column-role classification (case-insensitive exact match against known roles).
    for col in columns:
        role = _classify_column_role(col)
        if role:
            statements.append(f"Column '{col}' maps to role '{role}'.")
        else:
            unknowns.append(
                f"Which role does column '{col}' play (ready / active / done / blocked / backlog-icebox)?"
            )

    # 2. Priority/order signal — ask when there is at least one candidate but NOT exactly one
    #    priority field (ambiguous: 0 priority + ≥1 order, or >1 priority).
    if (len(priority_c) + len(order_c)) >= 1 and len(priority_c) != 1:
        unknowns.append(
            "How is the next item's priority/order decided (manual board order, or which field)?"
        )
    elif len(priority_c) == 1:
        statements.append(f"Priority is read from the '{priority_c[0]}' field.")
    elif order_c:
        statements.append(f"Item order is read from the '{order_c[0]}' field.")

    # 3. Custom single-select fields not yet classified (status field excluded — it IS classified).
    for field_name in custom_fields:
        if field_name == status_field:
            continue
        if field_name in single_selects:
            unknowns.append(f"How should the agent use custom field '{field_name}'?")

    # Guarantee statements is non-empty (required by spec even when all columns are unknown).
    if not statements:
        statements.append("No columns could be auto-classified; operator input required for all roles.")

    return {"statements": statements, "unknowns": unknowns}

def board_proposed_backlog_provider(
    profile: dict,
    current: dict,
    answers: dict | None = None,
) -> dict:
    """Propose a backlogProvider adapter block aligned to the board profile.

    Starts from a copy of current (preserving unrelated keys such as owner, projectNumber,
    itemTypes, linkPolicy) then overwrites the board-derived keys.  The schemaHash is carried
    forward from profile (board_profile stores it at construction time).
    """
    prop = dict(current)
    columns: list[str] = profile.get("columns") or []
    answers = answers or {}

    prop["statusField"] = profile.get("statusField")

    # Classify each column by role; collect into per-role lists (preserving column order).
    active: list[str] = []
    done: list[str] = []
    blocked: list[str] = []
    ready_auto: list[str] = []
    for col in columns:
        role = _classify_column_role(col)
        if role == "active":
            active.append(col)
        elif role == "done":
            done.append(col)
        elif role == "blocked":
            blocked.append(col)
        elif role == "ready":
            ready_auto.append(col)

    prop["activeStatuses"] = active
    prop["doneStatuses"] = done
    prop["blockedStatuses"] = blocked
    # readyStatuses: operator answer takes precedence; fall back to auto-classified.
    if "ready_column" in answers:
        prop["readyStatuses"] = [answers["ready_column"]]
    else:
        prop["readyStatuses"] = ready_auto

    # order/priority: set only when unambiguous; otherwise preserve whatever current carries.
    order_c: list[str] = profile.get("orderCandidates") or []
    priority_c: list[str] = profile.get("priorityCandidates") or []
    if order_c:
        prop["orderField"] = order_c[0]
    if len(priority_c) == 1:
        prop["priorityField"] = priority_c[0]

    # schemaHash carried from profile so raw fields are not re-fetched here.
    prop["schemaHash"] = profile.get("schemaHash")

    return prop

def board_answer_key(question: str) -> str:
    """Return the canonical answer-key for a board_assumptions unknown question.

    Priority: column role check first, then custom-field, then priority/order,
    then a slug fallback.  This order matters because role/custom questions
    contain neither 'priority' nor 'order'.
    """
    if "column '" in question:
        # Extract the name between "column '" and the next "'"
        start = question.index("column '") + len("column '")
        end = question.index("'", start)
        return f"role:{question[start:end]}"
    if "custom field '" in question:
        start = question.index("custom field '") + len("custom field '")
        end = question.index("'", start)
        return f"custom:{question[start:end]}"
    if "priorit" in question.lower() or "order" in question.lower():
        return "priority_order"
    # Slug fallback: lowercase, non-alphanumerics → underscore, truncate
    slug = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")
    return slug[:64]

def board_adopt_answers(raw: dict) -> dict:
    """Translate operator raw answers into the shape board_proposed_backlog_provider expects.

    Returns a dict containing everything in *raw*, plus ``ready_column`` set to
    the column name from any key ``role:<name>`` whose value (case-insensitive,
    stripped) equals ``"ready"``.  If no such key exists but *raw* already has
    ``ready_column``, that value is kept.
    """
    result = dict(raw)
    for key, val in raw.items():
        if key.startswith("role:") and str(val).strip().lower() == "ready":
            result["ready_column"] = key[len("role:"):]
            break
    return result

def board_order_value(text: str) -> float:
    """Parse an explicit board order field value to a sortable number. Blank/non-numeric sorts
    last so unranked items fall below explicitly-ordered ones."""
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    return float(match.group(0)) if match else float("inf")

def board_item_state_drift(
    title: str,
    url: str,
    board_status: str,
    content_state: str,
    done_statuses: list[str],
) -> str:
    """Pure: a project item's board status must reflect its real issue/PR state — a closed/merged
    item must sit in a done status, and an open item must not. Returns a drift message, or ''
    (also '' when the state is unknown, so we never guess). RCA: keeps features/bugs/tasks, not
    just goals/milestones, current on the stakeholder board."""
    state = (content_state or "").strip().upper()
    if state not in {"OPEN", "CLOSED", "MERGED"}:
        return ""
    bs = (board_status or "").strip().lower()
    done = {s.strip().lower() for s in done_statuses}
    ref = (url or title or "item").strip()
    if state in {"CLOSED", "MERGED"} and bs not in done:
        return (
            f"GitHub Project board item out of date: {ref} is {state.lower()} but its board status is "
            f"`{board_status or 'none'}`, not a done status; move it to a done status so the stakeholder board reflects shipped work"
        )
    if state == "OPEN" and bs in done:
        return (
            f"GitHub Project board item out of date: {ref} board status is `{board_status}` (done) but the issue/PR is still open; "
            "the board overstates completion"
        )
    return ""

def board_item_unconfigured_status_drift(title: str, url: str, board_status: str, configured_statuses: list[str]) -> str:
    """Pure: an in-scope board item must sit in a status the adapter enumerates
    (readyStatuses/activeStatuses/doneStatuses/blockedStatuses). A status outside all of them -- an
    ad-hoc review/QA column such as `In review` -- is drift: lanes must use only configured statuses
    and ship straight to a done status, never stage work in a separate review column. Empty status is
    not flagged (item not yet triaged). RCA: lanes parking items in an unconfigured review column."""
    bs = (board_status or "").strip()
    if not bs:
        return ""
    configured = {s.strip().lower() for s in configured_statuses if s.strip()}
    if bs.lower() in configured:
        return ""
    ref = (url or title or "item").strip()
    return (
        f"GitHub Project board item in an unconfigured status: {ref} board status is `{bs}`, which is not an "
        "adapter-approved status (readyStatuses/activeStatuses/doneStatuses/blockedStatuses). Move it to a configured "
        "status and do not stage work in a separate review/QA column -- ship straight to a done status when the issue/PR lands"
    )

def branch_issue_number(branch: str) -> str:
    """The trailing issue number on a branch name (e.g. `fix/...-334` -> `334`), or ''. A trailing
    ISO date (`hotfix/2026-06-19`) is NOT an issue number (P2), so it returns ''."""
    b = (branch or "").strip()
    if re.search(r"\d{4}-\d{2}-\d{2}$", b):
        return ""
    match = re.search(r"(?:^|[-_/#])(\d+)$", b)
    return match.group(1) if match else ""

def board_item_active_work_drift(
    title: str,
    url: str,
    board_status: str,
    content_state: str,
    is_active_work: bool,
    active_statuses: list[str],
    work_kind: str = "item",
    parent_ref: str = "",
) -> str:
    """Pure: a board item that is the target of active local work (the active goal ledger, an
    open mapped branch/PR) must sit in an adapter active status. An OPEN item still in Backlog/
    Ready while it is actively worked is drift -- the stakeholder board understates progress.
    Returns a drift message or ''. Only speaks to OPEN items and never guesses on unknown state
    (closed/merged is board_item_state_drift's job). RCA Jun-16 #234: real work underway on an
    item the board shows as not-started."""
    if not is_active_work:
        return ""
    if (content_state or "").strip().upper() != "OPEN":
        return ""
    active = {s.strip().lower() for s in active_statuses if s.strip()}
    if (board_status or "").strip().lower() in active:
        return ""
    ref = (url or title or "item").strip()
    primary = active_statuses[0] if active_statuses else "an active status"
    if work_kind == "subtask":
        parent = f" of {parent_ref}" if parent_ref else ""
        return (
            f"GitHub Project board subtask understates progress: {ref} is a board-backed subtask{parent} "
            f"being actively worked but its board status is `{board_status or 'none'}`, not an active status; "
            f"move it to `{primary}` (`tautline backlog-provider-update --target . --item {ref} --status {primary}`)"
        )
    return (
        f"GitHub Project board item understates progress: {ref} is being actively worked but its "
        f"board status is `{board_status or 'none'}`, not an active status; move it to `{primary}` "
        f"(`tautline backlog-provider-update --target . --item {ref} --status {primary}`)"
    )

RUNTIME_SECRET_SCAN_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

def detected_development_runtime() -> str:
    platform = sys.platform
    if platform == "darwin":
        return "darwin"
    if platform.startswith("win"):
        return "win32"
    if platform.startswith("linux"):
        try:
            osrelease = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            osrelease = ""
        try:
            version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            version = ""
        if "wsl2" in osrelease or "wsl2" in version:
            return "wsl2"
        if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP") or "microsoft" in osrelease or "microsoft" in version:
            return "wsl1"
        return "linux"
    return platform

def required_secret_fallback_findings(text: str, names: list[str]) -> list[str]:
    """Pure: which registered required-secret names are read with a degrade-to-empty fallback, turning a
    missing secret into a silent empty string instead of a loud failure. Catches the access-with-fallback
    forms (process.env.NAME ?? '' / || '' / ?? "" / ?? ``) and the destructuring default
    (const { NAME = '' } = process.env). Returns the offending names in registry order, deduped."""
    found: list[str] = []
    empty = r"(?:(['\"])\s*\1|`\s*`)"  # '' | "" | `` (template literal)
    for name in names:
        esc = re.escape(name)
        access = rf"process\.env\.{esc}|process\.env\[\s*['\"]{esc}['\"]\s*\]"
        fallback = rf"(?:{access})\s*(?:\?\?|\|\|)\s*{empty}"
        destructure = rf"\{{[^}}]*\b{esc}\s*=\s*{empty}[^}}]*\}}\s*=\s*process\.env"
        if name not in found and (re.search(fallback, text) or re.search(destructure, text)):
            found.append(name)
    return found

def parse_diff_added_lines(diff_text: str) -> dict[str, set[int]]:
    """Pure: map each file to the set of NEW-side line numbers ADDED by a unified diff. Deletions and
    context lines are ignored, so the gate measures only lines this change introduces (the right
    instrument for new code -- whole-repo fail_under is the coarse backstop, rec #7 Part 1)."""
    added: dict[str, set[int]] = {}
    current: str | None = None
    new_line = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path == "/dev/null":
                current = None
            else:
                # strip a leading b/ (git) and surrounding quotes
                current = re.sub(r"^b/", "", path).strip().strip('"')
                added.setdefault(current, set())
            in_hunk = False
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            new_line = int(m.group(1)) if m else 0
            in_hunk = True
            continue
        if not in_hunk or current is None:
            continue
        if raw.startswith("+"):
            added[current].add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            # deletion: new-side line number does not advance
            continue
        elif raw.startswith("\\"):
            # "\ No newline at end of file"
            continue
        else:
            # context line (leading space) advances the new-side counter
            new_line += 1
    return {f: lines for f, lines in added.items() if lines}

def parse_coverage_json_lines(report: dict) -> dict[str, set[int]]:
    """Pure: executed line numbers per file from a coverage.py JSON report (`coverage json`)."""
    out: dict[str, set[int]] = {}
    for path, info in (report.get("files") or {}).items():
        executed = info.get("executed_lines")
        if executed is None:
            # older coverage shape: derive from summary not available -> treat missing as covered? No.
            executed = []
        out[path] = {int(n) for n in executed}
    return out

def parse_lcov_lines(text: str) -> dict[str, set[int]]:
    """Pure: executed (hit>0) line numbers per file from an LCOV `.info` report (JS/TS toolchains)."""
    out: dict[str, set[int]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            current = line[3:].strip()
            out.setdefault(current, set())
        elif line.startswith("DA:") and current is not None:
            body = line[3:]
            parts = body.split(",")
            if len(parts) >= 2:
                try:
                    lineno, hits = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                if hits > 0:
                    out[current].add(lineno)
        elif line == "end_of_record":
            current = None
    return out

def load_coverage_executed_lines(path: Path) -> dict[str, set[int]]:
    """Auto-detect coverage.py JSON vs LCOV and return executed lines per file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return parse_coverage_json_lines(json.loads(text))
    return parse_lcov_lines(text)

def _match_coverage_path(diff_path: str, executed: dict[str, set[int]]) -> set[int]:
    """Reconcile a repo-relative diff path with a coverage report key (exact, then suffix match)."""
    if diff_path in executed:
        return executed[diff_path]
    for cov_path, lines in executed.items():
        if cov_path.endswith(diff_path) or diff_path.endswith(cov_path):
            return lines
    return set()

COVERAGE_MEASURABLE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".java", ".kt", ".cs", ".php", ".rs", ".scala", ".swift")

def diff_coverage_findings(
    added: dict[str, set[int]], executed: dict[str, set[int]], min_pct: int
) -> dict:
    """Pure: intersect added lines with executed lines; report overall new-line coverage pct and the
    per-file uncovered added lines. Only measurable source files (by extension) count, and a file
    absent from the coverage report is treated as 0% covered -- a new untested module must not pass by
    simply not appearing in the report."""
    total = 0
    covered = 0
    per_file: list[dict] = []
    for path in sorted(added):
        if not path.endswith(COVERAGE_MEASURABLE_SUFFIXES):
            continue
        new_lines = added[path]
        cov = _match_coverage_path(path, executed)
        hit = new_lines & cov
        uncovered = sorted(new_lines - cov)
        total += len(new_lines)
        covered += len(hit)
        if uncovered:
            per_file.append({"file": path, "uncovered": uncovered, "added": len(new_lines), "covered": len(hit)})
    pct = 100.0 if total == 0 else round(100.0 * covered / total, 2)
    return {
        "total_new_lines": total,
        "covered_new_lines": covered,
        "pct": pct,
        "below_floor": total > 0 and pct < min_pct,
        "min_pct": min_pct,
        "files": per_file,
    }

def parse_diff_added_hunks(diff_text: str) -> list[tuple[str, list[str]]]:
    """Pure: list of (file, [added line texts]) per diff hunk, so a check can require an owner/due
    annotation in the SAME hunk that introduced a marker."""
    hunks: list[tuple[str, list[str]]] = []
    current_file: str | None = None
    added: list[str] = []
    in_hunk = False

    def flush():
        if current_file is not None and added:
            hunks.append((current_file, list(added)))

    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            flush()
            added = []
            path = raw[4:].strip()
            current_file = None if path == "/dev/null" else re.sub(r"^b/", "", path).strip().strip('"')
            in_hunk = False
        elif raw.startswith("@@"):
            flush()
            added = []
            in_hunk = True
        elif in_hunk and raw.startswith("+") and not raw.startswith("+++"):
            added.append(raw[1:])
    flush()
    return [(f, lines) for f, lines in hunks if lines]

FLAKY_OWNER_MARKERS = ("owner:", "owner=", "@owner", "assignee:", "assigned:")

def flaky_marker_repo_count(target: Path, markers: list[str], scan_glob: str) -> int:
    """Bounded count of quarantine markers under scanPath -- the monotonic-decrease ratchet's input."""
    if not scan_glob:
        return 0
    lowered = [m.lower() for m in markers]
    count = 0
    seen = 0
    for candidate in sorted(target.glob(scan_glob)):
        paths = [candidate] if candidate.is_file() else (p for p in candidate.rglob("*") if p.is_file())
        for path in paths:
            seen += 1
            if seen > 20000:
                return count
            try:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for m in lowered:
                count += text.count(m)
    return count

SIDE_EFFECT_RECEIPT_KEYS = ("receiptProof", "receipt_proof", "proof")

def load_remediation_ledger(path: Path) -> list[dict]:
    """Read the remediation-obligation ledger (a top-level list or {"obligations": [...]})."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("obligations", [])
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

def _split_top_level_commas(text: str) -> list[str]:
    """Split on commas that are NOT inside quotes, so a quoted scalar containing a comma (e.g.
    `"push, pull_request"`) stays one item rather than being mis-split into two (Codex P1)."""
    items: list[str] = []
    current = ""
    quote: str | None = None
    for char in text:
        if quote is not None:
            current += char
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current += char
        elif char == ",":
            items.append(current)
            current = ""
        else:
            current += char
    items.append(current)
    return [item for item in items if item.strip()]

def _flow_mapping_top_keys(flow: str) -> set[str]:
    """Top-level keys of a YAML flow mapping like `{push: ..., pull_request: {...}}` -> {push,
    pull_request}. Keys nested inside a value (depth > 1) are ignored, and quoted text is skipped, so
    a flow `workflow_dispatch` whose nested input default or quoted value contains `pull_request`
    does not leak that as a top-level trigger (Codex P1)."""
    keys: set[str] = set()
    depth = 0
    token = ""
    quote: str | None = None
    for char in flow:
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            token = ""
        elif depth == 1 and char == ":":
            key = token.strip().lower()
            if re.fullmatch(r"[a-z_]+", key):
                keys.add(key)
            token = ""
        elif depth == 1 and char == ",":
            token = ""
        elif depth == 1:
            token += char
    return keys

def workflow_triggers_on_events(workflow_text: str, events: list[str]) -> set[str]:
    """Pure: which of `events` does a GitHub Actions workflow trigger on? Reads only the TOP-LEVEL
    `on:` key (column 0 -- ignores `jobs.<id>.on`). Handles every real `on:` shape: inline scalar
    (`on: push`), inline flow list (`on: [push, pull_request]`), inline flow mapping (top-level keys
    only), block list (`- push`), and block mapping (first-level keys); strips a leading YAML
    anchor/tag (`on: &events`). Event names appearing only as NESTED config under another trigger are
    never counted (Codex P1). Returns the subset of `events` triggered."""
    event_lookup = {ev.lower(): ev for ev in events}
    lines = workflow_text.splitlines()
    on_idx = None
    # GitHub's trigger key is literally lowercase `on` (text parsing always sees `on:`, never the
    # YAML-boolean `true:`), so match only `on:`/`"on":`/`'on':`, case-sensitive (Codex P1).
    for index, line in enumerate(lines):
        if re.match(r"""^(?:on|"on"|'on')\s*:""", line):
            on_idx = index
            break
    if on_idx is None:
        return set()
    found: set[str] = set()
    # Inline value on the `on:` line (comment stripped, leading anchor/tag like `&events`/`!x` removed).
    inline = lines[on_idx].split(":", 1)[1].split("#", 1)[0].strip()
    inline = re.sub(r"^[&!]\S+\s*", "", inline).strip().lower()
    if inline:
        if inline.startswith("{"):
            names = _flow_mapping_top_keys(inline)
        elif inline.startswith("["):
            # Flow list: split on TOP-LEVEL commas only (quote-aware), so a single quoted scalar like
            # ["push, pull_request"] is one item, not two triggers (Codex P1).
            names = {item.strip().strip("'\"") for item in _split_top_level_commas(inline[1:].rstrip("]"))}
        else:
            names = {inline.strip("'\"")}
        return {event_lookup[name] for name in names if name in event_lookup}
    # Block form: only first-level entries (minimal indent in the block) are triggers; nested config
    # is deeper-indented and ignored. Both block-mapping keys and block-list items are recognized.
    block = []
    for line in lines[on_idx + 1:]:
        if line.strip() and not line[:1].isspace():
            break
        if line.strip() and not line.lstrip().startswith("#"):
            block.append(line)
    if not block:
        return set()
    first_level = min(len(line) - len(line.lstrip(" \t")) for line in block)
    for line in block:
        if len(line) - len(line.lstrip(" \t")) != first_level:
            continue
        entry = line.strip().split("#", 1)[0].strip()
        if entry.startswith("- "):
            name = entry[2:].strip().strip("'\"").lower()
            if name in event_lookup:
                found.add(event_lookup[name])
        else:
            match = re.match(r"""["']?([A-Za-z_]+)["']?\s*:""", entry)
            if match and match.group(1).lower() in event_lookup:
                found.add(event_lookup[match.group(1).lower()])
    return found

def workflow_runs_tests(workflow_text: str, markers: list[str]) -> bool:
    """Pure: does a workflow run a recognized test command? Heuristic substring match against
    built-in test-runner markers plus adapter-declared test-RUN commands (not setup commands)."""
    low = workflow_text.lower()
    return any(marker.strip() and marker.lower() in low for marker in markers)

# How a platform-required-checks probe can come out. Named states rather than a bool, because
# "we could not ask" and "we asked and there is no gate" are different facts and collapsing them is
# how a lane ends up believing in a gate that does not exist.
PLATFORM_PROTECTION_ARMED = "armed"

PLATFORM_PROTECTION_ABSENT = "absent"

PLATFORM_PROTECTION_UNAVAILABLE = "unavailable"

PLATFORM_PROTECTION_UNVERIFIABLE = "unverifiable"

def _platform_plan_refusal(text: str) -> bool:
    """GitHub's "this is a paid feature" refusal, in any casing."""
    return "upgrade to github" in text.lower()

def _protection_required_contexts(payload: dict) -> list[str]:
    checks = payload.get("required_status_checks")
    contexts = checks.get("contexts") if isinstance(checks, dict) else None
    return [str(item) for item in contexts] if isinstance(contexts, list) else []

MERGE_GATE_ENFORCEMENTS = ("off", "advise", "block")

def pr_head_repo_slug(payload: dict) -> str:
    """The owner/repo that owns the PR's HEAD commit, when gh reported one.

    `headRepository.nameWithOwner` is returned directly by gh and is preferred over assembling the
    slug from `headRepositoryOwner.login` + `headRepository.name`, which is the same value with more
    ways to be wrong. The owner-plus-name form is kept only as a fallback for payloads that carry
    one but not the other.
    """
    head = payload.get("headRepository")
    if not isinstance(head, dict):
        return ""
    with_owner = str(head.get("nameWithOwner") or "").strip()
    if with_owner:
        return with_owner
    owner = payload.get("headRepositoryOwner")
    login = str(owner.get("login") or "").strip() if isinstance(owner, dict) else ""
    name = str(head.get("name") or "").strip()
    return f"{login}/{name}" if login and name else ""

def markdown_title_and_summary(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = ""
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            title = match.group(1).strip()
            break
    if not title:
        title = path.stem.replace("-", " ").replace("_", " ").strip().title()
    summary_parts = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            if summary_parts:
                break
            continue
        if stripped.startswith("#") or stripped.startswith("---"):
            continue
        if stripped.startswith(("-", "*", "|", ">", "<!--")):
            continue
        summary_parts.append(stripped)
        if len(" ".join(summary_parts)) >= 320:
            break
    summary = " ".join(summary_parts).strip()
    if len(summary) > 360:
        summary = summary[:357].rstrip() + "..."
    return title, summary or "No plain-language summary found; inspect the source item before export."

def github_issue_number_from_url(issue_url: str) -> str:
    match = re.search(r"/(?:issues|pull)/([0-9]+)(?:$|[?#])", issue_url.strip())
    return match.group(1) if match else ""

def github_repo_from_issue_url(issue_url: str) -> str:
    """`owner/name` from an issue/PR URL, so a cross-repo item is read from ITS repo.

    The adapter's `repo` is the LANE's repo. Using it to fetch a linked issue's body reads a
    DIFFERENT issue that happens to share the number -- which is worse than failing, because it
    succeeds and returns prose.
    """
    # PARSE THE HOST. Do not scan for `github.com` anywhere in the string.
    #
    # This was substring-matched twice and bypassed twice, which is why it now parses:
    #   - `github\.com/` alone matched inside `evilgithub.com/lane/repo/issues/5`.
    #   - Adding a lookbehind for word/dot/hyphen still matched inside
    #     `evil.example/github.com/lane/repo/issues/5`, where the preceding character is `/` --
    #     the host is `evil.example` and `github.com` is just a path segment.
    # Both resolved to a repository the caller never named, and every control that asks this
    # function "is this reference foreign?" inherits such a hole as a bypass -- including this
    # release's own `--issue` guard, which would then comment on the lane's same-numbered issue.
    #
    # Host comparison is case-insensitive (`https://GitHub.com/...` is ordinary to paste, and
    # returning "" for it would make a caller treat a legitimate reference as unresolvable), but
    # the owner/name keeps its original casing; callers that COMPARE repositories normalize case
    # themselves, since GitHub treats them case-insensitively.
    text = (issue_url or "").strip()
    if not text:
        return ""
    # A scheme-less `github.com/o/r/issues/1` is a form the board and operators both produce, and
    # urlsplit would read it as a PATH with no host, so give it one before parsing.
    candidate = text if "//" in text.split("?", 1)[0][:8] else f"https://{text}"
    try:
        host = urllib.parse.urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    if host.lower() not in {"github.com", "www.github.com"}:
        return ""
    path = urllib.parse.urlsplit(candidate).path
    match = re.fullmatch(r"/([^/\s]+/[^/\s]+)/(?:issues|pull)/\d+/?", path)
    return match.group(1) if match else ""

MILESTONE_PROGRESS_HEADING = "## Milestone Progress"

MILESTONE_PROGRESS_START = "<!-- tautline:milestone-progress:start -->"

MILESTONE_PROGRESS_END = "<!-- tautline:milestone-progress:end -->"

# Legacy markers parsed (never emitted) so an already-posted block written under the old brand is
# replaced in place rather than duplicated. Removed at METH-FU-TAUTLINE-FALLBACK-REMOVAL.
LEGACY_MILESTONE_PROGRESS_START = "<!-- minervit:milestone-progress:start -->"

LEGACY_MILESTONE_PROGRESS_END = "<!-- minervit:milestone-progress:end -->"

def upsert_marker_block(
    text: str,
    start_marker: str,
    end_marker: str,
    block: str,
    legacy_markers: tuple[str, str] | None = None,
) -> str:
    """Replace the span from start_marker through end_marker (inclusive) with block, or append
    block when the markers are absent. Everything outside the marker span is preserved, so
    milestone titles and any human edits elsewhere in the issue body can neither participate in
    boundary detection nor be clobbered.

    write-new/read-both: `legacy_markers` lets an already-posted body written under the old brand
    (legacy markers) be replaced in place with the new block+markers rather than duplicated.
    """
    block = block.strip()
    marker_pairs = ((start_marker, end_marker),)
    if legacy_markers is not None:
        marker_pairs += (legacy_markers,)
    for smark, emark in marker_pairs:
        start = text.find(smark)
        end = text.find(emark)
        if start != -1 and end != -1 and end >= start:
            before = text[:start].rstrip()
            after = text[end + len(emark):].strip()
            return "\n\n".join(segment for segment in (before, block, after) if segment) + "\n"
    base = text.strip()
    return (base + "\n\n" + block if base else block) + "\n"

def load_ui_evidence_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ui evidence manifest unreadable: {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit(f"ui evidence manifest must be a JSON object: {path}")
    return manifest

def _print_provider_diff(proposed: dict, current: dict, prefix: str) -> None:
    """Print the proposed backlogProvider vs current diff, one line per board-derived key."""
    for key in ("statusField", "readyStatuses", "activeStatuses", "doneStatuses", "blockedStatuses", "priorityField", "orderField", "schemaHash"):
        print(f"{prefix}: {key} = {proposed.get(key)!r}  (current: {current.get(key)!r})")

def stakeholder_issue_number(issue_ref: str) -> str:
    text = issue_ref.strip()
    if not text:
        return ""
    if re.fullmatch(r"[0-9]+", text):
        return text
    return github_issue_number_from_url(text)

MILESTONE_RUN_SCHEMA = "minervit-milestone-run/v1"

def selected_milestone_item(run: dict, item_index: int | None, pr: str | None = None, require_pr_match: bool = False) -> dict:
    items = run.get("items", [])
    pr_owner = None
    if pr:
        for item in items:
            if str(item.get("pr") or "") == str(pr):
                pr_owner = item
                break
    if item_index is not None:
        for item in items:
            if item.get("index") == item_index:
                if pr_owner and pr_owner.get("index") != item_index:
                    raise SystemExit(
                        f"PR {pr} is already recorded on milestone item {pr_owner.get('index')}; "
                        f"refusing to overwrite item {item_index}"
                    )
                if pr and item.get("pr") and str(item.get("pr")) != str(pr):
                    raise SystemExit(
                        f"milestone item {item_index} already records PR {item.get('pr')}; "
                        f"refusing to overwrite it with PR {pr}"
                    )
                return item
        raise SystemExit(f"milestone item not found: {item_index}")
    if pr_owner:
        return pr_owner
    if pr and require_pr_match:
        raise SystemExit(f"milestone item with PR {pr} not found; pass --item-index to identify the item explicitly")
    current_index = run.get("currentIndex")
    for item in items:
        if item.get("index") == current_index:
            return item
    for item in items:
        if item.get("status") == "in_progress":
            return item
    for item in items:
        if item.get("status") == "pending":
            return item
    raise SystemExit("milestone run has no selectable item")

# 0.9.0 security behavior change (see the sanitized-instrumentation plan's narrative-journals
# section): narrative session journals describe the adopter's product work and can never be proven
# safe to publish, so NO narrative journal can leave the machine. Every publication surface refuses
# outright for every adapter and in every mode (--commit --push, bare --file, and
# --allow-release-checkout-write -- even the no-commit path writes/stages narrative into a git
# worktree and is just as much a leak vector). Journals stay LOCAL evidence via
# prepare-session-journal + validate-session-journal under the lane's gitignored .ai-runs/. The
# replacement for contributing upstream is the sanitized, zero-freeform instrumentation record.
NARRATIVE_JOURNAL_PUBLISH_REFUSAL = (
    "publish_error: narrative session-journal publication is disabled as of 0.9.0. A session "
    "journal narrates the adopter's product work, so it can never be proven safe to publish -- no "
    "narrative journal can leave the machine, in any mode (--commit --push, --file, or "
    "--allow-release-checkout-write). Journals remain LOCAL evidence: create with "
    "prepare-session-journal and inspect with validate-session-journal (both stay under the lane's "
    "gitignored .ai-runs/). To contribute sanitized signal upstream, enable instrumentation and run "
    "`publish-instrumentation-record` -- a closed-vocabulary record with zero product-information "
    "capacity. See docs/reference/session-journals.md and docs/reference/instrumentation.md."
)

def rca_next_action_is_concrete(next_action_lower: str) -> bool:
    if "true blocker" in next_action_lower:
        return True
    if re.search(r"https?://\S+", next_action_lower):
        return True
    if re.search(r"\b(?:minervit-methodology|make|gh|python3?|npm|pnpm|yarn)\s+\S+", next_action_lower):
        return True
    if re.search(r"(?:^|\s)(?:\.?/)?(?:bin|docs|methodology|plugins|scripts|adapters|\.ai-runs|\.ai-work|\.ai-continuity)/[^\s`]+", next_action_lower):
        return True
    if re.search(r"(?:^|\s)(?:readme\.md|claude\.md|agents\.md|\.minervit-ai-delivery\.json)\b", next_action_lower):
        return True
    if re.search(r"\b(?:pr|check)\s*#?\d+\b", next_action_lower):
        return True
    return False

# Sentinel returned by the sub-issue reader when GitHub's native sub_issues GraphQL is unavailable
# (older gh / connection error): degrade to a non-blocking warning, never a false DoR-fail.
GROOMING_SUBISSUES_UNAVAILABLE = "__grooming_subissues_unavailable__"

def grooming_privacy_invariants(data: dict) -> list[str]:
    """Project-declared privacy/security invariants (optional). A project that declares none must
    NOT fail the privacy-negative-test check (over-block guard)."""
    raw = data.get("privacyInvariants")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]

def feature_request_section_is_stub(section: str) -> bool:
    stripped = section.strip()
    if len(stripped) < 12:
        return True
    return bool(re.fullmatch(r"(?is)\s*(?:todo|tbd|placeholder|n/?a|pending|none)\s*", stripped))
