"""The definition of done: one named, adapter-overridable set of conditions.

Pure leaf module (no cli import at module scope) so the registry and every checker are
unit-testable in isolation and only thin wiring touches the cli.py monolith -- the same
shape as plan_authoring.py and goal_assignment.py.

WHY THIS EXISTS. Before this module there was no definition of done anywhere in the
framework. The closest thing was a hardcoded sentence in ``compose_goal_assignment``
ending "and the PR is queued to merge" -- so the framework's own goal-writer authorized
stopping with an untouched open PR. Three fragments existed nearby (a board-evidence
gate, a plan-section presence check, and that sentence); none of them was one concept,
none was adapter-overridable, and the one an agent actually reads told it to stop early.

THE CENTRAL CONDITION, AND THE ONE THING IT MUST NEVER BECOME. ``pr_handed_off`` passes
when the PR is OUT OF THE BUILD LANE'S HANDS: merged, or auto-merge armed, or in the
merge queue. It fails only when the PR is open with no merge mechanism armed -- the case
where completion still depends on this lane. It must NEVER require a lane to wait for a
queued PR to land. The framework already ships and renders the rule "a queued
auto-merging PR is Done=shipped, not permission", reinforced by the ``watch-until-merged``
anti-pattern detector whose remedy is "queue-and-move-on policy for clean queued PRs".
Two wastes are available here: stopping at 95%, and a lane idling on a merge monitor.
This bar closes the first WITHOUT creating the second. An earlier draft made the
condition ``pr_merged`` and would have done exactly the latter.

Relatedly: merge-queue membership is read as PRESENCE ONLY. Reading
``mergeQueueEntry.estimatedTimeToMerge`` trips the existing ``stop.wrong_merge_queue_signal``
guard, and a done bar that tripped that guard would be self-defeating.

UNKNOWN IS NOT PASS AND IS NOT ZERO. Every checker takes already-read facts and returns
``unknown`` when the fact it needs is absent or was unreadable. This framework's dominant
defect class is a control that reads healthy because something upstream never let it run;
a done bar that silently passed when it could not check would be that defect with the
highest possible blast radius. ``unknown`` is reported distinctly at every surface and,
per WS2 T2.3, never blocks -- a bar that blocks on what it could not read wedges an
offline lane, and a bar that hides what it could not read is theater.

The fact-gathering half (git, ``gh``, the test-run store, the review ledger) lives in the
cli wiring. This module never shells out and never touches the network, so its checkers
are deterministic and its tests need no fixtures beyond plain dataclasses.
"""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------------------
#
# TUPLES, not lists, throughout this module's UPPER_CASE constants. A UPPER_CASE
# list[str] constant is auto-collected into the policy-phrase SSOT
# (methodology/policy-phrases.json) and would break tests/test_policy_phrases_ssot.py;
# these are a status vocabulary and a glob table, not guard phrases.

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
SKIPPED = "skipped"

CONDITION_STATUSES = (PASS, FAIL, UNKNOWN, SKIPPED)

DONE_CHECK_SCHEMA = "tautline-done-check/v1"

DEFINITION_OF_DONE_ENFORCEMENT_MODES = ("off", "warn", "block")

# `warn` for the FIRST release, and this deviates from the operator's explicit request for
# teeth at goal-completion, so the reasoning is recorded here and in a `tautline
# decision-record` rather than left to be discovered.
#
# The teeth are built, tested and one adapter key away: `definitionOfDone.enforcement: block`
# turns them on, and `done-check` already exits 1 on a fail so a hook or CI job can enforce
# today without waiting for anything.
#
# What argues for warn on the first release is measured, not cautious by temperament. Four
# implementation-review rounds found 21 findings in these checkers, and THREE of the four
# rounds found FALSE-BLOCK paths -- the review base defaulting to `origin/main` in a repo that
# integrates on `experimental` (which would have refused every goal completion in this
# repository), a sanctioned repo-only goal failing a board condition it should skip, a
# `.gitignore`-only change demanding a test, and an unpushed-commit check against a remote the
# adapter does not use. Each was fixed; the pattern is what matters. A false PASS fails to
# catch something. A false BLOCK stops every lane in the fleet at its done boundary, and this
# framework's own standing rule is that a control which wedges lanes teaches its operator to
# bypass it -- which costs more than the control was ever worth.
#
# So: report first, enforce on evidence. Flip the default once the field has exercised the
# gatherers against real PRs, real remotes and real boards.
DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT = "warn"


@dataclass(frozen=True)
class ConditionOutcome:
    """One condition's verdict plus the human-readable reason behind it.

    `reason` is never optional. A bare `fail` with no reason is the shape that makes a
    gate feel arbitrary and teaches its user to route around it.
    """

    condition_id: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in CONDITION_STATUSES:
            raise ValueError(f"unknown condition status: {self.status!r}")


def _outcome(condition_id: str, status: str, reason: str) -> ConditionOutcome:
    return ConditionOutcome(condition_id=condition_id, status=status, reason=reason)


