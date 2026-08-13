"""Item 71 WS1: a board read is verifiably complete, or it fails closed.

RCA 2026-07-31. `goal_tracker_items_for_scope` fetched ONE page and threw the payload's
`totalCount` away, so "not in the first page" and "not on the board" became indistinguishable and
`goal-start` refused an item that was present. A miss over a truncated read is not evidence of
absence, and the refusal that follows one is a false statement about the board.

The load-bearing subtlety is `totalCount` under `--query`. gh's `--query` support is already
version-dependent in this repo, and if gh reports the PROJECT-WIDE total while `--query` filters
the items it returns, a strict `total > len(items)` comparison would fail closed forever on reads
that are actually complete -- bricking `goal-start` and the blocking board-currency gate. So
scoped reads treat `totalCount` as an escalation hint only; only unscoped reads trust it. Cases 7
and 8 are what pin that, and they are the reason the shipped split is safe under either semantics.
"""

import json
import pathlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _tracker(cli, monkeypatch, *, scope_query=""):
    data = cli.load_project(EXAMPLE_ADAPTER)
    cfg = dict(cli.goal_tracker_config(data))
    cfg["scopeQuery"] = scope_query
    cfg.setdefault("owner", "example-org")
    cfg.setdefault("projectNumber", 7)
    monkeypatch.setattr(cli, "goal_tracker_config", lambda _d: cfg)
    return data


def _fake_gh(cli, monkeypatch, pages):
    """pages: list of (items, totalCount). Records each command's --limit."""
    seen = []

    def _json(command, _target):
        seen.append(command)
        items, total = pages[min(len(seen) - 1, len(pages) - 1)]
        payload = {"items": items}
        if total is not None:
            payload["totalCount"] = total
        return json.loads(json.dumps(payload))

    monkeypatch.setattr(cli, "goal_tracker_gh_json", _json)
    return seen


def _limit_of(command):
    return int(command[command.index("--limit") + 1])


def test_complete_first_page_is_returned_with_one_fetch(cli, monkeypatch, tmp_path):
    data = _tracker(cli, monkeypatch)
    seen = _fake_gh(cli, monkeypatch, [([{"id": "a"}, {"id": "b"}], 2)])

    assert cli.goal_tracker_items_for_scope(data, tmp_path, limit=100) == [{"id": "a"}, {"id": "b"}]
    assert len(seen) == 1, "a complete read must not escalate"


def test_a_short_read_escalates_to_totalcount(cli, monkeypatch, tmp_path):
    data = _tracker(cli, monkeypatch)
    seen = _fake_gh(
        cli, monkeypatch, [([{"id": "a"}], 3), ([{"id": "a"}, {"id": "b"}, {"id": "c"}], 3)]
    )

    items = cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    assert len(items) == 3
    assert len(seen) == 2
    assert _limit_of(seen[1]) >= 3, "the escalation must ask for at least totalCount"


def test_a_still_short_read_fails_closed_and_never_says_not_found(cli, monkeypatch, tmp_path):
    """The refusal must not contain language an agent reads as 'absent from the board'."""
    data = _tracker(cli, monkeypatch)
    _fake_gh(cli, monkeypatch, [([{"id": "a"}], 9), ([{"id": "a"}, {"id": "b"}], 9)])

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    message = str(raised.value)
    assert "truncated at 2 of 9" in message
    assert "not found" not in message
    assert "NOT 'not on the board'" in message


def test_absent_totalcount_with_a_non_full_page_is_trusted(cli, monkeypatch, tmp_path):
    data = _tracker(cli, monkeypatch)
    seen = _fake_gh(cli, monkeypatch, [([{"id": "a"}], None)])

    assert cli.goal_tracker_items_for_scope(data, tmp_path, limit=100) == [{"id": "a"}]
    assert len(seen) == 1


def test_absent_totalcount_escalates_to_the_ceiling_before_accusing_truncation(
    cli, monkeypatch, tmp_path
):
    """R4 P2, the same rule as the scoped case: no TRUSTED total means bound by the ceiling.

    A gh/host combination that omits totalCount on an unscoped read left the retry bounded by
    `limit * 4`. A complete 1000-item board under the default limit=100 fills that 400-item window
    and was reported `truncated ... of unknown` -- below the documented ceiling, and verifiable by
    simply fetching to it. That blocks goal-start and board-currency on valid boards.
    """
    data = _tracker(cli, monkeypatch)
    seen = _fake_gh(
        cli, monkeypatch, [([{"id": "a"}], None), ([{"id": f"i{n}"} for n in range(4)], None)]
    )

    items = cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    assert len(items) == 4, "a complete board was accused of truncation"
    assert _limit_of(seen[1]) == cli.GOAL_TRACKER_BOARD_READ_CEILING


