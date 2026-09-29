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


# --- item 71 T1.4 row 2: the warning-only callers degrade LOUDLY --------------------------------


def _enabled(cli, monkeypatch, tmp_path):
    data = {"goalTracker": {"enabled": True}, "backlogProvider": {"enabled": True}}
    monkeypatch.setattr(cli, "goal_tracker_config", lambda d: d["goalTracker"])
    monkeypatch.setattr(cli, "backlog_provider_config", lambda d: d["backlogProvider"])
    monkeypatch.setattr(cli, "goal_tracker_auth_issues", lambda t: [])
    monkeypatch.setattr(cli, "goal_tracker_status_issues", lambda d, t: [])
    return data
