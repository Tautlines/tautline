"""Telemetry helper primitives for the Minervit methodology CLI."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .util import resolve_env


TELEMETRY_ENABLED_ENV = "MINERVIT_METHODOLOGY_TELEMETRY"
TELEMETRY_PATH_ENV = "MINERVIT_METHODOLOGY_TELEMETRY_PATH"
GUARD_EVENT_MECHANISMS = {"phrase", "state", "regex-command"}
GUARD_EVENT_DETAIL_LIMIT = 200
GUARD_EVENTS_FILE = ".ai-runs/guard-events.jsonl"


def telemetry_enabled() -> bool:
    return resolve_env(TELEMETRY_ENABLED_ENV).strip().lower() in {"1", "on", "true", "yes"}


def telemetry_path() -> Path:
    override = resolve_env(TELEMETRY_PATH_ENV).strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "minervit" / "telemetry.jsonl"


def record_gate_telemetry(gate: str, outcome: str, **fields: object) -> None:
    """Best-effort opt-in gate telemetry. This must never affect guard behavior."""
    if not telemetry_enabled():
        return
    try:
        safe_fields = {k: v for k, v in fields.items() if isinstance(v, (int, float, bool))}
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gate": gate,
            "outcome": outcome,
            **safe_fields,
        }
        path = telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def guard_log_event(adapter_root: Path | str, check_id: str, fired: bool, mechanism: str, detail: object = "") -> None:
    """Best-effort lane-local guard-fire telemetry. This must never affect guard behavior."""
    try:
        root = Path(adapter_root).expanduser()
        path = root / GUARD_EVENTS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        detail_text = str(detail or "").replace("\r", "\n")
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "check_id": str(check_id),
            "fired": bool(fired),
            "mechanism": mechanism if mechanism in GUARD_EVENT_MECHANISMS else "state",
            "detail": detail_text[:GUARD_EVENT_DETAIL_LIMIT],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:
        return


def parse_guard_report_since(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def guard_event_after_since(record: dict, since: datetime | None) -> bool:
    if since is None:
        return True
    try:
        parsed = datetime.fromisoformat(str(record.get("ts") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) >= since
