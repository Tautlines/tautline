"""T1: the git-backed update probe (framework_update_probe).

The probe is display-only discovery: it reports the genuinely-available framework version for a
pin's channel so the session-start surfaces (T2) can PRINT it. It never feeds
framework_update_decision / framework_available_version. Fail-open is a hard invariant.

These tests load the CLI engine module (tautline_methodology.cli) anchored on a hermetic HOME and a
fixture git checkout (REPO_ROOT), exactly like tests/test_canonical_repo_resolution.py and
tests/test_maintainer_mode.py (SourceFileLoader gives a fresh module per test). plugin_version() is
monkeypatched to a fixed running version so the fixture never has to keep VERSION and the plugin
manifest in lockstep; VERSION *at the remote sha* is read from real git objects.
"""
import importlib.machinery
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"
# Post the package-split flip (roadmap #11): the engine lives in the package; bin/tautline is a
# thin shim. Load the engine module directly for the fresh-per-test in-process fixture.
CLI_ENGINE_PATH = CLI_PATH.parents[1] / "src" / "tautline_methodology" / "cli.py"

# Every env name that could leak the operator's machine into a probe assertion: the knob (both
# spellings), the env-version override, the freshness window, maintainer mode, and every managed
# key the canonical-repo resolver consults (so canonical resolves to our fixture REPO_ROOT).
PROBE_ENV_NAMES = (
    "TAUTLINE_METHODOLOGY_UPDATE_PROBE",
    "MINERVIT_METHODOLOGY_UPDATE_PROBE",
    "TAUTLINE_METHODOLOGY_AVAILABLE_VERSION",
    "MINERVIT_METHODOLOGY_AVAILABLE_VERSION",
    "TAUTLINE_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "TAUTLINE_METHODOLOGY_MAINTAINER_MODE",
    "MINERVIT_METHODOLOGY_MAINTAINER_MODE",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
)

RUNNING = "0.14.3"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _git_out(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "probe@example.invalid")
    _git(repo, "config", "user.name", "probe")


def _write_version(repo: Path, version: str, message: str) -> str:
    (repo / "VERSION").write_text(version + "\n", encoding="utf-8")
    _git(repo, "add", "VERSION")
    _git(repo, "commit", "-q", "-m", message)
    return _git_out(repo, "rev-parse", "HEAD")


def _make_fixture(
    tmp_path: Path, base: str = RUNNING, root: Path | None = None
) -> tuple[Path, Path, Path]:
    """A bare origin, a `source` authoring clone, and a `canonical` checkout (our REPO_ROOT).

    The canonical starts at `base` on main tracking origin/main and never fetches; a test advances
    the remote through `source` so origin is ahead while canonical HEAD stays behind and the new
    object is absent locally -- the real launch shape. `root` isolates a second checkout under one
    HOME (the shared-cache test builds two).
    """
    root = root or tmp_path
    root.mkdir(parents=True, exist_ok=True)
    remote = root / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(remote)],
        check=True, capture_output=True, text=True,
    )
    source = root / "source"
    _init(source)
    _write_version(source, base, "base methodology")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-q", "-u", "origin", "main")
    canonical = root / "canonical"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(canonical)], check=True, capture_output=True,
        text=True,
    )
    _git(canonical, "config", "user.email", "probe@example.invalid")
    _git(canonical, "config", "user.name", "probe")
    return remote, source, canonical


def _advance_remote(source: Path, version: str, branch: str = "main") -> str:
    """Bump VERSION on `branch` in the authoring clone and push to origin; return the new sha."""
    if branch != "main":
        _git(source, "switch", "-q", "-c", branch, "main")
    sha = _write_version(source, version, f"advance {branch} to {version}")
    _git(source, "push", "-q", "origin", branch)
    if branch != "main":
        _git(source, "switch", "-q", "main")
    return sha


