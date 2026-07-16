"""prod-onboarding-4 (productization): install-cli gains a --dry-run that mutates nothing, and an
uninstall-cli reverses the shim + methodology.env so a tool that edits the user's machine has a
clean off-ramp.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

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
  exit "${FAKE_METHODOLOGY_STATUS_EXIT:-0}"
fi
if [ "$1" = "snapshot-pin" ]; then
  echo "fake snapshot-pin $*"
  exit 0
fi
echo "unexpected methodology command: $*" >&2
exit 2
""",
        encoding="utf-8",
    )
    methodology.chmod(0o755)
    # Launchers resolve `tautline` FIRST: without this twin, a machine with a real
    # installed tautline shim leaks its user config into the hermetic test run.
    tautline = path / "tautline"
    tautline.write_text(methodology.read_text(encoding="utf-8"), encoding="utf-8")
    tautline.chmod(0o755)
    claude = path / "claude"
    claude.write_text(
        """#!/bin/sh
printf 'autocompact:%s\\n' "${CLAUDE_AUTOCOMPACT_PCT_OVERRIDE:-missing}"
printf 'exec_root:%s\\n' "${MINERVIT_METHODOLOGY_EXEC_ROOT:-missing}"
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


def test_shim_survives_unbound_variable_in_user_secrets(run_cli, tmp_path):
    """The shim runs set -eu and sources methodology.env -> the user's secrets file.
    A secrets line referencing a variable that is unset in the invoking environment
    (cron, git hooks, CI) must degrade gracefully, not kill every CLI invocation."""
    bin_dir = tmp_path / "bin"
    env = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(env))
    assert res.returncode == 0, res.stderr

    secrets_line = next(
        line for line in env.read_text(encoding="utf-8").splitlines()
        if line.startswith("MINERVIT_SECRETS_ENV=")
    )
    secrets_path = Path(secrets_line.split("=", 1)[1].strip("'\""))
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text('export MY_TOKEN="$USER-suffix"\n', encoding="utf-8")

    shim = bin_dir / "tautline"
    run = subprocess.run(
        [str(shim), "version"],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "shim-home"),
            "MINERVIT_METHODOLOGY_REPO": str(REPO_ROOT),
            # deliberately NO USER in the environment
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 0, f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    assert "unbound variable" not in run.stderr


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


# --- T4 (0.8.9 startup remediation): three-way $? dispatch on methodology-status -------------
#
# See .superpowers/sdd/task-089-T4-brief.md ("Launcher behavior (template change + truthful
# refusal)"). The fake methodology-status branch in _write_fake_launcher_bin honors
# FAKE_METHODOLOGY_STATUS_EXIT (default 0, unset by every test above this section, so those stay
# on the unchanged exit-0 path).


def _adapter_lane(tmp_path: Path) -> Path:
    adapter_lane = tmp_path / "adapter-backed-lane"
    adapter_lane.mkdir(parents=True)
    (adapter_lane / ".minervit-ai-delivery.json").write_text("{}\n", encoding="utf-8")
    return adapter_lane


def test_launcher_text_never_mentions_adapter_drift(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", "minervit-claude-test")
    assert res.returncode == 0, res.stderr
    launcher_text = (launcher_bin / "minervit-claude-test").read_text(encoding="utf-8")
    assert "adapter drift" not in launcher_text
    assert 'launcher_gate_repair "methodology-status integrity"' in launcher_text
    assert "launcher_gate_repair" in launcher_text
    assert "remedy: $remedy" in launcher_text, "the remedy must ship alongside the error text"
    assert "--enter-remediation-on-debt" in launcher_text
    assert "--defer-debt-preflights" in launcher_text
    assert "Startup remediation required for this lane." in launcher_text


def test_installed_claude_launcher_exit_2_execs_remediation_prompt_only(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", "minervit-claude-test")
    assert res.returncode == 0, res.stderr
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    adapter_lane = _adapter_lane(tmp_path)

    launcher = launcher_bin / "minervit-claude-test"
    run = subprocess.run(
        [str(launcher), "--model", "opus", "a user-typed prompt"],
        cwd=adapter_lane,
        env={
            **_shim_env(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
            "FAKE_METHODOLOGY_STATUS_EXIT": "2",
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    lane_real = adapter_lane.resolve()
    assert run.returncode == 0, run.stderr
    assert "fake sync" in run.stdout
    assert f"fake lane-start lane-start --target {lane_real} --defer-debt-preflights" in run.stdout
    assert (
        f"fake methodology-status methodology-status --target {lane_real} --fail-on-drift --enter-remediation-on-debt"
        in run.stdout
    )
    assert "fake prompt" not in run.stdout, "goal-kickoff-prompt must be skipped on the exit-2 path"
    claude_lines = [line for line in run.stdout.splitlines() if line.startswith("claude_args:")]
    assert len(claude_lines) == 1
    args_line = claude_lines[0]
    assert args_line.count("[") == 1, f"exactly one positional argument must reach claude: {args_line}"
    assert args_line.startswith("claude_args: [Startup remediation required for this lane.")
    assert f"--target {lane_real} --fail-on-drift" in args_line
    assert "a user-typed prompt" not in args_line
    assert "--model" not in args_line
    assert "opus" not in args_line


def test_installed_claude_launcher_exit_1_refuses_without_exec(run_cli, tmp_path):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    home = tmp_path / "home"
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", "minervit-claude-test")
    assert res.returncode == 0, res.stderr
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    adapter_lane = _adapter_lane(tmp_path)

    launcher = launcher_bin / "minervit-claude-test"
    run = subprocess.run(
        [str(launcher), "--model", "opus"],
        cwd=adapter_lane,
        env={
            **_shim_env(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
            "FAKE_METHODOLOGY_STATUS_EXIT": "1",
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 1
    assert "claude_args:" not in run.stdout, "exit 1 must never exec claude"
    combined = run.stdout + run.stderr
    assert "launch gate failed: methodology-status integrity" in combined
    assert "remedy:" in combined, "the remedy must ship alongside the error text"
    assert "adapter drift" not in combined


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

    # 0.9.2 rebrand: install-cli writes the tautline env + a byte-identical legacy mirror; the
    # launcher reads the tautline path first. Downgrade both, as install-cli/update-repin keep both.
    for env_file in (
        home / ".config" / "tautline" / "tautline.env",
        home / ".config" / "minervit" / "methodology.env",
    ):
        downgraded = env_file.read_text(encoding="utf-8").replace(
            "MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned", "MINERVIT_METHODOLOGY_UPDATE_POLICY=warn"
        )
        env_file.write_text(downgraded, encoding="utf-8")

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


# --- Task B8: install-cli bootstraps the snapshot store ---------------------------------------
#
# install-cli is the cutover: it writes the two managed store keys, materializes HEAD, and points
# `current` at it. From that moment the shim executes the snapshot -- but any launcher generated
# BEFORE the cutover still starts sessions that are UNPINNED against `current`, so install-cli
# and sync-methodology must both say so, starkly, until the launcher is regenerated.

STORE_REL = Path(".local") / "share" / "minervit" / "tautline-releases"
LAUNCHER_GENERATED_MARKER = "# Generated by tautline install-claude-launcher."


def _git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _snapshot_of_working_tree(dest: Path) -> Path:
    """A realistic snapshot: HEAD's exported tree (no .git), with the CLI *under test* dropped in.

    `git archive HEAD` cannot see uncommitted work, and the whole point of this fixture is to run
    the code we are writing, so bin/tautline is overwritten from the working tree.
    """
    import tarfile

    dest.mkdir(parents=True)
    tar_path = dest.parent / "snapshot.tar"
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(tar_path), "HEAD"],
        check=True, capture_output=True,
    )
    with tarfile.open(tar_path) as tar:
        tar.extractall(dest)  # noqa: S202 - our own git archive output
    tar_path.unlink()
    cli = dest / "bin" / "tautline"
    cli.write_text((REPO_ROOT / "bin" / "tautline").read_text(encoding="utf-8"), encoding="utf-8")
    cli.chmod(0o755)
    (dest / ".snapshot-meta.json").write_text(
        json.dumps(
            {
                "schema": "tautline-snapshot/v1",
                "commit": _git_head(REPO_ROOT),
                "channel": "stable",
            }
        ),
        encoding="utf-8",
    )
    return dest


def _fixture_canonical_repo(path: Path) -> str:
    """A minimal but REAL canonical checkout: a git repo carrying bin/tautline + VERSION."""
    (path / "bin").mkdir(parents=True)
    (path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    cli = path / "bin" / "tautline"
    cli.write_text("#!/bin/sh\nprintf 'canonical-fixture\\n'\n", encoding="utf-8")
    cli.chmod(0o755)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "T"],
        ["add", "-A"],
        ["commit", "-q", "-m", "canonical fixture"],
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    return _git_head(path)


def test_install_cli_writes_both_snapshot_managed_keys(run_cli, tmp_path):
    home = tmp_path / "home"
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    text = (home / ".config" / "tautline" / "tautline.env").read_text(encoding="utf-8")
    store = home / STORE_REL
    assert f"export TAUTLINE_METHODOLOGY_SNAPSHOT_STORE={store}" in text, text
    assert f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={store}" in text, text
    assert f"export TAUTLINE_METHODOLOGY_CANONICAL_REPO={REPO_ROOT}" in text, text
    assert f"export MINERVIT_METHODOLOGY_CANONICAL_REPO={REPO_ROOT}" in text, text


def test_install_cli_materializes_head_and_swaps_current(run_cli, tmp_path):
    home = tmp_path / "home"
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    assert "methodology_snapshot: materialized" in res.stdout, res.stdout
    store = home / STORE_REL
    head = _git_head(REPO_ROOT)
    snapshot = store / head[:12]
    assert (snapshot / "bin" / "tautline").is_file(), sorted(p.name for p in store.iterdir())
    assert (store / "current").is_symlink()
    assert (store / "current").resolve() == snapshot.resolve()
    manifest = json.loads((snapshot / ".snapshot-meta.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == head


def test_install_cli_dry_run_prints_store_actions_and_mutates_nothing(run_cli, tmp_path):
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    cfg = tmp_path / "cfg" / "methodology.env"
    res = run_cli("install-cli", "--bin-dir", str(bin_dir), "--config-env", str(cfg), "--dry-run")
    assert res.returncode == 0, res.stderr
    store = home / STORE_REL
    assert f"materialize snapshot of {REPO_ROOT}" in res.stdout, res.stdout
    assert str(store) in res.stdout, res.stdout
    assert not store.exists(), "dry-run must not materialize a snapshot"


def test_install_cli_demands_launcher_reinstall(run_cli, tmp_path):
    """DEFERRED REVIEW FINDING (shared with B9): between install-cli (snapshot mode ON) and
    `install-claude-launcher --force` (session-pinned exec root ON), a still-v1 launcher starts
    sessions that run UNPINNED against `current` and can hop versions mid-session. Say so."""
    home = tmp_path / "home"
    stale = home / ".local" / "bin" / "tautline-claude"
    stale.parent.mkdir(parents=True)
    stale.write_text(f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\nexec claude\n", encoding="utf-8")
    stale.chmod(0o755)
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "tautline install-claude-launcher --force" in out, out
    assert "UNPINNED" in out, out
    assert str(stale) in out, out  # the stale launcher is NAMED, not just alluded to
    assert res.stdout.rstrip().splitlines()[-1].startswith("next_step_required:"), res.stdout


def test_sync_methodology_warns_while_launcher_is_stale(run_cli, tmp_path):
    home = tmp_path / "home"
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    stale = home / ".local" / "bin" / "tautline-claude"
    stale.write_text(f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\nexec claude\n", encoding="utf-8")
    stale.chmod(0o755)
    res = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert res.returncode == 0, res.stderr
    assert "tautline install-claude-launcher --force" in res.stderr, res.stderr
    assert str(stale) in res.stderr, res.stderr


# --- the launcher scan runs on EVERY sync, over a real bin dir --------------------------------
#
# ~/.local/bin is not ours: it holds whatever the operator installed there, including compiled
# binaries and multi-megabyte single-file tools. stale_claude_launchers() slurps every entry as
# text, and it does so on every lane start. Guard it on what a launcher can actually BE -- a
# regular file, small, and textual -- so the scan costs a header read per entry instead of a full
# decode of everything on the machine.


def _compiled_binary(path: Path) -> Path:
    """A file that looks like what it is: an ELF header, NUL bytes, and megabytes of payload."""
    path.write_bytes(b"\x7fELF\x02\x01\x01\x00" + bytes(4 * 1024 * 1024))
    path.chmod(0o755)
    return path


def test_launcher_scan_skips_binaries_directories_and_oversized_files(cli, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = _compiled_binary(bin_dir / "compiled-tool")
    oversized = bin_dir / "huge-generated-script"
    oversized.write_text("#!/bin/sh\n" + "x" * cli.LAUNCHER_SCAN_MAX_BYTES, encoding="utf-8")
    (bin_dir / "a-directory").mkdir()
    stale = bin_dir / "tautline-claude"
    stale.write_text(f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\nexec claude\n", encoding="utf-8")
    stale.chmod(0o755)

    # None of these can be a launcher, and none of them is read as one.
    assert cli._launcher_text(binary) is None
    assert cli._launcher_text(oversized) is None
    assert cli._launcher_text(bin_dir / "a-directory") is None
    # ...and the guard did not blind the scan to the launcher it exists to find.
    assert cli._launcher_text(stale) is not None
    assert cli.stale_claude_launchers(bin_dir) == [stale]


def test_sync_survives_a_binary_in_the_user_bin_dir(run_cli, tmp_path):
    """End to end: a compiled binary sitting next to the launcher must not break the sync."""
    home = tmp_path / "home"
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    binary = _compiled_binary(bin_dir / "compiled-tool")
    stale = bin_dir / "tautline-claude"
    stale.write_text(f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\nexec claude\n", encoding="utf-8")
    stale.chmod(0o755)

    res = run_cli("sync-methodology", "--skip-update", "--no-remote")

    assert res.returncode == 0, res.stderr
    assert str(stale) in res.stderr, res.stderr        # the launcher is still named
    assert str(binary) not in res.stderr, res.stderr   # the binary never is


def test_sync_methodology_is_quiet_once_the_launcher_is_regenerated(run_cli, tmp_path):
    home = tmp_path / "home"
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    current = home / ".local" / "bin" / "tautline-claude"
    current.write_text(
        f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\n# tautline-launcher-template: 2\nexec claude\n",
        encoding="utf-8",
    )
    current.chmod(0o755)
    res = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert res.returncode == 0, res.stderr
    assert "install-claude-launcher --force" not in res.stderr, res.stderr


def test_uninstall_cli_reports_retained_snapshot_store(run_cli, tmp_path):
    home = tmp_path / "home"
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    store = home / STORE_REL
    res = run_cli("uninstall-cli")
    assert res.returncode == 0, res.stderr
    assert str(store) in res.stdout, res.stdout
    # A published snapshot is 0555/0444: a bare `rm -rf` is DENIED, so the instruction must not
    # hand the operator a command that fails on their own machine.
    assert f"chmod -R u+w {store}" in res.stdout, res.stdout
    assert store.is_dir(), "the store is retained: other sessions may still be executing it"


def test_install_cli_from_snapshot_materializes_canonical(tmp_path):
    """install-cli's normal post-migration path runs FROM the immutable snapshot. Every piece of
    state it writes must derive from the CANONICAL checkout: point methodology.env at the snapshot
    and the next reinstall has no repo to sync, no pin to trust, and no way to rebuild the store."""
    snapshot = _snapshot_of_working_tree(tmp_path / "snapshot")
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    canonical_head = _fixture_canonical_repo(canonical)
    home = tmp_path / "home"
    home.mkdir()
    res = subprocess.run(
        [str(snapshot / "bin" / "tautline"), "install-cli"],
        env={
            "HOME": str(home),
            "PATH": os.environ["PATH"],
            "MINERVIT_METHODOLOGY_CANONICAL_REPO": str(canonical),
        },
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, res.stderr
    text = (home / ".config" / "tautline" / "tautline.env").read_text(encoding="utf-8")
    assert f"export MINERVIT_METHODOLOGY_REPO={canonical}" in text, text
    assert f"export TAUTLINE_METHODOLOGY_REPO={canonical}" in text, text
    assert f"export MINERVIT_METHODOLOGY_CANONICAL_REPO={canonical}" in text, text
    assert f"export MINERVIT_METHODOLOGY_UPDATE_PINS={canonical_head}" in text, text
    assert str(snapshot) not in text, "no managed key may name the immutable snapshot"
    store = home / STORE_REL
    assert (store / canonical_head[:12] / "bin" / "tautline").is_file(), res.stdout
    assert (store / "current").resolve() == (store / canonical_head[:12]).resolve()
    assert f"methodology_repo: {canonical}" in res.stdout, res.stdout


# --- Task B9: launcher template v2 -------------------------------------------------------------
#
# The v1 launcher derived the "methodology repo" from wherever the CLI happened to live and then
# probed it with `version --no-remote`. Under the store that is a trap: the CLI lives in an
# IMMUTABLE snapshot, so the launcher would hand sync a tree with no .git and no origin. v2 severs
# that fallback, gates the sync (--launcher-gate), and pins the session to the snapshot it is
# actually going to execute by exporting the RESOLVED exec root -- resolved, because another lane
# swapping `current` mid-session must not move this session's code.

LAUNCHER_TEMPLATE_MARKER = "# tautline-launcher-template: 2"
STATE_REL = Path(".local") / "state" / "minervit"
LAUNCHER_RECORD_REL = STATE_REL / "installed-launchers.json"


def _v1_launcher_text() -> str:
    """A pre-cutover launcher: our generated header, no template marker."""
    return f"#!/bin/sh\n{LAUNCHER_GENERATED_MARKER}\nexec claude\n"


def _install_v2_launcher(run_cli, tmp_path, name="tautline-claude-test"):
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    launcher_bin = tmp_path / "launcher-bin"
    res = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", name)
    assert res.returncode == 0, res.stderr
    return launcher_bin / name


def _launch(launcher: Path, home: Path, fake_bin: Path, cwd: Path, **extra):
    return subprocess.run(
        [str(launcher)],
        cwd=cwd,
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "MINERVIT_METHODOLOGY_CLI": str(fake_bin / "minervit-methodology"),
            **extra,
        },
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_launcher_v2_gates_sync_and_severs_the_cli_location_fallback(run_cli, tmp_path):
    launcher = _install_v2_launcher(run_cli, tmp_path)
    text = launcher.read_text(encoding="utf-8")
    assert LAUNCHER_TEMPLATE_MARKER in text, text
    # All three sync variants are gated: without the gate, every lane on a launch storm fetches.
    assert '"$METHODOLOGY_CLI" sync-methodology --launcher-gate' in text, text
    assert "sync-methodology --auto-rescue-local-changes --launcher-gate" in text, text
    assert "sync-methodology --no-auto-rescue-local-changes --launcher-gate" in text, text
    assert 'snapshot-pin --target "${LANE_TARGET:-$PWD}"' in text, text
    # The severed fallback: neither the CLI's own location nor its `version` output may define the
    # canonical checkout, or a snapshot-executed launcher would point sync at an immutable tree.
    assert "version --no-remote" not in text, text
    assert 'dirname "$METHODOLOGY_CLI"' not in text, text
    syntax = subprocess.run(["sh", "-n", str(launcher)], text=True, capture_output=True, timeout=60)
    assert syntax.returncode == 0, syntax.stderr


def test_launcher_exports_resolved_snapshot_exec_root(run_cli, tmp_path):
    """The session is pinned to a RESOLVED <sha12>, never to the `current` symlink: another lane's
    sync can swap `current` mid-session, and a session that followed the symlink on every hook
    invocation would hop Tautline versions inside one conversation."""
    home = tmp_path / "home"
    launcher = _install_v2_launcher(run_cli, tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    store = home / STORE_REL
    snapshot = (store / _git_head(REPO_ROOT)[:12]).resolve()

    run = _launch(launcher, home, fake_bin, tmp_path)
    assert run.returncode == 0, run.stderr
    exec_roots = [
        line.split(":", 1)[1]
        for line in run.stdout.splitlines()
        if line.startswith("exec_root:")
    ]
    assert exec_roots == [str(snapshot)], run.stdout
    assert "current" not in exec_roots[0], "the symlink path must never reach the session"
    assert "fake snapshot-pin snapshot-pin --target" in run.stdout, run.stdout


def test_launcher_warns_and_skips_export_when_current_is_dangling(run_cli, tmp_path):
    home = tmp_path / "home"
    launcher = _install_v2_launcher(run_cli, tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    current = home / STORE_REL / "current"
    current.unlink()
    current.symlink_to(home / STORE_REL / "deleted-by-prune")

    run = _launch(launcher, home, fake_bin, tmp_path)
    assert run.returncode == 0, run.stderr
    assert "exec_root:missing" in run.stdout, run.stdout
    assert "methodology_snapshot: store missing or broken" in run.stderr, run.stderr


def test_install_claude_launcher_records_the_installed_launcher(run_cli, tmp_path):
    home = tmp_path / "home"
    launcher = _install_v2_launcher(run_cli, tmp_path)
    record = json.loads((home / LAUNCHER_RECORD_REL).read_text(encoding="utf-8"))
    assert str(launcher) in record["launchers"], record


def test_sync_warns_on_unrecorded_launchers_in_snapshot_mode(run_cli, tmp_path):
    """The other half of B8's deferred finding. A v1 launcher predates the recorder, so an ABSENT
    state file is not evidence of a clean machine -- it is evidence we cannot tell, and sync must
    say so rather than let a pre-cutover launcher keep starting unpinned sessions in silence."""
    home = tmp_path / "home"
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr
    assert not (home / LAUNCHER_RECORD_REL).exists()

    unknown = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert unknown.returncode == 0, unknown.stderr
    assert (
        "launcher_template: unknown - rerun tautline install-claude-launcher to record and "
        "upgrade launchers"
    ) in unknown.stdout, unknown.stdout

    launcher_bin = tmp_path / "launcher-bin"
    name = "tautline-claude-test"
    installed = run_cli("install-claude-launcher", "--bin-dir", str(launcher_bin), "--name", name)
    assert installed.returncode == 0, installed.stderr
    quiet = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert quiet.returncode == 0, quiet.stderr
    assert "launcher_template:" not in quiet.stdout, quiet.stdout

    # Downgrade the recorded launcher back to v1: the recorder knows where it is, so the staleness
    # is caught even though this bin dir is not USER_BIN_DIR and nothing else scans it.
    (launcher_bin / name).write_text(_v1_launcher_text(), encoding="utf-8")
    stale = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert stale.returncode == 0, stale.stderr
    expected = "launcher_template: stale - rerun tautline install-claude-launcher"
    assert expected in stale.stdout, stale.stdout


def test_sync_is_silent_about_launchers_without_snapshot_mode(run_cli, tmp_path):
    # No install-cli: no managed store key, so snapshot mode is OFF and neither check may fire --
    # a pre-cutover machine has no session exec root to be missing.
    home = tmp_path / "home"
    record = home / LAUNCHER_RECORD_REL
    record.parent.mkdir(parents=True)
    stale_launcher = tmp_path / "legacy-bin" / "tautline-claude"
    stale_launcher.parent.mkdir(parents=True)
    stale_launcher.write_text(_v1_launcher_text(), encoding="utf-8")
    record.write_text(
        json.dumps(
            {
                "schema": "tautline-installed-launchers/v1",
                "launchers": [str(stale_launcher)],
            }
        ),
        encoding="utf-8",
    )
    res = run_cli("sync-methodology", "--skip-update", "--no-remote")
    assert res.returncode == 0, res.stderr
    assert "launcher_template:" not in res.stdout + res.stderr, res.stdout + res.stderr


# --- Task B12: the migration cutover, end to end ------------------------------------------------
#
# Every existing machine is pre-cutover: a methodology.env with no store keys and a shim that execs
# the canonical checkout directly. `install-cli` is the single command that converts it, and the
# conversion has to hold two things at once that the v1 world conflated: the CLI now EXECUTES an
# immutable snapshot, while MINERVIT_METHODOLOGY_REPO keeps naming the mutable checkout that sync
# fetches into. If the cutover leaks the snapshot into that variable, sync has no `.git` to advance
# and the machine is stranded on the version it installed.

LEGACY_CONFIG_REL = Path(".config") / "minervit" / "methodology.env"
CONFIG_REL = Path(".config") / "tautline" / "tautline.env"
PRESERVED_SECRET = "https://hooks.example.invalid/T000/B000/preserved"


def _unlock_and_remove(path: Path) -> None:
    """Delete a published store the way uninstall-cli tells operators to.

    Snapshot dirs are 0555 and their files 0444, so a bare rmtree dies on the first unlink: the
    parent directory has to be writable to remove an entry from it.
    """
    import shutil

    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir() and not child.is_symlink():
            child.chmod(0o755)
    path.chmod(0o755)
    shutil.rmtree(path)


def _pre_cutover_machine(home: Path, canonical: Path) -> Path:
    """A machine as the pre-snapshot release left it: MINERVIT_-only env, no store keys, and a
    shim whose only job is to exec the canonical checkout."""
    config = home / LEGACY_CONFIG_REL
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "# Generated by minervit-methodology install-cli.\n"
        f"export MINERVIT_METHODOLOGY_REPO={canonical}\n"
        "export MINERVIT_METHODOLOGY_UPDATE_POLICY=pinned\n"
        "\n# Preserved local user/project environment. Do not commit these values.\n"
        f"export MINERVIT_SLACK_WEBHOOK_URL={PRESERVED_SECRET}\n",
        encoding="utf-8",
    )
    shim = home / ".local" / "bin" / "tautline"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f'CONFIG_ENV="$HOME/{LEGACY_CONFIG_REL.as_posix()}"\n'
        'if [ -f "$CONFIG_ENV" ]; then\n'
        '  . "$CONFIG_ENV"\n'
        "fi\n"
        "export MINERVIT_METHODOLOGY_REPO\n"
        'exec "$MINERVIT_METHODOLOGY_REPO/bin/tautline" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _shim_run(shim: Path, home: Path, *args: str) -> subprocess.CompletedProcess:
    """A hook-style invocation: bare `tautline`, no launcher, no inherited exec root."""
    return subprocess.run(
        [str(shim), *args],
        env=_shim_env(home),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_pre_to_post_migration_cutover(run_cli, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    shim = _pre_cutover_machine(home, REPO_ROOT)
    store = home / STORE_REL

    # BEFORE: the old shim execs the checkout in place. There is no store, and nothing warns --
    # a machine that has not been converted must not be nagged about a store it never had.
    before = _shim_run(shim, home, "version", "--no-remote")
    assert before.returncode == 0, before.stderr
    assert f"methodology_exec_root: {REPO_ROOT} (canonical checkout)" in before.stdout, before.stdout
    assert not store.exists()
    assert "snapshot store" not in before.stderr, before.stderr

    # THE CUTOVER: one command, run from the canonical checkout, over the old machine's state.
    install = run_cli("install-cli")
    assert install.returncode == 0, install.stderr

    config = (home / CONFIG_REL).read_text(encoding="utf-8")
    assert f"export MINERVIT_METHODOLOGY_REPO={REPO_ROOT}" in config, config
    assert f"export MINERVIT_METHODOLOGY_SNAPSHOT_STORE={store}" in config, config
    # The webhook the operator hand-added to the pre-cutover file survives the rewrite: a cutover
    # that silently drops local secrets is a cutover nobody runs twice.
    assert f"export MINERVIT_SLACK_WEBHOOK_URL={PRESERVED_SECRET}" in config, config

    # A sentinel INSIDE the published snapshot: the only thing that can distinguish "the shim
    # exec'd the store" from "the shim exec'd the checkout and the checkout reported a store".
    head = _git_head(REPO_ROOT)
    snapshot = (store / head[:12]).resolve()
    snapshot_cli = snapshot / "bin" / "tautline"
    snapshot_cli.chmod(0o755)
    snapshot_cli.write_text(
        "#!/bin/sh\n"
        "printf 'snapshot_sentinel: %s\\n' \"$0\"\n"
        "printf 'methodology_repo_env: %s\\n' \"${MINERVIT_METHODOLOGY_REPO:-missing}\"\n",
        encoding="utf-8",
    )
    snapshot_cli.chmod(0o755)

    # AFTER: the same shim path, the same bare invocation a Claude hook makes -- now the process
    # image is the file inside the immutable store...
    after = _shim_run(shim, home, "methodology-status")
    assert after.returncode == 0, after.stderr
    assert f"snapshot_sentinel: {snapshot_cli}" in after.stdout, after.stdout
    # ...while the repo sync manages is still the mutable canonical checkout. Leak the snapshot
    # into this variable and the next `sync-methodology` has no `.git` to fetch into.
    assert f"methodology_repo_env: {REPO_ROOT}" in after.stdout, after.stdout

    # ROLLBACK / DISASTER: the store is gone (wiped by hand, restored from a backup that skipped
    # ~/.local/share, deleted by an over-eager cleaner). The shim must say so once and keep the
    # machine working off the checkout -- degradation, never a dead CLI.
    _unlock_and_remove(store)
    fallback = _shim_run(shim, home, "version", "--no-remote")
    assert fallback.returncode == 0, fallback.stderr
    assert "snapshot store current link missing or broken" in fallback.stderr, fallback.stderr
    assert (
        f"methodology_exec_root: {REPO_ROOT} (canonical checkout)" in fallback.stdout
    ), fallback.stdout
    assert "snapshot_sentinel" not in fallback.stdout, fallback.stdout


# --- Maintainer standdown T5: launcher shell hardening + interlock regression locks ------------
#
# The shell auto-rescue is an update gate, so an armed maintainer mode must stand it down BEFORE
# any git mutation -- and the shell guard must read the armed state from the same place Python
# does: the installed config env file, PARSED (never sourced, never the ambient environment).
# Inherited live values and values exported by sourced secrets files can therefore neither arm
# nor disarm it, which is exactly the shell/Python divergence R1 finding MS-R1-P1-2 named.
#
# No test here invokes the `maintainer-mode` verb: T5 executes before T4, so the verb does not
# exist at this task's boundary. Every fixture that needs the mode on writes the export line(s)
# into the hermetic config env file directly, exactly as the verb will.

MAINTAINER_MODE_EXPORTS_AS_VERB_WRITES = [
    "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1",
    "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
]


def _write_launch_home_config(launch_home: Path, lines: list[str]) -> Path:
    """The launcher's config env file in a hermetic launch HOME (the tautline path it reads
    first), written directly -- the T5 boundary has no verb to write it for us."""
    config = launch_home / ".config" / "tautline" / "tautline.env"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _rescue_repo_state(repo: Path) -> tuple[str, str, str]:
    return (
        _git_out(repo, "rev-parse", "HEAD"),
        _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        _git_out(repo, "status", "--porcelain"),
    )


@pytest.mark.parametrize(
    "config_lines",
    [
        pytest.param(
            MAINTAINER_MODE_EXPORTS_AS_VERB_WRITES,
            id="both-spellings-as-the-verb-writes",
        ),
        pytest.param(["export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1"], id="minervit-only"),
        pytest.param(
            [
                "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=",
                "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1",
            ],
            id="blank-tautline-falls-through-to-minervit",
        ),
    ],
)
def test_launcher_auto_rescue_stands_down_when_file_armed(run_cli, tmp_path, config_lines):
    """File-armed, the generated launcher's auto-rescue returns before ANY git mutation.

    The warn-policy diverged/dirty fixture is the exact shape the stock shell rescue advances
    (test_launcher_shell_rescue_still_rescues_under_legacy_warn_policy is the without-the-key
    regression lock on that stock behavior). The guard's fallback order mirrors the Python file
    read: TAUTLINE_ first, blank counts as unset.
    """
    launcher = _install_plain_launcher(run_cli, tmp_path)
    repo, first, _second = _init_launcher_methodology_repo(tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    launch_home = tmp_path / "launch-home"
    launch_home.mkdir()
    _write_launch_home_config(launch_home, config_lines)
    before = _rescue_repo_state(repo)

    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_launcher_rescue_env(tmp_path, repo, fake_bin),
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert "fake sync" in run.stdout, "the standdown is a skip, never a failed launch"
    assert _git_out(repo, "rev-parse", "HEAD") == first
    assert _rescue_repo_state(repo) == before, (
        "the armed shell guard must leave HEAD, branch, and the dirty tree untouched"
    )
    assert "launcher_auto_rescue -" not in run.stdout + run.stderr
    assert (
        _git_out(repo, "branch", "--format=%(refname:short)", "--list", "minervit-local-rescue/*")
        == ""
    ), "no rescue branch may be created while the mode is file-armed"


@pytest.mark.parametrize(
    "name", ["TAUTLINE_METHODOLOGY_MAINTAINER_MODE", "MINERVIT_METHODOLOGY_MAINTAINER_MODE"]
)
def test_live_env_cannot_arm_the_shell_guard(run_cli, tmp_path, name):
    """No file key: a live-environment key must be INVISIBLE to the shell guard.

    File-only arming reaches the shell too -- the guard reads a value parsed from the config
    file, never the ambient environment, so the warn-policy rescue behaves exactly as stock.
    """
    launcher = _install_plain_launcher(run_cli, tmp_path)
    repo, _first, second = _init_launcher_methodology_repo(tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)

    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_launcher_rescue_env(tmp_path, repo, fake_bin, **{name: "1"}),
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert _git_out(repo, "rev-parse", "HEAD") == second, (
        "a live-env key must not arm the shell guard: the stock warn rescue must still advance"
    )
    assert "launcher_auto_rescue - preserved local methodology checkout" in run.stdout


def test_live_env_cannot_disarm_the_shell_guard(run_cli, tmp_path):
    """File key present: a live `=0` must NOT disarm the shell guard.

    Disarming is `maintainer-mode off`'s job, not the environment's -- the same
    authoritative-state property the Python side guarantees (MM-R4-P1-1).
    """
    launcher = _install_plain_launcher(run_cli, tmp_path)
    repo, first, _second = _init_launcher_methodology_repo(tmp_path)
    fake_bin = tmp_path / "fake-launcher-bin"
    _write_fake_launcher_bin(fake_bin)
    launch_home = tmp_path / "launch-home"
    launch_home.mkdir()
    _write_launch_home_config(launch_home, MAINTAINER_MODE_EXPORTS_AS_VERB_WRITES)
    before = _rescue_repo_state(repo)

    run = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_launcher_rescue_env(
            tmp_path,
            repo,
            fake_bin,
            TAUTLINE_METHODOLOGY_MAINTAINER_MODE="0",
            MINERVIT_METHODOLOGY_MAINTAINER_MODE="0",
        ),
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert _git_out(repo, "rev-parse", "HEAD") == first
    assert _rescue_repo_state(repo) == before, (
        "a live =0 must not disarm the file-armed shell guard"
    )
    assert "launcher_auto_rescue -" not in run.stdout + run.stderr


def test_generated_launcher_still_parses(run_cli, tmp_path):
    """`sh -n` on the regenerated launcher, plus the guard's load-bearing text.

    The parse lines carry the TAUTLINE_METHODOLOGY_MAINTAINER_MODE token on purpose: T4's
    content-keyed detection recognizes regenerated launchers by it, with NO
    LAUNCHER_TEMPLATE_VERSION bump (the sibling 0.9.18 plan escalates pre-guard launchers).
    """
    launcher = _install_plain_launcher(run_cli, tmp_path)
    text = launcher.read_text(encoding="utf-8")
    for marker in (
        'MAINTAINER_MODE_CONFIG="$HOME/.config/tautline/tautline.env"',
        '[ -f "$MAINTAINER_MODE_CONFIG" ] || '
        'MAINTAINER_MODE_CONFIG="$HOME/.config/minervit/methodology.env"',
        "LAUNCHER_MAINTAINER_MODE="
        "\"$(sed -n 's/^export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=//p' "
        '"$MAINTAINER_MODE_CONFIG" 2>/dev/null | tail -n 1)"',
        '[ -n "$LAUNCHER_MAINTAINER_MODE" ] || LAUNCHER_MAINTAINER_MODE='
        "\"$(sed -n 's/^export MINERVIT_METHODOLOGY_MAINTAINER_MODE=//p' "
        '"$MAINTAINER_MODE_CONFIG" 2>/dev/null | tail -n 1)"',
        '  [ "$LAUNCHER_MAINTAINER_MODE" != "1" ] || return 0',
    ):
        assert marker in text, marker
    assert LAUNCHER_TEMPLATE_MARKER in text, "the guard ships without a template-version bump"
    syntax = subprocess.run(["sh", "-n", str(launcher)], text=True, capture_output=True, timeout=60)
    assert syntax.returncode == 0, syntax.stderr


@pytest.mark.parametrize("policy", ["warn", "unverified"])
def test_skip_permissions_interlock_unchanged_by_maintainer_mode(run_cli, tmp_path, policy):
    """Regression lock: the mode key buys NO carve-out from the skip-permissions interlock.

    The guard consults effective_methodology_update_policy only -- an unverifiable upstream
    refuses --dangerously-skip-permissions whether or not the maintainer-mode key is in the
    hermetic config env file.
    """
    install = run_cli("install-cli", "--update-policy", policy)
    assert install.returncode == 0, install.stderr
    config = tmp_path / "home" / ".config" / "tautline" / "tautline.env"
    with config.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(MAINTAINER_MODE_EXPORTS_AS_VERB_WRITES) + "\n")

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
    assert policy in res.stderr
    assert not (launcher_bin / "minervit-claude-test").exists()
