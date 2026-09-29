"""The builder-lane GitHub guard: `tautline board|issue|debt` is the ONLY way a build agent
reaches issues or the project board, and a HUMAN never notices this control exists.

This file replaces two vacuous stubs (`test_board_structure_guard.py`,
`test_board_item_guard.py`) left behind when an earlier board guard was deleted. Their docstrings
recorded WHY a guard exists at all: a raw `gh api graphql ... updateProjectV2Field` once rebuilt a
project's whole Status option set and orphaned every card. Those files asserted
`'"decision": "block"' not in res.stdout` against a CLI verb that no longer exists, so they passed
by measuring nothing. The intent -- board mutations must not be reachable by an agent shelling out
-- is covered here, on a predicate that is actually wired to a PreToolUse hook.

THE MOST IMPORTANT TEST IN THIS FILE IS THE HUMAN ONE. The product director and the operator work
in the same repos with the same `gh`; a guard that adds one keystroke of friction for them is a
worse outcome than the incident it prevents. So the predicate is a no-op unless
`builder_role_active()` says builder, and the human case is asserted over the very commands the
builder case denies -- including the graphql call from the original incident.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tautline_methodology import builder_guard as bg

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"

HOOKS_JSON = REPO_ROOT / "plugins" / "tautline-core" / "hooks" / "hooks.json"

LEAN_ADAPTER = {
    "schemaVersion": "lean-1",
    "project": {"name": "Guarded", "repo": "example-org/guarded"},
    "integrationBranch": "main",
    "commands": {"test": "scripts/test.sh"},
}


# The commands the guard exists to stop. `gh api graphql ... updateProjectV2Field` is the literal
# shape of the 2026-06-24 incident the deleted stubs recorded.
DENIED_FOR_BUILDERS = [
    "gh repo sync",
    "gh workflow run deploy.yml",
    "gh workflow disable ci.yml",
    "gh issue create --title x --body y",
    "gh issue close 7",
    "gh issue edit 7 --add-label blocked",
    "gh project item-add 5 --owner example-org --url https://github.com/example-org/r/issues/1",
    "gh project item-edit --id ITEM --field-id F --text done",
    "gh label create blocked --color ff0000",
    "gh milestone list",
    "gh gist create notes.txt",
    'gh api graphql -f query=\'mutation { updateProjectV2Field(input: {}) { clientMutationId } }\'',
    "gh api repos/o/r/issues/1/comments -f body=x",
    "gh api -X PATCH repos/o/r/issues/1",
    'curl -H "Authorization: token abc" https://api.github.com/repos/o/r/issues',
    "git status && gh issue list",
    "echo x | gh issue create",
    "$(gh issue view 1)",
    # A loop body's command word is one token past `do`, so a segment head of `do` hid the real
    # invocation from the first cut of the tokenizer. Same class as `then`, `else` and `{`.
    "for i in 1 2; do gh issue close $i; done",
    "if gh issue view 1; then echo found; fi",
    # `gh repo` is allowed for its READ half only. These four do not come back: a deleted or
    # renamed repository is not something the operator who notices it can undo, and `gh repo edit`
    # reaches branch protection, which is the control fencing the App's Contents write permission.
    "gh repo delete example-org/guarded --yes",
    "gh repo edit --default-branch main",
    "gh repo rename newname",
    "gh repo archive example-org/guarded --yes",
    # Builders do not cut releases. `gh release` is in no allow-list at all, so `create` and the
    # rest of the family are denied by omission rather than by enumeration.
    "gh release create v1",
    "gh release delete v1 --yes",
    "gh release upload v1 dist.tgz",
    # A LEADING REDIRECTION sits where the command word would be, and the shell steps straight over
    # it: `2>/dev/null gh issue create` runs `gh issue create`. The first tokenizer read the whole
    # of `2>/dev/null` as the segment's head token, found it was not `gh`, and allowed the lot --
    # a one-character prefix that turned the guard off. Every spelling is here because they are
    # separate code paths in the tokenizer, not variations on one.
    "2>/dev/null gh issue create",
    "</dev/null gh issue create",
    ">/tmp/out gh issue create",
    ">>/tmp/out gh issue create",
    "2>&1 gh issue create",
    "&>/dev/null gh issue create",
    "2> /dev/null gh issue create",
    # ...and behind a wrapper, where the redirection applies to the whole command the same way.
    "env 2>/dev/null gh issue create",
    "GH_TOKEN=x 2>/dev/null gh issue create",
    # `gh auth` was allow-listed WHOLE, which handed a lane the operator's own credential and the
    # ability to destroy it. `gh auth token` prints it to stdout -- from where it reaches a log, a
    # comment, or the next command's argv. `gh auth refresh -s project` re-scopes the HUMAN's
    # credential to write the board, which is the one thing the App's Projects-read permission
    # exists to make impossible; the App is not in the loop for a `gh` that authenticates as a
    # person. `gh auth logout` destroys the operator's login on their own machine.
    "gh auth token",
    "gh auth login",
    "gh auth logout",
    "gh auth refresh -s project",
    "gh auth setup-git",
    "gh auth switch",
    # `gh pr` was allow-listed whole too, and a pull request is a board item: `--add-project` puts
    # one on the project, which is a board write by another door. Milestones and labels are
    # stakeholder-visible fields on the same object.
    "gh pr edit 3 --add-project Roadmap",
    "gh pr edit 3 --remove-project Roadmap",
    "gh pr edit 3 --add-label blocked",
    "gh pr edit 3 --remove-label blocked",
    "gh pr edit 3 --milestone v2",
    "gh pr create --fill --project Roadmap",
    "gh pr create --fill --label blocked",
    "gh pr list --label blocked",
    # ...including the short spellings, on the two actions where they mean project, milestone and
    # label rather than something else.
    "gh pr create --fill -m v2",
    "gh pr create --fill -l blocked",
    "gh pr create --fill -p Roadmap",
    "gh pr edit 3 -m v2",
    # `gh run` is how a lane READS its own CI. Deleting a run takes the logs a human was about to
    # look at; cancelling and re-running act on CI somebody is waiting on.
    "gh run delete 123",
    "gh run cancel 123",
    "gh run rerun 123 --failed",
    # Five shapes that put the SUBCOMMAND somewhere the head-token read could not see it. Each is
    # a different mechanism, which is why they are enumerated rather than generalised:
    #   * `xargs` appends the subcommand from stdin, leaving a bare `gh` -- which used to take the
    #     "a bare `gh` reaches nothing" exit meant for `gh --help`;
    #   * a herestring is a payload, exactly like `-c`, in different punctuation;
    #   * `env -S` splits a string into a command line, which is `-c` again under another name;
    #   * `find -exec` runs its own command word, one the segment's head is not;
    #   * a literal piped into a shell is the payload arriving through stdin.
    'echo "issue create" | xargs gh',
    "xargs gh",
    'bash <<< "gh issue create"',
    "sh <<<'gh project item-edit --id X'",
    'env -S "gh issue create"',
    "env --split-string='gh issue create'",
    "find . -exec gh issue create \\;",
    "find . -type f -execdir gh issue close 1 \\;",
    "printf 'gh issue create\\n' | sh",
    "echo 'gh issue create' | bash",
]

ALLOWED_FOR_BUILDERS = [
    "gh workflow list",
    "gh workflow view ci.yml",
    "gh pr create --fill",
    "gh pr view 12 --json state",
    "gh run list",
    "gh auth status",
    "gh api rate_limit",
    "gh api repos/o/r/pulls/3",
    # The read half of `gh repo`: a lane must be able to look at the repository it works in and to
    # get a copy of it.
    "gh repo view example-org/guarded",
    "gh repo view",
    "gh repo clone example-org/guarded",
    "tautline issue comment 5 --body hi",
    "git push",
    # A plain string argument to `echo` is NOT a command invocation: the tokenizer keys on the
    # first word of each segment, and `echo`'s arguments reach nothing. Documented here because
    # the alternative (substring matching on "gh issue") denies every `grep`, every commit message
    # and every code comment that mentions the verbs -- friction with no defect behind it.
    "echo gh issue",
    "git commit -m 'stop using gh issue create directly'",
    "curl https://example.com/health",
    # Redirections are recognised as OPERATORS, which must not cost a lane its ordinary plumbing:
    # an allowed `gh` keeps its output redirection, and a redirection in front of a command that is
    # not `gh` at all reaches nothing.
    "gh pr list > out.txt",
    "gh api rate_limit 2>/dev/null",
    "gh repo clone o/r 2> err.log",
    "2>/dev/null git status",
    # The pull-request work a lane actually does, with none of the board-reaching flags.
    "gh pr edit 3 --title 'a better title'",
    "gh pr edit 3 --body-file body.md",
    "gh pr comment 3 --body hi",
    "gh pr checks 3",
    "gh pr merge 3 --squash",
    # `-m` on `gh pr merge` is the MERGE-COMMIT strategy, not a milestone. Denying the short flag
    # everywhere would have broken an allowed verb on a spelling that means something else.
    "gh pr merge 3 -m",
    "gh run view 123 --log-failed",
    "gh run watch 123",
    "gh run download 123 --name coverage",
    # The same five mechanisms carrying ordinary work. Each one is a recursion, so each one is a
    # place a careless implementation would start denying a lane's own tooling.
    "git ls-files | xargs wc -l",
    "bash <<< 'gh pr list'",
    "env -S 'pytest -q'",
    "find . -name '*.py' -exec wc -l {} \\;",
    "printf 'echo hello\\n' | sh",
    "echo 'ls -la' | bash",
    # `||` is a logical OR, not a pipe: the left-hand text is never fed to the right-hand command.
    "echo 'gh issue create' || sh",
]


# --------------------------------------------------------------------------- humans are never bound


@pytest.mark.parametrize("command", DENIED_FOR_BUILDERS + ALLOWED_FOR_BUILDERS)
def test_a_human_lane_is_never_guarded_not_even_for_gh_project_item_edit_or_gh_api_graphql(command):
    """THE LOAD-BEARING TEST. Default is human, and a human is allowed everything.

    Every command the builder case denies -- `gh project item-edit`, `gh api graphql`, the raw
    mutation from the incident -- must come back allowed with an empty reason when the caller is
    not a builder lane. If this ever goes red the control has started charging the people it was
    never meant to bind, and it should be removed rather than tuned.
    """
    decision = bg.decide(command, builder=False)
    assert decision.allowed
    assert decision.reason == ""
    assert decision.matched == ""


def test_the_default_role_is_human_so_an_unmarked_lane_is_unguarded(tmp_path):
    from tautline_methodology.builder import builder_role_active

    assert builder_role_active(tmp_path, {}) is False


def test_the_env_marker_activates_the_builder_role(tmp_path):
    from tautline_methodology.builder import builder_role_active

    assert builder_role_active(tmp_path, {"TAUTLINE_ROLE": "builder"}) is True


def test_the_lane_role_file_activates_the_builder_role(tmp_path):
    from tautline_methodology.builder import builder_role_active

    (tmp_path / ".ai-work").mkdir()
    (tmp_path / ".ai-work" / "lane-role").write_text("builder\n", encoding="utf-8")
    assert builder_role_active(tmp_path, {}) is True


# --------------------------------------------------------------------------- the builder predicate


@pytest.mark.parametrize("command", DENIED_FOR_BUILDERS)
def test_a_builder_lane_is_denied_every_issue_and_board_reaching_command(command):
    decision = bg.decide(command, builder=True)
    assert not decision.allowed, command
    assert decision.matched
    assert "tautline board|issue|debt" in decision.reason
    assert "tautline issue --help" in decision.reason
    assert decision.matched[:40] in decision.reason
    assert len(decision.reason) < 300, len(decision.reason)


@pytest.mark.parametrize("command", ALLOWED_FOR_BUILDERS)
def test_a_builder_lane_keeps_the_commands_it_needs_to_do_its_job(command):
    decision = bg.decide(command, builder=True)
    assert decision.allowed, f"{command} -> {decision.reason}"


def test_the_gh_subcommand_rule_is_an_allow_list_so_an_unknown_verb_is_denied():
    """Allow-list, not deny-list: the deleted guard was a deny-list and a verb GitHub shipped
    later (`gh project`) walked straight through it."""
    assert not bg.decide("gh brand-new-verb --do-something", builder=True).allowed
    assert bg.ALLOWED_GH_SUBCOMMANDS == frozenset(
        {"pr", "run", "workflow", "auth", "repo", "status", "search"}
    )


def test_gh_search_issues_is_denied_while_gh_search_prs_is_allowed():
    assert not bg.decide("gh search issues --state open", builder=True).allowed
    assert bg.decide("gh search prs --state open", builder=True).allowed


def test_gh_repo_is_allowed_for_its_read_half_and_denied_for_the_half_that_does_not_come_back():
    """The subcommand is too coarse to be the unit of the decision.

    `gh repo view` and `gh repo clone` are how a lane looks at the repository it works in. `gh repo
    delete` is unrecoverable, `gh repo rename` and `gh repo archive` are stakeholder-visible, and
    `gh repo edit` reaches BRANCH PROTECTION -- which is the control that fences the App's residual
    Contents write permission (docs/builder-lanes.md). A lane able to edit it could unfence itself,
    so the second allow-list is what keeps that control outside the lane's reach.
    """
    assert bg.ALLOWED_GH_REPO_ACTIONS == frozenset({"view", "clone"})
    for command in ("gh repo view", "gh repo clone o/r"):
        assert bg.decide(command, builder=True).allowed, command
    for command in (
        "gh repo delete o/r --yes",
        "gh repo edit --enable-issues=false",
        "gh repo rename other",
        "gh repo archive o/r",
        "gh repo create o/r --public",
        "gh repo fork o/r",
        "gh repo set-default o/r",
        # An action this guard could not read is an argument shape it has not understood. Bare
        # `gh repo` fails CLOSED rather than inheriting the harmless-`gh --help` exit.
        "gh repo",
        "gh repo --json name",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_the_docstring_table_is_derived_from_the_constants_so_it_cannot_drift():
    """The module docstring described `gh repo` as allowing `view`, `clone` and `sync` for two
    commits after `sync` was taken out of the constant, and it described THREE second-level
    allow-lists when there were five. A table that restates a constant is a copy, and a copy of a
    security boundary that nobody diffs is worse than no table -- a reader trusts it.

    So the table names the CONSTANTS, and this test keeps the set of them honest in both
    directions: a new second-level allow-list nobody mentioned fails here, and so does a row for a
    list that no longer exists.
    """
    doc = bg.__doc__ or ""
    lists = sorted(
        name
        for name in dir(bg)
        if name.startswith("ALLOWED_GH_") and name != "ALLOWED_GH_SUBCOMMANDS"
    )
    assert lists, "no second-level allow-list found; the docstring table describes nothing"
    for name in lists:
        assert name in doc, f"{name} is a second-level allow-list the docstring does not name"
    for name in set(re.findall(r"ALLOWED_GH_[A-Z_]+", doc)):
        assert hasattr(bg, name), f"the docstring table names {name}, which no longer exists"
    # The concrete drift the table carried: the prose allowed `gh repo sync`, the constant did not.
    assert "sync" not in bg.ALLOWED_GH_REPO_ACTIONS
    assert not bg.decide("gh repo sync", builder=True).allowed


def test_gh_auth_is_narrowed_to_status_so_a_lane_cannot_read_or_re_scope_a_credential():
    """`gh auth` was allow-listed whole, and the whole verb is three separate liberties.

    `gh auth token` PRINTS the operator's credential, from where it reaches a log or a comment.
    `gh auth refresh -s project` re-scopes that credential to write the project board -- the App's
    Projects-read permission is not in that path at all, because `gh` is authenticated as a
    person -- so the pairing with `gh pr edit --add-project` below is a complete board write with
    the guard's blessing. `gh auth logout` destroys a login on the operator's own machine.

    `status` is what a lane legitimately needs: "am I authenticated, and as whom".
    """
    assert bg.ALLOWED_GH_AUTH_ACTIONS == frozenset({"status"})
    assert bg.decide("gh auth status", builder=True).allowed
    for command in (
        "gh auth token",
        "gh auth login --with-token",
        "gh auth logout",
        "gh auth refresh -s project",
        "gh auth setup-git",
        "gh auth",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_gh_pr_keeps_its_work_and_loses_the_flags_that_reach_the_board():
    """A pull request IS a board item, so `gh pr` is too coarse to be the unit of the decision.

    `--add-project` puts a PR on the project board, which is the write this whole control exists
    to prevent, reached through the one subcommand a lane uses constantly. Milestones and labels
    are the same class: stakeholder-visible fields somebody else curates.

    The LONG flags are denied on every `gh pr` action, including the read ones -- a lane that wants
    PRs with a label can filter them itself, and a per-action flag table would drift the first time
    `gh` moved a flag. The SHORT ones are denied only on `create` and `edit`, because `-m` on
    `gh pr merge` is the merge-commit strategy: denying it everywhere would have broken an allowed
    verb on a spelling that means something else entirely.
    """
    for command in (
        "gh pr edit 3 --add-project Roadmap",
        "gh pr edit 3 --remove-project Roadmap",
        "gh pr edit 3 --add-label blocked",
        "gh pr edit 3 --remove-label blocked",
        "gh pr edit 3 --milestone=v2",
        "gh pr create --fill --label=blocked",
        "gh pr create --fill -lblocked",
        "gh pr list --label blocked",
    ):
        assert not bg.decide(command, builder=True).allowed, command
    for command in (
        "gh pr create --fill",
        "gh pr view 3 --json state",
        "gh pr list --state open",
        "gh pr merge 3 -m",
        "gh pr edit 3 --title x --body-file b.md",
    ):
        assert bg.decide(command, builder=True).allowed, command


def test_gh_run_is_the_read_half_of_ci_and_not_the_half_that_deletes_it():
    """`gh run delete` removes a run AND its logs -- the evidence a human was about to read, and
    the one kind of deletion nobody notices until they go looking. `cancel` stops a run somebody
    is waiting on, and `rerun` can mask a red run by rolling the dice again."""
    assert bg.ALLOWED_GH_RUN_ACTIONS == frozenset({"list", "view", "watch", "download"})
    for command in ("gh run list", "gh run view 1", "gh run watch 1", "gh run download 1"):
        assert bg.decide(command, builder=True).allowed, command
    for command in ("gh run delete 1", "gh run cancel 1", "gh run rerun 1", "gh run"):
        assert not bg.decide(command, builder=True).allowed, command


def test_the_credential_and_the_board_write_are_denied_as_a_pair():
    """The two halves of the escape the review found, asserted together because neither is
    interesting alone: refresh the human's token onto `project` scope, then use `gh pr edit` to
    put the item on the board. Both are now denied, so the pair cannot be assembled."""
    assert not bg.decide("gh auth refresh -s project", builder=True).allowed
    assert not bg.decide("gh pr edit 3 --add-project Roadmap", builder=True).allowed


def test_gh_release_is_denied_entirely_because_builders_do_not_cut_releases():
    """Denied by OMISSION from the subcommand allow-list, which is the property worth pinning: a
    future `gh release <newverb>` is denied without anyone having to notice GitHub shipped it."""
    assert "release" not in bg.ALLOWED_GH_SUBCOMMANDS
    for command in (
        "gh release create v1",
        "gh release delete v1 --yes",
        "gh release list",
        "gh release view v1",
        "gh release upload v1 dist.tgz",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_gh_api_graphql_is_denied_in_every_spelling():
    for command in (
        "gh api graphql",
        "gh api /graphql",
        "gh api https://api.github.com/graphql -f query=x",
        "gh api graphql --paginate -F number=1",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_a_gh_api_endpoint_cannot_walk_out_of_the_allow_listed_section():
    """`repos/o/r/pulls/../issues` reads as a `pulls` section to a check that looks at the fourth
    path segment, and as `repos/o/r/issues` to whatever resolves the path at the other end. The
    allow-list is positional, so a `..` is not a path component -- it is a way of making the
    positions lie. Percent-encoded spellings are the same trick with an extra hop.
    """
    for command in (
        "gh api repos/o/r/pulls/../issues",
        "gh api repos/o/r/pulls/%2e%2e/issues",
        "gh api repos/o/r/pulls/%2E%2E/issues",
        "gh api repos/o/r/pulls/./../issues",
        "gh api /repos/o/r/pulls/../../../user/issues",
    ):
        assert not bg.decide(command, builder=True).allowed, command
    # A DOT INSIDE a segment is ordinary -- `README.md`, `ci.yml` -- and must keep working.
    assert bg.decide("gh api repos/o/r/contents/README.md", builder=True).allowed


def test_a_read_root_is_the_root_itself_and_not_everything_under_it():
    """`user` answers "who am I"; `user/issues` is the ISSUE LIST, reached through a root that
    looks like identity. It is the same section the allow-list refuses when it is spelled
    `repos/o/r/issues`, so allowing it by prefix put the whole point of the list one slash away."""
    assert bg.GH_API_READ_ROOTS == frozenset({"rate_limit", "user"})
    for command in ("gh api user", "gh api /user", "gh api rate_limit"):
        assert bg.decide(command, builder=True).allowed, command
    for command in (
        "gh api user/issues",
        "gh api /user/issues --paginate",
        "gh api user/repos",
        "gh api rate_limit/anything",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_gh_api_is_a_read_allow_list_gated_on_the_GET_method():
    allowed = [
        "gh api rate_limit",
        "gh api /user",
        "gh api repos/o/r/pulls/3",
        "gh api repos/o/r/commits/abc123",
        "gh api repos/o/r/actions/runs",
        "gh api repos/o/r/check-runs/1",
        "gh api repos/o/r/branches/main",
        "gh api repos/o/r/contents/README.md",
        "gh api -X GET repos/o/r/pulls --paginate",
        "gh api -H 'Accept: application/vnd.github+json' repos/o/r/pulls",
    ]
    denied = [
        "gh api repos/o/r/issues",
        "gh api repos/o/r/labels",
        "gh api -X POST repos/o/r/pulls",
        "gh api -XPOST repos/o/r/pulls",
        "gh api --method=DELETE repos/o/r/pulls/3",
        "gh api repos/o/r/pulls -f title=x",
        "gh api repos/o/r/pulls -F number=1",
        "gh api repos/o/r/pulls --input body.json",
        "gh api",
    ]
    for command in allowed:
        assert bg.decide(command, builder=True).allowed, command
    for command in denied:
        assert not bg.decide(command, builder=True).allowed, command


def test_the_gh_binary_is_recognised_through_the_usual_wrappers():
    for command in (
        "command gh issue create",
        "env GH_TOKEN=x gh issue create",
        "/opt/homebrew/bin/gh issue create",
        "xargs gh issue close",
        "xargs -n 1 gh issue close",
        "timeout 30 gh issue create",
        "GH_TOKEN=x gh issue create",
    ):
        assert not bg.decide(command, builder=True).allowed, command


def test_a_shell_runner_cannot_smuggle_a_denied_command_through_a_quoted_payload():
    """`bash -c '...'` puts the whole inner command in ONE token, so a tokenizer that stopped at
    the top level would let it through. The predicate recurses into the payload instead."""
    assert not bg.decide("bash -c 'gh issue create --title x'", builder=True).allowed
    assert not bg.decide('sh -c "gh project item-add 5"', builder=True).allowed
    assert bg.decide("bash -c 'gh pr view 1'", builder=True).allowed


def test_a_bare_gh_is_harmless_alone_and_unknown_behind_a_wrapper_that_feeds_it_arguments():
    """`gh` with no subcommand reaches nothing -- `gh --help`, `gh --version` -- so denying it
    would spend a lane's attention on a command that cannot cause the defect.

    `xargs gh` is the opposite fact wearing the same shape. `xargs` APPENDS the arguments from
    stdin, so `echo "issue create" | xargs gh` runs `gh issue create` while leaving the guard
    holding a single token. That is not a harmless invocation; it is no invocation at all yet, and
    unknown arguments to `gh` fail closed for the same reason a command substitution does.
    """
    assert bg.decide("gh", builder=True).allowed
    assert bg.decide("gh --version", builder=True).allowed
    assert bg.decide("command gh --help", builder=True).allowed
    assert not bg.decide("xargs gh", builder=True).allowed
    assert not bg.decide('echo "issue create" | xargs gh', builder=True).allowed
    assert not bg.decide("xargs -n 1 gh", builder=True).allowed


def test_a_herestring_is_a_payload_in_different_punctuation():
    assert not bg.decide("bash <<< 'gh issue create'", builder=True).allowed
    assert not bg.decide('sh <<<"gh project item-add 5"', builder=True).allowed
    assert bg.decide("bash <<< 'gh pr view 1'", builder=True).allowed


def test_env_split_string_is_dash_c_under_another_name():
    """`env -S "gh issue create"` splits the string into a command line and runs it. Before the
    fix the guard read the whole string as one word, found it was not `gh`, and allowed it."""
    for command in (
        'env -S "gh issue create"',
        "env --split-string='gh issue create'",
        "env --split-string 'gh issue create'",
        "env -S'gh issue create'",
    ):
        assert not bg.decide(command, builder=True).allowed, command
    assert bg.decide("env -S 'pytest -q'", builder=True).allowed


def test_find_exec_runs_a_command_word_the_segment_head_is_not():
    assert not bg.decide("find . -exec gh issue create \\;", builder=True).allowed
    assert not bg.decide("find . -execdir gh issue close 1 \\;", builder=True).allowed
    assert not bg.decide("find . -exec gh issue create {} +", builder=True).allowed
    assert bg.decide("find . -name '*.py' -exec wc -l {} \\;", builder=True).allowed


def test_a_literal_piped_into_a_shell_is_the_payload_arriving_through_stdin():
    """Best effort, and bounded on purpose: only a `printf`/`echo` LITERAL piped straight into
    `sh|bash|zsh` is read. A generated payload (`python gen.py | sh`) is text this module never
    sees, and the docstring says so rather than implying a completeness it does not have."""
    assert not bg.decide("printf 'gh issue create\\n' | sh", builder=True).allowed
    assert not bg.decide("echo 'gh issue create' | bash", builder=True).allowed
    assert bg.decide("printf 'echo hello\\n' | sh", builder=True).allowed
    # `||` is a logical OR, not a pipe: nothing is fed anywhere.
    assert bg.decide("echo 'gh issue create' || sh", builder=True).allowed


def test_http_clients_are_denied_only_when_they_actually_name_the_github_api():
    for command in (
        "curl https://api.github.com/repos/o/r/issues",
        "wget https://api.github.com/graphql",
        "xh POST https://api.github.com/repos/o/r/issues",
        "python3 -c \"import urllib.request; urllib.request.urlopen('https://api.github.com/repos/o/r/issues')\"",
    ):
        assert not bg.decide(command, builder=True).allowed, command
    for command in ("curl https://pypi.org/simple/", "python3 -c 'print(1)'"):
        assert bg.decide(command, builder=True).allowed, command


def test_a_gh_whose_arguments_come_from_a_substitution_is_unknown_not_harmless():
    """`gh $(echo issue) create` leaves the guard holding the single token `gh`, which looks
    exactly like a bare `gh --help`. Those are different facts: one reaches nothing, the other
    reaches whatever the substitution produces. Unknown arguments to `gh` fail closed."""
    assert not bg.decide("gh $(echo issue) create", builder=True).allowed
    assert not bg.decide("gh `echo issue` create", builder=True).allowed
    # ... while a substitution in an argument POSITION, after a subcommand the guard has already
    # read and allowed, stays allowed: that is ordinary lane work.
    assert bg.decide("gh pr view $(git rev-parse HEAD)", builder=True).allowed
    assert bg.decide('gh pr create --title "$(head -1 msg.txt)"', builder=True).allowed
    assert bg.decide("gh --version", builder=True).allowed


def test_a_redirection_is_an_operator_so_it_cannot_be_glued_to_the_command_word():
    """The tokenizer SPLITS at a redirection rather than stripping one afterwards.

    Stripping a leading `2>/dev/null` as a whole token would work until somebody wrote
    `2>/dev/nullgh issue create`, where a strip that removed the operator's characters and kept
    the rest would reassemble the word `gh`. Splitting at the operator makes that shape what the
    shell makes it -- a redirection to a file called `/dev/nullgh`, in front of a command word
    that is not `gh` -- so there is nothing to reassemble.
    """
    assert bg.tokenize("2>/dev/null gh issue create") == [
        bg.Segment(["2>", "/dev/null", "gh", "issue", "create"])
    ]
    assert bg.tokenize("2>/dev/nullgh issue create") == [
        bg.Segment(["2>", "/dev/nullgh", "issue", "create"])
    ]
    assert bg.tokenize("2>&1 gh issue create") == [
        bg.Segment(["2>&", "1", "gh", "issue", "create"])
    ]
    # A word that merely ENDS in digits is not a file-descriptor prefix: `log2>x` redirects the
    # output of a command called `log2`.
    assert bg.tokenize("log2>x") == [bg.Segment(["log2", ">", "x"])]
    # `&&` is still a segment separator, not the start of an `&>` redirection.
    assert bg.tokenize("git status && gh pr list") == [
        bg.Segment(["git", "status"]),
        bg.Segment(["gh", "pr", "list"]),
    ]


def test_effective_tokens_steps_over_a_leading_redirection_the_way_the_shell_does():
    assert bg.effective_tokens(["2>", "/dev/null", "gh", "issue", "create"]) == [
        "gh",
        "issue",
        "create",
    ]
    assert bg.effective_tokens(["2>&", "1", "gh", "pr", "list"]) == ["gh", "pr", "list"]
    assert bg.effective_tokens(["env", "2>", "/dev/null", "gh", "issue"]) == ["gh", "issue"]


def test_unparseable_shell_denies_for_a_builder_and_still_allows_a_human():
    broken = "gh pr view 'unterminated"
    assert not bg.decide(broken, builder=True).allowed
    assert bg.decide(broken, builder=False).allowed


# --------------------------------------------------------------------------- the PreToolUse hook


def _lane(tmp_path, *, builder: bool) -> Path:
    root = tmp_path / "lane"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".tautline.json").write_text(json.dumps(LEAN_ADAPTER), encoding="utf-8")
    if builder:
        (root / ".ai-work").mkdir(exist_ok=True)
        (root / ".ai-work" / "lane-role").write_text("builder\n", encoding="utf-8")
    return root


def _payload(root: Path, command: str, tool_name: str = "Bash") -> str:
    return json.dumps(
        {
            "session_id": "s1",
            "cwd": str(root),
            "tool_name": tool_name,
            "tool_input": {"command": command},
        }
    )


def test_the_hook_is_silent_and_exit_zero_for_a_human_on_the_incident_command(run_cli, tmp_path):
    root = _lane(tmp_path, builder=False)
    res = run_cli("builder-guard", "--hook", stdin=_payload(root, "gh api graphql -f query=x"))
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""
    assert res.stderr == ""


def test_the_hook_blocks_a_builder_with_exit_two_a_deny_object_and_a_readable_reason(
    run_cli, tmp_path
):
    root = _lane(tmp_path, builder=True)
    res = run_cli("builder-guard", "--hook", stdin=_payload(root, "gh issue create --title x"))
    assert res.returncode == 2, (res.stdout, res.stderr)
    payload = json.loads(res.stdout)
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    assert "tautline board|issue|debt" in specific["permissionDecisionReason"]
    assert "tautline board|issue|debt" in res.stderr
    assert "Traceback" not in res.stderr


def test_the_hook_allows_a_builder_the_commands_the_lane_needs(run_cli, tmp_path):
    root = _lane(tmp_path, builder=True)
    res = run_cli("builder-guard", "--hook", stdin=_payload(root, "gh pr view 12 --json state"))
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert res.stdout == ""


def test_the_hook_ignores_every_tool_that_is_not_bash(run_cli, tmp_path):
    root = _lane(tmp_path, builder=True)
    res = run_cli(
        "builder-guard", "--hook", stdin=_payload(root, "gh issue create", tool_name="Write")
    )
    assert res.returncode == 0
    assert res.stdout == ""


def test_a_malformed_payload_fails_open_for_a_human_and_closed_for_a_builder(run_cli, tmp_path):
    human = _lane(tmp_path / "h", builder=False)
    builder = _lane(tmp_path / "b", builder=True)
    open_res = run_cli("builder-guard", "--hook", "--target", str(human), stdin="not json at all")
    assert open_res.returncode == 0, open_res.stderr
    closed_res = run_cli(
        "builder-guard", "--hook", "--target", str(builder), stdin="not json at all"
    )
    assert closed_res.returncode == 2, (closed_res.stdout, closed_res.stderr)
    assert "Traceback" not in closed_res.stderr


def test_an_unexpected_error_in_the_hook_denies_a_builder_rather_than_failing_open(
    monkeypatch, tmp_path, cli
):
    """`builder-guard` does not end in `-hook`, so dispatch_command's fail-open contract does not
    cover it -- correctly, because failing open is only right for HUMANS. An unhandled exception
    would otherwise exit 1 with a traceback, which a harness reads as ALLOW: the guard failing open
    for a builder on the one path where that matters."""
    import argparse

    root = _lane(tmp_path, builder=True)
    monkeypatch.setattr(bg, "_hook_decision", _exploding)
    args = argparse.Namespace(
        target=root, hook=True, argv=False, shim_dir=False, report=False, command=[]
    )
    assert bg.builder_guard_command(args) == 2

    human = _lane(tmp_path / "h", builder=False)
    args.target = human
    assert bg.builder_guard_command(args) == 0


def _exploding(_args):
    raise RuntimeError("the guard blew up")


def test_the_env_marker_activates_the_hook_end_to_end(tmp_path):
    """The file marker is covered above; this is the OTHER activation path, and it needs an
    env-carrying runner (`run_cli` deliberately passes only PATH and HOME)."""
    root = _lane(tmp_path, builder=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TAUTLINE_ROLE": "builder"}
    res = subprocess.run(
        [sys.executable, str(CLI_PATH), "builder-guard", "--hook"],
        input=_payload(root, "gh issue create"),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert res.returncode == 2, (res.stdout, res.stderr)
    assert "tautline board|issue|debt" in res.stderr


# --------------------------------------------------------------------------- the argv/shim surface


def test_argv_mode_mirrors_the_hook_predicate(run_cli, tmp_path):
    root = _lane(tmp_path, builder=True)
    denied = run_cli(
        "builder-guard", "--argv", "--target", str(root), "--", "gh", "issue", "create", cwd=root
    )
    assert denied.returncode == 2, (denied.stdout, denied.stderr)
    assert "tautline board|issue|debt" in denied.stderr
    allowed = run_cli(
        "builder-guard", "--argv", "--target", str(root), "--", "gh", "pr", "list", cwd=root
    )
    assert allowed.returncode == 0, allowed.stderr


def test_argv_mode_does_not_re_split_a_quoted_argument_into_shell_syntax(run_cli, tmp_path):
    """The argv is already split by the caller's shell, so joining it back has to re-quote --
    otherwise a PR body that merely MENTIONS `gh issue create` denies a legitimate `gh pr create`.
    """
    root = _lane(tmp_path, builder=True)
    res = run_cli(
        "builder-guard",
        "--argv",
        "--target",
        str(root),
        "--",
        "gh",
        "pr",
        "create",
        "--body",
        "do not use gh issue create; use tautline issue",
        cwd=root,
    )
    assert res.returncode == 0, (res.stdout, res.stderr)


def test_the_shim_lets_allowed_gh_through_to_the_real_binary_and_stops_the_rest(tmp_path):
    """End-to-end for the non-Claude lanes (Codex and friends): the shim dir goes first on PATH,
    an allowed command must reach the REAL `gh`, and a denied one must never start it."""
    root = _lane(tmp_path, builder=True)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    config = home / ".config" / "minervit" / "builder-shim"

    real_bin = tmp_path / "realbin"
    real_bin.mkdir()
    receipt = tmp_path / "real-gh-ran.txt"
    fake_gh = real_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + json.dumps(str(receipt)) + "\nexit 0\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    tautline_dir = tmp_path / "tautbin"
    tautline_dir.mkdir()
    shim_tautline = tautline_dir / "tautline"
    shim_tautline.write_text(
        f'#!/bin/sh\nexec {json.dumps(sys.executable)} {json.dumps(str(CLI_PATH))} "$@"\n',
        encoding="utf-8",
    )
    shim_tautline.chmod(0o755)

    base_env = {
        "PATH": f"{tautline_dir}:{real_bin}:{os.environ['PATH']}",
        "HOME": str(home),
    }
    made = subprocess.run(
        [sys.executable, str(CLI_PATH), "builder-guard", "--shim-dir"],
        env=base_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert made.returncode == 0, made.stderr
    shim_dir = Path(made.stdout.strip())
    assert shim_dir == config
    gh_shim = shim_dir / "gh"
    assert gh_shim.is_file()
    assert stat.S_IMODE(gh_shim.stat().st_mode) == 0o755
    # Idempotent: a second call must not fail or produce a different directory.
    again = subprocess.run(
        [sys.executable, str(CLI_PATH), "builder-guard", "--shim-dir"],
        env=base_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert again.stdout.strip() == made.stdout.strip()

    shim_env = dict(base_env, PATH=f"{shim_dir}:{base_env['PATH']}")
    denied = subprocess.run(
        ["gh", "issue", "create", "--title", "x"],
        env=shim_env,
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert denied.returncode == 2, (denied.stdout, denied.stderr)
    assert "tautline board|issue|debt" in denied.stderr
    assert not receipt.exists(), "the real gh must never be started for a denied command"

    allowed = subprocess.run(
        ["gh", "pr", "view", "12"],
        env=shim_env,
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)
    assert receipt.exists(), "an allowed command must reach the real gh"
    assert "pr view 12" in receipt.read_text(encoding="utf-8")


# --------------------------------------------- the shim's version skew, the hook's defect again
#
# THE DEFECT THESE PIN. The hook command learned to tell "the verb denied" from "the verb does not
# exist" (see the four tests at the bottom of this file); the shim did not. It read ANY exit 2 from
# `tautline builder-guard --argv` as a deny, and an installed `tautline` older than the verb
# answers argparse's "invalid choice" with exit 2 for every argv. A human with the shim on PATH --
# which the docs tell an operator to leave there -- and an older CLI therefore had `gh` BRICKED:
# every invocation exit 2, with argparse noise on stderr, on a machine whose guard is supposed to
# be invisible to them. The shim now mirrors the hook: probe `--help`, and only a CLI that answers
# it is a CLI whose 2 means deny.


def _fake_shim_lane(tmp_path: Path, tautline_body: str) -> tuple[dict, Path, Path]:
    """A generated `gh` shim in front of a fake real `gh`, with a FAKE `tautline` on PATH.

    Returns the environment, the receipt the real `gh` writes when it runs, and the lane root.
    The tautline is fake because the fact under test is a CLI VERSION this tree cannot contain:
    one that does not have the `builder-guard` verb at all.
    """
    root = _lane(tmp_path, builder=True)
    shim_dir = bg.ensure_shim_dir(tmp_path / "shim")

    real_bin = tmp_path / "realbin"
    real_bin.mkdir(exist_ok=True)
    receipt = tmp_path / "real-gh-ran.txt"
    real_gh = real_bin / "gh"
    real_gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + json.dumps(str(receipt)) + "\nexit 0\n",
        encoding="utf-8",
    )
    real_gh.chmod(0o755)

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(exist_ok=True)
    fake = fake_bin / "tautline"
    fake.write_text(f"#!/bin/sh\n{tautline_body}\n", encoding="utf-8")
    fake.chmod(0o755)

    env = {"PATH": f"{shim_dir}:{fake_bin}:{real_bin}", "HOME": str(tmp_path / "home")}
    return env, receipt, root


def _run_shim(env: dict, root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *argv], env=env, cwd=str(root), text=True, capture_output=True, timeout=60
    )


def test_the_shim_runs_the_real_gh_when_the_installed_cli_predates_the_verb(tmp_path):
    """A human's `gh`, unbricked. An old CLI exits 2 for EVERY argv, `--help` included, so the
    probe answers "this 2 is not a deny" and the shim gets out of the way -- silently, because
    argparse's "invalid choice" on every `gh` call is friction a human would rightly complain
    about."""
    env, receipt, root = _fake_shim_lane(
        tmp_path,
        "echo \"tautline: error: argument command: invalid choice: 'builder-guard'\" >&2\nexit 2",
    )
    result = _run_shim(env, root, "issue", "create", "--title", "x")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout == "", result.stdout
    assert result.stderr == "", result.stderr
    assert receipt.exists(), "the real gh must run when the 2 was version skew, not a deny"


def test_the_shim_still_denies_when_the_cli_has_the_verb_and_said_deny(tmp_path):
    """The other direction: a fail-open that also fails open on a REAL deny is a deletion."""
    env, receipt, root = _fake_shim_lane(
        tmp_path,
        'case "$2" in --help) exit 0 ;; esac\n'
        'echo "Builder lanes reach issues and the board only through '
        '\\`tautline board|issue|debt\\`. Denied: gh issue create" >&2\n'
        "exit 2",
    )
    result = _run_shim(env, root, "issue", "create", "--title", "x")
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "tautline board|issue|debt" in result.stderr
    assert not receipt.exists(), "the real gh must never be started for a denied command"


def test_the_shim_never_recurses_into_itself_when_no_real_gh_exists(tmp_path):
    root = _lane(tmp_path, builder=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    tautline_dir = tmp_path / "tautbin"
    tautline_dir.mkdir()
    shim_tautline = tautline_dir / "tautline"
    shim_tautline.write_text(
        f'#!/bin/sh\nexec {json.dumps(sys.executable)} {json.dumps(str(CLI_PATH))} "$@"\n',
        encoding="utf-8",
    )
    shim_tautline.chmod(0o755)
    env = {"PATH": str(tautline_dir), "HOME": str(home)}
    made = subprocess.run(
        [sys.executable, str(CLI_PATH), "builder-guard", "--shim-dir"],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert made.returncode == 0, made.stderr
    shim_dir = made.stdout.strip()
    res = subprocess.run(
        ["gh", "pr", "list"],
        env=dict(env, PATH=f"{shim_dir}:{env['PATH']}"),
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert res.returncode == 127, (res.returncode, res.stdout, res.stderr)
    assert "not found" in res.stderr


# --------------------------------------------------------------------------- the control pays rent


def test_a_denial_is_recorded_in_the_event_log_and_named_by_the_report(run_cli, tmp_path):
    """CLAUDE.md: every control pays rent -- it names the real defects it caught, or it goes.

    `--report` is where the guard produces that evidence, so a denial that left no trace would
    make the whole control unfalsifiable.
    """
    root = _lane(tmp_path, builder=True)
    blocked = run_cli(
        "builder-guard", "--hook", stdin=_payload(root, "gh project item-edit --id ITEM"), cwd=root
    )
    assert blocked.returncode == 2

    report = run_cli("builder-guard", "--report", "--target", str(root), cwd=root)
    assert report.returncode == 0, report.stderr
    assert "builder_guard_denials: 1" in report.stdout
    assert "gh project item-edit" in report.stdout


def test_the_report_on_a_clean_lane_says_zero_rather_than_nothing(run_cli, tmp_path):
    root = _lane(tmp_path, builder=True)
    report = run_cli("builder-guard", "--report", "--target", str(root), cwd=root)
    assert report.returncode == 0, report.stderr
    assert "builder_guard_denials: 0" in report.stdout


def test_the_recorded_command_is_bounded_so_one_denial_cannot_fill_the_ledger(run_cli, tmp_path):
    root = _lane(tmp_path, builder=True)
    long_command = "gh issue create --body " + ("x" * 4000)
    blocked = run_cli("builder-guard", "--hook", stdin=_payload(root, long_command), cwd=root)
    assert blocked.returncode == 2
    assert bg.EVENT_COMMAND_MAX_CHARS == 500
    jsonl = next(
        (tmp_path / "home" / ".local" / "state" / "minervit" / "repo-events").rglob("events.jsonl")
    )
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line]
    denials = [row for row in rows if row.get("event") == bg.DENIAL_EVENT]
    assert len(denials) == 1
    assert len(denials[0]["refs"]["command"]) <= bg.EVENT_COMMAND_MAX_CHARS


# --------------------------------------------------------------------------- the hook registration


def test_the_pretooluse_bash_hook_is_registered_and_degrades_to_a_no_op_without_the_cli():
    settings = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    entries = [
        entry for entry in settings["hooks"].get("PreToolUse", []) if entry.get("matcher") == "Bash"
    ]
    assert entries, "the guard ships no PreToolUse Bash hook; nothing enforces it in session"
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    guard = [command for command in commands if "builder-guard --hook" in command]
    assert len(guard) == 1, commands
    # A machine without `tautline` on PATH must exit 0, not 2: a PreToolUse exit 2 is a DENY, so a
    # partial install would otherwise reject every Bash call the harness makes.
    assert "command -v tautline" in guard[0]
    assert "exit 0" in guard[0]
    # ...and an INSTALLED tautline that predates the verb must exit 0 too. See the four behavioural
    # tests below, which run this exact string; these string assertions only prove the shape is
    # still the fail-open one, they do not prove it behaves.
    assert "builder-guard --help" in guard[0]


# ------------------------------------------------------- the hook command, run as a shell string

# The hook command is a shell one-liner shipped in JSON, which means NOTHING type-checks it and
# nothing above runs it. These four tests do: they take the string out of hooks.json, run it under
# /bin/sh with a FAKE `tautline` on PATH, and assert the exit code the harness would read.
#
# THE DEFECT THEY PIN. The first cut was
#   `if command -v tautline >/dev/null 2>&1; then exec tautline builder-guard --hook; fi; exit 0`
# which is fail-open only for a machine with NO tautline. A machine with an INSTALLED tautline
# older than the `builder-guard` verb is the common case during a rollback or a staged upgrade, and
# there argparse exits 2 for "invalid choice" -- indistinguishable, to a PreToolUse harness, from a
# deny. Every Bash call on that machine would have been blocked, for HUMANS as well as builders,
# by a guard whose entire premise is that humans never notice it.
#
# The fix probes `builder-guard --help` to tell "the verb denied" from "the verb does not exist",
# and it probes ONLY after a 2, so the allow path -- every Bash call in every session -- still
# costs exactly one process.


def _hook_shell_argv() -> list[str]:
    """The PreToolUse Bash command as shipped, split for `subprocess`. No copy of the string here:
    a test that re-types the command tests the copy, not the thing that ships."""
    settings = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in settings["hooks"].get("PreToolUse", [])
        if entry.get("matcher") == "Bash"
        for hook in entry["hooks"]
        if "builder-guard --hook" in hook["command"]
    ]
    assert len(commands) == 1, commands
    return shlex.split(commands[0])


def _fake_cli(tmp_path: Path, body: str) -> tuple[dict, Path]:
    """A fake `tautline` FIRST on PATH, plus the file recording its invocations.

    First rather than alone: `command -v tautline` must resolve to this script and never to a real
    installation, which ordering guarantees, and the count of recorded invocations is what proves
    the allow path does not pay for the probe. The rest of PATH is the standard binary directories
    because the hook command uses `cat` and `rm` to move the guard's captured stderr around -- the
    PATH a harness actually runs a hook with. The no-tautline case below keeps a genuinely empty
    PATH, and exits before either of those is reached.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "invocations.txt"
    fake = bin_dir / "tautline"
    fake.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> {shlex.quote(str(log))}\n{body}\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin"}, log


