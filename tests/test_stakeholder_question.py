"""`stakeholder-question ask|list` -- Tier 1 salvage, track S2.

Salvaged from the pre-demolition `stakeholder-question-ask`/`-status` handlers. DROPPED ENTIRELY,
per the salvage spec: the Project-status sync, `--strict`, and any board/label coupling -- there is
no project-adapter dependency anywhere in this module.

Every remote call is served at the SOCKET boundary (`urlopen`/`OpenerDirector.open`), the same seam
`tests/test_backlog_providers.py` uses for `GitHubBacklog`, so the assertions read the real request
this module's transport builds rather than the transport agreeing with itself. The autouse
`_no_outbound_network` guard in conftest.py is the backstop under all of it.
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tautline_methodology import stakeholder_question as sq

GH_TOKEN = "ghp_NOT_A_REAL_TOKEN_0123456789"


# ================================================================================================
# a fake transport, at the socket boundary (mirrors test_backlog_providers.py's FakeHttp)
# ================================================================================================


class _Response(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(b"" if payload is None else json.dumps(payload).encode("utf-8"))
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    def __init__(self):
        self.routes: dict[str, list] = {}
        self.errors: dict[str, urllib.error.HTTPError] = {}
        self.calls: list[dict] = []

    def route(self, key, payload, headers=None):
        self.routes.setdefault(key, []).append((payload, headers or {}))
        return self

    def fail(self, key, code, body=None, headers=None):
        raw = b"{}" if body is None else json.dumps(body).encode("utf-8")
        self.errors[key] = urllib.error.HTTPError(key, code, "boom", headers or {}, io.BytesIO(raw))
        return self

    def handle(self, request, timeout=None):
        url = request.full_url
        method = request.get_method()
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        bare = path.split("?", 1)[0]
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.calls.append(
            {
                "method": method,
                "url": url,
                "path": bare,
                "query": path[len(bare) + 1 :] if "?" in path else "",
                "body": body,
                "headers": dict(request.headers),
            }
        )
        key = f"{method} {bare}"
        if key in self.errors:
            raise self.errors[key]
        queued = self.routes.get(key)
        if not queued:
            raise AssertionError(f"no recorded response for {key!r}; recorded: {sorted(self.routes)}")
        payload, headers = queued.pop(0) if len(queued) > 1 else queued[0]
        return _Response(payload, headers)


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    fake = FakeHttp()

    def _urlopen(request, *args, **kwargs):
        return fake.handle(request, kwargs.get("timeout"))

    def _open(self, request, *args, **kwargs):
        return fake.handle(request, kwargs.get("timeout"))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _open)
    return fake


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", GH_TOKEN)
    monkeypatch.delenv("GH_TOKEN", raising=False)


def _comment(number, body, *, login="octocat", created_at="2026-08-29T00:00:00Z"):
    return {
        "id": number,
        "body": body,
        "html_url": f"https://github.com/acme/widgets/issues/1#issuecomment-{number}",
        "created_at": created_at,
        "user": {"login": login},
    }


def _ns(**overrides) -> argparse.Namespace:
    base = {
        "action": "list",
        "issue": "1",
        "repo": "acme/widgets",
        "question": None,
        "why": None,
        "needed_for": None,
        "stakeholder": None,
        "question_id": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


# --- markers: build/parse, legacy prefix, sanitization at the extraction boundary ---------------


def test_marker_round_trips_through_parse():
    marker = sq.build_marker(question_id="abc-123", stakeholder="@alice", asked_at="2026-08-29T00:00:00Z")
    parsed = sq.parse_markers(f"hi {marker} there")
    assert parsed == [{"id": "abc-123", "stakeholder": "@alice", "asked_at": "2026-08-29T00:00:00Z"}]


def test_legacy_minervit_prefix_is_still_parsed():
    assert sq.parse_markers('<!-- minervit-question id="legacy-1" -->') == [{"id": "legacy-1"}]


def test_marker_with_no_id_is_not_a_question():
    assert sq.parse_markers('<!-- tautline-question stakeholder="@alice" -->') == []


def test_parse_markers_sanitizes_control_characters_in_attribute_values():
    """A hostile or corrupted comment can carry a marker whose attribute value contains a control
    character (e.g. to forge a fake terminal line). `list` must never print it raw."""
    marker = '<!-- tautline-question id="abc\x1b[2Kinjected" stakeholder="@alice" -->'
    parsed = sq.parse_markers(marker)
    assert parsed
    assert "\x1b" not in parsed[0]["id"]


def test_question_id_is_deterministic_and_slugged():
    a = sq.question_id("7", "What DB do we use?", "the migration script")
    b = sq.question_id("7", "What DB do we use?", "the migration script")
    assert a == b
    assert a.startswith("the-migration-script-")


# --- resolve_issue_ref: the --repo/--issue safety net that replaces the old adapter-repo check ---


def test_bare_number_with_repo_resolves():
    assert sq.resolve_issue_ref("42", "acme/widgets") == ("acme/widgets", "42")


def test_url_alone_resolves():
    assert sq.resolve_issue_ref("https://github.com/acme/widgets/issues/7", None) == ("acme/widgets", "7")


def test_pull_url_resolves():
    assert sq.resolve_issue_ref("https://github.com/acme/widgets/pull/9", None) == ("acme/widgets", "9")


def test_url_and_agreeing_repo_resolves():
    assert sq.resolve_issue_ref("https://github.com/acme/widgets/issues/7", "acme/widgets") == (
        "acme/widgets",
        "7",
    )


def test_url_and_conflicting_repo_is_refused():
    with pytest.raises(sq.StakeholderQuestionError, match="acme/widgets.*acme/other"):
        sq.resolve_issue_ref("https://github.com/acme/widgets/issues/7", "acme/other")


def test_bare_number_without_repo_is_refused():
    with pytest.raises(sq.StakeholderQuestionError, match="--repo owner/name is required"):
        sq.resolve_issue_ref("42", None)


def test_malformed_repo_flag_is_refused():
    with pytest.raises(sq.StakeholderQuestionError, match="--repo must be owner/name"):
        sq.resolve_issue_ref("42", "not a repo")


def test_non_github_host_url_does_not_resolve_a_repo():
    """A lookalike host must not be treated as naming a repository at all -- and with no --repo,
    that means refused for lack of one, not silently trusted."""
    with pytest.raises(sq.StakeholderQuestionError, match="--repo owner/name is required"):
        sq.resolve_issue_ref("https://evilgithub.com/acme/widgets/issues/7", None)


def test_host_substring_bypass_does_not_resolve_a_repo():
    with pytest.raises(sq.StakeholderQuestionError, match="--repo owner/name is required"):
        sq.resolve_issue_ref("https://evil.example/github.com/acme/widgets/issues/7", None)


def test_blank_issue_is_refused():
    with pytest.raises(sq.StakeholderQuestionError, match="--issue is required"):
        sq.resolve_issue_ref("", "acme/widgets")


# --- question_records: the answered/open positional heuristic -----------------------------------


def test_open_question_with_no_later_comment():
    marker = sq.build_marker(question_id="q1", stakeholder="@alice", asked_at="t0")
    comments = [_comment(1, f"question\n{marker}", login="agent")]
    records = sq.question_records(comments)
    assert len(records) == 1
    assert records[0]["status"] == "open"


def test_reply_from_a_different_author_marks_answered():
    marker = sq.build_marker(question_id="q1", stakeholder="@alice", asked_at="t0")
    comments = [
        _comment(1, f"question\n{marker}", login="agent"),
        _comment(2, "here's the answer", login="alice"),
    ]
    records = sq.question_records(comments)
    assert records[0]["status"] == "answered"
    assert records[0]["reply_author"] == "alice"


def test_a_follow_up_from_the_same_author_does_not_count_as_an_answer():
    """The asker's own second comment (e.g. a clarifying addendum) must not mark its own question
    answered -- that is precisely the false positive the author-inequality check exists to avoid."""
    marker = sq.build_marker(question_id="q1", stakeholder="@alice", asked_at="t0")
    comments = [
        _comment(1, f"question\n{marker}", login="agent"),
        _comment(2, "actually one more detail", login="agent"),
    ]
    records = sq.question_records(comments)
    assert records[0]["status"] == "open"


def test_a_second_question_by_the_same_author_does_not_answer_the_first():
    marker1 = sq.build_marker(question_id="q1", stakeholder="@alice", asked_at="t0")
    marker2 = sq.build_marker(question_id="q2", stakeholder="@alice", asked_at="t1")
    comments = [
        _comment(1, f"question one\n{marker1}", login="agent"),
        _comment(2, f"question two\n{marker2}", login="agent"),
    ]
    records = sq.question_records(comments)
    assert {r["id"]: r["status"] for r in records} == {"q1": "open", "q2": "open"}


def test_reply_between_two_questions_only_answers_the_earlier_one():
    marker1 = sq.build_marker(question_id="q1", stakeholder="@alice", asked_at="t0")
    marker2 = sq.build_marker(question_id="q2", stakeholder="@bob", asked_at="t1")
    comments = [
        _comment(1, f"question one\n{marker1}", login="agent"),
        _comment(2, "answer to one", login="alice"),
        _comment(3, f"question two\n{marker2}", login="agent"),
    ]
    records = sq.question_records(comments)
    by_id = {r["id"]: r for r in records}
    assert by_id["q1"]["status"] == "answered"
    # q2 has no comment after it at all.
    assert by_id["q2"]["status"] == "open"


def test_no_markers_yields_no_records():
    assert sq.question_records([_comment(1, "just chatting", login="someone")]) == []


# --- transport: pagination (Link header, per_page pinned), sanitized remote text ----------------


def test_list_comments_pins_per_page_and_follows_link_pagination(http, github_env):
    key = "GET /repos/acme/widgets/issues/1/comments"
    http.route(
        key,
        [_comment(1, "first page")],
        headers={"link": '<https://api.github.com/repos/acme/widgets/issues/1/comments?page=2>; rel="next"'},
    )
    http.route(key, [_comment(2, "second page")], headers={})
    client = sq._GitHubCommentClient(repo="acme/widgets")
    comments = client.list_comments("1")
    assert [c["id"] for c in comments] == [1, 2]
    first_call = http.calls[0]
    assert first_call["path"] == "/repos/acme/widgets/issues/1/comments"
    assert "per_page=100" in urllib.parse.unquote_plus(first_call["query"])
    assert len(http.calls) == 2


def test_list_comments_bounds_pagination(http, github_env, monkeypatch):
    """A server that never stops offering a next page costs a FINITE number of requests."""
    monkeypatch.setattr(sq, "MAX_PAGES", 3)
    key = "GET /repos/acme/widgets/issues/1/comments"
    # A single queued response that keeps pointing at itself as "next": FakeHttp repeats the last
    # entry once its queue is down to one, which is exactly the "never stops offering a page" case.
    http.route(key, [_comment(1, "page")], headers={"link": f'<{sq.GITHUB_API}{key.split(" ", 1)[1]}?page=2>; rel="next"'})
    client = sq._GitHubCommentClient(repo="acme/widgets")
    with pytest.raises(sq.StakeholderQuestionError, match="kept offering another page"):
        client.list_comments("1")
    assert len(http.calls) == 3


def test_post_comment_sends_body_and_returns_created_comment(http, github_env):
    created = _comment(99, "posted body", login="bot")
    http.route("POST /repos/acme/widgets/issues/1/comments", created)
    client = sq._GitHubCommentClient(repo="acme/widgets")
    result = client.post_comment("1", "posted body")
    assert result == created
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["body"] == {"body": "posted body"}
    assert call["headers"].get("Authorization") == f"Bearer {GH_TOKEN}"


# Redirect refusal is proven by the class-level census in test_backlog_providers.py
# (`test_every_discovered_http_transport_refuses_redirects`), which walks every transport with a
# `_build_opener` -- `stakeholder_question._GitHubCommentClient` included as of this module -- and
# asserts it behaviourally refuses a 302. A second, narrower copy of that check here would be a
# second thing to keep in step with the real one rather than added protection.


def test_no_credentials_refuses_with_actionable_message(http, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    import tautline_methodology.backlog as backlog_mod

    monkeypatch.setattr(backlog_mod, "_gh_auth_token", lambda: "")
    client = sq._GitHubCommentClient(repo="acme/widgets")
    with pytest.raises(sq.StakeholderQuestionError, match="GITHUB_TOKEN"):
        client.list_comments("1")
    assert http.calls == []  # refused before any request was made


def test_error_response_redacts_the_token(http, github_env):
    http.fail("GET /repos/acme/widgets/issues/1/comments", 404, {"message": "Not Found"})
    client = sq._GitHubCommentClient(repo="acme/widgets")
    with pytest.raises(sq.StakeholderQuestionError) as excinfo:
        client.list_comments("1")
    assert GH_TOKEN not in str(excinfo.value)
    assert "404" in str(excinfo.value)


# --- ask: secret-scan refusal BEFORE posting, dedupe, end-to-end ---------------------------------


def test_ask_refuses_a_secret_looking_question_before_posting(http, github_env, capsys):
    args = _ns(action="ask", question="the token is ghp_" + "x" * 36)
    code = sq.stakeholder_question_command(args)
    assert code == 1
    assert "stakeholder_question_error:" in capsys.readouterr().out
    # The refusal fires from the whole-body scan, before ANY network call -- not just the POST,
    # the dedupe GET too. No route is registered for either, so a call of either kind would raise
    # inside FakeHttp rather than merely fail this assertion.
    assert http.calls == []


def test_ask_refuses_a_secret_looking_stakeholder_before_posting(http, github_env, capsys):
    """The bug this guards: an earlier version scanned only question/why/needed_for, so a secret
    smuggled through --stakeholder flowed straight into the @-mention line and the marker's
    stakeholder= attribute -- both part of the POSTED body -- with no refusal at all."""
    args = _ns(action="ask", question="What database do we use?", stakeholder="ghp_" + "x" * 36)
    code = sq.stakeholder_question_command(args)
    assert code == 1
    out = capsys.readouterr().out
    assert "stakeholder_question_error:" in out
    assert "ghp_" not in out  # the refusal names the finding class, not the match
    assert http.calls == []


def test_ask_refuses_a_secret_looking_question_id_before_posting(http, github_env, capsys):
    """Same class of bug, via --question-id -> the marker's id= attribute."""
    args = _ns(action="ask", question="What database do we use?", question_id="ghp_" + "x" * 36)
    code = sq.stakeholder_question_command(args)
    assert code == 1
    out = capsys.readouterr().out
    assert "stakeholder_question_error:" in out
    assert "ghp_" not in out
    assert http.calls == []


