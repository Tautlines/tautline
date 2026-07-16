import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_ROOT = Path("docs/product/backlog/example-saas-v1/specs")
PLAN_REL = SOURCE_ROOT / "test-plan.md"
TEMPLATE_REL = Path("docs/product/backlog/templates/pr-execution-spec.template.md")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _run_cli(
    *args: str,
    home: Path,
    adapter_root: Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    merged_env = {
        **{
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "MINERVIT_REAL_CODEX",
                "MINERVIT_CODEX_FAST_MODE",
                "MINERVIT_CODEX_FAST_MODE_SHIM",
            }
        },
        "HOME": str(home),
        "MINERVIT_METHODOLOGY_ADAPTER_ROOT": str(adapter_root),
        **(env or {}),
    }
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env=merged_env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _write_adapter(adapter_root: Path, *, codex_fast_mode: bool = True, wrapper: str = "./scripts/codex-review.sh") -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for plan-review CLI coverage.",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    data["graphify"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["laneCoordination"] = {"enabled": False}
    data["review"]["codexFastMode"] = codex_fast_mode
    data["review"]["codexPlanWrapper"] = wrapper
    data["review"]["codexWrapper"] = wrapper
    for key in (
        "backlogProvider",
        "goalTracker",
        "stakeholderQuestions",
        "deploymentNotification",
        "productChat",
        "milestoneUpdate",
        "iterationReview",
    ):
        data.pop(key, None)
    adapter = adapter_root / f"plan-review-{'fast' if codex_fast_mode else 'normal'}.json"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    (target / SOURCE_ROOT).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")
    scripts = target / "scripts"
    scripts.mkdir()
    _write_review_script(
        target,
        "printf 'Codex review args: %s\\n' \"$*\"\n"
        "printf 'Verdict: clean\\n'\n"
        "printf 'No Critical or P1 findings.\\n'\n",
    )


def _write_review_script(target: Path, body: str, *, name: str = "codex-review.sh") -> Path:
    path = target / "scripts" / name
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_plan(target: Path, rel: Path = PLAN_REL, *, summary: str = "Deliver reviewed behavior safely.") -> Path:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Test Plan\n\n"
        "## Milestone Goal\n"
        f"{summary}\n\n"
        "## Non-Goals\n"
        "Do not change production behavior outside the tested fixture.\n\n"
        "## Evidence And Sources\n"
        "Use the adapter, current backlog entry, and review logs as source evidence.\n\n"
        "## Assumptions\n"
        "The test lane has a configured source-of-truth path and review wrapper.\n\n"
        "## Ordered Scope\n"
        "1. Build the fixture.\n"
        "2. Validate the gate.\n"
        "3. Record the review evidence.\n\n"
        "## Dependencies\n"
        "The plan depends on the configured adapter review wrapper and local lane files.\n\n"
        "## Acceptance Criteria\n"
        "The plan finalization precheck fails before review evidence and passes after clean review evidence.\n\n"
        "## Tests And Validation\n"
        "Run behavior and implementation gates.\n\n"
        "## Review And Merge Gates\n"
        "Cross-model review must be recorded before finalization.\n\n"
        "## Risks\n"
        "The main risk is accepting stale review evidence.\n\n"
        "## Open Decisions\n"
        "None.\n\n"
        "## Behavior Source Materials\n"
        "- `docs/product/user-scenarios.md`: reviewed and split into shop-owner/platform-admin role scenarios where needed.\n"
        "- `docs/product/acceptance-criteria.md`: reviewed and preserved for customer role expectations.\n\n"
        "## Completion Definition\n"
        "Done means the precheck accepts clean current evidence and rejects stale evidence.\n",
        encoding="utf-8",
    )
    return path


def _prepare_target(tmp_path: Path, *, codex_fast_mode: bool = True, wrapper: str = "./scripts/codex-review.sh"):
    home = tmp_path / "home"
    adapter_root = tmp_path / "trusted-adapters"
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(adapter_root, codex_fast_mode=codex_fast_mode, wrapper=wrapper)
    _write_plan(target)
    return home, adapter_root, target, adapter


def _manifest_path(target: Path, rel: Path = PLAN_REL) -> Path:
    return target / rel.parent / ".plan-reviews" / f"{rel.stem}.json"


