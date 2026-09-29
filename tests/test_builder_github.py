"""The builder lane's ENTIRE GitHub surface, served at the socket boundary.

Same discipline as `tests/test_backlog_providers.py`, and for the same reason: every remote test
here fakes `urllib.request.OpenerDirector.open`, not the module's own transport, so the assertions
read the URL, method, headers and body the verbs actually build. A test that stubs
`builder_github._Client._http` proves only that the module agrees with itself -- and this module's
whole risk surface is *what it sends*: which endpoint, with which credential, carrying which body.

The suite is organised around the laws these verbs exist to hold:

* the BOARD IS READ, never written -- the only writes that exist are an issue comment and a debt
  issue, and a debt issue that lands ON the board is an automation defect this command must SHOUT
  about rather than absorb;
* NO UNVERIFIED SUCCESS -- a posted comment is read back before its URL is printed, and a created
  debt issue's labels are read back before it is reported as filed;
* MISSING CONFIG REFUSES -- with the message that names the block to add, exit 1, no traceback;
* the CACHE IS AN OPTIMISATION -- a corrupt cache file is ignored, never fatal, and `--fresh`
  always goes to the network.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from tautline_methodology import backlog, builder, builder_github, lean
from tautline_methodology.jira_client import Secret

GH_TOKEN = "ghp_NOT_A_REAL_TOKEN_0123456789"
REPO = "example-org/example-saas"
OWNER = "example-org"
PROJECT_NUMBER = 5


# ================================================================================================
# a fake transport, at the socket boundary
# ================================================================================================


class _Response(io.BytesIO):
    def __init__(self, payload: object, headers: dict | None = None) -> None:
        super().__init__(b"" if payload is None else json.dumps(payload).encode("utf-8"))
        self.status = 200
        self.headers = headers or {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeHttp:
    """Recorded responses keyed by `METHOD /path`, plus every request that was made.

    A key holds a QUEUE of responses so a pager -- or a GraphQL endpoint answering an org query and
    then the user-owner retry -- can be served in order from one path; the last response repeats
    once the queue drains, which is what a read-back after a write needs.
    """

    def __init__(self) -> None:
        self.routes: dict[str, list] = {}
        self.errors: dict[str, urllib.error.HTTPError] = {}
        self.calls: list[dict] = []

    def route(self, key: str, payload: object, headers: dict | None = None) -> "FakeHttp":
        """`payload` may be a callable taking this recorder, for a response that must ECHO.

        GitHub returns the comment it actually stored, so a read-back served from a canned body
        would prove nothing about the write: the verification under test is precisely "does what
        came back match what went out?", and a fake that always answers "hello" makes that
        assertion vacuous.
        """
        self.routes.setdefault(key, []).append((payload, headers or {}))
        return self

    def fail(self, key: str, code: int, body: object = None) -> "FakeHttp":
        raw = b"{}" if body is None else json.dumps(body).encode("utf-8")
        self.errors[key] = urllib.error.HTTPError(key, code, "boom", {}, io.BytesIO(raw))
        return self

    def handle(self, request, timeout=None) -> _Response:
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
                "timeout": timeout,
            }
        )
        key = f"{method} {bare}"
        if key in self.errors:
            raise self.errors[key]
        queued = self.routes.get(key)
        if not queued:
            raise AssertionError(
                f"no recorded response for {key!r}; recorded: {sorted(self.routes)}"
            )
        payload, headers = queued.pop(0) if len(queued) > 1 else queued[0]
        return _Response(payload(self) if callable(payload) else payload, headers)

    def of(self, key: str) -> list[dict]:
        method, path = key.split(" ", 1)
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def graphql_bodies(self) -> list[dict]:
        return [c["body"] for c in self.of("POST /graphql")]


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    fake = FakeHttp()

    def _open(self, request, *args, **kwargs):  # OpenerDirector.open
        return fake.handle(request, kwargs.get("timeout", args[0] if args else None))

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _open)
    return fake


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", GH_TOKEN)
    monkeypatch.delenv("GH_TOKEN", raising=False)


# ================================================================================================
# fixtures: a lean target carrying a `builderGithub` block
# ================================================================================================


def lean_cfg(**builder_block) -> dict:
    block = {"owner": OWNER, "projectNumber": PROJECT_NUMBER}
    block.update(builder_block)
    return {
        "schemaVersion": "lean-1",
        "project": {"name": "Example SaaS", "repo": REPO},
        "integrationBranch": "main",
        "commands": {"test": "scripts/test.sh"},
        "builderGithub": block,
    }


@pytest.fixture
def target(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".tautline.json").write_text(json.dumps(lean_cfg()), encoding="utf-8")
    return root


def write_cfg(root, **builder_block) -> None:
    (root / ".tautline.json").write_text(json.dumps(lean_cfg(**builder_block)), encoding="utf-8")


# ================================================================================================
# board payload builders
# ================================================================================================


def field_value(name: str, value: str) -> dict:
    return {
        "__typename": "ProjectV2ItemFieldSingleSelectValue",
        "name": value,
        "field": {"name": name},
    }


def card(
    number: int,
    title: str,
    *,
    status: str = "In Progress",
    item_type: str = "Feature",
    labels=("area:api",),
    prs=(),
    sub=None,
    comments: int = 0,
    size: str = "",
) -> dict:
    values = [field_value("Status", status), field_value("Item Type", item_type)]
    if size:
        values.append(field_value("Size", size))
    return {
        "type": "ISSUE",
        "fieldValues": {"nodes": values},
        "content": {
            "__typename": "Issue",
            "number": number,
            "title": title,
            "url": f"https://github.com/{REPO}/issues/{number}",
            "state": "OPEN",
            "labels": {"nodes": [{"name": name} for name in labels]},
            "comments": {"totalCount": comments},
            "subIssuesSummary": (
                {"total": sub[0], "completed": sub[1]} if sub else {"total": 0, "completed": 0}
            ),
            "closedByPullRequestsReferences": {
                "totalCount": len(prs),
                "nodes": [
                    {"number": n, "url": f"https://github.com/{REPO}/pull/{n}", "state": "OPEN"}
                    for n in prs
                ],
            },
        },
    }


def project(cards, *, has_next=False, cursor=None, fields=None) -> dict:
    return {
        "number": PROJECT_NUMBER,
        "title": "Example Board",
        "url": f"https://github.com/orgs/{OWNER}/projects/{PROJECT_NUMBER}",
        "fields": {
            "nodes": fields
            or [
                {
                    "__typename": "ProjectV2SingleSelectField",
                    "name": "Status",
                    "options": [{"name": "Todo"}, {"name": "In Progress"}, {"name": "Done"}],
                },
                {
                    "__typename": "ProjectV2SingleSelectField",
                    "name": "Item Type",
                    "options": [{"name": "Feature"}, {"name": "Bug"}],
                },
                {"__typename": "ProjectV2Field", "name": "Title"},
            ]
        },
        "items": {
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
            "nodes": cards,
        },
    }


def org_board(cards, **kw) -> dict:
    return {"data": {"organization": {"projectV2": project(cards, **kw)}}}


def user_board(cards, **kw) -> dict:
    return {"data": {"user": {"projectV2": project(cards, **kw)}}}


ORG_MISS = {
    "data": {"organization": None},
    "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to an Organization."}],
}


def rest_issue(number: int, *, title="Do the thing", labels=("area:api",), state="open", body="B"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "labels": [{"name": name} for name in labels],
        "assignees": [{"login": "alice"}],
        "comments": 2,
    }


# ================================================================================================
# a runner: the REAL parser and dispatcher, so the CLI wiring is under test too
# ================================================================================================


@pytest.fixture
def run(cli, target, capsys):
    def _run(*argv, root=None):
        code = cli.main([*argv, "--target", str(root or target)])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def parse_json(out: str) -> dict:
    return json.loads(out)


# ================================================================================================
# board list
# ================================================================================================


def test_board_list_reads_the_project_over_graphql_with_a_bearer_token(http, github_env, run):
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    call = http.of("POST /graphql")[0]
    assert call["url"] == "https://api.github.com/graphql"
    assert call["headers"]["Authorization"] == f"Bearer {GH_TOKEN}"
    assert call["headers"]["Accept"] == "application/vnd.github+json"
    assert call["headers"]["X-github-api-version"] == "2022-11-28"
    assert call["body"]["variables"] == {
        "login": OWNER,
        "number": PROJECT_NUMBER,
        "cursor": None,
    }
    assert "organization(login:$login)" in call["body"]["query"]
    assert "orderBy:{field:POSITION,direction:ASC}" in call["body"]["query"]
    assert "12" in out and "Do the thing" in out and "In Progress" in out


def test_board_list_keeps_the_boards_own_position_order(http, github_env, run):
    http.route(
        "POST /graphql",
        org_board([card(30, "third"), card(10, "first"), card(20, "second")]),
    )
    _code, out, _err = run("board", "list")
    assert out.index("third") < out.index("first") < out.index("second")


def test_board_list_pages_the_items_connection_with_the_returned_cursor(http, github_env, run):
    http.route("POST /graphql", org_board([card(1, "one")], has_next=True, cursor="CUR"))
    http.route("POST /graphql", org_board([card(2, "two")]))
    _code, out, _err = run("board", "list")
    assert "one" in out and "two" in out
    assert [b["variables"]["cursor"] for b in http.graphql_bodies()] == [None, "CUR"]


def test_board_list_refuses_an_unbounded_pager(http, github_env, run):
    http.route("POST /graphql", org_board([card(1, "one")], has_next=True, cursor="CUR"))
    code, _out, err = run("board", "list")
    assert code == 1
    assert "page" in err.lower()
    assert len(http.of("POST /graphql")) == builder_github.MAX_PAGES


def test_board_list_falls_back_to_the_user_owner_when_the_org_query_is_null(http, github_env, run):
    http.route("POST /graphql", ORG_MISS)
    http.route("POST /graphql", user_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    queries = [b["query"] for b in http.graphql_bodies()]
    assert "organization(login:$login)" in queries[0]
    assert "user(login:$login)" in queries[1]
    assert "Do the thing" in out


def test_board_list_reports_graphql_errors_rather_than_an_empty_board(http, github_env, run):
    boom = {"data": None, "errors": [{"message": "Field 'projectV2' doesn't exist"}]}
    http.route("POST /graphql", boom)
    code, out, err = run("board", "list")
    assert code == 1
    assert "doesn't exist" in err
    # Both owner shapes were tried before giving up, and the failure is LOUD rather than "0 items".
    assert len(http.of("POST /graphql")) == 2
    assert "0 items" not in out + err


def test_board_list_hides_hidden_statuses_unless_asked(http, github_env, run):
    cards = [card(1, "open one"), card(2, "finished one", status="Done")]
    http.route("POST /graphql", org_board(cards))
    _code, out, _err = run("board", "list")
    assert "open one" in out and "finished one" not in out

    _code, out_all, _err = run("board", "list", "--all", "--fresh")
    assert "finished one" in out_all

    _code, out_named, _err = run("board", "list", "--status", "Done", "--fresh")
    assert "finished one" in out_named and "open one" not in out_named


def test_board_list_filters_by_type_label_and_text(http, github_env, run):
    cards = [
        card(1, "alpha widget", item_type="Feature", labels=("area:api",)),
        card(2, "beta gadget", item_type="Bug", labels=("area:ui",)),
    ]
    http.route("POST /graphql", org_board(cards))
    _code, out, _err = run("board", "list", "--type", "bug")
    assert "beta gadget" in out and "alpha widget" not in out
    _code, out, _err = run("board", "list", "--label", "AREA:API", "--fresh")
    assert "alpha widget" in out and "beta gadget" not in out
    _code, out, _err = run("board", "list", "--text", "GADGET", "--fresh")
    assert "beta gadget" in out and "alpha widget" not in out


def test_board_list_json_is_a_stable_envelope(http, github_env, run):
    http.route("POST /graphql", org_board([card(12, "Do the thing", prs=(20,), sub=(3, 2))]))
    _code, out, _err = run("board", "list", "--json")
    payload = parse_json(out)
    assert payload["verb"] == "board list"
    assert payload["repo"] == REPO
    assert payload["owner"] == OWNER
    assert payload["projectNumber"] == PROJECT_NUMBER
    item = payload["items"][0]
    assert item["number"] == 12
    assert item["status"] == "In Progress"
    assert item["type"] == "Feature"
    assert item["labels"] == ["area:api"]
    assert item["prCount"] == 1
    assert item["subIssues"] == {"total": 3, "completed": 2}


# ================================================================================================
# the board cache
# ================================================================================================


def test_the_board_read_is_cached_and_fresh_bypasses_it(http, github_env, run, target):
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    run("board", "list")
    assert len(http.of("POST /graphql")) == 1
    cache = target / builder_github.CACHE_PATH
    assert cache.is_file(), "the raw board payload is cached under .ai-work/"

    run("board", "list")
    assert len(http.of("POST /graphql")) == 1, "the second read came from the cache"

    run("board", "list", "--fresh")
    assert len(http.of("POST /graphql")) == 2, "--fresh always goes to the network"


def test_a_cache_for_a_different_board_is_not_reused(http, github_env, run, target):
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    run("board", "list")
    write_cfg(target, owner=OWNER, projectNumber=PROJECT_NUMBER + 1)
    run("board", "list")
    assert len(http.of("POST /graphql")) == 2


def test_a_stale_cache_is_refetched(http, github_env, run, target, monkeypatch):
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    run("board", "list")
    cache = target / builder_github.CACHE_PATH
    stored = json.loads(cache.read_text(encoding="utf-8"))
    stored["fetched_at"] -= builder_github.CACHE_TTL_SECONDS + 1
    cache.write_text(json.dumps(stored), encoding="utf-8")
    run("board", "list")
    assert len(http.of("POST /graphql")) == 2


def test_a_builder_acting_with_a_personal_token_says_so_once_on_stderr(
    http, github_env, run, target, monkeypatch
):
    """The security argument on this page is "a board write is refused by GITHUB, not by a hook",
    and it holds only when the lane is authenticated as the App. A builder lane with an exported
    GH_TOKEN -- the common shape on a machine with no App configured -- is authenticated as a
    PERSON, and every claim about Projects-read is then a claim about whatever that person's token
    happens to be scoped to.

    One line, on stderr so a `--json` envelope stays machine-readable, and once per process so it
    is a note rather than a per-request drumbeat. Nothing for a human: this says a BUILDER is not
    the bot, which is not a fact about a human's own session.
    """
    monkeypatch.setattr(builder_github, "_personal_token_noted", False)
    monkeypatch.setenv(builder.ROLE_ENV, builder.ROLE_BUILDER)
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, err = run("board", "list")
    assert code == 0, out
    assert "builder_note: acting with a personal token, not the builder App" in err
    assert err.count("builder_note:") == 1, err
    assert "builder_note:" not in out, "stdout stays the data channel"


def test_a_human_is_told_nothing_about_which_token_they_are_using(
    http, github_env, run, monkeypatch
):
    monkeypatch.setattr(builder_github, "_personal_token_noted", False)
    monkeypatch.delenv(builder.ROLE_ENV, raising=False)
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    _code, _out, err = run("board", "list")
    assert "builder_note:" not in err, err


def test_a_future_dated_cache_is_a_miss_rather_than_a_cache_that_never_expires(
    http, github_env, run, target
):
    """A TTL written as `now - fetched_at > TTL` expires NOTHING when `fetched_at` is ahead of the
    clock: the difference is negative, so the row stays fresh until the clock catches up with it.
    One file written by a machine whose clock is a day fast, and the lane reads a board that never
    refreshes -- the worst failure this cache has, because the output looks entirely correct and is
    simply old. Every way the cache can be wrong has the same right answer: read the board again.
    """
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    run("board", "list")
    cache = target / builder_github.CACHE_PATH
    stored = json.loads(cache.read_text(encoding="utf-8"))
    stored["fetched_at"] += 60 * 60 * 24 * 365
    cache.write_text(json.dumps(stored), encoding="utf-8")
    run("board", "list")
    assert len(http.of("POST /graphql")) == 2, "a cache dated in the future must not be reused"


def test_the_cache_freshness_window_is_a_window_and_not_a_half_line(target):
    """The predicate directly: a hit is a `fetched_at` inside [now - TTL, now], both ends."""
    cfg = builder.board_config(lean_cfg())
    builder_github.write_cached_board(target, cfg, {"title": "Board"})
    stored = json.loads((target / builder_github.CACHE_PATH).read_text(encoding="utf-8"))
    now = float(stored["fetched_at"])
    ttl = builder_github.CACHE_TTL_SECONDS

    assert builder_github.read_cached_board(target, cfg, now=now) is not None
    assert builder_github.read_cached_board(target, cfg, now=now + ttl) is not None
    assert builder_github.read_cached_board(target, cfg, now=now + ttl + 1) is None
    assert builder_github.read_cached_board(target, cfg, now=now - 1) is None


def test_a_corrupt_cache_is_ignored_never_fatal(http, github_env, run, target):
    cache = target / builder_github.CACHE_PATH
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{not json at all", encoding="utf-8")
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    assert "Do the thing" in out


def test_a_write_verb_never_writes_the_board_cache(http, github_env, run, target):
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.route("GET /repos/example-org/example-saas/issues/comments/1", echo_comment())
    run("issue", "comment", "7", "--body", "hello")
    assert not (target / builder_github.CACHE_PATH).exists()


# ================================================================================================
# board show / board fields
# ================================================================================================


def test_board_show_prints_the_card_and_the_issue_body(http, github_env, run):
    http.route("POST /graphql", org_board([card(12, "Do the thing", prs=(20,), sub=(3, 2))]))
    http.route(
        "GET /repos/example-org/example-saas/issues/12",
        rest_issue(12, body="the one page spec"),
    )
    code, out, _err = run("board", "show", "12")
    assert code == 0, out
    assert "In Progress" in out and "Feature" in out
    assert "the one page spec" in out
    assert "3" in out and "2" in out  # sub-issue progress
    assert "https://github.com/example-org/example-saas/pull/20" in out


def test_board_show_renders_a_multi_line_body_on_multiple_lines(http, github_env, run):
    """The body is the reason the verb exists, and a spec is not a paragraph.

    Every other remote string is flattened before it is printed, newlines included. A body is the
    exception -- it is printed in a block of its own with every line prefixed -- and flattening it
    turned headings, bullets and code into one unreadable run-on line.
    """
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    http.route(
        "GET /repos/example-org/example-saas/issues/12",
        rest_issue(12, body="## Goal\nship the parser"),
    )
    code, out, _err = run("board", "show", "12")
    assert code == 0, out
    lines = out.splitlines()
    assert "> ## Goal" in lines
    assert "> ship the parser" in lines


def test_board_show_says_so_when_the_issue_is_not_carded_and_still_shows_it(http, github_env, run):
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    http.route("GET /repos/example-org/example-saas/issues/99", rest_issue(99, body="orphan"))
    code, out, _err = run("board", "show", "99")
    assert code == 0, out
    assert "not on the board" in out.lower()
    assert "orphan" in out


def test_board_fields_lists_every_single_select_fields_live_options(http, github_env, run):
    http.route("POST /graphql", org_board([]))
    code, out, _err = run("board", "fields")
    assert code == 0, out
    assert "Status" in out and "In Progress" in out and "Todo" in out
    assert "Item Type" in out and "Bug" in out


def test_board_fields_json(http, github_env, run):
    http.route("POST /graphql", org_board([]))
    _code, out, _err = run("board", "fields", "--json")
    payload = parse_json(out)
    names = {f["name"]: f["options"] for f in payload["fields"]}
    assert names["Status"] == ["Todo", "In Progress", "Done"]
    assert names["Item Type"] == ["Feature", "Bug"]


# ================================================================================================
# issue read verbs
# ================================================================================================


def _comment(
    cid: int, *, author="alice", body="hello", created="2026-01-01T00:00:00Z", issue=7
) -> dict:
    return {
        "id": cid,
        "user": {"login": author},
        "created_at": created,
        "body": body,
        "url": f"https://api.github.com/repos/{REPO}/issues/comments/{cid}",
        "html_url": f"https://github.com/{REPO}/issues/{issue}#issuecomment-{cid}",
    }


def echo_comment(cid: int = 1, *, issue: int = 7):
    """The read-back response: the comment GitHub stored, i.e. the body that was POSTed."""

    def payload(fake: FakeHttp) -> dict:
        posted = [
            call
            for call in fake.calls
            if call["method"] == "POST" and isinstance(call["body"], dict) and "body" in call["body"]
        ]
        assert posted, "a read-back was served before anything was posted"
        return _comment(cid, body=posted[-1]["body"]["body"], issue=issue)

    return payload


def test_issue_show_reads_rest_and_reuses_the_board_read_for_status(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues/12", rest_issue(12, body="spec"))
    http.route("POST /graphql", org_board([card(12, "Do the thing", prs=(20,))]))
    code, out, _err = run("issue", "show", "12")
    assert code == 0, out
    assert "spec" in out and "alice" in out and "In Progress" in out
    assert http.of("GET /repos/example-org/example-saas/issues/12")[0]["method"] == "GET"


def test_issue_show_renders_a_multi_line_body_on_multiple_lines(http, github_env, run):
    """Same renderer, same law: two body lines come out as two lines, each one quoted."""
    http.route(
        "GET /repos/example-org/example-saas/issues/12",
        rest_issue(12, body="first line\nsecond line"),
    )
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("issue", "show", "12")
    assert code == 0, out
    lines = out.splitlines()
    assert "> first line" in lines
    assert "> second line" in lines
    assert "first line second line" not in out, "the body must not be collapsed onto one line"


def test_a_body_that_carries_a_control_character_is_still_scrubbed(http, github_env, run):
    """Keeping the newlines must not keep an ESC: a body could otherwise erase the lines above it
    and forge a different status. The line breaks survive; the escape sequence does not."""
    http.route(
        "GET /repos/example-org/example-saas/issues/12",
        rest_issue(12, body="clean line\n\x1b[2Kstate: closed"),
    )
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("issue", "show", "12")
    assert code == 0, out
    assert "\x1b" not in out, "an escape sequence survived the newline-preserving render"
    assert "> clean line" in out.splitlines()
    assert "> [2Kstate: closed" in out.splitlines(), "the line survives; only the ESC is dropped"


def test_issue_show_json(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues/12", rest_issue(12))
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    _code, out, _err = run("issue", "show", "12", "--json")
    payload = parse_json(out)
    assert payload["verb"] == "issue show"
    assert payload["issue"]["number"] == 12
    assert payload["issue"]["assignees"] == ["alice"]
    assert payload["onBoard"] is True
    assert payload["boardStatus"] == "In Progress"


def test_issue_comments_are_oldest_first_and_last_k_trims_the_tail(http, github_env, run):
    thread = [
        _comment(1, author="alice", body="first", created="2026-01-01T00:00:00Z"),
        _comment(2, author="bob", body="second", created="2026-01-02T00:00:00Z"),
        _comment(3, author="carol", body="third", created="2026-01-03T00:00:00Z"),
    ]
    http.route("GET /repos/example-org/example-saas/issues/7/comments", thread)
    _code, out, _err = run("issue", "comments", "7")
    assert out.index("first") < out.index("second") < out.index("third")
    assert "per_page=100" in http.of("GET /repos/example-org/example-saas/issues/7/comments")[0][
        "query"
    ]
    _code, out, _err = run("issue", "comments", "7", "--last", "1")
    assert "third" in out and "first" not in out


def test_issue_find_filters_labels_server_side_and_text_client_side(http, github_env, run):
    listing = [
        rest_issue(1, title="alpha widget", body="nothing here"),
        rest_issue(2, title="beta", body="mentions WIDGET in the body"),
        rest_issue(3, title="gamma", body="unrelated"),
        {**rest_issue(4, title="a pull request"), "pull_request": {"url": "x"}},
    ]
    http.route("GET /repos/example-org/example-saas/issues", listing)
    code, out, _err = run("issue", "find", "--label", "area:api", "--text", "widget")
    assert code == 0, out
    query = urllib.parse.unquote_plus(http.of("GET /repos/example-org/example-saas/issues")[0]["query"])
    assert "labels=area:api" in query
    assert "state=open" in query
    assert "per_page=100" in query
    assert "alpha widget" in out and "beta" in out
    assert "gamma" not in out
    assert "a pull request" not in out, "the issues endpoint returns PRs; they are not issues"


def test_issue_find_state_flag_reaches_the_query(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    run("issue", "find", "--state", "all")
    query = http.of("GET /repos/example-org/example-saas/issues")[0]["query"]
    assert "state=all" in query


# ================================================================================================
# issue comment: the stamp, and the read-back
# ================================================================================================


def test_issue_comment_posts_one_comment_stamped_and_reads_it_back(http, github_env, run):
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.route("GET /repos/example-org/example-saas/issues/comments/1", echo_comment())
    code, out, _err = run("issue", "comment", "7", "--body", "  the note  ")
    assert code == 0, out
    post = http.of("POST /repos/example-org/example-saas/issues/7/comments")[0]
    assert set(post["body"]) == {"body"}, "one comment, and nothing else is written"
    body = post["body"]["body"]
    assert body.startswith("the note"), "the body is trimmed"
    assert "the note\n\n<sub>builder" in body, "the lane stamp follows a blank line"
    assert body.rstrip().endswith("</sub>"), "the stamp is the trailer, not a prefix"
    # NO UNVERIFIED SUCCESS: the created comment is read back before its URL is printed.
    assert http.of("GET /repos/example-org/example-saas/issues/comments/1"), "no read-back"
    assert "https://github.com/example-org/example-saas/issues/7#issuecomment-1" in out


def test_issue_comment_refuses_an_empty_body(http, github_env, run):
    code, _out, err = run("issue", "comment", "7", "--body", "   ")
    assert code == 1
    assert "empty" in err.lower()
    assert not http.calls, "nothing is sent for a body that is only whitespace"


def test_issue_comment_reads_a_body_file(http, github_env, run, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("from a file\n", encoding="utf-8")
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.route("GET /repos/example-org/example-saas/issues/comments/1", echo_comment())
    code, _out, _err = run("issue", "comment", "7", "--body-file", str(note))
    assert code == 0
    assert "from a file" in http.of("POST /repos/example-org/example-saas/issues/7/comments")[0][
        "body"
    ]["body"]


def test_a_comment_that_reads_back_different_is_a_failure(http, github_env, run):
    """The planted defect. A read-back that only had to return 200 would verify nothing, so the
    verification compares what came back with what went out -- and this proves it does."""
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.route(
        "GET /repos/example-org/example-saas/issues/comments/1",
        _comment(1, body="something else entirely"),
    )
    code, _out, err = run("issue", "comment", "7", "--body", "the note")
    assert code == 1
    assert "read back" in err.lower()


def test_a_comment_that_cannot_be_read_back_is_a_failure(http, github_env, run):
    """A 201 is not evidence. The read-back is what says the comment is really there."""
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.fail("GET /repos/example-org/example-saas/issues/comments/1", 404)
    code, _out, err = run("issue", "comment", "7", "--body", "the note")
    assert code == 1
    assert "read" in err.lower()


# ================================================================================================
# debt file
# ================================================================================================


def _created(number: int, *, labels=("tech-debt",)) -> dict:
    return {
        "number": number,
        "title": "The flaky retry loop",
        "body": "b",
        "state": "open",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "labels": [{"name": name} for name in labels],
    }


NO_PROJECT_ITEMS = {"data": {"repository": {"issue": {"projectItems": {"nodes": []}}}}}


def test_debt_file_creates_a_labelled_issue_and_nothing_else(http, github_env, run, target):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route("POST /graphql", NO_PROJECT_ITEMS)
    code, out, _err = run(
        "debt", "file", "--title", "The flaky retry loop", "--body", "it retries forever",
        "--refs", "12", "--refs", "13",
    )
    assert code == 0, out
    post = http.of("POST /repos/example-org/example-saas/issues")[0]["body"]
    assert post["title"] == "The flaky retry loop"
    assert post["labels"] == ["tech-debt"]
    assert set(post) == {"title", "body", "labels"}, "no assignee, milestone or project"
    assert "it retries forever" in post["body"]
    assert "Origin:" in post["body"]
    assert "<sub>builder" in post["body"]
    assert "Refs #12" in post["body"] and "Refs #13" in post["body"]
    assert "https://github.com/example-org/example-saas/issues/99" in out


def test_debt_file_refuses_an_exact_duplicate_title(http, github_env, run):
    existing = [rest_issue(5, title="The  FLAKY, retry loop!", labels=("tech-debt",))]
    http.route("GET /repos/example-org/example-saas/issues", existing)
    code, _out, err = run("debt", "file", "--title", "The flaky retry loop", "--body", "x")
    assert code == 1
    assert "https://github.com/example-org/example-saas/issues/5" in err
    assert not http.of("POST /repos/example-org/example-saas/issues"), "nothing was created"


def test_debt_file_warns_about_a_near_match_but_proceeds(http, github_env, run):
    existing = [rest_issue(5, title="The flaky retry loop in checkout", labels=("tech-debt",))]
    http.route("GET /repos/example-org/example-saas/issues", existing)
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route("POST /graphql", NO_PROJECT_ITEMS)
    code, out, err = run("debt", "file", "--title", "The flaky retry loop", "--body", "x")
    assert code == 0, out
    assert "near" in err.lower()
    assert "issues/5" in err
    assert http.of("POST /repos/example-org/example-saas/issues"), "a near match still proceeds"


def test_debt_file_dedupe_reads_only_the_debt_label(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route("POST /graphql", NO_PROJECT_ITEMS)
    run("debt", "file", "--title", "New debt", "--body", "x")
    query = urllib.parse.unquote_plus(
        http.of("GET /repos/example-org/example-saas/issues")[0]["query"]
    )
    assert "labels=tech-debt" in query and "state=open" in query


def test_debt_file_fails_loudly_when_the_label_was_silently_dropped(http, github_env, run):
    """A token without issue-write silently drops `labels`, and the label is what the queue reads."""
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99, labels=()))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99, labels=()))
    code, _out, err = run("debt", "file", "--title", "New debt", "--body", "x")
    assert code == 1
    assert "tech-debt" in err
    assert "issues/99" in err


def test_debt_file_refuses_extra_labels_on_the_read_back(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route(
        "GET /repos/example-org/example-saas/issues/99",
        _created(99, labels=("tech-debt", "priority:high")),
    )
    code, _out, err = run("debt", "file", "--title", "New debt", "--body", "x")
    assert code == 1
    assert "priority:high" in err


def test_debt_file_exits_2_when_automation_put_the_issue_on_the_board(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route(
        "POST /graphql",
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {"project": {"number": PROJECT_NUMBER, "owner": {"login": OWNER}}}
                            ]
                        }
                    }
                }
            }
        },
    )
    code, _out, err = run("debt", "file", "--title", "New debt", "--body", "x")
    assert code == 2
    assert "https://github.com/example-org/example-saas/issues/99" in err
    assert "automation" in err.lower()
    body = http.graphql_bodies()[0]
    assert "projectItems" in body["query"]
    assert body["variables"] == {"owner": OWNER, "name": "example-saas", "number": 99}


def test_debt_file_ignores_a_different_project(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route(
        "POST /graphql",
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [{"project": {"number": 77, "owner": {"login": OWNER}}}]
                        }
                    }
                }
            }
        },
    )
    code, _out, _err = run("debt", "file", "--title", "New debt", "--body", "x")
    assert code == 0


def test_debt_file_json(http, github_env, run):
    http.route("GET /repos/example-org/example-saas/issues", [])
    http.route("POST /repos/example-org/example-saas/issues", _created(99))
    http.route("GET /repos/example-org/example-saas/issues/99", _created(99))
    http.route("POST /graphql", NO_PROJECT_ITEMS)
    _code, out, _err = run("debt", "file", "--title", "New debt", "--body", "x", "--json")
    payload = parse_json(out)
    assert payload["verb"] == "debt file"
    assert payload["number"] == 99
    assert payload["labels"] == ["tech-debt"]


# ================================================================================================
# config, credentials, and transport posture
# ================================================================================================


def test_every_verb_refuses_without_a_builder_github_block(run_cli, tmp_path):
    """No traceback, exit 1, and a message naming the block to add -- through the REAL CLI."""
    root = tmp_path / "plain"
    root.mkdir()
    cfg = lean_cfg()
    cfg.pop("builderGithub")
    (root / ".tautline.json").write_text(json.dumps(cfg), encoding="utf-8")
    for argv in (
        ["board", "list"],
        ["board", "fields"],
        ["issue", "find"],
        ["debt", "file", "--title", "t", "--body", "b"],
    ):
        result = run_cli(*argv, "--target", str(root))
        assert result.returncode == 1, (argv, result.stdout, result.stderr)
        assert "Traceback" not in result.stderr, argv
        assert "builderGithub" in result.stderr, argv


def test_a_missing_config_refuses_without_a_traceback(run_cli, tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    result = run_cli("board", "list", "--target", str(root))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "tautline init" in result.stderr


def test_no_token_refuses_and_names_the_environment_variables(http, run, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    code, _out, err = run("board", "list")
    assert code == 1
    assert "GITHUB_TOKEN" in err and "GH_TOKEN" in err
    assert not http.calls


def test_the_gh_cli_is_the_last_credential_seam(http, run, monkeypatch):
    """`_token()` is the ONE seam a sibling lane's App-minting hop replaces."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: "gho_FROM_THE_GH_CLI")
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, _out, _err = run("board", "list")
    assert code == 0
    assert http.calls[0]["headers"]["Authorization"] == "Bearer gho_FROM_THE_GH_CLI"


