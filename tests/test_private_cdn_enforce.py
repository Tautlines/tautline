"""sec-privacy-3 (productization): when iterationReview.hosting.access is 'private-cdn', the upload
path verifies (warn-only) that the bucket blocks public access -- the field was validated but never
enforced. Warn-only so a perms gap never wedges delivery, but a public bucket is surfaced loudly.
"""

BLOCKED = (
    '{ "PublicAccessBlockConfiguration": { "BlockPublicAcls": true, "IgnorePublicAcls": true, '
    '"BlockPublicPolicy": true, "RestrictPublicBuckets": true } }'
)
OPEN = '{ "PublicAccessBlockConfiguration": { "BlockPublicAcls": false } }'


def test_non_private_access_is_noop(cli, capsys):
    cli.enforce_private_cdn_access({"hosting": {"access": "public"}}, "b", dry_run=False)
    assert capsys.readouterr().out == ""


def test_dry_run_is_noop(cli, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: called.append(a) or (0, BLOCKED, ""))
    cli.enforce_private_cdn_access({"hosting": {"access": "private-cdn"}}, "b", dry_run=True)
    assert not called, "dry-run must not call aws"


def test_blocked_bucket_prints_verified(cli, capsys, monkeypatch):
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (0, BLOCKED, ""))
    cli.enforce_private_cdn_access({"hosting": {"access": "private-cdn"}}, "b", dry_run=False)
    assert "private-cdn verified" in capsys.readouterr().out


def test_open_bucket_warns(cli, capsys, monkeypatch):
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (0, OPEN, ""))
    cli.enforce_private_cdn_access({"hosting": {"access": "private-cdn"}}, "mybucket", dry_run=False)
    err = capsys.readouterr().err
    assert "does not fully block public access" in err and "mybucket" in err


def test_unverifiable_bucket_warns_but_does_not_raise(cli, capsys, monkeypatch):
    monkeypatch.setattr(cli, "run_command", lambda *a, **k: (255, "", "AccessDenied"))
    cli.enforce_private_cdn_access({"hosting": {"access": "private-cdn"}}, "b", dry_run=False)
    assert "could not verify public-access-block" in capsys.readouterr().err
