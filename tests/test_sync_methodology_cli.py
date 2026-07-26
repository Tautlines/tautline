import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
# The running framework version, read from the same VERSION file the fixture copies into
# the clone. DERIVED, never hardcoded: these assertions cover the RUNNING-version line, so
# a literal minor series breaks every one of them on the next release bump (it already had
# to be patched 0.14 -> 0.16 once; this removes the recurrence rather than the symptom).
RUNNING_VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    command_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
        env=command_env,
    )
    return result.stdout.strip()


def _run_cli(
    binary: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    command_env = {
        **os.environ,
        "HOME": str(cwd / ".test-home"),
        "MINERVIT_METHODOLOGY_REPO": "",
        **(env or {}),
    }
    result = subprocess.run(
        [sys.executable, str(binary), *args],
        cwd=cwd,
        env=command_env,
        text=True,
        capture_output=True,
        timeout=90,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {binary} {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _write_sync_adapter(source: Path) -> None:
    adapter = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter["latestCode"] = {"enabled": False}
    adapter.setdefault("ciTestGate", {})["enforcement"] = "warn"
    adapter_path = source / "adapters" / "projects" / "example-saas.json"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(json.dumps(adapter, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_methodology_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "sync-remote.git"
    source = tmp_path / "sync-source"
    clone = tmp_path / "sync-clone"
    lane = tmp_path / "sync-lane"
    lane.mkdir()

    (source / "bin").mkdir(parents=True)
    shutil.copy2(CLI_PATH, source / "bin" / "tautline")
    (source / "bin" / "tautline").chmod(0o755)
    _write_sync_adapter(source)
    shutil.copy2(
        REPO_ROOT / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json",
        source / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json",
    )
    shutil.copy2(REPO_ROOT / "VERSION", source / "VERSION")
    manifest_dest = source / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
    manifest_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_MANIFEST, manifest_dest)
    src_dest = source / "src" / "tautline_methodology"
    src_dest.mkdir(parents=True)
    for path in (REPO_ROOT / "src" / "tautline_methodology").glob("*.py"):
        shutil.copy2(path, src_dest / path.name)
    shutil.copytree(
        REPO_ROOT / "src" / "tautline_methodology" / "core",
        src_dest / "core",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (source / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.email", "validate@example.invalid")
    _git(source, "config", "user.name", "validate")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "initial methodology fixture")
    _git(tmp_path, "init", "--bare", "-q", "--initial-branch=main", str(remote))
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-q", "-u", "origin", "main")
    subprocess.run(["git", "clone", str(remote), str(clone)], text=True, capture_output=True, check=True)
    return source, clone, lane


def _advance_remote(source: Path, name: str, content: str) -> None:
    path = source / name
    path.write_text(content + "\n", encoding="utf-8")
    _git(source, "add", name)
    _git(source, "commit", "-q", "-m", f"advance methodology remote for {name}")
    _git(source, "push", "-q", "origin", "main")


# --- T2 surface wiring: probe supplies availability/offer/remote_status; one ls-remote per launch -

def _advance_remote_version(source: Path, version: str) -> str:
    """Bump the remote's VERSION (the probe reads it at the upstream tip) and return the new sha."""
    (source / "VERSION").write_text(version + "\n", encoding="utf-8")
    _git(source, "add", "VERSION")
    _git(source, "commit", "-q", "-m", f"advance remote VERSION to {version}")
    _git(source, "push", "-q", "origin", "main")
    return _git(source, "rev-parse", "HEAD")


def _make_git_shim(tmp_path: Path) -> tuple[Path, Path]:
    """A `git` wrapper first on PATH that logs every git argv, so a launch's ls-remote/fetch calls
    can be counted end-to-end (the in-subprocess analogue of the module _GitRecorder)."""
    shim_dir = tmp_path / "gitshim"
    shim_dir.mkdir()
    log = tmp_path / "gitshim.log"
    real = shutil.which("git")
    (shim_dir / "git").write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    (shim_dir / "git").chmod(0o755)
    return shim_dir, log


def _shim_env(shim_dir: Path) -> dict[str, str]:
    return {"PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"}


def _count(log: Path, token: str) -> int:
    if not log.exists():
        return 0
    return sum(1 for line in log.read_text(encoding="utf-8").splitlines() if token in line)


def _lane_start(binary: Path, clone: Path, lane: Path, tmp_path: Path, env=None):
    return _run_cli(
        binary,
        "lane-start",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        cwd=lane,
        env={
            "MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state"),
            **(env or {}),
        },
    )


def _methodology_status(binary: Path, clone: Path, lane: Path, *extra, env=None):
    return _run_cli(
        binary,
        "methodology-status",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        *extra,
        cwd=lane,
        env=env,
    )


def test_lane_start_offers_update_and_runs_exactly_one_ls_remote(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote_version(source, "0.99.0")
    # Bring the candidate object local WITHOUT advancing HEAD (the real post-fetch launch shape):
    # the probe resolves VERSION fetch-free, and the launch itself never fetches.
    _git(clone, "fetch", "-q", "origin", "main")
    shim_dir, log = _make_git_shim(tmp_path)

    started = _lane_start(binary, clone, lane, tmp_path, env=_shim_env(shim_dir))

    assert started.returncode == 0, started.stderr
    assert (
        "framework_update_available: version=0.99.0 change=minor (running "
        in started.stdout
    )
    assert started.stdout.count("framework_update_available:") == 1
    assert (
        "framework_update_offer: 0.99.0 is available; stable-channel updates need trust set "
        "and the release pinned first: tautline install-cli --update-policy pinned, then: "
        "tautline update-repin, then: tautline sync-methodology --target ."
    ) in started.stdout
    assert "framework_remote_status: remote differs" in started.stdout
    assert _count(log, "ls-remote") == 1, "the probe supplies remote_status; no second ls-remote"
    assert _count(log, "fetch") == 0, "launch surfaces never fetch"


def test_lane_start_no_offer_when_remote_is_equal(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    shim_dir, log = _make_git_shim(tmp_path)

    started = _lane_start(binary, clone, lane, tmp_path, env=_shim_env(shim_dir))

    assert started.returncode == 0, started.stderr
    assert "framework_update_offer:" not in started.stdout
    assert f"framework_update_available: version={RUNNING_VERSION}" in started.stdout
    assert "framework_remote_status: up to date" in started.stdout
    assert _count(log, "ls-remote") == 1


def _framework_remote_status_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("framework_remote_status: ")]


def test_lane_start_offline_is_byte_identical_to_today_single_ls_remote(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing-lane-remote.git"))
    shim_dir, log = _make_git_shim(tmp_path)

    # Probe ON: source:"failed" renders from git's own ls-remote stderr (one query, no fallback).
    on = _lane_start(binary, clone, lane, tmp_path, env=_shim_env(shim_dir))
    # Probe OFF: the probe stands down and the surface prints today's remote_methodology_status.
    off = _lane_start(
        binary, clone, lane, tmp_path, env={"TAUTLINE_METHODOLOGY_UPDATE_PROBE": "off"}
    )

    assert on.returncode == 0, on.stderr
    assert off.returncode == 0, off.stderr
    on_line, off_line = _framework_remote_status_lines(on.stdout), _framework_remote_status_lines(
        off.stdout
    )
    assert on_line == off_line, (on_line, off_line)  # byte-identical to pre-plan output
    assert on_line and on_line[0].startswith("framework_remote_status: unavailable:")
    assert "framework_update_offer:" not in on.stdout
    assert _count(log, "ls-remote") == 1, "one probe ls-remote; no fallback re-probe"


def test_lane_start_non_local_candidate_facts_only_zero_fetch_then_status_full_version(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote_version(source, "0.99.0")  # remote ahead, object NOT brought local
    shim_dir, log = _make_git_shim(tmp_path)

    started = _lane_start(binary, clone, lane, tmp_path, env=_shim_env(shim_dir))

    assert started.returncode == 0, started.stderr
    # Deliberate launch no-fetch: facts-only sha line, byte-identical availability, zero fetch.
    assert "framework_update_offer: upstream main is at" in started.stdout
    assert "inspect with: tautline methodology-status --target ." in started.stdout
    assert f"framework_update_available: version={RUNNING_VERSION}" in started.stdout
    assert "framework_remote_status: remote differs" in started.stdout
    assert _count(log, "fetch") == 0

    # The status surface (fetch allowed) upgrades the sha-only cache to the full version + offer.
    status = _methodology_status(binary, clone, lane)
    assert status.returncode == 0, status.stderr
    assert "framework_update_available: version=0.99.0 change=minor (running " in status.stdout
    assert "framework_update_offer: 0.99.0 is available;" in status.stdout


def test_methodology_status_metadata_failure_renders_remote_differs_no_offer(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote(source, "VERSION", "not-a-version")  # ls-remote ok, VERSION unparsable

    status = _methodology_status(binary, clone, lane)

    assert status.returncode == 0, status.stderr
    # A metadata failure is byte-identical to today: the commit-level remote_status line, no offer,
    # and the decision-derived (running-version) availability line.
    assert "remote_status: remote differs" in status.stdout
    assert "framework_update_offer:" not in status.stdout
    assert f"framework_update_available: version={RUNNING_VERSION}" in status.stdout


def test_methodology_status_no_remote_is_byte_identical_with_zero_probe_io(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote_version(source, "0.99.0")  # newer release exists; --no-remote must ignore it
    shim_dir, log = _make_git_shim(tmp_path)

    probe_on = _methodology_status(binary, clone, lane, "--no-remote", env=_shim_env(shim_dir))
    assert probe_on.returncode == 0, probe_on.stderr
    assert _count(log, "ls-remote") == 0, "--no-remote is a full probe standdown"
    assert _count(log, "fetch") == 0

    probe_off = _methodology_status(
        binary, clone, lane, "--no-remote", env={"TAUTLINE_METHODOLOGY_UPDATE_PROBE": "off"}
    )
    assert probe_off.returncode == 0, probe_off.stderr
    assert probe_on.stdout == probe_off.stdout
    assert "framework_update_offer:" not in probe_on.stdout


def test_sync_methodology_rescues_clean_non_main_project_lane(tmp_path):
    _source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _git(clone, "switch", "-q", "-c", "stale-feature")
    stale_head = _git(clone, "rev-parse", "HEAD")

    inside_methodology = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert inside_methodology.returncode == 1
    assert "methodology_update: failed - methodology checkout is on stale-feature, not main" in inside_methodology.stdout
    assert "MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1" in inside_methodology.stdout

    no_rescue = _run_cli(binary, "sync-methodology", "--no-auto-rescue-local-changes", "--no-remote", cwd=lane)
    assert no_rescue.returncode == 1
    assert "methodology_update: failed - methodology checkout is on stale-feature, not main" in no_rescue.stdout

    rescued = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - switched clean methodology checkout from non-release branch stale-feature" in rescued.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in rescued.stdout
    assert _git(clone, "branch", "--show-current") == "main"
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    assert _git(clone, "rev-parse", "stale-feature") == stale_head


def test_sync_methodology_repairs_divergent_main_and_preserves_local_commit(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    (clone / "LOCAL-MAIN-LANE-SYNC.md").write_text("local methodology main commit for project-lane sync\n")
    _git(clone, "add", "LOCAL-MAIN-LANE-SYNC.md")
    _git(
        clone,
        "-c",
        "user.email=validate@example.invalid",
        "-c",
        "user.name=validate",
        "commit",
        "-q",
        "-m",
        "local methodology main divergence before lane sync",
        env={"MINERVIT_METHODOLOGY_ALLOW_MAIN_COMMIT": "1"},
    )
    local_head = _git(clone, "rev-parse", "HEAD")
    _advance_remote(source, "REMOTE-DIVERGE-LANE.md", "remote methodology change for clean divergence lane sync")

    repaired = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)

    assert repaired.returncode == 0, repaired.stderr
    assert "methodology_update: updated - rescued divergent methodology main ahead=1 behind=1" in repaired.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in repaired.stdout
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    rescue_branches = _git(clone, "branch", "--format=%(refname:short)", "--list", "tautline-local-rescue/*-divergent-main-*")
    rescue_branch = rescue_branches.splitlines()[-1]
    assert _git(clone, "rev-parse", rescue_branch) == local_head
    assert "local methodology main commit for project-lane sync" in _git(
        clone, "show", f"{rescue_branch}:LOCAL-MAIN-LANE-SYNC.md"
    )


def test_sync_methodology_dirty_stale_fails_closed_then_auto_rescues_from_project_lane(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote(source, "REMOTE.md", "remote methodology change")
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local methodology edit\n")
    (clone / "LOCAL-NOTE.md").write_text("local untracked methodology note\n", encoding="utf-8")

    inside_methodology = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert inside_methodology.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in inside_methodology.stdout
    assert "refusing to start with stale methodology" in inside_methodology.stdout

    env_disabled = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE": "1"},
    )
    assert env_disabled.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in env_disabled.stdout

    no_rescue = _run_cli(binary, "sync-methodology", "--no-auto-rescue-local-changes", "--no-remote", cwd=lane)
    assert no_rescue.returncode == 1
    assert "methodology_update: failed - methodology checkout has local changes and remote differs" in no_rescue.stdout

    # `--no-remote` only suppresses final remote-status reporting; the update guard still probes
    # origin so it can refuse auto-rescue when a newer release cannot be confirmed.
    original_origin = _git(clone, "remote", "get-url", "origin")
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing-sync-remote.git"))
    remote_unavailable = _run_cli(binary, "sync-methodology", "--no-remote", cwd=lane)
    assert remote_unavailable.returncode == 1
    assert "refusing to auto-rescue without confirmed newer remote methodology" in remote_unavailable.stdout
    _git(clone, "remote", "set-url", "origin", original_origin)

    fake_token = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_REEXEC_TOKEN": str(tmp_path / "fake-reexec-token")},
    )
    assert fake_token.returncode == 1
    assert "methodology_update: failed - invalid or expired MINERVIT_METHODOLOGY_REEXEC_TOKEN" in fake_token.stdout

    rescued = _run_cli(
        binary,
        "sync-methodology",
        "--no-remote",
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - rescued local changes to tautline-local-rescue/" in rescued.stdout
    assert "methodology_update: skipped - already updated in this lane-start process" in rescued.stdout
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "HEAD") == _git(clone, "rev-parse", "origin/main")
    rescue_branch = _git(clone, "branch", "--format=%(refname:short)", "--list", "tautline-local-rescue/*").splitlines()[-1]
    assert "# local methodology edit" in _git(clone, "show", f"{rescue_branch}:bin/tautline")
    safe_branch = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in rescue_branch)
    assert (tmp_path / "methodology-rescue-state" / safe_branch / "untracked" / "LOCAL-NOTE.md").exists()


def test_lane_start_stable_manual_pin_skips_dirty_stale_update_and_renders(tmp_path):
    source, clone, lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    _advance_remote(source, "REMOTE-LANE.md", "remote methodology change for lane-start")
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local methodology edit before lane-start\n")
    (clone / "LOCAL-LANE-NOTE.md").write_text("local lane-start untracked methodology note\n", encoding="utf-8")

    started = _run_cli(
        binary,
        "lane-start",
        "--project",
        str(clone / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(lane),
        cwd=lane,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )

    assert started.returncode == 0, started.stderr
    assert (
        "framework_pin: channel=stable version=unversioned-current updatePolicy=manual "
        "migrationPolicy=dry-run source=adapter"
    ) in started.stdout
    assert "framework_remote_status: remote differs" in started.stdout
    assert (
        "methodology_update: skipped - framework updatePolicy=manual; "
        "run sync-methodology intentionally at a safe boundary"
    ) in started.stdout
    assert (lane / "CLAUDE.md").exists()
    assert (lane / "AGENTS.md").exists()


def test_sync_methodology_dirty_current_skips_unless_explicit_auto_rescue(tmp_path):
    _source, clone, _lane = _make_methodology_fixture(tmp_path)
    binary = clone / "bin" / "tautline"
    with (clone / "bin" / "tautline").open("a", encoding="utf-8") as handle:
        handle.write("\n# local current methodology edit\n")

    current = _run_cli(binary, "sync-methodology", "--no-remote", cwd=clone)
    assert current.returncode == 0, current.stderr
    assert "methodology_update: skipped - methodology checkout has local changes but remote is up to date" in current.stdout

    rescued = _run_cli(
        binary,
        "sync-methodology",
        "--auto-rescue-local-changes",
        "--no-remote",
        cwd=clone,
        env={"MINERVIT_METHODOLOGY_RESCUE_STATE_DIR": str(tmp_path / "methodology-rescue-state")},
    )
    assert rescued.returncode == 0, rescued.stderr
    assert "methodology_update: updated - rescued local changes to tautline-local-rescue/" in rescued.stdout
    assert _git(clone, "status", "--porcelain") == ""
