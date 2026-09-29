import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
# Raised 16_000 -> 16_043 to COMPLETE item 69's 0.43.0 raise, which is the whole point of this
# comment. That release added the unconditional template-version stamp (+43 bytes to the rendered
# adapter) and raised `MAX_EXAMPLE_CLAUDE_BYTES` in tests/test_rendered_adapter_budget.py -- the
# only one of the two constants whose test would have gone red. This one gates the SAME artifact
# and was left behind, so the corridor every later claimant budgeted against was 43 bytes smaller
# than the number they were quoting, and a passing suite hid the tighter gate.
#
# THE RULE, verbatim, because it is what this raise buys: a cap raise must enumerate EVERY
# constant gating the artifact, not just the one whose test would have gone red.
#
# Measured on this tip (item 71 PR2), by rendering example-saas to a scratch dir rather than by
# reading any PR: CLAUDE.md 15,764 and AGENTS.md 15,705. The binding budget is the tighter
# constant on the tighter file, so the corridor was 16,000 - 15,764 = 236 and this raise restores
# it to 279. NOT 320 -- that figure came from a 15,723-byte measurement taken before several
# releases landed, and the re-measure-at-your-tip rule governs.
#
# This is a raise by the already-spent delta, not a grant of new bytes.
#
# Raised 16_043 -> 16_318 (+275, measured) for item 101's PR-reference contract line, in the same
# commit as MAX_EXAMPLE_CLAUDE_BYTES above -- the rule this comment already states, now applied
# rather than re-learned. Measured by rendering example-saas at the branch tip: CLAUDE.md
# 15,841 -> 16,116, AGENTS.md 15,782 -> 16,057. Corridor 202 before and 202 after, so item 86's
# declared 200-byte claim is preserved.
MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES = 16_318


REQUIRED_RENDERED_ADAPTER_MARKERS = """
^## Deployment Targets
Adapter-owned deploy procedure/health is authoritative
^## Technical Stack Policy
Cloud default `aws`
Tool/framework defaults do not authorize new platforms
No plaintext secrets in source or images.
^## Session Start
Before gates, resolve CLI
$MINERVIT_METHODOLOGY_REPO/bin/tautline
lane-start --target .
methodology-status --target . --fail-on-drift
latest-code-status --target . --write
gh pr view <PR> --json state,mergeStateStatus
git fetch origin main --quiet && git merge-tree --write-tree HEAD origin/main >/dev/null
^## Development Environment
Supported lane runtimes: `linux`, `darwin`, `wsl2`
Windows native shell support: `unsupported`; supported Windows runtime: `wsl2`
Open the repo inside WSL2 Ubuntu
core.autocrlf input
^## Work Profiles
lane-start --profile product-docs
^## Lane Methodology Updates
Product/client lanes do not raw-pull latest methodology
set-framework-channel --target . stable|experimental
set-framework-channel --target . --source adapter stable|experimental
old repos default to stable/manual/dry-run
render-adapters --write --json-only
^## Local Resource Isolation
Lane startup writes lane-local env to `.ai-work/lane-env.sh`
Port collisions are not human blockers
^## Graphify Navigation
use Graphify report/query/path/explain before broad `rg`/grep
run `graphify update` before commit/push
semantic labeling is separate and non-blocking
commit `graphify-out/`
^## Context Continuity
prepare-continuity --target . --stdin
Context indexes:
Context rotate:
^## Session Signal
prepare-session-journal
publish-instrumentation-record
^## Goal Orchestration
Goal -> Milestone -> PR/tactical item
Project `Status` drift blocks
^## Delivery And Accounting
publish-milestone-update --target . --milestone <id> --stdin
usage-record
^## End-of-Goal Boundary
goal-complete --iteration-review-record
^## Milestone Continuation
milestone-start --target . --plan <source-of-truth-plan>
milestone-advance --target . --event <event>
^## Autonomy And Planning
plan-finalization-precheck --target . --plan <source-of-truth-plan>
Review target is 2 rounds inside a five-round budget charged per plan LINEAGE
Evidence is tracked `.plan-reviews/`
^## Planning Artifacts And Backlog Source Of Truth
Source/template:
Cross-Model Review Evidence
^## Autonomy And Status
Memories/Open Brain are evidence only
Methodology/process regressions use framework-intake
^## Delivery Summaries
Landed/shipped/queued reports start with executive outcome
Refresh continuity before summaries are complete
^## Execution Packet Work Loop
Packet defines scope, ordered queue, dependencies, safe parallelism
^## TDD And Behavior Specs
Behavior specs are required
behavior-spec-status --target .
^## Early-Warning Smoke
Early-warning smoke is no longer a standing gate
^## Local Gates
Before commit: `tautline lane-run --target . -- make pf-fast`
Before push: `tautline lane-run --target . -- make test-env-up`
Do not substitute GitHub Actions for local preflight
^## Review Before Push
codex-run --target . --risk-tier
finalize-implementation-review --target . --manifest <manifest>
track `.impl-reviews/` evidence before push
fix AC-bearing Critical/C1/P1/Important pre-merge; route out-of-AC findings at honest severity
^## Merge Queue
Routine merge command: `gh pr merge <PR> --squash --auto --delete-branch`
Do not use routine `--admin` merge
^## Background Commands
Long/background commands require monitor
foreground >10m review/test/gates need <=10m checkpoints
Follow `response-guard` recovery actions
^## Example SaaS-Specific Invariants
Every tenant-scoped endpoint must enforce tenant isolation.
""".strip().splitlines()


