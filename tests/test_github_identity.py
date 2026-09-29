"""Item 86 WS1 — per-lane GitHub identity primitives.

RCA `20260630T202308Z` Control 4: concurrent lanes on one upstream, all authenticated as the same
GitHub user, cannot be told apart by anything GitHub records — so a review posted by one lane and a
merge performed by another are indistinguishable after the fact, and the machine-wide `gh` lock is
the only thing keeping them from colliding.

The advisory that closes it has exactly one hard requirement: **it must not cry wolf.** A
shared-login warning that fires for a second repository, a subdirectory invocation, a worktree of
the same clone, or a lane that was deleted last week is worth less than no warning at all, because
it trains the reader to skip the line. Most of this file is that requirement.
"""

import json
import subprocess

import pytest


def _git(root, *args):
    # noqa: S603,S607 - fixed argv, no shell
    subprocess.run(  # noqa: S603,S607
        ["git", "-C", str(root), *args], check=True, capture_output=True
    )


def _clone(tmp_path, name, remote="https://github.com/acme/widgets.git"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    if remote:
        _git(root, "remote", "add", "origin", remote)
    return root


@pytest.fixture
def records_root(gh, tmp_path, monkeypatch):
    root = tmp_path / "state" / "identities"
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: root)
    return root


@pytest.fixture
def gh():
    from tautline_methodology import ghutil

    return ghutil


# --- upstream parsing --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/Acme/Widgets.git", "github.com/acme/widgets"),
        ("git@github.com:Acme/Widgets.git", "github.com/acme/widgets"),
        ("ssh://git@ghe.corp.example/Acme/Widgets", "ghe.corp.example/acme/widgets"),
        ("https://github.com/acme/widgets", "github.com/acme/widgets"),
    ],
)
def test_the_upstream_is_parsed_locally_from_the_remote(gh, tmp_path, url, expected):
    """No `gh repo view`, no API call, no network -- this runs on every lane start."""
    root = _clone(tmp_path, "lane", remote=url)
    assert gh.github_upstream_slug(root) == expected


def test_a_checkout_with_no_remote_has_no_upstream(gh, tmp_path):
    """And therefore never participates in a shared-login warning: two lanes with no remote are not
    evidence they are the same repository."""
    root = _clone(tmp_path, "lane", remote=None)
    assert gh.github_upstream_slug(root) == ""


def test_a_url_that_is_not_a_repo_path_is_not_guessed_at(gh, tmp_path):
    root = _clone(tmp_path, "lane", remote="https://github.com/acme")
    assert gh.github_upstream_slug(root) == ""


# --- lane identity -----------------------------------------------------------------------------


def test_a_subdirectory_invocation_is_the_same_lane(gh, tmp_path):
    """`--target` defaults to `Path(".")`, so an invocation from anywhere inside the clone must not
    mint a second lane. Ordinary solo work would otherwise trip the advisory against itself."""
    root = _clone(tmp_path, "lane")
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    assert gh.github_identity_lane_key(sub) == gh.github_identity_lane_key(root)


def test_a_linked_worktree_is_a_DISTINCT_lane(gh, tmp_path):
    """The correction that matters most in this item.

    The first version keyed on `--git-common-dir`, which collapses every linked worktree of a clone
    onto one lane. This framework's standard topology is ONE ISOLATED WORKTREE PER LANE, so in the
    normal multi-lane setup every lane wrote the same record, `len(lanes)` stayed 1, and the
    shared-login warning could never fire at all -- the feature's primary purpose, disabled by its
    own key. Avoiding a false positive by going blind in the common case is not a trade.
    """
    root = _clone(tmp_path, "lane")
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "-q", "-b", "side", str(linked))
    assert gh.github_identity_lane_key(linked) != gh.github_identity_lane_key(root)


def test_two_distinct_clones_are_distinct_lanes(gh, tmp_path):
    a = _clone(tmp_path, "a")
    b = _clone(tmp_path, "b")
    assert gh.github_identity_lane_key(a) != gh.github_identity_lane_key(b)


# --- token source and fingerprint ---------------------------------------------------------------


def test_the_token_source_names_the_variable_actually_in_use(gh):
    assert gh.github_token_source("github.com", {"GH_TOKEN": "x"}) == "env:GH_TOKEN"
    assert gh.github_token_source("github.com", {"GITHUB_TOKEN": "x"}) == "env:GITHUB_TOKEN"
    assert gh.github_token_source("github.com", {}) == "keyring"


