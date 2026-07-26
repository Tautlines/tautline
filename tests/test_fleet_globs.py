"""Fleet glob semantics: ** crosses directories, * does not; glob-vs-glob overlap."""

from datetime import datetime, timezone

from test_fleet_state import _init_repo, _lease


def test_star_does_not_cross_separators(cli):
    assert cli.fleet_globs_match("src/a.py", ["src/*.py"]) is True
    assert cli.fleet_globs_match("src/pkg/a.py", ["src/*.py"]) is False


def test_double_star_crosses_separators(cli):
    assert cli.fleet_globs_match("src/pkg/deep/a.py", ["src/**"]) is True
    assert cli.fleet_globs_match("docs/a.md", ["src/**"]) is False
    # A trailing /** covers the bare directory path itself too.
    assert cli.fleet_globs_match("src", ["src/**"]) is True
    assert cli.fleet_globs_match("srcx", ["src/**"]) is False


def test_interior_double_star_spans_whole_segments_only(cli):
    # "a/**/b" means zero or more WHOLE segments between a and b.
    assert cli.fleet_globs_match("src/a.py", ["src/**/a.py"]) is True
    assert cli.fleet_globs_match("src/pkg/a.py", ["src/**/a.py"]) is True
    assert cli.fleet_globs_match("src/pkg/deep/a.py", ["src/**/a.py"]) is True
    # The separator must survive translation, or this over-blocks.
    assert cli.fleet_globs_match("src/fooa.py", ["src/**/a.py"]) is False


def test_matcher_and_pair_overlap_agree_on_embedded_double_star(cli):
    # The two helpers must not disagree: whatever the real-path matcher treats as
    # recursive, the glob-vs-glob overlap check must treat as overlapping too.
    assert cli.fleet_globs_match("src/pkg/a.py", ["src/**.py"]) is True
    assert cli.fleet_glob_pair_overlap("src/**.py", "src/pkg/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/**/*.py", "src/pkg/a.py") is True


def test_glob_bracket_classes_are_literal_not_classes(cli):
    # Documented reduced syntax: brackets are NOT character classes. This test
    # exists so the limitation is provable, not just prose in the spec.
    assert cli.fleet_globs_match("src/a.py", ["src/[ab].py"]) is False
    assert cli.fleet_globs_match("src/[ab].py", ["src/[ab].py"]) is True


def test_exact_and_question_mark(cli):
    assert cli.fleet_globs_match("docs/reference/manual.md", ["docs/reference/manual.md"]) is True
    assert cli.fleet_globs_match("src/a.py", ["src/?.py"]) is True
    assert cli.fleet_globs_match("src/ab.py", ["src/?.py"]) is False


def test_non_string_globs_never_match(cli):
    assert cli.fleet_globs_match("src/a.py", [None, 42, "src/**"]) is True
    assert cli.fleet_globs_match("src/a.py", [None, 42]) is False


def test_glob_pair_overlap_wildcards_conservative(cli):
    # Wildcard-vs-wildcard overlaps must be caught (conservatively).
    assert cli.fleet_glob_pair_overlap("src/*.py", "src/a.*") is True
    assert cli.fleet_glob_pair_overlap("src/*.py", "docs/*.md") is False
    assert cli.fleet_glob_pair_overlap("src/**", "src/pkg/deep/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/a.py", "src/a.py") is True
    # A bare literal covers only its exact path, not descendants.
    assert cli.fleet_glob_pair_overlap("src", "src/a.py") is False


def test_glob_sets_overlap_returns_first_pair(cli):
    hit = cli.fleet_glob_sets_overlap(["docs/**", "src/*.py"], ["src/a.*"])
    assert hit == ("src/*.py", "src/a.*")
    assert cli.fleet_glob_sets_overlap(["docs/**"], ["src/**"]) is None
    assert cli.fleet_glob_sets_overlap([None, ""], ["src/**"]) is None


