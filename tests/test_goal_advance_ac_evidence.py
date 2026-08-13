"""Item 81 T1.4: `goal-advance` gets an evidence channel, so the closure gate has no dead end.

`goal-advance` is the PRIMARY autonomous closure path and, before this item, had no operator
evidence channel at all -- its done evidence was machine-composed by
`goal_tracker_done_evidence_for_transition`. Gating done moves on an AC table without opening this
channel would refuse the one path an unattended lane actually uses, and name nothing runnable on
it. That is the item-48 no-dead-ends failure mode, arriving through the front door.

One channel here: the three `--verification-evidence*` flags, mirroring `goal-tracker-update` and
composed through the same helper so file reading and URL validation keep one definition. The
milestone `acVerification` key and its precedence rules are a separate release. One non-negotiable:
with nothing supplied, the composed evidence is BYTE-IDENTICAL to what every existing ledger
produced before this release.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

TABLE = """## AC Verification

| Criterion | Verdict |
| --- | --- |
| the scheduler runs three windows per day | PASS |
"""

AC_ONE_CRITERION = "## Acceptance Criteria\n\n- the scheduler runs three windows per day\n"

EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

MILESTONE = {
    "index": 1,
    "title": "Ship the digest scheduler",
    "status": "complete",
    "validationEvidence": ["scripts/test.sh green at 5310"],
    "milestoneRun": ".ai-runs/milestone-1.json",
}


# --- Byte-identical when nothing is supplied -----------------------------------------------------


@pytest.mark.parametrize("event", ["milestone-complete", "goal-complete", "milestone-started"])
def test_composition_is_byte_identical_without_a_table(cli, event: str) -> None:
    """The regression this test exists to catch is a silent one: a composition that gains a blank
    line or reorders its parts changes every done-evidence comment the framework has ever posted,
    and nothing else in the suite would notice."""
    expected = {
        "milestone-complete": "scripts/test.sh green at 5310\n\nMilestone run: .ai-runs/milestone-1.json",
        "goal-complete": "the goal shipped",
        "milestone-started": "",
    }[event]

    assert cli.goal_tracker_done_evidence_for_transition(event, "the goal shipped" if event == "goal-complete" else "", dict(MILESTONE)) == expected
    assert cli.goal_tracker_done_evidence_for_transition(
        event, "the goal shipped" if event == "goal-complete" else "", dict(MILESTONE), ac_verification=""
    ) == expected


# --- The table lands ahead of the `Milestone run:` line ------------------------------------------


def test_the_table_is_composed_ahead_of_the_milestone_run_line(cli) -> None:
    composed = cli.goal_tracker_done_evidence_for_transition(
        "milestone-complete", "", dict(MILESTONE), ac_verification=TABLE
    )

    assert "| the scheduler runs three windows per day | PASS |" in composed
    assert composed.index("AC Verification") < composed.index("Milestone run:"), (
        "the table is the verification; the run link is its provenance and reads last"
    )


def test_goal_complete_also_carries_the_table(cli) -> None:
    composed = cli.goal_tracker_done_evidence_for_transition(
        "goal-complete", "the goal shipped", None, ac_verification=TABLE
    )

    assert composed.startswith("the goal shipped")
    assert "AC Verification" in composed


def test_a_table_already_present_in_validation_evidence_is_not_duplicated(cli) -> None:
    milestone = dict(MILESTONE, validationEvidence=[TABLE.strip()])

    composed = cli.goal_tracker_done_evidence_for_transition(
        "milestone-complete", "", milestone, ac_verification=TABLE
    )

    assert composed.count("AC Verification") == 1


# --- The flags exist on the path the refusal names -----------------------------------------------


def _help(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(CLI), *args, "--help"],
        cwd=REPO_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "COLUMNS": "120"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    "flag", ["--verification-evidence", "--verification-evidence-file", "--verification-evidence-url"]
)
def test_goal_advance_accepts_the_evidence_flags(flag: str) -> None:
    """`tests/test_refusal_continuations.py` proves a refusal names a flag that EXISTS. This proves
    the flag exists on `goal-advance` specifically, which is the path the closure refusal is most
    likely to be read on."""
    assert flag in _help("goal-advance")


def test_the_three_done_verbs_all_carry_the_channel() -> None:
    for verb in ["goal-advance", "goal-tracker-update", "backlog-provider-update"]:
        assert "--verification-evidence-file" in _help(verb), f"{verb} has no evidence channel"


def test_goal_advance_reads_the_flags_through_the_shared_composer(cli, tmp_path) -> None:
    """One definition: `goal-advance` resolves its evidence with the SAME
    `backlog_provider_done_evidence_text` the other two done verbs use, so the three paths cannot
    drift in how they read a file or validate a URL."""
    evidence_file = tmp_path / "ac.md"
    evidence_file.write_text(TABLE, encoding="utf-8")
    args = argparse.Namespace(
        verification_evidence="",
        verification_evidence_file=evidence_file,
        verification_evidence_url="https://example.com/run/1",
    )

    resolved = cli.backlog_provider_done_evidence_text(args, tmp_path)

    assert "| the scheduler runs three windows per day | PASS |" in resolved
    assert "Verification artifact: https://example.com/run/1" in resolved


# --- The transition path itself refuses and passes ------------------------------------------------


AC_BODY = """## Acceptance Criteria

