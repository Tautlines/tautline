"""Client-side merge gate: refuse to merge a PR whose live checks are not green.

Backlog item 21 (`2026-07-24-experimental-required-checks`), option 3 -- selected by the operator
on 2026-07-24 after the first two options turned out to be platform/billing decisions.

Branch protection and rulesets are PAID features for private repositories, so this repo returns
403 on every protection endpoint, including `main`. A green CI run therefore gates nothing: a red
commit stays mergeable, which is exactly how one reached `experimental` on 2026-07-29. That is not
a Tautline accident -- a private repo on a free plan is the single most common adopter
configuration, so a methodology that assumes platform-enforced required checks silently degrades
to NO gate at all for its most typical adopter.

When the platform cannot enforce the gate, the methodology enforces it. This module is the verdict
kernel: a pure function over `gh pr view --json statusCheckRollup` plus a coarse detector for raw
`gh pr merge` invocations that would route around the verb.

Pure leaf: no `cli` import, no subprocess, no filesystem. Everything here is unit-testable in
isolation, which matters more than usual for a component whose job is to say "no".
"""
from __future__ import annotations

import re
import shlex
from typing import NamedTuple

# Terminal-and-not-green. STALE is in here deliberately: GitHub reports it for a check whose run
# no longer corresponds to the head commit, which is precisely the "you are about to merge on the
# strength of an old green" case. It blocks unconditionally, even in tolerate-pending mode.
FAILED_CONCLUSIONS = frozenset(
    {
        "FAILURE",
        "ERROR",
        "CANCELLED",
        "TIMED_OUT",
        "STARTUP_FAILURE",
        "ACTION_REQUIRED",
        "STALE",
    }
)

# Terminal-and-acceptable. NEUTRAL and SKIPPED are green enough: a check that declined to run is
# not evidence of breakage, and treating it as one would block every conditional workflow.
GOOD_CONCLUSIONS = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})

# Not finished yet.
PENDING_STATES = frozenset(
    {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}
)

OUTCOME_BLOCK = "block"
OUTCOME_ALLOW = "allow"
OUTCOME_UNVERIFIABLE = "unverifiable"


class MergeGateVerdict(NamedTuple):
    outcome: str
    offenders: tuple[tuple[str, str], ...]
    reason: str


def _node_signal(node: dict) -> str:
    """The one field that says how a rollup node turned out.

    A CheckRun reports `conclusion` (null until it finishes, with `status` carrying the progress);
    a StatusContext reports `state`. Coerced through `str()` because a malformed payload with a
    non-string here must produce a verdict, not an AttributeError inside a merge gate.
    """
    for key in ("conclusion", "status", "state"):
        value = node.get(key)
        if value not in (None, ""):
            return str(value).strip().upper()
    return ""


def _node_name(node: dict) -> tuple[str, str]:
    name = node.get("name") or node.get("context") or "<unnamed check>"
    url = node.get("detailsUrl") or node.get("targetUrl") or ""
    return str(name), str(url)


def classify_merge_gate(rollup: object, block_on_pending: bool) -> MergeGateVerdict:
    """Decide whether a PR's live checks permit a merge. Never raises.

    Three outcomes, and the difference between the last two is the whole design:

    * ``block`` -- a POSITIVE bad signal. Some check failed, or (in block-on-pending mode) some
      check has not reported yet. This is the only outcome that stops a merge.
    * ``allow`` -- checks exist and every one of them is acceptable.
    * ``unverifiable`` -- we could not read a verdict at all (no rollup, an empty list, a
      malformed node, a signal GitHub has invented since this was written). Fail OPEN, loudly. A
      gate that blocks when it cannot see is a lockout, and the 2026-07-22 startup-gate incident
      is what that costs; blocking is reserved for evidence.

    Precedence is failure > pending > unknown. A failed check outranks an unknown one because
    "one check failed and one is unrecognized" is not an unverifiable state -- it is a failure.
    Pending outranks unknown for the same reason in the other direction: a positive pending signal
    is evidence, and evidence should not be discarded because some sibling node was strange.
    """
    if not isinstance(rollup, list) or not rollup:
        return MergeGateVerdict(
            OUTCOME_UNVERIFIABLE, (), "no status checks reported for this PR"
        )

    failed: list[tuple[str, str]] = []
    pending: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []

    for node in rollup:
        if not isinstance(node, dict):
            unknown.append(("<malformed rollup node>", ""))
            continue
        identity = _node_name(node)
        signal = _node_signal(node)
        if signal in FAILED_CONCLUSIONS:
            failed.append(identity)
        elif signal in GOOD_CONCLUSIONS:
            continue
        elif signal in PENDING_STATES or not signal:
            pending.append(identity)
        else:
            unknown.append(identity)

    if failed:
        return MergeGateVerdict(
            OUTCOME_BLOCK,
            tuple(failed),
            f"{len(failed)} check(s) are failing",
        )
    if pending and block_on_pending:
        return MergeGateVerdict(
            OUTCOME_BLOCK,
            tuple(pending),
            f"{len(pending)} check(s) have not reported yet",
        )
    if pending:
        # Pending outranks unknown in BOTH modes, not just the blocking one. Reporting
        # `unverifiable` here would contradict this module's own documented precedence and throw
        # away the positive pending evidence a caller surfaces as "tolerated" (deferred kernel P2).
        return MergeGateVerdict(
            OUTCOME_ALLOW,
            tuple(pending),
            f"{len(pending)} check(s) still running, tolerated by configuration",
        )
    if unknown:
        return MergeGateVerdict(
            OUTCOME_UNVERIFIABLE,
            tuple(unknown),
            "at least one check reported a signal this gate does not recognize",
        )
    return MergeGateVerdict(OUTCOME_ALLOW, (), "all checks are green")


