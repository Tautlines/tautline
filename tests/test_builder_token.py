"""The builder lane's IDENTITY: a GitHub App installation token, minted locally, cached, and
provably narrower than the human who launched the lane.

The point of this layer is not convenience. It is that a builder lane's writes are impossible to
mistake for a human's and impossible to widen from inside the lane: the App's configured permission
set grants Projects READ ONLY, so a board write is refused by GitHub itself no matter what the
harness allows. That claim is only worth something if an operator can VERIFY it, which is what
`tautline builder-token --status` prints and what these tests pin.

Every HTTP test is served at the SOCKET boundary (`urlopen` / `OpenerDirector.open`), reusing the
recorder the backlog provider suite already uses, so the assertions read the real URL, method,
headers and body this module builds. A test that stubbed this module's own `_request` would prove
only that the module agrees with itself -- and the request SHAPE (Bearer JWT, `application/
vnd.github+json`, the exact endpoint) is precisely what an identity layer has to get right.

The signing tests use a THROWAWAY RSA key generated into tmp_path by `openssl genrsa`. No fixture
key is committed: a private key in a repository is a private key that leaks, even a deliberately
worthless one, and the whole subject of this module is not leaking private keys.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from tautline_methodology import builder, builder_token
from test_backlog_providers import FakeHttp

APP_ID = "123456"
INSTALLATION_ID = 42
BOT_SLUG = "example-builder"
MINTED = "ghs_NOT_A_REAL_INSTALLATION_TOKEN_0123456789"

#: The permission set the App is configured with (docs/builder-lanes.md). `organization_projects`
#: at `read` is the ONE that carries the whole argument: a board write is refused by GitHub, not by
#: a hook, so it holds for every harness including ones this framework never sees.
GRANTED = {
    "contents": "write",
    "issues": "write",
    "metadata": "read",
    "pull_requests": "write",
    "organization_projects": "read",
}

LEAN_CFG = {
    "schemaVersion": "lean-1",
    "project": {"name": "Demo", "repo": "example-org/demo"},
    "integrationBranch": "main",
    "commands": {"test": "scripts/test.sh"},
}

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"


# ================================================================================================
# fixtures
# ================================================================================================


def _require_openssl() -> str:
    found = shutil.which("openssl")
    if not found:
        pytest.skip("openssl is not on PATH")
    return found


@pytest.fixture(scope="session")
def rsa_key(tmp_path_factory) -> Path:
    """A throwaway 2048-bit RSA key. Session-scoped: keygen is the slowest thing in this file."""
    openssl = _require_openssl()
    path = tmp_path_factory.mktemp("appkey") / "app.pem"
    subprocess.run(
        [openssl, "genrsa", "-out", str(path), "2048"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    path.chmod(0o600)
    return path


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    """The same socket-boundary recorder the backlog suite uses, imported rather than copied."""
    fake = FakeHttp()

    def _urlopen(request, *args, **kwargs):
        return fake.handle(request, kwargs.get("timeout", args[0] if args else None))

    def _open(self, request, *args, **kwargs):  # OpenerDirector.open
        return fake.handle(request, kwargs.get("timeout", args[0] if args else None))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _open)
    return fake


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch) -> Path:
    """A hermetic HOME, so the cache never touches the operator's real ~/.config."""
    root = tmp_path / "home"
    root.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(root))
    return root


def test_builder_tests_ignore_inherited_identity_and_leave_operator_cache_untouched(tmp_path):
    """Reproduce the five audit failures with synthetic credentials, never the operator's."""
    operator_home = tmp_path / "operator-home"
    cache = operator_home / builder_token.CACHE_RELPATH
    cache.parent.mkdir(parents=True)
    sentinel = "operator cache must remain untouched\n"
    cache.write_text(sentinel, encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "HOME": str(operator_home)}
    for prefix in ("TAUTLINE", "MINERVIT"):
        env.update({
            f"{prefix}_ROLE": "builder",
            f"{prefix}_GITHUB_APP_ID": "synthetic-inherited-app",
            f"{prefix}_GITHUB_APP_KEY": str(tmp_path / "not-an-operator-key"),
            f"{prefix}_GITHUB_APP_INSTALLATION_ID": "99",
        })
    env.update(GH_TOKEN="synthetic-inherited-token", GITHUB_TOKEN="synthetic-other-token")
    cases = [
        "test_builder_guard.py::test_an_unexpected_error_in_the_hook_denies_a_builder_rather_than_failing_open",
        "test_builder_token.py::test_only_print_writes_the_token_so_status_can_never_leak_it",
        "test_builder_github.py::test_no_token_refuses_and_names_the_environment_variables",
        "test_builder_github.py::test_the_gh_cli_is_the_last_credential_seam",
        "test_builder_token.py::test_the_emitted_token_line_refuses_rather_than_exporting_an_empty_gh_token",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", *(
            f"tests/{case}" for case in cases
        )],
        cwd=CLI_PATH.parents[1], env=env, text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 passed" in result.stdout
    assert "synthetic-inherited-token" not in result.stdout + result.stderr
    assert cache.read_text(encoding="utf-8") == sentinel


@pytest.fixture
def app_env(monkeypatch, rsa_key) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv(builder_token.APP_ID_ENV, APP_ID)
    monkeypatch.setenv(builder_token.APP_KEY_ENV, str(rsa_key))
    monkeypatch.setenv(builder_token.INSTALLATION_ID_ENV, str(INSTALLATION_ID))


