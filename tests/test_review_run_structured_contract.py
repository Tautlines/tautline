import json
import subprocess
from pathlib import Path

import pytest
from _adapter_fixtures import EXAMPLE_ADAPTER, write_trusted_adapter as _write_trusted_adapter


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"


@pytest.fixture
def lane(tmp_path):
    """A real git repo with one commit on a feature branch, so the review seam has a subject."""
    repo = tmp_path / "lane"
    repo.mkdir()
    def run(*a):
        # A def, not a lambda: ruff E731 is enabled here. This is the SECOND lane fixture
        # in the plan with the same lambda, so it is a systematic plan defect rather than
        # a slip -- both were caught by running lint, neither by reading the plan.
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)

    run("init", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "src.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("checkout", "-b", "feature")
    (repo / "src.py").write_text("x = 2\n")
    run("add", "-A")
    run("commit", "-m", "change")
    # THE REMOTE IS NOT DECORATION. `lane_project()` validates that the adapter's `repo` matches
    # the target's git remote and refuses with "Project adapter repo does not match the target git
    # remote" otherwise. The overlay here is `example-saas`, whose `repo` is
    # `example-org/example-saas`, so a lane without a matching `origin` exits during repo
    # validation -- before the structured-result seam these tests exist to exercise.
    run("remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    return repo




def _adapter(lane, fixture, agent_id="codex", marker=None):
    """Overlay on `example-saas`, never an ad-hoc dict.

    `codex-run` resolves its project through `lane_project()`, which rejects an untrusted
    source-adapter path, and then `load_project()`, which requires the full adapter shape. A
    hand-written dict carrying six keys fails there, BEFORE the structured-result seam these
    tests exist to exercise, so the tests would go red for a reason that has nothing to do with
    what they assert. Start from the real adapter and overlay only what the test varies.

    THE REVIEWER'S AGENT ID IS `codex` IN R2, deliberately. R2 keeps the manifest's `reviewer`
    field at the literal `codex` -- that is the whole point of the release, landing the output
    contract while the identity gate is untouched. Binding the role to a differently-named agent
    here would have the seam accept a structured result from one id and then write durable
    evidence claiming another reviewed it, weakening the very integrity anchor R2 is adding.
    R3's tests are where non-Codex reviewer ids appear, because R3 is where the manifest writer
    starts recording them.

    THE BUILDER IS A SECOND AGENT OF A DIFFERENT VENDOR, also deliberately. Binding one agent to
    both seams would make every test in this file start failing the moment R3 lands, because
    R3's default `block` enforcement refuses a same-vendor builder/reviewer pair -- and it would
    fail BEFORE reaching the result-parsing path these tests exercise. A structured-contract test
    must not be hostage to a gate from a later release.
    """
    record = {
        "vendor": "openai", "runtime": "codex", "instructionFile": "AGENTS.md",
        "reviewWrapper": str(FIXTURES / fixture),
    }
    if marker:
        record["transcriptMarker"] = marker
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["agents"] = {
        agent_id: record,
        "globex-builder": {"vendor": "globex", "runtime": "globex-tty",
                           "instructionFile": "GLOBEX.md"},
    }
    data["roles"] = {"builder": "globex-builder", "implementationReviewer": agent_id}
    data["review"]["codexWrapper"] = str(FIXTURES / fixture)
    return _write_trusted_adapter(lane, data)


def _manifests(lane):
    return sorted((lane / ".ai-runs" / "review-evidence").glob("*.json"))


def _seam(run_cli, lane, path, fixture):
    """Drive `codex-run` the way the CLI actually requires: the wrapper command after `--`.

    `codex-run` exits at argument validation when no command follows `--`, and it records
    evidence only when the command it was given MATCHES `review.codexWrapper` -- configuring the
    adapter does not launch anything by itself. Calling it without the command makes every test
    below fail before the structured-result path is reached, so the failure would look like a
    contract bug rather than a harness bug. Routing all of them through one helper also means the
    command and the adapter's wrapper cannot drift apart, since both derive from `fixture`.
    """
    # `--risk-tier T1` is not a bypass: `implementation_stage1_required_for_risk_tier` says only
    # an explicit T1 review skips Stage 1 sweep evidence, and it fails closed for everything else.
    # Without it the seam refuses with "requires --native-review-note before --" and every test
    # here dies at argument validation instead of exercising the contract -- the same shape as
    # omitting the wrapper command, one flag over.
    return run_cli("codex-run", "--project", str(path), "--target", str(lane),
                   "--risk-tier", "T1",
                   "--", str(FIXTURES / fixture), cwd=lane)


def test_malformed_output_refuses_and_does_not_crash(run_cli, lane):
    path = _adapter(lane, "malformed-output")
    result = _seam(run_cli, lane, path, "malformed-output")
    assert "Traceback" not in result.stderr
    assert _manifests(lane) == []


# `test_reviewer_and_recorded_by_are_unchanged_in_r2` lived here until R3.3. It pinned R2's
# promise that the contract lands WITHOUT inverting identity -- the ordering the whole program
# depends on, since inverting first would let a non-Codex reviewer's findings parse as
# `unlocatable` and the cross-check skip silently. R3.3 is the release allowed to change those
# fields, so the guard was deleted in the same commit that changes them rather than weakened.
# It failed first, which is how I know it was still doing its job.
