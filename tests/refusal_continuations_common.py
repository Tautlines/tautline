"""Shared refusal-continuation machinery (item 70, T2.1).

Extracted from `tests/test_refusal_continuations.py` so the launch/trust refusal surface can
apply the SAME runnable-command check and the same allowlist-with-reason discipline without a
second, drifting copy. Two suites asserting "a named remedy actually runs" against two hand-kept
implementations is how one of them quietly stops meaning it.

Refactor only: every function below is byte-preserved from the review-surface suite, and that
suite's own checks, prefixes and allowlist entries are unchanged. The PR carries before/after run
output proving zero delta.

Everything here reads the CLI itself rather than a hand-maintained list, which is the property
that makes the check survive a verb being renamed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "bin" / "tautline"

# An invocation shown inside a refusal: `tautline <verb> [--flag[=value]]...`.
INVOCATION = re.compile(
    r"\btautline\s+([a-z][a-z0-9-]+)((?:\s+--[a-zA-Z][a-zA-Z0-9-]*(?:[= ][^\s`\'\"]+)?)*)"
)
FLAG = re.compile(r"(?<![\w-])(--[a-zA-Z][a-zA-Z0-9-]*)")


def allowlisted(allowlist: dict[str, str], text: str) -> str:
    """The recorded REASON this text is exempt, or "" when it is not.

    A reason, never a bare membership test: an allowlist entry without one is a silent hole, and
    the suites that use this fail an entry whose reason is empty.
    """
    for fragment, reason in allowlist.items():
        if fragment in text:
            return reason
    return ""


def named_invocations(checked: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
    """(command, flag) -> the sites that name it, across every collected refusal."""
    found: dict[tuple[str, str], list[str]] = {}
    for site, text in checked:
        for command, tail in INVOCATION.findall(text):
            for flag in FLAG.findall(tail):
                found.setdefault((command, flag), []).append(site)
    return found


@lru_cache(maxsize=None)
def cli_verbs() -> frozenset[str]:
    """Every `tautline` subcommand, read from the CLI itself rather than hand-listed."""
    result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"\{([a-z0-9,\-]{40,})\}", result.stdout)
    return frozenset(match.group(1).split(",")) if match else frozenset()


@lru_cache(maxsize=None)
def accepted_flags(command: str) -> frozenset[str]:
    """The flags a verb's own --help advertises; empty when the verb does not exist."""
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return frozenset()
    return frozenset(FLAG.findall(result.stdout))
