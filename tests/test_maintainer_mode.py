"""Maintainer mode: key residency, arming predicate, update standdown, reporting, the
launcher shell interlocks, and the `maintainer-mode` verb (T1-T5).

The mode key lives ONLY in the installed config env file, read via user_config_env_value on
resolve_user_config_env() -- deliberately NOT through _managed_config_value and NOT from the
live environment. File-only residency is the split's load-bearing decision: the archived
monolith resolved the key live-env-first, so `maintainer-mode off` could strip the config file
yet leave an inherited live-env key armed (the unresolved MM-R4-P1-1). With the file as the
single source of truth, no other state can arm the machine.

The mode ARMS only when the key is set AND the checkout sync manages --
canonical_methodology_repo() -- is itself a git checkout. Keying on the canonical repo rather
than the bare exec root is load-bearing: with snapshot exec ON, the launcher-gate sync executes
from an immutable snapshot where _exec_root_is_git_checkout() is False, so an exec-root-only
predicate would never arm inside exactly the sessions the mode exists for.

When armed, update_methodology_repo returns ("skipped", ...) before any branch check, fetch,
rescue, or ff-merge -- ONE choke point, so every caller (launcher-gate sync, manual sync,
lane-target sync) stands down. The non-failed status keeps heal republishing canonical HEAD
into <store>/current and keeps the freshness stamp flowing; the armed launcher-gate path never
TAKES the stamp skip (it exists to avoid the expensive network sync, and the armed body is
offline and cheap -- skipping would bypass heal, MS-R1-P1-1).
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_install_uninstall import (
    STORE_REL,
    _git_out,
    _init_launcher_methodology_repo,
    _install_plain_launcher,
    _rescue_repo_state,
    _write_fake_launcher_bin,
)
from test_sync_methodology_cli import _advance_remote, _git, _make_methodology_fixture, _run_cli

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"
# Post the package-split flip (roadmap #11): the engine lives in the package; bin/tautline is a
# thin shim. Load the engine module (cli.py) for the in-process fixture; CLI_PATH stays the source
# of the real CLI bytes for the copied-CLI export-root filesystem fixtures.
CLI_ENGINE_PATH = CLI_PATH.parents[1] / "src" / "tautline_methodology" / "cli.py"

# Both alias spellings of the mode key, plus every managed key the arming predicate resolves.
# The operator's live shell exports several managed keys (the launcher sources the installed
# config env), so a test that did not clear them would assert against the operator's machine
# instead of the fixture -- and a live maintainer-mode export must be cleared for the
# off-by-default test to mean anything on the maintainer's own machine.
MAINTAINER_MODE_ENV_NAMES = (
    "TAUTLINE_METHODOLOGY_MAINTAINER_MODE",
    "MINERVIT_METHODOLOGY_MAINTAINER_MODE",
)
MANAGED_ENV_NAMES = (
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
)


def _cli_module_for_home(monkeypatch, home: Path):
    """A fresh CLI module anchored on `home`, with no inherited managed env.

    The module bakes HOME-derived constants (USER_CONFIG_ENV, LEGACY_USER_CONFIG_ENV) at
    import time and caches the resolved canonical repo in a module global, so both must be
    established per load. SourceFileLoader gives a fresh engine module (cli.py) per call.
    """
    for name in MAINTAINER_MODE_ENV_NAMES + MANAGED_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    loader = importlib.machinery.SourceFileLoader("tautline_cli", str(CLI_ENGINE_PATH))
    spec = importlib.util.spec_from_loader("tautline_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module._CANONICAL_METHODOLOGY_REPO = None
    module._CANONICAL_METHODOLOGY_REPO_ANCHOR = None
    return module


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    """A fresh CLI module per test with a hermetic HOME and no inherited managed env.

    Function-scoped ON PURPOSE (conftest's session-scoped `cli` cannot be used here): see
    _cli_module_for_home. The T5 shell/Python-agreement tests load additional modules anchored
    on their launcher launch HOMEs via the helper directly.
    """
    return _cli_module_for_home(monkeypatch, tmp_path / "home")


def _git_checkout(root: Path) -> Path:
    """A git fixture checkout that passes _valid_methodology_repo (.git + bin/<cli>)."""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bin" / "tautline").chmod(0o755)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def _export_root(cli, root: Path, snapshot: bool = False) -> Path:
    """A git-archive-style export: the copied CLI outside any repo (no .git anywhere).

    The copied-CLI-outside-repo shape from tests/test_release_tracks_and_migrations.py --
    bin/tautline is the real CLI's bytes, but there is no git checkout: a snapshot or a
    pip/package install exec root. With `snapshot` the tree also carries a snapshot manifest.
    """
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text(CLI_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "bin" / "tautline").chmod(0o755)
    if snapshot:
        (root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
            json.dumps({"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": "a" * 40}),
            encoding="utf-8",
        )
    return root


def _write_config_env(cli, lines: list[str]) -> Path:
    config_env = cli.USER_CONFIG_ENV
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_env


# --- Task T1: file-only mode key + arming predicate --------------------------------------------


def test_maintainer_mode_off_by_default(cli):
    # No key anywhere: not configured, not armed -- even though REPO_ROOT (the dev checkout
    # we run the tests from) is a git checkout the predicate would otherwise accept.
    assert cli.maintainer_mode_config_value() == ""
    assert cli.maintainer_mode_configured() is False
    assert cli.maintainer_mode_armed() is False


@pytest.mark.parametrize("name", MAINTAINER_MODE_ENV_NAMES)
def test_live_env_key_never_configures_the_mode(cli, monkeypatch, name):
    """THE split's load-bearing semantics: live env can never arm the machine.

    MM-R4-P1-1 (an `off` that cannot unset an inherited live-env key) is impossible by
    construction only if the live environment is inert here. REPO_ROOT is a real git checkout
    in this test, so armed() being False proves the CONFIGURED gate, not the checkout gate.
    """
    monkeypatch.setenv(name, "1")
    assert cli.maintainer_mode_config_value() == ""
    assert cli.maintainer_mode_configured() is False
    assert cli.maintainer_mode_armed() is False


def test_config_env_file_key_configures(cli):
    # The key in the hermetic ~/.config/tautline/tautline.env configures the mode...
    config = _write_config_env(cli, ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"])
    assert cli.maintainer_mode_configured() is True

    # ...and when ONLY the legacy file exists and carries the key, the
    # resolve_user_config_env fallback still reads it.
    config.unlink()
    legacy = cli.LEGACY_USER_CONFIG_ENV
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1\n", encoding="utf-8")
    assert cli.resolve_user_config_env() == legacy
    assert cli.maintainer_mode_configured() is True


def test_tautline_spelling_wins_inside_the_file(cli):
    # The alias spelling is read first, mirroring _managed_config_value's file order.
    _write_config_env(
        cli,
        [
            "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=0",
            "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
        ],
    )
    assert cli.maintainer_mode_config_value() == "0"
    assert cli.maintainer_mode_configured() is False

    # A BLANK TAUTLINE_ export counts as unset: the MINERVIT_ spelling still configures.
    _write_config_env(
        cli,
        [
            "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=",
            "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
        ],
    )
    assert cli.maintainer_mode_config_value() == "1"
    assert cli.maintainer_mode_configured() is True


def test_blank_or_zero_value_counts_as_unset(cli):
    _write_config_env(cli, ['export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=""'])
    assert cli.maintainer_mode_configured() is False
    assert cli.maintainer_mode_armed() is False

    _write_config_env(cli, ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=0"])
    assert cli.maintainer_mode_configured() is False
    assert cli.maintainer_mode_armed() is False


@pytest.mark.parametrize(
    "config_lines",
    [
        pytest.param(['export TAUTLINE_METHODOLOGY_MAINTAINER_MODE="1"'], id="double-quoted"),
        pytest.param(["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE='1'"], id="single-quoted"),
        pytest.param(
            ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1 # armed by hand"],
            id="trailing-comment",
        ),
        pytest.param(["  export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"], id="leading-whitespace"),
        pytest.param(["TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"], id="no-export-keyword"),
        pytest.param(
            [
                'export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=""',
                "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
            ],
            id="quoted-blank-falls-through",
        ),
    ],
)
def test_hand_edited_shapes_configure_python_side(cli, config_lines):
    """The shlex reference parse accepts these hand-edit shapes: they CONFIGURE the mode.

    Agreement lock for MS-IMPL-R1-P2-1: the launcher shell guard must arm on the same shapes
    (test_launcher_auto_rescue_stands_down_when_file_armed carries the shell half), and the
    divergence is fixed shell-side -- user_config_env_value is the reference semantics and
    weakening it here is never the fix.
    """
    _write_config_env(cli, config_lines)
    assert cli.maintainer_mode_configured() is True


def test_nested_quoted_value_stays_literal_and_does_not_configure(cli):
    """`="'1'"` is the three-character string '1' WITH quotes: shlex keeps inner
    quotes literal, so the mode is NOT configured -- and the launcher shell guard
    agrees (its substitution strips exactly one layer of MATCHING quotes, never
    two), keeping both halves of the machine in the same armed state."""
    _write_config_env(cli, ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=\"'1'\""])
    assert cli.maintainer_mode_configured() is False


def test_armed_requires_canonical_git_checkout(cli, tmp_path, monkeypatch):
    # Configured, but the checkout sync manages has no .git: nothing to stand down for.
    _write_config_env(cli, ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"])
    exec_root = tmp_path / "gitless"
    exec_root.mkdir()
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)

    assert cli.maintainer_mode_configured() is True
    assert cli.canonical_methodology_repo() == exec_root  # the .git-less REPO_ROOT fallback
    assert cli.maintainer_mode_armed() is False


def test_refuses_to_arm_on_snapshot_or_package_exec_root_without_canonical(
    cli, tmp_path, monkeypatch
):
    # A copied-out CLI (git-archive-style export / package install) with NO managed
    # canonical-repo key: the canonical repo falls back to the .git-less REPO_ROOT, so the
    # mode must refuse to arm even with the key set in the file.
    _write_config_env(
        cli,
        [
            "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1",
            "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
        ],
    )
    export = _export_root(cli, tmp_path / "copied-cli")
    monkeypatch.setattr(cli, "REPO_ROOT", export)

    assert cli.maintainer_mode_configured() is True
    assert cli.canonical_methodology_repo() == export
    assert cli.maintainer_mode_armed() is False


def test_arms_from_snapshot_exec_root_when_canonical_is_git_checkout(cli, tmp_path, monkeypatch):
    """THIS is the launcher-session case the feature exists for.

    With snapshot exec ON, the launcher-gate sync executes from an immutable snapshot (no
    .git), while the managed canonical-repo key names the real checkout sync manages. An
    exec-root-only predicate would never arm here.
    """
    canonical = _git_checkout(tmp_path / "canon")
    _write_config_env(
        cli,
        [
            "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1",
            f"export MINERVIT_METHODOLOGY_CANONICAL_REPO={canonical}",
        ],
    )
    monkeypatch.setattr(cli, "REPO_ROOT", _export_root(cli, tmp_path / "snap", snapshot=True))

    assert cli._exec_root_is_git_checkout() is False
    assert cli.canonical_methodology_repo() == canonical.resolve()
    assert cli.maintainer_mode_armed() is True


def test_arms_when_exec_root_is_git_checkout(cli, tmp_path, monkeypatch):
    # THE EXEC ROOT WINS when it is itself a checkout: the canonical-repo predicate subsumes
    # the exec-root case (pre-snapshot dev machines).
    _write_config_env(cli, ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"])
    checkout = _git_checkout(tmp_path / "dev")
    monkeypatch.setattr(cli, "REPO_ROOT", checkout)

    assert cli.canonical_methodology_repo() == checkout
    assert cli.maintainer_mode_armed() is True


# --- Task T2: update standdown at the single choke point ----------------------------------------
#
# End-to-end subprocess scenarios on the _make_methodology_fixture pattern: a fixture upstream, a
# canonical clone whose bin/tautline is the CLI under test, and a hermetic HOME carrying (or not
# carrying) the maintainer-mode key in the installed config env file -- exactly where the verb
# will write it. Live-environment spellings of every managed key are blanked so the operator's
# own machine can never leak into a fixture (resolve_env treats blank-once-stripped as unset).

# The full standdown detail is part of the contract: it names the disable verb so the mode is
# never a dead end, and the "skipped" status is what lets heal and the freshness stamp flow.
STANDDOWN_LINE = (
    "methodology_update: skipped - maintainer mode - update gates stand down; "
    "checkout left untouched (disable with `tautline maintainer-mode off`)"
)
# Printed only by launcher_gate_skip_reason's freshness-skip path -- the branch an ARMED
# launcher-gate sync must never take (MS-R1-P1-1: taking it bypasses heal).
FRESHNESS_SKIP_TOKEN = "by another lane"

SUBPROCESS_NEUTRAL_ENV_NAMES = (
    *MAINTAINER_MODE_ENV_NAMES,
    *MANAGED_ENV_NAMES,
    "MINERVIT_METHODOLOGY_SNAPSHOT_KEEP",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_KEEP",
    "MINERVIT_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_PIN_TTL_HOURS",
    "MINERVIT_METHODOLOGY_EXEC_ROOT",
    "TAUTLINE_METHODOLOGY_EXEC_ROOT",
    "MINERVIT_METHODOLOGY_UPDATE_POLICY",
    "TAUTLINE_METHODOLOGY_UPDATE_POLICY",
    "MINERVIT_METHODOLOGY_UPDATE_PINS",
    "TAUTLINE_METHODOLOGY_UPDATE_PINS",
    "MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "TAUTLINE_METHODOLOGY_SYNC_FRESHNESS_MINUTES",
    "MINERVIT_METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    "TAUTLINE_METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    "MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE",
    "TAUTLINE_METHODOLOGY_DISABLE_AUTO_RESCUE",
    "MINERVIT_METHODOLOGY_ALLOW_NON_MAIN",
    "TAUTLINE_METHODOLOGY_ALLOW_NON_MAIN",
    # The exec-handoff pair has no TAUTLINE_ alias BY DESIGN (tests/test_env_reads_use_resolver
    # .py): a stale one in the runner's shell must not reach the CLI under test.
    "MINERVIT_METHODOLOGY_SYNC_LOCK_FD",
    "MINERVIT_METHODOLOGY_SYNC_GATE",
)


def _maintainer_home(tmp_path: Path) -> Path:
    """One hermetic HOME per test, shared across every _run_cli cwd via an explicit override.

    _run_cli pins HOME to <cwd>/.test-home; tests here run the CLI from more than one cwd, and
    the config env file, the freshness stamp, and the state dir must all be the SAME machine.
    """
    home = tmp_path / "maintainer-home"
    home.mkdir(exist_ok=True)
    return home


def _sync_env(home: Path, **extra: str) -> dict[str, str]:
    env = {name: "" for name in SUBPROCESS_NEUTRAL_ENV_NAMES}
    env["HOME"] = str(home)
    env.update(extra)
    return env


def _arm_mode_in_config(home: Path) -> Path:
    """Both spellings, exactly as `maintainer-mode on` (T4) will write them."""
    config = home / ".config" / "tautline" / "tautline.env"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1\n"
        "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1\n",
        encoding="utf-8",
    )
    return config


def _commit_dev_work(clone: Path, name: str, message: str) -> str:
    (clone / name).write_text(f"{message}\n", encoding="utf-8")
    _git(clone, "add", name)
    _git(clone, "-c", "user.email=t@invalid", "-c", "user.name=t", "commit", "-q", "-m", message)
    return _git(clone, "rev-parse", "HEAD")


def _diverge_clean_dev_branch(source: Path, clone: Path) -> str:
    """The maintainer's steady state: a CLEAN dev branch diverged from origin/main (ahead 1,
    behind 1) -- the exact shape the launcher-gate sync fail-closes on today."""
    _git(clone, "switch", "-q", "-c", "maintainer/dev")
    head = _commit_dev_work(clone, "DEV-NOTE.md", "maintainer dev work")
    _advance_remote(source, "REMOTE-ADVANCE.md", "remote change the dev branch is behind on")
    return head


def _checkout_state(clone: Path) -> tuple[str, str, str]:
    return (
        _git(clone, "rev-parse", "HEAD"),
        _git(clone, "branch", "--show-current"),
        _git(clone, "status", "--porcelain"),
    )


def _stamp_path(home: Path) -> Path:
    return home / ".local" / "state" / "minervit" / "methodology-sync.stamp"


@pytest.fixture()
def sync_store(tmp_path):
    """A snapshot store root; published snapshots are 0555 dirs / 0444 files, so hand tmp_path
    back something removable (the test_snapshot_exec_integration teardown shape)."""
    root = tmp_path / "store"
    yield root
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


def test_standdown_passes_the_clean_diverged_dev_branch(tmp_path):
    """The exact today-fails scenario: armed, the launcher-gate sync passes and touches nothing."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)
    before = _checkout_state(clone)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert STANDDOWN_LINE in result.stdout
    assert "methodology_update: failed" not in result.stdout
    assert _checkout_state(clone) == before, "the armed standdown must leave the checkout untouched"


