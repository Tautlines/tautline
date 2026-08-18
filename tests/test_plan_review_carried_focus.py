"""WS1 T1.2: a carried plan-review blocker is BINDING on implementation review.

The release valve (T1.1) is only safe because the findings it releases past become obligations in
a medium where they can be falsified against an artifact. A carry that implementation review could
ignore would be a deferral with a better name, and the deferral is precisely what the source RCA
measured. So implementation review must re-test each carried Critical/P1 and say what it found.

REPORTED, NOT REFUSED, in this release. An earlier draft refused a push-eligible verdict while a
carried finding was unaccounted for; that gate was removed because deciding WHICH implementation
review owes a given plan's findings needs a durable plan-to-implementation lineage this codebase
does not have, and a gate an unstaged edit can bypass is worse than no gate. This docstring used to
describe the refusal, which made it a statement about a draft rather than about the shipped code.

Every test here fails without the change -- asserted as a difference against the same run without a
carried finding wherever the shipped behaviour is "report, and change nothing else", because an
absolute assertion on a report-only path is satisfied by the unchanged code.
"""

import json
import pathlib

from _classified_findings_fixtures import (
    SOURCE_OF_TRUTH,
    adapter,
    evidence_check,
    finalize,
    lane,
)


PLAN_REL = "widen-the-export-throttle.md"


def _capped_manifest(
    cli,
    subject,
    *,
    severity: str = "critical",
    binding: bool = True,
    focus_id: str = "R1",
    recorded_by: str = "tautline finalize-plan-review",
    plan: str | None = None,
) -> str:
    """Write a capped plan-review manifest into the lane and return its focus key."""
    reviews = subject.target / SOURCE_OF_TRUTH / ".plan-reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": cli.PLAN_REVIEW_SCHEMA,
        "recorded_by": recorded_by,
        "plan_path": plan or PLAN_REL,
        "verdict": cli.PLAN_REVIEW_CAPPED_VERDICT,
        "asserted_verdict": "blocked",
        "unresolved_critical_count": 1,
        "unresolved_p1_count": 0,
        "classified_findings": [
            {
                "id": focus_id,
                "focus_id": focus_id,
                "severity": severity,
                "status": cli.PLAN_REVIEW_CARRIED_STATUS,
                "summary": "the export retry loop is unbounded",
                "binding": binding,
                "carried_to": cli.PLAN_REVIEW_CARRY_TARGET,
                "carried_at_round": 4,
            }
        ],
    }
    stem = pathlib.PurePosixPath(plan).stem if plan else "widen-the-export-throttle"
    (reviews / f"{stem}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return cli.plan_review_focus_key(plan or PLAN_REL, focus_id)


def test_a_carried_critical_reaches_the_focus_list_as_binding(cli, tmp_path):
    subject = lane(cli, tmp_path)
    key = _capped_manifest(cli, subject)

    items = cli.plan_review_carried_focus_items(adapter(), subject.target)

    assert [item["focus_key"] for item in items] == [key]
    assert items[0]["binding"] is True
    assert items[0]["severity"] == "critical"
    assert "(BINDING; re-test against the code)" in cli.plan_review_carried_focus_lines(items)[0]


def test_an_unbinding_carried_finding_is_not_billed(cli, tmp_path):
    """`binding: false` is not a shape this writer produces; if one appears, it is advisory."""
    subject = lane(cli, tmp_path)
    _capped_manifest(cli, subject, binding=False)

    assert cli.plan_review_carried_focus_items(adapter(), subject.target) == []


def test_an_untrusted_recorder_cannot_manufacture_a_binding_obligation(cli, tmp_path):
    subject = lane(cli, tmp_path)
    _capped_manifest(cli, subject, recorded_by="hand-written")

    assert cli.plan_review_carried_focus_items(adapter(), subject.target) == []


def test_a_blocked_verdict_is_never_gated_on_carried_findings(cli, monkeypatch, capsys, tmp_path):
    """`blocked` stays the cheapest verdict to record honestly.

    Asserted as a DIFFERENCE against the same finalize with no capped manifest in the lane, not
    against a fixed exit code. The previous version of this test asserted `rc == 1` plus the
    absence of a string (`is binding, not advisory`) that occurs nowhere in the repository, so it
    could not fail: it passed with the whole feature deleted, and `rc == 1` is what `blocked`
    returns anyway. Comparing the two lanes is what actually pins "carried findings do not change
    the outcome" -- add a gate here and the codes diverge.
    """
    without_carry = lane(cli, tmp_path / "without")
    baseline = finalize(cli, monkeypatch, without_carry, verdict="blocked", critical=1)
    capsys.readouterr()

    subject = lane(cli, tmp_path / "with")
    _capped_manifest(cli, subject)
    rc = finalize(cli, monkeypatch, subject, verdict="blocked", critical=1)
    err = capsys.readouterr().err

    assert rc == baseline == 1  # blocked is always a non-push-eligible exit, carry or no carry
    # ...and the carried obligation is still REPORTED on the blocked path, not silently dropped.
    assert "implementation_review_focus:" in err
    assert "(BINDING" in err


def test_the_push_gate_reports_an_unaccounted_carried_finding(cli, monkeypatch, capsys, tmp_path):
    """Detection at the LAST gate too -- REPORTED, not refused.

    This release deliberately does not refuse here. Deciding which implementation review owes a
    given plan's findings needs a durable plan-to-implementation lineage the framework does not
    have, and three review rounds found eight ways the substitutes for it could be bypassed by an
    unstaged edit or could charge an unrelated branch. So the finding is printed at every gate and
    the refusal waits for the follow-up: a gate that reports success while doing nothing is the
    failure this program exists to remove, and one that blocks the wrong lane is no better.
    """
    subject = lane(cli, tmp_path)
    # A finished, push-eligible review -- recorded BEFORE the carried finding existed, which is
    # exactly how a review comes to ignore one.
    assert finalize(cli, monkeypatch, subject, verdict="clean") == 0, capsys.readouterr().err
    key = _capped_manifest(cli, subject)
    capsys.readouterr()

    rc = evidence_check(cli, monkeypatch, subject, strict=True)

    # Even under --strict: reported, and the gate still passes.
    assert rc == 0
    err = capsys.readouterr().err
    assert key in err
    assert "(BINDING; re-test against the code)" in err
    assert "REPORT-ONLY in this release" in err


def test_a_lane_that_never_capped_a_plan_review_owes_nothing(cli, monkeypatch, capsys, tmp_path):
    """The gate must be invisible to every lane that never hit the plan-review cap."""
    subject = lane(cli, tmp_path)

    assert cli.plan_review_carried_focus_items(adapter(), subject.target) == []
    assert finalize(cli, monkeypatch, subject, verdict="clean") == 0, capsys.readouterr().err
