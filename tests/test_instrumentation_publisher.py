"""T5 publisher tests. Starts from the pure security keystones (archive-path derivation and its
binding to record fields) before the git push path. The archive path is derived ONLY from validated
record fields, uses a colon-free UTC stamp (so the branch checks out on Windows/NTFS), and the
`-<end_seq>` suffix makes rapid same-second publishes collision-free -- see the plan's "Remote
metadata is constant" and "Window semantics" sections."""


def _record(**overrides):
    record = {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "9f2c4a1b0e7d5c3a",
        "plugin_version": "0.9.0",
        "window_seconds": 5400,
        "window_gap": False,
        "end_seq": 12,
        "events": [{"code": "startup", "count": 1}],
    }
    record.update(overrides)
    return record


def test_archive_relpath_derives_colon_free_stamp_and_end_seq_suffix(cli):
    path = cli.instrumentation_archive_relpath(_record())
    assert path == "telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-12.json"


def test_archive_relpath_truncates_fractional_seconds_to_seconds_precision(cli):
    # emitted_at may carry fractional seconds (schema allows .\d{1,6}); the filename stamp is
    # seconds-precision UTC, and the end_seq suffix -- not sub-second time -- disambiguates
    # same-second publishes.
    path = cli.instrumentation_archive_relpath(_record(emitted_at="2026-07-10T12:00:00.517432+00:00", end_seq=3))
    assert path == "telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-3.json"


def test_archive_relpath_two_same_second_records_differ_only_by_end_seq(cli):
    a = cli.instrumentation_archive_relpath(_record(end_seq=7))
    b = cli.instrumentation_archive_relpath(_record(end_seq=8))
    assert a != b
    assert a.endswith("-7.json") and b.endswith("-8.json")


# --- path-binding hygiene keystone: a blob's full path must equal what its own fields derive ------


def test_path_matches_record_true_for_self_derived_path(cli):
    record = _record()
    assert cli.instrumentation_archive_path_matches_record(cli.instrumentation_archive_relpath(record), record)


def test_path_matches_record_false_when_blob_moved_under_another_lane(cli):
    # A conforming blob for lane A physically placed under lane B's directory: the path's lane_id
    # no longer matches the blob's own lane_id, so it cannot forge lane B's remote_max.
    record = _record(lane_id="9f2c4a1b0e7d5c3a")
    moved = "telemetry/00000000deadbeef/20260710T120000Z-12.json"
    assert not cli.instrumentation_archive_path_matches_record(moved, record)


def test_path_matches_record_false_when_stamp_renamed(cli):
    record = _record()
    renamed = "telemetry/9f2c4a1b0e7d5c3a/20991231T235959Z-12.json"
    assert not cli.instrumentation_archive_path_matches_record(renamed, record)


def test_path_matches_record_false_when_end_seq_suffix_forged(cli):
    record = _record(end_seq=12)
    forged = "telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-999.json"
    assert not cli.instrumentation_archive_path_matches_record(forged, record)


# --- blob hygiene: a committed blob must be a KNOWN-version conforming record bound to its path ----


def _blob(**overrides):
    import json

    # Match instrumentation_record_blob_text(): archived blobs are byte-canonical (indent=2,
    # sort_keys) so hygiene's canonical-byte gate accepts a real publisher-written blob.
    return json.dumps(_record(**overrides), indent=2, sort_keys=True) + "\n"


def test_blob_hygiene_accepts_conforming_record_at_its_own_path(cli):
    relpath = cli.instrumentation_archive_relpath(_record())
    assert cli.instrumentation_blob_hygiene_errors(relpath, _blob()) == []


def test_blob_hygiene_rejects_nonconforming_json(cli):
    errors = cli.instrumentation_blob_hygiene_errors("telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-12.json", "{not json")
    assert errors and any("nonconforming" in e.lower() or "json" in e.lower() for e in errors)


def test_blob_hygiene_rejects_unknown_schema_version_fail_closed(cli):
    # A v2-labeled blob could carry freeform data through a grammar-only check; an older publisher
    # must FAIL CLOSED (upgrade-your-framework), never pass it on the strength of syntax alone.
    relpath = cli.instrumentation_archive_relpath(_record())
    errors = cli.instrumentation_blob_hygiene_errors(relpath, _blob(schema="tautline-instrumentation/v2"))
    assert errors and any("unknown" in e.lower() and "version" in e.lower() for e in errors)
    assert any("upgrade" in e.lower() for e in errors)


