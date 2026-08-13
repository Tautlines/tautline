import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = ROOT / "adapters" / "projects" / "example-saas.json"


def _run(target_home: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    home = target_home / "home"
    home.mkdir(exist_ok=True)
    command_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "MINERVIT_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/product-milestones",
        "EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/product-milestones",
    }
    if env:
        command_env.update(env)
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        env=command_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _write_fixture_adapter(target: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["backlogProvider"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for goal orchestration behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _prepare_target(tmp_path: Path) -> tuple[Path, Path, Path]:
    target = tmp_path / "goal-target"
    target.mkdir()
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:example-org/example-saas.git"],
        check=True,
    )
    evidence = target / ".ai-work"
    evidence.mkdir()
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")
    adapter = _write_fixture_adapter(target)
    _run(tmp_path, "render-adapters", "--project", str(adapter), "--target", str(target), "--write")
    goal_dir = target / "docs" / "product" / "goals"
    goal_dir.mkdir(parents=True)
    return target, adapter, goal_dir


def _write_goal(goal_dir: Path, name: str, body: str, *, age_seconds: float = 0.0) -> Path:
    """Write a goal plan, optionally back-dated so recency ordering is stated rather than raced.

    Two plans written back to back share an mtime on any machine fast enough to finish both
    inside one kernel timer tick (98 of 100 tries on the self-hosted runner), so a fixture that
    means "this plan is the newer one" has to say so.
    """
    path = goal_dir / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    if age_seconds:
        stamp = path.stat().st_mtime - age_seconds
        os.utime(path, (stamp, stamp))
    return path


def _write_milestone_marker(target: Path, milestone: str, slug: str) -> None:
    marker_dir = target / ".ai-work" / "milestone-update-delivery"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-milestone-update-delivery/v1",
                "milestone": milestone,
                "contentSha256": "fixture",
                "postedAt": "2026-01-01T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_iteration_review_record(target: Path, slug: str, goal_title: str) -> Path:
    record_dir = target / "docs" / "iteration-reviews" / slug
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / "goal-review.json"
    record_path.write_text(
        json.dumps(
            {
                "product": "Example SaaS",
                "goalTitle": goal_title,
                "kicker": "Example SaaS - Iteration Review",
                "why": "The goal can now close only after the customer review is delivered.",
                "milestones": [
                    {
                        "id": "M1",
                        "title": "First milestone completed",
                        "pr": "Ready for customer preview",
                        "status": "complete",
                    },
                    {
                        "id": "M2",
                        "title": "Second milestone completed",
                        "pr": "Ready for customer preview",
                        "status": "complete",
                    },
                ],
                "highlight": {
                    "heading": "The delivery story is complete before the goal closes.",
                    "items": ["Review delivery is checked", "Goal closure is evidence-backed"],
                },
                "quality": {
                    "tests": "Validated with fixture scenarios",
                    "types": "Checked for errors",
                    "review": "Independently reviewed",
                    "discipline": "Delivered in a focused sequence",
                },
                "next": [
                    {
                        "title": "Continue the next goal",
                        "blurb": "Use the next reviewed goal plan after this close-out.",
                    }
                ],
                "nextWhy": "The next goal can start after this one has a complete review.",
                "outro": {
                    "headline": "The goal closes with the review delivered.",
                    "subhead": "Completion now requires the artifact stakeholders receive.",
                },
                "videoUrl": (
                    "https://d111111abcdef8.cloudfront.net/"
                    f"example-saas/iteration-reviews/{slug}/iteration-review.mp4"
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return record_path


def _write_iteration_review_marker(target: Path, slug: str, record_path: Path) -> None:
    page_path = record_path.parent / "index.html"
    marker_dir = target / ".ai-work" / "iteration-review-delivery"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "schema": "minervit-iteration-review-delivery/v1",
                "reviewSlug": slug,
                "recordSha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
                "pageSha256": hashlib.sha256(page_path.read_bytes()).hexdigest(),
                "recordUrl": (
                    "https://d111111abcdef8.cloudfront.net/"
                    f"example-saas/iteration-reviews/{slug}/goal-review.json"
                ),
                "pageUrl": (
                    "https://d111111abcdef8.cloudfront.net/"
                    f"example-saas/iteration-reviews/{slug}/index.html"
                ),
                "provider": "google-chat-webhook",
                "webhookEnv": "EXAMPLE_SAAS_ITERATION_REVIEW_GOOGLE_CHAT_WEBHOOK",
                "postedAt": "2026-06-05T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_goal_lifecycle_requires_proof_markers_and_reports_boundary_condition(tmp_path):
    target, _adapter, goal_dir = _prepare_target(tmp_path)
    _write_goal(
        goal_dir,
        "test-goal-orchestration.md",
        # Older on purpose: the assertions below turn on `next-customer-goal.md` being the more
        # recent plan, which same-tick writes cannot establish.
        age_seconds=60,
        body="""
# Test Goal Orchestration

## Desired Outcome
Validate goal-level continuation above milestones. This is a multi-session goal in the fixture so the session-boundary clause is expected.

## Milestones
- [ ] First goal milestone
- [ ] Second goal milestone

## Risks
- M2 requires operator-provided fixture input before plan-finalization.

## Completion Criteria
- The goal ledger reaches complete only after both milestones are terminal.
""",
    )
    _write_goal(
        goal_dir,
        "next-customer-goal.md",
        """
# Next Customer Goal

## Desired Outcome
Give operators a clearer next customer-facing capability to build after the current goal closes.

## Milestones
- [ ] Shape the next customer-facing milestone

## Completion Criteria
- The next goal has its own ledger, validation proof, and closeout evidence.
""",
    )

    start = _run(
        tmp_path,
        "goal-start",
        "--target",
        str(target),
        "--goal",
        "docs/product/goals/test-goal-orchestration.md",
    )
    assert "next_action_type: continue_milestone" in start.stdout
    assert "next_action: Continue milestone 1: First goal milestone" in start.stdout
    assert "multi_session: true" in start.stdout

    premature = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "goal-complete",
        "--detail",
        "premature proof",
        check=False,
    )
    assert premature.returncode != 0
    assert "goal cannot complete while milestones are non-terminal" in premature.stderr

    no_proof = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-complete",
        check=False,
    )
    assert no_proof.returncode != 0
    assert "--detail or --milestone-run is required for milestone-complete" in no_proof.stderr

    no_marker = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-complete",
        "--detail",
        "first milestone proof",
        check=False,
    )
    assert no_marker.returncode != 0
    assert "milestone update has not been published for this completed milestone" in no_marker.stderr

    _write_milestone_marker(target, "First goal milestone", "first-goal-milestone")
    advance = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-complete",
        "--detail",
        "first milestone proof",
    )
    assert "percent_complete: 50" in advance.stdout
    assert "next_action: Continue milestone 2: Second goal milestone" in advance.stdout
    assert "known_operator_dependencies: 1" in advance.stdout
    assert "current_milestone_operator_dependency: M2 requires operator-provided fixture input before plan-finalization." in advance.stdout

    condition = _run(tmp_path, "goal-condition", "--target", str(target))
    assert "goal_condition_scope: claude-lanes" in condition.stdout
    assert "goal_condition: /goal Complete goal" in condition.stdout
    assert "required validation proof is surfaced in this conversation" in condition.stdout
    assert "authorized increment is delivered" in condition.stdout
    assert "Context exhaustion by itself does not satisfy the goal" in condition.stdout
    assert "invoke `/compact` or the strongest host compact/restart path" in condition.stdout

    _write_milestone_marker(target, "Second goal milestone", "second-goal-milestone")
    advance_2 = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-complete",
        "--detail",
        "second milestone proof",
    )
    assert "percent_complete: 100" in advance_2.stdout

    no_review = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "goal-complete",
        "--detail",
        "all milestones complete with validation proof",
        check=False,
    )
    assert no_review.returncode != 0
    assert "goal-complete requires --iteration-review-record" in no_review.stderr

    record_path = _write_iteration_review_record(target, "test-goal-orchestration", "Test Goal Orchestration")
    wrong_dir = target / "docs" / "iteration-reviews" / "wrong-goal-slug"
    wrong_dir.mkdir(parents=True)
    wrong_record = wrong_dir / "goal-review.json"
    wrong_record.write_text(record_path.read_text(encoding="utf-8"), encoding="utf-8")

    wrong_validate = _run(
        tmp_path,
        "validate-iteration-review",
        "--target",
        str(target),
        "--file",
        str(wrong_record),
        check=False,
    )
    assert wrong_validate.returncode != 0
    assert "record folder slug does not match the active goal_id" in wrong_validate.stderr

    wrong_publish = _run(
        tmp_path,
        "publish-iteration-review",
        "--target",
        str(target),
        "--record",
        "docs/iteration-reviews/wrong-goal-slug/goal-review.json",
        "--dry-run",
        check=False,
    )
    assert wrong_publish.returncode != 0
    assert "record folder slug does not match the active goal_id" in wrong_publish.stderr

    _run(
        tmp_path,
        "generate-iteration-review-page",
        "--target",
        str(target),
        "--record",
        "docs/iteration-reviews/test-goal-orchestration/goal-review.json",
        "--write",
    )
    _run(
        tmp_path,
        "publish-iteration-review",
        "--target",
        str(target),
        "--record",
        "docs/iteration-reviews/test-goal-orchestration/goal-review.json",
        "--dry-run",
    )
    _write_iteration_review_marker(target, "test-goal-orchestration", record_path)

    complete = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "goal-complete",
        "--detail",
        "all milestones complete with validation proof",
        "--iteration-review-record",
        "docs/iteration-reviews/test-goal-orchestration/goal-review.json",
    )
    assert "status: complete" in complete.stdout
    assert "next_action_type: goal_complete" in complete.stdout
    assert "next_goal_active: false" in complete.stdout
    assert "next_goal_name: Next Customer Goal" in complete.stdout
    assert "next_goal_short_description: Give operators a clearer next customer-facing capability" in complete.stdout
    assert "next_goal_claude_prompt: /goal Make goal `next-customer-goal` execution-ready and complete it" in complete.stdout
    assert "next_goal_name: Test Goal Orchestration" not in complete.stdout

    ledger = json.loads((target / ".ai-work" / "GOAL_RUN.json").read_text(encoding="utf-8"))
    assert ledger["iterationReviewRecord"] == "docs/iteration-reviews/test-goal-orchestration/goal-review.json"

    completed_status = _run(tmp_path, "methodology-status", "--target", str(target), "--no-remote")
    assert "goal_status: complete" in completed_status.stdout
    assert "next_goal_name: Next Customer Goal" in completed_status.stdout
    assert (
        "next_goal_claude_prompt: /goal Make goal `next-customer-goal` execution-ready and complete it"
        in completed_status.stdout
    )

    (target / ".ai-work" / "GOAL_RUN.json").unlink()
    candidate_status = _run(tmp_path, "methodology-status", "--target", str(target), "--no-remote")
    assert "goal_status: missing" in candidate_status.stdout
    assert "next_goal_source: repo-goal-plans" in candidate_status.stdout
    assert "next_goal_name: Next Customer Goal" in candidate_status.stdout
    assert "next_goal_status: needs-review" in candidate_status.stdout
    assert "next_goal_next_action: run the required cross-model review/precheck" in candidate_status.stdout

    kickoff = _run(tmp_path, "goal-kickoff-prompt", "--target", str(target))
    assert "goal_kickoff_mode: no-active-goal" in kickoff.stdout
    assert "next_goal_name: Next Customer Goal" in kickoff.stdout
    assert "next_goal_claude_prompt: /goal Make goal `next-customer-goal` execution-ready and complete it" in kickoff.stdout


