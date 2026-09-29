"""De-minervit refactor 2A PR3: GitHub-comment markers, rescue refs, compose prefix, and non-schema
state paths emit the tautline form while still reading/parsing the legacy minervit form for one
deprecation window (write-new/read-both). Lock-bearing paths and schema ids are out of scope.
"""


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