def test_absent_totalcount_that_fills_the_ceiling_fails_closed_of_unknown(
    cli, monkeypatch, tmp_path
):
    """Genuine truncation without a total: the ceiling itself came back full."""
    data = _tracker(cli, monkeypatch)
    ceiling = 5000
    _fake_gh(
        cli,
        monkeypatch,
        [([{"id": "a"}], None), ([{"id": f"i{n}"} for n in range(ceiling)], None)],
    )

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    assert "of unknown" in str(raised.value)


def test_a_miss_over_a_complete_read_names_what_was_searched(cli, monkeypatch, tmp_path):
    """'not found in configured query/list' is what an agent reads as 'not on the board'."""
    data = _tracker(cli, monkeypatch)
    _fake_gh(cli, monkeypatch, [([{"id": "a"}, {"id": "b"}], 2)])
    monkeypatch.setattr(
        cli, "goal_tracker_items", lambda d, t: cli.goal_tracker_items_for_scope(d, t)
    )

    with pytest.raises(SystemExit) as raised:
        cli.resolve_goal_tracker_item(data, tmp_path, "missing-ref")

    message = str(raised.value)
    assert "among the 2 items of a complete board read" in message


def test_a_scoped_read_never_trusts_totalcount(cli, monkeypatch, tmp_path):
    """THE case that would brick every scoped read.

    gh may report the project-wide total while `--query` filters the items it returns. A strict
    comparison here would raise on a read that is actually complete -- permanently, on every
    `goal-start` and every blocking board-currency check.
    """
    data = _tracker(cli, monkeypatch, scope_query="is:open")
    seen = _fake_gh(cli, monkeypatch, [([{"id": "a"}, {"id": "b"}], 57)])

    assert cli.goal_tracker_items_for_scope(data, tmp_path, limit=100) == [{"id": "a"}, {"id": "b"}]
    assert len(seen) == 1, "a scoped read must not escalate on a project-wide totalCount"
    assert "--query" in seen[0]


def test_a_scoped_read_escalates_to_the_ceiling_before_accusing_truncation(cli, monkeypatch, tmp_path):
    """R2 P1. A total we refuse to TRUST cannot bound the retry either.

    Escalating to `totalCount` and then declaring truncation because the answer filled it accuses
    a COMPLETE board of being unreadable -- a broad scope where every project item matches is the
    ordinary case. On a scoped read the only honest bound is the real ceiling.
    """
    data = _tracker(cli, monkeypatch, scope_query="is:open")
    seen = _fake_gh(
        cli, monkeypatch, [([{"id": "a"}], 1), ([{"id": f"i{n}"} for n in range(4)], 1)]
    )

    items = cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    assert len(items) == 4, "a complete scoped board was accused of truncation"
    assert _limit_of(seen[1]) == cli.GOAL_TRACKER_BOARD_READ_CEILING


def test_a_scoped_read_that_fills_the_ceiling_fails_closed_of_unknown(cli, monkeypatch, tmp_path):
    """Genuine truncation on a scoped read: the ceiling itself came back full."""
    data = _tracker(cli, monkeypatch, scope_query="is:open")
    ceiling = 5000
    _fake_gh(
        cli,
        monkeypatch,
        [([{"id": "a"}], None), ([{"id": f"i{n}"} for n in range(ceiling)], None)],
    )

    with pytest.raises(SystemExit) as raised:
        cli.goal_tracker_items_for_scope(data, tmp_path, limit=1)

    assert "of unknown" in str(raised.value)


def test_board_currency_does_not_accuse_a_complete_read_of_truncation(cli):
    """R1 P1. The verified read escalates PAST the caller's page, so a length heuristic lies.

    `provider_board_currency_issues` asks for 400 items. On a board of, say, 1000, the read layer
    now escalates and returns all 1000 -- complete. The old check treated `len(items) >= 400` as
    proof of truncation and blocked the pre-push gate with "cannot guarantee currency past that
    page" on a read that had just been verified complete. Completeness is the read layer's
    guarantee now; this gate consumes it instead of re-deriving it from a page size it no longer
    controls.
    """
    source = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
    assert "guarantee currency past that page" not in source, (
        "the page-length truncation heuristic is back; it accuses a verified-complete read"
    )


# --- item 71 T1.4 / wave-0 deferred finding 3: the position map must see the whole board -------


def _position_payload(ids, *, has_next, cursor):
    return {
        "data": {
            "node": {
                "items": {
                    "nodes": [{"id": i} for i in ids],
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                }
            }
        }
    }


