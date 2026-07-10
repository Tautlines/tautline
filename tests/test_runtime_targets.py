"""prod-extensibility-3 (productization): runtime->generated-file mapping is centralized in one
RUNTIME_TARGETS descriptor instead of scattered hardcoded {CLAUDE.md, AGENTS.md} assumptions, so a
new runtime target is a one-line addition. GENERATED_MARKDOWN_FILES derives from it.
"""


def test_descriptor_drives_markdown_set(cli):
    assert cli.GENERATED_MARKDOWN_FILES == {t["outputFile"] for t in cli.RUNTIME_TARGETS}


def test_default_targets_are_claude_and_codex(cli):
    by_agent = {t["agent"]: t["outputFile"] for t in cli.RUNTIME_TARGETS}
    assert by_agent["Claude"] == "CLAUDE.md"
    assert by_agent["Codex"] == "AGENTS.md"


def test_each_target_has_required_keys(cli):
    for t in cli.RUNTIME_TARGETS:
        assert {"agent", "outputFile", "runtime"} <= set(t)
        assert t["outputFile"].endswith(".md")


def test_example_adapter_renders_all_targets(cli):
    from pathlib import Path

    data = cli.load_project(Path(cli.REPO_ROOT) / "adapters" / "projects" / "example-saas.json")
    files = cli.expected_files(data, str(Path(cli.REPO_ROOT) / "adapters" / "projects" / "example-saas.json"))
    for t in cli.RUNTIME_TARGETS:
        assert t["outputFile"] in files and files[t["outputFile"]].strip()
    assert cli.LANE_ADAPTER_FILE in files
