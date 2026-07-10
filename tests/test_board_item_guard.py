"""Tier-2 enforcement for the board-item-updates skill (operator 2026-06-25): an agent does normal
collaboration work on board items (comments, Status, the milestone checklist, self-assign) but must
NOT change the stakeholder-authored substance — issue title/summary, body (which holds acceptance
criteria), labels, or milestone — unless the product's adapter opts in via backlogProvider
.allowedItemWrites. Default-deny; private-product-a leaves it default.
"""

import json


# --- pure classifier: which forbidden item-content writes a command performs ---

def test_title_edit_is_a_forbidden_write(cli):
    assert cli.item_content_write_kinds("gh issue edit 5 --title 'New title'") == {"title"}


def test_body_edit_is_a_forbidden_write(cli):
    assert cli.item_content_write_kinds("gh issue edit 5 --body 'rewritten'") == {"body"}
    assert cli.item_content_write_kinds("gh issue edit 5 --body-file b.md") == {"body"}


def test_label_and_milestone_edits_are_forbidden(cli):
    assert cli.item_content_write_kinds("gh issue edit 5 --add-label bug") == {"labels"}
    assert cli.item_content_write_kinds("gh issue edit 5 --remove-label bug") == {"labels"}
    assert cli.item_content_write_kinds("gh issue edit 5 --milestone M1") == {"milestone"}


def test_multiple_forbidden_flags_all_reported(cli):
    assert cli.item_content_write_kinds("gh issue edit 5 --title x --body y") == {"title", "body"}


def test_graphql_updateissue_is_forbidden(cli):
    cmd = "gh api graphql -f query='mutation{updateIssue(input:{title:\"x\"}){issue{id}}}'"
    assert cli.item_content_write_kinds(cmd) == {"title", "body"}


# --- allowed collaboration work must NOT be flagged ---

def test_comment_is_allowed(cli):
    assert cli.item_content_write_kinds("gh issue comment 5 --body 'progress: shipped'") == set()


def test_self_assign_is_allowed(cli):
    assert cli.item_content_write_kinds("gh issue edit 5 --add-assignee @me") == set()


def test_chained_comment_then_assign_is_allowed(cli):
    # The --body belongs to `gh issue comment`, not the edit -> segment scoping must not false-flag.
    assert cli.item_content_write_kinds("gh issue comment 5 --body x && gh issue edit 5 --add-assignee @me") == set()


def test_unrelated_command_is_allowed(cli):
    assert cli.item_content_write_kinds("git commit -m wip") == set()
    assert cli.item_content_write_kinds("") == set()


# --- the override resolver: default-deny, per-field opt-in ---

def test_allowed_item_writes_default_deny(cli):
    allowed = cli.allowed_item_writes({})
    assert allowed == {"title": False, "body": False, "labels": False, "milestone": False}


def test_allowed_item_writes_opt_in(cli):
    data = {"backlogProvider": {"allowedItemWrites": {"body": True}}}
    allowed = cli.allowed_item_writes(data)
    assert allowed["body"] is True and allowed["title"] is False


def test_allowed_item_writes_rejects_non_bool(cli):
    # Fail-closed: a non-boolean override is treated as denied, never truthy-coerced.
    data = {"backlogProvider": {"allowedItemWrites": {"title": "yes"}}}
    assert cli.allowed_item_writes(data)["title"] is False


# --- end to end at the Bash hook ---

def _adapter_root(tmp_path, adapter=None):
    (tmp_path / ".minervit-ai-delivery.json").write_text(json.dumps(adapter or {}))
    return tmp_path


def test_hook_blocks_title_edit_by_default(run_cli, tmp_path):
    root = _adapter_root(tmp_path)
    payload = json.dumps({"tool_name": "Bash", "cwd": str(root),
                          "tool_input": {"command": "gh issue edit 5 --title 'changed'"}})
    res = run_cli("background-command-hook", stdin=payload)
    assert '"decision": "block"' in res.stdout
    assert "title" in res.stdout.lower()


def test_hook_allows_title_edit_when_opted_in(run_cli, tmp_path):
    root = _adapter_root(tmp_path, {"backlogProvider": {"allowedItemWrites": {"title": True}}})
    payload = json.dumps({"tool_name": "Bash", "cwd": str(root),
                          "tool_input": {"command": "gh issue edit 5 --title 'changed'"}})
    res = run_cli("background-command-hook", stdin=payload)
    assert '"decision": "block"' not in res.stdout


def test_hook_allows_comment_and_status(run_cli, tmp_path):
    root = _adapter_root(tmp_path)
    for cmd in ["gh issue comment 5 --body done", "gh issue edit 5 --add-assignee @me"]:
        payload = json.dumps({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": cmd}})
        res = run_cli("background-command-hook", stdin=payload)
        assert '"decision": "block"' not in res.stdout, cmd
