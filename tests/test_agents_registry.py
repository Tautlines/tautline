import pytest

from tautline_methodology import agents


def _adapter(**overrides):
    data = {
        "agents": {
            "claude-code": {
                "vendor": "anthropic",
                "runtime": "claude-code",
                "instructionFile": "CLAUDE.md",
            },
            "codex": {
                "vendor": "openai",
                "runtime": "codex",
                "instructionFile": "AGENTS.md",
            },
        },
        "roles": {
            "planner": "claude-code",
            "planReviewer": "codex",
            "builder": "claude-code",
            "implementationReviewer": "codex",
        },
    }
    data.update(overrides)
    return data


def test_role_names_are_the_four_seams():
    assert agents.ROLE_NAMES == (
        "planner",
        "planReviewer",
        "builder",
        "implementationReviewer",
    )


def test_role_resolves_through_the_registry():
    data = _adapter()
    assert agents.role_agent_id(data, "implementationReviewer") == "codex"
    assert agents.role_agent(data, "implementationReviewer")["runtime"] == "codex"
    assert agents.role_vendor(data, "implementationReviewer") == "openai"
    assert agents.role_vendor(data, "builder") == "anthropic"


def test_unbound_role_resolves_to_none_rather_than_a_default():
    data = _adapter(roles={"builder": "claude-code"})
    assert agents.role_agent_id(data, "implementationReviewer") is None
    assert agents.role_vendor(data, "implementationReviewer") is None


def test_role_naming_an_unregistered_agent_is_a_validation_error():
    data = _adapter(roles={"builder": "claude-code", "implementationReviewer": "gpt-9"})
    errors = agents.agents_registry_errors(data)
    assert any("gpt-9" in e for e in errors), errors
    assert any("claude-code" in e and "codex" in e for e in errors), errors


def test_registered_agent_missing_a_required_field_is_a_validation_error():
    data = _adapter()
    del data["agents"]["codex"]["vendor"]
    errors = agents.agents_registry_errors(data)
    assert any("codex" in e and "vendor" in e for e in errors), errors


@pytest.mark.parametrize("field", ["vendor", "runtime", "instructionFile"])
def test_every_required_field_is_checked(field):
    data = _adapter()
    del data["agents"]["claude-code"][field]
    errors = agents.agents_registry_errors(data)
    assert any("claude-code" in e and field in e for e in errors), errors


def test_two_agents_may_share_a_vendor():
    """Two OpenAI harnesses is legal. The vendor-difference gate catches the ROLE PAIR at
    review time; registering them is not itself an error."""
    data = _adapter()
    data["agents"]["codex-cloud"] = {
        "vendor": "openai",
        "runtime": "codex-cloud",
        "instructionFile": "AGENTS2.md",
    }
    assert agents.agents_registry_errors(data) == []


def test_two_agents_may_share_a_runtime():
    """Two models on Claude Code is legal -- vendor and runtime are separate axes."""
    data = _adapter()
    data["agents"]["claude-code-haiku"] = {
        "vendor": "anthropic",
        "runtime": "claude-code",
        "instructionFile": "CLAUDE.md",
    }
    assert agents.agents_registry_errors(data) == []


def test_vendors_differing_only_in_case_or_whitespace_are_the_same_vendor():
    """Free-form is not uncanonicalised. "OpenAI" and " openai " are one provider, and a raw
    inequality would let `enforcement: block` pass a same-provider review as independent --
    losing exactly the property D1 asserts."""
    data = _adapter()
    data["agents"]["codex"]["vendor"] = "OpenAI"
    data["agents"]["codex-cloud"] = {
        "vendor": "  openai  ", "runtime": "codex-cloud", "instructionFile": "AGENTS2.md",
    }
    assert agents.role_vendor(data, "implementationReviewer") == "openai"
    assert agents.canonical_vendor("  OpenAI ") == agents.canonical_vendor("openai")