def _load_cli(monkeypatch, home: Path, repo_root: Path):
    for name in PROBE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    loader = importlib.machinery.SourceFileLoader("tautline_cli", str(CLI_ENGINE_PATH))
    spec = importlib.util.spec_from_loader("tautline_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    module._CANONICAL_METHODOLOGY_REPO = None
    module._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    monkeypatch.setattr(module, "plugin_version", lambda: RUNNING)
    return module


class _GitRecorder:
    """Wraps module.run_command and module.run_git, recording every git invocation's argv."""

    def __init__(self, module):
        self.calls: list[list[str]] = []
        real_command = module.run_command
        real_git = module.run_git

        def command(cmd, *args, **kwargs):
            if cmd and cmd[0] == "git":
                self.calls.append(list(cmd))
            return real_command(cmd, *args, **kwargs)

        def git(target, args):
            self.calls.append(["git", "-C", str(target), *args])
            return real_git(target, args)

        module.run_command = command
        module.run_git = git

    def has(self, token: str) -> bool:
        return any(token in call for call in self.calls)


def _cli(monkeypatch, tmp_path, repo_root):
    return _load_cli(monkeypatch, tmp_path / "home", repo_root)


PROJECT = {"repo": "acme/widgets"}
STABLE_PIN = {"channel": "stable", "updatePolicy": "manual"}
EXPERIMENTAL_PIN = {"channel": "experimental", "updatePolicy": "manual"}


# --- Happy path + channel selection ------------------------------------------------------------


def test_probe_reports_newer_version_when_remote_ahead(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] == "0.99.0"
    assert probe["isNewer"] is True
    assert probe["changeKind"] == "minor"
    assert probe["availableSha"] and probe["failureDetail"] is None


def test_probe_uses_pin_channel_branch_never_hardcoded(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    # main stays at base; only the experimental branch is bumped. A hardcoded main probe would miss.
    exp_sha = _advance_remote(source, "0.50.0", branch="experimental")
    cli = _cli(monkeypatch, tmp_path, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, EXPERIMENTAL_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] == "0.50.0"
    assert probe["isNewer"] is True
    assert probe["availableSha"] == exp_sha
    assert rec.has("refs/heads/experimental")
    assert not rec.has("refs/heads/main")


def test_tracking_ref_poisoning_still_newer_without_new_fetch(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    # Poison: fetch updates origin/main (tracking ref) AND brings the object local, but HEAD stays
    # behind. Currency is judged against HEAD only, so the offer must still fire -- fetch-free.
    _git(canonical, "fetch", "-q", "origin", "main")
    cli = _cli(monkeypatch, tmp_path, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] == "0.99.0"
    assert probe["isNewer"] is True
    assert not rec.has("fetch"), "the object was already local; no new fetch was needed"


def test_remote_equal_to_head_is_not_newer_and_never_fetches(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)  # no advance: origin/main == HEAD
    cli = _cli(monkeypatch, tmp_path, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["isNewer"] is False
    assert probe["changeKind"] == "none"
    assert not rec.has("fetch")


def test_local_ahead_compares_fetch_free_with_no_offer(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    # Canonical advances locally past origin (never pushed): the remote sha is an ancestor and so
    # a local object, so VERSION resolves without any fetch and the older remote is not newer.
    _write_version(canonical, "0.98.0", "local ahead of origin")
    cli = _cli(monkeypatch, tmp_path, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["isNewer"] is False
    assert probe["availableVersion"] == RUNNING  # origin/main still carries the base VERSION
    assert not rec.has("fetch")


# --- Cache behaviour ---------------------------------------------------------------------------


def test_ttl_cache_hit_skips_ls_remote(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)
    first = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)
    assert first["source"] == "git" and first["isNewer"] is True

    rec = _GitRecorder(cli)
    second = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)

    assert second["source"] == "cache"
    assert second["availableVersion"] == "0.99.0"
    assert second["isNewer"] is True
    assert not rec.has("ls-remote"), "a fresh cache entry must not re-query the remote"
    assert not rec.has("fetch")


def test_cached_read_recomputes_isnewer_after_update_silences_offer(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    available_sha = _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)
    first = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)
    assert first["isNewer"] is True and first["availableSha"] == available_sha

    # Accept the update: HEAD advances to availableSha and the running version becomes 0.99.0.
    _git(canonical, "fetch", "-q", "origin", "main")
    _git(canonical, "reset", "-q", "--hard", "origin/main")
    monkeypatch.setattr(cli, "plugin_version", lambda: "0.99.0")

    silenced = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)

    assert silenced["source"] == "cache"
    assert silenced["isNewer"] is False  # availableSha == HEAD now
    assert silenced["changeKind"] == "none"


def test_sha_only_cache_upgrades_under_allow_fetch(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)

    # allow_fetch=False and the object is not local: a deliberate sha-only result, cached partial.
    sha_only = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)
    assert sha_only["source"] == "git"
    assert sha_only["availableVersion"] is None
    assert sha_only["availableSha"] and sha_only["isNewer"] is False

    rec = _GitRecorder(cli)
    upgraded = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert upgraded["source"] == "git"  # a miss, not a cache read: it fetched and completed
    assert upgraded["availableVersion"] == "0.99.0"
    assert upgraded["isNewer"] is True
    assert rec.has("fetch")
    # And the entry is now complete: an allow_fetch=False caller is satisfied from cache.
    rec2 = _GitRecorder(cli)
    final = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)
    assert final["source"] == "cache" and final["availableVersion"] == "0.99.0"
    assert not rec2.has("ls-remote")


