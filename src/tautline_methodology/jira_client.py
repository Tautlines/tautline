"""A minimal Jira Cloud REST client: stdlib only, cached, with credentials that cannot be printed.

SALVAGED, 2026-08-28. This module was written for the Jira first-class-support program (0.139.0 -
0.143.0 plus the unmerged 0.144.0 read verbs) and the 2026-08-28 process-bankruptcy demolition swept
it out with the board-sync engine it had been welded to. The engine is not coming back. The client
is, because nothing about it belonged to the engine: it is an HTTP transport with an auth model and
a value grammar, and those are the parts a `backlog` provider needs whatever the surrounding process
looks like. What was DISCARDED is the shape around it -- the provider registry, the category/verb
contract, `unavailable_verbs`, the board pin, the `backlogProvider`/`goalTracker` adapter blocks.

**Nothing here has spoken to a real Jira instance.** The endpoints and response shapes come from
documentation, not from a live call, and no credentials exist in the environment that built it. The
provider must not be described as *supported* anywhere user-facing until a live validation run is
recorded: authenticate, JQL-search, read transitions, transition a scratch issue.

Two properties are load-bearing, and both are here because the FIRST version of this module got them
wrong and cross-model review caught them as P1s. They are stated as design constraints rather than
as reassurance, because the previous version's reassurance was the defect:

**The cache is scoped to an authenticated identity, never to a site.** The first version keyed on
`site_url` and carried a comment presenting that as the safety property. It is not. Two accounts on
one Jira site share a site key, so the second is served the first's response without ever
authenticating -- including issues its own permissions would have hidden. The key is now derived
from a fingerprint of the credentials actually used, so a different account is a different cache.

**A credential renders as `<redacted>` wherever an object or a frame is printed.** The first version
claimed the token "is never stored on the instance, so it cannot be reached from a traceback frame",
and assigned `self._token` twelve lines later. An underscore prefix is a naming convention, not
containment: the value stays in the instance dict and in frame locals, and `raise ... from None`
suppresses chaining, not frames. Rather than repeat a claim that cannot be met by hiding, the token
is wrapped in a type whose `__repr__` redacts, so the renderers that actually leak -- error
reporters that dump frame locals, `repr()` of the client -- print `<redacted>`. The raw value is
reachable only through an explicit `.reveal()`, which is greppable.

The identity GRAMMAR (`JIRA_CLOUD_HOST`, `JIRA_PROJECT_KEY`, `MAX_BOARD_ID_DIGITS`) lives here, with
the transport that consumes those values against a live API, and is imported by every validator that
needs it. That placement is the instruction the 0.143.0 routed row carried: a second copy of the
host rule would drift from the first, and this program has already paid for two readers of one fact
disagreeing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from tautline_methodology.util import flatten_printable, resolve_env

#: The environment variables that hold Jira credentials. NAMES, fixed by the framework rather than
#: configurable, because the lean `backlog` block carries no credential field at all: an adapter is
#: committed to a repository, so the only safe place for a token is the environment.
EMAIL_ENV = "JIRA_EMAIL"
API_TOKEN_ENV = "JIRA_API_TOKEN"

#: Item data changes constantly; the field schema effectively does not. Measured on the GitHub side:
#: 43% of one hour's rate budget went on re-fetching a static field schema.
CACHE_TTL_SECONDS = 60
SCHEMA_CACHE_TTL_SECONDS = 24 * 60 * 60

REQUEST_TIMEOUT_SECONDS = 30

#: A Jira Cloud tenant hostname: DNS labels, then `.atlassian.net`. A character class like
#: `[A-Za-z0-9.-]*` accepts `team-.` and `team..`, which are not resolvable hosts.
#:
#: The `{0,61}` bound is not decoration. DNS limits a label to 63 octets, and an unbounded repeat
#: accepts a 200-character tenant label that no resolver will ever answer for -- a value that passes
#: validation and points nowhere. The companion 253-octet limit on the whole hostname cannot be
#: expressed in the same pattern, so `site_url_issue` applies both together.
MAX_DNS_LABEL = 63
MAX_HOSTNAME = 253
_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
JIRA_CLOUD_HOST = re.compile(rf"^https://{_DNS_LABEL}(?:\.{_DNS_LABEL})*\.atlassian\.net/?$")

#: Jira's project-key grammar: an uppercase letter, then uppercase letters and digits. Jira Cloud
#: requires at least one more character after the leading letter, so `A` is invalid -- an earlier
#: `*` accepted it and the framework only discovered the truth as an API failure.
JIRA_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9]+$")

#: Python refuses `int()` on a digit string above 4300 characters and raises `ValueError`, so a
#: board id is length-bounded BEFORE it is converted. Converting first crashes the validator that
#: exists to report the invalid value.
MAX_BOARD_ID_DIGITS = 19

#: key -> (stored_at, is_schema, payload)
_RESPONSE_CACHE: dict[str, tuple[float, bool, object]] = {}


class JiraError(Exception):
    """Base for every typed Jira failure. A generic 'Jira request failed' is a defect."""


class JiraAuthError(JiraError):
    """401/403 -- the credentials were rejected, or lack permission."""


class JiraNotFoundError(JiraError):
    """404 -- names what was not found, so the caller need not guess."""


class JiraRateLimitError(JiraError):
    """429 -- carries `Retry-After` when Jira supplied one."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class JiraTransportError(JiraError):
    """5xx, refused redirects, and anything else that did not complete."""


