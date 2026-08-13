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
Review target is 2 rounds; rounds 3-4 self-authorize with `--exception-note`
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


def test_example_saas_generated_adapter_contract(cli):
    adapter_path = EXAMPLE_ADAPTER
    data = cli.load_project(adapter_path)
    files = cli.expected_files(data, str(adapter_path))

    # Future runtime targets must intentionally satisfy this shared generated-adapter contract
    # or split out a narrower per-runtime contract instead of silently skipping coverage.
    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files[filename]
        assert len(content.encode()) <= MAX_EXAMPLE_SAAS_RENDERED_MARKDOWN_BYTES, filename
        for marker in REQUIRED_RENDERED_ADAPTER_MARKERS:
            _assert_marker(content, marker, filename)
        for marker in FORBIDDEN_RENDERED_ADAPTER_MARKERS:
            assert marker not in content, f"{filename} leaked generated adapter marker: {marker}"


def test_a_pinned_board_renders_its_identity_into_every_generated_adapter(cli):
    """Item 71 WS2 / RCA 2026-07-02: the board is resolved from an ADAPTER PIN, never from a
    projectsV2 discovery query. Discovery is what found the wrong board and then read it
    confidently, so the pin has to be visible in the authority document every lane loads."""
    data = cli.load_project(EXAMPLE_ADAPTER)
    provider = data["backlogProvider"]
    assert provider["enabled"] and provider["owner"] and provider["projectNumber"], (
        "this test is vacuous unless the example adapter actually pins a board"
    )
    files = cli.expected_files(data, str(EXAMPLE_ADAPTER))

    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files[filename]
        assert f"{provider['owner']}/projects/{provider['projectNumber']}" in content, filename
        assert "ad-hoc projectsV2 discovery is prohibited" in content, filename


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


def test_provider_backed_adapter_renders_pr_reference_contract(cli):
    """Item 101 rule 1-3: a board mirror reads PR text as its only evidence, so a pinned lane's
    authority document has to say what goes in a PR title and when a closing keyword is allowed.

    The POSITIVE half of the conditionality pair. Without it every assertion about this feature
    is of the form "the text does not appear", which a no-op render satisfies perfectly."""
    data = cli.load_project(EXAMPLE_ADAPTER)
    provider = data["backlogProvider"]
    assert provider["enabled"] and provider["owner"] and provider["projectNumber"], (
        "this test is vacuous unless the example adapter actually pins a board"
    )

    files = cli.expected_files(data, str(EXAMPLE_ADAPTER))

    # Both generated runtimes, because the line is wired into two separate render branches
    # (provider-item mode and goal orchestration) and a one-branch render is the defect this
    # catches -- it is exactly how item 71 WS4 shipped in a PR body but not in the tree.
    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        content = files[filename]
        assert PR_REFERENCE_MARKER in content, filename
        assert "ISSUE number in every PR title" in content, filename
        assert "an advancing PR carries no closing keyword" in content, filename
        assert "board-item-updates" in content, filename


def test_provider_item_completion_mode_also_renders_the_pr_reference_contract(cli):
    """The other render branch. `provider_item_mode` builds its own goal-orchestration block, so
    a line added to only one branch renders for half the adopters and nothing says so."""
    data = cli.load_project(EXAMPLE_ADAPTER)
    data["backlogProvider"]["completionUnit"] = "provider-item"
    assert cli.provider_item_completion_enabled(data), (
        "this test is vacuous unless the mutation actually selects provider-item mode"
    )

    files = cli.expected_files(data, str(EXAMPLE_ADAPTER))

    for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
        assert PR_REFERENCE_MARKER in files[filename], filename


