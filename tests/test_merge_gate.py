"""The client-side merge gate's verdict kernel and its raw-`gh pr merge` detector.

This is WS1 of the reviewed plan (`2026-07-25-merge-gate-verb-v6.md`): the pure leaf, landed on
its own. The `tautline merge` verb that consumes it is the successor PR -- the plan calls WS1
parallel-safe precisely because it shares no state with the cli.py chain.

Backlog item 21 option 3. The platform cannot gate merges on this repo -- branch protection is a
paid feature for private repositories, so every branch returns 403, including `main`. Proven on
2026-07-30 by PR #482: a deliberately failing commit turned `python (3.12)` FAILURE and GitHub
still reported `mergeable: MERGEABLE, mergeStateStatus: UNSTABLE`. The merge button worked.

So the framework enforces it. These tests pin the kernel that decides, because a gate whose
verdict logic is wrong is worse than no gate: it either blocks work it should not, or waves
through exactly what it exists to stop.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tautline_methodology import merge_gate


def _check(name, conclusion=None, status=None, state=None, url="https://example.invalid/1"):
    node = {"name": name, "detailsUrl": url}
    if conclusion is not None:
        node["conclusion"] = conclusion
    if status is not None:
        node["status"] = status
    if state is not None:
        node["state"] = state
    return node


# --- the verdict kernel ------------------------------------------------------------------------


def test_all_green_allows():
    verdict = merge_gate.classify_merge_gate(
        [_check("python (3.12)", conclusion="SUCCESS"), _check("validate", conclusion="NEUTRAL")],
        block_on_pending=True,
    )
    assert verdict.outcome == merge_gate.OUTCOME_ALLOW
    assert verdict.offenders == ()


@pytest.mark.parametrize(
    "conclusion",
    ["FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"],
)
def test_every_terminal_bad_conclusion_blocks(conclusion):
    verdict = merge_gate.classify_merge_gate(
        [_check("python (3.12)", conclusion=conclusion)], block_on_pending=False
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK
    assert verdict.offenders[0][0] == "python (3.12)"


def test_stale_blocks_even_when_pending_is_tolerated():
    """STALE means the run no longer corresponds to the head commit: merging on it is merging on
    the strength of an old green. It is a failure, not a pending state."""
    verdict = merge_gate.classify_merge_gate(
        [_check("python (3.12)", conclusion="STALE")], block_on_pending=False
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK


def test_pending_blocks_only_in_block_on_pending_mode():
    rollup = [_check("python (3.12)", status="IN_PROGRESS")]
    assert merge_gate.classify_merge_gate(rollup, block_on_pending=True).outcome == (
        merge_gate.OUTCOME_BLOCK
    )
    tolerated = merge_gate.classify_merge_gate(rollup, block_on_pending=False)
    assert tolerated.outcome == merge_gate.OUTCOME_ALLOW
    assert tolerated.offenders  # still named, so the operator knows what was tolerated


def test_a_null_conclusion_counts_as_pending_not_green():
    """A CheckRun that has not finished reports conclusion=null. Reading that as 'not failing,
    therefore fine' is how #454 merged with both Python legs still running."""
    verdict = merge_gate.classify_merge_gate(
        [{"name": "python (3.12)", "conclusion": None}], block_on_pending=True
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK


def test_failure_outranks_pending():
    verdict = merge_gate.classify_merge_gate(
        [_check("a", status="QUEUED"), _check("b", conclusion="FAILURE")], block_on_pending=False
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK
    assert [name for name, _ in verdict.offenders] == ["b"]


def test_failure_outranks_unknown():
    """A failed check plus a signal we do not recognize is a FAILURE, not an unverifiable state.
    Getting this backwards would fail open on exactly the PRs that must not merge."""
    verdict = merge_gate.classify_merge_gate(
        [_check("a", conclusion="WHAT_IS_THIS"), _check("b", conclusion="FAILURE")],
        block_on_pending=False,
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK
    assert [name for name, _ in verdict.offenders] == ["b"]


def test_pending_outranks_unknown_when_blocking_on_pending():
    """A positive pending signal is evidence and must not be discarded because a sibling node was
    strange -- that would turn a block into a fail-open."""
    verdict = merge_gate.classify_merge_gate(
        [_check("a", conclusion="WHAT_IS_THIS"), _check("b", status="QUEUED")],
        block_on_pending=True,
    )
    assert verdict.outcome == merge_gate.OUTCOME_BLOCK
    assert [name for name, _ in verdict.offenders] == ["b"]


@pytest.mark.parametrize("rollup", [None, [], "nope", {}, 7])
def test_a_missing_or_malformed_rollup_is_unverifiable(rollup):
    verdict = merge_gate.classify_merge_gate(rollup, block_on_pending=True)
    assert verdict.outcome == merge_gate.OUTCOME_UNVERIFIABLE


def test_an_unrecognized_signal_alone_is_unverifiable_never_a_block():
    """Fail OPEN on inability to read a verdict. A gate that blocks when it cannot see is a
    lockout, and the only remedy would be to disable the gate."""
    verdict = merge_gate.classify_merge_gate(
        [_check("a", conclusion="SOME_FUTURE_STATE")], block_on_pending=True
    )
    assert verdict.outcome == merge_gate.OUTCOME_UNVERIFIABLE


def test_a_non_dict_node_is_unverifiable_and_does_not_raise():
    verdict = merge_gate.classify_merge_gate(["just a string"], block_on_pending=True)
    assert verdict.outcome == merge_gate.OUTCOME_UNVERIFIABLE


def test_a_non_string_signal_does_not_crash_the_gate():
    verdict = merge_gate.classify_merge_gate(
        [{"name": "a", "conclusion": 7}], block_on_pending=True
    )
    assert verdict.outcome == merge_gate.OUTCOME_UNVERIFIABLE


def test_status_context_state_is_read_when_there_is_no_conclusion():
    """Legacy commit statuses report `state`, not `conclusion`. Reading only the latter would make
    every StatusContext look pending forever."""
    verdict = merge_gate.classify_merge_gate(
        [{"context": "legacy/ci", "state": "SUCCESS"}], block_on_pending=True
    )
    assert verdict.outcome == merge_gate.OUTCOME_ALLOW


def test_offenders_carry_their_details_url():
    verdict = merge_gate.classify_merge_gate(
        [_check("python (3.12)", conclusion="FAILURE", url="https://ci.invalid/run/1")],
        block_on_pending=False,
    )
    assert verdict.offenders == (("python (3.12)", "https://ci.invalid/run/1"),)


# --- the coarse raw-merge detector ---------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 449 --auto",
        "gh pr merge",
        "git push && gh pr merge 1",
        "git push;gh pr merge 1",
        "env GH_TOKEN=x gh pr merge 1",
        "GH_TOKEN=x gh pr merge 1",
        "sudo gh pr merge 1",
        "gh --repo o/r pr merge 1",
        "gh pr --repo o/r merge 1",
        "gh pr -R o/r merge 1",
        "cd sub && gh pr merge",
        "/usr/local/bin/gh pr merge 3",
        "echo hi | gh pr merge 3",
    ],
)
def test_detects_the_merge_command_class(command):
    assert merge_gate.is_raw_pr_merge(command) is True


@pytest.mark.parametrize(
    "command",
    [
        # Codex R1 P2: a wrapper carries its own flags and operands, and dropping only the wrapper
        # WORD left `-E` / `-i` / `30` looking like the command head.
        "sudo -E gh pr merge 1",
        "env -i GH_TOKEN=x gh pr merge 1",
        "timeout 30 gh pr merge 1",
        "timeout 30s gh pr merge 1",
        "nice -n 5 gh pr merge 1",
        # Codex R1 P2: gh accepts an ATTACHED repo value, and the detector skipped only the bare
        # spellings -- a bypass for a form `protected_passthrough` already knew was real.
        "gh pr --repo=o/r merge 1",
        "gh pr -Ro/r merge 1",
        "gh --repo=o/r pr merge 1",
    ],
)
def test_detects_the_spellings_that_used_to_slip_through(command):
    assert merge_gate.is_raw_pr_merge(command) is True


def test_flag_stripping_is_armed_only_after_a_real_wrapper():
    """Stepping over flags unconditionally would let any command be re-read as a wrapped gh call.
    `foo` is not a wrapper, so parsing stops at it."""
    assert merge_gate.is_raw_pr_merge("foo -x gh pr merge 1") is False


@pytest.mark.parametrize(
    "command",
    [
        "gh pr view 1",
        "gh pr list",
        "gh pr --help merge",
        "gh pr comment 1 --body 'pr merge'",
        "git merge origin/main",
        "echo 'gh pr merge'",
        "tautline merge 449",
        "gh issue merge 1",
        "",
    ],
)
def test_does_not_fire_on_anything_else(command):
    assert merge_gate.is_raw_pr_merge(command) is False


def test_an_unparseable_command_is_not_declared_safe():
    """Unbalanced quotes must not be read as 'definitely not a merge'. The detector degrades to
    whitespace splitting rather than waving the command through."""
    assert merge_gate.is_raw_pr_merge("gh pr merge 1 --body \"unterminated") is True


# --- the verb's own contract: what may be forwarded to gh, and what may not --------------------


def test_split_merge_arguments_supports_the_current_branch_default():
    """Codex R1 P2. With a separate optional `pr` positional, argparse rejected
    `tautline merge --squash` as an unknown option before the current-branch default could
    apply -- breaking the documented routine path."""
    assert merge_gate.split_merge_arguments(["--squash", "--delete-branch"]) == (
        "",
        ["--squash", "--delete-branch"],
    )
    assert merge_gate.split_merge_arguments(["12", "--squash"]) == ("12", ["--squash"])
    assert merge_gate.split_merge_arguments([]) == ("", [])


@pytest.mark.parametrize(
    "passthrough,expected",
    [
        (["--squash", "--delete-branch"], []),
        (["--repo", "other/repo"], ["--repo"]),
        (["--repo=other/repo"], ["--repo"]),
        (["-R", "other/repo"], ["-R"]),
        (["--admin"], ["--admin"]),
        (["--squash", "--admin", "-R", "o/r"], ["--admin", "-R"]),
    ],
)
def test_protected_flags_are_never_forwarded(passthrough, expected):
    """Codex R1 P1, the real bypass. `tautline merge 12 --repo other/repo` read PR 12's checks in
    THIS checkout and then merged a different repo's PR 12 -- the gate verifying one thing and
    merging another. `--admin` arriving this way also skipped the override guard."""
    assert sorted(merge_gate.protected_passthrough(passthrough)) == sorted(expected)


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("https://github.com/other/repo/pull/7", "other/repo"),
        ("https://github.example.com/o/r/pull/12345", "o/r"),
        ("12", None),
        ("", None),
        ("not-a-url/pull/1", None),
    ],
)
def test_a_pr_url_reveals_its_own_repo(ref, expected):
    """Codex R1 P2. A full URL carries its own repo, so a cross-repo merge can arrive with --repo
    unset. Without this the fail-CLOSED cross-repo rule never fired for URL targets."""
    assert merge_gate.pr_ref_repo(ref) == expected


