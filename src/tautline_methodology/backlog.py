"""The backlog seam: one interface, three boards (local file, GitHub issues, Jira Cloud).

THE NO-SYNC LAW. Nothing in this module runs in the background, on a hook, on a timer, or on any
event other than the four explicit commands a person or an agent types: `tautline backlog
list|add|take|done`. There is no goal tracker, no milestone mirror, no board guard, no status
reconciler, and no "keep the queue in step" job. The 2026-08-28 process-bankruptcy demolition
removed a board-sync engine that had grown around exactly this seam; this module is the shape that
keeps it out. If a future change here needs a background writer, the change is wrong.

THE NO-FALLBACK LAW, which is the same law seen from the other side. When credentials are missing
or the network fails, these commands ERROR -- actionably, naming the environment variable to set --
and they never, under any condition, degrade to writing a local file instead. A silent local
fallback recreates divergence between two backlogs, and the next thing anyone builds to fix
divergence is a sync engine. That is the disease. Failing loudly is the cure.

THE NO-UNVERIFIED-SUCCESS LAW. A write is not reported as done because the request returned 2xx. It
is reported as done when the board is read back and SAYS so: the label is present, the transition
landed in the status category it was supposed to. This framework's dominant defect class is a
control that reports success while doing nothing, and every mutation here has a partial-success mode
that looks exactly like the whole thing -- an issue created without its label (which the queue reads
by), a transition that fired on the wrong workflow entry, a table row rewritten for a file that
never moved. Each is verified below, and each verification has a test that plants the defect.

THE CONFIGURED PROVIDER IS THE SOURCE OF TRUTH. When a project's lean config carries a `backlog`
block, that provider is the project's EXCLUSIVE backlog surface: no `BACKLOG.md`, no `TODO.md`, no
deferred-items notes scattered through the repo, and no local mirror of the remote board. Follow-ups
and deferred work are filed with `tautline backlog add` and nowhere else. The generated adapter says
so in one line, so an agent reads it every session.

TWO RULES FOR REMOTE DATA, because everything below the transport is written by somebody else:

* it is never printed raw -- `_safe` flattens control characters and caps length, so an issue title
  carrying an ANSI escape cannot forge output in the terminal that reads it, and an id of unbounded
  length cannot set a table's column width; and
* it is never interpolated into a URL unvalidated -- an id from a board response goes back through
  the same grammar check a hand-typed one does, and every path segment is percent-encoded.

The interface is four methods and one item shape, and it is deliberately tiny:

    list()                 -> the OPEN queue, in priority order (top of the list is next)
    add(title, body)       -> the created Item (its `.id` is the id the seam names)
    take(item_id | None)   -> the Item, now marked in progress; None takes the top of the queue
    done(item_id)          -> the Item, now closed

`add`/`take`/`done` return the whole `Item` rather than a bare id because the CLI's one-line answer
is "id and url", and a provider that returned only an id would force every caller to make a second
round trip for the second half of the line.

`list()` is the QUEUE, not the archive: every provider returns only work that is not finished, in
the order the provider ranks it, following pagination to the end. Finished items stay where the
provider keeps them (a `done/` directory, a closed issue, a Done transition) and are reachable there.
"""

from __future__ import annotations

import abc
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from tautline_methodology import jira_client, lean

# `Secret` is generic -- a credential that redacts itself when printed -- and lives beside the
# salvaged Jira client that introduced it so there is ONE definition rather than a second copy here.
from tautline_methodology.jira_client import Secret
from tautline_methodology.util import flatten_printable, resolve_env

PROVIDERS = ("local", "github", "jira")

#: The three states every provider normalises into. A caller never sees a provider's own vocabulary.
READY = "ready"
IN_PROGRESS = "in-progress"
DONE = "done"

DEFAULT_QUEUE_PATH = "QUEUE.md"
DEFAULT_GITHUB_LABEL = "backlog"
#: The label GitHub `take` adds. Not configurable: it is bookkeeping this seam owns, and a knob for
#: it would be a second thing to keep in step with the board.
GITHUB_IN_PROGRESS_LABEL = "in-progress"
GITHUB_API = "https://api.github.com"
GITHUB_HOST = "api.github.com"
GITHUB_TOKEN_ENVS = ("GITHUB_TOKEN", "GH_TOKEN")
#: Pinned EXPLICITLY. GitHub's default page size is 30, so dropping this parameter would silently
#: return the first 30 items of a longer backlog and every count downstream would be wrong.
GITHUB_PAGE_SIZE = 100

JIRA_IN_PROGRESS_TRANSITION = "In Progress"
JIRA_DONE_TRANSITION = "Done"
#: Jira Cloud's `maxResults` for a JQL search defaults to 50 and is capped at 5000.
JIRA_PAGE_SIZE = 100

#: Every pager is BOUNDED. A server that keeps offering a next page -- through a bug, a loop, or a
#: hostile response -- must cost a finite number of requests, not an unbounded session.
MAX_PAGES = 50

#: An id is rendered into a table whose column width it sets, and into a URL path. Both are reasons
#: to bound it before it is used, not after somebody notices a 4KB "issue number".
MAX_ID_CHARS = 40

#: A local id is `YYYY-MM-DD-<slugify() output>`: at most 10 + 1 + 60 = 71 characters (see
#: `LocalBacklog.add`'s `stem` and `slugify`'s own `[:60]`), and -- unlike a GitHub or Jira id --
#: entirely SELF-generated rather than read back from a remote API, so it needs no defence against
#: an API response forging terminal output or setting an unbounded column width; `_SLUG_STRIP`
#: already restricts it to `[a-z0-9-]`. `MAX_ID_CHARS` truncating it to 40 for the PR stamp
#: (`stamp_id`) would print a `Backlog: ...` line that no longer names the real item -- the
#: opposite of ready-to-paste. This is generous headroom over the real 71-character maximum, not a
#: guess.
_LOCAL_STAMP_ID_MAX_CHARS = 80

#: Local layout. `ready` is where `add` writes and `list` reads; the other two are where `take` and
#: `done` move a file to. Directory membership IS the state -- there is no status column to
#: disagree with the filesystem.
LOCAL_DIRS = {READY: "ready", IN_PROGRESS: "building", DONE: "done"}

REQUEST_TIMEOUT_SECONDS = 30
#: lane-status runs at session start, so its live read gets a short leash. A slow board must cost a
#: session a few seconds and one honest "unreachable" line, never a hang. The value is THREADED all
#: the way to `opener.open`; a leash held by the caller and ignored by the transport is not a leash.
ADVISORY_TIMEOUT_SECONDS = 5

_OWNER_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_QUEUE_ROW = re.compile(r"^\s*\|(?P<cells>.*)\|\s*$")
#: Cells are separated by pipes the writer did not escape. `(?<!\\)` is the whole difference between
#: a title with a pipe in it round-tripping and being silently dropped on the next write.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
#: Link text may contain escaped `]`, `[` and `|`, so it is "any escape, or any non-`]` non-`\`".
_QUEUE_LINK = re.compile(r"\[(?P<title>(?:\\.|[^\]\\])*)\]\((?P<path>[^)]+)\)")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
#: The characters a Markdown table row and a Markdown link give structural meaning to. A title is
#: the user's words: it is escaped on the way in and unescaped on the way out, never rewritten.
_ESCAPE_IN_CELL = ("\\", "|", "[", "]")
_UNESCAPE = re.compile(r"\\(.)")
#: `<...>; rel="next"` inside a GitHub `Link` header.
_LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def _escape(text: str) -> str:
    for char in _ESCAPE_IN_CELL:
        text = text.replace(char, "\\" + char)
    return text


def _unescape(text: str) -> str:
    return _UNESCAPE.sub(r"\1", text)


