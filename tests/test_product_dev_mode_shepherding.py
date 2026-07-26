"""Product-dev mode shepherding standdown (T1) + policy/status authorization (T2).

When the per-checkout product-dev mode is active, THREE shepherding agent hooks stand down for
the session:

- the latest-code baseline guard (whole handler -- intentionally dropping its stale-baseline
  STATE-CHANGE block along with the nag; that block is workflow discipline, not a merge gate),
- the active-goal Stop-guard (whole handler),
- the fake-monitor branch of the background-command guard (ONLY that branch -- the board-structure
  and item-content SAFETY branches stay on).

Every code-safety MERGE gate (`guard_check`, `cut_release`, the version-contract predicate) and
every plan-review gate (`plan_finalization_hook`, `plan_review_pending_hook`) stays ON. The mode
is NEVER read by a code-safety path -- the absolute safety invariant. Each standdown emits a
non-blocking `hook_additional_context` advisory (with the mode's `expiresAt`) so a later session
in the same checkout is told the mode is on rather than silently stood down, and
`methodology-status` reports a `product_dev_mode:` line.

Mode OFF (default or any fail-safe read error) => every hook behaves byte-identically to today,
EXCEPT the newly allowlisted `product-dev-mode` command (so enabling the mode is never itself
blocked by the stale-baseline guard it disables -- the chicken-and-egg guard).
"""
import ast
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Post the package-split flip (roadmap #11): the engine (these AST-scanned bodies) lives in cli.py;
# bin/tautline is a thin shim. Only source-scans reference CLI_PATH in this module.
CLI_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
GENERATED_ADAPTER = REPO_ROOT / "tests" / "fixtures" / "generated-adapter-example-saas.json"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
STATE_REL = ".ai-work/PRODUCT_DEV_MODE.json"
SCHEMA = "tautline-product-dev-mode/v1"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _arm_mode(root: Path, *, minutes: int = 200) -> str:
    """Arm product-dev mode under root/.ai-work (the sole state file). Returns the expiresAt."""
    now = datetime.now(timezone.utc)
    expires = _iso(now + timedelta(minutes=minutes))
    payload = {"schema": SCHEMA, "on": True, "startedAt": _iso(now), "expiresAt": expires}
    path = root / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return expires


# --- adapter roots -------------------------------------------------------------------------


def _generated_adapter_root(tmp_path: Path) -> Path:
    """A root carrying a fully-generated adapter (latestCode enabled) -- drives latest-code."""
    root = tmp_path / "lane"
    root.mkdir(parents=True)
    (root / ".minervit-ai-delivery.json").write_text(
        GENERATED_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return root


def _goal_lane(tmp_path: Path, cli) -> Path:
    """A generated-adapter root with an in-progress GOAL_RUN -- arms the Stop-guard."""
    root = _generated_adapter_root(tmp_path)
    goal_path = root / ".ai-work" / "GOAL_RUN.json"
    goal_path.parent.mkdir(parents=True, exist_ok=True)
    goal_path.write_text(
        json.dumps({"schema": cli.GOAL_RUN_SCHEMA, "goalId": "goal-1", "status": "in_progress"})
        + "\n",
        encoding="utf-8",
    )
    return root


def _bare_adapter_root(tmp_path: Path, adapter: dict | None = None) -> Path:
    """A minimal `.minervit-ai-delivery.json` -- enough for the background-command hook, which
    reads the adapter marker directly (never load_project)."""
    root = tmp_path / "board"
    root.mkdir()
    (root / ".minervit-ai-delivery.json").write_text(json.dumps(adapter or {}), encoding="utf-8")
    return root


# --- hook events ---------------------------------------------------------------------------


def _edit_event(root: Path) -> str:
    return json.dumps(
        {"tool_name": "Edit", "cwd": str(root), "tool_input": {"file_path": str(root / "x.py")}}
    )


def _bash_event(root: Path, command: str) -> str:
    return json.dumps({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": command}})


def _stop_event(root: Path, assistant: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "cwd": str(root),
            "minervit_active_goal": True,
            "last_user_message": "continue the goal",
            "last_assistant_message": assistant,
        }
    )


def _is_block(stdout: str) -> bool:
    return '"decision": "block"' in stdout


def _advisory_text(stdout: str) -> str:
    """Return the additionalContext of the (single) advisory in stdout, else ''."""
    stdout = stdout.strip()
    if not stdout:
        return ""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return ""
    return payload.get("hookSpecificOutput", {}).get("additionalContext", "")


FAKE_MONITOR_CMD = "while true; do sleep 5; tail -F build.log | grep -q done; done"
BOARD_STRUCTURE_CMD = "gh project field-create 5 --owner minervit --name 'Item Type'"
ITEM_CONTENT_CMD = "gh issue edit 5 --title 'changed'"


# --- latest-code + Stop-guard stand down when mode ON --------------------------------------


def test_shepherding_hooks_stand_down_when_mode_on(run_cli, cli, tmp_path):
    """Acceptance: latest-code and Stop-guard return 0 (no block) on inputs that block mode OFF."""
    lc_root = _generated_adapter_root(tmp_path / "lc")
    # Sanity: mode OFF blocks.
    off = run_cli("latest-code-hook", stdin=_edit_event(lc_root))
    assert _is_block(off.stdout), off.stdout
    # Mode ON stands down.
    _arm_mode(lc_root)
    on = run_cli("latest-code-hook", stdin=_edit_event(lc_root))
    assert on.returncode == 0
    assert not _is_block(on.stdout), on.stdout

    goal_root = _goal_lane(tmp_path / "goal", cli)
    off_goal = run_cli("response-guard-hook", stdin=_stop_event(goal_root, "I am stopping here."))
    assert _is_block(off_goal.stdout), off_goal.stdout
    _arm_mode(goal_root)
    on_goal = run_cli("response-guard-hook", stdin=_stop_event(goal_root, "I am stopping here."))
    assert on_goal.returncode == 0
    assert not _is_block(on_goal.stdout), on_goal.stdout


def test_latest_code_statechange_block_dropped_in_mode(run_cli, tmp_path):
    """The whole-handler standdown intentionally drops the stale-baseline STATE-CHANGE block
    (Edit/Write/state-changing Bash) too -- an accepted, TTL-bounded shepherding exception."""
    root = _generated_adapter_root(tmp_path)
    push = _bash_event(root, "git push origin HEAD")
    assert _is_block(run_cli("latest-code-hook", stdin=push).stdout)
    _arm_mode(root)
    on = run_cli("latest-code-hook", stdin=push)
    assert on.returncode == 0
    assert not _is_block(on.stdout), on.stdout


# --- background guard: fake-monitor stands down, safety branches stay on --------------------


def test_background_guard_keeps_safety_branches(run_cli, tmp_path):
    """Mode ON: the fake-monitor branch stands down, but board-structure and item-content
    SAFETY blocks still fire."""
    root = _bare_adapter_root(tmp_path)
    _arm_mode(root)
    monitor = run_cli("background-command-hook", stdin=_bash_event(root, FAKE_MONITOR_CMD))
    assert monitor.returncode == 0
    assert not _is_block(monitor.stdout), monitor.stdout

    board = run_cli("background-command-hook", stdin=_bash_event(root, BOARD_STRUCTURE_CMD))
    assert _is_block(board.stdout), board.stdout

    item = run_cli("background-command-hook", stdin=_bash_event(root, ITEM_CONTENT_CMD))
    assert _is_block(item.stdout), item.stdout


def test_background_fake_monitor_blocks_when_mode_off(run_cli, tmp_path):
    """Mode-OFF parity: the fake-monitor branch still blocks."""
    root = _bare_adapter_root(tmp_path)
    res = run_cli("background-command-hook", stdin=_bash_event(root, FAKE_MONITOR_CMD))
    assert _is_block(res.stdout), res.stdout


# --- plan-review gates STILL block in mode -------------------------------------------------


def test_plan_finalization_still_gates_in_mode(run_cli, tmp_path):
    """plan_finalization_hook is NOT dropped: ExitPlanMode on an unfinalized plan still blocks
    even with the mode on."""
    root = _generated_adapter_root(tmp_path)
    _arm_mode(root)
    event = json.dumps(
        {
            "tool_name": "ExitPlanMode",
            "cwd": str(root),
            "tool_input": {"planFilePath": str(root / "scratch-plan.md")},
        }
    )
    res = run_cli("plan-finalization-hook", stdin=event)
    assert res.returncode == 0
    assert _is_block(res.stdout), res.stdout


def test_plan_review_pending_still_gates_in_mode():
    """plan_review_pending_hook is NOT dropped: its handler must never read the mode, so it keeps
    gating identically whether or not the mode is on. The block predicate needs a live pending
    plan-review window (heavy machinery), so the invariant is enforced by source-scan: neither
    plan-review gate references the mode reader (they can never stand down)."""
    source = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    plan_gate_names = {"plan_finalization_hook", "plan_review_pending_hook"}
    reader_symbols = {"product_dev_mode_active", "product_dev_mode_state"}
    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert plan_gate_names <= set(funcs), plan_gate_names - set(funcs)
    for name in plan_gate_names:
        read = {
            n.id
            for n in ast.walk(funcs[name])
            if isinstance(n, ast.Name) and n.id in reader_symbols
        }
        assert not read, (
            f"{name}() reads product-dev-mode {read}: plan-review gates must never stand down"
        )


# --- the enabling verb is allowlisted through the latest-code hook -------------------------


def test_mode_verb_allowlisted_pure(cli):
    """`tautline product-dev-mode on|off` passes the latest-code command allowlist, even though
    it is a state-changing verb, so the enabling command is never self-blocked."""
    assert cli.latest_code_command_allowed("tautline product-dev-mode on")
    assert cli.latest_code_command_allowed("tautline product-dev-mode off --target .")
    assert cli.latest_code_command_allowed("minervit-methodology product-dev-mode on")
    # Unrelated commands stay blocked (prefix-match semantics, same as every other allowlist entry).
    assert not cli.latest_code_command_allowed("tautline goal-start")
    assert not cli.latest_code_command_allowed("rm -rf .")


def test_mode_verb_allowed_through_stale_baseline(run_cli, tmp_path):
    """Even with a stale/missing baseline AND mode OFF (the chicken-and-egg case), the
    latest-code hook lets `tautline product-dev-mode on` through instead of blocking it."""
    root = _generated_adapter_root(tmp_path)
    # A random state-changing bash still blocks (baseline is missing).
    assert _is_block(
        run_cli("latest-code-hook", stdin=_bash_event(root, "git push origin HEAD")).stdout
    )
    # The enabling verb is NOT blocked.
    verb = run_cli(
        "latest-code-hook", stdin=_bash_event(root, "tautline product-dev-mode on --target .")
    )
    assert verb.returncode == 0
    assert not _is_block(verb.stdout), verb.stdout


# --- each standdown emits the advisory (with expiresAt) ------------------------------------


def test_standdown_emits_advisory(run_cli, cli, tmp_path):
    """Each of the three standdowns emits a non-blocking advisory naming the mode + expiresAt."""
    lc_root = _generated_adapter_root(tmp_path / "lc")
    expires = _arm_mode(lc_root)
    lc = run_cli("latest-code-hook", stdin=_edit_event(lc_root))
    text = _advisory_text(lc.stdout)
    assert "product-dev mode" in text.lower()
    assert expires in text

    goal_root = _goal_lane(tmp_path / "goal", cli)
    g_expires = _arm_mode(goal_root)
    g = run_cli("response-guard-hook", stdin=_stop_event(goal_root, "I am stopping here."))
    g_text = _advisory_text(g.stdout)
    assert "product-dev mode" in g_text.lower()
    assert g_expires in g_text

    bg_root = _bare_adapter_root(tmp_path)
    b_expires = _arm_mode(bg_root)
    b = run_cli("background-command-hook", stdin=_bash_event(bg_root, FAKE_MONITOR_CMD))
    b_text = _advisory_text(b.stdout)
    assert "product-dev mode" in b_text.lower()
    assert b_expires in b_text


# --- methodology-status reports the mode ---------------------------------------------------


def _status_lane(tmp_path: Path, run_cli) -> Path:
    """A minimal started lane for methodology-status (latestCode disabled so the status run is
    hermetic and offline)."""
    target = tmp_path / "target"
    target.mkdir()
    git = ["git", "-C", str(target)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, capture_output=True)
    subprocess.run(
        [*git, "config", "user.email", "t@example.invalid"], check=True, capture_output=True
    )
    subprocess.run([*git, "config", "user.name", "t"], check=True, capture_output=True)
    subprocess.run(
        [*git, "remote", "add", "origin", "git@github.com:example-org/example-saas.git"],
        check=True, capture_output=True,
    )
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["latestCode"] = {"enabled": False}
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    adapter = target / ".tautline" / "adapter.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    started = run_cli(
        "lane-start", "--project", str(adapter), "--target", str(target), "--skip-update"
    )
    assert started.returncode == 0, started.stdout + started.stderr
    return target


def test_methodology_status_reports_mode(run_cli, tmp_path):
    target = _status_lane(tmp_path, run_cli)
    off = run_cli("methodology-status", "--target", str(target), "--no-remote")
    assert "product_dev_mode: off" in off.stdout, off.stdout

    _arm_mode(target)
    on = run_cli("methodology-status", "--target", str(target), "--no-remote")
    assert "product_dev_mode: on" in on.stdout, on.stdout
    assert "remaining" in on.stdout


# --- the safety invariant: never read by a code-safety path --------------------------------


def test_mode_never_read_by_code_safety():
    """`product_dev_mode_active` and `product_dev_mode_state` must be ABSENT from the code-safety
    merge paths `guard_check` and `cut_release` (the version-contract predicate lives in the test
    suite, not bin/tautline). AST-scan the function bodies for either reader symbol."""
    source = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    code_safety_names = {"guard_check", "cut_release"}
    reader_symbols = {"product_dev_mode_active", "product_dev_mode_state"}
    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert code_safety_names <= set(funcs), code_safety_names - set(funcs)
    for name in code_safety_names:
        called = {
            n.id
            for n in ast.walk(funcs[name])
            if isinstance(n, ast.Name) and n.id in reader_symbols
        }
        assert not called, (
            f"{name}() reads product-dev-mode {called}: "
            "the mode must never be read by a code-safety path"
        )