def test_standdown_never_fetches_or_advances(tmp_path):
    """With origin pointing at a void, an armed sync passes -- proof the UPDATE choke point does
    no fetch and no ff-merge. (The per-launch remote-status probe still runs at this task's
    boundary: it degrades to an `unavailable: ...` line without failing the sync. The
    no-ls-remote-at-launch guarantee is T3's, not T2's.)"""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing-remote.git"))
    home = _maintainer_home(tmp_path)

    off = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert off.returncode == 1, off.stdout + off.stderr
    assert "methodology_update: failed" in off.stdout

    _arm_mode_in_config(home)
    before = _checkout_state(clone)
    armed = _run_cli(clone / "bin" / "tautline", "sync-methodology", cwd=clone, env=_sync_env(home))

    assert armed.returncode == 0, armed.stdout + armed.stderr
    assert STANDDOWN_LINE in armed.stdout
    assert any(line.startswith("remote_status: ") for line in armed.stdout.splitlines())
    assert _checkout_state(clone) == before


def test_standdown_still_heals_current(tmp_path, sync_store):
    """Committed maintainer work reaches the next launch: a stale `current` is republished at
    canonical HEAD by the armed sync (the "skipped" status is non-failed, so heal still runs)."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    env = _sync_env(home, MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(sync_store))

    bootstrap = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=clone, env=env
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    old_head = _git(clone, "rev-parse", "HEAD")
    assert (sync_store / "current").resolve() == (sync_store / old_head[:12]).resolve()

    # The canonical checkout advances (committed dev-branch work); `current` is now stale.
    _git(clone, "switch", "-q", "-c", "maintainer/dev")
    new_head = _commit_dev_work(clone, "DEV-NOTE.md", "committed maintainer work")
    _arm_mode_in_config(home)

    armed = _run_cli(
        clone / "bin" / "tautline", "sync-methodology", "--no-remote", cwd=clone, env=env
    )

    assert armed.returncode == 0, armed.stdout + armed.stderr
    assert STANDDOWN_LINE in armed.stdout
    assert (sync_store / "current").resolve() == (
        sync_store / new_head[:12]
    ).resolve(), armed.stdout


def test_standdown_writes_the_freshness_stamp_but_never_skips(tmp_path):
    """The stamp is WRITTEN when armed (off-mode stamp semantics preserved for a later `off`),
    but the armed launcher-gate path never TAKES the freshness skip: the skip is a network-cost
    optimization, the armed body is offline, and skipping would bypass heal (MS-R1-P1-1)."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)

    first = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert STANDDOWN_LINE in first.stdout
    stamp = json.loads(_stamp_path(home).read_text(encoding="utf-8"))
    assert stamp["status"] == "skipped", "the armed sync must stamp its non-failed status"

    second = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert STANDDOWN_LINE in second.stdout, "the armed relaunch must run the standdown body again"
    assert FRESHNESS_SKIP_TOKEN not in second.stdout, (
        "the armed launcher-gate sync took the freshness stamp-skip branch"
    )


