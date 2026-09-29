"""GitHub provider cache, lock, and rate-budget primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse
from collections.abc import Mapping
from typing import Callable

from .util import resolve_env, write_text_atomic


GITHUB_CACHE_TTL_SECONDS = 300
# The board's field schema (names, ids, single-select options) is operator-authored and changes at
# most a few times a project. Re-reading it on the 300s default was 43% of ALL measured GraphQL
# spend (2,619 calls / 267,138 points) and 220 of the 247 calls that were refused outright for a
# spent budget -- the schema fetch, not real work, is what took lanes down.
GITHUB_FIELD_SCHEMA_TTL_SECONDS = 86400
# GraphQL cost is (items x fieldValues) / 100, so this page size is the whole per-read price:
# 12 -> 13 points per 100 items against gh project item-list's 102. The board that produced these
# numbers carries at most 8 values on any item, so 12 leaves headroom; a board that exceeds it is
# caught by github_project_field_values_truncated() and re-read wider rather than silently clipped.
GITHUB_PROJECT_FIELD_VALUE_PAGE = 12
GITHUB_PROJECT_FIELD_VALUE_PAGE_MAX = 50
GITHUB_PROJECT_ITEM_PAGE = 100
# `gh project item-list` defaults to 30 when --limit is omitted; the translation matches it so an
# omitted flag does not quietly widen the result set.
GITHUB_PROJECT_DEFAULT_ITEM_LIMIT = 30
GITHUB_SHARED_SNAPSHOT_SECONDS = 15
GITHUB_RATE_LIMIT_LOW_WATERMARK = 100
GITHUB_LOCK_TIMEOUT_SECONDS = 30

# --- Per-lane GitHub identity (item 86; RCA 20260630T202308Z Control 4) ---------------------------
#
# Freshness IS the liveness signal: there is no lane heartbeat to consult, and a pid check would
# call a lane dead the moment its shell exits between commands.
GITHUB_IDENTITY_ACTIVE_SECONDS = 90 * 60
# A steady-state lane start must cost ZERO subprocesses. Without the memo, every start pays
# `gh auth token` even when nothing about the identity could have changed.
GITHUB_IDENTITY_MEMO_SECONDS = 900
# A hard ceiling on cold resolution. This whole subsystem is advisory, and an advisory that can
# add ten seconds to `lane-start` will be switched off by whoever notices.
GITHUB_IDENTITY_BUDGET_SECONDS = 8
GITHUB_IDENTITY_RECORD_SCHEMA = "tautline-github-identity/v1"
# A TUPLE of tuples, not an UPPER_CASE list-of-str: that shape auto-enters the policy-phrases SSOT
# collector, and these are command tokens, not policy phrases.
GITHUB_LOCAL_ONLY_GH_COMMANDS = (("auth", "token"),)
GITHUB_LOCK_STALE_SECONDS = 120
GITHUB_PENDING_RETRY_MIN_SECONDS = 60
GITHUB_PENDING_RETRY_MAX_SECONDS = 900
GITHUB_RECENT_CALL_LIMIT = 25


def github_cache_root() -> Path:
    return Path(resolve_env("MINERVIT_GITHUB_CACHE_DIR") or (Path.home() / ".cache" / "minervit" / "github"))


def github_provider_state_root() -> Path:
    return Path(resolve_env("MINERVIT_GITHUB_TELEMETRY_DIR") or github_cache_root())


def github_lock_path() -> Path:
    return github_cache_root() / ".request.lock"


def github_operation_lock_path(args: list[str]) -> Path:
    return github_cache_root() / "locks" / f"{github_cache_key(args)}.lock"


def github_lock_timeout_seconds() -> float:
    try:
        return max(0.0, float(resolve_env("MINERVIT_GITHUB_LOCK_TIMEOUT_SECONDS", str(GITHUB_LOCK_TIMEOUT_SECONDS))))
    except ValueError:
        return float(GITHUB_LOCK_TIMEOUT_SECONDS)


def github_lock_stale_seconds() -> float:
    try:
        return max(1.0, float(resolve_env("MINERVIT_GITHUB_LOCK_STALE_SECONDS", str(GITHUB_LOCK_STALE_SECONDS))))
    except ValueError:
        return float(GITHUB_LOCK_STALE_SECONDS)


def github_process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return github_windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def github_windows_process_exists(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if proc.returncode != 0:
        return True
    for line in proc.stdout.splitlines():
        if line.strip().upper().startswith("INFO:"):
            continue
        cells = [cell.strip().strip('"') for cell in line.split(",")]
        if len(cells) >= 2 and cells[1] == str(pid):
            return True
    return False


def github_lock_owner(lock: Path) -> dict:
    owner_path = lock / "owner.json"
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        owner = {}
    return owner if isinstance(owner, dict) else {}


def github_lock_snapshot(lock: Path) -> dict:
    stat_result = lock.stat()
    owner = github_lock_owner(lock)
    try:
        created_at = float(owner.get("created_at_epoch", stat_result.st_mtime))
    except (TypeError, ValueError):
        created_at = stat_result.st_mtime
    try:
        pid = int(owner.get("pid", 0) or 0)
    except (TypeError, ValueError):
        pid = 0
    age_seconds = max(0.0, time.time() - created_at)
    return {
        "age_seconds": age_seconds,
        "created_at_epoch": created_at,
        "owner": owner,
        "pid": pid,
        "schema": str(owner.get("schema") or "legacy-empty-directory"),
        "token": str(owner.get("token") or ""),
    }


def github_lock_stale_reason(lock: Path, process_exists: Callable[[int], bool] | None = None) -> str:
    try:
        snapshot = github_lock_snapshot(lock)
    except FileNotFoundError:
        return "lock vanished before inspection"
    process_exists = process_exists or github_process_exists
    pid = int(snapshot["pid"])
    age_seconds = float(snapshot["age_seconds"])
    stale_seconds = github_lock_stale_seconds()
    if pid and not process_exists(pid):
        return f"owner pid {pid} is not running"
    if pid:
        return ""
    if age_seconds >= stale_seconds:
        return f"age {age_seconds:.1f}s exceeded stale threshold {stale_seconds:.1f}s"
    return ""


def github_lock_summary(lock: Path) -> str:
    try:
        snapshot = github_lock_snapshot(lock)
    except FileNotFoundError:
        return f"path={lock} state=missing"
    owner = snapshot["owner"] if isinstance(snapshot.get("owner"), dict) else {}
    command = str(owner.get("command") or "unknown")
    return (
        f"path={lock} schema={snapshot['schema']} pid={snapshot['pid'] or 'unknown'} "
        f"age={float(snapshot['age_seconds']):.1f}s command={command}"
    )


def github_remove_lock(lock: Path, reason: str) -> bool:
    try:
        shutil.rmtree(lock)
    except FileNotFoundError:
        return True
    except OSError as exc:
        print(f"github_lock_stale_remove_failed: path={lock} reason={reason} error={exc}", file=sys.stderr)
        return False
    print(f"github_lock_stale_removed: path={lock} reason={reason}", file=sys.stderr)
    return True


def github_lock_token(command: list[str]) -> str:
    return f"{os.getpid()}:{time.time_ns()}:{github_cache_key([str(part) for part in command])[:12]}"


def github_write_lock_owner(lock: Path, token: str, command: list[str], label: str) -> None:
    owner = {
        "schema": "minervit-github-lock/v1",
        "label": label,
        "pid": os.getpid(),
        "token": token,
        "created_at_epoch": time.time(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(shlex.quote(str(part)) for part in command[:16]),
    }
    (lock / "owner.json").write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def github_acquire_lock(
    lock: Path, command: list[str], label: str, max_wait: float | None = None
) -> str:
    """Acquire the machine-wide gh lock, optionally bounded by a CALLER's deadline.

    `max_wait` defaults to None, which keeps the existing 30-second behaviour for every caller that
    does not pass one -- the lock exists for rate-limit protection and most callers should wait.
    A caller that ADVERTISES a ceiling has to be able to enforce it, though: without this, an
    eight-second identity budget bounded only the subprocess while the lock wait ran unbounded
    ahead of it, so `lane-start` could block for 30 seconds and only then report that the budget
    was exceeded (Codex R5).
    """
    timeout_seconds = github_lock_timeout_seconds()
    if max_wait is not None:
        timeout_seconds = max(0.0, min(timeout_seconds, float(max_wait)))
    deadline = time.monotonic() + timeout_seconds
    token = github_lock_token(command)
    while True:
        try:
            lock.mkdir()
            github_write_lock_owner(lock, token, command, label)
            return token
        except FileExistsError:
            stale_reason = github_lock_stale_reason(lock)
            if stale_reason and github_remove_lock(lock, stale_reason):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"{label}: timed out after {timeout_seconds:.1f}s waiting for GitHub CLI lock; "
                    f"{github_lock_summary(lock)}"
                ) from None
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        except OSError:
            if lock.is_dir():
                github_remove_lock(lock, "failed to write lock owner metadata")
            raise


def github_release_lock(lock: Path, token: str) -> None:
    owner = github_lock_owner(lock)
    if owner.get("token") != token:
        return
    try:
        shutil.rmtree(lock)
    except FileNotFoundError:
        pass
    except OSError:
        pass


@contextmanager
def github_command_lock(command: list[str], max_wait: float | None = None):
    """Machine-local serialization for GitHub CLI calls so concurrent lanes do not stampede limits."""
    if not command or command[0] != "gh" or resolve_env("MINERVIT_GITHUB_SERIALIZE", "1") == "0":
        yield
        return
    if tuple(command[1:3]) in GITHUB_LOCAL_ONLY_GH_COMMANDS:
        # `gh auth token` reads the LOCAL credential store and issues no API request, so
        # serializing it behind a machine-wide lock buys zero rate-limit protection while costing
        # up to the full acquire timeout on every lane start. The exemption is keyed on the
        # command, not on a caller flag, so a new caller of the same command cannot forget it.
        yield
        return
    root = github_cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"github_request_lock_unavailable_warn: {root}: {exc}; continuing without serialization", file=sys.stderr)
        yield
        return
    lock = github_lock_path()
    try:
        token = github_acquire_lock(lock, command, "github_request_lock", max_wait=max_wait)
    except TimeoutError as exc:
        print(f"github_request_lock_timeout_warn: {exc}; continuing without serialization", file=sys.stderr)
        yield
        return
    except OSError as exc:
        print(f"github_request_lock_unavailable_warn: {lock}: {exc}; continuing without serialization", file=sys.stderr)
        yield
        return
    try:
        yield
    finally:
        github_release_lock(lock, token)


@contextmanager
def github_operation_lock(args: list[str]):
    """Operation-level coalescing lock: one process populates a shared snapshot, followers re-read it."""
    if resolve_env("MINERVIT_GITHUB_COALESCE", "1") == "0":
        yield
        return
    root = github_operation_lock_path(args).parent
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"github_operation_lock_unavailable_warn: {root}: {exc}; continuing without coalescing", file=sys.stderr)
        yield
        return
    lock = github_operation_lock_path(args)
    try:
        token = github_acquire_lock(lock, ["gh", *args], "github_operation_lock")
    except TimeoutError as exc:
        print(f"github_operation_lock_timeout_warn: {exc}; continuing without coalescing", file=sys.stderr)
        yield
        return
    except OSError as exc:
        print(f"github_operation_lock_unavailable_warn: {lock}: {exc}; continuing without coalescing", file=sys.stderr)
        yield
        return
    try:
        yield
    finally:
        github_release_lock(lock, token)


def github_cache_ttl_seconds() -> int:
    try:
        return max(0, int(resolve_env("MINERVIT_GITHUB_CACHE_TTL_SECONDS", str(GITHUB_CACHE_TTL_SECONDS))))
    except ValueError:
        return GITHUB_CACHE_TTL_SECONDS


def github_low_watermark() -> int:
    try:
        return max(0, int(resolve_env("MINERVIT_GITHUB_GRAPHQL_LOW_WATERMARK", str(GITHUB_RATE_LIMIT_LOW_WATERMARK))))
    except ValueError:
        return GITHUB_RATE_LIMIT_LOW_WATERMARK


def github_cache_read_mode() -> str:
    mode = resolve_env("MINERVIT_GITHUB_CACHE_READ_MODE", "low-budget").strip().lower()
    return mode if mode in {"low-budget", "always"} else "low-budget"


def github_shared_snapshot_seconds() -> int:
    try:
        return max(0, int(resolve_env("MINERVIT_GITHUB_SHARED_SNAPSHOT_SECONDS", str(GITHUB_SHARED_SNAPSHOT_SECONDS))))
    except ValueError:
        return GITHUB_SHARED_SNAPSHOT_SECONDS


def github_pending_retry_min_seconds() -> int:
    try:
        return max(1, int(resolve_env("MINERVIT_GITHUB_RETRY_MIN_SECONDS", str(GITHUB_PENDING_RETRY_MIN_SECONDS))))
    except ValueError:
        return GITHUB_PENDING_RETRY_MIN_SECONDS


def github_pending_retry_max_seconds() -> int:
    try:
        return max(github_pending_retry_min_seconds(), int(resolve_env("MINERVIT_GITHUB_RETRY_MAX_SECONDS", str(GITHUB_PENDING_RETRY_MAX_SECONDS))))
    except ValueError:
        return GITHUB_PENDING_RETRY_MAX_SECONDS


def github_cache_key(args: list[str]) -> str:
    payload = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_GH_IDENTITY: str | None = None


def github_identity_reset() -> None:
    """Drop the memoized identity (tests, and any caller that switches credentials in-process)."""
    global _GH_IDENTITY
    _GH_IDENTITY = None


# Every env var gh accepts as a credential ahead of hosts.yml. The ENTERPRISE pair is not
# optional trivia: on GitHub Enterprise Server it is the normal way to authenticate, and omitting
# it let two different enterprise credentials share one 24h schema cache (Codex v4 P1).
GH_TOKEN_ENV_NAMES = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)


def github_gh_config_root(os_name: str = "") -> Path:
    """Where gh keeps hosts.yml, following gh's own lookup order.

    `os_name` is a parameter rather than a read of os.name so the Windows branch is testable:
    monkeypatching os.name globally makes pathlib try to build a WindowsPath on POSIX.
    """
    explicit = resolve_env("GH_CONFIG_DIR").strip()
    if explicit:
        return Path(explicit)
    xdg = resolve_env("XDG_CONFIG_HOME").strip()
    if xdg:
        return Path(xdg) / "gh"
    appdata = resolve_env("AppData").strip()
    if (os_name or os.name) == "nt" and appdata:
        # gh's documented Windows default. Without it a Windows lane resolves no identity, loses
        # the long-lived cache entirely, and keeps paying full price for every field-list read --
        # fail-safe, but it silently withholds the whole point of this release (Codex v4 P2).
        return Path(appdata) / "GitHub CLI"
    return Path.home() / ".config" / "gh"


def github_token_credential_in_env() -> bool:
    """A token in the environment authenticates gh regardless of hosts.yml, and the resolver
    cannot tell two tokens apart without deriving a key from the secret itself."""
    return any(resolve_env(name).strip() for name in GH_TOKEN_ENV_NAMES)


def github_active_identity() -> str:
    """The host+account `gh` will authenticate as, read from gh's OWN on-disk config.

    Deliberately not a request and not a subprocess: this runs on the read path whose cost this
    release exists to cut, so resolving the identity must not add to it. Only host and account
    NAMES are read -- never a token, which must not end up in a cache key derivation.

    A best-effort empty string is safe: it degrades to the previous, unscoped key rather than
    failing a board read over an unreadable config file.
    """
    global _GH_IDENTITY
    if _GH_IDENTITY is not None:
        return _GH_IDENTITY
    if github_token_credential_in_env():
        # GH_TOKEN/GITHUB_TOKEN take PRECEDENCE over hosts.yml, so two different tokens resolve to
        # the SAME stored identity. Rather than derive a key from a secret, an indistinguishable
        # credential simply yields no identity -- and no long-lived cache (Codex R1(g) P2).
        _GH_IDENTITY = ""
        return _GH_IDENTITY
    parts: list[str] = []
    host_override = resolve_env("GH_HOST").strip()
    if host_override:
        parts.append(f"host={host_override}")
    config = github_gh_config_root() / "hosts.yml"
    try:
        current_host = ""
        for line in config.read_text(encoding="utf-8").splitlines():
            if line[:1] not in {" ", "\t", "", "#"} and line.rstrip().endswith(":"):
                current_host = line.strip().rstrip(":")
                continue
            stripped = line.strip()
            # `user:` is gh's active account for that host. `users:` is the roster, not the
            # selection, so it is deliberately not matched here.
            if stripped.startswith("user:"):
                parts.append(f"{current_host}/{stripped.split(':', 1)[1].strip()}")
    except OSError:
        pass
    _GH_IDENTITY = "|".join(parts)
    return _GH_IDENTITY


def github_cache_path(args: list[str]) -> Path:
    # A field schema is board-scoped in the argv but CREDENTIAL-scoped in reality: the same board
    # number resolves differently, or not at all, for another account. Folding the identity into
    # the key means `gh auth switch` simply misses instead of serving another account's private
    # schema metadata for 24h (Codex R1(f) P2). Only schema entries are re-keyed, so every other
    # cached read keeps its existing key and nothing is invalidated wholesale.
    key_args = args
    if github_args_are_schema_cacheable(args):
        identity = github_active_identity()
        if identity:
            key_args = [*args, f"__gh_identity={identity}"]
    return github_cache_root() / f"{github_cache_key(key_args)}.json"


def github_pending_retry_path(args: list[str]) -> Path:
    return github_provider_state_root() / "pending-retries" / f"{github_cache_key(args)}.json"


def github_telemetry_path() -> Path:
    return github_provider_state_root() / "provider-telemetry.jsonl"


def github_graphql_query_text(args: list[str]) -> str:
    for index, arg in enumerate(args):
        if arg.startswith("query="):
            return arg.split("=", 1)[1]
        if arg in {"-f", "-F", "--field", "--raw-field"} and index + 1 < len(args):
            nxt = args[index + 1]
            if nxt.startswith("query="):
                return nxt.split("=", 1)[1]
    return ""


def github_args_are_graphql_read(args: list[str]) -> bool:
    if len(args) < 2 or args[0] != "api" or args[1] != "graphql":
        return False
    query = github_graphql_query_text(args).lstrip().lower()
    return bool(query) and query.startswith("query")


def github_args_are_cacheable_read(args: list[str]) -> bool:
    if len(args) >= 2 and args[0] == "project" and args[1] in {"field-list", "view", "item-list"}:
        return True
    if github_args_are_graphql_read(args):
        return True
    if len(args) >= 2 and args[0] == "issue" and args[1] in {"list", "view"}:
        return True
    if len(args) >= 2 and args[0] == "run" and args[1] in {"list", "view"}:
        return True
    return False


def github_args_are_heavy_graphql(args: list[str]) -> bool:
    if len(args) >= 2 and args[0] == "project" and args[1] in {"field-list", "view", "item-list"}:
        return True
    return github_args_are_graphql_read(args)


# --- `gh project` read translation --------------------------------------------------------
# `gh project item-list/field-list/view` are GraphQL under the hood (Projects V2 has no REST API at
# all), but gh's generated query is charged ~102 points where the equivalent hand-written query is
# charged 11 or 1. At 5000 points/hour that is the difference between ~49 board reads an hour and
# effectively unlimited. These helpers translate the argv the call sites already build into a
# GraphQL call and reshape the response back into gh's exact JSON shape, so no call site changes.

_PROJECT_TRANSLATABLE_READS = {"item-list", "field-list", "view"}

# Selecting a value type also names its field, so the reshaper can key by field name like gh does.
_FIELD_NAME_SELECTION = "field{...on ProjectV2FieldCommon{name}}"
_ITEM_FIELD_VALUE_SELECTION = " ".join(
    [
        "__typename",
        "... on ProjectV2ItemFieldTextValue{text " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldSingleSelectValue{name " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldNumberValue{number " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldDateValue{date " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldIterationValue{title " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldLabelValue{labels(first:50){totalCount nodes{name}} "
        + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldUserValue{users(first:50){totalCount nodes{login}} "
        + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldRepositoryValue{repository{url} " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldPullRequestValue{pullRequests(first:50){totalCount nodes{url}} "
        + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldMilestoneValue{milestone{title} " + _FIELD_NAME_SELECTION + "}",
        # Reviewers and multi-select are real board value types. Without a fragment the value is
        # dropped -- and silently, because the node still counts toward fieldValues.totalCount, so
        # the truncation guard reads the page as complete (Codex R1 P2).
        # RequestedReviewer is a 5-member union: a bot, mannequin or enterprise team would
        # otherwise select nothing and be dropped WITHOUT tripping the truncation guard,
        # because the empty node still counts toward totalCount (Codex R1(c) P2).
        "... on ProjectV2ItemFieldReviewerValue{reviewers(first:50){totalCount nodes{"
        "... on User{login} ... on Team{name} ... on Bot{login}"
        " ... on Mannequin{login} ... on EnterpriseTeam{name}}} " + _FIELD_NAME_SELECTION + "}",
        "... on ProjectV2ItemFieldMultiSelectValue{options{name} " + _FIELD_NAME_SELECTION + "}",
        # An issue-field-backed board field (the live board's `Priority` is one, on 53 of 100
        # items) arrives as ProjectV2ItemIssueFieldValue wrapping its own union. gh drops these
        # too, so this is not a parity regression -- but the adapter configures `priorityField`
        # and can order work by it, and a blank priority silently falls back to status/position
        # ordering (Codex R1(b) P1).
        "... on ProjectV2ItemIssueFieldValue{issueFieldValue{__typename"
        " ... on IssueFieldSingleSelectValue{name}"
        " ... on IssueFieldTextValue{value}"
        " ... on IssueFieldNumberValue{value}"
        " ... on IssueFieldDateValue{value}"
        " ... on IssueFieldMultiSelectValue{value}} " + _FIELD_NAME_SELECTION + "}",
    ]
)
# `state` is selected deliberately: gh's item-list drops it, which forced a per-item REST
# `issue view` fallback (10,277 calls in the measured telemetry). Inline state removes that
# fallback entirely.
# `body` is selected for parity: goal_tracker_item_body() reads it straight off the board payload.
# It costs bandwidth but no quota -- GraphQL cost is node-count based, not field-count based.
_ITEM_CONTENT_SELECTION = (
    "__typename"
    " ... on Issue{number title url state body repository{nameWithOwner}}"
    " ... on PullRequest{number title url state body repository{nameWithOwner}}"
    " ... on DraftIssue{title body}"
)


# GraphQL validates the WHOLE query before executing any of it, so a host whose schema predates a
# type this query names rejects every board read -- on a host where `gh project` works fine. These
# are the shapes that mean "this host cannot run the query", as distinct from a genuine failure
# (not found, forbidden) which must surface rather than be masked by a second call (Codex v4 P1).
_TRANSLATION_UNSUPPORTED_MARKERS = (
    # GitHub runs graphql-ruby; these are ITS wordings, not the ones a spec reading suggests.
    "no such type",
    "can't be a fragment condition",
    "can't be spread inside",
    "cannot be spread inside",
    "cannot be spread here",
    # Plus the more universal phrasings, for proxies and future validators.
    "unknown type",
    "unknown argument",
    "unknown fragment",
    "doesn't exist on type",
    "does not exist on type",
    "cannot query field",
    "no such field",
)


def github_project_translation_unsupported(error: str, payload: object = None) -> bool:
    """Whether a failed board query means the HOST cannot run it, rather than that the read
    itself failed.

    The payload SHAPE decides it first, because wording is a moving target and guessing wrong is
    what made the first version of this fallback a no-op on exactly the hosts it targets (Codex
    v4 R3 P1). GraphQL specifies the difference: a document rejected at VALIDATION returns
    `errors` with no `data` key at all, while a document that ran and failed returns `data`
    alongside its errors. "Could not resolve to a ProjectV2" and "not accessible" are the latter
    and must surface, never be masked by a silent retry.

    The marker list remains as a fallback for transports that hand back only a message string.
    """
    if isinstance(payload, dict) and payload.get("errors") and "data" not in payload:
        return True
    text = str(error or "").lower()
    return any(marker in text for marker in _TRANSLATION_UNSUPPORTED_MARKERS)


def github_project_read_plan(args: list[str]) -> dict | None:
    """Recognize a `gh project` READ that can be served by a hand-written GraphQL query.

    Returns None -- meaning "leave it on gh" -- for anything this translation does not reproduce
    exactly: mutations, non-JSON output, a missing owner, and `--query` scope filters (gh's
    `--query` support is version-dependent and its totalCount semantics under a filter are already
    distrusted by the caller, so re-implementing it would be guessing).
    """
    if len(args) < 3 or args[0] != "project" or args[1] not in _PROJECT_TRANSLATABLE_READS:
        return None
    kind = args[1]
    rest = args[2:]
    if "--query" in rest:
        return None
    number = ""
    owner = ""
    limit = 0
    saw_json = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--owner" and index + 1 < len(rest):
            owner = rest[index + 1]
            index += 2
            continue
        if token == "--format" and index + 1 < len(rest):
            saw_json = rest[index + 1] == "json"
            index += 2
            continue
        if token == "--limit" and index + 1 < len(rest):
            try:
                limit = int(rest[index + 1])
            except ValueError:
                return None
            index += 2
            continue
        if token.startswith("-"):
            # An unrecognized flag could change the result set; do not pretend to honor it.
            return None
        if not number:
            number = token
        index += 1
    if not saw_json or not owner or not number:
        return None
    plan = {"kind": kind, "owner": owner, "number": number}
    if kind in {"item-list", "field-list"}:
        # gh defaults BOTH to --limit 30 and accepts an explicit one; hardcoding 100 in the query
        # returned a different set than gh on a board with more than 30 fields (Codex R1(e) P2).
        plan["limit"] = limit or GITHUB_PROJECT_DEFAULT_ITEM_LIMIT
    if kind == "field-list" and plan["limit"] > GITHUB_PROJECT_ITEM_PAGE:
        # GraphQL caps `first` at 100 and the field-list fetch has no cursor loop, so a larger
        # limit would turn a read gh serves fine into a query error. Leave it on gh rather than
        # half-implement pagination for a board with 100+ fields (Codex R1(g) P2).
        return None
    return plan


def github_project_owner_is_viewer(owner: object) -> bool:
    """`@me` is gh's shorthand for the authenticated user, not a login."""
    return str(owner or "").strip().lower() == "@me"


