"""Task 6 (real-pypi-package plan): package-mode UX and isolation.

A pip/pipx-installed Tautline is identified by its wheel-stamped `.snapshot-meta.json`
carrying `installKind: "package"` (written by registry_package_snapshot_manifest at
build time). Package mode must:

- say what mode it is in and how to update (`version`, the sync skip surface) —
  naming BOTH package channels: `pipx upgrade tautline` and `pip install -U tautline`;
- NEVER tell a snapshot-store machine to pip install (they update via repin);
- refuse `update-repin` with a truthful remedy BEFORE any fetch;
- never mutate a leftover configured checkout (the upgraded-machine scenario,
  R1 finding PP-R1-P1-1) — pip is the only channel that updates the RUNNING code,
  so mutating the leftover checkout would change nothing the wheel executes;
- READ adapter data from the RUNNING package's embedded tree, not the leftover
  checkout (R3 finding PP-R3-P1-1) — reads and writes stand down together;
- leave checkout and snapshot-store resolution canonical-first, byte-identically.

Everything runs against hermetic fixture trees (precedent: tests/test_sync_methodology_cli.py
and tests/test_registry_package_real.py): the CLI resolves REPO_ROOT from its own file
location, so a copied `bin/tautline` inside a fixture tree runs AS that install.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
# Post the package-split flip (roadmap #11): bin/tautline is a thin shim; the engine lives here.
# Load the engine module (cli.py) for the in-process package-mode fixture; CLI_PATH stays the
# copy source for building the wheel-shaped export tree.
CLI_ENGINE_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
ALLOWLIST = REPO_ROOT / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json"
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
ADAPTER_SCHEMA = REPO_ROOT / "methodology" / "adapter-schema.json"

PACKAGE_COMMIT = "d" * 40
PIPX_HINT = "pipx upgrade tautline"
PIP_HINT = "pip install -U tautline"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _hermetic_env(home: Path, **overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_REPO": "",
        "TAUTLINE_METHODOLOGY_REPO": "",
        "MINERVIT_METHODOLOGY_CANONICAL_REPO": "",
        "TAUTLINE_METHODOLOGY_CANONICAL_REPO": "",
        "MINERVIT_METHODOLOGY_SNAPSHOT_STORE": "",
        "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE": "",
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": "",
        # Stand the display-only update probe down for every SUBPROCESS run in this module: in
        # package mode `methodology-status` (without --no-remote) would otherwise GET pypi.org for
        # real, making the suite flaky/slow and pypi-state-dependent. The opt-out preserves output
        # byte-identically (the surfaces still render the installed-package remote-status via
        # remote_methodology_status, which is NOT gated by this knob). No test in this file asserts
        # update-probe output from a subprocess, and the git-mode probe surfacing tests live in
        # tests/test_sync_methodology_cli.py under a separate env, so none of them is disabled here.
        "TAUTLINE_METHODOLOGY_UPDATE_PROBE": "off",
    }
    env.update(overrides)
    home.mkdir(parents=True, exist_ok=True)
    return env


def _run(exec_root: Path, *args: str, env: dict[str, str], cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(exec_root / "bin" / "tautline"), *args],
        cwd=str(cwd or exec_root),
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )


def _adapter_content(marker: str | None) -> str:
    """The example adapter, offline-safe, optionally carrying a content marker."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["latestCode"] = {"enabled": False}
    data.setdefault("ciTestGate", {})["enforcement"] = "warn"
    if marker is not None:
        data["knownProjectRules"] = [marker]
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _runtime_tree(root: Path, adapter_marker: str | None = None) -> None:
    """The minimal runtime file set the copied CLI needs to run from `root`."""
    (root / "bin").mkdir(parents=True)
    shutil.copy2(CLI_PATH, root / "bin" / "tautline")
    (root / "bin" / "tautline").chmod(0o755)
    shutil.copy2(REPO_ROOT / "VERSION", root / "VERSION")
    adapter = root / "adapters" / "projects" / "example-saas.json"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(_adapter_content(adapter_marker), encoding="utf-8")
    shutil.copy2(ALLOWLIST, adapter.parent / ALLOWLIST.name)
    schema_dest = root / "methodology" / "adapter-schema.json"
    schema_dest.parent.mkdir(parents=True)
    shutil.copy2(ADAPTER_SCHEMA, schema_dest)
    manifest_dest = root / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
    manifest_dest.parent.mkdir(parents=True)
    shutil.copy2(PLUGIN_MANIFEST, manifest_dest)
    src_dest = root / "src" / "tautline_methodology"
    src_dest.mkdir(parents=True)
    for path in (REPO_ROOT / "src" / "tautline_methodology").glob("*.py"):
        shutil.copy2(path, src_dest / path.name)
    shutil.copytree(
        REPO_ROOT / "src" / "tautline_methodology" / "core",
        src_dest / "core",
        ignore=shutil.ignore_patterns("__pycache__"),
    )


