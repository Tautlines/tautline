import json
from pathlib import Path

import pytest

from tautline_methodology import agent_compat

EXAMPLE_ADAPTER = (
    Path(__file__).resolve().parents[1] / "adapters" / "projects" / "example-saas.json"
)


def _legacy():
    return {
        "review": {
            "codexWrapper": "./scripts/codex-review.sh",
            "codexPlanWrapper": "./scripts/codex-review.sh",
            "codexFastMode": True,
            "claudeReview": "Use Claude Superpowers review if installed.",
            "crossModelTiming": "before-push",
        },
        "goalExecution": {
            "preferredClaudeCommand": "/goal",
            "claudeGoalGuidance": True,
        },
    }


def test_legacy_review_keys_synthesise_a_codex_agent_and_reviewer_roles():
    registry, roles, _notes = agent_compat.synthesise_agents(_legacy())
    assert registry["codex"]["vendor"] == "openai"
    assert registry["codex"]["runtime"] == "codex"
    assert registry["codex"]["instructionFile"] == "AGENTS.md"
    assert registry["codex"]["reviewWrapper"] == "./scripts/codex-review.sh"
    assert registry["codex"]["planReviewWrapper"] == "./scripts/codex-review.sh"
    assert registry["codex"]["fastMode"] is True
    assert roles["implementationReviewer"] == "codex"
    assert roles["planReviewer"] == "codex"


def test_claude_review_never_infers_the_planner():
    """`claudeReview` is schema-required review guidance on every legacy adapter. It says who
    REVIEWS, not who authored the plan. Inferring `planner` from it would make every legacy
    adapter claim Claude planned the work, so the plan-review vendor check would compare
    against a fabricated author and pass -- the fail-open the design says not to build."""
    _registry, roles, _notes = agent_compat.synthesise_agents(_legacy())
    assert "planner" not in roles
    assert roles["builder"] == "claude-code"


def test_claude_review_presence_infers_the_builder():
    registry, roles, _notes = agent_compat.synthesise_agents(_legacy())
    assert registry["claude-code"]["vendor"] == "anthropic"
    assert registry["claude-code"]["runtime"] == "claude-code"
    assert registry["claude-code"]["instructionFile"] == "CLAUDE.md"
    assert registry["claude-code"]["reviewGuidance"].startswith("Use Claude")
    assert registry["claude-code"]["goalCommand"] == "/goal"
    assert registry["claude-code"]["goalGuidance"] is True
    assert roles["builder"] == "claude-code"


def test_the_shim_seeds_the_legacy_codex_marker():
    """A legacy adapter's scan behaviour must be bit-for-bit what it is today."""
    assert agent_compat.LEGACY_AGENT_SEEDS["codex"]["transcriptMarker"] == "codex"
    registry, _roles, _notes = agent_compat.synthesise_agents(
        {"review": {"codexWrapper": "./scripts/codex-review.sh",
                    "crossModelTiming": "before-push"}}
    )
    assert registry["codex"]["transcriptMarker"] == "codex"


def test_timing_and_budget_keys_are_left_alone():
    """crossModelTiming, roundBudgets and prePushReviewEvidence carry no vendor name and
    are not the shim's business."""
    data = _legacy()
    data["review"]["roundBudgets"] = {"T2": 3}
    data["review"]["prePushReviewEvidence"] = True
    effective = agent_compat.effective_agents(data)
    assert effective["review"]["crossModelTiming"] == "before-push"
    assert effective["review"]["roundBudgets"] == {"T2": 3}
    assert effective["review"]["prePushReviewEvidence"] is True


def test_an_explicit_declaration_is_never_overwritten_by_inference():
    data = _legacy()
    data["agents"] = {
        "mistral-cli": {"vendor": "mistral", "runtime": "mistral-cli",
                        "instructionFile": "MISTRAL.md"},
    }
    data["roles"] = {"builder": "mistral-cli"}
    effective = agent_compat.effective_agents(data)
    bindings = agent_compat.merged_bindings(effective)
    assert bindings["builder"] == "mistral-cli"
    assert bindings["implementationReviewer"] == "codex"
    assert agent_compat.merged_registry(effective)["mistral-cli"]["vendor"] == "mistral"


