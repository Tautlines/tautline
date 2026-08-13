"""A review of nothing is refused before it can be recorded, ledgered, or charged.

RCA `2026-07-28-empty-diff-review-recorded-clean`: a Stage 2 manifest whose subject was zero bytes
-- `head_sha == base_sha`, `diff_bytes: 0`, `diff_sha256` the empty-string digest -- was finalized
clean, written to the ledger, and counted against the round budget. Every downstream gate then
read a green review that had reviewed nothing. The manifest matched the current state for the same
reason it was void: both sides were empty, so the equality check that is supposed to bind evidence
to a subject passed on the absence of one.

The refusal is spelled once, in `implementation_review_subject_errors`, and wired at the doors that
can record or spend. Each void marker refuses INDEPENDENTLY: a forged manifest that simply omits
`diff_bytes` must not slip past, and `head_sha == base_sha` catches the case before any diff is
hashed.
"""
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _classified_findings_fixtures import finalize, lane

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


def void_lane(cli, tmp_path, **overrides):
    """A lane whose manifest AND state carry the void triple -- the incident replay.

    Both sides are voided together on purpose. That is what made the original incident invisible:
    a void manifest matched a void state, so `diff_sha256 does not match` never fired.
    """
    subject = lane(cli, tmp_path)
    void = {
        "head_sha": "same" * 10,
        "base_sha": "same" * 10,
        "diff_sha256": EMPTY_DIGEST,
        "diff_bytes": 0,
    }
    void.update(overrides)
    subject.state.update(void)
    manifest = subject.manifest()
    manifest.update(void)
    subject.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return subject


# --- 1. the predicate: each void marker refuses on its own ---------------------------------------


def test_head_equal_to_base_refuses(cli) -> None:
    assert cli.implementation_review_subject_errors(
        {"head_sha": "abc", "base_sha": "abc", "diff_sha256": "real", "diff_bytes": 4096}
    )


def test_zero_diff_bytes_refuses(cli) -> None:
    assert cli.implementation_review_subject_errors(
        {"head_sha": "abc", "base_sha": "def", "diff_sha256": "real", "diff_bytes": 0}
    )


def test_the_empty_string_digest_refuses_even_with_diff_bytes_absent(cli) -> None:
    """The forged-manifest case. Omitting `diff_bytes` must not buy a pass, and `head != base`
    must not either -- a hand-written manifest can claim any two shas it likes."""
    assert cli.implementation_review_subject_errors(
        {"head_sha": "abc", "base_sha": "def", "diff_sha256": EMPTY_DIGEST}
    )


def test_a_real_subject_is_accepted(cli) -> None:
    assert (
        cli.implementation_review_subject_errors(
            {"head_sha": "abc", "base_sha": "def", "diff_sha256": "real", "diff_bytes": 4096}
        )
        == []
    )


def test_an_unknown_subject_is_not_a_void_subject(cli) -> None:
    """Absence of evidence is not evidence of voidness. A record with no shas at all is a state
    the caller could not derive -- it must fall through to today's behavior, not mint a refusal."""
    assert cli.implementation_review_subject_errors({}) == []
    assert cli.implementation_review_subject_errors({"head_sha": "", "base_sha": ""}) == []


def test_the_empty_digest_constant_is_the_digest_of_nothing(cli) -> None:
    """Named so the incident's signature is greppable; before this constant existed the
    empty-string digest appeared nowhere in the repo, which is HOW a void review finalized clean."""
    assert cli.EMPTY_DIFF_SHA256 == EMPTY_DIGEST


# --- 2. door 1: manifest validation ---------------------------------------------------------------


def test_a_void_manifest_against_a_void_state_is_refused(cli, tmp_path) -> None:
    """The incident replay. Without the subject check these two match each other exactly."""
    subject = void_lane(cli, tmp_path)

    errors = subject.manifest_errors(cli, require_classification=False)

    assert any("no subject" in error for error in errors), errors
    assert not any("diff_sha256 does not match" in error for error in errors), (
        "the equality check passed BECAUSE both sides were void -- that is the defect, "
        "so it must not be what refuses this manifest"
    )


