import importlib

util = importlib.import_module("minervit_methodology.util")


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
