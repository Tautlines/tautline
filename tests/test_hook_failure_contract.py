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
    assert _commands_for_event(settings, "Stop") == [
        "tautline response-guard-hook"
    ]


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
            "guard helpers require the framework checkout's src/minervit_methodology package"
        ) from ModuleNotFoundError("No module named 'minervit_methodology'")

    assert cli.dispatch_command(_args("response-guard-hook", missing_package)) == 0
    err = capsys.readouterr().err
    assert "hook_fail_open" in err
    assert "missing framework package" in err


def test_hook_unrelated_systemexit_with_src_path_is_preserved(cli):
    def blocker(_args):
        raise SystemExit("validation failed for src/minervit_methodology/guards.py")

    with pytest.raises(SystemExit):
        cli.dispatch_command(_args("response-guard-hook", blocker))


def test_non_hook_command_fails_loud(cli):
    def boom(_args):
        raise RuntimeError("explode")

    with pytest.raises(RuntimeError):
        cli.dispatch_command(_args("render-adapters", boom))


def test_hook_normal_return_passes_through(cli):
    assert cli.dispatch_command(_args("latest-code-hook", lambda _a: 0)) == 0


def test_real_accessors_without_src_emit_guided_systemexit_and_hooks_fail_open(tmp_path):
    """Follow-up (review finding): the fail-open branch in dispatch_command
    keys on the accessor SystemExit message substring. Pin that contract against the
    REAL accessors (not a fabricated message) by running a copied bin with no sibling
    src/ in a subprocess, and prove a real -hook invocation still fails open."""
    import shutil
    import subprocess
    import sys
    import textwrap

    shutil.copy2(REPO_ROOT / "bin" / "tautline", tmp_path / "minervit-methodology")
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            import importlib.machinery
            import importlib.util

            loader = importlib.machinery.SourceFileLoader("mm_standalone", "minervit-methodology")
            spec = importlib.util.spec_from_loader("mm_standalone", loader)
            mm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mm)

            for accessor in (mm.guards_module, mm.public_release_module, mm.adapter_module):
                try:
                    accessor()
                except SystemExit as exc:
                    assert "require the framework checkout's src/minervit_methodology" in str(exc), (
                        f"accessor {accessor.__name__} lost the guided-message contract: {exc}"
                    )
                    assert isinstance(exc.__cause__, ModuleNotFoundError), (
                        f"accessor {accessor.__name__} lost the ModuleNotFoundError cause"
                    )
                else:
                    raise AssertionError(f"{accessor.__name__} did not raise without src/")
            print("accessors-ok")
            """
        )
    )
    result = subprocess.run(
        [sys.executable, "probe.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "accessors-ok" in result.stdout

    hook = subprocess.run(
        [sys.executable, str(tmp_path / "minervit-methodology"), "response-guard-hook"],
        cwd=tmp_path,
        input="{}",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert hook.returncode == 0, (
        f"-hook command must fail open without src/: rc={hook.returncode} stderr={hook.stderr}"
    )
