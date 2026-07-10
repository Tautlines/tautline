"""sec-privacy-2 (productization): purge-archive is the GDPR/CCPA erasure path the framework
previously lacked — it removes one project's/tenant's artifacts from an archive dir and drops their
_index.md entries, without touching other tenants, and refuses to operate outside the archive dir.
"""


def _seed(archive):
    (archive / "acme" / "2026").mkdir(parents=True)
    (archive / "acme" / "2026" / "20260101T000000Z-lane-session-journal.md").write_text("acme journal")
    (archive / "globex" / "2026").mkdir(parents=True)
    (archive / "globex" / "2026" / "20260101T000000Z-lane-session-journal.md").write_text("globex journal")
    (archive / "_index.md").write_text(
        "# Archive\n\n## Artifacts\n\n"
        "- `acme/2026/20260101T000000Z-lane-session-journal.md` - Acme\n"
        "- `globex/2026/20260101T000000Z-lane-session-journal.md` - Globex\n"
    )


def test_purge_removes_only_target_tenant(run_cli, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _seed(archive)
    res = run_cli("purge-archive", "--project", "acme", "--archive-dir", str(archive))
    assert res.returncode == 0, res.stderr
    assert not (archive / "acme").exists(), "target tenant dir must be erased"
    assert (archive / "globex").exists(), "other tenant must be untouched"
    index = (archive / "_index.md").read_text()
    assert "acme/" not in index
    assert "globex/" in index


def test_purge_dry_run_changes_nothing(run_cli, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _seed(archive)
    res = run_cli("purge-archive", "--project", "acme", "--archive-dir", str(archive), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert (archive / "acme").exists(), "dry-run must not delete"
    assert "purge_archive_dry_run" in res.stdout
    assert "acme/" in (archive / "_index.md").read_text()


def test_purge_missing_archive_errors(run_cli, tmp_path):
    res = run_cli("purge-archive", "--project", "acme", "--archive-dir", str(tmp_path / "nope"))
    assert res.returncode != 0
    assert "archive dir not found" in res.stderr
