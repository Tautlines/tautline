"""Behavior-spec delta REPORTING on `behavior-spec-status` (backlog item 72, Release B).

RCA `20260615T135932Z` clause (c): `behavior-spec-status` reported only absolute, repo-wide
inactive-scenario counts. A repo can carry 200 inactive scenarios for a year and a PR that adds
the 201st looks exactly like a PR that adds none -- so growth per change was invisible at the one
surface policy 15 requires before every plan finalization, merge, and delivery.

`--base <ref>` answers "what did THIS branch add", and it answers it as a REPORT: it never changes
the exit code (decision D5). Enforcement of the same rule lives in `behavior-spec-delta-check`,
which is diff-scoped and refuses; the division of labour is pinned here by
`TestFourCornerExitContract`, which runs both verbs on one fixture.

Three properties this file exists to hold, each of which was a real defect somewhere in item 72's
history rather than a hypothetical:

* **the count and the offender list are DIFFERENT sets** (plan amendment A4). A fully annotated
  `@pending` scenario is still growth. Driving the count off the offender list reports `0` for it,
  which is the invisibility gap this release closes. `test_a_compliant_added_scenario_is_still_growth`
  is that pin, and it fails if anyone "simplifies" the two sets into one;
* **`--base` reads ONE tree** (amendments A7/A10). Scenario text comes from HEAD blobs and the base
  commit's blobs, never from the worktree, so an uncommitted edit cannot make pre-existing debt look
  introduced or hide debt that is. `TestDirtyWorktree` shifts spans and deletes files on disk and
  requires the report not to move; and
* **a blind read reports `unknown`, never `0`.** A check that cannot see is indistinguishable from
  a clean one if it prints a number it cannot stand behind -- the defect class the whole item
  exists to close, adopted here from `behavior-spec-delta-check`'s `_blind`.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from tautline_methodology.core.runtime import BEHAVIOR_PENDING_CANONICAL_FORM

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLIANT_TAG = "@pending @owner:alice @reason:api-not-built @unpend:when-api-lands"


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


def _behavior(**overrides):
    return {
        "behaviorSpecs": {
            "paths": ["features/**"],
            "pendingTags": ["@pending"],
            "pendingRequiresOwnerAndTrigger": True,
            **overrides,
        }
    }


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _status(cli, monkeypatch, repo, data, *, strict=False, base=None):
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))
    args = argparse.Namespace(project=None, target=repo, strict=strict, base=base)
    return cli.behavior_spec_status(args)


def _delta_check(cli, monkeypatch, repo, data):
    monkeypatch.setattr(cli, "lane_project", lambda args: (data, None, repo))
    args = argparse.Namespace(project=None, target=repo, event="pre-commit")
    return cli.behavior_spec_delta_check(args)


def _lines(text, prefix):
    return [line for line in text.splitlines() if line.startswith(prefix)]


class TestAddedDeltaReporting:
    def test_it_reports_and_cites_a_metadata_less_scenario_this_branch_added(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text("Scenario: active\n", encoding="utf-8")
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            "@pending\nScenario: brand new, unannotated\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add debt")

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out
        added_issues = _lines(out, "behavior_specs_added_issue:")
        assert len(added_issues) == 1, out
        assert "brand new, unannotated" in added_issues[0]
        assert "features/new.feature:2" in added_issues[0]
        # The citation is INTERPOLATED from the constant, never retyped: the form grew a
        # `@reason:` field in 0.47.0, and a hardcoded copy of the two-field shape would have
        # silently told authors to write an annotation the gate rejects.
        assert BEHAVIOR_PENDING_CANONICAL_FORM in added_issues[0]
        assert "@owner:" in added_issues[0] and "@unpend:" in added_issues[0]

    def test_a_compliant_added_scenario_is_still_growth(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """Plan amendment A4, the pin the un-amended task text got backwards.

        `behavior_specs_added_inactive` counts every newly inactive scenario, annotated or not.
        Deriving it from the offender list reports `0` here -- and "this PR added an inactive
        scenario" would then be invisible at the exact surface the RCA says must show it.
        """
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text("Scenario: active\n", encoding="utf-8")
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            f"{COMPLIANT_TAG}\nScenario: annotated but inactive\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add annotated debt")

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out
        assert f"behavior_specs_added_issues: 0 (vs {base})" in out
        assert _lines(out, "behavior_specs_added_issue:") == []

    def test_stripping_metadata_reports_an_issue_with_zero_added(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The offender list is deliberately NOT a subset of the count, and this is the shape that
        proves it. Removing `@owner:`/`@unpend:` from a scenario that already existed introduces
        debt without introducing a scenario, so `0 added` and `1 issue` is the correct answer.
        Anything that "tidies" these into one set loses this case silently."""
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text(f"{COMPLIANT_TAG}\nScenario: annotated\n  Given x\n", encoding="utf-8")
        base = _commit(repo, "base")
        path.write_text("@pending\nScenario: annotated\n  Given x\n", encoding="utf-8")
        _commit(repo, "strip the metadata")

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 0 (vs {base})" in out
        assert f"behavior_specs_added_issues: 1 (vs {base})" in out
        added_issues = _lines(out, "behavior_specs_added_issue:")
        assert len(added_issues) == 1 and "annotated" in added_issues[0]

    def test_pre_existing_debt_is_never_reported_as_added(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """Invariant I3 on the reporting surface. A branch that never touches the debt reports 0
        added, while the repo-wide `behavior_specs_issue:` lines stay exactly as they were -- the
        two answers are to two different questions and neither may contaminate the other."""
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text(
            "@pending\nScenario: ancient debt\n  Given x\n", encoding="utf-8"
        )
        base = _commit(repo, "base")
        (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
        _commit(repo, "unrelated change")

        _status(cli, monkeypatch, repo, _behavior())
        without_base = capsys.readouterr().out
        _status(cli, monkeypatch, repo, _behavior(), base=base)
        with_base = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 0 (vs {base})" in with_base
        assert _lines(with_base, "behavior_specs_added_issue:") == []
        assert _lines(with_base, "behavior_specs_issue:") == _lines(
            without_base, "behavior_specs_issue:"
        )
        assert _lines(without_base, "behavior_specs_issue:") != []

    def test_a_rename_between_in_scope_paths_introduces_nothing(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The rename map is actually threaded through. Without it a moved file has no base entry
        under its new path and every pre-existing scenario in it reads as introduced -- a false
        report produced by a `git mv`. The deep pairing semantics stay pinned by
        `tests/test_behavior_spec_delta_check.py`; this is the passthrough pin only."""
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text(
            "@pending\nScenario: ancient debt\n  Given x\n", encoding="utf-8"
        )
        base = _commit(repo, "base")
        _git(repo, "mv", "features/old.feature", "features/moved.feature")
        _commit(repo, "rename in scope")

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 0 (vs {base})" in out
        assert _lines(out, "behavior_specs_added_issue:") == []

    def test_without_base_no_delta_surface_and_no_git_work(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """`methodology-status` calls this printer on every invocation, and policy 15 requires
        `methodology-status` before every finalization, merge and delivery. It does not get a
        merge-base plus a unified diff added to its hot path."""
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: debt\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "base")

        seen = _GitSpy(monkeypatch)
        _status(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr().out

        assert _lines(out, "behavior_specs_added_inactive:") == []
        assert _lines(out, "behavior_specs_added_issue:") == []
        assert _lines(out, "behavior_specs_added_warning:") == []
        assert seen.git_argv == [], seen.git_argv


class TestDirtyWorktree:
    """Plan amendment A10: `--base` reads HEAD blobs, so the worktree cannot move the report.

    Both halves are needed because a worktree-reading implementation fails them in opposite
    directions: an edit ABOVE a scenario shifts its span (making untouched debt look introduced),
    and deleting an added scenario from disk hides debt the branch really did add.
    """

    def _repo_with_added_debt(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text(
            "@pending\nScenario: ancient debt\n  Given x\n", encoding="utf-8"
        )
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            "@pending\nScenario: added debt\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add debt")
        return repo, base

    def _delta_lines(self, out):
        return (
            _lines(out, "behavior_specs_added_inactive:")
            + _lines(out, "behavior_specs_added_issues:")
            + _lines(out, "behavior_specs_added_issue:")
        )

    def test_an_uncommitted_edit_above_pre_existing_debt_changes_nothing(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._repo_with_added_debt(tmp_path)
        _status(cli, monkeypatch, repo, _behavior(), base=base)
        clean = self._delta_lines(capsys.readouterr().out)

        path = repo / "features" / "old.feature"
        path.write_text("# shifted\n# shifted\n" + path.read_text(encoding="utf-8"), "utf-8")

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        dirty = self._delta_lines(capsys.readouterr().out)

        assert dirty == clean
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in clean

    def test_deleting_the_added_scenario_from_disk_does_not_hide_it(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._repo_with_added_debt(tmp_path)
        (repo / "features" / "new.feature").unlink()

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out
        added_issues = _lines(out, "behavior_specs_added_issue:")
        assert len(added_issues) == 1 and "added debt" in added_issues[0]


class TestBlindReadFloor:
    """S5 / the non-vacuity floor. `0` and "I could not look" must never print the same."""

    def test_an_unresolvable_base_reports_unknown_and_leaves_the_exit_code_alone(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: debt\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "base")

        without_base = _status(cli, monkeypatch, repo, _behavior(), strict=True)
        capsys.readouterr()
        with_bad_base = _status(
            cli, monkeypatch, repo, _behavior(), strict=True, base="no-such-ref"
        )
        out = capsys.readouterr().out

        assert with_bad_base == without_base == 1
        assert _lines(out, "behavior_specs_added_warning:") != []
        assert "behavior_specs_added_inactive: unknown (vs no-such-ref)" in out
        assert "behavior_specs_added_issues: unknown (vs no-such-ref)" in out
        assert "behavior_specs_added_inactive: 0" not in out

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_base_says_so_instead_of_reporting_nothing(
        self, cli, monkeypatch, capsys, tmp_path, blank
    ):
        """`--base ""` is what an unset CI variable expands to. Under a truthiness test the whole
        report vanishes — no count, no warning — and silence reads exactly like a branch with no
        growth. A whitespace ref is the same defect wearing a value."""
        repo = self._seeded(tmp_path)

        code = _status(cli, monkeypatch, repo, _behavior(), base=blank)
        out = capsys.readouterr().out

        assert code == 0
        assert "blank ref" in "\n".join(_lines(out, "behavior_specs_added_warning:"))
        assert f"behavior_specs_added_inactive: unknown (vs {blank})" in out
        assert f"behavior_specs_added_issues: unknown (vs {blank})" in out

    def test_an_unknown_ref_and_unrelated_histories_do_not_share_a_remedy(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """Both used to collapse into one merge-base failure, so a lane comparing an orphan branch
        was told to fetch a ref it already had. A remedy that does not apply is a dead end."""
        repo = self._seeded(tmp_path)
        # Read the branch back rather than assuming `master`: `init.defaultBranch` is a per-machine
        # git setting, so a hardcoded name passes locally and fails on any runner configured
        # differently — which is exactly what it did on CI.
        original = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        _git(repo, "checkout", "-q", "--orphan", "unrelated")
        _git(repo, "rm", "-q", "-rf", ".")
        (repo / "README.md").write_text("orphan\n", encoding="utf-8")
        _commit(repo, "orphan root")
        orphan = _git(repo, "rev-parse", "HEAD").strip()
        _git(repo, "checkout", "-q", original)

        _status(cli, monkeypatch, repo, _behavior(), base=orphan)
        unrelated = capsys.readouterr().out
        _status(cli, monkeypatch, repo, _behavior(), base="no-such-ref")
        unknown = capsys.readouterr().out

        assert "no common ancestor" in unrelated
        assert "git fetch" not in unrelated
        assert "git fetch" in unknown
        assert "no common ancestor" not in unknown

    def test_an_empty_path_scope_is_unknown_not_zero(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The floor this program has now paid for three times: a work set derived from a pattern
        that selects nothing reports 0 findings, and 0 findings reads as clean. A stale or mistyped
        `behaviorSpecs.paths` must not answer confidently."""
        repo = self._seeded(tmp_path)
        base = _git(repo, "rev-parse", "HEAD").strip()

        _status(cli, monkeypatch, repo, _behavior(paths=["nowhere/**"]), base=base)
        out = capsys.readouterr().out

        assert "behaviorSpecs.paths" in "\n".join(_lines(out, "behavior_specs_added_warning:"))
        assert f"behavior_specs_added_inactive: unknown (vs {base})" in out

    def test_an_unreadable_tip_file_is_unknown_not_a_partial_count(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """Reachable for real in a blobless or partial clone. A count computed from the files that
        did load is one the report cannot stand behind, and it is usually the number a clean tree
        prints."""
        repo, base = self._committed_debt(tmp_path)
        real = cli.behavior_pending_scenarios_at_revision
        monkeypatch.setattr(
            cli, "behavior_pending_scenarios_at_revision",
            lambda d, t, rev: ([], ["features/a.feature"]) if rev == "HEAD" else real(d, t, rev),
        )

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0
        assert "features/a.feature" in out and "at HEAD" in out
        assert f"behavior_specs_added_inactive: unknown (vs {base})" in out

    def test_an_unreadable_base_file_is_unknown_not_a_flood_of_false_additions(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """Reading an unreadable BASE as "no pre-existing debt" would report every scenario in the
        file as introduced — the worst available direction, since it is exactly the pre-existing
        debt invariant I3 protects."""
        repo, base = self._committed_debt(tmp_path)
        real = cli.behavior_pending_scenarios_at_revision
        monkeypatch.setattr(
            cli, "behavior_pending_scenarios_at_revision",
            lambda d, t, rev: real(d, t, rev) if rev == "HEAD" else ([], ["features/a.feature"]),
        )

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0
        assert f"behavior_specs_added_inactive: unknown (vs {base})" in out

    def test_an_unreadable_file_list_is_capped_so_the_reason_survives(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """An unbounded join is truncated by log shippers, and the truncation takes the reason
        with it — leaving a warning that explains nothing."""
        repo, base = self._committed_debt(tmp_path)
        many = [f"features/f{i}.feature" for i in range(9)]
        monkeypatch.setattr(
            cli, "behavior_pending_scenarios_at_revision",
            lambda d, t, rev: ([], many) if rev == "HEAD" else ([], []),
        )

        _status(cli, monkeypatch, repo, _behavior(), base=base)
        warning = _lines(capsys.readouterr().out, "behavior_specs_added_warning:")[0]

        assert "and 4 more" in warning
        assert "features/f8.feature" not in warning
        assert "at HEAD" in warning

    def test_a_failed_diff_is_unknown_rather_than_a_rename_misread(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._committed_debt(tmp_path)

        def _raise(*_args, **_kwargs):
            raise cli.BehaviorRevisionUnavailable("diff")

        monkeypatch.setattr(cli, "git_diff_text_at", _raise)

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0
        assert f"behavior_specs_added_inactive: unknown (vs {base})" in out

    def test_an_unexpected_failure_lands_on_the_floor_and_not_on_the_exit_code(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The load-bearing one. `--base` is documented as never changing the exit code; without a
        guard, `git` absent from PATH raises out of the report, the verb dies before printing
        `behavior_specs_effective_enforcement:`, and a reporting flag has silently become a gate."""
        repo, base = self._committed_debt(tmp_path)

        def _boom(*_args, **_kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(cli, "run_git", _boom)

        without_base = _status(cli, monkeypatch, repo, _behavior(), strict=True)
        capsys.readouterr()
        with_base = _status(cli, monkeypatch, repo, _behavior(), strict=True, base=base)
        out = capsys.readouterr().out

        assert with_base == without_base
        assert "failed unexpectedly" in out
        assert f"behavior_specs_added_inactive: unknown (vs {base})" in out
        assert _lines(out, "behavior_specs_effective_enforcement:") != []

    def _seeded(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: debt\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "seed")
        return repo

    def _committed_debt(self, tmp_path):
        repo = self._seeded(tmp_path)
        return repo, _git(repo, "rev-parse", "HEAD").strip()


class TestKnownScenarioIdentityGaps:
    """A KNOWN GAP, pinned so it stays visible and cannot be re-broken silently. Deferred to A3
    (`ready/2026-08-10-behavior-spec-scenario-identity`, item 1: duplicate pairing across
    cardinality changes); the release notes say so rather than claiming a fix that is not here.

    A Gherkin scenario has no stable identity. `behavior_delta_findings` therefore pairs instances
    sharing a `(path, name)` IN LINE ORDER, and that tie-break is what makes an unchanged tree pair
    each instance with itself instead of falsely refusing. The cost is this case: insert a new bare
    duplicate ABOVE an existing one and annotate the original, and the new bare instance takes the
    old one's slot, so it reads as pre-existing debt.

    Why it is pinned rather than fixed HERE. The helper is shared with `behavior-spec-delta-check`,
    a gate. Three of A2's four review rounds proved that each patch to this pairing minted a fresh
    FALSE REFUSAL, which is the expensive direction for a gate and why the codex-run comparison was
    removed rather than patched a fourth time. Trading a narrow under-report on a REPORT for a new
    false refusal on a gate is a bad trade; A3 owns scenario identity and fixes both at once.

    The blast radius here is bounded by what this surface is: no exit code moves, nothing is
    refused, and `behavior_specs_added_inactive` still counts the growth correctly — only the
    issue half mis-attributes which of two same-named instances is the new one.

    This test asserts the gap. When A3 closes it, this test SHOULD fail — that is the point.
    """

    def test_an_inserted_duplicate_name_is_mistaken_for_the_pre_existing_instance(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = _repo(tmp_path)
        path = repo / "features" / "a.feature"
        path.write_text("@pending\nScenario: dup\n  Given x\n", encoding="utf-8")
        base = _commit(repo, "base: one bare scenario named dup")
        # Annotate the original AND insert a new bare scenario with the same name above it.
        path.write_text(
            "@pending\nScenario: dup\n  Given new\n\n"
            f"{COMPLIANT_TAG}\nScenario: dup\n  Given x\n",
            encoding="utf-8",
        )
        _commit(repo, "annotate the original, insert a new bare duplicate above it")

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0
        # Growth is still counted correctly: one more inactive scenario than the base had.
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out
        # THE GAP: the branch did add a bare `@pending`, and the issue half does not say so,
        # because line-order pairing gave the new instance the old one's slot. A3 item 1.
        assert f"behavior_specs_added_issues: 0 (vs {base})" in out
        assert _lines(out, "behavior_specs_added_issue:") == []


class TestAdapterOptOut:
    """`pendingRequiresOwnerAndTrigger: false` is a deliberate project decision, and both
    `behavior_spec_status_record` and `behavior-spec-delta-check` honour it. A report that lists
    offenders anyway invents debt the project has decided it does not have — the reporting
    surface's version of a false refusal."""

    def test_the_issue_half_is_disabled_while_growth_still_reports(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text("Scenario: active\n", encoding="utf-8")
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            "@pending\nScenario: bare but permitted\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add bare scenario")

        data = _behavior(pendingRequiresOwnerAndTrigger=False)
        code = _status(cli, monkeypatch, repo, data, base=base)
        out = capsys.readouterr().out

        assert code == 0
        # The count is NOT governed by this flag: it measures growth in inactive scenarios, which
        # the adapter's ceiling still cares about.
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out
        assert "behavior_specs_added_issues: disabled by adapter" in out
        assert _lines(out, "behavior_specs_added_issue:") == []


class TestFourCornerExitContract:
    """Decision D5 and the division of labour, on ONE fixture.

    The fixture is the shape that makes the contract falsifiable: pre-existing metadata-less debt
    committed at the base, plus an added COMPLIANT inactive scenario. Reporting must show growth
    (1 added) while refusing nothing, and the repo-wide exit code must be identical with and
    without `--base`.
    """

    def _fixture(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text(
            "@pending\nScenario: ancient debt\n  Given x\n", encoding="utf-8"
        )
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            f"{COMPLIANT_TAG}\nScenario: annotated but inactive\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add annotated scenario")
        return repo, base

    def test_strict_exits_1_with_and_without_base_and_the_issue_lines_are_identical(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._fixture(tmp_path)

        bare = _status(cli, monkeypatch, repo, _behavior(), strict=True)
        bare_out = capsys.readouterr().out
        based = _status(cli, monkeypatch, repo, _behavior(), strict=True, base=base)
        based_out = capsys.readouterr().out

        assert bare == based == 1
        assert _lines(based_out, "behavior_specs_issue:") == _lines(
            bare_out, "behavior_specs_issue:"
        )
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in based_out
        assert _lines(based_out, "behavior_specs_added_issue:") == []

    def test_warn_enforcement_with_base_still_exits_0(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._fixture(tmp_path)

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in out

    def test_the_staged_gate_passes_the_same_tree_the_repo_wide_gate_refuses(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The enforcement half: `behavior-spec-delta-check` sees only what the change introduces,
        so pre-existing debt exits 0 there while `--strict` status exits 1 on the same repo. That
        asymmetry IS the design -- diff-scoping the status verb's repo-wide ceiling stays
        METH-FU-BEHAVIOR-SPEC-CEILING-DIFF-SCOPE's deferred scope."""
        repo, base = self._fixture(tmp_path)
        (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
        _git(repo, "add", "-A")

        staged = _delta_check(cli, monkeypatch, repo, _behavior())
        capsys.readouterr()
        strict = _status(cli, monkeypatch, repo, _behavior(), strict=True, base=base)
        status_out = capsys.readouterr().out

        assert staged == 0
        assert strict == 1
        # The `base=` argument has to be load-bearing here, or this "pair" test silently degrades
        # into two exit-code assertions that `--base` is documented never to affect.
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in status_out
        assert f"behavior_specs_added_issues: 0 (vs {base})" in status_out

    def test_a_noncompliant_addition_still_leaves_the_exit_code_at_0_under_warn(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """D5's load-bearing corner. Every other case here has a compliant addition or an already
        failing exit code, so `return 1 if ... or offending` would pass the whole suite. This is
        the case where the delta finds a real offender and the exit code must not notice."""
        repo = _repo(tmp_path)
        (repo / "features" / "old.feature").write_text("Scenario: active\n", encoding="utf-8")
        base = _commit(repo, "base")
        (repo / "features" / "new.feature").write_text(
            "@pending\nScenario: bare and new\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "add bare scenario")

        code = _status(cli, monkeypatch, repo, _behavior(), base=base)
        out = capsys.readouterr().out

        assert code == 0, out
        assert f"behavior_specs_added_issues: 1 (vs {base})" in out
        assert len(_lines(out, "behavior_specs_added_issue:")) == 1

    def test_a_staged_metadata_less_scenario_is_refused_by_the_staged_gate(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo, base = self._fixture(tmp_path)
        (repo / "features" / "worse.feature").write_text(
            "@pending\nScenario: newly staged debt\n  Given x\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")

        staged = _delta_check(cli, monkeypatch, repo, _behavior())
        err = capsys.readouterr().err

        assert staged == 1
        assert "newly staged debt" in err
        # The status verb still answers about COMMITTED history, so the unstaged-to-committed
        # scenario is not in its `--base` answer. Two verbs, two revisions, deliberately.
        _status(cli, monkeypatch, repo, _behavior(), base=base)
        assert f"behavior_specs_added_inactive: 1 (vs {base})" in capsys.readouterr().out


# The full stdout of `behavior-spec-status` (no `--base`) at 0.52.0 on the fixture built by
# `TestInstructionLineCitation._fixture`, captured before the instruction line changed. This is a
# golden of the LINE SEQUENCE, not of one line: it fails on an inserted line, a dropped line, a
# reordered line, or a second changed line -- which is what makes "exactly one line moved" a real
# claim rather than a description of the diff its author intended.
GOLDEN_0_52_0 = [
    "behavior_specs: required=false enforcement=warn feature_files=1 inactive_scenarios=2 "
    "harnesses=0",
    "behavior_specs_pending_tags: @pending",
    "behavior_specs_feature_files: 1 - features/a.feature",
    "behavior_specs_inactive_sample: features/a.feature:2, features/a.feature:6",
    "behavior_specs_instruction: Executable behavior specs must run against the app package "
    "being changed; inactive acceptance scenarios require owner, reason, and un-pend trigger "
    "and cannot be normalized as covered.",
    "behavior_specs_issue: inactive acceptance scenarios exceed limit: 2 > 0; remove pending "
    "tags or record owner, reason, and un-pend trigger",
    "behavior_specs_issue: inactive scenario missing owner, un-pend trigger: "
    "features/a.feature:6 bare and inactive",
    "behavior_specs_effective_enforcement: warn",
]


class TestInstructionLineCitation:
    """RCA control #2's second clause: the canonical form is cited where every author already
    looks, and the `behavior_specs_issue:` lines -- which consumers and tests parse -- stay
    byte-identical."""

    def _fixture(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            f"{COMPLIANT_TAG}\n"
            "Scenario: annotated and inactive\n  Given x\n\n"
            "@pending\nScenario: bare and inactive\n  Given y\n",
            encoding="utf-8",
        )
        _commit(repo, "seed")
        return repo

    def test_exactly_one_line_moved_and_it_is_the_instruction_line(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        repo = self._fixture(tmp_path)

        _status(cli, monkeypatch, repo, _behavior())
        actual = capsys.readouterr().out.splitlines()

        assert len(actual) == len(GOLDEN_0_52_0), actual
        pairs = zip(actual, GOLDEN_0_52_0, strict=True)
        differing = [i for i, (a, b) in enumerate(pairs) if a != b]
        assert len(differing) == 1, [actual[i] for i in differing]
        index = differing[0]
        assert actual[index].startswith("behavior_specs_instruction:")
        # A pure APPEND: the pre-change sentence survives verbatim inside the new line.
        assert actual[index].startswith(GOLDEN_0_52_0[index])
        assert BEHAVIOR_PENDING_CANONICAL_FORM in actual[index]
        assert "@unpend:<trigger>" in actual[index]

    def test_the_citation_is_sourced_from_the_constant(self, cli, monkeypatch, capsys, tmp_path):
        """A retyped form drifts from the refusals the moment the form gains a field -- which it
        did, in 0.47.0, when `@reason:` was added."""
        repo = self._fixture(tmp_path)
        monkeypatch.setattr(
            cli, "BEHAVIOR_PENDING_CANONICAL_FORM", "@pending @sentinel:<value>", raising=True
        )

        _status(cli, monkeypatch, repo, _behavior())
        out = capsys.readouterr().out

        instruction = _lines(out, "behavior_specs_instruction:")[0]
        assert "@sentinel:<value>" in instruction


class _GitSpy:
    """Records the argv of every `git` subprocess launched while it is installed.

    Installed on `subprocess.run` itself rather than on `run_git`, because the revision readers
    reach git through three different doors (`run_git`, `git_object_bytes`, and `run_command`) and
    a spy that watches only one of them proves nothing about the other two.
    """

    def __init__(self, monkeypatch):
        self.git_argv: list[list[str]] = []
        real = subprocess.run

        def recording(args, *rest, **kwargs):
            argv = list(args) if isinstance(args, (list, tuple)) else [str(args)]
            if argv and Path(str(argv[0])).name == "git":
                self.git_argv.append([str(item) for item in argv])
            return real(args, *rest, **kwargs)

        monkeypatch.setattr(subprocess, "run", recording)


class TestSingleScan:
    """Finding 10: `behavior_spec_status_record` walks every feature file in the repo, and both
    verbs that print it were computing it twice per invocation."""

    def _repo(self, tmp_path):
        repo = _repo(tmp_path)
        (repo / "features" / "a.feature").write_text(
            "@pending\nScenario: debt\n  Given x\n", encoding="utf-8"
        )
        _commit(repo, "seed")
        return repo

    def _counting(self, cli, monkeypatch):
        calls: list[int] = []
        real = cli.behavior_spec_status_record

        def counting(data, target):
            calls.append(1)
            return real(data, target)

        monkeypatch.setattr(cli, "behavior_spec_status_record", counting)
        return calls

    def test_behavior_spec_status_scans_once(self, cli, monkeypatch, capsys, tmp_path):
        repo = self._repo(tmp_path)
        calls = self._counting(cli, monkeypatch)

        _status(cli, monkeypatch, repo, _behavior(), strict=True)
        capsys.readouterr()

        assert len(calls) == 1

    def test_the_printer_does_not_recompute_a_record_it_was_given(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The threading is what makes one scan possible; this is the pin that fails if a future
        caller quietly drops the argument and the printer starts scanning again."""
        repo = self._repo(tmp_path)
        data = _behavior()
        precomputed = cli.behavior_spec_status_record(data, repo)

        def refuse(*_args, **_kwargs):
            raise AssertionError("print_behavior_spec_status recomputed a supplied record")

        monkeypatch.setattr(cli, "behavior_spec_status_record", refuse)
        issues = cli.print_behavior_spec_status(data, repo, precomputed)
        capsys.readouterr()

        assert issues == precomputed["issues"]

    def test_methodology_status_scans_once_and_adds_no_git_work_for_behavior_specs(
        self, cli, monkeypatch, capsys, tmp_path
    ):
        """The hot-path pin, run through the real verb rather than around it.

        The spy is scoped to the behavior-spec section by a window opened around the printer, so
        it measures what this release could have added and not the git work `methodology-status`
        legitimately does for other gates. `test_the_spy_can_see_git_work` is its non-vacuity
        floor -- without it, a spy that watched the wrong door would pass forever.
        """
        repo = self._repo(tmp_path)
        project = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
        data = cli.load_project(project)
        data["behaviorSpecs"] = {**data["behaviorSpecs"], **_behavior()["behaviorSpecs"]}
        # The board provider would shell out to `gh` and reach the network; this test is about
        # one section of the verb and must not depend on GitHub being reachable or authorized.
        data["backlogProvider"] = {**data.get("backlogProvider", {}), "enabled": False}
        monkeypatch.setattr(cli, "lane_project", lambda args: (data, project, repo))

        spy = _GitSpy(monkeypatch)
        calls: list[int] = []
        window: list[list[str]] = []
        real_record = cli.behavior_spec_status_record
        real_printer = cli.print_behavior_spec_status

        def _in_window(func, *args, **kwargs):
            start = len(spy.git_argv)
            try:
                return func(*args, **kwargs)
            finally:
                window.extend(spy.git_argv[start:])

        def counting_record(*args, **kwargs):
            calls.append(1)
            return _in_window(real_record, *args, **kwargs)

        monkeypatch.setattr(cli, "behavior_spec_status_record", counting_record)
        monkeypatch.setattr(
            cli, "print_behavior_spec_status",
            lambda *a, **kw: _in_window(real_printer, *a, **kw),
        )
        args = argparse.Namespace(
            project=project, target=repo, no_remote=True, fail_on_drift=False,
            strict=False, enter_remediation_on_debt=False,
        )
        cli.methodology_status(args)
        capsys.readouterr()

        assert len(calls) == 1, calls
        assert window == [], window

    def test_the_spy_can_see_git_work(self, cli, monkeypatch, capsys, tmp_path):
        """Non-vacuity floor for `_GitSpy`. `--base` demonstrably reaches git, so a spy that
        records nothing there is broken rather than reassuring."""
        repo = self._repo(tmp_path)
        base = _git(repo, "rev-parse", "HEAD").strip()

        spy = _GitSpy(monkeypatch)
        _status(cli, monkeypatch, repo, _behavior(), base=base)
        capsys.readouterr()

        # BOTH doors, because `assert window == []` in the test above is only as strong as the
        # spy's coverage: `run_git` (merge-base) and `git_object_bytes` (cat-file). A spy that
        # watched one of them would keep passing if the other started doing work.
        assert any("merge-base" in argv for argv in spy.git_argv), spy.git_argv
        assert any("cat-file" in argv for argv in spy.git_argv), spy.git_argv