def test_blob_hygiene_rejects_freeform_extra_field(cli):
    import json

    record = _record()
    record["note"] = "customer ACME migration blocked on prod outage"  # freeform injection attempt
    relpath = cli.instrumentation_archive_relpath(_record())
    errors = cli.instrumentation_blob_hygiene_errors(relpath, json.dumps(record, sort_keys=True) + "\n")
    assert errors  # additionalProperties:false rejects it


def test_blob_hygiene_rejects_duplicate_key_blob_smuggling_freeform_text(cli):
    import json

    # A poisoned blob with a duplicate key: json.loads keeps only the LAST value, so the parsed
    # record is clean and passes schema + path binding, while the RAW bytes still carry the discarded
    # freeform product text. Hygiene must reject any blob whose raw bytes are not the exact canonical
    # serialization of the parsed record, so smuggled product text can never ride on the archive branch.
    raw = (
        "{\n"
        '  "plugin_version": "0.9.0 CUSTOMER-ACME-PROD-OUTAGE",\n'
        '  "emitted_at": "2026-07-10T12:00:00+00:00",\n'
        '  "end_seq": 12,\n'
        '  "events": [{"code": "startup", "count": 1}],\n'
        '  "lane_id": "9f2c4a1b0e7d5c3a",\n'
        '  "plugin_version": "0.9.0",\n'
        '  "schema": "tautline-instrumentation/v1",\n'
        '  "window_gap": false,\n'
        '  "window_seconds": 5400\n'
        "}\n"
    )
    assert "CUSTOMER-ACME" in raw  # the smuggled product text is physically in the blob bytes
    assert json.loads(raw)["plugin_version"] == "0.9.0"  # parse de-dups; schema + path checks pass
    errors = cli.instrumentation_blob_hygiene_errors("telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-12.json", raw)
    assert errors and any("canonical" in e.lower() for e in errors)


def test_blob_hygiene_rejects_blob_moved_under_another_lane(cli):
    # A conforming blob for lane A physically placed under lane B's directory must not validate:
    # its path lane_id no longer equals its own field, so it cannot forge lane B's remote_max.
    moved = "telemetry/00000000deadbeef/20260710T120000Z-12.json"
    errors = cli.instrumentation_blob_hygiene_errors(moved, _blob())
    assert errors and any("path" in e.lower() for e in errors)


def test_blob_hygiene_rejects_renamed_stamp(cli):
    renamed = "telemetry/9f2c4a1b0e7d5c3a/20991231T235959Z-12.json"
    errors = cli.instrumentation_blob_hygiene_errors(renamed, _blob())
    assert errors and any("path" in e.lower() for e in errors)


# --- commit-object closed-set parse: the final commit must contain ONLY pinned metadata ----------


def _commit_object(
    *,
    tree="4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    parents=(),
    author=None,
    committer=None,
    message=None,
    extra_headers=(),
):
    name = "tautline-telemetry"
    email = "telemetry@tautline.invalid"
    epoch = 1783684800  # 2026-07-10T12:00:00+00:00
    author = author or f"{name} <{email}> {epoch} +0000"
    committer = committer or f"{name} <{email}> {epoch} +0000"
    message = message if message is not None else "telemetry: instrumentation record"
    lines = [f"tree {tree}"]
    lines += [f"parent {p}" for p in parents]
    lines.append(f"author {author}")
    lines.append(f"committer {committer}")
    lines += list(extra_headers)
    lines.append("")
    lines.append(message)
    return "\n".join(lines) + "\n"


def test_commit_object_clean_for_pinned_metadata(cli):
    emitted_at = "2026-07-10T12:00:00+00:00"
    assert cli.instrumentation_commit_object_errors(_commit_object(), emitted_at=emitted_at) == []


def test_commit_object_clean_with_one_parent(cli):
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(parents=["a" * 40])
    assert cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at) == []


def test_commit_object_rejects_gpgsig_header(cli):
    # A user's signing config would add an identity-bearing gpgsig header block.
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(extra_headers=["gpgsig -----BEGIN PGP SIGNATURE-----"])
    errors = cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at)
    assert errors


def test_commit_object_rejects_nonconstant_author_identity(cli):
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(author="Acme Contributor <dev@example.invalid> 1783684800 +0000")
    errors = cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at)
    assert errors and any("author" in e.lower() for e in errors)


