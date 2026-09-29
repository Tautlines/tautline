"""The backlog seam: one interface, three boards, and no network in CI.

Every remote test here is served at the SOCKET boundary -- `urlopen`/`OpenerDirector.open` -- rather
than by stubbing a provider's own method. That is deliberate: it exercises the URL, method, headers
and body the provider actually builds, so the assertions read the real request. A test that stubs
the provider's own transport proves only that the provider agrees with itself. The autouse
`_no_outbound_network` guard in `conftest.py` sits underneath and makes a live connection impossible
even if a fake is forgotten -- a developer running this suite usually has a real `GITHUB_TOKEN`
exported, and a missing fake would otherwise mutate a live board and pass.

The suite is organised around the laws this module exists to hold:

* the LOOP works, identically, on all three providers, across PAGE BOUNDARIES;
* the CONFIG is validated with actionable messages, and a credential-missing message names the
  environment variable to set;
* there is NO FALLBACK -- a remote provider that fails writes nothing locally;
* there is NO SYNC -- nothing writes except the four explicit commands;
* there is NO UNVERIFIED SUCCESS -- every mutation is read back, and every verification has a test
  that plants the defect it exists to catch.
"""

from __future__ import annotations

import argparse
import inspect
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from tautline_methodology import (
    backlog,
    builder_github,
    builder_token,
    jira_client,
    lean,
    stakeholder_question,
)

SITE = "https://team.atlassian.net"
EMAIL = "someone@example.invalid"
TOKEN = "ATATT3xFfGF0-NOT-A-REAL-TOKEN-abc123"
GH_TOKEN = "ghp_NOT_A_REAL_TOKEN_0123456789"

LEAN_BASE = {
    "schemaVersion": "lean-1",
    "project": {"name": "Demo", "repo": "acme/demo"},
    "integrationBranch": "main",
    "commands": {"test": "scripts/test.sh"},
}


def lean_cfg(**backlog_block) -> dict:
    cfg = dict(LEAN_BASE)
    if backlog_block:
        cfg["backlog"] = dict(backlog_block)
    return cfg


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

    A key holds a QUEUE of responses so a pager can be served page 1 then page 2 from the same
    path; the last response repeats once the queue is drained, which is what a re-read after a
    write needs. Asserting on `calls` is how the GitHub tests prove the provider never reaches the
    Projects GraphQL endpoint and how the Jira tests prove the cursor it sent.
    """

    def __init__(self) -> None:
        self.routes: dict[str, list] = {}
        self.errors: dict[str, urllib.error.HTTPError] = {}
        self.calls: list[dict] = []
        #: When set, a request whose `timeout` is shorter than this many seconds "times out".
        self.simulated_seconds: float | None = None

    def route(self, key: str, payload: object, headers: dict | None = None) -> "FakeHttp":
        self.routes.setdefault(key, []).append((payload, headers or {}))
        return self

    def fail(self, key: str, code: int, body: object = None, headers: dict | None = None):
        raw = b"{}" if body is None else json.dumps(body).encode("utf-8")
        self.errors[key] = urllib.error.HTTPError(
            key, code, "boom", headers or {}, io.BytesIO(raw)
        )
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
        if self.simulated_seconds is not None and timeout is not None:
            if timeout < self.simulated_seconds:
                raise urllib.error.URLError(
                    f"timed out after {timeout}s (the board would have taken "
                    f"{self.simulated_seconds}s)"
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
        return _Response(payload, headers)

    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]

    def queries(self, path: str) -> list[str]:
        return [
            urllib.parse.unquote_plus(call["query"]) for call in self.calls if call["path"] == path
        ]


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    """Serve both transports from one recorder, and make a real socket impossible."""
    fake = FakeHttp()

    def _urlopen(request, *args, **kwargs):
        return fake.handle(request, kwargs.get("timeout", args[0] if args else None))

    def _open(self, request, *args, **kwargs):  # OpenerDirector.open
        return fake.handle(request, kwargs.get("timeout", args[0] if args else None))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _open)
    return fake


@pytest.fixture(autouse=True)
def _clean_jira_cache():
    """The Jira response cache is module-level, so it is shared state between tests."""
    jira_client.reset_response_cache()
    yield
    jira_client.reset_response_cache()


@pytest.fixture
def jira_env(monkeypatch):
    monkeypatch.setenv(jira_client.EMAIL_ENV, EMAIL)
    monkeypatch.setenv(jira_client.API_TOKEN_ENV, TOKEN)


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", GH_TOKEN)
    monkeypatch.delenv("GH_TOKEN", raising=False)


def _issue(number: int, title: str, *, labels=("backlog",), state="open") -> dict:
    return {
        "number": number,
        "title": title,
        "body": f"body of {number}",
        "state": state,
        "html_url": f"https://github.com/acme/demo/issues/{number}",
        "labels": [{"name": name} for name in labels],
    }


def _jira_issue(key: str, summary: str, category: str = "new") -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"statusCategory": {"key": category}},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": f"spec {key}"}]}
                ],
            },
        },
    }


ISSUE_TYPES = {
    "issueTypes": [
        {"id": "10002", "name": "Sub-task", "subtask": True},
        {"id": "10001", "name": "Task", "subtask": False},
    ],
    "startAt": 0,
    "maxResults": 100,
    "total": 2,
}


def _route_createmeta(http: FakeHttp) -> None:
    http.route("GET /rest/api/3/issue/createmeta/PROJ/issuetypes", ISSUE_TYPES)


# ================================================================================================
# config validation
# ================================================================================================


def test_no_backlog_key_means_the_local_queue_file():
    """A project that has named no board still has a backlog; the question is where it is written."""
    assert backlog.backlog_config(LEAN_BASE) == {
        "provider": "local",
        "path": backlog.DEFAULT_QUEUE_PATH,
    }
    assert backlog.backlog_config_errors(backlog.backlog_config(LEAN_BASE)) == []


@pytest.mark.parametrize(
    ("block", "fragment"),
    [
        ({"provider": "trello"}, "expected one of local, github, jira"),
        ({"provider": "local", "owner": "x"}, "unknown property 'owner'"),
        ({"provider": "local", "token": "ghp_real"}, "unknown property 'token'"),
        ({"provider": "local", "path": 7}, "backlog.path: expected a string"),
        ({"provider": "local", "path": "  "}, "non-blank queue file path"),
        ({"provider": "github"}, "backlog.repo is required"),
        ({"provider": "github", "repo": "https://github.com/a/b"}, "must be 'owner/name'"),
        ({"provider": "github", "repo": "demo"}, "must be 'owner/name'"),
        ({"provider": "github", "repo": "a/b", "label": " "}, "non-blank issue label"),
        ({"provider": "jira", "project": "PROJ"}, "backlog.site is required"),
        ({"provider": "jira", "site": SITE}, "backlog.project is required"),
        ({"provider": "jira", "site": "https://team.example.com", "project": "P1"}, "Jira CLOUD"),
        ({"provider": "jira", "site": "http://team.atlassian.net", "project": "P1"}, "Jira CLOUD"),
        ({"provider": "jira", "site": "https://team-..atlassian.net", "project": "P1"}, "CLOUD"),
        ({"provider": "jira", "site": SITE, "project": "A"}, "project-key grammar"),
        ({"provider": "jira", "site": SITE, "project": "proj"}, "project-key grammar"),
        ({"provider": "jira", "site": SITE, "project": "A/B"}, "project-key grammar"),
        ({"provider": "jira", "site": SITE, "project": "PROJ", "board": "0"}, "positive whole"),
        ({"provider": "jira", "site": SITE, "project": "PROJ", "board": "abc"}, "positive whole"),
        ({"provider": "jira", "site": SITE, "project": "PROJ", "board": "²"}, "positive whole"),
        ({"provider": "jira", "site": SITE, "project": "PROJ", "board": "9" * 40}, "positive whole"),
        # Track G: cap-overflow fix -- one case per backlog length cap that has no existing
        # domain-specific bound (`site` and `board` keep their own: DNS-limit and digit-count,
        # asserted separately below and in test_a_very_long_but_well_formed_jira_host_..., so a
        # generic cap here must not shadow them).
        (
            {"provider": "local", "path": "p" * (backlog._BACKLOG_FIELD_MAX_CHARS["path"] + 1)},
            "backlog.path",
        ),
        (
            {
                "provider": "github",
                "repo": "owner/repo",
                "label": "l" * (backlog._BACKLOG_FIELD_MAX_CHARS["label"] + 1),
            },
            "backlog.label",
        ),
        (
            {"provider": "github", "repo": "o/" + "r" * backlog._BACKLOG_FIELD_MAX_CHARS["repo"]},
            "backlog.repo",
        ),
        (
            {
                "provider": "jira",
                "site": SITE,
                "project": "P" * (backlog._BACKLOG_FIELD_MAX_CHARS["project"] + 1),
            },
            "backlog.project",
        ),
    ],
)
def test_backlog_config_errors_are_actionable(block, fragment):
    errors = backlog.backlog_config_errors(block)
    assert any(fragment in error for error in errors), errors


def test_a_very_long_but_well_formed_jira_host_is_refused_by_the_total_dns_limit():
    """The per-label bound lives in the pattern; the 253-octet total cannot, so both run together."""
    host = ".".join(["a" * 60] * 5)
    block = {"provider": "jira", "site": f"https://{host}.atlassian.net", "project": "PROJ"}
    assert any("DNS limit" in error for error in backlog.backlog_config_errors(block))


def test_valid_blocks_pass_for_every_provider():
    for block in (
        {"provider": "local"},
        {"provider": "local", "path": "docs/QUEUE.md"},
        {"provider": "github", "repo": "acme/demo"},
        {"provider": "github", "repo": "acme/demo", "label": "todo"},
        {"provider": "jira", "site": SITE, "project": "PROJ"},
        {"provider": f"{SITE}/" and "jira", "site": f"{SITE}/", "project": "PROJ", "board": "12"},
    ):
        assert backlog.backlog_config_errors(block) == [], block


def test_the_lean_validator_refuses_a_bad_backlog_block():
    errors = lean.lean_config_errors(lean_cfg(provider="jira", site="ftp://x", project="P"))
    assert any("Jira CLOUD" in error for error in errors), errors
    assert lean.lean_config_errors(lean_cfg(provider="github", repo="acme/demo")) == []


def test_the_shipped_lean_schema_documents_the_backlog_key_and_closes_it():
    """`additionalProperties: false` is how the published schema MEANS "credentials never live
    here": without it the document says no token belongs in the block while accepting one."""
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema-lean.json").read_text(
            encoding="utf-8"
        )
    )
    block = schema["properties"]["backlog"]
    assert block["required"] == ["provider"]
    assert block["additionalProperties"] is False
    assert set(block["properties"]["provider"]["enum"]) == set(backlog.PROVIDERS)
    assert set(block["properties"]) == set(backlog._CONFIG_KEYS)


