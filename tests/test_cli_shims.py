import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tautline_shim_runs_version():
    out = subprocess.run(
        [str(ROOT / "bin/tautline"), "version", "--no-remote"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert "methodology_repo:" in out.stdout


def test_minervit_shim_still_runs_version():
    out = subprocess.run(
        [str(ROOT / "bin/minervit-methodology"), "version", "--no-remote"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert "methodology_repo:" in out.stdout


def test_minervit_shim_survives_python_reexec():
    # Pre-0.8.0 installs auto-update by re-exec'ing bin/minervit-methodology with
    # sys.executable (os.execve(sys.executable, [sys.executable, <this path>, ...])).
    # That immutable fleet code re-parses whatever this file becomes AFTER the
    # update, so the compat shim must stay valid Python forever: the 0.8.0 bash
    # shim broke every 0.7.x -> 0.8.x upgrade mid-flight with a SyntaxError.
    import sys
    out = subprocess.run(
        [sys.executable, str(ROOT / "bin/minervit-methodology"), "version", "--no-remote"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "methodology_repo:" in out.stdout


def test_install_cli_installs_both_launchers(tmp_path):
    import os
    home = tmp_path / "home"
    home.mkdir()
    out = subprocess.run(
        [str(ROOT / "bin/tautline"), "install-cli"],
        env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    tautline = home / ".local" / "bin" / "tautline"
    legacy = home / ".local" / "bin" / "minervit-methodology"
    assert tautline.exists() and legacy.exists()
    assert tautline.read_text() == legacy.read_text()


def _installed_shim(tmp_path) -> Path:
    import os
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    out = subprocess.run(
        [str(ROOT / "bin/tautline"), "install-cli"],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return home / ".local" / "bin" / "tautline"


def test_installed_shim_is_valid_posix_sh(tmp_path):
    """The shim runs under /bin/sh on every user machine: a template typo is a fleet outage."""
    shim = _installed_shim(tmp_path)
    check = subprocess.run(["sh", "-n", str(shim)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_installed_shim_has_no_repo_preset_exec_bypass(tmp_path):
    """Task B8, structural pin. MINERVIT_METHODOLOGY_REPO (which every v1 launcher exports) must
    not be an exec target the store can be skipped through: the store block has to be reached
    BEFORE the canonical exec, and the preset must never be exec'd directly."""
    text = _installed_shim(tmp_path).read_text(encoding="utf-8")
    assert 'exec "$MINERVIT_METHODOLOGY_REPO_PRESET' not in text, text
    store_exec = text.index('"$SNAPSHOT_CURRENT/bin/tautline"')
    canonical_exec = text.index('exec "$MINERVIT_METHODOLOGY_REPO/bin/tautline"')
    assert store_exec < canonical_exec, "the store must be tried before the canonical checkout"