def _stdout_path(stdout: str, prefix: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return Path(line.split(": ", 1)[1])
    raise AssertionError(f"missing output line {prefix!r} in:\n{stdout}")


def test_plan_precheck_rejects_forbidden_roles_but_allows_quoted_source_role(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    forbidden_rel = SOURCE_ROOT / "forbidden-role.md"
    _write_plan(target, forbidden_rel, summary="Add user behavior coverage.")
    forbidden = _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        forbidden_rel.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )

    quoted_rel = SOURCE_ROOT / "quoted-source-role.md"
    quoted = _write_plan(target, quoted_rel, summary="Replace obsolete source wording with precise roles.")
    quoted.write_text(
        quoted.read_text(encoding="utf-8")
        + "\n## Role Vocabulary Deviation\nThe source used `user`; the adapted behavior uses shop owner and platform admin.\n",
        encoding="utf-8",
    )
    quoted_result = _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        quoted_rel.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )

    assert forbidden.returncode == 1
    assert "forbidden behavior role term present in plan: user" in forbidden.stderr
    assert quoted_result.returncode == 1
    assert "forbidden behavior role term present" not in quoted_result.stderr
    assert "plan review manifest missing" in quoted_result.stderr


def test_run_plan_review_writes_plan_only_metadata_and_stale_markers(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    user_plan = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Shadow",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--",
        "--plan",
        f"{PLAN_REL}.shadow",
        home=home,
        adapter_root=adapter_root,
    )
    assert user_plan.returncode == 1
    assert "review args cannot supply --plan" in user_plan.stderr

    single = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    assert single.returncode == 0, single.stdout + single.stderr
    assert "plan_review_scope: plan-only" in single.stdout
    assert "plan_review_code_diff_review: no" in single.stdout
    assert "plan_review_manifest:" not in single.stdout
    meta_path = _stdout_path(single.stdout, "plan_review_run_meta")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["review_scope"] == "plan-only"
    assert meta["code_diff_review"] is False

    _write_review_script(target, "sleep 10\n", name="silent-review.sh")
    stale_adapter = _write_adapter(adapter_root, wrapper="./scripts/silent-review.sh")
    stale_rel = SOURCE_ROOT / "test-plan-stale.md"
    (target / stale_rel).write_text((target / PLAN_REL).read_text(encoding="utf-8"), encoding="utf-8")
    stale = _run_cli(
        "run-plan-review",
        "--project",
        str(stale_adapter),
        "--target",
        str(target),
        "--plan",
        stale_rel.as_posix(),
        "--round",
        "R1Stale",
        "--model",
        "codex-test",
        "--no-output-timeout-seconds",
        "1",
        home=home,
        adapter_root=adapter_root,
        timeout=20,
    )
    assert stale.returncode == 124
    assert "plan_review_run_exit_code: 124" in stale.stdout
    assert "do not classify this frozen log as evidence" in stale.stdout
    stale_meta = json.loads(_stdout_path(stale.stdout, "plan_review_run_meta").read_text(encoding="utf-8"))
    stale_marker = json.loads(_stdout_path(stale.stdout, "plan_review_stale_marker").read_text(encoding="utf-8"))
    assert stale_meta["wrapper_exit_code"] == 124
    assert stale_meta["no_output_timeout_seconds"] == 1
    assert stale_marker["reason"] == "stale_no_output"
    assert stale_marker["noOutputTimeoutSeconds"] == 1