def test_standdown_covers_lane_target_syncs(tmp_path):
    """One choke point covers every caller: a lane-target sync (the project-startup shape whose
    auto-rescue would otherwise switch a clean non-main checkout to main) stands down too."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)
    before = _checkout_state(clone)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        "--no-remote",
        cwd=lane,
        # pinned update trust: the stable-channel framework gate must ALLOW the update so the
        # sync reaches update_methodology_repo -- where the armed standdown answers.
        env=_sync_env(home, MINERVIT_METHODOLOGY_UPDATE_POLICY="pinned"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert STANDDOWN_LINE in result.stdout
    assert _checkout_state(clone) == before


def test_mode_off_clean_diverged_branch_still_fails_closed(tmp_path):
    """The regression lock on the flagship scenario: without the key, the clean diverged dev
    branch fails exactly as today -- fail-closed, no freshness stamp, checkout untouched."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)  # no key anywhere
    before = _checkout_state(clone)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "methodology_update: failed - methodology checkout is on maintainer/dev, not main"
        in result.stdout
    )
    assert "refusing to sync from a non-release branch" in result.stdout
    assert not _stamp_path(home).exists(), "a failed sync must never stamp the methodology fresh"
    assert _checkout_state(clone) == before


def test_standdown_skips_dirty_checkout_without_rescue(tmp_path):
    """Armed, a dirty checkout is left exactly as it stands: no rescue branch, no reset -- the
    standdown answers before the dirty check that would otherwise trigger project-startup rescue."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    _advance_remote(source, "REMOTE-DIRTY.md", "remote change while the checkout is dirty")
    with (clone / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("# local methodology edit\n")
    (clone / "UNTRACKED-NOTE.md").write_text("untracked maintainer note\n", encoding="utf-8")
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)
    before = _checkout_state(clone)
    assert before[2] != "", "the fixture checkout must be dirty"

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=lane,  # project-startup shape: default auto-rescue would fire here with the mode off
        env=_sync_env(home),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert STANDDOWN_LINE in result.stdout
    assert "rescued" not in result.stdout
    assert _checkout_state(clone) == before, "the dirty checkout must be left exactly as it stands"
    assert (
        _git(clone, "branch", "--format=%(refname:short)", "--list", "minervit-local-rescue/*")
        == ""
    ), "no rescue branch may be created while the mode is armed"


def test_commit_inside_freshness_window_reaches_next_launch(tmp_path, sync_store):
    """The exact scenario MS-R1-P1-1 named: a commit landed INSIDE the freshness window must be
    in <store>/current at the very next launch -- the armed gate never takes the stamp skip, so
    heal runs on every armed launch."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)
    env = _sync_env(home, MINERVIT_METHODOLOGY_SNAPSHOT_STORE=str(sync_store))
    _git(clone, "switch", "-q", "-c", "maintainer/dev")

    first = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=env,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert STANDDOWN_LINE in first.stdout
    head1 = _git(clone, "rev-parse", "HEAD")
    assert (sync_store / "current").resolve() == (sync_store / head1[:12]).resolve()
    assert _stamp_path(home).exists(), "the armed launcher-gate sync must still write the stamp"

    # New maintainer work, committed and relaunched immediately -- well inside the window.
    head2 = _commit_dev_work(clone, "DEV-NOTE.md", "committed inside the freshness window")
    assert head2 != head1

    second = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=env,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert FRESHNESS_SKIP_TOKEN not in second.stdout, (
        "the armed launcher-gate sync took the freshness stamp-skip branch"
    )
    assert (sync_store / "current").resolve() == (sync_store / head2[:12]).resolve(), (
        "committed maintainer work must reach the very next launch"
    )


