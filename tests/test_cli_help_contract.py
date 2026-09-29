import argparse
import re


SUBCOMMAND_HELP_TOKENS = {
    # The surviving surface only. The 2026-08-28 process-bankruptcy demolition removed every other
    # verb this table used to pin; the contract itself -- a documented flag must appear in its own
    # `--help` -- is unchanged, and each entry below names a flag whose absence would be a silent
    # regression for a command adopters still run.
    ("sync-methodology", "--help"): (
        "--auto-rescue-local-changes",
        "--no-auto-rescue-local-changes",
    ),
    ("methodology-status", "--help"): (
        "--strict",
        "--fail-on-drift",
        "--no-remote",
    ),
    ("render-adapters", "--help"): ("--write", "--check", "--project"),
    ("lane-status", "--help"): ("--hook", "--json"),
    ("secret-status", "--help"): ("--name",),
    ("release-tail", "--help"): ("--dry-run",),
    ("registry-package", "--help"): ("--registry", "--version", "--destination"),
    ("public-release-export", "--help"): ("--destination",),
    ("decision-record", "--help"): ("--summary", "--rationale", "--reversibility"),
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
