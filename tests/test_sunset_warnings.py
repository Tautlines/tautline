"""Compat-sunset warn stage (roadmap #16, PR 1).

Every legacy minervit-era surface warns ONCE per process on use, stderr-only, naming the tautline
replacement and the 1.0 removal, with exit codes and stdout byte-identical. Four chokepoints:
env (resolve_env + the shell launcher), cli (the minervit-methodology launcher name), markers
(legacy adapter markers + config path), and slug (the pre-rebrand methodology repo slug). Warnings
are suppressible under both spellings and byte-silent in hook-shaped invocations.
"""

import importlib
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

util = importlib.import_module("tautline_methodology.util")

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "bin" / "tautline"
LEGACY_CLI_PATH = ROOT / "bin" / "minervit-methodology"


@pytest.fixture(autouse=True)
def _reset_sunset():
    util._reset_sunset_state()
    yield
    util._reset_sunset_state()


def _warn_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("deprecation_warning:")]


# --- chokepoint 1: env (resolve_env / util twin) ----------------------------------------------


def test_env_minervit_only_warns_once_naming_replacement(monkeypatch, capsys):
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "v")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "v"
    lines = _warn_lines(capsys.readouterr().err)
    assert lines == [
        "deprecation_warning: MINERVIT_GITHUB_RATE_GUARD is deprecated and will be "
        "removed in 1.0; use TAUTLINE_GITHUB_RATE_GUARD"
    ]


def test_env_tautline_spelling_is_silent(monkeypatch, capsys):
    monkeypatch.setenv("TAUTLINE_GITHUB_RATE_GUARD", "taut")
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "minv")
    assert util.resolve_env("MINERVIT_GITHUB_RATE_GUARD") == "taut"
    assert capsys.readouterr().err == ""


def test_twelve_distinct_envs_warn_twelve_times_repeat_is_one(monkeypatch, capsys):
    names = [
        "MINERVIT_GITHUB_CACHE_DIR",
        "MINERVIT_GITHUB_TELEMETRY_DIR",
        "MINERVIT_GITHUB_SERIALIZE",
        "MINERVIT_GITHUB_COALESCE",
        "MINERVIT_METHODOLOGY_TELEMETRY",
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT",
        "MINERVIT_METHODOLOGY_UPDATE_PROBE",
        "MINERVIT_METHODOLOGY_ALLOW_FANOUT",
        "MINERVIT_GITHUB_RATE_GUARD",
        "MINERVIT_LANE_EPICS",
        "MINERVIT_RENDERER_KIT_STATE_DIR",
        "MINERVIT_REAL_CODEX",
    ]
    for name in names:
        monkeypatch.delenv("TAUTLINE_" + name[len("MINERVIT_"):], raising=False)
        monkeypatch.setenv(name, "x")
    for name in names:
        util.resolve_env(name)
    for _ in range(3):
        util.resolve_env(names[0])  # repeats stay one
    lines = _warn_lines(capsys.readouterr().err)
    assert len(lines) == 12
    for name in names:
        assert any(name in ln for ln in lines), name


def test_env_dynamic_computed_name_gets_sane_replacement(monkeypatch, capsys):
    # R3 amendment (a): a computed/webhook-style MINERVIT_ name slices to a valid TAUTLINE_ twin
    # and never crashes; a non-MINERVIT_ computed name stays silent.
    monkeypatch.delenv("TAUTLINE_LANE_ZZZ", raising=False)
    monkeypatch.setenv("MINERVIT_LANE_ZZZ", "1")
    util.resolve_env("MINERVIT_LANE_" + "ZZZ")
    err = capsys.readouterr().err
    assert "MINERVIT_LANE_ZZZ is deprecated" in err
    assert "use TAUTLINE_LANE_ZZZ" in err
    monkeypatch.setenv("SOME_PROJECT_WEBHOOK", "u")
    util._reset_sunset_state()
    assert util.resolve_env("SOME_PROJECT_WEBHOOK") == "u"
    assert capsys.readouterr().err == ""


