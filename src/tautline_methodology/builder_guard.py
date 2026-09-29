"""The builder-lane GitHub guard: `tautline board|issue|debt` is the ONLY route to issues and the
project board for a BUILD AGENT, and no route at all is taken away from a HUMAN.

WHY THIS EXISTS. A raw `gh api graphql ... updateProjectV2Field` once rebuilt a project's whole
Status option set and orphaned every card on the board. The board is a stakeholder surface: the
damage is not a bad row, it is a director opening the board and finding the work gone. The verbs
(`builder_github`) put a narrow, reviewed, attributed path in front of every board and issue write;
this module is what makes that path the only one an agent can take, instead of the one it is asked
politely to prefer.

WHO IT BINDS, AND WHO IT MUST NOT. `builder.builder_role_active()` is the ONE role predicate in the
framework, and its default is HUMAN. The product director working in the product repo and the
operator on their own machine must see zero new friction -- not a prompt, not a slower `gh`, not a
line of output. So `decide(..., builder=False)` is unconditionally `allowed`, before any parsing
happens, and the test file's load-bearing case is the human one: every command the builder case
denies must come back allowed for a human, including the graphql call from the incident above.

HOW IT DECIDES. An ALLOW-LIST over `gh` subcommands, never a deny-list. The guard this replaces was
a deny-list, and `gh project` -- a verb GitHub shipped after it was written -- walked straight
through. An unknown verb is therefore denied by default; the cost of that is a builder lane that
has to ask for a new verb, which is a conversation, whereas the cost of the other direction is an
orphaned board.

Several subcommands carry a SECOND rule, because the subcommand itself is too coarse. The
authority for each is the constant named beside it, and `tests/test_builder_guard.py` derives this
table from those constants so the prose cannot drift away from the code:

  | subcommand  | rule                                | why the whole verb is not enough          |
  |-------------|-------------------------------------|-------------------------------------------|
  | `gh api`    | GET, read endpoints only            | the universal escape hatch; graphql never |
  | `gh search` | ALLOWED_GH_SEARCH_TARGETS           | `gh search issues` reaches issues         |
  | `gh repo`   | ALLOWED_GH_REPO_ACTIONS             | `delete`/`edit`/`rename`/`archive` do not |
  |             |                                     | come back, and `edit` reaches branch      |
  |             |                                     | protection -- the control fencing the     |
  |             |                                     | App's Contents write permission           |
  | `gh workflow`| ALLOWED_GH_WORKFLOW_ACTIONS        | `run`/`enable`/`disable` change what CI   |
  |             |                                     | does; a lane only needs to look           |
  | `gh run`    | ALLOWED_GH_RUN_ACTIONS              | `delete` removes the logs a human was     |
  |             |                                     | about to read; `cancel`/`rerun` act on    |
  |             |                                     | CI somebody is waiting on                 |
  | `gh auth`   | ALLOWED_GH_AUTH_ACTIONS             | `token` prints the operator's credential, |
  |             |                                     | `refresh -s project` re-scopes it to      |
  |             |                                     | write the board, `logout` destroys it     |
  | `gh pr`     | every action, minus the flags in    | a pull request IS a board item, so        |
  |             | _GH_PR_DENIED_FLAGS                 | `--add-project` is a board write          |

`gh release` is in no list at all: builders do not cut releases.

WHERE IT RUNS. Two surfaces, one predicate:
  * `tautline builder-guard --hook` -- a Claude Code PreToolUse hook (matcher "Bash"). Exit 2 with
    the reason on stderr is the block, and the JSON deny object goes to stdout as well, so the
    decision lands whichever channel the harness reads. The shipped hook command CAPTURES both
    streams and replays them only after `builder-guard --help` has confirmed the 2 is a deny
    rather than an older CLI's argparse "invalid choice" -- otherwise a human on a CLI one release
    behind gets argparse noise on every Bash call.
  * `tautline builder-guard --argv` behind a generated `gh` shim (`--shim-dir`) -- the same
    decision for Codex and any other lane whose harness has no hook contract.

WHERE IT LOOKS. Not only at the top level. A denied command is found inside `bash -c '...'`, a
herestring (`bash <<< '...'`), `env -S '...'`, a `find ... -exec` command, a `printf`/`echo` LITERAL
piped into `sh`, a loop body, a command substitution, behind a leading redirection
(`2>/dev/null gh ...`) and behind `xargs`/`command`/`timeout`/`env`.

WHAT IT DOES NOT CLAIM. This is a guard rail, not a sandbox, and saying so is part of the control
paying its rent -- a control believed to be airtight is worse than one whose edges are written
down. Three edges, named precisely:

  * A command word that only exists at run time (`GH=gh; $GH issue create`) is not recognised as
    `gh` at the hook.
  * A non-`gh` HTTP client is denied ONLY when the command TEXT contains `api.github.com` or
    `github.com/graphql`. That is a string match, not an understanding of the program: a
    `python -c` that assembles the host from two variables is not caught.
  * A payload this module cannot see as literal text is not caught: `python gen.py | sh`, a script
    written to a file and then run, a here-DOC body (as opposed to a here-STRING). That shape is deliberate
evasion rather than habit, and the threat this guard is sized for is habit: an agent reaching for
`gh issue` because that is what it has always typed. Two things narrow the gap anyway -- the PATH
shim catches the resolved binary however the command word was spelled, and `builder_github`'s own
verbs are where a lane's attention is pointed. An agent determined to get out has easier routes
than this one (its own HTTP client, for a start), and chasing them here would cost humans
precision the guard has no budget to spend.

Import rule, inherited from `builder`: nothing here imports `cli` at module scope. The event-log
write and the report reader import it lazily, so `cli` can import this module for its registrar.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from tautline_methodology.builder import builder_role_active

# --------------------------------------------------------------------------------- the vocabulary

#: Named verbs, not a vague prohibition. An agent that is told "denied" and not told WHERE the door
#: is will try the next spelling; this sentence is the door.
REASON_PREFIX = (
    "Builder lanes reach issues and the board only through `tautline board|issue|debt` "
    "(see `tautline issue --help`). Denied: "
)
#: Hook reasons are fed back to a model verbatim; a reason that runs to a page buries its own point.
REASON_MAX_CHARS = 300
MATCHED_MAX_CHARS = 160
#: What the ledger keeps of the offending command. Bounded so one denial cannot fill the log.
EVENT_COMMAND_MAX_CHARS = 500

DENIAL_EVENT = "builder_guard_denied"
DENIAL_EVENT_NAME = "builder-guard.denied"
REPORT_LIMIT = 20

#: The `gh` subcommands a builder lane may reach: pull requests, CI, auth and READS of the repo.
#: `issue`, `project`, `label`, `milestone`, `gist` and everything unknown are denied by omission.
#:
#: `release` was here and is gone: builders never cut releases. Cutting one is a stakeholder-facing
#: act with its own verb (`tautline cut-release`) and its own human, and `gh release create` on a
#: builder lane is either a mistake or an escape hatch around that -- neither of which is worth the
#: subcommand. `gh release delete` in the same allow-list would have let a lane remove a published
#: artifact, which is the `updateProjectV2Field` defect with a wider blast radius.
ALLOWED_GH_SUBCOMMANDS = frozenset({"pr", "run", "workflow", "auth", "repo", "status", "search"})
#: `gh search issues` reaches issues; `gh search prs` does not.
ALLOWED_GH_SEARCH_TARGETS = frozenset({"prs"})
#: `gh repo` is a subcommand with a destructive half. A lane needs to LOOK at the repository and to
#: get a copy of it; it never needs to delete, rename, archive, transfer, sync or re-settings one.
#: `gh repo delete o/r --yes` is not recoverable by the operator who notices it, and `gh repo edit`
#: reaches branch protection -- the control that the residual Contents write permission is fenced
#: by (see docs/builder-lanes.md), so a lane able to edit it could unfence itself.
ALLOWED_GH_REPO_ACTIONS = frozenset({"view", "clone"})
#: `gh workflow run|enable|disable` changes what CI does; a lane only ever needs to look.
ALLOWED_GH_WORKFLOW_ACTIONS = frozenset({"view", "list"})
#: `gh auth` was allow-listed whole, and the whole verb is three separate liberties. `gh auth
#: token` PRINTS the operator's credential to stdout, from where it reaches a log or a comment.
#: `gh auth refresh -s project` RE-SCOPES that credential to write the project board -- and the
#: App's Projects-read permission is not in that path at all, because `gh` authenticates as a
#: person, so this is the board write the App was supposed to make impossible. `gh auth logout`
#: destroys a login on the operator's own machine. `status` is the only one a lane needs.
ALLOWED_GH_AUTH_ACTIONS = frozenset({"status"})
#: `gh run` is how a lane reads its own CI, and three of its actions are not reads. `gh run delete`
#: removes a run and its logs -- the evidence a human was about to look at, and the one kind of
#: deletion nobody notices until they go looking. `cancel` stops a run somebody is waiting on;
#: `rerun` spends CI a lane was not asked to spend and can mask a red run by rolling the dice again.
ALLOWED_GH_RUN_ACTIONS = frozenset({"list", "view", "watch", "download"})

#: A pull request IS a board item, so `gh pr` -- the subcommand a lane uses constantly -- is too
#: coarse to be the unit of the decision. `--add-project` puts a PR on the project board, which is
#: the write this whole module exists to prevent, and milestones and labels are the same class:
#: stakeholder-visible fields somebody else curates.
#:
#: Denied on EVERY `gh pr` action, read ones included. A lane that wants PRs with a label can
#: filter them itself, and a per-action flag table would drift the first time `gh` moved a flag.
_GH_PR_DENIED_FLAGS = frozenset(
    {
        "--add-project",
        "--remove-project",
        "--project",
        "--milestone",
        "--add-label",
        "--remove-label",
        "--label",
    }
)
#: The SHORT spellings of the three above, denied only where they mean what they mean. `-m` on
#: `gh pr merge` is the MERGE-COMMIT strategy, not a milestone: denying it everywhere would break
#: an allowed verb on a spelling that means something else entirely.
_GH_PR_DENIED_SHORT_FLAGS = ("-p", "-m", "-l")
_GH_PR_FLAG_WRITING_ACTIONS = frozenset({"create", "edit"})

#: `gh api` is NOT in the subcommand allow-list -- it is the universal escape hatch, so it gets its
#: own read-only allow-list: these top-level endpoints, these repo sections, GET only.
GH_API_READ_ROOTS = frozenset({"rate_limit", "user"})
GH_API_READ_REPO_SECTIONS = frozenset(
    {"pulls", "commits", "actions", "check-runs", "branches", "contents"}
)

#: Any HTTP client naming one of these is reaching the API directly, whatever it is called.
GITHUB_ENDPOINT_MARKERS = ("api.github.com", "github.com/graphql")

_NET_TOOLS = frozenset({"curl", "wget", "http", "https", "xh", "httpie", "aria2c", "lwp-request"})
_SCRIPT_RUNNERS = ("python", "node", "ruby", "perl", "php", "deno", "bun", "irb", "osascript")
_SHELL_RUNNERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "eval"})

#: Wrappers that stand in FRONT of the real command word. Unwrapped so `command gh`, `env ... gh`,
#: `xargs gh` and `timeout 30 gh` are all just `gh`.
_WRAPPERS = frozenset(
    {
        "command",
        "builtin",
        "exec",
        "nohup",
        "time",
        "sudo",
        "doas",
        "env",
        "nice",
        "stdbuf",
        "timeout",
        "xargs",
        "setsid",
        "caffeinate",
    }
)
#: Wrappers that supply the command's ARGUMENTS from somewhere this module cannot read. `echo
#: "issue create" | xargs gh` runs `gh issue create` while leaving the guard holding one token, so
#: a bare `gh` behind one of these is unknown rather than harmless -- the same fact as a command
#: substitution, and it fails closed the same way.
_ARG_FEEDING_WRAPPERS = frozenset({"xargs"})
_WRAPPER_VALUE_FLAGS = frozenset(
    {"-u", "-n", "-I", "-i", "-P", "-d", "-a", "-L", "-s", "-k", "-C",
     "--signal", "--max-procs", "--replace", "--delimiter", "--unset", "--chdir"}
)
_TIMED_WRAPPERS = frozenset({"timeout", "nice", "caffeinate"})

#: `env -S "gh issue create"` splits a STRING into a command line and runs it -- `-c` under another
#: name, and the first read of it saw one long word that was not `gh`.
_ENV_SPLIT_FLAGS = ("--split-string", "-S")
#: `find . -exec gh issue create \;` runs a command word the segment's head is not.
_FIND_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
#: A herestring is a payload in different punctuation: `bash <<< "gh issue create"`.
_HERESTRING = "<<<"
#: `printf 'gh issue create\n' | sh` is the payload arriving through stdin. Only a LITERAL is read
#: -- see `_segment_denial` for exactly how far this goes and where it stops.
_LITERAL_PRINTERS = frozenset({"echo", "printf"})

#: Shell keywords that sit where a command word would, and mean nothing on their own. Without
#: these, `for i in 1 2; do gh issue close $i; done` reads as a segment whose command is `do` --
#: the loop body's real command word is one token further in, and the guard waved it through.
_SHELL_KEYWORDS = frozenset(
    {"do", "done", "then", "else", "elif", "fi", "if", "while", "until", "for", "case", "esac",
     "in", "select", "function", "{", "}", "!", "coproc"}
)

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: A token the tokenizer emitted for a REDIRECTION OPERATOR, optionally with its file-descriptor
#: prefix (`2>`, `2>&`). Word tokens can never match: the tokenizer splits at these characters, so
#: no ordinary argument reaches this regex.
_REDIRECT_RE = re.compile(r"^\d*(?:&>>|&>|>>|>&|>\||<<<|<<-|<<|<&|<>|<|>)$")
_DURATION_RE = re.compile(r"^[0-9]+(\.[0-9]+)?[smhd]?$")
_API_HOST_RE = re.compile(r"^(?:https?://)?api\.github\.com/?", re.IGNORECASE)

#: `gh api` flags that consume the following token. Anything not listed is treated as a bare flag,
#: which at worst makes the guard read one extra token as the endpoint -- the conservative miss.
_GH_API_VALUE_FLAGS = frozenset(
    {"-H", "--header", "-X", "--method", "-f", "--field", "-F", "--raw-field", "--input",
     "-q", "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview"}
)
#: Flags that make a `gh api` call a WRITE, whatever the endpoint says.
_GH_API_WRITE_FLAGS = frozenset({"-f", "--field", "-F", "--raw-field", "--input"})

MAX_RECURSION = 4


@dataclass(frozen=True)
class Decision:
    """What the guard decided, and the exact fragment it decided on.

    `matched` is kept separate from `reason` because the ledger stores it as its own field: a
    report that says WHICH command shape keeps being attempted is the evidence this control has to
    produce to keep paying rent, and digging it back out of a prose sentence is not evidence.
    """

    allowed: bool
    reason: str = ""
    matched: str = ""


def _deny(matched: str) -> Decision:
    fragment = " ".join(str(matched).split())
    if len(fragment) > MATCHED_MAX_CHARS:
        fragment = fragment[: MATCHED_MAX_CHARS - 3].rstrip() + "..."
    return Decision(False, (REASON_PREFIX + fragment)[:REASON_MAX_CHARS], fragment)


ALLOWED = Decision(True)


# ------------------------------------------------------------------------------------ tokenization


@dataclass(frozen=True)
class Segment:
    """One command position in the shell text.

    `substituted` marks a segment whose remaining arguments were eaten by a command substitution --
    `gh $(echo issue) create` leaves the tokens `["gh"]` and nothing else this module can read. That
    is NOT the same fact as a bare `gh`, and conflating the two let a `gh` with unknowable
    arguments read as a harmless help invocation.
    """

    tokens: list[str]
    substituted: bool = False
    #: This segment's stdout goes to the NEXT segment. `printf 'gh issue create' | sh` runs the
    #: text on the left, so the two segments are one invocation; `printf ... ; sh` and
    #: `printf ... || sh` are two, and reading a payload out of those would deny a lane for
    #: printing a sentence that merely mentions a verb.
    piped: bool = False


class _Scanner:
    """Accumulates tokens into segments, marking the ones a substitution truncated."""

    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self.tokens: list[str] = []
        self._buf: list[str] = []
        self._started = False

    def put(self, text: str) -> None:
        self._buf.append(text)
        self._started = True

    def end_token(self) -> None:
        if self._started:
            self.tokens.append("".join(self._buf))
        self._buf = []
        self._started = False

    def end_segment(self, *, substituted: bool = False, piped: bool = False) -> None:
        self.end_token()
        if self.tokens:
            self.segments.append(Segment(self.tokens, substituted, piped))
        self.tokens = []

    def split_before_operator(self) -> str:
        """End the pending word at a redirection operator, returning its file-descriptor prefix.

        `2>file` is one string of characters and three shell things: the fd `2`, the operator `>`
        and the target `file`. An all-digit pending word is that fd and belongs to the operator
        token; anything else is a word of its own (`log2>x` redirects a command called `log2`).
        """
        pending = "".join(self._buf)
        if self._started and pending.isdigit():
            self._buf = []
            self._started = False
            return pending
        self.end_token()
        return ""


def tokenize(command: str) -> list[Segment] | None:
    """Split shell text into command segments, or None when it cannot be parsed.

    Conservative by construction, and only in one direction: EVERY control operator starts a new
    segment, so a `gh` hidden behind `&&`, `|`, `;`, a newline, a subshell, `$(...)` or backticks
    still lands in the first position of a segment of its own. Quoted text is consumed as literal
    token content, which is why `echo "gh issue create"` is not a `gh` invocation -- and why a
    command substitution INSIDE double quotes still breaks the segment, because the shell would
    still run it.

    Redirection operators (`<`, `>`, `>>`, `2>`, `2>&`, `&>`, `<<<`) are OPERATORS here too, each
    emitted as a token of its own, so `effective_tokens` can step over a leading one the way the
    shell does and `_shell_payloads` can read a herestring's payload.

    None (unparseable -- an unterminated quote) is a DENY for builders and a no-op for humans; see
    `decide`. Guessing at broken shell is the one place where being clever is being wrong.
    """
    scan = _Scanner()
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\":
            if i + 1 < n:
                scan.put(command[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == "'":
            close = command.find("'", i + 1)
            if close < 0:
                return None
            scan.put(command[i + 1 : close])
            i = close + 1
            continue
        if ch == '"':
            i += 1
            closed = False
            while i < n:
                c = command[i]
                if c == "\\" and i + 1 < n:
                    scan.put(command[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    closed = True
                    break
                if c == "`":
                    scan.end_segment(substituted=True)
                    i += 1
                    continue
                if c == "$" and command[i + 1 : i + 2] == "(":
                    scan.end_segment(substituted=True)
                    i += 2
                    continue
                scan.put(c)
                i += 1
            if not closed:
                return None
            scan.put("")  # an empty quoted word is still a word
            continue
        if ch == "`":
            scan.end_segment(substituted=True)
            i += 1
            continue
        if ch in "()":
            scan.end_segment(substituted=ch == "(")
            i += 1
            continue
        if ch == "$" and command[i + 1 : i + 2] == "(":
            scan.end_segment(substituted=True)
            i += 2
            continue
        if ch in "<>" or (ch == "&" and command[i + 1 : i + 2] == ">"):
            # A REDIRECTION OPERATOR, and it is an operator rather than word characters. The shell
            # steps over a leading redirection to find the command word, so `2>/dev/null gh issue
            # create` IS `gh issue create`; a tokenizer that read `2>/dev/null` as the segment's
            # head token found a word that was not `gh` and allowed the whole line. Splitting here
            # rather than stripping later is what keeps `2>/dev/nullgh` from being reassembled into
            # a `gh`: the target word is `/dev/nullgh`, exactly as the shell reads it.
            fd = scan.split_before_operator()
            operator = ch
            i += 1
            if ch == "&":
                operator += ">"  # `&>` -- the peek above already proved this character
                i += 1
                if command[i : i + 1] == ">":
                    operator += ">"
                    i += 1
            elif ch == ">":
                if command[i : i + 1] in (">", "&", "|"):
                    operator += command[i]
                    i += 1
            else:  # "<"
                if command[i : i + 1] in ("<", "&", ">"):
                    operator += command[i]
                    i += 1
                    if operator == "<<" and command[i : i + 1] in ("<", "-"):
                        operator += command[i]
                        i += 1
            scan.put(fd + operator)
            scan.end_token()
            continue
        if ch in ";&|\n\r":
            # A single `|` PIPES this segment into the next; `||` is a logical OR and pipes
            # nothing. The distinction is what keeps `echo 'gh issue create' || sh` allowed.
            scan.end_segment(piped=ch == "|" and command[i + 1 : i + 2] != "|")
            i += 1
            continue
        if ch.isspace():
            scan.end_token()
            i += 1
            continue
        scan.put(ch)
        i += 1
    scan.end_segment()
    return scan.segments


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _is_redirection(token: str) -> bool:
    return bool(_REDIRECT_RE.match(token))


def _drop_redirection(rest: list[str]) -> list[str]:
    """Drop a redirection operator AND its target word -- the shell consumes both before the
    command word, so leaving the target behind would make `/dev/null` read as a command."""
    return rest[2:] if len(rest) > 1 else []


def effective_tokens(tokens: Sequence[str]) -> list[str]:
    """Strip shell keywords, inline assignments, redirections and wrapper commands so the head
    token is the REAL command word.

    `GH_TOKEN=x env -u FOO command gh issue create`, `do gh issue create` (a loop body),
    `2>/dev/null gh issue create` and `gh issue create` are the same invocation, and a guard that
    only recognised the last would be an inconvenience rather than a control.
    """
    return _unwrap(tokens)[0]


def _unwrap(tokens: Sequence[str]) -> tuple[list[str], bool]:
    """`effective_tokens`, plus whether an ARG-FEEDING wrapper was one of the ones removed.

    The second half is a fact the head token cannot carry: `xargs gh` and `gh` are the same one
    token, and only one of them is an invocation whose arguments the guard has read.
    """
    rest = list(tokens)
    arg_fed = False
    for _ in range(8):
        while rest and (
            _ASSIGNMENT_RE.match(rest[0]) or rest[0] in _SHELL_KEYWORDS or _is_redirection(rest[0])
        ):
            rest = _drop_redirection(rest) if _is_redirection(rest[0]) else rest[1:]
        if not rest:
            return [], arg_fed
        wrapper = _basename(rest[0])
        if wrapper not in _WRAPPERS:
            return rest, arg_fed
        arg_fed = arg_fed or wrapper in _ARG_FEEDING_WRAPPERS
        rest = rest[1:]
        while rest:
            token = rest[0]
            if _ASSIGNMENT_RE.match(token) or token in _SHELL_KEYWORDS:
                rest = rest[1:]
                continue
            if _is_redirection(token):
                rest = _drop_redirection(rest)
                continue
            if token == "--":
                rest = rest[1:]
                break
            if token.startswith("-") and token != "-":
                takes_value = token in _WRAPPER_VALUE_FLAGS
                rest = rest[1:]
                if takes_value and rest and not rest[0].startswith("-"):
                    rest = rest[1:]
                continue
            if wrapper in _TIMED_WRAPPERS and _DURATION_RE.match(token):
                rest = rest[1:]
                continue
            if wrapper == "xargs" and token in ("{}", "%"):
                rest = rest[1:]
                continue
            break
    return rest, arg_fed


# ------------------------------------------------------------------------------------- the rules


def _traverses(part: str) -> bool:
    """Is this path segment a `.` or `..`, in any spelling this module can see?

    The allow-list is POSITIONAL -- `repos/o/r/<section>` -- so a traversal segment does not
    reach a new path, it makes the positions lie: `repos/o/r/pulls/../issues` presents `pulls` at
    the position the guard reads and resolves to `repos/o/r/issues` at the other end. Percent
    encoding is the same trick with one extra hop, so `%2e` is folded before the comparison.
    """
    return part.lower().replace("%2e", ".") in (".", "..")


def _endpoint_allowed(endpoint: str) -> bool:
    value = _API_HOST_RE.sub("", endpoint.strip(), count=1)
    value = value.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in value.split("/") if part]
    if not parts:
        return False
    if any(_traverses(part) for part in parts):
        return False
    root = parts[0].lower()
    if root == "graphql":
        return False
    if root in GH_API_READ_ROOTS:
        # EXACTLY the root, with no sub-path. `user` answers "who am I"; `user/issues` is the
        # issue list, reached through a root that looks like identity -- the same section this
        # allow-list refuses two lines down when it is spelled `repos/o/r/issues`.
        return len(parts) == 1
    if root == "repos" and len(parts) >= 4 and parts[3].lower() in GH_API_READ_REPO_SECTIONS:
        return True
    return False


def _gh_api_allowed(rest: Sequence[str]) -> bool:
    """`gh api` is allowed only as a GET against the read allow-list. graphql is never allowed.

    Both halves matter. The endpoint list keeps `repos/o/r/issues` out even on a GET, because a
    read that an agent can do through `tautline issue` gains nothing by going around it; the method
    and field checks keep a WRITE out even when the path looks like a read.
    """
    method = "GET"
    endpoint: str | None = None
    index = 0
    total = len(rest)
    while index < total:
        token = rest[index]
        if token == "--":
            index += 1
            continue
        if token.startswith("-") and token != "-":
            name, sep, inline = token.partition("=")
            if name in _GH_API_WRITE_FLAGS:
                return False
            if name in ("-X", "--method"):
                if sep:
                    method = inline
                    index += 1
                else:
                    method = rest[index + 1] if index + 1 < total else ""
                    index += 2
                continue
            if token.startswith("-X") and len(token) > 2:
                method = token[2:]
                index += 1
                continue
            if (token.startswith("-f") or token.startswith("-F")) and len(token) > 2:
                return False
            if name in _GH_API_VALUE_FLAGS and not sep:
                index += 2
            else:
                index += 1
            continue
        if endpoint is None:
            endpoint = token
        index += 1
    if endpoint is None:
        return False
    if method.strip().upper() != "GET":
        return False
    return _endpoint_allowed(endpoint)


def _gh_allowed(tokens: Sequence[str], *, substituted: bool = False, arg_fed: bool = False) -> bool:
    args = list(tokens[1:])
    index = 0
    total = len(args)
    subcommand: str | None = None
    while index < total:
        token = args[index]
        if token == "--":
            index += 1
            continue
        if token.startswith("-") and token != "-":
            if token in ("-R", "--repo", "--hostname"):
                index += 2
            else:
                index += 1
            continue
        subcommand = token
        index += 1
        break
    if subcommand is None:
        # A bare `gh`, `gh --help` or `gh --version` reaches nothing. Denying it would spend the
        # lane's attention on a command that cannot cause the defect this guard exists for.
        #
        # A SUBSTITUTED segment is the opposite fact and must not share this exit: in
        # `gh $(echo issue) create` the subcommand is computed at run time, so the guard has not
        # read a harmless invocation -- it has read nothing. Unknown arguments to `gh` fail closed.
        #
        # `xargs gh` is the same fact through a different door: `echo "issue create" | xargs gh`
        # runs `gh issue create`, and the arguments arrive from a stream this module never sees.
        return not (substituted or arg_fed)
    rest = args[index:]
    name = subcommand.lower()
    if name == "api":
        return _gh_api_allowed(rest)
    if name not in ALLOWED_GH_SUBCOMMANDS:
        return False
    if name == "search":
        return _action_allowed(rest, ALLOWED_GH_SEARCH_TARGETS)
    if name == "repo":
        return _action_allowed(rest, ALLOWED_GH_REPO_ACTIONS)
    if name == "workflow":
        return _action_allowed(rest, ALLOWED_GH_WORKFLOW_ACTIONS)
    if name == "auth":
        return _action_allowed(rest, ALLOWED_GH_AUTH_ACTIONS)
    if name == "run":
        return _action_allowed(rest, ALLOWED_GH_RUN_ACTIONS)
    if name == "pr":
        return _gh_pr_allowed(rest)
    return True


def _gh_pr_allowed(rest: Sequence[str]) -> bool:
    """`gh pr` minus the flags that reach the board, the milestone list and the label set.

    The subcommand stays allowed -- opening, reading and merging pull requests is most of what a
    builder lane does -- and only the flags that write somebody else's surface are refused.
    """
    action = next((token for token in rest if not token.startswith("-")), "").lower()
    for token in rest:
        if not token.startswith("-") or token == "-":
            continue
        flag = token.partition("=")[0]
        if flag in _GH_PR_DENIED_FLAGS:
            return False
        if action in _GH_PR_FLAG_WRITING_ACTIONS and not flag.startswith("--"):
            # A short flag, possibly with its value glued on (`-lblocked`), which is how the `gh`
            # flag parser reads it and therefore how the guard has to read it too.
            if flag[:2] in _GH_PR_DENIED_SHORT_FLAGS:
                return False
    return True


def _action_allowed(rest: Sequence[str], allowed: frozenset[str]) -> bool:
    """The FIRST positional after a subcommand, checked against a second allow-list.

    `gh` puts the action before its flags (`gh repo delete o/r --yes`), so the first positional is
    the action. A missing one -- bare `gh repo` -- is denied rather than waved through: the
    subcommand-level exit for a bare `gh` exists because `gh --help` reaches nothing, but `gh repo`
    with an action this function could not read is an argument shape we have not understood, and
    the direction to fail in is closed.
    """
    action = next((token for token in rest if not token.startswith("-")), None)
    return action is not None and action.lower() in allowed


def _names_the_github_api(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in GITHUB_ENDPOINT_MARKERS)


def _shell_payloads(tokens: Sequence[str]) -> list[str]:
    """The inner command text a shell runner would execute.

    `bash -c 'gh issue create'` puts the whole inner command in ONE token, so a tokenizer that
    stopped at the top level would wave it through. `decide` recurses into these instead.
    """
    name = _basename(tokens[0]).lower()
    if name == "eval":
        return [" ".join(tokens[1:])] if len(tokens) > 1 else []
    payloads: list[str] = []
    index = 1
    while index < len(tokens):
        if tokens[index] in ("-c", "-lc", "-ic", "--command") and index + 1 < len(tokens):
            payloads.append(tokens[index + 1])
            index += 2
            continue
        index += 1
    return payloads


def _herestring_payloads(tokens: Sequence[str]) -> list[str]:
    """The word after a `<<<`, which the shell feeds to the command as its stdin.

    A herestring is a `-c` payload in different punctuation: `bash <<< "gh issue create"` and
    `bash -c "gh issue create"` run the same thing, and only one of them used to be read.
    """
    return [
        tokens[index + 1]
        for index, token in enumerate(tokens[:-1])
        if token == _HERESTRING
    ]


def _env_split_payloads(tokens: Sequence[str]) -> list[str]:
    """The string `env -S` would split into a command line -- `-c` under a third name.

    Read from the RAW segment tokens rather than the unwrapped ones, because `env` is a wrapper:
    unwrapping it leaves the payload sitting where a command word should be, as one long word that
    is not `gh`, which is exactly how this shape got through.
    """
    payloads: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        for flag in _ENV_SPLIT_FLAGS:
            if token == flag:
                if index + 1 < len(tokens):
                    payloads.append(tokens[index + 1])
                    index += 1
                break
            if token.startswith(flag + "="):
                payloads.append(token[len(flag) + 1 :])
                break
            if flag == "-S" and token.startswith("-S") and len(token) > 2:
                payloads.append(token[2:])  # `-S'gh issue create'`, glued the way getopt reads it
                break
        index += 1
    return payloads


def _find_exec_payloads(tokens: Sequence[str]) -> list[str]:
    """The command `find -exec` runs, which is a command word the segment's head is not."""
    payloads: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index] not in _FIND_EXEC_FLAGS:
            index += 1
            continue
        index += 1
        argv: list[str] = []
        while index < len(tokens) and tokens[index] not in (";", "+"):
            argv.append(tokens[index])
            index += 1
        if argv:
            payloads.append(shlex.join(argv))
    return payloads