def test_the_public_contract_calls_the_verb_experimental():
    """Honest labelling until first contact: the jira provider has never spoken to a live site, so
    the surface must not be bound to the stable semver policy yet."""
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1] / "methodology" / "public-contract-manifest.json"
        ).read_text(encoding="utf-8")
    )
    entry = next(c for c in manifest["commands"] if c["name"] == "backlog")
    assert entry["status"] == "experimental"


def test_provider_for_refuses_an_invalid_block_by_name(tmp_path):
    with pytest.raises(backlog.BacklogError) as excinfo:
        backlog.provider_for(tmp_path, lean_cfg(provider="github"))
    assert "backlog.repo is required" in str(excinfo.value)


def test_the_board_id_digit_bound_has_one_value_across_the_two_validators():
    from tautline_methodology import providers

    assert providers.MAX_BOARD_ID_DIGITS == jira_client.MAX_BOARD_ID_DIGITS


# ================================================================================================
# the PR<->backlog reference stamp (scripts/check_pr_backlog_ref.py reads this table)
# ================================================================================================


def test_reference_grammar_covers_every_provider():
    """Discovery-complete against the seam, not hand-listed beside it: a provider added to
    PROVIDERS without a matching REFERENCE_GRAMMAR entry fails here, before it can ship silently
    accepting nothing (KeyError at check time) or, worse, silently reusing whatever a `.get`
    default happened to be."""
    assert set(backlog.REFERENCE_GRAMMAR) == set(backlog.PROVIDERS)


@pytest.mark.parametrize("provider", backlog.PROVIDERS)
def test_the_generic_stamp_is_accepted_by_every_provider(provider):
    grammar = backlog.REFERENCE_GRAMMAR[provider]
    assert any(p.search("Backlog: something-2026") for p in grammar.patterns)
    assert any(p.search("some prose\n\nbacklog:   ANY-ID  \nmore prose") for p in grammar.patterns)


def test_local_grammar_accepts_only_the_generic_form():
    """Local has no external convention of its own the way GitHub and Jira do, so its grammar is
    exactly the one row every provider inherits -- nothing provider-specific to add."""
    assert len(backlog.REFERENCE_GRAMMAR["local"].patterns) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Closes #42",
        "closes #42",
        "CLOSES #42",
        "Close #42",
        "Closed #42",
        "Fix #42",
        "Fixes #42",
        "Fixed #42",
        "Resolve #42",
        "Resolves #42",
        "Resolved #42",
        "Fixes: #42",
        "Resolves acme/demo#42",
        "Closes https://github.com/acme/demo/issues/42",
    ],
)
def test_github_grammar_accepts_every_closing_keyword_and_ref_form(text):
    grammar = backlog.REFERENCE_GRAMMAR["github"]
    assert any(p.search(text) for p in grammar.patterns), text


def test_github_grammar_rejects_a_bare_number_with_no_keyword():
    """A bare `#42` with no keyword is not a closing reference GitHub would act on -- only the
    generic `Backlog:` form or an explicit keyword counts."""
    grammar = backlog.REFERENCE_GRAMMAR["github"]
    assert not any(p.search("see #42 for context") for p in grammar.patterns)


def test_jira_grammar_accepts_a_bare_key():
    grammar = backlog.REFERENCE_GRAMMAR["jira"]
    assert any(p.search("fix(PROJ-12): tighten validation") for p in grammar.patterns)


def test_jira_grammar_is_case_sensitive_like_real_jira_keys():
    """Jira project keys are always uppercase; a lowercase lookalike is not a real key and must
    not be accepted as one."""
    grammar = backlog.REFERENCE_GRAMMAR["jira"]
    assert not any(p.search("proj-12") for p in grammar.patterns)


def test_jira_grammar_rejects_githubs_closing_keyword():
    grammar = backlog.REFERENCE_GRAMMAR["jira"]
    assert not any(p.search("Closes #42") for p in grammar.patterns)


@pytest.mark.parametrize(
    "provider, stamp_id, described_fragment",
    [
        ("local", "2026-08-31-tighten-validation", "queue-item slug"),
        ("github", "#42", "closing keyword"),
        ("jira", "PROJ-12", "Jira issue key"),
    ],
)
def test_the_take_stamp_id_satisfies_its_own_providers_grammar(provider, stamp_id, described_fragment):
    """The exact id `backlog take` prints must be accepted by that SAME provider's grammar --
    otherwise a ready-to-paste line would fail the check that reads it."""
    grammar = backlog.REFERENCE_GRAMMAR[provider]
    assert any(p.search(f"Backlog: {stamp_id}") for p in grammar.patterns)
    assert described_fragment in grammar.describe


def test_local_stamp_id_is_not_truncated_at_a_realistic_max_length_slug(tmp_path):
    """Found by dogfooding: a local id is `YYYY-MM-DD-<slugify()>`, up to 71 characters, and the
    base class's `MAX_ID_CHARS` (40, sized for a TABLE column) would truncate one with `...` --
    printing a `Backlog: ...` line that no longer names the real item. `stamp_id` must not do
    that: it is the one thing this feature promises is ready to paste verbatim."""
    provider = backlog.LocalBacklog(root=tmp_path)
    long_id = "2026-08-31-" + ("x" * 60)  # 10 (date) + 1 (-) + 60 (slugify's own cap) = 71
    assert len(long_id) == 71
    item = backlog.Item(id=long_id, title="Some very long title indeed")
    assert provider.stamp_id(item) == long_id, "must be the WHOLE id, not truncated with '...'"


# ================================================================================================
# remote text is never printed raw
# ================================================================================================


def test_control_characters_from_a_board_cannot_forge_output():
    """Collapsing whitespace is not enough: ESC and BEL are not whitespace, so a title carrying
    `\\x1b[2K` can erase the line a report just wrote and forge the one above it."""
    hostile = "Fix\x1b[2K\x07 the thing\nsecond line"
    cleaned = backlog._safe(hostile)
    assert "\x1b" not in cleaned and "\x07" not in cleaned and "\n" not in cleaned
    assert cleaned == "Fix [2K the thing second line"


def test_an_unbounded_id_cannot_set_the_table_column_width():
    items = [backlog.Item(id="x" * 4000, title="huge", state=backlog.READY)]
    line = backlog._table(items)[0]
    assert len(line) < 250
    assert line.startswith("x" * 30)


def test_a_forged_error_body_cannot_paint_a_fake_status_line(jira, http, capsys, tmp_path):
    """THE REPRO. A hostile or compromised Jira answers 400 with erase-line and BEL in its
    ErrorCollection, and the bytes ride the error message all the way to the terminal -- where they
    wipe the line just written and paint a healthy `backlog: jira (PROJ) - 0 open` that nothing
    measured. Flattened at the source, in `_error_collection`, so no caller has to remember."""
    forged = "\x1b[2K\r\x1b[32mbacklog: jira (PROJ) - 0 open\x1b[0m\x07"
    http.fail("GET /rest/api/3/search/jql", 400, {"errorMessages": [forged]})
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.list()
    message = str(excinfo.value)
    for control in ("\x1b", "\x07", "\r"):
        assert control not in message, repr(message)
    assert "backlog: jira (PROJ) - 0 open" in message, "the words survive; only the control bytes go"

    # And the same body, all the way through the CLI print -- the end the user actually reads.
    (tmp_path / ".tautline.json").write_text(
        json.dumps(lean_cfg(provider="jira", site=SITE, project="PROJ")), encoding="utf-8"
    )
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    for control in ("\x1b", "\x07", "\r"):
        assert control not in out, repr(out)


