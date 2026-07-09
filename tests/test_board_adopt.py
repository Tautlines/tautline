"""Tests for the board-adopt flow (Part A). Module-level helpers are shared across A1–A5."""

import json


def _fields(*specs):
    out = []
    for name, ftype, opts in specs:
        f = {"name": name, "type": ftype}
        if opts is not None:
            f["options"] = [{"name": o} for o in opts]
        out.append(f)
    return out


BOARD5 = _fields(
    ("Title", "ProjectV2Field", None),
    ("Status", "ProjectV2SingleSelectField", ["Funnel", "Todo", "In progress", "Done"]),
    ("Epic Order", "ProjectV2Field", None),
    ("Size", "ProjectV2SingleSelectField", ["XS", "S", "M"]),
)


def test_profile_extracts_status_columns_in_order(cli):
    p = cli.board_profile(BOARD5)
    assert p["statusField"] == "Status"
    assert p["columns"] == ["Funnel", "Todo", "In progress", "Done"]


def test_profile_lists_single_selects_and_order_candidates(cli):
    p = cli.board_profile(BOARD5)
    assert p["singleSelects"]["Size"] == ["XS", "S", "M"]
    assert "Epic Order" in p["orderCandidates"]
    assert "Title" not in p["customFields"]  # builtin


def test_assumptions_flag_unknown_ready_column_and_priority(cli):
    a = cli.board_assumptions(cli.board_profile(BOARD5))
    # 4 columns, none literally named Ready/Backlog -> must ASK which is ready/active/done/icebox
    assert any("ready" in u.lower() for u in a["unknowns"])
    # one order candidate, zero priority candidates -> ask how next priority is decided
    assert any("priorit" in u.lower() or "order" in u.lower() for u in a["unknowns"])
    assert a["statements"]  # non-empty human-readable interpretation


def test_assumptions_no_unknowns_when_columns_are_canonical(cli):
    canonical = _fields(("Status", "ProjectV2SingleSelectField", ["Ready", "In progress", "Blocked", "Done"]))
    a = cli.board_assumptions(cli.board_profile(canonical))
    assert a["unknowns"] == []


def test_proposal_aligns_statuses_to_real_columns(cli):
    current = {"owner": "minervit", "projectNumber": 5, "statusField": "Status",
               "readyStatuses": ["Ready"], "activeStatuses": ["In progress"],
               "doneStatuses": ["Done"], "blockedStatuses": ["Blocked"]}
    profile = cli.board_profile(BOARD5)
    answers = {"ready_column": "Todo"}  # operator says Todo = ready
    prop = cli.board_proposed_backlog_provider(profile, current, answers)
    assert prop["activeStatuses"] == ["In progress"]
    assert prop["doneStatuses"] == ["Done"]
    assert prop["readyStatuses"] == ["Todo"]
    assert prop["blockedStatuses"] == []          # board has no Blocked column
    assert prop["owner"] == "minervit" and prop["projectNumber"] == 5  # preserved
    assert prop["schemaHash"] == cli.board_schema_hash(BOARD5)


# --- A4: backlog-board-examine CLI (read-only) ---

def test_backlog_board_examine_cli(tmp_path, run_cli):
    """backlog-board-examine prints profile/unknowns/proposed diff and exits 0 without writing anything."""
    adapter = {
        "backlogProvider": {
            "owner": "minervit",
            "projectNumber": 5,
            "statusField": "Status",
        }
    }
    (tmp_path / ".minervit-ai-delivery.json").write_text(json.dumps(adapter))
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(json.dumps(BOARD5))

    res = run_cli(
        "backlog-board-examine",
        "--target", str(tmp_path),
        "--fields-file", str(fields_path),
    )

    assert res.returncode == 0, f"stdout={res.stdout!r}\nstderr={res.stderr!r}"
    # Unknowns must appear: BOARD5 has Funnel/Todo columns with no canonical role mapping
    assert "board_examine_unknown:" in res.stdout
    # At least one unknown should reference a column that needs a role (Funnel or Todo)
    unknown_lines = [ln for ln in res.stdout.splitlines() if ln.startswith("board_examine_unknown:")]
    assert any("Funnel" in ln or "Todo" in ln or "ready" in ln.lower() for ln in unknown_lines)
    # Proposed diff lines must appear
    assert "board_examine_proposed:" in res.stdout
    # Must not write or mutate the adapter
    import json as _json
    on_disk = _json.loads((tmp_path / ".minervit-ai-delivery.json").read_text())
    assert on_disk == adapter  # file unchanged


