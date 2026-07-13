"""Every shipped SKILL.md must have frontmatter that actually parses as YAML.

A skill whose frontmatter fails to parse still loads - with *empty metadata*.
Its name, description and triggers are silently dropped, so the agent never
invokes it and nothing fails loudly. Two skills shipped that way (an unquoted
colon in the description makes YAML read the rest of the line as a nested key),
and it only surfaced when `claude plugin validate` refused the plugin, which in
turn would have blocked `/plugin install` from the public marketplace.

This guard makes that class of breakage fail here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_FILES = sorted((REPO_ROOT / "plugins").rglob("SKILL.md"))

KEY_VALUE = re.compile(r"^(?P<key>\w[\w-]*):[ \t]*(?P<value>.*)$")

# Quoted, block, and flow scalars can hold a ": " safely. A plain scalar cannot:
# YAML reads the colon as a nested key and the document fails to parse.
SAFE_SCALAR_PREFIXES = ('"', "'", "|", ">", "[", "{")


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.relative_to(REPO_ROOT)}: missing YAML frontmatter"
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.relative_to(REPO_ROOT)}: unterminated YAML frontmatter"
    return parts[1]


def test_skill_files_exist() -> None:
    assert SKILL_FILES, "no SKILL.md files found; this guard would vacuously pass"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_skill_frontmatter_has_no_unquoted_colon(skill: Path) -> None:
    violations = []
    for line in _frontmatter(skill).strip().splitlines():
        match = KEY_VALUE.match(line)
        if not match:
            continue
        value = match.group("value").strip()
        if not value or value.startswith(SAFE_SCALAR_PREFIXES):
            continue
        if ": " in value:
            violations.append(f"{match.group('key')}: {value[:60]}")
    assert not violations, (
        f"{skill.relative_to(REPO_ROOT)}: frontmatter value contains an unquoted ': ', "
        "so YAML parses it as a nested key and the skill loads with EMPTY metadata. "
        f"Quote the value. Offending: {violations}"
    )


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_skill_frontmatter_declares_name_and_description(skill: Path) -> None:
    keys = {
        match.group(1)
        for match in (re.match(r"^(\w[\w-]*):", line) for line in _frontmatter(skill).splitlines())
        if match
    }
    assert {"name", "description"} <= keys, (
        f"{skill.relative_to(REPO_ROOT)}: frontmatter must declare name and description; got {sorted(keys)}"
    )
