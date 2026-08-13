"""RCA: provider-backed lanes must keep the stakeholder board current at all times.

Pure-function coverage for the board-currency reconciliation (issue/PR state vs board status)
and the provider-disabled no-op. The gh-integration path degrades gracefully and is exercised
by scripts/validate.sh against the fake-gh harness.
"""

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "methodology" / "canonical-rules.md"
BACKLOG_PROVIDER_REFERENCE = ROOT / "docs" / "reference" / "operations" / "backlog-provider-workflow.md"
STAKEHOLDER_QUESTIONS_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "stakeholder-questions"
    / "references"
    / "stakeholder-questions-policy.md"
)
# Post the package-split flip (roadmap #11): the engine (these pinned verb/flag/handler strings)
# lives in cli.py; bin/tautline is a thin shim.
CLI = ROOT / "src" / "tautline_methodology" / "cli.py"
ADAPTER_SCHEMA = ROOT / "methodology" / "adapter-schema.json"
EXAMPLE_ADAPTER = ROOT / "adapters" / "projects" / "example-saas.json"
DONE = ["Done"]


@pytest.fixture(autouse=True)
def _offline_schema_mismatch_check(cli, monkeypatch):
    monkeypatch.setattr(cli, "goal_tracker_schema_mismatch_issues", lambda data, target: [])


