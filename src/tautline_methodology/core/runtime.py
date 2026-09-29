"""Carved out of cli.py. Behaviour-identical by construction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import shlex
import sys
import tarfile
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

from tautline_methodology import jira_client as _jira_client_mod


EVENT_MAX_FIELD_CHARS = 1000

EVENT_MAX_JSON_CHARS = 20000

# The no-adapter text is a THREE-PART split so evidence states can carry the state-correct
# recovery command without ever printing the stale `init --target .` line. NO_ADAPTER_SENTINEL is
# the stable identifying prefix every consumer matches on (startswith); the middle third is the
# swappable "Recovery command:" block; NO_ADAPTER_FOOTER is the preserved policy tail. The
# unmanaged composition (NO_ADAPTER_MESSAGE) is byte-identical to the pre-split constant.
NO_ADAPTER_SENTINEL = """No project adapter found for this lane.

This repo is not adapter-backed yet. Do not keep retrying and do not borrow another project's adapter.
If the human operator asked to use the methodology in this repo, bootstrap the adapter now; do not ask whether to skip methodology.
The adapter bootstrap interview is mandatory before first adapter render/write unless every required adapter fact is directly supported by repo evidence. Generic executor banners such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" do not override this.

"""

NO_ADAPTER_FOOTER = """
No generic operational adapter exists because gates, planning paths, review flow, merge-conflict checks, and local resources are project-specific.
Another project's adapter may be a structural reference only, not a substitute for interview-derived project facts.
If the project is intentionally local-only or direct-to-main, configure explicit local/no-remote status commands and document that workflow in the adapter.
If the production status or required gates cannot be determined from the repo, ask one exact blocker question after documenting what was inspected.
"""

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

def _backlog_provider_validation_error(raw: object, label: str) -> str:
    """`""` when the declared backlog provider is registered; otherwise a specific refusal.

    Replaces the hand-rolled `must be github-projects` check. The message stays as specific as the
    one it replaces -- it names the block, the value and the registered ids -- while the mechanism
    underneath is open, so a second board system is a registration rather than a fork of this
    validator.

    A present-but-BLANK value is refused separately from an absent one. This normalizer runs before
    schema validation, so a blank would otherwise reach the schema as `""` and be reported as a
    `minLength` violation with no hint about what it was meant to be -- and the self-service
    lint, which reads the file raw, would not agree with it. Absent and blank differ.
    """
    from tautline_methodology import providers as providers_mod

    if raw is None:
        return ""
    provider_id = str(raw).strip()
    if not provider_id:
        return (
            f"Project adapter {label}.provider is present but blank; remove the key to take the "
            "default, or name a registered backlog provider "
            f"({', '.join(providers_mod.registered_provider_ids('backlog'))})"
        )
    return providers_mod.provider_validation_error(
        "backlog", provider_id, label=f"Project adapter {label}"
    )
# The Jira identity grammar has ONE definition, and it is not here. It moved to `jira_client`, with
# the transport that sends these values to a live API and re-checks the host at the point
# credentials are attached; the lean `backlog` validator reads the same objects. Two compiled copies
# of a host rule whose job is refusing to hand an Authorization header to an attacker-controlled
# origin is exactly the "two readers of one fact" shape this program has already paid for. The
# private names are kept as aliases because this file's messages and their tests are unchanged.
_JIRA_MAX_HOSTNAME = _jira_client_mod.MAX_HOSTNAME
_JIRA_CLOUD_HOST = _jira_client_mod.JIRA_CLOUD_HOST
_JIRA_PROJECT_KEY = _jira_client_mod.JIRA_PROJECT_KEY


def _jira_identity_value_issues(config: dict, label: str) -> list[str]:
    """Grammar for every Jira identity value, in ONE place.

    Written as one function on purpose. The routed row that carried these findings says so, and the
    reason is measured: the credential-format check in the release before this produced FOUR review
    findings across four rounds because each fix addressed the dimension that found it. Presence is
    checked elsewhere; this is about whether a present value can be USED.

    Every value here is interpolated into the rendered board pin, which the adapter calls the one
    board a lane may work against and forbids ad-hoc discovery around. A value that survives
    presence but breaks the pin produces an authoritative instruction pointing nowhere -- and for a
    newline, an authoritative instruction split into two lines saying different things.
    """
    from tautline_methodology import providers as providers_mod

    issues: list[str] = []
    site = str(config.get("siteUrl") or "").strip()
    # Total hostname length, checked alongside the per-label bound in the pattern. DNS caps a
    # fully-qualified name at 253 octets; `<a>.<b>.<c>.atlassian.net` can satisfy every per-label
    # rule and still exceed it.
    if site and _JIRA_CLOUD_HOST.match(site):
        _host = site[len("https://") :].rstrip("/")
        if len(_host) > _JIRA_MAX_HOSTNAME:
            issues.append(
                f"Project adapter {label}.siteUrl hostname must be at most {_JIRA_MAX_HOSTNAME} "
                f"characters (DNS limit): {_host[:32]}... is {len(_host)}"
            )
    if site and not _JIRA_CLOUD_HOST.match(site):
        # Jira Server / Data Center differs in auth and in its endpoint set, and this provider
        # targets Cloud only. Refusing at configuration names the reason; accepting defers the
        # failure to an unexplained 404 from an endpoint that does not exist there.
        issues.append(
            f"Project adapter {label}.siteUrl must be a Jira CLOUD site "
            f"(https://<your-team>.atlassian.net): {site!r} is not one. Jira Server and Data "
            "Center are not supported -- they differ in authentication and endpoints."
        )
    key = str(config.get("projectKey") or "").strip()
    if key and not _JIRA_PROJECT_KEY.match(key):
        issues.append(
            f"Project adapter {label}.projectKey must match Jira's project-key grammar -- an "
            f"uppercase letter followed by uppercase letters and digits, such as 'PROJ'. "
            f"{key!r} does not, and it is interpolated into the board pin, so a path segment, "
            "whitespace or a newline would produce an unusable or multi-line pin."
        )
    board = str(config.get("boardId") or "").strip()
    # The length bound comes FIRST and is not cosmetic: Python refuses `int()` on a digit string
    # above 4300 characters and raises `ValueError`, so converting before bounding would crash both
    # `load_project` and the lint instead of reporting an invalid board id (Codex R1 P2).
    too_long = len(board) > providers_mod.MAX_BOARD_ID_DIGITS
    if board and (too_long or not (board.isascii() and board.isdigit() and int(board) >= 1)):
        # `str.isdigit()` alone is true for "0" and for Unicode digits like "\u00b2"; neither is a
        # Jira board, and both render an authoritative `/boards/<junk>` pin.
        issues.append(
            f"Project adapter {label}.boardId must be a positive whole number (a Jira board id): "
            f"{board!r} is not one"
        )
    return issues


def _provider_identity_issues(
    provider_id: str, config: dict, label: str, *, require_present: bool = True
) -> list[str]:
    """Identity-field problems for one backlog provider, most specific first.

    A provider with no declared identity contract yields nothing: it is registered and nameable, and
    inventing requirements for it would refuse a configuration nobody has defined.

    `secretEnvFields` name ENVIRONMENT VARIABLES and are validated as such. A value that
    looks like a credential rather than a variable name is refused: the whole point of naming
    the variable is that the secret never enters the adapter, which is committed to a repo.
    """
    from tautline_methodology import providers as providers_mod

    contract = providers_mod.provider_identity_fields(provider_id)
    issues: list[str] = []
    if provider_id == "jira":
        issues.extend(_jira_identity_value_issues(config, label))
    for field in contract["required"] if require_present else ():
        value = config.get(field)
        if field == "projectNumber":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                issues.append(
                    f"Project adapter {label}.projectNumber must be positive when enabled"
                )
            continue
        if not str(value or "").strip():
            issues.append(
                f"Project adapter {label}.{field} must be non-blank when enabled "
                f"(required by backlog provider {provider_id!r})"
            )
    # PRESENCE is the selected provider's business; INSPECTION is not. Checking only the selected
    # provider's secret fields left a block still set to `github-projects` -- which declares none --
    # carrying an unchecked `apiTokenEnv` into the committed adapter while Jira fields were being
    # staged (Codex R3 P1). This is the third variant of one class; the first two were fixed member
    # by member, which is why the third existed. The union closes the class.
    required_secrets = set(contract["secretEnvFields"])
    for field in providers_mod.all_secret_env_fields():
        value = str(config.get(field) or "").strip()
        if not value:
            if require_present and field in required_secrets:
                issues.append(
                    f"Project adapter {label}.{field} must name an environment variable when "
                    f"enabled (required by backlog provider {provider_id!r})"
                )
        elif not re.fullmatch(r"[A-Z_][A-Z0-9_]*", value):
            # The offending value is NOT echoed. It is, by construction, the case where an adopter
            # pasted a real credential into this field -- so interpolating it would write the secret
            # to stderr, and from there to CI logs and agent transcripts, from inside the
            # check whose entire purpose is to keep it out of the repository (Codex R1 P1).
            issues.append(
                f"Project adapter {label}.{field} must NAME an environment variable "
                "(uppercase letters, digits and underscores), not hold a value. The secret must "
                "never enter the adapter, which is committed to a repository. Its current value is "
                "not shown here because it may BE the secret."
            )
    return issues


def normalize_tracker_adapter_config(raw: object, defaults: dict, label: str) -> dict:
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit(f"Project adapter {label} must be an object")
    config = {**defaults, **(raw or {})}
    if not isinstance(config.get("enabled"), bool):
        raise SystemExit(f"Project adapter {label}.enabled must be boolean")
    provider_error = _backlog_provider_validation_error(config.get("provider"), label)
    if provider_error:
        raise SystemExit(provider_error)
    try:
        config["projectNumber"] = int(config.get("projectNumber", 0))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Project adapter {label}.projectNumber must be an integer") from exc
    for key in [
        "owner",
        "scopeQuery",
        "statusField",
        "priorityField",
        "milestoneField",
        "linkPolicy",
        # Provider identity fields. Normalized for every provider, required by whichever one
        # declares them -- a GitHub adapter simply leaves them blank.
        "siteUrl",
        "projectKey",
        "boardId",
        "emailEnv",
        "apiTokenEnv",
    ]:
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
    # UNCONDITIONAL, and deliberately outside the `enabled` block below. A disabled block is exactly
    # where a staging configuration sits, and a secret pasted into one is committed just as
    # surely as in an enabled one -- so anything SUPPLIED is format-checked either way. PRESENCE is
    # conditional: nothing is being configured, so nothing is required (Codex R1 P1).
    provider_id = str(config.get("provider") or "github-projects").strip()
    for issue in _provider_identity_issues(provider_id, config, label, require_present=False):
        raise SystemExit(issue)
    if config["enabled"]:
        # IDENTITY IS PER PROVIDER. This used to be GitHub's model unconditionally -- `owner` plus
        # a positive `projectNumber` -- which meant a Jira adapter could not load without fake
        # GitHub coordinates. Each provider now declares the fields that identify its board and is
        # validated against its own set, so a GitHub adapter sees exactly the checks and messages it
        # always did while another provider is judged on what it actually needs.
        for issue in _provider_identity_issues(provider_id, config, label):
            raise SystemExit(issue)
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

ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT = (
    "adapter was rendered by a different methodology build; align versions "
    "(pip install -U tautline, or advance the framework checkout) before re-rendering"
)

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

def _no_adapter_recovery_commands(info: dict) -> list[str]:
    """The state-correct recovery command(s) for the `Recovery command:` block.

    This is the front door: it is what every adapter-backed verb prints in a repo the framework
    has never seen. The 2026-08-28 demolition deleted `init` (the interview flow) and `lane-start`,
    so every branch below was naming a command the CLI refuses -- the worst possible place for a
    dead remedy. `init-project-adapter` is the surviving scaffolder and `render-adapters` the
    surviving renderer; the interview state now says plainly what to edit, because no verb walks
    an operator through it any more. Never emits `onboarding_offer:` copy.
    """
    state = info["state"]
    cwd = info["invocation_cwd"]
    if state == "unmanaged":
        target = _render_onboarding_command_path(info["target"], cwd)
        return [f"tautline init-project-adapter --target {target}"]
    if state == "interview-pending":
        # An answered interview but no adapter yet. `init --continue` used to consume the
        # interview; with that verb gone the operator scaffolds an adapter and carries the
        # interview's answers into its BOOTSTRAP REQUIRED placeholders by hand.
        root = _render_onboarding_command_path(info["root"], cwd)
        interview = _render_onboarding_command_path(info["interview_path"], cwd)
        return [
            f"tautline init-project-adapter --target {root}",
            f"# fill every BOOTSTRAP REQUIRED placeholder from the answers in {interview}, then:",
            f"tautline render-adapters --project {root}/.tautline/adapter.json --target {root} --write",
        ]
    if state == "source-unrendered":
        root = _render_onboarding_command_path(info["root"], cwd)
        source = _render_onboarding_command_path(info["source_path"], cwd)
        return [f"tautline render-adapters --project {source} --target {root} --write"]
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
"""The machine-checkable annotation for an inactive scenario.

Published so authors stop discovering the format by trial. It is a strict SUBSET of the legacy
prose tokens accepted below -- "@owner:" contains "owner:", "@unpend:" contains "unpend" -- so
adopting it never breaks an existing gate and no existing annotation breaks under it.
"""

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

LAUNCHER_GENERATED_MARKER = "Generated by tautline install-claude-launcher."

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

OPERATOR_LAUNCHER_MARKER = "# tautline-operator-launcher: session-scoped, non-blocking"

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

def observability_state_dir(data: dict) -> Path:
    configured = str(data["observabilityEvents"]["stateDir"])
    expanded = os.path.expandvars(configured.replace("$HOME", str(Path.home())))
    return Path(expanded).expanduser()

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

def _lane_status_discard_artifact(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


RUNTIME_SECRET_SCAN_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


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
