
from tautline_methodology import cli


def _data(**agents_over):
    agents = {
        "acme-bot": {
            "vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md",
            "reviewWrapper": "./scripts/acme-review.sh --base origin/main",
            "planReviewWrapper": "./scripts/acme-plan.sh",
        },
    }
    agents.update(agents_over)
    return {
        "agents": agents,
        "roles": {"implementationReviewer": "acme-bot", "planReviewer": "acme-bot"},
    }


def test_the_vendor_named_helper_is_gone():
    assert not hasattr(cli, "command_matches_codex_wrapper")
