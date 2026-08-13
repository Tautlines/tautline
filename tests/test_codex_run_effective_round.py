"""The round budget is spent by EXECUTIONS, not by labels.

RCA `20260707T181643Z`: six Codex executions ran against one lineage, every one invoked as `R1`.
Each passed a label-derived cap as round 1 while the aggregate was round 6. Plan review closed the
identical hole in 0.22.0 (`plan_review_effective_round`); implementation review had no analogue and
no visible per-lineage counter, so the spend was invisible from inside the loop and from outside it.

**Two currencies, counted from the same recorded manifests** (the plan's T2.0 decision, and the
thing most of this file exists to pin):

- The **absolute ceiling** counts TOTAL executions. All six of the incident's runs were
  confirming-by-predicate -- each followed a fix and bound a changed hash -- so confirming-ness
  cannot tell the pathology from a healthy remediation loop. Only quantity can.
- The **budget** and the self-authorization rung count CHARGED executions: the confirming predicate
  replayed over the recorded sequence. Collapse the two into one and either the budget silently
  shrinks (a within-budget round after a confirm starts demanding `--allow-extra-rounds`) or a
  converging loop gets refused at the ceiling -- the item-43 deadlock the policy names as a tooling
  defect to repair.

Tests 6 and 7 fail if the currencies are ever collapsed. That is their whole job.
"""
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

BRANCH = "fix/impl-review-round-integrity"
BASE = "base" * 10
OTHER_BASE = "othr" * 10


def record(cli, target, *, diff_sha256: str, base_sha: str = BASE, branch: str = BRANCH,
           index: int = 0, schema: str | None = None) -> None:
    """Write one recorded Stage 2 manifest, named the way `codex-run` names them.

    Filename order IS execution order -- the same idiom `recorded_implementation_round_diff_hashes`
    relies on -- so the index prefix is load-bearing, not decoration.
    """
    evidence = cli.implementation_review_evidence_dir(target)
    evidence.mkdir(parents=True, exist_ok=True)
    slug = cli.slugify(branch, "branch")
    path = evidence / f"2026081100{index:02d}Z-{slug}-{cli.IMPLEMENTATION_REVIEW_STAGE}.json"
    path.write_text(
        json.dumps(
            {
                "schema": schema if schema is not None else cli.IMPLEMENTATION_REVIEW_SCHEMA,
                "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
                "branch": branch,
                "base_sha": base_sha,
                "diff_sha256": diff_sha256,
            }
        ),
        encoding="utf-8",
    )


def lineage(cli, tmp_path, hashes, *, base_sha: str = BASE, branch: str = BRANCH):
    target = tmp_path / "lane"
    target.mkdir(exist_ok=True)
    for index, digest in enumerate(hashes):
        record(cli, target, diff_sha256=digest, base_sha=base_sha, branch=branch, index=index)
    return target


# --- 1. the pure function mirrors plan review's exactly -------------------------------------------


@pytest.mark.parametrize(
    ("declared", "observed", "expected"),
    [(1, 0, 1), (1, 5, 6), (None, 2, 3), (4, 1, 4), (None, 0, 1)],
)
def test_the_effective_round_is_the_higher_of_label_and_recorded_spend(
    cli, declared, observed, expected
) -> None:
    assert cli.implementation_review_effective_round(declared, observed) == expected


# --- 2. the lineage walk: keyed on branch AND base ------------------------------------------------


def test_only_manifests_for_this_lineage_are_counted(cli, tmp_path) -> None:
    """A manifest from an older base -- pre-rebase, or a prior merged PR on a direct-to-main lane --
    must not inflate the count. Lineage is (branch, base_sha), so ANY base change resets it."""
    target = lineage(cli, tmp_path, ["h1", "h2"])
    record(cli, target, diff_sha256="stale", base_sha=OTHER_BASE, index=7)
    record(cli, target, diff_sha256="other-branch", branch="feat/unrelated", index=8)
    record(cli, target, diff_sha256="not-a-review", index=9, schema="something-else/v1")

    assert cli.implementation_review_lineage_diff_hashes(target, BRANCH, BASE) == ["h1", "h2"]
    assert cli.implementation_review_observed_executions(target, BRANCH, BASE) == 2


