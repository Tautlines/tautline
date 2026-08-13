"""Backlog / stakeholder-question leaves: the backlog-item business-lead justification
scanners and their heading constants, plus stakeholder-question config/marker/parse/
substantive-answer helpers. The stateful verb handlers (backlog_provider_status,
backlog_board_examine, stakeholder_question_ask, ...) stay in bin/tautline; they reach
lane/adapter/board state and delegate the pure helpers here."""

from __future__ import annotations

import re

from .core.runtime import _extract_ac_section
from .core.runtime import _split_ac_items


def backlog_provider_completion_unit(data: dict) -> str:
    provider = data.get("backlogProvider") if isinstance(data, dict) else {}
    if not isinstance(provider, dict) or not provider.get("enabled"):
        return "goal"
    value = str(provider.get("completionUnit") or "goal").strip().lower()
    return value if value in {"goal", "provider-item"} else "goal"


def backlog_provider_done_evidence_comment(evidence: str) -> str:
    return "## Verification Evidence\n\n" + evidence.strip() + "\n"


# --- Oracle discipline: closure verification is measured against the WRITTEN acceptance criteria --
#
# RCA 2026-07-21 (issue #357 on a private product lane -- the incident is named in the source
# RCA, not here: this repo is a public cut and may not carry private product names). Done evidence
# was required to EXIST and nothing constrained its
# ORACLE, so an agent whose canonical spec had been frozen out of the run set verified the
# implementation against itself and reframed the failed AC lines as scope deferrals.

# The criterion cell accepts a BACKSLASH-ESCAPED pipe, which is how Markdown carries a literal `|`
# inside a table cell. Codex R2 P2: without this, an acceptance criterion whose own text contains a
# pipe ("Support A | B imports") produced a skeleton row the gate could not parse, so `ac-verify`
# emitted a table its own gate then refused -- the continuation refusing its own output.
_AC_ROW_RE = re.compile(r"(?im)^\s*\|(?P<criterion>(?:\\\||[^|\n])*)\|\s*(?P<verdict>PASS|FAIL)\s*\|")

_AC_INDEX_RE = re.compile(r"^(?:ac\s*)?#?0*(\d+)\b")

# Tuple, NOT a list: UPPER_CASE list-of-str constants are auto-collected into the policy-phrases
# SSOT (test_policy_phrases_ssot) and these are matcher inputs, not policy prose.
#
# HEURISTIC TRIPWIRE ONLY. Three literals cannot survive rewording, and both RCA copies say a
# reminder-class control is explicitly insufficient. The enforcement weight is carried by the
# structural row-to-criterion matching below; this tuple exists to catch the *literal* recurrence
# cheaply and to make the forbidden framing quotable in the refusal. Do not add legs here in place
# of strengthening the matcher -- test_a_reworded_evasion_is_still_refused_by_the_table_check pins
# that the matcher, not this list, is what actually holds.
_FORBIDDEN_ORACLE_PHRASES = (
    "within the shipped model",
    "verified against the implementation",
    "verify within the implementation",
)