def test_an_enterprise_host_prefers_the_enterprise_token(gh):
    """`gh` reads GH_ENTERPRISE_TOKEN first for a non-github.com host. Reporting `keyring` while an
    env token is actually in use would make the whole surface a lie on enterprise."""
    environ = {"GH_ENTERPRISE_TOKEN": "e", "GH_TOKEN": "x"}
    assert gh.github_token_source("ghe.corp.example", environ) == "env:GH_ENTERPRISE_TOKEN"
    # ...and github.com is unaffected by an enterprise token being present.
    assert gh.github_token_source("github.com", environ) == "env:GH_TOKEN"


def test_the_token_value_is_never_returned(gh, tmp_path, monkeypatch):
    """The fingerprint exists so two lanes can be told apart WITHOUT either of them handling the
    other's credential. A primitive that returned the token would defeat its own purpose."""
    secret = "ghp_canary_do_not_leak"

    class _Proc:
        returncode = 0
        stdout = secret + "\n"
        stderr = ""

    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: _Proc())
    fingerprint = gh.github_token_fingerprint(tmp_path)
    assert len(fingerprint) == 8
    assert secret not in fingerprint
    # Same token, same fingerprint; a different token, a different one.
    assert fingerprint == gh.github_token_fingerprint(tmp_path)


def test_an_unauthenticated_lane_has_no_fingerprint(gh, tmp_path, monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "not logged in"

    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: _Proc())
    assert gh.github_token_fingerprint(tmp_path) == ""


# --- the lock exemption -------------------------------------------------------------------------


def test_a_local_only_gh_command_does_not_take_the_machine_wide_lock(gh, monkeypatch):
    """`gh auth token` reads the local credential store and issues NO API request, so serializing it
    buys zero rate-limit protection while costing up to the full acquire timeout on every lane
    start. The exemption is keyed on the COMMAND, so a new caller cannot forget it."""
    acquired = []
    monkeypatch.setattr(gh, "github_acquire_lock", lambda *a, **k: acquired.append(a) or "token")
    with gh.github_command_lock(["gh", "auth", "token"]):
        pass
    assert acquired == []


def test_an_api_reaching_gh_command_still_takes_the_lock(gh, monkeypatch, tmp_path):
    """The exemption must be narrow. Anything that reaches the API is still serialized."""
    acquired = []
    monkeypatch.setattr(gh, "github_cache_root", lambda: tmp_path)
    monkeypatch.setattr(gh, "github_acquire_lock", lambda *a, **k: (acquired.append(a), "tok")[1])
    monkeypatch.setattr(gh, "github_release_lock", lambda *a, **k: None)
    with gh.github_command_lock(["gh", "api", "user"]):
        pass
    assert len(acquired) == 1


# --- the shared-login predicate: everything below is about NOT crying wolf ------------------------


