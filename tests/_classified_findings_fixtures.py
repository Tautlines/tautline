"""Shared temp-lane harness for the classified-findings contract suites.

W1.1 lands four suites (items 73 + 74 PR-B) that all need the same starting point: a
`finalize-implementation-review` run over a manifest the BASE validator already accepts, so each
test isolates the contract rule it names instead of re-deriving a valid manifest eight times.

What is real here: the manifest file, the review log and its sha pin, the classified-findings
JSON, and the ledger the finalizer writes. What is stubbed: adapter resolution (`lane_project`)
and git-state derivation (`implementation_review_state`). Both have their own suites, and driving
them here would make these tests about the loader instead of about the contract -- the idiom
`tests/test_behavior_spec_delta_check.py` already uses for the same reason.

``LEGACY_PLUGIN_VERSION`` is the version that introduced the mandatory Stage 1 sweep: new enough
that ``legacy_pre_stage1`` is False (so the base validator stays strict and the manifest shape
under test does not change), and older than the classified-findings contract, which is the
tolerance these suites need to exercise. ``assert_legacy_version_is_below_contract`` pins that
relationship so the tolerance tests cannot go vacuous when the contract constant moves.
"""
import argparse
import json
from pathlib import Path

WRAPPER = "./scripts/codex-review.sh"
SOURCE_OF_TRUTH = "docs/plans"


def adapter(**overrides) -> dict:
    """The narrowest adapter the finalize path reads: wrapper, plan root, evidence mode."""
    data = {
        "review": {"codexWrapper": WRAPPER, "prePushReviewEvidence": True},
        "planningArtifacts": {"sourceOfTruth": SOURCE_OF_TRUTH},
        # `off` keeps the separate test-evidence gate (item 37) out of these tests entirely: it
        # returns 0 and prints nothing, and the ledger-exclusion guard below it is `block`-only.
        "testEvidence": {"enforcement": "off"},
    }
    data.update(overrides)
    return data


def legacy_plugin_version(cli) -> str:
    return cli.STAGE1_SWEEP_REQUIREMENT_PLUGIN_VERSION


def assert_legacy_version_is_below_contract(cli) -> None:
    """The tolerance tests are only meaningful while this ordering holds."""
    assert cli.version_tuple(legacy_plugin_version(cli)) < cli.version_tuple(
        cli.CLASSIFIED_FINDINGS_CONTRACT_PLUGIN_VERSION
    ), (
        "the legacy fixture version must be older than the classified-findings contract, "
        "or every migration-tolerance test below passes for the wrong reason"
    )


BLOCKER_FREE_LOG = """# Codex review run

## Findings

- None. The diff is clean.

Verdict: clean
"""


class Lane:
    """A finalize-ready lane: paths on disk plus the git state the finalizer would have derived."""

    def __init__(self, target: Path, manifest_path: Path, log_path: Path, state: dict):
        self.target = target
        self.manifest_path = manifest_path
        self.log_path = log_path
        self.state = state

    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def ledger_path(self, cli, data: dict | None = None) -> Path:
        return cli.implementation_review_ledger_path(data or adapter(), self.target, self.state)

    def findings_file(self, findings: list[dict], name: str = "findings.json") -> Path:
        path = self.target / name
        path.write_text(json.dumps(findings), encoding="utf-8")
        return path

    def classify(self, **fields) -> None:
        """Hand-write a finalized classification onto the manifest.

        The manifest validator returns early on any MISSING required field, so a rule that lives
        in its `require_classification` block is only reachable from a manifest that is otherwise
        complete. Building that from `lane()` is also the honest shape: this is what a finalized
        manifest looks like on disk.
        """
        manifest = self.manifest()
        manifest.update(
            {
                "classification_status": "clean-with-deferrals",
                "verdict": "clean-with-deferrals",
                "unresolved_critical_count": 0,
                "unresolved_p1_count": 0,
                "classification_recorded_by": "tautline finalize-implementation-review",
                "classified_findings": [],
            }
        )
        manifest.update(fields)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def manifest_errors(
        self,
        cli,
        *,
        require_classification: bool = True,
        data: dict | None = None,
    ) -> list[str]:
        return cli.implementation_review_manifest_errors(
            data if data is not None else adapter(),
            self.target,
            self.state,
            self.manifest_path,
            require_classification,
        )

    def rewrite_log(self, cli, text: str) -> None:
        """Change the log AND re-pin its sha -- the honest shape of a differently-worded review."""
        self.log_path.write_text(text, encoding="utf-8")
        manifest = self.manifest()
        manifest["log_sha256"] = cli.file_sha256(self.log_path)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def unpin_log(self, text: str) -> None:
        """Change the log bytes and leave `log_sha256` stale -- a tampered or stale log."""
        self.log_path.write_text(text, encoding="utf-8")


