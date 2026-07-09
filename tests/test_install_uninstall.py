"""prod-onboarding-4 (productization): install-cli gains a --dry-run that mutates nothing, and an
uninstall-cli reverses the shim + methodology.env so a tool that edits the user's machine has a
clean off-ramp.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _shim_env(home):
    return {"HOME": str(home), "PATH": os.environ["PATH"]}


def _write_fake_launcher_bin(path: Path) -> None:
    path.mkdir()
    methodology = path / "minervit-methodology"
    methodology.write_text(
        """#!/bin/sh
if [ "$1" = "sync-methodology" ]; then
  echo "fake sync"
  exit 0
fi
if [ "$1" = "goal-kickoff-prompt" ]; then
  echo "fake prompt $*"
  exit 0
fi
if [ "$1" = "lane-start" ]; then
  echo "fake lane-start $*"
  exit 0
fi
if [ "$1" = "methodology-status" ]; then
  echo "fake methodology-status $*"
  exit 0
fi
echo "unexpected methodology command: $*" >&2
exit 2
""",
        encoding="utf-8",
    )
    methodology.chmod(0o755)
    claude = path / "claude"
    claude.write_text(
        """#!/bin/sh
printf 'autocompact:%s\\n' "${CLAUDE_AUTOCOMPACT_PCT_OVERRIDE:-missing}"
printf 'claude_args:'
for arg in "$@"; do
  printf ' [%s]' "$arg"
