"""The SessionStart hook contract.

Written for the standing-directive hook (0.13.0), which the 2026-08-28 process-bankruptcy
demolition removed along with the `autonomy-directive` verb. The CONTRACT it pinned outlives it and
now covers `lane-status --hook`, the one SessionStart hook the lean profile ships: fail-open at the
shell boundary, an explicit host-level per-hook timeout, and no dedup machinery -- the hook ALWAYS
emits, so compaction and resume re-inject by construction.
"""

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "plugins" / "tautline-core" / "hooks" / "hooks.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python-full.yml"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

def _shipped_session_start_commands() -> list[str]:
    """The SessionStart hook commands the framework actually ships, read from the payload.

    Read rather than restated. This file used to pin a hardcoded `autonomy-directive --hook`
    string and assert properties OF THAT STRING -- a test comparing a constant to itself, which
    kept passing after the 2026-08-28 demolition deleted the hook it described. The fail-open
    contract below is real and still worth pinning; it just has to be pinned against what ships.
    """
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "plugins" / "tautline-core" / "hooks" / "hooks.json"
        ).read_text(encoding="utf-8")
    )
    return [
        hook["command"]
        for matcher in payload["hooks"].get("SessionStart", [])
        for hook in matcher.get("hooks", [])
    ]


def _manifest_session_start_hooks() -> list[dict]:
    settings = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return settings["hooks"]["SessionStart"]


def _session_start_entries(settings: dict) -> list[dict]:
    return settings.get("hooks", {}).get("SessionStart", [])


def _active_registrations(settings: dict, command: str) -> list[dict]:
    """Every all-source wildcard entry whose nested command is EXACTLY the directive command."""
    active = []
    for entry in _session_start_entries(settings):
        if str(entry.get("matcher")) != "*":
            continue
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command" and hook.get("command") == command:
                active.append(entry)
    return active


# --- manifest / command shape -----------------------------------------------------------------


def test_every_shipped_session_start_hook_is_shell_fail_open():
    """Pins the fail-open contract on EVERY SessionStart hook the framework ships.

    A SessionStart hook runs before the session can do anything, so one that dies takes the
    session with it. Each piece matters: the `/bin/sh -c` wrapper, the `command -v` presence
    guard (the CLI may not be installed at all), stderr suppression, and the trailing `|| true`.
    """
    commands = _shipped_session_start_commands()
    assert commands, "the framework ships no SessionStart hook; this contract guards nothing"
    for cmd in commands:
        assert cmd.startswith("/bin/sh -c "), cmd
        assert "command -v tautline >/dev/null 2>&1" in cmd, cmd
        assert "2>/dev/null" in cmd, cmd
        assert cmd.rstrip("'").endswith("|| true"), cmd
    assert any("tautline lane-status --hook" in cmd for cmd in commands), (
        "lane-status is the SessionStart carrier the lean profile keeps; if it stops shipping, "
        "runtime_capabilities' only declared capability is a claim about nothing"
    )


# --- settings writer --------------------------------------------------------------------------


# --- lane-start self-enforcing migration ------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_adapter(target: Path) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for SessionStart directive-hook lane-start coverage.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary evidence exists."},
        ],
    }
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["backlogProvider"] = {"enabled": False}
    data["stakeholderQuestions"] = {"enabled": False}
    data["milestoneUpdate"] = {"enabled": False}
    data["productChat"] = {"enabled": False}
    data["deploymentNotification"] = {"enabled": False}
    behavior_specs = dict(data.get("behaviorSpecs") or {})
    behavior_specs["required"] = False
    behavior_specs["acceptanceHarnesses"] = []
    data["behaviorSpecs"] = behavior_specs
    document_context = dict(data.get("documentContext") or {})
    document_context["ignoredDocPaths"] = [
        *(document_context.get("ignoredDocPaths") or []),
        "docs/product/backlog",
    ]
    data["documentContext"] = document_context
    adapter = target / ".tautline" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("primary\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("secondary\n", encoding="utf-8")
    (target / "docs/product/backlog/example-saas-v1/specs").mkdir(parents=True)
    template = target / "docs/product/backlog/templates/pr-execution-spec.template.md"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")


def _start(run_cli, target: Path, adapter: Path):
    return run_cli(
        "lane-start", "--project", str(adapter), "--target", str(target), "--skip-update"
    )


def _home_settings(tmp_path: Path) -> dict:
    path = tmp_path / "home" / ".claude" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- always-emit: no dedup machinery ----------------------------------------------------------


def _run_hook(target: Path):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), "autonomy-directive", "--hook",
         "--target", str(target)],
        capture_output=True, text=True, timeout=60,
    )


# --- hook-state gate --------------------------------------------------------------------------


# --- release cascade --------------------------------------------------------------------------


# --- CI enumeration ---------------------------------------------------------------------------