def _assert_contains_all(path: Path, phrases: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [phrase for phrase in phrases if phrase not in text]
    assert missing == [], f"{path.relative_to(ROOT)} missing: {missing}"


def test_board_currency_policy_and_hook_contracts_remain_pinned():
    _assert_contains_all(
        CANONICAL,
        [
            "no excuses, no deviations",
            "Board currency is a blocking gate",
        ],
    )
    _assert_contains_all(
        CLI,
        [
            "backlog-provider-board-check",
            "guard-check --target . --boundary prepush",
            "backlog_provider_board_check",
        ],
    )


def test_backlog_provider_policy_commands_remain_pinned():
    _assert_contains_all(
        CANONICAL,
        [
            "adapter `backlogProvider.enabled` is true",
            "do not execute directly from a raw Project item",
            "Provider-backed status is live operational state",
            "free-text comments do not replace the structured Project `Status` field",
            "Provider-backed goal and milestone status must remain current",
            "issue comments are not a substitute for structured board `Status`",
        ],
    )
    _assert_contains_all(
        BACKLOG_PROVIDER_REFERENCE,
        [
            "Backlog-provider exports create real, numbered repository issues",
            "Board-only GitHub Project draft items are not a valid fulfillment of an ordinary export",
            "backlog-provider-status --target .",
            "backlog-provider-sync --target . --item <id-or-url> --write",
            "backlog-provider-migration-interview --target . --write",
            "stakeholder-question-ask",
            "stakeholder-question-status --target . --sync",
            "That write refreshes the repo plan and moves the selected board item plus any board-backed native subtasks to the first adapter-approved active status before planning/review work proceeds.",
        ],
    )
    _assert_contains_all(
        STAKEHOLDER_QUESTIONS_REFERENCE,
        [
            "If no stakeholder is configured, ask the",
            "human operator one exact blocker question naming the missing stakeholder",
            "persist the answer in the project adapter",
        ],
    )


def test_board_export_and_work_order_contracts_remain_pinned():
    _assert_contains_all(
        CANONICAL,
        [
            "stakeholder board exists only for customer-facing functionality",
            "board's order is the work order by default",
            "no epic assigned",
        ],
    )
    _assert_contains_all(
        BACKLOG_PROVIDER_REFERENCE,
        [
            "only and exclusively",
            "physical top-to-bottom ordering is the exact order work is taken",
        ],
    )
    _assert_contains_all(
        CLI,
        [
            "--customer-facing",
            "board_export_non_customer_facing_signal",
        ],
    )

    schema = json.loads(ADAPTER_SCHEMA.read_text(encoding="utf-8"))
    provider_props = schema["properties"]["backlogProvider"]["properties"]
    assert provider_props["workOrder"]["enum"] == ["board", "priority"]
    assert provider_props["epicField"]["type"] == "string"

    example = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    assert example["backlogProvider"]["workOrder"] == "board"
    assert example["backlogProvider"]["epicField"] == "Epic"


def test_closed_item_not_done_is_drift(cli):
    msg = cli.board_item_state_drift("Fix bug", "https://x/issues/9", "In Progress", "CLOSED", DONE)
    assert msg and "not a done status" in msg


def test_merged_item_not_done_is_drift(cli):
    msg = cli.board_item_state_drift("Feature", "https://x/pull/9", "Ready", "MERGED", DONE)
    assert msg and "not a done status" in msg


def test_open_item_marked_done_is_drift(cli):
    msg = cli.board_item_state_drift("Feature", "https://x/issues/9", "Done", "OPEN", DONE)
    assert msg and "overstates completion" in msg


def test_consistent_states_are_clean(cli):
    assert cli.board_item_state_drift("a", "u", "In Progress", "OPEN", DONE) == ""
    assert cli.board_item_state_drift("a", "u", "Done", "CLOSED", DONE) == ""
    assert cli.board_item_state_drift("a", "u", "Done", "MERGED", DONE) == ""


def test_unknown_state_never_guesses(cli):
    # No state in the payload -> never flag (older gh output / drafts).
    assert cli.board_item_state_drift("a", "u", "In Progress", "", DONE) == ""
    assert cli.board_item_state_drift("a", "u", "Done", "", DONE) == ""
    assert cli.board_item_state_drift("a", "u", "Done", "DRAFT", DONE) == ""


def test_content_state_extraction(cli):
    assert cli.board_item_content_state({"content": {"state": "closed"}}) == "CLOSED"
    assert cli.board_item_content_state({"state": "OPEN"}) == "OPEN"
    assert cli.board_item_content_state({"content": {"closed": True}}) == "CLOSED"
    assert cli.board_item_content_state({"content": {"title": "x"}}) == ""  # no state -> ""


def test_non_customer_facing_signal_detects_tech_debt(cli):
    # The board is exclusively customer-facing; tech-debt/cleanup/internal work must be flagged.
    for title, summary in [
        ("Refactor checkout internals", "clean up dead code"),
        ("Technical debt: pricing module", "no customer impact"),
        ("Bump dependency versions", "upgrade deps"),
        ("Fix flaky test in CI pipeline", "internal tooling"),
        ("Improve developer experience", "devx improvement"),
        ("Fix internal inventory bug", "internal bug in admin-only flow"),
        ("Admin-only dashboard fix", "back-office tooling"),
    ]:
        assert cli.board_export_non_customer_facing_signal(title, summary), (title, summary)


def test_customer_facing_items_have_no_signal(cli):
    for title, summary in [
        ("Add guest checkout", "Let customers check out without an account"),
        ("Fix checkout email not sending", "Customers do not receive order confirmation emails"),
        ("Pickup time selection on storefront", "Customers choose a pickup window"),
    ]:
        assert cli.board_export_non_customer_facing_signal(title, summary) == "", (title, summary)


CONFIGURED = ["Ready", "In progress", "Done", "Blocked"]


def test_unconfigured_status_is_drift(cli):
    # An item parked in a status the adapter does not enumerate (e.g. an ad-hoc review column)
    # is drift: lanes must ship straight to a done status, never stage in a review/QA column.
    msg = cli.board_item_unconfigured_status_drift("Parked", "https://x/issues/77", "In review", CONFIGURED)
    assert msg and "unconfigured status" in msg and "In review" in msg


def test_configured_statuses_are_clean(cli):
    for status in CONFIGURED:
        assert cli.board_item_unconfigured_status_drift("a", "u", status, CONFIGURED) == "", status
    # case-insensitive match against the configured set
    assert cli.board_item_unconfigured_status_drift("a", "u", "in PROGRESS", CONFIGURED) == ""


def test_empty_status_is_not_flagged(cli):
    # No status set yet (untriaged item) is not drift -- we never guess.
    assert cli.board_item_unconfigured_status_drift("a", "u", "", CONFIGURED) == ""
    assert cli.board_item_unconfigured_status_drift("a", "u", "   ", CONFIGURED) == ""


def _enabled_provider(scope_query):
    # Minimal enabled backlogProvider that passes normalize, varying only scopeQuery.
    return {
        "enabled": True, "provider": "github-projects", "owner": "minervit", "projectNumber": 7,
        "scopeQuery": scope_query, "statusField": "Status", "linkPolicy": "links",
        "readyStatuses": ["Ready"], "activeStatuses": ["In progress"], "doneStatuses": ["Done"],
        "blockedStatuses": ["Blocked"], "authoritativeFor": ["goal-status"], "repoPlanRequired": True,
        # Item 81's oracle-discipline gate reads the linked issue's BODY, which means a `gh issue
        # view` subprocess on every done move. It defaults to `warn` in the product and has its own
        # suite (tests/test_done_evidence_ac_table.py); leaving it live here would make this module
        # -- which is about board currency -- shell out to the network per test and report an
        # `unknown` degrade that says nothing about board currency.
        "doneEvidence": {"acTable": "off"},
    }


def test_scope_query_status_predicate_detector(cli):
    # Codex P2/P3: catch real status predicates (incl. GitHub's has:/no: existence qualifiers and
    # negation), but never overmatch a status-like substring inside another qualifier's value.
    for bad in ["status:Ready", "-status:Done", "label:ready status:Done", "no:status", "has:status", "-no:status"]:
        assert cli.scope_query_filters_status(bad, "Status"), bad
    for ok in [
        "", "label:ready", "label:customer-facing -label:wontfix", "assignee:@me",
        'label:"status:ready"', 'title:"Status: ready note"', "mystatus:ready", "custom-status:ready",
    ]:
        assert not cli.scope_query_filters_status(ok, "Status"), ok


def test_scope_query_status_predicate_is_rejected(cli):
    # normalize must reject a status-scoped query so the no-review-column enforcement can't be scoped away.
    import pytest
    for bad in ["status:Ready", "-status:Done", "no:status", "has:status"]:
        with pytest.raises(SystemExit):
            cli.normalize_tracker_adapter_config(_enabled_provider(bad), cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider")


def test_scope_query_without_status_predicate_is_allowed(cli):
    for ok in ["", "label:ready", "label:customer-facing -label:wontfix", 'label:"status:ready"']:
        cfg = cli.normalize_tracker_adapter_config(_enabled_provider(ok), cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider")
        assert cfg["scopeQuery"] == ok


def test_enabled_provider_allows_empty_blocked_statuses(cli):
    """C1a: a board with no 'Blocked' column (empty blockedStatuses) must normalize WITHOUT raising
    while enabled — board-adopt of the canonical Funnel/Todo/In progress/Done shape produces exactly
    this, and requiring it would write a self-invalidating adapter that bricks every later load."""
    provider = _enabled_provider("")
    provider["blockedStatuses"] = []
    cfg = cli.normalize_tracker_adapter_config(provider, cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider")
    assert cfg["enabled"] is True
    assert cfg["blockedStatuses"] == []


def test_enabled_provider_still_requires_ready_active_done(cli):
    """C1a guardrail: the relaxation is scoped to blockedStatuses ONLY — an empty
    readyStatuses/activeStatuses/doneStatuses must STILL raise when enabled."""
    import pytest
    for key in ("readyStatuses", "activeStatuses", "doneStatuses"):
        provider = _enabled_provider("")
        provider[key] = []
        with pytest.raises(SystemExit):
            cli.normalize_tracker_adapter_config(provider, cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider")


def test_provider_disabled_is_noop(cli, tmp_path):
    data = {"goalTracker": {"enabled": False}, "backlogProvider": {"enabled": False}}
    drift, unavailable, warnings = cli.provider_board_currency_issues(data, tmp_path, None)
    assert drift == [] and unavailable == [] and warnings == []


ACTIVE = ["In progress"]


def test_active_work_in_backlog_is_drift(cli):
    msg = cli.board_item_active_work_drift(
        "Pickup capacity", "https://x/issues/234", "Backlog", "OPEN", True, ACTIVE
    )
    assert msg and "not an active status" in msg and "In progress" in msg


def test_active_work_already_active_is_clean(cli):
    assert cli.board_item_active_work_drift(
        "Pickup capacity", "https://x/issues/234", "In progress", "OPEN", True, ACTIVE
    ) == ""


def test_no_active_work_signal_is_clean(cli):
    # An item nobody is working may legitimately sit in Backlog.
    assert cli.board_item_active_work_drift(
        "Future idea", "https://x/issues/9", "Backlog", "OPEN", False, ACTIVE
    ) == ""


def test_active_work_non_open_never_guesses(cli):
    # Closed/unknown state is handled by board_item_state_drift; this detector
    # only speaks to OPEN items, and never guesses on unknown state.
    assert cli.board_item_active_work_drift("a", "u", "Backlog", "CLOSED", True, ACTIVE) == ""
    assert cli.board_item_active_work_drift("a", "u", "Backlog", "", True, ACTIVE) == ""


def _enabled_tracker():
    # A normalized goalTracker block (goal_tracker_config reads data["goalTracker"] directly).
    return {
        "enabled": True, "provider": "github-projects", "owner": "minervit", "projectNumber": 7,
        "scopeQuery": "", "statusField": "Status",
        "readyStatuses": ["Ready"], "activeStatuses": ["In progress"],
        "doneStatuses": ["Done"], "blockedStatuses": ["Blocked"],
    }


def _enabled_data():
    return {"goalTracker": _enabled_tracker(), "backlogProvider": _enabled_provider("")}


def test_active_work_item_in_backlog_blocks_current_lane(cli, tmp_path, monkeypatch):
    # RCA Jun-16 #234 hotfix: a verified current-work item still in Backlog is blocking drift.
    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Backlog")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["234"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)
    assert any("understates progress" in d for d in drift)
    assert not any("understates progress" in w for w in warnings)


def test_active_parent_board_subtask_in_ready_blocks_current_lane(cli, tmp_path, monkeypatch):
    # Native GitHub sub-issues that are also board items inherit the active-work status obligation.
    # The parent issue's status is not enough; the board-backed subtask must be current too.
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Checkout parent",
            "state": "OPEN",
        },
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Checkout subtask",
            "state": "OPEN",
        },
    }
    statuses = {"PVTI_parent": "In progress", "PVTI_child": "Ready"}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: statuses[it["id"]])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"url": "https://github.com/o/r/issues/235", "title": "Checkout subtask"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["234"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )

    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)

    assert unavailable == []
    assert warnings == []
    assert any("board subtask understates progress" in d and "https://github.com/o/r/issues/235" in d for d in drift)