def test_conflicting_lease_foreign_live_only(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    now = datetime.now(timezone.utc)
    own = tmp_path / "repo"          # our own worktree
    other = tmp_path / "wt-other"    # a different lane
    cli.write_fleet_lease(
        repo, _lease(cli, lease_id="0a0a01", worktree=str(own), globs=("src/**",))
    )
    cli.write_fleet_lease(
        repo, _lease(cli, lease_id="0b0b02", worktree=str(other), globs=("docs/**",))
    )

    # Own lease never conflicts; foreign lease conflicts on its globs only.
    assert cli.fleet_conflicting_lease(repo, "src/a.py", own, now) is None
    hit = cli.fleet_conflicting_lease(repo, "docs/x.md", own, now)
    assert hit is not None and hit["lease_id"] == "0b0b02"
    assert cli.fleet_conflicting_lease(repo, "other/y.txt", own, now) is None


def test_conflicting_lease_none_owner_treats_all_foreign(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    now = datetime.now(timezone.utc)
    cli.write_fleet_lease(
        repo, _lease(cli, lease_id="0a0a01", worktree=str(repo), globs=("src/**",))
    )
    assert cli.fleet_conflicting_lease(repo, "src/a.py", None, now) is not None


def test_conflicting_lease_ignores_stale(cli, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    now = datetime.now(timezone.utc)
    stale = _lease(
        cli, lease_id="0c0c03", worktree=str(tmp_path / "wt-x"), globs=("src/**",), ttl=1
    )
    stale["renewed_at"] = "2020-01-01T00:00:00+00:00"
    stale["claimed_at"] = "2020-01-01T00:00:00+00:00"
    cli.write_fleet_lease(repo, stale)
    assert cli.fleet_conflicting_lease(repo, "src/a.py", tmp_path / "repo", now) is None


def test_dot_slash_prefixed_globs_are_normalized(cli):
    # A "./"-prefixed glob would otherwise claim happily and guard nothing, and would
    # not even collide with its own bare equivalent at claim time.
    assert cli.fleet_globs_match("src/a.py", ["./src/**"]) is True
    assert cli.fleet_globs_match("src/a.py", ["./src/*.py"]) is True
    assert cli.fleet_glob_pair_overlap("./src/**", "src/a.py") is True
    assert cli.fleet_glob_sets_overlap(["./src/**"], ["src/pkg/**"]) is not None


def test_recursive_glob_does_not_swallow_disjoint_narrowed_claims(cli):
    """`**` absorbs zero or more WHOLE segments -- it must not short-circuit to
    "overlaps everything". `src/**/a.py` and `src/b.py` share a `**` yet NO path
    matches both, and reporting overlap there rejects a legitimately narrowed
    claim, which breaks the guard's own first escape ("narrow the edit outside
    the leased globs")."""
    assert cli.fleet_glob_pair_overlap("src/**/a.py", "src/b.py") is False
    assert cli.fleet_glob_pair_overlap("src/**/a.py", "docs/a.py") is False
    assert cli.fleet_glob_sets_overlap(["src/**/a.py"], ["src/b.py"]) is None
    # ...but genuine intersections through the ** must still be caught.
    assert cli.fleet_glob_pair_overlap("src/**/a.py", "src/pkg/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/**/a.py", "src/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/**", "src/pkg/deep/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/**.py", "src/pkg/a.py") is True
    assert cli.fleet_glob_pair_overlap("src/**/*.py", "src/pkg/a.py") is True


def test_narrowing_escape_actually_works_end_to_end(run_cli, tmp_path):
    """The block message's escape (1) tells a lane to narrow outside the leased
    globs. That advice must be actionable: a narrowed, genuinely disjoint claim
    has to succeed under block enforcement."""
    from test_fleet_lease_cli import _cleanup_wt, _fleet_repo, _worktree

    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        first = run_cli(
            "fleet-lease", "claim", "--target", str(repo), "--globs", "src/**/a.py"
        )
        assert first.returncode == 0, first.stderr
        narrowed = run_cli(
            "fleet-lease", "claim", "--target", str(wt), "--globs", "src/b.py"
        )
        assert narrowed.returncode == 0, narrowed.stdout + narrowed.stderr
        assert "fleet_lease: claimed" in narrowed.stdout
    finally:
        _cleanup_wt(repo, wt)