def test_backlog_board_examine_registered_in_help(run_cli):
    """backlog-board-examine must appear in --help (replaces validate.sh grep pin; validate.sh is frozen)."""
    res = run_cli("--help")
    assert "backlog-board-examine" in res.stdout


# --- A5: backlog-board-adopt CLI (operator-gated adapter write) ---

def test_board_answer_key_maps_unknowns(cli):
    """board_answer_key produces the canonical key for each BOARD5 unknown question."""
    # column role question
    assert cli.board_answer_key("Which role does column 'Funnel' play (ready / active / done / blocked / backlog-icebox)?") == "role:Funnel"
    assert cli.board_answer_key("Which role does column 'Todo' play (ready / active / done / blocked / backlog-icebox)?") == "role:Todo"
    # priority/order question
    assert cli.board_answer_key("How is the next item's priority/order decided (manual board order, or which field)?") == "priority_order"
    # custom field question
    assert cli.board_answer_key("How should the agent use custom field 'Size'?") == "custom:Size"


def _write_hermetic_adapter(tmp_path):
    """Write a minimal hermetic adapter for adopt tests and return its path."""
    adapter = {
        "_generated": {"sourceAdapter": "x"},
        "backlogProvider": {
            "owner": "minervit",
            "projectNumber": 5,
            "statusField": "Status",
        },
    }
    adapter_path = tmp_path / ".minervit-ai-delivery.json"
    adapter_path.write_text(json.dumps(adapter))
    return adapter_path


def test_adopt_refuses_apply_with_unanswered_unknowns(tmp_path, run_cli):
    """adopt --apply with no --answer flags refuses and lists unanswered unknowns; adapter is unchanged."""
    adapter_path = _write_hermetic_adapter(tmp_path)
    original = json.loads(adapter_path.read_text())

    fields_path = tmp_path / "fields.json"
    fields_path.write_text(json.dumps(BOARD5))

    res = run_cli(
        "backlog-board-adopt",
        "--target", str(tmp_path),
        "--fields-file", str(fields_path),
        "--apply",
    )

    # Must refuse (non-zero exit)
    assert res.returncode != 0, f"Expected failure; stdout={res.stdout!r}"
    # Must list unanswered unknowns
    assert "board_adopt_unanswered:" in res.stdout
    assert "Funnel" in res.stdout or "Todo" in res.stdout
    # On-disk adapter must be unchanged
    on_disk = json.loads(adapter_path.read_text())
    assert on_disk["backlogProvider"] == original["backlogProvider"]


def test_adopt_apply_writes_aligned_backlog_provider(tmp_path, run_cli, cli):
    """adopt --apply with all unknowns answered writes the aligned backlogProvider."""
    adapter_path = _write_hermetic_adapter(tmp_path)
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(json.dumps(BOARD5))

    res = run_cli(
        "backlog-board-adopt",
        "--target", str(tmp_path),
        "--fields-file", str(fields_path),
        "--answer", "role:Todo=ready",
        "--answer", "role:Funnel=icebox",
        "--answer", "priority_order=manual",
        "--answer", "custom:Size=ignore",
        "--apply",
    )

    assert res.returncode == 0, f"stdout={res.stdout!r}\nstderr={res.stderr!r}"

    on_disk = json.loads(adapter_path.read_text())
    bp = on_disk["backlogProvider"]

    # Core alignment assertions
    assert bp["readyStatuses"] == ["Todo"]
    assert bp["activeStatuses"] == ["In progress"]
    assert bp["doneStatuses"] == ["Done"]
    assert bp["blockedStatuses"] == []
    # schemaHash must match what the CLI computes from BOARD5
    assert bp["schemaHash"] == cli.board_schema_hash(BOARD5)
    # boardProfile must be present
    assert "boardProfile" in bp
    # Original provider identity keys preserved
    assert bp["owner"] == "minervit"
    assert bp["projectNumber"] == 5
    # Non-backlogProvider sentinel key must be preserved (proves full adapter is preserved)
    assert on_disk.get("_generated") == {"sourceAdapter": "x"}


