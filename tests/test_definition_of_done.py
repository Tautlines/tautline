"""Batch 2026-08-11 item B7 -- the definition of done.

WS1 (registry + checkers), WS2 (the blocking arm at goal completion), WS3 (the warn arm
at the Stop boundary) and WS5 (canonical rule + manifest) are tested here. WS4's
goal-writing half lives in tests/test_goal_assignment_done_bar.py.

The load-bearing invariant these tests exist to hold: a checker that cannot read returns
`unknown`, never a pass and never `0`. The framework's dominant defect class is a control
that reads healthy because something upstream never let it run, and a done bar with that
defect has the highest possible blast radius.
"""

import ast
import io
import json
import subprocess
import textwrap
import time
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from tautline_methodology import done_definition as dod

REPO_ROOT = Path(__file__).resolve().parents[1]


BLOCK = {"enforcement": "block", "conditions": {}, "integrationBranch": "experimental"}


def _all_green_observations() -> dod.DoneObservations:
    """Facts under which every condition passes. Each test mutates one block off this."""
    return dod.DoneObservations(
        pr=dod.PrHandoffFacts(
            readable=True,
            found=True,
            merged=True,
            reference="PR #1",
            integration_branch="experimental",
        ),
        scope=dod.ScopeFacts(readable=True, total_units=3),
        diff=dod.DiffFacts(
            readable=True, changed_files=("src/pkg/thing.py", "tests/test_thing.py")
        ),
        tests=dod.TestGateFacts(condition="current", passed=5555, failed=0, collected=5557),
        review=dod.ReviewFacts(
            readable=True,
            finalized=True,
            verdict="clean",
            classification_status="clean",
            open_critical=0,
            open_p1=0,
            committed=True,
            ledger_path=".impl-reviews/branch.json",
            covers_current_diff=True,
        ),
        board=dod.BoardFacts(
            provider_enabled=True,
            readable=True,
            at_done_status=True,
            has_verification_evidence=True,
            reference="item 7",
        ),
    )


def _status_of(outcomes, condition_id: str) -> str:
    return next(o.status for o in outcomes if o.condition_id == condition_id)


def _reason_of(outcomes, condition_id: str) -> str:
    return next(o.reason for o in outcomes if o.condition_id == condition_id)


def _evaluate(observations, config=None, *, backlog_enabled=True):
    return dod.evaluate_done_conditions(
        config or BLOCK, observations, backlog_enabled=backlog_enabled
    )


# --- WS1: the registry -------------------------------------------------------------------


def test_every_condition_id_has_a_checker():
    assert dod.DONE_CONDITIONS, "the registry is empty; there is no definition of done"
    for condition_id, condition in dod.DONE_CONDITIONS.items():
        assert condition.condition_id == condition_id
        assert callable(condition.checker), f"{condition_id} has no checker"
        assert condition.passes_when.strip(), f"{condition_id} does not say when it passes"
        # A condition with no remedy is a refusal an agent routes around -- the same
        # defect shape as the round-cap dead end batch item B3 exists to fix.
        assert condition.remedy.strip(), f"{condition_id} names no remedy"
        outcome = condition.checker(dod.DoneObservations())
        assert outcome.condition_id == condition_id
        assert outcome.status in dod.CONDITION_STATUSES


def test_a_checker_that_cannot_read_returns_unknown_never_pass():
    """Every checker, given the all-unreadable observation set, must say `unknown`.

    The board block is given `provider_enabled=True` deliberately: with no provider at all the
    honest answer is `skipped`, and that is a different question. What this test pins is the
    CANNOT-READ path -- the provider exists and nothing about it could be established.
    """
    blind = dod.DoneObservations(board=dod.BoardFacts(provider_enabled=True, readable=False))
    for condition_id, condition in dod.DONE_CONDITIONS.items():
        outcome = condition.checker(blind)
        assert outcome.status == dod.UNKNOWN, (
            f"{condition_id} returned {outcome.status} from facts it could not read; "
            "a bar that passes when it cannot check is the defect this item exists to prevent"
        )
        assert outcome.reason.strip(), f"{condition_id} reported unknown with no reason"


def test_unknown_is_distinct_from_fail_at_every_surface():
    blind = _evaluate(dod.DoneObservations())
    assert dod.done_verdict(blind) == dod.UNKNOWN
    # Surface 1: nothing blocks.
    assert dod.done_check_blocking_failures(BLOCK, blind) == []
    # Surface 2: every unknown is named loudly.
    notices = dod.done_check_unknown_notices(blind)
    assert len(notices) == len([o for o in blind if o.status == dod.UNKNOWN])
    # Surface 3: the rendered lines say `unknown`, and never `0`, for an unread condition.
    lines = dod.render_done_check_lines(blind)
    assert any(" unknown - " in line for line in lines)
    assert not any(" fail - " in line for line in lines)
    # Surface 4: the JSON counts unknown separately from fail and from pass.
    payload = dod.done_check_payload(BLOCK, blind)
    assert payload["counts"]["unknown"] == len(notices)
    assert payload["counts"]["fail"] == 0
    assert payload["counts"]["pass"] == 0
    assert payload["verdict"] == dod.UNKNOWN


def test_an_all_unknown_run_is_not_reported_as_a_pass():
    """The plan's own validation bar: all-unknown means the checkers are wired to nothing."""
    payload = dod.done_check_payload(BLOCK, _evaluate(dod.DoneObservations()))
    assert payload["verdict"] != dod.PASS


# --- WS1: pr_handed_off, the central condition ------------------------------------------


def test_pr_handed_off_passes_for_a_merged_pr():
    obs = _all_green_observations()
    assert _status_of(_evaluate(obs), "pr_handed_off") == dod.PASS


def test_pr_handed_off_passes_for_an_open_pr_with_auto_merge_armed():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, is_open=True, auto_merge_armed=True, reference="PR #7"
        ),
    )
    outcomes = _evaluate(obs)
    assert _status_of(outcomes, "pr_handed_off") == dod.PASS
    assert "without this lane" in _reason_of(outcomes, "pr_handed_off")


def test_pr_handed_off_passes_for_a_pr_in_the_merge_queue():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, is_open=True, in_merge_queue=True, reference="PR #7"
        ),
    )
    assert _status_of(_evaluate(obs), "pr_handed_off") == dod.PASS


def test_pr_handed_off_fails_for_an_open_pr_with_no_merge_mechanism_armed():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    outcomes = _evaluate(obs)
    assert _status_of(outcomes, "pr_handed_off") == dod.FAIL
    reason = _reason_of(outcomes, "pr_handed_off")
    assert "no merge mechanism armed" in reason
    # The remedy must arm the merge, never watch it.
    assert "do not sit and watch it land" in reason


def test_pr_handed_off_is_unknown_when_pr_state_cannot_be_read():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=False, detail="gh is not installed"),
    )
    outcomes = _evaluate(obs)
    assert _status_of(outcomes, "pr_handed_off") == dod.UNKNOWN
    assert "gh is not installed" in _reason_of(outcomes, "pr_handed_off")


def test_pr_handed_off_fails_when_the_branch_has_no_pr_at_all():
    obs = replace(
        _all_green_observations(), pr=dod.PrHandoffFacts(readable=True, found=False)
    )
    assert _status_of(_evaluate(obs), "pr_handed_off") == dod.FAIL


def test_pr_handed_off_passes_on_the_integration_branch_itself():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True,
            found=False,
            on_integration_branch=True,
            integration_branch="experimental",
        ),
    )
    assert _status_of(_evaluate(obs), "pr_handed_off") == dod.PASS


def test_pr_handed_off_never_reads_estimated_time_to_merge():
    """Reading mergeQueueEntry.estimatedTimeToMerge trips the existing
    `stop.wrong_merge_queue_signal` guard. A done bar that tripped it would be
    self-defeating, so neither the registry nor its cli-side fact gatherer may name it."""
    forbidden = "estimatedTimeToMerge"
    module_source = (REPO_ROOT / "src" / "tautline_methodology" / "done_definition.py").read_text(
        encoding="utf-8"
    )
    # EXECUTABLE code only. Both this module and the plan name the field in prose precisely to
    # forbid it, and a raw substring search would make documenting the prohibition indistinguish-
    # able from committing the violation.
    assert forbidden not in _executable_text(module_source)

    cli_source = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")
    # The fact-gathering half, scoped to the collector rather than the whole monolith: the
    # anti-pattern guard's own regex legitimately names the field elsewhere in cli.py.
    start = cli_source.index("def done_definition_pr_facts(")
    end = cli_source.index("\ndef ", start + 1)
    assert forbidden not in _executable_text(cli_source[start:end])
    # And the GraphQL reader it delegates to asks only for presence/state.
    query_start = cli_source.index("def github_pr_queue_state(")
    query_end = cli_source.index("\ndef ", query_start + 1)
    assert forbidden not in cli_source[query_start:query_end]


