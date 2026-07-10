"""Public-release helper primitives for the Minervit methodology CLI."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def allowed_account_like_token(
    token: str,
    line: str,
    *,
    placeholder_account_ids: set[str],
) -> bool:
    if token in placeholder_account_ids or len(set(token)) == 1:
        return True
    if re.search(r"\btouch\s+-t\s+" + re.escape(token) + r"\b", line):
        try:
            datetime.strptime(token, "%Y%m%d%H%M")
            return True
        except ValueError:
            return False
    return False


def add_issue(
    issues: list[dict],
    seen: set[tuple[str, str, int | None, str]],
    code: str,
    path: Path,
    message: str,
    *,
    repo_root: Path,
    max_issues_per_rule: int,
    line: int | None = None,
) -> None:
    try:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    key = (code, rel, line, message)
    if key in seen:
        return
    if sum(1 for issue in issues if issue["code"] == code) >= max_issues_per_rule:
        return
    seen.add(key)
    issue = {"code": code, "path": rel, "message": message}
    if line is not None:
        issue["line"] = line
    issues.append(issue)


def export_path_included(
    rel: Path,
    *,
    allowed_product_docs: tuple[str, ...],
    excluded_prefixes: tuple[str, ...],
) -> bool:
    rel_posix = rel.as_posix()
    if rel_posix.startswith("docs/product/"):
        return rel_posix in allowed_product_docs
    return not any(rel_posix.startswith(prefix) for prefix in excluded_prefixes)


def export_marker_text(
    *,
    version: str,
    marker_schema: str,
    private_terms_source: str = "none",
    private_terms_count: int = 0,
) -> str:
    return json.dumps(
        {
            "privateTermsCount": private_terms_count,
            "privateTermsSource": private_terms_source,
            "schema": marker_schema,
            "version": version,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def export_destination_is_prior_export(
    destination: Path,
    *,
    marker_name: str,
    marker_schema: str,
) -> bool:
    marker = destination / marker_name
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("schema") == marker_schema


def private_adapter_entries(
    adapter_dir: Path,
    *,
    allowed_source_adapters: set[str],
) -> list[dict]:
    if not adapter_dir.exists():
        return []
    entries = []
    for path in sorted(adapter_dir.glob("*.json")):
        if path.name.startswith(".") or path.name in allowed_source_adapters:
            continue
        project = path.stem
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("project"), str) and payload["project"].strip():
                project = payload["project"].strip()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        entries.append({"path": path, "project": project})
    return entries


def private_terms_file_terms(private_terms_file: Path | None = None) -> list[str]:
    if private_terms_file is None:
        return []
    try:
        raw = private_terms_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"private terms file is not readable: {private_terms_file}: {exc}") from exc
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"private terms file must be newline/comma text or a JSON string array: {private_terms_file}") from exc
        if not isinstance(payload, list) or not all(isinstance(term, str) for term in payload):
            raise SystemExit(f"private terms file JSON must be an array of strings: {private_terms_file}")
        return [term.strip() for term in payload if term.strip()]
    terms = []
    for line in raw.splitlines():
        line = line.split("#", 1)[0]
        terms.extend(term.strip() for term in line.split(",") if term.strip())
    return terms


def configured_private_terms(
    *,
    env_value: str,
    private_terms_file: Path | None = None,
) -> list[str]:
    terms = [term.strip() for term in re.split(r"[\n,]", env_value) if term.strip()]
    terms.extend(private_terms_file_terms(private_terms_file))
    return terms


def private_terms(
    private_adapters: list[dict],
    *,
    configured_terms: list[str],
    reference_adapter_slug: str,
) -> list[str]:
    terms: set[str] = set()
    public_slug = reference_adapter_slug.replace("-", " ")
    for entry in private_adapters:
        path = Path(entry["path"])
        stem = path.stem
        project = str(entry.get("project") or "").strip()
        for term in {stem, stem.replace("-", " "), stem.replace("_", " "), project}:
            normalized = re.sub(r"\s+", " ", term).strip()
            if len(normalized) >= 4 and normalized.lower() != public_slug:
                terms.add(normalized)
    for term in configured_terms:
        normalized = re.sub(r"\s+", " ", term).strip()
        if len(normalized) >= 4 and normalized.lower() != public_slug:
            terms.add(normalized)
    return sorted(terms, key=lambda term: (-len(term), term.lower()))


def private_terms_source(
    *,
    env_value: str,
    private_terms_file: Path | None = None,
) -> str:
    has_env = bool(env_value.strip())
    has_file = private_terms_file is not None
    if has_env and has_file:
        return "env+file"
    if has_file:
        return "file"
    if has_env:
        return "env"
    return "none"


def path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def private_terms_file_allowed_for_export(
    private_terms_file: Path | None,
    source_root: Path,
    destination: Path,
) -> tuple[bool, str]:
    if private_terms_file is None:
        return True, ""
    terms_path = private_terms_file.resolve()
    source = source_root.resolve()
    dest = destination.resolve()
    if terms_path == source or path_is_under(terms_path, source):
        return (
            False,
            "private terms file must be outside the methodology repository so it cannot be exported",
        )
    if terms_path == dest or path_is_under(terms_path, dest):
        return (
            False,
            "private terms file must be outside the public-release-export destination",
        )
    return True, ""
