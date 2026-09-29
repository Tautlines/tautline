"""The builder-lane contract: who is a builder, and where the product board is.

This module is the ONE place two facts live, so the verbs (`builder_github`), the guard
(`builder_guard`) and the identity minting (`builder_token`) cannot drift apart:

1. `builder_role_active()` -- is THIS process a builder lane? A builder lane is any session an
   operator has marked as one, and NOTHING else. Humans (the product director working in the
   product repo, the operator on their own machine) are never builders by default. The two
   markers, either of which is sufficient:
     - the environment variable TAUTLINE_ROLE=builder (machine-wide on builder-only machines via
       the methodology env file, or exported by a lane orchestrator or `tautline builder-env`), or
     - the file `.ai-work/lane-role` under the target containing the single word `builder`
       (written by `tautline lane-role builder`).
   Any other value, or no marker at all, is HUMAN. There is no third role.

2. `board_config()` -- the product board's coordinates, read from the lean adapter's
   `builderGithub` block. Absent block means the project has not opted in and every builder verb
   refuses with the config it needs. Credentials are never here.

Import rule: nothing in this module imports `cli`; it is imported BY the feature modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from tautline_methodology.util import resolve_env

ROLE_ENV = "TAUTLINE_ROLE"
ROLE_BUILDER = "builder"
ROLE_FILE = Path(".ai-work") / "lane-role"

CONFIG_KEY = "builderGithub"


def builder_role_active(target: Path | None = None, environ: Mapping[str, str] | None = None) -> bool:
    """True only when an explicit builder marker is present. Default is human."""
    if resolve_env(ROLE_ENV, environ=environ).strip().lower() == ROLE_BUILDER:
        return True
    root = Path(target) if target is not None else Path.cwd()
    marker = root / ROLE_FILE
    try:
        return marker.read_text(encoding="utf-8").strip().lower() == ROLE_BUILDER
    except OSError:
        return False


class BuilderConfigError(ValueError):
    """The lean adapter's `builderGithub` block is missing or unusable."""


@dataclass(frozen=True)
class BoardConfig:
    """Coordinates of the product board and the repo whose issues back it."""

    repo: str  # owner/name
    owner: str  # Project (ProjectV2) owner login: an org or a user
    project_number: int
    status_field: str = "Status"
    type_field: str = "Item Type"
    hidden_statuses: tuple[str, ...] = ("Done",)
    debt_label: str = "tech-debt"

    @property
    def repo_owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


REQUIRED_KEYS = ("owner", "projectNumber")
OPTIONAL_KEYS = ("statusField", "typeField", "hiddenStatuses", "debtLabel")


def board_config_errors(cfg: dict | None) -> list[str]:
    """Validation the stdlib lean validator delegates to. Empty list means usable."""
    block = (cfg or {}).get(CONFIG_KEY)
    if block is None:
        return [f"no `{CONFIG_KEY}` block in the lean adapter"]
    if not isinstance(block, dict):
        return [f"`{CONFIG_KEY}` must be an object"]
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in block:
            errors.append(f"`{CONFIG_KEY}.{key}` is required")
    unknown = sorted(set(block) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        errors.append(f"`{CONFIG_KEY}` has unknown keys: {', '.join(unknown)}")
    if "owner" in block and (not isinstance(block["owner"], str) or not block["owner"].strip()):
        errors.append(f"`{CONFIG_KEY}.owner` must be a non-empty string")
    if "projectNumber" in block and (isinstance(block["projectNumber"], bool) or not isinstance(block["projectNumber"], int) or block["projectNumber"] < 1):
        errors.append(f"`{CONFIG_KEY}.projectNumber` must be a positive integer")
    for key in ("statusField", "typeField", "debtLabel"):
        if key in block and (not isinstance(block[key], str) or not block[key].strip()):
            errors.append(f"`{CONFIG_KEY}.{key}` must be a non-empty string")
    if "hiddenStatuses" in block and (
        not isinstance(block["hiddenStatuses"], list) or not all(isinstance(s, str) for s in block["hiddenStatuses"])
    ):
        errors.append(f"`{CONFIG_KEY}.hiddenStatuses` must be a list of strings")
    repo = str(((cfg or {}).get("project") or {}).get("repo") or "").strip()
    if "/" not in repo or repo.startswith("http"):
        errors.append("`project.repo` must be `owner/name` for the builder GitHub verbs")
    return errors


def board_config(cfg: dict | None) -> BoardConfig:
    """The board coordinates, or a BuilderConfigError naming exactly what to add."""
    errors = board_config_errors(cfg)
    if errors:
        raise BuilderConfigError(
            "The builder GitHub verbs need a `builderGithub` block in .tautline.json:\n  "
            + "\n  ".join(errors)
            + '\nExample:\n  "builderGithub": {"owner": "<org>", "projectNumber": 5, '
            '"statusField": "Status", "typeField": "Item Type", "hiddenStatuses": ["Done"], '
            '"debtLabel": "tech-debt"}'
        )
    block = dict((cfg or {})[CONFIG_KEY])
    return BoardConfig(
        repo=str((cfg or {})["project"]["repo"]).strip(),
        owner=str(block["owner"]).strip(),
        project_number=int(block["projectNumber"]),
        status_field=str(block.get("statusField") or "Status").strip(),
        type_field=str(block.get("typeField") or "Item Type").strip(),
        hidden_statuses=tuple(block.get("hiddenStatuses", ["Done"])),
        debt_label=str(block.get("debtLabel") or "tech-debt").strip(),
    )


def lane_stamp(target: Path | None = None, environ: Mapping[str, str] | None = None) -> str:
    """The attribution trailer every builder write carries: lane, branch, head SHA, UTC time.

    Deterministic, greppable, and the only way a reader of GitHub can tell which lane acted, since
    every lane on a machine shares one GitHub identity.
    """
    import subprocess
    from datetime import datetime, timezone

    root = Path(target) if target is not None else Path.cwd()

    def git(*args: str) -> str:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    sha = git("rev-parse", "--short=7", "HEAD") or "?"
    lane = resolve_env("TAUTLINE_LANE", environ=environ).strip() or root.name
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"<sub>builder · lane {lane} · {branch}@{sha} · {when}</sub>"


def github_token(cfg: dict | None = None, environ: Mapping[str, str] | None = None) -> str:
    """The token the builder verbs authenticate with, or "" to fall back to `gh auth token`.

    A re-export of `builder_token.github_token`, so a verb that needs the contract AND the
    credential reaches for one module rather than two. The import is deliberately LAZY:
    `builder_token` imports THIS module for the role markers, so a module-level import here would
    be a cycle -- and the import rule at the top of this file is what keeps it from becoming one.
    """
    from tautline_methodology import builder_token

    return builder_token.github_token(cfg, environ=environ)


__all__ = [
    "BoardConfig",
    "BuilderConfigError",
    "CONFIG_KEY",
    "ROLE_BUILDER",
    "ROLE_ENV",
    "ROLE_FILE",
    "board_config",
    "board_config_errors",
    "builder_role_active",
    "github_token",
    "lane_stamp",
]
_ = os  # keep the stdlib import explicit for readers grepping env access; resolve_env is the chokepoint
