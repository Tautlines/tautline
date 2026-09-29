"""arch-errors-1 (productization): ONE explicit hook-failure contract. Hooks (commands ending in
-hook) FAIL OPEN on an unexpected internal error -- a hook bug must never wedge a lane -- while
non-hook commands keep fail-loud behavior and intentional block exits are preserved.
"""

import argparse
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