def test_corrupt_cache_is_treated_as_a_miss(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)
    cache_path = cli._update_probe_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{not json", encoding="utf-8")

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] == "0.99.0"


# --- Remote identity: probe the remote sync will actually fetch from ----------------------------


def test_probe_uses_release_remote_not_branch_tracking_remote(monkeypatch, tmp_path):
    """A fork checkout whose branch tracks a NON-origin remote must still probe origin's release.

    update_methodology_repo fetches via methodology_release_upstream (prefer origin/<channel>), so
    the probe must resolve the SAME remote -- otherwise it reports a version from a remote the sync
    will not take, and the offer names the wrong unblock.
    """
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")  # origin/main -- the release sync would take

    # A second remote 'upstream' the branch will track, carrying a DIFFERENT (wrong) version.
    other = tmp_path / "upstream.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(other)],
        check=True, capture_output=True, text=True,
    )
    other_src = tmp_path / "upstream-src"
    _init(other_src)
    _write_version(other_src, "0.40.0", "upstream fork version")
    _git(other_src, "remote", "add", "origin", str(other))
    _git(other_src, "push", "-q", "-u", "origin", "main")
    _git(canonical, "remote", "add", "upstream", str(other))
    _git(canonical, "fetch", "-q", "upstream", "main")
    _git(canonical, "branch", "--set-upstream-to=upstream/main", "main")
    cli = _cli(monkeypatch, tmp_path, canonical)

    # Sanity: @{u} really is the non-origin remote, but the release resolver still prefers origin.
    assert cli.methodology_release_upstream("stable")[0] == "origin"
    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] == "0.99.0", "must read origin's release, not upstream/main"
    assert probe["availableVersion"] != "0.40.0"
    assert probe["isNewer"] is True


def test_same_remote_name_different_urls_do_not_share_cache(monkeypatch, tmp_path):
    """Two canonical checkouts under one HOME, both 'origin/main' but DIFFERENT remote URLs, must
    not share a discovery entry -- one's fresh cache must never silence or mislead the other."""
    _ra, source_a, canonical_a = _make_fixture(tmp_path, root=tmp_path / "a")
    _advance_remote(source_a, "0.99.0")
    _rb, source_b, canonical_b = _make_fixture(tmp_path, root=tmp_path / "b")
    _advance_remote(source_b, "0.55.0")

    cli = _cli(monkeypatch, tmp_path, canonical_a)  # one HOME => one cache file for both checkouts
    a = cli.framework_update_probe(canonical_a, PROJECT, STABLE_PIN, True, False)
    assert a["source"] == "git" and a["availableVersion"] == "0.99.0"

    # Switch REPO_ROOT to checkout B (same HOME/cache). Its key differs by URL identity, so B's
    # probe is a MISS against A's entry and reads B's OWN remote instead of A's 0.99.0.
    monkeypatch.setattr(cli, "REPO_ROOT", canonical_b)
    cli._CANONICAL_METHODOLOGY_REPO = None
    cli._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    b = cli.framework_update_probe(canonical_b, PROJECT, STABLE_PIN, True, False)

    assert b["source"] == "git"
    assert b["availableVersion"] == "0.55.0", "B must read its own remote, not A's cached version"
    assert b["availableVersion"] != "0.99.0"


# --- Failure classification (fail-open) --------------------------------------------------------