# --- coarse detector for raw `gh pr merge` -----------------------------------------------------
#
# This answers ONE question: is this shell command the `gh pr merge` command class? It never
# resolves the target PR, the flags, or the repo. That restraint is deliberate and hard-won: the
# reviewed design lineage removed target-parsing entirely because every attempt at it produced a
# new class of misidentification, and a gate that guesses which PR you meant is worse than no gate.

_OPERATORS = re.compile(r"(?:\|\||&&|[;|&\n])")

# Wrappers that take a command as their tail. Stripping them is what stops `env X=1 gh pr merge`
# and `sudo gh pr merge` from sailing past.
_WRAPPER_HEADS = frozenset(
    {"env", "sudo", "nohup", "time", "command", "builtin", "exec", "nice", "stdbuf", "timeout"}
)

_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# `timeout 30 gh ...`, `timeout 30s gh ...`, `nice -n 5 gh ...` -- a wrapper's own operand, which
# must be stepped over like its flags or the token after the wrapper is mistaken for the command.
_WRAPPER_OPERAND = re.compile(r"^\d+[smhd]?$")

# Wrapper flags that consume the NEXT token as their value. Without these, `sudo -u build gh ...`
# stops the strip at `build`, `env -C /tmp gh ...` stops at `/tmp`, and a valid wrapped raw merge
# reads as not-a-merge -- a false negative, which in a detector is a bypass (deferred kernel P2).
_WRAPPER_VALUE_FLAGS = frozenset(
    {
        "-u", "--user",          # sudo
        "-g", "--group",         # sudo
        "-C", "--chdir",         # env
        "-n", "--adjustment",    # nice
        "-s", "--signal",        # timeout
        "-k", "--kill-after",    # timeout
    }
)
# Deliberately NOT here: `-i`, which is env's ignore-environment and sudo's login-shell flag and
# takes no value. Listing it made `env -i gh pr merge 1` swallow `gh` itself and read the command
# as `pr merge 1` -- a false negative, and therefore a bypass.

# `gh` global flags that take a VALUE, so the value must be skipped too or it would be mistaken
# for the subcommand.
_GLOBAL_VALUE_FLAGS = frozenset({"-R", "--repo"})


