"""SessionStart standing-directive hook (0.13.0).

Registers a SessionStart hook for directive-core's already-shipped
`tautline autonomy-directive --hook`, so a BARE session (no entry-point verb run
yet) still receives the standing directive. The hook is fail-open at the shell
boundary and carries an explicit host-level per-hook timeout; there is NO dedup
machinery -- the hook ALWAYS emits, so compaction/resume re-inject the directive
by construction (at-most-double emission on dual-registered machines is accepted).
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "plugins" / "tautline-core" / "hooks" / "hooks.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-python-full.yml"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

EXPECTED_COMMAND = (
    "/bin/sh -c 'command -v tautline >/dev/null 2>&1 "
    "&& tautline autonomy-directive --hook 2>/dev/null || true'"
)


def _manifest_session_start_hooks() -> list[dict]:
    settings = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return settings["hooks"]["SessionStart"]


def _session_start_entries(settings: dict) -> list[dict]:
    return settings.get("hooks", {}).get("SessionStart", [])


def _active_registrations(settings: dict, command: str = EXPECTED_COMMAND) -> list[dict]:
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


def test_hooks_manifest_has_session_start_directive():
    """The invariant is that the DIRECTIVE is registered exactly once under the all-source matcher,
    not that it is the only SessionStart hook: 0.21.0 adds a second, independent lane-status entry
    (item 27), which is why the count is scoped to entries carrying this command."""
    entries = [
        entry
        for entry in _manifest_session_start_hooks()
        if any(hook.get("command") == EXPECTED_COMMAND for hook in entry.get("hooks", []))
    ]
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry["matcher"] == "*"
    assert len(entry["hooks"]) == 1
    hook = entry["hooks"][0]
    assert hook["type"] == "command"
    assert hook["command"] == EXPECTED_COMMAND


def test_hook_command_is_shell_fail_open():
    # Pins the fail-open contract so a refactor cannot drop any piece: the /bin/sh -c wrapper,
    # the `command -v` presence guard, stderr suppression, and the trailing `|| true`.
    cmd = EXPECTED_COMMAND
    assert cmd.startswith("/bin/sh -c ")
    assert "command -v tautline >/dev/null 2>&1" in cmd
    assert "tautline autonomy-directive --hook" in cmd
    assert "2>/dev/null" in cmd
    assert cmd.rstrip("'").endswith("|| true")


def test_manifest_and_settings_commands_identical(cli):
    (hook,) = _manifest_session_start_hooks()[0]["hooks"]
    assert hook["command"] == cli.SESSION_START_DIRECTIVE_HOOK_COMMAND


def test_session_start_hook_carries_timeout(cli, tmp_path):
    # The host-level per-hook timeout is what makes fail-open real: without it a hanging shim
    # would wait out the host's long default. It must appear in BOTH the manifest and freshly
    # written settings, byte-value 5.
    (manifest_hook,) = _manifest_session_start_hooks()[0]["hooks"]
    assert manifest_hook["timeout"] == 5
    settings_path = tmp_path / "settings.json"
    cli.write_claude_session_start_directive_hook(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    (written_hook,) = _active_registrations(settings)[0]["hooks"]
    assert written_hook["timeout"] == cli.SESSION_START_DIRECTIVE_HOOK_TIMEOUT == 5


# --- settings writer --------------------------------------------------------------------------


def test_install_hooks_adds_session_start_once(cli, tmp_path):
    settings_path = tmp_path / "settings.json"
    _, already_present = cli.write_claude_session_start_directive_hook(settings_path)
    assert already_present is False
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert len(_active_registrations(settings)) == 1

    _, already_present_again = cli.write_claude_session_start_directive_hook(settings_path)
    assert already_present_again is True
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert len(_active_registrations(settings)) == 1


def test_install_hooks_preserves_existing_session_start_entries(cli, tmp_path):
    settings_path = tmp_path / "settings.json"
    foreign = {
        "hooks": {
            "SessionStart": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "echo foreign"}]}
            ]
        }
    }
    settings_path.write_text(json.dumps(foreign), encoding="utf-8")
    cli.write_claude_session_start_directive_hook(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in _session_start_entries(settings)
        for hook in entry.get("hooks", [])
    ]
    assert "echo foreign" in commands, "foreign SessionStart entry must be preserved"
    assert EXPECTED_COMMAND in commands
    assert len(_active_registrations(settings)) == 1


def test_writer_replaces_narrowed_matcher_entry(cli, tmp_path):
    settings_path = tmp_path / "settings.json"
    narrowed = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "resume",
                    "hooks": [
                        {"type": "command", "command": EXPECTED_COMMAND},
                        {"type": "command", "command": "echo sibling"},
                    ],
                }
            ]
        }
    }
    settings_path.write_text(json.dumps(narrowed), encoding="utf-8")
    cli.write_claude_session_start_directive_hook(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    entries = _session_start_entries(settings)

    # Exactly one ACTIVE registration afterward (the wildcard), never a double.
    assert len(_active_registrations(settings)) == 1
    # The foreign sibling in the narrowed entry survives; the migrated command was removed from it.
    narrowed_after = [e for e in entries if str(e.get("matcher")) == "resume"]
    assert len(narrowed_after) == 1
    narrowed_cmds = [h["command"] for h in narrowed_after[0]["hooks"]]
    assert narrowed_cmds == ["echo sibling"], narrowed_cmds
    assert EXPECTED_COMMAND not in narrowed_cmds


def test_writer_drops_narrowed_entry_with_no_foreign_siblings(cli, tmp_path):
    settings_path = tmp_path / "settings.json"
    narrowed = {
        "hooks": {
            "SessionStart": [
                {"matcher": "resume", "hooks": [{"type": "command", "command": EXPECTED_COMMAND}]}
            ]
        }
    }
    settings_path.write_text(json.dumps(narrowed), encoding="utf-8")
    cli.write_claude_session_start_directive_hook(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    entries = _session_start_entries(settings)
    # The now-empty narrowed entry is dropped; only the wildcard remains.
    assert [str(e.get("matcher")) for e in entries] == ["*"]
    assert len(_active_registrations(settings)) == 1


def test_writer_rewrites_wildcard_entry_missing_or_wrong_timeout(cli, tmp_path):
    # A pre-existing wildcard entry with the exact command but a MISSING (or larger) timeout is
    # NOT healthy: a hanging shim would stall session start for the host default, defeating
    # the fail-open guarantee. The writer must rewrite it WITH the timeout and never leave two
    # wildcard registrations (which would re-introduce the double-emit + unbounded-timeout hole).
    for stale_hook in ({"type": "command", "command": EXPECTED_COMMAND},
                       {"type": "command", "command": EXPECTED_COMMAND, "timeout": 120}):
        settings_path = tmp_path / f"settings-{stale_hook.get('timeout', 'none')}.json"
        settings_path.write_text(
            json.dumps({"hooks": {"SessionStart": [{"matcher": "*", "hooks": [stale_hook]}]}}),
            encoding="utf-8",
        )
        # Not a current registration until the timeout is exactly the fail-open value.
        assert not cli.settings_session_start_directive_hook_installed(
            json.loads(settings_path.read_text(encoding="utf-8"))
        )
        _, already_present = cli.write_claude_session_start_directive_hook(settings_path)
        assert already_present is False
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        active = _active_registrations(settings)
        assert len(active) == 1, active  # rewritten, not duplicated
        assert active[0]["hooks"][0]["timeout"] == cli.SESSION_START_DIRECTIVE_HOOK_TIMEOUT == 5
        # Now it is healthy, and a re-run is a no-op.
        assert cli.settings_session_start_directive_hook_installed(settings)
        _, already_present_again = cli.write_claude_session_start_directive_hook(settings_path)
        assert already_present_again is True


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


def test_lane_start_installs_session_start_hook(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    result = _start(run_cli, target, adapter)
    assert result.returncode == 0, result.stdout + result.stderr
    settings = _home_settings(tmp_path)
    assert len(_active_registrations(settings)) == 1


def test_lane_start_second_run_no_duplicate_entry(tmp_path, run_cli):
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target)
    assert _start(run_cli, target, adapter).returncode == 0
    second = _start(run_cli, target, adapter)
    assert second.returncode == 0, second.stdout + second.stderr
    settings = _home_settings(tmp_path)
    assert len(_active_registrations(settings)) == 1


# --- always-emit: no dedup machinery ----------------------------------------------------------


def _run_hook(target: Path):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), "autonomy-directive", "--hook",
         "--target", str(target)],
        capture_output=True, text=True, timeout=60,
    )


def test_hook_always_emits_no_marker_files(tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    (target / ".ai-work").mkdir()
    # A valid generated-adapter marker so the directive resolves and emits.
    (target / ".tautline.json").write_text(
        EXAMPLE_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8"
    )

    def ai_work_files() -> set[str]:
        return {str(p.relative_to(target)) for p in (target / ".ai-work").rglob("*")}

    before = ai_work_files()
    first = _run_hook(target)
    second = _run_hook(target)
    assert first.returncode == 0 and second.returncode == 0
    assert "STANDING AUTONOMY DIRECTIVE" in first.stdout
    # Always-emit: the SECOND consecutive invocation emits identically -- no suppression, no
    # freshness window, no TTL claim silences it (the no-dedup design pin).
    assert first.stdout == second.stdout
    # And no marker/claim artifact was written to gate a future emission.
    assert ai_work_files() == before


# --- hook-state gate --------------------------------------------------------------------------


def test_methodology_status_hook_failure_when_session_start_missing(cli, tmp_path, monkeypatch):
    # A settings-managed machine WITHOUT the SessionStart entry is a blocking hook failure, exactly
    # like the existing eight, and the recovery action names install-hooks.
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    installed, status = cli.claude_session_start_directive_hook_state(tmp_path)
    assert installed is False
    assert "missing required hook" in status
    assert "install-hooks" in status

    # Once written, the same state function reports it installed (no longer a failure).
    cli.write_claude_session_start_directive_hook(settings_path)
    installed_after, _ = cli.claude_session_start_directive_hook_state(tmp_path)
    assert installed_after is True


# --- release cascade --------------------------------------------------------------------------


def test_rollback_notes_name_exact_command_and_knob(cli):
    report = cli.release_migration_report_data("0.13.0")
    assert report["version"] == "0.13.0"
    assert report["wipSafe"] is False
    assert [m["id"] for m in report["requiredMigrations"]] == ["grant-gh-project-scopes"]
    rollback = "\n".join(report["rollbackNotes"])
    assert EXPECTED_COMMAND in rollback, "rollbackNotes must carry the exact SessionStart command"
    assert "autonomy.standingDirective: false" in rollback, "rollbackNotes must name knob-off"
    behavior = "\n".join(report["behaviorChanges"])
    assert "SessionStart" in behavior
    assert "install-hooks" in behavior, "behaviorChanges must name the gate-extension recovery"


# --- CI enumeration ---------------------------------------------------------------------------


def test_ci_fresh_install_enumerates_session_start_hook():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    smoke = jobs["fresh-install-smoke"]
    run_text = "\n".join(str(step.get("run", "")) for step in smoke.get("steps", []))
    # The fresh-wheel smoke must assert the SessionStart directive hook lands, so a packaged
    # lane-start that omits it goes red in CI (it is identified by its shell-wrapped invocation,
    # not a bare `tautline <verb>`).
    assert "autonomy-directive --hook" in run_text
    # And the previously under-enumerated eighth hook (plan-review-pending) is now covered too.
    assert "plan-review-pending-hook" in run_text