def test_unreachable_remote_sets_failed_with_detail(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    _git(canonical, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    cli = _cli(monkeypatch, tmp_path, canonical)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "failed"
    assert probe["failureDetail"]
    assert probe["availableVersion"] is None
    assert probe["availableSha"] is None
    assert probe["isNewer"] is False


def test_unparsable_version_after_ls_remote_is_sha_only_not_failed(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    # ls-remote succeeds, but VERSION at the tip is garbage: a metadata failure degrades to sha-only
    # (source:"git", availableVersion=None), it must NEVER become source:"failed".
    _advance_remote(source, "not-a-version")
    cli = _cli(monkeypatch, tmp_path, canonical)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "git"
    assert probe["availableVersion"] is None
    assert probe["availableSha"]
    assert probe["isNewer"] is False


# --- Standdown ladder (source:"none", never attempted) -----------------------------------------


def _seed_fresh_newer_cache(cli, canonical) -> None:
    """A fresh, newer-than-running cache entry; a standdown that still returned it would be a bug.

    Every full-standdown case must ignore this and touch git zero times.
    """
    remote, branch, _ref = cli.methodology_release_upstream("stable")
    key = cli._update_probe_cache_key(canonical, remote, branch)
    cli._write_update_probe_cache(
        key,
        {
            "availableVersion": "0.99.0",
            "availableSha": "f" * 40,
            "probedAt": datetime.now(timezone.utc).isoformat(),
        },
    )


@pytest.mark.parametrize(
    "name",
    ["TAUTLINE_METHODOLOGY_UPDATE_PROBE", "MINERVIT_METHODOLOGY_UPDATE_PROBE"],
)
def test_knob_off_both_spellings_full_standdown(monkeypatch, tmp_path, name):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    _seed_fresh_newer_cache(cli, canonical)
    monkeypatch.setenv(name, "off")
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "none"
    assert probe["isNewer"] is False
    assert probe["availableVersion"] is None
    assert rec.calls == [], "a stood-down probe must run zero git subprocesses"


def test_no_remote_full_standdown_zero_subprocess(monkeypatch, tmp_path):
    _remote, source, canonical = _make_fixture(tmp_path)
    _advance_remote(source, "0.99.0")
    cli = _cli(monkeypatch, tmp_path, canonical)
    _seed_fresh_newer_cache(cli, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, True)

    assert probe["source"] == "none"
    assert probe["isNewer"] is False
    assert rec.calls == [], "--no-remote is a FULL standdown even with a fresh newer cache"


def test_armed_maintainer_mode_full_standdown(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    config = cli.USER_CONFIG_ENV
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1\n", encoding="utf-8")
    assert cli.maintainer_mode_armed() is True  # canonical (== REPO_ROOT) is a real checkout
    _seed_fresh_newer_cache(cli, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "none"
    assert rec.calls == []


class _StubPyPIResponse:
    """A minimal urlopen() return so package-mode probes never touch the real network."""

    def __init__(self, version: str):
        self._version = version

    def read(self) -> bytes:
        return json.dumps({"info": {"version": self._version}}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_package_runtime_probes_pypi_git_silent(monkeypatch, tmp_path):
    # PR-2 replaces PR-1's full package standdown with the PyPI branch (see
    # tests/test_package_mode_ux.py for the full package-mode probe suite). The guard THIS test
    # keeps is that package mode stays git-silent: it must NEVER run an ls-remote/fetch.
    export_root = tmp_path / "wheel"
    (export_root / "bin").mkdir(parents=True)
    cli = _cli(monkeypatch, tmp_path, export_root)
    (export_root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps(
            {"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": "a" * 40, "installKind": "package"}
        ),
        encoding="utf-8",
    )
    assert cli.running_from_installed_package() is True
    monkeypatch.setattr(cli, "urlopen", lambda url, timeout=None: _StubPyPIResponse("0.99.0"))
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(export_root, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "package"
    assert probe["availableVersion"] == "0.99.0"
    assert probe["isNewer"] is True
    assert rec.calls == [], "package mode runs zero git subprocesses (PyPI branch, never ls-remote)"


def test_methodology_dev_repo_full_standdown(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    dev_project = {"repo": next(iter(cli.methodology_repo_slugs()))}
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, dev_project, STABLE_PIN, True, False)

    assert probe["source"] == "none"
    assert rec.calls == []


# --- Env override ------------------------------------------------------------------------------


def test_env_override_wins_with_source_env(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", "0.77.0")
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "env"
    assert probe["availableVersion"] == "0.77.0"
    assert probe["availableSha"] is None
    assert probe["isNewer"] is True
    assert probe["changeKind"] == "minor"
    assert not rec.has("ls-remote"), "an env override short-circuits the remote probe"


# --- T2: display helper + offer renderer (pure, plus fixture-backed pinned checks) --------------
#
# The renderer takes DICTS the surfaces already have (decision, probe, pin); the offer copy is the
# feature's user-facing contract, so it is pinned by exact string here. Pinned-policy variants use a
# real fixture checkout: the already-pinned test resolves the candidate against the pin allowlist.

POLICY_ENV_NAMES = (
    "TAUTLINE_METHODOLOGY_UPDATE_POLICY",
    "MINERVIT_METHODOLOGY_UPDATE_POLICY",
    "TAUTLINE_METHODOLOGY_UPDATE_PINS",
    "MINERVIT_METHODOLOGY_UPDATE_PINS",
)


def _clear_policy_env(monkeypatch) -> None:
    for name in POLICY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _probe(
    *, version="0.99.0", sha="a" * 40, is_newer=True, change="minor", source="git", detail=None
):
    return {
        "availableVersion": version,
        "availableSha": sha,
        "changeKind": change,
        "isNewer": is_newer,
        "source": source,
        "failureDetail": detail,
        "probedAt": "2026-07-20T00:00:00+00:00",
    }


MANUAL_HOLD_REASON = (
    "framework updatePolicy=manual; run sync-methodology intentionally at a safe boundary"
)
SKIP_MANUAL = {"action": "skip", "reason": MANUAL_HOLD_REASON, "wipReasons": []}
SKIP_WIP_MINOR = {
    "action": "skip",
    "reason": "active work blocks automatic minor framework upgrade",
    "wipReasons": ["active branch feat/x", "goal ledger active (present)"],
}
SKIP_MANUAL_WITH_WIP = {
    "action": "skip",
    "reason": MANUAL_HOLD_REASON,
    "wipReasons": ["active branch feat/x"],
}


def test_available_line_is_probe_truthful_when_newer(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    line = cli.framework_update_available_line(
        {"availableVersion": RUNNING, "changeKind": "none"}, _probe()
    )
    assert line == "framework_update_available: version=0.99.0 change=minor (running 0.14.3)"


def test_available_line_is_byte_identical_when_not_newer(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    decision = {"availableVersion": RUNNING, "changeKind": "none"}
    # Reproduce the pre-probe format exactly (the surfaces printed this literal before T2).
    expected = (
        "framework_update_available: "
        f"version={decision['availableVersion']} change={decision['changeKind']}"
    )
    line = cli.framework_update_available_line(
        decision, _probe(version=None, sha=None, is_newer=False, change="none", source="none")
    )
    assert line == expected
    assert line == "framework_update_available: version=0.14.3 change=none"


def test_offer_experimental_manual_unpinned_is_bare_sync(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    _clear_policy_env(monkeypatch)
    lines = cli.framework_update_offer_lines(SKIP_MANUAL, _probe(), EXPERIMENTAL_PIN)
    assert lines == [
        "framework_update_offer: updatePolicy=manual holds automatic updates; "
        "take 0.99.0 with: tautline sync-methodology --target ."
    ]


def test_offer_signed_policy_names_the_held_remedy(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", "signed")
    for pin in (STABLE_PIN, EXPERIMENTAL_PIN):
        lines = cli.framework_update_offer_lines(SKIP_MANUAL, _probe(), pin)
        assert lines == [
            "framework_update_offer: 0.99.0 is available; take it with: tautline "
            "sync-methodology --target . (the signed trust policy verifies the release; on a "
            "hold, follow the printed methodology_update_held remedy)"
        ]


def test_offer_stable_pinned_candidate_already_pinned_is_bare_sync(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("TAUTLINE_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("TAUTLINE_METHODOLOGY_UPDATE_PINS", "a" * 40)  # the candidate itself
    lines = cli.framework_update_offer_lines(SKIP_MANUAL, _probe(sha="a" * 40), STABLE_PIN)
    assert lines == [
        "framework_update_offer: 0.99.0 is available; the release is already pinned; "
        "take it with: tautline sync-methodology --target ."
    ]


def test_offer_wip_hold_names_the_wip_reasons(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    _clear_policy_env(monkeypatch)
    lines = cli.framework_update_offer_lines(SKIP_WIP_MINOR, _probe(), STABLE_PIN)
    assert lines == [
        "framework_update_offer: 0.99.0 is available; held by active WIP "
        "(active branch feat/x, goal ledger active (present)); finish or park the WIP, "
        "then: tautline sync-methodology --target ."
    ]


def test_offer_manual_reason_with_wip_reasons_gets_plain_sync_not_wip_copy(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    _clear_policy_env(monkeypatch)
    # A manual-policy hold with wipReasons present is NOT a WIP hold: manual sync proceeds.
    lines = cli.framework_update_offer_lines(SKIP_MANUAL_WITH_WIP, _probe(), EXPERIMENTAL_PIN)
    assert lines == [
        "framework_update_offer: updatePolicy=manual holds automatic updates; "
        "take 0.99.0 with: tautline sync-methodology --target ."
    ]
    assert "held by active WIP" not in lines[0]


def test_offer_facts_only_for_sha_only_git_result(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    _clear_policy_env(monkeypatch)
    head = cli._update_probe_head(canonical)
    lines = cli.framework_update_offer_lines(
        SKIP_MANUAL,
        _probe(version=None, sha="c" * 40, is_newer=False, change="none", source="git"),
        STABLE_PIN,
    )
    assert lines == [
        f"framework_update_offer: upstream main is at {'c' * 12} (local {head[:12]}); "
        "inspect with: tautline methodology-status --target ."
    ]


def test_offer_facts_only_for_sha_only_cache_result(monkeypatch, tmp_path):
    # A cached recompute of a sha-only discovery (source "cache") must still emit the inspect
    # offer, exactly like the fresh "git" result -- otherwise it flickers off on repeat launches
    # within the freshness window while the "remote differs <sha>" line persists.
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    _clear_policy_env(monkeypatch)
    head = cli._update_probe_head(canonical)
    lines = cli.framework_update_offer_lines(
        SKIP_MANUAL,
        _probe(version=None, sha="c" * 40, is_newer=False, change="none", source="cache"),
        STABLE_PIN,
    )
    assert lines == [
        f"framework_update_offer: upstream main is at {'c' * 12} (local {head[:12]}); "
        "inspect with: tautline methodology-status --target ."
    ]


def test_offer_empty_for_failed_none_and_proceeding_update(monkeypatch, tmp_path):
    cli = _cli(monkeypatch, tmp_path, tmp_path)
    _clear_policy_env(monkeypatch)
    failed = _probe(version=None, sha=None, is_newer=False, source="failed", detail="offline")
    assert cli.framework_update_offer_lines(SKIP_MANUAL, failed, STABLE_PIN) == []
    stood_down = _probe(version=None, sha=None, is_newer=False, source="none")
    assert cli.framework_update_offer_lines(SKIP_MANUAL, stood_down, STABLE_PIN) == []
    updating = {"action": "update", "reason": "advancing", "wipReasons": []}
    assert cli.framework_update_offer_lines(updating, _probe(), STABLE_PIN) == []


def test_offline_line_is_byte_identical_to_remote_methodology_status(monkeypatch, tmp_path):
    # Fail-open byte-identity: the probe's failureDetail carries git's OWN ls-remote stderr, so the
    # surface renders the SAME `unavailable: <stderr>` string remote_methodology_status prints today
    # -- proven by comparing the two directly, from a single ls-remote (no fallback re-probe).
    _remote, _source, canonical = _make_fixture(tmp_path)
    _git(canonical, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    cli = _cli(monkeypatch, tmp_path, canonical)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(canonical, PROJECT, STABLE_PIN, False, False)

    assert probe["source"] == "failed"
    assert probe["failureDetail"] and probe["failureDetail"] != "remote query failed"
    probe_ls_remotes = sum(1 for call in rec.calls if "ls-remote" in call)
    assert probe_ls_remotes == 1, "one ls-remote for the probe; no fallback re-probe"

    probe_line = cli.framework_remote_status_from_probe(probe)
    today_line = cli.remote_methodology_status(False)  # untouched surface, same unreachable remote
    assert probe_line == today_line
    assert probe_line.startswith("unavailable: ")


def test_remote_status_from_probe_reuses_git_vocabulary(monkeypatch, tmp_path):
    _remote, _source, canonical = _make_fixture(tmp_path)
    cli = _cli(monkeypatch, tmp_path, canonical)
    head = cli._update_probe_head(canonical)
    assert cli.framework_remote_status_from_probe(_probe(sha="d" * 40)) == (
        f"remote differs {'d' * 12}"
    )
    assert cli.framework_remote_status_from_probe(_probe(sha=head, is_newer=False)) == "up to date"
    failed = _probe(version=None, sha=None, is_newer=False, source="failed", detail="unreachable")
    assert cli.framework_remote_status_from_probe(failed) == "unavailable: unreachable"
    stood_down = _probe(version=None, sha=None, is_newer=False, source="none")
    assert cli.framework_remote_status_from_probe(stood_down) is None
    env = _probe(sha=None, source="env")
    assert cli.framework_remote_status_from_probe(env) is None