# ---------------------------------------------------------------------------------------
# Observations -- the already-read facts the checkers judge
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PrHandoffFacts:
    """What a PR reader could establish about the lane's branch.

    `readable=False` is the outage case and is the ONLY thing that produces `unknown`
    here; every other combination is a real verdict. `found=False` with
    `on_integration_branch=True` is the legitimate no-PR case (the lane is standing on
    the integration branch itself), which is a pass, not a skip -- nothing is waiting on
    this lane.
    """

    readable: bool = False
    detail: str = ""
    found: bool = False
    merged: bool = False
    is_open: bool = False
    auto_merge_armed: bool = False
    in_merge_queue: bool = False
    on_integration_branch: bool = False
    closed_unmerged: bool = False
    reference: str = ""
    # The PR's own base, and the branch the project integrates on. Compared only when BOTH
    # are known: an unresolvable expectation is not evidence of a wrong base.
    base_ref: str = ""
    integration_branch: str = ""
    # The PR's remote head, and the lane's local tip. A PR can be merged or armed while its
    # head PREDATES the work being completed -- unpushed local commits, or a branch name
    # reused after an earlier merge. "A PR exists and is armed" is not "this work is handed
    # off". Compared only when both are known.
    head_oid: str = ""
    local_head: str = ""
    # Commits on the integration branch that are not on its remote, and whether the worktree
    # carries uncommitted changes. Both mean work that exists ONLY in this lane -- which is the
    # definition of not handed off, whatever a PR says.
    unpushed_commits: int = 0
    worktree_dirty: bool = False
    # Whether `git status` could be read AT ALL. Distinct from `worktree_dirty=False`, which
    # asserts a clean tree. An unreadable index or a broken submodule makes the status read fail,
    # and collapsing that into "clean" lets a matching armed PR carry `pr_handed_off` to a pass
    # while cleanliness was never established -- the fail-open this whole module refuses.
    worktree_status_readable: bool = True


@dataclass(frozen=True)
class ScopeFacts:
    """Goal-run milestones, already loaded. `readable=False` means no goal run was found
    or it could not be parsed -- not that scope is complete."""

    readable: bool = False
    detail: str = ""
    open_units: tuple[str, ...] = ()
    deferred_without_reason: tuple[str, ...] = ()
    total_units: int = 0


@dataclass(frozen=True)
class DiffFacts:
    """The outgoing diff's file list against the integration branch."""

    readable: bool = False
    detail: str = ""
    changed_files: tuple[str, ...] = ()
    # Deletions, kept SEPARATELY rather than excluded. A deleted test must not count as a
    # written one; a deleted source file is still behavior that needs coverage. Dropping every
    # deletion collapsed those two into one wrong answer.
    deleted_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestGateFacts:
    """The newest recorded test run, as classified by test_evidence.classify_test_run_evidence.

    `condition` is that classifier's own vocabulary -- `current` | `red` | `stale` |
    `missing` | `invalid` | `unavailable` -- carried through verbatim rather than
    re-derived, so there is one definition of what a test record proves.
    """

    condition: str = ""
    passed: int | None = None
    failed: int | None = None
    errors: int | None = None
    skipped: int | None = None
    collected: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class ReviewFacts:
    """The implementation-review ledger for this branch."""

    readable: bool = False
    detail: str = ""
    finalized: bool = False
    verdict: str = ""
    classification_status: str = ""
    open_critical: int | None = None
    open_p1: int | None = None
    committed: bool | None = None
    ledger_path: str = ""
    # Whether the ledger's recorded (branch, base_sha, diff_sha256) still describes the
    # outgoing diff. A ledger finalized on commit A stays tracked and clean after commit B is
    # added, so without this a `clean` verdict for a SUPERSEDED diff admits unreviewed code
    # through the blocking bar. `None` means the comparison could not be made.
    covers_current_diff: bool | None = None
    stale_reason: str = ""


@dataclass(frozen=True)
class BoardFacts:
    """The board item's done state, composed from the existing doneEvidence gate rather
    than re-implemented. `provider_enabled=False` is what makes `board_updated` skip.

    `pending_close` is what stops this condition deadlocking the transition it gates.
    `goal_tracker_sync_transition` is what MOVES the item to done, and it runs after the
    pre-flight seam -- so a pre-flight condition demanding "the item is already done" can
    never be satisfied by the command that would satisfy it. When the caller IS that
    transition it sets `pending_close=True` and the condition asks the eligibility question
    (is the closure evidence present?); a standalone `done-check` after the fact leaves it
    False and the condition asks whether the item actually reached done.
    """

    provider_enabled: bool = False
    readable: bool = False
    detail: str = ""
    at_done_status: bool = False
    has_verification_evidence: bool = False
    # Whether the EVIDENCE question could be answered at all, tracked separately from
    # `readable` (which covers the status read). Deriving evidence from the done status would
    # make the condition unfalsifiable in the one case it exists for: an item moved to Done by
    # a human or another tool with no verification comment ever posted.
    evidence_readable: bool | None = None
    pending_close: bool = False
    reference: str = ""


@dataclass(frozen=True)
class DoneObservations:
    """Every fact the registry judges. Each block defaults to its own unreadable state, so
    a caller that gathers nothing gets `unknown` everywhere -- never a silent pass."""

    pr: PrHandoffFacts = field(default_factory=PrHandoffFacts)
    scope: ScopeFacts = field(default_factory=ScopeFacts)
    diff: DiffFacts = field(default_factory=DiffFacts)
    tests: TestGateFacts = field(default_factory=TestGateFacts)
    review: ReviewFacts = field(default_factory=ReviewFacts)
    board: BoardFacts = field(default_factory=BoardFacts)


# ---------------------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------------------


def check_scope_complete(obs: DoneObservations) -> ConditionOutcome:
    facts = obs.scope
    if not facts.readable:
        return _outcome(
            "scope_complete",
            UNKNOWN,
            facts.detail or "no readable goal run; the unit list could not be established",
        )
    if facts.deferred_without_reason:
        return _outcome(
            "scope_complete",
            FAIL,
            "deferred with no recorded reason: " + "; ".join(facts.deferred_without_reason),
        )
    if facts.open_units:
        return _outcome(
            "scope_complete", FAIL, "still open: " + "; ".join(facts.open_units)
        )
    return _outcome(
        "scope_complete",
        PASS,
        f"all {facts.total_units} unit(s) implemented or deferred with a recorded reason",
    )


# Glob table, deliberately a tuple (see the SSOT note at the top of this module). Mirrors
# the pattern list the CI test-gate detector already uses, plus the directory forms.
TEST_PATH_GLOBS = (
    "test_*.py",
    "*_test.py",
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.spec.ts",
    "*.spec.js",
    "*_test.go",
    "*_spec.rb",
    "*.feature",
)

