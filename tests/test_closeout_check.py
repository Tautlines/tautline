import json
import pytest
import argparse
"""A merged PR owes its board closeout, and the owing survives the merge.

Item 79 WS1. The RCA cluster: work merged, the board was never moved to done, and nothing noticed
— because the only thing that could have noticed ran BEFORE the merge, when the answer was still
"not yet". After the merge there was no gate left, and the lane moved on.

So the check runs after the merge, and what it finds is recorded in lane state so a later boundary
can block on it. Two halves with deliberately different postures:

- The explicit verb `backlog-provider-closeout-check` is **fail-closed** (D1). Its green means
  verified: an unreachable provider is a failure, not a pass, because "I could not look" and
  "nothing is owed" must never be the same exit code.
- The passive boundary predicate **fails open with a named warning** (D3). A GitHub outage must
  not wedge every push on every lane over a fact only GitHub holds. Silence is forbidden on both
  sides; the difference is whether the lane stops.

**Scope fence (packet §0):** the boundary block ships at `guard-check --boundary status` and
`prepush` ONLY. The stop seam is wave-3 territory and no batch-2 slot may add a blocking
condition to the Stop-guard surface. There is deliberately no stop-boundary assertion here.
"""
PR = 4242
DONE = "Done"
ACTIVE = "In Progress"


def _adapter(**overrides) -> dict:
    data = {
        "project": "Fixture",
        "goalTracker": {
            "enabled": True, "provider": "github-projects", "owner": "example-org",
            "projectNumber": 7, "statusField": "Status", "doneStatuses": [DONE],
            "activeStatuses": [ACTIVE], "readyStatuses": ["Ready"], "blockedStatuses": ["Blocked"],
        },
        "backlogProvider": {
            "enabled": True, "provider": "github-projects", "owner": "example-org",
            "projectNumber": 7, "statusField": "Status", "doneStatuses": [DONE],
            "activeStatuses": [ACTIVE],
        },
        "laneState": {"goalRun": ".ai-work/GOAL_RUN.json"},
    }
    data.update(overrides)
    return data


def _item(number: int, status: str) -> dict:
    return {
        "content": {"url": f"https://github.com/example-org/repo/issues/{number}",
                    "number": number, "title": f"issue {number}", "state": "CLOSED"},
        "fieldValues": {"Status": status},
    }


def _wire(cli, monkeypatch, *, items=None, raises=None, refs=("101",)):
    """The verified read layer, faked. `raises` makes it raise the truncation SystemExit."""
    data = _adapter()
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda t: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: it["fieldValues"].get(f, ""))
    monkeypatch.setattr(cli, "closeout_pr_closing_refs", lambda t, pr, r=None: list(refs))
    if raises is not None:
        def _boom(*a, **k):
            raise SystemExit(raises)
        monkeypatch.setattr(cli, "goal_tracker_items", _boom)
    else:
        monkeypatch.setattr(cli, "goal_tracker_items", lambda d, t, **k: list(items or []))
    return data


# --- 1. drift blocks, and the refusal carries the exact command that fixes it -------------------


def test_a_closing_ref_not_done_blocks_and_embeds_the_continuation(cli, tmp_path, monkeypatch):
    """The refusal has to carry the command, not describe it. A gate that says "move it to done"
    without the invocation is the dead end this program keeps closing."""
    data = _wire(cli, monkeypatch, items=[_item(101, ACTIVE)])

    issues = cli.provider_closeout_issues(data, tmp_path, PR)

    assert len(issues) == 1, issues
    assert "101" in issues[0]
    assert f"--status {DONE}" in issues[0] or f'--status "{DONE}"' in issues[0]
    assert "backlog-provider-update" in issues[0]


def test_every_closing_ref_done_is_no_issue(cli, tmp_path, monkeypatch):
    data = _wire(cli, monkeypatch, items=[_item(101, DONE)], refs=("101",))

    assert cli.provider_closeout_issues(data, tmp_path, PR) == []


