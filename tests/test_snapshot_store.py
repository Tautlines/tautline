"""The immutable snapshot store (Track B, task B5).

A snapshot is a `git archive` export of one trust-verified commit, published into
`<store>/<short12-sha>/` behind an atomically-swapped `current` symlink. Three properties carry
the whole design and each has a test here:

1. **Immutable.** A published snapshot is 0444/0555 files and 0555 directories. Lanes execute it
   concurrently; a stray write path that mutated the tree under a running lane would be a
   cross-lane corruption, so the filesystem -- not code review -- is what forbids it.
2. **Atomically published.** A snapshot appears complete or not at all. Materialization stages
   into `<store>/.tmp/` and publishes with a single `os.rename`; every failure path leaves the
   store byte-identical to how it started, with no partial snapshot and no staging residue.
3. **Safely pruned.** Retention never deletes what something is using: the `current` target, a
   freshly-pinned snapshot, a recently-current one, or the newest `keep`.

Property 2 has a trap that this file pins deliberately (`test_publish_collision_...`): once
`_make_snapshot_read_only` has run, `shutil.rmtree` CANNOT delete the staging tree (unlinking a
child needs write permission on its 0555 parent), and with `ignore_errors=True` it fails
*silently*. Every cleanup path that can run after that point must therefore use `_rmtree_force`.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"

# Both alias spellings of every managed key the store resolves. The operator's live shell exports
# some of these (the launcher sources the installed config env), and resolve_env PREFERS the
# TAUTLINE_ alias -- so a test that cleared only the MINERVIT_ spelling would silently resolve the
# store against the operator's machine instead of the fixture.
MANAGED_ENV_NAMES = (
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
    "MINERVIT_METHODOLOGY_SNAPSHOT_KEEP",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_KEEP",
    "MINERVIT_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    # The session exec root the launcher exports. A developer running pytest INSIDE a Tautline
    # session inherits a real one, and the pin resolves it -- so leaving it set would let the
    # operator's own machine leak into a store test.
    "MINERVIT_METHODOLOGY_EXEC_ROOT",
    "TAUTLINE_METHODOLOGY_EXEC_ROOT",
)

GIT_IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@invalid")


def _raise_oserror(*_args, **_kwargs):
    raise OSError("injected failure")


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    """A fresh CLI module per test, hermetic HOME, no managed env inherited.

    Function-scoped ON PURPOSE (conftest's session-scoped `cli` cannot be used here): the module
    bakes HOME-derived constants at import time and caches the resolved canonical repo in a module
    global. SourceFileLoader is REQUIRED because bin/tautline has no .py extension.
    """
    for name in MANAGED_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    loader = importlib.machinery.SourceFileLoader("tautline_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader("tautline_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module._CANONICAL_METHODOLOGY_REPO = None
    module._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    return module


@pytest.fixture()
def fixture_repo(tmp_path):
    """A minimal but REAL git checkout: materialization runs `git archive` against it."""
    repo = tmp_path / "fixture-repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "bin" / "tautline").write_text("#!/bin/sh\necho fixture\n", encoding="utf-8")
    (repo / "bin" / "tautline").chmod(0o755)
    (repo / "VERSION").write_text("0.0.1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), *GIT_IDENTITY, "commit", "-q", "-m", "fixture"], check=True
    )
    return repo


@pytest.fixture()
def store(cli, tmp_path, monkeypatch):
    """The store root, resolved the way the CLI resolves it (tmp_path is unresolved on darwin)."""
    monkeypatch.setenv("MINERVIT_METHODOLOGY_SNAPSHOT_STORE", str(tmp_path / "store"))
    return cli.methodology_snapshot_store_root()


def _commit(repo: Path, version: str) -> None:
    (repo / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), *GIT_IDENTITY, "commit", "-aqm", f"bump {version}"], check=True
    )


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def materialized_pair(cli, fixture_repo, store):
    first, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    _commit(fixture_repo, "0.0.2")
    second, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    return first, second, store


@pytest.fixture()
def five_snapshots(cli, fixture_repo, store):
    """Five snapshots, oldest -> newest, with FORCED-distinct mtimes.

    Retention orders by (materializedAt, mtime, name). materializedAt is second-granularity, so
    five snapshots cut inside one second would tie and fall through to mtime -- which is real but
    sub-second, and a test that depended on it would be a timing flake. Stamping mtimes explicitly
    makes the ordering the assertions rely on deterministic without weakening the ordering rule
    itself. (os.utime needs ownership, not write permission, so it works on the 0555 tree.)
    """
    snaps = []
    base = time.time() - 10_000
    for index in range(5):
        _commit(fixture_repo, f"0.0.{index + 10}")
        dest, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
        assert dest is not None
        os.utime(dest, (base + index, base + index))
        snaps.append(dest)
    return store, snaps


# --- materialize -------------------------------------------------------------------------------


def test_materialize_creates_manifest_and_is_idempotent(cli, fixture_repo, store):
    dest, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    assert dest is not None, detail
    head = _head(fixture_repo)
    assert dest == store / head[:12]

    manifest = json.loads((dest / cli.SNAPSHOT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema"] == cli.SNAPSHOT_MANIFEST_SCHEMA
    assert manifest["commit"] == head
    assert manifest["version"] == "0.0.1"
    assert manifest["channel"] == "stable"
    assert manifest["canonicalRepo"] == str(fixture_repo.resolve())
    assert (dest / "bin" / "tautline").is_file()
    assert (dest / "VERSION").is_file()

    again, detail2 = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    assert again == dest
    assert "reused" in detail2


def test_materialize_snapshot_is_a_valid_exec_root(cli, fixture_repo, store):
    """The manifest the store WRITES must be one snapshot_manifest() ACCEPTS -- a snapshot whose
    own reader rejects it would report `unavailable` for its running commit."""
    dest, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    monkey = cli
    monkey.REPO_ROOT = dest  # what a process executing the snapshot would see
    assert cli.snapshot_manifest() is not None
    assert cli.running_from_snapshot() is True
    assert cli.running_methodology_commit() == _head(fixture_repo)
    assert cli.running_methodology_commit(short=True) == _head(fixture_repo)[:12]


def test_snapshot_tree_is_read_only(cli, fixture_repo, store):
    dest, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    assert dest is not None

    with pytest.raises(OSError):
        (dest / "VERSION").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(OSError):
        (dest / "planted-file").write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        (dest / "bin" / "planted-file").write_text("x", encoding="utf-8")

    assert stat.S_IMODE(dest.stat().st_mode) == 0o555
    assert stat.S_IMODE((dest / "bin").stat().st_mode) == 0o555
    assert stat.S_IMODE((dest / "VERSION").stat().st_mode) == 0o444
    assert stat.S_IMODE((dest / cli.SNAPSHOT_MANIFEST_NAME).stat().st_mode) == 0o444
    # ...and the CLI inside it must still be executable, or the snapshot cannot be run.
    assert stat.S_IMODE((dest / "bin" / "tautline").stat().st_mode) == 0o555
    assert os.access(dest / "bin" / "tautline", os.X_OK)


def test_materialize_failure_leaves_no_partial_snapshot(cli, fixture_repo, store, monkeypatch):
    monkeypatch.setattr(cli.tarfile, "open", _raise_oserror)
    dest, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    assert dest is None
    assert "extraction failed" in detail
    assert _published_snapshots(store) == []
    assert _staging_residue(store) == []


def test_publish_collision_cleans_up_read_only_staging(cli, fixture_repo, store):
    """The regression the implementation review demanded.

    A non-snapshot directory squatting on the destination makes `os.rename(staging, dest)` fail
    with ENOTEMPTY -- the one cleanup path that runs AFTER `_make_snapshot_read_only`. With
    `shutil.rmtree(staging, ignore_errors=True)` there (the original sketch) the 0555 staging tree
    survives, silently, and every retry leaks another one. Cleanup must use `_rmtree_force`.
    """
    head = _head(fixture_repo)
    squatter = store / head[:12]
    squatter.mkdir(parents=True)
    (squatter / "junk").write_text("not a snapshot\n", encoding="utf-8")

    dest, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")

    assert dest is None
    assert "could not publish" in detail
    assert _staging_residue(store) == [], "read-only staging tree leaked into .tmp/"
    assert (squatter / "junk").read_text(encoding="utf-8") == "not a snapshot\n"


def test_materialize_recovers_from_leaked_staging_tree(cli, fixture_repo, store):
    """A crash between read-only and publish leaves a 0555 staging tree behind. The next run
    reuses that staging NAME (same sha, and pids are recycled), so the pre-flight cleanup faces a
    read-only tree too -- plain rmtree there would wedge materialization permanently."""
    head = _head(fixture_repo)
    leaked = store / ".tmp" / f"mat-{head[:12]}-{os.getpid()}"
    (leaked / "bin").mkdir(parents=True)
    (leaked / "bin" / "tautline").write_text("stale\n", encoding="utf-8")
    cli._make_snapshot_read_only(leaked)
    leaked.chmod(0o555)

    dest, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")

    assert dest is not None, detail
    assert (dest / "bin" / "tautline").read_text(encoding="utf-8") == "#!/bin/sh\necho fixture\n"
    assert _staging_residue(store) == []


def test_materialize_reports_unresolvable_commit(cli, fixture_repo, store):
    dest, detail = cli.materialize_methodology_snapshot(fixture_repo, "deadbeef" * 5, "stable")
    assert dest is None
    assert "could not resolve" in detail
    assert _published_snapshots(store) == []


def _published_snapshots(store: Path) -> list[str]:
    if not store.is_dir():
        return []
    return sorted(p.name for p in store.iterdir() if re.fullmatch(r"[0-9a-f]{12}", p.name))


def _staging_residue(store: Path) -> list[str]:
    tmp = store / ".tmp"
    if not tmp.is_dir():
        return []
    return sorted(p.name for p in tmp.iterdir() if p.name.startswith("mat-"))


# --- safe extraction ---------------------------------------------------------------------------


def _tar_with_member(tar_path: Path, payload: Path, name: str, *, symlink_to: str | None = None) -> None:
    with tarfile.open(tar_path, "w") as archive:
        if symlink_to is not None:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = symlink_to
            archive.addfile(info)
        else:
            archive.add(payload, arcname=name)


def test_safe_extract_rejects_link_members(cli, tmp_path):
    """The py3.10/3.11 fallback cannot contain link targets the way 3.12's `data` filter does, and
    a link escaping the staging tree would let the chmod pass follow it out of the store. The
    release tree ships no links (verified: `git ls-files -s` has no 120000 entries), so reject."""
    tar_path = tmp_path / "linky.tar"
    _tar_with_member(tar_path, tmp_path, "bin/tautline", symlink_to="../../../etc/passwd")
    with pytest.raises(tarfile.TarError, match="link"):
        cli._safe_extract_methodology_tar(tar_path, tmp_path / "staging")


def test_safe_extract_rejects_escaping_members(cli, tmp_path):
    payload = tmp_path / "payload"
    payload.write_text("x", encoding="utf-8")
    tar_path = tmp_path / "escapey.tar"
    _tar_with_member(tar_path, payload, "../escaped")
    with pytest.raises(tarfile.TarError, match="unsafe"):
        cli._safe_extract_methodology_tar(tar_path, tmp_path / "staging")


# --- swap --------------------------------------------------------------------------------------


def test_swap_is_atomic_and_repoints(cli, materialized_pair):
    first, second, store = materialized_pair
    ok, detail = cli.swap_methodology_snapshot_current(first)
    assert ok, detail
    assert (store / "current").resolve() == first

    ok, detail = cli.swap_methodology_snapshot_current(second)
    assert ok, detail
    assert (store / "current").resolve() == second
    assert first.exists(), "the superseded snapshot must survive the swap (lanes still run it)"
    assert not [p for p in store.iterdir() if p.name.startswith(".current-tmp-")]


def test_swap_records_history(cli, materialized_pair):
    first, second, store = materialized_pair
    cli.swap_methodology_snapshot_current(first)
    cli.swap_methodology_snapshot_current(second)
    entries = [
        json.loads(line)
        for line in (store / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["snapshot"] for entry in entries] == [first.name, second.name]


# --- prune -------------------------------------------------------------------------------------


def test_prune_protects_current_pins_and_newest_keep(cli, five_snapshots, tmp_path):
    store, snaps = five_snapshots  # oldest -> newest
    cli.swap_methodology_snapshot_current(snaps[2])
    cli.write_methodology_snapshot_pin(tmp_path / "lane-x", snaps[0])

    pruned = cli.prune_methodology_snapshots(keep=1)

    assert snaps[4].exists(), "newest keep=1 must survive"
    assert snaps[2].exists(), "the current target must survive"
    assert snaps[0].exists(), "a fresh pin must survive"
    assert not snaps[1].exists()
    assert not snaps[3].exists()
    assert sorted(pruned) == sorted([snaps[1].name, snaps[3].name])


def test_prune_protects_recent_current_history(cli, five_snapshots):
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[1])
    cli.swap_methodology_snapshot_current(snaps[4])

    cli.prune_methodology_snapshots(keep=1)

    # snaps[1] is no longer current, but a session that started while it WAS current is still
    # executing it; the TTL window on the swap history is what keeps it alive.
    assert snaps[1].exists()
    assert snaps[4].exists()


def test_stale_pins_age_out(cli, five_snapshots, tmp_path):
    store, snaps = five_snapshots
    pin = cli.write_methodology_snapshot_pin(tmp_path / "lane-y", snaps[0])
    old = time.time() - 73 * 3600
    os.utime(pin, (old, old))

    cli.prune_methodology_snapshots(keep=1)

    assert not pin.exists(), "a pin past the 72h TTL is garbage, not protection"
    assert not snaps[0].exists()


def test_prune_defaults_to_keeping_three(cli, five_snapshots):
    store, snaps = five_snapshots
    pruned = cli.prune_methodology_snapshots()
    assert sorted(pruned) == sorted([snaps[0].name, snaps[1].name])
    assert all(snap.exists() for snap in snaps[2:])


def test_prune_leaves_store_metadata_alone(cli, five_snapshots, tmp_path):
    store, snaps = five_snapshots
    cli.write_methodology_snapshot_pin(tmp_path / "lane-z", snaps[4])
    cli.swap_methodology_snapshot_current(snaps[4])
    cli.prune_methodology_snapshots(keep=1)
    assert (store / "current").is_symlink()
    assert (store / "pins").is_dir()
    assert (store / "history.jsonl").is_file()
    assert _staging_residue(store) == []


def test_prune_on_missing_store_is_a_noop(cli, store):
    assert cli.prune_methodology_snapshots(keep=1) == []


# --- verbs -------------------------------------------------------------------------------------


def test_snapshot_verbs_are_registered_and_classified(cli):
    registered = set(cli.registered_subcommand_names())
    assert {"snapshot-status", "snapshot-prune", "snapshot-pin"} <= registered
    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    blocked = set(cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS)
    # snapshot-pin is invoked by the launcher during startup; snapshot-status is a read-only
    # diagnostic. snapshot-prune deletes trees and has no startup role.
    assert {"snapshot-pin", "snapshot-status"} <= allowed
    assert "snapshot-prune" in blocked
    assert not ({"snapshot-pin", "snapshot-status"} & blocked)
    assert "snapshot-prune" not in allowed


def test_snapshot_status_reports_store_current_and_pins(cli, five_snapshots, tmp_path, capsys):
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[4])
    cli.write_methodology_snapshot_pin(tmp_path / "lane-a", snaps[0])

    assert cli.snapshot_status(argparse.Namespace()) == 0

    out = capsys.readouterr().out
    assert f"snapshot_store_root: {store}" in out
    assert "snapshot_store_enabled: true" in out
    assert f"snapshot_store_current: {snaps[4].name}" in out
    assert f"snapshot: {snaps[0].name}" in out
    assert "version=0.0.10" in out
    assert f"snapshot_pin: {cli.instrumentation_lane_id(tmp_path / 'lane-a')} -> {snaps[0].name}" in out


def test_snapshot_status_on_disabled_store_exits_zero(cli, capsys):
    assert cli.snapshot_status(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "snapshot_store_enabled: false" in out
    assert "snapshot_store_current: none" in out


# --- heal reports the outcome it actually got --------------------------------------------------
#
# heal_methodology_snapshot_current() IS the recovery mechanism for a store whose `current` is
# missing or dangling. If it announces success when the swap failed, the one signal an operator has
# that the store is still broken is a line saying it was fixed -- a silent failure in the exact
# machinery that exists to make failures loud.


def _heal_fixture(cli, fixture_repo, monkeypatch) -> str:
    """Point heal at the fixture checkout and hand back its HEAD.

    REPO_ROOT, not the canonical-repo env key: _resolve_canonical_methodology_repo() gives the exec
    root precedence whenever it is itself a git checkout, and under pytest the exec root is this
    repository -- so a configured key alone would heal against the developer's own checkout.
    """
    monkeypatch.setattr(cli, "REPO_ROOT", fixture_repo)
    cli._CANONICAL_METHODOLOGY_REPO = None
    cli._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    assert cli.canonical_methodology_repo() == fixture_repo
    return subprocess.run(
        ["git", "-C", str(fixture_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_heal_reports_healed_when_the_swap_lands(cli, fixture_repo, store, monkeypatch, capsys):
    head = _heal_fixture(cli, fixture_repo, monkeypatch)

    cli.heal_methodology_snapshot_current()

    out = capsys.readouterr().out
    assert f"methodology_snapshot: healed current - materialized {head[:12]}" in out, out
    assert "heal failed" not in out, out
    assert cli.methodology_snapshot_current_dir() == (store / head[:12]).resolve()


def test_heal_reports_failure_when_the_swap_does_not_land(
    cli, fixture_repo, store, monkeypatch, capsys
):
    """A `current` that is still missing must never be reported as healed."""
    _heal_fixture(cli, fixture_repo, monkeypatch)
    monkeypatch.setattr(
        cli, "swap_methodology_snapshot_current", lambda _dir: (False, "swap failed: injected")
    )
    pruned: list[object] = []
    monkeypatch.setattr(cli, "prune_methodology_snapshots", lambda *a, **k: pruned.append(a))

    cli.heal_methodology_snapshot_current()

    out = capsys.readouterr().out
    assert "healed current" not in out, out
    assert "methodology_snapshot: heal failed" in out, out
    assert "swap failed: injected" in out, out
    # `current` is still broken, so nothing may be collected on the strength of a swap that
    # never happened -- prune protects the CURRENT target, and there isn't one.
    assert pruned == [], "prune must not run after a failed swap"
    assert cli.methodology_snapshot_current_dir() is None


# --- heal reconciles a STALE current, not just a missing one -----------------------------------
#
# `current` going stale is not an edge case, it is the steady state of every failure this design
# has: a publish that failed mid-advance, an operator taking the rollback lever in ONE shell (the
# docs bless "one command, one shell") so that lane fast-forwards the canonical checkout while
# publishing nothing, or a manual git advance of the canonical checkout. In every one of those the
# canonical checkout moves and `current` does not.
#
# What makes it permanent -- and this is the whole bug -- is that nothing downstream re-opens the
# question. The next lane's sync finds the checkout "Already up to date", so no advance fires and
# _reexec_updated_methodology (the ONLY other publisher) is never re-entered; heal used to return
# the moment `current` merely EXISTED. So the store froze one head behind and every unlevered
# session on the machine kept executing the stale snapshot indefinitely -- with sync reporting ok.
# Heal is the one code path that runs on every no-advance sync, so it is where freshness has to be
# re-established.


def test_heal_republishes_a_stale_current(cli, fixture_repo, store, monkeypatch, capsys):
    """The canonical checkout advanced but `current` still names the old snapshot."""
    old_head = _heal_fixture(cli, fixture_repo, monkeypatch)
    cli.heal_methodology_snapshot_current()
    assert cli.methodology_snapshot_current_dir() == (store / old_head[:12]).resolve()
    capsys.readouterr()

    # The canonical checkout moves on WITHOUT anything publishing a snapshot for it -- exactly what
    # a levered lane's advance, or a failed publish, leaves behind.
    _commit(fixture_repo, "0.0.2")
    new_head = _head(fixture_repo)
    assert new_head != old_head

    cli.heal_methodology_snapshot_current()

    out = capsys.readouterr().out
    # The next lane to start must execute the new head, not the frozen one.
    assert cli.methodology_snapshot_current_dir() == (store / new_head[:12]).resolve(), out
    assert new_head[:12] in out, out


def test_heal_leaves_a_current_that_already_matches_canonical_head_alone(
    cli, fixture_repo, store, monkeypatch, capsys
):
    """Reconciling must be a no-op when nothing moved: no republish, no swap, no prune churn.

    Heal runs on EVERY no-advance sync, so a version that re-materialized each time would rewrite
    the store (and re-run prune) on every lane start of every session on the machine.
    """
    head = _heal_fixture(cli, fixture_repo, monkeypatch)
    cli.heal_methodology_snapshot_current()
    capsys.readouterr()

    materialized: list[object] = []
    monkeypatch.setattr(
        cli,
        "materialize_methodology_snapshot",
        lambda *a, **k: materialized.append(a) or (None, "must not be called"),
    )
    pruned: list[object] = []
    monkeypatch.setattr(cli, "prune_methodology_snapshots", lambda *a, **k: pruned.append(a))

    cli.heal_methodology_snapshot_current()

    assert materialized == [], "a current already at canonical HEAD must not be republished"
    assert pruned == []
    assert capsys.readouterr().out == ""
    assert cli.methodology_snapshot_current_dir() == (store / head[:12]).resolve()


# --- health means EXECUTABLE, not merely manifest-consistent -----------------------------------
#
# Every consumer of the store asks the same question of `current`, and none of them ask it of the
# manifest: the shim tests `[ -x "$SNAPSHOT_CURRENT/bin/tautline" ]`, the launcher tests
# `[ -x "$SNAPSHOT_STORE/current/bin/tautline" ]`, and launcher_gate_skip_reason refuses to skip a
# sync when os.access(current/bin/tautline, X_OK) is false -- specifically so that heal gets a
# chance to rebuild it.
#
# Heal used to judge `current` healthy on a manifest-commit match alone. So a `current` whose
# .snapshot-meta.json was intact but whose bin/tautline had been deleted (an interrupted delete, a
# half-run cleanup script, a backup tool, an operator's rm) was pronounced healthy and never
# repaired -- while every shim that tried to exec it fell through to the canonical checkout, for
# good. The gate declined to skip, handed control to heal, and heal said "already the canonical
# head" and did nothing.


def _gut_snapshot(snapshot: Path) -> None:
    """Delete a published snapshot's CLI, leaving its manifest intact.

    The published tree is 0555 all the way down, so unlinking a child needs its parent unsealed
    first -- exactly what the accidents that produce this state (rm -rf interrupted, a restore that
    skipped a mode bit) do on their way through.
    """
    snapshot.chmod(0o755)
    (snapshot / "bin").chmod(0o755)
    (snapshot / "bin" / "tautline").unlink()


def test_heal_rebuilds_a_current_whose_cli_is_gone(cli, fixture_repo, store, monkeypatch, capsys):
    head = _heal_fixture(cli, fixture_repo, monkeypatch)
    cli.heal_methodology_snapshot_current()
    current = cli.methodology_snapshot_current_dir()
    assert current == (store / head[:12]).resolve()
    _gut_snapshot(current)
    assert (current / cli.SNAPSHOT_MANIFEST_NAME).is_file(), "the manifest must survive the gutting"
    capsys.readouterr()

    cli.heal_methodology_snapshot_current()

    healed = cli.methodology_snapshot_current_dir()
    assert healed is not None
    cli_path = healed / "bin" / "tautline"
    assert cli_path.is_file(), capsys.readouterr().out
    assert os.access(cli_path, os.X_OK), "a `current` the shim cannot exec is not healed"


def test_materialize_does_not_reuse_a_gutted_snapshot(cli, fixture_repo, store):
    """The manifest is the store's index, not its contents. A dir that still carries a matching
    manifest but has lost its CLI is not a snapshot to reuse -- it is the trap heal must clear."""
    dest, _ = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")
    assert dest is not None
    _gut_snapshot(dest)

    again, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")

    assert again == dest, detail
    assert os.access(again / "bin" / "tautline", os.X_OK), detail
    assert "reused" not in detail, f"a gutted snapshot must be republished, not reused: {detail}"
    assert _staging_residue(store) == []


# --- a failed `git archive` must not leak its tar ----------------------------------------------
#
# The archive tar is staged inside the store's own .tmp/. prune only ever walks manifest-bearing
# snapshot dirs, pins and history -- it never looks in .tmp -- so anything orphaned there is
# orphaned for good. Disk-full is the realistic trigger, which is precisely when leaking a
# multi-megabyte tar per attempt is least affordable.


def test_failed_git_archive_leaves_no_tar_behind(cli, fixture_repo, store, monkeypatch):
    real_run_command = cli.run_command

    def fail_archive(cmd, *args, **kwargs):
        if "archive" in cmd:
            # git archive -o creates its output file before it writes, then fails partway.
            for arg in cmd:
                if str(arg).endswith(".tar"):
                    Path(arg).write_bytes(b"partial")
            return 1, "", "fatal: write error: No space left on device"
        return real_run_command(cmd, *args, **kwargs)

    monkeypatch.setattr(cli, "run_command", fail_archive)

    snapshot_dir, detail = cli.materialize_methodology_snapshot(fixture_repo, "HEAD", "stable")

    assert snapshot_dir is None
    assert "git archive failed" in detail
    leaked = list((store / ".tmp").glob("*.tar"))
    assert leaked == [], f"failed archive leaked {leaked}"


def test_snapshot_prune_verb_prunes_and_reports(cli, five_snapshots, capsys):
    store, snaps = five_snapshots
    assert cli.snapshot_prune(argparse.Namespace(keep=1)) == 0
    out = capsys.readouterr().out
    assert "snapshot_pruned:" in out
    assert snaps[4].exists()
    assert not snaps[0].exists()


def test_snapshot_pin_verb_pins_current_for_the_lane(cli, five_snapshots, tmp_path, capsys):
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[3])
    lane = tmp_path / "lane-b"
    lane.mkdir()

    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0

    out = capsys.readouterr().out
    pin = store / "pins" / f"{cli.instrumentation_lane_id(lane)}.pin"
    assert pin.is_file()
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == snaps[3].name
    assert f"snapshot_pin: {pin}" in out
    assert f"snapshot_pin_target: {snaps[3].name}" in out


def test_snapshot_pin_without_current_exits_zero_with_a_note(cli, store, tmp_path, capsys):
    """A launcher calls this on EVERY start. A store that is disabled, empty, or mid-bootstrap
    must degrade to a note -- never a non-zero exit that fails the operator's session start."""
    assert cli.snapshot_pin(argparse.Namespace(target=tmp_path)) == 0
    out = capsys.readouterr().out
    assert "snapshot_pin: skipped" in out


# --- the pin must name the snapshot the SESSION is executing, not whatever `current` says now ---
#
# Session-stickiness is the entire point of the store: a session resolves ONE exec root (the
# launcher does it with `pwd -P` and exports it; the shim re-execs into it) and runs that tree for
# its whole life. `current` is not that -- it is a symlink another lane may swap at any instant.
#
# Pinning `current` therefore pins whatever the store happens to point at in the microseconds
# between this session resolving its exec root and calling `snapshot-pin`. Lose that race and the
# lane declares "I am running X" while it is running Y -- so prune, which honours pins, is free to
# collect Y: the exact tree the session is executing, and the exact deletion the pin exists to
# prevent. The window is not theoretical; the launcher runs sync (which publishes and swaps) for
# every lane on the machine, and the pin call sits a few shell lines after the exec-root resolve.


def _age_history(store: Path, seconds: float) -> None:
    """Push every swap-history entry past prune's TTL window.

    Prune protects a recently-current snapshot independently of any pin, so a long-lived session is
    only ever protected by its PIN once that window has closed. Aging the history is what exposes
    the pin as the sole protection -- which is the state the pin was built for.
    """
    history = store / "history.jsonl"
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    lines = []
    for line in history.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        entry["ts"] = stamp
        lines.append(json.dumps(entry))
    history.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_snapshot_pin_pins_the_snapshot_the_session_is_executing(
    cli, five_snapshots, tmp_path, monkeypatch, capsys
):
    """The race, run explicitly: resolve an exec root, let another lane swap `current`, then pin."""
    store, snaps = five_snapshots
    session_snapshot = snaps[3]
    cli.swap_methodology_snapshot_current(session_snapshot)
    # This process IS the snapshot: the launcher resolved `current` once and re-exec'd into it, so
    # the running tree -- not the symlink -- is what this session executes.
    monkeypatch.setattr(cli, "REPO_ROOT", session_snapshot)

    # ...and now another lane's sync advances the store, mid-session.
    cli.swap_methodology_snapshot_current(snaps[4])

    lane = tmp_path / "lane-race"
    lane.mkdir()
    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0

    pin = store / "pins" / f"{cli.instrumentation_lane_id(lane)}.pin"
    pinned = json.loads(pin.read_text(encoding="utf-8"))["snapshot"]
    assert pinned == session_snapshot.name, (
        f"pinned {pinned}, but this session executes {session_snapshot.name}"
    )
    assert f"snapshot_pin_target: {session_snapshot.name}" in capsys.readouterr().out


def test_pinning_current_would_let_prune_delete_the_running_snapshot(
    cli, five_snapshots, tmp_path, monkeypatch
):
    """The consequence the pin exists to prevent, asserted end to end."""
    store, snaps = five_snapshots
    session_snapshot = snaps[1]
    cli.swap_methodology_snapshot_current(session_snapshot)
    monkeypatch.setattr(cli, "REPO_ROOT", session_snapshot)
    cli.swap_methodology_snapshot_current(snaps[4])

    lane = tmp_path / "lane-long"
    lane.mkdir()
    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0
    # The session outlives the window in which a once-current snapshot is protected for free. From
    # here on the pin is the ONLY thing standing between prune and the running code.
    _age_history(store, 80 * 3600)

    cli.prune_methodology_snapshots(keep=1)

    assert session_snapshot.exists(), "prune collected the snapshot this session is executing"


def test_snapshot_pin_honours_an_exported_session_exec_root(
    cli, five_snapshots, tmp_path, monkeypatch
):
    """A launcher with MINERVIT_METHODOLOGY_CLI preset runs a CLI that is NOT the snapshot, while
    its hooks all exec the exported root. The exported root is the session's truth; use it."""
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[4])
    monkeypatch.setenv("MINERVIT_METHODOLOGY_EXEC_ROOT", str(snaps[2]))

    lane = tmp_path / "lane-exported"
    lane.mkdir()
    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0

    pin = store / "pins" / f"{cli.instrumentation_lane_id(lane)}.pin"
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == snaps[2].name