def _write_record(
    gh, records_root, *, lane, upstream, login, host="github.com", at=None, machine=""
):
    from datetime import datetime, timezone

    records_root.mkdir(parents=True, exist_ok=True)
    key = gh._github_identity_key(str(lane))
    (records_root / f"{key}.json").write_text(
        json.dumps(
            {
                "schema": gh.GITHUB_IDENTITY_RECORD_SCHEMA,
                "at": (at or datetime.now(timezone.utc).isoformat()),
                "laneKey": str(lane),
                "target": str(lane),
                "upstream": upstream,
                "ghHost": host,
                "login": login,
                "tokenFingerprint": "abcd1234",
                "source": "keyring",
                # THIS machine, as the real writer records it. Hard-coding a fake hostname made
                # every fixture a shape the writer never produces, and the machine filter added
                # after Codex R1 (v2) correctly excluded them all.
                "machine": machine or gh.github_provider_hostname(),
                "pid": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_two_lanes_on_one_upstream_under_one_login_warn(gh, records_root, tmp_path):
    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(gh, records_root, lane=b, upstream="github.com/acme/widgets", login="lane-bot")
    warnings = gh.github_shared_identity_warnings()
    assert len(warnings) == 1
    assert "login=lane-bot" in warnings[0]
    assert "2 lanes" in warnings[0]
    # The remedy is named, and it is the thing the reader has to do -- not a description of the
    # problem. A refusal or advisory whose fix has to be invented is one that gets ignored.
    assert "GH_TOKEN" in warnings[0] or "App installation token" in warnings[0]


@pytest.mark.parametrize(
    "second",
    [
        {"upstream": "github.com/acme/other", "login": "lane-bot"},  # a different repository
        {"upstream": "github.com/acme/widgets", "login": "someone-else"},  # a different identity
        {"upstream": "github.com/acme/widgets", "login": "lane-bot", "host": "ghe.corp.example"},
        {"upstream": "", "login": "lane-bot"},  # no parseable remote
    ],
)
def test_the_predicate_is_silent_for_everything_that_is_not_the_collision(
    gh, records_root, tmp_path, second
):
    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(gh, records_root, lane=b, **second)
    assert gh.github_shared_identity_warnings() == []


def test_a_stale_lane_is_not_an_active_one(gh, records_root, tmp_path):
    from datetime import datetime, timedelta, timezone

    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(
        gh, records_root, lane=b, upstream="github.com/acme/widgets", login="lane-bot", at=old
    )
    assert gh.github_shared_identity_warnings() == []


def test_a_deleted_clone_is_not_an_active_lane(gh, records_root, tmp_path):
    """Freshness alone is not enough: a lane deleted five minutes ago still has a fresh record."""
    a = _clone(tmp_path, "a")
    gone = tmp_path / "deleted-lane"
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(gh, records_root, lane=gone, upstream="github.com/acme/widgets", login="lane-bot")
    assert gh.github_shared_identity_warnings() == []


def test_a_malformed_record_is_skipped_rather_than_fatal(gh, records_root, tmp_path):
    """This subsystem is advisory. A corrupt file must not take a lane start down with it."""
    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(gh, records_root, lane=b, upstream="github.com/acme/widgets", login="lane-bot")
    (records_root / "garbage.json").write_text("{not json", encoding="utf-8")
    (records_root / "wrongshape.json").write_text("[]", encoding="utf-8")
    assert len(gh.github_shared_identity_warnings()) == 1


def test_a_touch_only_write_never_mints_a_lane(gh, records_root, tmp_path):
    """`create=False` callers refresh a lane that already registered; they must not register one.
    Otherwise every read-only status command would mint lanes and manufacture the collision."""
    a = _clone(tmp_path, "a")
    gh.github_identity_record_write(
        a,
        login="lane-bot",
        fingerprint="abcd1234",
        source="keyring",
        host="github.com",
        create=False,
    )
    assert gh.github_identity_records() == []
    gh.github_identity_record_write(
        a, login="lane-bot", fingerprint="abcd1234", source="keyring", host="github.com"
    )
    assert len(gh.github_identity_records()) == 1


def test_a_record_never_contains_a_token(gh, records_root, tmp_path):
    a = _clone(tmp_path, "a")
    gh.github_identity_record_write(
        a, login="lane-bot", fingerprint="abcd1234", source="env:GH_TOKEN", host="github.com"
    )
    text = (
        records_root / f"{gh._github_identity_key(gh.github_identity_lane_key(a))}.json"
    ).read_text()
    assert "abcd1234" in text  # the fingerprint, which is not the secret
    assert "tokenFingerprint" in text
    assert 'token":' not in text


# --- cost -----------------------------------------------------------------------------------------


def test_a_memoised_snapshot_makes_no_network_or_gh_call(gh, records_root, tmp_path, monkeypatch):
    """What the memo is actually for, stated as it now ships.

    An earlier version of this test asserted ZERO subprocesses. That claim died when the memo began
    revalidating against the current repository -- one `git config` -- which is what correctness
    costs once a retargeted `origin` can otherwise refresh a record for the wrong repo. It is
    affordable because only `github-budget-status --identity` reaches this path; the `lane-start`
    surface that needed a zero-cost guarantee is carried to a successor rather than shipped with
    one it could not keep.

    So the property tested is the one that matters and is true: no `gh`, no lock, no network.
    """
    lane = _clone(tmp_path, "lane")
    gh.github_identity_memo_write(
        lane,
        {
            "login": "lane-bot",
            "fingerprint": "abcd1234",
            "ghHost": "github.com",
            "source": "keyring",
        },
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    real_run = gh.subprocess.run

    def _guard(cmd, *a, **k):
        assert cmd and cmd[0] == "git", f"a memoised snapshot must not run {cmd[0]}"
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(gh.subprocess, "run", _guard)
    snapshot = gh.github_identity_snapshot(lane)
    assert snapshot["login"] == "lane-bot"
    assert snapshot["memo"] is True


def test_the_master_knob_stands_the_subsystem_down(gh, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "0")
    assert gh.github_identity_enabled() is False
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY", "1")
    assert gh.github_identity_enabled() is True


def test_a_nonsense_env_override_falls_back_rather_than_crashing(gh, monkeypatch):
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY_ACTIVE_SECONDS", "not-a-number")
    assert gh.github_identity_active_seconds() == gh.GITHUB_IDENTITY_ACTIVE_SECONDS


# --- the rule's reach: policy, skill, runbook -----------------------------------------------------


def test_the_runbook_ships_to_the_public_mirror(cli):
    """It is referenced by a string the shipped CLI prints, so an adopter who follows the warning
    must be able to reach it. A doc that stays behind in the private repo makes the remedy a dead
    end for exactly the audience the export exists for."""
    from pathlib import Path as _Path

    from tautline_methodology import public_release

    path = _Path("docs/reference/operations/per-lane-github-identity.md")
    assert public_release.export_path_included(
        path,
        allowed_product_docs=(),
        excluded_prefixes=cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES,
    )


# --- Codex R1 findings ---------------------------------------------------------------------------


def test_the_fingerprint_is_taken_for_the_selected_host(gh, tmp_path, monkeypatch):
    """Without `--hostname`, `gh auth token` resolves github.com even when the API call selects a
    GHES host. With only an enterprise token set, fingerprinting failed outright; with both set,
    the cache key hashed the PUBLIC token while the login came from the ENTERPRISE one -- so the
    cache could return another host's identity and the predicate could raise a FALSE shared-login
    warning, which is the one thing it must never do."""
    seen = {}

    class _Proc:
        returncode = 0
        stdout = "tok\n"
        stderr = ""

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(gh.subprocess, "run", _run)
    gh.github_token_fingerprint(tmp_path, "ghe.corp.example")
    assert "--hostname" in seen["cmd"]
    assert "ghe.corp.example" in seen["cmd"]


def test_an_app_installation_token_still_yields_an_identity(
    gh, tmp_path, monkeypatch, records_root
):
    """A GitHub App installation token cannot call `/user` -- it is not a user -- and returns 403.
    That is the SECOND REMEDY this feature's own runbook advertises, so reporting `unavailable`
    would mean the fix we recommend makes the tool go blind.

    The installation still has a stable identity for this feature's purpose: the fingerprint. Two
    lanes on the same installation token share one (correct -- they are indistinguishable to
    GitHub, which is the problem being detected); two on different ones do not.
    """
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, **k: "abcd1234")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))
    monkeypatch.setattr(
        gh,
        "_gh_json",
        lambda *a, **k: (1, None, "HTTP 403: Resource not accessible by integration"),
    )
    snapshot = gh.github_identity_snapshot(tmp_path, use_memo=False)
    assert snapshot.get("error") is None
    # NOT keyed on the fingerprint -- see test_an_app_identity_is_not_keyed_on_the_token for why
    # the first version of this assertion encoded a defect rather than a design.
    assert snapshot["login"] == "app-installation"
    assert snapshot["identityKind"] == "app-installation"


def test_a_genuine_auth_failure_is_not_mistaken_for_an_app(gh, tmp_path, monkeypatch):
    """Reporting an unreachable API as an App identity would invent a lane that does not exist."""
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, **k: "abcd1234")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))
    monkeypatch.setattr(gh, "_gh_json", lambda *a, **k: (1, None, "HTTP 401: Bad credentials"))
    assert gh.github_identity_snapshot(tmp_path, use_memo=False).get("error")


