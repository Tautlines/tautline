"""Item 72 Release A -- the owner+un-pend rule has ONE definition, and it is published.

RCA `20260615T135932Z` clause (b): the accepted tokens existed only as inline string checks,
DUPLICATED between `behavior_spec_status_record` and the codex-run review block, and the
machine-checkable form was never written down anywhere an author would read. Two copies of an
unpublished rule is the mechanism -- authors discovered the format by trial, and the copies were
free to drift apart silently.

Each test below fails if the mechanism is reverted:
  * `test_no_inline_token_checks_remain` fails the moment anyone re-inlines the token strings at
    either call site, which is what "duplicated" meant.
  * `TestPublished` fails if the canonical form stops being published or stops being accepted by
    the predicate that gates on it -- a form nobody can use is not a published form.
  * `TestGlobSemantics` fails if the scope predicate goes back to `fnmatch`, which silently
    rescopes the adapter in both directions (invariant I4).
"""

import ast
import inspect
from pathlib import Path

import pytest

from tautline_methodology import cli
from tautline_methodology.core import runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"

# The tokens the rule accepts. Kept as a tuple (not list[str]) so the policy-phrases SSOT
# collector does not adopt them -- these are code tokens, not rendered policy phrases.
LEGACY_TRIGGER_TOKENS = ("un-pend", "unpend", "trigger:", "remove @pending when")


class TestSingleDefinition:
    def test_every_call_site_routes_through_the_shared_predicate(self):
        """Every caller of the owner+un-pend rule calls the shared predicate.

        This was `== 2`, pinning the two historical call sites exactly. That is a CEILING on
        callers, and the invariant is a FLOOR: adding a legitimate third caller -- as
        `behavior-spec-delta-check` does -- broke the test without duplicating anything, while an
        inline fourth copy would have passed it if a routed call were removed in the same change.
        The property that actually matters is "nobody re-implements the rule", and
        `test_no_inline_token_checks_remain` below is what enforces it.
        """
        source = CLI_PATH.read_text()
        calls = source.count("behavior_pending_missing_metadata(")
        assert calls >= 2, (
            f"expected at least the two historical call sites (behavior_spec_status_record and "
            f"the codex-run block) to call the shared predicate, found {calls}"
        )

    def test_no_inline_token_checks_remain(self):
        """No call site re-implements the rule inline.

        This is the regression that fails if the duplication returns: it counts occurrences of
        the trigger-token comparison in cli.py, which was the duplicated body.
        """
        source = CLI_PATH.read_text()
        inlined = source.count('"remove @pending when" not in')
        assert inlined == 0, (
            f"{inlined} inline copies of the un-pend token check remain in cli.py; "
            "the rule has one definition, in core.runtime.behavior_pending_missing_metadata"
        )

    def test_the_predicate_lives_in_runtime_not_the_cli_monolith(self):
        """Carve campaign: behavior-spec parsing/predicates belong beside their family."""
        assert inspect.getmodule(runtime.behavior_pending_missing_metadata) is runtime


class TestPublished:
    def test_canonical_form_is_published(self):
        assert (
            runtime.BEHAVIOR_PENDING_CANONICAL_FORM
            == "@pending @owner:<goal-or-lane> @reason:<why> @unpend:<trigger>"
        )
        assert cli.BEHAVIOR_PENDING_CANONICAL_FORM is runtime.BEHAVIOR_PENDING_CANONICAL_FORM

    def test_the_published_form_actually_satisfies_the_rule(self):
        """A published form the gate rejects would be worse than no form at all."""
        filled = (
            runtime.BEHAVIOR_PENDING_CANONICAL_FORM.replace("<goal-or-lane>", "item-72")
            .replace("<why>", "upstream API not released")
            .replace("<trigger>", "board-read-probe-lands")
        )
        assert runtime.behavior_pending_missing_metadata(filled) == []

    def test_canonical_form_is_a_strict_subset_of_the_legacy_tokens(self):
        """Adopting the canonical form can never break an existing gate."""
        form = runtime.BEHAVIOR_PENDING_CANONICAL_FORM.lower()
        assert "owner:" in form
        assert any(token in form for token in LEGACY_TRIGGER_TOKENS)

    @pytest.mark.parametrize(
        "context,expected",
        [
            ("@pending @owner:lane-a @unpend:issue-12", []),
            ("@pending owner: lane-a un-pend when #12 closes", []),
            ("@pending owner: lane-a trigger: release 1.0", []),
            ("@pending owner: lane-a remove @pending when the API ships", []),
            ("@pending @unpend:issue-12", ["owner"]),
            ("@pending @owner:lane-a", ["un-pend trigger"]),
            ("@pending", ["owner", "un-pend trigger"]),
            ("@PENDING @OWNER:LANE-A @UNPEND:X", []),
        ],
    )
    def test_rule_cases(self, context, expected):
        assert runtime.behavior_pending_missing_metadata(context) == expected