# `features` is DELIBERATELY absent. `src/features/login.ts` is an ordinary feature-organized
# production layout, and classifying it as a test made a source-only change report that no
# behavior-carrying file changed -- so `tests_written` passed with no test at all. The
# `*.feature` glob above already covers Gherkin, which is what the directory was reaching for.
TEST_DIR_SEGMENTS = ("tests", "test", "e2e", "spec", "__tests__")

# Paths that are neither source nor test: a diff of only these has no behavior to cover,
# so `tests_written` must not fail a docs-only or plan-only change.
NON_BEHAVIOR_PATH_GLOBS = (
    "*.md",
    "*.rst",
    "*.txt",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.lock",
    "LICENSE",
    ".gitignore",
)


# A ref this pattern rejects never reaches a git argv. `definitionOfDone.integrationBranch` and
# the configured remote are adapter STRINGS, and the schema accepts any string: a value like
# `--output=/tmp/x` becomes `git diff --name-status --output=/tmp/x...HEAD`, which makes git
# CREATE OR TRUNCATE that file instead of reading a diff. An adapter typo should not be able to
# write to the filesystem.
_SAFE_GIT_REF_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")


def is_safe_git_ref(ref: str) -> bool:
    """True when `ref` is a plain ref name that cannot be read as a git option."""
    candidate = str(ref or "")
    if not candidate or ".." in candidate or candidate.endswith((".lock", "/", ".")):
        return False
    return bool(_SAFE_GIT_REF_RE.match(candidate))


def _clean_path(path: str) -> str:
    """Normalize a repo-relative path WITHOUT eating a leading dot.

    `lstrip("./")` strips CHARACTERS, not a prefix, so it turned `.gitignore` into `gitignore`
    and the explicit `.gitignore` glob could never match -- a gitignore-only change was then
    classified as behavior-carrying and demanded a test.
    """
    cleaned = str(path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def path_is_test(path: str) -> bool:
    """True when a repo-relative path is a test artifact, by filename glob or directory."""
    cleaned = _clean_path(path)
    if not cleaned:
        return False
    name = cleaned.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, glob) for glob in TEST_PATH_GLOBS):
        return True
    return any(segment in TEST_DIR_SEGMENTS for segment in cleaned.split("/")[:-1])


def path_is_non_behavior(path: str) -> bool:
    """True when a path cannot carry behavior (docs, images, lockfiles)."""
    cleaned = _clean_path(path)
    if not cleaned:
        return False
    name = cleaned.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, glob) for glob in NON_BEHAVIOR_PATH_GLOBS)


def check_tests_written(obs: DoneObservations) -> ConditionOutcome:
    facts = obs.diff
    if not facts.readable:
        return _outcome(
            "tests_written",
            UNKNOWN,
            facts.detail
            or "the outgoing diff could not be read; test coverage of the change is unknown",
        )
    if not facts.changed_files:
        return _outcome(
            "tests_written", UNKNOWN, "the outgoing diff lists no files; there is nothing to judge"
        )
    # Non-behavior files are filtered FIRST, on both sides. `tests/README.md` is under a test
    # directory and is not a test: counted as one, it satisfies the condition while no executable
    # test changed at all.
    carrying = [name for name in facts.changed_files if not path_is_non_behavior(name)]
    deleted = set(facts.deleted_files)
    # A DELETED test is not a written test -- removing tests must not satisfy the condition
    # that requires them. A deleted SOURCE file is still a behavior change that needs coverage,
    # so it stays counted.
    tests = [name for name in carrying if path_is_test(name) and name not in deleted]
    behavior = [name for name in carrying if not path_is_test(name)]
    if not behavior:
        return _outcome(
            "tests_written",
            PASS,
            "the change touches no behavior-carrying source file, so it needs no new test",
        )
    if not tests:
        return _outcome(
            "tests_written",
            FAIL,
            f"{len(behavior)} behavior-carrying file(s) changed and no test file changed; "
            "name the tests that cover the new behavior",
        )
    return _outcome(
        "tests_written",
        PASS,
        f"{len(tests)} test file(s) changed alongside {len(behavior)} behavior-carrying file(s)",
    )


# The classifier states that mean the CHECKER could not establish anything, as opposed to
# establishing that the suite is red. Kept as a tuple; see the SSOT note above.
TEST_EVIDENCE_UNKNOWN_CONDITIONS = ("", "missing", "invalid", "stale", "unavailable")


