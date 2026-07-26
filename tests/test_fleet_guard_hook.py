"""fleet-guard-hook: block/advise/observe on foreign-leased paths; fail-open everywhere."""

import json
import os
import shlex
import subprocess
from pathlib import Path

from test_fleet_lease_cli import _cleanup_wt as _cleanup
from test_fleet_lease_cli import _fleet_repo, _worktree


def _payload(wt: Path, file_path: str, tool: str = "Edit") -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return json.dumps({"tool_name": tool, "cwd": str(wt), "tool_input": {key: file_path}})


def test_foreign_edit_blocked_with_escapes(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        res = run_cli("fleet-guard-hook", stdin=_payload(wt, str(wt / "src" / "a.py")))
        assert res.returncode == 0
        assert '"decision": "block"' in res.stdout
        assert "fleet-lease takeover" in res.stdout
        assert "release" in res.stdout
        # The guard blocks ONLY on a live foreign lease, so every escape it prints
        # lands on the operator-owned path: both must carry --operator-note, or
        # they fail on first run and are not "runnable escapes" at all.
        assert res.stdout.count("--operator-note") == 2
    finally:
        _cleanup(repo, wt)


def test_all_four_structured_edit_tools_are_guarded(run_cli, tmp_path):
    # The promised surface is Edit|Write|MultiEdit|NotebookEdit. A regression that
    # dropped any one of them would otherwise pass every other test in this file.
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            target = "nb.ipynb" if tool == "NotebookEdit" else "a.py"
            res = run_cli(
                "fleet-guard-hook",
                stdin=_payload(wt, str(wt / "src" / target), tool=tool),
            )
            assert res.returncode == 0
            assert '"decision": "block"' in res.stdout, f"{tool} was not guarded"
    finally:
        _cleanup(repo, wt)


def test_escape_commands_survive_paths_with_spaces(run_cli, tmp_path):
    # Raw interpolation of a repo path containing a space word-splits into a
    # different command; the escapes must be shell-safe as printed.
    spaced = tmp_path / "dir with space"
    spaced.mkdir()
    repo = _fleet_repo(spaced)
    wt = _worktree(repo, spaced, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        res = run_cli("fleet-guard-hook", stdin=_payload(wt, str(wt / "src" / "a.py")))
        assert '"decision": "block"' in res.stdout
        # --target is the EDITING lane (wt), not the holder (repo). takeover
        # transfers the lease TO the --target worktree, so targeting the holder
        # would re-grant the holder its own lease and leave this lane blocked.
        assert f"--target {shlex.quote(str(wt))}" in res.stdout
        assert "--target /" not in res.stdout  # i.e. never emitted unquoted
    finally:
        _cleanup(repo, wt)


def test_own_lease_and_unleased_paths_allow_silently(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
    own = run_cli("fleet-guard-hook", stdin=_payload(repo, str(repo / "src" / "a.py")))
    assert own.returncode == 0 and own.stdout.strip() == ""
    free = run_cli("fleet-guard-hook", stdin=_payload(repo, str(repo / "docs" / "x.md")))
    assert free.returncode == 0 and free.stdout.strip() == ""


def test_outside_repo_and_non_edit_tools_allow(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "**")
    outside = run_cli(
        "fleet-guard-hook", stdin=_payload(repo, str(tmp_path / "elsewhere.txt"))
    )
    assert outside.returncode == 0 and outside.stdout.strip() == ""
    # Bash passes through BY DESIGN in v1. This asserts a KNOWN GAP, not a
    # satisfied guarantee: a lane can still reach a leased file with `sed -i` or
    # a redirect. Deciding which files an arbitrary shell string writes is not
    # reliably decidable, and a partial matcher would trade an honest gap for
    # false confidence. Never cite this test as evidence that all writes are
    # guarded; shell coverage is a v2 question.
    bash = run_cli(
        "fleet-guard-hook",
        stdin=json.dumps({
            "tool_name": "Bash", "cwd": str(repo),
            "tool_input": {"command": "sed -i '' s/a/b/ src/a.py"},
        }),
    )
    assert bash.returncode == 0 and bash.stdout.strip() == ""


def test_advise_mode_injects_context_not_block(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path, enforcement="advise")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        res = run_cli("fleet-guard-hook", stdin=_payload(wt, str(wt / "src" / "a.py")))
        assert '"decision": "block"' not in res.stdout
        assert "additionalContext" in res.stdout
    finally:
        _cleanup(repo, wt)


def test_observe_mode_logs_would_block(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path, enforcement="observe")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        res = run_cli("fleet-guard-hook", stdin=_payload(wt, str(wt / "src" / "a.py")))
        assert res.returncode == 0
        assert '"decision": "block"' not in res.stdout
        log = (repo / ".git" / "tautline-fleet" / "fleet.log").read_text(encoding="utf-8")
        assert "edit_would_block" in log
    finally:
        _cleanup(repo, wt)


def test_block_and_advise_both_land_in_fleet_log(run_cli, tmp_path):
    # fleet.log is the spec's evidence surface: enforcement decisions must appear
    # there in EVERY mode, not only observe.
    for mode, event in (("block", "edit_blocked"), ("advise", "edit_advised")):
        base = tmp_path / mode
        base.mkdir()
        repo = _fleet_repo(base, enforcement=mode)
        wt = _worktree(repo, base, "lane-b")
        try:
            run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
            run_cli("fleet-guard-hook", stdin=_payload(wt, str(wt / "src" / "a.py")))
            log = (repo / ".git" / "tautline-fleet" / "fleet.log").read_text(
                encoding="utf-8"
            )
            assert event in log, f"{mode} mode did not record {event}"
        finally:
            _cleanup(repo, wt)


def test_guard_blocks_at_every_point_in_a_takeover_chain(run_cli, tmp_path):
    """AT-REST invariant across takeover churn: after each completed takeover exactly
    one lease exists and covers the path, so the non-holding lane is always denied.

    Scope note, so this is not over-read: each takeover subprocess is awaited before
    the guard runs, so this does NOT exercise a live interleaving and cannot by itself
    prove the "no observable hole" property. The ordering that provides that property
    is proven deterministically by
    test_takeover_publishes_replacement_before_deleting_original in the lease suite."""
    import sys as _sys

    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    cli_path = str(Path(__file__).resolve().parents[1] / "bin" / "tautline")
    home = tmp_path / "race-home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    leases_dir = repo / ".git" / "tautline-fleet" / "leases"
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")

        def _takeover(into, note):
            lease_id = json.loads(
                next(leases_dir.glob("*.json")).read_text(encoding="utf-8")
            )["lease_id"]
            return subprocess.run(
                [_sys.executable, cli_path, "fleet-lease", "takeover",
                 "--target", str(into), "--lease", lease_id, "--note", note,
                 "--operator-note", "race test"],
                env=env, text=True, capture_output=True,
            )

        for i in range(6):
            churn = _takeover(wt if i % 2 == 0 else repo, f"churn {i}")
            assert churn.returncode == 0, churn.stderr
            # After every takeover the holder is the OTHER lane, so an edit from
            # the lane that does NOT hold it must always be denied.
            editor = repo if i % 2 == 0 else wt
            res = run_cli(
                "fleet-guard-hook", stdin=_payload(editor, str(editor / "src" / "a.py"))
            )
            assert res.returncode == 0
            assert '"decision": "block"' in res.stdout, (
                f"iteration {i}: guard allowed an edit a live foreign lease covered "
                f"-- a write-side hole was observable. stdout={res.stdout!r}"
            )
            # Exactly one lease at rest: takeover must leave neither both nor none.
            assert len(list(leases_dir.glob("*.json"))) == 1
    finally:
        _cleanup(repo, wt)


def test_corrupt_lease_never_blocks(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    leases = repo / ".git" / "tautline-fleet" / "leases"
    leases.mkdir(parents=True)
    (leases / "junk.json").write_text("{not json", encoding="utf-8")
    res = run_cli("fleet-guard-hook", stdin=_payload(repo, str(repo / "src" / "a.py")))
    assert res.returncode == 0
    assert '"decision": "block"' not in res.stdout


def test_garbage_stdin_allows(run_cli, tmp_path):
    res = run_cli("fleet-guard-hook", stdin="this is not json")
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_cross_repo_absolute_path_edit_still_guarded(run_cli, tmp_path):
    # cwd outside any Tautline repo, but the absolute edit path lands inside a
    # leased repo: the guard must still fire (adapter root resolved from the
    # edit path first; an editor with no lease here is foreign to all).
    repo = _fleet_repo(tmp_path)
    other = tmp_path / "unrelated"
    other.mkdir()
    run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
    payload = json.dumps({
        "tool_name": "Write", "cwd": str(other),
        "tool_input": {"file_path": str(repo / "src" / "a.py")},
    })
    res = run_cli("fleet-guard-hook", stdin=payload)
    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    # The escapes must be runnable from THIS cwd, which is outside the repo.
    assert f"--target {shlex.quote(str(repo))}" in res.stdout


def test_adapter_backed_cwd_editing_other_repo_still_guarded(run_cli, tmp_path):
    # cwd is itself an adapter-backed repo (A), but the absolute edit path lands
    # in leased repo B: the guard must consult B's lease store, not A's.
    repo_a = _fleet_repo(tmp_path)
    b_parent = tmp_path / "b"
    b_parent.mkdir()
    repo_b = _fleet_repo(b_parent)
    run_cli("fleet-lease", "claim", "--target", str(repo_b), "--globs", "src/**")
    payload = json.dumps({
        "tool_name": "Write", "cwd": str(repo_a),
        "tool_input": {"file_path": str(repo_b / "src" / "a.py")},
    })
    res = run_cli("fleet-guard-hook", stdin=payload)
    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout
    # cwd is adapter-backed repo A; the escapes must target leased repo B.
    assert f"--target {shlex.quote(str(repo_b))}" in res.stdout


def test_installed_fleet_guard_hook_matcher_covers_notebooks(cli, tmp_path):
    # A settings file written by an OLDER build would carry Edit|Write|MultiEdit,
    # leaving NotebookEdit silently unguarded while a command-string-only check
    # still reported "installed". The state check is matcher-aware, and the
    # writer repairs a stale matcher rather than treating it as already present.
    settings = tmp_path / "settings.json"
    cli.write_claude_fleet_guard_hook(settings, "tautline fleet-guard-hook")
    blocks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    matchers = [
        block["matcher"] for block in blocks
        if any("fleet-guard-hook" in hook.get("command", "")
               for hook in block.get("hooks", []))
    ]
    assert matchers == ["Edit|Write|MultiEdit|NotebookEdit"]

    stale = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit",
                    "hooks": [
                        {"type": "command", "command": "tautline fleet-guard-hook"}
                    ],
                }
            ]
        }
    }
    assert cli.settings_fleet_guard_hook_installed(stale) is False
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps(stale), encoding="utf-8")
    cli.write_claude_fleet_guard_hook(stale_path, "tautline fleet-guard-hook")
    repaired = json.loads(stale_path.read_text(encoding="utf-8"))
    assert cli.settings_fleet_guard_hook_installed(repaired) is True
    fleet_blocks = [
        block for block in repaired["hooks"]["PreToolUse"]
        if any("fleet-guard-hook" in hook.get("command", "")
               for hook in block.get("hooks", []))
    ]
    assert len(fleet_blocks) == 1, "repair must replace, not append a second entry"