def test_an_unreachable_provider_is_a_failure_not_a_pass(cli, tmp_path, monkeypatch):
    """D1, fail-closed. "I could not look" and "nothing is owed" must never share an exit code."""
    data = _wire(cli, monkeypatch, items=[])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: ["gh unreachable"])

    issues = cli.provider_closeout_issues(data, tmp_path, PR)

    assert issues and any("unreachable" in i or "unavailable" in i for i in issues), issues


# --- 2. the check CONSUMES the verified read; it does not re-implement one ----------------------


def test_a_truncated_board_read_is_a_blocking_closeout_error(cli, tmp_path, monkeypatch):
    """Packet §2. The read returns the complete set or raises; a truncation must surface as
    blocking, exactly the way `provider_board_currency_issues` surfaces it. Anything softer would
    report a clean closeout for items nobody looked at."""
    data = _wire(cli, monkeypatch, raises="GitHub Project board read truncated at 400 of 402 items")

    issues = cli.provider_closeout_issues(data, tmp_path, PR)

    assert issues, "a truncated read must block, never pass"
    assert any("402" in i for i in issues), "the error must carry the underlying reason"


def test_the_check_never_reintroduces_a_truncation_guard(cli):
    """`limit` is a first-page-size hint. `limit=400` was REMOVED at 0.46.0 because it was being
    read as a completeness guarantee; re-adding it here would ship two board-read truth models in
    one codebase. Nothing may branch on `len(items)` for completeness either."""
    import inspect

    source = inspect.getsource(cli.provider_closeout_issues)

    assert "limit=400" not in source
    assert "len(items)" not in source, "completeness is the read layer's contract, not a count"


# --- 3. the pending record: pure lane state, no network ----------------------------------------


def test_the_pending_record_round_trips_without_a_network(cli, tmp_path):
    """D3. Written, read and cleared with no provider call at all -- the lane-local half must work
    on a plane."""
    data = _adapter()
    cli.write_pending_closeout(data, tmp_path, PR, ["101", "102"])

    record = cli.read_pending_closeout(data, tmp_path)
    assert record["pr"] == PR
    assert record["refs"] == ["101", "102"]
    assert record["schema"] == "pending-closeout/v1"

    cli.clear_pending_closeout(data, tmp_path)
    assert cli.read_pending_closeout(data, tmp_path) is None


def test_the_pending_record_lives_beside_the_goal_run(cli, tmp_path):
    """Resolved through `laneState`, like every other lane artifact -- not hardcoded, so a lane
    that relocates its state directory keeps one convention."""
    data = _adapter()
    cli.write_pending_closeout(data, tmp_path, PR, ["101"])

    assert (tmp_path / ".ai-work" / "PENDING_CLOSEOUT.json").is_file()


# --- 4. the boundary predicate: blocks only on a VERIFIED unreconciled merge --------------------


def _boundary(cli, monkeypatch, tmp_path, *, merged, closeout_issues, closed_unmerged=False):
    data = _adapter()
    cli.write_pending_closeout(data, tmp_path, PR, ["101"])
    monkeypatch.setattr(
        cli, "closeout_pr_merge_state", lambda t, pr, r=None: ("closed" if closed_unmerged else ("merged" if merged else "open"))
        if merged is not None else None,
    )
    monkeypatch.setattr(
        cli, "provider_closeout_issues", lambda d, t, pr, r=None: list(closeout_issues)
    )
    return data


def test_a_verified_merged_and_unreconciled_pr_blocks(cli, tmp_path, monkeypatch):
    data = _boundary(
        cli, monkeypatch, tmp_path, merged=True, closeout_issues=["issue 101 is not Done"]
    )

    errors = cli.pending_closeout_errors(data, tmp_path)

    assert errors and str(PR) in errors[0]
    assert "backlog-provider-closeout-check" in " ".join(errors)