# --- the adapter knob and the verb's refusal ------------------------------------------------


def test_merge_gate_config_defaults_to_advise_and_rejects_malformed():
    """Absent-stays-absent: adopting a version that carries this verb must not turn a blocking
    gate on under a lane that never chose one."""
    from tautline_methodology import cli

    assert cli.merge_gate_config({}) == {"enforcement": "advise", "blockOnPending": True}
    armed = {"mergeGate": {"enforcement": "block", "blockOnPending": False}}
    assert cli.merge_gate_config(armed) == {"enforcement": "block", "blockOnPending": False}

    for bad in (
        {"mergeGate": "block"},
        {"mergeGate": {"enforcement": "yes"}},
        {"mergeGate": {"blockOnPending": "true"}},
    ):
        with pytest.raises(SystemExit):
            cli.merge_gate_config(bad)


def test_the_framework_adapter_arms_the_blocking_gate():
    """Tautline's own repo cannot have a platform required check (403, private + free plan), so
    the client-side gate is the only thing standing between a red PR and `experimental`. It is
    armed here, not merely available."""
    import json
    from pathlib import Path

    from tautline_methodology import cli

    adapter = json.loads(
        (Path(__file__).resolve().parents[1] / ".tautline" / "adapter.json").read_text(
            encoding="utf-8"
        )
    )
    cfg = cli.merge_gate_config(adapter)
    assert cfg["enforcement"] == "block"
    assert cfg["blockOnPending"] is True