def _make_package_install(
    tmp_path: Path, name: str = "pkg-install", *,
    install_kind: str | None = "package", adapter_marker: str | None = None,
) -> Path:
    """An installed-wheel-shaped tree: full runtime files, stamped manifest, no .git."""
    root = tmp_path / name
    _runtime_tree(root, adapter_marker)
    manifest: dict = {
        "schema": "tautline-snapshot/v1",
        "commit": PACKAGE_COMMIT,
        "shortCommit": PACKAGE_COMMIT[:12],
        "version": (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "channel": "stable",
        "materializedAt": "2026-07-15T00:00:00Z",
    }
    if install_kind is not None:
        manifest["installKind"] = install_kind
    (root / ".snapshot-meta.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def _make_checkout(
    tmp_path: Path, name: str, *,
    adapter_marker: str | None = None, origin: str | None = None,
) -> Path:
    """A real git checkout fixture (the leftover / canonical / exec-root shapes)."""
    root = tmp_path / name
    _runtime_tree(root, adapter_marker)
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "validate@example.invalid")
    _git(root, "config", "user.name", "validate")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", f"checkout fixture {name}")
    if origin is not None:
        _git(root, "remote", "add", "origin", origin)
    return root


def _make_lane(tmp_path: Path, name: str = "lane") -> Path:
    """A scratch project lane whose origin slug matches the example adapter's repo."""
    remote = tmp_path / "remotes" / "example-org" / "example-saas.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    lane = tmp_path / name
    lane.mkdir()
    _git(lane, "init", "-q", "-b", "main")
    _git(lane, "config", "user.email", "validate@example.invalid")
    _git(lane, "config", "user.name", "validate")
    (lane / "README.md").write_text("# lane fixture\n", encoding="utf-8")
    _git(lane, "add", "README.md")
    _git(lane, "commit", "-q", "-m", "seed lane")
    _git(lane, "remote", "add", "origin", str(remote))
    _git(lane, "push", "-q", "origin", "main")
    return lane


def _has_line(output: str, expected: str) -> bool:
    """Exact-line match (the smoke job's `grep -Fx` discipline): a bare substring check
    on `adapter_drift: clean` is satisfied by `methodology_rescue_ref_adapter_drift: clean`
    even while the real adapter_drift line lists three drifted files."""
    return expected in output.splitlines()


def _checkout_state(repo: Path) -> tuple[str, str, str]:
    return (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "branch", "--show-current"),
        (repo / ".git" / "config").read_text(encoding="utf-8"),
    )


def _unlock(root: Path) -> None:
    """Published snapshots are 0555 dirs / 0444 files; hand tmp_path back something removable."""
    if not root.exists():
        return
    try:
        root.chmod(0o755)
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            try:
                os.chmod(os.path.join(dirpath, name), 0o755)
            except OSError:
                pass


