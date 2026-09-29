"""Item 69 / WS1: a render never silently rolls a generated adapter back to an older template.

READ THIS BEFORE CITING THESE TESTS AS INCIDENT CLOSURE. Every test here runs NEW code against a
SYNTHETIC stamp. They demonstrate that the control works; they do NOT demonstrate that the
2026-08-03 incident is unreproducible. That render was performed by an OLD pinned snapshot
runtime, and a refusal can only fire when the runtime doing the overwriting already contains it.
Machines still on a pin cut before this release remain exactly as exposed as they were; the fleet
repin in the post-release roll-forward runbook is the control for them, not this code.

The gating test in this file is the fleet-safety one at the bottom. A version-bearing header that
is not equivalence-normalized on the READ paths turns `adapter_drift` -- an INTEGRITY gate -- into
an unconditional failure on every lane whose runtime differs from the on-disk stamp, which would
arm startup remediation fleet-wide on the next release and again on the one after that. The stamp
is unshippable without it.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

FUTURE_VERSION = "99.0.0"
SENTINEL_MTIME = 1_000_000_000


def _rendered_lane(cli, tmp_path):
    target = tmp_path / "lane"
    target.mkdir()
    data = cli.load_project(EXAMPLE_ADAPTER)
    project_arg, override = cli.expected_files_render_context(data, EXAMPLE_ADAPTER, target)
    for rel, content in cli.expected_files(data, project_arg, override, target).items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return data, target


def _stamp_markdown_from_the_future(cli, target, *, with_content_change=True):
    """Make the on-disk Markdown look like a NEWER runtime rendered it."""
    changed = []
    for rel in sorted(cli.GENERATED_MARKDOWN_FILES):
        dest = target / rel
        text = dest.read_text(encoding="utf-8").replace(
            f"<!-- tautline-template-version: {cli.plugin_version()} -->",
            f"<!-- tautline-template-version: {FUTURE_VERSION} -->",
        )
        if with_content_change:
            text += "\n<!-- a section only the newer template renders -->\n"
        dest.write_text(text, encoding="utf-8")
        os.utime(dest, (SENTINEL_MTIME, SENTINEL_MTIME))
        changed.append(dest)
    return changed


def test_the_channel_switch_caller_downgrades_json_without_an_attribute_error(cli, tmp_path):
    """Item 8. The hand-built Namespace is the whole risk here.

    `write_framework_channel_to_adapter` builds an `argparse.Namespace` by hand and wraps the
    render in `except (OSError, SystemExit)` to restore the adapter. An `AttributeError` from a
    bare `args.allow_template_downgrade` read is neither of those: it escapes the handler and
    leaves the adapter half-switched -- new channel written, no render, no rollback. That is the
    only thing standing between a repin and a broken lane, so it gets a direct assertion.
    """
    import argparse

    _data, target = _rendered_lane(cli, tmp_path)

    # A Namespace built WITHOUT the new attribute, exactly as a pre-existing caller would.
    legacy_namespace = argparse.Namespace(
        project=EXAMPLE_ADAPTER, target=target, write=True, check=False, json_only=True
    )
    assert cli.render_adapters(legacy_namespace) == 0

    # json_only=True means selected_expected_files returns ONLY the lane adapter, so no Markdown
    # is rendered on this path at all -- assert that, rather than asserting Markdown behavior that
    # this caller can never reach.
    data = cli.load_project(EXAMPLE_ADAPTER)
    project_arg, override = cli.expected_files_render_context(data, EXAMPLE_ADAPTER, target)
    json_only_files = cli.selected_expected_files(data, project_arg, True, override, target)
    assert set(json_only_files) == {cli.LANE_ADAPTER_FILE}