- the scheduler runs three windows per day
"""


def _sync_harness(cli, monkeypatch, *, body: str):
    item = {"id": "ITEM1", "content": {"url": "https://github.com/example-org/example-saas/issues/7"}}

    def _run(command, cwd=None, timeout=None, **kwargs):
        if command[:3] == ["gh", "issue", "view"]:
            return 0, body, ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://example.com/c"}), ""
        return 0, "{}", ""

    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda *a, **k: [])
    monkeypatch.setattr(
        cli,
        "goal_tracker_project_fields",
        lambda *a, **k: [{"name": "Status", "id": "F1", "options": [{"name": "Done", "id": "O1"}]}],
    )
    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda *a, **k: {"id": "P1"})
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *a, **k: item)
    monkeypatch.setattr(cli, "goal_tracker_board_backed_subtasks", lambda *a, **k: [])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda *a, **k: "CLOSED")
    monkeypatch.setattr(cli, "github_cache_invalidate_project", lambda *a, **k: None)
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda *a, **k: "ITEM1")
    monkeypatch.setattr(cli, "goal_tracker_milestone_ref", lambda *a, **k: "ITEM1")


def _project(cli, *, ac_table: str) -> dict:
    data = cli.load_project(EXAMPLE_ADAPTER)
    data["backlogProvider"]["doneEvidence"] = {"acTable": ac_table}
    return data


def test_the_transition_is_refused_under_strict_without_a_table(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli, ac_table="strict")
    _sync_harness(cli, monkeypatch, body=AC_BODY)
    run = {"status": "complete", "milestones": [dict(MILESTONE)]}

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_sync_transition(
            data,
            tmp_path,
            run,
            "milestone-complete",
            dict(MILESTONE),
            done_evidence=cli.goal_tracker_done_evidence_for_transition("milestone-complete", "", dict(MILESTONE)),
        )

    message = str(raised.value)
    assert "done_evidence_ac_error:" in message
    # No dead end: the refusal names a verb that exists AND a flag that exists on this path.
    assert "tautline ac-verify" in message
    assert "--verification-evidence-file" in message


def test_the_transition_passes_with_the_table_supplied(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli, ac_table="strict")
    _sync_harness(cli, monkeypatch, body=AC_BODY)
    run = {"status": "complete", "milestones": [dict(MILESTONE)]}

    cli.goal_tracker_sync_transition(
        data,
        tmp_path,
        run,
        "milestone-complete",
        dict(MILESTONE),
        done_evidence=cli.goal_tracker_done_evidence_for_transition(
            "milestone-complete", "", dict(MILESTONE), ac_verification=TABLE
        ),
    )


def test_the_closure_gate_runs_before_goal_advance_posts_its_ui_comment(cli) -> None:
    """Codex R3 P2, pinned structurally because the ordering IS the property.

    `goal-advance` posts a required UI-proof comment before it syncs the transition. With the
    closure gate only inside the transition, a refused completion happened after that comment was
    already public -- the same "a refused done move mutates nothing" property the pre-flight seam
    exists to hold, broken one caller up. The pre-flight call must therefore appear BEFORE the
    ui_comment_required block in the source.
    """
    source = inspect.getsource(cli.goal_advance)

    preflight = source.index("goal_advance_closure_preflight(")
    ui_block = source.index("if ui_comment_required:")
    transition = source.index("goal_tracker_sync_transition(")

    assert preflight < ui_block < transition, (
        "the closure pre-flight must run before any comment goal-advance posts"
    )

    # And it must cover the SUBTASKS this transition will auto-close, not just the parent. Codex R2:
    # hoisting only the parent left the subtask refusal inside the transition, which runs after the
    # required UI proof is already public -- a mutation before a refusal, by the seam that exists to
    # prevent exactly that.
    hoist = inspect.getsource(cli.goal_advance_closure_preflight)
    assert "goal_tracker_preflight_done_subtask_ac_evidence(" in hoist, (
        "the hoist must judge auto-closed subtasks too"
    )
    assert "goal_tracker_board_backed_subtasks(" in hoist


def test_the_transition_is_told_the_gate_already_ran(cli) -> None:
    """And exactly once: a second run would fetch the issue body twice and print a duplicate state
    line for the same decision."""
    source = inspect.getsource(cli.goal_advance)

    assert "ac_checked=True" in source

    funnel = inspect.getsource(cli.goal_tracker_update_status_with_done_evidence)
    assert "if not ac_checked:" in funnel, (
        "every entry point other than goal-advance must still be gated in the funnel"
    )


def test_the_composition_matches_goal_advance(cli) -> None:
    """Structural pin: the evidence `goal_advance` resolves must actually reach the composer, and
    it must keep resolving it through the one shared helper."""
    source = inspect.getsource(cli.goal_advance)

    assert source.count("backlog_provider_done_evidence_text(") == 1
    # LOAD-BEARING, and the only coverage of this branch's headline plumbing. No test here invokes
    # goal_advance() with the flags -- the composer is tested in isolation and the transition tests
    # hand-compose their evidence -- so a mutant that resolves `supplied` and then calls the
    # composer WITHOUT the kwarg silently discards every flag and passes the entire suite. This
    # assertion is what stands there.
    assert "ac_verification=supplied" in source, "the resolved evidence must reach the composer"


def test_a_correction_appended_after_a_stale_entry_decides(cli) -> None:
    """The correction path, now judged where the criteria are known.

    0.56.0 tried to decide this at COMPOSE time and could not: two rows can each name the same
    criterion without naming each other, and the composer has no criteria. Nothing is dropped from
    the posted evidence any more -- the gate simply takes the LAST verdict recorded against each
    criterion, and a correction is appended after what it corrects.
    """
    stale = TABLE.replace("PASS", "FAIL")
    composed = cli.goal_tracker_done_evidence_for_transition(
        "milestone-complete", "", dict(MILESTONE, validationEvidence=[stale]), ac_verification=TABLE
    )

    assert "| FAIL |" in composed, "the stale entry stays in the posted evidence, for the reader"

    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))
    assert cli.done_evidence_ac_table_issues(composed, AC_ONE_CRITERION, headings) == []


def test_a_paraphrased_correction_cannot_clear_a_failure(cli) -> None:
    """The deliberate cost of failing closed, stated rather than discovered.

    A correction written as a PARAPHRASE of the criterion no longer clears a recorded FAIL -- only a
    row naming the criterion outright does, by repeating its text or keying its index. Five review
    rounds spent trying to be cleverer than this produced four FALSE ACCEPTANCES, each introduced by
    the previous round's fix, so the ambiguity is resolved against the closure. The documented
    remedy is unaffected: `ac-verify` emits the criterion text verbatim.
    """
    body = "## Acceptance Criteria\n\n- the scheduler runs three windows per day and sends alerts\n"
    paraphrased = "| the scheduler runs three windows per day | FAIL |\n\n| day and sends alerts | PASS |\n"
    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))

    assert cli.done_evidence_ac_table_issues(paraphrased, body, headings), (
        "an ambiguous row must not clear a failure it might not be about"
    )

    outright = (
        "| the scheduler runs three windows per day | FAIL |\n\n"
        "| the scheduler runs three windows per day and sends alerts | PASS |\n"
    )
    assert cli.done_evidence_ac_table_issues(outright, body, headings) == []


def test_a_pass_written_above_a_fail_still_fails(cli) -> None:
    """Unweakened: the reframe-a-failure mechanism this item exists to stop. Ordering means "later
    corrects earlier", not "whichever verdict you would prefer"."""
    composed = "| the only criterion here | PASS |\n| the only criterion here | FAIL |\n"
    body = "## Acceptance Criteria\n\n- the only criterion here\n"

    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))
    issues = cli.done_evidence_ac_table_issues(composed, body, headings)

    assert len(issues) == 1
    assert "FAILED AC" in issues[0]


