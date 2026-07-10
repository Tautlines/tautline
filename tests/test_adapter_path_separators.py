"""Cross-platform path separators in the generated lane adapter.

Regression: a lane adapter rendered on Windows embedded Windows-style backslash separators in
`_generated.sourceAdapter` / `_generated.regenerate` (e.g. `adapters\\projects\\example-saas.json`).
On POSIX hosts the stored value then failed to resolve to the real source adapter, which broke
every CLI command that re-resolves it (backlog-provider-status, journal publish, lane-coordination,
prepare-continuity, ...). The committed file must be host-OS-independent.

Fix: always WRITE the canonical forward-slash form (`as_posix()`), and tolerate backslashes on
READ so an already-committed Windows-rendered adapter still resolves on POSIX (and vice-versa).
"""

from pathlib import PurePosixPath


def test_source_adapter_path_tolerates_backslashes(cli):
    # A Windows-rendered value with backslashes must still resolve to the real source adapter.
    resolved = cli.source_adapter_path("adapters\\projects\\example-saas.json")
    assert resolved == (cli.REPO_ROOT / "adapters/projects/example-saas.json")
    assert resolved.exists()


def test_source_adapter_path_forward_slash_unchanged(cli):
    # The canonical forward-slash form resolves identically.
    resolved = cli.source_adapter_path("adapters/projects/example-saas.json")
    assert resolved == (cli.REPO_ROOT / "adapters/projects/example-saas.json")
    assert resolved.exists()


def test_source_adapter_path_absolute_preserved(cli):
    abs_path = (cli.REPO_ROOT / "adapters/projects/example-saas.json").resolve()
    assert cli.source_adapter_path(str(abs_path)) == abs_path


def test_display_project_arg_is_posix(cli):
    # The embedded source path is the canonical forward-slash form regardless of host OS.
    p = cli.REPO_ROOT / "adapters" / "projects" / "example-saas.json"
    arg = cli.display_project_arg(p)
    assert "\\" not in arg
    assert arg == PurePosixPath("adapters/projects/example-saas.json").as_posix()


def test_render_project_config_emits_forward_slashes(cli):
    import json

    data = cli.load_project(cli.REPO_ROOT / "adapters/projects/example-saas.json")
    rendered = json.loads(cli.render_project_config(data, "adapters/projects/example-saas.json"))
    meta = rendered["_generated"]
    assert "\\" not in meta["sourceAdapter"]
    assert "\\" not in meta["regenerate"]
    assert meta["sourceAdapter"] == "adapters/projects/example-saas.json"


def test_project_source_arg_normalizes_stored_backslashes(cli):
    # Re-emit path (write side): a stored backslashed value must NOT be re-propagated verbatim on
    # the next render. Genuine red->green on POSIX (old code returned the value unchanged).
    from pathlib import Path

    data = {"_generated": {"sourceAdapter": "adapters\\projects\\example-saas.json"}}
    assert cli.project_source_arg(data, Path("unused")) == "adapters/projects/example-saas.json"


def test_lane_start_resolves_backslashed_source_adapter(run_cli, cli, tmp_path):
    # End-to-end pin at the lane_project call site (where the production failure was raised): a
    # Windows-rendered backslashed sourceAdapter must RESOLVE, so lane-start must not die with
    # "sourceAdapter is missing". The forged target's remote intentionally mismatches example-saas,
    # so lane-start still fails the later repo-identity check -- reaching THAT proves the source
    # adapter resolved AND its sha matched (the sha is computed from the resolved file).
    import hashlib
    import json
    import subprocess

    target = tmp_path / "forged-lane"
    target.mkdir()
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:owner/not-example-saas.git"],
        check=True,
    )
    source = cli.REPO_ROOT / "adapters/projects/example-saas.json"
    data = json.loads(source.read_text())
    data["_generated"] = {
        "doNotEdit": True,
        "source": "Minervit AI Delivery Methodology",
        "sourceAdapter": "adapters\\projects\\example-saas.json",  # backslashes (Windows render)
        "sourceAdapterSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "methodologyCommit": "test",
        "pluginVersion": "test",
        "regenerate": "test",
    }
    (target / ".minervit-ai-delivery.json").write_text(json.dumps(data, indent=2) + "\n")

    res = run_cli("lane-start", "--target", str(target), "--skip-update")
    combined = res.stdout + res.stderr
    assert "sourceAdapter is missing" not in combined  # backslashed path resolved
    assert "does not match the target git remote" in combined  # reached the later, correct check