def test_env_child_env_assembly_is_silent(capsys):
    got = util.resolve_env(
        "MINERVIT_GITHUB_RATE_GUARD", environ={"MINERVIT_GITHUB_RATE_GUARD": "v"}
    )
    assert got == "v"
    assert capsys.readouterr().err == ""


# --- suppression (both spellings) -------------------------------------------------------------


@pytest.mark.parametrize(
    "knob", ["TAUTLINE_SUPPRESS_SUNSET_WARNINGS", "MINERVIT_SUPPRESS_SUNSET_WARNINGS"]
)
def test_suppression_both_spellings_silence_every_family(monkeypatch, capsys, cli, knob):
    monkeypatch.setenv(knob, "1")
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "v")
    util.resolve_env("MINERVIT_GITHUB_RATE_GUARD")
    cli.sunset_warning("cli", cli.LEGACY_CLI_NAME, cli.CLI_NAME)
    cli.sunset_warning("markers", cli.LEGACY_LANE_ADAPTER_FILE, cli.LANE_ADAPTER_FILE)
    assert capsys.readouterr().err == ""


def test_suppression_zero_value_does_not_suppress(monkeypatch, capsys):
    monkeypatch.setenv("TAUTLINE_SUPPRESS_SUNSET_WARNINGS", "0")
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "v")
    util.resolve_env("MINERVIT_GITHUB_RATE_GUARD")
    assert _warn_lines(capsys.readouterr().err)


# --- suppression precedence agrees across layers (util twin + bin standalone fallback) ---------
# TAUTLINE-first-nonblank-else-legacy: a set, non-blank TAUTLINE_ value decides on its own (even
# "0", which shadows a legacy "1"); a blank/whitespace-only TAUTLINE_ falls through to the legacy
# spelling. Both Python layers must agree on the self-contradictory + whitespace configs (the shell
# `${TAUTLINE:-${MINERVIT:-}}` form already resolves this way).
@pytest.mark.parametrize(
    "taut,legacy,suppressed",
    [
        (None, None, False),   # neither set -> warns
        ("1", None, True),     # tautline truthy -> suppressed
        ("0", None, False),    # tautline "0" -> warns
        (None, "1", True),     # legacy-only truthy -> suppressed
        (None, "0", False),    # legacy-only "0" -> warns
        ("0", "1", False),     # contradiction: TAUTLINE-first "0" wins -> warns (not legacy "1")
        ("1", "0", True),      # contradiction: TAUTLINE-first "1" wins -> suppressed
        ("   ", "1", True),    # whitespace TAUTLINE falls through to legacy "1" -> suppressed
        ("   ", None, False),  # whitespace TAUTLINE, no legacy -> warns
    ],
)
def test_suppression_precedence_agrees_across_layers(
    monkeypatch, capsys, cli, taut, legacy, suppressed
):
    for name, val in (
        ("TAUTLINE_SUPPRESS_SUNSET_WARNINGS", taut),
        ("MINERVIT_SUPPRESS_SUNSET_WARNINGS", legacy),
    ):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    # a plain non-hook argv so the hook guard never masks the pure suppression decision
    monkeypatch.setattr(sys, "argv", ["tautline", "version"])

    # util twin
    util._reset_sunset_state()
    assert util._sunset_suppressed() is suppressed

    # bin standalone fallback (fresh dedup key so silence can only come from suppression)
    cli._SUNSET_EMITTED_FALLBACK.clear()
    cli._sunset_warning_fallback("env", "MINERVIT_PRECEDENCE_PROBE", "TAUTLINE_PRECEDENCE_PROBE")
    warned = bool(_warn_lines(capsys.readouterr().err))
    assert warned is (not suppressed)


