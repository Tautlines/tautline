"""pytest must be able to reclaim tmp trees that the product deliberately sealed read-only.

The suite exercises the installer and the snapshot store, and both seal their published trees
(``core/runtime.py::_seal_readonly`` -> 0o555 dirs, 0o444 files; ``cli.py`` seals a release root the
same way). That sealing is correct -- an installed release is immutable on purpose, and production
owns ``_rmtree_force`` for the one path allowed to tear it down.

pytest does not own that helper. Its ``tmp_path`` finalizer calls ``shutil.rmtree(path,
ignore_errors=True)``, which cannot unlink a child of a 0o555 directory AND does not report that it
failed -- so a leaked tree looks exactly like a clean reclaim. On 2026-08-16 that filled the disk:
17 GB across 13 sessions' worth of ``$TMPDIR/pytest-of-<user>``.

These tests pin the two halves of the fix: the unseal helper itself, and the autouse fixture that
runs it before pytest's own finalizer gets its turn.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent


def _seal(root: Path) -> None:
    """Seal a tree exactly the way the product does, so these tests fail for the real reason."""
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            path = Path(dirpath) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        if Path(dirpath) != root:
            Path(dirpath).chmod(0o555)


def _release_tree(parent: Path) -> Path:
    """A miniature of what the installer tests leave behind, sealed the way the installer seals."""
    tree = parent / "home" / ".local" / "share" / "minervit" / "tautline-releases" / "e211351cd399"
    (tree / "bin").mkdir(parents=True)
    (tree / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    (tree / "LICENSE").write_text("license\n", encoding="utf-8")
    _seal(tree)
    return tree


def test_shutil_rmtree_silently_leaves_a_sealed_tree_behind(tmp_path):
    """The external invariant the whole fix rests on: the failure mode is silent, not loud.

    If a future stdlib or pytest ever makes this raise -- or succeed -- the fix below needs
    revisiting, and this test is the tripwire that says so.
    """
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    _release_tree(doomed)

    shutil.rmtree(doomed, ignore_errors=True)  # exactly what pytest's tmp_path finalizer calls

    assert doomed.exists(), "sealed tree unexpectedly removed -- pytest's finalizer may now suffice"


def test_unseal_tree_makes_a_sealed_tree_removable(tmp_path):
    from _tmp_unseal import unseal_tree

    doomed = tmp_path / "doomed"
    doomed.mkdir()
    _release_tree(doomed)

    unseal_tree(doomed)
    shutil.rmtree(doomed, ignore_errors=True)

    assert not doomed.exists()


def test_unseal_tree_tolerates_a_root_that_is_already_gone(tmp_path):
    """Teardown runs on every test, including ones whose tmp_path never existed or was moved."""
    from _tmp_unseal import unseal_tree

    unseal_tree(tmp_path / "never-created")  # must not raise


def _child_env(**extra: str) -> dict[str, str]:
    """An environment a nested pytest can actually start in.

    The outer run's pytest variables MUST NOT reach the child. PYTEST_ADDOPTS is the one that
    bites: scripts/test.sh puts `-n auto` (and its junit report path) in there, the child inherits
    it, and because these child runs pass `-p no:xdist` on purpose -- they need one deterministic
    process to assert about -- the `-n` it inherits is suddenly an unrecognized argument and the
    child dies at exit code 4 before running a single test.

    That combination only exists under the real gate, so a worktree run is green and the
    fresh-checkout gate is red. Scrub the whole family rather than just the one name we tripped on:
    PYTEST_CURRENT_TEST and PYTEST_XDIST_WORKER describe the OUTER test, and inheriting them into a
    nested session is meaningless at best.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.update(extra)
    return env


