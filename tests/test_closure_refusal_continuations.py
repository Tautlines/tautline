"""Item 81 T3.1: no dead ends on the CLOSURE surface.

`tests/test_refusal_continuations.py` walks the review/gate surface: string literals in `cli.py`
under nine `<verb>_error:` prefixes, plus three named refusal builders. This item's refusals live in
`backlog.py`, carry two new prefixes, and would be invisible to it -- so the item-48 no-dead-ends
guarantee would simply not extend to the boundary where work is declared done.

**A DISJOINT SECOND WALK, not an extension of the first** (packet fork F1). The shipped walk's
`CHECKED >= 47` / `POLICY_REFUSALS >= 20` floors and its three allowlists keep their exact current
meaning, and that file is untouched -- other lanes are working in it. What is shared is the part
that must never fork: the runnable-command check, the invocation/flag parsing, and the
allowlist-carries-a-reason discipline all come from `refusal_continuations_common`, the module item
70 PR-A extracted for precisely this situation. The AST rendering helpers are imported from the
sibling suite rather than copied, so there is exactly one implementation of "render this string node
as a template" in the tree.

Two non-vacuity floors, because a static collector that silently stops matching passes every other
test in this file:

1. a measured minimum refusal count, and
2. **a floor per declared SOURCE** -- an emptied scope must read as `unavailable`, never as zero
   findings. That is the shape that let a behaviour-spec path filter silently disable the gates it
   was selecting for while every assertion stayed green.

The sibling canon item (`canon-vs-executed-conformance`) adds its `canon_conformance_error:` prefix
and `core/runtime.py` to the declared sources in ITS PR, not this one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from refusal_continuations_common import (  # noqa: E402
    FLAG,
    INVOCATION,
    accepted_flags,
    allowlisted,
    cli_verbs,
    named_invocations,
)

# Imported, never copied. These three are the AST rendering machinery the sibling suite already
# owns; re-implementing them here is how two walks start disagreeing about what a refusal SAYS.
# `MODULE_CONSTANTS` is a module-global that `_render` reads, so this walk snapshots it, swaps in
# the constants of the file it is reading, and restores it -- the sibling's own collection has
# already run at its import and is unaffected, and the restore keeps it that way if it ever
# re-collects.
from test_refusal_continuations import (  # noqa: E402
    MODULE_CONSTANTS,
    _module_string_constants,
    _outermost,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "tautline_methodology"

# Both prefixes are NEW in this PR, so widening the file set past `cli.py` sweeps in nothing that
# was previously unchecked -- the sibling walk's counts are unmoved by this file existing.
CLOSURE_GATE_SOURCES = (PACKAGE / "cli.py", PACKAGE / "backlog.py")

CLOSURE_GATE_PREFIXES = ("done_evidence_ac_error:", "done_evidence_ac_warning:")

# The pure function that BUILDS the closure refusals for callers to print or raise. Unlike the
# sibling's builders it accumulates into a list rather than returning each message, so this walk
# reads every renderable string in the function body, not only `return` values. Same intent: the
# policy core of the surface is walked BY NAME, so it stays checked wherever it is printed from.
CLOSURE_REFUSAL_BUILDERS = {"done_evidence_ac_table_issues"}


def _is_prefixed(text: str) -> bool:
    return any(text.lstrip().startswith(prefix) for prefix in CLOSURE_GATE_PREFIXES)


def _collect() -> list[tuple[str, str]]:
    """(site, message) for every closure refusal; site is `<file-or-builder>:<line>`."""
    saved = dict(MODULE_CONSTANTS)
    refusals: list[tuple[str, str]] = []
    try:
        for source in CLOSURE_GATE_SOURCES:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            MODULE_CONSTANTS.clear()
            MODULE_CONSTANTS.update(_module_string_constants(tree))

            for lineno, text in _outermost(tree, _is_prefixed):
                refusals.append((f"{source.name}:{lineno}", text))

            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in CLOSURE_REFUSAL_BUILDERS:
                    continue
                # The docstring is skipped EXPLICITLY. The sibling walk reads only `return` values,
                # so it excludes docstrings by construction; this walk reads the whole body (the
                # builder accumulates into a list rather than returning each message), and without
                # this the function's own docstring is collected as a refusal with no continuation.
                body = node.body
                first = body[0] if body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    body = body[1:]
                for statement in body:
                    for lineno, text in _outermost(statement, lambda t: len(t.strip()) > 20):
                        refusals.append((f"{node.name}:{lineno}", text))
    finally:
        MODULE_CONSTANTS.clear()
        MODULE_CONSTANTS.update(saved)
    return sorted(set(refusals))


def _body(text: str) -> str:
    return text.split(":", 1)[1] if _is_prefixed(text) else text


def _is_passthrough(text: str) -> bool:
    """A dispatcher, not a message: `print(f"done_evidence_ac_warning: {message}")`. Its body is
    entirely interpolation, so it carries no words of its own; the text it forwards is built in
    `done_evidence_ac_table_issues` and is checked there, by name."""
    return not re.sub(r"[{}\s]", "", _body(text))


CLOSURE_REFUSALS = _collect()
CLOSURE_CHECKED = [(site, text) for site, text in CLOSURE_REFUSALS if not _is_passthrough(text)]


# --- Check 1: no human handoff --------------------------------------------------------------------

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

CLOSURE_HUMAN_HANDOFF_ALLOWLIST: dict[str, str] = {
    # Empty on purpose. A closure refusal that tells the agent to go ask someone is the failure the
    # source RCA is about: a human DID catch #357, by reading the AC lines, and the whole point of
    # this gate is that the catch stops depending on that.
}


@pytest.mark.parametrize(("site", "text"), CLOSURE_CHECKED, ids=lambda value: str(value)[:60])
def test_no_closure_refusal_instructs_a_human_handoff(site: str, text: str) -> None:
    match = HUMAN_HANDOFF.search(text)
    if not match:
        return
    reason = allowlisted(CLOSURE_HUMAN_HANDOFF_ALLOWLIST, text)
    assert reason, (
        f"{site} refuses a closure and tells the agent to {match.group(0)!r}:\n\n"
        f"  {' '.join(text.split())}\n\n"
        "Give it a self-authorizing continuation instead (`tautline ac-verify` plus a flag that "
        "exists on the refused path), or add it to CLOSURE_HUMAN_HANDOFF_ALLOWLIST with the reason "
        "it cannot be self-authorized."
    )


# --- Check 2: every closure refusal carries a continuation ----------------------------------------

CONTINUATIONS = (
    ("command", re.compile(r"\b(?:tautline|codex-run|codex|git|gh)\s+[a-z][a-z0-9-]{2,}")),
    ("flag", re.compile(r"(?<![\w-])--[a-z][a-z0-9-]+")),
    ("config", re.compile(r"\b(?:adapter|backlogProvider)\.[a-zA-Z][a-zA-Z0-9.]+")),
    ("action", re.compile(r"\b(?:re-?run|re-?verify|retry|fix the implementation)\b", re.I)),
)

CLOSURE_CONTINUATION_ALLOWLIST: dict[str, str] = {
    # Empty on purpose. Unlike the review surface, this one has no validation-refusal CATEGORY to
    # exempt: every message here refuses a state transition on POLICY grounds, so every one of them
    # owes the lane a way forward.
}


@pytest.mark.parametrize(("site", "text"), CLOSURE_CHECKED, ids=lambda value: str(value)[:60])
def test_every_closure_refusal_carries_a_continuation(site: str, text: str) -> None:
    if any(pattern.search(text) for _, pattern in CONTINUATIONS):
        return
    reason = allowlisted(CLOSURE_CONTINUATION_ALLOWLIST, text)
    assert reason, (
        f"{site} refuses a closure and names nothing the lane can do next:\n\n"
        f"  {' '.join(text.split())}\n\n"
        "Every message on this surface refuses a state transition on policy grounds, so every one "
        "owes a runnable continuation."
    )


# --- Check 3: the continuation is actually runnable -----------------------------------------------

CLOSURE_NAMED_INVOCATIONS = named_invocations(CLOSURE_CHECKED)
CLI_VERBS = cli_verbs()

BARE_VERB = re.compile(r"(?<![\w/-])([a-z][a-z0-9-]{3,})(?=\s+--)")

CLOSURE_BARE_VERB_ALLOWLIST: dict[str, str] = {
    # Empty on purpose, same as the sibling surface: a verb named in a refusal is being OFFERED, so
    # write it the way the lane must type it.
}


@pytest.mark.parametrize(
    ("command", "flag"), sorted(CLOSURE_NAMED_INVOCATIONS), ids=lambda value: str(value)
)
def test_commands_named_in_closure_refusals_are_runnable(command: str, flag: str) -> None:
    accepted = accepted_flags(command)
    where = ", ".join(sorted(set(CLOSURE_NAMED_INVOCATIONS[(command, flag)])))
    assert accepted, (
        f"{where} refuses a closure and points the lane at `tautline {command}`, which is not a "
        "CLI subcommand. The remedy dies with 'invalid choice'."
    )
    assert flag in accepted, (
        f"{where} refuses a closure and points the lane at `tautline {command} {flag}`, but that "
        f"command does not accept {flag} (it accepts {', '.join(sorted(accepted))})."
    )


def _closure_bare_verbs() -> list[tuple[str, str, str]]:
    found = []
    for site, text in CLOSURE_CHECKED:
        for match in BARE_VERB.finditer(text):
            verb = match.group(1)
            if verb not in CLI_VERBS:
                continue
            if text[max(0, match.start() - 10) : match.start()].rstrip().endswith("tautline"):
                continue
            found.append((site, verb, text))
    return found


CLOSURE_BARE_VERBS = _closure_bare_verbs()


@pytest.mark.parametrize(
    ("site", "verb", "text"), CLOSURE_BARE_VERBS, ids=lambda value: str(value)[:60]
)
def test_closure_refusals_never_show_a_framework_verb_as_a_bare_command(
    site: str, verb: str, text: str
) -> None:
    reason = allowlisted(CLOSURE_BARE_VERB_ALLOWLIST, text)
    assert reason, (
        f"{site} offers `{verb} ...` as the way forward, but {verb!r} is a `tautline` subcommand, "
        f"not an executable. Write it as `tautline {verb} ...`.\n\n  {' '.join(text.split())}"
    )


CLOSURE_INVOCATION_COMMANDS = sorted({command for command, _flag in CLOSURE_NAMED_INVOCATIONS})


@pytest.mark.parametrize("command", CLOSURE_INVOCATION_COMMANDS, ids=lambda value: str(value))
def test_a_named_closure_remedy_carries_the_verbs_required_arguments(command: str) -> None:
    """An invocation shown in a refusal must be complete enough to actually execute: a remedy that
    ends in an argparse usage error only moves where the lane gets stuck."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), command, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    usage = result.stdout.split("\n\n", 1)[0]
    required = set(FLAG.findall(re.sub(r"\[[^\[\]]*\]", " ", usage)))
    if not required:
        return
    for site, text in CLOSURE_CHECKED:
        for shown_command, tail in INVOCATION.findall(text):
            if shown_command != command:
                continue
            missing = sorted(required - set(FLAG.findall(tail)))
            assert not missing, (
                f"{site} offers `tautline {command} …` but omits {', '.join(missing)}, which "
                f"{command} REQUIRES.\n\n  {' '.join(text.split())}"
            )