# --- Task T3: loud banner and status reporting ---------------------------------------------------
#
# The mode is never ambient: EVERY armed launch prints a loud banner (stderr, the
# warn_unpinned_launcher_window precedent for advisory banners) whose load-bearing line names the
# checkout and commit the machine is actually running -- because with update gates off, committed
# dev-branch work IS the machine-wide runtime via heal. The launch-time remote probe stands down
# too (a launch must not depend on the network while updates are off), and methodology-status
# carries a three-state maintainer_mode line so diagnosis works even during startup remediation.

# The literal remote_status value when armed: deterministic, offline, no ls-remote at launch.
REMOTE_STANDDOWN_LINE = "remote_status: skipped - maintainer mode"
# The three-state status line's configured-but-not-armed diagnostic (exact plan wording).
NOT_ARMED_LINE = "maintainer_mode: configured but not armed - no git checkout to manage"


def _banner_line(checkout: Path) -> str:
    """The banner's load-bearing `<checkout> @ <commit>` contract line.

    The 12-char slice matches running_methodology_commit(short=True) -- never `rev-parse
    --short`, whose length is repo-state-dependent.
    """
    return (
        "maintainer_mode: update gates off - running "
        f"{checkout.resolve()} @ {_git(checkout, 'rev-parse', 'HEAD')[:12]}"
    )


def _gitless_export(clone: Path, dest: Path) -> Path:
    """A full-tree copy of the fixture checkout WITHOUT .git: the snapshot/package exec-root
    shape where there is no git checkout for the mode to manage (configured-but-not-armed)."""
    shutil.copytree(clone, dest, ignore=shutil.ignore_patterns(".git"))
    return dest


def test_banner_prints_on_gated_sync(tmp_path):
    """The armed launcher-gate sync leads with the banner naming checkout @ commit."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _banner_line(clone) in result.stderr.splitlines(), result.stderr
    assert STANDDOWN_LINE in result.stdout


def test_banner_prints_on_every_armed_launch(tmp_path):
    """A relaunch INSIDE the freshness window still shows the banner: the mode is never ambient
    (the armed path never takes the stamp-skip branch, so the banner cannot be skipped away)."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)

    first = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert _banner_line(clone) in first.stderr.splitlines()
    assert _stamp_path(home).exists(), "the first armed gated sync must have stamped"

    second = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert _banner_line(clone) in second.stderr.splitlines(), (
        "the banner must print on EVERY armed launch, including inside the freshness window"
    )


