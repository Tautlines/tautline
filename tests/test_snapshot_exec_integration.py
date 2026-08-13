"""Tasks B6 + B7: the snapshot store meets the trust-gated re-exec path, and the launcher gate.

These tests drive the REAL CLI end to end -- a fixture upstream, a canonical clone, and a store on
disk -- because the property under test only exists across an `os.execve` boundary: the process
that materializes a snapshot is never the process that runs it.

The load-bearing B6 case is `test_materialize_failure_from_snapshot_reexecs_canonical`. When a lane
is already executing a snapshot and the store cannot publish the new one, re-execing our OWN
snapshot would hand it a token bound to the NEW head while its manifest still says the OLD one --
the snapshot would reject its own re-exec token ("invalid or expired") and the launch would block.
The canonical checkout is at the new head and already trust-verified, so it is what we exec.

The load-bearing B7 case is `test_launcher_gate_lock_survives_reexec`. CPython opens descriptors
close-on-exec, so a gate that flocked a plain file handle would silently RELEASE its lock at the
very moment a trust-gated advance re-execs -- a second lane would walk straight into the gate while
the first is mid-advance. Nothing but a real execve can prove the fd survived it, so the re-exec'd
process parks itself while a sibling proves the lock is still held.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_sync_methodology_cli import _advance_remote, _git, _make_methodology_fixture, _run_cli

SENTINEL = "methodology_sentinel: new-code"
# Printed only by a process that CONSUMED a valid re-exec token: the proof the handoff was accepted.
REEXEC_ACCEPTED = "methodology_update: skipped - already updated in this lane-start process"

# Both alias spellings of every managed key: resolve_env PREFERS the TAUTLINE_ alias, and a
# subprocess inherits the operator's real shell. A test that cleared only the MINERVIT_ spelling
# could resolve the canonical repo (or the store) against the operator's live machine.
MANAGED_ENV_NAMES = (
    "MINERVIT_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
    "MINERVIT_METHODOLOGY_SNAPSHOT_KEEP",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_KEEP",
    "MINERVIT_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "MINERVIT_METHODOLOGY_UPDATE_POLICY",
    "TAUTLINE_METHODOLOGY_UPDATE_POLICY",
    "MINERVIT_METHODOLOGY_UPDATE_PINS",
    "TAUTLINE_METHODOLOGY_UPDATE_PINS",
    "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "TAUTLINE_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    "TAUTLINE_METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    # The exec-handoff pair has no TAUTLINE_ alias BY DESIGN (see tests/test_env_reads_use_resolver
    # .py): only the gate itself may ever set them, so a stray one in the runner's shell must not
    # reach the CLI under test.
    "MINERVIT_METHODOLOGY_SYNC_LOCK_FD",
    "MINERVIT_METHODOLOGY_SYNC_GATE",
)

STAMP_SCHEMA = "tautline-methodology-sync-stamp/v1"
STATE_DIR = (".local", "state", "minervit")


def _env(store: Path, **extra: str) -> dict[str, str]:
    env = {name: "" for name in MANAGED_ENV_NAMES}
    env["MINERVIT_METHODOLOGY_SNAPSHOT_STORE"] = str(store)
    env.update(extra)
    return env


def _unlock(root: Path) -> None:
    """Published snapshots are 0555 dirs / 0444 files; hand tmp_path back something removable."""
    if not root.exists():
        return
    try:
        root.chmod(0o755)
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            try:
                os.chmod(os.path.join(dirpath, name), 0o755)
            except OSError:
                pass


@pytest.fixture()
def store(tmp_path):
    root = tmp_path / "store"
    yield root
    _unlock(root)


# Planted at the top of the ADVANCED upstream CLI, so it runs in the re-exec'd process and nowhere
# else. It reports what the successor inherited (the lock fd number, the freshness stamp as it
# stood BEFORE the exec) and, when the test asks it to, parks there so the test can interrogate the
# lock while a re-exec'd gate is provably mid-flight.
GATE_PROBE = """
import os
import time
from pathlib import Path
_probe_dir = os.environ.get("TAUTLINE_TEST_GATE_PROBE", "")
if _probe_dir:
    _probe = Path(_probe_dir)
    _stamp = Path.home() / ".local" / "state" / "minervit" / "methodology-sync.stamp"
    _text = _stamp.read_text(encoding="utf-8") if _stamp.is_file() else "missing"
    (_probe / "stamp-at-reexec").write_text(_text, encoding="utf-8")
    _fd = os.environ.get("MINERVIT_METHODOLOGY_SYNC_LOCK_FD", "missing")
    (_probe / "reexec-started").write_text(_fd, encoding="utf-8")
    _deadline = time.time() + 60
    while (_probe / "wait").exists() and not (_probe / "go").exists():
        if time.time() > _deadline:
            break
        time.sleep(0.05)
