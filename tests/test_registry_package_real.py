"""Task 1: `registry-package --registry pypi` builds the REAL package, not a pointer.

The pypi payload is a thin wrapper package plus the full committed tree embedded as
package data under `src/tautline/_dist/`, stamped with a build-time
`.snapshot-meta.json` (schema tautline-snapshot/v1). npm keeps its 3-file
namespace-pointer SHAPE (its copy changes ride Task 3, so nothing here asserts
byte-level npm copy content).

Everything runs against a hermetic git-fixture repo (precedent:
`_make_methodology_fixture` in tests/test_sync_methodology_cli.py), never the live
checkout: the CLI resolves REPO_ROOT from its own file location, so the copied
`bin/tautline` inside the fixture packages the fixture tree.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"

# The runtime-read set the goal promises, including dotfiles -- the exact canaries the
# CI fresh-install smoke (Task 5) later checks in site-packages.
EMBEDDED_FILE_CANARIES = (
    "VERSION",
    "bin/tautline",
    ".snapshot-meta.json",
    ".claude-plugin/marketplace.json",
    "plugins/tautline-core/.codex-plugin/plugin.json",
    "methodology/canonical-rules.md",
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _hermetic_env(home: Path) -> dict[str, str]:
    """The operator's live config must never leak into fixture runs (and vice versa)."""
    home.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_REPO": "",
        "TAUTLINE_METHODOLOGY_REPO": "",
        "MINERVIT_METHODOLOGY_CANONICAL_REPO": "",
        "TAUTLINE_METHODOLOGY_CANONICAL_REPO": "",
        "MINERVIT_METHODOLOGY_SNAPSHOT_STORE": "",
        "TAUTLINE_METHODOLOGY_SNAPSHOT_STORE": "",
    }


def _planted_excluded_paths(excluded_prefixes: tuple[str, ...]) -> list[str]:
    """One committed file per excluded prefix, so exclusion can never pass vacuously."""
    return [
        f"{prefix}private-fixture.txt" if prefix.endswith("/") else prefix
        for prefix in excluded_prefixes
    ]


def _make_package_fixture(
    repo: Path, excluded_prefixes: tuple[str, ...], *, git: bool = True
) -> Path:
    """A minimal methodology tree carrying the runtime-read set plus private-only content."""
    (repo / "bin").mkdir(parents=True)
    shutil.copy2(CLI_PATH, repo / "bin" / "tautline")
    (repo / "bin" / "tautline").chmod(0o755)
    shutil.copy2(REPO_ROOT / "VERSION", repo / "VERSION")
    for manifest_src, manifest_rel in (
        (PLUGIN_MANIFEST, "plugins/tautline-core/.codex-plugin/plugin.json"),
        (MARKETPLACE_MANIFEST, ".claude-plugin/marketplace.json"),
    ):
        dest = repo / manifest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_src, dest)
    canonical = repo / "methodology" / "canonical-rules.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# Canonical rules (fixture)\n", encoding="utf-8")
    migrations = repo / "docs" / "releases" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "0.0.0.json").write_text("{}\n", encoding="utf-8")
    src_dest = repo / "src" / "minervit_methodology"
    src_dest.mkdir(parents=True)
    for path in (REPO_ROOT / "src" / "minervit_methodology").glob("*.py"):
        shutil.copy2(path, src_dest / path.name)
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for rel in _planted_excluded_paths(excluded_prefixes):
        planted = repo / rel
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text("private fixture content that must never ship\n", encoding="utf-8")
    if git:
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "validate@example.invalid")
        _git(repo, "config", "user.name", "validate")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "package fixture")
    return repo


def _run_registry_package(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "bin" / "tautline"), "registry-package", *args],
        cwd=repo,
        env=_hermetic_env(repo.parent / "pkg-home"),
        text=True,
        capture_output=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def pypi_payload(cli, tmp_path_factory):
    """One materialized pypi payload shared by the read-only payload assertions."""
    tmp = tmp_path_factory.mktemp("registry-package-real")
    repo = _make_package_fixture(
        tmp / "fixture-repo", cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES
    )
    dest = tmp / "pkg"
    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    proc = _run_registry_package(
        repo,
        "--registry",
        "pypi",
        "--version",
        version,
        "--channel",
        "experimental",
        "--destination",
        str(dest),
        "--write",
    )
    return SimpleNamespace(
        repo=repo,
        dest=dest,
        dist=dest / "src" / "tautline" / "_dist",
        proc=proc,
        version=version,
        head=_git(repo, "rev-parse", "HEAD"),
    )


def _require_built(payload) -> None:
    assert payload.proc.returncode == 0, (
        "registry-package --registry pypi --write failed:\n"
        f"stdout:\n{payload.proc.stdout}\nstderr:\n{payload.proc.stderr}"
    )


