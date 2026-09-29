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