def check_tests_green(obs: DoneObservations) -> ConditionOutcome:
    facts = obs.tests
    condition = str(facts.condition or "")
    if condition in TEST_EVIDENCE_UNKNOWN_CONDITIONS:
        return _outcome(
            "tests_green",
            UNKNOWN,
            facts.detail
            or f"test-run evidence is `{condition or 'absent'}`; the gate's state on this "
            "tip is unknown",
        )
    if condition == "red":
        failed = facts.failed
        tail = f" ({failed} failed)" if isinstance(failed, int) else ""
        return _outcome("tests_green", FAIL, f"the recorded test run is red{tail}")
    if condition != "current":
        return _outcome(
            "tests_green", UNKNOWN, f"unrecognized test-run classification `{condition}`"
        )
    # `current` means the RECORD is trustworthy and the process exited 0 -- it does not mean the
    # report inside it is clean. `pytest ... || true` exits 0 with failures in the report, and the
    # classifier is not the place that partitions them. A gate reading only the exit code would
    # pass a red suite that swallowed its own status: an assertion substituted for an execution.
    failed = facts.failed if isinstance(facts.failed, int) else 0
    errors = facts.errors if isinstance(facts.errors, int) else 0
    if failed or errors:
        return _outcome(
            "tests_green",
            FAIL,
            f"the recorded run exited 0 but its report carries {failed} failed and {errors} "
            "errors; the exit code does not match the report",
        )
    collected = facts.collected if isinstance(facts.collected, int) else None
    skipped = facts.skipped if isinstance(facts.skipped, int) else 0
    executed = None if collected is None else collected - skipped
    if collected == 0 or executed == 0:
        # `collected == skipped` is the same nothing-ran state as `collected == 0`, and the
        # existing test-evidence classifier already calls both `current-zero-tests`. Checking
        # only the exact zero let an all-skipped suite report "0 passed" as a PASS.
        return _outcome(
            "tests_green",
            FAIL,
            f"the recorded run executed no tests ({collected} collected, {skipped} skipped); "
            "a green run of nothing proves nothing",
        )
    if not isinstance(facts.passed, int):
        # UNKNOWN, not pass. The condition's stated bar is "the test gate passes on the branch
        # tip, WITH THE PASS COUNT RECORDED AS A NUMBER", and exit-code-only evidence does not
        # meet it: a suite that collected and ran nothing exits 0 too. Nor is it a `fail` --
        # the run is real and green as far as it goes, and what is missing is the evidence to
        # judge it. Reported, never printed as `0`, which would read as "zero tests passed".
        return _outcome(
            "tests_green",
            UNKNOWN,
            "the recorded test run is current and green by exit code, but records no numeric "
            "pass count (exit-code-only evidence); declare a machine-readable report so counts "
            "parse",
        )
    return _outcome(
        "tests_green", PASS, f"the recorded test run is current and green: {facts.passed} passed"
    )


def check_review_clean(obs: DoneObservations) -> ConditionOutcome:
    facts = obs.review
    if not facts.readable:
        return _outcome(
            "review_clean",
            UNKNOWN,
            facts.detail or "no readable implementation-review ledger for this branch",
        )
    if not facts.finalized:
        return _outcome("review_clean", FAIL, "implementation review is not finalized")
    if facts.covers_current_diff is False:
        return _outcome(
            "review_clean",
            FAIL,
            facts.stale_reason
            or "the implementation-review ledger was finalized against a different diff; the "
            "current outgoing changes are unreviewed",
        )
    if facts.covers_current_diff is None:
        return _outcome(
            "review_clean",
            UNKNOWN,
            "whether the review ledger covers the current outgoing diff could not be established",
        )
    open_critical = facts.open_critical
    open_p1 = facts.open_p1
    if open_critical is None or open_p1 is None:
        return _outcome(
            "review_clean",
            UNKNOWN,
            "the ledger does not report open Critical/P1 counts; severity state is unknown",
        )
    if open_critical or open_p1:
        return _outcome(
            "review_clean",
            FAIL,
            f"implementation review has {open_critical} open Critical and {open_p1} open P1",
        )
    return _outcome(
        "review_clean",
        PASS,
        "implementation review is finalized with 0 open Critical and 0 open P1",
    )


# Both push-eligible verdicts, deliberately. `finalize-implementation-review` and the
# canonical rules permit `clean-with-deferrals` when Critical/P1 are zero and lower findings
# are routed; requiring bare `clean` here would make the default blocking bar reject a
# workflow the framework explicitly sanctions. The severity question belongs to
# `review_clean`, which reads the open Critical/P1 counts; this condition asks only whether
# the evidence is bound and committed.
LEDGER_CLEAN_STATUSES = ("clean", "clean-with-deferrals")


def check_evidence_bound(obs: DoneObservations) -> ConditionOutcome:
    """Is the review evidence committed, clean, and about THIS diff?

    Order matters, and the rule is: an ESTABLISHED failure outranks an unestablished anything.
    A ledger that is demonstrably not committed, or demonstrably not clean, is a fail whatever
    else could not be read -- reporting `unknown` there would hide a fact the checker actually
    has. Only once nothing is known to be wrong do the un-established questions get to speak,
    and then they speak as `unknown`, never as a pass.
    """
    facts = obs.review
    if not facts.readable:
        return _outcome(
            "evidence_bound",
            UNKNOWN,
            facts.detail or "no readable implementation-review ledger for this branch",
        )
    status = str(facts.classification_status or "")

    # --- established failures, in order of how badly they mislead -------------------------
    if status and status not in LEDGER_CLEAN_STATUSES:
        return _outcome(
            "evidence_bound",
            FAIL,
            f"the review-evidence ledger is at classification_status `{status}`",
        )
    if facts.covers_current_diff is False:
        # A committed, clean ledger describing a SUPERSEDED diff is worse than no ledger: it
        # binds evidence to code that is not being shipped, and it reads as proof.
        return _outcome(
            "evidence_bound",
            FAIL,
            facts.stale_reason
            or "the committed review-evidence ledger describes a different diff than the one "
            "being shipped",
        )
    if facts.committed is False:
        return _outcome(
            "evidence_bound",
            FAIL,
            f"the review-evidence ledger `{facts.ledger_path or '.impl-reviews'}` is not committed",
        )

    # --- nothing is known to be wrong; now the unestablished questions --------------------
    if not status:
        return _outcome(
            "evidence_bound", UNKNOWN, "the ledger records no classification_status"
        )
    if facts.committed is None:
        return _outcome(
            "evidence_bound",
            UNKNOWN,
            "whether the ledger is committed could not be established",
        )
    if facts.covers_current_diff is None:
        # `pass` here would claim the evidence is bound on the strength of the ledger merely
        # existing -- and becomes an outright bypass when `review_clean`, which asks the same
        # question, is disabled for the project.
        return _outcome(
            "evidence_bound",
            UNKNOWN,
            "whether the committed ledger describes the current outgoing diff could not be "
            "established",
        )
    return _outcome(
        "evidence_bound", PASS, f"the review-evidence ledger is committed at `{status}`"
    )