# --- identity grammar ----------------------------------------------------------------------------
#
# Three pure functions, deliberately not three checks scattered across three validators. The
# credential-format check in the release before these produced FOUR review findings across four
# rounds because each fix addressed the dimension that found it; the routed row that carried these
# findings says to write the grammar in ONE pass. Each returns a message or "".


def site_url_issue(site: str, label: str = "backlog.site") -> str:
    """Why `site` is not a usable Jira Cloud site URL, or "" when it is."""
    site = site.strip()
    if not site:
        return f"{label} is required for the jira provider (https://<your-team>.atlassian.net)"
    if not JIRA_CLOUD_HOST.match(site):
        # Jira Server / Data Center differs in auth and in its endpoint set, and this client targets
        # Cloud only. Refusing at configuration names the reason; accepting defers the failure to an
        # unexplained 404 from an endpoint that does not exist there.
        return (
            f"{label} must be a Jira CLOUD site (https://<your-team>.atlassian.net): {site!r} is "
            "not one. Jira Server and Data Center are not supported -- they differ in "
            "authentication and endpoints."
        )
    host = site[len("https://") :].rstrip("/")
    if len(host) > MAX_HOSTNAME:
        return (
            f"{label} hostname must be at most {MAX_HOSTNAME} characters (DNS limit): "
            f"{host[:32]}... is {len(host)}"
        )
    return ""


def project_key_issue(key: str, label: str = "backlog.project") -> str:
    """Why `key` is not a usable Jira project key, or "" when it is."""
    key = key.strip()
    if not key:
        return f"{label} is required for the jira provider (a project key such as 'PROJ')"
    if not JIRA_PROJECT_KEY.match(key):
        return (
            f"{label} must match Jira's project-key grammar -- an uppercase letter followed by "
            f"uppercase letters and digits, such as 'PROJ'. {key!r} does not, and it is "
            "interpolated into every JQL query and issue URL this provider builds."
        )
    return ""


def board_id_issue(board: str, label: str = "backlog.board") -> str:
    """Why `board` is not a usable Jira board id, or "" when it is (blank is allowed: optional)."""
    board = board.strip()
    if not board:
        return ""
    # The length bound comes FIRST and is not cosmetic: `int()` raises on a digit string above 4300
    # characters, so converting before bounding would crash the validator instead of reporting an
    # invalid board id.
    too_long = len(board) > MAX_BOARD_ID_DIGITS
    if too_long or not (board.isascii() and board.isdigit() and int(board) >= 1):
        # `str.isdigit()` alone is true for "0" and for Unicode digits like "²"; neither is a
        # Jira board, and both build a `/board/<junk>/issue` request that resolves to nothing.
        return f"{label} must be a positive whole number (a Jira board id): {board!r} is not one"
    return ""


