"""Item 80 WS3: a hint that a plan may be too big to review in one budget.

Never blocking, anywhere, permanently. Sizing is a judgement, and a gate that refuses on a
judgement it cannot justify teaches lanes to game the measure rather than split the work.
"""

from __future__ import annotations

from pathlib import Path

from tautline_methodology.plan_authoring import plan_scope_advisory

REPO_ROOT = Path(__file__).resolve().parents[1]


def _plan(lines=800, tasks=30, workstreams=6) -> str:
    body = "\n".join(f"Prose line {i}." for i in range(lines))
    task_lines = "\n".join(f"- T{i} do the thing -- model-tier: standard" for i in range(tasks))
    ws_lines = "\n".join(f"## WS{i}" for i in range(workstreams))
    return f"{body}\n{task_lines}\n{ws_lines}\n"


def test_all_three_conjuncts_are_required(cli) -> None:
    """ANY SINGLE MEASURE fires constantly on legitimate plans -- a long plan may be thorough,
    many tasks may be mechanical, many workstreams may be genuinely parallel. It is the
    COMBINATION that has predicted a fracture."""
    assert plan_scope_advisory(_plan()) , "all three together does hint"

    assert plan_scope_advisory(_plan(lines=100)) == [], "long alone is not a signal"
    assert plan_scope_advisory(_plan(tasks=2)) == [], "many tasks alone is not a signal"
    assert plan_scope_advisory(_plan(workstreams=1)) == [], "many workstreams alone is not one"


def test_a_compliant_plan_is_silent(cli) -> None:
    """THE ANCHOR. A predicate that nags the plans it was meant to leave alone gets ignored, and
    an ignored advisory is worse than none -- it trains lanes to skip the whole class of message."""
    compliant = (
        "# Milestone goal\n\nSmall, carved, reviewable.\n\n"
        "## WS1\n- T1 -- model-tier: mechanical\n"
    )

    assert plan_scope_advisory(compliant) == []


def test_the_shipped_plan_corpus_does_not_trip_it(cli) -> None:
    """THE OTHER ANCHOR, measured rather than asserted: run the predicate over every plan this
    repo actually ships. A false-positive floor of zero on real, accepted work is the only
    evidence that the thresholds mean anything."""
    plans = sorted((REPO_ROOT / "docs" / "superpowers" / "plans").glob("*.md"))
    assert plans, "the corpus must not be empty, or this test proves nothing"

    tripped = [
        p.name for p in plans
        if plan_scope_advisory(p.read_text(encoding="utf-8", errors="replace"))
    ]

    assert not tripped, f"shipped plans must not trip the sizing hint: {tripped}"


def test_framework_vocabulary_alone_does_not_trip_it(cli) -> None:
    """A document that merely TALKS about workstreams and model tiers -- like this packet, or a
    policy file -- is not a plan with them."""
    prose = "\n".join(
        "The plan-authoring standard describes WS1 through WS9 and model-tier: deep tagging."
        for _ in range(900)
    )

    assert plan_scope_advisory(prose) == [], "prose about the vocabulary is not a large plan"


def test_the_message_says_it_never_refuses(cli) -> None:
    [message] = plan_scope_advisory(_plan())

    assert "ADVISORY ONLY" in message
    assert "nothing here refuses" in message
    assert "allowed to be" in message, "a genuinely large plan is not doing anything wrong"


def test_the_message_carries_its_own_measurements(cli) -> None:
    """A hint that does not show its numbers cannot be argued with, and an unarguable hint is a
    verdict wearing a suggestion's clothes."""
    text = _plan(lines=900, tasks=40, workstreams=7)
    [message] = plan_scope_advisory(text)

    # Assert against what the predicate MEASURES, not against the fixture's inputs -- the total
    # includes the task and workstream lines, and a test that asserts its own arithmetic instead
    # of the code's is a test that will disagree with reality the moment the fixture changes.
    assert str(len(text.splitlines())) in message
    assert "40" in message, "the tagged-task count"
    assert "7" in message, "the workstream count"


def test_it_is_never_wired_to_an_exit_code(cli) -> None:
    """Permanently advisory. Pinned at the source so a later change has to argue with this test."""
    import inspect

    source = inspect.getsource(plan_scope_advisory)

    assert "raise SystemExit" not in source
    assert "return 1" not in source


def test_the_advisory_never_becomes_a_refusal_at_the_r1_seam(cli, tmp_path) -> None:
    """Wired warn-only at the seam, in EVERY mode and at every round count. A plan that is large
    but content-complete must launch its round, saying so on the way past."""
    big = tmp_path / "big.md"
    big.write_text(_plan(), encoding="utf-8")

    for enforcement in ("warn", "block"):
        data = {"planning": {"contentPregate": {"enforcement": enforcement}}}
        refusals, warnings = cli.plan_review_content_pregate(data, big, 0)

        assert any("ADVISORY ONLY" in w for w in warnings), enforcement
        assert not any("ADVISORY ONLY" in r for r in refusals), (
            f"sizing must never reach the refusal side, even under {enforcement}"
        )
