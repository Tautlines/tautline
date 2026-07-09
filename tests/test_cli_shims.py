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


def test_install_claude_launcher_reserves_tautline_name(tmp_path):
    import os
    out = subprocess.run(
        [str(ROOT / "bin/tautline"), "install-claude-launcher", "--name", "tautline",
         "--bin-dir", str(tmp_path / "bin")],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True, text=True,
    )
    assert out.returncode != 0
    assert "reserved command" in out.stderr