def _executable_text(source: str) -> str:
    """The module's code with comments and docstrings removed.

    Comments never reach the AST; docstrings are the first statement of a module, class or
    function and are dropped explicitly. What remains is what actually runs.
    """
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def test_the_done_bar_never_requires_waiting_for_a_queued_pr_to_land():
    """A queued, auto-merging, not-yet-landed PR must produce a clean verdict with nothing
    blocking and no instruction to wait, poll, or watch."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True,
            found=True,
            is_open=True,
            merged=False,
            auto_merge_armed=True,
            in_merge_queue=True,
            reference="PR #7",
        ),
    )
    outcomes = _evaluate(obs)
    assert dod.done_verdict(outcomes) == dod.PASS
    assert dod.done_check_blocking_failures(BLOCK, outcomes) == []
    text = " ".join(dod.render_done_check_lines(outcomes)).lower()
    for waiting_word in ("wait for", "poll", "watch until", "until it merges", "until it lands"):
        assert waiting_word not in text, f"the done bar told the lane to {waiting_word!r}"
    # And the registry's own remedy text must not either.
    assert "watch" not in dod.DONE_CONDITIONS["pr_handed_off"].passes_when.lower()


# --- WS1: the other checkers -------------------------------------------------------------


def test_scope_complete_fails_on_an_open_unit_and_on_a_reasonless_deferral():
    obs = replace(
        _all_green_observations(),
        scope=dod.ScopeFacts(readable=True, total_units=2, open_units=("2: WS2 (in_progress)",)),
    )
    assert _status_of(_evaluate(obs), "scope_complete") == dod.FAIL
    obs = replace(
        _all_green_observations(),
        scope=dod.ScopeFacts(
            readable=True, total_units=2, deferred_without_reason=("2: WS2",)
        ),
    )
    assert _status_of(_evaluate(obs), "scope_complete") == dod.FAIL


def test_tests_written_fails_when_source_changed_and_no_test_did():
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(readable=True, changed_files=("src/pkg/thing.py",)),
    )
    assert _status_of(_evaluate(obs), "tests_written") == dod.FAIL


def test_tests_written_passes_for_a_docs_only_change():
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(readable=True, changed_files=("docs/a.md", "README.md")),
    )
    assert _status_of(_evaluate(obs), "tests_written") == dod.PASS


@pytest.mark.parametrize(
    "path,expected",
    [
        ("tests/test_thing.py", True),
        ("src/pkg/thing_test.py", True),
        ("web/src/a.test.tsx", True),
        ("features/login.feature", True),
        ("spec/models/a_spec.rb", True),
        ("src/pkg/thing.py", False),
        ("docs/plan.md", False),
    ],
)
def test_path_is_test_classifies_the_common_conventions(path, expected):
    assert dod.path_is_test(path) is expected


def test_tests_green_maps_the_classifier_states_without_re_deriving_them():
    green = _all_green_observations()
    assert _status_of(_evaluate(green), "tests_green") == dod.PASS
    assert "5555 passed" in _reason_of(_evaluate(green), "tests_green")
    for unreadable in dod.TEST_EVIDENCE_UNKNOWN_CONDITIONS:
        obs = replace(green, tests=dod.TestGateFacts(condition=unreadable))
        assert _status_of(_evaluate(obs), "tests_green") == dod.UNKNOWN, unreadable
    red = replace(green, tests=dod.TestGateFacts(condition="red", failed=3))
    assert _status_of(_evaluate(red), "tests_green") == dod.FAIL


def test_tests_green_fails_a_current_run_that_collected_nothing():
    obs = replace(
        _all_green_observations(),
        tests=dod.TestGateFacts(condition="current", passed=0, failed=0, collected=0),
    )
    outcomes = _evaluate(obs)
    assert _status_of(outcomes, "tests_green") == dod.FAIL
    assert "proves nothing" in _reason_of(outcomes, "tests_green")


def test_review_clean_and_evidence_bound_read_the_ledger():
    green = _all_green_observations()
    dirty = replace(green, review=replace(green.review, open_p1=2))
    assert _status_of(_evaluate(dirty), "review_clean") == dod.FAIL
    uncommitted = replace(green, review=replace(green.review, committed=False))
    assert _status_of(_evaluate(uncommitted), "evidence_bound") == dod.FAIL
    blocked = replace(green, review=replace(green.review, classification_status="blocked"))
    assert _status_of(_evaluate(blocked), "evidence_bound") == dod.FAIL
    unfinalized = replace(green, review=replace(green.review, finalized=False))
    assert _status_of(_evaluate(unfinalized), "review_clean") == dod.FAIL


def test_evidence_bound_is_unknown_when_commit_state_is_unestablished():
    green = _all_green_observations()
    obs = replace(green, review=replace(green.review, committed=None))
    assert _status_of(_evaluate(obs), "evidence_bound") == dod.UNKNOWN


# --- WS1: enablement and normalization ---------------------------------------------------


def test_disabled_condition_is_skipped_and_reported_as_skipped():
    config = {**BLOCK, "conditions": {"pr_handed_off": False}}
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True),
    )
    outcomes = dod.evaluate_done_conditions(config, obs, backlog_enabled=True)
    assert _status_of(outcomes, "pr_handed_off") == dod.SKIPPED
    # Visible, not vanished: an invisible skip is indistinguishable from a pass.
    assert any("pr_handed_off skipped" in line for line in dod.render_done_check_lines(outcomes))
    assert dod.done_check_blocking_failures(config, outcomes) == []
    payload = dod.done_check_payload(config, outcomes)
    assert payload["counts"]["skipped"] == 1


def test_board_updated_is_skipped_when_the_project_has_no_backlog_provider():
    outcomes = dod.evaluate_done_conditions(
        BLOCK, _all_green_observations(), backlog_enabled=False
    )
    assert _status_of(outcomes, "board_updated") == dod.SKIPPED


def test_integration_branch_defaults_to_the_repository_base_branch():
    config = dod.normalize_definition_of_done({}, default_integration_branch="experimental")
    assert config["integrationBranch"] == "experimental"
    # And the adapter may override it -- the bar is never hardcoded to `main`.
    override = dod.normalize_definition_of_done(
        {"definitionOfDone": {"integrationBranch": "trunk"}},
        default_integration_branch="experimental",
    )
    assert override["integrationBranch"] == "trunk"


def test_normalize_definition_of_done_never_writes_back():
    """The zero-rendered-adapter-bytes claim rests on this: an absent key stays absent."""
    data = {"name": "demo"}
    before = json.dumps(data, sort_keys=True)
    config = dod.normalize_definition_of_done(data)
    assert json.dumps(data, sort_keys=True) == before
    assert "definitionOfDone" not in data
    assert config["enforcement"] == dod.DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT


def test_normalize_definition_of_done_fails_loud_on_a_malformed_value():
    with pytest.raises(SystemExit):
        dod.normalize_definition_of_done({"definitionOfDone": []})
    with pytest.raises(SystemExit):
        dod.normalize_definition_of_done({"definitionOfDone": {"enforcement": "sometimes"}})
    with pytest.raises(SystemExit):
        dod.normalize_definition_of_done({"definitionOfDone": {"conditions": {"nope": True}}})
    with pytest.raises(SystemExit):
        dod.normalize_definition_of_done(
            {"definitionOfDone": {"conditions": {"tests_green": "yes"}}}
        )
    with pytest.raises(SystemExit):
        dod.normalize_definition_of_done({"definitionOfDone": {"unexpected": 1}})


def test_enforcement_off_and_warn_never_block():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True),
    )
    for mode in ("off", "warn"):
        config = {**BLOCK, "enforcement": mode}
        outcomes = dod.evaluate_done_conditions(config, obs, backlog_enabled=True)
        assert _status_of(outcomes, "pr_handed_off") == dod.FAIL
        assert dod.done_check_blocking_failures(config, outcomes) == []


# --- WS1: module hygiene ------------------------------------------------------------------


def test_done_definition_imports_no_cli():
    source = (REPO_ROOT / "src" / "tautline_methodology" / "done_definition.py").read_text(
        encoding="utf-8"
    )
    assert "import cli" not in source
    assert "from .cli" not in source
    assert "from tautline_methodology.cli" not in source
    assert "tautline_methodology" not in source.split('"""', 2)[-1], (
        "done_definition.py must be a leaf module: no intra-package imports at all"
    )


def test_done_conditions_constant_is_not_collected_into_the_policy_phrase_ssot(cli):
    """A UPPER_CASE list[str] constant is auto-collected into methodology/policy-phrases.json.
    DONE_CONDITIONS is a dict of records and every other UPPER_CASE constant in the module
    is a tuple, precisely so this registry never lands in the phrase vocabulary."""
    rendered = json.loads(cli.render_policy_phrases_json())
    assert "DONE_CONDITIONS" not in rendered
    for name in (
        "CONDITION_STATUSES",
        "DONE_CONDITION_IDS",
        "TEST_PATH_GLOBS",
        "TEST_DIR_SEGMENTS",
        "NON_BEHAVIOR_PATH_GLOBS",
        "HANDOFF_BAR_MARKERS",
        "LEDGER_CLEAN_STATUSES",
        "TEST_EVIDENCE_UNKNOWN_CONDITIONS",
        "DEFINITION_OF_DONE_ENFORCEMENT_MODES",
    ):
        assert name not in rendered, f"{name} leaked into the policy-phrase SSOT; make it a tuple"


def test_done_check_is_registered_in_the_public_contract_manifest():
    manifest = json.loads((REPO_ROOT / "methodology" / "public-contract-manifest.json").read_text())
    names = {entry["name"] for entry in manifest["commands"]}
    assert "done-check" in names


def test_definition_of_done_is_a_known_adapter_key():
    schema = json.loads((REPO_ROOT / "methodology" / "adapter-schema.json").read_text())
    assert "definitionOfDone" in schema["properties"]