def test_the_refusal_names_a_likely_cause_and_a_runnable_continuation(cli, tmp_path) -> None:
    subject = void_lane(cli, tmp_path)

    joined = " ".join(subject.manifest_errors(cli, require_classification=False))

    assert "git switch -c" in joined and "git commit" in joined
    assert "no ledger is written" in joined.lower()


# --- 3. door 2: finalization refuses and mutates NOTHING ------------------------------------------


def test_a_refused_finalization_leaves_the_world_unchanged(cli, monkeypatch, tmp_path) -> None:
    """Budget follows for free: rounds are counted from recorded manifests, and a refusal that
    writes nothing adds none. That property only holds while every write sits after validation."""
    subject = void_lane(cli, tmp_path)
    before = subject.manifest_path.read_bytes()

    rc = finalize(cli, monkeypatch, subject, verdict="clean")

    assert rc == 1
    assert subject.manifest_path.read_bytes() == before, (
        "a refused finalization rewrote the manifest"
    )
    assert not subject.ledger_path(cli).exists(), "a refused finalization wrote a ledger"


def test_a_real_subject_still_finalizes_clean(cli, monkeypatch, tmp_path, capsys) -> None:
    """The happy-path regression guard: the new door refuses voidness, not review."""
    subject = lane(cli, tmp_path)

    rc = finalize(cli, monkeypatch, subject, verdict="clean")

    assert rc == 0, capsys.readouterr().err
    assert subject.ledger_path(cli).exists()


