"""Goal-Assignment Standard: the assignable goal a finalized plan hands to the builder lane.

Pure leaf module (no cli imports) so the composer + checker are unit-testable in
isolation and only thin wiring touches the cli.py monolith -- the same shape as
plan_authoring.py.

The cap is a HOST limit, not a style preference. The Claude Code harness refuses a
goal prompt longer than GOAL_ASSIGNMENT_CHAR_LIMIT characters, so a goal over it
cannot be assigned at all: the operator finds out only at paste time, after the
planning session that produced it is gone. Telling an author "keep it short" has
repeatedly failed to hold, so composition BUDGETS instead of trusting a count, and
the checker fails closed.

Budgeting is explicit, never silent. The irreducible core (what the goal is, where
the plan is, what done means, how to prove it) is never trimmed -- if it alone
cannot fit, composition raises rather than emit a goal missing its completion
condition. Only the milestone list and the plan's acceptance criteria flex, and every
dropped or shortened entry is reported back through the returned meta so the caller can
print the omission -- including the COUNT of what did not fit, which is itself part of
the core.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

# The Claude Code harness limit. Other hosts differ, so callers may override it, but
# nothing in the framework may raise it silently: the CLI surfaces it as an explicit flag.
#
# This is the DELIVERED cap: what the host refuses at paste time.
GOAL_ASSIGNMENT_CHAR_LIMIT = 4000

# The AUTHORING ceiling, and it sits deliberately below the delivered cap.
#
# Batch 2026-08-11 B7, T4.5. The length check was measuring the wrong artifact. A goal's real
# path is `source -> markdown render -> terminal -> human copy -> paste`, and every stage in
# the middle can add bytes the validator never sees. Measured 2026-08-11: a compliant
# 3,659-char / 66-line goal had only 5.17 spaces per line of headroom against the 4,000 cap,
# so a renderer indenting code blocks by six spaces delivers an over-limit goal that passed
# validation. Reserving 400 characters -- ~6 characters per line on a 66-line goal -- absorbs
# a renderer indent that a source-only check cannot see.
#
# This is the same defect class as the rest of that batch: a control reading healthy because
# it is looking at the wrong thing.
GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT = 3600

# Below this a goal cannot carry a plan reference AND a completion condition, so a
# "goal" that short is a fragment, not an assignment.
GOAL_ASSIGNMENT_MIN_CHARS = 80

# Per-milestone display cap. A plan bullet can be a paragraph; the goal is an index
# into the plan, not a copy of it, and the plan path travels in the goal itself.
GOAL_ASSIGNMENT_MILESTONE_CHARS = 160

# Per-criterion display cap. Wider than a milestone on purpose: a milestone is a pointer
# ("WS2 -- the composer"), while an acceptance criterion is the falsifiable statement the
# builder is judged against, and cutting it to a pointer would put back exactly the generic
# goal this binding exists to replace.
GOAL_ASSIGNMENT_CRITERION_CHARS = 200

_MILESTONE_PREFIX = " Milestones: "
_OMISSION_TEMPLATE = " (+{n} more in the plan)"
_CRITERIA_OMISSION_TEMPLATE = " (+{n} more acceptance criteria in the plan)"
_CRITERIA_FALLBACK_TEMPLATE = "all {n} acceptance criteria named in the plan are met"
_ELLIPSIS = "…"


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _shorten(text: str, limit: int) -> tuple[str, bool]:
    """Collapse to one line and cut to `limit` on a word boundary when possible.

    Returns (text, was_truncated) so the caller can report the trim instead of
    passing off a silently shortened milestone as the whole one.
    """
    collapsed = _collapse(text)
    if len(collapsed) <= limit:
        return collapsed, False
    keep = limit - len(_ELLIPSIS)
    if keep <= 0:
        return _ELLIPSIS[:limit], True
    cut = collapsed[:keep]
    spaced = cut.rsplit(" ", 1)[0]
    # Only honour the word boundary if it keeps most of the budget; a single long
    # token would otherwise collapse the entry to almost nothing.
    if len(spaced) >= keep // 2:
        cut = spaced
    return cut.rstrip(" ,;:-") + _ELLIPSIS, True


def goal_assignment_authoring_limit(limit: int = GOAL_ASSIGNMENT_CHAR_LIMIT) -> int:
    """The authoring ceiling for a given delivered cap, preserving the reserved margin.

    A caller on a non-Claude host passes its own `limit`; the transport inflation the reserve
    exists for is a property of the RENDERER, not of the host, so the margin travels with the
    cap rather than being a fixed 3,600 that could land above a smaller host limit.
    """
    reserve = GOAL_ASSIGNMENT_CHAR_LIMIT - GOAL_ASSIGNMENT_AUTHORING_CHAR_LIMIT
    return max(GOAL_ASSIGNMENT_MIN_CHARS, int(limit) - reserve)


def goal_assignment_length_issues(
    text: str, limit: int = GOAL_ASSIGNMENT_CHAR_LIMIT
) -> list[str]:
    """Fail-closed length check against the AUTHORING ceiling, not the delivered cap.

    Messages name BOTH numbers, so an author can see the margin they are spending rather than
    discovering at paste time that a renderer ate it. The overage is reported against the
    ceiling that was actually enforced.
    """
    issues: list[str] = []
    count = len(text or "")
    authoring_limit = goal_assignment_authoring_limit(limit)
    if count == 0:
        issues.append("goal assignment is empty; there is nothing to assign")
        return issues
    if count > authoring_limit:
        issues.append(
            f"goal assignment is {count} characters, {count - authoring_limit} over the "
            f"{authoring_limit}-character AUTHORING ceiling (the delivered cap is {limit}; the "
            f"{limit - authoring_limit}-character reserve absorbs indentation a renderer adds "
            "between here and the paste). Cut scope detail and point at the plan instead of "
            "restating it."
        )
    elif count < GOAL_ASSIGNMENT_MIN_CHARS:
        issues.append(
            f"goal assignment is only {count} characters (minimum {GOAL_ASSIGNMENT_MIN_CHARS}); "
            "it cannot carry a plan reference and a completion condition."
        )
    return issues


# The handoff bar's markers, shared with done_definition.HANDOFF_BAR_MARKERS in intent but
# duplicated deliberately: this module is a leaf with no intra-package imports, and importing
# done_definition here would couple the goal composer to the condition registry's import
# graph for one regex. The pair is held together by
# tests/test_goal_assignment_done_bar.py::test_the_two_handoff_vocabularies_agree.
_HANDOFF_BAR_RE = re.compile(
    r"(?i)(armed to merge|auto[- ]merge|merge queue|merge-queue|\bmerged\b)"
)

# A marker preceded by a negation is the OPPOSITE of the bar. "Do not enable auto-merge. Done
# when: a PR is open" contains a marker and stops short of handoff; so does "the PR is not
# merged". A bare search accepts exactly the clauses this check exists to reject.
_HANDOFF_NEGATION_RE = re.compile(
    r"(?i)\b(no|not|never|without|avoid|don'?t|do not|neither|nor)\b[^.;]{0,40}?$"
)

# The completion clause itself, not the whole body: a handoff word anywhere in a goal -- in a
# prohibition, in the scope, in a milestone title -- must not satisfy a clause that says "a PR
# is open".
# ONE sentence, cut at a period or newline -- NOT at a semicolon, which the composed
# clause uses to separate conditions inside a single sentence. Spanning several let
# unrelated later prose -- "Done when: tests pass and a PR is
# open. Auto-merge support is documented later." -- supply a marker the completion condition
# itself never states.
_COMPLETION_CLAUSE_RE = re.compile(
    r"(?i)\b(?:done when|complete when|completion means|acceptance)\b(?P<clause>[^.\n]*)"
)


def _clause_states_handoff(clause: str) -> bool:
    for found in _HANDOFF_BAR_RE.finditer(clause):
        if _HANDOFF_NEGATION_RE.search(clause[: found.start()]):
            continue
        return True
    return False


def _states_handoff_bar(text: str) -> bool:
    """True when a COMPLETION CLAUSE affirmatively commits to an armed merge.

    EVERY clause match is considered, not just the first: `acceptance` is a clause marker and
    also ordinary prose, so "Implement the acceptance criteria from the plan. Done when: the PR
    is auto-merge armed." would otherwise be judged on the first sentence alone and rejected.
    """
    clauses = [m.group("clause") for m in _COMPLETION_CLAUSE_RE.finditer(text)]
    if not clauses:
        return _clause_states_handoff(text)
    return any(_clause_states_handoff(clause) for clause in clauses)


def goal_assignment_shape_issues(
    text: str, plan_ref: str | None = None, *, require_handoff: bool = True
) -> list[str]:
    """Return missing-element messages for an authored goal; empty means compliant.

    Deliberately few checks. The recurring failure this module exists for is length, and a
    thick shape schema here would just be a second thing to argue past.

    The third check (batch 2026-08-11 B7, T4.2) is aimed at exactly one measured failure: a
    goal that states a completion condition which stops short of the handoff bar. Before it,
    "Done when: it feels finished" passed, and so did the framework's own composed clause
    ending "the PR is queued to merge" -- which never says the merge must be ARMED, so a lane
    reads it as satisfied by an open PR sitting untouched.

    `require_handoff=False` for a project whose adapter disables `pr_handed_off`: a no-PR
    workflow must not be asked to name a bar it does not enforce.
    """
    body = text or ""
    issues: list[str] = []
    if plan_ref:
        stem = plan_ref.rsplit("/", 1)[-1]
        if plan_ref not in body and stem not in body:
            issues.append(
                f"goal assignment does not reference the source-of-truth plan `{plan_ref}`; "
                "the builder lane needs the plan path to work from."
            )
    if not re.search(r"(?i)\b(done when|complete when|completion means|acceptance)\b", body):
        issues.append(
            "goal assignment states no completion condition (no 'Done when' / 'Complete when' / "
            "'Completion means' clause); without one the builder cannot tell when to stop."
        )
    elif require_handoff and not _states_handoff_bar(body):
        issues.append(
            "goal assignment states a completion condition that never names the handoff bar; "
            "say that the PR must be merged, or armed to merge without this lane (auto-merge or "
            "merge queue). A clause that stops at 'a PR is open' authorizes the exact 90-95% "
            "stop this bar exists to close."
        )
    return issues


def goal_assignment_issues(
    text: str,
    *,
    plan_ref: str | None = None,
    limit: int = GOAL_ASSIGNMENT_CHAR_LIMIT,
    require_handoff: bool = True,
) -> list[str]:
    """Every issue with an authored goal assignment; empty means assignable."""
    return goal_assignment_length_issues(text, limit) + goal_assignment_shape_issues(
        text, plan_ref, require_handoff=require_handoff
    )


def _clean_unit(text: str) -> str:
    """Strip the routing/markup noise a workstream title carries into a goal line.

    `model-tier:` tags route token spend during execution and say nothing about scope,
    so they cost characters the milestone list needs.
    """
    cleaned = re.sub(r"(?i)`?\s*model-tier:\s*(mechanical|standard|deep)\s*`?", "", str(text or ""))
    cleaned = cleaned.replace("**", "").strip(" -—–:")
    return _collapse(cleaned)


_SCOPE_HEADINGS = re.compile(
    r"(?i)^\s*(workstreams?|milestones?|ordered milestones|milestone queue|tasks?|deliverables?)\b"
)


def plan_assignment_milestones(plan_text: str) -> list[str]:
    """The plan's top-level units of work, in plan order.

    Subheadings inside a Workstreams/Milestones/Tasks section WIN over bullets: the
    plan-authoring standard names each unit as its own `### Task N model-tier: ...`
    heading, and the bullets underneath are that unit's file list or detail. Preferring
    bullets there produces a goal that lists file paths instead of workstreams. Bullets
    are the unit list only when the section has no subheadings at all.

    Completed `- [x]` bullets are skipped -- they are not work to assign.
    """
    bullets: list[str] = []
    headings: list[str] = []
    section_level = 0
    # The heading level the units sit at. Fixed by the FIRST subheading inside the section, so a
    # `#### Files` nested under a `### W1` workstream is that workstream's detail, not a unit.
    unit_level: int | None = None
    in_scope = False
    in_fence = False
    for raw in (plan_text or "").splitlines():
        # Fenced code is skipped wholesale. A plan that embeds a Python or shell snippet has
        # `# comment` lines in it, and reading one as an H1 silently ENDS the Workstreams
        # section -- dropping every workstream after the first code block.
        if re.match(r"^\s*(```|~~~)", raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", raw.strip())
        if heading:
            level, label = len(heading.group(1)), heading.group(2)
            if in_scope and level > section_level:
                if unit_level is None:
                    unit_level = level
                if level == unit_level:
                    headings.append(label)
                continue
            in_scope = bool(_SCOPE_HEADINGS.match(label))
            section_level = level
            unit_level = None
            continue
        if not in_scope:
            continue
        if raw[:1].isspace():  # nested bullet: detail of the entry above, not its own unit
            continue
        stripped = raw.strip()
        if re.match(r"^[-*]\s+\[[xX]\]\s+", stripped):
            continue
        match = re.match(r"^[-*]\s+(?:\[\s\]\s*)?(.+?)\s*$", stripped)
        if match:
            bullets.append(match.group(1))
    chosen = headings or bullets
    return [item for item in (_clean_unit(entry) for entry in chosen) if item]


# What the operator asked the goal to be focused on. `Acceptance` first: it is what the
# plan-authoring standard names, and it is the plan's own falsifiable bar. `Completion
# definition` is the documented alternative heading for the same thing and is read ONLY when
# no acceptance section exists, so a plan carrying both is not made to state its bar twice.
#
# The optional enumerator is not decoration: three plans in this repo head the section
# `## 6. Acceptance (independently testable)`, and a pattern anchored straight at the word
# returned nothing for them while the CLI reported `0 of 0` -- a parser finding no section
# reading exactly like a plan that named no criteria.
# `acceptance` must END the heading or be followed by punctuation -- `:`, a parenthetical,
# a bracket or a dash -- rather than another word. A bare prefix match binds
# `## Acceptance testing strategy` as the plan's criteria instead of falling through to
# `## Completion definition`, which is the same wrong-section binding as a generic heading
# winning over an exact one, just one word later.
_ACCEPTANCE_TERMINATOR = r"\s*(?:[:(\[\u2014-]|$)"
_ACCEPTANCE_HEADINGS = re.compile(
    r"(?i)^\s*(?:\d+[.)]\s*)?(?:acceptance(?:\s+criteria)?|success\s+criteria)"
    + _ACCEPTANCE_TERMINATOR
)
# The same terminator the acceptance pattern uses, for the same reason: a `\b` suffix lets
# `## Completion definition mapping` shadow the real `## Completion definition` and return a
# mapping table as the plan's bar. Fixing one half of a two-headed bug and leaving the other is
# how a defect class survives being fixed.
_COMPLETION_HEADINGS = re.compile(
    r"(?i)^\s*(?:\d+[.)]\s*)?(?:completion\s+(?:definition|criteria)|definition\s+of\s+done)"
    + _ACCEPTANCE_TERMINATOR
)

# `\d+[a-z]?` because plans amend a numbered list in place rather than renumber it: an
# in-repo plan states `2b.` as a criterion of its own, and a digits-only marker folded it into
# criterion 2, where the 200-character shortening then cut it -- while the report still said
# every parsed criterion was included. A dropped amendment is a dropped bar.
_LIST_ITEM_RE = re.compile(
    r"^(?:[-*+]|\d+[a-z]?[.)])\s+(?:\[(?P<mark>[ xX])\]\s*)?(?P<body>.+?)\s*$"
)


_CODE_SPAN_RE = re.compile(r"`[^`]*`")
# Markdown BOLD, not every double star. `docs/product/**`, `plugins/**/plugin.json` and
# `2**32` are literal text a criterion means literally, and a blanket `replace("**", "")`
# rewrites the bar into a different requirement. An opener must follow a boundary and precede
# a non-space; a closer must follow a non-space and precede a boundary.
_EMPHASIS_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s(\[{—–]))\*\*(?=\S)(.+?)(?<=\S)\*\*(?=$|[\s.,;:)\]}!?])"
)


def _strip_emphasis(text: str) -> str:
    """Drop bold markers outside code spans; leave everything inside backticks alone."""
    pieces: list[str] = []
    last = 0
    for span in _CODE_SPAN_RE.finditer(text):
        pieces.append(_EMPHASIS_RE.sub(r"\1", text[last : span.start()]))
        pieces.append(span.group(0))
        last = span.end()
    pieces.append(_EMPHASIS_RE.sub(r"\1", text[last:]))
    return "".join(pieces)


def _clean_criterion(text: str) -> str:
    """Collapse a criterion to one line without changing what it says.

    NOT `_clean_unit`: that strips a leading `-`, which is right for a milestone title and
    wrong for a criterion, where `--workstream is honored` and `-1 is preserved` are the bar.
    """
    return _collapse(_strip_emphasis(str(text or ""))).strip(" :—–")


def _criteria_from_section(
    plan_text: str, heading: re.Pattern[str]
) -> tuple[str | None, list[str]]:
    """Every item under the first matching section, continuation lines folded in.

    Real acceptance criteria wrap across lines -- `- **AC-1 (integrity).** A run produces a
    record ...` continues on the next two indented lines -- so a reader that takes only the
    bullet line states a truncated criterion and calls it the bar. Blank line or a new item
    ends one; a heading at or above the section's level ends the section.

    A section written as prose rather than a list still yields its paragraph, because a plan
    is allowed to state its bar in sentences; but when the section has ANY list item, only the
    list items count, so a lead-in line ("The following must hold:") never poses as a criterion.

    Returns `(matched heading label or None, items)`. The label is not decoration: without it
    a caller cannot tell "this plan names no criteria" from "this parser found nothing", and
    those two want opposite next actions.
    """
    items: list[tuple[bool, str]] = []  # (came_from_a_list_item, text)
    current: list[str] | None = None
    current_is_item = False
    skipping = False  # inside a `- [x]` entry: its continuation lines are not a bar either
    current_indent = 0
    blank_seen = False
    saw_list_item = False
    in_scope = False
    fence_marker: str | None = None
    section_level = 0
    matched_label: str | None = None

    def flush() -> None:
        nonlocal current, current_is_item, skipping
        if current:
            joined = _collapse(" ".join(current))
            if joined:
                items.append((current_is_item, joined))
        current = None
        current_is_item = False
        skipping = False

    for raw in (plan_text or "").splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})", raw)
        if fence:
            # A fence does NOT end the entry it sits inside. A criterion that shows expected
            # output and then continues -- "...and exits with status 0" -- lost that
            # continuation when the opening delimiter flushed the item. The fenced lines
            # themselves are still skipped: an example is not the bar.
            #
            # The OPENING delimiter is remembered rather than toggling one boolean, because a
            # plan that shows Markdown inside Markdown -- a ~~~ or ````-fenced block containing
            # a ``` example -- would otherwise close on the inner fence, and an example
            # `## Acceptance criteria` would be read as the real section while the real one is
            # skipped as fenced. Per CommonMark a fence closes only on the same character, at
            # least as long as the opener.
            marker = fence.group(1)
            # CommonMark: a CLOSING fence carries no info string, so ```` ```python ```` inside a
            # ``` block is content rather than a close. Closing on the marker alone makes a fake
            # `## Acceptance criteria` in that block visible to the scanner, where it can shadow
            # the real section.
            suffix = raw.strip()[len(marker):].strip()
            if fence_marker is None:
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(fence_marker) and not suffix:
                fence_marker = None
            continue
        if fence_marker is not None:
            continue
        # Up to three spaces of indent is a heading; four or more is an indented code block,
        # per CommonMark. Matching on the STRIPPED line read `    # rebuild the index` inside
        # an indented example as a heading and ended the section there -- dropping every
        # criterion below it while the report still said "N of N included", which claims
        # completeness for a bar the plan never finished stating.
        head = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", raw)
        # A heading indented INSIDE an open list item is that item's content -- plans quote
        # Markdown output inside a criterion -- and treating it as a section boundary truncated
        # the criterion and could end the section, dropping every criterion below it.
        if head and current is not None and (len(raw) - len(raw.lstrip())) > current_indent:
            head = None
        if head:
            flush()
            level, label = len(head.group(1)), head.group(2)
            if in_scope and level > section_level:
                continue  # a subheading inside the section, not the end of it
            if in_scope:
                break  # the section ended; the FIRST matching section is the plan's bar
            if heading.match(label):
                in_scope = True
                matched_label = _collapse(label)
            section_level = level
            continue
        if not in_scope:
            continue
        stripped = raw.strip()
        if not stripped:
            # A blank line does NOT end an entry. Criteria are written with blank-separated
            # continuation paragraphs, and flushing here dropped that paragraph from an
            # active criterion and promoted it to a criterion of its own under a satisfied
            # one -- a goal stating an incomplete bar, or a spurious one.
            blank_seen = True
            continue
        if stripped.startswith(("|", ">")):
            flush()
            blank_seen = False
            continue
        match = _LIST_ITEM_RE.match(stripped)
        indent = len(raw) - len(raw.lstrip())
        if blank_seen:
            blank_seen = False
            # Back at the left margin after a blank line is a new block; still indented is
            # the same entry continuing.
            if indent == 0:
                flush()
        # Indentation decides sibling from detail. A whole list can be written indented -- it
        # is still the list -- while an item indented UNDER another item is that item's detail
        # and folds into it. Comparing against the OPEN entry's indent gets both right.
        #
        # ...except against PROSE. A lead-in line ("All of the following must hold:") followed
        # by an indented list is the list, not one paragraph: comparing indents folded every
        # bullet into the lead-in and returned ONE combined criterion where the plan states
        # several, so the count under-reported and the 200-character cap could then truncate
        # what survived. Prose never owns a list item, whatever its indent.
        # `current is not None` matters: without it this clause also fires while SKIPPING a
        # satisfied `- [x]` entry, promoting that entry's sub-bullet to a criterion of its own
        # -- already-finished work presented as this work's bar.
        prose_cannot_own_a_list_item = current is not None and not current_is_item
        if match and (
            current is None
            and not skipping
            or indent <= current_indent
            or prose_cannot_own_a_list_item
        ):
            flush()
            current_indent = indent
            saw_list_item = True
            if (match.group("mark") or " ").lower() == "x":
                skipping = True  # already satisfied; not a bar this goal has to state
                continue
            current, current_is_item = [match.group("body")], True
            continue
        if current is not None:
            # A continuation of the entry above -- including an indented sub-bullet, whose
            # marker is dropped so the folded criterion does not read as a broken list.
            nested = _LIST_ITEM_RE.match(stripped)
            current.append(nested.group("body") if nested else stripped)
            continue
        if skipping:
            continue  # the wrapped remainder of a satisfied entry
        if not match:
            current, current_is_item = [stripped], False
    flush()

    listed = [text for is_item, text in items if is_item]
    # `saw_list_item` counts entries that were SKIPPED for being satisfied, so a section whose
    # criteria are all `- [x]` does not fall through to its lead-in line and hand back
    # "All of the following must hold:" as the plan's sole acceptance criterion. A section that
    # was a list stays a list even when every entry in it is already done.
    chosen = listed or ([] if saw_list_item else [text for _is_item, text in items])
    return matched_label, [item for item in (_clean_criterion(entry) for entry in chosen) if item]


def _acceptance_patterns(headings: Sequence[str] | None) -> tuple[re.Pattern[str], ...]:
    """The acceptance-section patterns, most specific first: configured before built-in.

    `planAcceptance.acHeadings` already tells plan finalization which section holds a
    project's criteria. A composer with its own hardcoded list would report "no acceptance
    section" for a project that renamed it -- the same section the finalization gate just
    graded. Union rather than replacement: configuring one heading must not make the composer
    blind to a plan that uses the standard one.

    Two patterns, not one, because a single prefix pattern is wrong in both directions:

    - It cannot bind a configured heading that ends in punctuation. `Definition of Ready (AC)`
      escaped and followed by `\\b` never matches, because a word boundary after `)` needs a
      word character after it and the heading has ended. The project whose section the gate
      grades would be told it names no criteria. The exact pattern anchors on the end of the
      heading instead, which is also the semantics the gate itself uses.
    - It binds the FIRST heading merely STARTING with "acceptance", so `## Acceptance mapping`
      sitting above `## Acceptance criteria` wins and the goal states a mapping row as the
      plan's bar. A goal that confidently states criteria that are not the plan's is worse
      than one that states none, so an exact heading anywhere in the document beats a generic
      prefix match earlier in it.
    """
    extra = [
        re.escape(str(item).strip().lower()) for item in (headings or ()) if str(item).strip()
    ]
    builtin_exact = re.compile(
        r"(?i)^\s*(?:\d+[.)]\s*)?(?:acceptance\ criteria|success\ criteria)\s*:?\s*$"
    )
    if not extra:
        return (builtin_exact, _ACCEPTANCE_HEADINGS)
    # The CONFIGURED headings are their own pass, ahead of the built-ins, because plan
    # finalization grades only the configured section. Folding them into one alternation left
    # document order to decide, so a standard `## Acceptance criteria` appearing earlier won --
    # and the goal would state a bar that is not the one the gate graded.
    configured_exact = re.compile(
        r"(?i)^\s*(?:\d+[.)]\s*)?(?:" + "|".join(extra) + r")\s*:?\s*$"
    )
    configured_generic = re.compile(
        r"(?i)^\s*(?:\d+[.)]\s*)?(?:" + "|".join(extra) + r")" + _ACCEPTANCE_TERMINATOR
    )
    return (configured_exact, configured_generic, builtin_exact, _ACCEPTANCE_HEADINGS)


def _criteria_scan(
    plan_text: str, headings: Sequence[str] | None = None
) -> tuple[str | None, list[str]]:
    """The acceptance section if the plan HAS one, else the completion-definition section.

    The fallback fires only when there is no acceptance section at all. A plan whose
    acceptance section exists but yields nothing -- a table, or only satisfied entries --
    must not quietly answer with a different section's text: that hides the section a human
    should look at behind an answer that looks fine.
    """
    for pattern in _acceptance_patterns(headings):
        label, items = _criteria_from_section(plan_text, pattern)
        if label is not None:
            return label, items
    return _criteria_from_section(plan_text, _COMPLETION_HEADINGS)


def plan_acceptance_criteria(plan_text: str, headings: Sequence[str] | None = None) -> list[str]:
    """The plan's OWN named acceptance criteria, in plan order.

    The composed completion clause used to be built solely from the adapter's definition of
    done, so every goal stated the same generic process bar and never said what THIS work has
    to satisfy. Definition-of-done and acceptance criteria are different things and the goal
    owes the builder both: the plan's bar, and the floor every plan shares.

    A plan with no such section returns `[]` and composes with the generic bar alone -- a
    missing section is a plan style, not an error, and refusing here would make the goal
    generator unusable on the plans that already exist. Ask
    `plan_acceptance_criteria_heading` which of those two empty answers you got.
    """
    return _criteria_scan(plan_text, headings)[1]


def plan_acceptance_criteria_heading(
    plan_text: str, headings: Sequence[str] | None = None
) -> str | None:
    """The heading the criteria were read from, or None when the plan has no such section.

    Exists so an empty result is not one indistinguishable state. `0 of 0` under a heading
    that WAS found means the parser could not read that section's shape and someone should
    look; `0 of 0` with no heading is a plan that simply names no criteria.
    """
    return _criteria_scan(plan_text, headings)[0]


# `*Verified by:* test_x` is provenance the plan-authoring standard asks for; it points at the
# test, it is not the bar, and it costs as much budget as the criterion it annotates.
#
# Bounded on BOTH sides rather than matched loosely. It must open a segment -- start of the
# criterion, or a sentence/dash boundary -- and it must carry the colon. "the record is verified
# by its embedded sha256" is a criterion, and a pattern loose enough to catch it amputates the
# bar and states an unfalsifiable one, which is the exact failure this change exists to end.
_CRITERION_PROVENANCE_RE = re.compile(
    r"(?i)(?:^|(?<=[.;)\]])|(?<=—)|(?<=–)|(?<= -))\s*[*_]{0,2}\s*verified by\s*:\s*[*_]{0,2}.*$"
)


def _criterion_phrase(text: str) -> str:
    """One acceptance criterion as a clause item rather than a standalone sentence.

    The terminating period goes because the clause supplies its own separators. Nothing else
    about the wording is touched: the goal QUOTES the plan's bar, and a composer that
    re-capitalised it would state something the plan does not say -- `Tautline`, `Python 3.12`
    and `AC-1` all mean what their case says they mean.
    """
    cleaned = _CRITERION_PROVENANCE_RE.sub("", _clean_criterion(text))
    return cleaned.rstrip(" .;:")


# One terse phrase per done condition, keyed by the condition id in
# `done_definition.DONE_CONDITIONS`. A dict of records, not a `list[str]` -- see the SSOT note
# in done_definition.py, and because the goal must state the SAME bar the framework enforces
# rather than a second hardcoded one. A composed goal that named a different bar from the one
# `done-check` applies would be the framework contradicting itself in the one artifact a
# builder reads first.
GOAL_ASSIGNMENT_DONE_PHRASES: dict[str, str] = {
    "scope_complete": (
        "every workstream in that plan is implemented or explicitly deferred with a "
        "recorded reason"
    ),
    "tests_written": "the new behavior has named tests",
    "tests_green": "the test gate passes on the branch tip with the pass count stated as a number",
    "review_clean": "implementation review is finalized with no open Critical/P1",
    "evidence_bound": "the review-evidence ledger is committed",
    "pr_handed_off": (
        "the PR is merged, or armed to merge without this lane (auto-merge or merge queue) -- "
        "never wait for a queued PR to land"
    ),
    "board_updated": "the board item is done with verification evidence",
}

# The set a caller gets when it says nothing. `board_updated` is out because a project with no
# backlog provider must not be told to update a board it does not have; a caller that knows the
# project has one passes the effective set explicitly.
GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS = (
    "scope_complete",
    "tests_written",
    "tests_green",
    "review_clean",
    "evidence_bound",
    "pr_handed_off",
)


# The bridge from the plan's own bar to the shared floor. Two sentences, not one list, and
# the second opens with a literal completion marker on purpose: `_states_handoff_bar` reads
# the completion CLAUSE, and an acceptance criterion legitimately names `scripts/test.sh` or
# `cli.py`. Stated as one sentence, a dotted filename in a criterion would sit between the
# clause marker and the handoff phrase; starting a second marked clause puts the handoff bar
# where no criterion's punctuation can stand in front of it.
_DONE_FLOOR_BRIDGE = ". Completion means those criteria and the standing floor: "


def _done_floor_phrases(conditions: Sequence[str] | None) -> str:
    ids = (
        list(conditions)
        if conditions is not None
        else list(GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS)
    )
    ordered = [key for key in GOAL_ASSIGNMENT_DONE_PHRASES if key in ids]
    phrases = [GOAL_ASSIGNMENT_DONE_PHRASES[key] for key in ordered]
    if not phrases:
        # Every condition disabled. Still say something falsifiable rather than emitting a
        # goal with no completion condition at all, which `goal_assignment_shape_issues`
        # would then refuse.
        return "the plan's own completion definition is met"
    if len(phrases) == 1:
        return phrases[0]
    return "; ".join(phrases[:-1]) + f"; and {phrases[-1]}"


def compose_done_clause(
    conditions: Sequence[str] | None = None,
    criteria: Sequence[str] | None = None,
    *,
    criteria_omitted: int = 0,
) -> str:
    """The ' Done when: ...' sentence: this plan's bar, then the floor every plan shares.

    The condition set is not a fixed string, on purpose. The bar is adapter-overridable, so a
    hardcoded sentence would keep demanding a PR from a project that has disabled
    `pr_handed_off` for a no-PR workflow -- a generated goal contradicting the enforcement the
    same adapter configures. Unknown ids are ignored rather than raising: this composes a
    sentence, and a goal is not the place to discover an adapter typo
    (`normalize_definition_of_done` fails loud on that).

    `criteria` are the plan's OWN acceptance criteria and lead, because that is what this
    work has to satisfy; the definition-of-done floor is RETAINED behind them, because it is
    what closes the measured stop at 90-95%. `criteria_omitted` is stated, never swallowed:
    criteria the budget could not fit are summarised with their count, and when none fit at
    all the clause still says how many the plan named.
    """
    floor = _done_floor_phrases(conditions)
    stated = [phrase for phrase in (_criterion_phrase(item) for item in (criteria or [])) if phrase]
    if not stated and criteria_omitted <= 0:
        return f" Done when: {floor}."
    if not stated:
        body = _CRITERIA_FALLBACK_TEMPLATE.format(n=criteria_omitted)
    elif criteria_omitted > 0:
        body = "; ".join(stated) + _CRITERIA_OMISSION_TEMPLATE.format(n=criteria_omitted)
    elif len(stated) == 1:
        body = stated[0]
    else:
        body = "; ".join(stated[:-1]) + f"; and {stated[-1]}"
    return f" Done when: {body}{_DONE_FLOOR_BRIDGE}{floor}."


# Composed, not left to author discipline -- the same principle the AFK line documents. The
# plan-authoring standard is parallel-by-default: every T1+ plan is authored as independent
# workstreams carrying `model-tier` tags precisely so token spend can be routed by difficulty.
# A goal that never says so hands that plan to a lane which works it in sequence on one model,
# and the parallelism the plan was authored for is lost between the plan and the build.
GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE = (
    " Parallelize wherever the plan's dependency graph allows it: dispatch independent tasks "
    "to concurrent subagents in a single batch rather than working them in sequence, give each "
    "its own worktree when they would otherwise touch the same files, and route each by its "
    "`model-tier` tag."
)


def compose_goal_assignment(
    *,
    command: str,
    title: str,
    plan_ref: str,
    milestones: Sequence[str] = (),
    criteria: Sequence[str] = (),
    proof_command: str = "tautline goal-status --target .",
    limit: int = GOAL_ASSIGNMENT_CHAR_LIMIT,
    conditions: Sequence[str] | None = None,
) -> tuple[str, dict]:
    """Build an assignable goal that is under `limit` by construction.

    Raises ValueError when the irreducible core does not fit -- that is the fail-closed
    edge, and emitting a core-less goal would be worse than refusing.

    The output carries no newlines and no hanging indent. That is not cosmetic: the goal's
    real path is source -> renderer -> terminal -> copy -> paste, indentation compounds at
    every stage, and a validated goal can arrive over the host's cap because of decoration
    the validator never measured. Flat left margin, one paragraph, no fence.
    """
    title = _collapse(title) or "the planned work"
    plan_ref = _collapse(plan_ref)
    proof_command = _collapse(proof_command)

    head = f"{_collapse(command)} Complete `{title}` from the finalized plan `{plan_ref}`."
    # Composed, not left to author discipline. The measured failure is a lane that stops at
    # 90-95% and asks for a new session; a goal that never says the human is away invites
    # exactly that, because waiting looks free.
    afk = (
        " The human is away for the duration: do not wait for them, and end the session at that "
        "bar, not before it."
    )
    autonomy = (
        " Work autonomously: use best judgment, record non-obvious calls with `tautline "
        "decision-record`, do not stop for permission mid-task, and if one part blocks, work the "
        "rest exhaustively."
    )
    proof = f" Proof: `{proof_command}`."
    # The parallel directive sits in the irreducible tail with the AFK and autonomy lines, not
    # in the elastic content: a goal that drops it under budget pressure is exactly the goal
    # whose plan was too big to work in sequence. Living in `tail`, it is counted everywhere
    # the tail is -- the core-too-large refusal, the criteria budget, the milestone budget --
    # so the cap check measures the goal that is actually emitted.
    tail = afk + GOAL_ASSIGNMENT_PARALLEL_DIRECTIVE + autonomy + proof

    total = len(milestones)
    # The fact that the plan HAS milestones is part of the irreducible core, not part of the
    # flexible list. Otherwise a budget that admits no full entry drops the list silently and
    # the goal never mentions the omitted work at all (Codex T2 R2 P2).
    fallback = f"{_MILESTONE_PREFIX}all {total} are in the plan." if total else ""

    prepared: list[tuple[str, bool]] = []
    for raw in criteria:
        phrase, was_cut = _shorten(_criterion_phrase(raw), GOAL_ASSIGNMENT_CRITERION_CHARS)
        if phrase:
            prepared.append((phrase, was_cut))
    criteria_total = len(prepared)

    # The core carries the COUNT of the plan's criteria for the same reason it carries the
    # milestone count: a budget that admits no full criterion must still say the plan named
    # them, or the goal silently reverts to the generic bar and reads as though there were
    # no plan-specific criteria at all.
    core_clause = compose_done_clause(conditions, criteria_omitted=criteria_total)
    core_len = len(head) + len(fallback) + len(core_clause) + len(tail)
    if prepared:
        # The summary sentence ("all N acceptance criteria ... are met") can be LONGER than the
        # criterion it stands in for, and the loop below states that criterion whenever it fits.
        # Measuring only the summary refuses goals whose actual output would have fitted -- a
        # fail-closed control rejecting on a length the result would never have had. Measure the
        # cheaper of the two things this function can actually emit.
        first_clause = compose_done_clause(
            conditions, [prepared[0][0]], criteria_omitted=criteria_total - 1
        )
        core_len = min(core_len, len(head) + len(fallback) + len(first_clause) + len(tail))
    if core_len > limit:
        raise ValueError(
            f"goal assignment core is {core_len} "
            f"characters, over the {limit}-character limit before any milestone fits. Shorten "
            f"the plan title ({len(title)} chars) or the plan path ({len(plan_ref)} chars)."
        )

    # Criteria have first claim on the leftover budget, ahead of the milestone list: the
    # milestone list indexes the plan, the criteria state the bar, and a goal that indexes a
    # plan it cannot state the bar of is the generic goal this binding replaces.
    stated: list[str] = []
    criteria_shortened = 0
    for phrase, was_cut in prepared:
        candidate = [*stated, phrase]
        clause = compose_done_clause(
            conditions, candidate, criteria_omitted=criteria_total - len(candidate)
        )
        if len(head) + len(fallback) + len(clause) + len(tail) > limit:
            break
        stated = candidate
        criteria_shortened += 1 if was_cut else 0
    criteria_omitted = criteria_total - len(stated)
    done_when = compose_done_clause(conditions, stated, criteria_omitted=criteria_omitted)
    base = head + done_when + tail

    entries: list[str] = []
    truncated = 0
    budget = limit - len(base) - 1  # -1 reserves the period that terminates the list
    if total and budget > len(_MILESTONE_PREFIX) + len(_OMISSION_TEMPLATE.format(n=total)):
        used = len(_MILESTONE_PREFIX)
        for index, raw in enumerate(milestones, start=1):
            shortened, was_cut = _shorten(raw, GOAL_ASSIGNMENT_MILESTONE_CHARS)
            if not shortened:
                continue
            entry = f"{index}. {shortened}"
            need = (2 if entries else 0) + len(entry)  # "; " separator
            omitted_if_stop = total - index
            reserve = len(_OMISSION_TEMPLATE.format(n=omitted_if_stop)) if omitted_if_stop else 0
            if budget - used - need < reserve:
                break
            used += need
            entries.append(entry)
            truncated += 1 if was_cut else 0

    omitted = total - len(entries)
    if entries:
        milestone_text = _MILESTONE_PREFIX + "; ".join(entries)
        if omitted > 0:
            milestone_text += _OMISSION_TEMPLATE.format(n=omitted)
        milestone_text += "."  # else the list runs straight into " Done when:"
    else:
        # No entry fit (or there are none). The fallback still names the count, so omitted work
        # is never invisible; it is empty only when the plan genuinely has no milestones.
        milestone_text = fallback

    text = head + milestone_text + done_when + tail
    # Flat left margin, enforced rather than intended: collapse any whitespace run the
    # composed parts could have introduced, so nothing downstream inherits an indent.
    text = _collapse(text)
    if len(text) > limit:  # pragma: no cover - budgeting above makes this unreachable
        raise ValueError(
            f"composed goal assignment is {len(text)} characters, over the {limit}-character limit"
        )

    meta = {
        "char_count": len(text),
        "limit": limit,
        "headroom": limit - len(text),
        "milestones_total": total,
        "milestones_included": len(entries),
        "milestones_omitted": omitted,
        "milestones_shortened": truncated,
        "criteria_total": criteria_total,
        "criteria_included": len(stated),
        "criteria_omitted": criteria_omitted,
        "criteria_shortened": criteria_shortened,
        "conditions": list(conditions) if conditions is not None else list(
            GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS
        ),
    }
    return text, meta