def test_exporting_a_new_token_invalidates_the_memo(gh, tmp_path, monkeypatch):
    """The documented remedy for a shared-login warning is `export GH_TOKEN=<per-lane token>`. A
    memo that ignored it kept reporting the OLD shared login for up to 900 seconds -- preserving
    the exact warning the operator had just acted on, which teaches them the remedy does not work.
    """
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    gh.github_identity_memo_write(
        tmp_path,
        {
            "login": "old-shared",
            "fingerprint": "aaaaaaaa",
            "ghHost": "github.com",
            "source": "keyring",
        },
    )
    assert gh.github_identity_memo_read(tmp_path)["login"] == "old-shared"
    monkeypatch.setenv("GH_TOKEN", "a-new-per-lane-token")
    assert gh._github_memo_is_stale(gh.github_identity_memo_read(tmp_path)) is True


def test_an_unchanged_token_leaves_the_memo_usable(gh, tmp_path, monkeypatch):
    """The invalidation must be keyed on an OBSERVED change, or the memo never hits and the whole
    zero-subprocess property is lost."""
    import hashlib

    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    token = "a-stable-token"
    fp = hashlib.sha256(token.encode()).hexdigest()[:8]
    monkeypatch.setenv("GH_TOKEN", token)
    gh.github_identity_memo_write(
        tmp_path,
        {"login": "lane-bot", "fingerprint": fp, "ghHost": "github.com", "source": "env:GH_TOKEN"},
    )
    assert gh._github_memo_is_stale(gh.github_identity_memo_read(tmp_path)) is False


