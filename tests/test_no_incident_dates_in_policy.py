import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISO_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _agent_facing_policy_paths() -> list[Path]:
    paths = [
        ROOT / "methodology" / "canonical-rules.md",
        ROOT / "methodology" / "policy-phrases-reference.md",
    ]
    paths.extend((ROOT / "methodology" / "policy").glob("*.md"))
    paths.extend((ROOT / "adapters").rglob("*.md"))
    paths.extend((ROOT / "adapters").rglob("*.json"))
    for plugin in (ROOT / "plugins").iterdir():
        skills = plugin / "skills"
        if skills.exists():
            paths.extend(path for path in skills.rglob("*.md") if path.name != "CHANGELOG.md")
    return sorted(paths)


def test_generated_reference_adapter_markdown_has_no_incident_dates(cli):
    adapter_path = ROOT / "adapters" / "projects" / "example-saas.json"
    data = cli.load_project(adapter_path)
    files = cli.expected_files(data, str(adapter_path))

    offenders = [
        filename
        for filename, content in files.items()
        if filename in cli.GENERATED_MARKDOWN_FILES and ISO_DATE.search(content)
    ]

    assert offenders == []
