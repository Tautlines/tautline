import importlib

util = importlib.import_module("tautline_methodology.util")


def test_tautline_prefix_takes_precedence(monkeypatch):
    monkeypatch.setenv("TAUTLINE_GITHUB_RATE_GUARD", "taut")
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "taut"


def test_minervit_name_still_honored(monkeypatch):
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "minv"


def test_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("TAUTLINE_X", raising=False)
    monkeypatch.delenv("MINERVIT_X", raising=False)
    assert util.resolve_env("MINERVIT_X", "fallback") == "fallback"


def test_non_minervit_name_read_directly(monkeypatch):
    monkeypatch.setenv("PLAIN_VAR", "v")
    assert util.resolve_env("PLAIN_VAR") == "v"


def test_minervit_env_emits_deprecation_warning(monkeypatch, capsys):
    # A value present only under a MINERVIT_ name still resolves, and the deprecation clock (unified
    # onto the shared compat-sunset renderer) emits a once-only stderr line in the fixed shape.
    util._reset_sunset_state()
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "minv"
    err = capsys.readouterr().err
    assert "MINERVIT_GITHUB_RATE_GUARD" in err
    assert "TAUTLINE_GITHUB_RATE_GUARD" in err
    assert "deprecated" in err.lower()
    assert "removed in 1.0" in err
    assert err.strip() == util._sunset_line(
        "MINERVIT_GITHUB_RATE_GUARD", "TAUTLINE_GITHUB_RATE_GUARD"
    )


def test_minervit_env_warning_is_deduped_per_process(monkeypatch, capsys):
    util._reset_sunset_state()
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    for _ in range(3):
        util.resolve_env("MINERVIT_GITHUB_RATE_GUARD")
    err = capsys.readouterr().err
    assert err.count("MINERVIT_GITHUB_RATE_GUARD") == 1


def test_tautline_alias_present_emits_no_warning(monkeypatch, capsys):
    util._reset_sunset_state()
    monkeypatch.setenv("TAUTLINE_GITHUB_RATE_GUARD", "taut")
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "taut"
    assert capsys.readouterr().err == ""


def test_minervit_warning_scoped_to_process_env(monkeypatch, capsys):
    # Internal child-env assembly passes an explicit `environ`; that plumbing must not warn.
    util._reset_sunset_state()
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD", environ={"MINERVIT_GITHUB_RATE_GUARD": "minv"}) == "minv"
    assert capsys.readouterr().err == ""
