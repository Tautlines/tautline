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

import json
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


def test_the_implicit_path_refuses_a_downgrade_without_touching_a_byte(cli, tmp_path, capsys):
    """Item 4. lane-start's render NARRATES and no-ops; it must never fail lane-start.

    A machine on a stale pin still has to be able to start a lane, because starting one is how it
    runs the repin that is the actual remedy. A refusal that blocks startup would strand exactly
    the population it is trying to protect.
    """
    data, target = _rendered_lane(cli, tmp_path)
    newer = _stamp_markdown_from_the_future(cli, target)
    before = {dest: dest.read_bytes() for dest in newer}

    written, _skipped, downgraded = cli.write_generated_files(
        data, EXAMPLE_ADAPTER, target, trigger="lane-start"
    )

    assert sorted(downgraded) == sorted(newer)
    for dest, original in before.items():
        assert dest.read_bytes() == original, "a refused downgrade rewrote the file"
        assert dest.stat().st_mtime == SENTINEL_MTIME, "a refused downgrade touched mtime"
        assert dest not in written

    message = cli.generated_downgrade_refusal(newer[0], FUTURE_VERSION, cli.plugin_version())
    assert FUTURE_VERSION in message
    assert cli.plugin_version() in message
    # The remedy is a runnable command, and the residual is named rather than hidden: an agent that
    # hits a SAME-version content difference must not conclude "no downgrade happened".
    assert "tautline update-repin --channel experimental" in message
    assert "--allow-template-downgrade" in message
    assert "Equal-version renders from a different channel or snapshot are NOT detected" in message


def test_the_explicit_path_refuses_with_a_prefix_and_the_override_writes(
    cli, run_cli, tmp_path
):
    """Item 5. The FIRST-CLASS deliberate-Markdown-downgrade path is the hand-run verb.

    The refusal is PRINTED with a `render_adapters_error:` prefix rather than raised as a bare
    SystemExit, because the refusal inventory `test_refusal_continuations.py` walks is scoped to
    printed prefixes -- a bare SystemExit would make "that suite is green" true no matter what the
    message said.
    """
    _data, target = _rendered_lane(cli, tmp_path)
    _stamp_markdown_from_the_future(cli, target)

    refused = run_cli(
        "render-adapters", "--project", str(EXAMPLE_ADAPTER), "--target", str(target), "--write"
    )

    assert refused.returncode == 1
    assert "render_adapters_error: " in refused.stderr
    assert FUTURE_VERSION in refused.stderr
    assert "--allow-template-downgrade" in refused.stderr
    assert (
        cli.generated_markdown_template_version(
            (target / "CLAUDE.md").read_text(encoding="utf-8")
        )
        == FUTURE_VERSION
    ), "the refused render wrote anyway"

    allowed = run_cli(
        "render-adapters", "--project", str(EXAMPLE_ADAPTER), "--target", str(target),
        "--write", "--allow-template-downgrade",
    )

    assert allowed.returncode == 0, allowed.stderr
    assert "generated_downgrade_deliberate: " in allowed.stdout
    assert (
        cli.generated_markdown_template_version(
            (target / "CLAUDE.md").read_text(encoding="utf-8")
        )
        == cli.plugin_version()
    )

    # The flag is a real accepted argument on every mode, not just a string inside a message.
    parsed = run_cli(
        "render-adapters", "--project", str(EXAMPLE_ADAPTER), "--target", str(target),
        "--allow-template-downgrade", "--check",
    )
    assert parsed.returncode in (0, 1), parsed.stderr
    assert "unrecognized arguments" not in parsed.stderr