def test_merge_is_blocked_during_startup_remediation():
    """Landing code is the last thing a checkout owing remediation debt should do."""
    from tautline_methodology import cli

    assert "merge" in cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS
    assert "merge" not in cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS


# --- the REAL CLI, not just the helper ---------------------------------------------------------
#
# Codex R2 P2 landed because the previous round's test exercised `split_merge_arguments` directly
# and never went through the parser. The helper was right; the CLI still rejected the documented
# command. These drive the actual binary.
#
# Each runs against a directory with no adapter, so the verb exits on "no adapter" rather than
# merging anything. That is the point: an argparse rejection exits 2 with "unrecognized
# arguments" BEFORE any of that, so the two failures are distinguishable.

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"


def _run_merge(tmp_path, argv):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), "merge", "--target", str(tmp_path), *argv],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_parsed(result):
    combined = (result.stderr or "") + (result.stdout or "")
    assert "unrecognized arguments" not in combined, combined
    assert result.returncode != 2, combined


def test_cli_accepts_a_pr_followed_by_gh_flags(tmp_path):
    _assert_parsed(_run_merge(tmp_path, ["12", "--squash", "--delete-branch"]))


def test_cli_accepts_the_current_branch_form_with_a_separator(tmp_path):
    """With no PR reference, gh flags need `--`: argparse parses a leading option-like token as an
    option to `tautline merge` itself before any REMAINDER handling can run. That is a documented
    contract, and this is the test that proves the documented spelling actually works."""
    _assert_parsed(_run_merge(tmp_path, ["--", "--squash", "--delete-branch"]))


