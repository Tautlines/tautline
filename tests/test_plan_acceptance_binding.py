"""Quality rec #13: AC-to-test-id binding at plan finalization.

canonical-rules.md already declares that a plan with a "missing named test/gate" or "missing concrete
testable acceptance criterion" is a stub -- but nothing enforced the per-AC binding. This gate gives
Definition-of-Ready teeth: under planAcceptance.enforcement=block, plan-finalization-precheck fails any
acceptance criterion that names no executable test/scenario id, or that is parked behind @pending
(FM1: untestable AC; FM2: AC excluded from live coverage), so the gap cannot be baked in at story entry.
"""

import pytest

BOUND = """## Acceptance Criteria
- Guest can submit an order -> `test_guest_submit_order` (orders.feature: Scenario: guest checkout)
- Admin sees the new order -> covered by: test_admin_order_visible
"""

UNBOUND = """## Acceptance Criteria
- Guest can submit an order
- Admin sees the new order and gets a confirmation email
"""

PENDING = """## Acceptance Criteria
- Guest can submit an order -> test_guest_submit_order @pending (harness not wired)
"""

CFG_BLOCK = {"enforcement": "block", "acHeadings": ["acceptance criteria"]}


def test_normalize_plan_acceptance(cli):
    with pytest.raises(SystemExit):
        cli.normalize_plan_acceptance({"planAcceptance": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_plan_acceptance({"planAcceptance": {"acHeadings": "ac"}})
    cfg = cli.normalize_plan_acceptance({})
    assert cfg["enforcement"] == "off" and cfg["acHeadings"] == ["acceptance criteria"]
    cfg2 = cli.normalize_plan_acceptance({"planAcceptance": {"enforcement": "block", "acHeadings": ["AC", "Acceptance"]}})
    assert cfg2["acHeadings"] == ["ac", "acceptance"]
