import json
import subprocess          # `_write_ledger` shells out to git for the base sha
from pathlib import Path

from _adapter_fixtures import EXAMPLE_ADAPTER, write_trusted_adapter as _write_trusted_adapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"




def _adapter(lane, builder, reviewer, enforcement=None):
    """Overlay on `example-saas`. `review-run` and `guard-check` resolve through
    `load_project()`, which requires the full adapter shape, so a partial dict fails at adapter
    loading before these tests reach the inversion they exist to prove."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    if enforcement:
        data["review"]["crossModel"] = {"enforcement": enforcement}
    data.update({
        "agents": {
            "acme-bot": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md",
                         "reviewWrapper": str(FIXTURES / "clean")},
            "globex-bot": {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "G.md",
                           "reviewWrapper": str(FIXTURES / "clean")},
            "acme-two": {"vendor": "acme", "runtime": "acme-cloud", "instructionFile": "A2.md",
                         "reviewWrapper": str(FIXTURES / "clean")},
        },
        "roles": {"builder": builder, "implementationReviewer": reviewer},
    })
    written = _write_trusted_adapter(lane, data)
    _adapter_path[:] = [written]
    return written



def _seam(run_cli, lane, path, reviewer_fixture="clean"):
    """`review-run` the way the CLI actually requires it.

    The wrapper command after `--`, because the verb refuses without one and records evidence
    only when the command MATCHES the bound reviewer's wrapper; and `--risk-tier T1`, because
    `implementation_stage1_required_for_risk_tier` fails closed for every other tier and the
    seam would refuse for want of a Stage 1 sweep before reaching the identity gate under test.
    Both were learned by running the seam, not by reading it.
    """
    return run_cli("review-run", "--project", str(path), "--target", str(lane),
                   "--risk-tier", "T1",
                   "--", str(FIXTURES / reviewer_fixture), cwd=lane)


_adapter_path: list = []


def _write_ledger(lane, *, reviewer, verdict="clean"):
    """A tracked implementation-review ledger on disk, as `finalize-implementation-review`
    writes one. Used to drive the ledger gate directly without running a full review cycle."""
    # DERIVED, never hardcoded. The ledger lives under the adapter's configured
    # `planningArtifacts.sourceOfTruth`, which this overlay puts under the example-saas root --
    # not `docs/superpowers/plans/`. A hardcoded path writes a file the gate never reads, and
    # the test then fails on "ledger missing" while looking like an identity failure.
    from tautline_methodology import cli as _cli

    ledger_dir = _cli.implementation_review_ledger_dir(_cli.load_project(_adapter_path[0]), lane)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    state = subprocess.run(["git", "rev-parse", "HEAD"], cwd=lane,
                           capture_output=True, text=True, check=True).stdout.strip()
    ledger = {
        "schema": "minervit-implementation-review-ledger/v1",
        "recorded_by": "tautline finalize-implementation-review",
        "branch": "feature",
        "base_sha": state,
        "diff_sha256": "0" * 64,
        "reviewer": reviewer,
        "verdict": verdict,
        "unresolved_critical_count": 0,
        "unresolved_p1_count": 0,
        "source_manifest_path": "",
    }
    path = ledger_dir / "feature.json"
    path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    # COMMIT it, or the docstring above is a lie and every caller drives the wrong gate: the
    # ledger check refuses an untracked or dirty ledger before it ever compares the reviewer
    # field, so a negative test would pass on the untracked error while believing it proved an
    # identity mismatch. Ledger JSONs are excluded from the reviewed diff, so this is free.
    subprocess.run(["git", "add", str(path)], cwd=lane, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "review: ledger fixture"], cwd=lane,
                   check=True, capture_output=True)
    return path


def test_run_command_reports_a_missing_binary_as_127(cli):
    """The unit-level twin, so the contract is pinned where every other caller reads it: a
    missing binary is an exit code, not an exception. 127 is the shell's own convention, so
    callers that already branch on non-zero need no new vocabulary."""
    code, stdout, stderr = cli.run_command(["definitely-not-a-real-binary-9f3c", "--version"])
    assert code == 127
    assert stdout == ""
    assert "definitely-not-a-real-binary-9f3c" in stderr
