"""sec-trust-exec-1 (productization): the auto-update must verify upstream trust BEFORE os.execve of
the new code. verify_upstream_trust() implements the policy gate (signed | pinned | unverified |
warn-default). Default 'warn' stays backward-compatible (allows, but loudly recommends a strict
policy); strict modes refuse an unverified/unpinned upstream.
"""

import stat
import subprocess
from pathlib import Path

import pytest

HEAD = "a" * 40
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_env_absent_policy_falls_back_to_warn_for_legacy_installs(cli, monkeypatch):
    # A1: fresh installs get pinned via methodology.env, but a legacy install with no policy env
    # keeps the backward-compatible 'warn' runtime fallback so it does not fail closed on update.
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", raising=False)
    assert cli.methodology_update_policy() == "warn"
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is True
    assert "WARNING" in msg and "trust" in msg.lower()


def test_unverified_policy_allows_silently(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "unverified")
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is True
    assert msg == ""


def test_pinned_policy_without_pins_refuses(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_PINS", raising=False)
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is False
    assert "no pins configured" in msg


def test_pinned_policy_matching_pin_allows(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", HEAD)
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is True
    assert msg == ""


def test_pinned_policy_non_matching_refuses(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", "b" * 40)
    # rev-parse of the pin must not resolve to HEAD in this hermetic test
    monkeypatch.setattr(cli, "run_git", lambda root, args: "unavailable")
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is False
    assert "not in the pinned allowlist" in msg


def test_gate_refusal_includes_repin_recovery_guidance(cli, monkeypatch):
    # A blocked lane start must tell the operator how to proceed (review, then
    # update-repin), not just refuse: the 0.7.0->0.8.2 stable advance left a
    # product lane hard-blocked with no recovery instruction in the output.
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", "b" * 40)
    monkeypatch.setattr(cli, "run_git", lambda root, args: "unavailable")
    detail = cli.gate_methodology_upstream_advance(HEAD)
    assert detail is not None
    assert "update-repin" in detail
    assert "review" in detail.lower()


def test_gate_refusal_signed_policy_gives_signature_guidance_not_repin(cli, monkeypatch):
    # update-repin only rewrites the pinned allowlist; the signed policy ignores it, so a
    # signed-policy refusal must steer to signature/signer remediation instead (Codex R1 P2).
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "signed")
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (1, "", "no signature"))
    detail = cli.gate_methodology_upstream_advance(HEAD)
    assert detail is not None
    assert "update-repin" not in detail
    assert "signature" in detail.lower() or "signer" in detail.lower()


def test_signed_policy_refuses_unsigned(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "signed")
    # Simulate `git verify-commit` failing (no valid signature).
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (1, "", "no signature"))
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is False
    assert "not validly signed" in msg


def test_signed_policy_allows_signed(cli, monkeypatch):
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "signed")
    monkeypatch.delenv("MINERVIT_METHODOLOGY_UPDATE_SIGNERS", raising=False)
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (0, "", "Good signature"))
    allowed, msg = cli.verify_upstream_trust(HEAD)
    assert allowed is True


# --- Re-exec wiring (regression for the ungated auto-rescue paths) ---------------------
#
# verify_upstream_trust() being correct is necessary but not sufficient: every os.execve of
# freshly-fetched upstream code must pass through it first. The two DEFAULT auto-rescue paths
# (non-main checkout, dirty working tree) once re-exec'd upstream with NO trust check — an
# ungated RCE on adopter startup. These tests pin the wiring so a new re-exec point cannot
# silently reintroduce the gap. They stub verify_upstream_trust (its policy is covered above)
# and assert the caller honors its verdict relative to os.execve.

RESCUED_HEAD = "c" * 40


def _fake_run_git(responses):
    def _run(_root, args):
        for prefix, value in responses:
            if tuple(args[: len(prefix)]) == prefix:
                return value
        return "unavailable"

    return _run


class _ExecveReached(Exception):
    """Raised by the os.execve stub so the test can assert the re-exec was actually reached
    (it is not an OSError, so the caller's `except OSError` does not swallow it)."""


def _arm_common(cli, monkeypatch):
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)
    monkeypatch.setattr(cli, "create_methodology_reexec_token", lambda head: "tok")
    monkeypatch.delenv("MINERVIT_METHODOLOGY_ALLOW_NON_MAIN", raising=False)