def test_the_done_bar_adds_zero_rendered_adapter_bytes(run_cli, tmp_path):
    """Asserted as a DELTA against the merge base, never as a ceiling assertion.

    A ceiling assertion passes while silently spending a corridor another lane budgeted.
    Renders the example adapter from the merge base and from this tip, in two separate
    trees, and requires the byte counts to be identical."""
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/experimental"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if base.returncode != 0 or not base.stdout.strip():
        pytest.skip("no origin/experimental merge base available in this checkout")
    base_sha = base.stdout.strip()

    tip_out = tmp_path / "tip"
    tip_out.mkdir()
    result = run_cli(
        "render-adapters",
        "--project",
        str(REPO_ROOT / "adapters" / "projects" / "example-saas.json"),
        "--target",
        str(tip_out),
        "--write",
    )
    assert result.returncode == 0, result.stderr

    base_tree = tmp_path / "base-tree"
    worktree = subprocess.run(
        ["git", "worktree", "add", "--detach", str(base_tree), base_sha],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if worktree.returncode != 0:
        pytest.skip(f"could not create a merge-base worktree: {worktree.stderr}")
    try:
        base_out = tmp_path / "base"
        base_out.mkdir()
        rendered = subprocess.run(
            [
                "python3",
                str(base_tree / "bin" / "tautline"),
                "render-adapters",
                "--project",
                str(base_tree / "adapters" / "projects" / "example-saas.json"),
                "--target",
                str(base_out),
                "--write",
            ],
            cwd=base_tree,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered.returncode == 0, rendered.stderr
        for name in ("CLAUDE.md", "AGENTS.md"):
            tip_text = (tip_out / name).read_text(encoding="utf-8")

            # The invariant this test is NAMED for, asserted directly: definitionOfDone is
            # read-side only and must never be materialized into a rendered adapter. This is the
            # part that fails if B7's claim is ever broken.
            for marker in ("definitionOfDone", "definition-of-done", "done-check"):
                assert marker not in tip_text, (
                    f"{name} materialized {marker!r}; definitionOfDone is read-side only"
                )

            # NO delta-against-merge-base assertion lives here any more, and the reason is
            # worth keeping: it CANNOT survive its own merge. This test compares the tip against
            # `git merge-base HEAD origin/experimental`, so on the day a spending branch lands,
            # the merge base becomes that branch's own tip and the delta collapses to zero --
            # a "declared delta" constant would then be red on the integration branch for
            # everyone. Item 101 caught this in its Stage 1 sweep after first writing exactly
            # that constant; a version of it shipped would have broken CI on experimental.
            #
            # B7's underlying argument is right and is not lost: a ceiling assertion "passes
            # while silently spending a corridor another lane budgeted". The control for that is
            # the pair of corridor constants -- MAX_EXAMPLE_CLAUDE_BYTES and
            # MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES -- which a spending lane must raise by its
            # own MEASURED delta, in one commit, naming both. That discipline is branch-local
            # where it belongs, instead of encoded in an assertion that expires at merge.
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(base_tree)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )


# --- WS2: the blocking arm, at goal completion ---------------------------------------------
#
# Driven in-process against a REAL lane (adapter + goal run on disk) with only the fact
# GATHERERS stubbed. Stubbing the evaluation instead would test nothing: the wiring, the config
# resolution and the refusal ORDERING are the whole deliverable here.

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
CLI_PATH = REPO_ROOT / "bin" / "tautline"


def _lane(tmp_path, enforcement="block", conditions=None):
    """A lane with an adapter and a started single-milestone goal, built by the real CLI.

    `enforcement` defaults to `block` HERE, not because that is the shipped default -- it is
    not, see `test_the_shipped_default_enforcement_is_warn` -- but because these tests exist to
    prove the teeth work when a project turns them on. The shipped default is pinned separately
    so the two questions cannot be confused for each other.
    """
    target = tmp_path / "lane"
    target.mkdir()
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin",
         "git@github.com:example-org/example-saas.git"],
        check=True,
    )
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data.pop("goalTracker", None)
    data["uiEvidence"] = {**(data.get("uiEvidence") or {}), "enabled": False}
    # Not the surface under test, and each of these raises its own pre-flight refusal ahead of
    # the done bar. Leaving them on would make every assertion below about someone else's gate.
    data["iterationReview"] = {**(data.get("iterationReview") or {}), "enabled": False}
    if enforcement is not None:
        data["definitionOfDone"] = {"enforcement": enforcement}
    if conditions is not None:
        # Set BEFORE the render. The generated lane adapter carries a sourceAdapterSha256, so a
        # test that rewrites the adapter afterwards trips the integrity check instead of
        # exercising the override.
        data.setdefault("definitionOfDone", {})["conditions"] = dict(conditions)
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for the definition of done.",
        "repoEvidence": [
            {"path": ".ai-work/e1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/e2.txt", "fact": "evidence two exists"},
        ],
    }
    work = target / ".ai-work"
    work.mkdir()
    (work / "e1.txt").write_text("one\n", encoding="utf-8")
    (work / "e2.txt").write_text("two\n", encoding="utf-8")
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}

    def cli_run(*args, check=True):
        result = subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
        )
        if check and result.returncode != 0:
            raise AssertionError(f"{args}\n{result.stdout}\n{result.stderr}")
        return result

    cli_run("render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    goals = target / "docs" / "product" / "goals"
    goals.mkdir(parents=True)
    (goals / "dod.md").write_text(
        "# Definition-of-done fixture goal\n\n"
        "## Desired Outcome\nProve the done bar refuses and permits the right things.\n\n"
        "## Milestones\n- [ ] The only milestone\n\n"
        "## Completion Criteria\n- The bar behaves as specified.\n",
        encoding="utf-8",
    )
    # A real commit, so `rev-parse HEAD` resolves. A lane with no commit at all is not a lane,
    # and without one the PR-head comparison silently degrades to "unknown local tip".
    for arg in (["config", "user.email", "lane@example.invalid"], ["config", "user.name", "Lane"]):
        subprocess.run(["git", "-C", str(target), *arg], check=True)
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "commit", "-q", "--no-verify", "-m", "fixture lane"], check=True
    )
    cli_run("goal-start", "--target", str(target), "--goal", "docs/product/goals/dod.md")
    run_path = target / ".ai-work" / "GOAL_RUN.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    for milestone in run["milestones"]:
        milestone["status"] = "complete"
    run_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target, cli_run


def _stub_facts(cli, monkeypatch, observations):
    """Point every gatherer at a fixed observation set; the evaluation stays real."""
    monkeypatch.setattr(cli, "done_definition_pr_facts", lambda *a, **k: observations.pr)
    monkeypatch.setattr(cli, "done_definition_scope_facts", lambda *a, **k: observations.scope)
    monkeypatch.setattr(cli, "done_definition_diff_facts", lambda *a, **k: observations.diff)
    monkeypatch.setattr(cli, "done_definition_test_facts", lambda *a, **k: observations.tests)
    monkeypatch.setattr(cli, "done_definition_review_facts", lambda *a, **k: observations.review)
    monkeypatch.setattr(cli, "done_definition_board_facts", lambda *a, **k: observations.board)


def _advance(cli, target, detail="validated: the fixture proved the bar"):
    return cli.goal_advance(
        argparse.Namespace(
            project=None,
            target=target,
            event="goal-complete",
            milestone_index=None,
            milestone_plan=None,
            milestone_run=None,
            pr=None,
            reason=None,
            detail=detail,
            iteration_review_record=None,
            ui_evidence_manifest=None,
            verification_evidence=None,
            verification_evidence_file=None,
            verification_evidence_url=None,
            session_id="session-under-test",
        )
    )


def _no_mutation(cli, monkeypatch):
    """Trip a loud failure if anything publishes to a forge before the bar has spoken."""
    calls = []

    def forbidden(name):
        def _raise(*_a, **_k):
            calls.append(name)
            raise AssertionError(f"{name} ran before the done bar refused")
        return _raise

    monkeypatch.setattr(
        cli, "sync_goal_issue_ui_evidence", forbidden("sync_goal_issue_ui_evidence")
    )
    monkeypatch.setattr(
        cli, "goal_tracker_sync_transition", forbidden("goal_tracker_sync_transition")
    )
    monkeypatch.setattr(
        cli, "goal_advance_closure_preflight", forbidden("goal_advance_closure_preflight")
    )
    return calls


def test_goal_advance_to_done_refuses_with_an_unarmed_open_pr(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    _stub_facts(cli, monkeypatch, obs)
    with pytest.raises(SystemExit) as excinfo:
        _advance(cli, target)
    message = str(excinfo.value)
    assert "the definition of done is not met" in message
    assert "pr_handed_off" in message
    assert "blocker-declare" in message, (
        "a refusal with no named exit is one an agent routes around"
    )
    # And the ledger did NOT move to complete.
    run = json.loads((target / ".ai-work" / "GOAL_RUN.json").read_text(encoding="utf-8"))
    assert run["status"] != "complete"


def test_refusal_happens_before_any_github_mutation(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    _stub_facts(cli, monkeypatch, obs)
    calls = _no_mutation(cli, monkeypatch)
    with pytest.raises(SystemExit):
        _advance(cli, target)
    assert calls == [], f"a refused done move mutated first: {calls}"


def test_goal_advance_to_done_succeeds_with_a_queued_auto_merging_pr(cli, tmp_path, monkeypatch):
    """The central permission. A PR that has NOT landed but is armed must not block the lane."""
    target, _run = _lane(tmp_path)
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True,
            found=True,
            is_open=True,
            merged=False,
            auto_merge_armed=True,
            in_merge_queue=True,
            reference="PR #7",
        ),
    )
    _stub_facts(cli, monkeypatch, obs)
    assert _advance(cli, target) == 0
    run = json.loads((target / ".ai-work" / "GOAL_RUN.json").read_text(encoding="utf-8"))
    assert run["status"] == "complete"


