"""Batch 2026-08-11 item B5, Release A: a done-evidence comment goes to the ITEM's repo.

QUEUE item 95, routed out of item 81 WS1 as an out-of-AC P2. `stakeholder_issue_post_comment`
addressed `data["repo"]` -- the LANE's repository -- while the closure gate had already learned to
read the item's acceptance criteria from the ITEM's repository. So one command read from one repo
and wrote to another, and for a board item backed by `github.com/other/repo/issues/5` the
verification claim landed on issue #5 of the lane's own repo: a real issue, belonging to someone
else, carrying a claim about work it has nothing to do with.

**Every assertion here is on argv.** The defect is invisible in return values -- posting to the
wrong repository succeeds exactly as cleanly as posting to the right one, which is why it survived
unnoticed through the read side being fixed. A test that checked a return value or an exit code
would have passed against the defect.

Release A is the addressing fix plus every refusal that is decidable LOCALLY: it parses a URL, or
it refuses. Nothing here probes a remote for write permission. Whether a correctly addressed
repository will ACCEPT the write is the successor plan's subject
(`2026-08-11-cross-repo-evidence-foreign-repo-failure-mode.md`), because no read-only check can
answer it -- `repos.permissions.push` is neither necessary for commenting on a public repo nor
sufficient for a fine-grained token lacking `Issues: write`.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

LANE_REPO = "example-org/example-saas"
FOREIGN_REPO = "other-org/their-service"


def _item(*, number: int = 7, repo: str | None = LANE_REPO, url: str | None = None) -> dict:
    """A Project item. `url=` overrides the content URL outright, for unparseable-URL cases."""
    if url is None:
        url = f"https://github.com/{repo}/issues/{number}" if repo else ""
    content: dict = {"url": url}
    return {
        "id": f"ITEM{number}",
        "content": content,
        "url": "https://github.com/orgs/example-org/projects/1?pane=item",
    }


def _project(cli, *, ac_table: str = "off") -> dict:
    """`acTable` defaults to `off` here: item 81's oracle check is a separate control with its own
    tests, and leaving it on would make these argv assertions depend on its issue-body fetches."""
    data = cli.load_project(EXAMPLE_ADAPTER)
    data["backlogProvider"]["doneEvidence"] = {"acTable": ac_table}
    return data


def _harness(
    cli, monkeypatch, *, item: dict, subtasks: list[dict] | None = None, body: str = ""
) -> list[list[str]]:
    """Record every `gh` argv the done move issues.

    Board READS are stubbed at their own helpers so the real mutations -- `gh project item-edit`
    and the comment POST -- still travel through `run_command` and land in the recorded list.
    Stubbing the mutation itself would assert against the test double rather than the code.
    """
    calls: list[list[str]] = []

    def _run(command, cwd=None, timeout=None, **kwargs):
        calls.append(list(command))
        if command[:1] == ["gh"] and command[1:3] in (["issue", "view"], ["pr", "view"]):
            return 0, body, ""
        if command[:2] == ["gh", "api"]:
            return 0, json.dumps({"html_url": "https://github.com/x/y/issues/1#c1"}), ""
        return 0, "{}", ""

    monkeypatch.setattr(cli, "run_command", _run)
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda *a, **k: [])
    monkeypatch.setattr(
        cli,
        "goal_tracker_project_fields",
        lambda *a, **k: [
            {"name": "Status", "id": "FIELD1", "options": [{"name": "Done", "id": "OPT1"}]}
        ],
    )
    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda *a, **k: {"id": "PROJ1"})
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda *a, **k: item)
    monkeypatch.setattr(
        cli, "goal_tracker_board_backed_subtasks", lambda *a, **k: list(subtasks or [])
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda *a, **k: "CLOSED")
    monkeypatch.setattr(cli, "github_cache_invalidate_project", lambda *a, **k: None)
    return calls


def _comment_calls(calls: list[list[str]]) -> list[list[str]]:
    """Every argv that POSTS a comment, by either route the code can take."""
    return [
        call
        for call in calls
        if (call[:2] == ["gh", "api"] and "--method" in call and "POST" in call)
        or call[:3] == ["gh", "issue", "comment"]
    ]


def _mutations(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[:3] == ["gh", "project", "item-edit"]] + _comment_calls(
        calls
    )


def _comment_repo(call: list[str]) -> str:
    """The repo a comment argv addresses, for either route."""
    if "--repo" in call:
        return call[call.index("--repo") + 1]
    for part in call:
        if part.startswith("repos/") and "/issues/" in part:
            return part.split("/issues/")[0][len("repos/") :]
    return ""


def _done_move(
    cli, data, target, item_ref: str = "ITEM7", evidence: str = "Verified: all criteria met."
):
    return cli.goal_tracker_update_status_with_done_evidence(
        data, target, item_ref, "Done", evidence=evidence, context="goal-tracker-update"
    )


# --- Acceptance criterion 1: the item's repo, not the lane's -------------------------------------


def test_cross_repo_item_evidence_comment_argv_names_the_item_repo(
    cli, monkeypatch, tmp_path
) -> None:
    """THE regression test QUEUE item 95 names. Before the fix this argv said `example-org/...`."""
    data = _project(cli)
    item = _item(number=5, repo=FOREIGN_REPO)
    calls = _harness(cli, monkeypatch, item=item)

    _done_move(cli, data, tmp_path)

    comments = _comment_calls(calls)
    assert comments, "the done move posted no evidence comment at all"
    assert _comment_repo(comments[0]) == FOREIGN_REPO
    assert LANE_REPO not in " ".join(comments[0]), (
        "the evidence comment argv still mentions the lane repo; the item's repo is the only "
        "correct target and the lane's must not appear on this call"
    )


def test_the_repo_and_the_number_come_from_the_same_url(cli, monkeypatch, tmp_path) -> None:
    """Codex R1 P1. Resolving them separately recreates the wrong-issue write.

    An item can expose several URL candidates. If an earlier one yields a NUMBER but no repository
    -- an enterprise URL ending `/issues/5` -- and a later one is a valid
    `correct/repo/issues/6`, then taking the number from the first and the repo from the second
    posts to `correct/repo#5`: a real issue in the right repository that has nothing to do with
    this item. Same defect class as the one this whole release exists to remove, reached by a
    different route, so both values must come from one resolver result.
    """
    data = _project(cli)
    item = {
        "id": "ITEM6",
        "content": {"url": "https://ghe.example.com/other/repo/issues/5"},
        "contentUrl": "https://github.com/correct/repo/issues/6",
        "url": "https://github.com/orgs/example-org/projects/1?pane=item",
    }
    calls = _harness(cli, monkeypatch, item=item)

    _done_move(cli, data, tmp_path)

    comments = _comment_calls(calls)
    assert comments, "the done move posted no evidence comment at all"
    argv = " ".join(comments[0])
    assert _comment_repo(comments[0]) == "correct/repo"
    assert "/issues/6" in argv or "6" in comments[0], (
        f"the comment used the number from a DIFFERENT url than the repo: {comments[0]}"
    )
    assert "/issues/5" not in argv, (
        f"posted to issue 5, which came from the unparseable enterprise url: {comments[0]}"
    )


# --- Acceptance criterion 2: a same-repo item is unchanged ---------------------------------------


def test_same_repo_item_is_unchanged(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli)
    calls = _harness(cli, monkeypatch, item=_item(number=7, repo=LANE_REPO))

    _done_move(cli, data, tmp_path)

    comments = _comment_calls(calls)
    assert comments, "the done move posted no evidence comment at all"
    assert _comment_repo(comments[0]) == LANE_REPO


def test_same_repo_done_move_performs_no_extra_network_call(cli, monkeypatch, tmp_path) -> None:
    """The new pre-flight is pure URL parsing, so it costs an existing single-repo adopter nothing.

    This is the test that fails if anyone "improves" the pre-flight into a write-permission probe:
    that was the superseded plan's mechanism, and it cannot make the guarantee it advertises.
    """
    data = _project(cli)
    calls = _harness(cli, monkeypatch, item=_item(number=7, repo=LANE_REPO))
    _done_move(cli, data, tmp_path)
    baseline = len(calls)

    calls.clear()
    cli.goal_tracker_preflight_done_evidence_targets(
        data, tmp_path, _item(number=7, repo=LANE_REPO), "ITEM7", "ctx", subtasks=[_item(number=8)]
    )
    assert calls == [], f"the target pre-flight issued network calls: {calls}"
    assert baseline > 0, "the harness recorded nothing at all; it is not exercising the real path"


# --- Acceptance criterion 3: one resolver serves both sides --------------------------------------


def test_read_and_write_sides_resolve_the_same_repo_for_one_item(cli) -> None:
    """The test that would have caught the original defect, and the one worth writing first."""
    item = _item(number=5, repo=FOREIGN_REPO)

    _, write_repo, write_number = cli.board_item_repo_and_issue_number(item)

    read_source = inspect.getsource(cli.goal_tracker_item_issue_body)
    assert "board_item_repo_and_issue_number" in read_source, (
        "the READ side no longer routes through the shared resolver, so the two sides can diverge "
        "again exactly as they did before"
    )
    assert write_repo == FOREIGN_REPO
    assert write_number == "5"


def test_one_shared_resolver_serves_the_read_and_write_sides(cli) -> None:
    """Structural, not coincidental: neither side may carry its own copy of the parse."""
    for name in ("goal_tracker_item_issue_body", "goal_tracker_done_evidence_target"):
        source = inspect.getsource(getattr(cli, name))
        assert "board_item_repo_and_issue_number" in source, (
            f"{name} does not use the shared resolver"
        )
        assert "github_repo_from_issue_url" not in source, (
            f"{name} parses the repo itself rather than using the shared resolver -- a second "
            "parser is how the read and write sides diverged in the first place"
        )


# --- Acceptance criterion 4: the repo parameter is required --------------------------------------


def test_post_comment_requires_an_explicit_repo(cli) -> None:
    signature = inspect.signature(cli.stakeholder_issue_post_comment)
    repo = signature.parameters.get("repo")
    assert repo is not None, "stakeholder_issue_post_comment takes no repo parameter"
    assert repo.kind is inspect.Parameter.KEYWORD_ONLY, (
        "repo must be keyword-only so it is never positional by accident"
    )
    assert repo.default is inspect.Parameter.empty, (
        "repo has a default; a default is the mechanism that produced this defect and would let "
        "the next caller re-introduce it silently"
    )
    with pytest.raises(TypeError):
        cli.stakeholder_issue_post_comment({}, Path("."), "1", "body")


def test_post_comment_argv_names_the_repo_it_was_given(cli, monkeypatch, tmp_path) -> None:
    data = _project(cli)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli,
        "run_command",
        lambda command, cwd=None, timeout=None, **k: (
            calls.append(list(command)),
            (0, json.dumps({"html_url": "u"}), ""),
        )[1],
    )

    cli.stakeholder_issue_post_comment(
        data, tmp_path, "5", "body", repo=FOREIGN_REPO, ac_checked=True
    )

    posted = _comment_calls(calls)
    assert posted, "no comment was posted"
    assert _comment_repo(posted[0]) == FOREIGN_REPO


def test_post_comment_gh_fallback_argv_names_the_repo_it_was_given(
    cli, monkeypatch, tmp_path
) -> None:
    """The fallback repeats the repo, and it is the path taken exactly when REST fails.

    Converting only the REST call would have left the defect live on the failure path -- the one
    that runs when things are already going wrong.
    """
    data = _project(cli)
    calls: list[list[str]] = []

    def _fail_rest(*a, **k):
        raise SystemExit("rest unavailable")

    def _client_run(_op, args, _target, **k):
        calls.append(list(args))
        return 0, "https://github.com/x/y/issues/5#c1", ""

    monkeypatch.setattr(cli, "github_issue_comment_rest", _fail_rest)
    monkeypatch.setattr(cli, "github_provider_client_run", _client_run)

    cli.stakeholder_issue_post_comment(
        data, tmp_path, "5", "body", repo=FOREIGN_REPO, ac_checked=True
    )

    assert calls, "the fallback path issued no call"
    assert calls[0][calls[0].index("--repo") + 1] == FOREIGN_REPO


# --- Acceptance criterion 5: the oracle check follows the comment --------------------------------


def test_verification_claim_check_reads_the_same_repo_as_the_comment_target(
    cli, monkeypatch, tmp_path
) -> None:
    """A verification check that validated against the WRONG issue would be worse than none."""
    data = _project(cli, ac_table="warn")
    read: list[str] = []

    def _issue_body(_data, _target, item):
        read.append(cli.github_repo_from_issue_url(item["content"]["url"]))
        return "## Acceptance Criteria\n\n- something\n", ""

    monkeypatch.setattr(cli, "goal_tracker_item_issue_body", _issue_body)
    monkeypatch.setattr(cli, "evidence_claims_verification", lambda _body: True)
    monkeypatch.setattr(cli, "done_evidence_ac_table_issues", lambda *a, **k: [])

    cli.stakeholder_issue_verification_claim_issues(
        data, tmp_path, "5", "Verified: done.", repo=FOREIGN_REPO
    )

    assert read == [FOREIGN_REPO], (
        f"the oracle check read {read}, not the repo the comment is about to be posted to"
    )


# --- Acceptance criterion 6: an unparseable repo refuses, and posts nothing -----------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://ghe.example.com/other/repo/issues/5",
        "https://api.github.com/repos/other/repo/issues/5",
    ],
    ids=["enterprise-host", "api-shaped"],
)
def test_unparseable_repo_url_refuses_and_attempts_no_comment(
    cli, monkeypatch, tmp_path, url: str
) -> None:
    """The ONLY input that reached the old lane-repo fallback, and the one where it was lethal.

    An item with no linked URL has no issue NUMBER either, so the funnel refuses it one line
    earlier and never reaches the fallback. What reaches it is a URL that yields a number while its
    repo will not parse -- and there the lane's repo is a guess that posts a third party's claim
    onto the lane's own same-numbered issue.
    """
    data = _project(cli)
    item = _item(url=url)
    calls = _harness(cli, monkeypatch, item=item)

    with pytest.raises(SystemExit) as excinfo:
        _done_move(cli, data, tmp_path)

    message = str(excinfo.value)
    assert "cannot determine which repository" in message
    assert url in message, "the refusal does not name the URL that could not be parsed"
    assert _comment_calls(calls) == [], "a comment was attempted despite the unresolvable target"
    assert _mutations(calls) == [], "the refusal mutated something before refusing"


# --- Acceptance criteria 7 and 8: the refusal precedes every mutation ----------------------------


def test_unresolvable_target_refuses_before_any_subtask_mutation(
    cli, monkeypatch, tmp_path
) -> None:
    data = _project(cli)
    parent = _item(url="https://ghe.example.com/other/repo/issues/5")
    calls = _harness(cli, monkeypatch, item=parent, subtasks=[_item(number=8), _item(number=9)])

    with pytest.raises(SystemExit):
        _done_move(cli, data, tmp_path)

    assert _mutations(calls) == [], (
        "subtasks were mutated before the parent's unresolvable target was refused -- a partial "
        "completion behind a refusal, which is the one thing the pre-flight seam exists to prevent"
    )


def test_unresolvable_subtask_target_refuses_before_the_parent_comment(
    cli, monkeypatch, tmp_path
) -> None:
    """A resolvable parent with an unresolvable SUBTASK still mutates nothing.

    Subtask comments route through the same `goal_tracker_post_done_evidence`, so each one now
    resolves to its own repo -- which is what makes a late failure in that loop newly reachable.
    """
    data = _project(cli)
    parent = _item(number=7, repo=LANE_REPO)
    bad_subtask = _item(url="https://ghe.example.com/other/repo/issues/9")
    calls = _harness(cli, monkeypatch, item=parent, subtasks=[_item(number=8), bad_subtask])

    with pytest.raises(SystemExit) as excinfo:
        _done_move(cli, data, tmp_path)

    assert "refused before any status edit" in str(excinfo.value)
    assert _mutations(calls) == [], (
        "an earlier subtask was already moved to Done before the refusal"
    )


def test_the_refusal_describes_its_actual_cause(cli) -> None:
    """Two causes reach this refusal, and it must not misdescribe either.

    The pre-flight reaches it for a subtask with NO linked URL at all, where "carries an issue
    number but no owner/name" is simply false. A refusal that misdescribes its own cause sends the
    operator to fix the wrong thing, which is worse than a vaguer one.
    """
    with pytest.raises(SystemExit) as unparseable:
        cli.goal_tracker_done_evidence_target(
            _item(url="https://ghe.example.com/o/r/issues/5"), "ctx"
        )
    assert "carries an issue number but no owner/name" in str(unparseable.value)

    with pytest.raises(SystemExit) as missing:
        cli.goal_tracker_done_evidence_target({"id": "ITEM1", "content": {}}, "ctx")
    text = str(missing.value)
    assert "no linked GitHub issue/PR URL" in text
    assert "carries an issue number" not in text


def test_an_already_done_subtask_is_not_preflighted(cli, monkeypatch, tmp_path) -> None:
    """The pre-flight must refuse only targets that will actually be WRITTEN.

    The mutation loop skips a subtask whose status already matches the target (`already_<status>`)
    or is already terminal (`skipped_terminal_status`) and posts it no comment. A pre-flight that
    resolved EVERY board-backed subtask would refuse the parent forever over a target nothing is
    going to write to -- turning a compatibility case into a permanent block. Plan-review P2.
    """
    data = _project(cli)
    parent = _item(number=7, repo=LANE_REPO)
    stale = _item(url="https://ghe.example.com/other/repo/issues/9")
    stale["fieldValues"] = {"nodes": [{"field": {"name": "Status"}, "name": "Done"}]}
    monkeypatch.setattr(
        cli, "goal_tracker_item_field", lambda item, _f: "Done" if item is stale else ""
    )
    calls = _harness(cli, monkeypatch, item=parent, subtasks=[stale])

    _done_move(cli, data, tmp_path)

    comments = _comment_calls(calls)
    assert comments, "the parent's own evidence comment never went out"
    assert all(_comment_repo(call) != "" for call in comments)
    assert not any("ghe.example.com" in " ".join(call) for call in comments)


def test_closure_preflight_refuses_before_any_ui_evidence_comment(cli) -> None:
    """`goal_advance` posts UI proof BEFORE the done funnel runs, so the funnel is too late a seam.

    `goal_advance_closure_preflight` runs ahead of `sync_goal_issue_ui_evidence`; the funnel's
    `goal_tracker_update_status_with_done_evidence` runs after it. A target check placed only in
    the funnel would let the UI comment publish and then refuse.
    """
    source = inspect.getsource(cli.goal_advance_closure_preflight)
    assert "goal_tracker_preflight_done_evidence_targets" in source, (
        "the target pre-flight is not reachable from the earliest seam, so goal-advance can post a "
        "UI-evidence comment before an unresolvable target is refused"
    )


# --- Acceptance criterion 9: the stakeholder-question paths --------------------------------------


def test_stakeholder_question_paths_address_the_lane_repo_by_construction(cli) -> None:
    """WS4's measurement, pinned. `--repo data["repo"]` on both reads is what makes it true."""
    for name in ("stakeholder_issue_view", "stakeholder_issue_list"):
        source = inspect.getsource(getattr(cli, name))
        assert 'data["repo"]' in source, f"{name} no longer reads the lane repo by construction"

    for name in ("stakeholder_question_status_for_issue", "stakeholder_question_ask"):
        source = inspect.getsource(getattr(cli, name))
        assert "stakeholder_issue_post_comment" in source
        assert 'repo=data["repo"]' in source, (
            f"{name} must state the lane repo explicitly; it is correct for this path only because "
            "the read side fetched from the lane repo, and that is now measured rather than assumed"
        )