def test_non_main_rescue_reexec_blocked_when_trust_denied(cli, monkeypatch):
    _arm_common(cli, monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_git",
        _fake_run_git([
            (("rev-parse", "--is-inside-work-tree"), "true"),
            (("branch", "--show-current"), "feature"),
            (("rev-parse", "HEAD"), RESCUED_HEAD),
        ]),
    )
    monkeypatch.setattr(cli, "rescue_methodology_non_main_checkout", lambda b: (True, "rescued non-main", "rescue/x"))
    seen = {}
    monkeypatch.setattr(cli, "verify_upstream_trust", lambda h: (seen.update(head=h) or (False, "blocked: not in the pinned allowlist")))

    def _no_execve(*a, **k):
        raise AssertionError("os.execve must NOT run when upstream trust is denied")

    monkeypatch.setattr(cli.os, "execve", _no_execve)
    status, detail = cli.update_methodology_repo(False, False, True, auto_rescue_stale_only=False)
    assert status == "failed"
    assert "refus" in detail.lower()
    assert seen["head"] == RESCUED_HEAD  # the gate verified the freshly-rescued upstream head


def test_local_changes_rescue_reexec_blocked_when_trust_denied(cli, monkeypatch):
    _arm_common(cli, monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_git",
        _fake_run_git([
            (("rev-parse", "--is-inside-work-tree"), "true"),
            (("branch", "--show-current"), "main"),
            (("status", "--porcelain"), "M bin/minervit-methodology"),
            (("rev-parse", "HEAD"), RESCUED_HEAD),
        ]),
    )
    monkeypatch.setattr(cli, "rescue_methodology_local_changes", lambda *a, **k: (True, "rescued local", "rescue/y"))
    seen = {}
    monkeypatch.setattr(cli, "verify_upstream_trust", lambda h: (seen.update(head=h) or (False, "blocked: not validly signed")))

    def _no_execve(*a, **k):
        raise AssertionError("os.execve must NOT run when upstream trust is denied")

    monkeypatch.setattr(cli.os, "execve", _no_execve)
    status, detail = cli.update_methodology_repo(False, False, True, auto_rescue_stale_only=False)
    assert status == "failed"
    assert "refus" in detail.lower()
    assert seen["head"] == RESCUED_HEAD


def test_non_main_rescue_reexec_proceeds_when_trust_allows(cli, monkeypatch):
    # The gate must not over-block: when trust allows, the path still reaches os.execve.
    _arm_common(cli, monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_git",
        _fake_run_git([
            (("rev-parse", "--is-inside-work-tree"), "true"),
            (("branch", "--show-current"), "feature"),
            (("rev-parse", "HEAD"), RESCUED_HEAD),
        ]),
    )
    monkeypatch.setattr(cli, "rescue_methodology_non_main_checkout", lambda b: (True, "rescued non-main", "rescue/x"))
    monkeypatch.setattr(cli, "verify_upstream_trust", lambda h: (True, ""))

    def _reached(*a, **k):
        raise _ExecveReached

    monkeypatch.setattr(cli.os, "execve", _reached)
    with pytest.raises(_ExecveReached):
        cli.update_methodology_repo(False, False, True, auto_rescue_stale_only=False)


# --- A1: install-cli pins the update policy at install time ---------------------------------


def _repo_head() -> str:
    return subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()


def test_install_cli_defaults_to_pinned_policy(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    config_env = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(config_env))
    assert res.returncode == 0, res.stderr
    text = config_env.read_text(encoding="utf-8")
    assert "MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned" in text
    assert f"MINERVIT_METHODOLOGY_UPDATE_PINS={_repo_head()}" in text  # shlex-quoted: a plain sha needs no quotes