def test_finalize_plan_review_requires_plan_only_meta_and_precheck_trusted_manifest(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    single = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    log_path = _stdout_path(single.stdout, "plan_review_run_log")
    meta_path = _stdout_path(single.stdout, "plan_review_run_meta")
    finalize = _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    precheck = _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr
    assert "recorded_by" in _manifest_path(target).read_text(encoding="utf-8")
    assert "plan_review_round_status: round 1 of 2; verdict=clean" in finalize.stdout
    assert precheck.returncode == 0, precheck.stderr

    original = meta_path.read_text(encoding="utf-8")
    meta = json.loads(original)
    meta["code_diff_review"] = True
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bad_diff = _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert bad_diff.returncode == 1
    assert "must prove plan-only scope and code_diff_review=false" in bad_diff.stderr
    meta_path.write_text(original, encoding="utf-8")
    meta = json.loads(original)
    meta["review_scope"] = "code-diff"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bad_scope = _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        "R1Single",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert bad_scope.returncode == 1
    assert "must prove plan-only scope and code_diff_review=false" in bad_scope.stderr


def test_record_plan_review_import_is_diagnostic_and_not_trusted_by_precheck(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    run = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Counts",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )
    log_path = _stdout_path(run.stdout, "plan_review_run_log")
    review_command = next(line.split(": ", 1)[1] for line in run.stdout.splitlines() if line.startswith("plan_review_run_command: "))
    record = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--review-command",
        review_command,
        "--reviewer",
        "codex",
        "--model",
        "codex-test",
        "--round",
        "R1Counts",
        "--wrapper-exit-code",
        "0",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    imported_manifest = _stdout_path(record.stdout, "plan_review_manifest")
    trusted_manifest = _manifest_path(target)
    trusted_manifest.parent.mkdir(parents=True, exist_ok=True)
    trusted_manifest.write_text(imported_manifest.read_text(encoding="utf-8"), encoding="utf-8")
    precheck = _run_cli(
        "plan-finalization-precheck",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
    )

    assert record.returncode == 0, record.stdout + record.stderr
    assert "diagnostic import only; wrote .imported.json" in record.stdout
    assert "plan-finalization-precheck trusts only the canonical run-plan-review manifest" in record.stdout
    assert precheck.returncode == 1
    assert "recorded_by is not trusted" in precheck.stderr


def test_legacy_recorder_names_stay_trusted(cli):
    # Pre-0.8.0 plan-review manifests in downstream product repos are recorded by
    # the legacy CLI name; the rebrand guarantees they stay finalizable (found
    # live: 208 legacy-recorded manifests in one product repo were rejected by
    # plan-finalization-precheck after the 0.8.x upgrade). record-plan-review
    # imports must stay untrusted under both names.
    assert "minervit-methodology run-plan-review" in cli.PLAN_REVIEW_TRUSTED_RECORDERS
    assert "minervit-methodology finalize-plan-review" in cli.PLAN_REVIEW_TRUSTED_RECORDERS
    assert "tautline record-plan-review" not in cli.PLAN_REVIEW_TRUSTED_RECORDERS
    assert "minervit-methodology record-plan-review" not in cli.PLAN_REVIEW_TRUSTED_RECORDERS


def test_run_plan_review_enforces_counts_round_caps_and_log_classification(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    count_mismatch = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Counts",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        '[{"severity":"Critical","summary":"blocking issue"}]',
        home=home,
        adapter_root=adapter_root,
    )
    assert count_mismatch.returncode == 1
    assert "unresolved Critical/P1 counts must match classified-findings-json" in count_mismatch.stderr

    for review_round in ("final", "R0"):
        bad_round = _run_cli(
            "run-plan-review",
            "--project",
            str(adapter),
            "--target",
            str(target),
            "--plan",
            PLAN_REL.as_posix(),
            "--round",
            review_round,
            "--model",
            "codex-test",
            "--verdict",
            "clean",
            "--unresolved-critical-count",
            "0",
            "--unresolved-p1-count",
            "0",
            home=home,
            adapter_root=adapter_root,
        )
        assert bad_round.returncode == 1
        assert "--round must include a numeric review round 1-4" in bad_round.stderr

    for path in [target / ".ai-runs" / "plan-review", target / SOURCE_ROOT / ".plan-reviews"]:
        if path.exists():
            shutil.rmtree(path)
    blocked_r1 = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1Blocked",
        "--model",
        "codex-test",
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        "1",
        "--unresolved-p1-count",
        "1",
        "--classified-findings-json",
        '[{"severity":"Critical","summary":"blocking issue"},{"severity":"P1","summary":"important issue"}]',
        home=home,
        adapter_root=adapter_root,
    )
    blocked_r2 = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R2Cap",
        "--model",
        "codex-test",
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        "1",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        '[{"severity":"Critical","summary":"blocking issue"}]',
        home=home,
        adapter_root=adapter_root,
    )
    r3_no_evidence = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R3",
        "--model",
        "codex-test",
        "--verdict",
        "blocked",
        "--unresolved-critical-count",
        "1",
        "--unresolved-p1-count",
        "1",
        "--classified-findings-json",
        '[{"severity":"Critical","summary":"blocking issue"},{"severity":"P1","summary":"important issue"}]',
        home=home,
        adapter_root=adapter_root,
    )
    r3_allowed = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R3",
        "--allow-r3-structural-critical",
        "--structural-critical-evidence",
        "R2 identified a confirmed structural Critical that would cause user-visible failure",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        "[]",
        home=home,
        adapter_root=adapter_root,
    )
    r4_no_note = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R4",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    r5 = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R5",
        "--exception-note",
        "A fifth round cannot be bought with any note; the cap is absolute",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )

    assert blocked_r1.returncode == 0, blocked_r1.stdout + blocked_r1.stderr
    # R2 blocked is no longer terminal: the ladder self-authorizes round 3 once the fixes land.
    assert blocked_r2.returncode == 0, blocked_r2.stdout + blocked_r2.stderr
    assert "self-authorize round 3 of 4 with --exception-note" in blocked_r2.stdout
    assert "no operator authorization needed" in blocked_r2.stdout
    # Past the target, a round without a recorded exception is refused...
    assert r3_no_evidence.returncode == 1
    assert "is past the 2-round convergence target" in r3_no_evidence.stderr
    assert "--exception-note" in r3_no_evidence.stderr
    # ...and with one it proceeds, no operator escalation involved.
    assert r3_allowed.returncode == 0, r3_allowed.stdout + r3_allowed.stderr
    assert "round 3 of 4 (recorded convergence exception); verdict=clean" in r3_allowed.stdout
    assert r4_no_note.returncode == 1
    assert "is past the 2-round convergence target" in r4_no_note.stderr
    # Past the hard cap refusal is unconditional -- a note cannot buy round 5.
    assert r5.returncode == 1
    assert "exceeds the hard cap of 4 rounds" in r5.stderr

    _write_review_script(
        target,
        "printf 'Codex review args: %s\\n' \"$*\"\n"
        "printf 'Verdict: clean\\n'\n"
        "printf 'Critical: fabricated blocker for validation.\\n'\n",
    )
    critical_log = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1CriticalLog",
        "--model",
        "codex-test",
        "--verdict",
        "clean",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert critical_log.returncode == 1
    assert "review log mentions Critical/P1/Important findings" in critical_log.stderr

    _write_review_script(
        target,
        "printf 'Codex review args: %s\\n' \"$*\"\n"
        "cat <<'REVIEW'\n"
        "## Findings\n\n"
        "### Critical (none)\nNone.\n\n"
        "### P1 (Important)\nImportant: wording concern is already addressed by the current plan text.\n"
        "REVIEW\n",
    )
    addressed = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R2Addressed",
        "--model",
        "codex-test",
        "--verdict",
        "clean-with-deferrals",
        "--unresolved-critical-count",
        "0",
        "--unresolved-p1-count",
        "0",
        "--classified-findings-json",
        '[{"severity":"Important","status":"addressed","summary":"wording concern already addressed"}]',
        home=home,
        adapter_root=adapter_root,
    )
    assert addressed.returncode == 0, addressed.stdout + addressed.stderr
    assert "plan_review_manifest:" in addressed.stdout


