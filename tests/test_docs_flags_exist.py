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
# TWO CLASSES, and the split is the point.
#
# INSTRUCTIONAL docs tell an operator what to run today: every command they name must exist and
# accept the flags they show. HISTORICAL records -- the changelog, the frozen migration reports,
# anything under docs/archive/ -- describe what PAST releases did. A changelog entry naming a
# retired verb is correct, and "fixing" it would falsify the record, so those are checked only for
# commands that still exist.
#
# Before the 2026-08-28 demolition this file had one list and skipped whenever `tautline <cmd>
# --help` exited non-zero -- which is exactly what a DELETED command does. The guard that exists to
# catch "an operator following the docs gets 'unrecognized argument'" was therefore silent on
# precisely that case: 89 documented invocations turned into skips overnight without one failure.
INSTRUCTIONAL_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CONTRIBUTING.md",
    *sorted((REPO_ROOT / "docs" / "reference").glob("*.md")),
]
HISTORICAL_DOCS = [
    REPO_ROOT / "CHANGELOG.md",
    *sorted((REPO_ROOT / "docs" / "releases" / "migrations").glob("*.json")),
]
# docs/archive/ is NOT in either list, and that is a discovery decision rather than a checking one.
# Everything under it is a superseded plan or a retired manual -- a record of what a past release
# did, which no operator is meant to follow. Scanning it produced pairs that could only ever be
# skipped, and the blanket skip that silenced them also silenced 28 real checks against the
# changelog and the migration reports. Excluded here so the skip below can be narrow.
ARCHIVE_ROOT = REPO_ROOT / "docs" / "archive"
DOCS = [*INSTRUCTIONAL_DOCS, *HISTORICAL_DOCS]

# `tautline <command> ... --flag` as it appears in a fenced command line.
INVOCATION = re.compile(r"\btautline\s+([a-z][a-z0-9-]+)((?:\s+--?[a-zA-Z0-9-]+(?:[= ][^\s`]+)?)*)")
FLAG = re.compile(r"(?<![\w-])(--[a-zA-Z][a-zA-Z0-9-]*)")


def _documented_flags() -> dict[tuple[str, str], list[Path]]:
    """Map (command, flag) -> the docs that reference it."""
    found: dict[tuple[str, str], list[Path]] = {}
    for doc in DOCS:
        if not doc.is_file():
            continue
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


# The commands the CLI actually registers. Computed ONCE, and the reason this exists as its own
# lookup is the failure it replaced: the parametrized test below used to `pytest.skip` whenever
# `tautline <cmd> --help` exited non-zero -- which is *precisely* what a DELETED command does. The
# guard that exists to catch "an operator following the docs gets 'unrecognized argument'" was
# therefore silent on exactly that case, and the 2026-08-28 demolition turned 89 documented
# invocations into skips overnight without a single failure. A command that is not registered is
# now a failure, not a skip.
REGISTERED = frozenset(
    subprocess.run(
        [sys.executable, str(CLI), "--help"],
        capture_output=True, text=True, check=False,
    ).stdout.partition("{")[2].partition("}")[0].split(",")
)


def test_the_registered_command_list_was_actually_read() -> None:
    """The lookup above is parsed out of `--help`; an empty parse would make every case below
    fail for the wrong reason, and a full-of-junk one would make them pass."""
    assert "version" in REGISTERED and "render-adapters" in REGISTERED
    assert len(REGISTERED) < 60, "the registered-command parse picked up more than a verb list"


@pytest.mark.parametrize(
    ("command", "flag"),
    sorted(DOCUMENTED),
    ids=lambda value: str(value),
)
def test_documented_flag_exists(command: str, flag: str) -> None:
    docs = DOCUMENTED[(command, flag)]
    instructional = [doc for doc in docs if doc in INSTRUCTIONAL_DOCS]
    if not instructional and command not in REGISTERED:
        # Named ONLY by historical records, AND the command is retired. A changelog entry or a
        # frozen migration report describes what a PAST release accepted, and rewriting it to match
        # today would falsify the record.
        #
        # The `command not in REGISTERED` half is load-bearing and was missing once: without it
        # every historical pair was skipped, including the 28 naming commands that still exist --
        # exactly the pairs where a changelog showing a flag the CLI no longer accepts is a real
        # signal, not a record to preserve.
        pytest.skip(f"`tautline {command} {flag}` is named only by historical records")
    where = ", ".join(str(doc.relative_to(REPO_ROOT)) for doc in instructional)
    if command not in REGISTERED:
        assert not instructional, (
            f"{', '.join(str(d.relative_to(REPO_ROOT)) for d in instructional)} documents "
            f"`tautline {command} {flag}`, but `{command}` is not a subcommand. An operator "
            "following the docs gets 'invalid choice'. Fix the doc, move it under docs/archive/, "
            "or restore the command."
        )
        raise AssertionError("unreachable: an unregistered command in an instructional doc")
    accepted = _accepted_flags(command)
    assert accepted, (
        f"`tautline {command}` is registered but its --help could not be read, so this guard "
        "cannot check the flag it is here to check"
    )
    assert flag in accepted, (
        f"{where} documents `tautline {command} {flag}`, but that command does not accept "
        f"{flag}. An operator following the docs gets 'unrecognized argument'. "
        "Fix the doc or add the flag."
    )


# --- the guard's own two layers, asserted separately ---------------------------------------------
#
# Both of these regressed at once and neither was visible from a green run: the discovery corpus
# swallowed docs/archive/, and the checking side skipped EVERY historical pair rather than only the
# retired ones. Together they took 28 real checks offline while the file still reported passing.


def test_the_archive_is_not_in_the_discovery_corpus():
    """docs/archive/ is history: scanning it can only ever produce pairs that get skipped."""
    archived = [doc for doc in DOCS if ARCHIVE_ROOT in doc.parents]
    assert not archived, (
        f"docs/archive/ entered the scanned corpus ({archived[:3]}); every pair it contributes is "
        "unactionable, and silencing them is what previously silenced the real checks too"
    )
    assert ARCHIVE_ROOT.is_dir(), "the archive moved; this exclusion now points at nothing"


def test_historical_records_are_still_checked_for_commands_that_exist():
    """The skip is for RETIRED commands only -- the half that went missing once.

    A changelog entry naming a live command with a flag it no longer accepts is a real signal: the
    command is still runnable, so an operator can still follow that line and get 'unrecognized
    argument'. Only a retired command earns the record-preserving skip.
    """
    checked = [
        (command, flag)
        for (command, flag), docs in DOCUMENTED.items()
        if command in REGISTERED and not [d for d in docs if d in INSTRUCTIONAL_DOCS]
    ]
    assert checked, (
        "no historical pair names a command that still exists, so the REGISTERED clause in the "
        "skip is guarding nothing -- either the corpus stopped being read or the split is wrong"
    )