def check_pr_handed_off(obs: DoneObservations) -> ConditionOutcome:
    """The central condition. See this module's docstring for why it is HANDOFF, not merge.

    Order matters: every armed state is checked BEFORE the open-and-unarmed fail, so a PR
    that is simultaneously open and queued passes. There is deliberately no branch here
    that returns anything other than a terminal verdict -- nothing in this function can
    tell a lane to wait, and no caller can derive "wait" from its output.
    """
    facts = obs.pr
    # DIRTINESS FIRST, ahead of the unreadable return. Uncommitted work is in no PR and no
    # review, and it is established by a purely LOCAL read that succeeds even when the forge is
    # unreachable -- so an offline lane with a dirty tree was returning `unknown`, which never
    # blocks, and completing on work nobody has seen. The previous round put this check one line
    # too late, which is the same mistake in a different place: a fact the checker HAS, not
    # reported, because a different question went unanswered.
    if facts.worktree_dirty:
        return _outcome(
            "pr_handed_off",
            FAIL,
            "the worktree has uncommitted changes; they are in no PR and no review. Commit and "
            "push them, or stash them, before calling this done",
        )
    if not facts.worktree_status_readable:
        # Checked BEFORE the armed-PR paths below. A failed status read is not a clean tree, and
        # an armed PR must not be allowed to answer a question nobody asked successfully.
        return _outcome(
            "pr_handed_off",
            UNKNOWN,
            "`git status` could not be read, so it is unknown whether uncommitted work is "
            "sitting outside the PR. Re-check where the worktree is readable",
        )
    if not facts.readable:
        return _outcome(
            "pr_handed_off",
            UNKNOWN,
            facts.detail or "PR state could not be read (offline, no credential, or no forge)",
        )
    label = facts.reference or "the branch PR"
    # The base ref is part of the condition, checked BEFORE any armed state. Merged, armed
    # or queued into the WRONG branch is not handed off to the integration path: a stacked
    # PR queued into a peer's unmerged feature branch, or a PR opened against `main` in a
    # repo that integrates on `experimental`, would otherwise satisfy the bar while the work
    # never reaches integration. Compared only when both refs are known -- an unresolvable
    # expectation is not evidence of a wrong base, and is said so in the reason.
    if facts.found and facts.base_ref and facts.integration_branch:
        if facts.base_ref != facts.integration_branch:
            return _outcome(
                "pr_handed_off",
                FAIL,
                f"{label} targets `{facts.base_ref}`, not the integration branch "
                f"`{facts.integration_branch}`; the work does not reach integration through it",
            )
    # A PR that does not CONTAIN the work is not a handoff of the work. Checked before the
    # armed states for the same reason the base ref is: merged-into-the-wrong-thing and
    # armed-without-the-commits are both "a PR exists" masquerading as "this is shipped".
    if facts.found and facts.head_oid and facts.local_head:
        if facts.head_oid != facts.local_head:
            return _outcome(
                "pr_handed_off",
                FAIL,
                f"{label} is at `{facts.head_oid[:12]}` but this lane's tip is "
                f"`{facts.local_head[:12]}`; the PR does not contain the current work. Push the "
                "branch, then re-check",
            )
    if facts.merged:
        return _outcome("pr_handed_off", PASS, f"{label} is merged")
    if facts.auto_merge_armed:
        return _outcome(
            "pr_handed_off",
            PASS,
            f"{label} has auto-merge armed; it merges without this lane, so this lane is done",
        )
    if facts.in_merge_queue:
        return _outcome(
            "pr_handed_off",
            PASS,
            f"{label} is in the merge queue; it merges without this lane, so this lane is done",
        )
    if facts.is_open:
        return _outcome(
            "pr_handed_off",
            FAIL,
            f"{label} is open with no merge mechanism armed, so completion still depends on this "
            "lane; arm auto-merge or enqueue it (do not sit and watch it land)",
        )
    if not facts.found:
        if facts.on_integration_branch:
            branch = facts.integration_branch or "the integration branch"
            # Standing on the integration branch is only a handoff if the work is actually ON
            # the remote. The previous version recorded the unpushed count and then passed
            # anyway -- a field set and never read, which is this item's own headline defect
            # committed inside the fix for it.
            if facts.unpushed_commits:
                return _outcome(
                    "pr_handed_off",
                    FAIL,
                    f"the lane is on `{branch}` with {facts.unpushed_commits} unpushed "
                    "commit(s); the work exists only in this lane until it is pushed",
                )
            return _outcome(
                "pr_handed_off",
                PASS,
                f"the lane is on `{branch}` itself; there is no PR for this work to hand off",
            )
        return _outcome(
            "pr_handed_off",
            FAIL,
            "the branch has no PR, so the work is still entirely in this lane's hands",
        )
    if facts.closed_unmerged:
        # CLOSED without a merge is the clearest possible evidence that the work was NOT handed
        # off. Reported as `unknown` it did not block, so abandoning a PR satisfied the bar.
        return _outcome(
            "pr_handed_off",
            FAIL,
            f"{label} is closed without being merged; the work was not handed off",
        )
    return _outcome(
        "pr_handed_off",
        UNKNOWN,
        f"{label} was found but is in no state this checker recognizes",
    )


