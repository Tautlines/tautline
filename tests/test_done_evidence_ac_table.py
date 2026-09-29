"""Item 81 WS1: closure verification is measured against the item's WRITTEN acceptance criteria.

RCA 2026-07-21 (issue #357 on a private product lane, two RCA copies; the product is named in the
source RCAs, not here -- this repo is a public cut). Nothing constrained the ORACLE used to verify
an item at closure. The canonical spec was frozen out of the run set, the executed specs were authored to
the divergent implementation, and the agent -- asked to verify -- adopted the only live oracle
left: the implementation itself ("verification within the shipped model"). It then reframed failed
acceptance-criteria lines as scope deferrals. A human caught it by quoting the AC lines back.

Done moves already required evidence to EXIST (`goal_tracker_post_done_evidence`, any non-empty
string passes) and still do. What is new here is that the evidence must be measured against
something the implementation cannot move: the criteria written on the linked issue.

Two properties carry the weight, and both have a test that fails if they are lost:

- **Matching is injective, not counted.** N identical or paraphrased rows can never cover N
  distinct criteria (case 5). A count-based check passes the exact evidence #357 produced.
- **The forbidden-phrase list is a tripwire, not the control.** A reworded evasion is still refused
  by the table check (case 7), so nobody can weaken the matcher and lean on the phrases.

The seam matters as much as the check: the gate runs as a PRE-FLIGHT, before the board-backed
subtask loop issues its first `gh project item-edit`. Case 11 is the test that catches a regression
to the v1 seam (inside `goal_tracker_post_done_evidence`), which fires only after subtasks have
already moved to done.
"""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

AC_HEADINGS = ["acceptance criteria", "acceptance"]

# Four top-level criteria under a title-case level-2 heading.
AC_BODY = """# Digest scheduler

Some preamble prose that is not a criterion.

## Acceptance Criteria

- The scheduler runs three windows per day
- Users receive a digest email every morning
- The dashboard shows the last successful run time
- Failures are retried twice before alerting

## Notes

Unrelated trailing section.
"""

CRITERIA = [
    "The scheduler runs three windows per day",
    "Users receive a digest email every morning",
    "The dashboard shows the last successful run time",
    "Failures are retried twice before alerting",
]


def _table(rows: list[tuple[str, str]], heading: str = "## AC Verification") -> str:
    lines = [heading, "", "| Criterion | Verdict |", "| --- | --- |"]
    lines += [f"| {criterion} | {verdict} |" for criterion, verdict in rows]
    return "\n".join(lines) + "\n"


def _all_pass() -> str:
    return _table([(criterion, "PASS") for criterion in CRITERIA])


def _issues(
    cli,
    evidence: str,
    body: str = AC_BODY,
    headings: list[str] | None = None,
) -> list[str]:
    return cli.done_evidence_ac_table_issues(evidence, body, list(headings or AC_HEADINGS))


# --- The check lives where the closure walker looks for it ---------------------------------------


# --- Case 0 (packet extra): the extractor is not silently empty ----------------------------------


# --- Case 1: a complete honest table passes ------------------------------------------------------


# --- Case 2: no table at all ---------------------------------------------------------------------


# --- Case 3: a FAIL row refuses ------------------------------------------------------------------


# --- Case 4: DEFERRED / PARTIAL / N/A are not rows -----------------------------------------------


# --- Case 5: matching is injective, not counted --------------------------------------------------


IDENTICAL_ROW_BODY = """## Acceptance Criteria

- ships correctly
- the digest email is sent nightly
- the dashboard shows the last successful run time
- failures are retried twice before alerting
"""


# --- Codex R2: the strictest verdict wins, and a piped criterion round-trips ----------------------


PIPED_BODY = """## Acceptance Criteria

- Support A | B imports
- The dashboard shows the last successful run time
"""


# --- Case 6: nested sub-bullets are ONE criterion ------------------------------------------------


NESTED_BODY = """## Acceptance Criteria

- The pipeline is observable end to end
    - metrics are emitted per stage
    - traces are sampled at one percent
    - logs carry the run id
"""