@pytest.fixture()
def snapshot_store(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    yield root
    _unlock(root)


# --- 6.1: the mode says what it is and how to update ---------------------------------------


def test_version_prints_package_install_kind_and_update_hint(tmp_path):
    pkg = _make_package_install(tmp_path)
    result = _run(pkg, "version", "--no-remote", env=_hermetic_env(tmp_path / "home"))
    assert result.returncode == 0, result.stderr
    assert "install_kind: package" in result.stdout
    hint_lines = [
        line for line in result.stdout.splitlines() if line.startswith("update_hint:")
    ]
    assert len(hint_lines) == 1, f"expected one update_hint line, got: {result.stdout!r}"
    assert PIPX_HINT in hint_lines[0], "the hint must name the pipx channel (primary install)"
    assert PIP_HINT in hint_lines[0], "the hint must name the plain-venv channel"


def test_sync_skip_names_the_package_update_channel(tmp_path):
    pkg = _make_package_install(tmp_path)
    result = _run(pkg, "sync-methodology", "--no-remote", env=_hermetic_env(tmp_path / "home"))
    assert result.returncode == 0, result.stderr
    assert "methodology_update: skipped" in result.stdout
    assert PIPX_HINT in result.stdout, "the sync skip must name the pipx channel"
    assert PIP_HINT in result.stdout, "the sync skip must name the plain-venv channel"


def test_snapshot_store_snapshot_gets_no_pip_hint(tmp_path):
    """A snapshot-store manifest (no installKind: package) updates via repin: telling that
    machine to pip install would be actively wrong. This is the boundary pin that turns RED
    if package behavior is ever keyed on generic snapshot detection instead of installKind."""
    snap = _make_package_install(tmp_path, "snapshot-store", install_kind=None)
    env = _hermetic_env(tmp_path / "home")
    version = _run(snap, "version", "--no-remote", env=env)
    assert version.returncode == 0, version.stderr
    assert "install_kind:" not in version.stdout
    assert "update_hint:" not in version.stdout
    sync = _run(snap, "sync-methodology", "--no-remote", env=env)
    assert sync.returncode == 0, sync.stderr
    assert PIPX_HINT not in sync.stdout
    assert PIP_HINT not in sync.stdout


def test_update_repin_refuses_from_a_package_install_with_a_truthful_remedy(tmp_path):
    pkg = _make_package_install(tmp_path)
    result = _run(pkg, "update-repin", env=_hermetic_env(tmp_path / "home"))
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "installed package" in combined, f"the refusal must name the real cause: {combined!r}"
    assert PIPX_HINT in combined
    assert PIP_HINT in combined
    assert "install-cli" in combined, "the checkout-runtime remedy must be named"
    assert "fix connectivity/auth" not in combined, (
        "the misleading connectivity diagnosis is reserved for real fetch failures on real checkouts"
    )


# --- 6.1: the upgraded-machine scenario (PP-R1-P1-1 / PP-R3-P1-1) ---------------------------


def test_package_mode_short_circuits_even_with_a_valid_configured_checkout(tmp_path):
    """installKind: package PLUS env still naming a REAL leftover checkout: package mode
    outranks the configured checkout because pip is the only channel that updates the
    RUNNING code. The checkout's origin points at a nonexistent path, so ANY attempted
    fetch would fail loudly — the skip/refusal outputs prove no fetch ever ran."""
    pkg = _make_package_install(tmp_path)
    leftover = _make_checkout(
        tmp_path, "leftover-checkout", origin=str(tmp_path / "missing-remote.git")
    )
    env = _hermetic_env(
        tmp_path / "home",
        MINERVIT_METHODOLOGY_REPO=str(leftover),
    )
    before = _checkout_state(leftover)

    sync = _run(pkg, "sync-methodology", "--no-remote", env=env)
    assert sync.returncode == 0, f"package-mode sync must stand down, not fail:\n{sync.stdout}\n{sync.stderr}"
    assert "methodology_update: skipped" in sync.stdout
    assert PIPX_HINT in sync.stdout
    assert _checkout_state(leftover) == before, (
        "package mode mutated the leftover checkout (HEAD, branch, or .git/config changed)"
    )

    repin = _run(pkg, "update-repin", env=env)
    combined = repin.stdout + repin.stderr
    assert repin.returncode != 0
    assert PIPX_HINT in combined
    assert "fix connectivity/auth" not in combined, (
        "update-repin reached the fetch: the refusal must come BEFORE any network touch"
    )
    assert "refusing to repin from a stale cached" not in combined
    assert _checkout_state(leftover) == before, "update-repin touched the leftover checkout"


def test_package_mode_sync_does_not_heal_a_leftover_snapshot_store(tmp_path, snapshot_store):
    """The store half of the upgraded-machine scenario (PP-R1-P1-1 extension): installKind:
    package PLUS a leftover configured store key. pip is the only channel that updates the
    RUNNING code, so healing/republishing the leftover checkout into the store would publish
    a tree nothing on this machine executes — the sync must not touch the store at all."""
    pkg = _make_package_install(tmp_path)
    leftover = _make_checkout(
        tmp_path, "leftover-checkout", origin=str(tmp_path / "missing-remote.git")
    )
    env = _hermetic_env(
        tmp_path / "home",
        MINERVIT_METHODOLOGY_REPO=str(leftover),
        MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(snapshot_store),
    )
    before = _checkout_state(leftover)

    sync = _run(pkg, "sync-methodology", "--no-remote", env=env)
    assert sync.returncode == 0, (
        f"package-mode sync must stand down, not fail:\n{sync.stdout}\n{sync.stderr}"
    )
    assert "methodology_update: skipped" in sync.stdout
    assert PIPX_HINT in sync.stdout
    assert "methodology_snapshot:" not in sync.stdout, (
        "package mode healed/published into the leftover store"
    )
    assert not (snapshot_store / "current").exists()
    assert list(snapshot_store.iterdir()) == [], (
        "package mode materialized snapshot(s) into the leftover store"
    )
    assert _checkout_state(leftover) == before, (
        "package mode mutated the leftover checkout while standing the store down"
    )

    status = _run(pkg, "snapshot-status", env=env)
    assert status.returncode == 0, status.stderr
    assert "snapshot_store_enabled: false" in status.stdout
    assert "snapshot_store_standdown: installed package runtime" in status.stdout, (
        "`enabled: false` over a configured key must name the package standdown, "
        f"or it reads as a bug:\n{status.stdout}"
    )


def test_package_mode_gated_sync_writes_no_freshness_stamp(tmp_path, snapshot_store):
    """The gated tail must not resolve the leftover checkout or stamp its head as freshly
    synced: the skip a stamp buys would hide the pipx/pip update hint behind 'synced Ns ago
    by another lane', recorded on the strength of a checkout this wheel never executes."""
    pkg = _make_package_install(tmp_path)
    leftover = _make_checkout(
        tmp_path, "leftover-checkout", origin=str(tmp_path / "missing-remote.git")
    )
    home = tmp_path / "home"
    env = _hermetic_env(
        home,
        MINERVIT_METHODOLOGY_REPO=str(leftover),
        MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(snapshot_store),
        # The exec-handoff pair must never leak in from the runner's shell.
        MINERVIT_METHODOLOGY_SYNC_LOCK_FD="",
        MINERVIT_METHODOLOGY_SYNC_GATE="",
    )
    stamp = home / ".local" / "state" / "minervit" / "methodology-sync.stamp"

    first = _run(pkg, "sync-methodology", "--launcher-gate", "--no-remote", env=env, cwd=pkg)
    assert first.returncode == 0, first.stderr
    assert PIPX_HINT in first.stdout
    assert not stamp.exists(), (
        "package mode stamped the leftover checkout's head as freshly synced"
    )

    second = _run(pkg, "sync-methodology", "--launcher-gate", "--no-remote", env=env, cwd=pkg)
    assert second.returncode == 0, second.stderr
    assert PIPX_HINT in second.stdout, "the freshness skip swallowed the package update hint"
    assert "ago by another lane" not in second.stdout


def test_package_mode_gated_sync_ignores_an_inherited_freshness_stamp(tmp_path, snapshot_store):
    """Codex R1 (this sweep): an upgraded machine inherits the stamp its CHECKOUT era
    wrote. Vetoing stamp WRITES is only half the isolation -- if the gate still
    CONSUMES the old stamp, `--launcher-gate` skips as 'synced Ns ago' and the
    pipx/pip update hint is hidden for a whole freshness window."""
    pkg = _make_package_install(tmp_path)
    leftover = _make_checkout(
        tmp_path, "leftover-checkout", origin=str(tmp_path / "missing-remote.git")
    )
    home = tmp_path / "home"
    env = _hermetic_env(
        home,
        MINERVIT_METHODOLOGY_REPO=str(leftover),
        MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(snapshot_store),
        MINERVIT_METHODOLOGY_SYNC_LOCK_FD="",
        MINERVIT_METHODOLOGY_SYNC_GATE="",
    )
    stamp = home / ".local" / "state" / "minervit" / "methodology-sync.stamp"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(
        json.dumps(
            {
                "schema": "tautline-methodology-sync-stamp/v1",
                "syncedAt": "2026-07-16T00:00:00Z",
                "head": "a" * 40,
                "snapshot": ("a" * 40)[:12],
                "status": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fresh = time.time() - 30.0
    os.utime(stamp, (fresh, fresh))

    run = _run(pkg, "sync-methodology", "--launcher-gate", "--no-remote", env=env, cwd=pkg)
    assert run.returncode == 0, run.stderr
    assert "ago by another lane" not in run.stdout, (
        f"package mode honored a checkout-era freshness stamp\n{run.stdout}"
    )
    assert PIPX_HINT in run.stdout, "the inherited stamp swallowed the package update hint"


def test_snapshot_store_machine_still_heals_current_on_sync(tmp_path, snapshot_store):
    """The boundary pin (green today, red if the standdown is ever keyed on generic snapshot
    detection instead of installKind: package): a snapshot-store exec root with the same
    leftover checkout + store env must KEEP healing `current` on sync."""
    snap = _make_package_install(tmp_path, "snapshot-store", install_kind=None)
    leftover = _make_checkout(
        tmp_path, "leftover-checkout", origin=str(tmp_path / "missing-remote.git")
    )
    env = _hermetic_env(
        tmp_path / "home",
        MINERVIT_METHODOLOGY_REPO=str(leftover),
        MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(snapshot_store),
    )
    # --skip-update keeps the sync off the missing remote; a non-failed skip still heals.
    sync = _run(snap, "sync-methodology", "--no-remote", "--skip-update", env=env)
    assert sync.returncode == 0, f"{sync.stdout}\n{sync.stderr}"
    assert "methodology_snapshot: healed current" in sync.stdout, sync.stdout
    assert (snapshot_store / "current").exists(), (
        "the snapshot-store machine stopped healing current (standdown keyed too broadly)"
    )


REMOTE_PROBE_STANDDOWN = (
    "remote_status: skipped - installed package runtime; no methodology checkout to probe"
)


def _make_tracking_checkout(tmp_path: Path, name: str) -> Path:
    """A leftover checkout WITH a tracking upstream whose origin then points at a void.

    The `push -u` is load-bearing: without @{u} tracking, remote_methodology_status returns
    'unavailable: no upstream configured' BEFORE the ls-remote, and a standdown test would pass
    without proving anything about network I/O. With tracking + a void origin, any attempted
    probe degrades to 'unavailable: fatal ...' — so its absence proves no probe ever ran."""
    bare = tmp_path / f"{name}-upstream.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    checkout = _make_checkout(tmp_path, name, origin=str(bare))
    _git(checkout, "push", "-q", "-u", "origin", "main")
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "void-missing.git"))
    return checkout


def test_read_only_reporters_stand_down_from_remote_probe_in_package_mode(tmp_path):
    """The read-only half of PP-R1-P1-1: without --no-remote, version / sync-methodology /
    methodology-status must not ls-remote the LEFTOVER checkout's origin — pip is the only
    channel that updates the RUNNING code, so the leftover's remote answers a question about
    code this wheel never executes, and probing it puts network I/O in every read-only report."""
    pkg = _make_package_install(tmp_path)
    leftover = _make_tracking_checkout(tmp_path, "leftover-checkout")
    env = _hermetic_env(tmp_path / "home", MINERVIT_METHODOLOGY_REPO=str(leftover))

    version = _run(pkg, "version", env=env)
    assert version.returncode == 0, version.stdout + version.stderr
    assert _has_line(version.stdout, REMOTE_PROBE_STANDDOWN), version.stdout
    assert "unavailable:" not in version.stdout, version.stdout

    sync = _run(pkg, "sync-methodology", env=env)
    assert sync.returncode == 0, sync.stdout + sync.stderr
    assert "methodology_update: skipped" in sync.stdout
    assert _has_line(sync.stdout, REMOTE_PROBE_STANDDOWN), sync.stdout
    assert "unavailable:" not in sync.stdout, sync.stdout

    lane = _make_lane(tmp_path, "probe-lane")
    render = _run(
        pkg, "render-adapters",
        "--project", str(pkg / "adapters" / "projects" / "example-saas.json"),
        "--target", str(lane), "--write",
        env=env,
    )
    assert render.returncode == 0, render.stdout + render.stderr
    status = _run(pkg, "methodology-status", "--target", str(lane), env=env)
    assert status.returncode == 0, status.stdout + status.stderr
    assert _has_line(status.stdout, REMOTE_PROBE_STANDDOWN), status.stdout
    assert "unavailable:" not in status.stdout, status.stdout


def test_snapshot_store_exec_root_still_probes_the_remote(tmp_path):
    """Boundary pin (the test_snapshot_store_snapshot_gets_no_pip_hint discipline): the probe
    standdown keys on installKind: package, never on generic snapshot detection. A snapshot-store
    exec root with the same leftover env must still ATTEMPT the probe — the void origin degrades
    it to 'unavailable: ...', and that degradation is the proof the probe ran."""
    snap = _make_package_install(tmp_path, "snapshot-store", install_kind=None)
    leftover = _make_tracking_checkout(tmp_path, "leftover-checkout")
    env = _hermetic_env(tmp_path / "home", MINERVIT_METHODOLOGY_REPO=str(leftover))
    version = _run(snap, "version", env=env)
    assert version.returncode == 0, version.stdout + version.stderr
    remote_lines = [
        line for line in version.stdout.splitlines() if line.startswith("remote_status: ")
    ]
    assert len(remote_lines) == 1, version.stdout
    assert remote_lines[0].startswith("remote_status: unavailable:"), version.stdout


def test_package_mode_reads_adapter_data_from_the_embedded_tree(tmp_path):
    """The READ half of the upgraded-machine scenario (PP-R3-P1-1): with a leftover valid
    checkout whose source-adapter content measurably differs, package mode resolves adapter
    data from the RUNNING package's embedded tree. Checkout and snapshot-store fixtures keep
    canonical-first resolution — the change is package-mode-only."""
    embedded_marker = "EMBEDDED-TREE-MARKER: rendered from the running package's own data."
    stale_marker = "STALE-CHECKOUT-MARKER: must never be read in package mode."
    canonical_marker = "CANONICAL-MARKER: canonical-first resolution must keep winning."

    pkg = _make_package_install(tmp_path, adapter_marker=embedded_marker)
    leftover = _make_checkout(tmp_path, "leftover-checkout", adapter_marker=stale_marker)
    env = _hermetic_env(tmp_path / "home", MINERVIT_METHODOLOGY_REPO=str(leftover))
    lane = _make_lane(tmp_path, "pkg-lane")

    render = _run(
        pkg, "render-adapters",
        "--project", str(pkg / "adapters" / "projects" / "example-saas.json"),
        "--target", str(lane), "--write",
        env=env,
    )
    assert render.returncode == 0, f"render failed:\n{render.stdout}\n{render.stderr}"
    lane_adapter = (lane / ".tautline.json").read_text(encoding="utf-8")
    assert embedded_marker in lane_adapter
    assert stale_marker not in lane_adapter

    status = _run(pkg, "methodology-status", "--target", str(lane), "--no-remote", env=env)
    assert status.returncode == 0, (
        "package mode resolved the lane's sourceAdapter against the STALE checkout "
        f"(sha mismatch), not the embedded tree:\n{status.stdout}\n{status.stderr}"
    )
    assert _has_line(status.stdout, "adapter_drift: clean"), status.stdout

    # Companion: a checkout-mode exec root (no package manifest) keeps canonical resolution,
    # where canonical IS the exec checkout (the resolver's exec-root-wins gate) even with a
    # configured repo env naming some other checkout.
    exec_marker = "EXEC-ROOT-MARKER: a checkout exec root is its own canonical repo."
    exec_checkout = _make_checkout(tmp_path, "exec-checkout", adapter_marker=exec_marker)
    canonical = _make_checkout(tmp_path, "canonical-checkout", adapter_marker=canonical_marker)
    env_checkout = _hermetic_env(tmp_path / "home2", MINERVIT_METHODOLOGY_REPO=str(canonical))
    lane2 = _make_lane(tmp_path / "co", "checkout-lane")
    render2 = _run(
        exec_checkout, "render-adapters",
        "--project", str(exec_checkout / "adapters" / "projects" / "example-saas.json"),
        "--target", str(lane2), "--write",
        env=env_checkout,
    )
    assert render2.returncode == 0, f"render failed:\n{render2.stdout}\n{render2.stderr}"
    assert exec_marker in (lane2 / ".tautline.json").read_text(encoding="utf-8")
    status2 = _run(
        exec_checkout, "methodology-status", "--target", str(lane2), "--no-remote",
        env=env_checkout,
    )
    assert status2.returncode == 0, (
        f"checkout-mode canonical-first resolution regressed:\n{status2.stdout}\n{status2.stderr}"
    )
    assert _has_line(status2.stdout, "adapter_drift: clean"), status2.stdout

    # Companion: a snapshot-store exec root (manifest WITHOUT installKind) keeps canonical-first.
    snap = _make_package_install(
        tmp_path, "snap-exec", install_kind=None, adapter_marker="SNAP-EXEC-MARKER"
    )
    env_snap = _hermetic_env(tmp_path / "home3", MINERVIT_METHODOLOGY_REPO=str(canonical))
    lane3 = _make_lane(tmp_path / "sn", "snap-lane")
    render3 = _run(
        snap, "render-adapters",
        "--project", str(canonical / "adapters" / "projects" / "example-saas.json"),
        "--target", str(lane3), "--write",
        env=env_snap,
    )
    assert render3.returncode == 0, f"render failed:\n{render3.stdout}\n{render3.stderr}"
    assert canonical_marker in (lane3 / ".tautline.json").read_text(encoding="utf-8")
    status3 = _run(snap, "methodology-status", "--target", str(lane3), "--no-remote", env=env_snap)
    assert status3.returncode == 0, (
        "snapshot-store resolution must stay canonical-first (keyed on installKind, not on "
        f"generic snapshot detection):\n{status3.stdout}\n{status3.stderr}"
    )
    assert _has_line(status3.stdout, "adapter_drift: clean"), status3.stdout


# --- T4: the installed-package (PyPI) update probe (framework_update_probe, package mode) --------
#
# PR 1 stood the update probe fully down in package mode. PR 2 replaces that arm with a PyPI JSON
# probe: newer -> a source:"package" result and the pipx/pip offer; equal/older -> no offer; ANY
# urlopen failure -> a byte-identical FULL standdown; a 24h cache skips the repeat GET; the knob
# (both spellings) and no_remote stand down BEFORE the network call; and NO git subprocess ever
# runs. These load bin/tautline in-process (the SourceFileLoader pattern of test_update_probe.py)
# so urllib.request.urlopen can be stubbed; the git subprocess recorder proves package mode is
# git-silent.

RUNNING = "0.14.4"

# The knob (both spellings), the env-version override, the freshness window, and maintainer mode:
# cleared so the operator's shell can never leak into a probe assertion.
_PROBE_ENV_NAMES = (
    "TAUTLINE_METHODOLOGY_UPDATE_PROBE",
    "MINERVIT_METHODOLOGY_UPDATE_PROBE",
    "TAUTLINE_METHODOLOGY_AVAILABLE_VERSION",
    "MINERVIT_METHODOLOGY_AVAILABLE_VERSION",
    "TAUTLINE_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "TAUTLINE_METHODOLOGY_MAINTAINER_MODE",
    "MINERVIT_METHODOLOGY_MAINTAINER_MODE",
)

PROJECT = {"repo": "acme/widgets"}
STABLE_PIN = {"channel": "stable", "updatePolicy": "manual"}


class _FakeResponse:
    """A minimal urlopen() return: a context manager whose .read() yields the JSON body bytes."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _GitRecorder:
    """Wraps module.run_command / module.run_git, recording every git invocation's argv."""

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


def _load_package_cli(monkeypatch, tmp_path):
    """Load bin/tautline as a module rooted on a hermetic HOME and a wheel-shaped export root so
    running_from_installed_package() is True (installKind: package manifest, no .git)."""
    for name in _PROBE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    export_root = tmp_path / "wheel"
    (export_root / "bin").mkdir(parents=True)
    loader = importlib.machinery.SourceFileLoader("tautline_pkg_cli", str(CLI_ENGINE_PATH))
    spec = importlib.util.spec_from_loader("tautline_pkg_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "REPO_ROOT", export_root)
    module._CANONICAL_METHODOLOGY_REPO = None
    module._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    (export_root / module.SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema": module.SNAPSHOT_MANIFEST_SCHEMA,
                "commit": "d" * 40,
                "installKind": "package",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "plugin_version", lambda: RUNNING)
    assert module.running_from_installed_package() is True
    return module


def _stub_urlopen(cli, monkeypatch, *, version=None, body=None, error=None, record=None):
    def fake(url, timeout=None):
        if record is not None:
            record.append((url, timeout))
        if error is not None:
            raise error
        payload = body if body is not None else json.dumps({"info": {"version": version}}).encode()
        return _FakeResponse(payload)

    monkeypatch.setattr(cli, "urlopen", fake)


def test_package_probe_newer_emits_pipx_pip_offer(monkeypatch, tmp_path):
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "package"
    assert probe["availableVersion"] == "0.99.0"
    assert probe["isNewer"] is True
    assert probe["availableSha"] is None
    assert probe["failureDetail"] is None
    assert len(calls) == 1 and calls[0][0] == cli.METHODOLOGY_UPDATE_PROBE_PYPI_URL
    assert calls[0][1] == cli.METHODOLOGY_UPDATE_PROBE_PYPI_TIMEOUT
    assert rec.calls == [], "package mode must run zero git subprocesses"

    skip = {"action": "skip", "reason": "manual", "wipReasons": []}
    offers = cli.framework_update_offer_lines(skip, probe, STABLE_PIN)
    assert offers == [
        f"framework_update_offer: 0.99.0 is available (running {RUNNING}); "
        f"update with: {cli.PACKAGE_INSTALL_UPDATE_HINT}"
    ]
    assert PIPX_HINT in offers[0] and PIP_HINT in offers[0]
    assert not cli.response_has_forbidden_opt_in(offers[0]), offers[0]


@pytest.mark.parametrize("available", ["0.14.4", "0.1.0"])
def test_package_probe_equal_or_older_emits_no_offer(monkeypatch, tmp_path, available):
    cli = _load_package_cli(monkeypatch, tmp_path)
    _stub_urlopen(cli, monkeypatch, version=available)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "package"
    assert probe["isNewer"] is False
    skip = {"action": "skip", "reason": "manual", "wipReasons": []}
    assert cli.framework_update_offer_lines(skip, probe, STABLE_PIN) == []


def _standdown_surface(cli, probe):
    """The three surface renderings that must be byte-identical to a full package standdown."""
    skip = {"action": "skip", "reason": "manual", "wipReasons": []}
    decision = {"availableVersion": RUNNING, "changeKind": "none"}
    return (
        cli.framework_update_available_line(decision, probe),
        cli.framework_update_offer_lines(skip, probe, STABLE_PIN),
        cli.framework_remote_status_from_probe(probe),
    )


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
        urllib.error.HTTPError(
            "https://pypi.org/pypi/tautline/json", 503, "Service Unavailable", {}, None
        ),
        ValueError("bad json"),
    ],
)
def test_package_probe_urlopen_failure_is_byte_identical_full_standdown(
    monkeypatch, tmp_path, error
):
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, error=error, record=calls)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "none", "any urlopen failure fails open to a FULL standdown"
    assert probe["isNewer"] is False
    assert probe["availableVersion"] is None
    assert probe["availableSha"] is None
    assert len(calls) == 1, "the GET was attempted exactly once"
    assert rec.calls == [], "no git subprocess on the failure path"

    # Byte-identical to the pre-PR-2 full standdown (a knob-off package probe reproduces that).
    monkeypatch.setenv("TAUTLINE_METHODOLOGY_UPDATE_PROBE", "off")
    standdown = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)
    assert standdown["source"] == "none"
    assert _standdown_surface(cli, probe) == _standdown_surface(cli, standdown)