# --- Guards on the walk itself --------------------------------------------------------------------


def test_the_closure_walk_finds_refusals() -> None:
    """Measured on this branch, not guessed (re-measured 2026-08-11 after the WS1 split): 13
    collected, 11 substantive. The two non-substantive ones are the
    `print(f"done_evidence_ac_warning: {message}")` dispatchers, whose forwarded text is checked at
    the builder -- and keeping them dispatchers is deliberate: a template like
    `done_evidence_ac_warning: {}: {}` would count as a refusal of its own, with a body of pure
    interpolation and therefore no continuation, failing the very check this file exists to run.
    The milestone `acVerification` path refusal lands in the follow-on release and takes these to
    14/12; ratchet then, do not pre-raise. A ratchet that never moves cannot tell "a prefix was
    renamed" from "coverage was added"."""
    assert len(CLOSURE_REFUSALS) >= 13, (
        f"the closure walk found only {len(CLOSURE_REFUSALS)} refusals; it used to find 13. Either "
        "a prefix in CLOSURE_GATE_PREFIXES was renamed or the emit shape changed. Fix the walk "
        "before trusting the greens above."
    )
    assert len(CLOSURE_CHECKED) >= 11, (
        f"only {len(CLOSURE_CHECKED)} substantive closure refusals; the continuation check is "
        "close to vacuous. Check whether the messages became pure passthroughs."
    )
    assert CLOSURE_NAMED_INVOCATIONS, (
        "no closure refusal names a `tautline` invocation; check 3 is vacuous"
    )
    assert len(CLI_VERBS) > 50, (
        f"only {len(CLI_VERBS)} CLI verbs parsed from `tautline --help`; the bare-verb check "
        "cannot recognise a subcommand it does not know about, so it would pass silently"
    )


