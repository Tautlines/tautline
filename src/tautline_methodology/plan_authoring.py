"""Plan-Authoring Standard: the required shape of a Tautline T1+ plan.

Pure leaf module (no cli imports) so the checker + knob are unit-testable in
isolation and only thin wiring touches the cli.py monolith. The verbatim
standard block is a single str, so it is auto-excluded from the policy-phrases
SSOT (which collects only non-empty list[str]); see policy.policy_phrase_constants.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

PLAN_AUTHORING_ENFORCEMENT_CHOICES: tuple[str, ...] = ("off", "observe", "advise", "block")
DEFAULT_PLANNING_AUTHORING_STANDARD: dict = {"enforcement": "advise"}

# The convention every hand-authored goal in this repo already follows (see
# ready/*/goal-*.txt in the backlog): a goal prompt sits beside its plan, named
# `goal-<something>.txt`. Existence-only -- content is `goal-assignment --check`'s job.
GOAL_PROMPT_ARTIFACT_GLOB = "goal*.txt"

# The `goal-assignment` skill's OWN documented Fast Path (`--out .ai-work/goal.txt`) writes a
# fixed, target-relative path rather than one beside the plan. Codex R1 P2: without this, the
# sanctioned workflow never clears `block` enforcement. Checked in addition to, never instead
# of, the beside-the-plan glob.
GOAL_PROMPT_FALLBACK_RELATIVE_PATH = ".ai-work/goal.txt"

# The three-part marker contract (authoritative; shared with skill + canonical rule).
_WORKSTREAMS_HEADING = re.compile(r"(?im)^#{1,3}\s+workstreams?\b")
# Leading \b only: `\bdepend` matches depends/dependency/dependent (depend at a word start)
# but NOT "independently" (depend mid-word), which the standard itself uses in "independently
# testable" and must not satisfy the dependency marker. No trailing \b (breaks the suffixes).
_DEPENDENCY = re.compile(r"(?i)(\bdepend|parallel-safe|predecessor|dependency graph)")
_MODEL_TIER = re.compile(r"(?i)\bmodel-tier:\s*(mechanical|standard|deep)\b")
_BEST_JUDGMENT = re.compile(r"(?i)\bbest judgment\b")
_DECISION_RECORD = re.compile(r"(?i)\bdecision-record\b")

PLAN_AUTHORING_MARKERS: dict[str, str] = {
    "workstreams": _WORKSTREAMS_HEADING.pattern,
    "dependency": _DEPENDENCY.pattern,
    "model_tier": _MODEL_TIER.pattern,
    "autonomy": _BEST_JUDGMENT.pattern,
    "decision_record": _DECISION_RECORD.pattern,
}

STANDING_PLAN_AUTHORING_STANDARD_CORE: str = (
    "STANDING PLAN-AUTHORING STANDARD\n"
    "Author this plan as parallel autonomous workstreams, not a linear sequence:\n"
    "- A `## Workstreams` section with an explicit dependency graph naming which "
    "workstreams are parallel-safe and which have hard predecessors, each assigned "
    "its own git worktree / isolation.\n"
    "- Every task tagged `model-tier: mechanical|standard|deep` so token spend is "
    "routed by difficulty.\n"
    "- Every task carries the execution-autonomy contract in its own text: use best "
    "judgment, record non-obvious decisions with `tautline decision-record`, do not "
    "stop for permission mid-task, and if blocked work exhaustively on the rest.\n"
    "- Each task ends with an independently testable deliverable and a review gate.\n"
    "- A build-ready plan ships its goal prompt alongside it (`goal*.txt`, composed "
    "with `tautline goal-assignment --out`).\n"
)


def _workstreams_section(text: str) -> str | None:
    """The text of the Workstreams section -- from its heading to the next heading of the same
    or higher level (or end of document). None if there is no Workstreams heading. Scoping the
    dependency check here stops an empty `## Workstreams` heading plus dependency language in an
    unrelated section (e.g. a `## Dependencies` block) from satisfying `block` enforcement."""
    m = _WORKSTREAMS_HEADING.search(text)
    if not m:
        return None
    heading = re.match(r"#+", text[m.start():])
    level = len(heading.group(0)) if heading else 2
    for nxt in re.finditer(r"(?m)^(#{1,6})\s", text[m.end():]):
        if len(nxt.group(1)) <= level:
            return text[m.start(): m.end() + nxt.start()]
    return text[m.start():]


def plan_authoring_standard_issues(plan_text: str) -> list[str]:
    """Return missing-element messages for the plan text; empty means compliant."""
    text = plan_text or ""
    issues: list[str] = []
    section = _workstreams_section(text)
    if section is None or not _DEPENDENCY.search(section):
        issues.append(
            "missing a `## Workstreams` section with a dependency graph "
            "(parallel-safe vs. hard-predecessor) inside that section. Add one per the "
            "plan-authoring standard."
        )
    if not _MODEL_TIER.search(text):
        issues.append(
            "no per-task `model-tier:` tags found (mechanical|standard|deep). "
            "Tag each task so spend is routed by difficulty."
        )
    if not (_BEST_JUDGMENT.search(text) and _DECISION_RECORD.search(text)):
        issues.append(
            "missing the embedded execution-autonomy contract (a 'best judgment' line "
            "and a `decision-record` reference) in the task text."
        )
    return issues


def plan_missing_goal_prompt_issue(
    plan_path: Path, *, target: Path | None = None, plan_ref: str | None = None
) -> str | None:
    """None if a goal-prompt artifact exists AND names this plan; otherwise the issue message.

    Candidates are every `GOAL_PROMPT_ARTIFACT_GLOB` file beside the plan, plus
    `<target>/GOAL_PROMPT_FALLBACK_RELATIVE_PATH` when `target` is given (the
    `goal-assignment` skill's own documented Fast Path writes there, not beside the plan --
    Codex R1 P2).

    BOUND to this plan, not just present: a candidate must contain the plan's own filename
    (every composed goal states its plan path verbatim -- "from the finalized plan `<ref>`" --
    so this is the same signal the composer already writes). Codex R1 P1: without this, the
    FIRST plan in a directory to get a goal silently satisfies `block` enforcement for every
    OTHER plan sharing that directory, which is exactly this repo's own flat
    `docs/superpowers/plans/` layout.

    Content is otherwise unexamined -- whether a bound candidate is a VALID goal (within the
    char cap, states the handoff bar) is `goal-assignment --check`'s job, not this one's.

    `plan_ref` is the string a caller would pass to `--plan` (target-relative, or the
    `<root>:...` form for an externally-rooted plan) -- used only in the printed remedy command,
    which otherwise (Codex R1 P2) suggests the plan's bare filename and fails when copy-pasted
    for any plan not sitting at the target root. Callers with no target context may omit it.
    """
    plan_name = plan_path.name

    # Codex R1 (this round) P2: matching ANY occurrence of the plan's name/ref anywhere in the
    # candidate's text is too loose once two plans can legitimately be mentioned in the same
    # goal prompt for reasons other than binding (a milestone note, a "see also"). The composer
    # (`compose_goal_assignment`) always states the bound plan in exactly one place -- the
    # source-plan clause "... from the finalized plan `<plan_ref>`." -- so parse THAT clause and
    # compare its captured reference, instead of approximating "looks like a delimited path"
    # against the whole text (which a punctuation-containing filename, e.g. "my plan.md", could
    # also satisfy by accident; a backtick-delimited exact capture has no such approximation).
    _SOURCE_PLAN_CLAUSE = re.compile(r"from the finalized plan `([^`]*)`")

    def _fallback_ref_proves_this_plan(bound_ref: str) -> bool:
        # Codex R1 P2 (this lineage): the TARGET-WIDE fallback is one file for the whole target,
        # so the bare-basename degradation would let a goal naming `ready/item-a/plan.md`
        # satisfy `ready/item-b/plan.md` -- the documented basename-collision class. Without a
        # caller-supplied `plan_ref`, the fallback binds only on proof: a directory-carrying
        # bound ref must RESOLVE (target-relative) to this very plan file; a bare ref (the
        # sanctioned Fast Path writes just the basename) keeps the basename rule, whose
        # ambiguity is scoped to same-named plans the composer itself could not tell apart.
        if "/" not in bound_ref:
            return bound_ref == plan_name
        if target is None:
            return False
        try:
            return (target / bound_ref).resolve() == plan_path.resolve()
        except OSError:
            return False

    def _binds_this_plan(text: str, *, fallback_candidate: bool = False) -> bool:
        for match in _SOURCE_PLAN_CLAUSE.finditer(text):
            bound_ref = match.group(1)
            if fallback_candidate and not plan_ref:
                if _fallback_ref_proves_this_plan(bound_ref):
                    return True
                continue
            if plan_ref:
                # Codex R1 (third + final confirming rounds) P1/P2, still true for an exact
                # compare: a caller-supplied `plan_ref` is the full reference the composer was
                # given, so only an exact match binds -- no suffix/substring leniency needed
                # now that we are comparing the parsed clause, not scanning raw text.
                if bound_ref == plan_ref:
                    return True
            else:
                # Codex R1 (second confirming round) P1: no `plan_ref` context (caller has none
                # to give) degrades to the bare-basename signal -- the bound ref must END with
                # this basename, at a real path boundary (start of the ref, or immediately after
                # `/`), not merely contain it as a substring (which is what let "long-plan.md"
                # falsely satisfy "plan.md" before, and would let "my plan.md" falsely satisfy
                # "plan.md" via naive delimiter-approximation).
                if bound_ref == plan_name or bound_ref.endswith("/" + plan_name):
                    return True
        return False

    candidates: list[Path] = []
    try:
        candidates.extend(sorted(plan_path.parent.glob(GOAL_PROMPT_ARTIFACT_GLOB)))
    except OSError:
        pass
    fallback: Path | None = None
    if target is not None:
        fallback = target / GOAL_PROMPT_FALLBACK_RELATIVE_PATH
        if fallback not in candidates and fallback.is_file():
            candidates.append(fallback)
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _binds_this_plan(text, fallback_candidate=candidate == fallback):
            return None
    ref = plan_ref if plan_ref is not None else plan_name
    # Codex R1 (confirming round) P3: an unquoted plan reference containing whitespace or shell
    # metacharacters (e.g. a path with a space) breaks the copy-pasted remedy command into the
    # wrong number of arguments. shlex.quote makes the printed command runnable verbatim.
    compose_hint = (
        "compose one with `tautline goal-assignment --plan "
        f"{shlex.quote(ref)} --out <dir>/goal-<name>.txt`"
    )
    if candidates:
        names = ", ".join(dict.fromkeys(c.name for c in candidates))
        return (
            f"a goal prompt artifact exists ({names}) but none of them names this plan "
            f"('{plan_name}' does not appear in its text); a build-ready plan's goal prompt must "
            f"reference ITS OWN plan, not a sibling's -- {compose_hint}"
        )
    return (
        f"no goal prompt artifact ({GOAL_PROMPT_ARTIFACT_GLOB}, or "
        f"{GOAL_PROMPT_FALLBACK_RELATIVE_PATH} under the lane target) found for {plan_name}; a "
        f"build-ready plan ships one so a builder lane is not asked for it by hand -- "
        f"{compose_hint}"
    )


def normalize_planning_authoring_standard(data: dict) -> dict:
    """Read-side normalizer (Pattern B — never written back into the adapter, so an
    absent knob stays absent on disk and no existing adapter needs regeneration)."""
    planning = data.get("planning")
    if planning is not None and not isinstance(planning, dict):
        raise SystemExit("Project adapter planning must be an object")
    raw = (planning or {}).get("authoringStandard")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter planning.authoringStandard must be an object")
    cfg = {**DEFAULT_PLANNING_AUTHORING_STANDARD, **(raw or {})}
    if cfg["enforcement"] not in PLAN_AUTHORING_ENFORCEMENT_CHOICES:
        raise SystemExit(
            "Project adapter planning.authoringStandard.enforcement must be "
            "off, observe, advise, or block"
        )
    return cfg


PLAN_CONTENT_PREGATE_ENFORCEMENT_CHOICES = ("off", "warn", "block")
DEFAULT_PLAN_CONTENT_PREGATE = {"enforcement": "warn"}


def normalize_planning_content_pregate(data: dict) -> dict:
    """Read-side normalizer for `planning.contentPregate`, shaped like its sibling above.

    Defaults to `warn`, not `block`, and that is a BINDING decision rather than timidity. The
    framework's own item-34 lineage says a plan legitimately grows, so auto-refusing a
    section-shaped gap at round zero would refuse plans that were about to be fine. Every
    enforcement surface this program has shipped landed warn-first with a deliberate, separately
    released flip -- templateCoverage, goLiveReadiness, the METH-FU precedent -- and this one
    follows them. The successor that flips the default is one enum change plus one inverted test,
    and it is gated on the shipped template having had a release for fleets to converge on.

    Pattern B: never written back, so an absent knob stays absent and no adapter needs
    regeneration.
    """
    planning = data.get("planning")
    if planning is not None and not isinstance(planning, dict):
        raise SystemExit("Project adapter planning must be an object")
    raw = (planning or {}).get("contentPregate")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter planning.contentPregate must be an object")
    cfg = {**DEFAULT_PLAN_CONTENT_PREGATE, **(raw or {})}
    if cfg["enforcement"] not in PLAN_CONTENT_PREGATE_ENFORCEMENT_CHOICES:
        raise SystemExit(
            "Project adapter planning.contentPregate.enforcement must be off, warn, or block"
        )
    return cfg


def partition_pregate_errors(issues: list[str]) -> tuple[list[str], list[str]]:
    """Split content issues into `(refusable, advisory)`.

    Length and marker heuristics stay ADVISORY even under `block`: they are proxies for quality,
    and a proxy that refuses is a proxy that gets gamed. Section-shaped gaps -- a plan with no
    assumptions, no dependencies, no acceptance criteria, no completion definition -- are the ones
    a reviewer cannot work around and a author can fix for free before any round is spent.
    """
    # WHITELIST THE REFUSABLE, do not blacklist the advisory. Blacklisting phrases means every
    # heuristic string nobody thought to list defaults to BLOCKING -- and that is exactly what
    # happened: `validate_plan_substance` emits "plan is too short to be decision-complete", which
    # matched none of the advisory phrases and so refused a plan whose sections were all present,
    # contradicting the rule this function exists to implement. Codex R2 P2. Defaulting to advisory
    # means a new heuristic is quiet until someone deliberately makes it refusable.
    refusable_markers = ("missing substantive sections",)
    refusable, advisory = [], []
    for issue in issues:
        text = str(issue)
        (refusable if any(m in text.lower() for m in refusable_markers) else advisory).append(text)
    return refusable, advisory


PLAN_TEMPLATE_COVERAGE_ENFORCEMENT_CHOICES = ("off", "report")
DEFAULT_PLAN_TEMPLATE_COVERAGE = {"enforcement": "report"}


def normalize_planning_template_coverage(data: dict) -> dict:
    """Read-side normalizer for `planning.templateCoverage`.

    REPORT-ONLY by construction: the enum has no blocking value at all, so there is no way to
    configure this into a refusal. A template is a starting point, and a lane that deleted a
    section it does not need has not done anything wrong -- the report exists so the TEMPLATE can
    be measured against the contract, not so lanes can be policed for editing it.
    """
    planning = data.get("planning")
    if planning is not None and not isinstance(planning, dict):
        raise SystemExit("Project adapter planning must be an object")
    raw = (planning or {}).get("templateCoverage")
    if raw is not None and not isinstance(raw, dict):
        raise SystemExit("Project adapter planning.templateCoverage must be an object")
    cfg = {**DEFAULT_PLAN_TEMPLATE_COVERAGE, **(raw or {})}
    if cfg["enforcement"] not in PLAN_TEMPLATE_COVERAGE_ENFORCEMENT_CHOICES:
        raise SystemExit(
            "Project adapter planning.templateCoverage.enforcement must be off or report"
        )
    return cfg


# A plan this large in a single unbroken scope section is usually several plans wearing one name.
# Measured, not guessed: the shipped corpus in docs/superpowers/plans/ sits below these, and the
# items that actually fractured mid-build (57, 62, 75) sat above them.
PLAN_SCOPE_ADVISORY_MIN_LINES = 700
PLAN_SCOPE_ADVISORY_MIN_TASKS = 24
PLAN_SCOPE_ADVISORY_MIN_WORKSTREAMS = 5


def plan_scope_advisory(plan_text: str) -> list[str]:
    """A HINT that a plan may be too big to review in one budget. Never blocking, anywhere, ever.

    THREE CONJUNCTS, not one. Any single measure fires constantly on legitimate plans -- a long
    plan may be thorough, many tasks may be mechanical, many workstreams may be genuinely
    parallel. It is the COMBINATION that has predicted a fracture, and requiring all three is what
    keeps this quiet on the compliant plans it must not nag.

    Deliberately advisory forever: sizing is a judgement, and a gate that refuses on a judgement
    it cannot justify teaches lanes to game the measure rather than to split the work. The value
    is the sentence, not an exit code.
    """
    lines = plan_text.splitlines()
    if len(lines) < PLAN_SCOPE_ADVISORY_MIN_LINES:
        return []
    tasks = sum(1 for line in lines if re.match(r"\s*[-*]\s+T\d", line) or "model-tier:" in line)
    if tasks < PLAN_SCOPE_ADVISORY_MIN_TASKS:
        return []
    workstreams = len(re.findall(r"(?mi)^#+\s*WS\d|^\s*[-*]\s*WS\d\b", plan_text))
    if workstreams < PLAN_SCOPE_ADVISORY_MIN_WORKSTREAMS:
        return []
    return [
        f"this plan is {len(lines)} lines with {tasks} tagged tasks across {workstreams} "
        "workstreams -- all three together, which has predicted a mid-build fracture before. "
        "Consider splitting it into source-of-truth plans that can each be reviewed in one "
        "budget. ADVISORY ONLY: nothing here refuses, and a plan that is genuinely this large "
        "is allowed to be."
    ]
