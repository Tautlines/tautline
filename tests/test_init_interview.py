"""Cover for `tautline init` -- the setup interview.

Three layers, cheapest first: `lean.init_command` called directly with a hand-built
`argparse.Namespace` (matches how `tests/test_lean_profile.py` exercises `lean.slim_command`) for
the bulk of the behavior; a real subprocess for the one thing that has to be a real subprocess --
a scripted stdin run through the actual interactive prompts; and a real subprocess through
`bin/tautline` for the surfaces this feature touches OUTSIDE `lean.py` (the `render-adapters` /
`lane-status` nudge, and `validate-adapter` becoming lean-aware).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
sys.path.insert(0, str(REPO_ROOT / "src"))
from tautline_methodology import lean  # noqa: E402


# --- direct-call harness ------------------------------------------------------------------------

# Every attribute `_register_lean_init` puts on the `init` subparser's namespace, at the value
# argparse would give it when the flag is not passed. A test overrides only what it cares about,
# so a new flag added to the CLI and forgotten here fails LOUD (AttributeError from
# `lean.init_command`), not silently.
_FLAG_DEFAULTS = dict(
    name=None,
    repo=None,
    branch=None,
    test_cmd=None,
    backlog=None,
    backlog_path=None,
    backlog_repo=None,
    backlog_label=None,
    backlog_site=None,
    backlog_project=None,
    backlog_board=None,
    handoffs=None,
    rules=None,
    yes=False,
    force=False,
)


def _ns(target: Path, **overrides) -> argparse.Namespace:
    values = dict(_FLAG_DEFAULTS, target=target, **overrides)
    return argparse.Namespace(**values)


def _run_cli(args: list[str], *, cwd: Path | None = None, input: str | None = None):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=str(cwd) if cwd else None,
        input=input,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_config(target: Path) -> dict:
    return json.loads((target / ".tautline.json").read_text(encoding="utf-8"))


# --- the golden minimal config -------------------------------------------------------------------


def test_yes_with_no_flags_in_a_plain_directory_gives_the_golden_minimal_config(tmp_path, capsys):
    """No git remote, no existing config, every question defaulted: the smallest lean-1 config
    `init` can produce. `handoffs` and `projectRules` are absent because those answers took the
    schema's own default -- LEAN LAW, applied to `init`'s output. `backlog` is the one exception:
    `init` always records that answer explicitly (see `lean_config_from_answers`), because Track
    J's `_backlog_norm` render line -- "this is where the backlog lives, do not create a second
    one" -- only fires when the key is present, and the whole point of asking the question is
    that answer reaching the adapter."""
    target = tmp_path / "widget"
    target.mkdir()
    rc = lean.init_command(_ns(target, yes=True))
    assert rc == 0
    assert _read_config(target) == {
        "$schema": "https://tautline.dev/schemas/adapter/lean-1.json",
        "schemaVersion": "lean-1",
        "project": {"name": "widget"},
        "integrationBranch": "main",
        "commands": {"test": "scripts/test.sh"},
        "backlog": {"provider": "local"},
        "workCoordination": True,
    }
    assert lean.lean_config_errors(_read_config(target)) == []
    out = capsys.readouterr().out
    assert "matches the lean-1 schema" in out
    assert "what next:" in out
    assert "tautline backlog add" in out


def test_yes_prefers_git_remote_and_current_branch_over_the_bare_defaults(tmp_path, capsys):
    target = tmp_path / "repo"
    target.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(target)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(target), "remote", "add", "origin", "git@github.com:acme/widget.git"],
        check=True,
        capture_output=True,
    )
    rc = lean.init_command(_ns(target, yes=True))
    assert rc == 0
    cfg = _read_config(target)
    assert cfg["project"] == {"name": "repo", "repo": "acme/widget"}
    assert cfg["integrationBranch"] == "trunk"


# --- explicit flags, one per question, plus the provider follow-ups -----------------------------


@pytest.mark.parametrize(
    "provider, provider_flags, expected_backlog",
    [
        ("local", {}, {"provider": "local"}),
        ("local", {"backlog_path": "backlog/QUEUE.md"}, {"provider": "local", "path": "backlog/QUEUE.md"}),
        (
            "github",
            {"backlog_repo": "acme/widget", "backlog_label": "todo"},
            {"provider": "github", "repo": "acme/widget", "label": "todo"},
        ),
        (
            "jira",
            {
                "backlog_site": "https://acme.atlassian.net",
                "backlog_project": "ENG",
                "backlog_board": "42",  # Jira boards are numeric ids, not names -- backlog.py
                # (Track J) validates this; see test_backlog_board_must_be_a_jira_board_id below.
            },
            {
                "provider": "jira",
                "site": "https://acme.atlassian.net",
                "project": "ENG",
                "board": "42",
            },
        ),
    ],
)
def test_every_provider_writes_the_expected_backlog_shape(
    tmp_path, provider, provider_flags, expected_backlog
):
    """Every question, and every provider-specific field, has a flag. `--yes` covers whichever
    provider fields THIS case leaves unset (real full-automation, with zero prompts reached at
    all when every relevant flag IS given, is proven separately below)."""
    target = tmp_path / "svc"
    target.mkdir()
    rc = lean.init_command(
        _ns(
            target,
            yes=True,  # covers whichever provider-specific field this case does NOT pass
            name="Service",
            repo="acme/svc",
            branch="develop",
            test_cmd="pytest -q",
            backlog=provider,
            handoffs=True,
            rules=["Tenants are isolated."],
            **provider_flags,
        )
    )
    assert rc == 0
    cfg = _read_config(target)
    assert cfg["project"] == {"name": "Service", "repo": "acme/svc"}
    assert cfg["integrationBranch"] == "develop"
    assert cfg["commands"] == {"test": "pytest -q"}
    assert cfg["handoffs"] is True
    assert cfg["projectRules"] == ["Tenants are isolated."]
    assert cfg.get("backlog") == expected_backlog
    assert lean.lean_config_errors(cfg) == []


@pytest.mark.parametrize(
    "provider, provider_flags, expected_line",
    [
        ("local", {}, "Backlog lives in local (QUEUE.md)."),
        (
            "github",
            {"backlog_repo": "acme/widget"},
            "Backlog lives in github (acme/widget).",
        ),
        (
            "jira",
            {"backlog_site": "https://acme.atlassian.net", "backlog_project": "ENG"},
            "Backlog lives in jira (ENG).",
        ),
    ],
)
def test_the_backlog_answer_is_echoed_with_a_confirm_line(
    tmp_path, capsys, provider, provider_flags, expected_line
):
    """Right after the backlog-provider question is answered, `init` echoes one confirm line --
    Track J's own `_backlog_norm` text (the exact sentence the rendered adapter also carries), not
    a hand-written paraphrase that could drift from it."""
    target = tmp_path / "svc"
    target.mkdir()
    rc = lean.init_command(_ns(target, yes=True, name="Service", backlog=provider, **provider_flags))
    assert rc == 0
    out = capsys.readouterr().out
    assert expected_line in out
    # It is the SAME sentence the adapter renders, not a lookalike.
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    norm_line = next(line for line in out.splitlines() if line.startswith("Backlog lives in"))
    assert norm_line in claude_md


def test_backlog_board_must_be_a_jira_board_id(tmp_path):
    """`init`'s fail-loud validation step is Track J's REAL `backlog_config_errors`, not a
    lookalike: a human-readable board NAME (the natural thing to type) is caught here, because
    Jira boards are addressed by numeric id, not name."""
    target = tmp_path / "svc"
    target.mkdir()
    with pytest.raises(SystemExit) as excinfo:
        lean.init_command(
            _ns(
                target,
                yes=True,
                name="Service",
                backlog="jira",
                backlog_site="https://acme.atlassian.net",
                backlog_project="ENG",
                backlog_board="Sprint Board",
            )
        )
    assert excinfo.value.code == 1
    written = _read_config(target)
    assert lean.lean_config_errors(written), (
        "the config was still written to disk (fail-loud reports the error on the file that "
        "exists, per the spec, rather than silently discarding it) but must remain invalid"
    )


def test_the_flag_form_reaches_no_input_call(tmp_path):
    """Every question answered by a flag: the real CLI, with stdin closed, must not hang or crash
    trying to read a prompt it never needed to ask."""
    target = tmp_path / "agentrun"
    target.mkdir()
    result = _run_cli(
        [
            "init",
            "--target",
            str(target),
            "--name",
            "Agentrun",
            "--branch",
            "main",
            "--test-cmd",
            "make test",
            "--backlog",
            "local",
            "--backlog-path",
            "QUEUE.md",
            "--yes",
        ],
        input="",  # closed stdin: an accidental input() call raises EOFError, failing the run
    )
    assert result.returncode == 0, result.stderr
    assert (target / ".tautline.json").is_file()


def test_more_than_three_rule_flags_fails_loud_instead_of_dropping_the_extra(tmp_path):
    target = tmp_path / "svc"
    target.mkdir()
    with pytest.raises(SystemExit, match="at most 3"):
        lean.init_command(
            _ns(target, yes=True, rules=["a", "b", "c", "d"])
        )
    assert not (target / ".tautline.json").exists()


# --- the interview, via a REAL scripted stdin run ------------------------------------------------


def test_interview_via_scripted_stdin_writes_the_expected_config(tmp_path):
    target = tmp_path / "acme-corp"
    target.mkdir()
    script = "\n".join(
        [
            "Acme Corp",  # 1. project name
            "acme/repo",  # 2. repo
            "release",  # 3. integration branch
            "make ci",  # 4. test command
            "local",  # 5. where does your backlog live
            "",  # 6. queue file path -- blank accepts the default
            "y",  # 7. continuity handoffs on?
            "Keep secrets in vault",  # 8. rule 1
            "",  # blank stops the rule loop after 1
        ]
    ) + "\n"
    result = _run_cli(["init", "--target", str(target)], input=script)
    assert result.returncode == 0, result.stderr
    assert _read_config(target) == {
        "$schema": "https://tautline.dev/schemas/adapter/lean-1.json",
        "schemaVersion": "lean-1",
        "project": {"name": "Acme Corp", "repo": "acme/repo"},
        "integrationBranch": "release",
        "commands": {"test": "make ci"},
        "backlog": {"provider": "local"},
        "workCoordination": True,
        "handoffs": True,
        "projectRules": ["Keep secrets in vault"],
    }
    # The prompts themselves reached the human -- a scripted run that silently skipped a question
    # would still produce a plausible-looking config, which is exactly the failure this asserts
    # against.
    assert "Project name" in result.stdout
    assert "Where does your backlog live?" in result.stdout
    assert "Continuity handoffs on?" in result.stdout


# --- overwrite refusal, and --force as reconfigure -----------------------------------------------


def test_overwrite_refusal_without_force(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    assert lean.init_command(_ns(target, yes=True, name="First")) == 0
    before = (target / ".tautline.json").read_text(encoding="utf-8")

    with pytest.raises(SystemExit, match="already exists"):
        lean.init_command(_ns(target, yes=True, name="Second"))

    assert (target / ".tautline.json").read_text(encoding="utf-8") == before, (
        "a refused overwrite must not touch the file on disk"
    )


def test_force_reconfigures_by_prefilling_from_the_existing_config(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    first = _ns(
        target,
        yes=True,
        name="Original",
        repo="acme/original",
        branch="main",
        test_cmd="make test",
        backlog="github",
        backlog_repo="acme/original",
        handoffs=True,
        rules=["Never log PII"],
    )
    assert lean.init_command(first) == 0
    written_once = _read_config(target)

    # --yes and NOTHING else: every answer must come from the config already on disk, not from
    # bare schema defaults -- otherwise a --force re-run silently erodes a project's config.
    assert lean.init_command(_ns(target, yes=True, force=True)) == 0
    assert _read_config(target) == written_once


def test_force_with_explicit_flags_overrides_only_what_was_asked(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    assert lean.init_command(
        _ns(target, yes=True, name="Original", branch="main", test_cmd="make test")
    ) == 0
    assert lean.init_command(
        _ns(target, yes=True, force=True, branch="release")
    ) == 0
    cfg = _read_config(target)
    assert cfg["project"]["name"] == "Original"  # untouched: still prefilled from disk
    assert cfg["integrationBranch"] == "release"  # the one thing this run changed


def test_force_over_a_legacy_adapter_archives_it_instead_of_stranding_it(tmp_path, capsys):
    """`--force` against a target whose only existing adapter is the LEGACY-named
    `.minervit-ai-delivery.json` must not leave it sitting there, superseded and unmentioned,
    once `.tautline.json` exists beside it -- that is a silently orphaned file with content
    (rules, settings) `tautline slim` would have carried across and `init` just did not."""
    target = tmp_path / "proj"
    target.mkdir()
    legacy = target / ".minervit-ai-delivery.json"
    legacy.write_text(json.dumps({"schemaVersion": "1.0.0", "project": "Legacy Co"}), encoding="utf-8")

    assert lean.init_command(_ns(target, yes=True, name="New", force=True)) == 0

    archived = target / (".minervit-ai-delivery.json" + lean.LEGACY_INIT_SUFFIX)
    assert not legacy.exists(), "the legacy file must not be left where slim would still find it"
    assert archived.is_file()
    assert json.loads(archived.read_text(encoding="utf-8"))["project"] == "Legacy Co"
    out = capsys.readouterr().out
    assert "archived" in out and str(archived) in out

    # Idempotent: a SECOND --force (now that .tautline.json exists) must not touch the archived
    # file again, or double-archive, or error.
    assert lean.init_command(_ns(target, yes=True, name="New", force=True)) == 0
    assert archived.is_file()
    assert not (target / (".minervit-ai-delivery.json" + lean.LEGACY_INIT_SUFFIX + "-2")).exists()


def test_force_over_a_lean_config_does_not_touch_any_legacy_file(tmp_path):
    """The archiving path is scoped to the LEGACY name specifically -- overwriting an existing
    `.tautline.json` must never be mistaken for stranding a legacy adapter that is not there."""
    target = tmp_path / "proj"
    target.mkdir()
    assert lean.init_command(_ns(target, yes=True, name="First")) == 0
    assert lean.init_command(_ns(target, yes=True, name="Second", force=True)) == 0
    assert not (target / (".tautline.json" + lean.LEGACY_INIT_SUFFIX)).exists()


# --- rendering -------------------------------------------------------------------------------


def test_init_renders_claude_and_agents_md_within_budget(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    assert lean.init_command(
        _ns(
            target,
            yes=True,
            name="Proj",
            backlog="jira",
            backlog_site="https://acme.atlassian.net",
            backlog_project="ENG",
            handoffs=True,
            rules=["Rule one.", "Rule two.", "Rule three."],
        )
    ) == 0
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (target / name).read_text(encoding="utf-8")
        assert text.startswith(lean.GENERATED_HEADER)
        assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
        assert "Rule one." in text


def test_the_handoffs_question_drives_track_h_s_real_render_lines(tmp_path):
    """`init`'s `handoffs` answer must reach Track H's actual `HANDOFF_PROCESS_LINES` render --
    not a stand-in. Answered "N" (the default), neither line appears; answered "y", both do,
    verbatim."""
    off = tmp_path / "off"
    off.mkdir()
    assert lean.init_command(_ns(off, yes=True, name="Off")) == 0
    off_text = (off / "CLAUDE.md").read_text(encoding="utf-8")
    for line in lean.HANDOFF_PROCESS_LINES:
        assert line not in off_text

    on = tmp_path / "on"
    on.mkdir()
    assert lean.init_command(_ns(on, yes=True, name="On", handoffs=True)) == 0
    on_text = (on / "CLAUDE.md").read_text(encoding="utf-8")
    for line in lean.HANDOFF_PROCESS_LINES:
        assert line in on_text
    assert len(on_text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES


def test_init_never_clobbers_a_hand_authored_claude_md(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "CLAUDE.md").write_text("# Hand-written\nDo not overwrite me.\n", encoding="utf-8")
    assert lean.init_command(_ns(target, yes=True, name="Proj")) == 0
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "# Hand-written\nDo not overwrite me.\n"
    proposed = target / "CLAUDE.md.lean-proposed"
    assert proposed.is_file()
    assert proposed.read_text(encoding="utf-8").startswith(lean.GENERATED_HEADER)


# --- init -> render loop, end to end on a tmp repo -----------------------------------------------


def test_init_then_backlog_then_render_loop_e2e(tmp_path):
    """A full adoption journey on a fresh git repo, through the REAL registered verbs (Track J's
    `backlog`, Track H's render addition) rather than stand-ins for them:

      init -> the rendered adapter already carries Track J's real backlog norm line ->
      backlog add/list -> a second `init --force --yes` (the documented "reconfigure" path) is a
      clean no-op re-render.
    """
    target = tmp_path / "e2e-repo"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)

    result = _run_cli(
        [
            "init",
            "--target",
            str(target),
            "--name",
            "E2E Repo",
            "--branch",
            "main",
            "--test-cmd",
            "scripts/test.sh",
            "--backlog",
            "local",
            "--yes",
        ],
        input="",
    )
    assert result.returncode == 0, result.stderr
    assert (target / ".tautline.json").is_file()
    assert (target / "CLAUDE.md").is_file()
    assert (target / "AGENTS.md").is_file()

    # Track J's `_backlog_norm`, driven by `init`'s answer -- not a stub of it. This is the line
    # that tells an agent NOT to create a second backlog (a TODO.md, say) alongside this one.
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Backlog lives in local (QUEUE.md)" in claude_md
    assert "tautline backlog add" in claude_md
    assert "The queue file is the only backlog surface." in claude_md

    validated = _run_cli(["validate-adapter", "--project", str(target / ".tautline.json")])
    assert validated.returncode == 0, validated.stderr
    assert "matches the lean-1 schema" in validated.stdout

    # find_adapter_root now resolves inside this repo: the gentle-nudge must NOT fire once a repo
    # is adopted.
    status = _run_cli(["lane-status", "--target", str(target)])
    assert lean.INIT_NUDGE_LINE not in status.stdout

    # The REAL `tautline backlog` verb (Track J), against the provider `init` just configured.
    added = _run_cli(["backlog", "add", "Write the first spec", "--target", str(target)])
    assert added.returncode == 0, added.stderr
    assert "Write the first spec" in added.stdout

    listed = _run_cli(["backlog", "list", "--target", str(target)])
    assert listed.returncode == 0, listed.stderr
    assert "Write the first spec" in listed.stdout
    assert "ready" in listed.stdout

    rerender = _run_cli(
        ["init", "--target", str(target), "--force", "--yes"],
        input="",
    )
    assert rerender.returncode == 0, rerender.stderr
    assert "wrote" in rerender.stdout and str(target / "CLAUDE.md") not in rerender.stdout, (
        "an unchanged re-render must not report CLAUDE.md/AGENTS.md as rewritten"
    )


def test_handoffs_on_reaches_track_h_s_lane_status_freshness_line(tmp_path):
    """`init --handoffs` sets the config key Track H's `lane-status` freshness line reads --
    real integration, not two features that happen to share a flag name."""
    result = _run_cli(
        ["init", "--target", str(tmp_path), "--name", "Proj", "--handoffs", "--yes"],
        input="",
    )
    assert result.returncode == 0, result.stderr
    status = _run_cli(["lane-status", "--target", str(tmp_path)])
    assert "handoff: none" in status.stdout, status.stdout


# --- the gentle nudge: backlog / render-adapters / lane-status on an un-adopted repo -------------


def test_backlog_nudges_toward_init_on_an_unadopted_repo(tmp_path):
    """Unlike `render-adapters`/`lane-status`, `backlog` has no OTHER reason to run without a
    config -- there is nothing for it to read -- so Track J built the "point at `tautline init`"
    message directly into `backlog_command` (`NO_CONFIG`) rather than this needing a second,
    redundant nudge wrapped around it. This proves that already satisfies the requirement."""
    result = _run_cli(["backlog", "list", "--target", str(tmp_path)])
    assert result.returncode != 0
    assert "tautline init" in result.stdout


def test_lane_status_nudges_toward_init_on_an_unadopted_repo(tmp_path):
    result = _run_cli(["lane-status", "--target", str(tmp_path)])
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert lean.INIT_NUDGE_LINE in result.stdout


def test_lane_status_hook_mode_stays_byte_silent_on_an_unadopted_repo():
    """The nudge is advisory prose; it must not break the hook contract the surrounding function
    documents (`--hook` is silent outside a managed lane so unrelated repos on the machine never
    see it)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        result = _run_cli(["lane-status", "--target", tmp, "--hook"])
    assert result.returncode == 0
    assert result.stdout == ""


def test_render_adapters_nudges_toward_init_on_an_unadopted_repo(tmp_path):
    result = _run_cli(
        [
            "render-adapters",
            "--project",
            str(tmp_path / ".tautline.json"),
            "--target",
            str(tmp_path),
            "--write",
        ]
    )
    assert lean.INIT_NUDGE_LINE in result.stderr
    # The nudge is advisory, not a gate: whatever render-adapters does today for an unresolvable
    # --project keeps happening, unchanged, alongside it.
    assert result.returncode != 0
    assert "trusted source adapter" in result.stderr


def test_render_adapters_does_not_nudge_an_adopted_repo(tmp_path):
    assert lean.init_command(_ns(tmp_path, yes=True, name="Adopted")) == 0
    result = _run_cli(
        [
            "render-adapters",
            "--project",
            str(tmp_path / ".tautline.json"),
            "--target",
            str(tmp_path),
            "--write",
        ]
    )
    assert lean.INIT_NUDGE_LINE not in result.stderr


# --- validate-adapter becomes lean-aware ----------------------------------------------------------


def test_validate_adapter_accepts_a_lean_config(tmp_path):
    assert lean.init_command(_ns(tmp_path, yes=True, name="Proj")) == 0
    result = _run_cli(["validate-adapter", "--project", str(tmp_path / ".tautline.json")])
    assert result.returncode == 0
    assert "matches the lean-1 schema" in result.stdout


def test_validate_adapter_reports_every_lean_violation(tmp_path):
    path = tmp_path / ".tautline.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "lean-1",
                "project": {"name": "X"},
                "integrationBranch": "main",
                "commands": {"test": "x"},
                "handoffs": "yes",
                "backlog": {"provider": "bitbucket"},
            }
        ),
        encoding="utf-8",
    )
    result = _run_cli(["validate-adapter", "--project", str(path)])
    assert result.returncode == 1
    assert "handoffs: expected boolean" in result.stderr
    assert "backlog.provider" in result.stderr


