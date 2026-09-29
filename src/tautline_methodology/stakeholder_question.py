"""Stakeholder Q&A on one GitHub issue/PR: `ask` posts a tagged question, `list` reports tags.

Tier 1 salvage (track S2), from the pre-demolition `stakeholder-question-ask`/`-status` handlers.
DROPPED ENTIRELY, on purpose, per the salvage spec: the Project-status sync, `--strict`, and any
board/label coupling. There is no project adapter dependency here at all -- every coordinate
(`--repo`, `--issue`) comes from the command line, so this runs in any repo, adapted or not.

THE NO-WRITE-BACK LAW. `ask` posts one comment. `list` never posts, never edits a label, never
writes a second "answered" marker back to the issue. An "answered" question is a POSITIONAL
inference made fresh every time `list` runs (see `question_records`), not a stored fact -- so there
is nothing to keep in sync and nothing a missed sync could leave stale.

Transport is plain REST against `api.github.com` (issue comments), never Projects GraphQL, and
copies `backlog.py`'s `GitHubBacklog` posture exactly rather than inventing a second one: same
token resolution (env first, `gh auth token` fallback), same redirect refusal, same origin pin,
same bounded `Link`-header pagination. The pieces below are imported from `backlog`, not
reimplemented, so the two transports cannot quietly drift apart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from tautline_methodology import backlog
from tautline_methodology.backlog import (
    GITHUB_API,
    GITHUB_HOST,
    GITHUB_TOKEN_ENVS,
    MAX_PAGES,
    _LINK_NEXT,
    _OWNER_REPO,
    _RefuseRedirect,
    _redact,
    _seg,
    url_path,
)
from tautline_methodology.jira_client import Secret
from tautline_methodology.util import flatten_printable, now_iso, resolve_env, slugify

REQUEST_TIMEOUT_SECONDS = 30
#: Pinned EXPLICITLY, same reasoning as backlog.py's GITHUB_PAGE_SIZE: GitHub's default page size
#: for the comments endpoint is 30, so an omitted `per_page` would silently read only the first 30
#: comments of a longer thread and every marker/heuristic past that point would go unseen.
GITHUB_COMMENTS_PAGE_SIZE = 100

#: Emitted on every new tag. `minervit-question` is parsed too (never emitted) so a marker written
#: before the rebrand is still recognised by `list` rather than silently invisible.
QUESTION_MARKER = "tautline-question"
_MARKER_RE = re.compile(r"<!--\s*(?:tautline|minervit)-question\s+([^>]*)-->")
_MARKER_ATTR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)="([^"]*)"')
_ISSUE_NUMBER_IN_URL_RE = re.compile(r"/(?:issues|pull)/([0-9]+)(?:$|[?#])")
_ISSUE_URL_REPO_RE = re.compile(r"/([^/\s]+/[^/\s]+)/(?:issues|pull)/\d+/?")


class StakeholderQuestionError(Exception):
    """Every user-facing failure this module raises. Always actionable."""


def _safe(text: object, limit: int = 200) -> str:
    """Remote-sourced text, made safe to PRINT and bounded in length. See backlog.py's `_safe`:
    same primitive (`util.flatten_printable`), same reasoning -- ids included."""
    return flatten_printable(text, limit)


def _safe_message(text: object) -> str:
    return flatten_printable(text, 2000, keep_newlines=True)


# --- markers: build one on `ask`, parse every one `list` finds ---------------------------------


def build_marker(*, question_id: str, stakeholder: str, asked_at: str) -> str:
    parts = []
    for key, value in (("id", question_id), ("stakeholder", stakeholder), ("asked_at", asked_at)):
        value = str(value or "").strip()
        if value:
            parts.append(f'{key}="{value.replace(chr(34), chr(39))}"')
    return f"<!-- {QUESTION_MARKER} {' '.join(parts)} -->"


def parse_markers(body: str) -> list[dict[str, str]]:
    """Every `tautline-question`/`minervit-question` marker in `body`, sanitised at extraction.

    `body` is REMOTE text -- anyone who can comment on the issue can write something that looks
    like a marker. Sanitising here, once, at the boundary, means every caller (`list`'s printed
    lines, the `ask` dedupe check) gets safe values without having to remember to do it itself.
    """
    markers = []
    for match in _MARKER_RE.finditer(body or ""):
        attrs = {
            key: _safe(value, 200) for key, value in _MARKER_ATTR_RE.findall(match.group(1))
        }
        if attrs.get("id"):
            markers.append(attrs)
    return markers


def question_id(issue_number: str, question: str, needed_for: str) -> str:
    seed = f"{issue_number}\n{question.strip()}\n{(needed_for or question).strip()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    slug = slugify((needed_for or question)[:60], "question")
    return f"{slug}-{digest}"


# --- issue/PR reference resolution: --issue is a number or a URL, --repo fills the gap ---------


def _issue_number_from_url(issue_url: str) -> str:
    match = _ISSUE_NUMBER_IN_URL_RE.search(issue_url.strip())
    return match.group(1) if match else ""


def _repo_from_issue_url(issue_url: str) -> str:
    """`owner/name` from an issue/PR URL, or "" if it does not parse as one.

    PARSES THE HOST rather than substring-matching for `github.com` anywhere in the string --
    `evilgithub.com/o/r/issues/1` and `evil.example/github.com/o/r/issues/1` (a bare path segment
    after the real, different host) both contain that substring while naming a different site.
    Host comparison is case-insensitive; the owner/name keeps its original casing.
    """
    text = (issue_url or "").strip()
    if not text:
        return ""
    candidate = text if "//" in text.split("?", 1)[0][:8] else f"https://{text}"
    try:
        host = urllib.parse.urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    if host.lower() not in {"github.com", "www.github.com"}:
        return ""
    path = urllib.parse.urlsplit(candidate).path
    match = _ISSUE_URL_REPO_RE.fullmatch(path)
    return match.group(1) if match else ""


def _issue_number(issue_ref: str) -> str:
    text = (issue_ref or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[0-9]+", text):
        return text
    return _issue_number_from_url(text)


def resolve_issue_ref(issue_ref: str, repo_flag: str | None) -> tuple[str, str]:
    """(repo, issue_number) for `--issue`, refusing a `--repo` / URL disagreement.

    There is no adapter "lane repo" to fall back on here (that coupling is dropped on purpose), so
    `--repo` plays the role the adapter used to: the caller's own statement of which repository is
    meant. A bare issue number with no `--repo` has no repository to read at all, and a URL whose
    repo disagrees with an explicitly-passed `--repo` is refused rather than guessed at -- silently
    preferring one would let a copy-pasted URL post to a different repository than intended.
    """
    text = (issue_ref or "").strip()
    if not text:
        raise StakeholderQuestionError("--issue is required: an issue/PR number or a github.com URL.")
    number = _issue_number(text)
    if not number:
        raise StakeholderQuestionError(
            f"--issue must be an issue/PR number or a github.com issue/PR URL, got {issue_ref!r}."
        )
    url_repo = _repo_from_issue_url(text)
    repo = (repo_flag or "").strip()
    if repo and not _OWNER_REPO.fullmatch(repo):
        raise StakeholderQuestionError(f"--repo must be owner/name, got {repo!r}.")
    if url_repo and repo and url_repo.lower() != repo.lower():
        raise StakeholderQuestionError(
            f"--issue names {url_repo}, but --repo says {repo}. Pass one, or make them agree; "
            "refusing rather than guessing which repository you mean."
        )
    resolved = repo or url_repo
    if not resolved:
        raise StakeholderQuestionError(
            "--repo owner/name is required when --issue is a bare number; there is no URL to read "
            "a repository from."
        )
    return resolved, number


# --- transport: plain REST, api.github.com issue comments only ---------------------------------


class _GitHubCommentClient:
    """List/create comments on one issue. Mirrors `backlog.GitHubBacklog`'s transport exactly --
    same credential posture, same redirect refusal, same origin pin -- because this is the second
    caller of that shape in this codebase, not a reason to invent a third one."""

    def __init__(self, *, repo: str, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.repo = repo
        self.timeout = timeout

    def _token(self) -> Secret:
        for env in GITHUB_TOKEN_ENVS:
            value = resolve_env(env).strip()
            if value:
                return Secret(value)
        # Live module-attribute lookup, NOT a direct-name import: conftest's autouse
        # `_no_real_gh_token` fixture patches `backlog._gh_auth_token` specifically, and a
        # `from ... import _gh_auth_token` would have copied the reference at import time,
        # putting this transport's tests outside that guard's reach.
        return Secret(backlog._gh_auth_token())

    @staticmethod
    def _assert_github_origin(url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != GITHUB_HOST:
            raise StakeholderQuestionError(
                f"Refusing to send a GitHub token to {_safe(url, 120)!r}: this client talks only "
                f"to https://{GITHUB_HOST}."
            )

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(_RefuseRedirect())

    def _request(self, method: str, url_or_path: str, payload: object | None = None) -> tuple[object, dict]:
        token = self._token()
        if not token:
            raise StakeholderQuestionError(
                "GitHub credentials: no token available. Export "
                f"{' or '.join(GITHUB_TOKEN_ENVS)} with a token that can comment on issues in "
                f"{self.repo}, or run `gh auth login` so the CLI can supply one."
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
        except StakeholderQuestionError:
            raise
        except urllib.error.HTTPError as exc:
            raise self._typed_error(exc, url_or_path, token) from None
        except (urllib.error.URLError, OSError) as exc:
            raise StakeholderQuestionError(
                _redact(f"GitHub request to {url_or_path} did not complete: {exc}", token)
            ) from None
        if not body.strip():
            return None, headers
        try:
            return json.loads(body), headers
        except ValueError:
            raise StakeholderQuestionError(f"GitHub returned a non-JSON body for {url_or_path}.") from None

    @staticmethod
    def _error_detail(exc: urllib.error.HTTPError) -> str:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("message") or "").strip()[:400]

    def _typed_error(self, exc: urllib.error.HTTPError, path: str, token: Secret) -> StakeholderQuestionError:
        detail = self._error_detail(exc)
        suffix = f" GitHub said: {_safe(detail, 400)}" if detail else ""
        if exc.code in (401, 403):
            return StakeholderQuestionError(
                _redact(
                    f"GitHub rejected the credentials for {path} (HTTP {exc.code}). Check "
                    f"{' / '.join(GITHUB_TOKEN_ENVS)} (or `gh auth login`) and that the token can "
                    f"comment on issues in {self.repo}.{suffix}",
                    token,
                )
            )
        if exc.code == 404:
            return StakeholderQuestionError(
                _redact(
                    f"GitHub has nothing at {path} (HTTP 404). Check --repo/--issue -- {self.repo!r} "
                    f"-- and that the token can see it (private repos need a token that can read "
                    f"them).{suffix}",
                    token,
                )
            )
        return StakeholderQuestionError(_redact(f"GitHub returned HTTP {exc.code} for {path}.{suffix}", token))

    def _paged(self, path: str) -> list:
        items: list = []
        url: str | None = path
        for _ in range(MAX_PAGES):
            if url is None:
                return items
            payload, headers = self._request("GET", url)
            if not isinstance(payload, list):
                raise StakeholderQuestionError(
                    f"GitHub {url_path(url)} returned unexpected JSON; expected a list."
                )
            items.extend(payload)
            match = _LINK_NEXT.search(headers.get("link", ""))
            url = match.group(1) if match else None
        raise StakeholderQuestionError(
            f"GitHub kept offering another page of {url_path(path)} after {MAX_PAGES} requests. "
            "Refusing to keep paging; report this if the thread is legitimately that long."
        )

    def list_comments(self, issue_number: str) -> list[dict]:
        query = urllib.parse.urlencode({"per_page": str(GITHUB_COMMENTS_PAGE_SIZE)})
        payload = self._paged(f"/repos/{_seg(self.repo)}/issues/{_seg(issue_number)}/comments?{query}")
        return [entry for entry in payload if isinstance(entry, dict)]

    def post_comment(self, issue_number: str, body: str) -> dict:
        payload, _headers = self._request(
            "POST", f"/repos/{_seg(self.repo)}/issues/{_seg(issue_number)}/comments", {"body": body}
        )
        if not isinstance(payload, dict):
            raise StakeholderQuestionError("GitHub returned unexpected JSON for a posted comment.")
        return payload


# --- comment shape: raw REST JSON -> sanitised fields -------------------------------------------


def comment_author(comment: dict) -> str:
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return _safe(login or "", 80)


def comment_created(comment: dict) -> str:
    return _safe(comment.get("created_at") or "", 40)


def comment_url(comment: dict) -> str:
    return _safe(comment.get("html_url") or "", 300)


def comment_body(comment: dict) -> str:
    """UNSANITISED on purpose: `parse_markers` needs the real text, and sanitises what it keeps."""
    return str(comment.get("body") or "")


# --- the answered/open heuristic, stated once and printed in --help too ------------------------


def question_records(comments: list[dict]) -> list[dict]:
    """One record per open-question tag found in `comments`, each carrying a positional verdict.

    "Answered" means: the first comment, anywhere after the tagged one in this issue's comment
    history, authored by someone OTHER than whoever posted the tagged comment. It is a POSITION
    check, not a content one -- it does not read whether the reply actually answers anything, and
    says so rather than pretending a keyword scan could tell. This is the "keep the heuristic
    simple" half of the salvage spec; `--help` states it in the same words.
    """
    records = []
    for index, comment in enumerate(comments):
        for marker in parse_markers(comment_body(comment)):
            asker = comment_author(comment).lower()
            reply = next(
                (later for later in comments[index + 1 :] if comment_author(later).lower() != asker),
                None,
            )
            records.append(
                {
                    "id": marker.get("id", ""),
                    "stakeholder": marker.get("stakeholder", ""),
                    # GitHub's OWN timestamp, not the marker's self-reported `asked_at` -- the
                    # marker still carries one (readable on the raw comment without running
                    # `list`), but anyone who can comment on the issue could write a marker
                    # claiming any `asked_at` they like, where `created_at` comes from GitHub
                    # itself.
                    "asked_at": comment_created(comment),
                    "question_url": comment_url(comment),
                    "status": "answered" if reply is not None else "open",
                    "reply_author": comment_author(reply) if reply is not None else "",
                    "reply_url": comment_url(reply) if reply is not None else "",
                }
            )
    return records


# --- the two verbs -------------------------------------------------------------------------------


def _cmd_ask(args: argparse.Namespace) -> int:
    repo, issue_number = resolve_issue_ref(args.issue, args.repo)
    question = " ".join((args.question or "").split())
    if not question:
        raise StakeholderQuestionError("--question is required and must be non-blank.")
    why = " ".join((args.why or "").split())
    needed_for = " ".join((getattr(args, "needed_for", "") or "").split())
    stakeholder = (args.stakeholder or "").strip()
    if stakeholder and not stakeholder.startswith("@"):
        stakeholder = f"@{stakeholder}"
    qid = (getattr(args, "question_id", "") or "").strip() or question_id(
        issue_number, question, needed_for or question
    )
    marker = build_marker(question_id=qid, stakeholder=stakeholder, asked_at=now_iso())
    lines = [f"{stakeholder} I need a clarification.".strip() if stakeholder else "I need a clarification."]
    lines += ["", "Question:", question]
    if why:
        lines += ["", "Why it matters:", why]
    if needed_for:
        lines += ["", "Needed for:", needed_for]
    lines += ["", marker]
    body = "\n".join(lines) + "\n"
    # Scanned as ONE composed string, not a hand-picked subset of the fields that fed it: a
    # subset scan (question/why/needed_for only, an earlier version of this function) let
    # --stakeholder and --question-id flow into the @-mention line and the marker's
    # stakeholder=/id= attributes completely unscanned, which is the ONLY thing this check exists
    # to prevent. Scanning the fully rendered body, immediately before the first network call
    # (the dedupe GET below, not just the POST), makes every field that ends up in the comment --
    # present today or added later -- covered by construction rather than by remembering to list
    # it here.
    if _looks_like_secret(body):
        raise StakeholderQuestionError(
            "The composed comment contains a secret-looking value (a token/password/key-shaped "
            "pattern) in --question, --why, --needed-for, --stakeholder, or --question-id; "
            "refusing to post it to GitHub (not echoing the match here either). Remove the value "
            "-- paste a redacted excerpt if you need to reference it -- and rerun."
        )
    client = _GitHubCommentClient(repo=repo)
    for record in question_records(client.list_comments(issue_number)):
        if record["id"] == qid:
            print("stakeholder_question_ask: already-present")
            print(f"stakeholder_question_id: {qid}")
            print(f"stakeholder_question_repo: {repo}")
            print(f"stakeholder_question_issue: {issue_number}")
            print(f"stakeholder_question_status: {record['status']}")
            print(f"stakeholder_question_url: {record['question_url'] or 'unknown'}")
            return 0
    posted = client.post_comment(issue_number, body)
    print("stakeholder_question_ask: posted")
    print(f"stakeholder_question_id: {qid}")
    print(f"stakeholder_question_repo: {repo}")
    print(f"stakeholder_question_issue: {issue_number}")
    print(f"stakeholder_question_url: {comment_url(posted) or 'unknown'}")
    _warn_if_concurrent_duplicate(client, issue_number, qid)
    return 0


def _warn_if_concurrent_duplicate(client: "_GitHubCommentClient", issue_number: str, qid: str) -> None:
    """Two concurrent `ask` invocations for the same question can both pass the dedupe check
    above before either has posted -- there is no server-side lock this client can take to
    prevent that, so the honest fix is a POST-verify, not pretending the earlier check made the
    race impossible. Re-reads the thread and warns (naming every duplicate's URL) if it now finds
    more than one comment carrying this id; never raises, since the post itself already succeeded
    and was reported -- this is a best-effort second look, not a gate on top of it.
    """
    try:
        records = question_records(client.list_comments(issue_number))
    except StakeholderQuestionError as exc:
        # UNKNOWN, stated as such, not silence: silence here would read as "no race detected"
        # when the truth is "the check could not run."
        print(f"stakeholder_question_race_check: unavailable - {_safe_message(exc)}")
        return
    matches = [record for record in records if record["id"] == qid]
    if len(matches) > 1:
        urls = ", ".join(match["question_url"] or "unknown" for match in matches)
        print(
            f"stakeholder_question_race_warning: {len(matches)} comments now carry id={qid} "
            f"(a concurrent `ask` likely posted the same tag): {urls}"
        )


def _cmd_list(args: argparse.Namespace) -> int:
    repo, issue_number = resolve_issue_ref(args.issue, args.repo)
    client = _GitHubCommentClient(repo=repo)
    records = question_records(client.list_comments(issue_number))
    if not records:
        print(f"stakeholder_question_list: repo={repo} issue={issue_number} no tagged questions found")
        return 0
    open_count = 0
    answered_count = 0
    for record in records:
        stakeholder = record["stakeholder"] or "unknown"
        if record["status"] == "answered":
            answered_count += 1
            print(
                f"stakeholder_question_answered: issue={issue_number} id={record['id']} "
                f"stakeholder={stakeholder} reply_by={record['reply_author'] or 'unknown'} "
                f"reply_url={record['reply_url'] or 'unknown'}"
            )
        else:
            open_count += 1
            print(
                f"stakeholder_question_open: issue={issue_number} id={record['id']} "
                f"stakeholder={stakeholder} asked_at={record['asked_at'] or 'unknown'} "
                f"question_url={record['question_url'] or 'unknown'}"
            )
    print(f"stakeholder_question_open_count: {open_count}")
    print(f"stakeholder_question_answered_count: {answered_count}")
    # Inline, not just in --help: a caller piping this stdout never sees --help, and "answered"
    # here is a claim about WHO commented and WHEN, not about what the reply says.
    print(
        "stakeholder_question_note: status is positional (first later comment by another "
        "author), not content-verified -- a reply that does not actually answer the question "
        "still counts as answered."
    )
    return 0


def _looks_like_secret(text: str) -> bool:
    """The same shapes `validate_event_value` refuses in a decision-record field
    (`cli.SESSION_JOURNAL_SECRET_PATTERNS`) -- imported lazily so this module never has to load the
    whole CLI engine just to ask a question, and so there is exactly one pattern list, not two that
    can quietly drift apart.
    """
    from tautline_methodology.cli import SESSION_JOURNAL_SECRET_PATTERNS

    return any(re.search(pattern, text) for pattern in SESSION_JOURNAL_SECRET_PATTERNS)


def stakeholder_question_command(args: argparse.Namespace) -> int:
    """`tautline stakeholder-question ask|list`. No SystemExit, no traceback: every failure is a
    printed `stakeholder_question_error:` line and exit 1, matching `backlog_command`'s posture."""
    action = args.action
    try:
        return _cmd_ask(args) if action == "ask" else _cmd_list(args)
    except StakeholderQuestionError as exc:
        print(f"stakeholder_question_error: {_safe_message(exc)}")
        return 1
    except Exception as exc:  # a CLI never answers with a traceback
        print(
            f"stakeholder_question_error: the {action} command hit an unexpected "
            f"{type(exc).__name__}: {_safe(exc, 200)}. That is a bug in this command, not a "
            "problem with your issue; please report it with the command you ran."
        )
        return 1
