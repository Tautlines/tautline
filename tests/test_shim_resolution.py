"""sec-trust-exec-3 (productization): the installed shim (~/.local/bin/minervit-methodology)
resolves the methodology repo from the operator-controlled MINERVIT_METHODOLOGY_REPO (live env,
then the methodology.env written by install-cli) BEFORE falling back to cwd discovery, so a
planted `minervit-ai-delivery-methodology` directory in an ancestor of the working dir cannot
hijack which code the shim execs. cwd discovery remains available as a warned fallback when
nothing is configured.

Migrated from scripts/validate.sh (frozen; arch-validate-tests-1/2) per the freeze policy: new
validation behavior belongs in pytest, not new validate.sh grep pins.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"


def _install(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home)}
    subprocess.run(
        [sys.executable, str(CLI_PATH), "install-cli"],
        env=env, check=True, capture_output=True, text=True, timeout=60,
    )
    return home / ".local" / "bin" / "minervit-methodology"


def _plant_sibling(parent: Path) -> Path:
    """Create parent/product-lane plus a sibling parent/minervit-ai-delivery-methodology whose
    shim prints a sentinel, so cwd discovery (if it wins) is observable."""
    product = parent / "product-lane"
    plant = parent / "minervit-ai-delivery-methodology" / "bin"
    product.mkdir(parents=True, exist_ok=True)
    plant.mkdir(parents=True, exist_ok=True)
    shim = plant / "minervit-methodology"
    shim.write_text("#!/bin/sh\nprintf 'nearest-product-methodology\\n'\n", encoding="utf-8")
    shim.chmod(0o755)
    return product


def test_configured_repo_beats_planted_sibling(tmp_path):
    shim = _install(tmp_path / "home")
    product = _plant_sibling(tmp_path / "near")
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    env.pop("MINERVIT_METHODOLOGY_REPO", None)  # rely on methodology.env, not an inherited preset
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        cwd=str(product), env=env, capture_output=True, text=True, timeout=60,
    )
    out = res.stdout + res.stderr
    assert "plugin_version:" in out, out                 # the real CLI ran -> configured repo won
    assert "nearest-product-methodology" not in out, out  # the planted sibling did NOT hijack


def test_cwd_discovery_is_warned_fallback(tmp_path):
    home = tmp_path / "home"
    shim = _install(home)
    product = _plant_sibling(tmp_path / "near")
    # Remove the configured repo so nothing operator-controlled resolves; cwd discovery must win.
    # 0.9.2 rebrand: both config surfaces and both env-var families must be cleared.
    for env_file in (
        home / ".config" / "tautline" / "tautline.env",
        home / ".config" / "minervit" / "methodology.env",
    ):
        if not env_file.is_file():
            continue
        kept = [ln for ln in env_file.read_text(encoding="utf-8").splitlines()
                if "MINERVIT_METHODOLOGY_REPO=" not in ln and "TAUTLINE_METHODOLOGY_REPO=" not in ln]
        env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_REPO": "",
        "TAUTLINE_METHODOLOGY_REPO": "",
        # Task B8: install-cli now also enables snapshot execution, and the store beats cwd
        # discovery for the EXEC target (test_store_beats_cwd_discovery below pins that). This
        # test is about CANONICAL resolution, so take the documented rollback lever and observe
        # the exec fallback ladder underneath the store.
        "MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC": "1",
    }
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        cwd=str(product), env=env, capture_output=True, text=True, timeout=60,
    )
    out = res.stdout + res.stderr
    assert "nearest-product-methodology" in out, out          # fallback resolved the nearest sibling
    assert "WARNING resolved via cwd discovery" in out, out   # and warned the operator


# --- Task B8: the shim's snapshot-store precedence ladder -------------------------------------
#
# Order, top to bottom:
#   1. MINERVIT_METHODOLOGY_EXEC_ROOT   (live env; the session-sticky root a launcher/re-exec set)
#   2. MINERVIT_METHODOLOGY_EXEC_OVERRIDE (live env only; the explicit dev redirection)
#   3. <store>/current                  (live env key, methodology.env key, or the baked default)
#   4. the canonical checkout           (MINERVIT_METHODOLOGY_REPO / cwd discovery)
#
# MINERVIT_METHODOLOGY_REPO is deliberately NOT an exec override any more: every v1 launcher
# exports it, so honoring it would send stale-v1 hook sessions to the MUTABLE canonical checkout
# -- the exact hazard the snapshot store exists to remove.

STORE_REL = Path(".local") / "share" / "minervit" / "tautline-releases"


def _clean_env(home: Path, **extra: str) -> dict:
    """A hermetic environment: no inherited MINERVIT_*/TAUTLINE_* from the operator's shell."""
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    env.update(extra)
    return env


def _store(home: Path) -> Path:
    return home / STORE_REL


