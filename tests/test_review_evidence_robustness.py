"""RCA (Jun-17): the review-evidence manifest scan crashed with
'list' object has no attribute 'get' on a stray non-manifest JSON array
(tier3-fill-classified-findings.json) in the evidence dir. It must skip a
non-object manifest, not raise."""
import json
import subprocess
from pathlib import Path


def test_non_object_manifest_is_skipped_not_raised(cli, tmp_path):
    stray = tmp_path / "tier3-fill-classified-findings.json"
    stray.write_text(json.dumps([{"finding": "x"}]), encoding="utf-8")
    errors = cli.implementation_review_manifest_errors({}, tmp_path, {}, stray)
    assert errors and "not a review manifest object" in errors[0]


def test_object_manifest_still_parsed(cli, tmp_path):
    # A dict manifest must NOT be short-circuited by the new guard (it proceeds
    # to normal validation and returns its own, different errors).
    manifest = tmp_path / "good.json"
    manifest.write_text(json.dumps({"plugin_version": "0.6.0"}), encoding="utf-8")
    errors = cli.implementation_review_manifest_errors({}, tmp_path, {}, manifest)
    assert all("not a review manifest object" not in e for e in errors)


def test_explicit_t1_legacy_stage1_superset_is_accepted(cli, tmp_path):
    note = (
        "Stage 1 native review inspected the current assembled diff and found no blockers "
        "before the Codex implementation review."
    )
    state = {
        "branch": "feature/t1",
        "base_sha": "base",
        "head_sha": "head",
        "diff_sha256": "diff-current",
        "diff_bytes": 42,
    }
    log = tmp_path / "review.log"
    log.write_text("review log\n", encoding="utf-8")
    sweep = tmp_path / "stage1-sweep.json"
    sweep.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_STAGE1_SWEEP_SCHEMA,
                "stage": cli.IMPLEMENTATION_STAGE1_SWEEP_STAGE,
                "recorded_by": "tautline record-stage1-sweep",
                "branch": state["branch"],
                "base_sha": state["base_sha"],
                "head_sha": state["head_sha"],
                "diff_sha256": state["diff_sha256"],
                "native_review_note": note,
                "classes": [
                    {
                        "class": "process integrity",
                        "members_checked": "review manifest compatibility fields for explicit T1 legacy evidence",
                        "status": "clean",
                    }
                ],
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "recorded_at": "2026-07-02T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
                "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
                "reviewer": "codex",
                "recorded_by": "tautline codex-run",
                "branch": state["branch"],
                "base_sha": state["base_sha"],
                "head_sha": state["head_sha"],
                "diff_sha256": state["diff_sha256"],
                "review_command": "./scripts/codex-review.sh",
                "review_wrapper": "./scripts/codex-review.sh",
                "risk_tier": "T1",
                "review_round": "R1",
                "native_review_required": True,
                "native_review_requirement": "Stage 1 native/Superpowers review on current assembled diff before this Stage 2 Codex round",
                "native_review_note": note,
                "stage1_sweep_required": True,
                "stage1_sweep_path": str(Path(sweep.name)),
                "stage1_sweep_sha256": cli.file_sha256(sweep),
                "log_path": str(Path(log.name)),
                "log_sha256": cli.file_sha256(log),
                "wrapper_exit_code": 0,
                "finished_at": "2026-07-02T00:00:01+00:00",
                "plugin_version": "0.6.127",
            }
        ),
        encoding="utf-8",
    )

    errors = cli.implementation_review_manifest_errors(
        {"review": {"codexWrapper": "./scripts/codex-review.sh"}},
        tmp_path,
        state,
        manifest,
        require_classification=False,
    )

    assert errors == []


def test_pre_stage1_t1_native_review_manifest_without_sweep_flag_is_accepted(cli, tmp_path):
    state = {
        "branch": "feature/t1",
        "base_sha": "base",
        "head_sha": "head",
        "diff_sha256": "diff-current",
        "diff_bytes": 42,
    }
    log = tmp_path / "review.log"
    log.write_text("review log\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
                "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
                "reviewer": "codex",
                "recorded_by": "tautline codex-run",
                "branch": state["branch"],
                "base_sha": state["base_sha"],
                "head_sha": state["head_sha"],
                "diff_sha256": state["diff_sha256"],
                "review_command": "./scripts/codex-review.sh",
                "review_wrapper": "./scripts/codex-review.sh",
                "risk_tier": "T1",
                "review_round": "R1",
                "native_review_required": True,
                "native_review_requirement": "native review required by the previous implementation-review contract",
                "log_path": str(Path(log.name)),
                "log_sha256": cli.file_sha256(log),
                "wrapper_exit_code": 0,
                "finished_at": "2026-07-02T00:00:01+00:00",
                "plugin_version": "0.6.78",
            }
        ),
        encoding="utf-8",
    )

    errors = cli.implementation_review_manifest_errors(
        {"review": {"codexWrapper": "./scripts/codex-review.sh"}},
        tmp_path,
        state,
        manifest,
        require_classification=False,
    )

    assert errors == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_review_evidence_uses_adapter_declared_experimental_base(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-qb", "experimental")
    (repo / "experimental.txt").write_text("experimental\n", encoding="utf-8")
    _git(repo, "add", "experimental.txt")
    _git(repo, "commit", "-qm", "experimental")
    _git(repo, "update-ref", "refs/remotes/origin/experimental", "HEAD")
    _git(repo, "checkout", "-qb", "feature/self-adapter")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-qm", "feature")

    data = {"review": {"codexWrapper": "codex review --base origin/experimental"}}
    assert cli.review_wrapper_base(data) == "origin/experimental"
    assert "origin/experimental" in cli.implementation_review_allowed_base_refs(data)

    state, errors = cli.implementation_review_state(
        repo,
        cli.implementation_review_effective_base(data),
    )

    assert errors == []
    assert state["base_ref"] == "origin/experimental"
    assert state["diff_bytes"] > 0


def test_review_evidence_requires_adapter_declared_base(cli, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-qb", "feature/self-adapter")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-qm", "feature")

    data = {"review": {"codexWrapper": "codex review --base origin/experimental"}}
    state, errors = cli.implementation_review_state(
        repo,
        cli.implementation_review_effective_base(data),
    )

    assert state is None
    assert errors == ["configured implementation review base is unavailable: origin/experimental"]


def test_review_evidence_allowed_bases_do_not_whitelist_local_override(cli):
    data = {"review": {"codexWrapper": "codex review --base origin/experimental"}}

    local_allowed = cli.implementation_review_allowed_base_refs(data, explicit_base="main")
    remote_allowed = cli.implementation_review_allowed_base_refs(data, explicit_base="origin/release")

    assert "main" not in local_allowed
    assert "origin/release" in remote_allowed


def test_review_evidence_allowed_bases_do_not_whitelist_local_wrapper_base(cli):
    data = {"review": {"codexWrapper": "codex review --base main"}}

    allowed = cli.implementation_review_allowed_base_refs(data)

    assert "main" not in allowed
    assert "origin/main" in allowed


def test_review_evidence_hint_base_never_recommends_rejected_local_base(cli):
    allowed = {"origin/main", "origin/experimental"}

    assert cli.implementation_review_hint_base(allowed, "main") == "origin/main"
    assert cli.implementation_review_hint_base(allowed, "origin/experimental") == "origin/experimental"
