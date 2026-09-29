"""#12 destructive-migration gate.

The framework's only migration control is collision/ordering; destructiveness/reversibility is
ungoverned. A migration that DROPs a column or SET NOT NULL without a default can irreversibly destroy
live PII or break the prior-version app mid-rollout. A migration with un-guarded destructive DDL must
carry an explicit expand-contract acknowledgement marker (reviewed) or it is drift.
"""


def _mig(path="migrations", enforcement="block"):
    return {"migrationSafety": {"migrationsPath": path, "enforcement": enforcement}}


def test_normalize_migration_safety(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_migration_safety({"migrationSafety": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_migration_safety({"migrationSafety": {"migrationsPath": 5}})
    cfg = cli.normalize_migration_safety({"migrationSafety": {"migrationsPath": "m", "enforcement": "block"}})
    assert cfg["migrationsPath"] == "m" and cfg["enforcement"] == "block"
    assert cli.normalize_migration_safety({})["enforcement"] == "warn"
