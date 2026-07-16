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

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
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
    src_dest = root / "src" / "minervit_methodology"
    src_dest.mkdir(parents=True)
    for path in (REPO_ROOT / "src" / "minervit_methodology").glob("*.py"):
        shutil.copy2(path, src_dest / path.name)


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