def test_the_lineage_walk_is_not_vacuous(cli, tmp_path) -> None:
    """Non-vacuity floor: an emptied glob scope returns [] and satisfies most counting assertions
    for the wrong reason. Prove the manifests being counted are actually on disk."""
    target = lineage(cli, tmp_path, ["h1", "h2", "h3"])

    evidence = cli.implementation_review_evidence_dir(target)
    assert len(list(evidence.glob("*.json"))) == 3
    assert cli.implementation_review_observed_executions(target, BRANCH, BASE) == 3


# --- 3. charged executions: the confirming predicate replayed -------------------------------------


@pytest.mark.parametrize(
    ("hashes", "charged"),
    [
        ([], 0),
        (["h1"], 1),
        # Two confirming re-runs: each followed a fix, each bound a NEW hash. Free.
        (["h1", "h2", "h3"], 1),
        # The repeat re-reviews an ALREADY-BOUND diff, so it is new inquiry, so it is charged.
        (["h1", "h2", "h2"], 2),
        (["h1", "h1", "h1"], 3),
    ],
)
def test_charged_executions_replay_the_confirming_predicate(cli, tmp_path, hashes, charged) -> None:
    target = lineage(cli, tmp_path, hashes)

    assert cli.implementation_review_observed_charged_executions(target, BRANCH, BASE) == charged


def test_a_void_manifest_is_not_a_spent_execution(cli, tmp_path) -> None:
    """Codex R3 P2. A void review spends no round, so it must not be counted as one.

    A checkout carrying a pre-0.60.0 void manifest -- exactly what this release stops writing --
    would otherwise start its first REAL review at execution 2, or sit at the hard cap for reviews
    that never had a subject. The same predicate that refuses to write one refuses to count one.
    """
    target = lineage(cli, tmp_path, ["h1"])
    evidence = cli.implementation_review_evidence_dir(target)
    slug = cli.slugify(BRANCH, "branch")
    void = evidence / f"20260811005Z-{slug}-{cli.IMPLEMENTATION_REVIEW_STAGE}.json"
    void.write_text(
        json.dumps({
            "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
            "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
            "branch": BRANCH,
            "base_sha": BASE,
            "head_sha": BASE,
            "diff_sha256": cli.EMPTY_DIFF_SHA256,
            "diff_bytes": 0,
        }),
        encoding="utf-8",
    )
    # Non-vacuity: the void manifest really is in the glob scope being counted.
    assert len(list(evidence.glob("*.json"))) == 2

    assert cli.implementation_review_lineage_diff_hashes(target, BRANCH, BASE) == ["h1"]
    assert cli.implementation_review_observed_executions(target, BRANCH, BASE) == 1
    assert cli.implementation_review_observed_charged_executions(target, BRANCH, BASE) == 1


def test_a_run_that_records_no_evidence_is_not_a_successful_run(cli) -> None:
    """Codex R3 P2. A zero wrapper exit with no manifest is not a successful review: nothing was
    recorded, so nothing can be finalized and nothing binds the diff. Reporting success there is
    the same green-over-nothing shape this item removes, one level up."""
    source = inspect.getsource(cli.codex_run)
    tail = source[source.index("review_evidence_warning: review completed but evidence manifest"):]

    assert "return 1" in tail.split("return returncode")[0], (
        "a recorded run that wrote no manifest must fail, not warn"
    )


