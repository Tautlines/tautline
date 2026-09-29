"""The builder lane's IDENTITY: mint, cache and prove a GitHub App installation token.

`builder.py` answers *who is a builder*. `builder_guard` answers *which commands a builder may
run*. This module answers the question underneath both: **as whom does a builder lane act, and how
narrow is that identity really?**

A build agent does not use the operator's GitHub credentials. It acts as a GitHub App
installation -- `<app-slug>[bot]` -- whose configured permission set is Issues RW, Pull requests RW,
Contents RW, Metadata R, Workflows RW, and Organization Projects **READ**. Two things follow, and
they are the whole reason this module exists:

* a board write is refused by GITHUB, not by a hook. It is impossible from a builder lane in any
  harness -- Claude, Codex, a bare shell, an orchestrator this framework has never seen -- because
  the token itself cannot do it. A guard can be bypassed; a permission cannot be talked around.
* every builder write is attributed to the bot, so reading the repository tells you which writes
  came from a lane and which came from a person, without trusting a commit trailer.

CONFIGURATION IS ENVIRONMENT-ONLY. The three variables below are never read from the committed
adapter, because the adapter is in a repository and an App private key is a credential that can
mint tokens for the whole installation. `resolve_env` is the framework's single env chokepoint and
this module reads through it exclusively.

SIGNING IS SHELLED OUT to `openssl`. The runtime is stdlib-only, RS256 needs RSA-PKCS1-v1_5 over
SHA-256, and `openssl dgst -sha256 -sign` does exactly that with the key passed by PATH -- never by
content, since argv is world-readable in `ps`. Neither the key nor the JWT is ever printed.

TRANSPORT POSTURE is the backlog seam's, deliberately identical: plain `urllib`, an origin pin on
`api.github.com`, and a redirect handler that REFUSES rather than replaying `Authorization` at a
host chosen by the response. The credential in flight here is a JWT that can mint installation
tokens, so the consequence of getting that wrong is larger here than anywhere else in the codebase.

Import rule: this module imports `builder` (the shared contract) and never `cli`; the CLI imports
it, the way `cli` imports `backlog` and `stakeholder_question`.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from tautline_methodology import builder, lean

# One definition of "a credential that redacts itself when printed", shared with the backlog seam
# and the Jira client rather than copied a third time.
from tautline_methodology.jira_client import Secret
from tautline_methodology.util import flatten_printable, resolve_env

# --- configuration surface -----------------------------------------------------------------------

#: The App's numeric id, from its settings page.
APP_ID_ENV = "TAUTLINE_GITHUB_APP_ID"
#: A FILESYSTEM PATH to the App's PEM private key, stored outside every repository at mode 0600.
#: Never the key material itself: an environment variable is inherited by every child process and
#: printed by `env`, and a key that is one careless `env > debug.txt` from disclosure is disclosed.
APP_KEY_ENV = "TAUTLINE_GITHUB_APP_KEY"
#: Optional. Absent, the installation is discovered from the repo owner (see
#: `discover_installation_id`); present, it settles an ambiguity discovery cannot.
INSTALLATION_ID_ENV = "TAUTLINE_GITHUB_APP_INSTALLATION_ID"

#: Precedence order for an operator-supplied token, checked before the App is consulted at all.
#: GH_TOKEN first, matching `gh`'s own precedence, so a lane and the `gh` CLI beside it never
#: disagree about which of two exported tokens is in force.
TOKEN_ENVS = ("GH_TOKEN", "GITHUB_TOKEN")

GITHUB_API = "https://api.github.com"
GITHUB_HOST = "api.github.com"

REQUEST_TIMEOUT_SECONDS = 30

#: GitHub caps an App JWT at 10 minutes and rejects one whose `iat` is even a second in the future.
#: 60 seconds of backdate absorbs the clock skew between a developer's laptop and GitHub; 540
#: seconds ahead leaves the total window at exactly the 600-second ceiling.
JWT_BACKDATE_SECONDS = 60
JWT_LIFETIME_SECONDS = 540

#: Installation tokens live an hour. Handing out one with less than this left invites a failure
#: MID-COMMAND -- half a claim posted, the release comment 401 -- which is the most expensive
#: moment to discover an expiry and the hardest to reproduce.
REFRESH_MARGIN_SECONDS = 300

#: Cached under the framework's existing per-user config directory, beside `methodology.env`, at
#: 0600. The directory is SHARED, so it is created private and never re-permissioned afterwards --
#: see `write_cache`. There is no `TAUTLINE_CONFIG_HOME` convention in this codebase to honour,
#: so the location is derived from HOME at call time (never at import) -- which is also what lets a
#: test point it somewhere hermetic.
CACHE_RELPATH = Path(".config") / "minervit" / "builder-token.json"


class BuilderTokenError(Exception):
    """Every failure this module reports. Always names the next thing the operator should do."""


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses a redirect rather than replaying `Authorization` at a host the response chose.

    urllib follows redirects by default and RE-SENDS headers. The credential this transport carries
    is an App JWT -- which mints installation tokens for every repository the App is installed on --
    so a 302 to an attacker-controlled host would hand over rather more than one API call's worth of
    access. Neither endpoint here needs redirects, so refusing costs nothing.

    A sibling of `backlog._RefuseRedirect` and `jira_client._NoCredentialRedirectHandler` rather
    than a shared base: each raises its OWN module's error type, and a caller catching one would
    not catch the others.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib contract
        raise BuilderTokenError(
            f"GitHub returned a {code} redirect; refusing to follow it because the Authorization "
            f"header would be replayed at the new location. This client talks only to "
            f"https://{GITHUB_HOST}."
        )


@dataclass(frozen=True)
class AppConfig:
    """The three environment values, once, so no caller re-reads the environment piecemeal."""

    app_id: str
    key_path: Path
    installation_id: int | None


@dataclass(frozen=True)
class MintedToken:
    """One installation token and the two facts an operator needs about it.

    `permissions` is GitHub's OWN answer to "what can this token do", read off the mint response
    rather than restated from the docs -- which is the only version of that claim worth printing.
    """

    token: Secret
    expires_at: str
    installation_id: int
    app_id: str
    permissions: dict


# --- configuration -------------------------------------------------------------------------------


def app_config(environ: Mapping[str, str] | None = None) -> AppConfig | None:
    """The App configuration, or None when this machine has none.

    None is not an error. A human's laptop legitimately has no App configured, and every caller
    here degrades to the operator's own credentials rather than refusing.
    """
    app_id = resolve_env(APP_ID_ENV, environ=environ).strip()
    key_text = resolve_env(APP_KEY_ENV, environ=environ).strip()
    if not app_id or not key_text:
        return None
    raw_installation = resolve_env(INSTALLATION_ID_ENV, environ=environ).strip()
    installation_id: int | None = None
    if raw_installation:
        try:
            installation_id = int(raw_installation)
        except ValueError:
            raise BuilderTokenError(
                f"{INSTALLATION_ID_ENV} must be the numeric installation id (the trailing number "
                f"in the App's install URL), not {flatten_printable(raw_installation, 60)!r}. "
                f"Unset it to have it discovered from the repo owner instead."
            ) from None
    return AppConfig(
        app_id=app_id, key_path=Path(key_text).expanduser(), installation_id=installation_id
    )


def _repo_owner(cfg: dict | None) -> str:
    repo = str(((cfg or {}).get("project") or {}).get("repo") or "").strip()
    return repo.split("/", 1)[0] if "/" in repo else ""


# --- the JWT ---------------------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    """Unpadded base64url. A JWT with `=` padding is rejected outright by conforming verifiers."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _warn_if_key_is_readable(key_path: Path) -> None:
    """Say so when the App key is readable by group or other. Never refuse.

    A key at 0644 is a key any local process can read and mint installation tokens with -- the
    credential this module exists to keep narrow, and the one whose disclosure is worth more than
    every token it ever issues. It is worth SAYING.

    It is not worth refusing over. A refusal breaks a lane that is working, at a moment the
    operator did not choose, over a file they can fix in one command -- and a control that stops
    somebody's work over a warning-grade fact is a control they will find a way to disable.
    """
    try:
        mode = key_path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        print(
            f"builder_token_warning: the GitHub App private key at {key_path} is mode "
            f"{mode:04o}, so it is readable beyond you. Anyone who can read it can mint "
            f"installation tokens for the whole installation. `chmod 600 {key_path}`.",
            file=sys.stderr,
        )