def test_package_probe_bad_json_shape_fails_open(monkeypatch, tmp_path):
    cli = _load_package_cli(monkeypatch, tmp_path)
    # 200 OK but the body is not the expected {"info": {"version": ...}} shape.
    _stub_urlopen(cli, monkeypatch, body=b'{"info": {}}')

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "none"
    assert probe["availableVersion"] is None


def test_package_probe_24h_cache_skips_second_urlopen(monkeypatch, tmp_path):
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)

    first = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)
    assert first["source"] == "package" and first["isNewer"] is True
    second = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert second["source"] == "package"
    assert second["availableVersion"] == "0.99.0"
    assert second["isNewer"] is True
    assert len(calls) == 1, "a fresh 24h cache entry must not re-GET pypi.org"


def test_package_probe_expired_cache_re_gets(monkeypatch, tmp_path):
    cli = _load_package_cli(monkeypatch, tmp_path)
    # Seed a stale (>24h old) cache entry directly; the probe must treat it as a miss and re-GET.
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    cli._write_update_probe_cache(
        cli.METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY,
        {"availableVersion": "0.50.0", "availableSha": None, "probedAt": stale},
    )
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["availableVersion"] == "0.99.0", "a stale entry must not be served"
    assert len(calls) == 1


def test_package_probe_failure_is_negatively_cached_no_retry(monkeypatch, tmp_path):
    """(a) An offline/unreachable PyPI must not re-attempt the 3s GET on every launch: the first
    failure writes a negative marker, and a second probe within the negative TTL stands down
    WITHOUT calling urlopen again, still rendering the full-standdown output."""
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, error=urllib.error.URLError("offline"), record=calls)

    first = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)
    assert first["source"] == "none"
    second = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert second["source"] == "none"
    assert len(calls) == 1, "a fresh negative-cache entry must not re-GET pypi.org"
    # The cached failure emits no availability/offer line (byte-identical full standdown).
    skip = {"action": "skip", "reason": "manual", "wipReasons": []}
    assert cli.framework_update_offer_lines(skip, second, STABLE_PIN) == []
    assert cli.framework_remote_status_from_probe(second) is None


