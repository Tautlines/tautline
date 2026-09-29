from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_name_constant(cli):
    assert cli.CLI_NAME == "tautline"
    assert cli.LEGACY_CLI_NAME == "minervit-methodology"
