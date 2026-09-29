"""The job-completed hook must never turn a green job red.

`.github/runner/job-cleanup.sh` is wired as `ACTIONS_RUNNER_HOOK_JOB_COMPLETED` (see
`.github/runner/Dockerfile`), and its own closing comment states the contract this module
enforces: *"Never fail the job on cleanup trouble: this hook's exit code becomes the JOB's exit
code, so a permission error here would turn a green suite red for a reason unrelated to the
change."*

That contract was not held, and the gap was invisible from the script alone. The runner does not
execute the hook through its shebang -- it runs it as

    /usr/bin/bash --noprofile --norc -e -o pipefail {0}

which is visible in every job log above the hook's output. The `-e` there OVERRIDES the script's
own `set -uo pipefail` (which deliberately omits `-e`), so the first unguarded non-zero command
aborts the script *before* its trailing `exit 0`, and the abort becomes the job's conclusion.

Measured cost: over the last 22 red `ci-python-full` runs on `experimental`, `Complete runner`
was the failing step in half of them, on jobs whose every real step had passed. Because
`postMergeTier.enforcement` is armed to `block`, each one stopped every lane's merge.

These tests EXECUTE the real script under the runner's real invocation rather than grepping it for
`set +e`. A shape test would stay green against a script that re-acquires `errexit` later, or that
grows a new unguarded command, or whose trap is registered after the first failure can fire. The
truth this module needs is the exit code, so it asserts the exit code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# Two probes below make a file unreadable to provoke a cleanup failure. Root ignores the mode bits
# and the `cp` succeeds, which would invert those assertions rather than fail them honestly. CI runs
# jobs as the `runner` user (see .github/runner/Dockerfile), so this skips nothing there.
running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
needs_unprivileged = pytest.mark.skipif(
    running_as_root, reason="root ignores mode bits, so an unreadable-file probe cannot fail"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".github" / "runner" / "job-cleanup.sh"
DOCKERFILE = REPO_ROOT / ".github" / "runner" / "Dockerfile"

# Exactly how the runner invokes a job hook. Taken from the job log, not from the shebang -- the
# shebang is never used for this file, which is the whole reason the defect was reachable.
RUNNER_INVOCATION = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]


def run_hook(
    home: Path,
    pristine: Path,
    extra_env: dict[str, str] | None = None,
    timeout: int = 60,
):
    """Run the real hook the way the runner runs it, against throwaway directories."""
    env = dict(os.environ)
    env["JOB_CLEANUP_TEST_MODE"] = "1"
    env["JOB_CLEANUP_HOME_DIR"] = str(home)
    env["JOB_CLEANUP_PRISTINE_DIR"] = str(pristine)
    env.update(extra_env or {})
    return subprocess.run(
        [*RUNNER_INVOCATION, str(HOOK)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def hook_with_production_paths_rewritten(tmp_path: Path, home: Path, pristine: Path) -> Path:
    """A copy of the hook whose PRODUCTION defaults point at throwaway directories.

    The sentinel-ABSENT path has to be exercised -- that is the whole point of the gate -- but
    exercising it against the real `/home/runner` would run the wipe against a live self-hosted
    runner's home, which on this project's CI container holds `_work` and therefore the very
    checkout pytest is running from. The first version of these tests relied on "/home/runner does
    not exist here": true on a developer Mac, FALSE on the runner. Codex Stage 2 R3, P1.

    Rewriting the two production literals in a copy tests the real question -- can an override
    reach the paths when the sentinel is absent? -- while naming nothing real.
    """
    text = HOOK.read_text()
    # Pin the literals. If the production defaults are ever renamed this must fail loudly rather
    # than silently stop rewriting them and point the copy back at the real /home/runner.
    assert text.count("    HOME_DIR=/home/runner\n") == 1, "production HOME_DIR literal moved"
    assert text.count("    PRISTINE=/opt/runner-pristine\n") == 1, "production PRISTINE moved"
    text = text.replace("    HOME_DIR=/home/runner\n", f"    HOME_DIR={home}\n")
    text = text.replace("    PRISTINE=/opt/runner-pristine\n", f"    PRISTINE={pristine}\n")
    copy = tmp_path / "job-cleanup-production-rewritten.sh"
    copy.write_text(text)
    copy.chmod(0o755)
    return copy


@pytest.fixture
def runner_home(tmp_path: Path) -> tuple[Path, Path]:
    """A registered runner home plus the pristine image snapshot it restores from."""
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / ".gitconfig").write_text("[user]\n\tname = pristine\n")

    home = tmp_path / "home"
    home.mkdir()
    # The registration files the hook preserves, per its own allowlist.
    (home / ".runner").write_text("{}\n")
    (home / ".credentials").write_text("{}\n")
    (home / ".env").write_text("\n")
    (home / "_diag").mkdir()
    (home / "_diag" / "Worker_current.log").write_text("log\n")
    # Job leftovers that must not survive.
    (home / "leftover-from-the-job").write_text("stale\n")
    return home, pristine


def test_hook_is_the_file_the_runner_actually_executes():
    """If the Dockerfile stops wiring this file, every other test here is testing nothing."""
    dockerfile = DOCKERFILE.read_text()
    assert "COPY job-cleanup.sh /usr/local/bin/job-cleanup.sh" in dockerfile
    assert (
        "ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/usr/local/bin/job-cleanup.sh" in dockerfile
    )


def test_clean_run_exits_zero(runner_home):
    home, pristine = runner_home
    result = run_hook(home, pristine)
    assert result.returncode == 0, (
        f"hook failed a job it should have left alone\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_hook_still_does_its_job(runner_home):
    """The exit-code fix must not be achieved by making the hook a no-op."""
    home, pristine = runner_home
    result = run_hook(home, pristine)
    assert result.returncode == 0
    assert not (home / "leftover-from-the-job").exists(), "job leftovers survived cleanup"
    assert (home / ".gitconfig").read_text() == "[user]\n\tname = pristine\n"
    # Registration must survive, or the runner deregisters on its first completed job.
    assert (home / ".runner").exists()
    assert (home / ".credentials").exists()


@needs_unprivileged
def test_unreadable_live_diagnostics_are_preserved_without_copying(runner_home):
    """A rotating/unreadable live log must never be copied, unlinked, or restored."""
    home, pristine = runner_home
    unreadable = home / "_diag" / "unreadable.log"
    unreadable.write_text("x\n")
    inode = unreadable.stat().st_ino
    unreadable.chmod(0o000)
    try:
        result = run_hook(home, pristine)
        assert result.returncode == 0, result.stderr
        assert unreadable.stat().st_ino == inode
        assert not result.stderr
    finally:
        if unreadable.exists():
            unreadable.chmod(0o600)


@needs_unprivileged
def test_an_unwritable_home_does_not_fail_the_job(tmp_path: Path):
    """The permission error the hook's own comment names as the case it must survive."""
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / ".gitconfig").write_text("x\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / "leftover").write_text("stale\n")
    home.chmod(0o500)  # readable and traversable, not writable
    try:
        result = run_hook(home, pristine)
        assert result.returncode == 0, (
            f"a permission error failed the job\nstderr:\n{result.stderr}"
        )
    finally:
        home.chmod(0o700)


def test_a_missing_pristine_snapshot_does_not_fail_the_job(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".runner").write_text("{}\n")
    result = run_hook(home, tmp_path / "does-not-exist")
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    # Losing the snapshot must not also lose the runner's identity.
    assert (home / ".runner").exists()


@needs_unprivileged
def test_cleanup_trouble_is_reported_rather_than_silently_discarded(runner_home):
    """The reason this bug survived 22 runs unexplained.

    Every failure-prone command redirected stderr to /dev/null, so the job log recorded
    `Process completed with exit code 1` and nothing about which command produced it. Not failing
    the job is correct; saying nothing about why is what made the defect uninvestigable.
    """
    home, pristine = runner_home
    unreadable = pristine / ".gitconfig"
    unreadable.write_text("x\n")
    unreadable.chmod(0o000)
    try:
        result = run_hook(home, pristine)
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "job-cleanup" in combined, (
            "cleanup trouble left no trace in the job log; the next occurrence is as "
            f"uninvestigable as this one was\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    finally:
        if unreadable.exists():
            unreadable.chmod(0o600)


def test_the_hook_does_not_rely_on_its_shebang(runner_home):
    """It is never executed through the shebang, so it must be correct under `bash -e` too.

    Pinned separately because the natural 'fix' for all of the above -- running it via its shebang
    -- is not available: the invocation is the runner's, not this repository's.
    """
    home, pristine = runner_home
    direct = subprocess.run(
        [str(HOOK)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            # REQUIRED. Without the sentinel the overrides below are ignored and this runs the
            # wipe against the real /home/runner, which exists on the CI runner.
            "JOB_CLEANUP_TEST_MODE": "1",
            "JOB_CLEANUP_HOME_DIR": str(home),
            "JOB_CLEANUP_PRISTINE_DIR": str(pristine),
        },
        timeout=60,
    )
    assert direct.returncode == 0


# --------------------------------------------------------------------------------------
# Codex Stage 2 R1: dropping the inherited errexit removed an abort that had been covering
# two destructive failure modes BY ACCIDENT. Both are worse than the red job the fix removes,
# so both are pinned.
# --------------------------------------------------------------------------------------


@needs_unprivileged
def test_a_failed_identity_copy_skips_the_wipe(runner_home, tmp_path):
    """A deregistered runner is worse than a red job, and the fix must not trade one for the other.

    Before the errexit fix, a failed `cp` of `.credentials` aborted the script, which happened to
    leave `$HOME` intact. With the abort gone, the wipe would proceed and the restore would have no
    identity to put back -- taking the runner offline while still reporting success.
    """
    home, pristine = runner_home
    (home / ".credentials").chmod(0o000)
    try:
        result = run_hook(home, pristine)
        assert result.returncode == 0
        # The wipe must NOT have run: identity intact, and the job's leftovers deliberately kept.
        assert (home / ".credentials").exists(), "the runner's identity was destroyed"
        assert (home / ".runner").exists()
        assert (home / "leftover-from-the-job").exists(), (
            "the home was wiped despite identity preservation failing"
        )
        assert "identity" in (result.stdout + result.stderr).lower()
    finally:
        if (home / ".credentials").exists():
            (home / ".credentials").chmod(0o600)


@needs_unprivileged
def test_unreadable_diagnostics_do_not_suppress_job_cleanup(runner_home):
    """Leaving diagnostics in place must not turn job hygiene into a no-op."""
    home, pristine = runner_home
    unreadable = home / "_diag" / "unreadable.log"
    unreadable.write_text("x\n")
    unreadable.chmod(0o000)
    try:
        result = run_hook(home, pristine)
        assert result.returncode == 0
        # The job leftovers are reset even though the live log is unreadable.
        assert not (home / "leftover-from-the-job").exists(), (
            "a _diag failure wrongly suppressed the wipe"
        )
        assert (home / ".runner").exists()
    finally:
        if unreadable.exists():
            unreadable.chmod(0o600)


def test_an_unusable_scratch_dir_skips_cleanup_rather_than_copying_the_filesystem_root(
    runner_home, tmp_path
):
    """`mktemp -d` failing must not leave KEEP_DIR empty and `${KEEP_DIR}/.` resolving to `/.`.

    With errexit dropped, an empty KEEP_DIR would make the identity restore
    `cp -a "/." "$HOME/"` -- copying the filesystem root into the runner's home, filling its disk,
    and still exiting 0. `set -u` does not catch it: the variable is set, just empty.
    """
    home, pristine = runner_home
    # A failing `mktemp` shim rather than a bad TMPDIR: macOS `mktemp -d` resolves its directory
    # through confstr(_CS_DARWIN_USER_TEMP_DIR) and IGNORES TMPDIR entirely, so the TMPDIR route
    # silently tests nothing on the platform this suite runs on. Shimming the binary tests the
    # guard itself and behaves the same everywhere.
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "mktemp"
    shim.write_text("#!/bin/sh\nexit 1\n")
    shim.chmod(0o755)
    # A SHORT timeout on purpose. Without the guard this run copies `/.` into the temp home; the
    # first version of this test held that open for a full minute and wrote 11GB before failing.
    # The guard makes the script exit in milliseconds, so the only thing a short deadline can cut
    # short is the failure mode.
    result = run_hook(
        home,
        pristine,
        extra_env={"PATH": f"{shim_dir}:{os.environ.get('PATH', '')}"},
        timeout=15,
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    # Nothing was wiped and nothing was copied in.
    assert (home / "leftover-from-the-job").exists(), "cleanup ran without usable scratch space"
    assert (home / ".runner").exists()
    combined = result.stdout + result.stderr
    assert "scratch" in combined.lower()
    # The unmistakable symptom of the bug: filesystem-root entries landing in the runner's home.
    for intruder in ("etc", "usr", "bin", "var"):
        assert not (home / intruder).exists(), f"filesystem root was copied into $HOME ({intruder})"


def test_the_path_overrides_are_inert_without_the_test_sentinel(tmp_path: Path):
    """Production must not trust these from whatever environment the hook is handed.

    Codex Stage 2 R2. Without the sentinel the overrides were read unconditionally, so anything
    exporting `JOB_CLEANUP_HOME_DIR` would redirect this script's wipe-and-restore, and a
    `JOB_CLEANUP_PRISTINE_DIR` pointing nowhere would let the wipe run against the real home with
    nothing to restore from. Moving off the `RUNNER_` prefix reduced the collision odds; it did not
    remove the trust.

    Run against a copy whose PRODUCTION literals are rewritten to throwaway paths -- NOT against
    the real hook. The earlier version of this test ran the real hook with the sentinel absent and
    justified it with "/home/runner does not exist here", which holds on a developer Mac and fails
    on the CI runner, where it would have wiped the live checkout mid-suite. Codex Stage 2 R3, P1.
    """
    production_home = tmp_path / "production-home"
    production_home.mkdir()
    (production_home / ".runner").write_text("{}\n")
    (production_home / "leftover-from-the-job").write_text("stale\n")
    production_pristine = tmp_path / "production-pristine"
    production_pristine.mkdir()
    (production_pristine / ".gitconfig").write_text("[user]\n\tname = pristine\n")

    # The override target. If the gate leaks, cleanup lands here instead.
    decoy = tmp_path / "decoy-home"
    decoy.mkdir()
    (decoy / "must-survive").write_text("untouched\n")

    hook = hook_with_production_paths_rewritten(tmp_path, production_home, production_pristine)
    env = dict(os.environ)
    env.pop("JOB_CLEANUP_TEST_MODE", None)
    env["JOB_CLEANUP_HOME_DIR"] = str(decoy)
    env["JOB_CLEANUP_PRISTINE_DIR"] = str(production_pristine)
    result = subprocess.run(
        [*RUNNER_INVOCATION, str(hook)], capture_output=True, text=True, env=env, timeout=30
    )

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert (decoy / "must-survive").exists(), (
        "the override was honoured without the sentinel; a stray env var can redirect the wipe"
    )
    # And the gate did not break the hook: the production target was cleaned normally.
    assert not (production_home / "leftover-from-the-job").exists()
    assert (production_home / ".runner").exists()


def test_the_sentinel_still_lets_the_overrides_through(tmp_path: Path):
    """The counterpart: gating must not make the seam unusable, or the suite tests nothing."""
    production_home = tmp_path / "production-home"
    production_home.mkdir()
    (production_home / "must-survive").write_text("untouched\n")
    production_pristine = tmp_path / "production-pristine"
    production_pristine.mkdir()

    target = tmp_path / "target-home"
    target.mkdir()
    (target / ".runner").write_text("{}\n")
    (target / "leftover-from-the-job").write_text("stale\n")
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / ".gitconfig").write_text("x\n")

    hook = hook_with_production_paths_rewritten(tmp_path, production_home, production_pristine)
    env = dict(os.environ)
    env["JOB_CLEANUP_TEST_MODE"] = "1"
    env["JOB_CLEANUP_HOME_DIR"] = str(target)
    env["JOB_CLEANUP_PRISTINE_DIR"] = str(pristine)
    result = subprocess.run(
        [*RUNNER_INVOCATION, str(hook)], capture_output=True, text=True, env=env, timeout=30
    )

    assert result.returncode == 0
    assert not (target / "leftover-from-the-job").exists(), "the override did not take effect"
    assert (production_home / "must-survive").exists(), "the production path was touched anyway"


def test_no_test_here_runs_the_REAL_hook_without_the_test_sentinel():
    """The P1 guard, kept as a ratchet rather than as a fixed intention.

    Codex Stage 2 R3 found two tests that invoked the real hook with the sentinel absent. On a
    developer Mac that is inert, because the production target `/home/runner` does not exist. On
    this project's CI runner it exists and holds `_work` -- so those tests would have wiped the
    checkout pytest was running from, mid-suite. The failure was invisible in exactly the place it
    was written and catastrophic in exactly the place it mattered.

    Fixing the two occurrences is not enough: the next test to reach for `subprocess.run([...HOOK])`
    reintroduces it. So the count is pinned. A new invocation of the REAL hook must either go
    through `run_hook` (which always sets the sentinel) or run a rewritten copy via
    `hook_with_production_paths_rewritten`; if you genuinely need a third direct call, make it
    carry `JOB_CLEANUP_TEST_MODE` and raise this number deliberately.
    """
    source = Path(__file__).read_text()
    # Needles assembled at runtime so this guard does not count ITSELF -- a self-matching scan
    # reports a number that drifts with its own wording rather than with the code it guards.
    hook_call = "str(" + "HOOK)"
    sentinel = "JOB_CLEANUP_" + "TEST_MODE"

    # Two direct invocations of the real hook: one inside run_hook, one in the shebang test.
    direct_invocations = source.count(hook_call)
    assert direct_invocations == 2, (
        f"{direct_invocations} direct invocations of the real hook (expected 2). A new one must "
        "carry the test sentinel, or target a rewritten copy, or it will run the wipe against the "
        "live /home/runner on the CI runner."
    )
    # run_hook sets it for every test that goes through it; the shebang test sets its own.
    assert source.count(sentinel) >= 3, (
        "a direct invocation of the real hook stopped setting the test sentinel"
    )


def test_auto_updated_runtime_and_live_logs_keep_their_inodes(runner_home):
    """Cleanup must not unlink the listener or downgrade the worker beneath a live process."""
    home, pristine = runner_home
    for family in ("bin", "externals"):
        versioned = home / f"{family}.2.337.0"
        versioned.mkdir()
        (home / family).symlink_to(versioned.name, target_is_directory=True)
        (versioned / "Runner.Listener").write_text("live listener\n")
        (versioned / "Runner.Worker").write_text("live worker\n")
        # The image snapshot predates the updater and contains both a plain runtime directory
        # and another version directory. Neither may overwrite or reappear beside the live one.
        (pristine / family).mkdir()
        (pristine / family / "Runner.Worker").write_text("old worker\n")
        (pristine / f"{family}.2.336.0").mkdir()
        (pristine / f"{family}.2.336.0" / "Runner.Listener").write_text("old listener\n")
    (pristine / "_diag").mkdir()
    (pristine / "_diag" / "Worker_current.log").write_text("old log\n")
    (pristine / "_diag" / "obsolete.log").write_text("obsolete\n")
    toolcache = home / "_work" / "_tool"
    toolcache.mkdir(parents=True)
    (toolcache / "job-interpreter").write_text("stale\n")
    live_paths = [
        home / family / filename
        for family in ("bin.2.337.0", "externals.2.337.0")
        for filename in ("Runner.Listener", "Runner.Worker")
    ] + [home / name for name in ("bin", "externals", "bin.2.337.0", "externals.2.337.0", "_diag", "_diag/Worker_current.log")]
    before = {path: (path.lstat().st_ino, path.lstat().st_dev) for path in live_paths}
    with (home / "_diag" / "Worker_current.log").open("a") as live_log:
        result = run_hook(home, pristine)
        assert result.returncode == 0, result.stderr
        live_log.write("written after cleanup\n")
    assert before == {path: (path.lstat().st_ino, path.lstat().st_dev) for path in live_paths}
    for family in ("bin", "externals"):
        assert (home / family).is_symlink()
        assert (home / family / "Runner.Worker").read_text() == "live worker\n"
        assert not (home / f"{family}.2.336.0").exists()
    assert (home / "_diag" / "Worker_current.log").read_text() == "log\nwritten after cleanup\n"
    assert not (home / "_diag" / "obsolete.log").exists()
    assert not toolcache.exists()
    assert not (home / "leftover-from-the-job").exists()
    assert (home / ".gitconfig").read_text() == "[user]\n\tname = pristine\n"
    assert (home / ".runner").exists() and (home / ".credentials").exists()


def test_unversioned_runtime_is_not_overwritten_by_pristine(runner_home):
    home, pristine = runner_home
    for family in ("bin", "externals"):
        (home / family).mkdir()
        (pristine / family).mkdir()
        (home / family / "runtime").write_text("running\n")
        (pristine / family / "runtime").write_text("old image\n")
    before = {home / family / "runtime": (home / family / "runtime").stat().st_ino
              for family in ("bin", "externals")}
    result = run_hook(home, pristine)
    assert result.returncode == 0, result.stderr
    for path, inode in before.items():
        assert path.stat().st_ino == inode
        assert path.read_text() == "running\n"
    assert not (home / "leftover-from-the-job").exists()