def test_same_mtime_goal_plans_are_ordered_by_name_not_by_directory_luck(tmp_path):
    """Plans that share a timestamp must still order deterministically, ascending by name.

    Ties are the normal case, not the exotic one: a fresh clone stamps every plan with the single
    checkout time, and two plans written back to back share a tick. The old ordering sorted
    `(mtime, name)` in reverse, so those ties resolved reverse-alphabetically and the last name in
    the directory read as "the most recent plan" -- which is how the fixture below used to hand
    `zz-...` back as the next goal on a fast machine.
    """
    target, _adapter, goal_dir = _prepare_target(tmp_path)
    body = """
# {title}

## Desired Outcome
Ordering fixture for tied plan timestamps.

## Milestones
- [ ] Only milestone

## Completion Criteria
- Done.
"""
    first = _write_goal(goal_dir, "aa-first-plan.md", body.format(title="Aa First Plan"))
    last = _write_goal(goal_dir, "zz-last-plan.md", body.format(title="Zz Last Plan"))
    shared = first.stat().st_mtime
    for path in (first, last):
        os.utime(path, (shared, shared))

    status = _run(tmp_path, "methodology-status", "--target", str(target), "--no-remote")
    assert "next_goal_name: Aa First Plan" in status.stdout
    assert "next_goal_name: Zz Last Plan" not in status.stdout