def test_install_cli_update_policy_flag_overrides(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    config_env = tmp_path / "cfg" / "methodology.env"
    res = run_cli(
        "install-cli", "--bin-dir", str(bin_dir), "--config-env", str(config_env), "--update-policy", "warn"
    )
    assert res.returncode == 0, res.stderr
    text = config_env.read_text(encoding="utf-8")
    assert "MINERVIT_METHODOLOGY_UPDATE_POLICY=warn" in text
    assert "MINERVIT_METHODOLOGY_UPDATE_PINS=" not in text


def _init_repo_with_upstream(tmp_path, upstream_version=None):
    """Two-commit repo where origin/main is one commit ahead of the local checkout.

    `upstream_version` writes a VERSION file into the AHEAD commit only, so the held-candidate
    remedy tests can exercise both the resolved-version path and the sha-only degrade (no VERSION)
    with the same harness.
    """
    upstream = tmp_path / "upstream.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "HOME": str(tmp_path),
        "PATH": subprocess.os.environ["PATH"],
    }
    (work / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "one"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "main"], check=True, capture_output=True, env=env)
    first = subprocess.check_output(["git", "-C", str(work), "rev-parse", "HEAD"], text=True, env=env).strip()
    # A second upstream commit that repin must advance to.
    (work / "f.txt").write_text("two\n")
    if upstream_version is not None:
        (work / "VERSION").write_text(f"{upstream_version}\n")
        subprocess.run(
            ["git", "-C", str(work), "add", "-A"], check=True, capture_output=True, env=env
        )
    subprocess.run(["git", "-C", str(work), "commit", "-am", "two"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True, capture_output=True, env=env)
    second = subprocess.check_output(["git", "-C", str(work), "rev-parse", "HEAD"], text=True, env=env).strip()
    # Reset the local checkout back to the first commit so origin/main is ahead until repin fetches.
    subprocess.run(["git", "-C", str(work), "reset", "--hard", first], check=True, capture_output=True, env=env)
    return work, first, second


def test_repin_advances_pin_after_fetch(cli, tmp_path):
    work, first, second = _init_repo_with_upstream(tmp_path)
    config_env = tmp_path / "methodology.env"
    config_env.write_text(
        f"export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\nexport MINERVIT_METHODOLOGY_UPDATE_PINS={first}\n",
        encoding="utf-8",
    )
    previous, new_head, trusted_range = cli.repin_methodology_update(work, config_env)
    assert previous == first
    assert new_head == second
    assert first[:12] in trusted_range and second[:12] in trusted_range
    assert f"MINERVIT_METHODOLOGY_UPDATE_PINS={second}" in config_env.read_text(encoding="utf-8")
    assert first not in config_env.read_text(encoding="utf-8")


# --- R1 P1: repin must keep BOTH pin spellings in lockstep -----------------------------------
# install-cli dual-writes MINERVIT_ and TAUTLINE_ pins, and resolve_env prefers the TAUTLINE_
# alias. Repin used to rewrite only the MINERVIT_ line, so a stale TAUTLINE_ value kept shadowing
# the fresh pin -> the next pinned update was wrongly rejected even though repin reported success.


def test_repin_dual_writes_both_pin_spellings(cli, tmp_path, monkeypatch):
    work, first, second = _init_repo_with_upstream(tmp_path)
    config_env = tmp_path / "methodology.env"
    config_env.write_text(
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\n"
        "export TAUTLINE_METHODOLOGY_UPDATE_POLICY=pinned\n"
        f"export MINERVIT_METHODOLOGY_UPDATE_PINS={first}\n"
        f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={first}\n",
        encoding="utf-8",
    )
    previous, new_head, _ = cli.repin_methodology_update(work, config_env)
    assert previous == first and new_head == second
    text = config_env.read_text(encoding="utf-8")
    assert f"export MINERVIT_METHODOLOGY_UPDATE_PINS={second}" in text
    assert f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={second}" in text
    assert first not in text  # no stale spelling of either pin name survives
    util = cli.util_module()
    for spelling in ("MINERVIT_METHODOLOGY_UPDATE_PINS", "TAUTLINE_METHODOLOGY_UPDATE_PINS"):
        assert util.user_config_env_value(spelling, config_env) == second
    # Model a fresh shell sourcing the repinned file, then resolve_env's TAUTLINE-first read: the
    # effective allowlist is the new pin, so the next pinned update is accepted (not the stale one).
    for spelling in ("TAUTLINE_METHODOLOGY_UPDATE_PINS", "MINERVIT_METHODOLOGY_UPDATE_PINS"):
        monkeypatch.setenv(spelling, util.user_config_env_value(spelling, config_env))
    assert util.resolve_env(cli.METHODOLOGY_UPDATE_PINS_ENV) == second


def test_repin_dual_writes_both_spellings_in_mirror(cli, tmp_path, monkeypatch):
    work, first, second = _init_repo_with_upstream(tmp_path)
    primary = tmp_path / "tautline.env"
    mirror = tmp_path / "methodology.env"
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", primary)
    monkeypatch.setattr(cli, "LEGACY_USER_CONFIG_ENV", mirror)
    body = (
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\n"
        f"export MINERVIT_METHODOLOGY_UPDATE_PINS={first}\n"
        f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={first}\n"
    )
    primary.write_text(body, encoding="utf-8")
    mirror.write_text(body, encoding="utf-8")
    cli.repin_methodology_update(work, primary)
    for surface in (primary, mirror):
        text = surface.read_text(encoding="utf-8")
        assert f"export MINERVIT_METHODOLOGY_UPDATE_PINS={second}" in text
        assert f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={second}" in text
        assert first not in text  # mirror kept in lockstep too


def test_repin_previous_reads_effective_tautline_first_pin(cli, tmp_path):
    # A pre-existing desync (TAUTLINE_ != MINERVIT_) must be reported by what the machine actually
    # trusted: the TAUTLINE_ spelling resolve_env prefers, not the shadowed MINERVIT_ line.
    work, first, second = _init_repo_with_upstream(tmp_path)
    effective = "e" * 40
    config_env = tmp_path / "methodology.env"
    config_env.write_text(
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\n"
        f"export MINERVIT_METHODOLOGY_UPDATE_PINS={first}\n"
        f"export TAUTLINE_METHODOLOGY_UPDATE_PINS={effective}\n",
        encoding="utf-8",
    )
    previous, new_head, _ = cli.repin_methodology_update(work, config_env)
    assert previous == effective  # TAUTLINE-first, not the stale MINERVIT_ value
    assert new_head == second


# --- R2 P2: repin must fail closed on fetch/channel errors -----------------------------------


def test_repin_fails_closed_when_fetch_fails(cli, tmp_path):
    # Codex R2 P2: a failed `git fetch origin <branch>` (offline/auth/missing branch) left a STALE
    # cached origin/<branch> remote-tracking ref that repin silently pinned and reported as current
    # upstream. Repin must exit non-zero and leave the pin untouched instead.
    work, first, second = _init_repo_with_upstream(tmp_path)
    config_env = tmp_path / "methodology.env"
    config_env.write_text(
        f"export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\nexport MINERVIT_METHODOLOGY_UPDATE_PINS={first}\n",
        encoding="utf-8",
    )
    # Break the upstream AFTER the initial push: fetch now fails, but the cached origin/main
    # remote-tracking ref (== second) survives and would be silently repinned without the fix.
    subprocess.run(
        ["git", "-C", str(work), "remote", "set-url", "origin", str(tmp_path / "gone.git")],
        check=True,
        capture_output=True,
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.repin_methodology_update(work, config_env)
    assert "fetch" in str(excinfo.value)
    text = config_env.read_text(encoding="utf-8")
    assert f"MINERVIT_METHODOLOGY_UPDATE_PINS={first}" in text, "pin must be unchanged on fetch failure"
    assert second not in text, "repin must never fall back to the stale cached origin/<branch> ref"


def test_update_repin_rejects_unknown_channel(run_cli):
    # Codex R2 P2: --channel accepted any string and unknown values silently mapped to main,
    # so a typo repinned trust to the wrong branch. Argparse must reject unknown channels.
    res = run_cli("update-repin", "--channel", "expermental")
    assert res.returncode != 0
    assert "invalid choice" in res.stderr


# --- P1: verify BEFORE the checkout advances (fetch-verify-then-merge) -----------------------
#
# Codex P1: `git pull --ff-only` advanced the on-disk checkout BEFORE verify_upstream_trust ran, so a
# denied upstream still moved bin/minervit-methodology to unverified code (the next shim invocation then
# executed it). Fail-closed must mean the working tree NEVER advances to unverified code. These drive
# update_methodology_repo end-to-end against a real temp git repo and assert the checkout HEAD.


def _git_head(repo) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


class _ReExecReached(Exception):
    pass


def test_update_leaves_head_unchanged_when_upstream_untrusted(cli, tmp_path, monkeypatch):
    work, first, second = _init_repo_with_upstream(tmp_path)
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    # origin/main (==second) is NOT pinned, so the advance is refused.
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", first)
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)

    def _no_execve(*a, **k):
        raise AssertionError("os.execve must NOT run when upstream trust is denied")

    monkeypatch.setattr(cli.os, "execve", _no_execve)

    assert _git_head(work) == first
    status, detail = cli.update_methodology_repo(False)

    # No dead ends (operator directive 2026-07-11): the checkout never advanced, so it still runs
    # trusted pinned code -- a safe launch state. The hold is reported as "held" (launch continues)
    # instead of "failed" (launch blocked), and the remedy ships alongside the error text.
    assert status == "held"
    assert "held by the trust policy" in detail
    assert "trusted retained checkout" in detail
    assert "update-repin" in detail, "the remedy must ship alongside the error text"
    assert "refus" in detail.lower()
    assert _git_head(work) == first, "checkout must NOT advance to unverified upstream code"


def test_untrusted_retained_head_stays_fail_closed(cli, tmp_path, monkeypatch):
    # Codex 0.9.1 R1 P1: `held` is only safe when the RETAINED head itself passes the trust
    # policy. With an allowlist containing NEITHER head (empty/replaced pins), the update must
    # stay a fail-closed `failed`, never a `held` launch labeled trusted.
    work, first, second = _init_repo_with_upstream(tmp_path)
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", "c" * 40)  # neither head is pinned
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)

    def _no_execve(*a, **k):
        raise AssertionError("os.execve must NOT run when upstream trust is denied")

    monkeypatch.setattr(cli.os, "execve", _no_execve)

    status, detail = cli.update_methodology_repo(False)

    assert status == "failed"
    assert "does not pass" in detail and "retained checkout" in detail
    assert _git_head(work) == first, "checkout must NOT advance to unverified upstream code"


