"""RCA cluster E: stop spending Codex rounds after two finalized clean rounds (O1)."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a shim.
CLI = ROOT / "src" / "tautline_methodology" / "cli.py"
CANONICAL = ROOT / "methodology" / "canonical-rules.md"
REVIEW_BEFORE_PUSH_SKILL = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "review-before-push"
    / "SKILL.md"
)


def _write_manifest(cli, target, branch, *, idx, verdict, uc, up, diff_sha256="diff-current"):
    evidence = cli.implementation_review_evidence_dir(target)
    evidence.mkdir(parents=True, exist_ok=True)
    slug = cli.slugify(branch, "branch")
    path = evidence / f"2026010{idx}T000000Z-{slug}-{cli.IMPLEMENTATION_REVIEW_STAGE}.json"
    path.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
                "verdict": verdict,
                "classification_status": verdict,
                "unresolved_critical_count": uc,
                "unresolved_p1_count": up,
                "diff_sha256": diff_sha256,
            }
        ),
        encoding="utf-8",
    )


def test_no_clean_rounds_when_dir_absent(cli, tmp_path):
    assert cli.finalized_clean_implementation_rounds(tmp_path, "feature/x") == 0


def test_counts_only_clean_zero_unresolved_rounds(cli, tmp_path):
    _write_manifest(cli, tmp_path, "feature/x", idx=1, verdict="clean", uc=0, up=0)
    _write_manifest(cli, tmp_path, "feature/x", idx=2, verdict="clean-with-deferrals", uc=0, up=0)
    # a round with unresolved findings does not count toward the clean cap
    _write_manifest(cli, tmp_path, "feature/x", idx=3, verdict="clean", uc=1, up=0)
    # a blocked round does not count
    _write_manifest(cli, tmp_path, "feature/x", idx=4, verdict="blocked", uc=0, up=0)
    assert cli.finalized_clean_implementation_rounds(tmp_path, "feature/x") == 2


def test_branch_scoped(cli, tmp_path):
    _write_manifest(cli, tmp_path, "feature/x", idx=1, verdict="clean", uc=0, up=0)
    _write_manifest(cli, tmp_path, "feature/y", idx=2, verdict="clean", uc=0, up=0)
    assert cli.finalized_clean_implementation_rounds(tmp_path, "feature/x") == 1


def test_diff_scoped_clean_round_budget(cli, tmp_path):
    _write_manifest(cli, tmp_path, "main", idx=1, verdict="clean", uc=0, up=0, diff_sha256="old-a")
    _write_manifest(cli, tmp_path, "main", idx=2, verdict="clean", uc=0, up=0, diff_sha256="old-b")
    _write_manifest(cli, tmp_path, "main", idx=3, verdict="clean", uc=0, up=0, diff_sha256="current")

    assert cli.finalized_clean_implementation_rounds(tmp_path, "main") == 3
    assert cli.finalized_clean_implementation_rounds(tmp_path, "main", "current") == 1


def test_origin_bases_constant(cli):
    assert "origin/main" in cli.IMPLEMENTATION_REVIEW_ORIGIN_BASES
    assert "main" not in cli.IMPLEMENTATION_REVIEW_ORIGIN_BASES


def test_review_budget_cli_and_policy_contracts_remain_pinned():
    cli_source = CLI.read_text(encoding="utf-8")
    canonical = CANONICAL.read_text(encoding="utf-8")
    review_before_push_skill = REVIEW_BEFORE_PUSH_SKILL.read_text(encoding="utf-8")

    assert "--allow-extra-rounds" in cli_source
    assert "--extra-round-reason" in cli_source
    assert "--scope-strict" in cli_source
    assert "Cross-model review is a confirmation pass with bounded rounds" in canonical
    assert REVIEW_BEFORE_PUSH_SKILL.exists()
    assert "name: review-before-push" in review_before_push_skill