# --- 4. door 3: codex-run refuses BEFORE the wrapper runs -----------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def void_review_repo(tmp_path):
    """A real repo whose review subject is empty: HEAD is the base.

    The wrapper touches a marker, so "the wrapper never ran" is an assertion about the filesystem
    rather than about stdout -- a refusal that still executed the wrapper has already spent the
    round it claims to have saved.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    rendered = subprocess.run(
        [sys.executable, str(CLI_PATH), "render-adapters",
         "--project", str(EXAMPLE_ADAPTER), "--target", str(repo), "--write"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "lane@example.test")
    _git(repo, "config", "user.name", "Lane")
    _git(repo, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")

    marker = repo / "wrapper-ran.marker"
    wrapper = repo / "scripts" / "codex-review.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    wrapper.chmod(0o755)
    (repo / ".gitignore").write_text(".ai-work/\n.ai-runs/\n.impl-reviews/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    # HEAD is now `main`, and `main` is the review base -- so the resolved scope is zero bytes.
    return repo, marker, env


def test_codex_run_refuses_a_void_subject_before_invoking_the_wrapper(void_review_repo) -> None:
    repo, marker, env = void_review_repo

    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "codex-run", "--target", str(repo),
         "--risk-tier", "T1", "--review-round", "R1", "--", "./scripts/codex-review.sh"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "codex_run_error:" in result.stderr
    assert "no subject" in result.stderr
    assert "git switch -c" in result.stderr, "a refusal with no runnable continuation is a dead end"
    assert not marker.exists(), "the wrapper ran despite the refusal; the round is already spent"


def test_a_void_run_records_no_manifest_and_therefore_spends_no_round(void_review_repo) -> None:
    """Refusals are round-free because the counter derives from RECORDED manifests. This asserts
    the mechanism, not the intent: nothing landed in the evidence directory."""
    repo, _marker, env = void_review_repo

    subprocess.run(
        [sys.executable, str(CLI_PATH), "codex-run", "--target", str(repo),
         "--risk-tier", "T1", "--review-round", "R1", "--", "./scripts/codex-review.sh"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120,
    )

    evidence = repo / ".ai-runs" / "review-evidence"
    manifests = sorted(evidence.glob("*.json")) if evidence.is_dir() else []
    assert manifests == [], f"a refused run left evidence behind: {manifests}"


# --- 5. door 4: the WRITER, the only site that actually records ----------------------------------


def test_the_evidence_writer_refuses_a_void_subject_it_derived_itself(
    cli, monkeypatch, tmp_path
) -> None:
    """Codex R2 P2. `codex-run` checks the subject BEFORE the wrapper; this function recomputes
    state AFTER it and writes the manifest from THAT. A wrapper that moves HEAD -- or any
    concurrent checkout -- passes the pre-flight and still records a void manifest. The guarantee
    is that a review with no subject cannot be RECORDED, and only a check on the recorded state
    makes that true."""
    target = tmp_path / "lane"
    target.mkdir()
    void_state = {
        "branch": "feat/void",
        "head_sha": "same" * 10,
        "base_sha": "same" * 10,
        "base_ref": "origin/experimental",
        "diff_sha256": EMPTY_DIGEST,
        "diff_bytes": 0,
    }
    monkeypatch.setattr(cli, "implementation_review_state", lambda t, base=None: (void_state, []))
    data = {"review": {"codexWrapper": "./scripts/codex-review.sh", "prePushReviewEvidence": True}}

    written = cli.write_implementation_review_evidence(
        data, target, ["./scripts/codex-review.sh"], tmp_path / "review.log", 0,
        "2026-08-11T00:00:00+00:00", "2026-08-11T00:00:01+00:00", "", tmp_path / "sweep.json",
        risk_tier="T1",
    )

    assert written is None, "a void subject was recorded as a Stage 2 manifest"
    evidence = cli.implementation_review_evidence_dir(target)
    assert not evidence.is_dir() or list(evidence.glob("*.json")) == []


def test_every_site_that_records_review_evidence_uses_the_one_predicate(cli) -> None:
    """The class, not the member. Sites that CREATE review evidence must all refuse a void subject
    through the same predicate; a hand-rolled subset at any one of them is how they disagree about
    what "no subject" means. `record_stage1_sweep` had exactly such a subset -- it refused zero
    diff bytes but not `head_sha == base_sha` and not the empty digest -- and a sweep artifact is
    what unlocks a Stage 2 round, so a sweep over nothing bought a review of nothing.

    `review_evidence_check` is the ONE deliberate exemption and is asserted to stay exempt: an
    empty OUTGOING diff at push time legitimately owes no evidence. The defect is recording a
    review of the emptiness, never the emptiness itself."""
    for recorder in (cli.write_implementation_review_evidence, cli.record_stage1_sweep,
                     cli.implementation_review_manifest_errors):
        source = inspect.getsource(recorder)
        assert "implementation_review_subject_errors" in source, recorder.__name__

    exempt = inspect.getsource(cli.review_evidence_check)
    assert "implementation_review_subject_errors" not in exempt
    assert "diff_bytes" in exempt, "the deliberate early-pass must still be there to be exempt"


# --- 6. no refusal on this surface hands the decision to a human ----------------------------------


def test_no_refusal_on_this_surface_tells_an_agent_to_consult_a_human(cli, tmp_path) -> None:
    """Same phrase list as the round ladder's own guard. "escalate" is the word that cost 30
    hours of lane time; "operator" alone is NOT forbidden -- these refusals deliberately say
    the opposite instruction."""
    forbidden = ("escalate", "ask the operator", "consult the operator", "ask the human")
    surfaces = [
        cli.implementation_review_subject_errors({"head_sha": "a", "base_sha": "a"}),
        void_lane(cli, tmp_path).manifest_errors(cli, require_classification=False),
    ]

    for errors in surfaces:
        joined = " ".join(errors).lower()
        for phrase in forbidden:
            assert phrase not in joined, f"{phrase!r} in: {joined}"