def test_package_probe_negative_cache_expires_and_retries(monkeypatch, tmp_path):
    """(b) Once the negative marker ages past the negative TTL, the probe retries the network so a
    recovered PyPI is seen within the hour."""
    cli = _load_package_cli(monkeypatch, tmp_path)
    # Seed a stale (>1h old) failure marker directly; the probe must treat it as a miss and re-GET.
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cli._write_update_probe_cache(
        cli.METHODOLOGY_UPDATE_PROBE_PACKAGE_CACHE_KEY,
        {"availableVersion": None, "availableSha": None, "probeFailed": True, "probedAt": stale},
    )
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "package"
    assert probe["availableVersion"] == "0.99.0", "a stale failure must not keep standing down"
    assert len(calls) == 1


def test_package_probe_fresh_success_not_clobbered_by_transient_failure(monkeypatch, tmp_path):
    """(c) A cached SUCCESS within the 24h window is checked FIRST and short-circuits the network,
    so a later transient failure never runs urlopen and never clobbers the valid discovery."""
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)
    first = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)
    assert first["source"] == "package" and first["isNewer"] is True

    # Now make urlopen fail; the fresh success cache must keep winning with NO network call.
    _stub_urlopen(cli, monkeypatch, error=urllib.error.URLError("transient"), record=calls)
    second = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert second["source"] == "package"
    assert second["availableVersion"] == "0.99.0"
    assert second["isNewer"] is True
    assert len(calls) == 1, "a fresh success short-circuits the network; no failing GET runs"


