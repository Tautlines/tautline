"""THE release gate (operator directive 2026-07-12: a release must not break users).

Two transitions, both proven end to end against the real code, both required before a release:

  A. PROCESS  -- an adapted project migrates from the heavyweight profile to the lean one via
     `tautline slim`, losing no content. This is the transition every deployed adopter has to
     make once, and the one that can silently destroy a repository if it is wrong.

  B. RUNTIME  -- a user machine deployed on the PREVIOUS release survives advancing its checkout
     to this code, in every state users actually occupy: old shim + legacy-only config + new code
     (the state a machine enters the moment `git pull` lands), then reinstall, then rollback.

A renders `adapters/projects/example-saas.json` through the real renderer, so the migration is
measured against the ~16KB adapter the framework really writes. Its HOOKS are a captured literal --
the real eighteen-entry payload 0.143.0's `install-hooks` produced, recorded before that verb was
deleted. That is deliberate and not a downgrade: the state under test is a machine set up by an
OLDER release, so a fixture that asks the current installer to build it would drift forward with
every change to that installer, which is the drift the migration exists to survive. B checks out
the pinned public 0.148.1 baseline, so running on the integration tip still proves an upgrade.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tautline_methodology import lean  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TAUTLINE = REPO_ROOT / "bin" / "tautline"
PREBANKRUPTCY_ADAPTER = REPO_ROOT / "tests" / "fixtures" / "prebankruptcy-adapter"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
# Deliberately pinned to the deployed public version while recovering from demolition. Update
# only when a newer public release becomes the supported migration baseline, not on every merge.
# Resolve by VERSION rather than a private commit SHA: exported public history has different IDs.
RUNTIME_BASELINE_VERSION = "0.148.1"

# The adapter budget the lean profile exists to hold. `render_lean_adapter` targets 2048; this is
# the gate's slightly looser ceiling, so a few bytes of a longer project name is not a release
# blocker but a return to the 16KB instruction file is.
ADAPTER_CEILING_BYTES = 2560

# Present in the heavyweight adapter, and absent from the lean one by construction. Asserting on
# these is what stops "slim ran and reported success" from passing while the ceremony survives.
CEREMONY_MARKERS = (
    "Session Start",
    "Goal Orchestration",
    "Execution Packet",
    "Merge Queue",
    "roundBudgets",
    "canonical-rules.md",
)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), text=True, encoding="utf-8", errors="replace"
    ).strip()


def _run(cmd: list[str], env: dict, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _tree_digest(root: Path) -> dict[str, str]:
    """sha256 of every regular file under `root`, keyed by relative path. `.git` excluded: git's
    own index and object store churn on any command, and this is a question about the worktree."""
    digest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if ".git" in path.relative_to(root).parts:
            continue
        digest[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _hook_commands(settings_path: Path) -> list[str]:
    """Every hook command string in a Claude settings file, flattened."""
    if not settings_path.is_file():
        return []
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for matchers in (data.get("hooks") or {}).values():
        for matcher in matchers:
            for entry in matcher.get("hooks") or []:
                commands.append(str(entry.get("command") or ""))
    return commands


# =============================================================================================
# A. the PROCESS transition: heavyweight adapted project -> lean profile
# =============================================================================================


@pytest.fixture()
def adapted_project(tmp_path):
    """A project in the state a real adopter is in today, built by running the shipped code.

    Returns (project, home, env). `HOME` is hermetic and carries the framework's hooks, because
    that is where `install-hooks` really writes them -- a migration measured only against the
    project directory would prove nothing about the hooks a session can actually feel.
    """
    if not EXAMPLE_ADAPTER.is_file():
        pytest.skip("example adapter is not present in this checkout")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}

    project = tmp_path / "example-saas"
    project.mkdir()
    _git("init", "-q", "-b", "main", cwd=project)
    _git("config", "user.email", "e2e@example.invalid", cwd=project)
    _git("config", "user.name", "e2e", cwd=project)
    # The renderer verifies the adapter's `repo` against the target's origin, so origin has to be
    # the adapter's URL at render time. It is repointed at a local bare repo afterwards so nothing
    # in this test can reach the network.
    _git("remote", "add", "origin", "https://github.com/example-org/example-saas.git", cwd=project)

    rendered = _run(
        [
            sys.executable,
            str(TAUTLINE),
            "render-adapters",
            "--project",
            str(EXAMPLE_ADAPTER),
            "--target",
            str(project),
            "--write",
        ],
        env,
        REPO_ROOT,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert (project / ".tautline.json").is_file()

    # The HEAVYWEIGHT instruction files, copied from a fixture rather than rendered.
    #
    # `render-adapters` above still produces the project's 1.x `.tautline.json`, which is what
    # `slim` migrates -- but as of the 2026-08-28 demolition it emits the LEAN adapter markdown,
    # because a renderer that documents deleted commands is a defect on a keep-listed surface. So
    # the current renderer can no longer build this test's "before" state, and asking it to would
    # be the same drift-forward mistake as calling `install-hooks` above: the state under test is a
    # project whose adapter was written by an OLDER release, and only a captured artifact pins that.
    #
    # These two files are the real 0.143.0 output for this same adapter, ~16KB each. See
    # tests/fixtures/prebankruptcy-adapter/README.md.
    for name in ("CLAUDE.md", "AGENTS.md"):
        shutil.copyfile(PREBANKRUPTCY_ADAPTER / name, project / name)
    assert (project / "CLAUDE.md").stat().st_size > 8000

    # The hooks a deployed machine is carrying, written DIRECTLY rather than by running
    # `install-hooks`.
    #
    # That verb was deleted with the rest of the process engine, so the fixture cannot call it --
    # but that is not the better reason. The state this test reproduces is a machine set up by an
    # OLDER release, and only a literal payload pins that. Asking the CURRENT code to build its own
    # "before" state would make the fixture drift forward with every change to the installer, which
    # is exactly the drift the migration has to survive.
    #
    # This is the real 0.143.0 payload, captured by running that release's own `install-hooks` into
    # a scratch HOME: eighteen framework hook entries across five events, the autocompact env block
    # and the question-guard bookkeeping key. `slim` identifies a hook by CONTENT -- does its
    # command invoke the CLI -- so it has to find all eighteen without a name catalogue, including
    # the two SessionStart entries wrapped in `/bin/sh -c` and the seven-matcher latest-code fan-out.
    settings_path = home / ".claude" / "settings.json"
    settings = {
        "env": {
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "85",
            "MINERVIT_CLAUDE_AUTOCOMPACT_PCT": "85",
            "MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED": "1",
            "TAUTLINE_CLAUDE_AUTOCOMPACT_PCT": "85",
            "TAUTLINE_CLAUDE_AUTOCOMPACT_REQUIRED": "1"
        },
        "hooks": {
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "command": "tautline context-rotation-heartbeat-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "*"
                }
            ],
            "PostToolUseFailure": [
                {
                    "hooks": [
                        {
                            "command": "tautline tool-rejection-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "*"
                }
            ],
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "command": "tautline plan-finalization-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "ExitPlanMode"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline branch-liveness-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Task"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline background-command-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Bash"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Bash"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Edit"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "MultiEdit"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Write"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "NotebookEdit"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "ExitPlanMode"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline latest-code-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Task"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline plan-review-pending-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Edit|Write|MultiEdit"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline question-guard-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "AskUserQuestion"
                },
                {
                    "hooks": [
                        {
                            "command": "tautline fleet-guard-hook",
                            "type": "command"
                        }
                    ],
                    "matcher": "Edit|Write|MultiEdit|NotebookEdit"
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "command": "/bin/sh -c 'command -v tautline >/dev/null 2>&1 && tautline autonomy-directive --hook 2>/dev/null || true'",
                            "timeout": 5,
                            "type": "command"
                        }
                    ],
                    "matcher": "*"
                },
                {
                    "hooks": [
                        {
                            "command": "/bin/sh -c 'command -v tautline >/dev/null 2>&1 && tautline lane-status --hook 2>/dev/null || true'",
                            "timeout": 25,
                            "type": "command"
                        }
                    ],
                    "matcher": "*"
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "command": "tautline response-guard-hook",
                            "type": "command"
                        }
                    ]
                }
            ]
        },
        "tautlineQuestionGuardCommands": [
            "tautline question-guard-hook"
        ]
    }

    # A hook the USER wrote, in each of the two places, so the migration has to discriminate
    # rather than truncate.
    settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
        {"matcher": "*", "hooks": [{"type": "command", "command": "echo user-authored"}]}
    )
    # Machine-wide settings that have nothing to do with the framework's process. They are the
    # reason the home file is backed up beside itself rather than into the repository, and the
    # rewrite must return them byte-identical.
    settings["permissions"] = {"allow": ["Bash(npm run test:*)"], "deny": ["Read(./.env)"]}
    settings["model"] = "opusplan"
    settings["enabledPlugins"] = {"some-plugin@marketplace": True}
    settings.setdefault("env", {})["USER_MACHINE_KNOB"] = "keep-me"
    settings_path.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # The generated git hooks, carrying the generator stamp `slim` matches on (line 2 of every
    # hook that release wrote). Executable, as the installer left them, so the fixture's own push
    # below is genuinely blocked by one -- a hook the migration then has to remove.
    for git_hook in ("pre-commit", "pre-push"):
        hook_path = project / ".git" / "hooks" / git_hook
        hook_path.write_text(
            "#!/bin/sh\n"
            "# MINERVIT-BRANCH-LIVENESS-HOOK\n"
            "set -u\n"
            'exec tautline branch-liveness-check --target "$(git rev-parse --show-toplevel)" '
            "--strict\n",
            encoding="utf-8",
        )
        hook_path.chmod(0o755)
    (project / ".git" / "hooks" / "commit-msg").write_text(
        "#!/bin/sh\necho user-authored commit-msg hook\n", encoding="utf-8"
    )

    # The process history an adopter accumulated: the plan directory this project's own config
    # names, the review ledgers beside it, and a product doc that must NOT be touched.
    plans = project / "docs" / "product" / "backlog" / "example-saas-v1" / "specs"
    (plans / ".plan-reviews" / "rounds").mkdir(parents=True)
    (plans / ".impl-reviews").mkdir(parents=True)
    (plans / "0001-checkout.md").write_text("# spec\none page\n", encoding="utf-8")
    (plans / ".plan-reviews" / "rounds" / "r1.json").write_text('{"round": 1}\n', encoding="utf-8")
    (plans / ".impl-reviews" / "feature-x.json").write_text('{"rounds": 3}\n', encoding="utf-8")
    # A ledger OUTSIDE the configured plan directory. Without it the ledger DISCOVERY layer is
    # never exercised: everything under `plans/` is archived by the config-named path alone, and a
    # discovery that found nothing would look identical to one that worked.
    stray = project / "docs" / "engineering" / ".impl-reviews"
    stray.mkdir(parents=True)
    (stray / "legacy-branch.json").write_text('{"rounds": 6}\n', encoding="utf-8")
    product_doc = project / "docs" / "product" / "user-scenarios.md"
    product_doc.write_text("# scenarios\nthe operator wrote this\n", encoding="utf-8")

    _git("add", "-A", cwd=project)
    _git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "adopted", cwd=project)

    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _git("remote", "set-url", "origin", str(bare), cwd=project)
    # `core.hooksPath` off: the pre-push hook this fixture just installed refuses the push (the
    # adapter's repo no longer matches the local origin). Being blocked by it here is incidental
    # setup friction; that the migration REMOVES it is what the test is about.
    _git("-c", "core.hooksPath=/dev/null", "push", "-q", "origin", "main", cwd=project)
    return project, home, env


def _slim(project: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return _run(
        [sys.executable, str(TAUTLINE), "slim", "--target", str(project), *args], env, REPO_ROOT
    )


def test_slim_migrates_an_adapted_project_and_destroys_nothing(adapted_project):
    project, home, env = adapted_project
    settings_path = home / ".claude" / "settings.json"

    before_project = _tree_digest(project)
    before_hooks = _tree_digest(project / ".git" / "hooks")
    before_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    heavy_adapter_bytes = (project / "CLAUDE.md").stat().st_size
    assert heavy_adapter_bytes > 8000, "fixture is not the heavyweight adapter to migrate"
    assert len(_hook_commands(settings_path)) >= 15, "fixture did not get the framework's hooks"

    # --- dry run changes nothing -------------------------------------------------------------
    dry = _slim(project, env, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "would " in dry.stdout
    assert _tree_digest(project) == before_project, "--dry-run mutated the project"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == before_settings

    # --- the migration ------------------------------------------------------------------------
    result = _slim(project, env)
    assert result.returncode == 0, result.stderr
    assert "rollback: git can restore everything" in result.stdout

    # 1. the framework's hooks are gone; the user's survive, in both places.
    remaining = _hook_commands(settings_path)
    assert remaining == ["echo user-authored"], remaining
    assert "tautlineQuestionGuardCommands" not in json.loads(
        settings_path.read_text(encoding="utf-8")
    )
    assert not (project / ".git" / "hooks" / "pre-commit").exists()
    assert not (project / ".git" / "hooks" / "pre-push").exists()
    assert (project / ".git" / "hooks" / "commit-msg").is_file(), "removed a user-authored git hook"

    # 1a. the home settings file was BACKED UP before it was rewritten, beside itself and NOT into
    #     the repository -- it carries machine-wide permission grants and env values.
    backup = settings_path.with_name(settings_path.name + ".before-tautline-slim")
    assert backup.is_file(), "the agent settings file was rewritten with no backup"
    assert json.loads(backup.read_text(encoding="utf-8")) == before_settings, (
        "the backup is not the pre-migration content"
    )
    assert f"{backup}" in result.stdout, "the summary must name where the backup went"
    archived_anywhere = {
        path.name for path in (project / lean.ARCHIVE_DIRNAME).rglob("*") if path.is_file()
    }
    assert "settings.json.before-tautline-slim" not in archived_anywhere
    assert not (project / lean.ARCHIVE_DIRNAME / ".claude").exists(), (
        "the machine-wide settings file must never be copied into the project"
    )

    # 1b. the rewrite touched hooks and framework bookkeeping ONLY. Every other top-level key --
    #     permissions, model, enabledPlugins, env -- survives byte-identical.
    after_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    for key, value in before_settings.items():
        if key in ("hooks", "tautlineQuestionGuardCommands"):
            continue
        assert key in after_settings, f"the rewrite dropped a non-hook settings key: {key}"
        assert after_settings[key] == value, f"the rewrite altered {key}"
    assert after_settings["permissions"]["deny"] == ["Read(./.env)"]
    assert after_settings["env"]["USER_MACHINE_KNOB"] == "keep-me"

    # 2. the config is valid lean-1 and every identity value survived the translation.
    config = json.loads((project / ".tautline.json").read_text(encoding="utf-8"))
    assert lean.lean_config_errors(config) == [], lean.lean_config_errors(config)
    source = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    assert config["project"]["name"] == source["project"]
    assert config["project"]["repo"] == source["repo"]
    assert config["integrationBranch"] == source["latestCode"]["base"]
    assert config["commands"]["test"] == source["commands"]["fullPreflight"]
    for rule in source["knownProjectRules"]:
        assert rule in config["projectRules"], f"dropped a project rule: {rule}"
    assert "roundBudgets" not in json.dumps(config), "a ceremony key survived the migration"

    # 3. the thin adapter: small, complete, and free of the process it replaced.
    for name, agent in (("CLAUDE.md", "Claude"), ("AGENTS.md", "Codex")):
        text = (project / name).read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        assert size <= ADAPTER_CEILING_BYTES, f"{name} is {size} bytes"
        assert size < heavy_adapter_bytes / 4, f"{name} did not actually shrink"
        assert text.startswith("<!-- GENERATED -->\n"), f"{name} lost its generated marker"
        assert f"- {agent} Adapter" in text
        for norm in lean.PROCESS_NORMS:
            assert norm in text, f"{name} is missing a process norm: {norm}"
        for marker in CEREMONY_MARKERS:
            assert marker not in text, f"{name} still carries ceremony: {marker}"

    # 4. the archive holds the displaced history.
    archive = project / lean.ARCHIVE_DIRNAME
    assert archive.is_dir()
    archived = {p.relative_to(archive).as_posix() for p in archive.rglob("*") if p.is_file()}
    plans_rel = "docs/product/backlog/example-saas-v1/specs"
    assert f"{plans_rel}/0001-checkout.md" in archived
    assert f"{plans_rel}/.plan-reviews/rounds/r1.json" in archived
    assert f"{plans_rel}/.impl-reviews/feature-x.json" in archived
    assert "docs/engineering/.impl-reviews/legacy-branch.json" in archived, (
        "the ledger outside the configured plan directory was never discovered"
    )
    assert not (project / "docs" / "engineering" / ".impl-reviews").exists()
    assert "CLAUDE.md" in archived and ".tautline.json" in archived
    assert "git-hooks/pre-push" in archived and "git-hooks/pre-commit" in archived
    archived_cfg = json.loads((archive / ".tautline.json").read_text(encoding="utf-8"))
    assert archived_cfg["schemaVersion"] == "1.0.0", "archived config is not the pre-migration one"

    # 5. THE contract: not one byte of content was destroyed. Every file that existed before the
    #    migration is still readable somewhere in the project -- in place, moved, or backed up.
    surviving = set(_tree_digest(project).values())
    surviving |= set(_tree_digest(project / ".git" / "hooks").values())
    before_all = dict(before_project)
    before_all.update({f".git/hooks/{name}": sha for name, sha in before_hooks.items()})
    for rel, sha in before_all.items():
        if rel.endswith(".sample"):
            continue
        assert sha in surviving, f"slim destroyed the content of {rel}"

    # 6. a product document the operator wrote is exactly where they left it.
    assert (project / "docs" / "product" / "user-scenarios.md").is_file()

    # 7. the second run is a no-op, byte for byte.
    settled = _tree_digest(project)
    settled_settings = settings_path.read_text(encoding="utf-8")
    again = _slim(project, env)
    assert again.returncode == 0, again.stderr
    assert "already lean - no changes" in again.stdout
    assert _tree_digest(project) == settled, "a second slim changed the project"
    assert settings_path.read_text(encoding="utf-8") == settled_settings

    # 8. lane-status -- KEEP-listed, advisory -- still runs, and still ANSWERS. Exit 0 is not
    #    enough: a report that degrades to "could not be computed" on every lean project is a
    #    control that reports nothing.
    status = _run(
        [sys.executable, str(TAUTLINE), "lane-status", "--target", str(project), "--json"],
        env,
        REPO_ROOT,
    )
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)
    assert payload["schema"] == "tautline-lane-status/v1"
    assert payload["branch"] == "main", payload
    assert payload["integrationBranch"] == "main", payload


def test_slim_leaves_the_agent_hooks_alone_when_asked(adapted_project):
    """`--keep-agent-hooks` is the opt-out, and it has to actually opt out."""
    project, home, env = adapted_project
    settings_path = home / ".claude" / "settings.json"
    before = settings_path.read_text(encoding="utf-8")
    result = _slim(project, env, "--keep-agent-hooks")
    assert result.returncode == 0, result.stderr
    assert settings_path.read_text(encoding="utf-8") == before
    config = json.loads((project / ".tautline.json").read_text(encoding="utf-8"))
    assert config["schemaVersion"] == lean.LEAN_SCHEMA_VERSION, "the rest must still have run"


def test_slim_refuses_a_project_it_was_never_adapted_to(tmp_path):
    """Pointing slim at an unrelated directory must be an error, not a silent rewrite."""
    env = {"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]}
    (tmp_path / "home").mkdir()
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "README.md").write_text("not a tautline project\n", encoding="utf-8")
    result = _slim(stranger, env)
    assert result.returncode != 0
    assert "no Tautline adapter found" in result.stderr
    assert list(stranger.iterdir()) == [stranger / "README.md"]


# =============================================================================================
# B. the RUNTIME transition: a deployed machine advances its checkout, then rolls back
# =============================================================================================


def _runtime_baseline(root: Path) -> str:
    def read(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    # Public tags are authoritative when present. Internal development has no release tags, so
    # accept its stable branch at that version, then a historical VERSION-pinned snapshot.
    candidates = [f"refs/tags/v{RUNTIME_BASELINE_VERSION}",
                  f"refs/tags/{RUNTIME_BASELINE_VERSION}", "refs/remotes/origin/main", "main"]
    pattern = "^" + RUNTIME_BASELINE_VERSION.replace(".", "[.]") + "$"
    candidates.extend(read("log", "--all", "--format=%H", f"-G{pattern}", "--", "VERSION").splitlines())
    for ref in candidates:
        if read("show", f"{ref}:VERSION") == RUNTIME_BASELINE_VERSION:
            return read("rev-parse", f"{ref}^{{commit}}")
    pytest.fail(
        f"Runtime upgrade baseline {RUNTIME_BASELINE_VERSION} is missing; fetch full Git history "
        "and release tags before running the release gate. No network fetch is done by tests."
    )


def test_runtime_baseline_stays_on_public_release_when_integration_is_current(tmp_path):
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "test@example.invalid", cwd=tmp_path)
    _git("config", "user.name", "test", cwd=tmp_path)
    (tmp_path / "VERSION").write_text("0.148.1\n", encoding="utf-8")
    _git("add", "VERSION", cwd=tmp_path)
    _git("commit", "-qm", "public baseline", cwd=tmp_path)
    expected = _git("rev-parse", "HEAD", cwd=tmp_path)
    (tmp_path / "VERSION").write_text("0.147.0\n", encoding="utf-8")
    _git("commit", "-qam", "development", cwd=tmp_path)
    _git("update-ref", "refs/remotes/origin/experimental", "HEAD", cwd=tmp_path)
    assert _runtime_baseline(tmp_path) == expected


def test_runtime_baseline_missing_history_is_a_failure_not_a_skip(tmp_path):
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    with pytest.raises(pytest.fail.Exception, match="0.148.1.*full Git history"):
        _runtime_baseline(tmp_path)


@pytest.fixture()
def upgrade_machine(tmp_path):
    """A hermetic 'user machine': HOME + a runtime clone at the pinned public baseline."""
    base = _runtime_baseline(REPO_ROOT)
    current = _git("rev-parse", "HEAD", cwd=REPO_ROOT)
    assert base != current, "the release gate must exercise a real upgrade transition"
    home = tmp_path / "home"
    home.mkdir()
    clone = tmp_path / "runtime"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", f"file://{REPO_ROOT}", str(clone)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    # A local clone advertises branches and tags, not source remote-tracking refs. The selected
    # stable commit may live only at origin/main, so fetch that exact object from the same disk.
    subprocess.run(
        ["git", "-C", str(clone), "fetch", "-q", "--no-tags", f"file://{REPO_ROOT}", base],
        check=True, capture_output=True, timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(clone), "checkout", "-q", base], check=True, capture_output=True
    )
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return home, clone, env, base, current


def test_user_machine_survives_upgrade_and_rollback(upgrade_machine):
    home, clone, env, base, current = upgrade_machine
    old_cli = clone / "bin" / "tautline"
    legacy_cfg = home / ".config" / "minervit" / "methodology.env"
    new_cfg = home / ".config" / "tautline" / "tautline.env"
    shim = home / ".local" / "bin" / "tautline"

    # --- deploy the PREVIOUS release exactly as a user machine has it -------------------------
    installed = _run([str(old_cli), "install-cli"], env, clone)
    assert installed.returncode == 0, installed.stderr
    assert legacy_cfg.is_file(), "previous release writes the legacy config"
    # a user secret preserved across the whole journey:
    with legacy_cfg.open("a", encoding="utf-8") as fh:
        fh.write('export UPGRADE_E2E_SECRET="survives"\n')
    baseline = _run([str(shim), "version", "--no-remote"], env, clone)
    assert baseline.returncode == 0, baseline.stderr
    assert f"plugin_version: {RUNTIME_BASELINE_VERSION}" in baseline.stdout

    # --- state 1: checkout advances to THIS code; nothing reinstalled yet ----------------------
    subprocess.run(
        ["git", "-C", str(clone), "checkout", "-q", current], check=True, capture_output=True
    )
    via_old_shim = _run([str(shim), "version", "--no-remote"], env, clone)
    assert via_old_shim.returncode == 0, (
        "old shim + legacy-only config MUST run the new code unchanged:\n" + via_old_shim.stderr
    )
    assert "plugin_version:" in via_old_shim.stdout
    sync = _run([str(shim), "sync-methodology", "--skip-update", "--no-remote"], env, clone)
    assert sync.returncode == 0, "sync via old surface must not fail closed:\n" + sync.stderr

    # --- state 2: user runs the new install-cli ------------------------------------------------
    reinstalled = _run([str(old_cli), "install-cli"], env, clone)
    assert reinstalled.returncode == 0, reinstalled.stderr
    assert new_cfg.is_file() and legacy_cfg.is_file(), "both surfaces exist after upgrade install"
    assert new_cfg.read_text(encoding="utf-8") == legacy_cfg.read_text(encoding="utf-8"), (
        "legacy mirror must stay byte-identical so pre-upgrade launchers keep resolving"
    )
    assert 'export UPGRADE_E2E_SECRET="survives"' in new_cfg.read_text(encoding="utf-8"), (
        "user values hand-added on the previous release must migrate"
    )
    post = _run([str(shim), "version", "--no-remote"], env, clone)
    assert post.returncode == 0, post.stderr

    # --- state 3: rollback to the previous release ---------------------------------------------
    subprocess.run(
        ["git", "-C", str(clone), "checkout", "-q", base], check=True, capture_output=True
    )
    rolled_back = _run([str(shim), "version", "--no-remote"], env, clone)
    assert rolled_back.returncode == 0, (
        "rollback must leave a working machine (legacy mirror keeps old code resolving):\n"
        + rolled_back.stderr
    )
    assert "plugin_version:" in rolled_back.stdout