def test_ask_posts_a_tagged_comment(http, github_env, capsys):
    key = "GET /repos/acme/widgets/issues/1/comments"
    http.route(key, [])  # dedupe check: nothing posted yet
    created = _comment(5, "posted", login="bot")
    http.route("POST /repos/acme/widgets/issues/1/comments", created)
    args = _ns(action="ask", question="What database do we use?", why="blocks the migration", needed_for="the schema PR", stakeholder="alice")
    code = sq.stakeholder_question_command(args)
    assert code == 0
    out = capsys.readouterr().out
    assert "stakeholder_question_ask: posted" in out
    post_call = next(c for c in http.calls if c["method"] == "POST")
    body = post_call["body"]["body"]
    assert "@alice" in body
    assert "What database do we use?" in body
    assert "blocks the migration" in body
    assert "the schema PR" in body
    assert "tautline-question" in body
    # The post-verify GET ran (dedupe + verify = 2 GETs) and found only the one comment this
    # FakeHttp route ever serves, so no race warning fires on the ordinary, uncontended path.
    assert [c["method"] for c in http.calls] == ["GET", "POST", "GET"]
    assert "stakeholder_question_race_warning" not in out


def test_ask_warns_on_concurrent_duplicate_after_posting(http, github_env, capsys):
    """No server-side lock stops two concurrent `ask` calls from both passing the dedupe GET
    before either has posted. The honest fix is a re-read AFTER posting: this simulates that race
    by having the SECOND GET (the post-verify) return two comments already carrying this id."""
    key = "GET /repos/acme/widgets/issues/1/comments"
    http.route(key, [])  # dedupe check: this process sees nothing yet
    http.route("POST /repos/acme/widgets/issues/1/comments", _comment(5, "posted", login="bot"))
    dup_a = _comment(5, sq.build_marker(question_id="same-id", stakeholder="", asked_at="t0"), login="bot")
    dup_b = _comment(6, sq.build_marker(question_id="same-id", stakeholder="", asked_at="t1"), login="bot")
    http.route(key, [dup_a, dup_b])  # post-verify: a concurrent `ask` won the race
    args = _ns(action="ask", question="What database do we use?", question_id="same-id")
    code = sq.stakeholder_question_command(args)
    assert code == 0  # the post itself succeeded; this is a warning, not a failure
    out = capsys.readouterr().out
    assert "stakeholder_question_ask: posted" in out
    assert "stakeholder_question_race_warning: 2 comments now carry id=same-id" in out
    assert dup_a["html_url"] in out
    assert dup_b["html_url"] in out