def _fake_tree(root: Path, sentinel: str) -> Path:
    """A bin/tautline-bearing tree whose CLI prints what it is and what it inherited."""
    (root / "bin").mkdir(parents=True, exist_ok=True)
    exe = root / "bin" / "tautline"
    exe.write_text(
        "#!/bin/sh\n"
        f'printf "sentinel:{sentinel}\\n"\n'
        'printf "exec_root:%s\\n" "${MINERVIT_METHODOLOGY_EXEC_ROOT:-unset}"\n'
        'printf "repo:%s\\n" "${MINERVIT_METHODOLOGY_REPO:-unset}"\n',
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return root


def _publish(store: Path, name: str, sentinel: str) -> Path:
    """Put a fake snapshot in the store and point `current` at it."""
    snapshot = _fake_tree(store / name, sentinel)
    current = store / "current"
    store.mkdir(parents=True, exist_ok=True)
    if current.is_symlink() or current.exists():
        current.unlink()
    os.symlink(name, current)
    return snapshot


def _run_shim(shim: Path, env: dict, cwd: Path | None = None) -> str:
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        cwd=str(cwd) if cwd else None,
        env=env, capture_output=True, text=True, timeout=60,
    )
    return res.stdout + res.stderr


def test_store_current_exec_exports_exec_root(tmp_path):
    """(3) The baked-default store execs `current` AND exports the RESOLVED root to children."""
    home = tmp_path / "home"
    shim = _install(home)
    snapshot = _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    out = _run_shim(shim, _clean_env(home))
    assert "sentinel:store-current" in out, out
    assert f"exec_root:{snapshot.resolve()}" in out, out  # realpath, not the `current` symlink


def test_exec_root_env_wins(tmp_path):
    """(1) A live MINERVIT_METHODOLOGY_EXEC_ROOT is the session's sticky root: nothing beats it."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    sticky = _fake_tree(tmp_path / "sticky", "sticky-exec-root")
    out = _run_shim(shim, _clean_env(home, MINERVIT_METHODOLOGY_EXEC_ROOT=str(sticky)))
    assert "sentinel:sticky-exec-root" in out, out
    assert "sentinel:store-current" not in out, out


def test_exec_override_env_wins_for_dev(tmp_path):
    """(2) The NEW explicit dev override beats the store. Live env only -- never a managed key."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    dev = _fake_tree(tmp_path / "dev", "dev-override")
    out = _run_shim(shim, _clean_env(home, MINERVIT_METHODOLOGY_EXEC_OVERRIDE=str(dev)))
    assert "sentinel:dev-override" in out, out
    assert "sentinel:store-current" not in out, out


def test_exec_override_is_never_read_from_the_env_file(tmp_path):
    """sec-trust-exec-3: the override is checked BEFORE methodology.env is sourced, so a file
    (which install-cli owns, and which a stale/compromised install could carry) cannot redirect
    execution. Only a live operator environment can."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    planted = _fake_tree(tmp_path / "planted", "env-file-override")
    config = home / ".config" / "tautline" / "tautline.env"
    with config.open("a", encoding="utf-8") as handle:
        handle.write(f"export MINERVIT_METHODOLOGY_EXEC_OVERRIDE={planted}\n")
    out = _run_shim(shim, _clean_env(home))
    assert "sentinel:env-file-override" not in out, out
    assert "sentinel:store-current" in out, out


def test_inherited_repo_env_does_not_bypass_store(tmp_path):
    """THE STALE-V1-LAUNCHER REGRESSION. Every v1 launcher exports MINERVIT_METHODOLOGY_REPO. It
    must keep its canonical-sync-target meaning (resolved + exported for Python) and lose its
    exec effect, or a v1 session runs the MUTABLE checkout another lane is concurrently
    resetting."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    canonical = _fake_tree(tmp_path / "canonical", "mutable-canonical-checkout")
    out = _run_shim(shim, _clean_env(home, MINERVIT_METHODOLOGY_REPO=str(canonical)))
    assert "sentinel:store-current" in out, out
    assert "sentinel:mutable-canonical-checkout" not in out, out
    # ... and it is still exported, because Python resolves the sync target from it:
    assert f"repo:{canonical}" in out, out