def test_active_parent_subtask_detection_uses_content_url_when_project_item_has_own_url(
    cli, tmp_path, monkeypatch
):
    # GitHub Project payloads can expose a project-item URL at top level and the issue URL under
    # content.url. Current-work detection must use the linked issue URL, or parent/subtask status
    # drift is missed for branches that close the parent issue number.
    parent = {
        "id": "PVTI_parent",
        "url": "https://github.com/orgs/o/projects/7/views/1?pane=issue&itemId=parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Checkout parent",
            "state": "OPEN",
        },
    }
    child = {
        "id": "PVTI_child",
        "url": "https://github.com/orgs/o/projects/7/views/1?pane=issue&itemId=child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Checkout subtask",
            "state": "OPEN",
        },
    }
    statuses = {"PVTI_parent": "In progress", "PVTI_child": "Ready"}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: statuses[it["id"]])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"url": "https://github.com/o/r/issues/235", "title": "Checkout subtask"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(
        cli,
        "lane_work_scope",
        lambda data, target: {
            "ledger_ref": "",
            "outgoing_issue_numbers": ["234"],
            "working_tree_refs": [],
            "unresolved_ledger": False,
        },
    )

    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)

    assert unavailable == []
    assert warnings == []
    assert any("board subtask understates progress" in d and "https://github.com/o/r/issues/235" in d for d in drift)


def test_subtask_status_matching_rejects_cross_repo_issue_number_collision(cli, tmp_path, monkeypatch):
    # Org-level Projects can include multiple repos with the same issue number. Subtask discovery must
    # match on strong issue identifiers (node id/url), never on a bare issue number.
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Checkout parent",
            "state": "OPEN",
        },
    }
    real_child = {
        "id": "PVTI_real_child",
        "content": {
            "id": "ISSUE_real_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Checkout real subtask",
            "state": "OPEN",
        },
    }
    unrelated_same_number = {
        "id": "PVTI_other_child",
        "content": {
            "id": "ISSUE_other_child",
            "url": "https://github.com/o/other/issues/235",
            "title": "Other repo item",
            "state": "OPEN",
        },
    }
    statuses = {
        "PVTI_parent": "In progress",
        "PVTI_real_child": "Ready",
        "PVTI_other_child": "Ready",
    }
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(
        cli,
        "goal_tracker_items",
        lambda data, target, limit=400: [parent, real_child, unrelated_same_number],
    )
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: statuses[it["id"]])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"url": "https://github.com/o/r/issues/235", "number": 235}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["234"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )

    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)

    assert unavailable == []
    assert warnings == []
    assert any("https://github.com/o/r/issues/235" in d for d in drift)
    assert not any("https://github.com/o/other/issues/235" in d for d in drift)


def test_unrelated_ledger_item_does_not_block_board_current_outgoing_work(cli, tmp_path, monkeypatch):
    # The prior false-block class remains closed: when the branch has its own tracked board item,
    # a stale ledger pointing elsewhere is not treated as the current work item.
    items = [
        {"id": "PVTI_234", "content": {"url": "https://github.com/o/r/issues/234", "title": "Old goal", "state": "OPEN"}},
        {"id": "PVTI_334", "content": {"url": "https://github.com/o/r/issues/334", "title": "Current branch", "state": "OPEN"}},
    ]
    statuses = {"PVTI_234": "Backlog", "PVTI_334": "In progress"}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: items)
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: statuses[it["id"]])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "PVTI_234", "outgoing_issue_numbers": ["334"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)
    assert not any("understates progress" in d for d in drift)
    assert unavailable == [] and warnings == []


def test_backlog_provider_board_check_blocks_current_active_work_drift(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "lane_project", lambda args: (_enabled_data(), tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_run_path", lambda data, target: tmp_path / ".ai-work" / "GOAL_RUN.json")
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Backlog")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["234"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )
    monkeypatch.setattr(cli, "print_provider_board_business_lead_warnings", lambda data, target: [])
    monkeypatch.setattr(cli, "print_unplaced_customer_facing_issue_warnings", lambda data, target: [])

    rc = cli.backlog_provider_board_check(SimpleNamespace(strict=False))

    assert rc == 1
    err = capsys.readouterr().err
    assert "backlog_provider_board_issue:" in err
    assert "understates progress" in err


def test_backlog_provider_active_check_blocks_current_active_work_drift(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "lane_project", lambda args: (_enabled_data(), tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_run_path", lambda data, target: tmp_path / ".ai-work" / "GOAL_RUN.json")
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Backlog")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["234"],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )

    rc = cli.backlog_provider_active_check(SimpleNamespace(strict=False))

    assert rc == 1
    err = capsys.readouterr().err
    assert "backlog_provider_active_issue:" in err
    assert "understates progress" in err


def test_backlog_provider_update_done_requires_and_posts_evidence(cli, tmp_path, monkeypatch):
    from types import SimpleNamespace

    posted = {}
    data = _enabled_data()
    data["repo"] = "o/r"
    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: item)
    monkeypatch.setattr(cli, "goal_tracker_update_status", lambda data, target, item_ref, status: {"item_id": "PVTI_1", "status": status, "output": ""})

    def _post(data, target, issue_number, body, **_ac_kwargs):
        posted["issue_number"] = issue_number
        posted["body"] = body
        return "https://github.com/o/r/issues/234#issuecomment-1"

    monkeypatch.setattr(cli, "stakeholder_issue_post_comment", _post)
    args = SimpleNamespace(
        item="PVTI_1",
        status="Done",
        verification_evidence="command: npm test\nPASS",
        verification_evidence_file=None,
        verification_evidence_url=None,
    )

    assert cli.backlog_provider_update(args) == 0
    assert posted["issue_number"] == "234"
    assert "## Verification Evidence" in posted["body"]
    assert "PASS" in posted["body"]


def test_backlog_provider_update_done_updates_closed_board_backed_subtasks(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    posted = []
    calls = []
    data = _enabled_data()
    data["repo"] = "o/r"
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Parent",
            "state": "CLOSED",
        },
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Child",
            "state": "CLOSED",
        },
        "fieldValues": {"Status": "In progress"},
    }
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: parent if ref == "PVTI_parent" else child)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/235"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: item["content"]["state"])
    monkeypatch.setattr(
        cli,
        "stakeholder_issue_post_comment",
        lambda data, target, issue_number, body, **_ac_kwargs: (
            posted.append((issue_number, body))
            or f"https://github.com/o/r/issues/{issue_number}#issuecomment-1"
        ),
    )
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.backlog_provider_update(
        SimpleNamespace(
            item="PVTI_parent",
            status="Done",
            verification_evidence="pytest -q\nPASS",
            verification_evidence_file=None,
            verification_evidence_url=None,
        )
    )

    assert rc == 0
    assert calls == [("PVTI_child", "Done"), ("PVTI_parent", "Done")]
    assert [issue for issue, _body in posted] == ["235", "234"]
    assert all("PASS" in body for _issue, body in posted)
    out = capsys.readouterr().out
    assert "backlog_provider_update_subtask_status_parent_ref: PVTI_parent" in out
    assert "backlog_provider_update_subtask_status_update: ok" in out


