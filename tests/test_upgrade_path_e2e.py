"""Release gate (operator directive 2026-07-12: a release must not break users): end-to-end proof
that a user machine deployed on the PREVIOUS release survives advancing its checkout to this code,
in every state users actually occupy:

  1. old shim + old (legacy-only) config + NEW checkout code  -- the state every machine enters the
     moment `git pull` lands the release, before any reinstall;
  2. after running the new `install-cli` -- both config surfaces exist, and the OLD launcher-era
     artifacts (which only know the legacy path) still resolve;
  3. rollback -- the checkout returns to the previous release and the machine still works.

The baseline is the merge-base with origin/experimental (the last shipped tree), so this test
always exercises the real previous-release code, not a simulation of it.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd or REPO_ROOT), text=True).strip()


def _run(cmd: list[str], env: dict, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


@pytest.fixture()
def upgrade_machine(tmp_path):
    """A hermetic 'user machine': HOME + a runtime clone checked out at the previous release."""
    try:
        base = _git("merge-base", "HEAD", "origin/experimental")
    except subprocess.CalledProcessError:
        pytest.skip("no origin/experimental merge-base available")
    current = _git("rev-parse", "HEAD")
    if base == current:
        pytest.skip("HEAD is the shipped baseline; no upgrade transition to prove")
    home = tmp_path / "home"
    home.mkdir()
    clone = tmp_path / "runtime"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", f"file://{REPO_ROOT}", str(clone)],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", base], check=True, capture_output=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return home, clone, env, base, current


def test_user_machine_survives_upgrade_and_rollback(upgrade_machine):
    home, clone, env, base, current = upgrade_machine
    old_cli = clone / "bin" / "tautline"
    legacy_cfg = home / ".config" / "minervit" / "methodology.env"
    new_cfg = home / ".config" / "tautline" / "tautline.env"
    shim = home / ".local" / "bin" / "tautline"

    # --- deploy the PREVIOUS release exactly as a user machine has it -------------------------
    installed = _run([str(old_cli), "install-cli"], env, clone)
    assert installed.returncode == 0, installed.stderr
    assert legacy_cfg.is_file(), "previous release writes the legacy config"
    # a user secret preserved across the whole journey:
    with legacy_cfg.open("a", encoding="utf-8") as fh:
        fh.write('export UPGRADE_E2E_SECRET="survives"\n')
    baseline = _run([str(shim), "version", "--no-remote"], env, clone)
    assert baseline.returncode == 0, baseline.stderr

    # --- state 1: checkout advances to THIS code; nothing reinstalled yet ----------------------
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", current], check=True, capture_output=True)
    via_old_shim = _run([str(shim), "version", "--no-remote"], env, clone)
    assert via_old_shim.returncode == 0, (
        "old shim + legacy-only config MUST run the new code unchanged:\n" + via_old_shim.stderr
    )
    assert "plugin_version:" in via_old_shim.stdout
    sync = _run([str(shim), "sync-methodology", "--skip-update", "--no-remote"], env, clone)
    assert sync.returncode == 0, "sync via old surface must not fail closed:\n" + sync.stderr

    # --- state 2: user runs the new install-cli ------------------------------------------------
    reinstalled = _run([str(old_cli), "install-cli"], env, clone)
    assert reinstalled.returncode == 0, reinstalled.stderr
    assert new_cfg.is_file() and legacy_cfg.is_file(), "both surfaces exist after upgrade install"
    assert new_cfg.read_text(encoding="utf-8") == legacy_cfg.read_text(encoding="utf-8"), (
        "legacy mirror must stay byte-identical so pre-upgrade launchers keep resolving"
    )
    assert 'export UPGRADE_E2E_SECRET="survives"' in new_cfg.read_text(encoding="utf-8"), (
        "user values hand-added on the previous release must migrate"
    )
    post = _run([str(shim), "version", "--no-remote"], env, clone)
    assert post.returncode == 0, post.stderr

    # --- state 3: rollback to the previous release ---------------------------------------------
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", base], check=True, capture_output=True)
    rolled_back = _run([str(shim), "version", "--no-remote"], env, clone)
    assert rolled_back.returncode == 0, (
        "rollback must leave a working machine (legacy mirror keeps old code resolving):\n"
        + rolled_back.stderr
    )
    assert "plugin_version:" in rolled_back.stdout
