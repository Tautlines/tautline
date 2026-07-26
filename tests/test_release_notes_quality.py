import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
RELEASE_NOTES = ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md"


def _release_notes_text() -> str:
    return RELEASE_NOTES.read_text(encoding="utf-8")


def test_release_notes_main_branch_is_archive_stub():
    text = _release_notes_text()
    lines = text.splitlines()

    assert len(lines) <= 12
    assert "methodology-release-notes-archive:docs/releases/minervit-ai-delivery-methodology.md" in text
    assert "`CHANGELOG.md` is the concise main-branch release history" in text
    assert "Do not append narrative" in text
    assert not re.search(r"^### Release Index$", text, flags=re.M)


def test_release_notes_stub_preserves_current_version_identity():
    text = _release_notes_text()

    assert re.search(rf"^## {re.escape(VERSION)} - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$", text, flags=re.M)


def test_changelog_carries_no_conflict_markers():
    """A rebase that resolves CHANGELOG.md by hand can leave a marker behind, and
    the file IS the published release notes -- a `>>>>>>> <sha> (subject)` line
    would ship verbatim. Cheap guard against an expensive embarrassment."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    offenders = [
        f"{n}: {line}"
        for n, line in enumerate(text.splitlines(), start=1)
        if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line.rstrip() == "======="
    ]
    assert not offenders, "conflict markers in CHANGELOG.md: " + "; ".join(offenders)
