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
from typing import Callable

from .util import resolve_env, write_text_atomic


GITHUB_CACHE_TTL_SECONDS = 300
GITHUB_SHARED_SNAPSHOT_SECONDS = 15
GITHUB_RATE_LIMIT_LOW_WATERMARK = 100
GITHUB_LOCK_TIMEOUT_SECONDS = 30
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


def github_acquire_lock(lock: Path, command: list[str], label: str) -> str:
    timeout_seconds = github_lock_timeout_seconds()
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
def github_command_lock(command: list[str]):
    """Machine-local serialization for GitHub CLI calls so concurrent lanes do not stampede limits."""
    if not command or command[0] != "gh" or resolve_env("MINERVIT_GITHUB_SERIALIZE", "1") == "0":
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
        token = github_acquire_lock(lock, command, "github_request_lock")
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


def github_cache_path(args: list[str]) -> Path:
    return github_cache_root() / f"{github_cache_key(args)}.json"


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
    ttl = github_cache_ttl_seconds() if max_age is None else max_age
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
    if github_cache_ttl_seconds() <= 0:
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


def github_cache_invalidate_project() -> int:
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
        if isinstance(args, list) and args and (
            args[0] == "project" or github_args_are_graphql_read([str(item) for item in args])
        ):
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
