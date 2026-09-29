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


def test_the_refusal_spends_no_codex_round(tmp_path):
    """The whole point: refusing AFTER the round has been spent would be worse than not
    refusing at all."""
    _, marker = _run(tmp_path)
    assert not marker.exists(), "the reviewer must not be spawned on a refused launch"


def test_the_refusal_hands_nothing_to_a_human(tmp_path):
    result, _ = _run(tmp_path)
    lowered = result.stderr.lower()
    for phrase in ("escalate", "ask the operator", "ask a human", "wait for the operator"):
        assert phrase not in lowered, phrase


# --- 2. the handshake, in both spellings ---------------------------------------------------------


def test_the_launched_path_prints_no_standalone_notice(tmp_path):
    """The confession belongs to standalone runs only -- a recorded round has evidence."""
    result, _ = _run(tmp_path, env_extra={HANDSHAKE: "run-plan-review"})
    assert "codex_plan_review_notice:" not in result.stderr


# --- 3. standalone runs, and confesses -----------------------------------------------------------


# --- 4. the sender ------------------------------------------------------------------------------