def _run_hook_command(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        _hook_shell_argv(),
        env=env,
        input=_payload(Path("/nonexistent"), "gh issue create --title x"),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _invocations(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_the_hook_command_exits_zero_when_the_installed_cli_predates_the_verb(tmp_path):
    """THE ROLLBACK CASE, and the reason this fix exists.

    An old `tautline` answers argparse's "invalid choice: 'builder-guard'" with exit 2 for EVERY
    argv, `--help` included. Exit 2 is a PreToolUse DENY, so without the probe this machine blocks
    every Bash call -- for the product director and the operator too, who are the people this guard
    is built never to touch.
    """
    env, log = _fake_cli(
        tmp_path,
        "echo \"tautline: error: argument command: invalid choice: 'builder-guard'\" >&2\nexit 2",
    )
    result = _run_hook_command(env)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    # Two invocations: the hook attempt, then the probe that disambiguated its 2.
    assert _invocations(log) == ["builder-guard --hook", "builder-guard --help"]
    # ...and NOTHING on either stream. An old CLI's argparse noise on every Bash call is friction
    # a human notices, from a control whose entire premise is that they never do -- so the hook
    # command captures both of the guard's streams and replays them only on a confirmed deny.
    assert result.stdout == "", result.stdout
    assert result.stderr == "", result.stderr


def test_the_hook_command_leaves_no_temp_file_behind(tmp_path):
    """The captured stderr goes through a file, because the alternative -- running the guard a
    second time to replay its output -- would record the denial in the event log twice and make
    the ledger's own count wrong. A file per Bash call has to clean up after itself."""
    env, _log = _fake_cli(tmp_path, "exit 2")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _run_hook_command(dict(env, TMPDIR=str(scratch)))
    assert list(scratch.iterdir()) == [], "the hook left a file behind on every Bash call"


def test_the_hook_command_still_denies_when_the_verb_exists_and_said_deny(tmp_path):
    """The other direction, which is the whole point of the guard: a fail-open that also fails
    open on a REAL deny is not a fix, it is a deletion."""
    env, log = _fake_cli(
        tmp_path,
        'case "$1 $2" in "builder-guard --help") exit 0 ;; esac\n'
        'echo \'{"hookSpecificOutput": {"permissionDecision": "deny"}}\'\n'
        'echo "Builder lanes reach issues and the board only through tautline board|issue|debt" '
        ">&2\n"
        "exit 2",
    )
    result = _run_hook_command(env)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert _invocations(log) == ["builder-guard --hook", "builder-guard --help"]
    # BOTH channels survive the capture. The JSON is what a harness parses; the reason is what a
    # model reads and acts on. Dropping either one makes the deny land as an unexplained failure.
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "tautline board|issue|debt" in result.stderr


def test_the_allow_path_costs_exactly_one_process(tmp_path):
    """Every Bash call in every session runs this. The probe must be on the DENY path only."""
    env, log = _fake_cli(tmp_path, "exit 0")
    result = _run_hook_command(env)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert _invocations(log) == ["builder-guard --hook"]


def test_the_hook_command_exits_zero_with_no_tautline_on_path(tmp_path):
    """The case the first cut already handled, asserted behaviourally rather than by substring."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    result = _run_hook_command({"PATH": str(empty)})
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
