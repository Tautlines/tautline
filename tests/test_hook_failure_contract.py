"""arch-errors-1 (productization): ONE explicit hook-failure contract. Hooks (commands ending in
-hook) FAIL OPEN on an unexpected internal error -- a hook bug must never wedge a lane -- while
non-hook commands keep fail-loud behavior and intentional block exits are preserved.
"""

import argparse
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "plugins" / "tautline-core" / "hooks" / "hooks.json"


def _args(cmd, func):
    ns = argparse.Namespace()
    ns.cmd = cmd
    ns.func = func
    return ns


def _commands_for_event(settings, event, matcher=None):
    commands = []
    for entry in settings["hooks"][event]:
        if matcher is not None and entry.get("matcher") != matcher:
            continue
        commands.extend(hook["command"] for hook in entry["hooks"])
    return commands


def test_plugin_hooks_json_registers_required_claude_guards():
    settings = json.loads(HOOKS_JSON.read_text())

    # Plan Task 7 (real-pypi-package): the hooks invoke `tautline`, the name that
    # resolves on EVERY supported install — the wheel ships it as a console script
    # and install_cli writes both shims. Only a machine that installed before the
    # `tautline` shim existed and never re-ran install-cli lacks it (recorded as a
    # requiredMigration in the 0.10.0 migration report).
    assert _commands_for_event(settings, "PostToolUseFailure", matcher="*") == [
        "tautline tool-rejection-hook"
    ]
    assert _commands_for_event(settings, "PreToolUse", matcher="Bash") == [
        "tautline background-command-hook"
    ]
    assert _commands_for_event(settings, "PreToolUse", matcher="ExitPlanMode") == [
        "tautline plan-finalization-hook"
    ]
    # Plan Task 8 (plan-review deadlock): plugin installs take their hooks from THIS
    # manifest, not from install-hooks/lane-start, so the pending-run edit guard must
    # be registered here or the headline Claude package never gets it.
    assert _commands_for_event(settings, "PreToolUse", matcher="Edit|Write|MultiEdit") == [
        "tautline plan-review-pending-hook"
    ]
    # Fleet Governor: its own matcher block, which ALSO covers NotebookEdit --
    # notebooks are files too and must not bypass the lease guard. Asserted
    # separately from the plan-review block so a regression that merged the two
    # (and silently dropped NotebookEdit) fails here.
    assert _commands_for_event(
        settings, "PreToolUse", matcher="Edit|Write|MultiEdit|NotebookEdit"
    ) == ["tautline fleet-guard-hook"]
    # Item 82 / RCA 20260701T115759Z: AskUserQuestion BLOCKS the turn waiting for the human, so the
    # Stop hook may never fire on a forbidden continue-vs-stop menu. Registered HERE because plugin
    # installs take their hooks from this manifest and would otherwise never receive it -- the same
    # reasoning as the plan-review block above, and the same failure it prevents.
    assert _commands_for_event(settings, "PreToolUse", matcher="AskUserQuestion") == [
        "tautline question-guard-hook"
    ]
    assert _commands_for_event(settings, "Stop") == [
        "tautline response-guard-hook"
    ]


def test_hook_invocation_docs_name_the_canonical_cli():
    """SWEEP-10 (deferral sweep): hooks.json has shipped canonical `tautline ...` commands
    since the wheel's console script landed, but the hand-maintained docs that DESCRIBE the
    hook wiring still spelled the legacy `minervit-methodology` CLI. The docs must name the
    command the hooks actually run, keyed off hooks.json so a future rename drags them along."""
    settings = json.loads(HOOKS_JSON.read_text())
    (stop_command,) = _commands_for_event(settings, "Stop")
    assert stop_command.startswith("tautline "), "Stop guard lost its canonical CLI spelling"

    policy_doc = (
        REPO_ROOT
        / "plugins"
        / "tautline-core"
        / "skills"
        / "background-task-monitoring"
        / "references"
        / "background-monitoring-policy.md"
    )
    policy = policy_doc.read_text(encoding="utf-8")
    assert stop_command in policy, (
        f"{policy_doc.name} must name the Stop hook command hooks.json registers"
    )
    assert "minervit-methodology response-guard-hook" not in policy, (
        f"{policy_doc.name} still spells the legacy hook invocation"
    )

    readme = (REPO_ROOT / "plugins" / "tautline-core" / ".claude-plugin" / "README.md").read_text(
        encoding="utf-8"
    )
    heading = "## Hooks and the CLI dependency"
    assert heading in readme
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    assert "`tautline` CLI" in section, "README hooks section must name the canonical CLI"
    assert "minervit-methodology" not in section, (
        "README hooks section still names the legacy CLI spelling"
    )