def test_the_cli_print_sanitises_any_error_type(tmp_path, capsys, monkeypatch):
    """The last line of defence, so an error type nobody has written yet cannot bypass the
    sanitising its own construction forgot."""
    (tmp_path / ".tautline.json").write_text(json.dumps(lean_cfg(provider="local")), encoding="utf-8")

    def _explode(*_args, **_kwargs):
        raise backlog.BacklogError("boom\x1b[2K\x07 after")

    monkeypatch.setattr(backlog.LocalBacklog, "list", _explode)
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "boom" in out and "after" in out


def test_a_multi_line_validation_report_keeps_its_lines(tmp_path, capsys):
    """Sanitising the CLI print must not flatten OUR OWN newlines: a config report is deliberately
    multi-line and one long line costs the reader the list of what is actually wrong."""
    (tmp_path / ".tautline.json").write_text(
        json.dumps(lean_cfg(provider="github", repo="not-a-repo")), encoding="utf-8"
    )
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    assert "backlog.repo must be 'owner/name'" in out
    assert out.count("\n") >= 2, out


def test_the_reference_line_sanitises_both_halves():
    item = backlog.Item(id="12\x1b[31m", title="t", url="https://x/\x07")
    assert "\x1b" not in item.reference() and "\x07" not in item.reference()


# ================================================================================================
# local: QUEUE.md + ready/building/done
# ================================================================================================


@pytest.fixture
def local(tmp_path) -> backlog.LocalBacklog:
    return backlog.LocalBacklog(root=tmp_path)


def test_the_local_loop_end_to_end(local, tmp_path):
    first = local.add("Collapse legacy config validation", "one page of why")
    second = local.add("Promote lean to main")
    assert [item.id for item in local.list()] == [first.id, second.id], "add appends to the END"
    assert (tmp_path / "ready" / f"{first.id}.md").read_text(encoding="utf-8").startswith(
        "# Collapse legacy config validation"
    )

    taken = local.take()
    assert taken.id == first.id, "take with no id takes the TOP of the queue"
    assert taken.state == backlog.IN_PROGRESS
    assert (tmp_path / "building" / f"{first.id}.md").is_file()
    assert not (tmp_path / "ready" / f"{first.id}.md").exists()

    finished = local.done(first.id)
    assert finished.state == backlog.DONE
    assert (tmp_path / "done" / f"{first.id}.md").is_file()
    assert [item.id for item in local.list()] == [second.id], "list is the QUEUE, not the archive"


def test_directory_membership_is_the_state(local, tmp_path):
    item = local.add("Something")
    local.take(item.id)
    assert f"building/{item.id}.md" in (tmp_path / "QUEUE.md").read_text(encoding="utf-8")
    assert local.list()[0].state == backlog.IN_PROGRESS


