import importlib
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

# Autouse fixture, registered by importing its name here: it restores the write bits on anything a
# test sealed read-only, so pytest's own tmp_path finalizer can actually reclaim the tree instead of
# silently leaving it on disk. See tests/_tmp_unseal.py for why that silence was expensive.
from _tmp_unseal import (  # noqa: F401
    _unseal_tmp_path_for_reclaim,
    pytest_runtest_makereport,
    pytest_sessionfinish,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir():
    sys.path.insert(0, str(SRC_ROOT))
CLI_PATH = REPO_ROOT / "bin" / "tautline"


#: Addresses a test may still reach: a loopback server a test started itself. Everything else is a
#: third party, and a test has no business talking to one.
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "", "0.0.0.0"}


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """No test may open a socket to anything but loopback.

    The backlog providers talk to api.github.com and to a Jira site, and a developer running this
    suite very often has a REAL `GITHUB_TOKEN` and real Jira credentials exported. A single test
    that forgot to install its fake transport would then reach a live endpoint with a live
    credential -- creating an issue, transitioning somebody's ticket, or burning rate budget --
    and it would PASS, so nothing would ever surface it. The provider suites patch at the HTTP
    boundary; this is the layer under them that makes "no live network in CI" a property of the
    test run rather than a promise each test file has to keep on its own.

    Loopback stays open because tests legitimately start local servers. Subprocesses are a
    different process and are unaffected -- which is correct: `gh auth token` is a local call.
    """
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else address
        if isinstance(host, str) and host not in _LOOPBACK:
            raise AssertionError(
                f"a test tried to open a network connection to {host!r}. Tests must not reach a "
                "third party: install a fake transport (see tests/test_backlog_providers.py) "
                "instead. This guard exists because a developer's real GITHUB_TOKEN or Jira "
                "credentials would otherwise let a missing fake mutate a live board and still pass."
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _no_real_gh_token(monkeypatch):
    """No test may shell out to the real `gh` to resolve a GitHub token.

    The socket guard above blocks THIS process; a subprocess has its own. `gh auth token` is the one
    place this codebase shells out on a credential path, and on a developer's machine it succeeds
    and hands back a real token -- so a provider test that forgot its fake would be authenticated
    rather than refused, and could reach a live board through a channel the in-process guard cannot
    see. Stubbed to "no token", which is the safe answer; a test that wants one sets the environment
    variable or overrides this deliberately, and its own patch wins because it is applied later.
    """
    from tautline_methodology import backlog

    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: "")


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

# Identity is test input, never ambient operator state. Inherited tokens can escape through an
# assertion or an evaluated shell snippet even when every HTTP request is faked. Both rebrand
# spellings matter because resolve_env falls back to MINERVIT_ after TAUTLINE_ is removed.
_OPERATOR_IDENTITY_ENV = ("GH_TOKEN", "GITHUB_TOKEN") + tuple(
    f"{prefix}_{suffix}"
    for prefix in ("TAUTLINE", "MINERVIT")
    for suffix in ("ROLE", "GITHUB_APP_ID", "GITHUB_APP_KEY", "GITHUB_APP_INSTALLATION_ID")
)

# _OPERATOR_SESSION_ENV is the launcher's own profile, where BOTH spellings must go because those
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
    for name in (*_OPERATOR_SESSION_ENV, *_OPERATOR_IDENTITY_ENV):
        monkeypatch.delenv(name, raising=False)
    for alias in _shadowing_aliases():
        monkeypatch.delenv(alias, raising=False)


@pytest.fixture
def run_cli(tmp_path):
    """Black-box runner with a hermetic HOME, mirroring validate.sh's isolation."""

    def _run(*args, stdin=None, cwd=None):
        # `cwd` matters for any adapter whose paths are project-relative: the event log is one, so
        # a caller that leaves it unset has the CLI resolve `.ai-work/events/...` against the
        # REPOSITORY, where every test and every earlier local run appends to one shared file.
        # Passing the lane makes that log per-test, which is the only way an assertion about it can
        # be about the command under test rather than about ambient state.
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "HOME": str(home)}
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            input=stdin,
            env=env,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=60,  # a CLI hang/regression should fail the test, not stall CI
        )

    return _run


# ---------------------------------------------------------------- agent-agnostic seam lanes
import subprocess as _subprocess  # noqa: E402


@pytest.fixture
def lane(tmp_path):
    repo = tmp_path / "lane"
    repo.mkdir()
    def run(*a):
        # A def, not a lambda: ruff E731. Third lane fixture in this plan with the same
        # lambda -- fixed on sight here rather than after lint says so again.
        return _subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)

    run("init", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "src.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("checkout", "-b", "feature")
    (repo / "src.py").write_text("x = 2\n")
    run("add", "-A")
    run("commit", "-m", "change")
    # `lane_project()` validates the adapter's `repo` against the target's git remote and
    # refuses with "Project adapter repo does not match the target git remote" otherwise. The
    # overlay is `example-saas` (`example-org/example-saas`). This is a SEPARATE copy of the
    # lane fixture from R2.5's, so the fix made there did not reach it -- added here on sight
    # rather than after the guard refuses, which it has already done three times in this program.
    run("remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    # A FETCHED base ref, not just a remote. `review_evidence_check` diffs against
    # `origin/main` and refuses when the remote is configured but its base ref is unfetched --
    # correctly, since it cannot compute an outgoing diff against a ref it does not have. The
    # lane has no reachable remote, so it plants the ref locally, which is exactly what a fetch
    # would leave behind.
    base_sha = _subprocess.run(["git", "rev-parse", "main"], cwd=repo, check=True,
                               capture_output=True, text=True).stdout.strip()
    run("update-ref", "refs/remotes/origin/main", base_sha)
    return repo
