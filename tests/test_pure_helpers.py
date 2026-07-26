"""Locks on pure, side-effect-free CLI helpers, plus documentation of a known smell."""

import inspect

from tautline_methodology import guards


def test_normalize_repo_slug(cli):
    assert cli.normalize_repo_slug("git@github.com:Org/Repo.git") == "org/repo"
    assert cli.normalize_repo_slug("<owner>/<repo>") is None


def test_parse_duration_seconds(cli):
    assert cli.parse_duration_seconds("24h") == 86400
    assert cli.parse_duration_seconds("30m") == 1800


def test_response_has_forbidden_opt_in(cli):
    assert cli.response_has_forbidden_opt_in("Should I push the branch?") is True
    assert cli.response_has_forbidden_opt_in("I pushed the branch and enabled auto-merge.") is False


def test_text_contains_any(cli):
    assert cli.text_contains_any("please keep going", ["keep going"]) is True
    assert cli.text_contains_any("all done here", ["keep going"]) is False


def test_guard_scan_helpers_are_served_from_package_through_cli_wrapper(cli):
    text = """I will stop here.

> quoted keep going should be ignored by policy scan

`inline keep going`

```
code block keep going
```

"quoted keep going"

Actual next action: keep going.
"""

    for name in (
        "text_contains_any",
        "response_guard_policy_scan_text",
        "response_guard_monitor_scan_text",
        "response_guard_context_scan_text",
    ):
        assert inspect.signature(getattr(cli, name)) == inspect.signature(getattr(guards, name))

    assert cli.text_contains_any("please keep going", ["keep going"])
    assert cli.text_contains_any("pleasekeep going", ["keep going"]) is False
    assert cli.text_contains_any("please   keep   going", ["keep going"]) is True
    assert cli.response_guard_policy_scan_text(text) == guards.response_guard_policy_scan_text(text)
    assert "quoted keep going" not in cli.response_guard_policy_scan_text(text)
    assert "inline keep going" not in cli.response_guard_policy_scan_text(text)
    assert "actual next action: keep going" in cli.response_guard_policy_scan_text(text)
    assert cli.response_guard_monitor_scan_text(text) == guards.response_guard_monitor_scan_text(text)
    assert "quoted keep going should be ignored" in cli.response_guard_monitor_scan_text(text)
    assert cli.response_guard_context_scan_text("“Keep Going”") == guards.response_guard_context_scan_text("“Keep Going”")
    assert cli.response_guard_context_scan_text("“Keep Going”") == '"keep going"'


def test_version_tuple_orders_and_tolerates_garbage(cli):
    # RCA O7 migration tolerance keys on version comparison; it must order correctly and
    # never raise on malformed input.
    assert cli.version_tuple("0.6.79") == (0, 6, 79)
    assert cli.version_tuple("0.6.73") < cli.version_tuple("0.6.79")
    assert cli.version_tuple("0.6.93") > cli.version_tuple("0.6.79")
    assert cli.version_tuple("") == (0,)
    assert cli.version_tuple("0.6.x") == (0, 6, 0)


def test_stage1_sweep_requirement_version_is_pinned(cli):
    # The migration-tolerance boundary is a real released version, not a placeholder.
    assert cli.version_tuple(cli.STAGE1_SWEEP_REQUIREMENT_PLUGIN_VERSION) >= (0, 6, 79)


def test_scratch_migration_lock_path_is_home_scoped_and_warning_backed(cli, tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    data = {"planningArtifacts": {"scratchPaths": ["scratch/plans", "scratch/notes"]}}

    lock_path = cli.scratch_migration_lock_path(data, tmp_path)

    assert lock_path.parent == home
    assert lock_path.name.startswith(".minervit-methodology-scratch-migration-")
    assert lock_path.name.endswith(".lock")
    lock_source = inspect.getsource(cli.scratch_migration_lock) + inspect.getsource(cli.directory_lock)
    assert "planning_migration_warning" in lock_source


def test_duplicate_slugify_binding_is_the_later_def(cli):
    # KNOWN SMELL: `slugify` is defined twice (lines 1429 and 4091); in-process the LATER
    # def wins. This test documents and regression-guards which binding is live so the
    # Phase 2 dedup (ratchet step 1) is a deliberate, reviewed change.
    assert "fallback" in inspect.signature(cli.slugify).parameters
    assert cli.slugify("Hello World!") == "hello-world"
