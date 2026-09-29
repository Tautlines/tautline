"""Fixture builders for the pre-push adapter-schema skew suite (backlog item 1).

Two builders, because the suite asks two different questions and only one of them is expensive.

``build_resolution_lane`` answers *which CLI did the hook resolve?* Every candidate is a three-line
stub that prints its own path, so a full hook run is a few milliseconds and needs no framework
engine, no ``gh``, and no adapter. Probe ``lane-self-checkout`` only tests for the PRESENCE of
``src/tautline_methodology/cli.py`` and ``methodology/adapter-schema.json``, so placeholder files
are a faithful stand-in -- the probe cannot tell them apart from the real thing, which is exactly
the property under test.

``build_real_skew_lane`` answers *does the refusal actually fire, and does the fix actually clear
it?* That one needs two REAL framework installs whose ``methodology/adapter-schema.json`` differ by
one top-level property, because the refusal it reproduces comes from
``adapter.validate_adapter_schema`` reading whichever schema the resolved CLI carries. The engine
is copied rather than symlinked: ``cli.py`` computes ``REPO_ROOT`` as
``Path(__file__).resolve().parents[2]``, and ``resolve()`` follows symlinks, so a symlinked package
would resolve back to the real checkout and read the real schema -- silently defeating the fixture
while every assertion still passed. Copying 37 files measures ~10ms, which is not worth outsmarting.

Hermetic ``HOME`` is not optional here. ``resolve_minervit_cli`` sources
``$HOME/.config/tautline/tautline.env`` before it probes anything, and on a maintainer's machine
that file exports ``TAUTLINE_METHODOLOGY_REPO``. A test that inherited the real ``HOME`` would be
testing the operator's environment, and would pass or fail depending on whose laptop it ran on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
PACKAGE_ROOT = REPO_ROOT / "src" / "tautline_methodology"
ADAPTER_SCHEMA = REPO_ROOT / "methodology" / "adapter-schema.json"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

# The key the "newer" side of the skew declares and the "older" side does not. Named for what it
# is rather than after any real proposal: control-posture's goLiveReadiness, item 6's archetype and
# shared-environment's environmentPersistence are all the same shape, and none of them should be
# able to make this fixture pass or fail by landing.
SKEW_KEY = "fixtureOnlySkewProbe"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _write_executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def _stub_cli(path: Path) -> Path:
    """A CLI stand-in that reports which one it is and lets every gate pass.

    The hook runs four to five gate steps through ``run_minervit_command``; a stub that exits 0
    lets the whole script run to completion, so the test observes a REAL hook execution rather
    than a parsed fragment of one. ``$0`` is the resolved path, which is the answer under test.
    """
    return _write_executable(
        path,
        "#!/bin/sh\nprintf 'resolved_cli: %s\\n' \"$0\"\nexit 0\n",
    )


def _counting_git(path: Path) -> Path:
    """A ``git`` shim that counts invocations, then behaves like git.

    Used to prove the resolver spawns ``git rev-parse`` once per hook run rather than once per
    gate. Counting by appending a line keeps it concurrency-safe enough for a single hook process
    and needs no locking.
    """
    return _write_executable(
        path,
        "#!/bin/sh\n"
        'printf \'x\\n\' >> "$GIT_STUB_COUNT_FILE"\n'
        'exec "$GIT_STUB_REAL" "$@"\n',
    )


def _real_git() -> str:
    which = shutil.which("git")
    assert which, "git must be on PATH to build the hook-skew fixtures"
    return which


@dataclass
class ResolutionLane:
    """A lane plus every resolution candidate, each one distinguishable by the path it prints."""

    root: Path
    home: Path
    baked_install: Path
    tautline_env_repo: Path
    minervit_env_repo: Path
    minervit_legacy_repo: Path
    path_dir: Path
    git_count_file: Path

    def hook(self, hook_name: str) -> Path:
        return self.root / ".git" / "hooks" / hook_name

    def env(self, **overrides: str) -> dict[str, str]:
        """A hermetic environment. Every name the resolver reads is set here or absent here."""
        base = {
            "HOME": str(self.home),
            "PATH": f"{self.path_dir}:{os.defpath}",
            "GIT_STUB_COUNT_FILE": str(self.git_count_file),
            "GIT_STUB_REAL": _real_git(),
        }
        base.update(overrides)
        return base

    def run_hook(self, hook_name: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.hook(hook_name))],
            cwd=self.root,
            env=self.env(**env_overrides),
            text=True,
            capture_output=True,
            timeout=60,
            input="",
        )

    def git_invocations(self) -> int:
        if not self.git_count_file.exists():
            return 0
        lines = self.git_count_file.read_text(encoding="utf-8").splitlines()
        return len([line for line in lines if line])

    def reset_git_count(self) -> None:
        self.git_count_file.write_text("", encoding="utf-8")


def build_resolution_lane(
    tmp_path: Path, *, framework_shaped: bool = True, engine: bool = True, schema: bool = True
) -> ResolutionLane:
    """Build a git lane and one stub CLI at every place the resolver looks.

    ``framework_shaped`` decides whether the lane itself can win probe ``lane-self-checkout``.
    ``engine`` and ``schema`` split that condition so a test can starve exactly one half and prove
    the probe requires both -- a lane carrying the engine but no schema is not an authority on a
    schema it does not have.
    """
    root = tmp_path / "lane"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("lane\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")

    if framework_shaped:
        if engine:
            engine_file = root / "src" / "tautline_methodology" / "cli.py"
            engine_file.parent.mkdir(parents=True, exist_ok=True)
            engine_file.write_text("# placeholder engine\n", encoding="utf-8")
        if schema:
            schema_file = root / "methodology" / "adapter-schema.json"
            schema_file.parent.mkdir(parents=True, exist_ok=True)
            schema_file.write_text("{}\n", encoding="utf-8")
        _stub_cli(root / "bin" / "tautline")

    baked_install = tmp_path / "baked-install"
    _stub_cli(baked_install / "bin" / "tautline")
    tautline_env_repo = tmp_path / "tautline-env-repo"
    _stub_cli(tautline_env_repo / "bin" / "tautline")
    minervit_env_repo = tmp_path / "minervit-env-repo"
    _stub_cli(minervit_env_repo / "bin" / "tautline")
    minervit_legacy_repo = tmp_path / "minervit-legacy-repo"
    _stub_cli(minervit_legacy_repo / "bin" / "minervit-methodology")

    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True, exist_ok=True)

    path_dir = tmp_path / "path-bin"
    path_dir.mkdir(parents=True, exist_ok=True)
    git_count_file = tmp_path / "git-invocations.txt"
    git_count_file.write_text("", encoding="utf-8")
    _counting_git(path_dir / "git")

    return ResolutionLane(
        root=root,
        home=home,
        baked_install=baked_install,
        tautline_env_repo=tautline_env_repo,
        minervit_env_repo=minervit_env_repo,
        minervit_legacy_repo=minervit_legacy_repo,
        path_dir=path_dir,
        git_count_file=git_count_file,
    )


def install_hooks_with_baked_path(lane_root: Path, baked_install_root: Path) -> None:
    """Write the real hooks into ``lane_root`` with ``baked_install_root`` as the baked path.

    ``git_branch_liveness_hook_content`` bakes ``REPO_ROOT / "bin" / CLI_NAME`` as its first
    statement, so monkeypatching ``REPO_ROOT`` for the duration of the write is how a stale runtime
    path gets baked in real life -- it is whichever checkout last ran ``lane-start``.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    import tautline_methodology.cli as cli_module  # noqa: PLC0415  (import must follow the path insert)

    original = cli_module.REPO_ROOT
    try:
        cli_module.REPO_ROOT = baked_install_root
        installed, errors = cli_module.write_git_branch_liveness_hooks(lane_root)
    finally:
        cli_module.REPO_ROOT = original
    assert not errors, errors
    assert installed, "no hooks were installed"