def test_held_update_does_not_block_sync_methodology_launch(cli, monkeypatch):
    # The launcher keys on sync-methodology's exit code: "held" must exit 0 (launch proceeds on
    # the trusted pinned checkout) while "failed" stays 1. Paired with the test above so the
    # held-vs-failed boundary cannot silently regress in either direction.
    import argparse

    monkeypatch.setattr(cli, "update_methodology_repo", lambda *a, **k: ("held", "update available but held by the trust pin"))
    monkeypatch.setattr(cli, "install_methodology_release_guards", lambda: "guards ok")
    monkeypatch.setattr(cli, "run_git", lambda root, args: "abc1234")
    args = argparse.Namespace(
        target=None,
        skip_update=False,
        allow_non_main=False,
        auto_rescue_local_changes=False,
        no_auto_rescue_local_changes=False,
        no_remote=True,
    )
    assert cli.sync_methodology(args) == 0

    monkeypatch.setattr(cli, "update_methodology_repo", lambda *a, **k: ("failed", "checkout is wedged"))
    assert cli.sync_methodology(args) == 1


def test_update_advances_when_upstream_is_trusted(cli, tmp_path, monkeypatch):
    # Mirror-image GREEN: once the upstream is pinned (repin), update fast-forwards then re-execs.
    work, first, second = _init_repo_with_upstream(tmp_path)
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", second)  # pin advanced to origin/main
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)
    monkeypatch.setattr(cli, "create_methodology_reexec_token", lambda head: "tok")

    def _reached(*a, **k):
        raise _ReExecReached

    monkeypatch.setattr(cli.os, "execve", _reached)

    assert _git_head(work) == first
    with pytest.raises(_ReExecReached):
        cli.update_methodology_repo(False)
    assert _git_head(work) == second, "checkout must advance to the trusted upstream before re-exec"