@pytest.fixture
def run_cli(tmp_path):
    """conftest's black-box runner, plus `env_extra`.

    This subsystem's whole subject is what the ENVIRONMENT says -- three App variables, GH_TOKEN,
    TAUTLINE_ROLE -- and the shared runner builds a fixed `{PATH, HOME}` env on purpose, so
    `monkeypatch.setenv` in a test never reaches the subprocess. Shadowing the fixture here keeps
    that hermetic default and adds the one knob these tests need, rather than widening the runner
    every other suite depends on.
    """

    def _run(*args, stdin=None, cwd=None, env_extra=None):
        hermetic_home = tmp_path / "home"
        hermetic_home.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "HOME": str(hermetic_home)}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            input=stdin,
            env=env,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=60,
        )

    return _run


def _route_mint(
    fake: FakeHttp, installation_id: int = INSTALLATION_ID, expires_in: int = 3600
) -> FakeHttp:
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in))
    return fake.route(
        f"POST /app/installations/{installation_id}/access_tokens",
        {"token": MINTED, "expires_at": expires_at, "permissions": GRANTED},
    )


def _project(root: Path, cfg: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".tautline.json").write_text(json.dumps(cfg or LEAN_CFG), encoding="utf-8")
    return root


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ================================================================================================
# the JWT: the one piece of cryptography here, and the one that must not be hand-waved
# ================================================================================================


def test_jwt_carries_the_rs256_header_and_the_app_claims(rsa_key):
    """RS256, `iss` = the app id, and a SHORT life clamped below GitHub's 10-minute ceiling.

    `iat` is backdated 60s on purpose: GitHub rejects a JWT whose `iat` is in the future by even a
    second, and a lane's clock is not synchronised with GitHub's.
    """
    before = int(time.time())
    token = builder_token.build_jwt(APP_ID, rsa_key)
    after = int(time.time())

    header_segment, payload_segment, signature_segment = token.split(".")
    header = json.loads(_b64url_decode(header_segment))
    payload = json.loads(_b64url_decode(payload_segment))

    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload["iss"] == APP_ID
    assert before - 61 <= payload["iat"] <= after - 59
    assert payload["exp"] - payload["iat"] == 600, "60s backdate + 540s ahead = a 10-minute window"
    assert payload["exp"] - after <= 540

    for segment in (header_segment, payload_segment, signature_segment):
        assert "=" not in segment, "base64url in a JWT is UNPADDED"
        assert "+" not in segment and "/" not in segment, "base64url, not standard base64"