@dataclass
class RealSkewLane:
    """A framework-shaped lane whose schema declares a key the baked older install refuses."""

    root: Path
    home: Path
    older_install: Path
    path_dir: Path

    @property
    def older_cli(self) -> Path:
        return self.older_install / "bin" / "tautline"

    @property
    def lane_cli(self) -> Path:
        return self.root / "bin" / "tautline"

    @property
    def lane_adapter(self) -> Path:
        return self.root / ".tautline.json"

    def env(self, **overrides: str) -> dict[str, str]:
        base = {"HOME": str(self.home), "PATH": f"{self.path_dir}:{os.defpath}"}
        base.update(overrides)
        return base

    def run_cli(
        self, cli: Path, *args: str, **env_overrides: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(cli), *args],
            cwd=self.root,
            env=self.env(**env_overrides),
            text=True,
            capture_output=True,
            timeout=120,
        )


def _copy_framework_install(destination: Path, *, declares_skew_key: bool) -> Path:
    """Copy a runnable framework install into ``destination``, optionally declaring the extra key.

    A real install, not a sketch. ``cli.py`` reads ``VERSION``, the six plugin manifests, the policy
    modules and the shipped adapters at import and at startup, so a copy of ``bin/`` plus ``src/``
    plus one schema file is not a CLI -- it is a CLI that exits on its first startup check. The set
    below is what actually runs; ``tests/``, ``docs/``, ``.git/`` and ``.venv/`` are excluded
    because nothing on this path reads them and they dominate the copy cost.

    The two installs differ by exactly one top-level property in the adapter schema and by nothing
    else, so any behavioural difference the tests observe is attributable to the schema alone.
    """
    destination.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("bin", "src", "methodology", "plugins", ".claude-plugin", "adapters"):
        shutil.copytree(
            REPO_ROOT / name, destination / name, ignore=ignore, dirs_exist_ok=True
        )
    for name in ("VERSION", "pyproject.toml"):
        source = REPO_ROOT / name
        if source.exists():
            shutil.copy2(source, destination / name)
    (destination / "bin" / "tautline").chmod(0o755)
    (destination / "bin" / "minervit-methodology").chmod(0o755)

    schema_path = destination / "methodology" / "adapter-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if declares_skew_key:
        schema["properties"][SKEW_KEY] = {"type": "object", "additionalProperties": True}
    else:
        schema["properties"].pop(SKEW_KEY, None)
    schema_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def _fake_gh(bin_dir: Path) -> Path:
    """A ``gh`` stand-in that keeps the branch-liveness and board gates out of the way.

    Copied in shape from ``tests/test_branch_liveness_hooks.py``'s fake rather than imported, so
    that file's fixture stays free to change without silently changing this one's meaning. The
    board gates fail closed on unavailability, so the fake must present a properly-scoped token or
    every hook run here blocks on the board gate instead of exercising its own subject.
    """
    return _write_executable(
        bin_dir / "gh",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "pr list")
    printf '%s\\n' '[{"number":901,"title":"Live","url":"https://example.test/pr/901","state":"OPEN","mergedAt":null,"closedAt":null,"headRefName":"feature/skew-key","baseRefName":"main","mergeStateStatus":"CLEAN","autoMergeRequest":null}]'
    ;;
  "repo view")
    printf '{"owner":{"login":"example-org"},"name":"example-saas"}\\n'
    ;;
  "api graphql")
    # Board READS are hand-written GraphQL now (they cost ~100x less than the `gh project`
    # subcommands), so this fake answers them here. Each branch keys on a token unique to one
    # query: only field-list selects ProjectV2IterationField, only item-list selects
    # ProjectV2ItemFieldTextValue, only project view selects shortDescription.
    case "$*" in
      *ProjectV2IterationField*)
        printf '%s%s%s\\n' '{"data":{"repositoryOwner":{"projectV2":{"fields":{"totalCount":1,' \\
          '"nodes":[{"__typename":"ProjectV2SingleSelectField","id":"PVTSSF_1","name":"Status",' \\
          '"options":[{"id":"o1","name":"Ready"},{"id":"o2","name":"In Progress"},' \\
          '{"id":"o3","name":"Done"},{"id":"o4","name":"Blocked"}]}]}}}}}'
        ;;
      *ProjectV2ItemFieldTextValue*)
        printf '%s%s\\n' '{"data":{"repositoryOwner":{"projectV2":{"items":{"totalCount":0,' \\
          '"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
        ;;
      *shortDescription*)
        printf '%s%s\\n' '{"data":{"repositoryOwner":{"projectV2":' \\
          '{"id":"PVT_1","number":1,"title":"Board"}}}}'
        ;;
      *)
        printf '%s%s\\n' '{"data":{"repository":{"pullRequest":' \\
          '{"isInMergeQueue":false,"mergeQueueEntry":null}}}}'
        ;;
    esac
    ;;
  "auth status")
    printf 'Token scopes: gist, read:org, read:project, project, repo, workflow\\n'
    ;;
  "project item-list")
    case "$*" in
      *--help*)
        printf -- 'Usage: gh project item-list\\n  -q, --query string\\n  -L, --limit int\\n'
        ;;
      *) printf '{"items":[]}\\n' ;;
    esac
    ;;
  "project field-list")
    printf '%s%s\\n' '{"fields":[{"name":"Status","type":"ProjectV2SingleSelectField",' \\
      '"options":[{"name":"Ready"},{"name":"In Progress"},{"name":"Done"},{"name":"Blocked"}]}]}'
    ;;
  *)
    printf '{}\\n'
    ;;
