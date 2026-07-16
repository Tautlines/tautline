import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES = 16_000


REQUIRED_RENDERED_ADAPTER_MARKERS = """
^## Deployment Targets
Adapter-owned deploy procedure/health is authoritative
^## Technical Stack Policy
Cloud default `aws`
Tool/framework defaults do not authorize new platforms
No plaintext secrets in source or images.
^## Session Start
Before gates, resolve CLI
$MINERVIT_METHODOLOGY_REPO/bin/tautline
lane-start --target .
methodology-status --target . --fail-on-drift
latest-code-status --target . --write
gh pr view <PR> --json state,mergeStateStatus
git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null
^## Development Environment
Supported lane runtimes: `linux`, `darwin`, `wsl2`
Windows native shell support: `unsupported`; supported Windows runtime: `wsl2`
Open the repo inside WSL2 Ubuntu
core.autocrlf input
^## Work Profiles
lane-start --profile product-docs
^## Lane Methodology Updates
Product/client lanes do not raw-pull latest methodology
set-framework-channel --target . stable|experimental
set-framework-channel --target . --source adapter stable|experimental
old repos default to stable/manual/dry-run
render-adapters --write --json-only
^## Local Resource Isolation
Lane startup writes lane-local env to `.ai-work/lane-env.sh`
Port collisions are not human blockers
^## Graphify Navigation
use Graphify report/query/path/explain before broad `rg`/grep
graphify . --update
commit `graphify-out/`
^## Context Continuity
prepare-continuity --target . --stdin
Context indexes:
Context rotate:
^## Session Signal
prepare-session-journal
publish-instrumentation-record
^## Goal Orchestration
Goal -> Milestone -> PR/tactical item
Project `Status` drift blocks
^## Delivery And Accounting
publish-milestone-update --target . --milestone <id> --stdin
usage-record
^## End-of-Goal Boundary
goal-complete --iteration-review-record
^## Milestone Continuation
milestone-start --target . --plan <source-of-truth-plan>
milestone-advance --target . --event <event>
^## Autonomy And Planning
plan-finalization-precheck --target . --plan <source-of-truth-plan>
Review target is 2 rounds; rounds 3-4 self-authorize with `--exception-note`
Evidence is tracked `.plan-reviews/`
^## Planning Artifacts And Backlog Source Of Truth
Source/template:
Cross-Model Review Evidence
^## Autonomy And Status
Memories/Open Brain are evidence only
Methodology/process regressions use framework-intake
^## Delivery Summaries
Landed/shipped/queued reports start with executive outcome
Refresh continuity before summaries are complete
^## Execution Packet Work Loop
Packet defines scope, ordered queue, dependencies, safe parallelism
^## TDD And Behavior Specs
Behavior specs are required
behavior-spec-status --target .
^## Early-Warning Smoke
Early-warning smoke is no longer a standing gate
^## Local Gates
Before commit: `tautline lane-run --target . -- make pf-fast`
Before push: `tautline lane-run --target . -- make test-env-up`
Do not substitute GitHub Actions for local preflight
^## Review Before Push
codex-run --target . --risk-tier
finalize-implementation-review --target . --manifest <manifest>
track `.impl-reviews/` evidence before push
fix Critical/C1/P1/Important before merge
^## Merge Queue
Routine merge command: `gh pr merge <PR> --squash --auto --delete-branch`
Do not use routine `--admin` merge
^## Background Commands
Long/background commands require monitor
foreground >10m review/test/gates need <=10m checkpoints
Follow `response-guard` recovery actions
^## Example SaaS-Specific Invariants
Every tenant-scoped endpoint must enforce tenant isolation.
""".strip().splitlines()


FORBIDDEN_RENDERED_ADAPTER_MARKERS = [
    "methodology-regression-rca.md",
    "Agent training default overrode methodology",
    "upper bound of 20 Markdown files",
    "Document Context Budget",
    "Verified Human Instructions",
]


def _assert_marker(content: str, marker: str, filename: str) -> None:
    if marker.startswith("^"):
        assert re.search(rf"^{re.escape(marker[1:])}", content, re.MULTILINE), (
            f"{filename} missing line-anchored generated adapter marker: {marker}"
        )
        return
    assert marker in content, f"{filename} missing generated adapter marker: {marker}"


def test_example_saas_generated_adapter_contract(cli):
    adapter_path = EXAMPLE_ADAPTER
    data = cli.load_project(adapter_path)
    files = cli.expected_files(data, str(adapter_path))

    # Future runtime targets must intentionally satisfy this shared generated-adapter contract
    # or split out a narrower per-runtime contract instead of silently skipping coverage.
    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files[filename]
        assert len(content.encode()) <= MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES, filename
        for marker in REQUIRED_RENDERED_ADAPTER_MARKERS:
            _assert_marker(content, marker, filename)
        for marker in FORBIDDEN_RENDERED_ADAPTER_MARKERS:
            assert marker not in content, f"{filename} leaked generated adapter marker: {marker}"


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_render_adapters_refuses_to_overwrite_handwritten_markdown(tmp_path):
    target = tmp_path / "protected-render"
    target.mkdir()
    (target / "CLAUDE.md").write_text("hand-written Claude instructions\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("hand-written Codex instructions\n", encoding="utf-8")

    result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
    )

    assert result.returncode != 0
    assert "refusing to overwrite non-generated adapter markdown" in result.stderr
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "hand-written Claude instructions\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "hand-written Codex instructions\n"
    assert not (target / ".tautline.json").exists()


def test_render_adapters_json_only_preserves_handwritten_markdown(tmp_path):
    target = tmp_path / "protected-render"
    target.mkdir()
    (target / "CLAUDE.md").write_text("hand-written Claude instructions\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("hand-written Codex instructions\n", encoding="utf-8")

    write_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    check_json_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--check",
        "--json-only",
    )
    check_full_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--check",
    )

    assert write_result.returncode == 0, write_result.stderr
    assert "wrote " in write_result.stdout
    assert (target / ".tautline.json").exists()
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "hand-written Claude instructions\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "hand-written Codex instructions\n"
    assert check_json_result.returncode == 0, check_json_result.stdout + check_json_result.stderr
    assert check_full_result.returncode == 1
    assert f"protected: {target / 'CLAUDE.md'}" in check_full_result.stdout
    assert f"protected: {target / 'AGENTS.md'}" in check_full_result.stdout