def _literal_text(tokens: Sequence[str]) -> str:
    """What a `printf`/`echo` segment would put on its stdout, as far as this module can tell."""
    return " ".join(token for token in tokens[1:] if not token.startswith("-"))


def _nested_payloads(segment: Segment, effective: Sequence[str], name: str) -> list[str]:
    """Every inner command TEXT this segment would run through another program.

    Each entry is gated on the head command word, so a `grep -e "..."` or an `echo -exec ..."` is
    not read as an invocation of something. What is NOT here is as load-bearing as what is: a
    payload this module cannot see as literal text -- `python gen.py | sh`, a file written then
    sourced, an HTTP client of the lane's own -- is not caught, and the module docstring says so
    rather than implying a completeness the design does not have.
    """
    payloads: list[str] = []
    if name in _SHELL_RUNNERS:
        payloads.extend(_shell_payloads(effective))
        payloads.extend(_herestring_payloads(segment.tokens))
    if name == "env" or any(_basename(token).lower() == "env" for token in segment.tokens):
        payloads.extend(_env_split_payloads(segment.tokens))
    if name == "find":
        payloads.extend(_find_exec_payloads(segment.tokens))
    return payloads


def _segment_denial(segment: Segment, depth: int, *, upstream: Segment | None = None) -> str | None:
    """The offending text of this segment, or None when the segment reaches nothing guarded.

    `upstream` is the segment PIPED into this one, and it is read for exactly one shape: a
    `printf`/`echo` literal piped into a shell (`printf 'gh issue create\\n' | sh`), where the
    payload arrives through stdin instead of through `-c`. Only a literal is read; a generated
    payload is text this module never sees.
    """
    effective, arg_fed = _unwrap(segment.tokens)
    # An EMPTY unwrap is not "nothing to check": `env -S "gh issue create"` unwraps to nothing at
    # all, because the payload sits in a flag rather than in a command word. The payload pass below
    # reads the raw tokens, so it still sees it.
    name = _basename(effective[0]).lower() if effective else ""
    text = " ".join(effective)
    if name == "gh":
        if _gh_allowed(effective, substituted=segment.substituted, arg_fed=arg_fed):
            return None
        if len(effective) == 1:
            return f"{text} $(...)" if segment.substituted else f"{text} (arguments from stdin)"
        return text
    if name in _NET_TOOLS or name.startswith(_SCRIPT_RUNNERS):
        return text if _names_the_github_api(text) else None
    if name in _SHELL_RUNNERS and _names_the_github_api(text):
        return text
    if depth >= MAX_RECURSION:
        return None
    payloads = _nested_payloads(segment, effective, name)
    if name in _SHELL_RUNNERS and upstream is not None:
        upstream_effective, _ = _unwrap(upstream.tokens)
        if upstream_effective and _basename(upstream_effective[0]).lower() in _LITERAL_PRINTERS:
            payloads.append(_literal_text(upstream_effective))
    for payload in payloads:
        inner = _scan(payload, depth + 1)
        if inner is not None:
            return inner
    return None


