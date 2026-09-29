"""Every shipped package module is in the release artifact registry.

`RELEASE_ARTIFACT_PATHS` is hand-maintained and feeds two things:

* the `cut-release` checksums manifest -- the integrity record of what a release distributes; and
* `HARD_EXCLUDED_FILES`, the set that may never classify as a product-management surface, which is
  what stops a broad adapter glob laundering framework code through the PM whole-diff version-bump
  exemption.

A module missing from it is therefore not merely unlisted. It is **omitted from the integrity
manifest a verifier checks**, so the manifest attests to a subset while presenting itself as the
whole -- and it becomes eligible for a PM classification that skips the version bump.

Found by review while adding `occupancy.py`, and the list had already drifted four times over:
`core/runtime.py` (which the W1 carve moved 391 symbols into at 0.41.0), `goal_assignment.py`,
`merge_gate.py`, and `test_evidence.py` were all absent. Nothing was checking, because the only
thing that could have caught it was a human reading a 35-line literal.

The registry is deliberately still explicit rather than globbed -- a release manifest built by
walking the filesystem would happily checksum whatever happened to be lying in the tree. This test
is the other half of that trade: the list stays hand-written, and drifting from reality fails.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "tautline_methodology"
CLI_PATH = PACKAGE_DIR / "cli.py"


def _registered_paths() -> set[str]:
    """`RELEASE_ARTIFACT_PATHS` read from the source by AST, not by importing the CLI."""
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "RELEASE_ARTIFACT_PATHS" not in targets:
            continue
        assert isinstance(node.value, ast.List), "RELEASE_ARTIFACT_PATHS must stay a list literal"
        return {
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    raise AssertionError("RELEASE_ARTIFACT_PATHS not found in cli.py")


def _shipped_modules() -> set[str]:
    return {
        str(path.relative_to(REPO_ROOT))
        for path in PACKAGE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def test_every_shipped_package_module_is_a_registered_release_artifact():
    missing = sorted(_shipped_modules() - _registered_paths())
    assert not missing, (
        "package modules absent from RELEASE_ARTIFACT_PATHS -- cut-release would checksum a "
        "release that does not include them, and HARD_EXCLUDED_FILES would not protect them from "
        f"a PM-surface classification: {missing}"
    )


def test_every_registered_artifact_exists():
    """The other direction: a rename or deletion must fail here, not at `cut-release` time."""
    absent = sorted(rel for rel in _registered_paths() if not (REPO_ROOT / rel).exists())
    assert not absent, f"registered release artifacts missing from the tree: {absent}"


def test_the_registry_is_not_vacuous():
    """A rewrite that returns an empty set would make both assertions above pass silently.

    The floor moved from 30 to 20 in the 2026-08-28 process-bankruptcy demolition, which deleted 29
    of the shipped modules outright. The number is a NON-VACUITY floor, not a target: its only job
    is to fail if the discovery ever collapses to nothing, so it tracks the real module count from
    below rather than pinning it.
    """
    registered = _registered_paths()
    assert len(registered) >= 20
    assert "bin/tautline" in registered
    assert "src/tautline_methodology/cli.py" in registered
    assert len(_shipped_modules()) >= 20
