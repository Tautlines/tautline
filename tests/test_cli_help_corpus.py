"""Golden ``--help`` corpus -- the primary behavior-neutrality ratchet.

Captures the root parser's help and every subcommand's ``<verb> --help`` under a
FIXED terminal width and compares byte-for-byte against committed goldens in
``tests/data/help_corpus/``. Because argparse wraps to ``COLUMNS`` (124/160 helps
are width-sensitive), the capture pins ``COLUMNS=80`` explicitly rather than relying
on its ambient absence -- a CI runner that exported ``COLUMNS`` would otherwise
reshape every wrapped help and break the golden.

The enumeration is the AST inventory (``_ast_inventory``), never a hardcoded list,
and a cross-check ties it to argparse's own ``{...}`` choices block plus the golden
filenames. One knob -- ``TAUTLINE_REGEN_HELP_CORPUS=1`` -- regenerates BOTH this
corpus and the dispatch-map golden together and prunes orphans, so drift is always
a conscious act. ``scripts/test.sh`` never sets the knob, so it only ever verifies.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from _ast_inventory import CLI_PATH, build_dispatch_map, verb_inventory

DATA_DIR = Path(__file__).resolve().parent / "data"
CORPUS_DIR = DATA_DIR / "help_corpus"
DISPATCH_GOLDEN = DATA_DIR / "dispatch_map.json"
ROOT_STEM = "__root__"

# Hermetic, width-pinned environment. Help output is HOME/cwd-invariant and exits 0,
# so any existing HOME works; COLUMNS is the load-bearing knob and must be explicit.
_HOME = Path(tempfile.mkdtemp(prefix="help_corpus_home_"))
_ENV = {"PATH": os.environ["PATH"], "HOME": str(_HOME), "COLUMNS": "80", "LINES": "24"}


def _capture(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env=_ENV,
        cwd=str(_HOME),
        text=True,
        capture_output=True,
        timeout=60,
    )


def _golden_path(stem: str) -> Path:
    return CORPUS_DIR / f"{stem}.txt"


def _root_choices(root_help: str) -> list[str]:
    """Reassemble argparse's wrapped ``{v1,v2,...}`` subcommand-choices metavar."""
    start = root_help.index("{")
    depth = 0
    for offset, char in enumerate(root_help[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                inner = root_help[start + 1 : offset]
                return [tok for tok in "".join(inner.split()).split(",") if tok]
    raise AssertionError("unbalanced choices metavar in root help")


def regenerate_goldens() -> None:
    """Rewrite BOTH goldens from the CURRENT parser. Gated behind the env knob."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    DISPATCH_GOLDEN.write_text(
        json.dumps(build_dispatch_map(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verbs = verb_inventory()
    _golden_path(ROOT_STEM).write_text(_capture("--help").stdout, encoding="utf-8")
    for verb in verbs:
        _golden_path(verb).write_text(_capture(verb, "--help").stdout, encoding="utf-8")
    keep = {ROOT_STEM, *verbs}
    for stale in CORPUS_DIR.glob("*.txt"):
        if stale.stem not in keep:
            stale.unlink()


if os.environ.get("TAUTLINE_REGEN_HELP_CORPUS") == "1":
    regenerate_goldens()


VERBS = verb_inventory()


def _assert_help_matches(result: subprocess.CompletedProcess, golden_text: str) -> None:
    """The one byte-for-byte comparison the whole corpus rides on.

    Both real golden tests AND the ``test_help_edit_is_detected`` ratchet-proof call
    this helper, so neutering the ``stdout ==`` check here reddens the meta-test too.
    """
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == golden_text


def test_root_help_matches_golden():
    _assert_help_matches(_capture("--help"), _golden_path(ROOT_STEM).read_text(encoding="utf-8"))


@pytest.mark.parametrize("verb", VERBS, ids=lambda v: v)
def test_verb_help_matches_golden(verb: str) -> None:
    """The per-verb goldens, content-compared -- not just the root.

    `test_enumeration_agrees_across_ast_argparse_and_goldens` below proves every verb HAS a
    golden file; it does not read what is IN one. Without this, a verb's own `--help` text (a
    flag's help string, say) could drift from its committed golden with nothing in this suite
    catching it -- which is exactly how `init.txt` shipped stale once, silently, until read by
    hand rather than by a test.
    """
    _assert_help_matches(_capture(verb, "--help"), _golden_path(verb).read_text(encoding="utf-8"))


def test_enumeration_agrees_across_ast_argparse_and_goldens():
    """Tie the AST verb list to argparse's own choices block and the golden files."""
    ast_verbs = set(VERBS)
    root_help = _golden_path(ROOT_STEM).read_text(encoding="utf-8")
    assert set(_root_choices(root_help)) == ast_verbs
    golden_stems = {p.stem for p in CORPUS_DIR.glob("*.txt")} - {ROOT_STEM}
    assert golden_stems == ast_verbs


def test_help_edit_is_detected():
    """Ratchet proof: the SAME comparison the real corpus rides on must bite on a
    one-character golden edit -- so neutering that comparison reddens this test too.

    Mutates the golden in memory (never the committed file), then asserts the real
    ``_assert_help_matches`` helper raises on the drift it must never silently accept.
    """
    result = _capture("version", "--help")
    golden = _golden_path("version").read_text(encoding="utf-8")
    _assert_help_matches(result, golden)  # baseline: the real comparison accepts truth
    flip = "#" if golden[0] != "#" else "@"
    mutated = flip + golden[1:]  # a guaranteed one-character edit of the golden
    with pytest.raises(AssertionError):
        _assert_help_matches(result, mutated)
