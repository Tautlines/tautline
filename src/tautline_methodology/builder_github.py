"""The builder lane's ENTIRE GitHub surface: read the board, read issues, write two things.

A builder lane gets these verbs and NOTHING else against GitHub. That is the point of the module,
not an accident of what has been implemented so far:

* every coordinate comes from `builder.board_config()` -- the lean adapter's `builderGithub` block
  plus `project.repo` -- so a lane cannot be pointed at a board by a flag, an environment variable,
  or a copy-pasted URL. A project that has not opted in gets a refusal naming the block to add;
* the BOARD IS READ-ONLY. There is no `board move`, no `board set-status`, no `item-add`. A lane
  that could move a card could quietly reorganise a human's board, and the board's ordering is the
  product director's statement of what matters -- it is an input to the lane, never an output;
* the only writes that exist are ONE issue comment (`issue comment`) and ONE debt
  issue (`debt file`). Both are read back before they are reported as done, because in this codebase
  a 2xx is not evidence: GitHub silently drops `labels` when a token cannot write issues, and a
  comment that 201s but cannot be fetched is a comment nobody can act on.

THE VERBS DO NOT CHECK THE BUILDER ROLE. They read a board and post a comment; a human running one
by hand harms nothing, and a role check here would be a second, weaker copy of the guard that
belongs at the gate. `builder.builder_role_active()` exists for the guard, not for these.

TRANSPORT. Plain `urllib`, api.github.com only, redirects refused, credentials from the environment,
then the builder GitHub App, then `gh auth token` -- and never from the project's config. That posture is `backlog.GitHubBacklog`'s,
and this module is the FOURTH place in this codebase that needs it (after the backlog seam, the Jira
client, and `stakeholder_question`). The shared primitives that carry no caller-specific wording --
`_gh_auth_token`, `_redact`, `_seg`, `url_path`, the `Link`-header regex, the page bound -- are
imported from `backlog` rather than copied. The four methods that DO carry caller-specific wording
(the origin pin, the redirect refusal, the request, the typed error) are local, because each has to
raise THIS module's error type and name THIS module's config keys in its remedy; a shared version
would have to be handed a message template per call site, which is not a mechanical extraction and
would have made `backlog`'s own tests move. `_token()` is the ONE credential seam, which is where the
sibling lane's GitHub App minting hop was fitted at integration.

GRAPHQL, and why the board read is the exception to `backlog.py`'s REST-only rule. A ProjectV2's
columns, its item ordering and its field options are NOT in the REST API at all -- there is no
readable board position on an item, and `orderBy:{field:POSITION}` on the items connection is the
only way to see the order a human dragged the cards into. So the board read is GraphQL, and it is
CACHED for five minutes precisely because GraphQL is the expensive surface: an agent reading the
board several times in one session must cost one query, not one per read. Writes are never cached.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from tautline_methodology import backlog, builder, lean
from tautline_methodology.backlog import (
    GITHUB_API,
    GITHUB_HOST,
    GITHUB_TOKEN_ENVS,
    MAX_PAGES,
    _LINK_NEXT,
    _redact,
    _seg,
    url_path,
)
from tautline_methodology.builder import BoardConfig, BuilderConfigError
from tautline_methodology.jira_client import Secret
from tautline_methodology.util import flatten_printable, resolve_env

REQUEST_TIMEOUT_SECONDS = 30
GRAPHQL_URL = f"{GITHUB_API}/graphql"

#: Pinned EXPLICITLY, same reasoning as `backlog.GITHUB_PAGE_SIZE`: GitHub's REST default is 30, so
#: an omitted `per_page` silently reads the first 30 of a longer list and every count is wrong.
REST_PAGE_SIZE = 100
#: GitHub's connection maximum. Asking for fewer costs more round trips for the same board.
BOARD_PAGE_SIZE = 100

#: Where the raw board payload is parked between reads. Under `.ai-work/` because that is the
#: target's scratch space -- never committed, and safe to delete at any moment.
CACHE_PATH = Path(".ai-work") / "builder-board-cache.json"
CACHE_TTL_SECONDS = 300

#: A title or a status sets a column width in a table and is written by somebody else. Bounded
#: before it is rendered, never after somebody notices a 4KB "status".
MAX_TITLE_CHARS = 110
MAX_FIELD_CHARS = 60
MAX_URL_CHARS = 300
#: An issue body is deliberately allowed to be long -- reading it is the whole point of `board show`
#: -- but not unbounded, and control characters still come out.
MAX_BODY_CHARS = 20000

#: Two debt titles are "the same item" when their normalised forms are equal, and "probably the same
#: item" when their token sets overlap this much. 0.6 is a warning threshold, not a refusal one: the
#: refusal is exact-match only, because a near-match refusal would block a legitimately similar
#: second finding and there is no way for the caller to override it.
NEAR_MATCH_THRESHOLD = 0.6

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_ISSUE_STATES = ("open", "closed", "all")


class BuilderGitHubError(Exception):
    """Every failure these verbs report. Always actionable: it names the next thing to do."""


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses a redirect rather than replaying the `Authorization` header at a new host.

    Its own class, raising THIS module's error type, for the reason `backlog._RefuseRedirect`'s
    docstring gives: a caller catching one module's error would not catch another's. The suite's
    transport walk finds this one through `_Client._build_opener`.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib contract
        raise BuilderGitHubError(
            f"GitHub returned a {code} redirect; refusing to follow it because the Authorization "
            "header would be replayed at the new location. If api.github.com genuinely moved, this "
            "is a bug worth reporting."
        )


def _safe(text: object, limit: int = MAX_TITLE_CHARS) -> str:
    """Remote-sourced text, made safe to PRINT and bounded. Everything from GitHub goes through."""
    return flatten_printable(text, limit)


def _safe_body(text: object) -> str:
    """An issue body, made safe to PRINT and bounded -- but WITH its own line breaks intact.

    Remote text otherwise goes through `_safe`, which flattens newlines too, because a response
    that can add lines can paint a convincing fake status line beside the real ones. A body is the
    one remote string that is not rendered beside anything: it is printed in a block of its own,
    after a blank line, and `_quoted` prefixes EVERY line of it with `> ` -- so no line of a body
    can pass for a line this code wrote. Flattening it, meanwhile, destroys the one thing a reader
    came for: an issue body is a spec, with headings, bullets and code, and read as a single
    2000-character paragraph it is unusable. Control characters still come out, and the bound is
    unchanged.
    """
    return flatten_printable(text, MAX_BODY_CHARS, keep_newlines=True)


def _quoted(body: str) -> list[str]:
    """A body as block-quote lines: one output line per body line, blank lines kept as `>`."""
    if not body.strip():
        return ["(no body)"]
    return [f"> {line}" if line else ">" for line in body.splitlines()]


def _safe_message(text: object) -> str:
    """A whole error message on its way to a terminal: control characters out, OUR newlines kept."""
    return flatten_printable(text, 4000, keep_newlines=True)


def _token(cfg: dict | None = None) -> Secret:
    """THE credential seam, in three steps: environment, then the App, then whatever `gh` holds.

    One function, named once, and the App hop the sibling lane built now lives in the middle of it.

    THE ORDER IS THE POLICY. An operator who exported GH_TOKEN answered this question deliberately
    and no App should second-guess them, so the environment stays first. The App comes next, which
    is what lets a builder lane act as the bot WITHOUT exporting a token into a process that also
    runs a test suite and a shell. `gh auth token` stays last so a human running the same verb by
    hand -- who has no App configured -- keeps working exactly as before: this layer adds an
    identity for builders, it takes nothing away from humans.

    `cfg` is the raw lean config, not a `BoardConfig`: the App needs `project.repo` to discover its
    installation id, and threading the parsed board config would give it the wrong half.

    The import is LAZY and goes through `builder`, which re-exports it for exactly this reason --
    `builder_token` imports `builder`, so a module-scope import here would tie this module's import
    graph to a credential path most of its callers never take.

    `backlog._gh_auth_token` is reached as a module ATTRIBUTE rather than imported by name so the
    suite's autouse `_no_real_gh_token` fixture -- which patches it on `backlog` -- actually covers
    this transport too.
    """
    for env in GITHUB_TOKEN_ENVS:
        value = resolve_env(env).strip()
        if value:
            _note_personal_token()
            return Secret(value)
    minted = _app_token(cfg)
    if minted:
        return Secret(minted)
    fallback = backlog._gh_auth_token()
    if fallback:
        _note_personal_token()
    return Secret(fallback)


#: What a builder lane is told when it is NOT the bot. The security argument these verbs rest on
#: is "a board write is refused by GitHub, not by a hook" -- and that holds only when the lane is
#: authenticated as the App installation. With an exported GH_TOKEN, or `gh auth token`, the lane
#: is authenticated as a PERSON, and every claim about Projects-read becomes a claim about however
#: that person's token happens to be scoped. Silence there is the failure: the lane looks
#: identical, and so does the output.
PERSONAL_TOKEN_NOTE = (
    "builder_note: acting with a personal token, not the builder App; board writes are refused "
    "only if this token cannot make them"
)

#: Once per process. `_token` is called on EVERY request, and a note repeated per request is noise
#: a reader learns to skip -- which is the same as not printing it.
_personal_token_noted = False


def _note_personal_token() -> None:
    """One stderr line, once, and only for a BUILDER lane.

    stderr rather than stdout because `--json` promises a machine-readable envelope there. Nothing
    at all for a human: this says a BUILDER is not acting as the bot, which is not a fact about a
    human's own session -- they were never supposed to be.

    The role is read against the CWD rather than `--target`, because the credential seam is three
    call frames below the one that knows the target. TAUTLINE_ROLE answers first and is how a lane
    is marked in practice; a role FILE under a `--target` elsewhere would be missed, and the cost
    of that miss is one absent note, not a decision.
    """
    global _personal_token_noted
    if _personal_token_noted or not builder.builder_role_active():
        return
    _personal_token_noted = True
    print(PERSONAL_TOKEN_NOTE, file=sys.stderr)


def _app_token(cfg: dict | None) -> str:
    """The App hop, or "" when no App is configured. Never falls through on a REAL failure.

    A configured App that cannot mint is an error the operator has to see -- a bad key path, a
    revoked installation, an App removed from the repository. Swallowing it and falling through to
    `gh auth token` would make the lane quietly act as the HUMAN whose credentials happen to be on
    the machine, writing to the board under their name, which is the one outcome the App exists to
    prevent. So the refusal is re-raised as this module's error type (the CLI's error contract only
    knows about `BuilderGitHubError`) rather than dropped.
    """
    from tautline_methodology.builder_token import BuilderTokenError

    try:
        return builder.github_token(cfg)
    except BuilderTokenError as exc:
        raise BuilderGitHubError(
            f"The builder GitHub App is configured but could not mint a token, and falling back "
            f"to your own `gh` credentials would write to the board under YOUR name. "
            f"{_safe_message(exc)}"
        ) from None


# --------------------------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------------------------


class _Client:
    """REST and GraphQL against api.github.com, with `GitHubBacklog`'s posture."""

    def __init__(
        self,
        *,
        repo: str,
        lean_cfg: dict | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.repo = repo
        #: The RAW lean config, carried only so `_token` can hand it to the App for installation
        #: discovery. Nothing else here reads it; `BoardConfig` remains the parsed view.
        self.lean_cfg = lean_cfg
        self.timeout = timeout

    @staticmethod
    def _assert_github_origin(url: str) -> None:
        """Refuse to attach a bearer token to anything but api.github.com.

        Applied to every request INCLUDING a `Link` header's next page and a comment `url` read out
        of a response body -- both URLs chosen by the response rather than by this code.
        """
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != GITHUB_HOST:
            raise BuilderGitHubError(
                f"Refusing to send a GitHub token to {_safe(url, 120)!r}: this client talks only "
                f"to https://{GITHUB_HOST}."
            )

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        """The opener actually used, exposed so a test can prove the refusal is INSTALLED."""
        return urllib.request.build_opener(_RefuseRedirect())

    def _request(
        self, method: str, url_or_path: str, payload: object | None = None
    ) -> tuple[object, dict]:
        """One request. Returns `(parsed body, lower-cased response headers)`.

        Headers come back because GitHub signals REST pagination only in the `Link` header.
        """
        token = _token(self.lean_cfg)
        if not token:
            raise BuilderGitHubError(
                "GitHub credentials: no token available. Export "
                f"{' or '.join(GITHUB_TOKEN_ENVS)} with a token that can read "
                f"{self.repo} and its project board, or run `gh auth login` so the CLI can supply "
                "one. A builder lane can instead configure the GitHub App and write as the bot -- "
                "`tautline builder-token --status` says which of the three this lane would use. "
                "The token is read from the environment and never from the project's config, "
                "which is committed to a repository."
            )
        url = url_or_path if url_or_path.startswith("http") else f"{GITHUB_API}{url_or_path}"
        self._assert_github_origin(url)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token.reveal()}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        opener = self._build_opener()
        try:
            with opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                headers = {
                    str(key).lower(): str(value) for key, value in dict(response.headers).items()
                }
        except BuilderGitHubError:
            raise
        except urllib.error.HTTPError as exc:
            raise self._typed_error(exc, url_path(url), token) from None
        except (urllib.error.URLError, OSError) as exc:
            raise BuilderGitHubError(
                _redact(f"GitHub request to {url_path(url)} did not complete: {exc}", token)
            ) from None
        if not body.strip():
            return None, headers
        try:
            return json.loads(body), headers
        except ValueError:
            raise BuilderGitHubError(
                f"GitHub returned a non-JSON body for {url_path(url)}."
            ) from None

    def _http(self, method: str, url_or_path: str, payload: object | None = None) -> object:
        return self._request(method, url_or_path, payload)[0]

    @staticmethod
    def _error_detail(exc: urllib.error.HTTPError) -> str:
        """GitHub's own description of the fault. Discarding it makes the caller guess."""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        parts = [str(payload.get("message") or "").strip()]
        for entry in payload.get("errors") or []:
            if isinstance(entry, dict):
                field_name = str(entry.get("field") or entry.get("resource") or "").strip()
                code = str(entry.get("code") or entry.get("message") or "").strip()
                parts.append(f"{field_name}: {code}".strip(": "))
            else:
                parts.append(str(entry))
        return " ".join(part for part in parts if part)[:400]

    def _typed_error(
        self, exc: urllib.error.HTTPError, path: str, token: Secret
    ) -> BuilderGitHubError:
        detail = self._error_detail(exc)
        suffix = f" GitHub said: {_safe(detail, 400)}" if detail else ""
        if exc.code in (401, 403):
            return BuilderGitHubError(
                _redact(
                    f"GitHub rejected the credentials for {path} (HTTP {exc.code}). Check "
                    f"{' / '.join(GITHUB_TOKEN_ENVS)} (or `gh auth login`) and that the token can "
                    f"read {self.repo} and the project the `builderGithub` block names.{suffix}",
                    token,
                )
            )
        if exc.code == 404:
            return BuilderGitHubError(
                _redact(
                    f"GitHub has nothing at {path} (HTTP 404). Check `project.repo` -- it is "
                    f"{self.repo!r} -- and that the token can see a private repository.{suffix}",
                    token,
                )
            )
        return BuilderGitHubError(
            _redact(f"GitHub returned HTTP {exc.code} for {path}.{suffix}", token)
        )

    def paged(self, path: str) -> list:
        """Every page of a REST list endpoint, following `Link` to the end. Bounded."""
        items: list = []
        url: str | None = path
        for _ in range(MAX_PAGES):
            if url is None:
                return items
            payload, headers = self._request("GET", url)
            if not isinstance(payload, list):
                raise BuilderGitHubError(
                    f"GitHub {url_path(url or path)} returned unexpected JSON; expected a list."
                )
            items.extend(payload)
            match = _LINK_NEXT.search(headers.get("link", ""))
            url = match.group(1) if match else None
        raise BuilderGitHubError(
            f"GitHub kept offering another page of {url_path(path)} after {MAX_PAGES} requests. "
            "Refusing to keep paging; narrow the filter or report this."
        )

    def graphql(self, query: str, variables: dict) -> dict:
        """One GraphQL POST. Returns the WHOLE envelope -- `data` and `errors` both.

        Errors are handed back rather than raised here because one caller legitimately expects them:
        `organization(login:)` answers NOT_FOUND for a user-owned project, which is the signal to
        retry as a user, not a failure. Every other caller goes through `graphql_data`, which
        refuses an errored response instead of reading an empty `data` as an empty result.
        """
        payload = self._http("POST", GRAPHQL_URL, {"query": query, "variables": variables})
        if not isinstance(payload, dict):
            raise BuilderGitHubError(
                "GitHub's GraphQL endpoint returned unexpected JSON; expected an object."
            )
        return payload

    def graphql_data(self, query: str, variables: dict, *, what: str) -> dict:
        payload = self.graphql(query, variables)
        errors = payload.get("errors")
        if errors:
            raise BuilderGitHubError(
                f"GitHub's GraphQL API refused {what}: {graphql_error_text(errors)}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BuilderGitHubError(f"GitHub returned no data for {what}.")
        return data


def graphql_error_text(errors: object) -> str:
    """A GraphQL `errors` array as one bounded line. A 200 with errors is a FAILED query."""
    if not isinstance(errors, list):
        return _safe(errors, 400)
    messages = []
    for entry in errors:
        if isinstance(entry, dict):
            messages.append(str(entry.get("message") or entry.get("type") or entry))
        else:
            messages.append(str(entry))
    return _safe("; ".join(messages) or "no message", 400)


# --------------------------------------------------------------------------------------------
# the board: one GraphQL query, position-ordered, cached
# --------------------------------------------------------------------------------------------

#: `%s` is the owner root -- `organization` or `user`. GitHub has no "owner(login:)" that resolves
#: both, so the fallback is a second query rather than a cleverer first one.
#:
#: `orderBy:{field:POSITION,direction:ASC}` is the WHOLE reason this is GraphQL: the manual board
#: order a human dragged the cards into is not a readable field on an item and is not in REST at
#: all. Reading the board in any other order would answer "what is next?" with something the
#: director did not say.
_BOARD_QUERY = """query($login:String!,$number:Int!,$cursor:String){
  %s(login:$login){
    projectV2(number:$number){
      number
      title
      url
      fields(first:50){nodes{
        __typename
        ... on ProjectV2SingleSelectField{name options{name}}
        ... on ProjectV2FieldCommon{name}
      }}
      items(first:%d,after:$cursor,orderBy:{field:POSITION,direction:ASC}){
        pageInfo{hasNextPage endCursor}
        nodes{
          type
          fieldValues(first:20){nodes{
            __typename
            ... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2FieldCommon{name}}}
            ... on ProjectV2ItemFieldTextValue{text field{... on ProjectV2FieldCommon{name}}}
            ... on ProjectV2ItemFieldNumberValue{number field{... on ProjectV2FieldCommon{name}}}
          }}
          content{
            __typename
            ... on Issue{
              number title url state
              labels(first:20){nodes{name}}
              comments{totalCount}
              subIssuesSummary{total completed}
              closedByPullRequestsReferences(first:20){totalCount nodes{number url state}}
            }
            ... on PullRequest{number title url state}
            ... on DraftIssue{title}
          }
        }
      }
    }
  }
}"""

#: The placement check `debt file` runs after creating an issue. Separate and tiny on purpose: it
#: asks one question -- did anything put this issue on a project? -- and an org auto-add workflow is
#: the thing it exists to catch.
_PROJECT_ITEMS_QUERY = """query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    issue(number:$number){
      projectItems(first:10){nodes{project{number owner{... on Organization{login} ... on User{login}}}}}
    }
  }
}"""

_OWNER_ROOTS = ("organization", "user")


def board_query(root: str) -> str:
    return _BOARD_QUERY % (root, BOARD_PAGE_SIZE)


def fetch_board(client: _Client, cfg: BoardConfig) -> dict:
    """The whole project, every page, in board position order.

    `organization` first, `user` second: GitHub answers a user-owned project's org query with a null
    and a NOT_FOUND error, which is not a failure -- it is the answer "try the other root". Only
    when BOTH roots come back without a project is the query reported as failed, and then the
    errors GitHub gave are printed rather than swallowed into an empty board.
    """
    failures: list[str] = []
    for root in _OWNER_ROOTS:
        query = board_query(root)
        pages: list[dict] = []
        cursor = None
        project: dict | None = None
        for _ in range(MAX_PAGES):
            payload = client.graphql(
                query, {"login": cfg.owner, "number": cfg.project_number, "cursor": cursor}
            )
            data = payload.get("data")
            holder = (data or {}).get(root) if isinstance(data, dict) else None
            candidate = holder.get("projectV2") if isinstance(holder, dict) else None
            if not isinstance(candidate, dict):
                if payload.get("errors"):
                    failures.append(f"{root}: {graphql_error_text(payload['errors'])}")
                else:
                    failures.append(f"{root}: no project {cfg.project_number} for {cfg.owner!r}")
                break
            project = candidate
            items = candidate.get("items") if isinstance(candidate.get("items"), dict) else {}
            pages.extend(node for node in (items.get("nodes") or []) if isinstance(node, dict))
            info = items.get("pageInfo") if isinstance(items.get("pageInfo"), dict) else {}
            if not info.get("hasNextPage"):
                merged = dict(project)
                merged["items"] = {"nodes": pages}
                return merged
            cursor = info.get("endCursor")
        else:
            raise BuilderGitHubError(
                f"The board kept offering another page after {MAX_PAGES} GraphQL requests. "
                "Refusing to keep paging; report this if the project is legitimately that large."
            )
        if project is not None:
            # The first page resolved but a later one did not: that is a real failure, not a
            # wrong-root signal, so it is not worth retrying as a user.
            break
    raise BuilderGitHubError(
        "Could not read project "
        f"{cfg.project_number} owned by {cfg.owner!r}. Tried both an organization and a user "
        "owner:\n  " + "\n  ".join(_safe(line, 400) for line in failures) + "\nCheck "
        "`builderGithub.owner` and `builderGithub.projectNumber`, and that the token has the "
        "`read:project` scope."
    )


def _cache_file(root: Path) -> Path:
    return root / CACHE_PATH


def read_cached_board(root: Path, cfg: BoardConfig, *, now: float | None = None) -> dict | None:
    """The cached board, or None. A corrupt or foreign cache is IGNORED, never fatal.

    The cache is an optimisation over an expensive GraphQL read, so every way it can be wrong --
    truncated JSON, a payload for a different board, a clock that moved in either direction -- has
    exactly one correct answer: read the board again. Raising here would let a stray file in
    `.ai-work/` break a verb.
    """
    path = _cache_file(root)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    if stored.get("owner") != cfg.owner or stored.get("number") != cfg.project_number:
        return None
    fetched_at = stored.get("fetched_at")
    if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
        return None
    # A WINDOW, not a half-line. `now - fetched_at > TTL` expires nothing when `fetched_at` is
    # ahead of the clock -- the difference is negative -- so one file written by a machine whose
    # clock is a day fast gives a lane a board that never refreshes. That is the worst failure
    # this cache has, because the output looks entirely correct and is simply old.
    age = (now if now is not None else time.time()) - float(fetched_at)
    if not 0 <= age <= CACHE_TTL_SECONDS:
        return None
    project = stored.get("project")
    return project if isinstance(project, dict) else None


def write_cached_board(root: Path, cfg: BoardConfig, project: dict) -> None:
    """Best effort. A cache that cannot be written is a slower next read, not a failed command."""
    path = _cache_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "owner": cfg.owner,
                    "number": cfg.project_number,
                    "fetched_at": time.time(),
                    "project": project,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def load_board(client: _Client, cfg: BoardConfig, root: Path, *, fresh: bool = False) -> dict:
    if not fresh:
        cached = read_cached_board(root, cfg)
        if cached is not None:
            return cached
    project = fetch_board(client, cfg)
    write_cached_board(root, cfg, project)
    return project


# --------------------------------------------------------------------------------------------
# the board's shape, in this module's vocabulary
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardItem:
    """One card. `number` is None for a draft item, which has no issue behind it."""

    number: int | None
    title: str
    url: str
    state: str
    kind: str
    status: str
    item_type: str
    size: str
    labels: tuple[str, ...] = ()
    prs: tuple[str, ...] = ()
    comments: int = 0
    sub_total: int = 0
    sub_done: int = 0
    fields: dict = field(default_factory=dict)

    @property
    def pr_count(self) -> int:
        return len(self.prs)

    def as_json(self) -> dict:
        return {
            "number": self.number,
            "title": _safe(self.title, MAX_TITLE_CHARS),
            "url": _safe(self.url, MAX_URL_CHARS),
            "state": _safe(self.state, MAX_FIELD_CHARS),
            "kind": _safe(self.kind, MAX_FIELD_CHARS),
            "status": _safe(self.status, MAX_FIELD_CHARS),
            "type": _safe(self.item_type, MAX_FIELD_CHARS),
            "size": _safe(self.size, MAX_FIELD_CHARS),
            "labels": [_safe(name, MAX_FIELD_CHARS) for name in self.labels],
            "prs": [_safe(url, MAX_URL_CHARS) for url in self.prs],
            "prCount": self.pr_count,
            "comments": self.comments,
            "subIssues": {"total": self.sub_total, "completed": self.sub_done},
        }


def _field_values(node: dict) -> dict:
    """`{field name: value as text}` for every single-select, text and number value on a card."""
    values: dict = {}
    holder = node.get("fieldValues")
    for entry in (holder.get("nodes") or []) if isinstance(holder, dict) else []:
        if not isinstance(entry, dict):
            continue
        field_def = entry.get("field")
        name = str(field_def.get("name") or "") if isinstance(field_def, dict) else ""
        if not name:
            continue
        if entry.get("name") is not None:
            values[name] = str(entry["name"])
        elif entry.get("text") is not None:
            values[name] = str(entry["text"])
        elif entry.get("number") is not None:
            values[name] = str(entry["number"])
    return values


def _int_or_none(value: object) -> int | None:
    """An integer from a remote field, or None. Never a crash: the API's shape is not ours."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def board_items(project: dict, cfg: BoardConfig) -> list[BoardItem]:
    """The cards, in the order GitHub returned them -- which is the board's own order."""
    items = project.get("items") if isinstance(project.get("items"), dict) else {}
    out: list[BoardItem] = []
    for node in (items.get("nodes") or []) if isinstance(items, dict) else []:
        if not isinstance(node, dict):
            continue
        content = node.get("content") if isinstance(node.get("content"), dict) else {}
        values = _field_values(node)
        labels_holder = content.get("labels") if isinstance(content.get("labels"), dict) else {}
        prs_holder = content.get("closedByPullRequestsReferences")
        prs_holder = prs_holder if isinstance(prs_holder, dict) else {}
        summary = content.get("subIssuesSummary")
        summary = summary if isinstance(summary, dict) else {}
        comments = content.get("comments") if isinstance(content.get("comments"), dict) else {}
        out.append(
            BoardItem(
                number=_int_or_none(content.get("number")),
                title=str(content.get("title") or ""),
                url=str(content.get("url") or ""),
                state=str(content.get("state") or ""),
                kind=str(content.get("__typename") or node.get("type") or ""),
                status=values.get(cfg.status_field, ""),
                item_type=values.get(cfg.type_field, ""),
                size=values.get("Size", ""),
                labels=tuple(
                    str(entry.get("name") or "")
                    for entry in (labels_holder.get("nodes") or [])
                    if isinstance(entry, dict)
                ),
                prs=tuple(
                    str(entry.get("url") or "")
                    for entry in (prs_holder.get("nodes") or [])
                    if isinstance(entry, dict)
                ),
                comments=_int_or_none(comments.get("totalCount")) or 0,
                sub_total=_int_or_none(summary.get("total")) or 0,
                sub_done=_int_or_none(summary.get("completed")) or 0,
                fields=values,
            )
        )
    return out


def board_fields(project: dict) -> list[dict]:
    """Every single-select field and its LIVE option names, so nobody guesses a column name."""
    holder = project.get("fields") if isinstance(project.get("fields"), dict) else {}
    out: list[dict] = []
    for entry in (holder.get("nodes") or []) if isinstance(holder, dict) else []:
        if not isinstance(entry, dict):
            continue
        options = entry.get("options")
        if not isinstance(options, list):
            continue
        out.append(
            {
                "name": _safe(entry.get("name") or "", MAX_FIELD_CHARS),
                "options": [
                    _safe(option.get("name") or "", MAX_FIELD_CHARS)
                    for option in options
                    if isinstance(option, dict)
                ],
            }
        )
    return out


def _matches(value: str, wanted: str) -> bool:
    return value.strip().lower() == wanted.strip().lower()


def filter_items(
    items: list[BoardItem],
    cfg: BoardConfig,
    *,
    statuses: list[str] | None = None,
    item_type: str = "",
    label: str = "",
    text: str = "",
    show_all: bool = False,
) -> list[BoardItem]:
    """The visible cards. Order is never touched -- it is the board's statement, not a preference."""
    named = [s for s in (statuses or []) if s.strip()]
    hidden = {s.strip().lower() for s in cfg.hidden_statuses}
    if named:
        hidden -= {s.strip().lower() for s in named}
    needle = text.strip().lower()
    out = []
    for item in items:
        if named and not any(_matches(item.status, wanted) for wanted in named):
            continue
        if not show_all and item.status.strip().lower() in hidden:
            continue
        if item_type and not _matches(item.item_type, item_type):
            continue
        if label and not any(_matches(name, label) for name in item.labels):
            continue
        if needle and needle not in item.title.lower():
            continue
        out.append(item)
    return out


# --------------------------------------------------------------------------------------------
# rendering: deterministic tables, and nothing raw
# --------------------------------------------------------------------------------------------


def render_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """A left-aligned table. Deterministic: the same rows always render the same bytes."""
    widths = [len(head) for head in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(head.ljust(widths[i]) for i, head in enumerate(headers)).rstrip()]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return lines


def _joined(values, limit: int = MAX_FIELD_CHARS) -> str:
    return _safe(", ".join(str(value) for value in values), limit) if values else "-"


# --------------------------------------------------------------------------------------------
# REST reads
# --------------------------------------------------------------------------------------------


def issue_number(value: object, *, verb: str = "this verb") -> int:
    if value is None:
        raise BuilderGitHubError(
            f"`tautline {verb}` needs an issue number. Run `tautline board list` and use the "
            "number in the first column."
        )
    text = _safe(str(value), 40).strip().lstrip("#")
    if not text.isdigit():
        raise BuilderGitHubError(
            f"{_safe(value, 40)!r} is not an issue number. Run `tautline board list` and use the "
            "number in the first column."
        )
    return int(text)


def get_issue(client: _Client, repo: str, number: int) -> dict:
    payload = client._http("GET", f"/repos/{_seg(repo)}/issues/{number}")
    if not isinstance(payload, dict):
        raise BuilderGitHubError(f"GitHub did not return issue #{number} as an object.")
    return payload


def issue_json(payload: dict) -> dict:
    return {
        "number": _int_or_none(payload.get("number")),
        "title": _safe(payload.get("title") or "", MAX_TITLE_CHARS),
        "state": _safe(payload.get("state") or "", MAX_FIELD_CHARS),
        "url": _safe(payload.get("html_url") or "", MAX_URL_CHARS),
        "labels": [_safe(name, MAX_FIELD_CHARS) for name in issue_labels(payload)],
        "assignees": [
            _safe(entry.get("login") or "", MAX_FIELD_CHARS)
            for entry in (payload.get("assignees") or [])
            if isinstance(entry, dict)
        ],
        "comments": _int_or_none(payload.get("comments")) or 0,
        "body": _safe_body(payload.get("body") or ""),
    }


def issue_labels(payload: dict) -> list[str]:
    return [
        str(entry.get("name") or "") if isinstance(entry, dict) else str(entry)
        for entry in (payload.get("labels") or [])
    ]


def list_comments(client: _Client, repo: str, number: int) -> list[dict]:
    query = urllib.parse.urlencode({"per_page": str(REST_PAGE_SIZE)})
    payload = client.paged(f"/repos/{_seg(repo)}/issues/{number}/comments?{query}")
    return [entry for entry in payload if isinstance(entry, dict)]


def find_issues(
    client: _Client, repo: str, *, labels: list[str], state: str
) -> list[dict]:
    """Open (or closed, or all) issues in the repo, label-filtered SERVER-side. Never PRs.

    GitHub's issues endpoint returns pull requests too, and a PR is not an issue: including one
    would put something in a `find` result that `issue show` would then describe wrongly.
    """
    params = {
        "state": state,
        "sort": "created",
        "direction": "desc",
        "per_page": str(REST_PAGE_SIZE),
    }
    if labels:
        params["labels"] = ",".join(labels)
    query = urllib.parse.urlencode(params)
    payload = client.paged(f"/repos/{_seg(repo)}/issues?{query}")
    return [
        entry
        for entry in payload
        if isinstance(entry, dict) and "pull_request" not in entry
    ]


# --------------------------------------------------------------------------------------------
# the two writes
# --------------------------------------------------------------------------------------------


def stamped(body: str, root: Path) -> str:
    """The comment body a builder actually posts: the text, a blank line, then the lane stamp.

    Every lane on a machine shares one GitHub identity, so without the stamp a reader of the issue
    cannot tell which lane wrote this -- and the first thing anyone asks about a surprising comment
    is which lane wrote it.
    """
    text = body.strip()
    if not text:
        raise BuilderGitHubError(
            "The comment body is empty. Pass --body \"<text>\" or --body-file <path> with "
            "something in it; a comment carrying only the lane stamp says nothing."
        )
    return f"{text}\n\n{builder.lane_stamp(root)}"


def post_comment(client: _Client, repo: str, number: int, body: str) -> dict:
    """POST one comment and READ IT BACK before anybody is told it exists.

    A 201 is not evidence. The read-back is `GET` on the `url` the response itself returned, which
    is origin-checked like every other URL this client is handed by a response.
    """
    created = client._http(
        "POST", f"/repos/{_seg(repo)}/issues/{number}/comments", {"body": body}
    )
    if not isinstance(created, dict):
        raise BuilderGitHubError("GitHub did not return the created comment.")
    api_url = str(created.get("url") or "")
    if not api_url:
        raise BuilderGitHubError(
            "GitHub returned a comment with no `url`, so it cannot be read back. Refusing to "
            "report a write this command cannot confirm."
        )
    try:
        confirmed = client._http("GET", api_url)
    except BuilderGitHubError as exc:
        raise BuilderGitHubError(
            f"The comment on #{number} was accepted but could NOT be read back "
            f"({_safe(str(exc), 300)}). A write this command cannot confirm is not reported as "
            "done; check the issue before assuming the comment is there."
        ) from None
    if not isinstance(confirmed, dict) or str(confirmed.get("body") or "").strip() != body.strip():
        raise BuilderGitHubError(
            f"The comment on #{number} read back as something other than what was posted. The "
            "board did not end up where this command said it would; check the issue."
        )
    return confirmed


def normalized_title(title: str) -> str:
    """Lowercase, punctuation stripped, whitespace collapsed. The dedupe key for a debt title."""
    return " ".join(_NON_WORD.sub(" ", str(title or "").lower()).split())


def title_similarity(left: str, right: str) -> float:
    """Token Jaccard over the normalised titles. 1.0 is the same words in any order."""
    a = set(normalized_title(left).split())
    b = set(normalized_title(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def debt_body(body: str, root: Path, refs: list[int]) -> str:
    """The filed body: the finding, then an `Origin:` section carrying the stamp and the refs."""
    text = body.strip()
    if not text:
        raise BuilderGitHubError(
            "The debt body is empty. Pass --body \"<text>\" or --body-file <path>: a debt item "
            "with no description is a note nobody can act on."
        )
    lines = [text, "", "Origin:", builder.lane_stamp(root)]
    lines.extend(f"Refs #{number}" for number in refs)
    return "\n".join(lines) + "\n"


def issue_on_project(client: _Client, cfg: BoardConfig, number: int) -> bool:
    """Whether the newly created issue landed on the CONFIGURED project.

    Asked because an organisation auto-add workflow can put every new issue on the board, and a
    debt item silently appearing on the product board is a change to the director's board that the
    builder did not make and must not be silent about.
    """
    data = client.graphql_data(
        _PROJECT_ITEMS_QUERY,
        {"owner": cfg.repo_owner, "name": cfg.repo_name, "number": number},
        what=f"the project-placement check for issue #{number}",
    )
    repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    issue = repository.get("issue") if isinstance(repository.get("issue"), dict) else {}
    holder = issue.get("projectItems") if isinstance(issue.get("projectItems"), dict) else {}
    for node in (holder.get("nodes") or []) if isinstance(holder, dict) else []:
        if not isinstance(node, dict):
            continue
        project = node.get("project") if isinstance(node.get("project"), dict) else {}
        owner = project.get("owner") if isinstance(project.get("owner"), dict) else {}
        if _int_or_none(project.get("number")) != cfg.project_number:
            continue
        login = str(owner.get("login") or "")
        if not login or login.lower() == cfg.owner.lower():
            return True
    return False


# --------------------------------------------------------------------------------------------
# command plumbing
# --------------------------------------------------------------------------------------------


NO_CONFIG = (
    "No Tautline config here, so there is no board to read. Run `tautline init` to create one, or "
    "`tautline slim` to migrate a project that already has a 1.x adapter."
)


@dataclass
class _Context:
    root: Path
    cfg: BoardConfig
    client: _Client
    as_json: bool
    fresh: bool


def _context(args: argparse.Namespace) -> _Context:
    root = Path(getattr(args, "target", Path("."))).resolve()
    adapter = lean.find_lean_adapter(root)
    if adapter is None:
        raise BuilderGitHubError(NO_CONFIG)
    lean_cfg = lean.load_lean_config(adapter)
    cfg = builder.board_config(lean_cfg)
    return _Context(
        root=root,
        cfg=cfg,
        client=_Client(repo=cfg.repo, lean_cfg=lean_cfg),
        as_json=bool(getattr(args, "json", False)),
        fresh=bool(getattr(args, "fresh", False)),
    )


def _emit(payload: dict) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _fail(message: str, *, as_json: bool, code: int) -> int:
    """A refusal on the RIGHT channel.

    stdout is the data channel: a caller doing `tautline board list > board.txt` must get the
    refusal in their terminal, not in the file. Under `--json` the envelope promise is stronger
    still -- a line of prose there gives the consumer a `json.loads` error with nothing to do with
    the actual failure -- so `--json` gets a parseable `{"error": ...}` on stdout AND the prose on
    stderr, because the two readers are different people.
    """
    if as_json:
        print(json.dumps({"error": message}, indent=2, sort_keys=True))
    print(f"builder_error: {message}", file=sys.stderr)
    return code


def _run(action_name: str, handler, args: argparse.Namespace) -> int:
    """One error contract for all three verbs: a named refusal, exit 1, and never a traceback."""
    as_json = bool(getattr(args, "json", False))
    try:
        return handler(args)
    except (BuilderGitHubError, BuilderConfigError) as exc:
        return _fail(_safe_message(exc), as_json=as_json, code=1)
    except _BoardTouched as exc:
        return _fail(_safe_message(exc), as_json=as_json, code=2)
    except Exception as exc:  # a CLI never answers with a traceback
        return _fail(
            f"`{action_name}` hit an unexpected {type(exc).__name__}: {_safe(exc, 200)}. That is "
            "a bug in this command, not a problem with your board; please report it with the "
            "command you ran.",
            as_json=as_json,
            code=1,
        )


class _BoardTouched(Exception):
    """The debt issue landed on the product board. Exit 2, loudly: automation did that, not us."""


# --------------------------------------------------------------------------------------------
# board
# --------------------------------------------------------------------------------------------


def _board_list(ctx: _Context, args: argparse.Namespace) -> int:
    project = load_board(ctx.client, ctx.cfg, ctx.root, fresh=ctx.fresh)
    items = board_items(project, ctx.cfg)
    shown = filter_items(
        items,
        ctx.cfg,
        statuses=list(getattr(args, "status", None) or []),
        item_type=getattr(args, "type", "") or "",
        label=getattr(args, "label", "") or "",
        text=getattr(args, "text", "") or "",
        show_all=bool(getattr(args, "all", False)),
    )
    if ctx.as_json:
        return _emit(
            {
                "verb": "board list",
                "repo": ctx.cfg.repo,
                "owner": ctx.cfg.owner,
                "projectNumber": ctx.cfg.project_number,
                "boardTitle": _safe(project.get("title") or "", MAX_TITLE_CHARS),
                "total": len(items),
                "shown": len(shown),
                "items": [item.as_json() for item in shown],
            }
        )
    print(
        f"board list {ctx.cfg.repo} ({ctx.cfg.owner} project {ctx.cfg.project_number}: "
        f"{len(shown)} of {len(items)} items)"
    )
    rows = [
        [
            str(item.number if item.number is not None else "-"),
            _safe(item.status, MAX_FIELD_CHARS) or "-",
            _safe(item.item_type, MAX_FIELD_CHARS) or "-",
            _safe(item.title, MAX_TITLE_CHARS),
            _joined(item.labels),
            str(item.pr_count),
        ]
        for item in shown
    ]
    for line in render_table(["number", "status", "type", "title", "labels", "prs"], rows):
        print(line)
    return 0


def _card_lines(item: BoardItem) -> list[str]:
    lines = [
        f"status: {_safe(item.status, MAX_FIELD_CHARS) or '-'}",
        f"type: {_safe(item.item_type, MAX_FIELD_CHARS) or '-'}",
    ]
    if item.size:
        lines.append(f"size: {_safe(item.size, MAX_FIELD_CHARS)}")
    lines.append(f"labels: {_joined(item.labels)}")
    lines.append(
        f"linked prs: {item.pr_count}"
        + (f" ({_joined(item.prs, MAX_URL_CHARS * 4)})" if item.prs else "")
    )
    if item.sub_total:
        lines.append(f"sub-issues: {item.sub_done}/{item.sub_total} complete")
    return lines


def _board_show(ctx: _Context, args: argparse.Namespace) -> int:
    number = issue_number(getattr(args, "number", None), verb="board show")
    project = load_board(ctx.client, ctx.cfg, ctx.root, fresh=ctx.fresh)
    carded = next(
        (item for item in board_items(project, ctx.cfg) if item.number == number), None
    )
    payload = get_issue(ctx.client, ctx.cfg.repo, number)
    detail = issue_json(payload)
    if ctx.as_json:
        return _emit(
            {
                "verb": "board show",
                "number": number,
                "onBoard": carded is not None,
                "card": carded.as_json() if carded else None,
                "issue": detail,
            }
        )
    if carded is None:
        print(
            f"board show #{number}: NOT on the board ({ctx.cfg.owner} project "
            f"{ctx.cfg.project_number}). Showing the issue only."
        )
    else:
        print(f"board show #{number} -- {detail['title']}")
        for line in _card_lines(carded):
            print(line)
    print(f"state: {detail['state']}")
    print(f"labels: {_joined(detail['labels'])}")
    print(f"comments: {detail['comments']}")
    print(f"url: {detail['url']}")
    print("")
    for line in _quoted(detail["body"]):
        print(line)
    return 0


def _board_fields(ctx: _Context, args: argparse.Namespace) -> int:
    project = load_board(ctx.client, ctx.cfg, ctx.root, fresh=ctx.fresh)
    fields = board_fields(project)
    if ctx.as_json:
        return _emit(
            {
                "verb": "board fields",
                "owner": ctx.cfg.owner,
                "projectNumber": ctx.cfg.project_number,
                "fields": fields,
            }
        )
    print(f"board fields ({ctx.cfg.owner} project {ctx.cfg.project_number})")
    for entry in fields:
        print(f"{entry['name']}: {', '.join(entry['options']) or '(no options)'}")
    return 0


def board_command(args: argparse.Namespace) -> int:
    def handler(args: argparse.Namespace) -> int:
        ctx = _context(args)
        if args.action == "list":
            return _board_list(ctx, args)
        if args.action == "show":
            return _board_show(ctx, args)
        return _board_fields(ctx, args)

    return _run(f"board {getattr(args, 'action', '')}", handler, args)


# --------------------------------------------------------------------------------------------
# issue
# --------------------------------------------------------------------------------------------


def _board_status_for(ctx: _Context, number: int) -> BoardItem | None:
    """The card for this issue, from the CACHED board read where one is warm.

    A board that cannot be read must not stop `issue show` from showing the issue: the status is a
    useful extra, and the issue is the answer.
    """
    try:
        project = load_board(ctx.client, ctx.cfg, ctx.root, fresh=ctx.fresh)
    except BuilderGitHubError as exc:
        # SAID, not swallowed. The issue is the answer here and the card is the extra, so a board
        # that cannot be read must not fail the verb -- but a status line that silently goes
        # missing reads exactly like an item that is not on the board, which is a different fact.
        print(f"builder_note: board not read ({_safe(str(exc), 300)})", file=sys.stderr)
        return None
    return next((item for item in board_items(project, ctx.cfg) if item.number == number), None)


def _issue_show(ctx: _Context, args: argparse.Namespace) -> int:
    number = issue_number(getattr(args, "number", None), verb="issue show")
    detail = issue_json(get_issue(ctx.client, ctx.cfg.repo, number))
    carded = _board_status_for(ctx, number)
    if ctx.as_json:
        return _emit(
            {
                "verb": "issue show",
                "issue": detail,
                "onBoard": carded is not None,
                "boardStatus": carded.status if carded else "",
                "prs": list(carded.prs) if carded else [],
            }
        )
    print(f"issue #{number} -- {detail['title']}")
    print(f"state: {detail['state']}")
    print(f"labels: {_joined(detail['labels'])}")
    print(f"assignees: {_joined(detail['assignees'])}")
    if carded is None:
        print(f"board status: not on the board ({ctx.cfg.owner} project {ctx.cfg.project_number})")
    else:
        print(f"board status: {_safe(carded.status, MAX_FIELD_CHARS) or '-'}")
        print(
            f"linked prs: {carded.pr_count}"
            + (f" ({_joined(carded.prs, MAX_URL_CHARS * 4)})" if carded.prs else "")
        )
    print(f"comments: {detail['comments']}")
    print(f"url: {detail['url']}")
    print("")
    for line in _quoted(detail["body"]):
        print(line)
    return 0


def _issue_comments(ctx: _Context, args: argparse.Namespace) -> int:
    number = issue_number(getattr(args, "number", None), verb="issue comments")
    comments = list_comments(ctx.client, ctx.cfg.repo, number)
    last = getattr(args, "last", None)
    if last:
        comments = comments[-int(last) :]
    records = [
        {
            "author": _safe(
                (entry.get("user") or {}).get("login")
                if isinstance(entry.get("user"), dict)
                else "",
                MAX_FIELD_CHARS,
            ),
            "created": _safe(entry.get("created_at") or "", 40),
            "url": _safe(entry.get("html_url") or "", MAX_URL_CHARS),
            "body": _safe(entry.get("body") or "", MAX_BODY_CHARS),
        }
        for entry in comments
    ]
    if ctx.as_json:
        return _emit(
            {
                "verb": "issue comments",
                "number": number,
                "count": len(records),
                "comments": records,
            }
        )
    print(f"issue #{number} comments ({len(records)})")
    for record in records:
        print("")
        print(f"--- {record['author'] or '?'}  {record['created'] or '?'}")
        print(record["body"] or "(empty)")
    return 0


def _issue_find(ctx: _Context, args: argparse.Namespace) -> int:
    labels = [value for value in (getattr(args, "label", None) or []) if value.strip()]
    state = (getattr(args, "state", None) or "open").strip().lower()
    if state not in _ISSUE_STATES:
        raise BuilderGitHubError(f"--state must be one of {', '.join(_ISSUE_STATES)}.")
    found = find_issues(ctx.client, ctx.cfg.repo, labels=labels, state=state)
    needle = (getattr(args, "text", "") or "").strip().lower()
    if needle:
        # Client-side, and only after the LABEL filter has already narrowed the fetch: GitHub's
        # issue search has its own indexing lag and its own rate budget, and a substring over a
        # label-filtered page is both exact and free.
        found = [
            entry
            for entry in found
            if needle in str(entry.get("title") or "").lower()
            or needle in str(entry.get("body") or "").lower()
        ]
    records = [issue_json(entry) for entry in found]
    if ctx.as_json:
        return _emit(
            {
                "verb": "issue find",
                "repo": ctx.cfg.repo,
                "count": len(records),
                "issues": [
                    {key: record[key] for key in ("number", "title", "state", "labels", "url")}
                    for record in records
                ],
            }
        )
    print(f"issue find {ctx.cfg.repo} ({len(records)} issues)")
    rows = [
        [str(r["number"]), r["state"], r["title"], _joined(r["labels"]), r["url"]]
        for r in records
    ]
    for line in render_table(["number", "state", "title", "labels", "url"], rows):
        print(line)
    return 0


def _body_text(args: argparse.Namespace) -> str:
    body = getattr(args, "body", None)
    path = getattr(args, "body_file", None)
    if body is not None and path:
        raise BuilderGitHubError("Pass --body or --body-file, not both.")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise BuilderGitHubError(f"--body-file could not be read: {exc}") from None
    return body or ""


def _write_comment(ctx: _Context, number: int, text: str, verb: str) -> int:
    body = stamped(text, ctx.root)
    confirmed = post_comment(ctx.client, ctx.cfg.repo, number, body)
    url = _safe(confirmed.get("html_url") or "", MAX_URL_CHARS)
    if ctx.as_json:
        return _emit({"verb": verb, "number": number, "url": url, "verified": True})
    print(f"{verb.split(' ', 1)[1]}: #{number} {url}")
    return 0


def _issue_comment(ctx: _Context, args: argparse.Namespace) -> int:
    number = issue_number(getattr(args, "number", None), verb="issue comment")
    return _write_comment(ctx, number, _body_text(args), "issue comment")


def issue_command(args: argparse.Namespace) -> int:
    def handler(args: argparse.Namespace) -> int:
        ctx = _context(args)
        action = args.action
        if action == "show":
            return _issue_show(ctx, args)
        if action == "comments":
            return _issue_comments(ctx, args)
        if action == "find":
            return _issue_find(ctx, args)
        return _issue_comment(ctx, args)

    return _run(f"issue {getattr(args, 'action', '')}", handler, args)


# --------------------------------------------------------------------------------------------
# debt
# --------------------------------------------------------------------------------------------


def _debt_file(ctx: _Context, args: argparse.Namespace) -> int:
    title = " ".join((getattr(args, "title", "") or "").split())
    if not title:
        raise BuilderGitHubError('`tautline debt file` needs --title "<one line>".')
    refs = [int(value) for value in (getattr(args, "refs", None) or [])]
    body = debt_body(_body_text(args), ctx.root, refs)
    label = ctx.cfg.debt_label

    existing = find_issues(ctx.client, ctx.cfg.repo, labels=[label], state="open")
    key = normalized_title(title)
    duplicates = [
        entry for entry in existing if normalized_title(entry.get("title") or "") == key
    ]
    if duplicates:
        lines = "\n  ".join(
            f"#{_int_or_none(entry.get('number'))} {_safe(entry.get('html_url') or '', MAX_URL_CHARS)}"
            f"  {_safe(entry.get('title') or '', MAX_TITLE_CHARS)}"
            for entry in duplicates
        )
        raise BuilderGitHubError(
            f"An open {label!r} issue already carries this title, so filing a second one would "
            f"split the same debt across two items:\n  {lines}\nComment on the existing item, or "
            "give this finding a title that says how it differs."
        )
    near = [
        (entry, title_similarity(title, entry.get("title") or ""))
        for entry in existing
        if title_similarity(title, entry.get("title") or "") >= NEAR_MATCH_THRESHOLD
    ]
    # A WARNING, not a refusal: near-match is a heuristic, and a heuristic that blocks has no
    # override. The caller sees the neighbours and decides.
    for entry, score in sorted(near, key=lambda pair: -pair[1]):
        print(
            f"builder_warning: near match ({score:.2f}) to an existing {label!r} issue: "
            f"#{_int_or_none(entry.get('number'))} "
            f"{_safe(entry.get('html_url') or '', MAX_URL_CHARS)}  "
            f"{_safe(entry.get('title') or '', MAX_TITLE_CHARS)}",
            file=sys.stderr,
        )

    # NOTHING ELSE. No assignee, no milestone, no project: a debt item is a note in the repository,
    # and anything that puts it on the board is a change to the director's board the builder made.
    created = ctx.client._http(
        "POST", f"/repos/{_seg(ctx.cfg.repo)}/issues", {"title": title, "body": body, "labels": [label]}
    )
    if not isinstance(created, dict):
        raise BuilderGitHubError("GitHub did not return the created issue.")
    number = _int_or_none(created.get("number"))
    if number is None:
        raise BuilderGitHubError("GitHub returned a created issue with no number.")
    url = _safe(created.get("html_url") or "", MAX_URL_CHARS)

    # (1) A 201 IS NOT SUCCESS. GitHub silently drops `labels` when the token cannot write issues,
    # and the label is the only thing that makes this findable as debt.
    read_back = get_issue(ctx.client, ctx.cfg.repo, number)
    labels = sorted(issue_labels(read_back))
    if labels != [label]:
        raise BuilderGitHubError(
            f"GitHub created issue #{number} ({url}) but reading it back shows labels "
            f"{labels or '[]'}, not exactly [{label!r}]. GitHub silently drops `labels` when the "
            "token lacks write access to the repository's issues, and anything EXTRA means "
            "something else labelled it. The issue exists; fix its labels by hand and give the "
            "token issues:write before filing another."
        )

    # (2) And it must not be ON the board. An org auto-add workflow can put every new issue on the
    # project, and a debt item appearing on the product board is a change the builder did not make.
    if issue_on_project(ctx.client, ctx.cfg, number):
        raise _BoardTouched(
            f"Issue #{number} ({url}) was filed as {label!r} debt but is NOW ON project "
            f"{ctx.cfg.project_number} owned by {ctx.cfg.owner}. The builder did not put it there "
            "-- an organisation auto-add workflow did. The product board has been changed by "
            "automation; remove the item from the board (or turn the workflow off) so the board "
            "keeps saying what the director said."
        )
    if ctx.as_json:
        return _emit(
            {
                "verb": "debt file",
                "number": number,
                "url": url,
                "labels": labels,
                "nearMatches": [
                    {
                        "number": _int_or_none(entry.get("number")),
                        "title": _safe(entry.get("title") or "", MAX_TITLE_CHARS),
                        "url": _safe(entry.get("html_url") or "", MAX_URL_CHARS),
                        "score": round(score, 3),
                    }
                    for entry, score in sorted(near, key=lambda pair: -pair[1])
                ],
            }
        )
    print(f"debt: #{number} {url}")
    return 0


def debt_command(args: argparse.Namespace) -> int:
    def handler(args: argparse.Namespace) -> int:
        return _debt_file(_context(args), args)

    return _run(f"debt {getattr(args, 'action', '')}", handler, args)


__all__ = [
    "BuilderGitHubError",
    "CACHE_PATH",
    "CACHE_TTL_SECONDS",
    "MAX_PAGES",
    "PERSONAL_TOKEN_NOTE",
    "BoardItem",
    "board_command",
    "board_fields",
    "board_items",
    "debt_command",
    "issue_command",
    "normalized_title",
    "title_similarity",
]