def test_pypi_payload_embeds_the_full_tree_with_dotfiles(pypi_payload) -> None:
    _require_built(pypi_payload)
    for rel in EMBEDDED_FILE_CANARIES:
        assert (pypi_payload.dist / rel).is_file(), f"embedded tree is missing {rel}"
    migrations = pypi_payload.dist / "docs" / "releases" / "migrations"
    assert migrations.is_dir(), "embedded tree is missing docs/releases/migrations/"
    assert any(migrations.iterdir()), "docs/releases/migrations/ shipped empty"


def test_pypi_payload_excludes_private_export_prefixes(cli, pypi_payload) -> None:
    _require_built(pypi_payload)
    planted = _planted_excluded_paths(cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES)
    tracked = set(_git(pypi_payload.repo, "ls-files").splitlines())
    for rel in planted:  # the fixture really committed private content under every prefix
        assert rel in tracked, f"fixture failed to commit {rel}; exclusion would pass vacuously"
    dist_files = [
        p.relative_to(pypi_payload.dist).as_posix()
        for p in pypi_payload.dist.rglob("*")
        if p.is_file()
    ]
    for prefix in cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES:
        offenders = [rel for rel in dist_files if rel == prefix or rel.startswith(prefix)]
        assert not offenders, f"private prefix {prefix!r} leaked into _dist/: {offenders}"