def test_backlog_provider_update_active_claims_native_parent_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    calls = []
    data = _enabled_data()
    data["repo"] = "o/r"
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/336",
            "title": "Parent",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "Ready"},
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/337",
            "title": "Child",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "Ready"},
    }
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: child if ref == "PVTI_child" else parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/337"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: item["content"]["state"])
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.backlog_provider_update(
        SimpleNamespace(
            item="PVTI_child",
            status="In progress",
            verification_evidence=None,
            verification_evidence_file=None,
            verification_evidence_url=None,
        )
    )

    assert rc == 0
    assert calls == [("PVTI_child", "In progress"), ("PVTI_parent", "In progress")]
    out = capsys.readouterr().out
    assert "backlog_provider_update_parent_active_subtask_ref: PVTI_child" in out
    assert "backlog_provider_update_parent_active_parent_ref: PVTI_parent" in out
    assert "backlog_provider_update_parent_active_claim: ok" in out


def test_backlog_provider_update_active_does_not_reopen_terminal_parent(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    calls = []
    data = _enabled_data()
    data["repo"] = "o/r"
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/336",
            "title": "Parent",
            "state": "CLOSED",
        },
        "fieldValues": {"Status": "Done"},
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/337",
            "title": "Child",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "Ready"},
    }
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: child if ref == "PVTI_child" else parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/337"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: item["content"]["state"])
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.backlog_provider_update(
        SimpleNamespace(
            item="PVTI_child",
            status="In progress",
            verification_evidence=None,
            verification_evidence_file=None,
            verification_evidence_url=None,
        )
    )

    assert rc == 0
    assert calls == [("PVTI_child", "In progress")]
    out = capsys.readouterr().out
    assert "backlog_provider_update_parent_active_claim: skipped_terminal_status" in out


def test_backlog_provider_update_done_blocks_when_board_backed_subtask_open(cli, tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace

    posted = []
    calls = []
    data = _enabled_data()
    data["repo"] = "o/r"
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Parent",
            "state": "CLOSED",
        },
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Child",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "In progress"},
    }
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: parent if ref == "PVTI_parent" else child)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/235"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: item["content"]["state"])
    monkeypatch.setattr(
        cli,
        "stakeholder_issue_post_comment",
        lambda data, target, issue_number, body, **_ac_kwargs: (
            posted.append((issue_number, body)) or "posted"
        ),
    )
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    with pytest.raises(SystemExit, match="finish or close the subtask before closing the parent"):
        cli.backlog_provider_update(
            SimpleNamespace(
                item="PVTI_parent",
                status="Done",
                verification_evidence="pytest -q\nPASS",
                verification_evidence_file=None,
                verification_evidence_url=None,
            )
        )

    assert calls == []
    assert posted == []


def test_backlog_provider_update_done_blocks_when_native_subtask_is_not_on_board(cli, tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace

    posted = []
    calls = []
    data = _enabled_data()
    data["repo"] = "o/r"
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Parent",
            "state": "CLOSED",
        },
        "fieldValues": {"Status": "In progress"},
    }
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/235"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: item["content"]["state"])
    monkeypatch.setattr(
        cli,
        "stakeholder_issue_post_comment",
        lambda data, target, issue_number, body, **_ac_kwargs: (
            posted.append((issue_number, body)) or "posted"
        ),
    )
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    with pytest.raises(SystemExit, match="native sub-issue\\(s\\) are not board items"):
        cli.backlog_provider_update(
            SimpleNamespace(
                item="PVTI_parent",
                status="Done",
                verification_evidence="pytest -q\nPASS",
                verification_evidence_file=None,
                verification_evidence_url=None,
            )
        )

    assert calls == []
    assert posted == []


def test_done_evidence_prefers_linked_content_url(cli):
    item = {
        "url": "https://github.com/orgs/minervit/projects/7/views/1?pane=issue&itemId=234",
        "content": {"url": "https://github.com/o/r/issues/234"},
    }

    assert cli.goal_tracker_item_issue_number(item) == "234"


def test_goal_tracker_update_done_requires_evidence(cli, tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace

    data = _enabled_data()
    data["repo"] = "o/r"
    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: item)
    monkeypatch.setattr(cli, "goal_tracker_update_status", lambda data, target, item_ref, status: {"item_id": "PVTI_1", "status": status, "output": ""})

    args = SimpleNamespace(
        item="PVTI_1",
        status="Done",
        verification_evidence="",
        verification_evidence_file=None,
        verification_evidence_url=None,
    )

    with pytest.raises(SystemExit, match="requires verification evidence"):
        cli.goal_tracker_update(args)