FORBIDDEN_RENDERED_ADAPTER_MARKERS = [
    "methodology-regression-rca.md",
    "Agent training default overrode methodology",
    "upper bound of 20 Markdown files",
    "Document Context Budget",
    "Verified Human Instructions",
]


def _assert_marker(content: str, marker: str, filename: str) -> None:
    if marker.startswith("^"):
        assert re.search(rf"^{re.escape(marker[1:])}", content, re.MULTILINE), (
            f"{filename} missing line-anchored generated adapter marker: {marker}"
        )
        return
    assert marker in content, f"{filename} missing generated adapter marker: {marker}"


def test_a_lane_with_no_board_pin_gets_no_identity_line(cli):
    """A lane with nothing to pin gets NO line rather than a line that guesses -- guessing is the
    failure this closes. Each of the three conditions is dropped independently, because a partial
    pin is exactly the state a guess would paper over."""
    base = cli.load_project(EXAMPLE_ADAPTER)

    for dropped in ("enabled", "owner", "projectNumber"):
        data = cli.load_project(EXAMPLE_ADAPTER)
        data["backlogProvider"][dropped] = False if dropped == "enabled" else type(
            base["backlogProvider"][dropped]
        )()
        files = cli.expected_files(data, str(EXAMPLE_ADAPTER))
        for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
            assert "Board pin:" not in files[filename], f"{filename} guessed with {dropped} unset"


PR_REFERENCE_MARKER = "- PR refs:"


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_render_adapters_refuses_to_overwrite_handwritten_markdown(tmp_path):
    target = tmp_path / "protected-render"
    target.mkdir()
    (target / "CLAUDE.md").write_text("hand-written Claude instructions\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("hand-written Codex instructions\n", encoding="utf-8")

    result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
    )

    assert result.returncode != 0
    assert "refusing to overwrite non-generated adapter markdown" in result.stderr
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "hand-written Claude instructions\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "hand-written Codex instructions\n"
    assert not (target / ".tautline.json").exists()


def test_render_adapters_json_only_preserves_handwritten_markdown(tmp_path):
    target = tmp_path / "protected-render"
    target.mkdir()
    (target / "CLAUDE.md").write_text("hand-written Claude instructions\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("hand-written Codex instructions\n", encoding="utf-8")

    write_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    check_json_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--check",
        "--json-only",
    )
    check_full_result = _run_cli(
        "render-adapters",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--check",
    )

    assert write_result.returncode == 0, write_result.stderr
    assert "wrote " in write_result.stdout
    assert (target / ".tautline.json").exists()
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "hand-written Claude instructions\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "hand-written Codex instructions\n"
    assert check_json_result.returncode == 0, check_json_result.stdout + check_json_result.stderr
    assert check_full_result.returncode == 1
    assert f"protected: {target / 'CLAUDE.md'}" in check_full_result.stdout
    assert f"protected: {target / 'AGENTS.md'}" in check_full_result.stdout