# --- A4: re-exec token hardening (private dir, 0600, mkstemp) --------------------------------


def test_reexec_token_created_0600_in_private_config_dir(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    token = cli.create_methodology_reexec_token("c" * 40)
    token_path = cli.Path(token)
    token_dir = tmp_path / ".config" / "tautline" / "reexec-tokens"

    assert token_path.parent == token_dir, "token must live under ~/.config/tautline, not the shared tempdir"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_dir.stat().st_mode) == 0o700

    # Round-trips: a token created in the private dir is still consumed as already-updated when the
    # checkout matches (guards against the hardening breaking the happy path).
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REEXEC_TOKEN", token)
    monkeypatch.setattr(cli, "run_git", lambda root, args: "c" * 40 if args[:2] == ["rev-parse", "HEAD"] else "")
    assert cli.consume_methodology_reexec_token() is True


# --- FR-2: the trust-`held` remedy names the actual update ----------------------------------
#
# The RCA case: a pinned machine held an advance and printed `update-repin --channel
# <stable|experimental>` -- no version, and a channel the operator had to guess. Following it in a
# loop never took the update. The held detail now carries the RESOLVED take-it offer, formatted in
# one place (update_methodology_repo, where the candidate's sha/version/channel are all in hand);
# the lane-start and sync-methodology emitters just print that detail.


