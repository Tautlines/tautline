"""Framework-owned `## Milestone Progress` checklist synced into the goal GitHub issue.

Covers the pure renderer, the marker-delimited in-place upsert, and the best-effort gh
orchestrator (resolution gates, idempotency, the empty-body/jq-null corruption guard, human
content preservation, and the non-blocking failure contract that keeps a gh outage from ever
wedging `goal-advance`).
"""

PLAN = """# Goal 5 — Advanced Private Product A Operations

Lots of human-authored planning prose that must never be disturbed.

## GitHub Project Source

- provider: github-projects
- owner: acme
- project_number: 2
- project_item_url: https://github.com/acme/widgets/issues/42
- status: Ready

## Milestone roadmap

| **G5.M1** | ... |
"""


def _run():
    return {
        "sourceGoal": "plan.md",
        "updatedAt": "2026-06-21T00:00:00Z",
        "milestones": [
            {"index": 1, "title": "G5.M1 — Production board", "status": "complete"},
            {"index": 2, "title": "G5.M2 — Cost basis", "status": "complete"},
            {"index": 3, "title": "G5.M3 — Receiving lots", "status": "in_progress"},
            {"index": 4, "title": "G5.M4 — Valuation", "status": "pending"},
        ],
    }


def _data(repo="acme/widgets"):
    return {"repo": repo}


def _seed_plan(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN, encoding="utf-8")
    return tmp_path


def test_render_block_is_marker_delimited_and_annotated(cli):
    block = cli.render_milestone_progress_block(_run())
    assert block.startswith(cli.MILESTONE_PROGRESS_START)
    assert block.rstrip().endswith(cli.MILESTONE_PROGRESS_END)
    assert cli.MILESTONE_PROGRESS_HEADING in block
    assert "2/4 milestones complete" in block
    assert "(updated 2026-06-21T00:00:00Z)" in block
    lines = block.splitlines()
    assert "- [x] G5.M1 — Production board" in lines
    assert "- [x] G5.M2 — Cost basis" in lines
    assert "- [ ] G5.M3 — Receiving lots — _in progress_" in lines
    assert "- [ ] G5.M4 — Valuation" in lines


def test_render_block_orders_by_index(cli):
    run = {"milestones": [
        {"index": 3, "title": "third", "status": "pending"},
        {"index": 1, "title": "first", "status": "complete"},
        {"index": 2, "title": "second", "status": "pending"},
    ]}
    checklist = [ln for ln in cli.render_milestone_progress_block(run).splitlines() if ln.startswith("- [")]
    assert checklist == ["- [x] first", "- [ ] second", "- [ ] third"]


def test_checkbox_line_strips_leading_heading_markers(cli):
    # A title that begins with "## " must not emit raw markdown structure.
    line = cli.milestone_progress_checkbox_line({"index": 1, "title": "## Roadmap injected", "status": "pending"})
    assert line == "- [ ] Roadmap injected"
    assert "## " not in line


def test_upsert_replaces_between_markers_and_preserves_human_content(cli):
    block_v1 = cli.render_milestone_progress_block(_run())
    body = f"# Title\n\nintro prose\n\n{block_v1}\n\n## Human Roadmap\n\nkeep me\n"
    # A second render (different content) must replace only the marker span.
    run2 = _run()
    run2["milestones"][3]["status"] = "complete"
    out = cli.upsert_marker_block(body, cli.MILESTONE_PROGRESS_START, cli.MILESTONE_PROGRESS_END,
                                  cli.render_milestone_progress_block(run2))
    assert "# Title" in out and "intro prose" in out
    assert "## Human Roadmap" in out and "keep me" in out
    assert "3/4 milestones complete" in out  # M4 now complete
    assert out.count(cli.MILESTONE_PROGRESS_START) == 1  # no duplicate blocks
    assert out.count(cli.MILESTONE_PROGRESS_END) == 1
    assert out.index(cli.MILESTONE_PROGRESS_END) < out.index("## Human Roadmap")


def test_upsert_appends_when_markers_absent(cli):
    body = "# Title\n\nbody only\n"
    block = cli.render_milestone_progress_block(_run())
    out = cli.upsert_marker_block(body, cli.MILESTONE_PROGRESS_START, cli.MILESTONE_PROGRESS_END, block)
    assert out.startswith("# Title")
    assert "body only" in out
    assert out.rstrip().endswith(cli.MILESTONE_PROGRESS_END)


