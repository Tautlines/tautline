"""Guided-onboarding classifier + renderer + sentinel-split contract (roadmap #14, PR 1).

These are byte-identity-critical tests: the unmanaged no-adapter output must stay byte-for-byte
identical to the pre-split constant, and every evidence state must carry the state-correct
recovery command behind the stable NO_ADAPTER_SENTINEL prefix. The classifier must stay
shell-free (the SessionStart hook calls it under total containment).
"""

import subprocess
from pathlib import Path

import pytest

# Frozen golden copy of the pre-split NO_ADAPTER_MESSAGE. Any drift in the split must fail here,
# not silently recompose to a different byte string. Stored as a fixture .txt (not a Python
# literal) so its intentionally-long prose lines do not enter the E501 ratchet, while remaining an
# independent byte-for-byte reference frozen at PR-1 time.
LEGACY_NO_ADAPTER_MESSAGE = (
    Path(__file__).resolve().parent / "fixtures" / "no_adapter_message_golden.txt"
).read_text(encoding="utf-8")

# The middle-third recovery block for the unmanaged state, exactly as shipped (3-space indent).
LEGACY_RECOVERY_BLOCK = "Recovery command:\n   tautline init --target .\n"

INTERVIEW_REL = ".ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _mk(tmp_path, name):
    d = (tmp_path / name).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_interview(root):
    p = root / INTERVIEW_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("interview", encoding="utf-8")
    return p


def _write_source_adapter(root, cli, legacy=False):
    rel = cli.LEGACY_REPO_LOCAL_ADAPTER_FILE if legacy else cli.REPO_LOCAL_ADAPTER_FILE
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    return p