def test_goal_condition_omits_boundary_clause_without_operator_dependency(tmp_path):
    target, _adapter, goal_dir = _prepare_target(tmp_path)
    _write_goal(
        goal_dir,
        "test-no-operator-dependency-goal.md",
        """
# Test No Operator Dependency Goal

## Desired Outcome
Validate ordinary implementation language does not become a human dependency.

## Milestones
- [ ] Validate ordinary implementation terms

## Risks
- M1 input validation must reject malformed CSV payloads.
- M1 fixture data should stay deterministic.
- M1 blocked states render correctly in the UI.

## Completion Criteria
- The goal condition omits the current-session authorized-increment clause.
""",
    )

    start = _run(
        tmp_path,
        "goal-start",
        "--target",
        str(target),
        "--goal",
        "docs/product/goals/test-no-operator-dependency-goal.md",
    )
    assert "multi_session: false" in start.stdout
    assert "known_operator_dependencies: 0" in start.stdout

    condition = _run(tmp_path, "goal-condition", "--target", str(target))
    assert "authorized increment is delivered" not in condition.stdout


def test_goal_deferred_and_blocked_terminal_transitions(tmp_path):
    target, _adapter, goal_dir = _prepare_target(tmp_path)
    _write_goal(
        goal_dir,
        "test-deferred-goal.md",
        """
# Test Deferred Goal

## Desired Outcome
Validate policy deferral.

## Milestones
- [ ] Deferrable goal milestone

## Completion Criteria
- The deferred milestone can be terminal only with a reason.
""",
    )
    _run(tmp_path, "goal-start", "--target", str(target), "--goal", "docs/product/goals/test-deferred-goal.md")

    missing_reason = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-deferred",
        check=False,
    )
    assert missing_reason.returncode != 0
    assert "--reason is required for milestone-deferred" in missing_reason.stderr

    deferred = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-deferred",
        "--reason",
        "policy deferral recorded in source-of-truth plan",
    )
    assert "next_action_type: ready_for_goal_completion" in deferred.stdout

    (target / ".ai-work" / "GOAL_RUN.json").unlink()
    _write_goal(
        goal_dir,
        "test-blocked-goal.md",
        """
# Test Blocked Goal

## Desired Outcome
Validate true blocker goal output.

## Milestones
- [ ] Credential-bound goal milestone

## Completion Criteria
- Blocking the milestone returns a true blocker.
""",
    )
    _run(tmp_path, "goal-start", "--target", str(target), "--goal", "docs/product/goals/test-blocked-goal.md")
    blocked = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-blocked",
        "--reason",
        "credential unavailable",
    )
    assert "next_action_type: true_blocker" in blocked.stdout
    assert "True blocker on milestone 1: credential unavailable" in blocked.stdout


