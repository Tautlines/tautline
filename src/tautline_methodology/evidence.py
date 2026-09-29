"""Optional execution receipts. No hooks, automatic reruns, or completion gates."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class EvidenceUnavailable(Exception):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceUnavailable("Git observation unavailable") from exc
    if result.returncode:
        raise EvidenceUnavailable("Git observation unavailable")
    return result.stdout


def repository_root(target: Path) -> Path:
    return Path(os.fsdecode(_git(target, "rev-parse", "--show-toplevel").strip())).resolve()


def receipt_dir(target: Path) -> Path:
    root = repository_root(target)
    common = Path(os.fsdecode(_git(root, "rev-parse", "--git-common-dir").strip()))
    if not common.is_absolute():
        common = root / common
    key = hashlib.sha256(os.fsencode(root)).hexdigest()[:24]
    return common.resolve() / "tautline" / "evidence" / key


def fingerprint(target: Path) -> dict:
    """Hash HEAD, index entries, and actual tracked/nonignored contents, including dirty files.

    Ignored build output and Git's own metadata never change the content identity. Symlinks are
    hashed as links, never followed outside the checkout. Nested repositories are unknown rather
    than silently treated as an empty directory. File stat and membership checks catch edits
    during the scan without retaining file contents or names in the receipt.
    """
    root = repository_root(target)
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    index = _git(root, "ls-files", "--stage", "-z")
    listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    digest = hashlib.sha256(hashlib.sha256(index).digest())
    paths = sorted(set(listing.split(b"\0")) - {b""})
    for raw in paths:
        path = root / os.fsdecode(raw)
        digest.update(len(raw).to_bytes(8, "big") + raw)
        try:
            before = path.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        digest.update(str(stat.S_IMODE(before.st_mode)).encode() + b"\0")
        if stat.S_ISLNK(before.st_mode):
            digest.update(b"link\0" + hashlib.sha256(os.fsencode(os.readlink(path))).digest())
        elif stat.S_ISREG(before.st_mode):
            digest.update(b"file\0")
            contents = hashlib.sha256()
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    contents.update(chunk)
            digest.update(contents.digest())
        else:
            raise EvidenceUnavailable("Nested repositories or special files cannot be fingerprinted")
        after = path.lstat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise EvidenceUnavailable("Working tree changed while fingerprinting")
    if (listing != _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
            or index != _git(root, "ls-files", "--stage", "-z")
            or head != _git(root, "rev-parse", "HEAD").decode("ascii").strip()):
        raise EvidenceUnavailable("Working tree changed while fingerprinting")
    return {"head": head, "fingerprint": digest.hexdigest(), "files": len(paths)}


def _snapshot(root: Path) -> dict | None:
    try:
        return fingerprint(root)
    except (EvidenceUnavailable, OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _latest_lock(store: Path, *, writing: bool = False):
    """Only serialize pointer publication/reads, never fingerprinting or command execution."""
    fd = os.open(store / ".latest.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise EvidenceUnavailable("Latest-start lock is not a regular file")
        deadline = time.monotonic() + (0.25 if writing else 0)
        while True:
            try:
                operation = fcntl.LOCK_EX if writing else fcntl.LOCK_SH
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise EvidenceUnavailable("Latest-start publication is busy") from exc
                time.sleep(0.001)
        yield
    finally:
        os.close(fd)


def _latest_run_id(store: Path) -> str:
    with _latest_lock(store):
        fd = os.open(store / "latest", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise EvidenceUnavailable("Latest-start pointer is not a regular file")
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise EvidenceUnavailable("Latest-start pointer exceeds size limit")
        pointer = json.loads(raw)
        if (not isinstance(pointer, dict)
                or pointer.get("schema") != "tautline-evidence-latest/v1"
                or not isinstance(pointer.get("runId"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", pointer["runId"])):
            raise EvidenceUnavailable("Latest-start pointer is invalid")
        return pointer["runId"]


def _execute(root: Path, command: list[str]) -> tuple[int, bool]:
    handlers = {}
    process = None
    pending_signal = None

    def interrupted(signum, _frame):
        # Raising here can unwind Popen after it spawned a child but before it returned the
        # handle. Remember the first signal instead; finish assigning the handle before cleanup.
        nonlocal pending_signal
        if pending_signal is None:
            pending_signal = signum

    def stop_group(signum: int) -> tuple[int, bool]:
        if process is not None:
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # A leader can exit while its descendants ignore the first signal and keep stdout
            # pipes open. Always remove the remaining group, even if the leader was reaped.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print("evidence: termination requested; child could not be reaped yet", file=sys.stderr)
        return 128 + signum, True

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                handlers[signum] = signal.signal(signum, interrupted)
        if pending_signal is not None:
            return stop_group(pending_signal)
        # Inherit the terminal, never collect/save output. A new process group lets an interrupt
        # reach descendants too, including test runners that spawn their own workers.
        process = subprocess.Popen(command, cwd=root, start_new_session=True)
        while True:
            if pending_signal is not None:
                return stop_group(pending_signal)
            try:
                code = process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
            if pending_signal is not None:
                return stop_group(pending_signal)
            return stop_group(-code) if code < 0 else (code, False)
    except OSError:
        if pending_signal is not None:
            return stop_group(pending_signal)
        print("evidence: command could not be started", file=sys.stderr)
        return 127, False
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _command_summary(command: list[str]) -> dict:
    # Even argv[0] may contain a credential. Only known public executable names are retained;
    # all arguments, shell snippets, environment values, and raw output are deliberately omitted.
    program = Path(command[0]).name
    known = {"python", "python3", "python3.12", "pytest", "ruff", "mypy", "make", "npm",
             "pnpm", "yarn", "uv", "cargo", "go", "node", "bash", "sh", "test.sh"}
    return {"program": program if program in known else "custom command",
            "argumentCount": len(command) - 1, "arguments": "omitted"}


def record_run(target: Path, command: list[str]) -> int:
    if not command:
        print("evidence: provide an executable and arguments after --", file=sys.stderr)
        return 2
    try:
        root = repository_root(target)
        store = receipt_dir(root)
        started = time.monotonic()
        run_id = f"{time.time_ns():020d}-{uuid.uuid4().hex}"
        path = store / f"{run_id}.json"
        record: dict = {"schema": "tautline-evidence/v1", "runId": run_id, "state": "running",
                  "startedAt": _now(), "command": _command_summary(command),
                  "before": _snapshot(root), "after": None, "exitCode": None}
        # Publish before execution. A new interrupted run must supersede an older passing one.
        _write(path, record)
        # Receipt names remain identifiers, never chronology: wall clocks can move backward.
        # Publishing the pointer defines start order; completing a run only updates its receipt.
        with _latest_lock(store, writing=True):
            _write(store / "latest", {"schema": "tautline-evidence-latest/v1", "runId": run_id})
    except (EvidenceUnavailable, OSError, ValueError):
        print("evidence: cannot create a receipt; command was not started", file=sys.stderr)
        return 2
    code, interrupted = _execute(root, command)
    record.update(state="finished", finishedAt=_now(), elapsedSeconds=round(time.monotonic() - started, 3),
                  after=_snapshot(root), exitCode=code, interrupted=interrupted)
    try:
        _write(path, record)
    except OSError:
        # The durable running receipt remains unknown; never leave a previous green receipt as
        # the latest observation. Preserve the explicit command's actual exit code.
        print("evidence: command finished but receipt completion could not be saved", file=sys.stderr)
    return code


def evidence_status(target: Path) -> dict:
    result = {"schema": "tautline-evidence-status/v1", "state": "unknown", "observedAt": _now(),
              "reason": "No execution receipt for this worktree"}
    try:
        store = receipt_dir(target)
        if not store.exists():
            return result
        run_id = _latest_run_id(store)
        record = json.loads((store / f"{run_id}.json").read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("schema") != "tautline-evidence/v1"
                or record.get("runId") != run_id):
            raise ValueError("invalid receipt")
        result["receipt"] = record
        if record.get("state") == "running":
            result.update(state="running", reason="Latest run has no completion; running or interrupted")
            return result
        current = _snapshot(repository_root(target))
        before, after = record.get("before"), record.get("after")
        if record.get("state") != "finished" or current is None or not before or not after:
            result["reason"] = "Complete content fingerprints are unavailable"
        elif record.get("interrupted") is True:
            result.update(state="interrupted", reason="Latest command was interrupted")
        elif before != after or current != after:
            result.update(state="stale", reason="HEAD, index, or files changed during or after the run")
        elif type(record.get("exitCode")) is not int or record.get("interrupted") is not False:
            result["reason"] = "Receipt has no trustworthy exit result"
        elif record["exitCode"] == 0:
            result.update(state="fresh_pass", reason="Recorded command exited 0; repository fingerprints match")
        else:
            result.update(state="failed", reason=f"Recorded command exited {record['exitCode']}")
        # A newer start may have published while we fingerprinted the tree. Never report an
        # earlier pass as current in that case; another status read observes the newer receipt.
        if _latest_run_id(store) != run_id:
            result.update(state="unknown", reason="A newer execution started during this observation")
    except (EvidenceUnavailable, OSError, ValueError):
        result.update(state="unknown", reason="Repository or latest receipt is unavailable or corrupt")
    return result


def evidence_command(args: argparse.Namespace) -> int:
    if args.action == "run":
        return record_run(args.target, args.command)
    result = evidence_status(args.target)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Evidence: {result['state']} — {result['reason']}")
        print("Scope: recorded command and repository files only; no merge or deployment claim.")
    return 0