def _pinned_held_detail(cli, tmp_path, monkeypatch, upstream_version=None, policy="pinned"):
    """Drive the REAL update_methodology_repo to a held outcome and return its detail.

    Deliberately does not monkeypatch update_methodology_repo -- the remedy formatting lives inside
    it, so mocking it would let these tests pass without exercising candidate resolution at all.
    Only the upstream inputs (repo, policy, pins) are driven.
    """
    work, first, second = _init_repo_with_upstream(tmp_path, upstream_version=upstream_version)
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", policy)
    # origin/main (==second) is NOT pinned, so the advance is refused.
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", first)
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)
    monkeypatch.setattr(cli.os, "execve", lambda *a, **k: pytest.fail("must not re-exec on a hold"))
    status, detail = cli.update_methodology_repo(False)
    return status, detail, first, second


def test_held_pinned_remedy_names_the_resolved_version_and_channel(cli, tmp_path, monkeypatch):
    status, detail, _first, _second = _pinned_held_detail(
        cli, tmp_path, monkeypatch, upstream_version="0.99.0"
    )

    assert status == "held"
    # Exactly ONE take-it line: the resolved offer REPLACES the generic remedy, never doubles it.
    assert detail.count("update-repin") == 1
    assert "<stable|experimental>" not in detail, "the channel must be resolved, not left to guess"
    assert "0.99.0 is available" in detail, "the remedy must name the release actually being held"
    assert "tautline sync-methodology --target ." in detail, (
        "the offer must name the taking command"
    )


def test_held_remedy_degrades_to_the_sha_when_version_unreadable(cli, tmp_path, monkeypatch):
    # No VERSION at the candidate: name the commit rather than borrow a version from anywhere else.
    # A wrong version is worse than no version -- it sends the operator to repin a release the hold
    # is not actually about.
    status, detail, _first, second = _pinned_held_detail(cli, tmp_path, monkeypatch)

    assert status == "held"
    assert detail.count("update-repin") == 1
    assert "<stable|experimental>" not in detail
    assert f"the upstream release at {second[:12]} is available" in detail


def test_held_pinned_remedy_uses_the_candidate_not_a_stale_probe(cli, tmp_path, monkeypatch):
    # The display probe resolves independently and can name a DIFFERENT sha than the one being held.
    # The candidate is authoritative: an env-forced probe version must not leak into the remedy.
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", "9.9.9")
    status, detail, _first, _second = _pinned_held_detail(
        cli, tmp_path, monkeypatch, upstream_version="0.99.0"
    )

    assert status == "held"
    assert "0.99.0 is available" in detail
    assert "9.9.9" not in detail


def test_held_signed_policy_keeps_its_own_remedy(cli, tmp_path, monkeypatch):
    # A signed hold is fixed by a valid signature, not by repinning. Its remedy must survive
    # untouched, and no repin offer may be injected into it.
    #
    # A signed HOLD (rather than a fail-closed `failed`) needs the RETAINED head to pass while the
    # candidate does not -- which real signatures cannot produce in a hermetic temp repo. Drive the
    # trust verdict per-head instead; update_methodology_repo itself still runs for real.
    work, first, second = _init_repo_with_upstream(tmp_path, upstream_version="0.99.0")
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "signed")
    monkeypatch.setattr(cli, "consume_methodology_reexec_token", lambda: None)
    monkeypatch.setattr(cli.os, "execve", lambda *a, **k: pytest.fail("must not re-exec on a hold"))
    monkeypatch.setattr(
        cli,
        "verify_upstream_trust",
        lambda head: (False, "not validly signed") if head == second else (True, ""),
    )

    status, detail = cli.update_methodology_repo(False)

    assert status == "held"
    assert "update-repin" not in detail, "a signed hold must not be steered to repinning"
    assert "signature" in detail or "signer" in detail
    assert "0.99.0 is available" not in detail, "no repin offer may be injected into a signed hold"