def test_stakeholder_issue_view_refuses_a_foreign_repo_url(cli) -> None:
    data = _project(cli)
    with pytest.raises(SystemExit) as excinfo:
        cli.stakeholder_issue_ref_repo_issues(data, f"https://github.com/{FOREIGN_REPO}/issues/5")
    message = str(excinfo.value)
    assert FOREIGN_REPO in message and LANE_REPO in message, "the refusal must name both repos"


def test_stakeholder_issue_view_refuses_a_url_whose_repo_cannot_be_parsed(cli) -> None:
    """The case a repo-COMPARISON rule waves through.

    An enterprise URL parses to a number and an EMPTY repo, so "refuse when the parsed repo differs
    from the lane's" would accept it and comment on lane issue #5. The rule is keyed on the
    reference FORM instead: a bare number is the only repo-less reference accepted.
    """
    data = _project(cli)
    with pytest.raises(SystemExit) as excinfo:
        cli.stakeholder_issue_ref_repo_issues(data, "https://ghe.example.com/other/repo/issues/5")
    assert "cannot parse" in str(excinfo.value)


@pytest.mark.parametrize(
    "ref",
    [
        "5",
        f"https://github.com/{LANE_REPO}/issues/5",
        f"  https://github.com/{LANE_REPO}/issues/5  ",
    ],
    ids=["bare-number", "lane-url", "lane-url-padded"],
)
def test_stakeholder_issue_view_accepts_a_lane_repo_url_and_a_bare_number(cli, ref: str) -> None:
    """The ordinary inputs keep working; the refusal is narrow by construction."""
    cli.stakeholder_issue_ref_repo_issues(_project(cli), ref)