def test_an_incomplete_memo_is_not_an_identity(gh, tmp_path, monkeypatch):
    """A snapshot missing a field is a partial write or an older shape. Returning it would surface
    a half-formed identity as a confident answer, and WRITE a record with an empty login that the
    shared-login predicate would then group other lanes against."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    gh.github_identity_memo_write(tmp_path, {"login": "lane-bot", "ghHost": "github.com"})
    assert gh._github_memo_is_stale(gh.github_identity_memo_read(tmp_path)) is True


# --- Codex R2 findings ---------------------------------------------------------------------------


def test_two_lanes_in_sibling_worktrees_do_warn(gh, records_root, tmp_path):
    """End to end on the topology this framework actually uses. This is the case the first lane
    key silently excluded, so it is asserted through the predicate rather than the key alone."""
    root = _clone(tmp_path, "lane")
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    a = tmp_path / "wt-a"
    b = tmp_path / "wt-b"
    _git(root, "worktree", "add", "-q", "-b", "lane-a", str(a))
    _git(root, "worktree", "add", "-q", "-b", "lane-b", str(b))
    for lane in (a, b):
        _write_record(
            gh,
            records_root,
            lane=gh.github_identity_lane_key(lane),
            upstream="github.com/acme/widgets",
            login="lane-bot",
        )
    warnings = gh.github_shared_identity_warnings()
    assert len(warnings) == 1
    assert "2 lanes" in warnings[0]


def test_an_app_identity_is_not_keyed_on_the_token(gh, tmp_path, monkeypatch):
    """Two lanes minting separate tokens from the SAME installation have different fingerprints
    while GitHub attributes both to one installation and they share its rate-limit bucket. Keying
    `login` on the fingerprint would make them look distinct and SUPPRESS the warning they should
    raise -- this control's failure mode is silence, so it errs toward grouping."""
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))
    monkeypatch.setattr(
        gh,
        "_gh_json",
        lambda *a, **k: (1, None, "HTTP 403: Resource not accessible by integration"),
    )
    logins = []
    for fp in ("aaaaaaaa", "bbbbbbbb"):
        # `fp=fp` binds at definition. A bare closure over the loop variable is B023, and here it
        # would make both iterations read the LAST fingerprint -- the test would pass while
        # exercising one value twice, which is the shape of an assertion that proves nothing.
        monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, fp=fp, **k: fp)
        logins.append(gh.github_identity_snapshot(tmp_path, use_memo=False)["login"])
    assert logins == ["app-installation", "app-installation"]


def test_a_rate_limited_user_token_is_not_called_an_app(gh, tmp_path, monkeypatch):
    """A bare 403 is also what an exhausted core budget or an org policy block returns for an
    ordinary user token. Classifying those as an App would record a FABRICATED identity and mask a
    shared login between lanes using different PATs."""
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, **k: "abcd1234")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))
    monkeypatch.setattr(
        gh, "_gh_json", lambda *a, **k: (1, None, "HTTP 403: API rate limit exceeded")
    )
    assert gh.github_identity_snapshot(tmp_path, use_memo=False).get("error")


@pytest.mark.parametrize(
    "host,expected",
    [
        ("github.com", "env:GH_TOKEN"),
        ("acme.ghe.com", "env:GH_TOKEN"),  # Enterprise CLOUD uses GH_TOKEN
        ("ghe.corp.example", "env:GH_ENTERPRISE_TOKEN"),  # GHES does not
    ],
)
def test_enterprise_cloud_follows_gh_token_precedence(gh, host, expected):
    """`gh` reads GH_ENTERPRISE_TOKEN first only for GHES. Treating every non-github.com host as
    GHES reported the wrong variable on `<tenant>.ghe.com` -- and because the memo's fingerprint
    check duplicated the precedence, the two disagreed, every memo looked stale, and the
    zero-subprocess path was silently destroyed."""
    environ = {"GH_TOKEN": "u", "GH_ENTERPRISE_TOKEN": "e"}
    assert gh.github_token_source(host, environ) == expected