def lane(
    cli,
    tmp_path: Path,
    *,
    log_text: str = BLOCKER_FREE_LOG,
    plugin_version: str | None = None,
    branch: str = "fix/classified-findings-contract",
) -> Lane:
    target = tmp_path / "lane"
    (target / SOURCE_OF_TRUTH).mkdir(parents=True, exist_ok=True)
    evidence_dir = cli.implementation_review_evidence_dir(target)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "review.log"
    log_path.write_text(log_text, encoding="utf-8")
    state = {
        "branch": branch,
        "head_sha": "head" * 10,
        "base_ref": "origin/experimental",
        "base_sha": "base" * 10,
        "diff_sha256": "diff-under-review",
        "diff_bytes": 4096,
    }
    manifest = {
        "schema": cli.IMPLEMENTATION_REVIEW_SCHEMA,
        "stage": cli.IMPLEMENTATION_REVIEW_STAGE,
        "reviewer": "codex",
        "recorded_by": "tautline codex-run",
        "branch": state["branch"],
        "base_sha": state["base_sha"],
        "head_sha": state["head_sha"],
        "diff_sha256": state["diff_sha256"],
        "review_command": WRAPPER,
        "review_wrapper": WRAPPER,
        # Explicit T1: keeps the Stage 1 sweep machinery (its own suite) out of these fixtures.
        "risk_tier": "T1",
        "native_review_required": False,
        "native_review_requirement": "explicit T1: no native review required",
        "stage1_sweep_required": False,
        "log_path": cli.path_relative_to_target(target, log_path),
        "log_sha256": cli.file_sha256(log_path),
        "wrapper_exit_code": 0,
        "finished_at": "2026-08-10T00:00:00+00:00",
    }
    if plugin_version is not None:
        manifest["plugin_version"] = plugin_version
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return Lane(target, manifest_path, log_path, state)


PLAN_TEXT = """# Widen the export throttle — Implementation Plan

## Milestone Goal
Raise the export throttle ceiling for the reporting surface without changing its failure mode.

## Non-Goals / Out of scope
Rewriting the queue. Changing the retention window. Touching the billing path.

## Evidence and source links
Two incident reports and the throttle counter series recorded over the preceding month.

## Assumptions
The queue depth stays inside its current envelope while the ceiling is raised.

## Dependencies
None outside this package.

## Ordered scope / implementation
1. Widen the ceiling behind the existing flag.
2. Record the new ceiling in the operations reference.
3. Extend the throttle suite with the widened bound.

## Acceptance criteria
The widened ceiling is observed under load, and the failure mode is byte-identical to today's.

## Tests / validation
The throttle suite runs green, including the two new bound cases.

## Review or merge gates
Implementation review at the usual tier, then the merge queue.

## Risks
A widened ceiling could mask a queue-depth regression; the counter series is the guard.

## Open decisions
None recorded.

## Completion Definition
Done means the widened ceiling ships with its bound cases green and the reference updated.
"""


def plan_lane(cli, tmp_path: Path, findings: list[dict], *, verdict: str = "clean-with-deferrals"):
    """A target whose plan passes substance validation and whose plan-review manifest carries
    `findings` -- enough to reach the classified-findings block in the precheck.

    The manifest's OTHER field values are deliberately left unverifiable (stub hashes, stub log
    paths): those checks run AFTER the classified-findings block, so their errors sit alongside
    the one under test rather than short-circuiting it. Every field is PRESENT, which is what the
    required-field early return cares about.
    """
    target = tmp_path / "plan-lane"
    source_root = target / SOURCE_OF_TRUTH
    source_root.mkdir(parents=True, exist_ok=True)
    plan_path = source_root / "widen-export-throttle.md"
    plan_path.write_text(PLAN_TEXT, encoding="utf-8")
    manifest_path = source_root / ".plan-reviews" / f"{cli.slugify(plan_path.stem, 'plan')}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": cli.PLAN_REVIEW_SCHEMA,
        "classifier_version": cli.PLAN_REVIEW_CLASSIFIER_VERSION,
        "recorded_by": "tautline run-plan-review",
        "plan_path": cli.path_relative_to_target(target, plan_path),
        "plan_content_sha256": cli.plan_content_sha256(plan_path),
        "review_command": WRAPPER,
        "log_path": "plan-review.log",
        "log_sha256": "stub",
        "review_run_meta_path": "plan-review-meta.json",
        "review_run_meta_sha256": "stub",
        "reviewer": "codex",
        "reviewer_model": "codex",
        "round": "R1",
        "wrapper_exit_code": 0,
        "verdict": verdict,
        "unresolved_critical_count": 0,
        "unresolved_p1_count": 0,
        "classified_findings": findings,
        "timestamp": "2026-08-10T00:00:00+00:00",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target, plan_path


