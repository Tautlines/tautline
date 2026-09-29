"""Every surface describing round-budget reset semantics must match the counter.

Three prior passes each corrected one surface while another kept contradicting it. PR #600's RCA
records two of them; the third claimed in its commit message to have checked EVERY OCCURRENCE and
still left `core/runtime.py` asserting the opposite.

This test exists so a fourth cannot happen silently. It does two things a hand check cannot:

1. It pins each enumerated surface against the counter's ACTUAL behaviour at 0.135.0/0.136.0 --
   both negatively (the falsified wordings are gone) and POSITIVELY (the true claims are present).
   Absence of the old sentence is not presence of the right one: a surface saying "rebasing grants
   a fresh quota" contains none of the historical phrases and is still wrong.

2. It DISCOVERS candidate surfaces across every tree that can ship such a claim, so a new one has
   to join the list rather than drift from it. Scanning only `methodology/` would have missed both
   surfaces that were still wrong -- they live in `src/` and `plugins/`.
"""

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

RESET_SEMANTICS_SURFACES = (
    ("src/tautline_methodology/core/runtime.py", "hard-cap refusal"),
    ("methodology/canonical-rules.md", "canonical rule 258"),
    ("methodology/policy/17-review-before-push.md", "policy 17"),
    (
        "plugins/tautline-core/skills/review-before-push/references/"
        "review-before-push-policy.md",
        "review-before-push skill reference",
    ),
    # Enumerated by DISCOVERY, not by hand -- it explains the ceiling in release notes and in the
    # counter's own docstrings, and a hand-written list had never included it. It passes both
    # checks today; enumerating it keeps it that way.
    ("src/tautline_methodology/cli.py", "counter internals and release notes"),
)

# One "not a negation" step, reused below: any char except a sentence end, so long as we are not
# standing on a negation word. Lets a pattern demand trigger-and-effect while letting "cannot
# refill" through as the true statement it is.
_NOT = r"(?:(?!\b(?:cannot|can't|never|does not|doesn't|do not|no longer|not|nor)\b)[^.])"

# True before 0.135.0/0.136.0, false now.
FALSIFIED_CLAIMS = (
    (r"counter resets on a base change", "the ceiling is base-independent since 0.135.0"),
    (r"[Aa]ny base change[^.]*resets the counter", "the ceiling is base-independent since 0.135.0"),
    (r"nothing enforces that but you", "the successor case is enforced since 0.136.0"),
    (r"it is unenforced today", "the enforcement question is now stated precisely, see below"),
    # AND the inverse overstatement, which this repository authored while fixing the first four.
    # `--acknowledge-reset` records metadata; `implementation_review_observed_executions` counts
    # only THIS branch's manifests and the capped-predecessor check stops firing once the
    # successor has a durable row, so the successor DOES get its own quota. It is an audited
    # reset. Claiming the spend is inherited or the obligation enforced is the same defect
    # inverted -- prose asserting a guarantee the tooling does not provide.
    (
        r"successor case is ENFORCED|inherits the spend|spend is inherited",
        "the acknowledgement is an AUDITED reset, not inherited spend",
    ),
    # The refill family. A surface can contradict the ceiling rule without using any wording
    # above -- "rebasing grants a fresh quota" is the reviewer's own example. Checked FILE-WIDE
    # precisely so a correct passage elsewhere cannot mask them.
    #
    # TEMPERED AGAINST NEGATIONS. The first draft flagged this file's own correct sentence, "so a
    # rebase cannot refill the cap": the trigger and the effect were both present, only the
    # negation made it true. A checker that cannot tell a claim from its denial reports the
    # correct text as the defect, and the natural response is to delete the checker.
    (
        rf"(?:rebas\w+|retarget\w*|base change){_NOT}{{0,80}}"
        rf"(?:grants?|gives?|earns?){_NOT}{{0,40}}(?:fresh|new)\s+(?:quota|budget|rounds?)",
        "a rebase does not grant a fresh quota; the ceiling counts across bases",
    ),
    (
        rf"(?:rebas\w+|retarget\w*|base change){_NOT}{{0,80}}refills?{_NOT}{{0,40}}"
        r"(?:budget|cap|quota)",
        "nothing refills the ceiling; it counts the branch's spend across bases",
    ),
)