def test_board_adopt_answers_preserves_existing_ready_column(cli):
    """board_adopt_answers keeps an existing ready_column when no role:*=ready key is present."""
    result = cli.board_adopt_answers({"ready_column": "Todo"})
    assert result["ready_column"] == "Todo"


def test_board_adopt_answers_derives_ready_column_from_role_key(cli):
    """board_adopt_answers sets ready_column from a role:<name>=ready entry."""
    result = cli.board_adopt_answers({"role:Backlog": "ready"})
    assert result["ready_column"] == "Backlog"


def test_adopt_answer_missing_equals_exits_nonzero(tmp_path, run_cli):
    """--answer without '=' exits non-zero (SystemExit guard)."""
    _write_hermetic_adapter(tmp_path)
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(json.dumps(BOARD5))

    res = run_cli(
        "backlog-board-adopt",
        "--target", str(tmp_path),
        "--fields-file", str(fields_path),
        "--answer", "notakeyvalue",
        "--apply",
    )

    assert res.returncode != 0, f"Expected non-zero exit; stdout={res.stdout!r}"


def test_backlog_board_adopt_registered_in_help(run_cli):
    """backlog-board-adopt must appear in --help."""
    res = run_cli("--help")
    assert "backlog-board-adopt" in res.stdout


def test_adopt_apply_of_enabled_board_writes_loadable_adapter(tmp_path, run_cli, cli):
    """C1/I1 regression: adopting BOARD5 (no Blocked column) into a FULLY-VALID ENABLED provider must
    write an adapter whose backlogProvider normalizes WITHOUT raising — even though blockedStatuses
    becomes []. Without C1a (blockedStatuses required-non-empty when enabled) the written provider is
    self-invalidating and every later load_project raises SystemExit, bricking the project.
    """
    adapter = {
        "_generated": {"sourceAdapter": "x"},
        "backlogProvider": {
            "enabled": True,
            "provider": "github-projects",
            "owner": "minervit",
            "projectNumber": 5,
            "statusField": "Status",
            "readyStatuses": ["Ready"],
            "activeStatuses": ["In progress"],
            "doneStatuses": ["Done"],
            "blockedStatuses": ["Blocked"],
            "authoritativeFor": ["goal-status"],
            "repoPlanRequired": True,
            "linkPolicy": "links",
        },
    }
    adapter_path = tmp_path / ".minervit-ai-delivery.json"
    adapter_path.write_text(json.dumps(adapter))
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(json.dumps(BOARD5))

    res = run_cli(
        "backlog-board-adopt",
        "--target", str(tmp_path),
        "--fields-file", str(fields_path),
        "--answer", "role:Todo=ready",
        "--answer", "role:Funnel=icebox",
        "--answer", "priority_order=manual",
        "--answer", "custom:Size=ignore",
        "--apply",
    )

    assert res.returncode == 0, f"stdout={res.stdout!r}\nstderr={res.stderr!r}"

    written_bp = json.loads(adapter_path.read_text())["backlogProvider"]
    # The board has no Blocked column, so adopt truthfully wrote an empty blockedStatuses ...
    assert written_bp["enabled"] is True
    assert written_bp["blockedStatuses"] == []
    # ... and the written provider must still load. This is the assertion that fails without C1a.
    normalized = cli.normalize_tracker_adapter_config(
        dict(written_bp), cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider"
    )
    assert normalized["enabled"] is True
    assert normalized["blockedStatuses"] == []