def _start_single_milestone_goal(tmp_path: Path, name: str, title: str) -> Path:
    target, _adapter, goal_dir = _prepare_target(tmp_path)
    _write_goal(
        goal_dir,
        name,
        f"""
# {title}

## Desired Outcome
Validate the milestone acVerification evidence channel.

## Milestones
- [ ] {title} milestone

## Completion Criteria
- The AC verification channel behaves as specified.
""",
    )
    _run(tmp_path, "goal-start", "--target", str(target), "--goal", f"docs/product/goals/{name}")
    return target


def _set_ac_verification(target: Path, value: str) -> None:
    run_path = target / ".ai-work" / "GOAL_RUN.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["milestones"][0]["acVerification"] = value
    run_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_an_empty_ac_verification_file_does_not_satisfy_the_completion_guard(tmp_path):
    """Codex R2 P2(a): the guard weighs the RESOLVED text, not the key's truthiness.

    Resolving the same value twice and getting two answers is what makes this dangerous: the key
    would satisfy the guard, composition would contribute nothing, and the command could publish
    the required UI-proof comment before refusing for missing verification evidence -- mutating on
    a refused move, which the whole seam exists to prevent.
    """
    target = _start_single_milestone_goal(tmp_path, "test-empty-ac.md", "Empty AC")
    (target / "ac.md").write_text("   \n\n", encoding="utf-8")
    _set_ac_verification(target, "ac.md")

    refused = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-complete",
        check=False,
    )

    assert refused.returncode != 0
    assert "--detail or --milestone-run is required for milestone-complete" in refused.stderr
    assert "acVerification is set but resolves to no text" in refused.stderr