def _segments(command: str) -> list[str]:
    """Split a command line into shell statements, ignoring operators inside quotes."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"' and index + 1 < len(command):
                index += 1
                current.append(command[index])
        elif char in "'\"":
            quote = char
            current.append(char)
        else:
            match = _OPERATORS.match(command, index)
            if match:
                segments.append("".join(current))
                current = []
                index = match.end()
                continue
            current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        # Unbalanced quotes. Fall back to whitespace splitting rather than declaring the command
        # safe: an unparseable command is not evidence that it is not a merge.
        return segment.split()


def _is_repo_flag(token: str) -> bool:
    """True for every spelling of gh's repo selector, attached values included.

    `--repo o/r`, `--repo=o/r`, `-R o/r` and `-Ro/r` are all accepted by gh, so a detector that
    recognised only the bare forms would leave `gh pr -Ro/r merge 1` looking like something other
    than a merge (Codex R1 P2). `protected_passthrough` already treats all four as equivalent;
    these two must not disagree about what a repo flag is.
    """
    return token.split("=", 1)[0] in _GLOBAL_VALUE_FLAGS or (
        token.startswith("-R") and len(token) > 2
    )


def _strip_wrappers(tokens: list[str]) -> list[str]:
    """Step over env assignments and command wrappers to expose the real command head.

    A wrapper is stepped over WITH its own flags and operands: `sudo -E gh ...`, `env -i X=1 gh
    ...` and `timeout 30 gh ...` are the ordinary spellings, and dropping only the wrapper word
    left `-E` / `-i` / `30` looking like the command (Codex R1 P2). Flag-stripping is armed only
    once a wrapper has actually been seen, so an unrelated `foo -x gh ...` is not silently
    re-interpreted.
    """
    seen_wrapper = False
    while tokens:
        head = tokens[0]
        if _ENV_ASSIGN.match(head):
            tokens = tokens[1:]
            continue
        if head.rsplit("/", 1)[-1] in _WRAPPER_HEADS:
            seen_wrapper = True
            tokens = tokens[1:]
            continue
        if seen_wrapper and head.startswith("-"):
            # A wrapper flag may carry its value as the next token (`sudo -u build`), attached
            # (`-ubuild`), or not at all (`sudo -E`). Only the separated form eats a token.
            takes_value = head in _WRAPPER_VALUE_FLAGS and "=" not in head
            # Belt and braces: whatever this list says, never swallow the command itself. A flag
            # misclassified as value-taking would otherwise hide the very invocation the detector
            # exists to see, and a false negative here is a bypass.
            if takes_value and len(tokens) > 1 and tokens[1].rsplit("/", 1)[-1] == "gh":
                takes_value = False
            tokens = tokens[2:] if takes_value and len(tokens) > 1 else tokens[1:]
            continue
        if seen_wrapper and _WRAPPER_OPERAND.match(head):
            tokens = tokens[1:]
            continue
        break
    return tokens


def is_raw_pr_merge(command: str) -> bool:
    """True iff some statement in `command` invokes the `gh pr merge` command class.

    Coarse by design -- yes/no on the command class, never a target or flag resolution. The cwd is
    irrelevant here; the caller decides whether the payload's directory is inside an armed repo,
    and `find_adapter_root` walks up, so `cd subdir && gh pr merge` is already covered.
    """
    if not command or "merge" not in command:
        return False
    for segment in _segments(command):
        tokens = _strip_wrappers(_tokens(segment))
        if not tokens or tokens[0].rsplit("/", 1)[-1] != "gh":
            continue
        rest = tokens[1:]
        # Skip gh's own global flags to reach the subcommand.
        while rest and rest[0].startswith("-"):
            flag = rest[0]
            rest = rest[1:]
            if flag in _GLOBAL_VALUE_FLAGS and rest:
                rest = rest[1:]
        if not rest or rest[0] != "pr":
            continue
        rest = rest[1:]
        # ONLY the repo selector may sit between `pr` and the subcommand. Skipping anything else
        # would make `gh pr --help merge` read as a merge. An ATTACHED value carries its own
        # argument, so only the separated spelling consumes the next token.
        while rest and _is_repo_flag(rest[0]):
            attached = "=" in rest[0] or (rest[0].startswith("-R") and len(rest[0]) > 2)
            rest = rest[1:] if attached else (rest[2:] if len(rest) > 1 else [])
        if rest and rest[0] == "merge":
            return True
    return False


# --- protecting the verb's own contract --------------------------------------------------------

# Flags that change WHAT gets merged, or HOW hard. Forwarding any of these blindly would let the
# gate verify one thing and merge another -- `tautline merge 12 --repo other/repo` reads PR 12's
# checks in this checkout and then merges someone else's PR 12. They must be parsed by the verb,
# never passed through.
#
# `--match-head-commit` is refused for the same reason in the time dimension -- a caller pin would
# silently replace the commit the gate verified with a SHA nothing verified -- but only while the
# gate is verifying at all. See VERIFIED_HEAD_FLAG.
PROTECTED_PASSTHROUGH_FLAGS = frozenset({"--repo", "-R", "--admin"})

# Refused only while the gate is actually verifying. With `enforcement=off` the verb reads no
# rollup, so it has no verified head to supply -- refusing the caller's pin there would take away
# gh's own race protection and offer nothing in its place. Conditional, so it is checked by the
# caller rather than folded into the unconditional set above.
VERIFIED_HEAD_FLAG = "--match-head-commit"

_PR_URL = re.compile(
    r"^https?://[^/\s]+/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/\d+", re.IGNORECASE
)


def head_pin_in(passthrough: list[str]) -> bool:
    """Whether the caller supplied their own `--match-head-commit`, in either spelling."""
    return any(token.split("=", 1)[0] == VERIFIED_HEAD_FLAG for token in passthrough)


def protected_passthrough(passthrough: list[str]) -> list[str]:
    """Flags in `passthrough` that the verb must own rather than forward.

    Every spelling `gh` accepts, because a guard that closes one of them closes nothing:

    * ``--repo other/repo`` -- separate value;
    * ``--repo=other/repo`` -- attached long value;
    * ``-R other/repo`` -- separate short value;
    * ``-Rother/repo``    -- ATTACHED short value, which reads as one unknown token and slipped
      straight through the first version of this guard (Codex R2 P1).
    """
    offenders: list[str] = []
    for token in passthrough:
        name = token.split("=", 1)[0]
        if name in PROTECTED_PASSTHROUGH_FLAGS:
            offenders.append(name)
        elif token.startswith("-R") and len(token) > 2:
            offenders.append("-R")
    return offenders


def pr_ref_repo(pr_ref: str) -> str | None:
    """The owner/repo a PR reference names, when it names one at all.

    A bare number or a branch-default reference targets the checkout's repo and returns None. A
    full URL carries its own repo, which is how a cross-repo merge can arrive with `--repo` unset
    -- so the caller must consult this before deciding that fail-open is safe.
    """
    match = _PR_URL.match(pr_ref.strip())
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


# A version token is a release CLAIM, not any three-dotted number that happens to appear. Two
# positions only, and the restriction is measured rather than guessed (backlog item 63):
#
#   `(0.38.0)` / `(0.38.3, item 58)` -- immediately after `(`, delimited by `)` or `,`
#   `(item 32, 0.29.0)`              -- immediately before `)`, after a comma and optional space
#
# Prose position is deliberately EXCLUDED, and that exclusion is the whole reason this is a regex
# and not `\d+\.\d+\.\d+`. Across all 364 commits that touch VERSION, a permissive "a version
# anywhere inside parentheses" rule flags two CORRECT commits that cite a prior release as
# explanation --
#
#   Release 0.6.115: restore per-product adapters (0.6.114 productization broke lane startup)
#   Release 0.6.94 - resolve remaining open methodology-RCA backlog (incl. ... 0.6.91 ...)
#
# -- whose VERSION is 0.6.115 and 0.6.94, each correctly named in the subject's own prefix. This
# rule covers 37 subjects with 0 false positives; the permissive one covers 39 with 2. Refusing a
# truthful title is the worst failure available to this guard, so tolerance was measured and
# rejected, not merely left untried.
_SUBJECT_VERSION = re.compile(r"\((\d+\.\d+\.\d+)(?=[),])|,\s*(\d+\.\d+\.\d+)\)")

# gh's subject override, every spelling it accepts. `-t` is load-bearing: a long-form-only check is
# bypassed by the shorter form a human is likelier to type.
_SUBJECT_FLAGS = frozenset({"--subject", "-t"})

# Strategies whose final subject does NOT come from the PR title: `--merge` synthesizes
# "Merge pull request #N from ...", `--rebase` preserves each commit's own subject.
_NON_SQUASH_FLAGS = frozenset({"--merge", "-m", "--rebase", "-r"})


def subject_version_tokens(subject: str) -> list[str]:
    """Release-version claims in a commit subject or PR title, in order, deduplicated.

    THE INVARIANT IS CONDITIONAL: if a subject carries a token it must equal `VERSION` at that
    commit; carrying none is always legal. 327 of the 364 VERSION-touching commits carry no token
    and are not defective -- mostly `chore(review):` ledgers and mid-branch bumps that have no
    business advertising a release -- so a rule requiring a token would flag 327 correct commits.

    Two consumers share this one function ON PURPOSE: the merge-time guard in `merge_command` and
    the history test in `tests/test_release_tracks_and_migrations.py`. A second copy of the rule
    would let the preventer and the detector disagree about what a version token is, which is the
    same drift class this whole feature exists to close.

    Deduplicated because the caller compares a set against one VERSION and a repeated token would
    otherwise name the same version twice in one refusal.
    """
    seen: list[str] = []
    for head, tail in _SUBJECT_VERSION.findall(subject or ""):
        token = head or tail
        if token and token not in seen:
            seen.append(token)
    return seen


# `gh pr merge` flags that CONSUME the following token. Their operand can itself look like a flag,
# and a scanner that does not consume it will read that operand as a flag of its own -- which is a
# bypass, not a cosmetic bug (Codex R1 P2): `--body -tignored --squash` is body text plus a squash
# that still takes its subject from the PR title, and `--body --merge --squash` likewise squashes.
# Reading either literally disarms the guard on exactly the case it exists to catch.
_GH_MERGE_VALUE_FLAGS = frozenset(
    {
        "--body", "-b",
        "--body-file", "-F",
        "--author-email", "-A",
        "--subject", "-t",
        "--match-head-commit",
        "--repo", "-R",
    }
)

# The short spellings among the above, for the attached form (`-tfoo`, `-bfoo`).
_GH_SHORT_VALUE_FLAGS = frozenset({"-b", "-F", "-A", "-t", "-R"})


def merge_passthrough_flags(passthrough: list[str]) -> list[tuple[str, str | None]]:
    """(name, value) for each gh flag in `passthrough`, with value operands consumed.

    The consuming is the entire point. Every spelling gh accepts is handled -- `--flag value`,
    `--flag=value`, `-fvalue` and `-f value` -- so that an operand which happens to look like a
    flag is never counted as one.

    KNOWN LIMIT, and it fails in the safe direction: combined boolean shorthand (`-md` for
    `--merge --delete-branch`) is not decomposed, so `-m` inside it is not seen as a strategy. That
    makes the guard CHECK a merge it could have skipped -- a possible unnecessary refusal, fixed by
    one `gh pr edit` -- rather than skip one it should have checked, which would be a bypass. The
    same asymmetry drives the ambiguous-strategy default in `non_squash_strategy_in`.
    """
    flags: list[tuple[str, str | None]] = []
    index = 0
    while index < len(passthrough):
        token = passthrough[index]
        index += 1
        if not token.startswith("-") or token == "-":
            continue  # a positional operand, not a flag
        name, separator, attached = token.partition("=")
        if separator and name in _GH_MERGE_VALUE_FLAGS:
            flags.append((name, attached))
            continue
        if not token.startswith("--") and len(token) > 2 and token[:2] in _GH_SHORT_VALUE_FLAGS:
            flags.append((token[:2], token[2:]))
            continue
        if name in _GH_MERGE_VALUE_FLAGS:
            value = None
            if index < len(passthrough):
                value = passthrough[index]
                index += 1
            flags.append((name, value))
            continue
        flags.append((name, None))
    return flags


def subject_override_in(passthrough: list[str]) -> str | None:
    """The value of gh's `--subject`, or None when the caller did not override the subject.

    `gh pr merge -t/--subject` sets the resulting commit subject DIRECTLY, so a guard that reads
    only the PR title has a documented bypass: `tautline merge 12 --squash --subject 'feat (9.9.9)'`
    ships that subject however correct the title is. All four spellings gh accepts are recognised
    here for the same reason `protected_passthrough` recognises all four of `-R`'s: a guard that
    closes one spelling closes nothing.

    Returns the LAST occurrence, matching gh's own last-wins flag handling -- a guard that read the
    first would check a value the merge does not use.
    """
    found: str | None = None
    for name, value in merge_passthrough_flags(passthrough):
        if name in _SUBJECT_FLAGS:
            found = value
    return found


def non_squash_strategy_in(passthrough: list[str]) -> bool:
    """Whether an explicit strategy is present whose subject cannot come from the PR title.

    Deliberately "is a non-squash strategy present", NOT "is --squash absent". With no strategy
    flag the effective strategy is the REPOSITORY's default -- server-side state this command does
    not read -- so treating that ambiguity as non-squash would disarm the guard for every bare
    `tautline merge`, a spelling this repo's own tests exercise. The ambiguous case therefore
    checks: being wrong there costs one `gh pr edit`, while the opposite default costs a permanent
    published lie.
    """
    return any(name in _NON_SQUASH_FLAGS for name, _ in merge_passthrough_flags(passthrough))


def split_merge_arguments(rest: list[str]) -> tuple[str, list[str]]:
    """Separate an optional leading PR reference from the flags forwarded to `gh pr merge`.

    `argparse.REMAINDER` on a single positional is what makes `tautline merge --squash` work at
    all: with a separate optional `pr` positional, argparse rejects a bare flag as unknown before
    the current-branch default can apply.
    """
    tokens = list(rest or [])
    # `argparse.REMAINDER` hands back the `--` separator itself. Forwarding it would make gh stop
    # option parsing and read `--squash` as a positional, so the merge would use the default
    # strategy instead of the requested one. Dropped in BOTH conventional positions -- before the
    # PR reference and after it -- because the verb's own refusal text suggests the second shape.
    if tokens and tokens[0] == "--":
        tokens = tokens[1:]
    pr_ref = ""
    if tokens and not tokens[0].startswith("-"):
        pr_ref, tokens = tokens[0], tokens[1:]
    if tokens and tokens[0] == "--":
        tokens = tokens[1:]
    return pr_ref, tokens