def test_goal_advance_to_done_refuses_with_a_failing_test_gate(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    obs = replace(
        _all_green_observations(), tests=dod.TestGateFacts(condition="red", failed=3)
    )
    _stub_facts(cli, monkeypatch, obs)
    with pytest.raises(SystemExit) as excinfo:
        _advance(cli, target)
    assert "tests_green" in str(excinfo.value)


def test_goal_advance_to_done_succeeds_when_every_condition_passes(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, _all_green_observations())
    assert _advance(cli, target) == 0


def test_unknown_conditions_report_loudly_and_do_not_block(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, dod.DoneObservations())
    assert _advance(cli, target) == 0
    printed = capsys.readouterr().out
    assert "done_bar_unknown:" in printed
    assert "unknown" in printed
    # Loud, and never dressed up as a zero.
    assert "pass=0" in printed and "unknown=" in printed


def test_goal_advance_to_done_succeeds_with_a_board_item_not_yet_moved_to_done(
    cli, tmp_path, monkeypatch
):
    """R1 P1: the pre-flight is what runs BEFORE the transition that moves the board. Asking
    whether the item is already done would make the gate unsatisfiable by the command that
    satisfies it."""
    target, _run = _lane(tmp_path)
    real_board = cli.done_definition_board_facts
    seen = {}

    def spy(data, tgt, run, *, pending_close=False, done_evidence=""):
        seen["pending_close"] = pending_close
        return dod.BoardFacts(
            provider_enabled=True,
            readable=True,
            pending_close=pending_close,
            at_done_status=False,          # NOT yet done -- the transition has not run
            has_verification_evidence=bool(done_evidence),
            reference="board item 7",
        )

    green = _all_green_observations()
    monkeypatch.setattr(cli, "done_definition_pr_facts", lambda *a, **k: green.pr)
    monkeypatch.setattr(cli, "done_definition_scope_facts", lambda *a, **k: green.scope)
    monkeypatch.setattr(cli, "done_definition_diff_facts", lambda *a, **k: green.diff)
    monkeypatch.setattr(cli, "done_definition_test_facts", lambda *a, **k: green.tests)
    monkeypatch.setattr(cli, "done_definition_review_facts", lambda *a, **k: green.review)
    monkeypatch.setattr(cli, "done_definition_board_facts", spy)
    assert real_board is not spy
    assert _advance(cli, target) == 0
    assert seen["pending_close"] is True


def test_board_updated_at_the_preflight_asks_for_evidence_not_for_a_done_status():
    pending = dod.BoardFacts(
        provider_enabled=True, readable=True, pending_close=True,
        at_done_status=False, has_verification_evidence=True, reference="item 7",
    )
    obs = replace(_all_green_observations(), board=pending)
    assert _status_of(_evaluate(obs), "board_updated") == dod.PASS
    without = replace(pending, has_verification_evidence=False)
    assert _status_of(_evaluate(replace(obs, board=without)), "board_updated") == dod.FAIL


def test_board_updated_at_a_standalone_check_requires_the_item_to_be_done():
    after = dod.BoardFacts(
        provider_enabled=True, readable=True, pending_close=False,
        at_done_status=False, has_verification_evidence=True, reference="item 7",
    )
    obs = replace(_all_green_observations(), board=after)
    assert _status_of(_evaluate(obs), "board_updated") == dod.FAIL


def test_evidence_bound_accepts_clean_with_deferrals():
    """`finalize-implementation-review` and the canonical rules both permit it when
    Critical/P1 are zero; a bar rejecting it would refuse a sanctioned workflow."""
    green = _all_green_observations()
    for status in ("clean", "clean-with-deferrals"):
        obs = replace(green, review=replace(green.review, classification_status=status))
        assert _status_of(_evaluate(obs), "evidence_bound") == dod.PASS, status


def test_done_check_json_shape_is_stable(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, _all_green_observations())
    code = cli.done_check(argparse.Namespace(project=None, target=target, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == dod.DONE_CHECK_SCHEMA
    assert payload["verdict"] == dod.PASS
    assert set(payload["counts"]) == set(dod.CONDITION_STATUSES)
    assert [c["id"] for c in payload["conditions"]] == list(dod.DONE_CONDITION_IDS)
    for entry in payload["conditions"]:
        assert set(entry) == {"id", "status", "reason", "passesWhen", "remedy"}
    assert payload["blocking"] == []


def test_done_check_exits_one_only_on_a_fail(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, dod.DoneObservations())
    assert cli.done_check(argparse.Namespace(project=None, target=target, json=False)) == 0
    capsys.readouterr()
    _stub_facts(
        cli,
        monkeypatch,
        replace(
            _all_green_observations(),
            pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
        ),
    )
    assert cli.done_check(argparse.Namespace(project=None, target=target, json=False)) == 1


# --- WS3: the warn arm, at the Stop boundary ------------------------------------------------
#
# Driven through the REAL `response-guard-hook` with a real Stop payload on stdin, not by
# calling the inner function. That is the whole point: `response_guard_hook` has its OWN
# `if not response_guard_has_active_goal(...): return 0` prefilter, so an arm tested only at
# the inner function could ship completely unreachable in the exact scenario it is built for.


def _complete_the_goal(target, *, session_id="session-under-test", completed_at=None):
    run_path = target / ".ai-work" / "GOAL_RUN.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["status"] = "complete"
    for milestone in run["milestones"]:
        milestone["status"] = "complete"
    if session_id is not None:
        run["completedBySession"] = session_id
    run["completedAt"] = completed_at or datetime.now(timezone.utc).isoformat()
    run_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return run


def _stop_payload(target, session_id="session-under-test", assistant="Done. The PR is open."):
    return {
        "hook_event_name": "Stop",
        "cwd": str(target),
        "session_id": session_id,
        "last_assistant_message": assistant,
    }


def _run_stop_hook(cli, target, payload, monkeypatch, capsys, observations):
    _stub_facts(cli, monkeypatch, observations)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = cli.response_guard_hook(argparse.Namespace())
    return code, capsys.readouterr().out


UNARMED = None  # set below, once _all_green_observations exists at call time


def _unarmed_observations():
    return replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )


def test_stop_after_self_declared_done_with_an_open_pr_warns(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    assert code == 0
    assert out.strip(), "the arm produced no output at all in the scenario it exists for"
    emitted = json.loads(out)
    context = emitted["hookSpecificOutput"]["additionalContext"]
    assert "done_bar_stop" in context
    assert "pr_handed_off" in context
    assert "advisory: nothing is blocked" in context


def test_stop_arm_never_emits_a_block_decision(cli, tmp_path, monkeypatch, capsys):
    """R1 P1. `hook_decision` prints {"decision": "block"} and the hook STILL returns exit code
    0, so an exit-code assertion would pass while this violated RCA DECISION 4. Assert on the
    emitted JSON."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    emitted = json.loads(out)
    assert "decision" not in emitted
    assert emitted["hookSpecificOutput"]["hookEventName"] == "Stop"


def test_stop_arm_never_changes_an_exit_code(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    for observations in (
        _unarmed_observations(),
        _all_green_observations(),
        dod.DoneObservations(),
    ):
        code, _out = _run_stop_hook(
            cli, target, _stop_payload(target), monkeypatch, capsys, observations
        )
        assert code == 0


def test_stop_warning_does_not_instruct_consulting_a_human(cli, tmp_path, monkeypatch, capsys):
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"].lower()
    for phrase in (
        "ask the operator", "ask the human", "consult the", "check with",
        "wait for the operator",
    ):
        assert phrase not in context, f"the warning tells the agent to {phrase!r}"


def test_stop_after_a_goal_completed_by_a_different_session_does_not_warn(
    cli, tmp_path, monkeypatch, capsys
):
    """Without session correlation this arm would warn every later unrelated session."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target, session_id="some-earlier-session")
    _code, out = _run_stop_hook(
        cli,
        target,
        _stop_payload(target, session_id="session-under-test"),
        monkeypatch,
        capsys,
        _unarmed_observations(),
    )
    assert out.strip() == ""


def test_stop_after_a_goal_with_no_session_stamp_reports_unknown_and_does_not_warn(
    cli, tmp_path, monkeypatch, capsys
):
    """Reported, not guessed. An un-correlatable completion gets one honest `unknown` line --
    silence would be a control that reads healthy while doing nothing."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target, session_id=None)
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "done_bar_stop: unknown" in context
    assert "pr_handed_off" not in context, "an un-correlated run must assert no verdict"


def test_the_unknown_line_is_bounded_to_recent_completions(cli, tmp_path, monkeypatch, capsys):
    """Otherwise a long-finished goal run prints it at every Stop, forever."""
    target, _run = _lane(tmp_path)
    stale = datetime.now(timezone.utc) - timedelta(days=9)
    _complete_the_goal(target, session_id=None, completed_at=stale.isoformat())
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    assert out.strip() == ""


def test_stop_warning_is_released_by_a_fresh_blocker_record(cli, tmp_path, monkeypatch, capsys):
    target, cli_run = _lane(tmp_path)
    _complete_the_goal(target)
    cli_run(
        "blocker-declare", "--target", str(target),
        "--kind", "approval-needed", "--reason", "the merge needs an operator lock this lane lacks",
    )
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    assert out.strip() == "", "a fresh declared blocker is the sanctioned exit and must release it"


def test_stop_warning_is_not_released_by_a_stale_blocker_record(cli, tmp_path, monkeypatch, capsys):
    target, cli_run = _lane(tmp_path)
    _complete_the_goal(target)
    cli_run(
        "blocker-declare", "--target", str(target),
        "--kind", "approval-needed", "--reason", "the merge needs an operator lock this lane lacks",
    )
    blocker = target / ".ai-work" / "BLOCKER.json"
    assert blocker.is_file()
    stale = time.time() - (60 * 60 * 6)
    os.utime(blocker, (stale, stale))
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    assert "done_bar_stop" in out, "a stale blocker must not release the warning"


def test_stop_with_no_completed_goal_this_session_is_unchanged(cli, tmp_path, monkeypatch, capsys):
    """An ACTIVE goal is the existing blocking path's business; this arm must stay out of it."""
    target, _run = _lane(tmp_path)  # goal is started, not completed
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _unarmed_observations()
    )
    assert "done_bar_stop" not in out


def test_the_active_goal_stop_path_is_unchanged_by_this_arm(cli, tmp_path, monkeypatch, capsys):
    """The existing hard-blocking active-goal check must still block, and must still be the
    thing that speaks -- the two branches are mutually exclusive by construction."""
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, _unarmed_observations())
    payload = _stop_payload(target, assistant="I'll pause here and wait for your review.")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.response_guard_hook(argparse.Namespace())
    out = capsys.readouterr().out
    if out.strip():
        emitted = json.loads(out)
        # Whatever it says, it is NOT this arm: the done-bar branch returns before this one.
        assert "done_bar_stop" not in json.dumps(emitted)


def test_a_crashing_done_bar_cannot_break_the_stop_hook(cli, tmp_path, monkeypatch, capsys):
    """Containment is the contract. An advisory that can take down the Stop hook is worse than
    no advisory -- the 2026-07-22 startup-gate lesson, applied here."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)

    def explode(*_a, **_k):
        raise RuntimeError("the forge fell over")

    monkeypatch.setattr(cli, "done_bar_stop_advisory", explode)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_stop_payload(target))))
    assert cli.response_guard_hook(argparse.Namespace()) == 0


# --- wiring: the checkers must be attached to real sources ----------------------------------


def test_every_checker_is_wired_to_a_real_fact_source(cli):
    """R1 P2. `unknown` never blocks, so a placeholder checker that always returned `unknown`
    would satisfy the registry test AND let every goal completion through -- this item's own
    headline defect, reproduced inside the item. Assert each condition can reach BOTH a pass
    and a fail from real fact shapes, and that a gatherer exists for every observation block."""
    green = _all_green_observations()
    for condition_id, condition in dod.DONE_CONDITIONS.items():
        assert condition.checker(green).status == dod.PASS, f"{condition_id} cannot pass"
    reachable_fail = {
        "scope_complete": replace(
            green, scope=dod.ScopeFacts(readable=True, total_units=1, open_units=("1: x",))
        ),
        "tests_written": replace(
            green, diff=dod.DiffFacts(readable=True, changed_files=("src/a.py",))
        ),
        "tests_green": replace(green, tests=dod.TestGateFacts(condition="red", failed=1)),
        "review_clean": replace(green, review=replace(green.review, open_critical=1)),
        "evidence_bound": replace(green, review=replace(green.review, committed=False)),
        "pr_handed_off": replace(
            green, pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True)
        ),
        "board_updated": replace(green, board=replace(green.board, at_done_status=False)),
    }
    assert set(reachable_fail) == set(dod.DONE_CONDITIONS)
    for condition_id, observations in reachable_fail.items():
        outcome = dod.DONE_CONDITIONS[condition_id].checker(observations)
        assert outcome.status == dod.FAIL, f"{condition_id} cannot fail: {outcome.reason}"
    # And every observation block has a cli-side gatherer, so none is left permanently unread.
    for gatherer in (
        "done_definition_pr_facts",
        "done_definition_scope_facts",
        "done_definition_diff_facts",
        "done_definition_test_facts",
        "done_definition_review_facts",
        "done_definition_board_facts",
    ):
        assert callable(getattr(cli, gatherer)), gatherer


def test_pr_facts_read_merge_queue_state_through_the_graphql_helper(cli, tmp_path, monkeypatch):
    """R1 P1: `mergeQueueEntry` is not a `gh pr list --json` field -- the CLI rejects it. Asking
    for it there would make every read fail, and a failed read is `unknown`, which does not
    block, so an unarmed open PR would sail through the bar built to catch it."""
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/x"], check=True)
    requested_fields = {}
    monkeypatch.setattr(cli, "github_remote_present", lambda *_a, **_k: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(cli, "github_repo_identity", lambda *_a, **_k: ("org", "repo", None))

    def fake_command_json(cmd, *_a, **_k):
        requested_fields["fields"] = cmd[cmd.index("--json") + 1]
        return 0, [{"number": 7, "state": "OPEN", "baseRefName": "experimental",
                    "autoMergeRequest": None, "mergeStateStatus": "BLOCKED"}], ""

    monkeypatch.setattr(cli, "command_json", fake_command_json)
    monkeypatch.setattr(
        cli, "github_pr_queue_state", lambda *_a, **_k: (True, "QUEUED", None)
    )
    facts = cli.done_definition_pr_facts({}, target, "experimental")
    assert "mergeQueueEntry" not in requested_fields["fields"]
    assert facts.in_merge_queue is True
    assert facts.readable is True


def test_pr_facts_fail_the_bar_when_the_pr_targets_the_wrong_branch(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/x"], check=True)
    monkeypatch.setattr(cli, "github_remote_present", lambda *_a, **_k: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(cli, "github_repo_identity", lambda *_a, **_k: ("org", "repo", None))
    monkeypatch.setattr(
        cli,
        "command_json",
        lambda *_a, **_k: (
            0,
            [{"number": 7, "state": "MERGED", "mergedAt": "2026-08-11T00:00:00Z",
              "baseRefName": "main", "autoMergeRequest": None}],
            "",
        ),
    )
    facts = replace(cli.done_definition_pr_facts({}, target, "experimental"), worktree_dirty=False)
    assert facts.base_ref == "main"
    outcome = dod.check_pr_handed_off(replace(_all_green_observations(), pr=facts))
    assert outcome.status == dod.FAIL
    assert "main" in outcome.reason and "experimental" in outcome.reason


def test_pr_handed_off_fails_when_the_pr_targets_a_branch_other_than_the_integration_branch():
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, merged=True, reference="PR #7",
            base_ref="someone-elses-feature", integration_branch="experimental",
        ),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "does not reach integration" in outcome.reason


def test_an_unresolvable_integration_branch_skips_the_base_check_rather_than_failing():
    """An expectation nobody can resolve is not evidence of a wrong base."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, merged=True, base_ref="whatever", integration_branch=""
        ),
    )
    assert dod.check_pr_handed_off(obs).status == dod.PASS


