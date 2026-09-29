"""Item 69 / WS3: an unexpected render names itself instead of needing diff archaeology.

Diagnosing the 2026-08-03 incident took a diff comparison against upstream main to work out that
*a render had happened at all*, let alone which one. Neither render path emitted an event or a
trigger-naming line; `lane-start` printed bare `wrote <path>` lines indistinguishable from any
other writer.

`trigger` alone would not have answered the question. It is a constant per call site, so every
render reached through `lane-start` reports `"lane-start"` no matter what launched it -- and the
incident was two concurrently launched sessions in SIBLING WORKTREES. The discriminators that
actually separate those two are process and location, so `refs` carries pid, argv0, cwd and the
runtime version alongside the trigger. Paths and ids only: no product narrative goes in an event.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


@pytest.fixture
def rendered_target(tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    # cwd=target deliberately: the observability state dir resolves against the PROCESS cwd, not
    # against --target, so a render driven from elsewhere writes its events beside the caller.
    result = subprocess.run(
        [
            sys.executable, str(CLI_PATH), "render-adapters",
            "--project", str(EXAMPLE_ADAPTER), "--target", str(target), "--write",
        ],
        cwd=str(target), env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return target, env, result


def _hermetic_lane(tmp_path: Path, monkeypatch) -> Path:
    """A lane whose event log is entirely inside tmp_path.

    Two separate reasons, both learned the hard way:

    * the observability state dir follows the PROCESS cwd, not `--target`, so a test that does not
      chdir writes its events beside the caller;
    * the instrumentation seq is allocated under `$HOME/.local/state/tautline/`, so a run whose
      HOME is not writable -- a sandboxed reviewer, a locked-down CI image -- gets a fail-open
      `event_log_warning` and NO event, and the assertion then fails for a reason that has nothing
      to do with what it is testing. `try_write_event` is fail-open by contract, so the test has to
      supply an environment where writing can actually succeed.
    """
    target = tmp_path / "lane"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(target)
    return target


def _events(target: Path) -> list[dict]:
    found: list[dict] = []
    for path in sorted(target.rglob("events.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                found.append(json.loads(line))
    return found


def test_the_explicit_render_names_its_trigger_and_its_process(rendered_target):
    """The EVENT fires on an OVERWRITE, not on a first render.

    Creating these files for the first time -- onboarding, a fresh worktree, every test fixture --
    cannot be the skew this exists to diagnose, and an always-on producer on the shared lane event
    log buries the one record anybody will ever look for. The stdout line still names every render
    that wrote.
    """
    target, env, result = rendered_target

    assert "adapter_render_trigger: render-adapters wrote " in result.stdout
    assert "CLAUDE.md" in result.stdout
    assert not [e for e in _events(target) if e.get("event") == "adapter_render"], (
        "a first render emitted a skew event"
    )

    claude = target / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + "\n<!-- hand edit to be overwritten -->\n",
        encoding="utf-8",
    )
    overwrite = subprocess.run(
        [
            sys.executable, str(CLI_PATH), "render-adapters",
            "--project", str(EXAMPLE_ADAPTER), "--target", str(target), "--write",
        ],
        cwd=str(target), env=env, capture_output=True, text=True, timeout=120,
    )
    assert overwrite.returncode == 0, overwrite.stderr

    renders = [event for event in _events(target) if event.get("event") == "adapter_render"]
    assert renders, "an overwrite of an existing generated file recorded no event"
    refs = renders[-1]["refs"]
    assert refs["trigger"] == "render-adapters"
    assert refs["runtime_version"] == (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    # The fields that make two concurrent sibling-worktree renders distinguishable.
    assert int(refs["pid"]) > 0
    assert refs["argv0"]
    assert refs["cwd"]
    assert "CLAUDE.md" in refs["files"]


def test_a_no_write_render_emits_nothing(rendered_target):
    """A second identical render changes nothing, so it must not narrate a render that did not
    happen -- provenance that fires on every invocation is noise, and noise is what made the
    original `wrote <path>` lines useless."""
    target, env, _first = rendered_target

    second = subprocess.run(
        [
            sys.executable, str(CLI_PATH), "render-adapters",
            "--project", str(EXAMPLE_ADAPTER), "--target", str(target), "--write",
        ],
        cwd=str(target), env=env, capture_output=True, text=True, timeout=120,
    )

    assert second.returncode == 0, second.stderr
    assert "unchanged" in second.stdout
    # The lane adapter is stamp-equivalent so it is skipped; the Markdown files are byte-identical
    # and now skipped too, so nothing was written and nothing is narrated.
    assert "adapter_render_trigger:" not in second.stdout
