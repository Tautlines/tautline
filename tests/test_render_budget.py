"""cross-counterproductive-2 (productization): the generated-file size ceiling (previously a
hardcoded 15KB/31KB check in validate.sh) is now an adapter-tunable renderBudget enforced at render
time. Defaults match the old values; a project can raise/lower them or switch warn<->block.
"""


def test_default_budget(cli):
    b = cli.render_budget_for({})
    assert b == {"maxGeneratedBytes": 31000, "minGeneratedBytes": 15000, "enforcement": "warn"}


def test_adapter_overrides_budget(cli):
    b = cli.render_budget_for({"renderBudget": {"maxGeneratedBytes": 50000, "enforcement": "block"}})
    assert b["maxGeneratedBytes"] == 50000
    assert b["enforcement"] == "block"
    assert b["minGeneratedBytes"] == 15000  # unspecified keys keep the default


def test_over_budget_markdown_is_flagged(cli):
    expected = {"CLAUDE.md": "x" * 40000, ".minervit-ai-delivery.json": "{}"}
    errs = cli.render_budget_errors({}, expected)
    assert any("CLAUDE.md" in e and "over" in e for e in errs)


def test_under_budget_markdown_is_flagged(cli):
    expected = {"AGENTS.md": "x" * 100}
    errs = cli.render_budget_errors({}, expected)
    assert any("AGENTS.md" in e and "under" in e for e in errs)


def test_json_adapter_is_not_size_limited(cli):
    # A huge JSON adapter is fine; only the generated markdown is bounded.
    expected = {".minervit-ai-delivery.json": "x" * 99999}
    assert cli.render_budget_errors({}, expected) == []


def test_within_budget_passes(cli):
    expected = {"CLAUDE.md": "x" * 20000, "AGENTS.md": "y" * 20000}
    assert cli.render_budget_errors({}, expected) == []
