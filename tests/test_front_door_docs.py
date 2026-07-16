"""Front-door documentation promises are test-bound, not prose-bound (plan Task 7,
R2 finding PP-R2-P2-3): the coarse README shape gate cannot fail when a specific
front-door promise is silently skipped, so every promise below is pinned by name.

The shared floor-rationale phrase is asserted byte-identically in BOTH
pyproject.toml and CONTRIBUTING.md so the two rationales cannot drift apart, and
the retired `match`-statement claim (stale: the CLI carries zero match statements
today; the tree parses clean under the 3.8/3.9 grammar via ast feature_version)
must stay gone from both.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
SETUP_RUNTIME = REPO_ROOT / "docs" / "reference" / "operations" / "setup-runtime.md"

# The retired rationale token. Deliberately backtick-wrapped so the plain verb
# "match" (e.g. mypy's "match the declared 3.10 floor" comment) stays legal.
RETIRED_FLOOR_TOKEN = "`match` statement"

# The verified replacement rationale, mechanically established on this tree:
# bin/tautline + src/ parse clean under ast feature_version (3, 9) — no syntax
# forces 3.10 — while zip(strict=) (PEP 618, bin/tautline's survived-sequence
# comparison) is a genuine 3.10-only runtime API, and every CI gate (ruff py310,
# mypy 3.10, the test matrix, and the fresh-install smoke) proves exactly 3.10.
SHARED_FLOOR_RATIONALE = "zip(strict=) is 3.10-only, and CI proves the floor on 3.10 every PR"


def _quickstart_section(text: str) -> str:
    start = text.index("## Quickstart")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_readme_quickstart_names_the_floor_and_cutover():
    """A README-following fresh user must learn the Python floor before cloning and
    must run the launcher cutover the tool itself demands (the unconditional
    next_step_required banner) — the docs finally agree with the tool."""
    quickstart = _quickstart_section(README.read_text(encoding="utf-8"))
    assert "Python 3.10+" in quickstart, "the Quickstart must state the Python 3.10+ prerequisite"
    assert "git" in quickstart.lower(), "the Quickstart prerequisites must name git"
    assert "tautline install-claude-launcher --force" in quickstart, (
        "the MANDATORY launcher cutover step must be in the Quickstart, after install-cli"
    )
    assert quickstart.index("install-cli") < quickstart.index(
        "tautline install-claude-launcher --force"
    ), "the cutover step comes after install-cli, matching the tool's own banner order"


def test_readme_has_pypi_install_subsection():
    """The real PyPI package gets a front-door install path: pipx to install,
    pipx to update, and an honest boundary (no launcher-driven auto-update)."""
    text = README.read_text(encoding="utf-8")
    assert "pipx install tautline" in text
    assert "pipx upgrade tautline" in text
    assert "PyPI" in text, "the subsection must be recognizably the install-from-PyPI path"


def test_floor_rationale_is_truthful():
    """The retired `match`-statement claim is gone from BOTH carriers, and both
    carry the byte-identical verified replacement so they cannot drift apart."""
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    assert RETIRED_FLOOR_TOKEN not in pyproject, (
        "pyproject.toml still carries the stale match-statement floor rationale"
    )
    assert RETIRED_FLOOR_TOKEN not in contributing, (
        "CONTRIBUTING.md still carries the stale match-statement floor rationale"
    )
    assert SHARED_FLOOR_RATIONALE in pyproject, (
        "pyproject.toml must carry the verified floor rationale"
    )
    assert SHARED_FLOOR_RATIONALE in contributing, (
        "CONTRIBUTING.md must carry the same verified floor rationale, byte-identical"
    )


def test_setup_runtime_documents_package_mode():
    """setup-runtime.md documents the installed package as a real install mode:
    the manifest identity that keys package-mode behavior, the update channel,
    and the no-launcher-auto-update boundary."""
    text = SETUP_RUNTIME.read_text(encoding="utf-8")
    assert "installKind" in text, (
        "package mode is keyed on the manifest's installKind; the docs must name it"
    )
    assert "pipx upgrade tautline" in text, "the pipx update channel must be documented"
    assert "pip install -U tautline" in text, "the plain-venv update channel must be documented"
    assert "does not auto-update" in text, (
        "the no-launcher-auto-update boundary must be stated plainly"
    )