def _ac_key(text: str) -> str:
    """Normalize an AC bullet or a table criterion cell to a comparable key."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    first = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", first)   # list marker
    first = re.sub(r"^\[[ xX]\]\s*", "", first.strip())      # checkbox
    first = first.replace("\\|", "|")                        # Markdown-escaped pipe
    first = re.sub(r"[`*_~]", "", first)                     # inline markdown
    return re.sub(r"\s+", " ", first).strip().rstrip(".;:").lower()


def _ac_row_eligible(key: str, cell: str, index: int, stage: str = "") -> bool:
    """Whether a table cell names the criterion at `index`. `stage` restricts it to one rule;
    the empty stage asks the question at its widest, which is what failure detection needs.

    ONE definition of eligibility, deliberately. Two Codex rounds found two different bugs in the
    same class -- a FAIL silenced by a PASS written above it, then a FAIL silenced by a PASS matched
    in an EARLIER STAGE -- because "does this row name this criterion" and "which row does this
    criterion consume" were answered by the same tangled loop. They are different questions and are
    now asked separately.
    """
    if not key or not cell:
        return False
    if stage in ("", "exact") and cell == key:
        return True
    if stage in ("", "index"):
        match = _AC_INDEX_RE.match(cell)
        if match and int(match.group(1)) == index + 1:
            return True
    if stage in ("", "substring"):
        return len(cell) >= 12 and (cell in key or key in cell)
    return False


def _ac_failed_criteria(criteria: list[str], rows: list[tuple[str, str]]) -> list[int]:
    """Criteria whose LAST recorded verdict is FAIL -- independent of coverage matching.

    Failure is not a question about assignment: a criterion is judged by every row that names it,
    at any matching stage, whether or not some other row was consumed for coverage. That is what
    stops a paraphrase or a stage ordering from hiding a FAIL.

    Among the rows that name one criterion, the LAST one decides, because evidence is composed in
    order and a correction is appended after what it corrects. This is the ONLY place that judgement
    can be made correctly: it needs the criterion itself, which is why the compose-time supersession
    it replaces could never converge -- two rows can each name the same criterion without naming
    each other, so no row-to-row comparison can tell a correction from an unrelated table. Five
    review rounds on that predicate said so in five different ways.

    Note what this does NOT weaken: a PASS row written ABOVE a FAIL row for the same criterion still
    fails it, which is the reframe-a-failure mechanism this item exists to stop. What it admits is
    the honest inverse -- a corrected verdict appended after a stale one -- which is exactly what
    the `--verification-evidence*` channel is for.
    """
    keys = [_ac_key(criterion) for criterion in criteria]
    cells = [_ac_key(cell) for cell, _verdict in rows]
    failed = []
    for i, key in enumerate(keys):
        # FAIL CLOSED, then allow an explicit correction to clear it. Any row that could name this
        # criterion and records FAIL fails it; the only thing that clears a FAIL is a STRICTLY LATER
        # row that names the criterion UNAMBIGUOUSLY -- repeating its text, or keying its index --
        # and records PASS.
        #
        # This shape exists because choosing WHICH rows to consult kept producing false acceptances,
        # each one introduced by the previous round's fix: a flat scan let an overlapping criterion's
        # PASS stand in for a shorter one (R3); ranking by specificity discarded a later index-keyed
        # FAIL (R4); ranking by ambiguity discarded a later paraphrased FAIL (R5). Every one of those
        # was the gate accepting an explicitly failed criterion, which is the single direction it
        # must never fail in. So no row that says FAIL is ever discarded. A correction still works,
        # because a lane correcting a verdict repeats the criterion text -- which is exactly what
        # `ac-verify` emits -- and no looser match can clear a failure it might not even be about.
        #
        # Clearing requires an EXACT restatement, not an index key: `_AC_INDEX_RE` accepts any cell
        # beginning with a number, so `| 1 smoke test | PASS |` in a retained CI matrix would read
        # as a correction to criterion 1 and turn an explicit FAIL green. Index rows still FAIL a
        # criterion -- nothing that says FAIL is discarded -- they just cannot clear one.
        fails = [
            j for j, cell in enumerate(cells)
            if rows[j][1] == "FAIL" and _ac_row_eligible(key, cell, i)
        ]
        if not fails:
            continue
        last_fail = max(fails)
        cleared = any(
            j > last_fail
            and rows[j][1] == "PASS"
            and _ac_row_eligible(key, cell, i, "exact")
            for j, cell in enumerate(cells)
        )
        if not cleared:
            failed.append(i)
    return failed


def _match_ac_rows(criteria: list[str], rows: list[tuple[str, str]]) -> dict[int, int]:
    """Injective criterion-index -> row-index matching. A row is consumed by at most one criterion,
    so N identical or paraphrased rows can never cover N distinct AC lines -- which is precisely the
    evidence #357 produced and a counting check accepts."""
    keys = [_ac_key(criterion) for criterion in criteria]
    cells = [_ac_key(cell) for cell, _verdict in rows]
    matched: dict[int, int] = {}
    used: set[int] = set()
    for stage in ("exact", "index", "substring"):
        for i, key in enumerate(keys):
            if i in matched or not key:
                continue
            eligible = [
                j for j, cell in enumerate(cells)
                if j not in used and _ac_row_eligible(key, cell, i, stage)
            ]
            if not eligible:
                continue
            # Within a stage a FAIL still wins, so the row a criterion CONSUMES is the honest one
            # when there is a choice. This is a nicety, not the guarantee: the guarantee that an
            # explicitly failed criterion cannot be hidden lives in `_ac_failed_criteria`, which
            # does not care what was consumed. Codex R2 and R5 both found FAILs hidden here, once
            # by row order and once by stage order; only the decoupling closes that.
            best = min(eligible, key=lambda j: (rows[j][1] != "FAIL", j))
            matched[i] = best
            used.add(best)
    return matched