def test_the_adapter_dirt_remedy_survives_the_empty_subject_refusal(cli) -> None:
    """Codex R3 P2. When the only dirty files are the generated adapters, "commit your outgoing
    work to a branch" is the wrong instruction and an actively harmful one -- it invites committing
    a tool-injected re-render. Item 69's guard owns that case and names discard or
    --allow-adapter-dirt.

    Gate ORDER is unchanged (C9 pins the subject refusal after the state derivation and before the
    ladder); only the remedy printed changes."""
    source = inspect.getsource(cli.codex_run)
    marker = "subject_errors = implementation_review_subject_errors(state_for_budget)"
    branch = source[source.index(marker):]
    branch = branch[: branch.index("codex_run_error: {message}")]

    assert "codex_run_adapter_dirt_status" in branch
    # C9: still before the ladder.
    assert source.index("implementation_review_subject_errors(state_for_budget)") < source.index(
        "implementation_review_round_cap_errors("
    )


# --- 4. the six-R1 replay: the ceiling counts TOTAL -----------------------------------------------


def _cap_errors(cli, *, round_number, budget, charged_round_number=None, is_confirming=False):
    return cli.implementation_review_round_cap_errors(
        round_number=round_number,
        budget=budget,
        charged_round_number=charged_round_number,
        risk_tier="T1",
        review_round_label="R1",
        is_confirming_round=is_confirming,
    )


def test_the_six_r1_replay_is_refused_at_the_ceiling(cli, tmp_path) -> None:
    """The 2026-07-07 mechanism, replayed. Four recorded executions, each binding a DIFFERENT hash,
    so the charged count is 1 and the fifth invocation is confirming. Under label counting it
    proceeds free forever. The ceiling counts total executions, so it refuses -- and a charged count
    of 1 does not rescue it."""
    target = lineage(cli, tmp_path, ["h1", "h2", "h3", "h4"])
    total = cli.implementation_review_observed_executions(target, BRANCH, BASE)
    charged = cli.implementation_review_observed_charged_executions(target, BRANCH, BASE)
    assert (total, charged) == (4, 1)

    # T1: budget 2, margin 2 -> hard cap 4. Fifth execution, labelled R1, on a changed diff.
    errors = _cap_errors(
        cli,
        round_number=cli.implementation_review_effective_round(1, total),
        budget=2,
        charged_round_number=cli.implementation_review_effective_round(1, charged),
        is_confirming=True,
    )

    assert errors, "the ceiling must count executions, not labels"
    assert "hard cap" in " ".join(errors)


def test_the_remediation_loop_below_the_ceiling_stays_free(cli, tmp_path) -> None:
    """Item 48's loop must survive. Two recorded executions, third confirming invocation: total
    effective round 3 is within the T1 cap of 4, so it proceeds -- the counter bounds the loop
    without re-creating item 43's deadlock."""
    target = lineage(cli, tmp_path, ["h1", "h2"])
    total = cli.implementation_review_observed_executions(target, BRANCH, BASE)

    assert _cap_errors(
        cli,
        round_number=cli.implementation_review_effective_round(1, total),
        budget=2,
        charged_round_number=cli.implementation_review_effective_round(1, 1),
        is_confirming=True,
    ) == []


# --- 5. the two currencies, the tests that fail if they are collapsed -----------------------------


def test_the_budget_stays_reachable_in_charged_rounds(cli, tmp_path) -> None:
    """T2.0 case (a), the silent-budget-cut guard.

    T2: budget 3, hard cap 5. Three recorded executions of which only ONE is charged. A fourth
    invocation whose hash matches a recorded one is NOT confirming, so the budget rung is genuinely
    reached: charged effective round 2 <= budget 3, total effective round 4 <= cap 5. It must
    proceed free, with no --allow-extra-rounds and no spurious recorded-reason demand.

    Under a single currency the total (4) would be compared against the budget (3) and this round
    would be refused -- a budget cut wearing an integrity fix's clothes.
    """
    target = lineage(cli, tmp_path, ["h1", "h2", "h3"])
    total = cli.implementation_review_observed_executions(target, BRANCH, BASE)
    charged = cli.implementation_review_observed_charged_executions(target, BRANCH, BASE)
    assert (total, charged) == (3, 1)

    effective = cli.implementation_review_effective_round(2, total)
    charged_round = cli.implementation_review_effective_round(2, charged)
    assert (effective, charged_round) == (4, 2)

    assert _cap_errors(
        cli, round_number=effective, budget=3, charged_round_number=charged_round
    ) == []
    assert not cli.implementation_review_round_self_authorized(charged_round, 3)