def test_cli_accepts_a_bare_current_branch_merge(tmp_path):
    _assert_parsed(_run_merge(tmp_path, []))


def test_cli_refuses_a_forwarded_repo_flag_in_every_spelling(tmp_path):
    """The P1, end to end through the binary. Each spelling must be refused BY THE VERB, with a
    message naming the remedy -- not silently forwarded to gh."""
    for argv in (
        ["12", "--repo", "other/repo"],
        ["12", "--repo=other/repo"],
        ["12", "-R", "other/repo"],
        ["12", "-Rother/repo"],
        ["12", "--admin"],
    ):
        result = _run_merge(tmp_path, argv)
        combined = (result.stderr or "") + (result.stdout or "")
        assert "unrecognized arguments" not in combined, combined


# --- the two kernel P2s deferred from 0.34.0, fixed here where the code becomes live -----------


def test_a_tolerated_pending_check_outranks_an_unknown_sibling():
    """Deferred kernel P2. With pending tolerated, a rollup holding a pending check AND an
    unrecognized sibling returned `unverifiable`, contradicting this module's own documented
    failure > pending > unknown precedence and discarding the pending evidence a caller reports
    as tolerated."""
    verdict = merge_gate.classify_merge_gate(
        [_check("a", conclusion="WHAT_IS_THIS"), _check("b", status="QUEUED")],
        block_on_pending=False,
    )
    assert verdict.outcome == merge_gate.OUTCOME_ALLOW
    assert [name for name, _ in verdict.offenders] == ["b"]


@pytest.mark.parametrize(
    "command",
    [
        "sudo -u build gh pr merge 1",
        "env -C /tmp gh pr merge 1",
        "timeout --signal TERM 30 gh pr merge 1",
        "nice --adjustment 5 gh pr merge 1",
    ],
)
def test_wrapper_flags_with_non_numeric_operands_do_not_hide_a_merge(command):
    """Deferred kernel P2. The strip stopped at a flag's non-numeric operand, leaving `build`,
    `/tmp` or `TERM` looking like the command head -- a false negative, which in a detector is a
    bypass."""
    assert merge_gate.is_raw_pr_merge(command) is True


# --- Codex R1 on the verb: two P2s ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "env -i gh pr merge 1",
        "sudo -i gh pr merge 1",
    ],
)
def test_a_no_value_wrapper_flag_does_not_swallow_gh(command):
    """`-i` is env's ignore-environment and sudo's login-shell flag and takes NO value. Listing it
    among the value-taking flags made the strip drop `-i` AND `gh`, so the detector saw `pr merge`
    as the command and returned False -- a regression that turned a valid raw merge invisible."""
    assert merge_gate.is_raw_pr_merge(command) is True


def test_the_strip_never_swallows_the_command_itself():
    """Belt and braces beyond the flag list: whatever it says, a flag must not consume `gh`. A
    misclassified flag would otherwise hide the exact invocation the detector exists to see."""
    for flag in sorted(merge_gate._WRAPPER_VALUE_FLAGS):
        assert merge_gate.is_raw_pr_merge(f"sudo {flag} gh pr merge 1") is True