def github_project_graphql_query(
    plan: dict, field_value_page: int = GITHUB_PROJECT_FIELD_VALUE_PAGE
) -> str:
    """The inlined query text. `repositoryOwner` with a ProjectV2Owner fragment resolves both
    user-owned and organization-owned boards in one shape, so there is no second code path (and no
    speculative second request to discover which one it is)."""
    kind = plan.get("kind")
    if kind == "view":
        body = "id title url number shortDescription public closed"
    elif kind == "field-list":
        body = (
            "fields(first:" + str(int(plan.get("limit") or GITHUB_PROJECT_DEFAULT_ITEM_LIMIT))
            + "){ totalCount nodes{ __typename "
            "... on ProjectV2FieldCommon{id name} "
            "... on ProjectV2SingleSelectField{id name options{id name}} "
            "... on ProjectV2IterationField{id name} } }"
        )
    else:
        # Built by concatenation rather than an f-string: the GraphQL braces and f-string escaping
        # are easy to get wrong together, and a mismatch here is a syntax error on every board read.
        body = (
            "items(first:$first, after:$after){ totalCount pageInfo{hasNextPage endCursor}"
            " nodes{"
            " id"
            " content{ " + _ITEM_CONTENT_SELECTION + " }"
            " fieldValues(first:" + str(int(field_value_page)) + "){"
            " totalCount nodes{ " + _ITEM_FIELD_VALUE_SELECTION + " }"
            " }"  # fieldValues
            " }"  # nodes
            " }"  # items
        )
    # `gh project --owner "@me"` is documented gh syntax and the adapter types `owner` as a bare
    # string, so an adapter may legitimately carry it. `@me` is not a GitHub login: handing it to
    # `repositoryOwner(login:)` fails EVERY translated read (Codex R1 P1). GraphQL already names
    # the authenticated user `viewer`, so it resolves in the same request -- no extra round trip,
    # and no $owner variable, which would be an unused-variable error.
    viewer_owner = github_project_owner_is_viewer(plan.get("owner"))
    variables = "$number:Int!" if viewer_owner else "$owner:String!,$number:Int!"
    if kind == "item-list":
        variables += ",$first:Int!,$after:String"
    root = (
        "viewer{ "
        if viewer_owner
        else "repositoryOwner(login:$owner){ ... on ProjectV2Owner { "
    )
    closing = " } }" if viewer_owner else " } } }"
    return (
        "query(" + variables + "){ "
        + root
        + "projectV2(number:$number){ "
        + body
        + closing
        + " }"
    )


