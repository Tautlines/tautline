"""D4 (0.6.113): read-only validate-grooming CLI + board-write-safety spy.

RCA 20260616T211526Z (grooming-gap): no first-class backlog-grooming capability. validate-grooming
enumerates epics by epicField VALUE (not an itemType), identifies feature items as native
sub-issues, checks the DoR (acceptance criteria + ## Verification + privacy-negative tests where
declared + sub-issue linkage), rejects duplicate feature numbers via featureSeries, and is strictly
READ-ONLY: it blocks via exit code only and never mutates the board.
"""

import argparse

import pytest

EPIC_FIELD = "Epic"


def _data(*, privacy=None, feature_series=None):
    provider = {
        "enabled": True,
        "provider": "github-projects",
        "owner": "acme",
        "projectNumber": 3,
        "statusField": "Status",
        "epicField": EPIC_FIELD,
        "featureSeries": feature_series or {},
    }
    data = {
        "backlogProvider": provider,
        # goal_tracker_items_for_scope reads the item-list query from goalTracker; give it the
        # minimal keys so the real read path (board-write-safety spy) reaches the gh layer.
        "goalTracker": {
            "enabled": False,
            "epicField": "",
            "featureSeries": {},
            "projectNumber": 3,
            "owner": "acme",
            "scopeQuery": "",
        },
    }
    if privacy is not None:
        data["privacyInvariants"] = privacy
    return data


def _good_feature_body():
    return (
        "## What this delivers\nA flag.\n\n## Why it matters\nUsers need it.\n\n"
        "## Acceptance criteria\n- The flag toggles behavior X and is covered by a unit test.\n\n"
        "## Verification\n- Run `pytest tests/test_flag.py` and confirm green.\n"
    )


def _epic(title, epic_value=EPIC_FIELD, node_id="EPIC_NODE"):
    return {"title": title, "content": {"id": node_id, "Epic": epic_value}, "Epic": epic_value}


def _sub(title, body, number=1, **extra):
    return {"title": title, "body": body, "number": number, **extra}


def _args(**kw):
    ns = argparse.Namespace(project=None, target=None, epic=None, strict=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def grooming_env(cli, monkeypatch, tmp_path):
    """Patch lane_project + the read primitives so validate_grooming runs without a real board.
    Returns a setter the test calls with (data, epics, subs_by_epic)."""
    state = {}

    def fake_lane_project(args):
        return state["data"], tmp_path, tmp_path

    monkeypatch.setattr(cli, "lane_project", fake_lane_project)
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda target: state.get("auth_issues", []))
    monkeypatch.setattr(cli, "goal_tracker_items_for_scope", lambda data, target, **kw: state["epics"])
    monkeypatch.setattr(cli, "grooming_sub_issues", lambda item, target: state["subs"].get(cli.goal_tracker_item_title(item), []))

    def configure(data, epics, subs_by_title, auth_issues=None):
        state["data"] = data
        state["epics"] = epics
        state["subs"] = subs_by_title
        state["auth_issues"] = auth_issues or []

    return configure


# --- pure DoR helpers --------------------------------------------------------------------------


def test_feature_dor_issues_pure(cli):
    assert cli.grooming_feature_dor_issues(_good_feature_body(), []) == []
    missing_ac = "## Verification\n- run the tests.\n"
    assert any("Acceptance criteria" in i for i in cli.grooming_feature_dor_issues(missing_ac, []))
    missing_v = "## Acceptance criteria\n- the flag toggles behavior X under test.\n"
    assert any("Verification" in i for i in cli.grooming_feature_dor_issues(missing_v, []))
    # privacy invariant declared but no negative-test section -> flagged
    assert any("privacy" in i.lower() for i in cli.grooming_feature_dor_issues(_good_feature_body(), ["no-cross-tenant-read"]))
    # privacy invariant declared AND a negative-tests section present -> not flagged on privacy
    body = _good_feature_body() + "\n## Privacy / negative tests\n- unauthorized tenant cannot read.\n"
    assert not any("privacy" in i.lower() for i in cli.grooming_feature_dor_issues(body, ["no-cross-tenant-read"]))
    # NO invariants declared -> privacy check never fires (over-block guard)
    assert not any("privacy" in i.lower() for i in cli.grooming_feature_dor_issues(_good_feature_body(), []))


# --- validate_grooming CLI ---------------------------------------------------------------------


