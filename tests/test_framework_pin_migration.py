"""Framework pin file rebrand (deminervit 2A PR2): the framework channel pin migrates from the
legacy `.minervit/pin.json` to `.tautline/pin.json`, mirroring the adapter-dir move. New pins are
written to the tautline path; a pre-existing legacy pin is still read and is migrated on read. The
legacy read-fallback is removed only at METH-FU-TAUTLINE-FALLBACK-REMOVAL.
"""

import json
from pathlib import Path


def _write_pin(path: Path, channel: str = "experimental") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"channel": channel}) + "\n", encoding="utf-8")


def test_pin_writes_to_tautline_dir(cli, tmp_path):
    # The canonical pin path (the write target for set-framework-channel/update-repin) is the
    # tautline dir, not the legacy .minervit dir.
    assert cli.framework_pin_path(tmp_path) == tmp_path / ".tautline" / "pin.json"
    assert cli.FRAMEWORK_PIN_FILE == ".tautline/pin.json"
    assert cli.LEGACY_FRAMEWORK_PIN_FILE == ".minervit/pin.json"


def test_legacy_pin_is_still_read(cli, tmp_path):
    # A lane that only has the legacy .minervit/pin.json (never re-pinned since the rename) must
    # still resolve its channel.
    _write_pin(tmp_path / ".minervit" / "pin.json", channel="experimental")
    assert not (tmp_path / ".tautline" / "pin.json").exists()
    pin = cli.load_framework_pin_file(tmp_path)
    assert pin is not None
    assert pin["channel"] == "experimental"


def test_legacy_pin_is_migrated_on_read(cli, tmp_path):
    # Reading a legacy-only pin materializes the canonical .tautline/pin.json (one-time migration),
    # byte-for-byte from the legacy file.
    legacy = tmp_path / ".minervit" / "pin.json"
    _write_pin(legacy, channel="experimental")
    cli.load_framework_pin_file(tmp_path)
    tautline = tmp_path / ".tautline" / "pin.json"
    assert tautline.exists()
    assert tautline.read_text(encoding="utf-8") == legacy.read_text(encoding="utf-8")


def test_invalid_legacy_pin_is_not_migrated(cli, tmp_path):
    # A legacy pin that is valid JSON but has an invalid field must NOT be copied onto the canonical
    # path before validation -- otherwise the bad canonical copy would win every future read and
    # hide a later fix to the legacy file (Codex 2A-PR2 R1 P2).
    legacy = tmp_path / ".minervit" / "pin.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"channel": "bogus"}) + "\n", encoding="utf-8")
    import pytest

    with pytest.raises(SystemExit):
        cli.load_framework_pin_file(tmp_path)
    assert not (tmp_path / ".tautline" / "pin.json").exists()


def test_tautline_pin_wins_over_legacy(cli, tmp_path):
    _write_pin(tmp_path / ".minervit" / "pin.json", channel="stable")
    _write_pin(tmp_path / ".tautline" / "pin.json", channel="experimental")
    pin = cli.load_framework_pin_file(tmp_path)
    assert pin["channel"] == "experimental"
    _, source = cli.effective_framework_pin({}, tmp_path)
    assert source == ".tautline/pin.json"
