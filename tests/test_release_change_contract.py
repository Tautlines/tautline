import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _rev_exists(ref: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    ).returncode == 0


def _evidence_only(path: str) -> bool:
    return path.startswith("docs/backlog/session-journals/") or path.startswith(
        "docs/backlog/methodology-regressions/"
    )


def _project_adapter_config_only(path: str) -> bool:
    path_obj = Path(path)
    return (
        len(path_obj.parts) == 3
        and path_obj.parts[0] == "adapters"
        and path_obj.parts[1] == "projects"
        and path_obj.suffix == ".json"
        and not path_obj.name.startswith(".")
    )


# Dependabot npm bumps rewrite the manifest range alongside the lockfile, so
# package.json is deliberately in the set; renderer-kit bot PRs stay reviewable
# (no auto-merge) but must not demand a framework release (METH-FU-VERSION-
# GATE-LOCKFILE-EXEMPTION). pip/github-actions pin bumps remain non-exempt.
_RENDERER_KIT_DEPENDENCY_PIN_NAMES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "package.json",
    }
)


def _renderer_kit_dependency_pin(path: str) -> bool:
    # parts[-2], not `in parts[:-1]`: the exemption covers exactly the files a
    # Dependabot bump edits -- pins at the kit ROOT. A pin-named file nested
    # deeper under the kit still demands the bump.
    path_obj = Path(path)
    parts = path_obj.parts
    return (
        len(parts) >= 3
        and parts[0] == "plugins"
        and parts[-2] == "renderer-kit"
        and path_obj.name in _RENDERER_KIT_DEPENDENCY_PIN_NAMES
    )


# The public release export refuses to ship anything under docs/superpowers/ -- see
# PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES. Plans, specs, and the tracked implementation-review
# ledgers are internal working artifacts that no adopter ever receives, and a diff that ships
# NOTHING cannot owe a release.
#
# Charging one produced a gate-vs-gate deadlock, observed live on PR #449: review-evidence-check
# REFUSES the push until the tracked .impl-reviews/ ledger is committed, and this contract then
# counted that same commit as a framework change requiring a full version bump. One gate demanded
# the file; the other charged a release for it, and the only exits were burning a version number
# on a planning document or a --no-verify break-glass. Same shape as the test-evidence/ledger
# deadlock 0.38.0 fixed, in a different pair of gates.
#
# The rationale is PINNED, not asserted: test_superpowers_docs_are_export_excluded reads the real
# export constant, so if these files ever start shipping, the exemption fails loudly and must be
# re-argued rather than silently covering public surface.
#
# NOT a contradiction of HARD_EXCLUDED_ROOTS, which also lists docs/superpowers. That set answers
# a DIFFERENT question -- "may a declared adapter glob classify this as a product-management
# surface?" -- and exists so a broad `docs/**` glob cannot launder framework code through the
# whole-diff PM exemption. It never claimed these paths must owe a release.
# `release_change_pm_surface_exempt` says so directly: the PM rule is OR'd ADDITIVELY beside these
# per-path rules, never a replacement for them. docs/backlog is the precedent and carries all
# three properties at once -- export-excluded, hard-excluded from the PM classifier, and already
# partly bump-exempt via _evidence_only. This rule has the same shape.
#
# The root is deliberately the whole tree, runbooks included, rather than plans|specs: the
# property being relied on is "the export refuses this prefix", which holds for every child. A
# narrower literal would drift from the constant it claims to track.
_UNSHIPPED_INTERNAL_DOC_ROOT = "docs/superpowers/"


def _unshipped_internal_doc(path: str) -> bool:
    return path.startswith(_UNSHIPPED_INTERNAL_DOC_ROOT)


def _version_bump_exempt(path: str) -> bool:
    return (
        _evidence_only(path)
        or _unshipped_internal_doc(path)
        or _project_adapter_config_only(path)
        or _renderer_kit_dependency_pin(path)
    )