@pytest.mark.parametrize(
    "name",
    ["TAUTLINE_METHODOLOGY_UPDATE_PROBE", "MINERVIT_METHODOLOGY_UPDATE_PROBE"],
)
def test_package_probe_knob_off_both_spellings_no_urlopen(monkeypatch, tmp_path, name):
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)
    rec = _GitRecorder(cli)
    monkeypatch.setenv(name, "off")

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)

    assert probe["source"] == "none"
    assert probe["isNewer"] is False
    assert calls == [], "the knob stands the probe down BEFORE the network call"
    assert rec.calls == []


def test_package_probe_no_remote_no_urlopen(monkeypatch, tmp_path):
    cli = _load_package_cli(monkeypatch, tmp_path)
    calls: list = []
    _stub_urlopen(cli, monkeypatch, version="0.99.0", record=calls)
    rec = _GitRecorder(cli)

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, True)

    assert probe["source"] == "none"
    assert calls == [], "no_remote is a FULL standdown; no GET"
    assert rec.calls == []


def test_package_remote_status_line_unchanged_even_when_pypi_is_newer(monkeypatch, tmp_path):
    """Design v5 Package-mode remote-status rule: the PyPI probe feeds availability/offer ONLY.
    Even when it finds a newer release, framework_remote_status_from_probe returns None so the
    surface keeps today's installed-package remote-status wording via remote_methodology_status."""
    cli = _load_package_cli(monkeypatch, tmp_path)
    _stub_urlopen(cli, monkeypatch, version="0.99.0")

    probe = cli.framework_update_probe(cli.REPO_ROOT, PROJECT, STABLE_PIN, True, False)
    assert probe["source"] == "package" and probe["isNewer"] is True

    assert cli.framework_remote_status_from_probe(probe) is None
    # And today's installed-package wording is exactly what the surface then renders.
    assert cli.remote_methodology_status(False) == (
        "skipped - installed package runtime; no methodology checkout to probe"
    )
