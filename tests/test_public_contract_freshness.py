"""Codex R2 P1: the committed public-contract manifest silently went stale across a
version bump because no test regenerates and compares it. Pin freshness here."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_contract_manifest_carries_current_version():
    manifest = json.loads((ROOT / "methodology" / "public-contract-manifest.json").read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert manifest["version"] == version


def test_public_contract_manifest_matches_a_fresh_regeneration(cli):
    """The committed manifest must be a faithful regeneration of the CURRENT classifier
    (public_contract_status_for_command) over the CURRENT registered verb set -- never
    hand-edited, never left stale after a classifier change.

    This is the invariant PR #624 broke: it hand-edited public-contract-manifest.json
    (stakeholder-question -> "experimental") without adding a matching entry to
    public_contract_status_for_command, so the committed file silently drifted from what
    regeneration actually produces. The version-only check above did not catch it -- the
    version field agreed while the command statuses didn't -- and the drift surfaced only when
    an unrelated PR's own regeneration (Track S1's) reverted the mismatched entries back to the
    classifier's honest "stable" default. Comparing the checked-in manifest against a live
    regeneration, for every registered command, catches that class of drift before it ships
    rather than after the next person's regen quietly "reverts" someone else's manual edit.
    """
    committed = json.loads((ROOT / "methodology" / "public-contract-manifest.json").read_text(encoding="utf-8"))
    fresh = cli.public_contract_manifest_data()
    committed_commands = {c["name"]: c for c in committed["commands"]}
    fresh_commands = {c["name"]: c for c in fresh["commands"]}
    # The narrower, actionable diagnostic for THIS bug class: which verb(s) disagree, and how.
    drifted = {
        name: {"committed": committed_commands.get(name), "fresh": fresh_commands[name]}
        for name in fresh_commands
        if committed_commands.get(name) != fresh_commands[name]
    }
    assert drifted == {}, f"committed manifest disagrees with a fresh regeneration: {drifted}"
    # The catch-all: every OTHER section (adapterKeys, generatedFiles, skills, policyModules,
    # semverPolicy, schema, version) can drift the same way and this is what would catch it.
    assert committed == fresh