def test_an_unmerged_pr_does_not_block(cli, tmp_path, monkeypatch):
    """Nothing is owed until the merge lands. Blocking earlier would make every open PR a wall."""
    data = _boundary(
        cli, monkeypatch, tmp_path, merged=False, closeout_issues=["issue 101 is not Done"]
    )

    assert cli.pending_closeout_errors(data, tmp_path) == []


def test_a_reconciled_board_clears_the_record(cli, tmp_path, monkeypatch):
    data = _boundary(cli, monkeypatch, tmp_path, merged=True, closeout_issues=[])

    assert cli.pending_closeout_errors(data, tmp_path) == []
    assert cli.read_pending_closeout(data, tmp_path) is None, "a passing check clears the record"


def test_a_pr_closed_without_merging_clears_the_record(cli, tmp_path, monkeypatch, capsys):
    """D5. An abandoned PR owes nothing, and leaving its record behind would wedge the lane on
    work that will never land."""
    data = _boundary(
        cli, monkeypatch, tmp_path, merged=True, closeout_issues=["x"], closed_unmerged=True
    )

    assert cli.pending_closeout_errors(data, tmp_path) == []
    assert cli.read_pending_closeout(data, tmp_path) is None
    assert "pending_closeout_cleared:" in capsys.readouterr().out


def test_an_unreachable_provider_warns_and_does_not_block(cli, tmp_path, monkeypatch, capsys):
    """D3, the deliberate asymmetry. The explicit verb stays fail-closed; this passive boundary
    fails OPEN, because a GitHub outage must not wedge every push on every lane over a fact only
    GitHub holds. It must never fail SILENTLY -- the closeout is still owed."""
    data = _adapter()
    cli.write_pending_closeout(data, tmp_path, PR, ["101"])
    monkeypatch.setattr(cli, "closeout_pr_merge_state", lambda t, pr, r=None: None)

    errors = cli.pending_closeout_errors(data, tmp_path)

    assert errors == [], "an outage must not block"
    err = capsys.readouterr().err
    assert "pending_closeout_warn:" in err
    assert str(PR) in err and "still owed" in err
    assert cli.read_pending_closeout(data, tmp_path) is not None, "the record survives an outage"


# --- 5. no board write, anywhere ---------------------------------------------------------------


def test_the_closeout_path_never_writes_to_the_board(cli, tmp_path, monkeypatch):
    """Board-write authority belongs to the sanctioned update commands. This surface ASSERTS and
    PRINTS; a gate that fixes what it finds cannot be trusted to report honestly about it."""
    commands = []
    data = _wire(cli, monkeypatch, items=[_item(101, ACTIVE)])
    monkeypatch.setattr(
        cli, "run_command", lambda cmd, *a, **k: commands.append(cmd) or (0, "", "")
    )
    monkeypatch.setattr(
        cli, "command_json", lambda cmd, *a, **k: commands.append(cmd) or (0, [], "")
    )

    cli.provider_closeout_issues(data, tmp_path, PR)

    for cmd in commands:
        joined = " ".join(str(c) for c in cmd)
        assert "item-edit" not in joined and "--field-id" not in joined, joined
        assert "backlog-provider-update" not in joined, joined


# --- 6. the allowRepoOnlyGoals exemption (G2 PRESENT branch) -----------------------------------


def test_a_repo_only_lane_with_no_closing_refs_passes(cli, tmp_path, monkeypatch):
    """G2 present-branch. `allowRepoOnlyGoals` shipped in 0.64.0 and is the sanctioned no-board-item
    path; a closeout gate that refused it would invent a parallel bypass around a knob that already
    exists, which is exactly what item 71's successor interface forbids."""
    data = _wire(cli, monkeypatch, items=[], refs=())
    data["goalTracker"]["allowRepoOnlyGoals"] = True

    assert cli.provider_closeout_issues(data, tmp_path, PR) == []


