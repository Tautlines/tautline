"""Quality rec #8: red-green discrimination proof.

The true FM1 kill -- proves a test would FAIL if the code broke, killing no-op / over-mock / assert-True
tests that pass no matter what. The framework mutates a single symbol of the changed source, runs the
test command, and requires a GENUINE assertion failure: a mutation that only breaks loading/collection
is rejected as a valid kill (that bypass would let an import error masquerade as discrimination).
"""

import argparse


def _ns(**kw):
    base = dict(project=None, target=None, file=None, test_command=None, strict=False)
    base.update(kw)
    return argparse.Namespace(**base)


# --- pure mutation generation --------------------------------------------------------------------

def test_generate_mutations_return_bool(cli):
    muts = cli.generate_mutations("def f():\n    return True\n")
    assert any(label == "return True -> return False" and "return False" in src for label, src in muts)


def test_generate_mutations_skips_comments(cli):
    muts = cli.generate_mutations("# return True in a comment\nx = 1\n")
    assert muts == []


def test_generate_mutations_equality(cli):
    muts = cli.generate_mutations("def f(a, b):\n    return a == b\n")
    assert any("!=" in src for _, src in muts)


# --- pure outcome classification -----------------------------------------------------------------

def test_outcome_survived_on_exit_zero(cli):
    assert cli.mutation_outcome(0, "1 passed") == "survived"


def test_outcome_killed_on_assertion(cli):
    assert cli.mutation_outcome(1, "E   AssertionError: 1 != 2\n1 failed") == "killed"


def test_outcome_error_on_import_only(cli):
    # A mutation that just breaks loading is NOT a valid kill -- it must be retried, not credited.
    assert cli.mutation_outcome(1, "ImportError: cannot import name x\nerrors during collection") == "error"


def test_outcome_killed_when_assertion_despite_collection_word(cli):
    assert cli.mutation_outcome(1, "AssertionError\nsome collection happened") == "killed"


def test_outcome_tooling_failure_is_not_a_kill(cli):
    # P1 fix: a non-zero exit with NO test-assertion evidence (lint/type/missing-command) must NOT be
    # credited as a kill -- otherwise a linter rejecting the mutated token masquerades as discrimination.
    assert cli.mutation_outcome(1, "app.py:1:1: F401 imported but unused\nFound 1 error.") == "error"
    assert cli.mutation_outcome(1, "bash: pytest: command not found") == "error"
    assert cli.mutation_outcome(1, "npm ERR! Missing script: \"test\"") == "error"
    # but a real test-runner failure summary is a kill
    assert cli.mutation_outcome(1, "1 failed, 3 passed") == "killed"


# --- orchestrator integration --------------------------------------------------------------------

def test_survivor_blocks_in_strict(cli, tmp_path):
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return True\n")
    # `true` always passes -> every mutation survives -> non-discriminating -> block.
    rc = cli.red_green_check(_ns(target=tmp_path, file=src, test_command="true", strict=True))
    assert rc == 1
    assert src.read_text() == "def f():\n    return True\n"  # reverted


def test_killed_passes(cli, tmp_path):
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return True\n")
    # A "test" that is green on the original and emits a real assertion failure once the mutation flips
    # return True -> return False. Baseline (original) is green; the mutant produces 'AssertionError'.
    cmd = "grep -q 'return True' m.py || { echo 'AssertionError: value changed'; exit 1; }"
    rc = cli.red_green_check(_ns(target=tmp_path, file=src, test_command=cmd, strict=True))
    assert rc == 0
    assert src.read_text() == "def f():\n    return True\n"  # reverted


def test_baseline_red_skips(cli, tmp_path):
    # If the unmutated test command is already red, we cannot measure discrimination -> skip, never block.
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return True\n")
    rc = cli.red_green_check(_ns(target=tmp_path, file=src, test_command="false", strict=True))
    assert rc == 0
    assert src.read_text() == "def f():\n    return True\n"  # reverted


def test_survivor_warn_mode_does_not_block(cli, tmp_path):
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return True\n")
    rc = cli.red_green_check(_ns(target=tmp_path, file=src, test_command="true", strict=False))
    assert rc == 0


def test_no_applicable_mutation_skips(cli, tmp_path):
    src = tmp_path / "m.py"
    src.write_text("x = 1\ny = 2\n")
    rc = cli.red_green_check(_ns(target=tmp_path, file=src, test_command="true", strict=True))
    assert rc == 0  # nothing to mutate -> not a failure