def test_held_offer_formatter_resolves_the_channel(cli, tmp_path, monkeypatch):
    # Unit-level: the non-stable channel must render as an explicit `--channel <name>` flag, since
    # the whole point of the fix is that the operator never has to pick between the two.
    work, _first, second = _init_repo_with_upstream(tmp_path, upstream_version="0.99.0")
    subprocess.run(
        ["git", "-C", str(work), "fetch", "origin", "main"], check=True, capture_output=True
    )
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", "c" * 40)
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))

    offer = cli._held_candidate_take_it_offer(work, second, "experimental")

    assert offer is not None
    assert "0.99.0 is available" in offer
    assert "tautline update-repin --channel experimental" in offer
    assert not offer.startswith("framework_update_offer: "), (
        "embedded in a detail, not printed as its own line"
    )

    # A non-pinned policy opts out entirely: nothing to rewrite, so the gate's own remedy stands.
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "signed")
    assert cli._held_candidate_take_it_offer(work, second, "experimental") is None


def test_held_refusal_swap_is_fail_safe(cli, tmp_path, monkeypatch):
    # If the gate's remedy text ever changes shape, the swap must return the gate's text untouched
    # rather than dropping the remedy or emitting a half-rewritten one.
    work, _first, second = _init_repo_with_upstream(tmp_path, upstream_version="0.99.0")
    subprocess.run(
        ["git", "-C", str(work), "fetch", "origin", "main"], check=True, capture_output=True
    )
    monkeypatch.setattr(cli, "REPO_ROOT", work)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_POLICY", "pinned")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", "c" * 40)
    monkeypatch.setattr(cli, "METHODOLOGY_UPDATE_PINS_FILE", cli.Path("/nonexistent/pins"))

    unrecognized = "refusing to advance: some future remedy shape"
    assert cli._resolve_held_refusal(unrecognized, work, second, "stable") == unrecognized

    # And the recognized shape IS swapped, with the generic text fully gone.
    recognized = (
        f"refusing to advance: reason; {cli._generic_pinned_advance_remedy()}; see SECURITY.md"
    )
    swapped = cli._resolve_held_refusal(recognized, work, second, "stable")
    assert cli._generic_pinned_advance_remedy() not in swapped
    assert "0.99.0 is available" in swapped
    assert swapped.count("update-repin") == 1


def test_held_remedy_stays_display_only():
    # The offer must never become an input to the update DECISION -- that is the update-prompts
    # invariant this reuses. Structural guard: the held formatters are reachable only from
    # update_methodology_repo, never from the decision or the pre-decision offer renderer.
    source = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")
    for decision_fn in ("def framework_update_decision(", "def framework_update_offer_lines("):
        start = source.index(decision_fn)
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        assert "_held_candidate_take_it_offer" not in body
        assert "_resolve_held_refusal" not in body


def test_both_held_emitters_print_the_detail_verbatim():
    # The resolved remedy is formatted in ONE place (update_methodology_repo). That only holds if
    # BOTH held emitters -- lane_start and _sync_methodology_body -- print the detail they are
    # handed without resolving, reformatting, or appending a competing remedy of their own. An
    # emitter that rebuilt the remedy locally would drift from the other the moment either changed,
    # which is how the generic `<stable|experimental>` text reached the operator on every surface.
    source = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")
    emitter_line = 'print(f"methodology_update: {status} - {detail}")'
    assert source.count(emitter_line) == 2, "expected exactly the lane-start and sync held emitters"

    for enclosing in ("def lane_start(", "def _sync_methodology_body("):
        start = source.index(enclosing)
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        assert emitter_line in body, f"{enclosing} must print the detail verbatim"
        # Neither emitter may resolve a remedy itself -- that is the formatter's single job.
        # (Prose mentions of update-repin in the surrounding comments are fine; calling the
        # resolver or the offer renderer from an emitter is not.)
        assert "_held_candidate_take_it_offer" not in body
        assert "_resolve_held_refusal" not in body
        assert "_framework_update_version_offer" not in body