def test_hook_fails_open_on_unexpected_error(cli, capsys):
    def boom(_args):
        raise RuntimeError("kaboom secret=topsecret123")

    rc = cli.dispatch_command(_args("response-guard-hook", boom))
    assert rc == 0, "a hook that raises must fail open (return 0), not wedge the lane"
    err = capsys.readouterr().err
    assert "hook_fail_open" in err
    assert "topsecret123" not in err  # redacted via redact_secrets


def test_hook_intentional_systemexit_is_preserved(cli):
    def blocker(_args):
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        cli.dispatch_command(_args("plan-finalization-hook", blocker))


def test_hook_missing_framework_package_systemexit_fails_open(cli, capsys):
    def missing_package(_args):
        raise SystemExit(
            "guard helpers require the framework checkout's src/tautline_methodology package"
        ) from ModuleNotFoundError("No module named 'tautline_methodology'")

    assert cli.dispatch_command(_args("response-guard-hook", missing_package)) == 0
    err = capsys.readouterr().err
    assert "hook_fail_open" in err
    assert "missing framework package" in err


def test_hook_unrelated_systemexit_with_src_path_is_preserved(cli):
    def blocker(_args):
        raise SystemExit("validation failed for src/tautline_methodology/guards.py")

    with pytest.raises(SystemExit):
        cli.dispatch_command(_args("response-guard-hook", blocker))


def test_non_hook_command_fails_loud(cli):
    def boom(_args):
        raise RuntimeError("explode")

    with pytest.raises(RuntimeError):
        cli.dispatch_command(_args("render-adapters", boom))


def test_hook_normal_return_passes_through(cli):
    assert cli.dispatch_command(_args("latest-code-hook", lambda _a: 0)) == 0


def test_standalone_shim_without_src_fails_open_for_hooks(tmp_path):
    """Post the package-split flip (roadmap #11), bin/tautline is a thin shim over
    tautline_methodology.cli. A STANDALONE copy of the shim with no sibling src/ can no longer
    reach the engine at all, so the shim itself must honor the arch-errors-1 hook fail-open
    contract: a ``-hook`` invocation must never wedge a lane even here (rc 0), while a non-hook
    command fails loud with a guided message instead of an opaque ModuleNotFoundError traceback.

    (The engine-side fail-open branch that keys on the accessors' guided SystemExit -- the case
    where the package IS present -- is pinned by test_hook_missing_framework_package_systemexit_
    fails_open above, against dispatch_command directly.)"""
    import shutil
    import subprocess
    import sys

    # A copied shim with NO src/ sibling: parents[1] has no src, so the shim's bootstrap adds
    # nothing to sys.path and the engine import fails -- the standalone fail-open path.
    standalone = tmp_path / "standalone" / "bin" / "minervit-methodology"
    standalone.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "bin" / "tautline", standalone)

    hook = subprocess.run(
        [sys.executable, str(standalone), "response-guard-hook"],
        cwd=tmp_path,
        input="{}",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert hook.returncode == 0, (
        f"-hook command must fail open without src/: rc={hook.returncode} stderr={hook.stderr}"
    )

    non_hook = subprocess.run(
        [sys.executable, str(standalone), "version", "--no-remote"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert non_hook.returncode != 0, "a non-hook command must fail loud without the package"
    assert "src/tautline_methodology" in (non_hook.stderr + non_hook.stdout), (
        "the standalone shim must emit a guided message naming the missing package"
    )