def test_unrelated_validation_evidence_is_never_dropped(cli) -> None:
    """Nothing is dropped at all now -- the composer only appends."""
    milestone = dict(MILESTONE, validationEvidence=["scripts/test.sh green at 5507", "coverage 91%"])

    composed = cli.goal_tracker_done_evidence_for_transition(
        "milestone-complete", "", milestone, ac_verification=TABLE
    )

    assert "scripts/test.sh green at 5507" in composed
    assert "coverage 91%" in composed
    assert "AC Verification" in composed


def test_a_supplemental_matrix_never_affects_the_verdict(cli) -> None:
    """The 0.56.0 false refusal, from the other side: a CI matrix names none of the criteria, so it
    cannot displace anything and cannot change any verdict."""
    body = "## Acceptance Criteria\n\n- the scheduler runs three windows per day\n"
    composed = (
        "| the scheduler runs three windows per day | PASS |\n\n"
        "## Test Results\n\n| test_scheduler | FAIL |\n"
    )

    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))

    assert cli.done_evidence_ac_table_issues(composed, body, headings) == []


def test_a_correction_identical_to_earlier_evidence_still_lands_last(cli) -> None:
    """Codex R1 P2. De-duplication is right for validationEvidence and wrong for the correction:
    when a lane re-supplies text that already appears earlier, dropping it as a duplicate leaves the
    stale FAIL as the last verdict, so the correction is refused by the gate it was meant to clear.
    """
    stale = TABLE.replace("PASS", "FAIL")
    milestone = dict(MILESTONE, validationEvidence=[TABLE, stale])

    composed = cli.goal_tracker_done_evidence_for_transition(
        "milestone-complete", "", milestone, ac_verification=TABLE
    )

    assert composed.rindex("| PASS |") > composed.rindex("| FAIL |"), (
        "the supplied correction must be the last verdict"
    )
    headings = cli.done_evidence_ac_headings(cli.load_project(EXAMPLE_ADAPTER))
    assert cli.done_evidence_ac_table_issues(composed, AC_ONE_CRITERION, headings) == []