def _changed_paths_against_base(base: str) -> set[str]:
    changed = set(filter(None, _git("diff", "--name-only", f"{base}...HEAD").splitlines()))
    for args in (
        ("diff", "--name-only", "HEAD"),
        ("diff", "--cached", "--name-only", "HEAD"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        changed.update(filter(None, _git(*args).splitlines()))
    return changed


def _release_contract_base_ref() -> str | None:
    explicit = os.environ.get("MINERVIT_VALIDATE_BASE_REF", "").strip()
    if explicit:
        if _rev_exists(explicit):
            return explicit
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            pytest.fail(f"CI cannot validate VERSION bump enforcement: {explicit!r} is not available")
        return None
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base:
        candidate = f"origin/{github_base}"
        if _rev_exists(candidate):
            return candidate
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            pytest.fail(f"CI cannot validate VERSION bump enforcement: {candidate!r} is not available")
    if _rev_exists("origin/main"):
        return "origin/main"
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        pytest.fail("CI cannot validate VERSION bump enforcement: no base ref found")
    return None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("adapters/projects/example-saas.json", True),
        ("adapters/projects/.draft.json", False),
        ("adapters/projects/nested/example.json", False),
        ("adapters/templates/example.json", False),
        ("methodology/adapter-schema.json", False),
        ("docs/backlog/session-journals/2026-07-04.md", True),
        ("docs/backlog/methodology-regressions/rca.md", True),
        ("docs/backlog/methodology-backlog.md", False),
        # Internal working artifacts the public export never ships: a plan, its spec, and the
        # tracked implementation-review ledger review-evidence-check demands before a push.
        ("docs/superpowers/plans/2026-07-22-painless-launch-default.md", True),
        ("docs/superpowers/specs/2026-07-22-painless-launch-default-design.md", True),
        ("docs/superpowers/plans/.impl-reviews/docs-painless-launch-default.json", True),
        # Guard rails: the exemption is exactly the export-excluded root, nothing adjacent.
        # docs/product/ and docs/releases/ both SHIP, so they keep owing a bump here -- a
        # PM-surfaces-only diff is exempted separately, as a whole-diff rule, by
        # release_change_pm_surface_exempt.
        ("docs/product/positioning.md", False),
        ("docs/releases/migrations/0.38.1.json", False),
        ("docs/superpowers-extra/plan.md", False),
        # Renderer-kit dependency pins (Dependabot npm bumps): manifest + lockfile
        # both travel in a bot PR, so both are exempt inside a renderer-kit dir.
        ("plugins/tautline-ops/skills/iteration-review/renderer-kit/package-lock.json", True),
        ("plugins/tautline-ops/skills/iteration-review/renderer-kit/package.json", True),
        ("plugins/tautline-ops/skills/iteration-review/renderer-kit/yarn.lock", True),
        # Guard rails: the exemption is scoped to dependency-pin files under a
        # renderer-kit directory inside plugins/ — nothing wider.
        ("package-lock.json", False),
        (
            "plugins/tautline-ops/skills/iteration-review/renderer-kit/src/IterationReview.tsx",
            False,
        ),
        ("plugins/tautline-ops/skills/iteration-review/package-lock.json", False),
    ],
)
def test_version_bump_exemption_classification(path: str, expected: bool):
    assert _version_bump_exempt(path) is expected


def test_superpowers_docs_are_export_excluded(cli):
    """The docs/superpowers/ exemption rests ENTIRELY on those files never reaching an adopter.

    Keyed to the real export constant rather than a copy of it: if the public export ever starts
    shipping plans, specs, or review ledgers, this fails and the exemption has to be re-argued --
    instead of silently growing into a hole over consumer-visible surface.
    """
    assert _UNSHIPPED_INTERNAL_DOC_ROOT in cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES


def test_planning_artifact_plus_framework_change_still_requires_bump():
    """Per-path, like every other rule here: a plan riding along with real code still owes a
    release. The deadlock this exemption breaks is a docs-ONLY push, not a discount on shipped
    behavior that happens to carry a plan update."""
    changed = {
        "docs/superpowers/plans/2026-07-22-painless-launch-default.md",
        "src/tautline_methodology/cli.py",
    }
    framework_changes = sorted(p for p in changed if p and not _version_bump_exempt(p))
    assert framework_changes == ["src/tautline_methodology/cli.py"]


def test_lockfile_plus_framework_change_still_requires_bump():
    changed = {
        "plugins/tautline-ops/skills/iteration-review/renderer-kit/package-lock.json",
        "bin/tautline",
    }
    framework_changes = sorted(p for p in changed if p and not _version_bump_exempt(p))
    assert framework_changes == ["bin/tautline"]


def test_release_contract_base_ref_prefers_explicit_env(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/experimental")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/experimental")

    assert _release_contract_base_ref() == "origin/experimental"


