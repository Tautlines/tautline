"""Item 74 PR-C / policy 16a: the go-live readiness profile.

**The enforcement boundary is the design, and it was chosen against a measured constraint.**
`methodology-status --target . --fail-on-drift` is the mandated lane-start command rendered into
every generated adapter, and `adapters/projects/example-saas.json` already carries a
`milestoneClose` deployment target. A drift failure keyed on "milestone-close target without the
profile" would therefore red every live-surface lane at session start on upgrade, with no
migration -- the adapter-removal 0.6.115 class, where a control shipped faster than lanes could
adopt it and had to be reverted.

So a lane that has not opted in gets a warn line and nothing else, at any flag combination; the
forcing function is a shipped, tested switch rather than silence.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rows(**states):
    return [{"control": control, "state": state, "detail": ""} for control, state in states.items()]


def _all_blocking(cli):
    return _rows(**{control: "block" for control in cli.GO_LIVE_CONTROLS})


LIVE_SURFACE = {"deploymentTargets": [{"name": "web", "milestoneClose": True}]}


# --- the un-opted lane: warn only, never a failure ----------------------------------------------


# --- the opted-in lane: held to the gates -------------------------------------------------------


# --- the table and the policy module must name the same gates -----------------------------------


# --- Codex R1: a crash, a deadlock, and a safety classification that would have been false --------


def test_the_adoption_checklist_exists_and_names_every_live_adapter(cli):
    """Codex R4. "Gated on adoption" is a sentence unless the gate has a written criterion.

    The release claims the default flip to `block` is gated on adoption. Without a checklist there
    is nothing to be gated ON: no enumeration of the lanes that must adopt, and no zero-open
    criterion. This asserts the list exists AND covers every adapter that would be affected, because
    a checklist that silently stops covering new lanes reports zero open rows while lanes go
    untracked -- worse than none.
    """
    checklist = (REPO_ROOT / "docs" / "backlog" / "methodology-backlog.md").read_text(
        encoding="utf-8"
    )
    assert "Go-live readiness adoption checklist" in checklist

    # It names the ENUMERATION COMMAND rather than transcribing adapters. A hand-typed list goes
    # stale the moment an adapter gains a milestone-close target, and a checklist that silently
    # stops covering new lanes reports zero open rows while lanes go untracked. The command cannot
    # go stale, and the public-boundary scan independently forbids naming a product here.
    assert "grep -ln milestoneClose adapters/projects/*.json" in checklist
    assert "zero open rows" in checklist
    # ...and the command it names must actually find the live lanes.
    live = [
        path.name
        for path in sorted((REPO_ROOT / "adapters" / "projects").glob("*.json"))
        if "milestoneClose" in path.read_text(encoding="utf-8")
    ]
    assert live, "the enumeration command finds nothing; the checklist would be vacuous"


# --- Codex R2: three more ways a control can look satisfied while asserting nothing --------------