def test_a_skip_names_its_actual_cause(cli):
    """A condition skipped because the project has no board, and one skipped because someone
    wrote `false` in the adapter, are different facts. The skip line is the only thing a reader
    gets, so reporting the second when the first is true sends them to edit a key that does not
    exist."""
    green = _all_green_observations()
    no_board = dod.evaluate_done_conditions(BLOCK, green, backlog_enabled=False)
    assert "no enabled backlog provider" in _reason_of(no_board, "board_updated")

    overridden = {**BLOCK, "conditions": {"board_updated": False}}
    explicit = dod.evaluate_done_conditions(overridden, green, backlog_enabled=True)
    assert "definitionOfDone.conditions" in _reason_of(explicit, "board_updated")


def test_done_check_runs_in_a_lane_with_no_goal_run(cli, tmp_path, monkeypatch, capsys):
    """`load_goal_run` RAISES SystemExit for the ordinary missing-ledger case, and SystemExit
    derives from BaseException -- so a bare `except Exception` killed `done-check` in the
    commonest lane state there is. A reporting verb nobody can reach is not a control."""
    target, _run = _lane(tmp_path)
    (target / ".ai-work" / "GOAL_RUN.json").unlink()
    _stub_facts(cli, monkeypatch, _all_green_observations())
    code = cli.done_check(argparse.Namespace(project=None, target=target, json=False))
    out = capsys.readouterr().out
    assert code == 0
    assert "done_check_summary:" in out


def test_the_stop_arm_survives_a_lane_with_no_goal_run(cli, tmp_path):
    """Same SystemExit trap, on the hook side, where escaping it would break every Stop."""
    target, _run = _lane(tmp_path)
    (target / ".ai-work" / "GOAL_RUN.json").unlink()
    assert cli.done_bar_stop_advisory(target, "session-under-test") == ""


def test_an_untracked_ledger_is_not_reported_as_committed(cli, tmp_path):
    """`git status --porcelain` prints nothing for a clean tracked file AND nothing for a path
    git is not tracking, so status alone would read an ignored `.impl-reviews/` as committed --
    a ledger that will never reach the remote, reported as bound evidence."""
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/ledger"], check=True)
    data = cli.load_project(cli.adapter_marker_path(target))
    ledger_dir = cli.implementation_review_ledger_dir(data, target)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / f"{cli.slugify('feat/ledger', 'branch')}.json"
    ledger.write_text(
        json.dumps(
            {
                "verdict": "clean",
                "classification_status": "clean",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
            }
        ),
        encoding="utf-8",
    )
    facts = cli.done_definition_review_facts(data, target)
    assert facts.readable is True
    assert facts.committed is False
    outcome = dod.check_evidence_bound(replace(_all_green_observations(), review=facts))
    assert outcome.status == dod.FAIL
    assert "not committed" in outcome.reason


# --- R2 findings: the ones that were real code defects ---------------------------------------


def test_pr_handed_off_fails_when_the_pr_does_not_contain_the_current_work():
    """R2 P1. A PR can be merged or armed while its head PREDATES the work being completed --
    unpushed local commits, or a branch name reused after an earlier merge. "A PR exists and is
    armed" is not "this work is handed off"."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True,
            found=True,
            merged=True,
            reference="PR #7",
            base_ref="experimental",
            integration_branch="experimental",
            head_oid="a" * 40,
            local_head="b" * 40,
        ),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "does not contain the current work" in outcome.reason
    assert "Push the branch" in outcome.reason


def test_pr_handed_off_passes_when_the_pr_head_matches_the_lane_tip():
    sha = "c" * 40
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, merged=True, reference="PR #7",
            base_ref="experimental", integration_branch="experimental",
            head_oid=sha, local_head=sha,
        ),
    )
    assert dod.check_pr_handed_off(obs).status == dod.PASS


def test_an_unknown_pr_head_does_not_manufacture_a_failure():
    """Compared only when BOTH are known: an unresolvable local tip is not evidence of a
    stale PR."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, merged=True, head_oid="d" * 40, local_head=""
        ),
    )
    assert dod.check_pr_handed_off(obs).status == dod.PASS


def test_pr_facts_gather_the_head_oid_and_the_local_tip(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/x"], check=True)
    requested = {}
    monkeypatch.setattr(cli, "github_remote_present", lambda *_a, **_k: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(cli, "github_repo_identity", lambda *_a, **_k: ("org", "repo", None))

    def fake_command_json(cmd, *_a, **_k):
        requested["fields"] = cmd[cmd.index("--json") + 1]
        return 0, [{"number": 7, "state": "MERGED", "mergedAt": "2026-08-11T00:00:00Z",
                    "baseRefName": "experimental", "headRefOid": "e" * 40,
                    "autoMergeRequest": None}], ""

    monkeypatch.setattr(cli, "command_json", fake_command_json)
    facts = cli.done_definition_pr_facts({}, target, "experimental")
    assert "headRefOid" in requested["fields"]
    assert facts.head_oid == "e" * 40
    assert len(facts.local_head) == 40, "the lane's own tip was not resolved"
    assert facts.head_oid != facts.local_head
    assert dod.check_pr_handed_off(replace(_all_green_observations(), pr=facts)).status == dod.FAIL


def test_tests_green_is_unknown_when_a_green_run_records_no_numeric_pass_count():
    """R2 P2. The condition's bar is 'passes on the branch tip WITH THE PASS COUNT RECORDED AS A
    NUMBER'. Exit-code-only evidence does not meet it -- a suite that collected nothing exits 0
    too -- and it is not a `fail` either: the run is real, the evidence to judge it is missing."""
    obs = replace(
        _all_green_observations(),
        tests=dod.TestGateFacts(condition="current", passed=None, collected=10),
    )
    outcome = dod.check_tests_green(obs)
    assert outcome.status == dod.UNKNOWN
    assert "no numeric pass count" in outcome.reason
    assert " 0 " not in f" {outcome.reason} "


def test_board_updated_never_derives_its_evidence_from_the_done_status():
    """R2 P1. A human or another tool can move an item straight to Done with no verification
    comment. Deriving evidence from the status makes the condition unfalsifiable exactly there."""
    obs = replace(
        _all_green_observations(),
        board=dod.BoardFacts(
            provider_enabled=True, readable=True, at_done_status=True,
            has_verification_evidence=False, evidence_readable=False, reference="item 7",
        ),
    )
    outcome = dod.check_board_updated(obs)
    assert outcome.status == dod.UNKNOWN
    assert "could not be read" in outcome.reason

    unverified = replace(obs.board, evidence_readable=True)
    assert dod.check_board_updated(replace(obs, board=unverified)).status == dod.FAIL


def test_board_facts_do_not_report_evidence_it_never_read(cli, tmp_path, monkeypatch):
    """The gatherer's half of the same finding, asserted against the shipped function rather
    than a hand-built fact: an earlier version returned `has_verification_evidence=at_done`."""
    target, _run = _lane(tmp_path)
    data = cli.load_project(cli.adapter_marker_path(target))
    data["backlogProvider"] = {"enabled": True}
    monkeypatch.setattr(
        cli, "goal_tracker_config",
        lambda _d: {"statusField": "Status", "doneStatuses": ["Done"]},
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda *_a, **_k: "7")
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *_a, **_k: {"Status": "Done"})
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda *_a, **_k: "Done")
    monkeypatch.setattr(cli, "goal_tracker_status_matches", lambda *_a, **_k: True)
    facts = cli.done_definition_board_facts(data, target, {})
    assert facts.at_done_status is True
    assert facts.has_verification_evidence is False
    assert facts.evidence_readable is False