# --- hook silence (verbs + --hook flag) -------------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["session-start-hook"], True),
        (["plan-finalization-hook", "--target", "."], True),
        (["autonomy-directive", "--hook"], True),
        (["--hook"], True),
        (["version", "--no-remote"], False),
        (["lane-start"], False),
        ([], False),
        (["-x", "--flag"], False),
    ],
)
def test_is_hook_invocation(argv, expected):
    assert util.is_hook_invocation(argv) is expected


@pytest.mark.parametrize(
    "argv", [["x", "session-start-hook"], ["x", "autonomy-directive", "--hook"]]
)
def test_hook_context_silences_env_warning(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "v")
    util.resolve_env("MINERVIT_GITHUB_RATE_GUARD")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "argv",
    [["tautline", "session-start-hook"], ["tautline", "autonomy-directive", "--hook"]],
)
def test_fallback_is_byte_silent_in_hook_context(monkeypatch, capsys, cli, argv):
    # The standalone-bin fallback (used when the util package is unavailable) must also honor
    # total containment: no stderr in a hook-shaped invocation, even with suppression unset.
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.delenv("TAUTLINE_SUPPRESS_SUNSET_WARNINGS", raising=False)
    monkeypatch.delenv("MINERVIT_SUPPRESS_SUNSET_WARNINGS", raising=False)
    cli._SUNSET_EMITTED_FALLBACK.clear()
    cli._sunset_warning_fallback("markers", ".minervit-ai-delivery.json", ".tautline.json")
    assert capsys.readouterr().err == ""


def test_fallback_warns_outside_hook_context(monkeypatch, capsys, cli):
    # Control for the guard above: the same fallback call with a plain (non-hook) argv DOES emit,
    # proving the silence comes from the hook guard rather than dedup or suppression.
    monkeypatch.setattr(sys, "argv", ["tautline", "version"])
    monkeypatch.delenv("TAUTLINE_SUPPRESS_SUNSET_WARNINGS", raising=False)
    monkeypatch.delenv("MINERVIT_SUPPRESS_SUNSET_WARNINGS", raising=False)
    cli._SUNSET_EMITTED_FALLBACK.clear()
    cli._sunset_warning_fallback("markers", ".minervit-ai-delivery.json", ".tautline.json")
    assert _warn_lines(capsys.readouterr().err) == [
        "deprecation_warning: .minervit-ai-delivery.json is deprecated and will be "
        "removed in 1.0; use .tautline.json"
    ]


# --- chokepoint 2: cli (legacy launcher name, marker-based) -----------------------------------


def test_cli_marker_warns_once_then_strips(monkeypatch, capsys, cli):
    monkeypatch.setattr(sys, "argv", ["tautline", "version"])
    monkeypatch.setenv("TAUTLINE_LEGACY_LAUNCHER_INVOKED", "minervit-methodology")
    cli._consume_legacy_launcher_marker()
    lines = _warn_lines(capsys.readouterr().err)
    assert lines == [
        "deprecation_warning: minervit-methodology is deprecated and will be "
        "removed in 1.0; use tautline"
    ]
    assert "TAUTLINE_LEGACY_LAUNCHER_INVOKED" not in os.environ  # stripped
    cli._consume_legacy_launcher_marker()  # no marker -> silent second time
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "argv", [["x", "session-start-hook"], ["x", "autonomy-directive", "--hook"]]
)
def test_cli_marker_hook_strips_silently(monkeypatch, capsys, cli, argv):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("TAUTLINE_LEGACY_LAUNCHER_INVOKED", "minervit-methodology")
    cli._consume_legacy_launcher_marker()
    assert capsys.readouterr().err == ""
    assert "TAUTLINE_LEGACY_LAUNCHER_INVOKED" not in os.environ  # still stripped


