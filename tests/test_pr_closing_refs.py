"""A PR body that binds no auto-close, or binds only the first of several, closes nothing.

Item 79 WS2, two RCAs that look unrelated and are the same hole from opposite sides.

`Resolves #A, #B` merges with **#B silently left open** (RCA 2026-06-15, issues #307/#260).
Nothing warns, because from GitHub's side nothing went wrong: it did exactly what one closing
keyword means. The author's intent and the platform's contract simply disagreed, and only the
platform got a vote.

Eighteen of sixty merged PRs carried **no closing reference at all** (RCA 2026-07-18 control 3).
Their issues never auto-closed, so no completion-moment gate could fire — there were no refs for
one to check. The comma-list predicate cannot catch this: zero refs yields zero list errors. Both
predicates exist because each is blind to the other's failure.

Both scan through the SHARED fence/inline-code blanker, so a body that shows the wrong form inside
a fenced block *as an example of what not to write* is not refused for containing it.
"""
import json

import pytest


# --- the comma-list trap -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Resolves #307, #260",
        "resolves #307,#260",
        "Fixes: #1, #2, #3",
        "Closed #10 , #11",
    ],
)
def test_a_comma_list_after_one_keyword_is_refused(cli, body: str) -> None:
    errors = cli.pr_body_closing_reference_errors(body)

    assert len(errors) == 1, errors
    assert "auto-closes only #" in errors[0]


def test_the_refusal_carries_the_rewritten_line(cli) -> None:
    """"Use one keyword per issue" without the rewrite is a rule the author still has to
    translate. The refusal hands back the exact replacement text."""
    errors = cli.pr_body_closing_reference_errors("Resolves #307, #260")

    assert "`Resolves #307`, `Resolves #260`" in errors[0]
    assert "Then re-run." in errors[0]


@pytest.mark.parametrize(
    "body",
    [
        "Resolves #307",
        "Resolves #307\nResolves #260",
        "Fixes #1 and Fixes #2",
        "See #307, #260 for context",          # no closing keyword: not a closing list
        "",
    ],
)
def test_a_compliant_or_irrelevant_body_is_not_refused(cli, body: str) -> None:
    assert cli.pr_body_closing_reference_errors(body) == []


def test_one_error_per_offending_keyword(cli) -> None:
    body = "Resolves #1, #2\n\nAlso Fixes #3, #4"

    assert len(cli.pr_body_closing_reference_errors(body)) == 2


# --- the missing-reference trap ----------------------------------------------------------------


def test_a_body_binding_no_auto_close_is_named(cli) -> None:
    error = cli.pr_body_missing_closing_reference_error("Some prose about the change.")

    assert error.startswith("missing_closing_ref:")
    assert "auto-close nothing" in error
    # Every exit that actually works, because a refusal with one exit is a wall for anyone the
    # exit does not fit -- and one that names an exit which does NOT work is worse still.
    assert "Resolves #<issue>" in error
    assert "allowRepoOnlyGoals" in error


@pytest.mark.parametrize("body", ["Resolves #7", "fixed #7", "Closes: #7", "text\n\nCloses #7\n"])
def test_a_body_that_binds_an_auto_close_passes(cli, body: str) -> None:
    assert cli.pr_body_missing_closing_reference_error(body) == ""


def test_a_comma_list_still_counts_as_binding_something(cli) -> None:
    """The two predicates answer different questions and must not double-refuse: `Resolves #1, #2`
    IS a closing reference (a defective one, which the other predicate names). Reporting it as
    *missing* too would tell the author to add what they already wrote."""
    assert cli.pr_body_missing_closing_reference_error("Resolves #1, #2") == ""
    assert cli.pr_body_closing_reference_errors("Resolves #1, #2")


# --- example text is not instruction ------------------------------------------------------------


def test_a_fenced_example_of_the_wrong_form_is_not_refused(cli) -> None:
    """A PR body documenting the trap -- showing `Resolves #1, #2` inside a fence as the thing NOT
    to do -- must not be refused for containing it. Both scanners share ONE blanker rather than
    each carrying its own four-line stripper, because two implementations of one rule drift."""
    body = "Resolves #7\n\nDo not write:\n\n```\nResolves #1, #2\n```\n"

    assert cli.pr_body_closing_reference_errors(body) == []
    assert cli.pr_body_missing_closing_reference_error(body) == ""