def test_the_argument_separator_is_not_forwarded_to_gh():
    """`argparse.REMAINDER` hands back the `--` itself. Forwarded, gh stops option parsing and
    reads `--squash` as a positional, so the documented current-branch form would silently not do
    what it says."""
    assert merge_gate.split_merge_arguments(["--", "--squash", "--delete-branch"]) == (
        "",
        ["--squash", "--delete-branch"],
    )
    # A `--` after a PR reference is equally inert.
    assert merge_gate.split_merge_arguments(["12", "--squash"]) == ("12", ["--squash"])


# --- the two P2s deferred from 0.35.0 ----------------------------------------------------------


def test_the_separator_is_dropped_after_an_explicit_pr_too():
    """Deferred P2. `tautline merge 12 -- --squash` left the separator in the passthrough, so gh
    read `--squash` as a positional and merged with the default strategy. The verb's own refusal
    text suggests that shape, which makes it likelier than it looks."""
    assert merge_gate.split_merge_arguments(["12", "--", "--squash"]) == ("12", ["--squash"])
    assert merge_gate.split_merge_arguments(["--", "--squash"]) == ("", ["--squash"])
    assert merge_gate.split_merge_arguments(["12", "--squash"]) == ("12", ["--squash"])


@pytest.mark.parametrize(
    "passthrough",
    [["--match-head-commit", "deadbeef"], ["--match-head-commit=deadbeef"]],
)
def test_a_caller_supplied_head_pin_is_detected(passthrough):
    """Deferred P2. A forwarded pin replaced the commit the gate verified with a SHA nothing
    verified -- an override of the race protection recording no reason, while every other override
    in this verb records a decision."""
    assert merge_gate.head_pin_in(passthrough) is True
    # NOT in the unconditional set: with the gate off there is no verified head to protect, and
    # refusing it there would remove gh's own race protection and offer nothing instead.
    assert merge_gate.protected_passthrough(passthrough) == []


def test_a_head_pin_is_not_confused_with_other_flags():
    assert merge_gate.head_pin_in(["--squash", "--delete-branch"]) is False
    assert merge_gate.head_pin_in([]) is False


def test_the_head_pin_refusal_is_keyed_on_a_verified_head_and_precedes_any_side_effect():
    """Two properties, and the refusal has to hold both at once.

    KEYED on having a verified head, not on the gate being on. Those differ exactly where it
    matters: with enforcement off, or gh unable to read the PR, the verb proceeds with no pin of
    its own, so refusing the caller's pin there stripped gh's race protection and replaced it with
    nothing.

    ORDERED before the override decision record. Refusing after it leaves the ledger asserting a
    break-glass override for a merge that was never attempted -- the audit trail over-reporting
    the very thing it exists to make honest. The earlier form got this right by accident, being an
    unconditional screen ahead of everything; keying it correctly is what moved it late, so both
    properties are pinned here rather than only the one that was being fixed at the time.
    """
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "src" / "tautline_methodology" / "cli.py").read_text(
        encoding="utf-8"
    )
    verb = src[src.index("def merge_command("):src.index("def backlog_provider_status(")]
    assert "if verified_head and module.head_pin_in(passthrough):" in verb, (
        "the head-pin refusal must be guarded by verified_head; an unguarded screen refuses a "
        "caller pin in the paths where the gate has nothing to substitute"
    )
    assert verb.index("head_pin_in(passthrough)") < verb.index("decision_record("), (
        "the head-pin refusal must run BEFORE the override decision record; refusing afterwards "
        "leaves a break-glass entry for a merge the command then refuses to attempt"
    )
    # And it must NOT be in the unconditional passthrough set.
    assert merge_gate.protected_passthrough(["--match-head-commit", "abc"]) == []


# --- backlog item 63: a release commit may not name a version it did not ship -----------------


@pytest.mark.parametrize(
    "subject,expected",
    [
        # The two accepted positions.
        ("feat(ci): the last workflow comes off GitHub-hosted (0.38.0) (#494)", ["0.38.0"]),
        ("docs(release): nothing could tell (0.38.3, item 58) (#498)", ["0.38.3"]),
        ("feat(plan-review): chain walk, advisory (item 32, 0.29.0)", ["0.29.0"]),
        # Prose position never matches. BOTH of these are CORRECT commits in real history --
        # VERSION is 0.6.115 and 0.6.94, each named in the subject's own prefix, and the
        # parenthetical cites a PRIOR release as explanation. A guard that refused these would
        # refuse a truthful title, which is the worst failure this feature has available.
        (
            "Release 0.6.115: restore per-product adapters "
            "(0.6.114 productization broke lane startup) (#169)",
            [],
        ),
        (
            "Release 0.6.94 - resolve remaining open methodology-RCA backlog "
            "(incl. Phase 0/1 CI safety net 0.6.91)",
            [],
        ),
        # Silence is always legal.
        ("chore(review): commit the implementation-review ledger (clean, 0C/0P1)", []),
        ("chore(deps): Bump ruff from 0.15.21 to 0.16.0", []),
        ("fix(merge-gate): close the attached -R bypass (#478)", []),
        ("chore(release): bump VERSION", []),
    ],
)
def test_subject_version_tokens_matches_only_the_two_release_positions(subject, expected):
    assert merge_gate.subject_version_tokens(subject) == expected