def test_pypi_payload_manifest_stamps_commit_version_channel_and_install_kind(
    cli, pypi_payload
) -> None:
    _require_built(pypi_payload)
    manifest = json.loads(
        (pypi_payload.dist / ".snapshot-meta.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "tautline-snapshot/v1"
    assert manifest["schema"] == cli.SNAPSHOT_MANIFEST_SCHEMA
    assert manifest["commit"] == pypi_payload.head
    assert manifest["shortCommit"] == pypi_payload.head[:12]
    assert manifest["version"] == pypi_payload.version
    assert manifest["channel"] == "experimental"
    assert manifest["installKind"] == "package"
    assert manifest.get("materializedAt"), "manifest must record when it was stamped"


def test_pypi_payload_manifest_carries_no_machine_path(pypi_payload) -> None:
    _require_built(pypi_payload)
    manifest = json.loads(
        (pypi_payload.dist / ".snapshot-meta.json").read_text(encoding="utf-8")
    )
    # canonical_methodology_repo() treats a manifest canonicalRepo as a resolution
    # candidate; a baked build path must never win canonical resolution.
    assert "canonicalRepo" not in manifest

    def _strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for inner in value.values():
                yield from _strings(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from _strings(inner)

    absolute = [text for text in _strings(manifest) if os.path.isabs(text)]
    assert not absolute, f"manifest bakes machine paths: {absolute}"


def test_pypi_payload_pyproject_declares_both_console_scripts(pypi_payload) -> None:
    _require_built(pypi_payload)
    pyproject = (pypi_payload.dest / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in pyproject
    assert 'tautline = "tautline:main"' in pyproject
    # The legacy name is load-bearing: plugin hooks and older rendered adapters invoke it.
    assert 'minervit-methodology = "tautline:main"' in pyproject
    assert 'requires-python = ">=3.10"' in pyproject
    assert 'build-backend = "hatchling.build"' in pyproject
    assert '"hatchling"' in pyproject
    # python -m build builds the wheel FROM the sdist: a dotfile missing from the sdist
    # silently vanishes from the wheel, so BOTH targets need explicit inclusion.
    assert "[tool.hatch.build.targets.sdist.force-include]" in pyproject
    assert "[tool.hatch.build.targets.wheel.force-include]" in pyproject
    assert '"src/tautline/_dist"' in pyproject


def test_pypi_payload_pyproject_makes_force_include_the_only_dist_owner(pypi_payload) -> None:
    """Default selection must EXCLUDE `_dist` so force-include is its single owner.

    hatchling's default selection (`packages` / `include`) also matches
    `src/tautline/_dist`, and the wheel archive refuses duplicate paths -- the CI
    fresh-install smoke (Task 5) caught `python -m build` dying with "A second file
    is being added to the wheel archive at the same path: tautline/_dist/.coveragerc".
    Excluding `_dist` from default selection in BOTH targets leaves force-include
    (which ignore rules cannot filter) as the one deterministic inclusion path.
    """
    _require_built(pypi_payload)
    pyproject = (pypi_payload.dest / "pyproject.toml").read_text(encoding="utf-8")
    sdist_start = pyproject.index("[tool.hatch.build.targets.sdist]")
    wheel_start = pyproject.index("[tool.hatch.build.targets.wheel]")
    sections = {
        "sdist": pyproject[sdist_start:wheel_start],
        "wheel": pyproject[wheel_start:],
    }
    for name, section in sections.items():
        assert 'exclude = ["src/tautline/_dist"]' in section, (
            f"the {name} target must exclude src/tautline/_dist from default "
            "selection; default selection + force-include double-adds the tree and "
            "the wheel build refuses the duplicate paths"
        )
        assert section.index('exclude = ["src/tautline/_dist"]') < section.index(
            "force-include"
        ), f"the {name} exclude belongs to the target table, not the force-include table"


def test_pypi_payload_wrapper_runs_the_embedded_cli(pypi_payload) -> None:
    _require_built(pypi_payload)
    env = _hermetic_env(pypi_payload.dest.parent / "wrapper-home")
    env["PYTHONPATH"] = str(pypi_payload.dest / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.argv=['tautline','version']; import tautline; tautline.main()",
        ],
        cwd=pypi_payload.dest.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"wrapper run failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # running_methodology_commit() prefers the manifest over git, so the wrapper proves
    # both the runpy wiring and the manifest reading in one subprocess -- no wheel build.
    assert pypi_payload.head in proc.stdout


def test_npm_payload_is_still_the_pointer(cli, tmp_path) -> None:
    """npm keeps the POINTER SHAPE: 3 small text files, no bin, no _dist, no wheel machinery.

    Shape assertions only, deliberately NOT byte-identity: Task 3 rewrites the npm
    README/description copy, and byte-level copy content belongs to Task 3's suite.
    """
    files = cli.registry_package_files("npm", "0.9.7")
    assert sorted(files) == ["LICENSE", "README.md", "package.json"]
    manifest = json.loads(files["package.json"])
    assert "bin" not in manifest, "the npm pointer must not grow an executable"
    dest = tmp_path / "npm-pkg"
    args = cli.argparse.Namespace(
        registry="npm", version="0.9.7", destination=dest, write=True
    )
    assert cli.registry_package(args) == 0
    written = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert written == ["LICENSE", "README.md", "package.json"]
    assert not (dest / "src").exists(), "npm must not embed the _dist payload"
    assert not (dest / "pyproject.toml").exists(), "npm must not grow wheel machinery"


def test_registry_package_refuses_a_version_that_disagrees_with_head(
    pypi_payload, tmp_path
) -> None:
    dest = tmp_path / "pkg-wrong-version"
    proc = _run_registry_package(
        pypi_payload.repo,
        "--registry",
        "pypi",
        "--version",
        "9.9.9",
        "--channel",
        "stable",
        "--destination",
        str(dest),
        "--write",
    )
    assert proc.returncode != 0
    assert "9.9.9" in proc.stderr
    assert "VERSION" in proc.stderr, f"refusal must name the real cause: {proc.stderr}"
    assert not dest.exists(), "a refused build must export nothing"


def test_registry_package_refuses_without_a_git_checkout(cli, tmp_path) -> None:
    repo = _make_package_fixture(
        tmp_path / "no-git-tree", cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES, git=False
    )
    dest = tmp_path / "pkg-no-git"
    proc = _run_registry_package(
        repo,
        "--registry",
        "pypi",
        "--version",
        (repo / "VERSION").read_text(encoding="utf-8").strip(),
        "--channel",
        "stable",
        "--destination",
        str(dest),
        "--write",
    )
    assert proc.returncode != 0
    assert "checkout" in proc.stderr, f"refusal must name the real cause: {proc.stderr}"
    assert not dest.exists(), "a refused build must export nothing"


def test_registry_package_clears_stale_dist_on_destination_reuse(cli, tmp_path) -> None:
    """Codex R1 P2 (this branch's implementation review): a reused --destination must
    never ship stale embedded files. The export overlays `git archive` output, so a
    file deleted from (or newly excluded by) the committed tree would survive from an
    earlier build under `_dist/` — and force-include ships the WHOLE directory into
    the wheel. The export must be the tree's single owner and start from empty."""
    repo = _make_package_fixture(
        tmp_path / "fixture-repo", cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES
    )
    dest = tmp_path / "pkg"
    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    args = (
        "--registry",
        "pypi",
        "--version",
        version,
        "--channel",
        "experimental",
        "--destination",
        str(dest),
        "--write",
    )
    first = _run_registry_package(repo, *args)
    assert first.returncode == 0, f"first build failed:\n{first.stdout}\n{first.stderr}"
    stale = dest / "src" / "tautline" / "_dist" / "docs" / "stale-deleted-file.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("left over from an earlier build; must not ship\n", encoding="utf-8")
    second = _run_registry_package(repo, *args)
    assert second.returncode == 0, f"rebuild failed:\n{second.stdout}\n{second.stderr}"
    assert not stale.exists(), (
        "a reused destination must not carry stale _dist files into the wheel"
    )
    dist = dest / "src" / "tautline" / "_dist"
    for rel in EMBEDDED_FILE_CANARIES:
        assert (dist / rel).is_file(), f"rebuild lost the embedded canary {rel}"