def test_a_lane_without_the_knob_and_no_closing_refs_still_passes(cli, tmp_path, monkeypatch):
    """No refs is no obligation regardless of the knob -- there is nothing to reconcile. The knob
    matters for the WS2 missing-closing-ref check, not for having nothing to close."""
    data = _wire(cli, monkeypatch, items=[], refs=())

    assert cli.provider_closeout_issues(data, tmp_path, PR) == []


# --- 7. the merge verb: the closeout is owed, but the merge is never blocked on it --------------


def _merge_wire(cli, monkeypatch, tmp_path, *, state, issues):
    data = _adapter()
    monkeypatch.setattr(cli, "closeout_pr_merge_state", lambda t, pr, r=None: state)
    monkeypatch.setattr(cli, "closeout_pr_closing_refs", lambda t, pr, r=None: ["101"])
    monkeypatch.setattr(cli, "provider_closeout_issues", lambda d, t, pr, r=None: list(issues))
    return data


def test_a_synchronous_merge_with_an_unreconciled_board_exits_non_zero(
    cli, tmp_path, monkeypatch, capsys
):
    """D2. The merge SUCCEEDED -- the non-zero exit is the owed board write, not a failed merge,
    and the marker says which. Swallowing it would recreate the RCA: merged, unreconciled, and
    nothing left to notice."""
    data = _merge_wire(cli, monkeypatch, tmp_path, state="merged", issues=["issue 101 is not Done"])

    rc = cli.merge_command_closeout(data, tmp_path, "4242", 0)

    err = capsys.readouterr().err
    assert rc == 1
    assert "merge_closeout_pending:" in err and "4242" in err
    assert "backlog-provider-closeout-check --pr 4242" in err
    assert cli.read_pending_closeout(data, tmp_path) is not None, "the boundary needs the record"


def test_a_synchronous_merge_with_a_clean_board_returns_gh_s_own_code(cli, tmp_path, monkeypatch):
    data = _merge_wire(cli, monkeypatch, tmp_path, state="merged", issues=[])
    cli.write_pending_closeout(data, tmp_path, 4242, ["101"])

    assert cli.merge_command_closeout(data, tmp_path, "4242", 0) == 0
    assert cli.read_pending_closeout(data, tmp_path) is None, "a reconciled board clears the record"


def test_a_queued_merge_records_the_debt_without_failing_the_queue(
    cli, tmp_path, monkeypatch, capsys
):
    """A queued auto-merge has nothing to check yet. Failing it would punish the lane for using the
    merge queue, which is the sanctioned path."""
    data = _merge_wire(cli, monkeypatch, tmp_path, state="open", issues=["would fail if checked"])

    rc = cli.merge_command_closeout(data, tmp_path, "4242", 0)

    assert rc == 0, "a successfully queued merge must not be failed"
    assert "merge_closeout_pending:" in capsys.readouterr().out
    record = cli.read_pending_closeout(data, tmp_path)
    assert record is not None and record["pr"] == 4242


def test_an_unresolvable_pr_records_nothing(cli, tmp_path, monkeypatch):
    """None means "do not record", never "nothing owed". A record keyed on a PR nobody can resolve
    would block a boundary with no way to clear it -- worse than the gap it covers."""
    data = _adapter()
    monkeypatch.setattr(cli, "closeout_pr_number", lambda t, ref, r=None: None)

    assert cli.merge_command_closeout(data, tmp_path, "", 0) == 0
    assert cli.read_pending_closeout(data, tmp_path) is None


def test_the_merge_itself_is_never_blocked_on_board_state(cli):
    """Structural: the closeout runs only AFTER a zero-return merge. A board check that could
    refuse the merge would be a different, worse control -- board state is not a merge criterion."""
    import inspect

    source = inspect.getsource(cli.merge_command)
    merge_at = source.index("completed = subprocess.run(gh_args")
    closeout_at = source.index("merge_command_closeout(")

    assert merge_at < closeout_at, "the closeout must run after the merge, never before"
    assert "if completed.returncode == 0:" in source[merge_at:closeout_at]


