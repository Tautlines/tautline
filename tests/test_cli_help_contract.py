import argparse
import re


SUBCOMMAND_HELP_TOKENS = {
    ("publish-release-update", "--help"): ("--last",),
    ("sync-methodology", "--help"): (
        "--auto-rescue-local-changes",
        "--no-auto-rescue-local-changes",
    ),
    ("background-run", "--help"): ("--timeout-seconds",),
    ("monitor-status", "--help"): ("--max-stale-seconds",),
    ("response-guard", "--help"): (
        "--active-monitor",
        "--derivable-next-action-prompt",
        "--terminal-stop",
        "--boundary-summary",
    ),
    ("graphify-install", "--help"): ("--skip-setup", "--build"),
    ("codex-run", "--help"): ("--stage1-sweep",),
    ("claude-review", "--help"): ("--packet", "--timeout-seconds", "--fail-on-blockers", "--no-fail-on-blockers"),
    ("claude-review-status", "--help"): ("--review-dir", "--limit"),
    ("iteration-review-renderer-setup", "--help"): ("--no-install", "--timeout-seconds"),
    ("maintainer-mode", "--help"): ("on", "off", "status", "update gates"),
    ("methodology-status", "--help"): (
        "--strict",
        "Exit 0 clean, 1 integrity",
        "2 debt-only",
        "methodology_status_blocking:",
        "docs/reference/startup-remediation.md",
    ),
    ("publish-rca-artifact", "--help"): (
        "--commit",
        "--push",
        "--branch",
        "--allow-release-checkout-write",
        "methodology-rca-archive",
        "Skip git add only",
    ),
    ("publish-session-journal", "--help"): ("--allow-release-checkout-write",),
}


def _contains_help_token(output: str, token: str) -> bool:
    token_pattern = rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])"
    return re.search(token_pattern, output) is not None


def _registered_cli_commands(cli, monkeypatch) -> set[str]:
    captured = {}

    def capture_parser(self, argv=None):
        captured["parser"] = self
        return argparse.Namespace(cmd="version", func=lambda _args: 0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture_parser)
    assert cli.main([]) == 0

    subparser_actions = [
        action
        for action in captured["parser"]._actions
        if getattr(action, "dest", None) == "cmd" and hasattr(action, "choices")
    ]
    assert len(subparser_actions) == 1
    return set(subparser_actions[0].choices)


def test_root_help_lists_registered_commands(run_cli, cli, monkeypatch):
    commands = _registered_cli_commands(cli, monkeypatch)
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr

    missing = [
        command
        for command in commands
        if not _contains_help_token(result.stdout, command)
    ]
    assert missing == []


def test_public_contract_covers_registered_commands(cli, monkeypatch):
    registered_commands = _registered_cli_commands(cli, monkeypatch)
    contract_commands = {
        command["name"] for command in cli.public_contract_manifest_data()["commands"]
    }

    assert sorted(registered_commands - contract_commands) == []
    assert sorted(contract_commands - registered_commands) == []


def test_subcommand_help_lists_required_options(run_cli):
    missing = []
    for args, tokens in SUBCOMMAND_HELP_TOKENS.items():
        result = run_cli(*args)
        assert result.returncode == 0, result.stderr
        missing.extend(
            f"{' '.join(args)}: {token}"
            for token in tokens
            if not _contains_help_token(result.stdout, token)
        )

    assert missing == []