def _scan(command: str, depth: int) -> str | None:
    segments = tokenize(command)
    if segments is None:
        return f"unparseable shell (a builder lane fails closed): {command}"
    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index else None
        matched = _segment_denial(
            segment, depth, upstream=previous if previous is not None and previous.piped else None
        )
        if matched:
            return matched
    return None


def decide(command: str, *, builder: bool) -> Decision:
    """The whole predicate. A human is allowed everything, before any parsing happens.

    That ordering is deliberate, not an optimisation: it means there is no shell text a human can
    type that this module can get wrong, so the guard cannot regress the people it was never meant
    to bind -- and the human case in the test file is an assertion about this line.
    """
    if not builder:
        return ALLOWED
    if not isinstance(command, str) or not command.strip():
        return ALLOWED
    matched = _scan(command, 0)
    return _deny(matched) if matched else ALLOWED


def decide_argv(argv: Iterable[str], *, builder: bool) -> Decision:
    """The same predicate over an ALREADY-SPLIT argv (the `gh` shim's path).

    Re-quoted rather than space-joined: the caller's shell already did the splitting, so a plain
    join would re-interpret a PR body that merely MENTIONS `gh issue create` as shell syntax and
    deny a perfectly good `gh pr create`.
    """
    return decide(shlex.join(list(argv)), builder=builder)