def test_every_declared_source_contributes_at_least_one_refusal() -> None:
    """The floor the CLAIMS.md lesson asks for: an emptied scope must read as UNAVAILABLE, never as
    zero findings. Without this, deleting `backlog.py` from CLOSURE_GATE_SOURCES -- or moving the
    builder out of it -- leaves every test in this file green while the walk sees nothing."""
    for source in CLOSURE_GATE_SOURCES:
        assert source.is_file(), f"declared closure source is missing: {source}"
        contributed = [site for site, _text in CLOSURE_REFUSALS if site.startswith(source.name)]
        assert contributed, (
            f"{source.name} is declared in CLOSURE_GATE_SOURCES but contributed no refusal. A "
            "scope that selects nothing is unavailable, not clean -- either the refusals moved out "
            "of this file or the prefixes changed."
        )


def test_the_named_builder_exists_and_is_where_the_walk_looks() -> None:
    """`CLOSURE_REFUSAL_BUILDERS` is matched by NAME against the AST. A renamed or relocated builder
    would silently contribute nothing, which is the same false-clean this whole item is about."""
    tree = ast.parse((PACKAGE / "backlog.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert CLOSURE_REFUSAL_BUILDERS <= defined, (
        f"{sorted(CLOSURE_REFUSAL_BUILDERS - defined)} is walked by name but is not defined in "
        "backlog.py any more."
    )
    for builder in CLOSURE_REFUSAL_BUILDERS:
        assert any(site.startswith(f"{builder}:") for site, _text in CLOSURE_REFUSALS), (
            f"{builder} is declared as a refusal builder but the walk read no message out of it"
        )


@pytest.mark.parametrize(
    "allowlist",
    [CLOSURE_HUMAN_HANDOFF_ALLOWLIST, CLOSURE_CONTINUATION_ALLOWLIST, CLOSURE_BARE_VERB_ALLOWLIST],
    ids=["human-handoff", "continuation", "bare-verb"],
)
def test_every_closure_allowlist_is_reason_bearing(allowlist: dict[str, str]) -> None:
    """An allowlist without reasons is a suppression list."""
    for fragment, reason in allowlist.items():
        assert len(reason.strip()) >= 40, f"allowlist entry {fragment!r} has no substantive reason"


def test_closure_allowlist_entries_still_match_a_refusal() -> None:
    """An entry that no longer matches anything is a stale suppression waiting to excuse
    something it was never written for."""
    for allowlist in (
        CLOSURE_HUMAN_HANDOFF_ALLOWLIST,
        CLOSURE_CONTINUATION_ALLOWLIST,
        CLOSURE_BARE_VERB_ALLOWLIST,
    ):
        for fragment in allowlist:
            assert any(fragment in text for _, text in CLOSURE_REFUSALS), (
                f"allowlist fragment {fragment!r} matches no closure refusal any more"
            )


def test_the_sibling_review_walk_is_untouched_by_this_one() -> None:
    """The two walks are disjoint by construction, and this proves it rather than asserting it in a
    comment: no message this walk collects appears in the sibling's corpus, so the sibling's
    `CHECKED >= 47` floor still measures exactly what it measured before this file existed."""
    from test_refusal_continuations import REFUSALS as REVIEW_REFUSALS

    overlap = {text for _site, text in CLOSURE_REFUSALS} & {text for _site, text in REVIEW_REFUSALS}
    assert not overlap, f"the two walks collect the same message: {sorted(overlap)[:2]}"