# --- item 37: the framework runs its own test-execution control -------------------------------


# The one junit report path on this repo. It used to be declared in the 1.x self-adapter
# (testEvidence.report.path) until the repo migrated to the lean profile, whose config
# deliberately has no such key -- but the path is still load-bearing: CI's evidence job copies
# exactly this file (.github/workflows/ci-python-full.yml and ci-python.yml both hardcode it).
JUNIT_REPORT_PATH = ".ai-runs/test-runs/latest-junit.xml"


def test_test_sh_emits_the_junit_report_ci_evidence_reads():
    """The path is only meaningful if the runner actually writes it AND the consumer reads the
    same one. Without this, test.sh could stop emitting (every run degrades to exit-code-only
    while CI still looks configured) or the workflow could drift to a path nothing produces --
    the declaration-instead-of-execution failure this control exists to end, kept after the
    adapter key that used to anchor it retired with the 1.x profile."""
    script = (REPO_ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")
    assert "--junitxml=" in script, "test.sh must emit a machine-readable report"
    assert JUNIT_REPORT_PATH in script, f"test.sh must write {JUNIT_REPORT_PATH}"

    for workflow in ("ci-python-full.yml", "ci-python.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert JUNIT_REPORT_PATH in text, (
            f"{workflow} must read the report test.sh writes ({JUNIT_REPORT_PATH})"
        )


# --- the rendered adapter may not instruct an agent to run a command that does not exist --------
#
# The 2026-08-28 process-bankruptcy demolition cut the CLI from 182 subcommands to 19 while the
# renderer still emitted a 206-line adapter naming 32 of the deleted ones -- step one of its
# Session Start was `lane-start`, which now errors. `adapter_drift` could not see it: it compares
# what is on disk against what the renderer produces, and both sides were equally stale, so drift
# reported "clean" over content that was wrong. Nothing else in the suite read the emitted text
# for verb validity.


def _registered_verbs() -> set[str]:
    """The verbs `tautline --help` actually offers, parsed from its own choices block."""
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "tautline"), "--help"],
        capture_output=True, text=True, check=False,
    ).stdout
    return {v.strip() for v in out.partition("{")[2].partition("}")[0].split(",") if v.strip()}


def _verbs_named_in(text: str) -> set[str]:
    """Every `tautline <verb>` the rendered text tells a reader to run."""
    return set(re.findall(r"\btautline\s+([a-z][a-z0-9-]+)", text))


def test_the_registered_verb_list_was_actually_read():
    """Discovery for the check below, asserted on its own.

    An empty or junk parse would make the verb check pass by comparing against nothing, and would
    look exactly like a clean render.
    """
    verbs = _registered_verbs()
    assert "render-adapters" in verbs and "version" in verbs
    assert 5 < len(verbs) < 60, f"the --help choices parse returned {len(verbs)} entries"


def test_the_rendered_adapter_names_no_command_the_cli_refuses(cli):
    """Every verb the generated adapter instructs an agent to run must be a real subcommand."""
    data = cli.load_project(EXAMPLE_ADAPTER)
    rendered = cli.expected_files(data, str(EXAMPLE_ADAPTER))
    registered = _registered_verbs()

    checked = 0
    for name, text in rendered.items():
        if not name.endswith(".md"):
            continue
        checked += 1
        dead = sorted(_verbs_named_in(text) - registered)
        assert not dead, (
            f"{name} tells an agent to run {dead}, which `tautline` refuses with 'invalid choice'. "
            "The renderer must not document commands the CLI does not have."
        )
    assert checked == len(cli.GENERATED_MARKDOWN_FILES), (
        f"only {checked} generated markdown file(s) were checked; the loop is skipping targets"
    )


def test_the_verb_scan_would_catch_a_dead_command():
    """The checking layer, proven against a planted defect.

    Without this, a scan whose regex stopped matching would report every adapter clean forever --
    the failure mode the demolition itself demonstrated.
    """
    planted = "Run `tautline lane-start --target .` first.\n"
    assert _verbs_named_in(planted) == {"lane-start"}
    assert "lane-start" not in _registered_verbs()
