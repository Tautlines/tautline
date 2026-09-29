"""Local operator replies: explicit answer, repeatable delivery, explicit acknowledgement.

Replies live beside the existing repo event log. Startup reads only these small files, never
the historical ledger and never a network service. No command executes the answer's text.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "tautline-inbox-answer/v1"
MAX_REPLY_BYTES = 16384
MAX_REPLIES = 2000


def decision_id(row: dict) -> str:
    value = json.dumps([row.get(k) for k in ("repo", "lane_id", "seq", "ts")])
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def response_dir(data: dict, target: Path, cli) -> Path:
    return cli.observability_event_paths(data, target)[1].parent / "answers"


def _valid(row, name: str) -> bool:
    if not isinstance(row, dict) or row.get("schema") != SCHEMA or row.get("id") != name:
        return False
    if not re.fullmatch(r"[a-f0-9]{20}", name):
        return False
    if not all(isinstance(row.get(k), str) and 0 < len(row[k]) <= 4096
               for k in ("lane_id", "summary", "answer", "answered_at")):
        return False
    try:
        for key in ("answered_at", "acknowledged_at"):
            value = row.get(key)
            if value is not None:
                if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
                    return False
    except ValueError:
        return False
    return True


def _read(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPLY_BYTES:
            raise ValueError("invalid answer file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            raw = stream.read(MAX_REPLY_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_REPLY_BYTES:
            raise ValueError("oversized answer file")
        row = json.loads(raw)
    finally:
        if fd >= 0:
            os.close(fd)
    if not _valid(row, path.stem):
        raise ValueError("invalid answer record")
    return row


def load(pairs, cli):
    records, warnings, visited = {}, [], set()
    for data, target in pairs:
        directory = response_dir(data, target, cli)
        if directory in visited or not directory.exists():
            continue
        visited.add(directory)
        try:
            if directory.is_symlink():
                raise ValueError("answer directory is a symlink")
            with os.scandir(directory) as entries:
                count = 0
                for entry in entries:
                    if not entry.name.endswith(".json"):
                        continue
                    count += 1
                    if count > MAX_REPLIES:
                        warnings.append("inbox: UNKNOWN — too many answers; inspect the answer directory")
                        break
                    path = Path(entry.path)
                    try:
                        row = _read(path)
                        records[row["id"]] = (row, path)
                    except (OSError, ValueError, TypeError, RecursionError):
                        warnings.append("inbox: UNKNOWN — an unreadable or invalid answer was ignored")
        except (OSError, ValueError):
            warnings.append("inbox: UNKNOWN — answer directory could not be read")
    return records, warnings


@contextmanager
def _lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise ValueError("answer directory must not be a symlink")
    fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        # A reply write never waits behind another process. Retry is cheap and explicit.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _write(path: Path, row: dict):
    fd, name = tempfile.mkstemp(prefix=".answer-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(row, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _emit(args, obj, text):
    print(json.dumps(obj, indent=2) if args.json else text)


def action(args, pairs, cli) -> int:
    """Called only for explicit answer/read-answer/ack actions; ordinary listing stays in cli."""
    records, warnings = load(pairs, cli)
    for warning in warnings:
        print(warning, file=cli.sys.stderr)
    lane_ids = {cli.instrumentation_lane_id(target) for _data, target in pairs}
    try:
        if getattr(args, "answers", False):
            answers = [row for row, _path in records.values()
                       if row["lane_id"] in lane_ids and row.get("acknowledged_at") is None]
            answers.sort(key=lambda row: (row["answered_at"], row["id"]))
            lines = [f"{row['id']}  {cli._ledger_safe(row['summary'], 80)}\n"
                     f"  answer: {cli._ledger_safe(row['answer'])}" for row in answers]
            if answers:
                lines.append("After incorporating an answer: tautline inbox --ack <id>")
            _emit(args, {"schema": SCHEMA, "answers": answers, "warnings": warnings},
                  "\n".join(lines) or "inbox: no unacknowledged answers for this lane")
            return 0
        ident = getattr(args, "answer", None) or getattr(args, "ack", None)
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{20}", ident):
            raise ValueError("use the decision id printed by tautline inbox")
        if getattr(args, "ack", None):
            if ident not in records or records[ident][0]["lane_id"] not in lane_ids:
                raise ValueError("no answer with that id in the requested lane(s)")
            _row, path = records[ident]
            with _lock(path.parent):
                row = _read(path)
                row["acknowledged_at"] = row.get("acknowledged_at") or _now()
                _write(path, row)
            _emit(args, {"id": ident, "status": "acknowledged"}, f"inbox: {ident} acknowledged")
            return 0
        text = cli._ledger_safe(getattr(args, "text", None) or "")
        errors = cli.validate_event_value(text, "answer")
        if errors:
            raise ValueError("; ".join(errors))
        results, _skipped, read_warnings = cli.read_countable_decisions(pairs)
        for warning in read_warnings:
            print(warning, file=cli.sys.stderr)
        matches = [row for row, _ts in results
                   if decision_id(row) == ident and cli.is_pending_decision(row)]
        if not matches:
            raise ValueError("no pending decision with that id in the requested lane(s)")
        question = matches[0]
        data, target = next((data, target) for data, target in pairs
                            if cli.instrumentation_lane_id(target) == question["lane_id"])
        path = response_dir(data, target, cli) / f"{ident}.json"
        with _lock(path.parent):
            if path.exists():
                row = _read(path)
                if row["answer"] != text:
                    raise ValueError("already answered differently; record a new decision to revise it")
            else:
                row = {"schema": SCHEMA, "id": ident, "lane_id": question["lane_id"],
                       "summary": question["summary"], "answer": text,
                       "answered_at": _now(), "acknowledged_at": None}
                _write(path, row)
        _emit(args, {"id": ident, "status": "answered"},
              f"inbox: {ident} answered; source lane will see it until acknowledged")
        return 0
    except (OSError, ValueError, StopIteration) as exc:
        print(f"inbox_error: {cli._ledger_safe(str(exc))}", file=cli.sys.stderr)
        return 1


def startup_lines(target: Path, cli) -> list[str]:
    """No event-history scan, no remote call, and no acknowledgement on delivery."""
    try:
        data = cli.ledger_target_data(target)
        if not response_dir(data, target, cli).exists():
            return []
        records, warnings = load([(data, target)], cli)
        lane_id = cli.instrumentation_lane_id(target)
        answers = [row for row, _path in records.values()
                   if row["lane_id"] == lane_id and row.get("acknowledged_at") is None]
        lines = list(warnings[:1])
        if answers:
            lines.append(f"inbox: {len(answers)} operator answer(s); read `tautline inbox --answers`, "
                         "incorporate, then `tautline inbox --ack <id>`.")
            for row in sorted(answers, key=lambda row: row["answered_at"])[:3]:
                lines.append(f"  {row['id']}: {cli._ledger_safe(row['answer'], 240)}")
        return lines
    except (OSError, ValueError, SystemExit):
        return ["inbox: UNKNOWN — could not read operator answers"]