# --- The milestone acVerification channel ---------------------------------------------------------


def test_an_inline_milestone_ac_verification_is_used(cli, tmp_path) -> None:
    assert cli.milestone_ac_verification_text(tmp_path, dict(MILESTONE, acVerification=TABLE)) == TABLE.strip()


def test_a_milestone_ac_verification_path_is_read_at_compose_time(cli, tmp_path) -> None:
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "ac.md").write_text(TABLE, encoding="utf-8")

    assert cli.milestone_ac_verification_text(tmp_path, dict(MILESTONE, acVerification="evidence/ac.md")) == TABLE.strip()


def test_an_absent_milestone_key_stays_absent(cli, tmp_path) -> None:
    assert cli.milestone_ac_verification_text(tmp_path, dict(MILESTONE)) == ""
    assert cli.milestone_ac_verification_text(tmp_path, None) == ""
    assert "acVerification" not in MILESTONE


def test_a_one_line_value_that_is_not_a_file_is_treated_as_inline_text(cli, tmp_path) -> None:
    """Refusing evidence a lane really wrote inline, because it looks path-shaped, is worse than
    reading it as prose."""
    assert cli.milestone_ac_verification_text(tmp_path, {"acVerification": "| all four | PASS |"}) == (
        "| all four | PASS |"
    )


@pytest.mark.parametrize("value", ["/etc/passwd", "../secret.txt", "~/secret.txt"])
def test_an_out_of_tree_ac_verification_path_is_refused(cli, tmp_path, value: str) -> None:
    """The goal ledger is repo-controlled data and whatever this key names is appended to done
    evidence and POSTED to the linked issue, so an absolute, `~`, or `../` value would turn a
    completion into a file-exfiltration primitive against anything the lane can read."""
    (tmp_path / "secret.txt").write_text("SENSITIVE\n", encoding="utf-8")
    inside = tmp_path / "repo"
    inside.mkdir()

    with pytest.raises(SystemExit) as raised:
        cli.milestone_ac_verification_text(inside, {"acVerification": value})

    message = str(raised.value)
    assert "done_evidence_ac_error:" in message
    assert "SENSITIVE" not in message, "the refusal must not echo the file it refused to read"
    assert "tautline ac-verify" in message, "a refusal with no next command is a dead end"