def test_an_inline_code_span_is_also_example_text(cli) -> None:
    body = "Resolves #7\n\nThe broken form is `Resolves #1, #2` and it drops the second.\n"

    assert cli.pr_body_closing_reference_errors(body) == []


def test_a_fenced_only_reference_does_not_satisfy_the_requirement(cli) -> None:
    """The other direction of the same rule: a closing reference that exists ONLY inside a fence
    is documentation, not a binding, and GitHub will not act on it either."""
    body = "How to close this:\n\n```\nResolves #7\n```\n"

    assert cli.pr_body_missing_closing_reference_error(body) != ""


# --- the scanners share one blanker, by construction --------------------------------------------


def test_both_scanners_use_the_shared_blanker(cli) -> None:
    """Structural. Two fence-strippers for one rule is how a body gets refused by one scanner and
    accepted by the other -- the one-fact-two-readers failure this codebase keeps paying for."""
    import inspect

    for predicate in (cli.pr_body_closing_reference_errors,
                      cli.pr_body_missing_closing_reference_error):
        source = inspect.getsource(predicate)
        assert "text_without_code_spans(" in source, predicate.__name__
        assert "```" not in source, f"{predicate.__name__} re-implements fence stripping"


# --- the merge verb rides the existing enforcement switch (D4b) ---------------------------------


def _merge_refs(cli, monkeypatch, *, body, enforcement, repo_only=False):
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": repo_only},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": repo_only},
        "workProfiles": {"enabled": True},
    }
    monkeypatch.setattr(cli, "read_work_profile_lock", lambda d, t: ("development", "test", []))
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(
        cli, "command_json",
        lambda *a, **k: (0, {"body": body}, "") if body is not None else (1, None, "boom"),
    )
    return data


@pytest.mark.parametrize(
    ("enforcement", "expected"), [("block", 1), ("advise", 0), ("off", 0)]
)
def test_the_merge_checks_ride_the_enforcement_switch(
    cli, tmp_path, monkeypatch, capsys, enforcement, expected
):
    """One enforcement contract for the whole verb. A second, differently-configured gate inside
    the same command is how an operator's `advise` setting silently stops meaning advise."""
    data = _merge_refs(cli, monkeypatch, body="no refs at all", enforcement=enforcement)

    rc = cli.merge_command_closing_refs(data, tmp_path, "12", None, enforcement)

    captured = capsys.readouterr()
    assert rc == expected
    if enforcement == "block":
        assert "merge_gate_issue:" in captured.err
    elif enforcement == "advise":
        assert "merge_gate_would_block:" in captured.out
    else:
        assert "missing_closing_ref" not in captured.out + captured.err


def test_an_unreadable_body_warns_and_lets_the_merge_proceed(cli, tmp_path, monkeypatch, capsys):
    """A provider hiccup must not refuse a merge whose other checks are green -- and must not pass
    silently either, or the gate is decorative."""
    data = _merge_refs(cli, monkeypatch, body=None, enforcement="block")

    rc = cli.merge_command_closing_refs(data, tmp_path, "12", None, "block")

    assert rc == 0
    assert "pr_closing_refs_warn:" in capsys.readouterr().err


def test_a_repo_only_lane_is_exempt_from_the_missing_reference_check(
    cli, tmp_path, monkeypatch, capsys
):
    """G2 present-branch. `allowRepoOnlyGoals` is the sanctioned no-board-item path; refusing it
    here would invent a parallel bypass around a knob that already exists."""
    data = _merge_refs(cli, monkeypatch, body="no refs at all", enforcement="block", repo_only=True)

    assert cli.merge_command_closing_refs(data, tmp_path, "12", None, "block") == 0
    assert "missing_closing_ref_exempt: allowRepoOnlyGoals" in capsys.readouterr().out


def test_the_exemption_never_covers_a_malformed_comma_list(cli, tmp_path, monkeypatch):
    """The exemptions answer "must this PR bind an issue?" -- never "may it bind one wrongly?".
    A comma list still silently drops refs whether or not the lane is repo-only."""
    data = _merge_refs(
        cli, monkeypatch, body="Resolves #1, #2", enforcement="block", repo_only=True
    )

    assert cli.merge_command_closing_refs(data, tmp_path, "12", None, "block") == 1