def check_board_updated(obs: DoneObservations) -> ConditionOutcome:
    facts = obs.board
    if not facts.provider_enabled:
        # The FACTS get the last word on whether there is a board, not the adapter's global
        # flag. A goal sanctioned as repo-only under `allowRepoOnlyGoals` has no board item
        # while `backlogProvider.enabled` is still true, and judging it by the global flag made
        # the sanctioned path fail with "the board item is not at a done status" -- an
        # explicitly supported workflow rendered unusable by the gate meant to support it.
        return _outcome(
            "board_updated",
            SKIPPED,
            facts.detail or "this goal has no board item to update",
        )
    if not facts.readable:
        return _outcome(
            "board_updated",
            UNKNOWN,
            facts.detail or "board state could not be read",
        )
    label = facts.reference or "the board item"
    if facts.pending_close:
        # The caller IS the transition that closes the item. Asking whether it is already
        # done would make this gate unsatisfiable; ask whether the closure it is about to
        # perform carries the evidence.
        if not facts.has_verification_evidence:
            return _outcome(
                "board_updated",
                FAIL,
                f"this transition would close {label} with no verification evidence",
            )
        return _outcome(
            "board_updated", PASS, f"this transition closes {label} with verification evidence"
        )
    if not facts.at_done_status:
        return _outcome("board_updated", FAIL, f"{label} is not at a done status")
    # Independent of the status, deliberately. A human or another tool can move an item
    # straight to Done without item 81's verification comment ever being posted, so deriving
    # the evidence from the status would make this condition unfalsifiable exactly where it
    # matters -- the case where nothing verified anything.
    if facts.evidence_readable is False:
        return _outcome(
            "board_updated",
            UNKNOWN,
            f"{label} is done, but whether it carries verification evidence could not be read",
        )
    if not facts.has_verification_evidence:
        return _outcome(
            "board_updated", FAIL, f"{label} is done but carries no verification evidence"
        )
    return _outcome("board_updated", PASS, f"{label} is done with verification evidence")


# ---------------------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DoneCondition:
    """One named condition, its checker, and the answer to "what do I do about it?".

    A dataclass record rather than a bare string, on purpose and for two reasons. A
    `list[str]` UPPER_CASE constant is auto-collected into the policy-phrase SSOT and
    would break tests/test_policy_phrases_ssot.py. And a condition with no `remedy` is a
    refusal an agent routes around -- the same defect shape as the round-cap dead end.
    """

    condition_id: str
    passes_when: str
    remedy: str
    checker: Callable[[DoneObservations], ConditionOutcome]
    # "always" | "backlog": `backlog` conditions are enabled only when the project has a
    # backlog provider, so a project with no board never fails a board condition.
    default_scope: str = "always"


DONE_CONDITIONS: dict[str, DoneCondition] = {
    condition.condition_id: condition
    for condition in (
        DoneCondition(
            condition_id="scope_complete",
            passes_when=(
                "every plan workstream is implemented, or explicitly deferred with a "
                "recorded reason"
            ),
            remedy=(
                "finish the open unit, or defer it with `tautline goal-advance "
                "--event milestone-deferred --reason <r>`"
            ),
            checker=check_scope_complete,
        ),
        DoneCondition(
            condition_id="tests_written",
            passes_when="the change's new or changed behavior has named tests",
            remedy=(
                "add a test that fails without the change, and name it in the plan's "
                "test inventory"
            ),
            checker=check_tests_written,
        ),
        DoneCondition(
            condition_id="tests_green",
            passes_when=(
                "the project's test gate passes on the branch tip, with the pass count "
                "recorded as a number"
            ),
            remedy="run and record the gate: `tautline test-run --target .`",
            checker=check_tests_green,
        ),
        DoneCondition(
            condition_id="review_clean",
            passes_when="implementation review is finalized with no open Critical/P1",
            remedy=(
                "fix the open Critical/P1 findings, then "
                "`tautline finalize-implementation-review`"
            ),
            checker=check_review_clean,
        ),
        DoneCondition(
            condition_id="evidence_bound",
            passes_when=(
                "the review-evidence ledger is committed at a push-eligible classification_status "
                "(`clean` or `clean-with-deferrals`)"
            ),
            remedy="commit the `.impl-reviews/` ledger the finalizer wrote",
            checker=check_evidence_bound,
        ),
        DoneCondition(
            condition_id="pr_handed_off",
            passes_when=(
                "the PR is out of this lane's hands: merged, or auto-merge armed, or in the merge "
                "queue, and targeting the integration branch. It NEVER requires waiting for a "
                "queued PR to land"
            ),
            remedy=(
                "arm the merge and move on: `gh pr merge --auto --squash` or enqueue it; "
                "do not watch it land"
            ),
            checker=check_pr_handed_off,
        ),
        DoneCondition(
            condition_id="board_updated",
            passes_when="the board item is at a done status with verification evidence",
            remedy="`tautline goal-advance --event goal-complete --detail <evidence>`",
            checker=check_board_updated,
            default_scope="backlog",
        ),
    )
}

DONE_CONDITION_IDS = tuple(DONE_CONDITIONS)


# ---------------------------------------------------------------------------------------
# Adapter normalization -- read-side only
# ---------------------------------------------------------------------------------------


def normalize_definition_of_done(
    data: Mapping | None, *, default_integration_branch: str = ""
) -> dict:
    """Read-side merge-over-default for the `definitionOfDone` knob.

    NEVER writes back into `data` and is never rendered, so an absent key stays absent on
    disk and no existing adapter needs regeneration -- the `normalize_autonomy` /
    `productDevelopment` precedent, and the reason this item's rendered-adapter byte claim
    is a hard zero.

    SystemExit on a malformed value: fail loud, never silently off. A done bar that
    quietly disabled itself because someone typo'd a condition id would be the exact
    reads-healthy-while-doing-nothing defect this whole item exists to prevent.
    """
    raw = data.get("definitionOfDone") if isinstance(data, Mapping) else None
    if raw is not None and not isinstance(raw, Mapping):
        raise SystemExit("Project adapter definitionOfDone must be an object")
    raw = dict(raw or {})

    unknown_keys = sorted(set(raw) - {"enforcement", "conditions", "integrationBranch"})
    if unknown_keys:
        raise SystemExit(
            "Project adapter definitionOfDone has unknown key(s): "
            + ", ".join(unknown_keys)
            + "; allowed: enforcement, conditions, integrationBranch"
        )

    enforcement = (
        str(raw.get("enforcement", DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT)).strip().lower()
    )
    if enforcement not in DEFINITION_OF_DONE_ENFORCEMENT_MODES:
        raise SystemExit(
            "Project adapter definitionOfDone.enforcement must be "
            + ", ".join(DEFINITION_OF_DONE_ENFORCEMENT_MODES)
        )

    conditions_raw = raw.get("conditions", {})
    if not isinstance(conditions_raw, Mapping):
        raise SystemExit("Project adapter definitionOfDone.conditions must be an object")
    conditions: dict[str, bool] = {}
    for key, value in conditions_raw.items():
        name = str(key)
        if name not in DONE_CONDITIONS:
            raise SystemExit(
                f"Project adapter definitionOfDone.conditions has unknown condition `{name}`; "
                "known conditions: " + ", ".join(DONE_CONDITION_IDS)
            )
        if not isinstance(value, bool):
            raise SystemExit(
                f"Project adapter definitionOfDone.conditions.{name} must be a boolean"
            )
        conditions[name] = value

    branch_raw = raw.get("integrationBranch", "")
    if not isinstance(branch_raw, str):
        raise SystemExit("Project adapter definitionOfDone.integrationBranch must be a string")
    integration_branch = branch_raw.strip() or str(default_integration_branch or "").strip()

    return {
        "enforcement": enforcement,
        "conditions": conditions,
        "integrationBranch": integration_branch,
    }