class Secret:
    """A credential that redacts itself when printed.

    Not security theatre, and not a claim that the value is unreachable -- it plainly is, via
    `reveal()`. What this closes is the path that actually leaks in practice: something renders an
    object or a frame, and a bare `str` attribute renders its contents. Every such renderer goes
    through `__repr__`/`__str__`, so redacting there covers error reporters that dump locals, log
    formatters, and `repr()` of any object holding one.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """The raw credential. Greppable ON PURPOSE: every real use should be easy to audit."""
        return self._value

    def __repr__(self) -> str:
        return "<redacted>"

    __str__ = __repr__

    def __bool__(self) -> bool:
        return bool(self._value)


def reset_response_cache(*, include_schema: bool = True) -> None:
    """Drop cached responses. `include_schema=False` keeps the long-TTL schema entries.

    After WRITING an item you want item data refetched, but the field schema did not change and
    refetching it is the waste this cache exists to avoid.
    """
    if include_schema:
        _RESPONSE_CACHE.clear()
        return
    for key in [k for k, (_, is_schema, _) in _RESPONSE_CACHE.items() if not is_schema]:
        _RESPONSE_CACHE.pop(key, None)


def reset_schema_cache() -> None:
    """Drop ONLY the long-TTL schema entries, leaving item data cached."""
    for key in [k for k, (_, is_schema, _) in _RESPONSE_CACHE.items() if is_schema]:
        _RESPONSE_CACHE.pop(key, None)


def cache_keys() -> list[str]:
    """The current cache keys, for tests that assert no credential is embedded in one."""
    return sorted(_RESPONSE_CACHE)


class _NoCredentialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses redirects rather than replaying the `Authorization` header at a new host.

    urllib follows redirects by default and re-sends headers. A 302 to an attacker-controlled host
    would hand it the credential. Jira Cloud's REST API does not need us to follow redirects, so
    refusing is free.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib contract
        raise JiraTransportError(
            f"Jira returned a {code} redirect to a different location; refusing to follow it "
            "because the Authorization header would be replayed there. If your site genuinely "
            "moved, update backlog.site in the adapter."
        )


class JiraClient:
    """One Jira Cloud site, one identity, one cache scope."""

    def __init__(
        self,
        *,
        site_url: str,
        email_env: str = EMAIL_ENV,
        api_token_env: str = API_TOKEN_ENV,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.site_url = site_url.rstrip("/")
        # THREADED, not defaulted. A caller on a session-start path gives this client a short leash
        # and the leash is void unless the value reaches `opener.open`. Storing it on the caller and
        # letting the transport use its own 30s constant is the shape that makes a bounded call
        # unbounded while every line of code still reads as though it were bounded.
        self.timeout = timeout
        self._email_env = email_env
        self._api_token_env = api_token_env
        # Through the resolver, which is the framework's single env-read chokepoint. A
        # shipped module that reads the process environment directly is a bypass the guard
        # in tests/test_env_reads_use_resolver.py exists to catch.
        self._email = resolve_env(email_env)
        self._token = Secret(resolve_env(api_token_env))
        self._clock = clock or time.time

    def __repr__(self) -> str:
        # Explicit, because the default would render the instance dict -- which holds the secret.
        fingerprint = self._identity_fingerprint()[:8]
        return f"JiraClient(site_url={self.site_url!r}, identity={fingerprint!r})"

    __str__ = __repr__

    # --- auth ------------------------------------------------------------------------------------

    def auth_issues(self) -> list[str]:
        """Every missing credential, named with the variable to set."""
        issues: list[str] = []
        if not self._email:
            issues.append(
                f"Jira credentials: environment variable {self._email_env} is not set. It must "
                "hold the Atlassian account email that owns the API token."
            )
        if not self._token:
            issues.append(
                f"Jira credentials: environment variable {self._api_token_env} is not set. Create "
                "an API token at https://id.atlassian.com/manage-profile/security/api-tokens and "
                f"export it as {self._api_token_env}."
            )
        return issues

    def _auth_header(self) -> str:
        raw = f"{self._email}:{self._token.reveal()}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _identity_fingerprint(self) -> str:
        """A stable, non-reversible id for (site, account, token).

        The cache key must distinguish identities WITHOUT embedding the credential -- a key is
        printed in diagnostics and may be written to disk. A digest does both.
        """
        material = "\0".join((self.site_url, self._email, self._token.reveal())).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    # --- transport -------------------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Central redaction. Per-call-site redaction is the rule someone forgets."""
        for secret in (self._token.reveal(), self._email):
            if secret:
                text = text.replace(secret, "<redacted>")
        return text

    def _cache_key(self, method: str, path: str, params: dict | None) -> str:
        query = urllib.parse.urlencode(sorted((params or {}).items()))
        # IDENTITY, not site. See the module docstring: site-keying crosses an authentication
        # boundary, because one site hosts many accounts with different permissions.
        return f"{self._identity_fingerprint()} {method} {path}?{query}"

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        """The opener actually used, exposed so a test can prove the redirect refusal is INSTALLED.

        A STATICMETHOD, matching the backlog seam's transport, so the suite can ENUMERATE every
        transport in the subsystem and call this on the class. A guard that has to be told which
        transports exist is a checking layer with no discovery layer, and a new transport is simply
        absent from it -- which is the exact shape that let the missing refusal ship in the first
        place.

        Built here rather than inline because a test that constructs `_NoCredentialRedirectHandler`
        directly proves only that the class refuses -- not that anything wires it in. That is the
        gap that lets a guard pass while the behaviour it guards is unreachable.
        """
        return urllib.request.build_opener(_NoCredentialRedirectHandler())

    def _assert_jira_cloud_origin(self) -> None:
        """Refuse to attach credentials to anything that is not a Jira Cloud site.

        Config validation is NOT sufficient here, and the review that found this named the exact
        path: a diagnostic surface may reach this client with adapter data that never passed
        validation, and a checked-in config carrying `site: https://attacker.example` would receive
        the Basic authorization header -- a credential exfiltration primitive committed to a
        repository. The grammar is the SAME object the validator uses, not a second copy.
        """
        if not JIRA_CLOUD_HOST.match(self.site_url):
            raise JiraAuthError(
                f"Refusing to send Jira credentials to {self.site_url!r}: it is not a Jira Cloud "
                "site (https://<your-team>.atlassian.net). This is checked again here, at the "
                "point credentials are attached, because diagnostic paths can reach this client "
                "with config that never passed validation."
            )

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        payload: object | None = None,
    ) -> object:
        # The ORIGIN is checked before anything else, because everything below this line either
        # attaches a credential or depends on the answer.
        self._assert_jira_cloud_origin()
        # Refuse LOCALLY before opening a socket. Without this, an unset credential is discovered
        # only from Jira's 401 -- a network round trip to learn a fact already knowable here, and
        # one that sends `Basic base64(":")` to a third party on the way. It also loses the
        # actionable half of the message: `auth_issues` says how to create a token, the 401 cannot.
        issues = self.auth_issues()
        if issues:
            raise JiraAuthError(" ".join(issues))
        url = f"{self.site_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(sorted(params.items()))}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", self._auth_header())
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        opener = self._build_opener()
        try:
            with opener.open(request, timeout=self.timeout) as response:
                # `read()` can fail mid-stream (reset connection, truncated body). Untyped, it
                # escapes as a raw OSError past the redaction this chokepoint exists to apply.
                try:
                    body = response.read().decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise JiraTransportError(
                        self._redact(f"Jira response for {path} could not be read: {exc}")
                    ) from None
        except JiraTransportError:
            raise
        except urllib.error.HTTPError as exc:
            raise self._typed_http_error(exc, path) from None
        except urllib.error.URLError as exc:
            raise JiraTransportError(
                self._redact(f"Jira request to {path} did not complete: {exc.reason}")
            ) from None
        if not body.strip():
            # A successful write with no content. `POST .../transitions` answers 204 with an empty
            # body, and treating that as a parse failure would report a transition that SUCCEEDED
            # as an error -- the worst direction for a write.
            return None
        try:
            return json.loads(body)
        except ValueError:
            raise JiraTransportError(
                self._redact(f"Jira returned a non-JSON body for {path}")
            ) from None

    @staticmethod
    def _error_collection(exc: urllib.error.HTTPError) -> str:
        """Jira's ErrorCollection, BOTH halves, as one sentence -- or "" when there is no body.

        A non-2xx body carries `errorMessages` (an array of whole sentences) and `errors` (a map of
        field -> problem), and Jira uses EITHER depending on what failed: a bad JQL answers in
        `errorMessages`, a rejected field in `errors`. Reading one half is how "Jira returned HTTP
        400" becomes the entire diagnosis a caller gets for a fault the server described precisely.

        SANITISED ON THE WAY OUT, at the source, because this is the one place the body's own bytes
        become part of a message a terminal will print. It reached stderr un-flattened once: a
        forged 400 body carrying erase-line and BEL could repaint the line above it and show a
        healthy backlog count that nothing had measured. Flattening here means no caller has to
        remember, including the ones that do not exist yet.
        """
        try:
            raw = exc.read().decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            return ""
        try:
            payload = json.loads(raw)
        except ValueError:
            return flatten_printable(raw, 400)
        if not isinstance(payload, dict):
            return ""
        parts = [str(item) for item in (payload.get("errorMessages") or []) if str(item).strip()]
        errors = payload.get("errors")
        if isinstance(errors, dict):
            parts.extend(f"{field}: {problem}" for field, problem in sorted(errors.items()))
        return flatten_printable(" ".join(parts), 400)

    def _typed_http_error(self, exc: urllib.error.HTTPError, path: str) -> JiraError:
        code = exc.code
        detail = self._error_collection(exc)
        suffix = f" Jira said: {detail}" if detail else ""
        if code in (401, 403):
            return JiraAuthError(
                self._redact(
                    f"Jira rejected the credentials for {path} (HTTP {code}). Check "
                    f"{self._email_env} and {self._api_token_env}, and that the account can see "
                    f"this project.{suffix}"
                )
            )
        if code == 404:
            return JiraNotFoundError(
                self._redact(f"Jira has nothing at {path} (HTTP 404).{suffix}")
            )
        if code == 429:
            # `headers` is an email.message.Message in real urllib and a plain dict in tests;
            # both answer `.get`, and anything else is treated as "no Retry-After supplied"
            # rather than crashing the error path that is already reporting a failure.
            headers = getattr(exc, "headers", None)
            raw = ""
            if headers is not None:
                try:
                    value = headers.get("Retry-After")
                except (AttributeError, TypeError):
                    value = None
                raw = "" if value is None else str(value)
            retry_after = int(raw) if raw.isdigit() else None
            rate_suffix = f" Retry after {retry_after} seconds." if retry_after is not None else ""
            return JiraRateLimitError(
                self._redact(f"Jira rate-limited the request to {path}.{rate_suffix}{suffix}"), retry_after
            )
        return JiraTransportError(self._redact(f"Jira returned HTTP {code} for {path}.{suffix}"))

    # --- reads and writes --------------------------------------------------------------------

    def get(self, path: str, params: dict | None = None, *, schema: bool = False) -> object:
        """A cached GET. `schema=True` selects the long TTL for effectively-static data."""
        key = self._cache_key("GET", path, params)
        cached = _RESPONSE_CACHE.get(key)
        if cached is not None:
            stored_at, stored_as_schema, payload = cached
            ttl = SCHEMA_CACHE_TTL_SECONDS if stored_as_schema else CACHE_TTL_SECONDS
            if self._clock() - stored_at < ttl:
                return payload
        payload = self._request("GET", path, params)
        _RESPONSE_CACHE[key] = (self._clock(), schema, payload)
        return payload

    def post(self, path: str, payload: object) -> object:
        """An uncached POST, which then invalidates cached ITEM data but not the field schema.

        A write is never served from cache and never cached, and the invalidation is deliberate:
        `take` transitions an issue and the very next `list` must not be answered from the copy
        read a moment earlier. The schema entries survive, because creating an issue does not
        change what fields exist.
        """
        result = self._request("POST", path, None, payload)
        reset_response_cache(include_schema=False)
        return result