def github_project_graphql_args(
    plan: dict,
    first: int = GITHUB_PROJECT_ITEM_PAGE,
    after: str = "",
    field_value_page: int = GITHUB_PROJECT_FIELD_VALUE_PAGE,
) -> list[str]:
    """Build the `gh api graphql` argv. The query is INLINED, never `query=@file`: the
    board-structure guard blocks file-loaded board queries because it cannot inspect them."""
    args = [
        "api",
        "graphql",
        "-f",
        f"query={github_project_graphql_query(plan, field_value_page)}",
    ]
    if not github_project_owner_is_viewer(plan.get("owner")):
        args += ["-f", f"owner={plan['owner']}"]
    args += [
        "-F",
        f"number={plan['number']}",
    ]
    if plan.get("kind") == "item-list":
        args.extend(["-F", f"first={int(first)}"])
        if after:
            args.extend(["-f", f"after={after}"])
    return args


def _project_field_key(name: str) -> str:
    """gh lowercases only the FIRST character of the field name: "Item Type" -> "item Type"."""
    return name[:1].lower() + name[1:] if name else ""


def github_project_export_field(node: dict) -> dict:
    if not isinstance(node, dict):
        return {}
    field = {"id": node.get("id"), "name": node.get("name"), "type": node.get("__typename")}
    options = node.get("options")
    if isinstance(options, list) and options:
        # gh omits `options` entirely when a single-select field has none; an empty list here would
        # be a shape the call sites never saw from gh.
        field["options"] = [
            {"id": option.get("id"), "name": option.get("name")}
            for option in options
            if isinstance(option, dict)
        ]
    return field