def _safe(text: object, limit: int = 110) -> str:
    """Remote-sourced text, made safe to PRINT and bounded in length.

    Both halves are load-bearing and neither is cosmetic. Collapsing whitespace alone leaves ESC and
    BEL untouched -- they are not whitespace -- so an issue title containing `\\x1b[2K` can erase the
    line a report just wrote and forge the one above it. Capping alone leaves an id of arbitrary
    length setting a table's column width. Everything that reaches a terminal from a board goes
    through here, ids included. The primitive lives in `util` so the Jira client sanitises its own
    error bodies with the SAME function -- the first version had it only here, and a remote error
    body reached stderr around the outside of it.
    """
    return flatten_printable(text, limit)


def _safe_message(text: object) -> str:
    """A whole error message on its way to a terminal. Control characters out, OUR newlines kept.

    The last line of defence, at the one place every failure is printed, so an error type nobody has
    written yet cannot bypass the sanitising its own construction forgot. Newlines survive because by
    this point they are this codebase's own -- a config validation report is deliberately multi-line
    and flattening it would cost the reader the list of what is actually wrong. Remote text is
    flattened at its source instead, where a response body that can add lines is a forgery risk in
    itself and not merely a formatting one.
    """
    return flatten_printable(text, 4000, keep_newlines=True)


QUEUE_HEADER = ("| # | Item | Notes |", "|---|------|-------|")

#: `list` is a METHOD on every provider, so a bare `list[...]` annotation written inside a provider
#: class body resolves to that method rather than to the builtin. One module-level alias, used
#: wherever a provider needs to say "a list of rows".
RowList = list[dict]


class BacklogError(Exception):
    """Every failure this seam reports. Always actionable: it names the next thing to do."""


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses a redirect rather than replaying the `Authorization` header at a new host.

    urllib follows redirects by default and RE-SENDS headers, so a 302 to an attacker-controlled
    host is handed the bearer token. Neither API needs redirects followed, so refusing costs
    nothing. `jira_client` carries the same refusal for its own transport; the two are separate
    because each raises its own module's error type, and a class-level test asserts that EVERY HTTP
    path in this subsystem installs one -- which is what stops the pair from drifting apart.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib contract
        raise BacklogError(
            f"GitHub returned a {code} redirect; refusing to follow it because the Authorization "
            "header would be replayed at the new location. If api.github.com genuinely moved, this "
            "is a bug worth reporting."
        )


@dataclass(frozen=True)
class Item:
    """One backlog item, in the seam's vocabulary rather than any provider's.

    `id` is what `take`/`done` accept: a slug for local, an issue number for GitHub, an issue key
    for Jira. `url` is empty for the local provider, which has no URL to give.
    """

    id: str
    title: str
    body: str = ""
    state: str = READY
    url: str = ""

    def reference(self) -> str:
        """`id`, or `id (url)`. THE output form, so both halves are sanitised here."""
        ident = _safe(self.id, MAX_ID_CHARS)
        return f"{ident} ({_safe(self.url, 200)})" if self.url else ident


class BacklogProvider(abc.ABC):
    """The whole interface. Four methods; no lifecycle, no sync, no background anything."""

    #: The `provider` value in the config that selects this implementation.
    name: str = ""

    def __init__(self) -> None:
        #: Things that happened which the caller should know about but which are not failures --
        #: a best-effort step that was skipped, and why. Printed by the command. A skipped step
        #: that says nothing is indistinguishable from one that worked.
        self.notices: list[str] = []

    @abc.abstractmethod
    def describe(self) -> str:
        """The board, for a human: `github (owner/name)`, `jira (PROJ)`, `local (QUEUE.md)`."""

    @abc.abstractmethod
    def list(self) -> Sequence[Item]:
        """The OPEN queue, in the provider's priority order. Top of the list is next."""

    @abc.abstractmethod
    def add(self, title: str, body: str = "") -> Item:
        """File a new item at the end of the queue. Returns the created item."""

    @abc.abstractmethod
    def take(self, item_id: str | None = None) -> Item:
        """Mark an item in progress. `None` takes the top of the queue."""

    @abc.abstractmethod
    def done(self, item_id: str) -> Item:
        """Close an item."""

    # --- shared helpers ---------------------------------------------------------------------

    def stamp_id(self, item: Item) -> str:
        """`item.id`, formatted the way it belongs in a `Backlog: <id>` PR stamp.

        The default is the bare, sanitised id -- right for local (a slug) and Jira (a key like
        `PROJ-12`). GitHub overrides this: its issue number needs the leading `#` GitHub's own
        closing keywords use, so `take`'s printed stamp is paste-ready rather than needing a
        hand-added `#`.
        """
        return _safe(item.id, MAX_ID_CHARS)

    def _top(self) -> Item:
        items = [item for item in self.list() if item.state == READY]
        if not items:
            raise BacklogError(
                f"{self.describe()} has no item waiting to be taken. File one with "
                '`tautline backlog add "<title>"`.'
            )
        return items[0]


# --------------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------------

_CONFIG_KEYS = ("provider", "path", "repo", "label", "site", "project", "board")

# Track G: cap-overflow fix. Sane per-field ceilings for the free-text backlog strings that have NO
# existing length bound -- the SAME concern MAX_ID_CHARS above exists for, applied to config rather
# than a synced item. Sized, together with lean.LEAN_*_MAX_CHARS, so a config with every free-text
# field simultaneously at its cap still renders under lean.LEAN_ADAPTER_MAX_BYTES (see
# lean.test_the_maximal_valid_config_still_renders_under_the_cap) -- not just "catches one
# pathological field," though it does that too, with a message naming that ONE field. `label` at 50
# matches GitHub's own real issue-label length limit, not a round number picked in the abstract, and
# stays untouched below: it never reaches the render (`describe_config` reads `repo`, never `label`,
# for the github line), so it is not part of the byte budget at all.
#
# RETIGHTENED (PR #630 review, R1 P1), `path`/`repo`/`project` only: the original 70/70/50 were
# never checked against the joint worst case (every OTHER field at its own cap, plus `handoffs`)
# and did not fit it -- see lean.py's LEAN_*_MAX_CHARS comment for the measured numbers. `project`
# is cut hardest (50 -> 12) because it is jira's single biggest lever on `_backlog_norm`'s rendered
# line and real Jira Cloud project keys are short mnemonics in practice (Atlassian's own UI default
# caps new keys at 10); `path`/`repo` still comfortably clear this repo's own values (`QUEUE.md`;
# `tautlines/tautline-dev`, 22 chars) and realistic longer ones (`docs/backlog/QUEUE.md`;
# `kubernetes/kubernetes`).
#
# Deliberately NOT every key in `_CONFIG_KEYS`: `site` and `board` already have a real,
# domain-specific length bound below -- `jira_client.site_url_issue`'s `MAX_HOSTNAME` (253, the DNS
# limit) and `board_id_issue`'s `MAX_BOARD_ID_DIGITS` -- and a generic cap here would run FIRST
# (this loop returns early on any error) and shadow that better, more specific message with a
# blander one. `project`'s format regex (`JIRA_PROJECT_KEY = ^[A-Z][A-Z0-9]+$`) has no length bound
# at all despite looking like it does -- `+` is unlimited, not "reasonably short" -- so it still
# needs one here. `site` is untouched for the same reason as `label`: it never reaches the render
# either (`describe_config` builds jira's line from `project`/`board` only), so retightening it
# would cost real Jira Cloud adopters headroom with zero byte-budget benefit -- verified by reading
# `describe_config`, not assumed.
_BACKLOG_FIELD_MAX_CHARS = {
    "path": 40,
    "repo": 35,
    "label": 50,
    "project": 12,
}