def test_this_release_is_not_declared_wip_safe(cli) -> None:
    """The release must not advertise a safety property it does not have.

    A cross-repo lane changes where its writes land and gains a newly reachable permission failure
    that Release B closes; a lane already in progress must not auto-adopt that on a patch update.
    This fails if anyone flips the flag before that residual is actually closed.
    """
    report = cli.release_migration_report_data(version="0.60.0")
    assert report["wipSafe"] is False
    joined = " ".join(report["behaviorChanges"] + report["rollbackNotes"])
    assert "Release B" in joined, "the residual is not named in the migration report"
    assert "WIP-safe" in joined


@pytest.mark.parametrize(
    "url",
    [
        "https://evilgithub.com/example-org/example-saas/issues/5",
        "https://notgithub.com/example-org/example-saas/issues/5",
        "https://github.com.attacker.test/example-org/example-saas/issues/5",
        # The host is `evil.example`; `github.com` is a PATH SEGMENT. This is the shape that
        # survived the first hardening attempt, because the character before `github.com` is `/`.
        "https://evil.example/github.com/example-org/example-saas/issues/5",
        "https://evil.example/x/github.com/example-org/example-saas/issues/5",
        # Userinfo, not a host: everything before `@` is credentials.
        "https://github.com@evil.example/example-org/example-saas/issues/5",
    ],
    ids=["evilgithub", "notgithub", "suffix-host", "embedded-path", "embedded-deep", "userinfo"],
)
def test_a_lookalike_host_does_not_resolve_to_a_repo(cli, url: str) -> None:
    """Plan-review R3 P1 and R4 P1. Substring matching was bypassed twice; now the host is parsed.

    `github_repo_from_issue_url` searched for `github.com/` anywhere in the string, so
    `evilgithub.com/lane/repo/issues/5` returned `lane/repo`. Adding a lookbehind for a preceding
    word character, dot or hyphen fixed that shape and still admitted
    `evil.example/github.com/lane/repo/issues/5`, where the preceding character is `/` and
    `github.com` is merely a path segment. Every control that decides "is this reference foreign?"
    from this function inherits such a hole as a bypass -- including this release's own `--issue`
    guard, which would have ACCEPTED these as the lane's own and commented on lane issue #5.

    The lesson, and the reason this is now `urlsplit(...).hostname` rather than a cleverer regex:
    a host check written as substring matching keeps having exactly one more bypass.
    """
    assert cli.github_repo_from_issue_url(url) == ""


