"""sec-secrets-1/3/4/5 (productization): a single redact_secrets() choke point masks webhook URLs,
token/secret query params, and live secret-env values before they reach any log, error, or process
output sink.
"""


def test_chat_webhook_url_is_masked(cli):
    out = cli.redact_secrets("posting to https://chat.googleapis.com/v1/spaces/AAA/messages?key=k&token=SECRETTOKEN now")
    assert "SECRETTOKEN" not in out
    assert "chat.googleapis.com/***redacted***" in out


def test_secret_query_params_masked(cli):
    out = cli.redact_secrets("curl 'https://api.example.com/x?token=abcd1234&key=zzzz9999&secret=hunter2pass'")
    assert "abcd1234" not in out
    assert "zzzz9999" not in out
    assert "hunter2pass" not in out
    assert out.count("***redacted***") >= 1


def test_live_secret_env_value_masked(cli, monkeypatch):
    monkeypatch.setenv("EXAMPLE_SAAS_ITERATION_REVIEW_GOOGLE_CHAT_WEBHOOK", "https://chat.googleapis.com/zzz/SUPERSECRETVALUE123")
    out = cli.redact_secrets("background-run -- publish --webhook https://chat.googleapis.com/zzz/SUPERSECRETVALUE123")
    assert "SUPERSECRETVALUE123" not in out


def test_non_secret_text_unchanged(cli):
    text = "minervit-methodology lane-start --target . && make preflight"
    assert cli.redact_secrets(text) == text


def test_empty_text_safe(cli):
    assert cli.redact_secrets("") == ""