# ================================================================================================
# the App identity, at the same socket boundary
# ================================================================================================
#
# `_token()` is a THREE-step seam: environment, then the builder GitHub App, then `gh auth token`.
# These tests assert the middle step from the only place that can prove it -- the `Authorization`
# header the verbs actually put on the wire -- because the whole point of the App is that the write
# lands as the BOT. A test that asserted `builder.github_token()` returned a string would pass
# equally well if the verbs then ignored it.
#
# Only the MINT is faked. The precedence, the config threading and the header construction are all
# the real code paths.

APP_TOKEN = "ghs_NOT_A_REAL_APP_TOKEN_0123456789"
APP_ID = "123456"
INSTALLATION_ID = 42


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    """A machine with the builder App configured and NO operator token exported.

    Returns the list the fake mint records its arguments in, so a test can assert not merely that
    an App token was sent but that the App was asked for the right installation.
    """
    from tautline_methodology import builder_token

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    key = tmp_path / "app-key.pem"
    key.write_text("-----BEGIN RSA PRIVATE KEY-----\nnot-a-key\n-----END RSA PRIVATE KEY-----\n")
    monkeypatch.setenv(builder_token.APP_ID_ENV, APP_ID)
    monkeypatch.setenv(builder_token.APP_KEY_ENV, str(key))
    monkeypatch.setenv(builder_token.INSTALLATION_ID_ENV, str(INSTALLATION_ID))

    mints: list[tuple] = []

    def _mint(app_id, key_path, installation_id):
        mints.append((app_id, Path(key_path).name, installation_id))
        return builder_token.MintedToken(
            token=Secret(APP_TOKEN),
            expires_at="2026-09-05T12:00:00Z",
            installation_id=installation_id,
            app_id=app_id,
            permissions={"issues": "write", "contents": "write"},
        )

    monkeypatch.setattr(builder_token, "mint_and_cache", _mint)
    return mints