done
printf '\\n'
""",
        encoding="utf-8",
    )
    claude.chmod(0o755)


def test_install_dry_run_makes_no_changes(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    env = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(env), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "install_cli_dry_run" in res.stdout
    assert not bin_dir.exists(), "dry-run must not create the bin dir"
    assert not env.exists(), "dry-run must not write methodology.env"


def test_install_cli_sources_optional_secrets_file(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    env = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(env))
    assert res.returncode == 0, res.stderr
    text = env.read_text(encoding="utf-8")
    assert "MINERVIT_SECRETS_ENV=" in text
    assert "secrets.zsh" in text
    assert '. "$MINERVIT_SECRETS_ENV"' in text


def test_uninstall_removes_shim_and_env(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    cfg = tmp_path / "cfg" / "methodology.env"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "minervit-methodology"
    shim.write_text("#!/bin/sh\n")
    cfg.parent.mkdir(parents=True)
    cfg.write_text("export X=1\n")
    res = run_cli("uninstall-cli", "--bin-dir", str(bin_dir), "--config-env", str(cfg))
    assert res.returncode == 0, res.stderr
    assert not shim.exists(), "uninstall must remove the shim"
    assert not cfg.exists(), "uninstall must remove methodology.env"
    assert "uninstall_cli_removed" in res.stdout


def test_install_env_sources_user_secrets(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    cfg = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(cfg))
    assert res.returncode == 0, res.stderr
    text = cfg.read_text(encoding="utf-8")
    assert "MINERVIT_SECRETS_ENV=" in text
    assert '. "$MINERVIT_SECRETS_ENV"' in text


def test_install_cli_writes_operational_shim_env_settings_and_preserves_user_env(run_cli, tmp_path):
    home = tmp_path / "home"
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    assert "claude_autocompact_settings:" in res.stdout
    assert "methodology_release_guard:" in res.stdout

    shim = home / ".local" / "bin" / "minervit-methodology"
    cfg = home / ".config" / "minervit" / "methodology.env"
    settings = home / ".claude" / "settings.json"
    assert shim.exists() and os.access(shim, os.X_OK)
    env_text = cfg.read_text(encoding="utf-8")
    assert "MINERVIT_METHODOLOGY_REPO=" in env_text
    assert "MINERVIT_CLAUDE_AUTOCOMPACT_PCT" in env_text
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" in env_text
    assert str(REPO_ROOT) in env_text
    settings_data = json.loads(settings.read_text(encoding="utf-8"))
    assert settings_data["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "85"
    pull_ff = subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "config", "--local", "pull.ff"],
        text=True,
    ).strip()
    assert pull_ff == "only"
    hook_path = Path(
        subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-path", "hooks/pre-commit"],
            text=True,
        ).strip()
    )
    if not hook_path.is_absolute():
        hook_path = REPO_ROOT / hook_path
    assert hook_path.exists() and os.access(hook_path, os.X_OK)
    assert "methodology_release_guard:" in res.stdout

    version = subprocess.run(
        [str(shim), "version", "--no-remote"],
        env=_shim_env(home),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert version.returncode == 0, version.stderr
    assert "plugin_version:" in version.stdout
    sync = subprocess.run(
        [str(shim), "sync-methodology", "--skip-update", "--no-remote"],
        env=_shim_env(home),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert sync.returncode == 0, sync.stderr
    assert "methodology_update: skipped - --skip-update requested" in sync.stdout

    custom_env = 'export MINERVIT_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK="https://example.invalid/product-milestones"'
    with cfg.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{custom_env}\n")
    rerun = run_cli("install-cli")
    assert rerun.returncode == 0, rerun.stderr
    assert custom_env in cfg.read_text(encoding="utf-8")


def test_installed_shim_prefers_configured_repo_over_adjacent_checkout(run_cli, tmp_path):
    home = tmp_path / "home"
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    shim = home / ".local" / "bin" / "minervit-methodology"
    parent = tmp_path / "nearest-methodology-resolution"
    product = parent / "product-lane"
    decoy_bin = parent / "minervit-ai-delivery-methodology" / "bin"
    product.mkdir(parents=True)
    decoy_bin.mkdir(parents=True)
    decoy = decoy_bin / "minervit-methodology"
    decoy.write_text("#!/bin/sh\nprintf '%s\\n' 'nearest-product-methodology'\n", encoding="utf-8")
    decoy.chmod(0o755)

    version = subprocess.run(
        [str(shim), "version", "--no-remote"],
        cwd=str(product),
        env=_shim_env(home),
        text=True,
        capture_output=True,
        timeout=60,
    )
    out = version.stdout + version.stderr
    assert version.returncode == 0, out
    assert "plugin_version:" in out
    assert "nearest-product-methodology" not in out


def test_install_claude_launcher_writes_startup_compatible_script(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode == 0, res.stderr
    assert "installed_claude_launcher:" in res.stdout
    assert "launcher_command: minervit-claude-test" in res.stdout
    assert "launcher_claude_autocompact_pct_override: 85" in res.stdout
    assert "launcher_claude_autocompact_settings:" in res.stdout
    assert "methodology_release_guard:" in res.stdout

    launcher = launcher_bin / "minervit-claude-test"
    assert launcher.exists() and os.access(launcher, os.X_OK)
    settings_data = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings_data["env"]["MINERVIT_CLAUDE_AUTOCOMPACT_PCT"] == "85"
    assert settings_data["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "85"
    assert settings_data["env"]["MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED"] == "1"

    launcher_text = launcher.read_text(encoding="utf-8")
    for marker in (
        '. "$HOME/.config/minervit/methodology.env"',
        "launcher_resolve_methodology_repo",
        "MINERVIT_METHODOLOGY_REPO_PRESET",
        'candidate="$search_dir/minervit-ai-delivery-methodology"',
        'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE="$MINERVIT_CLAUDE_AUTOCOMPACT_PCT"',
        "MINERVIT_CLAUDE_AUTOCOMPACT_REQUIRED=1",
        "claude_autocompact_pct_override:",
        "launcher_auto_rescue_methodology_repo",
        "MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE",
        'minervit-local-rescue/${stamp}-$$-launcher',
        'merge-base --is-ancestor refs/heads/main "$remote_head"',
        "rev-parse --abbrev-ref HEAD",
        'checkout -b "$rescue_branch"',
        "reset --hard origin/main",
        "sync-methodology --auto-rescue-local-changes",
        "sync-methodology --no-auto-rescue-local-changes",
        'LANE_TARGET=""',
        ".minervit-ai-delivery.json",
        'lane-start --target "$LANE_TARGET"',
        'methodology-status --target "$LANE_TARGET" --fail-on-drift',
        'GOAL_TARGET="${LANE_TARGET:-.}"',
        'goal-kickoff-prompt --target "$GOAL_TARGET"',
        "--dangerously-skip-permissions",
    ):
        assert marker in launcher_text
    assert 'git -C "$repo_real" switch' not in launcher_text
    syntax = subprocess.run(["sh", "-n", str(launcher)], text=True, capture_output=True, timeout=60)
    assert syntax.returncode == 0, syntax.stderr


def test_installed_claude_launcher_runs_without_lane_start_outside_adapter(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode == 0, res.stderr
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    launcher = launcher_bin / "minervit-claude-test"
    run = subprocess.run(
        [str(launcher), "--model", "opus"],
        cwd=tmp_path,
        env={
            **_shim_env(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert "fake sync" in run.stdout
    assert "fake lane-start" not in run.stdout
    assert "claude_autocompact_pct_override: 85" in run.stdout
    assert "autocompact:85" in run.stdout
    assert "claude_args: [--dangerously-skip-permissions] [--model] [opus]" in run.stdout


def test_installed_claude_launcher_starts_adapter_lane_from_nested_directory(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode == 0, res.stderr
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    adapter_lane = tmp_path / "adapter-backed-lane"
    nested = adapter_lane / "nested"
    nested.mkdir(parents=True)
    (adapter_lane / ".minervit-ai-delivery.json").write_text("{}\n", encoding="utf-8")

    launcher = launcher_bin / "minervit-claude-test"
    run = subprocess.run(
        [str(launcher), "--model", "sonnet"],
        cwd=nested,
        env={
            **_shim_env(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    lane_real = adapter_lane.resolve()
    assert run.returncode == 0, run.stderr
    assert "fake sync" in run.stdout
    assert f"fake lane-start lane-start --target {lane_real}" in run.stdout
    assert f"fake methodology-status methodology-status --target {lane_real} --fail-on-drift" in run.stdout
    assert "autocompact:85" in run.stdout
    assert "claude_args: [--dangerously-skip-permissions] [--model] [sonnet]" in run.stdout


def test_install_claude_launcher_refuses_non_generated_collision(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    first = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert first.returncode == 0, first.stderr
    custom = launcher_bin / "custom-launcher"
    custom.write_text("# custom launcher\n", encoding="utf-8")

    collision = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", "custom-launcher")
    assert collision.returncode != 0
    assert "not methodology-generated" in collision.stderr


def test_uninstall_keep_env(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    cfg = tmp_path / "cfg" / "methodology.env"
    bin_dir.mkdir(parents=True)
    (bin_dir / "minervit-methodology").write_text("#!/bin/sh\n")
    cfg.parent.mkdir(parents=True)
    cfg.write_text("export X=1\n")
    res = run_cli("uninstall-cli", "--bin-dir", str(bin_dir), "--config-env", str(cfg), "--keep-env")
    assert res.returncode == 0, res.stderr
    assert not (bin_dir / "minervit-methodology").exists()
    assert cfg.exists(), "--keep-env must preserve methodology.env"


def test_uninstall_dry_run_noop(run_cli, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "minervit-methodology"
    shim.write_text("#!/bin/sh\n")
    res = run_cli("uninstall-cli", "--bin-dir", str(bin_dir), "--config-env", str(tmp_path / "none.env"), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert shim.exists(), "dry-run must not remove anything"
    assert "uninstall_cli_dry_run" in res.stdout


# --- A2: --dangerously-skip-permissions interlock -------------------------------------------


def test_skip_permissions_refused_when_policy_not_pinned_or_signed(run_cli, tmp_path):
    # A warn/unverified effective policy must refuse skip-permissions at launcher-install time,
    # naming both the flag and the policy, and write no launcher.
    install = run_cli("install-cli", "--update-policy", "warn")
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode != 0
    assert "--dangerously-skip-permissions" in res.stderr
    assert "warn" in res.stderr
    assert not (launcher_bin / "minervit-claude-test").exists()


def test_skip_permissions_allowed_when_policy_pinned(run_cli, tmp_path):
    install = run_cli("install-cli")  # default pinned
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode == 0, res.stderr
    assert (launcher_bin / "minervit-claude-test").exists()


def test_launcher_rechecks_skip_permissions_policy_at_launch(run_cli, tmp_path):
    # The generated launcher re-checks the effective policy at launch, since it can change after
    # install. Installed under pinned, it runs; after the operator downgrades methodology.env to
    # warn, the same launcher refuses to start.
    install = run_cli("install-cli")  # default pinned
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
        "--dangerously-skip-permissions",
    )
    assert res.returncode == 0, res.stderr
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    launcher = launcher_bin / "minervit-claude-test"
    launch_env = {
        **_shim_env(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
    }

    proceeds = subprocess.run(
        [str(launcher)], cwd=tmp_path, env=launch_env, text=True, capture_output=True, timeout=60
    )
    assert proceeds.returncode == 0, proceeds.stderr
    assert "fake sync" in proceeds.stdout

    methodology_env = home / ".config" / "minervit" / "methodology.env"
    downgraded = methodology_env.read_text(encoding="utf-8").replace(
        "MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned", "MINERVIT_METHODOLOGY_UPDATE_POLICY=warn"
    )
    methodology_env.write_text(downgraded, encoding="utf-8")

    refused = subprocess.run(
        [str(launcher)], cwd=tmp_path, env=launch_env, text=True, capture_output=True, timeout=60
    )
    assert refused.returncode != 0
    assert "--dangerously-skip-permissions" in refused.stderr
    assert "warn" in refused.stderr
    assert "fake sync" not in refused.stdout

# --- Codex P1: launcher shell auto-rescue must not advance the checkout ungated ---------------
#
# launcher_auto_rescue_methodology_repo() does a raw `git fetch` + `reset --hard origin/main` with
# NO pin/signature check, BEFORE sync-methodology runs. On a pinned install with a dirty/stale
# checkout that advances the on-disk bin/minervit-methodology to unpinned upstream and then executes
# it -- the same advance-before-verify defect update_methodology_repo had. Under a verifying policy
# (pinned/signed) the shell rescue must be skipped so the trust-gated Python rescue inside
# sync-methodology (verify-before-advance) owns recovery; under legacy warn it still rescues.


def _git_out(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _init_launcher_methodology_repo(tmp_path):
    """Temp methodology checkout with a committed fake CLI, an origin advanced one commit past the
    local (stale) HEAD, and dirty local changes -- the state that triggers the launcher rescue."""
    upstream = tmp_path / "meth-upstream.git"
    repo = tmp_path / "methrepo"
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
    }
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    fake_cli = repo / "bin" / "minervit-methodology"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_text("#!/bin/sh\necho repo-cli \"$@\"\nexit 0\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    (repo / "f.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "one"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True, env=env)
    first = _git_out(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "two"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "push", "origin", "main"], check=True, capture_output=True, env=env)
    second = _git_out(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(repo), "reset", "--hard", first], check=True, capture_output=True, env=env)
    (repo / "f.txt").write_text("local-edit\n", encoding="utf-8")  # dirty -> rescue path triggers
    return repo, first, second


def _install_plain_launcher(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli(
        "install-claude-launcher",
        "--bin-dir",
        str(launcher_bin),
        "--name",
        "minervit-claude-test",
    )
    assert res.returncode == 0, res.stderr
    return launcher_bin / "minervit-claude-test"


def _launcher_rescue_env(tmp_path, repo, fake_bin, **extra):
    # Empty HOME (no methodology.env) so the inherited env controls the policy; no
    # MINERVIT_METHODOLOGY_CLI preset so the shell auto-rescue path actually runs.
    launch_home = tmp_path / "launch-home"
    launch_home.mkdir(exist_ok=True)
    return {
        "HOME": str(launch_home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "MINERVIT_METHODOLOGY_REPO": str(repo),
        **extra,
    }


def test_launcher_shell_rescue_never_advances_checkout_under_pinned_policy(run_cli, tmp_path):
    launcher = _install_plain_launcher(run_cli, tmp_path)
    repo, first, second = _init_launcher_methodology_repo(tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    assert _git_out(repo, "rev-parse", "HEAD") == first
    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_launcher_rescue_env(
            tmp_path,
            repo,
            fake_bin,
            MINERVIT_METHODOLOGY_UPDATE_POLICY="pinned",
            MINERVIT_METHODOLOGY_UPDATE_PINS=first,
        ),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert _git_out(repo, "rev-parse", "HEAD") == first, (
        "launcher shell auto-rescue must NOT advance a pinned methodology checkout to unverified "
        f"upstream (origin/main={second[:12]})"
    )
    # The launcher proceeds with the existing (old, still-trusted) checkout: the trust-gated
    # sync-methodology rescue owns recovery, and the skip is surfaced to the operator.
    assert run.returncode == 0, run.stderr
    assert "auto-rescue skipped under update policy pinned" in run.stderr
    assert "fake sync" in run.stdout


def test_launcher_shell_rescue_still_rescues_under_legacy_warn_policy(run_cli, tmp_path):
    # No-over-block guard: a legacy install without a verifying policy keeps the existing shell
    # rescue behavior (preserve local changes on a rescue branch, reset main to origin/main).
    launcher = _install_plain_launcher(run_cli, tmp_path)
    repo, first, second = _init_launcher_methodology_repo(tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_launcher_rescue_env(tmp_path, repo, fake_bin),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert _git_out(repo, "rev-parse", "HEAD") == second
    assert "launcher_auto_rescue - preserved local methodology checkout" in run.stdout