def test_goal_tracker_sync_done_posts_verification_evidence(cli, tmp_path, monkeypatch):
    posted = {}
    data = _enabled_data()
    data["repo"] = "o/r"
    item = {"content": {"url": "https://github.com/o/r/issues/234", "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda data, target, run: "PVTI_1")
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: item)
    monkeypatch.setattr(cli, "goal_tracker_update_status", lambda data, target, item_ref, status: {"item_id": "PVTI_1", "status": status, "output": ""})

    def _post(data, target, issue_number, body, **_ac_kwargs):
        posted["issue_number"] = issue_number
        posted["body"] = body
        return "https://github.com/o/r/issues/234#issuecomment-1"

    monkeypatch.setattr(cli, "stakeholder_issue_post_comment", _post)

    cli.goal_tracker_sync_transition(
        data,
        tmp_path,
        {"status": "complete"},
        "goal-complete",
        done_evidence="pytest -q\n754 passed",
    )

    assert posted["issue_number"] == "234"
    assert "754 passed" in posted["body"]


def test_goal_tracker_sync_transition_claims_board_backed_subtasks_active(cli, tmp_path, monkeypatch):
    calls = []
    data = _enabled_data()
    parent = {
        "id": "PVTI_parent",
        "content": {
            "id": "ISSUE_parent",
            "url": "https://github.com/o/r/issues/234",
            "title": "Parent",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "Ready"},
    }
    child = {
        "id": "PVTI_child",
        "content": {
            "id": "ISSUE_child",
            "url": "https://github.com/o/r/issues/235",
            "title": "Child",
            "state": "OPEN",
        },
        "fieldValues": {"Status": "Ready"},
    }
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda data, target, run: "PVTI_parent")
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, ref: parent if ref == "PVTI_parent" else child)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/235"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    cli.goal_tracker_sync_transition(data, tmp_path, {"status": "in_progress"}, "goal-start")

    assert calls == [("PVTI_parent", "In progress"), ("PVTI_child", "In progress")]


def test_unlinked_ledger_is_warning_not_block(cli, tmp_path, monkeypatch):
    # RCA Jun-17 + Codex review: an unlinked active ledger is a NON-blocking WARNING, never drift --
    # even an unverified branch number (#999 not on board) never blocks now.
    item = {"content": {"url": "https://github.com/o/r/issues/334", "title": "M2", "state": "OPEN"}}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "In progress")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": ["999"],
                              "working_tree_refs": [], "unresolved_ledger": True},
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda data, target, run: "")
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, {"goalId": "stale"})
    assert not any("GitHub Project Source" in d for d in drift)  # ledger never blocks
    assert any("active goal ledger" in w and "GitHub Project Source" in w for w in warnings)


def test_whole_project_state_drift_still_blocks(cli, tmp_path, monkeypatch):
    # Integrity-critical 0.6.97 currency is UNCHANGED: a closed item not in a done status BLOCKS.
    item = {"content": {"url": "https://github.com/o/r/issues/500", "title": "Shipped", "state": "CLOSED"}}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "In progress")  # closed but not done
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "CLOSED")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": [],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)
    assert any("not a done status" in d for d in drift)  # still blocks


def test_p3_title_only_ledger_ref_does_not_false_block(cli):
    # P3: a title-only ledger/plan ref must NOT match a different board item by a title suffix
    # (board_item_matches_strong_ref ignores title), so it cannot produce a spurious active-work block.
    item = {"id": "PVTI_a", "content": {"url": "https://github.com/o/r/issues/9", "title": "pickup scheduling"}}
    assert cli.board_item_matches_strong_ref(item, "Add pickup scheduling") is False
    assert cli.board_item_matches_strong_ref(item, "PVTI_a") is True  # id still matches
    assert cli.board_item_matches_strong_ref(item, "https://github.com/o/r/issues/9") is True  # url matches


def test_p2_changed_plan_ref_safe_on_md_directory(cli, tmp_path, monkeypatch):
    # P2: a `.md` path that resolves to a directory must not crash the gate (IsADirectoryError).
    md_dir = tmp_path / "weird.md"
    md_dir.mkdir()
    monkeypatch.setattr(cli, "run_git", lambda target, args: " M weird.md")
    assert cli.lane_changed_plan_refs(tmp_path) == []  # skipped, no crash


def test_unplaced_customer_facing_issue_warned(cli, tmp_path, monkeypatch):
    # An open issue that reads customer-facing (no tech-debt marker) and is NOT a board item.
    board_item = {"content": {"url": "https://github.com/o/r/issues/200", "title": "On board"}}
    repo_issues = [
        {"url": "https://github.com/o/r/issues/316", "title": "Customers cannot view orders",
         "body": "Customers cannot see their orders", "state": "OPEN"},
        {"url": "https://github.com/o/r/issues/317", "title": "Refactor checkout internals",
         "body": "internal cleanup, no customer impact", "state": "OPEN"},
        {"url": "https://github.com/o/r/issues/200", "title": "On board", "body": "x", "state": "OPEN"},
    ]
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [board_item])
    monkeypatch.setattr(cli, "goal_tracker_gh_json", lambda args, target, timeout=30: repo_issues)
    unplaced = cli.lane_unplaced_customer_facing_issues(_enabled_data(), tmp_path)
    assert any("316" in u for u in unplaced)        # customer-facing, missing -> flagged
    assert not any("317" in u for u in unplaced)     # tech-debt marker -> ignored
    assert not any("200" in u for u in unplaced)     # already on the board -> ignored


def test_unplaced_issue_check_noop_when_provider_disabled(cli, tmp_path):
    data = {"goalTracker": {"enabled": False}, "backlogProvider": {"enabled": False}}
    assert cli.lane_unplaced_customer_facing_issues(data, tmp_path) == []


def test_unplaced_issue_check_safe_when_gh_unreadable(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [])
    monkeypatch.setattr(cli, "goal_tracker_gh_json", lambda args, target, timeout=30: None)  # gh failure
    assert cli.lane_unplaced_customer_facing_issues(_enabled_data(), tmp_path) == []


def test_p1a_ledger_pvti_id_matches_board_item_active_work(cli, tmp_path, monkeypatch):
    # P1-A: the active ledger's project_item_id is a PVTI_ node id, not a URL. The reconciler must
    # match it against the board item's id (goal_tracker_item_matches), not a url-only endswith.
    item = {"id": "PVTI_lAHOAabc123", "content": {"url": "https://github.com/o/r/issues/234",
            "title": "Pickup", "state": "OPEN"}}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Backlog")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "PVTI_lAHOAabc123", "outgoing_issue_numbers": [],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, {"goalId": "g"})
    assert any("understates progress" in d for d in drift)


def test_p1c_working_tree_spec_ref_flags_active_work(cli, tmp_path, monkeypatch):
    # P1-C: a working-tree-changed plan/spec mapping (its ## GitHub Project Source) makes that board
    # item active work even with no PR and no ledger link.
    item = {"id": "PVTI_x", "content": {"url": "https://github.com/o/r/issues/234", "title": "M1", "state": "OPEN"}}
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [item])
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Backlog")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "OPEN")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": [],
                              "working_tree_refs": ["https://github.com/o/r/issues/234"],
                              "unresolved_ledger": True},
    )
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, None)
    assert any("understates progress" in d for d in drift)


def _sync_enabled_data():
    tracker = dict(_enabled_tracker(), priorityField="", milestoneField="", linkPolicy="links", authoritativeFor=["goal-status"])
    provider = dict(_enabled_provider(""), priorityField="", milestoneField="", typeField="", completionUnit="goal")
    return {"goalTracker": tracker, "backlogProvider": provider}