def test_the_verbs_send_the_app_minted_token_when_no_operator_token_is_exported(
    http, app_env, run
):
    """THE POINT OF THE IDENTITY LAYER. A lane with the App configured acts as the bot without
    anyone exporting GH_TOKEN into a process that also runs a test suite and a shell."""
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {APP_TOKEN}"
    assert app_env == [(APP_ID, "app-key.pem", INSTALLATION_ID)]


def test_the_app_token_is_used_for_a_write_not_only_a_read(http, app_env, run):
    """The read is the cheap case. The comment is where authorship is visible on a human's issue,
    so the write path is asserted separately rather than assumed to share the header."""
    http.route("POST /repos/example-org/example-saas/issues/7/comments", _comment(1))
    http.route("GET /repos/example-org/example-saas/issues/comments/1", echo_comment())
    code, out, _err = run("issue", "comment", "7", "--body", "progress")
    assert code == 0, out
    for call in http.calls:
        assert call["headers"]["Authorization"] == f"Bearer {APP_TOKEN}"


def test_an_exported_token_beats_the_app_and_the_app_is_never_consulted(http, app_env, run,
                                                                       monkeypatch):
    """A person who exported GH_TOKEN answered this question deliberately, and an App that
    second-guessed them would be a surprise on the machine least expecting one -- the operator's.

    `app_env` is still in force, so this also proves the environment check SHORT-CIRCUITS: an empty
    `mints` list is the assertion that the App was never even asked.
    """
    monkeypatch.setenv("GITHUB_TOKEN", GH_TOKEN)
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {GH_TOKEN}"
    assert app_env == []