def test_the_ceiling_refusal_names_both_runnable_exits(cli, tmp_path) -> None:
    """T2.0 case (b). A fully confirming loop at the ceiling is refused -- but the refusal must
    offer two exits, NEITHER of which requires another Codex execution. If it can only be satisfied
    by one, that is the item-43 deadlock and the implementation is wrong."""
    target = lineage(cli, tmp_path, ["h1", "h2", "h3", "h4"])
    total = cli.implementation_review_observed_executions(target, BRANCH, BASE)

    errors = _cap_errors(
        cli,
        round_number=cli.implementation_review_effective_round(1, total),
        budget=2,
        charged_round_number=cli.implementation_review_effective_round(1, 1),
        is_confirming=True,
    )
    joined = " ".join(errors)

    assert "smaller PRs" in joined, "the split exit -- a new branch is a new lineage"
    assert "finalize-implementation-review" in joined, "the bind-the-last-reviewed-diff exit"
    # Item 96: the finalize exit is real ONLY when a manifest still binds the current diff. An
    # unconditional promise recreates the dead end where the refusal names an exit finalize refuses.
    assert "binds" in joined or "bound" in joined, (
        "the finalize exit must be phrased conditionally on a manifest that still binds the diff"
    )


def test_the_refusal_explains_why_an_r1_is_round_five(cli, tmp_path) -> None:
    """An unexplained jump from label R1 to round 5 reads as a budget bug. Both currencies and the
    label appear, the same narration discipline `codex_run_confirming_round:` already follows."""
    errors = _cap_errors(cli, round_number=5, budget=2, charged_round_number=2, is_confirming=True)
    joined = " ".join(errors)

    assert "'R1'" in joined or '"R1"' in joined
    assert "charged" in joined


# --- 6. the ladder's existing contract is untouched by the new keyword ----------------------------


def test_the_charged_keyword_defaults_to_the_round_number(cli) -> None:
    """The default makes the change invisible to every existing caller and test. If the ladder's
    26-test contract needs edits, that is a design smell to resolve, not a test to update."""
    for round_number, budget in ((1, 2), (3, 2), (5, 2), (2, 3)):
        assert _cap_errors(cli, round_number=round_number, budget=budget) == _cap_errors(
            cli, round_number=round_number, budget=budget, charged_round_number=round_number
        )


# --- 7. no refusal on this surface hands the decision to a human ----------------------------------


def test_no_new_refusal_tells_an_agent_to_consult_a_human(cli) -> None:
    forbidden = ("escalate", "ask the operator", "consult the operator", "ask the human")
    surfaces = [
        _cap_errors(cli, round_number=5, budget=2, charged_round_number=2, is_confirming=True),
        _cap_errors(cli, round_number=3, budget=2, charged_round_number=3),
    ]

    for errors in surfaces:
        joined = " ".join(errors).lower()
        for phrase in forbidden:
            assert phrase not in joined, f"{phrase!r} in: {joined}"