def test_stop_reports_when_the_done_bar_could_establish_nothing(cli, tmp_path, monkeypatch, capsys):
    """R2 P1, and the sharpest one. A session can complete its goal and reach Stop with the PR,
    test and review facts ALL unreadable. No condition fails, so the arm used to return "" --
    silence indistinguishable from a clean bar, at the one boundary built to catch that."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, dod.DoneObservations()
    )
    assert out.strip(), "the arm went silent on a run that established nothing"
    emitted = json.loads(out)
    assert "decision" not in emitted
    context = emitted["hookSpecificOutput"]["additionalContext"]
    assert "could not establish a single condition" in context
    assert "Nothing is blocked and nothing was proven" in context


def test_stop_stays_quiet_when_the_bar_was_evaluated_and_found_no_fault(
    cli, tmp_path, monkeypatch, capsys
):
    """The other side of the same line: silence is honest when something actually passed."""
    target, _run = _lane(tmp_path)
    _complete_the_goal(target)
    _code, out = _run_stop_hook(
        cli, target, _stop_payload(target), monkeypatch, capsys, _all_green_observations()
    )
    assert out.strip() == ""


# --- Implementation review R1 findings ------------------------------------------------------


def test_review_evidence_for_a_superseded_diff_does_not_pass(cli):
    """Impl-review R1 P1, and the most dangerous finding in either review. A ledger finalized
    on commit A stays tracked and clean after commit B is added, so a `clean` verdict for a
    SUPERSEDED diff admitted unreviewed code straight through the blocking bar -- evidence that
    reads as proof of something it never saw."""
    green = _all_green_observations()
    stale = replace(
        green.review,
        covers_current_diff=False,
        stale_reason="ledger was finalized against diff aaaa but the outgoing diff is bbbb",
    )
    obs = replace(green, review=stale)
    for condition_id in ("review_clean", "evidence_bound"):
        outcome = dod.DONE_CONDITIONS[condition_id].checker(obs)
        assert outcome.status == dod.FAIL, condition_id
        assert "aaaa" in outcome.reason or "different diff" in outcome.reason


def test_an_unestablished_diff_binding_is_unknown_not_a_pass(cli):
    green = _all_green_observations()
    obs = replace(green, review=replace(green.review, covers_current_diff=None))
    assert dod.check_review_clean(obs).status == dod.UNKNOWN


def test_review_facts_compare_the_ledger_against_the_current_diff(cli, tmp_path):
    """The gatherer's half: a hand-written ledger claiming a fabricated diff must not pass."""
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/stale"], check=True)
    data = cli.load_project(cli.adapter_marker_path(target))
    ledger_dir = cli.implementation_review_ledger_dir(data, target)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / f"{cli.slugify('feat/stale', 'branch')}.json"
    ledger.write_text(
        json.dumps(
            {
                "verdict": "clean",
                "classification_status": "clean",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "diff_sha256": "f" * 64,
            }
        ),
        encoding="utf-8",
    )
    facts = cli.done_definition_review_facts(data, target)
    # Either the comparison ran and refused the fabricated hash, or it could not be made --
    # both are honest. What it must never be is a pass.
    assert facts.covers_current_diff in (False, None)
    if facts.covers_current_diff is False:
        stale_obs = replace(_all_green_observations(), review=facts)
        assert dod.check_review_clean(stale_obs).status == dod.FAIL


def test_the_pr_that_contains_the_tip_wins_over_a_historical_merged_one(cli, tmp_path, monkeypatch):
    """Impl-review R1 P2. When a branch NAME is reused after an earlier merge, preferring
    merged outright picked the historical PR, whose frozen head never matches the tip -- so the
    lane failed permanently even though its current PR was armed and contained the work."""
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "-b", "feat/reused"], check=True)
    tip = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    monkeypatch.setattr(cli, "github_remote_present", lambda *_a, **_k: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(cli, "github_repo_identity", lambda *_a, **_k: ("org", "repo", None))
    monkeypatch.setattr(
        cli,
        "command_json",
        lambda *_a, **_k: (
            0,
            [
                # The historical one: merged, but its head is ancient.
                {"number": 1, "state": "MERGED", "mergedAt": "2026-01-01T00:00:00Z",
                 "baseRefName": "experimental", "headRefOid": "0" * 40, "autoMergeRequest": None},
                # The current one: open, armed, and it IS the tip.
                {"number": 2, "state": "OPEN", "baseRefName": "experimental",
                 "headRefOid": tip, "autoMergeRequest": {"enabledAt": "now"}},
            ],
            "",
        ),
    )
    # Cleanliness is a different condition with its own test; neutralize it so this one is
    # about ranking and nothing else.
    facts = replace(cli.done_definition_pr_facts({}, target, "experimental"), worktree_dirty=False)
    assert facts.reference == "PR #2", "the historical merged PR was selected over the live one"
    assert dod.check_pr_handed_off(replace(_all_green_observations(), pr=facts)).status == dod.PASS


def test_the_handoff_check_rejects_a_negated_marker():
    """Impl-review R1 P2. `Do not enable auto-merge. Done when: a PR is open` contains a marker
    and stops short of handoff; so does `the PR is not merged`."""
    from tautline_methodology import goal_assignment as ga

    for body in (
        "/goal Do not enable auto-merge. Done when: a PR is open." + "." * 60,
        "/goal Complete it. Done when: the PR is not merged yet." + "." * 60,
    ):
        assert not dod.completion_clause_names_handoff_bar(body), body
        assert ga.goal_assignment_shape_issues(body, None) != [], body
    affirmative = "/goal Complete it. Done when: auto-merge is armed on the PR." + "." * 60
    assert dod.completion_clause_names_handoff_bar(affirmative)
    assert ga.goal_assignment_shape_issues(affirmative, None) == []


def test_the_handoff_check_reads_the_clause_not_the_whole_body():
    """A handoff word anywhere else -- a prohibition, the scope, a milestone title -- must not
    satisfy a completion clause that itself says `a PR is open`."""
    body = (
        "/goal Land the merge-queue refactor. Done when: a PR is open for review." + "." * 60
    )
    assert not dod.completion_clause_names_handoff_bar(body)


def test_unknown_done_condition_keys_are_refused_by_the_schema():
    """Impl-review R1 P2: `additionalProperties: true` accepted `tests_grean` at validation
    time, deferring the typo to whenever a done command next ran."""
    schema = json.loads((REPO_ROOT / "methodology" / "adapter-schema.json").read_text())
    conditions = schema["properties"]["definitionOfDone"]["properties"]["conditions"]
    assert conditions["additionalProperties"] is False
    assert set(conditions["properties"]) == set(dod.DONE_CONDITION_IDS)


# --- Implementation review, round 2 -----------------------------------------------------------


def test_tests_green_fails_a_zero_exit_whose_report_records_failures():
    """R2 P1. `pytest ... || true` exits 0 with failures in the report, and the classifier still
    says `current` -- it partitions trustworthiness, not redness. A gate reading only the exit
    code passes a red suite that swallowed its own status."""
    obs = replace(
        _all_green_observations(),
        tests=dod.TestGateFacts(condition="current", passed=100, failed=3, errors=0, collected=103),
    )
    outcome = dod.check_tests_green(obs)
    assert outcome.status == dod.FAIL
    assert "does not match the report" in outcome.reason

    errored = replace(
        _all_green_observations(),
        tests=dod.TestGateFacts(condition="current", passed=100, failed=0, errors=2, collected=102),
    )
    assert dod.check_tests_green(errored).status == dod.FAIL


def test_a_doc_under_a_test_directory_is_not_a_written_test():
    """R2 P2. `tests/README.md` sits under a test directory and is not a test; counted as one it
    satisfies the condition while no executable test changed."""
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(readable=True, changed_files=("src/pkg/thing.py", "tests/README.md")),
    )
    outcome = dod.check_tests_written(obs)
    assert outcome.status == dod.FAIL


def test_an_unestablished_diff_binding_makes_evidence_bound_unknown_not_pass():
    """R2 P2, and an outright bypass when `review_clean` is disabled for the project."""
    green = _all_green_observations()
    obs = replace(green, review=replace(green.review, covers_current_diff=None))
    assert dod.check_evidence_bound(obs).status == dod.UNKNOWN


def test_an_established_failure_outranks_an_unestablished_question():
    """A ledger demonstrably not committed is a FAIL even when the diff binding is unknown --
    reporting `unknown` there hides a fact the checker actually has."""
    green = _all_green_observations()
    obs = replace(
        green, review=replace(green.review, committed=False, covers_current_diff=None)
    )
    outcome = dod.check_evidence_bound(obs)
    assert outcome.status == dod.FAIL
    assert "not committed" in outcome.reason


def test_the_completion_clause_stops_at_the_sentence_but_not_at_a_semicolon():
    """R2 P2. Later prose must not supply a marker the clause never states -- but the COMPOSED
    clause separates its own conditions with `; ` inside one sentence, so cutting at a semicolon
    would hide the handoff condition from the check that requires it."""
    later_prose = (
        "/goal Complete it. Done when: tests pass and a PR is open. Auto-merge support is "
        "documented later." + "." * 40
    )
    assert not dod.completion_clause_names_handoff_bar(later_prose)

    from tautline_methodology import goal_assignment as ga

    composed, _meta = ga.compose_goal_assignment(
        command="/goal", title="T", plan_ref="docs/plans/widget.md", milestones=()
    )
    assert dod.completion_clause_names_handoff_bar(composed), (
        "the composed clause uses semicolons between conditions; the scan must not stop there"
    )


def test_the_review_base_comes_from_the_ledger_not_from_origin_main(cli):
    """R2 P1, and the finding that would have blocked this repository. `implementation_review_state`
    defaults to `origin/main`; this repo finalizes against `origin/experimental`, so recomputing
    with the default marks every valid ledger stale and the BLOCKING bar then refuses every goal
    completion -- a gate with a 100% false-positive rate on its own project."""
    import inspect

    source = inspect.getsource(cli.done_definition_review_facts)
    assert "ledger.get(\"base_ref\")" in source
    assert "implementation_review_state(target, ledger_base)" in source


def test_a_deleted_test_file_does_not_count_as_a_written_test(cli):
    """R2 P1. `git diff --name-only` lists deletions, so removing tests satisfied the condition
    that exists to require them."""
    import inspect

    source = inspect.getsource(cli.done_definition_diff_facts)
    assert "--diff-filter=d" in source, "deletions are not excluded from the outgoing diff"


def test_unpushed_commits_on_the_integration_branch_are_not_handed_off(cli, tmp_path, monkeypatch):
    """R2 P1. Standing ON the integration branch returned a pass before any remote comparison, so
    a goal could complete on commits only this lane can see."""
    target, _run = _lane(tmp_path)
    subprocess.run(["git", "-C", str(target), "branch", "-M", "experimental"], check=True)
    # No `origin/experimental` ref exists in the fixture, so the count is unreadable -> unknown,
    # never a pass. That is the honest verdict and it is the one the bar must give.
    facts = cli.done_definition_pr_facts({}, target, "experimental")
    assert facts.readable is False or facts.detail
    outcome = dod.check_pr_handed_off(replace(_all_green_observations(), pr=facts))
    assert outcome.status != dod.PASS


def test_a_sanctioned_repo_only_goal_skips_the_board_condition(cli, tmp_path, monkeypatch):
    """R2 P2, composing item 71 PR3. With `allowRepoOnlyGoals` set and no board ref, the sync
    that follows performs no board update -- so claiming the transition closes a board item
    describes something that will not happen."""
    target, _run = _lane(tmp_path)
    data = cli.load_project(cli.adapter_marker_path(target))
    data["backlogProvider"] = {"enabled": True}
    monkeypatch.setattr(
        cli, "goal_tracker_config",
        lambda _d: {"statusField": "Status", "doneStatuses": ["Done"], "allowRepoOnlyGoals": True},
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda *_a, **_k: "")
    facts = cli.done_definition_board_facts(
        data, target, {}, pending_close=True, done_evidence="| ac | PASS |"
    )
    assert facts.provider_enabled is False, "a repo-only goal must skip, not pass"
    outcomes = dod.evaluate_done_conditions(
        BLOCK, replace(_all_green_observations(), board=facts), backlog_enabled=False
    )
    assert _status_of(outcomes, "board_updated") == dod.SKIPPED