def test_the_app_discovers_its_installation_from_the_lean_configs_repo_owner(
    http, app_env, run, monkeypatch
):
    """The wiring test. `_Client` carries the RAW lean config, not the parsed `BoardConfig`,
    precisely because the App needs `project.repo` to find its installation -- so a client built
    without it would refuse on every machine that had not pinned the installation id by hand."""
    from tautline_methodology import builder_token

    monkeypatch.delenv(builder_token.INSTALLATION_ID_ENV, raising=False)
    seen: list[str] = []

    def _discover(app_id, key_path, owner):
        seen.append(owner)
        return 77

    monkeypatch.setattr(builder_token, "discover_installation_id", _discover)
    http.route("POST /graphql", org_board([card(12, "Do the thing")]))
    code, out, _err = run("board", "list")
    assert code == 0, out
    assert seen == [OWNER]
    assert app_env == [(APP_ID, "app-key.pem", 77)]
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {APP_TOKEN}"


def test_a_configured_app_that_cannot_mint_refuses_instead_of_falling_back_to_the_humans_gh(
    http, app_env, run, monkeypatch
):
    """The most important negative in this section.

    Falling through to `gh auth token` here would make the lane quietly write to the board under
    the OPERATOR's name -- the single outcome the App exists to prevent -- and it would do so on
    exactly the days something is already wrong (a revoked installation, a moved key). So a
    configured-but-broken App is a refusal, exit 1, no request made, and the message says why the
    fallback was not taken.
    """
    from tautline_methodology import builder_token

    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: "gho_THE_OPERATORS_OWN_TOKEN")

    def _explode(app_id, key_path, installation_id):
        raise builder_token.BuilderTokenError("the installation was suspended")

    monkeypatch.setattr(builder_token, "mint_and_cache", _explode)
    code, out, err = run("board", "list")
    assert code == 1, out
    assert "builder_error:" in err
    assert "the installation was suspended" in err
    assert "under YOUR name" in err
    assert "Traceback" not in out + err
    assert not http.calls


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_issue_comments_last_refuses_a_count_below_one(run_cli, target, value):
    """`--last 0` asked for "the last nothing" and got the WHOLE thread: `comments[-0:]` is
    `comments[0:]`, which is every comment. `--last -1` quietly drops the last one. Both are the
    same class of bug -- a slice reading a number the caller did not mean -- and neither is
    something a caller can see went wrong, because the output looks like a comment thread either
    way. argparse rejects the value before any of that, which is where the check belongs."""
    result = run_cli("issue", "comments", "7", "--last", value, "--target", str(target))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "--last" in result.stderr


