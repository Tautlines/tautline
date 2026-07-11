"""T7 (0.9.0): repo-wide guidance scan — no authoritative surface may INSTRUCT the refused
narrative-journal publishers.

Narrative publication is disabled in 0.9.0. If any policy module, plugin skill/reference, or
governance/reference doc still tells an agent to run `publish-session-journal` /
`publish-pending-session-journals`, every lane boundary would hit the refusal instead of the
intended local-only + instrumentation workflow. The only permitted mentions are ones that document
the refusal/deprecation itself, so every mention line must also carry a refusal-context marker.
Generated adapter markdown must not carry the refused invocations at all.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

REFUSED = ("publish-session-journal", "publish-pending-session-journals")
# A mention is legitimate only if the line frames the command as disabled/deprecated.
REFUSAL_MARKERS = (
    "disabled", "deprecated", "no longer", "cannot", "refuse", "refuses",
    "local-only", "local only", "removed", "removeafter", "0.9.0",
    "not published", "never", "no remote",
)


def _authoritative_surfaces() -> list[Path]:
    files: list[Path] = []
    files += sorted((REPO_ROOT / "methodology" / "policy").glob("*.md"))
    files.append(REPO_ROOT / "methodology" / "canonical-rules.md")
    for plugin in sorted((REPO_ROOT / "plugins").glob("*")):
        files += sorted((plugin / "skills").rglob("*.md"))
    # The ENTIRE docs tree, not just governance/reference: an agent-facing runbook, plan, spec, or
    # product doc under docs/ that still instructs the refused publishers would route a lane boundary
    # straight into the refusal and escape a narrower scan (pr-test-analyzer gap #6).
    files += sorted((REPO_ROOT / "docs").rglob("*.md"))
    # Root-level agent bootstrap guidance.
    for root_doc in ("README.md", "CLAUDE.md", "AGENTS.md"):
        files.append(REPO_ROOT / root_doc)
    return sorted({f for f in files if f.is_file()})


def test_no_authoritative_surface_instructs_the_refused_journal_publishers():
    offenders: list[str] = []
    for path in _authoritative_surfaces():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not any(token in line for token in REFUSED):
                continue
            low = line.lower()
            if not any(marker in low for marker in REFUSAL_MARKERS):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "authoritative surfaces still INSTRUCT the refused journal publishers (each such line must "
        "instead document the refusal, or migrate to publish-instrumentation-record):\n"
        + "\n".join(offenders)
    )


def test_generated_adapter_markdown_does_not_invoke_refused_publishers(cli):
    data = cli.load_project(EXAMPLE_ADAPTER)
    files = cli.expected_files(data, str(EXAMPLE_ADAPTER))
    offenders: list[str] = []
    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files.get(filename, "")
        for token in REFUSED:
            # The refused commands must not appear as an instruction in generated adapter guidance.
            if re.search(rf"`?{re.escape(token)}[^`\n]*--(commit|push|target)", content):
                offenders.append(f"{filename}: invokes {token}")
    assert offenders == [], "generated adapter markdown must not instruct the refused publishers:\n" + "\n".join(offenders)
