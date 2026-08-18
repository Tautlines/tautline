"""Let pytest reclaim the tmp trees this suite deliberately seals read-only.

Imported for its side effects by ``tests/conftest.py``: the autouse fixture and the two hooks below
are registered by importing their names into the conftest namespace.

Why this has to exist: the installer and the snapshot store seal every tree they publish
(``core/runtime.py::_seal_readonly`` -- 0o555 directories, 0o444 files), which is correct, because
an installed release is immutable by design. Production owns exactly one sanctioned teardown for
such a tree, ``_rmtree_force``, and it works by restoring the write bits first.

pytest cannot use that helper. Its reclaim is ``shutil.rmtree(path, ignore_errors=True)``, and plain
``rmtree`` cannot unlink a child of a 0o555 directory. With ``ignore_errors=True`` it does not even
complain -- the leak is indistinguishable from a clean reclaim, which is why nobody noticed until
``$TMPDIR/pytest-of-<user>`` reached 17 GB and filled the disk.

**Unseal only what pytest is about to delete.** Restoring write bits is destructive to evidence: it
rewrites the modes of the tree a failing test left behind, and a test that failed BECAUSE of
permissions is exactly the one whose modes a human needs to read. Retention exists to preserve that
state, so an unconditional finalizer would quietly defeat the thing it was added to support. Every
unseal below is therefore gated on pytest actually reclaiming the tree -- same conditions pytest
itself uses, which is why they are spelled out rather than approximated.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Owner bits only. The trees under tmp_path are ours by construction, and widening group/other here
# would hand out access the sealing existed to withhold.
_DIR_WRITE = 0o700
_FILE_WRITE = 0o600

# Set when a test's setup or call phase did not pass, so teardown can tell whether pytest is keeping
# this tree as evidence or throwing it away.
_FAILED = pytest.StashKey[bool]()


def unseal_tree(root: Path | str) -> None:
    """Restore owner write permission across ``root`` so a plain ``rmtree`` can remove it.

    Best effort by contract: this runs in teardown, so a tree that has already been removed, a path
    that vanished mid-walk, or a mode that cannot be changed must not turn an unrelated passing test
    red. A missing ``root`` simply walks nothing.

    Symlinks are never chmod'ed. ``os.walk`` does not descend into symlinked directories, and
    ``os.chmod`` on a symlink follows it by default -- so touching one could change the mode of a
    file outside the tree entirely. The sealed trees contain symlinks (installed releases carry
    them), which makes this a real path rather than a theoretical one.
    """
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        try:
            os.chmod(dirpath, os.stat(dirpath).st_mode | _DIR_WRITE)
        except OSError:
            # An unreadable/unwritable directory stops this branch, not the sweep: siblings still
            # get their bits back, so the reclaim is partial rather than abandoned.
            continue
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path):
                    continue
                os.chmod(path, os.stat(path).st_mode | _FILE_WRITE)
            except OSError:
                continue


def _reclaims_passing_trees(config: pytest.Config) -> bool:
    """True when pytest deletes a tmp_path as soon as its test passes."""
    return config.getini("tmp_path_retention_policy") == "failed"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    """Remember that this test did not pass, before its fixtures tear down.

    makereport for setup/call runs ahead of teardown finalizers, so the flag is set in time for the
    fixture below to read it.
    """
    report = yield
    if report.when in ("setup", "call") and not report.passed:
        item.stash[_FAILED] = True
    return report


@pytest.fixture(autouse=True)
def _unseal_tmp_path_for_reclaim(request, tmp_path):
    """Hand pytest a removable tree -- but only when it is going to remove this one."""
    yield
    if not _reclaims_passing_trees(request.config):
        return  # nothing is reclaimed per-test, so unsealing would only rewrite kept evidence
    if request.node.stash.get(_FAILED, False):
        return  # pytest keeps a failed test's tree; leave its modes exactly as the test left them
    unseal_tree(tmp_path)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus) -> None:
    """Same job one level up, for trees no per-test reclaim can see.

    ``tmp_path_factory.mktemp()`` allocates directly under the basetemp, so a module- or
    session-scoped fixture's tree is invisible to the fixture above -- ``test_cut_release.py`` builds
    a real snapshot exec root that way, and the snapshot store seals it. The only sweep that can ever
    remove it is pytest's whole-basetemp ``rmtree(..., ignore_errors=True)``, which is just as silent
    about sealed trees.

    Gated on the exact conditions under which pytest performs that sweep -- green session, per-test
    reclaim enabled, and no operator-supplied basetemp. On a red session the whole basetemp is kept
    for inspection, so unsealing it would rewrite the modes of every tree a human is about to read.
    ``tryfirst`` puts this ahead of pytest's own sessionfinish, which is the one doing the removing.
    """
    if exitstatus != 0 or not _reclaims_passing_trees(session.config):
        return
    factory = getattr(session.config, "_tmp_path_factory", None)
    basetemp = getattr(factory, "_basetemp", None)
    if basetemp is None or getattr(factory, "_given_basetemp", None) is not None:
        return
    unseal_tree(basetemp)