def test_validate_adapter_ceremony_path_is_unaffected(tmp_path):
    """The lean branch must not swallow a non-lean adapter -- it has to fall through to the
    existing ceremony schema exactly as before."""
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps({"schemaVersion": "0.1.0"}), encoding="utf-8")
    result = _run_cli(["validate-adapter", "--project", str(path)])
    assert "lean-1" not in result.stdout
    assert "lean-1" not in result.stderr


# --- flag parity: every interview question is also a flag ----------------------------------------


def test_help_lists_a_flag_for_every_question():
    result = _run_cli(["init", "--help"])
    assert result.returncode == 0
    for flag in (
        "--target",
        "--name",
        "--repo",
        "--branch",
        "--test-cmd",
        "--backlog",
        "--backlog-path",
        "--backlog-repo",
        "--backlog-label",
        "--backlog-site",
        "--backlog-project",
        "--backlog-board",
        "--handoffs",
        "--rule",
        "--yes",
        "--force",
    ):
        assert flag in result.stdout, f"{flag} is missing from `tautline init --help`"


def test_the_interview_never_asks_a_ninth_question(tmp_path):
    """EXACTLY 8 lines of input, one per question, the 8th a blank that declines every rule.
    stdin is then EOF: a 9th `input()` call raises EOFError and the process exits non-zero. A
    clean exit with this exact input is therefore proof the interview asks <=8 questions, not
    just a claim about it."""
    target = tmp_path / "q-corp"
    target.mkdir()
    eight_lines = "\n".join(
        [
            "Q Corp",  # 1. name
            "",  # 2. repo
            "",  # 3. integration branch
            "",  # 4. test command
            "local",  # 5. where does your backlog live
            "",  # 6. the one backlog follow-up
            "",  # 7. continuity handoffs on?
            "",  # 8. project rules -- blank declines all three
        ]
    ) + "\n"
    result = _run_cli(["init", "--target", str(target)], input=eight_lines)
    assert result.returncode == 0, result.stdout + result.stderr
    cfg = _read_config(target)
    assert cfg["project"]["name"] == "Q Corp"
    assert "projectRules" not in cfg


def test_eof_partway_through_the_interview_aborts_cleanly(tmp_path):
    """Some answers given (`input()` succeeds at least once), then stdin closes before the
    interview finishes -- the gap between the all-flags "zero prompts reached" case above and the
    exactly-8-then-EOF case: `input()` raising EOFError mid-interview must not surface a raw
    traceback, and must leave nothing on disk."""
    target = tmp_path / "partial"
    target.mkdir()
    result = _run_cli(
        ["init", "--target", str(target)],
        input="Partial Co\nacme/partial\n",  # answers name + repo, then stdin closes
    )
    assert result.returncode == 1
    assert "init: aborted (no input; nothing was written)" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not (target / ".tautline.json").exists()
    assert not (target / "CLAUDE.md").exists()


def test_immediate_eof_before_any_answer_also_aborts_cleanly(tmp_path):
    target = tmp_path / "empty"
    target.mkdir()
    result = _run_cli(["init", "--target", str(target)], input="")
    assert result.returncode == 1
    assert "init: aborted (no input; nothing was written)" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not (target / ".tautline.json").exists()