def test_no_banner_when_mode_off(tmp_path):
    """Byte-identical off-mode surface: no `maintainer_mode` token anywhere in stock sync output,
    plain or launcher-gated (including the gated relaunch that takes the stock freshness skip)."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)  # no key anywhere

    plain = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert plain.returncode == 0, plain.stdout + plain.stderr
    assert "maintainer_mode" not in plain.stdout + plain.stderr

    gated = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home),
    )
    assert gated.returncode == 0, gated.stdout + gated.stderr
    assert "maintainer_mode" not in gated.stdout + gated.stderr


def test_remote_probe_stands_down_when_armed(tmp_path):
    """No ls-remote at launch: with origin pointing at a void and NO --no-remote, the armed
    launcher-gate sync (the exact shape the generated launcher runs) passes and reports the
    literal standdown line instead of probing the network."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing-remote.git"))
    home = _maintainer_home(tmp_path)
    _arm_mode_in_config(home)

    result = _run_cli(
        clone / "bin" / "tautline",
        "sync-methodology",
        "--launcher-gate",
        cwd=clone,
        env=_sync_env(home),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert STANDDOWN_LINE in result.stdout
    remote_lines = [
        line for line in result.stdout.splitlines() if line.startswith("remote_status: ")
    ]
    assert remote_lines == [REMOTE_STANDDOWN_LINE], result.stdout
    # The probe against the dead origin would have degraded to `unavailable: ...` -- its absence
    # is what proves no probe ran.
    assert "unavailable:" not in result.stdout, result.stdout


def test_methodology_status_reports_maintainer_mode(tmp_path):
    """The three-state maintainer_mode line in the methodology-status report block."""
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)

    def status(root: Path) -> subprocess.CompletedProcess[str]:
        return _run_cli(
            root / "bin" / "tautline",
            "methodology-status",
            "--project",
            str(root / "adapters" / "projects" / "example-saas.json"),
            "--target",
            str(lane),
            "--no-remote",
            cwd=lane,
            env=_sync_env(home),
        )

    # Not configured: off.
    off = status(clone)
    assert off.returncode == 0, off.stdout + off.stderr
    assert "maintainer_mode: off" in off.stdout.splitlines(), off.stdout

    # Armed: on, naming the managed checkout and its commit (the same contract as the banner).
    _arm_mode_in_config(home)
    on = status(clone)
    assert on.returncode == 0, on.stdout + on.stderr
    head = _git(clone, "rev-parse", "HEAD")[:12]
    assert (
        f"maintainer_mode: on - update gates off; running {clone.resolve()} @ {head}"
        in on.stdout.splitlines()
    ), on.stdout

    # Configured but not armed: the key is set, but the exec root is a gitless export and no
    # canonical checkout is configured -- nothing to manage, and the line says so.
    export = _gitless_export(clone, tmp_path / "gitless-export")
    not_armed = status(export)
    assert not_armed.returncode == 0, not_armed.stdout + not_armed.stderr
    assert NOT_ARMED_LINE in not_armed.stdout.splitlines(), not_armed.stdout
    assert "maintainer_mode: on" not in not_armed.stdout


