"""arch-errors-5 (productization): write_text_atomic writes through a temp file + atomic rename, so a
crash mid-write never leaves a truncated generated file (which would wedge the next lane start). On
failure the temp file is cleaned up and the destination is left untouched.
"""

import pytest


def test_atomic_write_creates_file(cli, tmp_path):
    dest = tmp_path / "sub" / "CLAUDE.md"
    cli.write_text_atomic(dest, "hello")
    assert dest.read_text() == "hello"


def test_atomic_write_replaces_existing(cli, tmp_path):
    dest = tmp_path / "AGENTS.md"
    dest.write_text("old")
    cli.write_text_atomic(dest, "new content")
    assert dest.read_text() == "new content"


def test_atomic_write_leaves_no_temp_files(cli, tmp_path):
    dest = tmp_path / "f.md"
    cli.write_text_atomic(dest, "x")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "f.md"]
    assert leftovers == [], f"atomic write left temp files: {leftovers}"


def test_failed_write_preserves_original_and_cleans_temp(cli, tmp_path, monkeypatch):
    dest = tmp_path / "f.md"
    dest.write_text("original")

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cli.os, "replace", boom)
    with pytest.raises(RuntimeError):
        cli.write_text_atomic(dest, "partial")
    assert dest.read_text() == "original", "destination must be untouched on failure"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "f.md"]
    assert leftovers == [], f"failed atomic write left temp files: {leftovers}"
