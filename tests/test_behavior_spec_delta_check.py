"""Behavior-spec pending-source enforcement (backlog item 72, Release A).

The owner+un-pend rule for newly added `@pending` scenarios was enforced only inside `codex-run`,
and only on the evidence-recording path. A commit or push that never crossed that path landed
metadata-less pending debt silently -- the mechanism that grew one adopter's debt to 268 scenarios
before a repo-wide gate detonated on an unrelated PR.

This file covers the shared predicates that make a source-time gate possible without duplicating
the rule a third time. Two properties matter more than the individual cases:

* **the metadata rule has ONE definition** -- it was copy-pasted in two places, identical only by
  luck, and a token accepted at one gate and rejected at the other is a silent divergence; and
* **adapter scoping is never widened** (invariant I4) -- revision-scoped discovery reads git tree
  objects and cannot glob the worktree, so it needs a path predicate, and a second looser rule
  there would start gating files the adapter never put in scope. The agreement test is what keeps
  the glob and the predicate the same rule.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import subprocess

import pytest

from tautline_methodology.core.runtime import (
    BEHAVIOR_PENDING_CANONICAL_FORM,
    BEHAVIOR_REVISION_INDEX,
    BehaviorRevisionUnavailable,
    behavior_feature_files,
    behavior_feature_path_selected,
    behavior_feature_paths_at_revision,
    behavior_feature_text_at_revision,
    behavior_pending_scenarios,
    behavior_pending_scenarios_at_revision,
    behavior_delta_findings,
    behavior_pending_scenarios_from_text,
    parse_added_line_ranges,
    parse_diff_rename_pairs,
    behavior_rename_sources,
    git_diff_text_at,
    behavior_pending_missing_metadata,
)

ADAPTER = {"behaviorSpecs": {"paths": ["features/**"], "pendingTags": ["@pending"]}}


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "features").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "repo")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    return repo


def _scenario(context: str) -> dict:
    return {"context": context, "line": 3, "name": "does a thing", "path": Path("x.feature")}


class TestPendingMetadataPredicate:
    def test_the_canonical_form_is_compliant(self):
        """The documented form must satisfy the gate that documents it -- otherwise the spec an
        author is told to copy is one the gate rejects."""
        assert behavior_pending_missing_metadata(BEHAVIOR_PENDING_CANONICAL_FORM) == []

    def test_the_canonical_form_is_a_subset_of_the_legacy_tokens(self):
        """`@owner:` contains `owner:` and `@unpend:` contains `unpend`, which is why adopting the
        canonical form breaks no existing gate and no existing annotation breaks under it."""
        assert "owner:" in BEHAVIOR_PENDING_CANONICAL_FORM
        assert "unpend" in BEHAVIOR_PENDING_CANONICAL_FORM

    @pytest.mark.parametrize(
        "trigger", ["un-pend when X", "unpend when X", "trigger: X", "remove @pending when X"]
    )
    def test_each_legacy_trigger_token_alone_satisfies_the_trigger_field(self, trigger):
        assert behavior_pending_missing_metadata(f"owner: alice {trigger}") == []

    def test_an_empty_context_is_missing_both_fields(self):
        assert behavior_pending_missing_metadata("") == ["owner", "un-pend trigger"]

    def test_each_field_is_reported_independently(self):
        assert behavior_pending_missing_metadata("owner: alice") == ["un-pend trigger"]
        assert behavior_pending_missing_metadata("unpend when X") == ["owner"]

    def test_the_check_is_case_insensitive(self):
        assert behavior_pending_missing_metadata("OWNER: Alice UN-PEND when X") == []

    def test_a_scenario_record_with_no_context_key_does_not_raise(self):
        """Release A's predicate takes a STRING, but scenario records come from a parser over
        adopter-supplied text and the callers here hold dicts. A caller that indexed `["context"]`
        would raise KeyError on a malformed record -- inside a fail-open gate, which would turn a
        degraded read into a crashed commit hook. Every caller reads it with `.get`."""
        scenario = {"line": 1, "name": "x", "path": Path("features/a.feature")}
        added, offending = behavior_delta_findings([scenario], [], Path("."))
        assert added == [scenario]
        assert offending == [scenario]


class TestFeaturePathPredicate:
    @pytest.mark.parametrize(
        "pattern,rel,selected",
        [
            ("features/**", "features/a.feature", True),
            ("features/**", "features/nested/a.feature", True),
            ("features/**", "other/a.feature", False),
            ("apps/web/features", "apps/web/features/a.feature", True),  # bare directory prefix
            ("apps/web/features", "apps/web/other/a.feature", False),
            ("**/*.feature", "anywhere/deep/a.feature", True),
            # `fnmatch` gets BOTH of these wrong, in opposite directions, and the plan review
            # caught them after an agreement test whose fixture happened to omit both shapes.
            # Path.glob("**/*.feature") DOES match a target-root file; fnmatch does not, so the
            # predicate would have missed debt at the repo root.
            ("**/*.feature", "a.feature", True),
            # Path.glob("features/*.feature") does NOT descend; fnmatch's `*` consumes `/`, so the
            # predicate would have WIDENED the adapter's scope -- the invariant-I4 violation.
            ("features/*.feature", "features/a.feature", True),
            ("features/*.feature", "features/nested/a.feature", False),
            ("features/?.feature", "features/a.feature", True),
            ("features/?.feature", "features/ab.feature", False),
            ("docs/spec.feature", "docs/spec.feature", True),
            ("docs/spec.feature", "docs/other.feature", False),
            ("features/**", "features/a.md", False),  # not a .feature file at all
            ("src/**", "src/a.feature", False),  # pattern does not mention features
            # Directory GLOB: Path.glob matches the directory and behavior_feature_files rglobs
            # it, so every .feature beneath is selected. Testing only the full file path against
            # the pattern rejects exactly those files and silently empties the spec set.
            ("apps/*/features", "apps/web/features/a.feature", True),
            ("apps/*/features", "apps/web/features/deep/b.feature", True),
            ("apps/*/features", "apps/web/other/a.feature", False),
            # A leading `./` is valid in an adapter path and target.glob accepts it, but the
            # target-relative candidate has no prefix.
            ("./features/**", "features/a.feature", True),
            # A TRAILING SLASH selects directories only, so the resolver rglobs each subdirectory
            # and a file directly under `features/` is NOT in scope. Stripping the slash and
            # matching the file path widened the gate past the adapter's configuration.
            ("features/*/", "features/sub/b.feature", True),
            ("features/*/", "features/a.feature", False),
        ],
    )
    def test_pattern_semantics_mirror_the_glob(self, pattern, rel, selected):
        data = {"behaviorSpecs": {"paths": [pattern]}}
        assert behavior_feature_path_selected(data, rel) is selected

    def test_no_patterns_selects_nothing(self):
        assert behavior_feature_path_selected({}, "features/a.feature") is False

    def test_a_blank_pattern_is_skipped_rather_than_matching_everything(self):
        data = {"behaviorSpecs": {"paths": ["", "   "]}}
        assert behavior_feature_path_selected(data, "features/a.feature") is False


def test_the_glob_and_the_predicate_select_the_same_files(tmp_path):
    """INVARIANT I4, and the reason both rules route through one predicate.

    Revision-scoped discovery cannot glob a git tree object, so it needs a path predicate. If that
    predicate were written separately it would drift from the glob, and the drift direction that
    matters is WIDER -- a repo whose `behaviorSpecs.paths` covers only `apps/web` must never start
    gating `vendor/*.feature`. This asserts the two agree over several pattern shapes at once.
    """
    layout = [
        "features/a.feature",
        "features/nested/b.feature",
        "apps/web/features/c.feature",
        "docs/spec.feature",
        "root.feature",  # target-root: the shape `fnmatch` missed under `**/*.feature`
        "vendor/x.feature",  # deliberately out of scope
        "features/notes.md",  # not a feature file
    ]
    for rel in layout:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Feature: x\n", encoding="utf-8")

    def agree(paths: list[str]) -> set[str]:
        data = {"behaviorSpecs": {"paths": paths}}
        globbed = {
            str(path.relative_to(tmp_path)).replace("\\", "/")
            for path in behavior_feature_files(data, tmp_path)
        }
        predicated = {rel for rel in layout if behavior_feature_path_selected(data, rel)}
        assert globbed == predicated, f"glob and predicate disagree for {paths}"
        # NON-VACUITY FLOOR. Equality alone is satisfied by both sides returning nothing, and that
        # is not a hypothetical: the first version of the predicate emptied the spec set for
        # `apps/*/features` and `./features/**`, which disabled the existing behavior-spec gates
        # while every assertion in this test still passed. A correctness bug a correctness test
        # cannot see -- the matcher was behaving exactly as written; the failure was that the gate
        # went quiet, and quiet reads as clean. Every scope here is chosen to contain files.
        assert globbed, f"scope {paths} selected nothing; an emptied scope silently disables gates"
        return globbed

    # A NARROW scope: the single-star pattern must not descend, and nothing outside the configured
    # paths may be selected. This is the direction that matters -- widening is the I4 violation.
    narrow = agree(["features/*.feature", "apps/web/features", "docs/spec.feature"])
    assert narrow == {
        "features/a.feature",
        "apps/web/features/c.feature",
        "docs/spec.feature",
    }
    assert "vendor/x.feature" not in narrow  # out of scope, and stays out
    assert "features/nested/b.feature" not in narrow  # `features/*.feature` does not descend

    # A RECURSIVE scope: `**/*.feature` reaches the target root, which is the case `fnmatch` missed.
    everything = agree(["**/*.feature"])
    assert "root.feature" in everything
    assert everything == {rel for rel in layout if rel.endswith(".feature")}

    # And a scope that descends but stays inside its subtree.
    subtree = agree(["features/**"])
    assert subtree == {"features/a.feature", "features/nested/b.feature"}

    # A DIRECTORY GLOB, and a `./`-prefixed pattern. Both are valid adapter paths that Path.glob
    # handles, and the first version of the predicate dropped every file for both -- silently
    # emptying the spec set and disabling the existing behavior-spec gates rather than failing.
    assert agree(["apps/*/features"]) == {"apps/web/features/c.feature"}
    assert agree(["./features/**"]) == {"features/a.feature", "features/nested/b.feature"}
    assert agree(["features/*/"]) == {"features/nested/b.feature"}  # directories only


# --- revision seams (invariant I1: spans and ranges from the SAME tree object) -------------------

FEATURE_WITH_LEADING_BLANKS = """