def test_cli_argv0_basename_fallback(monkeypatch, capsys, cli):
    monkeypatch.delenv("TAUTLINE_LEGACY_LAUNCHER_INVOKED", raising=False)
    monkeypatch.setattr(sys, "argv", ["/opt/bin/minervit-methodology", "version"])
    cli._consume_legacy_launcher_marker()
    assert _warn_lines(capsys.readouterr().err)


def test_cli_canonical_argv0_is_silent(monkeypatch, capsys, cli):
    monkeypatch.delenv("TAUTLINE_LEGACY_LAUNCHER_INVOKED", raising=False)
    monkeypatch.setattr(sys, "argv", ["/opt/bin/tautline", "version"])
    cli._consume_legacy_launcher_marker()
    assert capsys.readouterr().err == ""


def test_cli_shim_exec_warns_once_end_to_end():
    res = subprocess.run(
        [sys.executable, str(LEGACY_CLI_PATH), "version", "--no-remote"],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert "methodology_repo:" in res.stdout
    lines = _warn_lines(res.stderr)
    assert lines == [
        "deprecation_warning: minervit-methodology is deprecated and will be "
        "removed in 1.0; use tautline"
    ]


def test_cli_canonical_shim_is_silent_end_to_end():
    res = subprocess.run(
        [str(CLI_PATH), "version", "--no-remote"],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert not _warn_lines(res.stderr)


# The cli warning must also fire for legacy-name invocations that TERMINATE INSIDE argparse (help,
# a bare no-subcommand error, an invalid verb): those never reach dispatch, so the marker consume
# runs as main()'s first statement, before parse_args. Warning is stderr-only; stdout/exit intact.


def _run_legacy(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LEGACY_CLI_PATH), *args],
        capture_output=True, text=True, timeout=60,
    )


def test_cli_legacy_help_warns_once_help_intact_end_to_end():
    res = _run_legacy("--help")
    assert res.returncode == 0, res.stderr
    assert "usage: tautline" in res.stdout  # help text lands on stdout, unchanged
    assert _warn_lines(res.stderr) == [
        "deprecation_warning: minervit-methodology is deprecated and will be "
        "removed in 1.0; use tautline"
    ]


def test_cli_legacy_no_subcommand_warns_end_to_end():
    res = _run_legacy()  # argparse errors on the required subcommand (exit 2)
    assert res.returncode == 2, res.stderr
    assert _warn_lines(res.stderr) == [
        "deprecation_warning: minervit-methodology is deprecated and will be "
        "removed in 1.0; use tautline"
    ]


def test_cli_legacy_invalid_subcommand_warns_end_to_end():
    res = _run_legacy("definitely-not-a-verb")
    assert res.returncode == 2, res.stderr
    assert _warn_lines(res.stderr) == [
        "deprecation_warning: minervit-methodology is deprecated and will be "
        "removed in 1.0; use tautline"
    ]


def test_cli_legacy_hook_with_help_stays_silent_end_to_end():
    # Hook containment survives the earlier (pre-argparse) placement: a `--hook` argv strips the
    # marker silently even when --help is present, so no cli warning reaches a hook's stderr.
    res = _run_legacy("--hook", "--help")
    assert not _warn_lines(res.stderr), res.stderr


def test_wheel_wrapper_sets_marker_when_argv0_is_legacy(cli, tmp_path):
    # The generated wheel wrapper sets the marker before it resets sys.argv[0] and runpy's the
    # embedded CLI, when its OWN console-script basename is the legacy name (argv0 pattern from
    # tests/test_registry_package_real.py).
    wrapper_src = cli.registry_package_wrapper_init("0.15.0")
    assert 'os.path.basename(sys.argv[0]) == "minervit-methodology"' in wrapper_src
    assert 'os.environ["TAUTLINE_LEGACY_LAUNCHER_INVOKED"] = "minervit-methodology"' in wrapper_src

    pkg = tmp_path / "tautline"
    (pkg / "_dist" / "bin").mkdir(parents=True)
    (pkg / "__init__.py").write_text(wrapper_src, encoding="utf-8")
    probe = (
        'import os\n'
        'print("MARK=" + os.environ.get("TAUTLINE_LEGACY_LAUNCHER_INVOKED", "NONE"))\n'
    )
    (pkg / "_dist" / "bin" / "tautline").write_text(probe, encoding="utf-8")
    driver = (
        "import sys\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "sys.argv = ['minervit-methodology']\n"
        "import tautline\n"
        "tautline.main()\n"
    )
    res = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, timeout=60)
    assert "MARK=minervit-methodology" in res.stdout, res.stderr