def test_unsetting_the_token_invalidates_an_env_backed_memo(gh, tmp_path, monkeypatch):
    """A lane reverting from a per-lane GH_TOKEN to its keyring credential kept reporting the old
    bot identity for up to 15 minutes -- hiding that it had fallen back to a possibly SHARED
    login, which is the state this feature exists to surface."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh.github_identity_memo_write(
        tmp_path,
        {
            "login": "lane-bot",
            "fingerprint": "aaaaaaaa",
            "ghHost": "github.com",
            "source": "env:GH_TOKEN",
        },
    )
    assert gh._github_memo_is_stale(gh.github_identity_memo_read(tmp_path)) is True


def test_the_api_call_is_bounded_by_the_remaining_budget(gh, tmp_path, monkeypatch):
    """A ceiling that is advertised and not enforced is the same shape as every other defect in
    this program. The checks either side of the call only changed the verdict; they let lane-start
    block for the lock's 30s plus another 10s and then report the budget exceeded."""
    seen = {}
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, **k: "abcd1234")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))

    def _capture(command, target, timeout, max_lock_wait=None):
        seen["timeout"] = timeout
        seen["max_lock_wait"] = max_lock_wait
        return 0, {"login": "lane-bot", "id": 1}, ""

    monkeypatch.setattr(gh, "_gh_json", _capture)
    monkeypatch.setattr(gh, "github_identity_memo_write", lambda *a, **k: None)
    monkeypatch.setattr(gh, "github_cache_write", lambda *a, **k: None)
    monkeypatch.setattr(gh, "github_record_provider_call", lambda **k: None)
    gh.github_identity_snapshot(tmp_path, use_memo=False)
    assert seen["timeout"] <= gh.github_identity_budget_seconds()
    # ...and the LOCK wait is bounded too. Bounding only the subprocess left the 30-second lock
    # acquisition running ahead of it, so the advertised ceiling bounded the fast part.
    assert seen["max_lock_wait"] is not None
    assert seen["max_lock_wait"] <= gh.github_identity_budget_seconds()


# --- Codex R3 findings ---------------------------------------------------------------------------


def test_the_repository_host_beats_a_stale_gh_host(gh, tmp_path, monkeypatch):
    """A lane with a parseable GHES remote and a stale `GH_HOST=github.com` still exported would
    have every repository-aware `gh` command infer GHES while this selected the public host and
    then explicitly queried it -- so the lane could cache and report the WRONG account, and raise
    or suppress shared-login warnings against it."""
    root = _clone(tmp_path, "lane", remote="https://ghe.corp.example/acme/widgets.git")
    monkeypatch.setenv("GH_HOST", "github.com")
    assert gh.github_gh_host(root) == "ghe.corp.example"


def test_gh_host_still_fills_in_when_there_is_no_remote(gh, tmp_path, monkeypatch):
    """`GH_HOST` is what you set when there is no repository to infer from, so that is when it is
    used -- removing it entirely would break the case it exists for."""
    root = _clone(tmp_path, "lane", remote=None)
    monkeypatch.setenv("GH_HOST", "ghe.corp.example")
    assert gh.github_gh_host(root) == "ghe.corp.example"


def test_a_ghes_host_does_not_fall_back_to_public_tokens(gh):
    """`gh` consults ONLY the enterprise variables for GHES. Including the public ones as a
    fallback meant a lane with a stored GHES credential and an exported public GH_TOKEN reported
    `source=env:GH_TOKEN` and compared THAT token's fingerprint against the enterprise credential --
    so every memo looked stale and the API was re-invoked on every call."""
    assert gh.github_token_source("ghe.corp.example", {"GH_TOKEN": "public"}) == "keyring"
    assert (
        gh.github_token_source(
            "ghe.corp.example", {"GH_ENTERPRISE_TOKEN": "e", "GH_TOKEN": "public"}
        )
        == "env:GH_ENTERPRISE_TOKEN"
    )


# --- Codex R4 findings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    ["https://[broken/acme/repo.git", "https://[::1", "ssh://git@[bad:host/acme/repo"],
)
def test_a_malformed_remote_never_crashes_the_lane(gh, tmp_path, bad_url):
    """Git accepts arbitrary remote strings, so `remote.origin.url` can hold something `urlsplit`
    refuses. Uncaught, that turned an ADVISORY into a lane-start crash -- breaking the one property
    this subsystem states most loudly: it can never fail a lane."""
    root = _clone(tmp_path, "lane", remote=bad_url)
    assert gh.github_upstream_slug(root) == ""
    assert gh.github_gh_host(root) == "github.com"


def test_a_malformed_remote_falls_through_to_the_next_one(gh, tmp_path):
    """Skipping the bad remote must not mean skipping the good one behind it."""
    root = _clone(tmp_path, "lane", remote="https://[broken/acme/repo.git")
    _git(root, "remote", "add", "upstream", "https://github.com/acme/widgets.git")
    assert gh.github_upstream_slug(root) == "github.com/acme/widgets"


def test_a_warm_memo_read_costs_no_subprocess_in_a_FRESH_process(gh, tmp_path, monkeypatch):
    """The claim, tested the way it actually ships.

    The previous version wrote the memo and read it back in ONE process, so the in-process lane-key
    cache was already populated and the read never needed `git rev-parse`. Every real warm read
    happens in a fresh CLI process with an empty cache -- and there, building both memo paths
    eagerly invoked git before the cheap path could be opened. The test proved the level it tested,
    not what ships.
    """
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    lane = _clone(tmp_path, "lane")
    gh.github_identity_memo_write(
        lane,
        {
            "login": "lane-bot",
            "fingerprint": "abcd1234",
            "ghHost": "github.com",
            "source": "keyring",
        },
    )
    # Simulate the fresh process: drop the cache the write populated.
    gh._GITHUB_LANE_KEY_CACHE.clear()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def _explode(*a, **k):
        raise AssertionError("a warm memo read must not run a subprocess in a fresh process")

    monkeypatch.setattr(gh.subprocess, "run", _explode)
    assert gh.github_identity_memo_read(lane)["login"] == "lane-bot"