def condition_is_enabled(config: Mapping, condition_id: str, *, backlog_enabled: bool) -> bool:
    """Per-condition enable/disable, with the default resolved from the condition's scope."""
    condition = DONE_CONDITIONS[condition_id]
    override = (config.get("conditions") or {}).get(condition_id)
    if isinstance(override, bool):
        return override
    if condition.default_scope == "backlog":
        return bool(backlog_enabled)
    return True


# ---------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------


def evaluate_done_conditions(
    config: Mapping,
    observations: DoneObservations,
    *,
    backlog_enabled: bool = False,
) -> list[ConditionOutcome]:
    """Every enabled condition's outcome, in registry order.

    A disabled condition yields a `skipped` outcome rather than vanishing from the list:
    an invisible skip is indistinguishable from a pass at every downstream surface.
    """
    outcomes: list[ConditionOutcome] = []
    for condition_id, condition in DONE_CONDITIONS.items():
        if condition_is_enabled(config, condition_id, backlog_enabled=backlog_enabled):
            outcomes.append(condition.checker(observations))
            continue
        # Name the ACTUAL cause. A condition skipped because the project has no backlog provider
        # and one skipped because someone wrote `false` in the adapter are different facts, and
        # reporting the second when the first is true sends a reader to edit a key that does not
        # exist. A skip line is the only thing a reader gets here, so it has to be true.
        overridden = isinstance((config.get("conditions") or {}).get(condition_id), bool)
        if overridden:
            reason = "disabled for this project by definitionOfDone.conditions"
        elif condition.default_scope == "backlog":
            reason = "this project has no enabled backlog provider, so there is no board to update"
        else:  # pragma: no cover - no non-backlog condition is off by default today
            reason = "not enabled by default for this project"
        outcomes.append(_outcome(condition_id, SKIPPED, reason))
    return outcomes


def done_outcomes_by_status(
    outcomes: Iterable[ConditionOutcome],
) -> dict[str, list[ConditionOutcome]]:
    grouped: dict[str, list[ConditionOutcome]] = {status: [] for status in CONDITION_STATUSES}
    for outcome in outcomes:
        grouped[outcome.status].append(outcome)
    return grouped


def done_verdict(outcomes: Sequence[ConditionOutcome]) -> str:
    """`fail` if anything failed, else `unknown` if anything was unreadable, else `pass`.

    `unknown` outranks `pass` and is NEVER folded into it. It does not block (see
    `done_check_blocking_failures`) but it must remain visible in the verdict, because a
    run in which nothing could be read is exactly as informative as no run at all.
    """
    grouped = done_outcomes_by_status(outcomes)
    if grouped[FAIL]:
        return FAIL
    if grouped[UNKNOWN]:
        return UNKNOWN
    return PASS


def done_check_blocking_failures(
    config: Mapping, outcomes: Sequence[ConditionOutcome]
) -> list[str]:
    """The messages that refuse a done transition. Only `fail` blocks, and only in `block`.

    `unknown` deliberately never appears here. A bar that blocked on what it could not
    read would wedge an offline lane; reporting it loudly and continuing is the only
    honest third option.
    """
    if str(config.get("enforcement", "")) != "block":
        return []
    messages: list[str] = []
    for outcome in outcomes:
        if outcome.status != FAIL:
            continue
        condition = DONE_CONDITIONS[outcome.condition_id]
        messages.append(f"{outcome.condition_id}: {outcome.reason}. Remedy: {condition.remedy}")
    return messages


def done_check_unknown_notices(outcomes: Sequence[ConditionOutcome]) -> list[str]:
    """The loud half of T2.3. Every `unknown` gets a line at every surface, so a bar that
    could not read anything is never mistaken for a bar that passed."""
    return [
        f"{outcome.condition_id}: {outcome.reason}"
        for outcome in outcomes
        if outcome.status == UNKNOWN
    ]


def render_done_check_lines(outcomes: Sequence[ConditionOutcome]) -> list[str]:
    """One `done_condition:` line per condition, plus the summary verdict."""
    lines = [
        f"done_condition: {outcome.condition_id} {outcome.status} - {outcome.reason}"
        for outcome in outcomes
    ]
    grouped = done_outcomes_by_status(outcomes)
    lines.append(
        "done_check_summary: "
        + f"verdict={done_verdict(outcomes)} "
        + " ".join(f"{status}={len(grouped[status])}" for status in CONDITION_STATUSES)
    )
    return lines


