import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_no_plugin_node_modules_are_tracked_or_present():
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "plugins"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    tracked_node_modules = [
        path for path in tracked if "/node_modules/" in path or path.endswith("/node_modules")
    ]
    assert tracked_node_modules == []

    plugin_node_modules = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "plugins").glob("**/node_modules")
        if path.is_dir()
    ]
    assert plugin_node_modules == []


def test_renderer_kit_ignores_dependency_build_and_media_outputs():
    ignore = (
        REPO_ROOT
        / "plugins/tautline-ops/skills/iteration-review/renderer-kit/.gitignore"
    ).read_text(encoding="utf-8")

    for pattern in [
        "node_modules/",
        "out/",
        "dist/",
        "build/",
        ".cache/",
        "*.mp4",
        "*.webm",
        "*.png",
        "*.jpg",
    ]:
        assert pattern in ignore


def test_iteration_review_renderer_state_dir_defaults_outside_repo(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MINERVIT_RENDERER_KIT_STATE_DIR", raising=False)

    state_dir = cli.iteration_review_renderer_state_dir()

    assert state_dir == tmp_path / ".local/state/minervit/renderer-kit"
    assert not cli.path_is_under(state_dir, cli.REPO_ROOT)


def test_iteration_review_renderer_setup_refuses_repo_local_cache(cli, monkeypatch, tmp_path):
    repo_local_cache = cli.REPO_ROOT / ".tmp-renderer-cache"
    monkeypatch.setenv("MINERVIT_RENDERER_KIT_STATE_DIR", str(repo_local_cache))

    try:
        cli.prepare_iteration_review_renderer_tree(tmp_path, cli.iteration_review_renderer_state_dir())
    except SystemExit as exc:
        assert "must be outside the methodology repo" in str(exc)
    else:
        raise AssertionError("repo-local renderer cache was accepted")
