"""Quality rec #7 Part 2: diff-scoped coverage gate.

Whole-repo `fail_under` (rec #7 Part 1) is a coarse backstop -- a large untested module barely moves
the aggregate, so new code can ship unexercised with the repo gate green (FM1). The `diff-coverage-check`
subcommand measures only the NEW lines a change adds (git diff) against a coverage report and fails when
their coverage is below coverageFloor.newCodeMinPct, blocking only when enforcement is block.
"""

import argparse

import pytest

SAMPLE_DIFF = """diff --git a/src/foo.py b/src/foo.py
index abc..def 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,0 +11,2 @@
+    new_line_eleven
+    new_line_twelve
@@ -20,1 +22,1 @@
-    old_twenty_two
+    changed_twenty_two
"""

NEW_FILE_DIFF = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,3 @@
+line_one
+line_two
+line_three
"""


def _ns(**kw):
    base = dict(project=None, target=None, base=None, report=None, min_pct=None, diff_file=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_normalize_coverage_floor(cli):
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"newCodeMinPct": 150}})
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"newCodeMinPct": "x"}})
    cfg = cli.normalize_coverage_floor({})
    assert cfg["enforcement"] == "warn" and cfg["newCodeMinPct"] == 80
    assert cfg["coverageReport"] == "coverage.json" and cfg["diffBase"] == "origin/main"