def test_a_branch_ref_with_digits_is_resolved_not_scraped(cli, tmp_path, monkeypatch) -> None:
    """`gh pr merge` accepts a branch name, and a branch name with digits in it is ordinary.
    Codex R1 P2: scraping the last digit run turned `feature/item-79-ws1` into PR 1 -- recording a
    debt against a PR this lane never merged while the real one went unrecorded."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    seen = []

    def fake_json(cmd, target, timeout=None):
        seen.append(cmd)
        return 0, {"number": 533}, ""

    monkeypatch.setattr(cli, "command_json", fake_json)

    assert cli.closeout_pr_number(tmp_path, "feature/item-79-ws1") == 533
    assert any("feature/item-79-ws1" in " ".join(c) for c in seen), "gh must be asked, not guessed"


def test_a_bare_number_needs_no_round_trip(cli, tmp_path, monkeypatch) -> None:
    """A ref that is entirely digits is a PR number and nothing else."""
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: pytest.fail("no gh call expected"))

    assert cli.closeout_pr_number(tmp_path, "533") == 533


def test_unreadable_closing_refs_are_not_an_empty_ref_list(cli, tmp_path, monkeypatch) -> None:
    """Codex R1 P2: returning [] on a transient auth/network failure made "I could not look"
    identical to "this PR closes nothing" -- so a merged PR with real board drift passed the
    fail-closed check and cleared its own pending record on the way through."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: (1, None, "auth failed"))

    assert cli.closeout_pr_closing_refs(tmp_path, 533) is None, "unreadable is a third answer"

    monkeypatch.setattr(cli, "goal_tracker_items", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda t: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    issues = cli.provider_closeout_issues(_adapter(), tmp_path, 533)
    assert issues, "the fail-closed verb must block when it could not look"
    assert any("could not be read" in i for i in issues)


def test_a_check_for_one_pr_does_not_clear_another_prs_debt(cli, tmp_path, monkeypatch) -> None:
    """Codex R1 P2: an unconditional clear meant a successful check for PR B deleted PR A's
    pending record, leaving the still-unreconciled merge with nothing to enforce it."""
    data = {}
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, tmp_path))
    monkeypatch.setattr(cli, "provider_closeout_issues", lambda d, t, pr, r=None: [])
    monkeypatch.setattr(cli, "read_pending_closeout", lambda d, t: {"pr": 100})
    cleared = []
    monkeypatch.setattr(cli, "clear_pending_closeout", lambda d, t: cleared.append(True))

    rc = cli.backlog_provider_closeout_check(argparse.Namespace(pr=200))

    assert rc == 0, "PR 200 really is reconciled"
    assert not cleared, "PR 100's debt is still owed and must survive"


def test_the_passive_boundary_warns_where_the_verb_refuses(cli, tmp_path, monkeypatch) -> None:
    """D3, and Codex R2 P2. The two boundaries answer an unreadable board differently ON PURPOSE:
    the explicit verb refuses to certify what it could not see, while this passive predicate runs
    at every status and prepush and must not wedge every push on every lane through a GitHub
    outage. My R1 fail-closed fix broke that asymmetry -- this pins it back."""
    data = _adapter()
    monkeypatch.setattr(cli, "read_pending_closeout", lambda d, t: {"pr": 533})
    monkeypatch.setattr(cli, "closeout_pr_merge_state", lambda t, pr, r=None: "merged")
    monkeypatch.setattr(
        cli, "provider_closeout_issues",
        lambda d, t, pr, r=None: ["PR 533's closing references could not be read, so whether ..."],
    )
    cleared = []
    monkeypatch.setattr(cli, "clear_pending_closeout", lambda d, t: cleared.append(True))

    errors = cli.pending_closeout_errors(data, tmp_path)

    assert errors, "never silent -- the debt is still owed"
    assert any("advisory" in e for e in errors), "unverifiable warns, it does not block"
    assert not cleared, "an unverifiable read must NOT clear the debt"