def backlog_config_errors(value: object) -> list[str]:
    """Validate a lean config's `backlog` block. Returns human-readable errors; empty means valid.

    Called by `lean.lean_config_errors`, so an invalid block is refused by `validate-adapter` and
    by every command that loads the config -- not discovered later as a confusing API failure.
    """
    if not isinstance(value, dict):
        return ["backlog: expected an object with a 'provider'"]
    errors: list[str] = []
    for key in sorted(set(value) - set(_CONFIG_KEYS)):
        errors.append(f"backlog: unknown property {key!r} (allowed: {', '.join(_CONFIG_KEYS)})")
    provider = value.get("provider")
    if provider not in PROVIDERS:
        return errors + [
            f"backlog.provider: expected one of {', '.join(PROVIDERS)}, got {provider!r}"
        ]
    for key in ("path", "repo", "label", "site", "project", "board"):
        if key not in value:
            continue
        if not isinstance(value[key], str):
            errors.append(f"backlog.{key}: expected a string")
            continue
        cap = _BACKLOG_FIELD_MAX_CHARS.get(key)
        if cap is not None and len(value[key]) > cap:
            errors.append(
                f"backlog.{key}: {len(value[key])} characters, over the {cap}-character cap"
            )
    if errors:
        return errors

    if provider == "github":
        repo = str(value.get("repo") or "").strip()
        if not repo:
            errors.append(
                "backlog.repo is required for the github provider: 'owner/name' of the repository "
                "whose issues are the backlog"
            )
        elif not _OWNER_REPO.match(repo):
            errors.append(
                f"backlog.repo must be 'owner/name': {repo!r} is not. A URL, a bare name or a "
                "trailing '.git' will not resolve against the GitHub REST API."
            )
        if "label" in value and not str(value["label"]).strip():
            errors.append(
                "backlog.label must be a non-blank issue label, or absent to use "
                f"{DEFAULT_GITHUB_LABEL!r}"
            )
    elif provider == "jira":
        # The grammar lives with the client that consumes these values against a live API, written
        # in one pass rather than one check per review round.
        for issue in (
            jira_client.site_url_issue(str(value.get("site") or "")),
            jira_client.project_key_issue(str(value.get("project") or "")),
            jira_client.board_id_issue(str(value.get("board") or "")),
        ):
            if issue:
                errors.append(issue)
    elif provider == "local" and "path" in value and not str(value["path"]).strip():
        errors.append(
            f"backlog.path must be a non-blank queue file path, or absent to use "
            f"{DEFAULT_QUEUE_PATH!r}"
        )
    return errors


def backlog_config(cfg: dict | None) -> dict:
    """The `backlog` block, or the local default when a lean config does not carry one.

    Absent means local-with-defaults rather than "no backlog", because every repository has a
    backlog whether or not it has named one; the question is only whether it is written down.
    """
    block = (cfg or {}).get("backlog")
    if not isinstance(block, dict):
        return {"provider": "local", "path": DEFAULT_QUEUE_PATH}
    return dict(block)


def describe_config(block: dict) -> str:
    """`<provider> (<repo|project|path>)` -- the same phrase the adapter line and lane-status use."""
    provider = str(block.get("provider") or "local")
    if provider == "github":
        return f"github ({str(block.get('repo') or '')})"
    if provider == "jira":
        project = str(block.get("project") or "")
        board = str(block.get("board") or "").strip()
        return f"jira ({project}{'/board ' + board if board else ''})"
    return f"local ({str(block.get('path') or DEFAULT_QUEUE_PATH)})"


def provider_for(root: Path, cfg: dict | None, *, timeout: float = REQUEST_TIMEOUT_SECONDS):
    """Build the provider a project's lean config names. Refuses an invalid block by name."""
    block = backlog_config(cfg)
    errors = backlog_config_errors(block)
    if errors:
        raise BacklogError(
            "The `backlog` block in this project's config is not usable:\n  "
            + "\n  ".join(errors)
            + "\nFix it and run `tautline validate-adapter --project .tautline.json` to confirm."
        )
    provider = str(block["provider"])
    if provider == "github":
        return GitHubBacklog(
            repo=str(block["repo"]).strip(),
            label=str(block.get("label") or DEFAULT_GITHUB_LABEL).strip(),
            timeout=timeout,
        )
    if provider == "jira":
        return JiraBacklog(
            site=str(block["site"]).strip(),
            project=str(block["project"]).strip(),
            board=str(block.get("board") or "").strip(),
            timeout=timeout,
        )
    return LocalBacklog(root=root, queue_path=str(block.get("path") or DEFAULT_QUEUE_PATH))


# --------------------------------------------------------------------------------------------
# the PR<->backlog reference stamp, read by scripts/check_pr_backlog_ref.py
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceGrammar:
    """One provider's accepted forms for a PR's `Backlog: <id>` reference stamp.

    A PR passes when its title or body matches ANY pattern here. `describe` is what a failing PR
    is told -- the CONFIGURED provider's forms only, never a cross-provider list, because a
    Jira-configured repo has no use for a GitHub closing keyword and should not be told about one.
    """

    patterns: tuple[re.Pattern[str], ...]
    describe: str


#: `Backlog: <id>` names no provider-specific syntax, so it is accepted everywhere -- the one row
#: every OTHER entry in REFERENCE_GRAMMAR below inherits for free, rather than restating.
_GENERIC_STAMP_RE = re.compile(r"backlog\s*:\s*\S+", re.IGNORECASE)

#: GitHub's own closing-keyword grammar, salvaged from the pre-2026-08-28 contract and
#: review-hardened there across two rounds (Codex R1 P2, R2 P2): the three forms GitHub actually
#: auto-closes on -- bare `#123`, cross-repository `owner/repo#123`, and the full issue URL --
#: because a check that recognises only the first refuses PRs GitHub itself would still honour,
#: which is the most expensive false positive a blocking check can have. This module never fires
#: on the comma-joined-references or fabricated-reference misuse the old contract also policed --
#: this is a presence check, not a hygiene enforcer; see the module docstring's NO-SYNC LAW
#: neighbour on why the plumbing around that old contract was deliberately not brought back.
_GITHUB_CLOSING_REF = (
    r"(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?:[\w.-]+/[\w.-]+)?#\d+)"
)
_GITHUB_CLOSING_KEYWORD_RE = re.compile(
    rf"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\b[ \t]*:?[ \t]*{_GITHUB_CLOSING_REF}",
    re.IGNORECASE,
)

#: A bare Jira issue key, e.g. `PROJ-12`. Reuses `jira_client.JIRA_PROJECT_KEY`'s own charset
#: (stripping its `^`/`$` anchors) rather than a second copy of the project-key grammar, so the
#: two cannot drift apart.
_JIRA_KEY_RE = re.compile(rf"\b{jira_client.JIRA_PROJECT_KEY.pattern[1:-1]}-\d+\b")

#: One entry per name in PROVIDERS. `test_reference_grammar_covers_every_provider` fails the
#: instant the two disagree, so a fourth provider cannot ship silently defaulting to no grammar
#: (which would make its every PR pass) or borrowing another provider's (which would make its
#: every PR fail on correct input) -- discovery-complete against the seam, not hand-listed beside
#: it.
REFERENCE_GRAMMAR: dict[str, ReferenceGrammar] = {
    "local": ReferenceGrammar(
        patterns=(_GENERIC_STAMP_RE,),
        describe="`Backlog: <slug>` -- the queue-item slug `tautline backlog list` shows",
    ),
    "github": ReferenceGrammar(
        patterns=(_GENERIC_STAMP_RE, _GITHUB_CLOSING_KEYWORD_RE),
        describe=(
            "`Backlog: #<issue>`, or a GitHub closing keyword "
            "(`Closes #<issue>`, `Fixes #<issue>`, `Resolves #<issue>`, ...)"
        ),
    ),
    "jira": ReferenceGrammar(
        patterns=(_GENERIC_STAMP_RE, _JIRA_KEY_RE),
        describe="`Backlog: <KEY>`, or a bare Jira issue key (e.g. `PROJ-12`)",
    ),
}


# --------------------------------------------------------------------------------------------
# local: QUEUE.md + ready/building/done
# --------------------------------------------------------------------------------------------


def slugify(title: str) -> str:
    slug = _SLUG_STRIP.sub("-", title.strip().lower()).strip("-")
    return slug[:60].rstrip("-") or "item"


