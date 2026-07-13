import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIVING_DOC_PATHS = [
    ROOT / "README.md",
    *(ROOT / "docs" / "product").glob("*.md"),
    *(ROOT / "docs" / "productization").glob("*.md"),
    *(ROOT / "docs" / "productization" / "designs").glob("*.md"),
]


def _living_doc_texts():
    for path in sorted(LIVING_DOC_PATHS):
        yield path, path.read_text(encoding="utf-8")


def test_public_docs_do_not_hardcode_mutable_test_counts():
    stale_count = re.compile(
        r"\b\d{2,4}(?:,\d{3})?\s+(?:behavior\s+|pytest\s+|unit\s+|passing\s+)?tests\b"
        r"|\b\d{2,4}(?:,\d{3})?-test\b",
        re.IGNORECASE,
    )

    offenders = []
    for path, text in _living_doc_texts():
        for match in stale_count.finditer(text):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")

    assert offenders == []


def test_public_docs_do_not_hardcode_old_size_snapshots():
    forbidden_literals = [
        "23,686-line",
        "23,686 lines",
        "23.7k-line",
        "688KB",
        "181KB README",
        "804 top-level defs",
        "9,182-line",
        "~1.1MB CLI",
    ]
    offenders = []
    for path, text in _living_doc_texts():
        for literal in forbidden_literals:
            if literal in text:
                offenders.append(f"{path.relative_to(ROOT)}: {literal}")

    assert offenders == []


def test_public_docs_do_not_claim_claude_plugin_gap():
    stale_claims = [
        "has no `.claude-plugin/` sibling directory",
        "ships only `plugins/tautline-core/.codex-plugin/plugin.json`",
        "Plugin-manifest gap (current, tracked)",
    ]
    offenders = []
    for path, text in _living_doc_texts():
        for claim in stale_claims:
            if claim in text:
                offenders.append(f"{path.relative_to(ROOT)}: {claim}")

    assert offenders == []


def test_public_docs_do_not_treat_generated_canonical_as_edit_source():
    generated_canonical = "methodology/canonical-rules.md"
    stale_suffix = " is the reusable process source"
    stale_claims = [
        f"`{generated_canonical}`{stale_suffix}",
        f"{generated_canonical}`{stale_suffix}",
        f"{generated_canonical}{stale_suffix}",
        f"`{generated_canonical}` is the editable reusable process source",
        f"{generated_canonical} is the editable reusable process source",
    ]
    offenders = []
    for path, text in _living_doc_texts():
        for claim in stale_claims:
            if claim in text:
                offenders.append(f"{path.relative_to(ROOT)}: {claim}")

    assert offenders == []


def test_release_engineering_documents_framework_channel_pins():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_engineering = (
        ROOT / "docs" / "reference" / "operations" / "release-engineering.md"
    ).read_text(encoding="utf-8")

    assert "docs/reference/operations/release-engineering.md" in readme
    assert "tautline set-framework-channel --target . stable" in release_engineering
    assert "tautline set-framework-channel --target . experimental" in release_engineering
    assert "wipSafe: true" in release_engineering
