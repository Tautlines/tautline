import json
import os
import re
import subprocess
import sys
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
    # This fixture's subject is graphify, so the board gate is neutralized the same way the
    # sibling gates above are. BOTH halves are needed, and only having the first is why this
    # test passed in CI and failed on a developer box for months:
    #
    #   unavailablePolicy=warn covers an UNREADABLE board (0.10.3 fails closed by default).
    #     That is CI's case -- no gh credentials -- so CI was green.
    #   enabled=False covers a READABLE one. `goal_tracker_failures` is board_drift PLUS
    #     blocking-unavailable, and drift is only computable when the board CAN be read. On a
    #     machine with a working gh token the provider answered, reported drift, and
    #     `methodology_status_blocking` grew a `goal_tracker` entry that the assertion below
    #     enumerates exactly -- so the test's verdict depended on the developer's GitHub
    #     credentials and on live board state neither it nor its fixture controls.
    data.setdefault("backlogProvider", {})["unavailablePolicy"] = "warn"
    data["backlogProvider"]["enabled"] = False
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
