"""Item 83 PR1 / WS1: `background-run` can say whether the work finished, and how.

The gap this closes: `background-run` used to `Popen` the command and return, so nothing in the
process tree ever called `wait()`. Nothing could know the exit code, and nothing recorded that the
run finished at all. A monitor could only infer from a dead pid -- and "the pid is gone" and "the
pid never started" are the same observation.

That is why a stalled background run reads exactly like a finished one, which is the contributing
factor behind the stale-monitor RCA: the tool that launches the work could not say whether the work
succeeded.
"""

import json
import time
from pathlib import Path



def _await_meta(meta_path: Path, key: str = "finishedAt", deadline: float = 10.0) -> dict:
    """Poll for a recorded completion. A deadline, never a sleep-and-hope."""
    end = time.time() + deadline
    while time.time() < end:
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.05)
            continue
        if key in data:
            return data
        time.sleep(0.05)
    raise AssertionError(f"{key} never appeared in {meta_path} within {deadline}s")


def _await_marker(log_path: Path, deadline: float = 10.0) -> str:
    """Poll for the terminal marker itself, and return the line that carries it.

    Waiting on the META file is not waiting for this line. The producer writes the metadata first
    and only then appends `[tautline] finished:` to the log (cli.py), so a test that awaits the
    metadata and immediately reads the log races that gap. It is microseconds on an idle machine
    and wide enough to lose under load -- this test went red exactly once, during a full-suite run
    competing with two other suites, and passed on every isolated rerun.

    Wait for the artifact under assertion rather than a proxy for it.
    """
    end = time.time() + deadline
    last = ""
    while time.time() < end:
        try:
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            lines = []
        if lines:
            last = lines[-1]
            if last.startswith("[tautline] finished:"):
                return last
        time.sleep(0.05)
    raise AssertionError(
        f"terminal marker never appeared in {log_path} within {deadline}s; last line was {last!r}"
    )


def _run(run_cli, tmp_path, *command, extra=()):
    log = tmp_path / "run.log"
    res = run_cli("background-run", "--log", str(log), *extra, "--", *command)
    assert res.returncode == 0, res.stderr
    return log, res


def test_a_receipt_is_bound_to_its_own_run_even_when_a_log_is_shared():
    """Attribution is solved by BINDING the receipt, not by locking the log.

    Nine review rounds went into a hand-rolled O_EXCL + pid + staleness lock meant to stop two runs
    sharing a log, and each round found the next race in it — pid reuse, takeover serialization,
    ownership released a moment too early. That work is filed as its own item, to be built on the
    `advisory_flock`/occupancy-lease primitives this repo already has rather than a fourth
    hand-rolled scheme.

    What makes the RECEIPT correct needs no lock at all: the reaper writes only when the metadata
    still names its own pid, and `monitor-status` ignores a receipt naming a different pid than the
    one asked about. Both are pinned below and neither depends on exclusion.
    """
    # Documented non-guarantee, asserted so it is not mistaken for an oversight: concurrent reuse
    # of one --log path is UNSUPPORTED, and the receipt binding is what keeps it from lying.