def plan_adapter() -> dict:
    """The narrowest adapter that reaches the precheck's classified-findings block: every
    plan-authoring gate ahead of it is explicitly quiet, so a failure here is about findings."""
    return {
        "review": {"codexWrapper": WRAPPER},
        "planningArtifacts": {"sourceOfTruth": SOURCE_OF_TRUTH, "reviewExemptions": []},
        "planAcceptance": {"enforcement": "off", "acHeadings": ["acceptance criteria"]},
        "planning": {"authoringStandard": {"enforcement": "off"}},
        "behaviorSpecs": {},
    }


def plan_precheck_errors(
    cli,
    tmp_path: Path,
    findings: list[dict],
    *,
    verdict: str = "clean-with-deferrals",
):
    target, plan_path = plan_lane(cli, tmp_path, findings, verdict=verdict)
    errors, _plan, _manifest = cli.plan_finalization_precheck_errors(
        plan_adapter(), target, Path(cli.path_relative_to_target(target, plan_path))
    )
    return errors


def finalize(
    cli,
    monkeypatch,
    subject: Lane,
    *,
    verdict: str = "clean",
    findings: list[dict] | None = None,
    findings_path: Path | None = None,
    critical: int = 0,
    p1: int = 0,
    data: dict | None = None,
) -> int:
    """Run the real `finalize_implementation_review` handler over `subject`."""
    project_data = data if data is not None else adapter()
    monkeypatch.setattr(cli, "lane_project", lambda args: (project_data, None, subject.target))
    monkeypatch.setattr(
        cli, "implementation_review_state", lambda target, base=None: (subject.state, [])
    )
    if findings_path is None and findings is not None:
        findings_path = subject.findings_file(findings)
    args = argparse.Namespace(
        project=None,
        target=subject.target,
        manifest=str(subject.manifest_path),
        base=None,
        verdict=verdict,
        unresolved_critical_count=critical,
        unresolved_p1_count=p1,
        classified_findings_json=str(findings_path) if findings_path else None,
    )
    return cli.finalize_implementation_review(args)


def evidence_check(
    cli,
    monkeypatch,
    subject: Lane,
    *,
    strict: bool,
    data: dict | None = None,
) -> int:
    """Run `review_evidence_check` over the lane's finalized manifest."""
    project_data = data if data is not None else adapter()
    monkeypatch.setattr(cli, "lane_project", lambda args: (project_data, None, subject.target))
    monkeypatch.setattr(
        cli, "implementation_review_state", lambda target, base=None: (subject.state, [])
    )
    monkeypatch.setattr(cli, "lane_session_plugin_drift", lambda data, target: None)
    monkeypatch.setattr(cli, "review_evidence_coordination_allowance", lambda data, target: False)
    monkeypatch.setattr(
        cli,
        "implementation_review_allowed_base_refs",
        lambda data, base=None: {"origin/experimental"},
    )
    monkeypatch.setattr(cli, "implementation_review_ledger_errors", lambda *a, **k: [])
    # Same reason as the line above: this lane is a tmp_path, not a git repo, so the
    # tracked/clean half of the evidence gate cannot pass here and is not what these tests
    # are about. The real gate still runs both; the round-history tracked bar is pinned in a
    # REAL repo by test_rounds_errors_flags_an_untracked_history.
    monkeypatch.setattr(cli, "implementation_review_rounds_errors", lambda *a, **k: [])
    args = argparse.Namespace(
        project=None,
        target=subject.target,
        base=None,
        strict=strict,
        scope_strict=False,
    )
    return cli.review_evidence_check(args)