# --- 8. the counter narrates every recorded run, label or no label --------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def review_lane(tmp_path):
    """A repo with a REAL review subject: one commit ahead of the base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    rendered = subprocess.run(
        [sys.executable, str(CLI_PATH), "render-adapters",
         "--project", str(EXAMPLE_ADAPTER), "--target", str(repo), "--write"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "lane@example.test")
    _git(repo, "config", "user.name", "Lane")
    _git(repo, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    wrapper = repo / "scripts" / "codex-review.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    (repo / ".gitignore").write_text(".ai-work/\n.ai-runs/\n.impl-reviews/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "switch", "-q", "-c", "feat/counted")
    (repo / "subject.py").write_text("# real outgoing work\n", encoding="utf-8")
    _git(repo, "add", "subject.py")
    _git(repo, "commit", "-q", "-m", "real outgoing work")
    return repo, env


def _run(repo: Path, env: dict, *extra: str):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), "codex-run", "--target", str(repo), *extra,
         "--", "./scripts/codex-review.sh"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120,
    )


def test_the_counter_prints_on_a_run_with_no_label_and_no_tier(review_lane) -> None:
    """The counter is about EXECUTIONS, not labels. A spend narrated only when the lane remembers
    to pass a flag is the same invisibility that let six R1s go unnoticed."""
    repo, env = review_lane

    result = _run(repo, env)

    assert "codex_run_execution_count: attempt 1 against outgoing lineage" in result.stdout
    assert "label none" in result.stdout
    assert "0 recorded, 0 charged" in result.stdout


def test_the_counter_counts_up_and_warns_at_three(review_lane) -> None:
    repo, env = review_lane

    first = _run(repo, env, "--risk-tier", "T1", "--review-round", "R1")
    assert "attempt 1 against" in first.stdout, first.stdout + first.stderr
    assert "codex_run_execution_warning:" not in first.stdout

    second = _run(repo, env, "--risk-tier", "T1", "--review-round", "R1")
    assert "attempt 2 against" in second.stdout
    assert "codex_run_execution_warning:" not in second.stdout

    third = _run(repo, env, "--risk-tier", "T1", "--review-round", "R1")
    assert "attempt 3 against" in third.stdout
    assert "codex_run_execution_warning: this would be execution 3" in third.stdout
    assert "smaller PRs" in third.stdout


def test_the_evidence_stamp_is_microsecond_resolution(cli) -> None:
    """Second resolution is what let two executions collide. The counter and the absolute ceiling
    both count RECORDED manifests, so a manifest that can be overwritten is a ceiling that can be
    walked past -- and a fast wrapper (a stub, a cached review, one that fails fast) reproduces it
    on every run."""
    stamp = cli.implementation_review_evidence_stamp()

    assert re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", stamp), stamp
    # No twelve-digit run, ever. These filenames are recorded INTO the tracked `.impl-reviews/`
    # ledger, and the public-release scanner reads twelve consecutive digits as an account-like
    # identifier -- correctly. Without the separator every future review would ship a false
    # positive into a public repo; CI caught it on the first ledger this change produced.
    longest = max((len(run) for run in re.findall(r"\d+", stamp)), default=0)
    assert longest < 12, f"{stamp} contains a {longest}-digit run the public-release scan blocks"
    # Sortable, because filename order IS execution order for the charged-execution replay.
    assert sorted([stamp, cli.implementation_review_evidence_stamp()])[0] == stamp


def test_the_manifest_and_its_log_share_one_stamp_definition(cli) -> None:
    """Codex R1 P2 on this change, and the reason this test is structural rather than timed.

    A manifest and the log it pins are two halves of one piece of evidence. Fixing only the
    manifest is WORSE than fixing neither: unique manifests pointing at an overwritten log make the
    first execution's evidence permanently unfinalizable, because its recorded `log_sha256` no
    longer matches the bytes on disk -- a lost round becomes a corrupt one.

    Pinned by construction rather than by racing the clock. The obvious end-to-end test -- run
    codex-run twice, assert two manifests -- only detects the defect when both runs happen to land
    inside one second, so it passed against the reintroduced bug on the first try. A test that
    proves the invariant only sometimes proves nothing.
    """
    for source in (inspect.getsource(cli.codex_run),
                   inspect.getsource(cli.write_implementation_review_evidence)):
        assert "implementation_review_evidence_stamp()" in source
        assert "strftime" not in source, (
            "evidence filenames must come from the one stamp definition; an inline strftime here "
            "is how the manifest and its log drifted apart in the first place"
        )


def test_a_manifest_always_pins_a_log_that_is_actually_on_disk(review_lane) -> None:
    """The integration half: whatever the stamps are, every recorded manifest's `log_sha256` must
    match the bytes of the log it names, or that execution's evidence can never be finalized."""
    repo, env = review_lane

    _run(repo, env, "--risk-tier", "T1", "--review-round", "R1")
    _run(repo, env, "--risk-tier", "T1", "--review-round", "R1")

    evidence = repo / ".ai-runs" / "review-evidence"
    manifests = sorted(evidence.glob("*-stage2-codex.json"))
    assert len(manifests) == 2, f"two executions collapsed into {len(manifests)} manifest(s)"
    assert [path.name for path in manifests] == sorted(path.name for path in manifests)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        log = repo / manifest["log_path"]
        assert log.exists(), f"{path.name} pins a log that is not on disk"
        digest = hashlib.sha256(log.read_bytes()).hexdigest()
        assert digest == manifest["log_sha256"], (
            f"{path.name} pins a log whose bytes a later execution overwrote"
        )