def _project_field_value(value: dict) -> object:
    kind = value.get("__typename")
    if kind == "ProjectV2ItemFieldTextValue":
        return value.get("text")
    if kind == "ProjectV2ItemFieldSingleSelectValue":
        return value.get("name")
    if kind == "ProjectV2ItemFieldNumberValue":
        return value.get("number")
    if kind == "ProjectV2ItemFieldDateValue":
        return value.get("date")
    if kind == "ProjectV2ItemFieldIterationValue":
        return value.get("title")
    if kind == "ProjectV2ItemFieldLabelValue":
        nodes = (value.get("labels") or {}).get("nodes") or []
        return [n.get("name") for n in nodes if isinstance(n, dict)]
    if kind == "ProjectV2ItemFieldUserValue":
        nodes = (value.get("users") or {}).get("nodes") or []
        return [n.get("login") for n in nodes if isinstance(n, dict)]
    if kind == "ProjectV2ItemFieldRepositoryValue":
        return (value.get("repository") or {}).get("url")
    if kind == "ProjectV2ItemFieldPullRequestValue":
        nodes = (value.get("pullRequests") or {}).get("nodes") or []
        return [n.get("url") for n in nodes if isinstance(n, dict)]
    if kind == "ProjectV2ItemFieldMilestoneValue":
        return (value.get("milestone") or {}).get("title")
    if kind == "ProjectV2ItemFieldReviewerValue":
        # A reviewer is a User or a Team, so the identity is a login OR a team name.
        nodes = (value.get("reviewers") or {}).get("nodes") or []
        names = [n.get("login") or n.get("name") for n in nodes if isinstance(n, dict)]
        return [name for name in names if name]
    if kind == "ProjectV2ItemFieldMultiSelectValue":
        options = value.get("options") or []
        return [o.get("name") for o in options if isinstance(o, dict) and o.get("name")]
    if kind == "ProjectV2ItemIssueFieldValue":
        inner = value.get("issueFieldValue")
        if not isinstance(inner, dict):
            return None
        # Single-select carries the label in `name`; every other member uses `value`.
        return inner.get("name") if inner.get("name") is not None else inner.get("value")
    return None


def github_project_export_item(node: dict) -> dict:
    """Reshape one ProjectV2Item into the flattened object `gh project item-list --format json`
    emits, so every existing board call site parses it unchanged.

    The item's own node type is deliberately NOT emitted as a top-level `type`: a board field named
    "Type" flattens to that same key, and one would silently overwrite the other.
    """
    if not isinstance(node, dict):
        return {}
    item: dict = {"id": node.get("id")}
    raw_content = node.get("content")
    if isinstance(raw_content, dict):
        content: dict = {"type": raw_content.get("__typename")}
        for key in ("number", "title", "url", "state", "body"):
            if raw_content.get(key) is not None:
                content[key] = raw_content[key]
        repository = raw_content.get("repository")
        if isinstance(repository, dict) and repository.get("nameWithOwner"):
            content["repository"] = repository["nameWithOwner"]
        item["content"] = content
    for value in ((node.get("fieldValues") or {}).get("nodes") or []):
        if not isinstance(value, dict):
            continue
        name = ((value.get("field") or {}).get("name") or "").strip()
        if not name:
            continue
        exported = _project_field_value(value)
        if exported is None or exported == []:
            continue
        item[_project_field_key(name)] = exported
    return item


_NESTED_VALUE_CONNECTIONS = ("labels", "users", "pullRequests", "reviewers")


def github_project_field_values_truncated(node: dict) -> bool:
    """A field value dropped by the page size is indistinguishable from a field carrying no value,
    so a clipped read would report "no Status" for an item that has one. Never silent.

    Labels, assignees, linked PRs and reviewers are their OWN connections nested inside a field
    value, so counting field-value nodes cannot see them being clipped (Codex R1(b) P2). Each is
    therefore checked against its own totalCount.
    """
    if not isinstance(node, dict):
        return False
    values = node.get("fieldValues") or {}
    nodes = values.get("nodes")
    if not isinstance(nodes, list):
        return False
    total = values.get("totalCount")
    if isinstance(total, int) and total > len(nodes):
        return True
    for value in nodes:
        if not isinstance(value, dict):
            continue
        for key in _NESTED_VALUE_CONNECTIONS:
            connection = value.get(key)
            if not isinstance(connection, dict):
                continue
            inner_total = connection.get("totalCount")
            inner_nodes = connection.get("nodes")
            if not isinstance(inner_total, int) or not isinstance(inner_nodes, list):
                continue
            if inner_total > len(inner_nodes):
                return True
    return False


def github_field_schema_ttl_seconds() -> int:
    try:
        return max(0, int(resolve_env(
            "MINERVIT_GITHUB_FIELD_SCHEMA_TTL_SECONDS", str(GITHUB_FIELD_SCHEMA_TTL_SECONDS)
        )))
    except ValueError:
        return GITHUB_FIELD_SCHEMA_TTL_SECONDS


def github_args_are_field_schema(args: list[str]) -> bool:
    return len(args) >= 2 and args[0] == "project" and args[1] == "field-list"


def github_args_owner(args: list[str]) -> str:
    for index, token in enumerate(args):
        if token == "--owner" and index + 1 < len(args):
            return args[index + 1]
    return ""


def github_args_are_schema_cacheable(args: list[str]) -> bool:
    """Whether a field-schema read may be SERVED from the persistent cache at all.

    `--owner @me` may not. The cache key is the argv, and that literal names neither an account
    nor a host, so a cached entry cannot say whose schema it holds; after `gh auth switch` it
    would serve the previous account's field ids. Shortening the TTL was not enough, because
    serving the schema from cache irrespective of read mode is itself NEW behavior -- `@me` keeps
    exactly what it had before this release (Codex R1(e) P2).
    """
    if not github_args_are_field_schema(args):
        return False
    if github_project_owner_is_viewer(github_args_owner(args)):
        return False
    # No resolvable identity means the key cannot say WHOSE schema it holds. Falling back to the
    # old unscoped key would be precisely the cross-account hit this scoping exists to prevent,
    # so an unresolvable credential loses the long-lived cache instead (Codex R1(g) P2).
    return bool(github_active_identity())