def test_snapshot_pin_ignores_an_exec_root_that_is_not_a_snapshot_of_this_store(
    cli, five_snapshots, tmp_path, monkeypatch
):
    """A pruned, foreign, or stale exec root names nothing this store can protect. Pinning it would
    write a pin that guards no snapshot at all -- worse than falling back to `current`."""
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[4])
    foreign = tmp_path / "somewhere-else"
    foreign.mkdir()
    monkeypatch.setenv("MINERVIT_METHODOLOGY_EXEC_ROOT", str(foreign))

    lane = tmp_path / "lane-foreign"
    lane.mkdir()
    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0

    pin = store / "pins" / f"{cli.instrumentation_lane_id(lane)}.pin"
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == snaps[4].name


def test_refresh_re_stamps_the_session_snapshot_not_current(
    cli, five_snapshots, tmp_path, monkeypatch
):
    """The pin heartbeat has the same duty as the pin: a long-lived lane whose relaunch re-stamps
    the pin at `current` would hand its own protection to a snapshot it is not running."""
    store, snaps = five_snapshots
    session_snapshot = snaps[1]
    cli.swap_methodology_snapshot_current(session_snapshot)
    monkeypatch.setattr(cli, "REPO_ROOT", session_snapshot)
    lane = tmp_path / "lane-heartbeat"
    lane.mkdir()
    assert cli.snapshot_pin(argparse.Namespace(target=lane)) == 0

    cli.swap_methodology_snapshot_current(snaps[4])
    cli.refresh_methodology_snapshot_pin(lane)

    pin = store / "pins" / f"{cli.instrumentation_lane_id(lane)}.pin"
    assert json.loads(pin.read_text(encoding="utf-8"))["snapshot"] == session_snapshot.name

    _age_history(store, 80 * 3600)
    cli.prune_methodology_snapshots(keep=1)
    assert session_snapshot.exists()


def test_snapshot_status_runs_end_to_end(cli, five_snapshots, tmp_path):
    """Proves the verb is really wired into the parser, not just callable as a function."""
    store, snaps = five_snapshots
    cli.swap_methodology_snapshot_current(snaps[4])
    home = tmp_path / "home"
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "snapshot-status"],
        env={"PATH": os.environ["PATH"], "HOME": str(home),
             "MINERVIT_METHODOLOGY_SNAPSHOT_STORE": str(store)},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert f"snapshot_store_current: {snaps[4].name}" in result.stdout