def test_issueless_adapter_renders_byte_identical(cli, monkeypatch):
    """An adapter with no issue-backed backlog -- this framework's own shape -- must render
    BYTE-IDENTICALLY with and without item 101, and be unaffected by any future edit to the
    contract text. Tautline titles its PRs by component, not by issue number, and a rule rendered
    into a repo that does not use it is a rule its lanes learn to ignore.

    Proven by MUTATION, not by absence: the contract line is swapped for a sentinel of a very
    different length and the rendered bytes must be unchanged. A plain "the marker is absent"
    assertion cannot tell a correctly-gated render from a render that never happened, so it would
    stay green if the feature were deleted -- and it would also stay green if the gate were
    written as `enabled` alone, which is why each of the three predicates is dropped separately.
    """
    for dropped in ("enabled", "owner", "projectNumber"):
        data = cli.load_project(EXAMPLE_ADAPTER)
        original = data["backlogProvider"][dropped]
        data["backlogProvider"][dropped] = False if dropped == "enabled" else type(original)()

        baseline = cli.expected_files(data, str(EXAMPLE_ADAPTER))

        monkeypatch.setattr(
            cli,
            "PR_REFERENCE_ADAPTER_LINE",
            "- SENTINEL: this line must never reach an adapter with no issue-backed backlog,"
            " and it is deliberately much longer than the real one so any leak moves the byte"
            " count rather than merely changing its text.\n",
        )
        mutated = cli.expected_files(data, str(EXAMPLE_ADAPTER))

        for filename in sorted(cli.GENERATED_MARKDOWN_FILES):
            assert mutated[filename] == baseline[filename], (
                f"{filename} changed when the PR-reference line changed, with {dropped} unset: "
                "the line is not gated on all three provider-pin conditions"
            )
            assert PR_REFERENCE_MARKER not in baseline[filename], filename
            assert "SENTINEL" not in mutated[filename], filename


def test_board_item_updates_skill_states_pr_reference_contract():
    """The skill is where this item deliberately put the detail that does not fit the rendered
    byte corridor, so an unprotected skill surface is an unprotected half of the deliverable."""
    skill_root = REPO_ROOT / "plugins" / "tautline-core" / "skills" / "board-item-updates"
    text = (skill_root / "SKILL.md").read_text() + (
        skill_root / "references" / "board-item-updates-policy.md"
    ).read_text()

    for required in (
        "owner/repo#",
        "Fixes #",
        "advancing",
        "default branch",
    ):
        assert required in text, f"board-item-updates skill is missing: {required}"


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


def test_self_adapter_declares_test_evidence_report():
    """Dogfood: Tautline must be subject to the control it ships.

    A framework that adds a test-execution gate and then does not point it at its own suite is
    making exactly the declaration-instead-of-execution claim this feature exists to end. The
    source adapter declares the report, and the GENERATED adapter must carry it too -- `test-run`
    reads the generated file, and its `_generated.sourceAdapterSha256` is byte-compared against the
    source, so a source edit without a re-render fails before the key is ever read.
    """
    import json

    source = json.loads((REPO_ROOT / ".tautline" / "adapter.json").read_text(encoding="utf-8"))
    generated = json.loads((REPO_ROOT / ".tautline.json").read_text(encoding="utf-8"))

    for name, data in (("source", source), ("generated", generated)):
        report = (data.get("testEvidence") or {}).get("report")
        assert report, f"the {name} adapter must declare testEvidence.report"
        assert report["format"] == "junit-xml", name
        assert report["path"] == ".ai-runs/test-runs/latest-junit.xml", name

    assert (generated.get("_generated") or {}).get("sourceAdapterSha256"), (
        "the generated adapter must carry the source hash the dogfood run is checked against"
    )


def test_test_sh_emits_the_declared_junit_report():
    """The declared path is only meaningful if the runner actually writes it. Without this, the
    adapter could point at a file nothing ever produces and every run would degrade to
    exit-code-only while still looking configured."""
    import json

    script = (REPO_ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")
    declared = json.loads((REPO_ROOT / ".tautline.json").read_text(encoding="utf-8"))
    path = declared["testEvidence"]["report"]["path"]

    assert "--junitxml=" in script, "test.sh must emit a machine-readable report"
    assert path.split("/")[-1] in script, (
        f"test.sh must write the report the adapter declares ({path})"
    )
