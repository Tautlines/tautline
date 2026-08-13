import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
# A graphify invocation whose target is the bare `.` -- the form that makes graphify choose a
# backend from ambient credentials. That choice is what RCA 20260616T133743Z proved a third
# party can retire out from under a lane, so no blocking gate may name one. Matching the SHAPE
# rather than the one retired literal keeps the guard alive for forms nobody has written yet.
AUTO_DETECT_INVOCATION = re.compile(r"graphify \.(?!\w)")


def _run(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command_env = {
        **os.environ,
        "HOME": str((cwd or REPO_ROOT) / ".test-home"),
    }
    if env:
        command_env.update(env)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=cwd,
        env=command_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "validation-bootstrap-evidence-1.txt").write_text("validation evidence one\n", encoding="utf-8")
    (evidence / "validation-bootstrap-evidence-2.txt").write_text("validation evidence two\n", encoding="utf-8")


def _graphify_adapter_data() -> dict:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["latestCode"] = {"enabled": False}
    data.setdefault("graphify", {})["freshnessEnforcement"] = "strict-if-present"
    data.setdefault("ciTestGate", {})["enforcement"] = "warn"
    # This fixture's subject is graphify and its env has no gh; opt the board gate
    # down the same way the sibling gates above are neutralized (0.10.3 fails
    # closed on an unreadable board by default).
    data.setdefault("backlogProvider", {})["unavailablePolicy"] = "warn"
    data["bootstrapEvidence"] = {
        "project": data["project"],
        "status": "repo-evident",
        "summary": "Pytest fixture for Graphify behavior.",
        "repoEvidence": [
            {"path": ".ai-work/validation-bootstrap-evidence-1.txt", "fact": "validation evidence one exists"},
            {"path": ".ai-work/validation-bootstrap-evidence-2.txt", "fact": "validation evidence two exists"},
        ],
    }
    return data


def _write_adapter(adapter_root: Path, name: str, data: dict) -> Path:
    adapter = adapter_root / name
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _write_graphify_adapter(adapter_root: Path) -> Path:
    return _write_adapter(adapter_root, "graphify-example.json", _graphify_adapter_data())


def _graphify_on_path(tmp_path: Path) -> str:
    """A PATH whose first entry holds a stub `graphify`, so shutil.which() resolves.

    `print_graphify_status` picks its next-action hint by priority, and "the CLI is missing"
    outranks "there is no graph output yet". A test about the OUTPUT-ABSENT hint therefore
    passes or fails according to whether the machine running it happens to have graphify
    installed -- green on a developer box, red on CI. The stub is never executed; only its
    presence is read, which is exactly the precondition under test.
    """
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "graphify"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    return f"{bindir}{os.pathsep}{os.environ['PATH']}"


def _adapter_env(adapter_root: Path) -> dict[str, str]:
    return {
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
        "MINERVIT_METHODOLOGY_REPO": "",
    }


def _prepare_graphify_target(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    target = tmp_path / "graphify-target"
    adapter_root = tmp_path / "trusted-adapters"
    adapter = _write_graphify_adapter(adapter_root)
    _init_repo(target)
    env = _adapter_env(adapter_root)
    started = _run("lane-start", "--project", str(adapter), "--target", str(target), "--skip-update", cwd=target, env=env)
    assert "graphify: enabled=true" in started.stdout
    assert "graphify_instruction: If output exists, it must be current before use/commit/push" in started.stdout
    assert "graphify-out/" in (target / ".gitignore").read_text(encoding="utf-8")
    return target, adapter, env


def test_graphify_status_detects_missing_stale_fresh_and_tracked_output(tmp_path):
    target, adapter, env = _prepare_graphify_target(tmp_path)

    missing = _run("graphify-status", "--project", str(adapter), "--target", str(target), cwd=target, env=env)
    assert "graphify: enabled=true" in missing.stdout
    assert "graphify_gitignore: ok graphify-out/" in missing.stdout
    assert "graphify_freshness: missing-output enforcement=strict-if-present" in missing.stdout

    output = target / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text('{"nodes":[]}\n', encoding="utf-8")
    (output / "GRAPH_REPORT.md").write_text("# Graph report\n", encoding="utf-8")
    time.sleep(1)
    (target / "app.py").write_text("new project behavior\n", encoding="utf-8")
    _git(target, "add", "app.py")

    stale = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=env,
        check=False,
    )
    assert stale.returncode == 1
    assert "graphify_freshness: stale enforcement=strict-if-present" in stale.stdout
    # This fixture derives from example-saas.json, which overrides updateCommand to
    # `graphify update`. Post-0.53.0 the remediation strings render the CONFIGURED command,
    # so the override -- not the default `graphify update .` -- is what must appear here.
    assert "graphify_issue: stale Graphify output: run `graphify update`" in stale.stdout
    assert (
        "graphify_next: run `graphify update` before commit, push, or Graphify-backed decisions"
    ) in stale.stdout

    time.sleep(1)
    (output / "graph.json").write_text('{"nodes":["fresh"]}\n', encoding="utf-8")
    fresh = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=env,
    )
    assert "graphify_freshness: current enforcement=strict-if-present" in fresh.stdout

    _git(target, "add", "-f", "graphify-out/graph.json")
    tracked = _run(
        "methodology-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--no-remote",
        "--fail-on-drift",
        cwd=target,
        env=env,
        check=False,
    )
    # graphify_failures is a DEBT gate (0.8.9 startup remediation); no INTEGRITY gate fires here
    # (lane-start already rendered the adapter cleanly), so bare --fail-on-drift exits 2
    # (remediation mode) instead of 1.
    assert tracked.returncode == 2
    assert "graphify_issue: tracked Graphify output must be removed from git" in tracked.stdout
    assert "methodology_status_blocking: debt - planning, milestone_update, graphify" in tracked.stdout