def test_a_partially_migrated_agent_keeps_its_legacy_wrapper():
    """D3 is ADDITIVE migration, so the realistic intermediate state is an adapter that has
    begun declaring `agents.codex` while still carrying `review.codexWrapper`. Skipping the
    whole agent because its id appears would leave a registered reviewer with no wrapper,
    which is the half-migrated regression additive keys were chosen to avoid."""
    data = _legacy()
    data["agents"] = {
        "codex": {"vendor": "openai", "runtime": "codex", "instructionFile": "AGENTS.md"},
    }
    effective = agent_compat.effective_agents(data)
    record = agent_compat.merged_registry(effective)["codex"]
    assert record["vendor"] == "openai"
    assert record["reviewWrapper"] == "./scripts/codex-review.sh"
    assert record["fastMode"] is True


def test_a_declared_field_is_never_overwritten_by_its_legacy_twin():
    data = _legacy()
    data["agents"] = {
        "codex": {"vendor": "openai", "runtime": "codex", "instructionFile": "AGENTS.md",
                  "reviewWrapper": "./scripts/new-review.sh"},
    }
    effective = agent_compat.effective_agents(data)
    merged = agent_compat.merged_registry(effective)
    assert merged["codex"]["reviewWrapper"] == "./scripts/new-review.sh"


def test_a_fully_declared_adapter_gets_no_inference_at_all():
    data = {
        "agents": {
            "a": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md"},
            "b": {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "B.md"},
        },
        "roles": {"planner": "a", "planReviewer": "b",
                  "builder": "a", "implementationReviewer": "b"},
    }
    registry, roles, notes = agent_compat.synthesise_agents(data)
    assert registry == {}
    assert roles == {}
    assert notes == []


def test_sparse_legacy_keys_do_not_get_a_guessed_default():
    """An adapter too sparse to infer a seam author gets NO inferred role. The gate that needs
    it refuses with a remedy; it must never silently pass on a guess."""
    data = {"review": {"crossModelTiming": "before-push"}}
    registry, roles, _notes = agent_compat.synthesise_agents(data)
    assert registry == {}
    assert roles == {}


def test_the_shim_reports_every_inference_it_made():
    _registry, _roles, notes = agent_compat.synthesise_agents(_legacy())
    joined = "\n".join(notes)
    assert "review.codexWrapper" in joined
    assert "roles.implementationReviewer" in joined
    assert "review.claudeReview" in joined
    assert "roles.builder" in joined


def test_inferred_summary_survives_projection():
    """`methodology-status` runs AFTER the load-time projection. Recomputing there would find
    the gaps already filled and print nothing for exactly the legacy adapter whose guess the
    operator most needs to see."""
    projected = agent_compat.effective_agents(_legacy())
    lines = agent_compat.inferred_summary_lines(projected)
    assert lines, "the inference must survive projection"
    joined = "\n".join(lines)
    assert "roles.implementationReviewer = codex" in joined
    assert "roles.builder = claude-code" in joined


def test_opt_in_is_recorded_from_the_raw_declaration():
    """`effective_agents` fills agents/roles for a legacy adapter, so the projected dict LOOKS
    declared. Anything deriving opt-in from it would treat every legacy adapter as opted in."""
    projected = agent_compat.effective_agents(_legacy())
    assert agent_compat.merged_registry(projected), "precondition: the shim inferred a registry"
    assert "agents" not in projected, (
        "the inference must NOT be written into the mapping -- render-adapters would serialise "
        "a synthesised registry into a generated adapter the adopter never wrote"
    )
    assert projected.registry_opt_in is False


def test_a_declared_but_empty_roles_block_is_still_an_opt_in():
    """Presence, not truthiness: `"roles": {}` is a deliberate declaration."""
    assert agent_compat.effective_agents({"roles": {}}).registry_opt_in is True


