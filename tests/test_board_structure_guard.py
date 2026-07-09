"""Board-as-source-of-truth safety rule #1 (2026-06-24 incident on a private product repo, issue #5):
no code path or agent may mutate a board's STRUCTURE. The exact call that orphaned every card's
Status was a raw `gh api graphql ... updateProjectV2Field` that rebuilt the whole option set. This
guard blocks board-structure mutations (field/option create-delete-edit, item reorder) at the
PreToolUse Bash hook, while still allowing reads and per-item VALUE edits (the opt-in write path).
"""

import json


# --- structure mutations that MUST be blocked ---

def test_blocks_graphql_update_project_field(cli):
    # The exact incident call: rebuilding a single-select field's options.
    cmd = "gh api graphql -f query='mutation { updateProjectV2Field(input: {fieldId: \"x\"}) { } }'"
    assert cli.command_mutates_board_structure(cmd) is True


def test_blocks_graphql_create_project_field(cli):
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{createProjectV2Field(input:{})}'") is True


def test_blocks_graphql_delete_project_field(cli):
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{deleteProjectV2Field(input:{})}'") is True


def test_blocks_graphql_item_reorder(cli):
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{updateProjectV2ItemPosition(input:{})}'") is True


def test_blocks_gh_project_field_create(cli):
    assert cli.command_mutates_board_structure("gh project field-create 5 --owner minervit --name 'Item Type'") is True


def test_blocks_gh_project_field_delete(cli):
    assert cli.command_mutates_board_structure("gh project field-delete 5 --owner minervit --id FIELD") is True


def test_blocks_gh_project_field_edit(cli):
    assert cli.command_mutates_board_structure("gh project field-edit --id FIELD --owner minervit") is True


def test_smart_quotes_do_not_evade(cli):
    # Curly quotes must not slip a banned mutation past the guard.
    assert cli.command_mutates_board_structure("gh project field-create 5 --name ‘X’") is True


# --- things that MUST stay allowed ---

def test_allows_item_value_edit(cli):
    # Per-item VALUE write (Status progression / backlinks) is the opt-in path, not a structure change.
    assert cli.command_mutates_board_structure("gh project item-edit --id ITEM --field-id F --single-select-option-id O") is False


def test_allows_board_reads(cli):
    assert cli.command_mutates_board_structure("gh project item-list 5 --owner minervit --format json") is False
    assert cli.command_mutates_board_structure("gh project field-list 5 --owner minervit --format json") is False


def test_allows_unrelated_command(cli):
    assert cli.command_mutates_board_structure("git status") is False
    assert cli.command_mutates_board_structure("") is False


# --- the content/schema line (operator clarification 2026-06-25): agents do normal developer work
# on board ITEMS; only SCHEMA/structure changes are forbidden. ---

def test_allows_normal_developer_item_work(cli):
    # Moving cards / changing status / setting field values / issues / comments / milestone tracking.
    assert cli.command_mutates_board_structure("gh project item-edit --id I --field-id Status --single-select-option-id O") is False
    assert cli.command_mutates_board_structure("gh project item-add 5 --owner minervit --url https://github.com/o/r/issues/1") is False
    assert cli.command_mutates_board_structure("gh issue edit 123 --body 'done'") is False
    assert cli.command_mutates_board_structure("gh issue comment 123 --body 'shipped'") is False


def test_allows_status_change_via_graphql(cli):
    # updateProjectV2ItemFieldValue sets an item's Status/field VALUE — content, must stay allowed.
    cmd = "gh api graphql -f query='mutation{updateProjectV2ItemFieldValue(input:{value:{singleSelectOptionId:\"x\"}}){}}'"
    assert cli.command_mutates_board_structure(cmd) is False


# --- newly-closed schema gaps (must be blocked) ---

def test_blocks_delete_whole_project(cli):
    assert cli.command_mutates_board_structure("gh project delete 5 --owner minervit") is True


def test_blocks_edit_project_settings(cli):
    assert cli.command_mutates_board_structure("gh project edit 5 --owner minervit --title New") is True


def test_blocks_copy_and_close_and_create_project(cli):
    assert cli.command_mutates_board_structure("gh project copy 5 --owner minervit --title Clone") is True
    assert cli.command_mutates_board_structure("gh project close 5 --owner minervit") is True
    assert cli.command_mutates_board_structure("gh project create --owner minervit --title New") is True


def test_blocks_board_level_graphql_mutations(cli):
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{deleteProjectV2(input:{})}'") is True
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{updateProjectV2(input:{shortDescription:\"x\"})}'") is True
    assert cli.command_mutates_board_structure("gh api graphql -f query='mutation{createProjectV2View(input:{})}'") is True


def test_blocks_file_loaded_graphql(cli):
    # A mutation hidden in a file can't be inspected -> block; the agent must inline the query.
    assert cli.command_mutates_board_structure("gh api graphql -F query=@mutation.graphql") is True
    assert cli.command_mutates_board_structure("echo m | gh api graphql -f query=@-") is True


def test_item_create_and_delete_are_not_schema(cli):
    # Adding/removing an ITEM is content management, not a schema change (gh project item-* stays allowed).
    assert cli.command_mutates_board_structure("gh project item-create 5 --owner minervit --title T") is False
    assert cli.command_mutates_board_structure("gh project item-delete --id I --project-id P") is False


# --- the predicate must actually BLOCK at the PreToolUse Bash hook (end-to-end) ---


def _adapter_root(tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}\n")
    return tmp_path


def test_hook_blocks_board_structure_mutation(run_cli, tmp_path):
    root = _adapter_root(tmp_path)
    payload = json.dumps({
        "tool_name": "Bash",
        "cwd": str(root),
        "tool_input": {"command": "gh api graphql -f query='mutation{updateProjectV2Field(input:{})}'"},
    })
    res = run_cli("background-command-hook", stdin=payload)
    assert '"decision": "block"' in res.stdout
    assert "board" in res.stdout.lower()


def test_hook_allows_item_value_edit(run_cli, tmp_path):
    root = _adapter_root(tmp_path)
    payload = json.dumps({
        "tool_name": "Bash",
        "cwd": str(root),
        "tool_input": {"command": "gh project item-edit --id ITEM --field-id F --text done"},
    })
    res = run_cli("background-command-hook", stdin=payload)
    assert '"decision": "block"' not in res.stdout