def test_a_whitespace_only_vendor_is_a_validation_error():
    data = _adapter()
    data["agents"]["codex"]["vendor"] = "   "
    errors = agents.agents_registry_errors(data)
    assert any("vendor" in e and "codex" in e for e in errors), errors


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "/abs", ".hidden?"])
def test_an_agent_id_that_is_not_a_safe_slug_is_rejected(bad_id):
    """The id becomes `<runsDir>/<agent-id>-fast-mode-bin/`. `../` in it writes outside the
    target."""
    data = _adapter()
    data["agents"][bad_id] = {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md"}
    errors = agents.agents_registry_errors(data)
    assert any(bad_id in e for e in errors), errors


@pytest.mark.parametrize("bad_path", ["../CLAUDE.md", "/etc/passwd", "sub/dir/CLAUDE.md", ".."])
def test_an_instruction_file_that_traverses_is_rejected(bad_path):
    data = _adapter()
    data["agents"]["claude-code"]["instructionFile"] = bad_path
    errors = agents.agents_registry_errors(data)
    assert any("instructionFile" in e for e in errors), errors


def test_a_plain_instruction_file_name_is_accepted():
    data = _adapter()
    data["agents"]["claude-code"]["instructionFile"] = "ACME.md"
    assert agents.agents_registry_errors(data) == []


def test_a_symlinked_instruction_file_is_caught_at_render_time(tmp_path):
    """The RESOLUTION half. `ACME.md` is syntactically clean, but if it already exists in the
    target as a symlink to somewhere else, writing it writes there. Validation cannot see the
    target; the renderer can, so the check lives with the layer that knows."""
    target = tmp_path / "lane"
    target.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    (target / "ACME.md").symlink_to(outside)
    assert agents._safe_instruction_file("ACME.md") is True
    assert agents.instruction_file_escapes_target(target, "ACME.md") is True


def test_a_plain_file_in_the_target_does_not_escape(tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    assert agents.instruction_file_escapes_target(target, "ACME.md") is False


def test_an_invented_vendor_on_an_invented_runtime_is_accepted():
    """THE load-bearing property. No enum, no allowlist, no known-vendor list."""
    data = {
        "agents": {
            "acme-bot": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "ACME.md"},
            "globex-bot": {"vendor": "globex", "runtime": "globex-tty",
                           "instructionFile": "GLOBEX.md"},
        },
        "roles": {
            "planner": "acme-bot",
            "planReviewer": "globex-bot",
            "builder": "acme-bot",
            "implementationReviewer": "globex-bot",
        },
    }
    assert agents.agents_registry_errors(data) == []
    assert agents.role_vendor(data, "implementationReviewer") == "globex"


def test_adapter_with_no_agents_block_produces_no_errors():
    """R1 is inert: a legacy adapter that declares nothing new is not newly invalid."""
    assert agents.agents_registry_errors({"project": "x"}) == []


def test_a_role_may_name_a_shim_synthesised_agent():
    """The additive partial-migration path D3 exists to support: an adapter declares
    `roles.implementationReviewer = "codex"` while still carrying `review.codexWrapper`, so the
    `codex` agent comes from the shim. Rejecting that would refuse the exact migration the shim
    was built to make possible."""
    from tautline_methodology import agent_compat

    data = agent_compat.effective_agents({
        "review": {"codexWrapper": "./scripts/codex-review.sh",
                   "claudeReview": "n/a", "crossModelTiming": "before-push"},
        "roles": {"implementationReviewer": "codex"},
    })
    assert agents.agents_registry_errors(data) == []
    assert agents.role_agent_id(data, "implementationReviewer") == "codex"
    assert agents.role_vendor(data, "implementationReviewer") == "openai"


def test_a_role_naming_nothing_at_all_is_still_rejected():
    """The relaxation is scoped: a role may name a synthesised agent, not an absent one."""
    from tautline_methodology import agent_compat

    data = agent_compat.effective_agents({
        "review": {"codexWrapper": "./scripts/codex-review.sh",
                   "claudeReview": "n/a", "crossModelTiming": "before-push"},
        "roles": {"implementationReviewer": "gpt-9"},
    })
    errors = agents.agents_registry_errors(data)
    assert any("gpt-9" in e for e in errors), errors


def test_a_malformed_declared_record_is_still_reported():
    """Records are still judged from the DECLARED block, so a real mistake in the adopter's own
    document is not hidden by the shim."""
    data = {"agents": {"acme-bot": {"runtime": "acme-shell", "instructionFile": "A.md"}}}
    errors = agents.agents_registry_errors(data)
    assert any("acme-bot" in e and "vendor" in e for e in errors), errors