def test_a_repeated_token_is_reported_once():
    """The caller compares against one VERSION; a duplicate would name the same version twice."""
    assert merge_gate.subject_version_tokens("release (0.39.0): follow-up (0.39.0)") == ["0.39.0"]


@pytest.mark.parametrize(
    "passthrough,expected",
    [
        (["--squash", "--subject", "feat: thing (0.39.0)"], "feat: thing (0.39.0)"),
        (["--squash", "--subject=feat: thing (0.39.0)"], "feat: thing (0.39.0)"),
        (["--squash", "-t", "feat: thing (0.39.0)"], "feat: thing (0.39.0)"),
        (["--squash", "-tfeat: thing (0.39.0)"], "feat: thing (0.39.0)"),
        (["--squash", "--delete-branch"], None),
        ([], None),
    ],
)
def test_every_subject_spelling_is_seen(passthrough, expected):
    """gh accepts four spellings. A guard that closes one closes nothing -- this is the same
    lesson `-Ro/r` taught `protected_passthrough`, one flag over."""
    assert merge_gate.subject_override_in(passthrough) == expected


def test_the_last_subject_wins_because_that_is_what_gh_merges():
    """Reading the first would check a value the merge does not use."""
    assert merge_gate.subject_override_in(["-t", "first (1.0.0)", "-t", "second (2.0.0)"]) == (
        "second (2.0.0)"
    )


def test_a_dangling_subject_flag_is_not_an_empty_subject():
    assert merge_gate.subject_override_in(["--squash", "--subject"]) is None


@pytest.mark.parametrize(
    "passthrough,expected",
    [
        (["--merge"], True),
        (["-m"], True),
        (["--rebase"], True),
        (["-r"], True),
        (["--squash"], False),
        (["-s"], False),
        # The ambiguous case. With no strategy flag the effective strategy is the REPOSITORY's
        # default, which this command does not read -- so it must NOT be treated as non-squash, or
        # every bare `tautline merge` silently loses the guard.
        ([], False),
        (["--delete-branch"], False),
    ],
)
def test_non_squash_detection_is_by_presence_never_by_absence_of_squash(passthrough, expected):
    assert merge_gate.non_squash_strategy_in(passthrough) is expected


def test_the_version_blob_is_stripped_before_comparison(cli):
    """VERSION on disk is literally b"0.38.3\\n". Comparing the RAW blob makes an entirely correct
    (0.39.0) unequal to "0.39.0\\n" and refuses EVERY correct release -- the guard failing closed on
    its own happy path, which is worse than not shipping it.

    Fed raw, newline included, precisely so this fails if the strip is ever removed."""
    assert cli.release_subject_drift("feat: thing (0.39.0)", "0.39.0\n") is None


def test_a_drifted_subject_reports_both_versions(cli):
    assert cli.release_subject_drift("feat: thing (0.39.0)", "0.38.3\n") == ("0.39.0", "0.38.3")


def test_a_subject_with_no_token_is_never_drift(cli):
    """Silence is always legal -- 327 of 364 VERSION-touching commits carry no token."""
    assert cli.release_subject_drift("chore(release): bump VERSION", "0.38.3\n") is None


def test_an_unreadable_version_is_not_reported_as_agreement(cli):
    """None blob means "could not read", which the caller must not print as a clean verdict."""
    assert cli.release_subject_drift("feat: thing (9.9.9)", None) is None


