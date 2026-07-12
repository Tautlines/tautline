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
    assert f"MINERVIT_METHODOLOGY_UPDATE_PINS={_repo_head()}" in text


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


def _init_repo_with_upstream(tmp_path):
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
    monkeypatch.setenv("MINERVIT_METHODOLOGY_UPDATE_PINS", first)  # origin/main==second is NOT pinned
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
    token_dir = tmp_path / ".config" / "minervit" / "reexec-tokens"

    assert token_path.parent == token_dir, "token must live under ~/.config/minervit, not the shared tempdir"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_dir.stat().st_mode) == 0o700

    # Round-trips: a token created in the private dir is still consumed as already-updated when the
    # checkout matches (guards against the hardening breaking the happy path).
    monkeypatch.setenv("MINERVIT_METHODOLOGY_REEXEC_TOKEN", token)
    monkeypatch.setattr(cli, "run_git", lambda root, args: "c" * 40 if args[:2] == ["rev-parse", "HEAD"] else "")
    assert cli.consume_methodology_reexec_token() is True