def test_legacy_unstamped_markdown_still_upgrades(cli, tmp_path):
    """Item 6. On the day this ships, the ENTIRE installed fleet is unstamped.

    Gating the upgrade on a stamp that does not exist yet would freeze every adopter out of the
    fix, so `no stamp` is the fail-open direction.
    """
    data, target = _rendered_lane(cli, tmp_path)
    claude = target / "CLAUDE.md"
    legacy = claude.read_text(encoding="utf-8").replace(
        f"<!-- tautline-template-version: {cli.plugin_version()} -->\n", ""
    )
    claude.write_text(legacy, encoding="utf-8")

    written, _skipped, downgraded = cli.write_generated_files(
        data, EXAMPLE_ADAPTER, target, trigger="lane-start"
    )

    assert downgraded == []
    assert claude in written
    assert cli.generated_markdown_template_version(
        claude.read_text(encoding="utf-8")
    ) == cli.plugin_version()


def test_the_json_twin_refuses_and_stamp_equivalence_still_wins_first(cli, tmp_path):
    """Item 7. The JSON adapter gets the same gate -- but ordering is load-bearing.

    Stamp equivalence short-circuits BEFORE the direction check. A foreign-stamped but
    content-identical adapter is the mixed-mode fleet's NORMAL state (a wheel and a checkout
    co-maintaining one project); checking direction first would turn all of it into refusals.
    """
    data, target = _rendered_lane(cli, tmp_path)
    lane_json = target / cli.LANE_ADAPTER_FILE

    # (a) content-identical, newer stamp -> equivalence wins, no refusal, no rewrite.
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    doc["_generated"]["pluginVersion"] = FUTURE_VERSION
    lane_json.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.utime(lane_json, (SENTINEL_MTIME, SENTINEL_MTIME))

    written, _skipped, downgraded = cli.write_generated_files(
        data, EXAMPLE_ADAPTER, target, trigger="lane-start"
    )
    assert downgraded == []
    assert lane_json not in written
    assert lane_json.stat().st_mtime == SENTINEL_MTIME

    # (b) newer stamp AND a real content difference -> a genuine downgrade, refused.
    doc = json.loads(lane_json.read_text(encoding="utf-8"))
    doc["_generated"]["pluginVersion"] = FUTURE_VERSION
    doc["project"] = "renamed-by-a-newer-template"
    lane_json.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = lane_json.read_bytes()

    _written, _skipped, downgraded = cli.write_generated_files(
        data, EXAMPLE_ADAPTER, target, trigger="lane-start"
    )
    assert lane_json in downgraded
    assert lane_json.read_bytes() == before


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


def test_a_stamp_skewed_lane_is_clean_on_every_read_path(cli, run_cli, tmp_path):
    """Item 9 -- THE GATING TEST. Drift is an integrity gate; a false positive here bricks lanes.

    Both directions of skew are checked because both occur in a mixed fleet, and because the read
    paths must stay direction-BLIND: they report content drift, they do not adjudicate downgrades.
    """
    data, target = _rendered_lane(cli, tmp_path)
    assert cli.adapter_drift(data, EXAMPLE_ADAPTER, target) == []

    for skew in (FUTURE_VERSION, "0.1.0"):
        for rel in sorted(cli.GENERATED_MARKDOWN_FILES):
            dest = target / rel
            dest.write_text(
                dest.read_text(encoding="utf-8").replace(
                    cli.GENERATED_TEMPLATE_VERSION_LINE.format(
                        version=cli.generated_markdown_template_version(
                            dest.read_text(encoding="utf-8")
                        )
                    ),
                    cli.GENERATED_TEMPLATE_VERSION_LINE.format(version=skew),
                ),
                encoding="utf-8",
            )

        assert cli.adapter_drift(data, EXAMPLE_ADAPTER, target) == [], (
            f"a stamp-only difference reported as drift at {skew}"
        )
        checked = run_cli(
            "render-adapters", "--project", str(EXAMPLE_ADAPTER), "--target", str(target),
            "--check",
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert "drift:" not in checked.stdout

    # And the normalization must not have blinded the gate: one byte of real content still drifts.
    claude = target / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8"
    )
    assert "CLAUDE.md" in cli.adapter_drift(data, EXAMPLE_ADAPTER, target)