def test_upsert_into_empty_body_emits_no_stray_content(cli):
    out = cli.upsert_marker_block("", cli.MILESTONE_PROGRESS_START, cli.MILESTONE_PROGRESS_END,
                                  cli.render_milestone_progress_block(_run()))
    assert out.startswith(cli.MILESTONE_PROGRESS_START)
    assert "null" not in out


def test_sync_noop_when_goal_not_linked_to_issue(cli, tmp_path):
    (tmp_path / "plan.md").write_text("# Goal\n\nno project source here\n", encoding="utf-8")
    assert cli.sync_goal_issue_milestone_progress(_data(), tmp_path, _run()) == []


def test_sync_skips_when_repo_not_owner_name(cli, tmp_path):
    _seed_plan(tmp_path)
    out = cli.sync_goal_issue_milestone_progress(_data(repo=""), tmp_path, _run())
    assert out and "milestone_progress_skipped" in out[0]
    assert "#42" in out[0]


def test_sync_edits_issue_with_checklist(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)
    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append(command)
        if command[1:3] == ["issue", "view"]:
            return 0, "# Issue body\n\nexisting prose\n", ""
        if command[1:3] == ["issue", "edit"]:
            return 0, "", ""
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out = cli.sync_goal_issue_milestone_progress(_data(), tmp_path, _run())
    assert out and "milestone_progress_synced: issue #42" in out[0]
    assert "(2/4 complete)" in out[0]
    edit = next(c for c in calls if c[1:3] == ["issue", "edit"])
    body = edit[edit.index("--body") + 1]
    assert "# Issue body" in body and "existing prose" in body  # original body preserved
    assert cli.MILESTONE_PROGRESS_HEADING in body
    assert "- [x] G5.M1 — Production board" in body


def test_sync_does_not_corrupt_empty_issue_body_with_null(cli, tmp_path, monkeypatch):
    # Regression: `gh issue view --json body --jq .body` yields "null" for a title-only issue.
    _seed_plan(tmp_path)
    captured = {}

    def fake_run_command(command, cwd=None, timeout=None):
        if command[1:3] == ["issue", "view"]:
            return 0, "null", ""  # simulate the jq-null sentinel reaching the caller
        if command[1:3] == ["issue", "edit"]:
            captured["body"] = command[command.index("--body") + 1]
            return 0, "", ""
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out = cli.sync_goal_issue_milestone_progress(_data(), tmp_path, _run())
    assert out and "milestone_progress_synced" in out[0]
    body = captured["body"]
    assert body.startswith(cli.MILESTONE_PROGRESS_START)  # no leading "null" line
    assert "null" not in body.splitlines()[0]
    assert not body.lstrip().startswith("null")


def test_sync_is_idempotent_when_already_current(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)
    run = _run()
    current = cli.upsert_marker_block(
        "# Issue body\n\nprose\n", cli.MILESTONE_PROGRESS_START, cli.MILESTONE_PROGRESS_END,
        cli.render_milestone_progress_block(run),
    )
    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append(command)
        if command[1:3] == ["issue", "view"]:
            return 0, current, ""
        raise AssertionError("must not edit when already current")

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.sync_goal_issue_milestone_progress(_data(), tmp_path, run) == []
    assert all(c[1:3] != ["issue", "edit"] for c in calls)


def test_sync_is_non_blocking_when_gh_missing(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)

    def boom(command, cwd=None, timeout=None):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(cli, "run_command", boom)
    out = cli.sync_goal_issue_milestone_progress(_data(), tmp_path, _run())
    assert out and "milestone_progress_skipped: gh unavailable" in out[0]


def test_sync_warns_but_does_not_raise_on_edit_failure(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)

    def fake_run_command(command, cwd=None, timeout=None):
        if command[1:3] == ["issue", "view"]:
            return 0, "# Issue body\n", ""
        return 1, "", "HTTP 403: Resource not accessible"

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out = cli.sync_goal_issue_milestone_progress(_data(), tmp_path, _run())
    assert out and "milestone_progress_warning" in out[0]
    assert "403" in out[0]