def test_a_refusal_keeps_stdout_a_data_channel(http, github_env, run):
    """`builder_error:` went to STDOUT, which is the channel a caller parses.

    Without `--json`, a caller doing `tautline board list > board.txt` got the prose refusal in
    the file and an empty terminal -- the one place a person is looking. With `--json`, the
    envelope promise was broken outright: the consumer got a line of prose where JSON was
    promised, and `json.loads` raised something with nothing to do with the actual failure.

    Exit codes are unchanged; only the channel is. `--json` gets a parseable `{"error": ...}` on
    stdout AND the prose on stderr, because the two readers are different people.
    """
    http.fail("POST /graphql", 401, {"message": "Bad credentials"})
    code, out, err = run("board", "list")
    assert code == 1
    assert out == "", out
    assert err.startswith("builder_error:"), err

    code, out, err = run("board", "list", "--json")
    assert code == 1
    assert json.loads(out)["error"], out
    assert "builder_error:" in err


def test_a_token_never_reaches_the_output(http, github_env, run):
    http.fail("POST /graphql", 401, {"message": "Bad credentials"})
    code, out, err = run("board", "list")
    assert code == 1
    assert GH_TOKEN not in out + err


def test_the_client_refuses_a_non_github_origin():
    with pytest.raises(builder_github.BuilderGitHubError, match="api.github.com"):
        builder_github._Client(repo=REPO)._assert_github_origin("https://evil.example/graphql")