def test_pruned_exec_root_falls_back_to_current(tmp_path):
    """The TTL degradation path: a session whose pinned snapshot was pruned past the retention
    window must hop to `current` (a version hop), never break."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    pruned = _store(home) / "bbbbbbbbbbbb"  # never materialized / already collected
    out = _run_shim(shim, _clean_env(home, MINERVIT_METHODOLOGY_EXEC_ROOT=str(pruned)))
    assert "sentinel:store-current" in out, out


def test_dangling_current_warns_and_falls_back_to_canonical(tmp_path):
    """(5) A broken store must warn ONCE, name the remedy, and still run: the store is an
    optimization, never a dependency."""
    home = tmp_path / "home"
    shim = _install(home)
    store = _store(home)
    _publish(store, "aaaaaaaaaaaa", "store-current")
    (store / "aaaaaaaaaaaa" / "bin" / "tautline").unlink()  # `current` now dangles
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        env=_clean_env(home), capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert "snapshot store current link missing or broken" in res.stderr, res.stderr
    assert "sync-methodology" in res.stderr, res.stderr
    assert "plugin_version:" in res.stdout, res.stdout  # fell through to the canonical checkout


def test_disable_snapshot_exec_skips_the_store(tmp_path):
    """(6) The documented rollback lever: no store exec, and no warning either."""
    home = tmp_path / "home"
    shim = _install(home)
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        env=_clean_env(home, MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC="1"),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert "sentinel:store-current" not in res.stdout, res.stdout
    assert "snapshot store current link missing" not in res.stderr, res.stderr
    assert "plugin_version:" in res.stdout, res.stdout


def test_disable_snapshot_exec_outranks_an_inherited_session_exec_root(tmp_path):
    """(0) The rollback lever outranks EVERY snapshot exec path -- including the sticky exec root.

    MINERVIT_METHODOLOGY_EXEC_ROOT is what a launcher (or a post-advance re-exec) exports to pin a
    session to one snapshot for its whole life, and the shim honours it at the very TOP of the
    ladder. If it outranks the disable key, an operator who set the lever to escape a bad snapshot
    is re-executed straight back into that snapshot by every process that inherited the root -- and
    since the root is re-exported, the entire process tree stays in the store the lever was meant
    to leave. An explicit disable must therefore be checked BEFORE the exec root is honoured, and
    must strip the root so children do not inherit it either.
    """
    home = tmp_path / "home"
    shim = _install(home)
    snapshot = _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    canonical = _fake_tree(tmp_path / "canonical", "canonical-checkout")

    out = _run_shim(
        shim,
        _clean_env(
            home,
            MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC="1",
            MINERVIT_METHODOLOGY_EXEC_ROOT=str(snapshot),
            MINERVIT_METHODOLOGY_REPO=str(canonical),
        ),
    )

    assert "sentinel:store-current" not in out, out          # not the pinned snapshot
    assert "sentinel:canonical-checkout" in out, out         # the checkout, as documented
    assert "exec_root:unset" in out, out                     # and children inherit no snapshot root


def test_shim_store_alias_precedence(tmp_path):
    """A stale MINERVIT_ export in methodology.env must lose to the fresh TAUTLINE_ alias, exactly
    as resolve_env orders them -- otherwise a preserved stale line points the machine at a dead
    store."""
    home = tmp_path / "home"
    shim = _install(home)
    fresh = tmp_path / "fresh-store"
    stale = tmp_path / "stale-store"
    _publish(fresh, "aaaaaaaaaaaa", "fresh-alias-store")
    _publish(stale, "aaaaaaaaaaaa", "stale-minervit-store")
    config = home / ".config" / "tautline" / "tautline.env"
    lines = [
        ln for ln in config.read_text(encoding="utf-8").splitlines()
        if "_METHODOLOGY_SNAPSHOT_STORE=" not in ln
    ]
    lines.append(f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={stale}")
    lines.append(f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={fresh}")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _run_shim(shim, _clean_env(home))
    assert "sentinel:fresh-alias-store" in out, out
    assert "sentinel:stale-minervit-store" not in out, out


def test_shim_live_store_env_beats_env_file_alias(tmp_path):
    """sec-trust-exec-3: a LIVE operator value beats every file-sourced value, including the
    TAUTLINE_ alias the file exports -- which is why the live values are captured BEFORE
    sourcing."""
    home = tmp_path / "home"
    shim = _install(home)
    live = tmp_path / "live-store"
    from_file = tmp_path / "file-store"
    _publish(live, "aaaaaaaaaaaa", "live-store")
    _publish(from_file, "aaaaaaaaaaaa", "file-store")
    config = home / ".config" / "tautline" / "tautline.env"
    lines = [
        ln for ln in config.read_text(encoding="utf-8").splitlines()
        if "_METHODOLOGY_SNAPSHOT_STORE=" not in ln
    ]
    lines.append(f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={from_file}")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _run_shim(shim, _clean_env(home, MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(live)))
    assert "sentinel:live-store" in out, out
    assert "sentinel:file-store" not in out, out


def test_store_beats_cwd_discovery(tmp_path):
    """The security half of removing the preset-exec block: with nothing configured, cwd discovery
    still resolves the canonical repo (and warns) -- but the store, not the planted sibling, is
    what gets EXECUTED."""
    home = tmp_path / "home"
    shim = _install(home)
    product = _plant_sibling(tmp_path / "near")
    _publish(_store(home), "aaaaaaaaaaaa", "store-current")
    for env_file in (
        home / ".config" / "tautline" / "tautline.env",
        home / ".config" / "minervit" / "methodology.env",
    ):
        kept = [
            ln for ln in env_file.read_text(encoding="utf-8").splitlines()
            if "_METHODOLOGY_REPO=" not in ln
        ]
        env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    out = _run_shim(shim, _clean_env(home), cwd=product)
    assert "sentinel:store-current" in out, out
    assert "nearest-product-methodology" not in out, out