esac
""",
    )


def build_real_skew_lane(tmp_path: Path, *, adapter_key: str = SKEW_KEY) -> RealSkewLane:
    """Build the real thing: a framework lane declaring a key its baked older install refuses.

    Two full framework installs that differ by exactly one top-level schema property, a git lane
    that IS the newer one, a rendered adapter that uses the key, and the real hooks installed with
    the older install baked in as ``script_path`` -- which is how a stale runtime path gets there
    in life, since it records whichever checkout last ran ``lane-start``.

    ``adapter_key`` is what makes the same builder serve both halves of the safety argument. The
    default is the key the lane's own schema declares, which is real version skew. Pass a name the
    lane's schema does NOT declare and you get a **typo** instead -- same lane, same probe-1 win,
    same authority, and the refusal must still fire. Authority over your own schema is not
    permission to invent keys, and one builder proving both is better than two that could drift.
    """
    root = tmp_path / "framework-lane"
    _copy_framework_install(root, declares_skew_key=True)
    older = _copy_framework_install(tmp_path / "older-install", declares_skew_key=False)

    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    _git(root, "checkout", "-qb", "feature/skew-key")

    home = tmp_path / "skew-home"
    (home / ".config").mkdir(parents=True, exist_ok=True)
    path_dir = tmp_path / "skew-path-bin"
    path_dir.mkdir(parents=True, exist_ok=True)
    _fake_gh(path_dir)

    # The source adapter: the shipped example, with test-evidence enforcement off (this lane has
    # never run a suite, and block-by-default would refuse for a reason unrelated to the subject)
    # and bootstrap evidence present. Written into the lane's own .tautline/ so every later
    # invocation resolves it identically with no env var. The shipped example is not weakened.
    for name in ("skew-evidence-1.txt", "skew-evidence-2.txt"):
        evidence = root / ".ai-work" / name
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("evidence\n", encoding="utf-8")
    adapter_data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter_data["testEvidence"] = {
        **(adapter_data.get("testEvidence") or {}),
        "enforcement": "off",
    }
    adapter_data["bootstrapEvidence"] = {
        "project": adapter_data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for adapter-schema skew coverage.",
        "repoEvidence": [
            {"path": ".ai-work/skew-evidence-1.txt", "fact": "evidence one exists"},
            {"path": ".ai-work/skew-evidence-2.txt", "fact": "evidence two exists"},
        ],
    }
    source_adapter = root / ".tautline" / "adapter.json"
    source_adapter.parent.mkdir(parents=True, exist_ok=True)
    source_adapter.write_text(
        json.dumps(adapter_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lane = RealSkewLane(root=root, home=home, older_install=older, path_dir=path_dir)
    rendered = lane.run_cli(
        lane.lane_cli,
        "render-adapters",
        "--project",
        str(source_adapter),
        "--target",
        str(root),
        "--write",
    )
    assert rendered.returncode == 0, rendered.stderr

    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "on: [pull_request, push]\njobs:\n  test:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        encoding="utf-8",
    )

    # Now add the key. Deliberately AFTER the render: this is the shape of a release that adds a
    # schema key -- the lane's schema declares it and the lane's adapter uses it, while every
    # installed CLI older than that release refuses it.
    rendered_adapter = lane.lane_adapter
    data = json.loads(rendered_adapter.read_text(encoding="utf-8"))
    data[adapter_key] = {"enabled": True}
    rendered_adapter.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    install_hooks_with_baked_path(root, older)
    return lane