# --- chokepoint 3: markers --------------------------------------------------------------------


def test_markers_lane_legacy_marker_warns(cli, tmp_path, capsys):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}")
    assert cli.find_adapter_root(tmp_path) == tmp_path
    err = capsys.readouterr().err
    assert ".minervit-ai-delivery.json" in err and "use .tautline.json" in err


def test_markers_canonical_marker_is_silent(cli, tmp_path, capsys):
    (tmp_path / ".tautline.json").write_text("{}")
    assert cli.find_adapter_root(tmp_path) == tmp_path
    assert capsys.readouterr().err == ""


def test_markers_source_adapter_legacy_warns(cli, tmp_path, capsys):
    legacy = tmp_path / ".minervit" / "adapter.json"
    legacy.parent.mkdir()
    legacy.write_text("{}")
    assert cli.repo_local_source_adapter_path(tmp_path) == legacy
    err = capsys.readouterr().err
    assert ".minervit/adapter.json" in err and "use .tautline/adapter.json" in err


def test_markers_user_config_legacy_warns(cli, tmp_path, monkeypatch, capsys):
    new = tmp_path / "tautline.env"
    legacy = tmp_path / "methodology.env"
    monkeypatch.setattr(cli, "USER_CONFIG_ENV", new)
    monkeypatch.setattr(cli, "LEGACY_USER_CONFIG_ENV", legacy)
    legacy.write_text("export X=1\n", encoding="utf-8")
    assert cli.resolve_user_config_env() == legacy
    err = capsys.readouterr().err
    assert str(legacy) in err and str(new) in err


# --- chokepoint 4: slug -----------------------------------------------------------------------


def test_slug_legacy_warns_naming_tautlines(cli, capsys):
    assert cli.adapter_is_methodology_repo({"repo": "minervit/minervit-ai-delivery-methodology"})
    err = capsys.readouterr().err
    assert "minervit/minervit-ai-delivery-methodology" in err
    assert "use tautlines/tautline-dev" in err


def test_slug_canonical_is_silent(cli, capsys):
    assert cli.adapter_is_methodology_repo({"repo": "tautlines/tautline-dev"})
    assert capsys.readouterr().err == ""


# --- shell -> python once-only handoff --------------------------------------------------------


def test_handoff_seed_silences_python(monkeypatch, capsys):
    token = "env:MINERVIT_GITHUB_RATE_GUARD"
    monkeypatch.setenv("TAUTLINE_SUNSET_SHELL_WARNED", token)
    monkeypatch.delenv("TAUTLINE_GITHUB_RATE_GUARD", raising=False)
    monkeypatch.setenv("MINERVIT_GITHUB_RATE_GUARD", "v")
    util.resolve_env("MINERVIT_GITHUB_RATE_GUARD")  # already shell-warned -> silent
    assert capsys.readouterr().err == ""
    assert "TAUTLINE_SUNSET_SHELL_WARNED" not in os.environ  # seeded then stripped


def test_handoff_pathological_name_round_trips():
    fam, legacy = "env", "MINERVIT_A,B:C %x\nD"
    token = urllib.parse.quote(fam, safe="") + ":" + urllib.parse.quote(legacy, safe="")
    joined = "env:MINERVIT_OTHER," + token
    pairs = util.parse_sunset_handoff(joined)
    assert (fam, legacy) in pairs
    assert ("env", "MINERVIT_OTHER") in pairs