def test_validate_grooming_happy_path(cli, grooming_env, capsys):
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": [_sub("F1", _good_feature_body())]})
    assert cli.validate_grooming(_args()) == 0
    out = capsys.readouterr().out
    assert "grooming_dor_ok" in out
    assert "sub_issues=1" in out


def test_validate_grooming_epic_missing_subissues(cli, grooming_env, capsys):
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": []})
    assert cli.validate_grooming(_args()) == 1
    err = capsys.readouterr().err
    assert "grooming_dor_issue" in err and "no feature items" in err


def test_validate_grooming_missing_acceptance_criteria(cli, grooming_env, capsys):
    body = "## Verification\n- run `pytest` and confirm green coverage of the change.\n"
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": [_sub("F1", body)]})
    assert cli.validate_grooming(_args()) == 1
    assert "Acceptance criteria" in capsys.readouterr().err


def test_validate_grooming_missing_verification(cli, grooming_env, capsys):
    body = "## Acceptance criteria\n- the flag toggles behavior X and is covered by a unit test.\n"
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": [_sub("F1", body)]})
    assert cli.validate_grooming(_args()) == 1
    assert "Verification" in capsys.readouterr().err


def test_validate_grooming_missing_privacy_negative_test(cli, grooming_env, capsys):
    grooming_env(_data(privacy=["no-cross-tenant-read"]), [_epic("Epic A")], {"Epic A": [_sub("F1", _good_feature_body())]})
    assert cli.validate_grooming(_args()) == 1
    assert "privacy" in capsys.readouterr().err.lower()


def test_no_privacy_invariants_does_not_fail_privacy_check(cli, grooming_env, capsys):
    # Over-block guard: a project declaring NO privacy invariants passes a clean item.
    grooming_env(_data(privacy=[]), [_epic("Epic A")], {"Epic A": [_sub("F1", _good_feature_body())]})
    assert cli.validate_grooming(_args()) == 0


def test_validate_grooming_feature_number_collision(cli, grooming_env, capsys):
    # FIX-7: collision detection uses `pattern` (the reliable mechanism on real sub-issue nodes,
    # which carry only number/title/url/body and no board field value). Both subs carry "F-1" in
    # their title -> duplicate.
    fs = {"pattern": r"F-\d+"}
    subs = [
        _sub("F-1: flag toggle", _good_feature_body(), number=1),
        _sub("F-1: duplicate", _good_feature_body(), number=2),
    ]
    grooming_env(_data(feature_series=fs), [_epic("Epic A")], {"Epic A": subs})
    assert cli.validate_grooming(_args()) == 1
    assert "duplicate feature number" in capsys.readouterr().err


def test_validate_grooming_feature_number_collision_via_body_pattern(cli, grooming_env, capsys):
    # The pattern matches in the body too (title+body haystack).
    fs = {"pattern": r"F-\d+"}
    subs = [
        _sub("alpha", "Feature F-7\n" + _good_feature_body(), number=1),
        _sub("beta", "Feature F-7\n" + _good_feature_body(), number=2),
    ]
    grooming_env(_data(feature_series=fs), [_epic("Epic A")], {"Epic A": subs})
    assert cli.validate_grooming(_args()) == 1
    assert "duplicate feature number F-7" in capsys.readouterr().err


def test_validate_grooming_field_unreadable_warns_and_falls_back(cli, grooming_env, capsys):
    # FIX-7: `field` configured but real sub-issue nodes carry no board field value -> warn once and
    # fall back to `pattern`, which still catches the collision.
    fs = {"field": "Feature", "pattern": r"F-\d+"}
    subs = [
        _sub("F-3: alpha", _good_feature_body(), number=1),
        _sub("F-3: beta", _good_feature_body(), number=2),
    ]
    grooming_env(_data(feature_series=fs), [_epic("Epic A")], {"Epic A": subs})
    assert cli.validate_grooming(_args()) == 1
    err = capsys.readouterr().err
    assert "grooming_feature_series_field_unreadable" in err
    assert "duplicate feature number F-3" in err


def test_validate_grooming_field_unreadable_no_pattern_fails_under_strict(cli, grooming_env, capsys):
    # Codex re-review P2: `field` configured but unreadable on real sub-issue nodes AND no `pattern`
    # fallback -> the numbering series could not be verified at all. Non-strict warns (advisory);
    # --strict fails closed instead of a silent grooming_dor_ok that hides unchecked collisions.
    fs = {"field": "Feature"}  # no pattern fallback
    grooming_env(_data(feature_series=fs), [_epic("Epic A")], {"Epic A": [_sub("F-1", _good_feature_body())]})
    assert cli.validate_grooming(_args()) == 0
    assert "grooming_feature_series_field_unreadable" in capsys.readouterr().err
    assert cli.validate_grooming(_args(strict=True)) == 1
    assert "could not be verified" in capsys.readouterr().err


