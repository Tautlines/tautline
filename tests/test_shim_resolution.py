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
    env_file = home / ".config" / "minervit" / "methodology.env"
    kept = [ln for ln in env_file.read_text(encoding="utf-8").splitlines()
            if "MINERVIT_METHODOLOGY_REPO=" not in ln]
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""}
    res = subprocess.run(
        [str(shim), "version", "--no-remote"],
        cwd=str(product), env=env, capture_output=True, text=True, timeout=60,
    )
    out = res.stdout + res.stderr
    assert "nearest-product-methodology" in out, out          # fallback resolved the nearest sibling
    assert "WARNING resolved via cwd discovery" in out, out   # and warned the operator