def test_the_position_map_pages_past_the_first_hundred(cli, tmp_path, monkeypatch) -> None:
    """This used to be ONE `items(first:100)` page with no cursor, so every item past the first
    hundred was simply missing from the authoritative board order."""
    calls = []

    def fake_gh_json(args, target):
        calls.append(args)
        cursor = next((a.split("=", 1)[1] for a in args if a.startswith("cursor=")), "")
        if not cursor:
            return _position_payload([f"i{n}" for n in range(100)], has_next=True, cursor="CUR1")
        assert cursor == "CUR1", f"page 2 did not carry page 1's endCursor: {cursor!r}"
        return _position_payload([f"i{n}" for n in range(100, 150)], has_next=False, cursor="CUR2")

    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda d, t: {"id": "PVT_1"})
    monkeypatch.setattr(cli, "goal_tracker_gh_json", fake_gh_json)

    positions = cli.goal_tracker_board_position_map({}, tmp_path)

    assert len(positions) == 150
    assert positions["i0"] == 0
    # The finding-3 acceptance: an item past position 100 is rankable by its TRUE position.
    assert positions["i119"] == 119
    assert len(calls) == 2, "the second page was never requested"


def test_a_mid_pagination_failure_returns_no_map_rather_than_a_partial_one(
    cli, tmp_path, monkeypatch
) -> None:
    """A partial map is worse than none. Callers document a fallback to item-list order and act on
    it honestly; a half-filled map looks authoritative and silently ranks the items it happens to
    contain above every item it does not."""
    def fake_gh_json(args, target):
        if not any(a.startswith("cursor=") for a in args):
            return _position_payload([f"i{n}" for n in range(100)], has_next=True, cursor="CUR1")
        raise SystemExit("board read failed on page 2")

    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda d, t: {"id": "PVT_1"})
    monkeypatch.setattr(cli, "goal_tracker_gh_json", fake_gh_json)

    assert cli.goal_tracker_board_position_map({}, tmp_path) == {}


def test_the_map_stops_at_the_same_ceiling_the_verified_read_uses(
    cli, tmp_path, monkeypatch
) -> None:
    """A board past the ceiling is a truncation, and a truncated map is exactly the partial the
    fallback exists to avoid -- so it returns nothing rather than a confident prefix."""
    page = 0

    def fake_gh_json(args, target):
        nonlocal page
        start = page * 100
        page += 1
        return _position_payload(
            [f"i{n}" for n in range(start, start + 100)], has_next=True, cursor=f"CUR{page}"
        )

    monkeypatch.setattr(cli, "goal_tracker_project_view", lambda d, t: {"id": "PVT_1"})
    monkeypatch.setattr(cli, "goal_tracker_gh_json", fake_gh_json)

    assert cli.goal_tracker_board_position_map({}, tmp_path) == {}
    assert page * 100 >= cli.GOAL_TRACKER_BOARD_READ_CEILING


# --- item 71 T1.4 row 2: the warning-only callers degrade LOUDLY --------------------------------


def _enabled(cli, monkeypatch, tmp_path):
    data = {"goalTracker": {"enabled": True}, "backlogProvider": {"enabled": True}}
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda t: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    return data


def test_the_lead_gap_scan_says_so_when_the_board_could_not_be_read(
    cli, tmp_path, monkeypatch, capsys
) -> None:
    """It returns [] either way -- the path is warning-only by design -- but "nothing is missing"
    and "I could not look" are different facts, and silence made them identical."""
    data = _enabled(cli, monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda *a, **k: (_ for _ in ()).throw(
        SystemExit("board read truncated at 400 of 402 items")
    ))

    assert cli.provider_board_business_lead_gaps(data, tmp_path) == []

    err = capsys.readouterr().err
    assert "backlog_provider_board_lead_warn: board read incomplete" in err
    assert "402" in err, "the warn line must carry the underlying reason, not just its own name"


def test_the_unplaced_issue_scan_says_so_when_the_board_could_not_be_read(
    cli, tmp_path, monkeypatch, capsys
) -> None:
    """This one matters more: it reports issues MISSING from the board, so an unreadable board
    produces the most reassuring possible answer -- nothing is missing -- from the least
    evidence."""
    data = _enabled(cli, monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "goal_tracker_items", lambda *a, **k: (_ for _ in ()).throw(
        SystemExit("board read truncated at 400 of 402 items")
    ))

    assert cli.lane_unplaced_customer_facing_issues(data, tmp_path) == []

    err = capsys.readouterr().err
    assert "lane_unplaced_customer_facing_warn: board read incomplete" in err
    assert "402" in err
