import importlib.util
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir():
    sys.path.insert(0, str(SRC_ROOT))
CLI_PATH = REPO_ROOT / "bin" / "tautline"


@pytest.fixture(scope="session")
def cli():
    """Import the extension-less CLI as a module for in-process pure-function tests.

    spec_from_file_location() returns None for a file with no .py extension, so build an
    explicit SourceFileLoader. The module's __main__ guard means main() never runs on import.
    """
    loader = SourceFileLoader("minervit_methodology", str(CLI_PATH))
    spec = importlib.util.spec_from_loader("minervit_methodology", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def run_cli(tmp_path):
    """Black-box runner with a hermetic HOME, mirroring validate.sh's isolation."""

    def _run(*args, stdin=None):
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "HOME": str(home)}
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            input=stdin,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,  # a CLI hang/regression should fail the test, not stall CI
        )

    return _run