@pending
Scenario: no metadata at all
  Given a thing
"""


class TestRevisionSeams:
    def test_committed_text_is_read_unstripped_so_line_numbers_survive(self, tmp_path):
        """The reader must NOT go through a helper that strips. `run_git` does, and stripping a
        feature file's leading blank lines shifts every line number below them -- so the spans
        parsed here would stop lining up with the diff ranges they are intersected against, which
        is invariant I1 broken by the helper written to enforce it, and silently."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(FEATURE_WITH_LEADING_BLANKS, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add feature")

        text = behavior_feature_text_at_revision(repo, "HEAD", "features/a.feature")

        assert text == FEATURE_WITH_LEADING_BLANKS
        assert text.startswith("\n\n"), "leading blank lines were stripped; spans will be wrong"

        # And the span agrees with the worktree parse, which is the property that matters.
        from_tree = behavior_pending_scenarios_from_text(
            text, ["@pending"], repo / "features/a.feature"
        )
        from_disk = behavior_pending_scenarios(repo / "features/a.feature", ["@pending"])
        assert [s["spanStart"] for s in from_tree] == [s["spanStart"] for s in from_disk]
        assert from_tree[0]["spanStart"] == 3  # the @pending line, counting the two blanks

    def test_discovery_at_a_revision_matches_the_adapter_scope(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "in.feature").write_text("@pending\nScenario: x\n", encoding="utf-8")
        (repo / "vendor").mkdir()
        (repo / "vendor" / "out.feature").write_text("@pending\nScenario: y\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add features")

        found = behavior_feature_paths_at_revision(ADAPTER, repo, "HEAD")

        assert found == ["features/in.feature"]  # vendor/ is outside behaviorSpecs.paths

    def test_the_index_revision_reads_staged_content_not_the_worktree(self, tmp_path):
        """A pre-commit gate polices what is being COMMITTED. Reading the worktree there would
        judge edits the commit does not contain, and miss staged ones it does."""
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text("@pending @owner:a @unpend:x\nScenario: staged\n", encoding="utf-8")
        _git(repo, "add", "-A")
        path.write_text("@pending\nScenario: worktree only\n", encoding="utf-8")

        staged = behavior_feature_text_at_revision(repo, BEHAVIOR_REVISION_INDEX, "features/a.feature")

        assert "staged" in staged
        assert "worktree only" not in staged

    def test_an_unreadable_path_is_reported_not_silently_skipped(self, tmp_path):
        """'git could not answer' and 'no pending debt here' are different facts. Conflating them
        turns a gate into decoration on exactly the repos where git is misbehaving."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("@pending\nScenario: x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add")

        assert behavior_feature_text_at_revision(repo, "HEAD", "features/missing.feature") is None

        scenarios, unreadable = behavior_pending_scenarios_at_revision(ADAPTER, repo, "HEAD")
        assert [s["name"] for s in scenarios] == ["x"]
        assert unreadable == []

    def test_a_non_repo_target_degrades_visibly_instead_of_raising(self, tmp_path):
        """These run in generated hooks in every consumer repo, including fresh clones with no
        remote, so a hard failure is a bricked commit path (invariant I5). But fail-open must be
        VISIBLE: a listing failure is not an empty repository, and reporting nothing would make
        the gate look identical when it is working and when it is blind."""
        scenarios, unreadable = behavior_pending_scenarios_at_revision(ADAPTER, tmp_path, "HEAD")

        assert scenarios == []
        assert unreadable == ["<listing at HEAD>"]


# --- the delta decision (invariant I3: only what the diff added may block) -----------------------


class TestDeltaFindings:
    """The introduced-debt decision is a COMPARISON of two revisions' scenario sets.

    It used to intersect each scenario's span with the diff's added line ranges, and the R1 review
    found that proxy wrong in both directions at once -- a deletion above a pre-existing scenario
    made it look introduced, and a feature-level `@pending` made a file's worth of newly inactive
    scenarios look untouched. "Did the diff touch these lines" is not the question. "Did this
    change introduce this debt" is, and comparing the two revisions answers it directly.
    """

    def _tip(self):
        return [
            {"path": "features/a.feature", "line": 2, "name": "added, no metadata",
             "context": "@pending"},
            {"path": "features/a.feature", "line": 20, "name": "added, compliant",
             "context": "@pending @owner:a @unpend:x"},
            {"path": "features/a.feature", "line": 90, "name": "pre-existing, no metadata",
             "context": "@pending"},
        ]

    def _base(self):
        return [
            {"path": "features/a.feature", "line": 40, "name": "pre-existing, no metadata",
             "context": "@pending"},
        ]

    def test_only_scenarios_this_change_introduced_are_considered(self, tmp_path):
        added, offending = behavior_delta_findings(self._tip(), self._base(), tmp_path)
        assert {s["name"] for s in added} == {"added, no metadata", "added, compliant"}
        assert [s["name"] for s in offending] == ["added, no metadata"]

    def test_pre_existing_debt_never_appears(self, tmp_path):
        """Invariant I3, and the RCA's false-block: a behaviour-touching change must not be refused
        over debt it never introduced -- however far the surrounding lines moved."""
        added, offending = behavior_delta_findings(self._tip(), self._base(), tmp_path)
        assert all(s["name"] != "pre-existing, no metadata" for s in added)
        assert all(s["name"] != "pre-existing, no metadata" for s in offending)

    def test_a_line_shift_does_not_make_pre_existing_debt_look_new(self, tmp_path):
        """The base scenario sits at line 40 and the tip's at line 90. Under range intersection a
        big enough insertion above it dragged it into an added range and refused the commit; the
        comparison matches on `(path, name)`, so where it moved to is irrelevant."""
        added, _offending = behavior_delta_findings(self._tip()[2:], self._base(), tmp_path)
        assert added == []

    def test_a_compliant_addition_still_counts_as_added_inactive(self, tmp_path):
        """Delta reporting is about GROWTH, so a well-annotated new `@pending` must count. Deriving
        the number from the offending list would report zero here -- the exact signal the RCA says
        is missing."""
        added, offending = behavior_delta_findings(self._tip()[1:2], self._base(), tmp_path)
        assert [s["name"] for s in added] == ["added, compliant"]
        assert offending == []

    def test_an_unchanged_tree_contributes_nothing(self, tmp_path):
        assert behavior_delta_findings(self._base(), self._base(), tmp_path) == ([], [])

    def test_a_second_scenario_with_an_existing_name_is_still_caught(self, tmp_path):
        """Matching is a MULTISET, not a set. Adding a second noncompliant scenario that happens to
        share a name with a pre-existing one must not be absorbed by it -- a set-based match would
        report zero additions for a change that added real debt."""
        duplicate = dict(self._base()[0], line=91)
        added, offending = behavior_delta_findings(
            self._base() + [duplicate], self._base(), tmp_path
        )
        assert len(added) == 1
        assert len(offending) == 1

    def test_a_file_renamed_between_in_scope_paths_introduces_nothing(self, tmp_path):
        """Invariant I3 across a move. The base knows this scenario under its old path, so the
        lookup has to follow the rename or every scenario in a moved file reads as introduced."""
        moved = [dict(s, path="features/b.feature") for s in self._base()]
        added, _offending = behavior_delta_findings(
            moved, self._base(), tmp_path,
            {"features/b.feature": "features/a.feature"},
        )
        assert added == []

    def test_pre_existing_debt_cannot_absorb_a_new_scenario_that_shares_its_name(self, tmp_path):
        """R2's absorption finding, and the reason matching happens ONCE over the full pending set.

        Base has one noncompliant `x`. The change annotates it and adds a second, unannotated `x`.
        Two independent multiset comparisons -- one over all pending scenarios, one pre-filtered to
        the noncompliant ones -- pair the NEW debt with the OLD debt and report nothing, so a
        commit that added real debt exits 0. Compliance has to be read off aligned instances, not
        compared as a separate population.
        """
        base = [{"path": "features/a.feature", "line": 5, "name": "x", "context": "@pending"}]
        tip = [
            {"path": "features/a.feature", "line": 5, "name": "x",
             "context": "@pending @owner:a @unpend:later"},
            {"path": "features/a.feature", "line": 20, "name": "x", "context": "@pending"},
        ]

        added, offending = behavior_delta_findings(tip, base, tmp_path)

        assert len(added) == 1, added
        assert len(offending) == 1, "the new unannotated scenario was absorbed by the old debt"
        assert offending[0]["line"] == 20

    def test_an_unchanged_file_with_mixed_compliance_duplicates_is_not_refused(self, tmp_path):
        """R3's finding, and the reason instances are paired IN LINE ORDER.

        A file holding an unannotated and an annotated scenario of the same name is unchanged
        between base and tip. A rule that always consumed the COMPLIANT base instance first paired
        the unannotated tip instance with the annotated base one and reported a metadata removal --
        refusing an unchanged tree. That is the same false-refusal class as R1's P1, reintroduced
        by the fix for R2's absorption, and it reaches `codex-run` too.
        """
        both = [
            {"path": "features/a.feature", "line": 5, "name": "x", "context": "@pending"},
            {"path": "features/a.feature", "line": 20, "name": "x",
             "context": "@pending @owner:a @unpend:later"},
        ]

        assert behavior_delta_findings(list(both), list(both), tmp_path) == ([], [])

    def test_annotating_the_only_instance_introduces_nothing(self, tmp_path):
        """The other half of the tie-break: fixing existing debt must not read as introducing it."""
        base = [{"path": "features/a.feature", "line": 5, "name": "x", "context": "@pending"}]
        tip = [{"path": "features/a.feature", "line": 5, "name": "x",
                "context": "@pending @owner:a @unpend:later"}]

        assert behavior_delta_findings(tip, base, tmp_path) == ([], [])

    def test_a_file_renamed_in_from_outside_scope_introduces_everything(self, tmp_path):
        """The other direction. Its debt reaches the gate for the first time, so it is this
        change's to annotate -- and a 100% rename carries no hunk, so nothing else would see it."""
        arrived = [dict(s, path="features/new.feature") for s in self._base()]
        added, offending = behavior_delta_findings(
            arrived, [], tmp_path, {"features/new.feature": "vendor/old.feature"}
        )
        assert len(added) == 1
        assert len(offending) == 1