def test_jwt_signature_verifies_against_the_public_key(rsa_key, tmp_path):
    """The signature is a real RS256 signature over `header.payload`, checked by openssl itself.

    Asserting only on the SHAPE of the third segment would pass for any random bytes, and a JWT
    GitHub rejects is a lane that cannot authenticate for a reason nothing here would explain.
    """
    openssl = _require_openssl()
    token = builder_token.build_jwt(APP_ID, rsa_key)
    signing_input, _, signature_segment = token.rpartition(".")

    public_key = tmp_path / "app.pub"
    subprocess.run(
        [openssl, "rsa", "-in", str(rsa_key), "-pubout", "-out", str(public_key)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    signature = tmp_path / "sig.bin"
    signature.write_bytes(_b64url_decode(signature_segment))

    verified = subprocess.run(
        [openssl, "dgst", "-sha256", "-verify", str(public_key), "-signature", str(signature)],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
    )
    assert verified.returncode == 0, verified.stderr.decode("utf-8", "replace")


def test_an_unreadable_private_key_is_refused_by_name(tmp_path):
    missing = tmp_path / "absent.pem"
    with pytest.raises(builder_token.BuilderTokenError) as exc:
        builder_token.build_jwt(APP_ID, missing)
    message = str(exc.value)
    assert builder_token.APP_KEY_ENV in message, "the refusal must name the variable to fix"
    assert str(missing) in message


def test_a_missing_openssl_is_refused_before_any_signing(monkeypatch, tmp_path, rsa_key):
    """`openssl` is the ONE external binary this module needs; its absence is a config problem with
    a one-line fix, not a traceback. An empty PATH is the honest way to ask -- patching `shutil`
    itself would prove only that the patch worked."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(builder_token.BuilderTokenError) as exc:
        builder_token.build_jwt(APP_ID, rsa_key)
    assert "openssl" in str(exc.value).lower()


def test_the_private_key_never_reaches_the_signing_subprocesss_argv(monkeypatch, rsa_key):
    """The PEM is passed by PATH, never by content: argv is world-readable in `ps`."""
    seen: dict = {}
    real_run = subprocess.run

    class _Spy:
        @staticmethod
        def run(command, **kwargs):
            seen["command"] = list(command)
            return real_run(command, **kwargs)

    # Patched on the MODULE's namespace, not on `subprocess` itself: replacing the real
    # `subprocess.run` process-wide would reach every other test sharing this worker.
    monkeypatch.setattr(builder_token, "subprocess", _Spy)
    builder_token.build_jwt(APP_ID, rsa_key)

    key_text = rsa_key.read_text(encoding="utf-8")
    joined = " ".join(seen["command"])
    assert "PRIVATE KEY" not in joined
    assert key_text not in joined
    assert str(rsa_key) in seen["command"]


# ================================================================================================
# installation discovery
# ================================================================================================


def test_discovery_asks_the_app_installations_endpoint_with_the_jwt(http, rsa_key):
    http.route(
        "GET /app/installations",
        [
            {"id": 7, "account": {"login": "someone-else"}},
            {"id": INSTALLATION_ID, "account": {"login": "example-org"}},
        ],
    )
    assert builder_token.discover_installation_id(APP_ID, rsa_key, "example-org") == INSTALLATION_ID

    call = http.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.github.com/app/installations"
    assert call["headers"]["Accept"] == "application/vnd.github+json"
    assert call["headers"]["Authorization"].startswith("Bearer ")
    assert call["headers"]["Authorization"].count(".") == 2, "a JWT, not an installation token"


def test_discovery_matches_the_owner_case_insensitively(http, rsa_key):
    http.route("GET /app/installations", [{"id": 9, "account": {"login": "Example-Org"}}])
    assert builder_token.discover_installation_id(APP_ID, rsa_key, "example-org") == 9


def test_discovery_refuses_when_no_installation_matches_and_lists_the_candidates(http, rsa_key):
    http.route(
        "GET /app/installations",
        [{"id": 7, "account": {"login": "other-org"}}, {"id": 8, "account": {"login": "third-org"}}],
    )
    with pytest.raises(builder_token.BuilderTokenError) as exc:
        builder_token.discover_installation_id(APP_ID, rsa_key, "example-org")
    message = str(exc.value)
    assert "example-org" in message
    assert "other-org" in message and "third-org" in message, "name the candidates it DID see"
    assert builder_token.INSTALLATION_ID_ENV in message, "and the way to settle it by hand"


def test_discovery_refuses_an_ambiguous_match_rather_than_picking_one(http, rsa_key):
    """Two installations on one owner is not a situation to guess at: minting against the wrong one
    yields a token with the wrong repository access, and the failure surfaces much later as a 404
    on an endpoint that looks correct."""
    http.route(
        "GET /app/installations",
        [
            {"id": 11, "account": {"login": "example-org"}},
            {"id": 12, "account": {"login": "example-org"}},
        ],
    )
    with pytest.raises(builder_token.BuilderTokenError) as exc:
        builder_token.discover_installation_id(APP_ID, rsa_key, "example-org")
    message = str(exc.value)
    assert "11" in message and "12" in message
    assert builder_token.INSTALLATION_ID_ENV in message


# ================================================================================================
# the exchange
# ================================================================================================


def test_the_exchange_posts_to_the_installations_access_tokens_endpoint(http, rsa_key):
    _route_mint(http)
    minted = builder_token.mint_installation_token(APP_ID, rsa_key, INSTALLATION_ID)

    assert minted.token.reveal() == MINTED
    assert minted.permissions == GRANTED

    call = http.calls[0]
    assert call["method"] == "POST"
    assert (
        call["url"] == f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens"
    )
    assert call["headers"]["Accept"] == "application/vnd.github+json"
    assert call["headers"]["Authorization"].startswith("Bearer ")
    assert call["headers"]["Authorization"].count(".") == 2, "the JWT authenticates the exchange"


def test_the_exchange_does_not_narrow_the_apps_configured_permissions(http, rsa_key):
    """No `permissions` in the body, deliberately.

    Narrowing at mint time would move the scope claim from the App's settings page -- which an
    operator can read, and which `--status` proves against -- into this code, where a lane would be
    trusted to restrict itself. The whole argument for the App is that it does not rely on that.
    """
    _route_mint(http)
    builder_token.mint_installation_token(APP_ID, rsa_key, INSTALLATION_ID)
    body = http.calls[0]["body"]
    assert body is None or "permissions" not in body


def test_the_minted_token_redacts_itself_when_printed(http, rsa_key):
    """It is a `Secret`, the same type the backlog seam and the Jira client carry, so an error
    reporter dumping locals renders `<redacted>` instead of a live installation token."""
    _route_mint(http)
    minted = builder_token.mint_installation_token(APP_ID, rsa_key, INSTALLATION_ID)
    assert MINTED not in repr(minted.token)
    assert MINTED not in str(minted.token)


def test_the_transport_refuses_a_redirect_rather_than_replaying_the_credential():
    """Same posture as the backlog seam: urllib re-sends `Authorization` across a redirect, and a
    302 to a hostile host would be handed a JWT that can mint tokens for the whole installation."""
    with pytest.raises(builder_token.BuilderTokenError, match="Authorization"):
        builder_token._RefuseRedirect().redirect_request(
            urllib.request.Request("https://api.github.com/app"), None, 302, "F", {}, "https://evil"
        )


def test_the_refusal_is_installed_in_the_opener_this_module_actually_uses():
    """A handler that refuses but is never wired in is a guard that cannot fire."""
    opener = builder_token._build_opener()
    assert any(
        isinstance(handler, builder_token._RefuseRedirect) for handler in opener.handlers
    ), "the redirect refusal must be INSTALLED, not merely defined"


def test_this_module_never_calls_urlopen_directly():
    """The other half: a call to `urlopen` bypasses the opener carrying the refusal entirely."""
    source = Path(builder_token.__file__).read_text(encoding="utf-8")
    assert "urlopen(" not in source


def test_the_credential_is_never_sent_anywhere_but_the_github_api():
    with pytest.raises(builder_token.BuilderTokenError, match="api.github.com"):
        builder_token._request("GET", "https://evil.example/app", jwt="x.y.z")


# ================================================================================================
# the cache
# ================================================================================================


def test_the_cache_is_written_private_to_this_user(http, home, rsa_key):
    _route_mint(http)
    builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)

    path = builder_token.cache_path()
    assert path == home / ".config" / "minervit" / "builder-token.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600, "an installation token is a credential"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(record) >= {"token", "expires_at", "installation_id", "app_id"}
    assert record["token"] == MINTED
    assert record["installation_id"] == INSTALLATION_ID
    assert record["app_id"] == APP_ID


def test_writing_the_cache_does_not_re_permission_a_directory_it_shares(http, home, rsa_key):
    """`~/.config/minervit` is the framework's SHARED config directory -- `methodology.env` lives
    there, and so does anything a future verb puts beside it. This module chmod'ed it to 0700 on
    every cache write, which silently changed the permissions of somebody else's files because
    one of them happened to be a token. Owning a file in a directory is not owning the directory.

    The file's own 0600 is the control that matters, and it is unchanged. A directory this module
    CREATES is still created private, because at that moment it does own it.
    """
    shared = builder_token.cache_path().parent
    shared.mkdir(parents=True, exist_ok=True)
    shared.chmod(0o755)
    (shared / "methodology.env").write_text("# somebody else's file\n", encoding="utf-8")

    _route_mint(http)
    builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)

    assert stat.S_IMODE(shared.stat().st_mode) == 0o755, "the shared directory was re-permissioned"
    assert stat.S_IMODE(builder_token.cache_path().stat().st_mode) == 0o600


def test_a_world_readable_app_key_warns_and_still_signs(rsa_key, tmp_path, capsys):
    """A private key at 0644 is a key any local process can read and mint installation tokens
    with -- the credential this whole module exists to keep narrow. It is worth SAYING so.

    It is not worth refusing over. A refusal here breaks a lane that is working, at a moment the
    operator did not choose, over a file they can fix in one command; and a control that stops
    somebody's work over a warning-grade fact is a control they will disable.
    """
    loose = tmp_path / "loose.pem"
    loose.write_bytes(rsa_key.read_bytes())
    loose.chmod(0o644)

    signature = builder_token._sign_rs256(b"payload", loose)
    assert signature, "the signature is still produced -- this is a warning, not a refusal"
    err = capsys.readouterr().err
    assert "builder_token_warning" in err
    assert str(loose) in err
    assert "0644" in err or "644" in err


def test_a_private_app_key_says_nothing(rsa_key, capsys):
    builder_token._sign_rs256(b"payload", rsa_key)
    assert capsys.readouterr().err == ""


def test_a_cached_token_with_time_left_is_reused_without_a_second_mint(http, home, rsa_key):
    _route_mint(http)
    first = builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)
    assert len(http.calls) == 1

    second = builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)
    assert second.token.reveal() == first.token.reveal()
    assert len(http.calls) == 1, "a valid cached token must not cost a request"


def test_a_token_inside_the_refresh_margin_is_reminted(http, home, rsa_key):
    """Five minutes of headroom, not zero: a token that expires DURING the command that reused it
    fails halfway through a write, which is the worst possible moment to discover it."""
    _route_mint(http, expires_in=builder_token.REFRESH_MARGIN_SECONDS - 30)
    builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)
    assert len(http.calls) == 1

    _route_mint(http, expires_in=3600)
    builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)
    assert len(http.calls) == 2, "a token about to expire must be replaced, not handed out"


def test_a_cache_minted_for_a_different_installation_is_not_reused(http, home, rsa_key):
    _route_mint(http)
    builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID)
    _route_mint(http, installation_id=99)
    builder_token.mint_and_cache(APP_ID, rsa_key, 99)
    assert len(http.calls) == 2, "the cache is keyed by app + installation, not by file existence"


def test_a_corrupt_cache_is_re_minted_rather_than_raising(http, home, rsa_key):
    path = builder_token.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    _route_mint(http)
    assert builder_token.mint_and_cache(APP_ID, rsa_key, INSTALLATION_ID).token.reveal() == MINTED


# ================================================================================================
# github_token: the seam the verbs call
# ================================================================================================


def test_github_token_prefers_gh_token_over_everything(monkeypatch, home, app_env, http):
    monkeypatch.setenv("GH_TOKEN", "gh-token-value")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
    assert builder_token.github_token(LEAN_CFG) == "gh-token-value"
    assert not http.calls, "an operator-supplied token must not cost a mint"


def test_github_token_falls_back_to_github_token(monkeypatch, home, app_env, http):
    monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
    assert builder_token.github_token(LEAN_CFG) == "github-token-value"
    assert not http.calls


def test_github_token_mints_from_the_app_when_no_token_is_exported(home, app_env, http):
    _route_mint(http)
    assert builder_token.github_token(LEAN_CFG) == MINTED


def test_github_token_is_empty_when_nothing_is_configured(monkeypatch, home, http):
    """Empty, not an error: the caller falls back to `gh auth token`, which is exactly right for a
    HUMAN running the same verb. A refusal here would break every human on every machine."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN", builder_token.APP_ID_ENV, builder_token.APP_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    assert builder_token.github_token(LEAN_CFG) == ""
    assert not http.calls


def test_github_token_discovers_the_installation_from_the_repo_owner(
    monkeypatch, home, app_env, http
):
    monkeypatch.delenv(builder_token.INSTALLATION_ID_ENV, raising=False)
    http.route(
        "GET /app/installations", [{"id": INSTALLATION_ID, "account": {"login": "example-org"}}]
    )
    _route_mint(http)
    assert builder_token.github_token(LEAN_CFG) == MINTED
    assert http.calls[0]["path"] == "/app/installations"


def test_discovery_without_a_repo_in_the_config_names_the_two_ways_to_fix_it(
    monkeypatch, home, app_env, http
):
    monkeypatch.delenv(builder_token.INSTALLATION_ID_ENV, raising=False)
    with pytest.raises(builder_token.BuilderTokenError) as exc:
        builder_token.github_token({"schemaVersion": "lean-1", "project": {"name": "Demo"}})
    message = str(exc.value)
    assert "project.repo" in message
    assert builder_token.INSTALLATION_ID_ENV in message
    assert not http.calls


def test_builder_exposes_github_token_without_an_import_cycle():
    """Lane A's `_token()` calls `builder.github_token`. `builder` is imported BY the feature
    modules, so the re-export has to be lazy -- and a lazy re-export is exactly the kind of thing
    that is written once and never exercised."""
    assert builder.github_token({"project": {"repo": "example-org/demo"}}, environ={}) == ""


# ================================================================================================
# `tautline builder-token`
# ================================================================================================


def test_print_writes_exactly_the_token_and_nothing_else(run_cli, tmp_path):
    """`GH_TOKEN="$(tautline builder-token --print)"` is the documented use. One stray line of
    chatter on
    stdout and the exported variable is garbage -- and the failure shows up as a 401 somewhere
    else entirely."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--print", "--target", str(target),
        cwd=target, env_extra={"GH_TOKEN": "gh-token-value"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "gh-token-value\n"


def test_a_bare_builder_token_refuses_rather_than_printing_a_live_credential(run_cli, tmp_path):
    """PRINTING A CREDENTIAL IS A DECISION, and it has to be asked for.

    `--print` was registered and never read, so `tautline builder-token` with no flag at all
    printed a live installation token. That is the shape somebody types while exploring a new
    verb -- and the shape a `--help`-guess produces -- and it puts the credential in the terminal
    scrollback, the shell history's output pane, and any transcript the session keeps. `--status`
    exists precisely because "tell me about the identity" is the common question; the answer to it
    must not be the credential itself.
    """
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--target", str(target),
        cwd=target, env_extra={"GH_TOKEN": "gh-token-value"},
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert result.stdout == "", result.stdout
    assert "gh-token-value" not in result.stdout + result.stderr
    # The refusal names the door, both halves of it: a message that says "no" without saying
    # "--print" sends the reader back to `--help` for a fact this line already knows.
    assert "--print" in result.stderr
    assert "--status" in result.stderr
    assert "Traceback" not in result.stderr


def test_print_with_no_identity_refuses_rather_than_printing_an_empty_line(run_cli, tmp_path):
    """An empty stdout would be captured into `GH_TOKEN=""`, which silences `gh`'s own fallback to
    the operator's login and turns a missing-config problem into an opaque 401."""
    target = _project(tmp_path / "proj")
    result = run_cli("builder-token", "--print", "--target", str(target), cwd=target)
    assert result.returncode == 1
    assert result.stdout.strip() == ""
    assert builder_token.APP_ID_ENV in result.stderr
    assert "Traceback" not in result.stderr


def test_status_reports_the_source_without_ever_printing_the_token(run_cli, tmp_path):
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--status", "--target", str(target),
        cwd=target, env_extra={"GH_TOKEN": "gh-token-value"},
    )
    assert result.returncode == 0, result.stderr
    assert "gh-token-value" not in result.stdout
    assert "gh-token-value" not in result.stderr
    assert "builder_token_source: env" in result.stdout
    assert "GH_TOKEN" in result.stdout


def test_status_with_nothing_configured_names_the_three_variables(run_cli, tmp_path):
    target = _project(tmp_path / "proj")
    result = run_cli("builder-token", "--status", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr
    assert "builder_token_source: none" in result.stdout
    for name in (
        builder_token.APP_ID_ENV,
        builder_token.APP_KEY_ENV,
        builder_token.INSTALLATION_ID_ENV,
    ):
        assert name in result.stdout


def test_status_prints_the_granted_permissions_so_projects_read_only_is_provable(
    http, home, app_env, tmp_path, capsys
):
    """THE proof step. An operator who cannot see `organization_projects: read` has no evidence
    that a builder lane is unable to move a board -- only an assurance."""
    target = _project(tmp_path / "proj")
    http.route("GET /app", {"slug": BOT_SLUG, "id": int(APP_ID)})
    _route_mint(http)

    exit_code = builder_token.builder_token_command(
        _args(target=target, status=True, print_token=False)
    )
    assert exit_code == 0

    out = capsys.readouterr().out
    assert MINTED not in out
    assert "builder_token_source: app" in out
    assert f"builder_token_bot_login: {BOT_SLUG}[bot]" in out
    assert f"builder_token_installation_id: {INSTALLATION_ID}" in out
    assert f"builder_token_app_id: {APP_ID}" in out
    assert "organization_projects=read" in out
    assert "issues=write" in out


def test_a_missing_pem_refuses_with_a_message_and_no_traceback(run_cli, tmp_path):
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--print", "--target", str(target), cwd=target,
        env_extra={
            builder_token.APP_ID_ENV: APP_ID,
            builder_token.APP_KEY_ENV: str(tmp_path / "absent.pem"),
            builder_token.INSTALLATION_ID_ENV: str(INSTALLATION_ID),
        },
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert builder_token.APP_KEY_ENV in result.stdout + result.stderr


def test_only_print_writes_the_token_so_status_can_never_leak_it(http, app_env, tmp_path, capsys):
    """The pair of promises, asserted on the App path where the token is a REAL minted one rather
    than an environment string: `--status` prints the identity and never the credential, and the
    credential comes out of exactly one flag."""
    target = _project(tmp_path / "proj")
    http.route("GET /app", {"slug": BOT_SLUG, "id": int(APP_ID)})
    _route_mint(http)

    assert builder_token.builder_token_command(
        _args(target=target, status=True, print_token=False)
    ) == 0
    status_out = capsys.readouterr().out
    assert MINTED not in status_out

    assert builder_token.builder_token_command(
        _args(target=target, status=False, print_token=True)
    ) == 0
    assert capsys.readouterr().out == f"{MINTED}\n"


def test_print_and_status_are_mutually_exclusive(run_cli, tmp_path):
    """`--print` writes a bare credential and `--status` promises never to; a single invocation
    cannot honour both, and silently letting one win is how a token ends up in a status log."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--print", "--status", "--target", str(target), cwd=target
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# ================================================================================================
# `tautline lane-role`
# ================================================================================================


def test_lane_role_builder_writes_the_marker_the_shared_contract_reads(run_cli, tmp_path):
    """Written by THIS verb, read by `builder.builder_role_active` -- the one place the role lives.
    Asserting the file's bytes here and calling the contract's own reader is what keeps the writer
    and the reader from drifting into two different spellings of `builder`."""
    target = tmp_path / "proj"
    target.mkdir()
    result = run_cli("lane-role", "builder", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr

    marker = target / builder.ROLE_FILE
    assert marker.read_text(encoding="utf-8").strip() == "builder"
    assert builder.builder_role_active(target, environ={}) is True


def test_lane_role_human_removes_the_marker(run_cli, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    run_cli("lane-role", "builder", "--target", str(target), cwd=target)
    result = run_cli("lane-role", "human", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr
    assert not (target / builder.ROLE_FILE).exists()
    assert builder.builder_role_active(target, environ={}) is False


def test_lane_role_human_on_a_lane_that_was_never_a_builder_is_a_no_op(run_cli, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    result = run_cli("lane-role", "human", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr


def test_lane_role_status_names_the_marker_that_decided_it(run_cli, tmp_path):
    """Which marker is the whole question when a lane behaves unexpectedly: an inherited
    TAUTLINE_ROLE from a parent shell and a file written last week look identical from the
    outside, and they are undone in completely different ways."""
    target = tmp_path / "proj"
    target.mkdir()

    default = run_cli("lane-role", "status", "--target", str(target), cwd=target)
    assert "lane_role: human" in default.stdout
    assert "default" in default.stdout

    run_cli("lane-role", "builder", "--target", str(target), cwd=target)
    from_file = run_cli("lane-role", "status", "--target", str(target), cwd=target)
    assert "lane_role: builder" in from_file.stdout
    assert str(builder.ROLE_FILE) in from_file.stdout


def test_lane_role_status_reports_the_env_marker_even_without_a_file(run_cli, tmp_path):
    """The env marker OUTRANKS the file, and says so: a machine-wide `TAUTLINE_ROLE=builder` is
    not undone by `tautline lane-role human`, and an operator who is not told that will try."""
    target = tmp_path / "proj"
    target.mkdir()
    result = run_cli(
        "lane-role", "status", "--target", str(target), cwd=target,
        env_extra={builder.ROLE_ENV: "builder"},
    )
    assert "lane_role: builder" in result.stdout
    assert builder.ROLE_ENV in result.stdout


def test_lane_role_builder_gitignores_the_marker(run_cli, tmp_path):
    """A committed `.ai-work/lane-role` would make every clone of that branch a builder lane --
    including the human's. The role is per-checkout state, so it must never be committable."""
    target = tmp_path / "proj"
    target.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)

    run_cli("lane-role", "builder", "--target", str(target), cwd=target)

    ignored = subprocess.run(
        ["git", "check-ignore", str(builder.ROLE_FILE)],
        cwd=target,
        capture_output=True,
        text=True,
    )
    gitignore = target / ".gitignore"
    assert ignored.returncode == 0, (
        ".ai-work/lane-role is not ignored; .gitignore is:\n"
        + (gitignore.read_text(encoding="utf-8") if gitignore.exists() else "(absent)")
    )


def test_lane_role_builder_does_not_duplicate_an_existing_ignore_rule(run_cli, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    (target / ".gitignore").write_text(".ai-work/\n", encoding="utf-8")

    run_cli("lane-role", "builder", "--target", str(target), cwd=target)
    run_cli("lane-role", "builder", "--target", str(target), cwd=target)

    text = (target / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".ai-work/") == 1


def test_lane_role_outside_a_git_checkout_still_writes_the_marker(run_cli, tmp_path):
    """The ignore rule is a courtesy; the role is the job. A directory that is not a git checkout
    (a scratch target, a container mount) must not lose its role because there is nothing to
    ignore it in."""
    target = tmp_path / "loose"
    target.mkdir()
    result = run_cli("lane-role", "builder", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr
    assert (target / builder.ROLE_FILE).is_file()


# ================================================================================================
# `tautline builder-env`
# ================================================================================================


def test_builder_env_prints_the_three_things_a_lane_evals(run_cli, tmp_path):
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    )
    assert result.returncode == 0, result.stderr
    assert f"export {builder.ROLE_ENV}=builder" in result.stdout.splitlines()
    assert "tautline builder-token --print" in result.stdout
    assert "tautline builder-guard --shim-dir" in result.stdout
    assert "export GH_TOKEN=" in result.stdout
    assert "export PATH=" in result.stdout


def _eval_snippet(snippet: str, fake_bin: Path) -> subprocess.CompletedProcess:
    """Run the emitted snippet under `sh` with a fake `tautline` first on PATH, and report back
    what the resulting environment looks like. `PATH` is echoed with the fake dir stripped so the
    assertion can be about what the snippet ADDED, not about the machine it ran on."""
    script = (
        f'PATH={shlex.quote(str(fake_bin))}:/usr/bin:/bin\n'
        f"{snippet}\n"
        'printf "PATH=%s\\n" "$PATH"\n'
        'printf "GH_TOKEN=[%s]\\n" "${GH_TOKEN-<unset>}"\n'
    )
    return subprocess.run(
        ["sh"], input=script, text=True, capture_output=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(fake_bin.parent / "home")},
    )


def _fake_tautline(tmp_path: Path, body: str) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "tautline"
    fake.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    fake.chmod(0o755)
    return bin_dir


def test_the_emitted_path_line_leaves_path_alone_when_the_shim_command_fails(run_cli, tmp_path):
    """`export PATH="$(tautline builder-guard --shim-dir):$PATH"` puts the EMPTY STRING at the
    front of PATH when the substitution fails -- and an empty PATH entry means the current
    directory. Every command the lane then runs is resolved against `.` first, so a file called
    `git` in a checked-out repository runs instead of git. The snippet must add a directory or add
    nothing."""
    target = _project(tmp_path / "proj")
    emitted = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    ).stdout
    fake_bin = _fake_tautline(tmp_path, 'echo "tautline: unknown verb" >&2\nexit 2')
    result = _eval_snippet(emitted, fake_bin)
    assert result.returncode == 0, result.stderr
    path_line = next(
        line for line in result.stdout.splitlines() if line.startswith("PATH=")
    )
    value = path_line[len("PATH=") :]
    assert value == f"{fake_bin}:/usr/bin:/bin", value
    assert not value.startswith(":"), "an empty leading PATH entry is the current directory"