# --- Implementation review, round 3 -----------------------------------------------------------


def test_unpushed_commits_on_the_integration_branch_fail_the_bar():
    """R3 P1, and it is this item's own headline defect committed inside the fix for it: the
    previous round RECORDED the unpushed count and then returned a pass anyway -- a field set
    and never read."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=False, on_integration_branch=True,
            integration_branch="experimental", unpushed_commits=3,
        ),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "3 unpushed commit(s)" in outcome.reason

    pushed = replace(obs.pr, unpushed_commits=0)
    assert dod.check_pr_handed_off(replace(obs, pr=pushed)).status == dod.PASS


def test_a_closed_unmerged_pr_fails_rather_than_reporting_unknown():
    """R3 P1. Unknown never blocks, so abandoning a PR satisfied the completion transition."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=True, found=True, merged=False, is_open=False,
            closed_unmerged=True, reference="PR #7",
        ),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "closed without being merged" in outcome.reason


def test_a_dirty_worktree_fails_the_bar():
    """R3 P1. The PR head can match HEAD exactly while the tree carries changes neither the PR
    nor the review has seen, so every other condition can pass on unshipped work."""
    obs = replace(
        _all_green_observations(),
        pr=replace(_all_green_observations().pr, worktree_dirty=True),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "uncommitted changes" in outcome.reason


def test_pr_facts_report_a_dirty_worktree(cli, tmp_path, monkeypatch):
    """Dirtiness is carried even when the PR read itself fails: a lane whose forge is
    unreachable may still be demonstrably dirty, and discarding that fact because a different
    question went unanswered is how a real signal gets lost."""
    target, _run = _lane(tmp_path)
    (target / "uncommitted.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(cli, "github_remote_present", lambda *_a, **_k: False)
    facts = cli.done_definition_pr_facts({}, target, "experimental")
    assert facts.readable is False, "the fixture has no reachable forge"
    assert facts.worktree_dirty is True
    readable_but_dirty = replace(facts, readable=True, found=True, merged=True)
    assert dod.check_pr_handed_off(
        replace(_all_green_observations(), pr=readable_but_dirty)
    ).status == dod.FAIL


def test_a_repo_only_goal_skips_the_board_even_when_the_provider_is_enabled():
    """R3 P1. The FACTS get the last word on whether a board exists, not the adapter's global
    flag: `allowRepoOnlyGoals` leaves `backlogProvider.enabled` true while the goal has no item,
    and judging by the flag made the explicitly sanctioned path fail as 'not at a done status'."""
    obs = replace(
        _all_green_observations(),
        board=dod.BoardFacts(
            provider_enabled=False, readable=True,
            detail="this goal is sanctioned repo-only; there is no board item to close",
        ),
    )
    outcomes = dod.evaluate_done_conditions(BLOCK, obs, backlog_enabled=True)
    assert _status_of(outcomes, "board_updated") == dod.SKIPPED
    assert "repo-only" in _reason_of(outcomes, "board_updated")
    assert dod.done_check_blocking_failures(BLOCK, outcomes) == []


def test_a_dotfile_keeps_its_leading_dot_when_classified():
    """R3 P2. `lstrip("./")` strips CHARACTERS, not a prefix, so `.gitignore` became
    `gitignore`, its own glob could never match, and a gitignore-only change was classified as
    behavior-carrying and demanded a test."""
    assert dod.path_is_non_behavior(".gitignore")
    assert dod.path_is_non_behavior("./.gitignore")
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(readable=True, changed_files=(".gitignore",)),
    )
    outcome = dod.check_tests_written(obs)
    assert outcome.status == dod.PASS


def test_an_earlier_acceptance_sentence_does_not_hide_the_real_done_clause():
    """R3 P2. `acceptance` is a clause marker AND ordinary prose, and only the first match was
    scanned -- so a perfectly good goal was rejected on the strength of an unrelated sentence."""
    from tautline_methodology import goal_assignment as ga

    body = (
        "/goal Implement the acceptance criteria from docs/plans/widget.md. Done when: the PR "
        "is auto-merge armed." + "." * 40
    )
    assert dod.completion_clause_names_handoff_bar(body)
    assert ga.goal_assignment_shape_issues(body, "docs/plans/widget.md") == []


# --- Implementation review, round 4 -----------------------------------------------------------


def test_a_dirty_worktree_fails_even_when_pr_state_is_unreadable():
    """R4 P1, and the same mistake as R3's in a different place: the dirtiness check sat one
    line BELOW the unreadable return, so an offline lane with uncommitted work reported
    `unknown` -- which never blocks -- and completed on changes nobody has seen. Dirtiness is a
    purely LOCAL fact that succeeds when the forge is unreachable; a fact the checker HAS must
    not be withheld because a different question went unanswered."""
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(
            readable=False, detail="gh is not installed", worktree_dirty=True
        ),
    )
    outcome = dod.check_pr_handed_off(obs)
    assert outcome.status == dod.FAIL
    assert "uncommitted changes" in outcome.reason


def test_an_all_skipped_run_is_not_a_green_run():
    """R4 P1. `collected == skipped` is the same nothing-ran state as `collected == 0`, and the
    existing classifier already calls both `current-zero-tests`."""
    obs = replace(
        _all_green_observations(),
        tests=dod.TestGateFacts(
            condition="current", passed=0, failed=0, errors=0, skipped=42, collected=42
        ),
    )
    outcome = dod.check_tests_green(obs)
    assert outcome.status == dod.FAIL
    assert "executed no tests" in outcome.reason


def test_a_deleted_test_does_not_count_but_a_deleted_source_file_still_does():
    """R4 P1. Excluding EVERY deletion was an overcorrection: a deleted behavior file then
    produced an empty diff and a non-blocking unknown, trading one hole for another."""
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(
            readable=True,
            changed_files=("src/pkg/gone.py", "tests/test_gone.py"),
            deleted_files=("src/pkg/gone.py", "tests/test_gone.py"),
        ),
    )
    outcome = dod.check_tests_written(obs)
    assert outcome.status == dod.FAIL, "a deleted test satisfied the condition requiring tests"

    kept = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(
            readable=True,
            changed_files=("src/pkg/thing.py", "tests/test_thing.py"),
            deleted_files=(),
        ),
    )
    assert dod.check_tests_written(kept).status == dod.PASS


def test_the_diff_and_handoff_gatherers_use_the_configured_remote(cli):
    """R4 P2. An adapter whose `latestCode.remote` is `upstream` has a stale-or-absent
    `origin/<branch>`; comparing against it reports upstream-pushed work as missing."""
    import inspect

    for fn in (cli.done_definition_diff_facts, cli.done_definition_pr_facts):
        source = inspect.getsource(fn)
        assert 'f"{remote}/' in source, f"{fn.__name__} still hardcodes a remote"
    observations = inspect.getsource(cli.done_definition_observations)
    assert "lane_status_config(data).get(\"remote\")" in observations


def test_the_shipped_default_enforcement_is_warn():
    """0.65.0 ships `warn`, deliberately, and this pins it so a flip is a conscious act.

    The operator asked for teeth at goal-completion and the teeth are built -- every refusal
    test above proves them under `enforcement: block`, and `done-check` exits 1 on a fail so a
    hook or CI job can enforce today. What ships conservative is only the DEFAULT, because four
    review rounds found false-BLOCK paths in these gatherers three times running. A false pass
    fails to catch something; a false block stops every lane in the fleet at its done boundary.
    Recorded with `tautline decision-record`; the PR body names the one-line change.
    """
    assert dod.DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT == "warn"
    config = dod.normalize_definition_of_done({})
    assert config["enforcement"] == "warn"
    # And under the default a failing condition is REPORTED, never blocking.
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    outcomes = dod.evaluate_done_conditions(config, obs, backlog_enabled=False)
    assert _status_of(outcomes, "pr_handed_off") == dod.FAIL
    assert dod.done_check_blocking_failures(config, outcomes) == []


def test_a_project_that_opts_into_block_gets_the_teeth(cli, tmp_path, monkeypatch):
    """The other half: the capability is real and one adapter key away."""
    target, _run = _lane(tmp_path, enforcement="block")
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    _stub_facts(cli, monkeypatch, obs)
    with pytest.raises(SystemExit) as excinfo:
        _advance(cli, target)
    assert "the definition of done is not met" in str(excinfo.value)


def test_the_default_lane_reports_but_does_not_refuse(cli, tmp_path, monkeypatch, capsys):
    """A lane that sets nothing sees the verdict and is not stopped by it."""
    target, _run = _lane(tmp_path, enforcement=None)
    obs = replace(
        _all_green_observations(),
        pr=dod.PrHandoffFacts(readable=True, found=True, is_open=True, reference="PR #7"),
    )
    _stub_facts(cli, monkeypatch, obs)
    assert _advance(cli, target) == 0
    printed = capsys.readouterr().out
    assert "pr_handed_off fail" in printed, "the failing condition was not reported"


# --- Implementation review, re-bind round -----------------------------------------------------


def test_a_features_directory_is_not_a_test_directory():
    """R5 P1. `src/features/login.ts` is an ordinary feature-organized production layout.
    Classified as a test, a source-only change reported that no behavior-carrying file changed
    and `tests_written` passed with no test at all -- a false pass in the direction that matters.
    The `*.feature` glob already covers Gherkin, which is what the directory was reaching for."""
    assert not dod.path_is_test("src/features/login.ts")
    assert dod.path_is_test("features/login.feature"), "Gherkin is still a test"
    obs = replace(
        _all_green_observations(),
        diff=dod.DiffFacts(readable=True, changed_files=("src/features/login.ts",)),
    )
    outcome = dod.check_tests_written(obs)
    assert outcome.status == dod.FAIL, "a source-only change under features/ passed with no test"


def test_an_adapter_ref_that_looks_like_a_git_option_is_refused():
    """R5 P1, and the only finding in this whole item that could WRITE to the filesystem.
    `definitionOfDone.integrationBranch` is an adapter string and the schema accepts any string,
    so `--output=/tmp/x` becomes `git diff --name-status --output=/tmp/x...HEAD` -- which makes
    git create or truncate that file instead of reading a diff."""
    for unsafe in ("--output=/tmp/x", "-o/tmp/x", "--upload-pack=touch /tmp/pwn", "..", "a..b",
                   "refs/heads/x.lock", "", "--"):
        assert not dod.is_safe_git_ref(unsafe), unsafe
    for safe in ("experimental", "main", "origin", "release/1.2", "feat/definition-of-done"):
        assert dod.is_safe_git_ref(safe), safe


