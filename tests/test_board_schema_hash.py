"""Slice B trigger (board-as-source-of-truth): "auto-propose on mismatch". The adapter stores a
hash of the board's schema (fields + single-select options, in column order). When the live board's
schema diverges from the stored hash, the agent re-proposes an aligned adapter. The hash must be
stable across irrelevant churn (field display order) but sensitive to meaningful change (a new/renamed
column, a reordered column, a new field) — because column order IS the workflow.
"""


def _fields(*specs):
    """specs: (name, type, [option names]) -> the shape gh project field-list --format json returns."""
    out = []
    for name, ftype, options in specs:
        f = {"id": f"F_{name}", "name": name, "type": ftype}
        if options is not None:
            f["options"] = [{"id": f"O_{name}_{o}", "name": o} for o in options]
        out.append(f)
    return out


STATUS = ("Status", "ProjectV2SingleSelectField", ["Funnel", "Todo", "In progress", "Done"])
SIZE = ("Size", "ProjectV2SingleSelectField", ["XS", "S", "M"])
TITLE = ("Title", "ProjectV2Field", None)


def test_hash_is_stable_for_identical_schema(cli):
    a = cli.board_schema_hash(_fields(STATUS, SIZE, TITLE))
    b = cli.board_schema_hash(_fields(STATUS, SIZE, TITLE))
    assert a == b
    assert isinstance(a, str) and len(a) >= 16


def test_hash_ignores_field_display_order(cli):
    # The order fields appear in the board's field list is cosmetic, not schema.
    assert cli.board_schema_hash(_fields(STATUS, SIZE, TITLE)) == cli.board_schema_hash(_fields(TITLE, SIZE, STATUS))


def test_hash_changes_when_a_column_is_added(cli):
    base = cli.board_schema_hash(_fields(STATUS))
    plus = cli.board_schema_hash(_fields(("Status", "ProjectV2SingleSelectField", ["Funnel", "Todo", "In progress", "Done", "Ready"])))
    assert base != plus


def test_hash_changes_when_columns_are_reordered(cli):
    # Column order is the workflow order — reordering is a meaningful schema change.
    a = cli.board_schema_hash(_fields(("Status", "ProjectV2SingleSelectField", ["Todo", "Funnel", "Done"])))
    b = cli.board_schema_hash(_fields(("Status", "ProjectV2SingleSelectField", ["Funnel", "Todo", "Done"])))
    assert a != b


def test_hash_changes_when_a_field_is_added(cli):
    assert cli.board_schema_hash(_fields(STATUS)) != cli.board_schema_hash(_fields(STATUS, SIZE))


# --- mismatch detector: stored hash vs live board ---

def test_schema_changed_is_false_when_hash_matches(cli):
    fields = _fields(STATUS, SIZE)
    stored = cli.board_schema_hash(fields)
    assert cli.board_schema_changed(stored, fields) is False


def test_schema_changed_is_true_when_board_diverges(cli):
    stored = cli.board_schema_hash(_fields(STATUS))
    assert cli.board_schema_changed(stored, _fields(STATUS, SIZE)) is True


def test_schema_changed_is_true_when_no_hash_stored_yet(cli):
    # A never-adopted board (no stored hash) is a mismatch -> propose adoption.
    assert cli.board_schema_changed("", _fields(STATUS)) is True
    assert cli.board_schema_changed(None, _fields(STATUS)) is True