def test_validate_grooming_feature_series_unconfigured(cli, grooming_env, capsys):
    # No featureSeries -> structural checks run, collision check skipped + announced, clean exits 0.
    subs = [
        _sub("F-1: alpha", _good_feature_body(), number=1),
        _sub("F-1: beta", _good_feature_body(), number=2),
    ]
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": subs})
    assert cli.validate_grooming(_args()) == 0
    out = capsys.readouterr().out
    assert "grooming_feature_series_unconfigured" in out


def test_validate_grooming_provider_unavailable(cli, grooming_env, capsys):
    grooming_env(_data(), [], {}, auth_issues=["gh CLI missing"])
    assert cli.validate_grooming(_args()) == 0  # warn-by-default
    assert cli.validate_grooming(_args(strict=True)) == 1  # strict -> fail


def test_validate_grooming_subissue_graphql_unavailable_degrades(cli, grooming_env, monkeypatch, capsys):
    grooming_env(_data(), [_epic("Epic A")], {})
    monkeypatch.setattr(cli, "grooming_sub_issues", lambda item, target: cli.GROOMING_SUBISSUES_UNAVAILABLE)
    # Non-strict: degrades to a warning; the epic is NOT false-failed and the command passes.
    assert cli.validate_grooming(_args()) == 0
    assert "grooming_subissues_warn" in capsys.readouterr().err


def test_validate_grooming_subissue_unavailable_fails_under_strict(cli, grooming_env, monkeypatch, capsys):
    # FIX-8: under --strict an unreadable sub-issue connection must FAIL, not degrade to pass.
    grooming_env(_data(), [_epic("Epic A")], {})
    monkeypatch.setattr(cli, "grooming_sub_issues", lambda item, target: cli.GROOMING_SUBISSUES_UNAVAILABLE)
    assert cli.validate_grooming(_args(strict=True)) == 1
    err = capsys.readouterr().err
    assert "grooming_dor_issue" in err
    assert "native sub-issue enumeration unavailable" in err


def test_validate_grooming_assigned_epic_typo_fails(cli, grooming_env, monkeypatch, capsys):
    # FIX-8: assigned epics that match NO board item is a typo / off-board ref -> fail.
    monkeypatch.delenv("MINERVIT_LANE_EPICS", raising=False)
    grooming_env(_data(), [], {})
    assert cli.validate_grooming(_args(epic=["Epic Nope"])) == 1
    err = capsys.readouterr().err
    assert "grooming_dor_issue" in err
    assert "matched no board items" in err


def test_validate_grooming_no_epics_unassigned_warns_and_passes(cli, grooming_env, monkeypatch, capsys):
    # FIX-8: no epics assigned and the board carries none -> warn + pass (nothing to groom yet).
    monkeypatch.delenv("MINERVIT_LANE_EPICS", raising=False)
    grooming_env(_data(), [], {})
    assert cli.validate_grooming(_args()) == 0
    assert "grooming_no_epics_warn" in capsys.readouterr().err


def test_validate_grooming_enumerates_epics_by_field_not_itemtype(cli, monkeypatch, tmp_path, capsys):
    data = _data()
    items = [
        _epic("Epic A", epic_value="Epic Alpha"),
        {"title": "Loose task", "content": {"id": "X"}},  # no epicField value -> not an epic
        _epic("Epic B", epic_value="Epic Beta"),
    ]
    monkeypatch.setattr(cli, "goal_tracker_items_for_scope", lambda d, t, **kw: items)
    epics = cli.grooming_epic_items(data, tmp_path, ["Epic Alpha"])
    assert [cli.goal_tracker_item_title(e) for e in epics] == ["Epic A"]
    # With no assignment, every item carrying an epicField value is an epic (the loose task is not).
    all_epics = cli.grooming_epic_items(data, tmp_path, [])
    assert sorted(cli.goal_tracker_item_title(e) for e in all_epics) == ["Epic A", "Epic B"]


def test_no_epic_assigned_announces_all(cli, grooming_env, capsys):
    grooming_env(_data(), [_epic("Epic A")], {"Epic A": [_sub("F1", _good_feature_body())]})
    cli.validate_grooming(_args())
    assert "no epic assigned; checking all epics on the board" in capsys.readouterr().out