def test_a_verified_not_done_board_still_blocks_the_passive_boundary(cli, tmp_path, monkeypatch):
    """The fail-open above is only for what could not be READ. A board that was read, and says the
    item is not done, still blocks -- otherwise the record would be decorative."""
    data = _adapter()
    monkeypatch.setattr(cli, "read_pending_closeout", lambda d, t: {"pr": 533})
    monkeypatch.setattr(cli, "closeout_pr_merge_state", lambda t, pr, r=None: "merged")
    monkeypatch.setattr(
        cli, "provider_closeout_issues", lambda d, t, pr, r=None: ["issue 101 is not Done"]
    )

    errors = cli.pending_closeout_errors(data, tmp_path)

    assert errors and not any("advisory" in e for e in errors), "a read board blocks"


def test_a_cross_repo_issue_does_not_collide_with_a_local_one(cli) -> None:
    """Codex R2 P2: issue 123 exists in every repository that has 123 issues. Collapsing a
    cross-repo `owner/repo#123` to "123" let a board card from a DIFFERENT repo satisfy this
    closeout while the real referenced issue stayed unreconciled."""
    ref = {"number": 123, "url": "https://github.com/other/repo/issues/123"}

    assert cli.closeout_ref_repo(ref) == "other/repo"
    assert cli.closeout_repo_from_url("https://github.com/a/b/issues/9") == "a/b"
    assert cli.closeout_repo_from_url("not a url") is None

    nested = {"number": 5, "repository": {"owner": {"login": "acme"}, "name": "widgets"}}
    assert cli.closeout_ref_repo(nested) == "acme/widgets"


def test_the_refs_reader_emits_repo_qualified_keys(cli, tmp_path, monkeypatch) -> None:
    """Proves the KEYING IS WIRED IN, not merely that the helper exists: an earlier version of
    this test only exercised `closeout_ref_repo` directly and passed against a mutant that keyed
    by bare number in the reader."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        cli, "command_json",
        lambda *a, **k: (0, {"closingIssuesReferences": [
            {"number": 123, "url": "https://github.com/other/repo/issues/123"},
        ]}, ""),
    )

    assert cli.closeout_pr_closing_refs(tmp_path, 533) == ["other/repo#123"]


def test_the_closeout_threads_its_repo_into_every_provider_read(cli, tmp_path, monkeypatch):
    """Proves the repo is THREADED, not merely parseable: an earlier version of this test only
    exercised `merge_repo_argument` and passed against a mutant that dropped the value. Every gh
    read inside the closeout must be pointed at the repo the merge targeted, or the debt is
    recorded against whatever PR happens to share that number in the local checkout."""
    seen = []
    monkeypatch.setattr(
        cli, "closeout_pr_number", lambda t, ref, r=None: seen.append(("number", r)) or 12
    )
    monkeypatch.setattr(
        cli, "closeout_pr_merge_state",
        lambda t, pr, r=None: seen.append(("state", r)) or "merged",
    )
    monkeypatch.setattr(
        cli, "provider_closeout_issues",
        lambda d, t, pr, r=None: seen.append(("issues", r)) or [],
    )
    monkeypatch.setattr(cli, "clear_pending_closeout", lambda d, t: None)

    cli.merge_command_closeout(_adapter(), tmp_path, "12", 0, repo="other/repo")

    assert seen, "the closeout must actually run"
    assert all(r == "other/repo" for _name, r in seen), f"repo dropped somewhere: {seen}"


def test_the_repo_travels_with_the_debt(cli, tmp_path, monkeypatch) -> None:
    """Codex R3 P2. A queued or cross-repo merge is settled by a LATER boundary that has no
    `--repo` to be given -- which is precisely why the merge must write the repo down. Without it
    the record's PR number is resolved against whatever PR shares that number locally."""
    monkeypatch.setattr(cli, "pending_closeout_path", lambda d, t: tmp_path / "PENDING.json")

    cli.write_pending_closeout(_adapter(), tmp_path, 12, ["other/repo#5"], "other/repo")

    record = json.loads((tmp_path / "PENDING.json").read_text())
    assert record["repo"] == "other/repo", "the repo is part of the debt, not of the invocation"
    assert record["pr"] == 12