def test_release_contract_base_ref_fails_ci_when_explicit_base_is_missing(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/missing")
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    with pytest.raises(pytest.fail.Exception, match="origin/missing"):
        _release_contract_base_ref()


def test_release_contract_base_ref_does_not_fallback_when_explicit_base_is_missing_locally(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/missing")
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    assert _release_contract_base_ref() is None


def test_release_contract_base_ref_uses_github_base_when_available(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/experimental")

    assert _release_contract_base_ref() == "origin/experimental"


def test_release_contract_base_ref_fails_ci_when_github_base_is_missing(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(module, "_rev_exists", lambda _ref: False)

    with pytest.raises(pytest.fail.Exception, match="origin/experimental"):
        _release_contract_base_ref()


def test_release_contract_base_ref_falls_back_to_main_for_local_checkouts(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    assert _release_contract_base_ref() == "origin/main"


def test_python_ci_fetches_base_ref_for_release_change_contract():
    workflow = (ROOT / ".github" / "workflows" / "ci-python.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow


# Item 48 / no-dead-ends. This gate is RIGHT and its message used to be a dead end: it listed the
# changed files and named no way to satisfy it. That is not a theoretical complaint -- every
# dependabot PR touching `.github/workflows/*.yml` lands here (PR #413, `actions/checkout` 4->7),
# because a bot cannot bump `VERSION`, and so it is red on arrival, permanently. A gate with no
# compliant path is how a team learns to ignore red.
#
# The exemption is deliberately NOT widened to workflow paths: `ci-python.yml` ships inside the
# public release export, so a pinned-action change in it is consumer-visible and genuinely is a
# release. The gate stays; the message now names the maintainer commit that clears it.
_VERSION_BUMP_REMEDY = """How to satisfy this gate (any one of these; no operator decision is needed):

1. Bump the release. Pick the next version, then, from the repo root:
     printf '%s\\n' 0.0.0 > VERSION            # substitute the real next version
     # add the matching section at the top of CHANGELOG.md
     tautline release-migration-report --version "$(cat VERSION)" --write
   Then stage all three explicitly -- the migration report is a NEW file, so `git commit -a`
   would silently leave it untracked and the release checks would stay red:
     git add VERSION CHANGELOG.md "docs/releases/migrations/$(cat VERSION).json"
     git commit -m 'chore(release): bump VERSION'

2. If this is a DEPENDABOT (or other bot) PR, the bot cannot do step 1 and must not be expected to.
   A maintainer pushes one commit onto the bot's branch carrying exactly the step-1 artifacts:
     gh pr checkout <number>
     # apply step 1 above, including the explicit `git add`, then
     git push

3. If the diff really is not consumer-visible, make it exempt at the source rather than here:
   add the path to `_version_bump_exempt`, or keep the diff to PM surfaces only (see
   `release_change_pm_surface_exempt`). Do NOT exempt `.github/workflows/*.yml` wholesale --
   those files ship in the public release export."""


def test_framework_changes_require_version_bump_when_base_ref_is_available(cli):
    base = _release_contract_base_ref()
    if base is None:
        pytest.skip("no base ref available for local VERSION bump enforcement")

    changed = _changed_paths_against_base(base)
    framework_changes = sorted(path for path in changed if path and not _version_bump_exempt(path))
    version_changed = "VERSION" in changed
    # ADDITIVE (Design 4): beyond the per-path `_version_bump_exempt` rules, a whole diff that is
    # PM-surfaces-only is also VERSION-bump-exempt. The predicate lives in bin/tautline (single
    # source); it re-extracts the outgoing diff with `--no-renames` and fails closed.
    pm_surface_exempt = cli.release_change_pm_surface_exempt(base, ROOT)

    assert not framework_changes or version_changed or pm_surface_exempt, (
        "framework changes require VERSION bump; changed files:\n"
        + "\n".join(f"- {path}" for path in framework_changes)
        + "\n\n"
        + _VERSION_BUMP_REMEDY
    )


# --- PM-surface-only diffs are VERSION-bump-exempt (T4, Design 4) --------------------------------


def _init_temp_repo(repo: Path) -> None:
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "Test"),
        ("config", "commit.gpgsign", "false"),
    ):
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _write(repo: Path, rel: str, content: str = "x\n") -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _write_real_adapter(repo: Path, surfaces: list[str]) -> None:
    """Copy the REAL committed self-adapter into `repo` with declared PM surfaces, so the helper's
    load_project()/normalize_product_development() path validates a genuine adapter, not a mock."""
    data = json.loads((ROOT / ".tautline" / "adapter.json").read_text(encoding="utf-8"))
    data["productDevelopment"] = {"surfaces": list(surfaces)}
    dest = repo / ".tautline" / "adapter.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_pm_surface_only_diff_is_bump_exempt(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    _write(repo, "docs/product/keep.md", "seed\n")
    base = _commit_all(repo, "base")
    _write(repo, "docs/product/backlog.md")
    _write(repo, "docs/product/plans/q3.md")
    _commit_all(repo, "pm work")
    assert cli.release_change_pm_surface_exempt(base, repo) is True


def test_code_diff_still_demands_bump(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    _write(repo, "docs/product/keep.md", "seed\n")
    base = _commit_all(repo, "base")
    _write(repo, "docs/product/backlog.md")
    _write(repo, "src/tautline_methodology/util.py", "code\n")
    _commit_all(repo, "mixed")
    # A mixed diff carrying a hard-excluded code path is NOT PM-surface-exempt -> bump required.
    assert cli.release_change_pm_surface_exempt(base, repo) is False


def test_deterministically_empty_changeset_is_no_framework_change(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    base = _commit_all(repo, "base")
    # Extraction SUCCEEDED with zero changed paths: a deterministically-empty set (not None).
    assert cli.release_change_changed_paths(base, repo) == set()
    # No PM exemption for an empty changeset, and the classifier agrees the empty set is False.
    assert cli.release_change_pm_surface_exempt(base, repo) is False
    empty_adapter = {"productDevelopment": {"surfaces": ["docs/product/**"]}}
    assert cli.changed_paths_are_pm_surfaces_only([], empty_adapter) is False


def test_undeterminable_diff_fails_closed(cli, tmp_path):
    # target is NOT a git worktree -> every git command is `unavailable`; extraction is
    # UNDETERMINABLE (None), NOT an empty set, and the exemption fails closed (bump required).
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    assert cli.release_change_changed_paths("origin/main", not_a_repo) is None
    assert cli.release_change_pm_surface_exempt("origin/main", not_a_repo) is False


def test_pure_project_adapter_config_diff_stays_exempt_via_existing_rule(cli, tmp_path):
    # Additivity proof: a pure adapters/projects/<name>.json diff keeps its PRE-EXISTING per-path
    # exemption; it is NOT exempt via the PM-surface branch (that path is hard-excluded).
    assert _version_bump_exempt("adapters/projects/example-saas.json") is True
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    _write(repo, "adapters/projects/example-saas.json", "{}\n")
    base = _commit_all(repo, "base")
    _write(repo, "adapters/projects/example-saas.json", '{"changed": true}\n')
    _commit_all(repo, "adapter tweak")
    assert cli.release_change_pm_surface_exempt(base, repo) is False


def test_no_renames_rename_of_code_into_pm_surface_demands_bump(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    _write(repo, "src/tautline_methodology/util.py", "code\n")
    base = _commit_all(repo, "base")
    (repo / "docs" / "product").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "mv", "src/tautline_methodology/util.py", "docs/product/util.md"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    _commit_all(repo, "rename code into pm surface")
    # `--no-renames` surfaces delete(src/...py)+add(docs/product/util.md); the old code path trips
    # the hard-exclusion, so a code->PM rename is never laundered into an exemption.
    paths = cli.release_change_changed_paths(base, repo)
    assert "src/tautline_methodology/util.py" in paths
    assert cli.release_change_pm_surface_exempt(base, repo) is False


def test_release_contract_exempts_pm_surface_with_real_adapter(cli, tmp_path):
    """End-to-end with a REAL adapter (loaded via load_project) declaring docs/product/** surfaces:
    a whole-diff of only docs/product/** is exempt; a code/framework-doc diff still needs a bump."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_repo(repo)
    _write_real_adapter(repo, ["docs/product/**"])
    _write(repo, "docs/product/keep.md", "seed\n")
    base = _commit_all(repo, "base")

    # Product-doc-only diff -> exempt.
    _write(repo, "docs/product/roadmap.md")
    pm_head = _commit_all(repo, "product docs")
    assert cli.release_change_pm_surface_exempt(base, repo) is True

    # A framework-doc change from the same base -> NOT exempt.
    subprocess.run(
        ["git", "-C", str(repo), "reset", "-q", "--hard", base],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    _write(repo, "docs/superpowers/plans/plan.md")
    _commit_all(repo, "framework doc")
    assert cli.release_change_pm_surface_exempt(base, repo) is False
    assert pm_head  # silence unused
