"""Pure stdlib utility helpers for the Minervit methodology CLI."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
import tempfile
import urllib.parse
from collections.abc import Mapping
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


def resolve_env(name: str, default: str = "", environ: Mapping[str, str] | None = None) -> str:
    """Read env var `name`, preferring its TAUTLINE_ alias over the MINERVIT_ name.

    Given a full MINERVIT_-prefixed name, the TAUTLINE_-prefixed variant wins when
    set; otherwise the given name is used. Non-MINERVIT_ names are read directly.

    `environ` reads a caller-supplied mapping instead of the process environment: a child env being
    assembled for exec, or a base_env injected by a test. A copy of os.environ is still the
    operator's environment, so it gets the same alias preference -- otherwise every setting read out
    of a child env dict is a place the rebrand silently did not reach.

    A value that is blank once stripped counts as unset, for the alias as much as for the name. A
    stale `TAUTLINE_X=` left in a shell must not blank out a working MINERVIT_X.
    """
    source = os.environ if environ is None else environ
    if name.startswith("MINERVIT_"):
        alias = "TAUTLINE_" + name[len("MINERVIT_"):]
        value = source.get(alias)
        if value is not None and value.strip() != "":
            return value
        legacy = source.get(name)
        if legacy is not None and legacy.strip() != "":
            # Falling back to the legacy MINERVIT_ name: start the deprecation clock. Warn once per
            # name, and only for a real process-env read (environ is None) so internal child-env
            # assembly and test-injected mappings stay silent.
            if environ is None:
                _warn_minervit_env_deprecation(name, alias)
            return legacy
        return default
    value = source.get(name)
    if value is not None and value.strip() != "":
        return value
    return default


# --- Compat-sunset deprecation warnings (shared renderer core) --------------------------------
#
# ONE process-wide emitted-set and ONE suppression decision, shared by resolve_env's `env`-family
# warning below and bin/tautline's sunset_warning() for the `cli`/`markers`/`slug` families (util
# cannot import bin, so bin delegates here). Both layers dedup against the SAME state, so a concrete
# legacy surface warns at most once per process across the shell launcher, bin, and util. Every
# piece of this block is removed with the MINERVIT_ family at METH-FU-TAUTLINE-FALLBACK-REMOVAL.
_SUNSET_EMITTED: set[tuple[str, str]] = set()
_SUNSET_SUPPRESSED: bool | None = None
_SUNSET_SEEDED = False

# The suppression knob (both spellings) and the shell->Python once-only handoff are DIRECT-read
# here, never through resolve_env: routing them through resolve_env would recurse into the MINERVIT_
# warner they exist to silence/dedup. They are declared EXEMPT in tests/test_env_reads_use_resolver.
SUNSET_SUPPRESS_ENV = "TAUTLINE_SUPPRESS_SUNSET_WARNINGS"
SUNSET_SUPPRESS_LEGACY_ENV = "MINERVIT_SUPPRESS_SUNSET_WARNINGS"
SUNSET_SHELL_WARNED_ENV = "TAUTLINE_SUNSET_SHELL_WARNED"


def _reset_sunset_state() -> None:
    """Test hook: clear the process-wide dedup set + the memoized suppression/seed flags so a
    fixture that monkeypatches the environment gets a fresh decision (suppression and the shell
    handoff are read-once/cached, and would otherwise leak across tests)."""
    global _SUNSET_SUPPRESSED, _SUNSET_SEEDED
    _SUNSET_EMITTED.clear()
    _SUNSET_SUPPRESSED = None
    _SUNSET_SEEDED = False


def _sunset_line(legacy: str, replacement: str) -> str:
    """The one fixed message shape, reused by the shell launcher echo verbatim."""
    return (
        f"deprecation_warning: {legacy} is deprecated and will be removed in 1.0; "
        f"use {replacement}"
    )


def _sunset_truthy(value: str | None) -> bool:
    return bool(value) and value.strip() not in ("", "0")


def is_hook_invocation(argv: list[str]) -> bool:
    """A hook-shaped invocation, detected from argv (not parsed args, because warnings can fire
    during bootstrap before argparse runs): a `--hook` flag anywhere, or a first non-flag verb
    ending in `-hook`. Hook processes must never inject stderr noise into a Claude session."""
    if "--hook" in argv:
        return True
    for tok in argv:
        if not tok.startswith("-"):
            return tok.endswith("-hook")
    return False


def _sunset_suppress_value() -> str | None:
    """The effective suppression value under TAUTLINE-first-nonblank-else-legacy precedence, to
    match resolve_env's alias model and the shell launcher's `${TAUTLINE:-${MINERVIT:-}}` form: the
    TAUTLINE_ spelling wins only when set and non-blank (after strip), otherwise the MINERVIT_
    spelling. A blank/whitespace-only TAUTLINE_ value is treated as unset so it falls through, so
    all three layers (shell, util, bin fallback) agree on a self-contradictory config."""
    taut = os.environ.get(SUNSET_SUPPRESS_ENV)
    if taut is not None and taut.strip() != "":
        return taut
    return os.environ.get(SUNSET_SUPPRESS_LEGACY_ENV)


def _sunset_suppressed() -> bool:
    """Whether sunset warnings are silenced for this process, read ONCE and memoized. Suppressed
    when the effective (TAUTLINE-first) suppression value is truthy, or by hook context."""
    global _SUNSET_SUPPRESSED
    if _SUNSET_SUPPRESSED is None:
        _SUNSET_SUPPRESSED = (
            _sunset_truthy(_sunset_suppress_value())
            or is_hook_invocation(sys.argv[1:])
        )
    return _SUNSET_SUPPRESSED


def parse_sunset_handoff(raw: str) -> list[tuple[str, str]]:
    """Decode the shell->Python once-only handoff: comma-joined `pct(family):pct(legacy)` tokens,
    each component URL-quoted so a pathological legacy name carrying `,`/`:`/newline round-trips.
    Malformed tokens are skipped, never raised."""
    pairs: list[tuple[str, str]] = []
    for token in raw.split(","):
        if not token:
            continue
        fam_enc, sep, leg_enc = token.partition(":")
        if not sep:
            continue
        pairs.append((urllib.parse.unquote(fam_enc), urllib.parse.unquote(leg_enc)))
    return pairs


def _seed_sunset_from_shell(environ: Mapping[str, str] | None = None) -> None:
    """Seed the emitted-set with the (family, legacy) surfaces the shell launcher already warned,
    then strip the handoff env so a child re-exec cannot re-seed. Idempotent (once per process);
    whichever of bin/util runs first seeds the shared set and the other is a no-op."""
    global _SUNSET_SEEDED
    if _SUNSET_SEEDED:
        return
    _SUNSET_SEEDED = True
    source = os.environ if environ is None else environ
    raw = source.get(SUNSET_SHELL_WARNED_ENV)
    if raw:
        for pair in parse_sunset_handoff(raw):
            _SUNSET_EMITTED.add(pair)
    if environ is None:
        os.environ.pop(SUNSET_SHELL_WARNED_ENV, None)


def _sunset_warning(family: str, legacy: str, replacement: str) -> None:
    """Emit the fixed-shape sunset line once per (family, legacy) per process. Seeds from the shell
    handoff first, so a surface the shell launcher already warned stays silent here."""
    _seed_sunset_from_shell()
    if _sunset_suppressed():
        return
    key = (family, legacy)
    if key in _SUNSET_EMITTED:
        return
    _SUNSET_EMITTED.add(key)
    print(_sunset_line(legacy, replacement), file=sys.stderr)


def _warn_minervit_env_deprecation(name: str, alias: str) -> None:
    """Env-family sunset warning (deminervit 2A, unified onto the shared renderer). The MINERVIT_
    -> TAUTLINE_ replacement is pure string slicing, so computed/webhook-style names warn correctly
    and each distinct name dedups on its own ("env", name) key."""
    _sunset_warning("env", name, alias)


def env_value_with_user_config_fallback(name: str, config_env: Path, secrets_env: Path) -> str:
    return (
        resolve_env(name).strip()
        or user_config_env_value(name, config_env).strip()
        or user_config_env_value(name, secrets_env).strip()
    )


def child_env(**overrides: str) -> dict[str, str]:
    """A copy of the process environment with `overrides` applied, for a subprocess.

    Lives here rather than in each caller so modules that need a child env do not have to name the
    process environment themselves. A module that names it without also reading through
    `resolve_env` is precisely the shape the env-reads guard exists to flag -- it is one edit away
    from an unaliased settings read nobody notices.
    """
    env = dict(os.environ)
    env.update(overrides)
    return env