# Every surface that DISCUSSES A RESET must get the ceiling right. Checked against the reset
# passage only -- a whole-file search for a generic word like "refuses" is a control that reports
# success while doing nothing, since `runtime.py` carries dozens of unrelated refusal messages and
# would satisfy it even with the clause deleted.
REQUIRED_OF_EVERY_RESET_PASSAGE = (
    (
        r"does not reset|base-independent|across bases|not reset|no longer reset",
        "must state that the ceiling survives a base change",
    ),
)

# Every tree that can ship a claim about the ceiling.
SCANNED_TREES = (
    ("methodology", "*.md"),
    ("src/tautline_methodology", "*.py"),
    ("plugins", "*.md"),
)

# A LIVE ASSERTION about the round-budget counter, not any sentence containing the word "reset".
# Requires base-change context, which is what separates this counter from the Stop-guard retry
# counter that also "resets" (`cli.py:11929`) and has nothing to do with review budgets.
# Equivalent wordings count. Requiring the literal pair "base change" + "reset" let a surface say
# "rebasing grants a fresh quota" or "a retarget refills the budget" and never be enumerated at
# all -- the drift this test exists to prevent, wearing different words.
_TRIGGER = r"base change|rebase|rebasing|retarget"
_EFFECT = r"reset|refill|fresh quota|fresh budget|starts over"
DISCOVERY_PATTERN = re.compile(
    rf"(?:{_TRIGGER})[^.]{{0,160}}(?:{_EFFECT})|(?:{_EFFECT})[^.]{{0,160}}(?:{_TRIGGER})",
    re.IGNORECASE,
)

def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


def _reset_passages(text: str) -> list[str]:
    """EACH sentence that discusses a reset, separately. Never joined.

    Two reasons, both found by review:

    1. A whole-FILE search satisfies "must mention refusal" from any unrelated refusal message, so
       the assertion would survive deleting the very clause it is meant to pin.
    2. Joining the passages is just as bad: one correct sentence then satisfies the check for a
       contradictory one beside it. Adding "rebasing grants a fresh quota" to a file that also says
       "across bases" would PASS -- the exact regression this test claims to reject.

    So every passage is validated on its own, and all of them must hold.
    """
    return [s for s in re.split(r"(?<=[.;])\s+", text) if DISCOVERY_PATTERN.search(s)]


def test_every_surface_claiming_a_reset_is_enumerated():
    """A new surface asserting a counter reset must join the list above, not drift from it."""
    listed = {rel for rel, _ in RESET_SEMANTICS_SURFACES}
    found = set()
    for subdir, pattern in SCANNED_TREES:
        for path in (REPO / subdir).rglob(pattern):
            if DISCOVERY_PATTERN.search(path.read_text(encoding="utf-8", errors="replace")):
                found.add(str(path.relative_to(REPO)))
    unenumerated = sorted(found - listed)
    assert not unenumerated, (
        "these surfaces assert a counter reset but are not enumerated in "
        f"RESET_SEMANTICS_SURFACES: {unenumerated}"
    )


# --- The refusals a lane actually reads -------------------------------------------------------
#
# Regexing a 2.5MB module is the wrong instrument for these two. It cannot tell an
# IMPLEMENTATION-review claim from a PLAN-review one, and that distinction is real: plan review
# walks the chain via `--predecessor` and genuinely DOES sum a lineage's members, so
# "a successor inherits every round already spent" is TRUE there and must not be flagged.
# Implementation review counts each branch's own executions, so the same sentence is FALSE there.
#
# So these assert on the rendered STRING each function returns. Bounded, unambiguous, and
# impossible to satisfy from unrelated text elsewhere in the file.


# NEGATION-AWARE, for the third time in this file. "not inherited spend" is the CORRECT sentence;
# a checker that flags it reports the fix as the defect. The lookbehind is the whole difference
# between pinning a claim and pinning the word.
_INHERITANCE_CLAIMS = re.compile(
    r"inherits every round|inherit the spend|carry the spend|(?<!not )inherited spend",
    re.IGNORECASE,
)
