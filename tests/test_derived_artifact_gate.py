"""RCA: derived-artifact freshness was a published HARD Stage-1 gate (canonical-rules: "regenerate
or prove those artifacts are current") enforced only by agent self-report -- no machine check.

`derived_artifact_staleness` is the machine check: within the reviewed base..HEAD diff, if a declared
artifact's source globs matched a changed file but the committed artifact itself was not changed in
that same diff, the mirror is stale (sources moved, the derived output did not). Hermetic -- it
inspects the changed-file set only, never runs a build, and cannot be silenced without actually
changing the artifact.
"""


import subprocess

import pytest


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_review_scope_changed_files_lists_outgoing_diff(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    (repo / "out.json").write_text("{}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "src" / "app.py").write_text("x = 2\n")  # source changed
    (repo / "gen.lock").write_text("locked\n")  # new file
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    assert set(cli.review_scope_changed_files(repo, base)) == {"src/app.py", "gen.lock"}


def _entry(artifact, sources, regenerate=""):
    return {"artifact": artifact, "sources": sources, "regenerate": regenerate}


def test_stale_when_source_changed_but_artifact_not(cli):
    entries = [_entry("graphify-out/graph.json", ["src/*"], "graphify . --update")]
    findings = cli.derived_artifact_staleness(entries, ["src/app.py"])
    assert len(findings) == 1
    assert "graphify-out/graph.json" in findings[0]
    assert "src/app.py" in findings[0]
    assert "graphify . --update" in findings[0]  # regenerate hint surfaced


def test_fresh_when_artifact_regenerated_in_same_diff(cli):
    entries = [_entry("graphify-out/graph.json", ["src/*"])]
    # source AND artifact both changed in the diff -> regenerated -> clean
    assert cli.derived_artifact_staleness(entries, ["src/app.py", "graphify-out/graph.json"]) == []


def test_clean_when_no_source_changed(cli):
    entries = [_entry("graphify-out/graph.json", ["src/*"])]
    assert cli.derived_artifact_staleness(entries, ["docs/readme.md", "tests/test_x.py"]) == []


def test_glob_spans_path_separators(cli):
    # fnmatch '*' spans '/', so a source glob catches nested files (conservative -> errs toward flag).
    entries = [_entry("api/schema.snapshot.json", ["api/models/*.py"])]
    findings = cli.derived_artifact_staleness(entries, ["api/models/sub/user.py"])
    assert len(findings) == 1


def test_independent_entries_reported_separately(cli):
    entries = [
        _entry("a.lock", ["a/*"]),
        _entry("b.snap", ["b/*"]),
    ]
    # only a's source changed -> exactly one finding, for a.lock
    findings = cli.derived_artifact_staleness(entries, ["a/x.py", "b.snap"])
    assert len(findings) == 1
    assert "a.lock" in findings[0]


def test_no_entries_is_clean(cli):
    assert cli.derived_artifact_staleness([], ["src/app.py"]) == []
    assert cli.derived_artifact_staleness(None, ["src/app.py"]) == []


def test_artifact_that_is_also_a_source_path_not_self_satisfied(cli):
    # If a source glob would match the artifact itself, the artifact's own change must not count as a
    # source change that satisfies freshness -- a real upstream source still has to move it.
    entries = [_entry("gen/out.json", ["gen/*"])]
    # only the artifact changed; nothing upstream -> not stale (no source moved)
    assert cli.derived_artifact_staleness(entries, ["gen/out.json"]) == []


# --- adapter config normalization (fail-closed on malformed declarations) ----------------------


def test_normalize_accepts_valid_entries(cli):
    raw = [{"artifact": "a.lock", "sources": ["a/*", "b/*"], "regenerate": "make a"}]
    assert cli.normalize_derived_artifacts(raw) == [
        {"artifact": "a.lock", "sources": ["a/*", "b/*"], "regenerate": "make a"}
    ]


def test_normalize_defaults_and_trims(cli):
    assert cli.normalize_derived_artifacts([{"artifact": "  a.lock  ", "sources": [" a/* "]}]) == [
        {"artifact": "a.lock", "sources": ["a/*"], "regenerate": ""}
    ]


def test_normalize_missing_is_empty_list(cli):
    assert cli.normalize_derived_artifacts(None) == []
    assert cli.normalize_derived_artifacts([]) == []


def test_normalize_rejects_malformed(cli):
    for bad in [
        {"artifact": "x", "sources": ["y"]},  # not a list
        [{"sources": ["a/*"]}],  # missing artifact
        [{"artifact": "a", "sources": []}],  # empty sources
        [{"artifact": "a", "sources": "a/*"}],  # sources not a list
        [{"artifact": "a", "sources": [""]}],  # blank source glob
        ["not-an-object"],
    ]:
        with pytest.raises(SystemExit):
            cli.normalize_derived_artifacts(bad)


# --- gate errors with the narrow recorded override --------------------------------------------


def test_gate_errors_block_stale(cli):
    assert cli.derived_artifact_gate_errors([_entry("a.lock", ["a/*"])], ["a/x.py"]) != []


def test_gate_errors_acknowledged_current_clears_block(cli):
    # operator regenerated and the output was byte-identical -> explicit narrow override clears it
    assert cli.derived_artifact_gate_errors([_entry("a.lock", ["a/*"])], ["a/x.py"], ["a.lock"]) == []


# --- review-fix hardening: path normalization, ** rejection, non-ASCII paths ------------------


def test_normalize_strips_leading_dot_slash(cli):
    # './gen/out.json' must line up with git's 'gen/out.json' or a regenerated artifact false-flags.
    assert cli.normalize_derived_artifacts([{"artifact": "./gen/out.json", "sources": ["./src/*"]}]) == [
        {"artifact": "gen/out.json", "sources": ["src/*"], "regenerate": ""}
    ]


def test_normalize_rejects_double_star_glob(cli):
    # fnmatch has no recursive '**'; 'proto/**/*.proto' would silently miss shallow sources.
    with pytest.raises(SystemExit):
        cli.normalize_derived_artifacts([{"artifact": "a", "sources": ["proto/**/*.proto"]}])


def test_review_scope_changed_files_keeps_non_ascii_paths_verbatim(cli, tmp_path):
    # Default git quoting octal-escapes non-ASCII paths; a unicode-named source would then never
    # match its declared glob and a stale artifact would pass. -z must return it verbatim.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "тест.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "тест.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    changed = cli.review_scope_changed_files(repo, base)
    assert len(changed) == 1
    assert changed[0].endswith(".py")
    assert "\\" not in changed[0] and '"' not in changed[0]  # not octal-escaped / quoted


def test_review_scope_target_relative_for_subdir_target(cli, tmp_path):
    # review-fix: a sub-directory target (--target app/) must report paths RELATIVE TO THE TARGET,
    # not repo-root-relative. derivedArtifacts artifact/sources are resolved against the target, so
    # a repo-root-relative 'app/src/a.py' would never match a target-relative 'src/*' glob and a
    # stale artifact would silently pass the freshness gate. --relative keeps the gate honest.
    repo = tmp_path / "repo"
    (repo / "app" / "src").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app" / "src" / "a.py").write_text("x = 1\n")
    (repo / "app" / "out.json").write_text("{}\n")  # committed derived mirror under the target
    (repo / "top.py").write_text("y = 1\n")  # sibling outside the target subtree
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "app" / "src" / "a.py").write_text("x = 2\n")  # source changed, out.json NOT regenerated
    (repo / "top.py").write_text("y = 2\n")  # change outside the target must be excluded
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    target = repo / "app"
    changed = cli.review_scope_changed_files(target, base)
    # target-relative and scoped to the target subtree (no 'app/' prefix, no sibling 'top.py')
    assert set(changed) == {"src/a.py"}
    # and the gate now correctly catches the stale artifact for a sub-directory target
    assert cli.derived_artifact_gate_errors([_entry("out.json", ["src/*"])], changed) != []
