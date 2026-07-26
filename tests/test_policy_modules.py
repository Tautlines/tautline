import re


def test_canonical_policy_matches_ordered_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()

    assert assembled == cli.CANONICAL_RULES.read_text(encoding="utf-8")
    assert assembled.startswith("<!-- GENERATED COMPATIBILITY SOURCE:")


def test_policy_module_manifest_shape(cli):
    manifest = cli.load_policy_modules_manifest()
    modules = manifest["modules"]

    assert manifest["generatedArtifact"] == "methodology/canonical-rules.md"
    assert manifest["generator"] == "minervit-methodology canonical-policy --write"
    assert modules[0] == "00-introduction.md"
    assert modules[-1] == "31-automation.md"
    assert len(modules) == len(set(modules))
    assert all((cli.POLICY_MODULES_DIR / module).exists() for module in modules)
    assert {path.name for path in cli.POLICY_MODULES_DIR.glob("*.md")} == set(modules)


def test_canonical_policy_command_is_stable(cli):
    manifest = cli.public_contract_manifest_data()
    commands = {item["name"]: item for item in manifest["commands"]}

    assert commands["canonical-policy"]["status"] == "stable"


def test_canonical_policy_command_check(run_cli):
    result = run_cli("canonical-policy", "--check")

    assert result.returncode == 0
    assert "canonical_policy_check: ok" in result.stdout


def test_policy_module_index_lists_manifest_modules(cli):
    index = cli.REPO_ROOT / "docs" / "reference" / "policy-module-index.md"
    text = index.read_text(encoding="utf-8")
    modules = cli.load_policy_modules_manifest()["modules"]
    linked_modules = set(re.findall(r"\.\./\.\./methodology/policy/([^)\s]+\.md)\)", text))

    assert linked_modules == set(modules)
    for module in modules:
        assert module in text


def test_canonical_policy_requires_proof_of_done_without_pending_tests(cli):
    assembled = cli.canonical_policy_text_from_modules()
    normalized = " ".join(assembled.split())

    assert "proof-of-done standard" in assembled
    assert "would make completion believable" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are gaps, not proof" in assembled
    assert "`@pending`/pending, skipped, disabled, quarantined, or wrong-target tests are not proof of completion" in normalized


def test_canonical_policy_size_ratchet(cli):
    assembled = cli.canonical_policy_text_from_modules()

    # Raised 60000 -> 60763 for the never-write-process-to-memory + intake-routing bullets in
    # 28-memory.md (2026-07-14 process-authority plan, Task 2), then 60763 -> 61093 for the
    # successor-plan sentence in 13-planning.md (same plan, Task 9), per the rough-edges
    # umbrella's shared-surface discipline: each lane raises the ratchet by its own measured
    # delta only. Raised 61093 -> 61900 for the three product-dev-mode standdown exception
    # bullets in 05-current-status-truth, 06a-stop-and-deferral-red-flags, and 20-background-work
    # (shepherding plan), then 61900 -> 62058 for the PM-surface VERSION-bump-exemption sentence
    # in 21-lane-lifecycle.md (classifier plan, T5), then 62058 -> 62626 for the PM-surface
    # pre-push review/CI exemption bullet in 17-review-before-push.md (this plan, T2). Raised
    # 62626 -> 63891 for the "## Unattended Operation" subsection in 03-autonomy.md (directive-core
    # plan, D4): the standing-autonomy-directive policy obligations (opt-out knob, durable record,
    # async operator-fork queue with hard-to-reverse fallback, guards-unchanged). Raised
    # 63891 -> 64262 for the plan-authoring standard bullet in 13-planning.md (2026-07-23
    # plan-authoring-standard plan, WS4): parallel-workstream shape, per-task model-tier tags,
    # embedded execution-autonomy contract, and the enforcement knob. Raised 64262 -> 64505
    # (Codex R1 P1): honest mechanical-enforcement scoping to the plan-review seam. Raised
    # 64505 -> 65077 (2026-07-23): the agent owns review AND merge -- deliver MERGED, never
    # hand a clean gate-green PR back for operator review/merge (Done = merged, not pushed).
    # Raised 65780 -> 66221 (2026-07-24, 0.20.0, item 26 key-with-title): the Delivery Summaries rule
    # requiring a bare item key (`FR-3`, `item 17`, a `METH-FU-...` slug) be followed by the
    # item's short title `KEY: <short title>` in human-facing output. Raised 66221 -> 66384
    # (2026-07-25, item 24 plan-review round advance gap): the convergence ladder now states that
    # the round-4 hard cap counts successful reviewer INVOCATIONS against one source plan rather
    # than `--round` labels. A lane that relabelled every round `R1` was getting unlimited rounds,
    # and a control nobody can read about is half a control -- the clause is the cheapest way to
    # say what the gate now enforces.
    # Raised 66384 -> 66843 (2026-07-26, item 27 session-start currency gate): the lane-currency
    # rule makes the agent, not the operator, responsible for lane freshness at session start --
    # attempt the printed remedy, and when it cannot complete, state the unresolved drift in your
    # own output rather than handing it back. Scoped to ownership plus disclosure and explicitly
    # NOT a precondition for responding, so it cannot become a session-start block.
    assert len(assembled.encode("utf-8")) <= 66843


def test_canonical_policy_keeps_ops_provider_detail_out_of_core_modules(cli):
    assembled = cli.canonical_policy_text_from_modules()
    forbidden = ("Google Chat", "S3", "CloudFront", "Baretail", "Drizzle")
    offenders = [term for term in forbidden if term in assembled]

    assert offenders == []
