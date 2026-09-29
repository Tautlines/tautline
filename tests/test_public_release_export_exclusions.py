"""The public export's internal-doc exclusion, kept from the retired release-change contract.

`tests/test_release_change_contract.py` enforced the per-PR VERSION-bump rule -- KILL item 5 of the
2026-08-28 process-bankruptcy demolition. By the time it was removed, every rule it described lived
ONLY in that file: `merge_gate.py` was gone, no workflow referenced it, and its helpers were
test-local, so it had become a simulation of a gate rather than a check on one.

Exactly one assertion in it was about live behaviour: that `docs/superpowers/` is excluded from the
public release export. That is a security-adjacent property on a KEEP surface, so it moves here
rather than dying with its host. Version CONSISTENCY (VERSION == the plugin manifests) is a
different guard and lives in tests/test_version_lockstep.py, untouched.
"""

_UNSHIPPED_INTERNAL_DOC_ROOT = "docs/superpowers/"


def test_superpowers_docs_are_export_excluded(cli):
    """Plans, specs and review ledgers must never reach an adopter.

    Keyed to the real export constant rather than a copy of it: if the public export ever starts
    shipping them, this fails and the exclusion has to be re-argued -- instead of silently growing
    into a hole over consumer-visible surface.
    """
    assert _UNSHIPPED_INTERNAL_DOC_ROOT in cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES


def test_the_export_exclusion_list_is_not_empty(cli):
    """Discovery, asserted separately: an empty prefix list would make the check above pass by
    matching nothing, and would look identical to a working one."""
    assert len(cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES) >= 1
