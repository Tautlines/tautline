# tests/_adapter_fixtures.py
"""Adapter fixtures for tests that drive real lane commands.

ONE module, because six test files need this and six copies is how five of them drift.
"""
import json
from pathlib import Path

EXAMPLE_ADAPTER = (
    Path(__file__).resolve().parents[1] / "adapters" / "projects" / "example-saas.json"
)


def write_trusted_adapter(lane, data):
    """Write an adapter where `lane_project()` will actually accept it.

    `require_source_adapter_for_target` trusts exactly three locations: a
    `<methodology_repo>/adapters/projects/*.json`, `MINERVIT_METHODOLOGY_ADAPTER_ROOT`, or the
    target's repo-local `.tautline/adapter.json`. An ad-hoc `lane/adapter.json` is refused BY
    NAME -- "Do not use ad hoc, copied, or generated lane-local adapter JSON" -- before the
    command reaches anything a seam test asserts.
    """
    path = lane / ".tautline" / "adapter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def example_overlay(**blocks):
    """The full `example-saas` adapter with `blocks` overlaid. Every lane command needs the
    full shape; `load_project()` refuses anything less."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data.update(blocks)
    return data