def test_a_provider_response_without_a_body_key_is_not_an_empty_body(
    cli, tmp_path, monkeypatch, capsys
):
    """A MISSING KEY IS NOT AN EMPTY VALUE. Some `gh` versions and response shapes omit `body`
    entirely; treating that absence as "no closing reference" refuses a PR whose body was never
    read. Same trap the `github-projects-reads` skill documents for `item-list --format json`
    dropping `fieldValues` -- a null there is an unanswered question, not an empty field.

    Found by a pre-existing branch-liveness test whose fake `gh` returns a canned PR list with no
    `body` key: the gate refused it, which is exactly the false positive this guard prevents."""
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": False},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": False},
    }
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: (0, [{"number": 12}], ""))

    assert cli.outgoing_pr_closing_ref_issues(data, tmp_path, "feat/x") == []
    assert "pr_closing_refs_warn: PR body absent" in capsys.readouterr().err


def test_a_merge_response_without_a_body_key_does_not_refuse(cli, tmp_path, monkeypatch, capsys):
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": False},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": False},
    }
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: (0, {"number": 12}, ""))

    assert cli.merge_command_closing_refs(data, tmp_path, "12", None, "block") == 0
    assert "pr_closing_refs_warn: PR body absent" in capsys.readouterr().err


def test_an_explicitly_empty_body_still_refuses(cli, tmp_path, monkeypatch):
    """The other half of the same rule, and the reason the distinction has to be a key check rather
    than a truthiness check: a body the provider DID return, which happens to be empty, binds
    nothing and must still be caught."""
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": False},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": False},
    }
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: (0, {"number": 12, "body": ""}, ""))

    assert cli.merge_command_closing_refs(data, tmp_path, "12", None, "block") == 1


# --- one exemption resolver, so the two boundaries cannot disagree ------------------------------


def test_both_boundaries_resolve_exemptions_through_one_function(cli) -> None:
    """Codex R1 P2. Prepush exempted a non-development work profile and merge did not, so a docs
    PR passed prepush and then refused at `tautline merge` -- the same gate answering the same
    question two ways depending on where you met it. The fix is not to add the missing branch in
    the second place; it is to have one place."""
    import inspect

    for fn in (cli.outgoing_pr_closing_ref_issues, cli.merge_command_closing_refs):
        source = inspect.getsource(fn)
        body = source.split('"""')[-1]  # skip the docstring, which may discuss the exemptions
        assert "closing_reference_exemption(data, target)" in body, fn.__name__
        for primitive in ("read_work_profile_lock", 'get("allowRepoOnlyGoals")'):
            assert primitive not in body, f"{fn.__name__} re-derives an exemption: {primitive}"


@pytest.mark.parametrize(
    ("knob", "profile", "recorded", "expected"),
    [
        (True, "development", False, "allowRepoOnlyGoals"),
        (False, "product-management", False, "work profile product-management"),
        (False, "development", False, ""),
    ],
)
def test_every_exemption_is_a_lane_that_already_said_so(
    cli, tmp_path, monkeypatch, knob, profile, recorded, expected
) -> None:
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": knob},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": knob},
        "workProfiles": {"enabled": True},
    }
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "read_work_profile_lock", lambda d, t: (profile, "test", []))

    assert cli.closing_reference_exemption(data, tmp_path) == expected


def test_a_docs_profile_pr_passes_prepush_and_merge_alike(cli, tmp_path, monkeypatch) -> None:
    """The end-to-end shape of the defect: same lane, same body, both boundaries must agree."""
    data = {
        "goalTracker": {"enabled": True, "allowRepoOnlyGoals": False},
        "backlogProvider": {"enabled": True, "allowRepoOnlyGoals": False},
        "workProfiles": {"enabled": True},
    }
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "read_work_profile_lock", lambda d, t: ("product-management", "x", []))
    monkeypatch.setattr(
        cli, "command_json",
        lambda args, *a, **k: (0, [{"number": 12, "body": "docs only"}], "")
        if "list" in args else (0, {"number": 12, "body": "docs only"}, ""),
    )

    assert cli.outgoing_pr_closing_ref_issues(data, tmp_path, "docs/x") == []
    assert cli.merge_command_closing_refs(data, tmp_path, "12", None, "block") == 0


# --- the escape hatch must not disable the gate forever ------------------------------------------


def _events(cli, tmp_path, entries):
    data = {"observability": {"stateDir": ".ai-runs", "humanLog": "events.log",
                              "jsonlLog": "events.jsonl"}}
    path = tmp_path / ".ai-runs" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return data, path