def test_the_emitted_token_line_refuses_rather_than_exporting_an_empty_gh_token(run_cli, tmp_path):
    """`export GH_TOKEN="$(tautline builder-token --print)"` exports an EMPTY GH_TOKEN when the
    mint fails at eval time -- and an exported-but-empty GH_TOKEN stops `gh` falling back to the
    operator's own login, turning a mint failure into an opaque 401 in some later command. The
    same reasoning already governed the GENERATION-time check; this is the EVAL-time one, and the
    two failures are minutes apart in a lane launch."""
    target = _project(tmp_path / "proj")
    emitted = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    ).stdout
    fake_bin = _fake_tautline(tmp_path, 'echo "builder_token_error: no identity" >&2\nexit 1')
    result = _eval_snippet(emitted, fake_bin)
    assert "GH_TOKEN=[<unset>]" in result.stdout, result.stdout
    assert "refusing to start a builder lane" in result.stderr, result.stderr


def test_the_emitted_snippet_exports_what_the_commands_return_when_they_succeed(run_cli, tmp_path):
    """The other direction: a snippet that fails safe but never succeeds is not a fix."""
    target = _project(tmp_path / "proj")
    emitted = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    ).stdout
    fake_bin = _fake_tautline(
        tmp_path,
        'case "$2" in\n'
        "  --print) echo minted-token-value ;;\n"
        "  --shim-dir) echo /opt/shim ;;\n"
        "  *) exit 1 ;;\n"
        "esac",
    )
    result = _eval_snippet(emitted, fake_bin)
    assert result.returncode == 0, result.stderr
    assert "GH_TOKEN=[minted-token-value]" in result.stdout
    assert f"PATH=/opt/shim:{fake_bin}:/usr/bin:/bin" in result.stdout


