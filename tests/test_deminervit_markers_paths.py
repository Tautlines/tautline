"""De-minervit refactor 2A PR3: GitHub-comment markers, rescue refs, compose prefix, and non-schema
state paths emit the tautline form while still reading/parsing the legacy minervit form for one
deprecation window (write-new/read-both). Lock-bearing paths and schema ids are out of scope.
"""


def test_milestone_markers_emit_tautline_and_keep_legacy_constants(cli):
    assert cli.MILESTONE_PROGRESS_START == "<!-- tautline:milestone-progress:start -->"
    assert cli.MILESTONE_PROGRESS_END == "<!-- tautline:milestone-progress:end -->"
    assert cli.LEGACY_MILESTONE_PROGRESS_START == "<!-- minervit:milestone-progress:start -->"
    assert cli.LEGACY_MILESTONE_PROGRESS_END == "<!-- minervit:milestone-progress:end -->"


def test_upsert_replaces_a_legacy_marker_block_in_place(cli):
    # An issue body posted under the old brand carries the legacy markers. Re-upserting must find and
    # REPLACE that block with the new tautline-marked block, never append a duplicate.
    ls, le = cli.LEGACY_MILESTONE_PROGRESS_START, cli.LEGACY_MILESTONE_PROGRESS_END
    ns, ne = cli.MILESTONE_PROGRESS_START, cli.MILESTONE_PROGRESS_END
    body = f"Issue title\n\n{ls}\nold progress\n{le}\n\ntrailing note\n"
    block = f"{ns}\n## Milestone Progress\n- [x] done\n{ne}"
    out = cli.upsert_marker_block(body, ns, ne, block, legacy_markers=(ls, le))
    assert ns in out and ne in out          # emits the tautline markers
    assert ls not in out and le not in out  # legacy block replaced, not left behind
    assert out.count("## Milestone Progress") == 1  # no duplicate block
    assert "Issue title" in out and "trailing note" in out  # surrounding text preserved


def test_stakeholder_question_emits_tautline_and_parses_both(cli):
    tautline_marker = cli.stakeholder_question_marker({"id": "Q1", "status": "open"})
    assert "tautline-question" in tautline_marker and "minervit-question" not in tautline_marker
    # A legacy marker already posted under the old brand, in the same attr format.
    legacy_marker = cli.stakeholder_question_marker({"id": "Q2", "status": "answered"}).replace(
        "tautline-question", "minervit-question"
    )
    parsed = cli.stakeholder_question_parse_markers(tautline_marker + "\n" + legacy_marker)
    ids = {p["id"] for p in parsed}
    assert ids == {"Q1", "Q2"}  # both the new and legacy forms are found


def test_renderer_state_dir_default_and_legacy_fallback(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MINERVIT_RENDERER_KIT_STATE_DIR", raising=False)
    # Fresh lane -> tautline path.
    assert cli.iteration_review_renderer_state_dir() == tmp_path / ".local/state/tautline/renderer-kit"
    # A lane that only has legacy state keeps using it (read-both).
    legacy = tmp_path / ".local/state/minervit/renderer-kit"
    legacy.mkdir(parents=True)
    assert cli.iteration_review_renderer_state_dir() == legacy


def test_rescue_state_dir_default_and_legacy_fallback(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(cli.METHODOLOGY_RESCUE_STATE_ENV, raising=False)
    monkeypatch.delenv("TAUTLINE_METHODOLOGY_RESCUE_STATE_DIR", raising=False)
    assert cli.methodology_rescue_state_dir() == tmp_path / ".local/state/tautline/methodology-rescue"
    legacy = tmp_path / ".local/state/minervit/methodology-rescue"
    legacy.mkdir(parents=True)
    assert cli.methodology_rescue_state_dir() == legacy


def test_compose_prefix_default_is_tautline(cli):
    assert cli.DEFAULT_LOCAL_RESOURCE_ISOLATION["composeProjectPrefix"] == "tautline"
    scaffold = cli.project_scaffold("Example App", "example-app", "adapter-schema.json")
    assert scaffold["localResourceIsolation"]["composeProjectPrefix"].startswith("tautline-")