def test_rows_are_renumbered_so_the_top_of_the_list_is_always_next(local, tmp_path):
    for title in ("One", "Two", "Three"):
        local.add(title)
    local.done(local.list()[0].id)
    table = [
        line
        for line in (tmp_path / "QUEUE.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and "](" in line
    ]
    assert [line.split("|")[1].strip() for line in table] == ["1", "2", "3"]


def test_a_title_containing_the_table_delimiter_survives_a_write(local):
    """The regression that made the round-trip guard non-negotiable: `|` is the table's delimiter
    and `[`/`]` are the link's, so a title carrying one used to render a row this module's own
    parser could not read back -- and the next write dropped it with no error anywhere."""
    kept = local.add("Second | piped [item]")
    local.add("Third")
    local.take(local.list()[0].id)
    assert [item.title for item in local.list()] == ["Second | piped [item]", "Third"]
    assert kept.id in {item.id for item in local.list()}


def test_prose_after_the_table_survives_a_write(local, tmp_path):
    """The queue file is a DOCUMENT. Keeping only the lines BEFORE the first row deleted every
    section under the table on the next `add` -- a project's notes, gone, silently."""
    (tmp_path / "QUEUE.md").write_text(
        "# Backlog Queue\n\nSpecs are ONE PAGE.\n\n"
        "| # | Item | Notes |\n|---|------|-------|\n\n"
        "## Conventions\n\nAnything below the table is ours and must survive.\n",
        encoding="utf-8",
    )
    local.add("New one")
    text = (tmp_path / "QUEUE.md").read_text(encoding="utf-8")
    assert "Specs are ONE PAGE." in text
    assert "## Conventions" in text
    assert "Anything below the table is ours and must survive." in text
    assert "New one" in text


def test_the_notes_cell_round_trips(local, tmp_path):
    (tmp_path / "QUEUE.md").write_text(
        "# Q\n\n| # | Item | Notes |\n|---|------|-------|\n"
        "| 1 | [Existing](ready/existing.md) | BUILDING \\| owner: octocat |\n",
        encoding="utf-8",
    )
    (tmp_path / "ready").mkdir()
    (tmp_path / "ready" / "existing.md").write_text("# Existing\n", encoding="utf-8")
    local.add("Second")
    rows = local._rows()
    assert rows[0]["notes"] == "BUILDING | owner: octocat"
    assert [row["title"] for row in rows] == ["Existing", "Second"]


@pytest.mark.parametrize("verb", ["add", "take", "done"])
def test_the_write_guard_refuses_rather_than_losing_a_row(local, tmp_path, monkeypatch, verb):
    """The checking layer, proven against a planted defect on EVERY write path.

    The contract is that the file is left alone AND no spec file has moved -- an earlier version
    validated after `shutil.move`, so its refusal said "unchanged" while the file had already gone.
    """
    keep = local.add("Keep me")
    before_text = (tmp_path / "QUEUE.md").read_text(encoding="utf-8")
    before_paths = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.md"))
    monkeypatch.setattr(backlog, "_escape", lambda text: text)
    with pytest.raises(backlog.BacklogError) as excinfo:
        if verb == "add":
            local.add("Broken | title")
        elif verb == "take":
            monkeypatch.setattr(local, "_rows", lambda: [{"title": "a|b", "path": "ready/x.md",
                                                          "notes": ""}])
            (tmp_path / "ready" / "x.md").write_text("# x\n", encoding="utf-8")
            local.take("x")
        else:
            monkeypatch.setattr(local, "_rows", lambda: [{"title": "a|b", "path": "ready/x.md",
                                                          "notes": ""}])
            (tmp_path / "ready" / "x.md").write_text("# x\n", encoding="utf-8")
            local.done("x")
    message = str(excinfo.value)
    assert "no file has been moved" in message
    assert (tmp_path / "QUEUE.md").read_text(encoding="utf-8") == before_text
    if verb == "add":
        assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.md")) == before_paths
    else:
        assert (tmp_path / "ready" / "x.md").is_file(), "the spec file must not have moved"
    # Read the file, not the provider: `_rows` is monkeypatched on the take/done legs.
    assert keep.title in (tmp_path / "QUEUE.md").read_text(encoding="utf-8")


def test_the_write_is_atomic_and_leaves_no_temporary_behind(local, tmp_path):
    """`write_text` truncates in place, so an interrupted write leaves a half-written queue -- the
    one file that says what the whole project is doing next."""
    local.add("One")
    local.add("Two")
    leftovers = [p.name for p in tmp_path.iterdir() if "tautline-tmp" in p.name]
    assert leftovers == []
    assert (tmp_path / "QUEUE.md").read_text(encoding="utf-8").endswith("|\n")


def test_an_unknown_id_names_the_ids_that_exist(local):
    local.add("Only item")
    with pytest.raises(backlog.BacklogError) as excinfo:
        local.done("no-such-item")
    message = str(excinfo.value)
    assert "no-such-item" in message and "only-item" in message


def test_taking_an_item_twice_is_refused(local):
    item = local.add("Once")
    local.take(item.id)
    with pytest.raises(backlog.BacklogError, match="already in-progress"):
        local.take(item.id)


def test_taking_from_an_empty_queue_says_how_to_file_one(local):
    with pytest.raises(backlog.BacklogError) as excinfo:
        local.take()
    assert "tautline backlog add" in str(excinfo.value)


def test_a_row_whose_file_vanished_is_refused_not_silently_rewritten(local, tmp_path):
    item = local.add("Ghost")
    (tmp_path / "ready" / f"{item.id}.md").unlink()
    with pytest.raises(backlog.BacklogError) as excinfo:
        local.take(item.id)
    assert "does not exist" in str(excinfo.value)


def test_ids_do_not_collide_when_two_items_share_a_title(local):
    first = local.add("Same title")
    second = local.add("Same title")
    assert first.id != second.id
    assert {item.id for item in local.list()} == {first.id, second.id}


def test_the_queue_file_path_is_configurable(tmp_path):
    provider = backlog.LocalBacklog(root=tmp_path, queue_path="docs/QUEUE.md")
    item = provider.add("Nested")
    assert (tmp_path / "docs" / "QUEUE.md").is_file()
    assert (tmp_path / "docs" / "ready" / f"{item.id}.md").is_file()
    assert provider.describe() == "local (docs/QUEUE.md)"


# ================================================================================================
# github: labelled issues over plain REST
# ================================================================================================


@pytest.fixture
def gh(github_env) -> backlog.GitHubBacklog:
    return backlog.GitHubBacklog(repo="acme/demo")


def test_github_list_reads_open_issues_by_label_oldest_first(gh, http):
    http.route(
        "GET /repos/acme/demo/issues",
        [_issue(7, "Older"), _issue(9, "Newer", labels=("backlog", "in-progress"))],
    )
    items = list(gh.list())
    assert [(item.id, item.state) for item in items] == [
        ("7", backlog.READY),
        ("9", backlog.IN_PROGRESS),
    ]
    assert items[0].url == "https://github.com/acme/demo/issues/7"
    query = http.calls[0]["query"]
    for expected in ("labels=backlog", "state=open", "sort=created", "direction=asc"):
        assert expected in query, query


def test_github_pins_per_page_at_100(gh, http):
    """GitHub's default page size is 30. Dropping the parameter would silently return the first 30
    items of a longer backlog and every count taken from it would be wrong."""
    http.route("GET /repos/acme/demo/issues", [])
    gh.list()
    assert "per_page=100" in http.calls[0]["query"]


def test_github_follows_the_link_header_to_the_end(gh, http):
    """GitHub signals "there is more" ONLY in the `Link` header: the body of a list endpoint is a
    bare array with no cursor, no total and no next field. A single-request implementation returns
    page one and looks entirely correct."""
    page2 = "https://api.github.com/repos/acme/demo/issues?page=2"
    http.route(
        "GET /repos/acme/demo/issues",
        [_issue(1, "One"), _issue(2, "Two")],
        {"Link": f'<{page2}>; rel="next", <{page2}>; rel="last"'},
    )
    http.route("GET /repos/acme/demo/issues", [_issue(3, "Three")])
    assert [item.id for item in gh.list()] == ["1", "2", "3"]
    assert len(http.calls) == 2, "it must stop when the Link header stops offering a next page"


def test_github_refuses_a_next_page_that_points_off_api_github_com(gh, http):
    """The next URL is chosen by the RESPONSE. Following it blindly would let one spoofed header
    redirect the bearer token to any host."""
    http.route(
        "GET /repos/acme/demo/issues",
        [_issue(1, "One")],
        {"Link": '<https://evil.example/steal>; rel="next"'},
    )
    with pytest.raises(backlog.BacklogError, match="talks only to https://api.github.com"):
        gh.list()


def test_github_pagination_is_bounded(gh, http):
    forever = "https://api.github.com/repos/acme/demo/issues?page=2"
    http.route(
        "GET /repos/acme/demo/issues", [_issue(1, "One")], {"Link": f'<{forever}>; rel="next"'}
    )
    with pytest.raises(backlog.BacklogError, match="kept offering another page"):
        gh.list()
    assert len(http.calls) == backlog.MAX_PAGES


def test_github_never_touches_the_projects_graphql_api(gh, http):
    """A measured rule: `gh project item-list` cost 102 GraphQL points per call against a
    5,000-point hourly budget where the REST equivalent cost 1."""
    http.route("GET /repos/acme/demo/issues", [_issue(1, "One")])
    http.route("POST /repos/acme/demo/issues", _issue(2, "Two"))
    http.route("POST /repos/acme/demo/issues/1/labels", [])
    http.route("GET /user", {"login": "octocat"})
    http.route(
        "PATCH /repos/acme/demo/issues/1", _issue(1, "One", labels=("backlog", "in-progress"))
    )
    http.route("GET /repos/acme/demo/issues/1", _issue(1, "One", labels=("backlog", "in-progress")))
    gh.list()
    gh.add("Two")
    gh.take("1")
    assert http.calls, "the guard would pass vacuously if nothing was requested"
    for url in http.urls():
        assert "graphql" not in url.lower(), url
        assert "/projects" not in url, url


def test_github_list_drops_pull_requests(gh, http):
    pull = dict(_issue(5, "A pull request"), pull_request={"url": "..."})
    http.route("GET /repos/acme/demo/issues", [_issue(4, "Real work"), pull])
    assert [item.id for item in gh.list()] == ["4"]


def test_github_add_creates_a_labelled_issue(gh, http):
    http.route("POST /repos/acme/demo/issues", _issue(11, "Filed"))
    item = gh.add("Filed", "the one-page spec")
    assert item.id == "11" and item.url.endswith("/11")
    assert http.calls[0]["body"] == {
        "title": "Filed",
        "body": "the one-page spec",
        "labels": ["backlog"],
    }


def test_github_add_refuses_when_the_label_was_silently_dropped(gh, http):
    """A 201 IS NOT SUCCESS HERE. GitHub drops `labels` when the token cannot write to the
    repository's issues, and the label is what `list` filters on -- so reporting success would hand
    back an id and a URL for an item the queue will never show again."""
    http.route("POST /repos/acme/demo/issues", _issue(12, "Filed", labels=()))
    with pytest.raises(backlog.BacklogError) as excinfo:
        gh.add("Filed")
    message = str(excinfo.value)
    assert "12" in message and "backlog" in message
    assert "issues:write" in message and "will not show it" in message


def test_github_take_labels_and_assigns_the_viewer(gh, http):
    taken = _issue(3, "Taken", labels=("backlog", "in-progress"))
    http.route("GET /user", {"login": "octocat"})
    http.route("POST /repos/acme/demo/issues/3/labels", [])
    http.route("PATCH /repos/acme/demo/issues/3", taken)
    http.route("GET /repos/acme/demo/issues/3", taken)
    item = gh.take("3")
    assert item.state == backlog.IN_PROGRESS
    assert gh.notices == []
    methods = [(call["method"], call["path"]) for call in http.calls]
    assert methods[0] == ("GET", "/user"), "the read comes first so a failure mutates nothing"
    assert ("POST", "/repos/acme/demo/issues/3/labels") in methods


def test_github_take_survives_an_installation_token_that_cannot_read_user(gh, http):
    """`GET /user` answers 403 "Resource not accessible by integration" for a GitHub Actions
    installation token. Treating that as fatal made `take` fail in CI AFTER the label was written,
    leaving the issue half-taken. The assignee is a courtesy; the label is the state carrier."""
    taken = _issue(4, "Taken", labels=("backlog", "in-progress"))
    http.fail("GET /user", 403, {"message": "Resource not accessible by integration"})
    http.route("POST /repos/acme/demo/issues/4/labels", [])
    http.route("GET /repos/acme/demo/issues/4", taken)
    item = gh.take("4")
    assert item.state == backlog.IN_PROGRESS
    assert gh.notices and "assignee not resolved" in gh.notices[0]
    assert "Resource not accessible by integration" in gh.notices[0]
    assert not any(call["method"] == "PATCH" for call in http.calls)


def test_github_take_reports_a_skipped_assignee_write(gh, http):
    taken = _issue(5, "Taken", labels=("backlog", "in-progress"))
    http.route("GET /user", {"login": "octocat"})
    http.route("POST /repos/acme/demo/issues/5/labels", [])
    http.fail("PATCH /repos/acme/demo/issues/5", 403)
    http.route("GET /repos/acme/demo/issues/5", taken)
    item = gh.take("5")
    assert item.state == backlog.IN_PROGRESS
    assert gh.notices and "assignee not set on #5" in gh.notices[0]


def test_github_take_errors_when_the_board_did_not_actually_change(gh, http):
    """2xx is not evidence. The label write can be accepted and not take effect; reporting success
    from the status code is the success-without-verification class this framework died of."""
    http.route("GET /user", {"login": "octocat"})
    http.route("POST /repos/acme/demo/issues/6/labels", [])
    http.route("PATCH /repos/acme/demo/issues/6", _issue(6, "Nope"))
    http.route("GET /repos/acme/demo/issues/6", _issue(6, "Nope"))  # label never landed
    with pytest.raises(backlog.BacklogError) as excinfo:
        gh.take("6")
    assert "reading it back shows 'ready'" in str(excinfo.value)


def test_github_take_with_no_id_takes_the_top_of_the_queue(gh, http):
    taken = _issue(21, "Top", labels=("backlog", "in-progress"))
    http.route("GET /repos/acme/demo/issues", [_issue(21, "Top"), _issue(22, "Next")])
    http.route("GET /user", {"login": "octocat"})
    http.route("POST /repos/acme/demo/issues/21/labels", [])
    http.route("PATCH /repos/acme/demo/issues/21", taken)
    http.route("GET /repos/acme/demo/issues/21", taken)
    assert gh.take().id == "21"


def test_github_revalidates_an_id_the_board_supplied(gh, http):
    """An id from a board response goes back through the same grammar check a hand-typed one does,
    because it is interpolated into a URL path."""
    http.route("GET /repos/acme/demo/issues", [dict(_issue(1, "Top"), number="../../evil")])
    with pytest.raises(backlog.BacklogError, match="not a GitHub issue number"):
        gh.take()


def test_github_done_closes_the_issue(gh, http):
    closed = _issue(8, "Shipped", state="closed")
    http.route("PATCH /repos/acme/demo/issues/8", closed)
    http.route("GET /repos/acme/demo/issues/8", closed)
    item = gh.done("#8")
    assert item.state == backlog.DONE
    assert http.calls[0]["body"] == {"state": "closed", "state_reason": "completed"}


def test_github_done_errors_when_the_issue_is_still_open(gh, http):
    http.route("PATCH /repos/acme/demo/issues/9", _issue(9, "Still open"))
    http.route("GET /repos/acme/demo/issues/9", _issue(9, "Still open"))
    with pytest.raises(backlog.BacklogError, match="reading it back shows 'ready'"):
        gh.done("9")


def test_github_refuses_an_id_that_is_not_an_issue_number(gh):
    with pytest.raises(backlog.BacklogError, match="not a GitHub issue number"):
        gh.done("PROJ-12")


def test_github_names_the_environment_variables_when_no_token_exists(monkeypatch, http):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: "")
    with pytest.raises(backlog.BacklogError) as excinfo:
        backlog.GitHubBacklog(repo="acme/demo").list()
    message = str(excinfo.value)
    assert "GITHUB_TOKEN" in message and "GH_TOKEN" in message and "gh auth login" in message
    assert not http.calls, "the refusal must happen before a socket is opened"


