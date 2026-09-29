"""`tautline secret-status`: where a secret is reachable from, and never what it is.

Item 85 WS1a. The refusal this verb repairs used to say "the secret is missing" and send the lane
straight to an operator escalation. The overwhelmingly common cause is not a missing value: it is a
value that IS persisted and that this process cannot see — a session started outside the lane env,
or a value written under the `MINERVIT_` spelling while the resolver prefers the `TAUTLINE_` alias.

So "confirmed absent" has to mean absent from **all three** layers, and the exit code carries that
predicate: 0 = reachable, 1 = confirmed absent, escalation now justified. Everything below exists to
keep those two answers honest.
"""

import argparse

import pytest


def _probe(cli, name):
    return cli.secret_status(argparse.Namespace(name=name))


@pytest.fixture
def layers(cli, tmp_path, monkeypatch):
    """Point all three layers at empty, writable temp files. Nothing leaks in from the machine."""
    config_env = tmp_path / "tautline.env"
    secrets = tmp_path / "secrets.zsh"
    config_env.write_text("", encoding="utf-8")
    secrets.write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", config_env)
    monkeypatch.setattr(cli, "LEGACY_USER_CONFIG_ENV", tmp_path / "methodology.env")
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", secrets)
    monkeypatch.setattr(cli, "LEGACY_USER_SECRETS_ENV", tmp_path / "legacy-secrets.zsh")
    for var in ("STRIPE_API_KEY", "TAUTLINE_DEMO_TOKEN", "MINERVIT_DEMO_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return config_env, secrets


def test_absent_from_every_layer_exits_one(cli, layers, capsys):
    """The escalation predicate. Only this answer justifies going to a human."""
    assert _probe(cli, "STRIPE_API_KEY") == 1
    out = capsys.readouterr().out
    assert "secret_source: absent" in out
    assert "only a value absent from all three layers is an operator escalation" in out


def test_a_value_in_the_process_env_is_reachable(cli, layers, monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_do_not_print_me")
    assert _probe(cli, "STRIPE_API_KEY") == 0
    assert "secret_source: process-env" in capsys.readouterr().out


def test_a_value_in_the_config_env_is_reachable(cli, layers, capsys):
    config_env, _secrets = layers
    config_env.write_text("STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    assert _probe(cli, "STRIPE_API_KEY") == 0
    assert "secret_source: config-env:" in capsys.readouterr().out


def test_a_value_in_the_secrets_file_is_reachable(cli, layers, capsys):
    _config_env, secrets = layers
    secrets.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    assert _probe(cli, "STRIPE_API_KEY") == 0
    assert "secret_source: secrets-file:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "asked,written",
    [
        ("MINERVIT_DEMO_TOKEN", "TAUTLINE_DEMO_TOKEN"),
        ("TAUTLINE_DEMO_TOKEN", "MINERVIT_DEMO_TOKEN"),
    ],
)
def test_either_spelling_finds_the_other(cli, layers, capsys, asked, written):
    """The misdiagnosis this verb exists to prevent, in both directions.

    Both spellings are live during the rebrand and `resolve_env` PREFERS the alias. A probe that
    checked only the name it was handed would report `absent` for a value sitting right there under
    its sibling — and `absent` is the answer that sends someone to an operator.
    """
    config_env, _secrets = layers
    config_env.write_text(f"{written}=present\n", encoding="utf-8")
    assert _probe(cli, asked) == 0
    assert "secret_source: config-env:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "asked,exported",
    [
        ("TAUTLINE_DEMO_TOKEN", "MINERVIT_DEMO_TOKEN"),
        ("MINERVIT_DEMO_TOKEN", "TAUTLINE_DEMO_TOKEN"),
    ],
)
def test_the_process_env_layer_probes_both_spellings(
    cli, layers, monkeypatch, capsys, asked, exported
):
    """`resolve_env` resolves MINERVIT_ -> TAUTLINE_ and NOT the reverse.

    Probing the process env through it reported `absent` -- exit 1, the escalation predicate -- for
    a TAUTLINE_-spelled name whose value was exported under the MINERVIT_ one and sitting in this
    process's own environment. That is exactly the misdiagnosis this verb exists to prevent,
    occurring inside the verb. Both directions are pinned so a future alias-resolution change
    cannot quietly restore the one-way behaviour.
    """
    monkeypatch.setenv(exported, "present")
    assert _probe(cli, asked) == 0
    assert "secret_source: process-env" in capsys.readouterr().out


def test_an_unreadable_layer_is_not_reported_as_confirmed_absent(cli, layers, capsys):
    """The distinction that is this verb's whole job.

    `user_config_env_value` returns "" on OSError, so a secrets file this process cannot read looked
    identical to one that simply does not hold the value -- and the answer it produced, exit 1, is
    the one that sends a lane to an operator. A probe must not report a definite result for a layer
    nothing ever read.
    """
    _config_env, secrets = layers
    secrets.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    secrets.chmod(0o000)
    try:
        assert _probe(cli, "STRIPE_API_KEY") == 2
    finally:
        secrets.chmod(0o600)
    out = capsys.readouterr().out
    assert "secret_source: indeterminate" in out
    assert "secret_layer_unreadable: secrets-file:" in out
    assert "NOT confirmed absent" in out
    assert "do not escalate on this result" in out


def test_an_indeterminate_result_does_not_print_the_escalation_marker(cli, layers, capsys):
    """`secret_source: absent` is not a description, it is the ESCALATION PREDICATE.

    Canonical policy 03 and 23 and the risk-tier skill all name that exact marker as the thing that
    justifies going to an operator. Printing it above an exit code meaning "indeterminate" hands an
    agent the token it was told to act on and relies on it reading the prose underneath instead.
    """
    _config_env, secrets = layers
    secrets.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    secrets.chmod(0o000)
    try:
        assert _probe(cli, "STRIPE_API_KEY") == 2
    finally:
        secrets.chmod(0o600)
    out = capsys.readouterr().out
    assert "secret_source: indeterminate" in out
    assert "secret_source: absent" not in out


def test_an_unreadable_parent_directory_is_not_a_missing_file(
    cli, layers, tmp_path, capsys, monkeypatch
):
    """`Path.is_file()` RETURNS FALSE rather than raising when a parent directory cannot be
    traversed, so an inaccessible file holding the secret read as a missing one and the probe
    exited 1: confirmed absent, escalate. Opening the file is what tells the two apart."""
    hidden = tmp_path / "locked"
    hidden.mkdir()
    secrets = hidden / "secrets.zsh"
    secrets.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", secrets)
    hidden.chmod(0o000)
    try:
        assert _probe(cli, "STRIPE_API_KEY") == 2
    finally:
        hidden.chmod(0o700)
    out = capsys.readouterr().out
    assert "secret_source: indeterminate" in out
    # ...and the LAYER SELECTION had the same bug: an unreadable secrets file must not silently
    # hand the probe the legacy path, or it reports on a file the operator does not use.
    assert f"secret_secrets_file: {secrets}" in out


def test_a_value_in_a_file_is_not_told_to_re_run_through_lane_run(cli, layers, capsys):
    """`lane-run` builds its child env from the CURRENT process environment; it does not source
    either persisted file. Prescribing it for a value that lives in a file sends the caller round
    the same refusal forever -- a remedy that cannot work is worse than none, because it looks
    like progress."""
    _config_env, secrets = layers
    secrets.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    assert _probe(cli, "STRIPE_API_KEY") == 0
    out = capsys.readouterr().out
    assert "lane-run" not in out
    assert f". {secrets}" in out


def test_a_layer_that_does_not_exist_is_absent_not_indeterminate(cli, layers, capsys):
    """A machine with no secrets file at all is the common case, not a broken one.

    Treating a missing file as unreadable would make `absent` unreachable there -- the probe would
    never be able to justify the escalation it exists to gate.
    """
    config_env, secrets = layers
    config_env.unlink()
    secrets.unlink()
    assert _probe(cli, "STRIPE_API_KEY") == 1
    out = capsys.readouterr().out
    assert "secret_source: absent" in out
    assert "secret_layer_unreadable" not in out


def test_the_probe_reads_through_the_resolver(cli, layers, monkeypatch):
    """The probe must not reach `os.environ` itself, however convenient that is.

    Reading the environment directly is exactly what `test_no_shipped_source_bypasses_the_resolver`
    forbids, and for the reason this verb cares about most: a direct read misses a managed alias.
    Fixing the one-way-alias defect by bypassing the resolver would have traded this verb's
    misdiagnosis for the same failure one layer up, in a guard that protects every other read in
    the tree. Pinned behaviourally -- a stubbed resolver that answers for nothing must make the
    probe report absent, which it cannot do if the value is being read from anywhere else.
    """
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_do_not_print_me")
    monkeypatch.setattr(cli.util_module(), "resolve_env", lambda name, *a, **k: "")
    assert _probe(cli, "STRIPE_API_KEY") == 1


def test_the_value_is_never_printed_from_any_layer(cli, layers, monkeypatch, capsys):
    """The contract. This verb runs inside refusals, so its output lands in lane logs and CI
    transcripts; echoing the secret to be more helpful would leak it into every one of them."""
    secret = "sk_live_51H8xQeCanaryValue"
    config_env, secrets = layers
    config_env.write_text(f"STRIPE_API_KEY={secret}\n", encoding="utf-8")
    secrets.write_text(f"export OTHER_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv("THIRD_KEY", secret)
    for name in ("STRIPE_API_KEY", "OTHER_KEY", "THIRD_KEY"):
        _probe(cli, name)
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize(
    "bad", ["stripe_api_key", "STRIPE-API-KEY", "", "  ", "STRIPE KEY", "1STRIPE", "$(id)"]
)
def test_a_name_that_is_not_an_env_var_is_refused(cli, layers, bad):
    """The argument is echoed into output and used to index config files, so it is validated as an
    env var name and not merely stripped."""
    with pytest.raises(SystemExit) as excinfo:
        _probe(cli, bad)
    assert "UPPER_CASE environment variable name" in str(excinfo.value)


def test_the_verb_is_registered_and_dispatches_to_its_own_handler():
    """Wiring, from the committed dispatch golden rather than from a parser this module rebuilds.

    The parser is constructed inside `main()`, so a test that reached for a factory would be
    asserting against its own reconstruction. `tests/data/dispatch_map.json` is the AST-derived
    pairing the repo already trusts to catch a verb wired to the wrong handler.
    """
    import json
    from pathlib import Path as _Path

    golden = json.loads(
        (_Path(__file__).resolve().parent / "data" / "dispatch_map.json").read_text("utf-8")
    )
    assert golden.get("secret-status") == "secret_status"


def test_the_name_argument_is_required(run_cli):
    """Any refusal printing `secret-status --name <VAR>` must run exactly as printed.

    Required, not defaulted: `test_a_named_remedy_carries_the_verbs_required_arguments` checks that
    a remedy names the arguments its verb demands, and a defaulted `--name` would let a refusal
    print a command that silently probes the wrong thing.
    """
    result = run_cli("secret-status")
    assert result.returncode != 0
    assert "required" in (result.stderr + result.stdout)
    assert "--name" in (result.stderr + result.stdout)


def test_a_first_setup_machine_is_pointed_at_the_current_store(
    cli, layers, capsys, monkeypatch, tmp_path
):
    """Neither store exists -- the normal first-setup case. Falling back unconditionally told the
    operator to create the DEPRECATED Minervit store, which is correct only for as long as the
    compatibility fallback survives and is wrong advice on the day it is removed."""
    current = tmp_path / "new-secrets.zsh"
    legacy = tmp_path / "old-secrets.zsh"
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", current)
    monkeypatch.setattr(cli, "LEGACY_USER_SECRETS_ENV", legacy)
    assert _probe(cli, "STRIPE_API_KEY") == 1
    out = capsys.readouterr().out
    assert f"secret_secrets_file: {current}" in out
    assert str(legacy) not in out


def test_an_existing_legacy_store_is_still_selected(cli, layers, capsys, monkeypatch, tmp_path):
    """The fallback is not deleted -- a machine that HAS the legacy store must still be read."""
    current = tmp_path / "new-secrets.zsh"
    legacy = tmp_path / "old-secrets.zsh"
    legacy.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", current)
    monkeypatch.setattr(cli, "LEGACY_USER_SECRETS_ENV", legacy)
    assert _probe(cli, "STRIPE_API_KEY") == 0
    assert f"secret_secrets_file: {legacy}" in capsys.readouterr().out


def test_the_sourcing_remedy_survives_a_path_with_a_space(
    cli, layers, capsys, monkeypatch, tmp_path
):
    """The remedy is printed for an agent to run AS PRINTED. An unquoted path splits."""
    spaced = tmp_path / "My Home" / "secrets.zsh"
    spaced.parent.mkdir()
    spaced.write_text("export STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    monkeypatch.setattr(cli, "USER_SECRETS_ENV", spaced)
    assert _probe(cli, "STRIPE_API_KEY") == 0
    out = capsys.readouterr().out
    assert (
        "'" in out.split("set -a; . ")[1].split(";")[0]
        or '"' in out.split("set -a; . ")[1].split(";")[0]
    )


def test_an_unreadable_config_directory_does_not_crash_the_probe(cli, layers, tmp_path, capsys, monkeypatch):
    """`resolve_user_config_env()` calls `Path.is_file()`, which RAISES for a path behind a
    non-traversable directory -- so the probe died with a traceback before any of its
    unreadable-layer handling could run. A verb whose contract is "tell absent from unreadable"
    must not crash on the unreadable case."""
    hidden = tmp_path / "locked-config"
    hidden.mkdir()
    config = hidden / "tautline.env"
    config.write_text("STRIPE_API_KEY=sk_live_do_not_print_me\n", encoding="utf-8")
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", config)
    hidden.chmod(0o000)
    try:
        assert _probe(cli, "STRIPE_API_KEY") == 2
    finally:
        hidden.chmod(0o700)
    assert "secret_source: indeterminate" in capsys.readouterr().out