# ----------------------------------------------------------------------------- the ledger evidence


def _lane_data(target: Path):
    """The lane's adapter view, or None when this tree has no adapter to write a ledger into."""
    from tautline_methodology import cli as cli_module

    namespace = argparse.Namespace(target=Path(target), project=None)
    data, _project_path, resolved = cli_module.lane_project(namespace, lean_ok=True)
    return data, resolved


def record_denial(target: Path, command: str, matched: str, cwd: str) -> None:
    """Append the denial to the lane's event log. NEVER raises, NEVER prints.

    Never raises because a ledger failure must not turn a deny into a crash (or, worse, into an
    allow). Never prints because the hook's stdout is a JSON channel the harness parses -- a
    stray warning line there would corrupt the decision it is carrying.
    """
    try:
        from tautline_methodology import cli as cli_module

        data, resolved = _lane_data(target)
        safe_command = cli_module.redact_secrets(command)[:EVENT_COMMAND_MAX_CHARS]
        cli_module.write_event(
            data,
            resolved,
            event=DENIAL_EVENT_NAME,
            severity="block",
            plain=f"builder guard denied a GitHub command: {matched}"[:200],
            next_action="use `tautline board|issue|debt` for issues and the board",
            refs={
                "command": safe_command,
                "matched": matched[:MATCHED_MAX_CHARS],
                "cwd": str(cwd)[:200],
            },
        )
    except BaseException:  # noqa: BLE001 - the ledger is evidence, never a gate on the decision
        return