def test_ask_race_check_failure_is_reported_but_does_not_fail_the_command(http, github_env, capsys, monkeypatch):
    """The post-verify is best-effort: if IT fails, that is reported honestly (never silence,
    which would read as "no race detected" when the truth is "the check could not run"), and it
    never turns an already-successful post into a command failure."""
    http.route("GET /repos/acme/widgets/issues/1/comments", [])
    http.route("POST /repos/acme/widgets/issues/1/comments", _comment(5, "posted", login="bot"))
    real_list_comments = sq._GitHubCommentClient.list_comments
    calls = {"n": 0}

    def flaky_list_comments(self, issue_number):
        calls["n"] += 1
        if calls["n"] > 1:  # the dedupe GET succeeds; only the post-verify GET fails
            raise sq.StakeholderQuestionError("simulated transient failure")
        return real_list_comments(self, issue_number)

    monkeypatch.setattr(sq._GitHubCommentClient, "list_comments", flaky_list_comments)
    args = _ns(action="ask", question="What database do we use?")
    code = sq.stakeholder_question_command(args)
    assert code == 0
    out = capsys.readouterr().out
    assert "stakeholder_question_ask: posted" in out
    assert "stakeholder_question_race_check: unavailable - simulated transient failure" in out


def test_ask_with_no_stakeholder_posts_without_a_mention(http, github_env):
    http.route("GET /repos/acme/widgets/issues/1/comments", [])
    http.route("POST /repos/acme/widgets/issues/1/comments", _comment(5, "posted"))
    args = _ns(action="ask", question="What database do we use?")
    assert sq.stakeholder_question_command(args) == 0
    body = next(c for c in http.calls if c["method"] == "POST")["body"]["body"]
    assert "@" not in body.split("Question:")[0]