def test_a_symlink_out_of_the_tree_is_refused(cli, tmp_path) -> None:
    """Resolved, never string-prefix matched: a repo-relative NAME can still point outside."""
    secret = tmp_path / "secret.txt"
    secret.write_text("SENSITIVE\n", encoding="utf-8")
    inside = tmp_path / "repo"
    inside.mkdir()
    (inside / "ac.md").symlink_to(secret)

    with pytest.raises(SystemExit) as raised:
        cli.milestone_ac_verification_text(inside, {"acVerification": "ac.md"})

    assert "done_evidence_ac_error:" in str(raised.value)
    assert "SENSITIVE" not in str(raised.value)


def test_containment_runs_through_the_shared_primitive(cli) -> None:
    """sec-config-path-1 has ONE implementation. This value is repo-controlled ledger data, so it
    belongs on the contained `configured_path` and not on its uncontained sibling `cli_path`; a
    second hand-rolled copy of the check is how the two drift apart."""
    source = inspect.getsource(cli.milestone_ac_verification_text)

    assert "configured_path(target, raw)" in source
    assert "cli_path(" not in source
    assert "is_relative_to" not in source, "do not re-implement the containment comparison here"


def test_the_completion_guard_accepts_the_ac_table_as_evidence(cli) -> None:
    """Codex R1 P2: the no-flag channel is unreachable unless the milestone-complete evidence guard
    counts `acVerification` as evidence. It is evidence -- an AC verdict table is the strongest form
    this command accepts -- and a feature whose only entry point is closed by a guard one block up
    is not a feature."""
    source = inspect.getsource(cli.goal_advance)
    guard = source[source.index('elif args.event == "milestone-complete":'):]
    guard = guard[: guard.index("update_blocker")]

    assert 'milestone.get("acVerification")' in guard
    assert "ac-verify" in guard, "the refusal must still name a runnable way to produce one"


def test_goal_advance_appends_the_milestone_table_before_the_flags(cli) -> None:
    """Structural pin: both sources are appended, milestone FIRST, so a flag correction supplied at
    the command line lands last and the gate's last-verdict rule lets it decide. There is no
    compose-time precedence and there must not be one -- the composer has no criteria."""
    source = inspect.getsource(cli.goal_advance)

    assert "backlog_provider_done_evidence_text(args, target)" in source
    milestone_at = source.index("            milestone_ac_text,")
    flags_at = source.index("backlog_provider_done_evidence_text(args, target)")
    assert milestone_at < flags_at, "a command-line correction must land after the milestone table"


def test_the_guard_and_the_composition_weigh_the_same_resolved_string(cli) -> None:
    """Codex R2 P2(a): resolved ONCE. The guard must not weigh the key's truthiness while
    composition weighs the resolved text -- that divergence is what let an empty file open the
    guard and then contribute nothing, refusing only after the UI-proof comment was already
    public. One resolution, one local, used in both places: they cannot disagree."""
    source = inspect.getsource(cli.goal_advance)
    disjunction = source[source.index('elif args.event == "milestone-complete":'):]
    disjunction = disjunction[: disjunction.index("raise SystemExit")]

    assert source.count("milestone_ac_verification_text(") == 1, "resolve the value exactly once"
    assert "or milestone_ac_text" in disjunction, "the guard weighs the RESOLVED text"
    assert "or milestone.get(\"acVerification\")" not in disjunction, "never the raw key"


def test_the_value_is_resolved_only_for_the_completing_transition(cli) -> None:
    """Codex R2 P2(b): milestone-started, -blocked and -deferred never use AC verification, so a
    stale or out-of-tree path must not be able to block the very transitions a lane uses to report
    that something is wrong. Resolution lives inside the milestone-complete branch."""
    source = inspect.getsource(cli.goal_advance)
    complete_at = source.index('elif args.event == "milestone-complete":')
    deferred_at = source.index('elif args.event == "milestone-deferred":')
    resolve_at = source.index("milestone_ac_verification_text(")

    assert complete_at < resolve_at < deferred_at