class LocalBacklog(BacklogProvider):
    """A queue file plus `ready/`, `building/` and `done/` directories, in the repository.

    The repo IS the source of truth here, which is the point of the default: a project that has
    named no board still gets one backlog, versioned with the code, and the queue file is the ONLY
    backlog surface. The table row's link says which directory an item is in, so the file's location
    and its state cannot disagree -- there is no status column to fall out of step.

    THE QUEUE FILE IS A DOCUMENT, NOT A TABLE. Only the table block is rewritten; every line before
    and after it is preserved byte for byte and the write is refused if it is not. An earlier
    version kept the preamble and dropped everything below the last row, which would have deleted a
    project's notes on the next `add`.
    """

    name = "local"

    def __init__(self, *, root: Path, queue_path: str = DEFAULT_QUEUE_PATH) -> None:
        super().__init__()
        self.root = Path(root)
        self.queue_path = queue_path
        self.queue = self.root / queue_path
        self.base = self.queue.parent

    def describe(self) -> str:
        return f"local ({self.queue_path})"

    def stamp_id(self, item: Item) -> str:
        """The bare slug, at the wider `_LOCAL_STAMP_ID_MAX_CHARS` rather than the base class's
        `MAX_ID_CHARS` -- see that constant for why a local id does not need the tighter bound a
        remote one does."""
        return _safe(item.id, _LOCAL_STAMP_ID_MAX_CHARS)

    # --- queue file ---------------------------------------------------------------------------

    @staticmethod
    def _split(text: str) -> tuple[list[str], list[str], list[str]]:
        """`(before, table, after)`. The table is the FIRST contiguous run of `|` lines.

        Splitting this way is what makes the rest of the document untouchable: rows are parsed only
        from the middle third, and the two outer thirds are carried across a rewrite verbatim.
        Trailing blank lines are trimmed from `before` so `_render`'s single blank line before the
        header is idempotent -- otherwise every write would add one.
        """
        lines = text.splitlines()
        first = next((i for i, line in enumerate(lines) if _QUEUE_ROW.match(line)), None)
        if first is None:
            before = list(lines)
            while before and not before[-1].strip():
                before.pop()
            return before, [], []
        last = first
        while last + 1 < len(lines) and _QUEUE_ROW.match(lines[last + 1]):
            last += 1
        before = lines[:first]
        while before and not before[-1].strip():
            before.pop()
        return before, lines[first : last + 1], lines[last + 1 :]

    @classmethod
    def _parse(cls, text: str) -> RowList:
        """Every queue row, in file order, as {title, path, notes}. Order IS priority."""
        rows: RowList = []
        for line in cls._split(text)[1]:
            match = _QUEUE_ROW.match(line)
            if not match:
                continue
            # Split on UNESCAPED pipes only. `|` is the table delimiter, so a title containing one
            # is written `\|`; splitting on every pipe cut such a row in half, the link no longer
            # parsed, and the next write dropped the row entirely -- a queue item lost with no
            # error. Found by round-tripping a title with a pipe in it, which is why the guard in
            # `_prepare` now runs on every write rather than trusting this pair to agree.
            cells = [cell.strip() for cell in _CELL_SPLIT.split(match.group("cells"))]
            if len(cells) < 2 or set("".join(cells)) <= set("-: "):
                continue  # the header separator, or a row with nothing in it
            # STRUCTURE FIRST, then unescape. Unescaping the whole cell before matching the link
            # turns `\[item\]` back into `[item]` and the link no longer parses -- the same
            # row-dropping defect one layer up. Escapes are removed only from the extracted words.
            link = _QUEUE_LINK.search(cells[1])
            if not link:
                continue  # the header row, or a note someone wrote by hand
            rows.append(
                {
                    "title": _unescape(link.group("title").strip()),
                    "path": link.group("path").strip(),
                    "notes": _unescape(cells[2].strip()) if len(cells) > 2 else "",
                }
            )
        return rows

    def _text(self) -> str:
        return self.queue.read_text(encoding="utf-8") if self.queue.is_file() else ""

    def _rows(self) -> RowList:
        return self._parse(self._text())

    def _render(self, rows: Sequence[dict], original: str) -> str:
        """The whole document, with only the table block rewritten and renumbered from 1.

        Renumbering on every write is what keeps "top of the list is next" true: a stale `#` column
        after a `done` would make the file say something the queue no longer means.
        """
        if original.strip():
            before, _table, after = self._split(original)
        else:
            before, after = ["# Backlog Queue", "", "Top of the list = next to build."], []
        table = list(QUEUE_HEADER)
        for index, row in enumerate(rows, start=1):
            title, notes = _escape(str(row["title"])), _escape(str(row["notes"]))
            table.append(f"| {index} | [{title}]({row['path']}) | {notes} |")
        return "\n".join([*before, "", *table, *after]) + "\n"

    def _prepare(self, rows: Sequence[dict]) -> str:
        """Render the file and PROVE it round-trips. Returns the text; touches nothing on disk.

        Separated from the write so a caller can validate BEFORE it moves a file. The check is not
        paranoia about a hypothetical: a title containing the table's own delimiter rendered a row
        this module's parser could not read back, and the next write dropped it -- the queue lost an
        item and reported success. Escaping is fixed; this asserts the fix on every write, on all
        three cells and on the document around the table, because the failure mode is invisible at
        the moment it happens and only surfaces as an item nobody can find.
        """
        original = self._text()
        text = self._render(rows, original)
        expected = [(str(r["title"]), str(r["path"]), str(r["notes"])) for r in rows]
        actual = [(r["title"], r["path"], r["notes"]) for r in self._parse(text)]
        if actual != expected:
            raise BacklogError(
                f"Refusing to write {self.queue_path}: the rendered table does not read back as "
                f"the {len(expected)} row(s) it was given ({len(actual)} survived). Nothing has "
                "been written and no file has been moved. This is a defect in the queue-file "
                "writer; please report the item title that triggered it."
            )
        if original.strip():
            before, _t, after = self._split(original)
            new_before, _nt, new_after = self._split(text)
            if (new_before, new_after) != (before, after):
                raise BacklogError(
                    f"Refusing to write {self.queue_path}: prose outside the queue table would be "
                    "changed or lost by this write. Nothing has been written and no file has been "
                    "moved. This is a defect in the queue-file writer; please report it."
                )
        return text

    def _commit(self, text: str) -> None:
        """Replace the queue file ATOMICALLY.

        `write_text` truncates in place, so an interrupted write leaves a half-written queue --
        the one file that says what the whole project is doing next. A temp file plus `os.replace`
        makes a reader see either the old document or the new one, never a torn one.
        """
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.queue.with_name(f".{self.queue.name}.tautline-tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.queue)

    def _state_of(self, row_path: str) -> str:
        parts = Path(row_path).parts
        for state, dirname in LOCAL_DIRS.items():
            if dirname in parts:
                return state
        return READY

    def _item(self, row: dict) -> Item:
        path = self.base / row["path"]
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
        return Item(
            id=Path(row["path"]).stem,
            title=row["title"] or Path(row["path"]).stem,
            body=body,
            state=self._state_of(row["path"]),
        )

    def _find(self, rows: Sequence[dict], item_id: str) -> int:
        for index, row in enumerate(rows):
            if Path(row["path"]).stem == item_id:
                return index
        known = ", ".join(Path(row["path"]).stem for row in rows) or "(the queue is empty)"
        raise BacklogError(
            f"No item {_safe(item_id, MAX_ID_CHARS)!r} in {self.queue_path}. Known ids: "
            f"{_safe(known, 300)}. Run `tautline backlog list` to see the queue."
        )

    # --- the four verbs -----------------------------------------------------------------------

    def list(self) -> Sequence[Item]:
        return [item for item in (self._item(row) for row in self._rows()) if item.state != DONE]

    def add(self, title: str, body: str = "") -> Item:
        title = " ".join(title.split())
        if not title:
            raise BacklogError('An item needs a title: `tautline backlog add "<title>"`.')
        rows = self._rows()
        taken = {Path(row["path"]).stem for row in rows}
        stem = f"{date.today().isoformat()}-{slugify(title)}"
        slug, suffix = stem, 2
        while slug in taken or (self.base / LOCAL_DIRS[READY] / f"{slug}.md").exists():
            slug, suffix = f"{stem}-{suffix}", suffix + 1
        relative = f"{LOCAL_DIRS[READY]}/{slug}.md"
        # Stored UNESCAPED. Escaping is the writer's job and unescaping is the parser's, so the
        # title is the user's words everywhere in memory and the two halves cannot drift.
        rows.append({"title": title, "path": relative, "notes": ""})
        # VALIDATED BEFORE ANYTHING IS CREATED, so a refusal leaves no orphan spec file behind.
        text = self._prepare(rows)
        spec = self.base / relative
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(
            f"# {title}\n\n{body.strip()}\n" if body.strip() else f"# {title}\n", encoding="utf-8"
        )
        try:
            self._commit(text)
        except OSError:
            spec.unlink(missing_ok=True)
            raise
        return Item(id=slug, title=title, body=body, state=READY)

    def _move(self, item_id: str | None, to_state: str) -> Item:
        rows = self._rows()
        if item_id is None:
            item_id = self._top().id
        index = self._find(rows, item_id)
        row = rows[index]
        source = self.base / row["path"]
        current = self._state_of(row["path"])
        if current == to_state:
            raise BacklogError(f"{_safe(item_id, MAX_ID_CHARS)} is already {to_state} in "
                               f"{self.queue_path}.")
        destination = self.base / LOCAL_DIRS[to_state] / f"{item_id}.md"
        if not source.is_file():
            # Silently rewriting the row would report a move that did not happen -- a control
            # claiming success for work it never did.
            raise BacklogError(
                f"{self.queue_path} lists {_safe(item_id, MAX_ID_CHARS)} at "
                f"{_safe(row['path'], 200)}, but that file does not exist. Restore it or remove "
                "the row, then run this again."
            )
        rows[index] = dict(row, path=f"{LOCAL_DIRS[to_state]}/{item_id}.md")
        # RENDER AND VALIDATE FIRST, MOVE SECOND. The other order let a guard refusal print "the
        # file is unchanged" after the spec file had already moved -- a refusal that lied about the
        # state it left behind, which is worse than the write it prevented.
        text = self._prepare(rows)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        try:
            self._commit(text)
        except OSError:
            # Put the file back rather than leave the table and the filesystem disagreeing.
            shutil.move(str(destination), str(source))
            raise
        if not destination.is_file():
            raise BacklogError(
                f"{item_id} was recorded as {to_state} but {destination} is not there. The queue "
                "file and the filesystem disagree; check both before continuing."
            )
        return Item(
            id=item_id,
            title=row["title"],
            body=destination.read_text(encoding="utf-8"),
            state=to_state,
        )

    def take(self, item_id: str | None = None) -> Item:
        return self._move(item_id, IN_PROGRESS)

    def done(self, item_id: str) -> Item:
        return self._move(item_id, DONE)


# --------------------------------------------------------------------------------------------
# github: issues under one label, plain REST
# --------------------------------------------------------------------------------------------


def _gh_auth_token() -> str:
    """The token `gh` holds, or "". A seam a test can replace without touching the environment."""
    if shutil.which("gh") is None:
        return ""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _redact(text: str, token: Secret) -> str:
    value = token.reveal()
    return text.replace(value, "<redacted>") if value else text


class GitHubBacklog(BacklogProvider):
    """Open issues carrying one label, oldest first.

    PLAIN REST, never the Projects GraphQL API. That is a measured rule, not a preference: on
    2026-08-16 `gh project item-list` cost 102 GraphQL points per call against a 5,000-point hourly
    budget, where the equivalent REST reads cost 1. A backlog an agent reads several times an hour
    must not be able to exhaust an adopter's quota.
    """

    name = "github"

    def __init__(
        self,
        *,
        repo: str,
        label: str = DEFAULT_GITHUB_LABEL,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self.repo = repo
        self.label = label
        self.timeout = timeout

    def describe(self) -> str:
        return f"github ({self.repo})"

    def stamp_id(self, item: Item) -> str:
        """`#<issue>` -- the form GitHub's own closing keywords use, so `Backlog: #<issue>` reads
        exactly like `Closes #<issue>` and is a form the check's grammar also matches."""
        return f"#{_safe(item.id, MAX_ID_CHARS)}"

    # --- transport ----------------------------------------------------------------------------

    def _token(self) -> Secret:
        for env in GITHUB_TOKEN_ENVS:
            # Through the resolver, the framework's single env-read chokepoint; reading the process
            # environment directly here would be the bypass its guard exists to catch.
            value = resolve_env(env).strip()
            if value:
                return Secret(value)
        return Secret(_gh_auth_token())

    @staticmethod
    def _assert_github_origin(url: str) -> None:
        """Refuse to attach a bearer token to anything but api.github.com.

        Applied to every request INCLUDING the `Link` header's next page, which is a URL chosen by
        the response rather than by this code. Following it without this check would let one
        compromised or spoofed response redirect the credential anywhere.
        """
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != GITHUB_HOST:
            raise BacklogError(
                f"Refusing to send a GitHub token to {_safe(url, 120)!r}: this client talks only "
                f"to https://{GITHUB_HOST}."
            )

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        """The opener actually used, exposed so a test can prove the redirect refusal is INSTALLED.

        Built here rather than inline because a test that constructs `_RefuseRedirect` directly
        proves only that the class refuses -- not that anything wires it in. That is the gap that
        lets a guard pass while the behaviour it guards is unreachable.
        """
        return urllib.request.build_opener(_RefuseRedirect())

    def _request(
        self, method: str, url_or_path: str, payload: object | None = None
    ) -> tuple[object, dict]:
        """One request. Returns `(parsed body, lower-cased response headers)`.

        Headers come back because GitHub signals pagination ONLY in the `Link` header -- the body
        of a list endpoint is a bare array with no cursor, no total and no next field in it.
        """
        token = self._token()
        if not token:
            raise BacklogError(
                "GitHub credentials: no token available. Export "
                f"{' or '.join(GITHUB_TOKEN_ENVS)} with a token that can read and write issues in "
                f"{self.repo}, or run `gh auth login` so the CLI can supply one. The token is read "
                "from the environment and never from the project's config, which is committed to a "
                "repository."
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
        except BacklogError:
            raise
        except urllib.error.HTTPError as exc:
            raise self._typed_error(exc, url_or_path, token) from None
        except (urllib.error.URLError, OSError) as exc:
            raise BacklogError(
                _redact(f"GitHub request to {url_or_path} did not complete: {exc}", token)
            ) from None
        if not body.strip():
            return None, headers
        try:
            return json.loads(body), headers
        except ValueError:
            raise BacklogError(f"GitHub returned a non-JSON body for {url_or_path}.") from None

    def _http(self, method: str, url_or_path: str, payload: object | None = None) -> object:
        return self._request(method, url_or_path, payload)[0]

    @staticmethod
    def _error_detail(exc: urllib.error.HTTPError) -> str:
        """GitHub's error body: `message`, plus the per-field `errors` array when there is one.

        "GitHub returned HTTP 422" is not a diagnosis. The server described the fault precisely and
        discarding that description makes the caller guess at something already known.
        """
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        parts = [str(payload.get("message") or "").strip()]
        for entry in payload.get("errors") or []:
            if isinstance(entry, dict):
                field = str(entry.get("field") or entry.get("resource") or "").strip()
                code = str(entry.get("code") or entry.get("message") or "").strip()
                parts.append(f"{field}: {code}".strip(": "))
            else:
                parts.append(str(entry))
        return " ".join(part for part in parts if part)[:400]

    def _typed_error(self, exc: urllib.error.HTTPError, path: str, token: Secret) -> BacklogError:
        detail = self._error_detail(exc)
        suffix = f" GitHub said: {_safe(detail, 400)}" if detail else ""
        if exc.code in (401, 403):
            return BacklogError(
                _redact(
                    f"GitHub rejected the credentials for {path} (HTTP {exc.code}). Check "
                    f"{' / '.join(GITHUB_TOKEN_ENVS)} (or `gh auth login`) and that the token can "
                    f"read and write issues in {self.repo}.{suffix}",
                    token,
                )
            )
        if exc.code == 404:
            return BacklogError(
                _redact(
                    f"GitHub has nothing at {path} (HTTP 404). Check backlog.repo -- it is "
                    f"{self.repo!r} -- and that the token can see a private repository.{suffix}",
                    token,
                )
            )
        return BacklogError(_redact(f"GitHub returned HTTP {exc.code} for {path}.{suffix}", token))

    def _paged(self, path: str) -> list:
        """Every page of a list endpoint, following the `Link` header to the end.

        GitHub signals "there is more" ONLY here: the body is a bare array, so a single-request
        implementation silently returns the first page and every count taken from it is wrong. The
        loop is bounded, and the next URL is origin-checked like any other.
        """
        items: list = []
        url: str | None = path
        for _ in range(MAX_PAGES):
            if url is None:
                return items
            payload, headers = self._request("GET", url)
            if not isinstance(payload, list):
                raise BacklogError(
                    f"GitHub {url_path(url)} returned unexpected JSON; expected a list."
                )
            items.extend(payload)
            match = _LINK_NEXT.search(headers.get("link", ""))
            url = match.group(1) if match else None
        raise BacklogError(
            f"GitHub kept offering another page of {url_path(path)} after {MAX_PAGES} requests. "
            "Refusing to keep paging; narrow the backlog label or report this."
        )

    # --- the four verbs -----------------------------------------------------------------------

    @staticmethod
    def _labels(payload: dict) -> set[str]:
        return {
            str(entry.get("name") or "") if isinstance(entry, dict) else str(entry)
            for entry in (payload.get("labels") or [])
        }

    def _issue(self, payload: dict) -> Item:
        labels = self._labels(payload)
        if str(payload.get("state") or "") == "closed":
            state = DONE
        elif GITHUB_IN_PROGRESS_LABEL in labels:
            state = IN_PROGRESS
        else:
            state = READY
        return Item(
            id=str(payload.get("number") or ""),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            state=state,
            url=str(payload.get("html_url") or ""),
        )

    def list(self) -> Sequence[Item]:
        query = urllib.parse.urlencode(
            {
                "labels": self.label,
                "state": "open",
                "sort": "created",
                "direction": "asc",
                "per_page": str(GITHUB_PAGE_SIZE),
            }
        )
        payload = self._paged(f"/repos/{_seg(self.repo)}/issues?{query}")
        # Pull requests come back from the issues endpoint too. An open PR is not a backlog item,
        # and listing one would put work in the queue that `take` cannot move.
        return [
            self._issue(entry)
            for entry in payload
            if isinstance(entry, dict) and "pull_request" not in entry
        ]

    def add(self, title: str, body: str = "") -> Item:
        title = " ".join(title.split())
        if not title:
            raise BacklogError('An item needs a title: `tautline backlog add "<title>"`.')
        payload = self._http(
            "POST",
            f"/repos/{_seg(self.repo)}/issues",
            {"title": title, "body": body, "labels": [self.label]},
        )
        if not isinstance(payload, dict):
            raise BacklogError("GitHub did not return the created issue.")
        item = self._issue(payload)
        if self.label not in self._labels(payload):
            # A 201 IS NOT SUCCESS HERE. GitHub silently drops `labels` when the token cannot push
            # to the repository, and the label is what `list` filters on -- so reporting success
            # would hand back an id and a URL for an item the queue will never show again.
            raise BacklogError(
                f"GitHub created issue {item.reference()} but WITHOUT the {self.label!r} label, "
                "which is silently dropped when the token lacks write access to the repository's "
                f"issues. The item exists but `tautline backlog list` will not show it. Add the "
                f"{self.label!r} label to that issue by hand, and give the token issues:write (or "
                "push access) before filing another."
            )
        return item

    def _number(self, item_id: str) -> str:
        number = _safe(item_id, MAX_ID_CHARS).strip().lstrip("#")
        if not number.isdigit():
            raise BacklogError(
                f"{_safe(item_id, MAX_ID_CHARS)!r} is not a GitHub issue number. Run "
                "`tautline backlog list` and use the id in the first column."
            )
        return number

    def _viewer_login(self) -> str:
        """The authenticated user's login, or "" -- BEST EFFORT and deliberately so.

        `GET /user` is not available to a GitHub Actions installation token: it answers 403
        "Resource not accessible by integration". Treating that as fatal made `take` fail in CI
        AFTER the label had been written, leaving the issue half-taken. The assignee is a courtesy;
        the label is the state carrier.
        """
        try:
            viewer = self._http("GET", "/user")
        except BacklogError as exc:
            self.notices.append(
                f"assignee not resolved ({_safe(str(exc), 300)}); the in-progress label is set and "
                "is what the queue reads"
            )
            return ""
        return str(viewer.get("login") or "") if isinstance(viewer, dict) else ""

    def _verified(self, number: str, expected: str) -> Item:
        """Read the issue back and confirm the state actually changed. 2xx is not evidence."""
        payload = self._http("GET", f"/repos/{_seg(self.repo)}/issues/{number}")
        if not isinstance(payload, dict):
            raise BacklogError(f"GitHub did not return issue {number} after the write.")
        item = self._issue(payload)
        if item.state != expected:
            raise BacklogError(
                f"GitHub accepted the change to issue {number} but reading it back shows "
                f"{item.state!r}, not {expected!r}. The board did not end up where this command "
                "said it would; check the issue before relying on the queue."
            )
        return item

    def take(self, item_id: str | None = None) -> Item:
        number = self._number(item_id if item_id is not None else self._top().id)
        # THE READ COMES FIRST. Every hard failure that can happen here happens before anything is
        # mutated, so a failed `take` cannot leave the issue labelled but unassigned.
        login = self._viewer_login()
        self._http(
            "POST",
            f"/repos/{_seg(self.repo)}/issues/{number}/labels",
            {"labels": [GITHUB_IN_PROGRESS_LABEL]},
        )
        if login:
            try:
                self._http("PATCH", f"/repos/{_seg(self.repo)}/issues/{number}", {"assignees": [login]})
            except BacklogError as exc:
                self.notices.append(
                    f"assignee not set on #{number} ({_safe(str(exc), 300)}); the in-progress "
                    "label is set and is what the queue reads"
                )
        return self._verified(number, IN_PROGRESS)

    def done(self, item_id: str) -> Item:
        number = self._number(item_id)
        self._http(
            "PATCH",
            f"/repos/{_seg(self.repo)}/issues/{number}",
            {"state": "closed", "state_reason": "completed"},
        )
        return self._verified(number, DONE)


def _seg(value: str) -> str:
    """A path segment, percent-encoded. `/` is preserved for `owner/name`, which is two segments."""
    return urllib.parse.quote(value, safe="/")


def url_path(url: str) -> str:
    """The path of a URL, for an error message that should not echo a query string with a token."""
    return urllib.parse.urlsplit(url).path or url


# --------------------------------------------------------------------------------------------
# jira: issues in one project, optionally filtered to one board
# --------------------------------------------------------------------------------------------


def _adf(body: str) -> dict:
    """Plain text as an Atlassian Document Format doc. The v3 API accepts nothing else."""
    paragraphs = [line for line in body.split("\n\n") if line.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": paragraph}]}
            for paragraph in paragraphs
        ],
    }


def _adf_text(node: object) -> str:
    """Every `text` leaf of an ADF document, in order. Enough to render a body in a terminal."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text") or "")
        return "".join(_adf_text(child) for child in (node.get("content") or []))
    if isinstance(node, list):
        return "".join(_adf_text(child) for child in node)
    return ""


class JiraBacklog(BacklogProvider):
    """Issues in one Jira Cloud project, optionally filtered to one board.

    The client, its auth model and the identity grammar were SALVAGED from the pre-demolition
    history (0.139.0-0.143.0 plus the unmerged 0.144.0 read verbs) and re-seated here. The
    board-sync shape they were welded to was discarded; see `jira_client`'s docstring.

    THE TWO ENDPOINTS PAGINATE DIFFERENTLY and are not interchangeable. `/rest/api/3/search/jql` is
    TOKEN-paginated -- `{isLast, issues, nextPageToken}`, no total, and `startAt` is not a parameter
    it accepts, so an offset pager against it re-reads page one forever while every response says
    200. `/rest/agile/1.0/board/{id}/issue` is offset-paginated and echoes the `maxResults` it
    actually granted, which may be smaller than the one requested; stepping by the REQUESTED value
    skips issues.
    """

    name = "jira"

    def __init__(
        self,
        *,
        site: str,
        project: str,
        board: str = "",
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self.site = site.rstrip("/")
        self.project = project
        self.board = board
        self.timeout = timeout
        self.client = jira_client.JiraClient(site_url=self.site, timeout=timeout)
        self._issue_type: dict | None = None

    def describe(self) -> str:
        return f"jira ({self.project}{'/board ' + self.board if self.board else ''})"

    def _call(self, verb, *args, **kwargs) -> object:
        try:
            return verb(*args, **kwargs)
        except jira_client.JiraError as exc:
            # Re-typed, never swallowed and never replaced with a local read. The message keeps the
            # env-var names the client's own auth check put in it.
            raise BacklogError(str(exc)) from None

    def _item(self, payload: dict) -> Item:
        fields = payload.get("fields")
        fields = fields if isinstance(fields, dict) else {}
        status = fields.get("status")
        category = (status or {}).get("statusCategory") if isinstance(status, dict) else None
        key_name = (category or {}).get("key") if isinstance(category, dict) else None
        state = {"done": DONE, "indeterminate": IN_PROGRESS}.get(str(key_name or "new"), READY)
        key = str(payload.get("key") or "")
        return Item(
            id=key,
            title=str(fields.get("summary") or ""),
            body=_adf_text(fields.get("description")),
            state=state,
            url=f"{self.site}/browse/{_seg(key)}" if key else "",
        )

    def _jql(self) -> str:
        # `Rank` is a Jira Software field and exists exactly when a board does, so the ordering
        # follows the board's presence rather than being asserted and failing on a project that has
        # no agile board.
        order = "Rank ASC" if self.board else "created ASC"
        return f'project = "{self.project}" AND statusCategory != Done ORDER BY {order}'

    def _paged_token(self, path: str, params: dict) -> list:
        """`/search/jql`: follow `nextPageToken` until `isLast`. No `startAt`, no `total`."""
        issues: list = []
        token = ""
        for _ in range(MAX_PAGES):
            page = dict(params)
            if token:
                page["nextPageToken"] = token
            payload = self._call(self.client.get, path, page)
            if not isinstance(payload, dict):
                raise BacklogError(f"Jira {path} returned unexpected JSON; expected an object.")
            batch = payload.get("issues")
            if not isinstance(batch, list):
                raise BacklogError(f"Jira {path} returned unexpected JSON; expected 'issues'.")
            issues.extend(batch)
            if payload.get("isLast"):
                return issues
            nxt = str(payload.get("nextPageToken") or "")
            if not nxt:
                return issues
            if nxt == token:
                # A repeated cursor cannot terminate. Truncating silently would under-report the
                # queue; saying so is the only honest answer.
                raise BacklogError(
                    f"Jira {path} returned the same page cursor twice, so paging cannot finish. "
                    f"Reporting {len(issues)} issue(s) would under-count the backlog."
                )
            token = nxt
        raise BacklogError(
            f"Jira {path} kept offering another page after {MAX_PAGES} requests. Refusing to keep "
            "paging; narrow the project or board, or report this."
        )

    def _paged_offset(self, path: str, params: dict, key: str, *, schema: bool = False) -> list:
        """Offset paging that steps by the maxResults the RESPONSE granted, not the one requested.

        Atlassian's own wording is "you can ask for more than you are given". Advancing `startAt` by
        the requested size after being handed a smaller page steps straight over the issues in
        between, and every one of them silently vanishes from the queue.
        """
        items: list = []
        start = 0
        for _ in range(MAX_PAGES):
            page = dict(params, startAt=str(start))
            payload = self._call(self.client.get, path, page, schema=schema)
            if not isinstance(payload, dict):
                raise BacklogError(f"Jira {path} returned unexpected JSON; expected an object.")
            batch = payload.get(key)
            if not isinstance(batch, list):
                raise BacklogError(f"Jira {path} returned unexpected JSON; expected {key!r}.")
            items.extend(batch)
            granted = payload.get("maxResults")
            step = granted if isinstance(granted, int) and granted > 0 else len(batch)
            if step <= 0:
                return items
            start += step
            total = payload.get("total")
            if isinstance(total, int) and start >= total:
                return items
            if len(batch) < step:
                return items
        raise BacklogError(
            f"Jira {path} kept offering another page after {MAX_PAGES} requests. Refusing to keep "
            "paging; narrow the project or board, or report this."
        )

    def list(self) -> Sequence[Item]:
        params = {
            "jql": self._jql(),
            "maxResults": str(JIRA_PAGE_SIZE),
            "fields": "summary,description,status",
        }
        if self.board:
            issues = self._paged_offset(
                f"/rest/agile/1.0/board/{_seg(self.board)}/issue", params, "issues"
            )
        else:
            # `/rest/api/3/search` was retired on Jira Cloud in favour of `/search/jql`.
            issues = self._paged_token("/rest/api/3/search/jql", params)
        return [self._item(entry) for entry in issues if isinstance(entry, dict)]

    def _issue_type_id(self) -> str:
        """The project's own issue-type id, resolved once and cached.

        `{"name": "Task"}` is not a documented v3 create shape and names are not unique across
        issue-type schemes, so it is a guess that fails as an opaque 400 on any project whose scheme
        differs. Reading the project's actual types replaces the guess with the id the API asks for.
        """
        if self._issue_type is None:
            types = self._paged_offset(
                f"/rest/api/3/issue/createmeta/{_seg(self.project)}/issuetypes",
                {"maxResults": "100"},
                "issueTypes",
                # Effectively static; the long TTL is the same trade the field schema gets.
                schema=True,
            )
            usable = [
                entry
                for entry in types
                if isinstance(entry, dict) and not entry.get("subtask")
                and str(entry.get("id") or "").strip()
            ]
            chosen = next(
                (e for e in usable if str(e.get("name") or "").strip().lower() == "task"), None
            ) or (usable[0] if usable else None)
            if chosen is None:
                raise BacklogError(
                    f"Jira project {self.project} offers no non-subtask issue type this command can "
                    "create. Check the project's issue-type scheme, and that the account can create "
                    "issues in it."
                )
            self._issue_type = chosen
        return str(self._issue_type.get("id") or "")

    def add(self, title: str, body: str = "") -> Item:
        title = " ".join(title.split())
        if not title:
            raise BacklogError('An item needs a title: `tautline backlog add "<title>"`.')
        fields: dict = {
            "project": {"key": self.project},
            "summary": title,
            "issuetype": {"id": self._issue_type_id()},
        }
        if body.strip():
            fields["description"] = _adf(body)
        payload = self._call(self.client.post, "/rest/api/3/issue", {"fields": fields})
        key = str(payload.get("key") or "") if isinstance(payload, dict) else ""
        if not key:
            raise BacklogError("Jira did not return a key for the created issue.")
        return Item(
            id=key, title=title, body=body, state=READY, url=f"{self.site}/browse/{_seg(key)}"
        )

    @staticmethod
    def _describe_transition(entry: dict) -> str:
        scope = "global" if entry.get("isGlobal") else "status-specific"
        to = entry.get("to")
        target = str((to or {}).get("name") or "") if isinstance(to, dict) else ""
        tail = f" -> {_safe(target, 40)}" if target else ""
        return f"id {_safe(entry.get('id'), 20)} {_safe(entry.get('name'), 60)!r} ({scope}){tail}"

    def _transition(self, key: str, wanted: str) -> None:
        """Resolve a transition to exactly ONE id, or refuse listing every candidate.

        A transition NAME is not unique. A workflow commonly carries both a global `Done` and a
        status-specific `Done`, and first-match-wins fires whichever the API happened to list first
        -- moving the issue somewhere nobody asked for, silently, while reporting success. Selection
        is by id; resolving a name to anything other than one id is an error, not a coin toss.
        """
        payload = self._call(self.client.get, f"/rest/api/3/issue/{_seg(key)}/transitions")
        available = payload.get("transitions") if isinstance(payload, dict) else None
        if not isinstance(available, list):
            raise BacklogError(
                f"Jira /rest/api/3/issue/{key}/transitions returned unexpected JSON; expected a "
                "'transitions' list."
            )
        entries = [entry for entry in available if isinstance(entry, dict)]
        matches = [
            entry
            for entry in entries
            if str(entry.get("name") or "").strip().lower() == wanted.lower()
            and str(entry.get("id") or "").strip()
        ]
        offered = "; ".join(self._describe_transition(entry) for entry in entries) or "(none)"
        if len(matches) > 1:
            raise BacklogError(
                f"Jira issue {key} offers {len(matches)} transitions named {wanted!r}, so the name "
                "does not select one and this command will not guess which to fire. Candidates: "
                f"{offered}. Rename one in the workflow so {wanted!r} is unambiguous, or move the "
                "issue in Jira."
            )
        if not matches:
            raise BacklogError(
                f"Jira issue {key} has no {wanted!r} transition from its current status. Available "
                f"transitions: {offered}. Rename the workflow transition to {wanted!r}, or move the "
                "issue in Jira."
            )
        self._call(
            self.client.post,
            f"/rest/api/3/issue/{_seg(key)}/transitions",
            {"transition": {"id": str(matches[0].get("id"))}},
        )

    def _key(self, item_id: str) -> str:
        key = _safe(item_id, MAX_ID_CHARS).strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]+-[0-9]+", key):
            raise BacklogError(
                f"{_safe(item_id, MAX_ID_CHARS)!r} is not a Jira issue key (like "
                f"{self.project}-123). Run `tautline backlog list` and use the id in the first "
                "column."
            )
        return key

    def _verified(self, key: str, expected: str) -> Item:
        """Read the issue back and confirm the transition landed where it was supposed to."""
        payload = self._call(
            self.client.get,
            f"/rest/api/3/issue/{_seg(key)}",
            {"fields": "summary,description,status"},
        )
        if not isinstance(payload, dict):
            raise BacklogError(f"Jira did not return issue {key}.")
        item = self._item(payload)
        if item.state != expected:
            raise BacklogError(
                f"Jira accepted the transition on {key} but reading it back shows {item.state!r}, "
                f"not {expected!r} -- the workflow moved it to a status in a different category. "
                "Check the issue and the workflow before relying on the queue."
            )
        return item

    def take(self, item_id: str | None = None) -> Item:
        key = self._key(item_id if item_id is not None else self._top().id)
        self._transition(key, JIRA_IN_PROGRESS_TRANSITION)
        return self._verified(key, IN_PROGRESS)

    def done(self, item_id: str) -> Item:
        key = self._key(item_id)
        self._transition(key, JIRA_DONE_TRANSITION)
        return self._verified(key, DONE)


# --------------------------------------------------------------------------------------------
# the advisory line lane-status prints
# --------------------------------------------------------------------------------------------


def advisory_line(root: Path, cfg: dict | None) -> str | None:
    """One line for `lane-status`, or None when the config names no backlog.

    A LIVE read, bounded by `ADVISORY_TIMEOUT_SECONDS`, and every failure is REPORTED rather than
    hidden: `backlog: <provider> unreachable (<reason>)`. It never prints a count it did not
    measure and never silently omits itself -- a control that reports a number it did not read is
    the defect class this framework has paid for most.
    """
    block = (cfg or {}).get("backlog")
    if not isinstance(block, dict):
        return None
    described = describe_config(block)
    try:
        provider = provider_for(root, cfg, timeout=ADVISORY_TIMEOUT_SECONDS)
        items = list(provider.list())
    except BacklogError as exc:
        return f"backlog: {described} unreachable ({_safe(str(exc))})"
    except Exception as exc:  # advisory surface: ANY failure becomes an honest line, never a hang
        return f"backlog: {described} unreachable ({_safe(f'{type(exc).__name__}: {exc}')})"
    top = next((item.title for item in items if item.state == READY), "")
    suffix = f", top: {_safe(top, limit=60)}" if top else ""
    return f"backlog: {described} - {len(items)} open{suffix}"


# --------------------------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------------------------

NO_CONFIG = (
    "No Tautline config here, so there is no backlog to read. Run `tautline init` to create one "
    "(it asks where your backlog lives), or `tautline slim` to migrate a project that already has "
    "a 1.x adapter."
)


def _table(items: Sequence[Item]) -> list[str]:
    if not items:
        return ["(the queue is empty)"]
    rows = [(_safe(item.id, MAX_ID_CHARS), item.state, _safe(item.title, 88)) for item in items]
    width = max(len(ident) for ident, _state, _title in rows)
    return [f"{ident:<{width}}  {state:<11}  {title}" for ident, state, title in rows]


def backlog_command(args: argparse.Namespace) -> int:
    """`tautline backlog list|add|take|done`. The ONLY thing that moves this queue."""
    root = Path(getattr(args, "target", Path("."))).resolve()
    adapter = lean.find_lean_adapter(root)
    if adapter is None:
        print(NO_CONFIG)
        return 1
    cfg = lean.load_lean_config(adapter)
    action = args.action
    argument = getattr(args, "item", None)
    provider = None
    try:
        provider = provider_for(root, cfg)
        if action == "list":
            for line in _table(list(provider.list())):
                print(line)
            return 0
        if action == "add":
            if not argument:
                raise BacklogError(
                    'Give the item a title: `tautline backlog add "<title>"` '
                    "(use --body for the one-page spec)."
                )
            item = provider.add(argument, getattr(args, "body", "") or "")
        elif action == "take":
            from tautline_methodology import work

            for line in work.advisory_lines(root, cfg):
                print(line, file=sys.stderr)
            item = provider.take(argument)
        else:
            if not argument:
                raise BacklogError(
                    "Say which item is done: `tautline backlog done <id>` "
                    "(`tautline backlog list` shows the ids)."
                )
            item = provider.done(argument)
    except BacklogError as exc:
        _print_notices(provider)
        print(f"backlog_error: {_safe_message(exc)}")
        return 1
    except Exception as exc:  # a CLI never answers with a traceback
        _print_notices(provider)
        print(
            f"backlog_error: the {action} command hit an unexpected "
            f"{type(exc).__name__}: {_safe(exc, 200)}. That is a bug in this command, not a "
            "problem with your board; please report it with the command you ran."
        )
        return 1
    _print_notices(provider)
    print(f"{action}: {item.reference()}  {_safe(item.title, 88)}")
    if action == "take":
        # Ready to paste, on its own line: the PR this work becomes should carry it verbatim, in
        # the title or the body, so the work is traceable back to the item it implements.
        print(f"Backlog: {provider.stamp_id(item)}")
        print(
            "Put that line in your PR's title or body -- it is how the PR is traced back to "
            "this item."
        )
    return 0


def _print_notices(provider) -> None:
    """Best-effort steps that were skipped. Silence would make a partial result look complete."""
    for notice in getattr(provider, "notices", []) or []:
        print(f"backlog_note: {_safe_message(notice)}")
