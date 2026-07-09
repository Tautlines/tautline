from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_name_constant(cli):
    assert cli.CLI_NAME == "tautline"
    assert cli.LEGACY_CLI_NAME == "minervit-methodology"


def test_generated_wrapper_prefers_tautline_and_falls_back():
    # The emitted lane wrapper must resolve `tautline` first, `minervit-methodology` as fallback.
    text = (ROOT / "bin/tautline").read_text()
    assert "command -v tautline" in text
    assert "command -v minervit-methodology" in text  # fallback retained


def test_legacy_cli_name_still_allowed_by_latest_code_guard(cli):
    # Existing lanes rendered before the rename still instruct `minervit-methodology <cmd>`;
    # the latest-code guard must keep releasing for them until the shim-removal cleanup.
    assert cli.latest_code_command_allowed("minervit-methodology latest-code-status --target . --write")
    assert cli.latest_code_command_allowed("tautline latest-code-status --target . --write")


def test_tautline_repo_alias_allowed_by_latest_code_guard(cli):
    # resolve_env honors TAUTLINE_-prefixed aliases, so the documented recovery form
    # with the aliased repo var must release the guard exactly like the legacy var.
    assert cli.latest_code_command_allowed("$TAUTLINE_METHODOLOGY_REPO/bin/tautline latest-code-status --target . --write")
    assert cli.latest_code_command_allowed("$MINERVIT_METHODOLOGY_REPO/bin/tautline latest-code-status --target . --write")
