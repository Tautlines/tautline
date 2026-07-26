"""Dispatch-map neutrality golden.

Help output alone cannot prove dispatch neutrality: a registrar could wire a verb
to the wrong ``set_defaults(func=...)`` while ``--help`` stays byte-identical. This
golden closes that gap -- ``tests/data/dispatch_map.json`` pins every
``(verb, handler)`` pair a fresh AST pass finds, so mis-wiring turns the map RED
even when the help corpus is unchanged.

Regeneration is a conscious act gated behind ``TAUTLINE_REGEN_HELP_CORPUS=1`` (see
``test_cli_help_corpus`` -- one knob regenerates both goldens together).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _ast_inventory import build_dispatch_map

GOLDEN = Path(__file__).resolve().parent / "data" / "dispatch_map.json"


def _assert_dispatch_matches(fresh: dict[str, str | None], committed: object) -> None:
    """The one equality the dispatch ratchet rides on.

    Both the real golden test AND ``test_dispatch_swap_is_detected`` call this helper,
    so neutering the ``==`` check here reddens the meta-test too.
    """
    assert fresh == committed


def test_dispatch_map_matches_golden():
    """A fresh AST pass must equal the committed golden, exactly."""
    committed = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _assert_dispatch_matches(build_dispatch_map(), committed)


def test_dispatch_map_has_no_hardcoded_count():
    """The golden stores no count field -- the count is len(map), AST-derived."""
    committed = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(committed, dict)
    # Every value is a handler name (str) or, only if the AST truly finds one, null.
    assert all(v is None or isinstance(v, str) for v in committed.values())


def test_dispatch_swap_is_detected():
    """Ratchet proof: the SAME equality the real golden rides on must bite when one
    handler is mis-wired -- so neutering that comparison reddens this test too.

    Mutates an in-memory copy (never the committed file), then asserts the real
    ``_assert_dispatch_matches`` helper raises on the swap the help corpus cannot see.
    """
    fresh = build_dispatch_map()
    committed = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _assert_dispatch_matches(fresh, committed)  # baseline: the real comparison accepts truth
    victim = next(iter(committed))
    swapped = dict(committed)
    swapped[victim] = f"{committed[victim]}__drift"  # a guaranteed handler mis-wiring
    with pytest.raises(AssertionError):
        _assert_dispatch_matches(fresh, swapped)
