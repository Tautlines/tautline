"""Git helper primitives for the Minervit methodology CLI."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def infer_repo_slug(target: Path) -> str:
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(target), "config", "--get", "remote.origin.url"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "<owner>/<repo>"
    if not remote:
        return "<owner>/<repo>"
    patterns = [
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
        r"(?P<owner>[^/:]+)/(?P<repo>[^/.]+)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return "<owner>/<repo>"


def target_is_git_worktree(target: Path) -> bool:
    try:
        result = subprocess.check_output(
            ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return False
    return result == "true"


def run_git(target: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unavailable"


def run_git_status(target: Path, args: list[str]) -> tuple[int, str]:
    """`git` exit status plus its stdout, decoded LOSSLESSLY -- nothing stripped, nothing collapsed.

    `run_git` above answers "what did git say", and for almost every caller that is the right
    question. It is the wrong one whenever git's output is a set of PATHS: it reports failure with
    the in-band sentinel `"unavailable"`, which is itself a legal filename, and it strips
    surrounding whitespace, which is legal in a filename too. A caller that must not confuse a
    failed command with a file literally named `unavailable` -- or two files named `foo` and
    `foo ` -- needs the exit status out of band and the bytes untouched.

    BYTES, NOT TEXT. `text=True` applies universal-newline translation, so legal paths differing
    only as `foo\r` and `foo\n` both arrive as `foo\n`; `errors="replace"` likewise collapses
    distinct non-UTF-8 names onto one. Either merges two different files into one identity, and a
    caller comparing path sets would then FABRICATE an overlap -- the failure that blocks unrelated
    work rather than merely missing something. Captured raw and decoded with `surrogateescape`,
    which round-trips any byte sequence.
    """
    proc = subprocess.run(
        ["git", "-C", str(target), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="surrogateescape")


def current_branch_name(target: Path) -> str:
    branch = run_git(target, ["branch", "--show-current"])
    return "" if branch == "unavailable" else branch.strip()


def git_branch_upstream(target: Path) -> str:
    upstream = run_git(target, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    return "" if upstream == "unavailable" else upstream.strip()