def test_builder_env_never_expands_the_token_itself(run_cli, tmp_path):
    """The snippet is TEXT for the operator's shell to expand. Substituting a live token here
    would put a credential into shell history, into any log the operator pastes, and into the
    terminal scrollback of a screen share."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    )
    assert "gh-token-value" not in result.stdout


def test_builder_env_says_so_rather_than_exporting_an_empty_token(run_cli, tmp_path):
    """A `GH_TOKEN` line emitted with nothing configured would be a line that cannot work: the
    lane pays a process to be told what this verb already knows. The EVAL-time half of the same
    reasoning -- a mint that fails when the snippet is run -- is pinned separately below."""
    target = _project(tmp_path / "proj")
    result = run_cli("builder-env", "--target", str(target), cwd=target)
    assert result.returncode == 0, result.stderr
    assert "tautline builder-token --print" not in result.stdout
    assert "# no builder identity is configured" in result.stdout
    assert builder_token.APP_ID_ENV in result.stdout
    assert f"export {builder.ROLE_ENV}=builder" in result.stdout


def test_builder_env_emits_the_token_line_when_the_app_is_configured(run_cli, tmp_path, rsa_key):
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={
            builder_token.APP_ID_ENV: APP_ID,
            builder_token.APP_KEY_ENV: str(rsa_key),
        },
    )
    assert builder_token.GH_TOKEN_SNIPPET in result.stdout


def test_builder_env_output_is_evalable_shell(run_cli, tmp_path):
    """`eval "$(tautline builder-env)"` is the documented launch. A snippet with a syntax error
    takes the whole shell down with it. Parsed only (`sh -n`) -- the PATH line calls a subcommand
    another lane owns, and running it here would couple this suite to that lane's progress."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={"GH_TOKEN": "gh-token-value"},
    )
    checked = subprocess.run(
        ["sh", "-n"], input=result.stdout, text=True, capture_output=True, timeout=30
    )
    assert checked.returncode == 0, checked.stderr


