"""Pure stdlib utility helpers for the Minervit methodology CLI."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SECRET_PARAM_RE = re.compile(r"((?:key|token|secret|password|pwd|sig|signature)=)([^\s&'\"]+)", re.IGNORECASE)
_CHAT_WEBHOOK_RE = re.compile(r"(https://chat\.googleapis\.com/\S+)")
_GENERIC_WEBHOOK_RE = re.compile(r"(https://hooks\.\S+|https://\S*webhook\S*)", re.IGNORECASE)
_SECRET_ENV_SUFFIXES = ("_WEBHOOK", "_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY", "_APIKEY")

SLUG_MAX_LENGTH = 120


def redact_secrets(text: str) -> str:
    """Mask secrets before they reach any sink (background-run log, SystemExit text, error paths).

    sec-secrets-1/3/4/5 (productization): there was no central redaction utility, so webhook URLs and
    token/secret query params leaked into plaintext logs, the process table, and error strings. This
    is the single choke point: call it at EVERY sink that emits caller-influenced text.
    Masks: Google Chat / generic webhook URLs, key/token/secret/password/signature query params, and
    the live values of any environment variable whose name ends in a secret-ish suffix.
    """
    if not text:
        return text
    # Live env-var secret values first (most specific): replace the actual secret string wherever it
    # appears, so a webhook URL pulled from the environment is masked even without a recognized param.
    for name, value in os.environ.items():
        if value and len(value) >= 8 and name.upper().endswith(_SECRET_ENV_SUFFIXES):
            text = text.replace(value, f"***{name}***")
    text = _CHAT_WEBHOOK_RE.sub("https://chat.googleapis.com/***redacted***", text)
    text = _GENERIC_WEBHOOK_RE.sub("***redacted-webhook***", text)
    text = _SECRET_PARAM_RE.sub(r"\1***redacted***", text)
    return text


def bootstrap_fail_command(field: str) -> str:
    return f"echo 'BOOTSTRAP REQUIRED: configure commands.{field} in project adapter' >&2; exit 1"


def title_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", value) if part) or "Project"


def normalize_repo_slug(value: str) -> str | None:
    text = value.strip()
    if not text or text.startswith("<") or " " in text:
        return None
    patterns = [
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
        r"gitlab\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
        r"(?P<owner>[^/:]+)/(?P<repo>[^/.]+)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}".lower()
    return None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_mtime(value: float | None) -> str:
    if value is None:
        return "none"
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted version like '0.6.79' into a comparable integer tuple. Non-numeric or
    missing components degrade to 0 so comparisons never raise on malformed input."""
    parts: list[int] = []
    for part in str(version).strip().split("."):
        match = re.match(r"\d+", part)
        parts.append(int(match.group(0)) if match else 0)
    return tuple(parts)


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+)\s*([smhdw]?)\s*", value or "")
    if not match:
        raise SystemExit("--since must be a duration such as 30m, 24h, or 7d")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def parse_event_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def slugify(text: str, fallback: str = "lane") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        return fallback
    if len(slug) > SLUG_MAX_LENGTH:
        # Slugs are used to build filenames (milestone-update markers, plan/
        # implementation-review manifests). A name over the filesystem limit
        # (NAME_MAX, 255 on macOS/Linux) raises ENAMETOOLONG, which previously
        # made a milestone whose "title" is a full paragraph impossible to
        # publish -- and therefore impossible to complete. Bound the slug and
        # append a short deterministic digest so distinct long inputs keep
        # distinct, stable slugs instead of colliding on a shared prefix.
        digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
        keep = SLUG_MAX_LENGTH - len(digest) - 1
        slug = f"{slug[:keep].rstrip('-')}-{digest}"
    return slug


def first_dir_pattern(path_text: str) -> str:
    path = Path(path_text)
    return f"{path.parts[0]}/" if path.parts else ""


def path_display(target: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(target.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def path_relative_to_target(target: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(target.resolve(strict=False)).as_posix()
    except ValueError as exc:
        raise ValueError(f"{path} is outside target {target}") from exc


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def compact_path_list(paths: list[Path], target: Path, limit: int = 5) -> str:
    if not paths:
        return "none"
    preview = ", ".join(path_display(target, path) for path in paths[:limit])
    suffix = "" if len(paths) <= limit else f", ... +{len(paths) - limit} more"
    return f"{len(paths)} - {preview}{suffix}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_atomic(path: Path, content: str) -> None:
    """arch-errors-5: write via a temp file + atomic rename so a crash mid-write never leaves a
    half-written file (e.g. a truncated CLAUDE.md/AGENTS.md that would wedge the next lane start).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        final_mode = path.stat().st_mode & 0o777
    except OSError:
        final_mode = 0o644
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        tmp.chmod(final_mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def command_string(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def user_config_env_value(name: str, config_env: Path) -> str:
    """Read one simple NAME=value entry from an installed env file without sourcing shell."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name or "")):
        return ""
    try:
        lines = config_env.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{name}="
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        for token in tokens:
            if token.startswith(prefix):
                return token.split("=", 1)[1].strip()
    return ""


def resolve_env(name: str, default: str = "") -> str:
    """Read env var `name`, preferring its TAUTLINE_ alias over the MINERVIT_ name.

    Given a full MINERVIT_-prefixed name, the TAUTLINE_-prefixed variant wins when
    set; otherwise the given name is used. Non-MINERVIT_ names are read directly.
    """
    if name.startswith("MINERVIT_"):
        alias = "TAUTLINE_" + name[len("MINERVIT_"):]
        value = os.environ.get(alias)
        if value is not None and value != "":
            return value
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def env_value_with_user_config_fallback(name: str, config_env: Path, secrets_env: Path) -> str:
    return (
        resolve_env(name).strip()
        or user_config_env_value(name, config_env).strip()
        or user_config_env_value(name, secrets_env).strip()
    )
