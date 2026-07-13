import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(tmp_path: Path, *args: str, input: str | None = None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        input=input,
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        timeout=60,
    )


def _init_target(target: Path) -> None:
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")


def test_work_loop_dry_run_consumes_packet_queue_and_refreshes_continuity(tmp_path):
    target = tmp_path / "work-loop-fixture"
    _init_target(target)
    packet = target / ".ai-work" / "EXECUTION_PACKET.md"
    packet.parent.mkdir(parents=True)
    packet.write_text(
        """# Execution Packet

## Milestone Goal
- Validate the dry-run parser.

## Non-Goals
- Do not mutate product code.

## Ordered Tactical Queue
- [x] Already completed dry-run item
  - Nested detail must not become a queue item
- [ ] First dry-run item
  - Nested implementation note
- [ ] Second dry-run item

## Queue Notes
- This note must not become a queue item.

## True-Blocker Criteria
- None for fixture.

## Completion Definition
- Run evidence and continuity are written.
""",
        encoding="utf-8",
    )

    result = _run_cli(
        tmp_path,
        "work-loop",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    run_files = sorted((target / ".ai-runs").glob("*work-loop-dry-run.json"))
    assert len(run_files) == 1
    record = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert record["schema"] == "minervit-work-loop-run/v1"
    assert record["mode"] == "dry-run"
    assert record["packet"] == ".ai-work/EXECUTION_PACKET.md"
    assert record["stoppedForHuman"] is False
    assert record["items"] == [
        {"index": 1, "title": "First dry-run item", "status": "would_execute"},
        {"index": 2, "title": "Second dry-run item", "status": "would_execute"},
    ]

    handoff = target / ".ai-continuity" / "NEXT_SESSION.md"
    handoff_text = handoff.read_text(encoding="utf-8")
    handoff_body_line = "Dry run consumed 2 execution packet item(s) without stopping between items."
    assert f"wrote {run_files[0]}" in result.stdout
    assert f"wrote {handoff}" in result.stdout
    assert handoff_body_line in handoff_text
    assert "Execute the first incomplete item in the execution packet." in handoff_text
    assert handoff_body_line not in result.stdout
    assert ".ai-continuity/" in (target / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_prepare_continuity_writes_handoff_with_startup_gate_order(tmp_path):
    target = tmp_path / "continuity-fixture"
    _init_target(target)
    content = "## Current State\n- validation fixture\n\n## Next Action\n- continue validation\n"

    result = _run_cli(
        tmp_path,
        "prepare-continuity",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--stdin",
        input=content,
    )

    assert result.returncode == 0, result.stderr
    handoff = target / ".ai-continuity" / "NEXT_SESSION.md"
    text = handoff.read_text(encoding="utf-8")
    assert "validation fixture" in text
    assert "wrote " in result.stdout
    assert str(handoff) in result.stdout
    assert "validation fixture" not in result.stdout
    for marker in [
        "tautline lane-start --target .",
        "tautline methodology-status --target . --fail-on-drift",
        "Do not replace the methodology status gate with ad hoc",
        "Methodology CLI resolver:",
        "if it is missing from `PATH` or exits 127/command-not-found",
        "source `$HOME/.config/tautline/tautline.env` (or the legacy minervit env) when present or use `${TAUTLINE_METHODOLOGY_REPO:-$MINERVIT_METHODOLOGY_REPO}/bin/tautline`",
        "rerun the same gate",
        "not a failed methodology gate",
        "not a reason to ask for a person-specific path",
        "If both the `PATH` command and portable checkout fallback are unavailable",
        "run the gates below in listed order",
        "Do not execute from Handoff Content before the gates pass",
        "Do not ask clarifying questions, report substantive status, or start analysis from Handoff Content before the methodology gates pass",
        "If either methodology gate is skipped or fails",
        "Methodology gate 1:",
        "Methodology gate 2:",
    ]:
        assert marker in text
    assert "Methodology repo:" not in text

    section = text[text.index("\n## Required Startup Gates\n") : text.index("\n## Handoff Content\n")]
    expected_order = [
        "- Read this section, run the gates below in listed order",
        "- Do not ask clarifying questions",
        "- Resolve the methodology CLI before running gates",
        "- If both the `PATH` command and portable checkout fallback are unavailable",
        "- Methodology gate 1: run `tautline lane-start --target .`",
        "- Methodology gate 2: run `tautline methodology-status --target . --fail-on-drift`",
        "- Do not replace the methodology status gate with ad hoc",
        "- If either methodology gate is skipped or fails",
        "- After the methodology status gate is clean",
    ]
    positions = [section.index(marker) for marker in expected_order]
    assert positions == sorted(positions)
    project_gate_positions = [
        section.index(line)
        for line in section.splitlines()
        if line.startswith("- Project gate after methodology status:")
    ]
    assert len(project_gate_positions) == 3
    assert positions[-1] < project_gate_positions[0] < project_gate_positions[1] < project_gate_positions[2]
