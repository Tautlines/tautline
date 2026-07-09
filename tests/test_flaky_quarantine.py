"""Quality rec #14: quarantine/flaky forcing-function.

A test marked @flaky/skip/xfail that nobody owns is silent gate erosion (FM2): the suite stays green
while real coverage rots. This gate fails a diff that ADDS a quarantine marker without recording an
owner + a due/issue/trigger in the same hunk, and (opt-in) enforces a repo-wide marker ratchet that can
only be lowered. Flaky tests become tracked debt, not a quiet hole in the gate.
"""

import argparse

import pytest

ADD_UNOWNED = """diff --git a/tests/test_orders.py b/tests/test_orders.py
--- a/tests/test_orders.py
+++ b/tests/test_orders.py
@@ -10,0 +11,2 @@
+    @pytest.mark.skip
+    def test_guest_checkout(self):
"""

ADD_OWNED = """diff --git a/tests/test_orders.py b/tests/test_orders.py
--- a/tests/test_orders.py
+++ b/tests/test_orders.py
@@ -10,0 +11,3 @@
+    # owner: alice  due: 2026-07-01  trigger: re-enable when payment sandbox is stable (#812)
+    @pytest.mark.skip(reason="payment sandbox flaky")
+    def test_guest_checkout(self):
"""

ADD_JS = """diff --git a/src/login.test.ts b/src/login.test.ts
--- a/src/login.test.ts
+++ b/src/login.test.ts
@@ -3,0 +4,1 @@
+  it.skip("logs in", () => {})
"""

NO_MARKER = """diff --git a/tests/test_orders.py b/tests/test_orders.py
--- a/tests/test_orders.py
+++ b/tests/test_orders.py
@@ -10,0 +11,1 @@
+    def test_guest_checkout(self):
"""

MARKERS = None  # use defaults


def _markers(cli):
    return list(cli.FLAKY_QUARANTINE_MARKERS)


def _ns(**kw):
    base = dict(project=None, target=None, base=None, diff_file=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_unowned_marker_flagged(cli):
    issues = cli.flaky_quarantine_diff_issues(ADD_UNOWNED, _markers(cli))
    assert len(issues) == 1
    assert "owner" in issues[0] and "due/issue/trigger" in issues[0]


def test_owned_marker_allowed(cli):
    assert cli.flaky_quarantine_diff_issues(ADD_OWNED, _markers(cli)) == []


def test_js_skip_flagged(cli):
    issues = cli.flaky_quarantine_diff_issues(ADD_JS, _markers(cli))
    assert len(issues) == 1 and "it.skip(" in issues[0]


def test_no_marker_no_issue(cli):
    assert cli.flaky_quarantine_diff_issues(NO_MARKER, _markers(cli)) == []


def test_parse_diff_added_hunks(cli):
    hunks = cli.parse_diff_added_hunks(ADD_OWNED)
    assert len(hunks) == 1
    file, added = hunks[0]
    assert file == "tests/test_orders.py" and len(added) == 3


def test_repo_ratchet_count(cli, tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_a.py").write_text("@pytest.mark.skip\ndef test_a(): ...\n@flaky\ndef test_b(): ...\n")
    count = cli.flaky_marker_repo_count(tmp_path, _markers(cli), "tests")
    assert count == 2


def test_repo_ratchet_disabled_when_no_scan_path(cli, tmp_path):
    assert cli.flaky_marker_repo_count(tmp_path, _markers(cli), "") == 0


def test_normalize_flaky_quarantine(cli):
    with pytest.raises(SystemExit):
        cli.normalize_flaky_quarantine({"flakyQuarantine": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_flaky_quarantine({"flakyQuarantine": {"maxMarkers": "x"}})
    cfg = cli.normalize_flaky_quarantine({})
    assert cfg["enforcement"] == "warn" and cfg["maxMarkers"] == -1 and cfg["scanPath"] == ""
    assert cfg["markers"] == cli.FLAKY_QUARANTINE_MARKERS


def test_handler_block_mode_fails_on_unowned(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "DEFAULT_FLAKY_QUARANTINE", {**cli.DEFAULT_FLAKY_QUARANTINE, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(ADD_UNOWNED)
    rc = cli.flaky_quarantine_check(_ns(target=tmp_path, diff_file=diff))
    assert rc == 1
    assert "flaky_quarantine_issue" in capsys.readouterr().out


def test_handler_warn_mode_does_not_block(cli, tmp_path):
    diff = tmp_path / "d.diff"
    diff.write_text(ADD_UNOWNED)
    rc = cli.flaky_quarantine_check(_ns(target=tmp_path, diff_file=diff))
    assert rc == 0


def test_handler_block_mode_passes_when_owned(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_FLAKY_QUARANTINE", {**cli.DEFAULT_FLAKY_QUARANTINE, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(ADD_OWNED)
    rc = cli.flaky_quarantine_check(_ns(target=tmp_path, diff_file=diff))
    assert rc == 0


def test_missing_diff_file_skips_not_crashes(cli, tmp_path, capsys):
    # P2 fix: a --diff-file that does not exist must skip cleanly, not raise FileNotFoundError.
    rc = cli.flaky_quarantine_check(_ns(target=tmp_path, diff_file=tmp_path / "nope.diff"))
    assert rc == 0
    assert "not found" in capsys.readouterr().out