def test_builder_env_prints_for_a_human_lane_too(run_cli, tmp_path):
    """builder-env is how a lane BECOMES a builder, so refusing when the lane is not one yet would
    make it impossible to use. The document, not the code, is what tells a human not to eval it."""
    target = _project(tmp_path / "proj")
    result = run_cli("builder-env", "--target", str(target), cwd=target)
    assert result.returncode == 0
    assert f"export {builder.ROLE_ENV}=builder" in result.stdout


# ================================================================================================
# documentation and packaging promises
# ================================================================================================


DOC = Path(__file__).resolve().parents[1] / "docs" / "builder-lanes.md"
DOCS_INDEX = Path(__file__).resolve().parents[1] / "docs" / "README.md"


def test_the_builder_lane_page_exists_and_is_reachable_from_the_docs_index():
    assert DOC.is_file()
    assert "builder-lanes.md" in DOCS_INDEX.read_text(encoding="utf-8"), (
        "an unreferenced page is a page nobody finds"
    )


def test_the_page_documents_the_exact_permission_set_and_the_proof_command():
    text = DOC.read_text(encoding="utf-8")
    for phrase in (
        "Issues: Read and write",
        "Pull requests: Read and write",
        "Contents: Read and write",
        "Metadata: Read-only",
        "Workflows: Read and write",
        "Projects: Read-only",
        "tautline builder-token --status",
        builder_token.APP_ID_ENV,
        builder_token.APP_KEY_ENV,
        builder_token.INSTALLATION_ID_ENV,
        'eval "$(tautline builder-env)"',
        "tautline lane-role builder",
        f"export {builder.ROLE_ENV}=builder",
        "0600",
    ):
        assert phrase in text, f"docs/builder-lanes.md must document {phrase!r}"