def done_check_payload(config: Mapping, outcomes: Sequence[ConditionOutcome]) -> dict:
    """Stable machine-readable shape for `done-check --json`."""
    grouped = done_outcomes_by_status(outcomes)
    return {
        "schema": DONE_CHECK_SCHEMA,
        "enforcement": str(config.get("enforcement", "")),
        "integrationBranch": str(config.get("integrationBranch", "")),
        "verdict": done_verdict(outcomes),
        "counts": {status: len(grouped[status]) for status in CONDITION_STATUSES},
        "conditions": [
            {
                "id": outcome.condition_id,
                "status": outcome.status,
                "reason": outcome.reason,
                "passesWhen": DONE_CONDITIONS[outcome.condition_id].passes_when,
                "remedy": DONE_CONDITIONS[outcome.condition_id].remedy,
            }
            for outcome in outcomes
        ],
        "blocking": done_check_blocking_failures(config, outcomes),
        "unknown": done_check_unknown_notices(outcomes),
    }


# ---------------------------------------------------------------------------------------
# The goal-writing half's shared vocabulary (WS4 reads this; see goal_assignment.py)
# ---------------------------------------------------------------------------------------

# The handoff bar, as one sentence, so the composer and the shape check cannot drift into
# two different bars. Deliberately a single str constant, not a list.
HANDOFF_BAR_CLAUSE = (
    "the PR is merged, or armed to merge without this lane (auto-merge or merge queue)"
)

# What a completion clause must NAME for `goal_assignment_shape_issues` to accept it. A
# clause may say any one of these; the point is that it commits to an ARMED merge rather
# than to an untouched open PR. Tuple, not list: see the SSOT note at the top.
HANDOFF_BAR_MARKERS = (
    r"armed to merge",
    r"auto[- ]merge",
    r"merge queue",
    r"merge[- ]queue",
    r"\bmerged\b",
)

_HANDOFF_BAR_RE = re.compile("|".join(HANDOFF_BAR_MARKERS), re.IGNORECASE)

# A marker preceded by a negation is the OPPOSITE of the bar. "Do not enable auto-merge" and
# "the PR is not merged" both contain a marker and both stop short of handoff, so a bare search
# accepts the very clauses this check exists to reject.
_HANDOFF_NEGATION_RE = re.compile(
    r"(?i)\b(no|not|never|without|avoid|don'?t|do not|neither|nor)\b[^.;]{0,40}?$"
)

# The completion clause only -- from the clause marker to the end of that sentence. Searching
# the whole body lets a handoff word ANYWHERE (including in a prohibition) satisfy a clause
# that itself stops at "a PR is open".
# ONE sentence, stopping at the first SENTENCE terminator -- a period or newline, not a
# semicolon: the composed clause separates its conditions with `; ` inside one sentence,
# and cutting there would hide the handoff condition from the check that requires it.
# Spanning several sentences let unrelated later prose --
# "Done when: tests pass and a PR is open. Auto-merge support is documented later." -- supply a
# marker the completion condition itself never states.
_COMPLETION_CLAUSE_RE = re.compile(
    r"(?i)\b(?:done when|complete when|completion means|acceptance)\b(?P<clause>[^.\n]*)"
)


def completion_clause_text(text: str) -> str:
    """The completion clause itself, or "" when the text states none."""
    match = _COMPLETION_CLAUSE_RE.search(str(text or ""))
    return match.group("clause") if match else ""


def _clause_states_handoff(clause: str) -> bool:
    """True when this one clause names an armed merge WITHOUT negating it."""
    for match in _HANDOFF_BAR_RE.finditer(clause):
        if _HANDOFF_NEGATION_RE.search(clause[: match.start()]):
            continue
        return True
    return False


def completion_clause_names_handoff_bar(text: str) -> bool:
    """True when a COMPLETION CLAUSE affirmatively commits to an armed merge.

    Three narrowings over a bare search, each closing a distinct way to pass while stopping
    short of the bar:

    1. Scoped to a completion clause, so a handoff word elsewhere -- in a prohibition, a
       milestone title, the scope -- cannot satisfy a clause that says "a PR is open".
    2. Negations rejected: "Do not enable auto-merge" and "the PR is not merged" both contain a
       marker and both stop short of handoff.
    3. EVERY clause match considered, not just the first. `acceptance` is a clause marker and
       also ordinary prose, so "Implement the acceptance criteria from the plan. Done when: the
       PR is auto-merge armed." would otherwise be judged on the first sentence and rejected.

    With no clause marker at all the whole text is judged, so a goal phrased without one is
    still weighed rather than silently accepted; reporting the MISSING clause is the caller's
    job, not this function's.
    """
    body = str(text or "")
    clauses = [m.group("clause") for m in _COMPLETION_CLAUSE_RE.finditer(body)]
    if not clauses:
        return _clause_states_handoff(body)
    return any(_clause_states_handoff(clause) for clause in clauses)


__all__ = [
    "BoardFacts",
    "CONDITION_STATUSES",
    "ConditionOutcome",
    "DEFAULT_DEFINITION_OF_DONE_ENFORCEMENT",
    "DEFINITION_OF_DONE_ENFORCEMENT_MODES",
    "DONE_CHECK_SCHEMA",
    "DONE_CONDITIONS",
    "DONE_CONDITION_IDS",
    "DiffFacts",
    "DoneCondition",
    "DoneObservations",
    "FAIL",
    "HANDOFF_BAR_CLAUSE",
    "PASS",
    "PrHandoffFacts",
    "ReviewFacts",
    "SKIPPED",
    "ScopeFacts",
    "TestGateFacts",
    "UNKNOWN",
    "completion_clause_names_handoff_bar",
    "condition_is_enabled",
    "done_check_blocking_failures",
    "done_check_payload",
    "done_check_unknown_notices",
    "done_outcomes_by_status",
    "done_verdict",
    "evaluate_done_conditions",
    "normalize_definition_of_done",
    "path_is_non_behavior",
    "path_is_test",
    "render_done_check_lines",
]
