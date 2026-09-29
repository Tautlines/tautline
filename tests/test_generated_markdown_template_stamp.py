"""Item 69 / WS1: the generated Markdown adapters carry the template version that produced them.

The 2026-08-03 incident was a render performed by an OLDER pinned runtime silently overwriting
newer committed `CLAUDE.md` / `AGENTS.md`. Nothing in the render path compared versions because
nothing in the rendered Markdown carried one: `GENERATED_HEADER_TEMPLATE` is exactly
`<!-- GENERATED -->` and `is_methodology_generated_markdown` reads only that prefix.

Two constraints shape the stamp, and this suite pins both:

- **Line 1 stays byte-identical.** Every existing runtime classifies a generated file by reading
  `len(GENERATED_HEADER_TEMPLATE)` bytes; changing that first line would make every older runtime
  in the fleet treat these files as hand-written and refuse to touch them, permanently. The stamp
  goes on line 2.
- **The stamp is not content.** A version that advances on every release would re-dirty every
  lane's adapter on every release -- the mixed-mode churn ping-pong that
  `adapter_stamp_equivalent_content`
  was built to kill. So the stamp is equivalence-normalized on comparison, exactly like the JSON
  adapter's `_generated` provenance keys.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

SENTINEL_MTIME = 1_000_000_000  # any write after setup moves mtime far away from this


def _rendered_lane(cli, tmp_path):
    """A target whose generated files are freshly rendered -- the zero-drift baseline."""
    target = tmp_path / "lane"
    target.mkdir()
    data = cli.load_project(EXAMPLE_ADAPTER)
    project_arg, override = cli.expected_files_render_context(data, EXAMPLE_ADAPTER, target)
    for rel, content in cli.expected_files(data, project_arg, override, target).items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    assert cli.adapter_drift(data, EXAMPLE_ADAPTER, target) == []
    return data, target


def test_stamp_only_differences_compare_equal_and_content_differences_do_not(cli):
    """Item 2. Equivalence is CONTENT-scoped, and it fails closed on an unstamped document."""
    equivalent = cli.markdown_stamp_equivalent_content
    fresh = "<!-- GENERATED -->\n<!-- tautline-template-version: 0.43.0 -->\nbody\n"
    on_disk_older = "<!-- GENERATED -->\n<!-- tautline-template-version: 0.41.0 -->\nbody\n"
    on_disk_changed = "<!-- GENERATED -->\n<!-- tautline-template-version: 0.41.0 -->\nDIFFERENT\n"
    unstamped = "<!-- GENERATED -->\nbody\n"

    # Stamp-only difference: normalizes to the on-disk stamp, so the byte comparison passes.
    assert equivalent(fresh, on_disk_older) == on_disk_older
    # Real content difference still gates.
    assert equivalent(fresh, on_disk_changed) != on_disk_changed
    # Fail closed: an unstamped on-disk document gets NO normalization, so the write proceeds and
    # today's fleet upgrades into the stamp instead of being frozen out of it.
    assert equivalent(fresh, unstamped) == fresh


def test_version_comparison_pads_before_comparing(cli):
    """`util.version_tuple` compares by LENGTH, so `0.42` would sort below `0.42.0` unpadded.

    Unpadded, a runtime at `0.42` reading a `0.42.0` stamp would refuse its own render as a
    downgrade -- a false refusal on the lane-startup boundary, which is the one failure mode this
    control cannot afford.
    """
    stamped = "<!-- GENERATED -->\n<!-- tautline-template-version: {v} -->\nbody\n"

    assert cli.markdown_render_is_downgrade(stamped.format(v="0.42.0"), "0.42") is False
    assert cli.markdown_render_is_downgrade(stamped.format(v="0.42"), "0.42.0") is False
    assert cli.markdown_render_is_downgrade(stamped.format(v="0.43.0"), "0.42.0") is True
    assert cli.markdown_render_is_downgrade(stamped.format(v="0.42.0"), "0.43.0") is False
    # Legacy unstamped: no stamp, no gate. The upgrade path must never be blocked on a stamp that
    # does not exist yet -- that is the entire installed fleet on the day this ships.
    assert cli.markdown_render_is_downgrade("<!-- GENERATED -->\nbody\n", "0.1.0") is False
