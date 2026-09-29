"""Track H: continuity handoffs.

`docs/reference/handoffs.md` and the `/handoff` skill are prose, covered here by content checks.
`lean.handoff_status_line` is the freshness computation `tautline lane-status` prints; it is
covered both as a pure unit (frozen `now`, no CLI, no git) and end to end through `cli.lane_status`
against a real lean git repo, because the pure tests cannot see the sanitization boundary
`cli.lane_status` applies before printing (lean.py never prints; see its own docstring on the
handoff functions).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pytest

from lane_status_fixtures import repo_with_remote
from tautline_methodology import cli, lean

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFFS_DOC = REPO_ROOT / "docs" / "reference" / "handoffs.md"
HANDOFF_SKILL = REPO_ROOT / "plugins" / "tautline-core" / "skills" / "handoff" / "SKILL.md"

TEMPLATE = (
    "# Handoff — <ISO-8601 UTC> — <branch>@<short-sha>\n"
    "## Doing: <goal / queue item>\n"
    "## State: <what is done AND VERIFIED; what is in flight; what is broken>\n"
    "## Next: <the exact next action a fresh session should take>\n"
    "## Gotchas: <anything a fresh session must know: env quirks, decisions in flight, traps>"
)


# --- the doc -------------------------------------------------------------------------------------


def test_handoffs_doc_defines_the_one_file_and_carries_the_template():
    text = HANDOFFS_DOC.read_text(encoding="utf-8")
    assert TEMPLATE in text
    assert ".ai-continuity/HANDOFF.md" in text
    assert "One page max" in text
    assert "Latest wins" in text or "latest wins" in text
    assert '"handoffs": true' in text
    assert "/handoff" in text
    assert "handoff: none" in text
    assert "lane-status" in text


# --- the skill -------------------------------------------------------------------------------------


def test_handoff_skill_is_a_concise_write_and_confirm_entrypoint():
    text = HANDOFF_SKILL.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---"
    assert "name: handoff" in lines
    assert "/handoff" in text
    assert TEMPLATE in text
    assert "docs/reference/handoffs.md" in text
    assert "tautline lane-status" in text
    # The skill writes and confirms; reading the file at session start is the generated
    # adapter's job (Track H item 4), not this skill's -- keep the two norms in their own place.
    assert "session start" not in text.lower()


# --- lean.handoff_status_line: pure, frozen time, no CLI --------------------------------------


def _write_handoff(root: Path, *, doing: str | None = "Building the widget") -> Path:
    path = root / ".ai-continuity" / "HANDOFF.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    doing_line = f"## Doing: {doing}\n" if doing is not None else ""
    path.write_text(
        "# Handoff — 2026-08-28T00:00:00Z — lane@abc1234\n"
        f"{doing_line}"
        "## State: nothing yet\n"
        "## Next: start\n"
        "## Gotchas: none\n",
        encoding="utf-8",
    )
    return path


def _write_lean_adapter(root: Path, *, handoffs: bool | None = None) -> None:
    cfg = {
        "schemaVersion": "lean-1",
        "project": {"name": "Widget Co"},
        "integrationBranch": "main",
        "commands": {"test": "scripts/test.sh"},
    }
    if handoffs is not None:
        cfg["handoffs"] = handoffs
    (root / ".tautline.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_neither_declared_nor_present_is_silent(tmp_path):
    assert lean.handoff_status_line(tmp_path) is None


def test_declared_but_no_file_reports_none(tmp_path):
    _write_lean_adapter(tmp_path, handoffs=True)
    assert lean.handoff_status_line(tmp_path) == "handoff: none"


def test_declared_false_and_no_file_is_still_silent(tmp_path):
    _write_lean_adapter(tmp_path, handoffs=False)
    assert lean.handoff_status_line(tmp_path) is None


def test_a_file_reports_even_without_the_flag(tmp_path):
    """A legacy (1.x) project, or a lean one that never set the flag, still gets the line the
    moment a handoff exists -- the flag only drives the adapter-prose norm, not this line."""
    path = _write_handoff(tmp_path)
    line = lean.handoff_status_line(tmp_path, now=path.stat().st_mtime)
    assert line == "handoff: 0s old — Building the widget"


@pytest.mark.parametrize(
    "elapsed_seconds, expected",
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m"),
        (3599, "59m"),
        (3600, "1h"),
        (86399, "23h"),
        (86400, "1d"),
        (604799, "6d"),
        (604800, "1w"),
        (1_209_600, "2w"),
    ],
)
def test_age_buckets_at_each_unit_boundary(tmp_path, elapsed_seconds, expected):
    path = _write_handoff(tmp_path, doing=None)
    frozen_now = path.stat().st_mtime + elapsed_seconds
    assert lean.handoff_status_line(tmp_path, now=frozen_now) == f"handoff: {expected} old"


def test_a_file_with_no_doing_line_omits_the_suffix(tmp_path):
    path = _write_handoff(tmp_path, doing=None)
    line = lean.handoff_status_line(tmp_path, now=path.stat().st_mtime)
    assert line == "handoff: 0s old"


def test_only_the_first_doing_line_is_used(tmp_path):
    path = tmp_path / ".ai-continuity" / "HANDOFF.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Handoff — t — b@sha\n## Doing: first\n## State: x\n## Doing: second (stale copy)\n",
        encoding="utf-8",
    )
    line = lean.handoff_status_line(tmp_path, now=path.stat().st_mtime)
    assert line == "handoff: 0s old — first"


def _watch_opens(monkeypatch: pytest.MonkeyPatch, watched: Path) -> list[Path]:
    """Record every `Path.open` call resolving to `watched`, without changing behavior for any
    other path. A plain function, not a callable object -- `Path.open` is looked up on the CLASS,
    and only a real function is a descriptor that binds `self` when accessed through an instance."""
    resolved_watched = watched.resolve()
    opened: list[Path] = []
    real_open = Path.open

    def spy_open(self: Path, *args: object, **kwargs: object):
        try:
            hit = self.resolve() == resolved_watched
        except OSError:
            hit = False
        if hit:
            opened.append(Path(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    return opened


def test_a_file_symlinked_outside_the_repo_is_treated_as_absent(tmp_path, monkeypatch):
    """A cloned repo could ship `.ai-continuity/HANDOFF.md` as a symlink to an arbitrary path
    (`~/.ssh/id_rsa`, say). `lane-status` runs on file PRESENCE alone from a SessionStart hook, so
    without this check that path gets stat'd (an existence/mtime oracle) and read (up to 200 chars
    leaked if a `## Doing:`-shaped line lands in the first 8KB)."""
    root = tmp_path / "repo"
    root.mkdir()
    _write_lean_adapter(root, handoffs=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "id_rsa"
    canary.write_text("## Doing: LEAKED SECRET\n", encoding="utf-8")

    link = root / ".ai-continuity" / "HANDOFF.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(canary)

    opened = _watch_opens(monkeypatch, canary)

    assert lean.handoff_status_line(root) == "handoff: none"
    assert opened == []


def test_a_symlinked_parent_directory_outside_the_repo_is_treated_as_absent(tmp_path, monkeypatch):
    """Same class of escape, one level up: `.ai-continuity/` itself is the symlink, to a directory
    outside the repo that holds a real `HANDOFF.md`. `_inside_target` resolves the whole chain, so
    this is caught by that check even though the leaf name is not itself a symlink."""
    root = tmp_path / "repo"
    root.mkdir()
    _write_lean_adapter(root, handoffs=True)
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    canary = outside / "HANDOFF.md"
    canary.write_text("## Doing: LEAKED SECRET\n", encoding="utf-8")

    (root / ".ai-continuity").symlink_to(outside, target_is_directory=True)

    opened = _watch_opens(monkeypatch, canary)

    assert lean.handoff_status_line(root) == "handoff: none"
    assert opened == []


# --- through the real CLI: cli.lane_status against a real lean git repo -----------------------


def _args(lane, *, hook=False, json_mode=False):
    return argparse.Namespace(target=Path(lane), hook=hook, json=json_mode, project=None)


def _lean_lane(tmp_path, *, handoffs: bool | None = None) -> Path:
    lane, _bare = repo_with_remote(tmp_path, version=None, name="lane")
    _write_lean_adapter(lane, handoffs=handoffs)
    # Same convention as `lane_status_fixtures.write_adapter`: the adapter and the ignore file
    # both stay untracked-but-ignored, so `git status --short` sees nothing new and the fixture
    # lane is never DIRTY for reasons unrelated to what each test actually exercises.
    (lane / ".gitignore").write_text(
        ".ai-continuity/\n.tautline.json\n.gitignore\n", encoding="utf-8"
    )
    return lane


@pytest.mark.parametrize("hook_mode", [False, True])
def test_lane_status_prints_the_freshness_line_in_both_modes(tmp_path, capsys, hook_mode):
    lane = _lean_lane(tmp_path, handoffs=True)
    handoff = _write_handoff(lane, doing="Wiring the freshness line")
    # Backdate the file so the printed age is deterministic without freezing global time --
    # `cli.lane_status` calls `time.time()` internally and this test does not own that call.
    stamp = time.time() - 7300  # a little over 2h
    os.utime(handoff, (stamp, stamp))

    assert cli.lane_status(_args(lane, hook=hook_mode)) == 0
    out = capsys.readouterr().out
    assert "handoff: 2h old — Wiring the freshness line" in out


def test_lane_status_reports_none_when_declared_but_unwritten(tmp_path, capsys):
    lane = _lean_lane(tmp_path, handoffs=True)
    cli.lane_status(_args(lane))
    assert "handoff: none" in capsys.readouterr().out


def test_lane_status_carries_no_handoff_text_for_a_project_that_never_opted_in(tmp_path, capsys):
    lane = _lean_lane(tmp_path, handoffs=None)
    cli.lane_status(_args(lane))
    assert "handoff:" not in capsys.readouterr().out


def test_a_forged_control_character_cannot_inject_a_report_line(tmp_path, capsys):
    """`.ai-continuity/HANDOFF.md` is agent-written free text. A raw BEL/escape byte in the Doing
    line could otherwise manipulate a real terminal; every value this report prints goes through
    `lane_status_safe_detail`, which flattens non-printable characters to a single space. (A bare
    `\\r` is neutralized even earlier and is not what this test is about: Python's text-mode read
    applies universal-newline translation, so an embedded `\\r` becomes a line break the
    `## Doing:` regex never crosses, and the text after it is dropped entirely rather than merely
    flattened.)"""
    lane = _lean_lane(tmp_path, handoffs=True)
    handoff = lane / ".ai-continuity" / "HANDOFF.md"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(
        "# Handoff — t — b@sha\n## Doing: real work\x07FAKE VERDICT LINE\n", encoding="utf-8"
    )

    assert cli.lane_status(_args(lane)) == 0
    out = capsys.readouterr().out
    assert "\x07" not in out
    handoff_lines = [line for line in out.splitlines() if "handoff:" in line]
    assert len(handoff_lines) == 1
    assert "real work FAKE VERDICT LINE" in handoff_lines[0]