def test_commit_object_rejects_local_timezone_offset(cli):
    # Default commit dates embed the local timezone; the publisher pins +0000.
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(author="tautline-telemetry <telemetry@tautline.invalid> 1783684800 -0400")
    errors = cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at)
    assert errors


def test_commit_object_rejects_wrong_date_epoch(cli):
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(author="tautline-telemetry <telemetry@tautline.invalid> 1700000000 +0000")
    errors = cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at)
    assert errors


def test_commit_object_rejects_nonconstant_message(cli):
    emitted_at = "2026-07-10T12:00:00+00:00"
    raw = _commit_object(message="telemetry for customer ACME product work")
    errors = cli.instrumentation_commit_object_errors(raw, emitted_at=emitted_at)
    assert errors and any("message" in e.lower() for e in errors)


# --- newline/control-char slack: the stdlib validator's re.search anchors with `$`, which matches
# just before a trailing newline. A "...+00:00\n" emitted_at would otherwise pass the anchored
# pattern AND then crash datetime.fromisoformat in the path-binding walk (fail-closed -> DoS). The
# instrumentation record must reject any control character in any string field, categorically. ----


def test_record_errors_rejects_trailing_newline_in_emitted_at(cli):
    tainted = cli.instrumentation_record_errors(_record(emitted_at="2026-07-10T12:00:00+00:00\n"))
    assert tainted, "a trailing-newline emitted_at must be rejected, not slip past the anchored pattern"


def test_record_errors_rejects_embedded_control_char_in_any_string_field(cli):
    # lane_id is a fixed 16-hex token; an embedded NUL/newline has zero legitimate meaning.
    assert cli.instrumentation_record_errors(_record(lane_id="9f2c4a1b0e7d5c3a\x00"))
    assert cli.instrumentation_record_errors(_record(schema="tautline-instrumentation/v1\r"))


def test_record_errors_rejects_non_finite_numbers(cli):
    # window_seconds/total_seconds are JSON "number" fields: Python's parser accepts non-standard
    # NaN/Infinity, and every `minimum` comparison against NaN is false, so a non-finite value would
    # slip past the schema and then canonicalize into non-standard JSON. Reject it.
    assert cli.instrumentation_record_errors(_record(window_seconds=float("nan")))
    assert cli.instrumentation_record_errors(_record(window_seconds=float("inf")))


def test_blob_text_refuses_to_serialize_non_finite_number(cli):
    import pytest

    with pytest.raises(ValueError):
        cli.instrumentation_record_blob_text(_record(window_seconds=float("inf")))


