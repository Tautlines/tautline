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
import pytest


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


@pytest.mark.parametrize("value", [True, False])
def test_the_knob_survives_the_converter_round_trip(cli, value: bool) -> None:
    """`load_project` round-trips legacy adapters through BOTH converters, so a key carried by only
    one family is silently dropped on the return leg — the setting would read as unset and the
    lane would meet a refusal it had explicitly configured away."""
    provider = dict(cli.DEFAULT_BACKLOG_PROVIDER)
    provider.update({"enabled": True, "owner": "example-org",
                     "projectNumber": 7, "allowRepoOnlyGoals": value})

    tracker = cli.goal_tracker_from_backlog_provider(provider)
    assert tracker["allowRepoOnlyGoals"] is value

    back = cli.backlog_provider_from_goal_tracker(tracker)
    assert back["allowRepoOnlyGoals"] is value


def test_a_legacy_adapter_missing_the_key_converts_without_raising(cli) -> None:
    """Defensively via `.get`: an adapter written before this key existed must convert,
    not crash."""
    provider = dict(cli.DEFAULT_BACKLOG_PROVIDER)
    provider.update({"enabled": True, "owner": "example-org", "projectNumber": 7})
    provider.pop("allowRepoOnlyGoals")

    assert cli.goal_tracker_from_backlog_provider(provider)["allowRepoOnlyGoals"] is False

    tracker = _tracker(cli)
    tracker.pop("allowRepoOnlyGoals")
    assert cli.backlog_provider_from_goal_tracker(tracker)["allowRepoOnlyGoals"] is False


# --- the sync path: refuse by default, proceed when sanctioned ---------------------------------


def test_without_the_knob_the_sync_refuses_and_names_it(cli, tmp_path, monkeypatch) -> None:
    """The refusal must name the sanctioned alternative. Naming none is what left the bypass as the
    only exit, which is the defect this closes -- so the refusal text is the control, not
    decoration."""
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: _tracker(cli))
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_sync_transition({}, tmp_path, {}, "goal-start")

    message = str(raised.value)
    assert "allowRepoOnlyGoals" in message
    assert "backlog-provider-sync" in message, "the sync remedy must still be offered first"
    assert "re-render" in message, "a source-adapter change is not live until the lane re-renders"


def test_with_the_knob_the_sync_proceeds_repo_only_and_says_so(
    cli, tmp_path, monkeypatch, capsys
) -> None:
    """Proceeding silently would be its own defect: the lane's board status is deliberately
    NOT updated for this goal, and the run has to state that rather than imply it."""
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")

    issues = cli.goal_tracker_sync_transition({}, tmp_path, {}, "goal-start")

    assert issues == []
    out = capsys.readouterr().out
    assert "goal_tracker_repo_only_goal:" in out
    assert "Board status is not updated" in out


def test_a_goal_that_does_have_an_item_is_unaffected_by_the_knob(
    cli, tmp_path, monkeypatch
) -> None:
    """The knob is an allowance for the MISSING-ref case only. A goal with a real item must take
    the normal path whether or not the knob is set, or the allowance would quietly become a
    board-sync opt-out."""
    synced = []
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "PVTI_real")
    monkeypatch.setattr(cli, "goal_tracker_milestone_ref", lambda t, m: "")
    monkeypatch.setattr(cli, "goal_tracker_primary_status", lambda tr, k: "In Progress")
    monkeypatch.setattr(
        cli, "goal_tracker_sync_status_update",
        lambda *a, **k: (synced.append(a[2]) or ("updated", ""), "")[0],
    )
    monkeypatch.setattr(cli, "goal_tracker_print_sync_result", lambda *a, **k: None)

    cli.goal_tracker_sync_transition({}, tmp_path, {}, "goal-start")

    assert synced == ["PVTI_real"], "a goal with a real item must still sync to the board"


# --- the drift gate honors the SAME knob -------------------------------------------------------