def test_github_falls_back_to_the_gh_cli_token(monkeypatch, http):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: GH_TOKEN)
    http.route("GET /repos/acme/demo/issues", [])
    assert list(backlog.GitHubBacklog(repo="acme/demo").list()) == []
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {GH_TOKEN}"


def test_github_rejection_names_the_credentials_and_carries_the_servers_own_words(gh, http):
    http.fail(
        "GET /repos/acme/demo/issues",
        401,
        {"message": "Bad credentials", "errors": [{"field": "token", "code": "invalid"}]},
    )
    with pytest.raises(backlog.BacklogError) as excinfo:
        gh.list()
    message = str(excinfo.value)
    assert "GITHUB_TOKEN" in message and "gh auth login" in message
    assert "Bad credentials" in message and "token: invalid" in message
    assert GH_TOKEN not in message


def test_github_404_points_at_the_configured_repo(gh, http):
    http.fail("GET /repos/acme/demo/issues", 404)
    with pytest.raises(backlog.BacklogError) as excinfo:
        gh.list()
    assert "backlog.repo" in str(excinfo.value) and "acme/demo" in str(excinfo.value)


#: `stakeholder_question` joined 2026-08-29 (Tier 1 salvage, track S2): its `_GitHubCommentClient`
#: is a THIRD transport that talks to api.github.com with a bearer token, so it must be found by
#: this walk exactly like the two providers below -- an opener this discovery cannot see is a
#: redirect refusal nobody is actually checking (the "discovery vs checking" defect class: see
#: `test_the_transport_discovery_actually_finds_the_transports` for why an empty/narrow walk makes
#: the guard beneath it pass by comparing against nothing).
#: `builder_github` joined 2026-09-05: its `_Client` is a FOURTH transport with a bearer token, and
#: the first that POSTs to the GraphQL endpoint. Added to the walk in the same change that
#: introduced it, because a transport that this discovery cannot see is a transport whose redirect
#: refusal nothing checks -- which is exactly how the missing one shipped the first time.
#: `builder_token` joined 2026-09-05 at INTEGRATION, and it is the reason the walk below grew a
#: second shape. It is a FIFTH bearer-token transport and it carries the most dangerous credential
#: in the subsystem -- an App JWT, which mints installation tokens for every repository the App is
#: installed on -- but it has no client CLASS: its `_build_opener` is a module-level function
#: beside a module-level `_request`. The three lanes disagreed about that shape, and the disagreement
#: is exactly the defect this walk exists to catch: a class-only walk would have imported the module,
#: found nothing in it, and reported the same green it reports for a module with no transport at all.
#: Discovery follows the credential, not the code shape.
SUBSYSTEM = (backlog, jira_client, stakeholder_question, builder_github, builder_token)


def _discovered_transports() -> dict:
    """Every opener-builder in the subsystem, class-bound or module-level. THE DISCOVERY LAYER.

    Enumerated, never listed. A hand-written list of the transports that exist today is a checking
    layer with no discovery layer: the next transport is simply absent from it and the suite stays
    green -- the exact shape that let a missing redirect refusal ship.

    Both shapes are walked because the subsystem uses both. Four transports put `_build_opener` on
    the client class as a staticmethod; `builder_token` puts it at module level because it has no
    client object to hang it on. Keying only on the class shape would make the walk silently blind
    to the second, which is a discovery layer that reports on a subset while presenting itself as
    the whole -- the same failure the module-level entry below is here to prevent.
    """
    found = {}
    for module in SUBSYSTEM:
        short = module.__name__.rsplit(".", 1)[-1]
        for name, obj in vars(module).items():
            if inspect.isclass(obj) and getattr(obj, "__module__", "") == module.__name__:
                if callable(getattr(obj, "_build_opener", None)):
                    found[f"{short}.{name}"] = obj
            elif (
                inspect.isfunction(obj)
                and name == "_build_opener"
                and getattr(obj, "__module__", "") == module.__name__
            ):
                # Wrapped in a shim with the same `_build_opener` staticmethod attribute the class
                # transports expose, so everything downstream -- the refusal probe, the planted
                # defect -- treats both shapes identically instead of branching on them.
                found[f"{short}.{name}"] = type(
                    "_ModuleTransport", (), {"_build_opener": staticmethod(obj)}
                )
    return found


def _refuses_redirects(opener) -> bool:
    """Whether this opener REFUSES a redirect, asked behaviourally rather than by class name.

    Probed with a real `Request` on purpose. urllib's stock handler returns a new Request; a
    refusing one raises. Probing with `None` would make the stock handler raise an AttributeError
    that reads exactly like a refusal -- a guard that passes on the transport it exists to catch.
    """
    request = urllib.request.Request("https://api.github.com/probe")
    for handler in opener.handlers:
        if not isinstance(handler, urllib.request.HTTPRedirectHandler):
            continue
        try:
            handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/")
        except Exception:
            return True
        return False
    return False  # no redirect handler at all: urllib's default behaviour is to FOLLOW


def test_the_transport_discovery_actually_finds_the_transports():
    """Discovery, asserted separately from the check that consumes it. An empty or broken walk
    would make the guard below pass by comparing against nothing."""
    discovered = _discovered_transports()
    assert set(discovered) == {
        "backlog.GitHubBacklog",
        "builder_github._Client",
        "builder_token._build_opener",
        "jira_client.JiraClient",
        "stakeholder_question._GitHubCommentClient",
    }, discovered


def test_every_discovered_http_transport_refuses_redirects():
    """urllib follows redirects by default and RE-SENDS headers, so a 302 hands the credential to
    whatever host the response names. Every transport in this subsystem must refuse."""
    for name, transport in _discovered_transports().items():
        assert _refuses_redirects(transport._build_opener()), (
            f"{name} builds an opener that FOLLOWS redirects, so its Authorization header would be "
            "replayed at whatever host a 302 names."
        )


def test_the_redirect_guard_catches_a_transport_that_forgot(monkeypatch):
    """The planted defect. A new transport that builds a stock opener must FAIL this guard, or the
    guard is decoration -- and it must be found by the walk, not by having been added to a list."""

    class _ForgetfulTransport:
        @staticmethod
        def _build_opener():
            return urllib.request.build_opener()

    _ForgetfulTransport.__module__ = backlog.__name__
    monkeypatch.setattr(backlog, "_ForgetfulTransport", _ForgetfulTransport, raising=False)
    assert "backlog._ForgetfulTransport" in _discovered_transports(), "the walk must FIND it"
    assert not _refuses_redirects(_ForgetfulTransport._build_opener())
    with pytest.raises(AssertionError, match="FOLLOWS redirects"):
        test_every_discovered_http_transport_refuses_redirects()


def test_no_transport_bypasses_its_opener():
    """The other half of discovery. A transport that called `urlopen` directly would never touch a
    `_build_opener` at all, so the walk above could not see it and the refusal would be absent."""
    for module in SUBSYSTEM:
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "urlopen(" not in source, (
            f"{module.__name__} calls urlopen directly, which bypasses the opener carrying the "
            "redirect refusal. Route it through `_build_opener()`."
        )


def test_each_refusal_names_its_own_modules_error_type():
    """The two handlers are separate BECAUSE each raises its own module's error type; a caller
    catching one would not catch the other. This is the property that justifies not sharing them."""
    with pytest.raises(backlog.BacklogError, match="Authorization header would be replayed"):
        backlog._RefuseRedirect().redirect_request(
            urllib.request.Request("https://api.github.com/x"), None, 302, "F", {}, "https://evil"
        )
    with pytest.raises(jira_client.JiraTransportError, match="Authorization header would be"):
        jira_client._NoCredentialRedirectHandler().redirect_request(
            urllib.request.Request(f"{SITE}/x"), None, 302, "F", {}, "https://evil"
        )


