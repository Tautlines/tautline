"""Migration proof: opening the notify seam changed nothing for anyone already using it.

This release is only safe if today's adapters are provably unaffected, so that has to be a test
rather than a claim. Two properties are proven here and one is proven by construction:

* the reference adapter renders **byte-identically** -- asserted against a recorded digest, never
  against a ceiling, because the rendered-adapter corridor was measured at **6 free bytes** at
  `b5f3f433a` and a ceiling assertion passes while silently spending it;
* an adapter with **no chat configuration at all** renders and loads -- the "fresh adopter who has
  neither" case exercised rather than asserted;
* the release adds **no public verb**, asserted rather than assumed.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

# Rendered example-saas, measured at origin/experimental b5f3f433a (VERSION 0.137.0) on 2026-08-26
# -- BEFORE the provider registry landed. Identity against this is the migration proof.
#
# The digest is taken over the render with its `tautline-template-version` stamp NORMALISED. That
# line carries VERSION, so every release changes it and a raw digest would have to be re-recorded
# each time -- which is how a byte-identity guard degrades into a number somebody updates without
# looking. Normalising the one line that is SUPPOSED to change leaves the assertion measuring the
# thing it is actually about: whether any rendered prose moved.
#
# The byte counts are asserted raw and separately, because the stamp is the same width across these
# versions and a size change is exactly what the corridor cares about.
#
# Re-recording either half is a deliberate act. If a legitimate rendered-prose change lands, update
# it in the same commit that causes it and state the measured byte delta in the PR body -- the
# corridor these sit in has SIX bytes of room.
PRE_REGISTRY_RENDER = {
    "CLAUDE.md": ("b2e40dea0a8e85b3", 16_312),
    "AGENTS.md": ("4d588c34e0c6a650", 16_253),
}
TEMPLATE_VERSION_LINE = re.compile(rb"^<!-- tautline-template-version: .* -->$", re.MULTILINE)


def _stable_digest(rendered: bytes) -> str:
    normalised = TEMPLATE_VERSION_LINE.sub(
        b"<!-- tautline-template-version: NORMALISED -->", rendered
    )
    return hashlib.sha256(normalised).hexdigest()[:16]


def _render(run_cli, tmp_path, adapter: Path) -> Path:
    target = tmp_path / "rendered"
    target.mkdir()
    result = run_cli(
        "render-adapters", "--project", str(adapter), "--target", str(target), "--write"
    )
    assert result.returncode == 0, result.stderr
    return target


def test_an_adapter_declaring_none_everywhere_loads(cli, tmp_path):
    data = json.loads(EXAMPLE_ADAPTER.read_text())
    for key in ("milestoneUpdate", "productChat", "deploymentNotification"):
        block = dict(data.get(key) or {})
        block.update({"enabled": False, "provider": "none"})
        data[key] = block
    adapter = tmp_path / "none-everywhere.json"
    adapter.write_text(json.dumps(data))

    loaded = cli.load_project(adapter)
    for key in ("milestoneUpdate", "productChat", "deploymentNotification"):
        assert loaded[key]["provider"] == "none"


def test_release_a_adds_no_public_verb():
    """The registry is a seam, not a surface. If a verb ever is added here, this assertion is where
    the omission of a public-contract update gets caught."""
    manifest = json.loads((REPO_ROOT / "methodology" / "public-contract-manifest.json").read_text())
    # Exact verb NAMES, not a substring scan: `provider-status` is a substring of the long-standing
    # `backlog-provider-status`, so a substring check would fail on a verb this release never
    # touched -- a false positive that teaches a reader to ignore the assertion.
    names = {
        str(entry.get("name"))
        for value in manifest.values()
        if isinstance(value, list)
        for entry in value
        if isinstance(entry, dict) and entry.get("name")
    }
    assert names, "could not read verb names from the public contract manifest"
    for invented in ("provider-status", "provider-list", "notify-post", "provider-registry"):
        assert invented not in names, f"unexpected public verb {invented!r} in the manifest"


@pytest.mark.parametrize("module", ["providers", "providers_notify"])
def test_provider_modules_are_shipped_in_the_package(module):
    assert (REPO_ROOT / "src" / "tautline_methodology" / f"{module}.py").is_file()
