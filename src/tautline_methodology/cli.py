"""Minervit AI Delivery Methodology CLI."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import posixpath
import re
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SCHEMA = REPO_ROOT / "methodology" / "adapter-schema.json"
PUBLIC_ADAPTER_SCHEMA_URL = (
    "https://raw.githubusercontent.com/tautlines/tautline/"
    "main/methodology/adapter-schema.json"
)
VERSION_FILE = REPO_ROOT / "VERSION"
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
RELEASE_UPDATE_DELIVERY_FILE = REPO_ROOT / "docs" / "releases" / "release-update-delivery.json"
RELEASE_UPDATE_DELIVERY_SCHEMA = "minervit-release-update-delivery/v1"
METHODOLOGY_REPO_SLUG = "tautlines/tautline-dev"
# Pre-rebrand slug; unconverted machines/adapters still carry it (removal: METH-FU-TAUTLINE-
# FALLBACK-REMOVAL).
LEGACY_METHODOLOGY_REPO_SLUGS = ("minervit/minervit-ai-delivery-methodology",)
METHODOLOGY_MAIN_COMMIT_OVERRIDE_ENV = "MINERVIT_METHODOLOGY_ALLOW_MAIN_COMMIT"
USER_CONFIG_ENV = Path.home() / ".config" / "tautline" / "tautline.env"
USER_SECRETS_ENV = Path.home() / ".config" / "tautline" / "secrets.zsh"
# Pre-rebrand config surfaces; still written as compatibility mirrors and read as fallbacks so
# pre-0.9.2 launchers/hooks keep resolving (removal: METH-FU-TAUTLINE-FALLBACK-REMOVAL).
LEGACY_USER_CONFIG_ENV = Path.home() / ".config" / "minervit" / "methodology.env"
LEGACY_USER_SECRETS_ENV = Path.home() / ".config" / "minervit" / "secrets.zsh"


def resolve_user_config_env() -> Path:
    """The effective config env file: the tautline path once it exists, else the legacy path."""
    if USER_CONFIG_ENV.is_file():
        return USER_CONFIG_ENV
    if LEGACY_USER_CONFIG_ENV.is_file():
        sunset_warning("markers", str(LEGACY_USER_CONFIG_ENV), str(USER_CONFIG_ENV))
        return LEGACY_USER_CONFIG_ENV
    return USER_CONFIG_ENV


USER_BIN_DIR = Path.home() / ".local" / "bin"
MANAGED_USER_CONFIG_ENV_KEYS = {
    "MINERVIT_METHODOLOGY_REPO",
    "MINERVIT_CLAUDE_AUTOCOMPACT_PCT",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    "MINERVIT_METHODOLOGY_UPDATE_POLICY",
    "MINERVIT_METHODOLOGY_UPDATE_PINS",
    # Snapshot-store keys: both alias spellings are managed so install-cli owns (and rewrites)
    # each one. A preserved stale MINERVIT_ export could otherwise shadow the fresh TAUTLINE_
    # alias that resolve_env prefers, pointing a converted machine at a dead store or checkout.
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_CLAUDE_AUTOCOMPACT_PCT",
    # Compat-sunset fresh-install-silent (R3 amendment b): install-cli dual-writes the TAUTLINE_
    # twins of the update-policy/pins knobs so a freshly generated config never warns on itself
    # when the launcher/Python resolve them through resolve_env. Both spellings are managed so
    # install-cli owns (rewrites) each and never double-preserves the twin as a user export.
    "TAUTLINE_METHODOLOGY_UPDATE_POLICY",
    "TAUTLINE_METHODOLOGY_UPDATE_PINS",
    "PATH",
}
GENERATED_HEADER_TEMPLATE = "<!-- GENERATED -->\n"
# RuntimeTarget descriptors (prod-extensibility-3): the single place that maps a runtime/agent kind
# to its generated instruction file, replacing scattered hardcoded {CLAUDE.md, AGENTS.md}
# assumptions. Adding a runtime target is a one-line addition here (the render_adapter `agent` arg
# still selects per-runtime content; that content split is the deeper provider-interface work).
RUNTIME_TARGETS = [
    {"agent": "Claude", "outputFile": "CLAUDE.md", "runtime": "claude-code"},
    {"agent": "Codex", "outputFile": "AGENTS.md", "runtime": "codex"},
]
GENERATED_MARKDOWN_FILES = {target["outputFile"] for target in RUNTIME_TARGETS}
CLI_NAME = "tautline"
LEGACY_CLI_NAME = "minervit-methodology"
# Compat-sunset (roadmap #16, chokepoint 2): the legacy CLI-name invocation marker. argv0 dies at
# both exec hops (the checkout shim's execv sets a canonical argv0; the wheel wrapper resets
# sys.argv[0] before runpy), so bin/minervit-methodology and the generated wheel wrapper set this
# process-private env marker pre-exec/pre-runpy; main() consumes it (warn once, then strip) with
# argv0 basename as a residual fallback. Direct-read, EXEMPT in the env-read guard. Removed with the
# MINERVIT_ family at METH-FU-TAUTLINE-FALLBACK-REMOVAL.
LEGACY_LAUNCHER_INVOKED_ENV = "TAUTLINE_LEGACY_LAUNCHER_INVOKED"
# The compat-sunset suppression knob (both spellings honored) and the collision-safe shell->Python
# once-only handoff. All three are DIRECT-read at renderer bootstrap (in util.py, never resolve_env,
# which would recurse into the MINERVIT_ warner they exist to silence/dedup) and EXEMPT in the
# env-read guard. The util-side reads are canonical; the constants here declare them for the guard's
# audit and back bin's standalone fallback.
SUPPRESS_SUNSET_WARNINGS_ENV = "TAUTLINE_SUPPRESS_SUNSET_WARNINGS"
SUPPRESS_SUNSET_WARNINGS_LEGACY_ENV = "MINERVIT_SUPPRESS_SUNSET_WARNINGS"
LANE_ADAPTER_FILE = ".tautline.json"
LEGACY_LANE_ADAPTER_FILE = ".minervit-ai-delivery.json"
REPO_LOCAL_ADAPTER_FILE = ".tautline/adapter.json"
LEGACY_REPO_LOCAL_ADAPTER_FILE = ".minervit/adapter.json"
FRAMEWORK_PIN_FILE = ".tautline/pin.json"
# Legacy pin location, read as a fallback and migrated on read for one deprecation window. Both are
# `str`, not `list[str]`. Removed at
# METH-FU-TAUTLINE-FALLBACK-REMOVAL, when every lane is on the tautline path at once.
LEGACY_FRAMEWORK_PIN_FILE = ".minervit/pin.json"
PUBLIC_CONTRACT_MANIFEST = REPO_ROOT / "methodology" / "public-contract-manifest.json"
PUBLIC_CONTRACT_MANIFEST_SCHEMA = "minervit-public-contract-manifest/v1"
PUBLIC_REFERENCE_ADAPTER_SLUG = "example-" + "saas"
PUBLIC_RELEASE_ALLOWED_SOURCE_ADAPTERS = {f"{PUBLIC_REFERENCE_ADAPTER_SLUG}.json"}
PUBLIC_RELEASE_PRIVATE_TERMS_ENV = "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS"
PUBLIC_RELEASE_EXPORT_MARKER = ".minervit-public-release-export.json"
PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA = "minervit-public-release-export/v1"
PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS = {"000000000000", "111111111111", "123456789012"}
PUBLIC_RELEASE_MAX_ISSUES_PER_RULE = 25
RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH = "docs/releases/release-update-delivery.json"
PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES = (
    # The framework's own self-adapter files are maintainer-lane config that
    # references private planning conventions; the self-adapter gates skip in
    # export trees, so the public export does not need them. The export marker
    # (.minervit-public-release-export.json) matches neither prefix:
    # ".minervit/" requires the slash, and the marker filename does not start
    # with ".minervit-ai-delivery.json".
    # The public repository is a downstream mirror: `release-tail` overlays the
    # export tree onto the mirror's current HEAD and fast-forwards it (never a
    # force-push, never a history rewrite). Dependabot PRs opened there can
    # never merge and always fail the release-change contract, so dependency
    # intake stays in the private repo.
    # Local agent-session state (worktrees of other branches live under
    # .claude/worktrees): never tracked, never shipped. Without this prefix,
    # untracked session worktrees make the export's dirty-state gate refuse on
    # exactly the workstations that ran agent sessions -- release validation
    # must not be session-dependent. Mirrors the boundary scan's IGNORED_PARTS.
    ".claude/",
    ".github/dependabot.yml",
    ".minervit-ai-delivery.json",
    ".minervit/",
    ".tautline.json",
    ".tautline/",
    "docs/backlog/",
    "docs/productization/",
    # Read-only process history (old plans, review ledgers, RCAs) archived by the 2026-08-28
    # process-bankruptcy demolition. Same reasoning as docs/superpowers/ below, whose content
    # moved here: never shipped to an adopter, so it must not become shippable by moving.
    "docs/archive/",
    # Where `tautline slim` re-archived that history (plus the repo's own retired 1.x
    # self-adapter and displaced git hooks) when the framework repo migrated itself to the lean
    # profile. Same never-shipped rationale, new root.
    "docs/archive-prebankruptcy/",
    # The release-update delivery ledger is an internal ops record of who was
    # notified about which release, and when. The rest of docs/releases/ is
    # public release material and still ships. Because the export tree cannot
    # carry the ledger, the release-update gate in public_release_issues() is
    # re-rooted to the source repository via release_update_root. NOTE: being
    # export-excluded ("don't ship it") is independent of being dirty-state-
    # excluded ("don't gate the export on its working-tree state") — see
    # public_release_dirty_state_path_included(), which deliberately does NOT
    # reuse this tuple for the ledger path.
    RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH,
    "docs/superpowers/",
    # Internal cross-machine campaign state: names workstations, local worktrees,
    # and local run counts. The carve TOOLING beside it (analyze/apply/model/
    # plan_core) is referenced by cli.py and by shipped release migrations, so it
    # ships; only this baton does not. Excluding the directory would break the
    # tooling, which is why this is a single-file prefix.
    "tools/carve/HANDOFF.md",
    # The public-boundary scan is a PRIVATE-REPO guard: its whole job is to hold the
    # denylist of identifiers that must not reach the export. It therefore cannot ship in
    # the export without publishing exactly what it exists to withhold. Three review
    # rounds were spent trying to keep the terms in a shipped file -- splitting literals
    # (rejoinable), then unsalted digests (dictionary-recoverable), then configuration
    # lookup (which silently disabled the guard). The terms are not the problem; shipping
    # the file is. Excluding it keeps the real regex working where it matters, in the
    # repository the export is produced from.
    "tests/test_public_boundary_scan.py",
)
PUBLIC_RELEASE_EXPORT_ALLOWED_PRODUCT_DOCS = (
    "docs/product/positioning.md",
    "docs/product/support-sla-model.md",
)
PUBLIC_RELEASE_PRIVATE_ADAPTER_PATH_RE = (
    r"adapters/projects/(?!"
    + re.escape(f"{PUBLIC_REFERENCE_ADAPTER_SLUG}.json")
    + r"\b)(?!\.)(?!\.validate-)(?!\.bootstrap-legacy-allowlist\.json\b)[A-Za-z0-9_.-]+\.json"
)
FRAMEWORK_CHANNELS = {"stable", "experimental", "methodology-dev"}
CLIENT_FRAMEWORK_CHANNELS = {"stable", "experimental"}
FRAMEWORK_CHANNEL_BRANCHES = {"stable": "main", "experimental": "experimental"}
FRAMEWORK_UPDATE_POLICIES = {"manual", "patch-auto", "minor-at-boundary"}
FRAMEWORK_MIGRATION_POLICIES = {"dry-run", "auto-apply-safe", "manual-only"}
DEFAULT_FRAMEWORK_PIN = {
    "channel": "stable",
    "version": "",
    "updatePolicy": "manual",
    "migrationPolicy": "dry-run",
}
# Opt-out knob for the display-only update probe (framework_update_probe). resolve_env prefers the
# TAUTLINE_ alias over this MINERVIT_ name, exactly like METHODOLOGY_SYNC_FRESHNESS_ENV; a falsey
# value in EITHER spelling stands the probe down. Unset => probe enabled.
METHODOLOGY_UPDATE_PROBE_ENV = "MINERVIT_METHODOLOGY_UPDATE_PROBE"
# Discovery cache for the update probe: a NEW disposable artifact, deliberately NOT under the
# lock-bearing ~/.cache/minervit/ root, so no dual-read is needed. Relative to $HOME.
METHODOLOGY_UPDATE_PROBE_CACHE_REL = ".cache/tautline/update-probe.json"
# Values (case-insensitive) that DISABLE the probe when set in either knob spelling.
METHODOLOGY_UPDATE_PROBE_OFF_VALUES = frozenset({"0", "off", "false", "no", "disable", "disabled"})
# Bounded subprocess timeouts: a single 5s ls-remote hard-bounds launch latency; the deliberate
# methodology-status fetch (allow_fetch=True only) is capped at 30s.
METHODOLOGY_UPDATE_PROBE_LS_REMOTE_TIMEOUT = 5
METHODOLOGY_UPDATE_PROBE_FETCH_TIMEOUT = 30
# Installed-package (pip/pipx) runtimes have no git checkout to ls-remote, so the update probe
# discovers the available release from PyPI's JSON API instead: one anonymous HTTPS GET, a 3s
# bound, a 24h cache (keyed by package name in the SAME cache file), fail-open. NO git subprocess
# ever runs in package mode. The URL is the stable unauthenticated read documented in
# setup-runtime.md.
METHODOLOGY_UPDATE_PROBE_PYPI_URL = "https://pypi.org/pypi/tautline/json"
METHODOLOGY_UPDATE_PROBE_PYPI_TIMEOUT = 3
METHODOLOGY_UPDATE_PROBE_PACKAGE_TTL = 24 * 60 * 60  # 24h; fresh enough for a user-persona prompt
# A negative-cache TTL for a FAILED PyPI probe (offline/timeout/unreachable/bad response): without
# it, an offline wheel would re-attempt the 3s GET on EVERY session-start command. 1h is long
# enough to stop per-launch retries yet short enough that a recovered PyPI is seen within the hour
# -- deliberately NOT the 24h success TTL, which would hide a recovered PyPI for a day.
METHODOLOGY_UPDATE_PROBE_PACKAGE_FAIL_TTL = 60 * 60  # 1h
METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY = "pypi:tautline"


_ADAPTER_MODULE = None


def adapter_module():
    global _ADAPTER_MODULE
    if _ADAPTER_MODULE is None:
        try:
            from tautline_methodology import adapter
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "adapter helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _ADAPTER_MODULE = adapter
    return _ADAPTER_MODULE


_RELEASES_MODULE = None


def releases_module():
    global _RELEASES_MODULE
    if _RELEASES_MODULE is None:
        try:
            from tautline_methodology import releases
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "release metadata helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _RELEASES_MODULE = releases
    return _RELEASES_MODULE


_UTIL_MODULE = None


def util_module():
    global _UTIL_MODULE
    if _UTIL_MODULE is None:
        try:
            from tautline_methodology import util
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "utility helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _UTIL_MODULE = util
    return _UTIL_MODULE


_GITUTIL_MODULE = None


def gitutil_module():
    global _GITUTIL_MODULE
    if _GITUTIL_MODULE is None:
        try:
            from tautline_methodology import gitutil
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "git helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _GITUTIL_MODULE = gitutil
    return _GITUTIL_MODULE


_PATHS_MODULE = None


def paths_module():
    global _PATHS_MODULE
    if _PATHS_MODULE is None:
        try:
            from tautline_methodology import paths
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "path helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _PATHS_MODULE = paths
    return _PATHS_MODULE


_PROFILES_MODULE = None


def profiles_module():
    global _PROFILES_MODULE
    if _PROFILES_MODULE is None:
        try:
            from tautline_methodology import profiles
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "work profile helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _PROFILES_MODULE = profiles
    return _PROFILES_MODULE


_GHUTIL_MODULE = None


def ghutil_module():
    global _GHUTIL_MODULE
    if _GHUTIL_MODULE is None:
        try:
            from tautline_methodology import ghutil
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "GitHub provider helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _GHUTIL_MODULE = ghutil
    return _GHUTIL_MODULE


# --- Execution root vs canonical checkout -------------------------------------------------
# REPO_ROOT answers "where am I executing from". canonical_methodology_repo() answers "which
# mutable git checkout does sync manage". They are the same directory on a dev checkout and on
# every unconverted machine; they diverge once a machine executes an immutable snapshot from the
# snapshot store, at which point every git WRITE must target the canonical checkout while every
# self-report must describe the snapshot actually running.
SNAPSHOT_MANIFEST_NAME = ".snapshot-meta.json"
SNAPSHOT_MANIFEST_SCHEMA = "tautline-snapshot/v1"
METHODOLOGY_CANONICAL_REPO_ENV = "MINERVIT_METHODOLOGY_CANONICAL_REPO"
METHODOLOGY_SNAPSHOT_STORE_ENV = "MINERVIT_METHODOLOGY_SNAPSHOT_STORE"
# The documented rollback lever (docs/reference/operations/release-engineering.md#rollback): take a
# machine back to executing the canonical checkout without uninstalling anything and without
# touching the store. It is reached for PRECISELY when the store has published a bad snapshot, so
# it has to beat EVERY path that would execute one -- the shim's exec ladder, the launcher, and the
# trust-gated advance below. A lever that only half-works is worse than none: the first upstream
# advance would otherwise re-exec the operator straight back into the snapshot they are escaping.
METHODOLOGY_DISABLE_SNAPSHOT_EXEC_ENV = "MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC"
# Written (never read) by this process: the post-update re-exec exports the tree it adopted so the
# launcher shim -- and every hook subprocess the re-exec'd session spawns -- executes that one tree
# for the whole session instead of independently re-resolving `store/current` mid-flight.
METHODOLOGY_EXEC_ROOT_ENV = "MINERVIT_METHODOLOGY_EXEC_ROOT"
# Machine-scoped maintainer-mode key. Despite the _ENV suffix convention it shares with its
# neighbours, this key is deliberately NOT an environment read: it lives ONLY in the installed
# config env file and is read ONLY from that file (see maintainer_mode_config_value).
METHODOLOGY_MAINTAINER_MODE_ENV = "MINERVIT_METHODOLOGY_MAINTAINER_MODE"


def snapshot_manifest() -> dict | None:
    """Manifest of the immutable snapshot we execute from, or None on a git checkout.

    Deliberately tolerant about extra keys and strict about the two that carry meaning: an
    unreadable, non-JSON, foreign-schema, or commit-less manifest reads exactly like "not a
    snapshot", so a corrupt file degrades to the pre-snapshot behavior instead of raising.
    """
    try:
        raw = (REPO_ROOT / SNAPSHOT_MANIFEST_NAME).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_MANIFEST_SCHEMA:
        return None
    commit = data.get("commit")
    if not isinstance(commit, str) or len(commit) < 12:
        return None
    return data


def running_from_snapshot() -> bool:
    return snapshot_manifest() is not None


# Both package update channels, spoken together everywhere package mode explains itself:
# pipx is the documented primary install, plain pip covers virtualenv installs. One string so
# the version hint, the sync skip surface, and the update-repin refusal can never drift apart.
PACKAGE_INSTALL_UPDATE_HINT = (
    "pipx upgrade tautline (pipx installs) / pip install -U tautline (virtualenv installs)"
)


def running_from_installed_package() -> bool:
    """True when THIS process executes a pip/pipx-installed wheel (plan Task 6, the ONE predicate).

    Keyed on the build-time manifest's `installKind: "package"` stamp
    (registry_package_snapshot_manifest), NEVER on generic snapshot detection: a snapshot-store
    machine is also a manifest-stamped export, but it updates via repin and must keep
    canonical-first behavior byte-identically. Package mode is different because pip is the only
    channel that updates the RUNNING code and data -- so sync/repin stand down (PP-R1-P1-1) and
    data-root resolution pins to the exec root's embedded tree (PP-R3-P1-1): reads and writes
    stand down together, one predicate, one rationale.
    """
    manifest = snapshot_manifest()
    return bool(manifest) and manifest.get("installKind") == "package"


def running_methodology_commit(short: bool = False) -> str:
    """The commit of the code THIS process is running.

    Snapshots are exported trees with no .git, so `rev-parse` there returns run_git's
    "unavailable" sentinel; the manifest is the only truthful source. Falls back to git on a
    real checkout.

    The short form is ALWAYS a fixed 12-char prefix of the full sha, NEVER git's
    `rev-parse --short` abbreviation. git's abbreviation length is repo-state-dependent (it grows
    with the object count) and a snapshot has no .git to ask at all, so deriving it from git would
    give one commit two names depending on WHERE we execute. That value is not merely printed:
    render_project_config embeds it as `_generated.methodologyCommit` and adapter_drift
    byte-compares the rendered adapter against the file on disk. A snapshot lane and a
    canonical-checkout lane at the SAME methodology commit would then render different bytes, each
    re-render putting the other lane back into drift -- and drift is a gate (methodology-status
    --fail-on-drift, lane-start), so the two lanes would ping-pong into repair sessions forever
    with zero methodology change. run_git's "unavailable" sentinel is 11 chars and survives the
    slice unchanged.
    """
    manifest = snapshot_manifest()
    commit = str(manifest["commit"]) if manifest else run_git(REPO_ROOT, ["rev-parse", "HEAD"])
    return commit[:12] if short else commit


def _valid_methodology_repo(candidate: Path) -> bool:
    """A canonical candidate is the MUTABLE checkout sync manages: it must be a real git
    checkout. A bin/tautline-only tree (a snapshot, a copied CLI) must never be accepted --
    fetch/merge/archive/repair run against the winner."""
    return (
        candidate.is_dir()
        and (candidate / ".git").exists()  # a file in worktrees, a directory in clones
        and (candidate / "bin" / CLI_NAME).is_file()
    )


def _managed_config_value(name: str) -> str:
    """Resolve a managed key: live env first, then the installed config env file.

    resolve_env already prefers the TAUTLINE_ alias over the MINERVIT_ name for the live
    environment; the file read mirrors that precedence explicitly, because install-cli
    dual-writes both spellings and a preserved stale MINERVIT_ export must never win over the
    fresh alias. Takes the full MINERVIT_-prefixed name, like every other managed-key reader.
    """
    live = util_module().resolve_env(name).strip()
    if live:
        return live
    spellings = [name]
    if name.startswith("MINERVIT_"):
        spellings.insert(0, "TAUTLINE_" + name[len("MINERVIT_"):])
    for spelled in spellings:
        value = user_config_env_value(spelled).strip()
        if value:
            return value
    return ""


def _exec_root_is_git_checkout() -> bool:
    """Is the tree we execute from a git checkout (rather than a snapshot / copied-out CLI)?

    Deliberately WEAKER than _valid_methodology_repo: that predicate validates a CONFIGURED
    candidate ("is this a plausible methodology checkout to point sync at?") and demands a
    bin/<cli> file. This one answers "am I self-managing?", where the only thing that matters is
    whether there is a git checkout here to manage. Requiring bin/<cli> here would be a trap: a
    git tree that merely lacks that file would be declared non-self-managing and sync would go
    hunting for a configured repository elsewhere -- which is precisely how an early cut of this
    change pointed the update machinery at the operator's deployed runtime checkout.
    """
    return (REPO_ROOT / ".git").exists()  # a file in worktrees, a directory in clones


def _resolve_canonical_methodology_repo() -> Path:
    """Which mutable git checkout does sync manage?

    THE EXEC ROOT WINS WHENEVER IT IS ITSELF A CHECKOUT. If we are executing from a git checkout,
    that checkout is by definition the one sync manages -- which is exactly what every REPO_ROOT
    call site did before this migration, so the fallback preserves pre-migration behavior byte for
    byte. A configured canonical repo may only take over when the exec root has no `.git`, i.e.
    when we run an immutable snapshot (or a copied-out CLI) and sync has nothing local to manage.

    That gate is load-bearing, not defensive: every installed `~/.config/minervit/methodology.env`
    exports MINERVIT_METHODOLOGY_REPO naming the DEPLOYED runtime checkout. If a configured value
    could outrank a live checkout, then `tautline sync-methodology` run from a dev worktree would
    fetch/merge/`reset --hard` the deployed runtime instead of the worktree the operator is
    standing in -- and the test suite (which monkeypatches REPO_ROOT at fixture repos while the
    real config env is readable) would drive rescue/reset against the operator's live checkout.
    """
    if _exec_root_is_git_checkout():
        return REPO_ROOT
    candidates: list[str] = []
    for key in (METHODOLOGY_CANONICAL_REPO_ENV, "MINERVIT_METHODOLOGY_REPO"):
        value = _managed_config_value(key)
        if value:
            candidates.append(value)
    manifest = snapshot_manifest()
    if manifest and manifest.get("canonicalRepo"):
        candidates.append(str(manifest["canonicalRepo"]))
    for raw in candidates:
        candidate = Path(raw).expanduser().resolve(strict=False)
        if _valid_methodology_repo(candidate):
            return candidate
    return REPO_ROOT


_CANONICAL_METHODOLOGY_REPO: Path | None = None
_CANONICAL_METHODOLOGY_REPO_ANCHOR: Path | None = None


def canonical_methodology_repo() -> Path:
    """The mutable git checkout sync manages; REPO_ROOT when unset (dev and pre-cutover).

    Cached per process: this is consulted on every git write path, and a mid-process change of the
    answer would split a single sync across two repositories. The cache is keyed by the REPO_ROOT
    it was resolved against -- inert in production (REPO_ROOT is a module constant) but required
    under pytest, where one imported module is shared across suites that each point REPO_ROOT at
    their own fixture repo; an input-blind cache would hand one suite another suite's repository.
    """
    global _CANONICAL_METHODOLOGY_REPO, _CANONICAL_METHODOLOGY_REPO_ANCHOR
    if _CANONICAL_METHODOLOGY_REPO is not None and _CANONICAL_METHODOLOGY_REPO_ANCHOR == REPO_ROOT:
        return _CANONICAL_METHODOLOGY_REPO
    resolved = _resolve_canonical_methodology_repo()
    _CANONICAL_METHODOLOGY_REPO = resolved
    _CANONICAL_METHODOLOGY_REPO_ANCHOR = REPO_ROOT
    return resolved


def maintainer_mode_config_value() -> str:
    """The maintainer-mode key's value from the installed config env file, and ONLY from there.

    FILE-ONLY RESIDENCY IS LOAD-BEARING. This read deliberately bypasses _managed_config_value
    and the live environment: the archived monolith plan resolved the key live-env-first, so
    `maintainer-mode off` could strip the config file yet leave an inherited live-env key armed
    (its unresolved MM-R4-P1-1). With the installed config env file as the single source of
    truth, `off` is authoritative by construction -- it removes the only bits that can arm the
    machine. The key lives ONLY in that file, written and removed exclusively by the
    `maintainer-mode` verb; it is never emitted by render-adapters or any adapter surface, so it
    can never ride a committed file into a user repo.

    The TAUTLINE_ alias spelling is read first with blank falling through, mirroring
    _managed_config_value's file order without its live-env rung.
    """
    for spelled in _maintainer_mode_export_names():
        value = user_config_env_value(spelled).strip()
        if value:
            return value
    return ""


def _maintainer_mode_export_names() -> tuple[str, str]:
    """Both alias spellings of the mode key, TAUTLINE_ first -- the read order of
    maintainer_mode_config_value and the write order of the `maintainer-mode` verb."""
    return (
        "TAUTLINE_" + METHODOLOGY_MAINTAINER_MODE_ENV[len("MINERVIT_"):],
        METHODOLOGY_MAINTAINER_MODE_ENV,
    )


def maintainer_mode_configured() -> bool:
    """Is the maintainer-mode key set (to "1") in the installed config env file?

    Blank and "0" count as unset -- see maintainer_mode_config_value for why only the file
    (never the live environment) can configure the mode.
    """
    return maintainer_mode_config_value() == "1"


def maintainer_mode_armed() -> bool:
    """Configured AND there is a real git checkout for sync to manage.

    THE PREDICATE KEYS ON THE CANONICAL REPO, NOT THE BARE EXEC ROOT. With snapshot exec ON (a
    hard requirement of the maintainer setup), the generated launcher resolves $METHODOLOGY_CLI
    to <store>/current/bin/tautline, so the launcher-gate sync executes from an immutable
    snapshot where _exec_root_is_git_checkout() is False -- an exec-root-only predicate would
    never arm inside exactly the sessions the mode exists for. Because
    _resolve_canonical_methodology_repo returns REPO_ROOT whenever the exec root is itself a
    checkout, the canonical-repo predicate subsumes the exec-root case; on a snapshot or
    pip/package exec root with no configured canonical git checkout, the canonical repo falls
    back to a .git-less REPO_ROOT and the mode refuses to arm (nothing to stand down for).
    """
    if not maintainer_mode_configured():
        return False
    # .git is a file in worktrees, a directory in clones -- same shape as
    # _exec_root_is_git_checkout.
    return (canonical_methodology_repo() / ".git").exists()


def maintainer_mode_status_line() -> str:
    """The three-state maintainer_mode report line (methodology-status; sync's diagnostic).

    `off` / `on - ...` / `configured but not armed - ...`. The armed form names the managed
    checkout and its commit -- the same `<checkout> @ <commit>` contract as the per-launch
    banner, because with update gates off that checkout's HEAD IS the machine-wide runtime
    (heal republishes it into <store>/current on every launch). The configured-but-not-armed
    form is a diagnostic: the key is set but there is no git checkout to manage (a snapshot or
    package exec root with no configured canonical checkout), so every gate runs stock. The
    12-char slice matches running_methodology_commit(short=True), never `rev-parse --short`
    (whose length is repo-state-dependent).
    """
    if not maintainer_mode_configured():
        return "maintainer_mode: off"
    if not maintainer_mode_armed():
        return "maintainer_mode: configured but not armed - no git checkout to manage"
    canonical = canonical_methodology_repo()
    head = run_git(canonical, ["rev-parse", "HEAD"])[:12]
    return f"maintainer_mode: on - update gates off; running {canonical} @ {head}"


def maintainer_mode_banner_lines() -> list[str]:
    """The per-launch maintainer-mode banner: LOUD ON PURPOSE (the visual weight of
    warn_unpinned_launcher_window's `!!` style).

    With update gates standing down, committed dev-branch work becomes the machine-wide runtime
    via heal -- deliberate and operator-approved, but a foot-gun if forgotten. The unmissable
    per-launch banner naming exactly which checkout and commit the machine runs is the
    mitigation. The load-bearing `maintainer_mode: update gates off - running <checkout> @
    <commit>` line is deliberately unprefixed so it stays grep-able alongside the other
    machine-readable `key: value` report lines.
    """
    bar = "!" * 76
    canonical = canonical_methodology_repo()
    head = run_git(canonical, ["rev-parse", "HEAD"])[:12]
    return [
        bar,
        "!! MAINTAINER MODE -- every methodology update gate on this machine is STANDING",
        "!! DOWN: no fetch, no trust verification, no branch check, no rescue. Every",
        "!! launch republishes the canonical checkout's HEAD as the machine-wide runtime",
        "!! (snapshot heal), exactly as committed:",
        "!!",
        f"maintainer_mode: update gates off - running {canonical} @ {head}",
        "!!",
        f"!! Disable by removing {METHODOLOGY_MAINTAINER_MODE_ENV} from "
        f"{resolve_user_config_env()}",
        bar,
    ]


MAINTAINER_MODE_ARM_MARKER_SCHEMA = "tautline-maintainer-mode-arm/v1"


def maintainer_mode_arm_marker_path() -> Path:
    """Where "this machine was armed" is recorded, OUTSIDE the config env file.

    Deliberately not in the config env: the whole failure this detects is that file being
    rewritten by something other than the `maintainer-mode` verb. A witness kept in the same
    file the edit destroys witnesses nothing.
    """
    return methodology_state_dir() / "maintainer-mode-armed.json"


def read_maintainer_mode_arm_marker() -> dict | None:
    """The arm marker, or None when this machine has no usable one.

    Unreadable or corrupt state reads as None: garbage is not evidence of a disarm, and a notice
    that fires on a truncated JSON file is a notice operators learn to ignore.
    """
    try:
        data = json.loads(maintainer_mode_arm_marker_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != MAINTAINER_MODE_ARM_MARKER_SCHEMA:
        return None
    return data


def write_maintainer_mode_arm_marker(config_env: Path, observed: bool = False) -> Path | None:
    """Record that this machine is armed, naming the surface holding the key.

    `observed` distinguishes a backfill (see ensure_maintainer_mode_arm_marker) from a real
    arming: the timestamp of a backfill is when the framework first SAW the machine armed, not
    when the operator armed it, and the notice must not claim otherwise.

    Best-effort, exactly like record_installed_launcher: an unwritable state dir must never fail
    an arming. Losing the marker only costs the detection, never the standdown itself.
    """
    path = maintainer_mode_arm_marker_path()
    record = {
        "schema": MAINTAINER_MODE_ARM_MARKER_SCHEMA,
        "configEnv": str(config_env),
        "armedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "observed" if observed else "verb",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        util_module().write_text_atomic(path, json.dumps(record, indent=2) + "\n")
    except OSError:
        return None
    return path


def ensure_maintainer_mode_arm_marker() -> None:
    """Backfill the witness on a machine that was armed before this control existed.

    WITHOUT THIS THE CONTROL PROTECTS NOBODY WHO ALREADY NEEDS IT. The marker is written by
    `maintainer-mode on`, so a fleet that armed months ago would carry no witness and a later
    silent disarm would go unreported -- on exactly the machines the RCA is about. Any launch
    that observes the mode ARMED with no marker records one, flagged `observed` so the notice
    never claims a first-arm time it cannot know. Best-effort and idempotent.

    ARMED, not merely configured (Codex R2 P2). `configured but not armed` means the key is set
    but there is no checkout to manage: every gate runs stock and no standdown ever existed.
    Backfilling there would arm a witness to nothing, and a later config cleanup would then report
    an unauthorized loss of a standdown that never stood down -- a permanent false alarm, which is
    precisely the "notice operators learn to ignore" failure this control is built to avoid.
    """
    if not maintainer_mode_armed():
        return
    if read_maintainer_mode_arm_marker() is not None:
        return
    write_maintainer_mode_arm_marker(resolve_user_config_env(), observed=True)


def maintainer_mode_standdown_loss_lines() -> list[str]:
    """The loud unauthorized-disarm notice, or [] when there is nothing to report.

    RCA 2026-07-22 control 2. The incident: an armed machine, a config env rewritten by an
    unrelated remediation, the mode key gone, and not one surface said so -- so the next launch
    through a different entry point hit the non-release-branch refusal the standdown existed to
    prevent. Both remedies are named because both are legitimate: re-arm, or accept the disarm
    through the verb (which is also how the notice is silenced -- there is deliberately no
    "dismiss" that leaves the machine in the state that caused the incident).
    """
    marker = read_maintainer_mode_arm_marker()
    if marker is None or maintainer_mode_configured():
        return []
    config_env = str(marker.get("configEnv") or resolve_user_config_env())
    stamp = str(marker.get("armedAt") or "an earlier session")
    # A backfilled marker only knows when the framework first SAW the machine armed.
    armed_at = f"observed armed {stamp}" if marker.get("source") == "observed" else stamp
    bar = "!" * 76
    return [
        bar,
        "!! MAINTAINER MODE WAS DISARMED WITHOUT THE VERB -- this machine recorded an armed",
        "!! standdown, and the mode key is now absent from every config surface. Nothing but",
        f"!! `{CLI_NAME} maintainer-mode off` is supposed to remove it, so the config env was",
        "!! edited behind the mode's back and every update gate is live again.",
        "!!",
        f"maintainer_mode_standdown_lost: armed {armed_at}; key absent from {config_env}",
        "!!",
        f"!! Re-arm:            {CLI_NAME} maintainer-mode on",
        f"!! Accept the disarm: {CLI_NAME} maintainer-mode off",
        bar,
    ]


def product_dev_mode_status_path(root: Path) -> Path:
    """The per-checkout .ai-work/PRODUCT_DEV_MODE.json path, resolved (sandboxed under `root`)
    exactly like the latest-code baseline via configured_path."""
    return configured_path(root, DEFAULT_PRODUCT_DEV_MODE["statusFile"])


def _product_dev_mode_parse_expiry(value: object) -> "datetime | None":
    """Parse a stamped expiresAt into an aware UTC datetime, or None if unparseable.

    Mirrors latest_code_baseline_state's tolerant parse (accepts a trailing `Z` or an explicit
    offset). A naive stamp is treated as UTC. Any bad value returns None -> the mode reads
    inactive (fail-safe)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def product_dev_mode_state(root: Path) -> "dict | None":
    """The SINGLE metadata reader over the per-checkout .ai-work/PRODUCT_DEV_MODE.json.

    Returns the validated, unexpired state dict (carrying startedAt/expiresAt for callers that
    print remaining TTL) when the mode is armed, else None. Pure and fail-safe: a missing /
    unreadable / corrupt / non-dict / wrong-schema / on-false / missing-or-bad-expiresAt /
    expired file all read as None (inactive), so an edited or stale-but-valid file can never
    accidentally arm the mode. Activity is decided by the STAMPED expiresAt, never recomputed
    from a live TTL value, so a later config change cannot retroactively move an already-open
    session's boundary.

    Must NEVER be called from a code-safety path (guard_check / cut_release / the version-contract
    predicate) -- the safety invariant; the only production caller is product_dev_mode_command's
    status/banner surface.
    """
    try:
        path = product_dev_mode_status_path(root)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != PRODUCT_DEV_MODE_SCHEMA:
        return None
    if data.get("on") is not True:
        return None
    expires = _product_dev_mode_parse_expiry(data.get("expiresAt"))
    if expires is None:
        return None
    if datetime.now(timezone.utc) >= expires:
        return None
    return data


def product_dev_mode_active(root: Path) -> bool:
    """Boolean wrapper: the mode is active iff the shared reader returns a state dict."""
    return product_dev_mode_state(root) is not None


def methodology_snapshot_store_root() -> Path:
    value = _managed_config_value(METHODOLOGY_SNAPSHOT_STORE_ENV)
    if value:
        return Path(value).expanduser().resolve(strict=False)
    return Path.home() / ".local" / "share" / "minervit" / "tautline-releases"


def methodology_snapshot_exec_disabled() -> bool:
    """Has the operator taken the documented rollback lever?

    Checked wherever the store would be CONSULTED FOR EXECUTION -- which, on the Python side, means
    every caller of methodology_snapshot_store_enabled(): publishing a snapshot, swapping `current`,
    healing it, pinning a lane to it, and exporting an exec root are all steps of executing the
    store. The shell side (shim + launcher) enforces the same lever on its own exec ladders.
    """
    return _managed_config_value(METHODOLOGY_DISABLE_SNAPSHOT_EXEC_ENV) == "1"


def methodology_snapshot_store_enabled() -> bool:
    """Snapshot mode requires the EXPLICIT managed key (live env or the config env file), and
    yields to the disable lever and to the package standdown.

    A stray store directory left by a rehearsal or a failed install must never activate
    snapshot behavior before the documented release -> repin -> install-cli cutover, so
    directory existence is deliberately NOT part of this answer.

    The disable lever is folded in HERE, rather than at each call site, because "snapshot mode is
    on" is exactly the question every caller is asking, and the generated launcher already answers
    it this way (it blanks SNAPSHOT_STORE when the lever is set, so a disabled machine behaves
    precisely as if the store key had never been configured). Python must agree, or the two halves
    of one machine disagree about which tree it runs.

    The package standdown (PP-R1-P1-1 extension) is folded in here for the same reason: every
    caller is consulting the store for EXECUTION, and a pip/pipx-installed wheel never executes
    the store -- pip is the only channel that updates the code this process runs, so a leftover
    store key on an upgraded machine is dead config. Without this, every sync kept healing and
    republishing the leftover checkout into a store nothing executes. Keyed on
    running_from_installed_package() (installKind: "package"), never on generic snapshot
    detection: a snapshot-store machine is also a manifest-stamped export and must keep store
    behavior byte-identically. Checked LAST so machines without a store key never pay the
    manifest read behind the package predicate.
    """
    if methodology_snapshot_exec_disabled():
        return False
    if not _managed_config_value(METHODOLOGY_SNAPSHOT_STORE_ENV):
        return False
    return not running_from_installed_package()


def methodology_data_roots() -> list[Path]:
    """Roots to search for methodology DATA (source adapters, archives), canonical first.

    Shipped release content (methodology/, plugins/, docs/, VERSION, src/) is in the snapshot by
    construction, so reading it from the exec root is correct. DATA is different: a snapshot is an
    export of COMMITTED content, and the per-product source adapters that matter most are private
    -- they live in the canonical checkout's working tree (or a private adapter root) and are never
    committed to the public repo. Anchored on the exec root they would simply not exist, so the
    adapter reads "missing"/"untrusted" and every lane rendered from it fails.

    The exec root stays in the list as a FALLBACK, which is what makes this a no-op on every dev
    checkout and every pre-cutover machine (the two roots are then the same directory, and the list
    collapses to one entry).
    """
    if running_from_installed_package():
        # Package mode (PP-R3-P1-1): the wheel's embedded tree is the ONLY data root. pip is the
        # update channel for code AND data, and behavior must never depend on stale checkout
        # state the user forgot exists -- a leftover configured checkout would otherwise win
        # canonical-first resolution and feed this runtime data its own code never shipped.
        # Checkout and snapshot-store machines keep canonical-first below, byte-identically.
        return [REPO_ROOT]
    roots = [canonical_methodology_repo()]
    if REPO_ROOT not in roots:
        roots.append(REPO_ROOT)
    return roots


def require_dev_checkout(verb: str) -> None:
    """Refuse a maintainer verb whose exec root cannot answer git (D-cat).

    `cut-release`, the `public-release-*` family and the release-update delivery writer all read
    and write the exec root AS A GIT REPOSITORY: tag lists, dirty checks, history/remote trust
    scans, and a committed delivery ledger. A runtime snapshot is an immutable `git archive`
    export with no `.git`, so none of that exists there -- and the failure is SILENT, not loud:
    run_git degrades to the "unavailable" sentinel, so `cut-release` reports every tag as "(new)"
    and every tree as clean, and the export's history-trust scan finds nothing to object to. The
    operator gets a confident, wrong answer about a release boundary.

    Deliberately anchored on REPO_ROOT (the exec root), NOT on the canonical repo: these verbs are
    maintainer operations on the checkout the maintainer is standing in, and silently redirecting a
    release cut into some other repository would be worse than refusing. The refusal names that
    checkout so the operator can act on it.
    """
    if running_from_snapshot() or not _exec_root_is_git_checkout():
        raise SystemExit(
            f"{verb} must run from a methodology dev checkout, not a runtime snapshot; "
            f"cd {canonical_methodology_repo()} and run bin/tautline {verb}"
        )


# --- Per-lane journal of canonical-repo mutations -----------------------------------------
# Many lanes drive sync against ONE canonical checkout. When a lane later finds that checkout in
# an unexpected state, attribution is impossible without a durable record of which lane wrote
# what, and when. This is that record: append-only JSONL under the user's state dir, keyed by the
# existing instrumentation lane id.
METHODOLOGY_WRITE_JOURNAL_SCHEMA = "tautline-methodology-write/v1"
METHODOLOGY_WRITE_JOURNAL_MAX_BYTES = 5_000_000


def methodology_state_dir() -> Path:
    """Where cross-lane methodology state lives. May not exist yet: every writer mkdirs it."""
    return Path.home() / ".local" / "state" / "minervit"


def methodology_write_journal_path() -> Path:
    return methodology_state_dir() / "methodology-writes.jsonl"


def append_methodology_write_journal(
    command: str,
    old_head: str,
    new_head: str,
    outcome: str,
    detail: str = "",
    lane: Path | None = None,
) -> None:
    """Record one canonical-repo mutation attempt. Best-effort BY DESIGN.

    Forensics must never become a failure mode: an unwritable state dir, a full disk, or a
    lane-id salt that cannot be created has to leave sync working exactly as it did before the
    journal existed, so every error here is swallowed. The append is flock-serialized so
    concurrent lanes interleave whole lines instead of shredding each other's entries.
    """
    try:
        path = methodology_write_journal_path()
        # NEVER journal into a methodology tree. The journal lives under $HOME, and if $HOME sits
        # inside a methodology checkout the log becomes an untracked file in the very repository
        # whose `git status` the sync machinery reads as a CONTROL SIGNAL: a dirty tree routes the
        # next sync into the local-changes rescue branch and invalidates the post-advance re-exec
        # token (which requires a clean tree). The tool would then perpetually auto-rescue its own
        # logfile. Both roots are checked -- the canonical checkout for the reason above, and the
        # exec root because a snapshot is read-only by construction and the write would just fail.
        for root in (canonical_methodology_repo(), REPO_ROOT):
            if path_is_under(path, root):
                return
        entry: dict[str, object] = {
            "schema": METHODOLOGY_WRITE_JOURNAL_SCHEMA,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lane_id": instrumentation_lane_id(lane or Path.cwd()),
            "pid": os.getpid(),
            "command": command,
            "old_head": old_head,
            "new_head": new_head,
            "outcome": outcome,
            "detail": detail,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > METHODOLOGY_WRITE_JOURNAL_MAX_BYTES:
            # Single-generation rotation: the journal is a debugging aid, so bounding it at two
            # files is worth more than unbounded history on a machine that syncs all day.
            os.replace(path, path.with_suffix(".jsonl.1"))
        with path.open("a", encoding="utf-8") as fh, advisory_flock(fh):
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:
        pass


def load_release_migration_report(version: str) -> dict | None:
    # Standalone copies of this script (no sibling src/) must keep the 0.6.202
    # behavior for read paths like methodology-status and lane-start: a missing
    # module reads the same as a missing report.
    try:
        module = releases_module()
    except SystemExit:
        return None
    return module.load_release_migration_report(version)


def changelog_release_blocks(path: Path | None = None) -> list[dict[str, str]]:
    return releases_module().changelog_release_blocks(path)


def changelog_release_block(version: str) -> dict[str, str] | None:
    return releases_module().changelog_release_block(version)


def release_update_releases_module():
    module = releases_module()
    previous = (
        module.VERSION_FILE,
        module.RELEASE_UPDATE_DELIVERY_FILE,
        module.RELEASE_UPDATE_DELIVERY_SCHEMA,
    )
    module.VERSION_FILE = VERSION_FILE
    module.RELEASE_UPDATE_DELIVERY_FILE = RELEASE_UPDATE_DELIVERY_FILE
    module.RELEASE_UPDATE_DELIVERY_SCHEMA = RELEASE_UPDATE_DELIVERY_SCHEMA
    return module, previous


def release_update_call(name: str, *args, **kwargs):
    module, previous = release_update_releases_module()
    try:
        return getattr(module, name)(*args, **kwargs)
    finally:
        (
            module.VERSION_FILE,
            module.RELEASE_UPDATE_DELIVERY_FILE,
            module.RELEASE_UPDATE_DELIVERY_SCHEMA,
        ) = previous


_PUBLIC_RELEASE_MODULE = None


def public_release_module():
    global _PUBLIC_RELEASE_MODULE
    if _PUBLIC_RELEASE_MODULE is None:
        try:
            from tautline_methodology import public_release
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "public-release helpers require the framework checkout's src/tautline_methodology "
                "package; run this command from a full checkout instead of a standalone copy of "
                "bin/tautline"
            ) from exc

        _PUBLIC_RELEASE_MODULE = public_release
    return _PUBLIC_RELEASE_MODULE
WORK_PROFILE_CHOICES = {"development", "product-docs", "support-docs"}
NON_DEV_WORK_PROFILES = {"product-docs", "support-docs"}
WORK_PROFILE_PUSH_POLICIES = {"pr-branch-only", "direct-main"}
DEFAULT_WORK_PROFILE_LOCK_PATH = ".ai-work/WORK_PROFILE.json"
DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_PATHS = [
    "*.md",
    "*.txt",
    "*.pdf",
    "docs/**",
    "documentation/**",
    "product/**",
    "requirements/**",
    "wireframes/**",
    "design/**",
    "designs/**",
    "assets/wireframes/**",
    "assets/product/**",
    "mockups/**",
    "screenshots/**",
    "research/**",
    "support/**",
    "runbooks/**",
]
DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_EXTENSIONS = [
    ".md",
    ".txt",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".drawio",
    ".excalidraw",
    ".fig",
    ".figma",
    ".heic",
    ".mov",
    ".mp4",
]
DEFAULT_NON_DEV_WORK_PROFILE_BLOCKED_PATHS = [
    ".github/**",
    ".gitlab/**",
    ".minervit-ai-delivery.json",
    ".minervit/**",
    ".tautline.json",
    ".tautline/**",
    "AGENTS.md",
    "CLAUDE.md",
    "Dockerfile",
    "Dockerfile.*",
    "Makefile",
    "app/**",
    "apps/**",
    "bin/**",
    "charts/**",
    "client/**",
    "config/**",
    "db/**",
    "deploy/**",
    "docker/**",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "drizzle/**",
    "infra/**",
    "k8s/**",
    "lib/**",
    "migrations/**",
    "package.json",
    "package-lock.json",
    "packages/**",
    "pnpm-lock.yaml",
    "poetry.lock",
    "prisma/**",
    "pyproject.toml",
    "requirements*.txt",
    "scripts/**",
    "server/**",
    "src/**",
    "terraform/**",
    "tsconfig*.json",
    "web/**",
    "yarn.lock",
]
DEFAULT_WORK_PROFILES = {
    "enabled": True,
    "defaultProfile": "development",
    "profileLockPath": DEFAULT_WORK_PROFILE_LOCK_PATH,
    "prePushBase": None,
    "profiles": {
        "development": {
            "description": "Full implementation profile. All startup, git, review, test, board, and code gates apply.",
            "allowedPaths": [],
            "allowedExtensions": [],
            "blockedPaths": [],
            "maxFileBytes": 0,
            "pushPolicy": "pr-branch-only",
        },
        "product-docs": {
            "description": "Product manager profile for requirements, wireframes, product docs, planning artifacts, and approved assets.",
            "allowedPaths": DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_PATHS,
            "allowedExtensions": DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_EXTENSIONS,
            "blockedPaths": DEFAULT_NON_DEV_WORK_PROFILE_BLOCKED_PATHS,
            "maxFileBytes": 25_000_000,
            "pushPolicy": "pr-branch-only",
        },
        "support-docs": {
            "description": "Support profile for investigations, support notes, runbooks, docs, screenshots, and approved assets.",
            "allowedPaths": DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_PATHS,
            "allowedExtensions": DEFAULT_NON_DEV_WORK_PROFILE_ALLOWED_EXTENSIONS,
            "blockedPaths": DEFAULT_NON_DEV_WORK_PROFILE_BLOCKED_PATHS,
            "maxFileBytes": 25_000_000,
            "pushPolicy": "pr-branch-only",
        },
    },
}
DEPRECATED_COMMAND_REPLACEMENTS = {
    "goal-tracker-status": "backlog-provider-status",
    "goal-tracker-next": "backlog-provider-next",
    "goal-tracker-sync": "backlog-provider-sync",
    "goal-tracker-update": "backlog-provider-update",
    # 0.9.0 security exception: narrative journal publication is disabled (refuses in every mode);
    # the commands remain in the contract as deprecated with a named replacement until removal >=1.0.0.
    "publish-session-journal": "publish-instrumentation-record",
    "publish-pending-session-journals": "publish-instrumentation-record",
    # 0.120.0 (agent-agnostic roles R3): the four vendor-named aliases. They belong HERE because
    # this map is what `public_contract_status_for_command` reads, and that is what puts a surface
    # into `deprecatedSurfaces` -- without which upgrade tooling reading the machine-readable
    # contract never learns the rename.
    #
    # An earlier attempt added them here ALONE and broke the byte-identity guard on every frozen
    # migration report back to 0.6.x, because this map is not version-scoped. The scope now lives
    # in `_release_migration_report_data_uncached`, keyed to 0.120.0, in the same idiom as the
    # 0.9.0 journal publishers. Map plus scope is what lets a rename announce itself in the
    # release that ships it without editing the published history of earlier ones.
    "codex-run": "review-run",
    "claude-review": "packet-review",
    "claude-review-status": "packet-review-status",
    "codex-plan-review": "plan-review-native",
}
REQUIRED_COMMANDS = [
    "mainStatus",
    "fastPreflight",
    "fullPreflight",
    "testEnvironment",
    "mergeQueue",
    "openPrCheck",
    "mergeConflictCheck",
]
DEFAULT_BOOTSTRAP_INTERVIEW_PATH = ".ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md"
LEGACY_BOOTSTRAP_ALLOWLIST = REPO_ROOT / "adapters/projects/.bootstrap-legacy-allowlist.json"
INVALID_REPO_EVIDENCE_PATHS = {".", ".git"}
WEAK_REPO_EVIDENCE_FILENAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "code_of_conduct.md",
    "contributing.md",
    "license",
    "license.md",
    "readme",
    "readme.md",
    "security.md",
}
GENERIC_BOOTSTRAP_SLOT_VALUES = {
    "answered",
    "answered with project-specific evidence",
    "done",
    "n/a",
    "na",
    "none",
    "project-specific evidence",
    "tbd",
    "todo",
}
DEFAULT_PLANNING_ARTIFACTS = {
    "scratchPaths": ["~/.claude/plans/"],
    "reviewExemptions": [
        "doc-only: docs/index/release/backlog/operator-guide changes with no product, runtime, infra, security, data, spec, or test-harness behavior change; implementation review and gates still apply."
    ],
}
# PM-surface classifier: opt-in product-development surfaces. `surfaces` is a tuple; the loader
# normalizes it to a list.
# Default is empty -> opt-in (no surface is a PM surface until an adapter declares one).
DEFAULT_PRODUCT_DEVELOPMENT = {
    "surfaces": (),
}
# The fail-closed ALLOWLIST (Design 1 rule A3): a declared surface's fixed root MUST sit under one
# of these safe product roots, segment-bounded. Framework doc roots, code, config, and root files
# are NOT product roots, so surfaces under them are rejected BY CONSTRUCTION.
PM_SURFACE_PRODUCT_ROOTS = ("docs/product",)
DEFAULT_LANE_STATE = {
    "lockPath": ".minervit-methodology-lock.json",
    "runsDir": ".ai-runs",
    "executionPacket": ".ai-work/EXECUTION_PACKET.md",
    "milestoneRun": ".ai-work/MILESTONE_RUN.json",
    "goalRun": ".ai-work/GOAL_RUN.json",
    "gitIgnore": True,
}
DEFAULT_GOAL_ARTIFACTS = {
    "templateTrigger": "Substantial multi-milestone, multi-PR, overnight, or ambiguous build/ship/finish work.",
    "reviewRequired": True,
}
DEFAULT_GOAL_EXECUTION = {
    "preferredClaudeCommand": "/goal",
    "claudeGoalGuidance": True,
    "fallback": "goal-ledger",
}
DEFAULT_LANE_COORDINATION = {
    "enabled": True,
    "enforcement": "strict",
    "root": "",
    "contractPath": "",
    "boardPath": "",
    "laneStatusDir": "",
    "maxStatusAgeHours": 24,
    "rule": (
        "For simultaneous lanes, use tracked repo coordination artifacts as the source of truth for shared "
        "contracts, lane ownership, dependencies, provided interfaces, blockers, and PR refs. Each lane updates "
        "its own lane status file; shared contract/interface changes land early before large dependent PRs."
    ),
}
DEFAULT_GOAL_TRACKER = {
    "enabled": False,
    "provider": "github-projects",
    "owner": "",
    "projectNumber": 0,
    "scopeQuery": "",
    "statusField": "Status",
    "priorityField": "",
    "milestoneField": "",
    "readyStatuses": ["Ready", "Next"],
    "activeStatuses": ["In Progress"],
    "doneStatuses": ["Done"],
    "blockedStatuses": ["Blocked"],
    "authoritativeFor": ["goal-priority", "milestone-order", "goal-status"],
    "repoPlanRequired": True,
    "linkPolicy": "repo goal plan links back to project item",
    # RCA 2026-07-31 control 4. A provider-backed lane whose work genuinely has no board item --
    # a repo-only goal -- had no sanctioned path: the sync raised unconditionally and named no
    # way out, so the only exits were disabling the tracker wholesale or hand-editing the ledger.
    # An escape hatch that does not exist is not a safety property; it is where bypasses get
    # invented. Off by default, so nothing changes for a lane that never sets it.
    "allowRepoOnlyGoals": False,
}
DEFAULT_BACKLOG_PROVIDER = {
    "enabled": False,
    "provider": "github-projects",
    "owner": "",
    "projectNumber": 0,
    "scopeQuery": "",
    "itemTypes": ["goal", "milestone", "bug", "task"],
    "typeField": "",
    "statusField": "Status",
    "priorityField": "",
    "milestoneField": "",
    "readyStatuses": ["Ready", "Next"],
    "activeStatuses": ["In Progress"],
    "doneStatuses": ["Done"],
    "blockedStatuses": ["Blocked"],
    "authoritativeFor": ["goal-priority", "milestone-order", "goal-status", "bug-status", "task-priority"],
    "repoPlanRequired": True,
    "tacticalPlanningAuthority": "repo",
    "syncMode": "read-select-write-status-links-notes",
    "linkPolicy": "external backlog item links to reviewed repo source-of-truth plan before execution",
    # Mirror of goalTracker.allowRepoOnlyGoals -- load_project round-trips legacy adapters through
    # BOTH converters, so a key present in only one family is silently dropped on the return leg.
    "allowRepoOnlyGoals": False,
    # Item 59: the checkout holding this lane's plans when they live outside it. Empty means
    # lane-only, which is every lane that keeps its plans in-repo. Its directory BASENAME becomes
    # the plan-reference root token (`tautline-backlog:ready/x/plan.md`), dynamically -- no
    # spelling is blessed. Independent of `enabled`: a lane may keep plans externally while its
    # board provider is off, which is exactly this repository's own configuration.
    "planRepo": "",
    "migrationInterviewPath": ".ai-work/BACKLOG_PROVIDER_MIGRATION.md",
    "exportMode": "interview-approved",
    "completionUnit": "goal",
    "featureSeries": {},
    # Item 81: oracle discipline at closure. `warn` by default -- an unproven gate wired to block
    # on every adopter is how a gate gets disabled permanently. The `strict` ratchet criteria are
    # published in the release migration report, not decided here.
    "doneEvidence": {"acTable": "warn"},
}
DEFAULT_STAKEHOLDER_QUESTIONS = {
    "enabled": False,
    "provider": "github-issues",
    "defaultMention": "",
    "unknownStakeholderPolicy": "ask-human-once",
    "openLabel": "needs-stakeholder-answer",
    "answeredLabel": "stakeholder-answered",
    "syncAt": ["startup", "milestone-boundary", "pr-boundary", "blocked"],
    "projectStatusOnOpen": "Blocked",
    "projectStatusOnAnswered": "In Progress",
}
DEFAULT_LATEST_CODE = {
    "enabled": True,
    "remote": "origin",
    "base": "main",
    "statusFile": ".ai-work/LATEST_CODE_BASELINE.json",
    "maxAgeMinutes": 60,
    "fetchAll": True,
    "includeOpenPrs": True,
    "includeRemoteBranches": True,
    "maxAheadBranches": 20,
    "rule": (
        "Before status, deep analysis, planning, implementation, review, or tactical subagent dispatch, "
        "fetch current remote state and inspect base plus other remote branches/PRs that may be ahead or deployed. "
        "Do not assume local HEAD or origin/main is the product surface when a deployed or active lane branch is ahead."
    ),
}
# Product-dev mode: a per-checkout, gitignored .ai-work/ state file resolved exactly like the
# latest-code baseline. INERT on its own -- the sibling shepherding-standdown plan wires the
# reader into the three nagging hooks. NEVER read by any code-safety path (guard_check /
# cut_release / the version-contract predicate); that invariant is what lets even a dev agent
# enable the mode without being able to ship unreviewed code.
DEFAULT_PRODUCT_DEV_MODE = {
    "statusFile": ".ai-work/PRODUCT_DEV_MODE.json",
}
# Lane currency check (item 27: session-start currency gate). `startupCheck` has NO `block` value --
# the never-blocks guarantee is structural, not a policy the handler is trusted to keep.
DEFAULT_LANE_STATUS = {
    "startupCheck": "report",
    # Schema max is 15 and the SessionStart host timeout is 25, so the host can never kill the hook
    # before the collector reports UNVERIFIED.
    "fetchTimeoutSeconds": 8,
    "maxAgeMinutes": 60,
    "integrationBranch": "",  # "" -> fall back to latestCode.base
    "statusFile": ".ai-work/LANE_STATUS.json",
    "claimSource": "",  # "" -> claim lookup is NOT performed (claim_state="not-checked")
}
LANE_STATUS_MAX_FETCH_TIMEOUT_SECONDS = 15
# One shared budget for ALL collection probes (fetch + every local git call), sized below
# SESSION_START_LANE_STATUS_HOOK_TIMEOUT (25) so the report always gets printed.
LANE_STATUS_COLLECTION_BUDGET_SECONDS = 18
# Bound the claim enumeration so a huge or slow claimSource cannot burn the budget.
LANE_STATUS_MAX_CLAIM_ENTRIES = 2000
# `redact_secrets` masks token SHAPES; it does not touch URL userinfo, and git echoes exactly that
# form on a failed authenticated fetch.
LANE_STATUS_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]*@")
LANE_STATUS_UNUSABLE_REMOTE = "<unusable>"

PRODUCT_DEV_MODE_SCHEMA = "tautline-product-dev-mode/v1"


# ---------------------------------------------------------------------------
# Fleet Governor: machine-local lease coordination across worktrees (v1).
# State lives in <git-common-dir>/tautline-fleet so every worktree of a repo
# shares it with zero configuration. Guard posture is deliberately fail-open:
# a coordination aid must never strand a lane on bad state.
# ---------------------------------------------------------------------------

# Imported directly rather than through the guarded `_MissingFrameworkPackage` idiom below,
# because DEFAULT_FLEET needs these values at module-import time and that idiom is not defined
# until much later in this file. `occupancy` is a dependency-free leaf, so a plain import here
# cannot introduce a cycle -- cli.py imports leaves, never the reverse.
from tautline_methodology import agent_compat  # noqa: E402
from tautline_methodology import lean  # noqa: E402 --- LEAN PROFILE WIRING ---
from tautline_methodology import runtime_capabilities  # noqa: E402
from tautline_methodology import agents as agents_mod  # noqa: E402
# The provider registry is a leaf: it imports neither `cli` nor `ghutil`, and the provider modules
# it pulls in reach back for `cli` lazily inside their verbs. So this import cannot close a cycle,
# by the same rule as `occupancy` above.
from tautline_methodology import providers as providers_mod  # noqa: E402
from tautline_methodology.occupancy import (  # noqa: E402
    DEFAULT_OCCUPANCY,
    OCCUPANCY_MAX_TTL_MINUTES,
    OCCUPANCY_MODES,
    OCCUPANCY_PRIMARY_CHECKOUT_MODES,
    OCCUPANCY_LEASE_SCHEMA,
    occupancy_acquire,
    occupancy_lease_is_live,
    occupancy_session_identity,
)
FLEET_ENFORCEMENT_CHOICES = ("block", "advise", "observe")
DEFAULT_FLEET = {
    "enabled": True,
    "enforcement": "block",
    "defaultTtlMinutes": 240,
    "occupancy": DEFAULT_OCCUPANCY,
}
# Upper bound on any lease TTL. Unbounded values overflow datetime arithmetic
# (`anchor + timedelta(minutes=ttl)` raises OverflowError above ~4.19e9 minutes),
# which escapes lease_is_live and aborts the whole conflict scan -- so ONE absurd
# lease stops every other live lease from being enforced. One year is far beyond
# any real working-set claim and leaves ~7 orders of magnitude of headroom.
FLEET_MAX_TTL_MINUTES = 60 * 24 * 365


def fleet_config(data: dict) -> dict:
    raw = data.get("fleet") if isinstance(data, dict) else None
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter fleet must be an object")
    cfg = {**DEFAULT_FLEET, **(raw or {})}
    # SHALLOW MERGE IS NOT ENOUGH FOR A SUB-OBJECT. `{**DEFAULT_FLEET, **raw}` replaces
    # `occupancy` wholesale, so an adapter that sets one key inside it silently loses the other
    # three to absence rather than to their defaults -- and the validation below would then be
    # judging keys nobody wrote. Normalize the sub-object against its own defaults explicitly.
    raw_occupancy = (raw or {}).get("occupancy")
    if raw_occupancy is not None and not isinstance(raw_occupancy, dict):
        raise SystemExit("Project adapter fleet.occupancy must be an object")
    cfg["occupancy"] = {**DEFAULT_OCCUPANCY, **(raw_occupancy or {})}
    occupancy = cfg["occupancy"]
    if not isinstance(occupancy.get("enabled"), bool):
        raise SystemExit("Project adapter fleet.occupancy.enabled must be a boolean")
    if occupancy.get("mode") not in OCCUPANCY_MODES:
        raise SystemExit(
            "Project adapter fleet.occupancy.mode must be one of: " + ", ".join(OCCUPANCY_MODES)
        )
    if occupancy.get("primaryCheckout") not in OCCUPANCY_PRIMARY_CHECKOUT_MODES:
        raise SystemExit(
            "Project adapter fleet.occupancy.primaryCheckout must be one of: "
            + ", ".join(OCCUPANCY_PRIMARY_CHECKOUT_MODES)
        )
    occupancy_ttl = occupancy.get("ttlMinutes")
    if (
        not isinstance(occupancy_ttl, int)
        or isinstance(occupancy_ttl, bool)
        or occupancy_ttl <= 0
        or occupancy_ttl > OCCUPANCY_MAX_TTL_MINUTES
    ):
        raise SystemExit(
            "Project adapter fleet.occupancy.ttlMinutes must be a positive integer "
            f"no greater than {OCCUPANCY_MAX_TTL_MINUTES}"
        )
    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit("Project adapter fleet.enabled must be a boolean")
    if cfg.get("enforcement") not in FLEET_ENFORCEMENT_CHOICES:
        raise SystemExit(
            "Project adapter fleet.enforcement must be one of: "
            + ", ".join(FLEET_ENFORCEMENT_CHOICES)
        )
    ttl = cfg.get("defaultTtlMinutes")
    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or ttl <= 0
        or ttl > FLEET_MAX_TTL_MINUTES
    ):
        raise SystemExit(
            "Project adapter fleet.defaultTtlMinutes must be a positive integer "
            f"no greater than {FLEET_MAX_TTL_MINUTES}"
        )
    return cfg


def occupancy_enabled(data: dict) -> bool:
    """Effective occupancy enablement: `fleet.enabled` AND `fleet.occupancy.enabled`.

    The master fleet opt-out has to keep working. A lane that turned the fleet governor off did
    not agree to a new coordination gate appearing underneath it, so occupancy is off there
    regardless of its own key -- one switch that means what it says.
    """
    cfg = fleet_config(data)
    return bool(cfg["enabled"]) and bool(cfg["occupancy"]["enabled"])


def occupancy_record_session(data: dict, target: Path) -> None:
    """Record that this session is in this worktree. Never raises, never blocks, never refuses.

    The SessionStart seam, and deliberately not a gate: `lane-status` runs as a hook on every
    session start and must stay exit 0 on every path. Refusing belongs to `lane-start`, which a
    human ran on purpose and can answer. This one only leaves the trace that makes the conflict
    VISIBLE -- to the next `lane-start`, and to anyone reading the lease.
    """
    try:
        if not occupancy_enabled(data):
            return
        path = occupancy_lease_path(target)
        if path is None:
            return
        status, _holder = occupancy_acquire(
            path,
            occupancy_session_identity(),
            datetime.now(timezone.utc),
            branch=run_git(target, ["branch", "--show-current"]) or "",
            ttl_minutes=fleet_config(data)["occupancy"]["ttlMinutes"],
        )
        if status == "conflict":
            # WRITE THE PEER RECORD. Losing the lease race is exactly when this session is the
            # invisible one -- it holds nothing, so the holder's own `lane-status` would report a
            # clean worktree while two sessions edit it. Codex R1 P2: PR3's collector reads these
            # records and nothing created them, which made the "peer record alone" case a test
            # fixture rather than a reachable state.
            occupancy_write_peer_record(target, occupancy_session_identity(), data)
            # Reported, never refused: see the docstring. The next lane-start is where this
            # becomes a decision.
            print(f"occupancy_status: conflict in {target}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - a hook that raises is a hook that breaks session start
        return


def occupancy_lease_path(target: Path) -> Path | None:
    """Where THIS worktree's occupancy lease lives, or None when there is no git dir to hang it on.

    Keyed on the worktree's own `--git-dir`, not the shared common dir the fleet governor uses:
    the fleet lease coordinates claims ACROSS worktrees, while this one answers "is another session
    sitting in THIS checkout", which is a per-worktree fact.
    """
    git_dir = run_git(target, ["rev-parse", "--git-dir"])
    if not git_dir or git_dir == "unavailable":
        return None
    git_path = Path(git_dir)
    if not git_path.is_absolute():
        git_path = (Path(target).resolve() / git_path).resolve()
    return git_path / "tautline-occupancy.json"

DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT = 85
CLAUDE_AUTOCOMPACT_ENV_KEYS = {
    "MINERVIT_CLAUDE_AUTOCOMPACT_PCT": str(DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT),
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT),
    "MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED": "1",
    # Compat-sunset (roadmap #16, PR2): dual-write the TAUTLINE_ autocompact twins into the durable
    # ~/.claude/settings.json env block. Claude Code loads these into every session's process env,
    # so claude_autocompact_env_status()'s resolve_env resolves through the TAUTLINE_ alias and the
    # PR-1 self-warning never fires on a normally-provisioned startup. Values are unchanged; the
    # legacy spellings stay for older runtimes. claude_autocompact_settings_state iterates this same
    # dict, so the drift check requires the twins too. Removed with the MINERVIT_ family at
    # METH-FU-TAUTLINE-FALLBACK-REMOVAL.
    "TAUTLINE_CLAUDE_AUTOCOMPACT_PCT": str(DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT),
    "TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED": "1",
}
DEFAULT_MILESTONE_CONTINUATION = {
    "watchdogEnabled": False,
    "watchdogCadenceMinutes": 30,
}
DEFAULT_SESSION_JOURNAL = {
    # Opt-in since 0.8.7: journals narrate the adopter's product work and publish to the
    # framework checkout's journal branch, so they must never be on without a declaration.
    "enabled": False,
    "branch": "methodology-session-archive",
    "archiveDir": "docs/backlog/session-journals",
    "cadence": "milestone",
    "gitIgnoreLocal": True,
    "maxBytes": 12000,
}
DEFAULT_INSTRUMENTATION = {
    # Opt-in exactly like session journals (0.9.0): the sanitized instrumentation record is the ONLY
    # session evidence that can ever reach a remote (it has zero freeform capacity by construction),
    # but publishing is off until an operator declares it per lane. `enabled` alone permits the
    # publish command; `cadence` gates only whether boundary guidance PROMPTS for emission
    # (milestone = at milestone boundaries, session = every session end, off = never prompted). A
    # disabled lane is never prompted regardless of cadence. Deliberately NO branch/archiveDir keys:
    # remote metadata is a fixed constant (see the publisher's "Remote metadata is constant" design).
    "enabled": False,
    "cadence": "milestone",
}
DEFAULT_OBSERVABILITY_EVENTS = {
    "enabled": True,
    "stateDir": "$HOME/.local/state/minervit/repo-events",
    "humanLog": "events.log",
    "jsonlLog": "events.jsonl",
    "rotateBytes": 5000000,
    "retainedRotations": 5,
    "requiredBoundaryEvents": [
        "startup",
        "planning_review_gate",
        "preflight",
        "pr_queue_merge",
        "blocker",
        "rca",
        "continuity",
        "context_rotation",
        "goal_transition",
        "milestone_transition",
    ],
}
DEFAULT_USAGE_ACCOUNTING = {
    "enabled": True,
    "stateDir": "$HOME/.local/state/minervit/usage",
    "jsonlLog": "usage.jsonl",
    "rollupJson": "usage-rollup.json",
    "rotateBytes": 5000000,
    "retainedRotations": 5,
}
DEFAULT_ITERATION_REVIEW = {
    "enabled": False,
    "granularities": ["goal"],
    "outputs": {
        "page": True,
        "video": True,
    },
    "boundary": {
        "announce": True,
        "autoRunAtBoundary": True,
    },
    "recordDir": "docs/iteration-reviews",
    "hosting": {
        "store": "s3",
        "bucket": "",
        "keyPattern": "<project>/iteration-reviews/<target-id>/<media-file>",
        "cdn": "cloudfront",
        "access": "private-cdn",
        "baseUrl": "",
    },
    "delivery": {
        "enabled": False,
        "trigger": "after-merge",
        "provider": "google-chat-webhook",
        "webhookEnv": "",
        "chatSpace": "",
        "primaryUrl": "cloudfront-page",
        "dedupe": True,
        "sentStateDir": ".ai-work/iteration-review-delivery",
    },
    "video": {
        "music": {
            "enabled": True,
            "source": "adapter-approved",
            "defaultUrl": "",
            "volume": 0.18,
        },
    },
    "rendererVersion": "0.2.1",
}
DEFAULT_MILESTONE_UPDATE = {
    "enabled": False,
    "trigger": "milestone-complete",
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "chatSpace": "Product Milestones",
    "dedupe": True,
    "sentStateDir": ".ai-work/milestone-update-delivery",
    "maxChars": 4000,
}
DEFAULT_PRODUCT_CHAT = {
    "enabled": False,
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "chatSpace": "Product",
    "maxChars": 6000,
}
DEFAULT_DEPLOYMENT_NOTIFICATION = {
    "enabled": False,
    "trigger": "deploy-ready",
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "reuseIterationReviewWebhook": True,
    "chatSpace": "Product",
    "dedupe": True,
    "sentStateDir": ".ai-work/deployment-notification-delivery",
    "maxChars": 3000,
    "pipeline": {
        "required": False,
        "mode": "ci-post-deploy",
        "evidencePaths": [],
        "requiredCommand": "tautline publish-deploy-ready-update",
        "healthCheckBeforeNotify": True,
    },
}
DEFAULT_DEPLOY_HEALTH = {
    "enabled": False,
    "provider": "github-actions",
    "workflow": "",
    "branch": "main",
    "limit": 25,
    "failOnLatestFailure": True,
    "maxConsecutiveFailures": 3,
    "maxSuccessAgeHours": 72,
}
DEFAULT_CONTEXT_ROTATION = {
    "enabled": True,
    "softPercent": 60,
    "hardPercent": 75,
    "heartbeatMinutes": 15,
    "heartbeatBoundary": "goal-heartbeat",
    "safeBoundaries": [
        "pr-queued",
        "pr-complete",
        "milestone-complete",
        "goal-boundary",
        "goal-heartbeat",
        "session-summary",
        "handoff-for-review",
    ],
}
DEFAULT_MODEL_EFFORT_POLICY = {
    "defaultEffort": "high",
    "xhighPolicy": "debugging/design escalation only",
    "executionPacketSonnetEligible": True,
}
DEFAULT_LOCAL_RESOURCE_LOCKS = {
    "locksDir": "~/.minervit-ai-delivery/locks",
    "resources": [],
}
DEFAULT_LOCAL_RESOURCE_ISOLATION = {
    "envFile": ".ai-work/lane-env.sh",
    "composeProjectPrefix": "tautline",
    "portStride": 10,
    "portVariables": [],
    "envTemplates": {},
    "isolatedCommands": [],
}
DEFAULT_DOCUMENT_CONTEXT = {
    "enforcement": "warn",
    "maxIndexBytes": 16000,
    "maxIndexLines": 250,
}
# RCA: a repo can define tests yet run them nowhere in CI, so regressions ship silently while every
# methodology gate (all local, agent-invoked) stays green. The CI-test-gate health check fails closed
# when the repo has tests but no CI workflow runs them on PR/push. "warn" surfaces it loudly; "block"
# makes it a blocking gate (methodology-status --fail-on-drift + pre-push).
DEFAULT_CI_TEST_GATE = {
    "enabled": True,
    "enforcement": "warn",
    "events": ["pull_request", "push"],
    "testCommandMarkers": [],
    "requiredWorkflow": "",
    "requiredCheckName": "",
}
UI_EVIDENCE_EVENTS = {"milestone-complete", "goal-complete", "work-item-complete"}
DEFAULT_UI_EVIDENCE = {
    "enabled": False,
    "enforcement": "warn",
    "tool": "playwright",
    "evidenceDir": ".ai-work/ui-evidence",
    "manifestGlob": "*.json",
    "captureCommand": "",
    "requiredEvents": ["milestone-complete", "goal-complete"],
    "issueComments": {
        "enabled": False,
        "provider": "github-issues",
        "triggerEvents": ["milestone-complete", "goal-complete"],
        "required": False,
    },
}
DEFAULT_RUNTIME_CONFIG = {
    "enforcement": "warn",
    "requiredSecrets": [],
    "bootAssertionCommand": "",
    "secretParityCommand": "",
}
SUPPORTED_DEVELOPMENT_RUNTIMES = {"linux", "darwin", "wsl1", "wsl2", "win32"}
DEFAULT_DEVELOPMENT_ENVIRONMENT = {
    "supportedRuntimes": [],
    "windows": {
        "native": "unspecified",
        "supportedRuntime": "wsl2",
        "setup": "",
        "reason": "",
    },
    "lineEndings": {
        "policy": "",
        "windowsGuidance": "",
    },
}
DEFAULT_MIGRATION_SAFETY = {
    "enforcement": "warn",
    "migrationsPath": "",
    "ackMarker": "MIGRATION-SAFETY-ACK",
}
DEFAULT_COVERAGE_FLOOR = {
    "enforcement": "warn",
    "newCodeMinPct": 80,
    "coverageReport": "coverage.json",
    "diffBase": "origin/main",
}
DEFAULT_PLAN_ACCEPTANCE = {
    "enforcement": "off",
    "acHeadings": ["acceptance criteria"],
}
# Test-quarantine markers across common stacks. A diff that ADDS one of these (rec #14) must record an
# owner + a due/issue/trigger, so a flaky/skipped test is tracked debt, not silent gate erosion. This is
# phrase vocabulary (a list of str) -> exported to the policy-phrase SSOT.
FLAKY_QUARANTINE_MARKERS = [
    "@flaky",
    "@pytest.mark.flaky",
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "@pytest.mark.skipif",
    "@unittest.skip",
    "pytest.skip(",
    "pytest.xfail(",
    "describe.skip(",
    "it.skip(",
    "test.skip(",
    "xit(",
    "xdescribe(",
    "@disabled",
    "@ignore",
    "t.skip(",
    "#[ignore]",
]
DEFAULT_FLAKY_QUARANTINE = {
    "enforcement": "warn",
    "maxMarkers": -1,
    "scanPath": "",
}
DEFAULT_HEALTH_CONTRACT = {"enforcement": "off"}
DEFAULT_SIDE_EFFECT_PROOF = {"enforcement": "off"}
DEFAULT_DEPLOYMENT_TARGETS: list[dict] = []
DEFAULT_AWS_CLI_CONVENTION = "For AWS-approved lanes, use AWS CLI: check `aws --version` and `aws sts get-caller-identity` or adapter identity check; install/login if missing; do not ask for SSH keys unless adapter declares SSH/non-AWS deployment."
DEFAULT_TECHNOLOGY_STACK = {
    "cloudProviderDefault": "AWS",
    "approvedCloudProviders": ["AWS"],
    "newProjectCloudDefault": "AWS",
    "newCloudProviderRequiresApproval": True,
    "awsCliConvention": DEFAULT_AWS_CLI_CONVENTION,
    "nonNegotiable": [
        "Cloud services default to AWS unless the adapter explicitly overrides approved providers.",
        "Non-approved cloud/hosting platforms require adapter approval or explicit human approval.",
    ],
    "rule": "Use adapter-declared stack defaults; tool/framework defaults never authorize a new deployment platform.",
}
DEFAULT_GRAPHIFY = {
    "enabled": True,
    "preferWhenPresent": True,
    "outputDir": "graphify-out",
    "reportPath": "graphify-out/GRAPH_REPORT.md",
    "graphPath": "graphify-out/graph.json",
    "installPackage": "graphifyy",
    "installCommand": "python3 -m pip install --user graphifyy",
    "setupCommand": "graphify install",
    # Both commands are the dependency-free no-LLM AST refresh, which cold-builds from nothing
    # (measured: exit 0 and graph.json + GRAPH_REPORT.md created with no API key and no
    # AWS_PROFILE). The auto-detect form `graphify .` is deliberately absent from every default:
    # it selects a backend from ambient credentials, and RCA 20260616T133743Z is what happens
    # when a provider retires the model that selection lands on -- a blocking gate whose
    # documented command can be killed by a third party, silently, forever.
    "buildCommand": "graphify update .",
    "updateCommand": "graphify update .",
    "queryCommand": "graphify query",
    "pathCommand": "graphify path",
    "explainCommand": "graphify explain",
    "gitIgnoreOutput": True,
    "allowProjectInstaller": False,
    "freshnessEnforcement": "strict-if-present",
    "freshnessRule": (
        "After every code, docs, schema, route, test, architecture, or other system change, run "
        "`graphify update .` (the no-LLM AST refresh; no API key, backend, or external-model "
        "dependency) before commit/push and before relying on existing Graphify output; stale "
        "graphs are blocking drift. LLM-backed graphify invocations are never the blocking gate."
    ),
    "semanticCommand": "GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli",
    "semanticRule": (
        "Semantic enrichment (community labels, GRAPH_REPORT) is a separate NON-blocking step: "
        "run the semantic command with its explicit backend only when enrichment is wanted; its "
        "failure never blocks commit or push."
    ),
    "rule": (
        "When enabled and graphify-out/GRAPH_REPORT.md or graphify-out/graph.json exists, use Graphify "
        "report/query/path/explain for codebase orientation before broad grep/rg to reduce token-heavy scans; "
        "use rg for exact lexical searches or when Graphify is absent. Stale Graphify output must be refreshed before use."
    ),
}
DEFAULT_BEHAVIOR_PENDING_TAGS = ["@pending"]
DEFAULT_BEHAVIOR_ACCEPTANCE_HARNESSES: list[dict] = []
DEFAULT_BUG_BACKLOG = {
    "sourceOfTruth": "backlogAdapter",
    "issueMirrors": [],
    "severityTaxonomy": "No project-specific bugBacklog configured; preserve project-local severity labels and do not invent tracker policy.",
    "autoP0Categories": [],
    "autoP1Categories": [
        "auth",
        "email",
        "tenant data",
        "security",
        "deploy",
        "billing",
        "data loss",
        "customer-blocking",
    ],
    "requiredFields": [
        "observed behavior",
        "expected behavior",
        "impact",
        "source files or evidence",
        "recommended fix",
        "test plan",
    ],
    "rule": "No project-specific bugBacklog configured; route bugs through backlogAdapter and do not open external issues unless project evidence requires them.",
}
GIT_BRANCH_LIVENESS_HOOKS = ["pre-commit", "pre-push"]
METHODOLOGY_REEXEC_TOKEN_ENV = "MINERVIT_METHODOLOGY_REEXEC_TOKEN"
METHODOLOGY_RESCUE_STATE_ENV = "MINERVIT_METHODOLOGY_RESCUE_STATE_DIR"
METHODOLOGY_REEXEC_TOKEN_MAX_AGE_SECONDS = 60


# package-split A2 (roadmap #11): a standalone copy of bin/tautline (no src/ sibling) must still
# LOAD so hooks fail open; a src-absent package import therefore binds a guided stand-in instead of
# raising at module load. Its attributes are stubs that raise the guided SystemExit the hook
# fail-open contract recognizes, so a moved-name USE on a standalone copy fails open (hook) or
# reports the guided message -- it never wedges bin's import. src-present binds the real module.
class _MissingFrameworkPackage:
    def __init__(self, exc: ModuleNotFoundError, subject: str) -> None:
        self._exc = exc
        self._subject = subject

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        subject, exc = self._subject, self._exc

        def _guided_stub(*args: object, **kwargs: object) -> object:
            raise SystemExit(
                f"{subject} require the framework checkout's src/tautline_methodology package; "
                "run this command from a full checkout instead of a standalone copy of bin/tautline"
            ) from exc

        return _guided_stub


# package-split W3 (roadmap #11): delivery/publication leaves moved to the package -- the closure-
# clean adapter/bootstrap leaves to tautline_methodology.adapters and the closure-clean release-
# machinery leaves to tautline_methodology.release. Each is re-exported below as an eager alias
# assignment (in place of its former def/const) so cli.<name> reach and every in-bin call site keep
# resolving. publish + install families have NO closure-clean defs (every verb handler reaches
# monolith state: run_git/run_command/lane_project/chat/deploy/canonical_* etc.) so they are fully
# deferred with no module this wave. The imports are fail-tolerant so a standalone bin/tautline
# with no src package still LOADS (hook fail-open contract): a src-absent import binds a stand-in.
try:
    from tautline_methodology import adapters as _adapters_mod
except ModuleNotFoundError as exc:
    _adapters_mod = _MissingFrameworkPackage(exc, "adapter/bootstrap leaves")  # type: ignore
try:
    from tautline_methodology import release as _release_mod
except ModuleNotFoundError as exc:
    _release_mod = _MissingFrameworkPackage(exc, "release machinery leaves")  # type: ignore
BOOTSTRAP_REQUIRED_PREFIX = _adapters_mod.BOOTSTRAP_REQUIRED_PREFIX

# package-split W4 (roadmap #11): the lane + context ROOT families -- the most shared-state-heavy
# families in the CLI. Only genuinely closure-clean leaves move: the lane slot/env-path/session-
# path derivations, the lane-coordination config accessor + contract/board templates, and the
# lane-start debt-preflight write wrapper to tautline_methodology.lane; the pure context-rotation
# decision core to tautline_methodology.context. Each moved name is re-exported below as an eager
# alias assignment (in place of its former def/const) so cli.<name> reach and every in-bin call
# site keep resolving. Every stateful lane/context verb handler (lane_start/lane_run/lane_project/
# ensure_lane_state/work_loop, context_bootstrap/context_status/context_rotation_check/heartbeat)
# reaches monolith state (REPO_ROOT, run_git, load_project, lane_project, goal_run_path, ...) and
# stays in bin, wired to the moved leaves through these aliases. The imports are fail-tolerant so
# a standalone bin/tautline with no src package still LOADS (hook fail-open contract): a src-absent
# import binds a guided stand-in.
try:
    from tautline_methodology import lane as _lane_mod
except ModuleNotFoundError as exc:
    _lane_mod = _MissingFrameworkPackage(exc, "lane lifecycle leaves")  # type: ignore
# --- carved: re-exported for the cli.<attr> surface ---
# 391 symbol(s) moved to tautline_methodology.core.runtime; re-exported
# here as eager aliases so cli.<name> reach and in-bin references keep resolving.
try:
    from tautline_methodology.core import runtime as _core_runtime_mod
except ImportError as exc:
    # Only an ABSENT destination may fail open. A destination that exists but raises
    # while initialising is a real implementation failure, and converting it here would
    # make every hook swallow it. find_spec distinguishes the two -- including when
    # find_spec itself raises: importing a parent package can re-raise the parent's own
    # initialisation failure, and only a ModuleNotFoundError naming a module on the
    # destination's dotted path means ABSENT rather than broken.
    import importlib.util as _ilu
    _dotted = "tautline_methodology.core.runtime".split(".")
    _chain = {".".join(_dotted[:_n]) for _n in range(1, len(_dotted) + 1)}
    try:
        _locatable = _ilu.find_spec("tautline_methodology.core.runtime") is not None
    except ModuleNotFoundError as _probe_exc:
        if _probe_exc.name not in _chain:
            raise
        _locatable = False
    except ValueError:
        _locatable = False
    if _locatable:
        raise
    # A missing SUBMODULE of an importable package raises plain ImportError, but the
    # hook fail-open path keys on SystemExit.__cause__ being a ModuleNotFoundError.
    if not isinstance(exc, ModuleNotFoundError):
        exc = ModuleNotFoundError(str(exc), name="tautline_methodology.core.runtime")
    _core_runtime_mod = _MissingFrameworkPackage(  # type: ignore[assignment]
        exc, "shared CLI runtime helpers"
    )
EVENT_MAX_FIELD_CHARS = _core_runtime_mod.EVENT_MAX_FIELD_CHARS
EVENT_MAX_JSON_CHARS = _core_runtime_mod.EVENT_MAX_JSON_CHARS
collect_bootstrap_placeholders = _core_runtime_mod.collect_bootstrap_placeholders
validate_relative_bootstrap_path = _core_runtime_mod.validate_relative_bootstrap_path
resolve_bootstrap_target_path = _core_runtime_mod.resolve_bootstrap_target_path
extract_bootstrap_header = _core_runtime_mod.extract_bootstrap_header
validate_render_adapter_provenance = _core_runtime_mod.validate_render_adapter_provenance
normalize_profile_path = _core_runtime_mod.normalize_profile_path
normalize_profile_string_list = _core_runtime_mod.normalize_profile_string_list
framework_pin_status_line = _core_runtime_mod.framework_pin_status_line
_update_probe_result = _core_runtime_mod._update_probe_result
_update_probe_parse_iso = _core_runtime_mod._update_probe_parse_iso
_framework_update_reason_is_wip_hold = _core_runtime_mod._framework_update_reason_is_wip_hold
normalize_tracker_adapter_config = _core_runtime_mod.normalize_tracker_adapter_config
ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT = _core_runtime_mod.ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT
protected_markdown_message = _core_runtime_mod.protected_markdown_message
RENDER_OMITTABLE_DOMAINS = _core_runtime_mod.RENDER_OMITTABLE_DOMAINS
HARD_EXCLUDED_ROOTS = _core_runtime_mod.HARD_EXCLUDED_ROOTS
HARD_EXCLUSION_SENTINELS = _core_runtime_mod.HARD_EXCLUSION_SENTINELS
public_contract_status_for_adapter_key = _core_runtime_mod.public_contract_status_for_adapter_key
public_contract_status_for_skill = _core_runtime_mod.public_contract_status_for_skill
telemetry_salt = _core_runtime_mod.telemetry_salt
instrumentation_seq_state_path = _core_runtime_mod.instrumentation_seq_state_path
read_instrumentation_seq_state = _core_runtime_mod.read_instrumentation_seq_state
PYTHON_FLOOR = _core_runtime_mod.PYTHON_FLOOR
REGISTRY_PACKAGE_REPO_SLUG = _core_runtime_mod.REGISTRY_PACKAGE_REPO_SLUG
REGISTRY_PACKAGE_REGISTRIES = _core_runtime_mod.REGISTRY_PACKAGE_REGISTRIES
REGISTRY_PACKAGE_DIST_DIR = _core_runtime_mod.REGISTRY_PACKAGE_DIST_DIR
PUBLIC_MIRROR_REPO = _core_runtime_mod.PUBLIC_MIRROR_REPO
PUBLIC_MIRROR_REMOTE = _core_runtime_mod.PUBLIC_MIRROR_REMOTE
PUBLIC_MIRROR_BRANCH = _core_runtime_mod.PUBLIC_MIRROR_BRANCH
RELEASE_TAIL_RUN_FIELDS = _core_runtime_mod.RELEASE_TAIL_RUN_FIELDS
ReleaseTailError = _core_runtime_mod.ReleaseTailError
_PM_SURFACE_METACHARACTERS = _core_runtime_mod._PM_SURFACE_METACHARACTERS
pm_surface_fixed_prefix = _core_runtime_mod.pm_surface_fixed_prefix
pm_roots_overlap = _core_runtime_mod.pm_roots_overlap
_looks_like_repo_relative_path = _core_runtime_mod._looks_like_repo_relative_path
read_lock = _core_runtime_mod.read_lock
no_adapter_message = _core_runtime_mod.no_adapter_message
methodology_reexec_token_dir = _core_runtime_mod.methodology_reexec_token_dir
SNAPSHOT_PIN_SCHEMA = _core_runtime_mod.SNAPSHOT_PIN_SCHEMA
SNAPSHOT_DEFAULT_KEEP = _core_runtime_mod.SNAPSHOT_DEFAULT_KEEP
SNAPSHOT_DEFAULT_PIN_TTL_HOURS = _core_runtime_mod.SNAPSHOT_DEFAULT_PIN_TTL_HOURS
_make_snapshot_read_only = _core_runtime_mod._make_snapshot_read_only
_rmtree_force = _core_runtime_mod._rmtree_force
_reject_unsafe_tar_members = _core_runtime_mod._reject_unsafe_tar_members
_safe_extract_methodology_tar = _core_runtime_mod._safe_extract_methodology_tar
_retire_store_snapshot_dir = _core_runtime_mod._retire_store_snapshot_dir
METHODOLOGY_SYNC_STAMP_SCHEMA = _core_runtime_mod.METHODOLOGY_SYNC_STAMP_SCHEMA
METHODOLOGY_SYNC_DEFAULT_FRESHNESS_MINUTES = (
    _core_runtime_mod.METHODOLOGY_SYNC_DEFAULT_FRESHNESS_MINUTES
)
normalize_critical_journeys = _core_runtime_mod.normalize_critical_journeys
load_claude_settings = _core_runtime_mod.load_claude_settings
write_claude_settings = _core_runtime_mod.write_claude_settings
lane_status_declared_claim_branch = _core_runtime_mod.lane_status_declared_claim_branch
LAUNCHER_GENERATED_MARKER = _core_runtime_mod.LAUNCHER_GENERATED_MARKER
_launcher_text = _core_runtime_mod._launcher_text
_launcher_digest = _core_runtime_mod._launcher_digest
LAUNCHER_DIVERGENCE_HAND_REPLACED = _core_runtime_mod.LAUNCHER_DIVERGENCE_HAND_REPLACED
LAUNCHER_DIVERGENCE_EDITED = _core_runtime_mod.LAUNCHER_DIVERGENCE_EDITED
_launcher_looks_generated = _core_runtime_mod._launcher_looks_generated
OPERATOR_LAUNCHER_MARKER = _core_runtime_mod.OPERATOR_LAUNCHER_MARKER
normalize_derived_artifacts = _core_runtime_mod.normalize_derived_artifacts
observability_state_dir = _core_runtime_mod.observability_state_dir
utc_event_timestamp = _core_runtime_mod.utc_event_timestamp
event_human_line = _core_runtime_mod.event_human_line
rotate_event_file = _core_runtime_mod.rotate_event_file
secure_event_log_paths = _core_runtime_mod.secure_event_log_paths
_lane_status_discard_artifact = _core_runtime_mod._lane_status_discard_artifact
EVENT_SEVERITIES = {"info", "ok", "warn", "block", "fail"}


# EVENT_LOG_SCHEMA, EVENT_START_SUFFIX, EVENT_REQUIRED_BOUNDARY_FAMILIES, EVENT_TERMINAL_SUFFIXES +
# the pure event_boundary_family decision core moved to tautline_methodology.core.policy; re-
# exported here as eager aliases so cli.<name> attribute reach and every in-bin reference keep
# resolving.
try:
    from tautline_methodology.core import policy as _core_policy_mod
except ModuleNotFoundError as exc:
    _core_policy_mod = _MissingFrameworkPackage(exc, "repo-event policy constants")  # type: ignore
EVENT_LOG_SCHEMA = _core_policy_mod.EVENT_LOG_SCHEMA
SESSION_JOURNAL_SECRET_PATTERNS = [
    r"github_pat_[A-Za-z0-9_]+",
    r"gh[pousr]_[A-Za-z0-9_]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"ASIA[0-9A-Z]{16}",
    r"xox[baprs]-[A-Za-z0-9-]{20,}",
    r"ATATT[A-Za-z0-9_-]{20,}",
    r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}",
]


def redact_secrets(text: str) -> str:
    return util_module().redact_secrets(text)


@contextmanager
def advisory_flock(lock_file):
    """Best-effort advisory exclusive lock around a body, portable across platforms (arch-errors-3).

    fcntl is POSIX-only; an unconditional `import fcntl` hard-crashes on Windows, contradicting the
    portability claim. This degrades gracefully: if fcntl is unavailable (non-POSIX) or the lock
    cannot be acquired, the body still runs WITHOUT advisory locking (acceptable for single-user
    non-POSIX use) instead of raising ImportError.
    """
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        fcntl = None  # type: ignore[assignment]
    if fcntl is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            fcntl = None  # type: ignore[assignment]
    try:
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def bootstrap_fail_command(field: str) -> str:
    return util_module().bootstrap_fail_command(field)


def title_from_slug(value: str) -> str:
    return util_module().title_from_slug(value)


def infer_repo_slug(target: Path) -> str:
    return gitutil_module().infer_repo_slug(target)


def normalize_repo_slug(value: str) -> str | None:
    return util_module().normalize_repo_slug(value)


def target_is_git_worktree(target: Path) -> bool:
    return gitutil_module().target_is_git_worktree(target)


def validate_adapter_repo_matches_target(data: dict, target: Path, require_target_identity: bool = False) -> None:
    expected = normalize_repo_slug(str(data.get("repo", "")))
    if not expected:
        return
    if not target_is_git_worktree(target):
        if require_target_identity:
            raise SystemExit(
                "Project adapter repo cannot be verified because the target is not a git worktree. "
                "Do not use another project's generated lane adapter; bootstrap or render the correct source "
                "adapter inside the project repo."
            )
        return
    actual_raw = infer_repo_slug(target)
    actual = normalize_repo_slug(actual_raw)
    if not actual:
        raise SystemExit(
            "Project adapter repo cannot be verified because the target git remote is missing or unparseable. "
            "Do not use another project's adapter; add the correct remote or bootstrap a local-only source adapter "
            "whose repo field explicitly documents the no-remote workflow."
        )
    if expected != actual:
        # Rebrand transition: the methodology repo's own new/legacy slugs are equivalent, so an
        # unconverted checkout (legacy origin URL) still starts under the updated self-adapter.
        methodology_slugs = {normalize_repo_slug(slug) for slug in methodology_repo_slugs()}
        if expected in methodology_slugs and actual in methodology_slugs:
            for candidate in (expected, actual):
                _warn_legacy_methodology_slug(candidate)
            return
        raise SystemExit(
            "Project adapter repo does not match the target git remote "
            f"({data.get('repo')} != {actual_raw}). Do not use another project's adapter; "
            "bootstrap or render the correct source adapter for this repo."
        )


def project_scaffold(project_name: str, repo_slug: str, schema_path: str) -> dict:
    project_slug = slugify(project_name)
    return {
        "$schema": schema_path,
        "_framework": {
            "channel": "stable",
            "version": "",
            "updatePolicy": "manual",
            "migrationPolicy": "dry-run",
        },
        "project": project_name,
        "repo": repo_slug,
        "productionDeployExists": True,
        "bootstrapEvidence": {
            "project": project_name,
            "status": "BOOTSTRAP REQUIRED: interviewed | repo-evident.",
            "summary": (
                "BOOTSTRAP REQUIRED: summarize repo-evident facts and human-operator answers used to choose "
                "project stack, gates, review flow, deployment posture, autonomy boundaries, and project rules."
            ),
            "interviewArtifact": {
                "path": DEFAULT_BOOTSTRAP_INTERVIEW_PATH,
                "sha256": "BOOTSTRAP REQUIRED: write the bootstrap interview artifact, answer it, and record its SHA256.",
            },
        },
        "backlogAdapter": (
            "BOOTSTRAP REQUIRED: inspect the project backlog, issue tracker, or docs and replace this with "
            "the lower-severity finding routing policy."
        ),
        "planningArtifacts": {
            "sourceOfTruth": "docs/ai/specs/",
            "template": "docs/ai/templates/pr-execution-spec.template.md",
            "templateTrigger": "Non-trivial, protected-category, infrastructure, customer-facing, or adapter-required PR work.",
            "reviewExemptions": DEFAULT_PLANNING_ARTIFACTS["reviewExemptions"],
            "scratchPaths": ["~/.claude/plans/"],
            "rule": (
                "BOOTSTRAP REQUIRED: replace with the project-specific plan/spec source-of-truth rule. "
                "Tool default plan paths remain scratch only."
            ),
        },
        "goalArtifacts": {
            "sourceOfTruth": "docs/ai/specs/goals",
            "template": "docs/ai/specs/goals/goal.template.md",
            "templateTrigger": DEFAULT_GOAL_ARTIFACTS["templateTrigger"],
            "reviewRequired": True,
        },
        "goalExecution": DEFAULT_GOAL_EXECUTION,
        "laneCoordination": DEFAULT_LANE_COORDINATION,
        "backlogProvider": DEFAULT_BACKLOG_PROVIDER,
        "goalTracker": DEFAULT_GOAL_TRACKER,
        "stakeholderQuestions": DEFAULT_STAKEHOLDER_QUESTIONS,
        "latestCode": DEFAULT_LATEST_CODE,
        "workProfiles": scaffold_work_profiles(),
        "commands": {
            **{field: bootstrap_fail_command(field) for field in REQUIRED_COMMANDS},
            "branchLivenessCheck": "tautline branch-liveness-check --target . --strict",
        },
        "localResourceIsolation": {
            **DEFAULT_LOCAL_RESOURCE_ISOLATION,
            "composeProjectPrefix": f"tautline-{project_slug}",
        },
        "review": {
            "codexWrapper": "BOOTSTRAP REQUIRED: configure the project Codex review wrapper or native review instruction.",
            "codexPlanWrapper": "BOOTSTRAP REQUIRED: configure the project Codex plan-review wrapper or native review instruction.",
            "claudeReview": "BOOTSTRAP REQUIRED: configure the project Claude review workflow.",
            "crossModelTiming": "before push",
        },
        "behaviorSpecs": {
            "required": False,
            "paths": [],
            "exemption": "BEHAVIOR-SPEC-EXEMPT: <reason>",
            "sourceMaterials": [],
            "sourceMaterialRule": (
                "If reviewed external/customer/business behavior specs are provided, review and adapt them before "
                "authoring new scenarios; preserve business intent and document deviations."
            ),
            "pendingTags": DEFAULT_BEHAVIOR_PENDING_TAGS,
            "inactiveAcceptanceEnforcement": "warn",
            "maxPendingScenarios": 0,
            "pendingRequiresOwnerAndTrigger": True,
            "acceptanceHarnesses": [],
            "roleVocabulary": {
                "allowed": [],
                "forbidden": [],
            },
        },
        "bugBacklog": {
            "sourceOfTruth": "BOOTSTRAP REQUIRED: configure the bug source of truth, such as backlog specs, GitHub issues, Jira, Linear, or another tracker.",
            "issueMirrors": [],
            "severityTaxonomy": "BOOTSTRAP REQUIRED: configure the project bug severity taxonomy.",
            "autoP0Categories": [],
            "autoP1Categories": [
                "auth",
                "email",
                "tenant data",
                "security",
                "deploy",
                "billing",
                "data loss",
                "customer-blocking",
            ],
            "requiredFields": DEFAULT_BUG_BACKLOG["requiredFields"],
            "rule": "BOOTSTRAP REQUIRED: configure when to write source-of-truth bug specs, when to open external issues, and when mirrors are optional.",
        },
        "technologyStack": DEFAULT_TECHNOLOGY_STACK,
        "graphify": DEFAULT_GRAPHIFY,
        # Day-one self-proving posture (rec #10): a NEW project blocks on the ci-test-gate from commit
        # one (warn-then-block migration -- the runtime DEFAULT stays warn so existing rendered adapters
        # are never silently wedged, the 0.6.115 lesson; new projects opt into block here). A repo with
        # no deploymentTargets is still a no-op until it declares a customer-facing surface.
        "ciTestGate": {
            "enabled": True,
            "enforcement": "block",
            "events": ["pull_request", "push"],
            "expectTests": True,
        },
        "uiEvidence": DEFAULT_UI_EVIDENCE,
        "deploymentTargets": DEFAULT_DEPLOYMENT_TARGETS,
        "continuity": {
            "path": ".ai-continuity/NEXT_SESSION.md",
            "archiveDir": ".ai-continuity/archive",
            "gitIgnore": True,
        },
        "laneState": DEFAULT_LANE_STATE,
        "milestoneContinuation": DEFAULT_MILESTONE_CONTINUATION,
        "sessionJournal": DEFAULT_SESSION_JOURNAL,
        "observabilityEvents": DEFAULT_OBSERVABILITY_EVENTS,
        "usageAccounting": DEFAULT_USAGE_ACCOUNTING,
        "iterationReview": DEFAULT_ITERATION_REVIEW,
        "milestoneUpdate": DEFAULT_MILESTONE_UPDATE,
        "productChat": DEFAULT_PRODUCT_CHAT,
        "deploymentNotification": DEFAULT_DEPLOYMENT_NOTIFICATION,
        "contextRotation": DEFAULT_CONTEXT_ROTATION,
        "readiness": {"sources": []},
        "knownProjectRules": [
            "BOOTSTRAP REQUIRED: replace with verified project-specific invariants or remove this item."
        ],
        "generatedFiles": ["CLAUDE.md", "AGENTS.md", LANE_ADAPTER_FILE],
    }


ADAPTER_BOOTSTRAP_QUESTIONS = _adapters_mod.ADAPTER_BOOTSTRAP_QUESTIONS


def trusted_source_adapter_roots() -> list[Path]:
    """Roots under which an adapter JSON is accepted as a canonical methodology source adapter.

    prod-onboarding-1: the framework's `adapters/projects/` is always trusted. An operator can
    designate ONE additional trusted root via MINERVIT_METHODOLOGY_ADAPTER_ROOT (e.g. a private
    `minervit-adapters` repo, or the adopter's own product repo) so the source adapter need NOT be
    committed into the framework repo. The root is operator-controlled (env), not attacker-supplied
    cwd discovery, so it does not widen the render trust boundary the way auto-adopting any
    lane-local JSON would. Adapters under the extra root still need real bootstrapEvidence
    (repo-evident/interviewed) and pass the same schema + identity checks.

    Canonical first (see methodology_data_roots): the private adapters this trust boundary exists
    for live in the canonical checkout's working tree, not in the snapshot we execute.
    """
    roots = [(root / "adapters/projects").resolve() for root in methodology_data_roots()]
    extra = util_module().resolve_env("MINERVIT_METHODOLOGY_ADAPTER_ROOT", "").strip()
    if extra:
        try:
            roots.append(Path(extra).expanduser().resolve())
        except OSError:
            pass
    return roots


def source_adapter_requires_bootstrap_evidence(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in trusted_source_adapter_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def repo_local_source_adapter_path(target: Path) -> Path:
    canonical = target / REPO_LOCAL_ADAPTER_FILE
    if canonical.exists():
        return canonical
    legacy = target / LEGACY_REPO_LOCAL_ADAPTER_FILE
    if legacy.exists():
        sunset_warning("markers", LEGACY_REPO_LOCAL_ADAPTER_FILE, REPO_LOCAL_ADAPTER_FILE)
        return legacy
    return canonical  # default write target


def is_repo_local_source_adapter(path: Path, target: Path) -> bool:
    try:
        resolved = path.resolve()
        return resolved in (
            (target / REPO_LOCAL_ADAPTER_FILE).resolve(),
            (target / LEGACY_REPO_LOCAL_ADAPTER_FILE).resolve(),
        )
    except OSError:
        return False


def source_adapter_allowed_for_target(path: Path, target: Path) -> bool:
    return source_adapter_requires_bootstrap_evidence(path) or is_repo_local_source_adapter(path, target)


def source_adapter_repo_relative_path(path: Path) -> str | None:
    resolved = path.resolve()
    for root in methodology_data_roots():
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return None


def source_adapter_legacy_allowlisted(path: Path, project_name: str) -> bool:
    rel = source_adapter_repo_relative_path(path)
    if not rel:
        return False
    for item in legacy_bootstrap_allowlist_entries():
        if item.get("path") == rel and item.get("project") == project_name:
            return True
    return False


def legacy_bootstrap_allowlist_entries() -> list[dict]:
    if not LEGACY_BOOTSTRAP_ALLOWLIST.is_file():
        return []
    try:
        payload = json.loads(LEGACY_BOOTSTRAP_ALLOWLIST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("adapters", []) if isinstance(item, dict)]


def legacy_bootstrap_project_allowlisted(project_name: str) -> bool:
    return any(item.get("project") == project_name for item in legacy_bootstrap_allowlist_entries())


bootstrap_slot_values = _adapters_mod.bootstrap_slot_values


def generic_bootstrap_slot_indexes(values: list[str]) -> list[int]:
    bad = []
    for index, value in enumerate(values, start=1):
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        if not normalized or normalized in GENERIC_BOOTSTRAP_SLOT_VALUES:
            bad.append(index)
    return bad


def validate_bootstrap_evidence_for_target(data: dict, project_path: Path, target: Path) -> None:
    evidence = data.get("bootstrapEvidence")
    if not isinstance(evidence, dict):
        return
    status = evidence.get("status")
    if status == "interviewed":
        artifact = evidence["interviewArtifact"]
        artifact_path = target / artifact["path"]
        if not artifact_path.is_file():
            raise SystemExit(f"Project adapter bootstrap interview artifact missing: {artifact_path}")
        artifact_path = resolve_bootstrap_target_path(target, artifact["path"], "interviewArtifact.path")
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        missing_sections = [
            title for title, _questions in ADAPTER_BOOTSTRAP_QUESTIONS if f"## {title}" not in text
        ]
        if missing_sections:
            raise SystemExit(
                "Project adapter bootstrap interview artifact is not the generated questionnaire; missing section(s): "
                + ", ".join(missing_sections)
            )
        project_header = extract_bootstrap_header(text, "Project")
        repo_header = extract_bootstrap_header(text, "Repository")
        if project_header != data["project"]:
            raise SystemExit(
                "Project adapter bootstrap interview artifact Project header does not match adapter project "
                f"({project_header or 'missing'} != {data['project']})"
            )
        if repo_header != data["repo"]:
            raise SystemExit(
                "Project adapter bootstrap interview artifact Repository header does not match adapter repo "
                f"({repo_header or 'missing'} != {data['repo']})"
            )
        if BOOTSTRAP_REQUIRED_PREFIX in text:
            raise SystemExit(
                f"Project adapter bootstrap interview artifact still contains {BOOTSTRAP_REQUIRED_PREFIX}: "
                f"{artifact_path}"
            )
        if "Answer:" not in text or "Evidence:" not in text:
            raise SystemExit(
                "Project adapter bootstrap interview artifact must contain answered `Answer:` and `Evidence:` slots"
            )
        expected_answers = sum(len(questions) for _title, questions in ADAPTER_BOOTSTRAP_QUESTIONS)
        answers = bootstrap_slot_values(text, "Answer")
        answer_evidence = bootstrap_slot_values(text, "Evidence")
        if len(answers) < expected_answers or len(answer_evidence) < expected_answers:
            raise SystemExit(
                "Project adapter bootstrap interview artifact must answer every generated question "
                f"({len(answers)} Answer slots, {len(answer_evidence)} Evidence slots, expected {expected_answers})"
            )
        bad_answers = generic_bootstrap_slot_indexes(answers)
        bad_evidence = generic_bootstrap_slot_indexes(answer_evidence)
        if bad_answers or bad_evidence:
            parts = []
            if bad_answers:
                parts.append("Answer slot(s) " + ", ".join(str(item) for item in bad_answers[:5]))
            if bad_evidence:
                parts.append("Evidence slot(s) " + ", ".join(str(item) for item in bad_evidence[:5]))
            raise SystemExit(
                "Project adapter bootstrap interview artifact contains generic slot value(s): "
                + "; ".join(parts)
            )
        actual_hash = file_sha256(artifact_path)
        if actual_hash != artifact["sha256"]:
            raise SystemExit(
                "Project adapter bootstrap interview artifact SHA256 mismatch; rerun the hash after editing "
                f"{artifact_path}"
            )
    elif status == "repo-evident":
        missing = []
        directories = []
        for item in evidence["repoEvidence"]:
            evidence_path = target / item["path"]
            if not evidence_path.exists():
                missing.append(item["path"])
                continue
            resolved = resolve_bootstrap_target_path(target, item["path"], "repoEvidence.path")
            if not resolved.is_file():
                directories.append(item["path"])
        if missing:
            raise SystemExit(
                "Project adapter bootstrap repoEvidence path(s) missing from target: " + ", ".join(missing)
            )
        if directories:
            raise SystemExit(
                "Project adapter bootstrap repoEvidence path(s) must be files, not directories: "
                + ", ".join(directories)
            )


def require_source_adapter_for_target(path: Path, target: Path, command: str) -> None:
    if source_adapter_allowed_for_target(path, target):
        return
    raise SystemExit(
        f"{command} requires --project to point at a trusted source adapter: "
        f"<methodology_repo>/adapters/projects/*.json, MINERVIT_METHODOLOGY_ADAPTER_ROOT, or {REPO_LOCAL_ADAPTER_FILE} "
        "inside the target repo. Do not use ad hoc, copied, or generated lane-local adapter JSON."
    )


def now_iso() -> str:
    return util_module().now_iso()


def warn_deprecated_command(cmd_name: str) -> None:
    # THE 0.120.0 ALIASES ARE WARNED BY THEIR PARSER, not here, and must not be warned twice.
    # Their entry in the map exists to publish the surface in `deprecatedSurfaces`; the runtime
    # notice is `deprecated_alias_notice`, which names the replacement AND the removal release
    # and is what the operator already sees. Emitting this generic line as well would print two
    # deprecation warnings for one invocation, with different removal wording.
    if cmd_name in RENAMED_COMMAND_ALIASES_0_120:
        return
    replacement = DEPRECATED_COMMAND_REPLACEMENTS.get(cmd_name)
    if not replacement:
        return
    print(
        f"deprecation_warning: command '{cmd_name}' is deprecated; use '{replacement}'. "
        "This warning does not change the command exit code and the command will not be removed before the next major release.",
        file=sys.stderr,
    )


# --- Compat-sunset shared warning renderer (roadmap #16) ---------------------------------------
_SUNSET_EMITTED_FALLBACK: set[tuple[str, str]] = set()


def sunset_warning(family: str, legacy: str, replacement: str) -> None:
    """Emit the shared once-only compat-sunset line (fixed shape, stderr-only, exit/stdout
    unchanged) naming a concrete legacy surface + its tautline replacement + the 1.0 removal.

    Delegates to the util twin so bin and util share ONE emitted-set + suppression decision + shell
    handoff seed (util cannot import bin). Falls back to a minimal bin-local emit ONLY when the util
    package is unavailable (a standalone bin copy, per the hook fail-open contract)."""
    try:
        util = util_module()
    except SystemExit:
        _sunset_warning_fallback(family, legacy, replacement)
        return
    util._sunset_warning(family, legacy, replacement)


def _sunset_warning_fallback(family: str, legacy: str, replacement: str) -> None:
    """Degraded standalone-bin path: a bin-local dedup + a direct both-spelling suppression read.
    Normal operation always routes through util so cross-layer double-warns cannot happen here.

    Hook-shaped invocations (a `--hook` flag, or a first non-flag verb ending in `-hook`) are
    byte-silent BEFORE any dedup/emit -- total containment, mirroring util._sunset_warning and the
    cli chokepoint's inline guard so the standalone-bin path never leaks into a session."""
    argv = sys.argv[1:]
    if "--hook" in argv or next((t for t in argv if not t.startswith("-")), "").endswith("-hook"):
        return
    key = (family, legacy)
    if key in _SUNSET_EMITTED_FALLBACK:
        return
    # TAUTLINE-first-nonblank-else-legacy, matching util._sunset_suppress_value and the shell `:-`
    # form: a set, non-blank TAUTLINE_ value wins; a blank/whitespace-only one falls through.
    taut = os.environ.get(SUPPRESS_SUNSET_WARNINGS_ENV)
    if taut is not None and taut.strip() != "":
        suppress = taut
    else:
        suppress = os.environ.get(SUPPRESS_SUNSET_WARNINGS_LEGACY_ENV)
    if suppress and suppress.strip() not in ("", "0"):
        return
    _SUNSET_EMITTED_FALLBACK.add(key)
    print(
        f"deprecation_warning: {legacy} is deprecated and will be removed in 1.0; "
        f"use {replacement}",
        file=sys.stderr,
    )


def _consume_legacy_launcher_marker() -> None:
    """Chokepoint 2 (cli): warn once on a legacy-CLI-name invocation, then strip the marker so child
    re-execs never double-warn. The marker survives the argv0-rewriting exec hops; argv0 basename is
    a residual fallback for a direct legacy-named invocation that skips a hop. Hook-shaped
    invocations (a `--hook` flag, or a first non-flag verb ending in `-hook`) strip SILENTLY --
    total containment before any warning can fire."""
    invoked = os.environ.pop(LEGACY_LAUNCHER_INVOKED_ENV, None)
    if not invoked and os.path.basename(sys.argv[0] or "") == LEGACY_CLI_NAME:
        invoked = LEGACY_CLI_NAME
    if not invoked:
        return
    argv = sys.argv[1:]
    if "--hook" in argv or next((t for t in argv if not t.startswith("-")), "").endswith("-hook"):
        return
    sunset_warning("cli", LEGACY_CLI_NAME, CLI_NAME)


def _warn_legacy_methodology_slug(slug: str) -> None:
    """Chokepoint 4 (slug): warn when an adapter/config `repo` is accepted via a pre-rebrand
    minervit methodology slug, naming the canonical tautlines slug replacement."""
    normalized = str(slug or "").strip().lower()
    if normalized and normalized in {s.lower() for s in LEGACY_METHODOLOGY_REPO_SLUGS}:
        sunset_warning("slug", normalized, METHODOLOGY_REPO_SLUG)


def normalize_framework_pin(raw: object, source: str = "framework pin") -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit(f"{source} must be an object")
    pin = {**DEFAULT_FRAMEWORK_PIN, **raw}
    channel = str(pin.get("channel") or DEFAULT_FRAMEWORK_PIN["channel"]).strip()
    if channel not in CLIENT_FRAMEWORK_CHANNELS:
        raise SystemExit(f"{source}.channel must be stable or experimental")
    update_policy = str(pin.get("updatePolicy") or DEFAULT_FRAMEWORK_PIN["updatePolicy"]).strip()
    if update_policy not in FRAMEWORK_UPDATE_POLICIES:
        raise SystemExit(f"{source}.updatePolicy must be one of: {', '.join(sorted(FRAMEWORK_UPDATE_POLICIES))}")
    migration_policy = str(pin.get("migrationPolicy") or DEFAULT_FRAMEWORK_PIN["migrationPolicy"]).strip()
    if migration_policy not in FRAMEWORK_MIGRATION_POLICIES:
        raise SystemExit(
            f"{source}.migrationPolicy must be one of: {', '.join(sorted(FRAMEWORK_MIGRATION_POLICIES))}"
        )
    version = str(pin.get("version") or "").strip()
    if version and not re.fullmatch(r"(?:[~^<>]=?)?[0-9]+(?:\.[0-9]+){1,2}(?:[-+][0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"{source}.version must be an exact semver or simple semver range")
    return {
        "channel": channel,
        "version": version,
        "updatePolicy": update_policy,
        "migrationPolicy": migration_policy,
    }


def default_work_profile(profile: str) -> dict:
    return json.loads(json.dumps(DEFAULT_WORK_PROFILES["profiles"][profile]))


def scaffold_work_profiles() -> dict:
    profiles = json.loads(json.dumps(DEFAULT_WORK_PROFILES))
    if profiles.get("prePushBase") is None:
        profiles.pop("prePushBase", None)
    return profiles


def normalize_single_work_profile(profile: str, raw: object, source: str) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit(f"{source} must be an object")
    allowed_keys = {
        "description",
        "allowedPaths",
        "additionalAllowedPaths",
        "allowedExtensions",
        "additionalAllowedExtensions",
        "blockedPaths",
        "additionalBlockedPaths",
        "maxFileBytes",
        "pushPolicy",
    }
    unknown_keys = sorted(set(raw) - allowed_keys)
    if unknown_keys:
        raise SystemExit(f"{source} contains unknown key(s): {', '.join(unknown_keys)}")
    base = default_work_profile(profile)
    merged = {**base, **{key: value for key, value in raw.items() if not key.startswith("additional")}}
    description = str(merged.get("description", "")).strip()
    if not description:
        raise SystemExit(f"{source}.description must be non-blank")
    push_policy = str(merged.get("pushPolicy", "pr-branch-only")).strip()
    if push_policy not in WORK_PROFILE_PUSH_POLICIES:
        raise SystemExit(f"{source}.pushPolicy must be one of: {', '.join(sorted(WORK_PROFILE_PUSH_POLICIES))}")
    try:
        max_file_bytes = int(merged.get("maxFileBytes", 0))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{source}.maxFileBytes must be a non-negative integer") from exc
    if max_file_bytes < 0:
        raise SystemExit(f"{source}.maxFileBytes must be a non-negative integer")
    allowed_paths = normalize_profile_string_list(merged.get("allowedPaths", []), f"{source}.allowedPaths")
    allowed_paths.extend(
        normalize_profile_string_list(raw.get("additionalAllowedPaths", []), f"{source}.additionalAllowedPaths")
    )
    allowed_extensions = normalize_profile_string_list(
        merged.get("allowedExtensions", []), f"{source}.allowedExtensions", extensions=True
    )
    allowed_extensions.extend(
        normalize_profile_string_list(
            raw.get("additionalAllowedExtensions", []),
            f"{source}.additionalAllowedExtensions",
            extensions=True,
        )
    )
    blocked_paths = normalize_profile_string_list(merged.get("blockedPaths", []), f"{source}.blockedPaths")
    blocked_paths.extend(
        normalize_profile_string_list(raw.get("additionalBlockedPaths", []), f"{source}.additionalBlockedPaths")
    )
    if profile in NON_DEV_WORK_PROFILES and (not allowed_paths or not allowed_extensions):
        raise SystemExit(f"{source} must declare allowedPaths and allowedExtensions")
    return {
        "description": description,
        "allowedPaths": [value for value in dict.fromkeys(allowed_paths) if value],
        "allowedExtensions": [value for value in dict.fromkeys(allowed_extensions) if value],
        "blockedPaths": [value for value in dict.fromkeys(blocked_paths) if value],
        "maxFileBytes": max_file_bytes,
        "pushPolicy": push_policy,
    }


def normalize_work_profiles(raw: object) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("Project adapter workProfiles must be an object")
    allowed_keys = {"enabled", "defaultProfile", "profileLockPath", "prePushBase", "profiles"}
    unknown_keys = sorted(set(raw) - allowed_keys)
    if unknown_keys:
        raise SystemExit(f"Project adapter workProfiles contains unknown key(s): {', '.join(unknown_keys)}")
    cfg = {**DEFAULT_WORK_PROFILES, **{key: value for key, value in raw.items() if key != "profiles"}}
    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit("Project adapter workProfiles.enabled must be boolean")
    default_profile = str(cfg.get("defaultProfile", "development")).strip()
    if default_profile not in WORK_PROFILE_CHOICES:
        raise SystemExit("Project adapter workProfiles.defaultProfile must be development, product-docs, or support-docs")
    if default_profile != "development":
        raise SystemExit(
            "Project adapter workProfiles.defaultProfile must remain development; use "
            "`tautline lane-start --profile <profile>` for explicit non-dev sessions"
        )
    profile_lock_path = normalize_profile_path(
        str(cfg.get("profileLockPath", DEFAULT_WORK_PROFILE_LOCK_PATH)),
        "Project adapter workProfiles.profileLockPath",
    )
    pre_push_base_raw = cfg.get("prePushBase")
    pre_push_base = None if pre_push_base_raw is None else str(pre_push_base_raw).strip()
    if pre_push_base == "":
        raise SystemExit("Project adapter workProfiles.prePushBase must be non-blank when set")
    raw_profiles = raw.get("profiles", {})
    if raw_profiles is None:
        raw_profiles = {}
    if not isinstance(raw_profiles, dict):
        raise SystemExit("Project adapter workProfiles.profiles must be an object")
    unknown_profiles = sorted(set(raw_profiles) - WORK_PROFILE_CHOICES)
    if unknown_profiles:
        raise SystemExit(
            "Project adapter workProfiles.profiles contains unsupported profile(s): "
            + ", ".join(unknown_profiles)
        )
    profiles = {
        profile: normalize_single_work_profile(
            profile,
            raw_profiles.get(profile, {}),
            f"Project adapter workProfiles.profiles.{profile}",
        )
        for profile in sorted(WORK_PROFILE_CHOICES)
    }
    normalized = {
        "enabled": bool(cfg["enabled"]),
        "defaultProfile": default_profile,
        "profileLockPath": profile_lock_path,
        "profiles": profiles,
    }
    if pre_push_base is not None:
        normalized["prePushBase"] = pre_push_base
    return normalized


def framework_pin_path(target: Path) -> Path:
    return target / FRAMEWORK_PIN_FILE


def legacy_framework_pin_path(target: Path) -> Path:
    return target / LEGACY_FRAMEWORK_PIN_FILE


def load_framework_pin_file(target: Path) -> dict | None:
    # Write-new/read-both: prefer the canonical .tautline/pin.json, fall back to the legacy
    # .minervit/pin.json, and migrate the legacy file onto the canonical path on read so a lane
    # re-pins itself once and stays on the new path thereafter (deprecation window).
    path = framework_pin_path(target)
    legacy = legacy_framework_pin_path(target)
    read_path = path if path.exists() else (legacy if legacy.exists() else None)
    if read_path is None:
        return None
    try:
        text = read_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"framework pin file is not valid JSON: {read_path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"framework pin file is unreadable: {read_path}: {exc}") from exc
    # Validate BEFORE migrating: normalize_framework_pin raises on an invalid pin (e.g. a bad
    # channel), so a malformed legacy pin must never be materialized onto the canonical path -- the
    # canonical copy would then win every future read and hide a fix to the legacy file.
    normalized = normalize_framework_pin(payload, str(read_path))
    if read_path == legacy and not path.exists():
        try:
            write_text_atomic(path, text)  # one-time migration; best-effort on read-only checkouts
        except OSError:
            pass
    return normalized


def effective_framework_pin(data: dict, target: Path) -> tuple[dict, str]:
    adapter_pin = normalize_framework_pin(data.get("_framework"), "Project adapter _framework")
    file_pin = load_framework_pin_file(target)
    if file_pin is None:
        return adapter_pin, "adapter"
    return {**adapter_pin, **file_pin}, FRAMEWORK_PIN_FILE


def framework_channel_branch(channel: str) -> str:
    return FRAMEWORK_CHANNEL_BRANCHES.get(channel, "main")


def semver_change_kind(current: str, available: str) -> str:
    current_parts = version_tuple(current)
    available_parts = version_tuple(available)
    current_major = current_parts[0] if len(current_parts) > 0 else 0
    current_minor = current_parts[1] if len(current_parts) > 1 else 0
    current_patch = current_parts[2] if len(current_parts) > 2 else 0
    available_major = available_parts[0] if len(available_parts) > 0 else 0
    available_minor = available_parts[1] if len(available_parts) > 1 else 0
    available_patch = available_parts[2] if len(available_parts) > 2 else 0
    if (available_major, available_minor, available_patch) <= (current_major, current_minor, current_patch):
        return "none"
    if available_major != current_major:
        return "major"
    if available_minor != current_minor:
        return "minor"
    return "patch"


def active_framework_wip_reasons(data: dict, target: Path) -> list[str]:
    """Work-in-progress signals that defer an automatic framework update.

    Process-bankruptcy demolition (2026-08-28): the goal ledger, milestone ledger, execution
    packet and running-review-evidence markers this used to consult were deleted along with the
    machinery that wrote them, so consulting them would only ever report "no work in progress".
    Standing on a feature branch is the one WIP signal a lean lane still has, and it is the one
    that mattered: it is what keeps an update from landing mid-change.
    """
    branch = run_git(target, ["branch", "--show-current"])
    if branch not in ("", "unavailable", "main", "master"):
        return [f"active branch {branch}"]
    return []


def framework_available_version(pin: dict) -> str:
    env_version = util_module().resolve_env("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", "").strip()
    if env_version:
        return env_version
    version = pin.get("version", "")
    if version and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}(?:[-+][0-9A-Za-z.-]+)?", version):
        return version
    return plugin_version()


def framework_update_decision(
    pin: dict,
    data: dict,
    target: Path,
    skip_update: bool = False,
    manual_request: bool = False,
) -> dict:
    if skip_update:
        return {"action": "skip", "reason": "--skip-update requested", "wipReasons": []}
    current = plugin_version()
    available = framework_available_version(pin)
    change_kind = semver_change_kind(current, available)
    wip_reasons = active_framework_wip_reasons(data, target)
    if adapter_is_methodology_repo(data):
        return {
            "action": "skip",
            "reason": "methodology-dev invocation uses the current checkout without auto-update",
            "wipReasons": wip_reasons,
            "availableVersion": available,
            "changeKind": change_kind,
        }
    if pin["updatePolicy"] == "manual" and not manual_request:
        return {
            "action": "skip",
            "reason": "framework updatePolicy=manual; run sync-methodology intentionally at a safe boundary",
            "wipReasons": wip_reasons,
            "availableVersion": available,
            "changeKind": change_kind,
        }
    if pin["channel"] == "stable" and methodology_update_policy() not in {"signed", "pinned"}:
        return {
            "action": "skip",
            "reason": "stable channel refuses raw main updates without signed or pinned update trust",
            "wipReasons": wip_reasons,
            "availableVersion": available,
            "changeKind": change_kind,
        }
    if wip_reasons and change_kind in {"minor", "major"}:
        return {
            "action": "skip",
            "reason": f"active work blocks automatic {change_kind} framework upgrade",
            "wipReasons": wip_reasons,
            "availableVersion": available,
            "changeKind": change_kind,
        }
    if wip_reasons and change_kind == "patch":
        report = load_release_migration_report(available)
        if not (isinstance(report, dict) and report.get("wipSafe") is True):
            return {
                "action": "skip",
                "reason": "active work allows patch auto-update only when the release migration report declares wipSafe=true",
                "wipReasons": wip_reasons,
                "availableVersion": available,
                "changeKind": change_kind,
            }
    if pin["updatePolicy"] == "minor-at-boundary" and wip_reasons:
        return {
            "action": "skip",
            "reason": "minor-at-boundary update waits until no goal, milestone, packet, review, or branch work is active",
            "wipReasons": wip_reasons,
            "availableVersion": available,
            "changeKind": change_kind,
        }
    return {
        "action": "update",
        "reason": f"{pin['channel']} channel {pin['updatePolicy']} permits {change_kind} update",
        "wipReasons": wip_reasons,
        "availableVersion": available,
        "changeKind": change_kind,
    }


# --- Update probe (display-only discovery; never feeds framework_update_decision) ---------------
#
# framework_update_probe answers "what release is genuinely available for this pin's channel", for
# the session-start surfaces (T2) to PRINT -- it is deliberately isolated from
# framework_available_version / framework_update_decision (which stay byte-identical), because
# feeding probe data into the decision would flip WIP/wipSafe policy branches. Fail-open is a hard
# invariant: any failure returns a benign dict, never raises, never blocks launch beyond the 5s
# ls-remote bound.
#
# The result "source" distinguishes two probe-absent cases the surface must route oppositely:
#   "none"   -> STOOD DOWN without attempting any remote query (knob/maintainer/methodology-dev/
#               no-remote/installed-package); the surface uses today's remote_methodology_status.
#   "failed" -> ATTEMPTED and the ls-remote query itself failed (offline/timeout); the surface
#               renders the unreachable-remote wording from failureDetail with no second query.
# Once the remote sha is known, EVERY downstream shortfall (object not local under allow_fetch=
# False; a fetch that fails; a VERSION missing/unreadable/unparsable) degrades to a sha-only
# result (source:"git", availableVersion=None) -- a metadata failure NEVER sets source:"failed".


def _update_probe_enabled() -> bool:
    """The knob is opt-OUT: unset means enabled; a falsey value in either spelling disables it."""
    value = util_module().resolve_env(METHODOLOGY_UPDATE_PROBE_ENV).strip().lower()
    return value not in METHODOLOGY_UPDATE_PROBE_OFF_VALUES


def _update_probe_cache_path() -> Path:
    return Path.home() / METHODOLOGY_UPDATE_PROBE_CACHE_REL


def _read_update_probe_cache(key: str, ttl_seconds: int) -> dict | None:
    """A fresh discovery entry for `key`, or None on miss/expiry. Corrupt cache => miss."""
    try:
        raw = json.loads(_update_probe_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get(key), dict):
        return None
    entry = raw[key]
    recorded = _update_probe_parse_iso(entry.get("probedAt"))
    if recorded is None:
        return None
    age = (datetime.now(timezone.utc) - recorded).total_seconds()
    if age < 0 or age > ttl_seconds:
        return None
    return entry


def _write_update_probe_cache(key: str, discovery: dict) -> None:
    """Best-effort discovery write (availableVersion/availableSha/probedAt only). Fail-open."""
    path = _update_probe_cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw[key] = discovery
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        util_module().write_text_atomic(path, json.dumps(raw, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass  # the cache is an optimization; a write failure costs one extra probe next time


def _update_probe_cache_key(canonical: Path, remote: str, branch: str) -> str:
    """Cache key = runtime kind + remote/branch + the remote's URL identity.

    The URL is hashed into the key so two canonical checkouts under one HOME that both have an
    'origin/<branch>' pointing at DIFFERENT remotes never share a discovery entry -- otherwise one
    checkout's fresh cache would silence the other's ls-remote and report a sha/version that its
    own remote does not carry. The cache FILE location is unchanged; only the key is qualified."""
    url = run_git(canonical, ["remote", "get-url", remote])
    identity = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"git:{remote}/{branch}:{identity}"


def _update_probe_head(canonical: Path) -> str | None:
    code, out, _ = run_command(["git", "-C", str(canonical), "rev-parse", "HEAD"])
    return out.strip() if code == 0 and out.strip() else None


def _update_probe_ls_remote(
    canonical: Path, remote: str, branch: str
) -> tuple[str | None, str | None]:
    """The upstream branch sha, else (None, failure_detail). failure_detail is git's OWN ls-remote
    stderr composed exactly as remote_methodology_status does (`stderr or stdout or 'remote query
    failed'`), so the launch surface renders byte-identical unreachable-remote output from this one
    query with no second remote call."""
    code, out, err = run_command(
        ["git", "-C", str(canonical), "ls-remote", remote, f"refs/heads/{branch}"],
        timeout=METHODOLOGY_UPDATE_PROBE_LS_REMOTE_TIMEOUT,
    )
    if code != 0 or not out:
        return None, (err or out or "remote query failed")
    return out.split()[0], None


def _update_probe_object_is_local(canonical: Path, sha: str) -> bool:
    code, _, _ = run_command(
        ["git", "-C", str(canonical), "cat-file", "-e", f"{sha}^{{commit}}"]
    )
    return code == 0


def _update_probe_fetch(canonical: Path, remote: str, branch: str) -> bool:
    """The ONLY repo mutation this feature makes, and only under allow_fetch=True. Writes the
    objects, FETCH_HEAD, and a DISPOSABLE refs/tautline-update-probe/<branch> ref -- never HEAD,
    the index, the working tree, or the branch's remote-tracking ref, so currency stays HEAD-based
    and the offer can never be masked."""
    ref = f"refs/tautline-update-probe/{branch}"
    code, _, _ = run_command(
        ["git", "-C", str(canonical), "fetch", remote, f"refs/heads/{branch}:{ref}", "--no-tags"],
        timeout=METHODOLOGY_UPDATE_PROBE_FETCH_TIMEOUT,
    )
    return code == 0


def _update_probe_version_at(canonical: Path, sha: str) -> str | None:
    """Parse VERSION at `sha` from a LOCAL object; None if missing/unreadable/unparsable."""
    code, out, _ = run_command(["git", "-C", str(canonical), "show", f"{sha}:VERSION"])
    if code != 0:
        return None
    version = out.strip()
    if version and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}(?:[-+][0-9A-Za-z.-]+)?", version):
        return version
    return None


def _update_probe_from_cache(discovery: dict, canonical: Path, probed_at: str) -> dict:
    """Recompute isNewer/changeKind from a cached DISCOVERY against CURRENT running version and
    canonical HEAD -- never trusting a stored isNewer, so accepting an update silences the offer."""
    available_version = discovery.get("availableVersion")
    available_sha = discovery.get("availableSha")
    running = plugin_version()
    head = _update_probe_head(canonical)
    if available_sha is not None and available_sha == head:
        return _update_probe_result(
            available_version, available_sha, "none", False, "cache", None, probed_at
        )
    if available_version:
        change_kind = semver_change_kind(running, available_version)
        is_newer = version_tuple(available_version) > version_tuple(running)
        return _update_probe_result(
            available_version, available_sha, change_kind, is_newer, "cache", None, probed_at
        )
    return _update_probe_result(None, available_sha, "none", False, "cache", None, probed_at)


def _update_probe_git(pin: dict, allow_fetch: bool, probed_at: str) -> dict:
    canonical = canonical_methodology_repo()
    # Resolve the remote+branch EXACTLY as update_methodology_repo will (via
    # methodology_release_upstream: prefer origin/<channel>, else the @{u} tracking ref when it
    # matches the channel branch), so the probe reports a version the eventual sync will actually
    # take. A checkout whose branch tracks a NON-origin remote must still probe origin's release.
    upstream = methodology_release_upstream(pin["channel"])
    if upstream is None:
        # No release remote resolvable (no origin, and @{u} does not match the channel branch): the
        # sync itself has nothing to fetch, so stand down and let the surface fall back to
        # remote_methodology_status's own "no upstream configured" wording (byte-identical).
        return _update_probe_result(None, None, "none", False, "none", None, probed_at)
    remote, branch, _ref = upstream
    cache_key = _update_probe_cache_key(canonical, remote, branch)
    cached = _read_update_probe_cache(cache_key, methodology_sync_freshness_seconds())
    if cached is not None:
        # A sha-only entry satisfies an allow_fetch=False caller, but an allow_fetch=True caller
        # treats it as a MISS -- it fetches and rewrites the entry complete below.
        if cached.get("availableVersion") is not None or not allow_fetch:
            return _update_probe_from_cache(cached, canonical, probed_at)
    remote_sha, ls_remote_detail = _update_probe_ls_remote(canonical, remote, branch)
    if remote_sha is None:
        # failureDetail carries git's own ls-remote stderr so the surface reproduces today's
        # remote_methodology_status unreachable line byte-for-byte with no second query.
        return _update_probe_result(
            None, None, "none", False, "failed", ls_remote_detail, probed_at
        )
    running = plugin_version()
    if remote_sha == _update_probe_head(canonical):
        discovery = {"availableVersion": running, "availableSha": remote_sha, "probedAt": probed_at}
        _write_update_probe_cache(cache_key, discovery)
        return _update_probe_result(running, remote_sha, "none", False, "git", None, probed_at)
    # Currency is judged against HEAD only; read VERSION at the remote sha when the object is local,
    # else fetch it into the disposable ref (allow_fetch only). Every shortfall => sha-only degrade.
    version: str | None = None
    if _update_probe_object_is_local(canonical, remote_sha):
        version = _update_probe_version_at(canonical, remote_sha)
    elif allow_fetch and _update_probe_fetch(canonical, remote, branch):
        version = _update_probe_version_at(canonical, remote_sha)
    if version is None:
        discovery = {"availableVersion": None, "availableSha": remote_sha, "probedAt": probed_at}
        _write_update_probe_cache(cache_key, discovery)
        return _update_probe_result(None, remote_sha, "none", False, "git", None, probed_at)
    change_kind = semver_change_kind(running, version)
    is_newer = version_tuple(version) > version_tuple(running)
    discovery = {"availableVersion": version, "availableSha": remote_sha, "probedAt": probed_at}
    _write_update_probe_cache(cache_key, discovery)
    return _update_probe_result(version, remote_sha, change_kind, is_newer, "git", None, probed_at)


def _update_probe_pypi_version() -> str | None:
    """The latest tautline release version from PyPI's JSON API, or None on ANY failure.

    Fail-open is total: urlopen/URLError/HTTPError/timeout, a non-JSON body, a missing
    info.version, or an unparsable version all return None so package-mode session-start output
    stays byte-identical to today's. NO exception escapes and NO git subprocess runs -- one
    anonymous HTTPS GET hard-bounded at 3s.
    """
    try:
        with urlopen(
            METHODOLOGY_UPDATE_PROBE_PYPI_URL,
            timeout=METHODOLOGY_UPDATE_PROBE_PYPI_TIMEOUT,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    if not isinstance(version, str):
        return None
    version = version.strip()
    if version and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}(?:[-+][0-9A-Za-z.-]+)?", version):
        return version
    return None


def _update_probe_package_result(version: str, probed_at: str) -> dict:
    """A source:"package" result recomputing isNewer/changeKind against CURRENT plugin_version --
    never trusting a cached isNewer, and never touching git (no HEAD to read in a wheel). Package
    results carry no availableSha, so framework_remote_status_from_probe returns None for them and
    the surface keeps today's installed-package remote-status wording."""
    running = plugin_version()
    change_kind = semver_change_kind(running, version)
    is_newer = version_tuple(version) > version_tuple(running)
    return _update_probe_result(version, None, change_kind, is_newer, "package", None, probed_at)


def _update_probe_package_failure_fresh(entry: dict) -> bool:
    """True for a cached FAILURE marker still within the (shorter) negative TTL. A fresh failure
    stands the probe down WITHOUT re-attempting the urlopen, so an offline wheel does not retry the
    3s GET on every session-start command; once it ages past the negative TTL the probe retries and
    a recovered PyPI is seen within the hour."""
    if not entry.get("probeFailed"):
        return False
    recorded = _update_probe_parse_iso(entry.get("probedAt"))
    if recorded is None:
        return False
    age = (datetime.now(timezone.utc) - recorded).total_seconds()
    return 0 <= age <= METHODOLOGY_UPDATE_PROBE_PACKAGE_FAIL_TTL


def _update_probe_package(probed_at: str) -> dict:
    """Installed-package (PyPI) discovery, replacing PR-1's full package standdown. A fresh 24h
    SUCCESS cache entry skips the urlopen; a fresh (1h) FAILURE marker stands down WITHOUT retrying
    the network; otherwise a GET to pypi.org (3s) refreshes the entry. ANY failure fails open to a
    FULL standdown (source:"none") so the output is byte-identical to today's installed-package
    session start -- the surface then renders the installed-package remote-status wording via
    remote_methodology_status. NO git subprocess ever runs on this path.

    Cache-entry shape distinguishes the two outcomes under the one `pypi:tautline` key: a SUCCESS
    carries a truthy `availableVersion` (24h TTL); a FAILURE carries `availableVersion: None` plus
    `probeFailed: True` (1h negative TTL). A fresh SUCCESS is checked FIRST and short-circuits the
    network entirely, so a later transient failure never clobbers a valid discovery within its
    window. A corrupt/absent entry is a miss (retry)."""
    cached = _read_update_probe_cache(
        METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY, METHODOLOGY_UPDATE_PROBE_PACKAGE_TTL
    )
    if cached is not None:
        if cached.get("availableVersion"):
            return _update_probe_package_result(cached["availableVersion"], probed_at)
        if _update_probe_package_failure_fresh(cached):
            return _update_probe_result(None, None, "none", False, "none", None, probed_at)
    version = _update_probe_pypi_version()
    if version is None:
        # Fail-open, but record a negative marker so subsequent launches within the negative TTL
        # stand down without re-attempting the GET. The write is best-effort (never raises).
        _write_update_probe_cache(
            METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY,
            {"availableVersion": None, "availableSha": None, "probeFailed": True,
             "probedAt": probed_at},
        )
        return _update_probe_result(None, None, "none", False, "none", None, probed_at)
    _write_update_probe_cache(
        METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY,
        {"availableVersion": version, "availableSha": None, "probedAt": probed_at},
    )
    return _update_probe_package_result(version, probed_at)


def framework_update_probe(
    target: Path,
    project_data: dict,
    pin: dict,
    allow_fetch: bool,
    no_remote: bool,
) -> dict:
    """Discover the genuinely-available framework version for `pin`'s channel (display-only).

    `target` is part of the stable surface signature (T2 passes the lane repo) but git discovery
    keys on canonical_methodology_repo(); it is unused here. Standdown ladder (each => source
    "none", never attempted a remote query): knob off (either spelling), armed maintainer mode,
    methodology-dev repo, no_remote (FULL standdown -- byte-identical --no-remote output even with
    a fresh cache). An installed-package runtime is NOT a standdown: it takes the PyPI branch (24h
    cache, 3s GET, fail-open to source "none", zero git subprocesses) BEFORE the env override, so a
    knob-off/maintainer/no_remote package launch still stands down first and the PyPI GET only runs
    when none of those fired. An MINERVIT_METHODOLOGY_AVAILABLE_VERSION override (checked AFTER the
    standdowns AND the package branch, so it can never change --no-remote output) returns source
    "env".
    """
    del target  # signature-stable; git discovery uses canonical_methodology_repo()
    probed_at = datetime.now(timezone.utc).isoformat()
    stood_down = _update_probe_result(None, None, "none", False, "none", None, probed_at)
    if not _update_probe_enabled():
        return stood_down
    if maintainer_mode_armed():
        return stood_down
    if adapter_is_methodology_repo(project_data):
        return stood_down
    if no_remote:
        return stood_down
    if running_from_installed_package():
        return _update_probe_package(probed_at)
    env_version = util_module().resolve_env("MINERVIT_METHODOLOGY_AVAILABLE_VERSION").strip()
    if env_version:
        running = plugin_version()
        change_kind = semver_change_kind(running, env_version)
        is_newer = version_tuple(env_version) > version_tuple(running)
        return _update_probe_result(
            env_version, None, change_kind, is_newer, "env", None, probed_at
        )
    return _update_probe_git(pin, allow_fetch, probed_at)


def framework_update_available_line(decision: dict, probe: dict) -> str:
    """The SINGLE framework_update_available line for a surface (display-only). Probe-truthful when
    the probe found a genuinely newer release; otherwise byte-identical to the pre-probe line, which
    is derived from the (untouched) framework_update_decision."""
    if probe.get("isNewer") and probe.get("availableVersion"):
        return (
            f"framework_update_available: version={probe['availableVersion']} "
            f"change={probe.get('changeKind', 'unknown')} (running {plugin_version()})"
        )
    return (
        "framework_update_available: "
        f"version={decision.get('availableVersion', plugin_version())} "
        f"change={decision.get('changeKind', 'unknown')}"
    )


def framework_remote_status_from_probe(probe: dict) -> str | None:
    """Render a launch surface's remote_status/framework_remote_status line FROM the probe result so
    the launch runs at most one ls-remote total. Returns None when the probe stood down or did not
    resolve git remote status (source none/env); the caller then falls back to
    remote_methodology_status. A failed probe renders the unreachable-remote wording from its own
    outcome (no second remote query); a known-sha result reuses the up-to-date/remote-differs
    vocabulary judged against HEAD, exactly as remote_methodology_status would.

    A source:"package" (PyPI) result NEVER feeds this line: git sha vocabulary must not render for
    a wheel, so this returns None and the caller keeps today's installed-package wording via
    remote_methodology_status (Design v5 Package-mode remote-status rule)."""
    source = probe.get("source")
    if source == "package":
        return None
    if source == "failed":
        return f"unavailable: {probe.get('failureDetail') or 'remote query failed'}"
    sha = probe.get("availableSha")
    if source in {"git", "cache"} and sha:
        head = _update_probe_head(canonical_methodology_repo())
        return "up to date" if sha == head else f"remote differs {sha[:12]}"
    return None


def _framework_update_candidate_pinned(sha: str | None) -> bool:
    """Mirror verify_upstream_trust's allowlist test: is `sha` already pinned (directly, or via a
    pin that resolves to it)? A pinned-policy candidate that is already pinned syncs directly."""
    if not sha:
        return False
    pins = _methodology_update_pins()
    if sha in pins:
        return True
    canonical = canonical_methodology_repo()
    return any(
        run_git(canonical, ["rev-parse", "--verify", f"{pin}^{{commit}}"]) == sha for pin in pins
    )


def _framework_update_version_offer(decision: dict, probe: dict, pin: dict, version: str) -> str:
    """The trust-aware version offer, naming the FIRST command that actually takes (or unblocks) the
    update. Keys on the decision's WIP hold first, then trust policy (channel-agnostic: the upstream
    trust gate runs for every channel), then channel only for the stable trust-must-be-set case."""
    if _framework_update_reason_is_wip_hold(decision.get("reason", "")):
        wip = ", ".join(decision.get("wipReasons", []))
        return (
            f"framework_update_offer: {version} is available; held by active WIP ({wip}); "
            "finish or park the WIP, then: tautline sync-methodology --target ."
        )
    policy = methodology_update_policy()
    channel = pin.get("channel", "stable")
    if policy == "pinned":
        if _framework_update_candidate_pinned(probe.get("availableSha")):
            return (
                f"framework_update_offer: {version} is available; the release is already pinned; "
                "take it with: tautline sync-methodology --target ."
            )
        return (
            f"framework_update_offer: {version} is available; the pin names an older release. "
            f"Edit `_framework.version` in the project adapter to {version}, then take it with: "
            "tautline sync-methodology --target ."
        )
    if policy == "signed":
        return (
            f"framework_update_offer: {version} is available; take it with: tautline "
            "sync-methodology --target . (the signed trust policy verifies the release; on a hold, "
            "follow the printed methodology_update_held remedy)"
        )
    if channel == "stable":
        return (
            f"framework_update_offer: {version} is available; stable-channel updates need trust "
            "set and the release pinned first: tautline install-cli --update-policy pinned, then "
            f"set `_framework.version` to {version}, then: tautline sync-methodology --target ."
        )
    updates = pin.get("updatePolicy", "manual")
    return (
        f"framework_update_offer: updatePolicy={updates} holds automatic updates; "
        f"take {version} with: tautline sync-methodology --target ."
    )


def _framework_update_package_offer(version: str) -> str:
    """The installed-package (PyPI) offer: pip is the ONLY channel that updates a wheel's running
    code, so the command is always the pipx/pip upgrade. Reuses PACKAGE_INSTALL_UPDATE_HINT (the
    one source the version hint, sync-skip surface, and update-repin refusal already share) so the
    package update command can never drift across surfaces."""
    return (
        f"framework_update_offer: {version} is available (running {plugin_version()}); "
        f"update with: {PACKAGE_INSTALL_UPDATE_HINT}"
    )


def framework_update_offer_lines(decision: dict, probe: dict, pin: dict) -> list[str]:
    """The framework_update_offer lines for a surface (display-only; never re-runs the decision).

    Emits ONLY on a genuine skip with a probe-truthful candidate: a newer release (the trust-aware
    version offer) or the deliberate sha-only launch discovery (a facts-only inspect offer). Never
    on a proceeding update, a held result, or a stood-down/failed probe. The facts-only branch is
    the launch no-fetch case; a metadata FAILURE also surfaces as a sha-only git result, so the
    surface (which fetches) suppresses the facts-only offer for its own sha-only results."""
    if decision.get("action") == "update":
        return []
    source = probe.get("source")
    if source in {"none", "failed"}:
        return []
    version = probe.get("availableVersion")
    if source == "package":
        # PyPI discovery (installed-package runtime): the offer names pip/pipx, never a git
        # sync/repin chain. Not-newer => no offer, exactly like the git happy path.
        if probe.get("isNewer") and version:
            return [_framework_update_package_offer(version)]
        return []
    if probe.get("isNewer") and version:
        return [_framework_update_version_offer(decision, probe, pin, version)]
    sha = probe.get("availableSha")
    # A sha-only discovery is emitted for both a fresh probe ("git") and its cached recompute
    # ("cache") -- mirror framework_remote_status_from_probe so the inspect offer does not flicker
    # off on repeat launches within the freshness window while "remote differs <sha>" persists.
    if source in {"git", "cache"} and version is None and sha:
        branch = framework_channel_branch(pin.get("channel", "stable"))
        local = (_update_probe_head(canonical_methodology_repo()) or "")[:12]
        return [
            f"framework_update_offer: upstream {branch} is at {sha[:12]} (local {local}); "
            "inspect with: tautline methodology-status --target ."
        ]
    return []


def goal_tracker_from_backlog_provider(provider: dict) -> dict:
    return {
        **DEFAULT_GOAL_TRACKER,
        "enabled": provider["enabled"],
        "provider": provider["provider"],
        "owner": provider["owner"],
        "projectNumber": provider["projectNumber"],
        # Identity is per-provider, so the projection carries EVERY provider's identity fields, not
        # just GitHub's. Copying only owner/projectNumber left a Jira board configured through one
        # block invisible in the other -- two blocks describing different boards for one lane.
        **{
            field: provider.get(field, "")
            for contract in providers_mod.PROVIDER_IDENTITY_FIELDS.values()
            for group in ("required", "optional", "secretEnvFields")
            for field in contract[group]
            if field not in ("owner", "projectNumber")
        },
        "scopeQuery": provider["scopeQuery"],
        "statusField": provider["statusField"],
        "priorityField": provider["priorityField"],
        "milestoneField": provider["milestoneField"],
        "readyStatuses": provider["readyStatuses"],
        "activeStatuses": provider["activeStatuses"],
        "doneStatuses": provider["doneStatuses"],
        "blockedStatuses": provider["blockedStatuses"],
        "authoritativeFor": provider["authoritativeFor"],
        "repoPlanRequired": provider["repoPlanRequired"],
        "linkPolicy": provider["linkPolicy"],
        "allowRepoOnlyGoals": provider.get(
            "allowRepoOnlyGoals", DEFAULT_BACKLOG_PROVIDER["allowRepoOnlyGoals"]
        ),
        "workOrder": provider.get("workOrder", "board"),
        "completionUnit": provider.get("completionUnit", "goal"),
        "epicField": provider.get("epicField", ""),
        "orderField": provider.get("orderField", ""),
        "featureSeries": provider.get("featureSeries", {}),
        # Mirror of the copy in backlog_provider_from_goal_tracker: load_project
        # round-trips legacy adapters through BOTH converters, and the opt-down
        # must survive the round trip (present-only; absence stays absence).
        **(
            {"unavailablePolicy": provider["unavailablePolicy"]}
            if "unavailablePolicy" in provider
            else {}
        ),
    }


def normalize_deploy_health_config(raw: object, index: int) -> dict:
    """Validate one deploymentTargets[].deployHealth block.

    Inlined from the deleted `tautline_methodology.deploy` module: the deploy-health command
    and the Google Chat deployment-notification pipeline went with the process engine, but
    `deployHealth` is still an adapter key the loader has to validate and the renderer reads.
    """
    defaults = DEFAULT_DEPLOY_HEALTH
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth must be an object")
    cfg = {**defaults, **raw}
    if "workflow" in raw and str(raw.get("workflow") or "").strip() and "enabled" not in raw:
        cfg["enabled"] = True
    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.enabled must be boolean")
    if not isinstance(cfg.get("failOnLatestFailure"), bool):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.failOnLatestFailure must be boolean")
    cfg["provider"] = str(cfg.get("provider") or "").strip()
    if cfg["provider"] not in {"github-actions"}:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.provider must be github-actions")
    cfg["workflow"] = str(cfg.get("workflow") or "").strip()
    cfg["branch"] = str(cfg.get("branch") or "main").strip()
    if cfg["enabled"] and not cfg["workflow"]:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.workflow must be non-blank when enabled")
    if cfg["enabled"] and not cfg["branch"]:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.branch must be non-blank when enabled")
    for key in ["limit", "maxConsecutiveFailures", "maxSuccessAgeHours"]:
        try:
            cfg[key] = int(cfg.get(key, defaults[key]))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.{key} must be an integer") from exc
    if cfg["limit"] < 1:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.limit must be positive")
    if cfg["maxConsecutiveFailures"] < 1:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.maxConsecutiveFailures must be positive")
    if cfg["maxSuccessAgeHours"] < 0:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.maxSuccessAgeHours must be zero or positive")
    return cfg


def project_json_decode_error(path: Path, exc: json.JSONDecodeError) -> str:
    return adapter_module().project_json_decode_error(path, exc, lane_adapter_file=(LANE_ADAPTER_FILE, LEGACY_LANE_ADAPTER_FILE))


def _adapter_schema() -> dict | None:
    return adapter_module().adapter_schema(ADAPTER_SCHEMA)


def schema_validation_errors(instance: object, schema: dict, path: str = "(root)") -> list[str]:
    return adapter_module().schema_validation_errors(instance, schema, path)


def hook_boundary_invocation() -> str:
    """The hook name this process was invoked under, or "" when it was not.

    Read through resolve_env, which applies its TAUTLINE_ alias preference ONLY to names beginning
    with MINERVIT_, so this is a plain direct read with no alias fan-out and no MINERVIT_ twin is
    created implicitly. The name never existed under the legacy prefix and is not a managed
    user-config key.

    Membership in GIT_BRANCH_LIVENESS_HOOKS is the validation: an arbitrary value enables nothing.
    The generated hooks are the only writers.
    """
    value = util_module().resolve_env("TAUTLINE_HOOK_BOUNDARY", "").strip()
    return value if value in GIT_BRANCH_LIVENESS_HOOKS else ""


def validate_adapter_schema(data: dict, path: Path) -> None:
    """Validate against the INSTALLED schema, downgrading a provable skew on a hook boundary.

    THE CANONICAL DOWNGRADE RULE, stated once, here. The unknown-top-level-property `SystemExit` is
    replaced by a report if and only if:

      (a) hook_boundary_invocation() is non-empty, AND
      (b) adapter_schema_skew_classification() returns a classification whose `disposition` is
          exactly `downgrade` -- which only the `tree-authoritative` proof produces, AND
      (c) every error in the list is a root-level unknown-property error, which is
          unknown_top_level_property_keys()'s all-or-nothing contract.

    Any other combination raises unchanged. A `refuse` disposition still raises; its only effect is
    that the hint rides along, so a refusal that named no remedy at all finally says something.

    Three invariants the diff preserves explicitly, because each is easy to lose here:

    - FAIL-OPEN ON AN UNREADABLE SCHEMA IS PRESERVED. The delegate returns silently when the schema
      cannot be read, and this wrapper never short-circuits that into an error path. It is the
      deliberate no-wedge choice.
    - THERE IS STILL EXACTLY ONE REFUSAL TEXT. When the seam does not downgrade, the SystemExit
      comes from adapter.validate_adapter_schema, never from a second copy of that message here.
    - `validate-adapter` IS UNAFFECTED and stays the strict oracle in every environment. It does not
      reach this wrapper -- it calls _adapter_schema() and schema_validation_errors directly -- so
      it is strict by construction rather than by a flag.
    """
    module = adapter_module()
    if hook_boundary_invocation():
        classification = module.adapter_schema_skew_classification(
            data,
            path,
            installed_schema_path=ADAPTER_SCHEMA,
            installed_version=methodology_version(),
        )
        if classification is not None:
            for line in module.adapter_schema_skew_report_lines(classification):
                print(line, file=sys.stderr)
            if classification["disposition"] == "downgrade":
                return
    return module.validate_adapter_schema(data, path, ADAPTER_SCHEMA)


RUNTIME_SECRET_SCAN_EXTENSIONS = _core_runtime_mod.RUNTIME_SECRET_SCAN_EXTENSIONS
required_secret_fallback_findings = _core_runtime_mod.required_secret_fallback_findings

# Directories a source scan must never walk into: vendored trees, build output and caches are not
# the adopter's code, and walking them turns a one-second lint into a minute of I/O.
RUNTIME_SECRET_SCAN_PRUNE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".turbo", ".cache",
    "__pycache__", ".venv", "venv", "target", "coverage", ".pytest_cache", ".mypy_cache",
}


def runtime_config(data: dict) -> dict:
    """Defaults merged with the adapter's runtimeConfig, for JSON of ANY shape.

    `validate-adapter` reads the adapter file RAW, so `runtimeConfig` can be a string, a list, a
    number -- every one of which a `**` merge raises `TypeError` on. That traceback replaced the
    violation list the command exists to print, losing the schema errors already collected. A
    non-object is not this function's error to report: the schema reports it, and this returns
    the defaults so the run reaches that report.
    """
    raw = data.get("runtimeConfig") if isinstance(data, dict) else None
    return {**DEFAULT_RUNTIME_CONFIG, **(raw if isinstance(raw, dict) else {})}


def required_secret_names(data: dict) -> list[str]:
    """Registered required-secret names, for JSON of any shape (see `runtime_config`)."""
    secrets = runtime_config(data).get("requiredSecrets")
    if not isinstance(secrets, list):
        return []
    return [s["name"] for s in secrets if isinstance(s, dict) and s.get("name")]


def adapter_project_root(adapter_path: Path) -> Path:
    """The project root an adapter file describes, given the path to that file.

    A repo-local adapter lives at `<root>/.tautline/adapter.json` (or the legacy `.minervit/`
    spelling), so its PARENT is a directory containing nothing but the adapter. Scanning that as
    the project would walk one file and find nothing -- which is how a source scan comes back
    clean on a repo full of defects. Anywhere else (a source adapter under `adapters/projects/`,
    an operator-supplied path), the adapter sits at the root and the parent is correct.
    """
    resolved = adapter_path.resolve()
    marker_dirs = {Path(REPO_LOCAL_ADAPTER_FILE).parent.name, Path(LEGACY_REPO_LOCAL_ADAPTER_FILE).parent.name}
    if resolved.parent.name in marker_dirs:
        return resolved.parent.parent
    return resolved.parent


def runtime_secret_fallback_issues(data: dict, target: Path) -> list[str]:
    """Issues for the required-runtime-secret registry (the #448 class).

    One finding, and it is a FINDING rather than an advisory: any source file that reads a
    registered required secret with a degrade-to-empty fallback (`?? \'\'` / `|| \'\'`) -- the idiom
    that turns a missing secret into a silent 500 instead of a loud boot failure.

    The companion advisory the old host also printed -- "this customer-facing adapter declares no
    required-secret registry at all" -- is deliberately NOT returned here. It is a suggestion about
    an absent declaration, not a defect in code that exists, and `validate-adapter` treats what it
    returns as a violation that fails the lint. Reporting it here would refuse every adapter that
    has deployment targets and no registry, which is a legal configuration.

    Process-bankruptcy demolition (2026-08-28): this used to be reported by `methodology-status`,
    whose ceremony index was deleted. The control is a SECURITY control, not process ceremony, so it
    moved to `validate-adapter` rather than dying with its old host -- an adapter lint is the right
    surface for it, and it is the one an adopter runs by hand.
    """
    issues: list[str] = []
    # `validate-adapter` reads the file RAW, so `data` here can be any JSON value -- a top-level
    # array is a real adopter mistake the schema reports properly, and this scan must not crash
    # ahead of it.
    if not isinstance(data, dict):
        return issues
    names = required_secret_names(data)
    if not names:
        return issues
    scanned = 0
    try:
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in RUNTIME_SECRET_SCAN_PRUNE_DIRS and not d.startswith(".")]
            for filename in files:
                if not filename.endswith(RUNTIME_SECRET_SCAN_EXTENSIONS):
                    continue
                scanned += 1
                if scanned > 20000:
                    return issues
                path = Path(root) / filename
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for name in required_secret_fallback_findings(text, names):
                    issues.append(
                        f"required secret `{name}` is read with a degrade-to-empty fallback (?? \'\' / || \'\') in "
                        f"{path.relative_to(target)}: a missing required secret must fail loudly, not silently "
                        "become an empty string"
                    )
    except OSError:
        pass
    return issues


def validate_adapter(args: argparse.Namespace) -> int:
    """`validate-adapter <path>`: self-serve schema lint for an adapter (arch-config-7).

    Reports every schema violation at once (unknown keys, wrong types, bad enums, missing required
    keys) so an adopter can fix their adapter without round-tripping through a full lane start.
    """
    path = args.project
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"adapter not found: {path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"adapter is not valid JSON: {path}: {exc}", file=sys.stderr)
        return 1
    if lean.is_lean_config(data):  # --- LEAN INIT WIRING ---
        # A lean-1 adapter fails every check below by design (none of the eleven ceremony keys),
        # so without this branch `validate-adapter` refused every config `tautline init` writes.
        # `lean.lean_config_errors` is the validator the schema doc names as authoritative; this
        # is "the same path" `tautline init` calls too (via `lean.lean_validation_report`).
        errors = lean.lean_config_errors(data)
        for line in lean.lean_validation_report(str(path), errors):
            print(line, file=sys.stderr if errors else sys.stdout)
        return 1 if errors else 0
    schema = _adapter_schema()
    if schema is None:
        print(f"adapter schema unavailable ({ADAPTER_SCHEMA}); cannot validate", file=sys.stderr)
        return 2
    errors = schema_validation_errors(data, schema)
    # Referential integrity JSON Schema cannot express: a `roles` value must resolve to a key in
    # `agents`. Reported ALONGSIDE the schema errors, never instead of them -- this command's
    # contract is that an adopter sees EVERY violation in one pass.
    #
    # SCHEMA ON THE RAW DATA, REGISTRY ON THE PROJECTED DATA, and the split is load-bearing.
    # This command reads the file directly rather than through `load_project`, so nothing has
    # projected the legacy shim for it. Checking references against raw JSON rejects the
    # documented partial migration -- an adapter that declares
    # `roles.implementationReviewer = "codex"` while still carrying `review.codexWrapper`, where
    # the `codex` agent comes from the shim. The schema still judges what the adopter wrote;
    # only the reference check sees the effective registry.
    errors = list(errors) + agents_mod.agents_registry_errors(agent_compat.effective_agents(data))
    # Provider membership is the registry's, not the schema's, since the notify enums were opened.
    # JSON Schema cannot express "is in the registry", so without this line `validate-adapter` would
    # report a clean adapter that `load_project` refuses on the very next command.
    errors = errors + notify_provider_errors(data) + backlog_provider_errors(data)
    # Security, not schema: a registered required secret read with a degrade-to-empty fallback
    # turns a missing secret into a silent empty string. Reported with the rest so an adopter
    # still sees every violation in one pass.
    errors = errors + runtime_secret_fallback_issues(data, adapter_project_root(args.project))
    if errors:
        print(f"adapter {path} has {len(errors)} schema violation(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    legacy_t0 = ((data.get("review") or {}).get("roundBudgets") or {}).get("T0")
    if isinstance(legacy_t0, int) and not isinstance(legacy_t0, bool) and legacy_t0 > 0:
        print(
            f"adapter warning: review.roundBudgets.T0={legacy_t0} is legacy; "
            "runtime coerces T0 to 0 because T0 does not use cross-model implementation review",
            file=sys.stderr,
        )
    print(f"adapter {path} matches the adapter schema ({ADAPTER_SCHEMA.name})")
    return 0


NOTIFY_BLOCK_LABELS = (
    ("milestoneUpdate", ()),
    ("productChat", ()),
    ("deploymentNotification", ()),
    ("iterationReview", ("delivery",)),
)


def notify_provider_block_errors(config: dict, label: str) -> list[str]:
    """Registry-membership and enabled-vs-null errors for ONE notify block, as a list.

    The single implementation behind both `validate_notify_provider` (which raises, on the
    `load_project` path) and `notify_provider_errors` (which collects, for `validate-adapter`).
    Deliberately not two parsers for one concept: this repository has already paid for that shape
    once, when a read side and a write side each resolved an issue's repo their own way and
    verification evidence landed on an unrelated issue.

    An ABSENT provider is not an error: `validate-adapter` reads the adapter file directly, with no
    defaults projected, and every notify block defaults to a real provider, so treating "unset" as
    invalid would refuse adapters that load fine.

    A PRESENT-BUT-BLANK provider IS an error, and the distinction is the whole point. `load_project`
    normalises before it validates, so `"provider": "   "` reaches the schema as `""` and is refused
    for `minLength`. Reading it here as "unset" would let `validate-adapter` print "matches the
    adapter schema" for the exact adapter the next command refuses -- the divergence this collector
    was added to close, reappearing one layer down.
    """
    errors: list[str] = []
    if "provider" not in config:
        return errors
    provider_id = str(config.get("provider") or "").strip()
    if not provider_id:
        return [
            f"Project adapter {label}.provider is present but blank; "
            "remove the key to take the default, or name a registered notify provider "
            f"({', '.join(providers_mod.providers_serving('notify', 'post'))})"
        ]
    error = providers_mod.provider_validation_error(
        "notify", provider_id, label=f"Project adapter {label}"
    )
    if error:
        return [error]
    implementation = providers_mod.resolve_provider("notify", provider_id)
    if config.get("enabled") and implementation is not None and implementation.is_null:
        delivering = providers_mod.providers_serving("notify", "post")
        errors.append(
            f"Project adapter {label}.provider is 'none' while {label}.enabled is true; "
            f"set {label}.enabled false to intend no delivery, or name a delivering notify provider "
            f"({', '.join(delivering)})"
        )
    return errors


def notify_provider_errors(data: dict) -> list[str]:
    """Every notify-provider violation in an adapter, for `validate-adapter`.

    Opening the four enums moved membership out of JSON Schema and into the registry, so schema
    validation alone can no longer see a bad provider id. Without this, `validate-adapter` would
    print "matches the adapter schema" for an adapter `load_project` refuses on the next command --
    a lint that green-lights an unusable config, which is worse than no lint. Reported ALONGSIDE
    the schema errors, on the same precedent as the agent-registry reference check.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        # `validate-adapter` reads the file directly, so `data` is whatever JSON the adopter wrote
        # -- a top-level array is a real thing people submit. Reporting it is the schema check's
        # job; this one simply has nothing to say about it, and must not traceback on the way past.
        return errors
    for key, nested in NOTIFY_BLOCK_LABELS:
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        label = key
        for child in nested:
            block = block.get(child)
            if not isinstance(block, dict):
                break
            label = f"{label}.{child}"
        if isinstance(block, dict):
            errors.extend(notify_provider_block_errors(block, label))
    return errors


def issues_provider_validation_error(raw: object) -> str:
    """`""` when the declared issues provider is registered; otherwise a specific refusal.

    Absent and present-but-blank are different mistakes and get different messages -- the
    distinction R1 had to learn twice, one layer apart, because `load_project` normalises before it
    validates while the self-service lint reads the file raw.
    """
    if raw is None:
        return ""
    provider_id = str(raw).strip()
    if not provider_id:
        return (
            "Project adapter stakeholderQuestions.provider is present but blank; remove the key to "
            "take the default, or name a registered issues provider "
            f"({', '.join(providers_mod.registered_provider_ids('issues'))})"
        )
    return providers_mod.provider_validation_error(
        "issues", provider_id, label="Project adapter stakeholderQuestions"
    )


def backlog_provider_errors(data: dict) -> list[str]:
    """Every backlog/issues provider violation in an adapter, for `validate-adapter`.

    R1's L1 lesson, third occurrence and the reason it is written down: opening an enum moves
    membership OUT of JSON Schema, so schema validation alone can no longer see a bad provider id.
    Without this, `validate-adapter` prints "matches the adapter schema" for an adapter
    `load_project` refuses on the very next command -- a lint that green-lights an unusable config,
    which is worse than no lint. Reported alongside the schema errors so an adopter still sees every
    violation in one pass.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return errors
    for key in ("backlogProvider", "goalTracker"):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        if "provider" not in block:
            # Omitting the key is the SUPPORTED way to take the default provider, so the block is
            # still a configured block and must still be inspected. Skipping it here meant a
            # literal credential in `apiTokenEnv` passed the lint and was refused by
            # `load_project` -- the fourth variant of one class, and the first three were each
            # fixed for the dimension that found them (Codex R4 P1).
            errors.extend(
                _core_runtime_mod._provider_identity_issues(
                    "github-projects", block, key, require_present=bool(block.get("enabled"))
                )
            )
            continue
        provider_id = str(block["provider"] or "").strip()
        if not provider_id:
            errors.append(
                f"Project adapter {key}.provider is present but blank; remove the key to take "
                "the default, or name a registered backlog provider "
                f"({', '.join(providers_mod.registered_provider_ids('backlog'))})"
            )
            continue
        error = providers_mod.provider_validation_error(
            "backlog", provider_id, label=f"Project adapter {key}"
        )
        if error:
            errors.append(error)
            continue
        # Membership is not identity. Checking only the former let the lint exit 0 for an adapter
        # `load_project` refuses on its identity fields -- the same divergence this collector was
        # added to close, one layer down, and the migration note sends adopters here to check.
        # Presence is required only when the block is enabled, matching the load path exactly; a
        # supplied secret is format-checked either way.
        errors.extend(
            _core_runtime_mod._provider_identity_issues(
                provider_id, block, key, require_present=bool(block.get("enabled"))
            )
        )
    stakeholder = data.get("stakeholderQuestions")
    if isinstance(stakeholder, dict) and "provider" in stakeholder:
        error = issues_provider_validation_error(stakeholder["provider"])
        if error:
            errors.append(error)
    return errors


def validate_notify_provider(config: dict, label: str) -> None:
    """Refuse one `notify` block whose provider is unregistered, or null while enabled.

    Replaces four hand-rolled `must be google-chat-webhook` refusals with one registry lookup. The
    message stays as specific as the one it replaces -- it names the value and the registered ids --
    while the mechanism underneath is open, so a second chat tool is a registration rather than a
    fork of this validator.

    The second check keeps the null provider honest. A block that is `enabled: true` and resolves to
    the no-op provider is a MISCONFIGURATION, not a preference: it reads as configured delivery and
    would deliver nothing. Refusing at load keeps silence-on-purpose (`enabled: false`, or no block
    at all) distinguishable from silence-by-accident, which is the difference between a deliberate
    opt-out and a control that reports success while doing nothing.
    """
    errors = notify_provider_block_errors(config, label)
    if errors:
        raise SystemExit(errors[0])


def load_project(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise SystemExit(project_json_decode_error(path, exc))
    if isinstance(data, dict):
        # A freshly-init'd bootstrap adapter is known-incomplete: surface the actionable
        # "replace your placeholders" guidance before the per-field validators below (and the
        # schema net at the end of this function), so the user sees the fix-this-first message
        # rather than a confusing minLength/non-blank error on an expected-empty placeholder.
        bootstrap_placeholders = collect_bootstrap_placeholders(data)
        if bootstrap_placeholders:
            raise SystemExit(
                "Project adapter still contains BOOTSTRAP REQUIRED placeholders: "
                + ", ".join(bootstrap_placeholders)
                + ". Replace them before rendering or starting a lane."
            )
    required = [
        "project",
        "repo",
        "productionDeployExists",
        "backlogAdapter",
        "planningArtifacts",
        "commands",
        "review",
        "behaviorSpecs",
        "continuity",
        "readiness",
        "generatedFiles",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"Project adapter missing required keys: {', '.join(missing)}")
    data["_framework"] = normalize_framework_pin(data.get("_framework"), "Project adapter _framework")
    data["workProfiles"] = normalize_work_profiles(data.get("workProfiles"))
    data["derivedArtifacts"] = normalize_derived_artifacts(data.get("derivedArtifacts"))
    bootstrap_evidence = data.get("bootstrapEvidence")
    if source_adapter_requires_bootstrap_evidence(path) and bootstrap_evidence is None:
        raise SystemExit(
            "Project adapter bootstrapEvidence missing. Source adapters under adapters/projects must record "
            "interview/repo-evidence provenance before render."
        )
    if bootstrap_evidence is not None:
        if not isinstance(bootstrap_evidence, dict):
            raise SystemExit("Project adapter bootstrapEvidence must be an object")
        if not isinstance(data["project"], str):
            raise SystemExit("Project adapter project must be a string")
        project_name = data["project"].strip()
        if not project_name:
            raise SystemExit("Project adapter project must be non-blank")
        data["project"] = project_name
        for key in ["project", "status", "summary"]:
            raw_value = bootstrap_evidence.get(key, "")
            if not isinstance(raw_value, str):
                raise SystemExit(f"Project adapter bootstrapEvidence.{key} must be a string")
            value = raw_value.strip()
            if not value:
                raise SystemExit(f"Project adapter bootstrapEvidence.{key} must be non-blank")
            bootstrap_evidence[key] = value
        if bootstrap_evidence["project"] != project_name:
            raise SystemExit(
                "Project adapter bootstrapEvidence.project must match project; copied adapter evidence is not valid "
                f"for this project ({bootstrap_evidence['project']} != {project_name})"
            )
        status = bootstrap_evidence["status"]
        if status.startswith(BOOTSTRAP_REQUIRED_PREFIX):
            pass
        elif status not in {"interviewed", "repo-evident", "legacy-reviewed"}:
            raise SystemExit(
                "Project adapter bootstrapEvidence.status must be interviewed, repo-evident, or legacy-reviewed"
            )
        elif status == "legacy-reviewed":
            if not legacy_bootstrap_project_allowlisted(project_name):
                raise SystemExit(
                    "Project adapter bootstrapEvidence.status legacy-reviewed is reserved for explicitly "
                    "grandfathered adapters; new projects must use interviewed or repo-evident"
                )
            if source_adapter_requires_bootstrap_evidence(path) and not source_adapter_legacy_allowlisted(path, project_name):
                raise SystemExit(
                    "Project adapter bootstrapEvidence.status legacy-reviewed is reserved for explicitly "
                    "grandfathered adapters; new projects must use interviewed or repo-evident"
                )
        elif status == "interviewed":
            artifact = bootstrap_evidence.get("interviewArtifact")
            if not isinstance(artifact, dict):
                raise SystemExit("Project adapter bootstrapEvidence.interviewArtifact must be an object")
            for key in ["path", "sha256"]:
                raw_value = artifact.get(key, "")
                if not isinstance(raw_value, str):
                    raise SystemExit(f"Project adapter bootstrapEvidence.interviewArtifact.{key} must be a string")
                value = raw_value.strip()
                if not value:
                    raise SystemExit(f"Project adapter bootstrapEvidence.interviewArtifact.{key} must be non-blank")
                artifact[key] = value
            validate_relative_bootstrap_path(artifact["path"], "interviewArtifact.path")
            if not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
                raise SystemExit("Project adapter bootstrapEvidence.interviewArtifact.sha256 must be a SHA256 hex digest")
            bootstrap_evidence["interviewArtifact"] = artifact
        elif status == "repo-evident":
            repo_evidence = bootstrap_evidence.get("repoEvidence")
            if not isinstance(repo_evidence, list) or len(repo_evidence) < 2:
                raise SystemExit("Project adapter bootstrapEvidence.repoEvidence must contain at least two evidence files")
            normalized_evidence = []
            seen_evidence_paths = set()
            for index, item in enumerate(repo_evidence):
                if not isinstance(item, dict):
                    raise SystemExit(f"Project adapter bootstrapEvidence.repoEvidence[{index}] must be an object")
                normalized_item = {}
                for key in ["path", "fact"]:
                    raw_value = item.get(key, "")
                    if not isinstance(raw_value, str):
                        raise SystemExit(
                            f"Project adapter bootstrapEvidence.repoEvidence[{index}].{key} must be a string"
                        )
                    value = raw_value.strip()
                    if not value:
                        raise SystemExit(
                            f"Project adapter bootstrapEvidence.repoEvidence[{index}].{key} must be non-blank"
                        )
                    normalized_item[key] = value
                validate_relative_bootstrap_path(normalized_item["path"], f"repoEvidence[{index}].path")
                path_key = normalized_item["path"].strip().rstrip("/")
                if path_key in seen_evidence_paths:
                    raise SystemExit(
                        f"Project adapter bootstrapEvidence.repoEvidence[{index}].path is duplicated: "
                        f"{normalized_item['path']}"
                    )
                seen_evidence_paths.add(path_key)
                if path_key in INVALID_REPO_EVIDENCE_PATHS:
                    raise SystemExit(
                        f"Project adapter bootstrapEvidence.repoEvidence[{index}].path is too generic: "
                        f"{normalized_item['path']}"
                    )
                if Path(path_key).name.lower() in WEAK_REPO_EVIDENCE_FILENAMES:
                    raise SystemExit(
                        f"Project adapter bootstrapEvidence.repoEvidence[{index}].path is weak boilerplate evidence: "
                        f"{normalized_item['path']}"
                    )
                normalized_evidence.append(normalized_item)
            bootstrap_evidence["repoEvidence"] = normalized_evidence
        data["bootstrapEvidence"] = bootstrap_evidence
    data["laneState"] = {**DEFAULT_LANE_STATE, **data.get("laneState", {})}
    data["milestoneContinuation"] = {
        **DEFAULT_MILESTONE_CONTINUATION,
        **data.get("milestoneContinuation", {}),
    }
    if not isinstance(data["milestoneContinuation"].get("watchdogEnabled"), bool):
        raise SystemExit("Project adapter milestoneContinuation.watchdogEnabled must be boolean")
    try:
        data["milestoneContinuation"]["watchdogCadenceMinutes"] = int(
            data["milestoneContinuation"]["watchdogCadenceMinutes"]
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter milestoneContinuation.watchdogCadenceMinutes must be a positive integer") from exc
    if data["milestoneContinuation"]["watchdogCadenceMinutes"] < 1:
        raise SystemExit("Project adapter milestoneContinuation.watchdogCadenceMinutes must be a positive integer")
    data["sessionJournal"] = {**DEFAULT_SESSION_JOURNAL, **data.get("sessionJournal", {})}
    if not isinstance(data["sessionJournal"].get("enabled"), bool):
        raise SystemExit("Project adapter sessionJournal.enabled must be boolean")
    if not isinstance(data["sessionJournal"].get("gitIgnoreLocal"), bool):
        raise SystemExit("Project adapter sessionJournal.gitIgnoreLocal must be boolean")
    if data["sessionJournal"].get("cadence") not in {"milestone", "session", "off"}:
        raise SystemExit("Project adapter sessionJournal.cadence must be milestone, session, or off")
    for key in ["branch", "archiveDir"]:
        value = str(data["sessionJournal"].get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter sessionJournal.{key} must be non-blank")
        if key == "archiveDir" and Path(value).is_absolute():
            raise SystemExit("Project adapter sessionJournal.archiveDir must be project-relative, not an absolute machine path")
        data["sessionJournal"][key] = value
    try:
        data["sessionJournal"]["maxBytes"] = int(data["sessionJournal"]["maxBytes"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter sessionJournal.maxBytes must be a positive integer") from exc
    if data["sessionJournal"]["maxBytes"] < 1:
        raise SystemExit("Project adapter sessionJournal.maxBytes must be a positive integer")
    data["observabilityEvents"] = {
        **DEFAULT_OBSERVABILITY_EVENTS,
        **data.get("observabilityEvents", {}),
    }
    observability = data["observabilityEvents"]
    if not isinstance(observability.get("enabled"), bool):
        raise SystemExit("Project adapter observabilityEvents.enabled must be boolean")
    for key in ["stateDir", "humanLog", "jsonlLog"]:
        value = str(observability.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter observabilityEvents.{key} must be non-blank")
        if key in {"humanLog", "jsonlLog"} and (Path(value).is_absolute() or "/" in value or "\\" in value):
            raise SystemExit(f"Project adapter observabilityEvents.{key} must be a filename, not a path")
        observability[key] = value
    if observability["humanLog"] == observability["jsonlLog"]:
        raise SystemExit("Project adapter observabilityEvents.humanLog and jsonlLog must be different filenames")
    try:
        observability["rotateBytes"] = int(observability["rotateBytes"])
        observability["retainedRotations"] = int(observability["retainedRotations"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter observabilityEvents.rotateBytes and retainedRotations must be positive integers") from exc
    if observability["rotateBytes"] < 1 or observability["retainedRotations"] < 1:
        raise SystemExit("Project adapter observabilityEvents.rotateBytes and retainedRotations must be positive integers")
    required_events = observability.get("requiredBoundaryEvents", [])
    if not isinstance(required_events, list) or not all(isinstance(item, str) and item.strip() for item in required_events):
        raise SystemExit("Project adapter observabilityEvents.requiredBoundaryEvents must be a list of non-blank strings")
    observability["requiredBoundaryEvents"] = [slugify(item, fallback="event").replace("-", "_") for item in required_events]
    data["instrumentation"] = {**DEFAULT_INSTRUMENTATION, **data.get("instrumentation", {})}
    instrumentation = data["instrumentation"]
    unknown_instrumentation_keys = set(instrumentation) - set(DEFAULT_INSTRUMENTATION)
    if unknown_instrumentation_keys:
        raise SystemExit(
            "Project adapter instrumentation.* has unsupported key(s): "
            + ", ".join(sorted(unknown_instrumentation_keys))
            + " -- telemetry remote metadata is a fixed constant, so there are no branch/archiveDir knobs"
        )
    if not isinstance(instrumentation.get("enabled"), bool):
        raise SystemExit("Project adapter instrumentation.enabled must be boolean")
    if instrumentation.get("cadence") not in {"milestone", "session", "off"}:
        raise SystemExit("Project adapter instrumentation.cadence must be milestone, session, or off")
    if instrumentation["enabled"] and not observability["enabled"]:
        # Config-coherence: instrumentation aggregates the observability event log, so enabling it
        # while events are disabled would publish empty/misleading records. Reject at load time.
        raise SystemExit(
            "Project adapter instrumentation.enabled requires observabilityEvents.enabled: the "
            "instrumentation record is an aggregation over the local observability event log and "
            "cannot be produced with event logging disabled"
        )
    data["usageAccounting"] = {
        **DEFAULT_USAGE_ACCOUNTING,
        **data.get("usageAccounting", {}),
    }
    usage = data["usageAccounting"]
    if not isinstance(usage.get("enabled"), bool):
        raise SystemExit("Project adapter usageAccounting.enabled must be boolean")
    for key in ["stateDir", "jsonlLog", "rollupJson"]:
        value = str(usage.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter usageAccounting.{key} must be non-blank")
        if key in {"jsonlLog", "rollupJson"} and (Path(value).is_absolute() or "/" in value or "\\" in value):
            raise SystemExit(f"Project adapter usageAccounting.{key} must be a filename, not a path")
        usage[key] = value
    if usage["jsonlLog"] == usage["rollupJson"]:
        raise SystemExit("Project adapter usageAccounting.jsonlLog and rollupJson must be different filenames")
    try:
        usage["rotateBytes"] = int(usage["rotateBytes"])
        usage["retainedRotations"] = int(usage["retainedRotations"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter usageAccounting.rotateBytes and retainedRotations must be positive integers") from exc
    if usage["rotateBytes"] < 1 or usage["retainedRotations"] < 1:
        raise SystemExit("Project adapter usageAccounting.rotateBytes and retainedRotations must be positive integers")
    data["iterationReview"] = {
        **DEFAULT_ITERATION_REVIEW,
        **data.get("iterationReview", {}),
    }
    iteration_review = data["iterationReview"]
    if not isinstance(iteration_review.get("enabled"), bool):
        raise SystemExit("Project adapter iterationReview.enabled must be boolean")
    granularities = iteration_review.get("granularities", [])
    if not isinstance(granularities, list) or any(str(item).strip() not in {"goal", "milestone"} for item in granularities):
        raise SystemExit("Project adapter iterationReview.granularities must contain only goal and/or milestone")
    if not granularities:
        raise SystemExit("Project adapter iterationReview.granularities must contain at least one value")
    iteration_review["granularities"] = [str(item).strip() for item in granularities]
    outputs = {**DEFAULT_ITERATION_REVIEW["outputs"], **iteration_review.get("outputs", {})}
    if not isinstance(outputs.get("page"), bool) or not isinstance(outputs.get("video"), bool):
        raise SystemExit("Project adapter iterationReview.outputs.page and outputs.video must be boolean")
    if iteration_review["enabled"] and not any(outputs.values()):
        raise SystemExit("Project adapter iterationReview.outputs must enable page or video when iterationReview is enabled")
    iteration_review["outputs"] = outputs
    boundary = {**DEFAULT_ITERATION_REVIEW["boundary"], **iteration_review.get("boundary", {})}
    if not isinstance(boundary.get("announce"), bool) or not isinstance(boundary.get("autoRunAtBoundary"), bool):
        raise SystemExit("Project adapter iterationReview.boundary.announce and boundary.autoRunAtBoundary must be boolean")
    iteration_review["boundary"] = boundary
    record_dir = str(iteration_review.get("recordDir", "")).strip()
    if not record_dir:
        raise SystemExit("Project adapter iterationReview.recordDir must be non-blank")
    if Path(record_dir).is_absolute():
        raise SystemExit("Project adapter iterationReview.recordDir must be project-relative, not an absolute machine path")
    iteration_review["recordDir"] = record_dir
    hosting = {**DEFAULT_ITERATION_REVIEW["hosting"], **iteration_review.get("hosting", {})}
    for key in ["store", "keyPattern", "cdn", "access"]:
        value = str(hosting.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter iterationReview.hosting.{key} must be non-blank")
        hosting[key] = value
    hosting["bucket"] = str(hosting.get("bucket", "")).strip()
    hosting["baseUrl"] = str(hosting.get("baseUrl", "")).strip()
    if hosting["store"] not in {"s3"}:
        raise SystemExit("Project adapter iterationReview.hosting.store must be s3")
    if hosting["cdn"] not in {"cloudfront"}:
        raise SystemExit("Project adapter iterationReview.hosting.cdn must be cloudfront")
    if outputs["video"] and iteration_review["enabled"] and not hosting["bucket"]:
        raise SystemExit("Project adapter iterationReview.hosting.bucket must be non-blank when enabled video output is configured")
    iteration_review["hosting"] = hosting
    delivery = {**DEFAULT_ITERATION_REVIEW["delivery"], **iteration_review.get("delivery", {})}
    if not isinstance(delivery.get("enabled"), bool):
        raise SystemExit("Project adapter iterationReview.delivery.enabled must be boolean")
    if not isinstance(delivery.get("dedupe"), bool):
        raise SystemExit("Project adapter iterationReview.delivery.dedupe must be boolean")
    for key in ["trigger", "provider", "primaryUrl", "sentStateDir"]:
        value = str(delivery.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter iterationReview.delivery.{key} must be non-blank")
        delivery[key] = value
    delivery["webhookEnv"] = str(delivery.get("webhookEnv", "")).strip()
    delivery["chatSpace"] = str(delivery.get("chatSpace", "")).strip()
    if delivery["trigger"] not in {"after-merge"}:
        raise SystemExit("Project adapter iterationReview.delivery.trigger must be after-merge")
    validate_notify_provider(delivery, "iterationReview.delivery")
    if delivery["primaryUrl"] not in {"cloudfront-page"}:
        raise SystemExit("Project adapter iterationReview.delivery.primaryUrl must be cloudfront-page")
    if Path(delivery["sentStateDir"]).is_absolute():
        raise SystemExit("Project adapter iterationReview.delivery.sentStateDir must be project-relative, not an absolute machine path")
    if delivery["enabled"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", delivery["webhookEnv"]):
        raise SystemExit("Project adapter iterationReview.delivery.webhookEnv must name an environment variable when delivery is enabled")
    if iteration_review["enabled"] and delivery["enabled"] and (not hosting["bucket"] or not hosting["baseUrl"]):
        raise SystemExit("Project adapter iterationReview delivery requires iterationReview.hosting.bucket and baseUrl")
    iteration_review["delivery"] = delivery
    deployment_notification_raw = data.get("deploymentNotification")
    deployment_notification = {
        **DEFAULT_DEPLOYMENT_NOTIFICATION,
        **(deployment_notification_raw or {}),
    }
    if deployment_notification_raw is None:
        deployment_notification["enabled"] = bool(iteration_review["enabled"] and delivery["enabled"])
    if not isinstance(deployment_notification.get("enabled"), bool):
        raise SystemExit("Project adapter deploymentNotification.enabled must be boolean")
    if not isinstance(deployment_notification.get("reuseIterationReviewWebhook"), bool):
        raise SystemExit("Project adapter deploymentNotification.reuseIterationReviewWebhook must be boolean")
    if not isinstance(deployment_notification.get("dedupe"), bool):
        raise SystemExit("Project adapter deploymentNotification.dedupe must be boolean")
    deployment_pipeline_raw = deployment_notification.get("pipeline") or {}
    if not isinstance(deployment_pipeline_raw, dict):
        raise SystemExit("Project adapter deploymentNotification.pipeline must be an object")
    deployment_pipeline = {
        **DEFAULT_DEPLOYMENT_NOTIFICATION["pipeline"],
        **deployment_pipeline_raw,
    }
    if (
        deployment_notification_raw is not None
        and "pipeline" not in deployment_notification_raw
        and bool(deployment_notification.get("enabled"))
    ):
        deployment_pipeline["required"] = True
    if not isinstance(deployment_pipeline.get("required"), bool):
        raise SystemExit("Project adapter deploymentNotification.pipeline.required must be boolean")
    if not isinstance(deployment_pipeline.get("healthCheckBeforeNotify"), bool):
        raise SystemExit("Project adapter deploymentNotification.pipeline.healthCheckBeforeNotify must be boolean")
    deployment_pipeline["mode"] = str(deployment_pipeline.get("mode", "")).strip()
    if deployment_pipeline["mode"] not in {"ci-post-deploy", "manual-command"}:
        raise SystemExit("Project adapter deploymentNotification.pipeline.mode must be ci-post-deploy or manual-command")
    deployment_pipeline["requiredCommand"] = str(deployment_pipeline.get("requiredCommand", "")).strip()
    if not deployment_pipeline["requiredCommand"]:
        raise SystemExit("Project adapter deploymentNotification.pipeline.requiredCommand must be non-blank")
    evidence_paths = deployment_pipeline.get("evidencePaths") or []
    if not isinstance(evidence_paths, list) or not all(isinstance(item, str) and item.strip() for item in evidence_paths):
        raise SystemExit("Project adapter deploymentNotification.pipeline.evidencePaths must be a list of non-blank project-relative paths")
    normalized_evidence_paths = []
    for evidence_path in evidence_paths:
        evidence_path = evidence_path.strip()
        if Path(evidence_path).is_absolute() or evidence_path == ".." or evidence_path.startswith("../") or "/../" in evidence_path:
            raise SystemExit("Project adapter deploymentNotification.pipeline.evidencePaths must be project-relative, not absolute or parent paths")
        normalized_evidence_paths.append(evidence_path)
    deployment_pipeline["evidencePaths"] = normalized_evidence_paths
    deployment_notification["pipeline"] = deployment_pipeline
    for key in ["trigger", "provider", "sentStateDir"]:
        value = str(deployment_notification.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter deploymentNotification.{key} must be non-blank")
        deployment_notification[key] = value
    deployment_notification["webhookEnv"] = str(deployment_notification.get("webhookEnv", "")).strip()
    deployment_notification["chatSpace"] = str(deployment_notification.get("chatSpace", "")).strip()
    if deployment_notification["trigger"] not in {"deploy-ready"}:
        raise SystemExit("Project adapter deploymentNotification.trigger must be deploy-ready")
    validate_notify_provider(deployment_notification, "deploymentNotification")
    if Path(deployment_notification["sentStateDir"]).is_absolute():
        raise SystemExit("Project adapter deploymentNotification.sentStateDir must be project-relative, not an absolute machine path")
    if deployment_notification["webhookEnv"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", deployment_notification["webhookEnv"]):
        raise SystemExit("Project adapter deploymentNotification.webhookEnv must name an environment variable when set")
    effective_deploy_webhook_env = deployment_notification["webhookEnv"]
    if not effective_deploy_webhook_env and deployment_notification["reuseIterationReviewWebhook"]:
        # DEFERRED to the release that ships a second delivering provider (decision-record
        # 2026-08-26). Borrowing another block's endpoint stops being coherent once the two blocks
        # can name different providers -- this block's payload would go to that provider's
        # endpoint. It is unreachable today: reaching it needs two different DELIVERING providers,
        # and this release registers exactly one plus a null peer that is refused while enabled.
        # The successor that adds a second delivering provider owns the check, and owns getting it
        # right for the DISABLED case, which is where the first attempt refused valid adapters.
        effective_deploy_webhook_env = str(delivery.get("webhookEnv") or "")
    if deployment_notification["enabled"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", effective_deploy_webhook_env or ""):
        raise SystemExit(
            "Project adapter deploymentNotification requires webhookEnv or reuseIterationReviewWebhook with iterationReview.delivery.webhookEnv when enabled"
        )
    if (
        deployment_notification["enabled"]
        and deployment_notification["reuseIterationReviewWebhook"]
        and not deployment_notification["webhookEnv"]
        and str(delivery.get("chatSpace") or "").strip()
        and (not deployment_notification["chatSpace"] or deployment_notification_raw is None)
    ):
        deployment_notification["chatSpace"] = str(delivery.get("chatSpace") or "Product").strip()
    if deployment_notification["enabled"] and not deployment_notification["chatSpace"]:
        deployment_notification["chatSpace"] = str(delivery.get("chatSpace") or "Product").strip()
    try:
        deployment_notification["maxChars"] = int(
            deployment_notification.get("maxChars", DEFAULT_DEPLOYMENT_NOTIFICATION["maxChars"])
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter deploymentNotification.maxChars must be a positive integer") from exc
    if deployment_notification["maxChars"] < 100:
        raise SystemExit("Project adapter deploymentNotification.maxChars must be at least 100")
    data["deploymentNotification"] = deployment_notification
    data["milestoneUpdate"] = {
        **DEFAULT_MILESTONE_UPDATE,
        **data.get("milestoneUpdate", {}),
    }
    milestone_update = data["milestoneUpdate"]
    if not isinstance(milestone_update.get("enabled"), bool):
        raise SystemExit("Project adapter milestoneUpdate.enabled must be boolean")
    if not isinstance(milestone_update.get("dedupe"), bool):
        raise SystemExit("Project adapter milestoneUpdate.dedupe must be boolean")
    for key in ["trigger", "provider", "sentStateDir"]:
        value = str(milestone_update.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter milestoneUpdate.{key} must be non-blank")
        milestone_update[key] = value
    milestone_update["webhookEnv"] = str(milestone_update.get("webhookEnv", "")).strip()
    milestone_update["chatSpace"] = str(milestone_update.get("chatSpace", "")).strip()
    if milestone_update["trigger"] not in {"milestone-complete"}:
        raise SystemExit("Project adapter milestoneUpdate.trigger must be milestone-complete")
    validate_notify_provider(milestone_update, "milestoneUpdate")
    if Path(milestone_update["sentStateDir"]).is_absolute():
        raise SystemExit("Project adapter milestoneUpdate.sentStateDir must be project-relative, not an absolute machine path")
    if milestone_update["enabled"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", milestone_update["webhookEnv"]):
        raise SystemExit("Project adapter milestoneUpdate.webhookEnv must name an environment variable when enabled")
    if milestone_update["enabled"] and not milestone_update["chatSpace"]:
        raise SystemExit("Project adapter milestoneUpdate.chatSpace must be non-blank when enabled")
    try:
        milestone_update["maxChars"] = int(milestone_update.get("maxChars", DEFAULT_MILESTONE_UPDATE["maxChars"]))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter milestoneUpdate.maxChars must be a positive integer") from exc
    if milestone_update["maxChars"] < 500:
        raise SystemExit("Project adapter milestoneUpdate.maxChars must be at least 500")
    data["productChat"] = {
        **DEFAULT_PRODUCT_CHAT,
        **data.get("productChat", {}),
    }
    product_chat = data["productChat"]
    if not isinstance(product_chat.get("enabled"), bool):
        raise SystemExit("Project adapter productChat.enabled must be boolean")
    product_chat["provider"] = str(product_chat.get("provider", "")).strip()
    product_chat["webhookEnv"] = str(product_chat.get("webhookEnv", "")).strip()
    product_chat["chatSpace"] = str(product_chat.get("chatSpace", "")).strip()
    validate_notify_provider(product_chat, "productChat")
    if product_chat["enabled"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", product_chat["webhookEnv"]):
        raise SystemExit("Project adapter productChat.webhookEnv must name an environment variable when enabled")
    if product_chat["enabled"] and not product_chat["chatSpace"]:
        raise SystemExit("Project adapter productChat.chatSpace must be non-blank when enabled")
    try:
        product_chat["maxChars"] = int(product_chat.get("maxChars", DEFAULT_PRODUCT_CHAT["maxChars"]))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter productChat.maxChars must be a positive integer") from exc
    if product_chat["maxChars"] < 100:
        raise SystemExit("Project adapter productChat.maxChars must be at least 100")
    video = {**DEFAULT_ITERATION_REVIEW["video"], **iteration_review.get("video", {})}
    music = {**DEFAULT_ITERATION_REVIEW["video"]["music"], **video.get("music", {})}
    if not isinstance(music.get("enabled"), bool):
        raise SystemExit("Project adapter iterationReview.video.music.enabled must be boolean")
    music["source"] = str(music.get("source", "")).strip()
    music["defaultUrl"] = str(music.get("defaultUrl", "")).strip()
    try:
        music["volume"] = float(music.get("volume", 0.18))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter iterationReview.video.music.volume must be a number between 0 and 1") from exc
    if music["source"] not in {"adapter-approved"}:
        raise SystemExit("Project adapter iterationReview.video.music.source must be adapter-approved")
    if music["volume"] < 0 or music["volume"] > 1:
        raise SystemExit("Project adapter iterationReview.video.music.volume must be between 0 and 1")
    video["music"] = music
    iteration_review["video"] = video
    renderer_version = str(iteration_review.get("rendererVersion", "")).strip()
    if not renderer_version:
        raise SystemExit("Project adapter iterationReview.rendererVersion must be non-blank")
    iteration_review["rendererVersion"] = renderer_version
    data["contextRotation"] = {**DEFAULT_CONTEXT_ROTATION, **data.get("contextRotation", {})}
    if not isinstance(data["contextRotation"].get("enabled"), bool):
        raise SystemExit("Project adapter contextRotation.enabled must be boolean")
    for key in ["softPercent", "hardPercent"]:
        try:
            data["contextRotation"][key] = int(data["contextRotation"][key])
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Project adapter contextRotation.{key} must be an integer percent") from exc
        if data["contextRotation"][key] < 1 or data["contextRotation"][key] > 100:
            raise SystemExit(f"Project adapter contextRotation.{key} must be between 1 and 100")
    if data["contextRotation"]["hardPercent"] < data["contextRotation"]["softPercent"]:
        raise SystemExit("Project adapter contextRotation.hardPercent must be greater than or equal to softPercent")
    try:
        data["contextRotation"]["heartbeatMinutes"] = int(data["contextRotation"]["heartbeatMinutes"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter contextRotation.heartbeatMinutes must be a positive integer") from exc
    if data["contextRotation"]["heartbeatMinutes"] < 1:
        raise SystemExit("Project adapter contextRotation.heartbeatMinutes must be a positive integer")
    heartbeat_boundary = str(data["contextRotation"].get("heartbeatBoundary", "")).strip()
    if not heartbeat_boundary:
        raise SystemExit("Project adapter contextRotation.heartbeatBoundary must be non-blank")
    data["contextRotation"]["heartbeatBoundary"] = heartbeat_boundary
    safe_boundaries = data["contextRotation"].get("safeBoundaries")
    if not isinstance(safe_boundaries, list) or not safe_boundaries:
        raise SystemExit("Project adapter contextRotation.safeBoundaries must be a non-empty array")
    normalized_boundaries = []
    for boundary in safe_boundaries:
        value = str(boundary).strip()
        if not value:
            raise SystemExit("Project adapter contextRotation.safeBoundaries must contain non-blank values")
        normalized_boundaries.append(value)
    data["contextRotation"]["safeBoundaries"] = normalized_boundaries
    data["planningArtifacts"] = {**DEFAULT_PLANNING_ARTIFACTS, **data["planningArtifacts"]}
    planning_source = str(data["planningArtifacts"].get("sourceOfTruth", "")).strip().rstrip("/")
    data["goalArtifacts"] = {**DEFAULT_GOAL_ARTIFACTS, **data.get("goalArtifacts", {})}
    data["goalArtifacts"].setdefault("sourceOfTruth", f"{planning_source}/goals" if planning_source else "goals")
    data["goalArtifacts"].setdefault(
        "template",
        f"{str(data['goalArtifacts']['sourceOfTruth']).strip().rstrip('/')}/goal.template.md",
    )
    for key in ["sourceOfTruth", "template", "templateTrigger"]:
        value = str(data["goalArtifacts"].get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter goalArtifacts.{key} must be non-blank")
        if Path(value).is_absolute():
            raise SystemExit(f"Project adapter goalArtifacts.{key} must be project-relative, not an absolute machine path")
        data["goalArtifacts"][key] = value
    if not isinstance(data["goalArtifacts"].get("reviewRequired"), bool):
        raise SystemExit("Project adapter goalArtifacts.reviewRequired must be boolean")
    # PM surfaces: merge default, reject broad globs, normalize to a list (runs AFTER
    # planningArtifacts/goalArtifacts sourceOfTruth so the bounded plan-root guard can read them).
    normalize_product_development(data)
    data["goalExecution"] = {**DEFAULT_GOAL_EXECUTION, **data.get("goalExecution", {})}
    for key in ["preferredClaudeCommand", "fallback"]:
        value = str(data["goalExecution"].get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter goalExecution.{key} must be non-blank")
        data["goalExecution"][key] = value
    if not data["goalExecution"]["preferredClaudeCommand"].startswith("/"):
        raise SystemExit("Project adapter goalExecution.preferredClaudeCommand must be a slash command such as /goal")
    if not isinstance(data["goalExecution"].get("claudeGoalGuidance"), bool):
        raise SystemExit("Project adapter goalExecution.claudeGoalGuidance must be boolean")
    if data["goalExecution"]["fallback"] not in {"goal-ledger"}:
        raise SystemExit("Project adapter goalExecution.fallback must be goal-ledger")
    lane_coordination = {**DEFAULT_LANE_COORDINATION, **data.get("laneCoordination", {})}
    if not isinstance(lane_coordination.get("enabled"), bool):
        raise SystemExit("Project adapter laneCoordination.enabled must be boolean")
    lane_coordination["enforcement"] = str(
        lane_coordination.get("enforcement", DEFAULT_LANE_COORDINATION["enforcement"])
    ).strip()
    if lane_coordination["enforcement"] not in {"warn", "strict"}:
        raise SystemExit("Project adapter laneCoordination.enforcement must be warn or strict")
    coordination_root = str(lane_coordination.get("root") or f"{planning_source}/coordination").strip().rstrip("/")
    if not coordination_root:
        coordination_root = "coordination"
    lane_coordination["root"] = coordination_root
    lane_coordination["contractPath"] = str(
        lane_coordination.get("contractPath") or f"{coordination_root}/cross-lane-contract.md"
    ).strip()
    lane_coordination["boardPath"] = str(
        lane_coordination.get("boardPath") or f"{coordination_root}/lane-board.md"
    ).strip()
    lane_coordination["laneStatusDir"] = str(
        lane_coordination.get("laneStatusDir") or f"{coordination_root}/lanes"
    ).strip().rstrip("/")
    for key in ["root", "contractPath", "boardPath", "laneStatusDir"]:
        value = str(lane_coordination.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter laneCoordination.{key} must be non-blank")
        if Path(value).is_absolute():
            raise SystemExit(f"Project adapter laneCoordination.{key} must be project-relative, not an absolute machine path")
        lane_coordination[key] = value
    try:
        lane_coordination["maxStatusAgeHours"] = int(
            lane_coordination.get("maxStatusAgeHours", DEFAULT_LANE_COORDINATION["maxStatusAgeHours"])
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter laneCoordination.maxStatusAgeHours must be a positive integer") from exc
    if lane_coordination["maxStatusAgeHours"] < 1:
        raise SystemExit("Project adapter laneCoordination.maxStatusAgeHours must be a positive integer")
    lane_coordination["rule"] = str(lane_coordination.get("rule", "")).strip()
    if not lane_coordination["rule"]:
        raise SystemExit("Project adapter laneCoordination.rule must be non-blank")
    data["laneCoordination"] = lane_coordination
    legacy_goal_tracker = normalize_tracker_adapter_config(data.get("goalTracker"), DEFAULT_GOAL_TRACKER, "goalTracker")
    if "backlogProvider" in data:
        backlog_provider = normalize_tracker_adapter_config(data.get("backlogProvider"), DEFAULT_BACKLOG_PROVIDER, "backlogProvider")
    elif legacy_goal_tracker["enabled"]:
        backlog_provider = {
            **DEFAULT_BACKLOG_PROVIDER,
            **goal_tracker_from_backlog_provider(legacy_goal_tracker),
            "itemTypes": ["goal", "milestone"],
            "tacticalPlanningAuthority": "repo",
            "syncMode": "read-select-write-status-links-notes",
            "migrationInterviewPath": DEFAULT_BACKLOG_PROVIDER["migrationInterviewPath"],
            "exportMode": "interview-approved",
        }
    else:
        backlog_provider = normalize_tracker_adapter_config(None, DEFAULT_BACKLOG_PROVIDER, "backlogProvider")
    backlog_provider["doneEvidence"] = normalize_done_evidence(backlog_provider.get("doneEvidence"))
    data["backlogProvider"] = backlog_provider
    data["goalTracker"] = goal_tracker_from_backlog_provider(backlog_provider) if backlog_provider["enabled"] else legacy_goal_tracker
    stakeholder_questions = {
        **DEFAULT_STAKEHOLDER_QUESTIONS,
        **data.get("stakeholderQuestions", {}),
    }
    if not isinstance(stakeholder_questions.get("enabled"), bool):
        raise SystemExit("Project adapter stakeholderQuestions.enabled must be boolean")
    provider_error = issues_provider_validation_error(stakeholder_questions.get("provider"))
    if provider_error:
        raise SystemExit(provider_error)
    for key in [
        "defaultMention",
        "unknownStakeholderPolicy",
        "openLabel",
        "answeredLabel",
        "projectStatusOnOpen",
        "projectStatusOnAnswered",
    ]:
        stakeholder_questions[key] = str(stakeholder_questions.get(key, "")).strip()
    if stakeholder_questions["unknownStakeholderPolicy"] != "ask-human-once":
        raise SystemExit("Project adapter stakeholderQuestions.unknownStakeholderPolicy must be ask-human-once")
    sync_at = stakeholder_questions.get("syncAt", [])
    allowed_sync = {"startup", "milestone-boundary", "pr-boundary", "blocked"}
    if not isinstance(sync_at, list) or any(str(item).strip() not in allowed_sync for item in sync_at):
        raise SystemExit("Project adapter stakeholderQuestions.syncAt must contain only startup, milestone-boundary, pr-boundary, and/or blocked")
    stakeholder_questions["syncAt"] = [str(item).strip() for item in sync_at]
    if stakeholder_questions["enabled"]:
        for key in ["openLabel", "answeredLabel"]:
            if not stakeholder_questions[key]:
                raise SystemExit(f"Project adapter stakeholderQuestions.{key} must be non-blank when enabled")
        if stakeholder_questions["openLabel"] == stakeholder_questions["answeredLabel"]:
            raise SystemExit("Project adapter stakeholderQuestions.openLabel and answeredLabel must differ")
    data["stakeholderQuestions"] = stakeholder_questions
    latest_code = {
        **DEFAULT_LATEST_CODE,
        **data.get("latestCode", {}),
    }
    if not isinstance(latest_code.get("enabled"), bool):
        raise SystemExit("Project adapter latestCode.enabled must be boolean")
    for key in ["remote", "base", "statusFile", "rule"]:
        value = str(latest_code.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter latestCode.{key} must be non-blank")
        latest_code[key] = value
    if Path(latest_code["statusFile"]).is_absolute():
        raise SystemExit("Project adapter latestCode.statusFile must be project-relative, not absolute")
    for key in ["fetchAll", "includeOpenPrs", "includeRemoteBranches"]:
        if not isinstance(latest_code.get(key), bool):
            raise SystemExit(f"Project adapter latestCode.{key} must be boolean")
    try:
        latest_code["maxAgeMinutes"] = int(latest_code["maxAgeMinutes"])
        latest_code["maxAheadBranches"] = int(latest_code["maxAheadBranches"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter latestCode.maxAgeMinutes and maxAheadBranches must be positive integers") from exc
    if latest_code["maxAgeMinutes"] < 1 or latest_code["maxAheadBranches"] < 0:
        raise SystemExit("Project adapter latestCode.maxAgeMinutes must be positive and maxAheadBranches must be non-negative")
    data["latestCode"] = latest_code
    model_effort_policy = {
        **DEFAULT_MODEL_EFFORT_POLICY,
        **data.get("modelEffortPolicy", {}),
    }
    if model_effort_policy["defaultEffort"] not in {"low", "medium", "high", "xhigh"}:
        raise SystemExit("Project adapter modelEffortPolicy.defaultEffort must be low, medium, high, or xhigh")
    model_effort_policy["xhighPolicy"] = str(model_effort_policy.get("xhighPolicy", "")).strip()
    if not model_effort_policy["xhighPolicy"]:
        raise SystemExit("Project adapter modelEffortPolicy.xhighPolicy must be non-blank")
    if not isinstance(model_effort_policy.get("executionPacketSonnetEligible"), bool):
        raise SystemExit("Project adapter modelEffortPolicy.executionPacketSonnetEligible must be boolean")
    data["modelEffortPolicy"] = model_effort_policy
    data["localResourceLocks"] = {**DEFAULT_LOCAL_RESOURCE_LOCKS, **data.get("localResourceLocks", {})}
    data["localResourceIsolation"] = {
        **DEFAULT_LOCAL_RESOURCE_ISOLATION,
        **data.get("localResourceIsolation", {}),
    }
    document_context = {**DEFAULT_DOCUMENT_CONTEXT, **data.get("documentContext", {})}
    if document_context["enforcement"] not in {"warn", "strict"}:
        raise SystemExit("Project adapter documentContext.enforcement must be warn or strict")
    for key in ["contextIndexPaths", "trackedDocRoots", "historicalPaths", "ignoredDocPaths"]:
        if key in document_context and any(not str(path).strip() for path in document_context.get(key, [])):
            raise SystemExit(f"Project adapter documentContext.{key} must contain non-blank paths")
        if key in document_context and any(Path(str(path).strip()).is_absolute() for path in document_context.get(key, [])):
            raise SystemExit(f"Project adapter documentContext.{key} must use project-relative or home-relative paths, not absolute machine paths")
    for key in ["maxIndexBytes", "maxIndexLines"]:
        try:
            document_context[key] = int(document_context[key])
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Project adapter documentContext.{key} must be a positive integer") from exc
        if document_context[key] < 1:
            raise SystemExit(f"Project adapter documentContext.{key} must be a positive integer")
    data["documentContext"] = document_context
    data["ciTestGate"] = normalize_ci_test_gate(data)
    data["uiEvidence"] = normalize_ui_evidence(data)
    data["developmentEnvironment"] = normalize_development_environment(data)
    data["runtimeConfig"] = normalize_runtime_config(data)
    data["criticalJourneys"] = normalize_critical_journeys(data)
    data["migrationSafety"] = normalize_migration_safety(data)
    data["coverageFloor"] = normalize_coverage_floor(data)
    data["planAcceptance"] = normalize_plan_acceptance(data)
    data["flakyQuarantine"] = normalize_flaky_quarantine(data)
    data["healthContract"] = normalize_health_contract(data)
    data["sideEffectProof"] = normalize_side_effect_proof(data)
    missing_commands = [key for key in REQUIRED_COMMANDS if key not in data["commands"]]
    if missing_commands:
        raise SystemExit(f"Project adapter commands missing required keys: {', '.join(missing_commands)}")
    # The 1.x review block normalized here -- roundBudgets, codexWrapper/codexPlanWrapper,
    # codexFastMode, prePushReviewEvidence -- configured the review-round economy, the codex-run
    # wrapper and the pre-push evidence gate. All three were deleted on 2026-08-28 and nothing
    # reads those keys any more; the lean profile spends `review` on a one-sentence norm instead.
    # The block is left on the adapter untouched (the schema still accepts it) rather than
    # validated against defaults for machinery that is gone.
    behavior_missing = [key for key in ["required", "paths", "exemption"] if key not in data["behaviorSpecs"]]
    if behavior_missing:
        raise SystemExit(f"Project adapter behaviorSpecs missing required keys: {', '.join(behavior_missing)}")
    behavior = data["behaviorSpecs"]
    behavior["sourceMaterials"] = behavior.get("sourceMaterials", [])
    behavior["sourceMaterialRule"] = behavior.get(
        "sourceMaterialRule",
        "If reviewed external/customer/business behavior specs are provided, review and adapt them before authoring new scenarios; preserve business intent and document deviations.",
    )
    for key in ["paths", "sourceMaterials"]:
        values = behavior.get(key, [])
        if not isinstance(values, list) or any(not str(value).strip() for value in values):
            raise SystemExit(f"Project adapter behaviorSpecs.{key} must be an array of non-blank strings")
        if any(Path(str(value).strip()).is_absolute() for value in values):
            raise SystemExit(f"Project adapter behaviorSpecs.{key} must use project-relative paths, not absolute machine paths")
    if not str(behavior.get("sourceMaterialRule", "")).strip():
        raise SystemExit("Project adapter behaviorSpecs.sourceMaterialRule must be non-blank")
    role_vocabulary = behavior.get("roleVocabulary", {})
    if role_vocabulary:
        for key in ["allowed", "forbidden"]:
            values = role_vocabulary.get(key, [])
            if not isinstance(values, list) or any(not str(value).strip() for value in values):
                raise SystemExit(f"Project adapter behaviorSpecs.roleVocabulary.{key} must be an array of non-blank strings")
    behavior["pendingTags"] = behavior.get("pendingTags", DEFAULT_BEHAVIOR_PENDING_TAGS)
    if not isinstance(behavior["pendingTags"], list) or any(not str(value).strip() for value in behavior["pendingTags"]):
        raise SystemExit("Project adapter behaviorSpecs.pendingTags must be an array of non-blank strings")
    behavior["inactiveAcceptanceEnforcement"] = str(
        behavior.get("inactiveAcceptanceEnforcement", "strict" if behavior["required"] else "warn")
    ).strip()
    if behavior["inactiveAcceptanceEnforcement"] not in {"warn", "strict"}:
        raise SystemExit("Project adapter behaviorSpecs.inactiveAcceptanceEnforcement must be warn or strict")
    try:
        behavior["maxPendingScenarios"] = int(behavior.get("maxPendingScenarios", 0))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter behaviorSpecs.maxPendingScenarios must be a non-negative integer") from exc
    if behavior["maxPendingScenarios"] < 0:
        raise SystemExit("Project adapter behaviorSpecs.maxPendingScenarios must be a non-negative integer")
    behavior["pendingRequiresOwnerAndTrigger"] = bool(behavior.get("pendingRequiresOwnerAndTrigger", True))
    behavior["acceptanceHarnesses"] = behavior.get("acceptanceHarnesses", DEFAULT_BEHAVIOR_ACCEPTANCE_HARNESSES)
    if not isinstance(behavior["acceptanceHarnesses"], list):
        raise SystemExit("Project adapter behaviorSpecs.acceptanceHarnesses must be an array")
    for index, harness in enumerate(behavior["acceptanceHarnesses"], start=1):
        if not isinstance(harness, dict):
            raise SystemExit(f"Project adapter behaviorSpecs.acceptanceHarnesses[{index}] must be an object")
        for key in ["name", "command", "appPath"]:
            if not str(harness.get(key, "")).strip():
                raise SystemExit(f"Project adapter behaviorSpecs.acceptanceHarnesses[{index}].{key} must be non-blank")
        for key in ["appPath", "command"]:
            value = str(harness[key]).strip()
            if key == "appPath" and Path(value).is_absolute():
                raise SystemExit(f"Project adapter behaviorSpecs.acceptanceHarnesses[{index}].appPath must be project-relative")
        harness["featurePaths"] = harness.get("featurePaths", [])
        harness["targetProof"] = harness.get("targetProof", [])
        for key in ["featurePaths", "targetProof"]:
            values = harness[key]
            if not isinstance(values, list) or any(not str(value).strip() for value in values):
                raise SystemExit(f"Project adapter behaviorSpecs.acceptanceHarnesses[{index}].{key} must be an array of non-blank strings")
            if key == "featurePaths" and any(Path(str(value).strip()).is_absolute() for value in values):
                raise SystemExit(f"Project adapter behaviorSpecs.acceptanceHarnesses[{index}].featurePaths must use project-relative paths")
    data["bugBacklog"] = {**DEFAULT_BUG_BACKLOG, **data.get("bugBacklog", {})}
    for key in ["sourceOfTruth", "severityTaxonomy", "rule"]:
        if not str(data["bugBacklog"].get(key, "")).strip():
            raise SystemExit(f"Project adapter bugBacklog.{key} must be non-blank")
    for key in ["issueMirrors", "autoP0Categories", "autoP1Categories", "requiredFields"]:
        values = data["bugBacklog"].get(key, [])
        if not isinstance(values, list) or any(not str(value).strip() for value in values):
            raise SystemExit(f"Project adapter bugBacklog.{key} must be an array of non-blank strings")
    raw_stack = data.get("technologyStack", {})
    data["technologyStack"] = {**DEFAULT_TECHNOLOGY_STACK, **raw_stack}
    for key in ["cloudProviderDefault", "newProjectCloudDefault", "rule"]:
        value = str(data["technologyStack"].get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter technologyStack.{key} must be non-blank")
        data["technologyStack"][key] = value
    approved_providers = data["technologyStack"].get("approvedCloudProviders", [])
    if not isinstance(approved_providers, list) or any(not str(provider).strip() for provider in approved_providers):
        raise SystemExit("Project adapter technologyStack.approvedCloudProviders must be an array of non-blank strings")
    approved_providers = [str(provider).strip() for provider in approved_providers]
    if not approved_providers:
        raise SystemExit("Project adapter technologyStack.approvedCloudProviders must contain at least one provider")
    data["technologyStack"]["approvedCloudProviders"] = approved_providers
    if data["technologyStack"]["cloudProviderDefault"] not in approved_providers:
        raise SystemExit("Project adapter technologyStack.cloudProviderDefault must appear in approvedCloudProviders")
    if data["technologyStack"]["newProjectCloudDefault"] not in approved_providers:
        raise SystemExit("Project adapter technologyStack.newProjectCloudDefault must appear in approvedCloudProviders")
    if not isinstance(data["technologyStack"].get("newCloudProviderRequiresApproval"), bool):
        raise SystemExit("Project adapter technologyStack.newCloudProviderRequiresApproval must be boolean")
    aws_is_approved = any(provider.upper() == "AWS" for provider in approved_providers)
    if aws_is_approved or "awsCliConvention" in raw_stack:
        value = str(data["technologyStack"].get("awsCliConvention", "")).strip()
        if not value:
            raise SystemExit("Project adapter technologyStack.awsCliConvention must be non-blank")
        data["technologyStack"]["awsCliConvention"] = value
    else:
        data["technologyStack"].pop("awsCliConvention", None)
    stack_rules = data["technologyStack"].get("nonNegotiable", [])
    if not isinstance(stack_rules, list) or any(not str(rule).strip() for rule in stack_rules):
        raise SystemExit("Project adapter technologyStack.nonNegotiable must be an array of non-blank strings")
    data["technologyStack"]["nonNegotiable"] = [str(rule).strip() for rule in stack_rules]
    data["graphify"] = {**DEFAULT_GRAPHIFY, **data.get("graphify", {})}
    graphify = data["graphify"]
    for key in ["enabled", "preferWhenPresent", "gitIgnoreOutput", "allowProjectInstaller"]:
        if not isinstance(graphify.get(key), bool):
            raise SystemExit(f"Project adapter graphify.{key} must be boolean")
    for key in [
        "outputDir",
        "reportPath",
        "graphPath",
        "installPackage",
        "installCommand",
        "setupCommand",
        "buildCommand",
        "updateCommand",
        "queryCommand",
        "pathCommand",
        "explainCommand",
        "freshnessRule",
        "freshnessEnforcement",
        "rule",
        "semanticCommand",
        "semanticRule",
    ]:
        value = str(graphify.get(key, "")).strip()
        if not value:
            raise SystemExit(f"Project adapter graphify.{key} must be non-blank")
        if key in {"outputDir", "reportPath", "graphPath"} and Path(value).is_absolute():
            raise SystemExit(f"Project adapter graphify.{key} must be project-relative, not an absolute machine path")
        graphify[key] = value.rstrip("/") if key == "outputDir" else value
    if graphify["freshnessEnforcement"] not in {"strict-if-present", "warn", "disabled"}:
        raise SystemExit("Project adapter graphify.freshnessEnforcement must be strict-if-present, warn, or disabled")
    if ".." in Path(graphify["outputDir"]).parts:
        raise SystemExit("Project adapter graphify.outputDir must stay inside the project")
    for key in ["reportPath", "graphPath"]:
        if ".." in Path(graphify[key]).parts:
            raise SystemExit(f"Project adapter graphify.{key} must stay inside the project")
    if graphify["outputDir"].strip(".") == "":
        raise SystemExit("Project adapter graphify.outputDir must not be the project root")
    data["deploymentTargets"] = data.get("deploymentTargets", DEFAULT_DEPLOYMENT_TARGETS)
    if not isinstance(data["deploymentTargets"], list):
        raise SystemExit("Project adapter deploymentTargets must be an array when present")
    for index, target_config in enumerate(data["deploymentTargets"]):
        if not isinstance(target_config, dict):
            raise SystemExit(f"Project adapter deploymentTargets[{index}] must be an object")
        required_deploy_fields = ["name", "milestoneClose", "target", "procedure", "healthCheck"]
        missing_deploy_fields = [key for key in required_deploy_fields if key not in target_config]
        if missing_deploy_fields:
            raise SystemExit(
                f"Project adapter deploymentTargets[{index}] missing required keys: {', '.join(missing_deploy_fields)}"
            )
        for key in ["name", "target", "procedure", "healthCheck"]:
            if not str(target_config.get(key, "")).strip():
                raise SystemExit(f"Project adapter deploymentTargets[{index}].{key} must be non-blank")
        if not isinstance(target_config["milestoneClose"], bool):
            raise SystemExit(f"Project adapter deploymentTargets[{index}].milestoneClose must be boolean")
        for key in ["rollback", "buildIdentity"]:
            if key in target_config and not str(target_config.get(key, "")).strip():
                raise SystemExit(f"Project adapter deploymentTargets[{index}].{key} must be non-blank when present")
        signals = target_config.get("outcomeSignals", [])
        if not isinstance(signals, list) or not all(isinstance(s, str) for s in signals):
            raise SystemExit(f"Project adapter deploymentTargets[{index}].outcomeSignals must be a list of strings")
        side_effects = target_config.get("sideEffects", [])
        if not isinstance(side_effects, list) or not all(isinstance(s, dict) for s in side_effects):
            raise SystemExit(f"Project adapter deploymentTargets[{index}].sideEffects must be a list of objects")
        target_config["deployHealth"] = normalize_deploy_health_config(target_config.get("deployHealth"), index)
    continuity_missing = [key for key in ["path", "archiveDir", "gitIgnore"] if key not in data["continuity"]]
    if continuity_missing:
        raise SystemExit(f"Project adapter continuity missing required keys: {', '.join(continuity_missing)}")
    lane_state_missing = [key for key in DEFAULT_LANE_STATE if key not in data["laneState"]]
    if lane_state_missing:
        raise SystemExit(f"Project adapter laneState missing required keys: {', '.join(lane_state_missing)}")
    planning_missing = [
        key
        for key in ["sourceOfTruth", "template", "templateTrigger", "scratchPaths", "rule"]
        if key not in data["planningArtifacts"]
    ]
    if planning_missing:
        raise SystemExit(f"Project adapter planningArtifacts missing required keys: {', '.join(planning_missing)}")
    planning_blank = [
        key
        for key in ["sourceOfTruth", "template", "templateTrigger", "rule"]
        if not str(data["planningArtifacts"].get(key, "")).strip()
    ]
    if planning_blank:
        raise SystemExit(f"Project adapter planningArtifacts has blank required values: {', '.join(planning_blank)}")
    scratch_paths = data["planningArtifacts"].get("scratchPaths", [])
    if not scratch_paths or any(not str(path).strip() for path in scratch_paths):
        raise SystemExit("Project adapter planningArtifacts.scratchPaths must contain at least one non-blank path")
    review_exemptions = data["planningArtifacts"].get("reviewExemptions", [])
    if not isinstance(review_exemptions, list) or any(not str(item).strip() for item in review_exemptions):
        raise SystemExit("Project adapter planningArtifacts.reviewExemptions must be an array of non-blank strings")
    data["planningArtifacts"]["reviewExemptions"] = [str(item).strip() for item in review_exemptions]
    if not str(data["localResourceLocks"].get("locksDir", "")).strip():
        raise SystemExit("Project adapter localResourceLocks.locksDir must be non-blank")
    for index, resource in enumerate(data["localResourceLocks"].get("resources", [])):
        for key in ["name", "reason", "commands"]:
            if key not in resource:
                raise SystemExit(f"Project adapter localResourceLocks.resources[{index}] missing required key: {key}")
        if not str(resource["name"]).strip():
            raise SystemExit(f"Project adapter localResourceLocks.resources[{index}].name must be non-blank")
        if not str(resource["reason"]).strip():
            raise SystemExit(f"Project adapter localResourceLocks.resources[{index}].reason must be non-blank")
        if not resource["commands"] or any(not str(command).strip() for command in resource["commands"]):
            raise SystemExit(f"Project adapter localResourceLocks.resources[{index}].commands must contain non-blank commands")
    isolation = data["localResourceIsolation"]
    if not str(isolation.get("envFile", "")).strip():
        raise SystemExit("Project adapter localResourceIsolation.envFile must be non-blank")
    if not str(isolation.get("composeProjectPrefix", "")).strip():
        raise SystemExit("Project adapter localResourceIsolation.composeProjectPrefix must be non-blank")
    try:
        port_stride = int(isolation.get("portStride", 0))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter localResourceIsolation.portStride must be a positive integer") from exc
    if port_stride < 1:
        raise SystemExit("Project adapter localResourceIsolation.portStride must be a positive integer")
    for index, item in enumerate(isolation.get("portVariables", [])):
        for key in ["name", "base"]:
            if key not in item:
                raise SystemExit(f"Project adapter localResourceIsolation.portVariables[{index}] missing required key: {key}")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(item["name"])):
            raise SystemExit(f"Project adapter localResourceIsolation.portVariables[{index}].name must be an env var name")
        try:
            base_port = int(item["base"])
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"Project adapter localResourceIsolation.portVariables[{index}].base must be an integer"
            ) from exc
        if base_port < 1 or base_port > 65535:
            raise SystemExit(f"Project adapter localResourceIsolation.portVariables[{index}].base must be a valid TCP port")
    for name, template in isolation.get("envTemplates", {}).items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(name)):
            raise SystemExit(f"Project adapter localResourceIsolation.envTemplates key must be an env var name: {name}")
        if not str(template).strip():
            raise SystemExit(f"Project adapter localResourceIsolation.envTemplates.{name} must be non-blank")
    isolated_commands = isolation.get("isolatedCommands", [])
    if any(not str(command).strip() for command in isolated_commands):
        raise SystemExit("Project adapter localResourceIsolation.isolatedCommands must contain non-blank commands")
    readiness_missing = [key for key in ["sources"] if key not in data["readiness"]]
    if readiness_missing:
        raise SystemExit(f"Project adapter readiness missing required keys: {', '.join(readiness_missing)}")
    bootstrap_placeholders = collect_bootstrap_placeholders(data)
    if bootstrap_placeholders:
        raise SystemExit(
            "Project adapter still contains BOOTSTRAP REQUIRED placeholders: "
            + ", ".join(bootstrap_placeholders)
            + ". Replace them before rendering or starting a lane."
        )
    if isinstance(data, dict):
        # Schema validation runs LAST: the per-field validators above emit specific, friendly
        # errors (e.g. "bugBacklog.sourceOfTruth must be non-blank"); the schema is the final net
        # for unknown top-level keys (additionalProperties:false) and type/structure issues they do
        # not cover, so a duplicated minLength/type rule never preempts the dedicated message.
        validate_adapter_schema(data, path)
    # THE ONE PROJECTION SITE, and it is here on purpose. Every downstream reader -- this
    # release's validation, R2's transcriptMarker lookup, R3's gates -- sees the projected
    # registry, so a legacy adapter carrying only `review.codexWrapper` exposes the shimmed
    # `agents.codex.transcriptMarker` and a partial migration is never rejected for a role whose
    # agent the shim would have synthesised. Applying it per-call-site instead is how one seam
    # ends up seeing a different adapter than another.
    #
    # AFTER schema validation, never before: the schema judges what the adopter WROTE.
    #
    # Returns a `ProjectedAdapter`, a dict subclass carrying what the adapter DECLARED before
    # projection. That state must not become an adapter key -- the schema is top-level
    # `additionalProperties: false`, so a key here would make every adapter fail validation.
    if isinstance(data, dict):
        data = agent_compat.effective_agents(data)
    return data


def display_project_arg(project_path: Path) -> str:
    # Canonical, host-OS-independent form: as_posix() always emits forward slashes,
    # so a Windows render and a POSIX render of the same adapter produce identical
    # committed files and resolve on every host. See source_adapter_path().
    # Relativized against the canonical checkout first: the stored value is re-resolved later by
    # source_adapter_path(), and a private adapter only ever exists under the canonical root.
    relative = source_adapter_repo_relative_path(project_path)
    return relative if relative is not None else project_path.resolve().as_posix()


def source_adapter_path(value: str) -> Path:
    """Resolve a stored `_generated.sourceAdapter` value to a filesystem path.

    Renders write the canonical forward-slash form, but a lane adapter produced on
    Windows by an older build may carry backslash separators; normalize them so
    the source adapter still resolves on POSIX hosts.

    A relative value is resolved canonical-first (see methodology_data_roots): the exec root is a
    snapshot that cannot carry a private adapter, and the caller's failure mode is a hard
    "sourceAdapter is missing" on a file that is sitting right there in the canonical checkout.
    The first root wins when the file exists nowhere, so the error message names the canonical
    path an operator can actually fix.
    """
    normalized = str(value).replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute():
        return path
    roots = methodology_data_roots()
    for root in roots:
        candidate = root / path
        if candidate.exists():
            return candidate
    return roots[0] / path


def project_source_arg(data: dict, project_path: Path) -> str:
    generated = data.get("_generated", {})
    if generated.get("sourceAdapter"):
        return str(generated["sourceAdapter"]).replace("\\", "/")
    if project_path.name in (LANE_ADAPTER_FILE, LEGACY_LANE_ADAPTER_FILE):
        return project_path.name
    return display_project_arg(project_path)


def render_project_config(
    data: dict,
    project_arg: str,
    source_path_override: Path | None = None,
    target_root: Path | None = None,
) -> str:
    payload = {key: value for key, value in data.items() if key != "_generated"}
    # productDevelopment is an opt-in PM-surface key; do NOT materialize its default-empty form
    # into the rendered adapter. The in-memory loader always normalizes it (the PM-surface reader
    # relies on that), but an empty surfaces list carries no configuration and an older deployed
    # runtime's schema rejects an unknown top-level key -- so it is rendered only once a surface is
    # actually declared. This keeps a fresh adapter forward-compatible with pre-classifier runtimes.
    pd = payload.get("productDevelopment")
    if isinstance(pd, dict) and not pd.get("surfaces"):
        payload = {key: value for key, value in payload.items() if key != "productDevelopment"}
    source_path = source_path_override or Path(project_arg)
    if not source_path.is_absolute():
        # Canonical-first: from a snapshot exec root a private adapter is absent, the hash degrades
        # to "unavailable", and the SAME commit renders different bytes on a snapshot lane than on
        # a canonical-checkout lane -- and _generated.sourceAdapterSha256 is byte-compared by
        # adapter_drift, which is a gate. That is the same permanent drift ping-pong the fixed-width
        # short commit closes, re-entering through the adapter hash.
        source_path = source_adapter_path(str(source_path))
    source_sha256 = file_sha256(source_path) if source_path.is_file() else "unavailable"
    methodology_commit = running_methodology_commit(short=True)
    adapter_target = target_root or canonical_methodology_repo()
    if adapter_is_methodology_repo(data) and is_repo_local_source_adapter(source_path, adapter_target):
        methodology_commit = "self-referential-methodology-repo"
    # Mode-independent by design (PP-R3-P2-2): `bin/tautline` does not exist in a pipx/pip
    # user's project, while `tautline` resolves on EVERY supported install (the wheel's console
    # script; the install-cli shim on checkout/snapshot machines). The spelling must NOT be
    # mode-conditional — this string is rendered CONTENT, byte-compared by adapter_drift, and a
    # per-mode value would reintroduce the exact mixed-mode ping-pong provenance-stamp
    # equivalence (adapter_stamp_equivalent_content) exists to kill.
    regenerate = f"tautline render-adapters --project {project_arg} --target <project> --write"
    if adapter_is_methodology_repo(data) and is_repo_local_source_adapter(source_path, adapter_target):
        regenerate += " --json-only"
    rendered = {
        **payload,
        "_generated": {
            "doNotEdit": True,
            "source": "Minervit AI Delivery Methodology",
            "sourceAdapter": project_arg,
            "sourceAdapterSha256": source_sha256,
            "methodologyCommit": methodology_commit,
            "pluginVersion": plugin_version(),
            "regenerate": regenerate,
        },
    }
    return json.dumps(rendered, indent=2, sort_keys=True) + "\n"


adapter_provenance_stamps = _adapters_mod.adapter_provenance_stamps


adapter_stamp_equivalent_content = _adapters_mod.adapter_stamp_equivalent_content
generated_markdown_template_version = _adapters_mod.generated_markdown_template_version
markdown_stamp_equivalent_content = _adapters_mod.markdown_stamp_equivalent_content


def _padded_version_tuple(
    left_text: str, right_text: str
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Both version tuples zero-padded to equal length before comparison.

    Not cosmetic: `util.version_tuple` compares tuples by length, so an unpadded "0.42" sorts
    BELOW "0.42.0" and a runtime would refuse its own render as a downgrade -- a false refusal on
    the lane-startup boundary.
    """
    left, right = version_tuple(left_text), version_tuple(right_text)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))


def markdown_render_is_downgrade(on_disk: str, runtime_version: str) -> bool:
    """True when THIS runtime would overwrite a generated Markdown file stamped by a NEWER one.

    Version-only, and the residual is stated in the refusal text rather than hidden: two runtimes
    on different channels at the same VERSION compare equal and the write proceeds, which is
    exactly how the 2026-08-03 incident is described. Detecting that would need the commit in the
    stamp, and a commit hash rendered into every lane's authority document is fleet-visible churn
    this item deliberately does not buy.
    """
    producer = generated_markdown_template_version(on_disk)
    if producer is None:
        return False
    runtime, stamp = _padded_version_tuple(runtime_version, producer)
    return runtime < stamp


def adapter_render_is_downgrade(fresh: str, on_disk: str) -> bool:
    """The JSON twin of markdown_render_is_downgrade, over `_generated.pluginVersion`.

    An equal `pluginVersion` with a differing `methodologyCommit` is NOT a downgrade: that is the
    cross-build case `ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT` already narrates, and duplicating it into
    a refusal would turn an explanatory drift line into a blocked render.
    """
    on_disk_stamps = adapter_provenance_stamps(on_disk)
    fresh_stamps = adapter_provenance_stamps(fresh)
    if not on_disk_stamps or not fresh_stamps:
        return False
    producer = str(on_disk_stamps.get("pluginVersion") or "")
    runtime_version = str(fresh_stamps.get("pluginVersion") or "")
    if not producer or not runtime_version:
        return False
    runtime, stamp = _padded_version_tuple(runtime_version, producer)
    return runtime < stamp


def render_adapter_downgrades(expected: dict[str, str], target: Path) -> list[tuple[Path, str]]:
    """Every expected file whose ON-DISK copy was produced by a newer template than this runtime.

    Shared by the explicit render path's refusal and its `--allow-template-downgrade` narration,
    so the set that is refused and the set that is reported as deliberately downgraded can never
    disagree.
    """
    found: list[tuple[Path, str]] = []
    for rel, content in expected.items():
        dest = target / rel
        try:
            current = dest.read_text(encoding="utf-8") if dest.exists() else None
        except OSError:
            continue
        if current is None:
            continue
        if rel == LANE_ADAPTER_FILE:
            # Stamp equivalence short-circuits BEFORE the downgrade check, deliberately: a file
            # whose only difference is its identity stamp is ALREADY this render, so there is
            # nothing to downgrade. Checking direction first would turn every foreign-stamped but
            # content-identical adapter -- the mixed-mode fleet's normal state -- into a refusal.
            if current == adapter_stamp_equivalent_content(content, current):
                continue
            if adapter_render_is_downgrade(content, current):
                found.append((dest, on_disk_template_stamp(dest)))
        elif rel in GENERATED_MARKDOWN_FILES:
            if current == markdown_stamp_equivalent_content(content, current):
                continue
            if markdown_render_is_downgrade(current, plugin_version()):
                found.append((dest, on_disk_template_stamp(dest)))
    return found


def on_disk_template_stamp(dest: Path) -> str:
    """The producer version recorded in a generated file on disk, Markdown or JSON."""
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    markdown = generated_markdown_template_version(text)
    if markdown:
        return markdown
    stamps = adapter_provenance_stamps(text) or {}
    return str(stamps.get("pluginVersion") or "unknown")


def generated_downgrade_refusal(dest: Path, on_disk_stamp: str, runtime_version: str) -> str:
    """One message, both paths, so the remedy an agent reads never depends on which verb refused.

    Registered in tests/test_refusal_continuations.py's REFUSAL_BUILDERS, which is what actually
    proves the commands named below exist and accept the flags shown -- the print sites are
    passthroughs and carry no words of their own.
    """
    return (
        f"{dest} was produced by template {on_disk_stamp}, NEWER than this runtime "
        f"{runtime_version}; writing would roll it back. Advance this runtime past that template "
        "with `tautline sync-methodology --target .` (or pull the framework checkout by hand), "
        "or, if the downgrade is deliberate, re-render with `tautline render-adapters "
        "--project <source-adapter> --target . --write --allow-template-downgrade`. "
        "Equal-version renders from a different channel or snapshot are NOT detected, so if the "
        "content still differs at the same version, align the runtimes instead."
    )


def init_project_adapter(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    project_name = args.project_name or title_from_slug(target.name)
    output = args.output or repo_local_source_adapter_path(target)
    output = output.resolve()
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Adapter already exists: {output}. Pass --overwrite to replace it.")
    repo_slug = args.repo or infer_repo_slug(target)
    if is_repo_local_source_adapter(output, target):
        schema_path = PUBLIC_ADAPTER_SCHEMA_URL
    else:
        # The canonical checkout, NOT the exec root. Under snapshot execution REPO_ROOT is
        # `<store>/<sha12>` -- an immutable export that prune COLLECTS -- so a path anchored there
        # dangles as soon as the store rotates, in an adapter file that outlives many releases. The
        # canonical checkout is the one methodology tree that persists, and on a dev checkout (and
        # every pre-cutover machine) it IS REPO_ROOT, so this is a no-op there.
        schema_root = canonical_methodology_repo() / "methodology/adapter-schema.json"
        try:
            schema_path = os.path.relpath(schema_root, output.parent)
        except ValueError:
            schema_path = str(schema_root)
    adapter = project_scaffold(project_name, repo_slug, schema_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(adapter, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    print("next: inspect the target repo, record bootstrapEvidence, and replace every BOOTSTRAP REQUIRED placeholder before rendering")
    print("warning: do not copy another project's adapter values as a substitute for facts you verified in this repo")
    print(f"render: tautline render-adapters --project {output} --target {target} --write")
    print(f"check: tautline methodology-status --target {target} --no-remote")
    return 0


def expected_files(
    data: dict,
    project_arg: str,
    source_path_override: Path | None = None,
    target_root: Path | None = None,
) -> dict[str, str]:
    # THE LEAN ADAPTER, rendered by `tautline_methodology.lean` -- the same template `slim` writes.
    #
    # The 430-line template this used to call named 32 verbs the 2026-08-28 process-bankruptcy
    # demolition deleted, starting with `lane-start` as step one of its Session Start. Shipping a
    # renderer that instructs agents to run commands the CLI refuses is a defect on a keep-listed
    # surface, and `adapter_drift` could not see it: both sides of that comparison were equally
    # stale, so drift stayed "clean" while the content was wrong.
    #
    # This consumes Track A's renderer rather than reproducing it, so a fresh project rendered here
    # and a migrated project rewritten by `slim` cannot drift apart -- there is one template. The
    # legacy adapter is projected through `lean_config_from_legacy`, which carries the project's own
    # rules across, so a 1.x adopter keeps their content and loses only the dead instructions.
    lean_cfg = lean.lean_config_from_legacy(data)
    files = {
        target["outputFile"]: lean.render_lean_adapter(lean_cfg, agent=target["agent"])
        for target in RUNTIME_TARGETS
    }
    files[LANE_ADAPTER_FILE] = render_project_config(data, project_arg, source_path_override, target_root)
    return files


def selected_expected_files(
    data: dict,
    project_arg: str,
    json_only: bool = False,
    source_path_override: Path | None = None,
    target_root: Path | None = None,
) -> dict[str, str]:
    files = expected_files(data, project_arg, source_path_override, target_root)
    if json_only:
        return {LANE_ADAPTER_FILE: files[LANE_ADAPTER_FILE]}
    return files


def expected_files_render_context(data: dict, project_path: Path, target: Path) -> tuple[str, Path | None]:
    if is_repo_local_source_adapter(project_path, target):
        return project_path.resolve().relative_to(target.resolve()).as_posix(), project_path
    project_arg = project_source_arg(data, project_path)
    if project_arg in (REPO_LOCAL_ADAPTER_FILE, LEGACY_REPO_LOCAL_ADAPTER_FILE):
        source = repo_local_source_adapter_path(target)
        if source.exists():
            return source.relative_to(target).as_posix(), source
    return project_arg, None


def is_methodology_generated_markdown(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read(len(GENERATED_HEADER_TEMPLATE)) == GENERATED_HEADER_TEMPLATE
    except OSError:
        return False


def protected_handwritten_markdown(expected: dict[str, str], target: Path) -> list[Path]:
    protected: list[Path] = []
    for rel in expected:
        if rel not in GENERATED_MARKDOWN_FILES:
            continue
        dest = target / rel
        if dest.exists() and not is_methodology_generated_markdown(dest):
            protected.append(dest)
    return protected


def render_adapters(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    if find_adapter_root(target) is None:  # --- LEAN INIT WIRING ---
        # Advisory only: prints, never gates. `require_source_adapter_for_target` below still
        # decides whether this invocation succeeds or fails, on exactly the rules it always has.
        print(lean.INIT_NUDGE_LINE, file=sys.stderr)
    require_source_adapter_for_target(args.project.resolve(), target, "render-adapters")
    raw_data = load_raw_adapter_json(args.project)
    data = load_project(args.project)
    omit = str(getattr(args, "omit_domain", "") or "")
    if omit:
        # Downgrade path (item 27): the 0.20.0 schema sets root additionalProperties:false, so a
        # repinned 0.20.x load_project REJECTS any adapter carrying `laneStatus` and normal CLI
        # startup breaks. Deleting the key from adapter SOURCE is not sufficient either, because a
        # 0.21 render materialises the default straight back. This omits it from the generated
        # output so the downgrade has a runnable, ordered procedure.
        if omit not in RENDER_OMITTABLE_DOMAINS:
            raise SystemExit(
                f"render-adapters: --omit-domain accepts only {', '.join(RENDER_OMITTABLE_DOMAINS)}"
            )
        data = {key: value for key, value in data.items() if key != omit}
        raw_data = {key: value for key, value in raw_data.items() if key != omit}
    if "goalTracker" in raw_data:
        # arch-terminology-1: goalTracker is deprecated in favor of backlogProvider. Warn at the
        # authoring/render boundary (not on every load) so the migration is visible without noise.
        print(
            "render_adapters_warning: adapter key 'goalTracker' is DEPRECATED; migrate to "
            "'backlogProvider'",
            file=sys.stderr,
        )
    validate_render_adapter_provenance(data, args.project)
    validate_bootstrap_evidence_for_target(data, args.project, target)
    validate_adapter_repo_matches_target(data, target)
    if args.write or args.check:
        # RCA O17: a re-render reproduces the adapter from canonical source; if a canonical
        # adapter fix is stranded on a local rescue ref (not on the base branch), surface it so
        # the render does not silently reproduce the pre-rescue adapter.
        print_methodology_rescue_ref_warnings()
    if is_repo_local_source_adapter(args.project.resolve(), target):
        project_arg = args.project.resolve().relative_to(target.resolve()).as_posix()
        source_path_override = args.project.resolve()
    else:
        project_arg = project_source_arg(data, args.project)
        source_path_override = None
    # renderBudget is gone (KILL item 4, render-budget machinery). Its `minGeneratedBytes: 15000`
    # FLOOR was a statute-era guard demanding the adapter be large, and it fired on every render
    # the moment the lean template landed -- a control whose verdict was exactly backwards. Its
    # ceiling is not missed either: `lean.render_lean_adapter` enforces a 2KB cap by construction,
    # dropping rules until the file fits rather than reporting that it does not.
    expected = selected_expected_files(data, project_arg, args.json_only, source_path_override, target)
    if args.write:
        protected = protected_handwritten_markdown(expected, target)
        if protected:
            raise SystemExit(protected_markdown_message(protected))
        # getattr with a default is mandatory, not style: render_adapters has programmatic callers
        # that build an argparse.Namespace by hand, and a bare attribute read would raise
        # AttributeError -- which escapes write_framework_channel_to_adapter's
        # `except (OSError, SystemExit)` restore handler and leaves the adapter half-switched.
        allow_downgrade = bool(getattr(args, "allow_template_downgrade", False))
        downgrades = render_adapter_downgrades(expected, target)
        if downgrades and not allow_downgrade:
            # PRINTED with the verb_error: prefix, not raised as a bare SystemExit: the refusal
            # inventory tests/test_refusal_continuations.py walks is scoped to printed prefixes, so
            # a bare SystemExit would make "that suite is green" vacuously true.
            for dest, stamp in downgrades:
                refusal = generated_downgrade_refusal(dest, stamp, plugin_version())
                print(f"render_adapters_error: {refusal}", file=sys.stderr)
            # Record BEFORE raising. A refusal that leaves no trace is the shape of the incident
            # this item exists for: the implicit path already emits adapter_render_refused, and an
            # audit breadcrumb that exists for one render path and not for the first-class explicit
            # one answers "who was stopped" only half the time.
            _narrate_adapter_render(
                data,
                target,
                trigger="render-adapters",
                written=[],
                overwritten=[],
                downgraded=[dest for dest, _stamp in downgrades],
                runtime_version=plugin_version(),
            )
            raise SystemExit(1)
        written_paths: list[Path] = []
        overwritten_paths: list[Path] = []
        for rel, content in expected.items():
            dest = target / rel
            try:
                current = dest.read_text(encoding="utf-8") if dest.exists() else None
            except OSError:
                current = None
            if rel == LANE_ADAPTER_FILE:
                if (
                    current is not None
                    and current == adapter_stamp_equivalent_content(content, current)
                ):
                    # Stamp-only difference: the content is already this render — rewriting
                    # would only flip the identity stamps (the mixed-mode ping-pong).
                    print(f"unchanged {dest} (provenance-stamp-only difference preserved)")
                    continue
            elif rel in GENERATED_MARKDOWN_FILES:
                if (
                    current is not None
                    and current == markdown_stamp_equivalent_content(content, current)
                ):
                    # Item 69: the same anti-churn skip the implicit path now has. Without it a
                    # re-render after a release bump rewrites every generated Markdown file for a
                    # stamp difference and the tree reads dirty for no content reason -- which is
                    # exactly the adapter dirt the review-entry guard then has to talk about.
                    print(f"unchanged {dest} (template-stamp-only difference preserved)")
                    continue
            if current is not None:
                overwritten_paths.append(dest)
            write_text_atomic(dest, content)  # arch-errors-5: crash-safe generated-file write
            print(f"wrote {dest}")
            written_paths.append(dest)
        for dest, stamp in downgrades:
            # The override fired. Say so loudly even on the sanctioned path -- a downgrade nobody
            # can see in the log is the shape of the incident this item exists for.
            print(
                f"generated_downgrade_deliberate: rewrote {dest} from template {stamp} to "
                f"{plugin_version()} (--allow-template-downgrade)"
            )
        _narrate_adapter_render(
            data,
            target,
            trigger="render-adapters",
            written=written_paths,
            overwritten=overwritten_paths,
            downgraded=[],
            runtime_version=plugin_version(),
        )
        return 0
    if args.check:
        failed = False
        protected = protected_handwritten_markdown(expected, target)
        for dest in protected:
            print(f"protected: {dest} (non-generated; use --json-only or migrate before full render)")
            failed = True
        for rel, content in expected.items():
            dest = target / rel
            if dest in protected:
                continue
            current = dest.read_text(encoding="utf-8") if dest.exists() else None
            if rel == LANE_ADAPTER_FILE and current is not None:
                content = adapter_stamp_equivalent_content(content, current)
            if rel in GENERATED_MARKDOWN_FILES and current is not None:
                # Same fleet-safety normalization as adapter_drift (item 69): a stamp-only
                # difference is not drift, in either direction.
                content = markdown_stamp_equivalent_content(content, current)
            if current != content:
                print(f"drift: {dest}")
                failed = True
        return 1 if failed else 0
    for rel, content in expected.items():
        print(f"===== {rel} =====")
        print(content)
    return 0


def load_raw_adapter_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"adapter not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(project_json_decode_error(path, exc)) from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"adapter must be a JSON object: {path}")
    return payload


# The vendor-named command aliases this release renames. Named once, read by the report scoping
# above and by the test that proves each one is wired to a parser -- so a fifth rename cannot be
# added to the CLI and silently left out of the published surfaces.
RENAMED_COMMAND_ALIASES_0_120: frozenset[str] = frozenset(
    {"codex-run", "claude-review", "claude-review-status", "codex-plan-review"}
)


def run_git(target: Path, args: list[str]) -> str:
    return gitutil_module().run_git(target, args)


def methodology_rescue_ref_adapter_changes(repo: Path | None = None) -> list[tuple[str, list[str]]]:
    """Local `tautline-local-rescue/*` (and legacy `minervit-local-rescue/*`) refs in the
    methodology repo that carry canonical adapter
    changes (`adapters/projects/*.json`) not present on the base branch. Lane auto-sync can
    silently move a canonical adapter fix onto a rescue ref; a later lane re-render then
    reproduces the pre-fix adapter (RCA O17). Returns (ref, [adapter_paths]) per affected ref.

    Rescue refs only ever exist in the CANONICAL checkout (rescue is a write path), so a snapshot
    exec root would leave this detector permanently blind and reporting "clean"."""
    repo = repo or canonical_methodology_repo()
    listing = run_git(
        repo,
        [
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads/tautline-local-rescue",
            "refs/heads/minervit-local-rescue",
        ],
    )
    if listing in ("", "unavailable"):
        return []
    base = (
        "origin/main"
        if run_git(repo, ["rev-parse", "--verify", "--quiet", "origin/main"]) not in ("", "unavailable")
        else "main"
    )
    results: list[tuple[str, list[str]]] = []
    for ref in [line.strip() for line in listing.splitlines() if line.strip()]:
        # A rescue ref that is an ANCESTOR of base (old main, merely behind -- e.g. a non-main
        # auto-rescue snapshot of a main that has since advanced) carries nothing un-landed: base
        # already contains it. Skip it. Two-dot tree diff alone would still flag it because base
        # advanced the same adapter files, producing a phantom "stranded fix" hint that has
        # confused operators and contributed to a lane wedge (RCA: rescue-ref detector ancestor
        # false-positive). Only code==0 (definitely an ancestor) skips; an error falls through to
        # report so a genuinely-divergent rescue ref is never silently dropped.
        if run_command(["git", "-C", str(repo), "merge-base", "--is-ancestor", ref, base])[0] == 0:
            continue
        # Two-dot (direct tree compare base vs ref), not three-dot (from merge-base): a rescue
        # adapter change already re-landed on base via cherry-pick/squash has matching content and
        # must not be reported as stranded (Codex P3).
        changed = run_git(repo, ["diff", "--name-only", f"{base}..{ref}", "--", "adapters/projects"])
        if changed in ("", "unavailable"):
            continue
        paths = [p.strip() for p in changed.splitlines() if p.strip()]
        if paths:
            results.append((ref, paths))
    return results


def print_methodology_rescue_ref_warnings(repo: Path | None = None) -> list[tuple[str, list[str]]]:
    """Print a blocking-style warning for each rescue ref that holds canonical adapter changes,
    naming the ref, the affected adapter paths, and a re-land command. Returns the findings."""
    repo = repo or canonical_methodology_repo()
    findings = methodology_rescue_ref_adapter_changes(repo)
    for ref, paths in findings:
        print(
            f"methodology_rescue_ref_adapter_drift: rescue ref {ref} holds canonical adapter changes "
            f"in {', '.join(paths)} that are not on the base branch. A re-render will reproduce the "
            f"pre-rescue adapter. Re-land them with `git -C {repo} cherry-pick`/PR from {ref} before "
            "rendering, or delete the rescue ref with an explicit decision."
        )
    return findings


@contextmanager
def github_command_lock(command: list[str]):
    """Machine-local serialization for GitHub CLI calls so concurrent lanes do not stampede limits."""
    if not command or command[0] != "gh" or util_module().resolve_env("MINERVIT_GITHUB_SERIALIZE", "1") == "0":
        yield
        return
    with ghutil_module().github_command_lock(command):
        yield


def run_command(
    command: list[str],
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        with github_command_lock(command):
            proc = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                env=env,
            )
    except TimeoutError as exc:
        return 124, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.strip() if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
        detail = stderr or stdout or f"command timed out after {timeout}s"
        return 124, stdout, detail
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        # A MISSING BINARY IS A RESULT, NOT A CRASH. Every caller already reads the exit code and
        # decides -- `claude-review-status` maps non-zero to "unavailable" and carries on -- but an
        # uncaught FileNotFoundError turned "that tool is not installed here" into a traceback
        # that took the whole verb down. Found by CI, which is the point: this repository's own
        # suite passed on a machine that happens to have the vendor CLI on PATH and failed on a
        # runner that does not, which is precisely the coupling this program exists to remove.
        # 127 is the shell's own "command not found", so callers that already branch on non-zero
        # need no new vocabulary.
        return 127, "", f"{command[0] if command else 'command'}: {exc}"
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


# --- GITHUB BUDGET STATUS (Tier 1 salvage, track S2) ------------------------------------------
# `github-budget-status` was removed in the 2026-08-28 process-bankruptcy demolition; ghutil.py
# kept its cache/lock/identity PRIMITIVES live throughout (its own docstrings named this verb as
# their intended caller -- see `github_identity_snapshot`), so reconnecting it is orchestration
# only. Plain REST (`gh api rate_limit`), never Projects GraphQL. Read-only except for
# `--identity`, which MINTS this lane's identity record on purpose (see `github_budget_status`).


def command_json(command: list[str], cwd: Path | None = None, timeout: int | None = None) -> tuple[int, object | None, str]:
    code, out, err = run_command(command, cwd, timeout=timeout)
    if code != 0:
        return code, None, err or out
    try:
        return 0, json.loads(out or "null"), ""
    except json.JSONDecodeError as exc:
        return 1, None, f"invalid JSON from {' '.join(command[:3])}: {exc}"


GITHUB_RATE_LIMIT_CHECK_TTL_SECONDS = 30


def github_rate_limit_snapshot(target: Path, max_age: int = GITHUB_RATE_LIMIT_CHECK_TTL_SECONDS) -> dict:
    args = ["api", "rate_limit"]
    cached, _raw = ghutil_module().github_cache_read(args, max_age=max_age)
    if isinstance(cached, dict):
        ghutil_module().github_record_provider_call(
            operation="rate_limit", args=args, target=target, resource="core",
            outcome="cache-hit", cache="rate-limit",
        )
        return cached
    code, payload, error = command_json(["gh", *args], target, timeout=15)
    if code != 0 or not isinstance(payload, dict):
        ghutil_module().github_record_provider_call(
            operation="rate_limit", args=args, target=target, resource="core",
            outcome="error", error=error or "gh api rate_limit failed",
        )
        return {"error": error or "gh api rate_limit failed"}
    ghutil_module().github_cache_write(args, payload)
    ghutil_module().github_record_provider_call(
        operation="rate_limit", args=args, target=target, resource="core",
        outcome="live", cache="write",
    )
    return payload


def github_cache_summary() -> dict:
    root = ghutil_module().github_cache_root()
    files = list(root.glob("*.json")) if root.is_dir() else []
    now = time.time()
    fresh = 0
    stale = 0
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            age = now - float(raw.get("stored_at") or 0)
        except (OSError, json.JSONDecodeError, ValueError):
            stale += 1
            continue
        # Each record stores the argv it was keyed on, and the TTL is per-args: judging a field
        # schema by the generic TTL would report it stale here while the client serves it fresh.
        stored_args = raw.get("args")
        ttl = (
            ghutil_module().github_cache_ttl_for_args([str(item) for item in stored_args])
            if isinstance(stored_args, list)
            else ghutil_module().github_cache_ttl_seconds()
        )
        if age <= ttl:
            fresh += 1
        else:
            stale += 1
    return {"dir": str(root), "entries": len(files), "fresh": fresh, "stale": stale}


def print_github_identity_status(
    target: Path, *, max_age: int | None = None, create_record: bool = True, allow_cold: bool = True,
) -> None:
    """The only identity code in this module (the primitives live in ghutil.py).

    Every failure path prints ONE `unavailable` line and leaves the exit code untouched. That is
    load-bearing rather than tidy: `github-budget-status` has to keep working with no network, no
    `gh`, and no credentials, and an advisory subsystem that can fail its host verb is one that
    gets switched off -- which is the same as never having shipped it.

    `allow_cold` is threaded straight from `--identity` by the one caller below: a bare status
    read only ever returns a warm memo (or nothing), and cold resolution -- the subprocess calls a
    stale/absent memo requires -- happens exactly when an operator asked for identity on purpose.
    """
    # The knob is checked HERE TOO, independently of the verb. `force` used to let a caller print
    # past an explicit stand-down; it is gone, and this check is now unconditional, so a future
    # caller cannot reintroduce the bypass by passing a flag. Defence in depth for a kill switch is
    # cheap; a kill switch with one enforcement point is one refactor from being decorative.
    if not ghutil_module().github_identity_enabled():
        return
    snapshot = ghutil_module().github_identity_snapshot(
        target, max_age=max_age, use_memo=max_age != 0, allow_cold=allow_cold
    )
    if snapshot.get("error"):
        print(f"github_identity: unavailable - {snapshot['error']}")
        return
    if any(not snapshot.get(key) for key in ("login", "fingerprint", "ghHost", "source")):
        # A snapshot missing a field is a partial write or an older shape, not an identity. Printing
        # it would surface `login=None` as a confident answer and, worse, WRITE a record with an
        # empty login that the shared-login predicate would then group other lanes against.
        print("github_identity: unavailable - incomplete identity snapshot")
        return
    print(
        f"github_identity: login={snapshot['login']} host={snapshot['ghHost']} "
        f"source={snapshot['source']} token={snapshot['fingerprint']}"
    )
    # The memo's own coordinates are forwarded, so a warm start pays no `git rev-parse`/`git config`.
    ghutil_module().github_identity_record_write(
        target,
        login=snapshot["login"],
        fingerprint=snapshot["fingerprint"],
        source=snapshot["source"],
        host=snapshot["ghHost"],
        create=create_record,
        lane_key=str(snapshot.get("laneKey") or ""),
        upstream=snapshot.get("upstream"),
    )
    for warning in ghutil_module().github_shared_identity_warnings():
        print(warning)


def github_budget_status(args: argparse.Namespace) -> int:
    """Read-only rate/GraphQL budget + identity report. Restored from the pre-demolition handler.

    `--identity` MINTS; a bare `github-budget-status` does not. An operator running `--identity` is
    explicitly declaring this lane, which is exactly the act the identity record represents, so
    minting there is honest rather than a workaround. A bare `github-budget-status` still only
    reads (memo-or-nothing; see `print_github_identity_status`), which preserves the same split for
    the cold-resolution subprocesses.

    ...and the MASTER KNOB OUTRANKS THE FLAG. `MINERVIT_GITHUB_IDENTITY=0` stands the whole identity
    subsystem down; `--identity` cannot force it back on. A kill switch a flag can defeat is not a
    kill switch.

    ALWAYS EXITS 0. This is a diagnostic verb (Tier 1 salvage rail: findings are printed, never
    enforced) -- an unreachable API, a missing `gh`, or a disabled identity knob is a FINDING this
    verb reports, not a reason to fail whatever called it. (The pre-demolition handler returned 1
    on a rate-limit fetch error; that exit code is the one deliberate behavior change here.)
    """
    target = args.target if args.target else Path(".")
    wants_identity = bool(getattr(args, "identity", False))
    if wants_identity and not ghutil_module().github_identity_enabled():
        print(
            "github_identity: unavailable - MINERVIT_GITHUB_IDENTITY=0 stands the subsystem down; "
            "unset it or set it to 1 to use --identity"
        )
    else:
        print_github_identity_status(
            target,
            max_age=0 if getattr(args, "refresh", False) else None,
            create_record=wants_identity,
            allow_cold=wants_identity,
        )
    snapshot = github_rate_limit_snapshot(
        target, max_age=0 if getattr(args, "refresh", False) else GITHUB_RATE_LIMIT_CHECK_TTL_SECONDS
    )
    if snapshot.get("error"):
        print(f"github_budget_status: unavailable - {snapshot['error']}")
        return 0
    low = ghutil_module().github_low_watermark()
    print(f"github_budget_status: ok low_watermark={low}")
    for name in ["graphql", "core", "search"]:
        resource = ghutil_module().github_rate_resource(snapshot, name)
        if not resource:
            continue
        remaining = resource.get("remaining", "unknown")
        limit = resource.get("limit", "unknown")
        used = resource.get("used", "unknown")
        reset = "unknown"
        try:
            reset = datetime.fromtimestamp(int(resource.get("reset")), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
        state = "low" if name == "graphql" and isinstance(remaining, int) and remaining <= low else "ok"
        print(f"github_budget_{name}: remaining={remaining} used={used} limit={limit} reset={reset} state={state}")
    cache = github_cache_summary()
    print(
        f"github_cache: dir={cache['dir']} entries={cache['entries']} "
        f"fresh={cache['fresh']} stale={cache['stale']} ttl={ghutil_module().github_cache_ttl_seconds()}"
    )
    pending = ghutil_module().github_pending_retry_records()
    recent = ghutil_module().github_recent_provider_calls()
    safe_next = str(pending[0].get("safeNextPoll") or "none") if pending else "none"
    print(
        f"github_provider_health: telemetry={ghutil_module().github_telemetry_path()} "
        f"pending_retries={len(pending)} recent_callers={len(recent)} safe_next_poll={safe_next}"
    )
    for retry in pending[:5]:
        # `reason` can carry a remote error body (a rejected `gh` call's stderr), so it goes
        # through the same sanitization primitive as every other remote-text print in this
        # codebase -- ids included -- rather than a hand-rolled newline-strip-and-cap.
        print(
            "github_provider_pending_retry: "
            f"operation={retry.get('operation', 'unknown')} attempts={retry.get('attempts', 'unknown')} "
            f"safe_next_poll={retry.get('safeNextPoll', 'unknown')} reset={retry.get('reset', 'unknown')} "
            f"reason={util_module().flatten_printable(retry.get('reason', ''), 160)}"
        )
    for call in recent[-5:]:
        print(
            "github_provider_recent_call: "
            f"at={call.get('at', 'unknown')} operation={call.get('operation', 'unknown')} "
            f"resource={call.get('resource', 'unknown')} outcome={call.get('outcome', 'unknown')} "
            f"cache={call.get('cache', 'none')} host={call.get('host', 'unknown')} pid={call.get('pid', 'unknown')}"
        )
    return 0
# --- END GITHUB BUDGET STATUS -------------------------------------------------------------------


def write_text_atomic(path: Path, content: str) -> None:
    return util_module().write_text_atomic(path, content)


def write_text_executable(path: Path, content: str) -> None:
    return util_module().write_text_executable(path, content)


def plugin_manifest() -> dict:
    try:
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"plugin_manifest_error: {PLUGIN_MANIFEST}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit(f"plugin_manifest_error: {PLUGIN_MANIFEST}: expected JSON object")
    for field in ("name", "version"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"plugin_manifest_error: {PLUGIN_MANIFEST}: missing {field}")
    return manifest


def plugin_name() -> str:
    return plugin_manifest()["name"]


def methodology_version() -> str:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise SystemExit(f"missing canonical VERSION file: {VERSION_FILE}") from exc
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise SystemExit(f"invalid canonical VERSION value: {version}")
    return version


def plugin_version() -> str:
    version = methodology_version()
    manifest_version = plugin_manifest()["version"]
    if manifest_version != version:
        raise SystemExit(
            f"version mismatch: VERSION is {version}, plugin manifest is {manifest_version}. "
            "Update VERSION first, then synchronize the plugin manifest, changelog, and release notes."
        )
    return version


RELEASE_ARTIFACT_PATHS = [
    "bin/tautline",
    "bin/minervit-methodology",
    "src/tautline_methodology/__init__.py",
    "src/tautline_methodology/core/__init__.py",
    "src/tautline_methodology/core/paths.py",
    "src/tautline_methodology/core/policy.py",
    "src/tautline_methodology/core/runtime.py",
    "src/tautline_methodology/adapter.py",
    "src/tautline_methodology/adapters.py",
    "src/tautline_methodology/backlog.py",
    # The builder-lane surface: the shared role/board contract, the GitHub verbs, the guard that
    # makes them the only route, and the identity that mints their token. `builder.py` was already
    # shipping unregistered on the base branch -- which means `cut-release` would have checksummed
    # a release that did not include it -- so it is registered here beside the three new modules
    # rather than leaving one quarter of the surface still missing.
    "src/tautline_methodology/builder.py",
    "src/tautline_methodology/builder_github.py",
    "src/tautline_methodology/builder_guard.py",
    "src/tautline_methodology/builder_token.py",
    "src/tautline_methodology/agent_compat.py",
    "src/tautline_methodology/agents.py",
    "src/tautline_methodology/doctor.py",
    "src/tautline_methodology/evidence.py",
    "src/tautline_methodology/health.py",
    "src/tautline_methodology/operator_inbox.py",
    "src/tautline_methodology/work.py",
    "src/tautline_methodology/work_git.py",
    "src/tautline_methodology/runtime_capabilities.py",
    "src/tautline_methodology/cli.py",
    "src/tautline_methodology/gitutil.py",
    "src/tautline_methodology/ghutil.py",
    "src/tautline_methodology/jira_client.py",
    "src/tautline_methodology/lane.py",
    "src/tautline_methodology/lane_status.py",
    "src/tautline_methodology/lean.py",
    "src/tautline_methodology/names.py",
    "src/tautline_methodology/occupancy.py",
    "src/tautline_methodology/paths.py",
    "src/tautline_methodology/profiles.py",
    "src/tautline_methodology/providers.py",
    "src/tautline_methodology/providers_github.py",
    "src/tautline_methodology/providers_jira.py",
    "src/tautline_methodology/providers_notify.py",
    "src/tautline_methodology/public_release.py",
    "src/tautline_methodology/release.py",
    "src/tautline_methodology/releases.py",
    "src/tautline_methodology/stakeholder_question.py",
    "src/tautline_methodology/util.py",
    "methodology/canonical-rules.md",
    "methodology/adapter-schema.json",
    # The lean profile's schema ships beside the 1.x one for the same reason: a release that
    # carried `slim` without the schema its output is written against would leave an adopter
    # unable to validate the config the migration just produced.
    "methodology/adapter-schema-lean.json",
    # R4: capabilities are DATA, so the data file ships with the release the same way the schema
    # does. A release that carried the module without its capability table would report every
    # runtime as zero-capable -- the fail-safe direction, but wrong, and silently so.
    "methodology/runtime-capabilities.json",
    "plugins/tautline-core/.codex-plugin/plugin.json",
]


def cut_release(args: argparse.Namespace) -> int:
    """`cut-release`: build the immutable release boundary for the current VERSION (prod-distribution-1/3).

    Validates VERSION == plugin manifest (fail-closed), computes SHA256 checksums of the distributed
    artifacts, and writes a checksums manifest under docs/releases/. By default it does NOT mutate git
    refs -- it prints the exact signed-tag command for the operator to run deliberately (composes with
    the auto-update trust gate, which can pin/verify that tag). Pass --create-tag to create the
    annotated (or, with --sign, signed) tag locally; pushing is always left to the operator.
    """
    require_dev_checkout("cut-release")
    version = plugin_version()
    tag = f"v{version}"
    checksum_lines: list[str] = []
    for rel in RELEASE_ARTIFACT_PATHS:
        path = REPO_ROOT / rel
        if not path.exists():
            raise SystemExit(f"cut-release: missing release artifact {rel}")
        checksum_lines.append(f"{file_sha256(path)}  {rel}")
    checksums = "\n".join(checksum_lines) + "\n"
    checksum_path = REPO_ROOT / "docs" / "releases" / f"checksums-{tag}.txt"
    dirty = run_git(REPO_ROOT, ["status", "--porcelain"])
    if dirty and dirty != "unavailable":
        print("cut_release_warning: working tree is dirty; a release tag should point at a clean commit", file=sys.stderr)
    existing = run_git(REPO_ROOT, ["tag", "--list", tag])
    print(f"cut_release_version: {version}")
    print(f"cut_release_tag: {tag} ({'exists' if existing == tag else 'new'})")
    print(f"cut_release_checksums: {checksum_path}")
    for line in checksum_lines:
        print(f"  {line}")
    if getattr(args, "dry_run", False):
        print("cut_release_dry_run: no files written, no tag created")
        return 0
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text(checksums, encoding="utf-8")
    print(f"cut_release_written: {checksum_path}")
    tag_flag = "-s" if getattr(args, "sign", False) else "-a"
    tag_cmd = f"git tag {tag_flag} {tag} -m 'tautline {version}'"
    if getattr(args, "create_tag", False):
        if existing == tag and not getattr(args, "force", False):
            raise SystemExit(f"cut-release: tag {tag} already exists; bump VERSION or pass --force")
        cmd = ["git", "-C", str(REPO_ROOT), "tag", tag_flag, tag, "-m", f"tautline {version}"]
        if getattr(args, "force", False):
            cmd.insert(3, "-f")
        code, _out, err = run_command(cmd)
        if code != 0:
            raise SystemExit(f"cut-release: git tag failed: {err.strip()}")
        print(f"cut_release_tagged: {tag} (push deliberately: git push origin {tag})")
    else:
        print(f"cut_release_next: commit the checksums, then create the tag: {tag_cmd}")
        print(f"cut_release_next: then push deliberately: git push origin {tag}")
    return 0


def version_tuple(version: str) -> tuple[int, ...]:
    return util_module().version_tuple(version)


def public_contract_status_for_command(name: str) -> dict:
    if name in DEPRECATED_COMMAND_REPLACEMENTS:
        return {
            "status": "deprecated",
            "replacement": DEPRECATED_COMMAND_REPLACEMENTS[name],
            "removeAfter": "1.0.0",
        }
    if name.endswith("-hook"):
        return {"status": "internal"}
    if name in {
        # The other four names this set carried -- backlog-provider-active-check,
        # dump-policy-phrases, publish-release-update, release-update-status -- were deleted on
        # 2026-08-28. A classifier entry for a command that cannot be registered classifies
        # nothing.
        "dump-instrumentation-schema",
    }:
        return {"status": "internal"}
    if name in {
        # autonomy-directive (0.12.0): ships experimental -- the sibling SessionStart hook plan
        # wires it to a manifest and the directive text/flags can settle before the stable semver
        # policy binds them.
        "autonomy-directive",
        # Restored lean utilities ship experimental while their output contracts settle.
        "work",
        "evidence",
        "health",
        # backlog (0.146.0): ships experimental, and the reason is the jira provider. Its client
        # has never spoken to a live Jira instance -- the endpoints and response shapes come from
        # documentation -- so binding this verb's output and flags to the stable semver policy
        # before first contact would be a promise made on an untested transport. The local and
        # github providers are exercised; the honest label for the surface is the weakest of its
        # three, until a live validation run is recorded.
        "backlog",
        # board / issue / debt (0.147.0): the builder lane's whole GitHub surface. Ships
        # experimental for the same reason "stakeholder-question" below does -- the transport has
        # never spoken to a LIVE GitHub instance, and the ProjectV2 board read leans on GraphQL
        # fields (subIssuesSummary, closedByPullRequestsReferences) whose availability on a given
        # instance is documentation, not observation. Binding the columns, the JSON envelopes and
        # the flags to the stable semver policy before first contact would be a promise made on an
        # untested transport.
        "board",
        "issue",
        "debt",
        "blocker-clear",
        "blocker-declare",
        "blocker-status",
        "claude-review-status",
        # decision-record (0.11.0): ships experimental -- the sibling decisions-report/journal read
        # surface and the standing-directive plans complete the family, so its output/flags can
        # settle before the stable semver policy binds them.
        "decision-record",
        # decisions-report (0.14.0): the read surface over the decision ledger ships experimental
        # alongside decision-record while the ledger CLI family's output/flags settle before the
        # stable semver policy binds them.
        "decisions-report",
        # event-tail / event-log-path / event-rotate (0.147.0): Tier 1 salvage Track S1 -- the
        # tail/locate/rotate surface over the SAME decision-record ledger. Ships experimental
        # alongside decisions-report while the ledger CLI family's output/flags settle before the
        # stable semver policy binds them.
        "event-tail",
        "event-log-path",
        "event-rotate",
        # github-budget-status / stakeholder-question (0.147.0): Tier 1 salvage Track S2. Ship
        # experimental -- both are plain REST against api.github.com, but neither has spoken to a
        # LIVE GitHub instance yet (the endpoints and response shapes come from documentation,
        # same posture "backlog" above ships under for its Jira leg). Binding output/flags to the
        # stable semver policy before first contact would be a promise made on an untested
        # transport. This entry was missing from the classifier when #624 shipped -- the commit
        # hand-edited the generated manifest to say "experimental" without adding it here, so the
        # NEXT regeneration (an unrelated PR) silently reverted both to the "stable" default.
        # test_public_contract_manifest_matches_a_fresh_regeneration pins this from recurring.
        "github-budget-status",
        "stakeholder-question",
        # builder-token / lane-role / builder-env: the builder lane's identity surface. Ships
        # experimental for the same reason "github-budget-status" above does -- the GitHub App
        # endpoints (/app, /app/installations, the access-token exchange) and their response shapes
        # come from documentation, and nothing here has spoken to a LIVE App installation yet.
        # Binding the flags and the --status output to the stable semver policy before first
        # contact would be a promise made on an untested transport. `lane-role` and `builder-env`
        # ship alongside them because the three are one surface: a lane that can take the role but
        # not the identity, or the reverse, is half-configured.
        "builder-token",
        "lane-role",
        "builder-env",
        "guard-check",
        # inbox (0.147.0): Tier 1 salvage Track S1 -- NEW operator-inbox v1 aggregating PENDING
        # decision-record entries across one or more repos. Ships experimental: the pending
        # heuristic (`--next` contains "awaiting") and the multi-repo table shape are both v1 and
        # may still change.
        "inbox",
        # doctor / red-green-check (0.147.0): Tier 1 salvage Track S3. `doctor` ships
        # experimental -- its branch-liveness check is plain REST against `gh`, documentation-
        # derived and not yet exercised against a live GitHub instance, the same untested-
        # transport posture github-budget-status ships under above. `red-green-check` touches no
        # external service at all, but ships experimental alongside it: both are brand-new in
        # this salvage batch, and the report line shapes (OK/FINDING/UNKNOWN(reason);
        # killed/survived/inconclusive) can still settle before the stable semver policy binds
        # them.
        "doctor",
        "red-green-check",
        # maintainer-mode (0.9.17): the machine-scoped standdown verb ships experimental --
        # the same introduce-as-experimental posture the snapshot verbs took -- so its output
        # and flags can settle across the sibling 0.9.18 launcher-regen escalation (which
        # rewrites the arming advisory into a policy-tiered refusal) before the stable semver
        # policy binds them.
        "maintainer-mode",
        "migrate-adapter",
        # product-dev-mode (0.10.8): ships experimental -- the sibling shepherding and
        # path-scoping plans complete its behavior, so its output/flags can settle first.
        "product-dev-mode",
        "prepare-instrumentation-record",
        "publish-instrumentation-record",
        "release-migration-report",
        "public-contract",
        "public-release-check",
        "public-release-export",
        "registry-package",
        "release-drift-check",
        "release-tail",
        # The snapshot store is introduced ahead of its release -> repin -> install-cli cutover and
        # nothing in the fleet executes snapshots yet. Shipping the verbs as `stable` would bind
        # their output and flags to the stable semver policy before a single machine has exercised
        # them; experimental is the same posture the 0.9.0 instrumentation verbs shipped under.
        "snapshot-pin",
        "snapshot-prune",
        "snapshot-status",
        "validate-instrumentation-record",
    }:
        return {"status": "experimental"}
    return {"status": "stable"}


def _env_file_is_selectable(path: Path) -> bool:
    """True when this path should be treated as THE secrets file -- present, or present and
    unreadable.

    `Path.is_file()` does not merely return False for an untraversable parent: it RAISES
    PermissionError, which would take the whole probe down before it printed anything. And when it
    does return False for an unreadable path, the selection falls through to the LEGACY file, so
    the probe reports on a file the operator does not use. Unreadable counts as selected.
    """
    if _env_file_is_unreadable(path):
        return True
    try:
        return path.is_file()
    except OSError:
        return True


def _env_file_is_unreadable(path: Path) -> bool:
    """True when the file EXISTS but this process cannot read it.

    A file that is simply not there is not unreadable -- it is a layer that legitimately holds
    nothing, and reporting it as indeterminate would make `absent` unreachable on the very common
    machine that has no secrets file at all.
    """
    try:
        with path.open("rb"):
            return False
    except FileNotFoundError:
        # Genuinely not there. The common machine has no secrets file at all, and calling that
        # indeterminate would make the escalation predicate unreachable.
        return False
    except IsADirectoryError:
        return True
    except OSError:
        # Everything else -- EACCES on the file, EACCES on a parent directory, EIO. `Path.is_file()`
        # was the original test here and it RETURNS FALSE rather than raising when a parent
        # directory lacks traverse permission, so an inaccessible file holding the secret was
        # reported as a missing one and the probe exited 1: confirmed absent, escalate. Opening the
        # file is what tells the two apart, so the open is the test.
        return True


def secret_status(args: argparse.Namespace) -> int:
    """Where a named secret is reachable from, WITHOUT ever printing its value.

    Item 85 WS1a. The remediation this closes: a refusal that says "the secret is missing" sends a
    lane straight to an operator escalation, when the overwhelmingly common cause is that the value
    IS persisted and the process simply cannot see it -- a session started outside the lane env, or
    the value written under the MINERVIT_ spelling while the resolver prefers the TAUTLINE_ alias.

    "Confirmed absent" therefore has to mean absent from ALL THREE layers, and the exit code says
    which: 0 = reachable, 1 = confirmed absent and an operator escalation is now justified. That
    predicate is what the policy rule needs by name.

    The VALUE is never printed, at any layer, by contract -- only where it was found. A probe that
    echoed the secret to make its own output more helpful would be a credential leak into every
    lane log and CI transcript that ran it.
    """
    name = str(args.name or "").strip()
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        raise SystemExit("secret-status --name must be an UPPER_CASE environment variable name")
    # NOT plain `resolve_user_config_env()`: that returns the preferred path whenever `is_file()`
    # is false, which it is for a legacy config sitting behind a non-traversable directory. The
    # probe would then never look at the inaccessible layer and would print `absent` -- the
    # escalation predicate -- for a layer it had not read, which is the contract this verb exists
    # to keep.
    # Selected through the SAFE selector directly, never `resolve_user_config_env()`: that helper
    # calls `Path.is_file()`, which RAISES for a path behind a non-traversable directory -- so the
    # probe died with a traceback before any of the unreadable-layer handling below could run. A
    # verb whose contract is "tell absent from unreadable" must not crash on the unreadable case.
    config_env = USER_CONFIG_ENV
    if not _env_file_is_selectable(USER_CONFIG_ENV) and _env_file_is_selectable(LEGACY_USER_CONFIG_ENV):
        config_env = LEGACY_USER_CONFIG_ENV
    # Same defect one level up: `is_file()` is False for an unreadable path, so a secrets file the
    # process cannot traverse to silently selected the LEGACY path, and the probe then reported on
    # a file the operator does not use. Unreadable counts as present-and-selected.
    # Legacy is selected only when it ACTUALLY EXISTS. On a first-setup machine neither store is
    # there, and falling back unconditionally told the operator to create the deprecated Minervit
    # store -- correct only for as long as the compatibility fallback survives, and wrong advice on
    # the day it is removed.
    secrets_env = USER_SECRETS_ENV
    if not _env_file_is_selectable(USER_SECRETS_ENV) and _env_file_is_selectable(
        LEGACY_USER_SECRETS_ENV
    ):
        secrets_env = LEGACY_USER_SECRETS_ENV
    # Both spellings are live during the rebrand and resolve_env PREFERS the alias, so a probe that
    # checked only the name it was handed would report `absent` for a value that is present under
    # its sibling -- the exact misdiagnosis this verb exists to prevent.
    names = [name]
    if name.startswith("MINERVIT_"):
        names.insert(0, "TAUTLINE_" + name[len("MINERVIT_"):])
    elif name.startswith("TAUTLINE_"):
        names.append("MINERVIT_" + name[len("TAUTLINE_"):])
    # Through the RESOLVER, once per spelling -- not `os.environ` directly, and not resolve_env on
    # the asked name alone. resolve_env resolves MINERVIT_ -> TAUTLINE_ and NOT the reverse, so a
    # single call would report `absent` for a TAUTLINE_-spelled name whose value is exported under
    # the MINERVIT_ one: this verb's own misdiagnosis, inside the verb. Reading os.environ directly
    # would fix that and break something worth more --
    # `test_no_shipped_source_bypasses_the_resolver`
    # exists so no shipped read can miss a managed alias, which is the same failure one layer up.
    # The legacy fallback's deprecation warning is WANTED here rather than tolerated: it names the
    # exact cause a caller is standing in front of -- the value is under the retired spelling.
    unreadable: list[str] = []
    source = "absent"
    if any(util_module().resolve_env(n).strip() for n in names):
        source = "process-env"
    else:
        for label, path in (("config-env", config_env), ("secrets-file", secrets_env)):
            if _env_file_is_unreadable(path):
                # An unreadable layer is NOT an absent one, and the distinction is this verb's
                # entire job. Collapsing them would send a lane to an operator on the strength of a
                # layer nothing ever read -- a probe reporting a definite answer it did not measure.
                unreadable.append(f"{label}:{path}")
                continue
            if any(user_config_env_value(n, path).strip() for n in names):
                source = f"{label}:{path}"
                break
    print(f"secret_name: {name}")
    # `absent` is not a description here, it is the ESCALATION PREDICATE -- canonical policy 03 and
    # 23 and the risk-tier skill all name this exact marker as the thing that justifies going to an
    # operator. Printing it above an exit code that says "indeterminate" hands an agent the token
    # it was told to act on and relies on it reading the prose underneath. It does not.
    printed_source = "indeterminate" if (source == "absent" and unreadable) else source
    print(f"secret_source: {printed_source}")
    print(f"secret_config_env: {config_env}")
    print(f"secret_secrets_file: {secrets_env}")
    for entry in unreadable:
        print(f"secret_layer_unreadable: {entry}")
    if source == "absent" and unreadable:
        print(
            "secret_next_action: NOT confirmed absent -- the layers above exist but could not be "
            "read, so this probe cannot tell you whether the value is there. Fix the permissions "
            "and re-run; do not escalate on this result"
        )
        return 2
    if source == "absent":
        print(
            "secret_next_action: persist the value in the secrets file above (export NAME=...), "
            "then re-run the failing command; only a value absent from all three layers is an "
            "operator escalation"
        )
        return 1
    if source.startswith(("config-env:", "secrets-file:")):
        # `lane-run` builds its child environment from the CURRENT process environment; it does not
        # source either persisted file. Prescribing it here would send the caller round the same
        # refusal forever -- a remedy that cannot work is worse than none, because it looks like
        # progress. Name the file the value is actually in.
        print(
            f"secret_next_action: the value is persisted but not exported into this process; run "
            f"`set -a; . {shlex.quote(source.split(':', 1)[1])}; set +a` in this shell (or start "
            "the session "
            "through the operator launcher, which sources it) and re-run the failing command"
        )
        return 0
    print(
        "secret_next_action: the value is reachable in this process; re-run the failing command "
        "with this environment (source the config env file first if the failing shell is a "
        "different one)"
    )
    return 0


def registered_subcommand_names() -> list[str]:
    """Every subcommand name registered on the real argparse registry, sourced by scanning this
    file's own `.add_parser(...)` call sites -- the same mechanism the public-contract manifest
    uses (see test_public_contract_freshness.py).
    """
    source = Path(__file__).read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\.add_parser\(\s*['\"]([^'\"]+)['\"]", source)))


def instrumentation_lane_id(target: Path) -> str:
    """sha256(salt + resolved lane path).hexdigest()[:16] -- stable per machine+lane, unlinkable to
    any product without the salt, and distinct across two worktrees that share a directory
    basename (the resolved absolute path, not the basename, is what's hashed)."""
    resolved = str(Path(target).resolve())
    digest = hashlib.sha256(telemetry_salt() + resolved.encode("utf-8")).hexdigest()
    return digest[:16]


def instrumentation_event_log_max_seq(lane_id: str, jsonl_path: Path, retained_rotations: int) -> int:
    """Highest `seq` recorded for `lane_id` across the local event log plus its retained rotations, 0
    when none. Used only to recover the per-lane counter after its persisted state is lost."""
    max_seq = 0
    for path in event_jsonl_read_paths(jsonl_path, retained_rotations):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(record, dict) and record.get("lane_id") == lane_id:
                seq = record.get("seq")
                if isinstance(seq, int) and not isinstance(seq, bool) and seq > max_seq:
                    max_seq = seq
    return max_seq


def allocate_instrumentation_seq(lane_id: str, ts: str, *, jsonl_path: Path | None = None, retained_rotations: int = 0) -> int:
    """Allocate the next seq for `lane_id` and persist it together with the high-water timestamp.

    CALLER CONTRACT: must already hold the shared event-log advisory lock for this lane (the same
    lock append_event_payload() takes around rotate+append) -- this function does its own
    read-modify-write with no locking of its own, so calling it unlocked would let two concurrent
    writers both read the same prior seq and allocate a duplicate.

    Rollback/loss recovery: if the persisted counter is missing (seq == 0) -- the state file was
    deleted, truncated, or the salt survived a state reset -- seed the counter above the highest seq
    already in the local event log before allocating. Otherwise a reset would restart at 1 and reissue
    seqs a published window's remote_max already covers, silently filtering those events out forever.
    The scan runs only in the seq == 0 case (genuine first event OR post-loss), so it costs one log
    read once, not per event. (Residual: a partial rollback to a lower NON-zero seq is not recovered
    here -- documented in docs/backlog METH-FU-INSTRUMENTATION-TELEMETRY-ACCURACY.)"""
    state = read_instrumentation_seq_state(lane_id)
    baseline = state["seq"]
    if baseline == 0 and jsonl_path is not None:
        baseline = instrumentation_event_log_max_seq(lane_id, jsonl_path, retained_rotations)
    seq = baseline + 1
    path = instrumentation_seq_state_path(lane_id)
    write_text_atomic(path, json.dumps({"seq": seq, "high_water_ts": ts}, sort_keys=True) + "\n")
    return seq


def public_contract_manifest_data() -> dict:
    command_names = registered_subcommand_names()
    schema = _adapter_schema() or {}
    adapter_keys = sorted((schema.get("properties") or {}).keys())
    skill_roots = [
        REPO_ROOT / "plugins" / "tautline-core" / "skills",
        REPO_ROOT / "plugins" / "tautline-ops" / "skills",
    ]
    skills = []
    for skill_root in skill_roots:
        if not skill_root.exists():
            continue
        for skill in sorted(skill_root.rglob("SKILL.md")):
            rel = skill.relative_to(skill_root).parent.as_posix()
            name = rel if rel != "." else skill.parent.name
            skills.append(
                {
                    "name": name,
                    **public_contract_status_for_skill(name, rel),
                    "path": skill.relative_to(REPO_ROOT).as_posix(),
                }
            )
    policy_modules = []
    for path in sorted((REPO_ROOT / "methodology").rglob("*")):
        if path.name.startswith(".") or path.is_dir():
            continue
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        if path.name == "public-contract-manifest.json":
            status = "stable"
        elif path.name in {"canonical-rules.md", "adapter-schema.json"}:
            status = "stable"
        else:
            status = "experimental"
        policy_modules.append({"name": rel_path, "status": status, "path": rel_path})
    generated_files = [
        {"name": target["outputFile"], "status": "stable", "runtime": target["runtime"]}
        for target in sorted(RUNTIME_TARGETS, key=lambda item: item["outputFile"])
    ]
    generated_files.extend(
        [
            {"name": LANE_ADAPTER_FILE, "status": "stable"},
            {"name": REPO_LOCAL_ADAPTER_FILE, "status": "stable"},
            {"name": FRAMEWORK_PIN_FILE, "status": "stable"},
        ]
    )
    return {
        "schema": PUBLIC_CONTRACT_MANIFEST_SCHEMA,
        "version": methodology_version(),
        "semverPolicy": {
            "patch": "stable bugfixes only; WIP-safe by default when release report declares wipSafe=true",
            "minor": "additive or deprecating only; no removals",
            "major": "breaking removals only after deprecation window and migration path",
            "recoveryException": "0.148.1 is an intentional compatibility break from public 0.111.0 for the lean workflow reset; see its explicit migration report (wipSafe=false). This is not an additive-only upgrade.",
            "securityException": "a stable surface CONFIRMED to expose adopter data to a remote MAY be hard-disabled ahead of the normal deprecation window in any release, with a REQUIRED migration note and a named replacement; the surface's REMOVAL still follows the normal major-release window",
        },
        "commands": [
            {"name": name, **public_contract_status_for_command(name)}
            for name in command_names
        ],
        "adapterKeys": [
            {"name": name, **public_contract_status_for_adapter_key(name, schema)}
            for name in adapter_keys
        ],
        "generatedFiles": generated_files,
        "skills": skills,
        "policyModules": policy_modules,
    }


def public_contract_manifest_text() -> str:
    return json.dumps(public_contract_manifest_data(), indent=2, sort_keys=True) + "\n"


def public_contract(args: argparse.Namespace) -> int:
    text = public_contract_manifest_text()
    output = (args.output or PUBLIC_CONTRACT_MANIFEST).resolve()
    if args.write:
        write_text_atomic(output, text)
        print(f"public_contract_manifest_written: {output}")
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"public_contract_manifest_check: missing/unreadable {output}: {exc}", file=sys.stderr)
            return 1
        if current != text:
            print(f"public_contract_manifest_check: stale {output}", file=sys.stderr)
            return 1
        print(f"public_contract_manifest_check: ok {output}")
    if args.print_manifest or not (args.write or args.check):
        print(text, end="")
    return 0


def public_release_candidate_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    code, out, _err = run_command(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    )
    if code == 0 and out:
        files = []
        for raw in out.split("\0"):
            if not raw:
                continue
            path = (repo_root / raw).resolve()
            if path.is_file():
                files.append(path)
        return sorted(set(files))
    excluded = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "graphify-out"}
    files = []
    for path in repo_root.rglob("*"):
        if any(part in excluded for part in path.relative_to(repo_root).parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def public_release_private_adapters(repo_root: Path = REPO_ROOT) -> list[dict]:
    return public_release_module().private_adapter_entries(
        repo_root / "adapters" / "projects",
        allowed_source_adapters=PUBLIC_RELEASE_ALLOWED_SOURCE_ADAPTERS,
    )


def public_release_configured_private_terms(private_terms_file: Path | None = None) -> list[str]:
    return public_release_module().configured_private_terms(
        env_value=util_module().resolve_env(PUBLIC_RELEASE_PRIVATE_TERMS_ENV),
        private_terms_file=private_terms_file,
    )


def public_release_private_terms(private_adapters: list[dict], private_terms_file: Path | None = None) -> list[str]:
    return public_release_module().private_terms(
        private_adapters,
        configured_terms=public_release_configured_private_terms(private_terms_file),
        reference_adapter_slug=PUBLIC_REFERENCE_ADAPTER_SLUG,
    )


def public_release_private_terms_source(private_terms_file: Path | None = None) -> str:
    return public_release_module().private_terms_source(
        env_value=util_module().resolve_env(PUBLIC_RELEASE_PRIVATE_TERMS_ENV),
        private_terms_file=private_terms_file,
    )


def public_release_private_terms_file_allowed_for_export(
    private_terms_file: Path | None,
    source_root: Path,
    destination: Path,
) -> tuple[bool, str]:
    return public_release_module().private_terms_file_allowed_for_export(
        private_terms_file,
        source_root,
        destination,
    )


def public_release_private_adapter_history_paths(repo_root: Path = REPO_ROOT) -> list[str]:
    code, out, _err = run_command(
        ["git", "-C", str(repo_root), "log", "--all", "--name-only", "--format="],
        timeout=30,
    )
    if code != 0 or not out:
        return []
    pattern = re.compile(r"^" + PUBLIC_RELEASE_PRIVATE_ADAPTER_PATH_RE + r"$")
    paths = set()
    for line in out.splitlines():
        rel = line.strip()
        if rel and pattern.match(rel):
            paths.add(rel)
    return sorted(paths)


def public_release_allowed_account_like_token(token: str, line: str) -> bool:
    return public_release_module().allowed_account_like_token(
        token,
        line,
        placeholder_account_ids=PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS,
    )


def public_release_git_history_trust_issues(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    code, out, err = run_command(
        ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
        timeout=10,
    )
    if code != 0 or out.strip().lower() != "true":
        detail = err or out or "not a git work tree"
        return [
            (
                "git-history-unavailable",
                repo_root,
                f"cannot verify git history for public release ({detail}); run the release gate from a complete git checkout",
            )
        ]
    code, out, err = run_command(
        ["git", "-C", str(repo_root), "rev-parse", "--is-shallow-repository"],
        timeout=10,
    )
    if code != 0:
        detail = err or out or "shallow status unavailable"
        return [
            (
                "git-history-unavailable",
                repo_root,
                f"cannot verify whether git history is complete ({detail}); run the release gate from a complete git checkout",
            )
        ]
    if out.strip().lower() == "true":
        return [
            (
                "git-history-shallow",
                repo_root,
                "git checkout is shallow; fetch full history before running the public release gate",
            )
        ]
    return []


def public_release_root_commits(repo_root: Path, ref: str = "HEAD") -> set[str]:
    code, out, _err = run_command(
        ["git", "-C", str(repo_root), "rev-list", "--max-parents=0", ref],
        timeout=10,
    )
    if code != 0:
        return set()
    return {line.strip() for line in out.splitlines() if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", line.strip())}


def public_release_same_history_remote_issues(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    local_roots = public_release_root_commits(repo_root)
    if not local_roots:
        return []
    code, out, _err = run_command(
        ["git", "-C", str(repo_root), "for-each-ref", "--format=%(refname)", "refs/remotes"],
        timeout=10,
    )
    if code != 0:
        return []
    issues: list[tuple[str, Path, str]] = []
    seen_remotes: set[str] = set()
    for raw in out.splitlines():
        ref = raw.strip()
        if not ref or ref.endswith("/HEAD"):
            continue
        parts = ref.split("/")
        if len(parts) < 4:
            continue
        remote = parts[2]
        if remote in seen_remotes:
            continue
        remote_roots = public_release_root_commits(repo_root, ref)
        shared = sorted(local_roots & remote_roots)
        if not shared:
            continue
        seen_remotes.add(remote)
        issues.append(
            (
                "same-history-remote",
                repo_root,
                f"target remote '{remote}' shares this repository's root commit {shared[0][:12]}; publish from a clean public-release-export repository instead of a same-history remote",
            )
        )
    return issues


def public_release_add_issue(
    issues: list[dict],
    seen: set[tuple[str, str, int | None, str]],
    code: str,
    path: Path,
    message: str,
    repo_root: Path = REPO_ROOT,
    line: int | None = None,
) -> None:
    public_release_module().add_issue(
        issues,
        seen,
        code,
        path,
        message,
        repo_root=repo_root,
        max_issues_per_rule=PUBLIC_RELEASE_MAX_ISSUES_PER_RULE,
        line=line,
    )


def public_release_issues(
    repo_root: Path = REPO_ROOT,
    private_terms_file: Path | None = None,
    release_update_root: Path | None = None,
) -> list[dict]:
    """Return public-release blockers found under ``repo_root``.

    ``release_update_root`` is used only to evaluate the release-update
    accountability gate ("has this release's update been delivered?"), a
    maintainer-side check. The delivery ledger
    (``docs/releases/release-update-delivery.json``) is export-excluded, so
    it never exists in an exported tree, and the gate is meaningless there.
    Resolution order:

    - If ``release_update_root`` is given explicitly, use it (the export
      path passes the source repo that owns the ledger).
    - Else, if ``repo_root`` itself is a genuine export candidate — it
      carries a valid ``PUBLIC_RELEASE_EXPORT_MARKER`` AND the
      export-excluded ledger is actually absent from that tree — skip the
      release-update issues entirely — a check run *inside* an export has
      no ledger to consult and must not raise spurious, unsatisfiable
      ``release-update-*`` blockers. Both conditions matter: a normal
      maintainer checkout that happens to contain a stray marker file
      still has its ledger, so it is not an export candidate and the gate
      must stay active.
    - Else, fall back to ``repo_root`` (the normal maintainer-repo
      ``public-release-check`` path, where the gate must still fire).
    """
    issues: list[dict] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    private_adapters = public_release_private_adapters(repo_root)
    for entry in private_adapters:
        public_release_add_issue(
            issues,
            seen,
            "private-source-adapter",
            entry["path"],
            f"real product adapter '{entry['project']}' is tracked in the framework repo; move it to {REPO_LOCAL_ADAPTER_FILE} in the adopter repo before public release",
            repo_root,
        )
    for code, path, message in public_release_git_history_trust_issues(repo_root):
        public_release_add_issue(
            issues,
            seen,
            code,
            path,
            message,
            repo_root,
        )
    for code, path, message in public_release_same_history_remote_issues(repo_root):
        public_release_add_issue(
            issues,
            seen,
            code,
            path,
            message,
            repo_root,
        )
    for rel in public_release_private_adapter_history_paths(repo_root):
        public_release_add_issue(
            issues,
            seen,
            "private-adapter-history",
            repo_root / rel,
            "private adapter path remains in git history; rewrite history before flipping this repository public or publish from a clean public repo",
            repo_root,
        )
    # The delivery ledger is export-excluded, so an export tree never carries it.
    # Evaluate release-update accountability against the repository that owns the
    # ledger (the export source), not the scanned tree; otherwise every release
    # reads as undelivered and every export is blocked. When no explicit source
    # is given and the scanned tree is a *genuine* export candidate, the ledger-
    # derived gate is meaningless (it deliberately has no ledger) — skip it rather
    # than falling back to the ledger-less export tree, which would raise the same
    # unsatisfiable blockers a second time (e.g. `public-release-check` run from
    # inside a generated export).
    #
    # Marker presence alone is not proof of that: a normal maintainer checkout
    # can contain a stray, untracked, or leftover marker file without being an
    # export at all, and its ledger is still right there. So require both: a
    # marker that actually validates as an export marker (schema-checked, not
    # just any file with the right name) AND the ledger genuinely absent from
    # this tree. A real export satisfies both (the export writes the marker and
    # excludes the ledger); a stray marker in a normal checkout satisfies only
    # the first, so the gate correctly stays active.
    delivery_root: Path | None
    if release_update_root is not None:
        delivery_root = release_update_root
    elif public_release_export_destination_is_prior_export(repo_root) and not (
        repo_root / RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH
    ).exists():
        delivery_root = None
    else:
        delivery_root = repo_root
    if delivery_root is not None:
        for code, path, message in release_update_public_release_issues(delivery_root):
            public_release_add_issue(issues, seen, code, path, message, delivery_root)

    private_terms = public_release_private_terms(private_adapters, private_terms_file)
    private_path_pattern = re.compile(PUBLIC_RELEASE_PRIVATE_ADAPTER_PATH_RE)
    account_id_pattern = re.compile(r"(?<!\d)\d{12}(?!\d)")
    url_pattern = re.compile(r"https?://[^\s\"'<>]+")
    private_term_pattern = (
        re.compile(r"\b(" + "|".join(re.escape(term) for term in private_terms) + r")\b", re.I)
        if private_terms
        else None
    )

    for path in public_release_candidate_files(repo_root):
        try:
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        is_private_adapter = rel.startswith("adapters/projects/") and path.name not in PUBLIC_RELEASE_ALLOWED_SOURCE_ADAPTERS
        for lineno, line in enumerate(text.splitlines(), 1):
            # Digest fragments (a 12-digit run that is interior to a sha/git-object hex
            # token) are filtered at the token level by allowed_account_like_token(), so
            # every path that quotes a digest -- .plan-reviews/, .impl-reviews/, plan
            # evidence headers, changelogs, checksum manifests -- is covered at once, and
            # a real account id sharing a line with a digest is still reported.
            for account_id_match in account_id_pattern.finditer(line):
                account_id = account_id_match.group(0)
                if public_release_allowed_account_like_token(account_id, line):
                    continue
                public_release_add_issue(
                    issues,
                    seen,
                    "account-id",
                    path,
                    "12-digit account-like identifier must not ship in public repo",
                    repo_root,
                    lineno,
                )
                break
            if private_path_pattern.search(line):
                public_release_add_issue(
                    issues,
                    seen,
                    "private-adapter-path",
                    path,
                    "public surface references a non-example adapter path",
                    repo_root,
                    lineno,
                )
            if is_private_adapter and url_pattern.search(line):
                public_release_add_issue(
                    issues,
                    seen,
                    "live-host-in-private-adapter",
                    path,
                    "private adapter contains a URL or host-like endpoint; move adapter private before public release",
                    repo_root,
                    lineno,
                )
            if private_term_pattern and not rel.startswith("adapters/projects/") and private_term_pattern.search(line):
                public_release_add_issue(
                    issues,
                    seen,
                    "private-product-reference",
                    path,
                    "public surface references a real product/client adapter name",
                    repo_root,
                    lineno,
                )
    return issues


def public_release_check(args: argparse.Namespace) -> int:
    require_dev_checkout("public-release-check")
    private_terms_file = getattr(args, "private_terms_file", None)
    issues = public_release_issues(private_terms_file=private_terms_file)
    payload = {"ok": not issues, "issues": issues}
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif issues:
        print("public_release_check: blocked")
        for issue in issues:
            location = issue["path"]
            if "line" in issue:
                location = f"{location}:{issue['line']}"
            print(f"- {issue['code']} {location}: {issue['message']}")
        print(
            "public_release_next: move each real source adapter into its own repo (copy it to "
            "`<repo>/.tautline/adapter.json`, then `tautline render-adapters --project "
            "<repo>/.tautline/adapter.json --target <repo> --write`), re-render active lanes from "
            "those repo-local adapters, then remove private adapter files and references before "
            "open source release."
        )
    else:
        print("public_release_check: ok")
    return 1 if issues else 0


def public_release_export_path_included(rel: Path) -> bool:
    return public_release_module().export_path_included(
        rel,
        allowed_product_docs=PUBLIC_RELEASE_EXPORT_ALLOWED_PRODUCT_DOCS,
        excluded_prefixes=PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES,
    )


def public_release_export_files(repo_root: Path = REPO_ROOT, include_untracked: bool = False) -> list[tuple[Path, Path]]:
    root = repo_root.resolve()
    files: list[tuple[Path, Path]] = []
    command = ["git", "-C", str(root), "ls-files", "-z", "--cached"]
    if include_untracked:
        command.extend(["--others", "--exclude-standard"])
    code, out, _err = run_command(command)
    if code != 0:
        raise SystemExit("public-release-export: destination source must be a git worktree")
    for raw in out.split("\0"):
        if not raw:
            continue
        rel = Path(raw)
        if rel.is_absolute() or ".." in rel.parts or (rel.parts and rel.parts[0] == ".git"):
            raise SystemExit(f"public-release-export: unsafe tracked path: {raw}")
        if not public_release_export_path_included(rel):
            continue
        source_path = root / rel
        if source_path.is_symlink():
            link_target = os.readlink(source_path)
            if os.path.isabs(link_target):
                raise SystemExit(f"public-release-export: absolute symlink targets are not exported: {rel.as_posix()}")
            logical_target = Path(posixpath.normpath(posixpath.join(rel.parent.as_posix(), link_target)))
            if logical_target.is_absolute() or ".." in logical_target.parts:
                raise SystemExit(
                    f"public-release-export: symlink target escapes or is missing: {rel.as_posix()} -> {link_target}"
                )
            try:
                resolved_target = source_path.resolve(strict=True)
                resolved_target.relative_to(root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise SystemExit(
                    f"public-release-export: symlink target escapes or is missing: {rel.as_posix()} -> {link_target}"
                ) from exc
            files.append((source_path, rel))
            continue
        path = source_path.resolve()
        if not path.is_file():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            raise SystemExit(f"public-release-export: tracked path resolves outside repository: {raw}")
        files.append((path, rel))
    return sorted(files, key=lambda item: item[1].as_posix())


def public_release_dirty_state_path_included(rel: Path) -> bool:
    """Whether ``rel`` should count toward the export's dirty/untracked gates.

    This is deliberately NOT the same predicate as
    ``public_release_export_path_included()``: "excluded from the exported
    tree" (don't ship it) and "excluded from the dirty-state gate" (don't
    refuse the export over its working-tree state) are two different
    concerns. Almost every export-excluded path is also fine to leave dirty
    or untracked (see
    ``test_public_release_export_ignores_dirty_and_untracked_excluded_internal_docs``).
    The one exception is the release-update delivery ledger: it is
    export-excluded (the export tree must not carry an internal ops record),
    but ``public_release_issues()`` re-roots the release-update gate to read
    that ledger from the SOURCE working tree via ``release_update_root``. If
    an uncommitted ledger change didn't count as dirty, someone could run
    `publish-release-update`, leave it uncommitted, and still pass the
    export's release-update gate on the strength of content that was never
    committed. Counting the ledger here restores the pre-export-exclusion
    invariant: a dirty or untracked ledger makes the export refuse.
    """
    if public_release_export_path_included(rel):
        return True
    return rel.as_posix() == RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH


def public_release_untracked_export_paths(repo_root: Path = REPO_ROOT) -> list[str]:
    code, out, err = run_command(["git", "-C", str(repo_root), "ls-files", "-z", "--others", "--exclude-standard"])
    if code != 0:
        detail = err or out or "git ls-files failed"
        raise SystemExit(f"public-release-export: cannot inspect untracked files: {detail}")
    return sorted(raw for raw in out.split("\0") if raw and public_release_dirty_state_path_included(Path(raw)))


def public_release_dirty_tracked_paths(repo_root: Path = REPO_ROOT) -> list[str]:
    paths: set[str] = set()
    for args in (
        ["diff", "--name-only"],
        ["diff", "--cached", "--name-only"],
    ):
        code, out, err = run_command(["git", "-C", str(repo_root), *args])
        if code != 0:
            detail = err or out or "git diff failed"
            raise SystemExit(f"public-release-export: cannot inspect dirty tracked files: {detail}")
        paths.update(
            line.strip()
            for line in out.splitlines()
            if line.strip() and public_release_dirty_state_path_included(Path(line.strip()))
        )
    return sorted(paths)


def public_release_export_marker_text(
    private_terms_source: str = "none",
    private_terms_count: int = 0,
) -> str:
    return public_release_module().export_marker_text(
        version=plugin_version(),
        marker_schema=PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
        private_terms_source=private_terms_source,
        private_terms_count=private_terms_count,
    )


def public_release_export_destination_is_prior_export(destination: Path) -> bool:
    return public_release_module().export_destination_is_prior_export(
        destination,
        marker_name=PUBLIC_RELEASE_EXPORT_MARKER,
        marker_schema=PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
    )


def init_public_release_export_repo(destination: Path) -> str:
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "public-release-export@example.invalid"],
        ["git", "config", "user.name", "Minervit Public Release Export"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--no-verify",
            "-q",
            "-m",
            f"Initial public release candidate {plugin_version()}",
        ],
    ]
    for command in commands:
        code, out, err = run_command(command, cwd=destination, timeout=60)
        if code != 0:
            detail = err or out or "unknown git error"
            raise SystemExit(f"public-release-export: {' '.join(command)} failed: {detail}")
    return run_git(destination, ["rev-parse", "--short", "HEAD"])


def public_release_export_repository(
    source_root: Path,
    destination: Path,
    force: bool = False,
    include_untracked: bool = False,
    include_working_tree: bool = False,
    private_terms_file: Path | None = None,
) -> dict:
    source = source_root.resolve()
    dest = destination.resolve()
    if dest == source or source in dest.parents or dest in source.parents:
        raise SystemExit("public-release-export: destination must be outside the methodology repository")
    dirty_tracked = public_release_dirty_tracked_paths(source)
    if dirty_tracked and not include_working_tree:
        raise SystemExit(
            "public-release-export: dirty tracked files are not exported by default; "
            "commit them or pass --include-working-tree only for an in-progress validation export"
        )
    # The release-update gate below is re-rooted to read the delivery ledger from
    # `source` (release_update_root=source) rather than the export tree, because the
    # ledger is export-excluded. public_release_dirty_tracked_paths() only inspects
    # `git diff`, which never reports untracked files, so an untracked ledger sails
    # past that check even though it is just as uncommitted as a dirty tracked one.
    # Refuse it here, narrowly -- only the ledger, not arbitrary untracked files; the
    # CLI wrapper already owns the general untracked-file policy for everything else.
    if not include_untracked and RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH in public_release_untracked_export_paths(
        source
    ):
        raise SystemExit(
            f"public-release-export: {RELEASE_UPDATE_DELIVERY_EXPORT_RELATIVE_PATH} is untracked in the source "
            "repository; commit it before export, or pass --include-untracked only for an in-progress validation export"
        )
    dest_exists = dest.exists()
    dest_has_entries = dest_exists and any(dest.iterdir())
    if dest_has_entries and not force:
        raise SystemExit(f"public-release-export: destination is not empty; pass --force to replace it: {dest}")
    if dest_has_entries and force and not public_release_export_destination_is_prior_export(dest):
        raise SystemExit(
            "public-release-export: --force only replaces a prior public-release-export destination "
            f"containing {PUBLIC_RELEASE_EXPORT_MARKER}; choose an empty directory or remove it manually"
        )
    files = public_release_export_files(source, include_untracked=include_untracked)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for source_file, rel in files:
        target_file = dest / rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if source_file.is_symlink():
            target_file.symlink_to(os.readlink(source_file))
        else:
            shutil.copy2(source_file, target_file)
    private_terms = public_release_private_terms(public_release_private_adapters(source), private_terms_file)
    (dest / PUBLIC_RELEASE_EXPORT_MARKER).write_text(
        public_release_export_marker_text(
            private_terms_source=public_release_private_terms_source(private_terms_file),
            private_terms_count=len(private_terms),
        ),
        encoding="utf-8",
    )
    commit = init_public_release_export_repo(dest)
    issues = public_release_issues(dest, private_terms_file=private_terms_file, release_update_root=source)
    return {"files": len(files), "commit": commit, "issues": issues}


def public_release_export(args: argparse.Namespace) -> int:
    require_dev_checkout("public-release-export")
    private_terms_file = getattr(args, "private_terms_file", None)
    destination = args.destination.resolve()
    terms_file_ok, terms_file_error = public_release_private_terms_file_allowed_for_export(
        private_terms_file,
        REPO_ROOT,
        destination,
    )
    if not terms_file_ok:
        print(f"public_release_export_error: {terms_file_error}", file=sys.stderr)
        return 2
    files = public_release_export_files(REPO_ROOT, include_untracked=args.include_untracked)
    private_terms = public_release_private_terms(public_release_private_adapters(REPO_ROOT), private_terms_file)
    dirty_tracked = public_release_dirty_tracked_paths(REPO_ROOT)
    untracked = public_release_untracked_export_paths(REPO_ROOT)
    print(f"public_release_export_mode: {'write' if args.write else 'dry-run'}")
    print(f"public_release_export_source: {REPO_ROOT}")
    print(f"public_release_export_destination: {destination}")
    print(f"public_release_export_files: {len(files)}")
    print(f"public_release_export_private_terms_source: {public_release_private_terms_source(private_terms_file)}")
    print(f"public_release_export_private_terms_count: {len(private_terms)}")
    print(f"public_release_export_dirty_tracked_files: {len(dirty_tracked)}")
    for rel in dirty_tracked[:10]:
        print(f"public_release_export_dirty_tracked_sample: {rel}")
    print(f"public_release_export_untracked_files: {len(untracked)}")
    for rel in untracked[:10]:
        print(f"public_release_export_untracked_sample: {rel}")
    if dirty_tracked and not args.include_working_tree:
        print(
            "public_release_export_error: dirty tracked files are not exported by default; "
            "commit them or pass --include-working-tree only for an in-progress validation export",
            file=sys.stderr,
        )
        return 2
    if untracked and not args.include_untracked:
        print(
            "public_release_export_error: untracked files are not exported by default; "
            "commit them, ignore them, or pass --include-untracked only for an in-progress validation export",
            file=sys.stderr,
        )
        return 2
    if not private_terms and not args.allow_empty_private_terms:
        print(
            "public_release_export_error: no private product/client terms configured; "
            f"set {PUBLIC_RELEASE_PRIVATE_TERMS_ENV}, pass --private-terms-file, "
            "or pass --allow-empty-private-terms only for repos with no private terms",
            file=sys.stderr,
        )
        return 2
    if not args.write:
        print("public_release_export_written: no")
        print("public_release_export_next: rerun with --write to create a clean git repository candidate")
        return 0
    result = public_release_export_repository(
        REPO_ROOT,
        destination,
        force=args.force,
        include_untracked=args.include_untracked,
        include_working_tree=args.include_working_tree,
        private_terms_file=private_terms_file,
    )
    print(f"public_release_export_written: {destination}")
    print(f"public_release_export_commit: {result['commit']}")
    issues = result["issues"]
    if issues:
        print("public_release_export_check: blocked")
        for issue in issues:
            location = issue["path"]
            if "line" in issue:
                location = f"{location}:{issue['line']}"
            print(f"- {issue['code']} {location}: {issue['message']}")
        print(
            "public_release_export_warning: delete the entire blocked candidate directory, "
            f"including its .git history, before sharing it: {destination}"
        )
        return 1
    print("public_release_export_check: ok")
    print("public_release_export_next: push this clean repository to the public remote only after release approval")
    return 0


# ---------------------------------------------------------------------------
# Release tail: registry packages, mirror publish, drift detection.
#
# The registry determines the payload. The npm package is a NAMESPACE POINTER:
# it reserves the name and points at the repository without installing the CLI.
# The PyPI package is REAL: a thin wrapper package plus the full committed tree
# embedded under src/tautline/_dist/, stamped with a build-time snapshot
# manifest. There is deliberately no --payload flag -- after 0.10.0 a pointer
# PyPI build has no legitimate caller, and a flag would be a way to publish the
# wrong thing. All registry copy is generated from here -- because the last
# hand-written copy promised "a native package install lands with the 0.9.0
# package split", which was untrue when it was published and stayed on both
# registries for months. Generated copy cannot drift from the truth by neglect.
# ---------------------------------------------------------------------------
REGISTRY_PACKAGE_NAME = "tautline"
# The description forks per registry because the PAYLOADS differ: the PyPI package
# installs the real CLI, while the npm package remains a namespace pointer whose
# truthful job is to point at pipx. One shared sentence would lie on one side.
_REGISTRY_PACKAGE_DESCRIPTION_LEAD = (
    "Tautline - fast, coordinated AI development. Shared work declarations, "
    "portable project instructions, handoffs, and optional verification receipts."
)
REGISTRY_PACKAGE_DESCRIPTIONS = {
    "npm": (
        _REGISTRY_PACKAGE_DESCRIPTION_LEAD
        + " Tautline is a Python CLI: install it with pipx install tautline."
    ),
    "pypi": _REGISTRY_PACKAGE_DESCRIPTION_LEAD,
}


def registry_package_readme(registry: str) -> str:
    """The per-registry README.

    Every claim here must be true today. No roadmap promise, no future-tense
    install instruction -- only what actually works right now, which DIFFERS by
    registry since the real PyPI payload landed: the PyPI package installs the
    real CLI, while the npm package remains a namespace pointer whose truthful
    job is to point at pipx.
    """
    repo_url = f"https://github.com/tautlines/{REGISTRY_PACKAGE_NAME}"
    header = (
        "# Tautline\n"
        "\n"
        "Fast, coordinated AI development.\n"
        "\n"
    )
    links = (
        "## Links\n"
        "\n"
        f"- Source: {repo_url}\n"
        f"- Roadmap: {repo_url}/blob/main/ROADMAP.md\n"
        f"- Issues: {repo_url}/issues\n"
        "- License: MIT\n"
    )
    if registry == "npm":
        body = (
            "## Install\n"
            "\n"
            "Tautline is a Python CLI. Install it with pipx:\n"
            "\n"
            "```\n"
            f"pipx install {REGISTRY_PACKAGE_NAME}\n"
            "```\n"
            "\n"
            f"The CLI ships on PyPI. This npm package reserves the `{REGISTRY_PACKAGE_NAME}`\n"
            "name and contains no code.\n"
            "\n"
            f"Source and documentation: {repo_url}\n"
            "\n"
        )
    elif registry == "pypi":
        body = (
            "## Install\n"
            "\n"
            f"Requires Python {PYTHON_FLOOR}+.\n"
            "\n"
            "```\n"
            f"pipx install {REGISTRY_PACKAGE_NAME}\n"
            "```\n"
            "\n"
            "Or into an existing virtualenv:\n"
            "\n"
            "```\n"
            f"pip install {REGISTRY_PACKAGE_NAME}\n"
            "```\n"
            "\n"
            "Updates arrive through the same channel: `pipx upgrade tautline` or\n"
            "`pip install -U tautline`.\n"
            "\n"
            "## Full runtime from a checkout\n"
            "\n"
            "The installed package is a stamped snapshot of one release; it updates only\n"
            "when you update it. For the auto-updating runtime, use the checkout mode:\n"
            "\n"
            "```\n"
            f"git clone {repo_url}\n"
            f"cd {REGISTRY_PACKAGE_NAME}\n"
            "bin/tautline install-cli\n"
            "```\n"
            "\n"
        )
    else:
        raise SystemExit(
            f"registry-package: unknown registry {registry!r}; "
            f"expected one of {', '.join(REGISTRY_PACKAGE_REGISTRIES)}"
        )
    return header + body + links


registry_package_license = _release_mod.registry_package_license


def registry_package_npm_manifest(version: str) -> str:
    # npm's trusted publishing compares `repository.url` against the OIDC claim, which
    # carries GitHub's canonical `owner/repo` — and npm documents the comparison as
    # case-sensitive. The canonical owner is `Tautlines`, not `tautlines`; publishing
    # 0.9.8 with the lowercase spelling failed with ENEEDAUTH because the OIDC exchange
    # returned no token and npm fell back to asking for a login. Use REGISTRY_PACKAGE_REPO_SLUG.
    repo_url = f"https://github.com/{REGISTRY_PACKAGE_REPO_SLUG}"
    manifest = {
        "name": REGISTRY_PACKAGE_NAME,
        "version": version,
        "description": REGISTRY_PACKAGE_DESCRIPTIONS["npm"],
        "homepage": repo_url,
        "repository": {"type": "git", "url": f"git+{repo_url}.git"},
        "bugs": f"{repo_url}/issues",
        "license": "MIT",
        "keywords": ["ai", "agents", "claude", "codex", "governance", "delivery", "framework"],
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def registry_package_pyproject(version: str) -> str:
    """pyproject.toml for the REAL PyPI package (wrapper + embedded tree).

    Both console scripts are load-bearing: today's plugin hooks and older rendered
    adapters invoke the legacy `minervit-methodology` name. `python -m build` builds
    the wheel FROM the sdist, so the embedded `_dist/` tree is force-included in BOTH
    build targets -- hatchling's default file selection honors ignore rules, and a
    dotfile silently missing from the sdist would silently vanish from the wheel.
    """
    # PyPI does not compare these case-sensitively, but they are the same registry
    # package metadata family as registry_package_npm_manifest()'s repository.url, so
    # they carry GitHub's canonical casing too rather than drifting from the truth.
    repo_url = f"https://github.com/{REGISTRY_PACKAGE_REPO_SLUG}"
    return (
        "[build-system]\n"
        # PEP 517 build isolation resolves this fresh at publish time, so `<2` keeps an
        # untested hatchling major from building an irreversible PyPI publish; `>=1.27`
        # floors at the metadata family the shipped 0.10.x wheels were built with.
        'requires = ["hatchling>=1.27,<2"]\n'
        'build-backend = "hatchling.build"\n'
        "\n"
        "[project]\n"
        f'name = "{REGISTRY_PACKAGE_NAME}"\n'
        f'version = "{version}"\n'
        f'description = "{REGISTRY_PACKAGE_DESCRIPTIONS["pypi"]}"\n'
        'readme = "README.md"\n'
        'license = {text = "MIT"}\n'
        f'requires-python = ">={PYTHON_FLOOR}"\n'
        "\n"
        "[project.scripts]\n"
        f'{CLI_NAME} = "tautline:main"\n'
        f'{LEGACY_CLI_NAME} = "tautline:main"\n'
        "\n"
        "[project.urls]\n"
        f'Homepage = "{repo_url}"\n'
        f'Repository = "{repo_url}"\n'
        f'Issues = "{repo_url}/issues"\n'
        "\n"
        "# The embedded tree (700+ non-Python files incl. dotfiles) must survive BOTH\n"
        "# build targets: python -m build builds the wheel from the sdist, so a file\n"
        "# dropped from the sdist silently vanishes from the wheel. force-include\n"
        "# bypasses hatchling's default (ignore-rule-aware) file selection entirely.\n"
        "# Each target also EXCLUDES _dist from default selection: default selection\n"
        "# matches the tree too, and the wheel archive refuses the duplicate paths\n"
        '# ("A second file is being added to the wheel archive at the same path"),\n'
        "# so force-include must be the tree's single owner.\n"
        "[tool.hatch.build.targets.sdist]\n"
        'include = ["src/tautline", "README.md", "LICENSE", "pyproject.toml"]\n'
        'exclude = ["src/tautline/_dist"]\n'
        "\n"
        "[tool.hatch.build.targets.sdist.force-include]\n"
        '"src/tautline/_dist" = "src/tautline/_dist"\n'
        "\n"
        "[tool.hatch.build.targets.wheel]\n"
        'packages = ["src/tautline"]\n'
        'exclude = ["src/tautline/_dist"]\n'
        "\n"
        "[tool.hatch.build.targets.wheel.force-include]\n"
        '"src/tautline/_dist" = "tautline/_dist"\n'
    )


def registry_package_wrapper_init(version: str) -> str:
    """src/tautline/__init__.py for the real PyPI package: the thin runpy wrapper.

    The full committed tree ships as package data under `_dist/`; main() executes the
    embedded single-file CLI in-process. The CLI's own
    `if __name__ == "__main__": raise SystemExit(main())` guard supplies the exit code,
    so the console scripts behave exactly like the checkout CLI with no protocol
    between the two files.
    """
    return (
        '"""Tautline: thin wrapper around the embedded single-file CLI under _dist/."""\n'
        "\n"
        "import os\n"
        "import runpy\n"
        "import sys\n"
        "\n"
        f'__version__ = "{version}"\n'
        "\n"
        "\n"
        "def main() -> int:\n"
        '    """Run the embedded CLI in-process; its __main__ guard raises SystemExit."""\n'
        "    cli = os.path.join(\n"
        f'        os.path.dirname(os.path.abspath(__file__)), "_dist", "bin", "{CLI_NAME}"\n'
        "    )\n"
        "    # Compat-sunset chokepoint 2: the wheel's legacy console script invokes THIS\n"
        "    # wrapper. sys.argv[0] is reset below, so record the legacy invocation name in a\n"
        "    # process-private marker first -- the embedded CLI main() consumes it (warn+strip).\n"
        f'    if os.path.basename(sys.argv[0]) == "{LEGACY_CLI_NAME}":\n'
        f'        os.environ["{LEGACY_LAUNCHER_INVOKED_ENV}"] = "{LEGACY_CLI_NAME}"\n'
        "    sys.argv[0] = cli\n"
        '    runpy.run_path(cli, run_name="__main__")\n'
        "    return 0\n"
    )


def registry_package_files(registry: str, version: str) -> dict[str, str]:
    """The small generated text files of a registry package, by relative path.

    For npm this is the ENTIRE pointer package. For pypi it is the wrapper shell only:
    the embedded `_dist/` tree and its snapshot manifest are materialized by
    registry_package() itself, because they come from `git archive`, not from strings.
    """
    if registry not in REGISTRY_PACKAGE_REGISTRIES:
        raise SystemExit(
            f"registry-package: unknown registry {registry!r}; "
            f"expected one of {', '.join(REGISTRY_PACKAGE_REGISTRIES)}"
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        raise SystemExit(f"registry-package: version must be X.Y.Z, got {version!r}")
    readme = registry_package_readme(registry)
    if registry == "npm":
        return {
            "package.json": registry_package_npm_manifest(version),
            "README.md": readme,
            "LICENSE": registry_package_license(),
        }
    return {
        "pyproject.toml": registry_package_pyproject(version),
        "README.md": readme,
        "LICENSE": registry_package_license(),
        "src/tautline/__init__.py": registry_package_wrapper_init(version),
    }


def registry_package_tree_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Committed-tree paths (HEAD) the pypi payload embeds under `_dist/`.

    Filtered by the public-release export exclusion rule. SCOPE THE SANITIZATION CLAIM
    HONESTLY: the PUBLISHED wheel's sanitization guarantee comes entirely from the
    publish rail building at the sanitized public-mirror tag checkout, where this
    filter is a no-op. On a private dev tree (the CI smoke, local scratch builds) the
    prefix filter is defense-in-depth only -- it is NOT the full public sanitizer, so
    dev-tree wheels are never claimed sanitized and no publish path consumes them.
    """
    code, out, err = run_command(
        ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", "-z", "HEAD"]
    )
    if code != 0:
        raise SystemExit(
            "registry-package: cannot list the committed tree: "
            f"{err or out or 'git ls-tree failed'}"
        )
    names = [name for name in out.split("\0") if name]
    return [name for name in names if public_release_export_path_included(Path(name))]


def registry_package_export_dist(
    dist_dir: Path, tree_files: list[str], repo_root: Path = REPO_ROOT
) -> None:
    """Materialize the embedded `_dist/` tree from `git archive HEAD` (committed content only)."""
    keep = set(tree_files)
    with tempfile.TemporaryDirectory(prefix="registry-package-") as tmp:
        tar_path = Path(tmp) / "tree.tar"
        code, _stdout, stderr = run_command(
            ["git", "-C", str(repo_root), "archive", "--format=tar", "-o", str(tar_path), "HEAD"]
        )
        if code != 0:
            raise SystemExit(f"registry-package: git archive failed: {stderr or 'unknown error'}")
        if dist_dir.is_symlink():
            # The export owns `_dist/` outright (deleted and rebuilt from empty below), so
            # refuse to operate through a link rather than rmtree/extract into a tree the
            # export does not own. Without this guard a live link crashes rmtree with a raw
            # OSError traceback ("[Errno None] None" on macOS) and a dangling link crashes
            # the mkdir below with FileExistsError — is_symlink() is true for both, and the
            # refusal deletes nothing (fail-closed, matching this command's error contract).
            raise SystemExit(
                f"registry-package: {dist_dir} is a symlink; the export owns _dist/ and "
                "refuses to operate through a link -- remove it and rerun"
            )
        if dist_dir.exists():
            # Codex R1 P2: a reused --destination must not overlay stale files into the
            # embedded tree — a file deleted from (or newly excluded by) the committed tree
            # would otherwise survive from an earlier build, and force-include ships the
            # WHOLE directory into the wheel. The export owns `_dist/` and starts empty.
            shutil.rmtree(dist_dir)
        dist_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(tar_path) as archive:
                _reject_unsafe_tar_members(archive)
                members = [m for m in archive.getmembers() if m.isfile() and m.name in keep]
                if sys.version_info >= (3, 12):
                    archive.extractall(dist_dir, members=members, filter="data")
                else:
                    archive.extractall(dist_dir, members=members)  # members validated above
        except tarfile.TarError as exc:
            raise SystemExit(f"registry-package: tree extraction failed: {exc}") from exc
    cli_path = dist_dir / "bin" / CLI_NAME
    if not cli_path.is_file() or not (dist_dir / "VERSION").is_file():
        raise SystemExit(
            f"registry-package: exported tree is missing bin/{CLI_NAME} or VERSION; "
            "refusing to package it"
        )
    cli_path.chmod(0o755)


def registry_package_snapshot_manifest(
    version: str, channel: str, commit: str, commit_epoch: int
) -> str:
    """The wheel's build-time `.snapshot-meta.json` (schema tautline-snapshot/v1).

    Exactly the manifest shape snapshot_manifest() already trusts (extra keys are
    tolerated), plus `installKind: "package"` for package-mode behavior. Deliberately
    NO `canonicalRepo` key and no other absolute path: canonical_methodology_repo()
    treats a manifest canonicalRepo as a resolution candidate, and a baked
    build-machine path must never win canonical resolution (nor survive the public
    boundary scan).

    `materializedAt` is the embedded commit's committer date (commit_epoch), NOT the
    build clock: the manifest is deterministic per commit, so a rebuild of a tag stays
    byte-comparable against the published wheel. (The snapshot STORE's materializedAt
    stays wall-clock on purpose -- there it is a materialization-order sort key.)
    """
    stamp = datetime.fromtimestamp(commit_epoch, tz=timezone.utc)
    manifest = {
        "schema": SNAPSHOT_MANIFEST_SCHEMA,
        "commit": commit,
        "shortCommit": commit[:12],
        "version": version,
        "channel": channel,
        "materializedAt": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installKind": "package",
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def registry_package(args: argparse.Namespace) -> int:
    files = registry_package_files(args.registry, args.version)
    destination = args.destination.resolve()
    tree_files: list[str] = []
    head_commit = ""
    commit_epoch = 0
    if args.registry == "pypi":
        # The real payload reads the tree AS a git repository (archive + commit stamp),
        # so refuse anywhere git cannot answer -- same posture as require_dev_checkout.
        require_dev_checkout("registry-package")
        # running_methodology_commit() is the ONE sanctioned commit reader (the structural
        # guard in tests/test_canonical_repo_resolution.py pins that class-wide, allowlist
        # deliberately empty). require_dev_checkout has just refused snapshot manifests and
        # non-git exec roots, so here the reader IS `rev-parse HEAD` of the checkout we
        # archive -- and its "unavailable" sentinel still fail-closes on the check below.
        head_commit = running_methodology_commit()
        if not re.fullmatch(r"[0-9a-f]{40}", head_commit):
            raise SystemExit(
                "registry-package: cannot resolve HEAD in this checkout; "
                "the pypi payload embeds the committed tree and needs a commit to stamp"
            )
        code, tree_version, err = run_command(
            ["git", "-C", str(REPO_ROOT), "show", "HEAD:VERSION"]
        )
        if code != 0:
            raise SystemExit(
                "registry-package: cannot read VERSION from the committed tree: "
                f"{err or 'git show failed'}"
            )
        tree_version = tree_version.strip()
        if tree_version != args.version:
            # Same fail-closed shape as the publish workflow's tag-vs-VERSION verify:
            # the embedded tree must carry exactly the version it is published as.
            raise SystemExit(
                f"registry-package: --version {args.version} disagrees with the archived "
                f"tree's VERSION {tree_version}; commit the version you intend to package"
            )
        # The manifest stamp is the COMMIT's date, not the build clock: rebuilding the
        # same tag must yield a byte-identical manifest so a tag-vs-registry rebuild
        # stays comparable. %ct (committer epoch) keeps the UTC rendering stable
        # regardless of the committer's timezone. Fail closed like the VERSION read
        # above -- a payload without a provenance stamp must not be materialized.
        code, commit_date, err = run_command(
            ["git", "-C", str(REPO_ROOT), "show", "-s", "--format=%ct", head_commit]
        )
        if code != 0 or not commit_date.isdigit():
            raise SystemExit(
                "registry-package: cannot read the commit date from the committed tree: "
                f"{err or commit_date or 'git show failed'}"
            )
        commit_epoch = int(commit_date)
        tree_files = registry_package_tree_files()
    total = len(files) + (len(tree_files) + 1 if args.registry == "pypi" else 0)
    print(f"registry_package_registry: {args.registry}")
    print(f"registry_package_name: {REGISTRY_PACKAGE_NAME}")
    print(f"registry_package_version: {args.version}")
    if args.registry == "pypi":
        print(f"registry_package_channel: {args.channel}")
        print(f"registry_package_commit: {head_commit}")
    print(f"registry_package_destination: {destination}")
    print(f"registry_package_files: {total}")
    if not args.write:
        print("registry_package_written: no")
        print("registry_package_next: rerun with --write to materialize the package tree")
        return 0
    for rel, content in files.items():
        path = destination / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if args.registry == "pypi":
        dist_dir = destination / Path(REGISTRY_PACKAGE_DIST_DIR)
        registry_package_export_dist(dist_dir, tree_files)
        (dist_dir / SNAPSHOT_MANIFEST_NAME).write_text(
            registry_package_snapshot_manifest(
                args.version, args.channel, head_commit, commit_epoch
            ),
            encoding="utf-8",
        )
    print(f"registry_package_written: {destination}")
    return 0


RELEASE_TAIL_PUBLISH_WORKFLOWS = {"npm": "publish-npm.yml", "pypi": "publish-pypi.yml"}
RELEASE_REGISTRY_URLS = {
    "npm": f"https://registry.npmjs.org/{REGISTRY_PACKAGE_NAME}",
    "pypi": f"https://pypi.org/pypi/{REGISTRY_PACKAGE_NAME}/json",
}


release_http_json = _release_mod.release_http_json


def registry_latest_version(registry: str) -> str:
    payload = release_http_json(RELEASE_REGISTRY_URLS[registry])
    if payload is None:
        return "absent"
    if registry == "npm":
        return str((payload.get("dist-tags") or {}).get("latest") or "absent")
    return str((payload.get("info") or {}).get("version") or "absent")


def registry_has_version(registry: str, version: str) -> bool:
    payload = release_http_json(RELEASE_REGISTRY_URLS[registry])
    if payload is None:
        return False
    key = "versions" if registry == "npm" else "releases"
    return version in (payload.get(key) or {})


def release_drift_surfaces() -> tuple[dict[str, str], list[str]]:
    surfaces = {"repo": plugin_version()}
    unreadable: list[str] = []
    for registry in ("npm", "pypi"):
        try:
            surfaces[registry] = registry_latest_version(registry)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            # Fail closed: report it as a surface that does not agree, never as agreement.
            surfaces[registry] = "unreadable"
            unreadable.append(f"{registry}: {exc}")
    return surfaces, unreadable


def release_drift_check(args: argparse.Namespace) -> int:
    """Report every release surface and its version, then the verdict.

    The failure this exists to catch: for months the repo said 0.9.1 while npm and
    PyPI both sat at 0.8.2, and nothing looked.
    """
    surfaces, unreadable = release_drift_surfaces()
    repo = surfaces["repo"]
    drifted = sorted(name for name in ("npm", "pypi") if surfaces[name] != repo)
    ok = not drifted
    if getattr(args, "as_json", False):
        print(
            json.dumps(
                {
                    "ok": ok,
                    "surfaces": surfaces,
                    "drifted": drifted,
                    "unreadable": unreadable,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if ok else 1
    for name in ("repo", "npm", "pypi"):
        print(f"release_drift_{name}: {surfaces[name]}")
    for detail in unreadable:
        print(f"release_drift_unreadable: {detail}")
    if ok:
        print("release_drift_verdict: aligned")
        return 0
    disagreement = ", ".join(f"{name}={surfaces[name]}" for name in drifted)
    print(f"release_drift_verdict: drift (repo={repo}; {disagreement})")
    print(
        "release_drift_next: run `tautline release-tail` to publish the current "
        "version to every stale surface"
    )
    return 1


release_tail_leaks = _release_mod.release_tail_leaks


def release_tail_notes(version: str) -> str:
    block = changelog_release_block(version)
    if block is None:
        return ""
    body = str(block.get("body", "")).strip()
    changelog = f"https://github.com/{PUBLIC_MIRROR_REPO}/blob/main/CHANGELOG.md"
    return f"{body}\n\nFull changelog: {changelog}\n"


def release_tail_preflight(version: str) -> list[str]:
    errors: list[str] = []
    blocks = changelog_release_blocks()
    newest = str(blocks[0].get("version", "")) if blocks else ""
    if newest != version:
        errors.append(
            f"VERSION is {version} but the newest CHANGELOG section is "
            f"{newest or 'missing'}; the release notes would describe the wrong release"
        )
    if changelog_release_block(version) is None:
        errors.append(f"CHANGELOG has no section for {version}")
    else:
        leaks = release_tail_leaks(release_tail_notes(version))
        if leaks:
            errors.append(
                "release notes contain terms that must never be published: "
                + ", ".join(leaks)
            )
    return errors


def release_tail_gh(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """The ONLY way the tail talks to gh. --repo is pinned here, not at call sites."""
    if "--repo" in args:
        raise ReleaseTailError("release_tail_gh() pins --repo; call sites must not pass it")
    return run_command(["gh", *args, "--repo", PUBLIC_MIRROR_REPO], timeout=timeout)


def release_tail_git(clone: Path, args: list[str], timeout: int = 600) -> tuple[int, str, str]:
    return run_command(["git", "-C", str(clone), *args], timeout=timeout)


release_tail_overlay = _release_mod.release_tail_overlay


def release_tail_mirror_push(version: str, export_dir: Path, clone: Path) -> tuple[str, bool]:
    """Commit the export tree onto the mirror's current HEAD and fast-forward push.

    Returns (sha, changed). `changed` is False when the mirror already carries this
    exact tree -- a resumed run must not add an empty duplicate commit.
    """
    code, out, err = run_command(
        ["git", "clone", "--quiet", PUBLIC_MIRROR_REMOTE, str(clone)], timeout=900
    )
    if code != 0:
        raise ReleaseTailError(f"cannot clone the public mirror: {err or out}")
    code, previous_head, err = release_tail_git(clone, ["rev-parse", "HEAD"])
    if code != 0:
        raise ReleaseTailError(f"cannot read the mirror's HEAD: {err}")
    print(f"release_tail_mirror_previous_head: {previous_head}")

    release_tail_overlay(export_dir, clone)
    release_tail_git(clone, ["config", "user.email", "release-tail@tautline.invalid"])
    release_tail_git(clone, ["config", "user.name", "Tautline Release Tail"])
    code, out, err = release_tail_git(clone, ["add", "-A"])
    if code != 0:
        raise ReleaseTailError(f"cannot stage the export tree: {err or out}")
    code, status, err = release_tail_git(clone, ["status", "--porcelain"])
    if code != 0:
        raise ReleaseTailError(f"cannot inspect the mirror clone: {err}")
    if not status.strip():
        print("release_tail_mirror: current")
        return previous_head, False

    code, out, err = release_tail_git(
        clone,
        [
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--no-verify",
            "-q",
            "-m",
            f"Tautline {version}",
        ],
    )
    if code != 0:
        raise ReleaseTailError(f"cannot commit onto the mirror: {err or out}")
    code, sha, err = release_tail_git(clone, ["rev-parse", "HEAD"])
    if code != 0:
        raise ReleaseTailError(f"cannot read the new mirror commit: {err}")
    # Fast-forward only. No --force, no --force-with-lease, no `+` refspec: the
    # mirror's history and everyone's clones survive a release.
    code, out, err = release_tail_git(
        clone, ["push", "origin", f"HEAD:refs/heads/{PUBLIC_MIRROR_BRANCH}"]
    )
    if code != 0:
        raise ReleaseTailError(f"cannot fast-forward the mirror: {err or out}")
    print("release_tail_mirror: pushed")
    return sha, True


release_tail_tag_commit = _release_mod.release_tail_tag_commit


def release_tail_ensure_tag(version: str, sha: str, clone: Path) -> str:
    tag = f"v{version}"
    code, out, err = release_tail_git(
        clone,
        ["ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
    )
    if code != 0:
        raise ReleaseTailError(f"cannot list the mirror's tags: {err or out}")
    # Compare COMMIT to COMMIT. The guard itself is untouched: a tag that genuinely
    # points at a different commit still refuses.
    existing = release_tail_tag_commit(out, tag)
    if existing:
        if existing != sha:
            raise ReleaseTailError(
                f"tag {tag} already exists on the mirror at {existing}, not {sha}; "
                "refusing to move a published tag"
            )
        print(f"release_tail_tag: current {tag}")
        return "current"
    code, out, err = release_tail_git(clone, ["tag", "-a", tag, "-m", f"Tautline {version}", sha])
    if code != 0:
        raise ReleaseTailError(f"cannot create tag {tag}: {err or out}")
    code, out, err = release_tail_git(clone, ["push", "origin", f"refs/tags/{tag}"])
    if code != 0:
        raise ReleaseTailError(f"cannot push tag {tag}: {err or out}")
    print(f"release_tail_tag: created {tag}")
    return "created"


def release_tail_release_state(tag: str) -> dict | None:
    code, out, _err = release_tail_gh(
        ["release", "view", tag, "--json", "isDraft,tagName,targetCommitish,url"]
    )
    if code != 0:
        return None
    try:
        state = json.loads(out or "null")
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def release_tail_ensure_release(
    version: str, tag: str, sha: str, notes_path: Path, skip_registry: bool
) -> str:
    """Create/publish the Release. Returns 'drafted' | 'published' | 'existing'.

    A DRAFT emits no `published` event, so no publish workflow fires. That is what
    makes the one-time bootstrap safe: --skip-registry leaves a real Release for the
    version, the operator configures Trusted Publishing against the workflows that
    now exist on the mirror, and a later run PUBLISHES THAT SAME DRAFT -- firing the
    event exactly once. Creating a second Release instead would double-publish.
    """
    state = release_tail_release_state(tag)
    if state is None:
        command = [
            "release",
            "create",
            tag,
            "--target",
            sha,
            "--title",
            f"Tautline {version}",
            "--notes-file",
            str(notes_path),
        ]
        if skip_registry:
            command.append("--draft")
        code, out, err = release_tail_gh(command)
        if code != 0:
            raise ReleaseTailError(f"cannot create the Release: {err or out}")
        if skip_registry:
            print("release_tail_release: drafted")
            return "drafted"
        print("release_tail_release: published")
        return "published"
    if state.get("isDraft"):
        if skip_registry:
            print("release_tail_release: drafted")
            return "drafted"
        code, out, err = release_tail_gh(["release", "edit", tag, "--draft=false"])
        if code != 0:
            raise ReleaseTailError(f"cannot publish the draft Release: {err or out}")
        print("release_tail_release: published")
        return "published"
    print("release_tail_release: existing")
    return "existing"


def release_tail_matching_run(workflow: str, sha: str) -> dict | None:
    """The run of `workflow` for THIS release, matched on the exact head SHA.

    A stale successful run of the same workflow (a previous release) must never be
    read as this release's success, so the match is on the SHA being released and
    nothing weaker. No matching run yet means STILL WAITING -- never success.
    """
    code, out, err = release_tail_gh(
        ["run", "list", "--workflow", workflow, "--json", RELEASE_TAIL_RUN_FIELDS, "--limit", "30"]
    )
    if code != 0:
        raise ReleaseTailError(f"cannot list runs for {workflow}: {err or out}")
    try:
        runs = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        raise ReleaseTailError(f"invalid run JSON for {workflow}: {exc}") from exc
    for run in runs if isinstance(runs, list) else []:
        if run.get("headSha") == sha:
            return run
    return None


def release_tail_wait_for_runs(
    workflows: list[str], sha: str, timeout: int, poll_interval: int
) -> None:
    deadline = time.monotonic() + timeout
    pending = set(workflows)
    failed: list[str] = []
    while pending:
        for workflow in sorted(pending):
            run = release_tail_matching_run(workflow, sha)
            if run is None or run.get("status") != "completed":
                continue  # no run at this SHA yet, or still running: not success
            pending.discard(workflow)
            conclusion = str(run.get("conclusion") or "unknown")
            print(f"release_tail_run: {workflow} conclusion={conclusion} url={run.get('url')}")
            if conclusion != "success":
                failed.append(workflow)
        if not pending:
            break
        if time.monotonic() >= deadline:
            raise ReleaseTailError(
                f"timed out after {timeout}s waiting for publish runs at {sha}: "
                + ", ".join(sorted(pending))
            )
        time.sleep(poll_interval)
    if failed:
        raise ReleaseTailError("publish workflow failed: " + ", ".join(sorted(failed)))


def release_tail_publish_registries(
    version: str, tag: str, sha: str, fired: bool, timeout: int, poll_interval: int
) -> None:
    """Ensure both registries hold `version`, then wait for the runs that do it.

    When the Release was just published the event already fired both workflows. On a
    resumed run the Release is already published, so no event fires -- the missing
    registry's workflow is dispatched explicitly, pinned to the version and the tag.
    Either way the wait matches runs by the exact SHA.
    """
    awaited: list[str] = []
    for registry, workflow in sorted(RELEASE_TAIL_PUBLISH_WORKFLOWS.items()):
        try:
            published = registry_has_version(registry, version)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise ReleaseTailError(f"cannot read {registry} before publishing: {exc}") from exc
        if published:
            print(f"release_tail_{registry}: {version} (already published)")
            continue
        if not fired:
            code, out, err = release_tail_gh(
                ["workflow", "run", workflow, "--ref", tag, "-f", f"version={version}"]
            )
            if code != 0:
                raise ReleaseTailError(f"cannot dispatch {workflow}: {err or out}")
            print(f"release_tail_{registry}_dispatch: {workflow} version={version} ref={tag}")
        awaited.append(workflow)
    if awaited:
        print(f"release_tail_waiting: {', '.join(awaited)} at {sha}")
        release_tail_wait_for_runs(awaited, sha, timeout, poll_interval)


def release_tail_print_plan(version: str, tag: str) -> None:
    print(f"release_tail_plan_export: public-release-export of {REPO_ROOT} (gate must be ok)")
    print(
        f"release_tail_plan_mirror: clone {PUBLIC_MIRROR_REPO}, overlay the export onto its "
        f"current HEAD, commit, fast-forward push to {PUBLIC_MIRROR_BRANCH} (never --force)"
    )
    print(f"release_tail_plan_tag: create and push {tag} at the pushed commit")
    print(
        f"release_tail_plan_release: gh release create {tag} --repo {PUBLIC_MIRROR_REPO} "
        "--target <pushed sha> (--draft with --skip-registry)"
    )
    print(
        "release_tail_plan_publish: the published Release fires "
        f"{', '.join(sorted(RELEASE_TAIL_PUBLISH_WORKFLOWS.values()))} on {PUBLIC_MIRROR_REPO}; "
        "wait for the runs at that exact SHA"
    )
    print("release_tail_plan_drift: release-drift-check must report repo == npm == pypi")


def release_tail_run(args: argparse.Namespace) -> int:
    version = plugin_version()
    tag = f"v{version}"
    print(f"release_tail_mode: {'dry-run' if args.dry_run else 'write'}")
    print(f"release_tail_version: {version}")
    print(f"release_tail_repo: {PUBLIC_MIRROR_REPO}")

    errors = release_tail_preflight(version)
    if errors:
        raise ReleaseTailError("; ".join(errors))
    print("release_tail_preflight: ok")

    if args.dry_run:
        release_tail_print_plan(version, tag)
        print("release_tail_written: no")
        print("release_tail_next: rerun without --dry-run to execute the tail")
        return 0

    private_terms = public_release_private_terms(
        public_release_private_adapters(REPO_ROOT), args.private_terms_file
    )
    if not private_terms and not args.allow_empty_private_terms:
        raise ReleaseTailError(
            "no private product/client terms configured; set "
            f"{PUBLIC_RELEASE_PRIVATE_TERMS_ENV}, pass --private-terms-file, or pass "
            "--allow-empty-private-terms only for repos with no private terms"
        )

    with tempfile.TemporaryDirectory(prefix="tautline-release-tail-") as scratch:
        root = Path(scratch)
        export_dir = root / "export"
        clone_dir = root / "mirror"

        result = public_release_export_repository(
            REPO_ROOT,
            export_dir,
            force=True,
            private_terms_file=args.private_terms_file,
        )
        issues = result.get("issues") or []
        if issues:
            details = "; ".join(f"{i.get('code')} {i.get('path')}" for i in issues[:5])
            raise ReleaseTailError(
                f"the public-release export gate is not ok ({len(issues)} issue(s)): {details}"
            )
        print(f"release_tail_export_files: {result.get('files')}")
        print("release_tail_export_check: ok")

        sha, _changed = release_tail_mirror_push(version, export_dir, clone_dir)
        print(f"release_tail_mirror_sha: {sha}")
        release_tail_ensure_tag(version, sha, clone_dir)

        notes_path = root / "release-notes.md"
        notes_path.write_text(release_tail_notes(version), encoding="utf-8")
        state = release_tail_ensure_release(version, tag, sha, notes_path, args.skip_registry)

        if args.skip_registry:
            print("release_tail_registries: skipped")
            print(
                "release_tail_next: configure Trusted Publishing on npm and PyPI against "
                f"{PUBLIC_MIRROR_REPO} + "
                f"{', '.join(sorted(RELEASE_TAIL_PUBLISH_WORKFLOWS.values()))}, then rerun "
                "`tautline release-tail` to publish the draft Release"
            )
            return 0

        # 'published' means the event just fired both workflows. 'existing' means the
        # Release was already published, so nothing fired and the missing registry's
        # workflow must be dispatched explicitly.
        release_tail_publish_registries(
            version, tag, sha, state == "published", args.timeout, args.poll_interval
        )

    drift = release_drift_check(argparse.Namespace(as_json=False))
    if drift != 0:
        raise ReleaseTailError(
            f"the publish workflows finished but the registries do not hold {version}; "
            "see release_drift_verdict above"
        )
    print("release_tail_written: yes")
    return 0


def release_tail(args: argparse.Namespace) -> int:
    try:
        return release_tail_run(args)
    except ReleaseTailError as exc:
        print(f"release_tail_error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:  # deeper CLI helpers fail closed with SystemExit
        print(f"release_tail_error: {exc}", file=sys.stderr)
        return 2


def ensure_git_excludes(target: Path, patterns: list[str], label: str = "Minervit lane-local state") -> None:
    patterns = [pattern for pattern in dict.fromkeys(patterns) if pattern]
    git_dir = run_git(target, ["rev-parse", "--git-dir"])
    if not git_dir or git_dir == "unavailable":
        return
    git_path = Path(git_dir)
    if not git_path.is_absolute():
        git_path = target / git_path
    exclude = git_path / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    missing = [pattern for pattern in patterns if pattern not in lines]
    if missing:
        with exclude.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"\n# {label}\n")
            for pattern in missing:
                f.write(f"{pattern}\n")


def ensure_root_gitignore_patterns(target: Path, patterns: list[str], label: str = "Minervit generated output") -> list[str]:
    patterns = [pattern for pattern in dict.fromkeys(patterns) if pattern]
    if not patterns:
        return []
    git_dir = run_git(target, ["rev-parse", "--show-toplevel"])
    if not git_dir or git_dir == "unavailable":
        return []
    root = Path(git_dir)
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    missing = [pattern for pattern in patterns if pattern not in lines]
    if not missing:
        return []
    with gitignore.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        if existing.strip():
            f.write("\n")
        f.write(f"# {label}\n")
        for pattern in missing:
            f.write(f"{pattern}\n")
    return [str(gitignore)]


def first_dir_pattern(path_text: str) -> str:
    return util_module().first_dir_pattern(path_text)


def slugify(text: str, fallback: str = "lane") -> str:
    return util_module().slugify(text, fallback)


lane_env_path = _lane_mod.lane_env_path


def lane_ignore_patterns(data: dict) -> list[str]:
    patterns: list[str] = []
    continuity = data["continuity"]
    lane_state = data["laneState"]
    session_journal = data["sessionJournal"]
    if continuity.get("gitIgnore", False):
        patterns.append(first_dir_pattern(continuity["path"]))
    if lane_state.get("gitIgnore", False):
        patterns.append(first_dir_pattern(lane_state["runsDir"]))
        patterns.append(first_dir_pattern(lane_state["executionPacket"]))
        patterns.append(first_dir_pattern(lane_state["milestoneRun"]))
        patterns.append(first_dir_pattern(lane_state["goalRun"]))
        patterns.append(lane_state["lockPath"])
        patterns.append(data["workProfiles"]["profileLockPath"])
    if session_journal.get("gitIgnoreLocal", True):
        patterns.append(first_dir_pattern(lane_state["runsDir"]))
    graphify = data.get("graphify", DEFAULT_GRAPHIFY)
    if graphify.get("enabled", True) and graphify.get("gitIgnoreOutput", True):
        patterns.append(f"{str(graphify.get('outputDir', DEFAULT_GRAPHIFY['outputDir'])).strip().rstrip('/')}/")
    return [pattern for pattern in dict.fromkeys(patterns) if pattern]


def graphify_ignore_pattern(data: dict) -> str:
    output_dir = str(data.get("graphify", DEFAULT_GRAPHIFY).get("outputDir", DEFAULT_GRAPHIFY["outputDir"])).strip().rstrip("/")
    return f"{output_dir}/"


def ensure_graphify_ignored(data: dict, target: Path) -> list[str]:
    graphify = data.get("graphify", DEFAULT_GRAPHIFY)
    if not graphify.get("enabled", True) or not graphify.get("gitIgnoreOutput", True):
        return []
    pattern = graphify_ignore_pattern(data)
    ensure_git_excludes(target, [pattern], label="Minervit generated Graphify output")
    return ensure_root_gitignore_patterns(target, [pattern], label="Minervit generated Graphify output")


def ensure_lane_state(data: dict, target: Path) -> None:
    lane_state = data["laneState"]
    continuity = data["continuity"]
    (target / lane_state["runsDir"]).mkdir(parents=True, exist_ok=True)
    if data["sessionJournal"].get("enabled", True):
        (target / lane_state["runsDir"] / "session-journals").mkdir(parents=True, exist_ok=True)
    (target / Path(lane_state["executionPacket"]).parent).mkdir(parents=True, exist_ok=True)
    (target / Path(lane_state["milestoneRun"]).parent).mkdir(parents=True, exist_ok=True)
    (target / Path(lane_state["goalRun"]).parent).mkdir(parents=True, exist_ok=True)
    (target / Path(continuity["path"]).parent).mkdir(parents=True, exist_ok=True)
    if continuity.get("gitIgnore", False) or lane_state.get("gitIgnore", False):
        ensure_git_excludes(target, lane_ignore_patterns(data))
    ensure_graphify_ignored(data, target)


def path_matches_work_profile_pattern(rel_path: str, pattern: str) -> bool:
    return profiles_module().path_matches_work_profile_pattern(rel_path, pattern)


# --- PM-surface classifier: loader-side broad-glob rejection + the pure fail-closed helper -------


def validate_pm_surface(pattern: str, source_of_truth_roots: list[str]) -> str:
    """Fail-closed loader validation of one declared PM surface (Design 1). SystemExit on any
    violation. Returns the normalized surface on success."""
    prefix = pm_surface_fixed_prefix(pattern).strip("/")
    has_wildcard = any(char in _PM_SURFACE_METACHARACTERS for char in pattern)
    # Rule A: a pattern that begins with a wildcard has no bounded fixed root.
    if not prefix:
        raise SystemExit(
            f"Project adapter productDevelopment.surfaces entry {pattern!r} has no fixed path root "
            "before its first wildcard; PM surfaces must be bounded (e.g. docs/product/**)"
        )
    # Rule A2: the fixed root must be under a subdirectory (no top-level file/glob surface).
    if "/" not in prefix:
        raise SystemExit(
            f"Project adapter productDevelopment.surfaces entry {pattern!r} is a "
            f"repo-root surface; "
            "PM surfaces must be scoped under a product subdirectory (e.g. docs/product/**)"
        )
    # Rule A4: the wildcard must begin on a path-segment boundary (reject docs/product*/**).
    if has_wildcard and not pm_surface_fixed_prefix(pattern).endswith("/"):
        raise SystemExit(
            f"Project adapter productDevelopment.surfaces entry {pattern!r} has a wildcard "
            f"mid-segment; "
            "the wildcard must start immediately after a '/' so it cannot span sibling directories"
        )
    # Rule A3 (PRIMARY, fail-closed-by-construction): the fixed root must be under a safe
    # product root.
    if not any(pm_roots_overlap(prefix, root) and (prefix == root or prefix.startswith(root + "/"))
               for root in PM_SURFACE_PRODUCT_ROOTS):
        raise SystemExit(
            f"Project adapter productDevelopment.surfaces entry {pattern!r} is not under a "
            f"safe product "
            f"root {list(PM_SURFACE_PRODUCT_ROOTS)}; framework docs, code, config, and root "
            f"files can "
            "never be declared PM surfaces"
        )
    # Rule B (defense-in-depth): reject if the fixed prefix overlaps any hard-excluded root
    # (symmetric), or the pattern matches any hard-exclusion sentinel.
    for root in HARD_EXCLUDED_ROOTS:
        if pm_roots_overlap(prefix, root):
            raise SystemExit(
                f"Project adapter productDevelopment.surfaces entry {pattern!r} overlaps the "
                f"hard-excluded root {root!r} and cannot be a PM surface"
            )
    for sentinel in HARD_EXCLUSION_SENTINELS:
        if path_matches_work_profile_pattern(sentinel, pattern):
            raise SystemExit(
                f"Project adapter productDevelopment.surfaces entry {pattern!r} would match the "
                f"hard-excluded path {sentinel!r} and cannot be a PM surface"
            )
    # Bounded source-of-truth guard (Design 3): reject a surface whose fixed prefix overlaps a
    # STRUCTURED, path-typed plan source-of-truth root (symmetric; no existence gate).
    for source_root in source_of_truth_roots:
        if pm_roots_overlap(prefix, source_root):
            raise SystemExit(
                f"Project adapter productDevelopment.surfaces entry {pattern!r} overlaps "
                f"the declared "
                f"plan source-of-truth root {source_root!r}; a PM surface may not "
                f"contain a plan root"
            )
    return pattern


def normalize_product_development(data: dict) -> None:
    """Merge DEFAULT_PRODUCT_DEVELOPMENT, validate + reject broad-glob surfaces, normalize the
    `surfaces` tuple to a list. Mutates data['productDevelopment']."""
    raw = data.get("productDevelopment")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("Project adapter productDevelopment must be an object")
    merged = {**DEFAULT_PRODUCT_DEVELOPMENT, **raw}
    surfaces_raw = merged.get("surfaces", ())
    if isinstance(surfaces_raw, (str, bytes)) or not isinstance(surfaces_raw, (list, tuple)):
        raise SystemExit(
            "Project adapter productDevelopment.surfaces must be an array of non-blank glob strings"
        )
    source_of_truth_roots: list[str] = []
    for section in ("planningArtifacts", "goalArtifacts"):
        value = (
            data.get(section, {}).get("sourceOfTruth")
            if isinstance(data.get(section), dict)
            else None
        )
        if _looks_like_repo_relative_path(value):
            source_of_truth_roots.append(str(value).strip().strip("/"))
    normalized: list[str] = []
    for surface in surfaces_raw:
        pattern = str(surface).strip()
        if not pattern:
            raise SystemExit(
                "Project adapter productDevelopment.surfaces must contain non-blank glob strings"
            )
        normalized.append(validate_pm_surface(pattern, source_of_truth_roots))
    # Preserve any other declared keys (only the surfaces value is normalized) so a typo or
    # unsupported key under productDevelopment (e.g. `surface` for `surfaces`) still reaches the
    # later additionalProperties:false schema validation and is REJECTED, rather than being
    # silently dropped here -- which would accept an invalid adapter that validate-adapter rejects
    # and quietly disable the intended PM-surface config (Codex R1 P2).
    data["productDevelopment"] = {**raw, "surfaces": normalized}


def lean_lane_data(cfg: dict) -> dict:
    """The lane-verb view of a lean adapter: `legacy_lane_view` plus the SAME machine-local
    observability defaults every 1.x lane gets from `load_project`, so a lane keeps writing (and
    the readers keep finding) the same events ledger across a 1.x -> lean migration.

    Validated with the authoritative lean validator FIRST: `load_lean_config` only sniffs
    `schemaVersion`, so a malformed marker (say `"project": "just-a-string"`) would otherwise
    reach `legacy_lane_view` and die as a raw AttributeError -- which `_ledger_targets_data`
    does not catch, so one broken target would abort a whole multi-repo aggregation instead of
    becoming its one error line."""
    errors = lean.lean_config_errors(cfg)
    if errors:
        raise SystemExit("lean adapter invalid: " + "; ".join(errors))
    data = lean.legacy_lane_view(cfg)
    data["observabilityEvents"] = dict(DEFAULT_OBSERVABILITY_EVENTS)
    return data


def lane_project(args: argparse.Namespace, *, lean_ok: bool = False) -> tuple[dict, Path, Path]:
    target = args.target.resolve()
    if getattr(args, "project", None):
        project_path = Path(args.project).resolve()
        require_source_adapter_for_target(project_path, target, "lane command")
    else:
        generated_path = adapter_marker_path(target)
        if not generated_path.exists():
            raise SystemExit(no_adapter_message_for(target))
        lean_cfg = lean.load_lean_config(generated_path)  # --- LEAN PROFILE WIRING ---
        if lean_cfg is not None:
            # A lean-1 adapter has no source adapter and no `_generated` provenance chain, so
            # every 1.x check below is unanswerable for it -- without this branch, verbs on the
            # lean KEEP list (decision-record first, then the ledger readers) refuse every lean
            # lane with a key-soup error about a schema the lane deliberately left behind.
            # Identity is still verified when it CAN be: a lean adapter naming another repo is
            # refused, while a missing remote (a fresh `tautline init` lane) must not block the
            # ledger -- refusing to record a decision there would gut the autonomy directive
            # exactly where it starts.
            if not lean_ok:
                raise SystemExit(
                    f"{target} is a lean-1 lane; this verb still requires the 1.x adapter profile."
                )
            data = lean_lane_data(lean_cfg)
            if target_is_git_worktree(target) and normalize_repo_slug(infer_repo_slug(target)):
                validate_adapter_repo_matches_target(data, target)
            return data, generated_path, target
        generated = load_project(generated_path)
        generated_meta = generated.get("_generated")
        if not isinstance(generated_meta, dict) or not generated_meta.get("sourceAdapter"):
            raise SystemExit(
                "Lane adapter is not generated from a methodology source adapter. Bootstrap or render from "
                "<methodology_repo>/adapters/projects/<project>.json instead of hand-writing .minervit-ai-delivery.json."
            )
        source_adapter_value = str(generated_meta["sourceAdapter"]).replace("\\", "/")
        source_path = source_adapter_path(source_adapter_value)
        if not Path(source_adapter_value).is_absolute():
            target_candidate = target / source_adapter_value
            if target_candidate.exists():
                source_path = target_candidate
            elif source_adapter_value in (REPO_LOCAL_ADAPTER_FILE, LEGACY_REPO_LOCAL_ADAPTER_FILE) and not source_path.exists():
                # The marker may record the other marker-era name (.tautline/ vs .minervit/);
                # resolve to whichever repo-local adapter actually exists in the target.
                fallback = repo_local_source_adapter_path(target)
                if fallback.exists():
                    source_path = fallback
        if not source_path.exists():
            raise SystemExit(
                f"Generated lane adapter sourceAdapter is missing: {source_path}. The per-product source adapter is "
                "not present in the methodology checkout (it may have been removed/relocated). To recover: restore it "
                f"under <methodology_repo>/adapters/projects/<project>.json, place it at {REPO_LOCAL_ADAPTER_FILE} "
                "inside the target repo, OR place it in a private adapters directory and set "
                "MINERVIT_METHODOLOGY_ADAPTER_ROOT to that directory; then re-render this lane "
                "(`tautline render-adapters --project <adapter> --target . --write`). Do not hand-edit "
                ".minervit-ai-delivery.json."
            )
        if not source_adapter_allowed_for_target(source_path, target):
            raise SystemExit(
                "Generated lane adapter sourceAdapter does not point at a trusted source adapter. Re-render this lane "
                f"from <methodology_repo>/adapters/projects/*.json, MINERVIT_METHODOLOGY_ADAPTER_ROOT, or "
                f"{REPO_LOCAL_ADAPTER_FILE} inside the target repo."
            )
        expected_source_sha = generated_meta.get("sourceAdapterSha256")
        if not isinstance(expected_source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha):
            raise SystemExit(
                "Generated lane adapter is missing _generated.sourceAdapterSha256. Re-render this lane from the "
                "canonical source adapter before startup."
            )
        actual_source_sha = file_sha256(source_path)
        if expected_source_sha != actual_source_sha:
            rescue_findings = methodology_rescue_ref_adapter_changes()
            rescue_hint = ""
            if rescue_findings:
                refs = "; ".join(f"{ref} ({', '.join(paths)})" for ref, paths in rescue_findings)
                rescue_hint = (
                    " A canonical adapter change is sitting on a local rescue ref and is not on the base branch: "
                    f"{refs}. Re-land those commits (cherry-pick/PR) before re-rendering, or the re-render will "
                    "reproduce the pre-rescue adapter."
                )
            raise SystemExit(
                "Generated lane adapter sourceAdapterSha256 does not match the methodology source adapter. "
                "Diagnose before re-rendering: (1) diff the canonical source adapter against the lane's last "
                "committed adapter; (2) check whether a canonical adapter fix was moved to a "
                "`tautline-local-rescue/*` ref by auto-sync; (3) only then re-render this lane from the "
                f"canonical source adapter.{rescue_hint}"
            )
        project_path = source_path
    if not project_path.exists():
        raise SystemExit(no_adapter_message_for(target))
    data = load_project(project_path)
    validate_adapter_repo_matches_target(data, target, require_target_identity=not getattr(args, "project", None))
    return data, project_path, target


def adapter_drift(data: dict, project_path: Path, target: Path) -> list[str]:
    project_arg, source_path_override = expected_files_render_context(data, project_path, target)
    expected = expected_files(data, project_arg, source_path_override, target)
    drift: list[str] = []
    for rel, content in expected.items():
        # Compat-sunset (roadmap #16, PR2): drift entries that name the lane marker must name the
        # RESOLVED on-disk file. A repo managed only via the legacy .minervit-ai-delivery.json
        # marker has no canonical .tautline.json, so both the content read and the drift label
        # follow the resolved marker (canonical if present, else legacy) -- never the constant the
        # operator does not have on disk. Resolution is by direct existence (find_adapter_root
        # already emitted the markers sunset warning upstream), so this stays side-effect-free.
        if rel == LANE_ADAPTER_FILE:
            canonical_marker = target / LANE_ADAPTER_FILE
            legacy_marker = target / LEGACY_LANE_ADAPTER_FILE
            if not canonical_marker.exists() and legacy_marker.exists():
                dest, label = legacy_marker, LEGACY_LANE_ADAPTER_FILE
            else:
                dest, label = canonical_marker, rel
        else:
            dest, label = target / rel, rel
        try:
            current = dest.read_text(encoding="utf-8") if dest.exists() else None
        except OSError as exc:
            drift.append(f"{label} (unreadable: {exc})")
            continue
        if rel in GENERATED_MARKDOWN_FILES and current is not None and not is_methodology_generated_markdown(dest):
            continue
        if rel in GENERATED_MARKDOWN_FILES and current is not None:
            # Template-stamp equivalence (item 69), mirroring the LANE_ADAPTER_FILE branch below.
            # WITHOUT this, shipping the stamp turns every lane whose runtime VERSION differs from
            # the on-disk stamp into `adapter_drift` -- an INTEGRITY gate, so
            # `methodology-status --fail-on-drift` hard-fails and startup remediation arms
            # fleet-wide on the next release, and again on the release after that. Direction stays
            # blind here on purpose: drift reports CONTENT, it does not adjudicate downgrades.
            content = markdown_stamp_equivalent_content(content, current)
        if rel == LANE_ADAPTER_FILE and current is not None:
            # Provenance-stamp equivalence: identity stamps are not content, so a wheel-stamped
            # and a checkout-stamped adapter with identical content are both clean.
            if current != adapter_stamp_equivalent_content(content, current):
                on_disk_stamps = adapter_provenance_stamps(current)
                if (
                    on_disk_stamps is not None
                    and on_disk_stamps != adapter_provenance_stamps(content)
                ):
                    # True drift ACROSS builds: re-rendering here just flips the file to this
                    # runtime's render — the designed resolution is aligning the runtimes.
                    drift.append(f"{label} ({ADAPTER_TRUE_DRIFT_ALIGNMENT_HINT})")
                else:
                    drift.append(label)
            continue
        if current != content:
            drift.append(label)
    return drift


def protected_adapter_markdown(data: dict, project_path: Path, target: Path) -> list[str]:
    project_arg, source_path_override = expected_files_render_context(data, project_path, target)
    expected = expected_files(data, project_arg, source_path_override, target)
    return [str(path) for path in protected_handwritten_markdown(expected, target)]


def configured_path(target: Path, path_text: str, *, allow_outside: bool = False) -> Path:
    return paths_module().configured_path(target, path_text, allow_outside=allow_outside)


def file_sha256(path: Path) -> str:
    return util_module().file_sha256(path)


DONE_EVIDENCE_AC_TABLE_MODES = ("off", "warn", "strict")


def normalize_done_evidence(raw: object) -> dict:
    """`backlogProvider.doneEvidence`, the closure-verification knob block (item 81).

    Separate from `normalize_tracker_adapter_config` on purpose: that function is shared with the
    deprecated `goalTracker`, and a done-evidence policy on the legacy key would be a second place
    the mode could be set from.
    """
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter backlogProvider.doneEvidence must be an object")
    config = {**DEFAULT_BACKLOG_PROVIDER["doneEvidence"], **(raw or {})}
    config["acTable"] = str(config.get("acTable", "warn")).strip().lower()
    if config["acTable"] not in DONE_EVIDENCE_AC_TABLE_MODES:
        raise SystemExit(
            "Project adapter backlogProvider.doneEvidence.acTable must be off, warn, or strict"
        )
    return config


def normalize_plan_acceptance(data: dict) -> dict:
    raw = data.get("planAcceptance")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter planAcceptance must be an object")
    cfg = {**DEFAULT_PLAN_ACCEPTANCE, **(raw or {})}
    if cfg["enforcement"] not in {"off", "warn", "block"}:
        raise SystemExit("Project adapter planAcceptance.enforcement must be off, warn, or block")
    headings = cfg.get("acHeadings")
    if not isinstance(headings, list) or not all(isinstance(h, str) for h in headings):
        raise SystemExit("Project adapter planAcceptance.acHeadings must be a list of strings")
    cfg["acHeadings"] = [h.strip().lower() for h in headings if h.strip()] or list(DEFAULT_PLAN_ACCEPTANCE["acHeadings"])
    return cfg


def find_adapter_root(cwd: Path) -> Path | None:
    for candidate in [cwd, *cwd.parents]:
        if (candidate / LANE_ADAPTER_FILE).exists():
            return candidate
        if (candidate / LEGACY_LANE_ADAPTER_FILE).exists():
            sunset_warning("markers", LEGACY_LANE_ADAPTER_FILE, LANE_ADAPTER_FILE)
            return candidate
    return None


def adapter_marker_path(root: Path) -> Path:
    canonical = root / LANE_ADAPTER_FILE
    if canonical.exists():
        return canonical
    legacy = root / LEGACY_LANE_ADAPTER_FILE
    if legacy.exists():
        sunset_warning("markers", LEGACY_LANE_ADAPTER_FILE, LANE_ADAPTER_FILE)
        return legacy
    return canonical  # default write target


def onboarding_state(target: Path, invocation_cwd: Path) -> dict:
    """Classify a target's Tautline onboarding state by parent-walking evidence exactly like
    find_adapter_root (`[target, *target.parents]`). PURE and SHELL-FREE (only .exists() reads),
    so the SessionStart hook can call it under total containment. `root` is None for `unmanaged`
    (the VCS-toplevel resolution is a separate, shelling helper -- resolve_unmanaged_root -- that
    the hook path never calls). Precedence: managed > source-unrendered > interview-pending >
    unmanaged. `invocation_cwd` is the TRUE process cwd (distinct from --target) so a paste-able
    command renders from where the operator sits."""
    target = Path(target)
    invocation_cwd = Path(invocation_cwd)
    marker_root = find_adapter_root(target)
    source_root: Path | None = None
    source_path: Path | None = None
    interview_root: Path | None = None
    interview_path: Path | None = None
    for candidate in [target, *target.parents]:
        if source_root is None:
            canonical = candidate / REPO_LOCAL_ADAPTER_FILE
            legacy = candidate / LEGACY_REPO_LOCAL_ADAPTER_FILE
            if canonical.exists():
                source_root, source_path = candidate, canonical
            elif legacy.exists():
                source_root, source_path = candidate, legacy
        if interview_root is None:
            interview = candidate / DEFAULT_BOOTSTRAP_INTERVIEW_PATH
            if interview.exists():
                interview_root, interview_path = candidate, interview
    if marker_root is not None:
        state, root = "managed", marker_root
    elif source_root is not None:
        state, root = "source-unrendered", source_root
    elif interview_root is not None:
        state, root = "interview-pending", interview_root
    else:
        state, root = "unmanaged", None
    return {
        "state": state,
        "target": target,
        "invocation_cwd": invocation_cwd,
        "root": root,
        "source_path": source_path if state == "source-unrendered" else None,
        "interview_path": interview_path if state == "interview-pending" else None,
    }


def no_adapter_message_for(target: Path) -> str:
    """Raise-site convenience: classify `target` from the true process cwd and compose the
    state-correct no-adapter message. Used by every direct raise site."""
    return no_adapter_message(onboarding_state(target, Path.cwd()))


def path_is_under(path: Path, root: Path) -> bool:
    return util_module().path_is_under(path, root)


def adapter_render_refs(trigger: str, runtime_version: str, paths: list[Path]) -> dict:
    """Who rendered, from where, with which template.

    `trigger` alone is too coarse to answer the question the incident posed: it is a constant per
    call site, so every render reached through lane-start reports "lane-start" no matter what
    launched it. The incident was two concurrently launched sessions in SIBLING WORKTREES, so the
    useful discriminators are process and location. Paths and ids only -- no product narrative.
    """
    session = (
        util_module().resolve_env("CLAUDE_CODE_SESSION_ID")
        or util_module().resolve_env("MINERVIT_SESSION_ID")
        or "unknown"
    )
    return {
        "trigger": trigger or "unknown",
        "pid": os.getpid(),
        "argv0": sys.argv[0] if sys.argv else "",
        "session": session,
        "runtime_version": runtime_version,
        "cwd": str(Path.cwd()),
        "files": sorted(path.name for path in paths),
    }


def _narrate_adapter_render(
    data: dict,
    target: Path,
    *,
    trigger: str,
    written: list[Path],
    overwritten: list[Path],
    downgraded: list[Path],
    runtime_version: str,
) -> None:
    """Item 69 control 3: make the next unexpected render self-identifying instead of forensic.

    The EVENT is emitted only when a pre-existing generated file was OVERWRITTEN. Creating these
    files for the first time -- onboarding, a fresh worktree, every test fixture -- cannot be the
    skew this exists to diagnose, and an always-on producer on the shared lane event log is noise
    that buries the one record anybody will ever look for. The stdout line still names every
    render that wrote, because that costs nothing and reads in context.
    """
    if written:
        joined = ", ".join(
            str(path.relative_to(target)) if path.is_relative_to(target) else str(path)
            for path in written
        )
        print(f"adapter_render_trigger: {trigger or 'unknown'} wrote {joined}")
    if overwritten:
        try_write_event(
            data,
            target,
            event="adapter_render",
            severity="info",
            plain=(
                f"{trigger or 'unknown'} overwrote {len(overwritten)} existing generated adapter "
                f"file(s) at {runtime_version}"
            ),
            next_action=(
                "none -- informational; if this render was unexpected, run "
                "`git diff -- CLAUDE.md AGENTS.md .tautline.json` and compare "
                "`refs.runtime_version` against the on-disk template stamp"
            ),
            refs=adapter_render_refs(trigger, runtime_version, overwritten),
        )
    for dest in downgraded:
        stamp = on_disk_template_stamp(dest)
        refs = adapter_render_refs(trigger, runtime_version, [dest])
        refs["on_disk_stamp"] = stamp
        try_write_event(
            data,
            target,
            event="adapter_render_refused",
            severity="warn",
            plain=(
                f"{trigger or 'unknown'} refused to downgrade {dest.name} "
                f"(on-disk template {stamp})"
            ),
            next_action=(
                "update or repin the runtime past the on-disk template, or re-render deliberately "
                "from the newer runtime with `tautline render-adapters --write "
                "--allow-template-downgrade`"
            ),
            refs=refs,
        )


def methodology_upstream() -> tuple[str, str, str] | None:
    args = ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    upstream = run_git(canonical_methodology_repo(), args)
    if upstream == "unavailable" or "/" not in upstream:
        return None
    remote, branch = upstream.split("/", 1)
    return remote, branch, upstream


def methodology_release_upstream(channel: str = "stable") -> tuple[str, str, str] | None:
    branch_name = framework_channel_branch(channel)
    if run_git(canonical_methodology_repo(), ["remote", "get-url", "origin"]) != "unavailable":
        return "origin", branch_name, f"origin/{branch_name}"
    upstream = methodology_upstream()
    if upstream and upstream[1] == branch_name:
        return upstream
    return None


METHODOLOGY_UPDATE_POLICY_ENV = "MINERVIT_METHODOLOGY_UPDATE_POLICY"
METHODOLOGY_UPDATE_PINS_ENV = "MINERVIT_METHODOLOGY_UPDATE_PINS"
METHODOLOGY_UPDATE_SIGNERS_ENV = "MINERVIT_METHODOLOGY_UPDATE_SIGNERS"
METHODOLOGY_UPDATE_PINS_FILE = Path.home() / ".config" / "minervit" / "methodology.update-pins"


def methodology_update_policy() -> str:
    policy = util_module().resolve_env(METHODOLOGY_UPDATE_POLICY_ENV).strip().lower()
    if policy in ("signed", "pinned", "unverified", "warn"):
        return policy
    return "warn"  # backward-compatible default; public distribution should set signed|pinned


def _methodology_update_pins() -> set[str]:
    raw_pins = util_module().resolve_env(METHODOLOGY_UPDATE_PINS_ENV)
    pins: set[str] = {p for p in re.split(r"[,\s]+", raw_pins) if p}
    try:
        for line in METHODOLOGY_UPDATE_PINS_FILE.read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if entry and not entry.startswith("#"):
                pins.add(entry)
    except OSError:
        pass
    return pins


def verify_upstream_trust(new_head: str) -> tuple[bool, str]:
    """Decide whether code at new_head may be re-exec'd after an auto-update (sec-trust-exec-1).

    The auto-update fast-forwards then os.execve's the NEW code. Without a trust check, one upstream
    compromise = fleet-wide RCE for every adopter pointed at a shared upstream. Policy is read from
    MINERVIT_METHODOLOGY_UPDATE_POLICY:
      - signed:     require a valid signature on new_head (git verify-commit); optional signer
                    allowlist via MINERVIT_METHODOLOGY_UPDATE_SIGNERS.
      - pinned:     require new_head to match a pinned commit/tag (MINERVIT_METHODOLOGY_UPDATE_PINS
                    or ~/.config/minervit/methodology.update-pins).
      - unverified: explicit opt-out for a single trusted operator on a trusted machine.
      - warn (default): allow, but emit a loud warning recommending a strict policy. This keeps the
                    existing single-operator workflow working while making the gate available and
                    enforceable; public distribution MUST set signed or pinned (see SECURITY.md).
    Returns (allowed, message); the caller refuses the re-exec when allowed is False.
    """
    policy = methodology_update_policy()
    if policy == "unverified":
        return True, ""
    # Trust is decided against the CANONICAL checkout: the candidate commit was fetched into it,
    # and a snapshot exec root holds no objects to resolve a pin or verify a signature against.
    canonical = canonical_methodology_repo()
    if policy == "pinned":
        pins = _methodology_update_pins()
        if not pins:
            return False, (
                "update policy 'pinned' but no pins configured; set "
                f"{METHODOLOGY_UPDATE_PINS_ENV} or {METHODOLOGY_UPDATE_PINS_FILE}"
            )
        if new_head in pins:
            return True, ""
        for pin in pins:
            if run_git(canonical, ["rev-parse", "--verify", f"{pin}^{{commit}}"]) == new_head:
                return True, ""
        return False, f"new upstream commit {new_head[:12]} is not in the pinned allowlist"
    if policy == "signed":
        code, _out, _err = run_command(["git", "-C", str(canonical), "verify-commit", "--raw", new_head])
        if code != 0:
            return False, f"new upstream commit {new_head[:12]} is not validly signed (git verify-commit failed)"
        raw_signers = util_module().resolve_env(METHODOLOGY_UPDATE_SIGNERS_ENV)
        signers = [s for s in re.split(r"[,\s]+", raw_signers) if s]
        if signers:
            _code2, _out2, info = run_command(["git", "-C", str(canonical), "verify-commit", "--raw", new_head])
            if not any(signer in (info or "") for signer in signers):
                return False, f"new upstream commit {new_head[:12]} signer not in allowlist {signers}"
        return True, ""
    return True, (
        f"WARNING: re-executing updated methodology at {new_head[:12]} WITHOUT upstream trust "
        f"verification. Set {METHODOLOGY_UPDATE_POLICY_ENV}=signed or =pinned to verify the upstream "
        "before re-exec (strongly recommended for any shared upstream)."
    )


def _generic_pinned_advance_remedy() -> str:
    """The pin remedy the trust gate falls back to.

    Shared verbatim with the held-status formatter in update_methodology_repo, which swaps this
    exact text for a resolved offer when it knows the held candidate -- one definition, so the
    generic remedy and the text the swap looks for can never drift apart.

    Names the PIN SURFACE, not a verb. `update-repin` was a convenience that rewrote the pins file;
    the 2026-08-28 demolition removed it, and an operator following that name now gets "invalid
    choice" while still blocked. The gate itself is untouched -- it is the fail-closed half of
    sec-trust-exec-1 -- and the allowlist it reads was always operator-writable directly, so the
    remedy is the file and the environment variable it has always consulted.
    """
    return (
        f"add the reviewed commit to the trusted pins ({METHODOLOGY_UPDATE_PINS_ENV}, or one "
        f"commit/tag per line in {METHODOLOGY_UPDATE_PINS_FILE}) and re-run"
    )


def gate_methodology_upstream_advance(candidate_head: str) -> str | None:
    """Return None when the checkout may advance to candidate_head, else a refusal detail (sec-trust-exec-1).

    Verify-before-advance: callers fetch the upstream commit WITHOUT moving the checkout, call this against
    the FETCHED sha, and only reset/merge/switch when it returns None. Advancing first and verifying after
    is the ungated-RCE bug this closes -- a bare `git pull --ff-only` (or an eager reset/switch) moves the
    on-disk bin/minervit-methodology to unverified code, and the next shim invocation then executes it even
    though this process refuses to re-exec it. Fail-closed = the working tree never advances to code the
    trust policy would reject. (The warn-policy advisory is emitted by the post-advance re-exec gate, so
    this helper stays silent on the allow path to avoid a duplicate warning.)
    """
    allowed, trust_msg = verify_upstream_trust(candidate_head)
    if not allowed:
        # Recovery guidance must match the failing policy: update-repin only rewrites the
        # pinned allowlist and is ignored by the signed policy, so routing a signed-policy
        # failure to repin would leave the operator blocked after following the advice.
        if methodology_update_policy() == "signed":
            recovery = (
                "ensure the new upstream head carries a valid signature from a trusted key "
                f"(and that the signer is listed in {METHODOLOGY_UPDATE_SIGNERS_ENV} when a signer "
                "allowlist is set); see SECURITY.md"
            )
        else:
            recovery = (
                "review the incoming commits (git log <current>..origin/<branch> in the methodology checkout), then "
                f"{_generic_pinned_advance_remedy()}; see SECURITY.md"
            )
        return (
            f"refusing to advance methodology checkout to unverified upstream {candidate_head[:12]}: {trust_msg}; "
            + recovery
        )
    return None


def create_methodology_reexec_token(expected_head: str) -> str:
    """Write a single-use re-exec handoff token (sec-trust-exec-4).

    The token lives in a private 0700 directory under ~/.config/minervit with a 0600,
    unpredictable mkstemp name — not the shared, world-writable system tempdir where another
    local user could pre-create, read, or race the file.
    """
    token_dir = methodology_reexec_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    try:
        token_dir.chmod(0o700)
    except OSError:
        pass
    fd, token_name = tempfile.mkstemp(dir=str(token_dir), prefix=f"reexec-{expected_head[:12]}-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"expected_head": expected_head, "created_at": time.time(), "pid": os.getpid()}, handle)
    except BaseException:
        try:
            os.unlink(token_name)
        except OSError:
            pass
        raise
    try:
        Path(token_name).chmod(0o600)  # mkstemp already restricts, but be explicit
    except OSError:
        pass
    return token_name


def consume_methodology_reexec_token() -> bool | None:
    token = os.environ.get(METHODOLOGY_REEXEC_TOKEN_ENV)
    if not token:
        return None
    token_path = Path(token)
    try:
        token_stat = token_path.stat()
    except OSError:
        return False
    # Reject a token planted by another local user: only trust one this uid owns.
    if hasattr(os, "getuid") and token_stat.st_uid != os.getuid():
        try:
            token_path.unlink()
        except OSError:
            pass
        return False
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    finally:
        try:
            token_path.unlink()
        except OSError:
            pass
    if not isinstance(payload, dict):
        return False
    expected_head = payload.get("expected_head")
    created_at = payload.get("created_at")
    if not isinstance(expected_head, str) or not isinstance(created_at, (int, float)):
        return False
    if time.time() - float(created_at) > METHODOLOGY_REEXEC_TOKEN_MAX_AGE_SECONDS:
        return False
    if not expected_head:
        return False
    manifest = snapshot_manifest()
    if manifest is not None:
        # A snapshot is an exported tree with no `.git`: `rev-parse` returns run_git's
        # "unavailable" sentinel, so the git check below could never match and EVERY post-advance
        # re-exec would be rejected as an invalid token. The manifest carries the truthful commit,
        # and an immutable tree cannot be dirty, so the porcelain check is vacuous here.
        return str(manifest["commit"]) == expected_head
    canonical = canonical_methodology_repo()
    current_head = run_git(canonical, ["rev-parse", "HEAD"])
    dirty = run_git(canonical, ["status", "--porcelain"])
    return bool(current_head == expected_head and dirty == "")


def methodology_rescue_state_dir() -> Path:
    configured = util_module().resolve_env(METHODOLOGY_RESCUE_STATE_ENV)
    if configured:
        return Path(configured).expanduser()
    # write-new/read-both: default to the tautline dir, but keep using a pre-existing legacy dir so
    # in-flight rescue state written under the old brand is not orphaned. No lock/mutex lives here.
    base = Path.home() / ".local" / "state"
    tautline = base / "tautline" / "methodology-rescue"
    legacy = base / "minervit" / "methodology-rescue"
    if not tautline.exists() and legacy.exists():
        return legacy
    return tautline


def move_untracked_methodology_files(rescue_branch: str) -> tuple[Path | None, str | None]:
    canonical = canonical_methodology_repo()
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "ls-files", "--others", "--exclude-standard", "-z"])
    if code != 0:
        return None, stderr or stdout or "could not list untracked files"
    paths = [part for part in stdout.split("\0") if part]
    if not paths:
        return None, None
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]+", "_", rescue_branch)
    rescue_dir = methodology_rescue_state_dir() / safe_branch / "untracked"
    moved: list[tuple[Path, Path]] = []
    for rel in paths:
        source = canonical / rel
        if not source.exists():
            continue
        dest = rescue_dir / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            moved.append((source, dest))
        except OSError as exc:
            rollback_errors: list[str] = []
            for original, moved_dest in reversed(moved):
                try:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(moved_dest), str(original))
                except OSError as rollback_exc:
                    rollback_errors.append(f"{moved_dest} -> {original}: {rollback_exc}")
            rollback_detail = f"; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
            return rescue_dir, f"could not preserve untracked file {rel}: {exc}{rollback_detail}"
    return rescue_dir, None


def tracked_private_source_adapter_paths(repo: Path | None = None) -> list[str]:
    repo = repo or canonical_methodology_repo()
    code, stdout, _stderr = run_command(["git", "-C", str(repo), "ls-files", "-z", "--", "adapters/projects/*.json"])
    if code != 0:
        return []
    paths = []
    for rel in [part for part in stdout.split("\0") if part]:
        path = Path(rel)
        if (
            path.as_posix().startswith("adapters/projects/")
            and not path.name.startswith(".")
            and path.name not in PUBLIC_RELEASE_ALLOWED_SOURCE_ADAPTERS
        ):
            paths.append(path.as_posix())
    return sorted(dict.fromkeys(paths))


def copy_private_source_adapters_for_reset(
    repo: Path | None = None,
    *,
    reason: str = "release-reset",
) -> tuple[list[tuple[str, Path]], str]:
    repo = repo or canonical_methodology_repo()
    paths = tracked_private_source_adapter_paths(repo)
    if not paths:
        return [], ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason).strip("-") or "release-reset"
    rescue_dir = methodology_rescue_state_dir() / "private-adapters" / f"{stamp}-{os.getpid()}-{safe_reason}"
    copied: list[tuple[str, Path]] = []
    try:
        for rel in paths:
            source = repo / rel
            if not source.exists() or not source.is_file():
                continue
            dest = rescue_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            copied.append((rel, dest))
    except OSError as exc:
        return [], f"private adapter preservation failed before reset: {exc}"
    if not copied:
        return [], ""
    return copied, f"; preserved private source adapters at {rescue_dir}"


def restore_private_source_adapters_after_reset(
    copied: list[tuple[str, Path]],
    repo: Path | None = None,
) -> tuple[bool, str]:
    repo = repo or canonical_methodology_repo()
    if not copied:
        return True, ""
    restored: list[str] = []
    for rel, source in copied:
        dest = repo / rel
        if dest.exists():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            restored.append(rel)
        except OSError as exc:
            return False, f"; failed to restore private source adapter {rel} from {source}: {exc}"
    if not restored:
        return True, ""
    return True, f"; restored private source adapters: {', '.join(restored)}"


def methodology_git_path(path_name: str) -> Path | None:
    canonical = canonical_methodology_repo()
    git_path = run_git(canonical, ["rev-parse", "--git-path", path_name])
    if not git_path or git_path == "unavailable":
        return None
    path = Path(git_path)
    return path if path.is_absolute() else canonical / path


def methodology_release_main_pre_commit_hook() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "# Generated by minervit-methodology. Protects release main from local commits.",
            "set -u",
            f'case "${{{METHODOLOGY_MAIN_COMMIT_OVERRIDE_ENV}:-}}" in',
            "  1|true|TRUE|yes|YES)",
            "    exit 0",
            "    ;;",
            "esac",
            'branch="$(git branch --show-current 2>/dev/null || true)"',
            'if [ "$branch" = "main" ]; then',
            "  printf '%s\\n' 'Minervit methodology release main is protected from local commits.' >&2",
            "  printf '%s\\n' 'Create a feature branch and merge through GitHub PR instead.' >&2",
            f"  printf '%s\\n' 'Break-glass only: set {METHODOLOGY_MAIN_COMMIT_OVERRIDE_ENV}=1 for this single commit.' >&2",
            "  printf '%s\\n' 'If local main already diverged, reset it: git fetch origin && git reset --hard origin/main' >&2",
            "  exit 1",
            "fi",
            "exit 0",
            "",
        ]
    )


def install_methodology_release_guards() -> str:
    if running_from_installed_package():
        # Same standdown, same rationale as update_methodology_repo: this writer sets
        # `git config --local pull.ff only` and installs hooks INTO the canonical checkout,
        # which in package mode is at best a leftover the wheel never executes (PP-R1-P1-1).
        return "skipped - installed package runtime; no methodology checkout to guard"
    canonical = canonical_methodology_repo()
    if run_git(canonical, ["rev-parse", "--is-inside-work-tree"]) != "true":
        return "skipped - methodology checkout is not a Git worktree"
    code, _stdout, stderr = run_command(["git", "-C", str(canonical), "config", "--local", "pull.ff", "only"])
    if code != 0:
        return f"failed - could not set pull.ff=only: {stderr or 'git config failed'}"
    hook_path = methodology_git_path("hooks/pre-commit")
    if hook_path is None:
        return "skipped - could not resolve git hooks path"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    desired = methodology_release_main_pre_commit_hook()
    head = run_git(canonical, ["rev-parse", "HEAD"])
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if existing == desired:
            return f"already ok - {hook_path}"
        if "Generated by minervit-methodology. Protects release main from local commits." not in existing:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            preserved = hook_path.with_name(f"{hook_path.name}.pre-minervit-{stamp}")
            shutil.move(str(hook_path), str(preserved))
            hook_path.write_text(desired, encoding="utf-8")
            hook_path.chmod(0o755)
            detail = f"installed - {hook_path}; preserved previous hook at {preserved}"
            append_methodology_write_journal(
                "install-methodology-release-guards", head, head, "ok", detail=detail
            )
            return detail
    hook_path.write_text(desired, encoding="utf-8")
    hook_path.chmod(0o755)
    detail = f"installed - {hook_path}"
    # Journaled only when it CHANGED something: this runs on every launch, and an "already ok"
    # entry per lane per launch would bury the mutations the journal exists to attribute.
    append_methodology_write_journal(
        "install-methodology-release-guards", head, head, "ok", detail=detail
    )
    return detail


def preserve_release_branch_pointer(branch_name: str, upstream_ref: str, reason: str) -> tuple[bool, str]:
    """Preserve the prior release branch on a rescue ref before a reset --hard to upstream.

    Returns (preserved_ok, detail). `preserved_ok` is False ONLY when a preservation that was
    genuinely required (local release branch carries unique commits) could not be created -- the caller must
    then abort before resetting so divergent work is never dropped. Nothing-to-preserve (main equals
    or is an ancestor of upstream) returns (True, "")."""
    canonical = canonical_methodology_repo()
    branch_ref = f"refs/heads/{branch_name}"
    main_sha = run_git(canonical, ["rev-parse", branch_ref])
    upstream_sha = run_git(canonical, ["rev-parse", upstream_ref])
    if main_sha in ("unavailable", upstream_sha):
        return True, ""
    # Preserve only when local main carries commits the upstream does not. A main that is merely
    # behind/fast-forwardable to upstream (an ancestor of it) has nothing unique to rescue, so a
    # reset --hard loses nothing and a rescue ref would be pure pollution -- it later trips the
    # rescue-ref drift detector and, on an intentionally-non-main checkout, contributed to a lane
    # wedge (RCA: non-main auto-rescue phantom ref). Only code==0 (definitely an ancestor) skips;
    # an error (code not in {0,1}) falls through to preserve so divergent work is never dropped.
    ancestor_code, _stdout, _stderr = run_command(
        ["git", "-C", str(canonical), "merge-base", "--is-ancestor", branch_ref, upstream_ref]
    )
    if ancestor_code == 0:
        return True, ""
    short_main = run_git(canonical, ["rev-parse", "--short", branch_ref])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason).strip("-") or branch_name
    rescue_branch = f"tautline-local-rescue/{stamp}-{os.getpid()}-{safe_reason}-{short_main}"
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "branch", rescue_branch, branch_ref])
    if code != 0:
        return False, f"; warning: could not preserve prior {branch_name} before reset: {stderr or stdout or 'command failed'}"
    return True, f"; preserved prior {branch_name} at {rescue_branch}"


def switch_release_branch(
    upstream_ref: str,
    branch_name: str,
    reason: str,
    preserve_existing_main: bool = True,
) -> tuple[bool, str]:
    canonical = canonical_methodology_repo()
    preserved_detail = ""
    if preserve_existing_main:
        # Fail closed: if a required preservation could not be created, abort before reset --hard so
        # divergent local main commits are never dropped (Codex P2: preservation was fail-open).
        preserved_ok, preserved_detail = preserve_release_branch_pointer(branch_name, upstream_ref, reason)
        if not preserved_ok:
            return False, f"auto-rescue aborted before reset because prior release {branch_name} could not be preserved{preserved_detail}"
    copied_private_adapters, private_adapter_detail = copy_private_source_adapters_for_reset(reason=reason)
    if private_adapter_detail.startswith("private adapter preservation failed"):
        return False, private_adapter_detail
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "switch", branch_name])
    if code != 0:
        code, stdout, stderr = run_command(["git", "-C", str(canonical), "switch", "-c", branch_name, upstream_ref])
        if code != 0:
            return False, f"auto-rescue failed during return to release {branch_name}: {stderr or stdout or 'command failed'}"
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "reset", "--hard", upstream_ref])
    if code != 0:
        return False, f"auto-rescue failed during reset release {branch_name} to upstream: {stderr or stdout or 'command failed'}"
    restored_ok, restore_detail = restore_private_source_adapters_after_reset(copied_private_adapters)
    if not restored_ok:
        return False, f"auto-rescue reset release {branch_name} but private adapter restore failed{restore_detail}{private_adapter_detail}"
    return True, preserved_detail + private_adapter_detail + restore_detail


def switch_release_main(upstream_ref: str, reason: str, preserve_existing_main: bool = True) -> tuple[bool, str]:
    return switch_release_branch(upstream_ref, "main", reason, preserve_existing_main)


def methodology_main_divergence(upstream_ref: str, branch_name: str = "main") -> tuple[int, int] | None:
    canonical = canonical_methodology_repo()
    code, stdout, _stderr = run_command(
        ["git", "-C", str(canonical), "rev-list", "--left-right", "--count", f"refs/heads/{branch_name}...{upstream_ref}"]
    )
    if code != 0:
        return None
    parts = stdout.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def repair_methodology_release_main_checkout(channel: str = "stable") -> tuple[bool, str]:
    canonical = canonical_methodology_repo()
    release_branch = framework_channel_branch(channel)
    upstream = methodology_release_upstream(channel)
    if upstream is None:
        return False, f"cannot repair methodology {release_branch} because release origin/{release_branch} is not configured"
    remote, branch, upstream_ref = upstream
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "fetch", remote, branch])
    if code != 0:
        return False, f"cannot repair methodology {release_branch} because release fetch failed: {stderr or stdout or 'command failed'}"
    if run_git(canonical, ["rev-parse", upstream_ref]) == "unavailable":
        return False, f"cannot repair methodology {release_branch} because release ref is unavailable: {upstream_ref}"
    dirty = run_git(canonical, ["status", "--porcelain"])
    if dirty == "unavailable":
        return False, f"cannot repair methodology {release_branch} because git status is unavailable"
    if dirty:
        rescued, detail, _rescue_branch = rescue_methodology_local_changes(upstream)
        return rescued, detail
    branch_name = run_git(canonical, ["branch", "--show-current"])
    if branch_name not in (release_branch, "unavailable"):
        rescued, detail, _rescue_branch = rescue_methodology_non_main_checkout(branch_name or "detached HEAD", channel)
        return rescued, detail
    divergence = methodology_main_divergence(upstream_ref, release_branch)
    if divergence is None:
        return False, f"cannot repair methodology {release_branch} because local-vs-origin divergence could not be measured"
    ahead, behind = divergence
    if ahead == 0 and behind == 0:
        guard = install_methodology_release_guards()
        return True, f"release main already matches {upstream_ref}; {guard}"
    old_head = run_git(canonical, ["rev-parse", "refs/heads/main"])
    # Verify-before-advance (sec-trust-exec-1): refuse before the switch/reset so a denied upstream
    # never advances the release main to unverified code.
    refusal = gate_methodology_upstream_advance(run_git(canonical, ["rev-parse", upstream_ref]))
    if refusal is not None:
        append_methodology_write_journal(
            "repair-methodology-main", old_head, old_head, "held", detail=refusal
        )
        return False, refusal
    switched, switch_detail = switch_release_branch(upstream_ref, release_branch, "divergent-main", preserve_existing_main=ahead > 0)
    if not switched:
        append_methodology_write_journal(
            "repair-methodology-main", old_head, old_head, "failed", detail=switch_detail
        )
        return False, switch_detail
    new_head = run_git(canonical, ["rev-parse", "HEAD"])
    guard = install_methodology_release_guards()
    if ahead > 0:
        detail = (
            f"rescued divergent methodology main ahead={ahead} behind={behind}{switch_detail}; "
            f"reset {old_head[:12]} -> {new_head[:12]}; {guard}"
        )
    else:
        detail = (
            f"fast-forwarded methodology main behind={behind}; "
            f"reset {old_head[:12]} -> {new_head[:12]}; {guard}"
        )
    append_methodology_write_journal(
        "repair-methodology-main", old_head, new_head, "ok", detail=detail
    )
    return True, detail


def rescue_methodology_local_changes(upstream: tuple[str, str, str] | None = None) -> tuple[bool, str, str]:
    canonical = canonical_methodology_repo()
    upstream = upstream or methodology_upstream()
    if upstream is None:
        return False, "cannot auto-rescue local changes because no supported upstream is configured", ""
    remote, branch, upstream_ref = upstream
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "fetch", remote, branch])
    if code != 0:
        return False, f"cannot auto-rescue local changes because upstream fetch failed: {stderr or stdout or 'command failed'}", ""
    upstream_sha = run_git(canonical, ["rev-parse", upstream_ref])
    if upstream_sha == "unavailable":
        return False, f"cannot auto-rescue local changes because upstream ref is unavailable: {upstream_ref}", ""
    # Verify-before-advance (sec-trust-exec-1): the fetch above did not move the checkout; refuse now,
    # before any rescue branch / commit / reset, so a denied upstream never advances the working tree.
    refusal = gate_methodology_upstream_advance(upstream_sha)
    if refusal is not None:
        return False, refusal, ""
    original_branch = run_git(canonical, ["branch", "--show-current"])
    old_head = run_git(canonical, ["rev-parse", "HEAD"])
    short_head = run_git(canonical, ["rev-parse", "--short", "HEAD"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rescue_branch = f"tautline-local-rescue/{stamp}-{os.getpid()}-{short_head}"

    def _failed(detail: str) -> tuple[bool, str, str]:
        append_methodology_write_journal(
            "rescue-methodology-local-changes", old_head, old_head, "failed", detail=detail
        )
        return False, detail, rescue_branch

    code, stdout, stderr = run_command(["git", "-C", str(canonical), "switch", "-c", rescue_branch])
    if code != 0:
        return _failed(f"auto-rescue failed during create rescue branch: {stderr or stdout or 'command failed'}")
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "add", "-u"])
    if code != 0:
        return _failed(f"auto-rescue failed during stage tracked methodology changes: {stderr or stdout or 'command failed'}")
    staged_code, _staged_stdout, staged_stderr = run_command(["git", "-C", str(canonical), "diff", "--cached", "--quiet"])
    if staged_code not in (0, 1):
        return _failed(f"auto-rescue failed during staged change check: {staged_stderr or 'command failed'}")
    if staged_code == 1:
        commit_command = [
            "git",
            "-C",
            str(canonical),
            "-c",
            "user.name=Minervit Methodology",
            "-c",
            "user.email=methodology@minervit.local",
            "commit",
            "-m",
            "chore: preserve local methodology changes before auto-sync",
        ]
        code, stdout, stderr = run_command(commit_command)
        if code != 0:
            run_command(["git", "-C", str(canonical), "reset"])
            return _failed(f"auto-rescue failed during commit rescue branch: {stderr or stdout or 'command failed'}")
    untracked_dir, untracked_error = move_untracked_methodology_files(rescue_branch)
    if untracked_error:
        return _failed(f"auto-rescue failed while preserving untracked files: {untracked_error}")
    switched, switch_detail = switch_release_main(upstream_ref, "local-changes", preserve_existing_main=original_branch != "main")
    if not switched:
        return _failed(switch_detail)
    new_head = run_git(canonical, ["rev-parse", "HEAD"])
    untracked_detail = f"; untracked files moved to {untracked_dir}" if untracked_dir else ""
    if old_head != "unavailable" and new_head != "unavailable":
        detail = f"rescued local changes to {rescue_branch}{untracked_detail}{switch_detail}; updated {old_head[:12]} -> {new_head[:12]}"
    else:
        detail = f"rescued local changes to {rescue_branch}{untracked_detail}{switch_detail}; reset main to {upstream_ref}"
    append_methodology_write_journal(
        "rescue-methodology-local-changes", old_head, new_head, "ok", detail=detail
    )
    return True, detail, rescue_branch


def rescue_methodology_non_main_checkout(branch_display: str, channel: str = "stable") -> tuple[bool, str, str]:
    canonical = canonical_methodology_repo()
    release_branch = framework_channel_branch(channel)
    upstream = methodology_release_upstream(channel)
    if upstream is None:
        return False, f"cannot auto-rescue non-main methodology checkout because release origin/{release_branch} is not configured", ""
    remote, branch, upstream_ref = upstream
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "fetch", remote, branch])
    if code != 0:
        return False, f"cannot auto-rescue non-main methodology checkout because release fetch failed: {stderr or stdout or 'command failed'}", ""
    upstream_sha = run_git(canonical, ["rev-parse", upstream_ref])
    if upstream_sha == "unavailable":
        return False, f"cannot auto-rescue non-main methodology checkout because release ref is unavailable: {upstream_ref}", ""
    dirty = run_git(canonical, ["status", "--porcelain"])
    if dirty == "unavailable":
        return False, "cannot auto-rescue non-main methodology checkout because status is unavailable", ""
    if dirty:
        rescued, detail, rescue_branch = rescue_methodology_local_changes(upstream)
        if not rescued:
            return False, detail, rescue_branch
        return True, f"non-main checkout {branch_display}; {detail}", rescue_branch
    old_head = run_git(canonical, ["rev-parse", "HEAD"])
    # Verify-before-advance (sec-trust-exec-1): refuse before the switch/reset so a denied upstream
    # never advances a clean non-release checkout to unverified code.
    refusal = gate_methodology_upstream_advance(upstream_sha)
    if refusal is not None:
        return False, refusal, ""
    switched, switch_detail = switch_release_branch(upstream_ref, release_branch, "non-main")
    if not switched:
        append_methodology_write_journal(
            "rescue-methodology-non-main", old_head, old_head, "failed", detail=switch_detail
        )
        return False, switch_detail, ""
    new_head = run_git(canonical, ["rev-parse", "HEAD"])
    if old_head != "unavailable" and new_head != "unavailable":
        detail = (
            f"switched clean methodology checkout from non-release branch {branch_display} ({old_head[:12]}) "
            f"to release {release_branch} {new_head[:12]}; branch preserved{switch_detail}"
        )
    else:
        detail = (
            f"switched clean methodology checkout from non-release branch {branch_display} "
            f"to release {release_branch}{switch_detail}"
        )
    append_methodology_write_journal(
        "rescue-methodology-non-main", old_head, new_head, "ok", detail=detail
    )
    return True, detail, ""


def invoked_from_methodology_repo() -> bool:
    """True when the cwd is inside EITHER methodology root (containment must cover both).

    This suppresses project-startup auto-rescue when a lane is already standing in the framework
    itself. Post-migration those are two directories -- the snapshot we execute and the canonical
    checkout sync mutates -- and missing either one would let an operator working inside one of
    them get their own checkout auto-rescued out from under them.
    """
    try:
        cwd = Path.cwd().resolve(strict=False)
    except OSError:
        return False
    return path_is_under(cwd, REPO_ROOT) or path_is_under(cwd, canonical_methodology_repo())


def methodology_repo_slugs() -> set[str]:
    return {METHODOLOGY_REPO_SLUG.lower(), *(slug.lower() for slug in LEGACY_METHODOLOGY_REPO_SLUGS)}


def adapter_is_methodology_repo(data: dict) -> bool:
    slug = str(data.get("repo", "")).strip().lower()
    if slug not in methodology_repo_slugs():
        return False
    _warn_legacy_methodology_slug(slug)
    return True


def should_auto_rescue_methodology_for_project_startup() -> bool:
    if util_module().resolve_env("MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE") == "1":
        return False
    return not invoked_from_methodology_repo()


# --- The immutable snapshot store ----------------------------------------------------------
# Lanes must not execute a tree that `sync-methodology` is concurrently rewriting. So sync mutates
# only the canonical checkout, and each trust-verified commit is EXPORTED into
# <store>/<short12-sha>/ -- a tree with no .git, made physically read-only -- behind an atomically
# swapped `current` symlink. Three invariants hold the design up:
#
#   immutable   a published snapshot is 0444/0555 files and 0555 dirs. Immutability is enforced by
#               the filesystem, not by discipline: any write path we failed to retarget at the
#               canonical checkout fails LOUDLY here instead of silently corrupting the tree that
#               other lanes are mid-execution on.
#   atomic      a snapshot is visible complete or not at all (stage in .tmp/, publish by rename),
#               and every failure path leaves the store exactly as it found it.
#   safe prune  retention never deletes a tree something is still executing: the current target,
#               a live pin, a recently-current snapshot, or the newest `keep`.
#
# PERMISSIONS AND rename(2) -- the trap that shapes the code below. Once a tree is 0555 you can
# neither move it to a new parent (rename must update its `..` entry, which needs write permission
# on the directory being moved: EACCES) nor delete it (unlinking a child needs write permission on
# its 0555 parent). shutil.rmtree(..., ignore_errors=True) fails at that SILENTLY. So: the
# read-only pass deliberately leaves the tree's ROOT writable and the caller locks it after the
# publish rename; prune restores the root's write bit before its rename; and every removal of a
# tree that may already be read-only goes through _rmtree_force. Nothing here may use bare rmtree.

SNAPSHOT_KEEP_ENV = "MINERVIT_METHODOLOGY_SNAPSHOT_KEEP"
SNAPSHOT_PIN_TTL_HOURS_ENV = "MINERVIT_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS"
_SNAPSHOT_DIR_PATTERN = re.compile(r"[0-9a-f]{12}")


_SNAPSHOT_STORE_WARNINGS: set[str] = set()

# Errno-sensitive fault naming: "store unreadable" on a full disk sends the operator chasing
# permissions instead of freeing space. These five cover the write faults prune can hit
# (ENOSPC/EDQUOT), the read-only-mount and stale-mount cases the helper's docstring names, and
# raw device errors. EACCES/EPERM stay on the default -- the exec integration tests pin it.
# getattr-guarded: EDQUOT/ESTALE are POSIX-only and absent from errno on native
# Windows -- direct attribute access would crash the CLI at IMPORT, before any
# command could run (Codex R2 on the 0.10.3 train).
_SNAPSHOT_STORE_FAULT_PHRASES: dict[int, str] = {
    code: phrase
    for name, phrase in (
        ("ENOSPC", "store out of space"),
        ("EDQUOT", "store quota exhausted"),
        ("EROFS", "store on a read-only filesystem"),
        ("ESTALE", "store on a stale mount"),
        ("EIO", "store I/O error"),
    )
    if (code := getattr(errno, name, None)) is not None
}


def warn_snapshot_store_unreadable(operation: str, exc: OSError) -> None:
    """Announce a store read that could not complete -- once per distinct failure per process.

    Reading the store must NEVER raise past its helper. The store is an optimization, never a
    dependency: "I cannot even look at it" has to answer the same as "there is nothing there" --
    no usable current, run the canonical checkout -- because a launch that dies on a chmod, an ACL,
    a stale mount or a full disk is the one failure mode the store was built to be incapable of.
    (A raise here does not merely fail a command: under the launcher's no-dead-ends policy a failed
    sync gate escalates to a repair session, so an unreadable store would drive the whole fleet into
    repair instead of quietly degrading.)

    But it must not degrade SILENTLY either, or a store that has been broken for weeks looks exactly
    like a machine that never enabled one. Deduplicated because a single sync reads the store
    several times over (gate skip, heal, stamp, pin refresh) and four copies of one line say nothing
    the first does not. The wording is errno-sensitive (_SNAPSHOT_STORE_FAULT_PHRASES) so the one
    line the operator gets names the actual fault, not a blanket "unreadable".

    The warning rides stderr: `snapshot-status` stdout is its machine-readable key:value report,
    and a degrade line dropped into the middle of it corrupts what a script is parsing.
    """
    phrase = _SNAPSHOT_STORE_FAULT_PHRASES.get(exc.errno, "store unreadable")
    detail = f"methodology_snapshot: {phrase} - {operation}: {exc}"
    if detail in _SNAPSHOT_STORE_WARNINGS:
        return
    _SNAPSHOT_STORE_WARNINGS.add(detail)
    print(detail, file=sys.stderr, flush=True)


def _snapshot_dir_manifest(dest: Path) -> dict | None:
    """The manifest of a snapshot directory in the store (vs. snapshot_manifest(), which reads the
    one we are EXECUTING). A dir with no readable, schema-matching manifest is not a snapshot: it
    is a partial publish or a foreign directory, and must never be reused or trusted."""
    try:
        data = json.loads((dest / SNAPSHOT_MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_MANIFEST_SCHEMA:
        return None
    return data


def _snapshot_is_executable(snapshot_dir: Path) -> bool:
    """Can anything actually RUN this snapshot?

    The one predicate that decides whether a snapshot is usable, and it is not the manifest. The
    shim asks `[ -x "$SNAPSHOT_CURRENT/bin/tautline" ]`, the launcher asks the same of
    `$SNAPSHOT_STORE/current/bin/tautline`, and both fall through to the canonical checkout when the
    answer is no. Python has to ask exactly that question, of exactly that path, or the two halves
    of one machine disagree about whether the store works: a manifest is an INDEX ENTRY, and a
    `current` whose .snapshot-meta.json is pristine while its CLI has been deleted is not a healthy
    snapshot, it is a trap that every shim on the machine execs into and every shim falls out of.
    """
    try:
        cli_path = snapshot_dir / "bin" / CLI_NAME
        return cli_path.is_file() and os.access(cli_path, os.X_OK)
    except OSError:
        return False


def _store_snapshot_dirs(store: Path) -> list[Path]:
    """Published snapshots, oldest -> newest.

    materializedAt is second-granularity, so mtime breaks ties and the (stable, arbitrary) name
    breaks the rest. Anything without a valid manifest is not listed -- it is not a snapshot.

    An unreadable store lists as EMPTY, never as an exception: same contract as
    methodology_snapshot_current_dir(). The guard has to span the stat()s as well as the iterdir(),
    and not just the iterdir() it once covered -- listing a directory needs only READ permission
    while stat-ing what is in it needs SEARCH, so a store with one but not the other enumerated
    happily and then raised EACCES on the first sort key. But a SINGLE entry vanishing under the
    stat (ENOENT/ENOTDIR: a concurrent prune retired it, snapshot-status lists locklessly) is not
    store-level unreadability: that entry is skipped, never escalated to "store unreadable".
    """
    keyed: list[tuple[str, float, str, Path]] = []
    try:
        if not store.is_dir():
            return []
        for path in store.iterdir():
            if not _SNAPSHOT_DIR_PATTERN.fullmatch(path.name):
                continue
            manifest = _snapshot_dir_manifest(path)
            if manifest is None:
                continue
            try:
                mtime = path.stat().st_mtime
            except (FileNotFoundError, NotADirectoryError):
                # A concurrent _retire_store_snapshot_dir rename landed between the manifest
                # read and the stat. A retired entry is not a store fault -- any correct
                # listing would have excluded it -- so skip it, never escalate.
                continue
            # str(): a hand-corrupted manifest with a non-string materializedAt would otherwise
            # take out the whole sort with a TypeError -- another store read crashing the CLI.
            keyed.append((str(manifest.get("materializedAt", "")), mtime, path.name, path))
    except OSError as exc:
        warn_snapshot_store_unreadable("cannot list snapshots", exc)
        return []
    keyed.sort(key=lambda item: item[:3])
    return [item[3] for item in keyed]


def materialize_methodology_snapshot(
    repo: Path, commit: str, channel: str
) -> tuple[Path | None, str]:
    """Export <commit> of <repo> into an immutable store directory. Atomic publish, idempotent.

    Returns (snapshot_dir, detail) or (None, why). NEVER raises: a broken/unwritable store must
    degrade to "keep running the code we already have", never fail an operator's session start.
    """
    store = methodology_snapshot_store_root()
    # --verify ... ^{commit}, not a bare rev-parse: a bare `rev-parse <40-hex>` happily echoes back
    # a sha that names no object in this repo, and we would go on to name a store directory after a
    # commit that does not exist and only discover it when `git archive` failed.
    full_sha = run_git(repo, ["rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"])
    if full_sha in ("", "unavailable") or not re.fullmatch(r"[0-9a-f]{40}", full_sha):
        return None, f"could not resolve {commit} in {repo}"
    dest = store / full_sha[:12]
    staging = store / ".tmp" / f"mat-{full_sha[:12]}-{os.getpid()}"
    tar_path = store / ".tmp" / f"mat-{full_sha[:12]}-{os.getpid()}.tar"
    try:
        (store / ".tmp").mkdir(parents=True, exist_ok=True)
        lock_path = store / ".store-lock"
        with lock_path.open("a", encoding="utf-8") as lock_file, advisory_flock(lock_file):
            existing = _snapshot_dir_manifest(dest)
            if existing and existing.get("commit") == full_sha:
                if _snapshot_is_executable(dest):
                    return dest, f"reused existing snapshot {full_sha[:12]}"
                # The manifest matches but the tree cannot be run. Reusing it would hand the caller
                # back the very trap it asked us to repair -- heal would swap `current` onto a
                # snapshot with no CLI and report success. Retire it and publish a whole one.
                if not _retire_store_snapshot_dir(dest):
                    return None, (
                        f"snapshot {full_sha[:12]} is missing bin/{CLI_NAME} and could not be "
                        "replaced"
                    )
            if staging.exists():
                # A crash between the read-only pass and the publish rename leaves a 0555 tree
                # under this exact name (same sha, and pids recycle). Plain rmtree cannot remove
                # it, so materialization would be wedged for as long as the leak survives.
                _rmtree_force(staging)
            staging.mkdir(parents=True)
            # The unlink has to cover the ARCHIVE too, not just the extraction: `git archive -o`
            # creates its output file before it writes, so a failure partway (disk-full is the
            # realistic one) leaves a partial tar behind. prune never walks .tmp -- it only visits
            # manifest-bearing snapshot dirs, pins and history -- so a tar orphaned here is orphaned
            # permanently, and the disk-full case would leak another one on every retry.
            try:
                code, _stdout, stderr = run_command(
                    [
                        "git", "-C", str(repo), "archive", "--format=tar",
                        "-o", str(tar_path), full_sha,
                    ]
                )
                if code != 0:
                    _rmtree_force(staging)
                    return None, f"git archive failed: {stderr or 'unknown error'}"
                try:
                    _safe_extract_methodology_tar(tar_path, staging)
                except (OSError, tarfile.TarError) as exc:
                    _rmtree_force(staging)
                    return None, f"snapshot extraction failed: {exc}"
            finally:
                tar_path.unlink(missing_ok=True)
            if not (staging / "bin" / CLI_NAME).is_file() or not (staging / "VERSION").is_file():
                _rmtree_force(staging)
                return None, (
                    f"exported tree is missing bin/{CLI_NAME} or VERSION; refusing to publish"
                )
            (staging / "bin" / CLI_NAME).chmod(0o755)
            manifest = {
                "schema": SNAPSHOT_MANIFEST_SCHEMA,
                "commit": full_sha,
                "shortCommit": full_sha[:12],
                "version": (staging / "VERSION").read_text(encoding="utf-8").strip(),
                "channel": channel,
                "materializedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "canonicalRepo": str(repo.resolve()),
                "materializedBy": {"pid": os.getpid(), "pluginVersion": methodology_version()},
            }
            util_module().write_text_atomic(
                staging / SNAPSHOT_MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n"
            )
            _make_snapshot_read_only(staging)
            try:
                os.rename(staging, dest)
            except OSError as exc:
                # The staging tree is READ-ONLY by now -- _rmtree_force, never rmtree, or this
                # leaks a 0555 tree per attempt and no one ever finds out.
                _rmtree_force(staging)
                winner = _snapshot_dir_manifest(dest)
                if winner and winner.get("commit") == full_sha:
                    return dest, (
                        f"reused snapshot {full_sha[:12]} published by a concurrent process"
                    )
                return None, f"could not publish snapshot {full_sha[:12]}: {exc}"
            try:
                dest.chmod(0o555)  # the last write bit: the tree is in place, seal its root
            except OSError:
                pass
    except OSError as exc:
        _rmtree_force(staging)
        return None, f"snapshot store unavailable: {exc}"
    append_methodology_write_journal(
        "snapshot.materialize", full_sha, full_sha, "ok", detail=str(dest)
    )
    return dest, f"materialized {full_sha[:12]}"


def swap_methodology_snapshot_current(snapshot_dir: Path) -> tuple[bool, str]:
    """Point <store>/current at a snapshot atomically (symlink + os.replace).

    os.replace on a symlink swaps the LINK, never its target, so no lane ever observes a missing
    or half-written `current`: it sees the old snapshot, then the new one.
    """
    store = snapshot_dir.parent
    tmp_link = store / f".current-tmp-{os.getpid()}"
    try:
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        os.symlink(snapshot_dir.name, tmp_link)  # relative: the store stays relocatable
        os.replace(tmp_link, store / "current")
    except OSError as exc:
        try:
            tmp_link.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"could not swap current symlink: {exc}"
    # The swap history is what protects a snapshot that is no longer current but is still being
    # executed by a session that adopted it while it was (see prune's TTL window).
    history_path = store / "history.jsonl"
    try:
        with history_path.open("a", encoding="utf-8") as handle, advisory_flock(handle):
            handle.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "snapshot": snapshot_dir.name,
                    }
                )
                + "\n"
            )
    except OSError:
        pass
    append_methodology_write_journal("snapshot.swap-current", "", snapshot_dir.name, "ok")
    return True, f"current -> {snapshot_dir.name}"


def methodology_snapshot_pin_path(lane_path: Path) -> Path:
    return methodology_snapshot_store_root() / "pins" / f"{instrumentation_lane_id(lane_path)}.pin"


def write_methodology_snapshot_pin(lane_path: Path, snapshot_dir: Path) -> Path:
    """Declare "this lane is executing this snapshot; do not delete it".

    The pin's MTIME is its heartbeat -- prune ages pins out past the TTL, so a lane that dies
    without cleaning up cannot protect a snapshot forever.
    """
    pin_path = methodology_snapshot_pin_path(lane_path)
    pin_path.parent.mkdir(parents=True, exist_ok=True)
    util_module().write_text_atomic(
        pin_path,
        json.dumps(
            {
                "schema": SNAPSHOT_PIN_SCHEMA,
                "snapshot": snapshot_dir.name,
                "lanePath": str(lane_path),
                "pid": os.getpid(),
                "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
    )
    return pin_path


def snapshot_pin_ttl_seconds() -> int:
    raw = util_module().resolve_env(SNAPSHOT_PIN_TTL_HOURS_ENV)
    hours = int(raw) if raw.isdigit() else SNAPSHOT_DEFAULT_PIN_TTL_HOURS
    return hours * 3600


def prune_methodology_snapshots(keep: int | None = None) -> list[str]:
    """Delete superseded snapshots. Returns the names actually removed.

    A snapshot is protected when ANY of these hold, because each means something may still be
    executing it: it is among the newest `keep`; it is the current target; a lane holds a pin on it
    younger than the TTL; or it was current within the TTL window (a session that adopted it is
    bounded by the same TTL). Everything else is garbage.
    """
    store = methodology_snapshot_store_root()
    if keep is None:
        raw_keep = util_module().resolve_env(SNAPSHOT_KEEP_ENV)
        keep = int(raw_keep) if raw_keep.isdigit() else SNAPSHOT_DEFAULT_KEEP
    ttl_seconds = snapshot_pin_ttl_seconds()
    pruned: list[str] = []
    lock_path = store / ".store-lock"
    try:
        # Inside the guard: is_dir() stats the store, and on an unreadable one that raises rather
        # than answering False. Prune is called from the heal/advance paths, so an escape here
        # fails a launch just as surely as one out of methodology_snapshot_current_dir().
        if not store.is_dir():
            return []
        with lock_path.open("a", encoding="utf-8") as lock_file, advisory_flock(lock_file):
            snaps = _store_snapshot_dirs(store)
            protected = {path.name for path in snaps[-keep:]} if keep > 0 else set()
            current = store / "current"
            if current.is_symlink():
                protected.add(current.resolve(strict=False).name)
            pins_dir = store / "pins"
            now = time.time()
            if pins_dir.is_dir():
                for pin in pins_dir.glob("*.pin"):
                    try:
                        if now - pin.stat().st_mtime > ttl_seconds:
                            pin.unlink()
                            continue
                        pin_data = json.loads(pin.read_text(encoding="utf-8"))
                        protected.add(str(pin_data.get("snapshot", "")))
                    except (OSError, json.JSONDecodeError):
                        continue
            history = store / "history.jsonl"
            if history.is_file():
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
                try:
                    lines = history.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                for line in lines:
                    try:
                        entry = json.loads(line)
                        when = datetime.strptime(entry["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=timezone.utc
                        )
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue
                    if when >= cutoff:
                        protected.add(str(entry.get("snapshot", "")))
            (store / ".tmp").mkdir(exist_ok=True)
            for snap in snaps:
                if snap.name in protected:
                    continue
                if _retire_store_snapshot_dir(snap):
                    pruned.append(snap.name)
    except OSError as exc:
        warn_snapshot_store_unreadable("prune incomplete", exc)
        return pruned
    if pruned:
        append_methodology_write_journal("snapshot.prune", "", "", "ok", detail=",".join(pruned))
    return pruned


def methodology_snapshot_current_dir() -> Path | None:
    """The snapshot <store>/current points at, or None when absent/dangling/not a snapshot.

    An UNREADABLE store answers None too, loudly. `is_symlink()` stats the path, and a store
    directory that cannot be opened at all (chmod, ACL, dead mount) makes that stat fail with
    EACCES -- which pathlib propagates on some interpreter/platform combinations and swallows on
    others. Every caller here treats None as "no usable snapshot, run the canonical checkout", so
    letting the error escape on the platforms that raise turned the store's one safety promise
    inside out: instead of degrading, an unreadable store BLOCKED the launch.
    """
    current = methodology_snapshot_store_root() / "current"
    try:
        if not current.is_symlink():
            return None
        resolved = current.resolve(strict=False)
    except OSError as exc:
        warn_snapshot_store_unreadable("no usable current, using canonical checkout", exc)
        return None
    return resolved if _snapshot_dir_manifest(resolved) else None


def _published_store_snapshot(candidate: Path) -> Path | None:
    """`candidate` as a snapshot PUBLISHED IN THIS STORE, or None.

    A pin records a snapshot by NAME and prune protects store entries by name, so a pin is only
    protection when the name it carries is one this store can actually collect. A path that is not
    a manifest-bearing <sha12> directory directly under the store root -- a pruned exec root, a
    checkout, a foreign or stale export -- must therefore never reach a pin: it would write a pin
    that guards nothing, which is strictly worse than falling back to `current`.
    """
    store = methodology_snapshot_store_root()
    try:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.parent != store.resolve(strict=False):
            return None
        if not _SNAPSHOT_DIR_PATTERN.fullmatch(resolved.name):
            return None
    except OSError as exc:
        warn_snapshot_store_unreadable("cannot resolve the session exec root", exc)
        return None
    return resolved if _snapshot_dir_manifest(resolved) else None


def session_snapshot_exec_root() -> Path | None:
    """The snapshot THIS SESSION is executing, or None when it is not executing one.

    NOT `current`. Session-stickiness is the store's whole point: a session resolves one exec root
    (the launcher does it with `pwd -P` and exports it; the shim re-execs into it) and runs that
    tree for its entire life, precisely so another lane's swap cannot hop it between versions
    mid-flight. `current` is the opposite of that -- a symlink any lane may move at any instant.

    Two sources, in the order they are authoritative:

    1. The running tree itself. When this process IS a snapshot, its own manifest is not an
       assertion about the session, it is the session: no env, no symlink, nothing to race.
    2. The exported exec root. This covers the one case (1) cannot see: an operator-preset
       MINERVIT_METHODOLOGY_CLI keeps the launcher's own CLI on the canonical checkout while every
       hook in the session still execs the exported snapshot -- so the session runs a snapshot that
       this process is not.

    Both are validated against the store, so a stale or pruned root degrades to `current` rather
    than writing a pin that protects nothing.
    """
    if running_from_snapshot():
        own = _published_store_snapshot(REPO_ROOT)
        if own is not None:
            return own
    # Read exactly as the shim and the launcher read it -- the MINERVIT_ spelling, no alias. This
    # is not an operator setting but the session's own inherited exec state, and resolve_env would
    # let a stale TAUTLINE_-spelled shell variable outrank it: Python would then pin one snapshot
    # while the shell half of the same session execs another, which is the very split this
    # function exists to close. tests/test_env_reads_use_resolver.py holds the exemption.
    exported = os.environ.get(METHODOLOGY_EXEC_ROOT_ENV, "").strip()
    if exported:
        return _published_store_snapshot(Path(exported))
    return None


def snapshot_pin_target() -> Path | None:
    """The snapshot a pin for THIS session must name.

    The session's own exec root when it has one, and only then `current`. Pinning `current`
    unconditionally is a race against the very stickiness the store provides: the launcher resolves
    the exec root and calls `snapshot-pin` a few lines later, and any lane that swaps `current` in
    that window makes this lane declare a snapshot it is not running -- leaving prune free to
    collect the one it IS running, which is the single deletion the pin exists to prevent.

    `current` remains the fallback, not the rule: a pre-cutover launcher, a bare `tautline
    snapshot-pin` on a machine whose store is only just enabled, and any session executing the
    canonical checkout all legitimately have no exec root, and the snapshot they would adopt on
    their next launch is exactly `current`.
    """
    return session_snapshot_exec_root() or methodology_snapshot_current_dir()


def heal_methodology_snapshot_current(channel: str = "stable") -> None:
    """Make `<store>/current` name the canonical HEAD: rebuild it when missing or dangling, and
    republish it when it is STALE.

    Without this the store would only ever gain a `current` on a trust-gated ADVANCE, which may be
    days away: a freshly-enabled store (or one whose current target was deleted) would leave every
    session falling back to the canonical checkout while the store sat there empty. Best-effort by
    construction -- the store is an optimization, never a dependency, so a failure prints and the
    sync carries on.

    Staleness is reconciled here because this is the ONLY publisher that runs when no advance
    fires, and every way the store gets left behind ends in exactly that state: a publish that
    failed mid-advance, an operator taking the rollback lever in one shell (that lane fast-forwards
    the canonical checkout and, executing the canonical tree, publishes nothing), or a manual git
    advance. In all three the checkout moves and `current` does not -- and because the next lane's
    sync then finds the checkout already up to date, no advance fires and _reexec_updated_methodology
    (the only other publisher) is never re-entered. Returning early on a `current` that merely
    EXISTS therefore froze the store one head behind for good, and every session on the machine kept
    executing the stale snapshot while sync reported ok.

    Trust is NOT re-litigated here: the canonical checkout only reaches a new head through the
    trust-gated advance path (or the operator's own hands), so its HEAD is already the machine's
    decision about what to run. This mirrors what heal has always done for a missing `current`.
    """
    if not methodology_snapshot_store_enabled():
        return
    canonical = canonical_methodology_repo()
    head = run_git(canonical, ["rev-parse", "HEAD"])
    if head == "unavailable":
        print(f"methodology_snapshot: heal skipped - HEAD unavailable in {canonical}")
        return
    current = methodology_snapshot_current_dir()
    at_head = current is not None and (
        (_snapshot_dir_manifest(current) or {}).get("commit") == head
    )
    # Healthy means RUNNABLE, not merely manifest-consistent. A `current` whose manifest names the
    # canonical head while its bin/tautline has been deleted passes every commit comparison in this
    # file and fails the only test that decides anything: the `-x` the shim and the launcher apply
    # before they exec it. Judged healthy, it is never repaired -- so every session on the machine
    # silently falls back to the canonical checkout, forever, while sync reports ok.
    if at_head and _snapshot_is_executable(current):
        return  # already the canonical head, and runnable: no republish, no swap, no prune churn
    # A `current` that is present but stale (or present but gutted) is republished, not left alone.
    # Distinguish that from an empty store in the report: "healed" is a store that had nothing to
    # run, "republished" is one that was quietly serving a head nobody can execute.
    action = "republished current" if current is not None else "healed current"
    snapshot_dir, snap_detail = materialize_methodology_snapshot(canonical, head, channel)
    if snapshot_dir is None:
        print(f"methodology_snapshot: failed - {snap_detail}")
        return
    swapped, swap_detail = swap_methodology_snapshot_current(snapshot_dir)
    if not swapped:
        # Report what actually happened. This function IS the recovery mechanism for a store whose
        # `current` is missing, dangling or stale, so announcing success over a failed swap would
        # leave the operator's only signal that the store is still broken reading as a repair -- a
        # silent failure in the very machinery that exists to make store failures loud.
        print(f"methodology_snapshot: heal failed - {snap_detail}; {swap_detail}")
        return
    print(f"methodology_snapshot: {action} - {snap_detail}; {swap_detail}")
    prune_methodology_snapshots()


# --- Launcher sync gate -------------------------------------------------------------------
# Every lane start runs sync-methodology. Ungated, N lanes launching together all fetch, all
# advance the one canonical checkout, and all race to publish the same snapshot into the same
# store. The gate makes the first lane do the work and the rest observe its result: a flock
# serializes them, and a freshness stamp lets the ones that wake up behind it skip a sync that
# demonstrably just happened.
METHODOLOGY_SYNC_FRESHNESS_ENV = "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES"
# Exec-handoff pair, read with os.environ.get and NEVER through resolve_env: a TAUTLINE_ alias for
# either would let a stale shell variable outrank what this process exported into its own
# environment microseconds earlier -- and for the lock fd, "outrank" means flocking a foreign file
# descriptor number. tests/test_env_reads_use_resolver.py holds the exemption and the prohibition.
METHODOLOGY_SYNC_LOCK_FD_ENV = "MINERVIT_METHODOLOGY_SYNC_LOCK_FD"
METHODOLOGY_SYNC_GATE_ENV = "MINERVIT_METHODOLOGY_SYNC_GATE"


def methodology_sync_lock_path() -> Path:
    return methodology_state_dir() / "methodology-sync.lock"


def methodology_sync_stamp_path() -> Path:
    return methodology_state_dir() / "methodology-sync.stamp"


def methodology_sync_freshness_seconds() -> int:
    """The window in which another lane's sync counts as this lane's sync. 0 disables the skip."""
    raw = util_module().resolve_env(METHODOLOGY_SYNC_FRESHNESS_ENV).strip()
    minutes = int(raw) if raw.isdigit() else METHODOLOGY_SYNC_DEFAULT_FRESHNESS_MINUTES
    return max(minutes, 0) * 60


def write_methodology_sync_stamp(head: str, snapshot: str, status: str) -> None:
    """Record that the methodology is synced as of NOW, to this head and this snapshot.

    Best-effort by construction: the stamp is an optimization, never a correctness input. A lane
    that cannot write it costs the next lane one redundant fetch, which is the pre-gate behavior.
    """
    try:
        path = methodology_sync_stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)  # fresh HOME: the state dir may not exist
        util_module().write_text_atomic(
            path,
            json.dumps(
                {
                    "schema": METHODOLOGY_SYNC_STAMP_SCHEMA,
                    "syncedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "head": head,
                    "snapshot": snapshot,
                    "status": status,
                    "pid": os.getpid(),
                },
                indent=2,
            )
            + "\n",
        )
    except OSError:
        pass


def read_methodology_sync_stamp() -> tuple[dict, float] | None:
    """The stamp plus its age in seconds, or None when absent, unreadable, or foreign.

    Age comes from the file's mtime, not from `syncedAt`: write_text_atomic renames a fresh temp
    file into place, so the mtime IS the write instant, and it cannot be faked by a stale clock in
    the JSON the way a hand-edited timestamp could.
    """
    path = methodology_sync_stamp_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - path.stat().st_mtime
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != METHODOLOGY_SYNC_STAMP_SCHEMA:
        return None
    return data, max(age, 0.0)


def launcher_gate_skip_reason() -> str | None:
    """Why this gated sync may trust a sibling lane's recent sync, or None to do the work.

    Every condition below is a bug that was worth a test:
      * a re-exec token VETOES the skip. A post-advance process arrives holding a stamp its own
        predecessor wrote seconds ago, and its entire purpose is the post-sync body the predecessor
        could not run (token consumption, release guards, heal, pin refresh, version reporting).
        Skipping there would silently drop all of it;
      * a fresh stamp over a store whose `current` is missing, dangling, or gutted must NOT skip,
        or the heal that would rebuild it is starved for a whole freshness window and every session
        launched in that window quietly falls back to the canonical checkout;
      * the stamp must name the snapshot `current` actually points at -- otherwise it describes a
        store state that no longer exists;
      * a stamp whose recorded head is NOT the snapshot it names records a sync whose publish
        FAILED (the checkout advanced, the store was left behind). Honoring it would starve the
        heal republish retry for a whole freshness window, and every launch inside that window
        would quietly pin outdated code;
      * an installed package VETOES the skip. Its gated sync stands down and prints the
        pipx/pip update hint -- that hint IS the work -- and the only stamp such a machine can
        hold was inherited from its checkout era, describing a runtime this wheel never
        executes.
    """
    window = methodology_sync_freshness_seconds()
    if window <= 0:
        return None
    if os.environ.get(METHODOLOGY_REEXEC_TOKEN_ENV):
        return None
    if running_from_installed_package():
        return None
    stamp = read_methodology_sync_stamp()
    if stamp is None:
        return None
    data, age = stamp
    if age >= window or str(data.get("status", "")) == "failed":
        return None
    if methodology_snapshot_store_enabled():
        current = methodology_snapshot_current_dir()
        if current is None:
            return None
        if str(data.get("snapshot", "")) != current.name:
            return None
        # The same runnability predicate heal now judges health by. Declining to skip is only half
        # the remedy: it exists to HAND a gutted `current` to heal, which must then rebuild it.
        if not _snapshot_is_executable(current):
            return None
        # Materialize names snapshot dirs <full_sha[:12]>, so name-vs-head compares commits. A
        # head run_git could not resolve never matches a sha12 name and fails open toward syncing.
        if str(data.get("head", ""))[:12] != current.name:
            return None
    return f"synced {int(age)}s ago by another lane"


@contextmanager
def launcher_sync_gate():
    """Hold one lock across the WHOLE gated body -- including across os.execve.

    CPython opens descriptors close-on-exec, so a gate that flocked a plain file handle would
    silently RELEASE its lock at the exact moment a trust-gated advance re-execs: the successor
    would do its checkout surgery with the gate wide open and a lane launching right then would
    walk straight in. os.set_inheritable keeps the open file description -- and therefore the flock
    on it -- alive across the exec, and the fd NUMBER travels in the environment so the successor
    ADOPTS that same lock. It must not reopen: the inherited fd still holds the lock, so a second
    open + flock would deadlock the successor against itself, forever.
    """
    lock_file = None
    inherited = os.environ.get(METHODOLOGY_SYNC_LOCK_FD_ENV, "").strip()
    if inherited.isdigit():
        lock_file = _adopt_launcher_gate_lock(int(inherited))
    if lock_file is None:
        path = methodology_sync_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)  # fresh HOME: the state dir may not exist
        lock_file = path.open("a", encoding="utf-8")
    os.set_inheritable(lock_file.fileno(), True)
    os.environ[METHODOLOGY_SYNC_LOCK_FD_ENV] = str(lock_file.fileno())
    os.environ[METHODOLOGY_SYNC_GATE_ENV] = "1"
    try:
        with advisory_flock(lock_file):
            yield
    finally:
        # Not reached on the re-exec path: os.execve replaces this process mid-body and the lock
        # deliberately rides the inherited fd into the successor, which closes the gate for us.
        os.environ.pop(METHODOLOGY_SYNC_LOCK_FD_ENV, None)
        os.environ.pop(METHODOLOGY_SYNC_GATE_ENV, None)
        try:
            lock_file.close()
        except OSError:
            pass


def _adopt_launcher_gate_lock(fd: int):
    """Wrap the inherited gate fd, or None when that number is not our lock file.

    The number alone proves nothing -- a foreign environment (or a stale export) could name a
    descriptor this process opened for something else entirely, and flocking THAT would lock a file
    nobody meant to lock. os.fstat identifies what actually sits on the number, and the (dev, ino)
    comparison confirms it is the very lock file we would otherwise have opened.
    """
    try:
        fd_stat = os.fstat(fd)
        lock_stat = methodology_sync_lock_path().stat()
    except OSError:
        return None
    if (fd_stat.st_dev, fd_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        return None
    try:
        return os.fdopen(fd, "a", encoding="utf-8")
    except OSError:
        return None


def refresh_methodology_snapshot_pin(lane: Path) -> None:
    """Re-stamp an EXISTING pin for this lane. Never creates one.

    Pins are created by the launcher's `snapshot-pin`; this keeps a long-lived lane that relaunches
    from having its pin aged out by prune's TTL while it is still executing the snapshot. Creating
    one here instead would let any incidental gated sync (a hook, a status check) claim a pin for a
    directory that is not really a lane, and pin-protected snapshots would never be collectable.

    Re-stamps snapshot_pin_target(), not `current`, for the same reason `snapshot-pin` does -- and
    it matters MORE here. This is the heartbeat that keeps a session's pin alive past the TTL, so a
    version that re-stamped `current` would, on the first sync after another lane advanced the
    store, quietly move the lane's only protection off the snapshot it is executing and onto one it
    is not. That is worse than never refreshing: the free protection a once-current snapshot enjoys
    inside the TTL window then expires with nothing behind it, and prune deletes the running tree.
    """
    if not methodology_snapshot_store_enabled():
        return
    target = snapshot_pin_target()
    if target is None:
        return
    try:
        if not methodology_snapshot_pin_path(lane).is_file():
            return
        write_methodology_snapshot_pin(lane, target)
    except OSError as exc:
        warn_snapshot_store_unreadable("cannot refresh pin", exc)


def _reexec_updated_methodology(old_head: str, new_head: str, detail: str, channel: str) -> str:
    """Journal the advance, publish it as a snapshot, and re-exec the NEW code. Trust is already
    verified by the caller -- every call site sits behind verify_upstream_trust(new_head).

    Returns ONLY on exec failure, with the detail the caller should report as `failed`.

    `old_head` is the CANONICAL checkout's pre-advance head, supplied by the caller -- never the
    running snapshot's commit, which may be many advances behind and would make the journal lie
    about what this run actually mutated.
    """
    canonical = canonical_methodology_repo()
    # Journal BEFORE the exec: os.execve replaces this process, so nothing after it ever runs.
    # (The rescue/repair helpers separately journal their own git surgery; this entry records the
    # ADOPTION -- which head this lane is about to start executing.)
    append_methodology_write_journal(
        "sync-methodology.advance", old_head, new_head, "ok", detail=detail
    )
    own_root = REPO_ROOT
    exec_root = own_root
    if methodology_snapshot_store_enabled():
        adopted: Path | None = None
        snapshot_dir, snap_detail = materialize_methodology_snapshot(canonical, new_head, channel)
        if snapshot_dir is None:
            print(f"methodology_snapshot: failed - {snap_detail}", flush=True)
        else:
            swapped, swap_detail = swap_methodology_snapshot_current(snapshot_dir)
            print(f"methodology_snapshot: {snap_detail}; {swap_detail}", flush=True)
            if swapped:
                adopted = snapshot_dir
        if adopted is not None:
            exec_root = adopted
            prune_methodology_snapshots()
        elif running_from_snapshot():
            # We are executing a snapshot of the OLD head and the store could not publish the new
            # one. Re-execing ourselves would hand this tree a token bound to new_head while its
            # manifest still says old_head -- consume_methodology_reexec_token() would reject it and
            # the launch would die with "invalid or expired". The canonical checkout is at new_head,
            # clean, and trust-verified: exec that instead and keep the session alive.
            exec_root = canonical
            print(
                f"methodology_snapshot: falling back to canonical checkout {canonical} "
                "for this session",
                flush=True,
            )
    elif running_from_snapshot():
        # Snapshot mode is OFF (the rollback lever, or the store key removed) while THIS process is
        # itself executing a snapshot -- an operator pulling the lever mid-session, or a direct call
        # to <store>/current/bin/tautline. Re-execing own_root walks into the same stale-token trap
        # as above: our manifest says old_head and the token is bound to new_head. Take the same
        # exit, which is also what the lever asks for -- execute the canonical checkout.
        exec_root = canonical
        print(
            f"methodology_snapshot: snapshot execution disabled; executing canonical checkout "
            f"{canonical} for this session",
            flush=True,
        )
    if os.environ.get(METHODOLOGY_SYNC_GATE_ENV) == "1":
        # Inside a launcher gate, os.execve is the ONLY exit from the gated body -- nothing after
        # it runs. Stamp here or the gate window re-execs stampless, and every sibling lane queued
        # on the flock repeats the fetch this run just finished. The snapshot recorded is whatever
        # `current` resolves to now: the one just swapped in on the happy path, the unchanged
        # previous one when the store could not publish (a truthful stamp the next lane can match).
        current = methodology_snapshot_current_dir()
        write_methodology_sync_stamp(new_head, current.name if current else "", "ok")
    # The exec target is the bin/tautline SHIM beside the chosen root (own_root == REPO_ROOT on the
    # unchanged path, else the adopted snapshot / canonical checkout). Post package-split the engine
    # lives in the package, so re-exec must always go through the shim, never this module.
    exec_cli = exec_root / "bin" / CLI_NAME
    print(f"methodology_update: updated - {detail}; re-running current command", flush=True)
    env = os.environ.copy()
    env[METHODOLOGY_REEXEC_TOKEN_ENV] = create_methodology_reexec_token(new_head)
    if exec_root != own_root:
        env[METHODOLOGY_EXEC_ROOT_ENV] = str(exec_root)
    try:
        os.execve(sys.executable, [sys.executable, str(exec_cli), *sys.argv[1:]], env)
    except OSError as exc:
        return f"{detail}; could not re-run after update: {exc}"
    raise AssertionError("unreachable after execve")  # pragma: no cover


def _held_candidate_take_it_offer(canonical: Path, candidate_sha: str, channel: str) -> str | None:
    """The resolved take-it remedy for a trust-`held` candidate, or None to keep the generic one.

    The generic gate remedy names no version and leaves `<stable|experimental>` for the operator to
    guess -- the lockout reported in the FR-2 RCA, where following it in a loop never took the
    update. This resolves both from the candidate actually being held, reusing the same offer copy
    the skip-path surfaces already print (`_framework_update_version_offer`).

    Two deliberate limits:

    - Only a `pinned` hold is rewritten. A `signed` hold's remedy is signature repair, which
      repinning cannot fix, so its own remedy is left exactly as the gate wrote it.
    - The HELD CANDIDATE is authoritative. Its version is read from the fetched commit itself, never
      from the display probe (which resolves independently and may name a different sha), so the
      remedy either names the real held version or names none at all -- never a wrong one.

    Display-only: nothing here feeds framework_update_decision or the trust gate.
    """
    if methodology_update_policy() != "pinned":
        return None
    version = _update_probe_version_at(canonical, candidate_sha)
    if version is None:
        # Sha-only degrade: VERSION is unreadable at the candidate (shallow object, malformed file).
        # Name the commit rather than borrow a version that may belong to a different candidate.
        version = f"the upstream release at {candidate_sha[:12]}"
    offer = _framework_update_version_offer(
        {}, {"availableSha": candidate_sha}, {"channel": channel}, version
    )
    return offer.removeprefix("framework_update_offer: ")


def _resolve_held_refusal(refusal: str, canonical: Path, candidate_sha: str, channel: str) -> str:
    """Swap the trust gate's generic pin remedy for the resolved take-it offer, leaving exactly one.

    Fail-safe both ways: no resolved offer (a signed hold), or a refusal that does not carry the
    generic remedy, returns the gate's own text untouched.
    """
    offer = _held_candidate_take_it_offer(canonical, candidate_sha, channel)
    if offer is None:
        return refusal
    generic = _generic_pinned_advance_remedy()
    if generic not in refusal:
        return refusal
    return refusal.replace(generic, f"take it -- {offer}")


def update_methodology_repo(
    skip_update: bool,
    allow_non_main: bool = False,
    auto_rescue_local_changes: bool = False,
    auto_rescue_stale_only: bool = False,
    channel: str = "stable",
) -> tuple[str, str]:
    """Sync the canonical checkout to its trusted release upstream.

    Journaling note: entries are appended by the code paths that actually WRITE to the canonical
    repo (the fast-forward below, the rescue/repair helpers, the release guards, update-repin) --
    never by the read-only refusals. The journal must stay a pure observer of mutations: it lives
    under $HOME, and an unconditional write here would leave a file behind on paths that touched
    nothing, which is both misleading forensics and a real side effect (it dirties any checkout
    that happens to contain $HOME, sending the very next sync down the local-changes rescue path).
    """
    if running_from_installed_package():
        # Package standdown (PP-R1-P1-1), evaluated BEFORE canonical-repo resolution so a
        # still-configured valid checkout can never reintroduce checkout mutation: pip updates
        # the RUNNING code; fetching/ff-merging a leftover checkout would change nothing this
        # wheel executes and would violate the auto-update non-goal. Read-only refusal: the
        # journal stays silent (see the docstring rule above). NOTE this "skipped" status is
        # deliberately non-failed, so it is NOT what keeps the sync tail from healing/stamping:
        # the store half of the standdown lives in methodology_snapshot_store_enabled() and the
        # freshness-stamp half in sync_methodology's gated tail.
        return "skipped", (
            "this Tautline runs from an installed package; checkout sync stands down - "
            f"update with {PACKAGE_INSTALL_UPDATE_HINT}"
        )
    canonical = canonical_methodology_repo()
    if skip_update:
        return "skipped", "--skip-update requested"
    reexec_token = consume_methodology_reexec_token()
    if reexec_token is True:
        return "skipped", "already updated in this lane-start process"
    if reexec_token is False:
        return "failed", f"invalid or expired {METHODOLOGY_REEXEC_TOKEN_ENV}; refusing to guess whether methodology sync already ran"
    if maintainer_mode_armed():
        # Maintainer standdown, placed AFTER --skip-update and the re-exec token (their contracts
        # keep existing precedence) and BEFORE any branch check, fetch, rescue, or ff-merge. This
        # is the single choke point every caller funnels through -- launcher-gate sync, manual
        # sync, lane-target sync -- so returning here is what makes the mode total. The non-failed
        # status is load-bearing: heal_methodology_snapshot_current still republishes canonical
        # HEAD into <store>/current (committed maintainer work reaches the very next launch) and
        # the freshness stamp is still written. Read-only refusal: the journal stays silent (see
        # the docstring rule above).
        return "skipped", (
            "maintainer mode - update gates stand down; checkout left untouched "
            "(disable with `tautline maintainer-mode off`)"
        )
    if run_git(canonical, ["rev-parse", "--is-inside-work-tree"]) != "true":
        return "skipped", "methodology checkout is not a Git worktree"
    release_branch = framework_channel_branch(channel)
    branch = run_git(canonical, ["branch", "--show-current"])
    if branch not in (release_branch, "unavailable") and not allow_non_main and util_module().resolve_env("MINERVIT_METHODOLOGY_ALLOW_NON_MAIN") != "1":
        branch_display = branch or "detached HEAD"
        if auto_rescue_local_changes:
            # Capture the pre-rescue canonical head BEFORE the rescue mutates the checkout: the
            # journal must record what this run actually moved, and after the reset it is gone.
            pre_rescue_head = run_git(canonical, ["rev-parse", "HEAD"])
            if channel == "stable":
                rescued, detail, _rescue_branch = rescue_methodology_non_main_checkout(branch_display)
            else:
                rescued, detail, _rescue_branch = rescue_methodology_non_main_checkout(branch_display, channel)
            if not rescued:
                return "failed", detail
            # The rescue reset HEAD to freshly-fetched upstream; verify trust BEFORE re-exec'ing it,
            # exactly as the pull/repair paths below do. Without this the default auto-rescue path is
            # an ungated RCE (one compromised upstream = fleet-wide code execution on adopter startup).
            rescued_head = run_git(canonical, ["rev-parse", "HEAD"])
            allowed, trust_msg = verify_upstream_trust(rescued_head)
            if trust_msg:
                print(f"methodology_update_trust: {trust_msg}", file=sys.stderr, flush=True)
            if not allowed:
                return "failed", f"{detail}; refusing to re-exec rescued methodology {rescued_head[:12]}: {trust_msg}"
            return "failed", _reexec_updated_methodology(pre_rescue_head, rescued_head, detail, channel)
        return (
            "failed",
            f"methodology checkout is on {branch_display}, not {release_branch}; refusing to sync from a non-release branch. "
            # RCA 2026-07-22 control 1: this message used to name ONLY the allow-non-main env
            # var, and never named maintainer mode -- the supported control for an operator who
            # intentionally tracks a non-release branch. Two consecutive sessions read it and
            # built a launcher bypass instead, and the second one hand-rewrote the config env and
            # silently disarmed the standdown. A refusal that omits its own control teaches
            # bypasses; the supported fix goes FIRST.
            f"If you develop the framework and track {branch_display} on purpose, arm the "
            f"machine-wide standdown by setting {METHODOLOGY_MAINTAINER_MODE_ENV}=1 in "
            f"{resolve_user_config_env()}. "
            f"Otherwise switch the methodology checkout to {release_branch}, or set "
            "MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1 for a single intentional deviation.",
        )
    dirty = run_git(canonical, ["status", "--porcelain"])
    if dirty == "unavailable":
        return "skipped", "methodology checkout status unavailable"
    if dirty:
        remote_status = ""
        if auto_rescue_local_changes:
            if auto_rescue_stale_only:
                remote_status = remote_methodology_status(False)
                if remote_status == "up to date":
                    return "skipped", "methodology checkout has local changes but remote is up to date"
                if not remote_status.startswith("remote differs "):
                    return (
                        "failed",
                        "methodology checkout has local changes and "
                        f"{remote_status}; refusing to auto-rescue without confirmed newer remote methodology. "
                        f"Resolve local changes in {canonical}, then rerun `tautline sync-methodology`.",
                    )
            # Pre-rescue canonical head, captured before the rescue branch/reset moves it.
            pre_rescue_head = run_git(canonical, ["rev-parse", "HEAD"])
            rescued, detail, _rescue_branch = rescue_methodology_local_changes(methodology_release_upstream(channel))
            if not rescued:
                return "failed", detail
            # The rescue reset HEAD to freshly-fetched upstream; verify trust BEFORE re-exec'ing it,
            # exactly as the pull/repair paths below do. Without this the default auto-rescue path is
            # an ungated RCE (one compromised upstream = fleet-wide code execution on adopter startup).
            rescued_head = run_git(canonical, ["rev-parse", "HEAD"])
            allowed, trust_msg = verify_upstream_trust(rescued_head)
            if trust_msg:
                print(f"methodology_update_trust: {trust_msg}", file=sys.stderr, flush=True)
            if not allowed:
                return "failed", f"{detail}; refusing to re-exec rescued methodology {rescued_head[:12]}: {trust_msg}"
            return "failed", _reexec_updated_methodology(pre_rescue_head, rescued_head, detail, channel)
        if not remote_status:
            remote_status = remote_methodology_status(False)
        if remote_status == "up to date":
            return "skipped", "methodology checkout has local changes but remote is up to date"
        return (
            "failed",
            "methodology checkout has local changes and "
            f"{remote_status}; refusing to start with stale methodology. "
            f"Resolve local changes in {canonical}, then rerun `tautline sync-methodology`.",
        )

    old_head = run_git(canonical, ["rev-parse", "HEAD"])
    # Verify-before-advance (sec-trust-exec-1): fetch the release upstream WITHOUT moving the checkout,
    # verify the FETCHED commit against the trust policy, and only then fast-forward. A bare
    # `git pull --ff-only` advances the on-disk bin/minervit-methodology BEFORE verification, so a denied
    # upstream would still be executed by the next shim invocation. On a denied upstream we return failed
    # with the checkout untouched.
    upstream = methodology_release_upstream(channel)
    if upstream is not None:
        remote, upstream_branch, upstream_ref = upstream
        code, stdout, stderr = run_command(["git", "-C", str(canonical), "fetch", remote, upstream_branch])
        if code == 0:
            upstream_sha = run_git(canonical, ["rev-parse", upstream_ref])
            if upstream_sha == "unavailable":
                code, stdout, stderr = 1, "", f"could not resolve fetched upstream ref {upstream_ref}"
            else:
                if upstream_sha != old_head:
                    refusal = gate_methodology_upstream_advance(upstream_sha)
                    if refusal is not None:
                        # HELD, not failed: the checkout never advanced, so it still runs code the
                        # active trust policy accepts -- a safe launch state. Blocking startup here
                        # left operators dead in the water with no remedy (operator directive
                        # 2026-07-11: the remedy must always ship alongside the error). Held is
                        # only safe when the RETAINED head itself passes the trust policy (Codex
                        # 0.9.1 R1 P1): an empty/replaced allowlist or an unsigned local commit
                        # must stay fail-closed, not launch under a "trusted" label.
                        retained_allowed, _retained_msg = verify_upstream_trust(old_head)
                        if retained_allowed:
                            # The held detail is the ONLY place the resolved remedy is formatted:
                            # the candidate's sha, version, and channel are all in hand here, and
                            # the lane-start / sync-methodology emitters just print what they get.
                            resolved = _resolve_held_refusal(
                                refusal, canonical, upstream_sha, channel
                            )
                            return "held", (
                                f"update available but held by the trust policy; continuing on the "
                                f"trusted retained checkout {old_head[:12]}. {resolved}"
                            )
                        return "failed", (
                            f"update refused and the retained checkout {old_head[:12]} does not pass "
                            f"the active trust policy either; {refusal}"
                        )
                code, stdout, stderr = run_command(["git", "-C", str(canonical), "merge", "--ff-only", upstream_sha])
    else:
        # No resolvable release upstream (e.g. no origin remote): fall back to the tracking-
        # configured pull. The post-advance re-exec gate below still refuses to re-exec an
        # unverified HEAD.
        code, stdout, stderr = run_command(["git", "-C", str(canonical), "pull", "--ff-only"])
    if code != 0:
        if auto_rescue_local_changes:
            repaired, detail = repair_methodology_release_main_checkout(channel)
            if repaired:
                repaired_head = run_git(canonical, ["rev-parse", "HEAD"])
                allowed, trust_msg = verify_upstream_trust(repaired_head)
                if trust_msg:
                    print(f"methodology_update_trust: {trust_msg}", file=sys.stderr, flush=True)
                if not allowed:
                    return "failed", f"{detail}; refusing to re-exec repaired methodology {repaired_head[:12]}: {trust_msg}"
                # old_head predates the failed ff (which never moves HEAD), so it IS the pre-repair
                # canonical head the repair then reset away from.
                return "failed", _reexec_updated_methodology(old_head, repaired_head, detail, channel)
        return "failed", stderr or stdout or "git pull --ff-only failed"
    new_head = run_git(canonical, ["rev-parse", "HEAD"])
    if old_head != "unavailable" and new_head != "unavailable" and old_head != new_head:
        allowed, trust_msg = verify_upstream_trust(new_head)
        if trust_msg:
            print(f"methodology_update_trust: {trust_msg}", file=sys.stderr, flush=True)
        if not allowed:
            return "failed", f"refusing to re-exec updated methodology {new_head[:12]}: {trust_msg}"
        return "failed", _reexec_updated_methodology(
            old_head,
            new_head,
            f"fast-forwarded {old_head[:12]} -> {new_head[:12]}",
            channel,
        )
    return "ok", stdout or "already up to date"


def write_claude_autocompact_settings(settings_path: Path) -> tuple[Path, bool]:
    settings_path = settings_path.expanduser()
    settings = load_claude_settings(settings_path)
    settings.setdefault("env", {})
    changed = False
    for key, value in CLAUDE_AUTOCOMPACT_ENV_KEYS.items():
        if settings["env"].get(key) != value:
            settings["env"][key] = value
            changed = True
    if changed or not settings_path.exists():
        write_claude_settings(settings_path, settings)
    return settings_path, not changed


def remote_methodology_status(no_remote: bool) -> str:
    # "Is the checkout sync manages behind its remote?" -- a question about the CANONICAL repo.
    # Asked of a snapshot it would answer "not a Git checkout" forever, and the stale-only
    # auto-rescue gate keys on this string.
    if running_from_installed_package():
        # Package standdown (PP-R1-P1-1), evaluated BEFORE canonical resolution so no git
        # subprocess runs at all: pip is the only channel that updates the RUNNING code, so a
        # leftover configured checkout's remote answers a question about code this wheel never
        # executes -- and probing it puts network I/O in every read-only report (version,
        # methodology-status, lane-start, the sync tails). Unreachable from the stale-only
        # auto-rescue gate, which keys on the 'up to date'/'remote differs ' prefixes:
        # update_methodology_repo returns its own package standdown before that logic runs.
        return "skipped - installed package runtime; no methodology checkout to probe"
    canonical = canonical_methodology_repo()
    local = run_git(canonical, ["rev-parse", "HEAD"])
    upstream = run_git(canonical, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if local == "unavailable":
        return "unavailable: not a Git checkout"
    if upstream == "unavailable":
        return "unavailable: no upstream configured"
    cached = run_git(canonical, ["rev-parse", "@{u}"])
    if no_remote:
        return "matches cached upstream" if cached == local else f"differs from cached upstream {cached[:12]}"
    if "/" not in upstream:
        return f"unavailable: unsupported upstream {upstream}"
    remote, branch = upstream.split("/", 1)
    code, stdout, stderr = run_command(["git", "-C", str(canonical), "ls-remote", remote, f"refs/heads/{branch}"])
    if code != 0 or not stdout:
        return f"unavailable: {stderr or stdout or 'remote query failed'}"
    remote_sha = stdout.split()[0]
    return "up to date" if remote_sha == local else f"remote differs {remote_sha[:12]}"


def methodology_canonical_commit_line() -> str:
    """HEAD of the checkout sync manages -- which is NOT the code this process is running.

    `methodology_commit` answers "what am I running" (the snapshot), this answers "what will I run
    after the next launch swaps the snapshot in". They are the same sha on a dev checkout, and they
    differ for exactly as long as a lane keeps executing a snapshot that sync has already advanced
    past; without both lines that lag is invisible and reads as "sync did nothing".

    Because the lines are read by COMPARING them, both must abbreviate the same way: the same
    fixed 12-char prefix running_methodology_commit(short=True) uses, never git's `rev-parse
    --short` (whose length is repo-state-dependent -- 8 chars in this repo, 7 in a fresh clone).
    Mixing the two forms makes an in-sync lane report two different-looking shas and read as
    permanent snapshot lag. run_git's "unavailable" sentinel is 11 chars and survives the slice.
    """
    canonical_head = run_git(canonical_methodology_repo(), ["rev-parse", "HEAD"])
    return f"methodology_canonical_commit: {canonical_head[:12]}"


def methodology_exec_root_line() -> str:
    """Where the running code lives, and whether it is immutable.

    The short form comes from the reporter, never from a manifest key: snapshot_manifest() accepts
    any manifest carrying `schema` + `commit`, so reading a `shortCommit` field directly would raise
    on a manifest the reader legitimately accepted.
    """
    origin = (
        f"snapshot {running_methodology_commit(short=True)}"
        if running_from_snapshot()
        else "canonical checkout"
    )
    return f"methodology_exec_root: {REPO_ROOT} ({origin})"


def lane_status_module():
    from . import lane_status as module

    return module


def lane_status_config(data: dict) -> dict:
    cfg = dict(DEFAULT_LANE_STATUS)
    cfg.update(data.get("laneStatus") or {})
    latest = data.get("latestCode") or {}
    if not cfg.get("integrationBranch"):
        cfg["integrationBranch"] = latest.get("base", DEFAULT_LATEST_CODE["base"])
    # Fetch the SAME remote the comparison ref is built from.
    cfg["remote"] = latest.get("remote", DEFAULT_LATEST_CODE["remote"])
    # An adapter value arrives as `object`; a non-numeric one falls back to the default rather
    # than raising on the session-start path.
    try:
        configured_timeout = int(str(cfg["fetchTimeoutSeconds"]))
    except (TypeError, ValueError):
        configured_timeout = int(str(DEFAULT_LANE_STATUS["fetchTimeoutSeconds"]))
    cfg["fetchTimeoutSeconds"] = min(configured_timeout, LANE_STATUS_MAX_FETCH_TIMEOUT_SECONDS)
    return cfg


def lane_status_safe_detail(text: object, *, limit: int = 200) -> str:
    """The single sanitiser for every externally-controlled string this report prints or persists.

    Order matters: strip URL userinfo first (redact_secrets masks known token shapes and leaves
    `user:token@` alone), then the shape pass, then flatten control characters -- which would
    otherwise let a hostile remote forge report lines -- and only then truncate, so a cut can never
    bisect a token that was just masked.
    """
    redacted = redact_secrets(LANE_STATUS_URL_USERINFO_RE.sub(r"\1<redacted>@", str(text)))
    flattened = " ".join(
        "".join(char if char.isprintable() else " " for char in redacted).split()
    )
    return flattened[:limit]


OCCUPANCY_RECORD_MAX_BYTES = 64 * 1024
# How many peer records one lane-status pass will examine. Generous next to any real fleet, and
# finite so an unpruned directory cannot spend the hook's whole budget.
OCCUPANCY_PEER_SCAN_LIMIT = 64


def lane_status_git_probe(target: Path, args: list[str], *, deadline: float) -> tuple[int, str]:
    """Bounded git probe that PRESERVES the exit code.

    `run_git` collapses every failure to the literal "unavailable", which makes an expected negative
    (a ref that genuinely does not exist) indistinguishable from a probe that never completed.
    Callers that must tell those apart use this form. Returns 124 when the shared deadline is spent,
    matching run_command's timeout convention, and never probes past it.
    """
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        return 124, "unavailable"
    code, stdout, _stderr = run_command(["git", "-C", str(target), *args], timeout=remaining)
    return code, (stdout.strip() if code == 0 else "unavailable")


def lane_status_git(target: Path, args: list[str], *, deadline: float) -> str:
    return lane_status_git_probe(target, args, deadline=deadline)[1]


def lane_status_remote_is_usable(target: Path, remote: str, *, deadline: float) -> bool:
    """Exact membership in `git remote`, never a pattern.

    git parses a leading `--` value as an OPTION, so `--upload-pack=/tmp/helper` in a
    repository-controlled adapter would make `git fetch` execute an attacker-named binary on the
    session-start path. A pattern test cannot enumerate every option git might grow; membership can.
    """
    if not remote or remote.startswith("-"):
        return False
    if any(char.isspace() or not char.isprintable() for char in remote):
        return False
    code, listing = lane_status_git_probe(target, ["remote"], deadline=deadline)
    return code == 0 and remote in listing.splitlines()


def lane_status_ref_is_usable(target: Path, ref: str, *, deadline: float) -> bool:
    """The integration branch is the SECOND injection parameter on the same fetch line."""
    if not ref or ref.startswith("-"):
        return False
    if any(char.isspace() or not char.isprintable() for char in ref):
        return False
    # No `--` here: `check-ref-format --branch -- x` exits 129 (verified). The leading-dash and
    # printability checks above are what guard this call.
    code, _ = lane_status_git_probe(
        target, ["check-ref-format", "--branch", ref], deadline=deadline
    )
    return code == 0


LANE_STATUS_NONINTERACTIVE_ENV = {
    # A SessionStart fetch must NEVER prompt: expired credentials or an SSH passphrase would stall
    # the session behind a credential UI, which is precisely the blocking this control forbids. A
    # timeout does not make an operation noninteractive -- it just kills it after the stall.
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oStrictHostKeyChecking=accept-new",
    "GCM_INTERACTIVE": "never",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
}


def lane_status_fetch_env() -> dict:
    env = dict(os.environ)
    env.update(LANE_STATUS_NONINTERACTIVE_ENV)
    return env


def lane_status_fetch(
    target: Path, cfg: dict, *, deadline: float
) -> tuple[list[str], bool]:
    """Two bounded steps. Returns (reasons, succeeded); a failed fetch never advances the window.

    Step 1 is the CONFIGURED fetch, which prunes every stale remote-tracking ref including this
    lane's own upstream -- a command-line refspec would narrow `--prune` to that destination and
    leave a deleted feature branch's ref alive, which is what makes ORPHANED unreachable. Step 2
    pins the integration ref explicitly, because in a narrow-fetchspec clone step 1 can succeed
    while updating only FETCH_HEAD, leaving the ref we compare against stale.
    """
    remote = cfg["remote"]
    integration = cfg["integrationBranch"]
    base_ref = f"{remote}/{integration}"
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        return ["collection budget spent before the fetch could run"], False
    budget = min(int(cfg["fetchTimeoutSeconds"]), remaining)

    probe_base = ["rev-parse", "--verify", "--quiet", base_ref]
    before = lane_status_git(target, probe_base, deadline=deadline)
    code, stdout, stderr = run_command(
        ["git", "-C", str(target), "fetch", remote, "--prune", "--quiet"],
        timeout=budget,
        env=lane_status_fetch_env(),
    )
    if code != 0:
        detail = lane_status_safe_detail(
            f"git fetch {remote} --prune failed: {(stderr or stdout or 'unknown error').strip()}"
        )
        return [detail], False

    after = lane_status_git(target, probe_base, deadline=deadline)
    if after == "unavailable" or after == before:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            return ["collection budget spent before the integration ref could be fetched"], False
        forced_code, forced_out, forced_err = run_command(
            [
                "git", "-C", str(target), "fetch", remote, "--quiet",
                f"+refs/heads/{integration}:refs/remotes/{remote}/{integration}",
            ],
            timeout=min(int(cfg["fetchTimeoutSeconds"]), remaining),
            env=lane_status_fetch_env(),
        )
        # Discarding this result would report SUCCESS while the compared ref stayed stale, and
        # `lastFetchAt` would then suppress retries for maxAgeMinutes -- a lane printing `clean OK`
        # from refs it never refreshed, which is the failure this control exists to end.
        if forced_code != 0:
            detail = lane_status_safe_detail(
                f"git fetch {remote} {integration} failed: "
                f"{(forced_err or forced_out or 'unknown error').strip()}"
            )
            return [detail], False
        confirmed = lane_status_git(target, probe_base, deadline=deadline)
        if confirmed == "unavailable":
            return [f"{base_ref} could not be verified after fetching it"], False
    return [], True


def lane_status_should_fetch(target: Path, cfg: dict) -> bool:
    """Freshness is scoped to the comparison TARGET, not just to time.

    It reads `lastFetchAt`, not `recordedAt` -- `recordedAt` advances on runs that skipped fetching,
    so with sessions more frequent than maxAgeMinutes the window would never expire. It also
    requires the recorded remote and integration branch to match the current configuration: a fetch
    is evidence only about the target it ran for, and a retarget inside the window against an
    existing-but-stale ref would otherwise render `clean OK`.
    """
    try:
        recorded = json.loads(
            configured_path(target, cfg["statusFile"]).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, SystemExit):
        return True
    if str(recorded.get("remote") or "") != cfg["remote"]:
        return True
    if str(recorded.get("integrationBranch") or "") != cfg["integrationBranch"]:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(
            str(recorded.get("lastFetchAt")).replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return True
    return age.total_seconds() >= int(cfg["maxAgeMinutes"]) * 60


def lane_status_squatted_by(
    target: Path, cfg: dict, *, deadline: float
) -> tuple[str | None, str | None, str | None]:
    """The INTEGRATION branch pinned behind its remote by another worktree.

    git forbids the same branch in two worktrees, so "another worktree holds MY branch" is
    unreachable; the real 2026-07-24 condition was the integration branch held at an old commit.
    Returns (description, unverified_reason, path) -- an unreadable worktree list is a reported
    reason, never a silent "not squatted".
    """
    integration = cfg["integrationBranch"]
    out = lane_status_git(target, ["worktree", "list", "--porcelain"], deadline=deadline)
    if out == "unavailable":
        return None, "worktree list unavailable - squat check skipped", None
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1].strip()
        elif line.startswith("branch ") and path:
            if line.split(" ", 1)[1].strip() != f"refs/heads/{integration}":
                continue
            if Path(path).resolve(strict=False) == target.resolve(strict=False):
                continue
            held = lane_status_git(
                target, ["rev-parse", f"refs/heads/{integration}"], deadline=deadline
            )
            remote_tip = lane_status_git(
                target, ["rev-parse", f"{cfg['remote']}/{integration}"], deadline=deadline
            )
            if "unavailable" in (held, remote_tip):
                return None, f"could not compare {integration} against {cfg['remote']}", None
            if held == remote_tip:
                return None, None, None
            # DIRECTIONAL: only "held BEHIND the remote" is squatting. A peer worktree legitimately
            # ahead with unpublished commits is not, and branding it so is a false verdict.
            behind_code, _ = lane_status_git_probe(
                target, ["merge-base", "--is-ancestor", held, remote_tip], deadline=deadline
            )
            if behind_code not in (0, 1):
                return (
                    None,
                    f"could not compare {integration} against {cfg['remote']} "
                    f"(git exit {behind_code})",
                    None,
                )
            if behind_code == 1:
                return None, None, None
            return f"{path} (at {held[:7]}, remote is {remote_tip[:7]})", None, path
    return None, None, None


def lane_status_claim_state(
    target: Path, cfg: dict, branch: str | None, *, deadline: float | None = None
) -> tuple[str, str | None]:
    """Tri-state, returning (state, unverified_reason).

    An UNSET source is `not-checked` and silent -- that is the common adopter path. A CONFIGURED
    source that cannot be used is still `not-checked`, but with a reported reason: an otherwise
    clean lane must not print `clean OK` over a check the adopter asked for and did not get.
    """
    source = str(cfg.get("claimSource") or "")
    if not source:
        return "not-checked", None
    if not branch:
        return "not-checked", "claim source configured but this lane has no branch identity"
    try:
        root = configured_path(target, source, allow_outside=True)
    except (SystemExit, ValueError, OSError):
        return "not-checked", f"claim source {source} could not be resolved - claim check skipped"
    if not root.is_dir():
        return "not-checked", f"claim source {source} is not a directory - claim check skipped"
    # Enumerate LAZILY with a bound: `sorted(root.iterdir())` materialises and sorts the whole
    # directory before any deadline check, so a large or slow claim source could burn the budget
    # before the loop below ever runs.
    entries = []
    try:
        for index, entry in enumerate(root.iterdir()):
            if deadline is not None and time.monotonic() >= deadline:
                return "not-checked", (
                    "claim scan exceeded the collection budget - claim check skipped"
                )
            if index >= LANE_STATUS_MAX_CLAIM_ENTRIES:
                return "not-checked", (
                    f"claim source has more than {LANE_STATUS_MAX_CLAIM_ENTRIES} entries - "
                    "claim check skipped"
                )
            entries.append(entry)
    except OSError:
        return "not-checked", f"claim source {source} is unreadable - claim check skipped"
    entries.sort()
    # EXACT match, never substring: a directory named `item-2` would otherwise match branch
    # `feat/item-27`, and this item's own claim (a dated slug) would miss its lane branch entirely.
    candidates = {branch.strip().lower(), branch.rsplit("/", 1)[-1].strip().lower()}
    for entry in entries:
        # A claimSource on a slow mount, or holding thousands of entries, must not let the host
        # timeout kill the hook before it reports: the scan yields to the shared budget like every
        # other probe on this path.
        if deadline is not None and time.monotonic() >= deadline:
            return "not-checked", "claim scan exceeded the collection budget - claim check skipped"
        if not entry.is_dir():
            continue
        declared = lane_status_declared_claim_branch(entry)
        if declared is not None:
            if declared.strip().lower() in candidates:
                return "matched", None
            continue
        if entry.name.strip().lower() in candidates:
            return "matched", None
    return "unmatched", None


def occupancy_read_record(path: Path) -> dict | None:
    """A lease/peer record read under the constraints of a session-start hook, or None.

    DESCRIPTOR-BASED, so the object checked is the object read. A stat-then-open pair can be
    defeated by swapping a FIFO in between -- and `.ai-work/occupancy-peers` is a directory other
    local processes write concurrently, so that is an ordinary race rather than an exotic one.
    Codex R3 P2. `O_NONBLOCK` means even a FIFO that slips through cannot block the open, and the
    `fstat` that follows is asked of the descriptor we hold rather than of the name.

    Bounded because this runs inside `lane-status`'s deadline: a device or a very large file would
    consume the budget the hook does not have.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > OCCUPANCY_RECORD_MAX_BYTES:
            return None
        # LOOP TO EOF. A single os.read may return a SHORT read -- ordinary on network and FUSE
        # filesystems -- and a prefix of a valid record parses as unreadable, so a live peer would
        # go unreported and a spurious UNVERIFIED line would appear instead. Codex R4 P2; the
        # module's own lease reader already loops for exactly this reason. The cap still bounds it:
        # reading one byte past the limit is enough to know the file is too big to be a record.
        chunks: list[bytes] = []
        remaining = OCCUPANCY_RECORD_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        lease = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError, UnicodeDecodeError):
        # ValueError covers JSONDecodeError (its subclass) and the plain ValueError a JSON integer
        # past Python's digit limit raises; RecursionError covers deep nesting; UnicodeDecodeError
        # covers non-UTF-8 bytes. Three review rounds found these one at a time, which is the
        # argument for catching the family rather than enumerating members.
        return None
    return lease if isinstance(lease, dict) else None


def occupancy_write_peer_record(target: Path, identity: dict, data: dict) -> Path | None:
    """Record that this session is HERE even though it does not hold the lease.

    The holder's lease answers "who won"; this answers "who else is in the room". Without it the
    session that lost the race is invisible to the very report meant to surface it.
    """
    session_id = str((identity or {}).get("session_id") or "").strip()
    if not session_id:
        return None
    peers = Path(target) / ".ai-work" / "occupancy-peers"
    # Filename derived from the session id, never the id itself: it may contain path separators.
    name = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    path = peers / f"{name}.json"
    # WRITTEN IN THE SHAPE THE READER ACCEPTS. `occupancy_lease_is_live` runs every record through
    # `_lease_well_formed`, which requires the schema marker and a `host` field -- my first version
    # omitted the schema and wrote `hostname`, so every peer record was discarded as malformed and
    # the peer-record-only case never fired at all. Codex R2 P2. That is the module's own
    # "writer accepted, reader rejected" class, which its comments warn about three times over;
    # the fix is to write through the same vocabulary the predicate reads, not a parallel one.
    record = {
        "schema": OCCUPANCY_LEASE_SCHEMA,
        "session_id": session_id,
        "pid": identity.get("pid"),
        "host": socket.gethostname(),
        "branch": run_git(target, ["branch", "--show-current"]) or "",
        "started_at": now_iso(),
        "ttl_minutes": fleet_config(data)["occupancy"]["ttlMinutes"],
    }
    try:
        peers.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return None
    return path


def lane_status_foreign_lease(target: Path, unverified: list) -> dict | None:
    """The record of another live session in this worktree, or None. Never raises, never fetches.

    Reads BOTH the holder lease and the peer records, because they answer different questions. A
    session that ran `lane-start` holds the lease; a session that never ran it holds nothing but
    still wrote a peer record -- and reporting only on the lease would make the one kind of session
    that skipped the gate the one kind nothing notices.

    A read failure appends to `unverified` rather than raising or returning None quietly: this
    collector runs inside a session-start hook, and "I could not look" must not render as "nobody
    is here". That is the same distinction the closeout work drew, and for the same reason.
    """
    identity = occupancy_session_identity()
    mine = str(identity.get("session_id") or "").strip()
    now = datetime.now(timezone.utc)
    candidates: list[Path] = []
    lease_path = occupancy_lease_path(target)
    if lease_path is not None:
        candidates.append(lease_path)
    peers_dir = Path(target) / ".ai-work" / "occupancy-peers"
    # SCANNED LAZILY, NOT SORTED. The previous shape sorted the whole directory by mtime and then
    # sliced -- so the cap limited how many records were PARSED but not how many were STATTED, and
    # "newest 64" could drop an older long-lived LIVE peer behind newer stale ones. Codex R2 P2,
    # raised twice. os.scandir yields entries without materializing the directory, and liveness is
    # the criterion that actually matters, so this stops at the first live foreign record rather
    # than ranking candidates it does not need to rank.
    examined = 0
    try:
        with os.scandir(peers_dir) as entries:
            for entry in entries:
                if examined >= OCCUPANCY_PEER_SCAN_LIMIT:
                    unverified.append(
                        f"occupancy peer records: stopped after {OCCUPANCY_PEER_SCAN_LIMIT} "
                        "examined; a live peer beyond that is not reported"
                    )
                    break
                if not entry.name.endswith(".json"):
                    continue
                examined += 1
                candidates.append(Path(entry.path))
    except FileNotFoundError:
        pass
    except OSError as exc:
        unverified.append(f"occupancy peer records unreadable: {exc}")
    for path in candidates:
        lease = occupancy_read_record(path)
        if lease is None:
            # Absent is silent; PRESENT-but-unreadable is not, because "I could not look" must not
            # render as "nobody is here".
            if path.exists():
                unverified.append(f"occupancy record unreadable or oversized: {path.name}")
            continue
        try:
            if not occupancy_lease_is_live(lease, now):
                continue
        except Exception:  # noqa: BLE001 - a liveness predicate must not break session start
            continue
        theirs = str(lease.get("session_id") or "").strip()
        if theirs and theirs != mine:
            return lease
    return None


def collect_lane_status_facts(
    data: dict, target: Path, *, cfg: dict, deadline: float
) -> tuple[dict, bool]:
    """Returns (facts, fetch_succeeded). The deadline is a PARAMETER, not created here: the handler
    does work before collection, and a fresh budget here would let the host timeout kill the hook
    before anything printed."""
    unverified: list[str] = []
    integration = cfg["integrationBranch"]
    remote = cfg["remote"]

    remote_ok = lane_status_remote_is_usable(target, remote, deadline=deadline)
    if not remote_ok:
        unverified.append(
            "latestCode.remote is not a configured remote of this repository - "
            "ref comparison skipped"
        )
    ref_ok = lane_status_ref_is_usable(target, integration, deadline=deadline)
    if not ref_ok:
        unverified.append(
            "laneStatus.integrationBranch is not a valid branch name - ref comparison skipped"
        )
    comparable = remote_ok and ref_ok
    # The raw value never reaches the report, the artifact, or --json.
    reported_remote = remote if remote_ok else LANE_STATUS_UNUSABLE_REMOTE
    base_ref = f"{remote}/{integration}" if comparable else ""

    branch_code, branch_raw = lane_status_git_probe(
        target, ["branch", "--show-current"], deadline=deadline
    )
    branch_probe_failed = branch_code != 0
    if branch_probe_failed:
        branch = None
        unverified.append("could not read the current branch - lane identity unverified")
    else:
        branch = branch_raw or None

    fetched = False
    if comparable and lane_status_should_fetch(target, cfg):
        reasons, fetched = lane_status_fetch(target, cfg, deadline=deadline)
        unverified.extend(reasons)

    upstream_raw = (
        lane_status_git(
            target,
            [
                "for-each-ref",
                "--format=%(upstream:short)%09%(upstream:track)",
                f"refs/heads/{branch}",
            ],
            deadline=deadline,
        )
        if branch
        else "unavailable"
    )
    if upstream_raw == "unavailable" or not upstream_raw.strip():
        upstream, upstream_gone = None, False
        if branch is not None:
            unverified.append("no upstream is configured for this branch (or it could not be read)")
    else:
        name, _, track = upstream_raw.partition("\t")
        upstream = name.strip() or None
        upstream_gone = bool(upstream) and "gone" in track.lower()
        if upstream and not upstream_gone:
            # `--quiet` is MANDATORY: without it a missing ref exits 128, not 1, and the
            # exit-1-means-absent rule would classify every deleted upstream as a failed probe --
            # so ORPHANED, this item's primary acceptance criterion, could never fire.
            verify_code, _ = lane_status_git_probe(
                target,
                ["rev-parse", "--verify", "--quiet", "--end-of-options", upstream],
                deadline=deadline,
            )
            if verify_code == 1:
                upstream_gone = True
            elif verify_code != 0:
                unverified.append(
                    f"could not verify whether {upstream} still exists (git exit {verify_code})"
                )

    ahead = behind = "unknown"
    base_version: str | None = None
    merged = False
    if comparable:
        base_present, _ = lane_status_git_probe(
            target,
            ["rev-parse", "--verify", "--quiet", "--end-of-options", base_ref],
            deadline=deadline,
        )
        if base_present != 0:
            unverified.append(f"{base_ref} is not present locally - cannot compare")
        else:
            # git_ahead_behind resolves the module-level UNBOUNDED run_git and has other callers,
            # so its two-line rev-list is inlined through the bounded probe instead.
            counts = lane_status_git(
                target,
                ["rev-list", "--left-right", "--count", f"HEAD...{base_ref}"],
                deadline=deadline,
            )
            parts = counts.split()
            if len(parts) == 2:
                ahead, behind = parts[0], parts[1]
            else:
                unverified.append("ahead/behind unavailable")
            # Distinguish ABSENT (no VERSION at base -- silent, adopters need not have one) from a
            # FAILED READ (corrupt blob, timeout). `cat-file -e` answers existence separately, so a
            # read failure on a file that IS there becomes UNVERIFIED instead of silently clean.
            base_version_exists, _ = lane_status_git_probe(
                target, ["cat-file", "-e", f"{base_ref}:VERSION"], deadline=deadline
            )
            base_version_code, base_version_raw = lane_status_git_probe(
                target, ["show", f"{base_ref}:VERSION"], deadline=deadline
            )
            if base_version_code == 0:
                base_version = base_version_raw.strip()
            elif base_version_exists == 0:
                unverified.append(
                    f"{base_ref}:VERSION exists but could not be read - "
                    "version comparison skipped"
                )
            # An ABSENT VERSION is not a failed check -- adopter repos need not have one. Only a
            # VERSION that exists on both sides and cannot be read or parsed is UNVERIFIED.
            merged_out = lane_status_git(
                target, ["branch", "--merged", base_ref], deadline=deadline
            )
            if merged_out == "unavailable":
                unverified.append("merged-into-base check unavailable")
            else:
                merged = (
                    bool(branch)
                    and branch != integration  # the base lane is not "dead"
                    and any(
                        line.strip().lstrip("* ").strip() == branch
                        for line in merged_out.splitlines()
                    )
                )

    # The COMMITTED version, so an uncommitted edit cannot mask STALE; DIRTY carries the tree.
    local_version_exists, _ = lane_status_git_probe(
        target, ["cat-file", "-e", "HEAD:VERSION"], deadline=deadline
    )
    local_version_code, local_version_raw = lane_status_git_probe(
        target, ["show", "HEAD:VERSION"], deadline=deadline
    )
    if local_version_code == 0:
        local_version = local_version_raw.strip()
    else:
        local_version = None
        if local_version_exists == 0:
            unverified.append("HEAD:VERSION exists but could not be read")

    module = lane_status_module()
    if local_version and base_version:
        if (
            module._version_tuple_or_none(local_version) is None
            or module._version_tuple_or_none(base_version) is None
        ):
            unverified.append(
                f"VERSION values are not comparable "
                f"({lane_status_safe_detail(local_version, limit=32)} vs "
                f"{lane_status_safe_detail(base_version, limit=32)})"
            )

    dirty_code, dirty_out = lane_status_git_probe(
        target, ["status", "--porcelain"], deadline=deadline
    )
    if dirty_code != 0:
        dirty = False
        unverified.append("working-tree status unavailable")
    else:
        dirty = bool(dirty_out)

    squatted_by = squatted_path = None
    if comparable:
        squatted_by, squat_reason, squatted_path = lane_status_squatted_by(
            target, cfg, deadline=deadline
        )
        if squat_reason:
            unverified.append(squat_reason)

    claim_state, claim_reason = lane_status_claim_state(
        target, cfg, branch, deadline=deadline
    )
    if claim_reason:
        unverified.append(claim_reason)

    return (
        {
            "branch": branch,
            "branch_probe_failed": branch_probe_failed,
            "upstream": upstream,
            "upstream_gone": upstream_gone,
            "ahead": ahead,
            "behind": behind,
            "local_version": local_version,
            "base_version": base_version,
            "integration_branch": integration,
            "remote": reported_remote,
            "merged_into_base": merged,
            "dirty": dirty,
            "squatted_by": squatted_by,
            "squatted_path": squatted_path,
            "claim_state": claim_state,
            "claim_source": str(cfg.get("claimSource") or ""),
            # GATED ON THE SAME SWITCH THE OTHER TWO READ. lane-start and the SessionStart seam
            # both honour the opt-out; this collector did not, so a lane that had explicitly
            # disabled occupancy still got CONCURRENT (or UNVERIFIED) from an old live lease --
            # most sharply right after flipping the adapter while a peer's lease is still running.
            # One switch, every reader. Codex R3 P2.
            "foreign_lease": (
                lane_status_foreign_lease(target, unverified)
                if occupancy_enabled(data)
                else None
            ),
            "unverified": unverified,
        },
        fetched,
    )


def methodology_status(args: argparse.Namespace) -> int:
    """Report identity, lock state, adapter drift, and lane paths.

    Process-bankruptcy demolition (2026-08-28): the ceremony index this verb used to print --
    goal/milestone ledgers, board currency, hook inventories, control posture, go-live readiness,
    behavior-spec and journal status -- was removed with the machinery behind it. What remains is
    the report a lean lane actually reads: who am I, what am I pinned to, and has the generated
    adapter drifted. Drift is the only failing condition, under --strict or --fail-on-drift.
    """
    data, project_path, target = lane_project(args)
    locked = read_lock(data, target)
    drift = adapter_drift(data, project_path, target)
    protected_markdown = protected_adapter_markdown(data, project_path, target)
    print(f"project: {data['project']}")
    print(f"target: {target}")
    print(f"methodology_repo: {REPO_ROOT}")
    print(f"plugin: {plugin_name()}")
    print(f"plugin_version: {plugin_version()}")
    print(f"methodology_commit: {running_methodology_commit(short=True)}")
    # THE SURFACE THAT WORKS EVERYWHERE. lane-status carries this line too, but only at
    # SessionStart and only where a harness runs hooks -- which is exactly the capability a
    # zero-capability runtime lacks. methodology-status is invoked deliberately and always
    # answers, so for the lane with the least enforcement this line is not a convenience.
    # Dropping it when this function was trimmed left that lane told nothing at all.
    _degradation = runtime_capabilities.lane_degradation(data)
    if _degradation.get("runtime"):
        print(f"enforcement: {runtime_capabilities.summary_line(_degradation)}")
    else:
        print(
            "enforcement: no runtime resolved for `roles.builder`, so no in-session gate is "
            "known to run in this lane"
        )
    # Adapter-compat diagnostics, kept: the shim REPORTS what it inferred rather than applying it
    # silently, and a deprecated adapter key is a real migration signal, not process ceremony.
    for line in agent_compat.inferred_summary_lines(data):
        print(line)
    for warning in agent_compat.deprecation_warnings(data):
        print(warning, file=sys.stderr)
    print(methodology_canonical_commit_line())
    print(methodology_exec_root_line())
    print(f"remote_status: {remote_methodology_status(args.no_remote)}")
    if locked and locked.get("invalid"):
        print(f"lock: invalid - {locked.get('path')}")
    elif locked:
        print(f"lock: locked {locked.get('shortCommit') or locked.get('commit', 'unknown')} - {locked.get('reason', 'no reason')}")
    else:
        print("lock: unlocked")
    print(f"adapter_drift: {'clean' if not drift else ', '.join(drift)}")
    print(f"adapter_markdown_protected: {'none' if not protected_markdown else ', '.join(protected_markdown)}")
    env_path = lane_env_path(data, target)
    print(f"lane_env: {'present' if env_path.exists() else 'missing'} {env_path}")
    if not drift:
        return 0
    if args.strict or args.fail_on_drift:
        print("methodology_status_blocking: integrity - drift")
        return 1
    return 0


def version(args: argparse.Namespace) -> int:
    print(f"plugin: {plugin_name()}")
    print(f"plugin_version: {plugin_version()}")
    print("version_source: VERSION")
    print(f"methodology_repo: {REPO_ROOT}")
    print(f"methodology_commit: {running_methodology_commit()}")
    print(f"methodology_commit_short: {running_methodology_commit(short=True)}")
    print(methodology_canonical_commit_line())
    print(methodology_exec_root_line())
    if running_from_installed_package():
        # Snapshot-store machines get NEITHER line: they update via repin, and telling them to
        # pip install would be actively wrong (test_snapshot_store_snapshot_gets_no_pip_hint).
        print("install_kind: package")
        print(f"update_hint: {PACKAGE_INSTALL_UPDATE_HINT}")
    print(f"remote_status: {remote_methodology_status(args.no_remote)}")
    return 0


def _builder_contract():
    """The builder-lane contract module, imported lazily.

    `builder.py` is the ONE place the role marker's spelling lives, and install-cli's generated
    env template offers that marker as a commented example. Spelling `TAUTLINE_ROLE=builder` here
    as a literal would be a second copy that nothing keeps in step with the first.
    """
    from tautline_methodology import builder

    return builder


def preserved_user_config_exports(config_env: Path) -> list[str]:
    if not config_env.exists():
        return []
    preserved: list[str] = []
    try:
        lines = config_env.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        stripped = line.strip()
        match = re.match(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=", stripped)
        if not match:
            continue
        if match.group(1) in MANAGED_USER_CONFIG_ENV_KEYS:
            continue
        if stripped not in preserved:
            preserved.append(stripped)
    return preserved


# --- The install-cli -> launcher-reinstall window ------------------------------------------
# install-cli turns snapshot execution ON. Only `install-claude-launcher --force` starts EXPORTING
# a session-pinned MINERVIT_METHODOLOGY_EXEC_ROOT. In between, a session started by a pre-cutover
# launcher runs UNPINNED against `<store>/current` -- and another lane's sync can swap that symlink
# underneath it, so its hooks can hop Tautline versions between invocations. That window is
# invisible unless we say so, loudly, in both commands that can observe it.
LAUNCHER_TEMPLATE_VERSION = 2
LAUNCHER_TEMPLATE_MARKER = f"# tautline-launcher-template: {LAUNCHER_TEMPLATE_VERSION}"
# The remedy for a pre-cutover launcher. It used to be `install-claude-launcher --force`, which
# REGENERATED the launcher; the 2026-08-28 demolition deleted that generator, so the only way to
# close the window now is to remove the stale launcher and let the installed shim serve. The
# detection is unchanged and still worth having: a launcher that predates snapshot execution
# starts sessions that version-hop mid-run, and nothing else reports it.
LAUNCHER_CUTOVER_REMEDY = "remove the pre-cutover launcher; the shim install-cli writes supersedes it"


def stale_claude_launchers(*bin_dirs: Path) -> list[Path]:
    """Installed Claude launchers generated before the snapshot-store cutover.

    Identified by what they ARE (our generated header) minus what they must become (the template
    marker), so a launcher the operator regenerates drops off the list without any extra state.
    """
    stale: list[Path] = []
    seen: set[Path] = set()
    for bin_dir in bin_dirs:
        try:
            entries = sorted(bin_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            resolved = entry.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            text = _launcher_text(entry)
            if text is None:
                continue
            # Operator launchers (FR-1) don't track LAUNCHER_TEMPLATE_VERSION; they are a distinct
            # non-blocking template. Excluding them here keeps a future template bump from flagging
            # them stale and having a regen-without-`--operator-channel` silently convert them back
            # into a gated default launcher (FR1V native-review P3).
            if OPERATOR_LAUNCHER_MARKER in text:
                continue
            if LAUNCHER_GENERATED_MARKER in text and LAUNCHER_TEMPLATE_MARKER not in text:
                stale.append(entry)
    return stale


def installed_launchers_path() -> Path:
    return methodology_state_dir() / "installed-launchers.json"


def read_installed_launcher_entries() -> list[dict] | None:
    """Recorded launchers as {path, sha256?} entries, or None when there is no usable record.

    Reads BOTH record shapes. v1 recorded bare path strings; those entries have no digest, and a
    digest-less entry is not a defect to report -- it simply narrows what
    diverged_installed_launchers() can prove about that launcher (see its docstring). Silently
    upgrading v1 to v2 here is deliberately NOT done: the digest a reader would compute is the
    CURRENT bytes, which would bless a launcher that was already hand-replaced.
    """
    try:
        data = json.loads(installed_launchers_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = data.get("launchers") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    parsed: list[dict] = []
    for entry in entries:
        if isinstance(entry, str) and entry:  # v1: a bare path
            parsed.append({"path": entry})
            continue
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        item: dict = {"path": path}
        digest = entry.get("sha256")
        if isinstance(digest, str) and digest.strip():
            item["sha256"] = digest.strip()
        install = entry.get("install")
        if isinstance(install, dict):
            item["install"] = install
        parsed.append(item)
    return parsed


def read_installed_launchers() -> list[Path] | None:
    """Recorded launcher paths, or None when the recorder has never written a usable record.

    None and [] are DIFFERENT answers, and the difference is the whole point: every launcher
    installed before this release predates the recorder, so "no record" means "there may be
    pre-cutover launchers on this machine that I cannot see", while [] means the recorder ran and
    genuinely knows of none. Collapsing the two would let exactly the launchers we are hunting --
    the old ones, in whatever bin dir the operator chose -- escape detection in silence.
    """
    entries = read_installed_launcher_entries()
    if entries is None:
        return None
    return [Path(entry["path"]) for entry in entries]


def diverged_installed_launchers() -> list[tuple[Path, str]]:
    """Recorded launchers that are no longer the generator's output, with why.

    RCA 2026-07-22 control 4. A hand-written replacement for a generated launcher is invisible to
    every generator-side guard: it never receives a new interlock, never bumps a template version,
    and drifts further from the framework with each release. That is precisely how a machine kept
    a launcher whose shell rescue could reset the operator's deliberately-tracked checkout, months
    after the framework grew the guard that would have stopped it.

    TWO detections, because the record predates digests and the fleet's existing records have none:

    - `hand-replaced`: the file no longer carries the generated marker. Needs NO digest, so it
      catches the July-20 class from a v1 record -- someone overwrote a generated launcher with
      their own script.
    - `edited`: the file still looks generated, but its bytes differ from what the generator
      wrote. Only a recorded digest can see this one.

    A recorded launcher that no longer exists is NOT a divergence: the operator deleting a
    launcher is legitimate, and a notice that never goes away is a notice that gets ignored.
    """
    diverged: list[tuple[Path, str]] = []
    for entry in read_installed_launcher_entries() or []:
        path = Path(entry["path"])
        generated = _launcher_looks_generated(path)
        if generated is None:  # gone, or unreadable: nothing we can honestly accuse
            continue
        if not generated:
            diverged.append((path, LAUNCHER_DIVERGENCE_HAND_REPLACED))
            continue
        recorded = entry.get("sha256")
        current = _launcher_digest(path)
        if recorded and current and current != recorded:
            diverged.append((path, LAUNCHER_DIVERGENCE_EDITED))
    return diverged


def launcher_regeneration_command(path: Path, install: dict | None) -> str:
    """The command that regenerates THIS launcher, or an honest hedge when we cannot know.

    Codex R1 P2. A bare `install-claude-launcher --name <basename> --force` is the right command
    only for a default-options install. For a launcher installed with `--bin-dir` it targets the
    wrong directory and leaves the divergence in place; for an OPERATOR launcher it is actively
    harmful -- it would replace a deliberately non-blocking launcher with a gated one, which is
    the very failure this RCA exists to end. So the options are recorded at install and replayed
    here.

    Records written before this release carry no install metadata. Rather than print a command
    that might be wrong for them, the line names the default form and says plainly that the
    original options must be re-added. A remediation the operator cannot trust is worse than one
    that admits what it does not know.
    """
    command = f"{CLI_NAME} install-claude-launcher --name {shlex.quote(path.name)}"
    if not install:
        return (
            f"{command} --force"
            "   # re-add the --bin-dir/--operator-channel/--runtime/--dangerously-skip-permissions"
            " options this launcher was originally installed with, if any"
        )
    bin_dir = install.get("binDir")
    if bin_dir and Path(str(bin_dir)) != USER_BIN_DIR:
        command += f" --bin-dir {shlex.quote(str(bin_dir))}"
    channel = install.get("operatorChannel")
    if channel:
        command += f" --operator-channel {shlex.quote(str(channel))}"
        runtime = install.get("runtime")
        if runtime:
            command += f" --runtime {shlex.quote(str(runtime))}"
    elif install.get("skipPermissions"):
        command += " --dangerously-skip-permissions"
    return f"{command} --force"


def launcher_divergence_lines(diverged: list[tuple[Path, str]]) -> list[str]:
    """The loud diverged-launcher notice, with the exact regeneration command per launcher.

    Per-launcher, not the bare cutover command: the operator's launchers are named whatever they
    chose and were installed with whatever options they chose, and a remediation line that
    regenerates the wrong launcher -- or the wrong KIND of launcher -- is worse than none (Codex
    R1 P2; see launcher_regeneration_command). The `launcher_divergence:` lines stay unprefixed
    and greppable like every other machine-readable report line.
    """
    if not diverged:
        return []
    bar = "!" * 76
    lines = [
        bar,
        f"!! GENERATED LAUNCHER DIVERGED -- {len(diverged)} launcher(s) this machine recorded",
        "!! as generated no longer match the generator. A hand-edited or hand-replaced launcher",
        "!! is invisible to every generator-side guard: it will not receive new interlocks and",
        "!! drifts further from the framework with each release.",
        "!!",
    ]
    for path, reason in diverged:
        lines.append(f"launcher_divergence: {path} {reason}")
    lines.append("!!")
    lines.append("!! Regenerate each one (customizations belong in a wrapper, not in the file):")
    recorded = {
        entry["path"]: entry.get("install")
        for entry in (read_installed_launcher_entries() or [])
    }
    for path, _reason in diverged:
        lines.append(f"!!   {launcher_regeneration_command(path, recorded.get(str(path)))}")
    lines.append(bar)
    return lines


def launcher_template_status_line() -> str | None:
    """What sync says about the launchers on this machine, or None when there is nothing to say.

    Only under snapshot mode: before the cutover there is no session exec root to be missing, so a
    v1 launcher is not stale, it is simply current.
    """
    if not methodology_snapshot_store_enabled():
        return None
    recorded = read_installed_launchers()
    if recorded is None:
        return (
            f"launcher_template: unknown - rerun {CLI_NAME} install-claude-launcher "
            "to record and upgrade launchers"
        )
    for path in recorded:
        text = _launcher_text(path)
        if text is not None and LAUNCHER_TEMPLATE_MARKER not in text:
            return f"launcher_template: stale - rerun {CLI_NAME} install-claude-launcher"
    return None


def launcher_cutover_warning_lines(stale: list[Path]) -> list[str]:
    bar = "!" * 76
    lines = [
        bar,
        "!! REQUIRED NEXT STEP -- this machine is HALF-CONVERTED to snapshot execution.",
        "!!",
        f"!!     {LAUNCHER_CUTOVER_REMEDY}",
        "!!",
        "!! Snapshot execution is ON, but a launcher generated before this cutover does not",
        "!! export a session exec root. Every session it starts runs UNPINNED against",
        "!! <store>/current, so another lane's sync can swap that symlink mid-session and the",
        "!! session's hooks will hop Tautline versions between invocations.",
    ]
    if stale:
        lines.append("!! Pre-cutover launchers found (regenerate every one of them):")
        lines.extend(f"!!   - {path}" for path in stale)
    else:
        lines.append("!! No pre-cutover launcher was found; remove any you installed by hand.")
    lines.append(bar)
    return lines


def warn_unpinned_launcher_window(*bin_dirs: Path) -> list[Path]:
    """Print the cutover banner when a pre-cutover launcher can still start unpinned sessions."""
    stale = stale_claude_launchers(*(bin_dirs or (USER_BIN_DIR,)))
    if not stale:
        return []
    for line in launcher_cutover_warning_lines(stale):
        print(line, file=sys.stderr)
    return stale


def install_cli(args: argparse.Namespace) -> int:
    bin_dir = args.bin_dir.expanduser().resolve()
    config_env = args.config_env.expanduser().resolve()
    shim = bin_dir / CLI_NAME
    legacy_shim = bin_dir / LEGACY_CLI_NAME
    # EVERY piece of state install-cli writes describes the CANONICAL checkout, never REPO_ROOT.
    # After the cutover install-cli itself normally runs FROM the immutable snapshot: recording
    # REPO_ROOT there would point methodology.env at a tree with no `.git` and no origin, pin the
    # trust allowlist at "unavailable", and leave nothing able to rebuild the store.
    canonical = canonical_methodology_repo()
    store_root = methodology_snapshot_store_root()
    canonical_head = run_git(canonical, ["rev-parse", "HEAD"])
    # sec-trust-exec-1: a fresh install pins the auto-update trust policy to the commit it installed
    # from, so the default new-install experience fails closed on an unexpected upstream instead of
    # re-exec'ing it. `update-repin` advances the pin after the operator reviews upstream.
    update_policy = getattr(args, "update_policy", "pinned") or "pinned"
    install_head = canonical_head if update_policy == "pinned" else ""
    if getattr(args, "dry_run", False):
        # prod-onboarding-4: show exactly what install-cli would mutate before it touches the machine.
        print("install_cli_dry_run: planned actions (no changes made):")
        print(f"  mkdir -p {bin_dir}")
        print(f"  mkdir -p {config_env.parent} (chmod 0700)")
        print(f"  write {config_env} (chmod 0600) setting MINERVIT_METHODOLOGY_REPO={canonical}")
        print(f"  set {METHODOLOGY_CANONICAL_REPO_ENV}={canonical} (both alias spellings)")
        print(f"  set {METHODOLOGY_SNAPSHOT_STORE_ENV}={store_root} (both alias spellings)")
        if config_env == USER_CONFIG_ENV.expanduser().resolve(strict=False):
            print(f"  write byte-identical legacy compatibility mirror {LEGACY_USER_CONFIG_ENV} (chmod 0600)")
        if update_policy == "pinned":
            print(
                f"  set {METHODOLOGY_UPDATE_POLICY_ENV}=pinned pinned at HEAD {install_head[:12]} "
                f"(advance by editing {METHODOLOGY_UPDATE_PINS_FILE})"
            )
        else:
            print(f"  set {METHODOLOGY_UPDATE_POLICY_ENV}={update_policy} (no pin written)")
        print(f"  make {config_env} source optional local secrets from {USER_SECRETS_ENV}")
        print(f"  write executable shim {shim}")
        print(f"  materialize snapshot of {canonical} HEAD {canonical_head[:12]} into {store_root}")
        print(f"  point {store_root}/current at that snapshot (shims execute it from then on)")
        print(f"  ensure {Path.home() / '.claude' / 'settings.json'} autocompact settings")
        print(f"  install methodology release guards under {canonical}")
        print(f"  then, IF a pre-cutover launcher exists: {LAUNCHER_CUTOVER_REMEDY}")
        print("  undo a real install with: tautline uninstall-cli")
        return 0
    bin_dir.mkdir(parents=True, exist_ok=True)
    # sec-secrets-2: methodology.env can hold preserved local secrets (webhook URLs/tokens). Create
    # the parent 0700 and warn if an existing file is group/other-readable, so secrets are not left
    # world-readable on a shared machine.
    config_env.parent.mkdir(parents=True, exist_ok=True)
    try:
        config_env.parent.chmod(0o700)
    except OSError:
        pass
    if config_env.exists():
        try:
            existing_mode = config_env.stat().st_mode
            if existing_mode & 0o077:
                print(
                    f"install_cli: warning - {config_env} was group/other-readable "
                    f"({existing_mode & 0o777:o}); tightening to 0600",
                    file=sys.stderr,
                )
        except OSError:
            pass
    # Rebrand transition: preserve user exports (webhook secrets etc.) from BOTH config surfaces.
    # Merge by VARIABLE NAME with the preferred file winning (Codex 0.9.2 R1 P2): exact-line dedup
    # would append a stale legacy assignment after the new one, and shell sourcing would then make
    # the stale value effective.
    # Normalized default-path comparison (Codex 0.9.2 R1 P2): config_env is resolved but the
    # constant is not; a symlinked HOME (macOS /var -> /private/var) must not skip the mirror.
    default_config_env = USER_CONFIG_ENV.expanduser().resolve(strict=False)
    preserved_exports = preserved_user_config_exports(config_env)
    if config_env == default_config_env:
        seen_names = {
            match.group(1)
            for entry in preserved_exports
            if (match := re.match(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=", entry))
        }
        for entry in preserved_user_config_exports(LEGACY_USER_CONFIG_ENV):
            match = re.match(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=", entry)
            if match and match.group(1) in seen_names:
                continue
            if match:
                seen_names.add(match.group(1))
            if entry not in preserved_exports:
                preserved_exports.append(entry)
    preserved_source = config_env if config_env.is_file() else (
        LEGACY_USER_CONFIG_ENV if LEGACY_USER_CONFIG_ENV.is_file() else config_env
    )

    # Pin behavior unchanged from 0.9.1: install pins at the installing HEAD; run update-repin
    # AFTER install-cli to widen trust (the machine-conversion runbook order). Pin-set
    # preservation ships separately as its own focused security change.
    pins_value = install_head

    env_lines = [
        "# Generated by tautline install-cli.",
        f"export TAUTLINE_METHODOLOGY_REPO={shlex.quote(str(canonical))}",
        f"export MINERVIT_METHODOLOGY_REPO={shlex.quote(str(canonical))}",
        # The snapshot-store cutover, in both alias spellings so resolve_env's TAUTLINE_-first
        # preference and every legacy MINERVIT_-only reader agree about one machine.
        f"export TAUTLINE_METHODOLOGY_CANONICAL_REPO={shlex.quote(str(canonical))}",
        f"export MINERVIT_METHODOLOGY_CANONICAL_REPO={shlex.quote(str(canonical))}",
        f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={shlex.quote(str(store_root))}",
        f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={shlex.quote(str(store_root))}",
        f"TAUTLINE_SECRETS_ENV={shlex.quote(str(USER_SECRETS_ENV))}",
        f"MINERVIT_SECRETS_ENV={shlex.quote(str(LEGACY_USER_SECRETS_ENV))}",
        'if [ -f "$TAUTLINE_SECRETS_ENV" ]; then',
        '  . "$TAUTLINE_SECRETS_ENV"',
        'elif [ -f "$MINERVIT_SECRETS_ENV" ]; then',
        '  . "$MINERVIT_SECRETS_ENV"',
        "fi",
        f"export MINERVIT_CLAUDE_AUTOCOMPACT_PCT=\"${{TAUTLINE_CLAUDE_AUTOCOMPACT_PCT:-${{MINERVIT_CLAUDE_AUTOCOMPACT_PCT:-{DEFAULT_CLAUDE_AUTOCOMPACT_PERCENT}}}}}\"",
        'export TAUTLINE_CLAUDE_AUTOCOMPACT_PCT="$MINERVIT_CLAUDE_AUTOCOMPACT_PCT"',
        'export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE="$MINERVIT_CLAUDE_AUTOCOMPACT_PCT"',
        f"export PATH={shlex.quote(str(bin_dir))}:$PATH",
        # Dual-write both spellings (R3 amendment b): a fresh config resolves the TAUTLINE_ alias
        # first, so it never trips its own MINERVIT_ sunset warning.
        f"export {METHODOLOGY_UPDATE_POLICY_ENV}={update_policy}",
        f"export TAUTLINE_METHODOLOGY_UPDATE_POLICY={update_policy}",
        "",
        # COMMENTED, and it stays commented. A machine-wide builder role is a decision about the
        # WHOLE MACHINE -- every lane on it acts as the bot and is bound by the builder guard --
        # and install-cli runs on the operator's own laptop as readily as on a builder box. Writing
        # a live export here would convert a human's machine into a builder-only one silently, the
        # single failure mode this whole surface is built to make impossible. Offering the line is
        # what makes the machine-wide option DISCOVERABLE; uncommenting it is the operator's act.
        "# Uncomment on a BUILDER-ONLY machine to make every lane on it a builder lane.",
        "# Humans must leave this commented. See docs/builder-lanes.md.",
        f"# export {_builder_contract().ROLE_ENV}={_builder_contract().ROLE_BUILDER}",
    ]
    if update_policy == "pinned" and install_head and install_head != "unavailable":
        env_lines.append(f"export {METHODOLOGY_UPDATE_PINS_ENV}={shlex.quote(pins_value)}")
        env_lines.append(f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={shlex.quote(pins_value)}")
    if preserved_exports:
        env_lines.extend(["", "# Preserved local user/project environment. Do not commit these values.", *preserved_exports])
    env_lines.append("")
    config_env.write_text("\n".join(env_lines), encoding="utf-8")
    try:
        config_env.chmod(0o600)  # sec-secrets-2: never leave webhook secrets world-readable
    except OSError:
        pass
    # Compatibility mirror: pre-0.9.2 launchers/hooks hardcode the legacy path; keep it identical
    # until METH-FU-TAUTLINE-FALLBACK-REMOVAL deletes it. Only mirrored for the default location.
    if config_env == default_config_env:
        LEGACY_USER_CONFIG_ENV.parent.mkdir(parents=True, exist_ok=True)
        try:
            LEGACY_USER_CONFIG_ENV.parent.chmod(0o700)
        except OSError:
            pass
        LEGACY_USER_CONFIG_ENV.write_text("\n".join(env_lines), encoding="utf-8")
        try:
            LEGACY_USER_CONFIG_ENV.chmod(0o600)
        except OSError:
            pass

    shim_content = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            # (0) The rollback lever, ABOVE every snapshot exec path. Live env only, exactly as
            # documented (release-engineering.md#rollback): the config env file must never be able
            # to redirect execution, and this is the one switch an operator reaches for when the
            # store has published a bad snapshot.
            'LIVE_SNAPSHOT_DISABLED="${TAUTLINE_METHODOLOGY_DISABLE_SNAPSHOT_EXEC:-${MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC:-}}"',
            # (i) Before anything else, both live-env-only exec checks.
            # The session-sticky exec root: a launcher (or a post-update re-exec) resolved ONE
            # snapshot for this session's life and exported it, so every hook subprocess executes
            # that same tree even after another lane swaps `current`. A pruned root simply fails
            # the -x test and we degrade to `current` below -- a version hop, never a breakage.
            'TL_EXEC_ROOT="${MINERVIT_METHODOLOGY_EXEC_ROOT:-}"',
            # ...but an exported root is still a SNAPSHOT root, so the lever has to strip it before
            # it is honoured. Checked here, not further down: a session (or any child of one) that
            # already carries an exec root would otherwise exec straight back into the very snapshot
            # the operator set the lever to escape, and re-export the root on the way, holding the
            # whole process tree inside the store. Unset, not just blanked, so children see it gone.
            'if [ "$LIVE_SNAPSHOT_DISABLED" = "1" ]; then',
            '  TL_EXEC_ROOT=""',
            "  unset MINERVIT_METHODOLOGY_EXEC_ROOT || true",
            "fi",
            'if [ -n "$TL_EXEC_ROOT" ] && [ -x "$TL_EXEC_ROOT/bin/tautline" ]; then',
            '  exec "$TL_EXEC_ROOT/bin/tautline" "$@"',
            "fi",
            # Deliberate dev exec-redirection. This is what MINERVIT_METHODOLOGY_REPO used to do by
            # accident: it is EXPORTED by every v1 launcher, so honoring it as an exec override
            # would send stale-v1 hook sessions to the mutable canonical checkout -- the exact
            # hazard the snapshot store removes. Redirection now needs this explicit variable,
            # which no launcher exports and which install-cli never writes to methodology.env.
            # Checked before sourcing: sec-trust-exec-3 (a file must never redirect execution).
            'TL_EXEC_OVERRIDE="${MINERVIT_METHODOLOGY_EXEC_OVERRIDE:-}"',
            'if [ -n "$TL_EXEC_OVERRIDE" ] && [ -x "$TL_EXEC_OVERRIDE/bin/tautline" ]; then',
            '  exec "$TL_EXEC_OVERRIDE/bin/tautline" "$@"',
            "fi",
            f"CONFIG_ENV={shlex.quote(str(config_env))}",
            'MINERVIT_METHODOLOGY_REPO_PRESET="${TAUTLINE_METHODOLOGY_REPO:-${MINERVIT_METHODOLOGY_REPO:-}}"',
            'MINERVIT_METHODOLOGY_REPO_ENV=""',
            # (ii) Capture the LIVE store setting BEFORE sourcing: afterwards the shell cannot
            # tell an operator override from a file-sourced value, and sec-trust-exec-3 requires
            # live env to beat every file-based source (a stale file TAUTLINE_ alias must never
            # shadow a live MINERVIT_ override). LIVE_SNAPSHOT_DISABLED is captured at (0) for the
            # same reason -- it has to be known before the exec-root fast path above.
            'LIVE_SNAPSHOT_STORE="${TAUTLINE_METHODOLOGY_SNAPSHOT_STORE:-${MINERVIT_METHODOLOGY_SNAPSHOT_STORE:-}}"',
            f"BAKED_SNAPSHOT_STORE={shlex.quote(str(store_root))}",
            # methodology.env sources the user's private secrets file; an unset-variable
            # reference there must degrade to missing config, not kill every CLI run in
            # minimal environments (cron, hooks, CI) via this shim's set -eu.
            'if [ -f "$CONFIG_ENV" ]; then',
            "  set +eu",
            '  . "$CONFIG_ENV"',
            "  set -eu",
            '  MINERVIT_METHODOLOGY_REPO_ENV="${TAUTLINE_METHODOLOGY_REPO:-${MINERVIT_METHODOLOGY_REPO:-}}"',
            'elif [ -f "$HOME/.config/minervit/methodology.env" ]; then',
            "  set +eu",
            '  . "$HOME/.config/minervit/methodology.env"',
            "  set -eu",
            '  MINERVIT_METHODOLOGY_REPO_ENV="${MINERVIT_METHODOLOGY_REPO:-}"',
            "fi",
            "resolve_minervit_methodology_repo() {",
            "  # sec-trust-exec-3: prefer operator-controlled sources (live env preset, then the",
            "  # methodology.env value) over cwd discovery, which an attacker could hijack by planting",
            "  # a minervit-ai-delivery-methodology directory in an ancestor of the working directory.",
            '  if [ -n "$MINERVIT_METHODOLOGY_REPO_PRESET" ] && { [ -x "$MINERVIT_METHODOLOGY_REPO_PRESET/bin/tautline" ] || [ -x "$MINERVIT_METHODOLOGY_REPO_PRESET/bin/minervit-methodology" ]; }; then',
            '    printf "%s\\n" "$MINERVIT_METHODOLOGY_REPO_PRESET"',
            "    return 0",
            "  fi",
            '  if [ -n "$MINERVIT_METHODOLOGY_REPO_ENV" ] && { [ -x "$MINERVIT_METHODOLOGY_REPO_ENV/bin/tautline" ] || [ -x "$MINERVIT_METHODOLOGY_REPO_ENV/bin/minervit-methodology" ]; }; then',
            '    printf "%s\\n" "$MINERVIT_METHODOLOGY_REPO_ENV"',
            "    return 0",
            "  fi",
            '  search_dir="$(pwd -P 2>/dev/null || pwd)"',
            '  while [ -n "$search_dir" ]; do',
            '    candidate="$search_dir/tautline"',
            '    if [ ! -x "$candidate/bin/tautline" ] && [ ! -x "$candidate/bin/minervit-methodology" ]; then',
            '      candidate="$search_dir/minervit-ai-delivery-methodology"',
            "    fi",
            '    if [ -x "$candidate/bin/tautline" ] || [ -x "$candidate/bin/minervit-methodology" ]; then',
            '      printf "%s\\n" "minervit-methodology: WARNING resolved via cwd discovery ($candidate); set MINERVIT_METHODOLOGY_REPO to a trusted checkout to avoid adopting an untrusted directory." >&2',
            '      printf "%s\\n" "$candidate"',
            "      return 0",
            "    fi",
            '    [ "$search_dir" != "/" ] || break',
            '    next_dir="$(dirname "$search_dir")"',
            '    [ "$next_dir" != "$search_dir" ] || break',
            '    search_dir="$next_dir"',
            "  done",
            f"  printf '%s\\n' {shlex.quote(str(canonical))}",
            "}",
            # MINERVIT_METHODOLOGY_REPO keeps its ONE remaining meaning: the canonical checkout
            # sync manages. Still resolved, still exported -- Python reads it to find the repo it
            # fetches/merges/archives. It is simply no longer an exec target ahead of the store.
            'MINERVIT_METHODOLOGY_REPO="$(resolve_minervit_methodology_repo)"',
            "export MINERVIT_METHODOLOGY_REPO",
            'TAUTLINE_METHODOLOGY_REPO="$MINERVIT_METHODOLOGY_REPO"',
            "export TAUTLINE_METHODOLOGY_REPO",
            # (iii) Store resolution AFTER sourcing (methodology.env may set the store), with the
            # live values captured above still winning. TAUTLINE_ first, matching resolve_env.
            'SNAPSHOT_STORE="${LIVE_SNAPSHOT_STORE:-${TAUTLINE_METHODOLOGY_SNAPSHOT_STORE:-${MINERVIT_METHODOLOGY_SNAPSHOT_STORE:-$BAKED_SNAPSHOT_STORE}}}"',
            'SNAPSHOT_DISABLED="${LIVE_SNAPSHOT_DISABLED:-${TAUTLINE_METHODOLOGY_DISABLE_SNAPSHOT_EXEC:-${MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC:-0}}}"',
            'SNAPSHOT_CURRENT="$SNAPSHOT_STORE/current"',
            'if [ "$SNAPSHOT_DISABLED" != "1" ] && [ -x "$SNAPSHOT_CURRENT/bin/tautline" ]; then',
            # pwd -P, not the symlink path: children must inherit the RESOLVED snapshot, or a
            # concurrent swap of `current` would silently move them to another version.
            '  MINERVIT_METHODOLOGY_EXEC_ROOT="$(cd "$SNAPSHOT_CURRENT" 2>/dev/null && pwd -P || true)"',
            '  if [ -n "$MINERVIT_METHODOLOGY_EXEC_ROOT" ]; then',
            "    export MINERVIT_METHODOLOGY_EXEC_ROOT",
            '    exec "$MINERVIT_METHODOLOGY_EXEC_ROOT/bin/tautline" "$@"',
            "  fi",
            'elif [ "$SNAPSHOT_DISABLED" != "1" ]; then',
            # No store-dir-exists condition on purpose: a post-cutover shim whose `current` is not
            # executable -- including a store deleted outright -- must warn and fall through to the
            # canonical checkout. A pre-cutover shim never carries this block, so nothing warns
            # before the machine is converted.
            "  SNAPSHOT_WARN='minervit-methodology: snapshot store current link'",
            '  SNAPSHOT_WARN="$SNAPSHOT_WARN missing or broken; executing canonical checkout"',
            "  SNAPSHOT_WARN=\"$SNAPSHOT_WARN (run 'tautline sync-methodology' to rebuild)\"",
            "  printf '%s\\n' \"$SNAPSHOT_WARN\" >&2",
            "fi",
            'if [ -x "$MINERVIT_METHODOLOGY_REPO/bin/tautline" ]; then',
            '  exec "$MINERVIT_METHODOLOGY_REPO/bin/tautline" "$@"',
            "fi",
            'exec "$MINERVIT_METHODOLOGY_REPO/bin/minervit-methodology" "$@"',
            "",
        ]
    )
    write_text_executable(shim, shim_content)
    write_text_executable(legacy_shim, shim_content)
    # The shims now execute `<store>/current`, so the store must exist before the next command
    # runs. Best-effort by construction: a store we cannot build degrades to "the shim warns and
    # executes the canonical checkout", which is exactly the pre-cutover behavior, so a broken
    # store must never fail the install that would let sync-methodology rebuild it.
    snapshot_dir, snapshot_detail = materialize_methodology_snapshot(canonical, "HEAD", "stable")
    if snapshot_dir is None:
        print(f"methodology_snapshot: unavailable - {snapshot_detail}", file=sys.stderr)
    else:
        swapped, swap_detail = swap_methodology_snapshot_current(snapshot_dir)
        if not swapped:
            print(f"methodology_snapshot: unavailable - {swap_detail}", file=sys.stderr)
            snapshot_dir = None
    settings_path, settings_ok = write_claude_autocompact_settings(
        Path.home() / ".claude" / "settings.json"
    )
    release_guard = install_methodology_release_guards()

    print(f"installed_cli: {shim}")
    print(f"installed_cli_legacy_alias: {legacy_shim}")
    print(f"methodology_env: {config_env}")
    print(f"methodology_repo: {canonical}")
    print(f"methodology_snapshot_store: {store_root}")
    if snapshot_dir is None:
        print(
            "methodology_snapshot: unavailable - shims will execute the canonical checkout "
            "until `tautline sync-methodology` rebuilds the store"
        )
    else:
        print(f"methodology_snapshot: {snapshot_detail}")
        print(f"methodology_snapshot_current: {store_root / 'current'} -> {snapshot_dir.name}")
    if update_policy == "pinned":
        print(f"update_policy: pinned at {install_head[:12]} (advance by setting `_framework.version` after reviewing upstream)")
    else:
        print(f"update_policy: {update_policy}")
    print(f"methodology_release_guard: {release_guard}")
    print(f"claude_autocompact_settings: {'already ok' if settings_ok else 'installed'} {settings_path}")
    print(f"shell_setup: source {config_env}")
    # LAST, and on both streams: this install just opened the unpinned-launcher window, and an
    # operator who stops reading here starts version-hopping sessions without ever being told.
    # Unconditional -- install-cli ALWAYS opens the window, whether or not a launcher exists yet.
    # CONDITIONAL now, and that is the fix. This used to print unconditionally, so the very first
    # command in the README Quickstart ended by telling every new user, in the loudest formatting
    # the CLI has, to run `install-claude-launcher --force` -- a verb this release deletes. The
    # window is real only when a pre-cutover launcher actually exists, so the warning fires then.
    stale = stale_claude_launchers(bin_dir, USER_BIN_DIR)
    if stale:
        for line in launcher_cutover_warning_lines(stale):
            print(line, file=sys.stderr)
        print(f"next_step_required: {LAUNCHER_CUTOVER_REMEDY}")
    return 0


def uninstall_cli(args: argparse.Namespace) -> int:
    """prod-onboarding-4: reverse install-cli (remove the CLI shim and methodology.env).

    The autocompact settings written into ~/.claude/settings.json and any installed git pre-push
    hook are intentionally NOT auto-reverted (they may be hand-edited / shared); they are reported so
    the operator can remove them deliberately.
    """
    bin_dir = args.bin_dir.expanduser().resolve()
    config_env = (args.config_env or resolve_user_config_env()).expanduser().resolve()
    shim = bin_dir / CLI_NAME
    legacy_shim = bin_dir / LEGACY_CLI_NAME
    dry_run = getattr(args, "dry_run", False)
    removed: list[str] = []
    keep_env = getattr(args, "keep_env", False)
    removal_targets = [(shim, False), (legacy_shim, False), (config_env, keep_env)]
    # A default install writes BOTH config surfaces (tautline.env + the legacy mirror, which can
    # hold preserved secrets); a default uninstall must reverse both (Codex 0.9.2 R1 P2).
    if config_env == USER_CONFIG_ENV.expanduser().resolve(strict=False) and LEGACY_USER_CONFIG_ENV.expanduser().resolve(strict=False) != config_env:
        removal_targets.append((LEGACY_USER_CONFIG_ENV, keep_env))
    for path, keep in removal_targets:
        if keep:
            print(f"uninstall_cli: keeping {path}")
            continue
        if path.exists() or path.is_symlink():
            if dry_run:
                print(f"uninstall_cli_dry_run: would remove {path}")
            else:
                path.unlink()
                removed.append(str(path))
    store = methodology_snapshot_store_root()
    if not dry_run:
        for entry in removed:
            print(f"uninstall_cli_removed: {entry}")
        if not removed:
            print("uninstall_cli: nothing to remove (already uninstalled)")
        print(
            "uninstall_cli_note: ~/.claude/settings.json autocompact settings and any installed git "
            "pre-push hook were left in place; remove them manually if desired."
        )
        # A live session may still be executing a snapshot out of this store, so uninstall never
        # deletes it. The removal command is spelled out because a published snapshot is 0555/0444
        # by design: a bare `rm -rf` is DENIED, and an operator handed one would think it failed.
        print(
            f"uninstall_cli_note: the snapshot store at {store} was RETAINED (sessions may still "
            f"be executing it); remove it with: chmod -R u+w {store} && rm -rf {store}"
        )
    else:
        print(f"uninstall_cli_dry_run: would retain the snapshot store at {store}")
    return 0


def sync_methodology(args: argparse.Namespace) -> int:
    """Sync the methodology checkout; under --launcher-gate, do it once per freshness window.

    The gate wraps the ENTIRE body -- update, guards, heal, stamp, pin -- because every one of
    those touches state shared by all lanes on this machine.
    """
    if maintainer_mode_armed():
        # BEFORE the launcher-gate skip check, so EVERY launch shows it -- the mode must never
        # be ambient (and the armed path never takes that skip anyway, per the MS-R1-P1-1 guard
        # below). stderr, like the cutover banner: loud advisories go to stderr while the
        # machine-readable stdout report keeps its stock shape.
        for line in maintainer_mode_banner_lines():
            print(line, file=sys.stderr)
    elif maintainer_mode_configured():
        # The key is set but there is nothing to manage: say so once, then proceed stock -- a
        # silently-inert key would leave the operator believing the machine is armed.
        print(maintainer_mode_status_line(), file=sys.stderr)
    # Every sync is a lane start, so this is where the half-converted machine is observable: the
    # store is enabled (install-cli ran) but a pre-cutover launcher is still starting sessions
    # that are UNPINNED against `current`. Warn on every sync until the operator closes it.
    if methodology_snapshot_store_enabled():
        warn_unpinned_launcher_window(USER_BIN_DIR)
    # The recorded-launcher check catches what the USER_BIN_DIR scan above cannot: a launcher the
    # operator installed with --bin-dir somewhere else, and -- via the deliberate None/[] split --
    # a machine whose launchers all predate the recorder entirely.
    launcher_status = launcher_template_status_line()
    if launcher_status:
        print(launcher_status)
    # RCA 2026-07-22 controls 2 and 4, both on the launch path because a launch is the only
    # surface the operator reliably sees. Neither can fail a sync: they report a machine-state
    # drift the operator has to decide about, and a gate that refuses here would be a second way
    # to be blocked at startup -- the exact failure this RCA exists to end.
    ensure_maintainer_mode_arm_marker()
    for line in maintainer_mode_standdown_loss_lines():
        print(line, file=sys.stderr)
    for line in launcher_divergence_lines(diverged_installed_launchers()):
        print(line, file=sys.stderr)
    if not getattr(args, "launcher_gate", False):
        return _sync_methodology_body(args)[0]
    lane = Path(getattr(args, "target", None) or ".").expanduser().resolve(strict=False)
    with launcher_sync_gate():
        # The freshness skip exists to avoid the expensive network sync; the ARMED body is offline
        # and cheap, and taking the skip would bypass heal -- a commit landed inside the freshness
        # window would miss the next launch (MS-R1-P1-1). So an armed launch always runs the full
        # standdown body. The stamp is still WRITTEN below when armed, so `maintainer-mode off`
        # leaves stock skip behavior exactly as a stock sync would have left it.
        skip = None if maintainer_mode_armed() else launcher_gate_skip_reason()
        if skip is not None:
            print(f"methodology_update: skipped - {skip}")
            print(f"plugin_version: {plugin_version()}")
            print(f"methodology_commit: {running_methodology_commit(short=True)}")
            print(methodology_canonical_commit_line())
            print(methodology_exec_root_line())
            if not args.no_remote:
                print(f"remote_status: {remote_methodology_status(False)}")
            # Still a live lane start: the pin is a heartbeat, and skipping the sync must not let
            # prune collect the snapshot this session is about to execute.
            refresh_methodology_snapshot_pin(lane)
            return 0
        code, status = _sync_methodology_body(args)
        if status is not None and status != "failed" and not running_from_installed_package():
            # A failed sync must never tell the next lane the methodology is fresh. Neither must a
            # framework-pin refusal (status None): that path never touched the methodology repo at
            # all, and stamping it would let one lane's WIP hold starve every other lane's sync.
            # A package install (PP-R1-P1-1 extension) never stamps either: it would record the
            # LEFTOVER checkout's head as freshly synced (package sync never touches it), and the
            # skip that stamp buys would hide the pipx/pip update hint behind "synced Ns ago by
            # another lane". The gated body is offline and cheap in package mode, so losing the
            # skip costs nothing and keeps gated output deterministic.
            current = methodology_snapshot_current_dir()
            write_methodology_sync_stamp(
                run_git(canonical_methodology_repo(), ["rev-parse", "HEAD"]),
                current.name if current else "",
                status,
            )
        refresh_methodology_snapshot_pin(lane)
        return code


def _sync_methodology_body(args: argparse.Namespace) -> tuple[int, str | None]:
    """The sync itself. Returns the exit code and the update status.

    The status is None when the framework pin declined the update before the methodology repo was
    touched at all -- the caller must not stamp that as a sync.
    """
    framework_pin = normalize_framework_pin(None)
    if getattr(args, "target", None) is not None:
        data, _project_path, target = lane_project(args)
        framework_pin, framework_pin_source = effective_framework_pin(data, target)
        framework_decision = framework_update_decision(
            framework_pin,
            data,
            target,
            args.skip_update,
            manual_request=True,
        )
        # Display-only discovery: no launch fetch (allow_fetch=False); a full standdown under
        # --no-remote. The manual path proceeds as the update (no offer); only genuine skip branches
        # below carry an offer, and they reuse this probe for the remote_status line.
        framework_probe = framework_update_probe(
            target, data, framework_pin, allow_fetch=False, no_remote=args.no_remote
        )
        print(framework_pin_status_line(framework_pin, framework_pin_source))
        print(framework_update_available_line(framework_decision, framework_probe))
        for reason in framework_decision.get("wipReasons", []):
            print(f"framework_wip: {reason}")
        if framework_decision["action"] != "update":
            print(f"methodology_update: skipped - {framework_decision['reason']}")
            print(f"plugin_version: {plugin_version()}")
            print(f"methodology_commit: {running_methodology_commit(short=True)}")
            print(methodology_canonical_commit_line())
            print(methodology_exec_root_line())
            if not args.no_remote:
                if maintainer_mode_armed():
                    # Remote-probe standdown -- same rationale as the sync tail below.
                    print("remote_status: skipped - maintainer mode")
                else:
                    remote_line = framework_remote_status_from_probe(framework_probe)
                    if remote_line is None:
                        remote_line = remote_methodology_status(False)
                    print(f"remote_status: {remote_line}")
            for offer_line in framework_update_offer_lines(
                framework_decision, framework_probe, framework_pin
            ):
                print(offer_line)
            return 0, None
    explicit_auto_rescue = getattr(args, "auto_rescue_local_changes", False)
    default_auto_rescue = False
    if not getattr(args, "no_auto_rescue_local_changes", False):
        default_auto_rescue = should_auto_rescue_methodology_for_project_startup()
    auto_rescue = explicit_auto_rescue or default_auto_rescue
    status, detail = update_methodology_repo(
        args.skip_update,
        getattr(args, "allow_non_main", False),
        auto_rescue,
        auto_rescue_stale_only=default_auto_rescue and not explicit_auto_rescue,
        channel=framework_pin["channel"],
    )
    print(f"methodology_update: {status} - {detail}")
    if status == "held":
        # The hold detail printed above carries the ACTIVE policy's remedy (pinned -> update-repin,
        # signed -> signature repair); do not restate a policy-specific command here (Codex R2 P2).
        print(
            "methodology_update_held: launch continues on the trusted retained checkout; "
            "to advance, follow the remedy in the hold message above"
        )
    if status != "failed":
        # A trust-gated advance never returns here (it re-execs), so reaching this line means no
        # advance happened this run -- exactly when a missing/dangling `current` would otherwise
        # persist until the next upstream commit. Bootstrap and self-repair both land here.
        heal_methodology_snapshot_current(framework_pin["channel"])
    print(f"plugin_version: {plugin_version()}")
    print(f"methodology_commit: {running_methodology_commit(short=True)}")
    # sync mutates the CANONICAL checkout while this process keeps running the snapshot it was
    # launched from: report both, or an advance looks like a no-op until the next launch swaps in.
    print(methodology_canonical_commit_line())
    print(methodology_exec_root_line())
    if status != "failed":
        print(f"methodology_release_guard: {install_methodology_release_guards()}")
    if not args.no_remote:
        if maintainer_mode_armed():
            # Launch-time remote-probe standdown: a launch must not depend on the network while
            # update gates are off (the probe ls-remotes the origin), and the literal line keeps
            # armed output deterministic. The launcher-gate stamp-skip branch needs no probe
            # treatment -- it is unreachable when armed (sync_methodology's MS-R1-P1-1 guard).
            print("remote_status: skipped - maintainer mode")
        else:
            print(f"remote_status: {remote_methodology_status(False)}")
    return (0 if status != "failed" else 1), status


def deprecated_alias_notice(old: str, new: str) -> str:
    """The deprecation line shown by `<old> --help` and printed when `<old>` actually runs.

    IN THE PARSER, not only at dispatch. argparse handles `--help` with an action that prints
    and exits DURING parsing, so a warning emitted from the handler never runs on the one path
    a user takes to discover the command.
    """
    return (
        f"DEPRECATED: `{old}` is the vendor-named alias of `{new}` and is removed at 1.0.0. "
        f"It behaves identically; switch to `{new}`."
    )


def event_repo_slug(data: dict) -> str:
    repo = str(data.get("repo") or data.get("project") or "repo")
    return slugify(repo, fallback="repo")


def observability_event_paths(data: dict, target: Path) -> tuple[Path, Path, Path]:
    observability = data["observabilityEvents"]
    directory = observability_state_dir(data) / event_repo_slug(data)
    human = directory / observability["humanLog"]
    jsonl = directory / observability["jsonlLog"]
    lock = directory / ".events.lock"
    return human, jsonl, lock


def user_config_env_value(name: str, config_env: Path | None = None) -> str:
    """Read one simple NAME=value entry from the installed config env without sourcing shell."""
    config_env = config_env or resolve_user_config_env()
    return util_module().user_config_env_value(name, config_env)


def release_update_public_release_issues(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    return release_update_call("release_update_public_release_issues", repo_root)


def normalize_event_text(data: dict, target: Path, text: str) -> str:
    normalized = str(text).replace("\n", " ").strip()
    # Both methodology roots and the snapshot store are redacted to one token. Post-cutover, paths
    # that used to be REPO_ROOT surface in three shapes -- the canonical checkout, the snapshot exec
    # root, and sibling snapshots under the store -- and a redactor that only knew the exec root
    # would leak the operator's machine layout into published event text.
    # ORDER IS LOAD-BEARING: the exec root lives INSIDE the store, so the longest, most specific
    # path must be replaced before its parent (replacing the store first would leave
    # "<methodology_repo>/<sha12>" and the exec-root rule could never match).
    replacements = [
        (str(target), "."),
        (str(REPO_ROOT), "<methodology_repo>"),
        (str(canonical_methodology_repo()), "<methodology_repo>"),
        (str(methodology_snapshot_store_root()), "<methodology_repo>"),
        (str(Path.home()), "$HOME"),
        (str(observability_state_dir(data)), "<event_state>"),
    ]
    for needle, replacement in replacements:
        if needle:
            normalized = normalized.replace(needle, replacement)
    normalized = re.sub(r"/Users/[^/\s`]+", "$HOME", normalized)
    normalized = re.sub(r"/private/var/folders/[^\s`]+", "<local-temp>", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def validate_event_value(value: str, field: str) -> list[str]:
    errors: list[str] = []
    if not value.strip():
        errors.append(f"{field} must be non-blank")
    if len(value) > EVENT_MAX_FIELD_CHARS:
        errors.append(f"{field} exceeds {EVENT_MAX_FIELD_CHARS} characters")
    for pattern in SESSION_JOURNAL_SECRET_PATTERNS:
        if re.search(pattern, value):
            errors.append(f"{field} contains a secret-looking value")
            break
    return errors


def build_event_payload(
    data: dict,
    target: Path,
    *,
    event: str,
    severity: str,
    plain: str,
    next_action: str,
    refs: dict | None = None,
    goal: str | None = None,
    milestone: str | None = None,
    pr: str | None = None,
) -> dict:
    event = slugify(event, fallback="event").replace("-", "_")
    severity = severity.lower().strip()
    if severity not in EVENT_SEVERITIES:
        raise SystemExit(f"severity must be one of: {', '.join(sorted(EVENT_SEVERITIES))}")
    plain = normalize_event_text(data, target, plain)
    next_action = normalize_event_text(data, target, next_action)
    errors = validate_event_value(plain, "plain") + validate_event_value(next_action, "next")
    if errors:
        raise SystemExit("; ".join(errors))
    payload = {
        "schema": EVENT_LOG_SCHEMA,
        "ts": utc_event_timestamp(),
        "project": data.get("project"),
        "repo": data.get("repo"),
        "repo_slug": event_repo_slug(data),
        "lane": target.name,
        "branch": run_git(target, ["branch", "--show-current"]),
        "head": run_git(target, ["rev-parse", "--short", "HEAD"]),
        "goal": normalize_event_text(data, target, goal or ""),
        "milestone": normalize_event_text(data, target, milestone or ""),
        "pr": normalize_event_text(data, target, pr or ""),
        "event": event,
        "severity": severity,
        "plain": plain,
        "next": next_action,
        "refs": refs or {},
        "methodology": {
            "plugin_version": plugin_version(),
            "methodology_commit": running_methodology_commit(short=True),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded) > EVENT_MAX_JSON_CHARS:
        raise SystemExit(f"event payload exceeds {EVENT_MAX_JSON_CHARS} bytes")
    return payload


def append_event_payload(
    data: dict, target: Path, payload: dict, *, bypass_enabled_gate: bool = False
) -> tuple[Path, Path]:
    # bypass_enabled_gate skips ONLY the enabled check, so the operator's decision ledger
    # (decision_record, the sole True caller -- pinned by test_bypass_gate_sole_callsite) works on a
    # disabled-narration lane. Locking, rotation, size limits, and in-lock lane_id/seq stamping are
    # untouched; every ordinary producer keeps the default False and stays gated by the toggle.
    if not bypass_enabled_gate and not data["observabilityEvents"].get("enabled", True):
        raise SystemExit("observability events are disabled by adapter")
    human, jsonl, lock = observability_event_paths(data, target)
    human.parent.mkdir(parents=True, exist_ok=True)
    secure_event_log_paths(human, jsonl, lock)
    with lock.open("a", encoding="utf-8") as lock_file, advisory_flock(lock_file):
        # T2: lane_id + seq are allocated INSIDE this same lock so two simultaneous
        # try_write_event calls for this lane can never duplicate or skip a seq (see the T2
        # comment above allocate_instrumentation_seq()).
        lane_id = instrumentation_lane_id(target)
        payload["lane_id"] = lane_id
        rotate_bytes = int(data["observabilityEvents"]["rotateBytes"])
        retained = int(data["observabilityEvents"]["retainedRotations"])
        payload["seq"] = allocate_instrumentation_seq(
            lane_id, str(payload["ts"]), jsonl_path=jsonl, retained_rotations=retained
        )
        rotate_event_file(human, rotate_bytes, retained)
        rotate_event_file(jsonl, rotate_bytes, retained)
        line = event_human_line(payload)
        with jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        with human.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        # Re-apply owner-only mode after creating files this call (open("a") creates 0644 under the
        # default umask); the 0700 dir already blocks others, this closes the file-mode window too.
        secure_event_log_paths(human, jsonl, lock)
    return human, jsonl


def write_event(
    data: dict,
    target: Path,
    *,
    event: str,
    severity: str,
    plain: str,
    next_action: str,
    refs: dict | None = None,
    goal: str | None = None,
    milestone: str | None = None,
    pr: str | None = None,
) -> tuple[Path, Path]:
    payload = build_event_payload(
        data,
        target,
        event=event,
        severity=severity,
        plain=plain,
        next_action=next_action,
        refs=refs,
        goal=goal,
        milestone=milestone,
        pr=pr,
    )
    return append_event_payload(data, target, payload)


def try_write_event(data: dict, target: Path, **kwargs: object) -> None:
    if not data.get("observabilityEvents", {}).get("enabled", True):
        return
    try:
        write_event(data, target, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        print(f"event_log_warning: {exc}")


def decision_record(args: argparse.Namespace) -> int:
    """`decision-record`: the fail-closed, machine-local structured decision ledger writer the
    standing autonomy directive instructs agents to use. Composes build_event_payload +
    append_event_payload (same events.jsonl, locking, in-lock lane_id/seq stamping) so a recorded
    decision survives even on a disabled-narration lane -- the toggle governs observability, not the
    operator's review ledger. Every non-empty stored field is sanitized + validated BEFORE any
    write; a malformed record is a loud error, never a silent drop."""
    data, _project_path, target = lane_project(args, lean_ok=True)
    # 1.x lanes only: lean lanes have no laneState scratch tree to materialize, and the ledger
    # state dir is created by the append primitive itself.
    if "laneState" in data:
        ensure_lane_state(data, target)

    # rationale is mandatory (the Unattended Operation policy this verb serves requires it on every
    # entry); --summary maps to `plain`, which build_event_payload validates fail-closed below.
    rationale = normalize_event_text(data, target, args.rationale)
    refs: dict[str, str] = {"reversibility": args.reversibility}
    errors = validate_event_value(rationale, "rationale")
    if errors:
        raise SystemExit("; ".join(errors))
    refs["rationale"] = rationale

    if args.alternatives:
        alternatives = normalize_event_text(data, target, args.alternatives)
        errors = validate_event_value(alternatives, "alternatives")
        if errors:
            raise SystemExit("; ".join(errors))
        refs["alternatives"] = alternatives

    surfaces: list[str] = []
    for raw in args.surface or []:
        surface = normalize_event_text(data, target, raw)
        errors = validate_event_value(surface, "surface")
        if errors:
            raise SystemExit("; ".join(errors))
        surfaces.append(surface)
    if surfaces:
        joined = ",".join(surfaces)
        errors = validate_event_value(joined, "surfaces")
        if errors:
            raise SystemExit("; ".join(errors))
        refs["surfaces"] = joined

    payload = build_event_payload(
        data,
        target,
        event="decision",
        severity="info",
        plain=args.summary,
        next_action=args.next,
        refs=refs,
        goal=args.goal,
        milestone=args.milestone,
        pr=args.pr,
    )
    # goal/milestone/pr are validated ONLY when non-empty: build_event_payload legitimately stores
    # empty strings on a lane with no flags and no active goal/milestone ledgers, and the DEFAULT
    # invocation must succeed there. The non-empty check covers BOTH author-supplied AND
    # state-DERIVED values (the goal-ledger loader accepts arbitrary goalId/sourceGoal strings, so a
    # derived goal is its own injection path).
    for field in ("goal", "milestone", "pr"):
        value = payload.get(field) or ""
        if value:
            errors = validate_event_value(value, field)
            if errors:
                raise SystemExit("; ".join(errors))

    # TOP-LEVEL discriminator (not a ref): free-form log-event refs pass through into
    # payload["refs"] only and can never set a top-level key, so this closes the "decision-NAMED
    # event mistaken for a ledger entry" forgery path with zero compatibility cost to the stable
    # --ref namespace. The sibling read surface keys on this field.
    payload["record_kind"] = "tautline-decision/v1"
    # Also top-level, also a discriminator, same reasoning: the AUTHORITATIVE pending signal
    # `inbox` reads (is_pending_decision) has to be structured, not text an agent could phrase a
    # dozen ways. A real bool, never absent-by-omission-vs-false ambiguity for JSON consumers.
    payload["awaiting_operator"] = bool(args.awaiting_operator)
    human, jsonl = append_event_payload(data, target, payload, bypass_enabled_gate=True)
    print(f"event_log: {human}")
    print(f"event_jsonl: {jsonl}")
    projected = validated_decision_projection(payload)
    if projected and is_pending_decision(projected[0]):
        from tautline_methodology import operator_inbox

        print(f"decision_id: {operator_inbox.decision_id(projected[0])}")
    return 0


# ---------------------------------------------------------------------------------------------
# Tier 1 salvage, Track S1 (ledger readers): decisions-report / event-tail / event-log-path /
# event-rotate / inbox. Salvaged from the pre-demolition tip (2c5b9a2c8) where the format still
# matches what decision_record ABOVE actually writes today -- same events.jsonl, same
# `record_kind: "tautline-decision/v1"` top-level discriminator, same `refs.rationale` /
# `refs.reversibility` shape. Every gate/sync/strict path the old handlers carried is gone: these
# are read-only (event-rotate excepted, and even that only renames two local files on request),
# on-demand, and never call each other in a loop. `inbox` is new; everything else is a close
# salvage extended with the two fields (`repo`, `next`) the old validator never carried through.
# ---------------------------------------------------------------------------------------------

DECISIONS_REPORT_SCHEMA = "tautline-decisions-report/v1"
INBOX_SCHEMA = "tautline-inbox/v1"
# Mirrors decision-record's own `--reversibility` choices (_register_events_1 above) as an
# independent constant rather than a shared import, so this read-only family never has to touch
# the writer's registration to add a value.
DECISION_REVERSIBILITY_ENUM = ("reversible", "hard-to-reverse")


def parse_duration_seconds(value: str) -> int:
    return util_module().parse_duration_seconds(value)


def parse_event_ts(value: str) -> datetime | None:
    return util_module().parse_event_ts(value)


def _aware_utc(dt: datetime) -> datetime:
    """Normalize a datetime to aware UTC so no aware/naive comparison can throw. Zone-less
    (naive) values are interpreted as UTC (the documented decisions-report bound contract)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _valid_capped_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= EVENT_MAX_FIELD_CHARS


def decision_shaped_record(record: object) -> bool:
    """Anything that looks like it MEANT to be a decision -- an `event == "decision"` row (incl. a
    free-form `log-event --event decision`) or a row carrying the top-level discriminator. Used to
    decide what belongs in the skipped diagnostic vs. an ordinary event that is simply ignored."""
    if not isinstance(record, dict):
        return False
    return record.get("event") == "decision" or record.get("record_kind") == "tautline-decision/v1"


def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]


def _ledger_safe(text: object, limit: int = 0) -> str:
    """Ledger text, made safe to PRINT. The ledger is machine-local, not remote, but
    normalize_event_text (the write-time pass in decision_record above) only collapses whitespace
    -- it does not strip control characters -- so a hand-edited or corrupted JSONL row can still
    smuggle an escape sequence into a summary/next field. Every ledger-sourced value that reaches
    a HUMAN-facing (non-JSON; JSON already escapes control bytes by construction) report goes
    through here first, mirroring backlog.py's `_safe` for remote text."""
    return util_module().flatten_printable(text, limit)


def validated_decision_projection(record: object) -> tuple[dict, datetime] | None:
    """Total, type-safe validator over every field a decisions-report/inbox row renders or
    computes with. Returns the CLOSED validated projection (absent optionals -> None) plus the
    parsed aware-UTC timestamp, or None for anything decision-shaped that is not a countable
    record (never crash, never leak the raw payload). Bools are rejected as `seq` (Python bools
    pass naive int checks).

    Extends the pre-demolition validator with `repo` and `next`: the old decisions-report table
    never showed either, so its projection never carried them through -- but inbox's pending
    heuristic reads `next` and inbox's "repo" column needs `repo`, so both are validated here
    rather than read unchecked at render time.

    Also validates the top-level `awaiting_operator` boolean (decision-record's `--awaiting-
    operator`; see is_pending_decision). ABSENT means "written before this field existed" and
    resolves to False -- every pre-existing record has no such key, and that must stay a
    countable, non-pending row rather than an invalid one. PRESENT-but-wrong-type invalidates the
    row like every other malformed field here: absence is legacy compatibility, corruption is not.
    """
    if not isinstance(record, dict):
        return None
    if record.get("event") != "decision":
        return None
    if record.get("record_kind") != "tautline-decision/v1":
        return None
    refs = record.get("refs")
    if not isinstance(refs, dict):
        return None
    plain = record.get("plain")
    if not _valid_capped_str(plain):
        return None
    next_step = record.get("next")
    if not _valid_capped_str(next_step):
        return None
    ts_raw = record.get("ts")
    if not isinstance(ts_raw, str):
        return None
    ts_dt = parse_event_ts(ts_raw)
    if ts_dt is None:
        return None
    seq = record.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0:
        return None
    lane_id = record.get("lane_id")
    if not isinstance(lane_id, str) or not lane_id.strip():
        return None
    lane = record.get("lane")
    if not _valid_capped_str(lane):
        return None
    rationale = refs.get("rationale")
    if not _valid_capped_str(rationale):
        return None
    reversibility = refs.get("reversibility")
    if reversibility not in DECISION_REVERSIBILITY_ENUM:
        return None
    awaiting_operator_raw = record.get("awaiting_operator")
    if awaiting_operator_raw is None:
        awaiting_operator = False  # legacy row, written before this field existed
    elif isinstance(awaiting_operator_raw, bool):
        awaiting_operator = awaiting_operator_raw
    else:
        return None
    optionals: dict[str, str | None] = {}
    for key, source in (
        ("alternatives", refs),
        ("surfaces", refs),
        ("goal", record),
        ("milestone", record),
        ("pr", record),
        ("repo", record),
    ):
        value = source.get(key)
        if value is None or value == "":
            optionals[key] = None  # empty string == absent, matching the writer's optional-finals
        elif isinstance(value, str) and value.strip() and len(value) <= EVENT_MAX_FIELD_CHARS:
            optionals[key] = value
        else:
            return None
    projection = {
        "ts": ts_raw,
        "lane": lane,
        "lane_id": lane_id,
        "seq": seq,
        "repo": optionals["repo"],
        "summary": plain,
        "rationale": rationale,
        "alternatives": optionals["alternatives"],
        "reversibility": reversibility,
        "surfaces": optionals["surfaces"],
        "goal": optionals["goal"],
        "milestone": optionals["milestone"],
        "pr": optionals["pr"],
        "next": next_step,
        "awaiting_operator": awaiting_operator,
    }
    return projection, _aware_utc(ts_dt)


def read_countable_decisions(
    pairs: list[tuple[dict, Path]],
) -> tuple[list[tuple[dict, datetime]], int, list[str]]:
    """Rotation-aware, lock-guarded read of countable decision records for the requested lanes.

    `pairs` are (adapter data, resolved lane target). Resolved JSONL paths are DEDUPED across
    targets (same-repo worktrees share one event log); each shared log is read once under its
    shared advisory lock and rows are attributed by `lane_id` to the requested set. Returns
    (projections-with-parsed-ts, skipped_lines, free-text warnings). A vanished path or a corrupt
    line is tolerated and counted skipped -- never crashed on, never leaked into output. Shared by
    both decisions-report and inbox.
    """
    entries: dict[str, dict] = {}
    for data, target in pairs:
        lane_id = instrumentation_lane_id(target)
        _human, jsonl, lock = observability_event_paths(data, target)
        retained = int(data["observabilityEvents"]["retainedRotations"])
        key = str(jsonl.resolve())
        entry = entries.get(key)
        if entry is None:
            entry = {"jsonl": jsonl, "lock": lock, "retained": retained, "lane_ids": set()}
            entries[key] = entry
        else:
            entry["retained"] = max(entry["retained"], retained)
        entry["lane_ids"].add(lane_id)
    results: list[tuple[dict, datetime]] = []
    skipped = 0
    warnings: list[str] = []
    for entry in entries.values():
        jsonl = entry["jsonl"]
        lock = entry["lock"]
        retained = entry["retained"]
        lane_ids = entry["lane_ids"]
        if not jsonl.parent.exists():
            continue
        seen: set[str] = set()
        try:
            with lock.open("a", encoding="utf-8") as lock_file, advisory_flock(lock_file):
                for path in event_jsonl_read_paths(jsonl, retained):
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        skipped += 1  # a rotation removed a path between enumeration and read
                        continue
                    for line in text.splitlines():
                        if not line.strip() or line in seen:
                            continue
                        seen.add(line)
                        try:
                            record = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            skipped += 1
                            warnings.append("ledger: skipped a corrupt (non-JSON) event log line")
                            continue
                        if not decision_shaped_record(record):
                            continue
                        projected = validated_decision_projection(record)
                        if projected is None:
                            # Attribute a malformed row by any READABLE lane_id: a decision-shaped
                            # row that clearly belongs to a NON-requested sibling lane is ignored
                            # (exactly as a VALID sibling row is), not counted into this report's
                            # scoped skipped diagnostic. Rows with no readable lane_id, or a
                            # requested lane's own malformed row, stay counted.
                            row_lane = record.get("lane_id")
                            if (
                                isinstance(row_lane, str)
                                and row_lane.strip()
                                and row_lane not in lane_ids
                            ):
                                continue
                            skipped += 1  # decision-shaped but not a countable record
                            continue
                        projection, ts_dt = projected
                        if projection["lane_id"] in lane_ids:
                            results.append((projection, ts_dt))
        except OSError as exc:
            # Same honesty as the inner per-line handler above: a whole source failing to open
            # (permission denied, removed mid-read, ...) must not vanish silently -- it is one
            # skipped unit with a printed reason, not zero evidence that anything went wrong.
            skipped += 1
            warnings.append(f"ledger: could not read {jsonl} ({exc})")
            continue
    return results, skipped, warnings


def ledger_target_data(target: Path) -> dict:
    """Load a target's GENERATED lane adapter directly (cheap, no git validation) -- the
    decisions-report/inbox read surfaces are read-only and multi-target, so each needs only the
    merged observabilityEvents config and the resolved path."""
    marker = adapter_marker_path(target)
    if not marker.exists():
        raise SystemExit(no_adapter_message_for(target))
    lean_cfg = lean.load_lean_config(marker)  # --- LEAN PROFILE WIRING ---
    if lean_cfg is not None:
        return lean_lane_data(lean_cfg)
    return load_project(marker)


def parse_report_since(value: str) -> datetime:
    """`--since`: a duration (30m, 24h, 7d) counted back from now, or an ISO-8601 timestamp.
    Zone-less ISO values are treated as UTC."""
    if re.fullmatch(r"\s*\d+\s*[smhdw]?\s*", value or ""):
        cutoff = datetime.now(timezone.utc).timestamp() - parse_duration_seconds(value)
        return datetime.fromtimestamp(cutoff, tz=timezone.utc)
    dt = parse_event_ts(value)
    if dt is None:
        raise SystemExit("--since must be a duration such as 30m/24h/7d or an ISO-8601 timestamp")
    return _aware_utc(dt)


def parse_report_until(value: str) -> datetime:
    """`--until`: an ISO-8601 timestamp (inclusive). Zone-less values are treated as UTC."""
    dt = parse_event_ts(value)
    if dt is None:
        raise SystemExit("--until must be an ISO-8601 timestamp")
    return _aware_utc(dt)


def _decision_repo_label(projection: dict) -> str:
    return projection.get("repo") or projection.get("lane") or projection["lane_id"][:12]


def _safe_ts_display(ts_dt: datetime) -> str:
    """Render a VALIDATED, PARSED timestamp for a human-facing table -- never the raw ledger
    string. `datetime.fromisoformat` (3.11+) accepts almost any single byte as the date/time
    separator, so a `ts` field carrying a control character (e.g. ESC in place of "T") still
    parses and validates; printing `ts_raw` directly would then inject that byte into the
    terminal. Re-deriving the display string from the parsed datetime's own components is
    airtight -- `isoformat()` can only ever emit digits, "-", ":", ".", "T", "+"/"-" -- which
    string sanitization (_ledger_safe) is not: that is a defense against what SURVIVES; this is a
    guarantee about what CAN be produced. Matches decision_record's own write-time convention
    (Z-suffixed UTC, second precision -- see utc_event_timestamp)."""
    return ts_dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _decisions_table(rows_in: list[tuple[dict, datetime]]) -> list[str]:
    if not rows_in:
        return ["(no decisions recorded in scope)"]
    rows = [
        (
            _safe_ts_display(ts_dt),
            "hard-to-reverse" if d["reversibility"] == "hard-to-reverse" else "reversible",
            _ledger_safe(_decision_repo_label(d), 32),
            _ledger_safe(d["summary"], 80),
        )
        for d, ts_dt in rows_in
    ]
    repo_width = max(len(repo) for _ts, _rev, repo, _summary in rows)
    return [
        f"{ts}  {rev:<15}  {repo:<{repo_width}}  {summary}"
        for ts, rev, repo, summary in rows
    ]


def _ledger_targets_data(targets: list[Path]) -> tuple[list[tuple[dict, Path]], list[str]]:
    """Load each --target's adapter INDEPENDENTLY. One bad target (no adapter, unreadable,
    malformed) must not abort a multi-repo aggregation -- it becomes one visible error line and
    every OTHER target still aggregates. Returns (pairs that loaded, one error line per target
    that did not -- `SystemExit` is the standard clean-CLI-error exception this whole file raises
    for adapter/schema problems, so it is the only exception type caught here)."""
    pairs: list[tuple[dict, Path]] = []
    errors: list[str] = []
    for target in targets:
        try:
            data = ledger_target_data(target)
        except SystemExit as exc:
            errors.append(f"{target}: {_ledger_safe(exc, 300)}")
            continue
        pairs.append((data, target))
    return pairs, errors


def decisions_report(args: argparse.Namespace) -> int:
    targets = [Path(t).resolve() for t in (args.target or [Path(".")])]
    since_dt = parse_report_since(args.since) if args.since else None
    until_dt = parse_report_until(args.until) if args.until else None
    pairs, target_errors = _ledger_targets_data(targets)
    requested_lane_ids: list[str] = []
    for _data, target in pairs:
        lane_id = instrumentation_lane_id(target)
        if lane_id not in requested_lane_ids:
            requested_lane_ids.append(lane_id)
    results, skipped, warnings = read_countable_decisions(pairs)
    grep_needle = args.grep.lower() if args.grep else None
    filtered: list[tuple[dict, datetime]] = []
    for projection, ts_dt in results:
        if since_dt is not None and not ts_dt > since_dt:
            continue
        if until_dt is not None and not ts_dt <= until_dt:
            continue
        if args.reversibility and projection["reversibility"] != args.reversibility:
            continue
        if args.goal is not None and projection["goal"] != args.goal:
            continue
        if grep_needle is not None:
            haystack = " ".join(
                str(projection.get(field) or "")
                for field in (
                    "summary", "rationale", "alternatives", "surfaces", "next",
                    "goal", "milestone", "pr",
                )
            ).lower()
            if grep_needle not in haystack:
                continue
        filtered.append((projection, ts_dt))
    # Within a lane descending (ts, seq); across lanes descending (ts, lane_id, seq) -- one reverse
    # sort over (ts, lane_id, seq) yields both (lane_id is constant within a lane).
    filtered.sort(key=lambda item: (item[1], item[0]["lane_id"], item[0]["seq"]), reverse=True)
    decisions = [projection for projection, _ in filtered]
    hard = sum(1 for d in decisions if d["reversibility"] == "hard-to-reverse")
    if args.json:
        envelope = {
            "schema": DECISIONS_REPORT_SCHEMA,
            "scope": {
                "targets": requested_lane_ids,
                "target_errors": target_errors,
                "since": args.since,
                "until": args.until,
                "reversibility": args.reversibility,
                "grep": args.grep,
                "goal": args.goal,
                "skipped_lines": skipped,
            },
            "decisions": decisions,
        }
        for error in target_errors:
            print(f"target_error: {error}", file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
        print(json.dumps(envelope, indent=2))
        return 0
    print(f"decisions: {len(decisions)} total, {hard} hard-to-reverse (retained rotations only)")
    for line in _decisions_table(filtered):
        print(line)
    for error in target_errors:
        print(f"target_error: {error}")
    if skipped:
        print(f"skipped: {skipped} decision-shaped line(s) failed validation (not counted)")
    for warning in warnings:
        print(warning, file=sys.stderr)
    return 0


def event_log_path(args: argparse.Namespace) -> int:
    data, _project_path, target = lane_project(args, lean_ok=True)
    human, jsonl, _lock = observability_event_paths(data, target)
    print(f"event_log: {human}")
    print(f"event_jsonl: {jsonl}")
    print(f"event_tail: tautline event-tail --target {target} --lines 80")
    return 0


def event_tail(args: argparse.Namespace) -> int:
    data, _project_path, target = lane_project(args, lean_ok=True)
    if args.lines < 1:
        raise SystemExit("--lines must be positive")
    human, _jsonl, _lock = observability_event_paths(data, target)
    for line in tail_lines(human, args.lines):
        print(_ledger_safe(line))
    return 0


def event_rotate(args: argparse.Namespace) -> int:
    data, _project_path, target = lane_project(args, lean_ok=True)
    human, jsonl, lock = observability_event_paths(data, target)
    human.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a", encoding="utf-8") as lock_file, advisory_flock(lock_file):
        rotate_bytes = 0 if args.force else int(data["observabilityEvents"]["rotateBytes"])
        retained = int(data["observabilityEvents"]["retainedRotations"])
        rotate_event_file(human, rotate_bytes, retained)
        rotate_event_file(jsonl, rotate_bytes, retained)
    print(f"event_rotate_log: {human}")
    print(f"event_rotate_jsonl: {jsonl}")
    return 0


def is_pending_decision(projection: dict) -> bool:
    """PENDING v1: two signals, checked in this order, structure before phrase-sniffing.

    1. AUTHORITATIVE -- `decision-record --awaiting-operator` sets an explicit boolean on the
       record (validated_decision_projection's `awaiting_operator`). This does not depend on how
       an agent phrases --next, so it is not defeated by guidance that discourages agents from
       writing loose "awaiting/pending/standing by" language in their own prose -- a phrase-
       sniffing heuristic and that guidance actively fight each other; a structured field and that
       guidance do not.
    2. FALLBACK, legacy rows only -- `--next` containing "awaiting" (case-insensitive substring).
       Every record written before `--awaiting-operator` existed has no such key at all,
       resolving to `awaiting_operator: False` (see validated_decision_projection); without this
       fallback every pre-existing "awaiting operator sign-off"-style --next would silently drop
       out of the inbox the moment the flag shipped. Deliberately a literal substring match, not a
       fuzzy classifier -- and deliberately SECOND: recording a decision today should reach for
       --awaiting-operator, not for phrasing.
    """
    if projection["awaiting_operator"]:
        return True
    return "awaiting" in projection["next"].lower()


def _inbox_table(rows_in: list[tuple[dict, datetime]]) -> list[str]:
    if not rows_in:
        return ["(inbox is empty -- nothing is recorded as awaiting an answer)"]
    rows = [
        (
            item.get("id", ""),
            _ledger_safe(_decision_repo_label(item), 32),
            _safe_ts_display(ts_dt),
            _ledger_safe(item["summary"], 60),
            _ledger_safe(item["next"], 60),
        )
        for item, ts_dt in rows_in
    ]
    repo_width = max(len(repo) for _ident, repo, _when, _summary, _next_step in rows)
    return [
        f"{ident}  {repo:<{repo_width}}  {when}  {summary}  next: {next_step}"
        for ident, repo, when, summary, next_step in rows
    ]


def inbox(args: argparse.Namespace) -> int:
    from tautline_methodology import operator_inbox

    if getattr(args, "text", None) is not None and not getattr(args, "answer", None):
        print("inbox_error: --text requires --answer <id>", file=sys.stderr)
        return 1
    targets = [Path(t).resolve() for t in (args.target or [Path(".")])]
    pairs, target_errors = _ledger_targets_data(targets)
    if any(getattr(args, field, None) for field in ("answer", "answers", "ack")):
        if target_errors:
            for error in target_errors:
                print(f"target_error: {error}", file=sys.stderr)
            return 1
        return operator_inbox.action(args, pairs, sys.modules[__name__])
    requested_lane_ids: list[str] = []
    for _data, target in pairs:
        lane_id = instrumentation_lane_id(target)
        if lane_id not in requested_lane_ids:
            requested_lane_ids.append(lane_id)
    results, skipped, warnings = read_countable_decisions(pairs)
    responses, response_warnings = operator_inbox.load(pairs, sys.modules[__name__])
    warnings.extend(response_warnings)
    pending = [(dict(projection, id=operator_inbox.decision_id(projection)), ts_dt)
               for projection, ts_dt in results if is_pending_decision(projection)
               and (operator_inbox.decision_id(projection) not in responses
                    or responses[operator_inbox.decision_id(projection)][0]["lane_id"]
                    != projection["lane_id"])]
    # Newest first, matching decisions-report's own convention (see the comment there).
    pending.sort(key=lambda item: (item[1], item[0]["lane_id"], item[0]["seq"]), reverse=True)
    items = [projection for projection, _ts_dt in pending]
    if args.json:
        envelope = {
            "schema": INBOX_SCHEMA,
            "scope": {
                "targets": requested_lane_ids,
                "target_errors": target_errors,
                "skipped_lines": skipped,
            },
            "pending": items,
        }
        for error in target_errors:
            print(f"target_error: {error}", file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
        print(json.dumps(envelope, indent=2))
        return 0
    print(f"inbox: {len(items)} pending decision(s) awaiting an answer")
    for line in _inbox_table(pending):
        print(line)
    if items:
        print('Answer: tautline inbox --answer <id> --text "<answer>" --target <source-lane>')
    for error in target_errors:
        print(f"target_error: {error}")
    if skipped:
        print(f"skipped: {skipped} decision-shaped line(s) failed validation (not counted)")
    for warning in warnings:
        print(warning, file=sys.stderr)
    return 0


def lane_status_reserved_state_paths(data: dict, target: Path) -> set[Path]:
    """Framework state files this control must never write over.

    "Ignored and untracked inside the worktree" is exactly what every framework state file looks
    like -- GOAL_RUN.json, BLOCKER.json, the latest-code baseline -- so the safety gate alone would
    happily let a misconfigured or hostile `statusFile` erase a declared blocker, an active goal, or
    the baseline on EVERY session start. Ownership has to be asserted, not inferred.
    """
    reserved: set[Path] = set()
    candidates = [
        ".ai-work/GOAL_RUN.json",
        ".ai-work/BLOCKER.json",
        ".ai-work/PRODUCT_DEV_MODE.json",
        ".ai-work/LATEST_CODE_BASELINE.json",
        ".ai-work/MILESTONE_RUN.json",
    ]
    latest = data.get("latestCode") or {}
    if latest.get("statusFile"):
        candidates.append(str(latest["statusFile"]))
    for rel in candidates:
        try:
            reserved.add(configured_path(target, rel).resolve(strict=False))
        except (SystemExit, ValueError, OSError):
            continue
    return reserved


def lane_status_status_path_is_safe(
    target: Path, path: Path, *, deadline: float, reserved: set[Path] | None = None
) -> tuple[bool, str | None]:
    """The artifact destination must be inside the worktree, ignored, and untracked.

    "Outside the worktree" is NOT safe -- an adapter-controlled path escaping the repository turns
    a SessionStart hook into an arbitrary-overwrite primitive against user metadata. Ignored and
    untracked together stop two different failures: overwriting tracked content, and leaving a file
    that every LATER invocation observes as DIRTY.
    """
    resolved = path.resolve(strict=False)
    root = target.resolve(strict=False)
    if root != resolved and root not in resolved.parents:
        return False, "laneStatus.statusFile resolves outside the worktree - artifact not written"
    if reserved and resolved in reserved:
        return False, (
            "laneStatus.statusFile names another framework state file - artifact not written"
        )
    ignored, _ = lane_status_git_probe(
        target, ["check-ignore", "-q", str(resolved)], deadline=deadline
    )
    if ignored != 0:
        return False, "laneStatus.statusFile is not git-ignored - artifact not written"
    tracked, _ = lane_status_git_probe(
        target, ["ls-files", "--error-unmatch", str(resolved)], deadline=deadline
    )
    # ONLY exit 1 proves untracked: 124 (deadline) and 128 (unreadable index) are failed
    # verifications, and treating them as "untracked" would let this safety gate pass silently.
    if tracked == 0:
        return False, "laneStatus.statusFile is tracked - artifact not written"
    if tracked != 1:
        return False, (
            f"could not determine whether laneStatus.statusFile is tracked (git exit {tracked}) - "
            "artifact not written"
        )
    return True, None


def lane_status_payload(facts: dict, findings: list[dict], *, last_fetch_at: str | None) -> dict:
    """The frozen `tautline-lane-status/v1` object. `--json` prints this verbatim, so the artifact
    and the JSON surface cannot drift apart."""
    return {
        "schema": lane_status_module().LANE_STATUS_SCHEMA,
        "recordedAt": now_iso(),
        "lastFetchAt": last_fetch_at,
        "branch": facts.get("branch"),
        "integrationBranch": facts.get("integration_branch"),
        "remote": facts.get("remote"),
        "ahead": facts.get("ahead"),
        "behind": facts.get("behind"),
        "localVersion": facts.get("local_version"),
        "baseVersion": facts.get("base_version"),
        "findings": findings,
        "resolved": not findings,
    }


def lane_status_path_is_owned_and_untracked(
    target: Path, path: Path, *, deadline: float, reserved: set[Path] | None = None
) -> bool:
    """Inside the worktree AND untracked AND not another framework's state -- the narrow case where
    a stale artifact is safe to remove even though the full safety gate refused the write.

    The reserved check is load-bearing: GOAL_RUN.json and the latest-code baseline are themselves
    ignored and untracked inside the worktree, so without it a refusal aimed at PROTECTING them
    would delete them instead. That is the second time this invalidation path has been able to
    destroy what it was guarding, so ownership is now asserted, never inferred.
    """
    resolved = path.resolve(strict=False)
    root = target.resolve(strict=False)
    if root != resolved and root not in resolved.parents:
        return False
    if reserved and resolved in reserved:
        return False
    if not resolved.is_file():
        return False
    tracked, _ = lane_status_git_probe(
        target, ["ls-files", "--error-unmatch", str(resolved)], deadline=deadline
    )
    return tracked == 1


def lane_status_write_artifact(
    target: Path, cfg: dict, payload: dict, *, deadline: float, data: dict | None = None
) -> str | None:
    """Write the single artifact atomically. Returns an error reason, or None.

    On any refusal or failure a PRIOR artifact is removed: `os.replace` would otherwise leave a
    previous `resolved: true` file republishing a stale clean verdict indefinitely.
    """
    try:
        path = configured_path(target, cfg["statusFile"])
    except (SystemExit, ValueError, OSError):
        return "laneStatus.statusFile could not be resolved - artifact not written"
    reserved = lane_status_reserved_state_paths(data or {}, target)
    safe, reason = lane_status_status_path_is_safe(
        target, path, deadline=deadline, reserved=reserved
    )
    if not safe:
        # Do NOT blindly unlink: the path just failed the safety gate, so it may be tracked content
        # or somewhere outside the worktree, and deleting it would turn a refusal into the very
        # destructive write the gate exists to prevent.
        #
        # But a destination that is still PROVABLY ours -- inside the worktree and untracked, merely
        # no longer ignored -- must not be left holding a `resolved: true` verdict while this run
        # reports UNVERIFIED, or consumers keep reading a stale clean answer. Invalidate only in
        # that narrow, provable case.
        if lane_status_path_is_owned_and_untracked(
            target, path, deadline=deadline, reserved=reserved
        ):
            _lane_status_discard_artifact(path)
        return reason
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    ok, tmp_reason = lane_status_status_path_is_safe(
        target, tmp, deadline=deadline, reserved=reserved
    )
    if not ok:
        _lane_status_discard_artifact(path)
        return f"lane-status temp path is not safe to write: {tmp_reason}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        # Clean up the PID-specific temp file too: when write_text succeeds but os.replace fails
        # (a directory at the destination, say), unlinking only the destination leaves a temp
        # artifact behind on EVERY session start.
        _lane_status_discard_artifact(tmp)
        _lane_status_discard_artifact(path)
        return f"lane-status artifact not written: {lane_status_safe_detail(exc, limit=120)}"
    return None


def lane_status_previous_fetch_at(target: Path, cfg: dict) -> str | None:
    """Carry `lastFetchAt` forward, but only when the recorded target still matches: a fetch is
    evidence only about the remote and branch it ran for."""
    try:
        recorded = json.loads(
            configured_path(target, cfg["statusFile"]).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, SystemExit):
        return None
    if str(recorded.get("remote") or "") != cfg["remote"]:
        return None
    if str(recorded.get("integrationBranch") or "") != cfg["integrationBranch"]:
        return None
    value = recorded.get("lastFetchAt")
    return str(value) if value else None


def lane_status_unverified_payload(reason: str) -> dict:
    return {
        "schema": lane_status_module().LANE_STATUS_SCHEMA,
        "recordedAt": now_iso(),
        "lastFetchAt": None,
        "branch": None,
        "integrationBranch": None,
        "remote": None,
        "ahead": "unknown",
        "behind": "unknown",
        "localVersion": None,
        "baseVersion": None,
        "findings": [{"id": "UNVERIFIED", "severity": "info", "detail": reason}],
        "resolved": False,
    }


def lane_status_invalidate_artifact_best_effort(args: argparse.Namespace) -> None:
    """Remove a prior artifact when this run could not produce one. Best effort by design: it runs
    inside the containment arm, so it re-derives the path defensively and never raises."""
    target = args.target.resolve()
    root = find_adapter_root(target)
    if root is None:
        return
    data = load_project(adapter_marker_path(root))
    cfg = lane_status_config(data)
    path = configured_path(root, cfg["statusFile"])
    deadline = time.monotonic() + 3
    if lane_status_path_is_owned_and_untracked(
        root, path, deadline=deadline, reserved=lane_status_reserved_state_paths(data, root)
    ):
        _lane_status_discard_artifact(path)


def lane_status(args: argparse.Namespace) -> int:
    """`lane-status`: report lane currency. NEVER blocks (C1/C2): every exit path is `return 0`, in
    both hook and command mode, and there is no `hook_decision` call anywhere on this path.

    `--hook` swallows every exception the way a session-start hook must, but -- unlike a carrier --
    still prints an UNVERIFIED line for a LOCATED lane, because a currency check that goes silent on
    failure is indistinguishable from one that never ran. Outside a managed lane it stays
    byte-silent: this hook is registered globally and would otherwise warn in every unrelated
    repository on the machine.
    """
    want_json = bool(getattr(args, "json", False))
    hook_mode = bool(getattr(args, "hook", False))
    try:
        # Resolution is INSIDE containment: a symlink loop raises from .resolve(), and outside the
        # try the shell swallows stderr and the session gets no line at all.
        target = args.target.resolve()
        root = find_adapter_root(target)
        if root is None:
            if hook_mode:
                return 0
            reason = f"{target} is not a Tautline lane root"
            # A `--json` caller must get the advertised v1 payload on THIS error case too, or JSON
            # consumers break precisely where they most need a parseable answer.
            if want_json:
                print(json.dumps(lane_status_unverified_payload(reason), indent=2, sort_keys=True))
            else:
                print(f"TAUTLINE LANE STATUS - UNVERIFIED: {reason}")
                print(lean.INIT_NUDGE_LINE)  # --- LEAN INIT WIRING ---
            return 0
        # A lean-1 adapter fails the 1.x loader by design -- it carries none of the eleven required
        # ceremony keys -- and the containment below would then report "could not be computed" for
        # every lean lane forever. lane-status is report-only and on the KEEP list, so it has to
        # keep ANSWERING when the config changes shape, not go quiet.
        data = lean.load_project_lean_aware(  # --- LEAN PROFILE WIRING ---
            adapter_marker_path(root), load_project
        )
        cfg = lane_status_config(data)
        # BEFORE the startupCheck early return, on purpose. "Every session leaves a trace" has to
        # hold for lanes that turned the startup CHECK off -- those are exactly the lanes most
        # likely to have several sessions in one checkout, and a peer record that only exists
        # where the check is on is a record with a hole in the shape of the problem. Turning off a
        # status report is not the same as opting out of coordination; `fleet.occupancy.enabled`
        # (or the master `fleet.enabled`) is how a lane says the latter.
        occupancy_record_session(data, root)
        if cfg["startupCheck"] == "off" and hook_mode:
            return 0
        deadline = time.monotonic() + LANE_STATUS_COLLECTION_BUDGET_SECONDS
        module = lane_status_module()
        facts, fetched = collect_lane_status_facts(data, root, cfg=cfg, deadline=deadline)
        findings = module.compute_lane_status_findings(facts)
        last_fetch_at = now_iso() if fetched else lane_status_previous_fetch_at(root, cfg)
        payload = lane_status_payload(facts, findings, last_fetch_at=last_fetch_at)
        write_error = lane_status_write_artifact(
            root, cfg, payload, deadline=deadline, data=data
        )
        if write_error:
            # Folded in BEFORE the payload is emitted, so --json reports it too.
            findings = findings + [
                {"id": "UNVERIFIED", "severity": "info", "detail": write_error}
            ]
            payload = dict(payload, findings=findings, resolved=False)
        if want_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        # Report under product-dev AND maintainer mode: a report cannot cause the friction those
        # standdowns exist to relieve, and the 2026-07-24 incident was an analysis session --
        # exactly the shape product-dev mode is used for. Abbreviation trims prose, never remedies.
        abbreviated = product_dev_mode_active(root) or maintainer_mode_armed()
        for line in module.render_lane_status_report(
            root, facts, findings, abbreviated=abbreviated
        ):
            print(line)
        # SURFACING POINT 1 (R4). The free carrier: on a runtime that supplies a SessionStart
        # hook, this line reaches the session at no cost. It deliberately does NOT reach a
        # zero-capability runtime -- that lane cannot be told anything at session start, which is
        # precisely why `methodology-status` and the review-evidence stamp are not conveniences
        # for it but the only surfaces that work.
        #
        # ONLY WHEN DEGRADED, because this surface's contract is that a clean lane prints exactly
        # one line (`test_clean_lane_prints_exactly_one_line`). A session-start carrier that
        # speaks every session trains its reader to skip it, and then it is not a signal at all --
        # the opposite trade from `methodology-status`, which is invoked deliberately and should
        # always answer. Same fact, two surfaces, different silence rules on purpose.
        degradation = runtime_capabilities.lane_degradation(data)
        if degradation.get("runtime") and runtime_capabilities.degraded(degradation):
            print(f"  ENFORCEMENT: {runtime_capabilities.summary_line(degradation)}")
        # Track H: continuity-handoff freshness. Unlike ENFORCEMENT above, this is not gated to
        # "only when degraded" -- a fresh session at start is exactly where this line earns its
        # keep -- but it is silent on a project that never wrote a handoff and never turned the
        # feature on, so `test_clean_lane_prints_exactly_one_line` is untouched by a project that
        # does not use this feature. `handoff_status_line` returns raw, unsanitized file content;
        # `lane_status_safe_detail` is this surface's one sanitizer for everything it prints.
        from tautline_methodology import work

        for work_line in work.advisory_lines(root, data):
            print(f"  {lane_status_safe_detail(work_line, limit=500)}")
        from tautline_methodology import operator_inbox

        for inbox_line in operator_inbox.startup_lines(root, sys.modules[__name__]):
            print(f"  {lane_status_safe_detail(inbox_line, limit=500)}")
        handoff_line = lean.handoff_status_line(root)
        if handoff_line:
            print(f"  {lane_status_safe_detail(handoff_line)}")
        # Track J: backlog freshness, beside Track H's handoff line and under the same rules. A
        # LIVE read on a five-second leash -- the count is measured, or the line says the board is
        # unreachable and why; it never prints a number it did not read and never goes silent on
        # failure. Conditional on the project naming a backlog, so a lane without one is untouched
        # and `test_clean_lane_prints_exactly_one_line` still holds. The line already carries
        # remote-sourced text through `backlog._safe`; `lane_status_safe_detail` is this surface's
        # one sanitiser for everything it prints, and it also redacts URL userinfo, so it runs here
        # too rather than trusting a caller two modules away to have covered every case.
        backlog_adapter = lean.find_lean_adapter(root)
        if backlog_adapter is not None:
            from tautline_methodology import backlog as backlog_mod

            backlog_line = backlog_mod.advisory_line(root, lean.load_lean_config(backlog_adapter))
            if backlog_line:
                print(f"  {lane_status_safe_detail(backlog_line)}")
    except (SystemExit, Exception):  # noqa: B036 - total containment WITH a line (C5)
        reason = "lane status could not be computed"
        # A prior clean run leaves `resolved: true` on disk. Without this, an invocation that
        # raises reports UNVERIFIED to the session while consumers keep reading yesterday's clean
        # verdict -- two readers disagreeing about the same lane, which is the exact failure the
        # write-error reporting exists to prevent.
        try:
            lane_status_invalidate_artifact_best_effort(args)
        except (SystemExit, Exception):  # noqa: B036 - invalidation must never break containment
            pass
        if want_json:
            print(json.dumps(lane_status_unverified_payload(reason), indent=2, sort_keys=True))
        else:
            print(f"TAUTLINE LANE STATUS - UNVERIFIED: {reason}")
        return 0
    return 0


# package-split A2 (roadmap #11): event record/audit helpers moved to tautline_methodology.events;
# re-exported as eager aliases so cli.<name> reach and every in-bin call site keep resolving.


# package-split A2 mechanism spike (roadmap #11 T3 Step 1): the first def carved into the
# tautline_methodology package, validating that bin (loaded under the package name) can import a
# real submodule. Moved to tautline_methodology.core.paths; re-exported as an eager alias so
# cli.<name> reach and the events/usage/instrumentation call sites keep resolving unchanged.
try:
    from tautline_methodology.core import paths as _core_paths_mod
except ModuleNotFoundError as exc:
    _core_paths_mod = _MissingFrameworkPackage(exc, "path helpers")  # type: ignore[assignment]
event_jsonl_read_paths = _core_paths_mod.event_jsonl_read_paths


def normalize_ci_test_gate(data: dict) -> dict:
    """Validate + normalize the adapter ciTestGate block. Type-checks rather than coerces, so an
    invalid value (a non-dict block, events:[1], requiredWorkflow:null) is rejected, not silently
    normalized into a bogus string (Codex P3)."""
    raw = data.get("ciTestGate")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter ciTestGate must be an object")
    cfg = {**DEFAULT_CI_TEST_GATE, **(raw or {})}
    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit("Project adapter ciTestGate.enabled must be boolean")
    if cfg["enforcement"] not in {"warn", "block"}:
        raise SystemExit("Project adapter ciTestGate.enforcement must be warn or block")
    events = cfg.get("events", [])
    if not isinstance(events, list) or not events or any(not isinstance(ev, str) or not ev.strip() for ev in events):
        raise SystemExit("Project adapter ciTestGate.events must be a non-empty array of non-blank strings")
    cfg["events"] = [ev.strip() for ev in events]
    markers = cfg.get("testCommandMarkers", [])
    if not isinstance(markers, list) or any(not isinstance(m, str) or not m.strip() for m in markers):
        raise SystemExit("Project adapter ciTestGate.testCommandMarkers must be an array of non-blank strings")
    cfg["testCommandMarkers"] = [m.strip() for m in markers]
    required_workflow = cfg.get("requiredWorkflow", "")
    if not isinstance(required_workflow, str):
        raise SystemExit("Project adapter ciTestGate.requiredWorkflow must be a string")
    cfg["requiredWorkflow"] = required_workflow.strip()
    if Path(cfg["requiredWorkflow"]).is_absolute():
        raise SystemExit("Project adapter ciTestGate.requiredWorkflow must be a workflow filename, not an absolute path")
    if "expectTests" in cfg and not isinstance(cfg["expectTests"], bool):
        raise SystemExit("Project adapter ciTestGate.expectTests must be boolean")
    if not isinstance(cfg.get("requiredCheckName", ""), str):
        raise SystemExit("Project adapter ciTestGate.requiredCheckName must be a string")
    cfg["requiredCheckName"] = str(cfg.get("requiredCheckName", "")).strip()
    return cfg


def normalize_ui_evidence(data: dict) -> dict:
    raw = data.get("uiEvidence")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter uiEvidence must be an object")
    cfg = {**DEFAULT_UI_EVIDENCE, **(raw or {})}
    issue_raw = (raw or {}).get("issueComments", {}) if isinstance(raw, dict) else {}
    if issue_raw is not None and not isinstance(issue_raw, dict):
        raise SystemExit("Project adapter uiEvidence.issueComments must be an object")
    cfg["issueComments"] = {**DEFAULT_UI_EVIDENCE["issueComments"], **(issue_raw or {})}

    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit("Project adapter uiEvidence.enabled must be boolean")
    if cfg["enforcement"] not in {"off", "warn", "block"}:
        raise SystemExit("Project adapter uiEvidence.enforcement must be off, warn, or block")
    if str(cfg.get("tool", "")).strip() != "playwright":
        raise SystemExit("Project adapter uiEvidence.tool must be playwright")
    cfg["tool"] = "playwright"
    for key in ("evidenceDir", "manifestGlob", "captureCommand"):
        if not isinstance(cfg.get(key, ""), str):
            raise SystemExit(f"Project adapter uiEvidence.{key} must be a string")
        cfg[key] = str(cfg.get(key, "")).strip()
    if not cfg["evidenceDir"]:
        raise SystemExit("Project adapter uiEvidence.evidenceDir must be non-blank")
    if Path(cfg["evidenceDir"]).is_absolute() or ".." in Path(cfg["evidenceDir"]).parts:
        raise SystemExit("Project adapter uiEvidence.evidenceDir must stay inside the project")
    if not cfg["manifestGlob"]:
        raise SystemExit("Project adapter uiEvidence.manifestGlob must be non-blank")

    allowed_events = UI_EVIDENCE_EVENTS
    required_events = cfg.get("requiredEvents", [])
    if not isinstance(required_events, list) or any(not isinstance(ev, str) or not ev.strip() for ev in required_events):
        raise SystemExit("Project adapter uiEvidence.requiredEvents must be an array of non-blank strings")
    cfg["requiredEvents"] = [ev.strip() for ev in required_events]
    invalid_required = sorted(set(cfg["requiredEvents"]) - allowed_events)
    if invalid_required:
        raise SystemExit(
            "Project adapter uiEvidence.requiredEvents may contain only "
            "milestone-complete, goal-complete, and work-item-complete"
        )

    comments = cfg["issueComments"]
    if not isinstance(comments.get("enabled"), bool):
        raise SystemExit("Project adapter uiEvidence.issueComments.enabled must be boolean")
    if comments.get("provider") != "github-issues":
        raise SystemExit("Project adapter uiEvidence.issueComments.provider must be github-issues")
    if not isinstance(comments.get("required"), bool):
        raise SystemExit("Project adapter uiEvidence.issueComments.required must be boolean")
    trigger_events = comments.get("triggerEvents", [])
    if not isinstance(trigger_events, list) or any(not isinstance(ev, str) or not ev.strip() for ev in trigger_events):
        raise SystemExit("Project adapter uiEvidence.issueComments.triggerEvents must be an array of non-blank strings")
    comments["triggerEvents"] = [ev.strip() for ev in trigger_events]
    invalid_triggers = sorted(set(comments["triggerEvents"]) - allowed_events)
    if invalid_triggers:
        raise SystemExit(
            "Project adapter uiEvidence.issueComments.triggerEvents may contain only "
            "milestone-complete, goal-complete, and work-item-complete"
        )
    if comments["enabled"] and not comments["triggerEvents"]:
        raise SystemExit("Project adapter uiEvidence.issueComments.triggerEvents must be non-empty when comments are enabled")
    return cfg


def normalize_development_environment(data: dict) -> dict:
    raw = data.get("developmentEnvironment")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter developmentEnvironment must be an object")
    windows_raw = (raw or {}).get("windows") or {}
    if not isinstance(windows_raw, dict):
        raise SystemExit("Project adapter developmentEnvironment.windows must be an object")
    line_endings_raw = (raw or {}).get("lineEndings") or {}
    if not isinstance(line_endings_raw, dict):
        raise SystemExit("Project adapter developmentEnvironment.lineEndings must be an object")
    cfg = {
        **DEFAULT_DEVELOPMENT_ENVIRONMENT,
        **(raw or {}),
    }
    cfg["windows"] = {
        **DEFAULT_DEVELOPMENT_ENVIRONMENT["windows"],
        **windows_raw,
    }
    cfg["lineEndings"] = {
        **DEFAULT_DEVELOPMENT_ENVIRONMENT["lineEndings"],
        **line_endings_raw,
    }
    runtimes = cfg.get("supportedRuntimes", [])
    if not isinstance(runtimes, list):
        raise SystemExit("Project adapter developmentEnvironment.supportedRuntimes must be an array")
    normalized_runtimes: list[str] = []
    for runtime in runtimes:
        if not isinstance(runtime, str) or not runtime.strip():
            raise SystemExit("Project adapter developmentEnvironment.supportedRuntimes must contain non-blank strings")
        runtime = runtime.strip().lower()
        if runtime not in SUPPORTED_DEVELOPMENT_RUNTIMES:
            raise SystemExit(
                "Project adapter developmentEnvironment.supportedRuntimes may contain only "
                "linux, darwin, wsl1, wsl2, or win32"
            )
        if runtime not in normalized_runtimes:
            normalized_runtimes.append(runtime)
    cfg["supportedRuntimes"] = normalized_runtimes
    windows = cfg["windows"]
    if windows["native"] not in {"unspecified", "unsupported", "supported", "diagnostic-only"}:
        raise SystemExit("Project adapter developmentEnvironment.windows.native must be unspecified, unsupported, supported, or diagnostic-only")
    if windows["supportedRuntime"] not in {"wsl2", "win32"}:
        raise SystemExit("Project adapter developmentEnvironment.windows.supportedRuntime must be wsl2 or win32")
    if windows["native"] in {"unsupported", "diagnostic-only"} and "win32" in cfg["supportedRuntimes"]:
        raise SystemExit(
            "Project adapter developmentEnvironment cannot include win32 in supportedRuntimes "
            f"when windows.native is {windows['native']}"
        )
    if windows["native"] == "supported" and "win32" not in cfg["supportedRuntimes"]:
        raise SystemExit(
            "Project adapter developmentEnvironment must include win32 in supportedRuntimes "
            "when windows.native is supported"
        )
    for key in ("setup", "reason"):
        if not isinstance(windows.get(key, ""), str):
            raise SystemExit(f"Project adapter developmentEnvironment.windows.{key} must be a string")
        windows[key] = windows.get(key, "").strip()
    line_endings = cfg["lineEndings"]
    if line_endings["policy"] not in {"", "lf", "crlf", "mixed"}:
        raise SystemExit("Project adapter developmentEnvironment.lineEndings.policy must be lf, crlf, mixed, or blank")
    if not isinstance(line_endings.get("windowsGuidance", ""), str):
        raise SystemExit("Project adapter developmentEnvironment.lineEndings.windowsGuidance must be a string")
    line_endings["windowsGuidance"] = line_endings.get("windowsGuidance", "").strip()
    return cfg


def normalize_runtime_config(data: dict) -> dict:
    """Validate + normalize the optional runtimeConfig block (required-runtime-secret registry).
    Type-checks rather than coerces; never SystemExits merely because a customer-facing adapter has no
    registry (that is an advisory surfaced by runtime_secret_fallback_issues, not a load-time wedge)."""
    raw = data.get("runtimeConfig")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter runtimeConfig must be an object")
    cfg = {**DEFAULT_RUNTIME_CONFIG, **(raw or {})}
    if cfg["enforcement"] not in {"warn", "block"}:
        raise SystemExit("Project adapter runtimeConfig.enforcement must be warn or block")
    secrets = cfg.get("requiredSecrets", [])
    if not isinstance(secrets, list):
        raise SystemExit("Project adapter runtimeConfig.requiredSecrets must be an array")
    norm: list[dict] = []
    for entry in secrets:
        if not isinstance(entry, dict):
            raise SystemExit("Project adapter runtimeConfig.requiredSecrets[] entries must be objects")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SystemExit("Project adapter runtimeConfig.requiredSecrets[].name must be a non-blank string")
        norm.append({**entry, "name": name.strip()})
    cfg["requiredSecrets"] = norm
    for key in ("bootAssertionCommand", "secretParityCommand"):
        if not isinstance(cfg.get(key, ""), str):
            raise SystemExit(f"Project adapter runtimeConfig.{key} must be a string")
        cfg[key] = str(cfg.get(key, "")).strip()
    return cfg


def normalize_migration_safety(data: dict) -> dict:
    raw = data.get("migrationSafety")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter migrationSafety must be an object")
    cfg = {**DEFAULT_MIGRATION_SAFETY, **(raw or {})}
    if cfg["enforcement"] not in {"warn", "block"}:
        raise SystemExit("Project adapter migrationSafety.enforcement must be warn or block")
    for key in ("migrationsPath", "ackMarker"):
        if not isinstance(cfg.get(key, ""), str):
            raise SystemExit(f"Project adapter migrationSafety.{key} must be a string")
        cfg[key] = str(cfg.get(key, "")).strip()
    if not cfg["ackMarker"]:
        cfg["ackMarker"] = DEFAULT_MIGRATION_SAFETY["ackMarker"]
    return cfg


def normalize_coverage_floor(data: dict) -> dict:
    raw = data.get("coverageFloor")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter coverageFloor must be an object")
    cfg = {**DEFAULT_COVERAGE_FLOOR, **(raw or {})}
    if cfg["enforcement"] not in {"warn", "block"}:
        raise SystemExit("Project adapter coverageFloor.enforcement must be warn or block")
    try:
        cfg["newCodeMinPct"] = int(cfg["newCodeMinPct"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter coverageFloor.newCodeMinPct must be an integer 0-100") from exc
    if not 0 <= cfg["newCodeMinPct"] <= 100:
        raise SystemExit("Project adapter coverageFloor.newCodeMinPct must be an integer 0-100")
    for key in ("coverageReport", "diffBase"):
        if not isinstance(cfg.get(key, ""), str):
            raise SystemExit(f"Project adapter coverageFloor.{key} must be a string")
        cfg[key] = str(cfg.get(key, "")).strip() or DEFAULT_COVERAGE_FLOOR[key]
    return cfg


def normalize_flaky_quarantine(data: dict) -> dict:
    raw = data.get("flakyQuarantine")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter flakyQuarantine must be an object")
    cfg = {**DEFAULT_FLAKY_QUARANTINE, **(raw or {})}
    if cfg["enforcement"] not in {"warn", "block"}:
        raise SystemExit("Project adapter flakyQuarantine.enforcement must be warn or block")
    try:
        cfg["maxMarkers"] = int(cfg["maxMarkers"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("Project adapter flakyQuarantine.maxMarkers must be an integer") from exc
    if not isinstance(cfg.get("scanPath", ""), str):
        raise SystemExit("Project adapter flakyQuarantine.scanPath must be a string")
    cfg["scanPath"] = str(cfg.get("scanPath", "")).strip()
    markers = cfg.get("markers", FLAKY_QUARANTINE_MARKERS)
    if not isinstance(markers, list) or not all(isinstance(m, str) for m in markers):
        raise SystemExit("Project adapter flakyQuarantine.markers must be a list of strings")
    cfg["markers"] = [m.strip() for m in markers if m.strip()] or list(FLAKY_QUARANTINE_MARKERS)
    return cfg


def normalize_health_contract(data: dict) -> dict:
    raw = data.get("healthContract")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter healthContract must be an object")
    cfg = {**DEFAULT_HEALTH_CONTRACT, **(raw or {})}
    if cfg["enforcement"] not in {"off", "warn", "block"}:
        raise SystemExit("Project adapter healthContract.enforcement must be off, warn, or block")
    return cfg


def normalize_side_effect_proof(data: dict) -> dict:
    raw = data.get("sideEffectProof")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter sideEffectProof must be an object")
    cfg = {**DEFAULT_SIDE_EFFECT_PROOF, **(raw or {})}
    if cfg["enforcement"] not in {"off", "warn", "block"}:
        raise SystemExit("Project adapter sideEffectProof.enforcement must be off, warn, or block")
    return cfg


def dispatch_command(args: argparse.Namespace) -> int:
    """One explicit hook-failure contract (arch-errors-1).

    Hooks (commands whose name ends in `-hook`) FAIL OPEN: an UNEXPECTED internal error must never
    wedge a lane, so it is logged to stderr and dispatch returns 0 (no block). Intentional block
    decisions are unaffected -- `hook_decision` prints its block to stdout (it does not raise), and a
    deliberate SystemExit is re-raised. Non-hook commands keep normal fail-loud behavior (exceptions
    propagate), since for them a surfaced error is the correct signal, not a silent pass.
    """
    cmd_name = getattr(args, "cmd", "") or ""
    warn_deprecated_command(cmd_name)
    # THE PER-PARSER ALIAS, consumed here rather than only shown by `--help`. It is deliberately
    # NOT routed through DEPRECATED_COMMAND_REPLACEMENTS: that map feeds `deprecatedSurfaces` in
    # every frozen migration report, so adding entries to it retroactively rewrites reports for
    # releases that shipped years of versions ago -- which the byte-identity guard rightly
    # refuses. A rename in THIS release must announce itself at run time without editing the
    # published history of earlier ones.
    _alias = getattr(args, "deprecated_alias", None)
    if _alias:
        _old, _new = _alias
        print(f"deprecation_warning: {deprecated_alias_notice(_old, _new)}", file=sys.stderr)
    if cmd_name.endswith("-hook"):
        try:
            return args.func(args)
        except SystemExit as exc:
            missing_framework_package = (
                "require the framework checkout's src/tautline_methodology" in str(exc)
                and isinstance(exc.__cause__, ModuleNotFoundError)
            )
            if not missing_framework_package:
                raise
            print(
                f"hook_fail_open: {cmd_name} hit a missing framework package and did NOT block: "
                f"{str(exc)}",
                file=sys.stderr,
            )
            return 0
        except Exception as exc:  # noqa: BLE001 - failing open is the explicit hook contract
            try:
                detail = redact_secrets(str(exc))
            except BaseException:
                # The last-resort fail-open handler must not depend on the lazily
                # imported util package (absent in standalone bin copies), and it
                # must never fall back to the unredacted message: degrade to the
                # exception type only.
                detail = f"{type(exc).__name__} (detail suppressed: secret redaction unavailable)"
            print(
                f"hook_fail_open: {cmd_name} hit an internal error and did NOT block: "
                f"{detail}",
                file=sys.stderr,
            )
            return 0
    return args.func(args)


def _register_misc_1(sub) -> None:
    version_p = sub.add_parser("version", help="Print plugin version, methodology repo commit, and local-vs-remote sync status.")
    version_p.add_argument("--no-remote", action="store_true")
    version_p.set_defaults(func=version)


def _register_install_1(sub) -> None:
    install_p = sub.add_parser("install-cli", help="Install the CLI shim + methodology.env; mutates ~/.local/bin and ~/.config/minervit.")
    install_p.add_argument("--bin-dir", type=Path, default=USER_BIN_DIR)
    install_p.add_argument("--config-env", type=Path, default=USER_CONFIG_ENV)
    install_p.add_argument("--dry-run", action="store_true", help="Print planned actions without changing anything.")
    install_p.add_argument(
        "--update-policy",
        choices=["signed", "pinned", "warn", "unverified"],
        default="pinned",
        help="Auto-update trust policy written to methodology.env. Default 'pinned' pins the "
        "install commit; advance the pin by adding the reviewed commit to the trusted-pins file.",
    )
    install_p.set_defaults(func=install_cli)

    uninstall_p = sub.add_parser("uninstall-cli", help="Remove the installed CLI shim and methodology.env (reverses install-cli).")
    uninstall_p.add_argument("--bin-dir", type=Path, default=USER_BIN_DIR)
    uninstall_p.add_argument("--config-env", type=Path, default=None, help="Config env file; defaults to the effective one (tautline path, else legacy).")
    uninstall_p.add_argument("--keep-env", action="store_true", help="Keep methodology.env; remove only the shim.")
    uninstall_p.add_argument("--dry-run", action="store_true", help="Print planned removals without changing anything.")
    uninstall_p.set_defaults(func=uninstall_cli)

    sync_p = sub.add_parser("sync-methodology", help="Update the methodology repo (optional auto-rescue), install guards, and report version/remote status.")
    sync_p.add_argument("--project", type=Path, help="Project adapter used with --target for release-track/WIP checks.")
    sync_p.add_argument("--target", type=Path, help="Adopter repo whose framework pin and WIP state should gate the sync.")
    sync_p.add_argument("--skip-update", action="store_true")
    sync_p.add_argument("--no-remote", action="store_true")
    sync_p.add_argument("--allow-non-main", action="store_true", help="Allow sync from a non-main methodology checkout for intentional methodology development.")
    sync_p.add_argument(
        "--auto-rescue-local-changes",
        action="store_true",
        help="Preserve dirty methodology checkout changes on a local rescue branch, reset release main to upstream, and re-run. This is already the default when invoked from outside the methodology repo.",
    )
    sync_p.add_argument(
        "--no-auto-rescue-local-changes",
        action="store_true",
        help="Disable project-startup auto-rescue and fail closed on dirty stale methodology checkouts.",
    )
    sync_p.add_argument(
        "--launcher-gate",
        action="store_true",
        help=(
            "Serialize concurrent lane launches on a lock, and skip the sync when another lane "
            "already synced within the freshness window "
            f"({METHODOLOGY_SYNC_FRESHNESS_ENV}, default "
            f"{METHODOLOGY_SYNC_DEFAULT_FRESHNESS_MINUTES} minutes; 0 disables the skip)."
        ),
    )
    sync_p.set_defaults(func=sync_methodology)


def _register_adapters_1(sub) -> None:
    render = sub.add_parser("render-adapters", help="Render CLAUDE.md/AGENTS.md/lane config from a project adapter (--write/--check) with drift guards.")
    render.add_argument("--project", type=Path, required=True)
    render.add_argument("--target", type=Path, required=True)
    render.add_argument("--write", action="store_true")
    render.add_argument("--check", action="store_true")
    render.add_argument(
        "--json-only",
        action="store_true",
        help="Render/check only .minervit-ai-delivery.json; preserve CLAUDE.md and AGENTS.md.",
    )
    render.add_argument(
        "--omit-domain",
        default="",
        help=(
            "Compatibility render: omit one adapter domain from the generated output. Accepts "
            "only laneStatus, for downgrading a lane below 0.21.0."
        ),
    )
    render.add_argument(
        "--allow-template-downgrade",
        action="store_true",
        help=(
            "Write even when the on-disk generated files were produced by a NEWER template than "
            "this runtime. Deliberate downgrade: use it when repinning a lane backwards on "
            "purpose, not to silence a stale pin."
        ),
    )
    render.set_defaults(func=render_adapters)

    validate_adapter_p = sub.add_parser(
        "validate-adapter",
        help="Validate a project adapter JSON file against the adapter schema (reports all violations).",
    )
    validate_adapter_p.add_argument("--project", type=Path, required=True, help="Path to the adapter JSON to validate.")
    validate_adapter_p.set_defaults(func=validate_adapter)


def _register_release_2(sub) -> None:

    public_contract_p = sub.add_parser(
        "public-contract",
        help="Generate/check the public compatibility contract manifest for commands, adapter keys, generated files, skills, and policy modules.",
    )
    public_contract_p.add_argument("--write", action="store_true", help="Write methodology/public-contract-manifest.json.")
    public_contract_p.add_argument("--check", action="store_true", help="Fail if the committed manifest is stale.")
    public_contract_p.add_argument("--print", action="store_true", dest="print_manifest", help="Print the manifest JSON.")
    public_contract_p.add_argument("--output", type=Path, help="Write/check a path other than the default manifest.")
    public_contract_p.set_defaults(func=public_contract)

    public_release_check_p = sub.add_parser(
        "public-release-check",
        help="Fail if the checkout still contains private adapters, private product references, account IDs, or live adapter hosts.",
    )
    public_release_check_p.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable issue JSON.")
    public_release_check_p.add_argument(
        "--private-terms-file",
        type=Path,
        help=f"Read private product/client scan terms from an untracked local file in addition to {PUBLIC_RELEASE_PRIVATE_TERMS_ENV}.",
    )
    public_release_check_p.set_defaults(func=public_release_check)

    public_release_export_p = sub.add_parser(
        "public-release-export",
        help="Create a clean git repository candidate for public release, then run public-release-check against it.",
    )
    public_release_export_p.add_argument("--destination", type=Path, required=True, help="Directory to create as the clean public repo candidate.")
    public_release_export_p.add_argument("--write", action="store_true", help="Create the export repo. Without --write, print the plan only.")
    public_release_export_p.add_argument("--force", action="store_true", help=f"Replace an existing destination only when it contains {PUBLIC_RELEASE_EXPORT_MARKER} from a prior export.")
    public_release_export_p.add_argument(
        "--include-untracked",
        action="store_true",
        help="Include untracked, non-ignored files. Intended for in-progress validation only; public release exports should run from a committed tree.",
    )
    public_release_export_p.add_argument(
        "--include-working-tree",
        action="store_true",
        help="Include dirty tracked working-tree content. Intended for in-progress validation only; public release exports should run from a committed tree.",
    )
    public_release_export_p.add_argument(
        "--allow-empty-private-terms",
        action="store_true",
        help=f"Allow export without {PUBLIC_RELEASE_PRIVATE_TERMS_ENV} or --private-terms-file; use only for repos with no private product/client terms.",
    )
    public_release_export_p.add_argument(
        "--private-terms-file",
        type=Path,
        help=f"Read private product/client scan terms from an untracked local file in addition to {PUBLIC_RELEASE_PRIVATE_TERMS_ENV}.",
    )
    public_release_export_p.set_defaults(func=public_release_export)

    registry_package_p = sub.add_parser(
        "registry-package",
        help=(
            "Generate a registry package tree: the real PyPI package (wrapper + "
            "embedded tree + stamped snapshot manifest) or the npm namespace pointer "
            "(one source of truth for the registry copy)."
        ),
    )
    registry_package_p.add_argument(
        "--registry",
        required=True,
        choices=list(REGISTRY_PACKAGE_REGISTRIES),
        help="Which registry's package tree to generate; the registry determines the payload.",
    )
    registry_package_p.add_argument("--version", required=True, help="Package version (X.Y.Z).")
    registry_package_p.add_argument(
        "--channel",
        default="stable",
        choices=sorted(FRAMEWORK_CHANNELS),
        help=(
            "Release channel stamped into the pypi payload's snapshot manifest "
            "(ignored for npm)."
        ),
    )
    registry_package_p.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Directory to materialize the package tree into.",
    )
    registry_package_p.add_argument(
        "--write",
        action="store_true",
        help="Write the package tree. Without --write, print the plan only.",
    )
    registry_package_p.set_defaults(func=registry_package)

    release_tail_p = sub.add_parser(
        "release-tail",
        help=(
            "Run the whole release tail: public export, fast-forward mirror commit, "
            "tag, GitHub Release, registry publish, drift check."
        ),
    )
    release_tail_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the full plan and mutate nothing. The default posture for an agent.",
    )
    release_tail_p.add_argument(
        "--skip-registry",
        action="store_true",
        help=(
            "One-time bootstrap: push the mirror, tag, and create the Release as a DRAFT "
            "(a draft fires no publish workflow). Rerun without this flag to publish it."
        ),
    )
    release_tail_p.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Seconds to wait for the publish workflow runs to reach a terminal state.",
    )
    release_tail_p.add_argument(
        "--poll-interval",
        type=int,
        default=15,
        help="Seconds between publish-run polls.",
    )
    release_tail_p.add_argument(
        "--allow-empty-private-terms",
        action="store_true",
        help="Allow the export gate to run with no private terms configured.",
    )
    release_tail_p.add_argument(
        "--private-terms-file",
        type=Path,
        help="Read private product/client scan terms from an untracked local file.",
    )
    release_tail_p.set_defaults(func=release_tail)

    release_drift_p = sub.add_parser(
        "release-drift-check",
        help="Report the repo, npm, and PyPI versions and fail when any surface has drifted.",
    )
    release_drift_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable drift JSON.",
    )
    release_drift_p.set_defaults(func=release_drift_check)


def _register_misc_3(sub) -> None:

    secret_status_p = sub.add_parser(
        "secret-status",
        help=(
            "Report WHERE a named secret is reachable from (process env, config env, secrets file) "
            "without printing its value; exit 1 only when it is absent from all three."
        ),
    )
    secret_status_p.add_argument(
        "--name",
        required=True,
        help="UPPER_CASE environment variable name to probe, e.g. STRIPE_API_KEY.",
    )
    secret_status_p.set_defaults(func=secret_status)


def _register_release_3(sub) -> None:
    cut_release_p = sub.add_parser(
        "cut-release",
        help="Build the release boundary for the current VERSION: checksums manifest + the signed-tag command (no git mutation by default).",
    )
    cut_release_p.add_argument("--dry-run", action="store_true", help="Print the plan without writing the checksums manifest.")
    cut_release_p.add_argument("--create-tag", action="store_true", help="Create the annotated git tag locally (not pushed).")
    cut_release_p.add_argument("--sign", action="store_true", help="Sign the tag (git tag -s) instead of -a.")
    cut_release_p.add_argument("--force", action="store_true", help="Overwrite an existing tag (with --create-tag).")
    cut_release_p.set_defaults(func=cut_release)


def _register_adapters_2(sub) -> None:
    init_adapter = sub.add_parser("init-project-adapter", help=f"Scaffold a new repo-local project adapter at {REPO_LOCAL_ADAPTER_FILE} and print bootstrap/render/start next steps.")
    init_adapter.add_argument("--target", type=Path, default=Path("."))
    init_adapter.add_argument("--output", type=Path, help="Override the source adapter path; defaults to <target>/.minervit/adapter.json.")
    init_adapter.add_argument("--project-name")
    init_adapter.add_argument("--repo")
    init_adapter.add_argument("--overwrite", action="store_true")
    init_adapter.set_defaults(func=init_project_adapter)


def _register_misc_8(sub) -> None:

    status = sub.add_parser("methodology-status", help="Report plugin version, lock state, adapter/plugin-version drift, and lane state paths.")
    status.add_argument("--project", type=Path)
    status.add_argument("--target", type=Path, default=Path("."))
    status.add_argument("--no-remote", action="store_true")
    # Codex R1 P2. `lane-start` already carries this flag, and the supported two-step startup runs
    # lane-start and then `methodology-status --fail-on-drift`. Without the same flag here, a lane
    # that started successfully under `--allow-non-main` failed the very next required gate -- an
    # escape that works on one surface and not the next is not an escape.
    status.add_argument(
        "--allow-non-main",
        action="store_true",
        help=(
            "Allow a non-release-branch methodology checkout for this run, matching lane-start's "
            "flag of the same name (one-shot deviation; MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1 is "
            "the environment equivalent)."
        ),
    )
    # Two flags, one behaviour. The 2026-08-28 demolition removed the debt gates, the control
    # posture and the remediation marker, so exit 2, `--posture` and `--enter-remediation-on-debt`
    # became text describing nothing -- accepted, documented, inert. They are gone; adapter drift
    # is the one blocking condition left, and both flags below make it exit 1.
    status.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit 1 when the generated files have drifted from the adapter, printing "
        "'methodology_status_blocking: integrity - drift' as the last line. Exit 0 otherwise.",
    )
    status.add_argument(
        "--strict",
        action="store_true",
        help="Identical to --fail-on-drift: exit 1 on adapter drift. Kept as a separate spelling "
        "because existing scripts and CI steps pass it.",
    )
    status.set_defaults(func=methodology_status)


def _register_events_1(sub) -> None:

    decision_record_p = sub.add_parser(
        "decision-record",
        help="Write a machine-local structured decision-ledger entry (works with narration off).",
    )
    decision_record_p.add_argument("--project", type=Path)
    decision_record_p.add_argument("--target", type=Path, default=Path("."))
    decision_record_p.add_argument(
        "--summary", required=True, help="One-line statement of the decision (non-blank)."
    )
    decision_record_p.add_argument(
        "--rationale", required=True, help="Why the decision was made (non-blank)."
    )
    decision_record_p.add_argument("--alternatives", help="Options considered and rejected.")
    decision_record_p.add_argument(
        "--reversibility", choices=["reversible", "hard-to-reverse"], default="reversible"
    )
    decision_record_p.add_argument(
        "--surface", action="append", help="A surface this decision touches; repeatable."
    )
    decision_record_p.add_argument(
        "--next", default="proceed as decided", help="Next action after the decision."
    )
    decision_record_p.add_argument(
        "--awaiting-operator",
        action="store_true",
        help=(
            "Mark this decision as explicitly awaiting an operator answer -- the authoritative "
            "signal `tautline inbox` reads, independent of how --next is phrased."
        ),
    )
    decision_record_p.add_argument("--goal")
    decision_record_p.add_argument("--milestone")
    decision_record_p.add_argument("--pr")
    decision_record_p.set_defaults(func=decision_record)

    lane_status_p = sub.add_parser(
        "lane-status",
        help="Report lane currency (branch/upstream/version drift). Report-only; never blocks.",
    )
    lane_status_p.add_argument("--target", type=Path, default=Path("."))
    lane_status_p.add_argument(
        "--hook",
        action="store_true",
        help="Hook-safe mode: contained, always exits 0.",
    )
    lane_status_p.add_argument(
        "--json",
        action="store_true",
        help="Emit the tautline-lane-status/v1 payload instead of the report.",
    )
    lane_status_p.set_defaults(func=lane_status)


# --- GITHUB SURFACE WIRING (Tier 1 salvage, track S2) -------------------------------------------
# Both verbs here are plain REST against api.github.com (or `gh api`), never Projects GraphQL, and
# neither depends on a project adapter -- `github-budget-status` never did, and
# `stakeholder-question` had its adapter/board coupling dropped on purpose. `github_budget_status`
# itself lives above, beside the ghutil primitives it orchestrates; `stakeholder_question` delegates
# to its own module the same way `backlog` below delegates to `backlog.py`.
def stakeholder_question(args: argparse.Namespace) -> int:
    from tautline_methodology import stakeholder_question as stakeholder_question_mod

    return stakeholder_question_mod.stakeholder_question_command(args)


# --- BUILDER IDENTITY WIRING (builder lanes, Lane C) --------------------------------------------
# Three thin delegations to `builder_token.py`, following `stakeholder_question` above: the engine
# stays in its own module and this file only wires argv to it.
def builder_token(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_token as builder_token_mod

    return builder_token_mod.builder_token_command(args)


def lane_role(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_token as builder_token_mod

    return builder_token_mod.lane_role_command(args)


def builder_env(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_token as builder_token_mod

    return builder_token_mod.builder_env_command(args)


def _register_builder_identity_1(sub) -> None:
    token_p = sub.add_parser(
        "builder-token",
        help="With --print, write the builder lane's GitHub token (a cached GitHub App "
        "installation token); with --status, prove its scope without printing it. One of the two "
        "is required -- there is no default, because the default would be a credential. Plain "
        "REST against api.github.com.",
    )
    token_p.add_argument("--target", type=Path, default=Path("."))
    # Mutually exclusive because the two modes make opposite promises about stdout: --print writes
    # a bare credential, --status promises never to. Letting one silently win is how a token ends
    # up in a status log somebody pastes into an issue. Neither is the default, for the same
    # reason: a bare `builder-token` used to print a live token to whoever was exploring the verb.
    token_mode = token_p.add_mutually_exclusive_group()
    token_mode.add_argument(
        "--print",
        dest="print_token",
        action="store_true",
        help="Write ONLY the token to stdout. For `GH_TOKEN=\"$(tautline builder-token "
        '--print)"`.',
    )
    token_mode.add_argument(
        "--status",
        action="store_true",
        help="Print the identity WITHOUT the token: source, app id, installation id, bot login, "
        "expiry, and the permissions GitHub granted -- which is how an operator proves Projects "
        "is read-only for builder lanes.",
    )
    token_p.set_defaults(func=builder_token)

    role_p = sub.add_parser(
        "lane-role",
        help="Mark this checkout as a builder lane, return it to human, or report which marker "
        "decided the role. Writes .ai-work/lane-role; humans are never builders by default.",
    )
    role_p.add_argument(
        "action",
        choices=["builder", "human", "status"],
        help="builder: write the marker. human: remove it. status: print the role and the marker "
        "(env, file, or default) that decided it.",
    )
    role_p.add_argument("--target", type=Path, default=Path("."))
    role_p.set_defaults(func=lane_role)

    env_p = sub.add_parser(
        "builder-env",
        help="Print the shell snippet a BUILDER lane evals to take on the builder role, token and "
        "guard shim. Prints only; a human never evals it. See docs/builder-lanes.md.",
    )
    env_p.add_argument("--target", type=Path, default=Path("."))
    env_p.set_defaults(func=builder_env)
# --- END BUILDER IDENTITY WIRING ----------------------------------------------------------------


def _register_github_1(sub) -> None:
    budget_p = sub.add_parser(
        "github-budget-status",
        help="Report GitHub REST/GraphQL rate-limit budget, cache health, and (with --identity) "
        "this lane's identity. Plain REST, never Projects GraphQL. Always exits 0: an unreachable "
        "API is a printed finding, not a failure.",
    )
    budget_p.add_argument("--target", type=Path, default=Path("."))
    budget_p.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the cached rate-limit status and fetch fresh budget data.",
    )
    budget_p.add_argument(
        "--identity",
        action="store_true",
        help="Force the GitHub identity report on for this invocation, whatever "
        "MINERVIT_GITHUB_IDENTITY is set to, and mint/refresh this lane's identity record. This "
        "verb is where an operator asks the question on purpose, so the master knob should not "
        "silence the answer here (MINERVIT_GITHUB_IDENTITY=0 still wins over the flag).",
    )
    budget_p.set_defaults(func=github_budget_status)

    stakeholder_question_p = sub.add_parser(
        "stakeholder-question",
        help="Post (ask) or report (list) a tagged clarification question as a GitHub issue/PR "
        "comment. Plain REST, no project adapter. No board/label sync, no --strict, no "
        "answered write-back -- `list` infers open vs answered from later replies every time "
        "it runs, never stores the verdict.",
    )
    stakeholder_question_p.add_argument(
        "action",
        choices=["ask", "list"],
        help="ask: post a new tagged question on --issue. list: report every tagged question on "
        "--issue as open or answered. Answered = the first comment, anywhere after the tagged "
        "one, posted by someone OTHER than whoever posted the tagged comment -- a positional "
        "check, not a read of what the reply says.",
    )
    stakeholder_question_p.add_argument(
        "--issue",
        required=True,
        help="Issue/PR number (requires --repo) or a full github.com issue/PR URL.",
    )
    stakeholder_question_p.add_argument(
        "--repo",
        help="owner/name. Required when --issue is a bare number; must agree with --issue when "
        "--issue is a URL.",
    )
    stakeholder_question_p.add_argument("--question", help="ask: the question text (required for ask).")
    stakeholder_question_p.add_argument("--why", help="ask: why it matters (optional).")
    stakeholder_question_p.add_argument(
        "--needed-for", dest="needed_for", help="ask: what the answer unblocks (optional)."
    )
    stakeholder_question_p.add_argument(
        "--stakeholder", help="ask: who to @-mention in the comment (optional; no mention if omitted)."
    )
    stakeholder_question_p.add_argument(
        "--question-id",
        dest="question_id",
        help="ask: explicit tag id (default: derived from --issue/--question/--needed-for). "
        "Reposting the same id is a no-op.",
    )
    stakeholder_question_p.set_defaults(func=stakeholder_question)
# --- END GITHUB SURFACE WIRING -------------------------------------------------------------------


def _register_events_2(sub) -> None:
    """Tier 1 salvage, Track S1: the ledger-reader family (decisions-report, event-tail,
    event-log-path, event-rotate) plus the new operator-inbox v1. Kept as its own registrar,
    separate from _register_events_1 above, so this whole track's parser wiring is one
    self-contained diff."""

    decisions_report_p = sub.add_parser(
        "decisions-report",
        help=(
            "Read surface over the decision ledger: filter by time/reversibility/text; table or "
            "--json (read-only)."
        ),
    )
    decisions_report_p.add_argument(
        "--target",
        type=Path,
        action="append",
        help="Lane root; repeatable (default `.`). Same-repo worktrees share one event log.",
    )
    decisions_report_p.add_argument(
        "--since",
        help="Lower time bound (exclusive): a duration (30m/24h/7d) or ISO-8601; zone-less = UTC.",
    )
    decisions_report_p.add_argument(
        "--until", help="Upper time bound (inclusive): an ISO-8601 timestamp; zone-less = UTC."
    )
    decisions_report_p.add_argument(
        "--reversibility",
        choices=list(DECISION_REVERSIBILITY_ENUM),
        help="Only decisions recorded with this --reversibility.",
    )
    decisions_report_p.add_argument(
        "--grep",
        help=(
            "Case-insensitive substring match over summary, rationale, alternatives, "
            "surfaces, next, goal, milestone, pr."
        ),
    )
    decisions_report_p.add_argument(
        "--goal", help="Only decisions whose recorded goal equals this value."
    )
    decisions_report_p.add_argument(
        "--json",
        action="store_true",
        help="Emit one tautline-decisions-report/v1 envelope object instead of a table.",
    )
    decisions_report_p.set_defaults(func=decisions_report)

    event_path_p = sub.add_parser(
        "event-log-path",
        help="Print the human and JSONL event log paths plus the event-tail command hint.",
    )
    event_path_p.add_argument("--project", type=Path)
    event_path_p.add_argument("--target", type=Path, default=Path("."))
    event_path_p.set_defaults(func=event_log_path)

    event_tail_p = sub.add_parser(
        "event-tail", help="Print the last N lines of the lane's human-readable event log."
    )
    event_tail_p.add_argument("--project", type=Path)
    event_tail_p.add_argument("--target", type=Path, default=Path("."))
    event_tail_p.add_argument("--lines", type=int, default=80)
    event_tail_p.set_defaults(func=event_tail)

    event_rotate_p = sub.add_parser(
        "event-rotate",
        help="Rotate the human and JSONL event logs when over size (or always with --force).",
    )
    event_rotate_p.add_argument("--project", type=Path)
    event_rotate_p.add_argument("--target", type=Path, default=Path("."))
    event_rotate_p.add_argument(
        "--force", action="store_true", help="Rotate regardless of current size."
    )
    event_rotate_p.set_defaults(func=event_rotate)

    inbox_p = sub.add_parser(
        "inbox",
        help=(
            "Pending operator decisions, explicit answers, and resume acknowledgements."
        ),
        description=(
            "Lists decision-ledger entries recorded as PENDING an operator answer, across one "
            "or more repos, newest first. PENDING is two signals, checked in this order: "
            "(1) authoritative -- `decision-record --awaiting-operator` set an explicit flag on "
            'the record; (2) fallback, legacy rows only -- --next contains "awaiting" '
            "(case-insensitive substring, not a fuzzy classifier). Answers stay visible to the "
            "source lane until --ack after incorporation. Answer text is never executed."
        ),
    )
    inbox_p.add_argument(
        "--target",
        type=Path,
        action="append",
        help=(
            "Repo root to include; repeatable (default `.`). Same-repo worktrees share one "
            "event log."
        ),
    )
    inbox_p.add_argument(
        "--json",
        action="store_true",
        help="Emit one tautline-inbox/v1 envelope instead of a table.",
    )
    inbox_action = inbox_p.add_mutually_exclusive_group()
    inbox_action.add_argument("--answer", metavar="ID", help="Answer a pending decision by its printed id.")
    inbox_action.add_argument("--answers", action="store_true", help="Read unacknowledged answers for the target lane(s).")
    inbox_action.add_argument("--ack", metavar="ID", help="Acknowledge an answer after incorporating it.")
    inbox_p.add_argument("--text", help="The answer text (with --answer). Never executed.")
    inbox_p.set_defaults(func=inbox)


# --- LEAN PROFILE WIRING ---
# The whole lean profile's footprint in this file: one handler that delegates, one registrar. The
# implementation lives in `tautline_methodology.lean`, which imports nothing from here, so the
# demolition of the surrounding machinery can proceed without touching it. Preserve this block and
# its call in `main()`; everything else about the lean profile is somewhere else on purpose.
def slim(args: argparse.Namespace) -> int:
    return lean.slim_command(args)


def backlog(args: argparse.Namespace) -> int:
    from tautline_methodology import backlog as backlog_mod

    return backlog_mod.backlog_command(args)


def doctor(args: argparse.Namespace) -> int:
    from tautline_methodology import doctor as doctor_mod

    return doctor_mod.doctor_command(args, framework_repo=canonical_methodology_repo())


def red_green_check(args: argparse.Namespace) -> int:
    from tautline_methodology import doctor as doctor_mod

    return doctor_mod.red_green_check_command(args)


def _register_lean_1(sub) -> None:
    slim_p = sub.add_parser(
        "slim",
        help=(
            "Migrate an adapted project to the lean profile: archive its process artifacts, "
            "remove the framework's hooks, rewrite its config to lean-1, and render the thin "
            "adapter. Never deletes; --dry-run shows the plan."
        ),
    )
    slim_p.add_argument("--target", type=Path, default=Path("."))
    slim_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every change without making one.",
    )
    slim_p.add_argument(
        "--keep-agent-hooks",
        action="store_true",
        help=(
            "Leave ~/.claude/settings.json alone. The framework's hooks are installed there, not "
            "in the project, so this opts OUT of removing the ones you can actually feel."
        ),
    )
    slim_p.set_defaults(func=slim)

    backlog_p = sub.add_parser(
        "backlog",
        help=(
            "Read and move this project's backlog: list|add|take|done, against the provider its "
            "config names (local queue file, GitHub issues, or Jira). Nothing syncs."
        ),
    )
    backlog_p.add_argument(
        "action",
        choices=["list", "add", "take", "done"],
        help=(
            "list: the open queue, top first. add: file a new item (give it a title). "
            "take: mark an item in progress (no id takes the top). done: close an item."
        ),
    )
    backlog_p.add_argument(
        "item",
        nargs="?",
        help="The title for `add`; the item id for `take` and `done`. `take` with no id takes "
        "the top of the queue.",
    )
    backlog_p.add_argument("--target", type=Path, default=Path("."))
    backlog_p.add_argument(
        "--body",
        default="",
        help="The one-page spec for `add`. Everything else about the item is its title.",
    )
    backlog_p.set_defaults(func=backlog)


# --- BUILDER LANE GITHUB WIRING ---
# The builder lane's whole GitHub footprint in this file: three handlers that delegate, one
# registrar. The implementation lives in `tautline_methodology.builder_github`, which imports
# nothing from here -- same direction as `lean` and `backlog` above, and for the same reason.
def board(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_github

    return builder_github.board_command(args)


def issue(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_github

    return builder_github.issue_command(args)


def debt(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_github

    return builder_github.debt_command(args)


def _at_least_one(raw: str) -> int:
    """A count that a Python slice would silently misread if it were allowed through.

    `--last 0` reaches `comments[-0:]`, which is `comments[0:]` -- the WHOLE thread, presented as
    "the last nothing". `--last -1` drops the last comment instead of showing it. Neither is
    visible to the caller, because the output looks like a comment thread either way, so the check
    belongs in argparse where the value is rejected before it reaches a slice at all.
    """
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, not {value}")
    return value


def _register_builder_verbs_1(sub) -> None:
    """`board`, `issue`, `debt`: the ENTIRE GitHub surface a builder lane gets.

    Three parsers rather than one `builder` parent with nested subcommands, because these are typed
    by an agent dozens of times a session and `tautline board list` is the shape a reader of the
    generated adapter can hold in their head. Every one reads its coordinates from the lean
    adapter's `builderGithub` block; none takes a `--repo`, an `--owner` or a project number, so a
    lane cannot be aimed at a board its project did not name.
    """
    board_p = sub.add_parser(
        "board",
        help=(
            "Read the product board (GitHub Projects): list|show|fields. Read-only -- there is no "
            "verb here that moves a card, because the board's order is the director's statement."
        ),
    )
    board_p.add_argument(
        "action",
        choices=["list", "show", "fields"],
        help=(
            "list: the board in its own position order. show: one card plus its issue body. "
            "fields: the LIVE Status/Item Type option names, so nothing has to guess a column."
        ),
    )
    board_p.add_argument("number", nargs="?", help="The issue number, for `show`.")
    board_p.add_argument("--target", type=Path, default=Path("."))
    board_p.add_argument(
        "--status",
        action="append",
        default=[],
        metavar="NAME",
        help="Only this status (repeatable). Naming a hidden status also unhides it.",
    )
    board_p.add_argument("--type", metavar="NAME", help="Only this Item Type.")
    board_p.add_argument("--label", metavar="NAME", help="Only cards carrying this issue label.")
    board_p.add_argument("--text", metavar="SUBSTR", help="Only titles containing this substring.")
    board_p.add_argument(
        "--all",
        action="store_true",
        help="Include the statuses `builderGithub.hiddenStatuses` hides (Done, by default).",
    )
    board_p.add_argument("--json", action="store_true", help="Emit a stable JSON envelope.")
    board_p.add_argument(
        "--fresh",
        action="store_true",
        help="Bypass the 5-minute board cache and re-read the project.",
    )
    board_p.set_defaults(func=board)

    issue_p = sub.add_parser(
        "issue",
        help=(
            "Read and comment on the board repo's issues: show|comments|find|comment. The only "
            "writes are comments -- never a label, a state or an assignee."
        ),
    )
    issue_p.add_argument(
        "action",
        choices=["show", "comments", "find", "comment"],
        help=(
            "show: body, state, labels, assignees and board status. comments: the thread, oldest "
            "first. find: issues by label and text. comment: post one stamped comment."
        ),
    )
    issue_p.add_argument("number", nargs="?", help="The issue number.")
    issue_p.add_argument("--target", type=Path, default=Path("."))
    issue_p.add_argument(
        "--last",
        type=_at_least_one,
        metavar="K",
        help="comments: only the last K (K >= 1).",
    )
    issue_p.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="L",
        help="find: only issues carrying this label (repeatable, filtered server-side).",
    )
    issue_p.add_argument(
        "--text",
        metavar="Q",
        help="find: case-insensitive substring over title and body, applied after the fetch.",
    )
    issue_p.add_argument(
        "--state",
        choices=["open", "closed", "all"],
        default="open",
        help="find: which issues to fetch (default: open).",
    )
    issue_p.add_argument("--body", help="comment: the comment text.")
    issue_p.add_argument("--body-file", help="comment: a file holding the comment text.")
    issue_p.add_argument("--json", action="store_true", help="Emit a stable JSON envelope.")
    issue_p.add_argument(
        "--fresh", action="store_true", help="Bypass the board cache when reading board status."
    )
    issue_p.set_defaults(func=issue)

    debt_p = sub.add_parser(
        "debt",
        help=(
            "File technical debt as a labelled issue -- and NOTHING else: no assignee, no "
            "milestone, and never on the product board."
        ),
    )
    debt_p.add_argument("action", choices=["file"], help="file: create one debt issue.")
    debt_p.add_argument("--target", type=Path, default=Path("."))
    debt_p.add_argument("--title", help="One line naming the debt.")
    debt_p.add_argument("--body", help="The finding.")
    debt_p.add_argument("--body-file", help="A file holding the finding.")
    debt_p.add_argument(
        "--refs",
        action="append",
        type=int,
        default=[],
        metavar="N",
        help="An issue this debt came out of (repeatable); rendered as `Refs #N`.",
    )
    debt_p.add_argument("--json", action="store_true", help="Emit a stable JSON envelope.")
    debt_p.set_defaults(func=debt)
# --- END BUILDER LANE GITHUB WIRING ---


def _register_diagnostics_1(sub) -> None:
    """`doctor` + `red-green-check`: the Tier-1 diagnostics salvage. Both handlers live in
    `tautline_methodology.doctor`, which -- like `lean` above -- imports nothing from here."""
    doctor_p = sub.add_parser(
        "doctor",
        help=(
            "Four advisory checks -- branch-liveness, framework-staleness, skip-lint, and "
            "--watch'd monitor-liveness: each prints OK, FINDING, or UNKNOWN(reason). Always "
            "exits 0; a finding is reported, never enforced."
        ),
    )
    doctor_p.add_argument(
        "--target", type=Path, default=Path("."), help="Git checkout the branch-liveness and skip-lint checks read."
    )
    doctor_p.add_argument(
        "--base",
        default=None,
        help=(
            "skip-lint diff base ref (default: origin/<latestCode.base> read from this target's "
            "own .tautline.json when present, else origin/main)."
        ),
    )
    doctor_p.add_argument(
        "--diff-file",
        type=Path,
        help="skip-lint: read the unified diff from this file instead of running git (for tests/CI).",
    )
    doctor_p.add_argument(
        "--watch",
        action="append",
        default=[],
        metavar="PID:LOGPATH",
        help="Repeatable. Run monitor-liveness for this PID + log file; skipped entirely when omitted.",
    )
    doctor_p.add_argument(
        "--stale-after", default="10m", help="monitor-liveness staleness threshold, e.g. 10m, 1h (default: 10m)."
    )
    doctor_p.set_defaults(func=doctor)

    redgreen_p = sub.add_parser(
        "red-green-check",
        help=(
            "Mutate one symbol of --file and run --test-command against it: report "
            "killed/survived/inconclusive. The file is always restored. Report-only -- always "
            "exits 0."
        ),
    )
    redgreen_p.add_argument("--target", type=Path, default=Path("."), help="Working directory the test command runs in.")
    redgreen_p.add_argument("--file", type=Path, required=True, help="Source file to mutate.")
    redgreen_p.add_argument(
        "--test-command", required=True, help="Command (run via bash -c in --target) that should FAIL when the code breaks."
    )
    redgreen_p.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds allowed per test-command run (baseline and each mutation), default 600. A run "
        "that hits this reports inconclusive(timeout) rather than hanging.",
    )
    redgreen_p.set_defaults(func=red_green_check)
# --- END LEAN PROFILE WIRING ---


# --- LEAN INIT WIRING ---
# `tautline init`: the setup interview for a repo that has never carried a Tautline adapter.
# Same shape as the block above -- one handler that delegates to `tautline_methodology.lean`, one
# registrar -- and the same reason: the implementation has no business depending on the monolith.
def init(args: argparse.Namespace) -> int:
    return lean.init_command(args)


def _register_lean_2(sub) -> None:
    init_p = sub.add_parser(
        "init",
        help=(
            "Interactive setup interview (<=8 questions; every question also has a flag) that "
            "writes a lean .tautline.json, validates it, and renders CLAUDE.md/AGENTS.md. "
            "Refuses to overwrite an existing config without --force."
        ),
    )
    init_p.add_argument("--target", type=Path, default=Path("."))
    init_p.add_argument("--name", help="Project name.")
    init_p.add_argument("--repo", help="owner/name. Empty string means no repo.")
    init_p.add_argument("--branch", help="Integration branch.")
    init_p.add_argument("--test-cmd", dest="test_cmd", help="The gate command.")
    init_p.add_argument(
        "--backlog", choices=lean.BACKLOG_PROVIDERS, help="Where the backlog lives."
    )
    init_p.add_argument("--backlog-path", help="local provider: queue file path (default QUEUE.md).")
    init_p.add_argument("--backlog-repo", help="github provider: owner/name.")
    init_p.add_argument("--backlog-label", help="github provider: issue label (default backlog).")
    init_p.add_argument("--backlog-site", help="jira provider: https://your-domain.atlassian.net")
    init_p.add_argument("--backlog-project", help="jira provider: project key.")
    init_p.add_argument(
        "--backlog-board", help="jira provider: board id, a positive number (optional)."
    )
    init_p.add_argument(
        "--work-coordination", action=argparse.BooleanOptionalAction, default=None,
        help="Advisory local work-manifest guidance. Default on for new projects.",
    )
    init_p.add_argument(
        "--handoffs",
        action="store_true",
        default=None,
        help="Turn on continuity handoffs (.ai-continuity/HANDOFF.md). Default off.",
    )
    init_p.add_argument(
        "--rule",
        dest="rules",
        action="append",
        default=None,
        help="A project rule an agent would otherwise get wrong. Repeatable, up to 3.",
    )
    init_p.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive: accept the prefilled default for every question not given a flag.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing .tautline.json (or .minervit-ai-delivery.json) instead of refusing.",
    )
    init_p.set_defaults(func=init)
# --- END LEAN INIT WIRING ---


# --- BUILDER GUARD WIRING -----------------------------------------------------------------------
# The guard's whole implementation lives in `builder_guard.py` and is reached lazily, the same way
# `stakeholder_question` is: that module imports `cli` back (for the event ledger), and a module-
# scope import here would close the loop.
def builder_guard(args: argparse.Namespace) -> int:
    from tautline_methodology import builder_guard as builder_guard_mod

    return builder_guard_mod.builder_guard_command(args)


def _register_builder_guard_1(sub) -> None:
    guard_p = sub.add_parser(
        "builder-guard",
        help=(
            "Keep BUILD AGENTS off GitHub issues and the project board except through "
            "`tautline board|issue|debt`. A no-op for humans: it engages only when "
            "builder_role_active() says builder, and the default is human."
        ),
    )
    guard_p.add_argument("--target", type=Path, default=Path("."))
    guard_p.add_argument(
        "--hook",
        action="store_true",
        help="Read a PreToolUse payload on stdin; exit 2 (deny, reason on stderr) or 0 (allow).",
    )
    guard_p.add_argument(
        "--argv",
        action="store_true",
        help="Judge an already-split argv after `--`; exit 2 or 0. The `gh` shim's entry point.",
    )
    guard_p.add_argument(
        "--shim-dir",
        dest="shim_dir",
        action="store_true",
        help="Create/refresh the `gh` shim directory and print its path, for lanes without hooks.",
    )
    guard_p.add_argument(
        "--report",
        action="store_true",
        help="Print how many denials this lane's event log holds, and the last 20 of them.",
    )
    guard_p.add_argument("command", nargs=argparse.REMAINDER)
    guard_p.set_defaults(func=builder_guard)
# --- END BUILDER GUARD WIRING -------------------------------------------------------------------


def _register_work_1(sub) -> None:
    from tautline_methodology import work

    work_p = sub.add_parser("work", help="Declare work and see local or Git-shared peers (advisory).")
    work.configure(work_p)
    work_p.set_defaults(func=work.command)


def evidence(args: argparse.Namespace) -> int:
    from tautline_methodology.evidence import evidence_command

    return evidence_command(args)


def health(args: argparse.Namespace) -> int:
    from tautline_methodology.health import health_command

    return health_command(args)


def _register_evidence_health_1(sub) -> None:
    evidence_p = sub.add_parser("evidence", help="Record an explicit command once or inspect its receipt. No gates.")
    evidence_p.add_argument("action", choices=("run", "status"))
    evidence_p.add_argument("--target", type=Path, default=Path("."))
    evidence_p.add_argument("--json", action="store_true", help="Machine-readable status.")
    evidence_p.add_argument("command", nargs="*", help="run: executable and arguments after --.")
    evidence_p.set_defaults(func=evidence)

    health_p = sub.add_parser("health", help="Advisory integration and CI snapshot; local unless --remote is given.")
    health_p.add_argument("--target", type=Path, default=Path("."))
    health_p.add_argument("--remote", action="store_true", help="Query live GitHub integration and exact-commit CI (bounded calls).")
    health_p.add_argument("--json", action="store_true")
    health_p.set_defaults(func=health)


def main(argv: list[str] | None = None) -> int:
    # Chokepoint 2 (cli) runs BEFORE argparse so a legacy-name invocation that terminates inside
    # parse_args -- `--help`, a bare no-subcommand error, an invalid subcommand -- still emits the
    # cli sunset warning. The warning is stderr-only and the marker strip is idempotent, so
    # parse_args below runs byte-identically afterward; canonical `tautline` calls carry no marker
    # and stay warning-free, and hook shapes strip silently.
    _consume_legacy_launcher_marker()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    _register_misc_1(sub)
    _register_install_1(sub)
    _register_adapters_1(sub)
    _register_release_2(sub)
    _register_misc_3(sub)
    _register_release_3(sub)
    _register_adapters_2(sub)
    _register_misc_8(sub)
    _register_events_1(sub)
    _register_builder_identity_1(sub)  # --- BUILDER IDENTITY WIRING ---
    _register_github_1(sub)  # --- GITHUB SURFACE WIRING ---
    _register_events_2(sub)
    _register_lean_1(sub)  # --- LEAN PROFILE WIRING ---
    _register_builder_verbs_1(sub)  # --- BUILDER LANE GITHUB WIRING ---
    _register_diagnostics_1(sub)
    _register_lean_2(sub)  # --- LEAN INIT WIRING ---
    _register_builder_guard_1(sub)  # --- BUILDER GUARD WIRING ---
    _register_work_1(sub)
    _register_evidence_health_1(sub)

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    # Codex R1 P2, and the durable half of the rollback note for item 82. An UNKNOWN subcommand is
    # an argparse error: it exits 2 before any handler runs, and `dispatch_command`'s `-hook`
    # fail-open contract is never reached. For an ordinary verb that is correct and loud. For a
    # HOOK it is dangerous in one specific direction: a PreToolUse hook exiting 2 is a DENY, so a
    # machine repinned BELOW the release that introduced a hook would have that hook installed in
    # its settings, invoked by the host, and rejecting every matching tool call -- a rollback that
    # makes the lane less usable than the version it rolled back from.
    #
    # Hooks are the one command family where the host, not a human, chooses the argv, so failing
    # open is the only safe answer. Scoped to the `-hook` suffix (the same discriminator
    # `bin/tautline` already uses for the missing-package case) so a mistyped ordinary verb still
    # fails loudly.
    if raw_argv and raw_argv[0].endswith("-hook") and raw_argv[0] not in sub.choices:
        print(
            f"hook_fail_open: {raw_argv[0]} - not a subcommand of this framework version",
            file=sys.stderr,
        )
        return 0
    # BOTH SPELLINGS. The deprecated alias is documented as behaving identically, and
    # special-casing only the old name meant the NEW one rejected reviewer args starting with `-`
    # before they reached `review_args` -- so the rename was a downgrade for anyone who adopted
    # it. Whatever the alias can do, the name replacing it must do.
    if raw_argv and raw_argv[0] == "evidence" and "--" in raw_argv:
        # Parse only our options. Older Python 3.12 argparse versions lose a trailing
        # nargs="*" positional after --target; child flags must never be parsed as ours.
        boundary = raw_argv.index("--")
        args = parser.parse_args(raw_argv[:boundary])
        if args.action != "run" or args.command:
            parser.error("evidence commands belong after -- and require the run action")
        args.command = raw_argv[boundary + 1:]
    elif raw_argv and raw_argv[0] in ("plan-review-native", "codex-plan-review"):
        args, unknown_args = parser.parse_known_args(raw_argv)
        if unknown_args:
            args.review_args = [*unknown_args, *(getattr(args, "review_args", None) or [])]
    else:
        args = parser.parse_args(raw_argv)
    if getattr(args, "write", False) and getattr(args, "check", False):
        raise SystemExit("--write and --check are mutually exclusive")
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    return dispatch_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
