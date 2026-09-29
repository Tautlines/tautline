"""Every reader that asks about a round record is classified: TOPOLOGY or COST.

Two questions get asked of the same record and they have different answers:

  COST     -- did this spend budget?      charged only
  TOPOLOGY -- did this really review?     charged, PLUS wrapper-success format errors

Conflating them opened a cap bypass. Making an unclassifiable reviewer response `charged: false`
was right for cost, and it silently dropped that record from every TOPOLOGY reader too: the
documented format-error recovery (delete the run meta, re-run) could then lose the `--predecessor`
link, so a predecessor with four charged rounds fell out of the walk and the retry saw one
execution instead of an exhausted lineage.

Codex found that reader-by-reader across two rounds -- one in R1, three more in R2 -- which is the
signature of a rule applied per-site instead of enumerated. So this file enumerates. A new reader
that asks either question must join a list here, and an unclassified one fails the last test.
"""

import ast
from pathlib import Path


from tautline_methodology import cli

CLI_SOURCE = Path(cli.__file__).read_text(encoding="utf-8")

# Readers answering "did this really review?" -- must admit a wrapper-success format error.
TOPOLOGY_READERS = (
    "plan_review_predecessor_edges",
    "plan_review_recorded_predecessor",
    "plan_review_reference_has_review_evidence",
    "plan_review_work_items_for_rel",
)

# Readers answering "did this REVIEW but not SPEND?" -- the intersection, and what the absolute
# ceiling counts. A third category, added because the guard below refused to let
# `plan_review_member_uncharged_executions` sit in either of the other two: it legitimately uses
# BOTH predicates, and forcing it into one would have meant either counting transport failures
# against the cap or letting format errors escape it.
#
# That is not a bookkeeping detail. Counting every uncharged record here is precisely the
# regression Codex R3 caught: five transient outages exhausted the cap and produced no finalizable
# evidence, bricking a lane for a reason unrelated to review.
CEILING_READERS = (
    "plan_review_member_uncharged_executions",
)

# Readers answering "did this spend budget?" -- must NOT admit one.
COST_READERS = (
    "plan_review_member_round_proof",
    "plan_review_sha_stale_at_cap",
    "plan_review_recorded_member_spend",
)


def _record(**overrides):
    base = dict(
        plan_identity="admin",
        plan_path="backlog/plans/admin.md",
        plan_content_sha256="c" * 64,
        declared_round="R1",
        wrapper_exit_code=0,
        reviewer="codex",
        reviewer_model="codex-test",
        started_at="2026-08-27T00:00:00Z",
        finished_at="2026-08-27T00:01:00Z",
        nonce="n1",
        log_sha256="a" * 64,
        declared_predecessor="backlog/plans/parent.md",
        work_items=[],
        source="run",
    )
    base.update(overrides)
    return cli.plan_round_record_module().render_reviewer_invocation(**base)


def _function_node(name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(CLI_SOURCE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in cli.py -- update this enumeration")


def _calls(node: ast.AST) -> set[str]:
    """Names this function actually CALLS.

    Read from the AST, not the source text. A text scan cannot tell a call from a mention, and
    these functions carry comments naming the very predicates under test -- an early draft of this
    file failed on its own explanatory prose. Comments are absent from the AST entirely, so the
    question "does it call this" is answered exactly.
    """
    return {
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _inlines_charged_get(node: ast.AST) -> bool:
    """Whether it reaches for `.get("charged")` directly instead of a shared predicate."""
    for n in ast.walk(node):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "charged"
        ):
            return True
    return False


def test_every_reader_asking_either_question_is_classified():
    """The guard that makes this an enumeration rather than a list of four fixes.

    Any function touching a record's charged/lineage disposition must be in one of the two lists
    above. A new one fails here rather than silently picking a side -- which is exactly how the
    four found by review came to disagree.
    """
    classified = set(TOPOLOGY_READERS) | set(COST_READERS) | set(CEILING_READERS) | {
        # The predicates themselves, and the delegation between them.
        "plan_review_record_is_charged_invocation",
        "plan_review_record_declares_lineage",
    }
    tree = ast.parse(CLI_SOURCE)
    unclassified = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name in classified:
            continue
        calls = _calls(node)
        touches = (
            "plan_review_record_is_charged_invocation" in calls
            or "plan_review_record_declares_lineage" in calls
            or _inlines_charged_get(node)
        )
        if touches:
            unclassified.append(node.name)
    assert not unclassified, (
        "these functions decide charged-vs-lineage but are in neither list; classify each as "
        "TOPOLOGY (did it review?), COST (did it spend?) or CEILING (reviewed but did not "
        f"spend?): {sorted(unclassified)}"
    )
