"""T3: this repo ships a concrete docs/product/** PM surface.

Under this repo's own adapter, a branch diff of only docs/product/*.md is PM-surfaces-only
(review/CI-exempt), while any docs/superpowers/plans/*.md (a plan/methodology path) is NOT --
the loader accepts docs/product/** precisely because this repo's plan sourceOfTruth lives under
docs/superpowers/plans, not under docs/product.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_ADAPTER = REPO_ROOT / ".tautline" / "adapter.json"


def test_self_adapter_declares_docs_product_surface(cli):
    adapter = cli.load_project(SELF_ADAPTER)
    assert "docs/product/**" in adapter["productDevelopment"]["surfaces"]


def test_self_adapter_docs_product_exempt_but_plans_not(cli):
    adapter = cli.load_project(SELF_ADAPTER)
    classify = cli.changed_paths_are_pm_surfaces_only
    assert classify(["docs/product/README.md"], adapter) is True
    assert classify(["docs/product/backlog/item.md"], adapter) is True
    plan_path = "docs/superpowers/plans/2026-07-17-pm-surface-prepush.md"
    assert classify([plan_path], adapter) is False
    assert classify(["bin/tautline"], adapter) is False
    assert classify(["docs/product/README.md", "src/x.py"], adapter) is False
