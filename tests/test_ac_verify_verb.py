"""Item 81 T1.4: `tautline ac-verify` -- the one runnable continuation every closure refusal names.

The gate refuses a done move whose evidence has no AC table. A refusal that cannot tell the lane
what the table should look like is a dead end with extra steps, so the skeleton is derived from the
item's OWN issue body, through the SAME extractor and splitter the gate uses. That shared derivation
is the property worth pinning: whatever the splitter does with an unusual checklist, the table the
lane is told to produce is exactly the table the gate will accept.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

AC_BODY = """# Digest scheduler

## Acceptance Criteria

- The scheduler runs three windows per day
- Users receive a digest email every morning
- The pipeline is observable end to end
    - metrics are emitted per stage
    - traces are sampled at one percent
"""


def _args(target: Path, **overrides) -> argparse.Namespace:
    values = {"project": EXAMPLE_ADAPTER, "target": target, "item": "ITEM1", "out": None}
    values.update(overrides)
    return argparse.Namespace(**values)


def _harness(
    cli,
    monkeypatch,
    *,
    body: str,
    code: int = 0,
    err: str = "",
    url: str = "https://github.com/example-org/example-saas/issues/7",
):
    item = {"id": "ITEM1", "content": {"url": url}} if url else {"id": "ITEM1", "content": {}}
    calls: list[list[str]] = []

    def _run(command, cwd=None, timeout=None, **kwargs):
        calls.append(list(command))
        if command[:3] == ["gh", "issue", "view"]:
            return (code, body, err) if code == 0 else (code, "", err)
        return 0, json.dumps({}), ""

    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *a, **k: item)
    return calls


def test_it_prints_one_skeleton_row_per_criterion(cli, monkeypatch, tmp_path, capsys) -> None:
    _harness(cli, monkeypatch, body=AC_BODY)

    assert cli.ac_verify(_args(tmp_path)) == 0

    out = capsys.readouterr().out
    assert "ac_verify_criteria: 3" in out, "the nested sub-bullets are one criterion, not three"
    for criterion in [
        "the scheduler runs three windows per day",
        "users receive a digest email every morning",
        "the pipeline is observable end to end",
    ]:
        assert f"| {criterion} | {cli.AC_TABLE_VERDICT_PLACEHOLDER} |" in out
    assert "## AC Verification" in out


def test_the_skeleton_it_prints_is_a_table_the_gate_accepts(
    cli,
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """The no-dead-ends property, asserted end to end rather than by inspection: fill in every
    verdict the verb printed and the gate must pass it."""
    _harness(cli, monkeypatch, body=AC_BODY)
    cli.ac_verify(_args(tmp_path))

    printed = capsys.readouterr().out
    skeleton = printed[printed.index("## AC Verification") :]
    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))

    # BOTH directions, because filling the placeholder before asserting is exactly how this lane's
    # first version of this test masked a P1: the unfilled skeleton parsed as four PASS rows.
    assert cli.done_evidence_ac_table_issues(skeleton, AC_BODY, headings), (
        "the unfilled skeleton must be refused -- a blank form cannot verify itself"
    )

    filled = skeleton.replace(cli.AC_TABLE_VERDICT_PLACEHOLDER, "PASS")

    assert cli.done_evidence_ac_table_issues(filled, AC_BODY, headings) == []


def test_an_issue_with_no_ac_section_exits_zero_with_an_explanation(
    cli,
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """Exit 0, not a refusal: an item that never wrote acceptance criteria is not an error state,
    and a verb that fails on it would make `ac-verify` unusable as a first step."""
    _harness(cli, monkeypatch, body="# Title\n\nJust a description.\n")

    assert cli.ac_verify(_args(tmp_path)) == 0

    out = capsys.readouterr().out
    assert "ac_verify_criteria: 0" in out
    assert "no written acceptance-criteria section" in out
    assert "| " not in out.split("ac_verify_criteria: 0")[1], (
        "no skeleton is printed when there are no criteria"
    )


def test_out_writes_a_file_ready_for_the_evidence_flag(cli, monkeypatch, tmp_path, capsys) -> None:
    _harness(cli, monkeypatch, body=AC_BODY)

    assert cli.ac_verify(_args(tmp_path, out=Path("evidence/ac.md"))) == 0

    written = (tmp_path / "evidence" / "ac.md").read_text(encoding="utf-8")
    assert written.startswith("## AC Verification")
    assert written.count(cli.AC_TABLE_VERDICT_PLACEHOLDER) == 3
    assert "ac_verify_out:" in capsys.readouterr().out


def test_an_unreadable_issue_body_refuses_with_a_runnable_remedy(
    cli,
    monkeypatch,
    tmp_path,
) -> None:
    _harness(cli, monkeypatch, body="", code=1, err="HTTP 403: Forbidden")

    with pytest.raises(SystemExit) as raised:
        cli.ac_verify(_args(tmp_path))

    message = str(raised.value)
    assert message.startswith("done_evidence_ac_error:")
    assert "issue body unavailable" in message
    assert "tautline backlog-provider-status" in message


def test_an_item_with_no_issue_link_refuses_rather_than_printing_an_empty_table(
    cli,
    monkeypatch,
    tmp_path,
) -> None:
    _harness(cli, monkeypatch, body=AC_BODY, url="")

    with pytest.raises(SystemExit) as raised:
        cli.ac_verify(_args(tmp_path))

    assert "no linked GitHub issue/PR URL" in str(raised.value)


def test_it_reads_the_body_from_the_items_own_repo(cli, monkeypatch, tmp_path) -> None:
    calls = _harness(cli, monkeypatch, body=AC_BODY, url="https://github.com/other/repo/issues/5")

    cli.ac_verify(_args(tmp_path))

    views = [call for call in calls if call[:3] == ["gh", "issue", "view"]]
    assert views and views[0][views[0].index("--repo") + 1] == "other/repo"
