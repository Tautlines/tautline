"""MINERVIT_REAL_CODEX must be readable by its TAUTLINE_ alias, like every other managed setting.

Found by the rewritten env-read guard (tests/test_env_reads_use_resolver.py), which the previous
version of this branch left blind to the mapping: resolve_real_codex reads its key out of a dict
that codex_fast_mode_env builds as `dict(base_env or os.environ)` -- the process environment by
another name -- so the read never went through resolve_env and the TAUTLINE_ spelling was dead.

An operator who sets TAUTLINE_REAL_CODEX (the documented, rebranded name) got no fast-mode shim and
no error: the setting was simply ignored, and `codex` was resolved off PATH instead. That is the
half-applied rebrand the resolver exists to prevent, in the one place a shim gets pointed at a
binary.
"""
import importlib

util = importlib.import_module("tautline_methodology.util")


def test_resolve_env_reads_the_mapping_it_is_given(monkeypatch):
    monkeypatch.delenv("TAUTLINE_THING", raising=False)
    monkeypatch.delenv("MINERVIT_THING", raising=False)
    assert util.resolve_env("MINERVIT_THING", environ={"TAUTLINE_THING": "aliased"}) == "aliased"
    assert util.resolve_env("MINERVIT_THING", environ={"MINERVIT_THING": "legacy"}) == "legacy"
    assert util.resolve_env("MINERVIT_THING", "fb", environ={}) == "fb"


def test_resolve_env_still_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("TAUTLINE_THING", "ambient")
    assert util.resolve_env("MINERVIT_THING") == "ambient"
