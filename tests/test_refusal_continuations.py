"""No dead ends on the review/gate surface (item 48, WS3).

0.9.1 shipped "no dead ends at launch": a gate that refuses must print an exact executable remedy.
The principle was never applied to the *review* surface, and the cost was measured. `codex-run`
refused a round with `"exceeds adapter budget {budget} for {risk_tier}; split/defer/escalate
instead of spending more Codex rounds on this PR."` -- a refusal that named no command, and whose
one named exit ("escalate") is an instruction to wake a human. On 2026-07-30 that message stopped
four development lanes overnight and cost ~30 hours, because the only valid answer to the question
it forced was "take the round", which the code would not let the lane do.

So the invariant gets a test instead of a doctrine. Three checks, in descending breadth:

1. `test_no_review_refusal_instructs_a_human_handoff` -- NO refusal on this surface may tell an
   agent to escalate, ask, or wait for a person. Broadest scope, near-empty allowlist. This is the
   one that pins the defect above.
2. `test_policy_refusals_carry_a_continuation` -- a refusal that denies an action on POLICY grounds
   (budget, cap, evidence state, authority) must name what to do instead: a runnable invocation, a
   flag, an adapter key, or a named autonomous action.
3. `test_commands_named_in_refusals_are_runnable` -- and the command it names must actually exist
   with the flags it shows. A remedy that dies with "unrecognized argument" is a dead end wearing a
   remedy's clothes; `implementation_review_round_cap_errors` shipped one (`validate-adapter
   --target .`, which takes `--project`) in this very item's first draft.

## Why an AST walk

`cli.py` is ~53k lines. A text grep for refusal-shaped strings drowns in prose, docstrings, and the
release-migration report bodies, and a grep that is 90% false positives gets an allowlist that is
90% noise, which is a test nobody reads. The walk instead collects exactly two things:

* strings whose head is one of `REVIEW_GATE_PREFIXES` -- the `key_error:` stderr convention this
  codebase uses for every refusal on the review/gate boundary; and
* the returns of the named pure refusal builders, whose strings carry no prefix because the caller
  adds it.

## What this does NOT cover, stated so nobody reads a green here as more than it is

* Refusals raised as `SystemExit("...")` rather than printed with a `<verb>_error:` prefix. The
  review/gate boundary uses the printed convention throughout; adapter and schema validation uses
  `SystemExit`, and that is a different surface with a different audience.
* Text assembled at runtime from a variable. A message whose remedy is computed (`finalizable_command`
  is the live example) can only be seen here as `{}`; those are allowlisted with a pointer to the
  runtime test that does cover them.
* Whether a named continuation actually *unblocks the lane*. Check 3 proves the command exists and
  accepts the flags shown. Proving the remedy works is the job of that gate's own tests.

## Why the allowlist is the honest part

The goal is "every dead end is a deliberate, named decision", not "zero dead ends", which would be a
lie the test enforces. Every allowlist entry carries a reason, in this file, and an entry with an
empty reason fails the suite (`test_allowlist_entries_carry_a_reason`). A non-vacuity guard
(`test_the_walk_finds_refusals`) fails if the collection ever silently stops finding anything --
the failure mode of every static check of this shape.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Item 70 T2.1: the runnable-command check and the allowlist-with-reason discipline live in a
# shared module so the launch/trust refusal surface applies the SAME one rather than a second,
# drifting copy. Refactor only -- this file's checks, prefixes and allowlist entries are unchanged.
from refusal_continuations_common import (  # noqa: E402
    FLAG,
    INVOCATION,
    accepted_flags,
    allowlisted,
    cli_verbs,
    named_invocations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
CLI = REPO_ROOT / "bin" / "tautline"

# The stderr prefixes that mark a refusal on the review/gate boundary. Each is the `<verb>_error:`
# convention already used by that command, so this list grows the same way the surface does.
REVIEW_GATE_PREFIXES = (
    "codex_run_error:",
    # Item 69 COVERAGE EXTENSION, deliberate: the render-adapters downgrade refusal names
    # `--allow-template-downgrade` as its continuation, and this walk is the only thing that
    # proves a named continuation is a real, runnable command. Without the prefix in this
    # inventory the walk never sees the message and "the suite is green" would be true whatever
    # the message said. test_the_walk_finds_refusals pins the resulting count rise.
    "render_adapters_error:",
    # Item 68 PR2 COVERAGE EXTENSION, deliberate: the occupancy gate's refusal names a runnable
    # `git worktree add` as its continuation, and this walk is the only thing that proves a named
    # continuation is real rather than advice. Without these prefixes the walk never sees the
    # messages, and "the suite is green" would be true whatever they said. The floor in
    # test_the_walk_finds_refusals rises by the measured count below.
    "occupancy_conflict:",
    "occupancy_instruction:",
    "occupancy_autoplaced:",
    "occupancy_primary_checkout:",
    "codex_plan_review_error:",
    "plan_review_run_error:",
    "plan_review_record_error:",
    "plan_review_convergence_error:",
    "plan_review_write_error:",
    "claude_review_error:",
    "claude_review_packet_error:",
    "implementation_review_finalize_error:",
)

# Pure functions that BUILD refusal strings for a caller to prefix and print. Their returns are the
# policy core of the surface -- the round ladders -- so they are walked by name.
REFUSAL_BUILDERS = {
    # Item 69: both render paths print this builder's return behind their own prefix, so the
    # message -- and the `--allow-template-downgrade` continuation it names -- is only reachable
    # by name. Without this entry the print sites read as passthroughs and the override would be
    # unchecked no matter what it said.
    "generated_downgrade_refusal",
    "plan_review_round_cap_errors",
    "plan_review_hard_cap_refusal",
    "implementation_review_round_cap_errors",
    # The in-flight lease refusal reaches stderr through the `plan_review_run_error: {}`
    # passthrough print, which `_is_passthrough` skips by construction, so the walk can only
    # see this message where it is BUILT.
    "plan_review_acquire_inflight_lease",
}


# --- Collection ---------------------------------------------------------------------------------


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so the walk can see through a constant.

    Extracting a shared invocation into a constant is the RIGHT fix when three refusals would
    otherwise carry three drifting copies of it -- but it also made this walk render the message as
    `{}` and report it as having no continuation. A checker that punishes the better structure
    trains people to write the worse one, so it resolves the constant instead.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            constants[target.id] = value.value
        elif isinstance(value, ast.JoinedStr):
            rendered = _render_joined(value, {})
            if rendered is not None:
                constants[target.id] = rendered
    return constants


def _render_joined(node: ast.JoinedStr, constants: dict[str, str]) -> str:
    parts = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            parts.append(constants.get(part.value.id, "{}"))
        else:
            parts.append("{}")
    return "".join(parts)


MODULE_CONSTANTS: dict[str, str] = {}


def _render(node: ast.AST) -> str | None:
    """A string node as a template, with every interpolation flattened to `{}`.

    Values are unknowable statically, so `f"round {n} exceeds {cap}"` renders as
    `round {} exceeds {}`. That is enough for every check here: they ask what the message SAYS, not
    what it says about a particular round.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return _render_joined(node, MODULE_CONSTANTS)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _render(node.left)
        right = _render(node.right)
        if left is None or right is None:
            return None
        return left + right
    return None


