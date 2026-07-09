from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
MAX_EXAMPLE_CLAUDE_BYTES = 16_000


def test_example_saas_rendered_claude_stays_within_phase4_budget(run_cli, tmp_path):
    target = tmp_path / "example-saas"
    target.mkdir()

    result = run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
    )

    assert result.returncode == 0, result.stderr
    rendered = target / "CLAUDE.md"
    assert rendered.exists()
    current = len(rendered.read_bytes())
    headroom = MAX_EXAMPLE_CLAUDE_BYTES - current
    assert current <= MAX_EXAMPLE_CLAUDE_BYTES, (
        f"rendered example-saas CLAUDE.md exceeds the byte budget "
        f"(current={current}, limit={MAX_EXAMPLE_CLAUDE_BYTES}, headroom={headroom}); "
        "trim/dedupe rendered sections in render_adapter (bin/minervit-methodology) "
        "-- do not raise this ceiling without a deliberate, reviewed decision"
    )
