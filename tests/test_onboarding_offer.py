"""Guided-onboarding classifier + renderer + sentinel-split contract (roadmap #14, PR 1).

These are byte-identity-critical tests: the unmanaged no-adapter output must stay byte-for-byte
identical to the pre-split constant, and every evidence state must carry the state-correct
recovery command behind the stable NO_ADAPTER_SENTINEL prefix. The classifier must stay
shell-free (the SessionStart hook calls it under total containment).
"""

import subprocess
from pathlib import Path


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


# ---------------------------------------------------------------------------
# renderer: exact offer lines per state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# renderer: cwd-relative rendering rule (absolute for unrelated cwd)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# renderer purity: same dict in -> same lines out, no process reads
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# every emitted line passes the guard scanner
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sentinel split: byte-identity + boundaries
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PR-1 deferred fix: the unmanaged recovery command renders the REQUESTED target relative to the
# invocation cwd (not a hard-coded `.`), so a gate verb run with --target <repo> from an unrelated
# cwd recovers <repo>, never the cwd. target==cwd stays `.` (byte-identity is preserved above).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# full composed kickoff output passes the guard scanner (declarative offer)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# shell-safety: paths with spaces / metacharacters are quoted in emitted COMMANDS
# ---------------------------------------------------------------------------
def _command_after_flag(text, flag):
    """shlex-parse `text` and return the token following `flag` (as the shell would see it)."""
    import shlex

    tokens = shlex.split(text)
    return tokens[tokens.index(flag) + 1]