def test_banner_names_configured_not_armed_state(tmp_path):
    """Configured-but-not-armed sync prints the diagnostic line INSTEAD of the standdown banner
    and proceeds stock -- byte-identical stdout to the same machine without the key."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    export = _gitless_export(clone, tmp_path / "gitless-export")
    home = _maintainer_home(tmp_path)

    stock = _run_cli(
        export / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=export,
        env=_sync_env(home),
    )
    assert stock.returncode == 0, stock.stdout + stock.stderr

    _arm_mode_in_config(home)  # the key is set, but there is no git checkout to manage
    diagnosed = _run_cli(
        export / "bin" / "tautline",
        "sync-methodology",
        "--no-remote",
        cwd=export,
        env=_sync_env(home),
    )

    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    assert NOT_ARMED_LINE in diagnosed.stderr.splitlines(), diagnosed.stderr
    assert "update gates off" not in diagnosed.stdout + diagnosed.stderr, (
        "the standdown banner must not print when the mode cannot arm"
    )
    assert STANDDOWN_LINE not in diagnosed.stdout
    assert diagnosed.stdout == stock.stdout, "the configured-but-not-armed sync must proceed stock"


# --- Task T5: launcher shell hardening -- shell/Python agreement and snapshot-exec lock ----------
#
# The generated launcher's auto-rescue guard parses the maintainer-mode key out of the installed
# config env file -- the SAME direct simple exports user_config_env_value reads -- so the shell
# and Python halves of one machine can never disagree about the armed state (MS-R1-P1-2). These
# two tests pin the agreement property and the snapshot-exec invariant that the launcher-install
# subprocess tests in test_install_uninstall.py cannot express, because they need the in-process
# predicates alongside the launcher run. No test invokes the `maintainer-mode` verb (T5 executes
# before T4): fixtures write the export line(s) into the hermetic config env file directly.

MAINTAINER_MODE_EXPORT_LINES = (
    "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1\n"
    "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1\n"
)


def test_maintainer_mode_key_leaves_snapshot_exec_enabled(cli, run_cli, tmp_path):
    """The mode key must not disable snapshot exec -- the store is what protects the operator's
    concurrent lanes while the maintainer edits the canonical checkout.

    Python half: methodology_snapshot_store_enabled() stays True with the store's managed key
    set and the maintainer-mode key written directly into the config env file. Shell half: the
    generated launcher still resolves $METHODOLOGY_CLI through <store>/current. (The companion
    guarantee that the VERB writes no snapshot keys is asserted in T4.1(a), the first task where
    the verb exists.)
    """
    home = tmp_path / "home"  # run_cli's hermetic HOME and the `cli` fixture's anchor
    launcher = _install_plain_launcher(run_cli, tmp_path)
    config = home / ".config" / "tautline" / "tautline.env"
    with config.open("a", encoding="utf-8") as fh:
        fh.write(MAINTAINER_MODE_EXPORT_LINES)

    assert cli.maintainer_mode_configured() is True
    assert cli.methodology_snapshot_store_enabled() is True, (
        "the maintainer-mode key must never turn snapshot exec off"
    )

    # The launcher's first CLI call runs THROUGH <store>/current: replace the published snapshot
    # CLI with a sentinel that names its own invocation path (the migration-test pattern; the
    # published file is 0444, hence the chmod), then launch with no MINERVIT_METHODOLOGY_CLI
    # preset so the store rung of the resolution ladder answers.
    store = home / STORE_REL
    current_cli = store / "current" / "bin" / "tautline"
    sentinel = current_cli.resolve()
    sentinel.chmod(0o755)
    sentinel.write_text(
        "#!/bin/sh\n"
        'printf "methodology_cli_sentinel: %s\\n" "$0"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    sentinel.chmod(0o755)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env={"HOME": str(home), "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    sentinel_lines = [
        line for line in run.stdout.splitlines() if line.startswith("methodology_cli_sentinel: ")
    ]
    assert sentinel_lines, run.stdout
    assert sentinel_lines[0] == f"methodology_cli_sentinel: {current_cli}", (
        "the armed launcher must still resolve $METHODOLOGY_CLI through <store>/current"
    )
    exec_roots = [
        line.split(":", 1)[1] for line in run.stdout.splitlines() if line.startswith("exec_root:")
    ]
    assert exec_roots == [str(sentinel.parent.parent)], run.stdout


def test_sourced_secrets_cannot_arm_or_disarm_the_shell_guard(run_cli, tmp_path, monkeypatch):
    """Shell and Python can never disagree about the armed state (MS-R1-P1-2).

    The config env file sources the user's private secrets file (the generated tautline.env
    precedent). The shell guard PARSES the config file's direct exports -- it never sees what
    sourcing executed -- and user_config_env_value reads the same direct simple exports, so a
    secrets-file export can neither arm (variant one) nor disarm (variant two) either side.
    """
    launcher = _install_plain_launcher(run_cli, tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    def _launch_home(name: str, secrets_value: str, direct_lines: list[str]) -> Path:
        launch_home = tmp_path / name
        secrets = launch_home / ".config" / "tautline" / "secrets.zsh"
        secrets.parent.mkdir(parents=True)
        secrets.write_text(
            f"export TAUTLINE_METHODOLOGY_MAINTAINER_MODE={secrets_value}\n", encoding="utf-8"
        )
        (launch_home / ".config" / "tautline" / "tautline.env").write_text(
            "\n".join(
                [
                    *direct_lines,
                    f"TAUTLINE_SECRETS_ENV={secrets}",
                    'if [ -f "$TAUTLINE_SECRETS_ENV" ]; then',
                    '  . "$TAUTLINE_SECRETS_ENV"',
                    "fi",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return launch_home

    def _launch(launch_home: Path, repo: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher)],
            cwd=tmp_path,
            env={
                "HOME": str(launch_home),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "MINERVIT_METHODOLOGY_REPO": str(repo),
            },
            text=True,
            capture_output=True,
            timeout=60,
        )

    # Variant one: the SECRETS file exports =1 while the config file carries NO direct
    # maintainer-mode export. The auto-rescue must NOT stand down (stock warn rescue advances
    # the diverged/dirty fixture), and Python agrees: not configured.
    home_one = _launch_home("launch-home-secrets-arm", "1", [])
    repo_one, _first_one, second_one = _init_launcher_methodology_repo(tmp_path / "one")
    run_one = _launch(home_one, repo_one)
    assert run_one.returncode == 0, run_one.stdout + run_one.stderr
    assert _git_out(repo_one, "rev-parse", "HEAD") == second_one, (
        "a sourced-secrets export must not arm the shell guard"
    )
    assert "launcher_auto_rescue - preserved local methodology checkout" in run_one.stdout
    module_one = _cli_module_for_home(monkeypatch, home_one)
    assert module_one.maintainer_mode_configured() is False, (
        "user_config_env_value reads direct simple exports only -- Python must agree"
    )

    # Variant two: the config file carries the direct export =1 while the sourced secrets file
    # exports =0. The auto-rescue STILL stands down (the guard parses the file; sourcing cannot
    # overwrite what it already read), and Python agrees: configured.
    home_two = _launch_home(
        "launch-home-secrets-disarm",
        "0",
        ["export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1"],
    )
    repo_two, first_two, _second_two = _init_launcher_methodology_repo(tmp_path / "two")
    before_two = _rescue_repo_state(repo_two)
    run_two = _launch(home_two, repo_two)
    assert run_two.returncode == 0, run_two.stdout + run_two.stderr
    assert _git_out(repo_two, "rev-parse", "HEAD") == first_two
    assert _rescue_repo_state(repo_two) == before_two, (
        "a sourced-secrets =0 must not disarm the file-armed shell guard"
    )
    assert "launcher_auto_rescue -" not in run_two.stdout + run_two.stderr
    module_two = _cli_module_for_home(monkeypatch, home_two)
    assert module_two.maintainer_mode_configured() is True


# --- Task T4: the `maintainer-mode` verb and its registry surfaces -------------------------------
#
# The verb is the ONLY supported writer of the mode key: `on` writes both alias spellings into the
# resolved config env file (and NOTHING else), `off` strips them from BOTH config surfaces so no
# latent copy can re-arm the machine later (MS-R1-P2-1), and `status` prints the same three-state
# line as methodology-status. `off` is authoritative BY CONSTRUCTION -- the files it strips are the
# only arming state -- and test (c) below is the regression lock for the archived monolith's
# unresolved MM-R4-P1-1 (an `off` that could not unset an inherited live-env key). The
# launcher-capability advisory is CONTENT-KEYED on the TAUTLINE_METHODOLOGY_MAINTAINER_MODE guard
# token that T5's template emits -- never stale_claude_launchers, which keys on the template marker
# and cannot see current-marker launchers that lack the guard.

MAINTAINER_MODE_EXPORT_SET = {
    "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1",
    "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
}
LAUNCHER_ADVISORY_NEXT_STEP = "next_step: tautline install-claude-launcher --force"


def _config_env_path(home: Path) -> Path:
    return home / ".config" / "tautline" / "tautline.env"


def _verb(clone: Path, home: Path, *args: str, **env_extra: str):
    return _run_cli(
        clone / "bin" / "tautline",
        "maintainer-mode",
        *args,
        cwd=clone,
        env=_sync_env(home, **env_extra),
    )


@pytest.fixture()
def unlock_home_store(tmp_path):
    """install-cli publishes 0555/0444 snapshot trees under the hermetic HOME's DEFAULT store
    root; unlock them on teardown so tmp_path stays removable (the sync_store shape)."""
    yield
    root = tmp_path / "maintainer-home" / ".local" / "share" / "minervit" / "tautline-releases"
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


def test_maintainer_mode_on_writes_both_spellings_and_nothing_else(tmp_path):
    """`on` writes exactly the two export lines -- created 0600 when the file is absent, mode and
    other exports preserved when present, idempotent, and NEVER a snapshot key (the verb-side
    half of T5's snapshot-exec guarantee, asserted here because the verb exists only from T4)."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    config = _config_env_path(home)
    assert not config.exists()

    result = _verb(clone, home, "on")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _banner_line(clone) in result.stdout.splitlines(), result.stdout
    assert any(line.startswith("next_step:") for line in result.stdout.splitlines()), result.stdout

    text = config.read_text(encoding="utf-8")
    assert {line for line in text.splitlines() if line.strip()} == MAINTAINER_MODE_EXPORT_SET, text
    assert "DISABLE_SNAPSHOT_EXEC" not in text, "the verb must never touch snapshot exec"
    assert "SNAPSHOT_STORE" not in text, "the verb must never write a snapshot-store key"
    assert (config.stat().st_mode & 0o777) == 0o600, "created 0600 when absent"

    again = _verb(clone, home, "on")
    assert again.returncode == 0, again.stdout + again.stderr
    assert config.read_text(encoding="utf-8") == text, "a second `on` must not duplicate lines"

    # An existing config file keeps its mode and its other exports.
    config.unlink()
    config.write_text("export KEEP_ME=1\n", encoding="utf-8")
    config.chmod(0o644)
    third = _verb(clone, home, "on")
    assert third.returncode == 0, third.stdout + third.stderr
    preserved = config.read_text(encoding="utf-8")
    assert "export KEEP_ME=1" in preserved.splitlines()
    assert MAINTAINER_MODE_EXPORT_SET <= set(preserved.splitlines())
    assert (config.stat().st_mode & 0o777) == 0o644, "mode preserved when present"


def test_maintainer_mode_off_removes_key_and_restores_stock_behavior(tmp_path):
    """The full round trip: on -> armed standdown -> off -> the T2(a) clean-diverged-branch
    launcher-gate sync fails closed again, exactly as stock."""
    source, clone, _lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    binary = clone / "bin" / "tautline"

    on = _verb(clone, home, "on")
    assert on.returncode == 0, on.stdout + on.stderr
    armed = _run_cli(
        binary, "sync-methodology", "--launcher-gate", "--no-remote", cwd=clone, env=_sync_env(home)
    )
    assert armed.returncode == 0, armed.stdout + armed.stderr
    assert STANDDOWN_LINE in armed.stdout

    off = _verb(clone, home, "off")
    assert off.returncode == 0, off.stdout + off.stderr
    assert "maintainer_mode: off" in off.stdout.splitlines(), off.stdout
    assert "MAINTAINER_MODE" not in _config_env_path(home).read_text(encoding="utf-8")

    # The armed gated sync above stamped the freshness window (deliberately -- T2(d) locks that
    # `off` inherits stock stamp semantics). Disable the window here so the post-off run models
    # the first launch after the stamp lapses: the STOCK gate body must fail closed again.
    after = _run_cli(
        binary,
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home, MINERVIT_METHODOLOGY_SYNC_FRESHNESS_MINUTES="0"),
    )
    assert after.returncode == 1, after.stdout + after.stderr
    assert (
        "methodology_update: failed - methodology checkout is on maintainer/dev, not main"
        in after.stdout
    )
    # The report-line token, not the bare word: fixture paths under pytest's tmp dir carry this
    # test module's own name, so a bare-token scan would match the printed checkout path.
    assert "maintainer_mode:" not in after.stdout + after.stderr