def test_the_page_tells_a_human_not_to_eval_the_builder_snippet():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "never" in text and "human" in text


def test_install_cli_offers_the_role_line_commented_rather_than_setting_it(run_cli, tmp_path):
    """A machine-wide role is a DECISION, and install-cli runs on every machine including the
    operator's own. Writing a live `TAUTLINE_ROLE=builder` there would silently convert a human's
    laptop into a builder-only machine."""
    result = run_cli("install-cli")
    assert result.returncode == 0, result.stderr

    home_dir = tmp_path / "home"
    written = [
        path
        for path in (
            home_dir / ".config" / "tautline" / "tautline.env",
            home_dir / ".config" / "minervit" / "methodology.env",
        )
        if path.is_file()
    ]
    assert written, "install-cli wrote no env file"
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert f"# export {builder.ROLE_ENV}=builder" in text
        assert not any(
            line.strip().startswith(f"export {builder.ROLE_ENV}=")
            for line in text.splitlines()
        ), "the role line must be an EXAMPLE, never a live export"


def test_a_malformed_installation_id_refuses_without_a_traceback(run_cli, tmp_path, rsa_key):
    """An operator typo in one environment variable must not answer with a stack trace."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-token", "--print", "--target", str(target), cwd=target,
        env_extra={
            builder_token.APP_ID_ENV: APP_ID,
            builder_token.APP_KEY_ENV: str(rsa_key),
            builder_token.INSTALLATION_ID_ENV: "not-a-number",
        },
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert builder_token.INSTALLATION_ID_ENV in result.stderr


def test_builder_env_still_emits_the_role_line_when_the_identity_is_misconfigured(
    run_cli, tmp_path, rsa_key
):
    """The role line comes first and depends on no configuration at all. A lane that gets NO
    snippet because one variable has a typo in it is a worse outcome than a lane that takes the
    role and reads a comment explaining the rest."""
    target = _project(tmp_path / "proj")
    result = run_cli(
        "builder-env", "--target", str(target), cwd=target,
        env_extra={
            builder_token.APP_ID_ENV: APP_ID,
            builder_token.APP_KEY_ENV: str(rsa_key),
            builder_token.INSTALLATION_ID_ENV: "not-a-number",
        },
    )
    assert result.returncode == 0, result.stderr
    assert f"export {builder.ROLE_ENV}=builder" in result.stdout
    assert "Traceback" not in result.stderr
    checked = subprocess.run(
        ["sh", "-n"], input=result.stdout, text=True, capture_output=True, timeout=30
    )
    assert checked.returncode == 0, "a snippet with a diagnostic in it is still evalable shell"
