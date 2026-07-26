"""PM-surface classifier: the single fail-closed decision point.

`changed_paths_are_pm_surfaces_only(paths, adapter)` is pure and fail-closed: it returns True
ONLY for a non-empty changeset in which every path matches a declared productDevelopment.surfaces
glob AND no path is in the STATIC hard-exclusion set (code, methodology, framework docs, release
artifacts, adapter/config files, every repo-root file). The hard-exclusion is authoritative even
against a broad adapter glob, and callers extract diff paths with rename detection DISABLED so a
code->PM-surface rename always carries its old code path into the changeset.
"""


def _adapter(surfaces):
    return {"productDevelopment": {"surfaces": list(surfaces)}}


BROAD = _adapter(["**"])  # a hypothetical broad glob the loader would reject; the classifier
# does not re-validate surfaces, so this proves the hard-exclusion beats even a broad glob.


def test_true_for_surfaces_only(cli):
    adapter = _adapter(["docs/product/**"])
    assert cli.changed_paths_are_pm_surfaces_only(
        ["docs/product/backlog.md", "docs/product/plans/q3.md"], adapter
    ) is True


def test_false_for_empty(cli):
    # Empty changeset -> never a PM exemption (fail closed).
    assert cli.changed_paths_are_pm_surfaces_only([], _adapter(["docs/product/**"])) is False


def test_false_for_path_outside_globs(cli):
    # Not hard-excluded, but not under any declared surface -> False.
    assert cli.changed_paths_are_pm_surfaces_only(
        ["docs/other/notes.md"], _adapter(["docs/product/**"])
    ) is False


def test_false_when_no_surfaces_declared(cli):
    # Opt-in: with no surfaces, nothing matches -> False even for a product path.
    assert cli.changed_paths_are_pm_surfaces_only(["docs/product/x.md"], _adapter([])) is False
    assert cli.changed_paths_are_pm_surfaces_only(["docs/product/x.md"], {}) is False


HARD_EXCLUDED_CASES = [
    # code / framework roots
    "bin/tautline",
    "src/tautline_methodology/adapter.py",
    "tests/test_pm_surface_classifier.py",
    "scripts/test.sh",
    "methodology/canonical-rules.md",
    "plugins/tautline-core/.claude-plugin/plugin.json",
    ".github/workflows/ci.yml",
    # framework doc roots (everything under docs/ EXCEPT docs/product/)
    "docs/superpowers/plans/2026-07-17-pm-surface-classifier-version.md",
    "docs/releases/0.10.7.md",
    "docs/backlog/item.md",
    "docs/governance/policy.md",
    "docs/productization/plan.md",
    "docs/reference/guide.md",
    "docs/assets/logo.png",
    # hidden marketplace/plugin release artifacts
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    # current + legacy adapter/config files
    ".tautline/adapter.json",
    ".tautline.json",
    "adapters/projects/example-saas.json",
    ".minervit/adapter.json",
    ".minervit-ai-delivery.json",
    # repo-root framework/config files (explicit + generic no-slash)
    "pyproject.toml",
    "CHANGELOG.md",
    "README.md",
    "requirements-dev.txt",
    "VERSION",
    "LICENSE",
    ".gitignore",
]


def test_hard_exclusion_beats_broad_glob(cli):
    for path in HARD_EXCLUDED_CASES:
        assert cli.changed_paths_are_pm_surfaces_only([path], BROAD) is False, path


def test_every_release_artifact_is_hard_excluded(cli):
    for rel in cli.RELEASE_ARTIFACT_PATHS:
        assert cli.changed_paths_are_pm_surfaces_only([rel], BROAD) is False, rel


def test_mixed_diff_with_one_excluded_path_is_false(cli):
    adapter = _adapter(["docs/product/**"])
    assert cli.changed_paths_are_pm_surfaces_only(
        ["docs/product/ok.md", "bin/tautline"], adapter
    ) is False


def test_rename_carries_code_path(cli):
    adapter = _adapter(["docs/product/**"])
    # A --no-renames extraction of a rename surfaces delete(old)+add(new). A code->PM rename
    # carries the old code path; the reverse carries the new code path. Both trip hard-exclusion.
    assert cli.changed_paths_are_pm_surfaces_only(
        ["src/tautline_methodology/util.py", "docs/product/util.md"], adapter
    ) is False
    assert cli.changed_paths_are_pm_surfaces_only(
        ["docs/product/util.md", "src/tautline_methodology/util.py"], adapter
    ) is False


def test_docs_product_is_not_hard_excluded(cli):
    # docs/product/ is the allowlisted surface root -> NOT hard-excluded (so it can be a surface).
    assert cli.changed_paths_are_pm_surfaces_only(
        ["docs/product/roadmap.md"], _adapter(["docs/product/**"])
    ) is True


def test_hard_exclusion_constants_are_immutable_types(cli):
    # Kept out of the policy-phrases SSOT: tuple/frozenset, never UPPER_CASE = [str, ...].
    assert isinstance(cli.HARD_EXCLUDED_ROOTS, tuple)
    assert isinstance(cli.HARD_EXCLUDED_FILES, frozenset)
    assert isinstance(cli.HARD_EXCLUSION_SENTINELS, tuple)