def test_a_refused_attempt_does_not_advance_the_recorded_count(review_lane) -> None:
    """Codex R4 P2. The counter prints BEFORE the run is known to record anything, so it says
    "attempt", not "execution": a later gate can refuse, or the wrapper can exit non-zero, and in
    either case no manifest is written and the recorded count does not move. Claiming a spend that
    did not happen is the same dishonest accounting this item exists to remove.

    It still prints here rather than after recording, because a lane refused by the ladder is
    exactly when it most needs to see where it stands.
    """
    repo, env = review_lane

    # A T2 attempt with no --native-review-note is refused by a preflight gate downstream of the
    # counter, so nothing is recorded.
    refused = _run(repo, env, "--risk-tier", "T2", "--review-round", "R1")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "attempt 1 against" in refused.stdout
    assert "0 recorded, 0 charged" in refused.stdout

    evidence = repo / ".ai-runs" / "review-evidence"
    manifests = list(evidence.glob("*-stage2-codex.json")) if evidence.is_dir() else []
    assert manifests == [], "a refused attempt recorded evidence"

    # The next attempt is still attempt 1: the refused one spent nothing and claims nothing.
    again = _run(repo, env, "--risk-tier", "T2", "--review-round", "R1")
    assert "attempt 1 against" in again.stdout


@pytest.mark.parametrize(("label", "parsed"), [("retry", None), ("R0", 0), ("R00", 0), ("round zero", None)])
def test_a_label_the_ladder_would_reject_reaches_the_ladder(cli, label, parsed) -> None:
    """The class, not the two members Codex named.

    `implementation_review_round_number` returns None for a label with no digits and 0 for `R0`,
    and the ladder's first rung -- `round_number is None or int(round_number) < 1` -- exists to
    refuse both. Effective-counting either one hands the ladder a positive number and silently
    retires that validation, so an invalid label proceeds and records as round 1.

    This was found twice, as None and as 0, which is the tell that the class is "anything the
    ladder rejects" rather than the two values that happened to be reported.
    """
    assert cli.implementation_review_round_number(label) == parsed
    assert _cap_errors(cli, round_number=parsed, budget=3), "the ladder must refuse this label"

    source = inspect.getsource(cli.codex_run)
    wiring = source[source.index("effective_round = charged_round = ladder_round_number"):]
    wiring = wiring[: wiring.index("round_errors =")]
    assert "if ladder_round_number is not None and ladder_round_number >= 1:" in wiring, (
        "only a POSITIVE parsed marker may be effective-counted"
    )


def test_only_a_positive_marker_is_promoted(cli) -> None:
    """The pure function is unchanged and still promotes; the CALLER decides what is promotable.
    Keeping the guard at the call site is why the ladder's own 29-test contract stays untouched."""
    assert cli.implementation_review_effective_round(0, 4) == 5
    assert cli.implementation_review_effective_round(None, 4) == 5


