"""Documented CLI flags must actually exist on the CLI.

The release-engineering reference told operators to run `release-tail --resume`.
No such flag was ever implemented — resuming is the default, needs no flag — so
following the documented bootstrap would have died with "unrecognized argument"
at the exact step that publishes the release. The docs were reviewed, the code
was reviewed, and nobody diffed one against the other.

The first version of this guard only scanned the operations docs — and the *same
phantom flag* survived in the CHANGELOG and the release migration record, which it
did not look at. A guard whose scope is narrower than the bug class is not a guard.
So it now covers every surface where a `tautline <command> --flag` is shown to a
reader: the operations docs, the CHANGELOG, and the release migration records.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "bin" / "tautline"
DOCS = [
    *sorted((REPO_ROOT / "docs" / "reference" / "operations").glob("*.md")),
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "README.md",
    *sorted((REPO_ROOT / "docs" / "releases" / "migrations").glob("*.json")),
]

# `tautline <command> ... --flag` as it appears in a fenced command line.
INVOCATION = re.compile(r"\btautline\s+([a-z][a-z0-9-]+)((?:\s+--?[a-zA-Z0-9-]+(?:[= ][^\s`]+)?)*)")
FLAG = re.compile(r"(?<![\w-])(--[a-zA-Z][a-zA-Z0-9-]*)")


def _documented_flags() -> dict[tuple[str, str], list[Path]]:
    """Map (command, flag) -> the docs that reference it."""
    found: dict[tuple[str, str], list[Path]] = {}
    for doc in DOCS:
        for command, tail in INVOCATION.findall(doc.read_text(encoding="utf-8")):
            for flag in FLAG.findall(tail):
                found.setdefault((command, flag), []).append(doc)
    return found


def _accepted_flags(command: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return set(FLAG.findall(result.stdout))


DOCUMENTED = _documented_flags()


def test_docs_reference_some_flags() -> None:
    assert DOCUMENTED, "no documented tautline invocations found; this guard would vacuously pass"


@pytest.mark.parametrize(
    ("command", "flag"),
    sorted(DOCUMENTED),
    ids=lambda value: str(value),
)
def test_documented_flag_exists(command: str, flag: str) -> None:
    accepted = _accepted_flags(command)
    if not accepted:
        pytest.skip(f"`tautline {command}` is not a CLI subcommand (prose, not an invocation)")
    where = ", ".join(str(doc.relative_to(REPO_ROOT)) for doc in DOCUMENTED[(command, flag)])
    assert flag in accepted, (
        f"{where} documents `tautline {command} {flag}`, but that command does not accept "
        f"{flag}. An operator following the docs gets 'unrecognized argument'. "
        "Fix the doc or add the flag."
    )