"""


def _advance_remote_with_sentinel(source: Path, extra: str = "") -> str:
    """Advance the fixture upstream with a commit whose bin/tautline ANNOUNCES ITSELF on startup.

    Nothing else can distinguish "we re-exec'd the new code" from "we printed a hopeful message and
    kept running the old code": the sentinel only reaches stdout if the new tree is what executes.
    """
    cli_path = source / "bin" / "tautline"
    text = cli_path.read_text(encoding="utf-8")
    anchor = "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
    assert anchor in text, "anchor line for the sentinel is gone from bin/tautline"
    injected = f'print("{SENTINEL}", flush=True)\n{extra}'
    cli_path.write_text(text.replace(anchor, anchor + injected, 1), encoding="utf-8")
    _git(source, "add", "bin/tautline")
    _git(source, "commit", "-q", "-m", "advance methodology remote with startup sentinel")
    _git(source, "push", "-q", "origin", "main")
    return _git(source, "rev-parse", "HEAD")


def _snapshots(store: Path) -> list[str]:
    return sorted(
        path.name
        for path in store.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name not in ("pins", "current")
    )


def test_advance_materializes_swaps_and_reexecs_new_snapshot(tmp_path, store):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"methodology_snapshot: materialized {new_head[:12]}" in result.stdout
    assert f"current -> {new_head[:12]}" in result.stdout
    assert SENTINEL in result.stdout, "the re-exec must run the NEW code"
    # The re-exec'd process accepted the token and reports the NEW commit -- from the snapshot's
    # manifest, since a snapshot has no .git for rev-parse to read.
    assert REEXEC_ACCEPTED in result.stdout
    assert f"methodology_commit: {new_head[:12]}" in result.stdout
    snapshot = (store / new_head[:12]).resolve()
    assert f"methodology_exec_root: {snapshot} (snapshot {new_head[:12]})" in result.stdout
    assert (store / "current").resolve() == snapshot
    assert _git(clone, "rev-parse", "HEAD") == new_head


def test_disable_snapshot_exec_holds_the_advance_on_the_canonical_checkout(tmp_path, store):
    """The documented rollback lever must survive a trust-gated upstream advance.

    `MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC=1` is what release-engineering.md tells an operator
    to set to take a machine back to executing the canonical checkout -- and it is reached for
    PRECISELY when the store has published a bad snapshot. If the next advance materializes anyway,
    swaps `current`, exports an exec root and re-execs the snapshot, the lever has handed the
    session straight back into the store it was supposed to escape, and a documented rollback that
    does not roll back is worse than none: under the launcher's no-dead-ends policy it drives the
    repair session into the very snapshot the operator is fleeing.

    The advance itself is NOT disabled -- the lever governs EXECUTION, not syncing -- so the
    canonical checkout still fast-forwards and still re-execs the new code from the checkout.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env=_env(store, MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC="1"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # The sync still advances the canonical checkout and still re-execs the NEW code.
    assert _git(clone, "rev-parse", "HEAD") == new_head
    assert SENTINEL in result.stdout, "the re-exec must still run the new code"
    assert REEXEC_ACCEPTED in result.stdout
    # ...from the CHECKOUT. Nothing was published, `current` was never swapped, and no exec root
    # was exported for this session's children to inherit.
    assert "methodology_snapshot:" not in result.stdout, result.stdout
    assert f"methodology_exec_root: {clone.resolve()} (canonical checkout)" in result.stdout
    assert not (store / "current").is_symlink()
    assert not (store / "current").exists()
    assert not store.exists() or _snapshots(store) == []


def test_held_does_not_touch_store(tmp_path, store):
    """A held advance runs unverified code nowhere: not in the checkout, not into the store."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    pinned = _git(clone, "rev-parse", "HEAD")  # the retained head is the only trusted commit
    bootstrap = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert (store / "current").resolve() == (store / pinned[:12]).resolve()
    _advance_remote(source, "HELD.md", "an upstream advance the pin does not cover")

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env=_env(
            store,
            MINERVIT_METHODOLOGY_UPDATE_POLICY="pinned",
            MINERVIT_METHODOLOGY_UPDATE_PINS=pinned,
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_update: held" in result.stdout
    assert _git(clone, "rev-parse", "HEAD") == pinned, "the checkout must not advance"
    assert "methodology_snapshot: materialized" not in result.stdout
    assert _snapshots(store) == [pinned[:12]], "no snapshot of the untrusted head"
    assert (store / "current").resolve() == (store / pinned[:12]).resolve()


def test_materialize_failure_never_blocks_launch(tmp_path, store):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    store.mkdir()
    store.chmod(0o000)  # a store nobody can even open
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_snapshot: failed" in result.stdout
    # The launch still adopts the new code -- from the canonical checkout, exactly as it did
    # before the store existed.
    assert SENTINEL in result.stdout
    assert REEXEC_ACCEPTED in result.stdout
    assert _git(clone, "rev-parse", "HEAD") == new_head


# A store that denies every read, injected at the PATHLIB boundary -- the layer the store helpers
# actually call, and the one place no interpreter gets to overrule us.
#
# Denying the syscalls instead (os.lstat & co.) would NOT do: pathlib is exactly what disagrees
# across versions. 3.11+ routes Path.is_symlink through os.path.islink, which returns False on any
# OSError, so a denied lstat there is swallowed before the CLI ever sees it -- the bug would stay
# invisible on the very interpreter our dev venvs run. Raising OUT of Path.is_symlink() reproduces
# what CI's linux runners see on 3.10 and 3.12, on every interpreter and every platform, and it
# states the invariant directly: a store read raised, and NOTHING may let that escape to the CLI.
#
# The write/open surface is denied too, so an EACCES store is modelled honestly end to end -- those
# calls were already inside an `except OSError`, and this keeps them honest.
_STORE_EACCES_SITECUSTOMIZE = '''\
import errno
import os
import pathlib

_STORE = os.environ["TAUTLINE_TEST_EACCES_STORE"]


def _denied(name):
    real = getattr(pathlib.Path, name)

    def deny(self, *args, **kwargs):
        if str(self).startswith(_STORE):
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    return deny


# resolve() is deliberately absent: it takes strict=False everywhere in the store helpers, and in
# non-strict mode it genuinely does swallow EACCES on every version. Denying it would be modelling
# a failure the real world does not produce.
for _name in (
    "is_symlink", "is_dir", "is_file", "exists", "iterdir",
    "stat", "lstat", "glob", "open", "read_text", "mkdir",
):
    setattr(pathlib.Path, _name, _denied(_name))
'''


def _eacces_store_env(tmp_path: Path, store: Path) -> dict[str, str]:
    """Make every read of `store` raise EACCES in the CLI subprocess, on any OS and interpreter."""
    fault_dir = tmp_path / "eacces-fault"
    fault_dir.mkdir()
    (fault_dir / "sitecustomize.py").write_text(_STORE_EACCES_SITECUSTOMIZE, encoding="utf-8")
    # PYTHONPATH (not a conftest patch) because the crash happens in a process we never touch: the
    # CLI re-execs itself mid-sync, and os.execve carries the env -- and only the env -- across.
    return _env(
        store,
        PYTHONPATH=str(fault_dir),
        TAUTLINE_TEST_EACCES_STORE=str(store),
    )


def test_unreadable_store_never_blocks_launch(tmp_path, store):
    """The store is an optimization, never a dependency: a store we cannot even READ must degrade
    to the canonical checkout with a warning, and must NEVER raise past its helper.

    The chmod-000 sibling above is not enough on its own. Whether a 000 directory actually makes
    pathlib raise depends on the platform and the interpreter -- pathlib swallows EACCES out of
    is_symlink() on some (macOS/3.14, where this repo's dev venvs live) and propagates it on others
    (CI's linux runners, on both 3.10 and 3.12) -- so it passed locally for the entire time the bug
    was live and only ever went red in CI. This test forces the error at the syscall boundary
    instead, so "a store read raised" is a FACT of the run rather than a property of the machine,
    and it fails everywhere the regression exists.

    Escaping here is a launch-blocker, not a cosmetic crash: a failed sync gate escalates to a
    `claude --dangerously-skip-permissions` repair session under the no-dead-ends policy, so one
    bad chmod on the store would drive the whole fleet into repair sessions.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    store.mkdir()
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env=_eacces_store_env(tmp_path, store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    # Degraded, and LOUDLY: publishing failed, and the heal path's read of `current` -- the one that
    # used to escape as an uncaught PermissionError -- reported itself instead of raising. The
    # sync lifecycle note stays on stdout; the degrade warnings are diagnostics and ride stderr.
    assert "methodology_snapshot: failed" in result.stdout
    assert "methodology_snapshot: store unreadable" in result.stderr
    assert "using canonical checkout" in result.stderr
    # ...and the launch still adopted the new code, from the canonical checkout.
    assert SENTINEL in result.stdout
    assert REEXEC_ACCEPTED in result.stdout
    assert _git(clone, "rev-parse", "HEAD") == new_head


def test_unreadable_store_never_blocks_snapshot_status(tmp_path, store):
    """`snapshot-status` is what an operator runs BECAUSE the store looks broken. It has to survive
    a broken store and report it -- every listing helper it calls (current, snapshots, pins) reads
    the store, and each one used to be able to traceback on the way to saying so."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    store.mkdir()

    result = _run_cli(
        clone / "bin" / "tautline",
        "snapshot-status",
        cwd=lane,
        env=_eacces_store_env(tmp_path, store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert "methodology_snapshot: store unreadable" in result.stderr
    assert "snapshot_store_current: none" in result.stdout
    assert "snapshot_store_count: 0" in result.stdout


def test_unreadable_store_warning_goes_to_stderr_not_the_status_report(tmp_path, store):
    """`snapshot-status` stdout is its machine-readable key:value report. The degrade warning is
    an operator diagnostic, so it must ride stderr -- a warning line in the middle of the report
    is exactly what a script parsing `snapshot_store_count:` would choke on."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    store.mkdir()

    result = _run_cli(
        clone / "bin" / "tautline",
        "snapshot-status",
        cwd=lane,
        env=_eacces_store_env(tmp_path, store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_snapshot: store unreadable" in result.stderr
    assert "methodology_snapshot: store unreadable" not in result.stdout
    for line in result.stdout.splitlines():
        if line.strip():
            assert ": " in line, f"non key:value line in the status report: {line!r}"


def test_bootstrap_heal_rebuilds_current(tmp_path, store):
    """A dangling `current` with no advance in sight must heal, or the store is dead weight."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    head = _git(clone, "rev-parse", "HEAD")
    store.mkdir()
    os.symlink("deadbeefdead", store / "current")
    assert (store / "current").is_symlink() and not (store / "current").exists()

    result = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_update: ok" in result.stdout, "no advance happened this run"
    assert f"methodology_snapshot: healed current - materialized {head[:12]}" in result.stdout
    current = (store / "current").resolve()
    assert current == (store / head[:12]).resolve()
    manifest = json.loads((current / ".snapshot-meta.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == head
    assert Path(manifest["canonicalRepo"]) == clone.resolve()


def test_materialize_failure_from_snapshot_reexecs_canonical(tmp_path, store):
    """THE trap: a stale snapshot can never accept a token bound to the new head.

    Running from snapshot(OLD) with a store that cannot publish snapshot(NEW), re-execing
    Path(__file__) would hand the OLD snapshot a token bound to the NEW head;
    consume_methodology_reexec_token() compares it against the manifest commit, rejects it, and the
    launch dies with "invalid or expired". The canonical checkout is at the new head, clean, and
    trust-verified: exec that instead.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    bootstrap = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    snapshot_cli = (store / "current").resolve() / "bin" / "tautline"
    assert snapshot_cli.is_file()
    new_head = _advance_remote_with_sentinel(source)
    store.chmod(0o555)  # readable and executable, but nothing new can be published into it

    result = _run_cli(snapshot_cli, "sync-methodology", "--no-remote", cwd=lane, env=_env(store))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_snapshot: failed" in result.stdout
    assert (
        f"methodology_snapshot: falling back to canonical checkout {clone.resolve()}"
        in result.stdout
    )
    assert "invalid or expired" not in result.stdout, "the re-exec'd process rejected its own token"
    assert REEXEC_ACCEPTED in result.stdout
    assert SENTINEL in result.stdout, "the canonical checkout at the new head is what re-executed"
    assert f"methodology_exec_root: {clone.resolve()} (canonical checkout)" in result.stdout
    assert _git(clone, "rev-parse", "HEAD") == new_head


# --- Task B7: the launcher gate ------------------------------------------------------------
# Every lane start syncs. Ungated, N simultaneous launches all fetch, all advance, and all race to
# publish the same snapshot; the gate makes the first lane do the work and the rest observe it.


def _home(lane: Path) -> Path:
    return lane / ".test-home"  # _run_cli pins HOME here, so the state dir is hermetic per fixture


def _state_path(lane: Path, name: str) -> Path:
    return _home(lane).joinpath(*STATE_DIR, name)


def _lock_path(lane: Path) -> Path:
    return _state_path(lane, "methodology-sync.lock")


def _stamp_path(lane: Path) -> Path:
    return _state_path(lane, "methodology-sync.stamp")


def _write_stamp(lane: Path, head: str, snapshot: str, age_seconds: float = 30.0) -> Path:
    """Forge a stamp as if a sibling lane had synced `age_seconds` ago."""
    path = _stamp_path(lane)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": STAMP_SCHEMA,
                "syncedAt": "2026-07-13T00:00:00Z",
                "head": head,
                "snapshot": snapshot,
                "status": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stamped = time.time() - age_seconds
    os.utime(path, (stamped, stamped))
    return path


def _bootstrap_store(clone: Path, lane: Path, store: Path) -> str:
    """One plain sync: publishes a snapshot of HEAD and points `current` at it."""
    result = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=lane, env=_env(store)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    head = _git(clone, "rev-parse", "HEAD")
    assert (store / "current").resolve() == (store / head[:12]).resolve()
    return head


def _reported(stdout: str, prefix: str) -> str:
    """The value the CLI printed after `prefix` (short shas vary in length; never hardcode one)."""
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _lock_is_held(lane: Path) -> bool:
    """Can a SIBLING process take the gate right now? (LOCK_NB: never block the test.)"""
    with _lock_path(lane).open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False


def test_launcher_gate_skips_when_stamp_fresh(tmp_path, store):
    """A fresh stamp naming the live snapshot means a sibling lane already did this work."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    head = _bootstrap_store(clone, lane, store)
    # Any fetch from here on fails loudly: the skip is only real if the sync never reaches git.
    shutil.rmtree(tmp_path / "sync-remote.git")
    _write_stamp(lane, head, head[:12])

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # The age is reported as whole seconds off the stamp's mtime, so pinning the exact
    # second makes this a race with subprocess startup: the stamp is forged 30s old, and
    # any spawn slower than a second reports 31s. Assert the shape, then bound the age --
    # that still proves the CLI read OUR stamp rather than syncing afresh.
    skipped = re.search(
        r"methodology_update: skipped - synced (\d+)s ago by another lane", result.stdout
    )
    assert skipped, result.stdout
    assert 30 <= int(skipped.group(1)) < 60, result.stdout
    assert "methodology_update: failed" not in result.stdout, "a fetch was attempted"
    # A skip still reports where the lane stands (git's short sha, from the canonical checkout).
    for line in ("methodology_commit: ", "methodology_canonical_commit: "):
        reported = _reported(result.stdout, line)
        assert reported and head.startswith(reported), f"{line}{reported} is not {head}"


def test_launcher_gate_serializes_two_syncs(tmp_path, store):
    """The gate is a real mutex: a second lane WAITS rather than racing into the same checkout."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    head = _bootstrap_store(clone, lane, store)
    shutil.rmtree(tmp_path / "sync-remote.git")
    _write_stamp(lane, head, head[:12])
    lock_path = _lock_path(lane)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        process = subprocess.Popen(
            [
                sys.executable,
                str(clone / "bin" / "tautline"),
                "sync-methodology",
                "--launcher-gate",
                "--no-remote",
            ],
            cwd=lane,
            env={**os.environ, "HOME": str(_home(lane)), **_env(store)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline:
                assert process.poll() is None, "the gated sync ran while another lane held the gate"
                time.sleep(0.1)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)

    stdout, stderr = process.communicate(timeout=90)
    assert process.returncode == 0, stdout + stderr
    assert "methodology_update: skipped - synced" in stdout, "it ran once the gate was free"


def test_stamp_not_written_on_failed_sync(tmp_path, store):
    """A failed sync must not tell the next lane the methodology is fresh."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    shutil.rmtree(tmp_path / "sync-remote.git")  # the fetch cannot succeed

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "methodology_update: failed" in result.stdout
    assert not _stamp_path(lane).exists(), "a failed sync stamped the methodology as fresh"


def test_launcher_gate_bootstraps_missing_state_dir(tmp_path, store):
    """Fresh HOME: ~/.local/state/minervit does not exist yet, and the gate must create it.

    Opening the lock (or the stamp) under a directory that is not there raises FileNotFoundError
    and takes the whole launch down -- on precisely the first run of every new machine.
    """
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    state_dir = _home(lane).joinpath(*STATE_DIR)
    assert not state_dir.exists(), "the fixture HOME must start without a state dir"

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert _lock_path(lane).is_file()
    assert _stamp_path(lane).is_file()


def test_fresh_stamp_with_dangling_current_still_syncs(tmp_path, store):
    """A fresh stamp over a BROKEN store must not skip: that starves the heal for a whole window.

    The stamp says "a sibling synced 30s ago", but `current` no longer resolves -- every session
    launched in the remaining freshness window would silently fall back to the canonical checkout.
    """
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    head = _bootstrap_store(clone, lane, store)
    snapshot = (store / "current").resolve()
    _unlock(snapshot)
    shutil.rmtree(snapshot)  # `current` now dangles
    assert (store / "current").is_symlink() and not (store / "current").exists()
    _write_stamp(lane, head, head[:12])

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_update: skipped - synced" not in result.stdout
    assert f"methodology_snapshot: healed current - materialized {head[:12]}" in result.stdout
    assert (store / "current").resolve() == (store / head[:12]).resolve()


def test_fresh_stamp_recording_a_stale_store_still_syncs(tmp_path, store):
    """A fresh stamp whose head is NOT the snapshot it names must not skip: the publish failed.

    The stamp is truthful -- a sibling synced the checkout to `head`, but the store could not
    publish, so `current` still names (and runs) the OLD commit. Honoring that stamp starves the
    heal republish retry for a whole freshness window, and every launch inside it quietly pins
    outdated code.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    old_head = _bootstrap_store(clone, lane, store)
    _advance_remote(source, "advance.txt", "new head after a failed publish")
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "reset", "-q", "--hard", "origin/main")
    new_head = _git(clone, "rev-parse", "HEAD")
    assert new_head != old_head
    assert (store / "current").resolve() == (store / old_head[:12]).resolve()
    _write_stamp(lane, new_head, old_head[:12])  # head != snapshot: the publish never landed

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_update: skipped - synced" not in result.stdout
    # A runnable-but-stale current takes heal's staleness-reconciliation path ("republished"),
    # not the broken-current path ("healed"): the store ends up on the new head either way.
    republished = f"methodology_snapshot: republished current - materialized {new_head[:12]}"
    assert republished in result.stdout, result.stdout
    assert (store / "current").resolve() == (store / new_head[:12]).resolve()


def test_launcher_gate_lock_survives_reexec(tmp_path, store):
    """THE trap: os.execve must not drop the gate's flock.

    CPython opens descriptors close-on-exec, so a gate holding a plain file handle releases its
    lock the instant a trust-gated advance re-execs -- the successor then does its checkout surgery
    with the gate WIDE OPEN, and a lane launching at that moment walks straight in. The re-exec'd
    CLI parks in the probe so we can prove, from a sibling process, that the lock is still held
    while it runs; that it later finishes at all proves it ADOPTED the inherited fd instead of
    blocking forever on the lock it was itself holding.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    _advance_remote_with_sentinel(source, extra=GATE_PROBE)
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "wait").touch()

    process = subprocess.Popen(
        [
            sys.executable,
            str(clone / "bin" / "tautline"),
            "sync-methodology",
            "--launcher-gate",
            "--no-remote",
        ],
        cwd=lane,
        env={
            **os.environ,
            "HOME": str(_home(lane)),
            **_env(store),
            "TAUTLINE_TEST_GATE_PROBE": str(probe),
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 60
        while not (probe / "reexec-started").is_file():
            assert process.poll() is None, "the CLI exited before the re-exec'd process started"
            assert time.time() < deadline, "the re-exec'd process never started"
            time.sleep(0.05)
        inherited_fd = (probe / "reexec-started").read_text(encoding="utf-8")
        assert inherited_fd.isdigit(), f"the successor inherited no lock fd: {inherited_fd!r}"
        assert _lock_is_held(lane), "os.execve released the gate's flock"
    finally:
        (probe / "go").touch()

    stdout, stderr = process.communicate(timeout=90)
    assert process.returncode == 0, stdout + stderr
    assert SENTINEL in stdout, "the re-exec'd process is the one that held the lock"
    assert not _lock_is_held(lane), "the gate never released the lock"


def test_stamp_written_before_reexec(tmp_path, store):
    """The successor must never start stampless, or every waiting lane redoes this fetch."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    new_head = _advance_remote_with_sentinel(source, extra=GATE_PROBE)
    probe = tmp_path / "probe"
    probe.mkdir()

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store, TAUTLINE_TEST_GATE_PROBE=str(probe)),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert SENTINEL in result.stdout
    observed = (probe / "stamp-at-reexec").read_text(encoding="utf-8")
    assert observed != "missing", "the re-exec'd process started without a freshness stamp"
    stamp = json.loads(observed)
    assert stamp["head"] == new_head, "the pre-exec stamp must name the head being adopted"
    assert stamp["snapshot"] == new_head[:12], "and the snapshot the successor will execute"


def test_reexec_token_never_takes_the_fresh_stamp_skip(tmp_path, store):
    """A re-exec'd process carries a stamp its own predecessor wrote SECONDS ago.

    If the freshness skip applied to it, it would consume its re-exec token and then skip the whole
    post-sync body -- no release guards, no heal, no pin refresh, no version reporting -- which is
    the entire reason the re-exec exists. The token is a veto on the skip.
    """
    source, clone, lane = _make_methodology_fixture(tmp_path)
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert SENTINEL in result.stdout
    assert "methodology_update: skipped - synced" not in result.stdout, "the successor skipped"
    assert REEXEC_ACCEPTED in result.stdout, "the successor must consume its token"
    assert "methodology_release_guard:" in result.stdout, "the post-sync body must run"
    assert f"methodology_commit: {new_head[:12]}" in result.stdout


def test_launcher_gate_refreshes_lane_pin(tmp_path, store):
    """A relaunching lane keeps its pin alive: fresh mtime, and the snapshot it now executes."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    head = _bootstrap_store(clone, lane, store)
    pinned = _run_cli(
        clone / "bin" / "tautline",
        "snapshot-pin",
        "--target",
        str(lane),
        cwd=lane,
        env=_env(store),
    )
    assert pinned.returncode == 0, pinned.stdout + pinned.stderr
    pins = sorted((store / "pins").glob("*.pin"))
    assert len(pins) == 1
    pin = pins[0]
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == head[:12]
    stale = time.time() - 36 * 3600  # older than nothing yet, but demonstrably not refreshed
    os.utime(pin, (stale, stale))
    new_head = _advance_remote_with_sentinel(source)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=lane,
        env=_env(store),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert SENTINEL in result.stdout
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == new_head[:12]
    assert time.time() - pin.stat().st_mtime < 300, "the pin's heartbeat was not refreshed"