# --- GitHub's cross-repository closing form ------------------------------------------------------


@pytest.mark.parametrize(
    "body", ["Fixes owner/repo#123", "Closes my-org/my.repo#7", "resolves: a/b#1"]
)
def test_a_qualified_cross_repo_reference_binds_an_auto_close(cli, body: str) -> None:
    """Codex R1 P2. `owner/repo#123` is GitHub's supported cross-repository closing form and
    auto-closes exactly like `#123`. Refusing it means the gate rejecting correct work -- the most
    expensive false positive a blocking gate can have."""
    assert cli.pr_body_missing_closing_reference_error(body) == ""


def test_a_qualified_comma_list_is_still_the_trap(cli) -> None:
    """The cross-repo form does not escape the comma-list rule: GitHub still honors only the
    first."""
    errors = cli.pr_body_closing_reference_errors("Fixes owner/repo#1, owner/repo#2")

    assert len(errors) == 1
    assert "owner/repo#1" in errors[0] and "owner/repo#2" in errors[0]


@pytest.mark.parametrize(
    "body",
    [
        "Closes https://github.com/owner/repo/issues/123",
        "Fixes http://github.com/o/r/issues/7",
    ],
)
def test_a_full_issue_url_binds_an_auto_close(cli, body: str) -> None:
    """Codex R2 P2. GitHub honors the full URL form; refusing it is the gate rejecting work GitHub
    would auto-close."""
    assert cli.pr_body_missing_closing_reference_error(body) == ""


def test_a_url_comma_list_is_still_the_trap(cli) -> None:
    body = "Closes https://github.com/o/r/issues/1, https://github.com/o/r/issues/2"

    assert len(cli.pr_body_closing_reference_errors(body)) == 1


def test_an_adapter_declared_base_branch_is_not_a_feature_branch(
    cli, tmp_path, monkeypatch
) -> None:
    """Codex R3 P2. A repo declaring an integration branch outside the built-in names had it treated
    as a feature branch, so a push to the base could inspect an open release PR's body and block the
    board gate -- on a branch every other gate already exempts."""
    calls = []
    data = {"goalTracker": {"enabled": True}, "backlogProvider": {"enabled": True}}
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(cli, "adapter_base_branch_names", lambda d, t=None: {"main", "experimental"})
    monkeypatch.setattr(cli, "command_json", lambda *a, **k: calls.append(a) or (0, [], ""))

    assert cli.outgoing_pr_closing_ref_issues(data, tmp_path, "experimental") == []
    assert calls == [], "an adapter-declared base branch must not be inspected as a feature branch"

    import inspect
    assert "adapter_base_branch_names(data, target)" in inspect.getsource(
        cli.outgoing_pr_closing_ref_issues
    )


def test_the_refusal_no_longer_advertises_the_removed_exemption(cli) -> None:
    """The `board-binding` decision exemption was wrong in FOUR different ways across four review
    rounds: unscoped across the whole repo, compared as text across timezones, grantable by any log
    event, anchored on the wrong branch, and finally still exempting a CONCURRENT lane's PR from
    one lane's decision. Every fix narrowed it; none made it correct. It is removed and filed as
    its own item, because a refusal that names an exit which does not work is worse than one that
    names fewer exits."""
    error = cli.pr_body_missing_closing_reference_error("no refs")

    assert "board-binding" not in error
    assert "decision-record" not in error
    assert "allowRepoOnlyGoals" in error, "the exits that DO work must still be named"
    assert "Resolves #<issue>" in error
    assert not hasattr(cli, "closing_reference_exemption_recorded"), (
        "the predicate is gone, not merely unreferenced"
    )


def test_an_adapter_declared_base_branch_counts_as_a_base(cli, tmp_path) -> None:
    """A project whose integration branch is neither `main` nor `develop` declares it in the
    adapter, and every caller of this set must honour that declaration. Codex R4 P2: without it,
    pushing the configured base queries an open release PR from the base and blocks the prepush
    board gate on that PR's body -- a gate failing on a branch it was never meant to police."""
    data = {"review": {"codexWrapper": "codex-run --base origin/release-train"}}

    names = cli.adapter_base_branch_names(data, tmp_path)

    assert "release-train" in names, "the declared base is a base"
    assert "origin/release-train" not in names, "compared against bare `branch --show-current`"
    assert {"main", "develop"} <= names, "the built-ins are added to, never replaced"
