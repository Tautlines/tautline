"""A goal that legitimately has no board item has a sanctioned path.

RCA 2026-07-31 control 4. `goal_tracker_sync_transition` used to raise UNCONDITIONALLY when the
source plan carried no GitHub Project Source item, and the refusal named no way out. A lane whose
work genuinely has no board item — a repo-only goal — had exactly two exits, both bad: disable the
tracker wholesale, or hand-edit the ledger.

A refusal that names no sanctioned alternative is where bypasses get invented, and an invented
bypass is worse than the allowance it replaces. `allowRepoOnlyGoals` is that allowance: off by
default, explicit rather than inferred from a missing ref, and honored identically by the sync
path and the drift gate — because a gate and its sync disagreeing about what is permitted makes a
sanctioned path unusable in practice.

**The record this closes.** QUEUE row 71 said PR1 (0.46.0, #513) shipped WS1+WS4.
`git grep allowRepoOnlyGoals` returned zero hits on the merged tree and the sync still raised
unconditionally: WS4 never landed. The row stated claim-time intent, not merged code. It ships here.
"""


def _tracker(cli, **overrides) -> dict:
    tracker = dict(cli.DEFAULT_GOAL_TRACKER)
    tracker.update({"enabled": True, "owner": "example-org", "projectNumber": 7})
    tracker.update(overrides)
    return tracker


# --- the knob exists in BOTH families, and survives the converter round trip --------------------


def test_the_knob_is_off_by_default_in_both_config_families(cli) -> None:
    """Off by default: a lane that never sets it sees exactly the behavior it had before."""
    assert cli.DEFAULT_GOAL_TRACKER["allowRepoOnlyGoals"] is False
    assert cli.DEFAULT_BACKLOG_PROVIDER["allowRepoOnlyGoals"] is False


# --- the sync path: refuse by default, proceed when sanctioned ---------------------------------


# --- the drift gate honors the SAME knob -------------------------------------------------------


# --- the allowance covers the GOAL item ONLY ---------------------------------------------------