def test_a_zero_budget_spends_nothing_at_all(gh, tmp_path, monkeypatch):
    """The host lookup and `gh auth token` each carry fixed five-second timeouts, so a budget below
    five seconds -- including zero, which an operator would reasonably read as "do not spend time
    on this" -- was not enforced until after both had already run."""
    monkeypatch.setenv("MINERVIT_GITHUB_IDENTITY_BUDGET_SECONDS", "0")

    def _explode(*a, **k):
        raise AssertionError("a zero budget must not reach any subprocess")

    monkeypatch.setattr(gh.subprocess, "run", _explode)
    result = gh.github_identity_snapshot(tmp_path, use_memo=False)
    assert "budget" in result.get("error", "")


# --- Codex R1 on the fresh lineage ----------------------------------------------------------------


def test_records_from_another_machine_are_excluded(gh, records_root, tmp_path, monkeypatch):
    """The record carried a `machine` field and nothing filtered on it.

    With a shared telemetry root or checkouts on shared storage, records from every host grouped
    together -- so two lanes on DIFFERENT machines could raise an advisory claiming they are active
    "on this machine". That is a false positive AND the exact opposite of the cross-machine
    exclusion the runbook documents.
    """
    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    _write_record(
        gh,
        records_root,
        lane=a,
        upstream="github.com/acme/widgets",
        login="lane-bot",
        machine="another-laptop",
    )
    _write_record(
        gh,
        records_root,
        lane=b,
        upstream="github.com/acme/widgets",
        login="lane-bot",
        machine="another-laptop",
    )
    assert gh.github_shared_identity_warnings() == []
    # ...and the same pair DOES warn when the records belong to this machine.
    _write_record(gh, records_root, lane=a, upstream="github.com/acme/widgets", login="lane-bot")
    _write_record(gh, records_root, lane=b, upstream="github.com/acme/widgets", login="lane-bot")
    assert len(gh.github_shared_identity_warnings()) == 1


def test_the_memo_carries_the_coordinates_the_record_writer_needs(gh, tmp_path, monkeypatch):
    """The writer grew `lane_key` and `upstream` parameters and the caller did not pass them, so a
    warm start still paid `git rev-parse` and `git config` -- a fix that added the capability and
    never connected it."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    lane = _clone(tmp_path, "lane")
    gh.github_identity_memo_write(
        lane,
        {
            "login": "lane-bot",
            "fingerprint": "abcd1234",
            "ghHost": "github.com",
            "source": "keyring",
        },
    )
    memo = gh.github_identity_memo_read(lane)
    assert memo["laneKey"] == gh.github_identity_lane_key(lane)
    assert memo["upstream"] == "github.com/acme/widgets"


def test_a_record_write_with_coordinates_runs_no_git(gh, tmp_path, monkeypatch):
    """End of the chain: given the memo's coordinates, filing the record must cost nothing."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    lane = _clone(tmp_path, "lane")
    key = gh.github_identity_lane_key(lane)
    gh._GITHUB_LANE_KEY_CACHE.clear()

    def _explode(*a, **k):
        raise AssertionError("filing a record with known coordinates must not run git")

    monkeypatch.setattr(gh.subprocess, "run", _explode)
    gh.github_identity_record_write(
        lane,
        login="lane-bot",
        fingerprint="abcd1234",
        source="keyring",
        host="github.com",
        lane_key=key,
        upstream="github.com/acme/widgets",
    )
    assert len(gh.github_identity_records()) == 1


def test_a_source_change_with_the_same_token_invalidates_the_memo(gh, tmp_path, monkeypatch):
    """The same token moving keyring -> GH_TOKEN leaves the fingerprint identical while `gh` now
    reads a different variable, so the identity line would report a source no longer in use."""
    import hashlib

    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    token = "a-stable-token"
    fp = hashlib.sha256(token.encode()).hexdigest()[:8]
    monkeypatch.delenv("GH_TOKEN", raising=False)
    gh.github_identity_memo_write(
        tmp_path,
        {"login": "lane-bot", "fingerprint": fp, "ghHost": "github.com", "source": "keyring"},
    )
    monkeypatch.setenv("GH_TOKEN", token)
    assert gh._github_memo_is_stale(gh.github_identity_memo_read(tmp_path)) is True