def test_deprecation_warnings_name_the_removal_release():
    warnings = agent_compat.deprecation_warnings(_legacy())
    assert warnings
    assert all(agent_compat.REMOVAL_RELEASE in w for w in warnings)
    assert any("review.codexWrapper" in w for w in warnings)
    assert any("goalExecution.preferredClaudeCommand" in w for w in warnings)


def test_no_legacy_keys_means_no_deprecation_warnings():
    assert agent_compat.deprecation_warnings({"project": "x"}) == []


def test_effective_agents_does_not_mutate_the_input():
    data = _legacy()
    before = repr(data)
    agent_compat.effective_agents(data)
    assert repr(data) == before


def test_the_projected_adapter_still_validates_against_the_schema(run_cli, tmp_path):
    """Framework state must never ride inside a user-owned, schema-validated document."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    projected = agent_compat.effective_agents(data)
    assert projected.registry_opt_in is False
    path = tmp_path / "projected.json"
    path.write_text(json.dumps(projected, indent=2), encoding="utf-8")
    assert run_cli("validate-adapter", "--project", str(path)).returncode == 0


def test_the_inference_never_reaches_the_mapping():
    """The regression that made this design change: an earlier version merged the inference into
    the dict, and `render-adapters` serialised a whole synthesised `agents` block into the repo's
    own generated adapter -- breaking R1's inertness and turning a runtime convenience into
    content the adopter never wrote. Anything a serialiser can reach eventually gets serialised.
    """
    projected = agent_compat.effective_agents(_legacy())
    assert "agents" not in projected
    assert "roles" not in projected
    assert json.loads(json.dumps(projected)) == _legacy()


@pytest.mark.parametrize("bad", [[1, 2, 3], "oops", 7, None])
def test_the_shim_is_total_on_malformed_adapter_shapes(bad):
    """Every entry point hands this module whatever was on disk. Guarding at one call site
    leaves the next to rediscover the crash -- this lane already did that three times with a
    related boundary -- so the shim itself is total."""
    assert agent_compat.synthesise_agents(bad) == ({}, {}, [])
    projected = agent_compat.effective_agents(bad)
    assert agent_compat.merged_registry(projected) == {}
    assert agent_compat.merged_bindings(projected) == {}
    assert agent_compat.deprecation_warnings(bad) == []
    assert agent_compat.inferred_summary_lines(bad) == []


def test_a_non_object_agents_block_does_not_crash_the_shim():
    data = {"agents": "oops", "review": {"codexWrapper": "./scripts/codex-review.sh"}}
    registry, _roles, _notes = agent_compat.synthesise_agents(data)
    assert registry["codex"]["reviewWrapper"] == "./scripts/codex-review.sh"


def test_the_summary_prints_declared_values_not_the_legacy_seed():
    """Explicit-wins has to hold in what the operator SEES, not only in what resolves.

    A partially migrated adapter may declare `agents.codex` with its own vendor and runtime
    while still relying on `review.codexWrapper`. Printing the seed would show values that are
    not in force -- and since the whole point of this output is "see the guess and pin it",
    pinning what it printed must be a no-op.
    """
    data = _legacy()
    data["agents"] = {
        "codex": {"vendor": "openai-gov", "runtime": "codex-enterprise",
                  "instructionFile": "AGENTS.md"},
    }
    projected = agent_compat.effective_agents(data)
    joined = "\n".join(agent_compat.inferred_summary_lines(projected))
    assert "vendor=openai-gov" in joined
    assert "runtime=codex-enterprise" in joined
    assert "vendor=openai " not in joined and "runtime=codex " not in joined


def test_the_summary_marks_which_fields_were_inferred():
    """The operator needs to know which values came from a guess and which they wrote."""
    projected = agent_compat.effective_agents(_legacy())
    joined = "\n".join(agent_compat.inferred_summary_lines(projected))
    assert "vendor=openai (inferred)" in joined
    assert "runtime=codex (inferred)" in joined