def _denial_rows(target: Path) -> list[dict]:
    from tautline_methodology import cli as cli_module

    data, resolved = _lane_data(target)
    _human, jsonl, _lock = cli_module.observability_event_paths(data, resolved)
    rows: list[dict] = []
    try:
        text = jsonl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event") == DENIAL_EVENT:
            rows.append(row)
    return rows


# --------------------------------------------------------------------------------------- the shim

SHIM_DIR = Path("~/.config/minervit/builder-shim")

#: POSIX sh, and SHELL BUILTINS ONLY after the guard call: `cd`, `pwd`, `test`, `printf` and
#: `command` are builtins, so the shim still works on a PATH that has no /usr/bin on it.
#:
#: Its own directory is BAKED IN at generation time rather than derived from `$0`. The first
#: version derived it with `dirname`, which is an external binary: on a PATH without one, `$0`'s
#: directory came out as the CWD, the "skip my own directory" test never matched, and the shim
#: exec'd ITSELF -- a fork bomb, found by the test below that now pins exit 127. `$0` is no better
#: a source: a shell that finds this script through PATH sets it to the bare word `gh`.
GH_SHIM_TEMPLATE = """#!/bin/sh
# Generated by `tautline builder-guard --shim-dir`. Do not edit; it is rewritten on every call.
#
# Prepend this directory to PATH in a builder lane whose harness has no PreToolUse hook (Codex and
# friends). A HUMAN shell is unaffected even with the shim on PATH: the guard is a no-op unless
# `builder_role_active()` says builder, so every command falls straight through to the real `gh`.
shim_dir={shim_dir}
shim_dir_real=$(CDPATH= cd -- "$shim_dir" 2>/dev/null && pwd -P)

if command -v tautline >/dev/null 2>&1; then
    # The guard's stderr is CAPTURED, not passed through, and its exit 2 is not trusted on its own.
    # An installed `tautline` older than the `builder-guard` verb answers argparse's "invalid
    # choice" with exit 2 for every argv -- indistinguishable from a deny unless something asks.
    # A human is told to leave this shim on PATH, so trusting that 2 bricked their `gh`: every
    # invocation exit 2 with argparse noise on stderr, from a control whose whole premise is that
    # humans never notice it. So: probe `--help`, exactly as the PreToolUse hook does, and print
    # the captured reason only when the CLI that produced the 2 actually has the verb.
    guard_stderr=$(tautline builder-guard --argv -- gh "$@" 2>&1 >/dev/null)
    guard_status=$?
    if [ "$guard_status" -eq 2 ] && tautline builder-guard --help >/dev/null 2>&1; then
        printf '%s\n' "$guard_stderr" >&2
        exit 2
    fi
fi

real_gh=""
IFS=:
for entry in $PATH; do
    [ -n "$entry" ] || entry=.
    if [ "$entry" = "$shim_dir" ]; then
        continue
    fi
    resolved=$(CDPATH= cd -- "$entry" 2>/dev/null && pwd -P)
    if [ -n "$resolved" ] && [ -n "$shim_dir_real" ] && [ "$resolved" = "$shim_dir_real" ]; then
        continue
    fi
    if [ -f "$entry/gh" ] && [ -x "$entry/gh" ]; then
        real_gh="$entry/gh"
        break
    fi
done
unset IFS

if [ -z "$real_gh" ]; then
    echo "gh: not found on PATH outside the tautline builder shim ($shim_dir)" >&2
    exit 127
fi
exec "$real_gh" "$@"
"""