def test_the_boundary_reads_the_repo_it_recorded(cli, tmp_path, monkeypatch) -> None:
    """The persisted repo must reach the provider reads, or persisting it changed nothing."""
    seen = []
    monkeypatch.setattr(cli, "read_pending_closeout", lambda d, t: {"pr": 12, "repo": "other/repo"})
    monkeypatch.setattr(
        cli, "closeout_pr_merge_state", lambda t, pr, r=None: seen.append(r) or "merged"
    )
    monkeypatch.setattr(
        cli, "provider_closeout_issues", lambda d, t, pr, r=None: seen.append(r) or []
    )
    monkeypatch.setattr(cli, "clear_pending_closeout", lambda d, t: None)

    cli.pending_closeout_errors(_adapter(), tmp_path)

    assert seen and all(r == "other/repo" for r in seen), f"repo dropped: {seen}"


def test_a_bare_number_matches_only_when_it_is_unambiguous(cli, tmp_path, monkeypatch) -> None:
    """Codex R3 P2: indexing every board item under its bare number let `other/repo#123` match
    `local/repo#123`, recreating the collision the qualified key exists to prevent. A bare number
    is an answer only while exactly one item carries it."""
    def _item(repo, number, status):
        return {
            "content": {"number": number, "url": f"https://github.com/{repo}/issues/{number}"},
            "fieldValues": {"Status": status},
        }

    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda t: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: it["fieldValues"].get(f, ""))
    # The referenced repo is on NEITHER board item, so the qualified key cannot match and the
    # bare fallback is what runs -- which is the code path the collision lives in.
    monkeypatch.setattr(cli, "closeout_pr_closing_refs", lambda t, pr, r=None: ["absent/repo#123"])
    monkeypatch.setattr(
        cli, "goal_tracker_items",
        lambda d, t: [_item("local/repo", 123, "Done"), _item("other/repo", 123, "Done")],
    )

    issues = cli.provider_closeout_issues(_adapter(), tmp_path, 99)

    assert issues, "two repos carry 123, so a bare match is a guess -- it must refuse, not pass"
    assert "not on the board" in issues[0]


def test_the_guard_boundary_blocks_on_verified_drift_and_not_on_an_outage(cli, tmp_path, monkeypatch):
    """Codex R3 P2: `pending_closeout_errors` already decided which messages are advisory, and the
    guard re-decided by "is the list non-empty" -- throwing that away and blocking every push
    through a GitHub outage anyway. One predicate, both readers."""
    monkeypatch.setattr(
        cli, "pending_closeout_errors",
        lambda d, t: ["PR 12 merged ... the board could not be read (advisory ...)"],
    )
    assert cli.guard_check_closeout_rc(_adapter(), tmp_path) == 0, "an outage must not wedge push"

    monkeypatch.setattr(cli, "pending_closeout_errors", lambda d, t: ["issue 101 is not Done"])
    assert cli.guard_check_closeout_rc(_adapter(), tmp_path) == 1, "verified drift still blocks"


def test_the_current_branch_lookup_also_honours_the_repo(cli, tmp_path, monkeypatch) -> None:
    """Codex R4 P2: `tautline merge --repo owner/repo` with no positional ref merges the CURRENT
    BRANCH over there, so resolving that branch's PR without --repo asked the local checkout --
    recording debt against the wrong PR, or skipping the owed cross-repo closeout entirely."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    seen = []

    def fake_json(cmd, target, timeout=None):
        seen.append(cmd)
        return 0, {"number": 12}, ""

    monkeypatch.setattr(cli, "command_json", fake_json)

    assert cli.closeout_pr_number(tmp_path, "", "other/repo") == 12
    assert seen and "--repo" in seen[0] and "other/repo" in seen[0], f"repo dropped: {seen}"
