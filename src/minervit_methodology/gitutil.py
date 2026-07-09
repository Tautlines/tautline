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
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return False
    return result == "true"


def run_git(target: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unavailable"


def current_branch_name(target: Path) -> str:
    branch = run_git(target, ["branch", "--show-current"])
    return "" if branch == "unavailable" else branch.strip()


def git_branch_upstream(target: Path) -> str:
    upstream = run_git(target, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    return "" if upstream == "unavailable" else upstream.strip()