def test_standalone_validator_rejects_duplicate_keys(cli, tmp_path):
    # The advertised `validate-instrumentation-record` must be as fail-closed on the raw bytes as the
    # archive hygiene walk: a duplicate-key file parses (json.loads keeps the last value) to a clean
    # record, but the raw bytes still carry the discarded product text, so the validator must reject it.
    import subprocess
    import sys
    from pathlib import Path

    poisoned = tmp_path / "poisoned.json"
    poisoned.write_text(
        "{\n"
        '  "plugin_version": "0.9.0 CUSTOMER-ACME-PROD-OUTAGE",\n'
        '  "emitted_at": "2026-07-10T12:00:00+00:00",\n'
        '  "end_seq": 12,\n'
        '  "events": [{"code": "startup", "count": 1}],\n'
        '  "lane_id": "9f2c4a1b0e7d5c3a",\n'
        '  "plugin_version": "0.9.0",\n'
        '  "schema": "tautline-instrumentation/v1",\n'
        '  "window_gap": false,\n'
        '  "window_seconds": 5400\n'
        "}\n",
        encoding="utf-8",
    )
    cli_path = Path(__file__).resolve().parents[1] / "bin" / "tautline"
    result = subprocess.run(
        [sys.executable, str(cli_path), "validate-instrumentation-record", "--file", str(poisoned)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "duplicate object key" in result.stderr


def test_blob_hygiene_fails_closed_on_newline_tainted_emitted_at_without_raising(cli):
    import json

    # A poisoned pre-existing blob whose emitted_at ends in a newline previously slipped past record
    # validation and then crashed the path-binding datetime.fromisoformat with an uncaught
    # ValueError, turning the whole-branch fail-closed hygiene walk into a telemetry DoS. Hygiene
    # must RETURN a rejection here, never raise.
    record = _record(emitted_at="2026-07-10T12:00:00+00:00\n")
    relpath = "telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-12.json"
    errors = cli.instrumentation_blob_hygiene_errors(relpath, json.dumps(record, sort_keys=True) + "\n")
    assert errors  # must not raise; must reject


# --- remote_max is history-wide, not tip-only (append-only telemetry bound) ---------------------


def test_remote_max_survives_a_descendant_commit_that_deletes_the_blob(cli, tmp_path):
    import json
    import subprocess

    repo = tmp_path / "archive"
    repo.mkdir()

    def g(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    g("init", "-q", "-b", cli.INSTRUMENTATION_ARCHIVE_BRANCH)
    g("config", "user.email", "telemetry@tautline.invalid")
    g("config", "user.name", "tautline-telemetry")
    rel = "telemetry/9f2c4a1b0e7d5c3a/20260710T120000Z-12.json"
    blob = repo / rel
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_text(json.dumps(_record(end_seq=12), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-q", "-m", "seq 12")
    assert cli.instrumentation_remote_max_for_lane(repo, "HEAD", "9f2c4a1b0e7d5c3a") == 12

    # A normal DESCENDANT commit deletes the telemetry blob (ancestry + hygiene both still pass since
    # the remaining tree conforms). remote_max must stay 12 -- computed across reachable history --
    # so the next publish cannot lower its bound and re-aggregate the already-published window.
    g("rm", "-q", rel)
    g("commit", "-q", "-m", "delete")
    assert cli.instrumentation_remote_max_for_lane(repo, "HEAD", "9f2c4a1b0e7d5c3a") == 12


def test_remote_max_fails_closed_on_git_error(cli, tmp_path):
    # A git failure (here: not a git repo) must return None so the publisher ABORTS, never 0 -- a
    # silent 0 would treat every retained event as unpublished and republish already-published windows.
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    assert cli.instrumentation_remote_max_for_lane(not_a_repo, "HEAD", "9f2c4a1b0e7d5c3a") is None


# --- branch-tip ancestry guard (force-push / rewind defense) ------------------------------------


def _ancestry_repo(tmp_path, cli):
    import subprocess

    repo = tmp_path / "ancestry"
    repo.mkdir()

    def g(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    g("init", "-q", "-b", "main")
    g("config", "user.email", "fw@example.invalid")
    g("config", "user.name", "Framework Checkout")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-q", "-m", "c1")
    c1 = g("rev-parse", "HEAD")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-q", "-m", "c2")
    c2 = g("rev-parse", "HEAD")
    return repo, c1, c2, g


def test_ancestry_guard_adopts_baseline_when_none_seen(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo, c1, _c2, _g = _ancestry_repo(tmp_path, cli)
    remote = "https://telemetry.invalid/archive.git"
    assert cli.read_instrumentation_ancestry_tip(remote) is None
    # No baseline -> adopt the fetched tip, no violation.
    assert cli.instrumentation_ancestry_guard_error(repo, remote, c1) is None


def test_ancestry_guard_passes_when_fetched_tip_descends_from_last_seen(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo, c1, c2, _g = _ancestry_repo(tmp_path, cli)
    remote = "https://telemetry.invalid/archive.git"
    cli.write_instrumentation_ancestry_tip(remote, c1)
    assert cli.read_instrumentation_ancestry_tip(remote) == c1
    # c2 descends from c1 (fast-forward advance) -> allowed.
    assert cli.instrumentation_ancestry_guard_error(repo, remote, c2) is None


def test_ancestry_guard_rejects_rewind_that_drops_last_seen_tip(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo, c1, c2, g = _ancestry_repo(tmp_path, cli)
    remote = "https://telemetry.invalid/archive.git"
    # We last saw c2. Now the branch is force-rewound onto a DIVERGENT history that does not contain
    # c2 as an ancestor (a rewind that would cement deletion of published telemetry).
    g("checkout", "-q", "-b", "rewound", c1)
    (repo / "divergent.txt").write_text("divergent\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-q", "-m", "divergent")
    rewound_tip = g("rev-parse", "HEAD")
    cli.write_instrumentation_ancestry_tip(remote, c2)
    error = cli.instrumentation_ancestry_guard_error(repo, remote, rewound_tip)
    assert error and "ancestry" in error.lower()
