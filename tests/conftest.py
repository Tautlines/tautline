import importlib
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir():
    sys.path.insert(0, str(SRC_ROOT))
CLI_PATH = REPO_ROOT / "bin" / "tautline"


@pytest.fixture(scope="session")
def cli():
    """The CLI engine module for in-process pure-function tests.

    Post package-split (roadmap #11) the whole engine -- every command handler,
    dispatch_command, main(), and the eager wave aliases -- lives in
    ``tautline_methodology.cli``; ``bin/tautline`` is a thin shim that imports main() from
    here. Import the real package module directly (SRC_ROOT is on sys.path above). The
    module's ``__main__`` guard means main() never runs on import.
    """
    return importlib.import_module("tautline_methodology.cli")


@pytest.fixture(autouse=True)
def _no_operator_maintainer_mode(monkeypatch, tmp_path):
    """Keep the OPERATOR'S OWN maintainer-mode state out of every in-process test.

    The session `cli` module bakes USER_CONFIG_ENV from the real HOME at import, and
    maintainer_mode_config_value() reads that file by design (file-only residency). So on a
    machine where the maintainer has legitimately run `tautline maintainer-mode on`, every
    in-process test that reaches update_methodology_repo gets ("skipped", "maintainer mode ...")
    instead of the behavior it asserts -- six upstream-trust tests go red for reasons that have
    nothing to do with the change under test. A suite that only passes on machines whose
    operator has not used the product is not a suite anyone can trust.

    Pointing both config surfaces at paths under tmp_path neutralizes the read without touching
    HOME (too blunt: many fixtures derive state dirs from it) and without touching subprocess
    tests, which pass their own hermetic HOME. test_maintainer_mode.py loads its own modules
    anchored on hermetic HOMEs, so this never masks the tests that exercise the mode on purpose.
    """
    module = importlib.import_module("tautline_methodology.cli")
    absent = tmp_path / "no-operator-config"
    monkeypatch.setattr(module, "USER_CONFIG_ENV", absent / "tautline.env", raising=False)
    monkeypatch.setattr(module, "LEGACY_USER_CONFIG_ENV", absent / "methodology.env", raising=False)


# Both env spellings are live during the rebrand, and resolve_env prefers TAUTLINE_. A test that
# sets only the MINERVIT_ spelling is therefore silently overridden on a session that exports the
# TAUTLINE_ one -- which the operator launcher does, by design.
_OPERATOR_SESSION_ENV = tuple(
    f"{prefix}_METHODOLOGY_{suffix}"
    for prefix in ("TAUTLINE", "MINERVIT")
    for suffix in (
        "UPDATE_POLICY",
        "UPDATE_PINS",
        "UPDATE_SIGNERS",
        "AVAILABLE_VERSION",
        "DISABLE_SNAPSHOT_EXEC",
        "DISABLE_AUTO_RESCUE",
    )
)

# The list above is the launcher's own profile, where BOTH spellings must go because those
# variables disable whole subsystems. Shadowing is a second, larger problem: ANY variable a test
# sets under the legacy name can be overridden by its TAUTLINE_ alias, and enumerating that set by
# hand does not converge -- successive review rounds each surfaced one more name (ALLOW_NON_MAIN,
# REAL_CODEX, CANONICAL_REPO/SNAPSHOT_STORE).
#
# So the alias set is read off the suite instead. Note the asymmetry that makes this safe: dropping
# an alias nothing needed costs nothing, while ASSERTING on an over-broad set fails the suite for
# operators whose environment is perfectly valid. Earlier attempts here asserted, and every one of
# their defects came from that. This only deletes, so the scan is free to be generous.
_LEGACY_ENV_NAME = re.compile(r'"(MINERVIT_[A-Z0-9_]+)"')


@lru_cache(maxsize=1)
def _shadowing_aliases() -> tuple[str, ...]:
    """TAUTLINE_ aliases of every legacy env name the suite mentions."""
    legacy: set[str] = set()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        legacy.update(_LEGACY_ENV_NAME.findall(path.read_text(encoding="utf-8")))
    return tuple(sorted(f"TAUTLINE_{name[len('MINERVIT_'):]}" for name in legacy))


@pytest.fixture(autouse=True)
def _no_operator_session_env(monkeypatch):
    """Keep the OPERATOR'S OWN launcher env out of every in-process test.

    Same principle as _no_operator_maintainer_mode above. The operator fleet launcher exports a
    session profile so the operator's own sessions never block: `UPDATE_POLICY=unverified` plus its
    pins, `DISABLE_AUTO_RESCUE=1`, and `DISABLE_SNAPSHOT_EXEC=1`. Every one of those is correct for
    the launcher and wrong for the suite, because each disables the very behavior a group of tests
    exists to assert:

    - UPDATE_POLICY/PINS/SIGNERS -- an inherited `unverified` makes verify_upstream_trust allow
      everything, so the trust tests' refusals, holds, and warn-default fallback never happen.
    - DISABLE_SNAPSHOT_EXEC -- the snapshot store never engages, so the snapshot/heal/pin tests
      assert against a subsystem that stood down.
    - DISABLE_AUTO_RESCUE -- the sync CLI's rescue paths stand down, so the rescue tests see a bare
      failure instead of the rescue they drive.

    Measured on this branch: 23 tests across 6 modules fail from this leakage alone and pass once
    it is scrubbed. A suite whose result depends on whether the operator launched the session is
    not a suite anyone can read, so the scrub gives every test the same baseline CI has. Tests that
    need one of these set it themselves.

    On top of that profile, every TAUTLINE_ alias of a legacy name the suite mentions is dropped,
    so it cannot shadow the spelling a test sets (see _shadowing_aliases above).
    """
    for name in _OPERATOR_SESSION_ENV:
        monkeypatch.delenv(name, raising=False)
    for alias in _shadowing_aliases():
        monkeypatch.delenv(alias, raising=False)


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