# ================================================================================================
# jira: salvaged client, re-seated
# ================================================================================================


@pytest.fixture
def jira(jira_env) -> backlog.JiraBacklog:
    return backlog.JiraBacklog(site=SITE, project="PROJ")


def test_jira_list_orders_by_created_without_a_board(jira, http):
    http.route(
        "GET /rest/api/3/search/jql", {"issues": [_jira_issue("PROJ-1", "First")], "isLast": True}
    )
    items = list(jira.list())
    assert [(item.id, item.url) for item in items] == [("PROJ-1", f"{SITE}/browse/PROJ-1")]
    assert items[0].body == "spec PROJ-1", "the ADF description is rendered as plain text"
    query = urllib.parse.unquote_plus(http.calls[0]["query"])
    assert 'project = "PROJ"' in query and "ORDER BY created ASC" in query
    assert "statusCategory != Done" in query


def test_jira_search_follows_the_page_token_until_is_last(jira, http):
    """`/search/jql` is TOKEN-paginated: `{isLast, issues, nextPageToken}`, with no total and no
    `startAt` parameter. An offset pager against it re-reads page one forever while every response
    says 200 -- a backlog that silently reports only its first page."""
    http.route(
        "GET /rest/api/3/search/jql",
        {"issues": [_jira_issue("PROJ-1", "One")], "isLast": False, "nextPageToken": "cursor-2"},
    )
    http.route(
        "GET /rest/api/3/search/jql",
        {"issues": [_jira_issue("PROJ-2", "Two")], "isLast": True},
    )
    assert [item.id for item in jira.list()] == ["PROJ-1", "PROJ-2"]
    queries = http.queries("/rest/api/3/search/jql")
    assert len(queries) == 2
    assert "startAt" not in queries[0], "/search/jql does not accept startAt"
    assert "nextPageToken=cursor-2" in queries[1]


def test_jira_search_stops_when_the_token_stops_being_offered(jira, http):
    http.route("GET /rest/api/3/search/jql", {"issues": [_jira_issue("PROJ-1", "One")]})
    assert [item.id for item in jira.list()] == ["PROJ-1"]
    assert len(http.calls) == 1


def test_jira_search_refuses_a_repeating_cursor_rather_than_under_counting(jira, http):
    http.route(
        "GET /rest/api/3/search/jql",
        {"issues": [_jira_issue("PROJ-1", "One")], "isLast": False, "nextPageToken": "same"},
    )
    http.route(
        "GET /rest/api/3/search/jql",
        {"issues": [_jira_issue("PROJ-2", "Two")], "isLast": False, "nextPageToken": "same"},
    )
    with pytest.raises(backlog.BacklogError, match="same page cursor twice"):
        jira.list()


def test_jira_board_paging_steps_by_the_maxresults_the_server_granted(jira_env, http):
    """Atlassian's own wording is "you can ask for more than you are given". Advancing `startAt` by
    the REQUESTED size after being handed a smaller page steps straight over the issues between --
    and every one of them silently vanishes from the queue."""
    provider = backlog.JiraBacklog(site=SITE, project="PROJ", board="12")
    granted = {"maxResults": 2, "total": 5}
    http.route(
        "GET /rest/agile/1.0/board/12/issue",
        dict(granted, startAt=0, issues=[_jira_issue("PROJ-1", "a"), _jira_issue("PROJ-2", "b")]),
    )
    http.route(
        "GET /rest/agile/1.0/board/12/issue",
        dict(granted, startAt=2, issues=[_jira_issue("PROJ-3", "c"), _jira_issue("PROJ-4", "d")]),
    )
    http.route(
        "GET /rest/agile/1.0/board/12/issue",
        dict(granted, startAt=4, issues=[_jira_issue("PROJ-5", "e")]),
    )
    assert [item.id for item in provider.list()] == [f"PROJ-{n}" for n in range(1, 6)]
    offsets = [
        q.split("startAt=")[1].split("&")[0]
        for q in http.queries("/rest/agile/1.0/board/12/issue")
    ]
    assert offsets == ["0", "2", "4"], "the step must follow the granted page, not the request"
    assert "ORDER BY Rank ASC" in http.queries("/rest/agile/1.0/board/12/issue")[0]


def test_jira_add_resolves_the_projects_own_issue_type_id(jira, http):
    """`{"name": "Task"}` is not a documented v3 create shape and names are not unique across issue
    type schemes, so it is a guess that fails as an opaque 400 on any project whose scheme differs."""
    _route_createmeta(http)
    http.route("POST /rest/api/3/issue", {"key": "PROJ-9"})
    item = jira.add("Filed from the CLI", "why it matters")
    assert item.id == "PROJ-9" and item.url == f"{SITE}/browse/PROJ-9"
    fields = next(c for c in http.calls if c["method"] == "POST")["body"]["fields"]
    assert fields["issuetype"] == {"id": "10001"}, "the non-subtask Task, by id"
    assert fields["project"] == {"key": "PROJ"} and fields["summary"] == "Filed from the CLI"
    assert backlog._adf_text(fields["description"]) == "why it matters"


def test_jira_add_refuses_when_the_project_offers_no_usable_issue_type(jira, http):
    http.route(
        "GET /rest/api/3/issue/createmeta/PROJ/issuetypes",
        {"issueTypes": [{"id": "1", "name": "Sub-task", "subtask": True}], "total": 1},
    )
    with pytest.raises(backlog.BacklogError, match="no non-subtask issue type"):
        jira.add("Filed")


def test_jira_take_and_done_select_a_transition_by_id(jira, http):
    http.route(
        "GET /rest/api/3/issue/PROJ-3/transitions",
        {
            "transitions": [
                {"id": "31", "name": "In Progress", "isGlobal": False, "to": {"name": "Doing"}},
                {"id": "41", "name": "Done", "isGlobal": True},
            ]
        },
    )
    http.route("POST /rest/api/3/issue/PROJ-3/transitions", None)
    http.route("GET /rest/api/3/issue/PROJ-3", _jira_issue("PROJ-3", "Moving", "indeterminate"))
    item = jira.take("proj-3")
    assert item.id == "PROJ-3" and item.state == backlog.IN_PROGRESS
    posted = [call for call in http.calls if call["method"] == "POST"]
    assert posted[0]["body"] == {"transition": {"id": "31"}}


def test_jira_refuses_an_ambiguous_transition_name_instead_of_guessing(jira, http):
    """A transition NAME is not unique -- a global `Done` and a status-specific `Done` in one
    workflow is common -- and first-match-wins fires whichever the API listed first, moving the
    issue somewhere nobody asked for while reporting success."""
    http.route(
        "GET /rest/api/3/issue/PROJ-7/transitions",
        {
            "transitions": [
                {"id": "41", "name": "Done", "isGlobal": True, "to": {"name": "Closed"}},
                {"id": "51", "name": "Done", "isGlobal": False, "to": {"name": "Resolved"}},
            ]
        },
    )
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.done("PROJ-7")
    message = str(excinfo.value)
    assert "2 transitions named 'Done'" in message and "will not guess" in message
    assert "id 41" in message and "id 51" in message
    assert "global" in message and "status-specific" in message
    assert not any(call["method"] == "POST" for call in http.calls), "nothing may have fired"


def test_jira_names_the_available_transitions_when_the_workflow_differs(jira, http):
    http.route(
        "GET /rest/api/3/issue/PROJ-4/transitions",
        {
            "transitions": [
                {"id": "11", "name": "Start Progress", "isGlobal": False},
                {"id": "21", "name": "Park\x1b[2K", "isGlobal": True},
            ]
        },
    )
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.take("PROJ-4")
    message = str(excinfo.value)
    assert "Start Progress" in message and "In Progress" in message and "id 11" in message
    assert "\x1b" not in message, "a transition name is remote text and is sanitised like any other"


def test_jira_take_errors_when_the_transition_landed_in_another_category(jira, http):
    http.route(
        "GET /rest/api/3/issue/PROJ-8/transitions",
        {"transitions": [{"id": "31", "name": "In Progress", "isGlobal": False}]},
    )
    http.route("POST /rest/api/3/issue/PROJ-8/transitions", None)
    http.route("GET /rest/api/3/issue/PROJ-8", _jira_issue("PROJ-8", "Still new", "new"))
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.take("PROJ-8")
    assert "reading it back shows 'ready'" in str(excinfo.value)


def test_jira_refuses_an_id_that_is_not_an_issue_key(jira):
    with pytest.raises(backlog.BacklogError, match="not a Jira issue key"):
        jira.done("42")


def test_jira_revalidates_a_key_the_board_supplied(jira, http):
    http.route(
        "GET /rest/api/3/search/jql",
        {"issues": [dict(_jira_issue("PROJ-1", "Top"), key="../../evil")], "isLast": True},
    )
    with pytest.raises(backlog.BacklogError, match="not a Jira issue key"):
        jira.take()


