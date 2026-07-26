"""Per-lane journal of canonical-repo mutations (Track B, task B2).

Concurrent lanes all drive sync against one canonical checkout. When a lane finds the checkout
in an unexpected state, the only way to attribute the write is a durable record of who wrote
what, when. The journal is forensics, not control flow: it is best-effort by construction and
must never turn a working sync into a failed one.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"
# Post the package-split flip (roadmap #11) the engine lives in the package; bin/tautline is a
# thin shim. Load the engine module directly for the fresh-per-test in-process fixture.
CLI_ENGINE_PATH = CLI_PATH.parents[1] / "src" / "tautline_methodology" / "cli.py"

ENTRY_KEYS = {
    "schema",
    "ts",
    "lane_id",
    "pid",
    "command",
    "old_head",
    "new_head",
    "outcome",
    "detail",
}


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    """A fresh CLI module per test with a hermetic HOME (the journal and the lane-id salt both
    live under HOME, and the module bakes HOME-derived constants at import time, so conftest's
    session-scoped `cli` cannot be reused here). SourceFileLoader gives a fresh engine module
    (cli.py) per call, independent of the import cache."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    loader = importlib.machinery.SourceFileLoader("tautline_cli", str(CLI_ENGINE_PATH))
    spec = importlib.util.spec_from_loader("tautline_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _entries(cli) -> list[dict]:
    text = cli.methodology_write_journal_path().read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_journal_path_lives_under_home_state(cli, tmp_path):
    expected = tmp_path / "home" / ".local" / "state" / "minervit" / "methodology-writes.jsonl"
    assert cli.methodology_write_journal_path() == expected


def test_journal_appends_schema_complete_entry(cli):
    cli.append_methodology_write_journal(
        "sync-methodology.ff-advance", "a" * 40, "b" * 40, "ok", detail="test"
    )
    entry = _entries(cli)[-1]
    assert entry["schema"] == "tautline-methodology-write/v1"
    assert entry["schema"] == cli.METHODOLOGY_WRITE_JOURNAL_SCHEMA
    assert set(entry) == ENTRY_KEYS
    assert re.fullmatch(r"[0-9a-f]{16}", entry["lane_id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["ts"])
    assert entry["pid"] == os.getpid()
    assert entry["command"] == "sync-methodology.ff-advance"
    assert entry["old_head"] == "a" * 40
    assert entry["new_head"] == "b" * 40
    assert entry["outcome"] == "ok"
    assert entry["detail"] == "test"


def test_journal_appends_in_order_without_truncating(cli):
    cli.append_methodology_write_journal("first", "a" * 40, "a" * 40, "skipped")
    cli.append_methodology_write_journal("second", "a" * 40, "b" * 40, "ok")
    entries = _entries(cli)
    assert [entry["command"] for entry in entries] == ["first", "second"]
    assert entries[0]["detail"] == ""  # detail defaults to empty, never missing


def test_journal_lane_defaults_to_cwd_and_honors_override(cli, tmp_path):
    other_lane = tmp_path / "other-lane"
    other_lane.mkdir()
    cli.append_methodology_write_journal("cwd-lane", "a" * 40, "a" * 40, "ok")
    cli.append_methodology_write_journal("named-lane", "a" * 40, "a" * 40, "ok", lane=other_lane)
    entries = _entries(cli)
    assert entries[0]["lane_id"] == cli.instrumentation_lane_id(Path.cwd())
    assert entries[1]["lane_id"] == cli.instrumentation_lane_id(other_lane)
    assert entries[0]["lane_id"] != entries[1]["lane_id"]


def test_journal_never_raises_on_unwritable_dir(cli, tmp_path):
    state = cli.methodology_write_journal_path().parent
    state.mkdir(parents=True)
    state.chmod(0o500)
    try:
        cli.append_methodology_write_journal("x", "h", "h", "failed")  # must not raise
        assert not cli.methodology_write_journal_path().exists()
    finally:
        state.chmod(0o755)


def test_journal_never_raises_when_lane_id_fails(cli, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(cli, "instrumentation_lane_id", _boom)
    cli.append_methodology_write_journal("x", "h", "h", "ok")  # must not raise
    assert not cli.methodology_write_journal_path().exists()


def test_journal_rotates_past_size_cap(cli):
    path = cli.methodology_write_journal_path()
    path.parent.mkdir(parents=True)
    path.write_text("x" * (cli.METHODOLOGY_WRITE_JOURNAL_MAX_BYTES + 1), encoding="utf-8")
    cli.append_methodology_write_journal("y", "h", "h", "ok")
    rotated = path.with_suffix(".jsonl.1")
    assert rotated.exists()
    assert rotated.stat().st_size == cli.METHODOLOGY_WRITE_JOURNAL_MAX_BYTES + 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert _entries(cli)[0]["command"] == "y"


def test_journal_does_not_rotate_below_size_cap(cli):
    cli.append_methodology_write_journal("first", "h", "h", "ok")
    cli.append_methodology_write_journal("second", "h", "h", "ok")
    assert not cli.methodology_write_journal_path().with_suffix(".jsonl.1").exists()
    assert len(_entries(cli)) == 2


# --- the journal records what happened, not what was about to be attempted ---------------------
#
# The journal's whole premise is a TRUTHFUL per-lane record of canonical mutations. `update-repin`
# advances the trust allowlist -- the set of upstream commits this machine will execute -- so an
# entry claiming a repin that never landed is the single most misleading line the file can carry:
# it is read to answer "who moved this machine's trust, and to what?".

OLD_HEAD = "a" * 40
NEW_HEAD = "b" * 40


def _pin_line(cli, head: str) -> str:
    return f"export {cli.METHODOLOGY_UPDATE_PINS_ENV}={head}"


@pytest.fixture()
def repin(cli, monkeypatch, tmp_path):
    """A repin whose git is stubbed out: only the ORDER of write-vs-journal is under test."""
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(cli, "run_git", lambda *a, **k: NEW_HEAD)
    config_env = tmp_path / "config" / "tautline.env"
    config_env.parent.mkdir(parents=True)
    config_env.write_text(_pin_line(cli, OLD_HEAD) + "\n", encoding="utf-8")
    return config_env


def test_repin_journals_ok_only_after_the_write_lands(cli, repin, tmp_path):
    previous, new_head, _range = cli.repin_methodology_update(tmp_path / "repo", repin, "stable")

    assert (previous, new_head) == (OLD_HEAD, NEW_HEAD)
    assert _pin_line(cli, NEW_HEAD) in repin.read_text(encoding="utf-8")
    entry = [e for e in _entries(cli) if e["command"] == "update-repin"][-1]
    assert entry["outcome"] == "ok"
    assert entry["new_head"] == NEW_HEAD


def test_repin_journals_failure_when_the_config_rewrite_fails(cli, repin, monkeypatch, tmp_path):
    """The rewrite can still fail -- it is a real write to a real file on disk. Journaling `ok`
    before it means the forensic record claims a repin that never happened."""
    def _boom(*_args, **_kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(cli, "_rewrite_config_env_export", _boom)

    with pytest.raises(SystemExit):
        cli.repin_methodology_update(tmp_path / "repo", repin, "stable")

    # The allowlist is untouched: the machine still trusts only what it trusted before.
    assert _pin_line(cli, OLD_HEAD) in repin.read_text(encoding="utf-8")
    entries = [e for e in _entries(cli) if e["command"] == "update-repin"]
    assert [e["outcome"] for e in entries] == ["failed"], entries