def test_the_client_refuses_redirects():
    opener = builder_github._Client._build_opener()
    handler = next(
        h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    )
    with pytest.raises(builder_github.BuilderGitHubError, match="Authorization header"):
        handler.redirect_request(
            urllib.request.Request("https://api.github.com/x"),
            None,
            302,
            "Found",
            {},
            "https://evil.example/",
        )


def test_remote_text_is_bounded_before_it_is_rendered(http, github_env, run):
    forged = "\x1b[2Kdone" + "x" * 500
    http.route("POST /graphql", org_board([card(12, forged)]))
    _code, out, _err = run("board", "list")
    assert "\x1b" not in out
    assert "x" * 300 not in out


# ================================================================================================
# the lean validator accepts the block
# ================================================================================================


def test_validate_adapter_accepts_a_builder_github_block(run_cli, tmp_path):
    root = tmp_path / "ok"
    root.mkdir()
    path = root / ".tautline.json"
    path.write_text(json.dumps(lean_cfg()), encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_lean_validator_delegates_to_the_builder_contract():
    cfg = lean_cfg()
    cfg["builderGithub"] = {"owner": "example-org"}  # projectNumber missing
    errors = lean.lean_config_errors(cfg)
    assert any("projectNumber" in error for error in errors), errors
    assert not any("unknown property" in error for error in errors), errors
    # DELEGATED, not restated: every error the builder contract reports is reported here verbatim,
    # so the two cannot drift into disagreeing about what a usable block is.
    assert set(builder.board_config_errors(cfg)) <= set(errors), errors


def test_a_lean_config_without_the_block_is_still_valid():
    cfg = lean_cfg()
    cfg.pop("builderGithub")
    assert lean.lean_config_errors(cfg) == []


def test_a_verb_that_needs_an_issue_number_says_which_verb(http, github_env, run):
    """`'None' is not an issue number` names nothing an operator can act on."""
    for argv, wanted in (
        (["board", "show"], "tautline board show"),
        (["issue", "show"], "tautline issue show"),
        (["issue", "comments"], "tautline issue comments"),
        (["issue", "comment", "--body", "x"], "tautline issue comment"),
    ):
        code, _out, err = run(*argv)
        assert code == 1, argv
        assert wanted in err, (argv, err)
        assert "None" not in err, argv
    assert not http.calls