def test_the_gatherers_refuse_an_unsafe_ref_before_calling_git(cli, tmp_path, monkeypatch):
    target, _run = _lane(tmp_path)
    calls = []
    real_run_git = cli.run_git

    def spy(t, args):
        calls.append(args)
        return real_run_git(t, args)

    monkeypatch.setattr(cli, "run_git", spy)
    diff = cli.done_definition_diff_facts(target, "--output=/tmp/pwn", "origin")
    assert diff.readable is False
    assert "unsafe ref" in diff.detail
    assert not any("--output=/tmp/pwn" in " ".join(a) for a in calls), (
        "the unsafe value reached a git argv"
    )
    pr = cli.done_definition_pr_facts({}, target, "--output=/tmp/pwn", "origin")
    assert pr.readable is False and "unsafe" in pr.detail


def test_the_schema_documents_the_default_it_actually_ships():
    """R5 P1. Flipping the default to `warn` left the schema description saying `block` -- a
    documentation lie about the one setting an adopter reads before enabling anything."""
    schema = json.loads((REPO_ROOT / "methodology" / "adapter-schema.json").read_text())
    described = schema["properties"]["definitionOfDone"]["properties"]["enforcement"]["description"]
    assert f"Default: {dod.DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT}" in described, described
    assert "Default: block" not in described


def test_the_ledger_binding_uses_the_recorded_sha_not_the_moving_ref(cli):
    """R6 P1. Once the PR merges, the integration ref moves forward -- so recomputing against
    the SYMBOLIC base_ref puts the merge base at the feature HEAD, yields an empty diff, and
    marks a valid ledger stale. That refuses a lane whose PR has already LANDED, which is the
    one state `pr_handed_off` most explicitly accepts. A sha is immutable."""
    import inspect

    source = inspect.getsource(cli.done_definition_review_facts)
    assert 'ledger.get("base_sha")' in source
    sha_at = source.index('ledger.get("base_sha")')
    ref_at = source.index('ledger.get("base_ref")')
    assert sha_at < ref_at, "the moving symbolic ref is consulted before the immutable sha"


def test_the_stop_advisory_does_not_read_the_board(cli, tmp_path, monkeypatch):
    """R7 P1. The Stop arm is ADVISORY, and a board-backed lane paid up to two 30-second reads
    for a condition that reports `unknown` regardless -- stalling session termination past a
    minute on a slow forge. A hook that makes stopping slow is a hook people disable."""
    target, _run = _lane(tmp_path)
    called = []
    monkeypatch.setattr(
        cli, "done_definition_board_facts",
        lambda *a, **k: called.append(1) or dod.BoardFacts(provider_enabled=False, readable=True),
    )
    _stub_facts(cli, monkeypatch, _all_green_observations())
    # _stub_facts replaces the board gatherer too; re-install the spy so the skip is what is tested.
    monkeypatch.setattr(
        cli, "done_definition_board_facts",
        lambda *a, **k: called.append(1) or dod.BoardFacts(provider_enabled=False, readable=True),
    )
    data = cli.load_project(cli.adapter_marker_path(target))
    cli.done_definition_observations(data, target, None, skip_board=True)
    assert called == [], "the Stop path read the board"
    # And the non-Stop path still does read it.
    cli.done_definition_observations(data, target, None, skip_board=False)
    assert called == [1], "the standalone path stopped reading the board"


# --------------------------------------------------------------------------------------
# The SECOND goal-emitting surface.
#
# `goal-condition` is the documented Claude `/goal` path. WS4 fixed `compose_goal_assignment`
# only, which left the command an operator actually runs still printing the pre-B7 completion
# text -- authorizing a stop at an open unarmed PR while `done-check` and `goal-advance`
# applied the new bar. Caught as a P1 by implementation review on the final tree.
# --------------------------------------------------------------------------------------


def _condition_output(cli, target, capsys):
    assert cli.goal_condition(argparse.Namespace(project=None, target=target)) == 0
    return capsys.readouterr().out


def test_goal_condition_states_the_handoff_bar(cli, tmp_path, capsys):
    target, _run = _lane(tmp_path)
    out = _condition_output(cli, target, capsys)
    assert "Done when:" in out, "the documented /goal path states no definition of done"
    assert "armed to merge without this lane" in out, (
        "the goal a builder is handed must state the handoff bar, or it authorizes the exact "
        "open-PR stop this item exists to refuse"
    )
    assert "never wait for a queued PR to land" in out


def test_goal_condition_and_goal_assignment_state_the_same_bar(cli, tmp_path, capsys):
    """Two surfaces, one source. Re-deriving the bar in each is how divergence comes back."""
    target, _run = _lane(tmp_path)
    out = _condition_output(cli, target, capsys)
    data, _project_path, resolved = cli.lane_project(
        argparse.Namespace(project=None, target=target)
    )
    expected = cli.goal_assignment_module().compose_done_clause(
        cli.goal_assignment_effective_conditions(data, resolved)
    ).strip()
    assert expected in out


def test_goal_condition_drops_a_clause_the_project_disabled(cli, tmp_path, capsys):
    """The printed bar follows the adapter, so it can never demand more than done-check applies."""
    target, _run = _lane(tmp_path, conditions={"pr_handed_off": False})
    out = _condition_output(cli, target, capsys)
    assert "armed to merge without this lane" not in out, (
        "a project that disabled pr_handed_off is still being told to hand off a PR"
    )
    # The rest of the bar survives -- disabling one condition must not blank the sentence.
    assert "Done when:" in out
    assert "implementation review is finalized with no open Critical/P1" in out


def test_a_rerun_without_a_session_id_clears_the_previous_stamp(cli, tmp_path, monkeypatch):
    """A stale stamp is worse than none: the Stop arm then guards the wrong session.

    `goal-complete` rerun in a LATER session with no resolvable id used to leave the earlier
    `completedBySession` in place while refreshing `completedAt`. The arm keys on that stamp,
    so it would suppress the advisory for the session actually standing at the boundary --
    the control reading healthy because its input was stale rather than absent.
    """
    target, _run = _lane(tmp_path)
    _stub_facts(cli, monkeypatch, _all_green_observations())
    assert _advance(cli, target) == 0
    run_path = target / ".ai-work" / "GOAL_RUN.json"
    assert json.loads(run_path.read_text(encoding="utf-8"))["completedBySession"] == (
        "session-under-test"
    )

    # Rerun with no --session-id and no session env var resolvable.
    monkeypatch.setattr(
        cli.util_module(), "resolve_env", lambda *_a, **_k: "", raising=False
    )
    args = argparse.Namespace(
        project=None,
        target=target,
        event="goal-complete",
        milestone_index=None,
        milestone_plan=None,
        milestone_run=None,
        pr=None,
        reason=None,
        detail="validated: the rerun carries no session identity",
        iteration_review_record=None,
        ui_evidence_manifest=None,
        verification_evidence=None,
        verification_evidence_file=None,
        verification_evidence_url=None,
        session_id=None,
    )
    assert cli.goal_advance(args) == 0
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert "completedBySession" not in run, (
        "the rerun inherited a stamp from a session that has ended"
    )


# --------------------------------------------------------------------------------------
# Two more fail-open paths, both found by review on the fixed tree. Each one let a checker
# report a pass on a question it never actually answered.
# --------------------------------------------------------------------------------------


def test_a_rename_keeps_the_deleted_source(cli, tmp_path):
    """`R100<TAB>old<TAB>new` carries both paths; keeping only the destination loses the source.

    Renaming a source file to a non-behavior path would otherwise leave a lone docs file in the
    diff, so `tests_written` passes with no test change -- while the identical edit expressed as
    a delete plus an add is correctly counted. One git formatting detail decided the verdict.
    """
    repo = tmp_path / "renames"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "base"], check=True)
    for arg in (["config", "user.email", "r@example.invalid"], ["config", "user.name", "R"]):
        subprocess.run(["git", "-C", str(repo), *arg], check=True)
    src = repo / "src"
    src.mkdir()
    (src / "tool.py").write_text("def tool():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-verify", "-m", "base"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "work"], check=True)
    docs = repo / "docs"
    docs.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "mv", "src/tool.py", "docs/tool.txt"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-verify", "-m", "rename away"], check=True
    )

    diff = cli.done_definition_diff_facts(repo, "base", remote="origin")
    assert diff.readable
    assert "src/tool.py" in diff.changed_files, "the rename source vanished from the diff"
    assert "src/tool.py" in diff.deleted_files, "the rename source was not counted as deleted"

    # And the condition built on those facts sees behavior with no test.
    obs = replace(_all_green_observations(), diff=diff)
    outcome = dod.check_tests_written(obs)
    assert outcome.status == dod.FAIL, (
        "renaming a source file out of the tree passed the condition that requires tests"
    )


def test_an_unreadable_git_status_is_unknown_not_clean(cli):
    """`unavailable` is a FAILED read, not a clean tree.

    With it collapsed into `dirty=False`, a merged or armed PR carried `pr_handed_off` to a pass
    while worktree cleanliness was never established.
    """
    armed = dod.PrHandoffFacts(
        readable=True,
        found=True,
        is_open=True,
        auto_merge_armed=True,
        reference="PR #7",
        base_ref="experimental",
        integration_branch="experimental",
        head_oid="abc123",
        local_head="abc123",
        worktree_dirty=False,
        worktree_status_readable=False,
    )
    outcome = dod.check_pr_handed_off(replace(_all_green_observations(), pr=armed))
    assert outcome.status == dod.UNKNOWN, (
        "an armed PR answered a question about the worktree that nobody could read"
    )
    assert "git status" in outcome.reason
    # Unknown, not blocking -- the same discipline every other condition follows.
    assert outcome.status != dod.PASS


def test_the_status_sentinel_never_reads_as_a_clean_tree(cli, tmp_path, monkeypatch):
    """The gatherer end, not just the checker: a failing `git status` must set the flag."""
    target, _run = _lane(tmp_path)
    real_run_git = cli.run_git

    def fail_status(t, args, *rest, **kw):
        if args and args[0] == "status":
            return "unavailable"
        return real_run_git(t, args, *rest, **kw)

    monkeypatch.setattr(cli, "run_git", fail_status)
    data, _p, resolved = cli.lane_project(
        argparse.Namespace(project=None, target=target)
    )
    pr_facts = cli.done_definition_pr_facts(
        data, resolved, "experimental", remote="origin"
    )
    assert pr_facts.worktree_status_readable is False
    assert pr_facts.worktree_dirty is False, (
        "an unreadable status must not be reported as dirty either -- it is unknown, not a state"
    )
