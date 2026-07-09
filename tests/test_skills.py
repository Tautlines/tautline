"""D4 (0.6.113): backlog-epic-grooming policy must remain lane-agnostic."""

from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "tautline-core"
    / "skills"
    / "backlog-epic-grooming"
    / "SKILL.md"
)
REFERENCE = SKILL.parent / "references" / "backlog-epic-grooming-policy.md"
ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOTS = (
    ROOT / "plugins" / "tautline-core" / "skills",
    ROOT / "plugins" / "tautline-ops" / "skills",
)


def _skill_dirs():
    dirs = []
    for skills_root in SKILLS_ROOTS:
        if not skills_root.is_dir():
            continue
        # `examples/` is a container; validate the example skills nested under it.
        dirs.extend(path for path in skills_root.iterdir() if path.is_dir() and path.name != "examples")
        examples_root = skills_root / "examples"
        if examples_root.is_dir():
            dirs.extend(path for path in examples_root.iterdir() if path.is_dir())
    return sorted(dirs)


def test_all_packaged_skills_have_valid_frontmatter():
    errors = []
    for skill in _skill_dirs():
        path = skill / "SKILL.md"
        if not path.exists():
            errors.append(f"{skill.name}: missing SKILL.md")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{skill.name}: missing frontmatter")
            continue
        try:
            end = text.index("\n---\n", 4)
        except ValueError:
            errors.append(f"{skill.name}: unterminated frontmatter")
            continue
        frontmatter = {}
        for line in text[4:end].splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
        if frontmatter.get("name") != skill.name:
            errors.append(f"{skill.name}: frontmatter name mismatch")
        if not frontmatter.get("description"):
            errors.append(f"{skill.name}: missing description")
        if not text[end + 5 :].strip():
            errors.append(f"{skill.name}: empty body")

    assert errors == []


def test_backlog_epic_grooming_skill_lane_agnostic():
    assert SKILL.exists(), "backlog-epic-grooming SKILL.md missing"
    assert REFERENCE.exists(), "backlog-epic-grooming reference missing"
    text = SKILL.read_text()
    reference = REFERENCE.read_text()
    # Frontmatter.
    assert text.startswith("---\n")
    assert "name: backlog-epic-grooming" in text
    assert "references/backlog-epic-grooming-policy.md" in text
    # Required detailed sections.
    for section in (
        "## Feature-Item Template",
        "## Done-When Checklist",
        "`## Acceptance criteria`",
        "## Verification",
        "## Privacy / negative tests",
    ):
        assert section in reference, f"missing section: {section}"
    # Placeholders only — no hardcoded lane data.
    assert "<PREFIX>" in reference
    assert "<EPIC_FIELD>" in reference
    assert "<PRIVACY_INVARIANT" in reference
    for leaked in ("Private Product A", "Project #3", "F-1", "F-2", "F-series"):
        assert leaked not in text
        assert leaked not in reference, f"hardcoded lane data leaked: {leaked}"
    # Disambiguation from plan-review convergence handling.
    assert "distinct from plan-review cap/focus-transfer handling" in reference


def test_grooming_skill_references_validate_grooming_read_only():
    text = SKILL.read_text() + "\n" + REFERENCE.read_text()
    assert "validate-grooming" in text
    assert "read-only" in text.lower()
    assert "never edits the board" in text
