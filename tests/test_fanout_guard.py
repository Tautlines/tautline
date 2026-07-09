"""MISSING-cost (productization): the fan-out runaway guard counts LIVE background runs (by their
.pid files) so the adapter's costPreferences.fanOutCap can cap concurrent agent spend. Stale/dead
pids and watchdog pids never count.
"""

import os


def test_empty_dir_has_no_live_runs(cli, tmp_path):
    assert cli.count_live_background_runs(tmp_path) == 0


def test_missing_dir_is_zero(cli, tmp_path):
    assert cli.count_live_background_runs(tmp_path / "does-not-exist") == 0


def test_live_pid_counts(cli, tmp_path):
    (tmp_path / "run-a.log.pid").write_text(f"{os.getpid()}\n")
    assert cli.count_live_background_runs(tmp_path) == 1


def test_dead_pid_does_not_count(cli, tmp_path):
    # PID 2^31-1 is not a live process on any realistic host.
    (tmp_path / "run-b.log.pid").write_text("2147483646\n")
    assert cli.count_live_background_runs(tmp_path) == 0


def test_watchdog_pid_is_ignored(cli, tmp_path):
    (tmp_path / "run-c.log.watchdog.pid").write_text(f"{os.getpid()}\n")
    assert cli.count_live_background_runs(tmp_path) == 0


def test_malformed_pid_is_skipped(cli, tmp_path):
    (tmp_path / "run-d.log.pid").write_text("not-a-pid\n")
    assert cli.count_live_background_runs(tmp_path) == 0
