"""Canonical-repo resolution and snapshot-manifest reporter primitives (Track B, task B1).

REPO_ROOT answers "where do I execute from"; canonical_methodology_repo() answers "which
mutable git checkout does sync manage". On a dev checkout they are the same path; once a
machine runs from an immutable snapshot they diverge, and every git write must target the
canonical checkout while every self-report must describe the snapshot we actually run.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"

# Both alias spellings of every managed key this module resolves. The operator's live shell
# exports several of these (the launcher sources the installed config env), so a test that
# only cleared the MINERVIT_ spelling would still see the TAUTLINE_ alias that resolve_env
# prefers and would assert against the operator's machine instead of the fixture.
MANAGED_ENV_NAMES = (
    "MINERVIT_METHODOLOGY_CANONICAL_REPO",
    "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
    "MINERVIT_METHODOLOGY_REPO",
    "TAUTLINE_METHODOLOGY_REPO",
    "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
    "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
)


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    """A fresh CLI module per test with a hermetic HOME and no managed env inherited.

    Function-scoped ON PURPOSE (conftest's session-scoped `cli` cannot be used here): the
    module bakes HOME-derived constants (USER_CONFIG_ENV) at import time and caches the
    resolved canonical repo in a module global, so both must be established per test.
    SourceFileLoader is REQUIRED because bin/tautline has no .py extension.
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
    return module


def _git_repo(root: Path) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bin" / "tautline").chmod(0o755)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def _exec_root(cli, root: Path, commit: str | None = None) -> Path:
    """An exec root that is NOT a git checkout: a snapshot, or a copied-out CLI.

    This is the ONLY state in which a configured canonical repo may take over: when the tree we
    execute has no `.git`, sync has nothing local to manage and must be pointed at the mutable
    checkout. With `commit` set the tree also carries a snapshot manifest.
    """
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tautline").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bin" / "tautline").chmod(0o755)
    if commit is not None:
        (root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
            json.dumps({"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": commit}),
            encoding="utf-8",
        )
    return root


def _write_config_env(cli, lines: list[str]) -> Path:
    config_env = cli.USER_CONFIG_ENV
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_env


def test_managed_keys_include_both_alias_spellings(cli):
    for name in (
        "MINERVIT_METHODOLOGY_CANONICAL_REPO",
        "TAUTLINE_METHODOLOGY_CANONICAL_REPO",
        "MINERVIT_METHODOLOGY_SNAPSHOT_STORE",
        "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE",
    ):
        assert name in cli.MANAGED_USER_CONFIG_ENV_KEYS


def test_canonical_repo_defaults_to_repo_root(cli):
    assert cli.canonical_methodology_repo() == cli.REPO_ROOT


def test_configured_canonical_repo_never_hijacks_a_live_git_exec_root(cli, tmp_path, monkeypatch):
    """A configured canonical repo must NOT redirect git writes away from a git exec root.

    Safety pin (found wiring B3). `MINERVIT_METHODOLOGY_REPO` is exported by every installed
    `~/.config/minervit/methodology.env` and names the DEPLOYED runtime checkout. Letting it
    outrank a REPO_ROOT that is itself a real checkout means `sync-methodology` run from a dev
    worktree would fetch/merge/`reset --hard` the deployed runtime instead of the worktree the
    operator is standing in -- and it would point the update machinery at the operator's live
    checkout from inside the test suite (tests/test_rescue_ref.py drives `switch_release_branch`
    with REPO_ROOT monkeypatched at a fixture repo). If we execute FROM a checkout, that checkout
    IS the one sync manages: that is the pre-migration behavior, byte for byte.
    """
    deployed = _git_repo(tmp_path / "deployed")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(deployed))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REPO", str(deployed))
    _write_config_env(cli, [f"export MINERVIT_METHODOLOGY_REPO={deployed}"])

    assert cli._valid_methodology_repo(cli.REPO_ROOT), "this test only means anything on a checkout"
    assert cli.canonical_methodology_repo() == cli.REPO_ROOT


def test_git_exec_root_self_targets_even_without_a_bin_cli(cli, tmp_path, monkeypatch):
    """A git exec root is self-managing even if it carries no bin/<cli>.

    Regression pin, and it is not hypothetical: an earlier cut gated self-targeting on
    _valid_methodology_repo(), which demands bin/<cli>. Every rescue/trust fixture repo in the
    suite is a bare git tree WITHOUT that file, so REPO_ROOT was judged "not a methodology repo",
    resolution fell through to MINERVIT_METHODOLOGY_REPO out of the real ~/.config methodology.env,
    and `switch_release_branch` ran `reset --hard origin/main` against the operator's DEPLOYED
    runtime checkout. Self-targeting must key on "is there a checkout here", nothing more.
    """
    bare = tmp_path / "fixture-repo"
    bare.mkdir()
    subprocess.run(["git", "-C", str(bare), "init", "-q"], check=True)
    assert not (bare / "bin" / "tautline").exists()
    elsewhere = _git_repo(tmp_path / "elsewhere")
    monkeypatch.setattr(cli, "REPO_ROOT", bare)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REPO", str(elsewhere))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(elsewhere))

    assert cli.canonical_methodology_repo() == bare