def _run_pytest_on(
    project: Path, basetemp: Path, *, wire_fixture: bool
) -> subprocess.CompletedProcess:
    """Run a real pytest session over a generated project, optionally wiring the real fixture in.

    A subprocess is the only honest way to assert on what survives a *session*: the fixture under
    test tears down inside that session, so an in-process assertion would race its own teardown.
    """
    conftest = "import sys\nsys.path.insert(0, %r)\n" % str(TESTS_ROOT)
    if wire_fixture:
        conftest += (
            "from _tmp_unseal import (  # noqa: F401\n"
            "    _unseal_tmp_path_for_reclaim,\n"
            "    pytest_runtest_makereport,\n"
            ")\n"
        )
    (project / "conftest.py").write_text(conftest, encoding="utf-8")

    return subprocess.run(
        [
            sys.executable, "-m", "pytest", str(project),
            "-p", "no:cacheprovider",
            "-p", "no:xdist",
            "-o", "tmp_path_retention_policy=failed",
            "--basetemp", str(basetemp),
            "-q",
        ],
        cwd=str(project),
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


SEALING_TEST = textwrap.dedent(
    """
    import os
    from pathlib import Path

    def _seal(root):
        for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
            for name in filenames:
                p = Path(dirpath) / name
                p.chmod(0o555 if p.stat().st_mode & 0o111 else 0o444)
            if Path(dirpath) != root:
                Path(dirpath).chmod(0o555)

    def test_seals_a_release_tree(tmp_path):
        tree = tmp_path / "home" / ".local" / "share" / "releases" / "abc"
        (tree / "bin").mkdir(parents=True)
        (tree / "bin" / "cli").write_text("#!/bin/sh\\n")
        _seal(tree)
        assert tree.exists()
    """
)


def test_passing_test_leaves_no_sealed_tmp_tree_behind(tmp_path):
    """The behaviour that actually keeps the disk from filling."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_seal.py").write_text(SEALING_TEST, encoding="utf-8")
    basetemp = tmp_path / "basetemp"

    result = _run_pytest_on(project, basetemp, wire_fixture=True)

    assert result.returncode == 0, result.stdout + result.stderr
    leaked = [p for p in basetemp.glob("test_seals_a_release_tree*") if p.is_dir()]
    assert leaked == [], f"sealed tmp tree survived a passing test: {leaked}"


def test_unwired_session_leaks_the_sealed_tree(tmp_path):
    """Proof the fixture is what does the work, not pytest's retention policy on its own."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_seal.py").write_text(SEALING_TEST, encoding="utf-8")
    basetemp = tmp_path / "basetemp"

    result = _run_pytest_on(project, basetemp, wire_fixture=False)

    assert result.returncode == 0, result.stdout + result.stderr
    leaked = [p for p in basetemp.glob("test_seals_a_release_tree*") if p.is_dir()]
    assert leaked, "expected the unwired session to leak -- the fixture may no longer be needed"


FAILING_SEALING_TEST = SEALING_TEST + textwrap.dedent(
    """
    def test_fails_after_sealing(tmp_path):
        # Nested on purpose: _seal leaves its OWN root writable (a 0555 root cannot be renamed
        # into place), so a one-level tree would have no sealed DIRECTORY to assert about.
        tree = tmp_path / "evidence"
        inner = tree / "sealed"
        inner.mkdir(parents=True)
        (inner / "note.txt").write_text("why it failed\\n")
        _seal(tree)
        assert False, "deliberate"
    """
)


def test_failing_test_keeps_its_tmp_tree_as_evidence(tmp_path):
    """Reclaiming disk must never cost us the artifacts that explain a failure."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_seal.py").write_text(FAILING_SEALING_TEST, encoding="utf-8")
    basetemp = tmp_path / "basetemp"

    result = _run_pytest_on(project, basetemp, wire_fixture=True)

    assert result.returncode != 0, result.stdout + result.stderr
    kept = [p for p in basetemp.glob("test_fails_after_sealing*") if p.is_dir()]
    assert kept, "a failing test's tmp tree was destroyed -- debugging evidence lost"
    assert (kept[0] / "evidence" / "sealed" / "note.txt").exists()


def test_a_failing_tests_kept_tree_still_has_the_modes_it_failed_with(tmp_path):
    """Keeping the tree is not enough -- the MODES are the evidence in a permission failure.

    Restoring write bits is itself destructive. An unconditional finalizer would run before pytest
    retains a failed test's tmp_path, rewriting 0o555 to 0o755 with no deletion following, so the
    one failure whose cause lives in the permissions is the one whose cause gets erased. Codex R1
    [P2] raised this against exactly that shape.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_seal.py").write_text(FAILING_SEALING_TEST, encoding="utf-8")
    basetemp = tmp_path / "basetemp"

    result = _run_pytest_on(project, basetemp, wire_fixture=True)

    assert result.returncode != 0, result.stdout + result.stderr
    kept = [p for p in basetemp.glob("test_fails_after_sealing*") if p.is_dir()]
    assert kept, "a failing test's tmp tree was destroyed -- debugging evidence lost"
    sealed_dir = kept[0] / "evidence" / "sealed"
    mode = stat.S_IMODE(sealed_dir.stat().st_mode)
    assert not mode & stat.S_IWUSR, (
        f"the kept tree was unsealed to {oct(mode)}; a permission failure's evidence is its modes"
    )


FACTORY_SEALING_TEST = textwrap.dedent(
    """
    import os
    from pathlib import Path
    import pytest

    def _seal(root):
        for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
            for name in filenames:
                p = Path(dirpath) / name
                p.chmod(0o555 if p.stat().st_mode & 0o111 else 0o444)
            if Path(dirpath) != root:
                Path(dirpath).chmod(0o555)

    @pytest.fixture(scope="module")
    def snapshot_exec_root(tmp_path_factory):
        dest = tmp_path_factory.mktemp("snapshot") / "exec-root"
        (dest / "bin").mkdir(parents=True)
        (dest / "bin" / "cli").write_text("#!/bin/sh\\n")
        _seal(dest)
        return dest

    def test_uses_a_sealed_snapshot(snapshot_exec_root):
        assert snapshot_exec_root.exists()
    """
)


def test_session_scoped_sealed_tree_does_not_block_basetemp_reclaim(tmp_path):
    """A sealed tree from tmp_path_factory sits OUTSIDE any test's tmp_path.

    Per-test reclaim never sees it, so only the whole-basetemp sweep at session end can remove it --
    and that sweep is ``shutil.rmtree(basetemp, ignore_errors=True)`` too, with the same silence.
    test_cut_release.py builds a real snapshot exec root exactly this way, so this is the suite's
    live case, not a hypothetical.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_factory.py").write_text(FACTORY_SEALING_TEST, encoding="utf-8")
    (project / "conftest.py").write_text(
        "import sys\nsys.path.insert(0, %r)\n"
        "from _tmp_unseal import (  # noqa: F401\n"
        "    _unseal_tmp_path_for_reclaim,\n"
        "    pytest_runtest_makereport,\n"
        "    pytest_sessionfinish,\n"
        ")\n"
        % str(TESTS_ROOT),
        encoding="utf-8",
    )
    temproot = tmp_path / "temproot"
    temproot.mkdir()

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(project),
            "-p", "no:cacheprovider",
            "-p", "no:xdist",
            "-o", "tmp_path_retention_policy=failed",
            "-q",
        ],
        cwd=str(project),
        env=_child_env(PYTEST_DEBUG_TEMPROOT=str(temproot)),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    survivors = [
        p
        for root in temproot.glob("pytest-of-*")
        for p in root.glob("pytest-*")
        if p.is_dir() and not p.is_symlink()
    ]
    assert survivors == [], f"sealed session-scoped tree blocked the basetemp reclaim: {survivors}"


def test_child_env_drops_the_outer_runs_pytest_variables(monkeypatch):
    """The scrub is the only reason these nested-pytest tests survive the real gate.

    Without it the suite is green in a worktree and red under scripts/test.sh, which is the worst
    possible split: the gate that exists to catch this is the only thing that sees it.
    """
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n auto --junitxml=/somewhere/report.xml")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_outer.py::test_outer (call)")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = _child_env(PYTEST_DEBUG_TEMPROOT="/tmp/somewhere")

    assert [name for name in env if name.startswith("PYTEST_")] == ["PYTEST_DEBUG_TEMPROOT"]
    assert env["PYTEST_DEBUG_TEMPROOT"] == "/tmp/somewhere"
    assert env["PATH"] == "/usr/bin", "the child still needs the rest of the environment"


def test_suite_configures_failed_retention_policy():
    """Without this ini setting the fixture has nothing to hand a reclaim to.

    pytest's own numbered-dir GC only runs at *clean* interpreter exit and then honours a stale
    lock for LOCK_TIMEOUT (3 days), so an interrupted run -- routine in agent sessions -- leaks its
    whole basetemp. Per-test reclaim is what makes an interrupted run cheap.
    """
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ini = config["tool"]["pytest"]["ini_options"]
    assert ini.get("tmp_path_retention_policy") == "failed"


def test_conftest_registers_the_unseal_fixture():
    """The helper module is inert unless conftest imports it into the fixture namespace."""
    source = (TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "_unseal_tmp_path_for_reclaim" in source