def test_goal_tracker_sync_write_claims_item_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    item = {"id": "PVTI_1", "title": "Build thing", "url": "https://github.com/o/r/issues/1",
            "fieldValues": {"Status": "Ready"}}
    plan_path = tmp_path / "backlog" / "plans" / "goals" / "build-thing.md"
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: item)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: plan_path)
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Build thing\n")
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": "PVTI_1", "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_1", write=True))

    assert rc == 0
    assert plan_path.read_text(encoding="utf-8") == "# Build thing\n"
    assert calls == [("PVTI_1", "In progress")]
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: ok" in out
    assert "goal_tracker_sync_active_status: In progress" in out


def test_goal_tracker_sync_write_does_not_move_already_active_item(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    item = {"id": "PVTI_3", "title": "Active thing", "url": "https://github.com/o/r/issues/3",
            "fieldValues": {"Status": "In progress"}}
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: item)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "active.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active thing\n")
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [])
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": "PVTI_3", "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_3", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: already_active" in out


def test_goal_tracker_sync_claims_board_backed_subtasks_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Active parent",
        "url": "https://github.com/o/r/issues/30",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/30", "title": "Active parent"},
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "title": "Ready subtask",
        "url": "https://github.com/o/r/issues/31",
        "content": {"id": "ISSUE_child", "url": "https://github.com/o/r/issues/31", "title": "Ready subtask"},
        "fieldValues": {"Status": "Ready"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active parent\n")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/31"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=True))

    assert rc == 0
    assert calls == [("PVTI_child", "In progress")]
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: already_active" in out
    assert "goal_tracker_sync_subtask_active_parent_ref: PVTI_parent" in out
    assert "goal_tracker_sync_subtask_active_claim: ok" in out


def test_goal_tracker_sync_selected_subtask_claims_native_parent_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Parent",
        "url": "https://github.com/o/r/issues/336",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/336", "title": "Parent", "state": "OPEN"},
        "fieldValues": {"Status": "Ready"},
    }
    child = {
        "id": "PVTI_child",
        "title": "Subtask",
        "url": "https://github.com/o/r/issues/337",
        "content": {"id": "ISSUE_child", "url": "https://github.com/o/r/issues/337", "title": "Subtask", "state": "OPEN"},
        "fieldValues": {"Status": "Ready"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: child if item_ref == "PVTI_child" else parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "subtask.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Subtask\n")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/337"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_child", write=True))

    assert rc == 0
    assert calls == [("PVTI_child", "In progress"), ("PVTI_parent", "In progress")]
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: ok" in out
    assert "goal_tracker_sync_parent_active_subtask_ref: PVTI_child" in out
    assert "goal_tracker_sync_parent_active_parent_ref: PVTI_parent" in out
    assert "goal_tracker_sync_parent_active_claim: ok" in out


def test_goal_tracker_sync_does_not_claim_terminal_subtask_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Active parent",
        "url": "https://github.com/o/r/issues/40",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/40", "title": "Active parent"},
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "title": "Done subtask",
        "url": "https://github.com/o/r/issues/41",
        "content": {"id": "ISSUE_child", "url": "https://github.com/o/r/issues/41", "title": "Done subtask"},
        "fieldValues": {"Status": "Done"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active parent\n")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/41"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_subtask_active_claim: skipped_terminal_status" in out


def test_goal_tracker_sync_does_not_claim_blocked_subtask_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Active parent",
        "url": "https://github.com/o/r/issues/42",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/42", "title": "Active parent"},
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "title": "Blocked subtask",
        "url": "https://github.com/o/r/issues/43",
        "content": {"id": "ISSUE_child", "url": "https://github.com/o/r/issues/43", "title": "Blocked subtask"},
        "fieldValues": {"Status": "Blocked"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active parent\n")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/43"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_subtask_active_claim: skipped_terminal_status" in out


def test_goal_tracker_sync_does_not_claim_non_open_subtask_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Active parent",
        "url": "https://github.com/o/r/issues/44",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/44", "title": "Active parent"},
        "fieldValues": {"Status": "In progress"},
    }
    child = {
        "id": "PVTI_child",
        "title": "Closed subtask",
        "url": "https://github.com/o/r/issues/45",
        "content": {"id": "ISSUE_child", "url": "https://github.com/o/r/issues/45", "title": "Closed subtask"},
        "fieldValues": {"Status": "Ready"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent, child])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active parent\n")
    monkeypatch.setattr(
        cli,
        "grooming_sub_issues",
        lambda item, target: [{"id": "ISSUE_child", "url": "https://github.com/o/r/issues/45"}]
        if item["id"] == "PVTI_parent"
        else [],
    )
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "CLOSED" if item["id"] == "PVTI_child" else "OPEN")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_subtask_active_claim: skipped_non_open_state" in out
    assert "goal_tracker_sync_subtask_active_item_state: CLOSED" in out


def test_goal_tracker_sync_dry_run_does_not_claim_board_backed_subtasks(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Dry parent",
        "url": "https://github.com/o/r/issues/46",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/46", "title": "Dry parent"},
        "fieldValues": {"Status": "Ready"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Dry parent\n")
    monkeypatch.setattr(
        cli,
        "goal_tracker_items",
        lambda data, target, limit=400: (_ for _ in ()).throw(AssertionError("dry run must not scan subtasks")),
    )
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=False))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: dry_run" in out
    assert "goal_tracker_sync_subtask" not in out


def test_goal_tracker_sync_warns_when_subtask_enumeration_unavailable(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    parent = {
        "id": "PVTI_parent",
        "title": "Active parent",
        "url": "https://github.com/o/r/issues/47",
        "content": {"id": "ISSUE_parent", "url": "https://github.com/o/r/issues/47", "title": "Active parent"},
        "fieldValues": {"Status": "In progress"},
    }
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: parent)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [parent])
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "parent.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Active parent\n")
    monkeypatch.setattr(cli, "grooming_sub_issues", lambda item, target: cli.GROOMING_SUBISSUES_UNAVAILABLE)
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": item_ref, "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_parent", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_subtask_active_warn: native sub-issue enumeration unavailable" in out


def test_goal_tracker_sync_write_does_not_move_done_item_back_to_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    item = {"id": "PVTI_4", "title": "Done thing", "url": "https://github.com/o/r/issues/4",
            "fieldValues": {"Status": "Done"}}
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: item)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "done.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Done thing\n")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": "PVTI_4", "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_4", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: skipped_terminal_status" in out


