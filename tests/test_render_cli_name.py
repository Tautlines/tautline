from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_name_constant(cli):
    assert cli.CLI_NAME == "tautline"
    assert cli.LEGACY_CLI_NAME == "minervit-methodology"


def test_generated_wrapper_prefers_tautline_and_falls_back():
    # The emitted lane wrapper must resolve `tautline` first, `minervit-methodology` as fallback.
    # Post the package-split flip (roadmap #11): the wrapper-generating engine lives in cli.py.
    text = (ROOT / "src" / "tautline_methodology" / "cli.py").read_text()
    assert "command -v tautline" in text
    assert "command -v minervit-methodology" in text  # fallback retained


def test_legacy_cli_name_still_allowed_by_latest_code_guard(cli):
    # Existing lanes rendered before the rename still instruct `minervit-methodology <cmd>`;
    # the latest-code guard must keep releasing for them until the shim-removal cleanup.
    assert cli.latest_code_command_allowed("minervit-methodology latest-code-status --target . --write")
    assert cli.latest_code_command_allowed("tautline latest-code-status --target . --write")


def test_tautline_repo_alias_allowed_by_latest_code_guard(cli):
    # resolve_env honors TAUTLINE_-prefixed aliases, so the documented recovery form
    # with the aliased repo var must release the guard exactly like the legacy var.
    assert cli.latest_code_command_allowed("$TAUTLINE_METHODOLOGY_REPO/bin/tautline latest-code-status --target . --write")
    assert cli.latest_code_command_allowed("$MINERVIT_METHODOLOGY_REPO/bin/tautline latest-code-status --target . --write")


def test_product_claude_codex_review_line_includes_wrapper(run_cli, tmp_path):
    # The generated product CLAUDE.md told agents to run `codex-run --target .
    # --risk-tier T1 --review-round R1` with NO command after `--`, which errors
    # ("codex-run requires a command after --"); AGENTS.md and the adapter's
    # review.codexWrapper carry the wrapper, so the Claude line must too (found
    # live by a Codex round in a product lane on 0.8.4).
    target = tmp_path / "render-target"
    target.mkdir()
    res = run_cli(
        "render-adapters",
        "--project",
        "adapters/projects/example-saas.json",
        "--target",
        str(target),
        "--write",
    )
    assert res.returncode == 0, res.stderr
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(ln for ln in claude_md.splitlines() if ln.startswith("- Codex review:"))
    assert " -- " in line, line
    assert "codex-review.sh" in line or "codexWrapper" in line, line


def test_legacy_evidence_precheck_line_still_matches(cli):
    # Pre-0.8.0 plans embed `minervit-methodology plan-finalization-precheck ...`
    # in their template-generated Precheck evidence line; the regenerated
    # expectation uses the tautline name, so exact comparison rejected every
    # legitimately-reviewed legacy plan (found live: RM remediation plans).
    manifest = {
        "recorded_by": "minervit-methodology finalize-plan-review",
        "plan_content_sha256": "a" * 64,
        "reviewer": "codex",
        "reviewer_model": "codex-test",
        "round": "R1",
        "review_command": "./scripts/codex-review.sh --plan p.md",
        "log_path": "log.txt",
        "log_sha256": "b" * 64,
        "review_run_meta_path": "meta.json",
        "review_run_meta_sha256": "c" * 64,
        "verdict": "clean",
        "unresolved_critical_count": 0,
        "unresolved_p1_count": 0,
        "classified_findings": [],
        "plan_path": "docs/p.md",
    }
    expected = cli.plan_review_evidence_body(manifest, "m.json").strip()
    legacy = expected.replace(
        "`tautline plan-finalization-precheck",
        "`minervit-methodology plan-finalization-precheck",
    )
    assert legacy != expected
    assert cli.plan_review_evidence_section_matches(legacy, expected)
    assert cli.plan_review_evidence_section_matches(expected, expected)
    assert not cli.plan_review_evidence_section_matches(legacy.replace("`clean`", "`blocked`"), expected)