def test_a_lookalike_host_is_refused_by_the_issue_guard(cli) -> None:
    """The bypass closed at the guard, not only at the parser."""
    with pytest.raises(SystemExit):
        cli.stakeholder_issue_ref_repo_issues(
            _project(cli), f"https://evilgithub.com/{LANE_REPO}/issues/5"
        )


@pytest.mark.parametrize(
    "url",
    [
        f"https://GitHub.com/{LANE_REPO}/issues/5",
        f"https://www.github.com/{LANE_REPO}/issues/5",
    ],
    ids=["host-casing", "www-host"],
)
def test_an_ordinary_lane_url_variant_still_resolves(cli, url: str) -> None:
    """Plan-review R3 P2. Hardening the host must not refuse a legitimate reference.

    `https://GitHub.com/...` is an ordinary thing to paste. A case-sensitive host match returned
    "" for it, which would make this release's guard refuse a same-repo reference that worked
    before -- a compatibility regression introduced by a security fix.
    """
    assert cli.github_repo_from_issue_url(url).lower() == LANE_REPO
    cli.stakeholder_issue_ref_repo_issues(_project(cli), url)


def test_stakeholder_issue_view_actually_applies_the_refusal(cli, monkeypatch, tmp_path) -> None:
    """The guard has to be WIRED IN, not merely defined.

    Every other test on this guard calls it directly, so all of them would still pass if the call
    inside `stakeholder_issue_view` were deleted -- a control that exists and is never invoked. This
    drives the real entry point and asserts the read never happens.
    """
    data = _project(cli)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli,
        "goal_tracker_gh_json",
        lambda command, target: (calls.append(list(command)), {"number": 5})[1],
    )

    with pytest.raises(SystemExit):
        cli.stakeholder_issue_view(data, tmp_path, f"https://github.com/{FOREIGN_REPO}/issues/5")
    assert calls == [], "the foreign issue was fetched before the refusal"

    cli.stakeholder_issue_view(data, tmp_path, "5")
    assert calls, "a bare number must still be read from the lane repo"
    assert calls[0][calls[0].index("--repo") + 1] == LANE_REPO