def test_canonical_repo_env_override_wins(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(repo))
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_repo_falls_back_to_methodology_repo_env(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "deployed")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REPO", str(repo))
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_repo_prefers_canonical_key_over_methodology_repo(cli, tmp_path, monkeypatch):
    canon = _git_repo(tmp_path / "canon")
    deployed = _git_repo(tmp_path / "deployed")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canon))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REPO", str(deployed))
    assert cli.canonical_methodology_repo() == canon.resolve()


def test_canonical_rejects_non_git_candidate(cli, tmp_path, monkeypatch):
    exec_root = _exec_root(cli, tmp_path / "snap")
    snapshot_like = _exec_root(cli, tmp_path / "other-snap")
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(snapshot_like))
    # non-git dirs are never sync targets: fetch/merge/rescue would have nothing to write to
    assert cli.canonical_methodology_repo() == exec_root


def test_invalid_candidates_fall_through_to_repo_root(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(tmp_path / "missing"))
    assert cli.canonical_methodology_repo() == cli.REPO_ROOT


def test_canonical_repo_falls_through_invalid_candidate_to_valid_one(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "deployed")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(tmp_path / "missing"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REPO", str(repo))
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_repo_reads_manifest_canonical_repo(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setattr(
        cli,
        "snapshot_manifest",
        lambda: {
            "schema": cli.SNAPSHOT_MANIFEST_SCHEMA,
            "commit": "a" * 40,
            "canonicalRepo": str(repo),
        },
    )
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_repo_reads_alias_from_config_env(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    _write_config_env(cli, [f"export TAUTLINE_METHODOLOGY_CANONICAL_REPO={repo}"])
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_repo_result_is_cached(cli, tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap"))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(repo))
    assert cli.canonical_methodology_repo() == repo.resolve()
    monkeypatch.delenv("MINERVIT_METHODOLOGY_CANONICAL_REPO")
    assert cli.canonical_methodology_repo() == repo.resolve()


def test_canonical_cache_is_keyed_by_exec_root(cli, tmp_path, monkeypatch):
    """The cache must not outlive the REPO_ROOT it was resolved against.

    REPO_ROOT is a module constant in production, so this is inert there -- but the CLI module is
    imported ONCE per pytest session (tests/conftest.py) and suite after suite monkeypatches
    REPO_ROOT at its own fixture repo. A cache that ignored its input would hand the second suite
    the first suite's repository and run `reset --hard` in it.
    """
    first = _git_repo(tmp_path / "first")
    second = _git_repo(tmp_path / "second")
    monkeypatch.setattr(cli, "REPO_ROOT", first)
    assert cli.canonical_methodology_repo() == first
    monkeypatch.setattr(cli, "REPO_ROOT", second)
    assert cli.canonical_methodology_repo() == second


def test_snapshot_manifest_absent_on_git_checkout(cli):
    assert cli.snapshot_manifest() is None
    assert cli.running_from_snapshot() is False


def test_snapshot_manifest_rejects_wrong_schema(cli, tmp_path, monkeypatch):
    root = tmp_path / "exec"
    root.mkdir()
    (root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps({"schema": "something-else/v9", "commit": "a" * 40}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "REPO_ROOT", root)
    assert cli.snapshot_manifest() is None


def test_snapshot_manifest_rejects_malformed_json(cli, tmp_path, monkeypatch):
    root = tmp_path / "exec"
    root.mkdir()
    (root / cli.SNAPSHOT_MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", root)
    assert cli.snapshot_manifest() is None


def test_snapshot_manifest_rejects_short_commit(cli, tmp_path, monkeypatch):
    root = tmp_path / "exec"
    root.mkdir()
    (root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps({"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": "abc"}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "REPO_ROOT", root)
    assert cli.snapshot_manifest() is None


def test_snapshot_manifest_accepted_and_reported(cli, tmp_path, monkeypatch):
    root = tmp_path / "exec"
    root.mkdir()
    (root / cli.SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps({"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": "b" * 40}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "REPO_ROOT", root)
    assert cli.snapshot_manifest()["commit"] == "b" * 40
    assert cli.running_from_snapshot() is True


def test_running_commit_prefers_manifest(cli, monkeypatch):
    manifest = {"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": "a" * 40}
    monkeypatch.setattr(cli, "snapshot_manifest", lambda: manifest)
    assert cli.running_methodology_commit() == "a" * 40
    assert cli.running_methodology_commit(short=True) == "a" * 12


def test_running_commit_falls_back_to_git(cli, monkeypatch):
    monkeypatch.setattr(cli, "snapshot_manifest", lambda: None)
    head = cli.run_git(cli.REPO_ROOT, ["rev-parse", "HEAD"])
    assert cli.running_methodology_commit() == head
    # Deliberately NOT `rev-parse --short`: git's abbreviation length is repo-state-dependent
    # (8 chars here, 7 in older clones) and a snapshot has no .git to ask, so pinning the short
    # form to git's abbreviation would make the SAME commit report differently per exec root.
    # See test_short_commit_is_identical_across_exec_roots.
    assert cli.running_methodology_commit(short=True) == head[:12]


def test_short_commit_is_identical_across_exec_roots(cli, monkeypatch):
    """The short form must not depend on WHERE we execute.

    A snapshot can only slice its manifest sha; a checkout could ask git to abbreviate. If those
    two disagree, one methodology commit has two names -- and the short name is embedded in a
    byte-compared generated artifact (see the render test below).
    """
    head = cli.run_git(cli.REPO_ROOT, ["rev-parse", "HEAD"])
    assert head != "unavailable"

    monkeypatch.setattr(cli, "snapshot_manifest", lambda: None)
    from_checkout = cli.running_methodology_commit(short=True)

    monkeypatch.setattr(
        cli, "snapshot_manifest", lambda: {"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": head}
    )
    from_snapshot = cli.running_methodology_commit(short=True)

    assert from_snapshot == from_checkout, (
        f"same commit {head} reports {from_checkout!r} from a checkout but {from_snapshot!r} "
        "from a snapshot exec root"
    )


def test_generated_adapter_is_byte_identical_across_exec_roots(cli, monkeypatch):
    """adapter_drift byte-compares the rendered adapter against the file on disk, and
    render_project_config embeds running_methodology_commit(short=True) as
    `_generated.methodologyCommit`. If a snapshot lane and a canonical-checkout lane at the SAME
    methodology commit render different bytes, drift can never converge: each lane's re-render
    puts the other back into drift (and drift is a gate -- methodology-status --fail-on-drift and
    lane-start both fail on it), a permanent ping-pong with zero methodology change.
    """
    source = "adapters/projects/example-saas.json"
    data = json.loads((cli.REPO_ROOT / source).read_text(encoding="utf-8"))
    head = cli.run_git(cli.REPO_ROOT, ["rev-parse", "HEAD"])

    monkeypatch.setattr(cli, "snapshot_manifest", lambda: None)
    from_checkout = cli.render_project_config(data, source)

    monkeypatch.setattr(
        cli, "snapshot_manifest", lambda: {"schema": cli.SNAPSHOT_MANIFEST_SCHEMA, "commit": head}
    )
    from_snapshot = cli.render_project_config(data, source)

    assert json.loads(from_checkout)["_generated"]["methodologyCommit"] == head[:12]
    assert from_snapshot == from_checkout


def test_short_commit_preserves_the_unavailable_sentinel(cli, monkeypatch):
    """Slicing must not mangle run_git's failure sentinel into a fake sha prefix."""
    monkeypatch.setattr(cli, "snapshot_manifest", lambda: None)
    monkeypatch.setattr(cli, "run_git", lambda target, args: "unavailable")
    assert cli.running_methodology_commit() == "unavailable"
    assert cli.running_methodology_commit(short=True) == "unavailable"


def test_snapshot_store_root_defaults_under_home(cli, tmp_path):
    expected = Path(tmp_path / "home") / ".local" / "share" / "minervit" / "tautline-releases"
    assert cli.methodology_snapshot_store_root() == expected


def test_snapshot_store_root_env_override(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_SNAPSHOT_STORE", str(tmp_path / "store"))
    assert cli.methodology_snapshot_store_root() == (tmp_path / "store").resolve()


def test_snapshot_store_alias_in_config_env_beats_stale_legacy_key(cli, tmp_path):
    _write_config_env(
        cli,
        [
            f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={tmp_path / 'fresh'}",
            f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={tmp_path / 'stale'}",
        ],
    )
    assert cli.methodology_snapshot_store_root() == (tmp_path / "fresh").resolve()


def test_snapshot_store_live_env_beats_config_env(cli, tmp_path, monkeypatch):
    _write_config_env(
        cli, [f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={tmp_path / 'from-file'}"]
    )
    monkeypatch.setenv("MINERVIT_METHODOLOGY_SNAPSHOT_STORE", str(tmp_path / "from-env"))
    assert cli.methodology_snapshot_store_root() == (tmp_path / "from-env").resolve()


def test_snapshot_store_disabled_without_managed_key(cli):
    # A stray store directory at the default location must NOT activate snapshot mode: the
    # cutover is release -> repin -> install-cli, and only the managed key expresses it.
    store = cli.methodology_snapshot_store_root()
    store.mkdir(parents=True)
    (store / "current").mkdir()
    assert cli.methodology_snapshot_store_enabled() is False


def test_snapshot_store_enabled_by_live_env(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_SNAPSHOT_STORE", str(tmp_path / "store"))
    assert cli.methodology_snapshot_store_enabled() is True


def test_snapshot_store_enabled_by_config_env(cli, tmp_path):
    _write_config_env(cli, [f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={tmp_path / 'store'}"])
    assert cli.methodology_snapshot_store_enabled() is True


# --- Task B3: update machinery retargeted at the canonical repo ------------------------------


def test_reexec_token_accepts_manifest_commit_from_snapshot(cli, tmp_path, monkeypatch):
    """From a snapshot the token cannot be validated with `rev-parse`.

    A snapshot is an exported tree with no `.git`, so run_git returns the "unavailable" sentinel
    and the post-advance handoff token would ALWAYS fail to validate -- update_methodology_repo
    would then report "invalid or expired token" on every re-exec and refuse to run. The snapshot
    tree is immutable, so the manifest commit is the truthful identity and the dirty check is
    vacuous.
    """
    head = "c" * 40
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap", commit=head))
    monkeypatch.setenv(cli.METHODOLOGY_REEXEC_TOKEN_ENV, cli.create_methodology_reexec_token(head))

    assert cli.running_from_snapshot() is True
    assert cli.consume_methodology_reexec_token() is True


def test_reexec_token_from_snapshot_rejects_a_different_commit(cli, tmp_path, monkeypatch):
    # The manifest comparison must still be a real check: a token minted for another commit is
    # not a licence to skip the update.
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap", commit="c" * 40))
    token = cli.create_methodology_reexec_token("d" * 40)
    monkeypatch.setenv(cli.METHODOLOGY_REEXEC_TOKEN_ENV, token)

    assert cli.consume_methodology_reexec_token() is False


def test_sync_journals_the_fast_forward_advance(cli, tmp_path, monkeypatch):
    """The advance is journaled BEFORE the re-exec.

    os.execve replaces this process, so a journal write placed after the fast-forward would never
    run on the one path that actually moves the canonical repo.
    """
    canonical = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap", commit="a" * 40))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)
    monkeypatch.setattr(cli, "create_methodology_reexec_token", lambda head: "tok")
    monkeypatch.setattr(cli, "verify_upstream_trust", lambda head: (True, ""))
    monkeypatch.setattr(cli, "methodology_release_upstream", lambda channel="stable": None)
    heads = iter(["1" * 40, "2" * 40])  # old_head, then new_head after the ff

    def _fake_run_git(_repo, args):
        if args == ["rev-parse", "HEAD"]:
            return next(heads)
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return "true"
        if args == ["branch", "--show-current"]:
            return "main"
        return ""

    monkeypatch.setattr(cli, "run_git", _fake_run_git)
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (0, "Updating", ""))

    class _Execve(Exception):
        pass

    monkeypatch.setattr(cli.os, "execve", lambda *a, **k: (_ for _ in ()).throw(_Execve()))
    with pytest.raises(_Execve):
        cli.update_methodology_repo(False)

    entries = [
        json.loads(line)
        for line in cli.methodology_write_journal_path().read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["command"].startswith("sync-methodology")
    assert entries[-1]["outcome"] == "ok"
    assert entries[-1]["old_head"] == "1" * 40
    assert entries[-1]["new_head"] == "2" * 40


def test_read_only_sync_refusal_writes_no_journal(cli, tmp_path, monkeypatch):
    """A refusal that mutated nothing must leave NO journal entry -- and no file at all.

    Not merely tidiness. The journal lives under $HOME, and tests/test_sync_methodology_cli.py
    points $HOME *inside* the methodology checkout it drives. An unconditional journal write on
    the refusal paths left an untracked `.test-home/` in that checkout, so the next sync saw a
    dirty tree and took the local-changes rescue branch instead of the clean non-main branch.
    Forensics has to observe mutations, never cause them.
    """
    status, _detail = cli.update_methodology_repo(True)  # --skip-update: no git write at all

    assert status == "skipped"
    assert not cli.methodology_write_journal_path().exists()


def test_journal_refuses_to_write_inside_the_managed_checkout(cli, tmp_path, monkeypatch):
    """$HOME inside the canonical checkout must not turn the journal into a tracked-tree change.

    The sync machinery reads the canonical repo's `git status` as a control signal: dirty routes
    the next sync into the local-changes rescue path, and the post-advance re-exec token is only
    honoured on a clean tree. A journal file landing in that tree makes the tool auto-rescue its
    own log and reject its own handoff token (observed: tests/test_sync_methodology_cli.py sets
    HOME to a directory inside the checkout it drives).
    """
    canonical = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", canonical)
    monkeypatch.setenv("HOME", str(canonical / ".test-home"))
    assert cli.methodology_write_journal_path().is_relative_to(canonical)  # the hazardous topology

    cli.append_methodology_write_journal("sync-methodology", "a" * 40, "b" * 40, "ok")

    assert not cli.methodology_write_journal_path().exists()
    status = subprocess.run(
        ["git", "-C", str(canonical), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".test-home" not in status, "the journal must not appear as a change in the managed tree"


def test_release_guards_install_into_the_canonical_repo_from_a_snapshot(cli, tmp_path, monkeypatch):
    """The retarget proof: from a snapshot exec root the guards land in the CANONICAL checkout.

    Trap 9 in the plan: `install_methodology_release_guards` rev-parses the exec root, so from a
    snapshot (no `.git`) it silently no-ops -- the release-main protection just stops existing.
    """
    canonical = _git_repo(tmp_path / "canon")
    exec_root = _exec_root(cli, tmp_path / "snap", commit="e" * 40)
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))

    detail = cli.install_methodology_release_guards()

    assert detail.startswith("installed"), detail
    assert (canonical / ".git" / "hooks" / "pre-commit").is_file()
    assert not (exec_root / ".git").exists()
    entries = [
        json.loads(line)
        for line in cli.methodology_write_journal_path().read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["command"] == "install-methodology-release-guards"


def test_rescue_ref_warnings_read_the_canonical_repo(cli, tmp_path, monkeypatch):
    # Trap 6: the rescue-ref drift detector defaults at REPO_ROOT, so from a snapshot it goes
    # blind -- it would report "clean" no matter what the canonical checkout is carrying.
    canonical = _git_repo(tmp_path / "canon")
    monkeypatch.setattr(cli, "REPO_ROOT", _exec_root(cli, tmp_path / "snap", commit="f" * 40))
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    seen: list[Path] = []
    monkeypatch.setattr(cli, "run_git", lambda repo, args: seen.append(repo) or "unavailable")

    cli.methodology_rescue_ref_adapter_changes()

    assert seen and seen[0] == canonical


# --- Task B4: self-reports describe the code we run, not the checkout sync manages -------------


def _commit(root: Path) -> str:
    """Give a fixture repo a HEAD, and return its short sha.

    The short form is the same fixed 12-char prefix the CLI reports -- NOT `rev-parse --short`,
    which abbreviates to 7 chars in a one-commit fixture repo and 8 in this one. The CLI must name
    a commit identically no matter which repo (or snapshot) it read it from.
    """
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=tests@example.invalid",
            "-c",
            "user.name=Tests",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()[:12]


def test_version_reports_the_running_snapshot_and_the_canonical_commit(
    cli, tmp_path, monkeypatch, capsys
):
    """From a snapshot the two commits differ, and `version` must show BOTH truthfully.

    `rev-parse` in the exec root answers "unavailable" (a snapshot has no `.git`), so every
    self-report that reads REPO_ROOT goes blind exactly when the divergence starts to matter.
    The manifest here carries ONLY `schema` + `commit` -- the shape snapshot_manifest() accepts --
    so a reporter that reached for a `shortCommit` key would raise KeyError on a manifest the
    reader legitimately accepted; the short form must be derived from `commit`.
    """
    canonical = _git_repo(tmp_path / "canon")
    canonical_head = _commit(canonical)
    snapshot_commit = "b" * 40
    snapshot = _exec_root(cli, tmp_path / "snap", commit=snapshot_commit)
    monkeypatch.setattr(cli, "REPO_ROOT", snapshot)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))

    assert cli.version(argparse.Namespace(no_remote=True)) == 0
    out = capsys.readouterr().out

    assert f"methodology_commit: {snapshot_commit}\n" in out
    assert f"methodology_commit_short: {snapshot_commit[:12]}\n" in out
    assert f"methodology_canonical_commit: {canonical_head}\n" in out
    assert f"methodology_exec_root: {snapshot} (snapshot {snapshot_commit[:12]})\n" in out


def test_version_exec_root_line_names_a_canonical_checkout_when_not_a_snapshot(cli, capsys):
    # On a dev checkout the exec root IS the canonical checkout: same path, no snapshot label,
    # and the two commit lines agree.
    assert cli.version(argparse.Namespace(no_remote=True)) == 0
    out = capsys.readouterr().out

    head = cli.run_git(cli.REPO_ROOT, ["rev-parse", "HEAD"])[:12]
    assert f"methodology_exec_root: {cli.REPO_ROOT} (canonical checkout)\n" in out
    assert f"methodology_canonical_commit: {head}\n" in out
    assert f"methodology_commit_short: {head}\n" in out


def test_running_and_canonical_commit_lines_are_the_same_string_in_sync(cli, capsys):
    """One commit, one name -- across the whole self-report surface.

    The two lines exist to be COMPARED: equal means "the snapshot I run is what sync manages",
    different means "my snapshot is behind". If the running line is a 12-char manifest slice while
    the canonical line is git's repo-state-dependent abbreviation (8 chars here, 7 in a fresh
    fixture repo), then a perfectly in-sync checkout reports two different-looking shas and reads
    as permanent snapshot lag.
    """
    assert cli.version(argparse.Namespace(no_remote=True)) == 0
    out = capsys.readouterr().out

    reported = {
        key: value
        for key, _, value in (line.partition(": ") for line in out.splitlines())
    }
    assert reported["methodology_commit_short"] == reported["methodology_canonical_commit"]
    assert reported["methodology_commit"].startswith(reported["methodology_commit_short"])


def test_sync_methodology_reports_both_commits(cli, tmp_path, monkeypatch, capsys):
    # sync mutates the canonical checkout while it keeps running the snapshot it was launched
    # from: the operator has to be able to see both, or "sync says it advanced but nothing
    # changed" is unexplainable until the next launch swaps the snapshot in.
    canonical = _git_repo(tmp_path / "canon")
    canonical_head = _commit(canonical)
    snapshot = _exec_root(cli, tmp_path / "snap", commit="c" * 40)
    monkeypatch.setattr(cli, "REPO_ROOT", snapshot)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    monkeypatch.setattr(cli, "update_methodology_repo", lambda *a, **k: ("ok", "fast-forwarded"))
    monkeypatch.setattr(cli, "install_methodology_release_guards", lambda: "installed")
    monkeypatch.setattr(cli, "should_auto_rescue_methodology_for_project_startup", lambda: False)

    rc = cli.sync_methodology(
        argparse.Namespace(target=None, skip_update=False, no_remote=True)
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "methodology_commit: cccccccccccc\n" in out
    assert f"methodology_canonical_commit: {canonical_head}\n" in out
    assert f"methodology_exec_root: {snapshot} (snapshot cccccccccccc)\n" in out


def _function_line_span(source: list[str], name: str) -> set[int]:
    """1-indexed line numbers of `def <name>` through the line before the next top-level def/class."""
    start = next(
        number
        for number, line in enumerate(source, start=1)
        if line.startswith(f"def {name}(")
    )
    end = next(
        (
            number
            for number, line in enumerate(source[start:], start=start + 1)
            if re.match(r"^(def |class |@)", line)
        ),
        len(source) + 1,
    )
    return set(range(start, end))


def test_no_self_report_rev_parses_the_exec_root():
    """Structural pin for the whole C-cat class: self-reports must not `rev-parse` REPO_ROOT.

    Every such read returns "unavailable" from a snapshot, so a single one re-introduced by a
    later change silently blanks a status line, a lock record, a session record, or an event
    payload. `running_methodology_commit()` is the only sanctioned reader.

    B4 allowlisted exactly one exception -- install-cli's trust pin, a WRITE of the commit the
    install trusts -- and noted that Track B task B8 would move it to the canonical repo. B8 did
    (a pin recorded from a snapshot's REPO_ROOT would read "unavailable" and trust nothing), so
    the line allowlist is now EMPTY and this guard is absolute. Do not re-open it.

    The ONE exemption is structural, not a text allowlist: the sanctioned reader's own body. Its
    checkout fallback is definitionally a `rev-parse` of REPO_ROOT -- that is the function's job --
    so its lines are excluded by SYMBOL. Until this change the reader slipped through only because
    it happened to hoist the args list into a local (`run_git(REPO_ROOT, args)`, which this
    single-line regex cannot see); a formatter joining those lines would have tripped a guard that
    never meant to catch it. Naming the exemption keeps the guard honest and absolute everywhere
    else.
    """
    source = CLI_PATH.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(r"""run_git\(\s*REPO_ROOT\s*,\s*\[\s*["']rev-parse""")

    # The guard must be able to go RED: if a refactor ever renames run_git or REPO_ROOT, this
    # scanner would quietly match nothing and pass forever.
    assert pattern.search('    return run_git(REPO_ROOT, ["rev-parse", "HEAD"])')

    sanctioned = _function_line_span(source, "running_methodology_commit")
    offenders = {
        f"{number}: {line.strip()}"
        for number, line in enumerate(source, start=1)
        if pattern.search(line) and number not in sanctioned
    }

    assert offenders == set()
    # ...and the exemption is not vacuous: the reader really does hold the only such call.
    assert any(pattern.search(source[number - 1]) for number in sanctioned)


# --- Task B10: canonical data paths, containment/redaction, release-checkout write guard -------
#
# A snapshot is an EXPORT of committed content. Private source adapters live only in the canonical
# checkout's working tree (they are never committed to the public repo), and archive copies are
# working-tree data the maintainer commits by hand -- so every adapter/archive path must resolve
# canonical-first, and every archive WRITE must land in the canonical checkout, never in the
# read-only tree we happen to execute.


# The private adapter's repo-relative path, assembled from parts ON PURPOSE. A literal
# `adapters/projects/<non-example>.json` anywhere in the public surface is exactly what
# public-release-check's private-adapter scanner blocks on -- and it is right to: a real private
# adapter path is a client name. Splitting it keeps this fixture from reading as the leak the
# scanner exists to catch.
PRIVATE_ADAPTER_DIR = "adapters/projects"
PRIVATE_ADAPTER_FILE = "private-product.json"
PRIVATE_ADAPTER_RELPATH = f"{PRIVATE_ADAPTER_DIR}/{PRIVATE_ADAPTER_FILE}"


def _reference_adapter_data() -> dict:
    reference = CLI_PATH.parents[1] / "adapters/projects/example-saas.json"
    return json.loads(reference.read_text(encoding="utf-8"))


def _private_adapter(canonical: Path) -> Path:
    """A source adapter that exists ONLY in the canonical checkout (never in a snapshot)."""
    source = _reference_adapter_data()
    path = canonical / PRIVATE_ADAPTER_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _snapshot_over_canonical(
    cli, tmp_path, monkeypatch, commit: str = "a" * 40
) -> tuple[Path, Path]:
    canonical = _git_repo(tmp_path / "canon")
    exec_root = _exec_root(cli, tmp_path / "snap", commit=commit)
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    return canonical, exec_root


def test_private_source_adapter_resolves_from_the_canonical_checkout(cli, tmp_path, monkeypatch):
    """Trap 3: a private adapter exists only in the canonical checkout's working tree.

    From a snapshot exec root every adapter path that anchors on REPO_ROOT points into an export
    that can never contain it, so the adapter is 'missing', its trust root is 'untrusted', and
    every lane rendered from it fails.
    """
    canonical, exec_root = _snapshot_over_canonical(cli, tmp_path, monkeypatch)
    private = _private_adapter(canonical)
    assert not (exec_root / "adapters").exists()

    assert cli.trusted_source_adapter_roots()[0] == (canonical / PRIVATE_ADAPTER_DIR).resolve()
    assert cli.source_adapter_requires_bootstrap_evidence(private) is True
    assert cli.source_adapter_path(PRIVATE_ADAPTER_RELPATH) == private
    assert cli.source_adapter_repo_relative_path(private) == PRIVATE_ADAPTER_RELPATH
    assert cli.display_project_arg(private) == PRIVATE_ADAPTER_RELPATH


def test_render_reads_the_source_adapter_from_the_canonical_checkout(cli, tmp_path, monkeypatch):
    """`sourceAdapterSha256` must not read 'unavailable' just because we run from a snapshot.

    render_project_config resolves a relative sourceAdapter against the repo root and hashes it.
    Anchored on the exec root the file is absent, the hash degrades to the sentinel, and the
    rendered adapter differs from the canonical-checkout render of the SAME commit -- the drift
    ping-pong the short-commit fix already closed, re-entering through the adapter hash.
    """
    canonical, _exec_root = _snapshot_over_canonical(cli, tmp_path, monkeypatch)
    private = _private_adapter(canonical)
    monkeypatch.setattr(cli, "plugin_version", lambda: "0.0.0-test")
    data = json.loads(private.read_text(encoding="utf-8"))

    rendered = json.loads(cli.render_project_config(data, PRIVATE_ADAPTER_RELPATH))

    assert rendered["_generated"]["sourceAdapterSha256"] == cli.file_sha256(private)
    assert rendered["_generated"]["sourceAdapterSha256"] != "unavailable"


def test_event_text_redacts_the_canonical_repo_and_the_snapshot_store(cli, tmp_path, monkeypatch):
    """Redaction must cover BOTH roots plus the store: post-cutover, machine paths that used to be
    REPO_ROOT now surface as the canonical checkout and as `<store>/<sha12>` exec roots."""
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("MINERVIT_METHODOLOGY_SNAPSHOT_STORE", str(store))
    canonical = _git_repo(tmp_path / "canon")
    exec_root = _exec_root(cli, store / ("b" * 12), commit="b" * 40)
    monkeypatch.setattr(cli, "REPO_ROOT", exec_root)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_CANONICAL_REPO", str(canonical))
    data = _reference_adapter_data()
    target = tmp_path / "lane"
    target.mkdir()

    text = f"synced {canonical}/methodology from {exec_root}/bin and pruned {store}/old"
    normalized = cli.normalize_event_text(data, target, text)

    assert str(canonical) not in normalized
    assert str(exec_root) not in normalized
    assert str(store) not in normalized
    assert normalized.count("<methodology_repo>") == 3


def test_renderer_kit_guard_refuses_both_methodology_roots(cli, tmp_path, monkeypatch):
    """The renderer kit is copied into user state; it must never be written into EITHER root."""
    canonical, exec_root = _snapshot_over_canonical(cli, tmp_path, monkeypatch)
    source = tmp_path / "renderer-source"
    source.mkdir()
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    for install_dir in (exec_root / "state" / "renderer-kit", canonical / "state" / "renderer-kit"):
        with pytest.raises(SystemExit) as excinfo:
            cli.prepare_iteration_review_renderer_tree(source, install_dir)
        assert "outside the methodology repo" in str(excinfo.value)
        assert not install_dir.exists()

    outside = tmp_path / "user-state" / "renderer-kit"
    cli.prepare_iteration_review_renderer_tree(source, outside)
    assert (outside / "package.json").is_file()


# --- The release-checkout write guard ---------------------------------------------------------
#
# Archive publication must never dirty the checkout sync/rescue manages: a dirty canonical routes
# the next sync into the local-changes rescue path for EVERY lane on the machine.


def _publish_args(artifact: Path, **overrides) -> argparse.Namespace:
    fields = dict(
        file=artifact,
        archive_dir=None,
        no_stage=False,
        allow_release_checkout_write=False,
        commit=False,
        push=False,
        branch="methodology-rca-archive",
        message=None,
    )
    fields.update(overrides)
    return argparse.Namespace(**fields)


def _rca_artifact(path: Path) -> Path:
    path.write_text(
        "# Methodology Regression RCA\n\n"
        "## What happened\nThe lane skipped a required durable RCA artifact.\n\n"
        "## Evidence\n- methodology/canonical-rules.md: resolved active process authority.\n\n"
        "## Root cause\nThe validation coverage was incomplete around RCA artifact shape.\n\n"
        "## Proposed control\nAdd focused RCA artifact tests under tests/test_rca_artifact.py.\n\n"
        "## Validation\nRun `tautline validate-rca-artifact --file docs/backlog/x.md`.\n",
        encoding="utf-8",
    )
    return path


def _canonical_checkout_on(cli, tmp_path, monkeypatch, branch: str, policy: str) -> Path:
    """A canonical checkout we also execute from (the pre-cutover shape), on a chosen branch."""
    canonical = _git_repo(tmp_path / "canon")
    _commit(canonical)
    subprocess.run(["git", "-C", str(canonical), "checkout", "-qB", branch], check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", canonical)
    monkeypatch.setattr(
        cli, "DEFAULT_RCA_ARCHIVE_DIR", canonical / "docs" / "backlog" / "methodology-regressions"
    )
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", policy)
    return canonical


def test_archive_write_refused_on_release_checkout(cli, tmp_path, monkeypatch, capsys):
    canonical = _canonical_checkout_on(cli, tmp_path, monkeypatch, "main", "pinned")
    artifact = _rca_artifact(tmp_path / "20260713T120000Z-methodology-rca.md")

    rc = cli.publish_rca_artifact(_publish_args(artifact))

    assert rc == 1
    err = capsys.readouterr().err
    assert "--allow-release-checkout-write" in err
    assert str(canonical) in err
    assert "main" in err
    # Refused BEFORE the write: the checkout sync manages must be exactly as clean as we found it.
    assert not (canonical / "docs" / "backlog").exists()
    status = subprocess.run(
        ["git", "-C", str(canonical), "status", "--short"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == ""


def test_archive_write_allowed_with_flag(cli, tmp_path, monkeypatch):
    canonical = _canonical_checkout_on(cli, tmp_path, monkeypatch, "main", "pinned")
    artifact = _rca_artifact(tmp_path / "20260713T120000Z-methodology-rca.md")

    rc = cli.publish_rca_artifact(_publish_args(artifact, allow_release_checkout_write=True))

    assert rc == 0
    archived = canonical / "docs" / "backlog" / "methodology-regressions" / artifact.name
    assert archived.is_file()
    staged = subprocess.run(
        ["git", "-C", str(canonical), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "docs/backlog/methodology-regressions/20260713T120000Z-methodology-rca.md" in staged
    # Every canonical mutation is attributable (B2's journal), including the archive stage.
    entries = [
        json.loads(line)
        for line in cli.methodology_write_journal_path().read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["command"] == "archive.git-add"
    assert entries[-1]["outcome"] == "ok"


def test_archive_write_allowed_on_dev_checkout(cli, tmp_path, monkeypatch):
    """A maintainer's dev checkout is not the auto-synced release checkout: staging an archive copy
    into a feature branch is ordinary work, and nothing on the machine rescues it out from under
    them."""
    canonical = _canonical_checkout_on(cli, tmp_path, monkeypatch, "feat/rca-flow", "pinned")
    artifact = _rca_artifact(tmp_path / "20260713T120000Z-methodology-rca.md")

    rc = cli.publish_rca_artifact(_publish_args(artifact))

    assert rc == 0
    assert (canonical / "docs" / "backlog" / "methodology-regressions" / artifact.name).is_file()


def test_archive_write_allowed_when_the_checkout_is_not_auto_synced(cli, tmp_path, monkeypatch):
    """Release branch, but no pinned/signed update policy: sync is not advancing this checkout, so
    it is not the checkout the guard exists to protect."""
    canonical = _canonical_checkout_on(cli, tmp_path, monkeypatch, "main", "warn")
    artifact = _rca_artifact(tmp_path / "20260713T120000Z-methodology-rca.md")

    assert cli.publish_rca_artifact(_publish_args(artifact)) == 0
    assert (canonical / "docs" / "backlog" / "methodology-regressions" / artifact.name).is_file()


def test_release_checkout_write_guard_fails_closed_on_an_unreadable_branch(
    cli, tmp_path, monkeypatch
):
    """A pinned checkout whose branch cannot be read (detached HEAD mid-rescue, unreadable git) is
    assumed to be the managed one: guessing 'dev' here would dirty exactly the tree we protect."""
    _canonical_checkout_on(cli, tmp_path, monkeypatch, "main", "pinned")
    monkeypatch.setattr(cli, "current_branch_name", lambda target: "")

    managed, detail = cli.canonical_release_checkout_status()

    assert managed is True
    assert "unknown branch" in detail


def test_archive_publication_to_a_branch_never_touches_the_checkout(cli, tmp_path, monkeypatch):
    """--commit --push publishes through an isolated clone, so it stays allowed on a pinned release
    checkout -- that is the sanctioned path, and the guard must not break it."""
    canonical = _canonical_checkout_on(cli, tmp_path, monkeypatch, "main", "pinned")
    assert cli.release_checkout_archive_write_allowed(
        _publish_args(canonical / "unused.md", commit=True, push=True), "RCA"
    )