def test_maintainer_mode_off_is_authoritative_over_live_env(tmp_path, monkeypatch):
    """The archived monolith's MM-R4-P1-1 regression lock: after `off`, a live-environment key
    in the sync process cannot re-arm anything, and every status surface reports off -- there is
    no state in which `off` misreports, because the file it strips is the only arming state."""
    source, clone, lane = _make_methodology_fixture(tmp_path)
    _diverge_clean_dev_branch(source, clone)
    home = _maintainer_home(tmp_path)
    binary = clone / "bin" / "tautline"

    on = _verb(clone, home, "on")
    assert on.returncode == 0, on.stdout + on.stderr
    off = _verb(clone, home, "off")
    assert off.returncode == 0, off.stdout + off.stderr

    sync = _run_cli(
        binary,
        "sync-methodology",
        "--launcher-gate",
        "--no-remote",
        cwd=clone,
        env=_sync_env(home, TAUTLINE_METHODOLOGY_MAINTAINER_MODE="1"),
    )
    assert sync.returncode == 1, sync.stdout + sync.stderr
    assert (
        "methodology_update: failed - methodology checkout is on maintainer/dev, not main"
        in sync.stdout
    )
    # Report-line token, not the bare word (fixture paths carry this module's name).
    assert "maintainer_mode:" not in sync.stdout + sync.stderr

    module = _cli_module_for_home(monkeypatch, home)
    assert module.maintainer_mode_configured() is False

    status = _verb(clone, home, "status", TAUTLINE_METHODOLOGY_MAINTAINER_MODE="1")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "maintainer_mode: off" in status.stdout.splitlines(), status.stdout

    meth = _run_cli(
        binary,
        "methodology-status",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        "--no-remote",
        cwd=lane,
        env=_sync_env(home, TAUTLINE_METHODOLOGY_MAINTAINER_MODE="1"),
    )
    assert meth.returncode == 0, meth.stdout + meth.stderr
    assert "maintainer_mode: off" in meth.stdout.splitlines(), meth.stdout


def test_maintainer_mode_on_refuses_without_a_checkout_to_manage(tmp_path):
    """From a snapshot/package-style exec root with no canonical git checkout, `on` exits 1,
    names the reason, and writes NO key -- an armed key with nothing to stand down would be a
    lie on every status surface."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    export = _gitless_export(clone, tmp_path / "gitless-export")
    home = _maintainer_home(tmp_path)

    result = _run_cli(
        export / "bin" / "tautline", "maintainer-mode", "on", cwd=export, env=_sync_env(home)
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "nothing to stand down" in result.stderr, result.stderr
    config = _config_env_path(home)
    assert not config.exists() or "MAINTAINER_MODE" not in config.read_text(encoding="utf-8"), (
        "a refused `on` must not write the key"
    )


def test_maintainer_mode_status_reports_three_states(tmp_path):
    """`status` exits 0 and prints the same three-state line methodology-status prints (T3)."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)

    off = _verb(clone, home, "status")
    assert off.returncode == 0, off.stdout + off.stderr
    assert "maintainer_mode: off" in off.stdout.splitlines(), off.stdout

    on = _verb(clone, home, "on")
    assert on.returncode == 0, on.stdout + on.stderr
    armed = _verb(clone, home, "status")
    assert armed.returncode == 0, armed.stdout + armed.stderr
    head = _git(clone, "rev-parse", "HEAD")[:12]
    assert (
        f"maintainer_mode: on - update gates off; running {clone.resolve()} @ {head}"
        in armed.stdout.splitlines()
    ), armed.stdout

    export = _gitless_export(clone, tmp_path / "gitless-export")
    not_armed = _run_cli(
        export / "bin" / "tautline", "maintainer-mode", "status", cwd=export, env=_sync_env(home)
    )
    assert not_armed.returncode == 0, not_armed.stdout + not_armed.stderr
    assert NOT_ARMED_LINE in not_armed.stdout.splitlines(), not_armed.stdout