def test_ask_requires_a_question(http, github_env, capsys):
    args = _ns(action="ask", question="   ")
    code = sq.stakeholder_question_command(args)
    assert code == 1
    assert "--question is required" in capsys.readouterr().out


def test_ask_is_idempotent_on_the_same_question_id(http, github_env, capsys):
    """Reposting the same tag is a no-op: the existing marker is found and nothing new is sent."""
    marker = sq.build_marker(question_id="same-id", stakeholder="", asked_at="t0")
    http.route(
        "GET /repos/acme/widgets/issues/1/comments",
        [_comment(1, f"already asked\n{marker}", login="bot")],
    )
    args = _ns(action="ask", question="What database do we use?", question_id="same-id")
    code = sq.stakeholder_question_command(args)
    assert code == 0
    assert "already-present" in capsys.readouterr().out
    assert [c["method"] for c in http.calls] == ["GET"]  # no POST


# --- list: end-to-end reporting ------------------------------------------------------------------


def test_list_reports_open_and_answered_counts(http, github_env, capsys):
    open_marker = sq.build_marker(question_id="open-1", stakeholder="@alice", asked_at="t0")
    answered_marker = sq.build_marker(question_id="answered-1", stakeholder="@bob", asked_at="t0")
    http.route(
        "GET /repos/acme/widgets/issues/1/comments",
        [
            _comment(1, f"q1\n{answered_marker}", login="agent"),
            _comment(2, "here you go", login="bob"),
            _comment(3, f"q2\n{open_marker}", login="agent"),
        ],
    )
    args = _ns(action="list")
    code = sq.stakeholder_question_command(args)
    assert code == 0
    out = capsys.readouterr().out
    assert "stakeholder_question_answered: issue=1 id=answered-1" in out
    assert "stakeholder_question_open: issue=1 id=open-1" in out
    assert "stakeholder_question_open_count: 1" in out
    assert "stakeholder_question_answered_count: 1" in out
    # Inline, not just in --help: a caller piping this stdout never sees --help.
    assert "positional" in out and "not content-verified" in out


