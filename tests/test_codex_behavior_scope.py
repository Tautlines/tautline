"""RCA 20260615T071304Z: the codex-run behavior-spec pre-check (0.6.94) hard-blocked any
behavior-touching PR whenever behavior-spec-status reported ANY issue -- including hundreds of
pre-existing repo-wide @pending placeholders the PR never touched, so every behavior-touching PR
was gridlocked on debt it never created.

`git_added_line_ranges` maps the outgoing diff's HEAD-side added/modified line ranges so the gate
blocks only on inactive scenarios the diff itself introduces (and structural/harness defects);
pre-existing inactive-scenario debt becomes a non-blocking warning. These tests pin the diff
parsing (the novel logic the fix turns on) including the target-relative keying.
"""


import subprocess


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init(repo):
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _head(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_git_added_line_ranges_new_modified_and_deleted(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    (repo / "a.feature").write_text("L1\nL2\nL3\n")
    (repo / "c.feature").write_text("gone1\ngone2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _head(repo)
    (repo / "a.feature").write_text("L1\nCHANGED\nL3\n")  # modify line 2
    (repo / "b.feature").write_text("N1\nN2\nN3\nN4\n")  # new file, 4 added lines
    (repo / "c.feature").unlink()  # delete (HEAD side is /dev/null)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    ranges = cli.git_added_line_ranges(repo, base)
    assert ranges.get("b.feature") == [(1, 4)]  # whole new file is added
    assert any(lo <= 2 <= hi for lo, hi in ranges.get("a.feature", []))  # modified line in range
    assert "c.feature" not in ranges  # a deletion adds no HEAD-side lines


def test_git_added_line_ranges_target_relative_for_subdir(cli, tmp_path):
    # review-fix (consistent with the 0.6.108 derived-artifact gate): a sub-directory target must
    # key ranges by target-relative path, matching path_relative_to_target() in the caller. Without
    # --relative the lookup would miss and a non-compliant scenario the diff itself introduced would
    # be mis-scored as pre-existing debt (fail-open).
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    _init(repo)
    (repo / "app" / "x.feature").write_text("L1\nL2\n")
    (repo / "top.feature").write_text("T1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _head(repo)
    (repo / "app" / "x.feature").write_text("L1\nL2\nL3\n")  # add line under the target
    (repo / "top.feature").write_text("T1\nT2\n")  # change outside the target subtree
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    ranges = cli.git_added_line_ranges(repo / "app", base)
    assert "x.feature" in ranges  # target-relative key
    assert "app/x.feature" not in ranges  # not repo-root-relative
    assert "top.feature" not in ranges  # outside the target subtree is excluded


def test_scenario_in_added_ranges_intersects_span(cli):
    # the helper tests the scenario's tag-through-body span, not just the Scenario: line
    scenario = {"line": 4, "spanStart": 3, "spanEnd": 9}  # tag at 3, scenario at 4, body to 9
    assert cli.scenario_in_added_ranges(scenario, [(3, 3)])  # tag-only add intersects
    assert cli.scenario_in_added_ranges(scenario, [(7, 7)])  # in-body edit intersects
    assert cli.scenario_in_added_ranges(scenario, [(1, 9)])  # enclosing range intersects
    assert not cli.scenario_in_added_ranges(scenario, [(10, 12)])  # below the span
    assert not cli.scenario_in_added_ranges(scenario, [(1, 2)])  # above the span
    assert not cli.scenario_in_added_ranges(scenario, [])  # nothing changed in this file
    # falls back to the Scenario: line when no span is present (older scenario dicts)
    assert cli.scenario_in_added_ranges({"line": 4}, [(4, 4)])
    assert not cli.scenario_in_added_ranges({"line": 4}, [(5, 5)])


_FEATURE_PENDING = """Feature: Demo

  @pending
  Scenario: does a thing
    Given x
    When y
    Then z
"""

_FEATURE_PLAIN = """Feature: Demo

  Scenario: does a thing
    Given x
    When y
    Then z
"""


def _pending_after_diff(cli, repo, rel, base):
    """The single pending scenario in `rel` and whether this diff (base..HEAD) introduced it."""
    ranges = cli.git_added_line_ranges(repo, base)
    scenarios = cli.behavior_pending_scenarios(repo / rel, ["@pending"])
    assert len(scenarios) == 1
    return cli.scenario_in_added_ranges(scenarios[0], ranges.get(rel, []))


def test_tag_only_pend_of_existing_scenario_counts_as_in_diff(cli, tmp_path):
    # CASE2: a diff that pends a previously-active scenario by adding ONLY the @pending tag line
    # above the unchanged Scenario: line must be scored as introduced-by-this-diff (would block if
    # it lacks owner/un-pend metadata), not waved through as pre-existing debt.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    (repo / "demo.feature").write_text(_FEATURE_PLAIN)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _head(repo)
    (repo / "demo.feature").write_text(_FEATURE_PENDING)  # only adds the '  @pending' line
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pend it")
    assert _pending_after_diff(cli, repo, "demo.feature", base) is True


def test_body_edit_of_inactive_scenario_counts_as_in_diff(cli, tmp_path):
    # CASE3: editing a step inside an already-@pending scenario is a modification of an inactive
    # scenario and must score as in-diff.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    (repo / "demo.feature").write_text(_FEATURE_PENDING)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _head(repo)
    (repo / "demo.feature").write_text(_FEATURE_PENDING.replace("When y", "When y2"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "edit step")
    assert _pending_after_diff(cli, repo, "demo.feature", base) is True


def test_untouched_pending_scenario_not_in_diff(cli, tmp_path):
    # A pre-existing @pending scenario the diff does not touch must NOT score as in-diff (it becomes
    # the non-blocking pre-existing-debt warning, the whole point of RCA 20260615T071304Z).
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    (repo / "demo.feature").write_text(_FEATURE_PENDING)
    (repo / "other.feature").write_text("Feature: Other\n\n  Scenario: unrelated\n    Given a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _head(repo)
    (repo / "other.feature").write_text("Feature: Other\n\n  Scenario: unrelated\n    Given a\n    When b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "touch other only")
    assert _pending_after_diff(cli, repo, "demo.feature", base) is False
