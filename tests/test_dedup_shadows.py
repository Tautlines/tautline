"""arch-cli-6 (productization): two top-level defs were shadowed (slugify, path_is_under), forcing
F811/no-redef suppressions in pyproject.toml. The live impls (the second def of each) are kept;
this pins their behavior so the dead-shadow deletion is provably no-change.
"""

from pathlib import Path

from tautline_methodology import util


def test_slugify_basic_and_fallback(cli):
    assert cli.slugify("Hello World!") == "hello-world"
    assert cli.slugify("", fallback="lane") == "lane"
    assert cli.slugify("   ", fallback="event") == "event"
    # default fallback is 'lane' (the live two-arg impl)
    assert cli.slugify("") == "lane"


def test_slugify_long_input_is_bounded_and_stable(cli):
    long_a = "x" * 500
    long_b = "y" * 500
    sa = cli.slugify(long_a, "plan")
    sb = cli.slugify(long_b, "plan")
    # SLUG_MAX_LENGTH moved to the package with slugify (0.6.204); a bin-side
    # copy would be a drift-prone decoy.
    assert len(sa) <= util.SLUG_MAX_LENGTH
    assert sa != sb  # digest keeps distinct long inputs distinct
    assert cli.slugify(long_a, "plan") == sa  # deterministic


def test_path_is_under(cli, tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    assert cli.path_is_under(root / "sub" / "f.txt", root) is True
    assert cli.path_is_under(tmp_path / "other", root) is False


def test_no_duplicate_top_level_defs():
    """The shadowed defs are gone: each name is defined exactly once at module top level.

    Post the package-split flip (roadmap #11) the engine (and these defs) live in cli.py;
    bin/tautline is a thin shim, so scan the engine module."""
    engine = Path(__file__).resolve().parents[1] / "src" / "tautline_methodology" / "cli.py"
    text = engine.read_text()
    assert text.count("\ndef slugify(") == 1
    assert text.count("\ndef path_is_under(") == 1
