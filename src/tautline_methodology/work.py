"""Local, advisory work declarations shared by sibling Git worktrees.

No daemon, network call, review, lease, or permission gate. One atomic JSON record per lane in
Git's common directory gives peers immediate visibility without committing scratch state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from tautline_methodology.util import resolve_env

SCHEMA = "tautline-work/v1"
MAX_RECORD_BYTES = 16_384
MAX_RECORDS = 256
TERMINAL = {"completed", "abandoned"}
STATUSES = {"active", "blocked", *TERMINAL}
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class WorkError(ValueError):
    pass


def _safe(value: object, limit: int = 180) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    text = " ".join(text.split())
    text = "".join(c for c in text if c.isprintable())
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", text)
    return text[:limit]


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=1
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkError("local Git state unavailable") from exc
    if result.returncode:
        raise WorkError("target must be an accessible Git worktree")
    return result.stdout.strip()


def identity(target: Path, lane: str | None = None) -> dict:
    lines = _git(
        target, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir"
    ).splitlines()
    if len(lines) != 3:
        raise WorkError("could not resolve Git worktree identity")
    root, git_dir, common_dir = map(Path, lines)
    lane = lane or resolve_env("TAUTLINE_WORK_LANE") or (
        "lane-" + hashlib.sha256(str(git_dir.resolve()).encode()).hexdigest()[:12]
    )
    if not _ID.fullmatch(lane):
        raise WorkError("lane must be 1-64 letters, digits, underscores or hyphens")
    return {
        "lane": lane,
        "worktree": str(root.resolve()),
        "gitDir": str(git_dir.resolve()),
        "store": str(common_dir.resolve() / "tautline" / "work"),
    }


def _scope(value: str) -> str:
    # Explicit files/directories, including not-yet-created paths. Globs would imply a more
    # precise conflict detector than a declaration can provide; interfaces cover semantic overlap.
    if not value or "\\" in value or any(c in value for c in "*?[]"):
        raise WorkError("--path must be a repository-relative file or directory, without globs")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise WorkError("--path must stay inside the repository")
    return str(path)


def _validate(record: object, name: str) -> dict:
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise WorkError("unrecognized record schema")
    if record.get("lane") != name or not _ID.fullmatch(name):
        raise WorkError("record identity mismatch")
    for key in ("goal", "worktree", "gitDir", "branch"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise WorkError(f"missing {key}")
    if not all(Path(record[key]).is_absolute() for key in ("worktree", "gitDir")):
        raise WorkError("worktree identity paths must be absolute")
    for key in ("item", "pr", "blocker"):
        if not isinstance(record.get(key), str):
            raise WorkError(f"invalid {key}")
    if record.get("status") not in STATUSES:
        raise WorkError("unrecognized status")
    for key in ("paths", "interfaces", "dependsOn"):
        values = record.get(key)
        if not isinstance(values, list) or len(values) > 64 or any(
            not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in values
        ):
            raise WorkError(f"invalid {key}")
    for path in record["paths"]:
        if _scope(path) != path:
            raise WorkError("noncanonical path")
    for key in ("updatedAt", "expiresHours"):
        value = record.get(key)
        if (
            isinstance(value, bool) or not isinstance(value, (float, int))
            or not -1e15 < value < 1e15 or not math.isfinite(value)
        ):
            raise WorkError(f"invalid {key}")
    if record["updatedAt"] <= 0 or not 1 <= record["expiresHours"] <= 168:
        raise WorkError("invalid expiry")
    return record


def _read(path: Path) -> dict:
    # O_NONBLOCK also prevents a malformed FIFO from hanging session startup.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise WorkError("record is not a regular file")
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise WorkError("record exceeds size limit")
    return _validate(json.loads(raw), path.stem)


def _worktrees(target: Path) -> dict[str, str]:
    result = {}
    current = ""
    for line in _git(target, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = str(Path(line[9:]).resolve())
            result[current] = "(detached)"
        elif line.startswith("branch "):
            result[current] = line[7:].removeprefix("refs/heads/")
    return result


def _overlap(left: str, right: str) -> bool:
    return left == "." or right == "." or left == right or (
        left.startswith(right + "/") or right.startswith(left + "/")
    )


def snapshot(target: Path, lane: str | None = None) -> dict:
    current = identity(target, lane)
    store = Path(current["store"])
    records = []
    result = {"schema": SCHEMA, **current, "records": records, "overlaps": []}
    if store.is_symlink() or store.parent.is_symlink():
        raise WorkError("work store must not be a symlink")
    if not store.exists():
        return result
    if not store.is_dir():
        raise WorkError("work store is not a regular directory")
    trees = _worktrees(target)
    now = time.time()
    for index, path in enumerate(store.iterdir()):
        if index >= MAX_RECORDS:
            records.append({"lane": "store", "state": "UNKNOWN", "reason": "record limit exceeded"})
            break
        if not path.name.endswith(".json"):
            continue
        try:
            record = dict(_read(path))
            age = now - record["updatedAt"]
            status = record["status"]
            state, reason = status.upper(), ""
            if age < 0:
                state, reason = "UNKNOWN", "timestamp is in the future"
            elif status not in TERMINAL:
                if record["worktree"] not in trees or not Path(record["worktree"]).is_dir():
                    state, reason = "STALE", "worktree removed or unavailable"
                elif trees[record["worktree"]] != record["branch"]:
                    state, reason = "STALE", "worktree changed branch"
                elif age > record["expiresHours"] * 3600:
                    state, reason = "STALE", "declaration expired; owner may have stopped"
            record.update(state=state, reason=reason, ageHours=round(max(0, age) / 3600, 1))
            records.append(record)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            records.append({"lane": _safe(path.stem, 64), "state": "UNKNOWN", "reason": _safe(exc)})
    records.sort(key=lambda record: record["lane"])
    overlap_deadline = time.monotonic() + 0.2
    active = [r for r in records if r["state"] in {"ACTIVE", "BLOCKED"}]
    for index, first in enumerate(active):
        for second in active[index + 1:]:
            if time.monotonic() > overlap_deadline:
                records.append({"lane": "overlaps", "state": "UNKNOWN", "reason": "overlap scan exceeded local time budget"})
                return result
            paths = [f"{a} <> {b}" for a in first["paths"] for b in second["paths"] if _overlap(a, b)]
            interfaces = sorted(set(first["interfaces"]) & set(second["interfaces"]))
            same_item = first["item"] and first["item"] == second["item"]
            if paths or interfaces or same_item:
                result["overlaps"].append({
                    "lanes": [first["lane"], second["lane"]],
                    "paths": paths, "interfaces": interfaces, "item": first["item"] if same_item else "",
                })
    return result


def render(state: dict, *, all_records: bool = False, compact: bool = False) -> list[str]:
    records = [r for r in state["records"] if all_records or r["state"].lower() not in TERMINAL]
    lines = ["WORK (local, advisory): " + (f"{len(records)} declaration(s)" if records else "none declared")]
    for record in records[:6] if compact else records:
        marker = " (you)" if record["lane"] == state["lane"] else ""
        age = f" {record['ageHours']:g}h" if "ageHours" in record else ""
        lines.append(f"  {record['lane']}{marker} {record['state']}{age}: {_safe(record.get('goal') or record.get('reason'))}")
        details = []
        for label, key in (("branch", "branch"), ("item", "item"), ("paths", "paths"), ("interfaces", "interfaces"), ("depends", "dependsOn"), ("blocked", "blocker"), ("PR", "pr")):
            value = record.get(key)
            if value:
                details.append(f"{label}={_safe(', '.join(value) if isinstance(value, list) else value)}")
        if not compact and record.get("worktree"):
            details.append(f"worktree={_safe(record['worktree'])}")
        if record.get("reason") and record.get("goal"):
            details.append(_safe(record["reason"]))
        if details:
            lines.append("    " + "; ".join(details))
    if compact and len(records) > 6:
        lines.append(f"  {len(records) - 6} more; run `tautline work status` for all declarations")
    for overlap in state["overlaps"][:6] if compact else state["overlaps"]:
        detail = overlap["paths"] + overlap["interfaces"] + (["item=" + overlap["item"]] if overlap["item"] else [])
        lines.append(f"  OVERLAP {' / '.join(overlap['lanes'])}: {_safe('; '.join(detail))}")
    if records:
        lines.append("  Coordinate overlaps directly; STALE/UNKNOWN is uncertain. No work is blocked.")
    return lines


def advisory_lines(target: Path, cfg: dict | None = None) -> list[str]:
    """Silent for existing projects until enabled or somebody declares work; never raises."""
    try:
        state = snapshot(target)
        if not state["records"] and not (cfg or {}).get("workCoordination"):
            return []
        return render(state, compact=True)
    except Exception as exc:
        return [f"WORK UNKNOWN (advisory): {_safe(exc)}"]


def _write(store: Path, record: dict) -> None:
    if store.is_symlink() or store.parent.is_symlink():
        raise WorkError("work store must not be a symlink")
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(record, indent=2, sort_keys=True).encode() + b"\n"
    if len(raw) > MAX_RECORD_BYTES:
        raise WorkError("declaration exceeds 16KB; shorten scope or goal")
    fd, name = tempfile.mkstemp(prefix=".work-", dir=store)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(name, store / (record["lane"] + ".json"))
    finally:
        Path(name).unlink(missing_ok=True)


def command(args: argparse.Namespace) -> int:
    try:
        if getattr(args, "description", None) is not None:
            if args.action != "declare" or args.goal is not None:
                raise WorkError("a positional goal is only valid for declare; use --goal for updates")
            args.goal = args.description
        if args.action == "declare" and not args.goal:
            raise WorkError("declare requires a goal")
        target = args.target.resolve()
        state = snapshot(target, args.lane)
        if args.action == "status":
            if args.json:
                print(json.dumps(state, indent=2, sort_keys=True))
            else:
                print("\n".join(render(state, all_records=args.all)))
            return 0
        store = Path(state["store"])
        old_path = store / (state["lane"] + ".json")
        if args.action == "declare":
            record = {
                "schema": SCHEMA, "lane": state["lane"], "goal": args.goal,
                "paths": [], "interfaces": [], "dependsOn": [], "item": "", "pr": "",
                "blocker": "", "status": "active", "expiresHours": 24,
            }
        else:
            try:
                record = _read(old_path)
            except FileNotFoundError as exc:
                raise WorkError('no declaration for this lane; use `tautline work declare "goal"`') from exc
            if record["gitDir"] != state["gitDir"] and not (args.action == "abandon" and args.lane):
                raise WorkError("lane belongs to another worktree; use its --target or a different --lane")
        if old_path.exists() and args.action == "declare":
            old = _read(old_path)
            if old["gitDir"] != state["gitDir"]:
                raise WorkError("lane belongs to another worktree; choose a different --lane")
        for arg, key in (("goal", "goal"), ("paths", "paths"), ("interfaces", "interfaces"), ("depends_on", "dependsOn"), ("item", "item"), ("pr", "pr"), ("blocker", "blocker"), ("status", "status"), ("expires_hours", "expiresHours")):
            value = getattr(args, arg, None)
            if value is not None:
                record[key] = list(dict.fromkeys(_scope(v) for v in value)) if key == "paths" else value
        for arg, key in (("clear_paths", "paths"), ("clear_interfaces", "interfaces"), ("clear_dependencies", "dependsOn")):
            if getattr(args, arg, False):
                record[key] = []
        if args.action in {"finish", "abandon"}:
            record["status"] = "completed" if args.action == "finish" else "abandoned"
        elif args.action == "update" and record["status"] in TERMINAL:
            record["status"] = getattr(args, "status", None) or "active"
        record["updatedAt"] = time.time()
        if args.action != "abandon":
            record.update(
                worktree=state["worktree"], gitDir=state["gitDir"],
                branch=_worktrees(target).get(state["worktree"], "(detached)"),
            )
        _validate(record, state["lane"])
        _write(store, record)
        print(f"work {args.action}: {state['lane']} {record['status']} — {_safe(record['goal'])}")
        print("\n".join(render(snapshot(target, args.lane))))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        if args.action == "status":
            if args.json:
                print(json.dumps({"schema": SCHEMA, "records": [{"state": "UNKNOWN", "reason": _safe(exc)}], "overlaps": []}))
            else:
                print(f"WORK UNKNOWN (advisory): {_safe(exc)}")
            return 0
        print(f"work_error: {_safe(exc)}", file=sys.stderr)
        return 1


def configure(parser) -> None:
    parser.add_argument("action", choices=("declare", "status", "update", "finish", "abandon"))
    parser.add_argument("description", nargs="?", help="The goal for declare.")
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--lane", help="Stable agent ID; default is this worktree (or TAUTLINE_WORK_LANE).")
    parser.add_argument("--all", action="store_true", help="Include completed and abandoned declarations in status.")
    parser.add_argument("--json", action="store_true", help="Machine-readable status.")
    parser.add_argument("--goal", help="Replace the declaration's goal.")
    parser.add_argument("--pr", help="Related PR URL; empty string clears it.")
    parser.add_argument("--path", dest="paths", action="append", help="Repo-relative file/directory; repeat to replace scope.")
    parser.add_argument("--interface", dest="interfaces", action="append", help="Shared interface/contract name; repeatable.")
    parser.add_argument("--depends-on", action="append", help="Lane or external dependency; repeatable.")
    parser.add_argument("--item", help="Backlog item ID.")
    parser.add_argument("--status", choices=("active", "blocked"))
    parser.add_argument("--blocker", help="What is needed; empty string clears it.")
    parser.add_argument("--expires-hours", type=float, help="Freshness lifetime, 1-168 hours (default 24).")
    for field in ("paths", "interfaces", "dependencies"):
        parser.add_argument(f"--clear-{field}", action="store_true")