def test_without_the_knob_a_missing_item_is_drift(cli, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: _tracker(cli))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")

    issues = cli.goal_tracker_drift_issues({}, tmp_path, {})

    assert len(issues) == 1
    assert "allowRepoOnlyGoals" in issues[0]


def test_with_the_knob_a_missing_item_is_not_drift(cli, tmp_path, monkeypatch) -> None:
    """One knob, both paths. A gate reporting drift for the exact state its own sync sanctions
    would make the sanctioned path unusable -- the lane would be permanently 'drifting' by
    configuration."""
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")

    data = {"backlogProvider": dict(cli.DEFAULT_BACKLOG_PROVIDER)}

    assert cli.goal_tracker_drift_issues(data, tmp_path, {"milestones": []}) == []


# --- the allowance covers the GOAL item ONLY ---------------------------------------------------


def test_a_board_backed_milestone_still_syncs_under_a_repo_only_parent(
    cli, tmp_path, monkeypatch
) -> None:
    """Codex R1 P2. The allowance sanctions the missing GOAL item and nothing else. An early return
    turned a parent-goal allowance into a MILESTONE-sync opt-out -- silently, because the run
    reported success while writing nothing to the board."""
    synced = []
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")
    monkeypatch.setattr(cli, "goal_tracker_milestone_ref", lambda t, m: "PVTI_milestone")
    monkeypatch.setattr(cli, "goal_tracker_status_for_milestone", lambda d, m: "Done")
    monkeypatch.setattr(
        cli, "goal_tracker_sync_status_update",
        lambda *a, **k: (synced.append(a[2]) or ("updated", ""), "")[0],
    )
    monkeypatch.setattr(cli, "goal_tracker_print_sync_result", lambda *a, **k: None)

    cli.goal_tracker_sync_transition({}, tmp_path, {}, "milestone-complete", {"index": 1})

    assert synced == ["PVTI_milestone"], (
        "the board-backed milestone must still sync under a repo-only parent"
    )


def test_an_unmapped_milestone_under_a_repo_only_parent_writes_to_nothing(
    cli, tmp_path, monkeypatch
) -> None:
    """The pre-existing fallback rolls an unmapped milestone up to the PARENT goal item. A
    repo-only parent has no item to roll up to, so the fallback must not fire -- calling the board
    update with an empty ref would be a write against nothing."""
    synced = []
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")
    monkeypatch.setattr(cli, "goal_tracker_milestone_ref", lambda t, m: "")
    monkeypatch.setattr(
        cli, "goal_tracker_sync_status_update",
        lambda *a, **k: (synced.append(a[2]) or ("updated", ""), "")[0],
    )
    monkeypatch.setattr(cli, "goal_tracker_print_sync_result", lambda *a, **k: None)

    cli.goal_tracker_sync_transition({}, tmp_path, {}, "milestone-complete", {"index": 1})

    assert synced == [], "no board write is possible when neither goal nor milestone has an item"


def test_milestone_drift_is_still_checked_under_a_repo_only_parent(
    cli, tmp_path, monkeypatch
) -> None:
    """Same rule from the gate side: an adapter that tracks milestones still has board-backed
    milestones to check under a repo-only parent. Skipping the loop would report a clean board for
    milestones nobody looked at."""
    provider = dict(cli.DEFAULT_BACKLOG_PROVIDER)
    provider.update({"enabled": True, "itemTypes": ["goal", "milestone"]})
    data = {"backlogProvider": provider}
    run = {"milestones": [{"index": 1, "title": "M1", "status": "complete"}]}
    monkeypatch.setattr(
        cli, "goal_tracker_config", lambda d: _tracker(cli, allowRepoOnlyGoals=True)
    )
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda d, t, r: "")
    monkeypatch.setattr(cli, "goal_tracker_milestone_ref", lambda t, m: "")

    issues = cli.goal_tracker_drift_issues(data, tmp_path, run)

    assert issues, "a completed milestone with no board mapping must still be reported"
    assert any("milestone" in i.lower() for i in issues), issues