def test_escape_targets_the_blocked_lane_not_the_holder(run_cli, tmp_path):
    """`takeover` grants the lease TO --target, so --target must name the BLOCKED lane.

    When a lane writes an ABSOLUTE path into another worktree of the same repo, the edit
    path resolves to the HOLDER. Targeting it would re-grant the holder its own lease --
    a no-op that leaves the blocked lane blocked forever: an escape that cannot escape.
    """
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        # cwd is lane-b (the blocked lane); the edit path is inside repo (the holder).
        payload = json.dumps({
            "tool_name": "Edit", "cwd": str(wt),
            "tool_input": {"file_path": str(repo / "src" / "a.py")},
        })
        res = run_cli("fleet-guard-hook", stdin=payload)
        assert '"decision": "block"' in res.stdout
        assert f"--target {shlex.quote(str(wt))}" in res.stdout, (
            "escape must target the blocked lane (lane-b), not the holder"
        )
        assert f"--target {shlex.quote(str(repo))}" not in res.stdout
    finally:
        _cleanup(repo, wt)


def test_symlinked_path_cannot_bypass_the_lease(run_cli, tmp_path):
    """A lease is stored against the spelling its holder CLAIMED. With
    `link -> actual` inside the repo, matching only the RESOLVED path means a
    lease on `link/**` never sees an edit to `link/a.py` -- a straight bypass.
    Both spellings are checked, so the claimed one still arbitrates."""
    repo = _fleet_repo(tmp_path)
    (repo / "actual").mkdir()
    (repo / "actual" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "link").symlink_to(repo / "actual")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        claimed = run_cli(
            "fleet-lease", "claim", "--target", str(repo), "--globs", "link/**"
        )
        assert claimed.returncode == 0, claimed.stderr
        # Foreign lane edits through the SYMLINK spelling the lease named.
        res = run_cli(
            "fleet-guard-hook", stdin=_payload(wt, str(repo / "link" / "a.py"))
        )
        assert res.returncode == 0
        assert '"decision": "block"' in res.stdout, (
            "symlink spelling bypassed the lease that claimed it"
        )
    finally:
        _cleanup(repo, wt)