def test_list_with_no_tagged_questions_reports_zero(http, github_env, capsys):
    http.route("GET /repos/acme/widgets/issues/1/comments", [_comment(1, "unrelated chat", login="someone")])
    code = sq.stakeholder_question_command(_ns(action="list"))
    assert code == 0
    assert "no tagged questions found" in capsys.readouterr().out


def test_list_sanitizes_the_stakeholder_field_in_printed_output(http, github_env, capsys):
    marker = '<!-- tautline-question id="q1" stakeholder="@alice\x1b[2K" asked_at="t0" -->'
    http.route("GET /repos/acme/widgets/issues/1/comments", [_comment(1, f"q\n{marker}", login="agent")])
    code = sq.stakeholder_question_command(_ns(action="list"))
    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out


def test_list_unreachable_repo_is_a_clean_refusal_not_a_traceback(http, github_env, capsys):
    http.fail("GET /repos/acme/widgets/issues/1/comments", 404, {"message": "Not Found"})
    code = sq.stakeholder_question_command(_ns(action="list"))
    assert code == 1
    assert "stakeholder_question_error:" in capsys.readouterr().out


# --- dispatch wiring -------------------------------------------------------------------------


def test_cli_stakeholder_question_delegates_to_the_module(cli, http, github_env, capsys):
    http.route("GET /repos/acme/widgets/issues/1/comments", [])
    args = _ns(action="list")
    assert cli.stakeholder_question(args) == 0
