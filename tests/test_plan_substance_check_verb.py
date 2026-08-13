"""Item 80: `plan-substance-check`, the explicit answer to "is this plan finished".

Distinct from the R1 pre-gate, which answers "may I launch a round". The knob softens the seam;
it does NOT soften this verb -- an explicit check that exits 0 on a failing plan is a check
nobody can trust.
"""

from __future__ import annotations

import argparse


def _args(**kw):
    base = {"target": kw.pop("target"), "plan": kw.pop("plan", ""), "list": kw.pop("list", False)}
    base.update(kw)
    return argparse.Namespace(**base)


def _good_plan() -> str:
    """A fixture that genuinely satisfies the contract, built from the requirement list rather
    than from an assumption about it.

    Worth recording why it is not a real published plan: NONE of the plans in this repo's own
    `docs/superpowers/plans/` pass this check. That is not a flaw in the verb -- it is exactly the
    gap backlog item 97 records, that plans reach `ready/` in a state the framework's own gate
    refuses and nothing catches it until a builder has already claimed the slot. This verb is part
    of what closes that.
    """
    body = "\n".join(f"Detail line {i} covering scope, evidence and rationale." for i in range(120))
    return f"""# Milestone goal

Ship the content pre-gate so plan problems surface while fixing them is still free.

## Non-goals

Flipping the default to block. That is a named successor, gated on a template release.

## Evidence

RCA links and measured counts: items 57, 62 and 75 each lost plan work to late refusal.

## Assumptions

The adapter is readable and the lane has a plan path inside its target.

## Ordered scope

1. The knob and its normalizer.
2. The pre-gate above the lease.
3. The explicit verb.

## Dependencies

W1.3 (items 76+77) must be merged: the pre-gate sits above its lease acquisition.

## Workstreams

WS1 (parallel-safe) -> WS2 (hard-predecessor on WS1) -> WS3 (parallel-safe).
A dependency graph, stated so spend can be routed and slots can be claimed independently.

## Tasks

- T1.1 write the failing tests -- model-tier: standard
- T1.2 extract the predicate and place the gate -- model-tier: deep
- T1.3 register the verb -- model-tier: mechanical

Use best judgment throughout; record non-obvious calls with `decision-record`.

## Acceptance criteria

A section-shaped gap warns by default and refuses under block, and never mid-loop.

## Tests and validation

Both new suites green; W1.3's lease suite green with zero edits.

## Definition of done

Merged with CI green and the ledger committed.

## Risks

A default of block would refuse plans that were about to be fine.

## Rollback

Repin below the release; the knob is read-side only and absent stays absent.

{body}
"""


def test_the_list_needs_no_adapter(cli, tmp_path, capsys) -> None:
    """A lane asking WHAT the requirements are may not have a lane yet. Putting the answer behind
    an adapter would gate it on the very setup the answer is about."""
    rc = cli.plan_substance_check(_args(target=tmp_path, list=True))

    out = capsys.readouterr().out
    assert rc == 0
    assert "plan_substance_requirements:" in out
    assert "acceptance criteria" in out


def test_a_complete_plan_passes_and_says_what_it_checked(cli, tmp_path, capsys) -> None:
    """A green run that says nothing lets a lane mistake 'the command ran' for 'the contract is
    met'."""
    plan = tmp_path / "plan.md"
    plan.write_text(_good_plan(), encoding="utf-8")

    rc = cli.plan_substance_check(_args(target=tmp_path, plan="plan.md"))

    assert rc == 0, capsys.readouterr().err
    assert "satisfies" in capsys.readouterr().out


def test_a_thin_plan_is_refused_with_its_gaps_named(cli, tmp_path, capsys) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\nnothing here.\n", encoding="utf-8")

    rc = cli.plan_substance_check(_args(target=tmp_path, plan="plan.md"))

    err = capsys.readouterr().err
    assert rc == 1
    assert "plan_substance_check_issue:" in err
    assert "before R1" in err and "void no evidence" in err, "say the fix is still free"


def test_containment_refuses_before_the_read(cli, tmp_path, capsys) -> None:
    """F7. A `--plan` escaping the target must refuse as a PATH error, not be read and then
    judged -- the judgement would be about a file this lane was never allowed to see."""
    rc = cli.plan_substance_check(_args(target=tmp_path, plan="../../../etc/hosts"))

    assert rc == 1
    assert "plan_substance_check_error:" in capsys.readouterr().err


def test_a_missing_plan_is_an_error_not_a_pass(cli, tmp_path, capsys) -> None:
    rc = cli.plan_substance_check(_args(target=tmp_path, plan="nope.md"))

    assert rc == 1
    assert "no plan at" in capsys.readouterr().err


def test_the_verb_is_not_softened_by_the_pregate_knob(cli, tmp_path, capsys) -> None:
    """The knob decides whether the R1 SEAM refuses. This verb answers a different question, and
    an explicit check that exits 0 on a failing plan is worse than no check."""
    import inspect

    source = inspect.getsource(cli.plan_substance_check)

    # The behaviour, not the text: the docstring MENTIONS the knob to explain why it does not
    # consult it, so a bare string search would fail on the very comment that documents the rule.
    body = source[source.index('"""', source.index('"""') + 3):]
    assert "normalize_planning_content_pregate" not in body, "the verb never reads the knob"
    assert "plan_review_content_pregate" not in body

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\nthin.\n", encoding="utf-8")
    assert cli.plan_substance_check(_args(target=tmp_path, plan="plan.md")) == 1


def test_the_verb_is_registered(cli) -> None:
    """The pre-gate's recovery text names this command; a named continuation that does not exist
    is the dead end this framework refuses to ship."""
    import inspect

    source = inspect.getsource(cli)

    assert '"plan-substance-check"' in source
    assert "plan_substance_p.set_defaults(func=plan_substance_check)" in source