def test_jira_names_the_environment_variables_before_opening_a_socket(monkeypatch, http):
    monkeypatch.delenv(jira_client.EMAIL_ENV, raising=False)
    monkeypatch.delenv(jira_client.API_TOKEN_ENV, raising=False)
    with pytest.raises(backlog.BacklogError) as excinfo:
        backlog.JiraBacklog(site=SITE, project="PROJ").list()
    message = str(excinfo.value)
    assert jira_client.EMAIL_ENV in message and jira_client.API_TOKEN_ENV in message
    assert not http.calls, "an unset credential is knowable locally; it must not cost a round trip"


def test_jira_refuses_to_attach_credentials_to_a_host_that_is_not_jira_cloud(jira_env, http):
    provider = backlog.JiraBacklog(site="https://attacker.example", project="PROJ")
    with pytest.raises(backlog.BacklogError, match="Refusing to send Jira credentials"):
        provider.list()
    assert not http.calls


def test_jira_rejection_carries_both_halves_of_the_error_collection(jira, http):
    """Jira answers in `errorMessages` for some faults and in the `errors` map for others. Reading
    one half turns a precise server-side diagnosis into "HTTP 400"."""
    http.fail(
        "GET /rest/api/3/search/jql",
        400,
        {"errorMessages": ["The JQL query is invalid."], "errors": {"jql": "unknown field 'Rank'"}},
    )
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.list()
    message = str(excinfo.value)
    assert "The JQL query is invalid." in message
    assert "jql: unknown field 'Rank'" in message


def test_jira_rejection_names_the_credentials_and_never_prints_one(jira, http):
    http.fail("GET /rest/api/3/search/jql", 401, {"errorMessages": ["Client must be authenticated"]})
    with pytest.raises(backlog.BacklogError) as excinfo:
        jira.list()
    message = str(excinfo.value)
    assert jira_client.EMAIL_ENV in message and jira_client.API_TOKEN_ENV in message
    assert "Client must be authenticated" in message
    assert TOKEN not in message and EMAIL not in message


def test_the_jira_cache_is_keyed_on_identity_and_embeds_no_credential(jira_env, http, monkeypatch):
    """Two accounts on ONE site must not share a cache entry: the second would be served the
    first's payload without ever authenticating, including issues its permissions would hide."""
    http.route("GET /rest/api/3/search/jql", {"issues": [], "isLast": True})
    backlog.JiraBacklog(site=SITE, project="PROJ").list()
    keys_one = jira_client.cache_keys()
    monkeypatch.setenv(jira_client.EMAIL_ENV, "other@example.invalid")
    backlog.JiraBacklog(site=SITE, project="PROJ").list()
    assert len(jira_client.cache_keys()) == len(keys_one) + 1
    for key in jira_client.cache_keys():
        assert TOKEN not in key and "other@example.invalid" not in key


def test_a_jira_credential_renders_as_redacted_wherever_it_is_printed(jira_env):
    client = jira_client.JiraClient(site_url=SITE)
    assert TOKEN not in repr(client) and TOKEN not in str(client)
    secret = jira_client.Secret(TOKEN)
    assert repr(secret) == "<redacted>" and str(secret) == "<redacted>"
    assert secret.reveal() == TOKEN


def test_a_jira_write_invalidates_item_data_but_not_the_field_schema(jira_env, http):
    http.route("GET /rest/api/3/field", [{"id": "summary"}])
    http.route("POST /rest/api/3/issue", {"key": "PROJ-5"})
    http.route("GET /rest/api/3/search/jql", {"issues": [], "isLast": True})
    client = jira_client.JiraClient(site_url=SITE)
    client.get("/rest/api/3/field", schema=True)
    client.get("/rest/api/3/search/jql")
    assert len(jira_client.cache_keys()) == 2
    client.post("/rest/api/3/issue", {"fields": {}})
    remaining = jira_client.cache_keys()
    assert len(remaining) == 1 and "/rest/api/3/field" in remaining[0]


# ================================================================================================
# the timeout is threaded, not merely stored
# ================================================================================================


def test_the_request_timeout_reaches_the_transport(jira_env, github_env, http):
    """A leash held by the caller and ignored by the transport is not a leash. The Jira client used
    its own 30s constant while the provider stored a 5s value nobody read, so lane-status' bound was
    void and an unreachable board would stall every session start."""
    http.route("GET /rest/api/3/search/jql", {"issues": [], "isLast": True})
    http.route("GET /repos/acme/demo/issues", [])
    backlog.JiraBacklog(site=SITE, project="PROJ", timeout=3).list()
    backlog.GitHubBacklog(repo="acme/demo", timeout=3).list()
    assert [call["timeout"] for call in http.calls] == [3, 3]


def test_lane_statuss_leash_actually_bounds_a_slow_board(tmp_path, jira_env, http):
    """The board takes longer than the advisory leash allows, so the line reports it rather than
    stalling a session start."""
    http.simulated_seconds = backlog.ADVISORY_TIMEOUT_SECONDS + 10
    http.route("GET /rest/api/3/search/jql", {"issues": [], "isLast": True})
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="jira", site=SITE, project="PROJ"))
    assert line is not None and "unreachable" in line and "timed out" in line
    assert http.calls[0]["timeout"] == backlog.ADVISORY_TIMEOUT_SECONDS


# ================================================================================================
# no fallback, no sync
# ================================================================================================


@pytest.mark.parametrize(
    "provider_block",
    [
        {"provider": "github", "repo": "acme/demo"},
        {"provider": "jira", "site": SITE, "project": "PROJ"},
    ],
)
def test_a_failing_remote_provider_never_writes_a_local_queue(
    tmp_path, monkeypatch, http, provider_block
):
    """THE NO-FALLBACK LAW. A silent local fallback recreates divergence between two backlogs, and
    the next thing anyone builds to fix divergence is a sync engine."""
    for env in ("GITHUB_TOKEN", "GH_TOKEN", jira_client.EMAIL_ENV, jira_client.API_TOKEN_ENV):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(backlog, "_gh_auth_token", lambda: "")
    provider = backlog.provider_for(tmp_path, lean_cfg(**provider_block))
    for call in (lambda: list(provider.list()), lambda: provider.add("Filed", "spec")):
        with pytest.raises(backlog.BacklogError):
            call()
    assert list(tmp_path.iterdir()) == [], "a remote failure must leave no local artifact behind"


def test_nothing_writes_except_the_four_commands(tmp_path):
    """THE NO-SYNC LAW, as behaviour rather than as prose: reading never writes."""
    provider = backlog.LocalBacklog(root=tmp_path)
    provider.add("One")
    before = sorted((path.name, path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))
    for _ in range(3):
        provider.list()
        provider.describe()
    assert sorted((path.name, path.stat().st_mtime_ns) for path in tmp_path.rglob("*")) == before


def test_no_test_can_execute_the_real_gh(monkeypatch):
    """The subprocess half of the network guard, proven rather than assumed.

    The socket guard blocks this process; `gh auth token` runs in another one. On a developer's
    machine it succeeds and hands back a REAL token, so a provider test that forgot its fake would
    be authenticated instead of refused -- through a channel the in-process guard cannot see.
    """

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a test executed a subprocess on the gh credential path")

    monkeypatch.setattr(backlog.subprocess, "run", _forbidden)
    assert backlog._gh_auth_token() == "", "the autouse stub must be in force"


def test_the_conftest_guard_blocks_a_forgotten_fake():
    """The layer under every provider suite. A developer running this suite usually has a real
    GITHUB_TOKEN exported, so a missing fake would otherwise mutate a live board and PASS."""
    import socket

    with pytest.raises(AssertionError, match="tried to open a network connection"):
        socket.socket().connect(("api.github.com", 443))


# ================================================================================================
# the advisory line lane-status prints
# ================================================================================================


def test_no_advisory_line_when_the_config_names_no_backlog(tmp_path):
    assert backlog.advisory_line(tmp_path, LEAN_BASE) is None


def test_the_advisory_line_reports_a_measured_count_and_the_top_item(tmp_path):
    provider = backlog.LocalBacklog(root=tmp_path)
    provider.add("Collapse legacy config validation")
    provider.add("Promote lean to main")
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="local"))
    assert line == "backlog: local (QUEUE.md) - 2 open, top: Collapse legacy config validation"


def test_the_advisory_line_says_unreachable_rather_than_inventing_a_count(tmp_path, monkeypatch):
    monkeypatch.delenv(jira_client.EMAIL_ENV, raising=False)
    monkeypatch.delenv(jira_client.API_TOKEN_ENV, raising=False)
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="jira", site=SITE, project="PROJ"))
    assert line is not None
    assert line.startswith("backlog: jira (PROJ) unreachable (")
    assert jira_client.EMAIL_ENV in line
    assert " open" not in line, "an unreachable board must never render a count"


def test_the_advisory_line_survives_an_unexpected_failure(tmp_path, monkeypatch):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(backlog, "provider_for", _explode)
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="local"))
    assert line is not None and "unreachable (RuntimeError:" in line