class TestGlobSemantics:
    """Invariant I4 -- the scope predicate must select exactly what `behavior_feature_files` globs.

    `fnmatch` treats `/` as an ordinary character. These three cases are precisely where it
    disagrees with `Path.glob`, in both directions.
    """

    @pytest.mark.parametrize(
        "pattern,rel,expected",
        [
            ("**/*.feature", "a.feature", True),      # fnmatch says False; Path.glob matches
            ("**/*.feature", "x/y/a.feature", True),
            # fnmatch says True here; Path.glob does not descend
            ("*.feature", "x/a.feature", False),
            ("*.feature", "a.feature", True),
            ("apps/*.feature", "apps/a.feature", True),
            ("apps/*.feature", "apps/x/a.feature", False),
            ("apps/**/*.feature", "apps/a.feature", True),
            ("features/**", "features/x/a.feature", True),
            ("features/**", "other/a.feature", False),
            # A hidden directory is a real path segment, not decoration. `lstrip("./")` is
            # character-wise and would eat the leading dot, selecting this for "features/**".
            ("features/**", ".features/a.feature", False),
            (".features/**", ".features/a.feature", True),
            ("**/*.feature", "./a.feature", True),
            # behavior_feature_files matches `features/group` as a DIRECTORY and rglobs beneath
            # it, so the predicate must select the nested file too or it under-scopes.
            ("features/*", "features/group/a.feature", True),
            ("features/*", "features/a.feature", True),
            ("apps/*.feature", "apps/x/a.feature", False),
            # Path.glob resolves a leading "./" away; the predicate must too, from either side.
            ("./features/**", "features/a.feature", True),
            ("./**/*.feature", "a.feature", True),
            # A trailing "/" is directory-only: Path.glob("features/*/") yields features/group
            # but NOT features/a.feature, so the pattern reaches files only via an ancestor.
            ("features/*/", "features/a.feature", False),
            ("features/*/", "features/group/a.feature", True),
            # A terminal "**" is directory-only too: it names directories to descend into, not a
            # wildcard for files. Measured: glob("features/*/**") -> ['features/group'].
            ("features/*/**", "features/a.feature", False),
            ("features/*/**", "features/group/a.feature", True),
            ("features/**", "features/a.feature", True),  # reached via the ancestor "features"
        ],
    )
    def test_segment_aware_matching(self, pattern, rel, expected):
        data = {"behaviorSpecs": {"paths": [pattern]}}
        assert runtime.behavior_feature_path_selected(data, rel) is expected

    def test_non_feature_paths_are_never_selected(self):
        data = {"behaviorSpecs": {"paths": ["**/*.feature"]}}
        assert runtime.behavior_feature_path_selected(data, "a.md") is False

    @pytest.mark.parametrize(
        "patterns",
        [
            ["**/*.feature"],
            ["*.feature"],
            ["apps/*.feature"],
            ["features/**"],
            ["apps/**/*.feature", "top.feature"],
            [".features/**"],
            ["features/**"],
            ["features/*"],
            ["features"],
            ["./features/**"],
            ["./**/*.feature"],
            ["features/*/"],
            ["features/*/**"],
            ["features/**/*.feature"],
        ],
    )
    def test_agrees_with_behavior_feature_files_file_for_file(self, tmp_path, patterns):
        """The agreement test: glob a real tree, and assert the predicate selects the same set.

        This is what proves I4 held -- the two cannot drift while this passes.
        """
        for rel in [
            "top.feature",
            "apps/a.feature",
            "apps/nested/b.feature",
            "features/c.feature",
            "features/deep/d.feature",
            ".features/hidden.feature",
            "features/group/nested.feature",
            "notes.md",
        ]:
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Feature: x\n")

        data = {"behaviorSpecs": {"paths": patterns}}
        globbed = {
            p.relative_to(tmp_path).as_posix()
            for p in runtime.behavior_feature_files(data, tmp_path)
        }
        predicated = {
            rel
            for rel in [
                "top.feature",
                "apps/a.feature",
                "apps/nested/b.feature",
                "features/c.feature",
                "features/deep/d.feature",
                ".features/hidden.feature",
                "features/group/nested.feature",
                "notes.md",
            ]
            if runtime.behavior_feature_path_selected(data, rel)
        }
        assert predicated == globbed, (
            f"scope drift for {patterns}: predicate={predicated} glob={globbed}"
        )


class TestPolicyDocumentsTheForm:
    def test_policy_15_shows_the_machine_checkable_form(self):
        """RCA clause (b): policy said metadata was required but never showed the form."""
        policy = (REPO_ROOT / "methodology" / "policy" / "15-tdd-and-behavior-specs.md").read_text()
        assert "@unpend:" in policy, (
            "policy 15 must show the machine-checkable form, not just require metadata"
        )
        assert "@owner:" in policy
        # The bullet requires owner, REASON and un-pend trigger; a form that showed only two of
        # the three would let an author follow it and still miss the written rule.
        assert "@reason:" in policy


class TestCallSitesStillParse:
    def test_cli_module_parses(self):
        ast.parse(CLI_PATH.read_text())