def test_goal_tracker_sync_write_does_not_claim_closed_ready_item(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    item = {"id": "PVTI_5", "title": "Closed thing", "url": "https://github.com/o/r/issues/5",
            "fieldValues": {"Status": "Ready"}}
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: item)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "closed.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Closed thing\n")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda item, target: "CLOSED")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": "PVTI_5", "status": status, "output": ""},
    )

    rc = cli.goal_tracker_sync(SimpleNamespace(item="PVTI_5", write=True))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "goal_tracker_sync_active_claim: skipped_non_open_state" in out
    assert "goal_tracker_sync_active_item_state: CLOSED" in out


def test_backlog_provider_sync_dry_run_does_not_claim_item_active(cli, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    data = _sync_enabled_data()
    item = {"id": "PVTI_2", "title": "Dry run thing", "url": "https://github.com/o/r/issues/2",
            "fieldValues": {"Status": "Ready"}}
    calls = []
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, tmp_path / "adapter.json", tmp_path))
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "resolve_goal_tracker_item", lambda data, target, item_ref: item)
    monkeypatch.setattr(cli, "goal_tracker_plan_path", lambda data, target, item: tmp_path / "dry-run.md")
    monkeypatch.setattr(cli, "goal_tracker_sync_text", lambda data, target, item, path: "# Dry run thing\n")
    monkeypatch.setattr(
        cli,
        "goal_tracker_update_status",
        lambda data, target, item_ref, status: calls.append((item_ref, status)) or {"item_id": "PVTI_2", "status": status, "output": ""},
    )

    rc = cli.backlog_provider_sync(SimpleNamespace(item="PVTI_2", write=False))

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "backlog_provider_sync_active_claim: dry_run" in out
    assert "backlog_provider_sync_active_status: In progress" in out


def test_p1c_lane_changed_plan_refs_parses_mapping(cli, tmp_path, monkeypatch):
    spec = tmp_path / "docs" / "specs" / "g2-m1.goal.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "# M1\n\n## GitHub Project Source\n- project_item_id: PVTI_node234\n- project_item_url: https://github.com/o/r/issues/234\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "run_git", lambda target, args: " M docs/specs/g2-m1.goal.md")
    refs = cli.lane_changed_plan_refs(tmp_path)
    assert refs == ["PVTI_node234"]  # first present of project_item_id/url/title


def test_p1c_lane_changed_plan_refs_ignores_unmapped_md(cli, tmp_path, monkeypatch):
    note = tmp_path / "notes.md"
    note.write_text("# just a note, no project source\n", encoding="utf-8")
    monkeypatch.setattr(cli, "run_git", lambda target, args: " M notes.md")
    assert cli.lane_changed_plan_refs(tmp_path) == []


def test_p1b_unplaced_issue_check_safe_when_gh_raises(cli, tmp_path, monkeypatch):
    # P1-B: a non-zero `gh issue list` (goal_tracker_gh_json raises SystemExit) must not crash the
    # gate -- the warning-only path degrades to [].
    def _raise(*a, **k):
        raise SystemExit("gh issue list failed")
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [])
    monkeypatch.setattr(cli, "goal_tracker_gh_json", _raise)
    assert cli.lane_unplaced_customer_facing_issues(_enabled_data(), tmp_path) == []


def test_branch_issue_number_rejects_trailing_date(cli):
    assert cli.branch_issue_number("hotfix/2026-06-19") == ""
    assert cli.branch_issue_number("fix/orders-334") == "334"
    assert cli.branch_issue_number("release/2026-06-19-334") == "334"


def test_unlinked_ledger_nudges_at_session_start_via_reconciler(cli, tmp_path, monkeypatch):
    # P1-C / #234 early surface: an unlinked active ledger (no outgoing work) yields a session-start
    # WARNING via the reconciler (goal_tracker_drift_issues -> warnings), never blocking drift.
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: [])
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": [],
                              "working_tree_refs": [], "unresolved_ledger": True},
    )
    monkeypatch.setattr(cli, "goal_tracker_goal_ref", lambda data, target, run: "")
    drift, unavailable, warnings = cli.provider_board_currency_issues(_enabled_data(), tmp_path, {"goalId": "g"})
    assert any("active goal ledger" in w and "GitHub Project Source" in w for w in warnings)
    assert drift == []


# --- non-wedging: declared statuses/fields the board lacks are a SCHEMA MISMATCH (warn -> adopt),
# not a hard block that fails sanctioned status writes closed (operator decision 2026-06-25). ---

def _status_fields(options):
    return [{"name": "Status", "type": "ProjectV2SingleSelectField",
             "options": [{"name": o} for o in options]}]


_TRACKER_RB = {"statusField": "Status", "readyStatuses": ["Ready"], "activeStatuses": ["In progress"],
               "doneStatuses": ["Done"], "blockedStatuses": ["Blocked"]}


def test_declared_status_missing_from_board_is_mismatch(cli):
    # Board 5's real columns; adapter still declares Ready/Blocked it never had.
    mm = cli.board_schema_mismatch(_status_fields(["Funnel", "Todo", "In progress", "Done"]), _TRACKER_RB)
    assert any("Ready" in m for m in mm)
    assert any("Blocked" in m for m in mm)
    # statuses that DO exist are not flagged -> writing to them is not wedged
    assert not any(m.endswith("In progress") for m in mm)
    assert not any(m.endswith("Done") for m in mm)


def test_board_matching_adapter_has_no_mismatch(cli):
    assert cli.board_schema_mismatch(_status_fields(["Ready", "In progress", "Done", "Blocked"]), _TRACKER_RB) == []


def test_missing_optional_and_custom_fields_are_mismatch(cli):
    fields = _status_fields(["Ready", "In progress", "Done", "Blocked"])
    tr = dict(_TRACKER_RB, priorityField="Goal Priority")
    mm = cli.board_schema_mismatch(fields, tr, type_field="Item Type", epic_field="Epic", order_field="Epic Order")
    assert any("priorityField" in m and "Goal Priority" in m for m in mm)
    assert any("typeField" in m and "Item Type" in m for m in mm)
    assert any("epicField" in m for m in mm)
    assert any("orderField" in m for m in mm)


# --- provider-unavailable fail-closed (2026-07-17: the "30x recurrence" root cause) ---

UNAVAILABLE_REMEDY = "gh auth refresh --hostname github.com -s read:project -s project"


def _gate_args():
    import argparse

    return argparse.Namespace(project=None, target=None, strict=False)


def _monkeypatch_unavailable(cli, tmp_path, monkeypatch, data):
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, tmp_path))
    monkeypatch.setattr(cli, "goal_run_path", lambda d, t: tmp_path / "no-such-goal-run")
    monkeypatch.setattr(
        cli,
        "provider_board_currency_issues",
        lambda d, t, g: ([], ["gh token scopes missing read:project"], []),
    )
    monkeypatch.setattr(cli, "print_provider_board_business_lead_warnings", lambda d, t: None)
    monkeypatch.setattr(cli, "print_unplaced_customer_facing_issue_warnings", lambda d, t: None)