def test_a_non_empty_ac_verification_file_satisfies_the_completion_guard(tmp_path):
    """The other half of the same pin: with real text and NO command-line flag, the guard opens.

    This is the whole point of the channel -- without this the feature does not exist.
    """
    target = _start_single_milestone_goal(tmp_path, "test-ac-guard.md", "AC Guard")
    (target / "ac.md").write_text(
        "| criterion | verdict |\n| --- | --- |\n| the one thing | PASS |\n", encoding="utf-8"
    )
    _set_ac_verification(target, "ac.md")
    _write_milestone_marker(target, "AC Guard milestone", "ac-guard-milestone")

    completed = _run(
        tmp_path, "goal-advance", "--target", str(target), "--event", "milestone-complete"
    )

    assert completed.returncode == 0
    run = json.loads((target / ".ai-work" / "GOAL_RUN.json").read_text(encoding="utf-8"))
    assert run["milestones"][0]["status"] == "complete"


def test_a_broken_ac_verification_path_still_lets_a_milestone_be_blocked(tmp_path):
    """Codex R2 P2(b): resolved for milestone-complete only.

    milestone-blocked and -deferred never use AC verification, and a stale or out-of-tree path must
    not be able to block the very transitions a lane uses to report that something is wrong -- that
    would make a bad ledger value unrecoverable without hand-editing the ledger.
    """
    target = _start_single_milestone_goal(tmp_path, "test-broken-ac.md", "Broken AC")
    _set_ac_verification(target, "../escapes-the-checkout.md")

    blocked = _run(
        tmp_path,
        "goal-advance",
        "--target",
        str(target),
        "--event",
        "milestone-blocked",
        "--reason",
        "credential unavailable",
    )

    assert "next_action_type: true_blocker" in blocked.stdout