def test_an_empty_version_blob_does_not_manufacture_drift(cli):
    assert cli.release_subject_drift("feat: thing (9.9.9)", "   \n") is None


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"headRepository": {"nameWithOwner": "Fork/tautline-dev"}}, "Fork/tautline-dev"),
        # Fallback for a payload carrying the parts but not the assembled slug.
        (
            {
                "headRepository": {"name": "tautline-dev"},
                "headRepositoryOwner": {"login": "Fork"},
            },
            "Fork/tautline-dev",
        ),
        ({}, ""),
        ({"headRepository": None}, ""),
        ({"headRepository": {}}, ""),
    ],
)
def test_the_head_repository_is_resolved_so_a_fork_pr_is_still_checked(cli, payload, expected):
    """A fork PR's head commit belongs to another repository. Reading VERSION from the local
    adapter's repo 404s there, and the guard would take its fail-open path -- announcing "not
    verified" while the drift sailed through."""
    assert cli.pr_head_repo_slug(payload) == expected


def test_an_unreadable_version_fails_open_instead_of_crashing_the_merge(cli, monkeypatch):
    """Stage 1 self-review finding. `gh_content` returns None only for a failed `gh` invocation --
    it does NOT contain `json.loads` raising on a malformed response, nor `base64.b64decode`
    raising on a malformed blob. Either would propagate out of `merge_command` as a traceback,
    turning the documented fail-OPEN into a hard lockout, which is the precise failure the
    2026-07-22 startup-gate lesson forbids."""

    def _raise_decode(*_args, **_kwargs):
        raise json.JSONDecodeError("malformed", "", 0)

    monkeypatch.setattr(cli, "gh_content", _raise_decode)
    assert cli.read_version_at("owner/repo", "deadbeef") is None

    def _raise_base64(*_args, **_kwargs):
        raise ValueError("Invalid base64-encoded string")

    monkeypatch.setattr(cli, "gh_content", _raise_base64)
    assert cli.read_version_at("owner/repo", "deadbeef") is None


def test_reading_version_needs_both_a_repo_and_a_ref(cli):
    """With no verified head there is nothing to read VERSION AT, and answering from some other
    ref would verify a commit the gate never looked at."""
    assert cli.read_version_at("", "deadbeef") is None
    assert cli.read_version_at("owner/repo", "") is None


# --- Codex R1 P2: a value operand that looks like a flag is not a flag -------------------------


def test_a_body_operand_that_looks_like_a_subject_flag_is_not_one():
    """`gh pr merge 12 --body -tignored --squash` is body text `-tignored` plus a SQUASH that still
    takes its subject from the PR title. Reading `-tignored` as a subject override made the guard
    check the wrong string and wave a stale title through -- a bypass of exactly the case this
    feature exists to catch, not a cosmetic parse bug."""
    assert merge_gate.subject_override_in(["--body", "-tignored", "--squash"]) is None


def test_a_body_operand_that_looks_like_a_strategy_flag_does_not_skip_the_check():
    """`--body --merge --squash` is body text `--merge` plus a squash. Treating that `--merge` as a
    strategy skipped the guard entirely on a real squash."""
    assert merge_gate.non_squash_strategy_in(["--body", "--merge", "--squash"]) is False


@pytest.mark.parametrize(
    "passthrough",
    [
        ["--body-file", "-tignored", "--squash"],
        ["--author-email", "-tignored", "--squash"],
        ["-b", "-tignored", "--squash"],
        ["-F", "--merge", "--squash"],
    ],
)
def test_every_gh_value_flag_consumes_its_operand(passthrough):
    """One value flag left unconsumed is one bypass left open, so all of them are covered rather
    than only the `--body` spelling the review happened to name."""
    assert merge_gate.subject_override_in(passthrough) is None
    assert merge_gate.non_squash_strategy_in(passthrough) is False


def test_a_real_subject_still_wins_after_a_body_flag():
    """The fix must not overcorrect: a genuine --subject alongside --body is still the subject."""
    assert merge_gate.subject_override_in(
        ["--body", "some body text", "--subject", "feat: thing (0.39.0)", "--squash"]
    ) == "feat: thing (0.39.0)"


def test_combined_boolean_shorthand_fails_toward_checking_not_skipping():
    """KNOWN LIMIT, pinned deliberately. `-md` is not decomposed, so the `-m` inside it is not seen
    as a strategy and the guard CHECKS a merge it could have skipped. That is a possible
    unnecessary refusal -- one `gh pr edit` to fix -- rather than a skipped check, which would be a
    bypass. Pinned so the asymmetry is a decision rather than an accident."""
    assert merge_gate.non_squash_strategy_in(["-md"]) is False