def _outermost(root: ast.AST, predicate) -> list[tuple[int, str]]:
    """Renderable string nodes matching `predicate`, WITHOUT descending into a match.

    Descending would re-report every fragment of an f-string as its own refusal, so a message that
    carries its remedy in one clause and its diagnosis in another would fail on the diagnosis half.
    """
    found: list[tuple[int, str]] = []
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        text = _render(node)
        if text is not None and predicate(text):
            found.append((getattr(node, "lineno", 0), text))
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


def _is_prefixed(text: str) -> bool:
    return any(text.lstrip().startswith(prefix) for prefix in REVIEW_GATE_PREFIXES)


def _collect() -> list[tuple[str, str]]:
    """(site, message) for every refusal on the review/gate surface. `site` is stable enough to
    allowlist against: `<prefix-or-builder>:<line>`."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    MODULE_CONSTANTS.clear()
    MODULE_CONSTANTS.update(_module_string_constants(tree))
    refusals: list[tuple[str, str]] = []

    for lineno, text in _outermost(tree, _is_prefixed):
        refusals.append((f"cli.py:{lineno}", text))

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in REFUSAL_BUILDERS:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or inner.value is None:
                continue
            # Docstrings and locals are skipped by construction: only `return` values are read, and
            # a returned fragment shorter than a sentence is a variable name, not a message.
            for lineno, text in _outermost(inner.value, lambda t: len(t.strip()) > 20):
                refusals.append((f"{node.name}:{lineno}", text))

    return sorted(set(refusals))


def _body(text: str) -> str:
    """The message with its `<verb>_error:` prefix removed."""
    if _is_prefixed(text):
        return text.split(":", 1)[1]
    return text


def _is_passthrough(text: str) -> bool:
    """A dispatcher, not a message: `print(f"plan_review_run_error: {error}")`.

    Its body is entirely interpolation, so it carries no words of its own to check. The text it
    forwards is built somewhere else and is collected there -- the round-ladder errors reach stderr
    through exactly this shape and are checked at `implementation_review_round_cap_errors`.
    """
    return not re.sub(r"[{}\s]", "", _body(text))


REFUSALS = _collect()
CHECKED = [(site, text) for site, text in REFUSALS if not _is_passthrough(text)]


# --- Check 1: no human handoff ------------------------------------------------------------------

# Phrases that hand the decision to a person. Deliberately narrow and literal: the check has to be
# something a reviewer can confirm by reading, not a sentiment classifier.
HUMAN_HANDOFF = re.compile(
    r"\b(?:escalate|escalation|escalating"
    r"|ask (?:the|an|your) operator"
    r"|ask (?:a|the) human"
    r"|consult (?:a|the) human|consult (?:the|an|your) operator"
    r"|contact (?:the )?maintainers?"
    r"|wait for (?:the|an) operator"
    r"|operator (?:approval|sign-?off) is required"
    r"|check with (?:the )?(?:operator|maintainer|a human))\b",
    re.I,
)

# A refusal is allowed to FORBID the handoff, and the good ones do -- `plan_review_hard_cap_refusal`
# ends with "do not ask the operator to choose a path". Without this, the test would fail exactly
# the messages that state the invariant it enforces.
NEGATED_HANDOFF = re.compile(r"(?:do not|don't|never|no|not an|instead of|rather than)\s+$", re.I)

# Allowlists are keyed by a DISTINCTIVE FRAGMENT of the message, not by a line number. Keying on
# `cli.py:<line>` was the first shape and it is a trap: any edit above the site silently re-points
# the entry at whatever moved onto that line, and every unrelated edit turns the suite red for a
# reason that has nothing to do with the change. A fragment moves with the message it excuses.
HUMAN_HANDOFF_ALLOWLIST: dict[str, str] = {
    # Empty on purpose, and it should stay that way. An operator-owned fork (scope, security,
    # spend) belongs in `decision-record --reversibility hard-to-reverse`, which keeps the lane
    # working while the question is queued -- not in a refusal that stops the lane dead. If a
    # genuine one appears, add it here WITH the reason it cannot be self-authorized.
}


_allowlisted = allowlisted


@pytest.mark.parametrize(("site", "text"), CHECKED, ids=lambda value: str(value)[:60])
def test_no_review_refusal_instructs_a_human_handoff(site: str, text: str) -> None:
    match = HUMAN_HANDOFF.search(text)
    while match and NEGATED_HANDOFF.search(text[max(0, match.start() - 24) : match.start()]):
        match = HUMAN_HANDOFF.search(text, match.end())
    if not match:
        return
    reason = _allowlisted(HUMAN_HANDOFF_ALLOWLIST, text)
    assert reason, (
        f"{site} refuses and tells the agent to {match.group(0)!r}:\n\n  {' '.join(text.split())}\n\n"
        "A refusal on the review/gate path may not hand the decision to a person. Give it a "
        "self-authorizing continuation instead (see implementation_review_round_cap_errors), or, "
        "if the fork is genuinely operator-owned, add it to HUMAN_HANDOFF_ALLOWLIST in this file "
        "with the reason it cannot be self-authorized."
    )


# --- Check 2: policy refusals carry a continuation ----------------------------------------------

# An input/artifact-validation refusal names the thing the caller supplied, and the fix is to supply
# it correctly. Those are exempt as a CATEGORY, not one at a time -- adding "run the command again"
# to `plan missing: <path>` is noise, not a continuation.
VALIDATION = re.compile(
    r"\b(?:missing|not found|cannot read|failed to read|failed to launch|is empty"
    r"|invalid|must be an array|is not shell-parseable|not under|must live under"
    r"|requires a value|is required|provided more than once|exited)\b",
    re.I,
)

# ...unless it also speaks policy, in which case it is policy. Ties go to policy on purpose: an
# unclassifiable refusal must land in the checked bucket, never in the exempt one.
POLICY = re.compile(
    r"\b(?:budget|cap|exceeds|past the|already finalized|does not use|cannot supply"
    r"|stop spending|self-authorized|authorization|not accepted|convergence target"
    r"|must match|must be codex|introduces)\b",
    re.I,
)

CONTINUATIONS = (
    # A runnable invocation.
    ("command", re.compile(r"\b(?:tautline|codex-run|codex|git|gh)\s+[a-z][a-z0-9-]{2,}")),
    # A bare framework verb, which resolves under `tautline` and under the plugin skills.
    (
        "verb",
        re.compile(
            r"\b(?:finalize-plan-review|plan-finalization-precheck|finalize-implementation-review"
            r"|record-stage1-sweep|run-plan-review|behavior-spec-status|self-review)\b"
        ),
    ),
    # A flag to pass: the lane fixes its own invocation.
    ("flag", re.compile(r"(?<![\w-])--[a-z][a-z0-9-]+")),
    # An adapter/config key to edit.
    ("config", re.compile(r"\b(?:adapter|review)\.[a-zA-Z][a-zA-Z0-9.]+")),
    # A named action a lane can take alone.
    (
        "action",
        re.compile(
            r"\b(?:decompose|split|rebase|rerun|re-run|retry|fetch|inspect the log|transfer"
            r"|route|routing)\b",
            re.I,
        ),
    ),
)

CONTINUATION_ALLOWLIST: dict[str, str] = {
    "an unfinalized successful run already matches the current plan content": (
        "The continuation IS present, but it is computed at runtime: the trailing interpolation is "
        "`finalizable_command`, the exact `finalize-plan-review` invocation for the unbound run "
        "that matches the current plan hash. A static walk can only ever see `{}` there. The "
        "runtime shape -- that the refusal carries a real, runnable command whenever one exists -- "
        "is asserted in tests/test_plan_review_runtime_guard.py, which pins both "
        "`finalize-plan-review` and its `--log` flag in the rendered message."
    ),
}


def _policy_refusals() -> list[tuple[str, str]]:
    return [
        (site, text)
        for site, text in CHECKED
        if POLICY.search(text) or not VALIDATION.search(text)
    ]


POLICY_REFUSALS = _policy_refusals()


@pytest.mark.parametrize(("site", "text"), POLICY_REFUSALS, ids=lambda value: str(value)[:60])
def test_policy_refusals_carry_a_continuation(site: str, text: str) -> None:
    if any(pattern.search(text) for _, pattern in CONTINUATIONS):
        return
    reason = _allowlisted(CONTINUATION_ALLOWLIST, text)
    assert reason, (
        f"{site} refuses on policy grounds and names nothing the lane can do next:\n\n"
        f"  {' '.join(text.split())}\n\n"
        "Add a runnable continuation (a `tautline`/`codex-run`/`git`/`gh` invocation, a flag to "
        "pass, an adapter key to set) or a named autonomous action the lane can take alone. If "
        "this refusal genuinely has no lane-side continuation, add it to CONTINUATION_ALLOWLIST "
        "in this file with a one-line reason."
    )


# --- Check 3: the continuation is actually runnable ---------------------------------------------

NAMED_INVOCATIONS = named_invocations(CHECKED)


def _required_flags(command: str) -> set[str]:
    """Flags argparse marks REQUIRED for a verb, read from its own usage line.

    Codex R4 P2: three refusals offered `finalize-implementation-review --verdict
    clean-with-deferrals` as the way out. That verb also requires `--manifest`,
    `--unresolved-critical-count`, and `--unresolved-p1-count`, so following the remedy landed on
    an argparse usage error. A no-dead-ends refusal that ends in a usage error is still a dead end;
    it only moves where the lane gets stuck.

    argparse prints required options UNBRACKETED in the usage block and optional ones inside
    `[...]`, so stripping the bracketed spans leaves exactly the required set.
    """
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    usage = result.stdout.split("\n\n", 1)[0]
    return set(FLAG.findall(re.sub(r"\[[^\[\]]*\]", " ", usage)))


CLI_VERBS = cli_verbs()
_accepted_flags = accepted_flags


# A framework verb shown as if it were an executable: `codex-run --allow-extra-rounds ...`.
# Every one of these is a `tautline` SUBCOMMAND, so pasting it gets "command not found" -- a dead
# end wearing a remedy's clothes. Check 3 missed this class entirely, because its INVOCATION regex
# anchors on the literal `tautline`; Codex R2 P2 found it in the ladder's own refusal, which is
# about as pointed as a review finding gets.
BARE_VERB = re.compile(r"(?<![\w/-])([a-z][a-z0-9-]{3,})(?=\s+--)")

BARE_VERB_ALLOWLIST: dict[str, str] = {
    # Empty on purpose. A verb named in a refusal is being offered as a next step; write it the way
    # the lane must type it. If a message genuinely needs to discuss a verb rather than offer it,
    # say so in prose ("the finalize-implementation-review verb") instead of command shape.
}


def _bare_verbs() -> list[tuple[str, str, str]]:
    found = []
    for site, text in CHECKED:
        for match in BARE_VERB.finditer(text):
            verb = match.group(1)
            if verb not in CLI_VERBS:
                continue
            if text[max(0, match.start() - 10) : match.start()].rstrip().endswith("tautline"):
                continue
            found.append((site, verb, text))
    return found


BARE_VERBS = _bare_verbs()


@pytest.mark.parametrize(
    ("site", "verb", "text"), BARE_VERBS, ids=lambda value: str(value)[:60]
)
def test_refusals_never_show_a_framework_verb_as_a_bare_command(
    site: str, verb: str, text: str
) -> None:
    reason = _allowlisted(BARE_VERB_ALLOWLIST, text)
    assert reason, (
        f"{site} offers `{verb} ...` as the way forward, but {verb!r} is a `tautline` subcommand, "
        f"not an executable. Pasting it gets 'command not found'.\n\n  {' '.join(text.split())}\n\n"
        f"Write it as `tautline {verb} ...`, including any arguments the verb refuses without."
    )


@pytest.mark.parametrize(
    ("command", "flag"), sorted(NAMED_INVOCATIONS), ids=lambda value: str(value)
)
def test_commands_named_in_refusals_are_runnable(command: str, flag: str) -> None:
    accepted = _accepted_flags(command)
    where = ", ".join(sorted(set(NAMED_INVOCATIONS[(command, flag)])))
    assert accepted, (
        f"{where} refuses and points the lane at `tautline {command}`, which is not a CLI "
        "subcommand. The remedy dies with 'invalid choice'. Name a real verb."
    )
    assert flag in accepted, (
        f"{where} refuses and points the lane at `tautline {command} {flag}`, but that command "
        f"does not accept {flag} (it accepts {', '.join(sorted(accepted))}). The remedy dies with "
        "'unrecognized argument', which is a dead end with extra steps."
    )


INVOCATION_COMMANDS = sorted({command for command, _flag in NAMED_INVOCATIONS})

REQUIRED_FLAG_ALLOWLIST: dict[str, str] = {
    # Empty on purpose. If a refusal wants to name a verb without offering a complete invocation,
    # write it as prose ("bind the evidence with finalize-implementation-review") rather than as a
    # command line -- backticks are a promise that the thing inside them runs.
}


@pytest.mark.parametrize("command", INVOCATION_COMMANDS, ids=lambda value: str(value))
def test_a_named_remedy_carries_the_verbs_required_arguments(command: str) -> None:
    """An invocation shown in a refusal must be complete enough to actually execute."""
    required = _required_flags(command)
    if not required:
        return
    for site, text in CHECKED:
        for shown_command, tail in INVOCATION.findall(text):
            if shown_command != command:
                continue
            shown = set(FLAG.findall(tail))
            missing = sorted(required - shown)
            if not missing:
                continue
            reason = _allowlisted(REQUIRED_FLAG_ALLOWLIST, text)
            assert reason, (
                f"{site} offers `tautline {command} …` as the way forward, but omits "
                f"{', '.join(missing)}, which {command} REQUIRES. Following the remedy exits with "
                f"an argparse usage error.\n\n  {' '.join(text.split())}\n\n"
                "Show the full invocation, with placeholders for values the message cannot know."
            )


# --- Guards on the test itself ------------------------------------------------------------------


def test_the_walk_finds_refusals() -> None:
    """A static collector that silently stops matching passes every other test in this file."""
    # Raised 40 -> 47 with item 69: the walk found 46 before that item and 48 after it added the
    # render_adapters_error: prefix plus the codex-run adapter-dirt refusal. A ratchet that never
    # moves cannot tell "a prefix was renamed" from "coverage was added".
    #
    # Raised 47 -> 55 with item 68 PR2: MEASURED 48 before the occupancy prefixes and 56 after, so
    # the four occupancy_* prefixes brought 8 messages onto this surface. The floor moves by the
    # measured delta and no further -- a floor set above what was counted is a ratchet that fails
    # the next honest change, and one set below it is a ratchet that has stopped ratcheting.
    assert len(CHECKED) >= 55, (
        f"the refusal walk found only {len(CHECKED)} messages on the review/gate surface; it used "
        "to find 48+. Either a prefix in REVIEW_GATE_PREFIXES was renamed, or the emit shape "
        "changed. Fix the walk before trusting the greens above."
    )
    assert len(POLICY_REFUSALS) >= 20, (
        f"only {len(POLICY_REFUSALS)} refusals classified as policy; the continuation check is "
        "close to vacuous. Check whether VALIDATION grew a pattern that swallows policy refusals."
    )
    assert NAMED_INVOCATIONS, "no refusal names a `tautline` invocation; check 3 is vacuous"
    assert len(CLI_VERBS) > 50, (
        f"only {len(CLI_VERBS)} CLI verbs parsed from `tautline --help`; the bare-verb check "
        "cannot recognise a subcommand it does not know about, so it would pass silently"
    )


@pytest.mark.parametrize(
    "allowlist",
    [HUMAN_HANDOFF_ALLOWLIST, CONTINUATION_ALLOWLIST, BARE_VERB_ALLOWLIST],
    ids=["human-handoff", "continuation", "bare-verb"],
)
def test_every_allowlist_is_reason_bearing(allowlist: dict[str, str]) -> None:
    for site, reason in allowlist.items():
        assert len(reason.strip()) >= 40, f"allowlist entry {site!r} has no substantive reason"


@pytest.mark.parametrize(
    "allowlist",
    [HUMAN_HANDOFF_ALLOWLIST, CONTINUATION_ALLOWLIST],
    ids=["human-handoff", "continuation"],
)
def test_allowlist_entries_carry_a_reason(allowlist: dict[str, str]) -> None:
    """A dead end is allowed to exist only as a deliberate, named decision."""
    for site, reason in allowlist.items():
        assert len(reason.strip()) >= 40, (
            f"allowlist entry {site!r} has no substantive reason. An allowlist without reasons is "
            "a suppression list; write why this refusal has no lane-side continuation."
        )


def test_allowlist_entries_still_match_a_refusal() -> None:
    """An entry that no longer matches anything is a stale suppression waiting to excuse something
    it was never written for."""
    for allowlist in (HUMAN_HANDOFF_ALLOWLIST, CONTINUATION_ALLOWLIST):
        for fragment in allowlist:
            assert any(fragment in text for _, text in REFUSALS), (
                f"allowlist fragment {fragment!r} matches no refusal on the review/gate surface "
                "any more. The message it excused was reworded or removed: delete the entry, or "
                "re-point it at the current wording."
            )
