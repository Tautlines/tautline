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

util = importlib.import_module("minervit_methodology.util")


def test_the_tautline_alias_points_the_shim(cli):
    assert cli.resolve_real_codex({"TAUTLINE_REAL_CODEX": "/opt/real/codex"}) == "/opt/real/codex"


def test_the_legacy_name_still_works(cli):
    assert cli.resolve_real_codex({"MINERVIT_REAL_CODEX": "/opt/real/codex"}) == "/opt/real/codex"


def test_the_alias_outranks_the_legacy_name(cli):
    env = {
        "MINERVIT_REAL_CODEX": "/opt/legacy/codex",
        "TAUTLINE_REAL_CODEX": "/opt/real/codex",
    }
    assert cli.resolve_real_codex(env) == "/opt/real/codex"


def test_a_blank_alias_does_not_shadow_the_legacy_name(cli):
    env = {"MINERVIT_REAL_CODEX": "/opt/legacy/codex", "TAUTLINE_REAL_CODEX": "   "}
    assert cli.resolve_real_codex(env) == "/opt/legacy/codex"


def test_neither_set_falls_back_to_path(cli, tmp_path):
    shim = tmp_path / "codex"
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o755)
    assert cli.resolve_real_codex({"PATH": str(tmp_path)}) == str(shim)


def test_the_passed_mapping_is_read_not_the_process_environment(cli, monkeypatch):
    """The mapping is the argument, not os.environ.

    Callers inject a base_env and rely on it being the thing that is read.
    """
    monkeypatch.setenv("TAUTLINE_REAL_CODEX", "/opt/ambient/codex")
    env = {"MINERVIT_REAL_CODEX": "/opt/passed/codex"}
    assert cli.resolve_real_codex(env) == "/opt/passed/codex"


def test_resolve_env_reads_the_mapping_it_is_given(monkeypatch):
    monkeypatch.delenv("TAUTLINE_THING", raising=False)
    monkeypatch.delenv("MINERVIT_THING", raising=False)
    assert util.resolve_env("MINERVIT_THING", environ={"TAUTLINE_THING": "aliased"}) == "aliased"
    assert util.resolve_env("MINERVIT_THING", environ={"MINERVIT_THING": "legacy"}) == "legacy"
    assert util.resolve_env("MINERVIT_THING", "fb", environ={}) == "fb"


def test_resolve_env_still_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("TAUTLINE_THING", "ambient")
    assert util.resolve_env("MINERVIT_THING") == "ambient"