def github_cache_ttl_for_args(args: list[str]) -> int:
    """The board's field schema gets a long TTL; everything else keeps the default.

    EXCEPT for `--owner @me`: the cache key is the argv, and that literal names neither an account
    nor a host, so a 24h entry would survive `gh auth switch` and serve the next account the
    previous account's field names, options and ids. A key that cannot identify whose schema it
    holds does not earn a long life (Codex R1(d) P2).
    """
    if github_args_are_schema_cacheable(args):
        return github_field_schema_ttl_seconds()
    return github_cache_ttl_seconds()


def github_operation_name(args: list[str]) -> str:
    if len(args) >= 2 and args[0] == "project":
        return f"project.{args[1]}"
    if len(args) >= 2 and args[0] == "api" and args[1] == "graphql":
        return "graphql.read" if github_args_are_graphql_read(args) else "graphql.mutation"
    if len(args) >= 2 and args[0] == "api" and args[1] == "rate_limit":
        return "rate_limit"
    if len(args) >= 2 and args[0] == "api":
        endpoint = args[1].split("?", 1)[0].strip("/")
        return f"rest.{endpoint.replace('/', '.') or 'root'}"
    if len(args) >= 2 and args[0] in {"issue", "pr", "repo", "auth"}:
        return f"{args[0]}.{args[1]}"
    return ".".join(args[:2]) if args else "unknown"


def github_rate_resource_for_args(args: list[str]) -> str:
    if github_args_are_heavy_graphql(args):
        return "graphql"
    if len(args) >= 1 and args[0] == "api":
        return "core"
    if len(args) >= 1 and args[0] == "project":
        return "graphql"
    return "core"


def github_cache_read(args: list[str], max_age: int | None = None) -> tuple[object | None, dict | None]:
    ttl = github_cache_ttl_for_args(args) if max_age is None else max_age
    if ttl <= 0:
        return None, None
    path = github_cache_path(args)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    stored_at = float(raw.get("stored_at") or 0)
    age = max(0.0, time.time() - stored_at)
    if age > ttl:
        return None, raw
    return raw.get("payload"), raw


def github_cache_write(args: list[str], payload: object) -> None:
    # The read resolves its TTL per-args, so the write must too: gating on the GENERIC TTL left a
    # disabled generic cache refusing to populate a schema whose read claims 24h, while any
    # pre-existing file stayed readable (Codex R1(e) P2).
    if github_cache_ttl_for_args(args) <= 0:
        return
    root = github_cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"github_cache_write_unavailable_warn: {root}: {exc}; continuing without cache write", file=sys.stderr)
        return
    record = {"stored_at": time.time(), "args": args, "payload": payload}
    path = github_cache_path(args)
    try:
        write_text_atomic(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"github_cache_write_unavailable_warn: {path}: {exc}; continuing without cache write", file=sys.stderr)


def github_provider_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def github_record_provider_call(
    *,
    operation: str,
    args: list[str],
    target: Path,
    resource: str,
    outcome: str,
    cache: str = "none",
    remaining: int | None = None,
    reset: str = "",
    safe_next_poll: str = "",
    error: str = "",
) -> None:
    root = github_provider_state_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "resource": resource,
            "outcome": outcome,
            "cache": cache,
            "argsHash": github_cache_key(args),
            "pid": os.getpid(),
            "host": github_provider_hostname(),
            "cwd": str(target),
        }
        if remaining is not None:
            record["remaining"] = remaining
        if reset:
            record["reset"] = reset
        if safe_next_poll:
            record["safeNextPoll"] = safe_next_poll
        if error:
            record["error"] = error[:500]
        with github_telemetry_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def github_recent_provider_calls(limit: int = GITHUB_RECENT_CALL_LIMIT) -> list[dict]:
    try:
        lines = github_telemetry_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict] = []
    for line in lines[-max(1, limit * 3):]:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            records.append(raw)
    return records[-limit:]


