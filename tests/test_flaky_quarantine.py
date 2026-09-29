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


def test_normalize_flaky_quarantine(cli):
    with pytest.raises(SystemExit):
        cli.normalize_flaky_quarantine({"flakyQuarantine": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_flaky_quarantine({"flakyQuarantine": {"maxMarkers": "x"}})
    cfg = cli.normalize_flaky_quarantine({})
    assert cfg["enforcement"] == "warn" and cfg["maxMarkers"] == -1 and cfg["scanPath"] == ""
    assert cfg["markers"] == cli.FLAKY_QUARANTINE_MARKERS