def test_codex_fast_mode_is_injected_for_plan_review_and_can_be_disabled(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(tmp_path, wrapper="./scripts/codex-review.sh")
    fake_bin = tmp_path / "fake-codex-bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${FAKE_CODEX_ARGS_FILE:?}\"\n"
        "printf 'fake codex args: %s\\n' \"$*\"\n"
        "printf '## Findings\\nNo Critical or P1 findings.\\n'\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    _write_review_script(target, "codex review \"$@\"\n")
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-fast.args"),
    }
    fast = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1FastMode",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
        env=env,
    )
    assert fast.returncode == 0, fast.stdout + fast.stderr
    assert "plan_review_codex_fast_mode: enabled" in fast.stdout
    assert "--enable fast_mode review --plan docs/product/backlog/example-saas-v1/specs/test-plan.md" in Path(env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    fast_meta = json.loads(_stdout_path(fast.stdout, "plan_review_run_meta").read_text(encoding="utf-8"))
    assert fast_meta["codex_fast_mode"] is True

    off_rel = SOURCE_ROOT / "fast-mode-plan-off.md"
    _write_plan(target, off_rel)
    off_adapter = _write_adapter(adapter_root, codex_fast_mode=False, wrapper="./scripts/codex-review.sh")
    off_env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-fast-off.args"),
    }
    off = _run_cli(
        "run-plan-review",
        "--project",
        str(off_adapter),
        "--target",
        str(target),
        "--plan",
        off_rel.as_posix(),
        "--round",
        "R1FastModeOff",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
        env=off_env,
    )
    off_args = Path(off_env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    assert off.returncode == 0, off.stdout + off.stderr
    assert "plan_review_codex_fast_mode: disabled" in off.stdout
    assert "--enable fast_mode" not in off_args
    assert "review --plan docs/product/backlog/example-saas-v1/specs/fast-mode-plan-off.md" in off_args


def test_builtin_codex_plan_review_wrapper_translates_plan_binding(tmp_path):
    home, adapter_root, target, adapter = _prepare_target(
        tmp_path,
        wrapper=f"{sys.executable} {CLI_PATH} codex-plan-review --target . --base origin/experimental",
    )
    fake_bin = tmp_path / "fake-codex-bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${FAKE_CODEX_ARGS_FILE:?}\"\n"
        "printf 'fake codex args: %s\\n' \"$*\"\n"
        "printf '## Findings\\nNo Critical or P1 findings.\\n'\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-plan-wrapper.args"),
    }

    result = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1BuiltinWrapper",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
        env=env,
    )

    args_text = Path(env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "review --base origin/experimental" in args_text
    assert "--plan " not in args_text
    assert "Plan path: docs/product/backlog/example-saas-v1/specs/test-plan.md" in args_text
    assert "Start your response with exactly `## Findings`" in args_text
    assert "Deliver reviewed behavior safely." in args_text

    extra_rel = SOURCE_ROOT / "test-plan-extra.md"
    _write_plan(target, extra_rel, summary="Review extra wrapper instructions safely.")
    extra_env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-plan-wrapper-extra.args"),
    }
    extra = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        extra_rel.as_posix(),
        "--round",
        "R1BuiltinWrapperExtra",
        "--model",
        "codex-test",
        "--",
        "check migrations",
        "--focus",
        "compatibility",
        home=home,
        adapter_root=adapter_root,
        env=extra_env,
    )
    extra_args_text = Path(extra_env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    assert extra.returncode == 0, extra.stdout + extra.stderr
    assert "--plan " not in extra_args_text
    assert "Plan path: docs/product/backlog/example-saas-v1/specs/test-plan-extra.md" in extra_args_text
    assert "Additional reviewer instructions:" in extra_args_text
    assert "'check migrations' --focus compatibility" in extra_args_text


def test_builtin_codex_plan_review_accepts_reviewer_flags_before_plan(tmp_path):
    home, adapter_root, target, _adapter = _prepare_target(tmp_path)
    fake_bin = tmp_path / "fake-codex-bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${FAKE_CODEX_ARGS_FILE:?}\"\n"
        "printf 'fake codex args: %s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-plan-direct.args"),
    }

    result = _run_cli(
        "codex-plan-review",
        "--target",
        str(target),
        "--base",
        "origin/experimental",
        "--focus",
        "compatibility",
        "--plan",
        PLAN_REL.as_posix(),
        home=home,
        adapter_root=adapter_root,
        env=env,
    )

    args_text = Path(env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "review --base origin/experimental" in args_text
    assert "--plan " not in args_text
    assert "Plan path: docs/product/backlog/example-saas-v1/specs/test-plan.md" in args_text
    assert "Additional reviewer instructions:" in args_text
    assert "--focus compatibility" in args_text


def test_builtin_codex_plan_review_uses_non_conflicting_plan_fence(tmp_path):
    home, adapter_root, target, _adapter = _prepare_target(tmp_path)
    plan_path = _write_plan(target, SOURCE_ROOT / "fenced-plan.md", summary="Review a plan containing a fenced example safely.")
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8")
        + "\n## Example\n\n"
        + "```bash\n"
        + "echo do-not-close-the-plan-wrapper\n"
        + "```\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "fake-codex-bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${FAKE_CODEX_ARGS_FILE:?}\"\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CODEX_ARGS_FILE": str(tmp_path / "fake-codex-plan-fenced.args"),
    }

    result = _run_cli(
        "codex-plan-review",
        "--target",
        str(target),
        "--base",
        "origin/experimental",
        "--plan",
        (SOURCE_ROOT / "fenced-plan.md").as_posix(),
        home=home,
        adapter_root=adapter_root,
        env=env,
    )

    args_text = Path(env["FAKE_CODEX_ARGS_FILE"]).read_text(encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Plan content:\n````markdown\n" in args_text
    assert "```bash\necho do-not-close-the-plan-wrapper\n```" in args_text
    assert "\n````\n" in args_text


def test_run_plan_review_next_action_names_the_resolved_target(tmp_path):
    """The printed finalize remedy must bind to THIS lane, not to whatever `.` happens to be.

    Track C made every guard remedy render the resolved absolute target via
    guard_target_argument(): on a multi-agent machine `--target .` names whichever checkout the
    shell is sitting in, which may be a worktree owned by another lane. run-plan-review's
    plan_review_next_action is the same class of copy-pasted remedy and was missed.

    The `--target .` inside the plan's committed Cross-Model Review Evidence block is a DIFFERENT
    site and is correct as `.`: it is written into a tracked plan file, where an absolute
    /Users/... path would be a machine token. That one stays.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)

    run = _run_cli(
        "run-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--round",
        "R1",
        "--model",
        "codex-test",
        home=home,
        adapter_root=adapter_root,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    next_action = next(
        line for line in run.stdout.splitlines() if line.startswith("plan_review_next_action: ")
    )
    assert f"finalize-plan-review --target {shlex.quote(str(target.resolve()))}" in next_action
    assert "--target ." not in next_action