def test_a_broken_backlog_block_becomes_an_advisory_line_not_a_crash(tmp_path):
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="github"))
    assert line is not None and "unreachable" in line and "backlog.repo is required" in line


def test_the_advisory_line_is_sanitised(tmp_path):
    provider = backlog.LocalBacklog(root=tmp_path)
    provider.add("Fix \x1b[2K the thing")
    line = backlog.advisory_line(tmp_path, lean_cfg(provider="local"))
    assert line is not None and "\x1b" not in line


# ================================================================================================
# the rendered adapter norm
# ================================================================================================


def test_no_backlog_key_renders_no_backlog_line():
    assert "Backlog lives in" not in lean.render_lean_adapter(dict(LEAN_BASE))


@pytest.mark.parametrize(
    ("block", "expected", "closing"),
    [
        ({"provider": "local"}, "local (QUEUE.md)", "The queue file is the only backlog surface."),
        (
            {"provider": "github", "repo": "acme/demo"},
            "github (acme/demo)",
            "Never create backlog/TODO files in the repo.",
        ),
        (
            {"provider": "jira", "site": SITE, "project": "PROJ", "board": "12"},
            "jira (PROJ/board 12)",
            "Never create backlog/TODO files in the repo.",
        ),
    ],
)
def test_the_adapter_names_the_configured_board_and_forbids_a_second_one(block, expected, closing):
    text = lean.render_lean_adapter(lean_cfg(**block))
    line = next(line for line in text.splitlines() if line.startswith("Backlog lives in"))
    assert line.startswith(f"Backlog lives in {expected}.")
    assert "`tautline backlog add`" in line and "`tautline backlog list`" in line
    assert line.endswith(closing)


def test_the_adapter_stays_in_budget_with_both_optional_blocks_and_many_rules():
    """The worst case that can be configured: continuity handoffs ON (Track H's two norm lines) and
    a backlog configured (Track J's one), with more project rules than will fit. Both features are
    protected from the trim; only project rules are dropped, and the file says how many."""
    cfg = lean_cfg(provider="jira", site=SITE, project="PROJ", board="12")
    cfg["handoffs"] = True
    cfg["projectRules"] = [f"Rule {index}: " + ("x" * 90) for index in range(40)]
    for agent in ("Claude", "Codex"):
        text = lean.render_lean_adapter(cfg, agent=agent)
        assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
        assert "Backlog lives in jira (PROJ/board 12)." in text
        for line in lean.HANDOFF_PROCESS_LINES:
            assert line in text
        for norm in lean.PROCESS_NORMS:
            assert norm in text
        assert "further project rule(s) preserved" in text


# ================================================================================================
# the command
# ================================================================================================


def _write_config(root: Path, **block) -> None:
    (root / ".tautline.json").write_text(json.dumps(lean_cfg(**block)), encoding="utf-8")


def _namespace(target: Path, action: str, item: str | None = None, body: str = ""):
    return argparse.Namespace(action=action, item=item, target=target, body=body)


def test_the_command_runs_the_whole_local_loop(tmp_path, capsys):
    _write_config(tmp_path, provider="local")
    assert backlog.backlog_command(_namespace(tmp_path, "add", "Collapse legacy config")) == 0
    item_id = capsys.readouterr().out.split(":", 1)[1].split()[0]
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 0
    assert item_id in capsys.readouterr().out
    assert backlog.backlog_command(_namespace(tmp_path, "take")) == 0
    take_out = capsys.readouterr().out
    assert (tmp_path / "building" / f"{item_id}.md").is_file()
    # The ready-to-paste PR stamp: local's is the bare slug, matching its own grammar entry.
    assert f"Backlog: {item_id}" in take_out
    assert "PR's title or body" in take_out
    assert backlog.backlog_command(_namespace(tmp_path, "done", item_id)) == 0
    assert (tmp_path / "done" / f"{item_id}.md").is_file()
    capsys.readouterr()
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 0
    assert "(the queue is empty)" in capsys.readouterr().out


def test_the_command_points_at_init_when_there_is_no_config(tmp_path, capsys):
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    assert "tautline init" in out and "tautline slim" in out


def test_add_without_a_title_says_how_to_give_one(tmp_path, capsys):
    _write_config(tmp_path, provider="local")
    assert backlog.backlog_command(_namespace(tmp_path, "add")) == 1
    assert "tautline backlog add" in capsys.readouterr().out


def test_done_without_an_id_says_how_to_find_one(tmp_path, capsys):
    _write_config(tmp_path, provider="local")
    assert backlog.backlog_command(_namespace(tmp_path, "done")) == 1
    assert "tautline backlog list" in capsys.readouterr().out


def test_an_empty_queue_says_so_rather_than_printing_nothing(tmp_path, capsys):
    _write_config(tmp_path, provider="local")
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 0
    assert "(the queue is empty)" in capsys.readouterr().out


def test_add_and_take_print_the_id_and_url(tmp_path, capsys, github_env, http):
    _write_config(tmp_path, provider="github", repo="acme/demo")
    http.route("POST /repos/acme/demo/issues", _issue(31, "Filed"))
    assert backlog.backlog_command(_namespace(tmp_path, "add", "Filed")) == 0
    out = capsys.readouterr().out
    assert "31 (https://github.com/acme/demo/issues/31)" in out and "Filed" in out


def test_a_skipped_best_effort_step_is_printed_not_swallowed(tmp_path, capsys, github_env, http):
    _write_config(tmp_path, provider="github", repo="acme/demo")
    taken = _issue(4, "Taken", labels=("backlog", "in-progress"))
    http.fail("GET /user", 403, {"message": "Resource not accessible by integration"})
    http.route("POST /repos/acme/demo/issues/4/labels", [])
    http.route("GET /repos/acme/demo/issues/4", taken)
    assert backlog.backlog_command(_namespace(tmp_path, "take", "4")) == 0
    out = capsys.readouterr().out
    assert "backlog_note: assignee not resolved" in out
    assert "take: 4 (" in out
    # GitHub's stamp form carries the leading `#`, matching its own closing-keyword grammar.
    assert "Backlog: #4" in out
    assert "PR's title or body" in out


def test_jira_command_take_prints_the_ready_to_paste_stamp(tmp_path, capsys, jira_env, http):
    _write_config(tmp_path, provider="jira", site=SITE, project="PROJ")
    http.route(
        "GET /rest/api/3/issue/PROJ-3/transitions",
        {"transitions": [{"id": "31", "name": "In Progress", "isGlobal": False}]},
    )
    http.route("POST /rest/api/3/issue/PROJ-3/transitions", None)
    http.route("GET /rest/api/3/issue/PROJ-3", _jira_issue("PROJ-3", "Moving", "indeterminate"))
    assert backlog.backlog_command(_namespace(tmp_path, "take", "PROJ-3")) == 0
    out = capsys.readouterr().out
    assert "take: PROJ-3" in out
    # Jira's stamp form is the bare key -- no `#` prefix, matching its own bare-key grammar.
    assert "Backlog: PROJ-3" in out
    assert "PR's title or body" in out


def test_add_and_done_do_not_print_the_take_only_stamp(tmp_path, capsys):
    """The stamp line is `take`'s alone -- `add` files an item nobody has started yet, and `done`
    is printed after the PR that should have carried the stamp has already merged. Printing it on
    either would suggest re-stamping a PR that is finished or does not exist."""
    _write_config(tmp_path, provider="local")
    assert backlog.backlog_command(_namespace(tmp_path, "add", "Some item")) == 0
    add_out = capsys.readouterr().out
    item_id = add_out.split(":", 1)[1].split()[0]
    assert "Backlog:" not in add_out

    assert backlog.backlog_command(_namespace(tmp_path, "done", item_id)) == 0
    assert "Backlog:" not in capsys.readouterr().out


def test_the_command_reports_a_provider_failure_and_exits_nonzero(tmp_path, capsys, monkeypatch):
    _write_config(tmp_path, provider="jira", site=SITE, project="PROJ")
    monkeypatch.delenv(jira_client.EMAIL_ENV, raising=False)
    monkeypatch.delenv(jira_client.API_TOKEN_ENV, raising=False)
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    assert out.startswith("backlog_error: ") and jira_client.EMAIL_ENV in out


def test_an_unexpected_failure_is_a_message_not_a_traceback(tmp_path, capsys, monkeypatch):
    """A CLI never answers with a stack trace. An AttributeError from an unexpected response shape
    is still a bug, but the user gets a sentence and an exit code, not 40 lines of frames."""
    _write_config(tmp_path, provider="local")

    def _explode(*_args, **_kwargs):
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(backlog.LocalBacklog, "list", _explode)
    assert backlog.backlog_command(_namespace(tmp_path, "list")) == 1
    out = capsys.readouterr().out
    assert "backlog_error: the list command hit an unexpected AttributeError" in out
    assert "please report it" in out
    assert "Traceback" not in out


def test_the_verb_is_registered_and_reachable():
    """The two new-verb guards read `tautline --help`; this pins the registration they read."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "bin" / "tautline"), "backlog", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "{list,add,take,done}" in result.stdout
