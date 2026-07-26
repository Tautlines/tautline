"""Usage-record accounting leaves: dedupe keys, token/parse coercion, and report grouping keys."""

from __future__ import annotations

import hashlib
import json


def usage_record_key(record: dict) -> str:
    existing = str(record.get("dedupe_key") or "").strip()
    if existing:
        return existing
    basis = "|".join(
        str(record.get(key, ""))
        for key in ["provider", "model", "session_id", "request_id", "ts", "activity"]
    )
    basis += "|" + json.dumps(record.get("tokens", {}), sort_keys=True)
    basis += "|" + str(record.get("cost_usd", ""))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def usage_tokens(record: dict) -> dict[str, int]:
    tokens = record.get("tokens") if isinstance(record.get("tokens"), dict) else {}
    return {
        "input": int(tokens.get("input", 0) or 0),
        "output": int(tokens.get("output", 0) or 0),
        "cache_creation_input": int(tokens.get("cache_creation_input", 0) or 0),
        "cache_read_input": int(tokens.get("cache_read_input", 0) or 0),
        "total": int(tokens.get("total", 0) or 0),
    }


def usage_nonnegative_int(value: int | str | None, field: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{field} must be a non-negative integer") from exc
    if parsed < 0:
        raise SystemExit(f"{field} must be a non-negative integer")
    return parsed


def usage_float_or_none(value: str | None, field: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SystemExit(f"{field} must be a non-negative decimal value") from exc
    if parsed < 0:
        raise SystemExit(f"{field} must be a non-negative decimal value")
    return parsed


def usage_report_key(record: dict, by: str) -> str:
    if by == "product":
        return str(record.get("project") or record.get("repo_slug") or "unknown")
    if by == "day":
        return str(record.get("ts", ""))[:10] or "unknown"
    return str(record.get(by) or "unknown")
