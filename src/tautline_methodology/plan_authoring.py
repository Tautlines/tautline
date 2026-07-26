"""Plan-Authoring Standard: the required shape of a Tautline T1+ plan.

Pure leaf module (no cli imports) so the checker + knob are unit-testable in
isolation and only thin wiring touches the cli.py monolith. The verbatim
standard block is a single str, so it is auto-excluded from the policy-phrases
SSOT (which collects only non-empty list[str]); see policy.policy_phrase_constants.
"""
from __future__ import annotations

import re

PLAN_AUTHORING_ENFORCEMENT_CHOICES: tuple[str, ...] = ("off", "observe", "advise", "block")
DEFAULT_PLANNING_AUTHORING_STANDARD: dict = {"enforcement": "advise"}

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
