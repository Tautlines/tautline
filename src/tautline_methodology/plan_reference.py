"""The rooted plan reference: `<root>:<relative-path>`.

Item 59 W1 (`docs/superpowers/plans/2026-08-02-plan-root-schema.md`). A recorded plan reference
used to be a bare relative path whose root was implied by whichever code read it. That
under-specification is what let `ready/item-a/plan.md` and `ready/item-b/plan.md` slug to the same
`.plan-reviews/plan.json` and overwrite each other's review evidence.

Pure leaf: no `cli` import, no subprocess, no filesystem -- `merge_gate.py` is the precedent.

**This module holds no set of valid roots, deliberately (R4 P1).** It decides *shape* -- is this
`<token>:<path>`, and what are the halves. The configured resolver decides *validity*, because
that is where the configuration to judge a token actually lives. An allowlist here could only be
wrong in one of two ways: hardcoding `backlog` would reject `tautline-backlog:`, the single
spelling the feature exists to support; or this leaf would grow config knowledge and stop being a
leaf. Unknown tokens are a loud error in the resolver, not here.

The token shape is narrow on purpose: non-empty, and no path separator. Every manifest written
before this release holds a bare relative path meaning "relative to this lane", and if any colon
could promote its prefix to a root, a legacy path that happens to contain one would silently
change meaning the day this ships. A too-narrow token misreads a rooted reference as a lane path,
which the resolver then reports as a missing file -- loud, and recoverable. The reverse is silent
and corrupts recorded evidence. So the narrow shape is the safe direction to err in.

`lane` is the one reserved literal, and it outranks a configured planRepo basename that collides
with it (decision recorded 2026-08-03): a planRepo directory literally named `lane` is refused at
`validate-adapter` rather than allowed to shadow the reserved meaning.
"""
from __future__ import annotations

from typing import NamedTuple

#: The reserved root token meaning "relative to this lane's own checkout". A bare legacy string
#: parses to this root, which is what keeps every pre-existing manifest meaning what it meant.
LANE_ROOT = "lane"

_SEPARATOR = "/"
_ROOT_DELIMITER = ":"


class PlanReference(NamedTuple):
    """A plan reference split into its root token and its root-relative path."""

    root: str
    relative: str


def _is_root_token(candidate: str) -> bool:
    """Shape test only: a root token is non-empty and carries no path separator."""
    return bool(candidate) and _SEPARATOR not in candidate


def parse_plan_reference(text: str) -> PlanReference:
    """Split `text` into `(root, relative)`, deciding shape and nothing else.

    A bare relative path yields the reserved `lane` root, so strings recorded before this release
    keep their meaning exactly. Any token shape is accepted -- judging whether a token names a
    configured root belongs to the resolver.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("plan reference is empty")

    head, delimiter, tail = stripped.partition(_ROOT_DELIMITER)
    if not delimiter or not _is_root_token(head):
        # No delimiter, or a prefix that cannot be a token -- this is a lane-relative path, and
        # returning it unchanged is what preserves legacy meaning.
        return PlanReference(LANE_ROOT, stripped)

    if not tail:
        raise ValueError(f"plan reference {stripped!r} names root {head!r} but no relative path")

    return PlanReference(head, tail)


def render_plan_reference(root: str, relative: str) -> str:
    """Render `(root, relative)` as `<root>:<relative>`.

    The root is always written explicitly, including for `lane`: reading accepts the bare legacy
    form, writing does not produce it, so recorded references converge on the rooted spelling
    without any existing string having to change meaning first.
    """
    if not root:
        raise ValueError("plan reference root is empty")
    if _ROOT_DELIMITER in root:
        raise ValueError(f"plan reference root {root!r} contains a colon")
    if _SEPARATOR in root:
        raise ValueError(f"plan reference root {root!r} contains a path separator")
    if not relative:
        raise ValueError(f"plan reference root {root!r} has no relative path")
    return f"{root}{_ROOT_DELIMITER}{relative}"
