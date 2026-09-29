"""Optional Git-branch transport for advisory work records.

The active checkout and index are never touched. Every writer overlays only its random clone
namespace onto a freshly fetched tree and uses an ordinary fast-forward push. Startup may read
an explicitly labelled cache; network failure never invalidates a successful local declaration.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath

SCHEMA = "tautline-work/v1"
MARKER = ".tautline-work.json"
BRANCH_SCHEMA = "tautline-work-branch/v1"
MAX_RECORDS = 256
MAX_RECORD_BYTES = 16_384
MAX_CACHE_BYTES = MAX_RECORDS * MAX_RECORD_BYTES + 65_536
_FIELDS = {"schema", "lane", "goal", "branch", "paths", "interfaces", "dependsOn", "item", "pr", "blocker", "status", "updatedAt", "expiresHours"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_NAMESPACE = re.compile(r"^[a-f0-9]{32}$")


class SyncError(ValueError):
    pass


class MetadataError(SyncError):
    pass


def _run(root: Path, args: list[str], deadline: float, *, data: bytes | None = None, env: dict | None = None, check: bool = True):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SyncError("synchronization time budget expired")
    process_env = dict(os.environ)
    process_env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "SSH_ASKPASS_REQUIRE": "never"})
    process_env["GIT_SSH_COMMAND"] = process_env.get("GIT_SSH_COMMAND", "ssh") + " -oBatchMode=yes"
    if env:
        process_env.update(env)
    try:
        child = subprocess.Popen(
            ["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", *args],
            stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env, start_new_session=True,
        )
        try:
            stdout, stderr = child.communicate(data, timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            # Killing the whole group also closes pipes held by an SSH/credential helper child.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                for stream in (child.stdout, child.stderr):
                    if stream:
                        stream.close()
            raise SyncError("synchronization time budget expired") from exc
    except OSError as exc:
        raise SyncError("Git synchronization could not start") from exc
    result = subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
    if check and result.returncode:
        # Git stderr can contain private remote URLs, credentials, or local filesystem paths.
        raise SyncError("Git synchronization failed; cached declarations remain available")
    return result


def _json_read(path: Path, limit: int = MAX_CACHE_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SyncError("coordination cache is not a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SyncError("coordination cache exceeds size limit")
    return json.loads(raw)


def _atomic(path: Path, value) -> None:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _locations(target: Path, config: dict) -> tuple[Path, str]:
    common = _run(target, ["rev-parse", "--path-format=absolute", "--git-common-dir"], time.monotonic() + 1).stdout.decode().strip()
    base = Path(common) / "tautline" / "work-git"
    if base.is_symlink() or base.parent.is_symlink():
        raise SyncError("coordination cache directory must not be a symlink")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = base / "identity.json"
    if not identity.exists():
        fd, temporary = tempfile.mkstemp(prefix=".identity-", dir=base)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"namespace": uuid.uuid4().hex}, stream)
            try:
                os.link(temporary, identity)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    stored_identity = _json_read(identity, 1024)
    if not isinstance(stored_identity, dict):
        raise SyncError("invalid local coordination identity")
    namespace = stored_identity.get("namespace", "")
    if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
        raise SyncError("invalid local coordination identity")
    key = hashlib.sha256((config["remote"] + "\0" + config["branch"]).encode()).hexdigest()[:24]
    cache = base / key
    if cache.is_symlink():
        raise SyncError("coordination cache directory must not be a symlink")
    cache.mkdir(exist_ok=True, mode=0o700)
    return cache, namespace


def validate_record(record: object, namespace: str | None = None, lane: str | None = None) -> dict:
    """Validate untrusted branch/cache data without consulting the remote owner's filesystem."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise MetadataError("invalid remote record schema")
    if set(record) != _FIELDS | {"namespace"}:
        raise MetadataError("invalid remote record fields")
    source = record.get("namespace")
    name = record.get("lane")
    if not isinstance(source, str) or not _NAMESPACE.fullmatch(source) or (namespace and namespace != source):
        raise MetadataError("invalid remote record namespace")
    if not isinstance(name, str) or not _ID.fullmatch(name) or (lane and lane != name):
        raise MetadataError("invalid remote record lane")
    for key in ("goal", "branch", "item", "pr", "blocker"):
        value = record.get(key)
        if not isinstance(value, str) or len(value) > 8000 or (key in {"goal", "branch"} and not value.strip()):
            raise MetadataError("invalid remote record text")
    for key in ("paths", "interfaces", "dependsOn"):
        values = record.get(key)
        if not isinstance(values, list) or len(values) > 64 or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in values):
            raise MetadataError("invalid remote record scope")
    for value in record["paths"]:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or any(c in value for c in "*?[]") or str(path) != value:
            raise MetadataError("invalid remote record path")
    if record.get("status") not in {"active", "blocked", "completed", "abandoned"}:
        raise MetadataError("invalid remote record status")
    for key in ("updatedAt", "expiresHours"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1e15 or not math.isfinite(value):
            raise MetadataError("invalid remote record timestamp")
    if not 1 <= record["expiresHours"] <= 168:
        raise MetadataError("invalid remote record expiry")
    if len(json.dumps(record).encode()) > MAX_RECORD_BYTES:
        raise MetadataError("invalid remote record size")
    return record


def _public(records: list[dict], namespace: str) -> list[dict]:
    if len(records) > MAX_RECORDS:
        raise MetadataError("local declaration limit exceeded")
    result = []
    for record in records:
        public = {key: record[key] for key in _FIELDS if key in record}
        public["namespace"] = namespace
        result.append(validate_record(public))
    return sorted(result, key=lambda record: record["lane"])


def _fetch(target: Path, config: dict, cache: Path, deadline: float) -> str | None:
    ref = "refs/heads/" + config["branch"]
    local_ref = "refs/tautline/work/" + cache.name
    result = _run(target, ["fetch", "--quiet", "--recurse-submodules=no", "--no-tags", "--no-write-fetch-head", config["remote"], "+" + ref + ":" + local_ref], deadline, check=False)
    if result.returncode:
        exists = _run(target, ["ls-remote", "--exit-code", "--refs", config["remote"], ref], deadline, check=False)
        if exists.returncode == 2 and not exists.stdout.strip():
            return None
        raise SyncError("remote unavailable; showing cached declarations")
    return _run(target, ["rev-parse", local_ref], deadline).stdout.decode().strip()


def _read_tree(target: Path, tip: str | None, deadline: float) -> tuple[list[dict], str]:
    if tip is None:
        return [], ""
    listing = _run(target, ["ls-tree", "-r", "-z", "-l", tip], deadline).stdout
    entries = []
    problems = []
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        meta, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id, size = meta.split()
        path = raw_path.decode("utf-8", errors="replace")
        if path != MARKER and not path.startswith("records/"):
            raise MetadataError("configured branch is not a Tautline metadata branch")
        if len(entries) >= MAX_RECORDS + 1:
            problems.append("remote record limit exceeded")
            break
        if mode != b"100644" or kind != b"blob" or not size.isdigit() or int(size) > MAX_RECORD_BYTES:
            problems.append("invalid remote record type or size")
            continue
        entries.append((path, object_id.decode(), int(size)))
    if not any(path == MARKER for path, _, _ in entries):
        raise MetadataError("configured branch is not a Tautline metadata branch")
    objects = _run(target, ["cat-file", "--batch"], deadline, data="".join(sha + "\n" for _, sha, _ in entries).encode()).stdout
    offset = 0
    records = []
    for path, sha, size in entries:
        end = objects.find(b"\n", offset)
        header = objects[offset:end].split()
        if header != [sha.encode(), b"blob", str(size).encode()]:
            raise MetadataError("invalid metadata branch object")
        raw = objects[end + 1:end + 1 + size]
        offset = end + 2 + size
        try:
            value = json.loads(raw)
            if path == MARKER:
                if value != {"schema": BRANCH_SCHEMA}:
                    raise MetadataError("configured branch is not a Tautline metadata branch")
            else:
                parts = path.split("/")
                if len(parts) != 3 or not parts[2].endswith(".json"):
                    raise ValueError("invalid record path")
                records.append(validate_record(value, parts[1], parts[2][:-5]))
        except (ValueError, TypeError) as exc:
            if path == MARKER:
                raise MetadataError("configured branch is not a Tautline metadata branch") from exc
            problems.append("invalid remote declaration ignored")
    return records, "; ".join(dict.fromkeys(problems))


def _publish(target: Path, config: dict, cache: Path, namespace: str, records: list[dict], tip: str | None, deadline: float) -> bool:
    fd, index_name = tempfile.mkstemp(prefix=".index-", dir=cache)
    os.close(fd)
    Path(index_name).unlink()
    env = {"GIT_INDEX_FILE": index_name, "GIT_AUTHOR_NAME": "Tautline", "GIT_AUTHOR_EMAIL": "tautline@localhost", "GIT_COMMITTER_NAME": "Tautline", "GIT_COMMITTER_EMAIL": "tautline@localhost"}
    try:
        _run(target, ["read-tree", tip] if tip else ["read-tree", "--empty"], deadline, env=env)
        updates = []
        values = [(MARKER, {"schema": BRANCH_SCHEMA})] + [(f"records/{namespace}/{r['lane']}.json", r) for r in records]
        for path, value in values:
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            sha = _run(target, ["hash-object", "-w", "--stdin"], deadline, data=raw).stdout.decode().strip()
            updates.append(f"100644 {sha}\t{path}\n")
        _run(target, ["update-index", "--index-info"], deadline, data="".join(updates).encode(), env=env)
        tree = _run(target, ["write-tree"], deadline, env=env).stdout.decode().strip()
        if tip and tree == _run(target, ["rev-parse", tip + "^{tree}"], deadline).stdout.decode().strip():
            return True
        args = ["commit-tree", tree, "-m", "Update advisory work declarations [skip ci]"]
        if tip:
            args.extend(["-p", tip])
        commit = _run(target, args, deadline, env=env).stdout.decode().strip()
        result = _run(target, ["push", "--quiet", "--recurse-submodules=no", config["remote"], commit + ":refs/heads/" + config["branch"]], deadline, check=False)
        return result.returncode == 0
    finally:
        Path(index_name).unlink(missing_ok=True)
        Path(index_name + ".lock").unlink(missing_ok=True)



def _cached(path: Path) -> dict:
    try:
        stored = _json_read(path)
        if not isinstance(stored, dict):
            return {}
    except (OSError, ValueError, TypeError):
        return {}
    records = stored.get("records", [])
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        return {}
    try:
        stored["records"] = [validate_record(record) for record in records]
    except (ValueError, TypeError):
        return {}
    now = time.time()
    timestamps = [stored.get(key) for key in ("lastSuccess", "lastAttempt")]
    valid = all(value is None or (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and 0 < value <= now and math.isfinite(value)
    ) for value in timestamps)
    valid = valid and isinstance(stored.get("state"), str) and stored["state"] in {"fresh", "cached", "offline", "pending", "unknown"}
    valid = valid and isinstance(stored.get("pending"), bool)
    valid = valid and isinstance(stored.get("error"), str) and len(stored["error"]) <= 1000
    if not valid:
        stored.update(lastSuccess=None, lastAttempt=None, state="unknown", pending=False,
                      error="cached synchronization metadata is invalid; remote freshness is unknown")
    if stored.get("lastSuccess") is None and stored.get("state") in {"fresh", "cached"}:
        stored["state"] = "unknown"
    return stored

def _digest(records: list[dict]) -> str:
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sync(target: Path, config: dict, records: list[dict], *, publish: bool = False, force: bool = False, refresh: bool = True, load_local: Callable[[], list[dict]] | None = None) -> dict:
    """Return validated cached/remote records and explicit synchronization health.

    Configuration is validated by the adapter. `refresh=False` never contacts a remote;
    failed publication is retained as pending and retried on the next due automatic refresh.
    Filesystem callers supply `load_local` so publication re-reads the authoritative atomic
    local records under the synchronization lock, independent of snapshot age or wall clocks.
    """
    result: dict = {"namespace": "", "records": [], "sync": {"state": "unknown", "lastSuccess": None, "lastAttempt": None, "pending": publish, "remote": config["remote"], "branch": config["branch"], "error": ""}}
    lock_fd = None
    lock_acquired = False
    cache = None
    stored = {}
    published_hash = None
    try:
        cache, namespace = _locations(target, config)
        result["namespace"] = namespace
        cache_file = cache / "state.json"
        stored = _cached(cache_file)
        result["records"] = stored.get("records", [])
        meta = result["sync"]
        meta.update({key: stored[key] for key in ("lastSuccess", "lastAttempt", "pending", "error") if key in stored})
        local = _public(records, namespace)
        local_hash = _digest(local)
        published_hash = stored.get("publishedHash")
        meta["pending"] = bool(meta["pending"] or publish or (local and local_hash != published_hash))
        meta["state"] = stored.get("state", "unknown")
        if meta["pending"] and meta["state"] in {"fresh", "cached"}:
            meta["state"] = "pending"
        if not refresh:
            if meta["state"] == "fresh":
                meta["state"] = "cached"
            return result
        now = time.time()
        age = now - (meta["lastAttempt"] or 0)
        if not publish and not force and 0 <= age < config.get("syncIntervalSeconds", 60):
            if meta["state"] == "fresh":
                meta["state"] = "cached"
            return result
        lock_fd = os.open(cache / "sync.lock", os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise SyncError("coordination synchronization lock is not a regular file")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_acquired = True
        except BlockingIOError:
            meta.update(state=("pending" if meta["pending"] else "cached") if meta["lastSuccess"] else "unknown", error="another local synchronization is in progress")
            return result
        # A previous holder may have completed between our initial cache read and this lock.
        latest = _cached(cache_file)
        if latest:
            result["records"] = latest.get("records", [])
            meta["lastSuccess"] = latest.get("lastSuccess")
            published_hash = latest.get("publishedHash")
            meta["pending"] = bool(meta["pending"] or latest.get("pending"))
        deadline = time.monotonic() + config.get("timeoutSeconds", 2)
        meta["lastAttempt"] = now
        fetch_urls = _run(target, ["remote", "get-url", "--all", config["remote"]], deadline).stdout.splitlines()
        push_urls = _run(target, ["remote", "get-url", "--push", "--all", config["remote"]], deadline).stdout.splitlines()
        if len(fetch_urls) != 1 or fetch_urls != push_urls:
            raise MetadataError("coordination remote must have one matching fetch and push URL; configure a dedicated remote")
        for _ in range(3):
            tip = _fetch(target, config, cache, deadline)
            remote, problems = _read_tree(target, tip, deadline)
            result["records"] = remote
            meta.update(lastSuccess=time.time(), error=problems)
            if load_local is not None:
                # A sibling may have replaced a record after the caller took its snapshot.
                # Re-read for every retry; timestamps cannot order writes after clock rollback.
                local = _public(load_local(), namespace)
                local_hash = _digest(local)
                meta["pending"] = bool(meta["pending"] or (local and local_hash != published_hash))
            if meta["pending"]:
                if not _publish(target, config, cache, namespace, local, tip, deadline):
                    continue
                own = {record["lane"] for record in local}
                result["records"] = [record for record in remote if record["namespace"] != namespace or record["lane"] not in own] + local
                meta["pending"] = False
                published_hash = local_hash
                if load_local is not None:
                    current_hash = _digest(_public(load_local(), namespace))
                    meta["pending"] = current_hash != published_hash
                    if meta["pending"] and not problems:
                        meta["error"] = "local declarations changed during synchronization; publication remains pending"
            meta["state"] = "unknown" if problems else ("pending" if meta["pending"] else "fresh")
            break
        else:
            raise SyncError("remote changed during synchronization; publication remains pending")
    except MetadataError as exc:
        result["sync"].update(state="unknown", error=str(exc))
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, SyncError) else "coordination synchronization unavailable; cached declarations may be stale"
        result["sync"].update(state="offline", error=message)
    finally:
        if lock_fd is not None:
            try:
                if cache is not None and lock_acquired:
                    _atomic(cache / "state.json", {"records": result["records"], "publishedHash": published_hash, **result["sync"]})
            except (OSError, ValueError):
                result["sync"].update(state="unknown", error="coordination cache could not be saved")
            os.close(lock_fd)
    return result