def test_handoff_malformed_tokens_skipped():
    assert util.parse_sunset_handoff("no-sep,,env:MINERVIT_X") == [("env", "MINERVIT_X")]


# --- shell launcher warnings (chokepoint 1, shell side) ---------------------------------------


def _slice(content: str, start: str, end: str) -> str:
    i = content.index(start)
    j = content.index(end, i) + len(end)
    return content[i:j]


def _repo_warn_harness(cli) -> str:
    content = cli.claude_launcher_content(False)
    helpers = _slice(content, "_tl_sunset_suppressed() {", "export TAUTLINE_SUNSET_SHELL_WARNED\n}")
    repo = _slice(
        content,
        'MINERVIT_METHODOLOGY_REPO_PRESET="${TAUTLINE_METHODOLOGY_REPO',
        "'env:MINERVIT_METHODOLOGY_REPO'\nfi",
    )
    return "#!/bin/sh\nset -u\n" + helpers + "\n" + repo + "\nprintf 'DONE\\n'\n"


def _run_sh(script: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, timeout=30)


def test_launcher_content_reads_tautline_repo_first_and_warns(cli):
    content = cli.claude_launcher_content(False)
    assert "${TAUTLINE_METHODOLOGY_REPO:-${MINERVIT_METHODOLOGY_REPO:-}}" in content
    assert (
        "_tl_sunset_warn MINERVIT_METHODOLOGY_REPO TAUTLINE_METHODOLOGY_REPO "
        "'env:MINERVIT_METHODOLOGY_REPO'"
    ) in content
    # hook launcher variants must never carry the warning helper
    assert "_tl_sunset_warn" not in cli.git_branch_liveness_hook_content(Path("/x"), "pre-commit")


def test_launcher_repo_precedence_only_tautline_is_silent(cli):
    script = _repo_warn_harness(cli)
    env = {"PATH": "/usr/bin:/bin", "TAUTLINE_METHODOLOGY_REPO": "/x"}
    res = _run_sh(script, env)
    assert res.returncode == 0, res.stderr
    assert not _warn_lines(res.stderr)


def test_launcher_repo_precedence_only_legacy_warns_once(cli):
    script = _repo_warn_harness(cli)
    env = {"PATH": "/usr/bin:/bin", "MINERVIT_METHODOLOGY_REPO": "/x"}
    res = _run_sh(script, env)
    assert res.returncode == 0, res.stderr
    lines = _warn_lines(res.stderr)
    assert lines == [
        "deprecation_warning: MINERVIT_METHODOLOGY_REPO is deprecated and will be "
        "removed in 1.0; use TAUTLINE_METHODOLOGY_REPO"
    ]


def test_launcher_repo_precedence_neither_is_silent(cli):
    script = _repo_warn_harness(cli)
    res = _run_sh(script, {"PATH": "/usr/bin:/bin"})
    assert res.returncode == 0, res.stderr
    assert not _warn_lines(res.stderr)


def test_launcher_shell_suppression_silences(cli):
    script = _repo_warn_harness(cli)
    env = {
        "PATH": "/usr/bin:/bin",
        "MINERVIT_METHODOLOGY_REPO": "/x",
        "MINERVIT_SUPPRESS_SUNSET_WARNINGS": "1",
    }
    res = _run_sh(script, env)
    assert res.returncode == 0, res.stderr
    assert not _warn_lines(res.stderr)


def test_launcher_shell_exports_handoff_token(cli):
    # The shell echo also records the surface in TAUTLINE_SUNSET_SHELL_WARNED so python never
    # re-warns it; assert the harness exports the collision-safe token.
    script = _repo_warn_harness(cli).replace(
        "printf 'DONE\\n'", 'printf "HANDOFF=%s\\n" "${TAUTLINE_SUNSET_SHELL_WARNED:-}"'
    )
    env = {"PATH": "/usr/bin:/bin", "MINERVIT_METHODOLOGY_REPO": "/x"}
    res = _run_sh(script, env)
    assert "HANDOFF=env:MINERVIT_METHODOLOGY_REPO" in res.stdout, res.stdout