def _sign_rs256(signing_input: bytes, key_path: Path) -> bytes:
    """`openssl dgst -sha256 -sign <pem>`: RSASSA-PKCS1-v1_5 over SHA-256, which IS RS256.

    The key goes by PATH and the signing input by STDIN. Neither ever reaches argv, which any local
    user can read out of `ps` for the lifetime of the call.
    """
    openssl = shutil.which("openssl")
    if not openssl:
        raise BuilderTokenError(
            "`openssl` is not on PATH, and it is what signs the GitHub App JWT (the runtime is "
            "stdlib-only and has no RSA implementation of its own). Install openssl, or export "
            f"{TOKEN_ENVS[0]} with a token instead of configuring {APP_ID_ENV}."
        )
    if not key_path.is_file():
        raise BuilderTokenError(
            f"The GitHub App private key named by {APP_KEY_ENV} is not a readable file: "
            f"{key_path}. Point {APP_KEY_ENV} at the PEM you downloaded when you generated the "
            "App's private key, stored outside any repository at mode 0600."
        )
    _warn_if_key_is_readable(key_path)
    try:
        result = subprocess.run(
            [openssl, "dgst", "-sha256", "-sign", str(key_path)],
            input=signing_input,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuilderTokenError(f"Could not run openssl to sign the App JWT: {exc}") from None
    if result.returncode != 0 or not result.stdout:
        detail = flatten_printable(result.stderr.decode("utf-8", "replace"), 300)
        raise BuilderTokenError(
            f"openssl could not sign with the key at {key_path} (named by {APP_KEY_ENV}). It must "
            f"be an unencrypted PEM RSA private key -- the file GitHub generates for the App. "
            f"openssl said: {detail}"
        )
    return result.stdout


def build_jwt(app_id: str, key_path: Path, now: float | None = None) -> str:
    """A signed App JWT. Never logged, never cached, never printed -- it lives for one exchange."""
    issued = int(now if now is not None else time.time()) - JWT_BACKDATE_SECONDS
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": issued, "exp": issued + JWT_BACKDATE_SECONDS + JWT_LIFETIME_SECONDS, "iss": app_id}
    segments = [
        _b64url(json.dumps(part, separators=(",", ":"), sort_keys=False).encode("utf-8"))
        for part in (header, payload)
    ]
    signing_input = ".".join(segments).encode("ascii")
    return f"{'.'.join(segments)}.{_b64url(_sign_rs256(signing_input, key_path))}"


# --- transport --------------------------------------------------------------------------------------


def _assert_github_origin(url: str) -> None:
    """Refuse to attach the App JWT to anything but api.github.com."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != GITHUB_HOST:
        raise BuilderTokenError(
            f"Refusing to send a GitHub App credential to "
            f"{flatten_printable(url, 120)!r}: this client talks only to https://{GITHUB_HOST}."
        )


def _build_opener() -> urllib.request.OpenerDirector:
    """The opener actually used, exposed so a test can prove the refusal is INSTALLED, not merely
    defined. A handler nothing wires in is a guard that cannot fire."""
    return urllib.request.build_opener(_RefuseRedirect())


def _request(
    method: str,
    url_or_path: str,
    *,
    jwt: str,
    payload: object | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> object:
    """One request against the App API, authenticated by the JWT. Returns the parsed body."""
    url = url_or_path if url_or_path.startswith("http") else f"{GITHUB_API}{url_or_path}"
    _assert_github_origin(url)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {jwt}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with _build_opener().open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except BuilderTokenError:
        raise
    except urllib.error.HTTPError as exc:
        raise _typed_error(exc, url_or_path) from None
    except (urllib.error.URLError, OSError) as exc:
        raise BuilderTokenError(
            f"The GitHub App request to {url_or_path} did not complete: {flatten_printable(exc, 200)}"
        ) from None
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError:
        raise BuilderTokenError(f"GitHub returned a non-JSON body for {url_or_path}.") from None


def _typed_error(exc: urllib.error.HTTPError, path: str) -> BuilderTokenError:
    """GitHub described the fault; discarding that description makes the operator guess at
    something already known. The three codes below each have one likely cause and one fix."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = flatten_printable(str((payload or {}).get("message") or ""), 300)
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        detail = ""
    suffix = f" GitHub said: {detail}" if detail else ""
    if exc.code == 401:
        return BuilderTokenError(
            f"GitHub rejected the App JWT (401) for {path}. The usual causes are an "
            f"{APP_ID_ENV} that is not this key's App, a private key that has been revoked, or a "
            f"machine clock more than a minute fast.{suffix}"
        )
    if exc.code == 404:
        return BuilderTokenError(
            f"GitHub returned 404 for {path}. For an installation id that means the App is not "
            f"installed there (or {INSTALLATION_ID_ENV} names an installation of a different "
            f"App).{suffix}"
        )
    return BuilderTokenError(f"GitHub returned HTTP {exc.code} for {path}.{suffix}")


# --- installation discovery ----------------------------------------------------------------------


def discover_installation_id(app_id: str, key_path: Path, owner: str) -> int:
    """The installation whose account is `owner`, or a refusal that names the candidates.

    Refusing on ambiguity rather than taking the first match is the point. Minting against the
    wrong installation yields a perfectly valid token with access to the wrong repositories, and
    that failure surfaces much later as a 404 on an endpoint that looks entirely correct.
    """
    jwt = build_jwt(app_id, key_path)
    body = _request("GET", "/app/installations", jwt=jwt)
    installations = body if isinstance(body, list) else []
    candidates = [
        (int(entry.get("id")), str(((entry.get("account") or {}).get("login") or "")))
        for entry in installations
        if isinstance(entry, dict) and str(entry.get("id") or "").isdigit()
    ]
    matches = [ident for ident, login in candidates if login.lower() == owner.lower()]
    if len(matches) == 1:
        return matches[0]
    seen = (
        ", ".join(f"{flatten_printable(login, 60)} (id {ident})" for ident, login in candidates)
        or "none"
    )
    if not matches:
        raise BuilderTokenError(
            f"This GitHub App has no installation on {flatten_printable(owner, 60)!r}. "
            f"Installations it does have: {seen}. Install the App on that account, or set "
            f"{INSTALLATION_ID_ENV} to the installation id you mean (the trailing number in the "
            f"App's install URL)."
        )
    raise BuilderTokenError(
        f"This GitHub App has {len(matches)} installations on "
        f"{flatten_printable(owner, 60)!r} (ids {', '.join(str(m) for m in matches)}), so the "
        f"right one cannot be inferred. Set {INSTALLATION_ID_ENV} to the one you mean."
    )


def resolve_installation_id(config: AppConfig, cfg: dict | None) -> int:
    """The configured installation id, or one discovered from the lean config's `project.repo`."""
    if config.installation_id is not None:
        return config.installation_id
    owner = _repo_owner(cfg)
    if not owner:
        raise BuilderTokenError(
            "The installation id could not be discovered because the lean adapter has no "
            "`project.repo` (owner/name) to take the owner from. Add `project.repo`, or set "
            f"{INSTALLATION_ID_ENV} directly."
        )
    return discover_installation_id(config.app_id, config.key_path, owner)


# --- the exchange ------------------------------------------------------------------------------------


def mint_installation_token(app_id: str, key_path: Path, installation_id: int) -> MintedToken:
    """Exchange an App JWT for an installation token.

    NO `permissions` IN THE BODY, on purpose. GitHub lets a mint request narrow the App's granted
    permissions, and narrowing here would move the scope claim out of the App's settings -- where an
    operator can read it, and where it binds every consumer -- and into this code, where a lane
    would be trusted to restrict itself. The entire argument for using an App is that nothing has to
    trust the lane.
    """
    jwt = build_jwt(app_id, key_path)
    body = _request("POST", f"/app/installations/{installation_id}/access_tokens", jwt=jwt)
    if not isinstance(body, dict) or not str(body.get("token") or "").strip():
        raise BuilderTokenError(
            f"GitHub accepted the token exchange for installation {installation_id} but returned "
            "no token. That is a GitHub-side fault; retry, and report it if it persists."
        )
    permissions = body.get("permissions")
    return MintedToken(
        token=Secret(str(body["token"])),
        expires_at=str(body.get("expires_at") or ""),
        installation_id=installation_id,
        app_id=app_id,
        permissions=permissions if isinstance(permissions, dict) else {},
    )


def app_bot_login(app_id: str, key_path: Path) -> str:
    """`<app-slug>[bot]` -- the author name every builder write is attributed to."""
    body = _request("GET", "/app", jwt=build_jwt(app_id, key_path))
    slug = str((body or {}).get("slug") or "").strip() if isinstance(body, dict) else ""
    return f"{flatten_printable(slug, 60)}[bot]" if slug else ""


# --- the cache ---------------------------------------------------------------------------------------


def cache_path() -> Path:
    """Resolved from HOME at CALL time, never at import: a module-level `Path.home()` bakes the
    directory of whichever process imported it first, which for a hook is not the operator's."""
    return Path.home() / CACHE_RELPATH


def _seconds_remaining(expires_at: str) -> float:
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return (expiry - datetime.now(timezone.utc)).total_seconds()


def read_cache(app_id: str, installation_id: int) -> MintedToken | None:
    """A cached token for THIS app and installation with real time left on it, or None.

    Every failure mode -- absent, unreadable, corrupt, someone else's installation, expiring -- is
    None, because the answer to all of them is identical: mint a fresh one. A raise here would turn
    a stale cache file into a wedged lane.
    """
    try:
        record = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if str(record.get("app_id") or "") != str(app_id):
        return None
    if record.get("installation_id") != installation_id:
        return None
    token = str(record.get("token") or "")
    expires_at = str(record.get("expires_at") or "")
    if not token or _seconds_remaining(expires_at) <= REFRESH_MARGIN_SECONDS:
        return None
    permissions = record.get("permissions")
    return MintedToken(
        token=Secret(token),
        expires_at=expires_at,
        installation_id=installation_id,
        app_id=str(app_id),
        permissions=permissions if isinstance(permissions, dict) else {},
    )


def write_cache(minted: MintedToken) -> Path:
    """Atomic and 0600, in a directory this call creates private but never re-permissions.

    Not `util.write_text_atomic`: that helper preserves an existing file's mode and defaults a NEW
    file to 0644, which for a live GitHub token is the wrong default in the one direction that
    matters. `mkstemp` creates at 0600 from the first byte, so the token is never briefly
    world-readable between creation and chmod.
    """
    import os
    import tempfile

    path = cache_path()
    # The PARENT is `~/.config/minervit`, which this module SHARES -- `methodology.env` lives
    # there. Chmod-ing it on every cache write silently re-permissioned somebody else's files
    # because one of them happened to be a token; owning a file in a directory is not owning the
    # directory. A directory this call CREATES is a different matter, and is created private.
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
    record = {
        "token": minted.token.reveal(),
        "expires_at": minted.expires_at,
        "installation_id": minted.installation_id,
        "app_id": minted.app_id,
        "permissions": minted.permissions,
    }
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        tmp.chmod(0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def mint_and_cache(app_id: str, key_path: Path, installation_id: int) -> MintedToken:
    """A usable installation token: the cached one while it has headroom, otherwise a fresh mint."""
    cached = read_cache(app_id, installation_id)
    if cached is not None:
        return cached
    minted = mint_installation_token(app_id, key_path, installation_id)
    write_cache(minted)
    return minted


# --- the seam ------------------------------------------------------------------------------------


def github_token(cfg: dict | None, environ: Mapping[str, str] | None = None) -> str:
    """The token the builder GitHub verbs should use, or "" to fall back to `gh auth token`.

    Precedence, and why: an operator-exported GH_TOKEN/GITHUB_TOKEN wins, because a person who
    exported a token on purpose is answering this question deliberately and no App should
    second-guess them. The App comes next. Empty last -- NOT a refusal -- because a human running
    the same verb on the same repository has no App configured and must keep working exactly as
    before. This layer adds an identity for builders; it takes nothing away from humans.
    """
    for name in TOKEN_ENVS:
        value = resolve_env(name, environ=environ).strip()
        if value:
            return value
    config = app_config(environ)
    if config is None:
        return ""
    installation_id = resolve_installation_id(config, cfg)
    return mint_and_cache(config.app_id, config.key_path, installation_id).token.reveal()


def token_source(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """`(source, detail)` where source is `env`, `app` or `none`. Never touches the network."""
    for name in TOKEN_ENVS:
        if resolve_env(name, environ=environ).strip():
            return "env", name
    config = app_config(environ)
    if config is not None:
        return "app", config.app_id
    return "none", ""


# --- CLI -----------------------------------------------------------------------------------------

NO_IDENTITY_HINT = (
    f"No builder identity is configured. Export {TOKEN_ENVS[0]} with a token, or configure the "
    f"GitHub App with {APP_ID_ENV} (the App's numeric id), {APP_KEY_ENV} (a path to its PEM "
    f"private key, 0600, outside any repository) and optionally {INSTALLATION_ID_ENV}. See "
    "docs/builder-lanes.md."
)


def _load_cfg(target: Path) -> dict | None:
    adapter = lean.find_lean_adapter(Path(target))
    return lean.load_lean_config(adapter) if adapter is not None else None


def _permissions_line(permissions: dict) -> str:
    if not permissions:
        return "(the mint response carried no permission list)"
    return ", ".join(
        f"{flatten_printable(str(key), 60)}={flatten_printable(str(value), 30)}"
        for key, value in sorted(permissions.items())
    )


#: A bare `builder-token` used to print a live installation token, because `--print` was
#: registered and never read. Printing a credential is a DECISION and it has to be asked for: the
#: no-flag shape is what somebody types while exploring a new verb, and it put the token in the
#: terminal scrollback and any transcript the session keeps.
NO_MODE_HINT = (
    "say which you want. `--print` writes ONLY the token to stdout, for "
    '`GH_TOKEN="$(tautline builder-token --print)"`. `--status` proves the identity -- source, '
    "app id, installation id, bot login, expiry and the permissions GitHub granted -- WITHOUT "
    "printing the token. There is no default, because the default would be a credential."
)


def builder_token_command(args: argparse.Namespace) -> int:
    """`tautline builder-token (--print | --status) [--target .]`.

    `--print` writes the token and NOTHING else to stdout, because the documented use is
    `GH_TOKEN="$(tautline builder-token --print)"` and one line of chatter makes the exported
    variable garbage. `--status` writes everything BUT the token. Neither flag is the default:
    see `NO_MODE_HINT`.
    """
    target = Path(getattr(args, "target", None) or Path("."))
    want_status = bool(getattr(args, "status", False))
    want_print = bool(getattr(args, "print_token", False))
    if not want_status and not want_print:
        print(f"builder_token_error: {NO_MODE_HINT}", file=sys.stderr)
        return 2
    try:
        cfg = _load_cfg(target)
        if want_status:
            return _print_status(cfg)
        token = github_token(cfg)
        if not token:
            # Refusing beats printing an empty line: `GH_TOKEN="$(...)"` would capture the blank,
            # and an EXPORTED-but-empty GH_TOKEN stops `gh` falling back to the operator's own
            # login -- turning a missing-config problem into an opaque 401 somewhere else.
            print(f"builder_token_error: {NO_IDENTITY_HINT}", file=sys.stderr)
            return 1
        print(token)
        return 0
    except BuilderTokenError as exc:
        print(f"builder_token_error: {flatten_printable(exc, 600)}", file=sys.stderr)
        return 1
    except Exception as exc:  # a CLI never answers with a traceback (backlog_command's contract)
        print(
            f"builder_token_error: this command hit an unexpected {type(exc).__name__}: "
            f"{flatten_printable(exc, 200)}. That is a bug in this command, not a problem with "
            "your GitHub App; please report it with the command you ran.",
            file=sys.stderr,
        )
        return 1


def _print_status(cfg: dict | None) -> int:
    """The proof an operator reads: who this lane is, and what GitHub says it may do."""
    source, detail = token_source()
    print(f"builder_token_source: {source}" + (f" ({detail})" if source == "env" else ""))
    if source == "env":
        print(
            "builder_token_scope: unknown - this token was supplied by the operator, so its "
            "scope is whatever they granted it. Only an App-minted token can be proved "
            "read-only on Projects from here."
        )
        return 0
    if source == "none":
        print(f"builder_token_hint: {NO_IDENTITY_HINT}")
        return 0

    config = app_config()
    if config is None:  # unreachable via `source == "app"`; kept so a future caller cannot crash
        print(f"builder_token_hint: {NO_IDENTITY_HINT}")
        return 0
    # The two facts that need no network go FIRST, so a status run that later fails to reach
    # GitHub has still told the operator which App and key this machine is configured with --
    # which is most of what they need to diagnose the failure that follows.
    print(f"builder_token_app_id: {flatten_printable(config.app_id, 40)}")
    installation_id = resolve_installation_id(config, cfg)
    print(f"builder_token_installation_id: {installation_id}")
    minted = mint_and_cache(config.app_id, config.key_path, installation_id)
    login = app_bot_login(config.app_id, config.key_path)
    print(f"builder_token_bot_login: {login or '(unavailable)'}")
    print(f"builder_token_expires_at: {flatten_printable(minted.expires_at, 40) or '(unknown)'}")
    print(f"builder_token_permissions: {_permissions_line(minted.permissions)}")
    return 0


def _ensure_ai_work_ignored(target: Path) -> None:
    """Append `.ai-work/` to the checkout's root .gitignore when it is not already ignored.

    A committed `.ai-work/lane-role` makes every clone of that branch a builder lane, including the
    human's -- the role is per-checkout state and must not be committable. Asked of git rather than
    by reading .gitignore, so an existing rule anywhere in the ignore chain (a global excludes file,
    `.git/info/exclude`, a parent .gitignore) counts and nothing is appended twice.

    A sibling of `cli.ensure_root_gitignore_patterns`, not a call to it: a feature module importing
    `cli` inverts the dependency direction the builder contract's import rule establishes, and the
    behaviour that matters here -- *is it ignored*, asked of git -- is not what that helper does.
    """
    root_text = _git_stdout(target, "rev-parse", "--show-toplevel")
    if not root_text:
        return  # not a git checkout: there is nothing to ignore it in, and the role still stands
    if _git_succeeds(target, "check-ignore", "-q", str(builder.ROLE_FILE)):
        return  # already ignored, by whichever file in the ignore chain -- nothing to add
    gitignore = Path(root_text) / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(
        f"{existing}{prefix}\n# Tautline lane state (the builder/human role marker)\n.ai-work/\n",
        encoding="utf-8",
    )


def _git(target: Path, *argv: str) -> subprocess.CompletedProcess | None:
    """A finished `git` run, or None when git could not run at all. Never raises: git's absence is
    not this verb's problem, and the role marker is still written on a machine without it."""
    try:
        return subprocess.run(
            ["git", *argv], cwd=str(target), capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_stdout(target: Path, *argv: str) -> str:
    result = _git(target, *argv)
    return result.stdout.strip() if result is not None and result.returncode == 0 else ""


def _git_succeeds(target: Path, *argv: str) -> bool:
    """For `check-ignore`, where the EXIT CODE is the answer and stdout may be empty."""
    result = _git(target, *argv)
    return result is not None and result.returncode == 0


def lane_role_command(args: argparse.Namespace) -> int:
    """`tautline lane-role builder|human|status [--target .]` -- the per-checkout role marker."""
    target = Path(getattr(args, "target", None) or Path("."))
    action = getattr(args, "action", "status")
    marker = target / builder.ROLE_FILE

    if action == "builder":
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{builder.ROLE_BUILDER}\n", encoding="utf-8")
        _ensure_ai_work_ignored(target)
        print(f"lane_role: builder ({builder.ROLE_FILE})")
        return 0
    if action == "human":
        try:
            marker.unlink()
            print(f"lane_role: human (removed {builder.ROLE_FILE})")
        except FileNotFoundError:
            print("lane_role: human (no marker to remove)")
        except OSError as exc:
            print(f"lane_role_error: could not remove {marker}: {flatten_printable(exc, 200)}")
            return 1
        if resolve_env(builder.ROLE_ENV).strip().lower() == builder.ROLE_BUILDER:
            # The env marker OUTRANKS the file, so removing the file did NOT make this lane human.
            # Saying nothing here is how an operator concludes the verb is broken.
            print(
                f"lane_role: WARNING still builder - {builder.ROLE_ENV}={builder.ROLE_BUILDER} is "
                "set in this environment and outranks the file. Unset it (or start a shell that "
                "does not export it) to become human."
            )
        return 0

    # status
    if resolve_env(builder.ROLE_ENV).strip().lower() == builder.ROLE_BUILDER:
        print(f"lane_role: builder (from {builder.ROLE_ENV})")
    elif builder.builder_role_active(target):
        print(f"lane_role: builder (from {builder.ROLE_FILE})")
    else:
        print("lane_role: human (default - no builder marker)")
    return 0


#: The GH_TOKEN half of the snippet. `export GH_TOKEN="$(tautline builder-token --print)"` exports
#: an EMPTY GH_TOKEN when the mint fails at eval time, and an exported-but-empty GH_TOKEN stops
#: `gh` falling back to the operator's own login -- turning a mint failure into an opaque 401 in
#: some later command, minutes away from the launch that caused it. The generation-time version of
#: this reasoning is the `source == "none"` branch below; this is the EVAL-time one, and both are
#: needed because the mint can succeed when the snippet is printed and fail when it is run.
GH_TOKEN_SNIPPET = """if _tautline_token="$(tautline builder-token --print)"; then
    export GH_TOKEN="$_tautline_token"
else
    echo "builder-env: no builder token; refusing to start a builder lane" >&2
fi
unset _tautline_token"""

#: The PATH half. `export PATH="$(tautline builder-guard --shim-dir):$PATH"` puts an EMPTY entry at
#: the front of PATH when the substitution fails, and an empty PATH entry means the CURRENT
#: DIRECTORY: every command the lane runs afterwards resolves against `.` first, so a file called
#: `git` in a checked-out repository runs instead of git. Add a directory, or add nothing.
PATH_SNIPPET = """_tautline_shim="$(tautline builder-guard --shim-dir 2>/dev/null)"
if [ -n "$_tautline_shim" ]; then
    export PATH="$_tautline_shim:$PATH"
fi
unset _tautline_shim"""


def builder_env_command(args: argparse.Namespace) -> int:
    """`tautline builder-env [--target .]` -- the snippet a lane evals to BECOME a builder.

    It PRINTS whether or not this lane is already a builder, and that is the design: this verb is
    how a lane becomes one, so refusing until it already is would make it unusable. Nothing here
    changes any state. What keeps a human out is documentation (docs/builder-lanes.md says never to
    eval it), not a check -- a check would have to guess at a human's intent, and the guess that
    fails closed breaks every legitimate builder launch.
    """
    target = Path(getattr(args, "target", None) or Path("."))
    print(f"export {builder.ROLE_ENV}={builder.ROLE_BUILDER}")

    # The ROLE line is printed FIRST and unconditionally, before anything that can fail. Taking the
    # role is the half of this snippet that never depends on configuration, and a lane that gets no
    # snippet at all because one environment variable has a typo in it is a worse outcome than a
    # lane that gets the role and a comment explaining the rest.
    try:
        source, _detail = token_source()
    except BuilderTokenError as exc:
        print(f"# builder identity unavailable: {flatten_printable(exc, 300)}")
        source = "none"
    if source == "none":
        # An `export GH_TOKEN="$(...)"` that resolves to nothing is worse than no line at all: an
        # exported-but-empty GH_TOKEN stops `gh` falling back to the operator's own login.
        print(f"# no builder identity is configured, so GH_TOKEN is left alone. {NO_IDENTITY_HINT}")
    else:
        print(GH_TOKEN_SNIPPET)

    # Emitted verbatim, and never executed here. `builder-guard --shim-dir` belongs to the guard
    # lane; running it from this verb would couple the snippet's correctness to that lane's state,
    # and a shell fragment is exactly the kind of thing that should be text until the operator's
    # shell expands it.
    print(PATH_SNIPPET)
    _ = target  # accepted for symmetry with the sibling verbs; the snippet is target-independent
    return 0


__all__ = [
    "APP_ID_ENV",
    "APP_KEY_ENV",
    "AppConfig",
    "BuilderTokenError",
    "GH_TOKEN_SNIPPET",
    "INSTALLATION_ID_ENV",
    "PATH_SNIPPET",
    "MintedToken",
    "NO_MODE_HINT",
    "REFRESH_MARGIN_SECONDS",
    "TOKEN_ENVS",
    "app_bot_login",
    "app_config",
    "build_jwt",
    "builder_env_command",
    "builder_token_command",
    "cache_path",
    "discover_installation_id",
    "github_token",
    "lane_role_command",
    "mint_and_cache",
    "mint_installation_token",
    "read_cache",
    "resolve_installation_id",
    "token_source",
    "write_cache",
]