def done_evidence_ac_criteria(issue_body: str, ac_headings: list[str]) -> list[str]:
    """The written acceptance criteria of a linked issue, one entry per AC line.

    `_extract_ac_section` takes a list of lowercased, colon-free headings and matches ANY heading
    level case-insensitively. `markdown_section()` is FORBIDDEN on this path: it is case-sensitive
    and level-exact, so against a lowercased heading list it silently matches nothing and the gate
    ships green and dead (test_done_evidence_ac_table.py's anti-inert case pins this).
    """
    headings = [
        str(heading).strip().lower().rstrip(":") for heading in ac_headings if str(heading).strip()
    ]
    section = _extract_ac_section(issue_body or "", headings)
    return _split_ac_items(section) if section else []


def done_evidence_ac_table_issues(
    evidence: str, issue_body: str, ac_headings: list[str]
) -> list[str]:
    """Oracle discipline: closure verification is measured against the item's WRITTEN acceptance
    criteria. When the linked issue carries an AC section, the done evidence must contain a
    line-by-line AC pass/fail table -- one row PER AC LINE, matched to that line -- and an unmet AC
    line is a FAILED AC, never a deferral."""
    issues: list[str] = []
    lowered = (evidence or "").lower()
    for phrase in _FORBIDDEN_ORACLE_PHRASES:
        if phrase in lowered:
            issues.append(
                "done_evidence_ac_error: forbidden verification oracle in done evidence: "
                f"{phrase!r} -- verification is measured against the item's written acceptance "
                "criteria, never the shipped implementation. Remedy: re-verify each AC line and "
                "post the table from "
                "`tautline ac-verify --item <item-ref> --target .`"
            )
    criteria = done_evidence_ac_criteria(issue_body, ac_headings)
    if not criteria:
        return issues
    rows = [
        (match.group("criterion"), match.group("verdict").upper())
        for match in _AC_ROW_RE.finditer(evidence or "")
    ]
    matched = _match_ac_rows(criteria, rows)
    unmatched = [criteria[i] for i in range(len(criteria)) if i not in matched]
    if unmatched:
        named = "; ".join(_ac_key(criterion)[:80] for criterion in unmatched[:5])
        more = f" (+{len(unmatched) - 5} more)" if len(unmatched) > 5 else ""
        issues.append(
            "done_evidence_ac_error: done evidence must contain a line-by-line AC pass/fail table "
            "with one PASS/FAIL row matched to each acceptance criterion. "
            f"{len(unmatched)} of {len(criteria)} criteria have no matching row: {named}{more}. "
            "A DEFERRED/PARTIAL/N-A verdict is not a row. Remedy: "
            "`tautline ac-verify --item <item-ref> --target .` prints the table skeleton; fill "
            "each verdict and pass it with --verification-evidence-file."
        )
    # Asked of ALL rows, not of the matched one: coverage and failure are different questions.
    # NOTE ON THE REMEDY BELOW (Codex R2 P2): it names `backlog-provider-update --status
    # <active-status>` WITHOUT --verification-evidence-file, deliberately. The non-done path of
    # `goal_tracker_update_status_with_done_evidence` updates status and does not post an evidence
    # comment, so appending that flag promised a publication the command would not perform -- a
    # dead end wearing a remedy's clothes, which is the exact class this surface exists to close.
    # Do not put the flag back without also making that path post.
    failed = [criteria[i] for i in _ac_failed_criteria(criteria, rows)]
    if failed:
        named = "; ".join(_ac_key(criterion)[:80] for criterion in failed[:5])
        issues.append(
            # One f-string, NOT `"..." + named + "..."`: a concatenation whose middle term is a
            # variable renders as unparseable to the closure refusal walk, which then descends and
            # reads the bare `FAILED AC: ` prefix as a refusal with no continuation. The walk found
            # exactly that here. Keep the whole message in one renderable node.
            f"done_evidence_ac_error: FAILED AC: {named} -- an unmet acceptance criterion "
            "is a FAILED AC, never a deferral, and the item cannot move to done. Remedy: leave the "
            "item in an active/blocked status "
            "(`tautline backlog-provider-update --target . --item <item-ref> "
            "--status <active-status>`) and post the honest table on the linked issue, or fix the "
            "implementation and re-verify."
        )
    return issues


