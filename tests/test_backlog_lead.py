"""RCA: every backlog item must LEAD with a plain-language business justification (what it delivers,
why it matters) before technical detail -- not a rote milestone restatement or pure technical detail.
"""

GOOD = (
    "## What this delivers\n"
    "Customers can reorder a past order in two taps from their order history.\n\n"
    "## Why it matters\n"
    "Reordering is the top requested feature and drives repeat purchases for busy regulars.\n\n"
    "## Technical detail\n"
    "Adds a reorder endpoint and history UI; see the repo plan.\n"
)


def test_compliant_item_passes(cli):
    assert cli.backlog_item_missing_business_lead(GOOD) == ""


def test_missing_what_is_flagged(cli):
    body = "## Why it matters\nCustomers care a lot about this outcome and ask for it often.\n"
    msg = cli.backlog_item_missing_business_lead(body)
    assert msg and "What this delivers" in msg


def test_missing_why_is_flagged(cli):
    body = "## What this delivers\nA new storefront pickup-time selector for customers to choose a slot.\n"
    msg = cli.backlog_item_missing_business_lead(body)
    assert msg and "Why it matters" in msg


def test_empty_or_technical_only_is_flagged(cli):
    assert cli.backlog_item_missing_business_lead("") != ""
    technical = "Add a Postgres column `reorder_token` and a migration; wire the API route.\n"
    assert cli.backlog_item_missing_business_lead(technical) != ""


def test_trivial_content_is_flagged(cli):
    body = "## What this delivers\nx\n\n## Why it matters\ny\n"
    assert cli.backlog_item_missing_business_lead(body) != ""


def test_synonym_headings_accepted(cli):
    body = (
        "## What is it\n"
        "A guest checkout flow so shoppers can buy without creating an account.\n\n"
        "## Why we care\n"
        "Account-creation friction is the biggest checkout drop-off for new customers.\n"
    )
    assert cli.backlog_item_missing_business_lead(body) == ""


def test_leading_with_technical_heading_is_flagged(cli):
    body = (
        "## Technical detail\n"
        "Implementation notes first.\n\n"
        "## What this delivers\n"
        "A capability described in enough words to pass the content length check here.\n\n"
        "## Why it matters\n"
        "It matters to customers for reasons described in enough words to pass the check.\n"
    )
    msg = cli.backlog_item_missing_business_lead(body)
    assert msg and "appears before" in msg


def test_business_section_after_technical_is_flagged(cli):
    # Codex P1: What -> Technical -> Why must fail (Why is after technical detail), not pass.
    body = (
        "## What this delivers\n"
        "Customers get a one-tap reorder described in enough words to pass the content check.\n\n"
        "## Technical detail\n"
        "Implementation notes in the middle.\n\n"
        "## Why it matters\n"
        "It drives repeat purchases for reasons described in enough words to pass the check.\n"
    )
    assert cli.backlog_item_missing_business_lead(body) != ""


def test_placeholder_content_is_flagged(cli):
    # Codex P2: >=24 chars of a single repeated token is not real plain-language content.
    body = (
        "## What this delivers\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n\n"
        "## Why it matters\nyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy\n"
    )
    assert cli.backlog_item_missing_business_lead(body) != ""


def test_deep_technical_heading_bounds_section(cli):
    # Codex P2: a ##### Technical heading must bound the prior section (not be swallowed into it).
    body = (
        "## What this delivers\nx\n"
        "##### Technical detail\n"
        "lots of technical words here that should not count toward the what section content length\n\n"
        "## Why it matters\n"
        "Real customer value described in enough distinct words to satisfy the content check here.\n"
    )
    # The What section is just 'x' (the ##### heading bounds it), so it must be flagged.
    assert cli.backlog_item_missing_business_lead(body) != ""


def test_leading_title_is_allowed_but_level1_section_is_not(cli):
    # A bare `# Title` before What/Why is fine (title); a `# <section>` with real body is not (Codex).
    titled = (
        "# Existing Repo Goal\n\n"
        "## What this delivers\nCustomers get one-tap reorder described in enough distinct words here.\n\n"
        "## Why it matters\nIt drives repeat purchases for reasons described in enough distinct words here.\n"
    )
    assert cli.backlog_item_missing_business_lead(titled) == ""
    level1_section = (
        "# Technical approach\nChange the validator ordering logic and regex behavior substantially.\n\n"
        "## What this delivers\nCustomers get one-tap reorder described in enough distinct words here.\n\n"
        "## Why it matters\nIt drives repeat purchases for reasons described in enough distinct words here.\n"
    )
    assert cli.backlog_item_missing_business_lead(level1_section) != ""


def test_board_lead_gaps_noop_when_provider_disabled(cli, tmp_path):
    data = {"goalTracker": {"enabled": False}, "backlogProvider": {"enabled": False}}
    assert cli.provider_board_business_lead_gaps(data, tmp_path) == []