# --- shell inventory: EVERY hand-wired _tl_sunset_warn surface, parameterized (not sampled) -----
# The 10 legacy MINERVIT_ knobs the interactive launcher resolves TAUTLINE_-first (REPO is wired at
# two call sites -- pre-source + post-source -- so 11 calls, 10 distinct knobs). Derived by reading
# the launcher blocks in bin/tautline; guarded for completeness so a new/dropped surface fails CI.
_SHELL_SUNSET_SURFACES = [
    "METHODOLOGY_REPO",
    "METHODOLOGY_SNAPSHOT_STORE",
    "METHODOLOGY_DISABLE_SNAPSHOT_EXEC",
    "METHODOLOGY_CLI",
    "METHODOLOGY_UPDATE_POLICY",
    "METHODOLOGY_DISABLE_AUTO_RESCUE",
    "METHODOLOGY_RESCUE_STATE_DIR",
    "SHOW_GOAL_PROMPT",
    "CLAUDE_AUTOCOMPACT_PCT",
    "NO_REPAIR_SESSION",
]


def test_shell_sunset_inventory_is_complete(cli):
    # Not a 1-of-N sample: every _tl_sunset_warn call in the rendered launcher must name one of the
    # known 10 legacy knobs, and each known knob must appear. Add an 11th surface (or drop one)
    # without updating _SHELL_SUNSET_SURFACES and this fails.
    content = cli.claude_launcher_content(False)
    found = set(re.findall(r"_tl_sunset_warn MINERVIT_(\S+) TAUTLINE_", content))
    assert found == set(_SHELL_SUNSET_SURFACES)
    # hook launcher variants must never carry any warning wiring
    assert "_tl_sunset_warn" not in cli.git_branch_liveness_hook_content(Path("/x"), "pre-commit")


@pytest.mark.parametrize("sfx", _SHELL_SUNSET_SURFACES)
def test_shell_sunset_surface_reads_tautline_first_and_warns(cli, sfx):
    content = cli.claude_launcher_content(False)
    # (a) a TAUTLINE_-first read of this knob exists
    assert f"${{TAUTLINE_{sfx}:-}}" in content
    # (a') the warn only fires when the legacy spelling is the only one set
    assert f'[ -n "${{MINERVIT_{sfx}:-}}" ]' in content
    # (b) the exact once-only warn call: legacy env, tautline replacement, handoff token
    assert f"_tl_sunset_warn MINERVIT_{sfx} TAUTLINE_{sfx} 'env:MINERVIT_{sfx}'" in content


# --- R3 amendment (b): fresh-install-silent ---------------------------------------------------


def test_fresh_install_config_never_warns_on_itself(run_cli, tmp_path):
    res = run_cli("install-cli")
    assert res.returncode == 0, res.stderr
    config = tmp_path / "home" / ".config" / "tautline" / "tautline.env"
    text = config.read_text(encoding="utf-8")
    # The update-policy/pins knobs now carry their TAUTLINE_ twin, so a fresh config resolves the
    # alias first and never trips its own MINERVIT_ sunset warning.
    assert "export TAUTLINE_METHODOLOGY_UPDATE_POLICY=" in text
    assert "export MINERVIT_METHODOLOGY_UPDATE_POLICY=" in text
    # Sourcing the fresh config and running the CLI emits no sunset warning.
    home = tmp_path / "home"
    script = f'. {config} && "{CLI_PATH}" version --no-remote'
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    res2 = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert res2.returncode == 0, res2.stderr
    assert not _warn_lines(res2.stderr), res2.stderr
