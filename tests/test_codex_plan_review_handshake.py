"""Item 77 WS2: `codex-plan-review` refuses a direct launch, because a direct launch records
nothing.

The wrapper writes no log, no run meta and no manifest. Run directly it looks exactly like a
review -- Codex starts, findings scroll past, the lane reads them -- and then there is no
evidence, so the round cannot be finalized and does not count. The cost is a full Codex round
spent on something that can never be bound, discovered only when someone tries to finalize it.

So the launcher and the wrapper shake hands: `run-plan-review` sets an env marker, and the
wrapper refuses without it. `--standalone` is the deliberate escape for an unrecorded advisory
read, and it says so at the end of every run rather than letting the lane forget which mode it
chose.

The refusal sits AFTER plan validation and BEFORE the prompt and command are built, so a
refused launch spends zero Codex.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
HANDSHAKE = "MINERVIT_PLAN_REVIEW_LAUNCHER"


def _plan(tmp_path: Path) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\nSome plan body for the wrapper to bind.\n", encoding="utf-8")
    return plan


def _run(tmp_path: Path, *extra: str, env_extra: dict | None = None):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    marker = tmp_path / "codex-was-spawned"
    fake = fake_bin / "codex"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'spawned\\n' > {marker}\n"
        "printf '## Findings\\nNo Critical or P1 findings.\\n'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
    }
    for spelling in (HANDSHAKE, "TAUTLINE_PLAN_REVIEW_LAUNCHER"):
        env.pop(spelling, None)
    env.update(env_extra or {})
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "codex-plan-review", "--target", str(tmp_path),
         "--plan", str(_plan(tmp_path)), *extra],
        env=env, text=True, capture_output=True, timeout=120,
    )
    return result, marker


# --- 1. the refusal ------------------------------------------------------------------------------


def test_a_direct_launch_is_refused(tmp_path):
    result, marker = _run(tmp_path)
    assert result.returncode == 2
    assert "codex_plan_review_error: refusing a direct launch" in result.stderr


def test_the_refusal_spends_no_codex_round(tmp_path):
    """The whole point: refusing AFTER the round has been spent would be worse than not
    refusing at all."""
    _, marker = _run(tmp_path)
    assert not marker.exists(), "the reviewer must not be spawned on a refused launch"


def test_the_refusal_names_both_ways_forward(tmp_path):
    """One records and counts, one is deliberately unrecorded. A refusal that named neither
    would just look like the tool being broken."""
    result, _ = _run(tmp_path)
    assert "run-plan-review" in result.stderr
    assert "--standalone" in result.stderr
    assert "--plan <source-of-truth-plan>" in result.stderr


def test_the_refusal_explains_why_rather_than_just_refusing(tmp_path):
    result, _ = _run(tmp_path)
    assert "records NO evidence" in result.stderr
    assert "can never be finalized" in result.stderr


def test_the_refusal_hands_nothing_to_a_human(tmp_path):
    result, _ = _run(tmp_path)
    lowered = result.stderr.lower()
    for phrase in ("escalate", "ask the operator", "ask a human", "wait for the operator"):
        assert phrase not in lowered, phrase


# --- 2. the handshake, in both spellings ---------------------------------------------------------


def test_the_handshake_admits_the_launched_path(tmp_path):
    result, marker = _run(tmp_path, env_extra={HANDSHAKE: "run-plan-review"})
    assert "refusing a direct launch" not in result.stderr
    assert marker.exists(), "the launched path must actually run the reviewer"


def test_the_tautline_spelling_is_accepted_too(tmp_path):
    """The rebrand alias, treated the same way every other env alias is."""
    result, marker = _run(tmp_path, env_extra={"TAUTLINE_PLAN_REVIEW_LAUNCHER": "run-plan-review"})
    assert "refusing a direct launch" not in result.stderr
    assert marker.exists()


def test_the_launched_path_prints_no_standalone_notice(tmp_path):
    """The confession belongs to standalone runs only -- a recorded round has evidence."""
    result, _ = _run(tmp_path, env_extra={HANDSHAKE: "run-plan-review"})
    assert "codex_plan_review_notice:" not in result.stderr


# --- 3. standalone runs, and confesses -----------------------------------------------------------


def test_standalone_runs_the_review(tmp_path):
    result, marker = _run(tmp_path, "--standalone")
    assert "refusing a direct launch" not in result.stderr
    assert marker.exists()


def test_standalone_confesses_that_it_recorded_nothing(tmp_path):
    """An advisory read is legitimate; forgetting it was advisory is what is not. The notice
    lands at the END of the run, where the lane is deciding what the output means."""
    result, _ = _run(tmp_path, "--standalone")
    assert "codex_plan_review_notice:" in result.stderr
    assert "recorded no evidence" in result.stderr
    assert "it is not a plan-review round" in result.stderr
    assert "run-plan-review" in result.stderr


# --- 4. the sender ------------------------------------------------------------------------------


def test_run_plan_review_sends_the_handshake(cli):
    """Pinned at the source: the launcher sets the marker on the env it spawns the wrapper
    with. Without this line the refusal above would lock out the recorded path too."""
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    assert "codex_env[PLAN_REVIEW_LAUNCHER_HANDSHAKE_ENV]" in source


def test_the_receiver_runs_before_the_prompt_is_built(cli):
    """Ordering is the design: refuse before the prompt and command exist, so a refused launch
    costs nothing and the launched path reaches the prompt text unchanged."""
    import inspect

    source = inspect.getsource(cli.codex_plan_review_command)
    refusal = source.index("refusing a direct launch")
    assert source.index("plan missing") < refusal, "plan validation runs first"
    assert refusal < source.index("plan_review_text("), "the refusal precedes the prompt build"


def test_the_handshake_is_dual_written_so_the_log_stays_clean(cli):
    """Codex R4 P2. The receiver reads via resolve_env, which prefers the TAUTLINE_ alias and
    warns when it falls back. Setting only the MINERVIT_ name would put a deprecation warning
    into every builtin run's captured log -- the artifact that is then classified as evidence.
    """
    import inspect

    source = inspect.getsource(cli.run_plan_review)
    assert "brand_env_pairs(codex_env)" in source
    handshake = source.index("codex_env[PLAN_REVIEW_LAUNCHER_HANDSHAKE_ENV]")
    assert source.index("brand_env_pairs(codex_env)") > handshake, (
        "the mirror must run AFTER the marker is set, or it copies nothing"
    )


def test_the_dual_write_uses_the_house_helper_not_a_second_copy(cli):
    """brand_env_pairs exists for exactly this and overwrites rather than setdefault, so an
    inherited divergent alias cannot make two consumers in one process tree disagree."""
    env = cli.brand_env_pairs({"MINERVIT_PLAN_REVIEW_LAUNCHER": "run-plan-review"})
    assert env["TAUTLINE_PLAN_REVIEW_LAUNCHER"] == "run-plan-review"