def shim_script(directory: Path) -> str:
    return GH_SHIM_TEMPLATE.format(shim_dir=shlex.quote(str(directory)))


def ensure_shim_dir(root: Path | None = None) -> Path:
    """Create or refresh the shim directory idempotently and return it."""
    directory = Path(root).expanduser() if root is not None else SHIM_DIR.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "gh"
    wanted = shim_script(directory)
    try:
        current = script.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current != wanted:
        script.write_text(wanted, encoding="utf-8")
    script.chmod(0o755)
    return directory


# ------------------------------------------------------------------------------------- the surface

DENY_HOOK_EVENT = "PreToolUse"
MALFORMED_MATCHED = "malformed PreToolUse payload"


def _deny_object(reason: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": DENY_HOOK_EVENT,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def _block(target: Path, command: str, decision: Decision, *, cwd: str, emit_json: bool) -> int:
    record_denial(target, command, decision.matched, cwd)
    if emit_json:
        print(_deny_object(decision.reason))
    print(decision.reason, file=sys.stderr)
    return 2


def _role(target: Path, environ: Mapping[str, str] | None = None) -> bool:
    """Is THIS process a builder lane? One predicate, and the environment is never read here.

    `environ=None` is passed straight through to `builder_role_active`, whose `resolve_env` is the
    framework's single environment chokepoint (and the reason it handles the TAUTLINE_/MINERVIT_
    alias pair). Reading the process environment directly in this module would put a second reader
    of the same fact beside it -- which is what `tests/test_env_reads_use_resolver.py` polices.
    """
    try:
        return builder_role_active(target, environ)
    except Exception:  # noqa: BLE001 - an unreadable marker is not a builder marker
        return False


UNEXPECTED_MATCHED = "the guard could not evaluate this command"


def _hook(args: argparse.Namespace) -> int:
    """Contained: an unexpected error here resolves to the SAME answer as a malformed payload.

    `builder-guard` does not end in `-hook`, so `dispatch_command`'s fail-open contract does not
    cover it -- and that is correct, because failing open is only right for humans. Without this
    wrapper an unexpected exception would print a traceback and exit 1, which a harness reads as
    ALLOW: the guard would fail open for a BUILDER, quietly, on the one path where it matters.
    """
    try:
        return _hook_decision(args)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - the direction of the failure is what is load-bearing
        if not _role(Path(args.target)):
            return 0
        return _block(
            Path(args.target),
            "",
            _deny(UNEXPECTED_MATCHED),
            cwd=str(args.target),
            emit_json=True,
        )


def _hook_decision(args: argparse.Namespace) -> int:
    target = Path(args.target)
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    payload: dict | None = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = None

    cwd_text = ""
    if payload is not None:
        candidate = payload.get("cwd")
        if isinstance(candidate, str) and candidate.strip():
            cwd_text = candidate.strip()
    root = Path(cwd_text) if cwd_text else target

    if not _role(root):
        # THE HUMAN PATH, and it is the first exit for a reason: silent, exit 0, nothing parsed.
        return 0

    if payload is None:
        # Fail-open is the priority for humans, and we already know this is not one. A builder lane
        # whose payload we cannot read is a builder lane whose command we cannot check.
        return _block(
            root, "", _deny(MALFORMED_MATCHED), cwd=str(root), emit_json=True
        )

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return _block(root, "", _deny(MALFORMED_MATCHED), cwd=str(root), emit_json=True)

    decision = decide(command, builder=True)
    if decision.allowed:
        return 0
    return _block(root, command, decision, cwd=str(root), emit_json=True)


def _argv_mode(args: argparse.Namespace) -> int:
    target = Path(args.target)
    argv = list(args.command or [])
    if not argv:
        return 0
    if not _role(target):
        return 0
    decision = decide_argv(argv, builder=True)
    if decision.allowed:
        return 0
    return _block(target, shlex.join(argv), decision, cwd=str(target), emit_json=False)


def _shim_mode(args: argparse.Namespace) -> int:
    print(ensure_shim_dir())
    return 0


def _report_mode(args: argparse.Namespace) -> int:
    from tautline_methodology import cli as cli_module

    target = Path(args.target)
    rows = _denial_rows(target)
    print(f"builder_guard_denials: {len(rows)}")
    if not rows:
        print("builder_guard_note: no denial recorded on this lane -- the guard has caught nothing")
        return 0
    for row in rows[-REPORT_LIMIT:]:
        refs = row.get("refs") if isinstance(row.get("refs"), dict) else {}
        stamp = cli_module._ledger_safe(row.get("ts", "?"), 40)
        matched = cli_module._ledger_safe(refs.get("matched", ""), MATCHED_MAX_CHARS)
        command = cli_module._ledger_safe(refs.get("command", ""), EVENT_COMMAND_MAX_CHARS)
        print(f"{stamp} denied: {matched} | command: {command}")
    return 0


def builder_guard_command(args: argparse.Namespace) -> int:
    """`tautline builder-guard`: one predicate, four surfaces."""
    modes = [bool(args.hook), bool(args.argv), bool(args.shim_dir), bool(args.report)]
    if sum(modes) != 1:
        raise SystemExit(
            "builder-guard needs exactly one of --hook, --argv, --shim-dir, --report"
        )
    if args.shim_dir:
        return _shim_mode(args)
    if args.report:
        return _report_mode(args)
    if args.argv:
        return _argv_mode(args)
    return _hook(args)


__all__ = [
    "ALLOWED_GH_AUTH_ACTIONS",
    "ALLOWED_GH_REPO_ACTIONS",
    "ALLOWED_GH_RUN_ACTIONS",
    "ALLOWED_GH_SEARCH_TARGETS",
    "ALLOWED_GH_SUBCOMMANDS",
    "ALLOWED_GH_WORKFLOW_ACTIONS",
    "DENIAL_EVENT",
    "DENIAL_EVENT_NAME",
    "Decision",
    "EVENT_COMMAND_MAX_CHARS",
    "GH_SHIM_TEMPLATE",
    "MATCHED_MAX_CHARS",
    "REASON_PREFIX",
    "SHIM_DIR",
    "Segment",
    "builder_guard_command",
    "decide",
    "decide_argv",
    "effective_tokens",
    "ensure_shim_dir",
    "record_denial",
    "shim_script",
    "tokenize",
]
