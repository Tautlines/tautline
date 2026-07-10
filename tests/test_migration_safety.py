"""#12 destructive-migration gate.

The framework's only migration control is collision/ordering; destructiveness/reversibility is
ungoverned. A migration that DROPs a column or SET NOT NULL without a default can irreversibly destroy
live PII or break the prior-version app mid-rollout. A migration with un-guarded destructive DDL must
carry an explicit expand-contract acknowledgement marker (reviewed) or it is drift.
"""


def _mig(path="migrations", enforcement="block"):
    return {"migrationSafety": {"migrationsPath": path, "enforcement": enforcement}}


def test_destructive_findings(cli):
    assert "DROP COLUMN" in cli.destructive_sql_findings("ALTER TABLE t DROP COLUMN c;")
    assert "TRUNCATE" in cli.destructive_sql_findings("TRUNCATE users;")
    assert "DROP TABLE" in cli.destructive_sql_findings("drop table old_orders;")
    assert "SET NOT NULL" in cli.destructive_sql_findings("ALTER TABLE t ALTER COLUMN c SET NOT NULL;")
    assert cli.destructive_sql_findings("ALTER TABLE t ADD COLUMN c int;") == []


def test_findings_ignores_line_comments(cli):
    assert cli.destructive_sql_findings("-- DROP TABLE old;\nADD COLUMN x int;") == []


def test_unguarded_destructive_migration_flagged(cli, tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    (m / "0044.sql").write_text("ALTER TABLE orders DROP COLUMN legacy;")
    issues = cli.migration_safety_issues(_mig(), tmp_path)
    assert any("0044.sql" in i and "DROP COLUMN" in i for i in issues)


def test_acked_migration_allowed(cli, tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    (m / "0044.sql").write_text("-- MIGRATION-SAFETY-ACK: reviewed, column unused\nALTER TABLE orders DROP COLUMN legacy;")
    assert cli.migration_safety_issues(_mig(), tmp_path) == []


def test_no_migration_safety_is_silent(cli, tmp_path):
    assert cli.migration_safety_issues({}, tmp_path) == []


def test_normalize_migration_safety(cli):
    import pytest
    with pytest.raises(SystemExit):
        cli.normalize_migration_safety({"migrationSafety": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_migration_safety({"migrationSafety": {"migrationsPath": 5}})
    cfg = cli.normalize_migration_safety({"migrationSafety": {"migrationsPath": "m", "enforcement": "block"}})
    assert cfg["migrationsPath"] == "m" and cfg["enforcement"] == "block"
    assert cli.normalize_migration_safety({})["enforcement"] == "warn"