# The unfilled verdict placeholder, and it MUST NOT match `_AC_ROW_RE`. Codex R1 P1: the first
# spelling was `PASS|FAIL`, whose embedded pipe closes the verdict cell, so the regex read the
# skeleton's own placeholder as a real `PASS`. Handing the generated file straight back therefore
# satisfied every criterion and closed the item with no pass/fail decision made anywhere -- a gate
# that accepts its own blank form. `PASS or FAIL` cannot match: the verdict group is anchored right
# after the criterion cell, and ` or FAIL |` is not a closing pipe.
# test_the_unfilled_skeleton_is_refused_by_the_gate is the regression test; it asserts the REFUSAL,
# not the parse, because the parse is an implementation detail and the refusal is the property.
AC_TABLE_VERDICT_PLACEHOLDER = "PASS or FAIL"


def done_evidence_ac_table_skeleton(criteria: list[str]) -> str:
    """The fill-in table `tautline ac-verify` prints -- the single runnable continuation every
    refusal on this surface names. Unfilled, it is REFUSED by the gate: a skeleton that passes is a
    form that verifies itself."""
    lines = ["## AC Verification", "", "| Criterion | Verdict |", "| --- | --- |"]
    # A pipe inside the criterion text is ESCAPED, not passed through: an unescaped one opens a
    # third cell and the row stops parsing, so the verb would hand the lane a table its own gate
    # refuses (Codex R2 P2). `_ac_key` unescapes on the way back in, so the escaped cell still
    # matches the criterion it came from.
    lines += [
        f"| {_ac_key(criterion).replace('|', chr(92) + '|')} | {AC_TABLE_VERDICT_PLACEHOLDER} |"
        for criterion in criteria
    ]
    return "\n".join(lines) + "\n"


def evidence_claims_verification(body: str) -> bool:
    """True when an outgoing comment CLAIMS verification, and so must be measured against the
    issue's own acceptance criteria. The observed #357 defect was a verification comment on an item
    that never moved to done, so the done-move funnel alone does not cover the mechanism."""
    text = body or ""
    if re.search(r"(?im)^#{1,6}\s*verification(\s+evidence)?\s*:?\s*$", text):
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in _FORBIDDEN_ORACLE_PHRASES)


BACKLOG_LEAD_WHAT_HEADINGS = ["what this delivers", "what it delivers", "what is it", "what is this", "what"]


BACKLOG_LEAD_WHY_HEADINGS = ["why it matters", "why we care", "why this matters", "value", "what value", "business value"]


BACKLOG_LEAD_MIN_CHARS = 24


def _backlog_lead_section(text: str, headings: list[str]) -> tuple[int, str] | None:
    """Earliest-by-position heading matching any of `headings` (exact, case-insensitive, levels
    `#`-`######`), with its section content (to the next heading of any level). Using the EARLIEST
    occurrence keeps the content check and the ordering check on the SAME section, so a placeholder
    `## What` near the top cannot borrow content from a real `## What this delivers` lower down
    (Codex). Returns (position, content) or None."""
    names = {h.lower() for h in headings}
    best: tuple[int, str] | None = None
    for match in re.finditer(r"(?im)^#{1,6}\s*(.+?)\s*$", text):
        if match.group(1).strip().lower() in names and (best is None or match.start() < best[0]):
            rest = text[match.end():]
            next_heading = re.search(r"(?m)^#{1,6}\s+\S", rest)
            content = (rest[: next_heading.start()] if next_heading else rest).strip()
            best = (match.start(), content)
    return best


def _backlog_lead_section_content(text: str, headings: list[str]) -> str | None:
    section = _backlog_lead_section(text, headings)
    return section[1] if section is not None else None


def _backlog_lead_content_ok(content: str | None) -> bool:
    """Real plain-language content: enough characters AND several distinct words, so a placeholder
    like `xxxxxxxxxxxxxxxxxxxxxxxx` does not pass (mirrors the customer-facing justification guard)."""
    if content is None:
        return False
    if len(re.sub(r"\s+", "", content)) < BACKLOG_LEAD_MIN_CHARS:
        return False
    distinct_words = len({word for word in re.findall(r"[a-z0-9]+", content.lower()) if len(word) > 1})
    return distinct_words >= 4


