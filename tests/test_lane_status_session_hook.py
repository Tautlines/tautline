"""SessionStart registration for the lane-status hook (item 27: session-start currency gate)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from tautline_methodology import cli

REPO = Path(__file__).resolve().parents[1]


def test_directive_hook_command_and_timeout_are_byte_unchanged():
    """C7: the lane-status hook is a SEPARATE entry precisely so this constant never moves."""
    assert cli.SESSION_START_DIRECTIVE_HOOK_COMMAND == (
        "/bin/sh -c 'command -v tautline >/dev/null 2>&1 "
        "&& tautline autonomy-directive --hook 2>/dev/null || true'"
    )
    assert cli.SESSION_START_DIRECTIVE_HOOK_TIMEOUT == 5


def test_lane_status_hook_uses_the_same_fail_open_shell_shape():
    command = cli.SESSION_START_LANE_STATUS_HOOK_COMMAND
    assert command.startswith("/bin/sh -c 'command -v tautline >/dev/null 2>&1")
    assert command.endswith("|| true'")
    assert "lane-status --hook" in command


def test_host_timeout_exceeds_every_configurable_fetch_timeout():
    """With a host timeout at or below the schema max, the host could kill the hook before it
    reported UNVERIFIED, defeating fail-open reporting AND the configured bound."""
    assert (
        cli.SESSION_START_LANE_STATUS_HOOK_TIMEOUT
        > cli.LANE_STATUS_MAX_FETCH_TIMEOUT_SECONDS + 5
    )
    assert (
        cli.LANE_STATUS_COLLECTION_BUDGET_SECONDS
        < cli.SESSION_START_LANE_STATUS_HOOK_TIMEOUT
    )


def test_plugin_manifest_registers_both_session_start_entries_with_their_timeouts():
    """The manifest is the load path most adopters use, and neither the constant nor the
    settings-writer test governs it -- an entry without an explicit timeout silently falls back to
    the host default and the hard fail-open bound is gone."""
    manifest = json.loads(
        (REPO / "plugins" / "tautline-core" / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    hooks = [hook for entry in manifest["hooks"]["SessionStart"] for hook in entry["hooks"]]
    commands = [hook["command"] for hook in hooks]
    assert cli.SESSION_START_DIRECTIVE_HOOK_COMMAND in commands
    assert cli.SESSION_START_LANE_STATUS_HOOK_COMMAND in commands
    lane_hook = next(
        hook for hook in hooks if hook["command"] == cli.SESSION_START_LANE_STATUS_HOOK_COMMAND
    )
    assert lane_hook["timeout"] == cli.SESSION_START_LANE_STATUS_HOOK_TIMEOUT
    directive_hook = next(
        hook for hook in hooks if hook["command"] == cli.SESSION_START_DIRECTIVE_HOOK_COMMAND
    )
    assert directive_hook["timeout"] == cli.SESSION_START_DIRECTIVE_HOOK_TIMEOUT


def test_writer_is_idempotent_and_preserves_foreign_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "echo foreign"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.write_claude_session_start_lane_status_hook(settings)
    _path, already = cli.write_claude_session_start_lane_status_hook(settings)
    assert already is True, "the 25s entry must be recognised as current, or the writer loops"
    body = settings.read_text(encoding="utf-8")
    assert "echo foreign" in body
    assert body.count("lane-status --hook") == 1


def test_writer_replaces_an_entry_carrying_a_stale_timeout(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": cli.SESSION_START_LANE_STATUS_HOOK_COMMAND,
                                    "timeout": 3,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.write_claude_session_start_lane_status_hook(settings)
    body = json.loads(settings.read_text(encoding="utf-8"))
    timeouts = [
        hook.get("timeout")
        for entry in body["hooks"]["SessionStart"]
        for hook in entry["hooks"]
        if "lane-status" in hook["command"]
    ]
    assert timeouts == [cli.SESSION_START_LANE_STATUS_HOOK_TIMEOUT]


def test_both_session_start_hooks_coexist_in_one_settings_file(tmp_path):
    """They are separate entries; installing one must never displace the other."""
    settings = tmp_path / "settings.json"
    cli.write_claude_session_start_directive_hook(settings)
    cli.write_claude_session_start_lane_status_hook(settings)
    body = settings.read_text(encoding="utf-8")
    assert "autonomy-directive --hook" in body
    assert "lane-status --hook" in body
    assert cli.settings_session_start_directive_hook_installed(
        json.loads(body)
    ), "installing lane-status must not invalidate the directive entry"


def test_missing_lane_status_hook_is_reported_but_is_not_drift():
    """C6: adding this to hook_failures would fail startup on every machine that has not re-run
    install-hooks -- the exact lockout class this item closes."""
    source = inspect.getsource(cli.methodology_status)
    assert "claude_session_start_lane_status_hook" in source, "must be reported"
    failures_block = source.split("hook_failures = []", 1)[1]
    assert "lane_status_hook_installed" not in failures_block, "must NOT gate drift"


def test_lane_start_installs_the_hook_for_settings_managed_users():
    """Settings-managed installs migrate through lane-start, not the plugin manifest. Wiring only
    install_hooks would leave them without the hook, and C6 means nothing would force the repair."""
    source = inspect.getsource(cli.lane_start)
    assert "write_claude_session_start_lane_status_hook" in source


def test_install_hooks_installs_the_lane_status_hook():
    source = inspect.getsource(cli.install_hooks)
    assert "write_claude_session_start_lane_status_hook" in source
