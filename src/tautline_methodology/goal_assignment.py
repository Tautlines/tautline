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
condition. Only the milestone list flexes, and every dropped or shortened entry is
reported back through the returned meta so the caller can print the omission.
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

_MILESTONE_PREFIX = " Milestones: "
_OMISSION_TEMPLATE = " (+{n} more in the plan)"
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


def compose_done_clause(conditions: Sequence[str] | None = None) -> str:
    """The ' Done when: ...' sentence, built from the EFFECTIVE enabled condition set.

    Not a fixed string, on purpose. The bar is adapter-overridable, so a hardcoded sentence
    would keep demanding a PR from a project that has disabled `pr_handed_off` for a no-PR
    workflow -- a generated goal contradicting the enforcement the same adapter configures.
    Unknown ids are ignored rather than raising: this composes a sentence, and a goal is not
    the place to discover an adapter typo (`normalize_definition_of_done` fails loud on that).
    """
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
        return " Done when: the plan's own completion definition is met."
    if len(phrases) == 1:
        return f" Done when: {phrases[0]}."
    return " Done when: " + "; ".join(phrases[:-1]) + f"; and {phrases[-1]}."


def compose_goal_assignment(
    *,
    command: str,
    title: str,
    plan_ref: str,
    milestones: Sequence[str] = (),
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
    done_when = compose_done_clause(conditions)
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
    base = head + done_when + afk + autonomy + proof

    total = len(milestones)
    # The fact that the plan HAS milestones is part of the irreducible core, not part of the
    # flexible list. Otherwise a budget that admits no full entry drops the list silently and
    # the goal never mentions the omitted work at all (Codex T2 R2 P2).
    fallback = f"{_MILESTONE_PREFIX}all {total} are in the plan." if total else ""
    if len(base) + len(fallback) > limit:
        raise ValueError(
            f"goal assignment core is {len(base) + len(fallback)} characters, over the "
            f"{limit}-character limit before any milestone fits. Shorten the plan title "
            f"({len(title)} chars) or the plan path ({len(plan_ref)} chars)."
        )

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

    text = head + milestone_text + done_when + afk + autonomy + proof
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
        "conditions": list(conditions) if conditions is not None else list(
            GOAL_ASSIGNMENT_DEFAULT_DONE_CONDITIONS
        ),
    }
    return text, meta