def test_lease_on_real_path_still_blocks_the_resolved_spelling(run_cli, tmp_path):
    """The converse direction must keep working: a lease claimed on the REAL
    path still blocks, which is what the resolve() half provides."""
    repo = _fleet_repo(tmp_path)
    (repo / "actual").mkdir()
    (repo / "actual" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "link").symlink_to(repo / "actual")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "actual/**")
        res = run_cli(
            "fleet-guard-hook", stdin=_payload(wt, str(repo / "link" / "a.py"))
        )
        assert res.returncode == 0
        assert '"decision": "block"' in res.stdout
    finally:
        _cleanup(repo, wt)


def test_symlink_escaping_the_repo_still_attributes_to_the_leased_repo(run_cli, tmp_path):
    """Attribution and matching must agree. When the edit path is lexically inside
    the leased repo via a symlink whose TARGET lies outside it, resolving first
    hides the repo that owns the lease and the cwd fallback consults the wrong one
    -- so fixing only the matching layer just moves the bypass to attribution."""
    repo = _fleet_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "link").symlink_to(outside)          # symlink ESCAPES the repo
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()                             # cwd is not any repo
    run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "link/**")
    payload = json.dumps({
        "tool_name": "Edit", "cwd": str(elsewhere),
        "tool_input": {"file_path": str(repo / "link" / "a.py")},
    })
    res = run_cli("fleet-guard-hook", stdin=payload)
    assert res.returncode == 0
    assert '"decision": "block"' in res.stdout, (
        "escaping symlink bypassed attribution to the repo that holds the lease"
    )