# --- board-write-safety spy --------------------------------------------------------------------

# A comprehensive mutating-token denylist: gh project/issue mutating subcommands AND raw-API
# mutations (REST verbs + GraphQL mutation). validate-grooming must trip NONE of these.
MUTATING_TOKENS = [
    "item-edit",
    "item-create",
    "item-add",
    "item-archive",
    "item-delete",
    "issue edit",
    "issue create",
    "project edit",
    "--method post",
    "--method patch",
    "--method put",
    "--method delete",
    "mutation",
    "addsubissue",
]


def _real_sub_node(title, body, number=1):
    """The REAL native sub-issue GraphQL node shape: number/title/url/body only (no field key)."""
    return {"number": number, "title": title, "url": f"https://x/{number}", "body": body}


def test_validate_grooming_board_write_safety(cli, monkeypatch, tmp_path):
    """Install the spy at the gh COMMAND layer (command_json + run_command), let the real read path
    (goal_tracker_items_for_scope, grooming_sub_issues, goal_tracker_auth_issues) execute, and
    prove NO mutating gh subcommand is invoked across the pass path or any fail class. The spy
    returns benign READ JSON shaped for both item-list and the subIssues GraphQL."""
    invocations = []
    monkeypatch.setenv("MINERVIT_GITHUB_CACHE_DIR", str(tmp_path / "github-cache"))

    # Per-case board state the command-layer spy serves up.
    board = {"items": [], "subs": []}

    def spy_command_json(cmd, cwd=None, timeout=30, **kw):
        argv = " ".join(str(c) for c in cmd).lower()
        invocations.append(argv)
        if "item-list" in argv:
            # gh project item-list ... --format json -> {items:[...]}
            return 0, {"items": board["items"]}, ""
        if "graphql" in argv:
            # gh api graphql -> {data:{node:{subIssues:{totalCount,nodes}}}}
            return 0, {"data": {"node": {"subIssues": {"totalCount": len(board["subs"]), "nodes": board["subs"]}}}}, ""
        return 0, {}, ""

    def spy_run_command(cmd, cwd=None, timeout=None, **kw):
        argv = " ".join(str(c) for c in cmd).lower()
        invocations.append(argv)
        if "auth" in argv and "status" in argv:
            # gh auth status -> token with `project` scope so auth-precheck passes.
            return 0, "", "Token scopes: 'project', 'repo', 'read:org'"
        return 0, "", ""

    monkeypatch.setattr(cli, "command_json", spy_command_json)
    monkeypatch.setattr(cli, "run_command", spy_run_command)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/gh")

    epic_item = {"title": "Epic A", "content": {"id": "EPIC_NODE", "Epic": EPIC_FIELD}, "Epic": EPIC_FIELD}
    good = _good_feature_body()
    cases = [
        # pass path
        ([epic_item], [_real_sub_node("F1", good)], None),
        # fail: missing sub-issues
        ([epic_item], [], None),
        # fail: missing verification
        ([epic_item], [_real_sub_node("F1", "## Acceptance criteria\n- x is covered by a test.\n")], None),
        # fail: privacy negative test missing
        ([epic_item], [_real_sub_node("F1", good)], ["no-cross-tenant-read"]),
        # fail: collision (pattern-based, the reliable mechanism on real sub nodes)
        ([epic_item], [_real_sub_node("F-1 a", good, 1), _real_sub_node("F-1 b", good, 2)], None),
    ]
    saw_pass = saw_fail = False
    for items, subs, privacy in cases:
        invocations.clear()
        board["items"], board["subs"] = items, subs
        data = _data(privacy=privacy, feature_series={"pattern": r"F-\d+"})
        monkeypatch.setattr(cli, "lane_project", lambda args, _d=data: (_d, tmp_path, tmp_path))
        rc = cli.validate_grooming(_args())
        saw_pass = saw_pass or rc == 0
        saw_fail = saw_fail or rc == 1
        # (a) the real read path actually reached the gh layer.
        assert invocations, "spy never observed a gh call — read path was stubbed"
        # (b) no invocation contains a mutating token.
        for inv in invocations:
            for token in MUTATING_TOKENS:
                assert token not in inv, f"mutating gh subcommand {token!r} invoked: {inv}"
    # The cases exercise both the pass path and the fail classes.
    assert saw_pass and saw_fail