def _write_marker(root, cli, legacy=False):
    rel = cli.LEGACY_LANE_ADAPTER_FILE if legacy else cli.LANE_ADAPTER_FILE
    p = root / rel
    p.write_text("{}", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# classifier: structured verdict per state
# ---------------------------------------------------------------------------
def test_unmanaged_structured_verdict(cli, tmp_path):
    d = _mk(tmp_path, "bare")
    info = cli.onboarding_state(d, d)
    assert info == {
        "state": "unmanaged",
        "target": d,
        "invocation_cwd": d,
        "root": None,
        "source_path": None,
        "interview_path": None,
    }


def test_managed_structured_verdict(cli, tmp_path):
    d = _mk(tmp_path, "managed")
    _write_marker(d, cli)
    info = cli.onboarding_state(d, d)
    assert info["state"] == "managed"
    assert info["root"] == d
    assert info["source_path"] is None and info["interview_path"] is None


def test_interview_pending_structured_verdict(cli, tmp_path):
    d = _mk(tmp_path, "ip")
    ipath = _write_interview(d)
    info = cli.onboarding_state(d, d)
    assert info["state"] == "interview-pending"
    assert info["root"] == d
    assert info["interview_path"] == ipath
    assert info["source_path"] is None


def test_source_unrendered_structured_verdict(cli, tmp_path):
    d = _mk(tmp_path, "su")
    spath = _write_source_adapter(d, cli)
    info = cli.onboarding_state(d, d)
    assert info["state"] == "source-unrendered"
    assert info["root"] == d
    assert info["source_path"] == spath
    assert info["interview_path"] is None


def test_precedence_source_beats_interview(cli, tmp_path):
    d = _mk(tmp_path, "both")
    _write_source_adapter(d, cli)
    _write_interview(d)
    info = cli.onboarding_state(d, d)
    assert info["state"] == "source-unrendered"


def test_precedence_marker_beats_everything(cli, tmp_path):
    d = _mk(tmp_path, "all")
    _write_marker(d, cli)
    _write_source_adapter(d, cli)
    _write_interview(d)
    assert cli.onboarding_state(d, d)["state"] == "managed"


def test_legacy_marker_repo_classifies_managed(cli, tmp_path):
    d = _mk(tmp_path, "legacy-marker")
    _write_marker(d, cli, legacy=True)
    assert cli.onboarding_state(d, d)["state"] == "managed"


def test_legacy_source_adapter_classifies_source_unrendered(cli, tmp_path):
    d = _mk(tmp_path, "legacy-src")
    _write_source_adapter(d, cli, legacy=True)
    assert cli.onboarding_state(d, d)["state"] == "source-unrendered"


# ---------------------------------------------------------------------------
# classifier: parent-walk / subdirectory starts classify like root
# ---------------------------------------------------------------------------
def test_subdirectory_classifies_like_root_interview(cli, tmp_path):
    root = _mk(tmp_path, "ip-root")
    _write_interview(root)
    sub = _mk(tmp_path / "ip-root", "a/b")
    info = cli.onboarding_state(sub, sub)
    assert info["state"] == "interview-pending"
    assert info["root"] == root


def test_subdirectory_classifies_like_root_source(cli, tmp_path):
    root = _mk(tmp_path, "su-root")
    _write_source_adapter(root, cli)
    sub = _mk(tmp_path / "su-root", "deep/dir")
    info = cli.onboarding_state(sub, sub)
    assert info["state"] == "source-unrendered"
    assert info["root"] == root


# ---------------------------------------------------------------------------
# classifier stays shell-free (hook total-containment invariant)
# ---------------------------------------------------------------------------
def test_classifier_never_shells_out(cli, tmp_path, monkeypatch):
    d = _mk(tmp_path, "no-shell")

    def boom(*args, **kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError("onboarding_state must not shell out")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(cli.subprocess, "run", boom)
    assert cli.onboarding_state(d, d)["state"] == "unmanaged"


# ---------------------------------------------------------------------------
# resolve_unmanaged_root (separate helper; the ONLY shelling surface)
# ---------------------------------------------------------------------------
def test_resolve_unmanaged_root_non_git_falls_back_to_target(cli, tmp_path):
    d = _mk(tmp_path, "non-git")
    assert cli.resolve_unmanaged_root(d) == d


def test_resolve_unmanaged_root_git_returns_toplevel(cli, tmp_path):
    repo = _mk(tmp_path, "git-repo")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    sub = _mk(tmp_path / "git-repo", "x/y")
    assert cli.resolve_unmanaged_root(sub).resolve() == repo.resolve()


# ---------------------------------------------------------------------------
# renderer: exact offer lines per state
# ---------------------------------------------------------------------------
def test_offer_lines_unmanaged_at_cwd(cli, tmp_path):
    d = _mk(tmp_path, "bare")
    info = dict(cli.onboarding_state(d, d), root=d)  # unmanaged root populated to cwd
    lines = cli.onboarding_offer_lines(info)
    assert lines == [
        "onboarding_offer: this repository has no Tautline adapter. Guided onboarding writes "
        "one from a short interview: tautline init --target .",
        "onboarding_offer: agents put the adopt/skip decision to the human operator through "
        "AskUserQuestion (or the host equivalent) before running init; do not run init "
        "unprompted and do not re-ask on refusal.",
    ]


def test_offer_lines_interview_pending(cli, tmp_path):
    d = _mk(tmp_path, "ip")
    _write_interview(d)
    info = cli.onboarding_state(d, d)
    lines = cli.onboarding_offer_lines(info)
    assert lines == [
        "onboarding_offer: an onboarding interview is already in progress "
        f"({INTERVIEW_REL}). Finish it: answer the remaining questions, then run: "
        "tautline init --target . --continue",
    ]


def test_offer_lines_source_unrendered(cli, tmp_path):
    d = _mk(tmp_path, "su")
    _write_source_adapter(d, cli)
    info = cli.onboarding_state(d, d)
    lines = cli.onboarding_offer_lines(info)
    assert lines == [
        "onboarding_offer: a source adapter exists but this repo is not rendered. Next: "
        f"tautline render-adapters --project {cli.REPO_LOCAL_ADAPTER_FILE} --target . --write, "
        "then: tautline lane-start --target .",
    ]


def test_offer_lines_managed_empty(cli, tmp_path):
    d = _mk(tmp_path, "managed")
    _write_marker(d, cli)
    assert cli.onboarding_offer_lines(cli.onboarding_state(d, d)) == []


def test_offer_lines_unmanaged_git_subdir_targets_toplevel(cli, tmp_path):
    repo = _mk(tmp_path, "git-repo")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    sub = _mk(tmp_path / "git-repo", "a/b")
    info = cli.onboarding_info_for_offer(sub, sub)
    # root is the git toplevel (an ANCESTOR of cwd) so it renders ABSOLUTE and targets the repo.
    assert info["root"].resolve() == repo.resolve()
    first = cli.onboarding_offer_lines(info)[0]
    assert f"tautline init --target {repo}" in first


def test_offer_lines_unmanaged_non_git_falls_back_to_target(cli, tmp_path):
    d = _mk(tmp_path, "non-git")
    info = cli.onboarding_info_for_offer(d, d)
    assert info["root"] == d
    assert "tautline init --target ." in cli.onboarding_offer_lines(info)[0]


# ---------------------------------------------------------------------------
# renderer: cwd-relative rendering rule (absolute for unrelated cwd)
# ---------------------------------------------------------------------------
def test_render_absolute_for_unrelated_target(cli, tmp_path):
    target = _mk(tmp_path, "proj")
    _write_source_adapter(target, cli)
    unrelated = _mk(tmp_path, "elsewhere")
    info = cli.onboarding_state(target, unrelated)
    line = cli.onboarding_offer_lines(info)[0]
    # target is NOT under the unrelated cwd -> absolute paths, never wrong-relative.
    assert f"--target {target}" in line
    assert str(target / cli.REPO_LOCAL_ADAPTER_FILE) in line


def test_render_relative_when_under_cwd(cli, tmp_path):
    root = _mk(tmp_path, "r")
    _write_source_adapter(root, cli)
    # invocation_cwd is the parent; root renders as its basename (relative, resolvable).
    info = cli.onboarding_state(root, tmp_path)
    line = cli.onboarding_offer_lines(info)[0]
    assert "--target r --write" in line


# ---------------------------------------------------------------------------
# renderer purity: same dict in -> same lines out, no process reads
# ---------------------------------------------------------------------------
def test_renderer_is_pure(cli, tmp_path):
    info = {
        "state": "source-unrendered",
        "target": Path("/x/proj"),
        "invocation_cwd": Path("/x/proj"),
        "root": Path("/x/proj"),
        "source_path": Path("/x/proj/.tautline/adapter.json"),
        "interview_path": None,
    }
    a = cli.onboarding_offer_lines(info)
    b = cli.onboarding_offer_lines(dict(info))
    assert a == b
    assert a == [
        "onboarding_offer: a source adapter exists but this repo is not rendered. Next: "
        "tautline render-adapters --project .tautline/adapter.json --target . --write, "
        "then: tautline lane-start --target .",
    ]


# ---------------------------------------------------------------------------
# every emitted line passes the guard scanner
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("builder", ["unmanaged", "interview-pending", "source-unrendered"])
def test_offer_lines_pass_guard_scanner(cli, tmp_path, builder):
    d = _mk(tmp_path, builder)
    if builder == "interview-pending":
        _write_interview(d)
    elif builder == "source-unrendered":
        _write_source_adapter(d, cli)
    info = cli.onboarding_info_for_offer(d, d)
    lines = cli.onboarding_offer_lines(info)
    assert lines
    for line in lines:
        assert not cli.response_has_forbidden_opt_in(line), line


# ---------------------------------------------------------------------------
# sentinel split: byte-identity + boundaries
# ---------------------------------------------------------------------------
def test_composed_unmanaged_message_byte_identical(cli, tmp_path):
    d = _mk(tmp_path, "bare")
    info = cli.onboarding_state(d, d)
    assert cli.no_adapter_message(info) == LEGACY_NO_ADAPTER_MESSAGE
    assert cli.NO_ADAPTER_MESSAGE == LEGACY_NO_ADAPTER_MESSAGE


def test_extracted_recovery_block_matches_shipped(cli):
    # sentinel + shipped unmanaged recovery block + footer == the whole legacy constant.
    assert (
        cli.NO_ADAPTER_SENTINEL + LEGACY_RECOVERY_BLOCK + cli.NO_ADAPTER_FOOTER
        == LEGACY_NO_ADAPTER_MESSAGE
    )
    assert cli.NO_ADAPTER_UNMANAGED_RECOVERY == LEGACY_RECOVERY_BLOCK
    assert cli.NO_ADAPTER_SENTINEL == LEGACY_NO_ADAPTER_MESSAGE.split(LEGACY_RECOVERY_BLOCK)[0]
    assert cli.NO_ADAPTER_FOOTER == LEGACY_NO_ADAPTER_MESSAGE.split(LEGACY_RECOVERY_BLOCK)[1]


@pytest.mark.parametrize("builder", ["unmanaged", "interview-pending", "source-unrendered"])
def test_no_adapter_message_sentinel_and_footer(cli, tmp_path, builder):
    d = _mk(tmp_path, builder)
    if builder == "interview-pending":
        _write_interview(d)
    elif builder == "source-unrendered":
        _write_source_adapter(d, cli)
    msg = cli.no_adapter_message(cli.onboarding_state(d, d))
    assert msg.startswith(cli.NO_ADAPTER_SENTINEL)
    assert msg.endswith(cli.NO_ADAPTER_FOOTER)
    assert "Recovery command:" in msg


def test_managed_never_composes_no_adapter_message(cli, tmp_path):
    # managed is not a no-adapter state; its recovery command list is empty.
    d = _mk(tmp_path, "managed")
    _write_marker(d, cli)
    info = cli.onboarding_state(d, d)
    assert cli._no_adapter_recovery_commands(info) == []


def test_evidence_states_carry_correct_command_not_stale(cli, tmp_path):
    ip = _mk(tmp_path, "ip")
    _write_interview(ip)
    ip_msg = cli.no_adapter_message(cli.onboarding_state(ip, ip))
    assert "tautline init --target . --continue" in ip_msg
    # the stale unmanaged recovery block must NOT appear in an evidence-state message.
    assert LEGACY_RECOVERY_BLOCK not in ip_msg
    # recovery uses the Recovery command: FORMAT, not onboarding_offer: copy.
    assert "onboarding_offer:" not in ip_msg

    su = _mk(tmp_path, "su")
    _write_source_adapter(su, cli)
    su_msg = cli.no_adapter_message(cli.onboarding_state(su, su))
    assert "tautline render-adapters" in su_msg
    assert "tautline lane-start --target ." in su_msg
    assert LEGACY_RECOVERY_BLOCK not in su_msg
    assert "onboarding_offer:" not in su_msg


def test_no_adapter_message_for_uses_process_cwd(cli, tmp_path, monkeypatch):
    d = _mk(tmp_path, "ip")
    _write_interview(d)
    monkeypatch.chdir(d)
    msg = cli.no_adapter_message_for(d)
    assert msg.startswith(cli.NO_ADAPTER_SENTINEL)
    assert "tautline init --target . --continue" in msg


# ---------------------------------------------------------------------------
# PR-1 deferred fix: the unmanaged recovery command renders the REQUESTED target relative to the
# invocation cwd (not a hard-coded `.`), so a gate verb run with --target <repo> from an unrelated
# cwd recovers <repo>, never the cwd. target==cwd stays `.` (byte-identity is preserved above).
# ---------------------------------------------------------------------------
def test_recovery_unmanaged_target_not_under_cwd_is_absolute(cli, tmp_path):
    target = _mk(tmp_path, "repo")
    unrelated = _mk(tmp_path, "elsewhere")
    info = cli.onboarding_state(target, unrelated)  # target NOT under cwd -> absolute
    assert info["state"] == "unmanaged"
    assert cli._no_adapter_recovery_commands(info) == [f"tautline init --target {target}"]
    msg = cli.no_adapter_message(info)
    assert f"tautline init --target {target}" in msg
    assert "tautline init --target .\n" not in msg  # never the stale cwd-relative dot


def test_recovery_unmanaged_target_under_cwd_is_relative(cli, tmp_path):
    target = _mk(tmp_path, "repo")
    info = cli.onboarding_state(target, tmp_path)  # cwd is the parent -> relative basename
    assert info["state"] == "unmanaged"
    assert cli._no_adapter_recovery_commands(info) == ["tautline init --target repo"]


def test_recovery_unmanaged_target_equals_cwd_is_dot(cli, tmp_path):
    d = _mk(tmp_path, "repo")
    info = cli.onboarding_state(d, d)  # target == cwd -> `.` (byte-identity path)
    assert cli._no_adapter_recovery_commands(info) == ["tautline init --target ."]


def test_lane_start_unmanaged_recovery_targets_requested_repo(cli, tmp_path):
    # End-to-end: `lane-start --target <unmanaged repo>` from a DIFFERENT cwd recovers that repo,
    # not the cwd. The gate still fails closed (nonzero); only its recovery text is correct.
    import os
    import subprocess
    import sys

    repo = _mk(tmp_path, "repo")
    cwd = _mk(tmp_path, "cwd")
    home = _mk(tmp_path, "home")
    # Post the package-split flip (roadmap #11): cli.__file__ is the engine module (cli.py), which
    # is not runnable as a bare script. Run the bin/tautline SHIM (the executable entrypoint).
    cli_path = cli.REPO_ROOT / "bin" / cli.CLI_NAME
    result = subprocess.run(
        [sys.executable, str(cli_path), "lane-start", "--target", str(repo)],
        cwd=str(cwd),
        env={"PATH": os.environ["PATH"], "HOME": str(home)},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode != 0  # fail-closed unchanged
    combined = result.stdout + result.stderr
    assert f"tautline init --target {repo}" in combined
    assert "tautline init --target .\n" not in combined


# ---------------------------------------------------------------------------
# full composed kickoff output passes the guard scanner (declarative offer)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("builder", ["unmanaged", "interview-pending", "source-unrendered"])
def test_full_kickoff_prompt_passes_guard(cli, tmp_path, builder):
    d = _mk(tmp_path, builder)
    if builder == "interview-pending":
        _write_interview(d)
    elif builder == "source-unrendered":
        _write_source_adapter(d, cli)
    info = cli.onboarding_info_for_offer(d, d)
    offer = "\n".join(cli.onboarding_offer_lines(info))
    output = cli.CLAUDE_ONBOARDING_KICKOFF_PROMPT_TEMPLATE.format(offer_lines=offer)
    assert not cli.response_has_forbidden_opt_in(output)
    assert "AskUserQuestion" in output


def test_launcher_content_passes_guard(cli):
    for skip in (False, True):
        assert not cli.response_has_forbidden_opt_in(cli.claude_launcher_content(skip))


# ---------------------------------------------------------------------------
# shell-safety: paths with spaces / metacharacters are quoted in emitted COMMANDS
# ---------------------------------------------------------------------------
def _command_after_flag(text, flag):
    """shlex-parse `text` and return the token following `flag` (as the shell would see it)."""
    import shlex

    tokens = shlex.split(text)
    return tokens[tokens.index(flag) + 1]


def test_offer_unmanaged_quotes_spaced_path(cli, tmp_path):
    target = _mk(tmp_path, "my repo")
    # invocation_cwd is the parent, so the root renders relative ("my repo") and must be quoted.
    info = dict(cli.onboarding_state(target, tmp_path), root=target)
    line = cli.onboarding_offer_lines(info)[0]
    assert "tautline init --target 'my repo'" in line
    assert _command_after_flag(line, "--target") == "my repo"


def test_offer_interview_pending_quotes_spaced_path(cli, tmp_path):
    target = _mk(tmp_path, "my repo")
    _write_interview(target)
    info = cli.onboarding_state(target, tmp_path)
    line = cli.onboarding_offer_lines(info)[0]
    assert "tautline init --target 'my repo' --continue" in line
    assert _command_after_flag(line, "--target") == "my repo"


def test_offer_source_unrendered_quotes_spaced_paths(cli, tmp_path):
    target = _mk(tmp_path, "my repo")
    _write_source_adapter(target, cli)
    info = cli.onboarding_state(target, tmp_path)
    line = cli.onboarding_offer_lines(info)[0]
    assert _command_after_flag(line, "--target") == "my repo"
    # the --project source path is under "my repo" -> also spaced and quoted -> parses back.
    assert _command_after_flag(line, "--project") == f"my repo/{cli.REPO_LOCAL_ADAPTER_FILE}"


def test_recovery_interview_pending_quotes_spaced_path(cli, tmp_path):
    target = _mk(tmp_path, "my repo")
    _write_interview(target)
    info = cli.onboarding_state(target, tmp_path)
    msg = cli.no_adapter_message(info)
    assert "tautline init --target 'my repo' --continue" in msg
    # the recovery line (indented under "Recovery command:") is shell-parseable back to the path.
    line = next(ln for ln in msg.splitlines() if "tautline init --target" in ln)
    assert _command_after_flag(line, "--target") == "my repo"


def test_recovery_source_unrendered_quotes_spaced_paths(cli, tmp_path):
    target = _mk(tmp_path, "my repo")
    _write_source_adapter(target, cli)
    info = cli.onboarding_state(target, tmp_path)
    msg = cli.no_adapter_message(info)
    render_line = next(ln for ln in msg.splitlines() if "tautline render-adapters" in ln)
    lane_line = next(ln for ln in msg.splitlines() if "tautline lane-start" in ln)
    expected_source = f"my repo/{cli.REPO_LOCAL_ADAPTER_FILE}"
    assert _command_after_flag(render_line, "--target") == "my repo"
    assert _command_after_flag(render_line, "--project") == expected_source
    assert _command_after_flag(lane_line, "--target") == "my repo"


def test_unmanaged_at_target_stays_unquoted_dot(cli, tmp_path):
    # shlex.quote('.') == '.', so the unmanaged-at-cwd command keeps the bare `--target .` form and
    # the composed message stays byte-identical to the golden.
    d = _mk(tmp_path, "bare")
    info = dict(cli.onboarding_state(d, d), root=d)
    assert "tautline init --target ." in cli.onboarding_offer_lines(info)[0]
    assert cli.no_adapter_message(cli.onboarding_state(d, d)) == LEGACY_NO_ADAPTER_MESSAGE