def test_maintainer_mode_survives_install_cli(tmp_path, unlock_home_store):
    """The key must NOT join MANAGED_USER_CONFIG_ENV_KEYS: install-cli reruns rewrite managed
    keys and preserve everything else (preserved_user_config_exports), so an armed machine
    stays armed across a reinstall."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    binary = clone / "bin" / "tautline"

    on = _verb(clone, home, "on")
    assert on.returncode == 0, on.stdout + on.stderr

    install = _run_cli(binary, "install-cli", cwd=clone, env=_sync_env(home))
    assert install.returncode == 0, install.stdout + install.stderr

    text = _config_env_path(home).read_text(encoding="utf-8")
    assert "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1" in text.splitlines()
    assert "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1" in text.splitlines()

    status = _verb(clone, home, "status")
    assert status.returncode == 0, status.stdout + status.stderr
    head = _git(clone, "rev-parse", "HEAD")[:12]
    assert (
        f"maintainer_mode: on - update gates off; running {clone.resolve()} @ {head}"
        in status.stdout.splitlines()
    ), status.stdout


def test_maintainer_mode_on_prints_advisory_for_token_lacking_launchers(
    tmp_path, unlock_home_store
):
    """Content-keyed launcher-capability detection. The fixture launcher carries the CURRENT
    template marker, so stale_claude_launchers -- the oracle this test forbids -- cannot see it;
    only the guard-token scan can.

    NOTE: the arms-under-warn behavior locked here is the deliberately scoped interim state of
    THIS release; the sibling 0.9.18 plan replaces it with a policy-tiered refusal and REWRITES
    this named test (that rewrite belongs to the sibling plan alone).
    """
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    binary = clone / "bin" / "tautline"

    install = _run_cli(binary, "install-cli", cwd=clone, env=_sync_env(home))
    assert install.returncode == 0, install.stdout + install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    installed = _run_cli(
        binary,
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "maint-claude",
        cwd=clone,
        env=_sync_env(home),
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    launcher = launcher_bin / "maint-claude"
    text = launcher.read_text(encoding="utf-8")
    assert "TAUTLINE_METHODOLOGY_MAINTAINER_MODE" in text, "T5's template must emit the token"

    # A pre-change launcher: CURRENT template marker, generated marker, NO guard token -- the
    # exact shape a launcher regenerated between the v2 template and this feature carries.
    pre_change = (
        "\n".join(line for line in text.splitlines() if "MAINTAINER_MODE" not in line) + "\n"
    )
    launcher.write_text(pre_change, encoding="utf-8")
    launcher.chmod(0o755)
    assert "# tautline-launcher-template: " in pre_change

    # Under pinned policy (install-cli's default): `on` ARMS and advises -- count + regeneration
    # command -- WITHOUT the hazard sentence (the Python standdown is complete under
    # pinned/signed with ANY launcher).
    pinned_on = _verb(clone, home, "on")
    assert pinned_on.returncode == 0, pinned_on.stdout + pinned_on.stderr
    config_text = _config_env_path(home).read_text(encoding="utf-8")
    assert "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1" in config_text.splitlines()
    assert "MAINTAINER MODE ADVISORY -- 1 installed launcher" in pinned_on.stderr, pinned_on.stderr
    assert str(launcher) in pinned_on.stderr
    assert LAUNCHER_ADVISORY_NEXT_STEP in pinned_on.stderr.splitlines(), pinned_on.stderr
    assert "auto-rescue" not in pinned_on.stderr

    # Under warn policy: STILL arms in this release, and the advisory names the live shell
    # auto-rescue hazard in so many words.
    warn_on = _verb(clone, home, "on", MINERVIT_METHODOLOGY_UPDATE_POLICY="warn")
    assert warn_on.returncode == 0, warn_on.stdout + warn_on.stderr
    assert "MAINTAINER MODE ADVISORY -- 1 installed launcher" in warn_on.stderr, warn_on.stderr
    assert LAUNCHER_ADVISORY_NEXT_STEP in warn_on.stderr.splitlines()
    assert "auto-rescue" in warn_on.stderr, warn_on.stderr
    assert "'warn'" in warn_on.stderr, warn_on.stderr

    # Regenerated launcher (token present, T5's template): the advisory goes quiet.
    regen = _run_cli(
        binary,
        "install-claude-launcher",
        "--force",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "maint-claude",
        cwd=clone,
        env=_sync_env(home),
    )
    assert regen.returncode == 0, regen.stdout + regen.stderr
    quiet_on = _verb(clone, home, "on")
    assert quiet_on.returncode == 0, quiet_on.stdout + quiet_on.stderr
    combined = quiet_on.stdout + quiet_on.stderr
    assert "ADVISORY" not in combined, combined
    assert "install-claude-launcher --force" not in combined, combined


def test_maintainer_mode_is_registered_and_classified(cli):
    """Exactly-one-set registry membership (BLOCKED: a machine update-gate mutator, the same
    posture as set-framework-channel / update-repin / install-cli -- diagnosis during startup
    remediation stays available through the ALLOWED methodology-status line) and the
    introduce-as-experimental public-contract posture the snapshot verbs shipped under."""
    assert "maintainer-mode" in cli.registered_subcommand_names()
    assert "maintainer-mode" in cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS
    assert "maintainer-mode" not in cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS
    assert cli.public_contract_status_for_command("maintainer-mode") == {"status": "experimental"}


def test_off_strips_both_config_surfaces(tmp_path):
    """A machine that migrated config surfaces while armed carries the key in BOTH files; `off`
    must strip both, or deleting the preferred file later re-arms the machine from the stale
    legacy copy (R1 finding MS-R1-P2-1)."""
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    home = _maintainer_home(tmp_path)
    config = _config_env_path(home)
    legacy = home / ".config" / "minervit" / "methodology.env"
    for path in (config, legacy):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "export KEEP_ME=1\n"
            "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1\n"
            "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1\n",
            encoding="utf-8",
        )

    off = _verb(clone, home, "off")
    assert off.returncode == 0, off.stdout + off.stderr
    assert "maintainer_mode: off" in off.stdout.splitlines(), off.stdout
    for path in (config, legacy):
        text = path.read_text(encoding="utf-8")
        assert "MAINTAINER_MODE" not in text, f"{path} still carries the key"
        assert "export KEEP_ME=1" in text.splitlines(), (
            "off must strip ONLY the maintainer-mode exports"
        )

    # The latent-re-arm probe: with the preferred file gone, resolve_user_config_env falls back
    # to the legacy file -- which must no longer carry the key.
    config.unlink()
    status = _verb(clone, home, "status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "maintainer_mode: off" in status.stdout.splitlines(), status.stdout