def test_unavailable_blocks_the_board_check_by_default(cli, tmp_path, monkeypatch, capsys):
    """A board the gate cannot READ is not a board it can vouch for. Warn-and-pass on
    every machine whose gh token lacks the project scope (gh auth login's default!) is
    how months of silent board drift happened: the drift detectors are sound but never
    received data, and all three enforcement surfaces passed anyway."""
    _monkeypatch_unavailable(cli, tmp_path, monkeypatch, _enabled_data())
    rc = cli.backlog_provider_board_check(_gate_args())
    err = capsys.readouterr().err
    assert rc == 1, "an unreadable authoritative board must BLOCK, not warn"
    assert UNAVAILABLE_REMEDY in err, f"the block must name the exact fix\n{err}"


def test_unavailable_blocks_the_active_check_by_default(cli, tmp_path, monkeypatch, capsys):
    _monkeypatch_unavailable(cli, tmp_path, monkeypatch, _enabled_data())
    rc = cli.backlog_provider_active_check(_gate_args())
    err = capsys.readouterr().err
    assert rc == 1, "the pre-commit/pre-push hook gate must fail closed on unavailability"
    assert UNAVAILABLE_REMEDY in err


def test_unavailable_policy_warn_is_a_deliberate_optout(cli, tmp_path, monkeypatch, capsys):
    """Offline work stays possible, but only by an explicit, audit-visible adapter
    choice -- never as the silent default."""
    data = _enabled_data()
    data["backlogProvider"]["unavailablePolicy"] = "warn"
    _monkeypatch_unavailable(cli, tmp_path, monkeypatch, data)
    assert cli.backlog_provider_board_check(_gate_args()) == 0
    assert cli.backlog_provider_active_check(_gate_args()) == 0
    err = capsys.readouterr().err
    assert "backlog_provider_board_warn" in err or "backlog_provider_active_warn" in err


def test_unavailable_policy_validates_and_defaults_to_block(cli):
    assert cli.backlog_provider_unavailable_policy(_enabled_data()) == "block"
    bad = _enabled_data()
    bad["backlogProvider"]["unavailablePolicy"] = "silently-ignore"
    with pytest.raises(SystemExit):
        cli.backlog_provider_unavailable_policy(bad)


def test_legacy_goal_tracker_unavailable_policy_survives_normalization(cli):
    """Codex R1 (0.10.3): a legacy goalTracker-only adapter's unavailablePolicy: warn
    must survive backlog_provider_from_goal_tracker -- silently dropping the opt-out
    would hard-block deliberate offline work after migration."""
    tracker = _enabled_tracker()
    tracker["unavailablePolicy"] = "warn"
    provider = cli.backlog_provider_from_goal_tracker(tracker)
    assert provider.get("unavailablePolicy") == "warn"
    data = {"goalTracker": {"enabled": False}, "backlogProvider": provider}
    assert cli.backlog_provider_unavailable_policy(data) == "warn"
    # And absence stays absent: no key means the block default, not a literal key.
    bare = cli.backlog_provider_from_goal_tracker(_enabled_tracker())
    assert "unavailablePolicy" not in bare


def test_unavailable_policy_survives_the_full_normalization_round_trip(cli):
    """Codex R2: load_project round-trips legacy adapters through BOTH converters;
    the opt-down must survive provider->tracker->provider, and absence must stay
    absence in both directions."""
    tracker = _enabled_tracker()
    tracker["unavailablePolicy"] = "warn"
    provider = cli.backlog_provider_from_goal_tracker(tracker)
    regenerated_tracker = cli.goal_tracker_from_backlog_provider(provider)
    assert regenerated_tracker.get("unavailablePolicy") == "warn"
    round_tripped = cli.backlog_provider_from_goal_tracker(regenerated_tracker)
    assert round_tripped.get("unavailablePolicy") == "warn"
    bare = cli.goal_tracker_from_backlog_provider(
        cli.backlog_provider_from_goal_tracker(_enabled_tracker())
    )
    assert "unavailablePolicy" not in bare


def test_snapshot_store_fault_phrases_build_without_posix_only_errnos(cli):
    """Codex R2: EDQUOT/ESTALE are absent from errno on native Windows; the map must
    be getattr-guarded so the CLI can IMPORT there. On POSIX all five entries exist."""
    phrases = cli._SNAPSHOT_STORE_FAULT_PHRASES
    assert all(isinstance(code, int) for code in phrases)
    import errno as _errno

    assert phrases[_errno.ENOSPC] == "store out of space"
    expected = {
        name for name in ("ENOSPC", "EDQUOT", "EROFS", "ESTALE", "EIO") if hasattr(_errno, name)
    }
    assert len(phrases) == len(expected)


# --- item 71 T1.3: the truncation-drift branch PR1 shipped but never pinned ---------------------


def test_a_truncated_board_read_is_blocking_drift(cli, tmp_path, monkeypatch):
    """0.46.0 made the currency gate consume the VERIFIED read and deleted the page-full heuristic
    it used to guess with, but the regression test for that branch never landed -- so the behavior
    shipped unpinned for six releases.

    A board that could not be read completely is not a board with no drift. The gate has no honest
    answer about items it never saw, and 'no drift' is the most reassuring possible answer from the
    least evidence.
    """
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: (
        _ for _ in ()
    ).throw(SystemExit("GitHub Project board read truncated at 400 of 402 items")))
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": [],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )

    drift, unavailable, warnings = cli.provider_board_currency_issues(
        _enabled_data(), tmp_path, None
    )

    assert any("could not be read for board reconciliation" in d for d in drift), drift
    assert any("402" in d for d in drift), "the drift entry must carry the underlying reason"


def test_a_complete_escalated_read_produces_no_truncation_drift(cli, tmp_path, monkeypatch):
    """The positive twin: a read that DID see the whole board -- 402 items, past the default 400 --
    attests to it, and the gate stays green. Without this the test above would pass just as well
    against a gate that blocked on every read."""
    items = [
        {"content": {"url": f"https://github.com/o/r/issues/{n}", "title": f"i{n}",
                     "state": "OPEN"}}
        for n in range(402)
    ]
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda data, target: [])
    monkeypatch.setattr(cli, "goal_tracker_items", lambda data, target, limit=400: items)
    monkeypatch.setattr(cli, "goal_tracker_item_field", lambda it, f: "Done")
    monkeypatch.setattr(cli, "board_item_fetch_state", lambda it, target: "CLOSED")
    monkeypatch.setattr(
        cli, "lane_work_scope",
        lambda data, target: {"ledger_ref": "", "outgoing_issue_numbers": [],
                              "working_tree_refs": [], "unresolved_ledger": False},
    )

    drift, unavailable, warnings = cli.provider_board_currency_issues(
        _enabled_data(), tmp_path, None
    )

    assert not any("could not be read for board reconciliation" in d for d in drift), drift