def backlog_item_missing_business_lead(body: str) -> str:
    """Pure: every backlog item must LEAD with plain-language business framing -- what it delivers
    and why it matters -- before technical detail (RCA: items were rote technical readings with no
    business context). Returns a drift/refusal message naming what is missing, or '' when compliant.
    Empty/whitespace body is itself missing the lead."""
    text = body or ""
    what = _backlog_lead_section(text, BACKLOG_LEAD_WHAT_HEADINGS)
    why = _backlog_lead_section(text, BACKLOG_LEAD_WHY_HEADINGS)
    missing = []
    if what is None or not _backlog_lead_content_ok(what[1]):
        missing.append("a plain-language `## What this delivers` section")
    if why is None or not _backlog_lead_content_ok(why[1]):
        missing.append("a plain-language `## Why it matters` section")
    if missing:
        return (
            "backlog item does not lead with a business justification: it is missing "
            + " and ".join(missing)
            + ". Every item must explain in plain language what it delivers and why it matters before technical detail."
        )
    # Lead off: What and Why must be the FIRST section headings. Any other `##`+ section before
    # both of them (e.g. `## Technical detail`, `## Implementation notes`, `## Technical approach`)
    # means the item does not lead with the business justification. This catches every technical
    # heading variant without enumerating them; a leading `#` (level-1) title is ignored (Codex).
    business_names = {h.lower() for h in BACKLOG_LEAD_WHAT_HEADINGS + BACKLOG_LEAD_WHY_HEADINGS}
    lead_end = max(what[0], why[0])
    headings = list(re.finditer(r"(?im)^(#{1,6})\s*(.+?)\s*$", text))
    for idx, match in enumerate(headings):
        if match.start() >= lead_end:
            break
        if match.group(2).strip().lower() in business_names:
            continue
        # Allow a single leading level-1 document TITLE (first heading, `#`, with no substantial
        # body). A level-1 heading that carries real content before What/Why is a section, not a
        # title, and must NOT be skipped (Codex: `# Technical approach` with a paragraph).
        if idx == 0 and len(match.group(1)) == 1:
            section_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
            title_body = text[match.end():section_end]
            if len(re.sub(r"\s+", "", title_body)) < BACKLOG_LEAD_MIN_CHARS:
                continue
        return (
            f"backlog item does not lead with the business justification: the section `{match.group(2).strip()}` "
            "appears before `## What this delivers` / `## Why it matters`. Lead with the business framing, then technical detail."
        )
    return ""


STAKEHOLDER_QUESTION_MARKER = "tautline-question"


STAKEHOLDER_QUESTION_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=\"([^\"]*)\"")


def stakeholder_questions_config(data: dict) -> dict:
    return data["stakeholderQuestions"]


def stakeholder_questions_status_summary(data: dict) -> str:
    config = stakeholder_questions_config(data)
    if not config["enabled"]:
        return "stakeholder_questions: enabled=false"
    default = f" default={config['defaultMention']}" if config.get("defaultMention") else " default=unknown"
    sync = ",".join(config.get("syncAt", [])) or "none"
    return (
        "stakeholder_questions: enabled=true provider=github-issues"
        f"{default} open_label={config['openLabel']} answered_label={config['answeredLabel']} sync_at={sync}"
    )


def stakeholder_login_from_mention(mention: str) -> str:
    return mention.strip().lstrip("@").lower()


def stakeholder_question_marker(attrs: dict[str, str]) -> str:
    parts = []
    for key in ["id", "status", "asked_at", "answered_at", "stakeholder", "issue"]:
        value = str(attrs.get(key, "")).strip()
        if value:
            safe = value.replace('"', "'")
            parts.append(f'{key}="{safe}"')
    return f"<!-- {STAKEHOLDER_QUESTION_MARKER} {' '.join(parts)} -->"


def stakeholder_question_parse_markers(body: str) -> list[dict[str, str]]:
    markers = []
    for match in re.finditer(r"<!--\s*(?:tautline|minervit)-question\s+([^>]*)-->", body or ""):
        attrs = {key: value for key, value in STAKEHOLDER_QUESTION_ATTR_RE.findall(match.group(1))}
        if attrs.get("id"):
            markers.append(attrs)
    return markers


def stakeholder_question_answer_is_substantive(body: str) -> bool:
    text = re.sub(r"\s+", " ", body or "").strip()
    if len(text) < 24 or len(re.findall(r"[A-Za-z0-9]+", text)) < 4:
        return False
    non_answer_patterns = [
        r"(?i)^\+1$",
        r"(?i)^ok(?:ay)?[.!]?$",
        r"(?i)^thanks?[.!]?$",
        r"(?i)\b(looking into it|checking|i'?ll check|will check|get back to you|not sure yet|need to think|following up)\b",
    ]
    return not any(re.search(pattern, text) for pattern in non_answer_patterns)