SHALLOW_NESTED_BODY = NESTED_BODY.replace("    - ", "  - ")


# --- Codex R1 P1: the blank form must not verify itself ------------------------------------------


# --- Case 7: the tripwire is not load-bearing ----------------------------------------------------


# --- Case 8: anti-inert -- markdown_section() would ship this gate green and dead -----------------


# --- Case 9: no AC section on the issue ----------------------------------------------------------


# --- The repo helper the fetch needs -------------------------------------------------------------


# --- Plumbing: the pre-flight seam, the knob, the fetch ------------------------------------------


def _item(*, number: int = 7, repo: str = "example-org/example-saas", body: str = "") -> dict:
    content: dict = {"url": f"https://github.com/{repo}/issues/{number}"}
    if body:
        content["body"] = body
    return {
        "id": "ITEM1",
        "content": content,
        "url": "https://github.com/orgs/example-org/projects/1?pane=item",
    }


def _project(cli, *, ac_table: str = "warn") -> dict:
    data = cli.load_project(EXAMPLE_ADAPTER)
    data["backlogProvider"]["doneEvidence"] = {"acTable": ac_table}
    return data


def _harness(
    cli,
    monkeypatch,
    *,
    item: dict,
    body: str,
    body_code: int = 0,
    body_err: str = "",
    subtasks: list[dict] | None = None,
):
    """Record every `gh` argv the done move actually issues.

    The board READS are stubbed at their own helper so the real mutation calls -- `gh project
    item-edit` from `goal_tracker_update_status`, and the comment POST from
    `stakeholder_issue_post_comment` -- still travel through `run_command` and land in this list.
    Stubbing the mutations themselves would make case 11 assert on the test double instead of on
    the code, and it would pass with the gate deleted.
    """
    calls: list[list[str]] = []

    def _run(command, cwd=None, timeout=None, **kwargs):
        calls.append(list(command))
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            if body_code != 0:
                return body_code, "", body_err
            return 0, body, ""
        if command[:2] == ["gh", "api"]:
            comment = {"html_url": "https://github.com/example-org/example-saas/issues/7#c1"}
            return 0, json.dumps(comment), ""
        return 0, "{}", ""

    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda *a, **k: [])
    monkeypatch.setattr(
        cli,
        "goal_tracker_project_fields",
        lambda *a, **k: [{"name": "Status", "id": "FIELD1", "options": [{"name": "Done", "id": "OPT1"}]}],
    )
    monkeypatch.setattr(cli, "github_backlog_board_identity", lambda *a, **k: {"id": "PROJ1"})
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *a, **k: item)
    monkeypatch.setattr(cli, "goal_tracker_board_backed_subtasks", lambda *a, **k: list(subtasks or []))
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda *a, **k: "CLOSED")
    monkeypatch.setattr(cli, "github_cache_invalidate_project", lambda *a, **k: None)
    return calls


def _mutations(calls: list[list[str]]) -> list[list[str]]:
    return [
        call
        for call in calls
        if call[:3] == ["gh", "project", "item-edit"]
        or (call[:2] == ["gh", "api"] and "--method" in call and "POST" in call)
        or call[:3] == ["gh", "issue", "comment"]
    ]


def test_the_knob_defaults_to_warn(cli) -> None:
    data = cli.load_project(EXAMPLE_ADAPTER)
    assert data["backlogProvider"]["doneEvidence"]["acTable"] == "warn"


# --- Case 11: a refused done move mutates nothing ------------------------------------------------


# --- F9: the subtask call site is excluded -------------------------------------------------------


SUBTASK_AC_BODY = """## Acceptance Criteria

- the subtask has its very own acceptance criterion
"""


# --- Case 12: the fetch can fail, and it must say so ---------------------------------------------


# --- Case 13: the repo comes from the issue URL, never from the adapter --------------------------


# --- The comment surface, which had no behavioral test at all --------------------------------------


CLAIMING_COMMENT = """## Verification Evidence

Everything checked out end to end.
"""


OVERLAPPING_BODY = """## Acceptance Criteria

- support csv import
- support csv import preview
"""