# --- Codex R2 on the fresh lineage: the ceiling is withdrawn, not patched again ---------------


def test_the_cold_path_still_works_for_the_diagnostic_verb(gh, tmp_path, monkeypatch):
    """Withdrawing the promise must not remove the capability -- an operator asking on purpose
    still gets a real answer, and waiting is the expected cost there."""
    monkeypatch.setattr(gh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(gh, "github_token_fingerprint", lambda *a, **k: "abcd1234")
    monkeypatch.setattr(gh, "github_cache_read", lambda *a, **k: (None, None))
    monkeypatch.setattr(gh, "_gh_json", lambda *a, **k: (0, {"login": "lane-bot", "id": 1}, ""))
    monkeypatch.setattr(gh, "github_identity_memo_write", lambda *a, **k: None)
    monkeypatch.setattr(gh, "github_cache_write", lambda *a, **k: None)
    monkeypatch.setattr(gh, "github_record_provider_call", lambda **k: None)
    assert gh.github_identity_snapshot(tmp_path, use_memo=False)["login"] == "lane-bot"


def test_supplied_coordinates_are_not_recomputed(gh, tmp_path, monkeypatch):
    """`setdefault` EVALUATES ITS DEFAULT even when the key is present, so the previous version ran
    `git rev-parse` and `git config` on every write regardless of what the caller supplied -- the
    coordinates were threaded through and then recomputed anyway."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    lane = _clone(tmp_path, "lane")
    key = gh.github_identity_lane_key(lane)
    gh._GITHUB_LANE_KEY_CACHE.clear()

    def _explode(*a, **k):
        raise AssertionError("supplied coordinates must not be recomputed")

    monkeypatch.setattr(gh.subprocess, "run", _explode)
    gh.github_identity_memo_write(
        lane,
        {
            "login": "lane-bot",
            "fingerprint": "abcd1234",
            "ghHost": "github.com",
            "source": "keyring",
            "laneKey": key,
            "upstream": "github.com/acme/widgets",
        },
    )
    assert gh.github_identity_memo_read(lane)["upstream"] == "github.com/acme/widgets"


# --- Codex R4: the warning has to be REACHABLE ----------------------------------------------------


def test_the_identity_probe_mints_a_record(gh, tmp_path, monkeypatch, records_root):
    """Without a minter the whole feature is inert.

    Removing the `lane-start` surface removed the only writer: `github-budget-status` passed
    `create_record=False`, so on a fresh install the record directory stayed EMPTY and
    `github_shared_identity_warnings()` could never see two lanes. A predicate that cannot fire,
    behind a release note saying it does.
    """
    lane = _clone(tmp_path, "lane")
    gh.github_identity_record_write(
        lane,
        login="lane-bot",
        fingerprint="abcd1234",
        source="keyring",
        host="github.com",
        create=True,
    )
    assert len(gh.github_identity_records()) == 1


def test_the_warning_is_reachable_from_the_shipped_writer(gh, records_root, tmp_path, monkeypatch):
    """End to end on the shipped surface: two lanes, each registered the way the shipped verb
    registers them, produce the warning. This is the assertion R4 showed was missing -- every other
    test wrote records through the fixture helper rather than through the code path that ships."""
    a, b = _clone(tmp_path, "a"), _clone(tmp_path, "b")
    for lane in (a, b):
        gh.github_identity_record_write(
            lane,
            login="lane-bot",
            fingerprint="abcd1234",
            source="keyring",
            host="github.com",
            create=True,
        )
    warnings = gh.github_shared_identity_warnings()
    assert len(warnings) == 1
    assert "2 lanes" in warnings[0]


def test_a_gh_host_change_invalidates_a_no_remote_memo(gh, tmp_path, monkeypatch):
    """With no parseable remote the host comes from GH_HOST, and skipping the comparison there
    meant a GH_HOST change inside the TTL returned the OLD host and login -- in the no-remote
    workflow the fallback explicitly supports."""
    monkeypatch.setattr(gh, "github_identity_records_root", lambda: tmp_path / "state")
    lane = _clone(tmp_path, "lane", remote=None)
    monkeypatch.setenv("GH_HOST", "github.com")
    gh.github_identity_memo_write(
        lane,
        {
            "login": "lane-bot",
            "fingerprint": "abcd1234",
            "ghHost": "github.com",
            "source": "keyring",
        },
    )
    monkeypatch.setenv("GH_HOST", "ghe.corp.example")
    memo = gh.github_identity_memo_read(lane)
    assert gh._github_memo_is_stale(memo, current_host=gh.github_gh_host(lane)) is True