def test_installed_hooks_enforce_graphify_freshness_and_keep_prepush_guard(tmp_path):
    target, _adapter, env = _prepare_graphify_target(tmp_path)

    _run(
        "install-hooks",
        "--settings",
        str(tmp_path / "graphify-claude-settings.json"),
        "--target",
        str(target),
        cwd=target,
        env=env,
    )
    pre_commit = target / ".git" / "hooks" / "pre-commit"
    pre_push = target / ".git" / "hooks" / "pre-push"
    assert "graphify-status --target . --strict" in pre_commit.read_text(encoding="utf-8")
    assert "graphify-status --target . --strict" in pre_push.read_text(encoding="utf-8")
    assert "guard-check --target . --boundary prepush" in pre_push.read_text(encoding="utf-8")

    output = target / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text('{"nodes":[]}\n', encoding="utf-8")
    time.sleep(1)
    (target / "hook-change.py").write_text("hook-visible project change\n", encoding="utf-8")
    stale = subprocess.run(
        [str(pre_commit)],
        cwd=target,
        env={**os.environ, **env, "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert stale.returncode == 1
    assert "graphify_issue: stale Graphify output: run `graphify update`" in stale.stdout

    time.sleep(1)
    (output / "graph.json").write_text('{"nodes":["hook-fresh"]}\n', encoding="utf-8")
    fresh = subprocess.run(
        [str(pre_commit)],
        cwd=target,
        env={**os.environ, **env, "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert fresh.returncode == 0, fresh.stderr
    assert "branch_liveness: pass" in fresh.stdout


def test_default_graphify_blocking_gate_is_the_no_llm_refresh(cli):
    """The blocking freshness gate must never name a backend-auto-detecting graphify invocation.

    RCA 20260616T133743Z: the retired default was a bare `graphify .` form, which selects a
    backend from ambient credentials. Its auto-detected bedrock model was decommissioned by the
    provider, so the documented BLOCKING gate command failed permanently -- while the flag the
    gate actually checks (an mtime comparison) only ever needed the dependency-free AST refresh.
    The gate and the command that satisfies it must be the same thing, and that thing must not
    depend on a third party's model catalogue.

    The absence check is a pattern, not a literal, so it also catches any FUTURE auto-detect
    form (`graphify . --anything`), not just the one command this release retired.
    """
    defaults = cli.DEFAULT_GRAPHIFY

    assert defaults["updateCommand"] == "graphify update ."
    # T1.4, decided by running it: `graphify update .` cold-builds from nothing with no API key
    # and no AWS_PROFILE (exit 0, graph.json + GRAPH_REPORT.md created), so the auto-detect form
    # survives in no default at all -- not even the initial build.
    assert defaults["buildCommand"] == "graphify update ."
    assert not AUTO_DETECT_INVOCATION.search(defaults["freshnessRule"])
    assert "`graphify update .`" in defaults["freshnessRule"]
    assert "no-LLM" in defaults["freshnessRule"]
    rule = defaults["freshnessRule"]
    assert "LLM-backed graphify invocations are never the blocking gate." in rule


def test_default_graphify_semantic_step_is_separate_non_blocking_and_backend_explicit(cli):
    """Semantic enrichment is the only part that needs a backend, so it names one explicitly."""
    defaults = cli.DEFAULT_GRAPHIFY

    assert defaults["semanticCommand"] == (
        "GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli"
    )
    assert defaults["semanticRule"].strip()
    assert "NON-blocking" in defaults["semanticRule"]
    # The point of naming the backend is that nothing here may be auto-detected again.
    assert "--backend=" in defaults["semanticCommand"]


def test_blank_semantic_keys_are_refused_like_every_other_graphify_command(tmp_path):
    """The two new keys join the required-non-blank loop.

    A blank value is a refusal, not a silent fallback to the default.
    """
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "blank-semantic-target"
    _init_repo(target)
    for key in ("semanticCommand", "semanticRule"):
        data = _graphify_adapter_data()
        data["graphify"][key] = "   "
        adapter = _write_adapter(adapter_root, f"blank-{key}.json", data)
        result = _run(
            "graphify-status",
            "--project",
            str(adapter),
            "--target",
            str(target),
            cwd=target,
            env=_adapter_env(adapter_root),
            check=False,
        )
        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert f"Project adapter graphify.{key} must be non-blank" in output


def test_stale_gate_remediation_names_the_configured_command_not_a_hardcoded_one(tmp_path):
    """A project that overrides updateCommand must be told to run ITS command when the gate trips.

    This is the regression test for the divergence the RCA found: the adapter documented one
    command and the gate printed another, so an adapter that had already been fixed still
    prescribed the broken invocation.
    """
    target = tmp_path / "sentinel-target"
    adapter_root = tmp_path / "trusted-adapters"
    data = _graphify_adapter_data()
    data["graphify"]["updateCommand"] = "mygraph refresh"
    data["graphify"]["buildCommand"] = "mygraph bootstrap"
    adapter = _write_adapter(adapter_root, "sentinel-graphify.json", data)
    _init_repo(target)
    env = _adapter_env(adapter_root)

    # The output-absent hint is only reachable when the CLI resolves, so put a stub on PATH
    # rather than inheriting whatever the running machine happens to have installed.
    absent = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        cwd=target,
        env={**env, "PATH": _graphify_on_path(tmp_path)},
    )
    assert "graphify: enabled=true cli=present" in absent.stdout
    assert (
        "graphify_next: build with `mygraph bootstrap` or update with `mygraph refresh`"
    ) in absent.stdout

    output = target / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text('{"nodes":[]}\n', encoding="utf-8")
    (output / "GRAPH_REPORT.md").write_text("# Graph report\n", encoding="utf-8")
    time.sleep(1)
    (target / "app.py").write_text("new project behavior\n", encoding="utf-8")

    stale = _run(
        "graphify-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        cwd=target,
        env=env,
        check=False,
    )
    assert stale.returncode == 1
    assert "graphify_issue: stale Graphify output: run `mygraph refresh`" in stale.stdout
    assert (
        "graphify_next: run `mygraph refresh` before commit, push, or Graphify-backed decisions"
    ) in stale.stdout
    assert not AUTO_DETECT_INVOCATION.search(stale.stdout)


def test_rendered_bullet_claims_no_llm_only_when_the_command_is_the_no_llm_default(cli):
    """The `(no-LLM)` qualifier describes the DEFAULT command, never an arbitrary override.

    The rendered Graphify bullet interpolates the CONFIGURED updateCommand. Appending
    `(no-LLM)` unconditionally would hand a lane that pinned an LLM-backed invocation a
    generated adapter asserting its blocking gate needs no backend -- the exact
    documented-command-vs-actual-gate divergence this release exists to remove, reintroduced
    by the fix for it. So the qualifier is rendered only when the two strings agree.
    """
    adapter_path = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
    data = cli.load_project(adapter_path)

    # example-saas overrides updateCommand, so it must NOT be told its command is no-LLM.
    assert data["graphify"]["updateCommand"] != cli.DEFAULT_GRAPHIFY["updateCommand"]
    overridden = cli.render_adapter(data, "Claude", str(adapter_path))
    assert "run `graphify update` before commit/push" in overridden
    assert "(no-LLM)" not in overridden

    # A lane on the default gets the qualifier, because there it is true.
    data["graphify"] = {**data["graphify"], "updateCommand": cli.DEFAULT_GRAPHIFY["updateCommand"]}
    defaulted = cli.render_adapter(data, "Claude", str(adapter_path))
    assert "run `graphify update .` (no-LLM) before commit/push" in defaulted