def github_pending_retry_read(args: list[str]) -> dict | None:
    try:
        raw = json.loads(github_pending_retry_path(args).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        safe_next_poll = float(raw.get("safe_next_poll_epoch") or 0)
    except (TypeError, ValueError):
        return None
    if safe_next_poll <= time.time():
        return None
    return raw


def github_pending_retry_clear(args: list[str]) -> None:
    try:
        github_pending_retry_path(args).unlink()
    except OSError:
        pass


def github_pending_retry_write(operation: str, args: list[str], reason: str, snapshot: dict) -> dict:
    prior_attempts = 0
    try:
        prior = json.loads(github_pending_retry_path(args).read_text(encoding="utf-8"))
        prior_attempts = int(prior.get("attempts") or 0) if isinstance(prior, dict) else 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        prior_attempts = 0
    attempts = prior_attempts + 1
    now = time.time()
    jitter = int(github_cache_key(args)[:4], 16) % 15
    reset = github_rate_resource(snapshot, "graphql").get("reset")
    reset_epoch = 0
    try:
        reset_epoch = int(reset)
    except (TypeError, ValueError):
        reset_epoch = 0
    if reset_epoch > now:
        safe_next_poll_epoch = reset_epoch + jitter
    else:
        backoff = min(github_pending_retry_max_seconds(), github_pending_retry_min_seconds() * (2 ** max(0, attempts - 1)))
        safe_next_poll_epoch = now + backoff + jitter
    record = {
        "operation": operation,
        "argsHash": github_cache_key(args),
        "attempts": attempts,
        "reason": reason,
        "safe_next_poll_epoch": safe_next_poll_epoch,
        "safeNextPoll": datetime.fromtimestamp(int(safe_next_poll_epoch), tz=timezone.utc).isoformat(),
        "reset": github_graphql_reset_text(snapshot),
        "resource": "graphql",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    path = github_pending_retry_path(args)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass
    return record


def github_pending_retry_records() -> list[dict]:
    root = github_provider_state_root() / "pending-retries"
    if not root.is_dir():
        return []
    records: list[dict] = []
    now = time.time()
    for path in root.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            safe_epoch = float(raw.get("safe_next_poll_epoch") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if safe_epoch > now and isinstance(raw, dict):
            records.append(raw)
    records.sort(key=lambda item: float(item.get("safe_next_poll_epoch") or 0))
    return records


def github_cache_invalidate_project(include_schema: bool = True) -> int:
    """Drop cached project reads.

    `include_schema=False` spares the field schema. A successful board write invalidates the ITEM
    data it just changed; that purge was free while the schema carried a 300s TTL nobody read
    from, but it would now discard the 24h schema on every status transition and hand back the
    quota reduction this release exists for. Only a REJECTED write -- the actual staleness signal
    -- purges the schema (Codex R1(d) P2).
    """
    root = github_cache_root()
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        args = raw.get("args")
        if isinstance(args, list) and not include_schema and github_args_are_field_schema(
            [str(item) for item in args]
        ):
            continue
        if isinstance(args, list) and args and (
            args[0] == "project" or github_args_are_graphql_read([str(item) for item in args])
        ):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def github_cache_invalidate_field_schema() -> int:
    """Drop ONLY the cached field schema, leaving cached board item data in place.

    The write path re-reads the schema live before resolving a name to an id, and dropping item
    data as a side effect of that would give back read savings the schema refresh never needed to
    spend. The read that follows repopulates this entry, so the 24h cache ends up refreshed rather
    than emptied (Codex R2 P1).
    """
    root = github_cache_root()
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        args = raw.get("args")
        if not isinstance(args, list) or not github_args_are_field_schema(
            [str(item) for item in args]
        ):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def github_rate_resource(snapshot: dict, name: str) -> dict:
    resources = snapshot.get("resources") if isinstance(snapshot, dict) else None
    resource = (resources or {}).get(name) if isinstance(resources, dict) else None
    return resource if isinstance(resource, dict) else {}


def github_graphql_remaining(snapshot: dict) -> int | None:
    value = github_rate_resource(snapshot, "graphql").get("remaining")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def github_graphql_reset_text(snapshot: dict) -> str:
    reset = github_rate_resource(snapshot, "graphql").get("reset")
    try:
        return datetime.fromtimestamp(int(reset), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return "unknown"


def github_shared_snapshot_read(args: list[str]) -> object | None:
    seconds = github_shared_snapshot_seconds()
    if seconds <= 0:
        return None
    cached, _raw = github_cache_read(args, max_age=seconds)
    return cached


# --- Per-lane GitHub identity: primitives (item 86 WS1) ------------------------------------------
#
# Every read here is LOCAL by default. The only command that can reach the network is the cold
# `gh api user` path, and it is bounded, cached, memoised and standdown-able -- because this
# subsystem is advisory, and an advisory that slows down `lane-start` gets switched off by whoever
# notices, which is the same as never having shipped it.


def github_identity_active_seconds() -> int:
    return _github_identity_env_int("ACTIVE_SECONDS", GITHUB_IDENTITY_ACTIVE_SECONDS)


def github_identity_memo_seconds() -> int:
    return _github_identity_env_int("MEMO_SECONDS", GITHUB_IDENTITY_MEMO_SECONDS)


def github_identity_budget_seconds() -> int:
    return _github_identity_env_int("BUDGET_SECONDS", GITHUB_IDENTITY_BUDGET_SECONDS)


def _github_identity_env_int(suffix: str, default: int) -> int:
    try:
        return max(0, int(resolve_env(f"MINERVIT_GITHUB_IDENTITY_{suffix}", str(default))))
    except ValueError:
        return default


def github_identity_enabled() -> bool:
    """Master knob. `0` stands the whole subsystem down -- both surfaces, no subprocess at all."""
    return resolve_env("MINERVIT_GITHUB_IDENTITY", "1") != "0"


def _git_capture(target: Path, args: list[str], timeout: float = 5) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args], cwd=str(target), capture_output=True, text=True, timeout=max(0.1,
                timeout)
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _gh_json(
    command: list[str], target: Path, timeout: int, max_lock_wait: float | None = None
) -> tuple[int, object | None, str]:
    try:
        lock_started = time.monotonic()
        with github_command_lock(command, max_wait=max_lock_wait):
            # Recomputed AFTER acquisition. The lock can consume its whole allowance and then fail
            # open, and handing the subprocess the original pre-lock timeout let a cold probe take
            # nearly TWICE its budget under ordinary contention -- a deadline spent twice is not a
            # deadline (Codex R1, fresh lineage).
            left = timeout if max_lock_wait is None else timeout - (time.monotonic() - lock_started)
            if left <= 0:
                return 1, None, "identity resolution over time budget"
            proc = subprocess.run(  # noqa: S603
                command, cwd=str(target), capture_output=True, text=True, timeout=max(0.1, left)
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, None, str(exc)
    if proc.returncode != 0:
        return proc.returncode, None, (proc.stderr or proc.stdout).strip()
    try:
        return 0, json.loads(proc.stdout or "null"), ""
    except json.JSONDecodeError as exc:
        return 1, None, f"invalid JSON from {' '.join(command[:3])}: {exc}"


def github_upstream_slug(target: Path, timeout: float = 5) -> str:
    """`host/owner/repo`, lowercased, parsed LOCALLY from the git remote.

    No `gh repo view`, no API call, no network. Empty when there is no parseable remote -- and a
    record with no upstream NEVER participates in a shared-login warning, because "two lanes with
    no remote" is not evidence they are the same repository.
    """
    probe_started = time.monotonic()
    for remote in ("origin", "upstream"):
        # ONE deadline across both probes. Reusing the full timeout for the second let a wedged
        # filesystem burn roughly twice the identity budget before the caller regained control.
        left = timeout - (time.monotonic() - probe_started)
        if left <= 0:
            return ""
        url = _git_capture(
            Path(target), ["config", "--get", f"remote.{remote}.url"], timeout=left
        ).strip()
        if not url:
            continue
        text = url
        if "://" not in text and "@" in text.split("/", 1)[0]:
            text = "ssh://" + text.replace(":", "/", 1)  # scp-style git@host:owner/repo
        try:
            parsed = urllib.parse.urlsplit(text)
            host = (parsed.hostname or "").lower()
        except ValueError:
            # Git accepts arbitrary remote strings, so `remote.origin.url` can hold something
            # `urlsplit` refuses -- `https://[broken/acme/repo.git` raises. Uncaught, that turned
            # an ADVISORY into a lane-start crash, breaking the one property this subsystem states
            # most loudly: it can never fail a lane. Try the next remote instead (Codex R4).
            continue
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if host and path.count("/") == 1:
            return f"{host}/{path.lower()}"
    return ""


def github_gh_host(target: Path | None = None, timeout: float = 5) -> str:
    """The host `gh` would use here: the REPOSITORY's host first, `GH_HOST` only as a fallback.

    Preferring `GH_HOST` was wrong. A lane with a parseable GHES remote and a stale
    `GH_HOST=github.com` still exported would have every repository-aware `gh` command infer GHES
    while this function selected the public host and then explicitly queried it -- so the lane
    could cache and report the WRONG account, and raise or suppress shared-login warnings against
    it (Codex R3). `GH_HOST` is what you set when there is no repository to infer from, so that is
    when it is used.
    """
    slug = github_upstream_slug(target, timeout=timeout) if target is not None else ""
    if slug:
        return slug.split("/", 1)[0]
    host = (resolve_env("GH_HOST") or "").strip()
    return host.lower() if host else "github.com"


_GITHUB_LANE_KEY_CACHE: dict[str, str] = {}


def github_identity_lane_key(target: Path) -> str:
    """One key per WORKTREE ROOT -- not per clone, and not per directory.

    The first version used `--git-common-dir`, which collapses every linked worktree of a clone onto
    one lane. That was an over-correction and it broke the feature's primary purpose: this
    framework's standard topology is ONE ISOLATED WORKTREE PER LANE, so in the normal multi-lane
    setup every lane wrote the same record, `len(lanes)` stayed 1, and the shared-login warning
    could never fire at all (Codex R2). Avoiding a false positive by going blind in the common case
    is not a trade, it is a control that reads healthy while measuring nothing.
    `--show-toplevel` keeps the property that actually mattered -- an invocation from a
    subdirectory resolves to the same lane as its root -- while keeping sibling worktrees distinct,
    which they genuinely are: separate checkouts, separate work, separate `gh` invocations.
    """
    try:
        cache_key = str(Path(target).resolve())
    except OSError:
        cache_key = str(target)
    cached = _GITHUB_LANE_KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    common = _git_capture(Path(target), ["rev-parse", "--show-toplevel"])
    if common:
        try:
            resolved = str(Path(common).resolve())
        except OSError:
            resolved = common
    else:
        resolved = cache_key
    _GITHUB_LANE_KEY_CACHE[cache_key] = resolved
    return resolved


def github_token_source(host: str = "github.com", environ: Mapping[str, str] | None = None) -> str:
    for name in _github_token_env_names(host):
        if (resolve_env(name, environ=environ) or "").strip():
            return f"env:{name}"
    return "keyring"


def _github_token_env_names(host: str) -> list[str]:
    """The env vars `gh` consults for this host, in `gh`'s own precedence order.

    ONE definition, shared by the source reporter and the memo's fingerprint check -- duplicating
    the precedence let the two disagree, which made every memo look stale on an Enterprise Cloud
    host and silently destroyed the zero-subprocess path (Codex R2).

    `gh` reads GH_ENTERPRISE_TOKEN first only for GHES. **Enterprise Cloud (`<tenant>.ghe.com`) uses
    GH_TOKEN like github.com does**, so treating any non-github.com host as GHES reported the wrong
    variable there.
    """
    normalized = (host or "").lower()
    cloud = (
        not normalized
        or normalized in ("github.com", "api.github.com")
        or normalized == "ghe.com"
        or normalized.endswith(".ghe.com")
    )
    if cloud:
        return ["GH_TOKEN", "GITHUB_TOKEN"]
    # GHES consults ONLY these. Adding the public variables as a fallback meant a lane with a
    # stored GHES credential and an exported public GH_TOKEN reported `source=env:GH_TOKEN` and
    # compared THAT token's fingerprint against the enterprise credential -- so every memo looked
    # stale and the API was re-invoked on every call (Codex R3).
    return ["GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"]


def github_token_fingerprint(target: Path, host: str = "", timeout: float = 5) -> str:
    """sha256(token)[:8] for the token `gh` would use ON THIS HOST.

    The token value is never returned, logged, cached, or written.

    The HOST matters and omitting it was a real defect: without `--hostname`, `gh auth token`
    resolves github.com even when the API call below explicitly selects a GHES host. On a lane with
    only `GH_ENTERPRISE_TOKEN` set, fingerprinting simply failed; with BOTH tokens set, the cache
    key hashed the PUBLIC token while the login came from the ENTERPRISE one -- so the cache could
    return another host's identity and the predicate could raise a false shared-login warning, which
    is the one thing it must never do (Codex R1).
    """
    command = ["gh", "auth", "token"]
    if host:
        command += ["--hostname", host]
    try:
        if timeout <= 0:
            return ""
        with github_command_lock(command, max_wait=timeout):
            proc = subprocess.run(  # noqa: S603
                command, cwd=str(target), capture_output=True, text=True, timeout=max(0.1, timeout)
            )
    except (OSError, subprocess.SubprocessError):
        return ""
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _github_token_is_installation(code: int, error: str) -> bool:
    """A 403 from `/user` with a token that authenticated is an App installation, not a failure.

    Distinguished from a genuine auth failure (401) and from a network error, because reporting an
    unreachable API as an App identity would invent a lane that does not exist.
    """
    if code == 0:
        return False
    # An APP-SPECIFIC signal only. A bare 403 is also what an exhausted core budget or an org policy
    # block returns for an ordinary user token, and classifying those as an App would record a
    # FABRICATED identity and mask a shared login between lanes using different PATs (Codex R2).
    return "resource not accessible by integration" in (error or "").lower()


def github_identity_records_root() -> Path:
    return github_provider_state_root() / "identities"


def _github_identity_key(lane_key: str) -> str:
    return hashlib.sha256(lane_key.encode("utf-8")).hexdigest()[:12]


def _github_memo_paths(target: Path, *, lane_key: str | None = None):
    """Memo paths for this target, CHEAPEST FIRST.

    The target-path key is tried before the lane key because computing the lane key costs a
    `git rev-parse` -- a subprocess, in a process that has just started and has no in-process cache
    to hit. That one call was the whole reason a warm read measured 212ms against a 150ms budget:
    the memo removed the `gh` calls and then paid git for the privilege of looking the answer up.
    """
    root = github_identity_records_root() / "memo"
    try:
        by_target = str(Path(target).resolve())
    except OSError:
        by_target = str(target)
    # LAZY. Returning both paths eagerly called `github_identity_lane_key` -- a `git rev-parse` --
    # before the reader could even open the cheap one, so a fresh CLI process paid a subprocess on
    # every warm read. The zero-subprocess test passed only because its write had already populated
    # the in-process lane-key cache: the test proved the level it tested, not what ships (Codex R4).
    yield root / f"t-{_github_identity_key(by_target)}.json"
    # A caller that already knows the lane key passes it; only a caller that does not pays for the
    # `git rev-parse`. `None` means "resolve it", "" means "there is none".
    resolved = github_identity_lane_key(target) if lane_key is None else lane_key
    if resolved:
        yield root / f"{_github_identity_key(resolved)}.json"


# Every key a usable snapshot must carry. A memo missing one is a partial write or an older shape,
# and returning it would surface a half-formed identity as a confident answer.
_GITHUB_SNAPSHOT_REQUIRED_KEYS = ("login", "fingerprint", "ghHost", "source")


def _github_env_token_fingerprint(host: str) -> str:
    """Fingerprint the token from the ENVIRONMENT, in-process, with no subprocess.

    This is what makes credential-change detection affordable. The documented remedy for a
    shared-login warning is `export GH_TOKEN=<per-lane token>`, and a memo that ignores it kept
    reporting the OLD shared login for up to 900 seconds -- preserving the exact warning the
    operator had just acted on, which would teach them the remedy does not work (Codex R1).

    Only the env layer is checked: hashing it costs nothing, and it is the layer the remedy
    touches. A keyring credential rotating under a lane still waits for the memo TTL, which is
    stated rather than hidden.
    """
    for name in _github_token_env_names(host):
        value = (resolve_env(name) or "").strip()
        if value:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return ""


def _github_current_token_source(host: str) -> str:
    """The source `gh` would report right now, computed in-process with no subprocess."""
    for name in _github_token_env_names(host):
        if (resolve_env(name) or "").strip():
            return f"env:{name}"
    return "keyring"


def _github_memo_is_stale(memo: dict, current_host: str = "") -> bool:
    """True when the memo cannot be trusted: incomplete, superseded, or about a different host.

    The HOST check matters because the memo is returned before the current repository host is
    resolved: a remote moved from github.com to GHES would keep printing and recording the OLD
    login and host beside a freshly-computed upstream for a full fifteen minutes, producing false
    or missed warnings the whole time (Codex R5).
    """
    if any(not memo.get(key) for key in _GITHUB_SNAPSHOT_REQUIRED_KEYS):
        return True
    env_fingerprint = _github_env_token_fingerprint(str(memo.get("ghHost") or ""))
    if current_host and str(memo.get("ghHost") or "").lower() != current_host.lower():
        return True
    if _github_current_token_source(str(memo.get("ghHost") or "")) != memo.get("source"):
        # The same token value moving between layers (keyring -> GH_TOKEN, or GH_TOKEN ->
        # GITHUB_TOKEN) leaves the fingerprint identical while `gh` now reads a different variable,
        # so the identity line would report a source that is no longer in use.
        return True
    if str(memo.get("source") or "").startswith("env:") and not env_fingerprint:
        # The memo was written from an environment variable that is now GONE -- the lane reverted
        # to its keyring credential. Without this it kept reporting the old bot identity for up to
        # 15 minutes, hiding the fact that it had fallen back to a possibly SHARED login, which is
        # the state this feature exists to surface (Codex R2).
        return True
    return bool(env_fingerprint) and env_fingerprint != memo.get("fingerprint")


def github_identity_memo_read(target: Path) -> dict:
    raw = None
    for path in _github_memo_paths(target):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    if not isinstance(raw, dict):
        return {}
    try:
        age = time.time() - float(raw.get("at") or 0)
    except (TypeError, ValueError):
        return {}
    if age > github_identity_memo_seconds():
        return {}
    snapshot = {k: v for k, v in raw.items() if k != "at"}
    snapshot["memo"] = True
    return snapshot


def github_identity_memo_write(target: Path, snapshot: dict) -> None:
    """Persist a snapshot, including the lane key and upstream so a warm read needs no git."""
    # BOTH keys. The lane key is what makes every worktree of a clone share one memo; the target
    # key is what lets the next process find it without shelling out to git first.
    payload = {k: v for k, v in snapshot.items() if k != "memo"}
    payload["at"] = time.time()
    # `setdefault` EVALUATES ITS DEFAULT even when the key is present, so the previous version ran
    # `git rev-parse` and `git config` on every write regardless of what the caller supplied -- the
    # coordinates were threaded through and then recomputed anyway (Codex R2, v2). Explicit guards.
    if not payload.get("laneKey"):
        payload["laneKey"] = github_identity_lane_key(target)
    if not payload.get("upstream"):
        payload["upstream"] = github_upstream_slug(target)
    body = json.dumps(payload, sort_keys=True) + "\n"
    # The lane-key PATH is derived from the payload we just resolved, not recomputed. Iterating
    # `_github_memo_paths` here called `github_identity_lane_key` again -- so the write still
    # shelled
    # out to git even with the coordinates in hand, which is the same defect as the eager
    # `setdefault` one layer up. Caught by the test written for that one.
    for path in _github_memo_paths(target, lane_key=str(payload.get("laneKey") or "")):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(path, body)
        except OSError:
            continue


def github_identity_snapshot(
    target: Path, max_age: int | None = None, *, use_memo: bool = True, allow_cold: bool = True
) -> dict:
    """Resolve this lane's GitHub identity.

    `allow_cold=False` returns the memo or nothing. `github-budget-status` PASSES IT, keyed on
    `--identity`: a bare invocation passes `allow_cold=False` so a status read never pays a cold
    `gh api user` subprocess, and `--identity` passes `allow_cold=True` because an operator who
    asked for identity on purpose is the one case where waiting is the expected cost. It was
    written for the `lane-start` surface an earlier release removed; reconnecting
    `github-budget-status` (Tier 1 salvage) gave the parameter its caller back rather than leaving
    it a promise only a test exercised.

    FOUR CONSECUTIVE REVIEW ROUNDS found a different way for the cold path to overrun its
    advertised eight-second ceiling: the lock wait ran ahead of the subprocess timeout, then the
    subprocess got its pre-lock allowance, then the two remote probes each took the full budget,
    then a sub-second remainder was rounded up to a whole second. Every fix was correct and the
    next round found another leak, which is the documented signal that the DESIGN is wrong rather
    than the arithmetic.

    So the promise is withdrawn instead of patched a fifth time. A cold resolution costs several
    subprocesses and can contend on a machine-wide lock; bounding that precisely is a real problem
    and `lane-start` does not need to solve it, because `lane-start` does not need to do it at all.
    It reports what is already known and names the diagnostic verb otherwise. Cold resolution
    happens in `github-budget-status --identity`, where an operator has asked the question on
    purpose and waiting is the expected cost.
    """
    started = time.monotonic()
    if use_memo and max_age != 0:
        # The memo is consulted BEFORE the host is resolved. `github_gh_host` shells out to read
        # the git remote, so resolving it first made the memoised path pay a subprocess anyway --
        # the cost this memo exists to remove. The memo already carries the host it was written
        # with, which is the same host any answer derived from it would have.
        memo = github_identity_memo_read(target)
        # The CURRENT repository coordinates are supplied, not left to a default nobody passes.
        # `_github_memo_is_stale` grew a `current_host` parameter and no caller provided it, and
        # the upstream was never compared at all -- so a retargeted `origin` or a reused checkout
        # path inside the TTL could refresh a record for the OLD repository and produce a false or
        # missed warning (Codex R3, v2). Resolving the upstream here costs one `git config`, which
        # is what correctness costs on this path; the diagnostic verb is where waiting is expected.
        if memo:
            current_upstream = github_upstream_slug(target)
            # With no parseable remote the host comes from GH_HOST, and skipping the comparison
            # there meant a GH_HOST change inside the TTL returned the OLD host and login -- in the
            # no-remote workflow the fallback explicitly supports (Codex R4).
            current = (
                current_upstream.split("/", 1)[0]
                if current_upstream
                else github_gh_host(target)
            )
            stale_repo = bool(current_upstream) and memo.get("upstream") not in (
                None,
                current_upstream,
            )
            if not stale_repo and not _github_memo_is_stale(memo, current_host=current):
                return memo
    def _left() -> float:
        """Whatever is left of the advertised ceiling. ONE deadline, threaded through every probe.

        Each probe previously carried its own fixed five-second timeout and the budget was only
        consulted between them, so with no valid origin two `git config` calls plus `gh auth token`
        could burn fifteen seconds against an eight-second ceiling (Codex R5). A ceiling made of
        independently-bounded parts is not a ceiling.
        """
        return github_identity_budget_seconds() - (time.monotonic() - started)

    if not allow_cold:
        # Memo or nothing. No lock, no subprocess, no ceiling to enforce.
        return {
            "error": "identity not resolved yet; run `github-budget-status --identity --target .` "
            "to resolve it (a subprocess, bounded and cached) and print it"
        }
    if github_identity_budget_seconds() <= 0:
        # Checked BEFORE the local lookups, not only before the API call. The host lookup and
        # `gh auth token` each carry fixed five-second timeouts, so a budget below five seconds --
        # including zero, which an operator would reasonably read as "do not spend time on this" --
        # was not enforced at all until after both had run (Codex R4).
        return {"error": "identity resolution over time budget"}
    host = github_gh_host(target, timeout=_left())
    if _left() <= 0:
        return {"error": "identity resolution over time budget"}
    if shutil.which("gh") is None:
        return {"error": "gh CLI missing"}
    fingerprint = github_token_fingerprint(target, host, timeout=_left())
    if not fingerprint:
        return {"error": "no authenticated GitHub token (gh auth token failed)"}
    source = github_token_source(host)
    # Fingerprint and host participate in the CACHE KEY ONLY; the executed command is
    # `gh api user --hostname <host>`. The cache dir is machine-shared across lanes, so keying by
    # token keeps two lanes with different GH_TOKENs from reading each other's identity, and keying
    # by host keeps an enterprise lane off github.com's entry.
    cache_args = ["api", "user", f"identity:{host}:{fingerprint}"]
    ttl = github_cache_ttl_seconds() if max_age is None else max_age
    cached, _raw = github_cache_read(cache_args, max_age=ttl)
    if isinstance(cached, dict) and cached.get("login"):
        snapshot = {
            "login": cached["login"], "id": cached.get("id"), "source": source,
            "fingerprint": fingerprint, "ghHost": host,
        }
        github_record_provider_call(
            operation="identity", args=cache_args, target=Path(target),
            resource="core", outcome="cache-hit", cache="hit",
        )
        github_identity_memo_write(target, snapshot)
        return snapshot
    if time.monotonic() - started > github_identity_budget_seconds():
        return {"error": "identity resolution over time budget"}
    # The remaining budget is what the call gets, not a fixed 10s on top of whatever the lock
    # already cost. The checks either side of this line only changed the eventual VERDICT; they let
    # `lane-start` block for the lock's 30s plus another 10s and then report that the budget was
    # exceeded -- a ceiling that is advertised and not enforced is the same shape as every other
    # defect in this program (Codex R2).
    remaining = _left()
    if remaining <= 0:
        return {"error": "identity resolution over time budget"}
    code, payload, error = _gh_json(
        ["gh", "api", "user", "--hostname", host],
        target,
        timeout=max(1, int(remaining)),
        max_lock_wait=remaining,
    )
    if code != 0 or not isinstance(payload, dict) or not payload.get("login"):
        # A GitHub App INSTALLATION token cannot call `/user` -- it is not a user -- and returns
        # 403. That is the second remedy this feature's own runbook advertises, so reporting
        # `unavailable` for it would mean the fix we recommend makes the tool go blind (Codex R1).
        #
        # The installation still has a stable identity for this feature's purpose: the token
        # fingerprint. Two lanes holding the SAME installation token share an identity (correct --
        # they are indistinguishable to GitHub, which is the whole problem), and two holding
        # different ones do not. So a synthetic login keyed on the fingerprint keeps the predicate
        # sound rather than silently excluding App-authenticated lanes from it.
        if _github_token_is_installation(code, error):
            # `login` is NOT keyed on the fingerprint. Two lanes minting separate tokens from the
            # SAME App installation have different fingerprints while GitHub attributes both to one
            # installation and they share its rate-limit bucket -- so keying on the token would
            # make them look like separate identities and SUPPRESS the warning they should raise
            # (Codex R2). This control's failure mode is silence, so it errs toward grouping.
            #
            # Residual, stated rather than implied: this also groups two DIFFERENT installations on
            # one upstream into one identity, which would be a false positive. An installation
            # token cannot query its own installation id (that needs an App JWT), so a stable
            # per-installation identity is not resolvable from inside a lane. Filed rather than
            # guessed at.
            snapshot = {
                "login": "app-installation", "id": None, "source": source,
                "fingerprint": fingerprint, "ghHost": host, "identityKind": "app-installation",
            }
            github_identity_memo_write(target, snapshot)
            return snapshot
        return {"error": error or "gh api user failed"}
    if time.monotonic() - started > github_identity_budget_seconds():
        # Checked AFTER the call as well as before it. A budget enforced only at the start bounds
        # nothing: the API call is the slow part, and a lane that blew the budget inside it would
        # still pay the whole cost and then report success.
        return {"error": "identity resolution over time budget"}
    github_cache_write(cache_args, {"login": payload["login"], "id": payload.get("id")})
    github_record_provider_call(
        operation="identity", args=cache_args, target=Path(target),
        resource="core", outcome="live", cache="miss",
    )
    snapshot = {
        "login": payload["login"], "id": payload.get("id"), "source": source,
        "fingerprint": fingerprint, "ghHost": host,
    }
    github_identity_memo_write(target, snapshot)
    return snapshot


def github_identity_record_write(
    target: Path,
    *,
    login: str,
    fingerprint: str,
    source: str,
    host: str,
    create: bool = True,
    lane_key: str = "",
    upstream: str | None = None,
) -> None:
    """Write this lane's identity record.

    `lane_key` and `upstream` are accepted from the caller because a warm memo already knows both.
    Recomputing them here ran `git rev-parse` AND `git config` on every `lane-start`, so the
    advertised zero-subprocess steady state still paid two subprocesses -- the memo removed the
    `gh` calls and then git was re-invoked to file the result (Codex R5).
    """
    root = github_identity_records_root()
    lane_key = lane_key or github_identity_lane_key(target)
    path = root / f"{_github_identity_key(lane_key)}.json"
    if not create and not path.exists():
        return  # touch-only callers refresh a lane; they never MINT one
    try:
        root.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": GITHUB_IDENTITY_RECORD_SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(),
            "laneKey": lane_key,
            "target": str(Path(target).resolve()),
            "upstream": github_upstream_slug(target) if upstream is None else upstream,
            "ghHost": host,
            "login": login,
            "tokenFingerprint": fingerprint,
            "source": source,
            # The MACHINE hostname, not the GitHub host. Two lanes on different machines sharing a
            # login are not the failure this warns about; they cannot collide on a local lock.
            "machine": github_provider_hostname(),
            "pid": os.getpid(),
        }
        write_text_atomic(path, json.dumps(record, sort_keys=True) + "\n")
        github_identity_records_prune(root)
    except OSError:
        return  # advisory subsystem: identity bookkeeping never breaks a lane


def github_identity_records_prune(root: Path) -> None:
    """Unlink on write, so a machine that has run lanes in many checkouts does not accumulate
    records forever and make every lane start read the whole set. The one-hour floor keeps an
    ACTIVE_SECONDS=0 test override from deleting the fixtures it just wrote."""
    cutoff = time.time() - max(2 * github_identity_active_seconds(), 3600)
    for path in root.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def github_identity_records() -> list[dict]:
    root = github_identity_records_root()
    records: list[dict] = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            records.append(raw)
    return records


def github_shared_identity_warnings(now: float | None = None) -> list[str]:
    """Fires ONLY for two or more distinct clones of the SAME upstream on the SAME GitHub host
    under one login, all recently active, on THIS machine.

    Everything else is silent by construction: a second repository, an invocation from a
    subdirectory, a worktree of the same lane, a checkout with no GitHub remote, a stale record, a
    deleted clone. Each of those would be a false positive, and a shared-login advisory that cries
    wolf is worth less than none -- it trains the reader to skip the line.
    """
    now = time.time() if now is None else now
    window = github_identity_active_seconds()
    this_machine = github_provider_hostname()
    groups: dict[tuple[str, str, str], dict[str, str]] = {}
    for record in github_identity_records():
        upstream = str(record.get("upstream") or "").strip()
        login = str(record.get("login") or "").strip()
        lane_key = str(record.get("laneKey") or "").strip()
        if not (upstream and login and lane_key):
            continue
        try:
            at = datetime.fromisoformat(str(record["at"])).timestamp()
        except (KeyError, ValueError):
            continue
        if now - at > window:
            continue
        if not Path(lane_key).exists():
            continue  # the clone is gone; a deleted worktree is not an active lane
        if str(record.get("machine") or "") != this_machine:
            # The record carries a `machine` and nothing filtered on it. With a shared telemetry
            # root or checkouts on shared storage, records from every host grouped together -- so
            # two lanes on DIFFERENT machines could raise an advisory claiming they are active "on
            # this machine", which is both a false positive and the exact opposite of the
            # documented cross-machine exclusion (Codex R1, fresh lineage).
            continue
        host = str(record.get("ghHost") or "github.com").strip().lower()
        groups.setdefault((host, upstream, login), {})[lane_key] = str(
            record.get("target") or lane_key
        )
    warnings: list[str] = []
    for (host, upstream, login), lanes in sorted(groups.items()):
        if len(lanes) > 1:
            listed = ", ".join(sorted(lanes.values()))
            warnings.append(
                f"github_identity_shared_warn: login={login} on {host} is held by {len(lanes)} "
                f"lanes active on {upstream} on this machine ({listed}); concurrent lanes on one "
                "upstream need separate GitHub identities (per-lane GH_TOKEN bot PAT or GitHub "
                "App installation token) - see "
                "docs/reference/operations/per-lane-github-identity.md"
            )
    return warnings