# --- the verb, against a real repo and a real staged index ---------------------------------------
#
# In-process with `lane_project` stubbed. Adapter RESOLUTION (source-adapter discovery, schema
# validation) is covered by its own suites; stubbing it here keeps these tests about the gate --
# real git repo, real `git add`, real parsing -- instead of about the loader.


def _behavior(**overrides):
    return {
        "behaviorSpecs": {
            "paths": ["features/**"],
            "pendingTags": ["@pending"],
            "pendingRequiresOwnerAndTrigger": True,
            **overrides,
        }
    }


class TestDeltaCheckVerb:
    def _run(self, cli, monkeypatch, repo, data):
        monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))
        args = argparse.Namespace(project=None, target=repo, event="pre-commit")
        return cli.behavior_spec_delta_check(args)

    def test_it_refuses_debt_this_commit_introduces(self, cli, monkeypatch, capsys, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: brand new, unannotated\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 1
        assert "behavior_spec_delta_error:" in out.err
        assert "brand new, unannotated" in out.err
        assert "behavior_spec_delta_instruction:" in out.err

    def test_an_annotated_scenario_passes_and_still_counts_as_growth(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending @owner:alice @unpend:when-api-lands\nScenario: annotated\n  Given x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")

        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0
        assert "behavior_specs_added_inactive: 1" in out.out

    def test_pre_existing_debt_does_not_block_an_unrelated_commit(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The RCA's false-block at the new boundary: a repo carrying metadata-less debt must
        still be able to commit changes that never touch it (invariant I3)."""
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text(
            "@pending\nScenario: ancient debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing debt")
        (repo / "README.md").write_text("unrelated change\n", encoding="utf-8")
        _git(repo, "add", "-A")

        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0
        assert "ancient debt" not in out.err
        assert "behavior_specs_added_inactive: 0" in out.out

    def test_pending_an_existing_scenario_is_caught(self, cli, monkeypatch, capsys, tmp_path):
        """Adding only the tag above an existing scenario still introduces inactive debt: the span
        covers the tag, not just the `Scenario:` line."""
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text("Scenario: was active\n  Given x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "active scenario")
        path.write_text("@pending\nScenario: was active\n  Given x\n", encoding="utf-8")
        _git(repo, "add", "-A")

        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 1
        assert "was active" in out.err

    def test_it_reads_the_index_not_the_worktree(self, cli, monkeypatch, capsys, tmp_path):
        """A pre-commit gate polices what is being COMMITTED. An unannotated edit left only in the
        worktree must not refuse a commit that does not contain it."""
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "@pending @owner:a @unpend:x\nScenario: staged and annotated\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        path.write_text("@pending\nScenario: worktree only, unannotated\n", encoding="utf-8")

        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0, out.err
        assert "worktree only" not in out.err

    def test_the_adapter_opt_out_is_honoured(self, cli, monkeypatch, capsys, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("@pending\nScenario: x\n", encoding="utf-8")
        _git(repo, "add", "-A")

        code = self._run(
            cli, monkeypatch, repo, _behavior(pendingRequiresOwnerAndTrigger=False)
        )
        out = capsys.readouterr()

        assert code == 0
        assert "disabled by adapter" in out.out

    def test_a_non_repo_target_fails_open(self, cli, monkeypatch, capsys, tmp_path):
        """Invariant I5: this runs in a generated hook in every consumer repo, including fresh
        clones. A hard failure on a tree git cannot read is a bricked commit path."""
        plain = tmp_path / "plain"
        plain.mkdir()

        code = self._run(cli, monkeypatch, plain, _behavior())

        assert code == 0

    def test_a_blind_check_reports_unknown_and_never_zero(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The count a failed check prints must not be the count a clean tree prints.

        Failing open is right -- this runs in a hook in every consumer repo -- but a fail-open that
        prints `behavior_specs_added_inactive: 0` is indistinguishable from a real clean result, in
        the logs and to any tool parsing them. A gate that looks identical when it is working and
        when it is blind has stopped being evidence of anything, which is the whole class of defect
        this item exists to close. So the diff failure path prints `unknown`.
        """
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("Feature: f\n", encoding="utf-8")
        _git(repo, "add", "-A")
        # A real HEAD, so the diff failure is a FAILURE rather than an unborn-HEAD empty base.
        _git(repo, "commit", "-qm", "base")
        (repo / "features" / "a.feature").write_text(
            "Feature: f\n@pending\nScenario: x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        def explode(*_args, **_kwargs):
            raise BehaviorRevisionUnavailable("diff HEAD...:index:")

        monkeypatch.setattr(cli, "git_diff_text_at", explode)
        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0, "a blind check must not brick the commit path"
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out
        assert "behavior_specs_added_inactive: 0" not in out.out, out.out
        assert "behavior_spec_delta_warning:" in out.out, "the degradation must be visible"

    def test_an_unstaged_adapter_edit_cannot_silence_the_gate(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R4's P1: policy and scenarios must come from the SAME revision.

        `lane_project` resolves the adapter from the worktree while everything else reads the
        index, so an adapter edited but not staged sets the rules for a tree it is not part of.
        The bypass direction is the one that matters: flipping `pendingRequiresOwnerAndTrigger` to
        false in the worktree alone would silence an otherwise enforcing staged adapter, without
        that change ever being committed or reviewed. Refuse to answer rather than answer from the
        wrong revision.
        """
        repo = _repo(tmp_path)
        adapter = repo / "adapter.json"
        adapter.write_text('{"behaviorSpecs": {"pendingRequiresOwnerAndTrigger": true}}\n')
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: unannotated\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        # Staged: enforcing. Worktree: disabled. The staged tree is what is being committed.
        adapter.write_text('{"behaviorSpecs": {"pendingRequiresOwnerAndTrigger": false}}\n')

        monkeypatch.setattr(
            cli, "lane_project",
            lambda args: (_behavior(pendingRequiresOwnerAndTrigger=False), adapter, repo),
        )
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert "behavior_spec_delta_check: disabled by adapter" not in out.out, (
            "an unstaged adapter edit silenced the gate: " + out.out
        )
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out
        assert code == 0

    def test_an_untracked_adapter_cannot_silence_the_gate_either(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R5: the same bypass through the missing-file door.

        If the adapter is untracked, staged for deletion, or unreadable, the staged blob is `None`
        -- which is ABSENT, not "same as the worktree". Skipping the guard on `None` let a
        worktree-only `pendingRequiresOwnerAndTrigger: false` print `disabled` and exit 0 using
        policy the staged revision does not carry. Absence read as agreement, which is the same
        confusion that produced the unborn-HEAD and unreadable-base findings.
        """
        repo = _repo(tmp_path)
        adapter = repo / "adapter.json"  # written, never `git add`ed
        adapter.write_text('{"behaviorSpecs": {"pendingRequiresOwnerAndTrigger": false}}\n')
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: unannotated\n", encoding="utf-8"
        )
        _git(repo, "add", "features")

        monkeypatch.setattr(
            cli, "lane_project",
            lambda args: (_behavior(pendingRequiresOwnerAndTrigger=False), adapter, repo),
        )
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert "behavior_spec_delta_check: disabled by adapter" not in out.out, (
            "an untracked adapter silenced the gate: " + out.out
        )
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out
        assert code == 0

    def test_a_partial_staged_read_reports_unknown_rather_than_a_number(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R1's fourth finding. A file that lists but will not read makes the scenario set PARTIAL,
        and a partial read is a blind read.

        Warning and then printing a count computed from the files that did load publishes a number
        the check cannot stand behind -- and that number is usually `0`, exactly what a clean tree
        prints. The warning does not help: the count is the machine-readable line.
        """
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("Feature: f\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        (repo / "features" / "b.feature").write_text(
            "@pending\nScenario: unreadable one\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        from tautline_methodology.core import runtime as rt

        # Only the STAGED read fails; HEAD still reads cleanly, so this isolates the tip branch
        # rather than falling through to the unreadable-base one.
        real = rt.behavior_feature_text_at_revision
        monkeypatch.setattr(
            rt, "behavior_feature_text_at_revision",
            lambda target, revision, rel: (
                None if revision == BEHAVIOR_REVISION_INDEX else real(target, revision, rel)
            ),
        )
        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out
        assert "behavior_specs_added_inactive: 0" not in out.out, out.out

    def test_an_unreadable_base_reports_unknown_instead_of_failing_closed(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The worst available outcome, and the one the naive handling produces.

        If the BASE cannot be read and that is treated as "no pre-existing debt", every scenario in
        the file looks introduced and the gate refuses the commit -- failing CLOSED over debt the
        change never touched. Wrong in the expensive direction: it blocks correct work, and the
        fix an author reaches for is to turn the gate off.
        """
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: pre-existing debt\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        from tautline_methodology.core import runtime as rt

        real = rt.behavior_feature_text_at_revision
        monkeypatch.setattr(
            rt, "behavior_feature_text_at_revision",
            lambda target, revision, rel: None if revision == "HEAD" else real(target, revision, rel),
        )
        code = self._run(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr()

        assert code == 0, "an unreadable base must never refuse the commit: " + out.out + out.err
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out


class TestSubdirectoryAndQuotedPaths:
    def test_a_target_below_the_repo_root_can_still_read_its_blobs(self, tmp_path):
        """`ls-files --relative` keys by TARGET-relative path while a blob spec resolves from the
        REPOSITORY root. Below a subdirectory target the two disagree, so every staged feature
        would read as unreadable and the gate would fail open on exactly the repos that configured
        a sub-path."""
        repo = _repo(tmp_path)
        sub = repo / "sub"
        (sub / "features").mkdir(parents=True)
        (sub / "features" / "a.feature").write_text(
            "@pending\nScenario: x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        text = behavior_feature_text_at_revision(sub, BEHAVIOR_REVISION_INDEX, "features/a.feature")

        assert text is not None, "blob spec was not anchored to the target"
        assert "Scenario: x" in text

        scenarios, unreadable = behavior_pending_scenarios_at_revision(
            ADAPTER, sub, BEHAVIOR_REVISION_INDEX
        )
        assert unreadable == []
        assert [s["name"] for s in scenarios] == ["x"]

    def test_a_git_quoted_path_decodes_to_the_name_discovery_returns(self):
        """Under the default core.quotePath a non-ASCII path arrives C-escaped and quoted. Storing
        the escaped text as the range key means it never matches the Unicode filename, so a newly
        added unannotated scenario in such a file passes with a count of zero."""
        diff = (
            '+++ "b/features/\\303\\251.feature"\n'
            "@@ -0,0 +1,2 @@\n"
        )
        ranges = parse_added_line_ranges(diff)

        assert "features/é.feature" in ranges, ranges

    def test_the_codex_run_gate_shares_the_one_hunk_parser(self, tmp_path):
        """`git_added_line_ranges` (the codex-run diff-scoping path) routes through
        `parse_added_line_ranges` rather than keeping its own copy.

        Not a tidiness point: the two parsers had already diverged. The cli.py copy did not decode
        git-quoted paths, so on the push boundary it stored the escaped text as the range key,
        which never matched the Unicode filename discovery returns -- a newly added unannotated
        scenario in such a file was invisible and the gate reported success.
        """
        repo = _repo(tmp_path)
        weird = repo / "features" / "é.feature"
        weird.write_text("Feature: f\n\nScenario: s\n  Given x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        base = _git(repo, "rev-parse", "HEAD").strip()
        weird.write_text(
            "Feature: f\n\n@pending\nScenario: s\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "make it pending, in a quoted path")

        from tautline_methodology import cli as cli_mod

        ranges = cli_mod.git_added_line_ranges(repo, base)

        assert "features/é.feature" in ranges, (
            f"the quoted path was not decoded, so it produced no ranges: {ranges}"
        )


class TestDeletionAndNeighbourTags:
    def test_removing_metadata_from_a_pending_scenario_is_caught(self, cli, monkeypatch, capsys, tmp_path):
        """Debt can be introduced by DELETION. A pure removal renders as `+N,0` -- nothing added --
        so a count>0 filter discarded the hunk and the gate reported zero additions and passed,
        while the staged scenario had just lost its `@owner:` line."""
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "Feature: f\n\n@pending @owner:alice @unpend:later\nScenario: annotated\n  Given x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "compliant pending scenario")

        path.write_text("Feature: f\n\n@pending\nScenario: annotated\n  Given x\n", encoding="utf-8")
        _git(repo, "add", "-A")

        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 1, out.out + out.err
        assert "annotated" in out.err

    def test_a_pure_deletion_hunk_adds_no_range(self):
        """A `+N,0` hunk added nothing on the tip side, so it contributes no added range.

        An earlier version anchored a touched point at `start` to catch metadata deleted from a
        compliant scenario. `start` is just the line the removal sits against, so deleting
        unrelated content immediately above a PRE-EXISTING noncompliant scenario marked that
        scenario touched and the gate refused -- invariant I3 broken, in a parser now shared with
        `codex-run`. The deletion case is caught by `test_a_deletion_above_pre_existing_debt_...`
        and `test_removing_metadata_from_a_pending_scenario_is_caught` instead, which measure
        compliance rather than guessing from adjacency.
        """
        assert parse_added_line_ranges("+++ b/features/a.feature\n@@ -3,1 +2,0 @@\n") == {}
        assert parse_added_line_ranges("+++ b/f.feature\n@@ -1,2 +0,0 @@\n") == {}

    def test_a_deletion_above_pre_existing_debt_does_not_refuse(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R1's P1, end to end. A pure deletion of unrelated content immediately above a
        pre-existing noncompliant `@pending` scenario must not make that scenario look introduced.

        This is the highest-cost failure available to this gate: it refuses a commit over debt the
        author did not create, in a code path shared with the push-boundary review gate. A control
        that blocks correct work is worse than no control, because the fix is to disable it.
        """
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "Feature: f\n\n# a comment that is about to go\n\n"
            "@pending\nScenario: pre-existing debt\n  Given x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")

        # Remove ONLY the comment. The scenario is untouched and shifts up by one line.
        path.write_text(
            "Feature: f\n\n\n@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 0, out.out + out.err
        assert "behavior_specs_added_inactive: 0" in out.out, out.out

    def test_a_feature_level_pending_tag_catches_every_scenario_below_it(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R1's feature-tag P2. Staging `@pending` above an existing `Feature:` makes every
        scenario in the file inactive, but the only line added is the tag near the top -- which
        intersects no scenario's span. Under range intersection a file's worth of newly inactive
        scenarios passed silently, which is the growth this verb exists to report.
        """
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "Feature: f\n\nScenario: one\n  Given x\n\nScenario: two\n  Given y\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "two active scenarios")

        path.write_text(
            "@pending\nFeature: f\n\nScenario: one\n  Given x\n\nScenario: two\n  Given y\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")

        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 1, out.out + out.err
        assert "behavior_specs_added_inactive: 2" in out.out, out.out
        assert "one" in out.err and "two" in out.err

    def test_the_codex_run_gate_sees_debt_introduced_by_deletion(self, tmp_path):
        """R2's P1: the release claims the push boundary now sees a metadata deletion, so the push
        boundary has to actually see it.

        Removing a separate `@owner:` line adds nothing, so the `+N,0` hunk carries no range and
        the range test classifies the now-noncompliant scenario as pre-existing debt. Comparing it
        against its counterpart at `base_sha` catches it. This exercises the shared comparison the
        `codex-run` block calls, on a real repo -- the alternative was to retract the claim, and a
        release note describing a fix that was not made is the defect this item is about.
        """
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "Feature: f\n\n@pending\n@owner:alice\n@unpend:later\nScenario: s\n  Given x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "compliant pending scenario")
        base_sha = _git(repo, "rev-parse", "HEAD").strip()
        # Delete ONLY the owner line: a pure `+N,0` hunk, no added lines anywhere.
        path.write_text(
            "Feature: f\n\n@pending\n@unpend:later\nScenario: s\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "drop the owner line")

        assert parse_added_line_ranges(
            subprocess.run(
                ["git", "-C", str(repo), "diff", "--relative", "--unified=0",
                 f"{base_sha}...HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout
        ) == {}, "premise: the deletion produces no added range, so ranges alone cannot see it"

        base_pending, unreadable = behavior_pending_scenarios_at_revision(ADAPTER, repo, base_sha)
        tip_pending, _ = behavior_pending_scenarios_at_revision(
            ADAPTER, repo, _git(repo, "rev-parse", "HEAD").strip()
        )
        assert unreadable == []
        _added, offending = behavior_delta_findings(tip_pending, base_pending, repo)

        assert [s["name"] for s in offending] == ["s"], offending

    def test_the_codex_run_gate_still_misses_debt_introduced_by_deletion(self, cli, tmp_path):
        """A KNOWN GAP, pinned so it stays visible and cannot be re-broken silently. Deferred to
        A3; the release notes say so rather than claiming a fix that is not here.

        `codex-run` scopes to the diff's added line ranges, and deleting an `@owner:` line adds no
        lines, so the now-noncompliant scenario reads as pre-existing debt and passes. The base-vs-
        tip comparison that sees it was wired in here and taken back out: four review rounds each
        found a fresh FALSE REFUSAL in it, and this is a blocking push gate, where refusing correct
        work is the expensive failure. `behavior-spec-delta-check` catches this case today, wired
        to no boundary.

        This test asserts the gap. When A3 closes it, this test SHOULD fail -- that is the point.
        """
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(
            "Feature: f\n\n@pending\n@owner:alice\n@unpend:later\nScenario: s\n  Given x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "compliant pending scenario")
        base_sha = _git(repo, "rev-parse", "HEAD").strip()
        path.write_text(
            "Feature: f\n\n@pending\n@unpend:later\nScenario: s\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "drop the owner line")

        status = {"pendingScenarios": behavior_pending_scenarios_at_revision(
            ADAPTER, repo, _git(repo, "rev-parse", "HEAD").strip()
        )[0]}
        blocking = cli.codex_run_blocking_pending_scenarios(_behavior(), repo, base_sha, status)

        assert blocking == [], (
            "codex-run now sees deletion-introduced debt -- if A3 wired the comparison back in, "
            "delete this test and restore the positive one; if it happened by accident, the "
            "false-refusal cases R1-R4 found need re-checking first"
        )
        # ...and the verb DOES catch it, which is why the gap is acceptable for this release.
        base_pending, _ = behavior_pending_scenarios_at_revision(ADAPTER, repo, base_sha)
        _added, offending = behavior_delta_findings(
            status["pendingScenarios"], base_pending, repo
        )
        assert [s["name"] for s in offending] == ["s"], offending

    def test_the_codex_run_gate_does_not_block_a_move_within_scope(self, cli, tmp_path):
        """R3's P1 at the wiring. Without the rename map every pre-existing scenario in a moved
        in-scope file reads as absent from the base, and the push gate refuses debt the change only
        moved -- the same false-refusal class as R1's P1, in the same shipped gate."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "Feature: f\n\n@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")
        base_sha = _git(repo, "rev-parse", "HEAD").strip()
        _git(repo, "mv", "features/a.feature", "features/b.feature")
        _git(repo, "commit", "-qm", "move it")

        status = {"pendingScenarios": behavior_pending_scenarios_at_revision(
            ADAPTER, repo, _git(repo, "rev-parse", "HEAD").strip()
        )[0]}
        blocking = cli.codex_run_blocking_pending_scenarios(_behavior(), repo, base_sha, status)

        assert blocking == [], "a move within scope introduced nothing"

    def test_the_codex_run_comparison_follows_renames(self, tmp_path):
        """R3's P1. A pure rename has no hunk, so without the rename map every pre-existing
        scenario in a file moved between two in-scope paths reads as absent from the base -- and
        the push gate refuses debt the change only moved. Same false-refusal class as R1's P1,
        reintroduced by the R2 fix, in the same shipped gate."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "Feature: f\n\n@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")
        base_sha = _git(repo, "rev-parse", "HEAD").strip()
        _git(repo, "mv", "features/a.feature", "features/b.feature")
        _git(repo, "commit", "-qm", "move it")

        base_pending, _ = behavior_pending_scenarios_at_revision(ADAPTER, repo, base_sha)
        tip_pending, _ = behavior_pending_scenarios_at_revision(
            ADAPTER, repo, _git(repo, "rev-parse", "HEAD").strip()
        )
        renames = behavior_rename_sources(
            ADAPTER, git_diff_text_at(repo, base_sha, _git(repo, "rev-parse", "HEAD").strip())
        )

        assert renames == {"features/b.feature": "features/a.feature"}, renames
        assert behavior_delta_findings(tip_pending, base_pending, repo, renames) == ([], [])

    def test_an_orphan_branch_is_unborn_and_still_enforces(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R3's orphan finding. `git checkout --orphan` leaves HEAD unborn in a repository full of
        commits on other refs, so `rev-list --all` is non-empty and the previous probe read the
        state as "git is broken" -- reporting `unknown` and waving the orphan branch's first commit
        straight through, which is exactly the commit that establishes that branch's baseline."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("Feature: f\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "history on another ref")
        _git(repo, "checkout", "-q", "--orphan", "fresh")
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: unannotated on an orphan branch\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 1, "the orphan branch's first commit must still be gated: " + out.out
        assert "behavior_specs_added_inactive: unknown" not in out.out, out.out
        assert "unannotated on an orphan branch" in out.err

    def test_rename_detection_does_not_depend_on_adopter_git_config(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R2's rename finding. With `diff.renames=false` git emits delete/add records rather than
        rename headers, so the base lookup finds no mapping and every pre-existing unannotated
        scenario in a moved file looks new -- a false refusal caused by the adopter's git config
        rather than by their change. Rename detection is pinned on at the invocation."""
        repo = _repo(tmp_path)
        _git(repo, "config", "diff.renames", "false")
        (repo / "features" / "a.feature").write_text(
            "Feature: f\n\n@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")
        _git(repo, "mv", "features/a.feature", "features/b.feature")

        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 0, "a move within scope introduced nothing: " + out.out + out.err
        assert "behavior_specs_added_inactive: 0" in out.out, out.out

    def test_a_broken_git_is_not_mistaken_for_an_unborn_head(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """R2's rev-parse finding. `run_git` reports every non-zero exit as `unavailable`, so an
        unborn HEAD and a broken git are indistinguishable from that one probe.

        Reading a failure as "unborn" empties the base set, and every pre-existing unannotated
        scenario then looks newly introduced and REFUSES the commit -- failing closed on a blind
        read, the most expensive direction available. An unborn HEAD must be confirmed positively.
        """
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: pre-existing debt\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre-existing noncompliant scenario")
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: pre-existing debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        real = cli.run_git

        def flaky(target, argv):
            # Everything git answers, EXCEPT the HEAD probe and the diff -- the shape a transient
            # git failure takes, not the shape an unborn repository takes.
            if argv[:2] == ["rev-parse", "--verify"]:
                return "unavailable"
            if "diff" in argv:
                return "unavailable"
            return real(target, argv)

        monkeypatch.setattr(cli, "run_git", flaky)
        monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
        code = cli.behavior_spec_delta_check(
            argparse.Namespace(project=None, target=repo, event="pre-commit")
        )
        out = capsys.readouterr()

        assert code == 0, "a broken git must not refuse the commit: " + out.out + out.err
        assert "behavior_specs_added_inactive: unknown" in out.out, out.out

    def test_a_quoted_non_ascii_rename_into_scope_is_seen(self):
        """R1's rename P2. Under the default `core.quotePath` a non-ASCII rename arrives as
        `rename to "features/\\303\\251.feature"`. Left quoted and escaped, the scope predicate does
        not recognise the destination -- and a 100% rename carries no hunk, so moving an
        unannotated feature file into scope produced nothing at all and passed."""
        diff = (
            "rename from \"vendor/\\303\\251.feature\"\n"
            "rename to \"features/\\303\\251.feature\"\n"
        )

        pairs = parse_diff_rename_pairs(diff)

        assert pairs == [("vendor/é.feature", "features/é.feature")], pairs
        assert behavior_rename_sources(ADAPTER, diff) == {
            "features/é.feature": "vendor/é.feature"
        }

    def test_a_whitespace_padded_pending_tag_is_honoured(self, tmp_path):
        """`behavior_spec_status_record` normalizes `[" @pending "]`; a gate that did not would
        give two enforcement answers for one adapter."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text("@pending\nScenario: x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        data = {"behaviorSpecs": {"paths": ["features/**"], "pendingTags": ["  @pending  "]}}

        scenarios, _unreadable = behavior_pending_scenarios_at_revision(
            data, repo, BEHAVIOR_REVISION_INDEX
        )

        assert [s["name"] for s in scenarios] == ["x"]

    @pytest.mark.parametrize(
        "pattern,rel,selected",
        [
            ("features/[^a].feature", "features/^.feature", True),   # pathlib: `^` is literal
            ("features/[^a].feature", "features/b.feature", False),  # ...not a negation
            ("features/[!a].feature", "features/b.feature", True),   # `!` is the negation
            ("features/[!a].feature", "features/a.feature", False),
            ("features/[]].feature", "features/].feature", True),    # `]` first is a member
        ],
    )
    def test_character_classes_follow_pathlib_not_regex(self, pattern, rel, selected):
        data = {"behaviorSpecs": {"paths": [pattern]}}
        assert behavior_feature_path_selected(data, rel) is selected


def test_a_rename_into_scope_is_treated_as_added_content(cli, monkeypatch, capsys, tmp_path):
    """A rename emits rename headers and no `@@` hunk, so the destination carried no ranges and an
    unannotated feature file MOVED into behaviorSpecs.paths reported zero additions and passed.
    `--no-renames` makes the destination read as added content, which is what it is to this gate."""
    repo = _repo(tmp_path)
    (repo / "vendor").mkdir()
    (repo / "vendor" / "a.feature").write_text("@pending\nScenario: moved in\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "out of scope")

    _git(repo, "mv", "vendor/a.feature", "features/a.feature")

    monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
    code = cli.behavior_spec_delta_check(
        argparse.Namespace(project=None, target=repo, event="pre-commit")
    )
    out = capsys.readouterr()

    assert code == 1, out.out + out.err
    assert "moved in" in out.err


@pytest.mark.parametrize(
    "pattern,rel,selected",
    [
        ("features/[!]].feature", "features/a.feature", True),   # negated, `]` is a member
        ("features/[!]].feature", "features/].feature", False),
    ],
)
def test_a_negated_class_with_a_leading_bracket_parses(pattern, rel, selected):
    assert behavior_feature_path_selected({"behaviorSpecs": {"paths": [pattern]}}, rel) is selected


def test_an_in_scope_rename_does_not_block_on_the_debt_it_moved(cli, monkeypatch, capsys, tmp_path):
    """Invariant I3, and the trade-off `--no-renames` got wrong. Moving an unannotated pending
    scenario BETWEEN two in-scope paths introduces nothing -- expanding every rename into a
    full-file addition blocked the move on pre-existing debt. Only a rename from OUTSIDE the
    adapter's scope brings its scenarios to the gate for the first time."""
    repo = _repo(tmp_path)
    (repo / "features" / "a.feature").write_text("@pending\nScenario: old debt\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre-existing debt, in scope")

    _git(repo, "mv", "features/a.feature", "features/b.feature")

    monkeypatch.setattr(cli, "lane_project", lambda args: (_behavior(), None, repo))
    code = cli.behavior_spec_delta_check(
        argparse.Namespace(project=None, target=repo, event="pre-commit")
    )
    out = capsys.readouterr()

    assert code == 0, out.out + out.err
    assert "old debt" not in out.err