def test_the_confirming_predicate_reads_the_same_ledger_as_the_counters(cli, tmp_path) -> None:
    """Codex R2 P2. A round that is FREE going in and CHARGED coming out is a budget bug in either
    direction, and that is what two ledgers produce.

    A branch carrying an old-base manifest -- a rebase, a retarget -- has a non-empty BRANCH-WIDE
    recorded set and an EMPTY lineage. Read branch-wide, the first round of the new lineage looks
    like a confirmation: admitted free, no `--extra-round-reason` recorded. The counter, reading
    the lineage, then replays that same round as a charged execution it had never seen.

    Lineage-scoping is also what the rest of this surface already says: a base change starts a
    fresh count, and a fresh count's first round is new inquiry, not owed re-binding.
    """
    target = lineage(cli, tmp_path, [], base_sha=BASE)
    record(cli, target, diff_sha256="from-the-old-base", base_sha=OTHER_BASE, index=0)

    # Branch-wide: a recorded round exists and does not bind the current diff -> reads confirming.
    assert cli.implementation_review_round_is_confirming(target, BRANCH, "current") is True
    # Lineage-scoped: this lineage has reviewed nothing, so the first round is new inquiry.
    assert cli.implementation_review_round_is_confirming(target, BRANCH, "current", BASE) is False
    # And the counters agree with the lineage-scoped answer, which is the whole point.
    assert cli.implementation_review_observed_executions(target, BRANCH, BASE) == 0
    assert cli.implementation_review_observed_charged_executions(target, BRANCH, BASE) == 0

    source = inspect.getsource(cli.codex_run)
    assert "diff_sha256_for_budget, base_for_lineage or None" in source, (
        "codex_run must pass the lineage base so both readings come from one ledger"
    )


def test_a_void_manifest_does_not_make_the_next_round_look_confirming(cli, tmp_path) -> None:
    """The same disagreement, reached through the other filter the lineage walk applies."""
    target = lineage(cli, tmp_path, [], base_sha=BASE)
    evidence = cli.implementation_review_evidence_dir(target)
    evidence.mkdir(parents=True, exist_ok=True)
    slug = cli.slugify(BRANCH, "branch")
    (evidence / f"20260811000Z-{slug}-{cli.IMPLEMENTATION_REVIEW_STAGE}.json").write_text(
        json.dumps({
            "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
            "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
            "branch": BRANCH,
            "base_sha": BASE,
            "head_sha": BASE,
            "diff_sha256": cli.EMPTY_DIFF_SHA256,
            "diff_bytes": 0,
        }),
        encoding="utf-8",
    )

    assert cli.implementation_review_round_is_confirming(target, BRANCH, "current", BASE) is False
    assert cli.implementation_review_observed_executions(target, BRANCH, BASE) == 0


def test_a_slug_colliding_branch_does_not_spend_this_branch_s_budget(cli, tmp_path) -> None:
    """Codex R3 P2. The SLUG is not the branch: `feat/a-b` and `feat/a_b` slugify to the same
    filename component and share the glob. Without verifying the recorded `branch`, a fresh branch
    warns, spends budget, or hits the hard cap on another branch's reviews.

    Same lesson as reading the recorded ledger instead of the label: trust the recorded fact over
    the derived one.
    """
    target = tmp_path / "lane"
    target.mkdir()
    mine, theirs = "feat/a-b", "feat/a_b"
    assert cli.slugify(mine, "branch") == cli.slugify(theirs, "branch"), (
        "this test is vacuous unless the two names really do collide"
    )
    for index, digest in enumerate(["h1", "h2", "h3"]):
        record(cli, target, diff_sha256=digest, branch=theirs, index=index)
    record(cli, target, diff_sha256="mine", branch=mine, index=9)

    # Non-vacuity: all four manifests really are in the glob scope being walked.
    evidence = cli.implementation_review_evidence_dir(target)
    assert len(list(evidence.glob("*.json"))) == 4

    assert cli.implementation_review_lineage_diff_hashes(target, mine, BASE) == ["mine"]
    assert cli.implementation_review_observed_executions(target, mine, BASE) == 1
    assert cli.recorded_implementation_round_diff_hashes(target, mine) == ["mine"]
